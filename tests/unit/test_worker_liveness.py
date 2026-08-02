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

The bug this pins down: ``worker_heartbeats.status`` is only ever written as
``'alive'``, and the row outlives the process. The System page rendered that
column directly with a green pill, so a worker that died an hour ago displayed
as healthy, and the "no worker" warning fired only when the table had never
had a row at all — a state that exists on a fresh database and essentially
never again.
"""

from __future__ import annotations

from src.api.routers.system import WORKER_STALE_AFTER_SECONDS
from src.worker.main import HEARTBEAT_INTERVAL_SECONDS


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
    Guards the shape of the API's answer. ``status`` cannot carry liveness
    because the worker only ever writes one value into it; the API must
    therefore compute and expose a separate signal.
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
