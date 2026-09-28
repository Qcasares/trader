"""
test_jev_forward_over_http.py
-----------------------------
The forward clock's job end to end, with nothing replaced but the vendor.

``tests/integration/test_jev_forward.py`` drives the regime job against a fake
of ``jev_client.ask``. This drives the shipped handler, ``jev_forward.collect``,
through the shipped lane, the real client, the real ``typesafe_sdk`` and
``httpx2``, real HTTP to the fake TypeSafe server in ``conftest.py``, the
validator and the ledger on a real Postgres, into a signal row; and then the
next session, whose state is the same, into a second signal resting on the
same answer without a request leaving at all.

The handler calls ``jev_lane.ask`` through the module attribute with every
keyword spelled and no transport, as the transport-seam scan requires; the
transport is bound here by replacing that attribute with the real ``ask``
given the test's transport, which is the one thing that differs from
production.

Needs both the SDK and a database: skipped without ``typesafe_sdk`` and without
``TEST_DATABASE_URL``. Runs on a database of its own, since the ledger refuses
DELETE.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from typing import Any

import pytest

pytest.importorskip("typesafe_sdk")

import asyncpg  # noqa: E402

from src.db import migrate as migrations  # noqa: E402
from src.db.repos import flags as flag_repo  # noqa: E402
from src.programme import (  # noqa: E402
    flags,
    jev_catalogue,
    jev_clock,
    jev_forward,
    jev_lane,
    jev_repo,
)
from src.programme.jev_questions import DECISION_REGIME  # noqa: E402
from tests.fakes.reference_prices import (  # noqa: E402
    EXPECTED_STATE,
    forward_sessions,
    seed_reference_bars,
)
from tests.sdk.conftest import ENDPOINT, FakeTypeSafe, Redirect, Reply  # noqa: E402

TEST_DSN = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = [
    pytest.mark.sdk,
    pytest.mark.skipif(not TEST_DSN, reason="TEST_DATABASE_URL not set"),
]

MODEL = jev_catalogue.DEFAULT_MODEL
KEY = "ts-test-key-not-a-secret"
OPTIONS = list(DECISION_REGIME.as_request_questions()["regime"]["criteria"])


def _own_dsn() -> str:
    base, _, tail = TEST_DSN.partition("?")
    return f"{base}_jev_forward_sdk?{tail}" if tail else f"{base}_jev_forward_sdk"


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
    """The programme, Jev and the decisions area on, every setting at its seed."""
    connection = await asyncpg.connect(dsn)
    try:
        for key, value in {
            flags.PROGRAMME_ENABLED: True,
            flags.JEV_ENABLED: True,
            f"{flags.JEV_AREA_PREFIX}decisions": True,
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


def _regime_reply() -> Reply:
    body = {
        "model": MODEL,
        "answers": {
            "regime": {
                "type": "choice",
                "choice": "risk_on",
                "confidence": 0.6,
                "probabilities": dict(
                    zip(OPTIONS, (0.72, 0.18, 0.06, 0.04), strict=True)
                ),
            }
        },
        "usage": {"input_tokens": 700, "output_tokens": 1},
    }
    return Reply(
        status=200,
        body=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "x-typesafe-request-id": "req_forward_http",
        },
    )


def _payload(session: Any) -> dict[str, Any]:
    return {
        "session": session.isoformat(),
        "set": DECISION_REGIME.name,
        "version": DECISION_REGIME.version,
    }


class TestTheRegimeJobOverHttp:
    async def test_a_session_becomes_a_signal_and_the_next_replays_it(
        self, conn: asyncpg.Connection, server: FakeTypeSafe, routed: Redirect
    ) -> None:
        now = await jev_clock.database_now(conn)
        session, following = forward_sessions(now)
        await seed_reference_bars(conn, following)
        server.script(_regime_reply())

        first = await jev_forward.collect(conn, _payload(session), KEY)

        assert first["status"] == "measured" and first["value"] == "risk_on"
        assert first["inserted"] is True and first["replayed"] is False
        assert first["backfilled"] is False
        (sent,) = routed.sent
        assert sent.url == ENDPOINT
        wire = json.loads(sent.body)
        assert wire["model"] == MODEL
        assert wire["state"] == DECISION_REGIME.dump_state(EXPECTED_STATE)
        assert "2026" not in json.dumps(wire["state"]), "a date reached the state"
        request = await jev_repo.get_request(conn, first["request_id"])
        assert request["subject_id"] == session.isoformat()
        assert request["http_status"] == 200
        signal = await jev_repo.get_signal(
            conn,
            signal=jev_clock.regime_signal(DECISION_REGIME, "regime"),
            symbol=jev_clock.sleeve_symbol(),
            session=session,
        )
        (answer,) = await jev_repo.answers_for(conn, first["request_id"])
        assert signal["answer_id"] == answer["id"]
        assert signal["value"] == "risk_on" and signal["backfilled"] is False

        second = await jev_forward.collect(conn, _payload(following), KEY)

        assert second["replayed"] is True
        assert second["request_id"] == first["request_id"]
        assert len(routed.sent) == len(server.received) == 1, (
            "the next session in the same state sent a request"
        )
        again = await jev_repo.get_signal(
            conn,
            signal=jev_clock.regime_signal(DECISION_REGIME, "regime"),
            symbol=jev_clock.sleeve_symbol(),
            session=following,
        )
        assert again["answer_id"] == signal["answer_id"]

        rerun = await jev_forward.collect(conn, _payload(session), KEY)
        assert rerun["status"] == "recorded_before"
        assert len(server.received) == 1
