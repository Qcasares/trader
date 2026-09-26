"""
test_jev_lane_over_http.py
--------------------------
One Jev call end to end, with nothing replaced but the vendor.

Every other Phase B suite holds a fake on one side. ``tests/unit/test_jev_lane.py``
and ``tests/integration/test_jev_lane.py`` drive the lane against a fake of
``jev_client.ask``; ``test_jev_client.py`` beside this drives the real client
and the real SDK, and stops at the ``JevCall`` it returns. Each fake is a
reading of what the other side produces, and a reading can be wrong in a way
both suites agree on. So this drives the shipped chain whole — the lane, the
client, the real ``typesafe_sdk`` and ``httpx2``, real HTTP to the fake
TypeSafe server in ``conftest.py``, the validator, and the ledger on a real
Postgres — and asserts on the two ends: the request as it left, and the row it
became.

The properties are the ones the phase exists to deliver. The request hash on
the row recomputes from the request that left, so a replay is found by what was
actually asked. The body on the row is the body that arrived, byte for byte. A
second identical ask is answered from that row with no request at all. A
failure the SDK raises for still becomes a row carrying exactly the evidence it
had. And a probe asks every time, and is never the answer anybody replays.

Needs both the SDK and a database: skipped without ``typesafe_sdk``, which only
``requirements-programme.lock`` installs, and without ``TEST_DATABASE_URL``.
CI's ``programme sdk`` job has both. Runs on a database of its own, derived
from ``TEST_DATABASE_URL`` as ``tests/integration/test_jev_lane.py`` derives
``_jev_lane``, because the ledger refuses DELETE and TRUNCATE and so what is
written here could not be cleared from a shared one. For the same reason each
test asks about a state no other test uses.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest

pytest.importorskip("typesafe_sdk")

import asyncpg  # noqa: E402

from src.db import migrate as migrations  # noqa: E402
from src.db.repos import flags as flag_repo  # noqa: E402
from src.programme import (  # noqa: E402
    flags,
    jev_catalogue,
    jev_lane,
    jev_repo,
)
from src.programme.jev_questions import (  # noqa: E402
    DECISION_REGIME,
    RegimeState,
    SleeveState,
)
from tests.sdk.conftest import (  # noqa: E402
    ENDPOINT,
    FakeTypeSafe,
    Redirect,
    Reply,
    Route,
    closed_port,
)

TEST_DSN = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = [
    pytest.mark.sdk,
    pytest.mark.skipif(not TEST_DSN, reason="TEST_DATABASE_URL not set"),
]

MODEL = jev_catalogue.DEFAULT_MODEL
KEY = "ts-test-key-not-a-secret"
REQUEST_ID = "req_0e2e5a1c"
AS_OF = datetime(2026, 9, 25, 20, 0, tzinfo=UTC)
REGIME_OPTIONS = list(DECISION_REGIME.as_request_questions()["regime"]["criteria"])


# ---------------------------------------------------------------------------
# The database
# ---------------------------------------------------------------------------


def _own_dsn() -> str:
    base, _, tail = TEST_DSN.partition("?")
    return f"{base}_jev_lane_sdk?{tail}" if tail else f"{base}_jev_lane_sdk"


@pytest.fixture(scope="module")
def dsn() -> str:
    async def setup() -> str:
        # The name comes from before the query string: a Unix-socket DSN puts
        # the socket path after it.
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
    """Jev switched on for the decision set, every setting at its seed."""
    connection = await asyncpg.connect(dsn)
    try:
        for key, value in {
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


@pytest.fixture(autouse=True)
def _the_environment_points_elsewhere(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    What the SDK would read if the client let it: another host, an alias. Set
    for every test, so each proves again that the whole chain ignores both.
    """
    monkeypatch.setenv("TYPESAFE_BASE_URL", "https://evil.example")
    monkeypatch.setenv("TYPESAFE_DEFAULT_MODEL", "jev-latest")


# ---------------------------------------------------------------------------
# States, answers and asking
# ---------------------------------------------------------------------------


def _state(trend: str, quintile: int, drawdown: str, momentum: str) -> RegimeState:
    """One sleeve's descriptors for all three: a state no other test asks about."""
    sleeve = SleeveState(
        trend=trend,
        volatility_quintile=quintile,
        drawdown=drawdown,
        momentum=momentum,
    )
    return RegimeState(equities=sleeve, bonds=sleeve, commodities=sleeve)


def _regime_body(**replaced: Any) -> bytes:
    """A well-formed answer to the regime set, top-level fields replaced."""
    body: dict[str, Any] = {
        "model": MODEL,
        "answers": {
            "regime": {
                "type": "choice",
                "choice": "risk_off",
                "confidence": 0.6,
                "probabilities": dict(
                    zip(REGIME_OPTIONS, (0.05, 0.15, 0.7, 0.1), strict=True)
                ),
            }
        },
        "usage": {"input_tokens": 900, "output_tokens": 1},
    }
    body.update(replaced)
    return json.dumps(body).encode()


def _reply(body: bytes, *, status: int = 200) -> Reply:
    return Reply(
        status=status,
        body=body,
        headers={
            "Content-Type": "application/json",
            "x-typesafe-request-id": REQUEST_ID,
        },
    )


def _keys_sorted(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _keys_sorted(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_keys_sorted(item) for item in value]
    return value


def _sha256(value: Any) -> str:
    text = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hashes_of(wire: dict[str, Any]) -> tuple[str, str]:
    """
    The request and state hashes of a request as it left, from their written
    definition (docs/08, the spec's lane step 4) rather than from
    ``jev_lane``: the state's keys sorted, the questions and their options in
    the order sent, compact, UTF-8. Recomputed with the lane's own function, a
    change to that function would agree with itself.
    """
    state = _keys_sorted(wire["state"])
    request = {"model": wire["model"], "state": state, "questions": wire["questions"]}
    return _sha256(request), _sha256(state)


async def _ask(
    conn: asyncpg.Connection, transport: Redirect, state: RegimeState
) -> jev_lane.AskResult:
    return await jev_lane.ask(
        conn,
        question_set=DECISION_REGIME,
        state=state,
        subject_type="session",
        subject_id="2026-09-25",
        as_of=AS_OF,
        api_key=KEY,
        transport=transport,
    )


# ---------------------------------------------------------------------------
# The tests
# ---------------------------------------------------------------------------


class TestOneCallEndToEnd:
    async def test_the_row_is_the_request_that_left_and_the_body_that_arrived(
        self, conn: asyncpg.Connection, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        body = _regime_body()
        server.script(_reply(body))

        result = await _ask(conn, transport, _state("below", 5, "severe", "down"))

        assert result.status == "ok", result
        assert not result.replayed
        (sent,) = transport.sent
        assert sent.url == ENDPOINT
        wire = json.loads(sent.body)
        assert wire["model"] == MODEL
        assert list(wire["questions"]["regime"]["criteria"]) == REGIME_OPTIONS

        row = await jev_repo.get_request(conn, result.request_row_id)
        assert row is not None
        # The replay key is the hash of what left, not of what the lane meant
        # to send: recomputed here from the wire, in the wire's own order.
        assert (row["request_hash"], row["state_hash"]) == _hashes_of(wire)
        assert row["state"] == wire["state"]
        assert list(row["questions"]["regime"]["criteria"]) == REGIME_OPTIONS
        assert row["raw_body"] == body.decode()
        assert row["vendor_request_id"] == REQUEST_ID
        assert row["http_status"] == 200
        assert row["model_requested"] == row["model_answered"] == MODEL
        assert (row["input_tokens"], row["output_tokens"]) == (900, 1)
        assert row["error_kind"] is None
        assert row["lane"] == "decision" and row["provenance"] == "internal"
        assert row["pack_hash"] == DECISION_REGIME.pack_hash

        (answer,) = await jev_repo.answers_for(conn, row["id"])
        assert answer["valid"] is True
        assert answer["choice"] == answer["argmax"] == "risk_off"
        assert answer["margin"] == pytest.approx(0.55)
        assert result.answers["regime"].valid

    async def test_the_same_request_again_is_answered_from_the_row(
        self, conn: asyncpg.Connection, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        server.script(_reply(_regime_body()))
        state = _state("below", 4, "deep", "down")

        first = await _ask(conn, transport, state)
        again = await _ask(conn, transport, state)

        assert first.status == again.status == "ok"
        assert again.replayed
        assert again.request_row_id == first.request_row_id
        assert again.answers == first.answers
        assert len(transport.sent) == len(server.received) == 1, (
            "a replay sent a request: a second answer is not a check of the first"
        )


class TestAFailureIsARowWithTheEvidenceItHad:
    async def test_a_403_that_is_not_json_is_a_content_block(
        self, conn: asyncpg.Connection, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        waf = b"<html><body><h1>Request blocked</h1></body></html>"
        server.script(
            Reply(status=403, body=waf, headers={"Content-Type": "text/html"})
        )

        result = await _ask(conn, transport, _state("near", 3, "shallow", "flat"))

        assert (result.status, result.error_kind) == ("error", "content_block")
        row = await jev_repo.get_request(conn, result.request_row_id)
        assert row is not None
        assert row["http_status"] == 403
        assert row["raw_body"] == waf.decode()
        assert row["vendor_request_id"] is None, "no header came back"
        assert row["model_answered"] is None
        assert await jev_repo.answers_for(conn, row["id"]) == []

    async def test_no_response_at_all_leaves_no_evidence_and_still_spends(
        self, conn: asyncpg.Connection, transport: Redirect
    ) -> None:
        # Both attempts, the first and its one retry, find nothing listening.
        transport.routes.extend([Route(port=closed_port()), Route(port=closed_port())])
        spent = await jev_repo.requests_today(conn)

        result = await _ask(conn, transport, _state("near", 2, "none", "flat"))

        assert (result.status, result.error_kind) == ("error", "connection")
        assert len(transport.sent) == 2
        row = await jev_repo.get_request(conn, result.request_row_id)
        assert row is not None
        assert row["http_status"] is None
        assert row["raw_body"] is None and row["vendor_request_id"] is None
        assert await jev_repo.requests_today(conn) == spent + 1

    async def test_a_2xx_the_sdk_refuses_is_judged_by_the_validator(
        self, conn: asyncpg.Connection, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        # The SDK requires `usage`; the validator lets it decide nothing. The
        # validator's verdict is the status, and the SDK's objection is kept.
        answer = json.loads(_regime_body())
        del answer["usage"]
        raw = json.dumps(answer).encode()
        server.script(_reply(raw))

        result = await _ask(conn, transport, _state("above", 1, "none", "up"))

        row = await jev_repo.get_request(conn, result.request_row_id)
        assert row is not None
        assert (row["status"], row["error_kind"]) == ("ok", "response_shape")
        assert row["raw_body"] == raw.decode()
        assert (row["input_tokens"], row["output_tokens"]) == (None, None)

    async def test_an_answer_that_fails_a_rule_is_recorded_as_not_measured(
        self, conn: asyncpg.Connection, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        answer = json.loads(_regime_body())
        del answer["answers"]["regime"]["confidence"]
        server.script(_reply(json.dumps(answer).encode()))

        result = await _ask(conn, transport, _state("above", 2, "shallow", "up"))

        assert result.status == "ok"
        assert result.answers["regime"].valid is False
        (recorded,) = await jev_repo.answers_for(conn, result.request_row_id)
        assert recorded["valid"] is False
        assert recorded["invalid_reason"] == "confidence_invalid"


class TestTheProbe:
    async def test_it_asks_every_time_and_is_never_the_canonical_answer(
        self, conn: asyncpg.Connection, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        server.script(
            _reply(
                json.dumps(
                    {
                        "model": MODEL,
                        "answers": {"about_the_sun": {"type": "noul", "noul": 0.98}},
                        "usage": {"input_tokens": 41, "output_tokens": 1},
                    }
                ).encode()
            )
        )

        first = await jev_lane.run_probe(conn, KEY, transport=transport)
        second = await jev_lane.run_probe(conn, KEY, transport=transport)

        assert first["status"] == second["status"] == "ok"
        assert first["as_expected"] is second["as_expected"] is True
        assert len(server.received) == 2
        assert first["request_id"] != second["request_id"]
        row = await jev_repo.get_request(conn, first["request_id"])
        assert row is not None and row["lane"] == "probe"
        assert await jev_repo.find_canonical(conn, row["request_hash"]) is None
