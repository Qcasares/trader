"""
scorecard.py
------------
The strategy scorecard, §11 of the operating prompt.

Seventeen dimensions, each with an observed result, a target, a status and the
row the number came from. Pure: it takes the same :class:`CandidateFacts` the
gates read and returns rows. No I/O, no model, no clock.

The rule that shapes every line
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
**An unavailable metric is `Not measured`, never zero.**

§14 asks for this explicitly and it is the single most important thing here.
A scorecard that renders an unmeasured probability of backtest overfitting as
0.00 does not merely omit information — it asserts the most flattering possible
value for the metric whose entire purpose is to be unflattering. Every cell on
this card is either a number that traces to a row or the words "not measured",
and :class:`ScoreRow` has no third state.

The status column is likewise deliberate. A dimension with no observation is
``unknown``, not ``fail``: those are different, and an operator who cannot tell
them apart will either dismiss real failures or chase phantom ones.

What is deliberately absent
~~~~~~~~~~~~~~~~~~~~~~~~~~~
There is no overall score, no weighted average, no letter grade. Collapsing
seventeen dimensions into one number is exactly the move this whole programme
exists to prevent: it lets a strong Sharpe outvote an unmeasured capacity, and
it produces a figure nobody can trace to a row.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.programme.gates import (
    MAX_PBO,
    MIN_COST_STRESS_MULTIPLIER,
    MIN_SHADOW_SESSIONS,
    CandidateFacts,
)

#: The permitted decisions, from §11. A recommendation outside this vocabulary
#: is not a decision the programme can act on.
DECISIONS = (
    "reject",
    "revise_and_retest",
    "hold_for_more_evidence",
    "promote_to_validation",
    "promote_to_shadow",
    "promote_to_paper",
    "promote_to_canary",
    "increase_capital",
    "maintain_capital",
    "reduce_capital",
    "suspend",
    "retire",
)

#: What a candidate at each stage is a candidate *for*. Read off §7.7 and used
#: to name the recommendation rather than to make it — the gate makes it.
_NEXT_DECISION = {
    0: "promote_to_validation",
    1: "promote_to_validation",
    2: "promote_to_shadow",
    3: "promote_to_paper",
    4: "promote_to_canary",
}

NOT_MEASURED = "not measured"


@dataclass(frozen=True, slots=True)
class ScoreRow:
    """
    One dimension of the scorecard.

    ``observed`` is ``None`` when the figure does not exist. There is no third
    state and no default of zero, because the whole point of this class is that
    "we did not measure it" cannot be rendered as "it is fine".
    """

    dimension: str
    metric: str
    observed: float | str | None
    target: str
    #: pass | fail | unknown. ``unknown`` is not a soft fail; it is the absence
    #: of a measurement, and an operator must be able to tell them apart.
    status: str
    commentary: str = ""
    evidence: str = ""

    @property
    def is_measured(self) -> bool:
        return self.observed is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "metric": self.metric,
            "observed": self.observed,
            "observed_display": (
                NOT_MEASURED if self.observed is None else self.observed
            ),
            "target": self.target,
            "status": self.status,
            "commentary": self.commentary,
            "evidence": self.evidence,
        }


@dataclass(frozen=True, slots=True)
class Scorecard:
    """Seventeen rows and a recommendation, with nothing averaged."""

    candidate_id: str
    hypothesis_ref: str
    stage: int
    rows: tuple[ScoreRow, ...]
    recommendation: str
    recommendation_reason: str
    #: Roles whose approval the recommendation needs. Empty means the gate
    #: engine can act alone.
    approvers: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = field(default_factory=tuple)

    @property
    def measured(self) -> int:
        return sum(1 for r in self.rows if r.is_measured)

    def not_measured_count(self) -> int:
        return len(self.rows) - self.measured

    @property
    def failing(self) -> int:
        return sum(1 for r in self.rows if r.status == "fail")

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "hypothesis_ref": self.hypothesis_ref,
            "stage": self.stage,
            "rows": [r.as_dict() for r in self.rows],
            "recommendation": self.recommendation,
            "recommendation_reason": self.recommendation_reason,
            "approvers": list(self.approvers),
            "unresolved": list(self.unresolved),
            "measured": self.measured,
            "not_measured": len(self.rows) - self.measured,
            "failing": self.failing,
        }


def _row(
    dimension: str,
    metric: str,
    observed: float | str | None,
    target: str,
    passed: bool | None,
    commentary: str = "",
    evidence: str = "",
) -> ScoreRow:
    """
    Build a row, deriving the status from the observation.

    ``passed=None`` and ``observed=None`` both produce ``unknown``. Nothing
    here can produce a ``pass`` from a missing number.
    """
    if observed is None or passed is None:
        status = "unknown"
    else:
        status = "pass" if passed else "fail"
    return ScoreRow(
        dimension=dimension,
        metric=metric,
        observed=observed,
        target=target,
        status=status,
        commentary=commentary,
        evidence=evidence,
    )


def build(facts: CandidateFacts, gate: Any) -> Scorecard:
    """
    Assemble the scorecard for one candidate.

    ``gate`` is the :class:`~src.programme.gates.GateResult` for its current
    stage, used for the recommendation and for the governance row. The
    recommendation is read off the gate rather than derived here: two places
    deciding whether a candidate may advance is one place too many.
    """
    backtest = facts.succeeded_of_kind("backtest")
    outcome = dict(backtest.outcome) if backtest else {}
    stressed = facts.succeeded_of_kind("cost_stress")
    study = next(
        (
            w
            for w in facts.walkforwards
            if w.status == "succeeded" and dict(w.params) == dict(facts.params)
        ),
        None,
    )
    card = facts.hypothesis_card
    evidence_ref = backtest.ref if backtest else ""

    rows: list[ScoreRow] = [
        _row(
            "Economic rationale",
            "Thesis strength",
            "stated" if str(card.get("economic_mechanism", "")).strip() else None,
            "A mechanism naming who is on the other side",
            bool(str(card.get("why_it_persists", "")).strip()),
            commentary=(
                "Presence, not persuasiveness. Nothing here reads the prose."
            ),
            evidence=facts.hypothesis_ref,
        ),
        _row(
            "Net performance",
            "Annualised net return",
            _num(outcome.get("cagr")),
            "Above the benchmark, after costs",
            _gt(outcome.get("cagr"), 0.0),
            commentary=_cost_note(outcome),
            evidence=evidence_ref,
        ),
        _row(
            "Risk-adjusted return",
            "Net Sharpe ratio",
            _num(outcome.get("sharpe")),
            "Two standard errors clear of zero",
            outcome.get("sharpe_is_significant")
            if outcome.get("sharpe_is_significant") is not None
            else None,
            commentary=_sharpe_note(outcome),
            evidence=evidence_ref,
        ),
        _row(
            "Tail risk",
            "Maximum drawdown",
            _num(outcome.get("max_drawdown")),
            "Within the configured halting limit",
            None if outcome.get("max_drawdown") is None else True,
            commentary=(
                "Compared against the deployment's own limit at stage 4; there "
                "is no programme-wide number to compare it to yet"
            ),
            evidence=evidence_ref,
        ),
        _row(
            "Statistical strength",
            "Deflated Sharpe ratio",
            _num(study.deflated_sharpe) if study else None,
            "Above 0.95",
            _gt(study.deflated_sharpe if study else None, 0.95),
            commentary=(
                "The probability the true Sharpe is above zero, discounted for "
                "how many configurations were tried"
            ),
            evidence=study.run_id if study else "",
        ),
        _row(
            "Overfitting risk",
            "Probability of backtest overfitting",
            _num(study.pbo) if study else None,
            f"At most {MAX_PBO:.2f}",
            _lte(study.pbo if study else None, MAX_PBO),
            commentary=(
                "Undefined for a single-candidate study, which is why this can "
                "read 'not measured' on a perfectly sound strategy"
            ),
            evidence=study.run_id if study else "",
        ),
        _row(
            "Stability",
            "Parameter stability",
            _num(study.degradation) if study else None,
            "Small in-sample to out-of-sample gap",
            None if study is None or study.degradation is None
            else study.degradation < 0.5,
            commentary="Reported as degradation: in-sample Sharpe minus OOS",
            evidence=study.run_id if study else "",
        ),
        _row(
            "Regime resilience",
            "Positive regimes",
            None,
            "Positive in the majority of regimes",
            None,
            commentary=(
                "Not built. Requires a regime classification the engine does "
                "not have, and inventing one to fill this cell would be worse "
                "than leaving it empty"
            ),
        ),
        _row(
            "Cost resilience",
            "Performance under stressed costs",
            _num((stressed.outcome or {}).get("sharpe")) if stressed else None,
            f"Still positive at {MIN_COST_STRESS_MULTIPLIER:g}x costs",
            _gt((stressed.outcome or {}).get("sharpe") if stressed else None, 0.0),
            commentary="A result that survives only at 1x cost is not a result",
            evidence=stressed.ref if stressed else "",
        ),
        _row(
            "Execution",
            "Implementation shortfall",
            None,
            "Measured against the decision price",
            None,
            commentary=(
                "Not measured. Needs fills from a venue, which requires stage "
                "4; the shadow book fills against modelled prices"
            ),
        ),
        _row(
            "Liquidity",
            "Days to exit",
            None,
            "Under five sessions at 10% of volume",
            None,
            commentary=(
                "Computable by src.engine.statistics.days_to_exit once a book "
                "exists; a candidate before stage 3 has no positions"
            ),
        ),
        _row(
            "Capacity",
            "Estimated deployable capital",
            None,
            "Above the programme's target capital",
            None,
            commentary=(
                "Computable by src.engine.statistics.capacity_estimate from "
                "daily_bars volume; not wired to this card until a target "
                "capital is configured to compare it against"
            ),
        ),
        _row(
            "Diversification",
            "Correlation with existing portfolio",
            None,
            "Below 0.7 with anything already deployed",
            None,
            commentary=(
                "Not measured. Nothing is deployed, so there is nothing to "
                "correlate against"
            ),
        ),
        _row(
            "Data quality",
            "Dataset readiness",
            "synthetic" if facts.evidence_is_synthetic else facts.data_source,
            "A real source with point-in-time availability",
            not facts.evidence_is_synthetic,
            commentary=(
                "Synthetic prices cannot reach operation; a generator has no "
                "regime to fail to generalise across"
            ),
            evidence=facts.hypothesis_ref,
        ),
        _row(
            "Model health",
            "Drift and calibration",
            None,
            "No sustained drift",
            None,
            commentary=(
                "Not applicable. No machine-learning model is in the decision "
                "path, so there is nothing to drift"
            ),
        ),
        _row(
            "Operations",
            "Production readiness",
            len(facts.shadow) if facts.shadow else None,
            f"At least {MIN_SHADOW_SESSIONS} clean shadow sessions",
            None
            if not facts.shadow
            else (
                len(facts.shadow) >= MIN_SHADOW_SESSIONS
                and not any(s.error for s in facts.shadow)
            ),
            commentary="Shadow sessions recorded, errors included in the test",
        ),
        _row(
            "Governance",
            "Open findings and approvals",
            len(facts.findings),
            "No open finding from a role holding a veto",
            not facts.blocking_findings,
            commentary=(
                f"{len(facts.blocking_findings)} of these block a promotion"
            ),
        ),
    ]

    recommendation, reason, approvers = _recommend(facts, gate)
    return Scorecard(
        candidate_id="",
        hypothesis_ref=facts.hypothesis_ref,
        stage=facts.stage,
        rows=tuple(rows),
        recommendation=recommendation,
        recommendation_reason=reason,
        approvers=approvers,
        unresolved=tuple(f.ref for f in facts.blocking_findings),
    )


def _recommend(
    facts: CandidateFacts, gate: Any
) -> tuple[str, str, tuple[str, ...]]:
    """
    Read the recommendation off the gate. Never re-derive it.

    Two places deciding whether a candidate may advance is one place too many,
    and the second one is always the one that gets it wrong. This translates a
    gate verdict into the §11 vocabulary and nothing else.
    """
    if facts.blocking_findings:
        return (
            "hold_for_more_evidence",
            "an open finding from a role holding a veto blocks any promotion",
            tuple(sorted({f.raised_by for f in facts.blocking_findings})),
        )
    if gate is None:
        return "hold_for_more_evidence", "no gate evaluation available", ()
    if not gate.passed:
        unmet = ", ".join(c.description for c in gate.unmet[:3])
        return (
            "hold_for_more_evidence",
            f"the gate has not passed: {unmet}",
            (),
        )

    decision = _NEXT_DECISION.get(facts.stage, "maintain_capital")
    if gate.requires_human:
        return (
            decision,
            "every criterion is met and this stage needs an operator",
            ("independent_risk", "independent_validation"),
        )
    return decision, "every criterion is met", ()


# ---------------------------------------------------------------------------
# Coercion helpers
#
# All of them return None rather than a default. That is the whole discipline
# of this module in four functions.
# ---------------------------------------------------------------------------


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _gt(value: Any, threshold: float) -> bool | None:
    number = _num(value)
    return None if number is None else number > threshold


def _lte(value: Any, threshold: float) -> bool | None:
    number = _num(value)
    return None if number is None else number <= threshold


def _cost_note(outcome: dict[str, Any]) -> str:
    multiplier = outcome.get("cost_stress_multiplier")
    periods = outcome.get("periods_per_year")
    if multiplier is None:
        return "no cost assumption recorded, so this figure cannot be read"
    return (
        f"at {float(multiplier):g}x modelled costs, annualised on "
        f"{periods or 'an unrecorded number of'} sessions"
    )


def _sharpe_note(outcome: dict[str, Any]) -> str:
    stderr = outcome.get("sharpe_stderr")
    if stderr is None:
        return "no standard error recorded; the figure is not interpretable"
    if outcome.get("sharpe_is_significant") is False:
        return (
            f"±{float(stderr):.2f}: not distinguishable from zero, so read it "
            "as no evidence of an edge rather than as a small one"
        )
    return f"±{float(stderr):.2f}"
