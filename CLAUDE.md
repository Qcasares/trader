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
   Engaging it also queues the cancel of this system's orders already at the
   venue; the flag alone stops only new ones.
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
   `gates`) and may not import its runner (`tick`, `author`, `client`, `main`,
   `panel`, `jev_client`, `jev_lane`, `jev_forward`, `jev_jobs`, `jev_plan`,
   `jev_eval`, `web_fetch` and `web_ingest`), which would drag an SDK, the
   planner that fills the queue, or the programme's one road to the open web
   and the job that takes it into the process that commands the worker.
   `test_safety_rule_5_names_every_runner_only_module` holds this list to
   `RUNNER_ONLY`.

   An amendment admitting typed Jev answers to a paper-only order path is
   **proposed** in `docs/08-jev-integration.md`; it lands in phase F and is not
   in force, so until then this rule covers Jev exactly as it covers any other
   model.
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

# The programme's dependencies. Deliberately a third file: the model SDKs,
# `anthropic` and `typesafe-sdk`, must not be installed alongside the broker
# credentials. The .txt is what a person edits; what is installed — by the
# image, programme.yml, CI and a developer alike — is its hash-locked closure,
# wheels only.
pip install --require-hashes --only-binary :all: -r requirements-programme.lock

# After editing requirements-programme.txt or requirements.txt, regenerate the
# lock from the repository root with uv from a throwaway virtualenv (uv is a
# tool, not a dependency of anything here), and commit both files. uv keeps
# every existing pin that still satisfies the source; --upgrade moves them all.
python -m venv /tmp/uv && /tmp/uv/bin/pip install uv
/tmp/uv/bin/uv pip compile requirements-programme.txt --generate-hashes \
    --python-version 3.11 --python-platform x86_64-manylinux_2_28 \
    -o requirements-programme.lock

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

# The Jev client against the real TypeSafe SDK, a fake TypeSafe server over
# real HTTP, and one call end to end into the ledger. Needs the programme's
# lock installed (above) plus `pip install pytest pytest-asyncio`; the
# end-to-end module also needs TEST_DATABASE_URL. Without the SDK every module
# skips itself and pytest exits 5, having collected nothing, so CI's `programme
# sdk` job, which runs exactly this, fails rather than pass on nothing.
pytest tests/sdk -m sdk -q

# Does the TypeSafe key work? Checks that TypeSafe's host accepts the key (a
# listing, no tokens), asks the connectivity probe once through the shipped
# client — the answer, not the listing, proves the pin — and judges it as the
# lane would. Records nothing and prints no secret. Exit 0 pass, 1 fail, 2 no
# key, 3 no verdict (network or vendor trouble, which says nothing about the
# key). Needs the lock installed. `jev-check.yml` runs it by dispatch with the
# repository secret, holding that key and nothing else.
TYPESAFE_API_KEY=… python -m src.programme.jev_check

# What the forward clock has recorded, read from the ledger and nothing else:
# every switch, the pin and today's spend; each session since the registered
# version's first regime job, measured, abstained, late or absent with its
# reason, coverage with its Wilson interval, each model's regimes and its
# agreement with the pre-registered baseline under the plan that registered
# the answers, and the flip rates; and each recorded state against the bars
# stored now. Read-only, one snapshot, `DATABASE_URL` alone, no key. `--json`
# for the rows.
python -m src.programme.jev_eval status
python -m src.programme.jev_eval forward [--since 2026-10-01] [--json]
python -m src.programme.jev_eval forward-audit [--since 2026-10-01]

# Jev's answers against labels (phase C9). Nothing here asks Jev. `labels
# import` and `labels copy` write labels, and `evaluate --record` one
# `jev_evaluations` row, refusing without a commit (`--commit`, `GIT_COMMIT`,
# or HEAD on a clean tree); every other command reads. The export is chosen
# by no answer: it leaves out only the web text the code screen flags
# (`--include-quarantined` keeps that too), never what Jev's screen
# quarantined. One labeller per evaluation, a person's or a dataset's, never
# pooled. Every web excerpt is undated, so a web set's evaluation is an upper
# bound and carries no threshold. `report` lists the newest of each apart,
# with why none could arm a threshold, which nothing in phases C or D1 does,
# and the looks each set, version and question has spent. `--split` has no
# default (plan version 2, phase D1): `dev` scores the development split alone,
# reading no label or date of a test item, its flip rates the population's as
# a look's are, and is never recorded; `test` and `all` read the held-out
# items, a look, and each is taken only with `--record`. Four looks per set,
# version and question, counted across every model, and `usable` refuses a
# fifth. A command or split the harness does not run is refused unread.
python -m src.programme.jev_eval labels export --set research.catalogue \
    --key asset_class --blind [--sample 60] > to_label.csv
python -m src.programme.jev_eval labels import --file labelled.csv \
    --as operator:quentin
python -m src.programme.jev_eval evaluate --set research.catalogue \
    --key asset_class --labelled-by operator:quentin --split dev [--json]
python -m src.programme.jev_eval evaluate --set research.catalogue \
    --key asset_class --labelled-by operator:quentin --split test|all \
    --record [--commit SHA] [--json]
python -m src.programme.jev_eval report [--json]

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

`anthropic` and TypeSafe's `typesafe-sdk` are deliberately absent from
`requirements.txt` and `requirements-dev.txt`. The engine must run, and be
testable, without an LLM SDK anywhere near it; `src/llm/commentary.py` and
`src/programme/client.py` both import `anthropic` lazily and degrade rather
than fail without it, and `src/programme/jev_client.py` imports `typesafe_sdk`
lazily, so it loads anywhere and only a call needs the SDK.

They live in `requirements-programme.txt`, whose hash-locked closure,
`requirements-programme.lock`, is installed only by the programme process, by
`Dockerfile.programme`, by CI's `programme sdk` job and by the dispatch-only
`jev-check.yml`. Two images rather than
one, so the boundary holds at runtime as well as in review: the worker
container, which holds the broker credentials, could not import an LLM client
if its code tried. The whole unit suite therefore runs on
`requirements-dev.txt` alone — every gate, validator and parser in
`src/programme` is testable with no SDK present.

`.github/workflows/ci.yml` runs ruff, the unit suite and the integration suite
against a real Postgres on every pull request, installing only
`requirements.txt` in the job that runs them. A second job, `programme sdk`,
installs the programme's lock to run `tests/sdk`: the one CI job holding a
model SDK, allowed it because it holds no secret and its token can only read.
`jev-check.yml` is the only other workflow besides `programme.yml` that
installs it: dispatch only, one job, a read-only token, and the TypeSafe key as
its one secret (`test_dependency_boundaries.py::test_the_jev_check_holds_the_model_key_and_nothing_else`).
Parity and the import boundaries get their own named steps: when they break,
the failure should say so in the checks list rather than hide in a wall of
dots.

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
| `src/data/` | `PriceSource` protocol, yfinance, synthetic generator, and `reference.py`: the forward clock's reference sleeves, constants the worker and the programme's forward clock both read |
| `src/db/` | asyncpg pool, migrations, repositories |
| `src/api/` | FastAPI control plane |
| `src/worker/` | The only process that runs backtests or places orders. `scheduling.py` turns the calendar plan into queue rows; `maintenance_jobs.py` handles ingest, the forward clock's reference bars, marks and reconciliation |
| `src/llm/` | Commentary only. Never reachable from the decision path. |
| `src/programme/` | The AI programme. A third process, and the only one permitted a model client. `gates.py` is pure and decides promotions; `tick.py` is one pass; `author.py` is everything the model may write and what happens to it first; `roles.py` is the twelve specialists as vocabulary and `panel.py` is the one function that asks a model to speak as one; `flags.py` holds the fail-closed switches and settings, Jev's among them; `models.py` is the provider/model/effort catalogue; `scorecard.py` and `reports.py` are artefacts assembled from rows, with no model prose in either. For Jev: `jev_catalogue.py` is the pin, the limits and the vocabulary, pure and API-importable; `jev_questions.py` the versioned, golden-hashed question sets and their enumerated state models; `jev_hash.py` a request's identity, pure, importable by the API and the harness and, like all of `src/programme`, by neither the worker nor the decision path; `jev_features.py` turns prices into the decision lane's point-in-time state; `jev_validate.py` judges a raw response strictly and never raises; `jev_repo.py` is the ledger's queries, SDK-free; `jev_client.py` is the only importer of `typesafe_sdk`; `jev_lane.py` is the programme's one road to Jev — gate, pin, hash, replay or call once, validate, record — and the one writer of a signal, and `jev_check.py` the operator's, by dispatch, recording nothing, and nothing else imports the client; `web_sources.py` is the web allow-list, the README parser, the excerpt normaliser and the code screen, pure and API-importable, and `web_fetch.py` the programme's one road to the web, runner-only, the only importer of `aiohttp` in the package, and imported by `web_ingest.py` alone, the `jev_web_ingest` job (phase C6), which fetches the allow-list's page once a UTC day, stores what `web_sources.screen_cell` decides through `jev_repo`, the one writer of `web_documents`, and calls nothing. From phase C4: `jev_clock.py` holds the forward clock's times, the worker's own, and its bar loader; `jev_forward.py` is the `jev_regime` job, one session asked before its cutoff, at most one call an attempt, and one answer recorded at most once; `jev_jobs.py` runs the re-asks and, from phases C7 and C8, the `jev_ask` job — one registered set asked about one stored text, a web excerpt read again through the code screen or a title the programme's model wrote, within its cap — and what an answer changes, which is a quarantine and nothing else; `jev_plan.py` is the planner, the only producer of a job that can make a call; `jev_prereg.py` is the analysis plan — version 2 from phase D1: floors by statistic, a family of 20, a 50/50 split, four looks, flips over the population and re-asks not compared counted against the limits — the regime's plan apart, with its baseline rule and sleeves, and, from C7+C8, each set's plan with its keyword baseline, each registered and golden-hashed before any answer and recorded with each; `jev_stats.py` the harness's statistics, a figure over nothing `None`; `jev_eval.py` the harness, `python -m src.programme.jev_eval`, which reads the ledger and, from C9, measures answers against labels, writing labels and evaluations through `jev_repo` in three commands alone; `jev_calibration.py` (C9), pure, when an evaluation could arm a threshold and what an armed one could do, read by the harness and by nothing that acts; `job_errors.py` how a job fails and what an ask comes to as its verdict; and, from C8, `claims.py` the performance-claim check, pure, which `author` re-exports and now screens a hypothesis's title with too. `main.py` runs Jev's jobs and the planner beside the tick |
| `web/` | Next.js frontend. Before any UI change, read `web/CLAUDE.md`: it routes to the design system beside the code (`web/REFERENCE.md`, `web/DESIGN.md`, `web/design-tokens.json`, `web/examples/`), where the honesty rules above are UI rules |

### Structural guarantees

Each is enforced by a test, not by discipline:

| Guarantee | Mechanism |
|---|---|
| No look-ahead | `PricePanel` is built with an `as_of` and refuses to re-slice forward |
| Decision lag | `SimulatedBroker` queues rather than fills; decide on T's close, execute at T+1's open |
| Availability windows | An unlisted asset is excluded from the weighting denominator, not treated as cash |
| Idempotent orders | `client_order_id = "{run_ref}:{session}:{symbol}"`; the venue rejects duplicates |
| Backtest/live parity | `tests/unit/test_parity.py` (synthetic) and `tests/unit/test_real_data.py` (observed prices) |
| The live ingest keeps one adjustment basis | Yahoo back-adjusts `Adj Close` at every distribution, and `run_ingest_bars` refetched ten days, so each distribution left a step at the ten-day boundary and a stored series drifted from any fresh fetch of its history by roughly its yield a year: the live panel was not what a backtest of the same days read. It now refetches each owned symbol's whole stored span, from the earlier of its first stored session and `session - REFERENCE_WINDOW_DAYS` to its latest stored session or the job's, whichever is later, and every stored row the fetch returns takes that fetch's `adj_close`. The download runs in a thread, so the lease and the heartbeat keep answering while years download (`tests/unit/test_reference_bars.py::test_the_fetch_leaves_the_event_loop_free`), and the writes are one transaction, so a failure part-way leaves every stored row as it was (`tests/integration/test_reference_bars.py::TestOneTransaction`). Raw prices are refreshed whole only inside `INGEST_LOOKBACK_DAYS`, as they always were; an older row keeps the open, high, low, close and volume it was first written with, so a split after the fact reprices the shadow replay only inside that lookback, as it always did. A stored session the fetch omits is counted in `rows_not_refreshed`, and a symbol whose session bar it omits is named in `session_missing`, each with a warning and neither fatal; a row the fetch repeats is not rewritten. A span that will not download falls back to the old ten-day window, so the session's bar lands wherever a ten-day fetch would have landed it and the live decision loses nothing; the job then fails, naming the rows it could not re-base, so the worker retries the whole span and `ingest_bars:{session}` succeeds only once one fetch has re-based every stored row it returns. No money reads an old row: `tests/unit/test_daily_bars_readers.py` names every statement that reads the table — a literal, an assembled string, SQL's `TABLE` shorthand or one of asyncpg's table copies — failing on one it does not name, and shows for every registered strategy that scrambling every earlier row's raw prices moves no order. `tests/integration/test_reference_bars.py::TestTheLiveIngestKeepsOneBasis`, `tests/unit/test_reference_bars.py` |
| The risk gate binds live, not just in backtests | `tests/integration/test_live_path.py::TestRiskGateOnTheLivePath` asserts against the shipped job, not the driver it ought to use |
| The halting limits can actually halt | `Driver` populates `RiskState`'s equity fields and seeds them from `daily_marks` on the live path; `tests/unit/test_real_data.py` and `TestMarksFeedTheRiskGate` drive both directions |
| Every scheduled job kind has a handler | `test_scheduling.py::test_every_scheduled_kind_has_a_handler` compares the planner's output against the worker's dispatch table as sets |
| The worker claims only what it can run | The queue is shared with the programme, and a kind with no handler was claimed, failed with `retry=False` and retired for good. `_drain` passes `kinds=list(HANDLERS)`, read at claim time so the filter cannot drift from the dispatch table. `test_worker_claim.py` pins the argument; `test_scheduling.py::TestTheWorkerClaimsOnlyWhatItCanRun` leaves a foreign kind queued and untouched |
| Re-planning a session is free | scheduled jobs carry `dedupe_key = "{kind}:{session}"` under a partial unique index, so a worker restart re-plans without duplicating |
| The rebalance schedule survives a restart | `deployments.last_rebalance` is written after every live decision; `TestTheRebalanceScheduleSurvivesRestarts` requires four consecutive sessions to decline after the first |
| Walk-forward before deployment | `walkforward_runs` persists each study's verdict; the deployment gate refuses without a completed, robust study **for the same parameters** |
| Enabling asks the gate again | `POST /deployments/{id}/enable` used to flip the status and check nothing, while `create` — which only ever writes a disabled row — held the whole gate. The programme inserts its shadow rows directly, and evidence changes after creation. Both now ask one `_deployment_gate`, `enable` of the row as stored, and `enable` answers **409** for any owner but `default` before asking it. `test_deployment_enable_gate.py` asserts every refusal leaves the row disabled |
| A late submission is refused, not filled | `run_submit_orders` expires a batch whose window closed over two hours ago rather than filling at a price the backtest never modelled |
| Honest timestamps | `Driver.step` seeks the injected clock to the session it is processing, so a fill carries the date it happened |
| Venue divergence is visible | `SimulatedBroker.underfunded_buys` records every buy it trimmed that a venue would have rejected |
| Brute force costs more than a shell loop | `src/api/throttle.py` backs off exponentially per source after 5 failed logins; keyed by source, not global, so an attacker cannot lock the operator out of the kill switch |
| No LLM in the order path | `tests/unit/test_import_boundaries.py`, covering `src/worker` and `src/api` as well as the decision path |
| A halted batch is not recorded as sent | `run_submit_orders` writes `partially_submitted` / `blocked_by_kill_switch` / `halted_by_venue`. It is also the retry filter (`status='planned'`), so recording a halted batch as submitted retired the un-sent remainder permanently |
| The kill switch cancels what this system has at the venue | `POST /system/kill` set the flag and nothing more, so an order submitted at the open and not yet filled stayed live at the venue while /system called the state safe; the route's docstring deferred the cancel to an Alpaca adapter that had since shipped. The route now also queues `cancel_open_orders` at priority 100, ahead of anything the planner queues, once the flag has committed on its own, so a queue that refuses the cancel cannot undo the stop. The worker runs it (`src/worker/kill_job.py`) only while the switch is engaged, read again before each venue, because a cancel claimed after a release would cancel what the resumed system had just placed. It cancels by id only this system's orders — a client order id carrying the `{deployment_id[:8]}:` prefix of one of the operator's deployments, which also catches an order the venue accepted before a crash kept it out of the ledger — and counts the rest without touching them, because the job can run minutes after the stop and an account-wide cancel would undo what the operator had since placed by hand. Each venue is handled on its own, so one that fails does not stop the next; each attempt cancels and looks again for up to twenty seconds, since `pending_cancel` is a cancel in flight; and it is confirmed only when the venue reports none of this system's orders open and no order-placing job is running in another worker that could still land one. Anything short of that fails the attempt, which retries, and every attempt is audited, a failed one included. A live venue behind a closed gate, or no credentials, is reported as not reached, never reached around: the three gates bind a cancel as they bind an order. Positions are not closed. `/system/status` reports the cancel for the stop in force as `venue_cancel` — `not_queued` for a switch with no row, which went through no route — and /system says what is still true at the venue in each state, the present state rather than one attempt's count. `KILL_GATED_KINDS` leaves the cancel out, so the switch cannot refuse its own second half, and `test_drain_boundary.py` keeps it undrainable. `tests/unit/test_kill_switch_cancel.py`, `test_alpaca_broker.py::TestKillSwitchSecondLayer`, `test_web_components.py::test_system_says_what_became_of_the_orders_at_the_venue`, and `test_live_path.py::TestTheKillSwitchCancelsAtTheVenue`, from the shipped route through `Worker._execute` to the fake venue over real HTTP |
| A dead worker looks dead | The API derives `stale` from the heartbeat's age against the *database* clock. `worker_heartbeats.status` is `'alive'` while a process runs and `'stopped'` after a clean shutdown, and it cannot report a crash — a process that dies writes nothing, and its row goes on saying `'alive'` — so the age is the input. Not the only one: a clean shutdown stamps a fresh `last_seen`, and read by its age alone a process that had just stopped showed on /system as a green "stopped" with a live halo for a minute. A process is alive only while its heartbeat is fresh *and* says `'alive'`: `web/src/lib/heartbeat.ts` decides it for every page that shows one, and `reports._alive` for the daily report's required actions. The programme's runner writes to the same table, under `programme`, and claims none of the worker's jobs, so /system's "no worker is alive" and the kill switch's cancel note count a worker's rows only (`isWorkerProcess`): counted as a worker, a live runner beside a dead worker kept both silent. `test_worker_liveness.py` keeps the threshold a multiple of the write interval and has the report name a clean stop; `test_web_taste.py` holds every page, and every pulse, to the helper, and `::test_no_worker_is_alive_counts_the_workers_only` the warning to the workers |
| An unready instance is taken out of rotation | `/api/v1/ready` answers **503**, not 200-with-a-false-body. `/health` stays 200 without a database, so a dependency outage cannot cause a restart loop |
| A half-configured deployment says what it is missing | `create_app` reports missing settings instead of raising, so `/health`, `/` and `/ready` survive to answer; `/ready` names every gap at once. Raising took down the endpoints whose job is to explain the failure |
| No session exists without a real signing key | `issue_session` and `verify_session` raise `InsecureSecretError` rather than touch a key that fails `session_secret_problem`. The guarantee is on the *operation*, not on startup — `test_secret_requirements.py` proves a token forged under the empty key is refused, and that removing the guard makes it authenticate as `operator` with a 200 |
| A mistyped risk limit is refused, not stored | `RiskLimitsRequest` forbids unknown keys, and `test_risk_limits_contract.py` parses the worker's own source to prove the settable set equals the enforced set |
| An impossible backtest window is a 422 | `calendar.bounds()` is read from the calendar, whose end is `exchange_calendars`' default, one year from the day the process imported it, so it moves with every start rather than going stale as a literal would. `test_calendar_bounds.py::TestTheUpperBoundMovesWithTheProcess` holds the end to a year from today, so a literal `end` fails it |
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
| The panel actually sits | Until phase A of the Jev integration it did not. `_convene` named the stage's roles `panel` and called `panel.assess` — on the tuple, since the module was never imported. The per-role `except` recorded `assessment_failed` for every role, the gate went on promoting, and ruff, CI and every test stayed green. `panel` is now imported as `specialist_panel`. `test_programme_convene.py` asserts every role is asked and recorded; `test_programme.py::TestThePanelSitsBeforeThePromotion` that a veto raised in a pass blocks that pass |
| A panel that did not finish holds the promotion | Once the panel could sit, the per-role `except` still let a role fail and the pass promote as if it had been heard — the defect above, one role at a time. `_convene` now returns the roles that were due and did not report, and `_advance` withholds the promotion (`promotion_withheld`, the roles named) until they have; only those roles are asked again. The hold outlasts the key: a panel that heard some of its roles and then lost its key or model settings holds until both are back, or until an operator confirms through `POST /candidates/{id}/promote`, which re-evaluates the gate and not the panel. Only a stage with no view on record reads as never convened and holds nothing, by design — which is also how a pass where every role failed looks once the key is gone (docs/08 open item 13). `test_programme_convene.py::TestAPanelThatDidNotFinishHoldsThePromotion` drives each case; `::test_a_panel_that_sat_in_part_holds_after_the_key_is_gone` pins the release it once allowed |
| A role's view and its findings are one write | `_convene` counts a role as heard once its `role_assessments` row exists. Written as separate statements, a failure between the view and its findings — a clash on `findings.ref` when two runners overlap — left the role heard and its objection nowhere, and the next pass promoted past a veto that had been raised and lost. `tick._record_view` writes both in one transaction, a savepoint inside a caller's. A failed write is caught per role, noted as `assessment_unrecorded`, and joins the unheard roles, so the promotion is withheld; `assessment_recorded` and `finding_raised` are noted only after the commit. `test_programme_convene.py::TestAViewAndItsFindingsAreOneWrite`, and `tests/integration/test_programme_panel_atomicity.py`, which forces a real unique violation on Postgres |
| An unmeasured metric is never rendered as zero | `ScoreRow.observed` is nullable with no third state, and `test_programme_scorecard.py` asserts it over every row. A card showing 0.00 for an unmeasured probability of backtest overfitting asserts the most flattering possible value for the metric whose purpose is to be unflattering |
| A missing measurement is `unknown`, not `fail` | Same file. An operator who cannot tell them apart will either dismiss real failures or chase phantom ones |
| A search that selected noise cannot reach shadow operation | Gate 2 → 3 refuses a *measured* PBO above `MAX_PBO`. It passes on an unmeasured one, because a single-candidate study has no selection to overfit and refusing on undefined would bar the honest case |
| An experiment that moves parameters moves them only where the strategy accepts them | The neighbourhood run and the walk-forward grid both moved every numeric parameter by a fixed factor, and a concentration cap at its default ceiling of 1.0 became 1.2 and 1.3, both refused. The neighbourhood experiment was rejected before it was queued, so at the default cap no candidate passed gate 1 → 2. The grid's defect sat behind it: a study was queued, failed in the worker at the first point it could not build, and was queued again on every pass, so gate 2 → 3 could never pass — for the default cap once the neighbourhood was fixed, and already for a configuration that survived 1.2 and not 1.3, such as an SMA period of 800. `tick._neighbouring_params` now steps each parameter up, else down, else holds it, validating every step against the whole schema; a neighbourhood that moves nothing is rejected, since it would read as stability while testing nothing. `tick._grid_around` keeps only the points the schema accepts, and `strategies.refused_grid_point` checks every combination the study will expand, since a rule across parameters can refuse a pair whose values each pass alone: `_enqueue_walkforward` refuses on it before it looks for the backtest to attach the study to, and `POST /backtests/{id}/walkforward` answers **422** naming the point rather than queue an operator's study that can only fail. `test_programme_parameter_moves.py` builds every default neighbourhood and every default grid combination across the registry through `build_strategy`, as the study does; `test_programme_cost_model.py::TestTheWalkforwardGridIsOneTheStudyCanBuild` builds the grid read back from the row; `test_live_path.py::TestWalkForwardIsRequiredToDeploy::test_a_walkforward_with_a_point_the_strategy_refuses_is_refused` holds the route |
| A shadow book cannot drift from its own decisions | Nothing stores it. `shadow_job._replay` rebuilds it from `shadow_decisions` on every run, filling session S's intents at S+1's open with the same `execute_pending` a backtest uses. `test_shadow.py` asserts two runs over the same log agree |
| Shadow mode reaches no venue | The deployment is created **disabled** and stays so. `_enabled_deployments` filters on status **and** on `owner_id = 'default'` (`TRADED_OWNER`), as does the maintenance jobs' selection, so a programme row flipped to enabled by any path still reaches no venue; the API's enable route refuses it first. `test_shadow.py` asserts the `orders` table stays empty; `test_deployment_enable_gate.py::TestTheWorkerTradesOnlyTheOperatorsRows` asserts the filter |
| Shadow lives in the worker, and the test says why | `src/programme` may not import `live_job`, so the programme enqueues `shadow_decision` and the worker runs it. `test_shadow_mode_lives_in_the_worker_because_of_that_boundary` fails if someone moves it, and explains the fix is to move it back |
| The forward clock's prices are the worker's, on one basis where it owns them | `ingest_reference_bars` takes its symbols from `src/data/reference.py`, and a payload's are ignored, so no job row chooses which instruments the worker fetches. Nor does its one field, the session, choose when or how far back: the job is refused outside that session's own window (`maintenance_jobs.reference_window`), by the database's clock — before its close plus `INGEST_AFTER_CLOSE`, when the vendor has only the session in progress to give as its close, and once the next session's bars have settled, when a stale session would count a sleeve's rows only up to itself and backfill years in front of the live ingest's first row. A sleeve is the live ingest's while an enabled operator deployment trades it, judged again inside the transaction that writes, so a deployment enabled while the job downloads takes its sleeve back; disabling the last such deployment hands the sleeve to this job, and enabling one hands it back, so a sleeve is always exactly one job's. A sleeve no enabled deployment trades is refetched over its whole stored span and written as the live ingest writes its own. A sleeve the live ingest owns is fetched only when short of `REFERENCE_MIN_ROWS`, and then only its history before the live ingest's `INGEST_LOOKBACK_DAYS` is inserted, with `ON CONFLICT DO NOTHING`: no row of it is overwritten, and no bar the live ingest refreshes whole — the session's close the live decision sizes its orders from among them — is written by a job the programme enqueues. A sleeve left without its session's close fails the job once what landed has committed, naming the sleeve and whose bar it is, so the worker retries it rather than retire it as done. It is in the worker's `HANDLERS` alone — not scheduled, not kill-gated, not drainable, `shadow_decision`'s precedent — and the programme's planner is its one producer: only `src/programme/jev_plan.py` may enqueue it, only while the programme, Jev and the decisions area are on, and every enqueue must pass `REFERENCE_PRIORITY`, which a test holds below every live-path kind. Nothing in `src/programme`, or anything it loads, writes `daily_bars`, whether the statement is a literal, an f-string, a placeholder or assembled by `+` or `str.join`. `tests/unit/test_reference_bars.py`, `tests/integration/test_reference_bars.py::TestTheReferenceJob`, `::TestTheWindow` and `::TestWhoOwnsASleeve`, `test_import_boundaries.py::test_nothing_in_the_programme_writes_daily_bars` |
| The API cannot reach a model client *transitively* | Every check in `test_import_boundaries.py` used to read one module's own imports, which is enough for a direct `import anthropic` and not enough for an indirect one. `test_the_programme_modules_the_api_imports_hold_no_client` walks the closure, and found a real hole: `src/api` imports `roles` for the role vocabulary, and `roles` imported `client`. `assess` now lives in `panel.py`, which nothing in `src/api` imports |
| Nothing that can move money imports a model client, loads the runner, or names a model vendor's host | `test_import_boundaries.py` builds one import graph of `src/` — `from a import b` read as `a.b` (the old check compared the module alone, so `from src.programme import tick` passed it), relative and function-level imports resolved, package `__init__`s followed, a star import read through a literal `__all__` — and walks the closure from **every** protected package, not only `src/api`, and from the entry points outside `src/`: `api/index.py` and the two scripts that build the API, as `api`; `tests/e2e/broker_check.py` and `src/db/migrate_cli.py`, as the worker. `broker_check`, which places orders, was once missing, so `test_every_credentialed_workflow_command_is_walked` now checks the list against every workflow holding `secrets.ALPACA_*`, `secrets.BANKR_*` or `secrets.DATABASE_URL`, the programme's own command excepted because the reverse boundary binds it. `FORBIDDEN_PREFIXES`, matched on whole dotted segments, adds the TypeSafe names (`typesafe_sdk`, `typesafe`, `typesafe_ai`, `jev`, and `cooksafe`, TypeSafe's own cookbook helper) and the other model SDKs; `httpx2`, the SDK's transport, is deliberately absent, being a general HTTP client like `aiohttp`. `RUNNER_ONLY` adds `panel`, `jev_client` and `jev_lane`. `test_the_order_path_cannot_reach_the_programme_at_all` keeps the decision path and the worker out of `src/programme` entirely. `test_nothing_guarded_imports_by_a_computed_name` reads a direct loader call with literal arguments — `import_module`, `__import__` with its fromlist, `resolve_name`, `pydoc.locate`, uvicorn's `import_from_string` — as the import it is, and refuses the rest: a computed name or fromlist, an aliased or stored loader, `getattr` on a loader module, `runpy`, the spec and path loaders, `exec`/`eval`/`compile`, and a star import through a non-literal `__all__` (`test_a_star_import_is_read_through_all_or_refused`). It reads spellings; it is not a sandbox — a loader it does not know (`mock.patch` with a dotted target, unpickling) is a reviewer's to catch. And because `aiohttp` reaches a model with no import to catch, `test_only_the_jev_modules_spell_the_typesafe_endpoint` keeps `api.typesafe.ai` out of every file but two across `src/`, `web/src/`, `api/`, `scripts/` and the entry points, and `test_nothing_that_can_move_money_names_a_model_vendor_host` refuses a list of vendors' and routers' API hosts in every module a protected process loads and anywhere in `web/src`, with one exemption: the API loads `jev_catalogue`, through `flags`, and the catalogue holds TypeSafe's base URL. For TypeSafe the API's control is therefore the key, not the host: `test_secret_isolation.py::test_only_the_programme_decrypts_a_stored_secret`. The list closes the likely spellings, not every one |
| A model SDK is installed only where it may be imported | `test_dependency_boundaries.py` reads requirements as pip does, includes followed, plus the Dockerfiles, compose and workflows: a model SDK is declared only in `requirements-programme.txt` and its lock, installed only by `Dockerfile.programme`, built only by the `programme` service and installed only by `programme.yml` — `worker.yml` *is* the worker, with the broker keys — by one CI job, and by the dispatch-only `jev-check.yml`, which holds the TypeSafe key and nothing else and installs nothing by name (`test_the_jev_check_holds_the_model_key_and_nothing_else`). `ci.yml` is read job by job, because each job has its own runner: `programme sdk` may install the lock because it references no secret, its token can only read, and it runs nothing but `-m sdk` tests, a marker pyproject.toml registers (`test_ci_holds_a_model_sdk_only_in_a_job_that_holds_nothing_else`, proved on synthetic workflows first by `test_ci_refuses_a_model_sdk_beside_anything_else`; `test_the_marker_ci_selects_is_registered`), and the job running the unit suite may install no SDK at all, which is what keeps "testable with no SDK present" checked (`test_the_unit_suite_runs_where_no_model_sdk_is_installed`). The job reader is checked against PyYAML's, which also proves every workflow parses (`test_the_job_reader_agrees_with_yaml`). The one TypeSafe name allowed is `typesafe-sdk`, from PyPI. `cooksafe` and npm's `@typesafe-ai/sdk` are TypeSafe's own and refused anyway: the programme may hold the SDK and nothing beside it, and the frontend holds no model client. `httpx2` is not a model SDK, and `test_test_tooling_may_install_httpx2` keeps starlette's migration to it open. Nothing redirects pip or uv to another index. None of the eight lookalike hosts docs/08 fact 9 names appears, as a host or a subdomain, in `src/`, `web/src/` or the files that install, build and deploy them; the scan once read three of the eight, and `test_every_host_the_doc_names_is_scanned` now holds it to the doc |
| The programme installs exactly the tree that was checked | `requirements-programme.lock` is the closure of `requirements-programme.txt`, every package pinned to one version and every file to a sha256, and everything that builds, deploys or tests the programme installs it with `--require-hashes --only-binary :all:` — wheels only, because pip does not hash-check what it fetches to build an sdist. `typesafe-sdk` is exactly 0.7.1 — 0.5.7, 0.6.0 and 0.7.0 echo a malformed key into an error — and exactly the two files of it whose attestation was checked; its dependencies, attested by nobody, are locked with it. `test_dependency_boundaries.py::test_the_lock_pins_every_file_it_installs`, `::test_typesafe_sdk_is_the_release_whose_provenance_was_checked`, `::test_the_lock_covers_what_the_programme_declares`, `::test_the_jev_client_imports_only_what_the_programme_declares`, `::test_the_lock_was_resolved_for_the_python_that_installs_it`, `::test_the_programme_set_is_installed_as_the_lock_hash_checked` and `::test_the_programme_set_is_refused_wherever_the_programme_is_not` |
| An effort level the model rejects is refused, not sent | Effort is a per-model capability — Haiku 4.5 has none and sending one is a 400 on *every* subsequent pass. `src/programme/models.py` carries the supported levels per model, `client.ask_json` omits `output_config` entirely where there are none, and the same `settings_problem` runs at the form and at the row |
| Unusable model settings mean no model call | `flags.model_settings` returns `None` on a missing row, an unreadable value or one the catalogue refuses, and `run_tick` treats that as "reconcile, evaluate and promote, but call nothing". Falling back to a default would spend at a vendor under a configuration nobody chose and write the result into the ledger as though somebody had |
| A model client is never handed a tool | `test_the_model_client_passes_no_tools` refuses the strings `tools` and `tool_choice` anywhere in `client.py` — keyword *or* dict key, since the request is assembled as a dict so `output_config` can be omitted. `test_model_request.py` asserts the same at the wire |
| Neither the worker nor the programme holds both a venue key and a model key | Only the API, the worker and the programme load `env_file: .env`, so between them possession is decided by blanking. The worker blanks `SECRETS_KEY`, `ANTHROPIC_API_KEY` and `TYPESAFE_API_KEY`; the API both model keys; the programme `ALPACA_KEY_ID`, `ALPACA_SECRET_KEY` and `BANKR_API_KEY`, because a venue key needs no import to use. `db` loads no `env_file` — it once held every key at once — and is passed `POSTGRES_USER`, `POSTGRES_DB` and `POSTGRES_PASSWORD` by name; `web` loads none. `test_secret_isolation.py` asserts both directions against compose and the workflows, takes the broker key names from `src/config.py` rather than a list, counts only `""` as a blank (a bare `NAME:` passes the shell's value through), refuses a model key read from the environment outside `src/programme`, and refuses the reseller's `JEV_API_KEY` anywhere in product files. `TestEveryComposeServiceIsAccountedFor` reads the services from the file rather than naming three, allows the shared file to those three alone, refuses a key's name in any other service, and renders the file through `docker compose config` with a sentinel for every key to check what each container receives (skipped where compose is absent). Not the API: it holds the broker keys beside `SECRETS_KEY`, which decrypts the stored model keys, for `broker_configured` — docs/08 open item 6. What it may not do is decrypt one: `test_only_the_programme_decrypts_a_stored_secret` keeps the vault's `get` and `crypto.decrypt` inside `src/programme`, under any import spelling, across `src/`, `api/`, `scripts/` and the entry points. And every compose service that connects does so as a superuser, whose `COPY ... FROM PROGRAM` reaches the database container's environment — open item 12 |
| A Jev answer is recorded once and replayed forever | Jev is not deterministic, so a second call would not check the first: it would be a second answer with an equal claim to be right. `jev_lane.ask` hashes the pinned model, the state with its keys sorted and the questions in the order asked, and looks the hash up before it sends anything; the partial unique index `jev_requests_canonical` admits one `ok` row per hash outside the probe lane, and the writer that loses a race for it replays the winner. A probe always asks and is never replayed. `test_jev_schema.py::TestTheCanonicalAnswerIsRecordedOnce`, `test_jev_repo.py::TestTheCanonicalRace`, `tests/unit/test_jev_lane.py::TestARecordedAnswerIsReplayed`, `::TestTheRaceForTheCanonicalAnswer` and `::TestAProbeAlwaysAsks`, and `tests/sdk/test_jev_lane_over_http.py::TestOneCallEndToEnd`, where the second ask makes no HTTP request at all |
| The Jev ledger cannot be tidied | All six Jev tables refuse UPDATE, DELETE and TRUNCATE with an exception — not the silent no-op `hypotheses` uses, because a caller editing an answer is rewriting what the model said and should hear so at once — and TRUNCATE by a statement trigger, which a row trigger never sees. `web_documents` allows one change, a quarantine from false to true with a reason, the rest of the row compared whole through `to_jsonb`. `test_jev_schema.py::TestTheLedgerIsAppendOnly` and `::TestQuarantineIsOneWay` read each row back after the refusal |
| When a Jev row became readable is the database's to say | `available_at` on `jev_requests` and `jev_signals` is overwritten on insert with `clock_timestamp()`, whatever the writer offers — not `now()`, which a transaction held open across a decision cutoff would date too early — and `jev_signals.backfilled` is generated from it and a cutoff held to the session's own day in New York, so nobody writes liveness and nobody can move it beyond that day. The daily budget counts from UTC midnight by the stamp, not by the caller's `requested_at`. A data-only restore therefore needs `--disable-triggers`. `test_jev_schema.py::TestAvailabilityIsStampedByTheDatabase` and `::TestBackfilledIsDerivedNotWritten`; `test_jev_repo.py::TestRequestsToday` |
| A Jev request row carries only the response it got | CHECKs hold each row to its status: `ok` and `invalid` carry a 2xx and the body they were validated from, `IS NOT NULL` spelled out because a CHECK that evaluates to NULL passes; an `ok` row was answered by the model it asked; a refused row got no response; and nothing a response carries — body, request id, answering model — is stored without an HTTP status, which keeps exception text, and any key an SDK before 0.7.1 echoed into one, out of `raw_body`. A request and its answers are one write, a savepoint inside a caller's transaction, and `questions` is `json`, not `jsonb`, so a stored row recomputes its own hash. `test_jev_schema.py::TestARowCarriesOnlyTheResponseItGot`, `test_jev_repo.py::TestAnExchangeIsOneWrite` and `::TestRecordRequest::test_the_stored_request_recomputes_its_own_hash` |
| A Jev response is judged from its raw body, and judging never raises | The SDK's parse reads `NaN`, keeps the last of a repeated name and defaults `answers` to `{}`, so `jev_validate.validate_body` parses the body itself as strict JSON and applies docs/08 fact 3: the pinned model, checked against the catalogue as well as compared; each question judged on its own answer; probabilities keyed exactly and summing to 1 ± 0.02 as the decimals written; the argmax recomputed. It returns a verdict for anything, because a call that was billed must be recorded, and a defect in the module itself refuses every answer as `validator_error`. `test_jev_validate.py::TestNothingRaisesOnAnyInput` judges 4,000 seeded bodies against an independently written copy of the rules; `::TestAResponseThatIsNotJSONIsRefusedWhole` |
| An invalid Jev answer is not measured, and a valid one is a measurement | An invalid answer is recorded with its reason and read downstream as not measured, never as 0. A Choice that is not its own argmax — SDK issue #15, the vendor's `choice` 0.01 below another option — is an abstention, and `true` is not 1. The schema holds the other side: a valid row carries its value, argmax and margin and no reason, and a valid Choice is its own argmax, so a validator that stopped refusing #15 still could not write one. `test_jev_validate.py::TestAChoice::test_a_choice_that_is_not_the_most_probable_is_an_abstention` and `::TestANoul::test_true_is_not_1`; `test_jev_schema.py::TestAValidAnswerIsAMeasurement` |
| A signal's origin is its answer's, not its writer's claim | From phase F the decision path's loader is to trust `provenance = 'internal'`, and a provenance a writer could simply claim would reopen the prompt-injection route that filter closes. The trigger `jev_signals_rest_on_their_answer` requires a signal's lane, provenance and pack hash to be its request's, and a `measured` signal to rest on a valid answer to an `ok`, non-probe request from the model it names; a mismatch raises. `test_jev_schema.py::TestASignalRestsOnItsAnswer` |
| Only one reader and one writer touch the signals | SQL is a string, so no import scan sees it: a module that never imports `jev_repo` can still query `jev_answers` or write `jev_signals` through the connection it already holds. Outside `src/programme` only `src/db/repos/signals.py` (phase F) may name a Jev table, so the decision path has one reader with one fixed filter; only `jev_lane` may write `jev_signals`; and `client`, `author`, `panel` and `tick`, which hold a generative model, name no Jev table. String literals, f-strings and statements assembled by `+` or `str.join` are scanned, by the scanner that holds `daily_bars` to the worker with the table as its argument, a write whose table the scan cannot read counted as a write of this one; each scanner proved against sources that must trip it. A runner could still read the ledger through `jev_repo` without naming a table, so from C4 each runner's whole import closure is walked too, and loads no `jev_*` or `web_*` module but `jev_catalogue`, the vocabulary `flags` reads (docs/08 invariant I8). `tests/unit/test_jev_table_boundaries.py`; `test_import_boundaries.py::test_no_model_runner_loads_a_jev_or_web_module` |
| Evidence remembers the model signals it used, and a forward experiment is paper | `candidates.evidence_uses_model_signals` cannot be cleared once set, by trigger, where `evidence_is_synthetic` is sticky only by convention; the five signal-provenance columns on `backtest_runs` and `walkforward_runs` are all NULL or all set, since half a provenance says nothing; and `deployments_forward_experiment_is_paper` makes a `forward_experiment` paper-only and never owner `default`, so relaxing it takes a migration. `test_jev_schema.py::TestModelSignalEvidenceIsSticky`, `::TestRunsRecordTheSignalsTheyUsed` and `::TestAForwardExperimentIsPaperAndNeverTheOperatorsBook` |
| A Jev question's words cannot change under its version | A threshold is per set, per question and per model, so answers to old words pooled with answers to new ones describe a question nobody asks. Every registered set has a golden pack hash — its name, version, lane, provenance and questions in order, never key-sorted, since option order is part of what the model reads — and the regime set's instructions render the windows and bucket edges `jev_features` computes with exactly, so moving a band from 1% to 1.2% changes the hash. The module's `GOLDEN_PACK_HASHES` sits beside the words, so the test also holds every registered set to `RELEASED_PACK_HASHES`, append-only history kept in the test: re-recording the golden after a rewording, which is the edit a failing hash test invites, still fails. Every Choice carries exactly one escape option, last. The regime's options say what each regime means and name the fields that bear on it, never the labels a rule would test: a rule the state fully determines is code's, the baseline twin's in phase G, and a question spelling one out would leave Jev only a table to misread. `test_jev_questions.py::TestTheGoldenHashes`, `::TestEveryChoiceCarriesAnEscape` and `::TestTheRegimeQuestionIsWrittenPlainly::test_the_options_are_defined_by_meaning_not_by_a_lookup` |
| The decision lane's state is enumerated | Jev holds world knowledge with no disclosed cutoff, and a date, a ticker or an exact figure lets it recall what happened next instead of judging what it was shown. A decision-lane state model may hold only Literal labels, booleans and models built from them, and no computed field or serializer; `QuestionSet.dump_state` takes exactly the registered model, because a subclass passes `isinstance` and can add a computed `as_of`; and `jev_features.regime_state` reads `adj_close` through `PricePanel.at(session)` and returns `None`, never a partial state. It reads shapes, not meanings: a ticker or a date spelled as a label (`spy`, `d20200316`), or a date split into small ordinals, passes it, and a reviewer is the control for that until a golden vocabulary per state is pinned, which phase F needs. `test_jev_questions.py::TestTheDecisionStateIsEnumerated`, including `::test_the_rule_reads_shapes_not_meanings`, and `::TestDumpingAState`; `test_jev_features.py::TestNoLookAhead`, `::TestMissingIsNone` and `::TestEachWindowIsExactlyAsLongAsDefined` |
| Jev is pinned, and an alias is refused | `jev-latest` answers with whatever TypeSafe released last, and every threshold is per model. `jev_catalogue.model_problem` accepts only a versioned id in `KNOWN_MODELS`, refusing the aliases by name in any case or spacing; `flags.jev_model` returns only what it accepts, with no default; the client refuses anything else before the SDK is imported; the validator refuses a response naming another model; and an `ok` row's answering model is its requested one. `test_jev_catalogue.py::TestTheModelIsPinned`, `test_jev_flags.py::TestTheModelIsPinned`, `test_jev_validate.py::TestTheAnswersMustComeFromThePinnedModel` |
| The Jev switches fail closed | Seeded off by migration 0012 and read through `flags.py` with `programme_enabled`'s broad `except`. A switch is on only for a stored JSON `true`; an area needs the master switch and its own, and a name that is not an area is off with no row read; the budget and the state limit read 0, no request, on any failure and on anything the catalogue's `settings_problem` refuses — above its ceiling included, rather than clamped, since a spend control that corrects itself upward is one nobody can reason about. `test_jev_flags.py::TestEveryReaderFailsClosed`, `::TestEverySwitchIsOnOnlyForJsonTrue`, `::TestTheAreaSwitches`, `::TestTheCountsFailClosedToZero` and `::TestTheReadersReadTheSeededKeys`; on Postgres, `test_jev_schema.py::TestTheSwitchesAreSeededOff::test_they_read_as_off_through_the_shipped_readers` |
| Jev off, no model or no key: nothing written, nothing sent | `jev_lane.ask` checks its arguments before any switch, then the switches, the pin, the web gate and the content block, the ledger, the key, the vendor's standing refusals, the budget and the lane's share of it, and the size. A switch off, no usable model, an answer on record and no key write no row: standing states, a model nobody can name, and an answer already there. Over the daily budget or the size limit writes a `refused_budget` or `refused_limits` row and sends nothing. `tests/unit/test_jev_lane.py::TestTheArgumentsAreCheckedFirst`, `::TestSwitchedOffWritesNothing`, `::TestNoUsableModelWritesNothing`, `::TestNoKeyWritesNothing`, `::TestTheBudget` and `::TestTheSizeLimit`; `tests/integration/test_jev_lane.py::TestNothingIsWrittenWithoutARequest` and `::TestARefusalIsRecordedAndSendsNothing` |
| The Jev request that leaves is the request that was hashed | The SDK resolves `TYPESAFE_BASE_URL` with no host check and falls back to `TYPESAFE_DEFAULT_MODEL` and then `jev-latest`. `jev_client` passes the catalogue's base URL, the pin and the key on every call, never names `extra_body`, `extra_headers` or `response_model`, and builds the SDK's `httpx2` client itself, with redirects refused. `tests/sdk/test_jev_client.py::TestWhatLeavesIsWhatWasHashed` records the original URL through a redirecting transport with all three variables set elsewhere, and `test_jev_client_offline.py::TestTheRequestIsNeverRewritten` reads the source. `transport` is a test seam production never passes, to `ask` or to `list_models`: `test_jev_client_offline.py::TestNothingInSrcHandsTheClientATransport::test_production_code_never_passes_one` and `tests/unit/test_jev_lane.py::TestTheTransportIsATestSeam`, each rooted at every function that takes one. No module but `jev_client` imports the SDK, where every one of these safeguards is applied (`test_import_boundaries.py::test_only_the_jev_client_imports_the_typesafe_sdk`) |
| Jev's evidence is what came off the wire | The SDK hands its errors a body it has already parsed and accepts `NaN` in a 200, so a response hook keeps the final attempt's response exactly as it arrived. `raw_body` is those bytes as UTF-8, an undecodable byte or a NUL marked by U+FFFD; the request id is the header's, `None` when absent; every failure returns a `JevCall` classed by `error_kind`, a 403 `auth` with a JSON body and `content_block` without. A 2xx the SDK refused is still judged by the validator, its objection kept in `error_class` and `error_kind`. `tests/sdk/test_jev_client.py::TestASuccessIsRecordedAsItArrived` and `::TestEveryFailureIsClassedWithItsEvidence`; `tests/unit/test_jev_lane.py::TestA2xxTheSDKCouldNotReadIsJudgedByTheValidator`; and `tests/sdk/test_jev_lane_over_http.py::TestAFailureIsARowWithTheEvidenceItHad`, which follows each case into a ledger row |
| A Jev call is billed at most twice, and waits on nobody's say-so | The SDK's default makes three attempts at a POST with no idempotency key, and honours `Retry-After` uncapped. Here: one retry, for 429, 500, 502, 503, 504 and 529, a failed connection or a timeout, inside 20 s, each attempt timed out at 10 s, `Retry-After` not deferred to; and a sliding window beneath the vendor's limits admits every attempt, retries included. `tests/sdk/test_jev_client.py::TestRetriesAreCapped`, `test_jev_client_offline.py::TestTheRateLimiter` |
| Nothing sent to Jev reaches a log | At DEBUG the SDK logs whole request and response bodies, and it reads `TYPESAFE_LOG_LEVEL` once, at import. `jev_client` sets it `off` before its lazy import, then holds the `typesafe_sdk` logger above CRITICAL with a filter that drops every record, on every call, so a later logging configuration cannot undo it; the lane logs neither the state nor the body. `tests/sdk/test_jev_client.py::TestNothingReachesALog`, down to a fresh process told to log at DEBUG; `test_jev_client_offline.py::TestTheSDKIsImportedLateAndSilenced`; `tests/unit/test_jev_lane.py::TestNothingSentReachesALog` |
| Every job kind has exactly one owner | `jobs` has two consumers. The programme claims only `JEV_HANDLERS` — `jev_probe`, `jev_regime`, `jev_reask`, `jev_web_ingest` and `jev_ask` — read at claim time as the worker reads `HANDLERS`, and only while `programme_enabled` and `jev_enabled` are both on: two independent switches, both required, neither derived from the other, so switching the programme off stops Jev's spend as well as the tick's. With either off a queued job waits, its attempts untouched. A running job's lease is extended every 60 s, and a failure's error has the key redacted. A probe that proved nothing — refused, unanswered, invalid or wrong — fails its job with the reason as its error, since the jobs page shows status and error and nothing reads the result column; and at shutdown a running job gets 35 s to finish, so a call that was sent is recorded rather than abandoned and asked again. `test_job_ownership.py::TestEachKindHasOneOwner` and `::TestEveryEnqueuedKindHasExactlyOneOwner` hold the two tables disjoint and every kind enqueued in `src/`, each spelled as a literal, to one of them — `enqueue` taken by a literal name, or off the jobs module by a computed one or its namespace, counting as a kind the scan cannot read — and refuse an `INSERT INTO jobs` anywhere in `src/` but `jobs.py`, which the scan would not see; `::TestTheProgrammeClaimsOnlyItsOwnKinds` and `::TestTheProgrammeRunsWhatItClaims`; `tests/integration/test_jev_lane.py::TestTheProgrammeLoop`, which also starts the whole process once, so a `start()` that forgot the loop fails |
| A stored credential's fallback is documented and delivered | The programme reads each model key from the vault first and its environment second. When `typesafe_api_key` joined `KNOWN_SECRETS`, documenting its fallback in `.env.example` and passing it in `programme.yml` were steps to remember; `test_env_example_is_complete.py::TestTheVaultAndTheEnvironmentAgree` now requires both of every stored secret. `TestTheDangerousDefaultsAreSafe::test_no_secret_has_a_value` finds credentials by the ending of their names rather than a list, which checked `SECRETS_KEY` for the first time |
| Every Jev ask reads all three switches itself | `jev_lane.ask` reads `programme_enabled`, `jev_enabled` and the set's area, each through its own fail-closed reader and none derived from another, and `jev_send_internal_detail` for a set declaring `internal_detail`, on every ask, before the ledger. The loops' checks stay; the road no longer depends on them. `internal_detail` is part of a set's equality, so a copy with it cleared is not the registered set. `tests/unit/test_jev_lane.py::TestTheProgrammeSwitchBindsTheLane` and `::TestTheDetailSwitch` |
| This system's detail goes only where declared (docs/08 fact 7) | A set of provenance `internal`, `operator` or `model` whose state could carry text beyond a plain `title` registers only with `internal_detail`, and the rule fails closed: a field is text unless it is a Literal, a boolean, a number, `None`, or a model or container of those that sends nothing its fields do not declare — so a dataclass, a TypedDict, a URL, a date, a validator standing in for a type and a serializer are all text. The first reading read only `str` and nested models, and a finding's full text in a dataclass registered as no detail and was sent with the switch off. `QuestionSet.dump_state` reads it again from the output on every ask: beyond the top-level title, only the field names and Literal values its model writes may be sent, or the ask raises before any switch is read. From phase D1 a lane in `TEXT_FREE_LANES`, the ops lane, sends no text at all: a set in it registers only declaring `internal_detail`, with a state proved text-free and no field exempted, a title included, and `dump_state` reads what every ask of it would send whatever its `internal_detail`; `system`, this system's own records computed in code, is read as its own text. `test_jev_questions.py::TestTheDetailRuleFailsClosed`, `::TestDumpingWhatAStateSends` and `::TestTheTextFreeLanes`, `test_jev_lane.py::TestUndeclaredDetailIsNeverSent` |
| No answer crosses question sets (docs/08 open item 15) | The request hash names no set, so two sets asking identical words about an identical state would share one canonical answer. The registry refuses a set asking another's questions (`QuestionSet.questions_hash`); `RELEASED_QUESTION_HASHES` is append-only and pairwise distinct, words no longer registered included; and `ask` raises on a row recorded by another pack — before anything is sent when it is the canonical row a replay would read, and after the call when it won a race that call lost, whose answer, billed, is dropped unrecorded like every lost race's (open item 17). `test_jev_questions.py::TestOpenItem15`, `test_jev_lane.py::TestNoAnswerCrossesSets` |
| A text subject is its content | `ask` refuses a subject that is not its state model's (`jev_questions.STATE_SUBJECT`), a `web_excerpt` or `hypothesis_title` subject whose id is not the sha256 of the text sent (`jev_hash.text_sha256`), and a session that is not its date as `YYYY-MM-DD`, so a replay can never answer for another subject and a label joins its answer exactly. A stored document is filed under the same address, by CHECK (`web_documents_content_is_its_excerpt`, migration 0013), so the web gate's quarantine lookup finds it. From phase D1 a subject that is not text is addressed by its whole state where `jev_questions.STATE_ADDRESSED` names its model — empty until D3's job errors — its id `jev_hash.state_hash` of the state sent, and registration refuses a model addressed both ways, one that could carry text, and a set asking about one under another provenance than the mapping's. `test_jev_lane.py::TestSubjectsAreContentAddressed`, `test_jev_questions.py::TestStateAddressedSubjects`, `test_jev_schema.py::TestADocumentIsAddressedByItsExcerpt` |
| A web set is asked only about screened, unquarantined content | Provenance `web` requires `WebExcerptState` at registration, and the other way round; `ask` refuses content quarantined under any source and, for every web set but the screen, content without a clean `guardrail.injection` answer from the screen as registered and the pin — probes included, and before any replay. The screen asks `addressed_to_ai`, as a Noul, and nothing else (`jev_questions.screen_problem`), since it alone may ask about unscreened text; any other set under its name is refused at registration and, placed by hand, clears nothing. With no screen registered, every web ask is refused. `test_jev_lane.py::TestTheWebGate`; `test_jev_questions.py::TestRegistrationRules`; on Postgres, `tests/integration/test_jev_lane.py::TestTheWebGate` and `test_jev_repo.py::TestTheWebReads` |
| The vendor's standing refusals are remembered | An `auth` failure holds every lane until 00:00 UTC, by the database's stamp, a key replaced since included, which only the dispatch-only key check can prove sooner (docs/08 open item 37); a 422 holds `(set, version, pin)` until a new version; content-blocked text — a web excerpt, a hypothesis title — is never sent again, by any set, a probe included, nor its answer read back. An enumerated state is held by no block: an edge's 403 page about labels would otherwise take a regime state out of the forward clock for good (open item 36). Derived from the ledger, so no process writes a switch, and none of the three writes a row. `test_jev_lane.py::TestStandingRefusals`; `tests/integration/test_jev_lane.py::TestTheVendorsStandingRefusals`, `::TestTheWebGate` and `test_jev_repo.py::TestTheStandingRefusals` |
| No lane can starve another | `jev_catalogue.LANE_BUDGET_PERCENT`, code constants summing to at most 100, applied per recorded lane beside the global budget, a probe spending the probe lane's share; from phase D1 research 25, guardrail 25, findings 10, ops 10, signals 0, decision 20, probe 10, the decision lane's twenty untouched. Rounded down, so a budget of 1 to 9 would leave the 10% lanes no call while reading as one that permits some; the catalogue refuses it (`MIN_DAILY_REQUEST_BUDGET`, still 10), naming the lanes with the smallest share, and it reads as 0. `test_jev_lane.py::TestTheLaneSlices`, `test_jev_catalogue.py::TestTheVocabulary`, `::TestTheSettings` and `::TestTheShares`, `tests/integration/test_jev_lane.py::TestTheLaneSlices` |
| Model-written text is labelled `model` | Migration 0013 adds the provenance to both tables' CHECKs, under their old names; `internal` keeps meaning computed in code, which the phase F loader trusts. Registration holds a set to it: `jev_questions.TEXT_SUBJECT_PROVENANCE` names who writes each kind of text, a hypothesis title the programme's model, and a set whose subject is one records that provenance and no other, while text whose writer nobody named is refused. `test_jev_questions.py::TestTextIsRecordedAsItsWriters`; `test_jev_schema.py::TestModelProvenance` applies 0013 over 0012 with rows |
| A Score answer is checked against itself (docs/08 open item 20) | `legend_mismatch`: a legend, where sent, names the levels asked, in order, and fails closed on any other shape. `score_inconsistent`: the score is its own probability-weighted mean within `0.005·(1 + n(n−1)/2)`, on the decimals written — a conservative bound, reading the score's rounding as independent of the probabilities' because the score's grid is unobserved, so it refuses nothing rounding could explain however the score is reported, and admits some answers rounding alone could not produce. A Score question registers only up to four levels, where the 0.02 sum tolerance covers rounding the probabilities. `test_jev_validate.py::TestAScore`, which works out how much of the bound each way of reporting uses, and the 4,000-body fuzz's independent copy of the rules; `test_jev_questions.py::test_a_score_question_registers_only_up_to_four_levels` |
| The web fetcher fetches exactly the allow-list and follows nothing | `web_fetch.fetch` takes an `ALLOWED_SOURCES` entry by identity, its rules checked again and its values compared with the record `web_sources` takes as it loads (`as_written`), and fetches with the recorded values; it raises before any session exists for anything else — an equal copy, a list rebound to hold another page, or the entry itself edited in place to any page, which checking its rules alone once let through; no function takes a URL. The allow-list is one page, validated when `web_sources` loads — `https`, the exact host, no port, user, query or fragment — and a scan of `src/` refuses every spelling of a write to it that it can read: aliases, `vars()` and `globals()`, a computed `setattr`, a descriptor's `__set__`, `object.__setattr__` naming an entry's field. It reads spellings and is not a sandbox; the comparison is what holds. No redirect of any 3xx is followed; `trust_env=False`, so no proxy variable or `.netrc` applies; a resolver refuses the whole answer when any address is not global, the metadata service among them, before a connection is made; TLS is aiohttp's verified default, and nothing in `src/programme` passes `ssl`, `verify` or their kin anything but `True`, `None`, a default context or a keyword-only seam, builds an `SSLContext` without `PROTOCOL_TLS_CLIENT`, assigns `check_hostname` or `verify_mode`, or spreads arguments into a connection, while the Jev client, called with no transport as production calls it, refuses an untrusted certificate; the headers are fixed, and written out in the test, and no cookie or credential is sent; the body is capped as declared, as received and as inflated, gzip inflated a bounded amount at a time; one `Content-Type` the source allows, with `charset=utf-8`, strict UTF-8, 200 only; 5 s to connect and 20 s in all, one attempt, aiohttp's resend after a dropped connection switched off. It never raises for the network, lets cancellation through, and logs status, size and hash, never the body. `session_factory` is a test seam production never passes, read from `src/` by the scan that holds `jev_client`'s transport; `web_fetch` is `RUNNER_ONLY`, and the programme's only way into `aiohttp`, by import, re-export or attribute; it imports nothing that stores or asks. Every control, and every fix its review asked for, was removed in turn and a test failed. `tests/unit/test_web_fetch.py`, over real local HTTPS; `test_web_sources.py::TestTheAllowList` and `::TestNothingInSrcWritesToTheAllowList`; `tests/sdk/test_jev_client.py::TestTLSIsVerifiedWithNoTransport`; `test_import_boundaries.py::test_only_the_web_fetcher_imports_aiohttp_in_the_programme` and `::test_no_programme_module_reaches_aiohttp_but_through_the_fetcher` |
| What the web fetches becomes titles, screened, in one normal form | `web_sources.parse_pwb_readme` keeps each row's title and nothing else — never a figure, a link or a heading — from between the generator's markers only, and refuses a page that has changed shape (`SnapshotRefused`) with a message that carries none of its text: a line that is not blank, a known heading, a table row or the generator's note before the first heading, since a renderer may read it as a heading or hide the rows under it, and a line over 4,096 characters, measured before any pattern reads one. `normalise_excerpt` is idempotent by construction, removes every hidden and unassigned character and every address form a renderer links or a browser acts on, reads each once, works on no more than 2,000 characters, keeps HTML for the code screen to find and never truncates. `code_screen` v1 reads keywords on a skeleton — lookalike letters, accents and emphasis read as the plain word — and its rules, readings and tables are data, hashed, and pinned beside the rules and by a released history in the test, so `code-screen v1` names one rule set for good and re-recording the golden after a change still fails. `screen_cell` decides each row's fate: only words that trip the screen themselves are quarantined, and a row whose decoration alone did is dropped, since quarantine is by content and the decoration leaves a clean title's own address. No line, title or text holds the parser, the normaliser or the screen for long. Every fixture is synthetic: the source publishes no licence. `test_web_sources.py::TestTheParser`, `::TestARefusedSnapshot`, `::TestNoLineHoldsTheParser`, `::TestTheNormaliser`, `::TestTheCodeScreen`, `::TestWhatBecomesOfARow`, `::TestTheAdversarialCorpus` and `::TestTheParserUnderFuzz` |
| The forward clock never backfills and never writes a missing row | `jev_forward.collect`, the `jev_regime` job, asks nothing once the database's clock reaches the session's cutoff, its close plus `scheduler.DECIDE_AFTER_CLOSE` — the moment the live decision is planned (`jev_clock`) — and fails for good, its error quoting the last reason an attempt before the cutoff met; before it, anything that can still change (the area off, no bar, no state, a sleeve the live ingest owns whose `ingest_bars:{S}` has not succeeded, or a sleeve nobody trades now after an attempt of that job did not succeed, unless the reference job for the session re-based it whole — docs/08 open item 40) fails for a retry and writes nothing. The clock is read again before the one ask. An answer, valid or not, is recorded once through `jev_lane.record_signal`, the only `INSERT INTO jev_signals` in `src/`, which refuses any set but a registered decision/internal one and any request row but that set's own, and copies lane, provenance, pack and model from the request row; the database stamps `available_at` and derives `backfilled`, and a session already recorded is read back, not written again. The bar loader reads `adj_close` from `REFERENCE_SOURCE` alone. `tests/unit/test_jev_forward.py`, every row of the handler's state machine; `tests/unit/test_jev_clock.py::TestTheTimes::test_the_cutoff_is_the_workers_decision_time`; `tests/unit/test_jev_lane.py::TestRecordSignalRefuses` and `::TestTheSignalIsItsAnswers`; `tests/integration/test_jev_forward.py`, where every status passes the real trigger and late is the database's word; `tests/sdk/test_jev_forward_over_http.py` |
| Jev's work is planned only while its switches allow it | `jev_plan.plan`, run before each drain at most once a minute in a `try` of its own, is told whether a key exists, never the key, and plans nothing without one or unless `programme_enabled`, `jev_enabled` and a usable pin hold, each through its own fail-closed reader; from phase D1, a set declaring `internal_detail` only while `jev_send_internal_detail` is on, read through its own reader as the road reads it, so no job is queued only to end `disabled` (`tests/unit/test_jev_plan.py::TestTheDetailSwitchGatesPlanning`); the forward clock's jobs also need the decisions area, each re-ask its set's, each `jev_ask` its set's lane's (from C7+C8, nothing that would call while an authentication failure holds the day or of a set the vendor refused with a 422, the screen's repairs, which make no call, planned under either), and the web ingest, once a UTC day for each allowed source and never for a past day, the research area, which its handler reads again, with the programme's switch, the pin and, in `main`'s wrapper, whether a key is set, before it fetches, outside any transaction, so a job queued before the key or the pin went fetches nothing (`tests/unit/test_web_ingest.py`, `tests/integration/test_web_ingest.py::TestTheFetchIsOutsideAnyTransaction`, `tests/integration/test_jev_dark.py::TestAJobQueuedBeforeTheKeyOrThePinWentFetchesNothing`). It enqueues with literal kinds only, under dedupe keys, never a past session, a job that calls only while its lane's share has a call left once the day's calls and the waiting jobs (queued or running, never finished) are counted, each job it plans taking its call from what is left, at most ten re-asks a UTC day however eligibility changes during it, and the reference job with 14 attempts, enough to reach the cutoff (open item 39). The claim needs the programme and Jev; the road needs all three. Seeded, the shipped loop plans, claims and asks nothing; the programme and Jev together plan exactly the daily probe (open item 18). The planner asks nothing itself: its closure reaches no lane, client, asking handler, model runner, vault or decryption, so every call goes through the job loop's claim, its one-call count and its shutdown grace. `tests/unit/test_jev_plan.py`, `tests/integration/test_jev_dark.py`, `test_job_ownership.py::TestThePlannerStep`, `test_import_boundaries.py::test_the_planner_reaches_no_road_to_a_model_and_no_key` |
| Every Jev job makes at most one call an attempt, and records at most one answer | Every outcome the road can return, every error kind among them, run through every handler in `JEV_HANDLERS` and counted, and each handler read for a second call site it can reach, through a table of follow-ups too, or a call inside a loop — the web ingest's for none, since it calls nothing, run to its end so that none is a count; the 35 s shutdown grace covers the one call in flight. Per attempt, not per job: a job's verdict is its status (`jev_jobs.ask_verdict`, the probe's rule for every ask), and a failed call is retried only for no response, a rate limit or a vendor fault — and then asks again, since an `error` row is no answer to replay. So a vendor timing out every call is called for one regime session up to eleven times before its cutoff (the queue's backoff), and a probe, a re-ask or an ask up to three, each call billed at most twice by the client's own retry, the lane's share of the day's budget bounding them all; a response refused whole fails for good, and a session's answer, once recorded, is never asked for again. `test_job_ownership.py::TestEveryJevHandlerMakesAtMostOneCall`, `tests/unit/test_jev_jobs.py` |
| The analysis is registered before the answers | `jev_prereg` holds the split, the size floors, the statistic floors (each met by its statistic's Wilson lower bound at the gate level, never a point estimate), the confidence levels, the bootstrap, the flip limits and the re-ask sample as data, pure, hashed by `plan_hash` and pinned by `GOLDEN_PLAN_HASH`; the test holds both to `RELEASED_PLAN_HASHES`, append-only history kept apart from the plan, moves every constant to prove each is in the hash, and checks the split, the strata and the rule against copies with their numbers as literals. From phase D1 `REGIME_BASELINE_RULE` and the sleeves are a plan of their own, hashed by `regime_plan_hash`, pinned by `GOLDEN_REGIME_PLAN_HASH` and held to `RELEASED_REGIME_PLAN_HASHES`, so a change to either is a `REGIME_PLAN_VERSION` bump that sets aside no other lane's history. The rule is total over all 180 equities states, never abstains and reads only the state's own labels. The rule and the sleeves are the agent's defaults (docs/08, C4): changed before the first regime answer by a free version bump, after it by the same bump recorded as a change of plan — the regime job writes both plans in force into its result and the planner the global one into each re-ask's payload, and the forward report scores agreement only under the regime plan that registered the answer, and counts a flip pair only under the global plan that drew it. `tests/unit/test_jev_prereg.py`; `tests/unit/test_jev_eval.py::TestAnAnswerIsScoredUnderThePlanThatRegisteredIt` and `::TestTheRegimeReport` |
| The analysis was versioned before the answers, and every look through the harness's commands is recorded and counted | Plan version 2 was released while the ledger was empty (phase D1): floors by statistic, a family of 20, a 50/50 split, flips over the population, re-asks not compared counted against the limits, the regime's plan kept apart. `jev_eval.execute` refuses a dry look at the test split and a recorded look at the development split, and fails closed: arguments naming a command the harness does not run (`jev_eval.COMMANDS`) or a split it does not take are refused before any connection, and no command reaches the evaluation by default; `usable` refuses a fifth look of a set, version and question, under any model; `GATE_CI` is spent across family and looks (0.999375). The harness binds only its own commands: `jev_eval.evaluate()`, the function, computes a test-split evaluation and records nothing, and anyone who reads the test split by hand is outside the protocol (docs/08 open item 79). `test_jev_prereg.py::TestTheGateFamily`, `test_jev_eval.py::TestLooks`, `test_jev_calibration.py::TestUsable` |
| A finding says who wrote it, and what was raised stays raised | 0015: `origin` (`'unknown'` only before it, by trigger); `findings_keep_what_was_raised`, under which only the closure's columns change, a closed finding is never reopened, and 0008 still needs an operator to close; `trg_findings_no_delete` and `trg_findings_no_truncate`, so no writer removes a finding, a blocking veto included, and a candidate's delete fails with its findings; and every insert names its writer (`raise_finding`'s keyword-only `origin`, `'model'` from the tick and `'operator'` from the API, as literals). `tests/integration/test_phase_d_schema.py::TestWhatWasRaisedStaysRaised` and `::TestEveryRuleBites`, every rule and conjunct 0015 adds broken alone and read from the catalogue against a database at 0014; `test_jev_table_boundaries.py::test_every_insert_into_findings_names_its_origin`, `::test_every_update_of_findings_sets_closure_columns_only` and `::test_its_callers_pass_literals` |
| Jev's code writes exactly what it is allowed to | A walk from every Jev handler, every askable set's parts and the planner finds exactly the allow-listed `(table, writer)` pairs — the ledger's, the web ingest's, `record_label_once` and `enqueue` — and no write of `system_flags`, nor any change to a job the programme did not claim. `test_jev_table_boundaries.py::TestWhatJevCodeCanWrite`, `::test_nothing_in_the_programme_writes_a_switch`, `test_job_ownership.py::test_nothing_in_the_programme_changes_a_job_it_did_not_claim` |
| The Jev side reads no detail | The title sets read a hypothesis by column list (`jev_repo.get_hypothesis_title`: ref, title, origin, creation time), never through `repo`'s `SELECT *` readers; a reach walk from every Jev handler, every askable set's parts, the planner and every harness command refuses any reachable SQL that reads `*` from `hypotheses`, `findings` or `role_assessments`, names a detail column of them, reads one as a whole row (`to_jsonb(h)`, `SELECT f`) or whole (`TABLE`, `COPY … TO`, asyncpg's `copy_from_table`), or reads one under a column list it cannot read — in any statement, an `INSERT … SELECT` or `UPDATE … FROM` as much as a `SELECT`, its comments read past and a comma join read as a join — proved on synthetic trees calling `repo.get_hypothesis` and `repo.list_findings` and on every spelling D1's review found it missed. `test_jev_table_boundaries.py::test_the_jev_side_never_reads_detail`, `test_jev_jobs.py::TestTheTitleProjection` |
| The harness reads, holds no key, makes no call, and cannot flatter | `python -m src.programme.jev_eval` runs each reading command in one read-only snapshot on `DATABASE_URL` — a write inside it is refused by PostgreSQL itself — and its closure reaches no lane, client, model runner, asking handler, vault or decryption, nor, from C9, the planner. The forward report's field list is pinned, and refuses a return, a P&L or a hit rate by any name; absent sessions stay in the denominator, a late row is never live, and a figure over nothing prints "not measured". Only coverage and the flip rates carry a Wilson interval: shares and agreement over sessions, which repeat one replayed judgement per state, are counted with their distinct states, and agreement over distinct states carries the interval. Each model is reported apart, each answer is scored only under the plan that registered it, a series starts at its own version's first job, and a re-ask with no comparable answer is counted as not compared, never dropped. From C9 it measures answers against labels (docs/08, C9): only `labels import`, `labels copy` and `evaluate --record` write, each in one transaction and through `jev_repo` alone, the one writer of `jev_labels` and `jev_evaluations`; an evaluation is computed against exactly one labeller, never pooled, and scores an answer only under the plans the job that recorded it names, counting the rest apart; `possibly_in_training` is computed from the items' dates against `jev_catalogue.MODEL_FIRST_OBSERVED`, never typed, and migration 0014 refuses a threshold on an upper bound (`NOT possibly_in_training OR threshold IS NULL`) as it refuses every row its eighteen named CHECKs forbid, each conjunct no other rule implies with a case that breaks it alone; `--record` refuses without a 40-hex commit, read from the repository only on a clean tree; Jev beats a baseline only by the exact one-sided sign test of the items one of the two got right, at the gate level, never on a bootstrap bound; every level printed is the row's own; a re-ask that could not be compared is counted, never dropped; the blind export leaves out only the web text the code screen flags, never what an answer quarantined; and `jev_calibration.usable` — which requires the held-out test split to bear a threshold out by the search's own rule — is reported and loaded by nothing that acts, so no lane is calibrated. `test_import_boundaries.py::test_the_harness_holds_no_key_and_reaches_no_client`, `::test_the_pure_modules_load_nothing`, in a fresh interpreter, and `::test_nothing_that_acts_loads_the_calibration`; `tests/unit/test_jev_eval.py`, `test_jev_stats.py`, `test_jev_calibration.py`; `test_jev_table_boundaries.py::test_only_the_repo_writes_jev_evaluations`; on PostgreSQL, `tests/integration/test_jev_harness.py`, every forward report from rows the shipped jobs wrote, `tests/integration/test_jev_evaluations.py`, every 0014 rule biting and each evaluation recorded from a ledger the shipped jobs wrote equal to its recomputation, and `test_jev_repo.py`, each read beneath them |
| `src/cli.py` loads nothing from the programme | The evaluation harness is `python -m src.programme.jev_eval`, never a `src/cli.py` command. The research command line's whole import closure is walked, and loads no module of `src.programme`, so neither the package permitted a model client nor the Jev ledger's readers reach the process that runs backtests. `test_import_boundaries.py::test_the_research_cli_loads_no_programme`, proved on a synthetic tree by `::test_the_research_cli_scan_sees_the_programme_loaded` |
| The daily report's data health is the traded universe's | The latest session is the stalest traded symbol's newest, the traded universe read by the worker's rule (`repo.traded_universe`, held to `maintenance_jobs._deployed_universe` on Postgres), so a fresh reference row cannot make a stale live panel look current; a universe that cannot be read is unknown, never current (docs/08 open item 38). `tests/unit/test_report_data_health.py`, `tests/integration/test_jev_forward.py::TestTheTradedUniverseIsTheWorkers` |
| The runners restart clear of every session's working hours, and never wait on the schedule to do it | `programme.yml` and `worker.yml` each stop a run at the next of five restart slots, 02:30, 07:30, 12:30, 17:00 and 22:30 UTC, so the restarts no longer drift round the clock; none falls from 20:30 to 22:15 UTC, where the ingest, the forward clock, the live decision and the marks sit after a close in both regimes. Each slot has two triggers, neither at it nor on the hour: 41 minutes before, so the successor is already pending in the `concurrency` group when the run stops, and 3 minutes after, which stands in for a late or lost one and restarts the chain from nothing. The first cut fired its crons at the slots, where a trigger finds nothing running to queue behind, so every restart lasted as long as GitHub was late — worst at the top of the hour, and a lost 17:00 event on a summer half day would have taken both processes out through that day's close. `tests/unit/test_jev_clock.py`: `::TestTheRunsStopAtTheSlots` runs the step's own bash for every minute of a day; `::TestASuccessorIsQueuedBeforeEveryStop` models the schedule late, erratic, losing an event and starting cold, and every stop must find its successor queued; `::TestTheRestartsLandOutsideTheWorkingHours`, session by session from 2007-03-12 to the calendar's end, summer half days included |
| Web text is stored in exactly two columns | `web_documents.excerpt`, what the ingest stores, and `jev_requests.state`, what a set was asked about: the design's two, since phases C7 and C8 ask the injection screen and the catalogue about stored excerpts (C6 held it to the first alone). A `jev_ask` job's payload names a document by its id and its subject by its address, never the text, and its result is labels and numbers; a state the validator refuses, and anything else the job raises, is reported without quoting it (`job_errors.described`). `web_ingest`, the `jev_web_ingest` job, stores the README's titles as excerpts, and writes `title` and `published_at` NULL by the statement itself (`jev_repo.insert_documents`), the allow-listed URL and the source's name beside them, and counts and the page's hash in its result. Its errors carry a fetch's failure kind and HTTP status, or the parser's code-written reason, and a failure while storing its class, SQLSTATE and constraint alone, since a driver's message can quote the value it could not take — asyncpg's does. It asks nothing: `run_job` takes no key, `main` drops the one the loop resolves once it has read whether one is set, and its closure reaches no lane, client, model runner or vault (`test_job_ownership.py::TestTheProgrammeRunsWhatItClaims::test_the_ingest_job_is_handed_no_key`, `test_import_boundaries.py::test_the_ingest_job_reaches_no_model_and_no_key`); it is `RUNNER_ONLY`, and the fetcher's one importer, which nothing else takes the fetcher from by name, attribute or literal lookup (`::test_only_the_ingest_job_imports_the_web_fetcher`), and no road to Jev — the lane, its client, the handlers that ask — reaches either (`::test_no_road_to_jev_reaches_the_road_to_the_web`). `tests/integration/test_web_ingest.py::TestTheCanary` serves a synthetic page carrying a token over local HTTPS to the shipped fetcher, runs the job through the programme's loop, and finds the token in `web_documents.excerpt`, one row — every title carrying a token under one marker, so any title's leak is found, not only the watched one's — and in no other text or JSON column of any table in `public` — read from `information_schema`, a column of a type it has not sorted failing it — no log record at DEBUG, and no job's payload, result or error; a token in a line the parser refuses, a row it cannot read, an address the normaliser removes or a row the screen drops is found nowhere at all. `tests/integration/test_jev_research.py::TestTheCanary` takes it end to end: every title of a page carrying a token, fetched over local HTTPS by the real fetcher, read, screened and described through the loop, is in those two columns and no other text or JSON column of any table, no DEBUG log record and no job's payload, result or error, a title refused as its state is built included |
| Quarantine is by content, one-way | `jev_repo.quarantine_content` is the only update of `web_documents` in `src/`, and `jev_repo` the only module that writes it (`test_jev_table_boundaries.py::test_only_the_repo_writes_web_documents` and `::test_the_one_update_of_web_documents_is_quarantine_content`, which read a statement assembled by `+` or `str.join` whole, an insert that goes on `ON CONFLICT … DO UPDATE` as an update, and a write whose table they cannot read as one of this table, each scanner proved on sources that must trip it): it quarantines every document holding exactly that content, under any source, that is not quarantined already, so a concurrent second call waits, updates nothing and raises nothing, and migration 0012's trigger refuses a release, a new reason and an edit. The ingest stores what `web_sources.screen_cell` decides — a quarantine for its rule, a drop counted by rule and stored nowhere — under the content address `jev_lane.ask` recomputes; content quarantined under any source is stored quarantined, naming the earliest such document; and a stored copy the screen now flags, or whose content another document holds quarantined, is quarantined when the page is read again. `insert_documents` is `ON CONFLICT DO NOTHING`, which asks no trigger, so a page read again stores only what changed and a changed title is a new snapshot, and hands back each row's id in the order given, a row already stored under its own id (`test_jev_repo.py::TestTheDocumentWriter`); each snapshot is one transaction, and takes its locks in one order — its documents in the unique index's order, its quarantines, the screen's and the earlier ones together, in content order — because two ingests at once that took them in page order each held what the other waited for, and PostgreSQL ended one with a deadlock. `tests/integration/test_web_ingest.py::TestQuarantineIsByContent`, `::TestQuarantineIsOneWay`, `::TestTheSnapshotIsOneWrite`, `::TestTwoWritersAtOnce` and `::TestAFirstIngest::test_the_address_is_the_one_the_lane_asks_by` |
| The injection screen runs first | The road refuses a web set's ask about text without a clean answer from `guardrail.injection` as registered under the pin (C1+C2's web gate), and from phase C7 the screen is registered, so the catalogue is asked only after it: the planner plans `research.catalogue` only for content the screen cleared — a canonical answer whose screen question is *valid* and `false`, an invalid answer naming `false` included among what it refuses (`jev_repo.documents_to_describe`) — and a tie, which is canonical and replays, holds its text unscreened under that version and pin, never described. Before any ask about web text the code screen reads the stored excerpt again, as it stands now, and a hit is quarantined by content and asked nothing; a re-ask of web text is read through it too. A valid `true` quarantines the text by content, its reason saying it is not calibrated, and a vendor content block on web text quarantines it, found by this call's row or, on any later ask the road refuses for it, the earliest block on record, so a quarantine that failed to write is made by the next attempt or by a later day's screen, which the planner plans for blocked content in use and which makes no call. The screen's own `true` is read back the same way (`jev_repo.screen_flag`, under any version and pin): before any ask about stored web text, a re-ask's included, it quarantines content still in use in the screen's words and nothing is asked, the planner plans that repair too and re-asks no flagged text, and both repairs are planned whatever the vendor holds, since neither makes a call (`tests/integration/test_jev_research.py::TestTheScreensQuarantineSurvivesAFailedWrite` and `::TestABlocksQuarantineSurvivesAFailedWrite::test_the_repair_is_planned_whatever_the_vendor_holds`). Each answer is recorded beside the global plan and its set's own plan in force (`jev_prereg.plans_in_force`), however its job ends: the planner writes them into the `jev_ask` payload and the handler asks nothing under any others, so every row a job records is recorded under the plans its payload names; and the job's row names the request beside them, in the result of a job that fails after its ask wrote a row — a response refused whole, an answer whose follow-up failed — as of one that succeeds, a `JobFailedError` carrying the record and `job_repo.fail` storing it, and keeping an earlier attempt's when a later one records nothing. The first cut recorded them only on success, so a refused answer, which the harness counts, had no plan. So the harness phase C9 builds can score an answer only under the plans it was recorded under, never by a baseline chosen after the answers (`tests/unit/test_jev_jobs.py::TestTheAsk`, `tests/integration/test_jev_research.py::TestEveryAnswerIsRecordedWithItsPlans`). `tests/integration/test_jev_research.py`, `tests/unit/test_jev_jobs.py::TestWhatIsNotAsked`, `::TestWhatAnAnswerChanges` and `::TestAReaskOfText`, `tests/integration/test_jev_repo.py::TestDocumentsToScreen` and `::TestDocumentsToDescribe` |
| The card check is shadow, and code reads the title | `guardrail.card` and `research.hypothesis`, asked from phase C8 about a title the programme's own model wrote and only one within `TITLE_MAX_CHARS`, refused by that number before any state is built, have no follow-up: an answer is recorded and acts on nothing, and no title is ever quarantined. Nothing that writes `hypotheses`, `candidates` or `findings` is reachable from `jev_jobs`: `tests/unit/test_jev_jobs.py::TestTheCardCheckChangesNothing` walks every reference from it over the import graph — an import under any alias, a chain of attributes, a re-export, a star import, `getattr` with a literal, a function stored in a variable or a dict, a literal looked up in `globals()`, `vars()`, `locals()` or `sys.modules`, and a module handed over, read through `vars` or loaded by name reached whole — reads every binding of a name and the code each module it enters runs when imported, so a writer stored into a table by a subscript, a method call, a loop or `setattr` at module level is reached too, and checks everything reached with the shared write scanner, proved on synthetic trees that must trip it; and `tests/integration/test_jev_research.py::TestTheTitleAsksChangeNothing` finds the three tables unchanged under every outcome. The performance-claim check moved, verbatim, into `claims.py`, pure, and `author.propose_hypothesis` now screens the title with it too (`tests/unit/test_claims.py`); the tick loads no `jev_*` or `web_*` module (`test_import_boundaries.py::test_no_model_runner_loads_a_jev_or_web_module`) |

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
the model settings, and the Jev switches), `jobs`, `audit_log`, `commentary`.

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

Migration 0012 adds the Jev ledger: `jev_requests` (every question a lane put
to Jev and every refusal to put one — the operator's key check records nothing — with the state, the questions and the raw body),
`jev_answers` (one per question asked, valid or not), and `jev_signals`,
`web_documents`, `jev_labels` and `jev_evaluations`, created now and filled
from phase C. All six refuse UPDATE, DELETE and TRUNCATE with an exception,
`web_documents` allowing only a one-way quarantine with a reason.
`available_at` is stamped by a trigger with `clock_timestamp()`, whatever the
writer offers, and `jev_signals.backfilled` is generated from it. The partial
unique index `jev_requests_canonical` admits one `ok` answer per request hash
outside the probe lane; CHECKs hold each request row to its status and a valid
answer to being a measurement, a valid Choice its own argmax; and a trigger,
`jev_signals_rest_on_their_answer`, holds a signal's lane, provenance and pack
to its answer's request. `questions` is `json`, not `jsonb`, so a stored
request keeps its option order and recomputes its own hash. 0012 also makes
`candidates.evidence_uses_model_signals` sticky, gives `backtest_runs` and
`walkforward_runs` signal-provenance columns that are all NULL or all set,
adds `deployments.evidence_class` with the CHECK
`deployments_forward_experiment_is_paper`, and seeds the Jev switches, every
one off. A data-only restore needs `--disable-triggers`, or every
`available_at` becomes the moment of the restore.

Migration 0014 gives `jev_evaluations` the columns docs/08's C9 defines — the
split, the plans' and answers' hashes, the levels its intervals and its gates
were computed at, the answer counts, accuracy over every item, the per-class
figures, the threshold's outcome and its group, each baseline's paired
difference with the discordant items it is made of, every flip rate with its
pairs and the re-asks it could not compare, labeller agreement. The split is
required, `all` by default; every measurement is nullable, NULL meaning not
measured. Eighteen named CHECKs hold them, `NOT possibly_in_training OR
threshold IS NULL` and a pinned model id among them, each conjunct no other
rule implies with a case that breaks it alone. The rows stay append-only under
0012's trigger.

Migration 0015 (phase D1) gives `findings` its `origin`: `'unknown'` before
0015, then `'model'` (the tick's panel), `'operator'` (the API) or `'jev'`,
the card check's, which only phase D4's writer raises; the column is `NOT
NULL` with no default, and a trigger refuses `'unknown'` on a new row. It
adds `source_request_id`, and a trigger holding a Jev finding to a valid
`true` of a canonical `guardrail.card` request; the rules that keep a Jev
finding non-blocking, on a candidate and one per answer; a trigger keeping
what was raised, which refuses every change but the closure's, and a reopen;
the refusal of DELETE and TRUNCATE on `findings`, so a candidate's cascading
delete fails with them; the card check's arming switch, off; provenance
`system` on `jev_requests` alone, so `jev_signals` still refuses it; and
0014's flip counts freed from `n`, since plan version 2 counts a flip rate's
pairs over the question's whole population.

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

- **Both implemented strategies have now been measured on real equity prices,
  and the interesting one failed.** The egress policy that blocked Yahoo,
  Stooq and `data.alpaca.markets` no longer does. Over 2007-01-03..2026-07-31,
  `asset_class_trend_following` returns +82.5% at Sharpe 0.303 ± 0.226, which
  is inside two standard errors of zero, and its walk-forward over
  `sma_period` in {105, 150, 210, 252} comes back **NOT ROBUST**: parameter
  stability 44%, stitched out-of-sample Sharpe +0.186 ± 0.251. `buy_and_hold`
  on SPY over the same window returns +428.7% at Sharpe 0.532 ± 0.226 and
  walks forward **ROBUST**, stitched OOS +0.722 ± 0.251, deflated Sharpe
  0.998. The trend follower's one honest advantage is drawdown, -28.2%
  against the benchmark's -56.5%; it buys that with roughly six points of
  CAGR. At 3x costs it decays to Sharpe 0.269, so the result is not a cost
  artefact. The deployment gate refuses it, which is the gate working.
- **The backtest was kinder than a venue would have been.** That run logged 29
  entries in `SimulatedBroker.underfunded_buys`, one trimmed as far as 13.7%
  short. Check that list before believing any result, and set
  `RiskLimits.cash_buffer_pct` when it is non-empty.
- **The engine, separately, has been run on real prices.**
  `tests/fixtures/cryptocom_candles.json` holds 24 daily candles for four spot
  pairs, captured from the Crypto.com public API, and `tests/unit/test_real_data.py`
  drives the whole ingest → panel → driver → gate → metrics path on them —
  including parity. That validates the *machinery*, not any strategy: 24
  sessions is seven weeks, the Sharpe standard error over it is about ±4, and
  the 210-day SMA the one implemented strategy needs is impossible in a window
  that short. Read it as "the plumbing survives contact with real numbers",
  nothing more. Two bugs came out of it, both listed in the git log.
- **An order has now been submitted to Alpaca, on paper.** `AlpacaBroker` is
  still tested against a fake server modelling the documented contract, and
  that is still where the coverage is. What has also happened, from the runner
  that will actually place the orders, is a full pass of the shipped adapter
  against `paper-api.alpaca.markets`: `get_account`, `get_clock`,
  `get_positions`, `submit`, `get_order`, `get_order_by_client_id`,
  `cancel_all` and `close_position`. The deterministic client order id round
  trips, which is the property the worker's retry safety rests on.
  `tests/e2e/broker_check.py` is that pass, and `broker-check.yml` runs it on
  dispatch. **A real fill has now round-tripped.** On 2026-08-26 the live
  worker submitted the first autonomous order (buy 124.240332854 SPY, market,
  `client_order_id 025d937d:20260825:SPY`), the venue filled it at an average
  of 765.335855, and the next morning's reconcile polled `get_order`, wrote
  the first `fills` row, and reported the position matching the venue to all
  nine decimals. Decide → stage → submit → fill → parse → reconcile has run
  end to end against `paper-api.alpaca.markets` on a scheduled session, not a
  probe. One honest caveat: the paper account was not flat — it carries five
  pre-existing positions from an earlier experiment (AAPL, AMZN, GOOGL, MSFT,
  NVDA, ~$95k) that the operator has been asked to clear, so the venue funded
  the buy on paper margin and every daily reconcile flags those five until the
  account is reset. The system's own ledger holds only what it traded.
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
  4. The venue-side prerequisite has since been met — the paper venue has now
  been proven to fill, not merely accept and cancel — but the stage 4 to 8
  gates themselves are still unbuilt: they
  return *not met — capability absent* and name what is missing. The
  scorecards and the statistics they need (deflated Sharpe, probability of
  backtest overfitting, capacity) are a later slice. See
  `docs/07-ai-programme-spine.md`, and `docs/08-jev-integration.md` for the Jev
  integration planned on top of it.
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
- **Jev is built dark, and only the key check has called it.** TypeSafe AI's System One
  model is to categorise research and operations, record signals, and — on
  paper only, and only once the proposed Rule 5 amendment is in force — make
  direct decisions. `docs/08-jev-integration.md` is the plan, the verified
  facts behind it, and the record of each phase. Phase A, the safety
  prerequisites, is done: the panel sits, enabling asks the gate, the worker
  claims only its own kinds, and the import, dependency and key boundaries
  refuse Jev before it arrives. Phase B, the foundations, is done and switched
  off: the ledger (migration 0012), the pure catalogue, question sets, features
  and validator, the client and the lane, and a `jev_probe` job the programme
  claims. Phase C is done: C1+C2 hardened the road, W gave the worker the
  reference bars, C5 built the web allow-list, the README parser and the
  fetcher, C4 starts the forward clock — the planner, the
  `jev_regime` job recording `decision.regime` v1 every session and consuming
  nothing, a daily probe, flip re-asks, the pre-registered analysis plan and
  the read-only harness — C6 the web ingest, a daily job that fetches the
  README, stores its titles, screened, and calls nothing, and C7+C8 the first
  four sets asked about text: `guardrail.injection`, the injection screen, and
  `research.catalogue`, about a stored excerpt the screen has cleared;
  `research.hypothesis` and `guardrail.card`, about a title the programme's
  own model wrote. One `jev_ask` job asks one of them about one subject. A
  screen's `true`, or a vendor's content block, quarantines the content; every
  other answer, the card check's among them, is recorded and changes nothing,
  so the card check runs in shadow. The ingest also records the README's own
  section headings as labels. C9 measures those answers against labels —
  `python -m src.programme.jev_eval evaluate`, against one labeller, a
  person's or the README's own grouping, which is never ground truth — with
  migration 0014, and arms nothing: every web excerpt is undated, so any
  evaluation of a web set is an upper bound and carries no threshold, and
  the calibration rules are read by the harness alone, so every lane stays
  suggestion-only and not calibrated. Phase D — findings routing, ops triage
  and the card check armed (docs/09) — is under way, its first part, D1,
  built: analysis plan version 2, released while the ledger holds no answer,
  with the regime's plan apart and every look at the held-out items counted;
  migration 0015, under which every finding names its writer and what was
  raised stays raised; the title sets reading a hypothesis by column list;
  the registry's rules for subjects addressed by their state and for the ops
  lane, which sends no text; phase D's budget shares; the detail switch read
  by the planner; and the card check's arming switch, seeded off and read by
  nothing that acts. D1 registers no set and plans and asks nothing new; D2
  to D4 are not built. It is all dark: every Jev switch is seeded off,
  so the planner plans nothing, no lane is wired into the tick, and nothing in
  the API or the UI reads the ledger. The regime's baseline rule and the
  reference sleeves are the defaults the agent that built C4 chose, not
  choices the operator has reviewed (docs/08, C4). The client is tested
  against the real SDK and a fake TypeSafe server over real HTTP, as are one
  call end to end into the ledger, the regime job end to end into a signal,
  and a stored excerpt screened and described end to end.
  The key has been proven against TypeSafe itself: on 2026-09-26
  `jev-check.yml` found the `TYPESAFE_API_KEY` secret accepted by TypeSafe's
  host, the listing naming only the aliases `jev-latest` and `jev-preview`,
  and the connectivity probe answered by `jev-1.13.0` in 201 ms — `true` at
  p=0.99, as expected. That is the only traffic so far: the check records
  nothing, and the programme has made no call, since every Jev switch is off.
  Nor has it fetched a page or asked about any text: the ingest job phase C6
  built is planned only while the programme, Jev and the research area are
  all on, a `jev_ask` only while the programme, Jev and its set's area —
  guardrails or research — are, and none has been.
