"""
test_jev_forward.py
-------------------
The forward clock against real PostgreSQL: the signals it writes, the trigger
that holds each to its answer, and the clock through the programme's loop.

``tests/unit/test_jev_forward.py`` drives every row of the handler's state
machine against fakes. What only the database can say is said here:

* **Every status passes the real trigger.** ``jev_signals_rest_on_their_answer``
  and the table's CHECKs accept what ``record_signal`` writes — measured,
  abstain and invalid, a response refused whole included — and the lane,
  provenance, pack and model on each row are its answer's request's.
* **A signal is written once.** A second record of a session writes no second
  row and reads the first back.
* **Late is the database's word.** ``backfilled`` is generated from the stamp
  the database puts on the row: false for a session whose cutoff is ahead of
  its clock, true for one whose cutoff has passed, whatever the writer thinks.
* **A replayed session rests on the first session's answer**, and costs no
  call.
* **The programme reads the traded universe as the worker does**, on the same
  rows (docs/08 open item 40), and a live-owned sleeve waits for the live
  ingest.
* **The clock runs through the loop**: planned by ``jev_plan``, claimed by the
  programme's drain, asked once, recorded once; and the next session in the
  same state asks nothing.

The client is a fake of ``jev_client.ask``: nothing here reaches TypeSafe. The
same journey over real HTTP is ``tests/sdk/test_jev_forward_over_http.py``.
Runs on a database of its own, derived from ``TEST_DATABASE_URL``, because the
ledger refuses DELETE and TRUNCATE. Skipped unless ``TEST_DATABASE_URL`` is
set.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import date, timedelta
from typing import Any

import pytest

pytest.importorskip("asyncpg")

import asyncpg  # noqa: E402

from src.core import calendar  # noqa: E402
from src.db import migrate as migrations  # noqa: E402
from src.db.repos import flags as flag_repo  # noqa: E402
from src.db.repos import jobs as job_repo  # noqa: E402
from src.programme import (  # noqa: E402
    flags,
    jev_catalogue,
    jev_client,
    jev_clock,
    jev_features,
    jev_forward,
    jev_lane,
    jev_plan,
    jev_repo,
    repo,
)
from src.programme.jev_questions import (  # noqa: E402
    DECISION_REGIME,
    RegimeState,
    SleeveState,
)
from src.programme.job_errors import JobFailedError  # noqa: E402
from src.programme.main import Programme  # noqa: E402
from src.worker import maintenance_jobs  # noqa: E402
from tests.fakes.reference_prices import (  # noqa: E402
    EXPECTED_STATE,
    forward_sessions,
    seed_reference_bars,
)

TEST_DSN = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="TEST_DATABASE_URL not set")

MODEL = jev_catalogue.DEFAULT_MODEL
KEY = "ts-test-key-not-a-secret"
SIGNAL = jev_clock.regime_signal(DECISION_REGIME, "regime")
SYMBOL = jev_clock.sleeve_symbol()
OPTIONS = list(DECISION_REGIME.as_request_questions()["regime"]["criteria"])
ESCAPE = DECISION_REGIME.escape_options["regime"]


# ---------------------------------------------------------------------------
# The database
# ---------------------------------------------------------------------------


def _own_dsn() -> str:
    base, _, tail = TEST_DSN.partition("?")
    return f"{base}_jev_forward?{tail}" if tail else f"{base}_jev_forward"


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


#: The programme, Jev and the decisions area on, the pin and the settings at
#: their seeds: what an operator starts the clock with.
ON: dict[str, Any] = {
    flags.PROGRAMME_ENABLED: True,
    flags.JEV_ENABLED: True,
    **{f"{flags.JEV_AREA_PREFIX}{area}": False for area in jev_catalogue.AREAS},
    f"{flags.JEV_AREA_PREFIX}decisions": True,
    flags.JEV_MODEL: MODEL,
    flags.JEV_DAILY_REQUEST_BUDGET: jev_catalogue.DEFAULT_DAILY_REQUEST_BUDGET,
    flags.JEV_MAX_STATE_TOKENS: jev_catalogue.DEFAULT_MAX_STATE_TOKENS,
}


@pytest.fixture
async def conn(dsn: str) -> AsyncIterator[asyncpg.Connection]:
    connection = await asyncpg.connect(dsn)
    try:
        for key, value in ON.items():
            await flag_repo.set_flag(connection, key, value, "test")
        await connection.execute("DELETE FROM jobs")
        yield connection
    finally:
        await connection.close()


@pytest.fixture
async def own() -> AsyncIterator[asyncpg.Connection]:
    """
    A database of the test's own, for a test that records the next forward
    session: a signal is written once and never deleted, so recorded in the
    module's database it would stand in the way of the clock's own test.
    """
    base, _, tail = TEST_DSN.partition("?")
    dsn = f"{base}_jev_forward_own?{tail}" if tail else f"{base}_jev_forward_own"
    name = dsn.partition("?")[0].rsplit("/", 1)[-1]
    admin = await asyncpg.connect(TEST_DSN)
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()
    await migrations.migrate(dsn)
    connection = await asyncpg.connect(dsn)
    try:
        for key, value in ON.items():
            await flag_repo.set_flag(connection, key, value, "test")
        yield connection
    finally:
        await connection.close()
        admin = await asyncpg.connect(TEST_DSN)
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        finally:
            await admin.close()


# ---------------------------------------------------------------------------
# The client, and states and sessions no other test uses
# ---------------------------------------------------------------------------


def _choice(choice: str, probabilities: tuple[float, ...]) -> dict[str, Any]:
    return {
        "type": "choice",
        "choice": choice,
        "confidence": 0.5,
        "probabilities": dict(zip(OPTIONS, probabilities, strict=True)),
    }


def _reply(answer: dict[str, Any] | None, *, model: str = MODEL) -> Callable[..., Any]:
    """
    A responder answering the regime question with ``answer``, as a 200, and
    any other question asked — the daily probe's, planned beside the clock —
    with a confident true.
    """

    def respond(**kwargs: Any) -> Any:
        answers: dict[str, Any] = {}
        for key, question in kwargs["questions"].items():
            if key == "regime":
                if answer is not None:
                    answers[key] = answer
            elif question["type"] == "noul":
                answers[key] = {"type": "noul", "noul": 0.99}
        body = json.dumps(
            {
                "model": model,
                "answers": answers,
                "usage": {"input_tokens": 300, "output_tokens": 1},
            }
        )
        return jev_client.JevCall(
            http_status=200,
            raw_body=body,
            request_id="req_forward",
            latency_ms=90,
            error_class=None,
            error_kind=None,
            input_tokens=300,
            output_tokens=1,
            wire_body=body.encode("utf-8"),
        )

    return respond


#: A clean risk_on answer: measured.
CLEAN = _choice("risk_on", (0.62, 0.21, 0.12, 0.05))


class _Client:
    """``jev_client.ask``, answering through ``respond``, counting calls."""

    def __init__(self) -> None:
        self.respond: Callable[..., Any] = _reply(CLEAN)
        self.calls: list[dict[str, Any]] = []

    async def ask(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.respond(**kwargs)

    def regime_calls(self) -> list[dict[str, Any]]:
        return [call for call in self.calls if "regime" in call["questions"]]


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> _Client:
    fake = _Client()
    monkeypatch.setattr(jev_client, "ask", fake.ask)
    return fake


def _states() -> Iterator[RegimeState]:
    # Bonds and commodities vary, so none of these is the loop's state.
    for trend, quintile, drawdown, momentum in itertools.product(
        ("below", "near"), (1, 2, 3, 4), ("deep", "severe"), ("down", "flat")
    ):
        sleeve = SleeveState(
            trend=trend,
            volatility_quintile=quintile,
            drawdown=drawdown,
            momentum=momentum,
        )
        yield RegimeState(equities=sleeve, bonds=sleeve, commodities=sleeve)


_UNUSED_STATES = _states()

#: Sessions far enough ahead that their cutoffs are ahead of any clock this
#: runs under, inside the calendar's reach, and apart from the loop's.
_FUTURE = iter(
    calendar.sessions(calendar.bounds()[1] - timedelta(days=120), calendar.bounds()[1])
)


async def _ask(
    conn: asyncpg.Connection, state: RegimeState, session: date
) -> jev_lane.AskResult:
    return await jev_lane.ask(
        conn,
        question_set=DECISION_REGIME,
        state=state,
        subject_type="session",
        subject_id=session.isoformat(),
        as_of=jev_clock.regime_as_of(session),
        api_key=KEY,
        probe=False,
    )


async def _record(
    conn: asyncpg.Connection, result: jev_lane.AskResult, session: date
) -> jev_lane.SignalRecord:
    return await jev_lane.record_signal(
        conn,
        question_set=DECISION_REGIME,
        question_key="regime",
        result=result,
        signal=SIGNAL,
        symbol=SYMBOL,
        session=session,
        decision_cutoff=jev_clock.decision_cutoff(session),
    )


async def _signal_row(conn: asyncpg.Connection, session: date) -> asyncpg.Record:
    return await conn.fetchrow(
        "SELECT * FROM jev_signals WHERE signal = $1 AND symbol = $2 AND session = $3",
        SIGNAL,
        SYMBOL,
        session,
    )


# ---------------------------------------------------------------------------
# What record_signal writes, the trigger accepts
# ---------------------------------------------------------------------------


class TestEveryStatusPassesTheRealTrigger:
    @pytest.mark.parametrize(
        ("answer", "model", "status", "value"),
        [
            pytest.param(CLEAN, MODEL, "measured", "risk_on", id="measured"),
            pytest.param(
                _choice(ESCAPE, (0.1, 0.1, 0.1, 0.7)),
                MODEL,
                "abstain",
                None,
                id="the-escape",
            ),
            pytest.param(
                _choice("neutral", (0.5, 0.3, 0.1, 0.1)),
                MODEL,
                "abstain",
                None,
                id="a-choice-that-is-not-its-argmax",
            ),
            pytest.param(
                _choice("risk_on", (0.4, 0.2, 0.1, 0.1)),
                MODEL,
                "invalid",
                None,
                id="probabilities-that-do-not-sum",
            ),
            pytest.param(CLEAN, "jev-latest", "invalid", None, id="refused-whole"),
        ],
    )
    async def test_each_status_is_written_resting_on_its_answer(
        self,
        conn: asyncpg.Connection,
        client: _Client,
        answer: dict[str, Any],
        model: str,
        status: str,
        value: str | None,
    ) -> None:
        client.respond = _reply(answer, model=model)
        session = next(_FUTURE)
        asked = await _ask(conn, next(_UNUSED_STATES), session)
        assert asked.status in ("ok", "invalid")

        record = await _record(conn, asked, session)

        assert (record.status, record.value, record.inserted) == (status, value, True)
        row = await _signal_row(conn, session)
        request = await jev_repo.get_request(conn, asked.request_row_id)
        (answer_row,) = await jev_repo.answers_for(conn, request["id"])
        assert row["answer_id"] == answer_row["id"] == record.answer_id
        assert (row["lane"], row["provenance"], row["pack_hash"]) == (
            request["lane"],
            request["provenance"],
            request["pack_hash"],
        )
        assert row["model"] == (request["model_answered"] or request["model_requested"])
        assert row["decision_cutoff"] == jev_clock.decision_cutoff(session)

    async def test_the_trigger_refuses_a_measurement_resting_on_an_invalid_answer(
        self, conn: asyncpg.Connection, client: _Client
    ) -> None:
        """
        The other side of the rows above, with ``record_signal`` bypassed: the
        database itself refuses to call an invalid answer a measurement, so a
        writer that computed the status wrongly could not store it.
        """
        client.respond = _reply(_choice("risk_on", (0.4, 0.2, 0.1, 0.1)))
        session = next(_FUTURE)
        asked = await _ask(conn, next(_UNUSED_STATES), session)
        (answer_row,) = await jev_repo.answers_for(conn, asked.request_row_id)
        assert answer_row["valid"] is False
        with pytest.raises(asyncpg.RaiseError, match="only a valid answer"):
            await conn.execute(
                """
                INSERT INTO jev_signals (signal, symbol, session, status, value,
                    answer_id, lane, provenance, pack_hash, model,
                    decision_cutoff, available_at)
                VALUES ($1, $2, $3, 'measured', 'risk_on', $4, 'decision',
                    'internal', $5, $6, $7, clock_timestamp())
                """,
                SIGNAL,
                SYMBOL,
                session,
                answer_row["id"],
                DECISION_REGIME.pack_hash,
                MODEL,
                jev_clock.decision_cutoff(session),
            )
        assert await _signal_row(conn, session) is None


class TestASignalIsWrittenOnce:
    async def test_a_rerun_writes_no_second_row(
        self, conn: asyncpg.Connection, client: _Client
    ) -> None:
        session = next(_FUTURE)
        asked = await _ask(conn, next(_UNUSED_STATES), session)
        first = await _record(conn, asked, session)
        again = await _record(conn, asked, session)

        assert first.inserted is True and again.inserted is False
        assert (again.status, again.value, again.answer_id) == (
            first.status,
            first.value,
            first.answer_id,
        )
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM jev_signals WHERE signal = $1 AND symbol = $2 "
            "AND session = $3",
            SIGNAL,
            SYMBOL,
            session,
        )
        assert count == 1


class TestLateIsTheDatabasesWord:
    async def test_a_session_whose_cutoff_is_ahead_is_live(
        self, conn: asyncpg.Connection, client: _Client
    ) -> None:
        session = next(_FUTURE)
        record = await _record(
            conn, await _ask(conn, next(_UNUSED_STATES), session), session
        )
        assert record.backfilled is False
        row = await _signal_row(conn, session)
        assert row["available_at"] < row["decision_cutoff"]

    async def test_a_session_whose_cutoff_has_passed_is_late(
        self, conn: asyncpg.Connection, client: _Client
    ) -> None:
        """
        Written after its cutoff — which the handler never does, and which is
        exactly why the database, not the writer, decides: the stamp is the
        database's, and so is the verdict.
        """
        now = await jev_clock.database_now(conn)
        past = calendar.sessions(now.date() - timedelta(days=30), now.date())[0]
        assert jev_clock.decision_cutoff(past) < now
        record = await _record(conn, await _ask(conn, next(_UNUSED_STATES), past), past)
        assert record.backfilled is True
        row = await _signal_row(conn, past)
        assert row["available_at"] > row["decision_cutoff"]


class TestAReplayedSessionRestsOnTheFirstAnswer:
    async def test_two_sessions_in_one_state_share_an_answer_id(
        self, conn: asyncpg.Connection, client: _Client
    ) -> None:
        state = next(_UNUSED_STATES)
        first_session, second_session = next(_FUTURE), next(_FUTURE)
        first = await _ask(conn, state, first_session)
        second = await _ask(conn, state, second_session)

        assert second.replayed and second.request_row_id == first.request_row_id
        assert len(client.calls) == 1, "a replay made a call"
        one = await _record(conn, first, first_session)
        two = await _record(conn, second, second_session)
        assert one.answer_id == two.answer_id
        request = await jev_repo.get_request(conn, second.request_row_id)
        assert request["subject_id"] == first_session.isoformat(), (
            "the answer is the first session's, which is how a replay is read"
        )


# ---------------------------------------------------------------------------
# The traded universe, and a sleeve the live ingest owns
# ---------------------------------------------------------------------------


async def _deployment(
    conn: asyncpg.Connection,
    symbols: list[str],
    *,
    status: str = "enabled",
    owner: str | None = None,
) -> uuid.UUID:
    deployment_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO deployments (id, strategy_name, params, mode, capital_usd,
                                 status)
        VALUES ($1, 'buy_and_hold', $2::jsonb, 'paper', 100000, $3)
        """,
        deployment_id,
        json.dumps({"symbols": symbols}),
        status,
    )
    if owner is not None:
        await conn.execute(
            "UPDATE deployments SET owner_id = $2 WHERE id = $1", deployment_id, owner
        )
    return deployment_id


async def _disable(conn: asyncpg.Connection, *ids: uuid.UUID) -> None:
    await conn.execute(
        "UPDATE deployments SET status = 'disabled' WHERE id = ANY($1::uuid[])",
        list(ids),
    )


class TestTheTradedUniverseIsTheWorkers:
    async def test_the_programme_and_the_worker_read_one_universe(
        self, conn: asyncpg.Connection
    ) -> None:
        """
        The programme may not import the worker, so it reads the rule again;
        this holds the two readings to one answer on the same rows: enabled,
        the operator's, each strategy asked for its universe.
        """
        ids = [
            await _deployment(conn, ["SPY", "EFA"]),
            await _deployment(conn, ["EFA", "QQQ"]),
            await _deployment(conn, ["TLT"], status="disabled"),
            await _deployment(conn, ["GSG"], owner="programme"),
        ]
        try:
            programme = await repo.traded_universe(conn)
            worker = await maintenance_jobs._deployed_universe(conn)
            assert programme.symbols == worker == {"SPY", "EFA", "QQQ"}
            assert programme.unreadable == ()
        finally:
            await _disable(conn, *ids)


class TestALiveOwnedSleeveWaitsForTheLiveIngest:
    async def test_it_waits_for_the_live_ingest_and_then_asks(
        self, own: asyncpg.Connection, client: _Client
    ) -> None:
        """
        SPY traded by an enabled deployment is the live ingest's, and its span
        is on one basis only once ``ingest_bars:{S}`` has succeeded: until
        then the session waits, retried, having asked nothing (docs/08 open
        item 40). A failed live ingest is quoted in the wait.
        """
        conn = own
        now = await jev_clock.database_now(conn)
        session, _ = forward_sessions(now)
        await seed_reference_bars(conn, session)
        await _deployment(conn, ["SPY"])
        payload = {
            "session": session.isoformat(),
            "set": DECISION_REGIME.name,
            "version": DECISION_REGIME.version,
        }
        key = jev_clock.ingest_job_key(session)

        with pytest.raises(JobFailedError) as waiting:
            await jev_forward.collect(conn, payload, KEY)
        assert waiting.value.retry is True
        assert f"{key} has not been planned" in waiting.value.error
        assert "equities (SPY)" in waiting.value.error

        job_id = await job_repo.enqueue(
            conn, "ingest_bars", {"session": session.isoformat()}, dedupe_key=key
        )
        await conn.execute(
            "UPDATE jobs SET status = 'failed', error = 'the span would not "
            "download' WHERE id = $1",
            job_id,
        )
        with pytest.raises(JobFailedError) as failed:
            await jev_forward.collect(conn, payload, KEY)
        assert failed.value.retry is True
        assert "is failed (the span would not download)" in failed.value.error
        assert client.regime_calls() == []
        assert await _signal_row(conn, session) is None, "a waiting session wrote"

        await conn.execute("UPDATE jobs SET status = 'succeeded' WHERE id = $1", job_id)
        result = await jev_forward.collect(conn, payload, KEY)
        assert result["status"] == "measured" and result["inserted"] is True
        assert len(client.regime_calls()) == 1

    async def test_a_sleeve_disabled_after_the_ingest_failed_still_waits(
        self, own: asyncpg.Connection, client: _Client
    ) -> None:
        """
        C4's review: SPY traded when ``ingest_bars:{S}`` failed its span
        refetch, the reference job for S leaving it to the live ingest, and
        then the deployment disabled. Read by who owns SPY now, it is nobody's
        and would be measured over the history the failed attempt stitched;
        it waits instead, through a retry that succeeds with nothing left to
        fetch, and is asked once the reference job has re-based it whole.
        """
        conn = own
        now = await jev_clock.database_now(conn)
        session, _ = forward_sessions(now)
        await seed_reference_bars(conn, session)
        deployment = await _deployment(conn, ["SPY"])
        payload = {
            "session": session.isoformat(),
            "set": DECISION_REGIME.name,
            "version": DECISION_REGIME.version,
        }
        ingest_id = await job_repo.enqueue(
            conn,
            "ingest_bars",
            {"session": session.isoformat()},
            dedupe_key=jev_clock.ingest_job_key(session),
        )
        await conn.execute(
            "UPDATE jobs SET attempts = 1, error = 'the span would not download' "
            "WHERE id = $1",
            ingest_id,
        )
        reference_id = await job_repo.enqueue(
            conn,
            "ingest_reference_bars",
            {"session": session.isoformat()},
            dedupe_key=jev_clock.reference_job_key(session),
        )
        await conn.execute("UPDATE jobs SET attempts = 1 WHERE id = $1", reference_id)
        left_spy_alone = {
            "upserted": {"GSG": 1_512, "IEF": 1_512},
            "backfilled": {},
            "untouched": ["SPY"],
            "taken_back": [],
        }
        await job_repo.complete(conn, reference_id, left_spy_alone)
        await _disable(conn, deployment)

        with pytest.raises(JobFailedError) as waiting:
            await jev_forward.collect(conn, payload, KEY)
        assert waiting.value.retry is True
        assert waiting.value.error.startswith("equities (SPY): no enabled deployment")
        assert "the span would not download" in waiting.value.error

        await conn.execute("UPDATE jobs SET attempts = 2 WHERE id = $1", ingest_id)
        await job_repo.complete(conn, ingest_id, {"symbols": 0, "bars": 0})
        with pytest.raises(JobFailedError) as still:
            await jev_forward.collect(conn, payload, KEY)
        assert still.value.retry is True, "a retry that fetched nothing re-based it"
        assert client.regime_calls() == []
        assert await _signal_row(conn, session) is None

        await conn.execute(
            "UPDATE jobs SET result = $2::jsonb WHERE id = $1",
            reference_id,
            json.dumps({**left_spy_alone, "upserted": {"GSG": 1, "IEF": 1, "SPY": 1}}),
        )
        result = await jev_forward.collect(conn, payload, KEY)
        assert result["status"] == "measured"
        assert len(client.regime_calls()) == 1


# ---------------------------------------------------------------------------
# The clock through the loop
# ---------------------------------------------------------------------------


async def _drain(dsn: str) -> bool:
    """One drain of the programme's Jev loop, on a real pool."""
    programme = Programme(dsn, api_key=None, secrets_key="", typesafe_key=KEY)
    programme._pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
    try:
        return await programme._drain_jev()
    finally:
        await programme._pool.close()


async def _due(conn: asyncpg.Connection, key: str) -> None:
    """The minute its collection opens: the job becomes claimable now."""
    changed = await conn.execute(
        "UPDATE jobs SET scheduled_for = NOW() WHERE dedupe_key = $1", key
    )
    assert changed == "UPDATE 1", key


class TestTheClockThroughTheLoop:
    async def test_planned_claimed_asked_once_and_recorded_once(
        self, conn: asyncpg.Connection, dsn: str, client: _Client
    ) -> None:
        """
        The planner puts the session in the queue, the programme's drain
        claims it, and it becomes one request, one answer and one signal, live.
        The next session, in the same state, is planned, claimed and recorded
        resting on the same answer, and no call is made for it.
        """
        now = await jev_clock.database_now(conn)
        session, following = forward_sessions(now)
        await seed_reference_bars(conn, following)
        for day in (session, following):
            panel = await jev_clock.load_regime_panel(conn, day)
            assert jev_features.regime_state(
                panel, day, jev_clock.REFERENCE_SLEEVES
            ) == (EXPECTED_STATE), (
                "the seeded bars no longer give the state this test is built on"
            )

        planned = await jev_plan.plan(conn, now=now, key_available=True)
        first_key = jev_clock.regime_job_key(DECISION_REGIME, session)
        assert first_key in planned
        assert jev_clock.reference_job_key(session) in planned
        await _due(conn, first_key)
        mark = await conn.fetchval("SELECT COALESCE(MAX(id), 0) FROM jev_requests")

        assert await _drain(dsn) is True

        first = (await jev_repo.job_outcomes(conn, [first_key]))[first_key]
        assert first["status"] == "succeeded", first["error"]
        assert first["result"]["status"] == "measured"
        assert first["result"]["backfilled"] is False
        assert first["result"]["replayed"] is False
        assert len(client.regime_calls()) == 1
        requests = await conn.fetch(
            "SELECT id FROM jev_requests WHERE id > $1 AND lane = 'decision'", mark
        )
        assert len(requests) == 1
        assert len(await jev_repo.answers_for(conn, requests[0]["id"])) == 1
        one = await _signal_row(conn, session)
        assert one is not None and one["backfilled"] is False

        # A minute into the first session's collection, the planner reaches
        # the next session.
        later = jev_clock.collect_at(session) + timedelta(minutes=1)
        planned = await jev_plan.plan(conn, now=later, key_available=True)
        second_key = jev_clock.regime_job_key(DECISION_REGIME, following)
        assert second_key in planned and first_key not in planned
        await _due(conn, second_key)

        assert await _drain(dsn) is True

        second = (await jev_repo.job_outcomes(conn, [second_key]))[second_key]
        assert second["status"] == "succeeded", second["error"]
        assert second["result"]["replayed"] is True
        assert len(client.regime_calls()) == 1, "the equal state was asked again"
        two = await _signal_row(conn, following)
        assert two["answer_id"] == one["answer_id"]
        assert two["backfilled"] is False

    async def test_a_worker_kind_the_planner_queues_is_left_for_the_worker(
        self, conn: asyncpg.Connection, dsn: str, client: _Client
    ) -> None:
        now = await jev_clock.database_now(conn)
        session, _ = forward_sessions(now)
        planned = await jev_plan.plan(conn, now=now, key_available=True)
        reference = jev_clock.reference_job_key(session)
        assert reference in planned
        await _due(conn, reference)

        await _drain(dsn)

        job = (await jev_repo.job_outcomes(conn, [reference]))[reference]
        assert (job["status"], job["attempts"]) == ("queued", 0)
