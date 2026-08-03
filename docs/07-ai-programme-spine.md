# The AI programme

Specification and record of the AI trading programme. Owner: Quentin Casares.
Slices 1 and 2 are built; slice 3 is not. Last revised 3 August 2026.

## What this is

The operating prompt in the request describes a twelve-role programme with
thirteen artefact types, an eight-stage promotion lifecycle and ten families of
metrics. That is a programme, not a feature, so it is decomposed into three
slices, each with its own specification and implementation cycle.

| Slice | Contents | Status |
|---|---|---|
| 1. Programme spine | Configuration, hypothesis ledger, experiment record, lifecycle model, deterministic gate engine, runner process, UI | Built |
| 2. Autonomous loop | Twelve role personas, findings register, veto mapping, autonomy ceiling, shadow operation — **built**. A candidate can now be carried automatically to the gate into broker paper trading | Built |
| 3. Scorecards and reports | Strategy scorecard, daily and monthly reports, validation report, and the statistics they need: deflated Sharpe, probability of backtest overfitting, turnover, capacity | Later |

As built, a candidate can be carried automatically from concept to the gate
into broker paper trading. It cannot cross that gate: stage 4 needs a venue,
and stage 5 is where capital is exposed and no model may decide. Both limits
are described below and both are enforced in code rather than described in
prose.

## The constraint that shapes everything

`tests/unit/test_import_boundaries.py` forbids `src/api` and `src/worker` from
importing any LLM client, because `src/worker` is the only process that places
an order. The operating prompt agrees with the repository here: its §3.6
prohibits an LLM in the synchronous order-approval path, prohibits it
overriding a hard risk limit, and prohibits it changing production capital
allocation.

So the AI layer is a third process. It holds the model client, it talks to the
rest of the system only through Postgres rows, and it is subject to the mirror
image of the existing guarantee: `src/programme` may import `anthropic`, and it
may never import `src.execution`, `src.worker`, or anything else that can
submit an order.

```
   operator ──► web/src/app/programme/ ──► src/api/routers/programme.py
                                                    │  reads rows, enqueues work,
                                                    │  never runs a model inline
                                                    ▼
                                            ┌───────────────┐
   src/programme/  ──────────────────────►  │   Postgres    │  ◄──── src/worker
   the only process holding an LLM client   └───────────────┘        unchanged
```

## The load-bearing idea

**The model never asserts a number.**

It authors hypothesis cards and proposes a configuration: a strategy name, a
parameter set, a universe and a window. Every figure that appears in a
programme artefact is read from a row the deterministic engine wrote, in
`backtest_runs`, `walkforward_runs` or `daily_marks`. `src/programme/gates.py`
is pure Python with no I/O and no model access, and it alone decides whether a
stage's entry criteria are met.

This is the same shape as `src/core`: pure logic, unit-testable without a
database, wrapped by a thin layer that fetches rows. It turns the operating
prompt's §3.2 ("never present a hypothesis, estimate or target as an observed
fact") from an instruction the model might follow into a property of the code.

A proposal is validated against the registered strategy's own `params_model`
before anything is enqueued, so a hallucinated parameter is a validation error
at the boundary rather than a backtest of something nobody designed.

## Schema

One migration, `migrations/0007_programme.sql`.

| Table | Purpose |
|---|---|
| `programme_config` | The §2 configuration, thirty-three keys, seeded NULL. NULL means TBD and renders as TBD. Nothing invents a value. Critical unknowns carry a flag so the UI can separate them from the rest. |
| `hypotheses` | The ledger. `card` holds all eighteen §7.1 fields as JSONB. A rule turns DELETE into a no-op, so "never delete failed hypotheses from the ledger" is a fact about the schema rather than a policy someone remembers. |
| `candidates` | A hypothesis instantiated as one testable configuration, and the row that carries `stage` (0 to 8) and `evidence_is_synthetic`. |
| `experiments` | The §8.4 record: code commit, dataset manifest, seed, training, validation and test windows, universe, cost assumptions, the run identifiers, and the conclusion. `preregistered_criteria` is NOT NULL and a trigger refuses to update it after insert. |
| `gate_evaluations` | Every judgement the gate engine made: each criterion, whether it was met, and the row identifier of the evidence. Append-only. |
| `programme_decisions` | The decision log and the §14 audit record. |
| `programme_runs` | One row per tick. A row with `status = 'requested'` is how the UI forces a tick, because the API must not run one inline for the same reason it never runs a backtest inline. |

Two additions to existing tables rather than new ones: a `programme_enabled`
row in `system_flags`, read through the same fail-closed helper as
`trading_enabled`, and a `worker_heartbeats` row with `worker_id = 'programme'`
so the API's existing staleness derivation covers the new process without
change.

### Why preregistration is a trigger

§5.2 asks the research lead to "prevent research results from being selected
retrospectively without disclosure". A column that can be edited after the
result arrives prevents nothing. Making `preregistered_criteria` immutable
after insert means the acceptance test is fixed before the experiment runs, and
the gate engine evaluates the recorded outcome against it mechanically. The UI
renders the criteria above the outcome for the same reason.

## The gate engine

`src/programme/gates.py` exposes frozen dataclasses and one function:

```python
def evaluate(facts: CandidateFacts) -> GateResult
```

`CandidateFacts` is assembled from rows by `repo.load_facts`, which does the
I/O. `GateResult` carries every criterion with its evidence, whether the gate
passed, and whether promotion needs a human.

| Transition | Criteria, all read from rows |
|---|---|
| 0 → 1 | Card complete; owner set; falsification test stated; simplest credible baseline named; preregistered criteria present; the universe resolves in `daily_bars` for the requested window |
| 1 → 2 | A succeeded backtest; a base-cost result and a stressed-cost result at `cost_stress_multiplier >= 2`; a parameter-neighbourhood experiment; a benchmark comparison; `effective_start` recorded; the preregistered criteria evaluate true against the recorded outcome |
| 2 → 3 | A completed `walkforward_runs` study with `is_robust = true` for the same parameters; an independent replication within tolerance; `sharpe_is_significant` recorded; documented limitations non-empty; **`evidence_is_synthetic` false** |
| 3 → 4 | A deployment exists; at least 20 shadow sessions recorded; none errored; the rebalance schedule actually fired; no buy was trimmed for want of cash |
| 4 → 8 | Declared, and returned as not met naming the missing capability — a venue, a canary allocation, a revalidation cycle |
| every gate | Prepended: no open high or critical finding from a role holding a veto |

### Synthetic data

No result in this repository is a real backtest: the equity data hosts are
blocked by this environment's egress policy. Requiring real data at gate 1 → 2
would therefore block every candidate and make the pipeline unexercisable.

So synthetic evidence carries a candidate through 0 → 1 and 1 → 2, the
candidate is marked `evidence_is_synthetic` indelibly, and gate 2 → 3 refuses
it. The pipeline can be built and tested today, and synthetic data still cannot
approach anything resembling a deployment, which is the rule the API already
enforces at the other end.

## The runner

`src/programme/` is a process, started with `python -m src.programme.main`.

| Module | Responsibility |
|---|---|
| `main.py` | Process entry, the tick loop, the heartbeat, and the fail-closed read of `programme_enabled` |
| `tick.py` | One pass: load pipeline state, evaluate each active candidate's gate, promote where no human is required, enqueue the experiments the next gate needs, and propose new hypotheses when the pipeline has room |
| `gates.py` | Pure. No I/O, no model. |
| `facts.py` | Assembles `CandidateFacts` from rows. I/O, no model. |
| `author.py` | The model calls: hypothesis cards and configuration proposals, returned as structured JSON and validated before anything is written |
| `client.py` | Lazy `anthropic` import, the same pattern as `src/llm/commentary.py` |
| `repo.py` | The asyncpg queries |

A tick that finds `programme_enabled` false does nothing and says so. A missing
row, an unreadable value or a database error is read as false, matching
`flags.trading_enabled()`. A control that defaults to "go" when it cannot
determine the answer is not a control.

The runner enqueues work into the existing `jobs` table using the existing
`backtest` and `walkforward` kinds, which the worker already handles. It does
not add a job kind: `tests/integration/test_scheduling.py` compares the session
planner's output against `SCHEDULED_KINDS` as sets, and a programme tick is not
a session job. Ticks are signalled through `programme_runs` instead.

## API

`src/api/routers/programme.py`. Reads rows, writes operator decisions, enqueues
nothing a model produced without validating it first, and imports no model
client.

| Endpoint | Purpose |
|---|---|
| `GET/PUT /api/v1/programme/config` | Read and set the §2 configuration |
| `GET/POST .../hypotheses`, `GET .../hypotheses/{ref}` | The ledger, including operator-authored cards |
| `GET .../candidates`, `GET .../candidates/{id}` | The pipeline board and one candidate |
| `GET .../candidates/{id}/gate` | The latest evaluation, criterion by criterion, with evidence |
| `POST .../candidates/{id}/promote` | Confirm a passed gate. Refuses when the gate has not passed. |
| `POST .../candidates/{id}/reject`, `.../hold` | The other two decisions |
| `GET .../experiments`, `GET .../experiments/{ref}` | The §8.4 records |
| `GET .../runs`, `POST .../tick` | Tick history, and requesting one |
| `GET .../status`, `PUT .../enabled` | Runner liveness and the AI kill switch |

The promotion endpoint confirms a pass; it cannot override a fail. That is the
difference between a human approval gate and a human override, and the
operating prompt's decision-rights matrix asks for the former.

## UI

`web/src/app/programme/`, following the existing pages' patterns.

The overview carries the autonomy switch with its fail-closed badge, the
runner's heartbeat and staleness, the last tick's summary, the count of
configuration values still TBD, and the pipeline board as stage 0 to 8 columns
of candidate cards.

The configuration page edits the §2 table with TBD highlighted and critical
unknowns separated from the rest. The ledger lists hypotheses including
rejected ones, which are never hidden, because the proportion of failed
experiments retained is one of the programme's own metrics. Candidate detail
renders the gate checklist with each criterion linking to the backtest or
walk-forward page that evidences it. The experiment record renders
preregistered criteria above the outcome.

Every model-authored field carries the AI badge, matching the disclaimer
convention `src/llm/commentary.py` already established: model output is output,
never input.

Promotion, rejection and the autonomy switch use the typed confirmation the
kill switch already uses.

## Verification

| Check | What it proves |
|---|---|
| `tests/unit/test_programme_gates.py` | Table-driven over every stage, met and unmet, with no database |
| `tests/unit/test_import_boundaries.py` (extended) | `src/programme` cannot import `src.execution`, `src.worker`, or a broker adapter |
| `tests/integration/test_programme_ledger.py` | DELETE on `hypotheses` removes nothing; updating `preregistered_criteria` after insert is refused |
| `tests/integration/test_programme_api.py` | Promotion refuses an unpassed gate; a synthetic-evidence candidate cannot pass 2 → 3; an audit row is written |
| `tests/unit/test_programme_author.py` | Model output naming an unregistered strategy, carrying an out-of-schema parameter, or asserting a performance figure is rejected |
| `pytest tests/unit/test_parity.py` | Unchanged, and run before and after |

## Dependencies and deployment

`requirements-programme.txt` is new and installed only by the programme process
and its container. `requirements.txt` and `requirements-dev.txt` stay free of
an LLM SDK, so CI still installs and tests the engine without one anywhere near
it, which is the standing rule in CLAUDE.md.

`docker-compose.yml` gains a `programme` service behind a profile, so the stack
still comes up without an API key.

## Two things the build added that the design did not name

**A benchmark strategy.** Gate 1 → 2 requires a comparison against a passive
benchmark, and the registry held one strategy. A benchmark the same engine
cannot run, over the same window, under the same cost model, is not a
comparison; it is a number quoted from elsewhere. So `src/strategies/buy_and_hold.py`
exists: equal-weight the available universe, rebalance only on drift. It is
deliberately the dullest strategy that can be written, because anything
cleverer would make it a competitor rather than a floor.

**A second Dockerfile.** `Dockerfile.programme` installs
`requirements-programme.txt`; the shared image does not. Building all three
services from one image would leave the SDK sitting in the container that holds
the broker credentials, with only a source-level test between it and an import.
Two images means the boundary holds at runtime as well as in review.

## Slice 2, as built: the controls without the capability

The governance half of slice 2 is in: twelve roles in `src/programme/roles.py`,
a findings register, the veto mapping, and an autonomy ceiling. The order was
deliberate — controls before the capability they control.

**A veto is a row.** A role raises a finding with a severity; a hard-coded rule
in `gates.py` blocks the gate when an open finding is at high or critical
severity *and* was raised by a role in `VETO_ROLES`. Nothing reads the
finding's text. So a role cannot argue a candidate forward by being persuasive,
and a terse critical finding from the risk officer cannot be talked past.

**A model cannot close its own finding.** `findings_closed_by_an_operator` is a
CHECK constraint requiring `closed_by LIKE 'operator:%'` on any transition out
of `open`, and the API endpoint that stamps that prefix is the only code that
produces one. Without this the arrangement is theatre: a role free to retract
its own blocking finding has not vetoed anything.

**Three things must agree before the runner promotes.** The gate passes,
`requires_human` is false, and the stage is within `programme_max_auto_stage`.
That ceiling is a database row read fail-closed to zero, clamped in code below
`FIRST_HUMAN_GATED_STAGE` on the way out rather than on the way in — so the
stored value never masquerades as the effective one, and setting it to 8 cannot
authorise a model to move capital.

**The panel runs before the promotion decision, not after it.** A review of
something already promoted is an audit, and an audit is not a control. The tick
convenes, re-loads the facts, and re-evaluates — so a finding raised on this
pass blocks this pass.

### Shadow mode: the book is derived, never stored

Stage 3 runs the shipped live decision path against a hypothetical book and
submits nothing. The design decision worth recording is that **no book is
stored**.

A stored book would be a second source of truth about a portfolio that exists
only on paper, free to drift from the decisions that produced it, and checking
it against them would *be* the reconciliation rather than the thing reconciled.
So every run seeds a fresh `SimulatedBroker` with a fixed notional and replays
`shadow_decisions` in session order, filling each session's intents at the next
session's open. "The hypothetical positions reconcile" becomes a property of
the arrangement rather than a claim anyone has to check, and the decision lag
comes free from the same `execute_pending` a backtest uses.

Two constraints shaped it. `SimulatedBroker` cannot be seeded with positions,
which rules out rehydrating a stored book without changing a parity-guarded
class; and `dry_run` decides unconditionally by design, so the schedule is
applied by the shadow job against its *own* last rebalance, read from the log
rather than from a deployment whose schedule belongs to a live run that is not
happening.

`src/worker/shadow_job.py` lives in the worker, not the programme, because it
must import `live_job` and the programme may not. The programme enqueues a
`shadow_decision` job; the worker runs it. That is the same boundary that lets
the programme hold a model client at all, and a test asserts the module is
where it is and says why.

The deployment a candidate shadows against is created **disabled** on entry to
stage 3 and stays that way. `_enabled_deployments` filters on status, so the
live loop can never pick it up.

What stage 3 does not prove, and stage 4 exists for: `dry_run` seeds the risk
gate's equity history from the paper book's marks, so a shadow candidate has
none of its own and the halting limits are not exercised. No venue is contacted
either. Both are what broker paper trading is for.

## What this deliberately does not do

No code generation. The model proposes parameters, universes and windows for
strategy classes that already exist and are already tested. Generating a new
`src/strategies/<name>.py` needs a sandbox, an execution boundary and a review
gate, none of which exist, and it is a later slice if it is wanted at all.

No role personas, no findings register, no automatic promotion past stage 2, no
scorecard, no reports, and no new statistics. Those are slices 2 and 3.
