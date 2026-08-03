"""
test_programme_gates.py
-----------------------
The promotion gates, driven with nothing but dataclasses.

No database, no network, no model. That is the point of keeping
:mod:`src.programme.gates` pure: the decision that governs whether a strategy
advances towards operating on real money is the one that must be cheap and
exhaustive to test.

Each gate is driven in both directions — a facts set that should pass, and one
mutation away from it per criterion that should not. A gate that cannot be made
to fail is not a gate.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.programme.gates import (
    BLOCKING_SEVERITIES,
    FIRST_HUMAN_GATED_STAGE,
    MIN_BARS_PER_SYMBOL,
    MIN_SHADOW_SESSIONS,
    VETO_ROLES,
    CandidateFacts,
    ExperimentFact,
    FindingFact,
    ShadowFact,
    WalkforwardFact,
    evaluate,
    evaluate_preregistered,
    replication_agrees,
)
from src.programme.gates import (
    REQUIRED_CARD_FIELDS as CARD_FIELDS,
)

START = date(2015, 1, 2)
END = date(2020, 12, 31)
UNIVERSE = ("SPY", "IEF")
PARAMS = {"sma_period": 210}

ACCEPTANCE = [{"metric": "sharpe", "op": ">=", "value": 0.3}]


def _card(**overrides: object) -> dict[str, object]:
    card = {name: f"stated {name}" for name in CARD_FIELDS}
    card["limitations"] = "single asset until 2007"
    card.update(overrides)
    return card


def _backtest(**overrides: object) -> ExperimentFact:
    outcome = {
        "sharpe": 0.62,
        "sharpe_is_significant": False,
        "effective_start": "2007-01-03",
        "preregistered_criteria": ACCEPTANCE,
    }
    outcome.update(overrides.pop("outcome", {}))  # type: ignore[arg-type]
    base = {
        "ref": "E-0001",
        "kind": "backtest",
        "status": "succeeded",
        "conclusion": "pass",
        "backtest_run_id": "run-1",
        "data_source": "yfinance",
        "outcome": outcome,
    }
    base.update(overrides)
    return ExperimentFact(**base)  # type: ignore[arg-type]


def _supporting() -> tuple[ExperimentFact, ...]:
    return (
        ExperimentFact(
            ref="E-0002",
            kind="cost_stress",
            status="succeeded",
            cost_stress_multiplier=3.0,
            outcome={"sharpe": 0.41},
        ),
        ExperimentFact(
            ref="E-0003", kind="parameter_neighbourhood", status="succeeded"
        ),
        ExperimentFact(ref="E-0004", kind="benchmark", status="succeeded"),
    )


def _facts(stage: int, **overrides: object) -> CandidateFacts:
    base: dict[str, object] = {
        "stage": stage,
        "status": "active",
        "params": dict(PARAMS),
        "universe": UNIVERSE,
        "start_session": START,
        "end_session": END,
        "data_source": "yfinance",
        "evidence_is_synthetic": False,
        "hypothesis_ref": "H-0001",
        "hypothesis_owner": "quentin",
        "hypothesis_card": _card(),
        "universe_coverage": {s: 1400 for s in UNIVERSE},
        "experiments": (),
        "walkforwards": (),
    }
    base.update(overrides)
    return CandidateFacts(**base)  # type: ignore[arg-type]


def _unmet(facts: CandidateFacts) -> set[str]:
    return {c.id for c in evaluate(facts).unmet}


# ---------------------------------------------------------------------------
# Stage 0 -> 1
# ---------------------------------------------------------------------------


class TestConceptGate:
    def test_a_complete_card_with_available_data_passes(self) -> None:
        assert evaluate(_facts(0)).passed

    def test_a_missing_card_field_blocks_it(self) -> None:
        card = _card()
        del card["falsification_test"]
        assert "card_complete" in _unmet(_facts(0, hypothesis_card=card))

    def test_a_blank_card_field_counts_as_missing(self) -> None:
        assert "card_complete" in _unmet(
            _facts(0, hypothesis_card=_card(economic_mechanism="   "))
        )

    def test_an_unowned_hypothesis_blocks_it(self) -> None:
        assert "owner_named" in _unmet(_facts(0, hypothesis_owner=""))

    def test_a_backwards_window_blocks_it(self) -> None:
        assert "window_ordered" in _unmet(
            _facts(0, start_session=END, end_session=START)
        )

    def test_a_thinly_covered_symbol_blocks_it(self) -> None:
        coverage = {"SPY": 1400, "IEF": MIN_BARS_PER_SYMBOL - 1}
        assert "universe_available" in _unmet(_facts(0, universe_coverage=coverage))

    def test_an_empty_universe_blocks_it(self) -> None:
        assert "universe_available" in _unmet(
            _facts(0, universe=(), universe_coverage={})
        )

    def test_a_symbol_absent_from_coverage_blocks_it(self) -> None:
        """A symbol nobody measured is not a symbol with enough data."""
        assert "universe_available" in _unmet(
            _facts(0, universe_coverage={"SPY": 1400})
        )


# ---------------------------------------------------------------------------
# Stage 1 -> 2
# ---------------------------------------------------------------------------


class TestResearchGate:
    def _complete(self, **overrides: object) -> CandidateFacts:
        return _facts(
            1, experiments=(_backtest(), *_supporting()), **overrides
        )

    def test_the_full_evidence_set_passes(self) -> None:
        assert evaluate(self._complete()).passed

    def test_no_backtest_blocks_it(self) -> None:
        unmet = _unmet(_facts(1, experiments=_supporting()))
        assert "backtest_succeeded" in unmet

    def test_a_failed_backtest_does_not_count(self) -> None:
        experiments = (_backtest(status="failed"), *_supporting())
        assert "backtest_succeeded" in _unmet(_facts(1, experiments=experiments))

    def test_an_understressed_cost_run_does_not_count(self) -> None:
        weak = ExperimentFact(
            ref="E-0002",
            kind="cost_stress",
            status="succeeded",
            cost_stress_multiplier=1.5,
        )
        experiments = (_backtest(), weak, *_supporting()[1:])
        assert "cost_stress" in _unmet(_facts(1, experiments=experiments))

    def test_a_missing_neighbourhood_run_blocks_it(self) -> None:
        experiments = (_backtest(), _supporting()[0], _supporting()[2])
        assert "parameter_neighbourhood" in _unmet(_facts(1, experiments=experiments))

    def test_a_missing_benchmark_blocks_it(self) -> None:
        experiments = (_backtest(), *_supporting()[:2])
        assert "benchmark_comparison" in _unmet(_facts(1, experiments=experiments))

    def test_a_missing_effective_start_blocks_it(self) -> None:
        experiments = (
            _backtest(outcome={"effective_start": None}),
            *_supporting(),
        )
        unmet = _unmet(_facts(1, experiments=experiments))
        assert "effective_start_recorded" in unmet

    def test_an_outcome_failing_its_own_criteria_blocks_it(self) -> None:
        experiments = (_backtest(outcome={"sharpe": 0.05}), *_supporting())
        unmet = _unmet(_facts(1, experiments=experiments))
        assert "preregistered_criteria_met" in unmet

    def test_criteria_that_cannot_be_evaluated_block_it(self) -> None:
        """An unanswerable test has not been passed."""
        experiments = (
            _backtest(
                outcome={
                    "preregistered_criteria": [
                        {"metric": "deflated_sharpe", "op": ">=", "value": 0.3}
                    ]
                }
            ),
            *_supporting(),
        )
        unmet = _unmet(_facts(1, experiments=experiments))
        assert "preregistered_criteria_met" in unmet

    def test_synthetic_evidence_still_passes_this_gate(self) -> None:
        """
        Deliberate. It is refused one gate later, and requiring real prices
        here would leave the pipeline unexercisable in this environment.
        """
        assert evaluate(self._complete(evidence_is_synthetic=True)).passed


# ---------------------------------------------------------------------------
# Stage 2 -> 3
# ---------------------------------------------------------------------------


class TestValidationGate:
    def _complete(self, **overrides: object) -> CandidateFacts:
        experiments = (
            _backtest(outcome={"sharpe_is_significant": True}),
            ExperimentFact(
                ref="E-0005",
                kind="replication",
                status="succeeded",
                conclusion="pass",
                seed=99,
            ),
        )
        walkforwards = (
            WalkforwardFact(
                run_id="wf-1",
                status="succeeded",
                params=dict(PARAMS),
                is_robust=True,
                degradation=0.18,
            ),
        )
        base: dict[str, object] = {
            "experiments": experiments,
            "walkforwards": walkforwards,
        }
        base.update(overrides)
        return _facts(2, **base)

    def test_the_full_evidence_set_passes(self) -> None:
        assert evaluate(self._complete()).passed

    def test_synthetic_evidence_is_refused_here(self) -> None:
        assert "evidence_is_real" in _unmet(
            self._complete(evidence_is_synthetic=True)
        )

    def test_a_synthetic_data_source_is_refused_here(self) -> None:
        assert "evidence_is_real" in _unmet(self._complete(data_source="synthetic"))

    def test_a_study_of_other_parameters_does_not_vouch(self) -> None:
        walkforwards = (
            WalkforwardFact(
                run_id="wf-2",
                status="succeeded",
                params={"sma_period": 105},
                is_robust=True,
            ),
        )
        assert "walkforward_robust" in _unmet(
            self._complete(walkforwards=walkforwards)
        )

    def test_a_study_that_returned_not_robust_blocks_it(self) -> None:
        walkforwards = (
            WalkforwardFact(
                run_id="wf-3",
                status="succeeded",
                params=dict(PARAMS),
                is_robust=False,
            ),
        )
        assert "walkforward_robust" in _unmet(
            self._complete(walkforwards=walkforwards)
        )

    def test_an_unfinished_study_blocks_it(self) -> None:
        walkforwards = (
            WalkforwardFact(
                run_id="wf-4",
                status="running",
                params=dict(PARAMS),
                is_robust=None,
            ),
        )
        assert "walkforward_robust" in _unmet(
            self._complete(walkforwards=walkforwards)
        )

    def test_a_failed_replication_blocks_it(self) -> None:
        experiments = (
            _backtest(outcome={"sharpe_is_significant": True}),
            ExperimentFact(
                ref="E-0005",
                kind="replication",
                status="succeeded",
                conclusion="fail",
            ),
        )
        assert "replicated" in _unmet(self._complete(experiments=experiments))

    def test_a_missing_significance_verdict_blocks_it(self) -> None:
        experiments = (
            _backtest(outcome={"sharpe_is_significant": None}),
            ExperimentFact(
                ref="E-0005",
                kind="replication",
                status="succeeded",
                conclusion="pass",
            ),
        )
        unmet = _unmet(self._complete(experiments=experiments))
        assert "sharpe_significance_recorded" in unmet

    def test_undocumented_limitations_block_it(self) -> None:
        assert "limitations_documented" in _unmet(
            self._complete(hypothesis_card=_card(limitations=""))
        )


# ---------------------------------------------------------------------------
# Stages this slice cannot judge
# ---------------------------------------------------------------------------


class TestShadowGate:
    """
    Stage 3 -> 4.

    Nothing here asks whether the shadow book made money, and that is the
    point: twenty sessions carries a Sharpe standard error near four, so any
    figure over that window is noise. What is being evidenced is that the
    machinery runs.
    """

    def _shadow(self, n: int, **overrides: object) -> tuple[ShadowFact, ...]:
        base = date(2024, 1, 2)
        out = []
        for i in range(n):
            kwargs: dict[str, object] = {
                "session": base + timedelta(days=i),
                "rebalanced": i == 0,
                "order_intents": 3 if i == 0 else 0,
            }
            kwargs.update(overrides)
            out.append(ShadowFact(**kwargs))  # type: ignore[arg-type]
        return tuple(out)

    def _complete(self, **overrides: object) -> CandidateFacts:
        base: dict[str, object] = {
            "shadow": self._shadow(MIN_SHADOW_SESSIONS),
            "has_deployment": True,
        }
        base.update(overrides)
        return _facts(3, **base)

    def test_a_clean_month_of_operation_passes(self) -> None:
        assert evaluate(self._complete()).passed

    def test_too_few_sessions_block_it(self) -> None:
        facts = self._complete(shadow=self._shadow(MIN_SHADOW_SESSIONS - 1))
        assert "shadow_sessions" in _unmet(facts)

    def test_no_deployment_blocks_it(self) -> None:
        assert "deployment_exists" in _unmet(self._complete(has_deployment=False))

    def test_a_failed_session_blocks_it(self) -> None:
        shadow = list(self._shadow(MIN_SHADOW_SESSIONS))
        shadow[5] = ShadowFact(
            session=shadow[5].session, rebalanced=False, error="no market data"
        )
        assert "shadow_without_errors" in _unmet(
            self._complete(shadow=tuple(shadow))
        )

    def test_a_schedule_that_never_fired_blocks_it(self) -> None:
        """Running is not the same as operating."""
        shadow = self._shadow(MIN_SHADOW_SESSIONS, rebalanced=False)
        assert "schedule_fired" in _unmet(self._complete(shadow=shadow))

    def test_a_trimmed_buy_blocks_it(self) -> None:
        """
        The simulated venue trimmed a buy a real one would have rejected, so
        the shadow book and a live one have already diverged.
        """
        shadow = list(self._shadow(MIN_SHADOW_SESSIONS))
        shadow[3] = ShadowFact(
            session=shadow[3].session, rebalanced=True, underfunded=1
        )
        assert "venue_would_have_agreed" in _unmet(
            self._complete(shadow=tuple(shadow))
        )

    def test_no_shadow_history_at_all_blocks_it(self) -> None:
        facts = self._complete(shadow=())
        unmet = _unmet(facts)
        assert {"shadow_sessions", "schedule_fired"} <= unmet

    def test_it_does_not_need_an_operator(self) -> None:
        """Stage 4 is broker paper trading, which is still below canary."""
        assert not evaluate(self._complete()).requires_human


class TestUnbuiltStages:
    @pytest.mark.parametrize("stage", [4, 5, 6, 7, 8])
    def test_they_refuse_and_name_the_missing_capability(self, stage: int) -> None:
        result = evaluate(_facts(stage))
        assert not result.passed
        # The veto criterion is prepended to every gate, built or not.
        assert [c.id for c in result.criteria] == [
            "no_blocking_findings",
            "capability_absent",
        ]
        assert result.criteria[1].detail

    def test_they_never_pass_by_having_no_criteria(self) -> None:
        """An empty criteria list must not read as unanimous agreement."""
        for stage in range(4, 9):
            assert not evaluate(_facts(stage)).passed


class TestTheVeto:
    """
    A veto is a row, not an opinion.

    Three mechanical conditions decide whether a finding halts a promotion —
    open, high or critical, raised by a role holding a veto — and none of them
    reads the finding's text. That is the property being tested here: the gate
    cannot be argued with, in either direction.
    """

    def _finding(self, **overrides: object) -> FindingFact:
        base: dict[str, object] = {
            "ref": "F-0001",
            "raised_by": "independent_risk",
            "severity": "critical",
            "title": "the universe was selected after the result was known",
            "status": "open",
        }
        base.update(overrides)
        return FindingFact(**base)  # type: ignore[arg-type]

    def test_an_otherwise_perfect_candidate_is_stopped(self) -> None:
        facts = _facts(
            1,
            experiments=(_backtest(), *_supporting()),
            findings=(self._finding(),),
        )
        result = evaluate(facts)
        assert not result.passed
        assert "no_blocking_findings" in {c.id for c in result.unmet}

    def test_the_refusal_names_the_finding(self) -> None:
        facts = _facts(0, findings=(self._finding(),))
        criterion = next(
            c for c in evaluate(facts).criteria if c.id == "no_blocking_findings"
        )
        assert "F-0001" in criterion.detail
        assert "independent_risk" in criterion.detail

    @pytest.mark.parametrize("severity", ["low", "medium"])
    def test_a_minor_finding_is_recorded_and_does_not_block(
        self, severity: str
    ) -> None:
        facts = _facts(0, findings=(self._finding(severity=severity),))
        assert evaluate(facts).passed

    def test_a_role_without_a_veto_does_not_halt_anything(self) -> None:
        """An objection from a proposing role is an objection, not a veto."""
        facts = _facts(0, findings=(self._finding(raised_by="quant_research"),))
        assert evaluate(facts).passed

    @pytest.mark.parametrize(
        "status", ["remediated", "accepted", "withdrawn"]
    )
    def test_a_closed_finding_stops_blocking(self, status: str) -> None:
        facts = _facts(0, findings=(self._finding(status=status),))
        assert evaluate(facts).passed

    def test_every_veto_role_can_actually_veto(self) -> None:
        for role in VETO_ROLES:
            facts = _facts(0, findings=(self._finding(raised_by=role),))
            assert not evaluate(facts).passed, role

    def test_it_applies_to_stages_with_no_gate_of_their_own(self) -> None:
        facts = _facts(6, findings=(self._finding(),))
        unmet = {c.id for c in evaluate(facts).unmet}
        assert {"no_blocking_findings", "capability_absent"} <= unmet

    def test_the_severities_that_block_are_the_documented_ones(self) -> None:
        assert BLOCKING_SEVERITIES == {"high", "critical"}


class TestHumanGating:
    @pytest.mark.parametrize("stage", [0, 1, 2, 3])
    def test_research_and_shadow_do_not_need_an_operator(
        self, stage: int
    ) -> None:
        assert not evaluate(_facts(stage)).requires_human

    @pytest.mark.parametrize("stage", [4, 5, 6, 7])
    def test_operating_stages_do(self, stage: int) -> None:
        assert evaluate(_facts(stage)).requires_human

    def test_the_boundary_is_where_capital_is_exposed(self) -> None:
        """
        Canary is the first stage at which the programme's own decision moves
        money at a venue, and the operating prompt forbids a model from
        changing production capital allocation.
        """
        assert FIRST_HUMAN_GATED_STAGE == 5


# ---------------------------------------------------------------------------
# Preregistration and replication
# ---------------------------------------------------------------------------


class TestPreregisteredCriteria:
    def test_a_satisfied_criterion_passes(self) -> None:
        assert evaluate_preregistered(ACCEPTANCE, {"sharpe": 0.5}) is True

    def test_an_unsatisfied_criterion_fails(self) -> None:
        assert evaluate_preregistered(ACCEPTANCE, {"sharpe": 0.1}) is False

    def test_every_criterion_must_hold(self) -> None:
        criteria = [
            {"metric": "sharpe", "op": ">=", "value": 0.3},
            {"metric": "max_drawdown", "op": ">=", "value": -0.2},
        ]
        outcome = {"sharpe": 0.5, "max_drawdown": -0.45}
        assert evaluate_preregistered(criteria, outcome) is False

    def test_a_missing_metric_is_unanswerable_not_failed(self) -> None:
        assert evaluate_preregistered(ACCEPTANCE, {}) is None

    def test_an_unknown_operator_is_unanswerable(self) -> None:
        criteria = [{"metric": "sharpe", "op": "roughly", "value": 0.3}]
        assert evaluate_preregistered(criteria, {"sharpe": 0.5}) is None

    def test_preregistering_nothing_is_not_passing(self) -> None:
        assert evaluate_preregistered([], {"sharpe": 9.9}) is None

    def test_a_non_numeric_outcome_is_unanswerable(self) -> None:
        assert evaluate_preregistered(ACCEPTANCE, {"sharpe": "excellent"}) is None


class TestReplication:
    def test_a_close_rerun_agrees(self) -> None:
        assert replication_agrees({"sharpe": 0.60}, {"sharpe": 0.66})

    def test_a_distant_rerun_does_not(self) -> None:
        assert not replication_agrees({"sharpe": 0.60}, {"sharpe": 0.95})

    def test_an_uncomparable_rerun_does_not(self) -> None:
        """A replication that cannot be compared has replicated nothing."""
        assert not replication_agrees({"sharpe": 0.60}, {})
        assert not replication_agrees({}, {"sharpe": 0.60})
