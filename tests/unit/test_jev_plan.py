"""
test_jev_plan.py
----------------
The planner: nothing unless every switch, the pin and a key allow it; each
rule behind its own area; no backlog; one probe a UTC day; the re-asks the
pre-registered sample; and never more calls planned than a lane's share has
left.

The switches are read through the shipped readers from a connection that
answers their one query and nothing else, so a planner that asked the wrong
switch — the lane's name where the area's belongs — reads off here as it would
in production. The queue and the ledger's reads are fakes of the functions the
planner calls, the queue keeping ``jobs.dedupe_key``'s uniqueness across every
status. That the dark database plans nothing end to end, through the loop, is
``tests/integration/test_jev_dark.py``'s.
"""

from __future__ import annotations

import dataclasses
import inspect
import itertools
import json
import logging
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from types import MappingProxyType
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from src.core import calendar
from src.data.reference import REFERENCE_PRIORITY
from src.db.repos import jobs as job_repo
from src.programme import (
    flags,
    jev_catalogue,
    jev_chips,
    jev_clock,
    jev_plan,
    jev_prereg,
    jev_questions,
    jev_redact,
    jev_repo,
    web_sources,
)
from src.programme.jev_questions import DECISION_REGIME
from src.worker.scheduling import PRIORITY

FLAG_QUERY = "SELECT value FROM system_flags WHERE key = $1"
MODEL = jev_catalogue.DEFAULT_MODEL
AREA_DECISIONS = f"{flags.JEV_AREA_PREFIX}decisions"
AREA_RESEARCH = f"{flags.JEV_AREA_PREFIX}research"
AREA_GUARDRAILS = f"{flags.JEV_AREA_PREFIX}guardrails"
AREA_FINDINGS = f"{flags.JEV_AREA_PREFIX}findings"
AREA_OPS = f"{flags.JEV_AREA_PREFIX}ops"

#: Monday 2026-09-28, 14:00 UTC: before the day's cutoff.
MORNING = datetime(2026, 9, 28, 14, 0, tzinfo=UTC)


def _switches(**overrides: str | None) -> dict[str, str]:
    rows: dict[str, str | None] = {
        flags.PROGRAMME_ENABLED: "true",
        flags.JEV_ENABLED: "true",
        AREA_DECISIONS: "true",
        flags.JEV_MODEL: json.dumps(MODEL),
        flags.JEV_DAILY_REQUEST_BUDGET: "500",
    }
    rows.update(overrides)
    return {key: value for key, value in rows.items() if value is not None}


class _Conn:
    """Answers the switches' one query from ``rows``, and nothing else."""

    def __init__(self, rows: Mapping[str, str]) -> None:
        self.rows = dict(rows)
        self.asked: list[str] = []

    async def fetchrow(self, query: str, *args: object) -> dict[str, str] | None:
        assert query == FLAG_QUERY, f"the planner ran SQL of its own: {query!r}"
        (key,) = args
        self.asked.append(str(key))
        return {"value": self.rows[key]} if key in self.rows else None


_ENQUEUE = inspect.signature(job_repo.enqueue)


@dataclass
class Queue:
    """``job_repo.enqueue`` and the ledger's reads the planner makes."""

    jobs: dict[str, dict[str, Any]] = field(default_factory=dict)
    calls_today: dict[str, int] = field(default_factory=dict)
    canonical: list[dict[str, Any]] = field(default_factory=list)
    quarantined: set[str] = field(default_factory=set)
    #: Content the injection screen found addressed to an AI system.
    flagged: set[str] = field(default_factory=set)
    canonical_asked: list[tuple[datetime, datetime]] = field(default_factory=list)
    #: What each subject read returns (phases C7 and C8), and every read made.
    screens: list[dict[str, Any]] = field(default_factory=list)
    descriptions: list[dict[str, Any]] = field(default_factory=list)
    titles: list[dict[str, Any]] = field(default_factory=list)
    #: What the findings sets' read returns (phase D2).
    findings: list[dict[str, Any]] = field(default_factory=list)
    subject_reads: list[dict[str, Any]] = field(default_factory=list)
    #: The failed jobs the ops set's read returns (phase D3), every read of
    #: them made, and the addresses ``unasked_subjects`` leaves out.
    failed: list[dict[str, Any]] = field(default_factory=list)
    job_reads: list[dict[str, Any]] = field(default_factory=list)
    asked_addresses: set[str] = field(default_factory=set)
    auth_held: bool = False
    refused_sets: set[str] = field(default_factory=set)

    async def enqueue(self, *args: Any, **kwargs: Any) -> Any:
        bound = _ENQUEUE.bind(*args, **kwargs)
        bound.apply_defaults()
        job = dict(bound.arguments)
        job.pop("conn")
        json.dumps(job["payload"])  # what the queue stores as jsonb
        key = job["dedupe_key"]
        assert key is not None, "the planner enqueues nothing without a key"
        if key in self.jobs:
            return None
        self.jobs[key] = {**job, "status": "queued"}
        return key

    async def job_outcomes(self, conn: Any, keys: Any) -> dict[str, dict[str, Any]]:
        return {key: self.jobs[key] for key in keys if key in self.jobs}

    async def requests_today(self, conn: Any, lane: str | None = None) -> int:
        return self.calls_today.get(lane or "", 0)

    async def pending_jobs(self, conn: Any, kinds: Any) -> int:
        return sum(
            1
            for job in self.jobs.values()
            if job["kind"] in kinds and job["status"] in ("queued", "running")
        )

    async def canonical_requests_between(
        self, conn: Any, *, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        self.canonical_asked.append((start, end))
        return [row for row in self.canonical if start <= row["available_at"] < end]

    async def content_quarantined(self, conn: Any, content_sha256: str) -> int | None:
        return 1 if content_sha256 in self.quarantined else None

    async def screen_flag(
        self, conn: Any, content_sha256: str
    ) -> dict[str, Any] | None:
        if content_sha256 not in self.flagged:
            return None
        return {"request_id": 1, "question_set_version": 1, "noul": 0.9}

    async def pending_asks(self, conn: Any, sets: Any) -> int:
        return sum(
            1
            for job in self.jobs.values()
            if job["kind"] == "jev_ask"
            and job["payload"]["set"] in sets
            and job["status"] in ("queued", "running")
        )

    async def auth_failed_today(self, conn: Any) -> bool:
        return self.auth_held

    async def set_refused(
        self, conn: Any, *, question_set: str, version: int, model: str
    ) -> bool:
        return question_set in self.refused_sets

    async def documents_to_screen(
        self, conn: Any, *, screen: Any, model: str, limit: int, day: date
    ) -> list[dict[str, Any]]:
        self.subject_reads.append(
            {
                "read": "screen",
                "set": screen,
                "model": model,
                "limit": limit,
                "day": day,
            }
        )
        return self.screens[:limit]

    async def documents_to_describe(
        self,
        conn: Any,
        *,
        screen: Any,
        catalogue: Any,
        model: str,
        limit: int,
        day: date,
    ) -> list[dict[str, Any]]:
        self.subject_reads.append(
            {
                "read": "describe",
                "set": catalogue,
                "screen": screen,
                "model": model,
                "limit": limit,
                "day": day,
            }
        )
        return self.descriptions[:limit]

    async def hypotheses_to_ask(
        self, conn: Any, *, question_set: Any, model: str, limit: int, day: date
    ) -> list[dict[str, Any]]:
        self.subject_reads.append(
            {
                "read": "titles",
                "set": question_set,
                "model": model,
                "limit": limit,
                "day": day,
            }
        )
        return self.titles[:limit]

    async def findings_to_ask(
        self, conn: Any, *, question_set: Any, model: str, limit: int, day: date
    ) -> list[dict[str, Any]]:
        self.subject_reads.append(
            {
                "read": "findings",
                "set": question_set,
                "model": model,
                "limit": limit,
                "day": day,
            }
        )
        return self.findings[:limit]

    async def failed_jobs_for_triage(
        self,
        conn: Any,
        *,
        kinds: Any,
        since: datetime,
        limit: int | None = 200,
    ) -> list[dict[str, Any]]:
        """As the read: of ``kinds``, finished after ``since``, newest first."""
        self.job_reads.append({"kinds": tuple(kinds), "since": since, "limit": limit})
        rows = [
            row
            for row in self.failed
            if row["kind"] in kinds and row["finished_at"] > since
        ]
        rows.sort(key=lambda row: (row["finished_at"], row["id"]), reverse=True)
        return rows if limit is None else rows[:limit]

    async def unasked_subjects(
        self,
        conn: Any,
        *,
        question_set: Any,
        model: str,
        subject_type: str,
        subjects: Any,
        day: date,
    ) -> list[str]:
        self.subject_reads.append(
            {
                "read": "unasked",
                "set": question_set,
                "model": model,
                "subject_type": subject_type,
                "subjects": list(subjects),
                "day": day,
            }
        )
        return [subject for subject in subjects if subject not in self.asked_addresses]


@pytest.fixture
def queue(monkeypatch: pytest.MonkeyPatch) -> Queue:
    fake = Queue()
    monkeypatch.setattr(job_repo, "enqueue", fake.enqueue)
    for name in (
        "job_outcomes",
        "requests_today",
        "pending_jobs",
        "canonical_requests_between",
        "content_quarantined",
        "pending_asks",
        "auth_failed_today",
        "set_refused",
        "documents_to_screen",
        "documents_to_describe",
        "hypotheses_to_ask",
        "findings_to_ask",
        "failed_jobs_for_triage",
        "unasked_subjects",
    ):
        monkeypatch.setattr(jev_repo, name, getattr(fake, name))
    monkeypatch.setattr(jev_repo, "screen_flag", fake.screen_flag)
    return fake


async def _plan(
    rows: Mapping[str, str] | None = None,
    *,
    now: datetime = MORNING,
    key: bool = True,
) -> list[str]:
    return await jev_plan.plan(
        _Conn(_switches() if rows is None else rows), now=now, key_available=key
    )


# ---------------------------------------------------------------------------
# Dark unless everything says otherwise
# ---------------------------------------------------------------------------

PROGRAMME = ["true", "false", '"true"', None]
JEV = ["true", "false", None]
DECISIONS = ["true", "false", None]
RESEARCH = ["true", "false", '"true"', None]
GUARDRAILS = ["true", "false", None]
PIN = [json.dumps(MODEL), json.dumps("jev-latest"), None]
KEY = [True, False]

#: One subject for each of the subject reads (phases C7 and C8), invented.
SCREEN_SUBJECT = {
    "content_sha256": "a1" * 32,
    "document_id": 7,
    "blocked": False,
    "flagged": False,
}
DESCRIBE_SUBJECT = {"content_sha256": "c3" * 32, "document_id": 9}
TITLE_SUBJECT = {"subject_id": "b2" * 32, "ref": "H-0007"}
#: And one for the findings sets' read (phase D2).
FINDING_SUBJECT = {"subject_id": "f6" * 32, "ref": "F-0042"}

#: And, from phase D3, failed jobs for the ops set, invented: each of a triaged
#: kind, its error one code leaves to Jev, with a word of the canary riding in
#: it, which the redactor reduces to a placeholder and nothing may log or
#: queue.
CANARY = "CANARY-d3e1"


def _residue_words(n: int) -> tuple[str, ...]:
    """
    ``n`` vocabulary words, each giving :func:`_failed`'s error a skeleton of
    its own that code leaves to Jev.
    """
    words: list[str] = []
    seen: set[tuple[str, ...]] = set()
    for word in sorted(jev_redact.VOCABULARY - jev_redact.FUNCTION_WORDS):
        error = f"[Errno 111] Connection refused while {word} {CANARY}"
        tokens = jev_chips.residue_skeleton("ingest_bars", error)
        if tokens is not None and word in tokens and tokens not in seen:
            seen.add(tokens)
            words.append(word)
        if len(words) == n:
            return tuple(words)
    raise AssertionError(f"the vocabulary gives fewer than {n} such errors")


_WORDS = _residue_words(40)


def _job_id(i: int) -> uuid.UUID:
    return uuid.UUID(f"6d0c5b1e-0d3a-4d37-9c43-{i:012d}")


def _failed(i: int, **overrides: Any) -> dict[str, Any]:
    """
    Failed job ``i`` as ``jev_repo.failed_jobs_for_triage`` returns one — its
    id, kind, error and finish time — the smaller ``i`` the newer, each with
    a skeleton of its own.
    """
    row = {
        "id": _job_id(i),
        "kind": "ingest_bars",
        "error": f"[Errno 111] Connection refused while {_WORDS[i - 1]} {CANARY}",
        "finished_at": MORNING - timedelta(minutes=i),
    }
    row.update(overrides)
    return row


class TestItIsDark:
    @pytest.mark.parametrize(
        ("programme", "jev", "decisions", "research", "guardrails", "pin", "key"),
        list(
            itertools.product(PROGRAMME, JEV, DECISIONS, RESEARCH, GUARDRAILS, PIN, KEY)
        ),
    )
    async def test_nothing_unless_every_switch_the_pin_and_a_key_allow_it(
        self,
        queue: Queue,
        programme: str | None,
        jev: str | None,
        decisions: str | None,
        research: str | None,
        guardrails: str | None,
        pin: str | None,
        key: bool,
    ) -> None:
        """
        From phases C7 and C8 the matrix has the guardrails area too, and a
        subject waiting for every set, so an ask planned without its area, or
        not planned with it, shows here. From phase D2 a finding's title waits
        too, with the findings area never switched on, so a findings set
        planned behind another area's switch shows here as well
        (:class:`TestTheSwitchMatrix` switches the findings area itself); and
        from phase D3 a failed job, with the ops area never switched on, so
        the ops set read or planned behind another switch shows here too.
        """
        queue.screens = [SCREEN_SUBJECT]
        queue.descriptions = [DESCRIBE_SUBJECT]
        queue.titles = [TITLE_SUBJECT]
        queue.findings = [FINDING_SUBJECT]
        queue.failed = [_failed(1)]
        rows = _switches(
            **{
                flags.PROGRAMME_ENABLED: programme,
                flags.JEV_ENABLED: jev,
                AREA_DECISIONS: decisions,
                AREA_RESEARCH: research,
                AREA_GUARDRAILS: guardrails,
                flags.JEV_MODEL: pin,
            }
        )
        planned = await _plan(rows, key=key)
        assert queue.job_reads == [], "a failed job was read with ops off"
        open_ = programme == "true" and jev == "true" and pin == json.dumps(MODEL)
        if not (open_ and key):
            assert planned == [] and queue.jobs == {}
            assert queue.subject_reads == []
            return
        kinds = {queue.jobs[k]["kind"] for k in planned}
        expected = {"jev_probe"}
        if decisions == "true":
            expected |= {"ingest_reference_bars", "jev_regime"}
        if research == "true":
            expected |= {"jev_web_ingest", "jev_ask"}
        if guardrails == "true":
            expected.add("jev_ask")
        assert kinds == expected, "a rule planned without its area, or not with it"
        asked = {
            queue.jobs[k]["payload"]["set"]
            for k in planned
            if queue.jobs[k]["kind"] == "jev_ask"
        }
        sets: set[str] = set()
        if guardrails == "true":
            sets |= {"guardrail.injection", "guardrail.card"}
        if research == "true":
            sets |= {"research.catalogue", "research.hypothesis"}
        assert asked == sets, "a set asked without its own area, or not with it"

    async def test_with_no_key_not_even_a_switch_is_read(self, queue: Queue) -> None:
        conn = _Conn(_switches())
        assert await jev_plan.plan(conn, now=MORNING, key_available=False) == []
        assert conn.asked == []

    async def test_each_switch_is_read_by_its_own_reader(self, queue: Queue) -> None:
        conn = _Conn(_switches())
        await jev_plan.plan(conn, now=MORNING, key_available=True)
        assert conn.asked[:3] == [
            flags.PROGRAMME_ENABLED,
            flags.JEV_ENABLED,
            flags.JEV_MODEL,
        ]
        assert AREA_DECISIONS in conn.asked

    async def test_a_naive_time_is_refused(self, queue: Queue) -> None:
        with pytest.raises(ValueError):
            await _plan(now=datetime(2026, 9, 28, 14))


# ---------------------------------------------------------------------------
# The daily probe
# ---------------------------------------------------------------------------


class TestTheDailyProbe:
    async def test_once_per_utc_day(self, queue: Queue) -> None:
        """Open item 18: the probe is planned, once a UTC day, and no more."""
        rows = _switches(**{AREA_DECISIONS: "false"})
        assert await _plan(rows) == ["jev_probe:2026-09-28"]
        assert await _plan(rows, now=MORNING + timedelta(hours=9)) == []
        assert await _plan(rows, now=MORNING + timedelta(hours=10)) == [
            "jev_probe:2026-09-29"
        ]

    async def test_it_is_planned_now_and_asks_nothing_itself(
        self, queue: Queue
    ) -> None:
        await _plan(_switches(**{AREA_DECISIONS: "false"}))
        (job,) = queue.jobs.values()
        assert job["kind"] == "jev_probe" and job["payload"] == {}
        assert job["scheduled_for"] == MORNING
        assert (job["priority"], job["max_attempts"]) == (40, 3)

    async def test_a_spent_probe_share_plans_none(self, queue: Queue) -> None:
        share = jev_catalogue.lane_budget(500, "probe")
        queue.calls_today["probe"] = share
        assert await _plan(_switches(**{AREA_DECISIONS: "false"})) == []

    async def test_a_budget_of_nothing_plans_nothing_that_calls(
        self, queue: Queue
    ) -> None:
        planned = await _plan(_switches(**{flags.JEV_DAILY_REQUEST_BUDGET: "0"}))
        assert {queue.jobs[k]["kind"] for k in planned} == {"ingest_reference_bars"}


# ---------------------------------------------------------------------------
# The forward clock
# ---------------------------------------------------------------------------


class TestTheForwardClock:
    async def test_today_and_the_next_session(self, queue: Queue) -> None:
        planned = await _plan()
        today, following = date(2026, 9, 28), date(2026, 9, 29)
        assert planned == [
            "jev_probe:2026-09-28",
            "ingest_reference_bars:2026-09-28",
            "jev_regime:decision.regime@1:2026-09-28",
            "ingest_reference_bars:2026-09-29",
            "jev_regime:decision.regime@1:2026-09-29",
        ]
        for session in (today, following):
            reference = queue.jobs[jev_clock.reference_job_key(session)]
            assert reference["kind"] == "ingest_reference_bars"
            assert reference["payload"] == {"session": session.isoformat()}
            assert reference["scheduled_for"] == jev_clock.reference_at(session)
            assert reference["priority"] == REFERENCE_PRIORITY
            assert reference["max_attempts"] == jev_plan.REFERENCE_ATTEMPTS
            regime = queue.jobs[jev_clock.regime_job_key(DECISION_REGIME, session)]
            assert regime["kind"] == "jev_regime"
            assert regime["payload"] == {
                "session": session.isoformat(),
                "set": "decision.regime",
                "version": 1,
            }
            assert regime["scheduled_for"] == jev_clock.collect_at(session)
            assert (regime["priority"], regime["max_attempts"]) == (50, 20)

    async def test_planning_again_adds_nothing(self, queue: Queue) -> None:
        await _plan()
        before = dict(queue.jobs)
        assert await _plan(now=MORNING + timedelta(minutes=1)) == []
        assert queue.jobs == before

    async def test_no_backlog(self, queue: Queue) -> None:
        """After the cutoff, today is not planned: a missed session is absent."""
        planned = await _plan(now=datetime(2026, 9, 28, 21, 0, tzinfo=UTC))
        assert all(key.endswith("2026-09-29") for key in planned if "@" in key)
        assert not any("2026-09-28" in key for key in planned if "jev_probe" not in key)

    async def test_the_next_session_is_planned_over_a_weekend(
        self, queue: Queue
    ) -> None:
        planned = await _plan(now=datetime(2026, 9, 26, 12, 0, tzinfo=UTC))
        assert "jev_regime:decision.regime@1:2026-09-28" in planned

    async def test_nothing_past_the_calendars_end(self, queue: Queue) -> None:
        _, last = calendar.bounds()
        after = calendar.session_close(last) + timedelta(hours=2)
        planned = await _plan(now=after)
        assert [queue.jobs[k]["kind"] for k in planned] == ["jev_probe"]

    async def test_a_spent_decision_share_plans_no_regime(self, queue: Queue) -> None:
        """The reference bars make no call, so they are still planned."""
        queue.calls_today["decision"] = jev_catalogue.lane_budget(500, "decision")
        planned = await _plan()
        kinds = [queue.jobs[k]["kind"] for k in planned]
        assert "jev_regime" not in kinds
        assert kinds.count("ingest_reference_bars") == 2

    async def test_jobs_already_waiting_count_against_the_share(
        self, queue: Queue
    ) -> None:
        share = jev_catalogue.lane_budget(10, "decision")  # 2
        assert share == 2
        for n in range(share):
            queue.jobs[f"elsewhere:{n}"] = {"kind": "jev_regime", "status": "queued"}
        planned = await _plan(_switches(**{flags.JEV_DAILY_REQUEST_BUDGET: "10"}))
        assert not [k for k in planned if k.startswith("jev_regime")]

    async def test_one_call_left_plans_one_session_not_two(self, queue: Queue) -> None:
        """
        Each regime job planned takes its call from the room it was planned
        against, so a pass with two sessions to plan and one call left plans
        the first and not the second. C4's review found nothing holding this:
        the test above leaves a room of nothing, which plans nothing whether or
        not the room is counted down.
        """
        assert jev_catalogue.lane_budget(10, "decision") == 2
        queue.calls_today["decision"] = 1
        planned = await _plan(_switches(**{flags.JEV_DAILY_REQUEST_BUDGET: "10"}))
        assert [k for k in planned if k.startswith("jev_regime")] == [
            "jev_regime:decision.regime@1:2026-09-28"
        ]
        assert [k for k in planned if k.startswith("ingest_reference_bars")] == [
            "ingest_reference_bars:2026-09-28",
            "ingest_reference_bars:2026-09-29",
        ], "the reference bars make no call and are planned regardless"


class TestTheWebIngest:
    """
    Phase C6: once a UTC day for each allowed source, behind the research
    area, due now, and never for a day but today.
    """

    RESEARCH_ON = {AREA_DECISIONS: "false", AREA_RESEARCH: "true"}

    async def test_once_a_utc_day_for_each_allowed_source(self, queue: Queue) -> None:
        planned = await _plan(_switches(**self.RESEARCH_ON))
        assert planned == [
            "jev_probe:2026-09-28",
            "jev_web_ingest:pwb-readme:2026-09-28",
        ]
        job = queue.jobs["jev_web_ingest:pwb-readme:2026-09-28"]
        assert job["kind"] == "jev_web_ingest"
        assert job["payload"] == {"source": "pwb-readme"}
        assert job["scheduled_for"] == MORNING
        assert (job["priority"], job["max_attempts"]) == (10, 3)
        ingests = [k for k in queue.jobs if k.startswith("jev_web_ingest")]
        assert len(ingests) == len(web_sources.ALLOWED_SOURCES)

    async def test_the_day_is_the_utc_days(self, queue: Queue) -> None:
        """
        At 01:00 UTC on the 29th it is still the 28th in New York; the key is
        the UTC day's, and the 28th, a past day, is not planned.
        """
        night = datetime(2026, 9, 29, 1, 0, tzinfo=UTC)
        planned = await _plan(_switches(**self.RESEARCH_ON), now=night)
        assert "jev_web_ingest:pwb-readme:2026-09-29" in planned
        assert not [k for k in queue.jobs if k.endswith("2026-09-28")]

    async def test_planning_again_the_same_day_adds_nothing(self, queue: Queue) -> None:
        rows = _switches(**self.RESEARCH_ON)
        await _plan(rows)
        for status in ("queued", "running", "succeeded", "failed"):
            queue.jobs["jev_web_ingest:pwb-readme:2026-09-28"]["status"] = status
            later = MORNING + timedelta(hours=9, minutes=59)
            assert await _plan(rows, now=later) == [], status
        assert await _plan(rows, now=MORNING + timedelta(hours=10)) == [
            "jev_probe:2026-09-29",
            "jev_web_ingest:pwb-readme:2026-09-29",
        ]

    async def test_it_is_planned_on_a_budget_of_nothing_since_it_calls_nothing(
        self, queue: Queue
    ) -> None:
        rows = _switches(**self.RESEARCH_ON, **{flags.JEV_DAILY_REQUEST_BUDGET: "0"})
        assert await _plan(rows) == ["jev_web_ingest:pwb-readme:2026-09-28"]

    async def test_the_research_area_is_read_by_its_own_reader(
        self, queue: Queue
    ) -> None:
        conn = _Conn(_switches(**self.RESEARCH_ON))
        await jev_plan.plan(conn, now=MORNING, key_available=True)
        assert AREA_RESEARCH in conn.asked


class TestTheReferenceJobsAttempts:
    """docs/08 open item 39."""

    def test_its_retries_reach_the_cutoff(self) -> None:
        n = jev_plan.REFERENCE_ATTEMPTS
        waited = timedelta(seconds=5 * n * (n - 1))
        span = jev_clock.DECISION_AFTER_CLOSE - jev_clock.REFERENCE_AFTER_CLOSE
        assert waited >= span == timedelta(minutes=15)
        assert timedelta(seconds=5 * (n - 1) * (n - 2)) < span, "not the fewest"
        assert n == 14

    def test_the_regime_jobs_outlast_its_window(self) -> None:
        n = jev_plan.REGIME_ATTEMPTS
        span = jev_clock.DECISION_AFTER_CLOSE - jev_clock.COLLECT_AFTER_CLOSE
        assert timedelta(seconds=5 * n * (n - 1)) >= 3 * span

    def test_the_backoff_is_the_queues(self) -> None:
        """Read from the queue's own SQL, so a change there is seen here."""
        source = inspect.getsource(job_repo.fail)
        (seconds,) = re.findall(r"attempts \* INTERVAL '(\d+) seconds'", source)
        assert timedelta(seconds=int(seconds)) == jev_plan.RETRY_BACKOFF_STEP

    @pytest.mark.parametrize(
        ("minutes", "attempts"), [(0, 1), (1, 4), (15, 14), (16, 15), (17, 15)]
    )
    def test_attempts_spanning(self, minutes: int, attempts: int) -> None:
        assert jev_plan.attempts_spanning(timedelta(minutes=minutes)) == attempts

    def test_the_priorities_sit_where_they_should(self) -> None:
        """The reference job behind every live-path kind; the regime above the
        probe; a re-ask behind everything."""
        assert REFERENCE_PRIORITY < min(PRIORITY.values())
        assert jev_plan.REGIME_PRIORITY > jev_plan.PROBE_PRIORITY
        assert jev_plan.REASK_PRIORITY < 0


# ---------------------------------------------------------------------------
# The re-asks
# ---------------------------------------------------------------------------

YESTERDAY = datetime(2026, 9, 27, 15, 0, tzinfo=UTC)


def _hash(prefix: str) -> str:
    return prefix + "0" * (64 - len(prefix))


def _canonical(
    row_id: int,
    request_hash: str,
    *,
    margins: tuple[float, ...] = (0.5,),
    at: datetime = YESTERDAY,
    **overrides: Any,
) -> dict[str, Any]:
    row = {
        "id": row_id,
        "request_hash": request_hash,
        "question_set": DECISION_REGIME.name,
        "question_set_version": DECISION_REGIME.version,
        "pack_hash": DECISION_REGIME.pack_hash,
        "lane": "decision",
        "subject_type": "session",
        "subject_id": "2026-09-25",
        "model_requested": MODEL,
        "available_at": at,
        "valid_margins": list(margins),
    }
    row.update(overrides)
    return row


def _reasks(queue: Queue) -> list[dict[str, Any]]:
    return [job for job in queue.jobs.values() if job["kind"] == "jev_reask"]


class TestTheReasks:
    async def test_the_previous_utc_days_answers_are_sampled(
        self, queue: Queue
    ) -> None:
        queue.canonical = [
            _canonical(1, _hash("00000000")),  # uniform: 0 % 20
            _canonical(2, _hash("00000001")),  # neither
            _canonical(3, _hash("00000002"), margins=(0.1,)),  # low margin
            _canonical(4, _hash("00000014")),  # uniform: 20 % 20
            _canonical(5, _hash("00000000"), at=MORNING - timedelta(hours=1)),
        ]
        planned = await _plan()
        assert [k for k in planned if k.startswith("jev_reask")] == [
            "jev_reask:1",
            "jev_reask:4",
            "jev_reask:3",
        ]
        ((start, end),) = queue.canonical_asked
        assert (start, end) == (
            datetime(2026, 9, 27, tzinfo=UTC),
            datetime(2026, 9, 28, tzinfo=UTC),
        )

    async def test_each_is_asked_a_day_after_its_answer(self, queue: Queue) -> None:
        queue.canonical = [_canonical(1, _hash("00000000"))]
        await _plan()
        (job,) = _reasks(queue)
        assert job["payload"]["request_id"] == 1
        assert job["scheduled_for"] == YESTERDAY + timedelta(hours=24)
        assert (job["priority"], job["max_attempts"]) == (-10, 3)

    async def test_each_records_the_stratum_and_the_plan_it_was_drawn_under(
        self, queue: Queue
    ) -> None:
        """
        The harness counts a pair only in the stratum it was sampled in and
        only under the plan that drew it (``jev_eval._flip_rates``), so a
        change of plan never re-sorts the pairs drawn before it. The handler
        reads the request id and nothing else.
        """
        queue.canonical = [
            _canonical(1, _hash("00000000")),
            _canonical(2, _hash("00000002"), margins=(0.1,)),
        ]
        await _plan()
        payloads = {
            job["payload"]["request_id"]: job["payload"] for job in _reasks(queue)
        }
        for request_id, stratum in ((1, "uniform"), (2, "low_margin")):
            assert payloads[request_id] == {
                "request_id": request_id,
                "stratum": stratum,
                "plan_version": jev_prereg.PLAN_VERSION,
                "plan_hash": jev_prereg.plan_hash(),
            }

    async def test_at_most_ten_a_day(self, queue: Queue) -> None:
        queue.canonical = [_canonical(n, _hash(f"{20 * n:08x}")) for n in range(1, 30)]
        planned = await _plan()
        assert len([k for k in planned if k.startswith("jev_reask")]) == 10
        assert await _plan(now=MORNING + timedelta(minutes=5)) == []
        assert len(_reasks(queue)) == jev_prereg.REASKS_PER_DAY

    async def test_never_beyond_the_probe_shares_calls(self, queue: Queue) -> None:
        queue.canonical = [_canonical(n, _hash(f"{20 * n:08x}")) for n in range(1, 30)]
        # A budget of 30 leaves the probe lane 3 calls; the daily probe takes one.
        await _plan(_switches(**{flags.JEV_DAILY_REQUEST_BUDGET: "30"}))
        assert len(_reasks(queue)) == 2

    @pytest.mark.parametrize(
        "overrides",
        [
            {"question_set": "research.gone"},
            {"pack_hash": "f" * 64},
            {"model_requested": "jev-9.9.9"},
        ],
        ids=["unregistered-set", "reworded-set", "another-model"],
    )
    async def test_what_is_not_asked_again(
        self, queue: Queue, overrides: dict[str, Any]
    ) -> None:
        queue.canonical = [_canonical(1, _hash("00000000"), **overrides)]
        await _plan()
        assert _reasks(queue) == []

    async def test_a_set_whose_area_is_off_is_not_asked_again(
        self, queue: Queue
    ) -> None:
        queue.canonical = [_canonical(1, _hash("00000000"))]
        await _plan(_switches(**{AREA_DECISIONS: "false"}))
        assert _reasks(queue) == []

    async def test_quarantined_text_is_not_asked_again(
        self, queue: Queue, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Web text is re-asked only while it is not quarantined."""
        from src.programme import jev_questions

        web_set = jev_questions.QuestionSet(
            name="research.excerpt",
            version=1,
            lane="research",
            provenance="web",
            questions=(("about_trading", {"type": "noul", "instructions": "Is it?"}),),
            state_model=jev_questions.WebExcerptState,
            purpose="test only",
        )
        monkeypatch.setitem(jev_questions.REGISTRY, web_set.name, web_set)
        sha = "ab" * 32
        queue.canonical = [
            _canonical(
                1,
                _hash("00000000"),
                question_set=web_set.name,
                pack_hash=web_set.pack_hash,
                lane="research",
                subject_type="web_excerpt",
                subject_id=sha,
            )
        ]
        queue.quarantined.add(sha)
        await _plan(_switches(**{f"{flags.JEV_AREA_PREFIX}research": "true"}))
        assert _reasks(queue) == []
        queue.quarantined.clear()
        await _plan(_switches(**{f"{flags.JEV_AREA_PREFIX}research": "true"}))
        assert len(_reasks(queue)) == 1

    async def test_text_the_screen_flagged_is_not_asked_again(
        self, queue: Queue
    ) -> None:
        """
        C7+C8's review: the screen's own ``true``, sampled for a re-ask while
        the quarantine it should have made had failed to write, sent the text
        to the vendor again as a probe. Flagged text is never re-asked; its
        repair is the screen's job (``jev_repo.documents_to_screen``).
        """
        from src.programme import jev_questions

        screen = jev_questions.GUARDRAIL_INJECTION
        sha = "cd" * 32
        queue.canonical = [
            _canonical(
                1,
                _hash("00000002"),
                margins=(0.1,),
                question_set=screen.name,
                pack_hash=screen.pack_hash,
                lane="guardrail",
                subject_type="web_excerpt",
                subject_id=sha,
            )
        ]
        rows = _switches(**{AREA_GUARDRAILS: "true"})
        queue.flagged.add(sha)
        await _plan(rows)
        assert _reasks(queue) == [], "flagged text was planned for a re-ask"
        queue.flagged.clear()
        await _plan(rows)
        assert len(_reasks(queue)) == 1

    async def test_the_cap_is_the_days_whatever_becomes_eligible(
        self, queue: Queue, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        C4's review: the cap was applied per pass to whatever was eligible,
        so switching an area on during the day drew a second ten from the
        answers the first pass had left out — twenty re-asks in one UTC day.
        The re-asks already queued for the day's answers count against it.
        """
        from src.programme import jev_questions

        research = jev_questions.QuestionSet(
            name="research.excerpt",
            version=1,
            lane="research",
            provenance="web",
            questions=(("about_trading", {"type": "noul", "instructions": "Is it?"}),),
            state_model=jev_questions.WebExcerptState,
            purpose="test only",
        )
        monkeypatch.setitem(jev_questions.REGISTRY, research.name, research)
        # Ten research answers whose hashes sort first, ten regime answers
        # after them, every one in the uniform stratum.
        queue.canonical = [
            _canonical(
                n,
                _hash(f"{20 * n:08x}"),
                question_set=research.name,
                pack_hash=research.pack_hash,
                lane="research",
                subject_type="web_excerpt",
                subject_id=f"{n:064x}",
            )
            for n in range(1, 11)
        ] + [_canonical(n, _hash(f"{20 * n:08x}")) for n in range(100, 110)]
        area = f"{flags.JEV_AREA_PREFIX}research"

        await _plan(_switches(**{area: "false"}))
        assert len(_reasks(queue)) == jev_prereg.REASKS_PER_DAY
        await _plan(_switches(**{area: "true"}), now=MORNING + timedelta(minutes=5))
        assert len(_reasks(queue)) == jev_prereg.REASKS_PER_DAY, (
            "a second sample was drawn in the same UTC day"
        )

    async def test_a_pass_short_of_room_leaves_the_rest_of_the_days_sample(
        self, queue: Queue
    ) -> None:
        """
        The day's cap, not the first pass's plan: a pass that ran out of room
        after two re-asks leaves eight, and a later pass with room plans the
        next eight of the same sample, in its order.
        """
        queue.canonical = [_canonical(n, _hash(f"{20 * n:08x}")) for n in range(1, 30)]
        await _plan(_switches(**{flags.JEV_DAILY_REQUEST_BUDGET: "30"}))
        assert len(_reasks(queue)) == 2
        await _plan(now=MORNING + timedelta(hours=1))
        sample = [
            f"jev_reask:{row['id']}"
            for _, row in jev_prereg.reask_sample(queue.canonical)
        ]
        assert sorted(key for key in queue.jobs if key.startswith("jev_reask")) == (
            sorted(sample)
        )

    async def test_the_sample_is_the_same_on_every_pass(self, queue: Queue) -> None:
        queue.canonical = [
            _canonical(n, _hash(f"{n:08x}"), margins=(0.05 * (n % 7),))
            for n in range(1, 60)
        ]
        first = [k for k in await _plan() if k.startswith("jev_reask")]
        queue.jobs.clear()
        second = [k for k in await _plan() if k.startswith("jev_reask")]
        assert first == second and first


# ---------------------------------------------------------------------------
# The asks (phases C7 and C8)
# ---------------------------------------------------------------------------

#: Both areas the asks need, and not the forward clock's.
ASKS_ON = {AREA_DECISIONS: "false", AREA_RESEARCH: "true", AREA_GUARDRAILS: "true"}


def _asks(queue: Queue, name: str | None = None) -> list[dict[str, Any]]:
    return [
        job
        for job in queue.jobs.values()
        if job["kind"] == "jev_ask" and name in (None, job["payload"]["set"])
    ]


def _screens(n: int, *, blocked: int = 0, flagged: int = 0) -> list[dict[str, Any]]:
    """
    ``n`` contents for the screen, the first ``blocked`` with a block on record
    and the first ``flagged`` with the screen's own ``true`` on record.
    """
    return [
        {
            "content_sha256": f"{i:064x}",
            "document_id": i,
            "blocked": i <= blocked,
            "flagged": i <= flagged,
        }
        for i in range(1, n + 1)
    ]


class TestTheAsks:
    """
    Phases C7 and C8: each set behind its own lane's area, no more of it a
    pass than its cap, within its lane's share, what the subject reads return
    and nothing else, and never the text in a payload.
    """

    def test_the_sets_and_their_caps_are_the_designs(self) -> None:
        from src.programme import jev_jobs

        assert dict(jev_plan.ASKS_PER_PASS) == {
            "guardrail.injection": 25,
            "guardrail.card": 10,
            "research.catalogue": 25,
            "research.hypothesis": 10,
            "findings.owner": 10,
            "findings.severity": 10,
            "ops.job_error": 10,
        }
        assert set(jev_plan.ASKS_PER_PASS) == set(jev_jobs.ASKABLE)
        assert (jev_plan.ASK_PRIORITY, jev_plan.ASK_ATTEMPTS) == (0, 3)
        assert jev_plan.ASK_ATTEMPTS == jev_repo.MAX_FAILED_CALLS
        assert jev_plan.REASK_PRIORITY < jev_plan.ASK_PRIORITY
        assert jev_plan.ASK_PRIORITY < jev_plan.INGEST_PRIORITY

    async def test_each_subject_is_one_job_naming_its_row_and_never_its_text(
        self, queue: Queue
    ) -> None:
        queue.screens = [SCREEN_SUBJECT]
        queue.descriptions = [DESCRIBE_SUBJECT]
        queue.titles = [TITLE_SUBJECT]
        planned = await _plan(_switches(**ASKS_ON))
        day = "2026-09-28"
        web, title, described = "a1" * 32, "b2" * 32, "c3" * 32
        expected = {
            f"jev_ask:guardrail.injection@1:web_excerpt:{web}:{day}": (
                "web_excerpt",
                web,
                7,
            ),
            f"jev_ask:guardrail.card@1:hypothesis_title:{title}:{day}": (
                "hypothesis_title",
                title,
                "H-0007",
            ),
            f"jev_ask:research.catalogue@1:web_excerpt:{described}:{day}": (
                "web_excerpt",
                described,
                9,
            ),
            f"jev_ask:research.hypothesis@1:hypothesis_title:{title}:{day}": (
                "hypothesis_title",
                title,
                "H-0007",
            ),
        }
        assert [k for k in planned if k.startswith("jev_ask:")] == list(expected)
        for key, (subject_type, subject_id, source_id) in expected.items():
            job = queue.jobs[key]
            name = key.split(":")[1].split("@")[0]
            assert job["kind"] == "jev_ask"
            plans = jev_prereg.plans_in_force(name, 1)
            assert plans is not None
            assert job["payload"] == {
                "set": name,
                "version": 1,
                "subject_type": subject_type,
                "subject_id": subject_id,
                "source_id": source_id,
                **plans,
            }, "the plans in force are named, and nothing else is"
            assert (job["priority"], job["max_attempts"]) == (0, 3)
            assert job["scheduled_for"] == MORNING
            assert key == jev_repo.ask_job_key(
                name, 1, subject_type, subject_id, date(2026, 9, 28)
            )

    async def test_each_read_is_for_its_set_the_pin_today_and_the_pass_cap(
        self, queue: Queue
    ) -> None:
        from src.programme import jev_questions

        await _plan(_switches(**ASKS_ON))
        reads = {(read["read"], read["set"].name): read for read in queue.subject_reads}
        assert set(reads) == {
            ("screen", "guardrail.injection"),
            ("titles", "guardrail.card"),
            ("describe", "research.catalogue"),
            ("titles", "research.hypothesis"),
        }
        for (_, name), read in reads.items():
            assert read["set"] is jev_questions.REGISTRY[name]
            assert read["model"] == MODEL
            assert read["day"] == date(2026, 9, 28)
            assert read["limit"] == jev_plan.ASKS_PER_PASS[name]
        screen = reads[("describe", "research.catalogue")]["screen"]
        assert screen is jev_questions.REGISTRY["guardrail.injection"]

    async def test_the_day_is_the_utc_days(self, queue: Queue) -> None:
        queue.screens = [SCREEN_SUBJECT]
        night = datetime(2026, 9, 29, 1, 0, tzinfo=UTC)
        planned = await _plan(_switches(**ASKS_ON), now=night)
        assert [k for k in planned if k.startswith("jev_ask:")] == [
            f"jev_ask:guardrail.injection@1:web_excerpt:{'a1' * 32}:2026-09-29"
        ]

    async def test_no_more_of_a_set_a_pass_than_its_cap(self, queue: Queue) -> None:
        queue.screens = _screens(40)
        queue.titles = [
            {"subject_id": f"{i:064x}", "ref": f"H-{i:04d}"} for i in range(1, 30)
        ]
        await _plan(_switches(**ASKS_ON))
        assert len(_asks(queue, "guardrail.injection")) == 25
        assert len(_asks(queue, "guardrail.card")) == 10
        assert len(_asks(queue, "research.hypothesis")) == 10

    async def test_never_beyond_the_lanes_share(self, queue: Queue) -> None:
        """
        A budget of 10 gives the guardrail and research lanes 2 calls each, at
        phase D's 25%; the screen, planned first, takes the guardrail lane's
        two, and the card check none.
        """
        assert jev_catalogue.lane_budget(10, "guardrail") == 2
        assert jev_catalogue.lane_budget(10, "research") == 2
        queue.screens = _screens(10)
        queue.titles = [TITLE_SUBJECT]
        await _plan(_switches(**ASKS_ON, **{flags.JEV_DAILY_REQUEST_BUDGET: "10"}))
        assert len(_asks(queue, "guardrail.injection")) == 2
        assert _asks(queue, "guardrail.card") == []
        assert len(_asks(queue, "research.hypothesis")) == 1

    async def test_one_call_left_plans_one_ask(self, queue: Queue) -> None:
        queue.screens = _screens(10)
        queue.calls_today["guardrail"] = 1
        await _plan(_switches(**ASKS_ON, **{flags.JEV_DAILY_REQUEST_BUDGET: "10"}))
        assert len(_asks(queue, "guardrail.injection")) == 1

    async def test_asks_already_waiting_count_against_their_lane(
        self, queue: Queue
    ) -> None:
        """
        Two card checks waiting from an earlier pass, one running and one
        queued, fill the guardrail lane's two calls, so no screen is planned;
        the research lane's are its own.
        """
        for n in range(2):
            queue.jobs[f"elsewhere:{n}"] = {
                "kind": "jev_ask",
                "status": "queued" if n else "running",
                "payload": {"set": "guardrail.card"},
            }
        queue.screens = _screens(5)
        queue.descriptions = [DESCRIBE_SUBJECT]
        await _plan(_switches(**ASKS_ON, **{flags.JEV_DAILY_REQUEST_BUDGET: "10"}))
        assert _asks(queue, "guardrail.injection") == []
        assert len(_asks(queue, "research.catalogue")) == 1

    async def test_finished_asks_do_not_count_against_the_lane(
        self, queue: Queue
    ) -> None:
        for n, status in enumerate(("succeeded", "failed", "cancelled")):
            queue.jobs[f"elsewhere:{n}"] = {
                "kind": "jev_ask",
                "status": status,
                "payload": {"set": "guardrail.card"},
            }
        queue.screens = _screens(5)
        await _plan(_switches(**ASKS_ON, **{flags.JEV_DAILY_REQUEST_BUDGET: "10"}))
        assert len(_asks(queue, "guardrail.injection")) == 2

    async def test_content_a_block_is_on_record_for_is_planned_with_no_call_left(
        self, queue: Queue
    ) -> None:
        """
        The screen's ask about blocked content makes no call — the road refuses
        it for the block, and its follow-up quarantines the content — so it is
        planned when the lane has no call left, and takes none.
        """
        queue.calls_today["guardrail"] = 3
        queue.screens = _screens(4, blocked=2)
        await _plan(_switches(**ASKS_ON, **{flags.JEV_DAILY_REQUEST_BUDGET: "10"}))
        assert [job["payload"]["source_id"] for job in _asks(queue)] == [1, 2]

    async def test_content_the_screen_flagged_is_planned_with_no_call_left(
        self, queue: Queue
    ) -> None:
        """
        C7+C8's review: content whose own screen answer was ``true`` and whose
        quarantine failed to write is planned again, before anything else, by
        an ask that makes no call — the handler quarantines it on the answer
        on record before any ask — so with no call left it is still planned,
        and takes none.
        """
        queue.calls_today["guardrail"] = 3
        queue.screens = _screens(4, flagged=2)
        await _plan(_switches(**ASKS_ON, **{flags.JEV_DAILY_REQUEST_BUDGET: "10"}))
        assert [job["payload"]["source_id"] for job in _asks(queue)] == [1, 2]

    async def test_nothing_that_calls_is_asked_while_an_authentication_failure_holds(
        self, queue: Queue
    ) -> None:
        """
        The road holds every lane for the day, so every ask that would call
        could only fail. The screen's repairs make no call and meet no hold —
        the road refuses blocked content for its block before it reads a
        standing refusal, and flagged content is quarantined before the road
        — so they alone are planned, and only the screen's subjects are read.
        """
        queue.auth_held = True
        queue.screens = _screens(4, blocked=1, flagged=2)
        queue.descriptions = [DESCRIBE_SUBJECT]
        queue.titles = [TITLE_SUBJECT]
        planned = await _plan(_switches(**ASKS_ON))
        assert [job["payload"]["source_id"] for job in _asks(queue)] == [1, 2]
        assert [read["set"].name for read in queue.subject_reads] == [
            "guardrail.injection"
        ]
        assert "jev_probe:2026-09-28" in planned

    async def test_a_set_the_vendor_refused_is_not_asked(self, queue: Queue) -> None:
        queue.refused_sets = {"guardrail.injection"}
        queue.screens = _screens(2)
        queue.titles = [TITLE_SUBJECT]
        await _plan(_switches(**ASKS_ON))
        assert _asks(queue, "guardrail.injection") == []
        assert len(_asks(queue, "guardrail.card")) == 1

    async def test_a_refused_screen_still_plans_its_repairs(self, queue: Queue) -> None:
        """
        C7+C8's review: a 422 holds the screen's version and pin until a new
        version, and the repair of a block whose quarantine failed — which
        the road refuses for the block, with no call, before it reads the
        hold — was held with it, for as long. Only what makes no call is
        planned of a refused set; of any other refused set, nothing.
        """
        queue.refused_sets = {"guardrail.injection", "research.hypothesis"}
        queue.screens = _screens(4, blocked=1, flagged=2)
        queue.titles = [TITLE_SUBJECT]
        await _plan(_switches(**ASKS_ON))
        assert [job["payload"]["source_id"] for job in _asks(queue)][:2] == [1, 2]
        assert len(_asks(queue, "guardrail.injection")) == 2
        assert _asks(queue, "research.hypothesis") == []
        assert len(_asks(queue, "guardrail.card")) == 1
        assert "research.hypothesis" not in [r["set"].name for r in queue.subject_reads]

    async def test_a_set_not_registered_is_not_asked(
        self, queue: Queue, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """And the catalogue is asked about nothing with no screen to clear it."""
        from src.programme import jev_questions

        monkeypatch.delitem(jev_questions.REGISTRY, "guardrail.injection")
        queue.screens = _screens(2)
        queue.descriptions = [DESCRIBE_SUBJECT]
        queue.titles = [TITLE_SUBJECT]
        await _plan(_switches(**ASKS_ON))
        assert {job["payload"]["set"] for job in _asks(queue)} == {
            "guardrail.card",
            "research.hypothesis",
        }

    async def test_a_set_with_no_plan_is_planned_nothing(
        self, queue: Queue, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Every ``jev_ask`` payload names the plans its answer will be recorded
        under, and the handler asks a set with none nothing, so the planner
        plans it nothing, and reads no subject for it.
        """
        real = jev_prereg.plans_in_force

        def only_the_card(name: str, version: int) -> dict[str, Any] | None:
            return real(name, version) if name == "guardrail.card" else None

        monkeypatch.setattr(jev_prereg, "plans_in_force", only_the_card)
        queue.screens = _screens(2)
        queue.descriptions = [DESCRIBE_SUBJECT]
        queue.titles = [TITLE_SUBJECT]
        await _plan(_switches(**ASKS_ON))
        assert {job["payload"]["set"] for job in _asks(queue)} == {"guardrail.card"}
        assert [read["set"].name for read in queue.subject_reads] == ["guardrail.card"]

    async def test_planning_again_the_same_day_adds_nothing(self, queue: Queue) -> None:
        queue.screens = [SCREEN_SUBJECT]
        rows = _switches(**ASKS_ON)
        await _plan(rows)
        before = dict(queue.jobs)
        assert [k for k in await _plan(rows) if k.startswith("jev_ask:")] == []
        assert queue.jobs == before
        later = await _plan(rows, now=MORNING + timedelta(days=1))
        assert [k for k in later if k.startswith("jev_ask:")] == [
            f"jev_ask:guardrail.injection@1:web_excerpt:{'a1' * 32}:2026-09-29"
        ]

    async def test_the_areas_are_read_by_their_own_reader(self, queue: Queue) -> None:
        conn = _Conn(_switches(**ASKS_ON))
        await jev_plan.plan(conn, now=MORNING, key_available=True)
        assert {AREA_GUARDRAILS, AREA_RESEARCH} <= set(conn.asked)


# ---------------------------------------------------------------------------
# Phase D1: the detail switch gates planning
# ---------------------------------------------------------------------------


class _DetailState(BaseModel):
    """A title and the detail behind it: more of this system's own text."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    title: str
    detail: str


#: A test-only set declaring ``internal_detail``: no registered set declares
#: it until phase D3's ``ops.job_error``.
DETAILED = jev_questions.QuestionSet(
    name="guardrail.detail_example",
    version=1,
    lane="guardrail",
    provenance="model",
    questions=(
        ("claims", {"type": "noul", "instructions": "Does `detail` claim a result?"}),
    ),
    state_model=_DetailState,
    purpose="test only: a set declaring internal_detail",
    internal_detail=True,
)

#: Its one subject, and the plans in force it is planned under.
DETAIL_SUBJECT = ("d4" * 32, "H-0042", True)
DETAIL_PLANS = {
    "plan_version": jev_prereg.PLAN_VERSION,
    "plan_hash": jev_prereg.GOLDEN_PLAN_HASH,
    "set_plan_version": 1,
    "set_plan_hash": "e" * 64,
}


@pytest.fixture
def detailed(monkeypatch: pytest.MonkeyPatch, queue: Queue) -> list[str]:
    """
    :data:`DETAILED` registered, given a subject type, planned at most five a
    pass, with plans in force and one subject waiting. Returns the names of the
    sets whose subjects were read, which is how a test sees that the planner
    stopped before reading any.
    """
    reads: list[str] = []
    monkeypatch.setitem(jev_questions.REGISTRY, DETAILED.name, DETAILED)
    monkeypatch.setattr(
        jev_questions,
        "STATE_SUBJECT",
        MappingProxyType(
            {**jev_questions.STATE_SUBJECT, _DetailState: "hypothesis_title"}
        ),
    )
    monkeypatch.setattr(
        jev_plan,
        "ASKS_PER_PASS",
        MappingProxyType({**jev_plan.ASKS_PER_PASS, DETAILED.name: 5}),
    )
    in_force = jev_prereg.plans_in_force
    monkeypatch.setattr(
        jev_prereg,
        "plans_in_force",
        lambda name, version: (
            DETAIL_PLANS if name == DETAILED.name else in_force(name, version)
        ),
    )
    subjects_of = jev_plan._ask_subjects

    async def subjects(
        conn: Any, question_set: Any, model: str, now: datetime
    ) -> list[tuple[str, object, bool]]:
        if question_set is DETAILED:
            reads.append(question_set.name)
            return [DETAIL_SUBJECT]
        return await subjects_of(conn, question_set, model, now)

    monkeypatch.setattr(jev_plan, "_ask_subjects", subjects)
    return reads


async def _plan_reading(rows: Mapping[str, str]) -> _Conn:
    """Plan once at :data:`MORNING`, and hand back what the switches read."""
    conn = _Conn(rows)
    await jev_plan.plan(conn, now=MORNING, key_available=True)
    return conn


DETAIL_ON = {flags.JEV_SEND_INTERNAL_DETAIL: "true"}


class TestTheDetailSwitchGatesPlanning:
    """
    Phase D's one general planner rule (docs/09, section 5.2): a set declaring
    ``internal_detail`` is planned only while ``jev_send_internal_detail`` is
    on, read through its own reader, as the road reads it, neither derived
    from the other — so no job is queued only to end ``disabled``. A test-only
    set stands for any set declaring it; from phase D3 the one registered set
    that does, ``ops.job_error``, is held to it as well.
    """

    async def test_off_it_is_not_planned_and_nothing_of_it_is_read(
        self, queue: Queue, detailed: list[str]
    ) -> None:
        conn = await _plan_reading(_switches(**ASKS_ON))
        assert _asks(queue, DETAILED.name) == []
        assert detailed == [], "its subjects were read with the switch off"
        assert flags.JEV_SEND_INTERNAL_DETAIL in conn.asked

    async def test_on_it_is_planned(self, queue: Queue, detailed: list[str]) -> None:
        await _plan_reading(_switches(**ASKS_ON, **DETAIL_ON))
        (job,) = _asks(queue, DETAILED.name)
        assert job["payload"]["subject_id"] == DETAIL_SUBJECT[0]
        assert job["payload"]["source_id"] == DETAIL_SUBJECT[1]
        assert detailed == [DETAILED.name]

    @pytest.mark.parametrize(
        "stored", ['"true"', "1", "false", None], ids=["string", "one", "off", "none"]
    )
    async def test_only_json_true_is_on(
        self, queue: Queue, detailed: list[str], stored: str | None
    ) -> None:
        rows = _switches(**ASKS_ON, **{flags.JEV_SEND_INTERNAL_DETAIL: stored})
        await _plan_reading(rows)
        assert _asks(queue, DETAILED.name) == []

    async def test_the_switch_does_not_stand_for_the_area(
        self, queue: Queue, detailed: list[str]
    ) -> None:
        rows = _switches(**{**ASKS_ON, **DETAIL_ON, AREA_GUARDRAILS: "false"})
        await _plan_reading(rows)
        assert _asks(queue, DETAILED.name) == []

    async def test_a_set_declaring_none_is_planned_either_way(
        self, queue: Queue, detailed: list[str]
    ) -> None:
        queue.screens = [SCREEN_SUBJECT]
        await _plan_reading(_switches(**ASKS_ON))
        assert len(_asks(queue, "guardrail.injection")) == 1
        assert _asks(queue, DETAILED.name) == []

    async def test_a_set_declaring_none_reads_no_detail_switch(
        self, queue: Queue
    ) -> None:
        """Phase C's sets declare none, so the switch is not even read for them."""
        queue.screens = [SCREEN_SUBJECT]
        queue.titles = [TITLE_SUBJECT]
        queue.canonical = [_canonical(1, _hash("00000000"))]
        conn = await _plan_reading(_switches(**{**ASKS_ON, AREA_DECISIONS: "true"}))
        assert _asks(queue)
        assert flags.JEV_SEND_INTERNAL_DETAIL not in conn.asked

    def test_the_ops_set_is_the_one_registered_set_declaring_it(self) -> None:
        declaring = {
            name
            for name, question_set in jev_questions.REGISTRY.items()
            if question_set.internal_detail
        }
        assert declaring == {"ops.job_error"}

    async def test_the_ops_set_waits_for_it(self, queue: Queue) -> None:
        """
        docs/09, section 5.2 (revised: D-SAFE-1): the ops area on and the
        detail switch off plans no ops ask and reads no failed job; switched
        on, the same pass plans it.
        """
        queue.failed = [_failed(1)]
        off = _switches(**{**OPS_ON, flags.JEV_SEND_INTERNAL_DETAIL: "false"})
        conn = await _plan_reading(off)
        assert _ops_asks(queue) == [] and queue.job_reads == []
        assert flags.JEV_SEND_INTERNAL_DETAIL in conn.asked
        await _plan_reading(_switches(**OPS_ON))
        assert len(_ops_asks(queue)) == 1

    async def test_the_forward_clock_waits_for_it_too(
        self, queue: Queue, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        The rule is the planner's, not one rule's: a regime set declaring
        ``internal_detail`` — none does — would wait for the switch as well,
        while the worker's reference bars, which ask nothing, would not.
        """
        declaring = dataclasses.replace(DECISION_REGIME, internal_detail=True)
        monkeypatch.setitem(jev_questions.REGISTRY, DECISION_REGIME.name, declaring)
        planned = await _plan()
        kinds = {queue.jobs[key]["kind"] for key in planned}
        assert "jev_regime" not in kinds
        assert "ingest_reference_bars" in kinds
        planned = await _plan(_switches(**DETAIL_ON))
        assert "jev_regime" in {queue.jobs[key]["kind"] for key in planned}

    async def test_its_reasks_wait_for_the_switch_too(
        self, queue: Queue, detailed: list[str]
    ) -> None:
        queue.canonical = [
            _canonical(
                1,
                _hash("00000000"),
                question_set=DETAILED.name,
                question_set_version=DETAILED.version,
                pack_hash=DETAILED.pack_hash,
                lane="guardrail",
                subject_type="hypothesis_title",
                subject_id=DETAIL_SUBJECT[0],
            )
        ]
        await _plan_reading(_switches(**ASKS_ON))
        assert _reasks(queue) == []
        await _plan_reading(_switches(**ASKS_ON, **DETAIL_ON))
        assert [job["payload"]["request_id"] for job in _reasks(queue)] == [1]


# ---------------------------------------------------------------------------
# Phase D2: the findings sets
# ---------------------------------------------------------------------------

#: The findings area on, and every other area the asks read off.
FINDINGS_ON = {
    AREA_DECISIONS: "false",
    AREA_RESEARCH: "false",
    AREA_GUARDRAILS: "false",
    AREA_FINDINGS: "true",
}

#: The two findings sets, in the order the planner plans them.
FINDING_SETS = ("findings.owner", "findings.severity")


def _planned_asks(queue: Queue, name: str) -> list[dict[str, Any]]:
    """The ``jev_ask`` jobs of ``name`` the planner queued, by their keys."""
    return [
        job
        for key, job in queue.jobs.items()
        if key.startswith("jev_ask:") and job["payload"]["set"] == name
    ]


def _findings(n: int) -> list[dict[str, Any]]:
    """``n`` invented finding titles, newest first, as the read returns them."""
    return [{"subject_id": f"{i:064x}", "ref": f"F-{i:04d}"} for i in range(1, n + 1)]


class TestTheFindingsRules:
    """
    Phase D2 (docs/09, section 5.2): ``findings.owner`` and
    ``findings.severity`` are planned behind the findings area and no other,
    at most ten of each a pass, each ask one call from the findings lane's
    share, under ``jev_repo.ask_job_key``, about what
    ``jev_repo.findings_to_ask`` returns and in its order — newest first —
    and nothing that would call while the vendor holds them.
    """

    def test_the_sets_are_the_findings_lanes_and_their_area_the_findings(
        self,
    ) -> None:
        for name in FINDING_SETS:
            question_set = jev_questions.REGISTRY[name]
            assert question_set.lane == "findings"
            assert jev_catalogue.LANE_AREA["findings"] == "findings"
            assert jev_plan.ASKS_PER_PASS[name] == 10
            assert name in jev_plan.FINDING_SET_NAMES
        assert jev_plan.FINDING_SET_NAMES == FINDING_SETS
        assert jev_catalogue.lane_budget(500, "findings") == 50

    async def test_each_finding_is_one_job_naming_its_ref_and_never_its_title(
        self, queue: Queue
    ) -> None:
        queue.findings = [FINDING_SUBJECT]
        planned = await _plan(_switches(**FINDINGS_ON))
        address = FINDING_SUBJECT["subject_id"]
        expected = [
            f"jev_ask:{name}@1:finding_title:{address}:2026-09-28"
            for name in FINDING_SETS
        ]
        assert [key for key in planned if key.startswith("jev_ask:")] == expected
        for key, name in zip(expected, FINDING_SETS, strict=True):
            job = queue.jobs[key]
            plans = jev_prereg.plans_in_force(name, 1)
            assert plans is not None
            assert job["kind"] == "jev_ask"
            assert job["payload"] == {
                "set": name,
                "version": 1,
                "subject_type": "finding_title",
                "subject_id": address,
                "source_id": "F-0042",
                **plans,
            }, "the plans in force are named, and nothing else is"
            assert (job["priority"], job["max_attempts"]) == (0, 3)
            assert job["scheduled_for"] == MORNING
            assert key == jev_repo.ask_job_key(
                name, 1, "finding_title", address, date(2026, 9, 28)
            )

    async def test_each_read_is_for_its_set_the_pin_today_and_the_pass_cap(
        self, queue: Queue
    ) -> None:
        await _plan(_switches(**FINDINGS_ON))
        reads = [(read["read"], read["set"].name) for read in queue.subject_reads]
        assert reads == [("findings", name) for name in FINDING_SETS]
        for read in queue.subject_reads:
            name = read["set"].name
            assert read["set"] is jev_questions.REGISTRY[name]
            assert read["model"] == MODEL
            assert read["day"] == date(2026, 9, 28)
            assert read["limit"] == 10

    async def test_the_findings_area_and_no_other(self, queue: Queue) -> None:
        """
        Behind the findings area, read through its own reader: neither the
        research area, which plans the hypothesis titles, nor the guardrails,
        which plans the card check, stands for it, and with it off not one
        finding is read.
        """
        queue.findings = [FINDING_SUBJECT]
        queue.titles = [TITLE_SUBJECT]
        conn = await _plan_reading(_switches(**ASKS_ON))
        assert AREA_FINDINGS in conn.asked
        assert {job["payload"]["set"] for job in _asks(queue)} == {
            "guardrail.card",
            "research.hypothesis",
        }
        assert "findings" not in {read["read"] for read in queue.subject_reads}

        queue.subject_reads.clear()
        await _plan_reading(_switches(**FINDINGS_ON))
        assert {read["read"] for read in queue.subject_reads} == {"findings"}
        assert {job["payload"]["set"] for job in _asks(queue)} >= set(FINDING_SETS)

    @pytest.mark.parametrize(
        "stored", ['"true"', "1", "false", None], ids=["string", "one", "off", "none"]
    )
    async def test_only_json_true_is_on(self, queue: Queue, stored: str | None) -> None:
        queue.findings = [FINDING_SUBJECT]
        await _plan(_switches(**{**FINDINGS_ON, AREA_FINDINGS: stored}))
        assert _asks(queue) == []
        assert queue.subject_reads == []

    async def test_no_more_than_ten_of_each_a_pass(self, queue: Queue) -> None:
        queue.findings = _findings(30)
        await _plan(_switches(**FINDINGS_ON))
        for name in FINDING_SETS:
            refs = [job["payload"]["source_id"] for job in _asks(queue, name)]
            assert refs == [f"F-{i:04d}" for i in range(1, 11)], "newest first"

    async def test_never_beyond_the_findings_share(self, queue: Queue) -> None:
        """
        A budget of 100 gives the findings lane 10 calls, which the owner
        set, planned first, takes whole; a budget of 50, five.
        """
        queue.findings = _findings(30)
        await _plan(_switches(**FINDINGS_ON, **{flags.JEV_DAILY_REQUEST_BUDGET: "100"}))
        assert len(_asks(queue, "findings.owner")) == 10
        assert _asks(queue, "findings.severity") == []

    async def test_the_share_is_the_findings_lanes_and_no_others(
        self, queue: Queue
    ) -> None:
        """
        Calls the research and guardrail lanes made today take nothing from
        the findings lane; its own do, and a budget of 50 leaves it five.
        """
        queue.findings = _findings(30)
        queue.calls_today.update({"research": 12, "guardrail": 12, "findings": 3})
        await _plan(_switches(**FINDINGS_ON, **{flags.JEV_DAILY_REQUEST_BUDGET: "50"}))
        assert len(_asks(queue, "findings.owner")) == 2
        assert _asks(queue, "findings.severity") == []

    async def test_asks_already_waiting_count_against_the_findings_share(
        self, queue: Queue
    ) -> None:
        """
        A severity ask waiting from an earlier pass, and an owner ask running,
        hold two of the five calls a budget of 50 gives the lane, leaving the
        owner set, planned first, three; finished ones hold none, and a
        waiting card check is the guardrail lane's.
        """
        waiting = [
            ("running", "findings.owner"),
            ("queued", "findings.severity"),
            ("succeeded", "findings.owner"),
            ("failed", "findings.severity"),
            ("queued", "guardrail.card"),
        ]
        for n, (status, name) in enumerate(waiting):
            queue.jobs[f"elsewhere:{n}"] = {
                "kind": "jev_ask",
                "status": status,
                "payload": {"set": name},
            }
        queue.findings = _findings(30)
        await _plan(_switches(**FINDINGS_ON, **{flags.JEV_DAILY_REQUEST_BUDGET: "50"}))
        assert len(_planned_asks(queue, "findings.owner")) == 3
        assert _planned_asks(queue, "findings.severity") == []

    async def test_one_job_per_address(self, queue: Queue) -> None:
        """
        A title is asked about by its address, once a set a day: two rows
        naming one address — the read returns each once, newest first — make
        one job, keyed by the address and never by the finding.
        """
        address = "e5" * 32
        queue.findings = [
            {"subject_id": address, "ref": "F-0009"},
            {"subject_id": address, "ref": "F-0003"},
        ]
        planned = await _plan(_switches(**FINDINGS_ON))
        for name in FINDING_SETS:
            (job,) = _asks(queue, name)
            assert job["payload"]["source_id"] == "F-0009"
        assert len([key for key in planned if key.startswith("jev_ask:")]) == 2

    async def test_planning_again_the_same_day_adds_nothing(self, queue: Queue) -> None:
        queue.findings = [FINDING_SUBJECT]
        rows = _switches(**FINDINGS_ON)
        await _plan(rows)
        before = dict(queue.jobs)
        assert [k for k in await _plan(rows) if k.startswith("jev_ask:")] == []
        assert queue.jobs == before

    async def test_nothing_is_planned_while_an_authentication_failure_holds(
        self, queue: Queue
    ) -> None:
        """Every findings ask would call, so none is planned, nor its read made."""
        queue.auth_held = True
        queue.findings = [FINDING_SUBJECT]
        planned = await _plan(_switches(**FINDINGS_ON))
        assert _asks(queue) == []
        assert queue.subject_reads == []
        assert "jev_probe:2026-09-28" in planned

    async def test_a_set_the_vendor_refused_is_not_asked(self, queue: Queue) -> None:
        queue.refused_sets = {"findings.owner"}
        queue.findings = [FINDING_SUBJECT]
        await _plan(_switches(**FINDINGS_ON))
        assert _asks(queue, "findings.owner") == []
        assert len(_asks(queue, "findings.severity")) == 1
        assert [read["set"].name for read in queue.subject_reads] == [
            "findings.severity"
        ]

    async def test_a_set_with_no_plan_is_planned_nothing(
        self, queue: Queue, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real = jev_prereg.plans_in_force

        def only_severity(name: str, version: int) -> dict[str, Any] | None:
            return real(name, version) if name == "findings.severity" else None

        monkeypatch.setattr(jev_prereg, "plans_in_force", only_severity)
        queue.findings = [FINDING_SUBJECT]
        await _plan(_switches(**FINDINGS_ON))
        assert {job["payload"]["set"] for job in _asks(queue)} == {"findings.severity"}

    async def test_the_detail_switch_is_not_read_for_them(self, queue: Queue) -> None:
        """Neither set declares ``internal_detail``: a title is all it sends."""
        queue.findings = [FINDING_SUBJECT]
        conn = await _plan_reading(_switches(**FINDINGS_ON))
        assert len(_asks(queue)) == 2
        assert flags.JEV_SEND_INTERNAL_DETAIL not in conn.asked
        for name in FINDING_SETS:
            assert jev_questions.REGISTRY[name].internal_detail is False

    async def test_a_findings_answer_is_reasked_behind_the_findings_area(
        self, queue: Queue
    ) -> None:
        """
        The re-ask sample draws from every canonical answer, so a findings
        set's answer is re-asked, as a probe, only while the findings area is
        on.
        """
        owner = jev_questions.REGISTRY["findings.owner"]
        queue.canonical = [
            _canonical(
                1,
                _hash("00000000"),
                question_set=owner.name,
                question_set_version=owner.version,
                pack_hash=owner.pack_hash,
                lane="findings",
                subject_type="finding_title",
                subject_id=FINDING_SUBJECT["subject_id"],
            )
        ]
        await _plan(_switches(**{**FINDINGS_ON, AREA_FINDINGS: "false"}))
        assert _reasks(queue) == []
        await _plan(_switches(**FINDINGS_ON))
        assert [job["payload"]["request_id"] for job in _reasks(queue)] == [1]


# ---------------------------------------------------------------------------
# Phase D3: the ops set
# ---------------------------------------------------------------------------

#: The ops area and the detail switch on, and every other area the asks read
#: off.
OPS_ON = {
    AREA_DECISIONS: "false",
    AREA_RESEARCH: "false",
    AREA_GUARDRAILS: "false",
    AREA_FINDINGS: "false",
    AREA_OPS: "true",
    flags.JEV_SEND_INTERNAL_DETAIL: "true",
}

#: Where the window starts at :data:`MORNING`: the midnight after the pin was
#: first observed, later than a week before.
OPS_SINCE = datetime(2026, 9, 27, 0, 0, tzinfo=UTC)


def _ops_asks(queue: Queue) -> list[dict[str, Any]]:
    return _planned_asks(queue, "ops.job_error")


def _state_of(job: Mapping[str, Any]) -> jev_questions.JobErrorState:
    tokens = jev_redact.skeleton(job["error"])
    return jev_questions.JobErrorState(job_kind=job["kind"], error=tokens)


def _address_of(job: Mapping[str, Any]) -> str:
    return jev_questions.job_error_subject(_state_of(job))


class TestTheOpsRule:
    """
    Phase D3 (docs/09, section 5.2): ``ops.job_error`` is planned behind the
    ops area and the detail switch together, each read through its own
    reader, at most ten a pass, each ask one call from the ops lane's share,
    under ``jev_repo.ask_job_key``; about each skeleton of a failed job of a
    triaged kind within the window whose error code leaves to Jev, newest
    first, once each, naming its newest job by id; never a job's error, in a
    payload, a key or a log.
    """

    def test_the_set_is_the_ops_lanes_and_its_area_the_ops(self) -> None:
        question_set = jev_questions.REGISTRY["ops.job_error"]
        assert question_set.lane == "ops"
        assert jev_catalogue.LANE_AREA["ops"] == "ops"
        assert question_set.internal_detail is True
        assert jev_plan.ASKS_PER_PASS["ops.job_error"] == 10
        assert jev_plan.OPS_SET_NAME == "ops.job_error"
        assert jev_plan.OPS_WINDOW == timedelta(days=7)
        assert jev_catalogue.lane_budget(500, "ops") == 50

    async def test_each_skeleton_is_one_job_naming_its_job_and_never_its_error(
        self, queue: Queue
    ) -> None:
        job = _failed(1)
        queue.failed = [job]
        planned = await _plan(_switches(**OPS_ON))
        address = _address_of(job)
        key = f"jev_ask:ops.job_error@1:job_error:{address}:2026-09-28"
        assert [k for k in planned if k.startswith("jev_ask:")] == [key]
        plans = jev_prereg.plans_in_force("ops.job_error", 1)
        assert plans is not None
        (ask,) = _ops_asks(queue)
        assert ask["payload"] == {
            "set": "ops.job_error",
            "version": 1,
            "subject_type": "job_error",
            "subject_id": address,
            "source_id": str(job["id"]),
            **plans,
        }, "the plans in force are named, and nothing else is"
        assert (ask["priority"], ask["max_attempts"]) == (0, 3)
        assert ask["scheduled_for"] == MORNING
        assert key == jev_repo.ask_job_key(
            "ops.job_error", 1, "job_error", address, date(2026, 9, 28)
        )
        stored = json.dumps([queue.jobs, planned], default=str)
        assert CANARY not in stored and "Connection" not in stored

    @pytest.mark.parametrize(
        ("ops", "detail"),
        [("true", "false"), ("false", "true"), ("false", "false"), (None, None)],
        ids=["ops-alone", "detail-alone", "neither", "unset"],
    )
    async def test_it_needs_the_ops_area_and_the_detail_switch(
        self, queue: Queue, ops: str | None, detail: str | None
    ) -> None:
        """
        The detail switch is not the area, nor the area the switch: with
        either off, nothing of the ops set is planned and no failed job is
        read at all.
        """
        queue.failed = [_failed(1)]
        rows = _switches(
            **{**OPS_ON, AREA_OPS: ops, flags.JEV_SEND_INTERNAL_DETAIL: detail}
        )
        conn = await _plan_reading(rows)
        assert _ops_asks(queue) == []
        assert queue.job_reads == [] and queue.subject_reads == []
        assert AREA_OPS in conn.asked

    @pytest.mark.parametrize(
        "stored", ['"true"', "1", "false", None], ids=["string", "one", "off", "none"]
    )
    @pytest.mark.parametrize("switch", [AREA_OPS, flags.JEV_SEND_INTERNAL_DETAIL])
    async def test_only_json_true_is_on(
        self, queue: Queue, switch: str, stored: str | None
    ) -> None:
        queue.failed = [_failed(1)]
        await _plan(_switches(**{**OPS_ON, switch: stored}))
        assert _ops_asks(queue) == []
        assert queue.job_reads == []

    async def test_each_switch_is_read_by_its_own_reader(self, queue: Queue) -> None:
        queue.failed = [_failed(1)]
        conn = await _plan_reading(_switches(**OPS_ON))
        assert len(_ops_asks(queue)) == 1
        assert AREA_OPS in conn.asked
        assert flags.JEV_SEND_INTERNAL_DETAIL in conn.asked
        assert conn.asked.index(AREA_OPS) < conn.asked.index(
            flags.JEV_SEND_INTERNAL_DETAIL
        ), "the detail switch is read for the ops set, after its area"

    async def test_the_read_is_the_triaged_kinds_since_the_later_bound(
        self, queue: Queue
    ) -> None:
        """
        A week before ``now``, or the midnight after the pin was first
        observed, whichever is later: at :data:`MORNING` the pin's, three
        weeks on the week's.
        """
        await _plan(_switches(**OPS_ON))
        (read,) = queue.job_reads
        assert read["kinds"] == jev_redact.TRIAGED_KINDS
        assert read["since"] == OPS_SINCE == jev_repo.job_error_since(MODEL)
        queue.job_reads.clear()
        later = datetime(2026, 10, 19, 14, 0, tzinfo=UTC)
        await _plan(_switches(**OPS_ON), now=later)
        (read,) = queue.job_reads
        assert read["since"] == later - timedelta(days=7)

    async def test_a_job_before_the_window_is_never_asked_about(
        self, queue: Queue
    ) -> None:
        queue.failed = [
            _failed(1, finished_at=OPS_SINCE),
            _failed(2, finished_at=OPS_SINCE + timedelta(seconds=1)),
        ]
        await _plan(_switches(**OPS_ON))
        assert [ask["payload"]["source_id"] for ask in _ops_asks(queue)] == [
            str(_job_id(2))
        ]

    @pytest.mark.parametrize(
        ("kind", "error"),
        [
            ("backtest", f"unknown data source '{CANARY}'"),
            ("ingest_bars", f"division by zero {CANARY}"),
            ("ingest_bars", None),
            ("ingest_bars", ""),
            ("backtest", "lease expired; worker presumed dead"),
        ],
        ids=["placed-by-code", "too-few-words", "no-error", "empty", "lease"],
    )
    async def test_only_the_residue_is_asked_about(
        self, queue: Queue, kind: str, error: str | None
    ) -> None:
        """
        What code places, and what reduces to too few words, is never planned:
        the planner reads a job's error by the handler's own rule
        (``jev_chips.residue_skeleton``), so no job is queued only to be
        refused.
        """
        assert jev_chips.residue_skeleton(kind, error) is None
        queue.failed = [_failed(1, kind=kind, error=error), _failed(2)]
        await _plan(_switches(**OPS_ON))
        assert [ask["payload"]["source_id"] for ask in _ops_asks(queue)] == [
            str(_job_id(2))
        ]

    async def test_one_job_per_address_naming_the_newest(self, queue: Queue) -> None:
        """
        Two jobs whose errors differ only in what the redactor takes out make
        one skeleton, asked about once, by its address, naming the newer job.
        """
        older = _failed(1, error=f"[Errno 104] Connection refused {CANARY}a")
        newer = _failed(2, error=f"[Errno 111] Connection refused {CANARY}b")
        newer["finished_at"] = older["finished_at"] + timedelta(minutes=5)
        assert _address_of(older) == _address_of(newer)
        queue.failed = [older, newer]
        await _plan(_switches(**OPS_ON))
        (ask,) = _ops_asks(queue)
        assert ask["payload"]["source_id"] == str(newer["id"])
        assert ask["payload"]["subject_id"] == _address_of(newer)

    async def test_newest_first_and_no_more_than_ten_a_pass(self, queue: Queue) -> None:
        queue.failed = [_failed(i) for i in range(1, 31)]
        await _plan(_switches(**OPS_ON))
        assert [ask["payload"]["source_id"] for ask in _ops_asks(queue)] == [
            str(_job_id(i)) for i in range(1, 11)
        ], "newest first"
        (read,) = [r for r in queue.subject_reads if r["read"] == "unasked"]
        assert read["subjects"] == [_address_of(_failed(i)) for i in range(1, 31)]

    async def test_what_the_unasked_read_leaves_out_is_not_planned(
        self, queue: Queue
    ) -> None:
        """
        ``jev_repo.unasked_subjects`` is asked about every address, for the
        registered set under the pin today, and only what it keeps is
        planned, in its order: an answer on record, a retired subject and one
        already waiting or planned today are its to leave out.
        """
        queue.failed = [_failed(i) for i in range(1, 4)]
        queue.asked_addresses = {_address_of(_failed(2))}
        await _plan(_switches(**OPS_ON))
        assert [ask["payload"]["source_id"] for ask in _ops_asks(queue)] == [
            str(_job_id(1)),
            str(_job_id(3)),
        ]
        (read,) = queue.subject_reads
        assert read["set"] is jev_questions.REGISTRY["ops.job_error"]
        assert read["model"] == MODEL
        assert read["subject_type"] == "job_error"
        assert read["day"] == date(2026, 9, 28)

    async def test_with_no_residue_no_unasked_read_is_made(self, queue: Queue) -> None:
        queue.failed = [_failed(1, error="division by zero")]
        await _plan(_switches(**OPS_ON))
        assert len(queue.job_reads) == 1
        assert queue.subject_reads == []
        assert _ops_asks(queue) == []

    async def test_never_beyond_the_ops_share(self, queue: Queue) -> None:
        """A budget of 50 gives the ops lane five calls."""
        assert jev_catalogue.lane_budget(50, "ops") == 5
        queue.failed = [_failed(i) for i in range(1, 31)]
        await _plan(_switches(**OPS_ON, **{flags.JEV_DAILY_REQUEST_BUDGET: "50"}))
        assert len(_ops_asks(queue)) == 5

    async def test_the_share_is_the_ops_lanes_and_no_others(self, queue: Queue) -> None:
        queue.failed = [_failed(i) for i in range(1, 31)]
        queue.calls_today.update({"findings": 5, "research": 12, "ops": 3})
        await _plan(_switches(**OPS_ON, **{flags.JEV_DAILY_REQUEST_BUDGET: "50"}))
        assert len(_ops_asks(queue)) == 2

    async def test_asks_already_waiting_count_against_the_ops_share(
        self, queue: Queue
    ) -> None:
        waiting = [
            ("running", "ops.job_error"),
            ("queued", "ops.job_error"),
            ("succeeded", "ops.job_error"),
            ("failed", "ops.job_error"),
            ("queued", "findings.owner"),
        ]
        for n, (status, name) in enumerate(waiting):
            queue.jobs[f"elsewhere:{n}"] = {
                "kind": "jev_ask",
                "status": status,
                "payload": {"set": name},
            }
        queue.failed = [_failed(i) for i in range(1, 31)]
        await _plan(_switches(**OPS_ON, **{flags.JEV_DAILY_REQUEST_BUDGET: "50"}))
        assert len(_ops_asks(queue)) == 3

    async def test_planning_again_the_same_day_adds_nothing(self, queue: Queue) -> None:
        queue.failed = [_failed(1)]
        rows = _switches(**OPS_ON)
        await _plan(rows)
        before = dict(queue.jobs)
        assert [k for k in await _plan(rows) if k.startswith("jev_ask:")] == []
        assert queue.jobs == before

    async def test_nothing_is_planned_while_an_authentication_failure_holds(
        self, queue: Queue
    ) -> None:
        """Every ops ask would call, so none is planned, nor a failed job read."""
        queue.auth_held = True
        queue.failed = [_failed(1)]
        planned = await _plan(_switches(**OPS_ON))
        assert _ops_asks(queue) == []
        assert queue.job_reads == []
        assert "jev_probe:2026-09-28" in planned

    async def test_a_set_the_vendor_refused_is_not_asked(self, queue: Queue) -> None:
        queue.refused_sets = {"ops.job_error"}
        queue.failed = [_failed(1)]
        await _plan(_switches(**OPS_ON))
        assert _ops_asks(queue) == []
        assert queue.job_reads == []

    async def test_a_set_with_no_plan_is_planned_nothing(
        self, queue: Queue, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real = jev_prereg.plans_in_force

        def no_ops_plan(name: str, version: int) -> dict[str, Any] | None:
            return None if name == "ops.job_error" else real(name, version)

        monkeypatch.setattr(jev_prereg, "plans_in_force", no_ops_plan)
        queue.failed = [_failed(1)]
        await _plan(_switches(**OPS_ON))
        assert _ops_asks(queue) == []
        assert queue.job_reads == []

    async def test_a_row_that_cannot_be_read_is_passed_over_by_class_and_id(
        self,
        queue: Queue,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """
        A defect on one row holds no other, and is logged by the exception's
        class and the job's id alone: never the error, nor the exception's
        message, which may quote it.
        """
        real = jev_chips.residue_skeleton
        broken = _failed(2)

        def residue(kind: object, error: object) -> Any:
            if error == broken["error"]:
                raise ValueError(f"cannot read {error!r}")
            return real(kind, error)

        monkeypatch.setattr(jev_chips, "residue_skeleton", residue)
        queue.failed = [_failed(1), broken, _failed(3)]
        caplog.set_level(logging.DEBUG)
        await _plan(_switches(**OPS_ON))
        assert [ask["payload"]["source_id"] for ask in _ops_asks(queue)] == [
            str(_job_id(1)),
            str(_job_id(3)),
        ]
        (record,) = [r for r in caplog.records if "passed over" in r.getMessage()]
        assert str(broken["id"]) in record.getMessage()
        assert "ValueError" in record.getMessage()
        assert CANARY not in record.getMessage() and "cannot read" not in (
            record.getMessage()
        )

    async def test_the_planner_logs_no_text(
        self, queue: Queue, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        docs/09, section 13 (D3): planning ops at DEBUG, every logger
        captured, quotes no job's error and none of its words: only keys,
        whose subjects are addresses.
        """
        queue.failed = [_failed(i) for i in range(1, 13)]
        queue.failed.append(_failed(13, kind="backtest", error=f"no {CANARY} data"))
        caplog.set_level(logging.DEBUG)
        planned = await _plan(_switches(**OPS_ON))
        assert len(_ops_asks(queue)) == 10
        logged = "\n".join(
            [record.getMessage() for record in caplog.records]
            + [repr(record.args) for record in caplog.records]
        )
        assert planned and any(key in logged for key in planned)
        assert CANARY not in logged
        for word in ("Errno", "Connection", "refused", "while"):
            assert word not in logged, word

    async def test_an_ops_answer_is_reasked_behind_the_ops_area_and_the_detail(
        self, queue: Queue
    ) -> None:
        """
        A re-ask resends the skeleton on record, so it waits for both
        switches as the ask did.
        """
        ops = jev_questions.REGISTRY["ops.job_error"]
        queue.canonical = [
            _canonical(
                1,
                _hash("00000000"),
                question_set=ops.name,
                question_set_version=ops.version,
                pack_hash=ops.pack_hash,
                lane="ops",
                subject_type="job_error",
                subject_id=_address_of(_failed(1)),
            )
        ]
        for off in (AREA_OPS, flags.JEV_SEND_INTERNAL_DETAIL):
            await _plan(_switches(**{**OPS_ON, off: "false"}))
            assert _reasks(queue) == [], off
        await _plan(_switches(**OPS_ON))
        assert [job["payload"]["request_id"] for job in _reasks(queue)] == [1]


#: Every switch the matrix sets, as phase D reads them, and the key: the
#: master switch, Jev's, the findings, ops and guardrails areas, the arming
#: switch and the detail switch (docs/09, section 13; D4 builds the rest of
#: the matrix's expectations on this one).
MATRIX = (
    flags.PROGRAMME_ENABLED,
    flags.JEV_ENABLED,
    AREA_FINDINGS,
    AREA_OPS,
    AREA_GUARDRAILS,
    flags.JEV_ARM_CARD_CHECK,
    flags.JEV_SEND_INTERNAL_DETAIL,
)


class TestTheSwitchMatrix:
    """
    docs/09, section 13 (D4, built up from D2): programme, Jev, findings, ops,
    guardrails, arm and detail, each on or off, with a key or without — all
    256 cases — and a subject waiting for every set. Each rule is planned
    exactly when its conjunction holds: the probe on programme, Jev and a key;
    the guardrail sets on those and the guardrails area; the findings sets on
    those and the findings area; and from phase D3 the ops set on those, the
    ops area and the detail switch together, so the ops area on with the
    detail switch off plans nothing and reads no failed job (revised:
    D-SAFE-1). Until D4 the arming switch has no consumer, so it plans nothing
    of its own, alone or with anything else, and neither does the detail
    switch without the ops area. The research and decisions areas stay off,
    which :class:`TestItIsDark` covers.
    """

    @pytest.mark.parametrize(
        ("switches", "key"),
        [
            (dict(zip(MATRIX, values[:-1], strict=True)), values[-1])
            for values in itertools.product([True, False], repeat=len(MATRIX) + 1)
        ],
    )
    async def test_each_rule_is_planned_exactly_when_its_conjunction_holds(
        self, queue: Queue, switches: dict[str, bool], key: bool
    ) -> None:
        queue.screens = [SCREEN_SUBJECT]
        queue.titles = [TITLE_SUBJECT]
        queue.findings = [FINDING_SUBJECT]
        queue.failed = [_failed(1)]
        rows = _switches(
            **{AREA_DECISIONS: "false", AREA_RESEARCH: "false"},
            **{name: "true" if on else "false" for name, on in switches.items()},
        )
        planned = await _plan(rows, key=key)
        open_ = (
            switches[flags.PROGRAMME_ENABLED] and switches[flags.JEV_ENABLED] and key
        )
        if not open_:
            assert planned == [] and queue.jobs == {}
            assert queue.subject_reads == []
            return
        expected = {"jev_probe:2026-09-28"}
        sets: set[str] = set()
        if switches[AREA_GUARDRAILS]:
            sets |= {"guardrail.injection", "guardrail.card"}
        if switches[AREA_FINDINGS]:
            sets |= set(FINDING_SETS)
        ops = switches[AREA_OPS] and switches[flags.JEV_SEND_INTERNAL_DETAIL]
        if ops:
            sets.add("ops.job_error")
        assert {k for k in planned if not k.startswith("jev_ask:")} == expected
        assert {job["payload"]["set"] for job in _asks(queue)} == sets
        assert {read["set"].name for read in queue.subject_reads} == sets
        assert bool(queue.job_reads) is ops, "a failed job read without both"
