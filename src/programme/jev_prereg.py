"""
jev_prereg.py
-------------
The analysis the Jev answers will be put through, registered before the
answers exist. Pure data and pure functions: the standard library alone, so the
API, the planner and the harness can all read it, and none of them can move it.

Why it is registered now
~~~~~~~~~~~~~~~~~~~~~~~~
An analysis chosen after the data is a search, and a search finds something:
the split that flatters, the threshold that clears, the baseline Jev happens to
beat. So every choice the harness and the forward report will make — how items
are split into development and test, how large each must be, which confidence
levels are reported and which gate, how many looks the gate's level is spent
over, how many flips are too many, which requests are re-asked, and the rule
Jev's regime is compared with — is data here, hashed by :func:`plan_hash` and
:func:`regime_plan_hash` and pinned beside them by :data:`GOLDEN_PLAN_HASH`
and :data:`GOLDEN_REGIME_PLAN_HASH`. ``tests/unit/test_jev_prereg.py`` holds
each to an append-only history kept in the test, ``RELEASED_PLAN_HASHES`` and
``RELEASED_REGIME_PLAN_HASHES``, as the question sets' words are held. Editing
a number here fails the build, and so does re-recording the golden to match,
which is the edit a failing hash test invites: a released plan is history,
and a change is a new :data:`PLAN_VERSION` (or :data:`REGIME_PLAN_VERSION`)
with its hash appended, not a corrected old plan.

Version 2, released while the ledger held no answer (phase D1)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Version 1 was phase C4's. Version 2 is phase D's first pull request, released
before any Jev area was first switched on, so it set aside nothing: an answer
is scored only under the plans in force when it was recorded
(``jev_eval.build_evaluation``), and none was recorded under version 1. It
changes, as docs/09 section 3.2 registers:

* **R1, floors by statistic** (:data:`STATISTIC_FLOORS`), where version 1 held
  a target per lane: covered accuracy at least 0.80, and covered precision of
  the acting class at least 0.90, each met by its one-sided Wilson lower bound
  at :data:`GATE_CI`. A question with an acting class is measured by that
  class's covered precision, any other by its covered accuracy, and a set
  plan may raise a floor, never lower it. So any lane — findings and ops
  among them — arrives through a set plan alone, and no floor lives in a test,
  outside the hash.
* **R2, a family of 20** (:data:`GATE_FAMILY`), where version 1's 10 was
  nearly full.
* **M1, a 50/50 split** (:data:`DEV_SPLIT_TENTHS`), where version 1's was
  30/70.
* **M2, flips over the population** (:data:`FLIP_PAIRS`): every canonical
  request of the question under the pin, labelled or not, where version 1
  counted only those that answered a scored item.
* **M3, looks counted** (:data:`MAX_LOOKS`): at most four looks at the
  held-out items of one set, version and question, under any model, the
  identity the family counts (:data:`LOOKS_COUNTED_BY`), so a new pin
  restores none. :data:`GATE_CI` is spent across the family and the looks,
  1 − 0.05 / (20 × 4).
* **M4, the regime's plan apart** (:func:`regime_plan`), so that a review of
  the regime's rule sets aside regime agreement alone.
* **M5, re-asks not compared count against the flip limits**
  (:data:`FLIPS_NOT_COMPARED`), in the worst case.

The regime's baseline, and the sleeves: the agent's defaults, in a plan apart
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
:data:`REGIME_BASELINE_RULE` is the code rule phase G's baseline twin will run
beside a Jev-driven allocator, and the forward report compares Jev's recorded
regimes with it now. It reads the equities sleeve only, on purpose: every other
condition would be a free choice, and each free choice is a place to fit the
rule to the answers. :data:`REGIME_SLEEVES` — SPY for equities, IEF for bonds,
GSG for commodities, as ``src/data/reference.py`` holds them for the worker —
says which instruments a regime series describes. **Both are the defaults the
agent that built phase C4 chose, not choices the operator has reviewed.**

From plan version 2 the two are a plan of their own, the regime plan
(:func:`regime_plan`, versioned by :data:`REGIME_PLAN_VERSION`), and the
global plan holds neither: inside the global plan, the operator's review of
the rule would have been a new global plan, setting aside every lane's
answers to change the regime's.

How either changes:

* **Before the first regime answer exists** — the decisions area is seeded off,
  so nothing is asked until an operator switches it on — a change is a new
  :data:`REGIME_PLAN_VERSION` with its hash appended to the released list, and
  costs nothing: no answer was analysed under the old plan. A changed sleeve
  also means changing ``src/data/reference.py`` and the test that holds the
  two equal, and starts a new signal series, since a signal's ``symbol``
  names the instruments (``jev_clock.sleeve_symbol``).
* **After it** — the same bump, which sets aside regime agreement alone: the
  regime job writes the regime plan in force into its result as it asks
  (``jev_forward``), so the forward report scores agreement only over the
  answers first recorded under the regime plan it runs and counts the rest
  apart by the regime plan they were recorded under (``jev_eval``); no
  answer is scored by a rule registered after it, and the old rule is never
  rewritten to match. A flip pair still counts under the global plan its
  re-ask's payload names.

What the plans hold, and what they do not
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The global plan: the split, the size floors, the margin grid a threshold is
searched on, the statistics' floors, the confidence levels and the looks they
are spent over, the bootstrap, the calibration bins, the flip limits and how
their pairs are counted, the re-ask sample and the "too few to say" floor. The
regime plan: the sleeves and the baseline rule. Nothing here is consumed by
anything that acts.

The set plans (phases C7, C8 and D2)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Each question set the research, guardrail and findings lanes ask has a plan of
its own (:func:`set_plan`), registered with the set and golden-hashed beside it
(:data:`GOLDEN_SET_PLAN_HASHES`), with an append-only released history in the
test, as the global plan has: per question, the class whose answer acts, the
target its statistic must meet — its statistic's floor raised, never lowered —
and the baseline Jev is measured against, in the plan's ``keyword_baseline``
slot whatever its rule: for phase C's sets a pure, deterministic function of
the text whose rules are data hashed into the plan; for phase D2's findings
sets the value already recorded beside the title, the raiser or the severity
(:data:`FINDINGS_RECORDED_BASELINE`), whose plans also name the population
they are asked about (:data:`FINDINGS_POPULATION`). ``decision.regime`` is the
regime plan's, and the connectivity probe measures the vendor, not a set, so
neither has one.

A plan is in force for the answers recorded under it, and for no others. So
every ``jev_ask`` job is planned with the set plan's version and hash, and the
global plan's, in its payload (:func:`plans_in_force`, written by ``jev_plan``),
and asks nothing under any others (``jev_jobs.run_ask``): every row it records,
on any attempt and however the job ends, was recorded under the plans its
payload names. Its row names the request its attempt recorded beside them too,
in the result of a job that succeeds and of one that fails after its ask wrote
a row — a response refused whole, an answer whose follow-up failed — as the
regime job writes the global plan into its result. The harness (C9) scores an
answer only under the plans in force when it was recorded. A baseline chosen
after the answers cannot be applied to them: a changed plan is a new
:data:`SET_PLAN_VERSIONS` entry, with its hash appended, and the answers
recorded under the old one stay scored under the old one.

A set plan names no global constant, so no set plan's hash moved with
version 2; what moved is the plans in force a job records, whose global half
is version 2's.
"""

from __future__ import annotations

import functools
import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import timedelta
from types import MappingProxyType
from typing import Any, Literal

#: Bumped whenever anything in the global plan changes; ``RELEASED_PLAN_HASHES``
#: in the test gains the new hash, and keeps every old one. Version 2 is phase
#: D1's (see the module docstring); version 1's hash stays released.
PLAN_VERSION = 2

#: What :func:`plan_hash` returns for :data:`PLAN_VERSION`. Not part of the plan
#: it pins, which could not hash itself.
GOLDEN_PLAN_HASH = "5d3a7fbbdb804440e70e077c75f9c997454786a84024d5ef58afabcab8365844"

# ---------------------------------------------------------------------------
# Items: the split and the sizes
# ---------------------------------------------------------------------------

#: An item is in the development split when the first eight hex digits of
#: ``sha256(f"{subject_type}:{subject_id}")``, read as an integer, are below
#: this many tenths of the way round ``% 10``: five in ten (M1). By content, so
#: an item's split never depends on when it was labelled or answered. The
#: test split is held to the same bar the development split's search applied
#: (``jev_calibration.usable``, ``held_out``), so the development share binds
#: as hard as the test share does: version 1's three in ten needed 40% more
#: labels wherever a covered count bound.
DEV_SPLIT_TENTHS = 5

#: The fewest test items an evaluation may gate on, development items a
#: threshold may be searched on, and items a threshold must still cover.
MIN_TEST_ITEMS = 200
MIN_DEV_ITEMS = 100
MIN_COVERED = 30

#: The thresholds searched: margins from 0.00 to 0.98 in steps of 0.02.
MARGIN_GRID: tuple[float, ...] = tuple(round(step * 0.02, 2) for step in range(50))

#: (R1) What a question's statistic must reach before a threshold is chosen
#: for it, by statistic: the Wilson lower bound of the statistic, one-sided at
#: :data:`GATE_CI`, never its point estimate, since 24 of the 30 covered items a
#: threshold needs is 0.80 with a lower bound far below it. A question with an
#: acting class — the answer that would act, a guardrail's ``true`` — is
#: measured by that class's covered precision, and any other by its covered
#: accuracy. A set's own plan may raise its statistic's floor, never lower it
#: (``tests/unit/test_jev_prereg.py::TestTheTargets``). Version 1 held a target
#: per lane, research and guardrail, so a findings or an ops set could arrive
#: only with a floor kept in a test, outside the hash.
STATISTIC_FLOORS: Mapping[str, Mapping[str, Any]] = MappingProxyType(
    {
        "covered_accuracy": MappingProxyType(
            {
                "measures": "a question with no acting class",
                "at_least": 0.80,
                "bound": "wilson_lower_at_gate_ci",
            }
        ),
        "covered_precision_of_the_acting_class": MappingProxyType(
            {
                "measures": "a question with an acting class",
                "at_least": 0.90,
                "bound": "wilson_lower_at_gate_ci",
            }
        ),
    }
)

# ---------------------------------------------------------------------------
# Uncertainty, and the looks it is spent over
# ---------------------------------------------------------------------------

#: Every reported interval: two-sided, 95%.
REPORT_CI = 0.95

#: (R2) The family a gate's level is Bonferroni over: up to this many gated
#: set-and-question pairs. A pair a set plan adds moves no hash of this plan,
#: so the count of the pairs the set plans gate is held to the family by a
#: test instead (``tests/unit/test_jev_prereg.py::TestTheGateFamily``); a
#: larger family is a new plan. Version 1's ten held nine pairs once phase D's
#: sets were planned, so a set's next version would have forced a new plan
#: just when it cost every lane's history.
GATE_FAMILY = 20

#: (M3) How many looks at the held-out items one set, version and question may
#: spend: evaluations recorded on the test split or on every item. A dry look
#: at them is refused (``jev_eval.execute``, which ``--split test`` and
#: ``--split all`` need ``--record`` to pass), and ``jev_calibration.usable``
#: refuses an evaluation with this many looks before it. Labelling until a dry
#: run passes and recording that one is optional stopping, which breaks the
#: error rate the gate's level claims.
MAX_LOOKS = 4

#: What a look is counted by: the set, its version and the question — the
#: identity a pair of the gate's family is — and never the model, so a look
#: under one pin is one of the same four under every other, and a new pin
#: restores no look the level never paid for.
LOOKS_COUNTED_BY: tuple[str, ...] = (
    "question_set",
    "question_set_version",
    "question_key",
)

#: The splits a look reads the held-out items of: the test split, and every
#: item, which holds it. The development split is the search's own, and a
#: look at it is no look.
LOOKED_AT_SPLITS: tuple[str, ...] = ("test", "all")

#: A gate's bound: one-sided, Bonferroni over the family and the looks,
#: 1 − (1 − :data:`REPORT_CI`) / (:data:`GATE_FAMILY` × :data:`MAX_LOOKS`) =
#: 1 − 0.05 / 80 = 0.999375. Written as a literal, and held to that formula by
#: ``tests/unit/test_jev_prereg.py::TestTheGateFamily``. At it, the exact
#: sign test needs eleven discordant items all one way, where version 1's
#: 0.995 needed eight.
GATE_CI = 0.999375

#: The bootstrap, and its seed: the first sixteen hex digits of the dataset's
#: sha256, read as an integer, so a figure recomputes from its dataset.
BOOTSTRAP_RESAMPLES = 2_000
BOOTSTRAP_SEED_RULE = "int(dataset_sha256[:16], 16)"

#: Calibration bins: deciles of the stated probability.
CALIBRATION_BINS = 10

#: A class with fewer labelled items than this prints "too few to say".
TOO_FEW_PER_CLASS = 10

# ---------------------------------------------------------------------------
# Consistency: flips, and the re-asks that measure them
# ---------------------------------------------------------------------------

#: The flip rates a usable evaluation may show, each on at least
#: :data:`MIN_FLIP_PAIRS` compared pairs; near a threshold means a canonical
#: margin within :data:`NEAR_THRESHOLD` of it.
MAX_FLIP_RATE = 0.05
MAX_FLIP_RATE_NEAR_THRESHOLD = 0.10
MIN_FLIP_PAIRS = 30
NEAR_THRESHOLD = 0.10

#: (M2) Which pairs a flip rate counts: every canonical request of the
#: question under the pin, labelled or not, each sampled under the plan in
#: force and counted in the stratum it was sampled in
#: (``jev_eval.build_evaluation``). A flip uses no label, and an armed
#: threshold acts on the population, so the population's flips are the ones
#: that matter. Version 1 counted a pair only when its canonical request
#: answered a scored item, so thirty uniform pairs needed about six hundred
#: labelled test items.
FLIP_PAIRS = "every_canonical_request_of_the_question_under_the_pin"

#: (M5) How a flip limit reads a re-ask that could not be compared — the
#: re-ask, or its canonical answer, not valid, failed or refused before it was
#: sent: as a flip, in the worst case. A rate is within its limit only if
#: (flipped + not compared) / (compared + not compared) is, on at least
#: :data:`MIN_FLIP_PAIRS` compared pairs (``jev_calibration.usable``). A
#: re-ask that ties or is refused whole is itself unstable, and the rule can
#: only refuse; version 1 read the compared pairs alone (docs/08 open item
#: 68).
FLIPS_NOT_COMPARED = "counted_as_flipped_in_the_worst_case"

#: The re-ask sample. A canonical request is in the uniform stratum when the
#: first eight hex digits of its request hash, as an integer, are divisible by
#: this: one in twenty, by content, whatever it answered.
REASK_UNIFORM_MODULUS = 20

#: Otherwise it is in the low-margin stratum when any of its valid answers
#: leads its runner-up by less than this. The two strata are reported apart
#: and never pooled: the uniform one is a sample of every request, the
#: low-margin one is a search for flips where they are likeliest.
REASK_LOW_MARGIN = 0.20

#: At most this many re-asks a UTC day, drawn from the previous day's canonical
#: requests, uniform first and then low-margin, each in request-hash order.
REASKS_PER_DAY = 10

#: A request is re-asked no sooner than this after its canonical answer.
REASK_AFTER = timedelta(hours=24)

ReaskStratum = Literal["uniform", "low_margin"]

# ---------------------------------------------------------------------------
# The regime plan: the baseline rule and the sleeves, frozen before the first
# answer, in a plan of their own (M4)
# ---------------------------------------------------------------------------

#: Bumped whenever the regime plan changes — the rule or the sleeves;
#: ``RELEASED_REGIME_PLAN_HASHES`` in the test gains the new hash, and keeps
#: every old one. A bump sets aside regime agreement alone: the global plan,
#: and every other lane's answers, are untouched by it.
REGIME_PLAN_VERSION = 1

#: What :func:`regime_plan_hash` returns for :data:`REGIME_PLAN_VERSION`.
GOLDEN_REGIME_PLAN_HASH = (
    "2833a4c00d1a6b0adab46c6d6bf0e3544deae6dc1a964598a088162fc1b6af74"
)

#: Which instrument stands for each sleeve. ``src/data/reference.py`` holds the
#: worker's copy, and ``tests/unit/test_jev_prereg.py`` holds the two equal.
#: The agent's default (see the module docstring).
REGIME_SLEEVES: Mapping[str, str] = MappingProxyType(
    {"equities": "SPY", "bonds": "IEF", "commodities": "GSG"}
)

#: The baseline twin's rule, in order; the first whose conditions all hold
#: wins. A condition maps a field of the dumped regime state, by its path, to
#: the labels it may hold; ``any_of`` holds when any one of its condition sets
#: does. ``neutral`` has none, so the rule is total, and it never answers the
#: escape: a rule does not abstain. Equities only, on purpose. The agent's
#: default (see the module docstring).
REGIME_BASELINE_RULE: tuple[tuple[str, Mapping[str, Any]], ...] = (
    (
        "risk_off",
        MappingProxyType(
            {
                "equities.trend": ("below",),
                "equities.momentum": ("down",),
                "any_of": (
                    MappingProxyType({"equities.drawdown": ("deep", "severe")}),
                    MappingProxyType({"equities.volatility_quintile": (5,)}),
                ),
            }
        ),
    ),
    (
        "risk_on",
        MappingProxyType(
            {
                "equities.trend": ("above",),
                "equities.momentum": ("up",),
                "equities.drawdown": ("none", "shallow"),
                "equities.volatility_quintile": (1, 2, 3),
            }
        ),
    ),
    ("neutral", MappingProxyType({})),
)

#: The special key of a condition set: holds when any of its sets holds.
ANY_OF = "any_of"


def regime_baseline(state: Mapping[str, Any]) -> str:
    """
    What :data:`REGIME_BASELINE_RULE` says about a regime state, as the lane
    dumps it: ``risk_off``, ``risk_on`` or ``neutral``, and never the escape.

    Reads labels and nothing else, by the paths the rule names; a path the
    state does not hold is :class:`KeyError`, a caller's defect, never a
    default.
    """
    for label, conditions in REGIME_BASELINE_RULE:
        if _holds(state, conditions):
            return label
    raise AssertionError("the rule's last line has no conditions, so it is total")


def _holds(state: Mapping[str, Any], conditions: Mapping[str, Any]) -> bool:
    for path, allowed in conditions.items():
        if path == ANY_OF:
            if not any(_holds(state, option) for option in allowed):
                return False
        elif _read(state, path) not in allowed:
            return False
    return True


def _read(state: Mapping[str, Any], path: str) -> Any:
    value: Any = state
    for part in path.split("."):
        value = value[part]
    return value


# ---------------------------------------------------------------------------
# Functions of the plan
# ---------------------------------------------------------------------------


def split_of(subject_type: str, subject_id: str) -> Literal["dev", "test"]:
    """Which split an item is in, by its content: see :data:`DEV_SPLIT_TENTHS`."""
    digest = hashlib.sha256(f"{subject_type}:{subject_id}".encode()).hexdigest()
    return "dev" if int(digest[:8], 16) % 10 < DEV_SPLIT_TENTHS else "test"


def reask_stratum(
    request_hash: str, valid_margins: Iterable[float]
) -> ReaskStratum | None:
    """
    The re-ask stratum a canonical request falls in, or ``None``: uniform by
    its hash first, low-margin by its valid answers' margins otherwise. Each
    request is in one stratum at most, so the two rates never share a pair.
    """
    if int(request_hash[:8], 16) % REASK_UNIFORM_MODULUS == 0:
        return "uniform"
    if any(margin < REASK_LOW_MARGIN for margin in valid_margins):
        return "low_margin"
    return None


def reask_sample(
    candidates: Iterable[Mapping[str, Any]], *, limit: int = REASKS_PER_DAY
) -> list[tuple[ReaskStratum, Mapping[str, Any]]]:
    """
    The requests to re-ask, and each one's stratum, from ``candidates``: each a
    mapping holding its ``request_hash`` and its ``valid_margins``. The uniform
    stratum first, then the low-margin one, each in request-hash order, and at
    most ``limit`` (never more than :data:`REASKS_PER_DAY`) in all.
    Deterministic, so a planner that runs every minute re-selects the same
    requests rather than drawing again.
    """
    if limit < 0:
        raise ValueError(f"limit is a count, got {limit}")
    uniform: list[Mapping[str, Any]] = []
    low: list[Mapping[str, Any]] = []
    for candidate in candidates:
        stratum = reask_stratum(candidate["request_hash"], candidate["valid_margins"])
        if stratum == "uniform":
            uniform.append(candidate)
        elif stratum == "low_margin":
            low.append(candidate)
    ordered: list[tuple[ReaskStratum, Mapping[str, Any]]] = [
        ("uniform", c) for c in sorted(uniform, key=lambda c: c["request_hash"])
    ] + [("low_margin", c) for c in sorted(low, key=lambda c: c["request_hash"])]
    return ordered[: min(limit, REASKS_PER_DAY)]


def global_plan() -> dict[str, Any]:
    """The whole global plan, as data: what :func:`plan_hash` hashes."""
    return _as_data(
        {
            "version": PLAN_VERSION,
            "split": {"dev_tenths": DEV_SPLIT_TENTHS, "by": "sha256(type:id)[:8] % 10"},
            "sizes": {
                "min_test_items": MIN_TEST_ITEMS,
                "min_dev_items": MIN_DEV_ITEMS,
                "min_covered": MIN_COVERED,
                "too_few_per_class": TOO_FEW_PER_CLASS,
            },
            "threshold": {"statistic": "margin", "grid": MARGIN_GRID},
            "statistic_floors": STATISTIC_FLOORS,
            "uncertainty": {
                "report_ci": REPORT_CI,
                "report_sides": 2,
                "gate_ci": GATE_CI,
                "gate_sides": 1,
                "gate_family": GATE_FAMILY,
                "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
                "bootstrap_seed": BOOTSTRAP_SEED_RULE,
                "calibration_bins": CALIBRATION_BINS,
            },
            "looks": {
                "max": MAX_LOOKS,
                "counted_by": LOOKS_COUNTED_BY,
                "splits": LOOKED_AT_SPLITS,
            },
            "flips": {
                "max_rate": MAX_FLIP_RATE,
                "max_rate_near_threshold": MAX_FLIP_RATE_NEAR_THRESHOLD,
                "min_pairs": MIN_FLIP_PAIRS,
                "near_threshold": NEAR_THRESHOLD,
                "pairs": FLIP_PAIRS,
                "not_compared": FLIPS_NOT_COMPARED,
            },
            "reasks": {
                "uniform_modulus": REASK_UNIFORM_MODULUS,
                "low_margin": REASK_LOW_MARGIN,
                "per_day": REASKS_PER_DAY,
                "after_hours": REASK_AFTER.total_seconds() / 3600,
                "order": ["uniform", "low_margin"],
            },
        }
    )


def plan_hash() -> str:
    """
    sha256 of :func:`global_plan` as compact JSON with its mappings' keys
    sorted: a mapping's order means nothing here, and a sequence's — the
    strata's order, the identity a look is counted by — is kept, since it is
    part of what the plan says.
    """
    return _sha256_of(global_plan())


def regime_plan() -> dict[str, Any]:
    """
    The regime plan, as data: what :func:`regime_plan_hash` hashes. The
    sleeves and the baseline rule, apart from the global plan since version 2
    (M4), so that changing either sets aside regime agreement alone.
    """
    return _as_data(
        {
            "version": REGIME_PLAN_VERSION,
            "sleeves": REGIME_SLEEVES,
            "baseline": REGIME_BASELINE_RULE,
        }
    )


def regime_plan_hash() -> str:
    """
    sha256 of :func:`regime_plan`, hashed as :func:`plan_hash` hashes the
    global plan: the rule's lines keep their order, since the first that holds
    wins.
    """
    return _sha256_of(regime_plan())


def _sha256_of(data: Any) -> str:
    """sha256 of ``data`` as compact JSON with its mappings' keys sorted."""
    text = json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _as_data(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _as_data(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str):
        return [_as_data(item) for item in value]
    return value


# ---------------------------------------------------------------------------
# The set plans (phases C7 and C8)
# ---------------------------------------------------------------------------

#: Each planned set's plan version, by the set's name and version. Bumped
#: whenever anything its plan holds changes; the test's released history gains
#: the new hash and keeps every old one. A set version with no entry has no
#: plan, and ``jev_jobs.run_ask`` asks nothing for it.
SET_PLAN_VERSIONS: Mapping[tuple[str, int], int] = MappingProxyType(
    {
        ("guardrail.injection", 1): 1,
        ("research.catalogue", 1): 1,
        ("research.hypothesis", 1): 1,
        ("guardrail.card", 1): 1,
        ("findings.owner", 1): 1,
        ("findings.severity", 1): 1,
        # Plan version 2 names the redactor's version 2 (D3's review); its
        # rules, and so its verdicts, are version 1's.
        ("ops.job_error", 1): 2,
    }
)

#: What :func:`set_plan_hash` returns for each planned set at its plan version
#: in :data:`SET_PLAN_VERSIONS`. Not part of the plans it pins.
GOLDEN_SET_PLAN_HASHES: Mapping[tuple[str, int], str] = MappingProxyType(
    {
        ("guardrail.injection", 1): (
            "2ba46f373fb98c836610d952cfa2d8737b53d8f30db6c2147d6c97bd14eff8f7"
        ),
        ("research.catalogue", 1): (
            "9ab204c87f7517215d9a63bac26cee7a853232d8dffba31c6f434ca0a5292deb"
        ),
        ("research.hypothesis", 1): (
            "1f7274a6d9d39de92d22806edf09d0da49c29804ca44ce64797873e36a07f050"
        ),
        ("guardrail.card", 1): (
            "a72753b5ea04d5af9392657928d777be19b9bbbbd9e013700f2e97e0d231956d"
        ),
        ("findings.owner", 1): (
            "e6cb5e05456468a9447b5748a3f09900a4893a5096cea6b0e98c445de05e09e9"
        ),
        ("findings.severity", 1): (
            "256b20e7cf141417af8bb71e4aeaca4b793d4ef1eedb947ec41db96bf30fcca2"
        ),
        ("ops.job_error", 1): (
            "0578dd14068847a7062f0f0a2f8f2f938a834efd1ac0c41092a9be7168ae5bba"
        ),
    }
)

#: Per question: the class whose answer would act, ``None`` where no answer
#: acts, and the target the statistic must meet before a threshold is chosen,
#: read as its statistic's floor is (:data:`STATISTIC_FLOORS`) — a Wilson
#: lower bound at the gate level — and never below it. A guardrail's answer
#: acts on its ``true`` (a text quarantined, a card refused), so its precision
#: is what is measured; a research answer is a suggestion, measured by its
#: accuracy.
SET_TARGETS: Mapping[tuple[str, str], Mapping[str, Any]] = MappingProxyType(
    {
        ("guardrail.injection", "addressed_to_ai"): MappingProxyType(
            {
                "acting_class": "true",
                "statistic": "covered_precision_of_the_acting_class",
                "at_least": 0.90,
                "bound": "wilson_lower_at_gate_ci",
            }
        ),
        ("research.catalogue", "asset_class"): MappingProxyType(
            {
                "acting_class": None,
                "statistic": "covered_accuracy",
                "at_least": 0.80,
                "bound": "wilson_lower_at_gate_ci",
            }
        ),
        ("research.catalogue", "mechanism"): MappingProxyType(
            {
                "acting_class": None,
                "statistic": "covered_accuracy",
                "at_least": 0.80,
                "bound": "wilson_lower_at_gate_ci",
            }
        ),
        ("research.hypothesis", "asset_class"): MappingProxyType(
            {
                "acting_class": None,
                "statistic": "covered_accuracy",
                "at_least": 0.80,
                "bound": "wilson_lower_at_gate_ci",
            }
        ),
        ("research.hypothesis", "mechanism"): MappingProxyType(
            {
                "acting_class": None,
                "statistic": "covered_accuracy",
                "at_least": 0.80,
                "bound": "wilson_lower_at_gate_ci",
            }
        ),
        ("guardrail.card", "performance_claim"): MappingProxyType(
            {
                "acting_class": "true",
                "statistic": "covered_precision_of_the_acting_class",
                "at_least": 0.90,
                "bound": "wilson_lower_at_gate_ci",
            }
        ),
        # Phase D2: a suggestion, which acts on nothing, measured by its
        # covered accuracy at the floor (docs/09, section 3.4).
        ("findings.owner", "owning_role"): MappingProxyType(
            {
                "acting_class": None,
                "statistic": "covered_accuracy",
                "at_least": 0.80,
                "bound": "wilson_lower_at_gate_ci",
            }
        ),
        ("findings.severity", "severity"): MappingProxyType(
            {
                "acting_class": None,
                "statistic": "covered_accuracy",
                "at_least": 0.80,
                "bound": "wilson_lower_at_gate_ci",
            }
        ),
        # Phase D3: a cause suggested beside code's, which acts on nothing,
        # measured as the findings sets are (docs/09, section 3.4).
        ("ops.job_error", "cause"): MappingProxyType(
            {
                "acting_class": None,
                "statistic": "covered_accuracy",
                "at_least": 0.80,
                "bound": "wilson_lower_at_gate_ci",
            }
        ),
    }
)

#: The injection screen's keyword baseline: the code screen, version 1, whose
#: rule data is named by its hash, so the plan pins the exact rules the screen
#: is measured against. It answers ``true`` when any rule fires on the excerpt.
#: A copy, since this module loads the standard library alone: the test holds
#: it to ``web_sources.CODE_SCREEN_VERSION``, ``code_screen_sha256()`` and
#: ``GOLDEN_CODE_SCREEN_SHA256``.
CODE_SCREEN_BASELINE: Mapping[str, Any] = MappingProxyType(
    {
        "rule": "web_sources.code_screen",
        "version": 1,
        "rules_sha256": (
            "95cc9a98bff72231934da34b8d475668af04ee84a966c86073850958e88e1984"
        ),
        "true_when": "a rule fires",
    }
)

#: The card check's keyword baseline: ``claims.find_performance_claim`` on the
#: title, ``true`` when it finds a claim. Its terms, how near a number must be
#: to one, and what a number is are copied here, and the test holds each to
#: ``claims``' own, so the plan's hash moves with any of them. What the rule
#: does with them is no constant and in no hash: the test holds it to a copy of
#: the rule written there as literals, and to its verdicts on invented titles
#: recorded under each plan version, so a change to what it decides fails
#: until the card's plan version is bumped (``tests/unit/test_jev_prereg.py::
#: TestTheCardBaselineIsPinnedByWhatItDoes``).
PERFORMANCE_CLAIM_BASELINE: Mapping[str, Any] = MappingProxyType(
    {
        "rule": "claims.find_performance_claim",
        "terms": (
            "sharpe",
            "sortino",
            "calmar",
            "cagr",
            "return",
            "returns",
            "drawdown",
            "alpha",
            "profit",
            "profitable",
            "pnl",
            "p&l",
            "win rate",
            "hit rate",
            "annualised",
            "annualized",
            "outperform",
        ),
        "proximity": 40,
        "number": r"-?\d+(?:[.,]\d+)?%?",
        "true_when": "a claim is found",
    }
)

#: The findings sets' baseline (phase D2, docs/09 section 3.4): the value
#: already recorded for the finding — the role that raised it for
#: ``findings.owner``, its severity for ``findings.severity``, named by each
#: question's ``reads`` — of the earliest finding the programme's model wrote
#: holding the title, by when it was opened and then by its ref. "Send it to
#: whoever raised it" is the honest comparison: a suggestion from the title
#: alone that cannot beat the value recorded beside it adds nothing, and a
#: keyword list, a weaker comparison, would let a chip be called calibrated
#: while it did worse than reading ``raised_by``. Neither column is ever
#: exported to a labeller (``jev_eval.export_labels``), and the harness reads
#: them for the baseline alone (``jev_repo.finding_records``).
FINDINGS_RECORDED_BASELINE: Mapping[str, Any] = MappingProxyType(
    {
        "rule": "findings.recorded",
        "of": "the earliest finding holding the title",
        "origin": "model",
        "order": ("opened_at", "ref"),
        "exported_to_labellers": False,
    }
)

#: Who the findings sets are asked about, and so whose titles are labelled:
#: every finding the programme's model wrote (``origin = 'model'``), whatever
#: its status, with a title of one to ``FINDING_TITLE_MAX_CHARS`` characters
#: — 200, ``jev_questions``' cap, a copy held to it by
#: ``tests/unit/test_jev_prereg.py``, since this module loads the standard
#: library alone — each title once, by its content address. Any status,
#: because the population labels are drawn from is then the population asked
#: about (docs/09, D24); a finding raised by an operator, by Jev, or before
#: migration 0015 named its writer is never in it.
FINDINGS_POPULATION: Mapping[str, Any] = MappingProxyType(
    {
        "table": "findings",
        "origin": "model",
        "status": "any",
        "title_chars": (1, 200),
        "subject": "finding_title",
        "address": "sha256 of the title as UTF-8",
    }
)

#: The label a keyword rule gives text none of its keywords is in: the
#: escape of both catalogue questions. A rule never answers anything else
#: without a keyword, and never ``other_mechanism``.
KEYWORD_FALLBACK = "insufficient_evidence"

#: How :func:`keyword_label` finds a keyword, by name, so a change to the
#: finding is a change to every plan that names it: ``keywords/v1`` is the
#: matcher below.
KEYWORD_MATCHER = "keywords/v1"

#: The ordered keyword rules for a strategy's asset class: the first rule any
#: of whose keywords the text holds gives its label; :data:`KEYWORD_FALLBACK`
#: otherwise. Design part C7's rules, as data. "Crypto words" are the design's
#: phrase; this is the list this build chose for it.
ASSET_CLASS_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "cryptocurrencies",
        ("crypto", "cryptocurrency", "bitcoin", "ethereum", "blockchain"),
    ),
    (
        "bonds",
        (
            "bond",
            "treasury",
            "yield",
            "fixed income",
            "sovereign",
            "credit",
            "term premium",
            "interest rate",
        ),
    ),
    ("commodities", ("commodity", "gold", "silver", "oil", "crude", "metal", "grain")),
    ("currencies", ("currency", "foreign exchange", "fx", "carry")),
    ("derivatives", ("option", "volatility", "vix", "covered call", "derivative")),
    (
        "multi_asset",
        ("multi-asset", "asset allocation", "risk parity", "tactical", "portfolio of"),
    ),
    ("equities", ("equity", "stock", "share", "company", "capm", "size effect")),
)

#: The ordered keyword rules for a strategy's source of return, read as
#: :data:`ASSET_CLASS_KEYWORDS` is. ``diversif*`` is the design's stem,
#: ``diversif``, written as one: it is found at the start of a word, in any
#: ending. Every other keyword is a whole word, as the design wrote it, so
#: ``season`` finds "seasons" and not "seasonality", which no keyword names.
MECHANISM_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("trend_or_momentum", ("momentum", "trend")),
    ("reversal", ("reversal", "mean reversion", "overreaction")),
    ("value", ("value", "book-to-market")),
    ("carry", ("carry", "yield")),
    ("size", ("size", "small")),
    ("low_risk", ("low volatility", "low beta", "betting against beta")),
    ("seasonality", ("season", "calendar", "month", "weekday", "holiday")),
    ("event", ("auction", "earnings", "announcement", "intervention")),
    ("sentiment", ("media", "tone", "sentiment", "news", "attention")),
    (
        "allocation",
        ("risk parity", "optimisation", "optimization", "allocation", "diversif*"),
    ),
)

#: The ops set's keyword rules (phase D3, docs/09 section 3.4): the likely
#: cause of a failed job, read by :func:`keyword_label` from the subject's
#: text — the job's kind and its skeleton, ``jev_questions.job_error_text`` —
#: ordered, first match wins, the code-defect words before ``data_missing``,
#: so "missing 1 required positional argument" is a code defect; text no
#: keyword is in is :data:`OPS_KEYWORD_FALLBACK`.
#:
#: The design's draft, cut to what can fire. Each keyword is held to a real
#: message a triaged job can record as it stands — a builtin's, triggered in
#: the test; an operating system's error, by its errno; PostgreSQL's, as
#: asyncpg raises it; numpy's and pandas' own — that code leaves to Jev and
#: whose skeleton is admissible, the keyword found in its subject text by this
#: matcher (``tests/unit/test_jev_prereg.py::TestTheOpsKeywords``). A keyword no
#: such message produces is dropped: every HTTP status, the rate-limit words,
#: ``unauthorized`` and ``forbidden``, since the data sources wrap every
#: vendor failure in a message code places (``jev_chips``); the words the
#: redactor cannot emit (``throttled``, ``unauthorised``, ``credential``,
#: ``exhausted``, ``dns``, ``outage``, ``inconsistent``); the builtins'
#: messages too short to be asked about (``not callable``, ``not
#: subscriptable``, ``is not defined``); and ``password``, ``cannot connect``,
#: ``empty response``, ``no data``, ``delisted`` and ``not found``, which no
#: such message holds in an admissible skeleton. So the rule never answers
#: ``rate_limit``.
OPS_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "credentials",
        (
            "permission",  # "permission denied", PostgreSQL's or the system's
            "authentication",  # "authentication failed", PostgreSQL refusing a login
        ),
    ),
    (
        "database",
        ("deadlock", "constraint", "violates", "duplicate key", "could not serialize"),
    ),
    ("resource_limit", ("memory", "disk", "no space")),
    (
        "network",
        (
            "connection",
            "refused",
            "reset",
            "timeout",
            "timed out",
            "unreachable",
            "socket",
        ),
    ),
    ("vendor_service", ("unavailable",)),
    (
        "code_defect",
        (
            "has no attribute",
            "unsupported operand",
            "out of range",
            "division by zero",
            "not iterable",
            "unexpected keyword argument",
            "required positional argument",
        ),
    ),
    ("data_missing", ("missing", "no rows", "empty")),
    ("data_invalid", ("malformed", "invalid", "nan")),
    ("configuration", ("parameter", "setting", "configuration", "unknown")),
)

#: What the ops rule gives text no keyword is in: ``unclear``, the set's
#: escape (docs/09, section 3.4).
OPS_KEYWORD_FALLBACK = "unclear"

#: Who the ops set is asked about, and so whose skeletons are labelled (phase
#: D3, docs/09 sections 3.4 and 3.7): every job of a triaged kind that failed
#: and finished after the UTC day the pinned model was first observed
#: (``jev_catalogue.MODEL_FIRST_OBSERVED``), so that every item is dated
#: strictly after it — a job failed by an expired lease has no finish time,
#: and is never in it — whose error code's table leaves to Jev and whose
#: skeleton holds at least the redactor's minimum of content words, each
#: skeleton once, by its state's address; and dated over these same rows
#: (``jev_repo.job_error_population``). The kinds, both versions and hashes
#: and the minimum are copies, since this module loads the standard library
#: alone, and ``tests/unit/test_jev_prereg.py::TestTheOpsPlan`` holds each to
#: ``jev_redact``'s and ``jev_chips``' own, so the plan's hash moves with the
#: redactor and the shapes table.
OPS_POPULATION: Mapping[str, Any] = MappingProxyType(
    {
        "table": "jobs",
        "status": "failed",
        "kinds": ("backtest", "walkforward", "ingest_bars", "ingest_reference_bars"),
        "finished": "after the UTC day the pin was first observed",
        "left_to_jev_by": MappingProxyType(
            {
                "rule": "jev_chips.code_cause",
                "version": 2,
                "sha256": (
                    "0ce6cdc62fbbbfe20ba80fa5f268157f6a21f838687fc8657bf8f4a84aa474d8"
                ),
            }
        ),
        "redactor": MappingProxyType(
            {
                "rule": "jev_redact.skeleton",
                "version": 2,
                "sha256": (
                    "ed4585f4750734e4615fc193300fddbc858fcb234462d3667bb859e05c1a3814"
                ),
            }
        ),
        "min_content_tokens": 3,
        "subject": "job_error",
        "address": "jev_hash.state_hash of the state sent",
        "dated_by": "the earliest finished_at of the population's rows holding it",
    }
)

#: The words a keyword's plural never falls on: in "portfolio of" the noun is
#: the one before.
_NOT_PLURALISED = frozenset({"of"})

#: What a keyword ending in this is: a stem, found at the start of a word.
_STEM = "*"


def plural(word: str) -> str:
    """
    ``word``'s regular English plural, by rule and nothing else: a ``y`` after
    a consonant becomes ``ies``; a word ending in ``s``, ``x``, ``z``, ``ch``
    or ``sh`` takes ``es``; every other word takes ``s``. Irregular plurals are
    not read, and a word the rule makes nonsense of ("news") merely gains a
    form no text holds.
    """
    if len(word) > 1 and word.endswith("y") and word[-2] not in "aeiou":
        return word[:-1] + "ies"
    if word.endswith(("s", "x", "z", "ch", "sh")):
        return word + "es"
    return word + "s"


def keyword_forms(keyword: str) -> tuple[str, ...]:
    """
    The forms :func:`keyword_label` finds ``keyword`` in: as written, and with
    its last word that is not "of" in the plural (:func:`plural`); a stem,
    ending ``*``, in its one form. Every keyword of every rule, so the rule a
    plan names is the one the docs describe:
    ``tests/unit/test_jev_prereg.py`` holds the forms of the whole list to a
    table written there.
    """
    if keyword.endswith(_STEM):
        return (keyword,)
    words = keyword.split(" ")
    last = max(i for i, word in enumerate(words) if word not in _NOT_PLURALISED)
    pluralised = [*words[:last], plural(words[last]), *words[last + 1 :]]
    return (keyword, " ".join(pluralised))


@functools.cache
def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    """
    One keyword, in every form, as whole words of casefolded text: neither end
    beside a letter or a digit, so "Turmoil in the Soil" holds no "oil"; and
    its words apart by any run of spaces and hyphens, whichever the keyword
    was written with, so "fixed-income" is "fixed income". A stem keeps no
    boundary at its end.
    """
    alternatives = []
    for form in keyword_forms(keyword):
        stem = form.endswith(_STEM)
        words = re.split(r"[ -]", form.removesuffix(_STEM))
        body = r"[\s-]+".join(re.escape(word) for word in words)
        alternatives.append(body if stem else body + r"(?![^\W_])")
    return re.compile(r"(?<![^\W_])(?:" + "|".join(alternatives) + ")")


def keyword_label(
    rules: Sequence[tuple[str, Sequence[str]]],
    text: str,
    *,
    fallback: str | None = None,
) -> str:
    """
    What an ordered keyword rule says of ``text``: the label of the first rule
    any of whose keywords ``text`` holds, read casefolded and as whole words
    (:func:`_keyword_pattern`), each keyword in its forms
    (:func:`keyword_forms`); ``fallback`` when none does —
    :data:`KEYWORD_FALLBACK` unless a plan names its own (from phase D, each
    plan records the one it uses as ``"fallback"``; every phase C plan keeps
    :data:`KEYWORD_FALLBACK`, so no hash of theirs moved). The constant is
    read when the rule is applied, never bound as a default, so a moved
    constant is a moved rule. Pure and deterministic: the text alone decides
    it.
    """
    folded = text.casefold()
    for label, keywords in rules:
        if any(_keyword_pattern(keyword).search(folded) for keyword in keywords):
            return label
    return KEYWORD_FALLBACK if fallback is None else fallback


def _keyword_baseline(
    rules: Sequence[tuple[str, Sequence[str]]],
    reads: str,
    *,
    fallback: str | None = None,
) -> dict[str, Any]:
    return {
        "rule": "jev_prereg.keyword_label",
        "matcher": KEYWORD_MATCHER,
        "reads": reads,
        "rules": rules,
        "fallback": KEYWORD_FALLBACK if fallback is None else fallback,
    }


def _set_plans() -> dict[tuple[str, int], dict[str, Any]]:
    """
    Every set plan, by set name and version, built from the constants above
    each time it is read, so a constant moved is a plan moved: per question,
    its target (:data:`SET_TARGETS`) and its baseline, in the plan's
    ``keyword_baseline`` slot whatever its rule; and from phase D2, for the
    findings sets, the population they are asked about
    (:data:`FINDINGS_POPULATION`), and from phase D3 the ops set's
    (:data:`OPS_POPULATION`). A phase C plan holds no population, so none of
    their hashes moved.
    """

    def question(name: str, key: str, baseline: Mapping[str, Any]) -> dict:
        return {**SET_TARGETS[(name, key)], "keyword_baseline": baseline}

    catalogue = {
        "asset_class": _keyword_baseline(ASSET_CLASS_KEYWORDS, "excerpt"),
        "mechanism": _keyword_baseline(MECHANISM_KEYWORDS, "excerpt"),
    }
    hypothesis = {
        "asset_class": _keyword_baseline(ASSET_CLASS_KEYWORDS, "title"),
        "mechanism": _keyword_baseline(MECHANISM_KEYWORDS, "title"),
    }
    questions = {
        ("guardrail.injection", 1): {
            "addressed_to_ai": question(
                "guardrail.injection",
                "addressed_to_ai",
                {**CODE_SCREEN_BASELINE, "reads": "excerpt"},
            ),
        },
        ("research.catalogue", 1): {
            key: question("research.catalogue", key, baseline)
            for key, baseline in catalogue.items()
        },
        ("research.hypothesis", 1): {
            key: question("research.hypothesis", key, baseline)
            for key, baseline in hypothesis.items()
        },
        ("guardrail.card", 1): {
            "performance_claim": question(
                "guardrail.card",
                "performance_claim",
                {**PERFORMANCE_CLAIM_BASELINE, "reads": "title"},
            ),
        },
        ("findings.owner", 1): {
            "owning_role": question(
                "findings.owner",
                "owning_role",
                {**FINDINGS_RECORDED_BASELINE, "reads": "raised_by"},
            ),
        },
        ("findings.severity", 1): {
            "severity": question(
                "findings.severity",
                "severity",
                {**FINDINGS_RECORDED_BASELINE, "reads": "severity"},
            ),
        },
        ("ops.job_error", 1): {
            "cause": question(
                "ops.job_error",
                "cause",
                _keyword_baseline(
                    OPS_KEYWORDS, "job_error_text", fallback=OPS_KEYWORD_FALLBACK
                ),
            ),
        },
    }
    populations: dict[tuple[str, int], Mapping[str, Any]] = {
        ("findings.owner", 1): FINDINGS_POPULATION,
        ("findings.severity", 1): FINDINGS_POPULATION,
        ("ops.job_error", 1): OPS_POPULATION,
    }
    return {
        key: {
            "set": key[0],
            "version": key[1],
            "plan_version": SET_PLAN_VERSIONS[key],
            "questions": planned,
            **({"population": populations[key]} if key in populations else {}),
        }
        for key, planned in questions.items()
        if key in SET_PLAN_VERSIONS
    }


def set_plan(name: str, version: int) -> dict[str, Any] | None:
    """
    The plan of ``name`` at ``version``, as data, or ``None`` if it has none:
    what :func:`set_plan_hash` hashes.
    """
    found = _set_plans().get((name, version))
    return None if found is None else _as_data(found)


def set_plan_hash(name: str, version: int) -> str | None:
    """
    sha256 of :func:`set_plan` as compact JSON with its mappings' keys sorted,
    as :func:`plan_hash` hashes the global plan; ``None`` for a set with no
    plan.
    """
    plan = set_plan(name, version)
    if plan is None:
        return None
    return _sha256_of(plan)


def plans_in_force(name: str, version: int) -> dict[str, Any] | None:
    """
    The global plan's version and hash and ``name``'s own plan's: what a job
    records beside an answer it asks for, so the harness scores the answer
    only under the plans in force when it was recorded, and never by a
    baseline chosen after it. ``None`` when the set has no plan; a set with
    none is asked nothing (``jev_jobs.run_ask``).
    """
    hashed = set_plan_hash(name, version)
    if hashed is None:
        return None
    return {
        "plan_version": PLAN_VERSION,
        "plan_hash": plan_hash(),
        "set_plan_version": SET_PLAN_VERSIONS[(name, version)],
        "set_plan_hash": hashed,
    }


__all__ = [
    "ANY_OF",
    "ASSET_CLASS_KEYWORDS",
    "BOOTSTRAP_RESAMPLES",
    "BOOTSTRAP_SEED_RULE",
    "CALIBRATION_BINS",
    "CODE_SCREEN_BASELINE",
    "DEV_SPLIT_TENTHS",
    "FINDINGS_POPULATION",
    "FINDINGS_RECORDED_BASELINE",
    "FLIPS_NOT_COMPARED",
    "FLIP_PAIRS",
    "GATE_CI",
    "GATE_FAMILY",
    "GOLDEN_PLAN_HASH",
    "GOLDEN_REGIME_PLAN_HASH",
    "GOLDEN_SET_PLAN_HASHES",
    "KEYWORD_FALLBACK",
    "KEYWORD_MATCHER",
    "LOOKED_AT_SPLITS",
    "LOOKS_COUNTED_BY",
    "MARGIN_GRID",
    "MAX_FLIP_RATE",
    "MAX_FLIP_RATE_NEAR_THRESHOLD",
    "MAX_LOOKS",
    "MECHANISM_KEYWORDS",
    "MIN_COVERED",
    "MIN_DEV_ITEMS",
    "MIN_FLIP_PAIRS",
    "MIN_TEST_ITEMS",
    "NEAR_THRESHOLD",
    "OPS_KEYWORDS",
    "OPS_KEYWORD_FALLBACK",
    "OPS_POPULATION",
    "PERFORMANCE_CLAIM_BASELINE",
    "PLAN_VERSION",
    "REASKS_PER_DAY",
    "REASK_AFTER",
    "REASK_LOW_MARGIN",
    "REASK_UNIFORM_MODULUS",
    "REGIME_BASELINE_RULE",
    "REGIME_PLAN_VERSION",
    "REGIME_SLEEVES",
    "REPORT_CI",
    "SET_PLAN_VERSIONS",
    "SET_TARGETS",
    "STATISTIC_FLOORS",
    "TOO_FEW_PER_CLASS",
    "ReaskStratum",
    "global_plan",
    "keyword_forms",
    "keyword_label",
    "plan_hash",
    "plans_in_force",
    "plural",
    "reask_sample",
    "reask_stratum",
    "regime_baseline",
    "regime_plan",
    "regime_plan_hash",
    "set_plan",
    "set_plan_hash",
    "split_of",
]
