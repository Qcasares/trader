"""
walkforward_job.py
------------------
Run a walk-forward study and persist its verdict.

The engine has implemented walk-forward since Phase 4 and the CLI could run
it. Nothing stored the result, so the deployment gate had nothing to consult
and the plan's mitigation for its own risk 7 — that a research UI is an
overfitting machine — existed only as advice.

What gets stored is the *judgement* as much as the numbers. ``is_robust`` is
the study's own conservative verdict; ``degradation`` is the headline, being
how much performance evaporated once the parameters had to be chosen in
advance rather than in hindsight.

Runs in a worker thread, like the backtest job, because it is CPU-bound pandas
work: one study is one backtest per candidate per fold, which is the most
expensive thing this system does.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import asyncpg

from src.core.calendar import sessions as nyse_sessions
from src.core.orders import RebalanceConstraints
from src.core.panel import PricePanel
from src.core.types import CostModel
from src.data import bars_to_rows
from src.engine.walkforward import run_walk_forward
from src.strategies import build_strategy
from src.worker.backtest_job import SOURCES

logger = logging.getLogger(__name__)


class WalkForwardJobError(RuntimeError):
    """The study could not be run."""


async def run_walkforward_job(
    conn: asyncpg.Connection, payload: dict[str, Any]
) -> dict[str, Any]:
    """Execute a queued walk-forward study and record its outcome."""
    run_id = uuid.UUID(str(payload["walkforward_run_id"]))
    row = await conn.fetchrow(
        "SELECT * FROM walkforward_runs WHERE id = $1", run_id
    )
    if row is None:
        raise WalkForwardJobError(f"unknown walkforward run {run_id}")

    await conn.execute(
        "UPDATE walkforward_runs SET status='running' WHERE id=$1", run_id
    )
    study = _decode(row)

    try:
        result = await asyncio.to_thread(_execute, study)
    except Exception as exc:  # noqa: BLE001 - recorded on the row, then re-raised
        await conn.execute(
            "UPDATE walkforward_runs SET status='failed', error=$2, "
            "finished_at=NOW() WHERE id=$1",
            run_id,
            str(exc),
        )
        logger.error("Walk-forward %s failed: %s", run_id, exc)
        raise

    await conn.execute(
        """
        UPDATE walkforward_runs SET
            status='succeeded', is_robust=$2, degradation=$3,
            mean_is_sharpe=$4, mean_oos_sharpe=$5, n_folds=$6,
            folds=$7::jsonb, metrics=$8::jsonb, finished_at=NOW()
        WHERE id=$1
        """,
        run_id,
        result["is_robust"],
        result["degradation"],
        result["mean_is_sharpe"],
        result["mean_oos_sharpe"],
        result["n_folds"],
        json.dumps(result["folds"], default=str),
        json.dumps(result["metrics"], default=str),
    )
    logger.info(
        "Walk-forward %s: %s (degradation %+.3f over %d fold(s))",
        run_id,
        "ROBUST" if result["is_robust"] else "NOT ROBUST",
        result["degradation"],
        result["n_folds"],
    )
    return {
        "walkforward_run_id": str(run_id),
        "is_robust": result["is_robust"],
        "degradation": result["degradation"],
        "n_folds": result["n_folds"],
    }


def _execute(study: dict[str, Any]) -> dict[str, Any]:
    """Synchronous body. Runs in a worker thread."""
    strategy = build_strategy(study["strategy_name"], study["params"])
    source_cls = SOURCES.get(study["data_source"])
    if source_cls is None:
        raise WalkForwardJobError(
            f"unknown data source {study['data_source']!r}"
        )

    start, end = study["start_session"], study["end_session"]
    bars = source_cls().fetch(strategy.universe(), start, end)
    if not bars:
        raise WalkForwardJobError(
            f"no bars for {strategy.universe()} between {start} and {end}"
        )

    panel = PricePanel.from_bars(bars_to_rows(bars))
    sessions = nyse_sessions(start, end)

    result = run_walk_forward(
        study["strategy_name"],
        panel,
        sessions,
        param_grid=study["param_grid"] or None,
        base_params=study["params"] or None,
        train_months=study["train_months"],
        test_months=study["test_months"],
        cost_model=CostModel(),
        constraints=RebalanceConstraints(min_trade_usd=Decimal("25")),
    )

    return {
        "is_robust": result.is_robust,
        "degradation": result.degradation,
        "mean_is_sharpe": result.mean_in_sample_sharpe,
        "mean_oos_sharpe": result.mean_out_of_sample_sharpe,
        "n_folds": len(result.folds),
        "folds": [
            {
                "index": f.fold.index,
                "train_start": f.fold.train_start,
                "train_end": f.fold.train_end,
                "test_start": f.fold.test_start,
                "test_end": f.fold.test_end,
                "chosen_params": f.chosen_params,
                "in_sample_sharpe": f.in_sample.sharpe,
                "out_of_sample_sharpe": f.out_of_sample.sharpe,
            }
            for f in result.folds
        ],
        # The stitched out-of-sample curve is the only performance figure here
        # that anybody should quote, and it carries its own standard error.
        #
        # The two research-integrity statistics ride alongside it rather than
        # inside it, because they are properties of the *study* — of how hard
        # it looked — and not of the curve. Both are None when the study could
        # not support them, and None is stored as null rather than as zero: an
        # unmeasured probability of overfitting rendered as 0.0 would be the
        # most flattering possible lie about a research process.
        "metrics": {
            **result.stitched_oos.to_dict(),
            "probability_of_backtest_overfitting": result.pbo,
            "deflated_sharpe": result.deflated_sharpe,
            "n_trials": result.param_grid_size,
        },
    }


def _decode(row: asyncpg.Record) -> dict[str, Any]:
    study = dict(row)
    for key in ("params", "param_grid"):
        value = study.get(key)
        if isinstance(value, str):
            study[key] = json.loads(value)
    for key in ("start_session", "end_session"):
        study[key] = _as_date(study[key])
    return study


def _as_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value))
