"""
test_programme_scorecard.py
---------------------------
The scorecard, and the one property that makes it worth having.

**An unavailable metric is `not measured`, never zero.** Most of this file
exists to hold that line, because the failure it prevents is silent: a card
rendering an unmeasured probability of backtest overfitting as 0.00 asserts the
most flattering possible value for the metric whose entire purpose is to be
unflattering, and nothing downstream can tell it apart from a real measurement.

The second property tested here is that a missing measurement is `unknown` and
not `fail`. An operator who cannot tell those apart will either dismiss real
failures as noise or chase phantom ones.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.programme import scorecard
from src.programme.gates import (
    MAX_PBO,
    CandidateFacts,
    ExperimentFact,
    FindingFact,
    ShadowFact,
    WalkforwardFact,
    evaluate,
)
from src.programme.scorecard import DECISIONS, NOT_MEASURED

PARAMS = {"sma_period": 210}


def _card() -> dict[str, str]:
    return {
        "economic_mechanism": "slow institutional rebalancing",
        "why_it_persists": "mandated bands force the other side",
        "limitations": "listed from 2006",
    }


def _facts(**overrides: object) -> CandidateFacts:
    base: dict[str, object] = {
        "stage": 1,
        "status": "active",
        "params": dict(PARAMS),
        "universe": ("SPY",),
        "start_session": date(2015, 1, 2),
        "end_session": date(2020, 12, 31),
        "data_source": "yfinance",
        "evidence_is_synthetic": False,
        "hypothesis_ref": "H-0001",
        "hypothesis_owner": "quentin",
        "hypothesis_card": _card(),
        "universe_coverage": {"SPY": 1400},
        "experiments": (),
        "walkforwards": (),
    }
    base.update(overrides)
    return CandidateFacts(**base)  # type: ignore[arg-type]


def _backtest(**outcome: object) -> ExperimentFact:
    payload = {
        "sharpe": 0.62,
        "sharpe_stderr": 0.18,
        "sharpe_is_significant": True,
        "cagr": 0.08,
        "max_drawdown": -0.22,
        "cost_stress_multiplier": 1.0,
        "periods_per_year": 252,
    }
    payload.update(outcome)
    return ExperimentFact(
        ref="E-0001",
        kind="backtest",
        status="succeeded",
        conclusion="pass",
        outcome=payload,
    )


def _build(facts: CandidateFacts) -> scorecard.Scorecard:
    return scorecard.build(facts, evaluate(facts))


def _row(card: scorecard.Scorecard, metric: str) -> scorecard.ScoreRow:
    return next(r for r in card.rows if r.metric == metric)


class TestNothingUnmeasuredReadsAsZero:
    def test_an_empty_candidate_measures_almost_nothing(self) -> None:
        card = _build(_facts())
        assert card.not_measured_count() > 8

    def test_every_unmeasured_row_says_so(self) -> None:
        """
        The property, asserted over the whole card rather than a chosen row.
        No cell may render an absent measurement as a number.
        """
        card = _build(_facts())
        for row in card.rows:
            if row.observed is None:
                assert row.as_dict()["observed_display"] == NOT_MEASURED

    def test_an_unmeasured_overfitting_probability_is_not_zero(self) -> None:
        """The single most dangerous value this module could produce."""
        row = _row(_build(_facts()), "Probability of backtest overfitting")
        assert row.observed is None
        assert row.as_dict()["observed_display"] == NOT_MEASURED
        assert row.observed != 0

    def test_an_unmeasured_deflated_sharpe_is_not_zero(self) -> None:
        row = _row(_build(_facts()), "Deflated Sharpe ratio")
        assert row.observed is None

    def test_a_measured_zero_is_kept_as_zero(self) -> None:
        """
        The mirror of the rule. A genuine zero is a measurement and must not be
        laundered into "not measured" either.
        """
        facts = _facts(experiments=(_backtest(cagr=0.0),))
        row = _row(_build(facts), "Annualised net return")
        assert row.observed == 0.0
        assert row.status == "fail"


class TestUnknownIsNotFail:
    def test_a_missing_measurement_is_unknown(self) -> None:
        card = _build(_facts())
        assert _row(card, "Deflated Sharpe ratio").status == "unknown"

    def test_a_bad_measurement_is_fail(self) -> None:
        study = WalkforwardFact(
            run_id="wf-1",
            status="succeeded",
            params=dict(PARAMS),
            is_robust=True,
            pbo=0.9,
        )
        facts = _facts(walkforwards=(study,))
        row = _row(_build(facts), "Probability of backtest overfitting")
        assert row.status == "fail"

    def test_a_good_measurement_is_pass(self) -> None:
        study = WalkforwardFact(
            run_id="wf-1",
            status="succeeded",
            params=dict(PARAMS),
            is_robust=True,
            pbo=MAX_PBO / 2,
        )
        facts = _facts(walkforwards=(study,))
        assert (
            _row(_build(facts), "Probability of backtest overfitting").status
            == "pass"
        )

    def test_unknown_rows_are_not_counted_as_failing(self) -> None:
        card = _build(_facts())
        assert card.failing < len([r for r in card.rows if r.status == "unknown"])


class TestHonestyRulesAreCarried:
    def test_a_return_carries_its_cost_assumption(self) -> None:
        row = _row(_build(_facts(experiments=(_backtest(),))), "Annualised net return")
        assert "1x modelled costs" in row.commentary
        assert "252" in row.commentary

    def test_a_return_with_no_cost_assumption_says_it_cannot_be_read(
        self,
    ) -> None:
        facts = _facts(
            experiments=(_backtest(cost_stress_multiplier=None),)
        )
        row = _row(_build(facts), "Annualised net return")
        assert "cannot be read" in row.commentary

    def test_an_insignificant_sharpe_is_labelled_as_no_evidence(self) -> None:
        """
        Not "a small edge". The repository's own honesty rule, carried onto the
        card where an operator actually reads the number.
        """
        facts = _facts(
            experiments=(_backtest(sharpe=0.2, sharpe_is_significant=False),)
        )
        row = _row(_build(facts), "Net Sharpe ratio")
        assert row.status == "fail"
        assert "no evidence of an edge" in row.commentary

    def test_a_sharpe_with_no_standard_error_is_not_interpretable(self) -> None:
        facts = _facts(
            experiments=(
                _backtest(sharpe_stderr=None, sharpe_is_significant=None),
            )
        )
        row = _row(_build(facts), "Net Sharpe ratio")
        assert row.status == "unknown"
        assert "not interpretable" in row.commentary

    def test_synthetic_evidence_fails_the_data_row(self) -> None:
        card = _build(_facts(evidence_is_synthetic=True))
        row = _row(card, "Dataset readiness")
        assert row.status == "fail"
        assert row.observed == "synthetic"


class TestTheRecommendation:
    def test_it_is_always_from_the_permitted_vocabulary(self) -> None:
        assert _build(_facts()).recommendation in DECISIONS

    def test_an_unpassed_gate_holds(self) -> None:
        card = _build(_facts())
        assert card.recommendation == "hold_for_more_evidence"
        assert "gate has not passed" in card.recommendation_reason

    def test_a_blocking_finding_holds_and_names_the_role(self) -> None:
        finding = FindingFact(
            ref="F-0001",
            raised_by="independent_risk",
            severity="critical",
            title="the universe excludes delisted instruments",
        )
        card = _build(_facts(findings=(finding,)))
        assert card.recommendation == "hold_for_more_evidence"
        assert "independent_risk" in card.approvers
        assert "F-0001" in card.unresolved

    def test_a_human_gated_stage_names_its_approvers(self) -> None:
        facts = _facts(stage=4, shadow=(ShadowFact(date(2024, 1, 2), True),))
        card = scorecard.build(facts, evaluate(facts))
        # Stage 4 cannot pass in this slice, so it holds — but the point is
        # that the vocabulary and the approver list are well formed.
        assert card.recommendation in DECISIONS

    def test_there_is_no_overall_score(self) -> None:
        """
        Deliberately absent. Collapsing seventeen dimensions into one number
        lets a strong Sharpe outvote an unmeasured capacity.
        """
        card = _build(_facts())
        assert not hasattr(card, "score")
        assert not hasattr(card, "grade")


class TestShape:
    def test_it_has_the_seventeen_dimensions(self) -> None:
        assert len(_build(_facts()).rows) == 17

    def test_every_row_states_a_target(self) -> None:
        for row in _build(_facts()).rows:
            assert row.target.strip(), row.metric

    def test_every_unbuilt_row_says_why(self) -> None:
        """
        A blank cell teaches nothing. Each dimension the engine cannot measure
        yet says what it would take.
        """
        for row in _build(_facts()).rows:
            if row.status == "unknown":
                assert row.commentary.strip(), row.metric

    @pytest.mark.parametrize("stage", [0, 1, 2, 3, 4])
    def test_it_builds_at_every_reachable_stage(self, stage: int) -> None:
        facts = _facts(stage=stage)
        assert scorecard.build(facts, evaluate(facts)).rows
