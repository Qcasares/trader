"""
test_jev_harness.py
-------------------
The evaluation harness's three reports, built on PostgreSQL from rows the
shipped code wrote: the planner's jobs, the forward clock's signals through
the programme's own drain, the re-asks the planner sampled and the re-ask job
ran, the daily probe, a session recorded late and a job that expired.

``tests/unit/test_jev_eval.py`` holds every rule of the report to rows built
by hand; the reads beneath it — ``signals_between``, ``probe_pairs``,
``probe_series``, ``first_job_session``, ``job_outcomes`` — once ran here on
nothing, and a wrong join, filter or column in any of them passed every suite
(docs/08, C4's review). So each report is built here the way an operator's
command builds it, and every count is checked against what was written.

The client is a fake of ``jev_client.ask``: nothing here reaches TypeSafe.
Runs on a database of its own, derived from ``TEST_DATABASE_URL``, because the
ledger refuses DELETE and TRUNCATE. Skipped unless ``TEST_DATABASE_URL`` is
set.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Callable
from datetime import UTC, date, datetime, time, timedelta
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
    jev_eval,
    jev_lane,
    jev_plan,
    jev_prereg,
    jev_repo,
)
from src.programme.jev_questions import (  # noqa: E402
    DECISION_REGIME,
    RegimeState,
    SleeveState,
)
from src.programme.main import Programme  # noqa: E402
from tests.fakes.reference_prices import (  # noqa: E402
    forward_sessions,
    seed_reference_bars,
)

TEST_DSN = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="TEST_DATABASE_URL not set")

MODEL = jev_catalogue.DEFAULT_MODEL
KEY = "ts-test-key-not-a-secret"
OPTIONS = list(DECISION_REGIME.as_request_questions()["regime"]["criteria"])
SIGNAL = jev_clock.regime_signal(DECISION_REGIME, "regime")
SYMBOL = jev_clock.sleeve_symbol()

#: A state the seeded bars never give: every sleeve falling, deep and calm.
FALLING = SleeveState(
    trend="below", volatility_quintile=2, drawdown="deep", momentum="down"
)
LATE_STATE = RegimeState(equities=FALLING, bonds=FALLING, commodities=FALLING)
OTHER_STATE = RegimeState(
    equities=FALLING,
    bonds=SleeveState(
        trend="near", volatility_quintile=3, drawdown="none", momentum="flat"
    ),
    commodities=FALLING,
)


# ---------------------------------------------------------------------------
# The database and the client
# ---------------------------------------------------------------------------


def _own_dsn() -> str:
    base, _, tail = TEST_DSN.partition("?")
    return f"{base}_jev_harness?{tail}" if tail else f"{base}_jev_harness"


@pytest.fixture
async def dsn() -> AsyncIterator[str]:
    """A database of the test's own, dropped after it."""
    dsn = _own_dsn()
    name = dsn.partition("?")[0].rsplit("/", 1)[-1]
    admin = await asyncpg.connect(TEST_DSN)
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()
    await migrations.migrate(dsn)
    try:
        yield dsn
    finally:
        admin = await asyncpg.connect(TEST_DSN)
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        finally:
            await admin.close()


@pytest.fixture
async def conn(dsn: str) -> AsyncIterator[asyncpg.Connection]:
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


def _body(answers: dict[str, Any], model: str = MODEL) -> str:
    return json.dumps(
        {
            "model": model,
            "answers": answers,
            "usage": {"input_tokens": 212, "output_tokens": 1},
        }
    )


def _call(status: int | None, body: str | None, **fields: Any) -> Any:
    values: dict[str, Any] = {
        "http_status": status,
        "raw_body": body,
        "request_id": "req_harness",
        "latency_ms": 120,
        "error_class": None,
        "error_kind": None,
        "input_tokens": 212 if status == 200 else None,
        "output_tokens": 1 if status == 200 else None,
        "wire_body": None if body is None else body.encode("utf-8"),
    }
    values.update(fields)
    return jev_client.JevCall(**values)


def _answering(regime: str, *, model: str = MODEL) -> Callable[..., Any]:
    """
    A 200 answering the regime question with ``regime``, ten points clear of
    the next option — a low margin, so the answer is in a re-ask stratum —
    and any Noul, the daily probe's, with a confident true.
    """

    def respond(**kwargs: Any) -> Any:
        answers: dict[str, Any] = {}
        for key, question in kwargs["questions"].items():
            if question["type"] == "noul":
                answers[key] = {"type": "noul", "noul": 0.99}
                continue
            others = [option for option in OPTIONS if option != regime]
            probabilities = {regime: 0.45, others[0]: 0.35, others[1]: 0.1}
            probabilities[others[2]] = 0.1
            answers[key] = {
                "type": "choice",
                "choice": regime,
                "confidence": 0.3,
                "probabilities": {o: probabilities[o] for o in OPTIONS},
            }
        return _call(200, _body(answers, model))

    return respond


def _timing_out(**kwargs: Any) -> Any:
    """No response at all: no status, no body and no vendor request id."""
    return _call(
        None,
        None,
        request_id=None,
        error_class="TypeSafeAPITimeoutError",
        error_kind="timeout",
        latency_ms=20_000,
    )


class _Client:
    """``jev_client.ask``, answering through ``respond``."""

    def __init__(self) -> None:
        self.respond: Callable[..., Any] = _answering("risk_on")
        self.calls = 0

    async def ask(self, **kwargs: Any) -> Any:
        self.calls += 1
        return self.respond(**kwargs)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> _Client:
    fake = _Client()
    monkeypatch.setattr(jev_client, "ask", fake.ask)
    return fake


async def _drain(dsn: str) -> None:
    """Every Jev job that is due, through the programme's own drain."""
    programme = Programme(dsn, api_key=None, secrets_key="", typesafe_key=KEY)
    programme._pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
    try:
        await programme._drain_jev()
    finally:
        await programme._pool.close()


async def _only_due(conn: asyncpg.Connection, *keys: str) -> None:
    """
    Make ``keys`` due now and hold every other queued job back, so a drain
    runs exactly these whatever the time of day the test runs at — today's
    own regime job, say, which is due for ten minutes after each close.
    """
    await conn.execute(
        "UPDATE jobs SET scheduled_for = NOW() + INTERVAL '30 days' "
        "WHERE status = 'queued'"
    )
    for key in keys:
        changed = await conn.execute(
            "UPDATE jobs SET scheduled_for = NOW() WHERE dedupe_key = $1", key
        )
        assert changed == "UPDATE 1", key


async def _job(conn: asyncpg.Connection, key: str) -> dict[str, Any]:
    return (await jev_repo.job_outcomes(conn, [key]))[key]


async def _ask_about(
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


# ---------------------------------------------------------------------------
# The ledger an operator's command reads
# ---------------------------------------------------------------------------


class _Ledger:
    """What was written, and when the report is read."""

    def __init__(self) -> None:
        self.expired: date
        self.late: date
        self.first: date
        self.second: date
        self.report_at: datetime
        self.canonical: dict[str, int] = {}


async def _write_the_ledger(
    conn: asyncpg.Connection, dsn: str, client: _Client
) -> _Ledger:
    """
    Every kind of row the report reads, each through the shipped path that
    writes it in operation.
    """
    ledger = _Ledger()
    now = await jev_clock.database_now(conn)
    ledger.first, ledger.second = forward_sessions(now)
    before = calendar.sessions(now.date() - timedelta(days=30), now.date())
    ledger.expired, ledger.late = before[0], before[5]
    assert jev_clock.decision_cutoff(ledger.late) < now
    await seed_reference_bars(conn, ledger.second)

    # A regime job for a past session that reached its cutoff unmeasured: its
    # error is why the session is absent, and it is the series' first job.
    expired_key = jev_clock.regime_job_key(DECISION_REGIME, ledger.expired)
    job_id = await job_repo.enqueue(
        conn,
        "jev_regime",
        {
            "session": ledger.expired.isoformat(),
            "set": DECISION_REGIME.name,
            "version": DECISION_REGIME.version,
        },
        dedupe_key=expired_key,
    )
    await conn.execute(
        "UPDATE jobs SET status = 'failed', attempts = 20, error = $2 WHERE id = $1",
        job_id,
        "expired: the forward clock missed it; before the cutoff: no bar",
    )

    # A session asked about after its cutoff: the database marks it late.
    late = await _ask_about(conn, LATE_STATE, ledger.late)
    recorded = await jev_lane.record_signal(
        conn,
        question_set=DECISION_REGIME,
        question_key="regime",
        result=late,
        signal=SIGNAL,
        symbol=SYMBOL,
        session=ledger.late,
        decision_cutoff=jev_clock.decision_cutoff(ledger.late),
    )
    assert recorded.backfilled is True
    ledger.canonical["late"] = late.request_row_id

    # The forward clock: planned, claimed by the programme's drain, asked,
    # recorded live; the daily probe runs in the same drain.
    planned = await jev_plan.plan(conn, now=now, key_available=True)
    first_key = jev_clock.regime_job_key(DECISION_REGIME, ledger.first)
    probe_key = f"jev_probe:{now.astimezone(UTC).date().isoformat()}"
    assert first_key in planned and probe_key in planned
    await _only_due(conn, first_key, probe_key)
    await _drain(dsn)
    first = await _job(conn, first_key)
    assert first["status"] == "succeeded", first["error"]
    ledger.canonical["first"] = first["result"]["request_id"]

    # The next session in the same state: a replay, recorded live.
    later = jev_clock.collect_at(ledger.first) + timedelta(minutes=1)
    planned = await jev_plan.plan(conn, now=later, key_available=True)
    planned_later = planned
    second_key = jev_clock.regime_job_key(DECISION_REGIME, ledger.second)
    assert second_key in planned
    await _only_due(conn, second_key)
    await _drain(dsn)
    second = await _job(conn, second_key)
    assert second["status"] == "succeeded", second["error"]
    assert second["result"]["replayed"] is True

    # A third canonical answer, whose re-ask will get no response.
    other = await _ask_about(conn, OTHER_STATE, calendar.bounds()[1])
    ledger.canonical["other"] = other.request_row_id

    # The next UTC day the planner samples the day's canonical answers. The
    # pass above can already be on that day, whatever the hour the test runs
    # at: ``ledger.first`` is the last session the clock plans at ``now``,
    # tomorrow's while today's cutoff is ahead, and its collection then falls
    # on the UTC day after the answers, so that pass queued the re-asks of the
    # answers on record by then. Each re-ask is one the planner queued, by one
    # pass or the other; the first cut looked in this pass's alone, and failed
    # on a weekday from New York's midnight to the day's cutoff.
    answered_on = {
        (await jev_repo.get_request(conn, request_id))["available_at"].date()
        for request_id in ledger.canonical.values()
    }
    (day,) = answered_on
    tomorrow = datetime.combine(day + timedelta(days=1), time(0, 10), UTC)
    planned = await jev_plan.plan(conn, now=tomorrow, key_available=True)
    reasks = {*planned_later, *planned}
    for name, respond in (
        ("first", _answering("neutral")),  # measured, and flipped
        ("late", _answering("risk_on", model="jev-latest")),  # refused whole
        ("other", _timing_out),  # no response
    ):
        key = jev_eval.reask_job_key(ledger.canonical[name])
        assert key in reasks, (name, sorted(reasks))
        client.respond = respond
        await _only_due(conn, key)
        await _drain(dsn)
    client.respond = _answering("risk_on")

    ledger.report_at = jev_clock.decision_cutoff(ledger.second) + timedelta(hours=1)
    return ledger


class TestTheReportsOnRealRows:
    async def test_forward_accounts_for_every_session(
        self, conn: asyncpg.Connection, dsn: str, client: _Client
    ) -> None:
        ledger = await _write_the_ledger(conn, dsn, client)

        report = await jev_eval.forward_report(conn, since=None, now=ledger.report_at)

        sessions = calendar.sessions(ledger.expired, ledger.second)
        assert report["since"] == ledger.expired.isoformat(), (
            "the series starts at its first job, the expired one"
        )
        assert report["sessions"] == len(sessions)
        assert (report["live_measured"], report["late"]) == (2, 1)
        assert report["live_abstain"] == report["live_invalid"] == 0
        assert report["absent"] == len(sessions) - 3
        assert (report["coverage"]["k"], report["coverage"]["n"]) == (
            2,
            len(sessions),
        )
        reasons = {a["session"]: a["reason"] for a in report["absences"]}
        assert reasons[ledger.expired.isoformat()].startswith("failed: expired")
        assert ledger.late.isoformat() not in reasons, "a late row is not absent"
        assert all(reasons.values())
        assert report["distinct_states"] == {"signals": 3, "distinct": 2}
        assert (report["replayed"]["k"], report["replayed"]["n"]) == (1, 3)

        assert report == await jev_eval.forward_report(
            conn, since=ledger.expired, now=ledger.report_at
        )

    async def test_forward_scores_each_model_under_the_plan_it_asked_under(
        self, conn: asyncpg.Connection, dsn: str, client: _Client
    ) -> None:
        ledger = await _write_the_ledger(conn, dsn, client)

        report = await jev_eval.forward_report(conn, since=None, now=ledger.report_at)

        assert list(report["models"]) == [MODEL]
        figures = report["models"][MODEL]
        assert (figures["live_measured"], figures["distinct_states"]) == (2, 1)
        risk_on = figures["answer_shares"]["risk_on"]
        assert (risk_on["k"], risk_on["n"], risk_on["distinct_states"]) == (2, 2, 1)
        assert "wilson" not in risk_on
        # The forward job wrote the plan in force into its result, and the
        # replayed session is scored under the plan its answer was asked under.
        assert figures["not_scored"] == {}
        assert figures["baseline_agreement_sessions"]["n"] == 2
        assert figures["baseline_agreement_states"]["n"] == 1
        first = await _job(
            conn, jev_clock.regime_job_key(DECISION_REGIME, ledger.first)
        )
        assert first["result"]["plan_hash"] == jev_prereg.plan_hash()

    async def test_forward_counts_every_re_ask_in_its_stratum(
        self, conn: asyncpg.Connection, dsn: str, client: _Client
    ) -> None:
        """
        Three re-asks, sampled by the planner and run by the re-ask job: one
        answered and flipped, one refused whole and one that got no response.
        The first is compared; the other two are counted as not compared,
        never dropped.
        """
        ledger = await _write_the_ledger(conn, dsn, client)

        report = await jev_eval.forward_report(conn, since=None, now=ledger.report_at)

        rates = report["flip_rates"][MODEL]
        assert rates["other_plans"] == 0
        compared = sum(rates[s]["n"] for s in jev_eval.STRATA)
        flipped = sum(rates[s]["k"] for s in jev_eval.STRATA)
        not_compared = sum(rates[s]["not_compared"] for s in jev_eval.STRATA)
        assert (compared, flipped, not_compared) == (1, 1, 2)
        for name in ("first", "late", "other"):
            job = await _job(conn, jev_eval.reask_job_key(ledger.canonical[name]))
            assert job["payload"]["plan_hash"] == jev_prereg.plan_hash()
            assert job["payload"]["stratum"] in jev_eval.STRATA

    async def test_forward_reports_the_daily_probe(
        self, conn: asyncpg.Connection, dsn: str, client: _Client
    ) -> None:
        ledger = await _write_the_ledger(conn, dsn, client)

        report = await jev_eval.forward_report(conn, since=None, now=ledger.report_at)

        (probe,) = report["probe_series"]
        assert (probe["status"], probe["p_true"], probe["model"]) == (
            "ok",
            0.99,
            MODEL,
        )

    async def test_the_text_says_it_all(
        self, conn: asyncpg.Connection, dsn: str, client: _Client
    ) -> None:
        ledger = await _write_the_ledger(conn, dsn, client)

        text = jev_eval.format_forward(
            await jev_eval.forward_report(conn, since=None, now=ledger.report_at)
        )

        assert "live measured 2, abstain 0, invalid 0, late 1" in text
        assert f"absent {ledger.expired.isoformat()}: failed: expired" in text
        assert "share risk_on: 2 of 2 sessions = 1.000, over 1 distinct state" in text

    async def test_forward_audit_rebuilds_each_state(
        self, conn: asyncpg.Connection, dsn: str, client: _Client
    ) -> None:
        """
        The two live sessions were asked about the states the bars give, and
        agree; the late one was asked about a state they do not, and drifts.
        """
        ledger = await _write_the_ledger(conn, dsn, client)

        audit = await jev_eval.forward_audit(conn, since=None, now=ledger.report_at)

        assert (audit["states"], audit["agree"], audit["drift"]) == (3, 2, 1)
        verdicts = {entry["session"]: entry for entry in audit["sessions"]}
        assert verdicts[ledger.late.isoformat()]["verdict"] == "drift"
        assert verdicts[ledger.late.isoformat()]["moved"]

    async def test_status_reads_the_switches_and_the_days_spend(
        self, conn: asyncpg.Connection, dsn: str, client: _Client
    ) -> None:
        await _write_the_ledger(conn, dsn, client)

        status = await jev_eval.status_report(conn)

        assert status["programme_enabled"] is True
        assert status["jev_enabled"] is True
        assert status["areas"]["decisions"] is True
        assert status["model"] == MODEL
        assert status["plan_hash"] == jev_prereg.plan_hash()
        # Three canonical calls — the late session, the forward clock's first
        # and the third state — and four in the probe lane: the daily probe
        # and three re-asks, the one that got no response among them.
        assert status["lanes"]["decision"]["spent_today"] == 3
        assert status["lanes"]["probe"]["spent_today"] == 4


class TestTheForwardReportUnderTheRegimePlan:
    """
    Plan version 2, M4 (docs/09, section 3.3): the regime's baseline rule and
    its sleeves are a plan of their own. The regime job, run by the
    programme's own drain, records both plans in its result, and the forward
    report scores agreement only over answers first recorded under the regime
    plan it runs: a new global plan sets aside no regime agreement, a new
    regime plan sets aside regime agreement alone, and a result naming no
    regime plan, as a phase C4 job's did, is "plan unknown".
    """

    async def test_the_job_records_both_plans(
        self, conn: asyncpg.Connection, dsn: str, client: _Client
    ) -> None:
        ledger = await _write_the_ledger(conn, dsn, client)
        for session in (ledger.first, ledger.second):
            job = await _job(conn, jev_clock.regime_job_key(DECISION_REGIME, session))
            assert job["result"]["plan_version"] == jev_prereg.PLAN_VERSION
            assert job["result"]["plan_hash"] == jev_prereg.plan_hash()
            assert (
                job["result"]["regime_plan_version"] == jev_prereg.REGIME_PLAN_VERSION
            )
            assert job["result"]["regime_plan_hash"] == jev_prereg.regime_plan_hash()

    async def test_a_new_global_plan_sets_aside_no_regime_agreement(
        self,
        conn: asyncpg.Connection,
        dsn: str,
        client: _Client,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ledger = await _write_the_ledger(conn, dsn, client)
        monkeypatch.setattr(jev_prereg, "plan_hash", lambda: "1" * 64)

        report = await jev_eval.forward_report(conn, since=None, now=ledger.report_at)

        figures = report["models"][MODEL]
        assert figures["not_scored"] == {}
        assert figures["baseline_agreement_sessions"]["n"] == 2

    async def test_a_new_regime_plan_sets_aside_regime_agreement_alone(
        self,
        conn: asyncpg.Connection,
        dsn: str,
        client: _Client,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ledger = await _write_the_ledger(conn, dsn, client)
        recorded = jev_prereg.regime_plan_hash()
        monkeypatch.setattr(jev_prereg, "regime_plan_hash", lambda: "2" * 64)

        report = await jev_eval.forward_report(conn, since=None, now=ledger.report_at)

        figures = report["models"][MODEL]
        # Both live sessions rest on the first session's answer, recorded
        # under the regime plan the job named.
        assert figures["not_scored"] == {recorded: 2}
        assert figures["baseline_agreement_sessions"]["n"] == 0
        assert report["plan_hash"] == jev_prereg.plan_hash()
        assert report["flip_rates"][MODEL]["other_plans"] == 0, (
            "a flip pair counts under the global plan its re-ask names, which "
            "a new regime plan does not move"
        )

    async def test_a_result_naming_no_regime_plan_is_plan_unknown(
        self, conn: asyncpg.Connection, dsn: str, client: _Client
    ) -> None:
        ledger = await _write_the_ledger(conn, dsn, client)
        key = jev_clock.regime_job_key(DECISION_REGIME, ledger.first)
        await conn.execute(
            "UPDATE jobs SET result = result - 'regime_plan_version' "
            "- 'regime_plan_hash' WHERE dedupe_key = $1",
            key,
        )

        report = await jev_eval.forward_report(conn, since=None, now=ledger.report_at)

        figures = report["models"][MODEL]
        assert figures["not_scored"] == {jev_eval.UNKNOWN_PLAN: 2}
        assert figures["baseline_agreement_sessions"]["n"] == 0
