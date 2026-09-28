"""
test_jev_clock.py
-----------------
When the forward clock runs, what it records a session under, and when the
processes that run it restart.

The cutoff is the property everything else stands on. A signal is live when
the database stamped it before the session's decision cutoff, and the cutoff
is the moment the worker's live decision reads the day's close
(``scheduler.DECIDE_AFTER_CLOSE``). The programme may not import the engine, so
``jev_clock`` restates the constant, and these hold the two together for every
session the calendar holds: a cutoff that drifted from the decision would call
live an answer the decision could not have read. The reference bars' time is
held to the live ingest's the same way, and to the window the worker's
reference job refuses to run outside.

The restarts are here because they bound the clock from the other side: a
process restarting between a close and its cutoff misses the session for good.
Both scheduled workflows stop each run at a fixed slot, and the slots are held
clear of every session's working hour after its close, in summer and in winter,
on a half day, and around the open. The step's own arithmetic is run, by bash,
for a run starting at every minute of a day. And since a restart is only as
short as the wait for its successor, GitHub's schedule and the workflows'
concurrency group are modelled, the schedule late, erratic or losing an event:
every stop must find its successor already queued.
"""

from __future__ import annotations

import functools
import os
import random
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pytest
import yaml

from src.core import calendar
from src.data.reference import REFERENCE_SLEEVES
from src.engine import scheduler
from src.engine.scheduler import JobKind
from src.programme import jev_clock
from src.programme.jev_questions import DECISION_REGIME, SLEEVES
from src.programme.main import JEV_HANDLERS
from src.worker.main import HANDLERS
from src.worker.maintenance_jobs import reference_window
from src.worker.scheduling import dedupe_key

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
NEW_YORK = jev_clock.EXCHANGE_TZ


def _sessions(start: date | None = None) -> list[date]:
    first, last = calendar.bounds()
    return calendar.sessions(start or first, last)


# ---------------------------------------------------------------------------
# The three times
# ---------------------------------------------------------------------------


class TestTheTimes:
    def test_the_cutoff_is_the_workers_decision_time(self) -> None:
        """
        For every session the calendar holds: the close plus the worker's own
        decision delay, on the session's own day in New York, which is what
        ``jev_signals_cutoff_is_on_its_session`` requires of every row.
        """
        assert jev_clock.DECISION_AFTER_CLOSE == scheduler.DECIDE_AFTER_CLOSE
        for session in _sessions():
            cutoff = jev_clock.decision_cutoff(session)
            assert cutoff == calendar.session_close(session) + (
                scheduler.DECIDE_AFTER_CLOSE
            )
            assert cutoff.astimezone(NEW_YORK).date() == session, session

    def test_it_is_when_the_live_decision_is_planned(self) -> None:
        """The scheduler's own plan, for the sessions around today."""
        for session in _sessions(date.today() - timedelta(days=400)):
            (decision,) = [
                job
                for job in scheduler.plan_session(session)
                if job.kind is JobKind.LIVE_DECISION
            ]
            assert decision.run_at == jev_clock.decision_cutoff(session)

    def test_reference_time_is_the_ingest_time(self) -> None:
        """
        The reference bars are fetched when the live ingest fetches the same
        bars, the minute the worker's reference job first agrees to run.
        """
        assert jev_clock.REFERENCE_AFTER_CLOSE == scheduler.INGEST_AFTER_CLOSE
        for session in _sessions(date.today() - timedelta(days=400)):
            opens, _ = reference_window(session)
            assert jev_clock.reference_at(session) == opens

    def test_reference_before_collect_before_cutoff(self) -> None:
        assert (
            timedelta(0)
            < jev_clock.REFERENCE_AFTER_CLOSE
            < jev_clock.COLLECT_AFTER_CLOSE
            < jev_clock.DECISION_AFTER_CLOSE
        )
        session = date(2026, 11, 27)  # a half day: closes 13:00 in New York
        assert (
            jev_clock.reference_at(session)
            < jev_clock.collect_at(session)
            < jev_clock.decision_cutoff(session)
        )
        assert jev_clock.decision_cutoff(session).astimezone(NEW_YORK).hour == 14

    @pytest.mark.parametrize(
        ("session", "hour"),
        [
            (date(2026, 9, 28), 17),  # an ordinary day: 17:00 in New York
            (date(2026, 11, 27), 14),  # the day after Thanksgiving: a half day
            (date(2026, 3, 9), 17),  # the Monday after the clocks go forward
            (date(2026, 11, 2), 17),  # the Monday after they go back
        ],
    )
    def test_the_cutoff_in_new_york(self, session: date, hour: int) -> None:
        cutoff = jev_clock.decision_cutoff(session).astimezone(NEW_YORK)
        assert (cutoff.date(), cutoff.hour, cutoff.minute) == (session, hour, 0)

    def test_a_regime_state_describes_the_close(self) -> None:
        session = date(2026, 9, 28)
        assert jev_clock.regime_as_of(session) == calendar.session_close(session)


# ---------------------------------------------------------------------------
# Which sessions are planned
# ---------------------------------------------------------------------------


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


class TestSessionsToPlan:
    @pytest.mark.parametrize(
        ("now", "expected"),
        [
            pytest.param(
                "2026-09-28 14:00", ["2026-09-28", "2026-09-29"], id="ordinary-day"
            ),
            pytest.param(
                "2026-09-28 20:59", ["2026-09-28", "2026-09-29"], id="before-cutoff"
            ),
            pytest.param("2026-09-28 21:00", ["2026-09-29"], id="at-the-cutoff"),
            pytest.param("2026-09-28 23:30", ["2026-09-29"], id="after-the-cutoff"),
            pytest.param(
                "2026-11-27 18:30", ["2026-11-27", "2026-11-30"], id="half-day"
            ),
            pytest.param("2026-11-27 19:00", ["2026-11-30"], id="half-day-cutoff"),
            pytest.param(
                "2026-03-09 20:30", ["2026-03-09", "2026-03-10"], id="clocks-forward"
            ),
            pytest.param("2026-03-09 21:00", ["2026-03-10"], id="forward-cutoff"),
            pytest.param(
                "2026-11-02 21:30", ["2026-11-02", "2026-11-03"], id="clocks-back"
            ),
            pytest.param("2026-11-02 22:00", ["2026-11-03"], id="back-cutoff"),
            pytest.param("2026-09-26 12:00", ["2026-09-28"], id="saturday"),
            pytest.param("2026-11-26 15:00", ["2026-11-27"], id="thanksgiving"),
            pytest.param(
                # 01:00 UTC on Tuesday is Monday evening in New York, past
                # Monday's cutoff.
                "2026-09-29 01:00",
                ["2026-09-29"],
                id="new-york-evening",
            ),
        ],
    )
    def test_today_while_its_cutoff_is_ahead_and_the_next(
        self, now: str, expected: list[str]
    ) -> None:
        planned = jev_clock.sessions_to_plan(_utc(now))
        assert [session.isoformat() for session in planned] == expected

    def test_never_a_past_session(self) -> None:
        now = _utc("2026-09-28 14:00")
        for hours in range(0, 24 * 21, 7):
            moment = now + timedelta(hours=hours)
            for session in jev_clock.sessions_to_plan(moment):
                assert jev_clock.decision_cutoff(session) > moment

    def test_nothing_past_the_calendars_end(self) -> None:
        _, last = calendar.bounds()
        close = calendar.session_close(last)
        assert jev_clock.sessions_to_plan(close) == [last]
        assert jev_clock.sessions_to_plan(close + timedelta(hours=2)) == []
        assert jev_clock.sessions_to_plan(close + timedelta(days=3)) == []

    def test_a_naive_time_is_refused(self) -> None:
        with pytest.raises(ValueError):
            jev_clock.sessions_to_plan(datetime(2026, 9, 28, 14))


# ---------------------------------------------------------------------------
# The names
# ---------------------------------------------------------------------------


class TestTheNames:
    def test_the_signal_is_the_set_its_version_and_its_question(self) -> None:
        assert jev_clock.regime_signal(DECISION_REGIME, "regime") == (
            "decision.regime@1:regime"
        )

    def test_the_symbol_is_the_sleeves_in_the_states_order(self) -> None:
        assert jev_clock.sleeve_symbol() == "equities=SPY;bonds=IEF;commodities=GSG"
        assert list(REFERENCE_SLEEVES) == list(SLEEVES)
        moved = {**REFERENCE_SLEEVES, "bonds": "TLT"}
        assert jev_clock.sleeve_symbol(moved) != jev_clock.sleeve_symbol()

    def test_a_sleeve_map_that_is_not_the_states_is_refused(self) -> None:
        with pytest.raises(ValueError):
            jev_clock.sleeve_symbol({"equities": "SPY", "bonds": "IEF"})

    def test_the_job_keys(self) -> None:
        session = date(2026, 9, 28)
        assert jev_clock.regime_job_key(DECISION_REGIME, session) == (
            "jev_regime:decision.regime@1:2026-09-28"
        )
        assert jev_clock.reference_job_key(session) == (
            "ingest_reference_bars:2026-09-28"
        )

    def test_the_live_ingests_key_is_the_session_planners(self) -> None:
        session = date(2026, 9, 28)
        assert jev_clock.ingest_job_key(session) == dedupe_key("ingest_bars", session)
        assert jev_clock.INGEST_KIND == JobKind.INGEST_BARS.value

    def test_each_kind_named_here_is_owned_where_it_should_be(self) -> None:
        assert jev_clock.REFERENCE_KIND in HANDLERS
        assert jev_clock.REGIME_KIND in JEV_HANDLERS
        assert jev_clock.INGEST_KIND in HANDLERS


# ---------------------------------------------------------------------------
# The restarts
# ---------------------------------------------------------------------------

#: The workflows that keep a long-lived process running, and restart it.
RESTARTING_WORKFLOWS = ("programme.yml", "worker.yml")

#: The most a run may last: GitHub's six hours less the job's own margin.
MAX_RUN = timedelta(seconds=20_700)

#: How far ahead the next slot must be before a run stops at it.
MIN_RUN = timedelta(minutes=10)

#: How long a stopped run takes to exit: ``timeout``'s ``--kill-after`` is a
#: minute, and the job's own teardown a little more.
EXIT_TAKES = timedelta(minutes=2)

#: How long a run takes from starting to its run step: a runner, a checkout,
#: an interpreter and the installs. Generous, so a slow one is covered too.
SETUP_TAKES = timedelta(minutes=5)

#: How long a restart keeps the process away when its successor was queued
#: before the stop — the predecessor's exit and the successor's setup, with
#: room to spare. The working-hours check allows this much after every slot,
#: and the chain holds every restart to it.
RESTART_TAKES = timedelta(minutes=15)

#: The first session under the daylight-saving rules in force: the working
#: hours are checked for every session from here to the calendar's end, so
#: each kind of day those rules produce — a summer half day, closing at
#: 17:00 UTC, among them — is checked whether or not the coming year has one.
DST_RULES_FROM = date(2007, 3, 12)

#: The line of the run step that reads the clock, which the tests replace.
READS_THE_CLOCK = "now=$(date -u +%s)"

#: A Monday with nothing odd about it, where the chains below start.
CHAIN_START = datetime(2026, 9, 28, 0, 0, tzinfo=UTC)


@functools.cache
def _workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text("utf-8"))


def _triggers(name: str) -> list[tuple[int, int]]:
    """Every (hour, minute) a workflow's schedule fires at, UTC, every day."""
    times: set[tuple[int, int]] = set()
    # PyYAML reads the key `on` as the boolean True.
    schedule = _workflow(name)[True]["schedule"]
    for entry in schedule:
        minute, hour, day, month, weekday = entry["cron"].split()
        assert (day, month, weekday) == ("*", "*", "*"), entry
        for h in hour.split(","):
            for m in minute.split(","):
                times.add((int(h), int(m)))
    return sorted(times)


def _run_step(name: str) -> str:
    """The step that runs the long-lived process, as the runner is handed it."""
    job = name.removesuffix(".yml")
    (run,) = [
        step["run"]
        for step in _workflow(name)["jobs"][job]["steps"]
        if "timeout --signal=TERM" in step.get("run", "")
    ]
    return run


def _stop_arithmetic(name: str) -> str:
    """
    The run step from the line after the one that reads the clock to the line
    before ``timeout``: every line that decides when the run stops, exactly as
    the runner executes them.
    """
    lines = _run_step(name).splitlines()
    assert lines.count(READS_THE_CLOCK) == 1, "the step reads the clock once"
    start = lines.index(READS_THE_CLOCK)
    (end,) = [i for i, line in enumerate(lines) if line.startswith("timeout ")]
    assert start < end
    assert '"$seconds"' in lines[end], "the step stops the process after $seconds"
    return "\n".join(lines[start + 1 : end])


def _slots(name: str) -> list[tuple[int, int]]:
    """The restart slots the run step stops at."""
    (listed,) = re.findall(r"for slot in ([0-9: ]+); do", _stop_arithmetic(name))
    return sorted(
        (int(slot.split(":")[0]), int(slot.split(":")[1])) for slot in listed.split()
    )


def _stops_in_bash(name: str, starts: Sequence[datetime], tz: str) -> list[datetime]:
    """
    Where the workflow's own run step stops a run whose step began at each of
    ``starts``: its arithmetic run by bash, the one line that reads the clock
    replaced by each start, under the time zone ``tz``.
    """
    script = "\n".join(
        [
            "set -uo pipefail",
            "stop_for() {",
            'now="$1"',
            _stop_arithmetic(name),
            'printf "%s\\n" "$seconds"',
            "}",
            'while read -r start; do stop_for "$start"; done',
        ]
    )
    out = subprocess.run(
        ["bash", "-c", script],
        input="".join(f"{int(start.timestamp())}\n" for start in starts),
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
        env={"PATH": os.environ.get("PATH", ""), "TZ": tz},
    ).stdout.split()
    assert len(out) == len(starts)
    return [
        start + timedelta(seconds=int(seconds))
        for start, seconds in zip(starts, out, strict=True)
    ]


def _stop_after(started: datetime, slots: Sequence[tuple[int, int]]) -> datetime:
    """
    The run step's rule, for the chains below: the first slot at least
    :data:`MIN_RUN` ahead, never more than :data:`MAX_RUN`.
    ``test_the_run_step_is_the_rule_the_chain_models`` holds it to the bash.
    """
    midnight = datetime.combine(started.astimezone(UTC).date(), time(), UTC)
    wait = MAX_RUN
    for day in (0, 1):
        for hour, minute in slots:
            at = midnight + timedelta(days=day, hours=hour, minutes=minute)
            if MIN_RUN <= at - started < wait:
                wait = at - started
    return started + wait


@dataclass(frozen=True)
class _Restart:
    """One stop, when the process was back, and whether a successor waited."""

    stopped: datetime
    back: datetime
    queued: bool


def _chain(
    name: str,
    *,
    delay: Callable[[datetime], timedelta | None],
    start: datetime = CHAIN_START,
    days: int = 30,
) -> list[_Restart]:
    """
    GitHub's schedule and the workflow's concurrency group, from nothing
    running at ``start``, for ``days``.

    Each trigger's event arrives ``delay(trigger)`` after its time, or never
    where that is ``None``: GitHub delays scheduled events, most at the top of
    the hour, drops some under load, and never fires one early. An event while
    a run is in progress queues a run, replacing any run already queued
    (``concurrency`` with ``cancel-in-progress: false``); a queued run starts
    when the run in progress exits; an event with nothing in progress starts a
    run at once. A run reaches its run step :data:`SETUP_TAKES` after it
    starts, stops where the step says, and exits :data:`EXIT_TAKES` later.
    """
    slots, triggers = _slots(name), _triggers(name)
    until = start + timedelta(days=days)
    events = []
    for offset in range(-1, days + 2):
        day = start.date() + timedelta(days=offset)
        for hour, minute in triggers:
            fired = datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)
            late = delay(fired)
            if late is not None and start <= fired + late < until:
                events.append(fired + late)
    events.sort()

    def begin(at: datetime) -> tuple[datetime, datetime]:
        stop = _stop_after(at + SETUP_TAKES, slots)
        return stop, stop + EXIT_TAKES

    restarts: list[_Restart] = []
    running: tuple[datetime, datetime] | None = None
    queued = False
    stopped_alone: datetime | None = None
    for event in events:
        while running is not None and running[1] <= event:
            stop, exited = running
            if queued:
                queued = False
                restarts.append(_Restart(stop, exited + SETUP_TAKES, True))
                running = begin(exited)
            else:
                running, stopped_alone = None, stop
        if running is None:
            if stopped_alone is not None:
                restarts.append(_Restart(stopped_alone, event + SETUP_TAKES, False))
                stopped_alone = None
            running = begin(event)
        else:
            queued = True
    return restarts


def _after_the_first_day(
    restarts: Sequence[_Restart], start: datetime = CHAIN_START
) -> list[_Restart]:
    """The restarts once a chain started from nothing has had a day to form."""
    return [r for r in restarts if r.stopped >= start + timedelta(days=1)]


def _waited(restarts: Sequence[_Restart]) -> list[str]:
    """Every restart that waited on the schedule, or took too long, said."""
    return [
        f"{r.stopped:%Y-%m-%d %H:%M} UTC: back at {r.back:%H:%M}"
        + ("" if r.queued else ", no successor queued")
        for r in restarts
        if not r.queued or r.back - r.stopped > RESTART_TAKES
    ]


@functools.cache
def _busy_windows() -> tuple[tuple[date, datetime, datetime], ...]:
    """
    When a restart would cost a session something, for every session from
    :data:`DST_RULES_FROM` to the calendar's end: from a quarter of an hour
    before the reconcile to a quarter after the submission around the open,
    and from a quarter of an hour before the ingest and the reference bars,
    through the regime and the cutoff, to the marks after the close.
    """
    windows = []
    for session in _sessions(DST_RULES_FROM):
        opened = calendar.session_open(session)
        closed = calendar.session_close(session)
        windows.append(
            (
                session,
                opened - scheduler.RECONCILE_BEFORE_OPEN - timedelta(minutes=15),
                opened + scheduler.SUBMIT_AFTER_OPEN + timedelta(minutes=15),
            )
        )
        windows.append(
            (
                session,
                closed + jev_clock.REFERENCE_AFTER_CLOSE - timedelta(minutes=15),
                closed + scheduler.MARKS_AFTER_CLOSE,
            )
        )
    return tuple(windows)


class TestTheRunsStopAtTheSlots:
    @pytest.mark.parametrize("name", RESTARTING_WORKFLOWS)
    def test_every_gap_between_slots_fits_one_run(self, name: str) -> None:
        """
        The run stops at the first slot at least ten minutes away, capped at
        its limit, so every gap between slots, the one across midnight
        included, must fit inside one run with that ten minutes to spare.
        """
        slots = _slots(name)
        minutes = [h * 60 + m for h, m in slots]
        gaps = [
            (minutes[(i + 1) % len(minutes)] - minutes[i]) % (24 * 60)
            for i in range(len(minutes))
        ]
        assert max(gaps) * 60 <= (MAX_RUN - MIN_RUN).total_seconds(), gaps
        # The job's own limit is above the run's and the kill that follows it.
        limit = _workflow(name)["jobs"][name.removesuffix(".yml")]["timeout-minutes"]
        assert MAX_RUN + timedelta(seconds=60) < timedelta(minutes=limit)

    @pytest.mark.parametrize("name", RESTARTING_WORKFLOWS)
    @pytest.mark.parametrize(
        ("day", "tz"),
        [
            pytest.param(date(2026, 9, 28), "UTC", id="ordinary"),
            pytest.param(date(2026, 3, 8), "America/New_York", id="clocks-forward"),
            pytest.param(date(2026, 11, 1), "America/New_York", id="clocks-back"),
            pytest.param(date(2026, 12, 31), "Asia/Kolkata", id="year-end"),
        ],
    )
    def test_the_run_step_is_the_rule_the_chain_models(
        self, name: str, day: date, tz: str
    ) -> None:
        """
        The step's own lines, run by bash for a run starting at every minute
        of the day: each stops at a slot, at least ten minutes and at most
        5h45m ahead, where :func:`_stop_after` says. Whatever the runner's
        local time zone and its daylight saving, since the slots are UTC.
        """
        slots = _slots(name)
        midnight = datetime(day.year, day.month, day.day, tzinfo=UTC)
        starts = [midnight + timedelta(minutes=m, seconds=17) for m in range(1440)]
        for start, stop in zip(starts, _stops_in_bash(name, starts, tz), strict=True):
            assert (stop.hour, stop.minute, stop.second) in {
                (h, m, 0) for h, m in slots
            }, f"{name}: a run starting at {start:%H:%M:%S} stops at {stop:%H:%M:%S}"
            assert MIN_RUN <= stop - start <= MAX_RUN, (start, stop)
            assert stop == _stop_after(start, slots), (start, stop)


class TestASuccessorIsQueuedBeforeEveryStop:
    """
    Each restart must be the queued successor starting as its predecessor
    exits, never a gap waiting on GitHub's scheduler: the schedule is late at
    the top of the hour and drops events under load, and a trigger that fires
    at the moment a run stops finds nothing running to queue behind, so every
    restart would last as long as that trigger was late.
    """

    @pytest.mark.parametrize("name", RESTARTING_WORKFLOWS)
    @pytest.mark.parametrize("minutes", [0, 1, 5, 15, 30, 40, 45, 60, 120])
    def test_whatever_the_schedule_delay(self, name: str, minutes: int) -> None:
        restarts = _after_the_first_day(
            _chain(name, delay=lambda _: timedelta(minutes=minutes))
        )
        assert len(restarts) >= 5 * 28
        assert not _waited(restarts), "\n".join(_waited(restarts)[:10])
        slots = set(_slots(name))
        assert all((r.stopped.hour, r.stopped.minute) in slots for r in restarts)

    @pytest.mark.parametrize("name", RESTARTING_WORKFLOWS)
    def test_whatever_each_event_is_delayed_by(self, name: str) -> None:
        """Every event late by its own draw from up to an hour, for sixty days."""
        draw = random.Random(20260928)
        delays: dict[datetime, timedelta] = {}

        def delay(fired: datetime) -> timedelta:
            return delays.setdefault(fired, timedelta(seconds=draw.randrange(3600)))

        restarts = _after_the_first_day(_chain(name, delay=delay, days=60))
        assert not _waited(restarts), "\n".join(_waited(restarts)[:10])

    @pytest.mark.parametrize("name", RESTARTING_WORKFLOWS)
    @pytest.mark.parametrize("minutes", [0, 20, 40])
    def test_one_lost_event_costs_no_restart(self, name: str, minutes: int) -> None:
        """
        Each event of three days lost in turn, the rest late by ``minutes``:
        a slot's other trigger stands in for the one that never came.
        """
        late = timedelta(minutes=minutes)
        lost_from = CHAIN_START + timedelta(days=2)
        candidates = [
            datetime.combine(lost_from.date() + timedelta(days=d), time(h, m), UTC)
            for d in range(3)
            for h, m in _triggers(name)
        ]
        for lost in candidates:
            restarts = _after_the_first_day(
                _chain(
                    name,
                    delay=lambda fired, lost=lost: None if fired == lost else late,
                    days=8,
                )
            )
            assert not _waited(restarts), (lost, _waited(restarts)[:5])

    @pytest.mark.parametrize("name", RESTARTING_WORKFLOWS)
    @pytest.mark.parametrize("minutes", [0, 20])
    def test_a_cold_start_forms_the_chain_within_a_day(
        self, name: str, minutes: int
    ) -> None:
        """
        From nothing running — the first deploy, or a day GitHub lost both of
        a slot's triggers — starting every seven minutes round the clock, the
        chain is queued at every stop after the first day.
        """
        for offset in range(0, 1440, 7):
            start = CHAIN_START + timedelta(minutes=offset)
            restarts = _after_the_first_day(
                _chain(
                    name,
                    delay=lambda _: timedelta(minutes=minutes),
                    start=start,
                    days=4,
                ),
                start,
            )
            assert restarts and not _waited(restarts), (start, _waited(restarts)[:5])

    @pytest.mark.parametrize("name", RESTARTING_WORKFLOWS)
    def test_no_trigger_fires_on_the_hour(self, name: str) -> None:
        """
        GitHub names the start of every hour as when scheduled events are
        likeliest to be late or dropped, and advises another minute.
        """
        assert [t for t in _triggers(name) if t[1] == 0] == []


class TestTheRestartsLandOutsideTheWorkingHours:
    """
    docs/08, review of phase C: the restarts are moved clear of the hour after
    each close, in both regimes of daylight saving, and held there.
    """

    @pytest.mark.parametrize("name", RESTARTING_WORKFLOWS)
    def test_no_restart_falls_in_a_sessions_working_hours(self, name: str) -> None:
        """
        Every session under the daylight-saving rules in force, to the
        calendar's end: no slot, and no :data:`RESTART_TAKES` after one, meets
        the hour after a close or the minutes around the open — the summer
        half days, which close at 17:00 UTC, the winter ones, and the days the
        clocks change among them.
        """
        slots = _slots(name)
        windows = _busy_windows()
        assert any(
            session.month == 7 and calendar.session_close(session).hour == 17
            for session, _, _ in windows
        ), "no summer half day was checked"
        for session, busy_from, busy_to in windows:
            for offset in (-1, 0, 1):
                day = session + timedelta(days=offset)
                for hour, minute in slots:
                    restart = datetime(
                        day.year, day.month, day.day, hour, minute, tzinfo=UTC
                    )
                    back = restart + RESTART_TAKES
                    assert back <= busy_from or restart >= busy_to, (
                        f"{name}: a restart at {restart:%H:%M} UTC on {day} "
                        f"meets {session}'s working window "
                        f"{busy_from:%H:%M}-{busy_to:%H:%M} UTC"
                    )

    @pytest.mark.parametrize("name", RESTARTING_WORKFLOWS)
    def test_the_slots_are_clear_of_the_evening_in_both_regimes(
        self, name: str
    ) -> None:
        """The review's statement of it: nothing from 20:30 to 22:15 UTC."""
        for hour, minute in _slots(name):
            assert not (20 * 60 + 30 <= hour * 60 + minute <= 22 * 60 + 15)

    def test_both_processes_restart_at_the_same_slots(self) -> None:
        """So one set of working hours, checked once, holds for both."""
        programme, worker = (_slots(name) for name in RESTARTING_WORKFLOWS)
        assert programme == worker
        assert _triggers("programme.yml") == _triggers("worker.yml")
