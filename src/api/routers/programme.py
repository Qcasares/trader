"""
programme.py
------------
The control plane for the AI programme.

Reads rows, records operator decisions, and asks the runner for a pass. It does
not import a model client and it never will — ``src/api`` is covered by
``tests/unit/test_import_boundaries.py``, and the programme's own reverse
boundary is asserted there too.

The endpoint that carries the weight is ``POST /candidates/{id}/promote``. It
**confirms a passed gate; it cannot override a failed one.** That distinction
is the whole of the operating prompt's decision-rights model in one refusal: a
role with veto authority can stop a promotion, and no role can push one
through. An operator who disagrees with a gate has to produce the missing
evidence, which is the same thing the runner has to do.

The gate is also re-evaluated at the moment of the click rather than read from
the last stored evaluation. A judgement made an hour ago describes an hour-old
set of rows, and "it passed when the runner looked" is not a reason to promote
now.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from src.api.deps import AuthedSession, DbConn
from src.db.repos import flags
from src.programme import repo
from src.programme.flags import (
    PROGRAMME_ENABLED,
    PROGRAMME_MAX_AUTO_STAGE,
    PROGRAMME_WORKER_ID,
    max_auto_stage,
    programme_enabled,
)
from src.programme.gates import (
    BLOCKING_SEVERITIES,
    FIRST_HUMAN_GATED_STAGE,
    MIN_SHADOW_SESSIONS,
    STAGE_NAMES,
    VETO_ROLES,
    evaluate,
)
from src.programme.roles import ROLES, ROLES_BY_KEY, SEVERITIES
from src.strategies import build_strategy, get_strategy_class, list_strategies

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/programme", tags=["programme"])

#: Matches ``src/api/routers/system.py``. The programme writes a heartbeat on
#: the same cadence as the worker, so it is presumed dead on the same terms.
PROGRAMME_STALE_AFTER_SECONDS = 60.0


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class ConfigUpdate(BaseModel):
    """Values to set. An empty string clears a value back to TBD."""

    model_config = {"extra": "forbid"}

    values: dict[str, str]


class HypothesisRequest(BaseModel):
    """An operator-authored hypothesis card."""

    model_config = {"extra": "forbid"}

    title: str = Field(min_length=8)
    owner: str = Field(min_length=1)
    card: dict[str, Any]
    parent_ref: str | None = None


class CandidateRequest(BaseModel):
    """A configuration to test a hypothesis with."""

    model_config = {"extra": "forbid"}

    hypothesis_ref: str
    strategy: str
    params: dict[str, Any] = Field(default_factory=dict)
    start_session: date
    end_session: date
    data_source: str = "yfinance"


class PromoteRequest(BaseModel):
    """
    Confirm a promotion. Typed confirmation, as with the kill switch.

    Advancing a strategy towards operation should take a deliberate act, and
    the string names the stage so a mis-click on the wrong candidate does not
    silently promote it.
    """

    model_config = {"extra": "forbid"}

    confirm: str
    rationale: str = ""

    @field_validator("confirm")
    @classmethod
    def _must_confirm(cls, value: str) -> str:
        if value != "PROMOTE":
            raise ValueError("confirm must be exactly 'PROMOTE'")
        return value


class DecisionRequest(BaseModel):
    """Reject, hold or retire a candidate."""

    model_config = {"extra": "forbid"}

    rationale: str = Field(min_length=1)


class FindingRequest(BaseModel):
    """An operator-raised finding."""

    model_config = {"extra": "forbid"}

    candidate_id: str | None = None
    raised_by: str
    severity: str
    title: str = Field(min_length=10)
    detail: str = ""
    remediation: str = ""

    @field_validator("severity")
    @classmethod
    def _known_severity(cls, value: str) -> str:
        if value not in SEVERITIES:
            raise ValueError(f"severity must be one of {SEVERITIES}")
        return value

    @field_validator("raised_by")
    @classmethod
    def _known_role(cls, value: str) -> str:
        if value not in ROLES_BY_KEY:
            raise ValueError(f"raised_by must be one of {sorted(ROLES_BY_KEY)}")
        return value


class CloseFindingRequest(BaseModel):
    """
    Resolve a finding. Never back to open.

    ``accepted`` is a deliberate decision to proceed with a known defect and is
    not the same as fixing one, so it is a separate value rather than a note on
    ``remediated``. A register that cannot tell them apart describes a
    programme with no outstanding problems.
    """

    model_config = {"extra": "forbid"}

    status: str
    note: str = Field(min_length=1)

    @field_validator("status")
    @classmethod
    def _closeable(cls, value: str) -> str:
        if value not in ("remediated", "accepted", "withdrawn"):
            raise ValueError(
                "status must be remediated, accepted or withdrawn"
            )
        return value


class AutonomyRequest(BaseModel):
    """
    Raise or lower the autonomy ceiling.

    Requires the typed confirmation whenever it is being raised. Lowering it
    needs nothing, which is the same asymmetry as every other control here.
    """

    model_config = {"extra": "forbid"}

    max_auto_stage: int = Field(ge=0, le=8)
    confirm: str = ""
    reason: str = ""


class EnabledRequest(BaseModel):
    """Turn the programme on or off. Off needs no confirmation."""

    model_config = {"extra": "forbid"}

    enabled: bool
    confirm: str = ""
    reason: str = ""

    @field_validator("confirm")
    @classmethod
    def _check(cls, value: str, info: Any) -> str:
        if info.data.get("enabled") and value != "ENABLE PROGRAMME":
            raise ValueError("confirm must be exactly 'ENABLE PROGRAMME'")
        return value


# POST rather than PUT throughout, even where PUT would read better. The CORS
# policy in `src/api/main.py` allows GET, POST, DELETE and OPTIONS, and the
# frontend is deployed to a different origin from the API — so a PUT here would
# be blocked by the browser's preflight and fail only in production, which is
# the worst place to discover it.


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@router.get("/config")
async def get_config(session: AuthedSession, conn: DbConn) -> dict[str, Any]:
    """The section 2 configuration. A null value means TBD and is rendered so."""
    rows = await repo.get_config(conn)
    return {
        "items": rows,
        "critical_unknowns": [
            r["key"] for r in rows if r["is_critical"] and not r["value"]
        ],
        "unknowns": [r["key"] for r in rows if not r["value"]],
    }


@router.post("/config")
async def post_config(
    body: ConfigUpdate, session: AuthedSession, conn: DbConn
) -> dict[str, Any]:
    """
    Set configuration values.

    An unrecognised key is reported rather than stored. The vocabulary is
    fixed, and a typo that quietly creates a thirty-fourth key produces a value
    nothing will ever read.
    """
    unknown = await repo.set_config(conn, body.values, f"operator:{session.subject}")
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown configuration keys: {unknown}",
        )
    await flags.record_audit(
        conn,
        actor=f"operator:{session.subject}",
        action="programme_config_updated",
        entity_type="programme_config",
        detail={"keys": sorted(body.values)},
    )
    return await get_config(session, conn)


# ---------------------------------------------------------------------------
# Hypotheses
# ---------------------------------------------------------------------------


@router.get("/hypotheses")
async def list_hypotheses(
    session: AuthedSession,
    conn: DbConn,
    hypothesis_status: str | None = Query(default=None, alias="status"),
) -> list[dict[str, Any]]:
    """
    The ledger. Rejected hypotheses are included and are not hidden by default.

    There is no DELETE endpoint here, and the schema would refuse one anyway.
    """
    return await repo.list_hypotheses(conn, status=hypothesis_status)


@router.get("/hypotheses/{ref}")
async def get_hypothesis(
    ref: str, session: AuthedSession, conn: DbConn
) -> dict[str, Any]:
    hypothesis = await repo.get_hypothesis(conn, ref)
    if hypothesis is None:
        raise HTTPException(status_code=404, detail=f"no hypothesis {ref!r}")
    hypothesis["candidates"] = [
        c
        for c in await repo.list_candidates(conn)
        if c["hypothesis_ref"] == ref
    ]
    return hypothesis


@router.post("/hypotheses", status_code=status.HTTP_201_CREATED)
async def create_hypothesis(
    body: HypothesisRequest, session: AuthedSession, conn: DbConn
) -> dict[str, Any]:
    created = await repo.create_hypothesis(
        conn,
        title=body.title,
        card=body.card,
        owner=body.owner,
        origin="operator",
        parent_ref=body.parent_ref,
    )
    await flags.record_audit(
        conn,
        actor=f"operator:{session.subject}",
        action="hypothesis_created",
        entity_type="hypothesis",
        entity_id=created["ref"],
        detail={"title": body.title},
    )
    return created


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------


@router.get("/candidates")
async def list_candidates(
    session: AuthedSession, conn: DbConn
) -> dict[str, Any]:
    """The pipeline board, with the stage vocabulary the UI renders."""
    return {
        "stages": [
            {"stage": k, "name": v} for k, v in sorted(STAGE_NAMES.items())
        ],
        "first_human_gated_stage": FIRST_HUMAN_GATED_STAGE,
        "candidates": await repo.list_candidates(conn),
    }


@router.post("/candidates", status_code=status.HTTP_201_CREATED)
async def create_candidate(
    body: CandidateRequest, session: AuthedSession, conn: DbConn
) -> dict[str, Any]:
    """
    Instantiate a hypothesis as a testable configuration.

    Parameters are validated against the strategy's own model, exactly as the
    backtest endpoint does and exactly as the runner does for a model-authored
    proposal. One definition of valid, three callers.
    """
    hypothesis = await repo.get_hypothesis(conn, body.hypothesis_ref)
    if hypothesis is None:
        raise HTTPException(
            status_code=404, detail=f"no hypothesis {body.hypothesis_ref!r}"
        )
    try:
        get_strategy_class(body.strategy)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=(
                f"unknown strategy {body.strategy!r}; "
                f"registered: {list_strategies()}"
            ),
        ) from None
    try:
        strategy = build_strategy(body.strategy, body.params)
    except Exception as exc:  # noqa: BLE001 - surfaced verbatim
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid parameters: {exc}",
        ) from exc
    if body.end_session <= body.start_session:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"end ({body.end_session}) must be after start "
            f"({body.start_session})",
        )

    candidate_id = await repo.create_candidate(
        conn,
        hypothesis_id=hypothesis["id"],
        strategy_name=body.strategy,
        params=strategy.params_dict(),
        universe=strategy.universe(),
        start_session=body.start_session,
        end_session=body.end_session,
        data_source=body.data_source,
    )
    return {"candidate_id": candidate_id}


@router.get("/candidates/{candidate_id}")
async def get_candidate(
    candidate_id: str, session: AuthedSession, conn: DbConn
) -> dict[str, Any]:
    candidate = await repo.get_candidate(conn, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="no such candidate")
    candidate["stage_name"] = STAGE_NAMES.get(candidate["stage"], "unknown")
    candidate["experiments"] = await repo.list_experiments(conn, candidate_id)
    candidate["gate"] = await _live_gate(conn, candidate_id)
    candidate["last_recorded_gate"] = await repo.latest_gate(conn, candidate_id)
    return candidate


@router.get("/candidates/{candidate_id}/gate")
async def get_gate(
    candidate_id: str, session: AuthedSession, conn: DbConn
) -> dict[str, Any]:
    """Evaluate the gate now, against the rows as they stand now."""
    gate = await _live_gate(conn, candidate_id)
    if gate is None:
        raise HTTPException(status_code=404, detail="no such candidate")
    return gate


async def _live_gate(
    conn: DbConn, candidate_id: str
) -> dict[str, Any] | None:
    facts = await repo.load_facts(conn, candidate_id)
    if facts is None:
        return None
    return evaluate(facts).as_dict()


@router.post("/candidates/{candidate_id}/promote")
async def promote(
    candidate_id: str,
    body: PromoteRequest,
    session: AuthedSession,
    conn: DbConn,
) -> dict[str, Any]:
    """
    Confirm a promotion the gate has already passed.

    409, not 403, when the gate has not passed: the request is not forbidden to
    this operator, it is inconsistent with the state of the evidence, and it
    would succeed once the missing rows exist. The response names every unmet
    criterion so the operator learns what to produce rather than that they were
    told no.
    """
    facts = await repo.load_facts(conn, candidate_id)
    if facts is None:
        raise HTTPException(status_code=404, detail="no such candidate")

    result = evaluate(facts)
    if not result.passed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": (
                    "the gate has not passed; an operator confirms a pass and "
                    "cannot override a failure"
                ),
                "unmet": [c.as_dict() for c in result.unmet],
            },
        )

    actor = f"operator:{session.subject}"
    await repo.record_gate(
        conn, candidate_id, result, promoted=True, approved_by=actor
    )
    await repo.promote(conn, candidate_id, result.to_stage)
    ref = await repo.record_decision(
        conn,
        subject_type="candidate",
        subject_id=candidate_id,
        decision=f"promote_stage_{result.to_stage}",
        made_by=actor,
        rationale=body.rationale,
        evidence=result.as_dict(),
    )
    await flags.record_audit(
        conn,
        actor=actor,
        action="candidate_promoted",
        entity_type="candidate",
        entity_id=candidate_id,
        detail={"to_stage": result.to_stage, "decision_ref": ref},
    )
    return {
        "candidate_id": candidate_id,
        "stage": result.to_stage,
        "stage_name": STAGE_NAMES.get(result.to_stage, "unknown"),
        "decision_ref": ref,
    }


@router.post("/candidates/{candidate_id}/reject")
async def reject(
    candidate_id: str,
    body: DecisionRequest,
    session: AuthedSession,
    conn: DbConn,
) -> dict[str, Any]:
    """
    Stop a candidate. Needs no gate and no confirmation.

    The asymmetry is the same one the kill switch has: stopping is
    frictionless, starting is not.
    """
    return await _close(conn, session, candidate_id, "rejected", body.rationale)


@router.post("/candidates/{candidate_id}/hold")
async def hold(
    candidate_id: str,
    body: DecisionRequest,
    session: AuthedSession,
    conn: DbConn,
) -> dict[str, Any]:
    """Park a candidate pending more evidence. The runner stops advancing it."""
    return await _close(conn, session, candidate_id, "held", body.rationale)


async def _close(
    conn: DbConn,
    session: AuthedSession,
    candidate_id: str,
    new_status: str,
    rationale: str,
) -> dict[str, Any]:
    candidate = await repo.get_candidate(conn, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="no such candidate")
    actor = f"operator:{session.subject}"
    await repo.set_candidate_status(conn, candidate_id, new_status, rationale)
    ref = await repo.record_decision(
        conn,
        subject_type="candidate",
        subject_id=candidate_id,
        decision="reject" if new_status == "rejected" else "hold",
        made_by=actor,
        rationale=rationale,
    )
    await flags.record_audit(
        conn,
        actor=actor,
        action=f"candidate_{new_status}",
        entity_type="candidate",
        entity_id=candidate_id,
        detail={"rationale": rationale},
    )
    return {"candidate_id": candidate_id, "status": new_status, "decision_ref": ref}


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------


@router.get("/experiments")
async def list_experiments(
    session: AuthedSession,
    conn: DbConn,
    candidate_id: str | None = None,
) -> list[dict[str, Any]]:
    return await repo.list_experiments(conn, candidate_id)


@router.get("/experiments/{ref}")
async def get_experiment(
    ref: str, session: AuthedSession, conn: DbConn
) -> dict[str, Any]:
    experiment = await repo.get_experiment(conn, ref)
    if experiment is None:
        raise HTTPException(status_code=404, detail=f"no experiment {ref!r}")
    return experiment


# ---------------------------------------------------------------------------
# Findings and assessments
# ---------------------------------------------------------------------------


@router.get("/findings")
async def list_findings(
    session: AuthedSession,
    conn: DbConn,
    candidate_id: str | None = None,
    only_open: bool = False,
) -> dict[str, Any]:
    """
    The register, with the vocabulary the UI needs to explain what blocks.

    `veto_roles` and `blocking_severities` are returned rather than duplicated
    in the frontend, so the rule the gate applies and the rule the page
    describes cannot drift apart.
    """
    return {
        "findings": await repo.list_findings(conn, candidate_id, only_open),
        "veto_roles": sorted(VETO_ROLES),
        "blocking_severities": sorted(BLOCKING_SEVERITIES),
        "roles": [
            {"key": r.key, "title": r.title, "holds_veto": r.holds_veto}
            for r in ROLES
        ],
    }


@router.post("/findings", status_code=status.HTTP_201_CREATED)
async def create_finding(
    body: FindingRequest, session: AuthedSession, conn: DbConn
) -> dict[str, Any]:
    """
    Raise a finding by hand.

    An operator can raise one under any role's name, and that is deliberate:
    the register is the programme's record of known defects, not a log of what
    a model happened to notice.
    """
    created = await repo.raise_finding(
        conn,
        candidate_id=body.candidate_id,
        raised_by=body.raised_by,
        severity=body.severity,
        title=body.title,
        detail=body.detail,
        remediation=body.remediation,
    )
    await flags.record_audit(
        conn,
        actor=f"operator:{session.subject}",
        action="finding_raised",
        entity_type="finding",
        entity_id=created["ref"],
        detail={"severity": body.severity, "raised_by": body.raised_by},
    )
    return created


@router.post("/findings/{ref}/close")
async def close_finding(
    ref: str,
    body: CloseFindingRequest,
    session: AuthedSession,
    conn: DbConn,
) -> dict[str, Any]:
    """
    Close a finding. The only route by which one is ever closed.

    ``closed_by`` is stamped from the session subject and never taken from the
    request, so there is no field a caller can set to impersonate an operator.
    The schema's CHECK constraint requires the ``operator:`` prefix, which this
    is the only code that produces — that is what makes "a model cannot close
    its own finding" a fact rather than a policy.
    """
    actor = f"operator:{session.subject}"
    try:
        await repo.close_finding(conn, ref, body.status, actor, body.note)
    except repo.FindingClosureError as exc:  # pragma: no cover - defence in depth
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    await flags.record_audit(
        conn,
        actor=actor,
        action="finding_closed",
        entity_type="finding",
        entity_id=ref,
        detail={"status": body.status, "note": body.note},
    )
    return {"ref": ref, "status": body.status, "closed_by": actor}


@router.get("/candidates/{candidate_id}/shadow")
async def list_shadow(
    candidate_id: str, session: AuthedSession, conn: DbConn
) -> dict[str, Any]:
    """
    Shadow sessions, newest first.

    ``equity`` is the derived book's value, not a P&L: the opening balance is a
    fixed notional and the window is a few weeks, so a return computed from it
    would carry a standard error several times its own size. It is here so an
    operator can see the book moving, not so anyone can quote it.
    """
    return {
        "sessions": await repo.list_shadow_decisions(conn, candidate_id),
        "required": MIN_SHADOW_SESSIONS,
    }


@router.get("/candidates/{candidate_id}/assessments")
async def list_assessments(
    candidate_id: str, session: AuthedSession, conn: DbConn
) -> list[dict[str, Any]]:
    """
    Every specialist view, newest first, disagreement included.

    Nothing here is summarised into a consensus. Two roles reaching opposite
    conclusions from the same brief is information, and a field averaging them
    would be a thirteenth opinion nobody held.
    """
    return await repo.list_assessments(conn, candidate_id)


# ---------------------------------------------------------------------------
# The runner
# ---------------------------------------------------------------------------


@router.get("/status")
async def get_status(session: AuthedSession, conn: DbConn) -> dict[str, Any]:
    """
    Whether the programme is on, and whether its process is alive.

    ``enabled`` is read the same fail-closed way the runner reads it, so the UI
    cannot show "on" for a programme the runner would refuse to run.
    """
    enabled = await programme_enabled(conn)

    row = await conn.fetchrow(
        "SELECT last_seen, status, "
        "       EXTRACT(EPOCH FROM (NOW() - last_seen)) AS age_seconds "
        "FROM worker_heartbeats WHERE worker_id = $1",
        PROGRAMME_WORKER_ID,
    )
    runs = await repo.list_runs(conn, limit=1)
    config = await repo.get_config(conn)
    open_findings = await repo.list_findings(conn, only_open=True)
    blocking = [
        f
        for f in open_findings
        if f["severity"] in BLOCKING_SEVERITIES and f["raised_by"] in VETO_ROLES
    ]
    return {
        "enabled": enabled,
        # Read through the same clamped, fail-closed helper the runner uses, so
        # the page cannot show a ceiling the runner would not honour.
        "max_auto_stage": await max_auto_stage(conn),
        "autonomy_hard_cap": FIRST_HUMAN_GATED_STAGE - 1,
        "open_findings": len(open_findings),
        "blocking_findings": len(blocking),
        "runner": (
            None
            if row is None
            else {
                "last_seen": row["last_seen"].isoformat(),
                "status": row["status"],
                "age_seconds": float(row["age_seconds"]),
                "stale": float(row["age_seconds"]) > PROGRAMME_STALE_AFTER_SECONDS,
            }
        ),
        "last_run": runs[0] if runs else None,
        "critical_unknowns": [
            r["key"] for r in config if r["is_critical"] and not r["value"]
        ],
        "unknown_count": sum(1 for r in config if not r["value"]),
    }


@router.post("/enabled")
async def set_enabled(
    body: EnabledRequest, session: AuthedSession, conn: DbConn
) -> dict[str, Any]:
    """Turn the programme on or off. Enabling needs the typed confirmation."""
    actor = f"operator:{session.subject}"
    await flags.set_flag(conn, PROGRAMME_ENABLED, body.enabled, actor)
    await flags.record_audit(
        conn,
        actor=actor,
        action="programme_enabled" if body.enabled else "programme_disabled",
        entity_type="system",
        detail={"reason": body.reason},
    )
    logger.warning(
        "Programme %s by %s: %s",
        "ENABLED" if body.enabled else "DISABLED",
        actor,
        body.reason or "(no reason given)",
    )
    return await get_status(session, conn)


@router.post("/autonomy")
async def set_autonomy(
    body: AutonomyRequest, session: AuthedSession, conn: DbConn
) -> dict[str, Any]:
    """
    Set how far the runner may promote without an operator.

    Raising it needs the typed confirmation; lowering it needs nothing. The
    request is validated to 0..8 and then *stored as asked*, because the clamp
    that matters is applied on the way out by ``flags.max_auto_stage`` against
    ``FIRST_HUMAN_GATED_STAGE``. Clamping on the way in instead would make the
    stored value look like the effective one, and a future change to the
    constant would silently widen every deployment that had ever been set high.
    """
    current = await max_auto_stage(conn)
    if body.max_auto_stage > current and body.confirm != "RAISE AUTONOMY":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="confirm must be exactly 'RAISE AUTONOMY' to raise the ceiling",
        )

    actor = f"operator:{session.subject}"
    await flags.set_flag(conn, PROGRAMME_MAX_AUTO_STAGE, body.max_auto_stage, actor)
    await flags.record_audit(
        conn,
        actor=actor,
        action="programme_autonomy_set",
        entity_type="system",
        detail={
            "requested": body.max_auto_stage,
            "previous": current,
            "reason": body.reason,
        },
    )
    effective = await max_auto_stage(conn)
    logger.warning(
        "Programme autonomy ceiling set to %s (effective %s) by %s: %s",
        body.max_auto_stage,
        effective,
        actor,
        body.reason or "(no reason given)",
    )
    return {
        "requested": body.max_auto_stage,
        "effective": effective,
        "hard_cap": FIRST_HUMAN_GATED_STAGE - 1,
    }


@router.get("/runs")
async def list_runs(
    session: AuthedSession, conn: DbConn, limit: int = Query(default=50, le=200)
) -> list[dict[str, Any]]:
    return await repo.list_runs(conn, limit=limit)


@router.post("/tick", status_code=status.HTTP_202_ACCEPTED)
async def request_tick(session: AuthedSession, conn: DbConn) -> dict[str, Any]:
    """
    Ask the runner for an immediate pass.

    202 and a row, never an inline run. The API does not hold a model client
    and must not block a request handler on a model call, for the same reason
    it never runs a backtest inline: the request it would stall might be the
    one an operator is using to stop something.
    """
    run_id = await repo.request_tick(conn, f"operator:{session.subject}")
    return {"run_id": run_id, "status": "requested"}
