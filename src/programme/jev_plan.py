"""
jev_plan.py
-----------
The planner: what Jev work is due, put in the queue, and nothing else.

Runner-only. It runs in the programme's Jev loop, before each drain, at most
once a minute (``main.JEV_PLAN_SECONDS``), and all it does is enqueue: every
job's handler checks every one of its own preconditions again when it runs,
because a planner is only a scheduler, and a job planned while a switch was on
may run after it went off.

Dark unless everything says otherwise
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
:func:`plan` plans nothing unless ``programme_enabled`` and ``jev_enabled`` are
on, ``jev_model`` is a usable pin and a TypeSafe key exists, each read through
its own fail-closed reader, none derived from another; and each rule also needs
its own area. Without a key it plans nothing at all, the worker's reference
bars included, since nothing downstream could use them and a ``no_key`` failure
a day would pile up saying so. Seeded as migration 0012 seeds the switches, it
plans nothing (``tests/integration/test_jev_dark.py``).

The rules
~~~~~~~~~
Each with the area it needs, what it enqueues, when, and under which key:

* **The daily probe** — the master switch alone; ``jev_probe``, now, under
  ``jev_probe:{UTC date}``.
* **The reference bars** — decisions; the worker's ``ingest_reference_bars``,
  at the close plus 45 minutes, under ``ingest_reference_bars:{S}``.
* **The regime** — decisions; ``jev_regime``, at the close plus 50 minutes,
  under ``jev_regime:{set}@{version}:{S}``.
* **The re-asks** — the set's own area; ``jev_reask``, at least 24 hours after
  the canonical answer, under ``jev_reask:{request id}``.

The daily probe proves each day, on a fixed state whose answer is known, that
the key, the pin and the validator still work, and gives a daily series of the
pinned model's probability on it: it closes open item 18, under which nothing
enqueued the probe at all. The sessions ``S`` are today's New York session while
its cutoff is ahead and the next one (``jev_clock.sessions_to_plan``), never a
past one, so a session missed is absent rather than backfilled. The re-asks are
the pre-registered sample of the previous UTC day's canonical requests
(``jev_prereg.reask_sample``), less any whose set has been reworded since, whose
model is not the pin, or whose text has been quarantined.

Spend
~~~~~
A job that makes a call is enqueued only while its lane's share of the day's
budget (``jev_catalogue.LANE_BUDGET_PERCENT``) has a call left once the calls
already made today and the jobs already waiting are counted. The reference job
makes no call. Every enqueue names its kind as a literal, so
``tests/unit/test_job_ownership.py`` can hold each to exactly one owner, and the
reference job's priority by name (``REFERENCE_PRIORITY``), which a test holds
below every kind on the live path, so the worker claims the live ingest first.

How many attempts
~~~~~~~~~~~~~~~~~
The queue backs a failed job off by ``attempts × 10 s`` (``job_repo.fail``).
The reference job fails while a sleeve lacks its session's close, so that the
worker retries it, and a vendor late by minutes needs its retries to reach the
cutoff, fifteen minutes after its first chance: :data:`REFERENCE_ATTEMPTS` is
the fewest attempts whose waits add up to that, 14, where the design's 3
spanned thirty seconds (docs/08 open item 39).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg

from src.data.reference import REFERENCE_PRIORITY
from src.db.repos import jobs as job_repo
from src.programme import (
    flags,
    jev_catalogue,
    jev_clock,
    jev_prereg,
    jev_questions,
    jev_repo,
)

logger = logging.getLogger(__name__)

#: The daily probe: below the forward clock, above every research ask.
PROBE_PRIORITY = 40
PROBE_ATTEMPTS = 3

#: A re-ask waits behind everything: it measures, and nothing waits on it.
REASK_PRIORITY = -10
REASK_ATTEMPTS = 3

#: The forward clock's job: above the probe and every research ask, since a
#: session missed is missed for good; and with the queue's backoff, 20
#: attempts span about 32 minutes, three times the ten from collection to the
#: cutoff, so attempts never run out first and the one after the cutoff fails
#: as ``expired`` with the last reason it met (``jev_forward``).
REGIME_PRIORITY = 50
REGIME_ATTEMPTS = 20

#: What ``job_repo.fail`` waits between attempts, per attempt so far. A test
#: reads the queue's SQL to hold this to it.
RETRY_BACKOFF_STEP = timedelta(seconds=10)


def attempts_spanning(span: timedelta) -> int:
    """
    The fewest attempts whose waits between them add up to at least ``span``:
    ``n`` attempts wait ``10 s × (1 + 2 + … + (n − 1))``, ``5·n·(n − 1)`` seconds.
    """
    if span <= timedelta(0):
        return 1
    attempts = 1
    while RETRY_BACKOFF_STEP * (attempts * (attempts - 1) // 2) < span:
        attempts += 1
    return attempts


#: The reference job's attempts: enough for its retries to reach the cutoff
#: from the minute the bars settle (docs/08 open item 39).
REFERENCE_ATTEMPTS = attempts_spanning(
    jev_clock.DECISION_AFTER_CLOSE - jev_clock.REFERENCE_AFTER_CLOSE
)

#: The job kinds that spend each lane's share, for counting what is already
#: waiting: a probe of any set is recorded in the probe lane.
LANE_KINDS: Mapping[str, tuple[str, ...]] = {
    "probe": ("jev_probe", "jev_reask"),
    "decision": ("jev_regime",),
}

#: The forward clock's set.
REGIME_SET_NAME = "decision.regime"


class _Room:
    """
    Calls each lane may still be planned today: its share of the budget, less
    the calls it made since UTC midnight, less the jobs already waiting to make
    one. Read once a pass and counted down as jobs are planned.
    """

    def __init__(self, conn: asyncpg.Connection, budget: int) -> None:
        self._conn = conn
        self._budget = budget
        self._left: dict[str, int] = {}

    async def left(self, lane: str) -> int:
        if lane not in self._left:
            share = jev_catalogue.lane_budget(self._budget, lane)
            spent = await jev_repo.requests_today(self._conn, lane)
            waiting = await jev_repo.pending_jobs(self._conn, LANE_KINDS[lane])
            self._left[lane] = share - spent - waiting
        return self._left[lane]

    def take(self, lane: str) -> None:
        self._left[lane] -= 1


async def plan(
    conn: asyncpg.Connection, *, now: datetime, key_available: bool
) -> list[str]:
    """
    Enqueue whatever Jev work is due at ``now``, and return the keys of the
    jobs this pass added; a job already in the queue under its key is not
    added again, whatever its status (``jobs.dedupe_key`` is unique across
    every status). Plans nothing unless every switch, the pin and a key allow
    it (see the module docstring).
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if not key_available:
        return []
    if not await flags.programme_enabled(conn):
        return []
    if not await flags.jev_enabled(conn):
        return []
    model = await flags.jev_model(conn)
    if model is None:
        return []

    room = _Room(conn, await flags.jev_daily_request_budget(conn))
    planned = await _plan_probe(conn, now, room)
    if await flags.jev_area_enabled(conn, "decisions"):
        planned += await _plan_clock(conn, now, room)
    planned += await _plan_reasks(conn, now, model, room)
    if planned:
        logger.info("Jev planner queued %s", ", ".join(planned))
    return planned


async def _plan_probe(
    conn: asyncpg.Connection, now: datetime, room: _Room
) -> list[str]:
    """One connectivity probe a UTC day, on the master switch alone."""
    key = f"jev_probe:{now.astimezone(UTC).date().isoformat()}"
    if await _queued(conn, key) or await room.left("probe") <= 0:
        return []
    added = await job_repo.enqueue(
        conn,
        "jev_probe",
        {},
        priority=PROBE_PRIORITY,
        max_attempts=PROBE_ATTEMPTS,
        scheduled_for=now,
        dedupe_key=key,
    )
    room.take("probe")
    return [key] if added is not None else []


async def _plan_clock(
    conn: asyncpg.Connection, now: datetime, room: _Room
) -> list[str]:
    """
    The worker's reference bars and the regime job, for each session to plan.

    The reference job makes no call, so no share is needed for it; it is the
    worker's, claimed behind every live-path kind at the same minute.
    """
    question_set = jev_questions.REGISTRY.get(REGIME_SET_NAME)
    planned: list[str] = []
    for session in jev_clock.sessions_to_plan(now):
        reference = jev_clock.reference_job_key(session)
        added = await job_repo.enqueue(
            conn,
            "ingest_reference_bars",
            {"session": session.isoformat()},
            priority=REFERENCE_PRIORITY,
            max_attempts=REFERENCE_ATTEMPTS,
            scheduled_for=jev_clock.reference_at(session),
            dedupe_key=reference,
        )
        if added is not None:
            planned.append(reference)
        if question_set is None:
            continue
        regime = jev_clock.regime_job_key(question_set, session)
        if await _queued(conn, regime) or await room.left("decision") <= 0:
            continue
        added = await job_repo.enqueue(
            conn,
            "jev_regime",
            {
                "session": session.isoformat(),
                "set": question_set.name,
                "version": question_set.version,
            },
            priority=REGIME_PRIORITY,
            max_attempts=REGIME_ATTEMPTS,
            scheduled_for=jev_clock.collect_at(session),
            dedupe_key=regime,
        )
        room.take("decision")
        if added is not None:
            planned.append(regime)
    return planned


async def _plan_reasks(
    conn: asyncpg.Connection, now: datetime, model: str, room: _Room
) -> list[str]:
    """
    The pre-registered re-ask sample of the previous UTC day's answers, and
    never more than ``jev_prereg.REASKS_PER_DAY`` of them in the UTC day.

    The cap is the day's, not a pass's: a re-ask already queued for one of
    those answers, by any earlier pass, counts against it. Counted per pass,
    a change of eligibility during the day — an area switched on, a pin
    changed — would draw a second sample from answers the first left out.
    Only this planner queues a re-ask, and only on the day after its answer,
    so the jobs of the previous day's answers are exactly today's re-asks.
    """
    today = datetime.combine(now.astimezone(UTC).date(), datetime.min.time(), UTC)
    rows = await jev_repo.canonical_requests_between(
        conn, start=today - timedelta(days=1), end=today
    )
    keys = [f"jev_reask:{row['id']}" for row in rows]
    queued = await jev_repo.job_outcomes(conn, keys) if keys else {}
    left_today = jev_prereg.REASKS_PER_DAY - len(queued)
    if left_today <= 0:
        return []
    eligible = [
        row
        for row, key in zip(rows, keys, strict=True)
        if key not in queued and await _reaskable(conn, row, model)
    ]
    planned: list[str] = []
    for stratum, row in jev_prereg.reask_sample(eligible, limit=left_today):
        key = f"jev_reask:{row['id']}"
        if await room.left("probe") <= 0:
            break
        # The handler reads the request id alone; the plan and the stratum
        # the request was sampled under are for the harness, which counts a
        # pair only in its own stratum and only under the plan that drew it.
        added = await job_repo.enqueue(
            conn,
            "jev_reask",
            {
                "request_id": row["id"],
                "stratum": stratum,
                "plan_version": jev_prereg.PLAN_VERSION,
                "plan_hash": jev_prereg.plan_hash(),
            },
            priority=REASK_PRIORITY,
            max_attempts=REASK_ATTEMPTS,
            scheduled_for=row["available_at"] + jev_prereg.REASK_AFTER,
            dedupe_key=key,
        )
        room.take("probe")
        if added is not None:
            planned.append(key)
    return planned


async def _reaskable(
    conn: asyncpg.Connection, row: Mapping[str, Any], model: str
) -> bool:
    """
    Whether a canonical request may be re-asked as itself: its set registered
    under the pack that asked it, the pin the model that answered, its set's
    area on, and, for web text, the text not since quarantined.
    """
    question_set = jev_questions.REGISTRY.get(row["question_set"])
    if question_set is None or question_set.pack_hash != row["pack_hash"]:
        return False
    if row["model_requested"] != model:
        return False
    area = jev_catalogue.LANE_AREA.get(question_set.lane)
    if area is None or not await flags.jev_area_enabled(conn, area):
        return False
    if row["subject_type"] == "web_excerpt":
        return await jev_repo.content_quarantined(conn, row["subject_id"]) is None
    return True


async def _queued(conn: asyncpg.Connection, key: str) -> bool:
    """Whether a job is in the queue under ``key``, in any status."""
    return key in await jev_repo.job_outcomes(conn, [key])


__all__ = [
    "LANE_KINDS",
    "PROBE_ATTEMPTS",
    "PROBE_PRIORITY",
    "REASK_ATTEMPTS",
    "REASK_PRIORITY",
    "REFERENCE_ATTEMPTS",
    "REGIME_ATTEMPTS",
    "REGIME_PRIORITY",
    "RETRY_BACKOFF_STEP",
    "attempts_spanning",
    "plan",
]
