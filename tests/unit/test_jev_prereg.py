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

#: The upper-case names in ``__all__`` that are not choices of the plan:
#: ``ANY_OF`` is the rule's own syntax, and the golden is the plan's hash.
_NOT_CHOICES = frozenset({"ANY_OF", "GOLDEN_PLAN_HASH"})


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
