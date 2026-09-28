"""
test_jev_forward.py
-------------------
The forward clock's job, every row of its state machine, without a database.

What carries the weight, each failing silently if it goes:

* **It never backfills.** Once the database's clock reaches the session's
  cutoff nothing is asked, whatever else holds, and the job fails for good
  with the reason it last met. A session missed is absent, not asked about
  late.
* **It writes no ``missing`` row.** Every condition that can change before
  the cutoff — a switch, a late ingest, a vendor's late bar — fails the job
  for a retry and writes nothing; only an answer is recorded.
* **One ask per job.** The shutdown grace covers one call, and a job that
  asked twice would be two answers with an equal claim to be right.
* **A live-owned sleeve waits for the live ingest** (docs/08 open item 40).

The connection answers the switches' query and nothing else, and every other
thing the handler touches is replaced here by a fake of the module attribute
it calls, so a handler that reached around one would fail. The real
Postgres counterpart, with the trigger that holds each signal to its answer,
is ``tests/integration/test_jev_forward.py``.
"""

from __future__ import annotations

import ast
import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from src.core.panel import PricePanel
from src.data.reference import (
    REFERENCE_SLEEVES,
    REFERENCE_SOURCE,
    REFERENCE_SYMBOLS,
    REFERENCE_WINDOW_DAYS,
)
from src.programme import (
    flags,
    jev_catalogue,
    jev_clock,
    jev_features,
    jev_forward,
    jev_lane,
    jev_prereg,
    jev_repo,
    repo,
)
from src.programme.jev_lane import AskResult, SignalRecord
from src.programme.jev_questions import DECISION_REGIME, RegimeState
from src.programme.job_errors import JobFailedError

ROOT = Path(__file__).resolve().parents[2]
FORWARD = ROOT / "src" / "programme" / "jev_forward.py"

FLAG_QUERY = "SELECT value FROM system_flags WHERE key = $1"
KEY = "ts-test-key-not-a-secret"

#: A Monday: closes 20:00 UTC, so its cutoff is 21:00 UTC.
SESSION = date(2026, 9, 28)
CUTOFF = jev_clock.decision_cutoff(SESSION)
COLLECT = jev_clock.collect_at(SESSION)
SIGNAL = "decision.regime@1:regime"
SYMBOL = "equities=SPY;bonds=IEF;commodities=GSG"
PAYLOAD = {"session": SESSION.isoformat(), "set": "decision.regime", "version": 1}

#: What every result the job completes with says of the analysis plan.
PLAN_IN_FORCE = {
    "plan_version": jev_prereg.PLAN_VERSION,
    "plan_hash": jev_prereg.plan_hash(),
}


# ---------------------------------------------------------------------------
# The rig
# ---------------------------------------------------------------------------


class _Conn:
    """Answers the switches' one query from ``rows``, and nothing else."""

    def __init__(self, rows: Mapping[str, str]) -> None:
        self.rows = dict(rows)

    async def fetchrow(self, query: str, *args: object) -> dict[str, str] | None:
        assert query == FLAG_QUERY, f"the handler ran SQL of its own: {query!r}"
        (key,) = args
        return {"value": self.rows[key]} if key in self.rows else None


def _switches(decisions: bool = True) -> dict[str, str]:
    return {
        flags.PROGRAMME_ENABLED: "true",
        flags.JEV_ENABLED: "true",
        f"{flags.JEV_AREA_PREFIX}decisions": "true" if decisions else "false",
    }


def _closes(n: int, step: float) -> list[float]:
    return [100.0 * math.exp(step * i) for i in range(n)]


def _panel(
    session: date = SESSION, n: int = 1_400, symbols: tuple[str, ...] = ()
) -> PricePanel:
    """Every reference sleeve rising steadily, ending on ``session``."""
    sessions = pd.bdate_range(end=pd.Timestamp(session), periods=n)
    rows = []
    for symbol in symbols or REFERENCE_SYMBOLS:
        for day, close in zip(sessions, _closes(n, 0.001), strict=True):
            rows.append((symbol, day.date(), close, close, close, close, 1e6, close))
    return PricePanel.from_bars(rows, as_of=session)


def _asked(status: str = "ok", **fields: Any) -> AskResult:
    return AskResult(status=status, request_row_id=fields.pop("row", 7), **fields)


@dataclass
class Rig:
    conn: _Conn
    now: datetime = COLLECT
    signal_recorded: bool = False
    traded: repo.TradedUniverse = field(
        default_factory=lambda: repo.TradedUniverse(frozenset(), ())
    )
    jobs: dict[str, dict[str, Any]] = field(default_factory=dict)
    panel: PricePanel | None = field(default_factory=_panel)
    answer: Callable[..., AskResult] = lambda **kw: _asked("ok")
    record: SignalRecord = SignalRecord(
        status="measured",
        value="risk_on",
        answer_id=11,
        backfilled=False,
        inserted=True,
    )
    asks: list[dict[str, Any]] = field(default_factory=list)
    recorded: list[dict[str, Any]] = field(default_factory=list)
    clock_reads: int = 0
    panel_reads: list[date] = field(default_factory=list)


@pytest.fixture
def rig(monkeypatch: pytest.MonkeyPatch) -> Rig:
    state = Rig(_Conn(_switches()))

    async def signal_exists(conn, *, signal, symbol, session):
        assert (signal, symbol, session) == (SIGNAL, SYMBOL, SESSION)
        return state.signal_recorded

    async def database_now(conn):
        state.clock_reads += 1
        return state.now

    async def traded_universe(conn):
        return state.traded

    async def job_outcomes(conn, keys):
        return {key: state.jobs[key] for key in keys if key in state.jobs}

    async def load_regime_panel(conn, session, symbols=REFERENCE_SYMBOLS):
        state.panel_reads.append(session)
        return state.panel

    async def ask(conn, **kwargs):
        state.asks.append(kwargs)
        return state.answer(**kwargs)

    async def record_signal(conn, **kwargs):
        state.recorded.append(kwargs)
        return state.record

    monkeypatch.setattr(jev_repo, "signal_exists", signal_exists)
    monkeypatch.setattr(jev_clock, "database_now", database_now)
    monkeypatch.setattr(repo, "traded_universe", traded_universe)
    monkeypatch.setattr(jev_repo, "job_outcomes", job_outcomes)
    monkeypatch.setattr(jev_clock, "load_regime_panel", load_regime_panel)
    monkeypatch.setattr(jev_lane, "ask", ask)
    monkeypatch.setattr(jev_lane, "record_signal", record_signal)
    return state


async def _collect(rig: Rig, payload: Mapping[str, Any] = PAYLOAD) -> dict[str, Any]:
    return await jev_forward.collect(rig.conn, dict(payload), KEY)


async def _refused(rig: Rig, payload: Mapping[str, Any] = PAYLOAD) -> JobFailedError:
    with pytest.raises(JobFailedError) as failed:
        await _collect(rig, payload)
    return failed.value


def _asked_nothing(rig: Rig) -> None:
    assert rig.asks == [], "a question was asked"
    assert rig.recorded == [], "a signal was recorded"


# ---------------------------------------------------------------------------
# Every row of the state machine
# ---------------------------------------------------------------------------


class TestThePayload:
    @pytest.mark.parametrize(
        "session",
        ["2026-09-26", "2026-11-26", "2031-01-02", "1990-01-02", "not-a-date", None],
        ids=[
            "saturday",
            "thanksgiving",
            "past-the-calendar",
            "before-it",
            "text",
            "none",
        ],
    )
    async def test_a_day_that_is_not_a_session_fails_for_good(
        self, rig: Rig, session: object
    ) -> None:
        failed = await _refused(rig, {**PAYLOAD, "session": session})
        assert failed.retry is False
        _asked_nothing(rig)

    @pytest.mark.parametrize("name", ["probe.connectivity", "decision.other", None])
    async def test_a_set_that_is_not_the_clocks_fails_for_good(
        self, rig: Rig, name: object
    ) -> None:
        failed = await _refused(rig, {**PAYLOAD, "set": name})
        assert failed.retry is False
        _asked_nothing(rig)

    @pytest.mark.parametrize("version", [2, 0, "1", None])
    async def test_a_job_from_another_version_is_superseded(
        self, rig: Rig, version: object
    ) -> None:
        """Planned before a bump: completed, asking nothing, and saying so."""
        result = await _collect(rig, {**PAYLOAD, "version": version})
        assert result["status"] == "superseded"
        _asked_nothing(rig)


class TestASessionIsRecordedOnce:
    async def test_a_session_already_recorded_asks_nothing(self, rig: Rig) -> None:
        rig.signal_recorded = True
        result = await _collect(rig)
        assert result == {
            "session": SESSION.isoformat(),
            "signal": SIGNAL,
            **PLAN_IN_FORCE,
            "status": "recorded_before",
        }
        _asked_nothing(rig)


class TestItNeverBackfills:
    @pytest.mark.parametrize(
        "after", [timedelta(0), timedelta(seconds=1), timedelta(days=3)]
    )
    async def test_at_or_after_the_cutoff_nothing_is_asked(
        self, rig: Rig, after: timedelta
    ) -> None:
        rig.now = CUTOFF + after
        failed = await _refused(rig)
        assert failed.retry is False
        assert failed.error.startswith(f"expired: the forward clock missed {SESSION}")
        _asked_nothing(rig)
        assert rig.panel_reads == [], "the bars were read for a session it missed"

    async def test_the_reason_it_missed_is_the_last_one_it_met(self, rig: Rig) -> None:
        """
        The cutoff is when, not why: the error keeps the reason the attempt
        before met, read from the job's own row, which is what the report shows
        for an absent session.
        """
        key = jev_clock.regime_job_key(DECISION_REGIME, SESSION)
        rig.jobs[key] = {
            "attempts": 9,
            "error": "no regime state for 2026-09-28: bonds (IEF) has no close",
            "status": "running",
        }
        rig.now = CUTOFF + timedelta(seconds=5)
        failed = await _refused(rig)
        assert "Before the cutoff: no regime state for 2026-09-28" in failed.error

    async def test_a_first_attempt_after_the_cutoff_says_there_was_none(
        self, rig: Rig
    ) -> None:
        key = jev_clock.regime_job_key(DECISION_REGIME, SESSION)
        rig.jobs[key] = {"attempts": 1, "error": None, "status": "running"}
        rig.now = CUTOFF + timedelta(minutes=30)
        assert "No earlier attempt" in (await _refused(rig)).error

    async def test_the_clock_is_read_again_just_before_the_ask(self, rig: Rig) -> None:
        """However long the bars took, nothing is asked once the cutoff is met."""
        reads = iter([CUTOFF - timedelta(seconds=30), CUTOFF])

        async def later(conn):
            return next(reads)

        jev_clock.database_now = later  # restored by the rig's monkeypatch
        failed = await _refused(rig)
        assert failed.retry is False and failed.error.startswith("expired")
        _asked_nothing(rig)


class TestWhatCanChangeBeforeTheCutoffIsRetried:
    async def test_the_decisions_area_off(self, rig: Rig) -> None:
        rig.conn.rows[f"{flags.JEV_AREA_PREFIX}decisions"] = "false"
        failed = await _refused(rig)
        assert failed.retry is True and "decisions area is off" in failed.error
        _asked_nothing(rig)

    @pytest.mark.parametrize(
        "rows",
        [
            {flags.PROGRAMME_ENABLED: "true", flags.JEV_ENABLED: "false"},
            {flags.PROGRAMME_ENABLED: "true"},
            {},
        ],
        ids=["jev-off", "jev-missing", "nothing-readable"],
    )
    async def test_the_area_reads_off_with_the_master_switch(
        self, rig: Rig, rows: dict[str, str]
    ) -> None:
        rig.conn.rows = {**rows, f"{flags.JEV_AREA_PREFIX}decisions": "true"}
        assert (await _refused(rig)).retry is True
        _asked_nothing(rig)

    async def test_no_bars_at_all(self, rig: Rig) -> None:
        rig.panel = None
        failed = await _refused(rig)
        assert failed.retry is True and REFERENCE_SOURCE in failed.error
        _asked_nothing(rig)

    async def test_no_state_says_why(self, rig: Rig) -> None:
        rig.panel = _panel(n=jev_features.MIN_HISTORY_SESSIONS - 1)
        failed = await _refused(rig)
        assert failed.retry is True
        assert "equities (SPY) has 1,279 of the 1,280 closes it needs" in failed.error
        assert CUTOFF.strftime("%Y-%m-%d %H:%M") in failed.error
        _asked_nothing(rig)

    async def test_a_sleeve_without_its_sessions_close(self, rig: Rig) -> None:
        rig.panel = _panel(session=SESSION - timedelta(days=1))
        # A panel that ends the day before, read as of the session.
        rig.panel = PricePanel(
            {f: rig.panel.frame(f) for f in rig.panel.fields}, as_of=SESSION
        )
        failed = await _refused(rig)
        assert failed.retry is True
        assert f"has no close on {SESSION.isoformat()}" in failed.error


class TestALiveOwnedSleeveWaitsForTheLiveIngest:
    """docs/08 open item 40."""

    INGEST = jev_clock.ingest_job_key(SESSION)

    @pytest.mark.parametrize(
        "job",
        [
            None,
            {"status": "queued", "error": None},
            {"status": "running", "error": None},
            {"status": "queued", "error": "refetching the stored span failed"},
            {"status": "failed", "error": "refetching the stored span failed"},
        ],
        ids=["not-planned", "queued", "running", "retrying", "failed"],
    )
    async def test_until_the_ingest_has_succeeded_the_session_waits(
        self, rig: Rig, job: dict[str, Any] | None
    ) -> None:
        rig.traded = repo.TradedUniverse(frozenset({"SPY", "QQQ"}), ())
        if job is not None:
            rig.jobs[self.INGEST] = job
        failed = await _refused(rig)
        assert failed.retry is True
        assert failed.error.startswith("equities (SPY): the live ingest's")
        assert self.INGEST in failed.error
        if job is not None and job["error"]:
            assert job["error"] in failed.error
        _asked_nothing(rig)
        assert rig.panel_reads == []

    async def test_once_it_has_succeeded_the_session_is_asked(self, rig: Rig) -> None:
        rig.traded = repo.TradedUniverse(frozenset({"SPY"}), ())
        rig.jobs[self.INGEST] = {"status": "succeeded", "error": None}
        await _collect(rig)
        assert len(rig.asks) == 1

    async def test_a_sleeve_nobody_trades_waits_for_nothing(self, rig: Rig) -> None:
        rig.traded = repo.TradedUniverse(frozenset({"QQQ", "EFA"}), ())
        await _collect(rig)
        assert len(rig.asks) == 1

    async def test_a_universe_that_cannot_be_read_waits_for_the_ingest(
        self, rig: Rig
    ) -> None:
        """Failing closed: any sleeve may be the live ingest's."""
        rig.traded = repo.TradedUniverse(frozenset(), ("0f6c-deployment",))
        failed = await _refused(rig)
        assert failed.retry is True and "0f6c-deployment" in failed.error
        rig.jobs[self.INGEST] = {"status": "succeeded", "error": None}
        await _collect(rig)
        assert len(rig.asks) == 1


#: The reference job for SESSION, run while the live ingest owned SPY: IEF and
#: GSG re-based whole, SPY left to the live ingest.
LEFT_SPY_ALONE = {
    "status": "succeeded",
    "attempts": 1,
    "error": None,
    "result": {
        "upserted": {"GSG": 1_512, "IEF": 1_512},
        "backfilled": {},
        "untouched": ["SPY"],
        "taken_back": [],
    },
}


class TestASleeveTheLiveIngestHeldWhenItFailedWaitsToo:
    """
    docs/08 open item 40, C4's review: who owns a sleeve when the regime job
    runs is not who owned it when the live ingest ran. SPY was traded when
    ``ingest_bars:{S}`` failed its span refetch, whose fallback still wrote
    SPY's ten-day window on a newer basis than the rows before it; the
    reference job for S, running while the live ingest owned SPY, left it
    alone; then the deployment was disabled. SPY now reads as nobody's, and
    measured it would be measured over a stitched history.
    """

    INGEST = jev_clock.ingest_job_key(SESSION)
    REFERENCE = jev_clock.reference_job_key(SESSION)
    FAILED_ONCE = "refetching the stored span failed"

    @pytest.mark.parametrize(
        "ingest",
        [
            {"status": "queued", "attempts": 1, "error": FAILED_ONCE},
            {"status": "failed", "attempts": 14, "error": FAILED_ONCE},
            {"status": "running", "attempts": 2, "error": FAILED_ONCE},
            # A retry after the disable, with nothing left to ingest.
            {"status": "succeeded", "attempts": 2, "error": None},
        ],
        ids=["retrying", "gave-up", "retry-running", "vacuous-retry"],
    )
    async def test_a_sleeve_disabled_after_a_failed_ingest_waits(
        self, rig: Rig, ingest: dict[str, Any]
    ) -> None:
        rig.traded = repo.TradedUniverse(frozenset(), ())
        rig.jobs[self.INGEST] = ingest
        rig.jobs[self.REFERENCE] = LEFT_SPY_ALONE
        failed = await _refused(rig)
        assert failed.retry is True
        assert failed.error.startswith("equities (SPY): no enabled deployment")
        assert "bonds" not in failed.error and "commodities" not in failed.error
        assert self.INGEST in failed.error and self.REFERENCE in failed.error
        _asked_nothing(rig)
        assert rig.panel_reads == []

    @pytest.mark.parametrize(
        "reference",
        [None, {"status": "queued", "attempts": 0, "error": None}],
        ids=["reference-not-planned", "reference-not-run"],
    )
    async def test_a_reference_job_that_has_not_re_based_it_proves_nothing(
        self, rig: Rig, reference: dict[str, Any] | None
    ) -> None:
        rig.traded = repo.TradedUniverse(frozenset(), ())
        rig.jobs[self.INGEST] = {
            "status": "failed",
            "attempts": 14,
            "error": self.FAILED_ONCE,
        }
        if reference is not None:
            rig.jobs[self.REFERENCE] = reference
        failed = await _refused(rig)
        assert failed.retry is True
        assert failed.error.startswith(
            "equities (SPY), bonds (IEF), commodities (GSG): no enabled deployment"
        )

    async def test_the_reference_job_re_basing_it_whole_clears_it(
        self, rig: Rig
    ) -> None:
        """Disabled before the reference job ran, which then refetched it whole."""
        rig.traded = repo.TradedUniverse(frozenset(), ())
        rig.jobs[self.INGEST] = {
            "status": "failed",
            "attempts": 14,
            "error": self.FAILED_ONCE,
        }
        rig.jobs[self.REFERENCE] = {
            **LEFT_SPY_ALONE,
            "result": {"upserted": {"GSG": 1_512, "IEF": 1_512, "SPY": 1_512}},
        }
        await _collect(rig)
        assert len(rig.asks) == 1

    @pytest.mark.parametrize(
        "ingest",
        [
            None,
            {"status": "queued", "attempts": 0, "error": None},
            {"status": "succeeded", "attempts": 1, "error": None},
        ],
        ids=["not-planned", "not-yet-run", "succeeded-first-time"],
    )
    async def test_an_ingest_with_no_failed_attempt_leaves_nothing_to_wait_for(
        self, rig: Rig, ingest: dict[str, Any] | None
    ) -> None:
        """No attempt failed, so no attempt left a window behind."""
        rig.traded = repo.TradedUniverse(frozenset(), ())
        if ingest is not None:
            rig.jobs[self.INGEST] = ingest
        rig.jobs[self.REFERENCE] = LEFT_SPY_ALONE
        await _collect(rig)
        assert len(rig.asks) == 1

    async def test_a_sleeve_still_traded_needs_only_the_ingest_to_succeed(
        self, rig: Rig
    ) -> None:
        """
        Traded now, a retry that succeeded refetched it: the attempt that
        succeeds is the latest, and the universe it read is the one now.
        """
        rig.traded = repo.TradedUniverse(frozenset({"SPY"}), ())
        rig.jobs[self.INGEST] = {"status": "succeeded", "attempts": 2, "error": None}
        rig.jobs[self.REFERENCE] = LEFT_SPY_ALONE
        await _collect(rig)
        assert len(rig.asks) == 1


class TestWhatTheAskCameTo:
    async def test_an_answer_is_recorded_and_the_job_completes(self, rig: Rig) -> None:
        rig.answer = lambda **kw: _asked("ok", row=41, replayed=True)
        result = await _collect(rig)
        (asked,) = rig.asks
        assert asked["question_set"] is DECISION_REGIME
        assert isinstance(asked["state"], RegimeState)
        assert (asked["subject_type"], asked["subject_id"]) == (
            "session",
            SESSION.isoformat(),
        )
        assert asked["as_of"] == jev_clock.regime_as_of(SESSION)
        assert asked["api_key"] == KEY and asked["probe"] is False
        (recorded,) = rig.recorded
        assert recorded["question_set"] is DECISION_REGIME
        assert recorded["question_key"] == "regime"
        assert recorded["result"].request_row_id == 41
        assert (recorded["signal"], recorded["symbol"]) == (SIGNAL, SYMBOL)
        assert recorded["session"] == SESSION
        assert recorded["decision_cutoff"] == CUTOFF
        assert result == {
            "session": SESSION.isoformat(),
            "signal": SIGNAL,
            **PLAN_IN_FORCE,
            "status": "measured",
            "value": "risk_on",
            "backfilled": False,
            "request_id": 41,
            "replayed": True,
            "inserted": True,
        }

    async def test_a_response_refused_whole_is_recorded_not_retried(
        self, rig: Rig
    ) -> None:
        """What an allocator would have seen at the cutoff: an invalid signal."""
        rig.answer = lambda **kw: _asked("invalid", row=42)
        rig.record = SignalRecord("invalid", None, 12, False, True)
        result = await _collect(rig)
        assert result["status"] == "invalid" and result["value"] is None
        assert len(rig.recorded) == 1

    @pytest.mark.parametrize(
        "kind", ["connection", "timeout", "rate_limited", "server"]
    )
    async def test_a_transient_failure_is_retried(self, rig: Rig, kind: str) -> None:
        rig.answer = lambda **kw: _asked("error", row=43, error_kind=kind)
        failed = await _refused(rig)
        assert failed.retry is True and kind in failed.error
        assert rig.recorded == []

    @pytest.mark.parametrize(
        "kind", ["auth", "content_block", "invalid_request", "response_shape", "client"]
    )
    async def test_any_other_failure_is_not(self, rig: Rig, kind: str) -> None:
        rig.answer = lambda **kw: _asked("error", row=44, error_kind=kind)
        failed = await _refused(rig)
        assert failed.retry is False and kind in failed.error
        assert rig.recorded == []

    async def test_a_switch_turned_off_mid_job_is_retried(self, rig: Rig) -> None:
        rig.answer = lambda **kw: _asked("disabled", row=None)
        assert (await _refused(rig)).retry is True

    @pytest.mark.parametrize(
        "status",
        [
            "no_key",
            "refused_model",
            "auth_held",
            "set_refused",
            "content_blocked",
            "refused_budget",
            "refused_limits",
        ],
    )
    async def test_a_standing_refusal_is_not_retried(
        self, rig: Rig, status: str
    ) -> None:
        rig.answer = lambda **kw: _asked(status, row=None)
        failed = await _refused(rig)
        assert failed.retry is False
        assert "came to" not in failed.error, "a refusal without its own reason"
        assert rig.recorded == []


# ---------------------------------------------------------------------------
# One ask, and the module attribute
# ---------------------------------------------------------------------------


class TestOneAskPerJob:
    async def test_one_ask_per_job(self, rig: Rig) -> None:
        """Every path through the handler, counted: never more than one ask."""
        answers = [
            lambda **kw: _asked("ok"),
            lambda **kw: _asked("invalid"),
            lambda **kw: _asked("error", error_kind="server"),
            lambda **kw: _asked("disabled", row=None),
            lambda **kw: _asked("no_key", row=None),
        ]
        for answer in answers:
            rig.asks.clear()
            rig.answer = answer
            try:
                await _collect(rig)
            except JobFailedError:
                pass
            assert len(rig.asks) == 1


def _ask_calls(tree: ast.AST) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "ask"
    ]


def test_it_asks_through_the_module_attribute() -> None:
    """
    ``jev_lane.ask``, looked up on the module at the call, with every argument
    named and no transport: the SDK suite hands the road a transport by
    replacing that attribute, and the transport-seam scan refuses one passed
    here, or a ``**`` that could carry one.
    """
    tree = ast.parse(FORWARD.read_text("utf-8"))
    (call,) = _ask_calls(tree)
    assert isinstance(call.func.value, ast.Name) and call.func.value.id == "jev_lane"
    assert [ast.unparse(arg) for arg in call.args] == ["conn"]
    named = [keyword.arg for keyword in call.keywords]
    assert None not in named, "a ** reaches the road"
    assert set(named) == {
        "question_set",
        "state",
        "subject_type",
        "subject_id",
        "as_of",
        "api_key",
        "probe",
    }
    imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "src.programme.jev_lane"
    ]
    assert not imports, "ask imported by name would not be the patched attribute"


# ---------------------------------------------------------------------------
# The prices
# ---------------------------------------------------------------------------


class _BarsConn:
    """Answers the loader's query with ``rows``, and records it."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.queries: list[tuple[str, tuple[Any, ...]]] = []

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.queries.append((query, args))
        return self.rows


def _bar_rows(session: date, n: int = 1_400, extra_after: int = 0) -> list[dict]:
    sessions = pd.bdate_range(end=pd.Timestamp(session), periods=n)
    if extra_after:
        sessions = sessions.append(
            pd.bdate_range(
                start=pd.Timestamp(session) + pd.Timedelta(days=1), periods=extra_after
            )
        )
    rows = []
    for symbol in REFERENCE_SYMBOLS:
        for i, day in enumerate(sessions):
            # After the session, a crash: a descriptor that peeked would move.
            price = 100.0 * math.exp(0.001 * i) * (0.5 if day.date() > session else 1)
            rows.append({"symbol": symbol, "session": day.date(), "adj_close": price})
    return rows


class TestTheLoader:
    async def test_the_loader_filters_one_source(self) -> None:
        conn = _BarsConn(_bar_rows(SESSION))
        await jev_clock.load_regime_panel(conn, SESSION)
        ((query, args),) = conn.queries
        compact = " ".join(query.split())
        assert "FROM daily_bars" in compact
        assert "source = $2" in compact and args[1] == REFERENCE_SOURCE
        assert "session <= $3" in compact and args[2] == SESSION
        assert "session >= $3::date - $4::int" in compact
        assert args[3] == REFERENCE_WINDOW_DAYS
        assert sorted(args[0]) == sorted(REFERENCE_SYMBOLS)

    async def test_it_reads_the_adjusted_close_and_no_raw_price(self) -> None:
        conn = _BarsConn(_bar_rows(SESSION))
        panel = await jev_clock.load_regime_panel(conn, SESSION)
        ((query, _),) = conn.queries
        selected = query.split("FROM")[0]
        assert "adj_close" in selected
        for raw in ("open", "high", "low", " close", "volume"):
            assert raw not in selected.replace("adj_close", ""), raw
        assert panel is not None and panel.as_of == SESSION
        assert panel.latest("SPY", "close") is None
        assert panel.latest("SPY", "adj_close") is not None

    async def test_no_rows_is_no_panel(self) -> None:
        assert await jev_clock.load_regime_panel(_BarsConn([]), SESSION) is None

    async def test_a_future_bar_changes_nothing(self) -> None:
        """
        The SQL stops at the session; and were a later bar ever handed over,
        the panel is cut at the session, so the state is the same.
        """
        without = await jev_clock.load_regime_panel(
            _BarsConn(_bar_rows(SESSION)), SESSION
        )
        with_future = await jev_clock.load_regime_panel(
            _BarsConn(_bar_rows(SESSION, extra_after=30)), SESSION
        )
        assert without is not None and with_future is not None
        state = jev_features.regime_state(without, SESSION, REFERENCE_SLEEVES)
        assert state is not None
        assert (
            jev_features.regime_state(with_future, SESSION, REFERENCE_SLEEVES) == state
        )


class TestTheSymbolIsTheSleeves:
    async def test_the_symbol_is_the_sleeves(self, rig: Rig) -> None:
        """
        The state is computed from the reference sleeves, and the signal names
        them: the only record of which instruments a regime describes.
        """
        await _collect(rig)
        (recorded,) = rig.recorded
        assert recorded["symbol"] == jev_clock.sleeve_symbol(REFERENCE_SLEEVES)
        (asked,) = rig.asks
        expected = jev_features.regime_state(_panel(), SESSION, REFERENCE_SLEEVES)
        assert asked["state"] == expected

    async def test_other_sleeves_would_not_be_read(self, rig: Rig) -> None:
        """A panel holding only other instruments has no state to ask about."""
        rig.panel = _panel(symbols=("QQQ", "TLT", "DBC"))
        failed = await _refused(rig)
        assert "is not in the panel" in failed.error
        _asked_nothing(rig)


class TestTheResultNamesThePlanInForce:
    """
    docs/08: after the first regime answer, a change of plan is recorded as a
    change of plan, and what was analysed under the old plan stays under it.
    The forward report can keep to that only if each answer says which plan
    was in force when it was asked, so every result the job completes with
    names it (``jev_eval._answer_plan`` reads it back).
    """

    async def test_an_answer_names_the_plan_it_was_asked_under(self, rig: Rig) -> None:
        result = await _collect(rig)
        assert (result["plan_version"], result["plan_hash"]) == (
            jev_prereg.PLAN_VERSION,
            jev_prereg.plan_hash(),
        )

    async def test_every_completion_names_it(self, rig: Rig) -> None:
        rig.signal_recorded = True
        assert (await _collect(rig))["plan_hash"] == jev_prereg.plan_hash()
        superseded = await _collect(rig, {**PAYLOAD, "version": 2})
        assert superseded["plan_hash"] == jev_prereg.plan_hash()


async def test_the_result_holds_no_state_and_no_price(rig: Rig) -> None:
    """
    The job's result, which the queue stores as JSON, is labels, counts and
    ids, and the plan in force: nothing that was sent, and no price.
    """
    result = await _collect(rig)
    assert json.loads(json.dumps(result)) == result
    assert set(result) == {
        "session",
        "signal",
        "plan_version",
        "plan_hash",
        "status",
        "value",
        "backfilled",
        "request_id",
        "replayed",
        "inserted",
    }
    assert all(not isinstance(value, dict | list) for value in result.values())


def test_the_catalogue_knows_the_area_it_reads() -> None:
    assert jev_catalogue.LANE_AREA[DECISION_REGIME.lane] == "decisions"
