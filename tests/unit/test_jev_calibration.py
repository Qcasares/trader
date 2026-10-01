"""
When an evaluation could arm a threshold, and what an armed one may do
(``src/programme/jev_calibration.py``, phase C9).

Nothing arms anything in phase C, so every rule here is a rule about a future
change, and the tests are what will hold it:

* **Each reason alone refuses.** :func:`usable` is given an evaluation that
  passes every condition, then one broken at a time, and must refuse it
  naming that reason and no other — so a condition dropped from the function
  is a test that fails, not a gate that quietly opened.
* **Friction, never less.** :func:`card_verdict` is driven through every
  combination of the code's verdict, the answer and the calibration: it never
  accepts what the code rejected, an armed verdict never accepts what the
  unarmed one rejected, and no calibration is the code's verdict exactly.
* **A text is described only on a clean answer.** :func:`document_path` is
  driven through every combination too: a code flag is a quarantine whatever
  Jev said, and ``describe`` means a valid ``false`` and no code flag. It
  takes no calibration, by its signature.
"""

from __future__ import annotations

import hashlib
import inspect
import itertools
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from src.programme import jev_calibration, jev_prereg, jev_questions, jev_stats
from src.programme.jev_calibration import (
    REASONS,
    analysis_plan_hash,
    card_verdict,
    document_path,
    usable,
)
from src.programme.jev_validate import ValidatedAnswer

PIN = "jev-1.13.0"
SET = "research.catalogue"
PLAN = analysis_plan_hash(SET, 1)
CREATED = datetime(2026, 11, 2, 15, tzinfo=UTC)


def _usable_row(**overrides: Any) -> dict[str, Any]:
    """An evaluation that passes every condition, as the ledger returns one."""
    row: dict[str, Any] = {
        "id": 10,
        "created_at": CREATED,
        "question_set": SET,
        "question_set_version": 1,
        "question_key": "asset_class",
        "model": PIN,
        "analysis_plan_hash": PLAN,
        "split": "test",
        "n": jev_prereg.MIN_TEST_ITEMS,
        "possibly_in_training": False,
        "dataset_sha256": "a" * 64,
        "threshold_dataset_sha256": "d" * 64,
        "threshold_outcome": "chosen",
        "threshold": 0.42,
        "threshold_target": 0.80,
        "coverage_at_threshold": 0.55,
        # 114 of the 120 test items at the threshold right: a one-sided lower
        # bound of 0.871 at the gate level, above the plan's 0.80.
        "n_at_threshold": 120,
        "accuracy_at_threshold": 0.95,
        "accuracy_wilson_low": 0.83,
        "accuracy_all_items_wilson_low": 0.81,
        "majority_baseline_accuracy": 0.40,
        "keyword_baseline_accuracy": 0.55,
        # Of the items only one of the two got right, Jev got 90 of 100 against
        # the majority label and 60 of 90 against the keyword rule: each
        # beaten by the exact one-sided sign test at the gate level.
        "vs_majority_jev_right_only": 90,
        "vs_majority_baseline_right_only": 10,
        "vs_keyword_jev_right_only": 60,
        "vs_keyword_baseline_right_only": 30,
        "flip_rate": 0.02,
        "flip_rate_n": jev_prereg.MIN_FLIP_PAIRS,
        "flip_rate_near_threshold": 0.08,
        "flip_rate_near_threshold_n": jev_prereg.MIN_FLIP_PAIRS,
    }
    row.update(overrides)
    return row


def _verdict(
    row: dict[str, Any], earlier: list[dict[str, Any]] | None = None
) -> tuple[bool, float | None, list[str]]:
    return usable(row, earlier=earlier or [], pin=PIN, plan_hash=PLAN)


#: For each reason, one way to break an otherwise usable evaluation that
#: breaks that condition alone: overrides of the row, and the other rows on
#: record.
BROKEN: dict[str, tuple[dict[str, Any], list[dict[str, Any]]]] = {
    "set": ({"question_key": "rebalance_horizon"}, []),
    "model": ({"model": "jev-1.14.0"}, []),
    "plan": ({"analysis_plan_hash": "b" * 64}, []),
    "split": ({"split": "all"}, []),
    "size": ({"n": jev_prereg.MIN_TEST_ITEMS - 1}, []),
    "training": ({"possibly_in_training": True}, []),
    "threshold": ({"threshold_outcome": "none_found", "threshold": None}, []),
    # 102 of 120 right at the threshold on the test split: 0.85, whose
    # one-sided lower bound at the gate level, 0.748, falls short of 0.80.
    "held_out": ({"accuracy_at_threshold": 0.85}, []),
    "majority": ({"majority_baseline_accuracy": 0.82}, []),
    # Seven of seven discordant items Jev's way, which the bootstrap called a
    # win: its exact chance, 1 in 128, is above the gate's 1 in 200.
    "keyword": (
        {"vs_keyword_jev_right_only": 7, "vs_keyword_baseline_right_only": 0},
        [],
    ),
    "uniform_flips": ({"flip_rate": jev_prereg.MAX_FLIP_RATE + 0.01}, []),
    "near_threshold_flips": (
        {"flip_rate_near_threshold_n": jev_prereg.MIN_FLIP_PAIRS - 1},
        [],
    ),
    # An evaluation of an earlier version of the set, on this test set. No
    # set has a version 2 yet, so the earlier one is numbered 0 here.
    "reused_test_set": (
        {},
        [
            {
                "id": 3,
                "created_at": CREATED - timedelta(days=30),
                "question_set": SET,
                "question_set_version": 0,
                "question_key": "asset_class",
                "model": PIN,
                "dataset_sha256": "a" * 64,
                "threshold_dataset_sha256": "e" * 64,
            }
        ],
    ),
    "superseded": (
        {},
        [
            {
                "id": 11,
                "created_at": CREATED + timedelta(minutes=5),
                "question_set": SET,
                "question_set_version": 1,
                "question_key": "asset_class",
                "model": PIN,
            }
        ],
    ),
}


class TestUsable:
    def test_an_evaluation_that_meets_every_condition_is_usable(self) -> None:
        assert _verdict(_usable_row()) == (True, 0.42, [])

    def test_every_reason_has_a_case(self) -> None:
        assert set(BROKEN) == set(REASONS)

    @pytest.mark.parametrize("reason", sorted(BROKEN))
    def test_each_reason_alone_makes_it_unusable(self, reason: str) -> None:
        overrides, earlier = BROKEN[reason]
        assert _verdict(_usable_row(**overrides), earlier) == (False, None, [reason])

    def test_what_counts_as_a_used_test_set(self) -> None:
        (earlier,) = BROKEN["reused_test_set"][1]
        row = _usable_row()
        # The development set an earlier version tuned on is a used set too.
        tuned = dict(
            earlier, dataset_sha256="f" * 64, threshold_dataset_sha256="a" * 64
        )
        assert _verdict(row, [tuned]) == (False, None, ["reused_test_set"])
        # Another set's, the same version's, or another test set is not.
        for other in (
            dict(earlier, question_set="guardrail.card"),
            dict(earlier, question_set_version=1, created_at=CREATED, id=2),
            dict(earlier, dataset_sha256="c" * 64),
        ):
            assert _verdict(row, [other]) == (True, 0.42, []), other

    def test_an_older_row_of_its_key_does_not_supersede_it(self) -> None:
        older = dict(BROKEN["superseded"][1][0], id=9, created_at=CREATED)
        assert _verdict(_usable_row(), [older]) == (True, 0.42, [])
        other_model = dict(BROKEN["superseded"][1][0], model="jev-1.14.0")
        assert _verdict(_usable_row(), [other_model]) == (True, 0.42, [])

    @pytest.mark.parametrize(
        ("overrides", "reason"),
        [
            ({"question_set": "decision.regime"}, "set"),
            ({"question_set": "probe.connectivity"}, "set"),
            ({"question_set_version": 2}, "set"),
            ({"threshold": None}, "threshold"),
            ({"coverage_at_threshold": None}, "threshold"),
            # The test split measured nothing at the threshold, or too little.
            ({"n_at_threshold": 0, "accuracy_at_threshold": None}, "held_out"),
            ({"n_at_threshold": None, "accuracy_at_threshold": None}, "held_out"),
            ({"accuracy_at_threshold": None}, "held_out"),
            ({"coverage_at_threshold": 0.0}, "held_out"),
            (
                {
                    "n_at_threshold": jev_prereg.MIN_COVERED - 1,
                    "accuracy_at_threshold": 1.0,
                },
                "held_out",
            ),
            ({"n_at_threshold": True, "accuracy_at_threshold": 1.0}, "held_out"),
            # A target the row raises binds; one it lowers does not loosen the
            # plan's.
            ({"threshold_target": 0.90}, "held_out"),
            (
                {"threshold_target": 0.50, "accuracy_at_threshold": 0.85},
                "held_out",
            ),
            ({"possibly_in_training": None}, "training"),
            ({"keyword_baseline_accuracy": None}, "keyword"),
            ({"accuracy_all_items_wilson_low": 0.5}, "keyword"),
            ({"accuracy_wilson_low": None}, "majority"),
            ({"vs_keyword_jev_right_only": None}, "keyword"),
            ({"vs_majority_baseline_right_only": True}, "majority"),
            ({"vs_majority_jev_right_only": -1}, "majority"),
            (
                {"vs_keyword_jev_right_only": 30, "vs_keyword_baseline_right_only": 20},
                "keyword",
            ),
            ({"flip_rate": None}, "uniform_flips"),
            ({"flip_rate_n": None}, "uniform_flips"),
            ({"flip_rate_near_threshold": 0.11}, "near_threshold_flips"),
            ({"n": True}, "size"),
        ],
    )
    def test_a_missing_or_unmeasured_figure_refuses_too(
        self, overrides: dict[str, Any], reason: str
    ) -> None:
        """An unmeasured figure is never read as a pass, nor ``True`` as 1."""
        ok, threshold, reasons = _verdict(_usable_row(**overrides))
        assert (ok, threshold) == (False, None)
        assert reason in reasons

    @pytest.mark.parametrize(
        ("question_set", "key", "right", "tested", "borne_out"),
        [
            ("research.catalogue", "asset_class", 30, 30, True),
            ("research.catalogue", "asset_class", 29, 30, False),
            ("research.catalogue", "asset_class", 114, 120, True),
            ("guardrail.card", "performance_claim", 70, 70, True),
            ("guardrail.card", "performance_claim", 66, 70, False),
        ],
    )
    def test_the_held_out_bound_is_the_searchs_own_rule(
        self, question_set: str, key: str, right: int, tested: int, borne_out: bool
    ) -> None:
        """
        The test split is held to the rule the development split's search
        applied: the statistic's one-sided Wilson lower bound at the gate level,
        on at least ``MIN_COVERED`` items, against the plan's target — 0.80
        for the research lane, which 30 of 30 meets and 29 of 30 does not, and
        0.90 for a guardrail's covered precision.
        """
        target = jev_prereg.SET_TARGETS[(question_set, key)]["at_least"]
        bound = jev_stats.wilson(right, tested, jev_prereg.GATE_CI, one_sided=True)
        assert bound is not None
        assert (bound[0] >= target) is borne_out
        plan = analysis_plan_hash(question_set, 1)
        row = _usable_row(
            question_set=question_set,
            question_key=key,
            analysis_plan_hash=plan,
            threshold_target=target,
            n_at_threshold=tested,
            accuracy_at_threshold=right / tested,
        )
        verdict = usable(row, earlier=[], pin=PIN, plan_hash=plan or "")
        refused = (False, None, ["held_out"])
        assert verdict == ((True, 0.42, []) if borne_out else refused)

    def test_a_baseline_is_beaten_by_the_exact_sign_test_alone(self) -> None:
        """
        The paired difference's bootstrap interval is reported and gates
        nothing: a bound above 0 beside 7 of 7 discordant items does not beat
        the baseline, and a bound below 0 beside 60 of 90 does not stop it.
        The exact test at the gate level decides — 8 of 8 is the fewest that
        can.
        """
        for low, counts, beaten in (
            (0.30, (7, 0), False),
            (0.005, (5, 0), False),
            (-0.20, (60, 30), True),
            (None, (8, 0), True),
            (0.30, (7, 1), False),
        ):
            row = _usable_row(
                vs_keyword_diff_low=low,
                vs_keyword_jev_right_only=counts[0],
                vs_keyword_baseline_right_only=counts[1],
            )
            ok, _, reasons = _verdict(row)
            assert ("keyword" not in reasons) is beaten, (low, counts, reasons)
            assert ok is beaten

    def test_no_pin_and_no_plan_match_nothing(self) -> None:
        row = _usable_row()
        assert usable(row, earlier=[], pin="", plan_hash=PLAN)[2] == ["model"]
        assert usable(row, earlier=[], pin=PIN, plan_hash="")[2] == ["plan"]

    def test_a_row_never_recorded_is_never_the_newest(self) -> None:
        row = _usable_row(id=None, created_at=None)
        assert _verdict(row) == (False, None, ["superseded"])


class TestTheAnalysisPlanHash:
    def test_it_is_the_plans_in_force_hashed(self) -> None:
        plans = jev_prereg.plans_in_force(SET, 1)
        text = json.dumps(plans, sort_keys=True, separators=(",", ":"))
        assert PLAN == hashlib.sha256(text.encode("utf-8")).hexdigest()

    def test_each_set_has_its_own_and_an_unplanned_set_none(self) -> None:
        hashes = {
            name: analysis_plan_hash(name, version)
            for name, version in jev_prereg.SET_PLAN_VERSIONS
        }
        assert None not in hashes.values()
        assert len(set(hashes.values())) == len(hashes)
        assert analysis_plan_hash("decision.regime", 1) is None
        assert analysis_plan_hash(SET, 2) is None

    def test_it_moves_with_either_plan(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real = jev_prereg.plans_in_force(SET, 1)
        for key in ("plan_hash", "set_plan_hash"):
            moved = dict(real, **{key: "0" * 64})
            monkeypatch.setattr(jev_prereg, "plans_in_force", lambda n, v, m=moved: m)
            assert analysis_plan_hash(SET, 1) != PLAN, key


def _answer(
    *, valid: bool, argmax: str | None, margin: float | None, noul: float | None
) -> ValidatedAnswer:
    return ValidatedAnswer(
        question_key="performance_claim",
        question_type="noul",
        noul=noul,
        choice=None,
        score=None,
        probabilities=None,
        confidence=None,
        argmax=argmax,
        margin=margin,
        valid=valid,
        invalid_reason=None if valid else "tie",
    )


#: Every kind of answer the verdicts can meet: none, a valid ``true`` and a
#: valid ``false`` at several margins, and invalid answers, one of them still
#: naming ``true``.
ANSWERS: list[ValidatedAnswer | None] = [
    None,
    *[
        _answer(valid=True, argmax="true", margin=m, noul=(1 + m) / 2)
        for m in (0.0, 0.1, 0.42, 0.5, 0.98)
    ],
    *[
        _answer(valid=True, argmax="false", margin=m, noul=(1 - m) / 2)
        for m in (0.0, 0.42, 0.98)
    ],
    _answer(valid=False, argmax=None, margin=0.0, noul=0.5),
    _answer(valid=False, argmax="true", margin=0.9, noul=0.95),
    _answer(valid=False, argmax="false", margin=0.9, noul=0.05),
]

CALIBRATIONS: list[tuple[float] | None] = [None, (0.0,), (0.42,), (0.5,), (0.99,)]


class TestTheCardVerdict:
    @pytest.mark.parametrize(
        ("answer", "calibration"),
        list(itertools.product(ANSWERS, CALIBRATIONS)),
    )
    def test_it_never_accepts_what_the_code_rejected(
        self, answer: ValidatedAnswer | None, calibration: tuple[float] | None
    ) -> None:
        assert card_verdict("reject", answer, calibration) == "reject"

    @pytest.mark.parametrize("answer", ANSWERS)
    def test_unarmed_it_is_the_codes_verdict(
        self, answer: ValidatedAnswer | None
    ) -> None:
        for code in ("accept", "reject"):
            assert card_verdict(code, answer, None) == code

    @pytest.mark.parametrize(
        ("code", "answer", "calibration"),
        list(itertools.product(("accept", "reject"), ANSWERS, CALIBRATIONS[1:])),
    )
    def test_armed_it_never_gives_less_friction(
        self,
        code: str,
        answer: ValidatedAnswer | None,
        calibration: tuple[float],
    ) -> None:
        armed = card_verdict(code, answer, calibration)  # type: ignore[arg-type]
        unarmed = card_verdict(code, answer, None)  # type: ignore[arg-type]
        assert not (unarmed == "reject" and armed == "accept")
        (threshold,) = calibration
        jev_rejects = (
            answer is not None
            and answer.valid
            and answer.argmax == "true"
            and answer.margin is not None
            and answer.margin >= threshold
        )
        assert armed == ("reject" if code == "reject" or jev_rejects else "accept")

    def test_an_unknown_code_verdict_is_refused(self) -> None:
        with pytest.raises(ValueError):
            card_verdict("maybe", None, None)  # type: ignore[arg-type]


class TestTheDocumentPath:
    @pytest.mark.parametrize(
        ("code_flag", "answer"), list(itertools.product((True, False), ANSWERS))
    )
    def test_every_combination(
        self, code_flag: bool, answer: ValidatedAnswer | None
    ) -> None:
        path = document_path(code_flag, answer)
        if code_flag:
            assert path == "quarantine"
        if path == "describe":
            assert not code_flag
            assert answer is not None and answer.valid and answer.argmax == "false"
        if answer is not None and answer.valid and answer.argmax == "true":
            assert path == "quarantine"
        if not code_flag and (answer is None or not answer.valid):
            assert path == "hold"

    def test_it_takes_no_calibration(self) -> None:
        """
        A threshold could only release a text the screen's argmax already
        quarantines, which is friction removed; the function cannot take one.
        """
        assert list(inspect.signature(document_path).parameters) == [
            "code_flag",
            "answer",
        ]

    def test_a_code_flag_is_a_boolean(self) -> None:
        with pytest.raises(TypeError):
            document_path(1, None)  # type: ignore[arg-type]


class TestTheVocabulary:
    def test_the_answers_are_the_screens_and_the_acting_classes(self) -> None:
        assert jev_calibration.TRUE == jev_questions.SCREEN_FLAG_ARGMAX
        assert jev_calibration.FALSE == jev_questions.SCREEN_CLEAR_ARGMAX
        for key in (
            ("guardrail.card", "performance_claim"),
            ("guardrail.injection", "addressed_to_ai"),
        ):
            assert jev_prereg.SET_TARGETS[key]["acting_class"] == jev_calibration.TRUE
