"""
jev_calibration.py
------------------
When a recorded evaluation of Jev could arm a threshold, and what an armed
threshold would be allowed to do. Pure: the standard library, ``jev_prereg``,
the analysis plan, and ``jev_stats``, the statistics the plan's gates are
computed by, and nothing else
(``tests/unit/test_import_boundaries.py::test_the_pure_modules_load_nothing``).

Consumed by nothing that acts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Phase C9 writes this and arms nothing with it. Every lane stays
suggestion-only and "not calibrated" until phase D decides how a usable
evaluation is armed, so the planner, the jobs, the lane, the tick and the
ingest may not load this module at all
(``test_import_boundaries.py::test_nothing_that_acts_loads_the_calibration``).
The harness may, to report whether each evaluation it shows would be usable
and why not.

Friction, never less
~~~~~~~~~~~~~~~~~~~~
In the research and guardrail lanes Jev may add friction and never remove it
(docs/08, "What this is"). The two verdicts below are written so that no
calibration can turn that round:

* :func:`card_verdict` rejects whatever the code's own check rejects, armed or
  not, and an armed threshold can only add a rejection: a valid ``true`` that
  leads by at least the threshold. ``None`` for the calibration is the code's
  verdict, exactly.
* :func:`document_path` takes no calibration at all. Phase C already
  quarantines a web text on the injection screen's valid ``true`` argmax, so a
  threshold could only ever release such a text, which is friction removed.
  A code-screen flag is a quarantine whatever Jev answered, and a text is
  described only on a valid ``false`` with no code flag.

``tests/unit/test_jev_calibration.py`` holds both exhaustively.

What usable means
~~~~~~~~~~~~~~~~~
Design C9's list, every condition required and each enough alone to refuse
(:func:`usable`, one test per reason): the evaluation is the registered set's
current version, a key it plans, and the pinned model; computed under the
analysis plans in force; on the held-out test split with at least
``MIN_TEST_ITEMS``; on items the model cannot have been trained on; with a
threshold chosen and a coverage measured at it; beating both baselines —
accuracy's lower bound above each, over the valid answers and over every
item, and each paired difference's lower bound above 0 at the gate level;
with the uniform and the near-threshold flip rates measured on enough pairs
and below their limits; on a test set no earlier version's evaluation used;
and the newest evaluation of its key.

And one condition design C9's list left out: **the held-out test split bears
the threshold out** (``held_out``). The threshold is the smallest of fifty
margins whose statistic cleared its target on the development split, and the
best of a search flatters by construction (CLAUDE.md, honesty rules), so its
development bound is optimistic; the test split is the one measurement of it
that was not searched. So the statistic measured there — covered accuracy,
or the acting class's covered precision — must meet the plan's target by the
same rule the search applied: on at least ``MIN_COVERED`` test items, by its
one-sided Wilson lower bound at ``GATE_CI``. Without it a threshold the test
split refuted outright, every answer leading by it wrong, read as usable
(``tests/unit/test_jev_eval.py::TestAThresholdTheTestSplitRefutes``).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from src.programme import jev_prereg, jev_stats

if TYPE_CHECKING:
    from src.programme.jev_validate import ValidatedAnswer

#: A Noul's two answers. The guardrails' acting class is ``true``
#: (``jev_prereg.SET_TARGETS``); the injection screen's clearance is
#: ``false`` (``jev_questions.SCREEN_CLEAR_ARGMAX``, which this module may not
#: load, being pure: ``tests/unit/test_jev_calibration.py`` holds the two
#: equal).
TRUE = "true"
FALSE = "false"

#: Why an evaluation may not arm a threshold, one sentence each, keyed by a
#: name the tests and the report read.
REASONS: Mapping[str, str] = {
    "set": "not the registered set's version, or a question its plan does not plan",
    "model": "not the pinned model",
    "plan": "computed under analysis plans other than those in force",
    "split": "not on the held-out test split",
    "size": f"fewer than {jev_prereg.MIN_TEST_ITEMS} test items",
    "training": "its items may be in the model's training data (an upper bound)",
    "threshold": "no threshold chosen, or no coverage measured at it",
    "held_out": (
        "the held-out test split does not bear its threshold out: fewer than "
        f"{jev_prereg.MIN_COVERED} test items measured at it, or their "
        "statistic's one-sided Wilson lower bound at the gate level below its "
        "target"
    ),
    "majority": "does not beat the majority baseline",
    "keyword": "does not beat the keyword baseline",
    "uniform_flips": (
        f"its uniform flip rate is not measured on {jev_prereg.MIN_FLIP_PAIRS} "
        f"pairs at or below {jev_prereg.MAX_FLIP_RATE}"
    ),
    "near_threshold_flips": (
        "its near-threshold flip rate is not measured on "
        f"{jev_prereg.MIN_FLIP_PAIRS} pairs at or below "
        f"{jev_prereg.MAX_FLIP_RATE_NEAR_THRESHOLD}"
    ),
    "reused_test_set": "its test set was used by an earlier version's evaluation",
    "superseded": "not the newest evaluation of its key",
}


def analysis_plan_hash(name: str, version: int) -> str | None:
    """
    The identity of the analysis an evaluation of ``name`` at ``version`` is
    computed under: sha256 of ``jev_prereg.plans_in_force`` — the global
    plan's version and hash and the set plan's — as compact JSON with its keys
    sorted. ``None`` for a set with no plan, which nothing evaluates. A
    change to either plan is a new identity, so an evaluation computed under
    one plan never passes for one computed under another.
    """
    plans = jev_prereg.plans_in_force(name, version)
    if plans is None:
        return None
    text = json.dumps(plans, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def usable(
    evaluation: Mapping[str, Any],
    *,
    earlier: Sequence[Mapping[str, Any]],
    pin: str,
    plan_hash: str,
) -> tuple[bool, float | None, list[str]]:
    """
    Whether ``evaluation``, a recorded ``jev_evaluations`` row, could arm a
    threshold: ``(True, threshold, [])``, or ``(False, None, reasons)`` with
    every reason that holds, by its key in :data:`REASONS`.

    ``earlier`` is every other evaluation on record for the set, at any
    version: the newer rows of its own key make it superseded, and an earlier
    version's row on the same test set makes that set used. ``pin`` is the
    pinned model and ``plan_hash`` the :func:`analysis_plan_hash` of the set
    at its registered version, both the caller's to read; ``None`` for
    either reads as no pin and no plan, which nothing matches.

    A threshold the development split chose is usable only where the test
    split bears it out (``held_out``, see the module docstring):
    ``tests/unit/test_jev_calibration.py::TestUsable`` and
    ``tests/unit/test_jev_eval.py::TestAThresholdTheTestSplitRefutes``.
    """
    reasons: list[str] = []
    name = evaluation.get("question_set")
    version = evaluation.get("question_set_version")
    key = evaluation.get("question_key")
    plan = jev_prereg.set_plan(name, version) if isinstance(name, str) else None
    planned = None if plan is None else plan["questions"].get(key)
    if planned is None:
        reasons.append("set")
    if evaluation.get("model") != pin or not pin:
        reasons.append("model")
    if evaluation.get("analysis_plan_hash") != plan_hash or not plan_hash:
        reasons.append("plan")
    if evaluation.get("split") != "test":
        reasons.append("split")
    if not _at_least(evaluation.get("n"), jev_prereg.MIN_TEST_ITEMS):
        reasons.append("size")
    if evaluation.get("possibly_in_training") is not False:
        reasons.append("training")
    threshold = evaluation.get("threshold")
    if (
        evaluation.get("threshold_outcome") != "chosen"
        or threshold is None
        or evaluation.get("coverage_at_threshold") is None
    ):
        reasons.append("threshold")
    if not _held_out(evaluation, None if planned is None else planned["at_least"]):
        reasons.append("held_out")
    for baseline in ("majority", "keyword"):
        if not _beats(evaluation, baseline):
            reasons.append(baseline)
    if not _flips_within(
        evaluation, "flip_rate", "flip_rate_n", jev_prereg.MAX_FLIP_RATE
    ):
        reasons.append("uniform_flips")
    if not _flips_within(
        evaluation,
        "flip_rate_near_threshold",
        "flip_rate_near_threshold_n",
        jev_prereg.MAX_FLIP_RATE_NEAR_THRESHOLD,
    ):
        reasons.append("near_threshold_flips")
    if _test_set_reused(evaluation, earlier):
        reasons.append("reused_test_set")
    if _superseded(evaluation, earlier):
        reasons.append("superseded")
    if reasons:
        return False, None, reasons
    return True, float(threshold), []


def _at_least(value: object, floor: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= floor


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _held_out(evaluation: Mapping[str, Any], planned_target: object) -> bool:
    """
    Whether the test split bears the threshold out: some test item covered,
    at least ``MIN_COVERED`` measured at the threshold, and their statistic's
    one-sided Wilson lower bound at ``GATE_CI`` at least the target — the
    plan's, or the row's where it is higher, never the row's where it is
    lower. The rule the development split's search applied
    (``jev_stats.choose_threshold``), applied to the items it never saw.

    The count right is read back from the stored share, which is exactly
    ``right / n_at_threshold``; a share no count of the items could give is
    not a measurement.
    """
    tested = evaluation.get("n_at_threshold")
    share = _number(evaluation.get("accuracy_at_threshold"))
    coverage = _number(evaluation.get("coverage_at_threshold"))
    targets = [
        t
        for t in (_number(planned_target), _number(evaluation.get("threshold_target")))
        if t is not None
    ]
    if (
        not _at_least(tested, jev_prereg.MIN_COVERED)
        or share is None
        or coverage is None
        or not coverage > 0
        or not targets
    ):
        return False
    right = round(share * tested)
    if not 0 <= right <= tested:
        return False
    bound = jev_stats.wilson(right, tested, jev_prereg.GATE_CI, one_sided=True)
    return bound is not None and bound[0] >= max(targets)


def _beats(evaluation: Mapping[str, Any], baseline: str) -> bool:
    """
    The baseline measured; accuracy's lower bound above it, over the valid
    answers as the design names it and over every item as design 10.1
    compares it, since the baseline answers every item; and the paired
    difference's lower bound, a one-sided bound at the gate level, above 0.
    """
    measured = _number(evaluation.get(f"{baseline}_baseline_accuracy"))
    if measured is None:
        return False
    for low in ("accuracy_wilson_low", "accuracy_all_items_wilson_low"):
        bound = _number(evaluation.get(low))
        if bound is None or not bound > measured:
            return False
    difference = _number(evaluation.get(f"vs_{baseline}_diff_low"))
    return difference is not None and difference > 0


def _flips_within(
    evaluation: Mapping[str, Any], rate: str, pairs: str, limit: float
) -> bool:
    measured = _number(evaluation.get(rate))
    return (
        measured is not None
        and _at_least(evaluation.get(pairs), jev_prereg.MIN_FLIP_PAIRS)
        and measured <= limit
    )


def _test_set_reused(
    evaluation: Mapping[str, Any], earlier: Sequence[Mapping[str, Any]]
) -> bool:
    """
    Whether an evaluation of an earlier version of the set used this test
    set: its dataset, or the development set its threshold was chosen on, is
    this one's, by hash. Rewording a question after seeing how it scored and
    scoring the new words on the same items measures the rewording, not the
    question. Hashes name whole sets, so a test set sharing only some items
    with an earlier one is not seen (docs/08 open item 60).
    """
    dataset = evaluation.get("dataset_sha256")
    version = evaluation.get("question_set_version")
    if not isinstance(version, int) or not dataset:
        return True
    for row in earlier:
        if row.get("question_set") != evaluation.get("question_set"):
            continue
        before = row.get("question_set_version")
        if not isinstance(before, int) or before >= version:
            continue
        if dataset in (row.get("dataset_sha256"), row.get("threshold_dataset_sha256")):
            return True
    return False


def _superseded(
    evaluation: Mapping[str, Any], earlier: Sequence[Mapping[str, Any]]
) -> bool:
    """Whether another row of the same set, version, key and model is newer."""
    key = _identity(evaluation)
    order = _order(evaluation)
    if order is None:
        return True
    for row in earlier:
        if _identity(row) != key or row.get("id") == evaluation.get("id"):
            continue
        theirs = _order(row)
        if theirs is None or theirs > order:
            return True
    return False


def _identity(row: Mapping[str, Any]) -> tuple[object, ...]:
    return (
        row.get("question_set"),
        row.get("question_set_version"),
        row.get("question_key"),
        row.get("model"),
    )


def _order(row: Mapping[str, Any]) -> tuple[datetime, int] | None:
    created, row_id = row.get("created_at"), row.get("id")
    if not isinstance(created, datetime) or not isinstance(row_id, int):
        return None
    return created, row_id


# ---------------------------------------------------------------------------
# What an armed threshold would be allowed to do
# ---------------------------------------------------------------------------


def card_verdict(
    code: Literal["accept", "reject"],
    answer: ValidatedAnswer | None,
    calibration: tuple[float] | None,
) -> Literal["accept", "reject"]:
    """
    The card check's verdict on a hypothesis title: ``reject`` when the code's
    own check rejects it (``claims.find_performance_claim``), whatever Jev
    said, and, only once armed with a usable ``calibration`` — the threshold
    :func:`usable` returned, as a one-tuple — when ``guardrail.card`` answered
    validly that the title states a performance figure (``true``) by a margin
    of at least it. Unarmed, the code's verdict, exactly. Never accepts what
    the code rejected, and an armed verdict is never an acceptance where the
    unarmed one rejects.
    """
    if code not in ("accept", "reject"):
        raise ValueError(f"the code's verdict is accept or reject, got {code!r}")
    if code == "reject":
        return "reject"
    if calibration is None:
        return code
    (threshold,) = calibration
    if (
        answer is not None
        and answer.valid
        and answer.argmax == TRUE
        and answer.margin is not None
        and answer.margin >= threshold
    ):
        return "reject"
    return "accept"


def document_path(
    code_flag: bool, answer: ValidatedAnswer | None
) -> Literal["quarantine", "hold", "describe"]:
    """
    What becomes of a stored web text, from the code screen's flag and the
    injection screen's answer: ``quarantine`` on a code flag, whatever Jev
    answered, or on a valid ``true``; ``describe`` on a valid ``false`` with
    no code flag; ``hold`` on anything else — no answer, an invalid one, a
    tie. It takes no calibration (see the module docstring).
    """
    if not isinstance(code_flag, bool):
        raise TypeError(f"the code screen's flag is a boolean, got {code_flag!r}")
    if code_flag:
        return "quarantine"
    if answer is None or not answer.valid:
        return "hold"
    if answer.argmax == TRUE:
        return "quarantine"
    if answer.argmax == FALSE:
        return "describe"
    return "hold"


__all__ = [
    "FALSE",
    "REASONS",
    "TRUE",
    "analysis_plan_hash",
    "card_verdict",
    "document_path",
    "usable",
]
