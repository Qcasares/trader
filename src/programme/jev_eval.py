"""
jev_eval.py
-----------
The Jev evaluation harness, from the command line.

    DATABASE_URL=… python -m src.programme.jev_eval status
    DATABASE_URL=… python -m src.programme.jev_eval forward [--since DATE] [--json]
    DATABASE_URL=… python -m src.programme.jev_eval forward-audit [--since DATE]
    DATABASE_URL=… python -m src.programme.jev_eval evaluate --set S --key K \\
        --labelled-by L --split dev|test|all [--model M] [--record [--commit SHA]]
    DATABASE_URL=… python -m src.programme.jev_eval labels export --set S \\
        --key K --blind [--sample N] [--include-quarantined]
    DATABASE_URL=… python -m src.programme.jev_eval labels import --file F \\
        (--as operator:NAME | --source DATASET)
    DATABASE_URL=… python -m src.programme.jev_eval labels copy --set S --key K \\
        --from-version A --to-version B
    DATABASE_URL=… python -m src.programme.jev_eval report [--json]
    DATABASE_URL=… python -m src.programme.jev_eval preview --set S \\
        [--limit N] [--json]
    DATABASE_URL=… python -m src.programme.jev_eval suggestions [--json]

Exit 0 when a command ran, 1 when the harness refused it, 2 on a usage error.
Never ``src/cli.py``: the research CLI loads the engine, and this loads the
ledger (``test_import_boundaries.py::test_the_research_cli_loads_no_programme``).
Runner-only, like everything that reads the ledger for the programme, so the
API cannot load it.

It holds no key and makes no call
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Every figure here is computed from rows the lanes wrote in ordinary operation,
under every switch; nothing here asks Jev anything. Its import closure reaches
no lane, no client, no model runner, no handler that asks, no vault and no
decryption (``tests/unit/test_import_boundaries.py``,
``test_the_harness_holds_no_key_and_reaches_no_client``). The environment it
reads is ``DATABASE_URL``, and ``GIT_COMMIT`` for ``evaluate --record`` alone.
Every command runs in one transaction, and every command but three in one
read-only snapshot. The three are phase C9's that write, each through
``jev_repo`` and nothing else: ``labels import`` and ``labels copy`` write
labels (``record_label``), and ``evaluate --record`` an evaluation
(``record_evaluation``) — held by ``tests/unit/test_jev_eval.py::
TestTheCommandsThatWrite::test_three_commands_write_and_the_rest_only_read``,
and on PostgreSQL, where the database itself refuses a reading command's
write, by ``tests/integration/test_jev_evaluations.py::
TestTheCommandsOnPostgres``.

What an evaluation may say (phase C9)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
``evaluate`` measures one question of one registered set, at its registered
version, against exactly one labeller, for one pinned model, by design section
10.1's definitions, binding (:func:`evaluate`, :func:`build_evaluation`), over
the split ``--split`` names, which has no default. ``test`` and ``all`` read
the held-out test items, a look the gate's level is spent on, so from plan
version 2 each is taken only with ``--record``, which refuses without a clean
40-hex commit, and ``jev_calibration.usable`` refuses a fifth look of a set,
version and question under any model (M3). ``dev`` scores the development
split's items alone — the threshold's search, reading no label or date of a
test item and scoring none of its answers — and is never recorded; its flip
rates, which use no label, are the whole population's, as a look's are. The
rule is held in :func:`execute`, which ``main`` and every caller of the
harness's commands reach (:func:`look_problem`).
What it refuses outright: ``decision.regime``, which has no ground truth for
the present regime, its numbers being ``forward``'s; a question with no plan
registered before the answers; and nothing labelled, which writes nothing and
prints "not measured: no labelled items".

* **Each answer under the plans it was recorded under** (docs/08, C7+C8): the
  plans of the ``jev_ask`` job whose result names the answer's request as
  recorded rather than replayed; for an answer no result names, the plans
  every job that asked about its subject was planned under, if they all
  agree; otherwise the plans are unknown. An item answered under plans other
  than those in force, or under unknown ones, is set apart and counted
  (``n_other_plans``, ``n_plan_unknown``), and never scored, never guessed.
* **Possibly in training is computed**, never typed: false only when every
  item the evaluation reads — the development split's, which a threshold
  rests on, as well as the test split's — is dated strictly after the
  model's first observation (``jev_catalogue.MODEL_FIRST_OBSERVED``). Every
  web document is stored undated, so an evaluation of a web set — against
  the README's grouping or a person's labels alike — is an upper bound, and
  says so everywhere it is printed; it is never given a threshold (docs/08
  open item 65).
* **The threshold is the development split's**, searched on its items alone
  and measured on the test split's; the figure a gate reads is a one-sided
  Wilson lower bound, never a point estimate, and a threshold is usable only
  where the test split's own bound meets the target too
  (``jev_calibration.usable``, ``held_out``).
* **Both baselines answer every item**, so Jev is compared with them over
  every scored item, an answer that was not valid or not asked counted as
  wrong. The findings sets' second baseline (phase D2) is no keyword rule but
  ``findings.recorded``: who raised the earliest model-written finding
  holding the title, or the severity it was recorded at
  (``jev_repo.finding_records``), read here and never on the side that asks,
  and never exported to a labeller. The paired difference is reported with
  its bootstrap interval at the reporting level; Jev "beats" a baseline only
  by the exact one-sided sign
  test, at the gate level, of the items only one of the two got right, which
  the row records (``jev_stats.sign_test``), and "too few to say" where not
  even every one of them going Jev's way could reach the level.
* **Flips are the population's** (plan version 2, M2): a flip rate counts
  every canonical answer to the question under the model that was asked
  again, labelled or not, in the stratum its re-ask was sampled in and under
  the plan that sampled it, since a flip uses no label and an armed threshold
  would act on every answer; so a flip count may exceed ``n``, which migration
  0015 allows.
* **Every level is the row's**: each interval at its ``ci_level`` and each
  gate at its ``gate_ci_level``, as recorded, never the plan in force when it
  is read, and printed as the decimal it was written as (99.9375%, never a
  rounded 99.9%).
* **A figure over nothing is "not measured"**, never 0 or 0.00, and nothing is
  sorted by a figure, so an unknown is never sorted as a low.

``labels export --blind`` prints the subjects a labeller is to label, with
their text and with no answer column, the sample chosen by the subjects'
content addresses and never by any answer: every stored subject but the web
text the code screen flags, content Jev's own screen quarantined among them,
since leaving that out would choose the subjects by what Jev said
(:func:`export_labels`). ``labels import`` records a file of
labels only if every row names the registered set, version and question, an
option that is not the escape, and a subject that is stored; ``labels copy``
carries one version's labels to the registered version only where the
question's options are the same. ``report`` prints the newest evaluation of
each set, version, question, model, labeller and split, with whether it could
arm a threshold (``jev_calibration.usable``, which nothing that acts reads) and
the quarantines, counted by what made them.

From phase D2 two more commands read (docs/09, section 9.3). ``preview``
prints what a title set — the findings sets, the hypothesis categories and
the card check — would be asked about on the day, from the planner's own
read, with the exact state the ``jev_ask`` handler would send or why it would
send nothing, and every switch, the pin, the plans, the holds and the lane's
calls left that decide whether it is planned at all; a web set is refused,
since its subjects are chosen by the injection screen's own answers. It
loads neither the planner nor the handler: their rules are copied, and held
equal on the same rows (``tests/integration/test_jev_findings.py::
TestPreviewIsThePlanners``). ``suggestions`` prints, for each open finding
but Jev's, by its ref, how each findings set's ask came out — answered,
invalid, held, retired, waiting, or not asked and why — and never a title,
an option, a probability or a chip, since anyone who reads it may later
label a set; Jev's own findings are counted, never named.

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
  the regime plan this report runs, which the regime job records in its
  result when it asks; an answer recorded under another regime plan, or with
  none recorded — a phase C4 job's result names the global plan alone — is
  counted apart by the regime plan it was recorded under, or as unknown, and
  never scored by a rule registered after it. The regime plan has stood
  apart from the global plan since plan version 2 (M4), so reviewing the
  rule sets aside regime agreement alone. A flip rate counts only the
  re-asks sampled under the global plan this report runs, in the stratum
  they were sampled in, which the planner records in the re-ask's payload.
  The report names both plans.

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
import csv
import dataclasses
import hashlib
import io
import json
import logging
import math
import os
import re
import statistics
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import asyncpg

from src.config import normalise_dsn
from src.core import calendar
from src.programme import (
    claims,
    flags,
    jev_calibration,
    jev_catalogue,
    jev_clock,
    jev_features,
    jev_prereg,
    jev_questions,
    jev_repo,
    jev_stats,
    web_sources,
)
from src.programme.jev_hash import text_sha256

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
    "regime_plan_version",
    "regime_plan_hash",
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

#: How an answer whose job recorded no regime plan — a phase C4 job, whose
#: result named the global plan alone — is counted in ``not_scored``.
UNKNOWN_PLAN = "unknown"

#: The exit codes: a command that ran, one the harness refused, a usage error.
EXIT_OK, EXIT_REFUSED, EXIT_USAGE = 0, 1, 2

#: The analysis plans an answer is recorded under, by the names
#: ``jev_prereg.plans_in_force`` gives them, as ``jev_jobs.PLAN_KEYS`` names
#: them in a ``jev_ask`` job's payload and result. A copy, since the harness
#: may not load ``jev_jobs``, which asks; ``tests/unit/test_jev_eval.py`` holds
#: the two equal.
PLAN_KEYS = ("plan_version", "plan_hash", "set_plan_version", "set_plan_hash")

#: The sets ``evaluate`` refuses whatever their labels, and why.
NO_GROUND_TRUTH: Mapping[str, str] = {
    "decision.regime": (
        "decision.regime has no ground truth for the present regime, so it is "
        "not evaluated against labels: its numbers are forward's"
    ),
}

#: The subjects a label may be of: text, which a person can read and judge —
#: a web excerpt, a hypothesis title and, from phase D2, a finding's title
#: (docs/09, section 3.7).
LABELLED_SUBJECTS = ("web_excerpt", "hypothesis_title", "finding_title")

#: The splits an evaluation may be recorded over: the held-out test split,
#: which a gate reads, or every labelled item, which holds it. Each is a look
#: at the held-out items (``jev_prereg.LOOKED_AT_SPLITS``, which a test holds
#: equal), so from plan version 2 each is computed only to be recorded
#: (:func:`look_problem`): a look nobody records is a look ``usable`` cannot
#: count.
SPLITS = ("test", "all")

#: The development split: the threshold search's own items. ``evaluate
#: --split dev`` scores them alone — it reads no label or date of a test item,
#: and scores none of its answers — and is never recorded (plan version 2,
#: M3), so an operator can see how the search stands without spending a look.
#: Its flip rates are the population's (M2), as a look's are: a flip uses no
#: label, so counting a test item's re-ask among them is no look at it (D1's
#: review, D1RT-2). Nor can it say whether a look would be an upper bound,
#: which a held-out item's date decides (docs/08 open item 83).
DEV_SPLIT = "dev"

#: What ``evaluate --split`` takes. It has no default, so nobody looks at the
#: test split by accident.
EVALUATE_SPLITS = (DEV_SPLIT, *SPLITS)

#: What ``evaluate`` prints, and writes nothing, over no labelled item.
NOTHING_LABELLED = "not measured: no labelled items"

#: A labeller, as migration 0012's CHECK ``jev_labels_by_a_person_or_a_dataset``
#: admits one: a person, or a dataset at a fixed hash.
LABELLER = re.compile(r"(?:operator:.+|source:.+@.+)", re.DOTALL)

#: What ``labels import --as`` takes: a person, lower case, so one person is
#: one labeller however they type their name.
OPERATOR = re.compile(r"operator:[a-z0-9][a-z0-9_.-]{0,62}", re.ASCII)

#: What ``labels import --source`` takes as a dataset's name, before the hash
#: of the file is appended to it.
DATASET = re.compile(r"[a-z0-9][a-z0-9-]{0,62}", re.ASCII)

#: A commit as git names one.
COMMIT = re.compile(r"[0-9a-f]{40}", re.ASCII)

#: The columns ``labels import`` reads: these six, and optionally ``note``,
#: stored beside the label, and ``text``, the export's, read and checked
#: against the subject's address, never stored. Any other column is refused,
#: an answer column above all.
IMPORT_COLUMNS = (
    "question_set",
    "question_set_version",
    "question_key",
    "subject_type",
    "subject_id",
    "label",
)
IMPORT_OPTIONAL_COLUMNS = ("note", "text")

#: What ``labels export`` writes: the subject and its text, and no answer.
EXPORT_COLUMNS = ("subject_type", "subject_id", "text")

#: Where ``git`` is run to name the commit an evaluation is recorded under.
REPOSITORY = Path(__file__).resolve().parents[2]


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
    regime_plan = jev_prereg.regime_plan_hash()
    by_model: dict[str, list[Mapping[str, Any]]] = {}
    for row in live_measured:
        by_model.setdefault(str(row["model"]), []).append(row)
    return {
        "plan_version": jev_prereg.PLAN_VERSION,
        "plan_hash": plan,
        "regime_plan_version": jev_prereg.REGIME_PLAN_VERSION,
        "regime_plan_hash": regime_plan,
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
            model: _model_figures(question_set, rows, jobs, regime_plan)
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
    regime_plan: str,
) -> dict[str, Any]:
    """
    One model's live measured sessions: the regimes' shares, and agreement
    with the baseline rule over the answers first recorded under
    ``regime_plan``, the others counted by the regime plan they were recorded
    under.
    """
    scored = []
    not_scored: dict[str, int] = {}
    for row in measured:
        recorded_under = _answer_regime_plan(question_set, row, jobs)
        if recorded_under == regime_plan:
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


def _answer_regime_plan(
    question_set: jev_questions.QuestionSet,
    row: Mapping[str, Any],
    jobs: Mapping[str, Mapping[str, Any]],
) -> str | None:
    """
    The regime plan in force when a session's answer was first recorded: the
    regime plan the regime job that asked it wrote in its result. A replayed
    session's answer was asked about another session, whose job is the one
    that asked. ``None`` when no such job, or no regime plan in it, is on
    record — a phase C4 job's result names the global plan alone, and the
    global plan's hash is never read as a regime plan's.
    """
    try:
        asked_about = date.fromisoformat(str(row.get("subject_id")))
    except ValueError:
        return None
    job = jobs.get(jev_clock.regime_job_key(question_set, asked_about)) or {}
    result = job.get("result") or {}
    recorded = result.get("regime_plan_hash") if isinstance(result, Mapping) else None
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
        "regime_plan_version": jev_prereg.REGIME_PLAN_VERSION,
        "regime_plan_hash": jev_prereg.regime_plan_hash(),
    }


# ---------------------------------------------------------------------------
# Evaluations against labels (phase C9)
# ---------------------------------------------------------------------------


class Refused(Exception):  # noqa: N818 - it names the outcome, not an error
    """A command the harness refuses, with the sentence it says why; exit 1."""


@dataclasses.dataclass(frozen=True)
class Evaluation:
    """
    One evaluation, as ``jev_evaluations`` holds it: every column migrations
    0012 and 0014 give the table but the two the database assigns, ``id`` and
    ``created_at``, in ``jev_repo.EVALUATION_COLUMNS``'s order, ``None``
    wherever nothing was measured. ``code_commit`` is ``None`` until the
    evaluation is recorded. ``tests/unit/test_jev_eval.py`` holds the fields
    to the columns.
    """

    question_set: str
    question_set_version: int
    question_key: str
    model: str
    split: str
    dataset_ref: str
    dataset_sha256: str
    analysis_plan_hash: str
    keyword_baseline_ref: str | None
    answers_sha256: str
    code_commit: str | None
    possibly_in_training: bool
    ci_level: float
    gate_ci_level: float
    n: int
    n_per_class: dict[str, int]
    n_valid: int
    n_escape: int
    n_invalid: int
    n_not_asked: int
    n_contested: int
    n_other_plans: int
    n_plan_unknown: int
    n_distinct_states: int
    accuracy: float | None
    accuracy_wilson_low: float | None
    accuracy_wilson_high: float | None
    accuracy_all_items: float | None
    accuracy_all_items_wilson_low: float | None
    accuracy_all_items_wilson_high: float | None
    balanced_accuracy: float | None
    per_class: dict[str, Any]
    brier: float | None
    brier_ci_low: float | None
    brier_ci_high: float | None
    brier_reference: float | None
    calibration_bins: list[dict[str, Any]] | None
    majority_baseline_accuracy: float | None
    keyword_baseline_accuracy: float | None
    vs_majority_diff: float | None
    vs_majority_diff_low: float | None
    vs_majority_diff_high: float | None
    vs_majority_jev_right_only: int
    vs_majority_baseline_right_only: int
    vs_keyword_diff: float | None
    vs_keyword_diff_low: float | None
    vs_keyword_diff_high: float | None
    vs_keyword_jev_right_only: int
    vs_keyword_baseline_right_only: int
    threshold_outcome: str
    threshold_statistic: str | None
    threshold_target: float | None
    threshold_dataset_sha256: str | None
    threshold: float | None
    coverage_at_threshold: float | None
    n_at_threshold: int | None
    accuracy_at_threshold: float | None
    accuracy_at_threshold_wilson_low: float | None
    accuracy_at_threshold_wilson_high: float | None
    flip_rate: float | None
    flip_rate_n: int
    flip_rate_not_compared: int
    flip_rate_low_margin: float | None
    flip_rate_low_margin_n: int
    flip_rate_low_margin_not_compared: int
    flip_rate_near_threshold: float | None
    flip_rate_near_threshold_n: int | None
    flip_rate_near_threshold_not_compared: int | None
    flip_median_lag_hours: float | None
    labeller_agreement: float | None
    labeller_kappa: float | None
    labeller_agreement_n: int

    def row(self) -> dict[str, Any]:
        """Every column, by name: what ``jev_repo.record_evaluation`` takes."""
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class Ledger:
    """
    Everything one evaluation reads, read in one snapshot, so the figures it
    prints all describe the same moment of the ledger (:func:`read_ledger`).

    ``labels`` are every labeller's labels of the question; ``answers`` the
    answer each labelled subject is scored by (``jev_repo.
    answers_for_subjects``); ``jobs`` the ``jev_ask`` jobs about those
    subjects, which name the plans each answer was recorded under; ``dates``
    and ``texts`` each subject's date and text; ``pairs`` the question's
    canonical answers beside their re-asks under the model, and ``reasks``
    the re-ask jobs by key, which name the stratum and plan each was sampled
    under. From phase D2, ``records`` holds, for each finding-title subject,
    who raised the earliest finding of its population holding the title and
    the severity it was recorded at (``jev_repo.finding_records``): what the
    ``findings.recorded`` baseline answers with, read here and nowhere on the
    side that asks.
    """

    labels: Sequence[Mapping[str, Any]]
    answers: Mapping[jev_repo.Subject, Mapping[str, Any]]
    jobs: Sequence[Mapping[str, Any]]
    dates: Mapping[jev_repo.Subject, datetime | None]
    texts: Mapping[jev_repo.Subject, str]
    pairs: Sequence[Mapping[str, Any]]
    reasks: Mapping[str, Mapping[str, Any]]
    records: Mapping[jev_repo.Subject, Mapping[str, Any]] = dataclasses.field(
        default_factory=dict
    )


@dataclasses.dataclass(frozen=True)
class _Item:
    """One labelled subject: its label, split and answer, and how it stands."""

    subject: jev_repo.Subject
    label: str
    split: str
    answer: Mapping[str, Any] | None
    standing: Literal["scored", "other_plans", "plan_unknown"]

    @property
    def valid(self) -> bool:
        return self.answer is not None and self.answer["valid"] is True

    @property
    def predicted(self) -> str | None:
        """The option a valid answer chose; ``None`` for any other."""
        return self.answer["argmax"] if self.valid else None

    @property
    def correct(self) -> bool:
        return self.predicted == self.label


def question_problem(
    question_set: jev_questions.QuestionSet, question_key: str
) -> str | None:
    """
    Why ``question_key`` of ``question_set`` is not evaluated against labels,
    or ``None``: a set with no ground truth, a question the set does not ask,
    a subject nobody can label, or no plan registered for the question
    before its answers.
    """
    if question_set.name in NO_GROUND_TRUTH:
        return NO_GROUND_TRUTH[question_set.name]
    if question_key not in dict(question_set.questions):
        return f"{question_set.name} v{question_set.version} asks no {question_key!r}"
    subject_type = jev_questions.STATE_SUBJECT.get(question_set.state_model)
    if subject_type not in LABELLED_SUBJECTS:
        return (
            f"{question_set.name} is asked about a {subject_type!r}, and a label "
            "is of text: a web excerpt, a hypothesis title or a finding title"
        )
    plan = jev_prereg.set_plan(question_set.name, question_set.version)
    if plan is None or question_key not in plan["questions"]:
        return (
            f"{question_set.name} v{question_set.version} has no analysis plan for "
            f"{question_key!r} registered before its answers (jev_prereg), and "
            "nothing is evaluated under a plan chosen after them"
        )
    return None


def options_of(question_set: jev_questions.QuestionSet, question_key: str) -> list[str]:
    """
    The labels a question's answer can be compared with, in its own order:
    a Choice's options without its escape, which no label is, or a Noul's
    ``true`` and ``false``. A Score is labelled by no evaluation in phase C.
    """
    question = dict(question_set.questions)[question_key]
    if question["type"] == "noul":
        return [jev_calibration.TRUE, jev_calibration.FALSE]
    if question["type"] == "choice":
        escape = question_set.escape_options.get(question_key)
        return [option for option in question["criteria"] if option != escape]
    raise Refused(
        f"{question_set.name}'s {question_key!r} is a Score, labelled by none"
    )


def keyword_baseline(
    question_set: jev_questions.QuestionSet,
    question_key: str,
    *,
    records: Mapping[jev_repo.Subject, Mapping[str, Any]] | None = None,
) -> tuple[Callable[[jev_repo.Subject, str], str], str]:
    """
    The keyword baseline the question's set plan registered, as a function
    of the item — its subject beside its text — and how the evaluation names
    it. Only the rule the plan names, as the plan holds it: the injection
    screen's is the code screen at the version and rule data the plan hashed,
    and is refused if the screen running now is another; the catalogue's and
    the hypotheses' are the plan's own ordered keyword rules; the card's the
    claims check with the plan's terms. From phase D2 the findings sets' is
    ``findings.recorded``: the value the plan names — who raised the
    finding, or its severity — of the earliest finding of the population
    holding the title, from ``records`` (``jev_repo.finding_records``), and
    refused if the plan registered another order or writer than the one the
    harness reads (docs/09, section 3.4). Each rule but the last reads the
    text alone.
    """
    plan = jev_prereg.set_plan(question_set.name, question_set.version)
    assert plan is not None  # question_problem first
    baseline = plan["questions"][question_key]["keyword_baseline"]
    rule = baseline["rule"]
    if rule == "findings.recorded":
        reads = baseline["reads"]
        if (
            reads not in jev_repo.FINDING_RECORD_COLUMNS
            or baseline["origin"] != "model"
            or tuple(baseline["order"]) != jev_repo.FINDING_RECORD_ORDER
        ):
            raise Refused(
                f"{question_set.name}'s plan registers a recorded baseline the "
                "harness does not read; nothing is measured against it"
            )
        held = records or {}

        def recorded(subject: jev_repo.Subject, text: str) -> str:
            record = held.get(subject)
            if record is None:
                raise Refused(
                    f"no finding of the population holds the title "
                    f"{subject[1][:12]}…, so the recorded baseline cannot answer it"
                )
            return str(record[reads])

        return recorded, (
            f"findings.recorded, reading {reads} of the earliest model-written "
            "finding holding the title"
        )
    if rule == "web_sources.code_screen":
        if (
            baseline["version"] != web_sources.CODE_SCREEN_VERSION
            or baseline["rules_sha256"] != web_sources.code_screen_sha256()
        ):
            raise Refused(
                "the code screen running is not the one the plan registered as "
                f"{question_set.name}'s baseline; nothing is measured against it"
            )

        def screen(subject: jev_repo.Subject, text: str) -> str:
            flagged = web_sources.code_screen(text) is not None
            return jev_calibration.TRUE if flagged else jev_calibration.FALSE

        return screen, (
            f"web_sources.code_screen v{baseline['version']}, rules "
            f"{baseline['rules_sha256'][:12]}, reading {baseline['reads']}"
        )
    if rule == "claims.find_performance_claim":
        if tuple(baseline["terms"]) != claims.PERFORMANCE_TERMS:
            raise Refused(
                "the claims check's terms are not the ones the plan registered as "
                f"{question_set.name}'s baseline; nothing is measured against it"
            )

        def claim(subject: jev_repo.Subject, text: str) -> str:
            found = claims.find_performance_claim(text) is not None
            return jev_calibration.TRUE if found else jev_calibration.FALSE

        return claim, f"claims.find_performance_claim, reading {baseline['reads']}"
    if rule == "jev_prereg.keyword_label":
        rules = tuple((label, tuple(keywords)) for label, keywords in baseline["rules"])
        return (
            lambda subject, text: jev_prereg.keyword_label(rules, text),
            f"jev_prereg.keyword_label {baseline['matcher']}, reading "
            f"{baseline['reads']}",
        )
    raise Refused(f"{question_set.name}'s plan names a baseline nobody knows, {rule!r}")


def answer_plans(
    subject: jev_repo.Subject,
    answer: Mapping[str, Any],
    jobs: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    """
    The analysis plans ``answer`` was recorded under, or ``None`` when they
    cannot be named (docs/08, C7+C8, "The plans an answer was recorded
    under", which states this rule for C9):

    * the plans of the ``jev_ask`` job whose result names the answer's
      request as recorded — ``replayed`` false — read from that result, or
      that job's payload where the result does not carry them; a replay
      never re-dates an answer;
    * for an answer no result names — a lease that expired after the ask, an
      attempt superseded after an earlier one recorded — the plans of the
      payloads of every ``jev_ask`` job that asked about its subject (claimed
      at least once), only if every one names the same plans;
    * ``None`` — unknown — where they disagree, or no job names the subject.
    """
    request_id = answer["request_id"]
    named = {
        _plans(job.get("result")) or _plans(job.get("payload"))
        for job in jobs
        if isinstance(job.get("result"), Mapping)
        and job["result"].get("request_id") == request_id
        and job["result"].get("replayed") is False
    }
    if not named:
        named = {
            _plans(job.get("payload"))
            for job in jobs
            if _about(job.get("payload"), subject) and (job.get("attempts") or 0) > 0
        }
    if len(named) != 1:
        return None
    (plans,) = named
    return dict(plans) if plans is not None else None


def _plans(record: object) -> tuple[tuple[str, Any], ...] | None:
    if not isinstance(record, Mapping) or not all(k in record for k in PLAN_KEYS):
        return None
    return tuple((key, record[key]) for key in PLAN_KEYS)


def _about(payload: object, subject: jev_repo.Subject) -> bool:
    return (
        isinstance(payload, Mapping)
        and (
            payload.get("subject_type"),
            payload.get("subject_id"),
        )
        == subject
    )


def _sha256_lines(lines: Sequence[str]) -> str:
    return hashlib.sha256("\n".join(sorted(lines)).encode("utf-8")).hexdigest()


def dataset_sha256(items: Sequence[tuple[str, str, str]]) -> str:
    """
    A labelled dataset's identity: sha256 of its ``(subject_type,
    subject_id, label)`` triples, each written tab-separated, sorted and
    joined by line feeds. The labels alone name it, never an answer, so one
    labeller's items in one split hash alike whatever Jev said about them.
    """
    return _sha256_lines(["\t".join(item) for item in items])


def seed_of(dataset: str) -> int:
    """The bootstrap's seed, by ``jev_prereg.BOOTSTRAP_SEED_RULE``."""
    assert jev_prereg.BOOTSTRAP_SEED_RULE == "int(dataset_sha256[:16], 16)"
    return int(dataset[:16], 16)


def labeller_identity(labelled_by: str) -> str:
    """
    Who a labeller is: a person by their name, and a dataset by its name
    whatever version of it labelled, since a new version of a page is the
    same source labelling again and never a second opinion.
    """
    if labelled_by.startswith("source:"):
        return labelled_by.rsplit("@", 1)[0]
    return labelled_by


def possibly_in_training(model: str, dates: Sequence[datetime | None]) -> bool:
    """
    Whether any of ``dates`` may predate what ``model`` was trained on: an
    item undated, or dated on or before the day the model was first observed
    (``jev_catalogue.MODEL_FIRST_OBSERVED``), by its UTC day; and any item at
    all of a model with no first observation. False only when every item is
    dated strictly after it.
    """
    first = jev_catalogue.MODEL_FIRST_OBSERVED.get(model)
    if first is None:
        return True
    return any(day is None or day.astimezone(UTC).date() <= first for day in dates)


def _figure(k: int, n: int) -> tuple[float | None, float | None, float | None]:
    """A proportion and its Wilson interval at the reporting level, or Nones."""
    share = jev_stats.proportion(k, n)
    interval = jev_stats.wilson(k, n, jev_prereg.REPORT_CI)
    if share is None or interval is None:
        return None, None, None
    return share, interval[0], interval[1]


def _holding(
    value: float, interval: tuple[float, float] | None
) -> tuple[float | None, float | None]:
    """
    A percentile interval, widened where it misses its own estimate — which
    a very skewed few items can make it do — so it holds what it is quoted
    beside (migration 0014's ``jev_evaluations_intervals_hold_their_
    estimates``); widened, never narrowed, which is the conservative side.
    """
    if interval is None:
        return None, None
    return min(interval[0], value), max(interval[1], value)


def near_threshold(margin: float, threshold: float) -> bool:
    """
    Whether a canonical answer's margin is within ``jev_prereg.NEAR_THRESHOLD``
    of the threshold, compared as the decimals they were written as. The
    validator stores a margin as the decimal difference of the probabilities
    the vendor wrote, and the grid is written in hundredths; in binary
    ``0.52 - 0.42`` exceeds 0.1, so a margin exactly 0.10 from a threshold
    fell out of its window on one side of 20 of the grid's 91 edges and into
    it on the other (``jev_validate``'s rule: numbers are compared as the
    decimals written wherever that decides a rule).
    ``tests/unit/test_jev_eval.py::TestTheFlips::test_every_grid_threshold_holds_both_edges``.
    """
    distance = abs(Decimal(repr(float(margin))) - Decimal(repr(float(threshold))))
    return distance <= Decimal(repr(jev_prereg.NEAR_THRESHOLD))


def _mean(values: Sequence[float]) -> float:
    return math.fsum(values) / len(values)


def _difference(pairs: Sequence[tuple[bool, bool]]) -> float:
    """Jev's accuracy over the pairs less the baseline's: a paired difference."""
    return _mean([float(j) for j, _ in pairs]) - _mean([float(b) for _, b in pairs])


def build_evaluation(
    *,
    question_set: jev_questions.QuestionSet,
    question_key: str,
    labelled_by: str,
    model: str,
    split: Literal["all", "test", "dev"],
    ledger: Ledger,
) -> Evaluation:
    """
    One evaluation from rows already read: pure, so every definition of
    design section 10.1 is tested without a database. See :func:`evaluate`
    for what it is, and the module docstring for the rules it keeps.

    Over :data:`DEV_SPLIT` it scores the development split's items alone —
    their labels, answers and dates — and so its search, and measures
    nothing at the threshold, which a recorded look measures on the test
    split; its flip rates are the population's, as every split's are
    (``tests/unit/test_jev_eval.py::TestLooks``).
    """
    problem = question_problem(question_set, question_key)
    if problem is not None:
        raise Refused(problem)
    if split not in EVALUATE_SPLITS:
        raise Refused(f"the split is dev, test or all, not {split!r}")
    name, version = question_set.name, question_set.version
    question = dict(question_set.questions)[question_key]
    options = options_of(question_set, question_key)
    escape = question_set.escape_options.get(question_key)
    target = jev_prereg.set_plan(name, version)["questions"][question_key]
    in_force = jev_prereg.plans_in_force(name, version)
    plan_identity = jev_calibration.analysis_plan_hash(name, version)
    assert in_force is not None and plan_identity is not None

    # The labeller's labels, one per subject; a subject given two labels by
    # it would be contested, which the schema's one label per labeller per
    # item makes none, and is counted rather than assumed.
    own: dict[jev_repo.Subject, set[str]] = {}
    for row in ledger.labels:
        if row["labelled_by"] == labelled_by:
            subject = (row["subject_type"], row["subject_id"])
            own.setdefault(subject, set()).add(row["label"])
    contested = {s for s, labels in own.items() if len(labels) > 1}
    unanimous = {
        s: next(iter(labels)) for s, labels in own.items() if s not in contested
    }

    items: list[_Item] = []
    for subject in sorted(unanimous):
        answer = ledger.answers.get(subject)
        standing: Literal["scored", "other_plans", "plan_unknown"] = "scored"
        if answer is not None:
            plans = answer_plans(subject, answer, ledger.jobs)
            if plans is None:
                standing = "plan_unknown"
            elif plans != in_force:
                standing = "other_plans"
        items.append(
            _Item(
                subject=subject,
                label=unanimous[subject],
                split=jev_prereg.split_of(*subject),
                answer=answer,
                standing=standing,
            )
        )
    if split == DEV_SPLIT:
        # The search's own items: no label and no date of a test item is read
        # below, and none of its answers is scored. The flip rates below count
        # the population, which uses no label, as every split's do.
        items = [i for i in items if i.split == DEV_SPLIT]
    in_split = [i for i in items if split == "all" or i.split == split]
    scored = [i for i in in_split if i.standing == "scored"]
    other_plans = sum(1 for i in in_split if i.standing == "other_plans")
    plan_unknown = sum(1 for i in in_split if i.standing == "plan_unknown")
    contested_here = sum(
        1 for s in contested if split == "all" or jev_prereg.split_of(*s) == split
    )
    if not scored:
        apart = ""
        if other_plans or plan_unknown:
            apart = (
                f" under the plans in force ({other_plans} answered under other "
                f"plans and {plan_unknown} under plans unknown, set apart)"
            )
        raise Refused(f"{NOTHING_LABELLED}{apart}")
    for item in items:
        if item.label not in options:
            raise Refused(
                f"a label of {labelled_by} is {item.label!r}, which is not one of "
                f"{question_set.name}'s {question_key!r} options; labels import "
                "refuses one, so the ledger holds a label no import wrote"
            )

    dataset = dataset_sha256([(*i.subject, i.label) for i in in_split])
    seed = seed_of(dataset)
    n = len(scored)
    answered = [i for i in scored if i.answer is not None]
    valid = [i for i in scored if i.valid]
    correct = sum(1 for i in scored if i.correct)
    accuracy = _figure(correct, len(valid))
    all_items = _figure(correct, n)

    # Per label class, over every scored item: recall, and the precision of
    # the answers choosing it, Jev's and the keyword rule's.
    keyword, keyword_ref = keyword_baseline(
        question_set, question_key, records=ledger.records
    )
    guesses: dict[jev_repo.Subject, str] = {}
    for item in scored:
        text = ledger.texts.get(item.subject)
        if text is None:
            raise Refused(
                f"the text of {item.subject[0]} {item.subject[1][:12]} is not "
                "stored, so the keyword baseline cannot answer it"
            )
        guesses[item.subject] = keyword(item.subject, text)
    n_per_class = {c: sum(1 for i in scored if i.label == c) for c in options}
    n_per_class = {c: count for c, count in n_per_class.items() if count}
    per_class: dict[str, Any] = {}
    recalls = []
    for label, count in n_per_class.items():
        right = sum(1 for i in scored if i.label == label and i.correct)
        chose = sum(1 for i in scored if i.predicted == label)
        keyword_chose = sum(1 for i in scored if guesses[i.subject] == label)
        keyword_right = sum(
            1 for i in scored if i.label == label and guesses[i.subject] == label
        )
        recall = _figure(right, count)
        precision = _figure(right, chose)
        recalls.append(recall[0])
        per_class[label] = {
            "n": count,
            "correct": right,
            "recall": recall[0],
            "recall_wilson": None if recall[0] is None else [recall[1], recall[2]],
            "predicted": chose,
            "precision": precision[0],
            "precision_wilson": (
                None if precision[0] is None else [precision[1], precision[2]]
            ),
            "too_few_to_say": count < jev_prereg.TOO_FEW_PER_CLASS,
            "keyword": {
                "predicted": keyword_chose,
                "correct": keyword_right,
                "precision": jev_stats.proportion(keyword_right, keyword_chose),
                "recall": jev_stats.proportion(keyword_right, count),
            },
        }
    balanced = _mean(recalls) if recalls else None

    # The Brier score over the valid answers, its bootstrap interval, and
    # its climatology on the same items.
    brier = brier_low = brier_high = reference = None
    bins: list[dict[str, Any]] | None = None
    if valid:
        labels = [i.label for i in valid]
        if question["type"] == "noul":
            p_true = [float(i.answer["noul"]) for i in valid]
            truths = [label == jev_calibration.TRUE for label in labels]
            brier = jev_stats.brier_noul(p_true, truths)
            interval = jev_stats.bootstrap_interval(
                list(zip(p_true, truths, strict=True)),
                lambda sample: jev_stats.brier_noul(
                    [p for p, _ in sample], [t for _, t in sample]
                ),
                resamples=jev_prereg.BOOTSTRAP_RESAMPLES,
                seed=seed,
                level=jev_prereg.REPORT_CI,
            )
            base_rate = sum(truths) / len(truths)
            reference = jev_stats.brier_noul([base_rate] * len(truths), truths)
            bins = jev_stats.calibration_bins(
                p_true,
                truths,
                jev_prereg.CALIBRATION_BINS,
                level=jev_prereg.REPORT_CI,
            )
        else:
            distributions = [dict(i.answer["probabilities"]) for i in valid]
            brier = jev_stats.brier_choice(distributions, labels)
            interval = jev_stats.bootstrap_interval(
                list(zip(distributions, labels, strict=True)),
                lambda sample: jev_stats.brier_choice(
                    [d for d, _ in sample], [lab for _, lab in sample]
                ),
                resamples=jev_prereg.BOOTSTRAP_RESAMPLES,
                seed=seed,
                level=jev_prereg.REPORT_CI,
            )
            criteria = list(question["criteria"])
            climate = {
                option: labels.count(option) / len(labels) for option in criteria
            }
            reference = jev_stats.brier_choice([climate] * len(labels), labels)
            bins = jev_stats.calibration_bins(
                [float(i.answer["probabilities"][i.predicted]) for i in valid],
                [i.correct for i in valid],
                jev_prereg.CALIBRATION_BINS,
                level=jev_prereg.REPORT_CI,
            )
        assert brier is not None
        brier_low, brier_high = _holding(brier, interval)

    # Both baselines answer every scored item; Jev is compared with each on
    # the same items, its answers that were not valid, or not asked, wrong:
    # the paired difference with its bootstrap interval, reported at the
    # reporting level like every other interval, and the discordant items
    # it is made of, which alone decide whether Jev beats the baseline — by
    # the exact one-sided sign test at the gate level, never by the
    # bootstrap, whose bound over a few discordant items sits at the point
    # estimate (jev_stats.sign_test).
    majority = max(options, key=lambda c: (n_per_class.get(c, 0), -options.index(c)))
    majority_right = [i.label == majority for i in scored]
    keyword_right_all = [guesses[i.subject] == i.label for i in scored]
    majority_accuracy = jev_stats.proportion(sum(majority_right), n)
    keyword_accuracy = jev_stats.proportion(sum(keyword_right_all), n)
    comparisons = {}
    for baseline, right in (
        ("majority", majority_right),
        ("keyword", keyword_right_all),
    ):
        pairs = [(i.correct, b) for i, b in zip(scored, right, strict=True)]
        point = _difference(pairs)
        interval = jev_stats.bootstrap_interval(
            pairs,
            _difference,
            resamples=jev_prereg.BOOTSTRAP_RESAMPLES,
            seed=seed,
            level=jev_prereg.REPORT_CI,
        )
        jev_only = sum(1 for jev, base in pairs if jev and not base)
        baseline_only = sum(1 for jev, base in pairs if base and not jev)
        comparisons[baseline] = (
            point,
            *_holding(point, interval),
            jev_only,
            baseline_only,
        )

    # The threshold: searched on the development split's scored items alone,
    # never on an upper bound, and measured on the test split's. Whether the
    # evaluation may rest on the model's training data is read over every item
    # it reads — the development split's too when its figures are the test
    # split's, since the threshold rests on those — so a threshold is never
    # searched on an undated development item beside a dated test split.
    in_training = possibly_in_training(
        model, [ledger.dates.get(i.subject) for i in items]
    )
    acting = target["acting_class"]
    choice = jev_stats.ThresholdChoice("not_attempted")
    if not in_training:
        development = [i for i in items if i.split == "dev" and i.standing == "scored"]
        choice = jev_stats.choose_threshold(
            [
                jev_stats.DevItem(
                    label=i.label,
                    predicted=i.predicted,
                    margin=float(i.answer["margin"]) if i.valid else None,
                )
                for i in development
            ],
            grid=jev_prereg.MARGIN_GRID,
            target=target["at_least"],
            min_covered=jev_prereg.MIN_COVERED,
            level=jev_prereg.GATE_CI,
            acting_class=acting,
            min_dev=jev_prereg.MIN_DEV_ITEMS,
        )
    threshold = threshold_dataset = statistic = target_value = None
    coverage = n_at = None
    at_threshold: tuple[float | None, float | None, float | None] = (None, None, None)
    if choice.outcome == "chosen":
        threshold = choice.threshold
        assert threshold is not None
        statistic, target_value = target["statistic"], target["at_least"]
        threshold_dataset = dataset_sha256(
            [(*i.subject, i.label) for i in items if i.split == "dev"]
        )
    if choice.outcome == "chosen" and split != DEV_SPLIT:
        assert threshold is not None
        tested = [i for i in scored if i.split == "test"]
        covered = [
            i for i in tested if i.valid and float(i.answer["margin"]) >= threshold
        ]
        coverage = jev_stats.proportion(len(covered), len(tested))
        measured = [i for i in covered if acting is None or i.predicted == acting]
        n_at = len(measured)
        right_at = sum(
            1
            for i in measured
            if i.label == (acting if acting is not None else i.predicted)
        )
        at_threshold = _figure(right_at, n_at)

    # The flip rates: every canonical answer to the question under the model
    # beside its re-ask, labelled or not (plan version 2, M2:
    # ``jev_prereg.FLIP_PAIRS``) — a flip uses no label, and an armed threshold
    # would act on the population, so the population's flips are the ones
    # that bear on it. Each pair counted only in the stratum and under the
    # global plan its re-ask was sampled in; the near-threshold rate from
    # either stratum, by the canonical margin, once a threshold is chosen.
    # Version 1 counted a pair only when its canonical request answered a
    # scored item, so thirty uniform pairs took some six hundred labels.
    assert jev_prereg.FLIP_PAIRS == (
        "every_canonical_request_of_the_question_under_the_pin"
    )
    plan = jev_prereg.plan_hash()
    strata: dict[str, list[Mapping[str, Any]]] = {name: [] for name in STRATA}
    for pair in ledger.pairs:
        job = ledger.reasks.get(reask_job_key(pair["canonical_request_id"])) or {}
        payload = job.get("payload") or {}
        stratum = payload.get("stratum") if isinstance(payload, Mapping) else None
        if (
            isinstance(payload, Mapping)
            and payload.get("plan_hash") == plan
            and stratum in strata
        ):
            strata[stratum].append(pair)

    def argmaxes(pair: Mapping[str, Any]) -> tuple[str | None, str | None]:
        return (
            pair["canonical_argmax"] if pair["canonical_valid"] else None,
            pair["probe_argmax"] if pair["probe_valid"] else None,
        )

    # A pair either of whose answers was not measured is no comparison: it
    # is in no rate, and counted apart, so a re-ask is never lost from both.
    uniform_flipped, uniform_n = jev_stats.flip_rate(
        [argmaxes(p) for p in strata["uniform"]]
    )
    low_flipped, low_n = jev_stats.flip_rate(
        [argmaxes(p) for p in strata["low_margin"]]
    )
    uniform_apart = len(strata["uniform"]) - uniform_n
    low_apart = len(strata["low_margin"]) - low_n
    lags = [
        p["lag_seconds"] / 3600 for p in strata["uniform"] if None not in argmaxes(p)
    ]
    near: tuple[float | None, int | None, int | None] = (None, None, None)
    if threshold is not None:
        window = [
            p
            for stratum in STRATA
            for p in strata[stratum]
            if p["canonical_margin"] is not None
            and near_threshold(p["canonical_margin"], threshold)
        ]
        near_flipped, near_n = jev_stats.flip_rate([argmaxes(p) for p in window])
        near = (
            jev_stats.proportion(near_flipped, near_n),
            near_n,
            len(window) - near_n,
        )

    # How far another labeller agrees with this one: each scored item another
    # labeller labelled, compared once, with the earliest label any other
    # labeller gave it; a dataset's versions are one labeller.
    mine = labeller_identity(labelled_by)
    others: dict[jev_repo.Subject, tuple[int, str]] = {}
    for row in ledger.labels:
        if labeller_identity(row["labelled_by"]) == mine:
            continue
        subject = (row["subject_type"], row["subject_id"])
        if subject not in others or row["id"] < others[subject][0]:
            others[subject] = (row["id"], row["label"])
    compared = [(i.label, others[i.subject][1]) for i in scored if i.subject in others]
    agreeing = sum(1 for a, b in compared if a == b)

    return Evaluation(
        question_set=name,
        question_set_version=version,
        question_key=question_key,
        model=model,
        split=split,
        dataset_ref=labelled_by,
        dataset_sha256=dataset,
        analysis_plan_hash=plan_identity,
        keyword_baseline_ref=keyword_ref,
        answers_sha256=_sha256_lines([str(i.answer["answer_id"]) for i in answered]),
        code_commit=None,
        possibly_in_training=in_training,
        ci_level=jev_prereg.REPORT_CI,
        gate_ci_level=jev_prereg.GATE_CI,
        n=n,
        n_per_class=n_per_class,
        n_valid=len(valid),
        n_escape=sum(1 for i in valid if escape is not None and i.predicted == escape),
        n_invalid=len(answered) - len(valid),
        n_not_asked=n - len(answered),
        n_contested=contested_here,
        n_other_plans=other_plans,
        n_plan_unknown=plan_unknown,
        n_distinct_states=len({i.answer["state_hash"] for i in answered}),
        accuracy=accuracy[0],
        accuracy_wilson_low=accuracy[1],
        accuracy_wilson_high=accuracy[2],
        accuracy_all_items=all_items[0],
        accuracy_all_items_wilson_low=all_items[1],
        accuracy_all_items_wilson_high=all_items[2],
        balanced_accuracy=balanced,
        per_class=per_class,
        brier=brier,
        brier_ci_low=brier_low,
        brier_ci_high=brier_high,
        brier_reference=reference,
        calibration_bins=bins,
        majority_baseline_accuracy=majority_accuracy,
        keyword_baseline_accuracy=keyword_accuracy,
        vs_majority_diff=comparisons["majority"][0],
        vs_majority_diff_low=comparisons["majority"][1],
        vs_majority_diff_high=comparisons["majority"][2],
        vs_majority_jev_right_only=comparisons["majority"][3],
        vs_majority_baseline_right_only=comparisons["majority"][4],
        vs_keyword_diff=comparisons["keyword"][0],
        vs_keyword_diff_low=comparisons["keyword"][1],
        vs_keyword_diff_high=comparisons["keyword"][2],
        vs_keyword_jev_right_only=comparisons["keyword"][3],
        vs_keyword_baseline_right_only=comparisons["keyword"][4],
        threshold_outcome=choice.outcome,
        threshold_statistic=statistic,
        threshold_target=target_value,
        threshold_dataset_sha256=threshold_dataset,
        threshold=threshold,
        coverage_at_threshold=coverage,
        n_at_threshold=n_at,
        accuracy_at_threshold=at_threshold[0],
        accuracy_at_threshold_wilson_low=at_threshold[1],
        accuracy_at_threshold_wilson_high=at_threshold[2],
        flip_rate=jev_stats.proportion(uniform_flipped, uniform_n),
        flip_rate_n=uniform_n,
        flip_rate_not_compared=uniform_apart,
        flip_rate_low_margin=jev_stats.proportion(low_flipped, low_n),
        flip_rate_low_margin_n=low_n,
        flip_rate_low_margin_not_compared=low_apart,
        flip_rate_near_threshold=near[0],
        flip_rate_near_threshold_n=near[1],
        flip_rate_near_threshold_not_compared=near[2],
        flip_median_lag_hours=statistics.median(lags) if lags else None,
        labeller_agreement=jev_stats.proportion(agreeing, len(compared)),
        labeller_kappa=jev_stats.cohen_kappa(
            [a for a, _ in compared], [b for _, b in compared]
        ),
        labeller_agreement_n=len(compared),
    )


async def read_ledger(
    conn: asyncpg.Connection,
    *,
    question_set: jev_questions.QuestionSet,
    question_key: str,
    model: str,
) -> Ledger:
    """Everything :func:`build_evaluation` reads, through ``jev_repo``."""
    name, version = question_set.name, question_set.version
    labels = await jev_repo.labels_for(
        conn,
        question_set=name,
        version=version,
        question_key=question_key,
        labelled_by=None,
    )
    subjects = sorted({(row["subject_type"], row["subject_id"]) for row in labels})
    answers = await jev_repo.answers_for_subjects(
        conn,
        question_set=name,
        version=version,
        question_key=question_key,
        model=model,
        subjects=subjects,
    )
    pairs = await jev_repo.probe_pairs(
        conn,
        question_set=name,
        version=version,
        question_key=question_key,
        model=model,
    )
    reasks = await jev_repo.job_outcomes(
        conn, sorted({reask_job_key(p["canonical_request_id"]) for p in pairs})
    )
    return Ledger(
        labels=labels,
        answers=answers,
        jobs=await jev_repo.ask_jobs_about(
            conn, question_set=name, version=version, subjects=subjects
        ),
        dates=await jev_repo.item_dates(conn, subjects),
        texts=await jev_repo.subject_texts(conn, subjects),
        pairs=pairs,
        reasks=reasks,
        records=await jev_repo.finding_records(conn, subjects),
    )


async def evaluate(
    conn: asyncpg.Connection,
    *,
    question_set: jev_questions.QuestionSet,
    question_key: str,
    labelled_by: str,
    model: str,
    split: Literal["all", "test", "dev"],
) -> Evaluation:
    """
    One question of ``question_set`` against exactly one labeller's labels,
    for ``model``, over ``split``: every column of ``jev_evaluations``, by
    design section 10.1's definitions, ``code_commit`` left for ``--record``.
    Reads only; :class:`Refused` for a set with no ground truth, a question
    with no plan registered before its answers, a labeller or model nobody
    may name, and nothing labelled.

    The function computes whatever split it is asked for: the rule that a
    look at the held-out items is recorded binds the harness's own commands
    (:func:`execute`), and a caller of this function, or anyone reading the
    test split by hand, is outside the protocol (docs/08 open item 79).
    """
    if question_set is not jev_questions.REGISTRY.get(question_set.name):
        raise Refused(f"{question_set.name} v{question_set.version} is not registered")
    problem = question_problem(question_set, question_key)
    if problem is not None:
        raise Refused(problem)
    if not LABELLER.fullmatch(labelled_by):
        raise Refused(
            f"{labelled_by!r} is no labeller: a person is operator:NAME and a "
            "dataset source:NAME@HASH"
        )
    model_problem = jev_catalogue.model_problem(model)
    if model_problem is not None:
        raise Refused(model_problem)
    ledger = await read_ledger(
        conn, question_set=question_set, question_key=question_key, model=model
    )
    return build_evaluation(
        question_set=question_set,
        question_key=question_key,
        labelled_by=labelled_by,
        model=model,
        split=split,
        ledger=ledger,
    )


def resolve_commit(
    given: str | None,
    environ: Mapping[str, str],
    git: Callable[[Sequence[str]], str | None],
) -> str:
    """
    The commit an evaluation is recorded under: ``--commit``, else
    ``GIT_COMMIT``, else ``git rev-parse HEAD`` on a working tree with nothing
    uncommitted; 40 lowercase hex digits, or :class:`Refused`. A figure that
    cannot name the code that computed it cannot be recomputed, and an
    uncommitted tree's code is named by no commit at all.
    """
    if given is not None:
        candidate, source = given.strip(), "--commit"
    elif environ.get("GIT_COMMIT", "").strip():
        candidate, source = environ["GIT_COMMIT"].strip(), "GIT_COMMIT"
    else:
        status = git(["status", "--porcelain"])
        if status is None:
            raise Refused(
                "no commit to record the evaluation under: no --commit, no "
                "GIT_COMMIT, and git could not be read"
            )
        if status.strip():
            raise Refused(
                "the working tree has uncommitted changes, so no commit names the "
                "code computing this evaluation; commit them, or name one"
            )
        candidate, source = (git(["rev-parse", "HEAD"]) or "").strip(), "git"
    if not COMMIT.fullmatch(candidate):
        raise Refused(f"{source} is not a commit: 40 lowercase hex digits")
    return candidate


def _git(arguments: Sequence[str]) -> str | None:
    """``git`` in the repository, its output, or ``None`` if it failed."""
    try:
        done = subprocess.run(
            ["git", *arguments],
            cwd=REPOSITORY,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


# ---------------------------------------------------------------------------
# Labels (phase C9)
# ---------------------------------------------------------------------------


def _registered(name: str) -> jev_questions.QuestionSet:
    question_set = jev_questions.REGISTRY.get(name)
    if question_set is None:
        raise Refused(f"no question set named {name!r} is registered")
    return question_set


def _subject_type(question_set: jev_questions.QuestionSet) -> str:
    return jev_questions.STATE_SUBJECT[question_set.state_model]


async def export_labels(
    conn: asyncpg.Connection,
    *,
    question_set: jev_questions.QuestionSet,
    question_key: str,
    sample: int | None,
    include_quarantined: bool,
) -> str:
    """
    The subjects a labeller is to label for one question, as CSV with
    :data:`EXPORT_COLUMNS` and no answer column: every stored subject of the
    set's kind, in the order of their content addresses, the first ``sample``
    of them where one is asked for.

    Which subjects is decided by the stored texts and the code alone. Web
    text the code screen, run on it now, flags is left out unless
    ``include_quarantined`` — a quarantine made by code, from the words, and
    never asked about by any set — and nothing else is. Content Jev's own
    injection screen quarantined, or a vendor's content block, is exported
    like any other: those were decided by a response to a request, and
    leaving them out chose the subjects by what Jev said, so that an
    evaluation of the screen never saw one of its own ``true`` answers
    (docs/08, C9). Nothing about any answer, request or quarantine is read,
    so neither what a labeller sees nor which subjects can depend on what Jev
    or the vendor said
    (``tests/unit/test_jev_eval.py::TestTheBlindExport``, and on PostgreSQL
    ``tests/integration/test_jev_evaluations.py::TestTheCommandsOnPostgres``).
    """
    problem = question_problem(question_set, question_key)
    if problem is not None:
        raise Refused(problem)
    if sample is not None and sample < 1:
        raise Refused(f"a sample is at least one subject, not {sample}")
    subject_type = _subject_type(question_set)
    rows = await jev_repo.subjects_to_label(conn, subject_type=subject_type)
    if subject_type == "web_excerpt" and not include_quarantined:
        rows = [row for row in rows if web_sources.code_screen(row["text"]) is None]
    chosen = sorted(rows, key=lambda row: row["subject_id"])
    if sample is not None:
        chosen = chosen[:sample]
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(EXPORT_COLUMNS)
    for row in chosen:
        writer.writerow([row["subject_type"], row["subject_id"], row["text"]])
    return out.getvalue()


def source_labeller(dataset: str, data: bytes) -> str:
    """``source:<dataset>@<sha12>``: a dataset's labeller, at the file's hash."""
    if not DATASET.fullmatch(dataset):
        raise Refused(
            f"{dataset!r} is not a dataset's name: lower-case letters, digits "
            "and hyphens"
        )
    if dataset in web_sources.ALLOWED_SOURCES:
        raise Refused(
            f"{dataset} is an allow-listed source, whose labeller is its own "
            "grouping, recorded by the web ingest alone"
        )
    return f"source:{dataset}@{hashlib.sha256(data).hexdigest()[:12]}"


def parse_labels(data: bytes) -> list[dict[str, str]]:
    """
    A labels file's rows, read as UTF-8 CSV with a header, or
    :class:`Refused`: the six columns of :data:`IMPORT_COLUMNS`, and of
    :data:`IMPORT_OPTIONAL_COLUMNS` only, every one named once.
    """
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise Refused("the labels file is not UTF-8") from None
    reader = csv.DictReader(io.StringIO(text, newline=""))
    header = reader.fieldnames or []
    unknown = sorted(set(header) - set(IMPORT_COLUMNS) - set(IMPORT_OPTIONAL_COLUMNS))
    missing = sorted(set(IMPORT_COLUMNS) - set(header))
    if unknown or missing or len(set(header)) != len(header):
        raise Refused(
            f"a labels file's columns are {list(IMPORT_COLUMNS)}, optionally "
            f"{list(IMPORT_OPTIONAL_COLUMNS)}, each once; this one's are "
            f"{header} (an answer column is never read)"
        )
    rows = []
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise Refused(
                f"line {reader.line_num} of the labels file is not a row of it"
            )
        rows.append(row)
    return rows


def label_problems(
    rows: Sequence[Mapping[str, str]],
) -> list[str]:
    """
    Every reason a row of a labels file may not be recorded, by its line:
    the set must be registered and the row's version its registered one, the
    question one it asks with a plan, the subject its kind of text named by
    a content address, the label one of the question's options and never its
    escape, a ``text`` given the text the address names, and each item
    labelled once in the file.
    """
    problems = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for line, row in enumerate(rows, start=2):
        name = row["question_set"]
        question_set = jev_questions.REGISTRY.get(name)
        if question_set is None:
            problems.append(f"line {line}: no set named {name!r} is registered")
            continue
        version = row["question_set_version"]
        if version != str(question_set.version):
            problems.append(
                f"line {line}: {name} is registered at v{question_set.version}, "
                f"not {version!r}"
            )
            continue
        key = row["question_key"]
        problem = question_problem(question_set, key)
        if problem is not None:
            problems.append(f"line {line}: {problem}")
            continue
        subject_type = _subject_type(question_set)
        if row["subject_type"] != subject_type:
            problems.append(
                f"line {line}: {name} is asked about a {subject_type!r}, not a "
                f"{row['subject_type']!r}"
            )
            continue
        subject_id = row["subject_id"]
        if not re.fullmatch(r"[0-9a-f]{64}", subject_id):
            problems.append(f"line {line}: a subject is named by its sha256")
            continue
        try:
            options = options_of(question_set, key)
        except Refused as refused:
            problems.append(f"line {line}: {refused}")
            continue
        escape = question_set.escape_options.get(key)
        label = row["label"]
        if label == escape:
            problems.append(
                f"line {line}: {label!r} is the question's escape, which an "
                "answer may be and a label never is"
            )
            continue
        if label not in options:
            problems.append(f"line {line}: {label!r} is not one of {options}")
            continue
        text = row.get("text")
        if text and text_sha256(text) != subject_id:
            problems.append(
                f"line {line}: its text is not the text its subject names; the "
                "label would be of words nobody is asked about"
            )
            continue
        item = (name, version, key, subject_type, subject_id)
        if item in seen:
            problems.append(f"line {line}: the file labels this item twice")
            continue
        seen.add(item)
    return problems


async def import_labels(
    conn: asyncpg.Connection, *, rows: Sequence[Mapping[str, str]], labelled_by: str
) -> dict[str, Any]:
    """
    Record every row of a labels file as ``labelled_by``'s, or none of them:
    each row checked (:func:`label_problems`), each subject stored, and no
    item this labeller has labelled otherwise, since a label revised after
    the answers are seen is not ground truth. A row this labeller has
    recorded already, with the same label, is counted and written again by
    nobody. Through ``jev_repo.record_label``, in the caller's transaction.
    """
    if not LABELLER.fullmatch(labelled_by):
        raise Refused(f"{labelled_by!r} is no labeller")
    problems = label_problems(rows)
    if not problems:
        wanted = sorted({(r["subject_type"], r["subject_id"]) for r in rows})
        stored = await jev_repo.subject_texts(conn, wanted)
        for line, row in enumerate(rows, start=2):
            if (row["subject_type"], row["subject_id"]) not in stored:
                problems.append(
                    f"line {line}: no stored {row['subject_type']} has the address "
                    f"{row['subject_id'][:12]}…"
                )
    already: dict[tuple[str, str, str, str], str] = {}
    if not problems:
        for name, version, key in sorted(
            {
                (r["question_set"], int(r["question_set_version"]), r["question_key"])
                for r in rows
            }
        ):
            for label in await jev_repo.labels_for(
                conn,
                question_set=name,
                version=version,
                question_key=key,
                labelled_by=labelled_by,
            ):
                already[(name, key, label["subject_type"], label["subject_id"])] = (
                    label["label"]
                )
        for line, row in enumerate(rows, start=2):
            item = (
                row["question_set"],
                row["question_key"],
                row["subject_type"],
                row["subject_id"],
            )
            if item in already and already[item] != row["label"]:
                problems.append(
                    f"line {line}: {labelled_by} labelled this item "
                    f"{already[item]!r} already, and a label is never revised"
                )
    if problems:
        raise Refused(
            "the labels file was refused, and nothing was recorded:\n"
            + "\n".join(problems)
        )
    recorded = repeated = 0
    for row in rows:
        item = (
            row["question_set"],
            row["question_key"],
            row["subject_type"],
            row["subject_id"],
        )
        if item in already:
            repeated += 1
            continue
        await jev_repo.record_label(
            conn,
            question_set=row["question_set"],
            question_set_version=int(row["question_set_version"]),
            question_key=row["question_key"],
            subject_type=row["subject_type"],
            subject_id=row["subject_id"],
            label=row["label"],
            labelled_by=labelled_by,
            note=row.get("note") or None,
        )
        recorded += 1
    return {"labelled_by": labelled_by, "recorded": recorded, "already": repeated}


def _question_words(question: Mapping[str, Any]) -> tuple[Any, ...]:
    """What a question's options are: its type and its criteria, in order."""
    criteria = question.get("criteria")
    if isinstance(criteria, Mapping):
        criteria = tuple(criteria.items())
    elif isinstance(criteria, list):
        criteria = tuple(criteria)
    return (question.get("type"), criteria)


async def copy_labels(
    conn: asyncpg.Connection,
    *,
    question_set: jev_questions.QuestionSet,
    question_key: str,
    from_version: int,
    to_version: int,
) -> dict[str, Any]:
    """
    Carry every label of ``question_key`` at ``from_version`` to the
    registered ``to_version``, each by its own labeller, where the question's
    options — its type, and its options with their descriptions, in order —
    are the same in both. A version no longer registered is read from the
    requests it was asked with, the only place its words are kept, and is
    refused when none was. An item a labeller has labelled at the new version
    keeps its label. Through ``jev_repo.record_label``, in the caller's
    transaction.
    """
    if to_version != question_set.version:
        raise Refused(
            f"labels are copied to {question_set.name}'s registered version, "
            f"v{question_set.version}, not v{to_version}"
        )
    if from_version == to_version:
        raise Refused("a version's labels are its own already")
    problem = question_problem(question_set, question_key)
    if problem is not None:
        raise Refused(problem)
    registered = dict(question_set.questions)[question_key]
    recorded = await jev_repo.recorded_questions(
        conn, question_set=question_set.name, version=from_version
    )
    if not recorded:
        raise Refused(
            f"{question_set.name} v{from_version}'s words are on record nowhere: "
            "no request of it is in the ledger, so its options cannot be compared"
        )
    if any(
        question_key not in words
        or _question_words(words[question_key]) != _question_words(registered)
        for words in recorded
    ):
        raise Refused(
            f"{question_key!r}'s options in v{from_version} are not those of "
            f"v{to_version}, so its labels are of another question"
        )
    labels = await jev_repo.labels_for(
        conn,
        question_set=question_set.name,
        version=from_version,
        question_key=question_key,
        labelled_by=None,
    )
    held = {
        (label["subject_type"], label["subject_id"], label["labelled_by"])
        for label in await jev_repo.labels_for(
            conn,
            question_set=question_set.name,
            version=to_version,
            question_key=question_key,
            labelled_by=None,
        )
    }
    copied = kept = 0
    for label in labels:
        if (label["subject_type"], label["subject_id"], label["labelled_by"]) in held:
            kept += 1
            continue
        note = f"copied from v{from_version}"
        await jev_repo.record_label(
            conn,
            question_set=question_set.name,
            question_set_version=to_version,
            question_key=question_key,
            subject_type=label["subject_type"],
            subject_id=label["subject_id"],
            label=label["label"],
            labelled_by=label["labelled_by"],
            note=f"{note}; {label['note']}" if label["note"] else note,
        )
        copied += 1
    return {"copied": copied, "already_labelled": kept}


# ---------------------------------------------------------------------------
# The report (phase C9)
# ---------------------------------------------------------------------------


def quarantine_counts(reasons: Mapping[str, str]) -> dict[str, int]:
    """
    Quarantined content counted by what quarantined it first, in design
    section 10.3's words — never as injections found: the code screen by its
    version, Jev's screen, which is not calibrated, and vendor content blocks,
    each 0 where none did, and anything else apart.
    """
    counts = {
        "by the code screen v1": 0,
        "by Jev's screen (not calibrated)": 0,
        "by vendor content blocks": 0,
    }
    for reason in reasons.values():
        phrase = "for another reason"
        screened = re.match(r"code-screen v(\d+): ", reason or "")
        if screened is not None:
            phrase = f"by the code screen v{screened.group(1)}"
        elif (reason or "").startswith(f"jev {jev_questions.SCREEN_SET_NAME} "):
            phrase = "by Jev's screen (not calibrated)"
        elif (reason or "").startswith("vendor content block "):
            phrase = "by vendor content blocks"
        counts[phrase] = counts.get(phrase, 0) + 1
    return counts


async def evaluations_report(conn: asyncpg.Connection) -> dict[str, Any]:
    """
    The newest evaluation of each set, version, question, model, labeller and
    split — never one labeller's standing for another's — each with whether
    it could arm a threshold and every reason it could not
    (``jev_calibration.usable``, against the pin and the plans in force now),
    how many of its set, version and question's looks at the held-out items
    are spent, under every model (plan version 2, M3), and the quarantines by
    what made them.
    """
    pin = await flags.jev_model(conn)
    entries = []
    for row in await jev_repo.latest_evaluations(conn):
        everything = await jev_repo.evaluations_for(
            conn, question_set=row["question_set"]
        )
        registered = jev_questions.REGISTRY.get(row["question_set"])
        plan_hash = (
            jev_calibration.analysis_plan_hash(registered.name, registered.version)
            if registered is not None
            else None
        )
        usable, threshold, reasons = jev_calibration.usable(
            row,
            earlier=[other for other in everything if other["id"] != row["id"]],
            pin=pin or "",
            plan_hash=plan_hash or "",
        )
        entries.append(
            {
                "evaluation": row,
                "usable": usable,
                "usable_threshold": threshold,
                "not_usable_because": reasons,
                "looks_spent": looks_spent(row, everything),
            }
        )
    return {
        "pin": pin,
        "evaluations": entries,
        "quarantined_content": quarantine_counts(
            await jev_repo.quarantine_reasons(conn)
        ),
    }


def looks_spent(
    evaluation: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> int:
    """
    How many looks at the held-out items the set, version and question of
    ``evaluation`` have spent: the recorded rows among ``rows`` of that
    identity (``jev_prereg.LOOKS_COUNTED_BY``, never the model) on a split
    that holds the test items (``jev_prereg.LOOKED_AT_SPLITS``), ``evaluation``
    among them where it is one. What ``report`` prints beside each row, so an
    operator sees how many of the ``jev_prereg.MAX_LOOKS`` are left before a
    new set version is the only way to arm (docs/08 open item 78).
    """

    def identity(row: Mapping[str, Any]) -> tuple[Any, ...]:
        return tuple(row.get(column) for column in jev_prereg.LOOKS_COUNTED_BY)

    counted = {
        row.get("id"): row
        for row in [*rows, evaluation]
        if identity(row) == identity(evaluation)
        and row.get("split") in jev_prereg.LOOKED_AT_SPLITS
    }
    return len(counted)


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
        f"plan v{report['plan_version']} {report['plan_hash'][:12]}; regime plan "
        f"v{report['regime_plan_version']} {report['regime_plan_hash'][:12]}",
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
        rule = f"the regime plan v{report['regime_plan_version']} baseline rule"
        lines.append(
            format_count(
                f"  agrees with {rule}",
                figures["baseline_agreement_sessions"],
            )
        )
        lines.append(
            format_figure(
                f"  agrees with {rule}, distinct states",
                figures["baseline_agreement_states"],
            )
        )
        for plan, sessions in figures["not_scored"].items():
            under = (
                "no regime plan recorded"
                if plan == UNKNOWN_PLAN
                else f"regime plan {plan[:12]}, not this one"
            )
            lines.append(f"  not scored: {sessions} sessions answered under {under}")
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
    lines.append(
        f"plan v{report['plan_version']} {report['plan_hash'][:12]}; regime plan "
        f"v{report['regime_plan_version']} {report['regime_plan_hash'][:12]}"
    )
    return "\n".join(lines)


def _count_of(share: float | None, n: int | None) -> int | None:
    """The k behind a stored share of n: exact, since the share is k / n."""
    if share is None or not n:
        return None
    return round(share * n)


def _interval(low: Any, high: Any, label: str) -> str:
    if low is None or high is None:
        return ""
    return f" ({label}: {said(low)} to {said(high)})"


def _level(value: Any) -> str | None:
    """
    A level a row recorded, as printed — 95%, 99.5%, 99.9375% — or ``None``:
    exactly, as the decimal it was written as, since the gate's level from plan
    version 2, 0.999375, rounded to one place would print as a level nobody
    registered.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    digits = format((Decimal(repr(float(value))) * 100).normalize(), "f")
    return f"{digits}%"


def _beaten(e: Mapping[str, Any], column: str, name: str, gate: float | None) -> str:
    """
    Whether Jev beat a baseline, in the words the row's discordant items
    allow: by the exact one-sided sign test at the row's gate level, "beats
    it" or "does not beat it", with the items it rests on and its chance;
    "too few to say" where not even every one of them going Jev's way could
    reach the level; never from the bootstrap interval, whose bound over a
    few such items sits at the point estimate.
    """
    jev_only = e.get(f"vs_{column}_jev_right_only")
    base_only = e.get(f"vs_{column}_baseline_right_only")
    counts = (jev_only, base_only)
    if gate is None or not all(
        isinstance(c, int) and not isinstance(c, bool) and c >= 0 for c in counts
    ):
        return "not measured whether Jev is the better of the two"
    differ = jev_only + base_only
    which = (
        f"they differ on {differ} item{'' if differ == 1 else 's'}, Jev right "
        f"alone on {jev_only} and {name} right alone on {base_only}"
    )
    if not jev_stats.sign_test_can_decide(differ, gate):
        return (
            f"{which}: too few for the exact one-sided sign test at "
            f"{_level(gate)} to say"
        )
    chance = jev_stats.sign_test(jev_only, base_only)
    verdict = (
        "beats it"
        if jev_stats.sign_test_beats(jev_only, base_only, gate)
        else "does not beat it"
    )
    return (
        f"{which}; exact one-sided sign test at {_level(gate)}, p = "
        f"{chance:.3g}: {verdict}"
    )


def format_evaluation(evaluation: Mapping[str, Any]) -> str:
    """
    One evaluation, every figure with its n and its interval, in the words
    design section 10.3 allows: "agreed with the labeller on k of n answered
    items", never "Jev is x% accurate"; "upper bound" on every figure of an
    evaluation possibly in training; a baseline "beaten" only by the exact
    one-sided sign test of the items only one of the two got right, at the
    gate level, and never on a bootstrap bound or a point estimate; a
    threshold "chosen on the dev split, measured on the test split", and
    none printed as 0. Every level printed is the one the row recorded —
    ``ci_level`` for each interval, ``gate_ci_level`` for each gate — never
    the plan in force when it is read. A figure not measured says so, and no
    list is sorted by a figure.
    """
    e = evaluation
    reported = _level(e.get("ci_level"))
    gate_value = e.get("gate_ci_level")
    gate = None if _level(gate_value) is None else float(gate_value)
    wilson = f"Wilson {reported}" if reported else "Wilson, level not recorded"
    bootstrap = f"bootstrap {reported}" if reported else "bootstrap, level not recorded"
    labeller = e["dataset_ref"]
    readme = (
        " (the README's own grouping, never ground truth)"
        if labeller.startswith("source:pwb-readme@")
        else ""
    )
    bound = ", an upper bound" if e["possibly_in_training"] else ""
    lines = [
        f"{e['question_set']} v{e['question_set_version']} {e['question_key']}, "
        f"{e['model']}; labeller {labeller}{readme}; split {e['split']}; "
        f"dataset {str(e['dataset_sha256'])[:12]}; plans "
        f"{said(e.get('analysis_plan_hash'))[:12]}",
    ]
    if e["possibly_in_training"]:
        lines.append(
            "UPPER BOUND: an item is undated or dated on or before the model was "
            "first observed, so it may be in the model's training data; every "
            "figure below is an upper bound, and no threshold rests on it"
        )
    lines.append(
        f"items: {e['n']} scored; {said(e.get('n_other_plans'))} answered under "
        f"other plans and {said(e.get('n_plan_unknown'))} under plans unknown, set "
        f"apart; {said(e.get('n_contested'))} contested"
    )
    lines.append(
        f"answers: {said(e.get('n_valid'))} valid ({said(e.get('n_escape'))} the "
        f"escape), {said(e.get('n_invalid'))} not valid, {said(e.get('n_not_asked'))} "
        f"not asked, over {said(e.get('n_distinct_states'))} distinct states"
    )
    n_valid = e.get("n_valid")
    if e.get("accuracy") is None:
        lines.append(f"accuracy: not measured (n = {said(n_valid)} valid answers)")
    else:
        lines.append(
            f"accuracy: agreed with {labeller} on "
            f"{_count_of(e['accuracy'], n_valid)} of {n_valid} answered items "
            f"({str(e['dataset_sha256'])[:12]}, {e['split']}) = {said(e['accuracy'])}"
            + _interval(e["accuracy_wilson_low"], e["accuracy_wilson_high"], wilson)
            + bound
        )
    if e.get("accuracy_all_items") is None:
        lines.append(f"accuracy over every item: not measured (n = {e['n']})")
    else:
        lines.append(
            f"accuracy over every item, the not valid and the not asked counted "
            f"wrong: {_count_of(e['accuracy_all_items'], e['n'])} of {e['n']} = "
            f"{said(e['accuracy_all_items'])}"
            + _interval(
                e["accuracy_all_items_wilson_low"],
                e["accuracy_all_items_wilson_high"],
                wilson,
            )
            + bound
        )
    lines.append(
        f"balanced accuracy, the mean recall over the classes labelled: "
        f"{said(e.get('balanced_accuracy'))}{bound}"
    )
    for label, figures in (e.get("per_class") or {}).items():
        if figures["too_few_to_say"]:
            lines.append(f"  {label}: too few to say (n = {figures['n']})")
            continue
        recall = (
            f"recall {figures['correct']} of {figures['n']} = "
            f"{said(figures['recall'])}"
            + _interval(*(figures["recall_wilson"] or (None, None)), wilson)
        )
        if figures["precision"] is None:
            precision = f"precision not measured (predicted {figures['predicted']})"
        else:
            precision = (
                f"precision {figures['correct']} of {figures['predicted']} = "
                f"{said(figures['precision'])}"
                + _interval(*(figures["precision_wilson"] or (None, None)), wilson)
            )
        keyword = figures["keyword"]
        lines.append(
            f"  {label}: n {figures['n']}, {recall}, {precision}; the keyword rule "
            f"predicted {keyword['predicted']}, precision "
            f"{said(keyword['precision'])}, recall {said(keyword['recall'])}"
        )
    if e.get("brier") is None:
        lines.append(f"Brier: not measured (n = {said(n_valid)} valid answers)")
    else:
        lines.append(
            f"Brier: {said(e['brier'])} over {n_valid} valid answers"
            + _interval(e["brier_ci_low"], e["brier_ci_high"], bootstrap)
            + f", beside its climatology {said(e['brier_reference'])}{bound}"
        )
    for b in e.get("calibration_bins") or []:
        lines.append(
            f"  stated p in [{b['low']:.1f}, {b['high']:.1f}]: {b['n']} answers, "
            f"mean {said(b['mean_p'])}, agreement {said(b['agreement'])}"
            + _interval(*(b["wilson"] or (None, None)), wilson)
        )
    lines.append(
        f"baselines on the same {e['n']} items: the majority label, in-sample "
        f"(which favours it), {said(e.get('majority_baseline_accuracy'))}; the "
        f"keyword rule ({said(e.get('keyword_baseline_ref'))}) "
        f"{said(e.get('keyword_baseline_accuracy'))}"
    )
    for name, column in (
        ("the majority label", "majority"),
        ("the keyword rule", "keyword"),
    ):
        point = e.get(f"vs_{column}_diff")
        low, high = e.get(f"vs_{column}_diff_low"), e.get(f"vs_{column}_diff_high")
        if point is None:
            lines.append(f"Jev minus {name}: not measured")
            continue
        lines.append(
            f"Jev minus {name} on the same {e['n']} items: {point:+.3f}"
            + _interval(low, high, bootstrap)
            + f"; {_beaten(e, column, name, gate)}{bound}"
        )
    outcome = e.get("threshold_outcome")
    if outcome == "chosen":
        tested = e.get("n_at_threshold")
        statistic = e["threshold_statistic"]
        right = _count_of(e.get("accuracy_at_threshold"), tested)
        measured = (
            f"{statistic} {right} of {tested} = {said(e['accuracy_at_threshold'])}"
            + _interval(
                e["accuracy_at_threshold_wilson_low"],
                e["accuracy_at_threshold_wilson_high"],
                wilson,
            )
            if e.get("accuracy_at_threshold") is not None
            else f"{statistic} not measured (n = {said(tested)})"
        )
        by = (
            f" by its one-sided Wilson lower bound at {_level(gate)}"
            if gate is not None
            else ""
        )
        if e.get("split") == DEV_SPLIT:
            # Never a promise that a look bears it out: the look's search runs
            # only when every item the look reads is dated after the pin was
            # first observed, and this run reads no date of a test item, so
            # it cannot know (D1's review, D1RP-2; docs/08 open item 83).
            lines.append(
                f"threshold: margin >= {said(e['threshold'])}, chosen on the dev "
                f"split to reach {said(e['threshold_target'])}{by}; nothing is "
                "measured at it here, since this run reads no label or date of a "
                "test item. A recorded look measures it on the test split, and "
                "searches for it again only if every item the look reads, the "
                "held-out ones included, is dated after the model was first "
                "observed; otherwise the look is an upper bound and attempts no "
                "threshold"
            )
        else:
            lines.append(
                f"threshold: margin >= {said(e['threshold'])}, chosen on the dev "
                f"split to reach {said(e['threshold_target'])}{by}, measured on "
                f"the test split: coverage {said(e['coverage_at_threshold'])}, "
                f"{measured}"
            )
    elif outcome == "none_found":
        lines.append(
            "threshold: none found on the dev split; every lane stays "
            "suggestion-only and not calibrated"
        )
    else:
        why = (
            "possibly in training"
            if e["possibly_in_training"]
            else f"fewer than {jev_prereg.MIN_DEV_ITEMS} dev items"
        )
        lines.append(f"threshold: not attempted ({why}); not calibrated")
    for name, rate, pairs in (
        ("uniform", "flip_rate", "flip_rate_n"),
        ("low-margin", "flip_rate_low_margin", "flip_rate_low_margin_n"),
        (
            "near the threshold",
            "flip_rate_near_threshold",
            "flip_rate_near_threshold_n",
        ),
    ):
        share, n = e.get(rate), e.get(pairs)
        if share is None and n is None:
            lines.append(f"flips, {name}: not measured (no threshold chosen)")
            continue
        # Every re-ask sampled under the plan is in the text: those compared,
        # and those whose pair could not be — never a rate quoted over the
        # valid ones as though they were all that was asked.
        apart = e.get(f"{rate}_not_compared")
        asked = (
            f"{n + apart} re-asked, {apart} not compared"
            if isinstance(apart, int) and isinstance(n, int)
            else "how many could not be compared not recorded"
        )
        if share is None:
            lines.append(f"flips, {name}: not measured ({n} compared; {asked})")
            continue
        k = _count_of(share, n)
        interval = jev_stats.wilson(k, n, float(e["ci_level"])) if reported else None
        lines.append(
            f"flips, {name}: {k} of {n} compared re-asks changed their argmax = "
            f"{said(share)}"
            + _interval(*(interval or (None, None)), wilson)
            + f"; {asked}"
        )
    lag = e.get("flip_median_lag_hours")
    lines.append(
        "median lag of a uniform re-ask: "
        + ("not measured" if lag is None else f"{said(lag)} h")
    )
    if e.get("labeller_agreement") is None:
        lines.append(
            f"labeller agreement: not measured ({said(e.get('labeller_agreement_n'))} "
            "items another labeller labelled)"
        )
    else:
        lines.append(
            f"labeller agreement: another labeller gave "
            f"{_count_of(e['labeller_agreement'], e['labeller_agreement_n'])} of "
            f"{e['labeller_agreement_n']} items {labeller}'s label = "
            f"{said(e['labeller_agreement'])}, Cohen's kappa "
            f"{said(e.get('labeller_kappa'))}"
        )
    commit = e.get("code_commit")
    if commit:
        lines.append(f"commit {commit}")
    elif e.get("split") == DEV_SPLIT:
        lines.append(
            "the development split's search: no look at the held-out items, no "
            "label or date of a test item read, and never recorded; the flip "
            "rates are the whole population's, as a look's are, since a flip "
            "uses no label"
        )
    else:
        lines.append("dry run: nothing recorded; --record writes it")
    return "\n".join(lines)


def format_report(report: Mapping[str, Any]) -> str:
    """Every evaluation the report holds, in the order read, and the quarantines."""
    lines = [f"pin {said(report['pin'])}"]
    if not report["evaluations"]:
        lines.append("no evaluation is recorded")
    for entry in report["evaluations"]:
        lines.append("")
        lines.append(format_evaluation(entry["evaluation"]))
        e = entry["evaluation"]
        looks = entry.get("looks_spent")
        lines.append(
            f"looks at the held-out items of {e['question_set']} "
            f"v{e['question_set_version']} {e['question_key']}, under every model: "
            + (
                "not counted"
                if looks is None
                else f"{looks} of {jev_prereg.MAX_LOOKS} spent"
            )
        )
        if entry["usable"]:
            lines.append(
                f"usable as a calibration, at margin >= "
                f"{said(entry['usable_threshold'])}; nothing that acts reads it"
            )
        else:
            reasons = "; ".join(
                jev_calibration.REASONS[r] for r in entry["not_usable_because"]
            )
            lines.append(f"not usable as a calibration: {reasons}")
    counts = "; ".join(
        f"{k} {phrase}" for phrase, k in report["quarantined_content"].items()
    )
    lines.append("")
    lines.append(f"quarantined content: {counts}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# What would leave, and how each ask came out (phase D2)
# ---------------------------------------------------------------------------
#
# docs/09, section 9.3. ``preview`` is what an operator reads before switching
# an area on; ``suggestions`` says how the asks about the findings register
# came out, and shows no answer. Both read, in the caller's read-only
# snapshot, and neither loads the planner or the handler: the reads and rules
# below are copies of theirs, held equal on the same rows by
# ``tests/integration/test_jev_findings.py::TestPreviewIsThePlanners``.

#: The subjects ``preview`` shows: a title the programme's model wrote. A web
#: set's subjects are chosen by the injection screen's own answers — content
#: it cleared, for the catalogue, and content its ``true`` is on record for,
#: for the screen's repairs — so listing them would show those answers, and
#: ``preview`` does not; phase D3's job-error skeleton joins it.
PREVIEWED_SUBJECTS = ("hypothesis_title", "finding_title")

#: How many subjects ``preview`` lists unless told: the planner's cap a pass
#: for every set it reads (``jev_plan.ASKS_PER_PASS``, held equal by
#: ``tests/unit/test_jev_eval.py::TestPreview``, since the harness may not
#: load the planner).
PREVIEW_LIMIT = 10


async def _titles_to_ask(
    conn: asyncpg.Connection,
    subject_type: str,
    question_set: jev_questions.QuestionSet,
    model: str,
    limit: int,
    day: date,
) -> list[dict[str, Any]]:
    """The planner's read of ``question_set``'s subjects, as it reads them."""
    read = (
        jev_repo.findings_to_ask
        if subject_type == "finding_title"
        else jev_repo.hypotheses_to_ask
    )
    return await read(
        conn, question_set=question_set, model=model, limit=limit, day=day
    )


async def _previewed(
    conn: asyncpg.Connection,
    question_set: jev_questions.QuestionSet,
    subject_type: str,
    row: Mapping[str, Any],
) -> dict[str, Any]:
    """
    One subject as the ``jev_ask`` handler would take it: the row read again
    by its ref, by column list (``jev_repo.get_finding_title``,
    ``get_hypothesis_title``), held to the address planned, to the
    programme's model as its writer and to its cap, and built into the state
    that would be sent — or why nothing would be, in code's words, quoting
    no text.
    """
    finding = subject_type == "finding_title"
    loaded = await (
        jev_repo.get_finding_title(conn, row["ref"])
        if finding
        else jev_repo.get_hypothesis_title(conn, row["ref"])
    )
    cap = (
        jev_questions.FINDING_TITLE_MAX_CHARS
        if finding
        else jev_questions.TITLE_MAX_CHARS
    )
    entry: dict[str, Any] = {
        "subject_type": subject_type,
        "subject_id": row["subject_id"],
        "source_id": row["ref"],
        "state": None,
        "not_sent_because": None,
    }
    title = None if loaded is None else loaded["title"]
    if loaded is None:
        entry["not_sent_because"] = "the row is no longer stored"
    elif not isinstance(title, str) or text_sha256(title) != row["subject_id"]:
        entry["not_sent_because"] = "the row no longer holds the text planned"
    elif loaded["origin"] != "model":
        entry["not_sent_because"] = (
            f"written by {loaded['origin']!r}, not by the programme's model"
        )
    elif len(title) > cap:
        entry["not_sent_because"] = (
            f"{len(title)} characters, over the {cap} its state carries"
        )
    else:
        state_model = (
            jev_questions.FindingTitleState
            if finding
            else jev_questions.HypothesisTitleState
        )
        try:
            entry["state"] = question_set.dump_state(state_model(title=title))
        except ValueError:
            entry["not_sent_because"] = "the title does not make the state"
    return entry


async def preview_report(
    conn: asyncpg.Connection,
    *,
    question_set: jev_questions.QuestionSet,
    limit: int,
    day: date,
) -> dict[str, Any]:
    """
    What ``question_set`` would be asked about on ``day``, and what would be
    sent: the subjects the planner's read returns, at most ``limit``, each
    with the row it comes from and the exact state the handler would build
    from it, or why nothing would be sent; and every switch the planner reads
    for it, through the shipped readers, whether each is on, the pin, the
    plans in force, the standing holds and the lane's calls left today.
    Whether a key is set is not the harness's to know: it holds none. Reads
    only, and enqueues nothing.
    """
    subject_type = jev_questions.STATE_SUBJECT.get(question_set.state_model)
    if question_set is not jev_questions.REGISTRY.get(question_set.name):
        raise Refused(f"{question_set.name} v{question_set.version} is not registered")
    if subject_type not in PREVIEWED_SUBJECTS:
        raise Refused(
            f"{question_set.name} is asked about a {subject_type!r}; preview shows "
            "what a title set would send, and a web set's subjects are chosen by "
            "the injection screen's own answers, which it does not show"
        )
    if limit < 1:
        raise Refused(f"a preview lists at least one subject, not {limit}")
    name, version, lane = question_set.name, question_set.version, question_set.lane
    area = jev_catalogue.LANE_AREA.get(lane)
    switches = {
        flags.PROGRAMME_ENABLED: await flags.programme_enabled(conn),
        flags.JEV_ENABLED: await flags.jev_enabled(conn),
        f"{flags.JEV_AREA_PREFIX}{area}": (
            area is not None and await flags.jev_area_enabled(conn, area)
        ),
    }
    if question_set.internal_detail:
        switches[flags.JEV_SEND_INTERNAL_DETAIL] = (
            await flags.jev_send_internal_detail(conn)
        )
    model = await flags.jev_model(conn)
    plans = jev_prereg.plans_in_force(name, version)
    holds = {
        "authentication_failure_today": await jev_repo.auth_failed_today(conn),
        "refused_at_this_version_under_the_pin": (
            model is not None
            and await jev_repo.set_refused(
                conn, question_set=name, version=version, model=model
            )
        ),
    }
    budget = await flags.jev_daily_request_budget(conn)
    lane_sets = sorted(
        other.name
        for other in jev_questions.REGISTRY.values()
        if other.lane == lane
    )
    calls_left = (
        jev_catalogue.lane_budget(budget, lane)
        - await jev_repo.requests_today(conn, lane)
        - await jev_repo.pending_asks(conn, lane_sets)
    )
    reasons = [f"{switch} is off" for switch, on in switches.items() if not on]
    if model is None:
        reasons.append("no usable pin is set")
    if plans is None:
        reasons.append(f"{name} v{version} has no analysis plan in force")
    reasons += [
        f"held: {hold.replace('_', ' ')}" for hold, on in holds.items() if on
    ]
    if calls_left <= 0:
        reasons.append(f"the {lane} lane has no call left today")
    subjects = []
    if model is not None and plans is not None:
        for row in await _titles_to_ask(
            conn, subject_type, question_set, model, limit, day
        ):
            subjects.append(await _previewed(conn, question_set, subject_type, row))
    return {
        "set": name,
        "version": version,
        "lane": lane,
        "provenance": question_set.provenance,
        "subject_type": subject_type,
        "day": day.isoformat(),
        "pin": model,
        "switches": switches,
        "plans_in_force": plans is not None,
        "holds": holds,
        "calls_left_today": max(calls_left, 0),
        "key": "not read: the harness holds none, and nothing is planned without one",
        "would_plan": not reasons,
        "not_planned_because": reasons,
        "subjects": subjects,
    }


def format_preview(report: Mapping[str, Any]) -> str:
    """``preview`` as text: the switches, then each subject and its state."""
    lines = [
        f"preview of {report['set']} v{report['version']} ({report['lane']} lane, "
        f"provenance {report['provenance']}, about a {report['subject_type']}) "
        f"for {report['day']}",
        f"pin: {said(report['pin'])}",
        "switches: "
        + "; ".join(
            f"{switch} {'on' if on else 'off'}"
            for switch, on in report["switches"].items()
        ),
        f"plans in force: {'yes' if report['plans_in_force'] else 'no'}",
        "holds: "
        + "; ".join(
            f"{hold.replace('_', ' ')}: {'yes' if on else 'no'}"
            for hold, on in report["holds"].items()
        ),
        f"calls left today in the lane: {report['calls_left_today']}",
        f"key: {report['key']}",
    ]
    if report["would_plan"]:
        lines.append("would plan: yes, given a key")
    else:
        lines.append("would plan: no — " + "; ".join(report["not_planned_because"]))
    lines.append(f"subjects: {len(report['subjects'])}")
    for subject in report["subjects"]:
        lines.append(
            f"{subject['subject_type']} {subject['subject_id']} from "
            f"{subject['source_id']}"
        )
        if subject["state"] is not None:
            state = json.dumps(subject["state"], ensure_ascii=False, sort_keys=True)
            lines.append(f"  would send: {state}")
        else:
            lines.append(f"  would send nothing: {subject['not_sent_because']}")
    return "\n".join(lines)


#: How ``suggestions`` says who wrote a finding no set asks about.
WRITERS = {
    "operator": "written by an operator",
    "unknown": "written before migration 0015 named its writer",
}


def ask_status(
    origin: str, title: object, outcome: Mapping[str, Any] | None
) -> str:
    """
    How one findings set's ask about one finding came out, in a fixed
    phrase: ``answered`` or ``invalid`` for a canonical answer on record
    — never which option, never a probability — then a hold, a retirement,
    a job waiting, or why it was not asked.
    """
    if origin != "model":
        return f"not asked: {WRITERS.get(origin, 'not written by the programme')}"
    if not isinstance(title, str) or not title:
        return "not asked: no title"
    if len(title) > jev_questions.FINDING_TITLE_MAX_CHARS:
        return (
            f"not asked: over the {jev_questions.FINDING_TITLE_MAX_CHARS}-"
            "character cap"
        )
    if outcome is None:
        return "not asked: no usable pin"
    if outcome["answered"]:
        return "answered" if outcome["valid"] else "invalid"
    if outcome["blocked"]:
        return "held: a vendor content block, so never sent again"
    if outcome["retired"]:
        return f"retired: {outcome['failed_calls']} failed calls"
    if outcome["waiting"]:
        return "waiting: a job is queued or running"
    if outcome["failed_calls"]:
        return f"not answered yet: {outcome['failed_calls']} failed calls"
    return "not asked yet"


async def suggestions_report(conn: asyncpg.Connection) -> dict[str, Any]:
    """
    For each open finding but Jev's, by its ref, whether each findings set
    asked about its title and how the ask came out (:func:`ask_status`); and
    the switches, the pin and the holds that decide whether any is asked.
    Statuses, refs and counts alone: no title, no answer, no probability and
    no chip, since anyone who reads this may later label a set, and a label
    made after seeing the answer is not blind (docs/09, sections 3.5 and
    9.3). Jev's own findings are counted, never named: a ref beside a
    hypothesis would say what Jev answered about its title.
    """
    model = await flags.jev_model(conn)
    sets = [
        question_set
        for question_set in jev_questions.REGISTRY.values()
        if jev_questions.STATE_SUBJECT.get(question_set.state_model) == "finding_title"
    ]
    areas = sorted(
        {
            area
            for question_set in sets
            if (area := jev_catalogue.LANE_AREA.get(question_set.lane)) is not None
        }
    )
    switches = {
        flags.PROGRAMME_ENABLED: await flags.programme_enabled(conn),
        flags.JEV_ENABLED: await flags.jev_enabled(conn),
        **{
            f"{flags.JEV_AREA_PREFIX}{area}": await flags.jev_area_enabled(conn, area)
            for area in areas
        },
    }
    holds = {"authentication_failure_today": await jev_repo.auth_failed_today(conn)}
    for question_set in sets:
        holds[f"{question_set.name} refused under the pin"] = (
            model is not None
            and await jev_repo.set_refused(
                conn,
                question_set=question_set.name,
                version=question_set.version,
                model=model,
            )
        )
    findings = [
        finding
        for finding in await jev_repo.open_findings(conn)
        if finding["origin"] != "jev"
    ]
    addresses = {
        finding["ref"]: text_sha256(finding["title"])
        for finding in findings
        if isinstance(finding["title"], str)
    }
    outcomes: dict[str, dict[str, dict[str, Any]]] = {}
    if model is not None:
        for question_set in sets:
            outcomes[question_set.name] = await jev_repo.ask_outcomes(
                conn,
                question_set=question_set,
                model=model,
                subject_type="finding_title",
                subject_ids=sorted(set(addresses.values())),
            )
    rows = []
    for finding in findings:
        address = addresses.get(finding["ref"])
        rows.append(
            {
                "ref": finding["ref"],
                "asks": {
                    question_set.name: ask_status(
                        finding["origin"],
                        finding["title"],
                        None
                        if model is None
                        else outcomes[question_set.name].get(address or ""),
                    )
                    for question_set in sets
                },
            }
        )
    return {
        "pin": model,
        "switches": switches,
        "holds": holds,
        "jev_findings_raised": await jev_repo.jev_findings_raised(conn),
        "open_findings": len(rows),
        "findings": rows,
    }


def format_suggestions(report: Mapping[str, Any]) -> str:
    """``suggestions`` as text: refs, statuses and counts, and nothing else."""
    lines = [
        "suggestions: how each ask came out, never what it answered; no answer, "
        "probability or chip is shown before phase E",
        f"pin: {said(report['pin'])}",
        "switches: "
        + "; ".join(
            f"{switch} {'on' if on else 'off'}"
            for switch, on in report["switches"].items()
        ),
        "holds: "
        + "; ".join(
            f"{hold.replace('_', ' ')}: {'yes' if on else 'no'}"
            for hold, on in report["holds"].items()
        ),
        f"findings Jev raised: {report['jev_findings_raised']} (counted, never named)",
        f"open findings, oldest first: {report['open_findings']}",
    ]
    for row in report["findings"]:
        asks = "; ".join(f"{name} {status}" for name, status in row["asks"].items())
        lines.append(f"{row['ref']}: {asks}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------

#: The three commands that write, each in its own transaction and through
#: ``jev_repo`` alone; every other command reads, in one read-only snapshot.
WRITING_COMMANDS = ("labels import", "labels copy", "evaluate --record")

#: Every command the harness runs, as :func:`_command` names it: the ones
#: that read and the three that write. Anything else is refused before any
#: connection, so arguments ``_parser`` would never make run nothing, an
#: evaluation least of all (D1's review, D1RP-1).
#: ``tests/unit/test_jev_eval.py::TestLooks`` holds it to what the parser makes.
COMMANDS = (
    "status",
    "forward",
    "forward-audit",
    "report",
    "labels export",
    "evaluate",
    "preview",
    "suggestions",
    *WRITING_COMMANDS,
)

#: The two commands that evaluate: a dry run, and a look recorded.
EVALUATE_COMMANDS = ("evaluate", "evaluate --record")


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("a sample is at least one subject")
    return number


def _operator(value: str) -> str:
    if not OPERATOR.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "a person labels as operator:NAME, the name in lower-case letters, "
            "digits, '.', '_' and '-'"
        )
    return value


def _version(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("a version is a count")
    return number


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.programme.jev_eval",
        description=(
            "The Jev evaluation harness. Reads the ledger and asks nothing; "
            "labels import, labels copy and evaluate --record write labels and "
            "evaluations, and nothing else."
        ),
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

    evaluate_ = commands.add_parser(
        "evaluate", help="one question against one labeller; a dry run unless --record"
    )
    evaluate_.add_argument("--set", dest="question_set", required=True)
    evaluate_.add_argument("--key", required=True)
    evaluate_.add_argument(
        "--labelled-by", "--labeller", dest="labelled_by", required=True
    )
    evaluate_.add_argument(
        "--split",
        choices=EVALUATE_SPLITS,
        required=True,
        help=(
            "required, with no default: dev, the search's own items, never "
            "recorded; or test or all, a look at the held-out items, taken only "
            "with --record"
        ),
    )
    evaluate_.add_argument("--model", help="a pinned model; the pin by default")
    evaluate_.add_argument("--record", action="store_true")
    evaluate_.add_argument("--commit", help="the commit --record records under")
    evaluate_.add_argument("--json", action="store_true")

    labels = commands.add_parser("labels", help="export, import or copy labels")
    label_commands = labels.add_subparsers(dest="labels_command", required=True)
    export = label_commands.add_parser(
        "export", help="the subjects to label, with their text and no answer"
    )
    export.add_argument("--set", dest="question_set", required=True)
    export.add_argument("--key", required=True)
    export.add_argument(
        "--blind",
        action="store_true",
        required=True,
        help="required: no export shows an answer",
    )
    export.add_argument("--sample", type=_positive)
    export.add_argument(
        "--include-quarantined",
        action="store_true",
        help=(
            "also the web text the code screen flags, which no set is asked "
            "about; what Jev's screen or a vendor's block quarantined is "
            "always exported, since leaving it out would choose the subjects "
            "by what was answered"
        ),
    )
    imported = label_commands.add_parser("import", help="record a file of labels")
    imported.add_argument("--file", type=Path, required=True)
    who = imported.add_mutually_exclusive_group(required=True)
    who.add_argument("--as", dest="operator", type=_operator)
    who.add_argument("--source", dest="dataset")
    copied = label_commands.add_parser(
        "copy", help="carry a version's labels to the registered version"
    )
    copied.add_argument("--set", dest="question_set", required=True)
    copied.add_argument("--key", required=True)
    copied.add_argument("--from-version", type=_version, required=True)
    copied.add_argument("--to-version", type=_version, required=True)

    report = commands.add_parser(
        "report", help="the newest evaluation of each question, model and labeller"
    )
    report.add_argument("--json", action="store_true")

    preview = commands.add_parser(
        "preview", help="what a title set would be asked about, and send"
    )
    preview.add_argument("--set", dest="question_set", required=True)
    preview.add_argument("--limit", type=_positive, default=PREVIEW_LIMIT)
    preview.add_argument("--json", action="store_true")
    suggestions = commands.add_parser(
        "suggestions",
        help="how each findings set's ask came out: statuses, never an answer",
    )
    suggestions.add_argument("--json", action="store_true")
    return parser


def _command(arguments: argparse.Namespace) -> str:
    """
    The command ``arguments`` name, as the harness runs it: one of
    :data:`COMMANDS`, or :class:`Refused`. Read before any connection, by
    :func:`look_problem` and by ``_run``, and nothing dispatches on anything
    else: a command of ``None``, mis-cased or padded, or ``labels`` with a
    subcommand it has none of, once fell through ``_read`` to the evaluation
    and printed a held-out one with no look recorded (D1's review, D1RP-1).
    """
    command = getattr(arguments, "command", None)
    if command == "labels":
        name = f"labels {getattr(arguments, 'labels_command', None)}"
    elif command == "evaluate":
        record = getattr(arguments, "record", False)
        name = "evaluate --record" if record else "evaluate"
    else:
        name = str(command)
    # The parser's own name for it heads the name the harness runs it by, so
    # neither of the derived names is taken as a command on its own.
    if name not in COMMANDS or name.partition(" ")[0] != command:
        raise Refused(f"the harness runs no command {name!r}; nothing was read")
    return name


def _dumped(value: Any) -> str:
    return json.dumps(value, default=str, indent=2, sort_keys=True)


async def _read(
    conn: asyncpg.Connection, arguments: argparse.Namespace, command: str
) -> str:
    """
    A command that reads, inside the caller's read-only snapshot, named by
    :func:`_command`. Each command has its branch, and anything else is
    refused: no command reaches the evaluation by default.
    """
    now = await jev_clock.database_now(conn)
    report: Any
    if command == "status":
        report = await status_report(conn)
        text = format_status(report)
    elif command == "forward":
        report = await forward_report(conn, since=arguments.since, now=now)
        text = format_forward(report)
    elif command == "forward-audit":
        report = await forward_audit(conn, since=arguments.since, now=now)
        text = format_audit(report)
    elif command == "report":
        report = await evaluations_report(conn)
        text = format_report(report)
    elif command == "labels export":
        return await export_labels(
            conn,
            question_set=_registered(arguments.question_set),
            question_key=arguments.key,
            sample=arguments.sample,
            include_quarantined=arguments.include_quarantined,
        )
    elif command == "evaluate":
        evaluation = await _evaluate(conn, arguments)
        report = evaluation.row()
        text = format_evaluation(report)
    elif command == "preview":
        report = await preview_report(
            conn,
            question_set=_registered(arguments.question_set),
            limit=arguments.limit,
            day=now.astimezone(UTC).date(),
        )
        text = format_preview(report)
    elif command == "suggestions":
        report = await suggestions_report(conn)
        text = format_suggestions(report)
    else:
        raise Refused(f"no reading command {command!r}; nothing was read")
    return _dumped(report) if getattr(arguments, "json", False) else text


async def _evaluate(
    conn: asyncpg.Connection, arguments: argparse.Namespace
) -> Evaluation:
    model = arguments.model or await flags.jev_model(conn)
    if model is None:
        raise Refused("no usable pin is set; name the model with --model")
    return await evaluate(
        conn,
        question_set=_registered(arguments.question_set),
        question_key=arguments.key,
        labelled_by=arguments.labelled_by,
        model=model,
        split=arguments.split,
    )


async def _write(
    conn: asyncpg.Connection,
    arguments: argparse.Namespace,
    command: str,
    *,
    commit: str | None,
    rows: Sequence[Mapping[str, str]] | None,
    labelled_by: str | None,
) -> str:
    """One of the three commands that write, inside the caller's transaction."""
    if command == "labels import":
        assert rows is not None and labelled_by is not None
        done = await import_labels(conn, rows=rows, labelled_by=labelled_by)
        return (
            f"labels of {done['labelled_by']}: {done['recorded']} recorded, "
            f"{done['already']} recorded before"
        )
    if command == "labels copy":
        done = await copy_labels(
            conn,
            question_set=_registered(arguments.question_set),
            question_key=arguments.key,
            from_version=arguments.from_version,
            to_version=arguments.to_version,
        )
        return (
            f"{done['copied']} labels copied to v{arguments.to_version}; "
            f"{done['already_labelled']} items labelled there already kept theirs"
        )
    if command != "evaluate --record":
        raise Refused(f"no writing command {command!r}; nothing was written")
    evaluation = dataclasses.replace(
        await _evaluate(conn, arguments), code_commit=commit
    )
    recorded = await jev_repo.record_evaluation(conn, **evaluation.row())
    if arguments.json:
        return _dumped({**evaluation.row(), "recorded_as": recorded})
    return f"{format_evaluation(evaluation.row())}\nrecorded as evaluation {recorded}"


async def _run(arguments: argparse.Namespace, dsn: str) -> str:
    command = _command(arguments)
    commit = rows = labelled_by = None
    # Everything that can be refused without the ledger is refused first.
    if command == "evaluate --record":
        commit = resolve_commit(arguments.commit, os.environ, _git)
    if command == "labels import":
        try:
            data = arguments.file.read_bytes()
        except OSError as error:
            raise Refused(
                f"the labels file cannot be read ({error.strerror})"
            ) from None
        rows = parse_labels(data)
        labelled_by = arguments.operator or source_labeller(arguments.dataset, data)
    conn = await asyncpg.connect(dsn)
    try:
        if command in WRITING_COMMANDS:
            # One transaction: what is checked is what is written beside it.
            async with conn.transaction(isolation="repeatable_read"):
                return await _write(
                    conn,
                    arguments,
                    command,
                    commit=commit,
                    rows=rows,
                    labelled_by=labelled_by,
                )
        # Read-only, and one snapshot for every figure a report prints.
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            return await _read(conn, arguments, command)
    finally:
        await conn.close()


def look_problem(arguments: argparse.Namespace) -> str | None:
    """
    Why ``arguments`` would take a look at the held-out items that nothing
    counts, or record what is not a look, or ``None`` (plan version 2, M3).

    ``evaluate --split test`` and ``--split all`` read the test split, so
    each is a look, and ``jev_calibration.usable`` counts recorded looks
    alone: one taken as a dry run would be a look the gate's level was never
    spent on, and labelling until a dry run passed, then recording that one,
    is optional stopping. So each needs ``--record``. ``--split dev`` scores
    the search's own items and reads no label of a test item, so it is never
    recorded: it is no look, and a row of it would be one ``usable`` could
    not read as one.

    It decides from the command :func:`_command` names, which raises
    :class:`Refused` for anything but a command the harness runs, and gives a
    problem for a split that is not one of :data:`EVALUATE_SPLITS`, so
    arguments no parser made fail closed rather than past the rule (D1's
    review, D1RP-1).
    """
    command = _command(arguments)
    if command not in EVALUATE_COMMANDS:
        return None
    split = getattr(arguments, "split", None)
    record = command == "evaluate --record"
    if split not in EVALUATE_SPLITS:
        return (
            f"--split takes {', '.join(EVALUATE_SPLITS)}, not {split!r}, and has "
            "no default; nothing was read"
        )
    if split in jev_prereg.LOOKED_AT_SPLITS and not record:
        return (
            f"--split {split} reads the held-out test items, a look the gate's "
            f"level is spent on, and each of the {jev_prereg.MAX_LOOKS} looks a "
            "set, version and question has is recorded: add --record to take "
            "it, or read the development split with --split dev, which spends "
            "none; nothing was read"
        )
    if split == DEV_SPLIT and record:
        return (
            "--split dev is the development split's search, which reads no label "
            "of a test item and is never recorded; record a look with --split "
            "test or --split all; nothing was read"
        )
    return None


async def execute(arguments: argparse.Namespace, dsn: str) -> int:
    """
    Run one parsed command against ``dsn`` and print what it found: 0 when
    it ran, 1 when the harness refused it, with why, on standard error.

    Every command the harness runs comes through here, ``main`` included, so
    the rule on looks is held here (:func:`look_problem`), before any
    connection is made, and fails closed: arguments naming a command or a
    split the harness does not run are refused the same way, never read as
    an evaluation. ``tests/unit/test_jev_eval.py::TestLooks``, and on
    PostgreSQL ``tests/integration/test_jev_evaluations.py::
    TestTheCommandsOnPostgres``.
    """
    try:
        problem = look_problem(arguments)
        if problem is not None:
            raise Refused(problem)
        output = await _run(arguments, dsn)
    except Refused as refused:
        print(str(refused), file=sys.stderr)
        return EXIT_REFUSED
    print(output)
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """
    Run one command and print what it found. 0 when it ran, 1 when it was
    refused — no ``DATABASE_URL``, or the command's own refusal — and 2 on a
    usage error.
    """
    parser = _parser()
    try:
        arguments = parser.parse_args(argv)
    except SystemExit as exit_:
        return EXIT_USAGE if exit_.code else EXIT_OK
    if getattr(arguments, "commit", None) is not None and not arguments.record:
        print(
            "--commit names the commit --record records under, and nothing is "
            "recorded without --record",
            file=sys.stderr,
        )
        return EXIT_USAGE
    dsn = normalise_dsn(os.environ.get("DATABASE_URL", "").strip())
    if not dsn:
        print("DATABASE_URL is not set; the harness reads the ledger", file=sys.stderr)
        return EXIT_REFUSED
    return asyncio.run(execute(arguments, dsn))


if __name__ == "__main__":
    raise SystemExit(main())
