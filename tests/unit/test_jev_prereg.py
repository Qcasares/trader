"""
The analysis is registered before the answers it analyses (docs/08, phase C,
I15).

``src/programme/jev_prereg.py`` holds every choice the forward report and the
harness will make — the split, the size floors, the confidence levels, the
flip limits, the re-ask sample and the rule Jev's regime is compared with — as
data, hashed. An analysis chosen after the data is a search, and a search
finds something; these tests are what make the choice unrevisable:

* the plan hashes to its golden, and every version to
  :data:`RELEASED_PLAN_HASHES`, an append-only history kept here, apart from
  the plan, so re-recording the golden after an edit still fails;
* every constant of the plan is in the hash, so a number cannot move without
  moving it;
* the functions of the plan — the split, the re-ask strata, the baseline rule —
  are checked against copies written here independently, with their numbers as
  literals, so a changed formula fails even where its constants did not move;
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
from datetime import timedelta
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

#: Every released plan's hash, by version. A version bump appends a row; no row
#: is ever edited or removed. The module's ``GOLDEN_PLAN_HASH`` sits beside the
#: plan, so re-recording it is exactly the edit a developer makes when the hash
#: test fails; this table is history, and editing a released row is an edit to
#: it that a reviewer sees for what it is: an analysis moved after it was
#: registered. Version 1 is the agent's default plan, the baseline rule and the
#: sleeves included (docs/08, phase C, C4). Its row was re-pinned once, in C4's
#: review, before the plan merged and before any answer existed: the research
#: target had been registered without the Wilson bound the design's metric
#: definition requires (``TestTheLaneTargets``).
RELEASED_PLAN_HASHES: dict[int, str] = {
    1: "f744c2d88bded050e7b1b0fb946c9e29b502264d55ee6ac7c6a68b182daf7caf",
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
        line = "PLAN_VERSION = 1"
        assert source.count(line) == 1
        variant = _execute_variant(
            monkeypatch, source.replace(line, "PLAN_VERSION = 2")
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


#: A different value for every constant of the plan. A constant added to the
#: module's ``__all__`` must be added here too, and then fails
#: :meth:`TestEveryConstantIsHashed.test_moving_it_moves_the_hash` unless
#: ``global_plan`` carries it: a choice outside the hash is a choice nobody
#: registered.
_MOVED: dict[str, Any] = {
    "PLAN_VERSION": 2,
    "DEV_SPLIT_TENTHS": 4,
    "MIN_TEST_ITEMS": 201,
    "MIN_DEV_ITEMS": 101,
    "MIN_COVERED": 31,
    "MARGIN_GRID": jev_prereg.MARGIN_GRID[:-1],
    "LANE_TARGETS": MappingProxyType(
        {
            **jev_prereg.LANE_TARGETS,
            "research": {"statistic": "covered_accuracy", "at_least": 0.75},
        }
    ),
    "REPORT_CI": 0.90,
    "GATE_CI": 0.99,
    "GATE_FAMILY": 11,
    "BOOTSTRAP_RESAMPLES": 1_000,
    "BOOTSTRAP_SEED_RULE": "int(dataset_sha256[:8], 16)",
    "CALIBRATION_BINS": 5,
    "TOO_FEW_PER_CLASS": 11,
    "MAX_FLIP_RATE": 0.06,
    "MAX_FLIP_RATE_NEAR_THRESHOLD": 0.11,
    "MIN_FLIP_PAIRS": 31,
    "NEAR_THRESHOLD": 0.11,
    "REASK_UNIFORM_MODULUS": 21,
    "REASK_LOW_MARGIN": 0.21,
    "REASKS_PER_DAY": 11,
    "REASK_AFTER": timedelta(hours=25),
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
        "KEYWORD_FALLBACK",
        "KEYWORD_MATCHER",
        "MECHANISM_KEYWORDS",
        "PERFORMANCE_CLAIM_BASELINE",
        "SET_PLAN_VERSIONS",
        "SET_TARGETS",
    }
)

#: The upper-case names in ``__all__`` that are not choices of the global plan:
#: ``ANY_OF`` is the rule's own syntax, the goldens are hashes, and the set
#: plans' choices are held by their own test below.
_NOT_CHOICES = frozenset({"ANY_OF", "GOLDEN_PLAN_HASH", "GOLDEN_SET_PLAN_HASHES"}) | (
    _SET_PLAN_CHOICES
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
        assert _MOVED[name] != getattr(jev_prereg, name)
        monkeypatch.setattr(jev_prereg, name, _MOVED[name])
        assert jev_prereg.plan_hash() != before

    def test_the_order_of_the_rules_lines_is_part_of_the_plan(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        First match wins, so the same lines in another order are a different
        rule: the hash keeps a sequence's order and sorts only a mapping's
        keys. The move above is exactly a reordering.
        """
        moved = _MOVED["REGIME_BASELINE_RULE"]
        assert sorted(moved, key=lambda line: line[0]) == sorted(
            jev_prereg.REGIME_BASELINE_RULE, key=lambda line: line[0]
        )
        before = jev_prereg.plan_hash()
        monkeypatch.setattr(jev_prereg, "REGIME_BASELINE_RULE", moved)
        assert jev_prereg.plan_hash() != before

    def test_nothing_in_the_plan_can_be_changed_in_place(self) -> None:
        """
        A mapping of the plan is read-only, so the hash computed at the start
        of a report is still the plan's at its end.
        """
        with pytest.raises(TypeError):
            jev_prereg.LANE_TARGETS["research"] = {}  # type: ignore[index]
        with pytest.raises(TypeError):
            jev_prereg.LANE_TARGETS["research"]["at_least"] = 0.5  # type: ignore[index]
        with pytest.raises(TypeError):
            jev_prereg.REGIME_SLEEVES["bonds"] = "TLT"  # type: ignore[index]
        risk_off = jev_prereg.REGIME_BASELINE_RULE[0][1]
        with pytest.raises(TypeError):
            risk_off["equities.trend"] = ("near",)  # type: ignore[index]
        with pytest.raises(TypeError):
            risk_off[jev_prereg.ANY_OF][0]["equities.drawdown"] = ()  # type: ignore[index]


class TestTheLaneTargets:
    """
    The design's binding metric definition (docs/08, phase C, design section
    10.1): a threshold is the smallest margin with at least ``MIN_COVERED``
    covered items whose target's **Wilson lower bound at ``GATE_CI``** meets
    the target — for every lane. A point estimate is not a target met.
    """

    def test_every_lane_target_is_a_wilson_lower_bound_at_the_gate_level(
        self,
    ) -> None:
        for lane, target in jev_prereg.LANE_TARGETS.items():
            assert target.get("bound") == "wilson_lower_at_gate_ci", (
                f"the {lane} target is registered as a bare point estimate: "
                f"{dict(target)}"
            )

    def test_a_point_estimate_at_the_target_is_far_from_meeting_it(self) -> None:
        """
        Why the bound matters, in the plan's own numbers: 24 of the 30 covered
        items a threshold needs is a covered accuracy of 0.80, exactly the
        research target, and its lower bound at the gate level is 0.57.
        """
        from src.programme import jev_stats

        target = jev_prereg.LANE_TARGETS["research"]["at_least"]
        n = jev_prereg.MIN_COVERED
        k = round(target * n)
        assert k / n == pytest.approx(target)
        bounds = jev_stats.wilson(k, n, jev_prereg.GATE_CI, one_sided=True)
        assert bounds is not None
        low, _ = bounds
        assert low == pytest.approx(0.567, abs=0.001)
        assert low < target


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

    def test_the_sleeves_are_the_workers(self) -> None:
        """
        The plan's record of which instruments a regime series describes is
        the worker's copy, in the state's own order: two copies that disagreed
        would describe one series by instruments nobody fetched.
        """
        assert dict(jev_prereg.REGIME_SLEEVES) == dict(REFERENCE_SLEEVES)
        assert tuple(jev_prereg.REGIME_SLEEVES) == SLEEVES == tuple(REFERENCE_SLEEVES)


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
            expected = "dev" if int(digest[:8], 16) % 10 < 3 else "test"
            assert jev_prereg.split_of("web_excerpt", subject_id) == expected

    def test_about_three_in_ten_are_development(self) -> None:
        splits = [jev_prereg.split_of("session", f"{i:06d}") for i in range(10_000)]
        share = splits.count("dev") / len(splits)
        assert 0.28 < share < 0.32

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
}

#: The sets with no plan of their own: the probe measures the vendor, not a
#: set, and the regime is the global plan's ``regime`` section.
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

    def test_the_global_plan_did_not_move(self) -> None:
        """The set plans are beside the global plan, not in it."""
        assert jev_prereg.PLAN_VERSION == 1
        assert jev_prereg.plan_hash() == RELEASED_PLAN_HASHES[1]


#: A different value for every choice of the set plans.
_MOVED_SET: dict[str, Any] = {
    "ASSET_CLASS_KEYWORDS": jev_prereg.ASSET_CLASS_KEYWORDS[1:],
    "CODE_SCREEN_BASELINE": {**jev_prereg.CODE_SCREEN_BASELINE, "version": 2},
    "KEYWORD_FALLBACK": "unclear",
    "KEYWORD_MATCHER": "keywords/v2",
    "MECHANISM_KEYWORDS": jev_prereg.MECHANISM_KEYWORDS[::-1],
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
        assert "regime" in jev_prereg.global_plan()

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


def _target_problems(plan: dict[str, Any], lane: str) -> list[str]:
    """How a plan's targets fall short of its lane's, if they do."""
    lane_target = jev_prereg.LANE_TARGETS[lane]
    problems = []
    for key, question in plan["questions"].items():
        if question["statistic"] != lane_target["statistic"]:
            problems.append(f"{key} measures {question['statistic']}")
        if question["bound"] != lane_target["bound"]:
            problems.append(f"{key} is bounded by {question['bound']}")
        if question["at_least"] < lane_target["at_least"]:
            problems.append(f"{key}'s target is below its lane's")
    return problems


class TestTheTargets:
    def test_a_set_plan_may_raise_a_target_never_lower_it(self) -> None:
        """
        The lane's target is a floor: the same statistic, read the same way —
        a Wilson lower bound at the gate level — and at least as high.
        """
        for name, question_set in _registered().items():
            plan = jev_prereg.set_plan(name, question_set.version)
            if plan is not None:
                assert _target_problems(plan, question_set.lane) == [], name

    def test_the_target_check_bites(self) -> None:
        plan = jev_prereg.set_plan("guardrail.card", 1)
        assert plan is not None
        plan["questions"]["performance_claim"]["at_least"] = 0.85
        assert _target_problems(plan, "guardrail") == [
            "performance_claim's target is below its lane's"
        ]

    def test_the_design_targets(self) -> None:
        """Covered precision of at least 0.90 for the guardrails, covered
        accuracy of at least 0.80 for the research sets."""
        expected = {
            "guardrail.injection": ("covered_precision_of_the_acting_class", 0.90),
            "guardrail.card": ("covered_precision_of_the_acting_class", 0.90),
            "research.catalogue": ("covered_accuracy", 0.80),
            "research.hypothesis": ("covered_accuracy", 0.80),
        }
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
