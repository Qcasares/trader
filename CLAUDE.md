# CLAUDE.md

Guidance for Claude Code (claude.ai/code) working in this repository.

## Project Overview

A **systematic trading platform**: deterministic, backtestable strategies with a
research lab and a live control plane. Strategies are Python classes with typed
parameter schemas; the same code path runs a backtest and a live session.

Informed by [paperswithbacktest/awesome-systematic-trading](https://github.com/paperswithbacktest/awesome-systematic-trading),
though strategies are implemented from the **described rules** rather than
copied — that repository publishes no licence.

A **legacy** seven-agent crypto pipeline (`src/agents/`, `src/orchestrator.py`,
`src/main.py`, `src/db/repositories.py`) used to live alongside this. It has
been deleted: it never ran end to end, nothing in the engine imported it, and
its presence cost roughly 2.5GB of install (torch, transformers) plus a set of
lint and test exclusions. It is in the git history if it is ever wanted.

One file survives on purpose: `src/bankr_client.py`, a complete working client
for the bankr.bot API, kept as the reference for a future crypto broker
adapter. Nothing imports it.

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
   conditions: the deployment's `mode=live`, `LIVE_TRADING_ENABLED` in the
   environment, and `ALPACA_ALLOW_LIVE` in the environment. Do not weaken any
   of them — and note that **deriving one from another is a weakening**.
   `_alpaca_from_env` once passed
   `allow_live=(mode is LIVE and live_trading_enabled)`, which reduced three
   conditions to two while every test still passed, because the tests drove the
   `AlpacaBroker` constructor rather than the factory that builds it.
   `TestTheShippedFactoryHonoursAllThreeGates` now drives the factory.
2. **The kill switch fails closed.** `flags.trading_enabled()` returns `False`
   on a missing row, an unreadable value, or any database error. A control that
   defaults to "go" when it cannot determine the answer is not a control.
3. **Anything a backtest holds in memory, the live path must read back.** A
   `Driver` is constructed fresh for every live job. `last_rebalance`,
   `peak_equity` and `prior_equity` all defaulted to "none/zero" there, so the
   schedule fired every session and both halting limits were inert — while the
   backtest, walking one process, honoured all three. When adding state to
   `Driver`, ask where the live path gets it from.
4. **Every trade path goes through `apply_risk`** (`src/core/risk.py`) — the
   same call on both paths. Never add a clamp to one driver only. Mechanically:
   `apply_risk` has exactly **one** call site, `Driver.decide`, and every path
   that produces orders — backtest, live decision, dry run — calls it. If you
   find yourself calling `strategy.target_weights` followed by
   `weights_to_orders` anywhere else, you are rebuilding the bypass that
   `tests/integration/test_live_path.py::TestRiskGateOnTheLivePath` exists to
   catch.
5. **Never let LLM output reach an order.** Enforced by
   `tests/unit/test_import_boundaries.py`. `src/llm/` is commentary only. The
   guard covers the order-placing *processes* (`src/worker`, `src/api`) as
   well as the pure decision path — `src/worker` is the only thing here that
   submits an order, so it is where an LLM import would matter most.
6. **Never commit credentials.** Not values, not placeholders, not defaults —
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

# Backend stack (db, api, worker) — the frontend deploys to Vercel
docker compose up --build
# ...plus the UI, for local testing only
docker compose --profile web up --build

# Tests
pytest tests/unit -q                                     # no DB needed
TEST_DATABASE_URL=postgresql://localhost/trader_test \
    pytest tests/ -q                                     # includes integration
pytest tests/unit/test_parity.py -q                      # the important one
ruff check src/ tests/

# Browser journey — needs the whole stack running, so it is not in CI
.venv/bin/python tests/e2e/test_browser_journey.py
```

Both commands above lint and run everything. The only `ruff` exclusion left is
`src/bankr_client.py` and its test — a reference file no strategy imports,
where reformatting buys nothing and risks breaking the reference.

`anthropic` is deliberately absent from both requirements files. The engine
must run, and be testable, without an LLM SDK anywhere near it;
`src/llm/commentary.py` imports it lazily and returns `None` without it.

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
| `src/worker/` | The only process that runs backtests or places orders. `scheduling.py` turns the calendar plan into queue rows; `maintenance_jobs.py` handles ingest, marks and reconciliation |
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
| The halting limits can actually halt | `Driver` populates `RiskState`'s equity fields and seeds them from `daily_marks` on the live path; `tests/unit/test_real_data.py` and `TestMarksFeedTheRiskGate` drive both directions |
| Every scheduled job kind has a handler | `test_scheduling.py::test_every_scheduled_kind_has_a_handler` compares the planner's output against the worker's dispatch table as sets |
| Re-planning a session is free | scheduled jobs carry `dedupe_key = "{kind}:{session}"` under a partial unique index, so a worker restart re-plans without duplicating |
| The rebalance schedule survives a restart | `deployments.last_rebalance` is written after every live decision; `TestTheRebalanceScheduleSurvivesRestarts` requires four consecutive sessions to decline after the first |
| Walk-forward before deployment | `walkforward_runs` persists each study's verdict; the deployment gate refuses without a completed, robust study **for the same parameters** |
| A late submission is refused, not filled | `run_submit_orders` expires a batch whose window closed over two hours ago rather than filling at a price the backtest never modelled |
| Honest timestamps | `Driver.step` seeks the injected clock to the session it is processing, so a fill carries the date it happened |
| Venue divergence is visible | `SimulatedBroker.underfunded_buys` records every buy it trimmed that a venue would have rejected |
| Brute force costs more than a shell loop | `src/api/throttle.py` backs off exponentially per source after 5 failed logins; keyed by source, not global, so an attacker cannot lock the operator out of the kill switch |
| No LLM in the order path | `tests/unit/test_import_boundaries.py`, covering `src/worker` and `src/api` as well as the decision path |
| A halted batch is not recorded as sent | `run_submit_orders` writes `partially_submitted` / `blocked_by_kill_switch` / `halted_by_venue`. It is also the retry filter (`status='planned'`), so recording a halted batch as submitted retired the un-sent remainder permanently |
| A dead worker looks dead | The API derives `stale` from the heartbeat's age against the *database* clock; `worker_heartbeats.status` is only ever written `'alive'` and cannot carry liveness. `test_worker_liveness.py` keeps the threshold a multiple of the write interval |
| An unready instance is taken out of rotation | `/api/v1/ready` answers **503**, not 200-with-a-false-body. `/health` stays 200 without a database, so a dependency outage cannot cause a restart loop |
| A mistyped risk limit is refused, not stored | `RiskLimitsRequest` forbids unknown keys, and `test_risk_limits_contract.py` parses the worker's own source to prove the settable set equals the enforced set |
| An impossible backtest window is a 422 | `calendar.bounds()` is read from the calendar, so it tracks the `exchange_calendars` release rather than a literal that goes stale |

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
`deployments`/`decisions`/`orders`/`fills`, `daily_marks`, `walkforward_runs`,
`system_flags` (the kill switch), `jobs`, `audit_log`, `commentary`.

P&L is `equity_t − equity_{t−1} − net deposits`, from `daily_marks`, written by
`src/db/repos/marks.py`. The legacy `get_daily_pnl` in
`src/db/repositories.py` sums **cash flow** and is wrong — do not use it.

`daily_marks` is not only the P&L record: it is the memory the risk gate runs
on. A live process is rebuilt for every session, so `max_drawdown_pct` and
`max_daily_loss_usd` are measured against `peak_equity` and `prior_equity`
read back from this table. Stop writing marks and both limits silently go
inert while the backtest continues to honour them.

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
