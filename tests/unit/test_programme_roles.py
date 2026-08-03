"""
test_programme_roles.py
-----------------------
The panel, and the one thing about it that has force.

A role's verdict is commentary and its summary is prose. The only part of an
assessment that changes what the system does is a finding's severity and the
identity of the role that raised it, so that is what these tests are about: the
vocabulary is closed, the veto set matches the decision-rights matrix, and a
role without a veto cannot halt anything by objecting loudly.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.programme.gates import BLOCKING_SEVERITIES, VETO_ROLES
from src.programme.roles import (
    MAX_FINDINGS_PER_ASSESSMENT,
    ROLES,
    ROLES_BY_KEY,
    ROLES_BY_STAGE,
    SEVERITIES,
    VERDICTS,
    Assessment,
    InvalidAssessmentError,
    ProposedFinding,
    blocking_count,
    facts_brief,
    roles_for_stage,
    validate_assessment,
)


def _assessment(**overrides: object) -> Assessment:
    base: dict[str, object] = {
        "verdict": "concern",
        "summary": "The universe looks selected after the fact, which would "
        "explain the result without any of the stated mechanism.",
        "findings": [],
    }
    base.update(overrides)
    return Assessment(**base)  # type: ignore[arg-type]


def _finding(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "severity": "high",
        "title": "the universe excludes delisted instruments",
        "detail": "Every symbol in the universe still trades today, which "
        "means the result is measured on survivors only.",
        "remediation": "Rebuild the universe from point-in-time membership.",
    }
    base.update(overrides)
    return base


class TestTheRoster:
    def test_there_are_twelve(self) -> None:
        assert len(ROLES) == 12
        assert len(ROLES_BY_KEY) == 12

    def test_every_veto_role_exists(self) -> None:
        """
        The gate's veto set and the roster must name the same things.

        A key in `VETO_ROLES` with no role behind it is a veto nobody can
        exercise; a role that believes it holds one and does not is worse,
        because it would raise critical findings expecting them to bite.
        """
        assert VETO_ROLES <= set(ROLES_BY_KEY)

    def test_the_roles_that_hold_a_veto_say_so(self) -> None:
        for role in ROLES:
            assert role.holds_veto == (role.key in VETO_ROLES)

    def test_the_proposing_roles_hold_none(self) -> None:
        """A role that proposes a trade must not be the one approving it."""
        for key in ("quant_research", "portfolio_construction", "machine_learning"):
            assert not ROLES_BY_KEY[key].holds_veto

    def test_the_director_holds_none(self) -> None:
        """
        The prompt is explicit: the programme director may prioritise and
        recommend, and may not override a risk, validation or compliance
        control.
        """
        assert not ROLES_BY_KEY["programme_director"].holds_veto


class TestWhoIsSummoned:
    @pytest.mark.parametrize("stage", sorted(ROLES_BY_STAGE))
    def test_each_stage_summons_known_roles(self, stage: int) -> None:
        assert all(key in ROLES_BY_KEY for key in ROLES_BY_STAGE[stage])

    def test_the_research_stages_summon_a_veto_holder(self) -> None:
        """A panel with no veto in it cannot stop anything."""
        for stage in (0, 1, 2):
            summoned = {r.key for r in roles_for_stage(stage)}
            assert summoned & VETO_ROLES, stage

    def test_operating_stages_summon_the_full_panel(self) -> None:
        assert set(roles_for_stage(5)) == set(ROLES)
        assert set(roles_for_stage(8)) == set(ROLES)

    def test_an_unknown_stage_summons_nobody(self) -> None:
        assert roles_for_stage(-1) == ()


class TestTheVocabularyIsClosed:
    def test_a_valid_assessment_passes(self) -> None:
        validate_assessment(_assessment())

    @pytest.mark.parametrize("verdict", VERDICTS)
    def test_every_documented_verdict_is_accepted(self, verdict: str) -> None:
        validate_assessment(_assessment(verdict=verdict))

    def test_an_invented_verdict_is_refused(self) -> None:
        with pytest.raises(InvalidAssessmentError):
            validate_assessment(_assessment(verdict="broadly positive"))

    @pytest.mark.parametrize("severity", SEVERITIES)
    def test_every_documented_severity_is_accepted(self, severity: str) -> None:
        validate_assessment(
            _assessment(findings=[ProposedFinding(**_finding(severity=severity))])
        )

    def test_an_invented_severity_is_refused(self) -> None:
        """
        A severity the gate cannot compare is a finding that silently never
        blocks, which is the worst of both outcomes: it looks like a control
        and behaves like a note.
        """
        with pytest.raises(InvalidAssessmentError):
            validate_assessment(
                _assessment(
                    findings=[ProposedFinding(**_finding(severity="medium-high"))]
                )
            )

    def test_an_invented_field_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            Assessment(
                verdict="support",
                summary="a" * 30,
                findings=[],
                confidence=0.9,  # type: ignore[call-arg]
            )

    def test_a_finding_must_say_what_would_fix_it(self) -> None:
        payload = _finding()
        payload["remediation"] = "tbd"
        with pytest.raises(ValidationError):
            ProposedFinding(**payload)

    def test_a_finding_must_name_a_specific_defect(self) -> None:
        payload = _finding()
        payload["title"] = "concerns"
        with pytest.raises(ValidationError):
            ProposedFinding(**payload)

    def test_too_many_findings_are_refused(self) -> None:
        payload = [ProposedFinding(**_finding()) for _ in range(6)]
        with pytest.raises(ValidationError):
            _assessment(findings=payload)


class TestWhatActuallyBlocks:
    def test_a_veto_role_at_high_severity_blocks(self) -> None:
        assessment = _assessment(
            findings=[ProposedFinding(**_finding(severity="high"))]
        )
        assert blocking_count(assessment, ROLES_BY_KEY["independent_risk"]) == 1

    def test_the_same_finding_from_a_proposing_role_does_not(self) -> None:
        assessment = _assessment(
            findings=[ProposedFinding(**_finding(severity="critical"))]
        )
        assert blocking_count(assessment, ROLES_BY_KEY["quant_research"]) == 0

    @pytest.mark.parametrize("severity", ["low", "medium"])
    def test_a_minor_finding_from_a_veto_role_does_not(self, severity: str) -> None:
        assessment = _assessment(
            findings=[ProposedFinding(**_finding(severity=severity))]
        )
        assert blocking_count(assessment, ROLES_BY_KEY["compliance"]) == 0

    def test_the_blocking_severities_are_the_documented_ones(self) -> None:
        assert BLOCKING_SEVERITIES == {"high", "critical"}

    def test_the_cap_matches_the_schema_limit(self) -> None:
        assert MAX_FINDINGS_PER_ASSESSMENT == 5


class TestTheBrief:
    """Every role is shown one rendering, so a disagreement is about evidence."""

    def _brief(self, **overrides: object) -> str:
        candidate: dict[str, object] = {
            "hypothesis_ref": "H-0001",
            "hypothesis_title": "Cross-asset trend persistence",
            "strategy_name": "asset_class_trend_following",
            "params": {"sma_period": 210},
            "universe": ["SPY", "IEF"],
            "start_session": "2010-01-04",
            "end_session": "2020-12-31",
            "data_source": "yfinance",
            "evidence_is_synthetic": False,
            "stage": 1,
            "experiments": [],
        }
        candidate.update(overrides)
        gate = {
            "from_stage_name": "rapid research",
            "to_stage_name": "independent validation",
            "passed": False,
            "criteria": [
                {
                    "description": "A backtest completed at base costs",
                    "met": False,
                    "detail": "no succeeded backtest",
                    "evidence": None,
                }
            ],
        }
        return facts_brief(candidate, gate)

    def test_it_names_the_unmet_criteria(self) -> None:
        assert "UNMET" in self._brief()
        assert "A backtest completed at base costs" in self._brief()

    def test_synthetic_data_is_labelled_in_the_brief(self) -> None:
        """
        Synthetic data is labelled everywhere it appears, and a role reasoning
        about a Sharpe without knowing the prices were generated is the exact
        failure that rule exists to prevent.
        """
        assert "SYNTHETIC" in self._brief(evidence_is_synthetic=True)

    def test_it_says_plainly_when_there_is_no_evidence(self) -> None:
        assert "Experiments: none recorded." in self._brief()

    def test_an_experiment_carries_its_cost_and_significance(self) -> None:
        brief = self._brief(
            experiments=[
                {
                    "ref": "E-0001",
                    "kind": "backtest",
                    "status": "succeeded",
                    "conclusion": "pass",
                    "outcome": {
                        "sharpe": 0.62,
                        "sharpe_is_significant": False,
                        "cost_stress_multiplier": 1.0,
                        "effective_start": "2007-01-03",
                    },
                    "preregistered_criteria": [
                        {"metric": "sharpe", "op": ">=", "value": 0.3}
                    ],
                }
            ]
        )
        assert "sharpe_is_significant" in brief
        assert "cost_stress_multiplier" in brief
        assert "effective_start" in brief
        assert "preregistered" in brief
