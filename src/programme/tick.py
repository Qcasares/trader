"""
tick.py
-------
One pass of the programme.

The order is deliberate and it is the order a careful researcher would use:

1. **Reconcile.** Attach finished engine results to the experiments waiting on
   them, and decide each conclusion by evaluating the preregistered criteria.
   Done first so the gates below judge today's evidence rather than
   yesterday's.
2. **Convene.** Ask the stage's specialist panel for its views, record each
   verbatim, and open any findings they raise. Before the promotion decision,
   not after it: a review of something already promoted is an audit, and an
   audit is not a control.
3. **Judge.** Re-evaluate the gate — the panel may have just raised a blocking
   finding — record the judgement, and promote where the gate passed, no
   operator is required, and the autonomy ceiling permits it.
4. **Fill the gaps.** For a candidate the gate refused, enqueue the experiments
   whose absence refused it. This is the only reason the programme queues work:
   it never runs an experiment because a result might be interesting.
5. **Propose.** If the pipeline has room, ask the model for a hypothesis and a
   configuration to test it with.

Steps 1, 3 and 4 need no model at all. A tick with no API key does all of them
and records that it skipped the other two, which is the right degradation: the
governance machinery is the part that must keep working. The panel's absence
never *unblocks* anything, because a finding it already raised stays open.

Three independent things must agree before this promotes a candidate: the gate
passes, ``requires_human`` is false, and the stage is within the autonomy
ceiling. The ceiling is a database row read fail-closed to zero and clamped in
code below ``FIRST_HUMAN_GATED_STAGE``, so raising it cannot authorise a model
to move capital however it is set.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import asyncpg

from src.core import calendar
from src.db.repos import backtests as backtest_repo
from src.db.repos import jobs as job_repo
from src.programme import author, flags, gates, repo, roles
from src.programme.gates import (
    MIN_COST_STRESS_MULTIPLIER,
    evaluate,
    replication_agrees,
)
from src.programme.models import ModelSettings
from src.strategies import build_strategy, get_strategy_class

logger = logging.getLogger(__name__)

#: How many candidates may sit in the research stages at once.
#:
#: A cap rather than a rate limit, because the cost that matters is not tokens
#: but attention: a board of forty candidates nobody reads is the same as no
#: board. It is also the multiple-testing control — every extra candidate is
#: another draw, and the ledger records how many were taken.
MAX_ACTIVE_RESEARCH_CANDIDATES = 8

#: Cost multiplier used for the stressed run. Above the gate's floor on
#: purpose: the gate asks for at least 2x, and a run at exactly the threshold
#: leaves no room for the cost model itself to be optimistic.
STRESS_MULTIPLIER = max(3.0, MIN_COST_STRESS_MULTIPLIER)

#: Fraction by which numeric parameters are perturbed for the neighbourhood
#: run. A result that survives 1.2x its own parameter is not proof of
#: stability, but a result that does not survive it is proof of the opposite.
NEIGHBOURHOOD_FACTOR = 1.2

DEFAULT_INITIAL_CASH = 100_000.0

#: The stage at which a candidate operates in shadow.
SHADOW_STAGE = 3

#: How many shadow sessions may be queued in one pass.
#:
#: A candidate promoted into shadow with a year of calendar behind it would
#: otherwise queue two hundred jobs at once, and the live decision path shares
#: this queue. Ten a pass backfills a month in three passes and never starves
#: anything.
MAX_SHADOW_SESSIONS_PER_TICK = 10

#: Experiment kinds this tick knows how to enqueue, and the gate criterion each
#: one answers. Ordered so the plain backtest exists before anything is
#: compared against it.
BACKTEST_KINDS = (
    "backtest",
    "cost_stress",
    "parameter_neighbourhood",
    "benchmark",
    "replication",
)


@dataclass(slots=True)
class TickReport:
    """What the pass did. Written to ``programme_runs.actions`` verbatim."""

    actions: list[dict[str, Any]] = field(default_factory=list)
    model_used: str = ""

    def note(self, action: str, **detail: Any) -> None:
        self.actions.append({"action": action, **detail})
        logger.info("programme: %s %s", action, detail)


def code_version() -> str:
    """
    The commit this tick ran. Empty when the deployment did not say.

    Read from the environment rather than by shelling out to git: the runner
    may be a container with no repository in it, and a reproducibility field
    that is quietly wrong is worse than one that is honestly blank.
    """
    for name in ("GIT_COMMIT", "VERCEL_GIT_COMMIT_SHA", "SOURCE_COMMIT"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


async def run_tick(
    conn: asyncpg.Connection,
    api_key: str | None,
    settings: ModelSettings | None,
) -> TickReport:
    """
    Do one pass. Never raises for a single candidate's sake.

    ``settings`` is ``None`` when the operator's model configuration could not
    be read or is unusable, and that is not the same condition as a missing API
    key even though both land in the same place: no model call. Both are noted
    on the run, because a pass that reconciled experiments and evaluated gates
    without proposing anything should say which of the two reasons applied
    rather than look like a pass with nothing to propose.
    """
    report = TickReport()
    if settings is None:
        report.note(
            "model_unconfigured",
            reason=(
                "the model settings are missing or unusable; this pass will "
                "reconcile, evaluate and promote, and will not call a model"
            ),
        )

    await _reconcile_experiments(conn, report)

    ceiling = await flags.max_auto_stage(conn)
    report.note("autonomy_ceiling", max_auto_stage=ceiling)

    candidates = [
        c for c in await repo.list_candidates(conn) if c["status"] == "active"
    ]
    for candidate in candidates:
        try:
            await _advance(conn, candidate, report, ceiling, api_key, settings)
        except Exception as exc:  # noqa: BLE001 - one bad candidate is not a tick
            logger.exception("candidate %s failed to advance", candidate["id"])
            report.note("candidate_error", candidate=candidate["id"], error=str(exc))

    research_count = sum(1 for c in candidates if c["stage"] <= 2)
    if research_count < MAX_ACTIVE_RESEARCH_CANDIDATES:
        await _propose(conn, api_key, settings, report)
    else:
        report.note(
            "proposal_skipped",
            reason=(
                f"{research_count} candidates already in the research stages "
                f"(cap {MAX_ACTIVE_RESEARCH_CANDIDATES})"
            ),
        )
    return report


# ---------------------------------------------------------------------------
# 1. Reconcile
# ---------------------------------------------------------------------------


async def _reconcile_experiments(
    conn: asyncpg.Connection, report: TickReport
) -> None:
    """
    Attach finished engine results to the experiments waiting on them.

    The conclusion is computed by :func:`repo.complete_experiment`, which
    evaluates the preregistered criteria against the metrics. Nothing here
    decides whether a result was good.
    """
    rows = await conn.fetch(
        """
        SELECT e.ref, e.candidate_id, e.kind, b.status AS run_status,
               b.metrics, b.error, b.data_source
        FROM experiments e
        JOIN backtest_runs b ON b.id = e.backtest_run_id
        WHERE e.status IN ('queued', 'running')
        """
    )
    for row in rows:
        if row["run_status"] == "succeeded":
            metrics = repo.loads_json(row["metrics"], {})
            conclusion = await repo.complete_experiment(conn, row["ref"], metrics)
            if row["data_source"] == "synthetic":
                await conn.execute(
                    "UPDATE candidates SET evidence_is_synthetic = TRUE "
                    "WHERE id = $1",
                    row["candidate_id"],
                )
            report.note(
                "experiment_completed",
                experiment=row["ref"],
                kind=row["kind"],
                conclusion=conclusion,
            )
        elif row["run_status"] == "failed":
            await repo.fail_experiment(conn, row["ref"], row["error"] or "unknown")
            report.note("experiment_failed", experiment=row["ref"])

    await _reconcile_walkforwards(conn, report)
    await _judge_replications(conn, report)


async def _reconcile_walkforwards(
    conn: asyncpg.Connection, report: TickReport
) -> None:
    rows = await conn.fetch(
        """
        SELECT e.ref, w.status, w.is_robust, w.degradation, w.mean_oos_sharpe,
               w.error
        FROM experiments e
        JOIN walkforward_runs w ON w.id = e.walkforward_run_id
        WHERE e.status IN ('queued', 'running')
        """
    )
    for row in rows:
        if row["status"] == "succeeded":
            await repo.complete_experiment(
                conn,
                row["ref"],
                {
                    "is_robust": row["is_robust"],
                    "degradation": (
                        float(row["degradation"])
                        if row["degradation"] is not None
                        else None
                    ),
                    "sharpe": (
                        float(row["mean_oos_sharpe"])
                        if row["mean_oos_sharpe"] is not None
                        else None
                    ),
                },
            )
            report.note("walkforward_completed", experiment=row["ref"])
        elif row["status"] == "failed":
            await repo.fail_experiment(conn, row["ref"], row["error"] or "unknown")


async def _judge_replications(
    conn: asyncpg.Connection, report: TickReport
) -> None:
    """
    Decide whether each replication reproduced the run it was checking.

    A replication's preregistered criteria cannot express "agrees with
    experiment E-0001", so its conclusion is overwritten here by comparing the
    two outcomes. This is the one place a conclusion is set by something other
    than the preregistered criteria, and it is still a deterministic
    comparison of two numbers the engine produced.
    """
    rows = await conn.fetch(
        """
        SELECT r.ref, r.conclusion, r.outcome AS replicate, b.outcome AS reference
        FROM experiments r
        JOIN experiments b
          ON b.candidate_id = r.candidate_id
         AND b.kind = 'backtest'
         AND b.status = 'succeeded'
        WHERE r.kind = 'replication' AND r.status = 'succeeded'
        """
    )
    for row in rows:
        reference = repo.loads_json(row["reference"], {})
        replicate = repo.loads_json(row["replicate"], {})
        verdict = "pass" if replication_agrees(reference, replicate) else "fail"
        # Recomputed every tick because it is a cheap deterministic comparison,
        # and written only when it changes, so a tick's action list records
        # events rather than restating a settled fact each time it runs.
        if verdict == row["conclusion"]:
            continue
        await conn.execute(
            "UPDATE experiments SET conclusion = $2 WHERE ref = $1",
            row["ref"],
            verdict,
        )
        report.note("replication_judged", experiment=row["ref"], verdict=verdict)


# ---------------------------------------------------------------------------
# 2 and 3. Judge, then fill the gaps
# ---------------------------------------------------------------------------


async def _advance(
    conn: asyncpg.Connection,
    candidate: dict[str, Any],
    report: TickReport,
    ceiling: int,
    api_key: str | None,
    settings: ModelSettings | None,
) -> None:
    facts = await repo.load_facts(conn, candidate["id"])
    if facts is None:
        return

    result = evaluate(facts)

    # The panel runs before the promotion decision, not after it, so a finding
    # raised this pass blocks this pass. Reviewing something already promoted
    # is an audit, and an audit is not a control.
    await _convene(conn, candidate, result, report, api_key, settings)

    # Reloaded, because the panel may have just raised a blocking finding. The
    # first evaluation is what the roles were shown; this one is what decides.
    facts = await repo.load_facts(conn, candidate["id"]) or facts
    result = evaluate(facts)

    within_ceiling = result.to_stage <= ceiling
    promoted = result.passed and not result.requires_human and within_ceiling
    await repo.record_gate(conn, candidate["id"], result, promoted=promoted)

    if result.passed and not result.requires_human and not within_ceiling:
        report.note(
            "promotion_withheld",
            candidate=candidate["id"],
            to_stage=result.to_stage,
            reason=(
                f"the autonomy ceiling is {ceiling}; raise it to promote "
                "without an operator"
            ),
        )
        return

    if promoted:
        await repo.promote(conn, candidate["id"], result.to_stage)
        await repo.record_decision(
            conn,
            subject_type="candidate",
            subject_id=candidate["id"],
            decision=f"promote_stage_{result.to_stage}",
            made_by="gate_engine",
            rationale="every criterion met; no operator approval required",
            evidence=result.as_dict(),
            code_version=code_version(),
        )
        report.note(
            "promoted",
            candidate=candidate["id"],
            to_stage=result.to_stage,
        )
        return

    if result.passed and result.requires_human:
        report.note(
            "awaiting_operator",
            candidate=candidate["id"],
            to_stage=result.to_stage,
        )
        return

    await _enqueue_missing_evidence(conn, candidate, result, report)


async def _convene(
    conn: asyncpg.Connection,
    candidate: dict[str, Any],
    result: Any,
    report: TickReport,
    api_key: str | None,
    settings: ModelSettings | None,
) -> None:
    """
    Run the stage-relevant panel, record every view, and open any findings.

    Each role is asked independently and its answer stored verbatim. Nothing
    here reconciles two roles that disagree: the operating prompt asks for
    disagreement to be exposed, and a "consensus" field would be a fourth
    opinion nobody held.

    Findings are opened, never closed. The only close path is an operator
    endpoint, and the schema refuses any other.
    """
    if not api_key or settings is None:
        return

    panel = roles.roles_for_stage(candidate["stage"])
    if not panel:
        return

    # Convened once per stage, not once per tick. The evidence a role reasons
    # about changes when an experiment completes, and an hourly re-run of the
    # same panel over the same rows would spend money to produce the same
    # paragraph and bury the pass in noise.
    already = await conn.fetchval(
        "SELECT COUNT(DISTINCT role) FROM role_assessments "
        "WHERE candidate_id = $1 AND stage = $2",
        uuid.UUID(candidate["id"]),
        candidate["stage"],
    )
    if int(already or 0) >= len(panel):
        return

    seen = {
        r["role"]
        for r in await conn.fetch(
            "SELECT DISTINCT role FROM role_assessments "
            "WHERE candidate_id = $1 AND stage = $2",
            uuid.UUID(candidate["id"]),
            candidate["stage"],
        )
    }
    candidate_view = dict(candidate)
    candidate_view["experiments"] = await repo.list_experiments(
        conn, candidate["id"]
    )
    brief = roles.facts_brief(candidate_view, result.as_dict())

    for role in panel:
        if role.key in seen:
            continue
        try:
            assessment = await panel.assess(role, api_key, settings, brief)
        except Exception as exc:  # noqa: BLE001 - one role is not the panel
            report.note("assessment_failed", role=role.key, error=str(exc))
            continue

        await repo.record_assessment(
            conn,
            candidate_id=candidate["id"],
            role=role.key,
            verdict=assessment.verdict,
            summary=assessment.summary,
            stage=candidate["stage"],
            model=settings.model,
            evidence={"gate": result.as_dict()},
        )
        report.note(
            "assessment_recorded",
            candidate=candidate["id"],
            role=role.key,
            verdict=assessment.verdict,
            findings=len(assessment.findings),
            blocking=roles.blocking_count(assessment, role),
        )

        for proposed in assessment.findings:
            finding = await repo.raise_finding(
                conn,
                candidate_id=candidate["id"],
                raised_by=role.key,
                severity=proposed.severity,
                title=proposed.title,
                detail=proposed.detail,
                remediation=proposed.remediation,
            )
            report.note(
                "finding_raised",
                finding=finding["ref"],
                role=role.key,
                severity=proposed.severity,
                blocks=role.holds_veto
                and proposed.severity in gates.BLOCKING_SEVERITIES,
            )


async def _enqueue_missing_evidence(
    conn: asyncpg.Connection,
    candidate: dict[str, Any],
    result: Any,
    report: TickReport,
) -> None:
    """Queue exactly the experiments whose absence refused the gate."""
    unmet = {c.id for c in result.unmet}
    existing = await conn.fetch(
        "SELECT kind, status FROM experiments WHERE candidate_id = $1",
        uuid.UUID(candidate["id"]),
    )
    live_kinds = {
        r["kind"] for r in existing if r["status"] in ("queued", "running", "succeeded")
    }

    wanted: list[str] = []
    if "backtest_succeeded" in unmet or "effective_start_recorded" in unmet:
        wanted.append("backtest")
    if "cost_stress" in unmet:
        wanted.append("cost_stress")
    if "parameter_neighbourhood" in unmet:
        wanted.append("parameter_neighbourhood")
    if "benchmark_comparison" in unmet:
        wanted.append("benchmark")
    if "replicated" in unmet:
        wanted.append("replication")
    if "walkforward_robust" in unmet:
        wanted.append("walkforward")

    for kind in wanted:
        if kind in live_kinds:
            continue
        if kind == "walkforward":
            await _enqueue_walkforward(conn, candidate, report)
        else:
            await _enqueue_backtest(conn, candidate, kind, report)

    if candidate["stage"] == SHADOW_STAGE:
        await _enqueue_shadow(conn, candidate, report)


async def _enqueue_shadow(
    conn: asyncpg.Connection, candidate: dict[str, Any], report: TickReport
) -> None:
    """
    Queue the shadow sessions this candidate has not yet recorded.

    The programme cannot run one itself: the shadow job imports
    ``src.worker.live_job``, and ``src/programme`` is forbidden from importing
    the worker because it is the package holding the model client. So it
    enqueues, with a dedupe key, and the worker picks the work up — the same
    division as every other job this module creates.

    ``shadow_decision`` is not a scheduled kind. The session planner does not
    emit it, so it stays out of ``SCHEDULED_KINDS``; adding it there would
    break the set comparison in ``test_scheduling.py`` and, worse, would start
    shadowing every deployment on every session.
    """
    deployment_id = await repo.ensure_shadow_deployment(conn, candidate["id"])
    if deployment_id is None:
        report.note(
            "shadow_blocked",
            candidate=candidate["id"],
            reason="no succeeded backtest to approve a deployment against",
        )
        return

    entered = date.fromisoformat(candidate["stage_entered_at"][:10])
    today = date.today()
    if today <= entered:
        return

    already = await repo.shadow_sessions_recorded(conn, candidate["id"])
    # Bounded per pass. A candidate promoted into shadow with a year of
    # calendar behind it would otherwise queue two hundred jobs at once and
    # starve the live decision path, which shares this queue.
    pending = [
        s
        for s in calendar.sessions(entered, today)
        if s not in already
    ][:MAX_SHADOW_SESSIONS_PER_TICK]

    for session in pending:
        job_id = await job_repo.enqueue(
            conn,
            "shadow_decision",
            {"candidate_id": candidate["id"], "session": session.isoformat()},
            dedupe_key=f"shadow:{candidate['id']}:{session.isoformat()}",
        )
        if job_id is not None:
            report.note(
                "shadow_queued", candidate=candidate["id"], session=str(session)
            )


def _neighbouring_params(params: dict[str, Any]) -> dict[str, Any]:
    """
    Nudge every numeric parameter by a fixed factor.

    Deterministic rather than random: a neighbourhood test that samples
    differently on each run cannot be replicated, and replication is a
    criterion two gates later.
    """
    out = dict(params)
    for key, value in params.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            out[key] = max(1, int(round(value * NEIGHBOURHOOD_FACTOR)))
        elif isinstance(value, float):
            out[key] = value * NEIGHBOURHOOD_FACTOR
    return out


async def _enqueue_backtest(
    conn: asyncpg.Connection,
    candidate: dict[str, Any],
    kind: str,
    report: TickReport,
) -> None:
    """
    Register an experiment and queue the backtest that answers it.

    The experiment row is written *before* the job, and it carries the
    acceptance criteria. There is no window in which a result exists and the
    test it was meant to satisfy does not.
    """
    strategy_name = candidate["strategy_name"]
    params = dict(candidate["params"])
    stress = 1.0
    seed: int | None = None

    if kind == "cost_stress":
        stress = STRESS_MULTIPLIER
    elif kind == "parameter_neighbourhood":
        params = _neighbouring_params(params)
    elif kind == "benchmark":
        strategy_name = "buy_and_hold"
        params = {"symbols": list(candidate["universe"])}
    elif kind == "replication":
        # Same configuration, re-run. The engine is deterministic, so a
        # disagreement here is a reproducibility defect rather than noise —
        # which is exactly what the criterion is for.
        seed = 1

    try:
        strategy_cls = get_strategy_class(strategy_name)
        strategy = build_strategy(strategy_name, params)
    except Exception as exc:  # noqa: BLE001
        report.note(
            "experiment_rejected",
            candidate=candidate["id"],
            kind=kind,
            error=str(exc),
        )
        return

    criteria = await _criteria_for(conn, candidate, kind)
    request = backtest_repo.BacktestRequest(
        strategy_name=strategy_name,
        strategy_version=strategy_cls.version,
        params=strategy.params_dict(),
        universe=strategy.universe(),
        start_session=date.fromisoformat(candidate["start_session"]),
        end_session=date.fromisoformat(candidate["end_session"]),
        initial_cash=DEFAULT_INITIAL_CASH,
        data_source=candidate["data_source"],
        cost_model={"stress_multiplier": stress},
    )
    run_id = await backtest_repo.create_run(conn, request)
    job_id = await job_repo.enqueue(conn, "backtest", {"run_id": str(run_id)})
    experiment = await repo.record_experiment(
        conn,
        candidate_id=candidate["id"],
        hypothesis_id=candidate["hypothesis_id"],
        kind=kind,
        preregistered_criteria=criteria,
        code_commit=code_version(),
        dataset_manifest={
            "source": candidate["data_source"],
            "symbols": strategy.universe(),
            "window": f"{candidate['start_session']}..{candidate['end_session']}",
        },
        seed=seed,
        universe=strategy.universe(),
        cost_assumptions={"stress_multiplier": stress},
        backtest_run_id=str(run_id),
        job_id=str(job_id) if job_id else None,
        test_start=date.fromisoformat(candidate["start_session"]),
        test_end=date.fromisoformat(candidate["end_session"]),
    )
    report.note(
        "experiment_queued",
        candidate=candidate["id"],
        kind=kind,
        experiment=experiment["ref"],
        strategy=strategy_name,
    )


async def _criteria_for(
    conn: asyncpg.Connection, candidate: dict[str, Any], kind: str
) -> list[dict[str, Any]]:
    """
    The acceptance test for one experiment, fixed before it runs.

    The plain backtest inherits the hypothesis card's own acceptance criteria
    where they parse, because that is what preregistration means: the test was
    written when the idea was, not when the answer arrived. The supporting runs
    get a test appropriate to what they are for — a stressed run must still
    clear zero, a benchmark run only has to complete.
    """
    if kind == "backtest":
        hypothesis = await conn.fetchrow(
            "SELECT card FROM hypotheses WHERE id = $1",
            uuid.UUID(candidate["hypothesis_id"]),
        )
        card = repo.loads_json(hypothesis["card"], {}) if hypothesis else {}
        parsed = _parse_card_criteria(card.get("acceptance_criteria", ""))
        if parsed:
            return parsed
        return [{"metric": "sharpe", "op": ">", "value": 0.0}]
    if kind == "cost_stress":
        return [{"metric": "sharpe", "op": ">", "value": 0.0}]
    if kind == "parameter_neighbourhood":
        return [{"metric": "sharpe", "op": ">", "value": 0.0}]
    if kind == "replication":
        return [{"metric": "sharpe", "op": ">=", "value": -99.0}]
    return [{"metric": "n_sessions", "op": ">", "value": 0}]


def _parse_card_criteria(text: str) -> list[dict[str, Any]]:
    """
    Read machine-checkable criteria out of a card's acceptance prose.

    Only accepts the explicit form ``metric op value``, one per line — for
    example ``sharpe >= 0.3``. Prose that does not parse yields nothing and the
    caller falls back to a floor, which is stated rather than inferred: the
    alternative is guessing at what a sentence meant and calling the guess a
    preregistered criterion.
    """
    out: list[dict[str, Any]] = []
    for line in str(text).splitlines():
        parts = line.replace(",", " ").split()
        if len(parts) != 3:
            continue
        metric, op, raw = parts
        if op not in (">=", ">", "<=", "<", "==", "!="):
            continue
        try:
            out.append({"metric": metric, "op": op, "value": float(raw)})
        except ValueError:
            continue
    return out


async def _enqueue_walkforward(
    conn: asyncpg.Connection, candidate: dict[str, Any], report: TickReport
) -> None:
    """
    Queue a walk-forward study of this candidate's exact parameters.

    Refused on synthetic data, matching the API: a walk-forward on generated
    prices proves nothing about robustness, because the generator has no regime
    to fail to generalise across.
    """
    if candidate["data_source"] == "synthetic" or candidate["evidence_is_synthetic"]:
        report.note(
            "walkforward_refused",
            candidate=candidate["id"],
            reason="synthetic prices have no regime to fail to generalise across",
        )
        return

    backtest = await conn.fetchrow(
        """
        SELECT b.id FROM experiments e JOIN backtest_runs b ON b.id = e.backtest_run_id
        WHERE e.candidate_id = $1 AND e.kind = 'backtest' AND b.status = 'succeeded'
        ORDER BY e.created_at DESC LIMIT 1
        """,
        uuid.UUID(candidate["id"]),
    )
    if backtest is None:
        report.note(
            "walkforward_deferred",
            candidate=candidate["id"],
            reason="no succeeded backtest to study",
        )
        return

    params = dict(candidate["params"])
    grid = _grid_around(params)
    if not grid:
        report.note(
            "walkforward_refused",
            candidate=candidate["id"],
            reason="no numeric parameter to vary",
        )
        return

    wf_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO walkforward_runs (id, backtest_run_id, strategy_name, params,
            param_grid, start_session, end_session, train_months, test_months,
            data_source, status)
        VALUES ($1,$2,$3,$4::jsonb,$5::jsonb,$6,$7,36,12,$8,'queued')
        """,
        wf_id,
        backtest["id"],
        candidate["strategy_name"],
        json.dumps(params, sort_keys=True),
        json.dumps(grid, sort_keys=True),
        date.fromisoformat(candidate["start_session"]),
        date.fromisoformat(candidate["end_session"]),
        candidate["data_source"],
    )
    job_id = await job_repo.enqueue(
        conn, "walkforward", {"walkforward_run_id": str(wf_id)}
    )
    experiment = await repo.record_experiment(
        conn,
        candidate_id=candidate["id"],
        hypothesis_id=candidate["hypothesis_id"],
        kind="walkforward",
        preregistered_criteria=[{"metric": "is_robust", "op": "==", "value": 1}],
        code_commit=code_version(),
        universe=candidate["universe"],
        walkforward_run_id=str(wf_id),
        job_id=str(job_id) if job_id else None,
    )
    report.note(
        "walkforward_queued",
        candidate=candidate["id"],
        experiment=experiment["ref"],
    )


def _grid_around(params: dict[str, Any]) -> dict[str, list[Any]]:
    """Three points around each numeric parameter, for the study to choose from."""
    grid: dict[str, list[Any]] = {}
    for key, value in params.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            grid[key] = sorted(
                {max(1, int(value * 0.7)), value, int(value * 1.3)}
            )
        elif isinstance(value, float):
            grid[key] = sorted({value * 0.7, value, value * 1.3})
    return grid


# ---------------------------------------------------------------------------
# 4. Propose
# ---------------------------------------------------------------------------


async def _propose(
    conn: asyncpg.Connection,
    api_key: str | None,
    settings: ModelSettings | None,
    report: TickReport,
) -> None:
    """
    Ask the model for a hypothesis and a way to test it.

    Every failure mode here is recorded and none is fatal. A rejected draft is
    a fact about the tick worth keeping: "the model proposed something that
    asserted a Sharpe ratio and it was refused" is exactly the kind of thing
    that should be visible rather than retried until it slips through.
    """
    if not api_key:
        report.note("proposal_skipped", reason="no ANTHROPIC_API_KEY configured")
        return
    if settings is None:
        report.note(
            "proposal_skipped", reason="the model settings are unusable"
        )
        return

    config_rows = await repo.get_config(conn)
    context = "\n".join(
        f"- {r['key']}: {r['value'] or 'TBD'}" for r in config_rows
    )
    existing = [h["title"] for h in await repo.list_hypotheses(conn, limit=50)]

    try:
        title, card = await author.propose_hypothesis(
            api_key, settings, context, existing
        )
    except Exception as exc:  # noqa: BLE001 - recorded, never fatal
        report.note("hypothesis_rejected", error=str(exc))
        return

    hypothesis = await repo.create_hypothesis(
        conn,
        title=title,
        card=card,
        owner="programme",
        origin="model",
        model=settings.model,
    )
    report.model_used = settings.model
    report.note("hypothesis_recorded", ref=hypothesis["ref"], title=title)

    try:
        config = await author.propose_configuration(
            api_key, settings, {"title": title, "card": card}
        )
    except Exception as exc:  # noqa: BLE001
        report.note(
            "configuration_rejected", hypothesis=hypothesis["ref"], error=str(exc)
        )
        return

    strategy = build_strategy(config.strategy, config.params)
    candidate_id = await repo.create_candidate(
        conn,
        hypothesis_id=hypothesis["id"],
        strategy_name=config.strategy,
        params=strategy.params_dict(),
        universe=strategy.universe(),
        start_session=date.fromisoformat(config.start_session),
        end_session=date.fromisoformat(config.end_session),
        data_source="yfinance",
    )
    report.note(
        "candidate_created",
        candidate=candidate_id,
        hypothesis=hypothesis["ref"],
        strategy=config.strategy,
    )
