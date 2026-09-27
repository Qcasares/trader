"""
test_jev_lane.py
----------------
The Jev lane and the programme's job loop against real PostgreSQL.

``tests/unit/test_jev_lane.py`` drives every branch of the lane against fakes of
the ledger. This drives the shipped lane through the shipped ``jev_repo``
against the shipped schema, where the rules are the database's rather than a
fake's: one ask is one request row and its answers, stamped by the database; a
second identical ask is answered from that row with no call; a switch that is
off writes nothing; two writers racing for the canonical answer leave one; and
the programme's loop claims only its own job kinds, only while both of its
switches are on.

The client is a fake of ``jev_client.ask``: no key exists, and nothing here may
reach TypeSafe. The SDK's own tests, over real HTTP to a local server, are in
``tests/sdk``.

Runs on a database of its own, derived from ``TEST_DATABASE_URL`` the way
``test_deployment_enable_gate.py`` derives ``_enable``. It has to: the ledger
refuses DELETE and TRUNCATE, so what is written here could not be cleared from
a shared database afterwards. For the same reason each test asks about a state
no other test uses, and counts rows written after its own start.

Skipped unless ``TEST_DATABASE_URL`` is set.
"""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import json
import os
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

pytest.importorskip("asyncpg")

import asyncpg  # noqa: E402

from src import crypto  # noqa: E402
from src.config import get_settings  # noqa: E402
from src.db import migrate as migrations  # noqa: E402
from src.db.repos import flags as flag_repo  # noqa: E402
from src.db.repos import jobs as job_repo  # noqa: E402
from src.db.repos import secrets as secret_repo  # noqa: E402
from src.programme import (  # noqa: E402
    flags,
    jev_catalogue,
    jev_client,
    jev_lane,
    jev_questions,
    jev_repo,
)
from src.programme.jev_hash import text_sha256  # noqa: E402
from src.programme.jev_questions import (  # noqa: E402
    DECISION_REGIME,
    PROBE_CONNECTIVITY,
    SCREEN_QUESTION,
    SCREEN_SET_NAME,
    ProbeState,
    QuestionSet,
    RegimeState,
    SleeveState,
    WebExcerptState,
)
from src.programme.main import JEV_HANDLERS, Programme  # noqa: E402

TEST_DSN = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="TEST_DATABASE_URL not set")

MODEL = jev_catalogue.DEFAULT_MODEL
KEY = "ts-test-key-not-a-secret"
AS_OF = datetime(2026, 9, 25, 20, 0, tzinfo=UTC)
AREA_DECISIONS = f"{flags.JEV_AREA_PREFIX}decisions"
AREA_RESEARCH = f"{flags.JEV_AREA_PREFIX}research"
AREA_GUARDRAILS = f"{flags.JEV_AREA_PREFIX}guardrails"


# ---------------------------------------------------------------------------
# The database
# ---------------------------------------------------------------------------


def _derived(suffix: str) -> str:
    base, _, tail = TEST_DSN.partition("?")
    return f"{base}_{suffix}?{tail}" if tail else f"{base}_{suffix}"


def _lane_dsn() -> str:
    return _derived("jev_lane")


async def _drop(dsn: str) -> None:
    # The name comes from before the query string: a Unix-socket DSN puts the
    # socket path after it, and splitting the whole URL on "/" would return
    # that instead of the database.
    name = dsn.partition("?")[0].rsplit("/", 1)[-1]
    admin = await asyncpg.connect(TEST_DSN)
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        await admin.close()


async def _created(dsn: str) -> str:
    """``dsn``'s database, dropped if it was there, created and migrated."""
    await _drop(dsn)
    name = dsn.partition("?")[0].rsplit("/", 1)[-1]
    admin = await asyncpg.connect(TEST_DSN)
    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()
    await migrations.migrate(dsn)
    return dsn


@pytest.fixture(scope="module")
def dsn() -> str:
    return asyncio.run(_created(_lane_dsn()))


#: Every switch as a test starts: Jev on for the decision set, the programme
#: on, and the settings at their seeds. Each test changes what it is about.
BASELINE: dict[str, Any] = {
    flags.PROGRAMME_ENABLED: True,
    flags.JEV_ENABLED: True,
    **{f"{flags.JEV_AREA_PREFIX}{area}": False for area in jev_catalogue.AREAS},
    AREA_DECISIONS: True,
    flags.JEV_MODEL: MODEL,
    flags.JEV_DAILY_REQUEST_BUDGET: jev_catalogue.DEFAULT_DAILY_REQUEST_BUDGET,
    flags.JEV_MAX_STATE_TOKENS: jev_catalogue.DEFAULT_MAX_STATE_TOKENS,
}


@pytest.fixture
async def conn(dsn: str):
    """A connection with every switch at the baseline and the queue empty."""
    connection = await asyncpg.connect(dsn)
    try:
        for key, value in BASELINE.items():
            await flag_repo.set_flag(connection, key, value, "test")
        await connection.execute("DELETE FROM jobs")
        yield connection
    finally:
        await connection.close()


@pytest.fixture
async def fresh() -> AsyncIterator[tuple[str, asyncpg.Connection]]:
    """
    A database of the test's own, migrated, every switch at the baseline.

    For a test that records one of the vendor's standing refusals. An
    authentication failure holds every lane until 00:00 UTC and a 422 holds its
    set for good, both read from rows the ledger will not let anybody delete:
    recorded in the module's database, either would hold every test after it.
    """
    own = await _created(_derived("jev_lane_fresh"))
    connection = await asyncpg.connect(own)
    try:
        for key, value in BASELINE.items():
            await flag_repo.set_flag(connection, key, value, "test")
        yield own, connection
    finally:
        await connection.close()
        await _drop(own)


async def _set(conn: asyncpg.Connection, key: str, value: Any) -> None:
    await flag_repo.set_flag(conn, key, value, "test")


async def _watermark(conn: asyncpg.Connection) -> int:
    return await conn.fetchval("SELECT COALESCE(MAX(id), 0) FROM jev_requests")


async def _rows_since(conn: asyncpg.Connection, mark: int) -> list[asyncpg.Record]:
    return await conn.fetch(
        "SELECT * FROM jev_requests WHERE id > $1 ORDER BY id", mark
    )


# ---------------------------------------------------------------------------
# States no other test asks about
# ---------------------------------------------------------------------------


def _sleeves() -> Iterator[SleeveState]:
    for trend, quintile, drawdown, momentum in itertools.product(
        ("above", "near", "below"),
        (1, 2, 3, 4, 5),
        ("none", "shallow", "deep", "severe"),
        ("up", "flat", "down"),
    ):
        yield SleeveState(
            trend=trend,
            volatility_quintile=quintile,
            drawdown=drawdown,
            momentum=momentum,
        )


_UNUSED = _sleeves()


def _fresh_state() -> RegimeState:
    """A regime state no earlier test in this module has asked about."""
    sleeve = next(_UNUSED)
    return RegimeState(equities=sleeve, bonds=sleeve, commodities=sleeve)


# ---------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------


def _clean_answers(questions: dict[str, dict]) -> dict[str, Any]:
    answers: dict[str, Any] = {}
    for key, question in questions.items():
        if question["type"] == "noul":
            answers[key] = {"type": "noul", "noul": 0.97}
        else:
            options = list(question["criteria"])
            answers[key] = {
                "type": "choice",
                "choice": options[0],
                "confidence": 0.49,
                "probabilities": dict(
                    zip(options, (0.62, 0.21, 0.12, 0.05), strict=True)
                ),
            }
    return answers


def _body(answers: dict[str, Any], model: str = MODEL) -> str:
    return json.dumps(
        {
            "model": model,
            "answers": answers,
            "usage": {"input_tokens": 212, "output_tokens": 0},
        }
    )


def _call(status: int | None, body: str | None, **fields: Any) -> Any:
    values: dict[str, Any] = {
        "http_status": status,
        "raw_body": body,
        "request_id": "req_integration",
        "latency_ms": 131,
        "error_class": None,
        "error_kind": None,
        "input_tokens": 212 if status == 200 else None,
        "output_tokens": 0 if status == 200 else None,
        # The bytes as they arrived, which is what the validator reads.
        "wire_body": None if body is None else body.encode("utf-8"),
    }
    values.update(fields)
    return jev_client.JevCall(**values)


def _clean(**kwargs: Any) -> Any:
    return _call(200, _body(_clean_answers(kwargs["questions"])))


class _Client:
    """``jev_client.ask``, answering through ``respond``, counting calls."""

    def __init__(self, respond: Callable[..., Any] = _clean) -> None:
        self.respond = respond
        self.calls: list[dict[str, Any]] = []

    async def ask(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        result = self.respond(**kwargs)
        if asyncio.iscoroutine(result):
            result = await result
        return result


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> _Client:
    fake = _Client()
    monkeypatch.setattr(jev_client, "ask", fake.ask)
    return fake


async def _ask(
    conn: asyncpg.Connection,
    state: Any,
    question_set=DECISION_REGIME,
    api_key: str | None = KEY,
    **kwargs: Any,
) -> jev_lane.AskResult:
    # Each state model's own subject (jev_questions.STATE_SUBJECT): the probe's
    # fixed sentence is the probe, and a regime state describes a session.
    probing = question_set.lane == "probe"
    return await jev_lane.ask(
        conn,
        question_set=question_set,
        state=state,
        subject_type=kwargs.pop("subject_type", "probe" if probing else "session"),
        subject_id=kwargs.pop(
            "subject_id", "connectivity" if probing else "2026-09-25"
        ),
        as_of=AS_OF,
        api_key=api_key,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# One ask, one record; the second, a replay
# ---------------------------------------------------------------------------


class TestOneAskIsOneRecord:
    async def test_an_answer_is_one_request_row_and_its_answers(
        self, conn: asyncpg.Connection, client: _Client
    ) -> None:
        state = _fresh_state()
        mark = await _watermark(conn)
        before = await conn.fetchval("SELECT clock_timestamp()")

        result = await _ask(conn, state)

        after = await conn.fetchval("SELECT clock_timestamp()")
        assert len(client.calls) == 1
        (row,) = await _rows_since(conn, mark)
        assert result.status == "ok" and not result.replayed
        assert result.request_row_id == row["id"]
        assert row["status"] == "ok"
        assert row["lane"] == "decision" and row["provenance"] == "internal"
        assert row["question_set"] == "decision.regime"
        assert row["question_set_version"] == 1
        assert row["pack_hash"] == DECISION_REGIME.pack_hash
        assert row["model_requested"] == row["model_answered"] == MODEL
        assert row["http_status"] == 200
        assert row["raw_body"] == _body(
            _clean_answers(DECISION_REGIME.as_request_questions())
        )
        assert row["vendor_request_id"] == "req_integration"
        assert (row["input_tokens"], row["output_tokens"]) == (212, 0)
        assert row["latency_ms"] == 131
        assert row["as_of"] == AS_OF
        assert before <= row["available_at"] <= after
        assert row["requested_at"] <= row["available_at"]

        answers = await conn.fetch(
            "SELECT * FROM jev_answers WHERE request_id = $1 ORDER BY id", row["id"]
        )
        assert [a["question_key"] for a in answers] == ["regime"]
        (answer,) = answers
        assert answer["valid"] is True and answer["invalid_reason"] is None
        assert answer["choice"] == answer["argmax"] == "risk_on"
        assert answer["confidence"] == 0.49
        assert answer["margin"] == pytest.approx(0.41)
        assert json.loads(answer["probabilities"]) == {
            "risk_on": 0.62,
            "neutral": 0.21,
            "risk_off": 0.12,
            "insufficient_evidence": 0.05,
        }

    async def test_the_row_is_the_request(
        self, conn: asyncpg.Connection, client: _Client
    ) -> None:
        """
        What "record once, replay forever" rests on: the stored row recomputes
        its own hash, through the lane's definition and an independent one, so
        a replay can be checked against the request it claims to answer.
        """
        mark = await _watermark(conn)
        await _ask(conn, _fresh_state())
        stored = await jev_repo.get_request(
            conn, (await _rows_since(conn, mark))[0]["id"]
        )

        assert stored["request_hash"] == jev_lane.request_hash(
            stored["model_requested"], stored["state"], stored["questions"]
        )
        assert stored["state_hash"] == jev_lane.state_hash(stored["state"])
        body = {
            "model": stored["model_requested"],
            "state": json.loads(json.dumps(stored["state"], sort_keys=True)),
            "questions": stored["questions"],
        }
        text = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        assert stored["request_hash"] == hashlib.sha256(text.encode()).hexdigest()
        assert list(stored["questions"]["regime"]["criteria"]) == list(
            DECISION_REGIME.as_request_questions()["regime"]["criteria"]
        )

    async def test_the_second_ask_is_replayed_without_a_call(
        self, conn: asyncpg.Connection, dsn: str, client: _Client
    ) -> None:
        state = _fresh_state()
        first = await _ask(conn, state)
        mark = await _watermark(conn)

        # On a connection of its own: the replay reads the ledger, not memory.
        other = await asyncpg.connect(dsn)
        try:
            second = await _ask(other, state, api_key=None)
        finally:
            await other.close()

        assert len(client.calls) == 1, "the recorded answer was asked for again"
        assert await _rows_since(conn, mark) == [], "the replay wrote a row"
        assert second.replayed is True and second.status == "ok"
        assert second.request_row_id == first.request_row_id
        assert second.answers == first.answers
        assert list(second.answers["regime"].probabilities) == list(
            DECISION_REGIME.as_request_questions()["regime"]["criteria"]
        )


# ---------------------------------------------------------------------------
# Switched off, no model, no key: nothing written
# ---------------------------------------------------------------------------


class TestNothingIsWrittenWithoutARequest:
    @pytest.mark.parametrize(
        "key, value, status",
        [
            # The lane reads the programme's switch itself, on every ask.
            (flags.PROGRAMME_ENABLED, False, "disabled"),
            (flags.JEV_ENABLED, False, "disabled"),
            (AREA_DECISIONS, False, "disabled"),
            (flags.JEV_ENABLED, "true", "disabled"),
            (flags.JEV_MODEL, "jev-latest", "refused_model"),
        ],
    )
    async def test_a_switch_or_setting_that_says_no(
        self,
        conn: asyncpg.Connection,
        client: _Client,
        key: str,
        value: Any,
        status: str,
    ) -> None:
        await _set(conn, key, value)
        mark = await _watermark(conn)
        result = await _ask(conn, _fresh_state())
        assert result.status == status
        assert result.request_row_id is None
        assert client.calls == []
        assert await _rows_since(conn, mark) == []

    async def test_no_key(self, conn: asyncpg.Connection, client: _Client) -> None:
        mark = await _watermark(conn)
        result = await _ask(conn, _fresh_state(), api_key=None)
        assert result.status == "no_key"
        assert client.calls == [] and await _rows_since(conn, mark) == []


# ---------------------------------------------------------------------------
# Refused before sending: a row, no call
# ---------------------------------------------------------------------------


class TestARefusalIsRecordedAndSendsNothing:
    async def test_a_spent_budget(
        self, conn: asyncpg.Connection, client: _Client
    ) -> None:
        spent = await jev_repo.requests_today(conn)
        await _set(conn, flags.JEV_DAILY_REQUEST_BUDGET, spent)
        mark = await _watermark(conn)

        result = await _ask(conn, _fresh_state())

        assert client.calls == []
        (row,) = await _rows_since(conn, mark)
        assert result.status == "refused_budget"
        assert result.request_row_id == row["id"]
        assert row["status"] == "refused_budget"
        assert row["http_status"] is None and row["raw_body"] is None
        # Never sent, so dated by the database, and not counted as a call.
        assert row["requested_at"] is not None
        assert await jev_repo.requests_today(conn) == spent

    async def test_a_state_over_the_limit(
        self, conn: asyncpg.Connection, client: _Client
    ) -> None:
        await _set(conn, flags.JEV_MAX_STATE_TOKENS, 1)
        mark = await _watermark(conn)

        result = await _ask(conn, _fresh_state())

        assert client.calls == []
        (row,) = await _rows_since(conn, mark)
        assert result.status == row["status"] == "refused_limits"
        assert row["http_status"] is None


# ---------------------------------------------------------------------------
# A probe asks every time
# ---------------------------------------------------------------------------


class TestAProbeAlwaysAsks:
    async def test_probes_are_recorded_and_never_canonical(
        self, conn: asyncpg.Connection, client: _Client
    ) -> None:
        mark = await _watermark(conn)
        first = await _ask(conn, ProbeState(), PROBE_CONNECTIVITY)
        second = await _ask(conn, ProbeState(), PROBE_CONNECTIVITY)

        assert len(client.calls) == 2
        rows = await _rows_since(conn, mark)
        assert [r["status"] for r in rows] == ["ok", "ok"]
        assert {r["lane"] for r in rows} == {"probe"}
        assert rows[0]["request_hash"] == rows[1]["request_hash"]
        assert not first.replayed and not second.replayed
        assert await jev_repo.find_canonical(conn, rows[0]["request_hash"]) is None

    async def test_a_probe_of_a_recorded_request_asks_again(
        self, conn: asyncpg.Connection, client: _Client
    ) -> None:
        state = _fresh_state()
        canonical = await _ask(conn, state)
        probed = await _ask(conn, state, probe=True)

        assert len(client.calls) == 2
        assert probed.request_row_id != canonical.request_row_id
        row = await jev_repo.get_request(conn, probed.request_row_id)
        assert row["lane"] == "probe"
        found = await jev_repo.find_canonical(conn, row["request_hash"])
        assert found["id"] == canonical.request_row_id


# ---------------------------------------------------------------------------
# Two writers, one answer
# ---------------------------------------------------------------------------


class TestTheRaceForTheCanonicalAnswer:
    async def test_two_writers_leave_one_answer_and_both_read_it(
        self, conn: asyncpg.Connection, dsn: str, client: _Client
    ) -> None:
        """
        Both find nothing and both call, held at the client until both have;
        the index lets one write in and the other replays it.
        """
        both_called = asyncio.Event()

        async def respond(**kwargs: Any) -> Any:
            if len(client.calls) >= 2:
                both_called.set()
            await asyncio.wait_for(both_called.wait(), timeout=10)
            return _clean(**kwargs)

        client.respond = respond
        state = _fresh_state()
        mark = await _watermark(conn)
        first, second = await asyncpg.connect(dsn), await asyncpg.connect(dsn)
        try:
            results = await asyncio.gather(_ask(first, state), _ask(second, state))
        finally:
            await first.close()
            await second.close()

        assert len(client.calls) == 2
        rows = await _rows_since(conn, mark)
        assert [r["status"] for r in rows] == ["ok"], "two canonical answers"
        assert {r.request_row_id for r in results} == {rows[0]["id"]}
        assert sorted(r.replayed for r in results) == [False, True]
        assert results[0].answers == results[1].answers


# ---------------------------------------------------------------------------
# What arrived is what is recorded
# ---------------------------------------------------------------------------


class TestWhatArrivedIsWhatIsRecorded:
    async def test_a_response_refused_whole_is_recorded_and_asked_again(
        self, conn: asyncpg.Connection, client: _Client
    ) -> None:
        wrong_model = _body(
            _clean_answers(DECISION_REGIME.as_request_questions()), "jev-1.13.1"
        )
        client.respond = lambda **kw: _call(200, wrong_model)
        state = _fresh_state()
        mark = await _watermark(conn)

        refused = await _ask(conn, state)
        client.respond = _clean
        answered = await _ask(conn, state)

        rows = await _rows_since(conn, mark)
        assert [r["status"] for r in rows] == ["invalid", "ok"]
        assert rows[0]["model_answered"] == "jev-1.13.1"
        assert rows[0]["raw_body"] == wrong_model
        (answer,) = await conn.fetch(
            "SELECT valid, invalid_reason FROM jev_answers WHERE request_id = $1",
            rows[0]["id"],
        )
        assert (answer["valid"], answer["invalid_reason"]) == (
            False,
            "model_mismatch",
        )
        assert refused.status == "invalid"
        assert answered.status == "ok" and not answered.replayed

    async def test_a_2xx_the_sdk_could_not_read_is_judged_by_the_validator(
        self, conn: asyncpg.Connection, client: _Client
    ) -> None:
        """
        The body arrived whole and the validator accepts it: ``ok``, canonical,
        and the SDK's objection kept on the row beside the verdict.
        """
        answers = _clean_answers(DECISION_REGIME.as_request_questions())
        body = json.dumps({"model": MODEL, "answers": answers})
        client.respond = lambda **kw: _call(
            200,
            body,
            error_kind="response_shape",
            error_class="TypeSafeAPIResponseValidationError",
            input_tokens=None,
            output_tokens=None,
        )
        mark = await _watermark(conn)

        result = await _ask(conn, _fresh_state())

        (row,) = await _rows_since(conn, mark)
        assert row["status"] == "ok" and row["error_kind"] == "response_shape"
        assert row["raw_body"] == body
        assert row["input_tokens"] is None and row["output_tokens"] is None
        (answer,) = await conn.fetch(
            "SELECT * FROM jev_answers WHERE request_id = $1", row["id"]
        )
        assert answer["valid"] is True and answer["choice"] == "risk_on"
        assert result.status == "ok" and result.error_kind == "response_shape"
        found = await jev_repo.find_canonical(conn, row["request_hash"])
        assert found["id"] == row["id"]

    async def test_a_body_holding_a_nul_is_still_recorded(
        self, conn: asyncpg.Connection, client: _Client
    ) -> None:
        """
        A text column cannot hold a NUL, and a 403 page can. Stored verbatim,
        the insert would fail and the call — made, possibly billed — would go
        unrecorded and uncounted.
        """
        client.respond = lambda **kw: _call(
            403,
            "<html>blocked\x00</html>",
            error_kind="content_block",
            error_class="TypeSafePermissionDeniedError",
        )
        mark = await _watermark(conn)

        result = await _ask(conn, _fresh_state())

        (row,) = await _rows_since(conn, mark)
        assert result.status == row["status"] == "error"
        assert row["raw_body"] == "<html>blocked\ufffd</html>"
        assert row["http_status"] == 403
        assert row["error_kind"] == "content_block"

    async def test_no_response_is_recorded_as_none(
        self, conn: asyncpg.Connection, client: _Client
    ) -> None:
        client.respond = lambda **kw: _call(
            None,
            None,
            request_id=None,
            latency_ms=20_000,
            error_kind="timeout",
            error_class="TypeSafeAPITimeoutError",
        )
        mark = await _watermark(conn)
        spent = await jev_repo.requests_today(conn)

        result = await _ask(conn, _fresh_state())

        (row,) = await _rows_since(conn, mark)
        assert result.status == "error" and result.error_kind == "timeout"
        assert row["http_status"] is None and row["raw_body"] is None
        assert row["vendor_request_id"] is None
        # A call was made, whether or not anything came back: it is counted.
        assert await jev_repo.requests_today(conn) == spent + 1


# ---------------------------------------------------------------------------
# The road on Postgres: the vendor's standing refusals, the web gate, slices
# ---------------------------------------------------------------------------
#
# ``tests/unit/test_jev_lane.py`` drives every branch of these against a fake
# ledger. Here each is read from the rows the shipped writer leaves in the
# shipped schema, through the shipped reads and their indexes (migration
# 0013), and a refusal that would hold other tests runs on a database of its
# own (``fresh``).


def _refused_key(**kwargs: Any) -> Any:
    return _call(
        401,
        '{"detail":"invalid key"}',
        error_class="TypeSafeAuthenticationError",
        error_kind="auth",
    )


def _refused_request(**kwargs: Any) -> Any:
    return _call(
        422,
        '{"detail":[]}',
        error_class="TypeSafeUnprocessableEntityError",
        error_kind="invalid_request",
    )


def _blocked(**kwargs: Any) -> Any:
    return _call(
        403,
        "<html><body>Request blocked.</body></html>",
        error_class="TypeSafePermissionDeniedError",
        error_kind="content_block",
    )


#: The trigger that stamps ``available_at``; see ``_auth_failure_at``.
STAMP_TRIGGER = "trg_jev_requests_available_at"


async def _auth_failure_at(conn: asyncpg.Connection, available_at: datetime) -> None:
    """
    An authentication failure recorded at ``available_at``, as one recorded
    then would be. The stamp cannot be forged — that is its point — so the row
    is written with it switched off, in one transaction, on a database of the
    test's own.
    """
    async with conn.transaction():
        await conn.execute(f"ALTER TABLE jev_requests DISABLE TRIGGER {STAMP_TRIGGER}")
        await conn.execute(
            """
            INSERT INTO jev_requests (
                request_hash, state_hash, question_set, question_set_version,
                pack_hash, lane, provenance, subject_type, subject_id, as_of,
                state, questions, model_requested, http_status, status,
                error_class, error_kind, raw_body, requested_at, available_at
            )
            VALUES ($1, $2, 'decision.regime', 1, $3, 'decision', 'internal',
                    'session', '2026-09-25', $4, '{}'::jsonb, '{}'::json, $5,
                    401, 'error', 'TypeSafeAuthenticationError', 'auth',
                    '{"detail":"invalid key"}', $6, $6)
            """,
            uuid.uuid4().hex * 2,
            uuid.uuid4().hex * 2,
            DECISION_REGIME.pack_hash,
            AS_OF,
            MODEL,
            available_at,
        )
        await conn.execute(f"ALTER TABLE jev_requests ENABLE TRIGGER {STAMP_TRIGGER}")


class TestTheVendorsStandingRefusals:
    async def test_an_authentication_failure_holds_every_lane(
        self, fresh: tuple[str, asyncpg.Connection], client: _Client
    ) -> None:
        """
        A refused key is refused on every call until somebody changes it, so
        one failure holds the decision lane, a probe of it, and the
        connectivity probe alike, and none of them writes a row.
        """
        _, conn = fresh
        client.respond = _refused_key
        failed = await _ask(conn, _fresh_state())
        assert (failed.status, failed.error_kind) == ("error", "auth")
        client.respond = _clean
        mark = await _watermark(conn)

        held = [
            await _ask(conn, _fresh_state()),
            await _ask(conn, _fresh_state(), probe=True),
            await _ask(conn, ProbeState(), PROBE_CONNECTIVITY),
        ]

        assert [result.status for result in held] == ["auth_held"] * 3
        assert all(result.request_row_id is None for result in held)
        assert len(client.calls) == 1, "a held ask was sent"
        assert await _rows_since(conn, mark) == []

    async def test_an_authentication_failure_holds_until_utc_midnight(
        self, fresh: tuple[str, asyncpg.Connection], client: _Client
    ) -> None:
        """
        Yesterday's failure holds nothing today; one a second after UTC
        midnight holds, by the database's stamp.
        """
        _, conn = fresh
        midnight = await conn.fetchval("SELECT date_trunc('day', now(), 'UTC')")
        await _auth_failure_at(conn, midnight - timedelta(seconds=1))

        asked = await _ask(conn, _fresh_state())
        assert asked.status == "ok" and len(client.calls) == 1

        await _auth_failure_at(conn, midnight + timedelta(seconds=1))
        held = await _ask(conn, _fresh_state())
        assert held.status == "auth_held" and len(client.calls) == 1

    async def test_a_422_holds_its_set_and_version_and_nothing_else(
        self, fresh: tuple[str, asyncpg.Connection], client: _Client
    ) -> None:
        _, conn = fresh
        client.respond = _refused_request
        refused = await _ask(conn, _fresh_state())
        assert (refused.status, refused.error_kind) == ("error", "invalid_request")
        client.respond = _clean
        mark = await _watermark(conn)

        held = [
            await _ask(conn, _fresh_state()),
            await _ask(conn, _fresh_state(), probe=True),
        ]
        assert [result.status for result in held] == ["set_refused"] * 2
        assert len(client.calls) == 1 and await _rows_since(conn, mark) == []

        other = await _ask(conn, ProbeState(), PROBE_CONNECTIVITY)
        assert other.status == "ok" and len(client.calls) == 2

    async def test_a_recorded_answer_is_replayed_while_held(
        self, fresh: tuple[str, asyncpg.Connection], client: _Client
    ) -> None:
        """The holds stop calls, and a replay makes none."""
        _, conn = fresh
        state = _fresh_state()
        answered = await _ask(conn, state)
        client.respond = _refused_key
        await _ask(conn, _fresh_state())

        replayed = await _ask(conn, state, api_key=None)

        assert replayed.status == "ok" and replayed.replayed
        assert replayed.request_row_id == answered.request_row_id
        assert len(client.calls) == 2

    async def test_an_enumerated_state_is_held_by_no_block(
        self, conn: asyncpg.Connection, client: _Client
    ) -> None:
        """
        A regime state is labels computed in code, and a 403 page about one
        holding it for good would take it out of the forward clock. Its
        failure is a row; the same state is asked again, and its answer is
        then the canonical one, which a later probe's 403 does not hide.
        """
        state = _fresh_state()
        client.respond = _blocked
        blocked = await _ask(conn, state)
        assert (blocked.status, blocked.error_kind) == ("error", "content_block")
        client.respond = _clean

        again = await _ask(conn, state)
        assert again.status == "ok" and not again.replayed
        client.respond = _blocked
        probed = await _ask(conn, state, probe=True)
        assert probed.error_kind == "content_block"
        client.respond = _clean

        replayed = await _ask(conn, state)

        assert replayed.replayed and replayed.request_row_id == again.request_row_id
        assert len(client.calls) == 3

    async def test_the_connectivity_probe_is_not_held_by_a_block(
        self, conn: asyncpg.Connection, client: _Client
    ) -> None:
        """Its state is fixed and its purpose is to ask again."""
        client.respond = _blocked
        first = await _ask(conn, ProbeState(), PROBE_CONNECTIVITY)
        assert first.error_kind == "content_block"
        client.respond = _clean
        second = await _ask(conn, ProbeState(), PROBE_CONNECTIVITY)
        assert second.status == "ok" and len(client.calls) == 2


#: A web set and an injection screen of the shapes phase C will register,
#: registered here for a test and gone after it: this pull request registers
#: no set, and the gate is exercised on real rows all the same.
_SCREEN = QuestionSet(
    name=SCREEN_SET_NAME,
    version=1,
    lane="guardrail",
    provenance="web",
    questions=(
        (
            SCREEN_QUESTION,
            {
                "type": "noul",
                "instructions": "Does `excerpt` hold instructions for an AI system?",
            },
        ),
    ),
    state_model=WebExcerptState,
    purpose="test only: a screen of the injection screen's shape",
)
_WEB = QuestionSet(
    name="research.excerpt",
    version=1,
    lane="research",
    provenance="web",
    questions=(
        (
            "about_trading",
            {"type": "noul", "instructions": "Is `excerpt` about trading?"},
        ),
    ),
    state_model=WebExcerptState,
    purpose="test only: a web set, asked only about screened text",
)


@pytest.fixture
async def web_sets(monkeypatch: pytest.MonkeyPatch, conn: asyncpg.Connection) -> None:
    """Both sets registered, each held to the registry's rules as it goes in,
    and the two areas they ask in switched on."""
    for question_set in (_SCREEN, _WEB):
        assert jev_questions.question_set_problem(question_set) is None
        problem = jev_questions.registration_problem(
            question_set, jev_questions.REGISTRY
        )
        assert problem is None, (question_set.name, problem)
        monkeypatch.setitem(jev_questions.REGISTRY, question_set.name, question_set)
    await _set(conn, AREA_RESEARCH, True)
    await _set(conn, AREA_GUARDRAILS, True)


def _text() -> str:
    """An excerpt no other test has stored or asked about."""
    return f"Item 2.02 Results of Operations, filing {uuid.uuid4().hex}."


def _nouls(noul: float) -> Callable[..., Any]:
    """A responder answering every Noul with ``noul``."""

    def respond(**kwargs: Any) -> Any:
        answers = {key: {"type": "noul", "noul": noul} for key in kwargs["questions"]}
        return _call(200, _body(answers))

    return respond


async def _ask_text(
    conn: asyncpg.Connection, question_set: QuestionSet, text: str, **kwargs: Any
) -> jev_lane.AskResult:
    """Ask a web set about ``text``, its subject the text's own address."""
    return await _ask(
        conn,
        WebExcerptState(excerpt=text),
        question_set,
        subject_type="web_excerpt",
        subject_id=text_sha256(text),
        **kwargs,
    )


async def _screen(
    conn: asyncpg.Connection, client: _Client, text: str, noul: float = 0.03
) -> jev_lane.AskResult:
    """The screen's answer about ``text``: addressed to people, unless told
    otherwise."""
    kept = client.respond
    client.respond = _nouls(noul)
    try:
        return await _ask_text(conn, _SCREEN, text)
    finally:
        client.respond = kept


async def _document(conn: asyncpg.Connection, text: str) -> int:
    return await conn.fetchval(
        "INSERT INTO web_documents (source, url, content_sha256, excerpt) "
        "VALUES ('sec_edgar_rss', 'https://example.invalid/filing', $1, $2) "
        "RETURNING id",
        text_sha256(text),
        text,
    )


async def _quarantine(conn: asyncpg.Connection, document_id: int) -> None:
    await conn.execute(
        "UPDATE web_documents SET quarantined = TRUE, "
        "quarantine_reason = 'addressed to an AI' WHERE id = $1",
        document_id,
    )


@pytest.mark.usefixtures("web_sets")
class TestTheWebGate:
    async def test_quarantined_text_is_sent_to_nobody(
        self, conn: asyncpg.Connection, client: _Client
    ) -> None:
        """Not to a web set, and not to the screen either."""
        text = _text()
        await _quarantine(conn, await _document(conn, text))
        mark = await _watermark(conn)

        results = [await _ask_text(conn, _WEB, text), await _screen(conn, client, text)]

        assert [result.status for result in results] == ["quarantined"] * 2
        assert client.calls == [] and await _rows_since(conn, mark) == []

    async def test_a_web_set_asks_only_about_text_the_screen_cleared(
        self, conn: asyncpg.Connection, client: _Client
    ) -> None:
        cleared, flagged = _text(), _text()
        mark = await _watermark(conn)
        assert (await _ask_text(conn, _WEB, cleared)).status == "unscreened"
        assert client.calls == [] and await _rows_since(conn, mark) == []

        assert (await _screen(conn, client, cleared)).status == "ok"
        assert (await _screen(conn, client, flagged, noul=0.97)).status == "ok"
        asked = await _ask_text(conn, _WEB, cleared)
        held = await _ask_text(conn, _WEB, flagged)

        assert (asked.status, held.status) == ("ok", "unscreened")
        assert len(client.calls) == 3
        row = await jev_repo.get_request(conn, asked.request_row_id)
        assert (row["provenance"], row["lane"]) == ("web", "research")
        assert (row["subject_type"], row["subject_id"]) == (
            "web_excerpt",
            text_sha256(cleared),
        )

    async def test_the_gate_precedes_the_replay(
        self, conn: asyncpg.Connection, client: _Client
    ) -> None:
        """An answer read back about text since quarantined is that text,
        asked about again."""
        text = _text()
        document = await _document(conn, text)
        await _screen(conn, client, text)
        first = await _ask_text(conn, _WEB, text)
        assert first.status == "ok"

        await _quarantine(conn, document)
        again = await _ask_text(conn, _WEB, text)

        assert (again.status, again.replayed) == ("quarantined", False)
        assert len(client.calls) == 2

    async def test_no_screen_registered_is_no_screen_passed(
        self,
        monkeypatch: pytest.MonkeyPatch,
        conn: asyncpg.Connection,
        client: _Client,
    ) -> None:
        """A clear answer on record from a screen that is no longer registered
        clears nothing: the gate fails closed."""
        text = _text()
        await _screen(conn, client, text)
        monkeypatch.delitem(jev_questions.REGISTRY, SCREEN_SET_NAME)

        result = await _ask_text(conn, _WEB, text)

        assert result.status == "unscreened" and len(client.calls) == 1

    async def test_blocked_text_is_never_sent_again(
        self, conn: asyncpg.Connection, client: _Client
    ) -> None:
        """
        By any set, the screen and a probe included, and before the replay: a
        canonical answer on record about text a later call found blocked is not
        read back. Held by the text's state, so the module's database will do.
        """
        text = _text()
        await _screen(conn, client, text)
        answered = await _ask_text(conn, _WEB, text)
        assert answered.status == "ok"
        client.respond = _blocked
        blocked = await _ask_text(conn, _WEB, text, probe=True)
        assert (blocked.status, blocked.error_kind) == ("error", "content_block")
        client.respond = _clean
        mark = await _watermark(conn)

        results = [
            await _ask_text(conn, _WEB, text),
            await _ask_text(conn, _WEB, text, probe=True),
            await _screen(conn, client, text),
        ]

        assert [r.status for r in results] == ["content_blocked"] * 3
        assert not any(r.replayed for r in results)
        assert len(client.calls) == 3 and await _rows_since(conn, mark) == []
        other = _text()
        await _screen(conn, client, other)
        assert (await _ask_text(conn, _WEB, other)).status == "ok"


class TestTheLaneSlices:
    async def test_each_lane_spends_only_its_slice(
        self, fresh: tuple[str, asyncpg.Connection], client: _Client
    ) -> None:
        """
        At a budget of 10, the probe lane may make one call and the decision
        lane two. A probe of the decision set is held to the probe lane's
        slice, so once the connectivity probe has spent it the probe is
        refused, and the decision lane's two calls are untouched. Each refusal
        is a ``refused_budget`` row, and the day's total never reaches the
        budget.
        """
        _, conn = fresh
        await _set(conn, flags.JEV_DAILY_REQUEST_BUDGET, 10)

        probe = await _ask(conn, ProbeState(), PROBE_CONNECTIVITY)
        probed = await _ask(conn, _fresh_state(), probe=True)
        decided = [await _ask(conn, _fresh_state()) for _ in range(3)]

        assert (probe.status, probed.status) == ("ok", "refused_budget")
        assert [result.status for result in decided] == ["ok", "ok", "refused_budget"]
        rows = await _rows_since(conn, 0)
        assert [(row["lane"], row["status"]) for row in rows] == [
            ("probe", "ok"),
            ("probe", "refused_budget"),
            ("decision", "ok"),
            ("decision", "ok"),
            ("decision", "refused_budget"),
        ]
        assert len(client.calls) == 3
        assert await jev_repo.requests_today(conn) == 3


# ---------------------------------------------------------------------------
# The programme's loop
# ---------------------------------------------------------------------------


async def _job(conn: asyncpg.Connection, job_id: Any) -> asyncpg.Record:
    return await conn.fetchrow(
        "SELECT status, attempts, locked_by, started_at, error, result "
        "FROM jobs WHERE id = $1",
        job_id,
    )


async def _drain(dsn: str, **options: Any) -> bool:
    """One pass of the programme's Jev loop, on a real pool."""
    programme = Programme(
        dsn,
        api_key=None,
        secrets_key=options.get("secrets_key", ""),
        typesafe_key=options.get("typesafe_key", KEY),
    )
    programme._pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
    try:
        return await programme._drain_jev()
    finally:
        await programme._pool.close()


class TestTheProgrammeLoop:
    def test_it_owns_the_probe(self) -> None:
        assert "jev_probe" in JEV_HANDLERS

    @pytest.mark.parametrize(
        "switch", [flags.JEV_ENABLED, flags.PROGRAMME_ENABLED], ids=["jev", "programme"]
    )
    async def test_with_a_switch_off_the_job_stays_queued(
        self, conn: asyncpg.Connection, dsn: str, client: _Client, switch: str
    ) -> None:
        await _set(conn, switch, False)
        job_id = await job_repo.enqueue(conn, "jev_probe")
        mark = await _watermark(conn)

        assert await _drain(dsn) is False

        job = await _job(conn, job_id)
        assert job["status"] == "queued"
        assert job["attempts"] == 0, "an attempt was spent while switched off"
        assert job["locked_by"] is None and job["started_at"] is None
        assert client.calls == [] and await _rows_since(conn, mark) == []

    async def test_with_both_on_it_runs_and_completes_the_probe(
        self, conn: asyncpg.Connection, dsn: str, client: _Client
    ) -> None:
        job_id = await job_repo.enqueue(conn, "jev_probe")

        assert await _drain(dsn) is True

        job = await _job(conn, job_id)
        assert job["status"] == "succeeded"
        assert job["attempts"] == 1
        assert job["locked_by"] == flags.PROGRAMME_WORKER_ID
        result = json.loads(job["result"])
        assert result["status"] == "ok"
        assert result["as_expected"] is True
        row = await jev_repo.get_request(conn, result["request_id"])
        assert row["lane"] == "probe" and row["status"] == "ok"
        assert row["question_set"] == "probe.connectivity"
        assert client.calls[0]["api_key"] == KEY

    async def test_it_claims_only_its_own_kinds(
        self, conn: asyncpg.Connection, dsn: str, client: _Client
    ) -> None:
        worker_job = await job_repo.enqueue(conn, "backtest", {"run_id": "r-1"})
        probe_job = await job_repo.enqueue(conn, "jev_probe")

        await _drain(dsn)

        backtest = await _job(conn, worker_job)
        assert backtest["status"] == "queued", backtest["error"]
        assert backtest["attempts"] == 0 and backtest["locked_by"] is None
        assert (await _job(conn, probe_job))["status"] == "succeeded"

    async def test_the_key_comes_from_the_vault_first(
        self, conn: asyncpg.Connection, dsn: str, client: _Client
    ) -> None:
        secrets_key = crypto.generate_key()
        await secret_repo.set_secret(
            conn, secret_repo.TYPESAFE_API_KEY, "vault-key", secrets_key, "test"
        )
        try:
            await job_repo.enqueue(conn, "jev_probe")
            await _drain(dsn, secrets_key=secrets_key, typesafe_key="env-key")
        finally:
            await secret_repo.clear_secret(conn, secret_repo.TYPESAFE_API_KEY)
        assert [call["api_key"] for call in client.calls] == ["vault-key"]

    @pytest.mark.parametrize(
        ("reply", "status", "error"),
        [
            pytest.param(
                lambda **kw: _call(
                    401,
                    '{"detail":"no"}',
                    error_class="TypeSafeAuthenticationError",
                    error_kind="auth",
                ),
                "failed",
                "the probe failed: auth",
                id="a-refused-key",
            ),
            pytest.param(
                lambda **kw: _call(
                    422,
                    '{"detail":[]}',
                    error_class="TypeSafeUnprocessableEntityError",
                    error_kind="invalid_request",
                ),
                "failed",
                "the probe failed: invalid_request",
                id="a-refused-request",
            ),
            pytest.param(
                lambda **kw: _call(
                    503,
                    '{"error":"busy"}',
                    error_class="TypeSafeInternalServerError",
                    error_kind="server",
                ),
                "queued",
                "the probe failed: server",
                id="a-vendor-fault-is-retried",
            ),
            pytest.param(
                lambda **kw: _call(
                    200,
                    _body({"about_the_sun": {"type": "noul", "noul": 0.03}}),
                ),
                "failed",
                "not as expected",
                id="the-wrong-answer",
            ),
            pytest.param(
                lambda **kw: _call(200, _body({}, model="jev-latest")),
                "failed",
                "failed validation",
                id="an-invalid-answer",
            ),
        ],
    )
    async def test_a_probe_that_proved_nothing_fails_its_job(
        self,
        fresh: tuple[str, asyncpg.Connection],
        client: _Client,
        reply: Callable[..., Any],
        status: str,
        error: str,
    ) -> None:
        """
        The probe's verdict is the job's status. Recorded as ``succeeded`` with
        the reason in a result column nothing shows, a refused key would read
        as a working one on the jobs page and in the daily report.

        Each on a database of its own: a refused key and a refused request are
        standing refusals, which would hold every probe after them.
        """
        dsn, conn = fresh
        client.respond = reply
        job_id = await job_repo.enqueue(conn, "jev_probe")

        assert await _drain(dsn) is True

        job = await _job(conn, job_id)
        assert job["status"] == status
        assert job["attempts"] == 1
        assert error in job["error"], job["error"]
        assert KEY not in job["error"]

    async def test_a_probe_with_no_key_fails_its_job_and_asks_nothing(
        self, conn: asyncpg.Connection, dsn: str, client: _Client
    ) -> None:
        job_id = await job_repo.enqueue(conn, "jev_probe")

        assert await _drain(dsn, typesafe_key=None) is True

        job = await _job(conn, job_id)
        assert (job["status"], job["attempts"]) == ("failed", 1)
        assert "no TypeSafe key" in job["error"]
        assert client.calls == []

    async def _started(
        self, monkeypatch: pytest.MonkeyPatch, dsn: str
    ) -> tuple[Programme, asyncio.Task[None]]:
        """
        ``Programme.start`` as shipped, with the tick loop held idle: this is
        about what runs beside the tick, and a tick on this database would do
        work of its own.
        """
        monkeypatch.setenv("DATABASE_URL", dsn)
        get_settings.cache_clear()
        programme = Programme(dsn, api_key=None, secrets_key="", typesafe_key=KEY)

        async def idle(self: Programme) -> None:
            await self._stopping.wait()

        monkeypatch.setattr(Programme, "_loop", idle)
        return programme, asyncio.create_task(programme.start())

    async def test_start_runs_the_jev_loop(
        self,
        monkeypatch: pytest.MonkeyPatch,
        conn: asyncpg.Connection,
        dsn: str,
        client: _Client,
    ) -> None:
        """
        Every other test here drives the loop directly. This one starts the
        process: a start() that forgot the loop would leave the probe queued
        for ever, with nothing anywhere saying so.
        """
        job_id = await job_repo.enqueue(conn, "jev_probe")
        programme, running = await self._started(monkeypatch, dsn)
        try:
            for _ in range(200):
                if (await _job(conn, job_id))["status"] == "succeeded":
                    break
                await asyncio.sleep(0.05)
        finally:
            programme.stop()
            await asyncio.wait_for(running, timeout=10)
            get_settings.cache_clear()
        assert (await _job(conn, job_id))["status"] == "succeeded"

    async def test_shutdown_lets_a_call_in_flight_finish_and_be_recorded(
        self,
        monkeypatch: pytest.MonkeyPatch,
        conn: asyncpg.Connection,
        dsn: str,
        client: _Client,
    ) -> None:
        """
        A call already sent has been billed, and the lane records every call it
        makes. Cancelled mid-call by the routine SIGTERM, the call left no row,
        was never counted against the budget, and was asked again once the
        job's lease lapsed.
        """
        sent = asyncio.Event()

        async def slow(**kwargs: Any) -> Any:
            sent.set()
            await asyncio.sleep(0.5)
            return _clean(**kwargs)

        client.respond = slow
        job_id = await job_repo.enqueue(conn, "jev_probe")
        mark = await _watermark(conn)
        programme, running = await self._started(monkeypatch, dsn)
        try:
            await asyncio.wait_for(sent.wait(), timeout=10)
            programme.stop()
            await asyncio.wait_for(running, timeout=10)
        finally:
            programme.stop()
            get_settings.cache_clear()

        assert len(client.calls) == 1
        (row,) = await _rows_since(conn, mark)
        assert row["status"] == "ok"
        job = await _job(conn, job_id)
        assert (job["status"], job["attempts"]) == ("succeeded", 1)

    async def test_a_failing_pass_fails_the_job_for_a_retry(
        self, conn: asyncpg.Connection, dsn: str, client: _Client
    ) -> None:
        def broken(**kwargs: Any) -> Any:
            raise RuntimeError("the client broke its contract")

        client.respond = broken
        job_id = await job_repo.enqueue(conn, "jev_probe")

        assert await _drain(dsn) is True

        job = await _job(conn, job_id)
        assert job["status"] == "queued", "a retry was not left for it"
        assert job["attempts"] == 1
        assert "broke its contract" in job["error"]
