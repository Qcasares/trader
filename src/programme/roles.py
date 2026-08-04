"""
roles.py
--------
The twelve specialists, and what each of them is allowed to do about it.

The operating prompt asks for a coordinated team rather than one assistant, and
for disagreement to be exposed rather than blended into consensus. That is the
easy half. The hard half is making a role's authority mean something, and the
answer here is narrow on purpose:

    a verdict is commentary          -- stored, rendered, consulted by nobody
    a finding is a record            -- stored, rendered, and counted
    a finding from a veto role,
    open, at high or critical        -- blocks the gate, mechanically

Nothing a role writes is read by :mod:`src.programme.gates`. The gate reads
``findings.severity`` and ``findings.raised_by`` and stops. So a role cannot
argue a candidate forward by being persuasive, and cannot argue one backward
either: raising a blocking finding is an act with a fixed effect, recorded
under the role's name, and only an operator can clear it — enforced by a CHECK
constraint in migration 0008, not by this module's good intentions.

Which roles run when
~~~~~~~~~~~~~~~~~~~~
Not all twelve on every pass. A compliance review of a stage-0 concept with no
data and no model is a paragraph of nothing, and twelve paragraphs of nothing
per tick is how a review process becomes wallpaper. Each stage summons the
roles whose mandate is actually engaged by the evidence that exists at that
point.

The programme director is deliberately absent from every stage list. Its
mandate is prioritisation and it holds no veto, so its output would be
commentary on commentary.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from src.programme.gates import BLOCKING_SEVERITIES, VETO_ROLES

logger = logging.getLogger(__name__)


class Role(BaseModel):
    """A specialist: who they are and what they are looking for."""

    model_config = {"frozen": True}

    key: str
    title: str
    mandate: str
    #: What this role should be trying to find. Phrased as suspicion rather
    #: than as a checklist, because a checklist is answerable by a model
    #: pattern-matching the checklist.
    looks_for: str

    @property
    def holds_veto(self) -> bool:
        return self.key in VETO_ROLES


ROLES: tuple[Role, ...] = (
    Role(
        key="quant_research",
        title="Quantitative research lead",
        mandate="Develop economically motivated, statistically defensible ideas.",
        looks_for=(
            "A mechanism that names who is on the other side and why they "
            "accept the worse expected outcome. A result that survives its "
            "own parameter neighbourhood. Evidence that the number quoted is "
            "not the best of many quietly taken."
        ),
    ),
    Role(
        key="data_engineering",
        title="Data engineering lead",
        mandate="Provide point-in-time correct, traceable data.",
        looks_for=(
            "Information used before it could have been known. Survivorship "
            "in the universe. Corporate actions handled inconsistently "
            "between the signal series and the money series. A window whose "
            "first years contain fewer instruments than the strategy claims "
            "to hold."
        ),
    ),
    Role(
        key="machine_learning",
        title="Machine-learning lead",
        mandate="Govern any model used to forecast, rank or classify.",
        looks_for=(
            "Complexity without demonstrated incremental value over a naive "
            "baseline. Target leakage. Validation that ignores time ordering."
        ),
    ),
    Role(
        key="portfolio_construction",
        title="Portfolio construction lead",
        mandate="Turn signals into a portfolio inside risk and liquidity limits.",
        looks_for=(
            "Concentration the weighting scheme did not intend. Turnover the "
            "cost model was never asked about. Correlation with what is "
            "already deployed, which makes a diversifying claim false."
        ),
    ),
    Role(
        key="independent_risk",
        title="Independent risk officer",
        mandate="Protect capital, independently of whether the result is good.",
        looks_for=(
            "A drawdown the halting limits would not have caught. Exposure "
            "concentrated in one regime or a handful of trades. Any path by "
            "which this could exceed its intended risk, including via a "
            "control that is present but inert."
        ),
    ),
    Role(
        key="execution",
        title="Execution engineering lead",
        mandate="Turn approved changes into orders without giving back the edge.",
        looks_for=(
            "Fills assumed at prices a venue would not have given. Trades "
            "sized beyond plausible participation. An edge smaller than the "
            "spread it must cross."
        ),
    ),
    Role(
        key="platform",
        title="Platform and MLOps lead",
        mandate="Keep it reproducible, observable and reversible.",
        looks_for=(
            "A result that cannot be reproduced from what was recorded. A "
            "missing commit, seed or dataset manifest. No stated way back if "
            "this is wrong."
        ),
    ),
    Role(
        key="independent_validation",
        title="Independent validation lead",
        mandate="Challenge every claim made by the people who produced it.",
        looks_for=(
            "A metric that does not follow from the rows it cites. An "
            "acceptance criterion looser than the hypothesis promised. "
            "Multiple testing the variant count does not admit to."
        ),
    ),
    Role(
        key="compliance",
        title="Compliance and model-governance lead",
        mandate="Approvals, records and permitted data use.",
        looks_for=(
            "Data used outside its licence. A decision with no recorded "
            "rationale. A running configuration that differs from the "
            "approved one."
        ),
    ),
    Role(
        key="operations",
        title="Trading operations and reconciliation lead",
        mandate="Make the intended portfolio and the actual one agree.",
        looks_for=(
            "State that cannot be reconciled after a restart. Positions or "
            "cash with no independent second source. A failure mode with no "
            "safe state to fall into."
        ),
    ),
    Role(
        key="adversarial_review",
        title="Adversarial review",
        mandate="Prove this should not be trusted.",
        looks_for=(
            "The cheapest story in which this result is an artefact. What "
            "breaks when volatility doubles, liquidity halves, the feed goes "
            "stale, or the broker rejects half the orders. Assume the result "
            "is wrong and find out how."
        ),
    ),
    Role(
        key="programme_director",
        title="Programme director",
        mandate="Prioritise, and keep complexity economically justified.",
        looks_for=(
            "Whether this is worth the attention it is consuming, and whether "
            "a simpler thing already in the portfolio does the same job."
        ),
    ),
)

ROLES_BY_KEY: dict[str, Role] = {role.key: role for role in ROLES}

#: Which roles are summoned at each stage.
#:
#: A compliance review of a stage-0 concept with no data and no model produces
#: a paragraph of nothing, and twelve of those per pass is how a review process
#: becomes wallpaper nobody reads. The set widens as there is more to review.
ROLES_BY_STAGE: dict[int, tuple[str, ...]] = {
    0: ("quant_research", "data_engineering", "adversarial_review"),
    1: (
        "quant_research",
        "data_engineering",
        "independent_risk",
        "execution",
        "adversarial_review",
    ),
    2: (
        "independent_validation",
        "independent_risk",
        "data_engineering",
        "portfolio_construction",
        "machine_learning",
        "adversarial_review",
    ),
    3: (
        "independent_validation",
        "independent_risk",
        "operations",
        "platform",
        "execution",
    ),
    4: (
        "independent_risk",
        "operations",
        "compliance",
        "platform",
        "independent_validation",
    ),
}

#: Above this stage the full panel is summoned. Capital is exposed there and
#: the cost of an unread paragraph is smaller than the cost of an unasked
#: question.
FULL_PANEL_FROM_STAGE = 5


def roles_for_stage(stage: int) -> tuple[Role, ...]:
    if stage >= FULL_PANEL_FROM_STAGE:
        return ROLES
    return tuple(ROLES_BY_KEY[key] for key in ROLES_BY_STAGE.get(stage, ()))


# ---------------------------------------------------------------------------
# What a role may return
# ---------------------------------------------------------------------------


class ProposedFinding(BaseModel):
    """A defect a role wants on the record."""

    model_config = {"extra": "forbid"}

    severity: str
    title: str = Field(min_length=10, max_length=200)
    detail: str = Field(min_length=20)
    remediation: str = Field(min_length=10)


class Assessment(BaseModel):
    """One role's view, and anything it wants recorded."""

    model_config = {"extra": "forbid"}

    verdict: str
    summary: str = Field(min_length=20, max_length=1500)
    findings: list[ProposedFinding] = Field(default_factory=list, max_length=5)


VERDICTS = ("support", "concern", "object", "abstain")

SEVERITIES = ("low", "medium", "high", "critical")

#: The most a single role may raise in one pass.
#:
#: Not a quality control — a noise one. A role that finds nine critical defects
#: in a candidate has either found one defect described nine ways or is
#: producing a list nobody will action. Five is enough to stop something and
#: few enough to read.
MAX_FINDINGS_PER_ASSESSMENT = 5


class InvalidAssessmentError(ValueError):
    """A role returned something outside the vocabulary it was given."""


def validate_assessment(assessment: Assessment) -> None:
    """
    Check a reply against the fixed vocabulary, raising with the reason.

    Verdicts and severities are closed sets. A model that returns "moderate"
    or "medium-high" is not making a subtle point; it is producing a value the
    gate cannot compare, and a severity the gate cannot compare is a finding
    that silently never blocks.
    """
    if assessment.verdict not in VERDICTS:
        raise InvalidAssessmentError(
            f"verdict must be one of {VERDICTS}, got {assessment.verdict!r}"
        )
    for finding in assessment.findings:
        if finding.severity not in SEVERITIES:
            raise InvalidAssessmentError(
                f"severity must be one of {SEVERITIES}, "
                f"got {finding.severity!r}"
            )
    if len(assessment.findings) > MAX_FINDINGS_PER_ASSESSMENT:
        raise InvalidAssessmentError(
            f"at most {MAX_FINDINGS_PER_ASSESSMENT} findings per assessment"
        )


def system_prompt(role: Role) -> str:
    veto = (
        "You hold a veto. A finding you raise at high or critical severity "
        "stops this candidate advancing until an operator closes it, and you "
        "cannot close it yourself. Use it when the evidence warrants it and "
        "not to register unease."
        if role.holds_veto
        else "You do not hold a veto. A finding you raise is recorded and "
        "counted; it does not halt anything. Say what you think anyway."
    )
    return f"""\
You are the {role.title} of a systematic trading programme.

Your mandate: {role.mandate}

What you are looking for: {role.looks_for}

{veto}

Rules, all of them hard:
- You are shown rows a deterministic engine produced. Reason about those. \
Never state a performance figure that is not in what you were shown, and never \
predict one.
- Do not agree for the sake of agreeing. If another role would take a \
different view, that is the point of there being more than one of you.
- `abstain` is a real answer. Use it when the evidence you would need does not \
exist yet, rather than composing a view to fill the field.
- A finding must name a specific defect and what would fix it. "Needs more \
testing" is not a finding.
- Severity is one of low, medium, high, critical. High and critical are for \
defects that make the result untrustworthy or unsafe, not for things you would \
prefer to see done differently.
- Reply with a single JSON object: verdict, summary, findings (a list, \
possibly empty, each with severity, title, detail, remediation).
"""


def blocking_count(assessment: Assessment, role: Role) -> int:
    """How many of this assessment's findings will actually halt a promotion."""
    if not role.holds_veto:
        return 0
    return sum(1 for f in assessment.findings if f.severity in BLOCKING_SEVERITIES)


def facts_brief(candidate: dict[str, Any], gate: dict[str, Any]) -> str:
    """
    Render what every role is shown.

    One rendering for all of them, so a disagreement between two roles is a
    disagreement about the same evidence rather than an artefact of one having
    been told more than the other.
    """
    lines = [
        f"Hypothesis {candidate.get('hypothesis_ref')}: "
        f"{candidate.get('hypothesis_title')}",
        f"Strategy: {candidate.get('strategy_name')} "
        f"with {candidate.get('params')}",
        f"Universe: {', '.join(candidate.get('universe') or []) or 'none'}",
        f"Window: {candidate.get('start_session')} to "
        f"{candidate.get('end_session')}",
        f"Data source: {candidate.get('data_source')}"
        + (
            "  (SYNTHETIC — generated prices, no regime to generalise across)"
            if candidate.get("evidence_is_synthetic")
            else ""
        ),
        f"Stage: {candidate.get('stage')}",
        "",
        f"Gate {gate.get('from_stage_name')} -> {gate.get('to_stage_name')}: "
        f"{'passed' if gate.get('passed') else 'not passed'}",
    ]
    for criterion in gate.get("criteria") or []:
        mark = "met " if criterion.get("met") else "UNMET"
        lines.append(f"  [{mark}] {criterion.get('description')}")
        if criterion.get("detail"):
            lines.append(f"          {criterion['detail']}")
        evidence = criterion.get("evidence")
        if evidence:
            lines.append(
                f"          evidence: {evidence.get('table')} "
                f"{evidence.get('row_id')} = {evidence.get('value')}"
            )

    experiments = candidate.get("experiments") or []
    if experiments:
        lines += ["", "Experiments:"]
        for experiment in experiments:
            lines.append(
                f"  {experiment.get('ref')} {experiment.get('kind')} "
                f"{experiment.get('status')} -> "
                f"{experiment.get('conclusion') or 'no conclusion'}"
            )
            outcome = experiment.get("outcome") or {}
            if outcome:
                shown = {
                    k: outcome[k]
                    for k in (
                        "sharpe",
                        "sharpe_stderr",
                        "sharpe_is_significant",
                        "cagr",
                        "max_drawdown",
                        "volatility",
                        "turnover_annual",
                        "n_sessions",
                        "effective_start",
                        "cost_stress_multiplier",
                        "periods_per_year",
                    )
                    if k in outcome
                }
                lines.append(f"      {shown}")
            lines.append(
                f"      preregistered: {experiment.get('preregistered_criteria')}"
            )
    else:
        lines += ["", "Experiments: none recorded."]

    return "\n".join(lines)
