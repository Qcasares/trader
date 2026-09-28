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
levels are reported and which gate, how many flips are too many, which
requests are re-asked, and the rule Jev's regime is compared with — is data
here, hashed by :func:`plan_hash` and pinned beside it by
:data:`GOLDEN_PLAN_HASH`. ``tests/unit/test_jev_prereg.py`` holds both to
``RELEASED_PLAN_HASHES``, an append-only history kept in the test, as the
question sets' words are held. Editing a number here fails the build, and so
does re-recording the golden to match, which is the edit a failing hash test
invites: a released plan is history, and a change is a new
:data:`PLAN_VERSION` with its hash appended, not a corrected old plan.

The regime's baseline, and the sleeves: the agent's defaults
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
:data:`REGIME_BASELINE_RULE` is the code rule phase G's baseline twin will run
beside a Jev-driven allocator, and the forward report compares Jev's recorded
regimes with it now. It reads the equities sleeve only, on purpose: every other
condition would be a free choice, and each free choice is a place to fit the
rule to the answers. :data:`REGIME_SLEEVES` — SPY for equities, IEF for bonds,
GSG for commodities, as ``src/data/reference.py`` holds them for the worker —
says which instruments a regime series describes. **Both are the defaults the
agent that built phase C4 chose, not choices the operator has reviewed.**

How either changes:

* **Before the first regime answer exists** — the decisions area is seeded off,
  so nothing is asked until an operator switches it on — a change is a new
  :data:`PLAN_VERSION` with its hash appended to the released list, and costs
  nothing: no answer was analysed under the old plan. A changed sleeve also
  means changing ``src/data/reference.py`` and the test that holds the two
  equal, and starts a new signal series, since a signal's ``symbol`` names the
  instruments (``jev_clock.sleeve_symbol``).
* **After it** — the same bump, recorded as a change of plan: the regime job
  writes the plan in force into its result as it asks, and the planner into
  each re-ask's payload, so the forward report scores agreement only over the
  answers first recorded under the plan it runs, counts the rest apart by the
  plan they were recorded under, and counts a flip pair only under the plan
  that sampled it (``jev_eval``); no answer is scored by a rule registered
  after it, and the old rule is never rewritten to match.

What the plan holds, and what it does not
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The global plan: the split, the size floors, the margin grid a threshold is
searched on, each lane's target, the confidence levels, the bootstrap, the
calibration bins, the flip limits, the re-ask sample, the "too few to say"
floor and the regime rule. Phase C7 and C8 add a plan per question set beside
the sets they register; no set plan exists yet, and ``usable`` (C9) is what
will one day read them. Nothing here is consumed by anything that acts.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import timedelta
from types import MappingProxyType
from typing import Any, Literal

#: Bumped whenever anything below changes; ``RELEASED_PLAN_HASHES`` in the test
#: gains the new hash, and keeps every old one.
PLAN_VERSION = 1

#: What :func:`plan_hash` returns for :data:`PLAN_VERSION`. Not part of the plan
#: it pins, which could not hash itself.
GOLDEN_PLAN_HASH = "f744c2d88bded050e7b1b0fb946c9e29b502264d55ee6ac7c6a68b182daf7caf"

# ---------------------------------------------------------------------------
# Items: the split and the sizes
# ---------------------------------------------------------------------------

#: An item is in the development split when the first eight hex digits of
#: ``sha256(f"{subject_type}:{subject_id}")``, read as an integer, are below
#: this many tenths of the way round ``% 10``: three in ten. By content, so an
#: item's split never depends on when it was labelled or answered.
DEV_SPLIT_TENTHS = 3

#: The fewest test items an evaluation may gate on, development items a
#: threshold may be searched on, and items a threshold must still cover.
MIN_TEST_ITEMS = 200
MIN_DEV_ITEMS = 100
MIN_COVERED = 30

#: The thresholds searched: margins from 0.00 to 0.98 in steps of 0.02.
MARGIN_GRID: tuple[float, ...] = tuple(round(step * 0.02, 2) for step in range(50))

#: What each lane must reach before a threshold is chosen for it: the Wilson
#: lower bound of the statistic, one-sided at :data:`GATE_CI`, never its point
#: estimate, since 24 of the 30 covered items a threshold needs is 0.80 with a
#: lower bound of 0.57. A set's own plan may raise a target, never lower it.
LANE_TARGETS: Mapping[str, Mapping[str, Any]] = MappingProxyType(
    {
        "research": MappingProxyType(
            {
                "statistic": "covered_accuracy",
                "at_least": 0.80,
                "bound": "wilson_lower_at_gate_ci",
            }
        ),
        "guardrail": MappingProxyType(
            {
                "statistic": "covered_precision_of_the_acting_class",
                "at_least": 0.90,
                "bound": "wilson_lower_at_gate_ci",
            }
        ),
    }
)

# ---------------------------------------------------------------------------
# Uncertainty
# ---------------------------------------------------------------------------

#: Every reported interval: two-sided, 95%.
REPORT_CI = 0.95

#: A gate's bound: one-sided, 99.5%, Bonferroni over a family of up to
#: :data:`GATE_FAMILY` set-and-question pairs; a larger family is a new plan.
GATE_CI = 0.995
GATE_FAMILY = 10

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
#: :data:`MIN_FLIP_PAIRS` pairs; near a threshold means a canonical margin
#: within :data:`NEAR_THRESHOLD` of it.
MAX_FLIP_RATE = 0.05
MAX_FLIP_RATE_NEAR_THRESHOLD = 0.10
MIN_FLIP_PAIRS = 30
NEAR_THRESHOLD = 0.10

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
# The regime's baseline: a rule, frozen before the first answer
# ---------------------------------------------------------------------------

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
    """The whole plan, as data: what :func:`plan_hash` hashes."""
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
            "lane_targets": LANE_TARGETS,
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
            "flips": {
                "max_rate": MAX_FLIP_RATE,
                "max_rate_near_threshold": MAX_FLIP_RATE_NEAR_THRESHOLD,
                "min_pairs": MIN_FLIP_PAIRS,
                "near_threshold": NEAR_THRESHOLD,
            },
            "reasks": {
                "uniform_modulus": REASK_UNIFORM_MODULUS,
                "low_margin": REASK_LOW_MARGIN,
                "per_day": REASKS_PER_DAY,
                "after_hours": REASK_AFTER.total_seconds() / 3600,
                "order": ["uniform", "low_margin"],
            },
            "regime": {"sleeves": REGIME_SLEEVES, "baseline": REGIME_BASELINE_RULE},
        }
    )


def plan_hash() -> str:
    """
    sha256 of :func:`global_plan` as compact JSON with its mappings' keys
    sorted: a mapping's order means nothing here, and a sequence's — the rule's
    lines, the strata's order — is kept, since it is part of what the plan
    says.
    """
    text = json.dumps(
        global_plan(),
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


__all__ = [
    "ANY_OF",
    "BOOTSTRAP_RESAMPLES",
    "BOOTSTRAP_SEED_RULE",
    "CALIBRATION_BINS",
    "DEV_SPLIT_TENTHS",
    "GATE_CI",
    "GATE_FAMILY",
    "GOLDEN_PLAN_HASH",
    "LANE_TARGETS",
    "MARGIN_GRID",
    "MAX_FLIP_RATE",
    "MAX_FLIP_RATE_NEAR_THRESHOLD",
    "MIN_COVERED",
    "MIN_DEV_ITEMS",
    "MIN_FLIP_PAIRS",
    "MIN_TEST_ITEMS",
    "NEAR_THRESHOLD",
    "PLAN_VERSION",
    "REASKS_PER_DAY",
    "REASK_AFTER",
    "REASK_LOW_MARGIN",
    "REASK_UNIFORM_MODULUS",
    "REGIME_BASELINE_RULE",
    "REGIME_SLEEVES",
    "REPORT_CI",
    "TOO_FEW_PER_CLASS",
    "ReaskStratum",
    "global_plan",
    "plan_hash",
    "reask_sample",
    "reask_stratum",
    "regime_baseline",
    "split_of",
]
