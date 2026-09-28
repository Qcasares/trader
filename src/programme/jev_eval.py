"""
jev_eval.py
-----------
The Jev evaluation harness, from the command line.

    DATABASE_URL=… python -m src.programme.jev_eval status
    DATABASE_URL=… python -m src.programme.jev_eval forward [--since DATE] [--json]
    DATABASE_URL=… python -m src.programme.jev_eval forward-audit [--since DATE]

Never ``src/cli.py``: the research CLI loads the engine, and this loads the
ledger. Runner-only, like everything that reads the ledger for the programme,
so the API cannot load it.

It holds no key and makes no call
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Every figure here is computed from rows the lanes wrote in ordinary operation,
under every switch; nothing here asks Jev anything. The environment it reads is
``DATABASE_URL`` and nothing else, every command runs in a read-only
transaction, and its import closure reaches no lane, no client and no model
runner (``tests/unit/test_import_boundaries.py``,
``test_the_harness_holds_no_key_and_reaches_no_client``).
Phase C9 adds the commands that label and evaluate, which write labels and
evaluations and nothing else; C4's three only read.

What the forward report may say
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
``forward`` accounts for every NYSE session since the first job of the
registered set's version was planned whose cutoff has passed: measured,
abstained or invalid on time, late (``backfilled``, which the database
decided), or absent, with the reason its job's error gives, or "not planned".
Absent sessions stay in the denominator of its coverage, and a late row is
never counted as live. **Nothing computes a return, a P&L or a hit rate**: the
answers are collected and not consumed, and a regime is not a forecast.
``tests/unit/test_jev_eval.py`` pins the report's fields.

Each figure is quoted as what it is (docs/08, phase C, design section 10.3):

* **Coverage** — live measured sessions of all the sessions — carries a Wilson
  interval at ``jev_prereg.REPORT_CI``, as do the flip rates, each pair a
  request of its own.
* **Shares and agreement over sessions carry none.** Every session in one
  state rests on the same replayed answer, so sessions are not independent
  trials, and an interval over them narrows with how often one judgement
  repeats: twenty sessions in one state would state a lower bound of 0.84
  from a single answer. They are counted, with the distinct states they rest
  on beside them. Agreement over distinct states, each one judgement, is the
  one that carries an interval.
* **By model.** A signal's name carries its set and version but not the
  model, so each model's answers are reported apart and named, never pooled:
  after a change of pin they are two judges.
* **Under the plan that registered them.** Agreement is scored by
  ``jev_prereg.REGIME_BASELINE_RULE`` only over answers first recorded under
  the plan this report runs, which the regime job records in its result when
  it asks; an answer recorded under another plan, or with no plan recorded,
  is counted apart by the plan it was recorded under and never scored by a
  rule registered after it. A flip rate likewise counts only the re-asks
  sampled under this plan, in the stratum they were sampled in, which the
  planner records in the re-ask's payload. The report names its plan.

A figure over nothing is "not measured", never 0 (``jev_stats``), and the text
formatter prints it so.

``forward-audit`` rebuilds each recorded state from the bars dated on or before
its session as they are stored now, and says whether it agrees, which
descriptors drifted, or why it cannot be rebuilt: a measure of how far the
stored history has moved under the answers since they were recorded. A
distribution re-bases a sleeve's closes by one factor, and every descriptor is
a ratio of closes or a statistic of log returns, so a re-basing never drifts a
state (``tests/unit/test_jev_features.py::TestARebasingMovesNoDescriptor``):
drift is an uneven change — a revision, a late adjustment, a stitch mended, a
gap filled — and is data trouble (docs/08 open item 48).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import statistics
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time
from typing import Any

import asyncpg

from src.config import normalise_dsn
from src.core import calendar
from src.programme import (
    flags,
    jev_catalogue,
    jev_clock,
    jev_features,
    jev_prereg,
    jev_questions,
    jev_repo,
    jev_stats,
)

logger = logging.getLogger(__name__)

#: The set the forward clock asks, its question, and the probe whose daily
#: series the report shows.
REGIME_SET_NAME = "decision.regime"
REGIME_QUESTION = "regime"
PROBE_SET_NAME = "probe.connectivity"

#: Every field of the forward report, pinned by ``tests/unit/test_jev_eval.py``
#: so that a return, a P&L or a hit rate cannot arrive without a reviewer
#: reading the test that refuses it.
FORWARD_FIELDS: tuple[str, ...] = (
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

#: Every field of one model's block of the forward report, pinned beside it.
MODEL_FIELDS: tuple[str, ...] = (
    "live_measured",
    "distinct_states",
    "answer_shares",
    "baseline_agreement_sessions",
    "baseline_agreement_states",
    "not_scored",
)

#: What a session came to, in the report's words.
OUTCOMES = ("live_measured", "live_abstain", "live_invalid", "late", "absent")

#: The re-ask strata, in the order the plan samples them; never pooled.
STRATA = ("uniform", "low_margin")

#: How an answer whose job recorded no plan is counted in ``not_scored``.
UNKNOWN_PLAN = "unknown"

#: The exit codes: a command that ran, one the harness refused, a usage error.
EXIT_OK, EXIT_REFUSED, EXIT_USAGE = 0, 1, 2


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------


def figure(k: int, n: int) -> dict[str, Any]:
    """
    ``k`` of ``n`` independent trials, as the report carries such a
    proportion: the counts, the share, and its Wilson interval at
    ``jev_prereg.REPORT_CI``, the last two ``None`` — not measured — when
    ``n`` is 0.
    """
    interval = jev_stats.wilson(k, n, jev_prereg.REPORT_CI)
    return {
        "k": k,
        "n": n,
        "share": jev_stats.proportion(k, n),
        "wilson": list(interval) if interval is not None else None,
        "level": jev_prereg.REPORT_CI,
    }


def count(k: int, n: int) -> dict[str, Any]:
    """
    ``k`` of ``n`` where the ``n`` are not independent trials — sessions,
    many of which repeat one replayed judgement — so no interval: the counts
    and the share, ``None`` when ``n`` is 0. An interval over them would
    narrow with how often one answer repeats.
    """
    return {"k": k, "n": n, "share": jev_stats.proportion(k, n)}


def sessions_between(start: date, now: datetime) -> list[date]:
    """
    The NYSE sessions from ``start`` whose decision cutoff has passed at
    ``now``: every session the forward clock has had its chance at. A session
    whose cutoff is still ahead is pending, and in no count.
    """
    first, last = calendar.bounds()
    end = min(now.astimezone(jev_clock.EXCHANGE_TZ).date(), last)
    start = max(start, first)
    if end < start:
        return []
    return [
        session
        for session in calendar.sessions(start, end)
        if jev_clock.decision_cutoff(session) <= now
    ]


def build_forward(
    *,
    question_set: jev_questions.QuestionSet,
    symbol: str,
    sessions: Sequence[date],
    signals: Sequence[Mapping[str, Any]],
    jobs: Mapping[str, Mapping[str, Any]],
    pairs: Mapping[str, Sequence[Mapping[str, Any]]],
    probes: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """
    The forward report from rows already read: pure, so every rule it follows
    is tested without a database.

    ``sessions`` is the denominator; ``signals`` the recorded signals of the
    series, joined to their answers and requests (``jev_repo.signals_between``);
    ``jobs`` the job rows by their keys — each session's regime job, the regime
    job of every session an answer was first asked about, and the re-ask job
    of every pair; ``pairs`` each model's canonical-and-re-ask pairs
    (``jev_repo.probe_pairs``); ``probes`` the daily probe's rows.
    """
    by_session = {row["session"]: row for row in signals}
    counts = dict.fromkeys(OUTCOMES, 0)
    absences: list[dict[str, Any]] = []
    for session in sessions:
        row = by_session.get(session)
        outcome = _outcome(row)
        counts[outcome] += 1
        if outcome == "absent":
            key = jev_clock.regime_job_key(question_set, session)
            absences.append(
                {
                    "session": session.isoformat(),
                    "reason": _absent_reason(jobs.get(key)),
                }
            )

    in_range = [by_session[s] for s in sessions if s in by_session]
    live_measured = [row for row in in_range if _outcome(row) == "live_measured"]
    answered = [row for row in in_range if row.get("request_id") is not None]
    replayed = [
        row for row in answered if row.get("subject_id") != row["session"].isoformat()
    ]
    plan = jev_prereg.plan_hash()
    by_model: dict[str, list[Mapping[str, Any]]] = {}
    for row in live_measured:
        by_model.setdefault(str(row["model"]), []).append(row)
    return {
        "plan_version": jev_prereg.PLAN_VERSION,
        "plan_hash": plan,
        "signal": jev_clock.regime_signal(question_set, REGIME_QUESTION),
        "symbol": symbol,
        "since": sessions[0].isoformat() if sessions else None,
        "until": sessions[-1].isoformat() if sessions else None,
        "sessions": len(sessions),
        **counts,
        "coverage": figure(counts["live_measured"], len(sessions)),
        "absences": absences,
        "distinct_states": {
            "signals": len(answered),
            "distinct": len({row["state_hash"] for row in answered}),
        },
        "replayed": count(len(replayed), len(answered)),
        "models": {
            model: _model_figures(question_set, rows, jobs, plan)
            for model, rows in sorted(by_model.items())
        },
        "flip_rates": {
            model: _flip_rates(model_pairs, jobs, plan)
            for model, model_pairs in sorted(pairs.items())
        },
        "probe_series": _probe_series(probes),
    }


def _outcome(row: Mapping[str, Any] | None) -> str:
    """What a session came to: absent without a row, late if the database says
    so, and otherwise its status, live."""
    if row is None:
        return "absent"
    if row["backfilled"]:
        return "late"
    return f"live_{row['status']}"


def _absent_reason(job: Mapping[str, Any] | None) -> str:
    """Why a session has no row, from its job: the job's error, its state, or
    that it was never planned."""
    if job is None:
        return "not planned"
    if job.get("error"):
        return f"{job['status']}: {job['error']}"
    return f"its job is {job['status']} with no error recorded"


def _states(rows: Sequence[Mapping[str, Any]]) -> int:
    """How many distinct states ``rows`` rest on."""
    return len({row["state_hash"] for row in rows})


def _model_figures(
    question_set: jev_questions.QuestionSet,
    measured: Sequence[Mapping[str, Any]],
    jobs: Mapping[str, Mapping[str, Any]],
    plan: str,
) -> dict[str, Any]:
    """
    One model's live measured sessions: the regimes' shares, and agreement
    with the baseline rule over the answers first recorded under ``plan``,
    the others counted by the plan they were recorded under.
    """
    scored = []
    not_scored: dict[str, int] = {}
    for row in measured:
        recorded_under = _answer_plan(question_set, row, jobs)
        if recorded_under == plan:
            scored.append(row)
        else:
            label = recorded_under or UNKNOWN_PLAN
            not_scored[label] = not_scored.get(label, 0) + 1
    return {
        "live_measured": len(measured),
        "distinct_states": _states(measured),
        "answer_shares": _answer_shares(question_set, measured),
        "baseline_agreement_sessions": _agreement_over_sessions(scored),
        "baseline_agreement_states": _agreement_over_states(scored),
        "not_scored": dict(sorted(not_scored.items())),
    }


def _answer_plan(
    question_set: jev_questions.QuestionSet,
    row: Mapping[str, Any],
    jobs: Mapping[str, Mapping[str, Any]],
) -> str | None:
    """
    The plan in force when a session's answer was first recorded: the plan
    the regime job that asked it wrote in its result. A replayed session's
    answer was asked about another session, whose job is the one that asked.
    ``None`` when no such job, or no plan in it, is on record.
    """
    try:
        asked_about = date.fromisoformat(str(row.get("subject_id")))
    except ValueError:
        return None
    job = jobs.get(jev_clock.regime_job_key(question_set, asked_about)) or {}
    result = job.get("result") or {}
    recorded = result.get("plan_hash") if isinstance(result, Mapping) else None
    return recorded if isinstance(recorded, str) else None


def _answer_shares(
    question_set: jev_questions.QuestionSet, measured: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """
    Each regime's share of one model's live measured sessions, and how many
    distinct states those sessions rest on; the escape is never among them,
    since an escape is an abstention. Counted, not given an interval: a state
    the market sat in for twenty sessions is one answer, twenty times.
    """
    escape = question_set.escape_options.get(REGIME_QUESTION)
    criteria = dict(question_set.questions)[REGIME_QUESTION]["criteria"]
    options = [option for option in criteria if option != escape]
    shares = {}
    for option in options:
        named = [row for row in measured if row["value"] == option]
        shares[option] = {
            **count(len(named), len(measured)),
            "distinct_states": _states(named),
        }
    return shares


def _agrees(row: Mapping[str, Any]) -> bool:
    return jev_prereg.regime_baseline(row["state"]) == row["value"]


def _agreement_over_sessions(scored: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """
    Sessions on which the regime Jev named is the baseline rule's, counted,
    with the distinct states they rest on: no interval, since sessions in one
    state repeat one judgement.
    """
    return {
        **count(sum(1 for row in scored if _agrees(row)), len(scored)),
        "distinct_states": _states(scored),
    }


def _agreement_over_states(scored: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """
    The same over distinct states, each one judgement — one model's canonical
    answer for the state, which every session in it replays — so this is the
    agreement that carries an interval.
    """
    by_state: dict[str, Mapping[str, Any]] = {}
    for row in scored:
        by_state.setdefault(row["state_hash"], row)
    return figure(sum(1 for row in by_state.values() if _agrees(row)), len(by_state))


def _flip_rates(
    pairs: Sequence[Mapping[str, Any]],
    jobs: Mapping[str, Mapping[str, Any]],
    plan: str,
) -> dict[str, Any]:
    """
    Each re-ask stratum's flip rate, never pooled: of the pairs whose two
    answers were both measured, those whose argmax moved, with the pairs that
    could not be compared counted apart — a re-ask refused whole, failed or
    refused before it was sent among them — and the median lag in hours.

    A pair counts in the stratum its re-ask was sampled in, and only when it
    was sampled under ``plan``, both of which the planner records in the
    re-ask's payload; every other pair is counted in ``other_plans`` and in
    no rate.
    """
    strata: dict[str, list[Mapping[str, Any]]] = {name: [] for name in STRATA}
    other_plans = 0
    for pair in pairs:
        job = jobs.get(reask_job_key(pair["canonical_request_id"])) or {}
        payload = job.get("payload") or {}
        if not isinstance(payload, Mapping):
            payload = {}
        stratum = payload.get("stratum")
        if payload.get("plan_hash") != plan or stratum not in strata:
            other_plans += 1
            continue
        strata[stratum].append(pair)
    rates: dict[str, Any] = {}
    for stratum, members in strata.items():
        compared = [p for p in members if p["canonical_valid"] and p["probe_valid"]]
        flipped = sum(1 for p in compared if p["canonical_argmax"] != p["probe_argmax"])
        lags = [p["lag_seconds"] / 3600 for p in compared]
        rates[stratum] = {
            **figure(flipped, len(compared)),
            "not_compared": len(members) - len(compared),
            "median_lag_hours": statistics.median(lags) if lags else None,
        }
    rates["other_plans"] = other_plans
    return rates


def reask_job_key(request_id: int) -> str:
    """``jev_reask:{request id}``: the re-ask job of one canonical request."""
    return f"jev_reask:{request_id}"


def _probe_series(probes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The daily probe, one entry a request: its stated p(true) where valid."""
    series = []
    for row in probes:
        valid = bool(row.get("valid"))
        series.append(
            {
                "request_id": row["id"],
                "at": row["available_at"].isoformat(),
                "status": row["status"],
                "model": row.get("model_answered") or row.get("model_requested"),
                "p_true": row["noul"] if valid else None,
                "not_measured_because": (
                    None if valid else row.get("invalid_reason") or row["status"]
                ),
            }
        )
    return series


# ---------------------------------------------------------------------------
# Reading the rows
# ---------------------------------------------------------------------------


def _regime_set() -> jev_questions.QuestionSet:
    return jev_questions.get(REGIME_SET_NAME)


async def _first_session(
    conn: asyncpg.Connection, question_set: jev_questions.QuestionSet
) -> date | None:
    """Where the registered version's series starts: its own first job."""
    return await jev_repo.first_job_session(
        conn,
        jev_clock.REGIME_KIND,
        question_set=question_set.name,
        version=question_set.version,
    )


async def forward_report(
    conn: asyncpg.Connection, *, since: date | None, now: datetime
) -> dict[str, Any]:
    """Read the rows the forward report is built from, and build it."""
    question_set = _regime_set()
    signal = jev_clock.regime_signal(question_set, REGIME_QUESTION)
    symbol = jev_clock.sleeve_symbol()
    first = await _first_session(conn, question_set)
    start = since or first
    sessions = sessions_between(start, now) if start is not None else []
    signals: list[dict[str, Any]] = []
    if sessions:
        signals = await jev_repo.signals_between(
            conn, signal=signal, symbol=symbol, start=sessions[0], end=sessions[-1]
        )
    models = sorted({row["model"] for row in signals})
    pairs = {
        model: await jev_repo.probe_pairs(
            conn,
            question_set=question_set.name,
            version=question_set.version,
            question_key=REGIME_QUESTION,
            model=model,
        )
        for model in models
    }
    keys = {jev_clock.regime_job_key(question_set, s) for s in sessions}
    for row in signals:
        try:
            asked_about = date.fromisoformat(str(row.get("subject_id")))
        except ValueError:
            continue
        keys.add(jev_clock.regime_job_key(question_set, asked_about))
    for model_pairs in pairs.values():
        keys.update(reask_job_key(p["canonical_request_id"]) for p in model_pairs)
    jobs = await jev_repo.job_outcomes(conn, sorted(keys)) if keys else {}
    probes = []
    if sessions:
        probes = await jev_repo.probe_series(
            conn,
            question_set=PROBE_SET_NAME,
            since=datetime.combine(sessions[0], time.min, UTC),
        )
    return build_forward(
        question_set=question_set,
        symbol=symbol,
        sessions=sessions,
        signals=signals,
        jobs=jobs,
        pairs=pairs,
        probes=probes,
    )


async def forward_audit(
    conn: asyncpg.Connection, *, since: date | None, now: datetime
) -> dict[str, Any]:
    """
    Each recorded regime state beside the state its session's bars give now:
    ``agree``, ``drift`` with the descriptors that moved, or ``cannot rebuild``
    with the reason. Read with the instruments the signal was recorded under,
    which its symbol names, so a series is audited with its own sleeves.
    """
    question_set = _regime_set()
    signal = jev_clock.regime_signal(question_set, REGIME_QUESTION)
    symbol = jev_clock.sleeve_symbol()
    first = await _first_session(conn, question_set)
    start = since or first
    sessions = sessions_between(start, now) if start is not None else []
    rows = []
    if sessions:
        rows = await jev_repo.signals_between(
            conn, signal=signal, symbol=symbol, start=sessions[0], end=sessions[-1]
        )
    sleeves = _sleeves_of(symbol)
    audited = []
    for row in rows:
        if row.get("state") is None:
            continue
        session = row["session"]
        panel = await jev_clock.load_regime_panel(
            conn, session, sorted(sleeves.values())
        )
        if panel is None:
            audited.append(_audited(session, "cannot rebuild", why="no bar is stored"))
            continue
        rebuilt = jev_features.regime_state(panel, session, sleeves)
        if rebuilt is None:
            why = jev_features.regime_state_problem(panel, session, sleeves)
            audited.append(_audited(session, "cannot rebuild", why=why))
            continue
        moved = _drift(row["state"], question_set.dump_state(rebuilt))
        audited.append(_audited(session, "drift" if moved else "agree", moved=moved))
    return {
        "signal": signal,
        "symbol": symbol,
        "states": len(audited),
        "agree": sum(1 for a in audited if a["verdict"] == "agree"),
        "drift": sum(1 for a in audited if a["verdict"] == "drift"),
        "cannot_rebuild": sum(1 for a in audited if a["verdict"] == "cannot rebuild"),
        "sessions": audited,
    }


def _sleeves_of(symbol: str) -> dict[str, str]:
    """The sleeves a signal's symbol names: ``equities=SPY;…`` read back."""
    return dict(part.split("=", 1) for part in symbol.split(";"))


def _audited(
    session: date, verdict: str, *, moved: Sequence[str] = (), why: str | None = None
) -> dict[str, Any]:
    return {
        "session": session.isoformat(),
        "verdict": verdict,
        "moved": list(moved),
        "why": why,
    }


def _drift(recorded: Mapping[str, Any], rebuilt: Mapping[str, Any]) -> list[str]:
    """The descriptor paths whose labels differ between two states."""
    moved = []
    for sleeve in jev_questions.SLEEVES:
        for descriptor in sorted(set(recorded[sleeve]) | set(rebuilt[sleeve])):
            if recorded[sleeve].get(descriptor) != rebuilt[sleeve].get(descriptor):
                moved.append(f"{sleeve}.{descriptor}")
    return moved


async def status_report(conn: asyncpg.Connection) -> dict[str, Any]:
    """
    Every Jev switch through its fail-closed reader, the pin, each lane's share
    of the day's budget and what it has spent, and today's traffic.
    """
    budget = await flags.jev_daily_request_budget(conn)
    lanes = {}
    for lane in jev_catalogue.LANES:
        share = jev_catalogue.lane_budget(budget, lane)
        spent = await jev_repo.requests_today(conn, lane)
        lanes[lane] = {"share": share, "spent_today": spent}
    return {
        "programme_enabled": await flags.programme_enabled(conn),
        "jev_enabled": await flags.jev_enabled(conn),
        "areas": {
            area: await flags.jev_area_enabled(conn, area)
            for area in jev_catalogue.AREAS
        },
        "send_internal_detail": await flags.jev_send_internal_detail(conn),
        "model": await flags.jev_model(conn),
        "daily_request_budget": budget,
        "max_state_tokens": await flags.jev_max_state_tokens(conn),
        "lanes": lanes,
        "today": await jev_repo.status_summary(conn),
        "plan_version": jev_prereg.PLAN_VERSION,
        "plan_hash": jev_prereg.plan_hash(),
    }


# ---------------------------------------------------------------------------
# Saying it
# ---------------------------------------------------------------------------


def said(value: Any) -> str:
    """A value as the harness prints it: ``None`` is "not measured", never 0."""
    if value is None:
        return "not measured"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def format_figure(name: str, value: Mapping[str, Any]) -> str:
    """One proportion, with its n and its interval, or why there is none."""
    if value["share"] is None:
        return f"{name}: not measured (n = {value['n']})"
    low, high = value["wilson"]
    return (
        f"{name}: {value['k']} of {value['n']} = {said(value['share'])} "
        f"(Wilson {value['level']:.0%}: {said(low)} to {said(high)})"
    )


def format_count(name: str, value: Mapping[str, Any], of: str = "sessions") -> str:
    """
    A count over sessions, which are not independent trials: its n, the
    distinct states it rests on where the report has them, and never an
    interval.
    """
    if value["share"] is None:
        return f"{name}: not measured (n = {value['n']})"
    text = f"{name}: {value['k']} of {value['n']} {of} = {said(value['share'])}"
    if "distinct_states" in value:
        states = value["distinct_states"]
        text += f", over {states} distinct state{'' if states == 1 else 's'}"
    return text + " (no interval: sessions in one state repeat one judgement)"


def format_forward(report: Mapping[str, Any]) -> str:
    lines = [
        f"{report['signal']} for {report['symbol']}",
        f"plan v{report['plan_version']} {report['plan_hash'][:12]}",
        f"sessions: {report['sessions']} ({said(report['since'])} to "
        f"{said(report['until'])}), cutoffs passed",
        f"live measured {report['live_measured']}, abstain {report['live_abstain']}, "
        f"invalid {report['live_invalid']}, late {report['late']}, "
        f"absent {report['absent']}",
        format_figure("coverage (live measured / sessions)", report["coverage"]),
        f"distinct states: {report['distinct_states']['distinct']} of "
        f"{report['distinct_states']['signals']} answered sessions",
        format_count("served by a replay", report["replayed"], "answered sessions"),
    ]
    for model, figures in report["models"].items():
        lines.append(
            f"{model}: {figures['live_measured']} live measured sessions over "
            f"{figures['distinct_states']} distinct states"
        )
        for option, value in figures["answer_shares"].items():
            lines.append(format_count(f"  share {option}", value))
        lines.append(
            format_count(
                f"  agrees with the plan v{report['plan_version']} baseline rule",
                figures["baseline_agreement_sessions"],
            )
        )
        lines.append(
            format_figure(
                f"  agrees with the plan v{report['plan_version']} baseline rule, "
                "distinct states",
                figures["baseline_agreement_states"],
            )
        )
        for plan, sessions in figures["not_scored"].items():
            lines.append(
                f"  not scored: {sessions} sessions answered under plan "
                f"{plan[:12]}, not this one"
            )
    for model, strata in report["flip_rates"].items():
        for stratum in STRATA:
            value = strata[stratum]
            lines.append(
                format_figure(f"flips, {model}, {stratum}", value)
                + f"; not compared {value['not_compared']}; median lag "
                f"{said(value['median_lag_hours'])} h"
            )
        if strata["other_plans"]:
            lines.append(
                f"flips, {model}: {strata['other_plans']} re-asks sampled under "
                "another plan, in no rate"
            )
    for absence in report["absences"]:
        lines.append(f"absent {absence['session']}: {absence['reason']}")
    for probe in report["probe_series"]:
        lines.append(
            f"probe {probe['at']}: p(true) {said(probe['p_true'])}"
            + (
                ""
                if probe["p_true"] is not None
                else f" ({probe['not_measured_because']})"
            )
        )
    return "\n".join(lines)


def format_audit(report: Mapping[str, Any]) -> str:
    lines = [
        f"{report['signal']} for {report['symbol']}: {report['states']} states, "
        f"{report['agree']} agree, {report['drift']} drift, "
        f"{report['cannot_rebuild']} cannot be rebuilt"
    ]
    for entry in report["sessions"]:
        detail = ", ".join(entry["moved"]) or entry["why"] or ""
        lines.append(f"{entry['session']}: {entry['verdict']} {detail}".rstrip())
    return "\n".join(lines)


def format_status(report: Mapping[str, Any]) -> str:
    lines = [
        f"programme_enabled {report['programme_enabled']}, jev_enabled "
        f"{report['jev_enabled']}, model {said(report['model'])}",
        "areas: " + ", ".join(f"{area} {on}" for area, on in report["areas"].items()),
        f"send internal detail: {report['send_internal_detail']}",
        f"budget {report['daily_request_budget']} calls a day, state limit "
        f"{report['max_state_tokens']} tokens",
    ]
    for lane, spend in report["lanes"].items():
        lines.append(
            f"lane {lane}: {spend['spent_today']} of {spend['share']} calls today"
        )
    today = report["today"]
    latency = today["latency_ms"]
    lines.append(
        f"today: {today['calls']} calls of {today['requests']} requests; "
        f"validity {said(today['validity_rate'])} over {today['answers']} answers; "
        f"latency p50 {said(latency['p50'])} ms over {latency['n']}"
    )
    lines.append(f"plan v{report['plan_version']} {report['plan_hash'][:12]}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.programme.jev_eval",
        description="The Jev evaluation harness. Reads the ledger; asks nothing.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    status = commands.add_parser("status", help="switches, the pin, spend today")
    status.add_argument("--json", action="store_true")
    forward = commands.add_parser("forward", help="the forward clock's record")
    forward.add_argument("--since", type=date.fromisoformat)
    forward.add_argument("--json", action="store_true")
    audit = commands.add_parser(
        "forward-audit", help="recorded states against the bars stored now"
    )
    audit.add_argument("--since", type=date.fromisoformat)
    audit.add_argument("--json", action="store_true")
    return parser


async def _run(arguments: argparse.Namespace, dsn: str) -> str:
    conn = await asyncpg.connect(dsn)
    try:
        # Read-only, and one snapshot for every figure a report prints.
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            now = await jev_clock.database_now(conn)
            if arguments.command == "status":
                report = await status_report(conn)
                text = format_status(report)
            elif arguments.command == "forward":
                report = await forward_report(conn, since=arguments.since, now=now)
                text = format_forward(report)
            else:
                report = await forward_audit(conn, since=arguments.since, now=now)
                text = format_audit(report)
    finally:
        await conn.close()
    if arguments.json:
        return json.dumps(report, default=str, indent=2, sort_keys=True)
    return text


def main(argv: Sequence[str] | None = None) -> int:
    """
    Run one command and print what it found. 0 when it ran, 1 when it was
    refused — no ``DATABASE_URL`` — and 2 on a usage error.
    """
    try:
        arguments = _parser().parse_args(argv)
    except SystemExit as exit_:
        return EXIT_USAGE if exit_.code else EXIT_OK
    dsn = normalise_dsn(os.environ.get("DATABASE_URL", "").strip())
    if not dsn:
        print("DATABASE_URL is not set; the harness reads the ledger", file=sys.stderr)
        return EXIT_REFUSED
    print(asyncio.run(_run(arguments, dsn)))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
