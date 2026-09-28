"""
What the forward report may say, and how it says nothing (CLAUDE.md, honesty
rules).

``src/programme/jev_eval.py`` reads the ledger and prints the forward clock's
record. The rules it follows, each of which would fail silently:

* **The field list is pinned.** Nothing computes a return, a P&L or a hit rate:
  the answers are collected and not consumed, and a regime is not a forecast.
  A field arriving here arrives past a reviewer reading this test.
* **Absent sessions stay in the denominator.** A session the clock missed is a
  session it missed; a coverage over the sessions that happened to be answered
  is 100% by construction.
* **A late row is never live.** ``backfilled`` is the database's word, and a
  late answer counted as live is a backfill wearing a forward result's name.
* **Sessions are not trials.** Every session in one state replays one answer,
  so a share or an agreement over sessions carries no interval, which would
  narrow with how often one judgement repeats; agreement over distinct states
  does.
* **Each model apart**, and **each answer under the plan that registered it**:
  a pin change is a second judge, and a rule registered after an answer never
  scores it.
* **A figure over nothing is "not measured", never 0**, in the data and in the
  text.
* **It reads, and holds no key**: ``DATABASE_URL`` is the one variable it reads,
  and every command runs in a read-only transaction.

``build_forward`` is pure, so the rules are tested here without a database;
``tests/integration/test_jev_harness.py`` builds every report from rows the
shipped planner, forward job, re-ask job and daily probe wrote on PostgreSQL.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from src.core import calendar
from src.core.panel import PricePanel
from src.data.reference import REFERENCE_SLEEVES, REFERENCE_SYMBOLS
from src.programme import jev_clock, jev_eval, jev_prereg, jev_repo
from src.programme.jev_questions import DECISION_REGIME, RegimeState, SleeveState

ROOT = Path(__file__).resolve().parents[2]
EVAL = ROOT / "src" / "programme" / "jev_eval.py"
SYMBOL = jev_clock.sleeve_symbol()
MODEL = "jev-1.13.0"
PLAN = jev_prereg.plan_hash()

#: The forward report's fields, in order. Adding one is an edit here, where a
#: reviewer reads what it is; a return, a P&L or a hit rate is refused below
#: whatever it is called.
PINNED_FIELDS = (
    "plan_version",
    "plan_hash",
    "signal",
    "symbol",
    "since",
    "until",
    "sessions",
    "live_measured",
    "live_abstain",
    "live_invalid",
    "late",
    "absent",
    "coverage",
    "absences",
    "distinct_states",
    "replayed",
    "models",
    "flip_rates",
    "probe_series",
)

#: One model's block, in order.
PINNED_MODEL_FIELDS = (
    "live_measured",
    "distinct_states",
    "answer_shares",
    "baseline_agreement_sessions",
    "baseline_agreement_states",
    "not_scored",
)

#: Fragments no key anywhere in the report may contain.
FORBIDDEN = ("return", "pnl", "profit", "loss", "hit", "sharpe", "equity", "price")


def _sleeve(trend: str, quintile: int, drawdown: str, momentum: str) -> SleeveState:
    return SleeveState(
        trend=trend, volatility_quintile=quintile, drawdown=drawdown, momentum=momentum
    )


CALM = _sleeve("near", 3, "none", "flat")
RISING = RegimeState(
    equities=_sleeve("above", 2, "none", "up"), bonds=CALM, commodities=CALM
)
FALLING = RegimeState(
    equities=_sleeve("below", 5, "severe", "down"), bonds=CALM, commodities=CALM
)
SIDEWAYS = RegimeState(equities=CALM, bonds=CALM, commodities=CALM)

#: Five consecutive sessions, all of whose cutoffs are long past.
SESSIONS = calendar.sessions(date(2026, 9, 14), date(2026, 9, 18))


def _dumped(state: RegimeState) -> dict[str, Any]:
    return DECISION_REGIME.dump_state(state)


def _state_hash(state: RegimeState) -> str:
    return hashlib.sha256(
        json.dumps(_dumped(state), sort_keys=True).encode()
    ).hexdigest()


def _signal(
    session: date,
    value: str | None,
    *,
    status: str = "measured",
    backfilled: bool = False,
    state: RegimeState = RISING,
    request_id: int | None = None,
    asked_about: date | None = None,
    model: str = MODEL,
) -> dict[str, Any]:
    """A row as ``jev_repo.signals_between`` returns it."""
    return {
        "session": session,
        "status": status,
        "value": value,
        "backfilled": backfilled,
        "model": model,
        "request_id": request_id if request_id is not None else 100 + session.day,
        "subject_id": (asked_about or session).isoformat(),
        "state_hash": _state_hash(state),
        "state": _dumped(state),
    }


def _asked(session: date, plan: str | None = PLAN) -> tuple[str, dict[str, Any]]:
    """A regime job that asked about ``session`` and recorded ``plan``."""
    result: dict[str, Any] = {"status": "measured"}
    if plan is not None:
        result["plan_hash"] = plan
    return (
        jev_clock.regime_job_key(DECISION_REGIME, session),
        {"status": "succeeded", "error": None, "result": result},
    )


def _reasked(
    pair: Mapping[str, Any], stratum: str | None = None, plan: str | None = PLAN
) -> tuple[str, dict[str, Any]]:
    """The re-ask job that sampled ``pair``, in ``stratum`` under ``plan``."""
    if stratum is None:
        margins = [pair["canonical_margin"]] if pair["canonical_margin"] else []
        stratum = jev_prereg.reask_stratum(pair["request_hash"], margins)
    payload: dict[str, Any] = {"request_id": pair["canonical_request_id"]}
    if stratum is not None:
        payload["stratum"] = stratum
    if plan is not None:
        payload["plan_hash"] = plan
    return (
        jev_eval.reask_job_key(pair["canonical_request_id"]),
        {"status": "succeeded", "error": None, "payload": payload},
    )


def _build(
    signals: list[dict[str, Any]],
    *,
    sessions: list[date] | None = None,
    jobs: Mapping[str, Mapping[str, Any]] | None = None,
    pairs: Mapping[str, list[dict[str, Any]]] | None = None,
    probes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    ``build_forward`` over ``signals``. Unless ``jobs`` names them itself,
    every answer was asked by a regime job under this plan and every pair
    sampled under it, as the shipped planner and forward job record them.
    """
    every: dict[str, Mapping[str, Any]] = {}
    for row in signals:
        every.update([_asked(date.fromisoformat(row["subject_id"]))])
    for model_pairs in (pairs or {}).values():
        for pair in model_pairs:
            every.update([_reasked(pair)])
    every.update(jobs or {})
    return jev_eval.build_forward(
        question_set=DECISION_REGIME,
        symbol=SYMBOL,
        sessions=SESSIONS if sessions is None else sessions,
        signals=signals,
        jobs=every,
        pairs=pairs or {},
        probes=probes or [],
    )


def _keys(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        found = {str(k) for k in value}
        for item in value.values():
            found |= _keys(item)
        return found
    if isinstance(value, list):
        found: set[str] = set()
        for item in value:
            found |= _keys(item)
        return found
    return set()


_PAIR_IDS = iter(range(1_000, 10_000))


def _pair(
    request_hash: str,
    first: str | None,
    again: str | None,
    *,
    margin: float | None,
    lag_hours: float = 24.0,
    request_id: int | None = None,
) -> dict[str, Any]:
    """A pair as ``jev_repo.probe_pairs`` returns it."""
    return {
        "canonical_request_id": request_id if request_id else next(_PAIR_IDS),
        "request_hash": request_hash,
        "canonical_valid": first is not None,
        "canonical_argmax": first,
        "canonical_margin": margin,
        "probe_status": "ok" if again is not None else "invalid",
        "probe_valid": again is not None,
        "probe_argmax": again,
        "lag_seconds": lag_hours * 3600,
    }


def _probe(row: int, valid: bool, noul: float | None) -> dict[str, Any]:
    return {
        "id": row,
        "available_at": datetime(2026, 9, 14, 13, row, tzinfo=UTC),
        "status": "ok" if valid else "error",
        "model_requested": MODEL,
        "model_answered": MODEL if valid else None,
        "valid": valid if valid else None,
        "noul": noul,
        "invalid_reason": None,
    }


def _populated() -> dict[str, Any]:
    """A report with something in every field."""
    first, second, third, fourth, _ = SESSIONS
    return _build(
        [
            _signal(first, "risk_on"),
            _signal(second, "risk_on", request_id=100 + first.day, asked_about=first),
            _signal(third, None, status="abstain", state=SIDEWAYS),
            _signal(fourth, "risk_off", backfilled=True, state=FALLING),
        ],
        pairs={
            MODEL: [
                _pair("0" * 8 + "a" * 56, "risk_on", "risk_off", margin=0.5),
                _pair("1" * 64, "risk_on", "risk_on", margin=0.1),
            ]
        },
        probes=[_probe(1, True, 0.99), _probe(2, False, None)],
    )


def _model(report: Mapping[str, Any], model: str = MODEL) -> Mapping[str, Any]:
    return report["models"][model]


class TestTheFieldListIsPinned:
    def test_the_forward_field_list_is_pinned(self) -> None:
        assert jev_eval.FORWARD_FIELDS == PINNED_FIELDS
        assert tuple(_populated()) == PINNED_FIELDS
        assert tuple(_build([], sessions=[])) == PINNED_FIELDS

    def test_each_models_field_list_is_pinned(self) -> None:
        assert jev_eval.MODEL_FIELDS == PINNED_MODEL_FIELDS
        assert tuple(_model(_populated())) == PINNED_MODEL_FIELDS

    def test_nothing_computes_a_return_a_pnl_or_a_hit_rate(self) -> None:
        keys = _keys(_populated())
        for fragment in FORBIDDEN:
            assert not [key for key in keys if fragment in key.lower()], fragment

    def test_the_harness_names_no_table_of_money(self) -> None:
        """It reads the ledger and the bars; never the book."""
        source = EVAL.read_text(encoding="utf-8")
        for table in ("daily_marks", "fills", "orders", "positions", "backtest_"):
            assert table not in source, table

    def test_the_report_names_its_plan(self) -> None:
        report = _populated()
        assert report["plan_version"] == jev_prereg.PLAN_VERSION
        assert report["plan_hash"] == jev_prereg.plan_hash()
        assert report["signal"] == "decision.regime@1:regime"
        assert report["symbol"] == "equities=SPY;bonds=IEF;commodities=GSG"

    def test_the_report_is_plain_data(self) -> None:
        report = _populated()
        assert json.loads(json.dumps(report, default=str)) is not None


class TestEverySessionIsAccountedFor:
    def test_absent_sessions_stay_in_the_denominator(self) -> None:
        first, second, third, fourth, fifth = SESSIONS
        expired = jev_clock.regime_job_key(DECISION_REGIME, third)
        report = _build(
            [_signal(first, "risk_on"), _signal(second, "neutral", state=SIDEWAYS)],
            jobs={
                expired: {
                    "status": "failed",
                    "error": "expired: the forward clock missed it",
                }
            },
        )
        assert report["sessions"] == 5
        assert report["live_measured"] == 2
        assert report["absent"] == 3
        assert report["coverage"]["k"] == 2
        assert report["coverage"]["n"] == 5
        assert report["coverage"]["share"] == pytest.approx(0.4)
        assert report["absences"] == [
            {
                "session": third.isoformat(),
                "reason": "failed: expired: the forward clock missed it",
            },
            {"session": fourth.isoformat(), "reason": "not planned"},
            {"session": fifth.isoformat(), "reason": "not planned"},
        ]

    def test_every_session_has_exactly_one_outcome(self) -> None:
        report = _populated()
        assert sum(report[o] for o in jev_eval.OUTCOMES) == report["sessions"]

    def test_a_job_with_no_error_says_so(self) -> None:
        first = SESSIONS[0]
        key = jev_clock.regime_job_key(DECISION_REGIME, first)
        report = _build([], jobs={key: {"status": "queued", "error": None}})
        assert report["absences"][0]["reason"] == (
            "its job is queued with no error recorded"
        )

    def test_a_signal_outside_the_sessions_counts_nowhere(self) -> None:
        later = date(2026, 9, 21)
        report = _build([_signal(later, "risk_on")])
        assert report["live_measured"] == 0
        assert report["models"] == {}
        assert report["distinct_states"] == {"signals": 0, "distinct": 0}


class TestALateRowIsNeverLive:
    def test_backfilled_rows_are_late_never_live(self) -> None:
        first, second, *_ = SESSIONS
        report = _build(
            [
                _signal(first, "risk_off", backfilled=True, state=FALLING),
                _signal(second, "risk_on"),
            ]
        )
        assert report["late"] == 1
        assert report["live_measured"] == 1
        assert report["coverage"]["k"] == 1
        shares = _model(report)["answer_shares"]
        assert shares["risk_off"]["k"] == 0
        assert shares["risk_on"]["n"] == 1
        assert _model(report)["baseline_agreement_sessions"]["n"] == 1

    @pytest.mark.parametrize(
        ("status", "field"),
        [
            ("measured", "live_measured"),
            ("abstain", "live_abstain"),
            ("invalid", "live_invalid"),
        ],
    )
    def test_a_live_row_counts_under_its_status(self, status: str, field: str) -> None:
        value = "risk_on" if status == "measured" else None
        report = _build([_signal(SESSIONS[0], value, status=status)])
        assert report[field] == 1
        assert report["coverage"]["k"] == (1 if status == "measured" else 0)


class TestWhatTheAnswersSay:
    def test_shares_are_of_the_live_measured_regimes_escape_excluded(self) -> None:
        first, second, third, *_ = SESSIONS
        report = _build(
            [
                _signal(first, "risk_on"),
                _signal(second, "risk_on"),
                _signal(third, None, status="abstain"),
            ]
        )
        shares = _model(report)["answer_shares"]
        assert list(shares) == ["risk_on", "neutral", "risk_off"]
        assert shares["risk_on"]["k"] == 2 and shares["risk_on"]["n"] == 2
        assert shares["neutral"]["share"] == 0.0

    def test_agreement_is_with_the_preregistered_rule(self) -> None:
        first, second, third, *_ = SESSIONS
        report = _build(
            [
                _signal(first, "risk_on", state=RISING),
                _signal(second, "risk_on", state=FALLING),
                _signal(third, "neutral", state=SIDEWAYS),
            ]
        )
        assert jev_prereg.regime_baseline(_dumped(RISING)) == "risk_on"
        assert jev_prereg.regime_baseline(_dumped(FALLING)) == "risk_off"
        agreement = _model(report)["baseline_agreement_sessions"]
        assert (agreement["k"], agreement["n"]) == (2, 3)

    def test_a_replayed_state_is_one_judgement(self) -> None:
        """
        Two sessions in one state are answered once: the second replays the
        first's answer. Agreement over distinct states weighs that judgement
        once; over sessions, twice.
        """
        first, second, *_ = SESSIONS
        report = _build(
            [
                _signal(first, "risk_on", request_id=500),
                _signal(second, "risk_on", request_id=500, asked_about=first),
            ]
        )
        assert report["distinct_states"] == {"signals": 2, "distinct": 1}
        assert (report["replayed"]["k"], report["replayed"]["n"]) == (1, 2)
        assert _model(report)["baseline_agreement_sessions"]["n"] == 2
        assert _model(report)["baseline_agreement_states"]["n"] == 1


def _one_state_twenty_sessions() -> dict[str, Any]:
    """
    Twenty sessions in one state: the first asked, the other nineteen replays
    of its answer — the reviewer's case, one judgement twenty times.
    """
    sessions = calendar.sessions(date(2026, 8, 17), date(2026, 9, 14))[:20]
    assert len(sessions) == 20
    first = sessions[0]
    return _build(
        [_signal(s, "risk_on", request_id=700, asked_about=first) for s in sessions],
        sessions=sessions,
    )


class TestSessionsAreNotTrials:
    """
    docs/08, phase C, design section 10.3: a regime's share is quoted as "n
    sessions, d distinct states", agreement as "agreement on d distinct
    states", and only forward coverage with a Wilson interval. Every session in
    one state rests on one replayed answer, so an interval over sessions
    narrows with how often one judgement repeats: twenty sessions in one state
    would state a lower bound of 0.84 from a single answer.
    """

    def test_a_share_over_sessions_carries_no_interval(self) -> None:
        report = _one_state_twenty_sessions()
        risk_on = _model(report)["answer_shares"]["risk_on"]
        assert (risk_on["k"], risk_on["n"], risk_on["distinct_states"]) == (20, 20, 1)
        assert "wilson" not in risk_on, "an interval over one judgement repeated"

    def test_agreement_over_sessions_carries_no_interval(self) -> None:
        agreement = _model(_one_state_twenty_sessions())["baseline_agreement_sessions"]
        assert (agreement["k"], agreement["n"], agreement["distinct_states"]) == (
            20,
            20,
            1,
        )
        assert "wilson" not in agreement

    def test_agreement_over_distinct_states_is_the_interval(self) -> None:
        """The one judgement, once: 1 of 1, with the width one answer earns."""
        agreement = _model(_one_state_twenty_sessions())["baseline_agreement_states"]
        assert (agreement["k"], agreement["n"]) == (1, 1)
        low, high = agreement["wilson"]
        assert low == pytest.approx(0.207, abs=0.001) and high == 1.0

    def test_the_replay_share_is_counted_not_estimated(self) -> None:
        replayed = _one_state_twenty_sessions()["replayed"]
        assert (replayed["k"], replayed["n"]) == (19, 20)
        assert "wilson" not in replayed

    def test_coverage_keeps_its_interval(self) -> None:
        coverage = _one_state_twenty_sessions()["coverage"]
        assert (coverage["k"], coverage["n"]) == (20, 20)
        assert coverage["wilson"] is not None

    def test_the_text_says_so(self) -> None:
        text = jev_eval.format_forward(_one_state_twenty_sessions())
        (share,) = [line for line in text.splitlines() if "share risk_on" in line]
        assert "Wilson" not in share
        assert "20 of 20 sessions = 1.000, over 1 distinct state" in share
        (states,) = [
            line for line in text.splitlines() if "rule, distinct states:" in line
        ]
        assert "1 of 1 = 1.000 (Wilson 95%: 0.207 to 1.000)" in states


class TestEachModelApart:
    """
    A signal's name carries its set and version, not the model, so after a
    change of pin two judges' answers share a series. Each is reported apart
    and named; neither's judgement of a state displaces the other's.
    """

    def test_two_models_are_two_blocks(self) -> None:
        first, second, *_ = SESSIONS
        report = _build(
            [
                _signal(first, "neutral", state=RISING, model="jev-1.13.0"),
                _signal(second, "risk_on", state=RISING, model="jev-1.14.0"),
            ]
        )
        assert list(report["models"]) == ["jev-1.13.0", "jev-1.14.0"]
        older, newer = (report["models"][m] for m in report["models"])
        assert older["answer_shares"]["neutral"]["k"] == 1
        assert newer["answer_shares"]["risk_on"]["k"] == 1
        assert jev_prereg.regime_baseline(_dumped(RISING)) == "risk_on"
        assert older["baseline_agreement_states"]["k"] == 0
        assert newer["baseline_agreement_states"]["k"] == 1, (
            "the second model's judgement of a state the first judged was dropped"
        )

    def test_the_text_names_each_model(self) -> None:
        first, second, *_ = SESSIONS
        text = jev_eval.format_forward(
            _build(
                [
                    _signal(first, "neutral", model="jev-1.13.0"),
                    _signal(second, "risk_on", model="jev-1.14.0"),
                ]
            )
        )
        assert "jev-1.13.0: 1 live measured sessions" in text
        assert "jev-1.14.0: 1 live measured sessions" in text


class TestAnAnswerIsScoredUnderThePlanThatRegisteredIt:
    """
    docs/08: after the first regime answer, a change of plan is recorded as
    one — what was analysed under the old plan stays under it. The regime job
    records the plan in force when it asks, and agreement is scored only over
    answers first recorded under the plan the report runs.
    """

    def test_an_answer_recorded_under_another_plan_is_not_scored(self) -> None:
        first, second, third, *_ = SESSIONS
        older = "e" * 64
        report = _build(
            [
                _signal(first, "risk_on", state=RISING),
                _signal(second, "risk_off", state=FALLING),
                _signal(third, "neutral", state=SIDEWAYS),
            ],
            jobs=dict([_asked(first, older), _asked(second, None)]),
        )
        figures = _model(report)
        assert figures["live_measured"] == 3
        assert sum(v["k"] for v in figures["answer_shares"].values()) == 3
        assert figures["baseline_agreement_sessions"]["n"] == 1
        assert figures["baseline_agreement_states"]["n"] == 1
        assert figures["not_scored"] == {older: 1, jev_eval.UNKNOWN_PLAN: 1}

    def test_a_replay_is_scored_under_the_plan_its_answer_was_asked_under(
        self,
    ) -> None:
        """
        The second session's own job ran under this plan, but the answer it
        replays was asked, and seen, under the older one.
        """
        first, second, *_ = SESSIONS
        older = "e" * 64
        report = _build(
            [
                _signal(first, "risk_on", request_id=500),
                _signal(second, "risk_on", request_id=500, asked_about=first),
            ],
            jobs=dict([_asked(first, older), _asked(second, PLAN)]),
        )
        assert _model(report)["baseline_agreement_sessions"]["n"] == 0
        assert _model(report)["not_scored"] == {older: 2}

    def test_the_text_names_what_was_not_scored(self) -> None:
        first = SESSIONS[0]
        text = jev_eval.format_forward(
            _build([_signal(first, "risk_on")], jobs=dict([_asked(first, "e" * 64)]))
        )
        assert "not scored: 1 sessions answered under plan eeeeeeeeeeee" in text


class TestTheFlipRates:
    def test_the_strata_are_never_pooled(self) -> None:
        uniform = "0" * 8 + "b" * 56
        assert jev_prereg.reask_stratum(uniform, []) == "uniform"
        low = "1" * 64
        assert jev_prereg.reask_stratum(low, [0.1]) == "low_margin"
        report = _build(
            [],
            pairs={
                MODEL: [
                    _pair(uniform, "risk_on", "risk_off", margin=0.6, lag_hours=24),
                    _pair(uniform, "risk_on", "risk_on", margin=0.6, lag_hours=30),
                    _pair(low, "risk_on", "risk_on", margin=0.1, lag_hours=25),
                    _pair(low, "risk_on", None, margin=0.1, lag_hours=26),
                ]
            },
        )
        rates = report["flip_rates"][MODEL]
        assert rates["uniform"]["k"] == 1 and rates["uniform"]["n"] == 2
        assert rates["uniform"]["median_lag_hours"] == pytest.approx(27.0)
        assert rates["low_margin"]["k"] == 0 and rates["low_margin"]["n"] == 1
        assert rates["low_margin"]["not_compared"] == 1
        assert rates["other_plans"] == 0

    def test_no_pairs_is_not_measured(self) -> None:
        rates = _build([], pairs={MODEL: []})["flip_rates"][MODEL]
        for stratum in ("uniform", "low_margin"):
            assert rates[stratum]["share"] is None
            assert rates[stratum]["wilson"] is None
            assert rates[stratum]["median_lag_hours"] is None

    def test_a_pair_counts_in_the_stratum_it_was_sampled_in(self) -> None:
        """
        What the planner recorded, not a recomputation from one question's
        margin: a request drawn into the low-margin stratum by another of its
        questions stays there.
        """
        pair = _pair("1" * 64, "risk_on", "risk_off", margin=0.6)
        assert jev_prereg.reask_stratum(pair["request_hash"], [0.6]) is None
        report = _build(
            [],
            pairs={MODEL: [pair]},
            jobs=dict([_reasked(pair, stratum="low_margin")]),
        )
        assert report["flip_rates"][MODEL]["low_margin"]["k"] == 1

    @pytest.mark.parametrize("plan", ["e" * 64, None])
    def test_a_pair_sampled_under_another_plan_is_in_no_rate(
        self, plan: str | None
    ) -> None:
        pair = _pair("1" * 64, "risk_on", "risk_off", margin=0.1)
        report = _build(
            [], pairs={MODEL: [pair]}, jobs=dict([_reasked(pair, plan=plan)])
        )
        rates = report["flip_rates"][MODEL]
        assert rates["low_margin"]["n"] == rates["low_margin"]["not_compared"] == 0
        assert rates["other_plans"] == 1

    def test_a_re_ask_with_no_answer_is_counted_as_not_compared(self) -> None:
        """
        A re-ask refused whole or failed is a pair too
        (``jev_repo.probe_pairs``), so a vendor that malformed every re-ask
        cannot read as though none was made.
        """
        pair = _pair("1" * 64, "risk_on", None, margin=0.1)
        pair.update(probe_status="error", probe_valid=None)
        rates = _build([], pairs={MODEL: [pair]})["flip_rates"][MODEL]
        assert rates["low_margin"]["n"] == 0
        assert rates["low_margin"]["not_compared"] == 1


class TestTheProbeSeries:
    def test_a_day_the_probe_did_not_answer_is_in_the_series(self) -> None:
        series = _build([], probes=[_probe(1, True, 0.99), _probe(2, False, None)])[
            "probe_series"
        ]
        assert [entry["p_true"] for entry in series] == [0.99, None]
        assert series[1]["not_measured_because"] == "error"
        assert series[0]["not_measured_because"] is None


class TestNothingMeasuredIsNotZero:
    def test_a_figure_over_nothing_is_none(self) -> None:
        figure = jev_eval.figure(0, 0)
        assert figure["share"] is None and figure["wilson"] is None
        assert jev_eval.count(0, 0)["share"] is None

    def test_an_empty_report_measures_nothing(self) -> None:
        report = _build([], sessions=[])
        assert report["coverage"]["share"] is None
        assert report["replayed"]["share"] is None
        assert report["models"] == {}

    def test_a_model_with_nothing_scored_measures_no_agreement(self) -> None:
        first = SESSIONS[0]
        figures = _model(
            _build([_signal(first, "risk_on")], jobs=dict([_asked(first, None)]))
        )
        assert figures["baseline_agreement_sessions"]["share"] is None
        assert figures["baseline_agreement_states"]["share"] is None
        assert figures["baseline_agreement_states"]["wilson"] is None

    def test_the_formatter_never_prints_0_for_none(self) -> None:
        text = jev_eval.format_forward(_build([], sessions=[]))
        assert "not measured" in text
        assert "0.000" not in text
        assert " of 0 = " not in text, "a share was printed for a figure over nothing"
        assert text.count("not measured (n = 0)") == 2, "coverage and replays"

    def test_the_formatter_says_an_unscored_agreement_is_not_measured(
        self,
    ) -> None:
        first = SESSIONS[0]
        text = jev_eval.format_forward(
            _build([_signal(first, "risk_on")], jobs=dict([_asked(first, None)]))
        )
        assert text.count("not measured (n = 0)") == 2, "both agreements"
        assert " of 0 " not in text

    def test_a_genuine_zero_is_printed_as_zero(self) -> None:
        text = jev_eval.format_forward(_build([], sessions=list(SESSIONS[:3])))
        assert "coverage (live measured / sessions): 0 of 3 = 0.000" in text

    @pytest.mark.parametrize(
        ("value", "printed"),
        [(None, "not measured"), (0, "0"), (0.0, "0.000"), (0.25, "0.250")],
    )
    def test_said(self, value: Any, printed: str) -> None:
        assert jev_eval.said(value) == printed

    def test_the_status_formatter_says_not_measured(self) -> None:
        text = jev_eval.format_status(
            {
                "programme_enabled": False,
                "jev_enabled": False,
                "areas": {"decisions": False},
                "send_internal_detail": False,
                "model": None,
                "daily_request_budget": 0,
                "max_state_tokens": 0,
                "lanes": {"decision": {"share": 0, "spent_today": 0}},
                "today": {
                    "calls": 0,
                    "requests": 0,
                    "answers": 0,
                    "validity_rate": None,
                    "latency_ms": {"p50": None, "n": 0},
                },
                "plan_version": 1,
                "plan_hash": jev_prereg.plan_hash(),
            }
        )
        assert "model not measured" in text
        assert "validity not measured over 0 answers" in text
        assert "latency p50 not measured ms over 0" in text


class TestTheSeriesStartsAtItsOwnVersion:
    async def test_the_report_starts_at_the_registered_versions_first_job(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        A version bump starts a new series: counted from the first job of
        every version, the new one's coverage would hold every session since
        the old one's first job as absent, "not planned".
        """
        seen: dict[str, Any] = {}

        async def first_job_session(
            conn: Any,
            kind: str,
            *,
            question_set: str | None = None,
            version: int | None = None,
        ) -> date | None:
            seen.update(kind=kind, question_set=question_set, version=version)
            return None

        monkeypatch.setattr(jev_repo, "first_job_session", first_job_session)
        report = await jev_eval.forward_report(
            object(), since=None, now=datetime(2026, 9, 26, tzinfo=UTC)
        )
        assert seen == {
            "kind": "jev_regime",
            "question_set": DECISION_REGIME.name,
            "version": DECISION_REGIME.version,
        }
        assert report["sessions"] == 0


class TestTheSessionsCounted:
    def test_only_sessions_whose_cutoff_has_passed(self) -> None:
        session = date(2026, 9, 28)
        cutoff = jev_clock.decision_cutoff(session)
        before = jev_eval.sessions_between(session, cutoff - timedelta(seconds=1))
        at = jev_eval.sessions_between(session, cutoff)
        assert before == [] and at == [session]

    def test_weekends_and_holidays_are_not_sessions(self) -> None:
        now = datetime(2026, 12, 1, tzinfo=UTC)
        found = jev_eval.sessions_between(date(2026, 11, 20), now)
        assert date(2026, 11, 26) not in found, "Thanksgiving"
        assert date(2026, 11, 22) not in found, "a Sunday"
        assert date(2026, 11, 27) in found, "a half day is a session"

    def test_a_start_after_now_counts_nothing(self) -> None:
        now = datetime(2026, 9, 1, tzinfo=UTC)
        assert jev_eval.sessions_between(date(2026, 9, 14), now) == []


# ---------------------------------------------------------------------------
# forward-audit
# ---------------------------------------------------------------------------


def _panel(session: date, n: int = 1_400) -> PricePanel:
    sessions = pd.bdate_range(end=pd.Timestamp(session), periods=n)
    rows = []
    for symbol in REFERENCE_SYMBOLS:
        for i, day in enumerate(sessions):
            close = 100.0 * math.exp(0.001 * i)
            rows.append((symbol, day.date(), close, close, close, close, 1e6, close))
    return PricePanel.from_bars(rows, as_of=session)


class TestTheAudit:
    def test_the_sleeves_are_read_back_from_the_symbol(self) -> None:
        assert jev_eval._sleeves_of(SYMBOL) == dict(REFERENCE_SLEEVES)

    def test_drift_names_the_descriptors_that_moved(self) -> None:
        recorded = _dumped(RISING)
        rebuilt = _dumped(
            RegimeState(
                equities=_sleeve("above", 3, "none", "up"),
                bonds=CALM,
                commodities=_sleeve("near", 3, "none", "down"),
            )
        )
        assert jev_eval._drift(recorded, rebuilt) == [
            "equities.volatility_quintile",
            "commodities.momentum",
        ]
        assert jev_eval._drift(recorded, recorded) == []

    async def test_each_state_is_rebuilt_from_the_bars_stored_now(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Agree, drift naming the descriptors that moved, or cannot rebuild with
        the reason, each read with the sleeves the signal's symbol names.
        """
        from src.programme import jev_features

        first, second, third, fourth, _ = SESSIONS
        panels = {
            first: _panel(first),
            second: _panel(second),
            third: None,
            fourth: _panel(fourth, n=300),
        }
        agreeing = jev_features.regime_state(_panel(first), first, REFERENCE_SLEEVES)
        rebuilt = jev_features.regime_state(_panel(second), second, REFERENCE_SLEEVES)
        assert agreeing is not None and rebuilt is not None
        other = "below" if rebuilt.bonds.trend != "below" else "above"
        moved = rebuilt.model_copy(
            update={"bonds": rebuilt.bonds.model_copy(update={"trend": other})}
        )

        async def first_job_session(
            conn: Any,
            kind: str,
            *,
            question_set: str | None = None,
            version: int | None = None,
        ) -> date:
            assert kind == "jev_regime"
            assert (question_set, version) == (
                DECISION_REGIME.name,
                DECISION_REGIME.version,
            )
            return first

        async def signals_between(conn: Any, **kwargs: Any) -> list[dict[str, Any]]:
            assert kwargs["symbol"] == SYMBOL
            return [
                _signal(first, "risk_on", state=agreeing),
                _signal(second, "risk_on", state=moved),
                _signal(third, "risk_on", state=moved),
                _signal(fourth, "risk_on", state=moved),
            ]

        async def load_regime_panel(
            conn: Any, session: date, symbols: list[str]
        ) -> PricePanel | None:
            assert symbols == sorted(REFERENCE_SLEEVES.values())
            return panels[session]

        monkeypatch.setattr(jev_repo, "first_job_session", first_job_session)
        monkeypatch.setattr(jev_repo, "signals_between", signals_between)
        monkeypatch.setattr(jev_clock, "load_regime_panel", load_regime_panel)
        report = await jev_eval.forward_audit(
            object(), since=None, now=datetime(2026, 9, 26, tzinfo=UTC)
        )
        verdicts = [(e["session"], e["verdict"]) for e in report["sessions"]]
        assert verdicts == [
            (first.isoformat(), "agree"),
            (second.isoformat(), "drift"),
            (third.isoformat(), "cannot rebuild"),
            (fourth.isoformat(), "cannot rebuild"),
        ]
        assert report["sessions"][1]["moved"] == ["bonds.trend"]
        assert report["sessions"][2]["why"] == "no bar is stored"
        assert "of the 1,280 closes it needs" in report["sessions"][3]["why"]
        assert (report["agree"], report["drift"], report["cannot_rebuild"]) == (1, 1, 2)


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


class _Transaction:
    def __init__(self, record: dict[str, Any], kwargs: dict[str, Any]) -> None:
        record["transaction"] = kwargs

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: object) -> None:
        return None


class _Conn:
    def __init__(self, record: dict[str, Any]) -> None:
        self.record = record

    def transaction(self, **kwargs: Any) -> _Transaction:
        return _Transaction(self.record, kwargs)

    async def close(self) -> None:
        self.record["closed"] = True


class TestTheCommandLine:
    def test_a_usage_error_is_2(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert jev_eval.main([]) == jev_eval.EXIT_USAGE == 2
        assert jev_eval.main(["bogus"]) == 2
        assert jev_eval.main(["forward", "--since", "not-a-date"]) == 2

    def test_help_is_not_a_failure(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert jev_eval.main(["--help"]) == jev_eval.EXIT_OK == 0

    def test_no_database_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert jev_eval.main(["status"]) == jev_eval.EXIT_REFUSED == 1
        assert "DATABASE_URL" in capsys.readouterr().err

    def test_every_command_reads_in_one_read_only_snapshot(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        record: dict[str, Any] = {}

        async def connect(dsn: str) -> _Conn:
            record["dsn"] = dsn
            return _Conn(record)

        async def database_now(conn: Any) -> datetime:
            return datetime(2026, 9, 26, tzinfo=UTC)

        async def forward_report(conn: Any, *, since: Any, now: Any) -> dict[str, Any]:
            return _build([], sessions=[])

        monkeypatch.setenv("DATABASE_URL", "postgresql://reader@db/trader")
        monkeypatch.setattr(jev_eval.asyncpg, "connect", connect)
        monkeypatch.setattr(jev_clock, "database_now", database_now)
        monkeypatch.setattr(jev_eval, "forward_report", forward_report)
        assert jev_eval.main(["forward", "--json"]) == 0
        assert record["transaction"] == {
            "isolation": "repeatable_read",
            "readonly": True,
        }
        assert record["closed"] is True
        printed = json.loads(capsys.readouterr().out)
        assert tuple(sorted(printed)) == tuple(sorted(PINNED_FIELDS))

    def test_the_one_variable_it_reads_is_database_url(self) -> None:
        """No key, no model setting: the harness asks nothing, so it needs none."""
        tree = ast.parse(EVAL.read_text(encoding="utf-8"))
        read = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in {"environ", "getenv"}:
                read.add(node.attr)
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value.isupper() and node.value.endswith(("_KEY", "_URL")):
                    read.add(node.value)
        assert read == {"environ", "DATABASE_URL"}
