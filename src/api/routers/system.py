"""
system.py
---------
The control plane: status, kill switch, jobs.

The kill switch is the only endpoint here that matters under stress, so it is
deliberately the simplest: one POST, one required field, no toggle semantics.
Engaging never fails on a bad reason string and never requires a confirmation
token — the asymmetry is intentional. Stopping should be frictionless;
starting should not.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status

from src.api.deps import AppSettings, AuthedSession, DbConn
from src.api.drain import drain_once
from src.api.schemas import (
    JobSummary,
    KillSwitchRequest,
    ReleaseKillSwitchRequest,
    SystemConfigurationRequest,
    SystemStatus,
)
from src.api.security import (
    SESSION_COOKIE,
    AuthError,
    InsecureSecretError,
    constant_time_equals,
    verify_session,
)
from src.db.migrate import MigrationError, current_version, migrate
from src.db.repos import flags
from src.db.repos import jobs as job_repo
from src.programme import flags as programme_flags
from src.programme import models as model_catalogue

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/system", tags=["system"])

#: A worker is presumed dead once its heartbeat is this old.
#:
#: The worker writes one every ``src.worker.main.HEARTBEAT_INTERVAL_SECONDS``,
#: so this is four missed beats — long enough to ride out a slow query or a
#: brief database blip, short enough that an operator is not looking at a
#: reassuring green pill for a process that died minutes ago.
#:
#: ``test_worker_liveness.py`` asserts this stays a multiple of that interval.
#: The two numbers living in different modules is exactly how a threshold ends
#: up shorter than the cadence it measures, which would report every healthy
#: worker as dead.
WORKER_STALE_AFTER_SECONDS = 60.0


async def _build_status(conn, settings: AppSettings) -> SystemStatus:
    """
    Assemble the complete system status.

    Shared by every endpoint in this module rather than reconstructed per
    handler. An earlier version had ``/kill`` and ``/resume`` build their own
    response and omit ``workers``, which defaults to empty — so the moment an
    operator halted trading, the UI also told them no worker was alive. A false
    alarm is worst precisely when someone is already reacting to a problem.
    """
    state = await flags.system_state(conn)
    # Age is computed by the database, not by comparing against the API's own
    # clock: the two processes deploy separately and their clocks can differ by
    # more than the staleness threshold, which would make liveness depend on
    # NTP drift.
    workers = await conn.fetch(
        "SELECT worker_id, last_seen, status, "
        "       EXTRACT(EPOCH FROM (NOW() - last_seen)) AS age_seconds "
        "FROM worker_heartbeats ORDER BY last_seen DESC LIMIT 10"
    )
    return SystemStatus(
        trading_enabled=state.trading_enabled,
        kill_reason=state.reason,
        updated_by=state.updated_by,
        updated_at=state.updated_at.isoformat() if state.updated_at else None,
        live_trading_enabled=settings.live_trading_enabled,
        alpaca_allow_live=settings.alpaca_allow_live,
        broker_configured=settings.has_broker_credentials,
        jobs=await job_repo.counts_by_status(conn),
        # `stale` is reported rather than left for the caller to derive. The
        # stored `status` column is only ever written as 'alive', so a UI
        # rendering it directly showed a green "alive" pill for a worker that
        # died an hour ago — the precise failure the heartbeat exists to catch.
        # A dead worker produces no error anywhere: backtests queue, no mark is
        # written, and both halting limits go inert, all silently.
        workers=[
            {
                "worker_id": w["worker_id"],
                "last_seen": w["last_seen"].isoformat(),
                "status": w["status"],
                "age_seconds": float(w["age_seconds"]),
                "stale": float(w["age_seconds"]) > WORKER_STALE_AFTER_SECONDS,
            }
            for w in workers
        ],
        database_ok=True,
    )


@router.get("/status", response_model=SystemStatus)
async def get_status(
    session: AuthedSession, conn: DbConn, settings: AppSettings
) -> SystemStatus:
    """Everything needed to answer "is it running and is it safe"."""
    return await _build_status(conn, settings)


@router.post("/kill", response_model=SystemStatus)
async def kill(
    body: KillSwitchRequest,
    session: AuthedSession,
    conn: DbConn,
    settings: AppSettings,
) -> SystemStatus:
    """
    Engage the kill switch.

    Sets the durable flag the worker checks before every submission. In a
    deployment with a live broker this endpoint would also call
    ``broker.cancel_all()`` synchronously — the flag stops new orders, the
    cancel deals with the ones already in flight, and neither alone is enough.
    That half lands with the Alpaca adapter; today there is no live venue to
    cancel against, so engaging the flag is the whole of it.
    """
    await flags.engage_kill_switch(conn, body.reason, actor=session.subject)
    return await _build_status(conn, settings)


@router.post("/resume", response_model=SystemStatus)
async def resume(
    body: ReleaseKillSwitchRequest,
    session: AuthedSession,
    conn: DbConn,
    settings: AppSettings,
) -> SystemStatus:
    """
    Re-enable trading. Requires the literal confirmation string.

    The typed confirmation is validated by the request model, so a malformed
    attempt never reaches the flag.
    """
    await flags.release_kill_switch(conn, actor=session.subject, note=body.note)
    return await _build_status(conn, settings)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
#
# Which model the programme is pointed at, how hard it is asked to think, the
# ceiling on a reply, and how often it runs.
#
# These are read here through `src.programme.flags` and `src.programme.models`,
# and that is the whole list — the API may not import `src.programme.client`,
# `.tick`, `.author` or `.main`, which is asserted by
# `tests/unit/test_import_boundaries.py`. Importing any of them to reach the
# catalogue would drag a model SDK into the process that commands the worker,
# which is the one thing the three-process split exists to prevent. The
# catalogue lives in its own module precisely so this endpoint can read it
# without doing that.


async def _configuration(conn: DbConn) -> dict[str, Any]:
    """
    The catalogue, what is stored, and whether the two agree.

    ``stored`` and ``effective`` are reported separately, the same way the
    autonomy ceiling reports ``requested`` and ``effective``. They can differ in
    one direction only: a stored value the runner refuses is reported as stored
    with ``usable`` false, and never smoothed into a working default. A page
    that renders a broken setting as though it were fine describes a programme
    that is about to do nothing and cannot say why.
    """
    raw = {
        key: await flags.get_flag(conn, key)
        for key in programme_flags.SETTING_KEYS
    }
    rows = await conn.fetch(
        "SELECT key, updated_by, updated_at FROM system_flags WHERE key = ANY($1)",
        list(programme_flags.SETTING_KEYS),
    )
    provenance = {
        r["key"]: {
            "updated_by": r["updated_by"],
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        }
        for r in rows
    }

    settings_problem = model_catalogue.settings_problem(
        raw[programme_flags.PROGRAMME_PROVIDER],
        raw[programme_flags.PROGRAMME_MODEL],
        raw[programme_flags.PROGRAMME_EFFORT],
        raw[programme_flags.PROGRAMME_MAX_TOKENS],
    )
    tick_problem = model_catalogue.tick_seconds_problem(
        raw[programme_flags.PROGRAMME_TICK_SECONDS]
    )

    settings = None if settings_problem else await programme_flags.model_settings(conn)
    payload = model_catalogue.catalogue()
    payload["stored"] = {
        "provider": raw[programme_flags.PROGRAMME_PROVIDER],
        "model": raw[programme_flags.PROGRAMME_MODEL],
        "effort": raw[programme_flags.PROGRAMME_EFFORT],
        "max_tokens": raw[programme_flags.PROGRAMME_MAX_TOKENS],
        "tick_seconds": raw[programme_flags.PROGRAMME_TICK_SECONDS],
    }
    payload["provenance"] = provenance
    payload["settings_problem"] = settings_problem
    payload["tick_problem"] = tick_problem
    payload["usable"] = settings_problem is None
    # Whether `output_config.effort` is actually sent. False for a model with no
    # effort parameter, where sending one is a 400 — the stored value is kept
    # for the day the model changes, and reporting it as though it were in
    # effect would be the same lie as rendering an unmeasured metric as zero.
    payload["effort_applies"] = bool(settings and settings.effort_applies)
    # The API process does not hold ANTHROPIC_API_KEY and cannot see whether the
    # programme process does. Saying so beats a "key: absent" pill that is
    # really "this process would not know".
    payload["api_key_visible_here"] = False
    return payload


@router.get("/configuration")
async def get_configuration(
    session: AuthedSession, conn: DbConn
) -> dict[str, Any]:
    """What the programme is pointed at, and everything it could be pointed at."""
    return await _configuration(conn)


@router.post("/configuration")
async def set_configuration(
    body: SystemConfigurationRequest, session: AuthedSession, conn: DbConn
) -> dict[str, Any]:
    """
    Point the programme somewhere else.

    Validated through the same functions the runner uses to read the row back,
    so a value this endpoint accepts is a value the runner will act on. 422 with
    the reason rather than a repaired value: an effort level the chosen model
    does not accept is a 400 at the vendor, and finding that out on the next
    tick, in a log, is worse than finding it out on the form.

    The four model settings are written in one transaction. Half-applied, they
    describe a request nobody chose — a new model with the old model's effort
    level, which is exactly the combination that errors.
    """
    problem = model_catalogue.settings_problem(
        body.provider, body.model, body.effort, body.max_tokens
    )
    if problem is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problem)
    tick_problem = model_catalogue.tick_seconds_problem(body.tick_seconds)
    if tick_problem is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, tick_problem)

    actor = f"operator:{session.subject}"
    before = {
        key: await flags.get_flag(conn, key)
        for key in programme_flags.SETTING_KEYS
    }
    async with conn.transaction():
        await flags.set_flag(
            conn, programme_flags.PROGRAMME_PROVIDER, body.provider, actor
        )
        await flags.set_flag(conn, programme_flags.PROGRAMME_MODEL, body.model, actor)
        await flags.set_flag(conn, programme_flags.PROGRAMME_EFFORT, body.effort, actor)
        await flags.set_flag(
            conn, programme_flags.PROGRAMME_MAX_TOKENS, body.max_tokens, actor
        )
        await flags.set_flag(
            conn, programme_flags.PROGRAMME_TICK_SECONDS, body.tick_seconds, actor
        )
        await flags.record_audit(
            conn,
            actor=actor,
            action="system_configuration_updated",
            entity_type="system",
            detail={"before": before, "after": body.model_dump()},
        )
    logger.warning(
        "Programme configuration set by %s: provider=%s model=%s effort=%s "
        "max_tokens=%s tick=%ss",
        actor,
        body.provider,
        body.model,
        body.effort,
        body.max_tokens,
        body.tick_seconds,
    )
    return await _configuration(conn)


@router.api_route("/drain", methods=["GET", "POST"])
async def drain(
    request: Request,
    conn: DbConn,
    settings: AppSettings,
) -> dict:
    """
    Run queued research jobs in this process. For hosts with no worker.

    Answers to GET as well as POST, which is not an endorsement of mutating
    GETs — Vercel Cron issues a GET and gives no way to change that, and an
    endpoint a scheduler cannot call is not a scheduler.

    Disabled unless ``SERVERLESS_DRAIN_ENABLED`` is set, and it should stay
    disabled anywhere a worker exists: running a backtest inside a request
    handler on a long-lived server stalls every other request on that event
    loop, the kill switch included. See ``src/api/drain.py``.

    Authenticated by an operator session **or** ``CRON_SECRET`` as a bearer
    token, so a platform scheduler can call it unattended. It is never
    anonymous: it is the one endpoint that consumes real CPU on demand, which
    makes it the one worth rate-limiting by having a credential at all.
    """
    if not settings.serverless_drain_enabled:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "job draining is not enabled on this deployment; a worker process "
            "runs jobs here",
        )

    actor = _drain_caller(request, settings)
    result = await drain_once(conn, worker_id=f"drain:{actor}")
    if result["ran"]:
        logger.info("Drain by %s ran %d job(s)", actor, result["ran"])
    return result


@router.post("/migrate")
async def migrate_database(
    request: Request,
    conn: DbConn,
    settings: AppSettings,
) -> dict:
    """
    Apply pending migrations through the API.

    Exists for hosts with no shell. `python -m src.db.migrate_cli` assumes
    somewhere to run it, and a serverless deployment has nowhere: the
    database's own console is the only alternative, and pasting DDL into a
    web form is how schemas drift. This endpoint runs the same runner the CLI
    does — checksum verification and transactional application included — so
    "the deployed schema" has exactly one definition.

    Safe to call repeatedly: the runner is idempotent, and a concurrent
    duplicate loses on the schema_migrations primary key and rolls back.

    Same authentication as the drain — an operator session or CRON_SECRET —
    and POST only, because unlike the drain no platform scheduler needs to
    call it. Login works without a database, so the operator can mint the
    session this needs on a deployment whose schema does not exist yet;
    that ordering is the whole point.
    """
    actor = _drain_caller(request, settings)
    try:
        applied = await migrate(conn)
    except MigrationError as exc:
        # 409, not 500: the state of the world refuses the request — an
        # edited applied migration or a malformed set — and retrying without
        # changing the repository will refuse identically.
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    version = await current_version(conn)
    logger.info(
        "Migrate by %s applied %d migration(s); at version %d",
        actor,
        len(applied),
        version,
    )
    return {
        "applied": [str(m) for m in applied],
        "current_version": version,
    }


def _drain_caller(request: Request, settings: AppSettings) -> str:
    """
    Identify the caller, or refuse.

    Tries the cron secret first because that is the unattended path; falls back
    to a normal session so an operator can force a drain from the UI without
    knowing the secret.
    """
    header = request.headers.get("authorization", "")
    if settings.cron_secret and header.lower().startswith("bearer "):
        presented = header[7:].strip()
        # Constant-time: this is a fixed secret compared on every scheduled
        # call, which is exactly the shape a timing oracle likes.
        if constant_time_equals(presented, settings.cron_secret):
            return "cron"

    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        try:
            return verify_session(settings.session_secret, cookie).subject
        except AuthError:
            pass
        except InsecureSecretError as exc:
            # Reached only when the cron secret did not already authorise this
            # call, so there is no other way in. 503 rather than the 401 below:
            # the cookie was never checked, and saying "unauthorised" would
            # blame a caller who may well be entitled.
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)
            ) from exc

    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "this endpoint requires an operator session or the CRON_SECRET "
        "bearer token",
    )


@router.get("/jobs", response_model=list[JobSummary])
async def list_jobs(
    session: AuthedSession,
    conn: DbConn,
    job_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[JobSummary]:
    rows = await job_repo.list_jobs(conn, job_status, limit)
    return [
        JobSummary(
            id=str(r["id"]),
            kind=r["kind"],
            status=r["status"],
            attempts=r["attempts"],
            max_attempts=r["max_attempts"],
            error=r["error"],
            created_at=r["created_at"].isoformat() if r["created_at"] else None,
            finished_at=r["finished_at"].isoformat() if r["finished_at"] else None,
        )
        for r in rows
    ]


@router.get("/audit")
async def audit(
    session: AuthedSession, conn: DbConn, limit: int = Query(default=50, ge=1, le=200)
) -> list[dict]:
    rows = await conn.fetch(
        "SELECT actor, action, entity_type, entity_id, detail, at "
        "FROM audit_log ORDER BY at DESC LIMIT $1",
        limit,
    )
    return [
        {
            "actor": r["actor"],
            "action": r["action"],
            "entity_type": r["entity_type"],
            "entity_id": r["entity_id"],
            "detail": r["detail"],
            "at": r["at"].isoformat(),
        }
        for r in rows
    ]
