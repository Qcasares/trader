"""
test_kill_switch_cancel.py
--------------------------
The kill switch's second half is the worker's, and the switch does not stop it.

``POST /system/kill`` queues ``cancel_open_orders``. The worker dispatches every
kind through one table and refuses the order-placing ones while the switch is
engaged: were the cancel among them, the switch that queued it would refuse it,
every time, and the page would wait for a cancel that could never run. That it
is not drainable, so no HTTP request reaches the venue's orders from the API
process, is ``test_drain_boundary.py``. The integration half, against real
Postgres and the fake venue over real HTTP, is
``tests/integration/test_live_path.py::TestTheKillSwitchCancelsAtTheVenue``.
"""

from __future__ import annotations

import pytest

from src.worker.kill_job import run_cancel_open_orders
from src.worker.main import HANDLERS, KILL_GATED_KINDS, SCHEDULED_KINDS
from src.worker.scheduling import PRIORITY


def test_the_cancel_is_a_worker_job() -> None:
    assert HANDLERS["cancel_open_orders"] is run_cancel_open_orders


def test_the_switch_does_not_stop_its_own_cancel() -> None:
    assert "cancel_open_orders" not in KILL_GATED_KINDS


def test_the_switch_still_stops_every_kind_that_places_an_order() -> None:
    assert KILL_GATED_KINDS == {"live_decision", "submit_orders"}
    assert KILL_GATED_KINDS <= set(HANDLERS)


def test_the_worker_and_the_cancel_read_one_list_of_order_placing_kinds() -> None:
    """
    The worker refuses these under the switch, and the cancel waits for any of
    them running elsewhere before it confirms; two copies could drift apart.
    """
    from src.worker import kill_job, main

    assert main.KILL_GATED_KINDS is kill_job.KILL_GATED_KINDS


def test_the_cancel_is_queued_by_the_switch_and_never_planned() -> None:
    assert "cancel_open_orders" not in SCHEDULED_KINDS


def test_the_cancel_goes_ahead_of_everything_the_planner_queues() -> None:
    """
    Claimed behind a backtest, it would wait minutes while the orders it could
    have cancelled filled.
    """
    pytest.importorskip("fastapi")
    from src.api.routers.system import CANCEL_PRIORITY

    assert CANCEL_PRIORITY > max(PRIORITY.values())
