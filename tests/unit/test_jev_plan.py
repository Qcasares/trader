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

import inspect
import itertools
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from src.core import calendar
from src.data.reference import REFERENCE_PRIORITY
from src.db.repos import jobs as job_repo
from src.programme import (
    flags,
    jev_catalogue,
    jev_clock,
    jev_plan,
    jev_prereg,
    jev_repo,
    web_sources,
)
from src.programme.jev_questions import DECISION_REGIME
from src.worker.scheduling import PRIORITY

FLAG_QUERY = "SELECT value FROM system_flags WHERE key = $1"
MODEL = jev_catalogue.DEFAULT_MODEL
AREA_DECISIONS = f"{flags.JEV_AREA_PREFIX}decisions"
AREA_RESEARCH = f"{flags.JEV_AREA_PREFIX}research"

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
    canonical_asked: list[tuple[datetime, datetime]] = field(default_factory=list)

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
    ):
        monkeypatch.setattr(jev_repo, name, getattr(fake, name))
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
PIN = [json.dumps(MODEL), json.dumps("jev-latest"), None]
KEY = [True, False]


class TestItIsDark:
    @pytest.mark.parametrize(
        ("programme", "jev", "decisions", "research", "pin", "key"),
        list(itertools.product(PROGRAMME, JEV, DECISIONS, RESEARCH, PIN, KEY)),
    )
    async def test_nothing_unless_every_switch_the_pin_and_a_key_allow_it(
        self,
        queue: Queue,
        programme: str | None,
        jev: str | None,
        decisions: str | None,
        research: str | None,
        pin: str | None,
        key: bool,
    ) -> None:
        rows = _switches(
            **{
                flags.PROGRAMME_ENABLED: programme,
                flags.JEV_ENABLED: jev,
                AREA_DECISIONS: decisions,
                AREA_RESEARCH: research,
                flags.JEV_MODEL: pin,
            }
        )
        planned = await _plan(rows, key=key)
        open_ = programme == "true" and jev == "true" and pin == json.dumps(MODEL)
        if not (open_ and key):
            assert planned == [] and queue.jobs == {}
            return
        kinds = {queue.jobs[k]["kind"] for k in planned}
        expected = {"jev_probe"}
        if decisions == "true":
            expected |= {"ingest_reference_bars", "jev_regime"}
        if research == "true":
            expected.add("jev_web_ingest")
        assert kinds == expected, "a rule planned without its area, or not with it"

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

    async def test_planning_again_the_same_day_adds_nothing(
        self, queue: Queue
    ) -> None:
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
