"""
jev_plan.py
-----------
The planner: what Jev work is due, put in the queue, and nothing else.

Runner-only. It runs in the programme's Jev loop, before each drain, at most
once a minute (``main.JEV_PLAN_SECONDS``), and all it does is enqueue: each of
the programme's handlers reads again, when it runs, what the planner read for
it — the road reads the switches, the pin and the key on every ask, and the
web ingest, which asks nothing, reads the programme's switch, its area and
the pin itself, and ``main``'s wrapper whether a key is set — because a
planner is only a scheduler, and a job planned while they held may run after
one went. The worker's reference job reads no switch: what it checks is its
session's window, by the database's clock, and it stores prices only the
forward clock reads.

Dark unless everything says otherwise
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
:func:`plan` plans nothing unless ``programme_enabled`` and ``jev_enabled`` are
on, ``jev_model`` is a usable pin and a TypeSafe key exists, each read through
its own fail-closed reader, none derived from another; and each rule also needs
its own area. Without a key it plans nothing at all, the worker's reference
bars and the web ingest included, though neither calls Jev: nothing downstream
could use them, a ``no_key`` failure a day would pile up saying so, and a page
fetched for a lane that cannot ask about it is a fetch for nothing (design
R28). Seeded as migration 0012 seeds the switches, it plans nothing
(``tests/integration/test_jev_dark.py``).

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
* **The web ingest** (phase C6) — research; ``jev_web_ingest``, now, once a
  UTC day for each source on the allow-list, under
  ``jev_web_ingest:{source}:{UTC date}``, with the payload ``{"source":
  <name>}`` and nothing else: the page fetched is the allow-list's, never one a
  payload names.
* **The asks** (phases C7 and C8) — each set its lane's area; ``jev_ask``,
  now, under ``jev_ask:{set}@{version}:{subject_type}:{subject_id}:{UTC
  date}`` (``jev_repo.ask_job_key``), at most :data:`ASKS_PER_PASS` of a set
  a pass: the injection screen (25) and the card check (10) behind
  guardrails, the catalogue (25) and the hypothesis categories (10) behind
  research. The payload names the set, its version, the subject, the row its
  text is read from and the analysis plans in force, which the handler asks
  under and no others, never the text; a set with no plan is planned nothing.
  The subjects are ``jev_repo``'s reads: stored content the screen has not
  answered, and first its repairs, content still in use that a vendor
  content block or the screen's own ``true`` is on record for; content the
  screen cleared, for the catalogue, and never any other; model-written
  hypothesis titles within their cap, newest first. Each read leaves out a
  subject whose job is waiting or was planned today, and retires one after
  three failed calls — but for the screen's repairs, returned until their
  content is quarantined whatever its answers and failed calls; the day in
  the key lets a later day's plan ask again about a subject whose job failed.
  Nothing that would call is planned while an authentication failure
  recorded today holds every lane, nor of a set the vendor refused with a
  422 at its version under the pin; the screen's repairs, which make no
  call, are planned under either.

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
already made today and the jobs already waiting are counted: the ``jev_ask``
jobs of a lane's sets among them, from phase C7. The reference job, the web
ingest and the screen's repairs — its asks about content a block, or its own
``true``, is on record for — make no call. Every enqueue names its kind as a
literal, so
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
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from types import MappingProxyType
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
    web_sources,
)

logger = logging.getLogger(__name__)

#: The daily probe: below the forward clock, above every research ask.
PROBE_PRIORITY = 40
PROBE_ATTEMPTS = 3

#: A re-ask waits behind everything: it measures, and nothing waits on it.
REASK_PRIORITY = -10
REASK_ATTEMPTS = 3

#: The daily web ingest: behind the forward clock and the probe, ahead of the
#: re-asks. It makes no call, so it takes nothing from a lane's share; three
#: attempts, since only a failure to store is retried, and a failed fetch or a
#: refused page waits for the next day's job.
INGEST_PRIORITY = 10
INGEST_ATTEMPTS = 3

#: The area the web ingest needs.
INGEST_AREA = "research"

#: The ``jev_ask`` jobs (phases C7 and C8): behind the forward clock, the
#: probe and the web ingest, ahead of the re-asks; three attempts, the failed
#: calls that retire a subject (``jev_repo.MAX_FAILED_CALLS``).
ASK_PRIORITY = 0
ASK_ATTEMPTS = 3

#: Every set a ``jev_ask`` job asks, with the most one pass may plan of it
#: (design C7 and C8). Each is planned behind its own lane's area, within its
#: lane's share: the injection screen and the card check the guardrails',
#: the catalogue and the hypothesis categories the research area's.
ASKS_PER_PASS: Mapping[str, int] = MappingProxyType(
    {
        "guardrail.injection": 25,
        "guardrail.card": 10,
        "research.catalogue": 25,
        "research.hypothesis": 10,
    }
)

#: The catalogue's set: asked only about content the screen cleared.
CATALOGUE_SET_NAME = "research.catalogue"

#: The two sets asked about a hypothesis's title.
TITLE_SET_NAMES = ("guardrail.card", "research.hypothesis")

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


def _lane_asks(lane: str) -> tuple[str, ...]:
    """The sets a ``jev_ask`` job asks whose answers are recorded in ``lane``."""
    return tuple(
        name
        for name in ASKS_PER_PASS
        if (question_set := jev_questions.REGISTRY.get(name)) is not None
        and question_set.lane == lane
    )


class _Room:
    """
    Calls each lane may still be planned today: its share of the budget, less
    the calls it made since UTC midnight, less the jobs already waiting to make
    one — of its kinds, and, from phase C7, the ``jev_ask`` jobs of its sets.
    Read once a pass and counted down as jobs are planned.
    """

    def __init__(self, conn: asyncpg.Connection, budget: int) -> None:
        self._conn = conn
        self._budget = budget
        self._left: dict[str, int] = {}

    async def left(self, lane: str) -> int:
        if lane not in self._left:
            share = jev_catalogue.lane_budget(self._budget, lane)
            spent = await jev_repo.requests_today(self._conn, lane)
            waiting = 0
            if kinds := LANE_KINDS.get(lane, ()):
                waiting += await jev_repo.pending_jobs(self._conn, kinds)
            if sets := _lane_asks(lane):
                waiting += await jev_repo.pending_asks(self._conn, sets)
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
    if await flags.jev_area_enabled(conn, INGEST_AREA):
        planned += await _plan_ingest(conn, now)
    planned += await _plan_asks(conn, now, model, room)
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


async def _plan_ingest(conn: asyncpg.Connection, now: datetime) -> list[str]:
    """
    One web ingest a UTC day for each source on the allow-list, due now.

    Keyed by the UTC date of ``now``, so no day but today is ever planned —
    nothing is caught up — and a job already under today's key, finished or
    not, is never joined by a second: the key holds across every status. The
    names come from the allow-list, and the payload names the source and
    nothing else, since the handler refuses anything more. It makes no call,
    so it takes nothing from a lane's share.
    """
    day = now.astimezone(UTC).date().isoformat()
    planned: list[str] = []
    for name in web_sources.ALLOWED_SOURCES:
        key = f"jev_web_ingest:{name}:{day}"
        if await _queued(conn, key):
            continue
        added = await job_repo.enqueue(
            conn,
            "jev_web_ingest",
            {"source": name},
            priority=INGEST_PRIORITY,
            max_attempts=INGEST_ATTEMPTS,
            scheduled_for=now,
            dedupe_key=key,
        )
        if added is not None:
            planned.append(key)
    return planned


async def _plan_asks(
    conn: asyncpg.Connection, now: datetime, model: str, room: _Room
) -> list[str]:
    """
    The ``jev_ask`` jobs (phases C7 and C8), set by set, each behind its own
    lane's area: at most :data:`ASKS_PER_PASS` of a set a pass, a job that can
    make a call only while its lane's share has one left, due now, under
    ``jev_repo.ask_job_key``. What each set is asked about is ``jev_repo``'s
    to read: :func:`jev_repo.documents_to_screen`,
    :func:`jev_repo.documents_to_describe` — content the screen cleared, and
    nothing else — and :func:`jev_repo.hypotheses_to_ask`.

    While an authentication failure recorded today holds every lane, or the
    vendor has refused a set with a 422 at its version under the pin, nothing
    of it that would make a call is planned: the road would refuse each such
    ask before any call, so each job would only fail. The screen's repairs are
    planned all the same, since they make no call and meet no hold — the road
    refuses blocked content for its block before it reads a standing refusal,
    and the handler quarantines flagged content before the road — and a 422
    holds the screen until a new version, which would otherwise hold its
    repairs as long.
    """
    held_today = await jev_repo.auth_failed_today(conn)
    day = now.astimezone(UTC).date()
    planned: list[str] = []
    for name in ASKS_PER_PASS:
        question_set = jev_questions.REGISTRY.get(name)
        if question_set is None:
            continue
        area = jev_catalogue.LANE_AREA.get(question_set.lane)
        if area is None or not await flags.jev_area_enabled(conn, area):
            continue
        plans = jev_prereg.plans_in_force(name, question_set.version)
        if plans is None:
            continue
        held = held_today or await jev_repo.set_refused(
            conn, question_set=name, version=question_set.version, model=model
        )
        if held and name != jev_questions.SCREEN_SET_NAME:
            continue
        subjects = await _ask_subjects(conn, question_set, model, day)
        if held:
            subjects = [subject for subject in subjects if not subject[2]]
        planned += await _enqueue_asks(conn, now, question_set, plans, subjects, room)
    return planned


async def _ask_subjects(
    conn: asyncpg.Connection,
    question_set: jev_questions.QuestionSet,
    model: str,
    day: date,
) -> list[tuple[str, object, bool]]:
    """
    What ``question_set`` is to be asked about: each subject's address, the
    row its text is read from, and whether its ask can make a call. Only the
    screen's repairs cannot: its ask about content a block is on record for,
    which the road refuses for the block before any call and whose follow-up
    quarantines the content, and about content the screen itself flagged,
    which the handler quarantines on the answer on record before any ask.
    """
    limit = ASKS_PER_PASS[question_set.name]
    if question_set.name == jev_questions.SCREEN_SET_NAME:
        rows = await jev_repo.documents_to_screen(
            conn, screen=question_set, model=model, limit=limit, day=day
        )
        return [
            (
                row["content_sha256"],
                row["document_id"],
                not (row["blocked"] or row["flagged"]),
            )
            for row in rows
        ]
    if question_set.name == CATALOGUE_SET_NAME:
        screen = jev_questions.REGISTRY.get(jev_questions.SCREEN_SET_NAME)
        if screen is None:
            return []
        rows = await jev_repo.documents_to_describe(
            conn,
            screen=screen,
            catalogue=question_set,
            model=model,
            limit=limit,
            day=day,
        )
        return [(row["content_sha256"], row["document_id"], True) for row in rows]
    if question_set.name in TITLE_SET_NAMES:
        rows = await jev_repo.hypotheses_to_ask(
            conn, question_set=question_set, model=model, limit=limit, day=day
        )
        return [(row["subject_id"], row["ref"], True) for row in rows]
    return []


async def _enqueue_asks(
    conn: asyncpg.Connection,
    now: datetime,
    question_set: jev_questions.QuestionSet,
    plans: Mapping[str, Any],
    subjects: Sequence[tuple[str, object, bool]],
    room: _Room,
) -> list[str]:
    """
    One ``jev_ask`` job for each subject, in the order given, until the lane's
    share has no call left: the payload names the set, its version, the
    subject, the row its text is read from and the analysis plans in force
    (``jev_prereg.plans_in_force``), never the text. The handler asks nothing
    under other plans, so every answer the job records is recorded under the
    plans its payload names.
    """
    day = now.astimezone(UTC).date()
    subject_type = jev_questions.STATE_SUBJECT[question_set.state_model]
    planned: list[str] = []
    for subject_id, source_id, calls in subjects:
        if calls and await room.left(question_set.lane) <= 0:
            break
        key = jev_repo.ask_job_key(
            question_set.name, question_set.version, subject_type, subject_id, day
        )
        added = await job_repo.enqueue(
            conn,
            "jev_ask",
            {
                "set": question_set.name,
                "version": question_set.version,
                "subject_type": subject_type,
                "subject_id": subject_id,
                "source_id": source_id,
                **plans,
            },
            priority=ASK_PRIORITY,
            max_attempts=ASK_ATTEMPTS,
            scheduled_for=now,
            dedupe_key=key,
        )
        if calls:
            room.take(question_set.lane)
        if added is not None:
            planned.append(key)
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
    area on, and, for web text, the text neither quarantined since nor found
    addressed to an AI system by the injection screen, whose quarantine may
    have failed to write (``jev_repo.screen_flag``): a probe would send the
    flagged text to the vendor again, and its repair is the screen's job.
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
        return (
            await jev_repo.content_quarantined(conn, row["subject_id"]) is None
            and await jev_repo.screen_flag(conn, row["subject_id"]) is None
        )
    return True


async def _queued(conn: asyncpg.Connection, key: str) -> bool:
    """Whether a job is in the queue under ``key``, in any status."""
    return key in await jev_repo.job_outcomes(conn, [key])


__all__ = [
    "ASKS_PER_PASS",
    "ASK_ATTEMPTS",
    "ASK_PRIORITY",
    "CATALOGUE_SET_NAME",
    "INGEST_AREA",
    "INGEST_ATTEMPTS",
    "INGEST_PRIORITY",
    "LANE_KINDS",
    "PROBE_ATTEMPTS",
    "PROBE_PRIORITY",
    "REASK_ATTEMPTS",
    "REASK_PRIORITY",
    "REFERENCE_ATTEMPTS",
    "REGIME_ATTEMPTS",
    "REGIME_PRIORITY",
    "RETRY_BACKOFF_STEP",
    "TITLE_SET_NAMES",
    "attempts_spanning",
    "plan",
]
