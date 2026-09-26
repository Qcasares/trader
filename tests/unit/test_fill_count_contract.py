"""
test_fill_count_contract.py
---------------------------
That a backtest's ``n_fills`` metric counts exactly the rows stored as its
fills.

The backtest detail page titles its fills card with a count, and used to take
it from the length of ``GET /backtests/{id}/orders`` — which is a page the API
caps at 500 unless asked for more. A run with 779 fills rendered "Fills (500)"
under a metric grid that said 779, and "Showing the 200 most recent of 500".
The count now comes from ``BacktestMetrics.n_fills``, the total the API already
returns, and the page fetches only the rows it shows.

That is only honest while the metric and the stored rows count the same thing.
Today they do by construction — ``metrics_from_records`` counts
``len(r.fills)`` over the records, and ``_execute`` writes one order row per
fill over the same records — but the two live in different modules, and the
first change that stores a subset (only the rebalance legs, only fills above a
notional floor) would make the card's total describe rows nobody can page to.
So the equality is asserted on a real run of the shipped job, not restated.

Synthetic prices on purpose: the property is about the engine's bookkeeping,
and a seeded generator makes the run deterministic and offline.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

pytest.importorskip("pandas")

from src.worker.backtest_job import _execute  # noqa: E402


@pytest.fixture(scope="module")
def result() -> dict:
    # Four years of the trend follower: long enough past its warm-up to
    # rebalance monthly across the five-asset universe, short enough to run in
    # a couple of seconds.
    run = {
        "id": uuid.uuid4(),
        "strategy_name": "asset_class_trend_following",
        "params": {},
        "data_source": "synthetic",
        "start_session": date(2008, 1, 2),
        "end_session": date(2011, 12, 30),
        "initial_cash": 100000.0,
        "cost_model": {"stress_multiplier": 1.0},
    }
    return _execute(run)


def test_the_run_filled_something(result: dict) -> None:
    # Guards the guard: zero rows and a zero metric are equal too.
    assert result["metrics"]["n_fills"] > 20


def test_the_fill_count_is_the_number_of_stored_fills(result: dict) -> None:
    assert len(result["order_rows"]) == result["metrics"]["n_fills"], (
        "BacktestMetrics.n_fills no longer counts the rows written to "
        "backtest_orders, and the backtest page titles its fills card with it. "
        "Either store every fill or report the stored count separately."
    )


def test_every_stored_order_is_a_fill(result: dict) -> None:
    """The rows the card lists are fills, so the total it quotes is of fills."""
    assert {row[-1] for row in result["order_rows"]} == {"fill"}
