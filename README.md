# Systematic trading platform

Deterministic, backtestable strategies with a research lab and a live control
plane. Strategies are Python classes with typed parameter schemas; the same code
path runs a backtest and a live session.

```python
backtest = Driver(strategy, SimulatedBroker(), SimClock(sessions))
live     = Driver(strategy, AlpacaBroker(),    RealClock())
```

The backtest **is** the live path with two objects swapped. That is not a
convention — `tests/unit/test_parity.py` asserts both emit byte-identical
`OrderIntent` lists from identical inputs, and it is mutation-tested.

---

## Read this before believing any number

- **No strategy here has ever been backtested on real prices.** Equity data
  hosts were unreachable throughout development, so the `yfinance` adapter has
  never spoken to its host. Every figure in this repository is synthetic, or
  drawn from 24 real crypto candles that validate the machinery and nothing
  else.
- **Alpaca has never been contacted.** `AlpacaBroker` is tested against a fake
  server modelling the documented contract. No order, paper or live, has ever
  been placed.
- **Live trading takes three independent gates plus a kill switch**, all
  closed by default. This is paper-only by construction, not by intention.
- One strategy is implemented. The reference list's median Sharpe is ~0.35 and
  seven of its entries are negative. Expect disappointment and let the
  walk-forward say so.

The UI is built to make those caveats hard to ignore: a Sharpe never renders
without its standard error, a result never renders without its cost assumption
and annualisation basis, and synthetic data is labelled everywhere it appears.

## Running it

Locally, with Docker or without — see **[SETUP.md](SETUP.md)**.

```bash
docker compose --profile web up --build
docker compose run --rm api python -m src.db.migrate_cli
```

## Deploying

Two shapes, and which you want depends on whether you need the live path.

### Research lab, on Vercel

Backtests, tearsheets, the kill switch. Two projects from **this one
repository** — import it twice at <https://vercel.com/new>:

| Project | Root Directory | Framework |
|---|---|---|
| API | *(repository root)* | detected from `vercel.json` |
| UI | `web` | Next.js |

Set these on the **API** project:

| Variable | Value | Why it matters |
|---|---|---|
| `DATABASE_URL` | any managed Postgres | Neon is in Vercel's marketplace and sets this for you |
| `SESSION_SECRET` | 32+ random chars | no default; the API refuses to start without one |
| `ADMIN_PASSWORD_HASH` | bcrypt hash | your operator login |
| `CORS_ORIGINS` | the UI project's URL | exact origin, no trailing slash |
| `SESSION_COOKIE_SAMESITE` | `none` | **required.** Different sites, so a `Lax` cookie is never sent — login returns 200 and everything after it 401s, which reads as a correct password being rejected |
| `SERVERLESS_DRAIN_ENABLED` | `true` | **required.** No worker can exist on serverless, so without it a backtest queues forever |
| `DB_POOL_MAX_SIZE` | `3` | **required.** Every cold start builds its own pool; the default of 10 exhausts a free tier's connection limit |
| `CRON_SECRET` | long random string | lets the scheduled sweep authenticate |

And on the **UI** project: `NEXT_PUBLIC_API_BASE` = the API project's URL. It is
inlined at *build* time, so changing it needs a redeploy.

Then apply migrations once, from a checkout:
`DATABASE_URL=... python -m src.db.migrate_cli`.

The three variables marked **required** each fail in a way that points somewhere
other than the cause. They are the whole reason this table exists.

### Live path, on a host with real processes

Not Vercel. The live path needs something that outlives a request — a scheduler
that wakes at the close, and a worker holding the only route to a broker.
`render.yaml` declares Postgres, the API and the worker as one blueprint.

## Architecture

```
                    ┌──────────────────────────┐
                    │  Strategy (pure, no I/O) │
                    └────────────┬─────────────┘
                                 ▼
                    ┌──────────────────────────┐
                    │  core/risk.apply_risk    │  shared gate
                    │  core/orders.weights_to_ │  shared sizing
                    │            orders        │
                    └────────────┬─────────────┘
              ┌──────────────────┴──────────────────┐
              ▼                                     ▼
      SimulatedBroker                        AlpacaBroker
      + SimClock                             + RealClock
```

| Package | Responsibility |
|---|---|
| `src/core/` | Value types, `PricePanel`, calendar, clock, order sizing, risk gate |
| `src/engine/` | `Driver`, metrics, scheduler, walk-forward |
| `src/strategies/` | Strategy ABC, registry, implementations |
| `src/execution/` | `BrokerAdapter`, `SimulatedBroker`, `AlpacaBroker` |
| `src/data/` | `PriceSource`, yfinance, synthetic, Crypto.com |
| `src/db/` | asyncpg pool, migrations, repositories |
| `src/api/` | FastAPI control plane |
| `src/worker/` | The only process that runs backtests or places orders |
| `src/llm/` | Commentary only. Never reachable from the decision path |
| `web/` | Next.js frontend |

Correctness is enforced by tests rather than by discipline — no look-ahead,
decision lag, idempotent orders, backtest/live parity, a kill switch that fails
closed, and no LLM import reachable from an order. `CLAUDE.md` lists each
guarantee against the mechanism that holds it.

## Tests

```bash
pytest tests/unit -q                                     # no database needed
TEST_DATABASE_URL=postgresql://localhost/trader_test pytest tests/ -q
pytest tests/unit/test_parity.py -q                      # the important one
ruff check src/ tests/
```

404 tests: 326 unit, 78 integration against a real Postgres.

If the parity test fails, the backtest has stopped predicting the live system —
which is worse than whatever bug the change was fixing.
