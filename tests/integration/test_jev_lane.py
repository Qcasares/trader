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
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

pytest.importorskip("asyncpg")

import asyncpg  # noqa: E402

from src import crypto  # noqa: E402
from src.db import migrate as migrations  # noqa: E402
from src.db.repos import flags as flag_repo  # noqa: E402
from src.db.repos import jobs as job_repo  # noqa: E402
from src.db.repos import secrets as secret_repo  # noqa: E402
from src.programme import (  # noqa: E402
    flags,
    jev_catalogue,
    jev_client,
    jev_lane,
    jev_repo,
)
from src.programme.jev_questions import (  # noqa: E402
    DECISION_REGIME,
    PROBE_CONNECTIVITY,
    ProbeState,
    RegimeState,
    SleeveState,
)
from src.programme.main import JEV_HANDLERS, Programme  # noqa: E402

TEST_DSN = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="TEST_DATABASE_URL not set")

MODEL = jev_catalogue.DEFAULT_MODEL
KEY = "ts-test-key-not-a-secret"
AS_OF = datetime(2026, 9, 25, 20, 0, tzinfo=UTC)
AREA_DECISIONS = f"{flags.JEV_AREA_PREFIX}decisions"


# ---------------------------------------------------------------------------
# The database
# ---------------------------------------------------------------------------


def _lane_dsn() -> str:
    base, _, tail = TEST_DSN.partition("?")
    return f"{base}_jev_lane?{tail}" if tail else f"{base}_jev_lane"


@pytest.fixture(scope="module")
def dsn() -> str:
    async def setup() -> str:
        # The name comes from before the query string: a Unix-socket DSN puts
        # the socket path after it, and splitting the whole URL on "/" would
        # return that instead of the database.
        name = _lane_dsn().partition("?")[0].rsplit("/", 1)[-1]
        admin = await asyncpg.connect(TEST_DSN)
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            await admin.execute(f'CREATE DATABASE "{name}"')
        finally:
            await admin.close()
        await migrations.migrate(_lane_dsn())
        return _lane_dsn()

    return asyncio.run(setup())


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
    return await jev_lane.ask(
        conn,
        question_set=question_set,
        state=state,
        subject_type="session",
        subject_id="2026-09-25",
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
