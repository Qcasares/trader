"""
gates.py
--------
The promotion gates. Pure, and deliberately so.

This module decides whether a candidate has earned its next lifecycle stage. It
takes a frozen snapshot of facts and returns a verdict with every criterion and
the row that evidences it. It performs no I/O, opens no connection, reads no
clock, and never touches a model client.

That is the same shape as ``src/core``, for the same reason: the decision that
matters most is the one that must be testable without a database and without a
network. ``tests/unit/test_programme_gates.py`` drives every transition in both
directions with nothing but dataclasses.

The division of labour in the programme is:

    the model proposes            -> hypothesis cards, configurations
    the engine measures           -> backtest_runs, walkforward_runs
    this module decides           -> pass or fail, per criterion, with evidence

A model cannot argue with a gate, because a gate does not read prose. If a
criterion is unmet the only route forward is to produce the missing row.

Synthetic data
~~~~~~~~~~~~~~
Synthetic evidence carries a candidate through the research stages and is
refused at gate 2 -> 3. The reason is stated plainly in CLAUDE.md: no result in
this repository is a real backtest, because the equity data hosts are blocked
by this environment's egress policy. Requiring real prices at gate 1 -> 2 would
make the pipeline unexercisable, and an unexercisable pipeline is not a safer
one — it is an untested one. The refusal sits at the gate before anything
operates, which is where the API already refuses synthetic data for
walk-forward studies and deployments.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

#: The lifecycle from the operating prompt's section 7.7.
STAGE_NAMES: dict[int, str] = {
    0: "concept",
    1: "rapid research",
    2: "independent validation",
    3: "shadow mode",
    4: "broker paper trading",
    5: "canary production",
    6: "graduated production",
    7: "mature production",
    8: "reduced, suspended or retired",
}

#: Promotions into this stage or beyond need an operator, never the runner.
#:
#: Stage 5 is canary production: the first stage at which capital is exposed to
#: a venue under the programme's own decision. The operating prompt prohibits an
#: LLM from changing production capital allocation, and this is the line that
#: prohibition draws in code.
FIRST_HUMAN_GATED_STAGE = 5

#: Fields a hypothesis card must carry before any research is done against it.
#:
#: Taken from section 7.1. Vague hypotheses are rejected here rather than
#: argued with: "use AI to predict prices" cannot supply a falsification test,
#: so it cannot leave stage 0.
REQUIRED_CARD_FIELDS: tuple[str, ...] = (
    "economic_mechanism",
    "why_it_persists",
    "instruments",
    "trading_horizon",
    "entry_exit_concept",
    "expected_return_source",
    "expected_risks",
    "expected_turnover",
    "expected_capacity",
    "data_requirements",
    "alternative_explanations",
    "simplest_baseline",
    "falsification_test",
    "acceptance_criteria",
    "rejection_criteria",
)

#: Cost multiplier at which a result must still hold to clear gate 1 -> 2.
#:
#: Doubling costs is not a stress test of the venue; it is a test of whether the
#: result was ever more than the cost model.
MIN_COST_STRESS_MULTIPLIER = 2.0

#: How far a replication may drift from the result it replicates, in Sharpe.
REPLICATION_SHARPE_TOLERANCE = 0.10

#: Minimum bars a symbol needs in the window before the universe counts as
#: available. One quarter of sessions, so a symbol that listed late is caught
#: at stage 0 rather than silently shrinking the weighting denominator later.
MIN_BARS_PER_SYMBOL = 60

#: Roles whose finding stops a promotion.
#:
#: Read straight off the operating prompt's decision-rights matrix, whose "may
#: veto" column names risk, validation and compliance on the promotion rows,
#: and which elsewhere lets data engineering block a dataset, the platform lead
#: block a deployment lacking rollback, and operations stop trading when
#: reconciliation fails. A role not in this set can still raise a finding; it
#: simply does not halt anything by doing so, which is the difference between
#: an objection and a veto.
VETO_ROLES: frozenset[str] = frozenset(
    {
        "independent_risk",
        "independent_validation",
        "compliance",
        "data_engineering",
        "platform",
        "operations",
        "adversarial_review",
    }
)

#: Severities that block. Anything below is recorded and does not halt.
BLOCKING_SEVERITIES: frozenset[str] = frozenset({"high", "critical"})

#: Sessions a candidate must operate in shadow before it may reach a broker.
#:
#: Twenty is about a month of NYSE sessions. Not chosen because a month proves
#: the strategy works — it proves nothing of the kind, and a Sharpe over twenty
#: sessions has a standard error near ±4. It is long enough for the *operation*
#: to fail: a monthly rebalance to actually fire, a data gap to appear, a
#: schedule to drift. That is what this stage is evidencing.
MIN_SHADOW_SESSIONS = 20


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Evidence:
    """Where a criterion's answer came from. A criterion without one is unmet."""

    table: str
    row_id: str
    value: Any = None

    def as_dict(self) -> dict[str, Any]:
        return {"table": self.table, "row_id": self.row_id, "value": self.value}


@dataclass(frozen=True, slots=True)
class Criterion:
    """One requirement, and whether the rows satisfy it."""

    id: str
    description: str
    met: bool
    evidence: Evidence | None = None
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "met": self.met,
            "detail": self.detail,
            "evidence": self.evidence.as_dict() if self.evidence else None,
        }


@dataclass(frozen=True, slots=True)
class GateResult:
    """The verdict on one transition."""

    from_stage: int
    to_stage: int
    criteria: tuple[Criterion, ...]
    requires_human: bool

    @property
    def passed(self) -> bool:
        """Every criterion met. An empty criteria list never passes."""
        return bool(self.criteria) and all(c.met for c in self.criteria)

    @property
    def unmet(self) -> tuple[Criterion, ...]:
        return tuple(c for c in self.criteria if not c.met)

    def as_dict(self) -> dict[str, Any]:
        return {
            "from_stage": self.from_stage,
            "to_stage": self.to_stage,
            "from_stage_name": STAGE_NAMES.get(self.from_stage, "unknown"),
            "to_stage_name": STAGE_NAMES.get(self.to_stage, "unknown"),
            "passed": self.passed,
            "requires_human": self.requires_human,
            "criteria": [c.as_dict() for c in self.criteria],
        }


@dataclass(frozen=True, slots=True)
class ExperimentFact:
    """One experiment, reduced to what a gate needs to know about it."""

    ref: str
    kind: str
    status: str
    conclusion: str | None = None
    backtest_run_id: str | None = None
    walkforward_run_id: str | None = None
    data_source: str = ""
    cost_stress_multiplier: float | None = None
    seed: int | None = None
    outcome: Mapping[str, Any] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded"


@dataclass(frozen=True, slots=True)
class WalkforwardFact:
    """A walk-forward study's verdict, and the parameters it studied."""

    run_id: str
    status: str
    params: Mapping[str, Any] = field(default_factory=dict)
    is_robust: bool | None = None
    degradation: float | None = None


@dataclass(frozen=True, slots=True)
class FindingFact:
    """An open finding, reduced to what decides whether it blocks."""

    ref: str
    raised_by: str
    severity: str
    title: str
    status: str = "open"

    @property
    def blocks(self) -> bool:
        """
        Whether this finding halts a promotion.

        Three conditions, all mechanical: it is open, its severity is high or
        critical, and the role that raised it holds a veto. No part of this
        reads the finding's text, so a well-argued low-severity note cannot
        block and a terse critical one from the risk officer cannot be talked
        past.
        """
        return (
            self.status == "open"
            and self.severity in BLOCKING_SEVERITIES
            and self.raised_by in VETO_ROLES
        )


@dataclass(frozen=True, slots=True)
class ShadowFact:
    """One recorded shadow session."""

    session: date
    rebalanced: bool
    order_intents: int = 0
    underfunded: int = 0
    error: str | None = None


@dataclass(frozen=True, slots=True)
class CandidateFacts:
    """
    Everything a gate is allowed to know.

    Assembled from rows by :mod:`src.programme.facts`. Nothing in here is a
    model's opinion: ``hypothesis_card`` may have been drafted by a model, but
    the gates only ever check that its fields are *present*, never that they
    are persuasive.
    """

    stage: int
    status: str
    params: Mapping[str, Any]
    universe: tuple[str, ...]
    start_session: date
    end_session: date
    data_source: str
    evidence_is_synthetic: bool
    hypothesis_ref: str
    hypothesis_owner: str
    hypothesis_card: Mapping[str, Any]
    #: symbol -> number of bars available in the requested window.
    universe_coverage: Mapping[str, int] = field(default_factory=dict)
    experiments: tuple[ExperimentFact, ...] = ()
    walkforwards: tuple[WalkforwardFact, ...] = ()
    #: Every finding still open against this candidate, blocking or not.
    findings: tuple[FindingFact, ...] = ()
    #: Shadow sessions recorded, oldest first.
    shadow: tuple[ShadowFact, ...] = ()
    #: Whether a deployment exists for this candidate to operate against.
    has_deployment: bool = False

    @property
    def blocking_findings(self) -> tuple[FindingFact, ...]:
        return tuple(f for f in self.findings if f.blocks)

    def succeeded_of_kind(self, kind: str) -> ExperimentFact | None:
        """The first succeeded experiment of a kind, or ``None``."""
        for exp in self.experiments:
            if exp.kind == kind and exp.succeeded:
                return exp
        return None


# ---------------------------------------------------------------------------
# Preregistered criteria
# ---------------------------------------------------------------------------

_COMPARATORS = {
    ">=": lambda a, b: a >= b,
    ">": lambda a, b: a > b,
    "<=": lambda a, b: a <= b,
    "<": lambda a, b: a < b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


def evaluate_preregistered(
    criteria: Sequence[Mapping[str, Any]], outcome: Mapping[str, Any]
) -> bool | None:
    """
    Judge a recorded outcome against criteria fixed before the run.

    Each criterion is ``{"metric": str, "op": str, "value": number}``. Returns
    ``None`` when the outcome does not carry a metric a criterion names, which
    is *not* the same as failing: an unanswerable test has not been passed and
    has not been failed, and conflating the two is how a missing measurement
    becomes a green tick.

    An empty criteria list returns ``None``. Preregistering nothing is not the
    same as preregistering something satisfied trivially.
    """
    if not criteria:
        return None

    verdicts: list[bool] = []
    for criterion in criteria:
        metric = criterion.get("metric")
        op = criterion.get("op")
        target = criterion.get("value")
        if metric is None or op not in _COMPARATORS:
            return None
        observed = outcome.get(metric)
        if observed is None:
            return None
        try:
            verdicts.append(_COMPARATORS[op](float(observed), float(target)))
        except (TypeError, ValueError):
            return None
    return all(verdicts)


def replication_agrees(
    reference: Mapping[str, Any],
    replicate: Mapping[str, Any],
    tolerance: float = REPLICATION_SHARPE_TOLERANCE,
) -> bool:
    """
    Whether a re-run reproduced the result it was checking.

    Compared on Sharpe because that is the figure a promotion would rest on. A
    missing Sharpe on either side is a disagreement: a replication that cannot
    be compared has not replicated anything.
    """
    a = reference.get("sharpe")
    b = replicate.get("sharpe")
    if a is None or b is None:
        return False
    try:
        return abs(float(a) - float(b)) <= tolerance
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# The gates
# ---------------------------------------------------------------------------


def evaluate(facts: CandidateFacts) -> GateResult:
    """
    Judge the transition out of the candidate's current stage.

    Stages this slice cannot evidence return a single unmet criterion naming
    the missing capability, rather than an empty list or an exception. An
    operator reading the UI should see *why* a candidate is parked, and
    "shadow-mode operation is not built yet" is a better answer than silence.
    """
    from_stage = facts.stage
    to_stage = min(from_stage + 1, 8)
    requires_human = to_stage >= FIRST_HUMAN_GATED_STAGE

    builder = _GATES.get(from_stage)
    if builder is None:
        criteria = (
            Criterion(
                id="capability_absent",
                description=(
                    f"Promotion out of stage {from_stage} "
                    f"({STAGE_NAMES.get(from_stage, 'unknown')}) is not "
                    "implemented in this slice"
                ),
                met=False,
                detail=_MISSING_CAPABILITY.get(
                    from_stage, "no gate is defined for this stage"
                ),
            ),
        )
    else:
        criteria = builder(facts)

    # Prepended to every gate, including the unbuilt ones, and first in the
    # list because it is the criterion that overrides the rest. A veto is not
    # one consideration among several: a candidate with an open critical
    # finding from the risk officer does not advance because its backtest is
    # good.
    return GateResult(
        from_stage=from_stage,
        to_stage=to_stage,
        criteria=(_no_blocking_findings(facts), *criteria),
        requires_human=requires_human,
    )


def _no_blocking_findings(facts: CandidateFacts) -> Criterion:
    """
    The veto, expressed as a criterion.

    Named findings rather than a count, because "3 open findings" tells an
    operator to go looking and the references tell them where.
    """
    blocking = facts.blocking_findings
    return Criterion(
        id="no_blocking_findings",
        description=(
            "No open high or critical finding from a role holding a veto"
        ),
        met=not blocking,
        evidence=Evidence("findings", ",".join(f.ref for f in blocking))
        if blocking
        else None,
        detail=(
            ""
            if not blocking
            else "; ".join(
                f"{f.ref} ({f.raised_by}, {f.severity}): {f.title}"
                for f in blocking
            )
        ),
    )


def _gate_concept_to_research(facts: CandidateFacts) -> tuple[Criterion, ...]:
    """Stage 0 -> 1. The card is complete and the data exists."""
    card = facts.hypothesis_card
    missing = [f for f in REQUIRED_CARD_FIELDS if not str(card.get(f, "")).strip()]
    criteria = [
        Criterion(
            id="card_complete",
            description="The hypothesis card carries every required field",
            met=not missing,
            evidence=Evidence("hypotheses", facts.hypothesis_ref, len(card)),
            detail="" if not missing else f"missing: {', '.join(missing)}",
        ),
        Criterion(
            id="owner_named",
            description="The hypothesis has a named owner",
            met=bool(facts.hypothesis_owner.strip()),
            evidence=Evidence(
                "hypotheses", facts.hypothesis_ref, facts.hypothesis_owner
            ),
        ),
        Criterion(
            id="window_ordered",
            description="The requested window runs forwards",
            met=facts.end_session > facts.start_session,
            detail=f"{facts.start_session} to {facts.end_session}",
        ),
    ]

    if not facts.universe:
        criteria.append(
            Criterion(
                id="universe_available",
                description="Every symbol has bars in the requested window",
                met=False,
                detail="the candidate has an empty universe",
            )
        )
    else:
        thin = sorted(
            s
            for s in facts.universe
            if facts.universe_coverage.get(s, 0) < MIN_BARS_PER_SYMBOL
        )
        criteria.append(
            Criterion(
                id="universe_available",
                description=(
                    f"Every symbol has at least {MIN_BARS_PER_SYMBOL} bars in "
                    "the requested window"
                ),
                met=not thin,
                evidence=Evidence(
                    "daily_bars", ",".join(facts.universe), dict(
                        facts.universe_coverage
                    )
                ),
                detail="" if not thin else f"too few bars: {', '.join(thin)}",
            )
        )
    return tuple(criteria)


def _gate_research_to_validation(facts: CandidateFacts) -> tuple[Criterion, ...]:
    """
    Stage 1 -> 2. The screening evidence exists and says yes.

    Every criterion here is a row that must exist, not a number that must be
    impressive. Whether the number is good enough was fixed before the run, in
    ``preregistered_criteria``, and is checked mechanically.
    """
    backtest = facts.succeeded_of_kind("backtest")
    stressed = next(
        (
            e
            for e in facts.experiments
            if e.kind == "cost_stress"
            and e.succeeded
            and (e.cost_stress_multiplier or 0) >= MIN_COST_STRESS_MULTIPLIER
        ),
        None,
    )
    neighbourhood = facts.succeeded_of_kind("parameter_neighbourhood")
    benchmark = facts.succeeded_of_kind("benchmark")

    criteria = [
        Criterion(
            id="backtest_succeeded",
            description="A backtest completed at base costs",
            met=backtest is not None,
            evidence=(
                Evidence("backtest_runs", backtest.backtest_run_id or "", None)
                if backtest
                else None
            ),
        ),
        Criterion(
            id="cost_stress",
            description=(
                "The result survives costs stressed by at least "
                f"{MIN_COST_STRESS_MULTIPLIER:g}x"
            ),
            met=stressed is not None,
            evidence=(
                Evidence(
                    "experiments", stressed.ref, stressed.cost_stress_multiplier
                )
                if stressed
                else None
            ),
            detail=(
                ""
                if stressed
                else "no succeeded cost_stress experiment at the required "
                "multiplier"
            ),
        ),
        Criterion(
            id="parameter_neighbourhood",
            description="Performance was measured at neighbouring parameters",
            met=neighbourhood is not None,
            evidence=(
                Evidence("experiments", neighbourhood.ref) if neighbourhood else None
            ),
        ),
        Criterion(
            id="benchmark_comparison",
            description="The result was compared against a passive benchmark",
            met=benchmark is not None,
            evidence=Evidence("experiments", benchmark.ref) if benchmark else None,
        ),
    ]

    effective_start = (backtest.outcome.get("effective_start") if backtest else None)
    criteria.append(
        Criterion(
            id="effective_start_recorded",
            description=(
                "The window over which the full universe was actually listed "
                "is recorded"
            ),
            met=effective_start is not None,
            evidence=(
                Evidence("backtest_runs", backtest.backtest_run_id or "",
                         effective_start)
                if backtest
                else None
            ),
            detail=(
                ""
                if effective_start is not None
                else "a metric without effective_start describes a different "
                "strategy from the one requested"
            ),
        )
    )

    verdict = (
        evaluate_preregistered(
            list(backtest.outcome.get("preregistered_criteria") or []),
            backtest.outcome,
        )
        if backtest
        else None
    )
    criteria.append(
        Criterion(
            id="preregistered_criteria_met",
            description=(
                "The outcome satisfies the acceptance criteria fixed before "
                "the run"
            ),
            met=verdict is True,
            evidence=Evidence("experiments", backtest.ref) if backtest else None,
            detail=(
                ""
                if verdict is True
                else (
                    "the criteria could not be evaluated against the recorded "
                    "outcome"
                    if verdict is None
                    else "the recorded outcome does not satisfy them"
                )
            ),
        )
    )
    return tuple(criteria)


def _gate_validation_to_shadow(facts: CandidateFacts) -> tuple[Criterion, ...]:
    """
    Stage 2 -> 3. Independent challenge survived, on real prices.

    This is the gate synthetic evidence cannot pass. It is also the gate that
    requires a walk-forward study of *these* parameters: a study of a
    neighbouring configuration vouches for the neighbour.
    """
    robust = next(
        (
            w
            for w in facts.walkforwards
            if w.status == "succeeded"
            and w.is_robust is True
            and dict(w.params) == dict(facts.params)
        ),
        None,
    )
    replication = facts.succeeded_of_kind("replication")
    backtest = facts.succeeded_of_kind("backtest")
    significance = (
        backtest.outcome.get("sharpe_is_significant") if backtest else None
    )
    limitations = facts.hypothesis_card.get("limitations")

    return (
        Criterion(
            id="evidence_is_real",
            description="No synthetic data underwrites this candidate",
            met=not facts.evidence_is_synthetic and facts.data_source != "synthetic",
            evidence=Evidence("candidates", facts.hypothesis_ref, facts.data_source),
            detail=(
                ""
                if not facts.evidence_is_synthetic
                else "synthetic prices cannot support operation; re-run the "
                "candidate against a real source"
            ),
        ),
        Criterion(
            id="walkforward_robust",
            description=(
                "A completed walk-forward study of these exact parameters "
                "returned a robust verdict"
            ),
            met=robust is not None,
            evidence=(
                Evidence("walkforward_runs", robust.run_id, robust.degradation)
                if robust
                else None
            ),
            detail=(
                ""
                if robust
                else "no robust study for these parameters; a study of a "
                "neighbouring configuration vouches for the neighbour"
            ),
        ),
        Criterion(
            id="replicated",
            description="An independent re-run reproduced the result",
            met=replication is not None and replication.conclusion == "pass",
            evidence=Evidence("experiments", replication.ref) if replication else None,
        ),
        Criterion(
            id="sharpe_significance_recorded",
            description="The Sharpe ratio carries its significance verdict",
            met=significance is not None,
            evidence=(
                Evidence("backtest_runs", backtest.backtest_run_id or "", significance)
                if backtest
                else None
            ),
            detail=(
                ""
                if significance is not None
                else "a Sharpe without its standard error is not a result"
            ),
        ),
        Criterion(
            id="limitations_documented",
            description="The known limitations are written down",
            met=bool(str(limitations or "").strip()),
            evidence=Evidence("hypotheses", facts.hypothesis_ref),
        ),
    )


def _gate_shadow_to_paper(facts: CandidateFacts) -> tuple[Criterion, ...]:
    """
    Stage 3 -> 4. It has operated on a schedule, and operated correctly.

    Nothing here asks whether the shadow book made money, and it would be the
    wrong question: twenty sessions carries a Sharpe standard error near four,
    so any figure over that window is noise. What this stage evidences is that
    the machinery runs — the schedule fires, the sessions are continuous, the
    logs are complete, and the venue would have accepted what the book filled.
    """
    recorded = len(facts.shadow)
    errors = [s for s in facts.shadow if s.error]
    rebalances = [s for s in facts.shadow if s.rebalanced]
    underfunded = [s for s in facts.shadow if s.underfunded]

    return (
        Criterion(
            id="deployment_exists",
            description="A deployment exists for the candidate to operate against",
            met=facts.has_deployment,
            detail=(
                ""
                if facts.has_deployment
                else "one is created on entry to stage 3; this candidate has none"
            ),
        ),
        Criterion(
            id="shadow_sessions",
            description=(
                f"At least {MIN_SHADOW_SESSIONS} shadow sessions recorded"
            ),
            met=recorded >= MIN_SHADOW_SESSIONS,
            evidence=Evidence("shadow_decisions", facts.hypothesis_ref, recorded),
            detail=f"{recorded} recorded",
        ),
        Criterion(
            id="shadow_without_errors",
            description="No shadow session failed",
            met=not errors,
            evidence=(
                Evidence(
                    "shadow_decisions",
                    ",".join(s.session.isoformat() for s in errors[:5]),
                    len(errors),
                )
                if errors
                else None
            ),
            detail=(
                ""
                if not errors
                else f"{len(errors)} session(s) errored; stable operation is "
                "the thing this stage exists to demonstrate"
            ),
        ),
        Criterion(
            id="schedule_fired",
            description="The rebalance schedule actually fired at least once",
            met=bool(rebalances),
            evidence=(
                Evidence(
                    "shadow_decisions",
                    rebalances[-1].session.isoformat(),
                    len(rebalances),
                )
                if rebalances
                else None
            ),
            detail=(
                ""
                if rebalances
                else "a candidate that never rebalanced has not demonstrated "
                "correct decision timing, only that it ran"
            ),
        ),
        Criterion(
            id="venue_would_have_agreed",
            description="No buy was trimmed for want of cash",
            met=not underfunded,
            evidence=(
                Evidence(
                    "shadow_decisions",
                    underfunded[-1].session.isoformat(),
                    len(underfunded),
                )
                if underfunded
                else None
            ),
            detail=(
                ""
                if not underfunded
                else "the simulated venue trimmed a buy a real one would have "
                "rejected, so the shadow book and a live one have already "
                "diverged; set cash_buffer_pct"
            ),
        ),
    )


#: Why the later gates cannot be judged yet. Rendered to the operator verbatim.
_MISSING_CAPABILITY: dict[int, str] = {
    4: (
        "broker paper trading against a live account, with position and cash "
        "reconciliation, is not built"
    ),
    5: "canary allocation and rollback criteria are not built",
    6: "graduated capital increase is not built",
    7: "periodic revalidation and capacity management are not built",
    8: "a retired candidate has no next stage",
}

_GATES = {
    0: _gate_concept_to_research,
    1: _gate_research_to_validation,
    2: _gate_validation_to_shadow,
    3: _gate_shadow_to_paper,
}
