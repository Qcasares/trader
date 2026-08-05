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
   The same test carries the **reverse** boundary: `src/programme` is the one
   package permitted a model client, and is therefore the one package that may
   not import `src.execution` or `src.worker`. That prohibition is the price of
   the permission; without it the separation is a convention that one import
   would end. `src/api` may read the programme's rows (`repo`, `flags`,
   `gates`) and may not import its runner (`tick`, `author`, `client`, `main`),
   which would drag the SDK into the process that commands the worker.
6. **Never commit credentials.** Not values, not placeholders, not defaults —
   `docker-compose.yml` reads everything from gitignored `.env`.
7. **The programme's switch fails closed too.** `programme_enabled` is read
   through `src/programme/flags.py` with the same broad `except` as the kill
   switch. The stakes look lower because the process writes rows rather than
   placing orders; they are not. A runaway programme fills the `jobs` queue the
   live decision path shares, and spends money at a model API on every pass.

## Honesty rules

These exist because the research UI is a machine for fooling yourself.

- **Never render a Sharpe without its standard error.** Five years of daily
  data gives roughly ±0.45, so a reported 0.50 is indistinguishable from zero.
  `PerformanceMetrics.sharpe_is_significant` is the check.
- **Never quote a Sharpe from a search without deflating it.** The best of
  fifty parameter sets has a flattering Sharpe by construction.
  `src/engine/statistics.deflated_sharpe_ratio` discounts it for the number of
  attempts; the walk-forward computes it and stores it beside the curve. It
  takes a **per-observation** Sharpe — feeding it an annualised one inflates
  the statistic by `sqrt(periods_per_year)`.
- **An unmeasured metric is never zero.** Everywhere: the scorecard renders
  "not measured", the daily report renders "no data", and both keep a genuine
  zero as a zero. Reporting an unmeasured probability of backtest overfitting
  as 0.00 is the single most flattering lie this system could tell.
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
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
export DATABASE_URL=postgresql://trader@localhost:5432/trader
python -m src.db.migrate_cli                 # apply migrations

# Research CLI
python -m src.cli strategies
python -m src.cli backtest --strategy asset_class_trend_following \
    --source yfinance --start 1999-01-01
python -m src.cli walkforward --strategy asset_class_trend_following \
    --grid '{"sma_period":[105,150,210]}'

# Services (three processes on purpose, see the boundaries below)
uvicorn src.api.main:app --reload            # HTTP control plane
python -m src.worker.main                    # runs backtests and live jobs
python -m src.programme.main                 # the AI programme; needs the extra
                                             # requirements file below
cd web && npm run dev                        # Next.js frontend

# Which model the programme is pointed at, at what effort, under what token
# ceiling, and how often it runs are settings in the control plane, on
# System > Configuration. They are stored in `system_flags`, seeded by
# migration 0010, and re-read on every pass. `PROGRAMME_MODEL` and
# `PROGRAMME_TICK_SECONDS` used to be environment variables and are no longer
# read at all. The API key stays in the environment: it is a credential, and it
# belongs to the one process permitted to hold a model client.

# The programme's dependencies. Deliberately a third file: `anthropic` must not
# be installed alongside the broker credentials.
pip install -r requirements-programme.txt

# Backend stack (db, api, worker) — the frontend deploys to Vercel
docker compose up --build
# ...plus the AI programme, which is the only service needing an API key
docker compose --profile programme up --build
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

# Smoke the DEPLOYED system. Its own npm package so Vercel, which builds web/,
# never installs Playwright. `E2E_CHANNEL=chrome` borrows the installed
# browser instead of downloading one.
cd tests/e2e/live && npm ci && E2E_CHANNEL=chrome npm test
# ...and the authenticated half, which is skipped rather than failed without it
E2E_PASSWORD='…' npm test
```

Everything above runs against a stack this machine stood up. `tests/e2e/live`
is the exception and the reason it exists: it talks to the deployment, where
the routing, the proxy, the headers, the environment and the build are all
different things. It is `workflow_dispatch` only (`.github/workflows/smoke.yml`),
never scheduled, because it performs one deliberately-failed login and
`src/api/throttle.py` backs off per source after five — a scheduled run would
spend those on nobody's behalf. Read-only in every other respect.

Both commands above lint and run everything. The only `ruff` exclusion left is
`src/bankr_client.py` and its test — a reference file no strategy imports,
where reformatting buys nothing and risks breaking the reference.

`anthropic` is deliberately absent from `requirements.txt` and
`requirements-dev.txt`. The engine must run, and be testable, without an LLM
SDK anywhere near it; `src/llm/commentary.py` and `src/programme/client.py`
both import it lazily and degrade rather than fail without it.

It lives in `requirements-programme.txt`, installed only by the programme
process and by `Dockerfile.programme`. Two images rather than one, so the
boundary holds at runtime as well as in review: the worker container, which
holds the broker credentials, could not import an LLM client if its code tried.
The whole unit suite therefore runs on `requirements-dev.txt` alone — every
gate, validator and parser in `src/programme` is testable with no SDK present.

`.github/workflows/ci.yml` runs ruff, the unit suite and the integration suite
against a real Postgres on every pull request, installing only
`requirements.txt`. Parity and the import boundaries get their own named
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
| `src/engine/` | `Driver`, metrics, scheduler, walk-forward, and `statistics.py`: deflated Sharpe, probability of backtest overfitting, capacity, days to exit — all pure |
| `src/strategies/` | Strategy ABC, registry, strategy implementations |
| `src/execution/` | `BrokerAdapter` protocol, `SimulatedBroker`, `AlpacaBroker` |
| `src/data/` | `PriceSource` protocol, yfinance, synthetic generator |
| `src/db/` | asyncpg pool, migrations, repositories |
| `src/api/` | FastAPI control plane |
| `src/worker/` | The only process that runs backtests or places orders. `scheduling.py` turns the calendar plan into queue rows; `maintenance_jobs.py` handles ingest, marks and reconciliation |
| `src/llm/` | Commentary only. Never reachable from the decision path. |
| `src/programme/` | The AI programme. A third process, and the only one permitted a model client. `gates.py` is pure and decides promotions; `tick.py` is one pass; `author.py` is everything the model may write and what happens to it first; `roles.py` is the twelve specialists as vocabulary and `panel.py` is the one function that asks a model to speak as one; `flags.py` holds the fail-closed switches and settings; `models.py` is the provider/model/effort catalogue; `scorecard.py` and `reports.py` are artefacts assembled from rows, with no model prose in either |
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
| A half-configured deployment says what it is missing | `create_app` reports missing settings instead of raising, so `/health`, `/` and `/ready` survive to answer; `/ready` names every gap at once. Raising took down the endpoints whose job is to explain the failure |
| No session exists without a real signing key | `issue_session` and `verify_session` raise `InsecureSecretError` rather than touch a key that fails `session_secret_problem`. The guarantee is on the *operation*, not on startup — `test_secret_requirements.py` proves a token forged under the empty key is refused, and that removing the guard makes it authenticate as `operator` with a 200 |
| A mistyped risk limit is refused, not stored | `RiskLimitsRequest` forbids unknown keys, and `test_risk_limits_contract.py` parses the worker's own source to prove the settable set equals the enforced set |
| An impossible backtest window is a 422 | `calendar.bounds()` is read from the calendar, so it tracks the `exchange_calendars` release rather than a literal that goes stale |
| The model that holds an SDK cannot reach an order | `test_import_boundaries.py::test_the_programme_cannot_reach_an_order` and `::test_the_api_does_not_import_the_programme_runner`. The reverse of the rule above, and the reason `src/programme` is allowed the client at all |
| A failed hypothesis stays in the ledger | A rule on `hypotheses` turns DELETE into a no-op. `test_programme.py::TestTheLedgerCannotBeTidied` proves a blanket `DELETE FROM hypotheses` removes nothing |
| An acceptance test cannot be written after the answer | `experiments.preregistered_criteria` is NOT NULL, refused empty by `record_experiment`, and frozen after insert by a trigger. The conclusion is then `evaluate_preregistered` applied to the engine's own metrics — never typed by hand, never read from prose |
| A human approval confirms a pass, it does not override a failure | `POST /candidates/{id}/promote` re-evaluates the gate at the moment of the click and answers **409 with the unmet criteria** when it has not passed. An operator's route forward is the runner's route forward: produce the evidence |
| Synthetic prices cannot reach operation | `candidates.evidence_is_synthetic` is set by any synthetic-sourced experiment and never cleared; gate 2 → 3 refuses it. Permitted through the research stages on purpose — no equity data host is reachable from this environment, and a pipeline nothing can traverse is untested rather than safe |
| A gate with no criteria never passes | `GateResult.passed` requires a non-empty list. Stages this slice cannot evidence return one unmet criterion naming the missing capability, so an unbuilt stage reads as blocked rather than as unanimous agreement |
| A model cannot close its own finding | `findings_closed_by_an_operator` requires `closed_by LIKE 'operator:%'` on any transition out of `open`, and the API endpoint is the only code that produces that prefix. A role free to retract its own blocking finding has not vetoed anything |
| A veto is a row, not an opinion | `gates._no_blocking_findings` blocks on open, high-or-critical findings from a role in `VETO_ROLES`, and reads none of their text. Prepended to every gate, including the unbuilt ones |
| The runner cannot promote past its ceiling | `programme_max_auto_stage` is read fail-closed to zero and clamped below `FIRST_HUMAN_GATED_STAGE` **on the way out**, not on the way in — so the stored value never masquerades as the effective one, and a boolean stored there does not read as stage 1 |
| The panel reviews before the promotion, not after | `tick._convene` runs, then facts are re-loaded and the gate re-evaluated. A review of something already promoted is an audit, and an audit is not a control |
| An unmeasured metric is never rendered as zero | `ScoreRow.observed` is nullable with no third state, and `test_programme_scorecard.py` asserts it over every row. A card showing 0.00 for an unmeasured probability of backtest overfitting asserts the most flattering possible value for the metric whose purpose is to be unflattering |
| A missing measurement is `unknown`, not `fail` | Same file. An operator who cannot tell them apart will either dismiss real failures or chase phantom ones |
| A search that selected noise cannot reach validation | Gate 1 → 2 refuses a *measured* PBO above `MAX_PBO`. It passes on an unmeasured one, because a single-candidate study has no selection to overfit and refusing on undefined would bar the honest case |
| A shadow book cannot drift from its own decisions | Nothing stores it. `shadow_job._replay` rebuilds it from `shadow_decisions` on every run, filling session S's intents at S+1's open with the same `execute_pending` a backtest uses. `test_shadow.py` asserts two runs over the same log agree |
| Shadow mode reaches no venue | The deployment is created **disabled** and stays so; `_enabled_deployments` filters on status. `test_shadow.py` asserts the `orders` table stays empty |
| Shadow lives in the worker, and the test says why | `src/programme` may not import `live_job`, so the programme enqueues `shadow_decision` and the worker runs it. `test_shadow_mode_lives_in_the_worker_because_of_that_boundary` fails if someone moves it, and explains the fix is to move it back |
| The API cannot reach a model client *transitively* | Every check in `test_import_boundaries.py` used to read one module's own imports, which is enough for a direct `import anthropic` and not enough for an indirect one. `test_the_programme_modules_the_api_imports_hold_no_client` walks the closure, and found a real hole: `src/api` imports `roles` for the role vocabulary, and `roles` imported `client`. `assess` now lives in `panel.py`, which nothing in `src/api` imports |
| An effort level the model rejects is refused, not sent | Effort is a per-model capability — Haiku 4.5 has none and sending one is a 400 on *every* subsequent pass. `src/programme/models.py` carries the supported levels per model, `client.ask_json` omits `output_config` entirely where there are none, and the same `settings_problem` runs at the form and at the row |
| Unusable model settings mean no model call | `flags.model_settings` returns `None` on a missing row, an unreadable value or one the catalogue refuses, and `run_tick` treats that as "reconcile, evaluate and promote, but call nothing". Falling back to a default would spend at a vendor under a configuration nobody chose and write the result into the ledger as though somebody had |
| A model client is never handed a tool | `test_the_model_client_passes_no_tools` refuses the strings `tools` and `tool_choice` anywhere in `client.py` — keyword *or* dict key, since the request is assembled as a dict so `output_config` can be omitted. `test_model_request.py` asserts the same at the wire |

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
`system_flags` (the kill switch, the programme's switch and autonomy ceiling,
and the model settings), `jobs`, `audit_log`, `commentary`.

The AI programme adds `programme_config` (the operating prompt's section 2,
NULL meaning TBD), `hypotheses` (append-only), `candidates` (a hypothesis as one
testable configuration, carrying its lifecycle stage), `experiments` (the
reproducibility record, with immutable preregistered criteria),
`gate_evaluations`, `programme_decisions`, `programme_runs`, `shadow_decisions`,
plus `role_assessments` and `findings` for the specialist panel and its veto.
Three
of those carry rules rather than only columns — the no-delete rule on
`hypotheses`, the immutable-preregistration trigger on `experiments`, and the
operator-only closure constraint on `findings`. See the structural guarantees
above before changing any of them.

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
- **Alpaca has been contacted, read-only, on paper.** `AlpacaBroker` is still
  tested against a fake server modelling the documented contract, and that is
  still where the coverage is. What has now happened once, by hand, is
  `get_account`, `get_positions` and `get_clock` against
  `paper-api.alpaca.markets` through the shipped adapter — the account, the
  empty position map and the market clock all came back correctly parsed. **No
  order has ever been submitted to Alpaca, on paper or live.** `submit`,
  `cancel_all` and `close_position` remain exercised only against the fake.
- Verify which venue a key belongs to before storing it, by trying both. A
  paper key is refused by `api.alpaca.markets` with a 401 and a live key is
  refused by `paper-api.alpaca.markets` the same way, so one pair of requests
  settles it. This is not hypothetical: the dashboard's live/paper toggle
  decides which kind you get, the two look identical apart from a `PK` or `AK`
  prefix, and a live key was pasted here once already. The three gates would
  have refused to trade with it, but "something downstream would have caught
  it" is not a reason to store the wrong credential.
- **Crypto is not supported**, and this fixture does not change that. It has no
  24/7 scheduler, no crypto broker adapter and no venue-aware cost model;
  `src/data/cryptocom_source.py` exists to feed the engine real prices. The
  locked plan is equities first.
- Two strategies are implemented, and one of them is `buy_and_hold`, which
  exists because gate 1 → 2 will not pass a candidate without a benchmark
  comparison and a benchmark the same engine cannot run over the same window
  under the same cost model is not a comparison. The
  awesome-systematic-trading median Sharpe is ~0.35 and seven entries are
  negative; expect disappointment and let the walk-forward say so.
- **The AI programme stops at the gate into broker paper trading.** It carries
  a candidate automatically from concept through rapid research, independent
  validation and shadow operation, with the twelve specialist roles, the
  findings register and the veto mapping in place. It cannot cross into stage
  4: that needs a venue, and Alpaca has never been contacted. Stages 4 to 8
  return *not met — capability absent* and name what is missing. The
  scorecards and the statistics they need (deflated Sharpe, probability of
  backtest overfitting, capacity) are a later slice. See
  `docs/07-ai-programme-spine.md`.
- **Shadow mode proves operation, not performance.** Twenty sessions carries a
  Sharpe standard error near ±4, so the shadow book's equity is not a result
  and the UI says so. It also does not exercise the halting limits: `dry_run`
  seeds the risk gate's equity history from the *paper* book's marks, and a
  shadow candidate has none of its own. Both are what stage 4 is for.
- The programme has never called a model. `ANTHROPIC_API_KEY` is unset in this
  environment, so `author.py`'s prompts and its three validation layers are
  exercised by unit tests against fabricated replies and by nothing else. The
  gates, the reconciliation and the promotions do not need the model and are
  tested end to end against real Postgres.
