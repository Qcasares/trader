"""
test_system_configuration.py
----------------------------
The configuration endpoints, against a real PostgreSQL database.

Skipped unless ``TEST_DATABASE_URL`` is set. What needs a database rather than a
unit test is everything about *stored* state: that migration 0010 seeds values
the runner can actually use, that the four model settings move together, and
that an unusable row makes the runner decline to call a model rather than fall
back to a default nobody chose.

    createdb trader_test
    TEST_DATABASE_URL=postgresql://localhost/trader_test \\
        pytest tests/integration/test_system_configuration.py
"""

from __future__ import annotations

import asyncio
import json
import os

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("asyncpg")

import asyncpg  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api.security import hash_password  # noqa: E402
from src.programme import flags as programme_flags  # noqa: E402
from src.programme import models  # noqa: E402

TEST_DSN = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DSN,
    reason="TEST_DATABASE_URL not set; skipping configuration integration tests",
)

PASSWORD = "test-password-123"

ENDPOINT = "/api/v1/system/configuration"


@pytest.fixture(scope="module")
def client():
    from src.config import get_settings
    from src.db.migrate import migrate

    os.environ["DATABASE_URL"] = TEST_DSN
    os.environ["SESSION_SECRET"] = "a" * 48
    os.environ["ADMIN_PASSWORD_HASH"] = hash_password(PASSWORD)
    get_settings.cache_clear()

    asyncio.run(migrate(TEST_DSN))

    from src.api.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def authed(client):
    assert (
        client.post("/api/v1/auth/login", json={"password": PASSWORD}).status_code
        == 200
    )
    return client


def _run(coro):
    return asyncio.run(coro)


async def _with_conn(fn):
    conn = await asyncpg.connect(TEST_DSN)
    try:
        return await fn(conn)
    finally:
        await conn.close()


def _defaults() -> dict:
    return {
        "provider": models.ANTHROPIC,
        "model": models.DEFAULT_MODEL,
        "effort": models.DEFAULT_EFFORT,
        "max_tokens": models.DEFAULT_MAX_TOKENS,
        "tick_seconds": models.DEFAULT_TICK_SECONDS,
    }


@pytest.fixture(autouse=True)
def restore_defaults(authed):
    """
    Every test leaves the deployment on the seeded defaults.

    Ordering matters more here than in most fixtures: these rows are read by the
    runner, and a test that left a deployment pointed at a model nobody chose
    would be a test that changed production behaviour.
    """
    yield
    authed.post(ENDPOINT, json=_defaults())


class TestTheMigrationSeedsSomethingUsable:
    def test_a_fresh_deployment_can_call_a_model(self, authed) -> None:
        """
        The seeded values are not decoration. If they do not validate, the
        programme reconciles and promotes but never proposes, and the only sign
        is a line in a log.
        """
        body = authed.get(ENDPOINT).json()
        assert body["usable"] is True
        assert body["settings_problem"] is None
        assert body["tick_problem"] is None

    def test_the_runner_reads_back_what_the_migration_wrote(self, authed) -> None:
        settings = _run(_with_conn(programme_flags.model_settings))
        assert settings is not None
        assert settings.model == models.DEFAULT_MODEL
        assert settings.effort == models.DEFAULT_EFFORT

    def test_the_seeded_values_are_marked_as_the_migration_s(self, authed) -> None:
        """
        So the page can say these are defaults nobody has reviewed, which is a
        different thing from a choice somebody made.
        """
        body = authed.get(ENDPOINT).json()
        provenance = body["provenance"]
        assert set(provenance) == set(programme_flags.SETTING_KEYS)


class TestSettingIt:
    def test_a_valid_change_is_stored_and_read_back(self, authed) -> None:
        body = _defaults() | {"model": "claude-opus-5", "effort": "low"}
        response = authed.post(ENDPOINT, json=body)
        assert response.status_code == 200
        assert response.json()["stored"]["model"] == "claude-opus-5"

        settings = _run(_with_conn(programme_flags.model_settings))
        assert settings is not None
        assert (settings.model, settings.effort) == ("claude-opus-5", "low")

    def test_the_operator_is_recorded_in_the_audit_log(self, authed) -> None:
        authed.post(ENDPOINT, json=_defaults() | {"effort": "medium"})

        async def latest(conn):
            return await conn.fetchrow(
                "SELECT actor, action FROM audit_log "
                "WHERE action = 'system_configuration_updated' "
                "ORDER BY at DESC LIMIT 1"
            )

        row = _run(_with_conn(latest))
        assert row is not None
        assert row["actor"].startswith("operator:")

    def test_an_effort_the_model_rejects_is_a_422(self, authed) -> None:
        """
        Refused at the form rather than at the vendor. The alternative is a 400
        on every tick from then on, discovered in a log.
        """
        haiku = next(c for c in models.MODELS if not c.efforts)
        opus = models.MODELS_BY_ID["claude-opus-5"]
        rejected = set(models.EFFORT_LEVELS) - set(opus.efforts)
        if not rejected:
            pytest.skip("no effort level is rejected by this model")
        response = authed.post(
            ENDPOINT, json=_defaults() | {"model": opus.id, "effort": rejected.pop()}
        )
        assert response.status_code == 422
        # And the effortless model is still selectable, because the stored
        # effort is simply not sent for it.
        assert (
            authed.post(ENDPOINT, json=_defaults() | {"model": haiku.id}).status_code
            == 200
        )

    def test_an_unavailable_provider_is_a_422_naming_what_is_missing(
        self, authed
    ) -> None:
        unavailable = next(p for p in models.PROVIDERS if not p.available)
        response = authed.post(
            ENDPOINT, json=_defaults() | {"provider": unavailable.key}
        )
        assert response.status_code == 422
        assert "not available" in response.json()["detail"]

    def test_a_ceiling_above_the_model_is_a_422(self, authed) -> None:
        choice = models.MODELS_BY_ID[models.DEFAULT_MODEL]
        response = authed.post(
            ENDPOINT, json=_defaults() | {"max_tokens": choice.max_output + 1}
        )
        assert response.status_code == 422

    def test_a_one_second_cadence_is_a_422(self, authed) -> None:
        response = authed.post(ENDPOINT, json=_defaults() | {"tick_seconds": 1})
        assert response.status_code == 422

    def test_an_unknown_field_is_refused(self, authed) -> None:
        """
        ``extra="forbid"``, for the same reason the risk limits forbid one: a
        mistyped field that is silently dropped leaves the operator looking at a
        page that says saved and a runner that never saw it.
        """
        response = authed.post(ENDPOINT, json=_defaults() | {"temperature": 0.7})
        assert response.status_code == 422

    def test_a_refused_change_stores_nothing(self, authed) -> None:
        """
        The four settings move together or not at all. Half-applied they
        describe a request nobody chose — a new model with the old model's
        effort level, which is exactly the pairing that errors.
        """
        before = authed.get(ENDPOINT).json()["stored"]
        authed.post(
            ENDPOINT,
            json=_defaults() | {"model": "claude-opus-5", "tick_seconds": 1},
        )
        assert authed.get(ENDPOINT).json()["stored"] == before

    def test_an_unauthenticated_caller_cannot_change_it(self, client) -> None:
        client.post("/api/v1/auth/logout")
        assert client.post(ENDPOINT, json=_defaults()).status_code == 401


class TestItFailsClosed:
    def test_an_unusable_row_means_no_model_call(self, authed) -> None:
        """
        The important one.

        A stored value the runner refuses must produce *no model call*, not a
        fallback to the module default. Falling back would spend money at a
        vendor under a configuration nobody chose and write the result into the
        ledger as though somebody had. The runner is not paralysed without a
        model: it still reconciles, evaluates gates and promotes.
        """

        async def corrupt(conn):
            await conn.execute(
                "UPDATE system_flags SET value = $2::jsonb WHERE key = $1",
                programme_flags.PROGRAMME_MODEL,
                json.dumps("claude-imaginary-9"),
            )

        _run(_with_conn(corrupt))
        assert _run(_with_conn(programme_flags.model_settings)) is None

        body = authed.get(ENDPOINT).json()
        assert body["usable"] is False
        assert "unknown model" in body["settings_problem"]

    def test_a_missing_row_means_no_model_call(self, authed) -> None:
        """
        The migration seeds all four, so an absent one means something removed
        it. Inventing a replacement is how a deleted setting stops looking like
        a deleted setting.
        """

        async def delete(conn):
            await conn.execute(
                "DELETE FROM system_flags WHERE key = $1",
                programme_flags.PROGRAMME_EFFORT,
            )

        _run(_with_conn(delete))
        assert _run(_with_conn(programme_flags.model_settings)) is None

    def test_the_cadence_fails_slow_rather_than_closed(self, authed) -> None:
        """
        The one setting that does *not* fail closed, and deliberately.

        An unreadable cadence that halted the loop would take the programme down
        over a formatting mistake, while an unreadable cadence that ticks hourly
        costs at most one pass an hour — and every pass is still gated by
        ``programme_enabled`` and by ``model_settings``, both of which fail
        closed. Failing slow is the conservative direction for a cadence.
        """

        async def corrupt(conn):
            await conn.execute(
                "UPDATE system_flags SET value = $2::jsonb WHERE key = $1",
                programme_flags.PROGRAMME_TICK_SECONDS,
                json.dumps("hourly"),
            )

        _run(_with_conn(corrupt))
        assert (
            _run(_with_conn(programme_flags.tick_seconds))
            == models.DEFAULT_TICK_SECONDS
        )
