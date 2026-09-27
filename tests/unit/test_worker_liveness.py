"""
test_worker_liveness.py
-----------------------
Whether the control plane can tell a running worker from a dead one.

This matters more than its size suggests. The worker is the only process that
runs a backtest, writes a mark, or places an order, and its death is silent by
construction: jobs queue rather than fail, no mark is written, and both halting
limits go inert because they are measured against marks. Nothing raises. The
heartbeat row exists solely so a human can see it, and the API reporting it
wrongly defeats the entire mechanism.

The first bug this pins down: ``worker_heartbeats.status`` cannot report a
crash. A running process writes ``'alive'`` into it, a clean shutdown writes
``'stopped'``, and a process that dies writes nothing at all, so its row goes on
saying ``'alive'`` for as long as it exists. The System page rendered that
column directly with a green pill, so a worker that died an hour ago displayed
as healthy, and the "no worker" warning fired only when the table had never
had a row at all — a state that exists on a fresh database and essentially
never again. Staleness is therefore the input.

The second (2026-09-27): staleness alone is not enough either. A clean shutdown
writes ``'stopped'`` with ``last_seen = NOW()``, so for the minute before the
row goes stale a stopped process read as alive — a green "stopped" on /system,
"alive" on /programme, and nothing in the daily report's actions. A process is
alive only while its heartbeat is fresh *and* says ``'alive'``.
"""

from __future__ import annotations

import asyncio
import re
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from src.api.routers.system import WORKER_STALE_AFTER_SECONDS
from src.programme import reports
from src.worker.main import HEARTBEAT_INTERVAL_SECONDS

ROOT = Path(__file__).resolve().parents[2]


class TestTheThresholdAgreesWithTheCadence:
    """
    The two numbers live in different modules — the API decides what stale
    means, the worker decides how often it says otherwise. Nothing but this
    test stops them drifting, and drift in one direction reports every healthy
    worker as dead while drift in the other hides a death for as long as the
    gap.
    """

    def test_threshold_exceeds_the_write_interval(self) -> None:
        assert WORKER_STALE_AFTER_SECONDS > HEARTBEAT_INTERVAL_SECONDS, (
            "a staleness threshold at or below the heartbeat interval marks a "
            "healthy worker dead between beats"
        )

    def test_threshold_allows_at_least_three_missed_beats(self) -> None:
        # One missed beat is a slow query. Three is a problem. Anything
        # tighter turns an ordinary database hiccup into a false alarm on the
        # one screen an operator consults when something is already wrong.
        missed = WORKER_STALE_AFTER_SECONDS / HEARTBEAT_INTERVAL_SECONDS
        assert missed >= 3, f"only tolerates {missed:.1f} missed heartbeats"

    def test_threshold_is_not_so_loose_it_hides_a_death(self) -> None:
        assert WORKER_STALE_AFTER_SECONDS <= 300, (
            "a worker dead for five minutes has already missed a submission "
            "window; the screen should not still be green"
        )


class TestStalenessIsDerivedNotStored:
    """
    Guards the shape of the API's answer. ``status`` cannot carry liveness on
    its own, because nothing writes into it when a process crashes; the API
    must therefore compute and expose a separate signal, from the heartbeat's
    age.
    """

    def test_the_status_column_is_never_written_as_dead(self) -> None:
        """
        The premise of the whole fix. If the worker ever learned to write
        'dead' into this column, deriving staleness separately would become
        redundant — and this test would be the thing that says so.
        """
        import inspect

        from src.worker import main

        source = inspect.getsource(main)
        # The worker writes 'alive' while running and 'stopped' on a graceful
        # exit. Neither covers a crash, which is the case that matters.
        assert "'alive'" in source
        assert "'dead'" not in source, (
            "the worker now claims to write a dead status; if a crashed "
            "process can really do that, revisit the staleness derivation"
        )

    def test_build_status_reports_stale_and_age(self) -> None:
        """
        The response contract the UI depends on. Asserted against the source of
        the shipped function rather than a live call, so it runs without a
        database — a contract check that only runs when Postgres is up is a
        contract check that does not run.
        """
        import inspect

        from src.api.routers import system

        source = inspect.getsource(system._build_status)
        assert '"stale"' in source, "the UI cannot colour what is not reported"
        assert '"age_seconds"' in source
        assert "NOW() - last_seen" in source, (
            "age must be computed by the database; comparing against the API "
            "process's own clock makes liveness depend on clock drift between "
            "two separately deployed services"
        )


class _Conn:
    """Just enough of an asyncpg connection for ``build_daily_report``: every
    query answers empty except the heartbeats, which answer ``rows``. The
    report is built for a day with no marks, no orders and no bars, which it
    already handles, so what varies is the one thing under test."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.heartbeat_queries: list[str] = []

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if "worker_heartbeats" in query:
            self.heartbeat_queries.append(query)
            return self.rows
        return []

    async def fetchrow(self, query: str, *args: Any) -> None:
        return None

    async def fetchval(self, query: str, *args: Any) -> None:
        return None


def _report(rows: list[dict[str, Any]]) -> reports.DailyReport:
    conn = _Conn(rows)
    report = asyncio.run(reports.build_daily_report(conn, date(2026, 9, 27)))
    assert conn.heartbeat_queries, "the report no longer reads the heartbeats"
    return report


def _heartbeat(worker_id: str, status: str, age: float) -> dict[str, Any]:
    return {"worker_id": worker_id, "status": status, "age": age}


class TestAProcessThatShutDownCleanlyIsNotAlive:
    """
    A clean shutdown writes ``status='stopped', last_seen=NOW()``
    (``src/worker/main.py`` ``_mark_stopped``, ``src/programme/main.py``
    ``_record_shutdown``). The row is fresh for the next minute and its process
    is not running, so whoever reads liveness from the age alone reads a
    stopped process as alive. The pages decide through one helper
    (``web/src/lib/heartbeat.ts``); these hold the daily report, the one reader
    in ``src/`` that decides anything from a heartbeat itself.
    """

    def test_the_report_carries_each_heartbeat_s_stored_status(self) -> None:
        """The report page cannot render a clean stop it is not told of."""
        report = _report([_heartbeat("worker-1", "stopped", 5.0)])
        (row,) = report.operations["workers"]
        assert row["status"] == "stopped", row
        assert row["stale"] is False, "five seconds old is not stale"

    def test_a_process_that_shut_down_cleanly_is_an_action(self) -> None:
        report = _report(
            [
                _heartbeat("worker-1", "stopped", 5.0),
                _heartbeat("programme", "alive", 4.0),
            ]
        )
        named = [a for a in report.actions if "worker-1" in a]
        assert named, (
            "a worker that shut down five seconds ago is not running, and the "
            f"report's required actions do not say so: {report.actions}"
        )
        assert not [a for a in report.actions if "programme" in a], report.actions

    @pytest.mark.parametrize(
        ("status", "age", "alive"),
        [
            ("alive", 4.0, True),
            ("alive", 600.0, False),  # a crash: nothing wrote 'stopped'
            ("stopped", 5.0, False),  # a clean shutdown, inside the minute
            ("stopped", 600.0, False),
            ("idle", 4.0, False),  # the column's default, which nothing writes
        ],
    )
    def test_only_a_fresh_heartbeat_saying_alive_is_alive(
        self, status: str, age: float, alive: bool
    ) -> None:
        report = _report([_heartbeat("w", status, age)])
        flagged = any(" w:" in a or " w," in a for a in report.actions)
        assert flagged is not alive, (status, age, report.actions)


#: Where a claim about what the stored status holds would be read as fact.
_CLAIM_SOURCES = ("src/**/*.py", "web/src/**/*.ts", "web/src/**/*.tsx")

#: The claim, spelled as it was: the column "only ever written 'alive'", or
#: the worker writing "one value into it". Built from parts, so this file
#: does not match itself.
_CLAIM = re.compile(
    "only ever " + r"writ(?:ten|es)\b[^.]{0,40}?(?:" + "alive|one value" + ")",
    re.I,
)


def _prose(text: str) -> str:
    """Text with comment markers and line breaks folded, so a claim split
    across a docblock's lines reads as one sentence."""
    text = re.sub(r"(?m)^\s*(?:\*|#|//)+\s?", " ", text)
    return " ".join(text.replace("`", "").split())


def test_the_claim_scan_reads_a_split_docblock() -> None:
    split = "/**\n * the column is only ever\n * written `'alive'`, so"
    assert _CLAIM.search(_prose(split))
    assert _CLAIM.search(_prose("# the worker only ever writes one value into it"))
    elsewhere = "`create` — which only ever writes a disabled row"
    assert not _CLAIM.search(_prose(elsewhere))


def test_nothing_claims_the_status_column_is_only_ever_alive() -> None:
    """
    It is not. 'alive' while running, 'stopped' after a clean shutdown — and
    nothing after a crash, which is why the age is still the input. The claim
    in its old form led the pages to read a fresh row as alive whatever it
    said: exactly the stopped process that looked alive.
    """
    paths = [ROOT / "CLAUDE.md", Path(__file__)]
    for pattern in _CLAIM_SOURCES:
        paths.extend(ROOT.glob(pattern))
    paths = [
        p for p in paths if "node_modules" not in p.parts and ".next" not in p.parts
    ]
    # Guards the guard: it read the files the claim was found in.
    assert {"system.py", "api.ts", "StatusBadge.tsx", "CLAUDE.md"} <= {
        p.name for p in paths
    }
    claims = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        if path == Path(__file__):
            text = text[: text.index("#: Where a claim about what")]
        claims += [
            f"{path.relative_to(ROOT)}: …{m.group(0)}…"
            for m in _CLAIM.finditer(_prose(text))
        ]
    assert not claims, (
        "worker_heartbeats.status is 'alive' while a process runs and 'stopped' "
        "after a clean shutdown; it cannot report a crash, which is why the "
        "heartbeat's age is still the input:\n  " + "\n  ".join(claims)
    )
