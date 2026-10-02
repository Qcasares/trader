"""
The analysis is registered before the answers it analyses (docs/08, phase C,
I15; docs/09, section 3, plan version 2).

``src/programme/jev_prereg.py`` holds every choice the forward report and the
harness will make — the split, the size floors, the statistics' floors, the
confidence levels and the looks they are spent over, the flip limits and how
their pairs are counted, the re-ask sample, and, in a plan of its own, the
rule Jev's regime is compared with — as data, hashed. An analysis chosen
after the data is a search, and a search finds something; these tests are
what make the choice unrevisable:

* the global plan and the regime plan each hash to their golden, and every
  version to an append-only history kept here, apart from the plans —
  :data:`RELEASED_PLAN_HASHES` and :data:`RELEASED_REGIME_PLAN_HASHES` — so
  re-recording a golden after an edit still fails; version 1 of the global
  plan stays released beside version 2, which phase D1 released while the
  ledger held no answer;
* every constant of each plan is in its hash, so a number cannot move without
  moving it, and a constant of one plan moves no other plan's hash;
* the gate's level is Bonferroni over the family and the looks, and a look is
  counted by the family's own identity, never by the model;
* the functions of the plan — the split, the re-ask strata, the baseline rule,
  and from phases C7 and C8 the sets' keyword baselines, the card's claims
  check among them — are checked against copies written here independently,
  with their numbers as literals, so a changed formula fails even where its
  constants did not move;
* the baseline rule is total over every equities state and never abstains, and
  reads only the regime state's own fields and labels.
"""

from __future__ import annotations

import ast
import hashlib
import itertools
import json
import random
import sys
import types
import typing
from collections.abc import Callable
from datetime import timedelta
from fractions import Fraction
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from src.data.reference import REFERENCE_SLEEVES
from src.programme import jev_prereg
from src.programme.jev_questions import (
    DECISION_REGIME,
    SLEEVES,
    RegimeState,
    SleeveState,
)

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "src" / "programme" / "jev_prereg.py"

#: Every released global plan's hash, by version. A version bump appends a row;
#: no row is ever edited or removed. The module's ``GOLDEN_PLAN_HASH`` sits
#: beside the plan, so re-recording it is exactly the edit a developer makes
#: when the hash test fails; this table is history, and editing a released row
#: is an edit to it that a reviewer sees for what it is: an analysis moved
#: after it was registered.
#:
#: Version 1 is the agent's default plan of phase C4, the baseline rule and the
#: sleeves included (docs/08, phase C, C4). Its row was re-pinned once, in
#: C4's review, before the plan merged and before any answer existed: the
#: research target had been registered without the Wilson bound the design's
#: metric definition requires. Version 2 is phase D1's (docs/09, section 3.2):
#: floors by statistic, a family of 20, a 50/50 split, flips over the
#: population, four looks counted across models, re-asks not compared counted
#: against the flip limits, and the regime's rule moved to a plan of its own.
#: It was released while the ledger held no answer, so it set aside none.
RELEASED_PLAN_HASHES: dict[int, str] = {
    1: "f744c2d88bded050e7b1b0fb946c9e29b502264d55ee6ac7c6a68b182daf7caf",
    2: "5d3a7fbbdb804440e70e077c75f9c997454786a84024d5ef58afabcab8365844",
}

#: Every released regime plan's hash, by version (M4): the sleeves and the
#: baseline rule, apart from the global plan since its version 2. Version 1
#: is the agent's defaults of phase C4, as they stood inside global plan
#: version 1, now hashed on their own; append-only, as above.
RELEASED_REGIME_PLAN_HASHES: dict[int, str] = {
    1: "2833a4c00d1a6b0adab46c6d6bf0e3544deae6dc1a964598a088162fc1b6af74",
}


def _release_problems(module: types.ModuleType) -> list[str]:
    problems: list[str] = []
    version = module.PLAN_VERSION
    computed = module.plan_hash()
    if computed != module.GOLDEN_PLAN_HASH:
        problems.append(
            f"the plan hashes to {computed}, but its golden is "
            f"{module.GOLDEN_PLAN_HASH}"
        )
    released = RELEASED_PLAN_HASHES.get(version)
    if released is None:
        problems.append(f"plan v{version} is not in RELEASED_PLAN_HASHES: append it")
    elif computed != released:
        problems.append(
            f"plan v{version} hashes to {computed}, but was released as "
            f"{released}: a released plan is frozen, so bump PLAN_VERSION and "
            "append a row"
        )
    newest = max(RELEASED_PLAN_HASHES)
    if version != newest:
        problems.append(f"plan v{version} is the module's, but v{newest} was released")
    return problems


def _regime_release_problems(module: types.ModuleType) -> list[str]:
    problems: list[str] = []
    version = module.REGIME_PLAN_VERSION
    computed = module.regime_plan_hash()
    if computed != module.GOLDEN_REGIME_PLAN_HASH:
        problems.append(
            f"the regime plan hashes to {computed}, but its golden is "
            f"{module.GOLDEN_REGIME_PLAN_HASH}"
        )
    released = RELEASED_REGIME_PLAN_HASHES.get(version)
    if released is None:
        problems.append(
            f"regime plan v{version} is not in RELEASED_REGIME_PLAN_HASHES: append it"
        )
    elif computed != released:
        problems.append(
            f"regime plan v{version} hashes to {computed}, but was released as "
            f"{released}: a released plan is frozen, so bump REGIME_PLAN_VERSION "
            "and append a row"
        )
    newest = max(RELEASED_REGIME_PLAN_HASHES)
    if version != newest:
        problems.append(
            f"regime plan v{version} is the module's, but v{newest} was released"
        )
    return problems


def _execute_variant(monkeypatch: pytest.MonkeyPatch, source: str) -> types.ModuleType:
    """Execute ``source`` as a fresh module, apart from the imported one."""
    variant = types.ModuleType("jev_prereg_variant")
    monkeypatch.setitem(sys.modules, variant.__name__, variant)
    exec(compile(source, str(MODULE), "exec"), variant.__dict__)
    return variant


class TestThePlanIsItsReleasedHash:
    def test_the_plan_is_its_released_hash(self) -> None:
        assert _release_problems(jev_prereg) == []

    def test_released_plans_are_pairwise_distinct_and_numbered_from_one(self) -> None:
        values = list(RELEASED_PLAN_HASHES.values())
        assert len(set(values)) == len(values)
        assert sorted(RELEASED_PLAN_HASHES) == list(
            range(1, len(RELEASED_PLAN_HASHES) + 1)
        ), "versions are appended in order and none is ever removed"

    def test_editing_the_plan_with_its_golden_redone_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        The edit a developer makes when the hash test fails: a new number, and
        the golden re-recorded to match. The module agrees with itself
        afterwards; the release history does not.
        """
        source = MODULE.read_text(encoding="utf-8")
        line = "MIN_TEST_ITEMS = 200"
        assert source.count(line) == 1
        variant = _execute_variant(
            monkeypatch, source.replace(line, "MIN_TEST_ITEMS = 150")
        )
        variant.GOLDEN_PLAN_HASH = variant.plan_hash()
        problems = _release_problems(variant)
        assert any("a released plan is frozen" in p for p in problems), problems

    def test_a_bump_without_its_row_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = MODULE.read_text(encoding="utf-8")
        line = f"PLAN_VERSION = {jev_prereg.PLAN_VERSION}"
        assert source.count(line) == 1
        variant = _execute_variant(
            monkeypatch,
            source.replace(line, f"PLAN_VERSION = {jev_prereg.PLAN_VERSION + 1}"),
        )
        variant.GOLDEN_PLAN_HASH = variant.plan_hash()
        problems = _release_problems(variant)
        assert any("append it" in p for p in problems), problems

    def test_an_edit_without_its_golden_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = MODULE.read_text(encoding="utf-8")
        line = "REASKS_PER_DAY = 10"
        assert source.count(line) == 1
        variant = _execute_variant(
            monkeypatch, source.replace(line, "REASKS_PER_DAY = 12")
        )
        problems = _release_problems(variant)
        assert any("but its golden is" in p for p in problems), problems

    def test_the_hash_is_of_the_plan_as_compact_sorted_json(self) -> None:
        """
        Recomputed here from the plan itself, so ``plan_hash`` cannot drift to
        hashing something narrower than what ``global_plan`` returns.
        """
        text = json.dumps(
            jev_prereg.global_plan(), sort_keys=True, separators=(",", ":")
        )
        assert hashlib.sha256(text.encode()).hexdigest() == jev_prereg.plan_hash()

    def test_the_plan_is_plain_data(self) -> None:
        """Mappings, lists, strings and numbers: it round-trips through JSON."""
        plan = jev_prereg.global_plan()
        assert json.loads(json.dumps(plan, allow_nan=False)) == plan


class TestThePlanVersions:
    def test_v2_is_released_and_v1_kept(self) -> None:
        """
        Plan version 2 is phase D1's, released while the ledger held no answer
        (docs/09, section 3.1): it is the module's and the newest released,
        and version 1, the plan phase C recorded nothing under, keeps its row,
        so an answer a job recorded under it would still name a released plan.
        """
        assert jev_prereg.PLAN_VERSION == 2 == max(RELEASED_PLAN_HASHES)
        assert jev_prereg.GOLDEN_PLAN_HASH == RELEASED_PLAN_HASHES[2]
        assert RELEASED_PLAN_HASHES[1] == (
            "f744c2d88bded050e7b1b0fb946c9e29b502264d55ee6ac7c6a68b182daf7caf"
        )
        assert jev_prereg.plans_in_force("research.catalogue", 1)["plan_version"] == 2

    def test_what_v2_registers(self) -> None:
        """
        The numbers docs/09 section 3.2 gives version 2, read back from the
        plan as hashed, not from the module's names alone.
        """
        plan = jev_prereg.global_plan()
        assert plan["version"] == 2
        assert plan["split"]["dev_tenths"] == 5
        assert plan["uncertainty"]["gate_family"] == 20
        assert plan["uncertainty"]["gate_ci"] == 0.999375
        assert plan["looks"] == {
            "max": 4,
            "counted_by": ["question_set", "question_set_version", "question_key"],
            "splits": ["test", "all"],
        }
        floors = plan["statistic_floors"]
        assert floors["covered_accuracy"]["at_least"] == 0.80
        assert floors["covered_precision_of_the_acting_class"]["at_least"] == 0.90
        assert plan["flips"]["pairs"] == (
            "every_canonical_request_of_the_question_under_the_pin"
        )
        assert plan["flips"]["not_compared"] == "counted_as_flipped_in_the_worst_case"
        # Unchanged from version 1.
        assert plan["uncertainty"]["report_ci"] == 0.95
        assert plan["sizes"] == {
            "min_test_items": 200,
            "min_dev_items": 100,
            "min_covered": 30,
            "too_few_per_class": 10,
        }
        assert plan["flips"]["max_rate"] == 0.05
        assert plan["flips"]["max_rate_near_threshold"] == 0.10
        assert plan["flips"]["min_pairs"] == 30
        assert plan["flips"]["near_threshold"] == 0.10
        assert "lane_targets" not in plan


#: A different value for every constant of the global plan. A constant added
#: to the module's ``__all__`` must be added here too, and then fails
#: :meth:`TestEveryConstantIsHashed.test_moving_it_moves_the_hash` unless
#: ``global_plan`` carries it: a choice outside the hash is a choice nobody
#: registered.
_MOVED: dict[str, Any] = {
    "PLAN_VERSION": 3,
    "DEV_SPLIT_TENTHS": 4,
    "MIN_TEST_ITEMS": 201,
    "MIN_DEV_ITEMS": 101,
    "MIN_COVERED": 31,
    "MARGIN_GRID": jev_prereg.MARGIN_GRID[:-1],
    "STATISTIC_FLOORS": MappingProxyType(
        {
            **jev_prereg.STATISTIC_FLOORS,
            "covered_accuracy": {
                **jev_prereg.STATISTIC_FLOORS["covered_accuracy"],
                "at_least": 0.75,
            },
        }
    ),
    "REPORT_CI": 0.90,
    "GATE_CI": 0.99,
    "GATE_FAMILY": 21,
    "MAX_LOOKS": 5,
    "LOOKS_COUNTED_BY": (*jev_prereg.LOOKS_COUNTED_BY, "model"),
    "LOOKED_AT_SPLITS": ("test",),
    "BOOTSTRAP_RESAMPLES": 1_000,
    "BOOTSTRAP_SEED_RULE": "int(dataset_sha256[:8], 16)",
    "CALIBRATION_BINS": 5,
    "TOO_FEW_PER_CLASS": 11,
    "MAX_FLIP_RATE": 0.06,
    "MAX_FLIP_RATE_NEAR_THRESHOLD": 0.11,
    "MIN_FLIP_PAIRS": 31,
    "NEAR_THRESHOLD": 0.11,
    # Version 1's rules, which M2 and M5 replaced.
    "FLIP_PAIRS": "the_canonical_requests_of_the_scored_items",
    "FLIPS_NOT_COMPARED": "set_apart_from_the_rate",
    "REASK_UNIFORM_MODULUS": 21,
    "REASK_LOW_MARGIN": 0.21,
    "REASKS_PER_DAY": 11,
    "REASK_AFTER": timedelta(hours=25),
}

#: A different value for every constant of the regime plan (M4), held below to
#: move the regime plan's hash and leave the global plan's alone.
_MOVED_REGIME: dict[str, Any] = {
    "REGIME_PLAN_VERSION": 2,
    "REGIME_SLEEVES": MappingProxyType(
        {"equities": "SPY", "bonds": "TLT", "commodities": "GSG"}
    ),
    "REGIME_BASELINE_RULE": (
        jev_prereg.REGIME_BASELINE_RULE[1],
        jev_prereg.REGIME_BASELINE_RULE[0],
        jev_prereg.REGIME_BASELINE_RULE[2],
    ),
}

#: The upper-case names in ``__all__`` that are choices of the set plans, not
#: of the global plan: each has a move in ``_MOVED_SET``, held below to move a
#: set plan's hash and leave the global plan's alone.
_SET_PLAN_CHOICES = frozenset(
    {
        "ASSET_CLASS_KEYWORDS",
        "CODE_SCREEN_BASELINE",
        "FINDINGS_POPULATION",
        "FINDINGS_RECORDED_BASELINE",
        "KEYWORD_FALLBACK",
        "KEYWORD_MATCHER",
        "MECHANISM_KEYWORDS",
        "OPS_KEYWORDS",
        "OPS_KEYWORD_FALLBACK",
        "OPS_POPULATION",
        "PERFORMANCE_CLAIM_BASELINE",
        "SET_PLAN_VERSIONS",
        "SET_TARGETS",
    }
)

#: The upper-case names in ``__all__`` that are not choices of the global plan:
#: ``ANY_OF`` is the rule's own syntax, the goldens are hashes, and the set
#: plans' and the regime plan's choices are held by their own tests below.
_NOT_CHOICES = (
    frozenset(
        {
            "ANY_OF",
            "GOLDEN_PLAN_HASH",
            "GOLDEN_REGIME_PLAN_HASH",
            "GOLDEN_SET_PLAN_HASHES",
        }
    )
    | _SET_PLAN_CHOICES
    | frozenset(_MOVED_REGIME)
)


class TestEveryConstantIsHashed:
    def test_every_constant_has_a_move(self) -> None:
        constants = {name for name in jev_prereg.__all__ if name.isupper()}
        assert constants - _NOT_CHOICES == set(_MOVED)

    @pytest.mark.parametrize("name", sorted(_MOVED))
    def test_moving_it_moves_the_hash(
        self, monkeypatch: pytest.MonkeyPatch, name: str
    ) -> None:
        before = jev_prereg.plan_hash()
        regime_before = jev_prereg.regime_plan_hash()
        assert _MOVED[name] != getattr(jev_prereg, name)
        monkeypatch.setattr(jev_prereg, name, _MOVED[name])
        assert jev_prereg.plan_hash() != before
        assert jev_prereg.regime_plan_hash() == regime_before, (
            f"{name} is the global plan's, and moved the regime plan"
        )

    def test_nothing_in_the_plan_can_be_changed_in_place(self) -> None:
        """
        A mapping of the plan is read-only, so the hash computed at the start
        of a report is still the plan's at its end.
        """
        floors = jev_prereg.STATISTIC_FLOORS
        with pytest.raises(TypeError):
            floors["covered_accuracy"] = {}  # type: ignore[index]
        with pytest.raises(TypeError):
            floors["covered_accuracy"]["at_least"] = 0.5  # type: ignore[index]
        with pytest.raises(TypeError):
            jev_prereg.REGIME_SLEEVES["bonds"] = "TLT"  # type: ignore[index]
        risk_off = jev_prereg.REGIME_BASELINE_RULE[0][1]
        with pytest.raises(TypeError):
            risk_off["equities.trend"] = ("near",)  # type: ignore[index]
        with pytest.raises(TypeError):
            risk_off[jev_prereg.ANY_OF][0]["equities.drawdown"] = ()  # type: ignore[index]
        assert isinstance(jev_prereg.LOOKS_COUNTED_BY, tuple)
        assert isinstance(jev_prereg.LOOKED_AT_SPLITS, tuple)


class TestTheStatisticFloors:
    """
    R1: the floors are by statistic, where version 1 held a target per lane,
    and each is read as the design's binding metric definition reads every
    target (docs/08, phase C, design section 10.1): a threshold is the
    smallest margin with at least ``MIN_COVERED`` covered items whose
    statistic's **Wilson lower bound at ``GATE_CI``** meets the floor. A point
    estimate is not a floor met.
    """

    def test_every_floor_is_a_wilson_lower_bound_at_the_gate_level(self) -> None:
        assert set(jev_prereg.STATISTIC_FLOORS) == {
            "covered_accuracy",
            "covered_precision_of_the_acting_class",
        }
        for statistic, floor in jev_prereg.STATISTIC_FLOORS.items():
            assert floor.get("bound") == "wilson_lower_at_gate_ci", (
                f"the {statistic} floor is registered as a bare point estimate: "
                f"{dict(floor)}"
            )
        assert jev_prereg.STATISTIC_FLOORS["covered_accuracy"]["at_least"] == 0.80
        assert (
            jev_prereg.STATISTIC_FLOORS["covered_precision_of_the_acting_class"][
                "at_least"
            ]
            == 0.90
        )

    def test_each_floor_says_which_questions_it_measures(self) -> None:
        """The rule R1 states, written into the hash beside each floor."""
        floors = jev_prereg.STATISTIC_FLOORS
        assert floors["covered_accuracy"]["measures"] == (
            "a question with no acting class"
        )
        assert floors["covered_precision_of_the_acting_class"]["measures"] == (
            "a question with an acting class"
        )

    def test_a_point_estimate_at_the_floor_is_far_from_meeting_it(self) -> None:
        """
        Why the bound matters, in the plan's own numbers: 24 of the 30 covered
        items a threshold needs is a covered accuracy of 0.80, exactly its
        floor, and its lower bound at the gate level is about 0.51.
        """
        from src.programme import jev_stats

        floor = jev_prereg.STATISTIC_FLOORS["covered_accuracy"]["at_least"]
        n = jev_prereg.MIN_COVERED
        k = round(floor * n)
        assert k / n == pytest.approx(floor)
        bounds = jev_stats.wilson(k, n, jev_prereg.GATE_CI, one_sided=True)
        assert bounds is not None
        low, _ = bounds
        assert low == pytest.approx(0.505, abs=0.001)
        assert low < floor

    def test_how_many_items_all_right_a_floor_needs(self) -> None:
        """
        docs/09 section 3.6: at 0.999375 a covered accuracy floor of 0.80
        needs 42 covered items all right, and a covered precision floor of
        0.90 needs 94 — against 30 and 60 at version 1's 0.995, where the
        first was ``MIN_COVERED``'s, the bound alone needing 27.
        """
        from src.programme import jev_stats

        def fewest(floor: float, level: float) -> int:
            bound_alone = next(
                n
                for n in range(1, 1_000)
                if jev_stats.wilson(n, n, level, one_sided=True)[0] >= floor
            )
            return max(jev_prereg.MIN_COVERED, bound_alone)

        assert fewest(0.80, jev_prereg.GATE_CI) == 42
        assert fewest(0.90, jev_prereg.GATE_CI) == 94
        assert (fewest(0.80, 0.995), fewest(0.90, 0.995)) == (30, 60)


def _gated_family() -> set[tuple[str, int, str]]:
    """
    Every set, version and question a set plan gates — each version's
    questions counted, since an earlier version's gate was applied too —
    from the plans themselves rather than from ``SET_TARGETS``, whose
    entries gate nothing without a plan naming them.
    """
    return {
        (name, version, key)
        for name, version in jev_prereg.SET_PLAN_VERSIONS
        for key in (jev_prereg.set_plan(name, version) or {}).get("questions", {})
    }


class TestTheGateFamily:
    """
    ``GATE_CI`` is a Bonferroni level: one-sided, so that at most
    ``GATE_FAMILY`` gated set-and-question pairs, each looked at the held-out
    items of at most ``MAX_LOOKS`` times, together err no more often than one
    reported interval leaves out. A pair added through a set plan moves no
    hash of the global plan, so without this nothing would notice the family
    outgrow the level: a larger family is a new global plan, with
    ``GATE_FAMILY`` raised and ``GATE_CI`` with it (docs/08, C9; docs/09,
    section 3.2, R2 and M3).
    """

    def test_the_gated_pairs_fit_the_family(self) -> None:
        family = _gated_family()
        assert len(family) <= jev_prereg.GATE_FAMILY, sorted(family)

    def test_the_family_holds_phase_ds_pairs(self) -> None:
        """
        Pinned pair by pair: phase C's six, phase D2's two findings questions
        and phase D3's ops question — nine of the twenty (docs/09, section
        13).
        """
        assert _gated_family() == {
            ("guardrail.injection", 1, "addressed_to_ai"),
            ("research.catalogue", 1, "asset_class"),
            ("research.catalogue", 1, "mechanism"),
            ("research.hypothesis", 1, "asset_class"),
            ("research.hypothesis", 1, "mechanism"),
            ("guardrail.card", 1, "performance_claim"),
            ("findings.owner", 1, "owning_role"),
            ("findings.severity", 1, "severity"),
            ("ops.job_error", 1, "cause"),
        }

    def test_the_level_is_bonferroni_over_the_family_and_the_looks(self) -> None:
        """
        (1 − ``GATE_CI``) × ``GATE_FAMILY`` × ``MAX_LOOKS`` ≤ 1 − ``REPORT_CI``,
        exactly, and ``GATE_CI`` is the literal 0.999375 = 1 − 0.05 / (20 × 4):
        computed as the fractions the numbers are written as, so no binary
        rounding passes a level the formula does not give.
        """
        gate = Fraction(repr(jev_prereg.GATE_CI))
        report = Fraction(repr(jev_prereg.REPORT_CI))
        spent = (1 - gate) * jev_prereg.GATE_FAMILY * jev_prereg.MAX_LOOKS
        assert spent <= 1 - report
        assert gate == 1 - (1 - report) / (
            jev_prereg.GATE_FAMILY * jev_prereg.MAX_LOOKS
        )
        assert jev_prereg.GATE_CI == 0.999375
        assert (jev_prereg.GATE_FAMILY, jev_prereg.MAX_LOOKS) == (20, 4)

    def test_the_level_check_bites(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A fifth look, the level unchanged, spends more than it claims."""
        monkeypatch.setattr(jev_prereg, "MAX_LOOKS", 5)
        with pytest.raises(AssertionError):
            self.test_the_level_is_bonferroni_over_the_family_and_the_looks()

    def test_looks_are_counted_as_the_family_is(self) -> None:
        """
        A look is counted by the set, its version and the question — the
        identity a pair of the family has (:func:`_gated_family`) — and never
        by the model: the family the level is spent over counts sets,
        versions and questions, so a look counted per model would let a
        second pin spend four more looks outside the 0.05 the level claims
        (docs/09, D-HMB-06). The names are the evaluation row's columns,
        which ``jev_calibration.usable`` counts by.
        """
        assert jev_prereg.LOOKS_COUNTED_BY == (
            "question_set",
            "question_set_version",
            "question_key",
        )
        assert "model" not in jev_prereg.LOOKS_COUNTED_BY
        (sample,) = list(_gated_family())[:1]
        assert len(sample) == len(jev_prereg.LOOKS_COUNTED_BY)
        assert jev_prereg.LOOKED_AT_SPLITS == ("test", "all")
        from src.programme import jev_repo

        assert set(jev_prereg.LOOKS_COUNTED_BY) <= set(jev_repo.EVALUATION_COLUMNS)

    def test_the_count_sees_a_question_a_set_plan_adds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Not vacuous: enough more planned questions and the family overflows."""
        before = len(_gated_family())
        real = jev_prereg._set_plans

        def more() -> dict[tuple[str, int], dict[str, Any]]:
            plans = real()
            questions = plans[("research.catalogue", 1)]["questions"]
            for i in range(jev_prereg.GATE_FAMILY - before + 1):
                questions[f"invented_{i}"] = dict(questions["asset_class"])
            return plans

        monkeypatch.setattr(jev_prereg, "_set_plans", more)
        assert len(_gated_family()) == jev_prereg.GATE_FAMILY + 1
        assert jev_prereg.plan_hash() == jev_prereg.GOLDEN_PLAN_HASH


class TestThePureModuleLoadsNothing:
    def test_it_imports_the_standard_library_alone(self) -> None:
        """
        The API, the planner and the harness all read the plan, so it may load
        nothing that could act. ``test_import_boundaries.py`` proves the same
        in a fresh interpreter; this reads the source.
        """
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0 and node.module is not None
                roots.add(node.module.split(".")[0])
        assert roots <= set(sys.stdlib_module_names) | {"__future__"}, roots


# ---------------------------------------------------------------------------
# The regime plan (M4): the baseline rule and the sleeves, apart
# ---------------------------------------------------------------------------


class TestTheRegimePlan:
    def test_golden_and_released(self) -> None:
        assert _regime_release_problems(jev_prereg) == []
        values = list(RELEASED_REGIME_PLAN_HASHES.values())
        assert len(set(values)) == len(values)
        assert sorted(RELEASED_REGIME_PLAN_HASHES) == list(
            range(1, len(RELEASED_REGIME_PLAN_HASHES) + 1)
        )

    def test_editing_the_rule_with_its_golden_redone_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The edit a failing hash test invites, refused by the history."""
        source = MODULE.read_text(encoding="utf-8")
        line = '"equities.volatility_quintile": (1, 2, 3),'
        assert source.count(line) == 1
        variant = _execute_variant(
            monkeypatch,
            source.replace(line, '"equities.volatility_quintile": (1, 2),'),
        )
        variant.GOLDEN_REGIME_PLAN_HASH = variant.regime_plan_hash()
        problems = _regime_release_problems(variant)
        assert any("a released plan is frozen" in p for p in problems), problems
        # The global plan does not hold the rule, so it does not move.
        assert variant.plan_hash() == jev_prereg.plan_hash()

    def test_a_bump_without_its_row_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = MODULE.read_text(encoding="utf-8")
        line = f"REGIME_PLAN_VERSION = {jev_prereg.REGIME_PLAN_VERSION}"
        assert source.count(line) == 1
        bumped = f"REGIME_PLAN_VERSION = {jev_prereg.REGIME_PLAN_VERSION + 1}"
        variant = _execute_variant(monkeypatch, source.replace(line, bumped))
        variant.GOLDEN_REGIME_PLAN_HASH = variant.regime_plan_hash()
        problems = _regime_release_problems(variant)
        assert any("append it" in p for p in problems), problems

    def test_the_global_plan_holds_no_regime(self) -> None:
        """
        M4: the rule and the sleeves are the regime plan's, and the global
        plan holds neither, so reviewing either sets aside regime agreement
        alone, never every lane's answers.
        """
        plan = jev_prereg.global_plan()
        assert "regime" not in plan
        text = json.dumps(plan)
        for label, _ in jev_prereg.REGIME_BASELINE_RULE:
            assert label not in text, label
        for symbol in jev_prereg.REGIME_SLEEVES.values():
            assert f'"{symbol}"' not in text, symbol
        regime = jev_prereg.regime_plan()
        assert regime["version"] == jev_prereg.REGIME_PLAN_VERSION
        assert regime["sleeves"] == dict(jev_prereg.REGIME_SLEEVES)
        assert [label for label, _ in regime["baseline"]] == [
            "risk_off",
            "risk_on",
            "neutral",
        ]

    @pytest.mark.parametrize("name", sorted(_MOVED_REGIME))
    def test_moving_it_moves_the_regime_plan_and_not_the_global_plan(
        self, monkeypatch: pytest.MonkeyPatch, name: str
    ) -> None:
        before, global_before = jev_prereg.regime_plan_hash(), jev_prereg.plan_hash()
        assert _MOVED_REGIME[name] != getattr(jev_prereg, name)
        monkeypatch.setattr(jev_prereg, name, _MOVED_REGIME[name])
        assert jev_prereg.regime_plan_hash() != before, name
        assert jev_prereg.plan_hash() == global_before, name

    def test_every_regime_constant_has_a_move(self) -> None:
        constants = {name for name in jev_prereg.__all__ if name.isupper()}
        assert set(_MOVED_REGIME) <= constants
        assert {n for n in constants if n.startswith("REGIME_")} == set(_MOVED_REGIME)

    def test_the_order_of_the_rules_lines_is_part_of_the_plan(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        First match wins, so the same lines in another order are a different
        rule: the hash keeps a sequence's order and sorts only a mapping's
        keys. The move above is exactly a reordering.
        """
        moved = _MOVED_REGIME["REGIME_BASELINE_RULE"]
        assert sorted(moved, key=lambda line: line[0]) == sorted(
            jev_prereg.REGIME_BASELINE_RULE, key=lambda line: line[0]
        )
        before = jev_prereg.regime_plan_hash()
        monkeypatch.setattr(jev_prereg, "REGIME_BASELINE_RULE", moved)
        assert jev_prereg.regime_plan_hash() != before

    def test_the_hash_is_of_the_regime_plan_as_compact_sorted_json(self) -> None:
        text = json.dumps(
            jev_prereg.regime_plan(), sort_keys=True, separators=(",", ":")
        )
        assert hashlib.sha256(text.encode()).hexdigest() == (
            jev_prereg.regime_plan_hash()
        )
        plan = jev_prereg.regime_plan()
        assert json.loads(json.dumps(plan, allow_nan=False)) == plan

    def test_the_sleeves_are_the_workers(self) -> None:
        """
        The regime plan's record of which instruments a regime series
        describes is the worker's copy, in the state's own order: two copies
        that disagreed would describe one series by instruments nobody
        fetched.
        """
        assert dict(jev_prereg.REGIME_SLEEVES) == dict(REFERENCE_SLEEVES)
        assert tuple(jev_prereg.REGIME_SLEEVES) == SLEEVES == tuple(REFERENCE_SLEEVES)
        assert jev_prereg.regime_plan()["sleeves"] == dict(REFERENCE_SLEEVES)


# ---------------------------------------------------------------------------
# The regime's baseline
# ---------------------------------------------------------------------------

_TRENDS = typing.get_args(SleeveState.model_fields["trend"].annotation)
_QUINTILES = typing.get_args(SleeveState.model_fields["volatility_quintile"].annotation)
_DRAWDOWNS = typing.get_args(SleeveState.model_fields["drawdown"].annotation)
_MOMENTA = typing.get_args(SleeveState.model_fields["momentum"].annotation)

#: Every sleeve state the vocabulary allows: 3 × 5 × 4 × 3.
_SLEEVE_STATES = [
    SleeveState(trend=t, volatility_quintile=v, drawdown=d, momentum=m)
    for t, v, d, m in itertools.product(_TRENDS, _QUINTILES, _DRAWDOWNS, _MOMENTA)
]
_CALM = SleeveState(
    trend="near", volatility_quintile=3, drawdown="none", momentum="flat"
)


def _expected(equities: SleeveState) -> str:
    """
    The rule as the design states it, written again with its labels as
    literals: the module's rule is checked against this, not against itself.
    """
    if (
        equities.trend == "below"
        and equities.momentum == "down"
        and (
            equities.drawdown in ("deep", "severe") or equities.volatility_quintile == 5
        )
    ):
        return "risk_off"
    if (
        equities.trend == "above"
        and equities.momentum == "up"
        and equities.drawdown in ("none", "shallow")
        and equities.volatility_quintile in (1, 2, 3)
    ):
        return "risk_on"
    return "neutral"


def _dumped(
    equities: SleeveState, bonds: SleeveState, commodities: SleeveState
) -> dict[str, Any]:
    """A state as the lane sends and records it: the set's own dump."""
    return DECISION_REGIME.dump_state(
        RegimeState(equities=equities, bonds=bonds, commodities=commodities)
    )


class TestTheBaselineRule:
    def test_there_are_180_equities_states(self) -> None:
        assert len(_SLEEVE_STATES) == 180
        assert len({s.model_dump_json() for s in _SLEEVE_STATES}) == 180

    def test_the_baseline_rule_is_total_and_never_abstains(self) -> None:
        """
        Every one of the 180 equities descriptor combinations gets one of the
        three regimes, and the one written independently here: a rule does not
        abstain, so the escape is never its answer.
        """
        escape = DECISION_REGIME.escape_options["regime"]
        seen = set()
        for equities in _SLEEVE_STATES:
            answer = jev_prereg.regime_baseline(_dumped(equities, _CALM, _CALM))
            assert answer != escape
            assert answer == _expected(equities), equities
            seen.add(answer)
        assert seen == {"risk_on", "neutral", "risk_off"}

    def test_the_rule_answers_with_the_questions_own_regimes(self) -> None:
        options = list(DECISION_REGIME.as_request_questions()["regime"]["criteria"])
        escape = DECISION_REGIME.escape_options["regime"]
        labels = [label for label, _ in jev_prereg.REGIME_BASELINE_RULE]
        assert sorted(labels) == sorted(o for o in options if o != escape)
        assert jev_prereg.REGIME_BASELINE_RULE[-1] == ("neutral", {}), (
            "the last line holds unconditionally, which is what makes it total"
        )

    def test_the_rule_reads_only_state_labels(self) -> None:
        """
        Every path the rule names is a field of the regime state, sleeve then
        descriptor, and every label it lists is one that descriptor can hold:
        the rule reads the labels Jev is shown and nothing else, so a figure,
        a date or a ticker cannot enter it.
        """
        sleeves = set(RegimeState.model_fields)
        vocabulary = {
            name: set(typing.get_args(field.annotation))
            for name, field in SleeveState.model_fields.items()
        }

        def conditions(mapping):
            for path, allowed in mapping.items():
                if path == jev_prereg.ANY_OF:
                    for option in allowed:
                        yield from conditions(option)
                else:
                    yield path, allowed

        paths = []
        for _, mapping in jev_prereg.REGIME_BASELINE_RULE:
            for path, allowed in conditions(mapping):
                sleeve, descriptor = path.split(".")
                assert sleeve in sleeves, path
                assert descriptor in vocabulary, path
                assert isinstance(allowed, tuple) and allowed, path
                assert set(allowed) <= vocabulary[descriptor], (path, allowed)
                paths.append(path)
        assert {p.split(".")[0] for p in paths} == {"equities"}, (
            "equities only, on purpose: every other condition is a free choice"
        )

    def test_the_rule_reads_equities_alone(self) -> None:
        """
        Whatever bonds and commodities say, the answer is the equities
        sleeve's: every equities state against every bonds state, and against
        every commodities state.
        """
        dumps = [s.model_dump() for s in _SLEEVE_STATES]
        calm = _CALM.model_dump()
        for equities, expected in zip(
            dumps, (_expected(s) for s in _SLEEVE_STATES), strict=True
        ):
            for other in dumps:
                assert (
                    jev_prereg.regime_baseline(
                        {"equities": equities, "bonds": other, "commodities": calm}
                    )
                    == expected
                )
                assert (
                    jev_prereg.regime_baseline(
                        {"equities": equities, "bonds": calm, "commodities": other}
                    )
                    == expected
                )

    def test_a_state_without_a_path_the_rule_reads_is_a_defect(self) -> None:
        """A missing field is a caller's defect, never read as a default."""
        with pytest.raises(KeyError):
            jev_prereg.regime_baseline({"bonds": _CALM.model_dump()})
        with pytest.raises(KeyError):
            jev_prereg.regime_baseline({"equities": {"trend": "below"}})


# ---------------------------------------------------------------------------
# The split and the re-ask sample
# ---------------------------------------------------------------------------


def _hash_of(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class TestTheSplit:
    def test_the_split_is_by_content(self) -> None:
        """Written again here with its numbers as literals."""
        for i in range(2_000):
            subject_id = _hash_of(f"item {i}")
            digest = _hash_of(f"web_excerpt:{subject_id}")
            expected = "dev" if int(digest[:8], 16) % 10 < 5 else "test"
            assert jev_prereg.split_of("web_excerpt", subject_id) == expected

    def test_the_split_is_five_tenths(self) -> None:
        """
        M1: half the items are development items, where version 1 held three
        in ten; the test split is held to the bar the search applied, so the
        development share binds as hard as the test share does.
        """
        assert jev_prereg.DEV_SPLIT_TENTHS == 5
        splits = [jev_prereg.split_of("session", f"{i:06d}") for i in range(10_000)]
        share = splits.count("dev") / len(splits)
        assert 0.48 < share < 0.52

    def test_the_type_is_part_of_the_address(self) -> None:
        """One id under two subject types is two items, each split on its own."""
        differ = sum(
            jev_prereg.split_of("session", f"{i}")
            != jev_prereg.split_of("hypothesis_title", f"{i}")
            for i in range(1_000)
        )
        assert differ > 0


def _hash_with_prefix(divisible: bool, seed: int) -> str:
    """A request hash whose first eight hex digits are, or are not, ≡ 0 mod 20."""
    rng = random.Random(seed)
    while True:
        candidate = f"{rng.getrandbits(256):064x}"
        if (int(candidate[:8], 16) % 20 == 0) == divisible:
            return candidate


class TestTheReaskStrata:
    @pytest.mark.parametrize("margins", [[], [0.9], [0.01], [0.5, 0.05]])
    def test_the_uniform_stratum_is_by_hash_whatever_was_answered(
        self, margins: list[float]
    ) -> None:
        request_hash = _hash_with_prefix(True, 1)
        assert jev_prereg.reask_stratum(request_hash, margins) == "uniform"

    @pytest.mark.parametrize(
        ("margins", "stratum"),
        [
            ([], None),
            ([0.20], None),
            ([0.5, 0.9], None),
            ([0.199], "low_margin"),
            ([0.9, 0.0], "low_margin"),
        ],
    )
    def test_the_low_margin_stratum_is_by_the_valid_answers(
        self, margins: list[float], stratum: str | None
    ) -> None:
        request_hash = _hash_with_prefix(False, 2)
        assert jev_prereg.reask_stratum(request_hash, margins) == stratum

    def test_the_strata_are_written_again_here(self) -> None:
        rng = random.Random(3)
        for _ in range(3_000):
            request_hash = f"{rng.getrandbits(256):064x}"
            margins = [rng.random() for _ in range(rng.randint(0, 3))]
            if int(request_hash[:8], 16) % 20 == 0:
                expected = "uniform"
            elif any(m < 0.2 for m in margins):
                expected = "low_margin"
            else:
                expected = None
            assert jev_prereg.reask_stratum(request_hash, margins) == expected


def _candidate(request_hash: str, margins: list[float]) -> dict[str, Any]:
    return {"request_hash": request_hash, "valid_margins": margins, "id": request_hash}


class TestTheReaskSample:
    def _pool(self) -> list[dict[str, Any]]:
        uniform = [_candidate(_hash_with_prefix(True, s), [0.9]) for s in range(10, 16)]
        low = [_candidate(_hash_with_prefix(False, s), [0.05]) for s in range(20, 28)]
        neither = [
            _candidate(_hash_with_prefix(False, s), [0.9]) for s in range(30, 35)
        ]
        return uniform + low + neither

    def test_uniform_first_then_low_margin_each_in_hash_order(self) -> None:
        pool = self._pool()
        sample = jev_prereg.reask_sample(pool, limit=100)
        strata = [stratum for stratum, _ in sample]
        assert strata == ["uniform"] * 6 + ["low_margin"] * 4
        uniform = [c["request_hash"] for s, c in sample if s == "uniform"]
        low = [c["request_hash"] for s, c in sample if s == "low_margin"]
        assert uniform == sorted(uniform) and low == sorted(low)

    def test_never_more_than_ten_a_day_whatever_the_limit(self) -> None:
        assert len(jev_prereg.reask_sample(self._pool(), limit=100)) == 10
        assert len(jev_prereg.reask_sample(self._pool(), limit=3)) == 3
        assert jev_prereg.reask_sample(self._pool(), limit=0) == []

    def test_the_sample_is_deterministic(self) -> None:
        """A planner running every minute re-selects, it does not redraw."""
        pool = self._pool()
        first = jev_prereg.reask_sample(pool, limit=7)
        rng = random.Random(4)
        for _ in range(20):
            shuffled = list(pool)
            rng.shuffle(shuffled)
            assert jev_prereg.reask_sample(shuffled, limit=7) == first

    def test_neither_stratum_is_never_sampled(self) -> None:
        pool = [c for c in self._pool() if c["valid_margins"] == [0.9]]
        sampled = {c["id"] for _, c in jev_prereg.reask_sample(pool, limit=10)}
        assert all(int(identifier[:8], 16) % 20 == 0 for identifier in sampled), (
            "only the uniform stratum can draw a request with no low margin"
        )

    def test_a_negative_limit_is_refused(self) -> None:
        with pytest.raises(ValueError):
            jev_prereg.reask_sample([], limit=-1)


# ---------------------------------------------------------------------------
# The set plans (phases C7 and C8)
# ---------------------------------------------------------------------------

#: Every released set plan's hash, by set name, set version and plan version.
#: Append-only, as ``RELEASED_PLAN_HASHES`` is: the module's
#: ``GOLDEN_SET_PLAN_HASHES`` sits beside the plans, so re-recording it is the
#: edit a failing hash test invites, and this history is what refuses it. A
#: plan changed after answers were recorded under it is a new plan version,
#: and those answers stay scored under the old one.
RELEASED_SET_PLAN_HASHES: dict[tuple[str, int, int], str] = {
    ("guardrail.injection", 1, 1): (
        "2ba46f373fb98c836610d952cfa2d8737b53d8f30db6c2147d6c97bd14eff8f7"
    ),
    ("research.catalogue", 1, 1): (
        "9ab204c87f7517215d9a63bac26cee7a853232d8dffba31c6f434ca0a5292deb"
    ),
    ("research.hypothesis", 1, 1): (
        "1f7274a6d9d39de92d22806edf09d0da49c29804ca44ce64797873e36a07f050"
    ),
    ("guardrail.card", 1, 1): (
        "a72753b5ea04d5af9392657928d777be19b9bbbbd9e013700f2e97e0d231956d"
    ),
    # Phase D2: the findings sets, their baseline the value recorded beside
    # the title, released while the ledger held no answer of theirs.
    ("findings.owner", 1, 1): (
        "e6cb5e05456468a9447b5748a3f09900a4893a5096cea6b0e98c445de05e09e9"
    ),
    ("findings.severity", 1, 1): (
        "256b20e7cf141417af8bb71e4aeaca4b793d4ef1eedb947ec41db96bf30fcca2"
    ),
    # Phase D3: the ops set, its baseline the keyword rule on the skeleton's
    # text, released while the ledger held no answer of it.
    ("ops.job_error", 1, 1): (
        "eaf2412b1c757bde0a0d42bd3d3f3c10fab1c4e9ae04bd30d750a5aef46fa883"
    ),
    # D3's review: the plan names the redactor's version 2, which replaced
    # version 1 before D3 merged, while the ledger held no answer of the set.
    ("ops.job_error", 1, 2): (
        "0578dd14068847a7062f0f0a2f8f2f938a834efd1ac0c41092a9be7168ae5bba"
    ),
}

#: The sets with no plan of their own: the probe measures the vendor, not a
#: set, and the regime's rule is the regime plan's (M4).
WITHOUT_A_SET_PLAN = frozenset({"probe.connectivity", "decision.regime"})


def _set_plan_release_problems(module: types.ModuleType) -> list[str]:
    problems: list[str] = []
    for (name, version), plan_version in module.SET_PLAN_VERSIONS.items():
        computed = module.set_plan_hash(name, version)
        golden = module.GOLDEN_SET_PLAN_HASHES.get((name, version))
        if computed != golden:
            problems.append(f"{name} v{version}'s plan hashes to {computed}")
        released = RELEASED_SET_PLAN_HASHES.get((name, version, plan_version))
        if released is None:
            problems.append(
                f"{name} v{version} plan v{plan_version} is not in "
                "RELEASED_SET_PLAN_HASHES: append it"
            )
        elif computed != released:
            problems.append(
                f"{name} v{version} plan v{plan_version} hashes to {computed}, "
                f"but was released as {released}: a released plan is frozen, so "
                "bump its plan version and append a row"
            )
        released_versions = [
            p for (n, v, p) in RELEASED_SET_PLAN_HASHES if (n, v) == (name, version)
        ]
        if released_versions and plan_version != max(released_versions):
            problems.append(f"{name} v{version} is not at its newest plan")
    if set(module.GOLDEN_SET_PLAN_HASHES) != set(module.SET_PLAN_VERSIONS):
        problems.append("a golden without a plan, or a plan without a golden")
    return problems


class TestTheSetPlansAreTheirReleasedHashes:
    def test_every_set_plan_is_its_released_hash(self) -> None:
        assert _set_plan_release_problems(jev_prereg) == []

    def test_editing_a_plan_with_its_golden_redone_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        A keyword rule changed after answers were recorded under the plan, and
        the golden re-recorded: the module agrees with itself, the released
        history does not, and the change must be a new plan version.
        """
        source = MODULE.read_text(encoding="utf-8")
        line = '("currencies", ("currency", "foreign exchange", "fx", "carry")),'
        assert source.count(line) == 1
        edited = line.replace('"carry")', '"carry", "peg")')
        variant = _execute_variant(monkeypatch, source.replace(line, edited))
        key = ("research.catalogue", 1)
        variant.GOLDEN_SET_PLAN_HASHES = {
            **variant.GOLDEN_SET_PLAN_HASHES,
            key: variant.set_plan_hash(*key),
        }
        problems = _set_plan_release_problems(variant)
        assert any("a released plan is frozen" in p for p in problems), problems

    def test_a_bump_without_its_row_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = MODULE.read_text(encoding="utf-8")
        line = '("guardrail.card", 1): 1,'
        assert source.count(line) == 1
        variant = _execute_variant(
            monkeypatch, source.replace(line, '("guardrail.card", 1): 2,')
        )
        key = ("guardrail.card", 1)
        variant.GOLDEN_SET_PLAN_HASHES = {
            **variant.GOLDEN_SET_PLAN_HASHES,
            key: variant.set_plan_hash(*key),
        }
        problems = _set_plan_release_problems(variant)
        assert any("append it" in p for p in problems), problems

    def test_released_set_plans_are_pairwise_distinct(self) -> None:
        values = list(RELEASED_SET_PLAN_HASHES.values())
        assert len(set(values)) == len(values)

    def test_the_hash_is_of_the_plan_as_compact_sorted_json(self) -> None:
        for name, version in jev_prereg.SET_PLAN_VERSIONS:
            plan = jev_prereg.set_plan(name, version)
            text = json.dumps(plan, sort_keys=True, separators=(",", ":"))
            assert hashlib.sha256(text.encode()).hexdigest() == (
                jev_prereg.set_plan_hash(name, version)
            )
            assert json.loads(json.dumps(plan, allow_nan=False)) == plan

    def test_a_set_with_no_plan_has_no_hash_and_no_plans_in_force(self) -> None:
        assert jev_prereg.set_plan("decision.regime", 1) is None
        assert jev_prereg.set_plan_hash("decision.regime", 1) is None
        assert jev_prereg.plans_in_force("decision.regime", 1) is None
        assert jev_prereg.plans_in_force("research.catalogue", 2) is None

    def test_plans_in_force_names_both_plans(self) -> None:
        assert jev_prereg.plans_in_force("research.catalogue", 1) == {
            "plan_version": jev_prereg.PLAN_VERSION,
            "plan_hash": jev_prereg.plan_hash(),
            "set_plan_version": 1,
            "set_plan_hash": jev_prereg.set_plan_hash("research.catalogue", 1),
        }

    def test_the_set_plans_are_beside_the_global_plan_not_in_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        No set plan holds a constant of the global plan, which is why plan
        version 2 moved no set plan's hash: moving the gate's level, the
        family, the looks or the floors leaves every set plan as released.
        What a job records beside an answer names both, so it is the plans in
        force that moved (``plans_in_force``).
        """
        before = _set_plan_hashes()
        for name, value in (
            ("GATE_CI", 0.995),
            ("GATE_FAMILY", 10),
            ("MAX_LOOKS", 1),
            ("DEV_SPLIT_TENTHS", 3),
        ):
            monkeypatch.setattr(jev_prereg, name, value)
        assert _set_plan_hashes() == before


#: A different value for every choice of the set plans.
_MOVED_SET: dict[str, Any] = {
    "ASSET_CLASS_KEYWORDS": jev_prereg.ASSET_CLASS_KEYWORDS[1:],
    "CODE_SCREEN_BASELINE": {**jev_prereg.CODE_SCREEN_BASELINE, "version": 2},
    "FINDINGS_POPULATION": {**jev_prereg.FINDINGS_POPULATION, "status": "open"},
    "FINDINGS_RECORDED_BASELINE": {
        **jev_prereg.FINDINGS_RECORDED_BASELINE,
        "order": ("opened_at", "ref", "candidate_id"),
    },
    "KEYWORD_FALLBACK": "unclear",
    "KEYWORD_MATCHER": "keywords/v2",
    "MECHANISM_KEYWORDS": jev_prereg.MECHANISM_KEYWORDS[::-1],
    "OPS_KEYWORDS": jev_prereg.OPS_KEYWORDS[1:],
    "OPS_KEYWORD_FALLBACK": "insufficient_evidence",
    "OPS_POPULATION": {**jev_prereg.OPS_POPULATION, "min_content_tokens": 2},
    "PERFORMANCE_CLAIM_BASELINE": {
        **jev_prereg.PERFORMANCE_CLAIM_BASELINE,
        "proximity": 41,
    },
    "SET_PLAN_VERSIONS": MappingProxyType(
        {**jev_prereg.SET_PLAN_VERSIONS, ("guardrail.injection", 1): 2}
    ),
    "SET_TARGETS": MappingProxyType(
        {
            **jev_prereg.SET_TARGETS,
            ("guardrail.card", "performance_claim"): {
                **jev_prereg.SET_TARGETS[("guardrail.card", "performance_claim")],
                "at_least": 0.95,
            },
        }
    ),
}


def _set_plan_hashes() -> dict[tuple[str, int], str | None]:
    return {
        key: jev_prereg.set_plan_hash(*key) for key in jev_prereg.GOLDEN_SET_PLAN_HASHES
    }


class TestEverySetPlanChoiceIsHashed:
    def test_every_choice_has_a_move(self) -> None:
        constants = {name for name in jev_prereg.__all__ if name.isupper()}
        assert _SET_PLAN_CHOICES <= constants
        assert set(_MOVED_SET) == _SET_PLAN_CHOICES

    @pytest.mark.parametrize("name", sorted(_MOVED_SET))
    def test_moving_it_moves_a_set_plan_and_not_the_global_plan(
        self, monkeypatch: pytest.MonkeyPatch, name: str
    ) -> None:
        before, global_before = _set_plan_hashes(), jev_prereg.plan_hash()
        monkeypatch.setattr(jev_prereg, name, _MOVED_SET[name])
        assert _set_plan_hashes() != before, name
        assert jev_prereg.plan_hash() == global_before, name

    def test_nothing_in_a_set_plan_can_be_changed_in_place(self) -> None:
        card = ("guardrail.card", "performance_claim")
        with pytest.raises(TypeError):
            jev_prereg.SET_PLAN_VERSIONS[("guardrail.card", 1)] = 2  # type: ignore[index]
        with pytest.raises(TypeError):
            jev_prereg.SET_TARGETS[card]["at_least"] = 0.5  # type: ignore[index]
        with pytest.raises(TypeError):
            jev_prereg.CODE_SCREEN_BASELINE["version"] = 2  # type: ignore[index]
        with pytest.raises(TypeError):
            jev_prereg.PERFORMANCE_CLAIM_BASELINE["proximity"] = 1  # type: ignore[index]
        with pytest.raises(TypeError):
            jev_prereg.FINDINGS_RECORDED_BASELINE["origin"] = "any"  # type: ignore[index]
        with pytest.raises(TypeError):
            jev_prereg.FINDINGS_POPULATION["status"] = "open"  # type: ignore[index]
        assert isinstance(jev_prereg.FINDINGS_RECORDED_BASELINE["order"], tuple)
        assert isinstance(jev_prereg.FINDINGS_POPULATION["title_chars"], tuple)


def _registered() -> dict[str, Any]:
    from src.programme import jev_questions

    return dict(jev_questions.REGISTRY)


class TestEveryAskedSetHasItsPlan:
    def test_every_registered_set_asking_a_question_has_a_plan(self) -> None:
        """
        A plan lands no later than its set: a registered set with no plan, or
        a plan that does not cover each of its questions, fails here, so no
        answer is ever recorded with no plan in force. The probe is exempt,
        and the regime is the global plan's.
        """
        for name, question_set in _registered().items():
            plan = jev_prereg.set_plan(name, question_set.version)
            if name in WITHOUT_A_SET_PLAN:
                assert plan is None, name
                continue
            assert plan is not None, f"{name} v{question_set.version} has no plan"
            keys = [key for key, _ in question_set.questions]
            assert sorted(plan["questions"]) == sorted(keys), name
        assert jev_prereg.regime_plan()["baseline"], "the regime's rule is its plan's"

    def test_every_plan_is_of_a_registered_set(self) -> None:
        registered = {(qs.name, qs.version) for qs in _registered().values()}
        assert set(jev_prereg.SET_PLAN_VERSIONS) <= registered

    def test_the_check_bites(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A set registered with no plan is found by the test above."""
        monkeypatch.setattr(
            jev_prereg,
            "SET_PLAN_VERSIONS",
            MappingProxyType(
                {
                    key: value
                    for key, value in jev_prereg.SET_PLAN_VERSIONS.items()
                    if key != ("guardrail.card", 1)
                }
            ),
        )
        with pytest.raises(AssertionError, match="guardrail.card v1 has no plan"):
            self.test_every_registered_set_asking_a_question_has_a_plan()


#: R1's rule, written here as literals: a question with an acting class is
#: measured by that class's covered precision, any other by its covered
#: accuracy.
_STATISTIC_OF = {
    True: "covered_precision_of_the_acting_class",
    False: "covered_accuracy",
}


def _target_problems(plan: dict[str, Any]) -> list[str]:
    """How a plan's targets fall short of their statistics' floors, if they do."""
    problems = []
    for key, question in plan["questions"].items():
        statistic = _STATISTIC_OF[question["acting_class"] is not None]
        floor = jev_prereg.STATISTIC_FLOORS[statistic]
        if question["statistic"] != statistic:
            problems.append(f"{key} measures {question['statistic']}, not {statistic}")
        if question["bound"] != floor["bound"]:
            problems.append(f"{key} is bounded by {question['bound']}")
        if question["at_least"] < floor["at_least"]:
            problems.append(f"{key}'s target is below its statistic's floor")
    return problems


class TestTheTargets:
    def test_a_set_plan_may_raise_a_floor_never_lower_it(self) -> None:
        """
        R1: a question's statistic is its acting class's covered precision
        where it has one and its covered accuracy otherwise, read the same
        way as the floor — a Wilson lower bound at the gate level — and its
        target is at least the floor. Any lane arrives through a set plan
        alone, so no floor needs keeping here, outside the hash.
        """
        for name, question_set in _registered().items():
            plan = jev_prereg.set_plan(name, question_set.version)
            if plan is not None:
                assert _target_problems(plan) == [], name

    def test_the_target_check_bites(self) -> None:
        plan = jev_prereg.set_plan("guardrail.card", 1)
        assert plan is not None
        plan["questions"]["performance_claim"]["at_least"] = 0.85
        assert _target_problems(plan) == [
            "performance_claim's target is below its statistic's floor"
        ]
        plan = jev_prereg.set_plan("guardrail.card", 1)
        assert plan is not None
        plan["questions"]["performance_claim"]["statistic"] = "covered_accuracy"
        assert _target_problems(plan) == [
            "performance_claim measures covered_accuracy, not "
            "covered_precision_of_the_acting_class"
        ]
        plan = jev_prereg.set_plan("research.catalogue", 1)
        assert plan is not None
        plan["questions"]["mechanism"]["bound"] = "point_estimate"
        assert _target_problems(plan) == ["mechanism is bounded by point_estimate"]

    def test_the_design_targets(self) -> None:
        """Covered precision of at least 0.90 for the guardrails, covered
        accuracy of at least 0.80 for the research sets and, from phase D2,
        for the findings sets, and from phase D3 for the ops set (docs/09,
        section 3.4)."""
        expected = {
            "guardrail.injection": ("covered_precision_of_the_acting_class", 0.90),
            "guardrail.card": ("covered_precision_of_the_acting_class", 0.90),
            "research.catalogue": ("covered_accuracy", 0.80),
            "research.hypothesis": ("covered_accuracy", 0.80),
            "findings.owner": ("covered_accuracy", 0.80),
            "findings.severity": ("covered_accuracy", 0.80),
            "ops.job_error": ("covered_accuracy", 0.80),
        }
        assert {name for name, _ in jev_prereg.SET_PLAN_VERSIONS} == set(expected)
        for name, (statistic, at_least) in expected.items():
            plan = jev_prereg.set_plan(name, 1)
            assert plan is not None
            for question in plan["questions"].values():
                assert (question["statistic"], question["at_least"]) == (
                    statistic,
                    at_least,
                ), name

    def test_the_acting_class_is_an_answer_its_question_can_give(self) -> None:
        """
        A guardrail acts on ``true`` — a quarantine, a refusal — so its
        precision is measured on ``true``; a research answer acts on nothing.
        """
        for name, question_set in _registered().items():
            plan = jev_prereg.set_plan(name, question_set.version)
            if plan is None:
                continue
            for key, question in question_set.questions:
                acting = plan["questions"][key]["acting_class"]
                if question_set.lane == "guardrail":
                    assert question["type"] == "noul" and acting == "true", key
                else:
                    assert acting is None, key


class TestTheKeywordBaselinesAreWhatTheyName:
    def test_the_injection_baseline_is_the_code_screen_v1(self) -> None:
        """
        Its rules pinned by their hash: the plan names the code screen as it
        is, and a new version of the screen is a new plan.
        """
        from src.programme import web_sources

        plan = jev_prereg.set_plan("guardrail.injection", 1)
        assert plan is not None
        baseline = plan["questions"]["addressed_to_ai"]["keyword_baseline"]
        assert baseline == {
            "rule": "web_sources.code_screen",
            "version": web_sources.CODE_SCREEN_VERSION,
            "rules_sha256": web_sources.code_screen_sha256(),
            "true_when": "a rule fires",
            "reads": "excerpt",
        }
        assert baseline["rules_sha256"] == web_sources.GOLDEN_CODE_SCREEN_SHA256

    def test_the_card_baseline_is_the_claims_check(self) -> None:
        from src.programme import claims

        plan = jev_prereg.set_plan("guardrail.card", 1)
        assert plan is not None
        baseline = plan["questions"]["performance_claim"]["keyword_baseline"]
        assert baseline["rule"] == "claims.find_performance_claim"
        assert baseline["reads"] == "title"
        assert tuple(baseline["terms"]) == claims.PERFORMANCE_TERMS
        assert baseline["proximity"] == claims._PROXIMITY
        assert baseline["number"] == claims._NUMBER.pattern

    def test_the_research_sets_read_the_same_rules_from_their_own_text(
        self,
    ) -> None:
        catalogue = jev_prereg.set_plan("research.catalogue", 1)
        hypothesis = jev_prereg.set_plan("research.hypothesis", 1)
        assert catalogue is not None and hypothesis is not None
        for key in ("asset_class", "mechanism"):
            mine = dict(catalogue["questions"][key]["keyword_baseline"])
            theirs = dict(hypothesis["questions"][key]["keyword_baseline"])
            assert (mine.pop("reads"), theirs.pop("reads")) == ("excerpt", "title")
            assert mine == theirs


class TestTheFindingsBaseline:
    """
    Phase D2 (docs/09, section 3.4): the findings sets are measured against
    the value already recorded beside the title — ``raised_by`` for the owner,
    ``severity`` for the severity — of the earliest finding the programme's
    model wrote holding it, by ``opened_at`` then ``ref``. Data in each plan,
    hashed with it, so the rule an answer is scored by was registered before
    the answer.
    """

    @pytest.mark.parametrize(
        ("name", "key", "reads"),
        [
            ("findings.owner", "owning_role", "raised_by"),
            ("findings.severity", "severity", "severity"),
        ],
    )
    def test_it_reads_the_recorded_value(self, name: str, key: str, reads: str) -> None:
        plan = jev_prereg.set_plan(name, 1)
        assert plan is not None
        assert list(plan["questions"]) == [key]
        assert plan["questions"][key]["keyword_baseline"] == {
            "rule": "findings.recorded",
            "of": "the earliest finding holding the title",
            "origin": "model",
            "order": ["opened_at", "ref"],
            "exported_to_labellers": False,
            "reads": reads,
        }

    def test_the_two_plans_differ_by_what_they_read_alone(self) -> None:
        owner = jev_prereg.set_plan("findings.owner", 1)
        severity = jev_prereg.set_plan("findings.severity", 1)
        assert owner is not None and severity is not None
        a = dict(owner["questions"]["owning_role"]["keyword_baseline"])
        b = dict(severity["questions"]["severity"]["keyword_baseline"])
        assert (a.pop("reads"), b.pop("reads")) == ("raised_by", "severity")
        assert a == b
        assert owner["population"] == severity["population"]

    def test_the_population_is_every_model_written_finding_within_the_cap(
        self,
    ) -> None:
        """
        Any status, so the population labelled is the population asked about
        (docs/09, D24); the cap a copy of ``jev_questions``', which this
        module, loading the standard library alone, cannot import.
        """
        from src.programme import jev_questions

        plan = jev_prereg.set_plan("findings.owner", 1)
        assert plan is not None
        assert plan["population"] == {
            "table": "findings",
            "origin": "model",
            "status": "any",
            "title_chars": [1, jev_questions.FINDING_TITLE_MAX_CHARS],
            "subject": "finding_title",
            "address": "sha256 of the title as UTF-8",
        }
        subject = jev_questions.STATE_SUBJECT[jev_questions.FindingTitleState]
        assert subject == plan["population"]["subject"]

    def test_no_phase_c_plan_names_a_population(self) -> None:
        """
        So adding the findings plans, and from phase D3 the ops plan, each
        naming its population, moved no phase C plan's hash.
        """
        for name, version in jev_prereg.SET_PLAN_VERSIONS:
            plan = jev_prereg.set_plan(name, version)
            assert plan is not None
            names_one = name.startswith(("findings.", "ops."))
            assert ("population" in plan) is names_one, name


class TestTheKeywordFallback:
    """
    ``keyword_label`` takes the label a plan gives text no keyword is in, and
    each plan records it as ``"fallback"`` (docs/09, section 3.4): phase D3's
    ops plan names ``unclear``, its escape. Every phase C plan keeps
    ``insufficient_evidence``, so none of their hashes moved.
    """

    def test_the_c_plans_are_unchanged(self) -> None:
        for name in (
            "guardrail.injection",
            "research.catalogue",
            "research.hypothesis",
            "guardrail.card",
        ):
            released = RELEASED_SET_PLAN_HASHES[(name, 1, 1)]
            assert jev_prereg.set_plan_hash(name, 1) == released, name
        for name in ("research.catalogue", "research.hypothesis"):
            plan = jev_prereg.set_plan(name, 1)
            assert plan is not None
            for question in plan["questions"].values():
                assert question["keyword_baseline"]["fallback"] == (
                    jev_prereg.KEYWORD_FALLBACK
                )

    def test_the_fallback_is_the_label_of_text_no_keyword_is_in(self) -> None:
        rules = (("found", ("needle",)),)
        assert jev_prereg.keyword_label(rules, "a needle") == "found"
        assert jev_prereg.keyword_label(rules, "hay") == jev_prereg.KEYWORD_FALLBACK
        assert jev_prereg.keyword_label(rules, "hay", fallback="unclear") == "unclear"
        assert jev_prereg.keyword_label(rules, "a needle", fallback="unclear") == (
            "found"
        )


#: The card check's rule, ``claims.find_performance_claim``, written out here
#: as literals and read by hand, apart from the module: its terms, how far a
#: term may be from a number, and what a number is. The plan hashes the
#: module's constants (``jev_prereg.PERFORMANCE_CLAIM_BASELINE``); this copy
#: holds what the rule does with them, which no hash sees.
CLAIM_TERMS_AS_WRITTEN = (
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
)
CLAIM_REACH_AS_WRITTEN = 40


def _numbers_as_written(text: str) -> list[tuple[int, int]]:
    """
    Every number in ``text``, as spans, read left to right without overlap: a
    run of decimal digits, a minus before it if one is there, one decimal part
    after a point or a comma if digits follow it, and a percent sign after it
    if one is there.
    """
    spans: list[tuple[int, int]] = []
    i, n = 0, len(text)
    while i < n:
        start = i
        if text[i] == "-" and i + 1 < n and text[i + 1].isdecimal():
            i += 1
        if not text[i].isdecimal():
            i = start + 1
            continue
        while i < n and text[i].isdecimal():
            i += 1
        if i + 1 < n and text[i] in ".," and text[i + 1].isdecimal():
            i += 1
            while i < n and text[i].isdecimal():
                i += 1
        if i < n and text[i] == "%":
            i += 1
        spans.append((start, i))
    return spans


def _claim_as_written(text: str) -> str | None:
    """
    The first number whose surroundings — forty characters either side of it,
    in the lowercased text — hold a term anywhere, a longer word holding one
    included, as those surroundings of the text as written, stripped; or
    ``None``. Counted in the lowercased text, which is how the rule counts.
    """
    lowered = text.lower()
    for start, end in _numbers_as_written(lowered):
        before = max(0, start - CLAIM_REACH_AS_WRITTEN)
        near = lowered[before : end + CLAIM_REACH_AS_WRITTEN]
        if any(term in near for term in CLAIM_TERMS_AS_WRITTEN):
            return text[before : end + CLAIM_REACH_AS_WRITTEN].strip()
    return None


#: What the card baseline decides about each of these invented titles — a
#: claim found or not — as each plan version of ``guardrail.card`` registered
#: it, by plan version. A change to what the rule decides is a new plan
#: version with a row of its own here, and its hash appended to
#: ``RELEASED_SET_PLAN_HASHES``; re-recording a released row, the edit a
#: failing test invites, moves the baseline answers were already measured
#: against.
CARD_VERDICTS_AS_REGISTERED: dict[int, tuple[tuple[str, bool], ...]] = {
    1: (
        ("14% Annualised Returns From Invented Carry", True),
        ("Invented Carry Returns 14%", True),
        ("A Sharpe of 1.2 in Fictional Bond Futures", True),
        ("Drawdowns Under -3% in Made-Up Markets", True),
        ("Profitability of 2 Invented Signals", True),
        ("Unprofitable Carry Over 12 Imaginary Pairs", True),
        ("Alphabet Soup of 7 Invented Factors", True),
        ("Win Rate Near 60 in Fictional Pairs", True),
        ("PNL Of 3,5 On Invented Lots", True),
        ("Return" + "x" * 34 + "12", True),
        ("Return" + "x" * 35 + "12", False),
        ("12" + "x" * 34 + "return", True),
        ("12" + "x" * 35 + "return", False),
        ("In 1999" + "x" * 45 + " a Sharpe of 2", True),
        ("Carry in 12 Fictional Markets", False),
        ("Momentum Over 2026 and Beyond", False),
        ("Returns Without a Figure", False),
        ("Invented Value in Mid-Caps", False),
        ("--Seven Returns--", False),
    ),
}


class TestTheCardBaselineIsPinnedByWhatItDoes:
    """
    C7+C8's review: the card's plan hashed the claims check's terms, reach and
    number pattern, and nothing held how the check applies them, so a rule
    that read a term only before its number left the plan's hash golden and
    every test green, and a card answer recorded under plan version 1 would
    have been measured against a different baseline still calling itself
    version 1. The design's rule for every keyword baseline holds here too:
    tested against a copy written as literals. And its verdicts on invented
    titles are recorded under the plan version that registered them.
    """

    def test_the_copy_names_the_constants_the_plan_hashes(self) -> None:
        plan = jev_prereg.set_plan("guardrail.card", 1)
        assert plan is not None
        baseline = plan["questions"]["performance_claim"]["keyword_baseline"]
        assert tuple(baseline["terms"]) == CLAIM_TERMS_AS_WRITTEN
        assert baseline["proximity"] == CLAIM_REACH_AS_WRITTEN

    def test_the_check_is_the_copy_written_here(self) -> None:
        """
        A seeded corpus of invented titles built to sit on the rule's edges:
        a term before its number and after it, at the reach and one beyond,
        inside a longer word, in any case, with numbers negative, decimal by a
        point or a comma, in percent, run together, and in digits of other
        scripts, which the rule reads as digits.
        """
        from src.programme import claims

        rng = random.Random(29)
        words = [
            "Invented",
            "Carry",
            "Momentum",
            "in",
            "Fictional",
            "Bond",
            "Futures",
            "Imaginary",
            *CLAIM_TERMS_AS_WRITTEN,
            "Returnable",
            "Drawdowns",
            "Alphabet",
            "Profitability",
            "Unprofitable",
            "Outperformance",
            "Sharpening",
            "Hit Rates",
            "PnL",
            "İstanbul",
        ]
        numbers = [
            "12",
            "-3",
            "0.5",
            "1,5",
            "14%",
            "-2.75%",
            "2026",
            "1,234,567",
            "3-4",
            "--7",
            "12%%",
            "٣٤",
            "１２",
        ]
        fillers = ["x" * width for width in range(30, 45)]
        found = {"claim": 0, "none": 0}
        for _ in range(5_000):
            pieces = [
                rng.choice(rng.choice((words, words, numbers, fillers)))
                for _ in range(rng.randint(1, 6))
            ]
            title = rng.choice([" ", "-", ", ", ""]).join(pieces)
            title = rng.choice([title, title.title(), title.upper()])
            claim = claims.find_performance_claim(title)
            assert claim == _claim_as_written(title), title
            found["claim" if claim is not None else "none"] += 1
        assert min(found.values()) > 500, found

    @pytest.mark.parametrize(
        ("title", "verdict"),
        CARD_VERDICTS_AS_REGISTERED[
            jev_prereg.SET_PLAN_VERSIONS[("guardrail.card", 1)]
        ],
    )
    def test_it_decides_as_its_plan_version_registered(
        self, title: str, verdict: bool
    ) -> None:
        from src.programme import claims

        assert (claims.find_performance_claim(title) is not None) is verdict
        assert (_claim_as_written(title) is not None) is verdict

    def test_every_card_plan_version_has_its_verdicts(self) -> None:
        version = jev_prereg.SET_PLAN_VERSIONS[("guardrail.card", 1)]
        released = {
            p for (n, v, p) in RELEASED_SET_PLAN_HASHES if n == "guardrail.card"
        }
        assert version in CARD_VERDICTS_AS_REGISTERED
        assert set(CARD_VERDICTS_AS_REGISTERED) == released


#: The design's ordered keyword rules (design part C7), written here as
#: literals, apart from the module: the module's data is checked against
#: these, not against itself. "Crypto words" are the build's list;
#: ``diversif*`` is the design's stem.
ASSET_CLASS_RULES_AS_WRITTEN = (
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
MECHANISM_RULES_AS_WRITTEN = (
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

#: Every keyword's second form, written out: its last word that is not "of"
#: in the plural, by the rule the module states — a consonant and ``y``
#: become ``ies``; ``s``, ``x``, ``z``, ``ch`` or ``sh`` takes ``es``;
#: anything else ``s`` — for the whole list, so a rule the data broke would
#: show here. The first build's docs claimed a plural rule its data kept for
#: five keywords.
PLURALS = {
    "crypto": "cryptos",
    "cryptocurrency": "cryptocurrencies",
    "bitcoin": "bitcoins",
    "ethereum": "ethereums",
    "blockchain": "blockchains",
    "bond": "bonds",
    "treasury": "treasuries",
    "yield": "yields",
    "fixed income": "fixed incomes",
    "sovereign": "sovereigns",
    "credit": "credits",
    "term premium": "term premiums",
    "interest rate": "interest rates",
    "commodity": "commodities",
    "gold": "golds",
    "silver": "silvers",
    "oil": "oils",
    "crude": "crudes",
    "metal": "metals",
    "grain": "grains",
    "currency": "currencies",
    "foreign exchange": "foreign exchanges",
    "fx": "fxes",
    "carry": "carries",
    "option": "options",
    "volatility": "volatilities",
    "vix": "vixes",
    "covered call": "covered calls",
    "derivative": "derivatives",
    "multi-asset": "multi-assets",
    "asset allocation": "asset allocations",
    "risk parity": "risk parities",
    "tactical": "tacticals",
    "portfolio of": "portfolios of",
    "equity": "equities",
    "stock": "stocks",
    "share": "shares",
    "company": "companies",
    "capm": "capms",
    "size effect": "size effects",
    "momentum": "momentums",
    "trend": "trends",
    "reversal": "reversals",
    "mean reversion": "mean reversions",
    "overreaction": "overreactions",
    "value": "values",
    "book-to-market": "book-to-markets",
    "size": "sizes",
    "small": "smalls",
    "low volatility": "low volatilities",
    "low beta": "low betas",
    "betting against beta": "betting against betas",
    "season": "seasons",
    "calendar": "calendars",
    "month": "months",
    "weekday": "weekdays",
    "holiday": "holidays",
    "auction": "auctions",
    "earnings": "earningses",
    "announcement": "announcements",
    "intervention": "interventions",
    "media": "medias",
    "tone": "tones",
    "sentiment": "sentiments",
    "news": "newses",
    "attention": "attentions",
    "optimisation": "optimisations",
    "optimization": "optimizations",
    "allocation": "allocations",
}

_KEYWORDS = sorted(
    {
        keyword
        for rules in (ASSET_CLASS_RULES_AS_WRITTEN, MECHANISM_RULES_AS_WRITTEN)
        for _, keywords in rules
        for keyword in keywords
    }
)


def _holds(keyword: str, text: str) -> bool:
    """
    Whether ``text`` holds ``keyword``, worked out again here with a plain
    scan of whole words and the plural table above, apart from the module.
    """
    import re

    words = [w for w in re.split(r"[^\w]+|_", text.casefold()) if w]
    if keyword.endswith("*"):
        return any(w.startswith(keyword[:-1]) for w in words)
    for form in (keyword, PLURALS[keyword]):
        parts = re.split(r"[ -]", form)
        for i in range(len(words) - len(parts) + 1):
            if words[i : i + len(parts)] == parts:
                return True
    return False


def _label(rules: Any, text: str) -> str:
    for name, keywords in rules:
        if any(_holds(keyword, text) for keyword in keywords):
            return name
    return "insufficient_evidence"


#: Two labels the cases below name often.
_MOMENTUM = "trend_or_momentum"
_NO_KEYWORD = "insufficient_evidence"


class TestTheKeywordRules:
    def test_the_rules_are_the_designs_as_written(self) -> None:
        assert jev_prereg.ASSET_CLASS_KEYWORDS == ASSET_CLASS_RULES_AS_WRITTEN
        assert jev_prereg.MECHANISM_KEYWORDS == MECHANISM_RULES_AS_WRITTEN
        assert jev_prereg.KEYWORD_FALLBACK == "insufficient_evidence"

    def test_each_rules_labels_are_its_questions_options(self) -> None:
        """
        In the catalogue's own vocabulary, so a baseline's answer and Jev's
        are compared option for option; the fallback is the escape, and no
        rule answers ``other_mechanism``.
        """
        from src.programme.jev_questions import (
            ASSET_CLASS_CRITERIA,
            MECHANISM_CRITERIA,
            RESEARCH_CATALOGUE,
        )

        escapes = RESEARCH_CATALOGUE.escape_options
        for rules, criteria, key in (
            (jev_prereg.ASSET_CLASS_KEYWORDS, ASSET_CLASS_CRITERIA, "asset_class"),
            (jev_prereg.MECHANISM_KEYWORDS, MECHANISM_CRITERIA, "mechanism"),
        ):
            labels = [label for label, _ in rules]
            assert len(labels) == len(set(labels))
            assert set(labels) <= set(criteria) - {escapes[key], "other_mechanism"}
            assert jev_prereg.KEYWORD_FALLBACK == escapes[key]
        asset_options = set(ASSET_CLASS_CRITERIA) - {escapes["asset_class"]}
        assert {label for label, _ in jev_prereg.ASSET_CLASS_KEYWORDS} == asset_options

    def test_every_keyword_is_lowercase_and_spelt_plainly(self) -> None:
        for keyword in _KEYWORDS:
            assert keyword == keyword.casefold().strip(), keyword
            assert all(
                ch.isalpha() or ch in " -" for ch in keyword.removesuffix("*")
            ), keyword

    @pytest.mark.parametrize("keyword", _KEYWORDS)
    def test_the_plural_is_formed_by_the_stated_rule(self, keyword: str) -> None:
        if keyword.endswith("*"):
            assert jev_prereg.keyword_forms(keyword) == (keyword,)
            return
        assert jev_prereg.keyword_forms(keyword) == (keyword, PLURALS[keyword])

    def test_the_table_covers_the_whole_list(self) -> None:
        assert set(PLURALS) == {k for k in _KEYWORDS if not k.endswith("*")}
        assert [k for k in _KEYWORDS if k.endswith("*")] == ["diversif*"]

    @pytest.mark.parametrize("keyword", _KEYWORDS)
    def test_every_form_is_found_as_whole_words(self, keyword: str) -> None:
        """
        Each form in a title, capitalised, its words apart by a space or a
        hyphen, is found; inside a longer word it is not.
        """
        rules = (("found", (keyword,)),)
        for form in jev_prereg.keyword_forms(keyword):
            stem = form.removesuffix("*")
            written = stem.title()
            spellings = (written, written.replace(" ", "-"), written.replace("-", " "))
            for spelling in spellings:
                title = f"An Invented {spelling} Study"
                assert jev_prereg.keyword_label(rules, title) == "found", title
            inside = f"Xq{stem}"
            assert jev_prereg.keyword_label(rules, inside) != "found", inside
            if not form.endswith("*"):
                after = f"{stem}qx"
                assert jev_prereg.keyword_label(rules, after) != "found", after

    def test_the_stem_is_found_in_any_ending(self) -> None:
        rules = (("allocation", ("diversif*",)),)
        for title in ("Diversification Premia", "A Diversified Book", "Diversifying"):
            assert jev_prereg.keyword_label(rules, title) == "allocation", title
        assert jev_prereg.keyword_label(rules, "Undiversified") != "allocation"

    def test_turmoil_in_the_soil_holds_no_oil(self) -> None:
        """
        Whole words, at both ends: the first build's matching read "oil" in
        "Turmoil" and "Soil".
        """
        asset = jev_prereg.ASSET_CLASS_KEYWORDS
        assert jev_prereg.keyword_label(asset, "Turmoil in the Soil") == (
            "insufficient_evidence"
        )
        assert jev_prereg.keyword_label(asset, "Oil after the Turmoil") == (
            "commodities"
        )

    @pytest.mark.parametrize(
        ("title", "asset_class", "mechanism"),
        [
            ("Momentum in Invented Commodity Futures", "commodities", _MOMENTUM),
            ("Commodities Momentum, Invented", "commodities", _MOMENTUM),
            ("Bitcoin Overnight Drift", "cryptocurrencies", _NO_KEYWORD),
            ("Yield Curve Carry in Invented Markets", "bonds", "carry"),
            ("Fixed-Income Value, Invented", "bonds", "value"),
            ("Multi Asset Trend Following", "multi_asset", _MOMENTUM),
            ("Portfolios of Risk Parity", "multi_asset", "allocation"),
            ("Diversification Without Forecasts", _NO_KEYWORD, "allocation"),
            ("Small Firms in an Invented Market", _NO_KEYWORD, "size"),
            ("Pre-Holiday Drift", _NO_KEYWORD, "seasonality"),
            ("FX Carry Revisited", "currencies", "carry"),
            ("Betting Against Beta, Again", _NO_KEYWORD, "low_risk"),
            ("Goldman Rotation", _NO_KEYWORD, _NO_KEYWORD),
            ("Seasonality in Stock Returns", "equities", _NO_KEYWORD),
        ],
    )
    def test_the_first_rule_that_holds_gives_the_label(
        self, title: str, asset_class: str, mechanism: str
    ) -> None:
        """
        Order decides: a title naming a bond's yield and a currency's carry is
        a bond title, since bonds come first. And whole words decide too:
        "Goldman" holds no gold, and "Seasonality" no season.
        """
        assert jev_prereg.keyword_label(jev_prereg.ASSET_CLASS_KEYWORDS, title) == (
            asset_class
        )
        assert jev_prereg.keyword_label(jev_prereg.MECHANISM_KEYWORDS, title) == (
            mechanism
        )

    def test_it_is_pure_and_deterministic(self) -> None:
        """The text alone decides: the same text, the same label, in any order."""
        rng = random.Random(7)
        words = [k for k in _KEYWORDS if not k.endswith("*")] + ["invented", "drift"]
        titles = [
            " ".join(rng.choice(words) for _ in range(rng.randint(1, 6)))
            for _ in range(500)
        ]
        rules = jev_prereg.MECHANISM_KEYWORDS
        first = [jev_prereg.keyword_label(rules, title) for title in titles]
        shuffled = list(enumerate(titles))
        rng.shuffle(shuffled)
        for index, title in shuffled:
            assert jev_prereg.keyword_label(rules, title) == first[index]

    def test_the_rule_is_read_as_a_copy_written_here_reads_it(self) -> None:
        """
        The label worked out again here, from the literal rules, the plural
        table and a plain scan of whole words, agrees with the module's on a
        seeded corpus of invented titles built from the keywords themselves,
        their plurals, and words that hold a keyword inside them.
        """
        rng = random.Random(11)
        words = [k for k in _KEYWORDS if not k.endswith("*")]
        words += [PLURALS[k] for k in words]
        words += ["Diversification", "Turmoil", "Soil", "Goldman", "Seasonality"]
        for _ in range(2_000):
            title = rng.choice([" ", "-", ", "]).join(
                rng.choice(words).title() for _ in range(rng.randint(1, 5))
            )
            for rules in (ASSET_CLASS_RULES_AS_WRITTEN, MECHANISM_RULES_AS_WRITTEN):
                assert jev_prereg.keyword_label(rules, title) == _label(rules, title), (
                    title
                )


# ---------------------------------------------------------------------------
# Phase D3: the ops set's plan
# ---------------------------------------------------------------------------

#: The ops rule, written out here as literals and read by hand, apart from
#: the module: the plan hashes the module's constant, and this copy holds the
#: words a reviewer read (docs/09, section 3.4).
OPS_RULES_AS_WRITTEN = (
    ("credentials", ("permission", "authentication")),
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

#: design section 3.4's draft of the ops rule, as literals: what the rule
#: above was cut from, by the evidence below.
OPS_KEYWORDS_DRAFTED = (
    ("rate_limit", ("http_429", "rate limit", "throttled", "too many requests")),
    (
        "credentials",
        (
            "http_401",
            "http_403",
            "unauthorized",
            "unauthorised",
            "forbidden",
            "credential",
            "password",
            "permission",
            "authentication",
        ),
    ),
    (
        "database",
        ("deadlock", "constraint", "violates", "duplicate key", "could not serialize"),
    ),
    ("resource_limit", ("memory", "disk", "exhausted", "no space")),
    (
        "network",
        (
            "connection",
            "refused",
            "reset",
            "timeout",
            "timed out",
            "unreachable",
            "dns",
            "socket",
            "cannot connect",
        ),
    ),
    (
        "vendor_service",
        (
            "http_500",
            "http_502",
            "http_503",
            "http_504",
            "http_529",
            "unavailable",
            "outage",
            "empty response",
        ),
    ),
    (
        "code_defect",
        (
            "has no attribute",
            "not subscriptable",
            "unsupported operand",
            "out of range",
            "division by zero",
            "is not defined",
            "not callable",
            "not iterable",
            "unexpected keyword argument",
            "required positional argument",
        ),
    ),
    (
        "data_missing",
        ("missing", "no data", "no rows", "delisted", "empty", "not found"),
    ),
    ("data_invalid", ("malformed", "invalid", "nan", "inconsistent")),
    ("configuration", ("parameter", "setting", "configuration", "unknown")),
)

#: What the ops rule says of invented subject texts, recorded under the set
#: plan version that registered it: a change to what the rule decides fails
#: here until the plan's version is bumped and a row appended.
_OPS_VERDICTS_OF_PLAN_1: tuple[tuple[str, str], ...] = (
    ("ingest_bars: errno [number] connection refused", "network"),
    ("backtest: errno [number] connection reset by peer", "network"),
    (
        "backtest: [address] missing [number] required positional argument [quoted]",
        "code_defect",
    ),
    (
        "walkforward: [address] got an unexpected keyword argument missing",
        "code_defect",
    ),
    (
        "walkforward: duplicate key value violates unique constraint [quoted]",
        "database",
    ),
    ("backtest: permission denied for table [word]", "credentials"),
    ("backtest: permission denied connection refused", "credentials"),
    (
        "ingest_reference_bars: errno [number] no space left on device",
        "resource_limit",
    ),
    ("backtest: errno [number] resource temporarily unavailable", "vendor_service"),
    ("backtest: query returned no rows", "data_missing"),
    ("backtest: cannot [word] from an empty sequence", "data_missing"),
    ("backtest: invalid input syntax for type integer [quoted]", "data_invalid"),
    ("backtest: cannot convert float nan to integer", "data_invalid"),
    ("backtest: unrecognized configuration parameter [quoted]", "configuration"),
    ("ingest_bars: connection [word] missing", "network"),
    ("backtest: [word] [word] [word]", "unclear"),
    ("ingest_reference_bars: ", "unclear"),
)

OPS_VERDICTS_AS_REGISTERED: dict[int, tuple[tuple[str, str], ...]] = {
    1: _OPS_VERDICTS_OF_PLAN_1,
    # Plan version 2 moved the redactor it names and not one keyword (D3's
    # review), so its verdicts are version 1's.
    2: _OPS_VERDICTS_OF_PLAN_1,
}


def _raised(fn: Callable[[], object]) -> str:
    """The message ``fn`` raises."""
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - the message is the evidence
        return str(exc)
    raise AssertionError("raised nothing")


def _missing_positional(a: object) -> object:
    return a


def _os_error(name: str) -> str:
    """An operating system error as Python raises it: errno and strerror."""
    import errno
    import os

    code = getattr(errno, name)
    return str(OSError(code, os.strerror(code)))


def _postgres(class_name: str, message: str) -> str:
    """PostgreSQL's message as asyncpg's own class for it raises it."""
    import asyncpg

    cls = getattr(asyncpg.exceptions, class_name)
    return str(cls(message))


def _evidence() -> tuple[tuple[str, str], ...]:
    """
    The evidence corpus (docs/09, D-HMB-10): real messages a triaged job can
    record as they stand — none is wrapped by a data source, which places
    every vendor failure under a shape of its own — each named by where it
    comes from. A builtin's and numpy's and pandas' are triggered here; an
    operating system's is its errno with the platform's strerror;
    PostgreSQL's is the server's text as asyncpg's class for its SQLSTATE
    raises it, the asyncpg the job uses.
    """
    import asyncpg
    import numpy
    import pandas

    pg = f"PostgreSQL, through asyncpg {asyncpg.__version__}"
    return (
        ("builtins: AttributeError", _raised(lambda: int.no_such_attribute)),
        ("builtins: TypeError", _raised(lambda: 1 + "a")),
        ("builtins: IndexError", _raised(lambda: [][0])),
        ("builtins: ZeroDivisionError", _raised(lambda: 1.0 / 0)),
        ("builtins: TypeError", _raised(lambda: 1 in 3)),
        ("builtins: TypeError", _raised(lambda: _missing_positional(1, b=2))),
        ("builtins: TypeError", _raised(lambda: _missing_positional())),
        ("builtins: ValueError", _raised(lambda: int("abc"))),
        ("builtins: ValueError", _raised(lambda: int(float("nan")))),
        ("random: IndexError", _raised(lambda: random.choice([]))),
        (
            f"numpy {numpy.__version__}",
            _raised(lambda: numpy.array([1.0, [1, 2]], dtype=float)),
        ),
        (f"pandas {pandas.__version__}", _raised(lambda: pandas.Timestamp("xyzzy"))),
        ("os: ECONNREFUSED", _os_error("ECONNREFUSED")),
        ("os: ECONNRESET", _os_error("ECONNRESET")),
        ("os: ETIMEDOUT", _os_error("ETIMEDOUT")),
        ("os: ENETUNREACH", _os_error("ENETUNREACH")),
        ("os: ENOSPC", _os_error("ENOSPC")),
        ("os: ENOMEM", _os_error("ENOMEM")),
        ("os: EDQUOT", _os_error("EDQUOT")),
        ("os: ENOTSOCK", _os_error("ENOTSOCK")),
        ("os: EDEADLK", _os_error("EDEADLK")),
        ("os: EACCES", _os_error("EACCES")),
        ("os: EAGAIN", _os_error("EAGAIN")),
        (
            pg,
            _postgres(
                "UniqueViolationError",
                'duplicate key value violates unique constraint "jobs_dedupe_key"',
            ),
        ),
        (
            pg,
            _postgres(
                "SerializationError",
                "could not serialize access due to concurrent update",
            ),
        ),
        (
            pg,
            _postgres(
                "QueryCanceledError", "canceling statement due to statement timeout"
            ),
        ),
        (
            pg,
            _postgres("InsufficientPrivilegeError", "permission denied for table jobs"),
        ),
        (
            pg,
            _postgres(
                "InvalidAuthorizationSpecificationError",
                'Peer authentication failed for user "trader"',
            ),
        ),
        (
            pg,
            _postgres(
                "InvalidTextRepresentationError",
                'invalid input syntax for type integer: "abc"',
            ),
        ),
        (
            pg,
            _postgres("InvalidTextRepresentationError", 'malformed array literal: "x"'),
        ),
        (pg, _postgres("NoDataFoundError", "query returned no rows")),
        (
            pg,
            _postgres(
                "UndefinedObjectError", 'unrecognized configuration parameter "x"'
            ),
        ),
        (
            pg,
            _postgres(
                "DiskFullError",
                'could not extend file "base/1/2": No space left on device',
            ),
        ),
        (
            pg,
            _postgres(
                "ConnectionDoesNotExistError",
                "connection was closed in the middle of operation",
            ),
        ),
    )


def _subject_text(kind: str, message: str) -> str | None:
    """
    The subject text the planner would send for a job of ``kind`` failing
    with ``message``, or ``None`` where code places it or its skeleton is too
    short to ask about (``jev_chips.residue_skeleton``).
    """
    from src.programme import jev_chips, jev_questions

    tokens = jev_chips.residue_skeleton(kind, message)
    if tokens is None:
        return None
    state = jev_questions.JobErrorState(job_kind=kind, error=tokens)
    return jev_questions.job_error_text(state)


class TestTheOpsKeywords:
    """
    The ops baseline (docs/09, section 3.4): pinned by what it says, and every
    keyword one a message this system can send produces.
    """

    def test_held_to_literals_and_to_verdicts(self) -> None:
        assert jev_prereg.OPS_KEYWORDS == OPS_RULES_AS_WRITTEN
        assert jev_prereg.OPS_KEYWORD_FALLBACK == "unclear"
        version = jev_prereg.SET_PLAN_VERSIONS[("ops.job_error", 1)]
        for text, label in OPS_VERDICTS_AS_REGISTERED[version]:
            assert (
                jev_prereg.keyword_label(
                    jev_prereg.OPS_KEYWORDS, text, fallback="unclear"
                )
                == label
            ), text

    def test_the_labels_are_code_causes_and_the_fallback_the_escape(self) -> None:
        from src.programme import jev_chips, jev_questions

        labels = [label for label, _ in jev_prereg.OPS_KEYWORDS]
        assert len(labels) == len(set(labels))
        assert set(labels) <= set(jev_chips.CAUSES)
        assert labels.index("code_defect") < labels.index("data_missing")
        ops = jev_questions.REGISTRY["ops.job_error"]
        assert ops.escape_options == {"cause": jev_prereg.OPS_KEYWORD_FALLBACK}

    def test_every_evidence_message_is_one_jev_would_be_asked_about(self) -> None:
        """
        Each message of the corpus is residue under every triaged kind, and
        its skeleton admissible: evidence the redactor would send.
        """
        from src.programme import jev_redact

        for source, message in _evidence():
            for kind in jev_redact.TRIAGED_KINDS:
                assert _subject_text(kind, message) is not None, (source, message)

    def test_every_keyword_is_produced(self) -> None:
        """
        Each keyword is found, by ``keyword_label``'s own matcher, in the
        subject text of a corpus message code leaves to Jev (docs/09,
        D-HMB-10): a keyword nothing produces could never fire, and would
        read as a rule it is not.
        """
        texts = [
            text
            for _, message in _evidence()
            if (text := _subject_text("backtest", message)) is not None
        ]
        for _, keywords in jev_prereg.OPS_KEYWORDS:
            for keyword in keywords:
                pattern = jev_prereg._keyword_pattern(keyword)
                assert any(pattern.search(t.casefold()) for t in texts), keyword

    def test_the_check_bites(self) -> None:
        """A keyword only an HTTP status could produce is found in no text."""
        texts = [
            text
            for _, message in _evidence()
            if (text := _subject_text("backtest", message)) is not None
        ]
        for keyword in ("http_429", "rate limit", "throttled", "forbidden"):
            pattern = jev_prereg._keyword_pattern(keyword)
            assert not any(pattern.search(t.casefold()) for t in texts), keyword

    def test_the_rule_is_the_drafts_less_what_no_message_produces(self) -> None:
        """
        The rule is design section 3.4's draft cut, and only cut: its labels
        in the draft's order, each label's keywords the draft's in the draft's
        order, and every keyword the draft held that the rule dropped found in
        no subject text of the evidence — so nothing was dropped that a
        message this system records could have fired, and nothing added that
        the draft did not hold.
        """
        kept = {keyword for _, keywords in OPS_RULES_AS_WRITTEN for keyword in keywords}
        drafted = dict(OPS_KEYWORDS_DRAFTED)
        order = [label for label, _ in OPS_KEYWORDS_DRAFTED]
        labels = [label for label, _ in jev_prereg.OPS_KEYWORDS]
        assert labels == [label for label in order if label in labels]
        for label, keywords in jev_prereg.OPS_KEYWORDS:
            assert list(keywords) == [k for k in drafted[label] if k in keywords]
        texts = [
            text
            for _, message in _evidence()
            for kind in ("backtest", "ingest_bars")
            if (text := _subject_text(kind, message)) is not None
        ]
        dropped = [
            keyword
            for _, keywords in OPS_KEYWORDS_DRAFTED
            for keyword in keywords
            if keyword not in kept
        ]
        assert "rate limit" in dropped and "sqlstate" not in kept
        for keyword in dropped:
            pattern = jev_prereg._keyword_pattern(keyword)
            assert not any(pattern.search(t.casefold()) for t in texts), keyword

    def test_no_keyword_matches_a_job_kind(self) -> None:
        """
        The subject text opens with the job's kind, and ``keyword_label``
        reads across an underscore, so no keyword may match a kind alone:
        ``ingest_bars`` would otherwise answer for ``bars``.
        """
        from src.programme import jev_redact

        for kind in jev_redact.TRIAGED_KINDS:
            for _, keywords in jev_prereg.OPS_KEYWORDS:
                for keyword in keywords:
                    assert not jev_prereg._keyword_pattern(keyword).search(kind), (
                        keyword,
                        kind,
                    )
            assert (
                jev_prereg.keyword_label(
                    jev_prereg.OPS_KEYWORDS, f"{kind}: ", fallback="unclear"
                )
                == "unclear"
            )


class TestTheOpsPlan:
    """
    The plan names the rule it reads, the population it is asked about and
    the versions of the code that decide it (docs/09, section 3.4).
    """

    def test_the_baseline_is_the_keyword_rule_on_the_subject_text(self) -> None:
        plan = jev_prereg.set_plan("ops.job_error", 1)
        assert plan is not None
        assert list(plan["questions"]) == ["cause"]
        question = plan["questions"]["cause"]
        assert question["acting_class"] is None
        assert question["statistic"] == "covered_accuracy"
        assert question["at_least"] == 0.80
        assert question["keyword_baseline"] == {
            "rule": "jev_prereg.keyword_label",
            "matcher": jev_prereg.KEYWORD_MATCHER,
            "reads": "job_error_text",
            "rules": [[label, list(words)] for label, words in OPS_RULES_AS_WRITTEN],
            "fallback": "unclear",
        }

    def test_the_population_copies_are_the_codes_own(self) -> None:
        """
        This module loads the standard library alone, so the population holds
        copies — the triaged kinds, the redactor's and the shapes' versions
        and hashes, the minimum content — each held here to its original, so
        a moved redactor or table is a moved plan.
        """
        from src.programme import jev_chips, jev_questions, jev_redact

        population = jev_prereg.OPS_POPULATION
        assert population["kinds"] == jev_redact.TRIAGED_KINDS
        assert dict(population["redactor"]) == {
            "rule": "jev_redact.skeleton",
            "version": jev_redact.REDACTOR_VERSION,
            "sha256": jev_redact.redactor_sha256(),
        }
        assert dict(population["left_to_jev_by"]) == {
            "rule": "jev_chips.code_cause",
            "version": jev_chips.SHAPES_VERSION,
            "sha256": jev_chips.shapes_sha256(),
        }
        assert population["min_content_tokens"] == jev_redact.MIN_CONTENT_TOKENS
        assert (
            population["subject"]
            == (jev_questions.STATE_SUBJECT[jev_questions.JobErrorState])
        )
        assert population["status"] == "failed"
        plan = jev_prereg.set_plan("ops.job_error", 1)
        assert plan is not None
        assert plan["population"]["kinds"] == list(jev_redact.TRIAGED_KINDS)
