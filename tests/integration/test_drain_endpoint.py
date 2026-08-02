"""
test_drain_endpoint.py
----------------------
``POST /api/v1/system/drain`` against a real database.

This endpoint exists because a serverless host cannot run a worker: every
invocation is created for a request and destroyed after it, so a submitted
backtest would sit queued forever with the UI honestly reporting "waiting for
a worker" and nothing ever arriving.

It is also the one endpoint that consumes real CPU on demand, and the one that
relaxes "the API never runs a backtest inline". Both of those need holding
down, so the tests here are about *refusal* as much as about the happy path:
disabled by default, never anonymous, and research jobs only.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import date

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("asyncpg")

import asyncpg  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api.security import hash_password  # noqa: E402

TEST_DSN = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DSN, reason="TEST_DATABASE_URL not set; skipping drain integration tests"
)

PASSWORD = "drain-test-password"
CRON_SECRET = "cron-secret-for-tests"


def _client(**env: str) -> TestClient:
    from src.config import get_settings
    from src.db.migrate import migrate

    os.environ["DATABASE_URL"] = TEST_DSN
    os.environ["SESSION_SECRET"] = "n" * 48
    os.environ["ADMIN_PASSWORD_HASH"] = hash_password(PASSWORD)
    os.environ.pop("SERVERLESS_DRAIN_ENABLED", None)
    os.environ.pop("CRON_SECRET", None)
    for key, value in env.items():
        os.environ[key] = value
    get_settings.cache_clear()

    asyncio.run(migrate(TEST_DSN))

    from src.api.main import create_app

    return TestClient(create_app())


@pytest.fixture
def enabled():
    with _client(SERVERLESS_DRAIN_ENABLED="true", CRON_SECRET=CRON_SECRET) as c:
        c.post("/api/v1/auth/login", json={"password": PASSWORD})
        yield c


@pytest.fixture
def disabled():
    with _client() as c:
        c.post("/api/v1/auth/login", json={"password": PASSWORD})
        yield c


class TestDisabledByDefault:
    def test_drain_is_404_when_not_enabled(self, disabled) -> None:
        """
        404, not 403: on a deployment with a worker this endpoint genuinely
        does not exist as a capability, and saying "forbidden" would imply
        there is something here to get permission for.
        """
        response = disabled.post("/api/v1/system/drain")
        assert response.status_code == 404
        assert "worker" in response.json()["detail"]


class TestItIsNeverAnonymous:
    def test_no_credential_is_refused(self, enabled) -> None:
        enabled.cookies.clear()
        assert enabled.post("/api/v1/system/drain").status_code == 401

    def test_a_wrong_bearer_is_refused(self, enabled) -> None:
        enabled.cookies.clear()
        response = enabled.post(
            "/api/v1/system/drain", headers={"Authorization": "Bearer nope"}
        )
        assert response.status_code == 401

    def test_the_cron_secret_is_accepted(self, enabled) -> None:
        enabled.cookies.clear()
        response = enabled.post(
            "/api/v1/system/drain",
            headers={"Authorization": f"Bearer {CRON_SECRET}"},
        )
        assert response.status_code == 200

    def test_a_get_is_accepted_because_vercel_cron_sends_one(self, enabled) -> None:
        # Not an endorsement of mutating GETs. Vercel Cron issues a GET and
        # offers no way to change that; an endpoint the scheduler cannot call
        # is not a scheduled job.
        enabled.cookies.clear()
        response = enabled.get(
            "/api/v1/system/drain",
            headers={"Authorization": f"Bearer {CRON_SECRET}"},
        )
        assert response.status_code == 200

    def test_an_operator_session_is_accepted(self, enabled) -> None:
        # Already logged in by the fixture; no bearer token presented.
        assert enabled.post("/api/v1/system/drain").status_code == 200


class TestItActuallyRunsTheWork:
    def test_a_queued_backtest_completes_with_no_worker(self, enabled) -> None:
        """
        The whole point. No worker process exists in this test — only the API —
        so if the run reaches 'succeeded' the drain is what ran it.
        """
        created = enabled.post(
            "/api/v1/backtests",
            json={
                "strategy": "asset_class_trend_following",
                "start": "2018-01-01",
                "end": "2020-12-31",
                "data_source": "synthetic",
            },
        )
        assert created.status_code == 202, created.text
        run_id = created.json()["run_id"]

        assert enabled.get(f"/api/v1/backtests/{run_id}").json()["status"] == "queued"

        result = enabled.post("/api/v1/system/drain").json()
        assert result["ran"] >= 1

        run = enabled.get(f"/api/v1/backtests/{run_id}").json()
        assert run["status"] == "succeeded", run.get("error")
        # And it produced a real result, with its honesty fields populated.
        assert run["metrics"]["n_sessions"] > 500
        assert run["metrics"]["sharpe_stderr"] > 0
        assert run["metrics"]["periods_per_year"] == 252

    def test_draining_an_empty_queue_is_a_no_op(self, enabled) -> None:
        enabled.post("/api/v1/system/drain")  # clear anything outstanding
        assert enabled.post("/api/v1/system/drain").json()["ran"] == 0


class TestTradingJobsAreNotDrainable:
    def test_a_queued_submit_orders_job_is_left_alone(self, enabled) -> None:
        """
        The boundary that matters. A drainable trading job would let an HTTP
        request place an order, routing around the kill-switch check and the
        three live gates that make the worker/API split meaningful.
        """

        job_id = uuid.uuid4()

        # Each helper owns its connection for the life of one `asyncio.run`.
        # Holding one across two closes the loop it was bound to.
        async def enqueue() -> None:
            conn = await asyncpg.connect(TEST_DSN)
            try:
                await conn.execute(
                    "INSERT INTO jobs (id, kind, payload, status) "
                    "VALUES ($1, 'submit_orders', $2::jsonb, 'queued')",
                    job_id,
                    f'{{"session": "{date(2021, 6, 1).isoformat()}"}}',
                )
            finally:
                await conn.close()

        async def status_of() -> str:
            conn = await asyncpg.connect(TEST_DSN)
            try:
                return await conn.fetchval(
                    "SELECT status FROM jobs WHERE id = $1", job_id
                )
            finally:
                await conn.close()

        asyncio.run(enqueue())

        result = enabled.post("/api/v1/system/drain").json()
        assert all(j["kind"] != "submit_orders" for j in result["jobs"])

        assert asyncio.run(status_of()) == "queued", (
            "a trading job was touched by the drain; only a worker may run "
            "anything that can reach a venue"
        )
