# CLAUDE.md

Guidance for Claude Code (claude.ai/code) working in this repository.

## Project Overview

A **systematic trading platform**: deterministic, backtestable strategies with a
research lab and a live control plane. Strategies are Python classes with typed
parameter schemas; the same code path runs a backtest and a live session.

Informed by [paperswithbacktest/awesome-systematic-trading](https://github.com/paperswithbacktest/awesome-systematic-trading),
though strategies are implemented from the **described rules** rather than
copied — that repository publishes no licence.

There is also a **legacy** crypto agent pipeline (`src/agents/`,
`src/orchestrator.py`, `src/main.py`) built against bankr.bot. It is not wired
into the systematic engine, its context-promotion map is broken, and nothing in
the new path may import it. Treat it as historical unless asked otherwise.

## The one idea to understand first

**One `Driver`, two injected dependencies.**

```python
backtest = Driver(strategy, SimulatedBroker(), SimClock(sessions))
live     = Driver(strategy, AlpacaBroker(),    RealClock())
```

The backtest *is* the live path with two objects swapped. This is not a
convention — `tests/unit/test_parity.py` asserts both emit byte-identical
`OrderIntent` lists from identical inputs, and it is mutation-tested.

**Before changing anything in `src/core/`, `src/engine/` or `src/execution/`,
run the parity test.** If it breaks, the change has made the backtest stop
predicting the live system, which is worse than the bug being fixed.

## Safety rules

1. **Paper only.** Reaching a live Alpaca endpoint requires *three* independent
   conditions: `mode=live`, `LIVE_TRADING_ENABLED` in the environment, and an
   explicit `allow_live=True`. Do not weaken any of them.
2. **The kill switch fails closed.** `flags.trading_enabled()` returns `False`
   on a missing row, an unreadable value, or any database error. A control that
   defaults to "go" when it cannot determine the answer is not a control.
3. **Every trade path goes through `apply_risk`** (`src/core/risk.py`) — the
   same call on both paths. Never add a clamp to one driver only. Mechanically:
   `apply_risk` has exactly **one** call site, `Driver.decide`, and every path
   that produces orders — backtest, live decision, dry run — calls it. If you
   find yourself calling `strategy.target_weights` followed by
   `weights_to_orders` anywhere else, you are rebuilding the bypass that
   `tests/integration/test_live_path.py::TestRiskGateOnTheLivePath` exists to
   catch.
4. **Never let LLM output reach an order.** Enforced by
   `tests/unit/test_import_boundaries.py`. `src/llm/` is commentary only. The
   guard covers the order-placing *processes* (`src/worker`, `src/api`) as
   well as the pure decision path — `src/worker` is the only thing here that
   submits an order, so it is where an LLM import would matter most.
5. **Never commit credentials.** Not values, not placeholders, not defaults —
   `docker-compose.yml` reads everything from gitignored `.env`.

## Honesty rules

These exist because the research UI is a machine for fooling yourself.

- **Never render a Sharpe without its standard error.** Five years of daily
  data gives roughly ±0.45, so a reported 0.50 is indistinguishable from zero.
  `PerformanceMetrics.sharpe_is_significant` is the check.
- **Never quote a performance figure without its cost assumption.** Every
  result carries `cost_stress_multiplier`.
- **Never quote a metric without `effective_start`.** A 1999 backtest of the
  five asset-class ETFs is a single-asset SPY strategy until 2007, because GSG
  did not list until 2006.
- **Never quote an annualised figure without its session count.** 252 is the
  NYSE year; a venue that never closes has 365. Annualising continuous returns
  on 252 understates volatility by `sqrt(365/252)` — about 20% — and flatters
  the Sharpe by the same factor. `PerformanceMetrics.periods_per_year` carries
  the assumption, and `metrics_from_records` takes it as an argument rather
  than defaulting silently.
- **Synthetic data is labelled everywhere it appears** and cannot back a
  deployment — the API rejects it.
- **The backtest must say when it was kinder than the venue.** `SimulatedBroker`
  trims an underfunded buy where a real venue rejects it; every trim lands in
  `SimulatedBroker.underfunded_buys` and logs a warning. The parity test cannot
  see this — the order *intents* match exactly and it is the fills that
  diverge. Check the list before believing a result, and set
  `RiskLimits.cash_buffer_pct` if it is non-empty.

## Commands

```bash
# Setup
python -m venv .venv && .venv/bin/pip install -r requirements.txt
export DATABASE_URL=postgresql://trader@localhost:5432/trader
python -m src.db.migrate_cli                 # apply migrations

# Research CLI
python -m src.cli strategies
python -m src.cli backtest --strategy asset_class_trend_following \
    --source yfinance --start 1999-01-01
python -m src.cli walkforward --strategy asset_class_trend_following \
    --grid '{"sma_period":[105,150,210]}'

# Services (API and worker are separate processes on purpose)
uvicorn src.api.main:app --reload            # HTTP control plane
python -m src.worker.main                    # runs backtests and live jobs
cd web && npm run dev                        # Next.js frontend

# Everything at once
docker compose up --build

# Tests
pytest tests/unit -q                                     # no DB needed
TEST_DATABASE_URL=postgresql://localhost/trader_test \
    pytest tests/ -q                                     # includes integration
pytest tests/unit/test_parity.py -q                      # the important one
ruff check src/ tests/
```

`ruff` excludes the legacy pipeline via `pyproject.toml`, so the command above
lints exactly the code this repository is responsible for. Likewise the legacy
agent tests are skipped when `anthropic` is absent — `requirements-engine.txt`
omits it deliberately, and a missing optional dependency must not take the
whole suite down during collection.

`.github/workflows/ci.yml` runs ruff, the unit suite and the integration suite
against a real Postgres on every pull request, installing only
`requirements-engine.txt`. Parity and the import boundaries get their own named
steps: when they break, the failure should say so in the checks list rather
than hide in a wall of dots.

## Architecture

```
                    ┌──────────────────────────┐
                    │  Strategy (pure, no I/O) │
                    │  target_weights(...)     │
                    └────────────┬─────────────┘
                                 ▼
                    ┌──────────────────────────┐
                    │  core/risk.apply_risk    │  shared gate
                    │  core/orders.weights_to_ │  shared sizing
                    │            orders        │
                    └────────────┬─────────────┘
                                 ▼
              ┌──────────────────┴──────────────────┐
              ▼                                     ▼
      SimulatedBroker                        AlpacaBroker
      + SimClock                             + RealClock
```

| Package | Responsibility |
|---|---|
| `src/core/` | Value types, `PricePanel`, calendar, clock, order sizing, risk gate |
| `src/engine/` | `Driver`, metrics, scheduler, walk-forward |
| `src/strategies/` | Strategy ABC, registry, strategy implementations |
| `src/execution/` | `BrokerAdapter` protocol, `SimulatedBroker`, `AlpacaBroker` |
| `src/data/` | `PriceSource` protocol, yfinance, synthetic generator |
| `src/db/` | asyncpg pool, migrations, repositories |
| `src/api/` | FastAPI control plane |
| `src/worker/` | The only process that runs backtests or places orders |
| `src/llm/` | Commentary only. Never reachable from the decision path. |
| `web/` | Next.js frontend |

### Structural guarantees

Each is enforced by a test, not by discipline:

| Guarantee | Mechanism |
|---|---|
| No look-ahead | `PricePanel` is built with an `as_of` and refuses to re-slice forward |
| Decision lag | `SimulatedBroker` queues rather than fills; decide on T's close, execute at T+1's open |
| Availability windows | An unlisted asset is excluded from the weighting denominator, not treated as cash |
| Idempotent orders | `client_order_id = "{run_ref}:{session}:{symbol}"`; the venue rejects duplicates |
| Backtest/live parity | `tests/unit/test_parity.py` (synthetic) and `tests/unit/test_real_data.py` (observed prices) |
| The risk gate binds live, not just in backtests | `tests/integration/test_live_path.py::TestRiskGateOnTheLivePath` asserts against the shipped job, not the driver it ought to use |
| Honest timestamps | `Driver.step` seeks the injected clock to the session it is processing, so a fill carries the date it happened |
| Venue divergence is visible | `SimulatedBroker.underfunded_buys` records every buy it trimmed that a venue would have rejected |
| No LLM in the order path | `tests/unit/test_import_boundaries.py`, covering `src/worker` and `src/api` as well as the decision path |

## Adding a strategy

1. Create `src/strategies/<name>.py` with a `StrategyParams` subclass and a
   `Strategy` subclass decorated with `@register`.
2. Implement `universe()`, `should_rebalance()`, `target_weights()`.
3. Import it in `src/strategies/__init__.py` so registration happens.
4. Add tests. Walk-forward it before considering a deployment.

```python
@register
class MyStrategy(Strategy):
    name = "my_strategy"
    params_model = MyParams

    def universe(self) -> list[str]:
        return list(self.params.symbols)

    def should_rebalance(self, session, last_rebalance) -> bool:
        return last_rebalance is None or session.month != last_rebalance.month

    def target_weights(self, panel, state, session) -> TargetWeights:
        # panel is already truncated to `session` — future data is unreachable
        return TargetWeights({...})
```

`target_weights` **must be pure**: no network, no clock, no database. Anything
else makes the backtest unreproducible and the parity test meaningless.

Signals use `adj_close` (split- and dividend-adjusted); money uses raw `close`.
Mixing them makes the ledger disagree with the broker by the cumulative
dividend adjustment.

## Database

PostgreSQL. Migrations are numbered SQL files in `migrations/` applied by
`src/db/migrate.py`, which verifies a checksum — **never edit an applied
migration**, write a new one.

Key tables: `daily_bars` (raw prices, `source` in the PK so vendors can be
reconciled), `backtest_runs`/`backtest_equity`/`backtest_orders`,
`deployments`/`decisions`/`orders`/`fills`, `daily_marks`, `system_flags`
(the kill switch), `jobs`, `audit_log`, `commentary`.

P&L is `equity_t − equity_{t−1} − net deposits`, from `daily_marks`. The legacy
`get_daily_pnl` in `src/db/repositories.py` sums **cash flow** and is wrong —
do not use it.

## Conventions

- Python 3.11+, type hints throughout, async/await, `logging` not `print`
- `Decimal` for money and quantities; `float` for indicator maths. The single
  conversion point is `src/core/orders.weights_to_orders`.
- Frozen dataclasses for value types; pydantic for strategy params and API models
- ruff, line length 88
- Tests assert behaviour against real dependencies where possible — real
  Postgres, the real NYSE calendar, a fake Alpaca over real HTTP. Mocking a
  boundary only proves the mock matches your assumption about it.

## Known limitations

- **No result in this repository is a real backtest.** Equity data hosts
  (Yahoo, Stooq, `data.alpaca.markets`) are blocked by this environment's
  egress policy, so no strategy has ever been measured on real equity prices.
  Run against real data before drawing any conclusion.
- **The engine, separately, has been run on real prices.**
  `tests/fixtures/cryptocom_candles.json` holds 24 daily candles for four spot
  pairs, captured from the Crypto.com public API, and `tests/unit/test_real_data.py`
  drives the whole ingest → panel → driver → gate → metrics path on them —
  including parity. That validates the *machinery*, not any strategy: 24
  sessions is seven weeks, the Sharpe standard error over it is about ±4, and
  the 210-day SMA the one implemented strategy needs is impossible in a window
  that short. Read it as "the plumbing survives contact with real numbers",
  nothing more. Two bugs came out of it, both listed in the git log.
- Alpaca has never been contacted. `AlpacaBroker` is tested against a fake
  server modelling the documented contract.
- **Crypto is not supported**, and this fixture does not change that. It has no
  24/7 scheduler, no crypto broker adapter and no venue-aware cost model;
  `src/data/cryptocom_source.py` exists to feed the engine real prices. The
  locked plan is equities first.
- One strategy is implemented. The awesome-systematic-trading median Sharpe is
  ~0.35 and seven entries are negative; expect disappointment and let the
  walk-forward say so.
