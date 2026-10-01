"""
test_jev_research_over_http.py
------------------------------
One stored web excerpt screened and described end to end, with nothing
replaced but the vendor.

``tests/integration/test_jev_research.py`` drives phases C7 and C8 through the
programme's loop against a fake of ``jev_client.ask``. This drives the shipped
planner and the shipped ``jev_ask`` handler through the lane, the real client,
the real ``typesafe_sdk`` and ``httpx2``, real HTTP to the fake TypeSafe server
in ``conftest.py``, the validator and the ledger on a real Postgres: the
injection screen asked about a document's excerpt, and only once it has
cleared it, the catalogue — each request exactly the state the screen judged,
``{"excerpt": …}`` and nothing else — and the screen asked again replayed from
its row, with no request leaving at all.

The handler calls ``jev_lane.ask`` through the module attribute with every
keyword spelled and no transport; the transport is bound here by replacing
that attribute with the real ``ask`` given the test's transport, which is the
one thing that differs from production.

Needs both the SDK and a database: skipped without ``typesafe_sdk`` and without
``TEST_DATABASE_URL``. Runs on a database of its own, since the ledger refuses
DELETE. The excerpt is invented: the catalogue it stands for publishes no
licence.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

pytest.importorskip("typesafe_sdk")

import asyncpg  # noqa: E402

from src.db import migrate as migrations  # noqa: E402
from src.db.repos import flags as flag_repo  # noqa: E402
from src.programme import (  # noqa: E402
    flags,
    jev_catalogue,
    jev_jobs,
    jev_lane,
    jev_plan,
    jev_prereg,
    jev_repo,
    web_sources,
)
from src.programme.jev_hash import text_sha256  # noqa: E402
from src.programme.jev_questions import (  # noqa: E402
    GUARDRAIL_INJECTION,
    RESEARCH_CATALOGUE,
)
from tests.sdk.conftest import ENDPOINT, FakeTypeSafe, Redirect, Reply  # noqa: E402

TEST_DSN = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = [
    pytest.mark.sdk,
    pytest.mark.skipif(not TEST_DSN, reason="TEST_DATABASE_URL not set"),
]

MODEL = jev_catalogue.DEFAULT_MODEL
KEY = "ts-test-key-not-a-secret"
EXCERPT = "Quiet Momentum in Invented Mid-Cap Shares"


def _own_dsn() -> str:
    base, _, tail = TEST_DSN.partition("?")
    return f"{base}_jev_research_sdk?{tail}" if tail else f"{base}_jev_research_sdk"


@pytest.fixture(scope="module")
def dsn() -> str:
    async def setup() -> str:
        name = _own_dsn().partition("?")[0].rsplit("/", 1)[-1]
        admin = await asyncpg.connect(TEST_DSN)
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            await admin.execute(f'CREATE DATABASE "{name}"')
        finally:
            await admin.close()
        await migrations.migrate(_own_dsn())
        return _own_dsn()

    return asyncio.run(setup())


@pytest.fixture
async def conn(dsn: str) -> AsyncIterator[asyncpg.Connection]:
    """The programme, Jev and both areas the asks need on, every setting seeded."""
    connection = await asyncpg.connect(dsn)
    try:
        for key, value in {
            flags.PROGRAMME_ENABLED: True,
            flags.JEV_ENABLED: True,
            f"{flags.JEV_AREA_PREFIX}research": True,
            f"{flags.JEV_AREA_PREFIX}guardrails": True,
            flags.JEV_MODEL: MODEL,
            flags.JEV_DAILY_REQUEST_BUDGET: jev_catalogue.DEFAULT_DAILY_REQUEST_BUDGET,
            flags.JEV_MAX_STATE_TOKENS: jev_catalogue.DEFAULT_MAX_STATE_TOKENS,
        }.items():
            await flag_repo.set_flag(connection, key, value, "test")
        yield connection
    finally:
        await connection.close()


@pytest.fixture
def routed(monkeypatch: pytest.MonkeyPatch, transport: Redirect) -> Redirect:
    """``jev_lane.ask`` as shipped, handed the test's transport."""
    real = jev_lane.ask

    async def ask(conn: Any, **kwargs: Any) -> jev_lane.AskResult:
        assert "transport" not in kwargs, "the handler passed a transport itself"
        return await real(conn, **kwargs, transport=transport)

    monkeypatch.setattr(jev_lane, "ask", ask)
    return transport


def _reply(answers: dict[str, Any], request_id: str) -> Reply:
    body = {
        "model": MODEL,
        "answers": answers,
        "usage": {"input_tokens": 300, "output_tokens": 1},
    }
    return Reply(
        status=200,
        body=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "x-typesafe-request-id": request_id,
        },
    )


def _choice(question: dict[str, Any]) -> dict[str, Any]:
    """The first option at 0.64, the rest sharing what is left."""
    options = list(question["criteria"])
    rest = round(0.36 / (len(options) - 1), 4)
    probabilities = dict.fromkeys(options, rest)
    probabilities[options[0]] = round(1 - rest * (len(options) - 1), 4)
    return {
        "type": "choice",
        "choice": options[0],
        "confidence": 0.5,
        "probabilities": probabilities,
    }


async def _ask_job(conn: asyncpg.Connection, name: str) -> dict[str, Any]:
    (row,) = await conn.fetch(
        "SELECT payload FROM jobs WHERE kind = 'jev_ask' AND payload->>'set' = $1",
        name,
    )
    return json.loads(row["payload"])


class TestOneDocumentScreenedAndDescribed:
    async def test_the_screen_then_the_catalogue_over_http(
        self, conn: asyncpg.Connection, server: FakeTypeSafe, routed: Redirect
    ) -> None:
        await jev_repo.insert_documents(
            conn,
            [
                jev_repo.DocumentRow(
                    source="pwb-readme",
                    url=web_sources.as_written(
                        web_sources.ALLOWED_SOURCES["pwb-readme"]
                    ).url,
                    excerpt=EXCERPT,
                )
            ],
        )
        questions = RESEARCH_CATALOGUE.as_request_questions()
        server.script(
            _reply({"addressed_to_ai": {"type": "noul", "noul": 0.04}}, "req_screen"),
            _reply(
                {key: _choice(question) for key, question in questions.items()},
                "req_catalogue",
            ),
        )
        now = datetime.now(UTC)

        await jev_plan.plan(conn, now=now, key_available=True)
        screen_payload = await _ask_job(conn, GUARDRAIL_INJECTION.name)
        assert (
            await conn.fetchval(
                "SELECT COUNT(*) FROM jobs WHERE payload->>'set' = $1",
                RESEARCH_CATALOGUE.name,
            )
            == 0
        ), "the catalogue was planned before the screen cleared the text"
        screened = await jev_jobs.run_ask(conn, screen_payload, KEY)
        assert screened["status"] == "ok" and screened["replayed"] is False
        assert screened["answers"]["addressed_to_ai"]["argmax"] == "false"
        assert screened["plan_hash"] == jev_prereg.GOLDEN_PLAN_HASH

        await jev_plan.plan(conn, now=now + timedelta(minutes=1), key_available=True)
        catalogue_payload = await _ask_job(conn, RESEARCH_CATALOGUE.name)
        described = await jev_jobs.run_ask(conn, catalogue_payload, KEY)
        assert described["status"] == "ok"
        assert set(described["answers"]) == {"asset_class", "mechanism"}
        assert all(answer["valid"] for answer in described["answers"].values())

        first, second = routed.sent
        assert first.url == second.url == ENDPOINT
        for sent in (first, second):
            wire = json.loads(sent.body)
            assert wire["model"] == MODEL
            assert wire["state"] == {"excerpt": EXCERPT}
        assert list(json.loads(first.body)["questions"]) == ["addressed_to_ai"]
        assert list(json.loads(second.body)["questions"]) == [
            "asset_class",
            "mechanism",
        ]

        for result, name in (
            (screened, GUARDRAIL_INJECTION.name),
            (described, RESEARCH_CATALOGUE.name),
        ):
            row = await jev_repo.get_request(conn, result["request_id"])
            assert (row["question_set"], row["status"]) == (name, "ok")
            assert (row["subject_type"], row["subject_id"]) == (
                "web_excerpt",
                text_sha256(EXCERPT),
            )
            assert row["http_status"] == 200 and row["model_answered"] == MODEL
        assert described["request_id"] > screened["request_id"]

        again = await jev_jobs.run_ask(conn, screen_payload, KEY)
        assert again["replayed"] is True
        assert again["request_id"] == screened["request_id"]
        assert len(routed.sent) == len(server.received) == 2, (
            "the screen asked again sent a request"
        )
