"""
repo.py
-------
Every query the programme layer makes.

Kept apart from :mod:`src.programme.tick` so the runner's logic reads as a
sequence of decisions rather than a sequence of SQL statements, and apart from
:mod:`src.programme.gates` so the gates stay pure.

Two conventions worth stating, because they are what keep the model honest:

* ``record_experiment`` requires preregistered criteria and refuses an empty
  set. The database makes them immutable after insert; this makes them
  mandatory before it. Between the two, an acceptance test cannot be written
  once the answer is known.
* ``complete_experiment`` copies the outcome from the engine's own row and
  decides ``conclusion`` by evaluating the preregistered criteria against it.
  Nothing decides a conclusion by reading prose.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

import asyncpg

from src.programme.gates import (
    CandidateFacts,
    ExperimentFact,
    FindingFact,
    GateResult,
    ShadowFact,
    WalkforwardFact,
    evaluate_preregistered,
)

logger = logging.getLogger(__name__)

#: Kinds an experiment may take. Mirrors the comment in migration 0007.
EXPERIMENT_KINDS = (
    "baseline",
    "backtest",
    "cost_stress",
    "parameter_neighbourhood",
    "benchmark",
    "replication",
    "walkforward",
)


def _maybe_float(value: Any) -> float | None:
    """A number, or None. Never 0.0 for something that was not measured."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def loads_json(value: Any, default: Any) -> Any:
    """asyncpg returns JSONB as text on some drivers and dict on others."""
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


async def get_config(conn: asyncpg.Connection) -> list[dict[str, Any]]:
    """
    The programme configuration, every key, in the operating prompt's order.

    A NULL value is returned as ``None`` and rendered as TBD. Nothing here
    substitutes a default for a value nobody supplied.
    """
    rows = await conn.fetch(
        "SELECT key, value, is_critical, notes, updated_by, updated_at "
        "FROM programme_config ORDER BY is_critical DESC, key"
    )
    return [
        {
            "key": r["key"],
            "value": r["value"],
            "is_critical": r["is_critical"],
            "notes": r["notes"],
            "updated_by": r["updated_by"],
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        }
        for r in rows
    ]


async def set_config(
    conn: asyncpg.Connection, values: Mapping[str, str | None], actor: str
) -> list[str]:
    """
    Set configuration values. Returns the keys that were not recognised.

    Unknown keys are reported rather than inserted. The configuration is a
    fixed vocabulary from the operating prompt, and a typo that silently
    creates a thirty-fourth key is a value nobody will ever read.
    """
    known = {r["key"] for r in await conn.fetch("SELECT key FROM programme_config")}
    unknown = [k for k in values if k not in known]
    for key, value in values.items():
        if key in unknown:
            continue
        cleaned = (value or "").strip() or None
        await conn.execute(
            "UPDATE programme_config SET value = $2, updated_by = $3, "
            "updated_at = NOW() WHERE key = $1",
            key,
            cleaned,
            actor,
        )
    return sorted(unknown)


async def critical_unknowns(conn: asyncpg.Connection) -> list[str]:
    """Critical configuration still marked TBD."""
    rows = await conn.fetch(
        "SELECT key FROM programme_config WHERE is_critical AND value IS NULL "
        "ORDER BY key"
    )
    return [r["key"] for r in rows]


# ---------------------------------------------------------------------------
# Hypotheses
# ---------------------------------------------------------------------------


async def _next_ref(conn: asyncpg.Connection, table: str, prefix: str) -> str:
    """Sequential human-facing reference, H-0001 and so on."""
    count = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
    return f"{prefix}-{int(count) + 1:04d}"


async def create_hypothesis(
    conn: asyncpg.Connection,
    title: str,
    card: Mapping[str, Any],
    owner: str,
    origin: str = "operator",
    model: str = "",
    parent_ref: str | None = None,
) -> dict[str, Any]:
    """Add a hypothesis to the ledger. Nothing ever removes one."""
    hyp_id = uuid.uuid4()
    ref = await _next_ref(conn, "hypotheses", "H")
    await conn.execute(
        """
        INSERT INTO hypotheses (id, ref, title, owner, card, origin, model,
                                parent_ref)
        VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7,$8)
        """,
        hyp_id,
        ref,
        title,
        owner,
        json.dumps(dict(card), sort_keys=True, default=str),
        origin,
        model,
        parent_ref,
    )
    logger.info("Recorded hypothesis %s (%s) from %s", ref, title, origin)
    return {"id": str(hyp_id), "ref": ref}


async def list_hypotheses(
    conn: asyncpg.Connection, status: str | None = None, limit: int = 200
) -> list[dict[str, Any]]:
    """
    The ledger, newest first, rejections included.

    Rejections are never filtered out by default. The proportion of failed
    experiments retained is one of the programme's own metrics, and a ledger
    that hides its failures reports it as 100% while being worthless.
    """
    if status:
        rows = await conn.fetch(
            "SELECT * FROM hypotheses WHERE status = $1 "
            "ORDER BY created_at DESC LIMIT $2",
            status,
            limit,
        )
    else:
        rows = await conn.fetch(
            "SELECT * FROM hypotheses ORDER BY created_at DESC LIMIT $1", limit
        )
    return [_decode_hypothesis(r) for r in rows]


async def get_hypothesis(
    conn: asyncpg.Connection, ref: str
) -> dict[str, Any] | None:
    row = await conn.fetchrow("SELECT * FROM hypotheses WHERE ref = $1", ref)
    return _decode_hypothesis(row) if row else None


async def decide_hypothesis(
    conn: asyncpg.Connection, ref: str, status: str, rationale: str
) -> None:
    await conn.execute(
        "UPDATE hypotheses SET status=$2, decision=$2, decision_rationale=$3, "
        "decided_at=NOW() WHERE ref=$1",
        ref,
        status,
        rationale,
    )


def _decode_hypothesis(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "ref": row["ref"],
        "title": row["title"],
        "owner": row["owner"],
        "card": loads_json(row["card"], {}),
        "status": row["status"],
        "parent_ref": row["parent_ref"],
        "variants_tried": row["variants_tried"],
        "origin": row["origin"],
        "model": row["model"],
        "decision": row["decision"],
        "decision_rationale": row["decision_rationale"],
        "created_at": row["created_at"].isoformat(),
        "decided_at": (
            row["decided_at"].isoformat() if row["decided_at"] else None
        ),
    }


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------


async def create_candidate(
    conn: asyncpg.Connection,
    hypothesis_id: str,
    strategy_name: str,
    params: Mapping[str, Any],
    universe: Sequence[str],
    start_session: date,
    end_session: date,
    data_source: str,
) -> str:
    """Instantiate a hypothesis as one testable configuration."""
    cand_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO candidates (id, hypothesis_id, strategy_name, params,
            universe, start_session, end_session, data_source,
            evidence_is_synthetic)
        VALUES ($1,$2,$3,$4::jsonb,$5,$6,$7,$8,$9)
        """,
        cand_id,
        uuid.UUID(hypothesis_id),
        strategy_name,
        json.dumps(dict(params), sort_keys=True, default=str),
        list(universe),
        start_session,
        end_session,
        data_source,
        data_source == "synthetic",
    )
    await conn.execute(
        "UPDATE hypotheses SET variants_tried = variants_tried + 1 WHERE id = $1",
        uuid.UUID(hypothesis_id),
    )
    return str(cand_id)


async def list_candidates(
    conn: asyncpg.Connection, include_closed: bool = True
) -> list[dict[str, Any]]:
    """The pipeline board: every candidate with its stage and hypothesis."""
    clause = "" if include_closed else "WHERE c.status = 'active'"
    rows = await conn.fetch(
        f"""
        SELECT c.*, h.ref AS hypothesis_ref, h.title AS hypothesis_title,
               h.origin AS hypothesis_origin
        FROM candidates c JOIN hypotheses h ON h.id = c.hypothesis_id
        {clause}
        ORDER BY c.stage DESC, c.created_at DESC
        """  # noqa: S608 - `clause` is a literal chosen here, never user input
    )
    return [_decode_candidate(r) for r in rows]


async def get_candidate(
    conn: asyncpg.Connection, candidate_id: str
) -> dict[str, Any] | None:
    try:
        cand_uuid = uuid.UUID(candidate_id)
    except ValueError:
        return None
    row = await conn.fetchrow(
        """
        SELECT c.*, h.ref AS hypothesis_ref, h.title AS hypothesis_title,
               h.origin AS hypothesis_origin
        FROM candidates c JOIN hypotheses h ON h.id = c.hypothesis_id
        WHERE c.id = $1
        """,
        cand_uuid,
    )
    return _decode_candidate(row) if row else None


def _decode_candidate(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "hypothesis_id": str(row["hypothesis_id"]),
        "hypothesis_ref": row["hypothesis_ref"],
        "hypothesis_title": row["hypothesis_title"],
        "hypothesis_origin": row["hypothesis_origin"],
        "strategy_name": row["strategy_name"],
        "params": loads_json(row["params"], {}),
        "universe": list(row["universe"]),
        "start_session": row["start_session"].isoformat(),
        "end_session": row["end_session"].isoformat(),
        "data_source": row["data_source"],
        "stage": row["stage"],
        "stage_entered_at": row["stage_entered_at"].isoformat(),
        "status": row["status"],
        "evidence_is_synthetic": row["evidence_is_synthetic"],
        "deployment_id": (
            str(row["deployment_id"]) if row["deployment_id"] else None
        ),
        "notes": row["notes"],
        "created_at": row["created_at"].isoformat(),
    }


async def set_candidate_status(
    conn: asyncpg.Connection, candidate_id: str, status: str, note: str = ""
) -> None:
    await conn.execute(
        "UPDATE candidates SET status = $2, notes = $3 WHERE id = $1",
        uuid.UUID(candidate_id),
        status,
        note,
    )


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------


class PreregistrationRequiredError(ValueError):
    """An experiment was recorded without acceptance criteria."""


async def record_experiment(
    conn: asyncpg.Connection,
    candidate_id: str,
    hypothesis_id: str,
    kind: str,
    preregistered_criteria: Sequence[Mapping[str, Any]],
    *,
    code_commit: str = "",
    dataset_manifest: Mapping[str, Any] | None = None,
    seed: int | None = None,
    universe: Sequence[str] = (),
    cost_assumptions: Mapping[str, Any] | None = None,
    backtest_run_id: str | None = None,
    walkforward_run_id: str | None = None,
    job_id: str | None = None,
    train_start: date | None = None,
    train_end: date | None = None,
    test_start: date | None = None,
    test_end: date | None = None,
) -> dict[str, Any]:
    """
    Register an experiment before it runs.

    Refuses an empty criteria set. An experiment with nothing to satisfy cannot
    fail, and a test that cannot fail is not evidence — it is a formality that
    later reads like one.
    """
    if not preregistered_criteria:
        raise PreregistrationRequiredError(
            "an experiment must carry acceptance criteria fixed before it runs"
        )
    if kind not in EXPERIMENT_KINDS:
        raise ValueError(f"unknown experiment kind {kind!r}")

    exp_id = uuid.uuid4()
    ref = await _next_ref(conn, "experiments", "E")
    await conn.execute(
        """
        INSERT INTO experiments (id, ref, hypothesis_id, candidate_id, kind,
            code_commit, dataset_manifest, seed, universe, cost_assumptions,
            preregistered_criteria, backtest_run_id, walkforward_run_id,
            job_id, train_start, train_end, test_start, test_end, status)
        VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9,$10::jsonb,$11::jsonb,
                $12,$13,$14,$15,$16,$17,$18,'queued')
        """,
        exp_id,
        ref,
        uuid.UUID(hypothesis_id),
        uuid.UUID(candidate_id),
        kind,
        code_commit,
        json.dumps(dict(dataset_manifest or {}), sort_keys=True, default=str),
        seed,
        list(universe),
        json.dumps(dict(cost_assumptions or {}), sort_keys=True, default=str),
        json.dumps(list(preregistered_criteria), sort_keys=True, default=str),
        uuid.UUID(backtest_run_id) if backtest_run_id else None,
        uuid.UUID(walkforward_run_id) if walkforward_run_id else None,
        uuid.UUID(job_id) if job_id else None,
        train_start,
        train_end,
        test_start,
        test_end,
    )
    return {"id": str(exp_id), "ref": ref}


async def complete_experiment(
    conn: asyncpg.Connection, experiment_ref: str, outcome: Mapping[str, Any]
) -> str | None:
    """
    Attach the engine's result and decide the conclusion mechanically.

    ``outcome`` is copied from ``backtest_runs.metrics`` or the equivalent, and
    the conclusion is :func:`evaluate_preregistered` applied to it. Nothing
    reads prose to decide whether an experiment passed, and nothing writes a
    conclusion by hand.
    """
    row = await conn.fetchrow(
        "SELECT preregistered_criteria FROM experiments WHERE ref = $1",
        experiment_ref,
    )
    if row is None:
        return None
    criteria = loads_json(row["preregistered_criteria"], [])
    payload = dict(outcome)
    # Carried alongside the metrics so a gate reading the outcome can re-derive
    # the verdict without a second query.
    payload["preregistered_criteria"] = criteria
    verdict = evaluate_preregistered(criteria, payload)
    conclusion = (
        "inconclusive" if verdict is None else ("pass" if verdict else "fail")
    )
    await conn.execute(
        "UPDATE experiments SET status='succeeded', outcome=$2::jsonb, "
        "conclusion=$3, finished_at=NOW() WHERE ref=$1",
        experiment_ref,
        json.dumps(payload, sort_keys=True, default=str),
        conclusion,
    )
    return conclusion


async def fail_experiment(
    conn: asyncpg.Connection, experiment_ref: str, error: str
) -> None:
    await conn.execute(
        "UPDATE experiments SET status='failed', error=$2, finished_at=NOW() "
        "WHERE ref=$1",
        experiment_ref,
        error,
    )


async def list_experiments(
    conn: asyncpg.Connection, candidate_id: str | None = None, limit: int = 200
) -> list[dict[str, Any]]:
    if candidate_id:
        rows = await conn.fetch(
            "SELECT * FROM experiments WHERE candidate_id = $1 "
            "ORDER BY created_at DESC LIMIT $2",
            uuid.UUID(candidate_id),
            limit,
        )
    else:
        rows = await conn.fetch(
            "SELECT * FROM experiments ORDER BY created_at DESC LIMIT $1", limit
        )
    return [_decode_experiment(r) for r in rows]


async def get_experiment(
    conn: asyncpg.Connection, ref: str
) -> dict[str, Any] | None:
    row = await conn.fetchrow("SELECT * FROM experiments WHERE ref = $1", ref)
    return _decode_experiment(row) if row else None


def _decode_experiment(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "ref": row["ref"],
        "hypothesis_id": str(row["hypothesis_id"]),
        "candidate_id": str(row["candidate_id"]),
        "kind": row["kind"],
        "code_commit": row["code_commit"],
        "dataset_manifest": loads_json(row["dataset_manifest"], {}),
        "seed": row["seed"],
        "universe": list(row["universe"]),
        "cost_assumptions": loads_json(row["cost_assumptions"], {}),
        "preregistered_criteria": loads_json(row["preregistered_criteria"], []),
        "backtest_run_id": (
            str(row["backtest_run_id"]) if row["backtest_run_id"] else None
        ),
        "walkforward_run_id": (
            str(row["walkforward_run_id"]) if row["walkforward_run_id"] else None
        ),
        "status": row["status"],
        "outcome": loads_json(row["outcome"], {}),
        "conclusion": row["conclusion"],
        "error": row["error"],
        "created_at": row["created_at"].isoformat(),
        "finished_at": (
            row["finished_at"].isoformat() if row["finished_at"] else None
        ),
    }


# ---------------------------------------------------------------------------
# Findings and assessments
# ---------------------------------------------------------------------------


class FindingClosureError(RuntimeError):
    """Something tried to close a finding without being an operator."""


async def raise_finding(
    conn: asyncpg.Connection,
    candidate_id: str | None,
    raised_by: str,
    severity: str,
    title: str,
    detail: str = "",
    remediation: str = "",
) -> dict[str, Any]:
    """
    Record a defect. Only ever opens one; closing is a separate, operator act.

    Deliberately has no counterpart in this module that a tick could call. The
    close path lives behind the API and stamps ``operator:<subject>``, which is
    the only string the schema's CHECK constraint accepts — so a role cannot
    retract its own veto even by calling into the repository directly.
    """
    finding_id = uuid.uuid4()
    ref = await _next_ref(conn, "findings", "F")
    await conn.execute(
        """
        INSERT INTO findings (id, ref, candidate_id, raised_by, severity,
                              title, detail_md, remediation)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
        """,
        finding_id,
        ref,
        uuid.UUID(candidate_id) if candidate_id else None,
        raised_by,
        severity,
        title,
        detail,
        remediation,
    )
    logger.info("Finding %s raised by %s (%s): %s", ref, raised_by, severity, title)
    return {"id": str(finding_id), "ref": ref}


async def close_finding(
    conn: asyncpg.Connection, ref: str, status: str, closed_by: str, note: str = ""
) -> None:
    """
    Resolve a finding. ``closed_by`` must name an operator.

    Checked here as well as by the schema, so the failure is a clear exception
    rather than a constraint violation whose message names a CHECK. Both
    checks stay: this one explains, the database one guarantees.
    """
    if status == "open":
        raise ValueError("close_finding cannot return a finding to open")
    if not closed_by.startswith("operator:"):
        raise FindingClosureError(
            "a finding can only be closed by an operator; a role that could "
            "clear its own veto has not vetoed anything"
        )
    await conn.execute(
        "UPDATE findings SET status=$2, closed_by=$3, close_note=$4, "
        "closed_at=NOW() WHERE ref=$1",
        ref,
        status,
        closed_by,
        note,
    )


async def list_findings(
    conn: asyncpg.Connection,
    candidate_id: str | None = None,
    only_open: bool = False,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    args: list[Any] = []
    if candidate_id:
        args.append(uuid.UUID(candidate_id))
        clauses.append(f"candidate_id = ${len(args)}")
    if only_open:
        clauses.append("status = 'open'")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = await conn.fetch(
        f"SELECT * FROM findings {where} ORDER BY opened_at DESC LIMIT 500"  # noqa: S608
        , *args,
    )
    return [
        {
            "id": str(r["id"]),
            "ref": r["ref"],
            "candidate_id": str(r["candidate_id"]) if r["candidate_id"] else None,
            "raised_by": r["raised_by"],
            "severity": r["severity"],
            "title": r["title"],
            "detail_md": r["detail_md"],
            "remediation": r["remediation"],
            "status": r["status"],
            "opened_at": r["opened_at"].isoformat(),
            "closed_at": r["closed_at"].isoformat() if r["closed_at"] else None,
            "closed_by": r["closed_by"],
            "close_note": r["close_note"],
        }
        for r in rows
    ]


async def record_assessment(
    conn: asyncpg.Connection,
    candidate_id: str,
    role: str,
    verdict: str,
    summary: str,
    stage: int,
    model: str = "",
    evidence: Mapping[str, Any] | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO role_assessments (candidate_id, role, verdict, summary,
                                      evidence, stage, model)
        VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7)
        """,
        uuid.UUID(candidate_id),
        role,
        verdict,
        summary,
        json.dumps(dict(evidence or {}), default=str),
        stage,
        model,
    )


async def list_assessments(
    conn: asyncpg.Connection, candidate_id: str, limit: int = 100
) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        "SELECT * FROM role_assessments WHERE candidate_id = $1 "
        "ORDER BY created_at DESC LIMIT $2",
        uuid.UUID(candidate_id),
        limit,
    )
    return [
        {
            "id": r["id"],
            "role": r["role"],
            "verdict": r["verdict"],
            "summary": r["summary"],
            "evidence": loads_json(r["evidence"], {}),
            "stage": r["stage"],
            "model": r["model"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Facts for the gate engine
# ---------------------------------------------------------------------------


async def load_facts(
    conn: asyncpg.Connection, candidate_id: str
) -> CandidateFacts | None:
    """
    Assemble the frozen snapshot the gates judge.

    All the I/O lives here so :mod:`src.programme.gates` can stay pure. Note
    what is *not* fetched: no prose, no commentary, no model output beyond the
    hypothesis card's presence. A gate cannot be talked round because it is
    never told anything that could do the talking.
    """
    cand = await get_candidate(conn, candidate_id)
    if cand is None:
        return None

    hyp = await conn.fetchrow(
        "SELECT ref, owner, card FROM hypotheses WHERE id = $1",
        uuid.UUID(cand["hypothesis_id"]),
    )

    exp_rows = await conn.fetch(
        """
        SELECT e.ref, e.kind, e.status, e.conclusion, e.seed, e.outcome,
               e.cost_assumptions, e.backtest_run_id, e.walkforward_run_id,
               b.data_source
        FROM experiments e
        LEFT JOIN backtest_runs b ON b.id = e.backtest_run_id
        WHERE e.candidate_id = $1
        ORDER BY e.created_at DESC
        """,
        uuid.UUID(candidate_id),
    )
    experiments = tuple(
        ExperimentFact(
            ref=r["ref"],
            kind=r["kind"],
            status=r["status"],
            conclusion=r["conclusion"],
            backtest_run_id=(
                str(r["backtest_run_id"]) if r["backtest_run_id"] else None
            ),
            walkforward_run_id=(
                str(r["walkforward_run_id"]) if r["walkforward_run_id"] else None
            ),
            data_source=r["data_source"] or "",
            cost_stress_multiplier=_stress_of(r["cost_assumptions"]),
            seed=r["seed"],
            outcome=loads_json(r["outcome"], {}),
        )
        for r in exp_rows
    )

    wf_rows = await conn.fetch(
        """
        SELECT w.id, w.status, w.params, w.is_robust, w.degradation, w.metrics
        FROM walkforward_runs w
        JOIN experiments e ON e.walkforward_run_id = w.id
        WHERE e.candidate_id = $1
        """,
        uuid.UUID(candidate_id),
    )
    walkforwards = tuple(
        WalkforwardFact(
            run_id=str(r["id"]),
            status=r["status"],
            params=loads_json(r["params"], {}),
            is_robust=r["is_robust"],
            degradation=float(r["degradation"]) if r["degradation"] else None,
            # `.get` rather than `[...]`: a study recorded before these
            # statistics existed has no key, and a missing measurement must
            # read as None rather than as a good score.
            pbo=_maybe_float(
                loads_json(r["metrics"], {}).get(
                    "probability_of_backtest_overfitting"
                )
            ),
            deflated_sharpe=_maybe_float(
                loads_json(r["metrics"], {}).get("deflated_sharpe")
            ),
        )
        for r in wf_rows
    )

    finding_rows = await conn.fetch(
        "SELECT ref, raised_by, severity, title, status FROM findings "
        "WHERE candidate_id = $1 AND status = 'open'",
        uuid.UUID(candidate_id),
    )
    findings = tuple(
        FindingFact(
            ref=r["ref"],
            raised_by=r["raised_by"],
            severity=r["severity"],
            title=r["title"],
            status=r["status"],
        )
        for r in finding_rows
    )

    shadow_rows = await conn.fetch(
        """
        SELECT session, rebalanced, order_intents, underfunded, error
        FROM shadow_decisions WHERE candidate_id = $1 ORDER BY session
        """,
        uuid.UUID(candidate_id),
    )
    shadow = tuple(
        ShadowFact(
            session=r["session"],
            rebalanced=r["rebalanced"],
            order_intents=len(loads_json(r["order_intents"], [])),
            underfunded=len(loads_json(r["underfunded"], [])),
            error=r["error"],
        )
        for r in shadow_rows
    )

    coverage_rows = await conn.fetch(
        """
        SELECT symbol, COUNT(*) AS bars FROM daily_bars
        WHERE symbol = ANY($1) AND session BETWEEN $2 AND $3
        GROUP BY symbol
        """,
        cand["universe"],
        date.fromisoformat(cand["start_session"]),
        date.fromisoformat(cand["end_session"]),
    )

    return CandidateFacts(
        stage=cand["stage"],
        status=cand["status"],
        params=cand["params"],
        universe=tuple(cand["universe"]),
        start_session=date.fromisoformat(cand["start_session"]),
        end_session=date.fromisoformat(cand["end_session"]),
        data_source=cand["data_source"],
        evidence_is_synthetic=cand["evidence_is_synthetic"],
        hypothesis_ref=hyp["ref"] if hyp else "",
        hypothesis_owner=hyp["owner"] if hyp else "",
        hypothesis_card=loads_json(hyp["card"], {}) if hyp else {},
        universe_coverage={r["symbol"]: int(r["bars"]) for r in coverage_rows},
        experiments=experiments,
        walkforwards=walkforwards,
        findings=findings,
        shadow=shadow,
        has_deployment=cand["deployment_id"] is not None,
    )


def _stress_of(cost_assumptions: Any) -> float | None:
    payload = loads_json(cost_assumptions, {})
    value = payload.get("stress_multiplier", payload.get("cost_stress"))
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Gate evaluations and promotion
# ---------------------------------------------------------------------------


async def record_gate(
    conn: asyncpg.Connection,
    candidate_id: str,
    result: GateResult,
    promoted: bool = False,
    approved_by: str | None = None,
) -> int:
    """Append the judgement, whether or not it promoted anything."""
    return int(
        await conn.fetchval(
            """
            INSERT INTO gate_evaluations (candidate_id, from_stage, to_stage,
                criteria, passed, requires_human, promoted, approved_by)
            VALUES ($1,$2,$3,$4::jsonb,$5,$6,$7,$8)
            RETURNING id
            """,
            uuid.UUID(candidate_id),
            result.from_stage,
            result.to_stage,
            json.dumps([c.as_dict() for c in result.criteria], default=str),
            result.passed,
            result.requires_human,
            promoted,
            approved_by,
        )
    )


async def latest_gate(
    conn: asyncpg.Connection, candidate_id: str
) -> dict[str, Any] | None:
    row = await conn.fetchrow(
        "SELECT * FROM gate_evaluations WHERE candidate_id = $1 "
        "ORDER BY evaluated_at DESC LIMIT 1",
        uuid.UUID(candidate_id),
    )
    if row is None:
        return None
    return {
        "id": row["id"],
        "from_stage": row["from_stage"],
        "to_stage": row["to_stage"],
        "criteria": loads_json(row["criteria"], []),
        "passed": row["passed"],
        "requires_human": row["requires_human"],
        "promoted": row["promoted"],
        "approved_by": row["approved_by"],
        "evaluated_at": row["evaluated_at"].isoformat(),
    }


async def promote(
    conn: asyncpg.Connection, candidate_id: str, to_stage: int
) -> None:
    """
    Advance a candidate. Never called except after a passed gate.

    The caller is responsible for that, and both callers — the runner and the
    API — check. The API's check is the one that matters: it makes a human
    approval a confirmation of a pass rather than an override of a failure.
    """
    await conn.execute(
        "UPDATE candidates SET stage = $2, stage_entered_at = NOW() WHERE id = $1",
        uuid.UUID(candidate_id),
        to_stage,
    )


#: Risk limits a shadow deployment is created with.
#:
#: The cash buffer is not a nicety. A target that invests every last dollar
#: leaves nothing to absorb the slippage between the decision price and the
#: fill, so the simulated venue trims the buy — and a real venue rejects it
#: outright. Every such trim lands in ``SimulatedBroker.underfunded_buys``, and
#: gate 3 -> 4 refuses a candidate with any, because the shadow book and a live
#: one have already diverged in holdings however identical their intents were.
#:
#: One percent, discovered rather than chosen: without it every shadow
#: candidate trips that criterion on its first session, which is the gate
#: correctly reporting a real divergence and not a threshold set too tight.
SHADOW_RISK_LIMITS: dict[str, Any] = {"cash_buffer_pct": 0.01}


async def ensure_shadow_deployment(
    conn: asyncpg.Connection, candidate_id: str
) -> str | None:
    """
    Give a candidate entering stage 3 something to operate against.

    The row is created **disabled** and stays that way for the whole of shadow
    mode. ``_enabled_deployments`` in the worker filters on ``status``, so a
    disabled deployment cannot be picked up by the live loop however long it
    sits there — the shadow job reaches it by id, deliberately, and submits
    nothing.

    ``approved_backtest_run_id`` is required by the schema, and by the time a
    candidate is at stage 3 the 2 -> 3 gate has already established that a
    succeeded backtest and a robust walk-forward of these exact parameters
    exist. This does not re-check that; it reads the row the gate read.

    Returns ``None`` when there is no approved backtest to point at, which
    should be impossible at this stage and is reported rather than assumed
    away.
    """
    cand = await get_candidate(conn, candidate_id)
    if cand is None:
        return None
    if cand["deployment_id"]:
        return cand["deployment_id"]

    approved = await conn.fetchval(
        """
        SELECT b.id FROM experiments e
        JOIN backtest_runs b ON b.id = e.backtest_run_id
        WHERE e.candidate_id = $1 AND e.kind = 'backtest' AND b.status = 'succeeded'
        ORDER BY e.created_at DESC LIMIT 1
        """,
        uuid.UUID(candidate_id),
    )
    if approved is None:
        logger.error(
            "Candidate %s reached shadow with no succeeded backtest to approve "
            "a deployment against",
            candidate_id,
        )
        return None

    deployment_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO deployments (id, owner_id, strategy_name, params, mode,
            capital_usd, risk_limits, approved_backtest_run_id, status)
        VALUES ($1,'programme',$2,$3::jsonb,'paper',$4,$5::jsonb,$6,'disabled')
        """,
        deployment_id,
        cand["strategy_name"],
        json.dumps(cand["params"], sort_keys=True, default=str),
        0,
        json.dumps(SHADOW_RISK_LIMITS),
        approved,
    )
    await conn.execute(
        "UPDATE candidates SET deployment_id = $2 WHERE id = $1",
        uuid.UUID(candidate_id),
        deployment_id,
    )
    logger.info(
        "Created disabled shadow deployment %s for candidate %s",
        deployment_id,
        candidate_id,
    )
    return str(deployment_id)


async def shadow_sessions_recorded(
    conn: asyncpg.Connection, candidate_id: str
) -> set[date]:
    rows = await conn.fetch(
        "SELECT session FROM shadow_decisions WHERE candidate_id = $1",
        uuid.UUID(candidate_id),
    )
    return {r["session"] for r in rows}


async def list_shadow_decisions(
    conn: asyncpg.Connection, candidate_id: str, limit: int = 200
) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT session, rebalanced, target_weights, order_intents, risk_events,
               rationale, equity, underfunded, error, created_at
        FROM shadow_decisions WHERE candidate_id = $1
        ORDER BY session DESC LIMIT $2
        """,
        uuid.UUID(candidate_id),
        limit,
    )
    return [
        {
            "session": r["session"].isoformat(),
            "rebalanced": r["rebalanced"],
            "target_weights": loads_json(r["target_weights"], {}),
            "order_intents": loads_json(r["order_intents"], []),
            "risk_events": loads_json(r["risk_events"], []),
            "rationale": r["rationale"],
            "equity": float(r["equity"]) if r["equity"] is not None else None,
            "underfunded": loads_json(r["underfunded"], []),
            "error": r["error"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


async def record_decision(
    conn: asyncpg.Connection,
    subject_type: str,
    subject_id: str,
    decision: str,
    made_by: str,
    rationale: str = "",
    evidence: Mapping[str, Any] | None = None,
    code_version: str = "",
) -> str:
    dec_id = uuid.uuid4()
    ref = await _next_ref(conn, "programme_decisions", "D")
    await conn.execute(
        """
        INSERT INTO programme_decisions (id, ref, subject_type, subject_id,
            decision, rationale_md, evidence, made_by, code_version)
        VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9)
        """,
        dec_id,
        ref,
        subject_type,
        subject_id,
        decision,
        rationale,
        json.dumps(dict(evidence or {}), default=str),
        made_by,
        code_version,
    )
    return ref


# ---------------------------------------------------------------------------
# Ticks
# ---------------------------------------------------------------------------


async def request_tick(
    conn: asyncpg.Connection, requested_by: str
) -> str:
    """Ask the runner for an immediate pass. The API never runs one itself."""
    run_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO programme_runs (id, trigger, status, requested_by) "
        "VALUES ($1, 'manual', 'requested', $2)",
        run_id,
        requested_by,
    )
    return str(run_id)


async def claim_tick(
    conn: asyncpg.Connection, trigger: str = "scheduled"
) -> str | None:
    """
    Take the oldest requested tick, or open a scheduled one.

    ``FOR UPDATE SKIP LOCKED`` so two runners cannot claim the same request,
    the same discipline the worker uses on the job queue.
    """
    async with conn.transaction():
        row = await conn.fetchrow(
            "SELECT id FROM programme_runs WHERE status = 'requested' "
            "ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1"
        )
        if row is not None:
            await conn.execute(
                "UPDATE programme_runs SET status='running', started_at=NOW() "
                "WHERE id = $1",
                row["id"],
            )
            return str(row["id"])
    run_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO programme_runs (id, trigger, status, started_at, "
        "requested_by) VALUES ($1, $2, 'running', NOW(), 'scheduler')",
        run_id,
        trigger,
    )
    return str(run_id)


async def finish_tick(
    conn: asyncpg.Connection,
    run_id: str,
    actions: Sequence[Mapping[str, Any]],
    status: str = "succeeded",
    model: str = "",
    error: str | None = None,
) -> None:
    await conn.execute(
        "UPDATE programme_runs SET status=$2, actions=$3::jsonb, model=$4, "
        "error=$5, finished_at=NOW() WHERE id=$1",
        uuid.UUID(run_id),
        status,
        json.dumps(list(actions), default=str),
        model,
        error,
    )


async def list_runs(
    conn: asyncpg.Connection, limit: int = 50
) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        "SELECT * FROM programme_runs ORDER BY created_at DESC LIMIT $1", limit
    )
    return [
        {
            "id": str(r["id"]),
            "trigger": r["trigger"],
            "status": r["status"],
            "actions": loads_json(r["actions"], []),
            "model": r["model"],
            "error": r["error"],
            "requested_by": r["requested_by"],
            "created_at": r["created_at"].isoformat(),
            "started_at": r["started_at"].isoformat() if r["started_at"] else None,
            "finished_at": (
                r["finished_at"].isoformat() if r["finished_at"] else None
            ),
        }
        for r in rows
    ]
