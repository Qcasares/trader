"""
cli.py
------
Command-line entry point for the systematic engine.

    python -m src.cli strategies
    python -m src.cli backtest --strategy asset_class_trend_following \
        --start 1999-01-01 --end 2026-07-01 --source synthetic

This is now the only CLI. It used to be described as "separate from
``src/main.py``, which runs the legacy crypto agent loop" — that loop, and the
seven agents behind it, have been deleted.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import date, datetime
from decimal import Decimal

from src.core.calendar import sessions as nyse_sessions
from src.core.clock import SimClock
from src.core.orders import RebalanceConstraints
from src.core.panel import PricePanel
from src.core.types import CostModel
from src.data import SyntheticSource, YFinanceSource, bars_to_rows
from src.data.base import DataSourceError, PriceSource
from src.engine import Driver, DriverConfig, metrics_from_records
from src.engine.walkforward import run_walk_forward
from src.execution.simulated import SimulatedBroker
from src.strategies import build_strategy, describe_all, list_strategies

logger = logging.getLogger(__name__)

SOURCES: dict[str, type[PriceSource]] = {
    "synthetic": SyntheticSource,
    "yfinance": YFinanceSource,
}


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def cmd_strategies(args: argparse.Namespace) -> int:
    """List registered strategies and their tunable parameters."""
    if args.json:
        print(json.dumps(describe_all(), indent=2, default=str))
        return 0
    for descriptor in describe_all():
        print(f"{descriptor['name']}  (v{descriptor['version']})")
        print(f"  {descriptor['description']}")
        print(f"  universe: {', '.join(descriptor['universe'])}")
        print(f"  warmup:   {descriptor['warmup_sessions']} sessions")
        print(f"  params:   {json.dumps(descriptor['params'])}")
        if descriptor["source"]:
            print(f"  source:   {descriptor['source']}")
        print()
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    """Run one backtest and print its metrics."""
    if args.strategy not in list_strategies():
        print(
            f"unknown strategy {args.strategy!r}; available: "
            f"{', '.join(list_strategies())}",
            file=sys.stderr,
        )
        return 2

    params = json.loads(args.params) if args.params else None
    strategy = build_strategy(args.strategy, params)
    universe = strategy.universe()

    source = SOURCES[args.source]()
    print(f"Fetching {len(universe)} symbols from {source.name}...", file=sys.stderr)
    try:
        bars = source.fetch(universe, args.start, args.end)
    except DataSourceError as exc:
        print(f"data source failed: {exc}", file=sys.stderr)
        return 1
    if not bars:
        print("data source returned no bars", file=sys.stderr)
        return 1

    panel = PricePanel.from_bars(bars_to_rows(bars))
    trading_sessions = nyse_sessions(args.start, args.end)

    clock = SimClock(trading_sessions)
    broker = SimulatedBroker(
        initial_cash=Decimal(str(args.cash)),
        cost_model=CostModel(
            slippage_bps=args.slippage_bps,
            stress_multiplier=args.cost_stress,
        ),
        clock=clock,
    )
    driver = Driver(
        strategy,
        broker,
        clock,
        DriverConfig(
            constraints=RebalanceConstraints(
                min_trade_usd=Decimal(str(args.min_trade)),
                max_weight_per_asset=args.max_weight,
            ),
            run_ref=args.run_ref,
        ),
    )

    effective_start = driver.effective_start(panel, trading_sessions)

    async def run() -> list:
        records = []
        for session in trading_sessions:
            records.append(await driver.step(panel, session))
            clock.advance()
        return records

    records = asyncio.run(run())
    metrics = metrics_from_records(
        records,
        effective_start=effective_start,
        cost_stress_multiplier=args.cost_stress,
    )

    if args.json:
        print(json.dumps(metrics.to_dict(), indent=2, default=str))
        return 0

    print()
    print(f"strategy        {strategy.name} v{strategy.version}")
    print(f"universe        {', '.join(universe)}")
    print(f"data source     {source.name}")
    if source.name == "synthetic":
        print("                ** SYNTHETIC DATA — not a real backtest result **")
    print(f"requested start {args.start}")
    print(f"effective start {effective_start}   <- full universe + warmup satisfied")
    if effective_start and effective_start > args.start:
        print(
            "                (metrics before this date reflect a partial "
            "universe, not the strategy)"
        )
    print(f"cost stress     {args.cost_stress:g}x  ({args.slippage_bps:g} bps base)")
    print()
    print(metrics.summary())
    print()
    print(
        f"rebalances {metrics.n_rebalances}   fills {metrics.n_fills}   "
        f"commission ${metrics.total_commission:,.2f}"
    )
    print(
        f"exposure {metrics.exposure:.1%}   turnover {metrics.turnover_annual:.2f}x/yr"
        f"   calmar {metrics.calmar:.2f}"
    )
    print(f"final equity ${metrics.final_equity:,.2f}")
    if not metrics.sharpe_is_significant:
        print()
        print(
            "WARNING: this Sharpe is within two standard errors of zero. "
            "It is not evidence the strategy works."
        )
    return 0


def cmd_walkforward(args: argparse.Namespace) -> int:
    """
    Run a walk-forward study.

    Choose parameters on each training window, measure on the window that
    follows. The gap between the two is the number that matters: a strategy
    that scores well in-sample and poorly out-of-sample has been curve-fitted,
    and finding that out here costs nothing.
    """
    if args.strategy not in list_strategies():
        print(f"unknown strategy {args.strategy!r}", file=sys.stderr)
        return 2

    strategy = build_strategy(args.strategy)
    source = SOURCES[args.source]()
    print(f"Fetching {source.name} data...", file=sys.stderr)
    try:
        bars = source.fetch(strategy.universe(), args.start, args.end)
    except DataSourceError as exc:
        print(f"data source failed: {exc}", file=sys.stderr)
        return 1

    panel = PricePanel.from_bars(bars_to_rows(bars))
    trading_sessions = nyse_sessions(args.start, args.end)
    grid = json.loads(args.grid) if args.grid else {"sma_period": [105, 150, 210]}

    try:
        result = run_walk_forward(
            args.strategy,
            panel,
            trading_sessions,
            param_grid=grid,
            train_months=args.train_months,
            test_months=args.test_months,
            cost_model=CostModel(
                slippage_bps=args.slippage_bps, stress_multiplier=args.cost_stress
            ),
            constraints=RebalanceConstraints(
                min_trade_usd=Decimal(str(args.min_trade))
            ),
        )
    except ValueError as exc:
        print(f"cannot run walk-forward: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({
            "strategy": result.strategy_name,
            "folds": len(result.folds),
            "mean_in_sample_sharpe": result.mean_in_sample_sharpe,
            "mean_out_of_sample_sharpe": result.mean_out_of_sample_sharpe,
            "degradation": result.degradation,
            "stitched_oos": result.stitched_oos.to_dict(),
            "parameter_stability": result.parameter_stability,
            "is_robust": result.is_robust,
            "fold_choices": [
                {
                    "test_start": f.fold.test_start.isoformat(),
                    "test_end": f.fold.test_end.isoformat(),
                    "chosen_params": f.chosen_params,
                    "in_sample_sharpe": f.in_sample.sharpe,
                    "out_of_sample_sharpe": f.out_of_sample.sharpe,
                }
                for f in result.folds
            ],
        }, indent=2, default=str))
        return 0

    print()
    if source.name == "synthetic":
        print("** SYNTHETIC DATA \u2014 not a real validation result **")
        print()
    print(result.summary())
    print()
    print("per-fold parameter choices:")
    for fold_result in result.folds:
        print(
            f"  {fold_result.fold.test_start}..{fold_result.fold.test_end}  "
            f"{fold_result.chosen_params}  "
            f"IS {fold_result.in_sample.sharpe:+.3f}  "
            f"OOS {fold_result.out_of_sample.sharpe:+.3f}"
        )
    if not result.is_robust:
        print()
        print(
            "WARNING: this strategy did not clear walk-forward validation. "
            "Do not deploy it."
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.cli",
        description="Systematic trading engine — research CLI.",
    )
    parser.add_argument(
        "--log-level", default="WARNING", help="Python logging level."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("strategies", help="List registered strategies.")
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(func=cmd_strategies)

    backtest = sub.add_parser("backtest", help="Run a backtest.")
    backtest.add_argument("--strategy", required=True)
    backtest.add_argument("--start", type=_parse_date, default=date(1999, 1, 1))
    backtest.add_argument("--end", type=_parse_date, default=date.today())
    backtest.add_argument("--cash", type=float, default=100_000.0)
    backtest.add_argument(
        "--source",
        choices=sorted(SOURCES),
        default="yfinance",
        help="yfinance for real history; synthetic for engine verification.",
    )
    backtest.add_argument("--slippage-bps", type=float, default=5.0)
    backtest.add_argument(
        "--cost-stress",
        type=float,
        default=1.0,
        help="Multiply all costs. Re-run at 3x; if the sign flips, do not deploy.",
    )
    backtest.add_argument("--min-trade", type=float, default=25.0)
    backtest.add_argument("--max-weight", type=float, default=1.0)
    backtest.add_argument("--params", help="JSON object of strategy parameters.")
    backtest.add_argument("--run-ref", default="cli")
    backtest.add_argument("--json", action="store_true")
    backtest.set_defaults(func=cmd_backtest)

    walk = sub.add_parser(
        "walkforward", help="Validate a strategy out of sample."
    )
    walk.add_argument("--strategy", required=True)
    walk.add_argument("--start", type=_parse_date, default=date(2007, 1, 1))
    walk.add_argument("--end", type=_parse_date, default=date.today())
    walk.add_argument("--source", choices=sorted(SOURCES), default="yfinance")
    walk.add_argument("--train-months", type=int, default=36)
    walk.add_argument("--test-months", type=int, default=12)
    walk.add_argument(
        "--grid",
        help='JSON parameter grid, e.g. \'{"sma_period":[105,150,210]}\'',
    )
    walk.add_argument("--slippage-bps", type=float, default=5.0)
    walk.add_argument("--cost-stress", type=float, default=1.0)
    walk.add_argument("--min-trade", type=float, default=25.0)
    walk.add_argument("--json", action="store_true")
    walk.set_defaults(func=cmd_walkforward)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.WARNING),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
