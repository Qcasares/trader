"""
jev_forward.py
--------------
The forward clock: ``decision.regime`` asked about each session before its
decision cutoff, and one answer recorded as one frozen signal. Collected and
not consumed: nothing reads a signal but the harness until phase F, and the
Rule 5 amendment that would let one reach an order is proposed, not in force.

Runner-only: it asks through ``jev_lane``, which holds the client.

Why going forward, and only going forward
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Jev holds world knowledge with no disclosed cutoff (docs/08, fact 6), so an
answer about a past session may be a memory of what followed it rather than a
judgement of what it was shown. Only answers recorded before the decision they
could have served are evidence, so this job asks nothing once the database's
clock — the one that stamps ``available_at`` — has reached the session's
cutoff, and writes nothing for a session it did not answer: **it never
backfills**. A call begun before the cutoff whose row commits after it is
recorded, and the database, not this module, marks it backfilled.

What each attempt does
~~~~~~~~~~~~~~~~~~~~~~
In order; the first that applies decides.

==  =========================================================  ==================
#   Condition                                                  Outcome
==  =========================================================  ==================
0   The payload's session is not an NYSE session, or its set   fail, no retry
    is not the forward clock's
0   Its version is not the registered set's (planned before a  complete,
    bump)                                                      ``superseded``
1   A signal is already recorded for the session               complete, nothing
                                                               asked
2   The database's clock has reached the cutoff                fail, no retry:
                                                               ``expired``
3   The decisions area is off                                  fail, retry
4   A sleeve is the live ingest's and ``ingest_bars:{S}`` has   fail, retry
    not succeeded; or it is nobody's now, an attempt of the
    ingest did not succeed, and the reference job for ``S``
    did not re-base it (docs/08 open item 40)
5   No bars, or no regime state (:func:`regime_state_problem`)  fail, retry
6   The ask recorded a response, ``ok`` or ``invalid``          record the signal,
                                                               complete
7   Anything else the ask came to                              as
                                                               ``job_errors.ask_verdict``
==  =========================================================  ==================

Steps 3 to 5 are retried because each can change before the cutoff — an
operator's switch, a late ingest, a vendor's late bar — and the queue's
backoff (``attempts × 10 s``) with ``jev_plan.REGIME_ATTEMPTS`` attempts outlasts
the ten minutes to the cutoff, so the attempt after it fails at step 2 with the
last reason it met. That error, on the job row, is the durable record of why
the session is absent, which ``python -m src.programme.jev_eval forward``
reads; no ``missing`` row is written, because a first row is final and would
bar the measurement a bar landing two minutes later made possible.

A live-owned sleeve waits for the live ingest (open item 40). A sleeve an
enabled operator deployment trades is the live ingest's, which refetches its
whole stored span on one adjustment basis only when ``ingest_bars:{S}``
succeeds; until then its rows before the ten-day window may be on an older
basis, which the reference job, leaving the sleeve to the live ingest, cannot
mend. So the session is not measured before that job succeeds, exactly as
though its close were missing. Where the traded universe cannot be read, every
sleeve is taken to be the live ingest's: failing closed waits for a job that
is due anyway. Who owns a sleeve now is not who owned it when the ingest ran:
a sleeve whose deployment was disabled after an attempt of the ingest failed
may still carry that attempt's window on a newer basis than the rows before
it, which neither a later attempt, no longer fetching it, nor the reference
job, run while the live ingest owned it, has mended. So once an attempt of
``ingest_bars:{S}`` has not succeeded, a sleeve nobody trades now is read only
if the reference job for ``S`` re-based it whole.

One ask per attempt, through the module attribute ``jev_lane.ask`` with every
argument named: the SDK suite hands the road a transport by replacing that
attribute, and nothing here may pass one itself. So a session is asked at
most once per attempt, not once in all: an attempt whose call got no response
(``job_errors.ask_verdict``: no connection, a timeout, a rate limit or a vendor
fault) is retried before the cutoff, and asks again, since an ``error`` row is
not an answer to replay. The queue's backoff fits up to eleven attempts in the
ten minutes to the cutoff, so a vendor timing out every call is called up to
eleven times for the session, each call billed at most twice by the client's
own retry, and the lane's share of the day's budget bounds them all. An
invalid response is recorded as an ``invalid`` signal and not asked again: it
is what an allocator would have seen at the cutoff, and asking again would
buy a second answer, not check the first. Two sessions with one state share
one canonical answer and one call: the second is a replay. Whatever the
attempts, one answer is recorded a session.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

import asyncpg

from src.core import calendar
from src.data.reference import REFERENCE_SLEEVES, REFERENCE_SOURCE
from src.programme import (
    flags,
    jev_clock,
    jev_features,
    jev_lane,
    jev_prereg,
    jev_questions,
    jev_repo,
    repo,
)
from src.programme.job_errors import JobFailedError, ask_verdict

logger = logging.getLogger(__name__)

#: The set the forward clock asks, and its question.
REGIME_SET_NAME = "decision.regime"
REGIME_QUESTION = "regime"

#: How much of another job's error is quoted in this one's.
QUOTED_ERROR_CHARS = 300


async def collect(
    conn: asyncpg.Connection, payload: dict[str, Any], api_key: str | None
) -> dict[str, Any]:
    """
    The ``jev_regime`` job: one session's regime, at most one call an attempt
    and its answer recorded at most once. An attempt whose call got no
    response is retried before the cutoff, and asks again, since nothing was
    recorded to replay. See the module docstring for every outcome.

    ``payload`` is ``{"session": "YYYY-MM-DD", "set": "decision.regime",
    "version": 1}``. The result holds labels, counts, ids and the analysis
    plan in force — its version and hash, which the forward report scores the
    answer under — never a state or a price.
    """
    session = _session(payload)
    question_set = jev_questions.REGISTRY.get(REGIME_SET_NAME)
    if payload.get("set") != REGIME_SET_NAME or question_set is None:
        raise JobFailedError(
            f"a regime job asks {REGIME_SET_NAME}, and this one names "
            f"{payload.get('set')!r}",
            retry=False,
        )
    signal = jev_clock.regime_signal(question_set, REGIME_QUESTION)
    symbol = jev_clock.sleeve_symbol(REFERENCE_SLEEVES)
    # The analysis plan in force as the session is asked: the forward report
    # scores an answer only under the plan it was first recorded under.
    result: dict[str, Any] = {
        "session": session.isoformat(),
        "signal": signal,
        "plan_version": jev_prereg.PLAN_VERSION,
        "plan_hash": jev_prereg.plan_hash(),
    }

    version = payload.get("version")
    if version != question_set.version:
        logger.info(
            "Regime job for %s names v%s; v%s is registered, so it is superseded",
            session,
            version,
            question_set.version,
        )
        return {**result, "status": "superseded", "version": version}

    if await jev_repo.signal_exists(
        conn, signal=signal, symbol=symbol, session=session
    ):
        return {**result, "status": "recorded_before"}

    cutoff = jev_clock.decision_cutoff(session)
    now = await jev_clock.database_now(conn)
    if now >= cutoff:
        raise JobFailedError(
            await _expired(conn, question_set, session, cutoff, now), retry=False
        )

    if not await flags.jev_area_enabled(conn, "decisions"):
        raise JobFailedError(
            f"the decisions area is off, so {session.isoformat()} waits for it "
            f"until its cutoff at {_utc(cutoff)}",
            retry=True,
        )

    waiting = await _live_ingest_problem(conn, session)
    if waiting is not None:
        raise JobFailedError(waiting, retry=True)

    panel = await jev_clock.load_regime_panel(conn, session)
    if panel is None:
        raise JobFailedError(
            f"no reference bar is stored under {REFERENCE_SOURCE} up to "
            f"{session.isoformat()}; retried until its cutoff at {_utc(cutoff)}",
            retry=True,
        )
    state = jev_features.regime_state(panel, session, REFERENCE_SLEEVES)
    if state is None:
        problem = jev_features.regime_state_problem(panel, session, REFERENCE_SLEEVES)
        raise JobFailedError(
            f"no regime state for {session.isoformat()}: {problem}; retried until "
            f"its cutoff at {_utc(cutoff)}",
            retry=True,
        )

    # Read again at the last moment: nothing is asked once the cutoff has been
    # reached, however long the bars took to load.
    now = await jev_clock.database_now(conn)
    if now >= cutoff:
        raise JobFailedError(
            await _expired(conn, question_set, session, cutoff, now), retry=False
        )
    asked = await jev_lane.ask(
        conn,
        question_set=question_set,
        state=state,
        subject_type="session",
        subject_id=session.isoformat(),
        as_of=jev_clock.regime_as_of(session),
        api_key=api_key,
        probe=False,
    )
    if asked.status in ("ok", "invalid"):
        record = await jev_lane.record_signal(
            conn,
            question_set=question_set,
            question_key=REGIME_QUESTION,
            result=asked,
            signal=signal,
            symbol=symbol,
            session=session,
            decision_cutoff=cutoff,
        )
        return {
            **result,
            "status": record.status,
            "value": record.value,
            "backfilled": record.backfilled,
            "request_id": asked.request_row_id,
            "replayed": asked.replayed,
            "inserted": record.inserted,
        }
    error, retry = ask_verdict(asked)
    assert error is not None  # ok is handled above
    raise JobFailedError(error, retry=retry)


def _session(payload: dict[str, Any]) -> date:
    """The payload's session, which must be an NYSE session the calendar holds."""
    raw = payload.get("session")
    try:
        session = date.fromisoformat(str(raw))
    except ValueError:
        raise JobFailedError(
            f"a regime job names its session as YYYY-MM-DD, got {raw!r}", retry=False
        ) from None
    first, last = calendar.bounds()
    if not first <= session <= last or not calendar.is_session(session):
        raise JobFailedError(
            f"{session.isoformat()} is not an NYSE session the calendar holds",
            retry=False,
        )
    return session


async def _live_ingest_problem(conn: asyncpg.Connection, session: date) -> str | None:
    """
    Why a sleeve the live ingest owns, or owned, cannot be read for
    ``session`` yet, or ``None``.

    A sleeve is the live ingest's while an enabled operator deployment trades
    it (``repo.traded_universe``, the worker's own rule). Its stored span is on
    one basis only once ``ingest_bars:{S}`` has succeeded, so until then the
    session is treated as though its close were missing.

    Owned now is not enough to ask, because it is not when the ingest ran. An
    attempt of ``ingest_bars:{S}`` that failed its span refetch while a
    deployment traded a sleeve still wrote the ten-day window for it, leaving
    the rows before on an older basis; if the deployment is disabled before
    this job runs, the sleeve reads as nobody's, a later attempt that
    succeeds no longer fetches it, and the reference job for ``S``, which ran
    while the live ingest owned it, left it alone. So once any attempt of the
    ingest has failed, or is still running, a sleeve no deployment trades
    now is read only if the reference job for ``S`` re-based it whole — its
    result names it among those it upserted — and otherwise waits, like a
    missing close, until the cutoff (docs/08 open item 40).
    """
    traded = await repo.traded_universe(conn)
    ingest_key = jev_clock.ingest_job_key(session)
    reference_key = jev_clock.reference_job_key(session)
    jobs = await jev_repo.job_outcomes(conn, [ingest_key, reference_key])
    ingest = jobs.get(ingest_key)
    cutoff = _utc(jev_clock.decision_cutoff(session))
    if traded.unreadable:
        owned = list(REFERENCE_SLEEVES.items())
        whose = (
            f"deployment(s) {', '.join(traded.unreadable)} cannot be built from "
            "their stored parameters, so any sleeve may be the live ingest's"
        )
    else:
        owned = [
            (sleeve, symbol)
            for sleeve, symbol in REFERENCE_SLEEVES.items()
            if symbol in traded.symbols
        ]
        whose = "an enabled deployment trades it"
    if owned and not (ingest is not None and ingest["status"] == "succeeded"):
        named = ", ".join(f"{sleeve} ({symbol})" for sleeve, symbol in owned)
        return (
            f"{named}: the live ingest's, since {whose}, and {ingest_key} "
            f"{_job_state(ingest)}. A live-owned sleeve's history is on one "
            "adjustment basis only once that job has succeeded, so "
            f"{session.isoformat()} waits for it until its cutoff at {cutoff}"
        )
    if not _an_attempt_failed(ingest):
        return None
    rebased = _upserted(jobs.get(reference_key))
    suspect = [
        (sleeve, symbol)
        for sleeve, symbol in REFERENCE_SLEEVES.items()
        if (sleeve, symbol) not in owned and symbol not in rebased
    ]
    if not suspect:
        return None
    named = ", ".join(f"{sleeve} ({symbol})" for sleeve, symbol in suspect)
    return (
        f"{named}: no enabled deployment trades it now, but {ingest_key} "
        f"{_job_state(ingest)} after an attempt that did not succeed, which may "
        "have left the rows before its ten-day window on an older adjustment "
        f"basis while a deployment traded it; and {reference_key} "
        f"{_reference_state(jobs.get(reference_key))}, so "
        f"{session.isoformat()} waits until its cutoff at {cutoff}"
    )


def _job_state(job: dict[str, Any] | None) -> str:
    """A job's state, its error quoted, for a wait's reason."""
    if job is None:
        return "has not been planned"
    state = f"is {job['status']}"
    if job.get("error"):
        state += f" ({_quoted(job['error'])})"
    return state


def _an_attempt_failed(ingest: dict[str, Any] | None) -> bool:
    """
    Whether an attempt of the live ingest has failed, or is still running:
    anything but no attempt at all and a success on the first.
    """
    if ingest is None:
        return False
    attempts = int(ingest.get("attempts") or 0)
    if attempts == 0:
        return False
    return not (ingest["status"] == "succeeded" and attempts == 1)


def _upserted(reference: dict[str, Any] | None) -> frozenset[str]:
    """The symbols a succeeded reference job re-based whole, rows and all."""
    if reference is None or reference["status"] != "succeeded":
        return frozenset()
    result = reference.get("result")
    upserted = result.get("upserted") if isinstance(result, dict) else None
    if not isinstance(upserted, dict):
        return frozenset()
    return frozenset(
        symbol
        for symbol, rows in upserted.items()
        if isinstance(rows, int) and rows > 0
    )


def _reference_state(reference: dict[str, Any] | None) -> str:
    """What the reference job did, or did not do, for a wait's reason."""
    if reference is None:
        return "has not been planned"
    if reference["status"] != "succeeded":
        return f"{_job_state(reference)} and has re-based nothing"
    return "succeeded without re-basing it whole"


async def _expired(
    conn: asyncpg.Connection,
    question_set: jev_questions.QuestionSet,
    session: date,
    cutoff: datetime,
    now: datetime,
) -> str:
    """
    The error of a job that reached the cutoff unmeasured: when, and the last
    reason an attempt before it met, read from this job's own row, since that
    reason — not the clock — is why the session is absent.
    """
    key = jev_clock.regime_job_key(question_set, session)
    job = (await jev_repo.job_outcomes(conn, [key])).get(key)
    said = (
        f"expired: the forward clock missed {session.isoformat()}; its cutoff was "
        f"{_utc(cutoff)} and the database's clock read "
        f"{now.astimezone(UTC):%H:%M:%S} UTC, so nothing is asked about it and "
        "no row is written."
    )
    # A claim counts the attempt and leaves the last error in place, so this
    # job's row still holds what the attempt before this one met.
    if job is not None and job.get("attempts", 0) > 1 and job.get("error"):
        return f"{said} Before the cutoff: {_quoted(job['error'])}"
    return f"{said} No earlier attempt is recorded under {key}."


def _utc(moment: datetime) -> str:
    return f"{moment.astimezone(UTC):%Y-%m-%d %H:%M} UTC"


def _quoted(error: str) -> str:
    text = " ".join(str(error).split())
    if len(text) <= QUOTED_ERROR_CHARS:
        return text
    return text[: QUOTED_ERROR_CHARS - 1] + "…"


__all__ = [
    "REGIME_QUESTION",
    "REGIME_SET_NAME",
    "collect",
]
