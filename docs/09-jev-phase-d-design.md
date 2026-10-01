# Jev phase D: the synthesised design

Base: `origin/main` at `23dee2b`: phases A, B and C are merged, every Jev
switch is seeded off, and the programme has made no Jev call. The ledger holds
no answer, no label and no evaluation. The repository was read and not
changed.

Binding: CLAUDE.md, above all its safety rules 1, 4, 5 and 7 and its honesty
rules, and docs/08. The parts of docs/08 that matter most here are facts 4, 5
and 7, "Switches, all fail closed", "Lanes", "The Rule 5 amendment — PROPOSED",
"Delivery", "Phase C, as built", and open items 54 to 70.

Safety rule 5 does not change in this phase. No LLM or Jev output reaches an
order, and the amendment stays proposed until phase F. Phase D touches nothing
in the decision path, the signals, the worker, the engine or the three
live-money gates.

This design draws on three proposals, `proposal_safety.md`,
`proposal_measurement.md` and `proposal_operator.md`, written in a working
directory and not committed. Each section names the proposal it follows, and
why. Where all three missed something that the code or the docs require, the
addition is marked **(added)**.

**Revised after review.** Two critiques, safety (`D-SAFE-1` to `D-SAFE-7`) and
honesty (`D-HMB-01` to `D-HMB-16`), were each checked against the code and
docs/08 at `23dee2b`. All twenty-three are real, and every one is resolved
here. A change made for a critique is marked **(revised: id)**. Section 15
lists the alternatives each fix offered that this design did not take, and
why. The largest changes:

- Ops skeletons are sent only while `jev_send_internal_detail` is on, under
  a provenance of their own, `system`.
- Re-judges are replays by construction: they are asked with no key.
- `findings` refuses DELETE, TRUNCATE and a reopen.
- The Jev side reads hypotheses and findings only through column lists, and
  a reach walk holds that.

Every claim below about the code was checked against `23dee2b` in this
session.

- **Words and hashes.** The words in section 2 were built with the shipped
  `QuestionSet`. They passed the real `question_set_problem` and
  `registration_problem` against the real registry, and the suite's wording
  rules. The hashes in section 2.6 were computed from them. `ops.job_error`'s
  pack hash was recomputed under provenance `system` with `PROVENANCES` and
  the detail rule's provenances patched as D1 patches them.
- **Sizes.** The sizes in section 3.6 were computed with `jev_stats.wilson`
  itself.
- **The tests D1 moves** (revised: D-HMB-01). D1's constants, its shares, its
  command-line rules, its migration 0015 and its `raise_finding` signature
  were applied to a scratch copy of `23dee2b`. Both the unit and integration
  suites were then run on that copy and on an unmodified one. The unmodified
  copy passed both suites. Section 13's last table lists every test that
  failed on the D1 copy.

---

## 0. The shape, and the decisions

### The design in brief

Phase D does three things:

- it releases version 2 of the analysis plan, first, while the ledger is still
  empty;
- it registers three question sets;
- it arms one threshold.

Everything goes through the parts phase C already proved:

- one road, `jev_lane.ask`;
- one job kind for stored subjects, `jev_ask`;
- one planner, the only producer of a job that can make a call;
- one ledger writer.

Phase D adds no job kind, no API route or read, no worker change and no gate
change.

**What leaves, and under which switches** (revised: D-SAFE-1, D-SAFE-5).

- A finding title is sent under the findings area, as docs/08 fact 7's
  defaults send titles.
- A job-error skeleton is this system's own text, reduced to a closed
  vocabulary. It is neither a title nor a code-computed feature, so it is
  sent only while `jev_send_internal_detail` is on as well as the ops area.
- A skeleton is recorded under provenance `system`: computed in code from
  this system's records, which can quote an outsider's words. It is never
  `internal`, which the phase F loader is to trust.

**What a Jev answer may change.** In phase C an answer could change one
thing: the injection screen's quarantine. In phase D it can change exactly one
more, and only when all of these hold:

- an operator has switched on `jev_arm_card_check`;
- the newest operator-labelled evaluation of `guardrail.card` under the pin is
  usable;
- the card check answers `true`, validly, at or above that evaluation's
  margin;
- the code's own check accepts the title.

Then the system raises **one non-blocking finding for each active candidate**
of that title's model-written hypotheses. That finding:

- is raised as `jev:guardrail.card`;
- has the severity `medium`, a literal in the statement that writes it;
- is held to low or medium by a CHECK, so it can never block a gate;
- is closed only by an operator.

A named test refuses everything else an answer could touch.

### Decisions where the proposals conflict

| # | Question | Safety | Measurement | Operator | This design | Why |
|---|---|---|---|---|---|---|
| D1 | The global analysis plan | Unchanged. New lanes take the research floor through a mapping kept in a test | Version 2: floors by statistic (R1), a family of 20 (R2), a 50/50 split (M1), flips counted over the population (M2), four recorded looks (M3), the regime's plan kept apart (M4) | Version 2 with lane targets for findings and ops, and nothing else | **Version 2 as measurement proposed, plus M5 (added): re-asks that could not be compared count against the flip limits. Looks are counted per set, version and question across every model (revised: D-HMB-06)** | A target kept in a test is not in the hashed plan, which breaks pre-registration. An answer is scored only under the plans in force (`build_evaluation`), so version 2 is free now and costs every lane's history later. The operator's version 2 leaves the family at 9 of 10, so the next rewording would force a version 3 just when it costs most. The family counts set, version and question, so looks counted per model would let a second pin spend four more outside the 0.05 the level claims |
| D2 | One findings set or two | One set, two questions | Two sets | One set, two questions | **Two sets: `findings.owner` and `findings.severity`** (measurement) | A rewording is a new version, and a new version re-asks every subject. Severity is the question most likely to be reworded or dropped, and on its own it costs owner nothing |
| D3 | The findings words | Areas, never authority | The role's name first, with examples | Similar to safety, with "mandate" | **Safety's options. The tail is reworded so that the cap phrase stands alone** | Each option says what kind of defect falls in an area, so no answer speaks to who may veto. The suite's rules pass |
| D4 | The findings baseline | Keyword rules | **The value already recorded** (`raised_by`, `severity`) | Keyword rules | **The recorded value** (measurement) | "Send it to whoever raised it" is the honest comparison. A weak keyword list would let a chip be called calibrated while it does worse than reading `raised_by` |
| D5 | How severity and owner are shown | Only when it escalates | Nowhere until calibrated | Beside the recorded severity, with a warning when it is lower | **Severity only when it escalates (safety). On a finding that blocks, the owner chip only when it names a role in `VETO_ROLES` (revised: D-SAFE-3). The full answers stay in the ledger** | A lower suggested severity next to a blocking finding is friction removed by persuasion. So is a suggested reviewer without a veto beside a veto that blocks: it argues the veto was raised outside its role's mandate |
| D6 | Duplicates | Code only, exact matches | Jev set deferred | Jev set and a code similarity chip | **Code only: identical normalised titles, oriented by the block. The Jev set and the similarity chip are deferred** | The Jev set needs a two-field subject (a change to the road) and `internal_detail`. Its `true` points at closing a finding, and at the 0.95 target measurement computed about 12,000 labels |
| D7 | The ops state | An enumerated tuple of vocabulary tokens | A redacted string with `internal_detail` | A redacted string with `internal_detail` | **The enumerated tuple (safety), with square-bracket placeholders (added fix), registered with `internal_detail` (revised: D-SAFE-1)** | A skeleton is this system's own text. Fact 7's defaults send code-computed features and titles, and a 48-word sentence over a 400-word vocabulary is neither, so it goes only while `jev_send_internal_detail` is on: the road (`_switched_on`) and the planner both read that switch for a set declaring it. The tuple of `Literal` tokens keeps the second machine check. `dump_state` runs its output check for every set in an ops lane whatever its `internal_detail`, and pydantic refuses any other token. Safety's angle brackets trip the code screen's `markup_in_cell`, which masks `instruction_phrase` (verified) |
| D8 | The ops provenance | `internal` | A new `system` | `internal` | **A new `system` (measurement; revised: D-SAFE-5)** | `internal` means computed in code, "which no outsider can write to" (docs/08, Lanes), and the phase F loader is to trust it. A skeleton's residue is exactly the text code did not write: a library's exception quoting a vendor's reply. A vendor therefore chooses which vocabulary words appear, in which order. Recorded as `internal`, only the lane filters would keep that text from the loader, and provenance would stop being an independent filter. 0015 adds `system` to `jev_requests`' CHECK alone. `jev_signals`' CHECK keeps refusing it, so no ops answer can ever rest under a signal, by the schema as well as by `record_signal` and the loader's lane filter |
| D9 | Which kinds' errors are sent | Research and ingest kinds only | Every worker kind | Every worker kind's residue | **`backtest`, `walkforward`, `ingest_bars`, `ingest_reference_bars` only** (safety) | Venue jobs carry broker responses, quantities and order ids, and their errors are the ones an operator must read whole. Programme kinds' errors are code-built, and triaging them with Jev would be a loop |
| D10 | The ops options | Causes | Fault kinds, including `stopped_on_purpose` | Actions (`wait_and_retry`, …) | **Causes** (safety) | An option that recommends waiting or dismissing removes friction by persuasion. What code knows exactly (a switch, a window) is never asked |
| D11 | Code triage | `code_cause` | — | A pinned table of shapes, held to the raise sites | **Both: `jev_chips.code_cause` over the operator's pinned, hashed table of shapes** | Code places every known shape first, and only the residue goes to Jev. The tests hold the table to the code |
| D12 | The worker's error text | — | — | Prefix the error with its class | **No worker change in D (open item 73)** | The worker places orders. A change to what it records is reviewed on its own |
| D13 | The redactor | An allow-list | A deny-list that admits a residue | An allow-list | **An allow-list: safety's rules, with three fixes (added)**: placeholders taken before the split; square brackets; `finished_at` required | An allow-list fails closed. The fixes are in section 4 |
| D14 | Running the code screen on a skeleton at run time | Tests only | Yes | Yes | **Tests only, but rule by rule rather than first hit (added)** | The vocabulary is static, and the tests prove it cannot satisfy any `instruction_phrase` alternative. The `Literal` and `dump_state` refuse any other word. Read first hit, the check is masked (D7) |
| D15 | Lane shares | Research 25, guardrail 25, findings 10, ops 10 | 30/30/5/5 | 25/30/10/5 | **25/25/10/10, with decision 20 and probe 10** (safety) | A 5% share would raise `MIN_DAILY_REQUEST_BUDGET` from 10 to 20, and a stored budget of 10 to 19 would silently start to read as 0 |
| D16 | What arming does | Moves `candidates.status` from `active` to `held`, with an `audit_log` row | One non-blocking finding | One non-blocking finding per active candidate | **One non-blocking finding per active candidate** (operator, measurement) | docs/08 sanctions it ("rejects or raises a finding", raised as `jev:<set>`). An operator can reverse it, it writes no programme state, and it needs no release route. A hold armed at up to one false positive in ten would freeze candidates with no way back until phase E |
| D17 | An arming switch | Yes | No | Yes | **Yes, `jev_arm_card_check`, seeded off by 0015** | A fail-closed switch and a usable evaluation are two independent conditions, and neither is derived from the other |
| D18 | Where arming lives | A runner-only module, `jev_arming` | Inside `jev_jobs` | Inside `jev_jobs` | **`jev_arming`, runner-only** (safety) | Open item 67 asks for the move. With this module, `jev_calibration` has two importers (the harness and `jev_arming`), and every path from what acts runs through one module |
| D19 | Answers recorded before arming | A daily re-judge by replay, planned behind the switch | Prospective only | A replay planned through a threshold read in SQL | **Safety's re-judge, replay-only by construction: asked with no key (revised: D-SAFE-4, D-HMB-05)** | It adds friction to candidates still in play. The planner reads the switch, never a calibration (`PLANNER_MUST_NOT_REACH`). The operator's version puts calibration logic in the planner. The road replays before it reads the key, so a re-judge whose canonical answer is missing under the pin in force at run time makes no call and is completed as `not_on_record` |
| D20 | Who may label for arming | People only | People only | Anyone | **People only (`operator:`)** | A person's blind labels, never a dataset's |
| D21 | `findings.origin` | Nullable: `model`, `operator` | Nullable, plus `jev` and `source_key` | `NOT NULL DEFAULT 'unknown'`, plus `jev`, `source_request_id`, a trigger and a unique index | **The operator's, plus `DROP DEFAULT` and an insert trigger refusing `'unknown'` (added), with each rule as its own named CHECK. A Jev finding rests on its answer by trigger (revised: D-HMB-11). `findings` refuses DELETE, TRUNCATE and a reopen (revised: D-SAFE-6)** | Every row from 0015 on names its writer, and `'unknown'` means "raised before 0015" and nothing else. What was raised, a blocking veto included, stays raised |
| D22 | The race on `findings.ref` | Raised, unsolved | — | — | **Jev findings take `J-` refs, counted over Jev findings alone (added), padded to at least four digits and never cut (revised: D-HMB-12)** | `repo._next_ref` is `COUNT(*) + 1`. The Jev loop runs one job at a time, so it can never race the tick or the API for an `F-` ref. With DELETE refused, the count only grows, so a ref is never computed twice |
| D23 | The harness's new commands | `suggestions` | — | `preview` | **Both, read-only. `suggestions` prints whether each subject was asked and how it came out, never an answer (revised: D-HMB-04)** | `preview` prints exactly what would leave before an area is switched on. `suggestions` shows the operator the lanes are running. Shown an answer or a chip, a person who later labels the set is no longer blind |
| D24 | Which findings are asked about | Open ones only | Every model-written finding | Open ones only | **Every model-written finding, any status** (measurement) | The population labels are drawn from (every model-written title) is then the population asked about. Asking costs one call, and chips are drawn for open findings only |
| D25 | The pull requests | Four | Five | Two | **Four: D1, plan v2 and the foundations; D2, findings; D3, ops; D4, arming** | Each is reviewed on its own, and D1 merges before any area is first switched on |

---

## 1. Scope, and what is out of scope

### In scope

| PR | Part | Calls Jev? |
|---|---|---|
| **D1** | Plan v2: R1, R2 and M1–M5 (section 3.2) and the regime's plan apart (M4); migration 0015, with provenance `system` on `jev_requests` and `findings` refusing DELETE, TRUNCATE and a reopen; `repo.raise_finding(origin=…)` at its two callers; `jev_repo.get_hypothesis_title`, the title sets' read by column list (revised: D-SAFE-2); two registry rules, `STATE_ADDRESSED` and `TEXT_FREE_LANES`, and `system` in the catalogue and the detail rule; `flags.jev_arm_card_check`; the lane shares; the planner's detail-switch rule (section 5.2); the boundary tests, the detail-read reach walk among them; every existing test D1 moves (section 13) | No |
| **D2** | Findings routing: `FindingTitleState`, `findings.owner` v1 and `findings.severity` v1, their plans with the recorded-value baseline, their `ASKABLE` entries, the planner rule, `jev_chips` (the route, severity and duplicate chips), and the harness's `finding_title` subject, `preview` and `suggestions` (findings half) | Yes, dark |
| **D3** | Ops triage: `jev_redact`; `jev_chips.code_cause` with its table of shapes; the reconciliation and data-health chips (code only); `JobErrorState`, `ops.job_error` v1 (provenance `system`, `internal_detail`) and its plan; the `ASKABLE` entry; the planner rule; the harness's `job_error` subject, its labels read back through their state (revised: D-HMB-07); the canary | Yes, dark, and only while the detail switch is on too |
| **D4** | The card check armed: `jev_calibration.ARMABLE`, `arming` and `card_addition`; `jev_arming`; `repo.raise_card_finding`; the re-judge step, replay-only by construction; the move across the boundary (open item 67); the property tests | No new call; it acts on the card's answers |

### Out of scope, on purpose

| Not in D | Why |
|---|---|
| Any page, route or API read | Phase E. D proves none is needed now: every output of D is a ledger row, a job result or a finding, and the read-only harness shows each one (`preview`, `suggestions`, `status`, `report`). `jev_chips` and `jev_redact` are pure, so E can import them. The API's only change is one literal argument on a write it already makes (`create_finding` passes `origin="operator"`), and `src/api` still loads no runner module |
| Sending reconciliation discrepancies or data-quality alerts | Every field is code-computed (`maintenance_jobs.run_reconcile`'s `{deployment_id, kind, symbol, ours, venue[, drift]}`; `reports._data_health`'s counts, symbols and note). A rule the state fully determines belongs in code, and these rows carry the account's positions and cash. The chips are code's |
| Triage of venue kinds (`live_decision`, `submit_orders`, `cancel_open_orders`, `eod_marks`, `reconcile`), of `shadow_decision`, and of the programme's own kinds | D9 |
| A Jev duplicate-finding question, and a code chip for similar titles | D6. Open item 71 |
| Sending a card's body or a finding's detail | The operator has not chosen to send detail (docs/08 defaults). `ops.job_error` declares `internal_detail` because a skeleton is this system's own text. It sends no body and no detail, and is sent only while the detail switch is on (D7) |
| Jev writing, editing, closing or re-rating a finding; any write to `hypotheses`, `candidates`, `role_assessments`, `programme_decisions` or `system_flags` | The task's facts and docs/08's Lanes. Section 6 names the test that refuses each |
| Arming the injection screen's line (open item 54), or any chip | `document_path` takes no calibration, and every web excerpt is undated (open item 65). Chips stay "not calibrated" in D |
| Held-out dataset import (`jev_eval_items`) | An imported item cannot be asked under its set's provenance (`TEXT_SUBJECT_PROVENANCE`), and items crafted to calibrate do not transfer (fact 5). Measurement's Q9 and safety's §1 agree |
| The worker, the gates, the engine, signals, the decision path | Untouched. Parity runs in CI because CLAUDE.md says so, not because anything there changes |

---

## 2. The question sets, word for word (final)

These words are final. Section 2.6 gives the pack and questions hashes of
exactly these strings. Building each set with the shipped `QuestionSet`, they
pass the real `question_set_problem` and `registration_problem`, with the
mappings in section 2.1 added. They also meet every wording rule the suite
applies (`TestEverySetIsWrittenPlainly`):

- the escape option is last, and is the only escape;
- no negating word appears;
- the first sentence of every instruction is the question;
- every backticked name is a field of the set's state;
- each cap is rendered from its constant.

The four phase C sets keep their words. `guardrail.card` v1 keeps its words,
pack hash `3f98bbc1…e0ebd455` and plan. D4 changes only its `purpose`, which is
prose: it is not hashed, though it is part of the set's equality.

### 2.1 State models and registry mappings

```python
# jev_questions.py — D2
#: roles.ProposedFinding.title's max_length; a test holds the two equal.
FINDING_TITLE_MAX_CHARS = 200

class FindingTitleState(BaseModel):
    """The title of a finding the programme's model wrote, and nothing else."""
    model_config = _STATE_CONFIG
    title: Annotated[
        str, StringConstraints(min_length=1, max_length=FINDING_TITLE_MAX_CHARS)
    ]

# jev_questions.py — D3 (jev_redact is pure, the standard library alone)
class JobErrorState(BaseModel):
    """A failed research or ingest job's error, as a skeleton: its kind, and
    its message reduced to tokens of a closed vocabulary and placeholders."""
    model_config = _STATE_CONFIG
    job_kind: Literal[jev_redact.TRIAGED_KINDS]
    error: Annotated[
        tuple[Literal[jev_redact.TOKENS], ...],
        Field(min_length=1, max_length=jev_redact.SKELETON_MAX_TOKENS),
    ]

def job_error_subject(state: JobErrorState) -> str:
    """A job_error subject's address: jev_hash.state_hash of the state as sent."""
    return jev_hash.state_hash(state.model_dump(mode="json"))

# (revised: D-HMB-07) The subject's text, as the export shows it and the
# baseline reads it, and the way back. Tokens hold no space, and no job kind
# holds ": ", so the text names exactly one state; a test holds the round trip
# over the fuzz, and refuses any text that is not one.
def job_error_text(state: JobErrorState) -> str:
    return f"{state.job_kind}: {' '.join(state.error)}"

def job_error_from_text(text: str) -> JobErrorState | None:
    """The state a subject's text names, or None for text that names none."""
```

| Mapping | Gains | PR | Rule it feeds |
|---|---|---|---|
| `STATE_SUBJECT` | `FindingTitleState: "finding_title"`; `JobErrorState: "job_error"` | D2; D3 | The lane holds a request's subject type to its state model's |
| `TEXT_SUBJECT_FIELD` | `FindingTitleState: "title"` | D2 | A text subject's id is `text_sha256` of that field |
| `TEXT_SUBJECT_PROVENANCE` | `"finding_title": "model"` | D2 | A finding title is recorded as the panel model's text, never `internal` |
| `STATE_ADDRESSED` **(new; safety; revised: D-SAFE-5)** | A mapping from a state model to the provenance every set asking about it records. Empty in D1; `{JobErrorState: "system"}` in D3 | D1; D3 | A non-text subject addressed by its whole state. `subject_id == jev_hash.state_hash(sent_state)` is checked in `jev_lane._check_subject` beside the text rule. Registration refuses: a model in both `STATE_ADDRESSED` and `TEXT_SUBJECT_FIELD`; one that could carry text under the detail rule with no exemption; and a set asking about it under any provenance but the one it names, as `TEXT_SUBJECT_PROVENANCE` does for text |
| `TEXT_FREE_LANES` **(new; safety; revised: D-SAFE-1)** | `frozenset({"ops"})` | D1 | Registration refuses an ops-lane set unless it declares `internal_detail` **and** the detail rule proves its state text-free with no exemption, not even `title`. `QuestionSet.dump_state` runs its output check (`_sends_undeclared_text`, with no `title` exempted) on every ask of a set in these lanes **whatever its `internal_detail`**. So the detail switch gates what is sent, and the check of what is sent stays |
| `jev_catalogue.PROVENANCES` and `jev_questions._OWN_TEXT_PROVENANCES` **(revised: D-SAFE-5)** | `"system"` | D1 | `system` is this system's own records, computed in code and able to quote an outsider. The detail rule reads it as this system's own text |
| `jev_catalogue.SUBJECT_TYPES` | `"finding_title"`; `"job_error"` | D2; D3 | Vocabulary. `subject_type` has no CHECK in 0012 |

Each new model was checked this session against the rules.

- **`FindingTitleState`**: `_model_carries_text(…, exempt=("title",))` is
  `False`, so it registers under provenance `model` without `internal_detail`,
  as fact 7's "findings as titles only" intends.
- **`JobErrorState`**: `_model_carries_text(…, exempt=())` is `False`. Every
  value is a `Literal` written in code. Registered with `internal_detail` and
  provenance `system`, `ops.job_error` passed the real `question_set_problem`
  and `registration_problem` with `system` patched in. `dump_state`'s output
  check, run with no `title` exemption as the D1 rule runs it, admitted a
  sample dump.

The lane holds no content block on a `JobErrorState`: it is enumerated, not
text (`jev_lane._is_text`), as with the regime state (open item 36).

### 2.2 `findings.owner` v1 — lane `findings` (area `findings`), provenance `model`, `FindingTitleState`, subject `finding_title`

```python
_FINDING_TAIL = (
    "`title` is the title of a finding, a defect that one of this system's "
    "reviewing specialists recorded against a trading strategy under test. It is "
    f"up to {FINDING_TITLE_MAX_CHARS} characters, and it is all the text given."
)

FINDINGS_OWNER = QuestionSet(
    name="findings.owner", version=1, lane="findings", provenance="model",
    questions=((
        "owning_role",
        {
            "type": "choice",
            "instructions": (
                "Which specialist's area of responsibility does the defect in "
                "`title` belong to? " + _FINDING_TAIL
            ),
            "criteria": {
                "quant_research": "The trading idea itself: its economic mechanism, who takes the other side of the trade and why, or whether its result holds across nearby parameter values.",
                "data_engineering": "The data: information used before it was available, survivorship in the universe, corporate actions handled inconsistently, or gaps in the price history.",
                "machine_learning": "A model that forecasts, ranks or classifies: leakage of the target, validation that ignores time order, or complexity that adds little over a simple baseline.",
                "portfolio_construction": "Turning signals into a portfolio: unintended concentration, turnover, correlation with strategies already held, or risk and liquidity limits.",
                "independent_risk": "Risk to capital: drawdowns, exposure concentrated in one regime or a few trades, or a halting limit that would fail to act.",
                "execution": "Turning decisions into orders: fill prices, trading costs and spreads, or trade sizes larger than a market would absorb.",
                "platform": "Reproducing and operating the work: a result that the recorded commit, seed or dataset fails to rebuild, or a change that is hard to reverse.",
                "independent_validation": "Whether a claim follows from its evidence: a metric that disagrees with the rows it cites, an acceptance test looser than the hypothesis promised, or more tests run than the analysis admits.",
                "compliance": "Approvals, records and permitted use: data used outside its licence, a decision recorded with its reasons missing, or a running configuration that differs from the approved one.",
                "operations": "Keeping the intended portfolio and the actual one in agreement: reconciliation, state lost on a restart, or positions and cash that rest on a single source.",
                "adversarial_review": "Whether the result is an artefact: a stress that would break it, such as doubled volatility, halved liquidity, stale data or rejected orders.",
                "programme_director": "Priorities and economy: whether the work is worth the attention it takes, or whether a simpler strategy already held does the same job.",
                "unclear": "The defect in `title` fits two or more of the areas above about equally well, or fits each of them only weakly.",
            },
        },
    ),),
    state_model=FindingTitleState,
    purpose=(
        "Suggests the specialist area a finding the programme's model raised "
        "falls in, from its title alone. Suggestion-only: nothing it answers "
        "writes, routes or closes a finding."
    ),
)
```

### 2.3 `findings.severity` v1 — lane `findings`, provenance `model`, `FindingTitleState`, subject `finding_title`

```python
FINDINGS_SEVERITY = QuestionSet(
    name="findings.severity", version=1, lane="findings", provenance="model",
    questions=((
        "severity",
        {
            "type": "choice",
            "instructions": (
                "How serious is the defect in `title`? " + _FINDING_TAIL
                + " Seriousness is about whether the strategy's result can be "
                "trusted and whether running the strategy is safe."
            ),
            "criteria": {
                "low": "A minor weakness: the result stays trustworthy and the strategy safe, and fixing it would improve the record.",
                "medium": "A real weakness that limits how far the result can be trusted, while leaving it usable.",
                "high": "A defect that makes the result untrustworthy or the strategy unsafe to run until it is fixed.",
                "critical": "A defect that invalidates the result entirely, or exposes capital to a loss the controls would fail to stop.",
                "insufficient_evidence": "The title leaves the seriousness open: it fits two or more of the levels above about equally well, or fits each of them only weakly.",
            },
        },
    ),),
    state_model=FindingTitleState,
    purpose=(
        "Suggests how serious a finding the programme's model raised reads, from "
        "its title alone. Suggestion-only: nothing it answers writes a finding's "
        "severity or status, and a suggested level is shown only where it is more "
        "serious than the one recorded."
    ),
)
```

### 2.4 `ops.job_error` v1 — lane `ops` (area `ops`), provenance `system`, `internal_detail`, `JobErrorState`, subject `job_error`

```python
# jev_redact.py: the placeholders, in their order, each with what it stands for.
PLACEHOLDERS: Mapping[str, str] = MappingProxyType({
    "[number]": "a number",
    "[id]": "an identifier mixing letters and digits",
    "[name]": "a name written with capital letters",
    "[word]": "another word",
    "[date]": "a date",
    "[time]": "a time of day",
    "[address]": "a web, network or code address",
    "[path]": "a file path",
    "[quoted]": "quoted text",
    "[value]": "the value given to a setting",
    "[secret]": "a credential",
    "[more]": "words left out at the end",
})
SKELETON_MAX_TOKENS = 48

# jev_questions.py
def _placeholder_legend() -> str:
    items = [f"{token} {meaning}" for token, meaning in jev_redact.PLACEHOLDERS.items()]
    return ", ".join(items[:-1]) + ", and " + items[-1]

OPS_JOB_ERROR = QuestionSet(
    name="ops.job_error", version=1, lane="ops", provenance="system",
    # (revised: D-SAFE-1) This system's own text: sent only while
    # jev_send_internal_detail is on. TEXT_FREE_LANES requires it, and
    # dump_state checks what is sent all the same.
    internal_detail=True,
    questions=((
        "cause",
        {
            "type": "choice",
            "instructions": (
                "What most likely caused the failure recorded in `error`? `error` "
                "is the error message of a failed background job of the kind "
                "named in `job_kind`, reduced to at most "
                f"{jev_redact.SKELETON_MAX_TOKENS} words from a fixed technical "
                "vocabulary and kept in their order, and each word outside that "
                f"vocabulary is replaced by a placeholder: {_placeholder_legend()}. "
                "It is all the text given."
            ),
            "criteria": {
                "network": "A connection to another service failed, was refused, was reset or timed out.",
                "rate_limit": "Another service refused the request because too many requests were made in a short time.",
                "vendor_service": "A data vendor or another outside service reported an error or an outage, or sent a reply that was empty or unreadable.",
                "credentials": "A key, password or permission was missing, wrong, expired or refused.",
                "data_missing": "Data the job needed was missing: prices, sessions, rows or records it expected to find.",
                "data_invalid": "Data the job read was malformed, inconsistent or outside the range it accepts.",
                "configuration": "A setting, parameter or other input given to the job was invalid or contradictory.",
                "database": "The database refused or failed an operation: a constraint, a lock, a deadlock or its own connection dropping.",
                "resource_limit": "The job ran out of time, memory, disk space or another resource.",
                "code_defect": "A defect in this system's own code: an unexpected exception such as a missing attribute, a wrong type or an index out of range.",
                "unclear": "The error fits two or more of the causes above about equally well, or fits each of them only weakly.",
            },
        },
    ),),
    state_model=JobErrorState,
    purpose=(
        "Suggests the most likely cause of a failed research or ingest job that "
        "code's table of known failures cannot place, from a skeleton of its "
        "error message. A cause, never an action: nothing it answers retries, "
        "resumes, cancels or fails a job, or reads or writes a switch. This "
        "system's own text, so it is sent only while jev_send_internal_detail "
        "is on."
    ),
)
```

Rendered, the instructions read as follows. The bound and the legend come
from `jev_redact`'s constants, so moving either moves the pack hash:

> What most likely caused the failure recorded in `error`? `error` is the error message of a failed background job of the kind named in `job_kind`, reduced to at most 48 words from a fixed technical vocabulary and kept in their order, and each word outside that vocabulary is replaced by a placeholder: [number] a number, [id] an identifier mixing letters and digits, [name] a name written with capital letters, [word] another word, [date] a date, [time] a time of day, [address] a web, network or code address, [path] a file path, [quoted] quoted text, [value] the value given to a setting, [secret] a credential, and [more] words left out at the end. It is all the text given.

### 2.5 Why these words

**Areas, never authority (safety).** Each owner option paraphrases its role's
`mandate` and `looks_for` from `roles.py`, positively, since the suite refuses
a negation and Jev reads literally. No option mentions a veto, blocking or who
may close. Routing is about subject matter, and words about authority would
invite an answer about authority. All twelve roles are offered, the director
included, because docs/08's Lanes row says "the twelve plus unclear". The
options follow `roles.ROLES`' order, then the escape; a test holds them equal.

**Two sets, one question each (measurement).** Each is versioned and evaluated
alone. Rewording the severity scale, which measurement expects to fall short
of 0.80 from a title alone, leaves every answer about the owner standing. The
cost is one more call per distinct title, from the findings share.

**The severity scale is the panel's.** `roles.system_prompt` says "High and
critical are for defects that make the result untrustworthy or unsafe". The
levels say the same, so a suggested level means what a recorded one means. The
options follow `roles.SEVERITIES`' order, then the escape `insufficient_evidence`,
where the operator proposed `unclear`. Two proposals chose
`insufficient_evidence`, and it names what is missing: evidence of
seriousness.

**Neither the raiser nor the recorded severity is in the state.** Either
would let Jev echo the very value it is compared with (section 3.4).

**The tail is reworded.** Safety's tail put "up to 200 characters" after a
clause about the strategy, where it could be read as describing the defect. It
is now a sentence of its own, still rendered from `FINDING_TITLE_MAX_CHARS`
(`test_every_cap_is_rendered_from_its_constant`).

**Causes, never actions (safety; operator rejected).** No ops option says "wait
and retry", "safe to ignore" or "will clear". An option that recommends
dismissing an error removes friction by persuasion. What code knows exactly,
such as a switch, a window or a lease, is code's chip and is never asked.

**The skeleton is described to Jev exactly.** Jev reads `[secret]` literally,
and it must know that this is a stand-in, not evidence. The placeholders use
square brackets, not safety's angle brackets. Section 4 explains why.

**Behind the detail switch, under `system` (revised: D-SAFE-1, D-SAFE-5).**
Neither changes a word Jev reads. `internal_detail` is not in the pack hash.
`system` is, since the provenance is, so `ops.job_error`'s pack hash below is
the one computed under `system`; its questions hash is unchanged. The set's
`purpose` says it is sent only while the detail switch is on.

### 2.6 Hashes of these words, and the registry after D

The hashes below were computed this session with the shipped `QuestionSet`.
The pull requests re-pin them from the words as merged, and the result must be
identical.

| Set | Pack hash | Questions hash | Question size (estimated tokens) |
|---|---|---|---|
| `findings.owner` v1 | `7e97f8b11d80494d5ecb978bc04240226229993d2f73617b1fccdf7ea4437c8c` | `2989fecdce44b1ff9bd1c216b5eb1f33bbc76fc15427403e83defac412239ff3` | 840 |
| `findings.severity` v1 | `a9cae8cdafff291715982ea74dc3fe05f3e0da1ba8ffdd03cc428df585e830e0` | `0504d4817b84e44db3fc268f4d64bfd0d4d0e4ec62856f84595ccd9bab08db9e` | 336 |
| `ops.job_error` v1 | `1e625e8f0965342d12907dbc27fb78e66db44086bb0b6428359c8ab9c512b512` (under `system`; it was `b7d03b54…9273c4f117` under `internal`) | `e24fe30799ea8252dd3eac4dba6df02cb7fd9a0aaf4d4d11007fedc7df6a617a` | 645 |

- **Distinct hashes.** All nine questions hashes are pairwise distinct (the
  registry's open item 15 rule).
- **The registry pin** (revised: D-HMB-13). `REGISTRY` holds six sets at
  `23dee2b`. It becomes eight after D2 and nine after D3:
  `probe.connectivity`, `decision.regime`, the four phase C sets, then
  `findings.owner` and `findings.severity`, then `ops.job_error`.
- **Released histories.** `GOLDEN_PACK_HASHES` and the tests'
  `RELEASED_PACK_HASHES` and `RELEASED_QUESTION_HASHES` each gain a row per
  set.
- **Probes.** No set is in the probe lane, so `PROBE_EXPECTED` is unchanged.
- **State sizes.** A title state is at most about 605 tokens. A skeleton is 48
  ASCII tokens of at most 32 characters, under 600 tokens. Both are far under
  the seeded 8,000.

---

## 3. The plans

### 3.1 Why the global plan changes, and why now (measurement)

Five facts from the code decide this section.

1. **An answer is scored only under the plans in force.**
   `jev_eval.build_evaluation` scores an item only when the plans its answer
   was recorded under equal `jev_prereg.plans_in_force`. That is the global
   plan's version and hash, and the set plan's. Every other item is counted
   apart in `n_other_plans` and never scored. So a change to the global plan
   sets aside every lane's history; changed now, it sets aside nothing.
2. **The test's floor rule cannot hold a findings or ops set.**
   `tests/unit/test_jev_prereg.py::_target_problems` reads
   `LANE_TARGETS[lane]`, and `LANE_TARGETS` names `research` and `guardrail`
   only. Safety proposed adding a floor mapping inside the test. A floor that
   lives in a test is not in `plan_hash()`, so it is not pre-registered.
3. **The family is nearly full.** The six phase C pairs plus D's three make
   nine of `GATE_FAMILY`'s ten (`TestTheGateFamily`). The next version of any
   set would force a version 3 of the plan, after answers exist.
4. **Flips need about 858 labels as built.** `build_evaluation` counts a re-ask
   pair only when its canonical request answered a scored item. Checked this
   session: the `canonical` set is built from the scored items. Thirty uniform
   pairs at one in twenty then need about 600 labelled test items, which is 858
   labelled items under the 30/70 split. A flip uses no label.
5. **Looks are not counted.** `evaluate` can run as a dry run on the test split
   as often as anyone likes, and only recorded rows reach `usable`. Labelling
   until a dry run passes, then recording that run, is optional stopping. It
   breaks the error rate `GATE_CI` claims, on the first arming this programme
   makes.

So **D1 releases plan version 2 before any Jev area is first switched on.**
Every item below is free until then, and costs that lane's history after.
`RELEASED_PLAN_HASHES` keeps version 1 (`f744c2d8…2daf7caf`), and
`GOLDEN_PLAN_HASH` is re-pinned as merged.

### 3.2 Global plan version 2

| Item | v1 | v2 | Why | Cost |
|---|---|---|---|---|
| **R1** Floors by statistic (measurement) | `LANE_TARGETS`: research covered accuracy ≥ 0.80; guardrail covered precision of `true` ≥ 0.90 | `STATISTIC_FLOORS`: `covered_accuracy` ≥ 0.80 and `covered_precision_of_the_acting_class` ≥ 0.90, each the one-sided Wilson lower bound at `GATE_CI`. A question with an acting class is measured by that class's covered precision; any other by covered accuracy. A set plan may raise a floor, never lower it | Any lane, findings and ops included, arrives through a set plan alone. Every phase C set reads the same target as before | None |
| **R2** Family (measurement) | `GATE_FAMILY` 10 | 20 | D's three pairs take the family to 9. A set's next version would force a version 3 after answers exist | About 20% more covered items at a gate |
| **M1** Split (measurement) | `DEV_SPLIT_TENTHS` 3 | 5 | `held_out` holds the test split to the same bar the search applied, so the 30% development share binds. A 50/50 split reaches the bar with 40% fewer labels wherever a covered count binds | Where only the floors bind, 400 items rather than 334 |
| **M2** Flips over the population (measurement) | A pair counts only when its canonical request answered a scored item | Every canonical request of the set's question under the pin, sampled under the plan in force, counted in its stratum, labelled or not | Fact 4. The armed threshold acts on the population, so the population's flips are the ones that matter | Flip counts may exceed `n`. Migration 0015 moves the flip conjuncts out of `jev_evaluations_counts_within_n` (section 7) |
| **M3** Looks (measurement; revised: D-HMB-06) | Uncounted | `MAX_LOOKS` 4 per set, version and question, **counted across every model**: the family the level is spent over counts set, version and question (`test_jev_prereg.py::_gated_family`), so a look under a second pin is one of the same four. `evaluate --split test` and `--split all` require `--record`, enforced in `jev_eval.execute`, so `main` and every caller of `execute` hold it. A new `--split dev` prints the development split's search and never records. `--split` has no default (added), so nobody looks at the test split by accident. `usable` refuses an evaluation with four earlier test or all evaluations of its set, version and question, under any model (`looks`). `GATE_CI` = 1 − 0.05 / (20 × 4) = **0.999375**, written as a literal and held to that formula | Fact 5. The first arming must not rest on optional stopping (CLAUDE.md: the best of fifty is flattering by construction). Counted per model, every new pin would restore four looks the level never paid for | About 30% more covered items beyond R2's. The sign test needs 11 discordant items, not 8 (computed). A new pin gets no fresh looks: arming under it after four looks needs a new set version (open item 78) |
| **M4** The regime's plan apart (measurement) | `REGIME_BASELINE_RULE` and `REGIME_SLEEVES` inside the global plan | A regime plan of its own: `REGIME_PLAN_VERSION` 1, `regime_plan()`, `regime_plan_hash()` and `GOLDEN_REGIME_PLAN_HASH`, with a released history in the test. The global plan loses its `regime` section | The operator's review of the rule and the sleeves is pending (docs/08, Inputs needed 2). Inside the global plan, that review would set aside every other lane's answers | `jev_forward` records two plans; `forward` reads the regime plan (section 3.3) |
| **M5** Re-asks not compared **(added)** | `usable` reads the compared pairs alone (open item 68) | `usable` reads each flip rate in the worst case: (flipped + not compared) ÷ (compared + not compared) must be within its limit, on at least `MIN_FLIP_PAIRS` compared pairs | Open item 68 left this for "a new plan version". Version 2 is that version. A re-ask that ties or is refused whole is itself unstable, and the rule only refuses | It uses columns 0014 already stores. It can only refuse an arming |

**Unchanged in v2:** `REPORT_CI` 0.95, `MIN_TEST_ITEMS` 200, `MIN_DEV_ITEMS`
100, `MIN_COVERED` 30, `MARGIN_GRID`, the bootstrap and its seed rule, the
bins, `TOO_FEW_PER_CLASS`, the flip limits (0.05 and 0.10), `MIN_FLIP_PAIRS`
30, `NEAR_THRESHOLD` 0.10 and the re-ask sample.

`_MOVED` in the test gains `STATISTIC_FLOORS`, `MAX_LOOKS`, M2's rule and
M5's rule. Every constant in it is moved and must move the hash.
`TestTheGateFamily` holds (1 − `GATE_CI`) × `GATE_FAMILY` × `MAX_LOOKS` ≤
1 − `REPORT_CI`.

**Separable.** If the owner strikes an M item before D1 merges, its tests and
its part of 0015 go with it, and nothing else in this design changes. R1 and R2
are required (section 11, Q1).

### 3.3 The regime's plan, apart (M4)

- **The regime job.** `jev_forward.collect` writes `regime_plan_version` and
  `regime_plan_hash` into its result, beside `plan_version` and `plan_hash`.
- **The forward report.** `jev_eval forward` scores agreement only over answers
  first recorded under the regime plan it runs. It counts the rest apart, by
  the regime plan they were recorded under. A row with no regime plan (a C4-era
  result) is "plan unknown".
- **Flips.** A flip pair still counts under the global plan its re-ask payload
  names, as before.
- **The tests.** The test holding `REGIME_SLEEVES` equal to
  `src/data/reference.py` moves to the regime plan.
- **The docs.** docs/08's C4 text and Inputs needed item 2 change from "a
  change … is a new `PLAN_VERSION`" to "a new `REGIME_PLAN_VERSION`, which sets
  aside regime agreement alone".

### 3.4 The set plans

Each set plan:

- enters `SET_PLAN_VERSIONS` at plan version 1;
- is pinned in `GOLDEN_SET_PLAN_HASHES`;
- gains a row in the test's append-only `RELEASED_SET_PLAN_HASHES`;
- is recorded with every answer through `plans_in_force`, in each `jev_ask`
  payload and result, as C7 and C8 built.

`keyword_label` gains a `fallback` argument, recorded in each plan as
`"fallback"`. The phase C plans keep `insufficient_evidence`, so their hashes
are unchanged.

| Set, question | Acting class | Statistic and target | Baseline (the plan's `keyword_baseline` slot) | Population (a plan field) |
|---|---|---|---|---|
| `findings.owner`, `owning_role` | none | covered accuracy ≥ 0.80 (the floor) | **`findings.recorded`, reading `raised_by`**: the role that raised the earliest model-written finding holding the title, ordered by `opened_at` then `ref` (measurement) | Findings with `origin = 'model'`, title 1–200 characters, any status |
| `findings.severity`, `severity` | none | covered accuracy ≥ 0.80 | **`findings.recorded`, reading `severity`**, of the same finding | The same |
| `ops.job_error`, `cause` | none | covered accuracy ≥ 0.80 | `jev_prereg.keyword_label(OPS_KEYWORDS)` on the subject's text, fallback `unclear` | Failed jobs (`status = 'failed'`, `finished_at` set) of `TRIAGED_KINDS`, finished after `MODEL_FIRST_OBSERVED[pin]`. Each has `code_cause(kind, error) is None` and at least `MIN_CONTENT_TOKENS` content tokens. Redactor v1 and the shapes table are named by their hashes. An item is dated over these same rows (section 3.7; revised: D-HMB-08) |
| `guardrail.card`, `performance_claim` | `true` | covered precision ≥ 0.90 | the claims check (unchanged, set plan v1) | unchanged |

**Why the recorded value is the findings baseline (measurement; safety and
operator rejected).** If Jev, reading only the title, cannot beat "route it to
whoever raised it" on the items where the two disagree, its suggestion adds
nothing. A keyword list would be a weaker comparison, so a chip could be called
calibrated while doing worse than reading `raised_by`.

`build_evaluation` calls the baseline with the subject beside its text. A new
`jev_repo.finding_records(conn, subjects)` reads `raised_by` and `severity`.
Neither column is ever exported to a labeller.

`OPS_KEYWORDS` are ordered, first match wins, and are read by `keyword_label`
on the casefolded text. The words below are a draft for D3's review.

**Every keyword is held to a skeleton the redactor produces (revised:
D-HMB-10).** The draft first held each keyword only to the vocabulary, which
let in keywords nothing can emit:

- `sqlstate` is written in capitals, and rule 14 turns a piece with two or
  more capitals into `[name]`.
- The exception class names (`keyerror`, `uniqueviolationerror`,
  `memoryerror`, `timeouterror` and the rest) appear only if a message quotes
  its own class. The worker records `str(exc)`, which never does (open item
  73).

So a test, `TestTheOpsKeywords::test_every_keyword_is_produced`, holds each
keyword to an evidence corpus kept in the test. The corpus holds real
messages, each run through `jev_redact.skeleton`:

- builtins' messages, produced by triggering the error in the test
  (`None.x`, `1 / 0`, `[][0]`, `f()` with an argument missing);
- library exceptions' `str()`, built from the library's own classes with the
  message its source writes, each entry naming the library and version;
- the triaged modules' pass-through raises.

Each keyword must be found, by `keyword_label`'s own matcher, in the subject
text of at least one corpus message that `code_cause` leaves to Jev. A
keyword no message produces is dropped, which is how the words below were
cut. The code-defect label now reads the messages builtins actually write,
and it sits before `data_missing`, so "missing 1 required positional
argument" is a code defect:

| Label | Keywords |
|---|---|
| `rate_limit` | `http_429`, `rate limit`, `throttled`, `too many requests` |
| `credentials` | `http_401`, `http_403`, `unauthorized`, `unauthorised`, `forbidden`, `credential`, `password`, `permission`, `authentication` |
| `database` | `deadlock`, `constraint`, `violates`, `duplicate key`, `could not serialize` |
| `resource_limit` | `memory`, `disk`, `exhausted`, `no space` |
| `network` | `connection`, `refused`, `reset`, `timeout`, `timed out`, `unreachable`, `dns`, `socket`, `cannot connect` |
| `vendor_service` | `http_500`, `http_502`, `http_503`, `http_504`, `http_529`, `unavailable`, `outage`, `empty response` |
| `code_defect` | `has no attribute`, `not subscriptable`, `unsupported operand`, `out of range`, `division by zero`, `is not defined`, `not callable`, `not iterable`, `unexpected keyword argument`, `required positional argument` |
| `data_missing` | `missing`, `no data`, `no rows`, `delisted`, `empty`, `not found` |
| `data_invalid` | `malformed`, `invalid`, `nan`, `inconsistent` |
| `configuration` | `parameter`, `setting`, `configuration`, `unknown` |

The subject's text is `f"{job_kind}: {' '.join(tokens)}"`. That is what Jev
saw, what the export shows and what the baseline reads. A test holds that no
keyword matches a job kind alone, since `ingest_bars` would otherwise match
`bars` across its underscore. These rules, like the catalogue's:

- are held to a copy written in the test as literals;
- are held to verdicts on invented skeletons, recorded under the plan version
  that registered them (the `TestTheCardBaselineIsPinnedByWhatItDoes`
  discipline).

The card's plan does not change (measurement). What an armed answer does is
decision policy, not measurement, so it lives in code (section 10) and can
change without setting aside a single answer.

### 3.5 Labels, kept blind

| Set | A label is | The export shows (`labels export --blind`) | Withheld |
|---|---|---|---|
| `findings.owner` | one of the twelve role keys | `finding_title`, the address, the title | The raiser, the severity, the status, the candidate, every answer |
| `findings.severity` | low, medium, high or critical | the same | The recorded severity, every answer |
| `ops.job_error` | one of the ten causes | `job_error`, the address, `"{kind}: {skeleton}"` | The job, its raw error, every answer |
| `guardrail.card` | true or false (C9, unchanged) | `hypothesis_title`, the address, the title | The card, every answer, and the Jev findings once armed |

The export keeps its three columns. The operator proposal's `context` column,
holding the raw error, is rejected: it would put the raw error in a file on
disk. Phase C9's rules are kept: no answer column, no revised label, no escape
label, one labeller per evaluation.

**An ops label is checked against the state it names (revised:
D-HMB-07).** C9's import checks a text subject by `text_sha256(text) ==
subject_id`, and a `job_error` subject is the state hash of `{job_kind,
error}`, never the sha256 of its text. So `label_problems` reads a subject of a
type in `STATE_ADDRESSED` back through `jev_questions.job_error_from_text`.
The text must name a state, and that state's `job_error_subject` must be the
subject id. A text that names none is refused. Without this, `labels import`
refused every ops row that kept the exported text, and admitted one whose
text was blanked.

What only a person can control is recorded rather than solved (measurement;
revised: D-HMB-04). The earlier draft called D's labels "the cleanest this
system will have" because no page shows an answer before phase E. That claim
is withdrawn:

- **`suggestions` printed the chips.** It now prints only whether each
  subject was asked and how the ask came out (answered, invalid, held, not
  asked and why): never an argmax, a probability or a chip. It prints the
  count of Jev findings raised, never their refs (section 9.3).
- **The findings page shows the raiser and the severity beside every title**
  (`web/src/app/programme/findings/page.tsx`). Those are the values the
  recorded baseline reads. A labeller who has read the register can label
  what the baseline says, which makes the baseline hard to beat, and nothing
  records who has read it. Findings sets arm nothing in D, so this biases a
  measurement and can release nothing (open item 75).
- **A card labeller who has seen Jev's findings on the register is exposed.**
  Gating such labels is a later plan's (open item 72).

### 3.6 Sizes under v2

A gate is reached when the covered count clears the target by its one-sided
Wilson lower bound, on both the development and the test split, together with
the floors and the flip pairs.

The rates in the table are assumptions that show the arithmetic, not
measurements. The figures were computed this session with `jev_stats.wilson`
(measurement's `sizes4.py`, re-run).

| Case | v1 as built | v2, four looks |
|---|---|---|
| `findings.owner`, accuracy 0.90 at coverage 0.70 | 858 | **483** |
| `findings.owner`, accuracy 0.85 at coverage 0.70 | 2,062 | 1,923 |
| `findings.severity`, accuracy 0.75 | unreachable | unreachable |
| `ops.job_error`, accuracy 0.90 at coverage 0.80 | 858 | 423 |
| `guardrail.card`, precision 0.97, πr 0.14 | 3,048 | **2,800** |
| `guardrail.card`, precision 1.00, πr 0.14 | 1,429 | 1,343 |

At 0.999375, a covered accuracy floor of 0.80 needs 42 all-right items. A
covered precision floor of 0.90 needs 94, against 30 and 60 at 0.995.

The table counts labels for the floors alone. A gate needs every condition of
`usable` at once (revised: D-HMB-03), and three of them bind before the floors
do.

**1. The baselines.** `_beats` (`jev_calibration.py`) needs three things at
once:

- the reported (95%, two-sided) Wilson lower bound of Jev's accuracy above the
  baseline's accuracy, over the valid answers;
- the same over every item, where an escape or an invalid answer counts as
  wrong;
- Jev better on the items only one of the two got right, by the exact sign
  test at `GATE_CI`.

At 0.999375 the sign test needs at least 11 such items all in Jev's favour,
14 with one against, 17 with two, and 19 with three (computed). For the
findings sets the baseline is the recorded value. Over every item of a test
split, Jev must be right this often, computed with `jev_stats.wilson`:

| The raiser agrees with a person's label | n = 200 | n = 400 | n = 600 |
|---|---|---|---|
| 0.80 | 0.860 | 0.840 | 0.833 |
| 0.85 | 0.900 | 0.885 | 0.880 |
| 0.90 | 0.945 | 0.930 | 0.925 |
| 0.95 | 0.985 | 0.973 | 0.968 |

**An assumption, stated: the raiser agrees with a person most of the time.**
`roles.system_prompt` gives each role its own `mandate` and `looks_for` and
nothing else, and `findings.owner`'s options paraphrase those mandates. So a
person labelling a title's area should usually name the role that raised it,
which puts the raiser's agreement at 0.85 to 0.95. Jev, reading the title
alone, would then have to be right on 90% to 98.5% of every item, escapes
counted wrong, and correct the raiser on at least 11 items more than the
raiser corrects it. **`findings.owner` is not expected to beat the raiser.**
Its chip will most likely read "not calibrated" for good. It is a routing
suggestion, and the owner may drop it (section 11, Q3).

**2. The flip pairs, counted in canonical requests, not labels.** Under M2 a
flip pair needs no label, but it needs a canonical request re-asked.

- *Uniform.* One canonical request in twenty is in the uniform stratum
  (`REASK_UNIFORM_MODULUS`), so 30 pairs need about 600 distinct canonical
  requests of the question under the pin: 600 distinct titles for a findings
  set or the card.
- *Near the threshold.* 30 pairs whose canonical margin is within 0.10 of the
  threshold. Above a threshold of 0.30 they come from the uniform stratum
  alone (open item 80), since the low-margin stratum holds margins under
  0.20. If one answer in five to ten lies that near the threshold, they need
  150 to 300 uniform pairs: about 3,000 to 6,000 distinct canonical requests.
- *The re-ask ceiling.* At most ten re-asks a UTC day across every lane,
  uniform first, drawn from the previous day's canonical requests alone
  (`jev_plan._plan_reasks`). A day with more uniform requests than that loses
  the rest for good.

**3. The supply of subjects.** No rate of model-written findings can be given.
The panel has never sat with a key (`ANTHROPIC_API_KEY` is unset), and its
output is bounded:

- at most five findings an assessment (`roles.MAX_FINDINGS_PER_ASSESSMENT`);
- each role heard once a stage for each candidate;
- at most eight candidates in research (`tick.MAX_ACTIVE_RESEARCH_CANDIDATES`).

Model-written hypothesis titles arrive at most one a tick, and none while
eight candidates sit in research.

What this means, plainly:

- **`findings.owner`** is not expected to beat the raiser it is measured
  against. It is a routing suggestion that will most likely stay "not
  calibrated".
- **`findings.severity`** will probably never be calibrated from a title.
- **`ops.job_error`** will run rarely, and will likely stay "not calibrated".
- **The card check** needs 1,300 to 2,800 labelled titles for its floors, and
  for its near-threshold flips about 3,000 to 6,000 titles asked under the
  pin. At the rates above, that is years, not months.

D builds the arming, proves that it can only add friction, and arms the day
the evidence exists.

### 3.7 What the harness gains

No new statistic. Every figure comes from `jev_stats`' existing functions.

| Change | Where | PR |
|---|---|---|
| `TEXT_SUBJECTS` becomes `LABELLED_SUBJECTS`, adding `finding_title` and `job_error`; `question_problem` reads it | `jev_eval` | D2, D3 |
| Each subject's date: a title's earliest `opened_at` among model-written findings holding it; a skeleton's earliest `finished_at` among the rows its population reads, the failed triaged jobs finished after `MODEL_FIRST_OBSERVED[pin]` that hold it (revised: D-HMB-08; see below) | `jev_repo.item_dates` | D2, D3 |
| Each subject's text and population, by the plan's rule. Skeletons are recomputed in the harness from raw rows, and a raw error is never printed | `jev_repo.subject_texts`, `subjects_to_label`, `failed_jobs_for_triage` | D2, D3 |
| The `findings.recorded` baseline | `jev_eval.keyword_baseline`, `read_ledger`, `build_evaluation` | D2 |
| M2: every pair of the question under the pin. M3: `--split dev`, `--record` required on test and all (in `execute`), the `looks` reason counted per set, version and question across models. M5: the worst-case flip rule | `build_evaluation`, the parser, `execute`, `jev_calibration.usable` | D1 |
| A label of a `STATE_ADDRESSED` subject is checked through the state its text names (`jev_questions.job_error_from_text`), not `text_sha256` (revised: D-HMB-07) | `jev_eval.label_problems` | D3 |
| `preview` and `suggestions` (section 9.3), and an arming line in `status` and `report` | `jev_eval` | D2–D4 |

**How an ops item is dated (revised: D-HMB-08).** The first draft dated a
skeleton by the earliest failed triaged job holding it, of any date. Its
population, though, reads only jobs finished after the pin's first
observation. The worker has run since August 2026, so a recurring vendor
error would carry a date from before 26 September 2026. One such labelled
item makes `possibly_in_training` true, and `build_evaluation` then searches
no threshold for the whole evaluation. So an item is now dated over exactly
the rows its population reads. The reasoning, recorded for the owner (section
11, Q14; open item 81):

- `MODEL_FIRST_OBSERVED` guards against text that was public before the
  model's training. A job's error is a private row of this database, and the
  skeleton text exists only from D's redactor on.
- A skeleton that is also a public string, a library's own message, is in
  every model's training whatever its date. No date can tell those apart,
  and the label of a cause is no future event a model could recall.
- The rule's consequence is stated rather than hidden. For ops,
  `possibly_in_training` reads false for every item of the population, so it
  carries no information there, and the report says so beside each ops
  evaluation.

---

## 4. The redactor, and code first

### 4.1 Where it sits, and why an allow-list

`src/programme/jev_redact.py` is new and pure. It loads the standard library
alone and is in `PURE_PROGRAMME_MODULES`. The API can import it, so phase E
computes a subject with the same function. **It is the only way any part of
`jobs.error` becomes state.**

Job errors are not all code-built.

- `Worker._execute` and `api/drain.drain_once` write `str(exc)` for any
  exception, checked this session. That text can quote:
  - a driver's value (asyncpg's `DataError`);
  - a validator's input;
  - a vendor's reply;
  - symbols, amounts, uuids and paths.
- `job_repo.fail` cuts the error to 4,000 characters.
- `requeue_expired` writes `'lease expired; worker presumed dead'`, or keeps an
  earlier attempt's error, and **sets no `finished_at`** (added).

A deny-list can never be shown complete, and an allow-list is total by
construction, so the redactor keeps what it knows and replaces everything
else.

`skeleton(text: object) -> tuple[str, ...]` never raises, for any input of any
type, and is deterministic. Every element is in `TOKENS`, its length is 0 to
`SKELETON_MAX_TOKENS` (48), and it reads at most `MAX_INPUT_CHARS` (4,000).

### 4.2 The rules, in order (safety's, fixed)

The first rule that applies decides each piece.

0. A value that is not a `str` gives `()`. A string is cut to
   `MAX_INPUT_CHARS`.
1. **Split on whitespace into chunks.** A chunk exactly equal to a placeholder
   or to an `HTTP_TOKENS` entry is emitted as itself, so a skeleton read again
   is unchanged. *(Fix: safety split on `[`, `]` first, which, with bracketed
   placeholders, would break idempotence.)*
2. Every other chunk is split on `, ; ( ) [ ] { } |`, which are emitted as
   nothing.
   - A run opened by a piece *beginning* with `'`, `"` or `` ` `` is closed by
     a later piece *ending* with the same character, or by the end. The whole
     run is one `[quoted]`.
   - An apostrophe inside a word (`ingest's`) opens nothing.
3. Leading and trailing `. : ! ?` are stripped, so no colon survives.
4. Any character outside printable ASCII gives `[word]`.
5. A piece containing `://`, starting `www.`, or holding `@` gives
   `[address]`.
6. `key=value` gives the key, by these rules, then `[value]`. If the key,
   casefolded, is in `SECRET_WORDS`, it gives the key then `[secret]`. The
   value is never emitted.
   - `SECRET_WORDS`: password, passwd, pwd, secret, token, apikey, api_key,
     key, authorization, bearer, cookie, session, dsn, credential,
     credentials.
7. The piece after a `SECRET_LEADS` word gives `[secret]`. The word is read
   casefolded, with leading dashes dropped.
   - `SECRET_LEADS`: authorization, bearer, basic, password, passwd, pwd,
     secret, token, apikey, api_key.
8. A piece containing `/` or `\` gives `[path]`.
9. A date gives `[date]`, and a time of day gives `[time]`.
10. A dotted run gives `[number]` when it is a decimal, and `[address]`
    otherwise.
11. A number directly after `http`, `status` or `code` and from 100 to 599
    gives `http_NNN` when listed, and `http_other` otherwise. Any other number
    gives `[number]`.
    - Listed: 400, 401, 403, 404, 408, 409, 422, 429, 500, 501, 502, 503, 504
      and 529.
12. Any digit left in a piece gives `[id]`.
13. A piece exactly an `EXCEPTION_NAMES` entry gives itself.
14. Two or more capitals give `[name]`, unless the casefolded piece is in
    `CAPS_VOCABULARY` (`http`, `json`, `sql`, `utc`, `nan`, each a
    `VOCABULARY` word), which gives that word.
15. A piece whose casefolded form is in `VOCABULARY` gives that word.
16. Anything else gives `[word]`.

Then, in this order (revised: D-HMB-09):

1. A run of one placeholder repeated collapses to one.
2. Over 48 tokens, the first 47 are kept and `[more]` is added.
3. Runs are collapsed again.

The third step is what makes the redactor idempotent. Without it, an input
whose 47th token is a literal `[more]` ends `[more] [more]`. Read again, that
collapses to 47 tokens, which is a different skeleton. Rule 1 emits a chunk
equal to a placeholder as itself, so such an input is easy to write. The fixed
corpus holds it (section 4.6).

**What the planner and handler admit** is `admissible(tokens)`: at least
`MIN_CONTENT_TOKENS` (3) content tokens. These are vocabulary words outside
`FUNCTION_WORDS`, exception names and HTTP tokens (operator's idea, made
concrete).

### 4.3 The vocabulary and its sets

| Set | What | Constraint, held by a test |
|---|---|---|
| `VOCABULARY` | At most 400 reviewed words, each `^[a-z][a-z_]{1,31}$`. Drawn from the raise sites of the triaged kinds' modules (`backtest_job`, `walkforward_job`, `maintenance_jobs`' ingest and reference functions, `src/data/*`), the common error words of the libraries they use, and `TRIAGED_KINDS`. **Never from the other job kinds or from table names** (revised: D-HMB-02): `jev_ask`, `jev_requests`, `system_flags` and their like are no word a research or ingest job writes. `FUNCTION_WORDS` ⊂ `VOCABULARY` | Disjoint from `NEVER_IN_VOCABULARY`, **and so is every part of every word**: each underscore-separated part of a vocabulary word and of an HTTP token, and each word of an exception name split at its capitals (revised: D-HMB-02) |
| `NEVER_IN_VOCABULARY` | Read against whole words and their parts, because the code screen's skeleton reads an underscore as a space (`web_sources.SKELETON_SPACES`). At `23dee2b`, `code_screen` answers `instruction_phrase` for `backtest: jev_ask failed`, `walkforward: system_prompt missing` and `backtest: gpt_cache missing` (checked this session), though no whole token is a forbidden word. (a) Every word an alternative of the code screen's `instruction_phrase` requires and cannot do without. These are the verbs (ignore, disregard, forget, override, bypass, follow, obey, heed, answer, respond, reply, classify, label, categorise, categorize, mark, score, tag, output, print), the role words (system, assistant, user, developer, human), the targets (instructions, instruction, prompt, prompts, directions, guidelines), the address words (you, ai, model, chatbot, bot, llm), `as`, and the targets of `rate`/`mark` (this, it, me, title, text, paper, item, entry). (b) The vendor names: jev, typesafe, claude, anthropic, chatgpt, openai, gpt. (c) The sleeves and every ticker in the fixtures and docs, lower-cased: spy, ief, gsg, aapl, amzn, googl, msft, nvda. (d) Nothing that names a person, place, venue or account | Held to the rule's patterns by a test that parses them (section 4.6) |
| `EXCEPTION_NAMES` | A fixed list: builtins (`KeyError`, `TimeoutError`, …), asyncpg's (`UniqueViolationError`, `DeadlockDetectedError`, …), aiohttp's, pydantic's `ValidationError`, `JSONDecodeError`, and this repository's (`DataSourceError`, `InsufficientDataError`, `BacktestJobError`, `WalkForwardJobError`) | Each resolves to a real exception class in its module, or to one defined in `src/` |
| `HTTP_TOKENS` | `http_400` … `http_529` as listed, and `http_other` | — |
| `PLACEHOLDERS` | Section 2.4, in order | Equal to the legend the words render |
| `TOKENS` | `VOCABULARY ∪ EXCEPTION_NAMES ∪ HTTP_TOKENS ∪ PLACEHOLDERS`, as a sorted tuple | Equal to `JobErrorState.error`'s `Literal`, exactly |
| `TRIAGED_KINDS` | `("backtest", "walkforward", "ingest_bars", "ingest_reference_bars")` | A subset of `src.worker.main.HANDLERS`, which the test may import. Disjoint from `KILL_GATED_KINDS`, `cancel_open_orders`, `eod_marks`, `reconcile`, `shadow_decision` and `main.JEV_HANDLERS` |

### 4.4 Versioning

`REDACTOR_VERSION` is 1. `redactor_sha256()` hashes:

- the version;
- every set above, sorted;
- the placeholders, in order, with their meanings;
- `SECRET_WORDS` and `SECRET_LEADS`;
- the split and strip characters;
- the rule names, in order;
- both bounds and `MIN_CONTENT_TOKENS`.

`GOLDEN_REDACTOR_SHA256` is pinned beside them. Every released hash is pinned,
append-only, in `tests/unit/test_jev_redact.py`, so re-recording the golden
after an edit still fails. The test also maps each `ops.job_error` version to
the redactor hash it was released with. A change of vocabulary is a new set
version, because the same words over a different skeleton are a different
question. The ops set plan names the hash.

### 4.5 Code triage first (operator's shapes, safety's function)

`jev_chips.code_cause(kind: str, error: object) -> str | None` is pure. Its
data is `JOB_ERROR_SHAPES`, an ordered tuple of `(name, kinds, matcher,
cause)`, read first match wins.

- It is hashed by `shapes_sha256()`, pinned with a released history in the
  test, and named by the ops set plan.
- It returns a cause from `CAUSES` (the ops options without the escape) or from
  `CODE_ONLY_CAUSES` (`switched_off`, `expired`, `held_by_design`,
  `needs_review`, `unclassified`).
- It returns **`None` only for a triaged kind's error that no shape matches.**
  This is the residue, the one thing Jev may be asked about. For every other
  kind, an unmatched error is `unclassified`, and it is never sent.

The shapes come from the operator's table (§1.2 and §4.5 of that proposal):

| Group | Kinds | Shapes |
|---|---|---|
| Generic | any | `kill switch engaged`, which is `switched_off`. `lease expired; worker presumed dead`, which is `expired`. `no handler for `, which is `code_defect`. A `SQLSTATE` code, which is `database` |
| The triaged modules | `backtest`, `walkforward`, `ingest_bars`, `ingest_reference_bars` | Every literal or f-string message raised in their modules, each with its cause. These include: `unknown backtest run`/`walkforward run` (`code_defect`); `unknown data source` (`configuration`); `no bars for` (`data_missing`); `refetching the stored span from` (`vendor_service`); `no close is stored for` (`data_missing`); `bars settle at` and `is superseded` (`expired`); `is not an NYSE session` (`code_defect`) |
| Venue kinds | `live_decision`, `submit_orders`, `cancel_open_orders`, `eod_marks`, `reconcile`, `shadow_decision` | The broker shapes (`Alpaca credentials are not configured`, `returned 401`, `returned 429`, `returned 5xx`, `Alpaca rejected`, `Alpaca request failed`, `still open at the venue`, …), each a code chip. The residue is `unclassified` |
| Programme kinds | `JEV_HANDLERS`' kinds | Every `job_errors.NOT_ASKED` reason, every `ask_verdict` and `main.probe_verdict` outcome, every handler's `JobFailedError` literal, and `described()`. Each maps as the operator's table does (`disabled` is `switched_off`; `auth_held` and `no_key` are `credentials`; holds and blocks are `held_by_design`; the retried error kinds are `network`, `rate_limit` or `vendor_service`; a probe answered otherwise and a page that changed shape are `needs_review`; a cutoff passed is `expired`) |

**Reconciliation and data health: code chips, never sent (all three
proposals).**

- **`reconciliation_chip(mismatch, *, traded)`** reads one entry of
  `run_reconcile`'s mismatches. It gives `venue_only_position` (flagged
  `untraded` when no enabled deployment's universe holds the symbol),
  `ledger_only_position`, `quantity_mismatch` or `cash_drift`.
- **`data_health_chips(data_health)`** reads `reports._data_health`'s dict. It
  gives `no_data_ingested`, `deployment_unbuildable`,
  `traded_symbol_without_bars` and `traded_data_stale`.
  - `traded_data_stale` fires at `sessions_behind > STALE_AFTER_DAYS`, which
    is 3, held to `reports._required_actions`' own rule by a test.
- **`ingest_chips(result)`** reads an ingest result's `session_missing` and
  `rows_not_refreshed`.

None of these changes, corrects or sends anything.

### 4.6 How it is tested (`tests/unit/test_jev_redact.py`, `test_jev_chips.py`)

The tests combine safety's table and operator's §4.4 and §4.5, with the masking
fix.

| Property | Test |
|---|---|
| Total | 10,000 seeded inputs, including random Unicode with lone surrogates and NUL, 1 MB strings, deep quotes, chains of `=`, runs with no space, `None`, bytes, ints and dicts: it never raises and always returns a tuple |
| Closed | Every token of every output is in `TOKENS`, and `TOKENS` equals the `Literal` exactly |
| Bounded and deterministic | At most 48 tokens. Two inputs equal in their first 4,000 characters give equal outputs. The same output comes from two fresh interpreters with different `PYTHONHASHSEED`. Each pathological input of 4,000 characters finishes under 50 ms |
| Idempotent | `skeleton(" ".join(skeleton(x))) == skeleton(x)` over the fuzz, and over a fixed corpus the fuzz would rarely find (revised: D-HMB-09): 46 vocabulary words, then a literal `[more]`, then two or more words; the same with `[more]` at every position from 45 to 49; runs of one placeholder across the 47th token. This holds only because placeholders are read before the split and runs are collapsed after the truncation |
| Secrets never survive (non-interference) | A corpus of every credential shape the deployment holds or could echo, including passwords that are vocabulary words, planted in every marked form across 30 error templates (asyncpg and aiohttp messages, tracebacks, Python and JSON reprs). The shapes: TypeSafe-shaped and `sk-ant-` keys; Alpaca `PK…`/`AK…` pairs; Fernet keys; DSNs with passwords; `PGPASSWORD=`; bearer tokens; JWTs; cookies; hex and base64 runs. The secret never appears, and swapping it for another value of its shape leaves the skeleton unchanged. The stated limit: a secret spelled wholly in vocabulary words in unmarked prose would survive as those words |
| Identifiers never survive | Tickers, uuids, `client_order_id`s, deployment-id prefixes, quantities, amounts, hosts, paths, emails, IPs, dates and times each become their placeholder, and swapping one for another of its class leaves the skeleton unchanged |
| No instruction can be spelled — **read rule by rule (added), and part by part (revised: D-HMB-02)** | (a) A structural test: for each alternative of each `instruction_phrase` pattern, the words it requires are read, and at least one is found outside `VOCABULARY` **and outside every underscore-separated part of a vocabulary word, an HTTP token and every capital-split part of an exception name**. `NEVER_IN_VOCABULARY` is held to those words. (a2) Every vocabulary word alone, every HTTP token and exception name alone, and every ordered pair of them, each in the subject text `"{kind}: {pair}"` for each triaged kind, trips none of `hidden_characters`, `markup_in_cell` and `instruction_phrase`, each rule read directly. That is about 160,000 pairs, each tried against compiled patterns. The test is proved by a vocabulary holding `jev_ask`, `system_prompt` or `gpt_cache`, which must trip it. (b) Over the fuzz and over `test_web_sources.py::TestTheAdversarialCorpus` embedded in error text, each output's subject text trips none of `hidden_characters`, `markup_in_cell` and `instruction_phrase`, **each rule's patterns read directly** from `web_sources`' compiled rules rather than through `code_screen`'s first hit. This session showed that an angle-bracket placeholder makes `code_screen` answer `markup_in_cell`, masking an `instruction_phrase` beneath it |
| The vocabulary's shape | Every word matches its pattern. No ticker, vendor or instruction word appears. `CAPS_VOCABULARY` ⊂ `VOCABULARY` |
| Our own errors | Every message the triaged kinds' raise sites can produce, collected from the AST of those modules (f-strings rendered with sentinel arguments), has its skeleton pinned in a table in the test |
| Code first | Every literal raise in the triaged modules and in `src/data` has its constant part matched by a shape, and every pass-through raise (`raise BacktestJobError(str(exc))`) is in a reviewed list. Every programme error constructor is matched by a programme shape. `code_cause` returns `None` for a triaged kind only. Shapes are pinned with a released history |
| Pinned | Golden and released history. Each rule removed in turn fails a test (the C5 mutation discipline) |
| Pure | In a fresh interpreter it loads `src`, `src.programme`, itself and the standard library alone. `jev_chips` loads also `jev_redact` |

---

## 5. Jobs, the planner, priorities, budget shares, dedupe keys

### 5.1 No new job kind

Every D ask is a `jev_ask` job: `jev_jobs.run_ask`, one call an attempt, with
`ask_verdict` as its verdict and the plans in its payload. `main.JEV_HANDLERS`,
the claim filter, `ROAD_CALLS`, the one-call scans, the lease extension and the
35 s shutdown grace all apply unchanged.

`Askable` gains `address(row, state) -> str`, the function the subject is
checked by.

- **Text sets:** it is `text_sha256(text(row))`, checked before `admit` as
  today.
- **`ops.job_error`:** it is `jev_questions.job_error_subject(state)`, checked
  once the state is built, since the address is the state's.

The entries:

| Set | `load` (by `source_id`) | `admit` (refuses before any state, without a retry) | `build` | `as_of` | `what` | `follow_up` |
|---|---|---|---|---|---|---|
| `findings.owner`, `findings.severity` | `jev_repo.get_finding_title(ref)`: `ref, title, origin, opened_at` only, never `detail_md`, `remediation` or `close_note` (safety) | `origin != 'model'`; `len(title) > FINDING_TITLE_MAX_CHARS`, refused by the cap and never by pydantic | `FindingTitleState(title=…)` | `opened_at` | `finding {ref}` | none |
| `ops.job_error` | `jev_repo.get_failed_job(id)`: `id, kind, status, error, finished_at` | `status != 'failed'`; `kind ∉ TRIAGED_KINDS`; `finished_at IS NULL` **(added)**; `code_cause(kind, error) is not None`; `not admissible(skeleton(error))` | `JobErrorState(job_kind=kind, error=skeleton(error))`. The raw error is read by this line and by `code_cause` alone | `finished_at` | `job {id}` | none |
| `research.hypothesis`, `guardrail.card` | **`jev_repo.get_hypothesis_title(ref)`: `ref, title, origin, created_at` only (D1; revised: D-SAFE-2, D-HMB-16)**, in place of C8's `repo.get_hypothesis`, whose `SELECT *` hands the Jev side the card | unchanged | unchanged | unchanged | unchanged | `research.hypothesis`: none. `guardrail.card`: **`jev_arming.card_follow_up`** (D4, section 10), which receives that projection and nothing more |

Errors name the row by its ref or id and quote nothing. Pydantic's
`ValidationError` is caught by the existing guard (`_built`). `run_reask`
gains no follow-up: a probe measures and acts on nothing.

**A re-judge is asked with no key (D4; revised: D-SAFE-4, D-HMB-05).** A
re-judge is a `jev_ask` job of `guardrail.card` whose payload carries one name
more than an ask's: `"rejudge": true`. `_ask_payload` admits exactly
`ASK_PAYLOAD_KEYS`, or those and `rejudge` with the value `True` for a set in
`REJUDGED = frozenset({"guardrail.card"})`, and nothing else. For a re-judge,
`run_ask` passes `api_key=None` to `jev_lane.ask`.

The road looks up the canonical answer, under the pin it reads at that moment,
before it reads the key (`jev_lane.py`, the replay precedes the `no_key`
return). So a re-judge replays the answer on record, or meets `no_key`
having sent nothing and written nothing. That is so even when the pin moved
between the plan and the claim, which leaves no canonical row under the new
pin. Every call the client makes sits behind the key check, so a re-judge
cannot make one.

`run_ask` completes such a job as `not_on_record`: no answer on record under
the pin in force, nothing asked, nothing raised. It is never a failure that
retries. The one-call scans (`test_job_ownership.py`) count a re-judge as an
attempt that can make no call.

### 5.2 The planner (`jev_plan`)

| Rule | Switches beyond programme ∧ Jev ∧ pin ∧ key, each through its own reader | Read | Key (`jev_repo.ask_job_key`) | Priority / attempts | Most a pass | Calls |
|---|---|---|---|---|---|---|
| Finding owner | `findings` area | `jev_repo.findings_to_ask` (below) | `jev_ask:findings.owner@1:finding_title:{sha}:{UTC date}` | 0 / 3 | 10 | 1 each, from the findings share |
| Finding severity | `findings` area | the same | `jev_ask:findings.severity@1:finding_title:{sha}:{UTC date}` | 0 / 3 | 10 | 1 each, from the findings share |
| Job error cause | `ops` area ∧ **`jev_send_internal_detail`** (revised: D-SAFE-1) | `jev_repo.failed_jobs_for_triage`, then Python: the residue, admitted, addressed, the newest job per address, then `jev_repo.unasked_subjects` | `jev_ask:ops.job_error@1:job_error:{state sha}:{UTC date}` | 0 / 3 | 10 | 1 each, from the ops share |
| Card re-judge (D4) | `guardrails` area ∧ **`jev_arm_card_check`** | `jev_repo.cards_to_rejudge` | `jev_repo.rejudge_job_key`: `jev_ask:guardrail.card@1:hypothesis_title:{sha}:{UTC date}:rejudge` | 0 / 3 | 10 (`REJUDGES_PER_PASS`) | **0, by construction**: asked with no key (section 5.1) |

`ASKS_PER_PASS` gains the three sets, so `_lane_asks` counts their waiting jobs
against their lanes' shares.

**The re-judge rule is a step of its own, `_plan_rejudges` (revised:
D-SAFE-4).** The first draft generalised `_plan_asks`' hold exception ("under
a hold, plan any set's no-call subjects"). It is withdrawn: on the scratch copy
it changed what `_plan_asks` reads under a hold, which two phase C tests pin
(`test_jev_plan.py::TestTheAsks::test_nothing_that_calls_is_asked_while_an_authentication_failure_holds`
and `::test_a_refused_screen_still_plans_its_repairs`). `_plan_asks` keeps its
screen-only exception, word for word.

`_plan_rejudges` plans under an authentication or 422 hold, because a
re-judge cannot call. It takes nothing from the guardrail share, because it
makes no call. `jev_repo.pending_asks` leaves re-judges out of the waiting
count for the same reason, which closes the earlier open item 75 (section 14).

**One general fix, added (measurement and operator): a set declaring
`internal_detail` is planned only while `jev_send_internal_detail` is on.** It
is live from D3, where `ops.job_error` declares it. In D1 it is tested with a
test-only set. No job is queued only to end `disabled`, and the planner reads
the detail switch through its own reader, as the road does, neither derived
from the other.

The planner:

- never loads `jev_calibration` or `jev_arming`;
- reads the arming switch, never whether a calibration is usable, so arming can
  never plan a call;
- holds a raw error in memory only between the read and `code_cause` or the
  redactor;
- logs ids and counts, never text.

A failure on one row is logged by its class and the job's id.

### 5.3 The reads it stands on (`jev_repo`)

| Read | Behaviour |
|---|---|
| `findings_to_ask(conn, *, question_set, model, limit, day, max_failed=MAX_FAILED_CALLS)` | Distinct titles of findings with `origin = 'model'` and title length 1–200, by content address computed in SQL (`encode(sha256(convert_to(title,'UTF8')),'hex')`), newest first by `opened_at` then `ref`, with the newest finding's ref. It excludes a title that is blocked (`_blocked`), answered or retired (`_unanswered`), or waiting or planned today (`_not_waiting`) |
| `get_finding_title(conn, ref)` | `ref, title, origin, opened_at`, and no other column |
| `get_hypothesis_title(conn, ref)` (D1; revised: D-SAFE-2) | `ref, title, origin, created_at`, and no other column. The title sets' `load`, in place of `repo.get_hypothesis` |
| `rejudge_job_key(name, version, subject_type, subject_id, day)` (D4) | The re-judge's dedupe key, spelled once, as `ask_job_key` is. Its own key, so a re-judge never shares a day's key with an ask. The two are disjoint by construction anyway: an ask is planned for a title with no canonical answer under the pin, and a re-judge only for one with |
| `pending_asks(conn, sets)` (changed in D4) | As C7, less the jobs whose payload carries `rejudge`, which cannot call |
| `failed_jobs_for_triage(conn, *, kinds, since, limit=200)` | `id, kind, error, finished_at` of jobs with `status = 'failed'`, `kind = ANY($1)`, `finished_at > since`, newest first. Its callers apply `code_cause`, the redactor and the admission. `since` is the later of now − 7 days and `MODEL_FIRST_OBSERVED[pin]` |
| `get_failed_job(conn, job_id)` | `id, kind, status, error, finished_at` |
| `unasked_subjects(conn, *, question_set, model, subject_type, subjects, day)` | Of the given addresses, those neither answered `ok` nor retired for the set, version and pin, and not waiting or planned today (C7's filters, generalised over a list) |
| `cards_to_rejudge(conn, *, question_set, model, limit, day)` (D4) | Content addresses of model-written titles with at least one candidate whose `status = 'active'` and a canonical `ok` `guardrail.card` answer at the registered version under the pin, and no re-judge about them waiting or planned today (`rejudge_job_key`) |
| `finding_records(conn, subjects)` (harness, D2) | Per address, `raised_by` and `severity` of the earliest model-written finding holding it |

### 5.4 Budget shares (`jev_catalogue.LANE_BUDGET_PERCENT`, code constants; safety)

| Lane | C | **D** | At the seeded 500 |
|---|---|---|---|
| research | 35 | **25** | 125 |
| guardrail | 35 | **25** | 125 |
| findings | 0 | **10** | 50 |
| ops | 0 | **10** | 50 |
| signals | 0 | 0 | 0 |
| decision | 20 | 20 | 100 |
| probe | 10 | 10 | 50 |

- **The minimum budget.** `MIN_DAILY_REQUEST_BUDGET` is derived as
  `max(ceil(100 / share))` and stays 10, so no stored budget changes meaning.
  Measurement's 5% shares would have raised it to 20.
- **The refusal message.** `settings_problem`'s refusal now names the lanes with
  the smallest share, read from the table **(added**, from operator's
  observation), rather than the literal "the probe lane's".
- **The decision lane.** Its share is untouched, so no findings or ops backlog
  can take the forward clock's calls.
- **Research and guardrail.** 125 calls each still cover the README's first day
  (about 61 screens and 61 catalogue asks).

### 5.5 Spend, top down

1. The daily budget.
2. The lane shares.
3. The planner's per-pass caps, and the waiting jobs counted against each
   share.
4. One call an attempt, and one retry in the client.
5. Three failed calls retire a subject.
6. Content addressing: a repeated title or skeleton is answered once and
   replayed.
7. Replays are free, and a re-judge can only replay: it is asked with no
   key, and is left out of the waiting count (section 5.1).

---

## 6. What each answer may change, and what it may never change

### 6.1 What it may change

| Set, question | Answer | Changes | Stored where |
|---|---|---|---|
| `findings.owner`, `findings.severity` | any | nothing | the ledger alone. Chips are computed at read time by `jev_chips` and stored nowhere |
| `ops.job_error` | any | nothing | the ledger alone |
| `guardrail.card`, unarmed | any | nothing | the ledger |
| `guardrail.card`, **armed** (D4) | When `card_addition(code, answer, (t,))` holds: the code accepts the title, and the answer is a valid `true` whose margin is at least `t` | **One finding per active candidate** of the model-written hypotheses holding the title. Each is `origin 'jev'`, `raised_by 'jev:guardrail.card'`, severity `'medium'` (a literal), `source_request_id` the answer's request, with a `J-` ref | `findings`, by `repo.raise_card_finding` alone, called by `jev_arming.card_follow_up` alone |
| `guardrail.injection` | as phase C | the quarantine, as phase C | `web_documents` |
| any set | a probe's answer (a re-ask) | nothing | the probe lane |

**The severity of a Jev finding is code's, not Jev's.** The literal `'medium'`
in the statement is the same for every answer. Jev's answer decides only
whether the row exists, and 0015 holds it to low or medium. docs/08 sanctions
the row itself: "Findings it raises carry `raised_by='jev:<set>'`, never in
`VETO_ROLES`", and the Guardrails row's "raises a finding".

### 6.2 What it may never change

- **A finding.** No Jev path changes a finding's severity, status, raiser,
  title, detail, candidate or anything else. 0015's
  `findings_keep_what_was_raised` trigger refuses every update but the
  closure's, and a return to `open`, for every writer. 0008's CHECK requires
  an operator for a closure. No writer at all can remove a finding: 0015
  refuses DELETE and TRUNCATE on `findings`, a cascade from a deleted
  candidate included (revised: D-SAFE-6).
- **Closing a finding**, or adding to `VETO_ROLES`.
- **Blocking a gate.** A Jev finding's raiser starts `jev:`, outside
  `VETO_ROLES`, and its severity is held below the blocking ones.
- **These tables:** `hypotheses`, `candidates`, `role_assessments`,
  `programme_decisions`, `gate_evaluations`, `experiments`, `system_flags` (no
  switch, the kill switch and the arming switch included), `deployments`,
  `orders`, `fills`, `daily_marks`, `daily_bars` and `jev_signals` (decision
  lane only, as before).
- **`jev_labels`.** No label is made from an answer.
- **`jev_evaluations`.** Only `evaluate --record` writes it.
- **`jobs`.** No resume, retry, cancel, fail or requeue of a job the programme
  did not claim. The planner's `enqueue` and the loop's own
  claim, complete, fail and lease are unchanged.
- **A generative model's prompt (I8).** A Jev finding never blocks, so it
  never enters `_no_blocking_findings`' detail, which is all
  `roles.facts_brief` shows of findings.
- **Any code constant.**

### 6.3 Every misuse a test must refuse

| # | Misuse | Refused by (section 13) |
|---|---|---|
| M1 | A suggested severity written into `findings.severity` | The trigger (T-S3); `TestWhatJevCodeCanWrite`; every `UPDATE findings` in `src/` sets only the closure columns |
| M2 | An answer closing or reopening a finding | Closing: `TestWhatJevCodeCanWrite`, and 0008's CHECK `findings_closed_by_an_operator`, which refuses any status but `open` without an `operator:` closer. Reopening (revised: D-SAFE-6): 0008's CHECK always admits `status = 'open'`, so it is no control here. The control is 0015's `findings_keep_what_was_raised`, which refuses a move from a closed status back to `open` for every writer, beside `close_finding`'s refusal of `open` in code and `TestWhatJevCodeCanWrite` |
| M3 | A `jev:` name in `VETO_ROLES`, or a Jev finding that blocks | `test_veto_roles_are_role_keys`; the CHECKs `findings_jev_never_blocks` and `findings_jev_is_raised_by_jev`; `test_a_jev_finding_never_blocks` |
| M4 | A duplicate chip used to unblock a gate | `test_closing_what_duplicate_chips_mark_unblocks_nothing` (a property over random registers) |
| M5 | A lower suggested severity offered as advice | `test_the_severity_chip_only_escalates` |
| M6 | A triage answer resuming, retrying, cancelling or failing a job | `test_nothing_in_the_programme_changes_a_job_it_did_not_claim`; the ops canary (each triaged job's row byte-identical under every outcome) |
| M7 | An answer touching any switch | `test_nothing_in_the_programme_writes_a_switch` |
| M8 | A raw job error, a secret or an account identifier sent | The redactor's properties; the `Literal`; `dump_state`; the error-use scan; the ops canary |
| M9 | A venue or programme job's error sent | `TRIAGED_KINDS` and its test; the planner's read; the handler's admission; the state's `Literal` |
| M10 | A finding's detail, remediation or close note, or a hypothesis's card, sent | `FindingTitleState`; `HypothesisTitleState`; the title sets' `load` by column list (`get_finding_title`, `get_hypothesis_title`); `test_the_jev_side_never_reads_detail`, a reach walk from every Jev root (revised: D-SAFE-2, D-HMB-16); the findings canary |
| M11 | An operator's, a pre-0015 or a Jev finding's title sent | `origin`; the read's `origin = 'model'`; the admission; `test_only_model_findings_are_asked` |
| M12 | The planner planning a call because of arming, or a re-judge making one | `PLANNER_MUST_NOT_REACH` gains `jev_arming` and `jev_calibration`; a re-judge is asked with `api_key=None` (section 5.1); P9, the moved pin included (revised: D-SAFE-4) |
| M13 | An armed threshold giving less friction, releasing or removing anything | P1–P6, P11 |
| M14 | A stale, superseded, dataset-labelled, other-model, other-plan or over-budget evaluation arming | P3, P8 |
| M15 | An answer reaching a generative prompt | `test_no_model_runner_loads_a_jev_or_web_module` (unchanged); `test_a_jev_finding_never_reaches_the_brief` |
| M16 | A finding raised on an operator-written hypothesis's candidate | `repo.active_model_candidates` reads `origin = 'model'` hypotheses alone; P4 |
| M17 | One skeleton filed under two subjects, or a forged subject | `STATE_ADDRESSED` in `_check_subject` |
| M18 | Ops triage about the programme's own jobs (a loop) | `TRIAGED_KINDS ∩ JEV_HANDLERS = ∅` |
| M19 | A new lane spending another's calls | the shares (`test_jev_catalogue.py`); the per-lane counts |
| M20 | A re-ask's answer raising a finding | P7 |
| M21 | A Jev finding's ref racing the tick's or the API's | the `J-` prefix; `test_jev_findings_take_their_own_refs` |
| M22 | A finding written with no stated writer, or as `'unknown'` | `DROP DEFAULT`; the insert trigger; `raise_finding`'s keyword-only `origin` with no default |
| M23 | A finding removed: deleted, truncated, or taken with its candidate (revised: D-SAFE-6) | 0015's `trg_findings_no_delete` and `trg_findings_no_truncate`; `test_phase_d_schema.py::TestWhatWasRaisedStaysRaised`, a case each, the cascade from a candidate's delete among them |
| M24 | A suggested reviewer without a veto shown beside a veto that blocks (revised: D-SAFE-3) | `jev_chips.route_chip`, which on a blocking finding returns a chip only for a role in `VETO_ROLES`; `test_jev_chips.py::test_the_route_chip_never_argues_against_a_veto` |
| M25 | A skeleton sent with the detail switch off (revised: D-SAFE-1) | `internal_detail` on `ops.job_error`, required by `TEXT_FREE_LANES`; the road's `_switched_on`; the planner's detail rule; the dark matrix's "ops on, detail off" case |
| M26 | An ops answer resting under a signal, or read as `internal` (revised: D-SAFE-5) | Provenance `system`, required by `STATE_ADDRESSED`; `jev_signals_provenance_check`, which refuses `system`; `record_signal`, which takes decision/internal sets alone; `test_jev_schema.py::TestTheVocabulariesAgree`, rewritten for the two vocabularies |
| M27 | A Jev finding resting on anything but a valid `true` to a canonical card request (revised: D-HMB-11) | 0015's trigger `findings_jev_rests_on_its_answer`; `test_phase_d_schema.py::TestAJevFindingRestsOnItsAnswer`, a case for each condition |

### 6.4 The contract phase E must meet

This follows operator §6.3, with severity shown only when it escalates. It is
binding on E, and D tests the pure functions behind it.

1. **Beside, never instead.** The recorded raiser, severity, status and raw
   error stay primary. A chip is secondary and labelled "suggested by Jev".
   - It shows inline its probability, its margin, the set version and
     `model_answered`.
   - It reads "not calibrated" unless the newest evaluation of that question
     is usable.
2. **No action hangs off a chip.** The close form shows no Jev content and
   pre-fills nothing.
3. **Friction, never its release.**
   - The severity chip appears only when the suggestion is more serious than
     the recorded level (`severity_chip`).
   - The owner chip says "suggested reviewer". It is routing, not a verdict on
     the finding. **On a finding that blocks, it is shown only when the role
     it names holds a veto** (`route_chip`; revised: D-SAFE-3). A reviewer
     without a veto beside a veto that blocks would argue the veto was raised
     outside its role's mandate, and invite a close as `accepted` or
     `withdrawn`, which is friction removed. The escape, and every role
     outside `VETO_ROLES`, stay in the ledger and are not shown there. On a
     finding that blocks nothing, the chip is shown for any role.
   - A duplicate chip points only from a newer finding to an older one, on the
     same candidate, that blocks at least as much.
4. **Code and Jev are told apart.** "code: data_missing (no_bars)" sits beside
   "Jev suggests: network (p 0.71, not calibrated)".
5. **An unknown is never a value.** The escape reads "Jev: unclear", and an
   invalid or missing answer reads "not measured".
6. **Every chip links to its ledger row**, and a Jev finding links to its
   request and its evaluation.
7. **No chip near a switch, the kill switch included.**
8. **No Jev answer is shown to a person while they label its set** (measurement
   §3.5). In D, `suggestions` shows statuses, never answers (section 9.3).
   Whether a labeller has read the findings register is not recorded (open
   item 75).

---

## 7. Who writes which table

| Table | Writer (caller) | What D writes | Constraint | Never |
|---|---|---|---|---|
| `jev_requests`, `jev_answers` | `jev_repo.record_exchange` via `jev_lane.ask` | The three sets' rows: lanes `findings` and `ops`, provenances `model` and `system`, subject types `finding_title` and `job_error` | 0012 and 0013's CHECKs, which already name these lanes; `jev_requests_provenance_check`, which 0015 widens to `system`; the canonical index | any other writer |
| `jev_labels` | `jev_repo.record_label` (`labels import`/`copy`) | People's labels of the new subjects | as C9 | a label from an answer |
| `jev_evaluations` | `jev_repo.record_evaluation` (`evaluate --record`) | Evaluations of the new sets; every recorded look | 0014 and 0015 | — |
| `findings` | `repo.raise_finding(…, origin=…)`, called by the tick with `'model'` and by the API with `'operator'`; **`repo.raise_card_finding`**, called by `jev_arming.card_follow_up` alone | `origin` on every new row; the armed card's findings | 0008, 0015 | any update but the closure's; a reopen; a delete or truncate, by any writer; a Jev path closing or re-rating |
| `jobs` | `job_repo.enqueue`, by `jev_plan` | `jev_ask` jobs of the new sets, and re-judges | `idx_jobs_dedupe_key` | `INSERT INTO jobs` anywhere else; an update from a Jev path but the loop's own |
| `system_flags` | migration 0015 | `jev_arm_card_check = false` | — | any write from `src/programme` |
| everything else | as phase C | nothing | — | — |

**Why no `audit_log` row and no `programme_decisions` row for an armed finding
(operator; safety's audit row not needed).** The finding is the record. Its
`source_request_id` names the answer, and its detail names the evaluation.
`programme_decisions` takes its ref from `repo._next_ref`, which the tick and
the API already race.

**Refs (added; revised: D-HMB-12).** `raise_card_finding` writes `'J-'` and
the count of Jev findings plus one, padded to at least four digits and never
cut:

```sql
WITH next AS (SELECT (COUNT(*) + 1)::text AS n FROM findings WHERE origin = 'jev')
SELECT 'J-' || lpad(n, greatest(4, length(n)), '0') FROM next
```

The padding is one constant, `repo.JEV_REF_SQL`, the expression over `n`, so
a test can evaluate it for any count without writing ten thousand findings.

PostgreSQL's `lpad` truncates a longer string. The first draft's
`lpad(…, 4, '0')` therefore gave the 10,000th Jev finding `J-1000`, which is
taken, and every later attempt computed the same ref. Checked this session on
the local cluster: `lpad('10001', 4, '0')` is `1000`, and the form above gives
`J-10001`. `repo._next_ref`'s `:04d` never truncates.

- Only the Jev loop writes Jev findings, one job at a time
  (`Programme._drain_jev`), so no `J-` ref is ever raced.
- With DELETE and TRUNCATE refused, the count never falls, so no ref is
  computed twice.
- The tick's and the API's `F-` refs never meet a `J-` ref. Their count
  includes Jev rows, so they skip numbers but never collide.
- A clash, for example two runners overlapping at a restart, fails the
  attempt. The retry replays and writes once.

### Migration `0015_jev_phase_d.sql` (D1)

A draft of this migration was applied on the scratch copy over a database at
0014, and both suites were run against it (section 13). It differed from the
block below in one respect, which the run showed was needed: every comparison
of `origin` in a trigger is now NULL-safe (`IS DISTINCT FROM`). A BEFORE
trigger runs before `NOT NULL` is checked. The draft's `NEW.origin <> 'jev'`
was NULL for an insert naming no origin, so its trigger raised its own error
where the column's `NOT NULL` should have.

```sql
-- 0015_jev_phase_d.sql
-- Phase D's schema. Additive, but for one CHECK of 0014's replaced whole and
-- jev_requests' provenance CHECK widened under its own name, as 0013 did.

-- =========================================================================
-- Who wrote each finding, and what was raised stays raised
-- =========================================================================
ALTER TABLE findings
    ADD COLUMN origin TEXT NOT NULL DEFAULT 'unknown',
    ADD COLUMN source_request_id BIGINT REFERENCES jev_requests (id);

-- The default existed to give the rows already stored 'unknown', which is
-- what it means: raised before 0015, by a writer nobody can now prove. Every
-- row from here on names its writer, or the insert fails.
ALTER TABLE findings ALTER COLUMN origin DROP DEFAULT;

ALTER TABLE findings
    ADD CONSTRAINT findings_origin_check
        CHECK (origin IN ('unknown', 'model', 'operator', 'jev')),
    -- A finding Jev's answer raised says so in its raiser, and only it does.
    ADD CONSTRAINT findings_jev_is_raised_by_jev
        CHECK ((origin = 'jev') = (raised_by LIKE 'jev:%')),
    -- It names the request it rests on, and only it does. What that request
    -- must be is the trigger's below: this CHECK only says one is named.
    ADD CONSTRAINT findings_jev_names_its_request
        CHECK ((origin = 'jev') = (source_request_id IS NOT NULL)),
    -- It can never block, whatever VETO_ROLES holds.
    ADD CONSTRAINT findings_jev_never_blocks
        CHECK (origin <> 'jev' OR severity IN ('low', 'medium')),
    -- It belongs to a candidate.
    ADD CONSTRAINT findings_jev_is_on_a_candidate
        CHECK (origin <> 'jev' OR candidate_id IS NOT NULL);

-- One finding per candidate per answer, so a retried follow-up adds nothing.
CREATE UNIQUE INDEX IF NOT EXISTS findings_one_per_jev_answer
    ON findings (candidate_id, raised_by, source_request_id)
    WHERE origin = 'jev';

CREATE OR REPLACE FUNCTION findings_origin_is_known() RETURNS trigger AS $$
BEGIN
    IF NEW.origin IS NOT DISTINCT FROM 'unknown' THEN
        RAISE EXCEPTION
            'a finding raised from migration 0015 on names its writer (finding %)',
            NEW.ref;
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_findings_origin_is_known
    BEFORE INSERT ON findings
    FOR EACH ROW EXECUTE FUNCTION findings_origin_is_known();

-- (revised: D-HMB-11) A Jev finding rests on a valid `true` to a canonical
-- guardrail.card request, as jev_signals_rest_on_their_answer holds a signal
-- to its answer. Refused here rather than left to the foreign key, which
-- checks later, with a newer snapshot.
CREATE OR REPLACE FUNCTION findings_jev_rests_on_its_answer() RETURNS trigger AS $$
DECLARE
    origin RECORD;
BEGIN
    IF NEW.origin IS DISTINCT FROM 'jev' THEN
        RETURN NEW;
    END IF;
    SELECT r.status, r.lane, r.question_set
      INTO origin
      FROM jev_requests r
     WHERE r.id = NEW.source_request_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'findings: request % is not visible to this transaction',
            NEW.source_request_id
            USING ERRCODE = 'foreign_key_violation';
    END IF;
    IF NOT (origin.status = 'ok'
            AND origin.lane <> 'probe'
            AND origin.question_set = 'guardrail.card'
            AND NEW.raised_by = 'jev:' || origin.question_set
            AND EXISTS (SELECT 1 FROM jev_answers a
                         WHERE a.request_id = NEW.source_request_id
                           AND a.question_key = 'performance_claim'
                           AND a.valid
                           AND a.argmax = 'true'))
    THEN
        RAISE EXCEPTION
            'findings: a Jev finding rests on a valid true answer to a canonical guardrail.card request (request %)',
            NEW.source_request_id;
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_findings_jev_rests_on_its_answer
    BEFORE INSERT ON findings
    FOR EACH ROW EXECUTE FUNCTION findings_jev_rests_on_its_answer();

-- Only the closure columns change, and a closed finding is never reopened;
-- 0008's CHECK still needs an operator to close, and admits `open` always,
-- which is why the reopen is refused here (revised: D-SAFE-6). Compared
-- whole, so a column a later migration adds is covered.
CREATE OR REPLACE FUNCTION findings_keep_what_was_raised() RETURNS trigger AS $$
BEGIN
    IF (to_jsonb(NEW) - ARRAY['status', 'closed_at', 'closed_by', 'close_note'])
       IS DISTINCT FROM
       (to_jsonb(OLD) - ARRAY['status', 'closed_at', 'closed_by', 'close_note'])
    THEN
        RAISE EXCEPTION 'a finding changes only by its closure (finding %)', OLD.ref;
    END IF;
    IF OLD.status IS DISTINCT FROM 'open' AND NEW.status IS NOT DISTINCT FROM 'open' THEN
        RAISE EXCEPTION 'a closed finding is never reopened (finding %)', OLD.ref;
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_findings_keep_what_was_raised
    BEFORE UPDATE ON findings
    FOR EACH ROW EXECUTE FUNCTION findings_keep_what_was_raised();

-- (revised: D-SAFE-6) What was raised stays raised: no writer removes a
-- finding, a blocking veto included, and a candidate's delete, which would
-- cascade to its findings, fails with them. Raised rather than skipped, as
-- the Jev ledger's refusals are, and TRUNCATE by a statement trigger, which a
-- row trigger never sees.
CREATE OR REPLACE FUNCTION findings_refuse_removal() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'findings keeps what was raised: % is refused', TG_OP
        USING HINT = 'Close the finding instead; only an operator can.';
END $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_findings_no_delete
    BEFORE DELETE ON findings
    FOR EACH ROW EXECUTE FUNCTION findings_refuse_removal();
CREATE TRIGGER trg_findings_no_truncate
    BEFORE TRUNCATE ON findings
    FOR EACH STATEMENT EXECUTE FUNCTION findings_refuse_removal();

-- =========================================================================
-- The card check's arming switch, off
-- =========================================================================
INSERT INTO system_flags (key, value, updated_by)
VALUES ('jev_arm_card_check', 'false'::JSONB, 'migration')
ON CONFLICT (key) DO NOTHING;

-- =========================================================================
-- Provenance `system` (revised: D-SAFE-5): this system's own records,
-- computed in code, which can quote an outsider. A request may carry it; a
-- signal may not, so jev_signals_provenance_check is left as 0013 wrote it,
-- and jev_signals_rest_on_their_answer, which holds a signal's provenance to
-- its request's, can never admit a signal on a `system` request.
-- =========================================================================
ALTER TABLE jev_requests DROP CONSTRAINT jev_requests_provenance_check;
ALTER TABLE jev_requests ADD CONSTRAINT jev_requests_provenance_check
    CHECK (provenance IN ('web', 'internal', 'operator', 'model', 'system'));

-- =========================================================================
-- Plan v2 (M2): a flip rate counts the set's population, so its pair counts
-- are no longer bounded by the n scored items. Every other conjunct of
-- 0014's rule is kept, word for word.
-- =========================================================================
ALTER TABLE jev_evaluations
    DROP CONSTRAINT jev_evaluations_counts_within_n,
    ADD CONSTRAINT jev_evaluations_counts_within_n CHECK (
        n_valid BETWEEN 0 AND n
        AND n_escape BETWEEN 0 AND n
        AND n_invalid BETWEEN 0 AND n
        AND n_not_asked BETWEEN 0 AND n
        AND n_distinct_states BETWEEN 0 AND n
        AND n_at_threshold BETWEEN 0 AND n
        AND labeller_agreement_n BETWEEN 0 AND n
        AND vs_majority_jev_right_only >= 0
        AND vs_majority_baseline_right_only >= 0
        AND vs_majority_jev_right_only + vs_majority_baseline_right_only <= n
        AND vs_keyword_jev_right_only >= 0
        AND vs_keyword_baseline_right_only >= 0
        AND vs_keyword_jev_right_only + vs_keyword_baseline_right_only <= n
    ),
    ADD CONSTRAINT jev_evaluations_flip_counts_are_counts CHECK (
        flip_rate_n >= 0
        AND flip_rate_low_margin_n >= 0
        AND flip_rate_near_threshold_n >= 0
        AND flip_rate_not_compared >= 0
        AND flip_rate_low_margin_not_compared >= 0
        AND flip_rate_near_threshold_not_compared >= 0
    );
```

- **No backfill.** Existing rows read `'unknown'` and are never sent. The
  programme has never called a model, so no row can be a model's. A backfill
  from `audit_log` would be a guess, because `create_finding` writes the
  finding and its audit row as two statements.
- **The one update.** `close_finding`'s is the only `UPDATE findings` in
  `src/` (checked), and it sets closure columns alone.
- **Applying it.** 0015 applies over a database at 0014 holding rows, or fails
  whole.
- **The tests it moves (added; revised: D-HMB-01).** Found by running both
  suites on the scratch copy, not by reading, and listed in section 13's last
  table:
  - With the default dropped, every insert into `findings` must name its
    writer.
  - With DELETE refused, `test_programme_panel_atomicity.py`'s clean-up, which
    deletes its candidate and its taken finding, must leave them, retiring
    the candidate instead.
  - With the flip bounds moved, seventeen cases of C9's schema suite name the
    wrong rule or are now admitted.
  - With `system` added to one of the two provenance CHECKs, the schema
    suite's vocabulary test reads two vocabularies.

  They land in D1, or D1's integration suite fails.
- **Nothing in `src/` deletes a finding or a candidate** (checked: no `DELETE
  FROM findings`, `DELETE FROM candidates` or `TRUNCATE` in `src/`). Only that
  one integration test's clean-up did, and it changes in D1.
- **Its rules.** Each named rule and each conjunct no other rule implies has a
  case breaking it alone. `::test_every_rule_0015_adds_has_a_case` holds that,
  as C9's review required of 0014.

---

## 8. Every switch, read where

| Switch | Seeded | Read by in phase D | Fail-closed reader |
|---|---|---|---|
| `programme_enabled` | off (0007) | The road (every ask), the claim, the planner, `jev_arming` | `flags.programme_enabled` |
| `jev_enabled` | off (0012) | The same | `flags.jev_enabled` |
| `jev_area_findings` | off (0012) | The road for `findings.*`; the planner's findings rules | `flags.jev_area_enabled(conn, "findings")`, which needs the master too |
| `jev_area_ops` | off (0012) | The road for `ops.job_error`; the planner's ops rule; `preview` | `flags.jev_area_enabled(conn, "ops")` |
| `jev_area_guardrails` | off (0012) | The road for the card; the planner's card asks and re-judges; `jev_arming` | `flags.jev_area_enabled(conn, "guardrails")` |
| **`jev_arm_card_check`** (new) | off (**0015**) | `jev_arming`, on every follow-up, before any evaluation is read; the planner's re-judge rule; the harness's `status` and `report` | `flags.jev_arm_card_check`, through `flags._switch`: on only for a stored JSON `true`. `JEV_KEYS` gains it, held to the seeds of 0012 and 0015 |
| `jev_model` | `jev-1.13.0` | The road, the planner, `jev_arming` (the pin `usable` compares with) | `flags.jev_model` |
| `jev_daily_request_budget`, `jev_max_state_tokens` | 500, 8,000 | The road; the planner's room | unchanged |
| `jev_send_internal_detail` | off | The road, for a set declaring `internal_detail`, which from D3 is `ops.job_error`; **the planner** (new; live for ops from D3; revised: D-SAFE-1); `preview` | `flags.jev_send_internal_detail` |
| `trading_enabled`, `programme_max_auto_stage` | — | Nothing in `src/programme`'s Jev modules reads or writes either | — |

What each act needs, with every conjunct read by its own reader and none
derived from another:

- **To send a finding title:** programme ∧ Jev ∧ findings, read by the road at
  the moment of sending.
- **To send a skeleton:** programme ∧ Jev ∧ ops ∧ `jev_send_internal_detail`
  (revised: D-SAFE-1). With ops on and the detail switch off, nothing is
  planned and nothing is sent: a case of the dark matrix
  (`test_jev_dark.py`), and of the planner's switch matrix.
- **To raise an armed finding:** programme ∧ Jev ∧ guardrails ∧
  `jev_arm_card_check` ∧ a usable newest evaluation labelled by a person for
  the registered version under the pin ∧ `card_addition`. Any conjunct that
  cannot be read means no finding.

---

## 9. Module boundaries and the tests that hold them

### 9.1 Modules

| Module | Kind | May import | Must not reach (tested) | Writes |
|---|---|---|---|---|
| `jev_redact` (new, D3) | pure, API-importable | the standard library | anything else (fresh interpreter) | nothing |
| `jev_chips` (new, D2/D3) | pure, API-importable | the standard library, `jev_redact` | anything else (fresh interpreter); no writer | nothing |
| `jev_arming` (new, D4) | **runner-only** (`RUNNER_ONLY`; Safety rule 5's list) | `flags`, `jev_repo`, `jev_calibration`, `jev_prereg`, `jev_questions`, `claims`, `repo`, `asyncpg` | the lane and its client, `jev_plan`, `jev_forward`, `web_*`, `client`, `author`, `panel`, `tick`, `main`, the vault, `src.crypto`, every forbidden SDK (`ARMING_MUST_NOT_REACH`) | `findings`, through `repo.raise_card_finding` alone |
| `jev_calibration` | pure | `jev_prereg`, `jev_stats` | as C9 | nothing. It gains the pure `ARMABLE`, `Arming`, `arming` and `card_addition`, and `usable` gains `looks` and M5 |
| `jev_questions`, `jev_catalogue`, `jev_prereg`, `jev_lane`, `jev_jobs`, `jev_plan`, `jev_repo`, `jev_eval`, `jev_forward`, `flags` | as C | `jev_questions` gains `jev_redact`; `jev_jobs` gains `jev_redact`, `jev_chips` and `jev_arming`; `jev_plan` and `jev_eval` gain `jev_redact` and `jev_chips` | as C, plus the rows below | as C |
| `repo`, `tick`, `src/api/routers/programme.py` | unchanged in kind | — | still name no Jev table and load no `jev_*` module | `findings.origin`, by literal; `repo` gains `raise_card_finding` and `active_model_candidates`, each naming its columns, never `*` (the detail-read walk below reaches both) |

### 9.2 Boundary rules added (each a test, section 13)

- `RUNNER_ONLY` gains `jev_arming`, and CLAUDE.md's Safety rule 5 list names it
  (`test_safety_rule_5_names_every_runner_only_module`).
- `PURE_PROGRAMME_MODULES` gains `jev_redact` and `jev_chips`, and
  `PURE_MODULES_MAY_LOAD["src.programme.jev_chips"] =
  ("src.programme.jev_redact",)`.
- **The calibration's move (open item 67; safety B4).**
  `test_nothing_that_acts_loads_the_calibration` becomes four tests:
  1. `jev_calibration`'s importers in `src/` are exactly `jev_eval` and
     `jev_arming`, under every spelling the graph reads.
  2. The closures of the planner, the forward clock, the lane, its client,
     `web_ingest`, `web_fetch` and the four model runners reach it not at all.
  3. From `jev_jobs` and `main`, every path to it passes through `jev_arming`.
     With `jev_arming` removed from the graph, it is unreachable.
  4. `jev_arming` is imported by `jev_jobs` alone, under every spelling.

  `test_nothing_that_can_move_money_loads_the_calibration` is unchanged.
- `card_verdict` and `card_addition` are called in `src/` only in `jev_arming`
  and in `jev_calibration` itself. `usable` and `arming` are called only in
  `jev_arming`, `jev_eval` and `jev_calibration`. `document_path` is called by
  nothing that acts.
- `PLANNER_MUST_NOT_REACH` gains `jev_arming` and `jev_calibration`, and
  `HARNESS_MUST_NOT_REACH` gains `jev_arming`. The harness reports arming
  through the pure `arming`, and holds nothing.
- `ARMING_MUST_NOT_REACH`: a walk from `jev_arming`.
- Every `jev_*` and `web_*` module is still kept out of the model runners
  (I8, unchanged). The tick's one edit is a literal.
- **The API cannot reach `jev_arming` (revised: D-SAFE-7).** The design
  first cited `test_the_api_imports_no_runner`, which does not exist. The two
  real tests read `RUNNER_ONLY`, so adding `jev_arming` to it binds both:
  `test_the_api_does_not_import_the_programme_runner` (direct imports) and
  `test_the_programme_modules_the_api_imports_hold_no_client` (the closure,
  `FORBIDDEN_PREFIXES + RUNNER_ONLY`). Each must fail on a synthetic tree in
  which a module of `src/api` holds `from src.programme import jev_arming`
  (`_synthetic`, as the file's other scans are proved).
- **The Jev side reads no detail (D1; revised: D-SAFE-2, D-HMB-16).** The
  first draft's test scanned the SQL spelled in `jev_*` and `web_*` modules.
  But Jev code reads rows through `src/programme/repo`, whose readers run
  `SELECT *`. At `23dee2b`, `jev_jobs._load_hypothesis` calls
  `repo.get_hypothesis`, so every title ask already reads the card (checked).
  The scan could not see it, and would not have seen a later call to
  `repo.list_findings`, which reads `detail_md`, `remediation` and
  `close_note`. The test is now a reach walk:
  - It uses the `_Reach` that `test_jev_jobs.py`'s card-check scan uses, from
    every root on the Jev side: each `JEV_HANDLERS` handler, each `ASKABLE`
    `load`, `admit`, `build` and `follow_up`, `jev_plan.plan`, every `jev_eval`
    command, and from D4 `jev_arming`.
  - It refuses any reachable function whose SQL reads `*` from `hypotheses`,
    `findings` or `role_assessments`, or names a detail column of them in a
    SELECT or a RETURNING. The detail columns are a hypothesis's `card` and
    `decision_rationale`, a finding's `detail_md`, `remediation` and
    `close_note`, and an assessment's `summary` and `evidence`.
  - An INSERT that writes `detail_md` or `remediation`, as
    `raise_card_finding` does with code-built words, is a write, not a read.
  - It is proved on synthetic trees: a handler calling `repo.get_hypothesis`,
    and one calling `repo.list_findings`, must each trip it.
  - D1 moves the title sets' `load` to `jev_repo.get_hypothesis_title`, so the
    walk passes at D1.

### 9.3 The harness: the read surfaces D adds

Both commands are read-only, run in one snapshot, read `DATABASE_URL` alone,
and stay inside the harness's closure.

- **`python -m src.programme.jev_eval preview --set S [--limit N] [--json]`
  (operator; D2/D3).** It runs the reads the planner runs for `S` and prints:
  - each subject;
  - the row it comes from;
  - **the exact state that would be sent**, or why it would not be;
  - for `ops.job_error`, each recent failed job with its code chip and shape;
  - which switches would have to be on, and whether they are.

  It enqueues nothing and loads no planner, lane or client. An integration test
  holds its subjects and states equal to the planner's and the handler's on
  the same rows. It is what an operator reads before switching an area on.
- **`python -m src.programme.jev_eval suggestions [--json]` (safety; D2–D4;
  revised: D-HMB-04).** It prints labels, numbers and ids, never a title or an
  error. **It prints no Jev answer, no probability and no chip until phase E.**
  Anyone who reads it may later label a set, and a label made after seeing the
  answer is not blind. It prints:
  - each open finding's ref, and for each findings set whether it was asked
    and how the ask came out: answered, invalid, held, or not asked and why;
  - each failed job of the last seven days, by id and kind, with code's chip
    (code's, never Jev's), and whether Jev was asked and how it came out;
  - whether the card check is armed, and every reason it is not;
  - the count of Jev findings raised, never their refs. The register shows
    them, and a ref next to a hypothesis says what Jev answered about its
    title.
- **`status` and `report`.** `status` gains one line, "card check: armed /
  would arm if switched on / not armed (reasons)". `report` prints the looks
  each identity has spent (M3).

---

## 10. Arming the card check (D4)

### 10.1 Exactly when `card_verdict` is consulted

`card_verdict` is consulted in one acting place: `jev_arming.card_follow_up(conn,
row, result)`, the follow-up of `ASKABLE["guardrail.card"]`.
`jev_jobs.run_ask` runs it after the one ask, inside the attempt.

- **It acts only on `result.status == "ok"`**: a fresh canonical answer, or a
  replay of one, which is how a re-judge reaches it. A re-judge that finds no
  canonical answer under the pin in force meets `no_key`, having sent nothing,
  and `run_ask` completes it as `not_on_record` before any follow-up runs
  (section 5.1).
- `row` is the title sets' projection, `ref, title, origin, created_at`
  (`jev_repo.get_hypothesis_title`), and nothing more (revised: D-SAFE-2).
- On every other status it returns `{}` at once, as `_screen_follow_up` does.
- It is never run by `run_reask`, the planner, the lane, the tick, the API or
  the forward clock.
- The harness reads the pure `arming` to report, and acts on nothing.

### 10.2 From which evaluation

`jev_arming.armed_calibration(conn)` reads, each through its own fail-closed
reader:

- `programme_enabled`, `jev_enabled`, `jev_area_enabled("guardrails")` and
  `jev_arm_card_check`;
- the pin;
- the registered `guardrail.card`;
- `jev_repo.evaluations_for(conn, question_set="guardrail.card")`, every
  version, newest first.

It then calls the pure `jev_calibration.arming(rows, *, name, version, key,
pin, plan_hash, switched_on)`, with `plan_hash =
analysis_plan_hash("guardrail.card", version)`. That function returns
`Arming(calibration=(t,), evaluation_id=…, reasons=())` only if every one of
the following holds:

- **The pair is armable.** `(name, key)` is in `ARMABLE =
  frozenset({("guardrail.card", "performance_claim")})`, a code constant of one
  pair. No other set or question can be armed in D, whatever is recorded.
- **The switches are on.** Otherwise the reason is `switch`.
- **The newest row is chosen.** It is the newest row of `(name, registered
  version, key, pin)` by `(created_at, id)`, whoever labelled it and on
  whatever split. A newer evaluation that fails **disarms**, and nothing older
  is consulted.
- **It was labelled by a person.** Its `dataset_ref` starts `operator:`
  (safety, measurement), never a dataset's.
- **It is usable.** `usable(newest, earlier=every other row, pin, plan_hash)`
  is `(True, t, [])`:
  - the test split, with at least 200 items;
  - not possibly in training;
  - a threshold chosen on the development split and borne out on the test
    split (`held_out`);
  - both baselines beaten by the exact sign test;
  - both flip rates measured on 30 pairs and within limits in the worst case
    (M5);
  - a fresh test set;
  - the newest of its key;
  - the plans in force;
  - **no more than `MAX_LOOKS` looks spent (M3)**, counted per set, version
    and question across every model (revised: D-HMB-06).

Otherwise it returns the reasons. The calibration is read at each follow-up and
never cached, so a change takes effect from the next job.

A database error while reading raises. The attempt then fails for a retry, and
nothing is raised on a read that failed.

### 10.3 What arming does (operator, measurement)

```python
# row: jev_repo.get_hypothesis_title's projection; subject = text_sha256(row["title"])
answer = result.answers.get("performance_claim")
code = "reject" if claims.find_performance_claim(row["title"]) else "accept"
arming = await armed_calibration(conn)
if jev_calibration.card_addition(code, answer, arming.calibration):
    # card_verdict(code, answer, cal) == "reject" and card_verdict(code, answer, None) == "accept"
    async with conn.transaction():  # a savepoint inside a caller's
        for candidate in await repo.active_model_candidates(conn, title_sha256=subject):
            await repo.raise_card_finding(conn, candidate_id=..., hypothesis_ref=...,
                                          request_id=result.request_row_id,
                                          title=..., detail=..., remediation=...)
```

`repo.active_model_candidates` returns the candidates with `status = 'active'`
of hypotheses with `origin = 'model'` whose title address equals the subject.
`raise_card_finding` writes one row per candidate:

- `origin 'jev'`, `raised_by 'jev:guardrail.card'` and severity `'medium'`,
  each a literal in its statement;
- the `J-` ref;
- `source_request_id`;
- `ON CONFLICT … WHERE origin = 'jev' DO NOTHING`.

Its words, built by code from ids and numbers, and pinned in `jev_arming`:

- **title:** `Jev's calibrated card check reads the title of {hypothesis_ref} as stating a performance result`
- **detail:** `guardrail.card v{version}, question performance_claim: Jev's stated probability of true {p:.2f}, a lead of {margin:.2f} over false, at or above the threshold {t:.2f} chosen on evaluation {id} (the test split, {n} items labelled by {labeller}, {n_at} measured at the threshold). Request {request}, model {model}. The code's own check accepts this title. This finding blocks nothing, and only an operator closes it.`
- **remediation:** `An operator reads the title. A title that states or promises a result is replaced by a new hypothesis whose title states the idea to test, and this finding is closed.`

What the follow-up does in the other cases:

- **The code rejects the stored title** (a pre-C8 title): nothing is raised.
  The code's rule is enforced where it lives, before storage. The result says
  `code_rejects_stored_title`, and `suggestions` lists it.
- **No candidate is active:** nothing is raised, and the result records it.

The result records, labels and numbers only:

- whether it was armed, with the evaluation's id and the threshold, or the
  reasons it was not;
- `code`, the verdict, and whether the finding was `added`;
- the refs raised, and the count of active candidates.

### 10.4 Re-judges (safety; revised: D-SAFE-4, D-HMB-05)

While `jev_arm_card_check` is on, the planner's `_plan_rejudges` plans one
re-judge a UTC day for each title that has an active candidate and a
canonical `ok` answer. The re-judge replays that answer and runs the
follow-up, so arming reaches the candidates still in play whose titles were
answered before it.

- **It can make no call, by construction.** `run_ask` asks a re-judge with
  `api_key=None`, and the road's every call sits behind its key check, after
  the canonical lookup (section 5.1). The first draft asked with the live key.
  It planned a re-judge with `calls=False`, outside the lane's room and under
  holds, yet the road looks the canonical answer up under the pin it reads at
  run time (`jev_lane.py`). A pin moved between the plan and the claim
  therefore found no canonical row, and the job made a fresh card call the
  planner never counted.
- Such a re-judge now completes as `not_on_record`, having sent and written
  nothing. The title is asked under the new pin by the ordinary card rule,
  from the guardrail share, like any title with no answer under the pin.
- It reads no calibration, only the switch. With no usable evaluation, the
  replay raises nothing.

### 10.5 What arming may never do

Arming may never:

- reject, hold, retire, release or promote a candidate;
- touch a hypothesis, another finding, a decision row, a stage or a
  deployment;
- act on a re-ask, an invalid answer, a tie, a `false`, an answer below the
  threshold, or a code-only rejection;
- plan a call;
- arm the injection screen's line.

The tick needs no change, because a non-blocking finding changes no gate.

### 10.6 Property tests

| # | Property | Where |
|---|---|---|
| P1 | `card_verdict`, exhaustive (C9's, kept). It never accepts what the code rejected. With no calibration it is the code's verdict exactly. Armed, it only adds rejections | `test_jev_calibration.py` |
| P2 | `card_addition`, exhaustive over code × answer (none, invalid, tie, valid `false`, valid `true`) × margins on the 0.01 grid written as decimals × every threshold on `MARGIN_GRID`. It is never true unarmed, and never true when the code rejects. It holds exactly when the answer is valid `true` with margin ≥ t. It is monotone: a lower threshold adds a superset | `test_jev_calibration.py` |
| P3 | `arming`: each condition alone disarms. The conditions: the switch; each `usable` reason, including `looks` and M5; a labeller that is not a person; a pair not in `ARMABLE`; no rows; a newer unusable row over an older usable one; another pin; another version; another plan hash | `test_jev_calibration.py` |
| P4 | The follow-up oracle, against a fake ledger applying 0015's rules. It runs over: every switch on, off or unreadable; every evaluation state; every kind of answer; both code verdicts; candidate statuses active, held, rejected and retired; 0, 1 and 2 active candidates; hypothesis origins model and operator. The findings written equal the oracle's, and no other statement is executed | `test_jev_arming.py` |
| P5 | Armed against unarmed, end to end (revised: D-HMB-15). The same ledger and scripted answers run twice through the programme's loop, every switch on in both, `jev_arm_card_check` included, so both plan the same jobs. The armed run alone has a usable evaluation recorded, built to pass 0014 and 0015 under plan v2, with the labels it was computed from. Findings appear only in the armed run, only for answers that pass `card_addition`, one per active candidate per answer. **Compared equal across the runs:** every table but `findings`, `jev_evaluations` and `jev_labels`, and `jobs` in every column but `result`. **Asserted apart:** each job's `result` is equal across the runs but for its arming fields (`armed`, the evaluation's id and threshold or the reasons, `added`, the refs raised). Those read armed with the recorded evaluation in one run, and not armed with its reasons in the other. The first draft compared "every other table", which could not pass: the armed run's evaluation row and its jobs' results differ by construction | `tests/integration/test_jev_arming.py` |
| P6 | Static. The only insert of an `origin 'jev'` finding is `raise_card_finding`'s. Its callers in `src/` are `jev_arming` alone. No `UPDATE`/`DELETE` of `findings`, `candidates` or `hypotheses` is reachable from Jev code | `test_jev_table_boundaries.py` |
| P7 | A re-ask's answer `true` at margin 1.0, under a usable evaluation with every switch on, raises nothing. `run_reask` reaches no `jev_arming` | `test_jev_arming.py` |
| P8 | The calibration is read at the moment of the follow-up. An evaluation recorded between two jobs changes only the second. A newer unusable one disarms. A switch turned off between the plan and the run disarms. A failed read raises nothing and fails the attempt for a retry | unit and integration |
| P9 | Re-judges are replays, by construction (revised: D-SAFE-4, D-HMB-05). `cards_to_rejudge` returns only subjects with canonical `ok` answers under the registered version and the pin. A fake client counts zero calls, and the planner takes no call from the share. **The pin moved between plan and run:** a re-judge planned under one pin and claimed after `jev_model` names another makes no call (the fake client counts zero), writes no `jev_requests` row and raises nothing, and its job completes as `not_on_record`. A re-judge's payload with any set but `guardrail.card`, or `rejudge` anything but `True`, is refused as malformed | `test_jev_plan.py`, `test_jev_jobs.py`, integration |
| P10 | The screen stays unarmed. `document_path` takes no calibration; `ARMABLE` holds no screen pair; `_screen_follow_up` reaches no `jev_arming` | `test_jev_calibration.py`, `test_import_boundaries.py` |
| P11 | A Jev finding never blocks. `FindingFact.blocks` is false for every row 0015 admits. Gate results are identical with and without one. It never appears in `roles.facts_brief` | `test_programme_gates.py`, `test_programme_convene.py`, integration |
| P12 | Idempotent. A retried attempt raises no second finding (the unique index), and two follow-ups on one answer raise one finding per candidate | integration |

### 10.7 The outlook, plainly

The stored model titles have already passed the claims check (C8:
`author.propose_hypothesis` screens the title). Positives are therefore
promises without numbers, and rare.

At plausible rates (section 3.6), arming needs about 1,300 to 2,800 labelled
titles for its floors, all written after 26 September 2026. The near-threshold
flip rate binds harder (revised: D-HMB-03). Above a threshold of 0.30 its 30
pairs come from the uniform stratum alone (open item 80). If one answer in
five to ten lies within 0.10 of the threshold, that is about 3,000 to 6,000
distinct titles asked under the pin, at most ten re-asks a day across every
lane. The card check is built to arm, and will very likely stay unarmed for
years. `status` says so every day.

---

## 11. Open questions for the owner

Decide each before D1 merges, while it is free:

1. **Plan v2's items.** R1 and R2 are required. M1–M4 are recommended together
   (measurement): with them, every case section 3.6 computes needs fewer
   labels than v1, and the first arming does not rest on optional stopping.
   M5 is this design's addition (open item 68). Each is separable.
2. **The armed effect.** A finding that never blocks (chosen). Alternatively, a
   hold, once phase E gives a held candidate a release route: that would be a
   change of decision policy, made in code, not a plan.
3. **The findings sets** (revised: D-HMB-03). Keep `findings.severity` (one
   call per title, measured, shown only when it escalates) or drop it.
   Measurement expects it never to reach 0.80. Keep `findings.owner` or drop
   it: it is not expected to beat the raiser it is measured against
   (section 3.6), so its chip will most likely read "not calibrated" for
   good. It is a routing suggestion at one call per title.
4. **Ops provenance.** `system` (chosen; revised: D-SAFE-5), which `jev_signals`
   refuses by CHECK, or `internal`, which the phase F loader is to trust.
5. **The triaged kinds.** Research and ingest only (chosen). Venue, shadow and
   programme kinds get code chips alone.
6. **Duplicates.** Code-exact only, with the Jev question deferred (open item
   71).
7. **Shares.** 25/25/10/10/20/10, with the minimum budget staying 10.
8. **Time to arm** (revised: D-HMB-03). Years: 1,300 to 2,800 labelled titles
   for the floors, and about 3,000 to 6,000 titles asked under the pin for the
   near-threshold flips (section 3.6). Accept it, or revisit the card's target
   before any card answer exists, which is a free set-plan change.
9. **The exposure of card labels after the first armed finding** (open item
   72).
10. **Who labels for arming.** A person only (chosen).
11. **The worker's error naming its class** (open item 73). It is not in D;
    reviewed as a worker change of its own.
12. **The daily report's "blocking" count**, which counts every high or
    critical finding (open item 74). It is pre-existing and fixed on its own.
13. **The arming switch's granularity.** One per armable pair (chosen), set
    through phase E's typed confirmation.
14. **How ops items are dated** (revised: D-HMB-08). Over the rows the
    population reads (chosen), so `possibly_in_training` reads false for
    every ops item. Or over every occurrence, so a recurring vendor error
    seen before 26 September 2026 marks any ops evaluation as an upper bound,
    and none is ever armable (open item 81).
15. **Ops skeletons behind the detail switch** (revised: D-SAFE-1). docs/08
    fact 7's defaults, which the operator recorded, send code-computed
    features and titles. Other text of this system's goes only while
    `jev_send_internal_detail` is on. A skeleton is neither a feature nor a
    title, so it waits for the detail switch as well as the ops area
    (chosen). If the owner would rather ops ran under its area switch alone,
    that is a change to fact 7's defaults. It is made in docs/08 before D3
    merges, `TEXT_FREE_LANES` then refuses `internal_detail` rather than
    requiring it, and the dark matrix's "ops on, detail off" case is
    reversed. Know before answering: the detail switch is one switch for all
    of this system's detail. Switched on for ops, it lets any later set
    declaring `internal_detail` send too, once that set's own area is on
    (open item 82).
16. **The owner chip on a blocking finding** (revised: D-SAFE-3). Shown only
    when it names a role that holds a veto (chosen), or never on a blocking
    finding.
17. **Label exposure** (revised: D-HMB-04). `suggestions` now shows no
    answer. Nothing records which labeller has read the findings register,
    which shows the raiser and the severity beside each title. Accept that for
    D, where no findings set can arm (open item 75), or ask for exposure to be
    recorded before a findings set is ever armable.

---

## 12. The pull-request split

There are four pull requests, each dark. Each has its own "Phase D, as built"
subsection in docs/08, its CLAUDE.md rows, and ruff, the unit suite, parity,
the integration suite on PostgreSQL and the SDK job all green.

**Order.** D1 comes first, and it **merges before any Jev area is first
switched on**. D2 and D3 follow in either order. D4 is last, so that the
allow-list of what Jev code can write is final.

| PR | Contents | Depends on | Dark because |
|---|---|---|---|
| **D1 — plan v2 and the foundations** | Plan v2: R1, R2, M1–M5 (looks across models), and the regime plan apart (`jev_forward` result, `jev_eval forward`); migration 0015 and its schema suite (origin, the Jev finding's trigger, no reopen, no delete or truncate, the arming switch, `system` on `jev_requests`, the flip counts); `repo.raise_finding(origin=…)`, keyword-only with no default, at its two callers; `jev_repo.get_hypothesis_title` as the title sets' `load`; `STATE_ADDRESSED` (a mapping to its writer's provenance) and `TEXT_FREE_LANES` in the registry, `dump_state` and `_check_subject`, tested with test-only sets; `system` in `PROVENANCES` and the detail rule; `flags.jev_arm_card_check` and `JEV_KEYS`; the shares and the settings message; the planner's detail-switch rule; the harness's M2, M3 (enforced in `execute`) and M5; the boundary tests listed for D1 in section 13, the detail-read reach walk among them; every existing test D1 moves (section 13, last table: 86 unit and 31 integration cases, and `test_jev_prereg.py` rewritten) | — | Registers no set; plans and asks nothing; the arming switch has no consumer |
| **D2 — findings routing** | `FindingTitleState`, `findings.owner` v1 and `findings.severity` v1, with goldens and released rows; their plans and the `findings.recorded` baseline; the `ASKABLE` entries; the planner rules and `findings_to_ask`/`get_finding_title`; `jev_chips` (`Chip`, `route_chip`, `severity_chip`, `duplicate_chips`); the harness's `finding_title` subject, `preview` and `suggestions` (findings half); the findings canary; the SDK case; the dark matrix gaining the findings area | D1 | The `findings` area is seeded off |
| **D3 — ops triage** | `jev_redact`, with its golden and corpus; `jev_chips.code_cause`, its shapes table and released hashes; the reconciliation, data-health and ingest chips; `JobErrorState`, `job_error_text` and `job_error_from_text`; `ops.job_error` v1 (provenance `system`, `internal_detail`) and its plan, with the keywords held to evidence; the `ASKABLE` entry with `address`; the planner rule and its reads; the harness's `job_error` subject, its dating over the population's rows and its labels read back through their state; `preview` and `suggestions` (jobs half); the ops canary; the SDK case; the dark matrix gaining the ops area and "ops on, detail off". Reviewed as this system's own text leaving it for the first time | D1 | The `ops` area and the detail switch are both seeded off |
| **D4 — the card check armed** | `jev_calibration.ARMABLE`, `Arming`, `arming` and `card_addition`; `jev_arming`; `repo.raise_card_finding` and `active_model_candidates`; `_plan_rejudges`, `cards_to_rejudge`, `rejudge_job_key`, the `rejudge` payload asked with no key, and `pending_asks` leaving re-judges out; the boundary move (open item 67); P1–P12; the arming line in `status` and `report`; the Lanes table's Guardrails and Findings rows rewritten; `guardrail.card`'s purpose | D1, D2, D3 | The arming switch is seeded off, and no usable evaluation can exist for a long time |

---

## 13. Binding test list

Every test below is added, or changed where the text says so. The tag gives
the PR. "Proved on synthetic trees" means each scan trips on sources that must
trip it, and stays quiet on sources that must not, as phase C's scans do.

### `tests/unit/test_jev_prereg.py`

| Test | PR | Proves |
|---|---|---|
| `TestThePlanVersions::test_v2_is_released_and_v1_kept` | D1 | `RELEASED_PLAN_HASHES` holds both versions; the golden is the newest |
| `_MOVED` gains `STATISTIC_FLOORS`, `MAX_LOOKS`, M2's and M5's rules (changed) | D1 | Each moves the hash |
| `TestTheStatisticFloors::test_every_floor_is_a_wilson_lower_bound_at_the_gate_level` | D1 | R1, read as the targets were |
| `TestTheTargets::test_a_set_plan_may_raise_a_floor_never_lower_it` (changed `_target_problems`) | D1 | An acting class means precision, otherwise accuracy, and never below the floor |
| `TestTheGateFamily::test_the_level_is_bonferroni_over_the_family_and_the_looks` | D1 | (1 − `GATE_CI`) × 20 × 4 ≤ 0.05, and `GATE_CI` = 0.999375 |
| `TestTheSplit::test_the_split_is_five_tenths` (literal copy updated) | D1 | M1 |
| `TestTheRegimePlan::test_golden_and_released`, `::test_the_global_plan_holds_no_regime`, `::test_the_sleeves_are_the_workers` (moved) | D1 | M4 |
| `TestTheSetPlans::test_released_rows` for `findings.owner`, `findings.severity` and `ops.job_error` | D2/D3 | The set plans are pre-registered |
| `TestTheFindingsBaseline::test_it_reads_the_recorded_value` | D2 | The `findings.recorded` rule is data in the plan |
| `TestTheOpsKeywords::test_held_to_literals_and_to_verdicts`, `::test_every_keyword_is_produced` (each keyword found in the redacted subject text of a message of the evidence corpus that `code_cause` leaves to Jev; revised: D-HMB-10), `::test_no_keyword_matches_a_job_kind` | D3 | The ops baseline is pinned by what it does, and every keyword can fire |
| `TestTheKeywordFallback::test_the_c_plans_are_unchanged` | D2 | The `fallback` argument moves no phase C hash |
| `TestTheGateFamily::test_the_gated_pairs_fit_the_family` (count 9) | D2/D3 | The family holds D's pairs |
| `TestTheGateFamily::test_looks_are_counted_as_the_family_is` (revised: D-HMB-06) | D1 | The plan names looks per set, version and question, the family's own identity (`_gated_family`), so no model restores a look |

### `tests/unit/test_jev_calibration.py`

| Test | PR | Proves |
|---|---|---|
| `TestUsable::test_each_reason_alone` gains `looks` and the M5 worst case; `::test_a_look_under_another_pin_is_counted` (revised: D-HMB-06) | D1 | M3 and M5 bind; four looks under one pin leave none for the next |
| `TestTheFlipLimitsReadTheWorstCase` | D1 | A re-ask that was not compared counts as a flip |
| `TestTheCardAddition` (P2) | D4 | Arming only adds |
| `TestArming` (P3), `TestOnlyOnePairIsArmable` | D4 | Every condition is required; `ARMABLE` is one pair |
| `TestTheCardVerdict` (P1, kept), `TestTheDocumentPath` (P10, kept) | — | Unchanged |

### `tests/unit/test_jev_eval.py`

| Test | PR | Proves |
|---|---|---|
| `TestLooks::test_a_held_out_look_must_be_recorded`, `::test_the_dev_split_never_records_and_reads_no_test_item`, `::test_split_has_no_default`, `::test_execute_refuses_a_dry_look_at_held_out_items` (the rule lives in `execute`, which `main` and the integration suite's `_run` both reach) | D1 | M3 at the command line |
| `TestTheFlipsCountThePopulation::test_a_pair_of_an_unlabelled_subject_counts` | D1 | M2 |
| `TestTheRegimeReport::test_agreement_is_scored_under_the_regime_plan` | D1 | M4 |
| `TestTheNewSubjects::test_question_problem_admits_finding_title_and_job_error`, `::test_dates_texts_and_populations` | D2/D3 | The harness can measure the new sets |
| `TestTheRecordedBaseline::test_owner_and_severity_compare_with_raised_by_and_severity` | D2 | D4 in section 0 |
| `TestTheExportStaysBlind::test_no_raiser_severity_status_or_raw_error_is_exported` | D2/D3 | Blind labels |
| `TestPreview::test_it_prints_exactly_what_would_leave` (for ops, the switches it names include the detail switch), `TestSuggestions::test_ids_labels_and_numbers_only`, `::test_no_answer_no_probability_no_chip_and_no_jev_ref` (revised: D-HMB-04) | D2/D3 | The read surfaces, and that `suggestions` shows no answer |
| `TestTheJobErrorLabels::test_a_label_is_checked_through_the_state_its_text_names`, `::test_a_text_naming_another_state_or_none_is_refused`, `::test_an_exported_file_imports_unchanged` (revised: D-HMB-07) | D3 | Ops labels can be imported, and only as the state they name |
| `TestTheOpsDates::test_an_item_is_dated_over_the_population_rows` (an occurrence before `MODEL_FIRST_OBSERVED` leaves the date where the population puts it; revised: D-HMB-08) | D3 | One recurring error does not make every ops evaluation an upper bound |
| `TestTheArmingLine::test_status_says_why_the_card_check_is_not_armed` | D4 | The operator sees the reasons |

### `tests/unit/test_jev_questions.py`

| Test | PR | Proves |
|---|---|---|
| `TestStateAddressedSubjects::test_a_job_error_subject_must_be_its_state_hash` (with `test_jev_lane.py`), `::test_a_model_is_not_both_text_and_state_addressed`, `::test_a_state_addressed_set_records_its_writers_provenance` (revised: D-SAFE-5) | D1 | M17, M26 |
| `TestTheTextFreeLanes::test_an_ops_set_carrying_text_is_refused` (str, title, a dataclass, a validator, a serializer), `::test_an_ops_set_without_internal_detail_is_refused`, `::test_dump_state_checks_an_ops_set_whatever_its_internal_detail` (a test-only set declaring `internal_detail` whose dump would carry an undeclared string is refused on its first dump; revised: D-SAFE-1) | D1 | Ops states are enumerated, declared as detail, and still read on every dump |
| The registry pin (eight sets after D2, nine after D3, from six at `23dee2b`; revised: D-HMB-13); goldens; released pack and question rows | D2/D3 | The words are frozen |
| `test_job_error_text_round_trips` (over the redactor's fuzz: `job_error_from_text(job_error_text(s)) == s`, and a text that names no state gives `None`) | D3 | The export's text names exactly one subject |
| `test_the_owning_role_options_are_the_twelve_roles`, `test_the_severity_options_are_the_findings_severities` | D2 | The options are the panel's vocabulary, in order |
| `test_the_cause_options_are_jev_chips_causes` | D3 | One vocabulary for code and Jev |
| `test_the_title_cap_is_proposed_findings` | D2 | 200 = `roles.ProposedFinding.title`'s `max_length` |
| `test_the_skeleton_bound_and_legend_are_rendered_from_jev_redact` (executed with each moved) | D3 | The pack hash moves with the redactor's constants |
| `TestEverySetIsWrittenPlainly` (automatic over the registry) | D2/D3 | The wording rules |

### `tests/unit/test_jev_lane.py`

| Test | PR | Proves |
|---|---|---|
| `TestSubjectsAreContentAddressed::test_a_state_addressed_subject_is_refused_before_any_switch` | D1 | The road checks a `job_error` address first |
| `TestStandingRefusals::test_a_skeleton_is_held_by_no_content_block` | D3 | An enumerated state is held by nothing (open item 36) |
| `TestTheDetailSwitch::test_ops_asks_nothing_with_the_detail_switch_off` (programme, Jev and ops on, detail off: `disabled`, no row, no call; revised: D-SAFE-1) | D3 | The road holds a skeleton to the detail switch |

### `tests/unit/test_jev_jobs.py`

| Test | PR | Proves |
|---|---|---|
| `TestASKABLE::test_it_covers_exactly_the_registered_text_and_skeleton_sets` | D2/D3 | The askable sets are known |
| `TestTheFindingAsk::test_only_a_model_written_title_within_the_cap`, `::test_the_cap_refuses_not_pydantic`, `::test_the_state_is_the_title_alone` | D2 | M10, M11 |
| `TestTheJobErrorAsk::test_each_admission_refuses_alone` (status, kind, `finished_at`, code-triaged, too few tokens), `::test_the_address_is_checked_after_build`, `::test_errors_name_the_job_and_quote_nothing` | D3 | M8, M9 |
| `TestTheCardCheckChangesNothing` becomes `TestWhatAnAnswerMayChange`: the same walk, whose only writer of `findings`, `candidates` or `hypotheses` is `repo.raise_card_finding`, reached only from `jev_arming.card_follow_up`, proved on synthetic trees | D4 (D2/D3 keep it at none) | P6 |
| `TestTheTitleProjection::test_the_title_sets_load_by_column_list` (`jev_repo.get_hypothesis_title`, never `repo.get_hypothesis`; revised: D-SAFE-2) | D1 | No card reaches the Jev side |
| `TestARejudge::test_it_is_asked_with_no_key`, `::test_no_canonical_answer_under_the_pin_completes_not_on_record`, `::test_the_marker_is_the_cards_alone_and_exactly_true` (revised: D-SAFE-4, D-HMB-05) | D4 | A re-judge can only replay |

### `tests/unit/test_jev_arming.py` (new, D4)

| Test | Proves |
|---|---|
| `TestTheFollowUpOracle` (P4) | Exactly the findings `card_addition` allows, and no other statement |
| `TestOnlyOkActs`, `TestAReaskNeverActs` (P7) | No action on a status other than `ok`, nor on a probe |
| `TestReadAtTheMoment` (P8, unit half) | No cached calibration |
| `TestTheFindingsWords` | Title, detail and remediation from ids and numbers only; severity a literal |
| `TestACodeRejectionRaisesNothing` | Legacy titles are left to the operator |

### `tests/unit/test_jev_redact.py` (new, D3) and `tests/unit/test_jev_chips.py` (new, D2/D3)

Every property in section 4.6 is a test in these files. In addition:

| Test | PR | Proves |
|---|---|---|
| `test_the_severity_chip_only_escalates` | D2 | M5 |
| `test_the_route_chip_never_argues_against_a_veto` (property over random registers, mirroring the severity chip's: on every finding that blocks, `route_chip` is `None` or names a role in `VETO_ROLES`; on one that blocks nothing it shows any answer; revised: D-SAFE-3) | D2 | M24 |
| `test_closing_what_duplicate_chips_mark_unblocks_nothing` (property over random registers) | D2 | M4 |
| `test_a_chip_is_labels_and_numbers` | D2 | No text in a chip |
| `test_code_cause_is_none_only_for_triaged_residue` | D3 | Only the residue reaches Jev |
| `test_the_stale_rule_is_the_reports` | D3 | One threshold for staleness |
| `test_reconciliation_and_data_health_chips_cover_every_shape` | D3 | Every structured case has a chip |

### `tests/unit/test_jev_plan.py`

| Test | PR | Proves |
|---|---|---|
| `TestTheFindingsRules`, `TestTheOpsRule` (shares, caps, keys, holds, newest-first, one job per address) | D2/D3 | The new rules plan as specified |
| `TestTheDetailSwitchGatesPlanning` (a test-only set in D1; `ops.job_error` from D3) | D1, D3 | A set declaring `internal_detail` is planned only while the detail switch is on |
| `TestRejudges` (P9), with `::test_rejudges_are_planned_under_holds_and_take_no_share` and `::test_a_moved_pin_plans_no_call` | D4 | Re-judges are replays |
| `TestTheSwitchMatrix`: programme, Jev, findings, ops, guardrails, arm and detail × key, all 256 cases; each rule planned exactly when its conjunction holds; the arming switch alone plans nothing; ops on and detail off plans nothing (revised: D-SAFE-1) | D4 (built up from D2) | The planner obeys every switch |
| `test_the_planner_logs_no_text` (captured at DEBUG) | D3 | No raw error in the logs |

### `tests/unit/test_import_boundaries.py`

| Test | PR | Proves |
|---|---|---|
| `RUNNER_ONLY` += `jev_arming`; `test_safety_rule_5_names_every_runner_only_module` | D4 | The API cannot import the arming module |
| `PURE_PROGRAMME_MODULES` += `jev_redact`, `jev_chips`; `test_the_pure_modules_load_nothing` | D2/D3 | Both load nothing |
| `test_only_the_harness_and_the_arming_import_the_calibration`, `test_what_acts_reaches_the_calibration_only_through_the_arming`, `test_only_jev_jobs_imports_the_arming` (every spelling), `test_nothing_else_that_acts_loads_the_calibration` (replaces `test_nothing_that_acts_loads_the_calibration`) | D4 | Open item 67 |
| `test_the_arming_reaches_no_road_and_no_key` (`ARMING_MUST_NOT_REACH`) | D4 | The arming module asks nothing |
| `PLANNER_MUST_NOT_REACH` += `jev_arming`, `jev_calibration`; `HARNESS_MUST_NOT_REACH` += `jev_arming` | D4 | Neither can arm or act |
| `test_calibration_functions_are_called_where_allowed` (AST, section 9.2) | D4 | The verdicts are read in one place |
| `test_the_api_does_not_import_the_programme_runner` and `test_the_programme_modules_the_api_imports_hold_no_client` (both existing; both read `RUNNER_ONLY`, so both hold with `jev_arming` in it), each proved on a synthetic tree in which a module of `src/api` holds `from src.programme import jev_arming` (revised: D-SAFE-7; the draft named `test_the_api_imports_no_runner`, which does not exist) | D4 | Safety rule 5's list |

### `tests/unit/test_jev_table_boundaries.py`

| Test | PR | Proves |
|---|---|---|
| `TestWhatJevCodeCanWrite::test_exactly_these_writers` | D1, then D4 adds one | From every `JEV_HANDLERS` handler, every `ASKABLE` follow-up and `jev_plan.plan`, the reachable `(table, writer)` pairs are exactly the allow-list. `jev_requests`/`jev_answers` ← `record_exchange`; `jev_signals` ← `record_signal`; `web_documents` ← `insert_documents`, `quarantine_content`; `jev_labels` ← `record_label_once`; `jobs` ← `enqueue`; in D4, `findings` ← `raise_card_finding`. The message names `findings`, `hypotheses`, `candidates`, `programme_decisions` and `system_flags`. Proved on synthetic trees |
| `test_every_update_of_findings_sets_closure_columns_only` | D1 | M1 |
| `test_every_insert_into_findings_names_its_origin`, `test_raise_finding_takes_origin_keyword_only_with_no_default`, `test_its_callers_pass_literals` (`'model'` from the tick, `'operator'` from the API), `test_only_raise_card_finding_writes_jev_findings`, `test_its_severity_and_raiser_are_literals` | D1/D4 | M11, M22 |
| `test_the_jev_side_never_reads_detail` (revised: D-SAFE-2, D-HMB-16): a reach walk with `test_jev_jobs.py`'s `_Reach`, from every `JEV_HANDLERS` handler, every `ASKABLE` `load`, `admit`, `build` and `follow_up`, `jev_plan.plan`, every `jev_eval` command and, from D4, `jev_arming`. It refuses any reachable function whose SQL reads `*` from `hypotheses`, `findings` or `role_assessments`, or names a detail column of them (section 9.2) in a SELECT or a RETURNING. Proved on synthetic trees that call `repo.get_hypothesis` and `repo.list_findings` | D1 | M10 |
| `test_a_job_error_is_used_only_by_the_redactor_and_code_cause` (AST over `jev_jobs`, `jev_plan`, `jev_eval`) | D3 | M8 |
| `test_nothing_in_the_programme_writes_a_switch` (the shared write scanner over `system_flags`; no reference to `set_flag`, `engage_kill_switch` or `release_kill_switch`) | D1 | M7 |
| `test_the_gates_and_the_programmes_rows_name_no_jev_table` (existing; holds with `raise_card_finding`) | D4 | Unchanged |

### `tests/unit/test_job_ownership.py`

| Test | PR | Proves |
|---|---|---|
| `test_nothing_in_the_programme_changes_a_job_it_did_not_claim` (the only state-changing `job_repo` calls in `src/programme` are `main`'s claim/complete/fail/lease, and `jev_plan`'s and `tick`'s `enqueue`; never `requeue_expired`) | D1 | M6 |
| `test_triaged_kinds_are_the_workers_and_no_others` (⊆ `HANDLERS`; disjoint from the venue kinds, `shadow_decision` and `JEV_HANDLERS`) | D3 | M9, M18 |
| `TestEveryJevHandlerMakesAtMostOneCall` covers the new `ASKABLE` entries through every road outcome, reads `jev_arming` for a call (none), and counts a re-judge's attempt at zero calls under every outcome, a moved pin included | D2–D4 | One call an attempt |
| `TestEveryEnqueuedKindHasExactlyOneOwner` (unchanged, still passes) | — | No new kind |

### Other unit suites

| Test | PR | Proves |
|---|---|---|
| `test_jev_catalogue.py::TestTheShares` (new values; minimum still 10), `::test_the_settings_message_names_the_smallest_shares`, `::test_subject_types`, `TestTheVocabulary::test_the_provenances` (with `system`) | D1–D3 | The budget split and the vocabulary |
| `test_jev_flags.py::TestTheReadersReadTheSeededKeys` (0012 and 0015), `::test_the_arming_switch_is_on_only_for_json_true` | D1 | The switch fails closed |
| `test_jev_forward.py::test_the_result_names_both_plans` | D1 | M4 |
| `test_programme_gates.py::test_veto_roles_are_role_keys` (⊆ `ROLES_BY_KEY`, no `:`), `::test_a_jev_finding_never_blocks` (P11) | D1/D4 | M3 |
| `test_programme_convene.py::test_a_jev_finding_never_reaches_the_brief`, `::test_the_tick_raises_findings_as_model` (new; reads `origin` from the existing fakes, which take `**kwargs` and need no change) | D1/D4 | M15, M22 |
| `test_report_data_health.py` (unchanged) | — | — |

### Integration (PostgreSQL)

| Test | PR | Proves |
|---|---|---|
| `tests/integration/test_phase_d_schema.py`: `TestTheMigration` (0015 over 0014 holding findings and evaluations, or failing whole); `TestEveryRuleBites` (each origin rule, Jev rule, trigger and flip rule broken alone and admitted with that rule dropped); `::test_every_rule_0015_adds_has_a_case`; `TestOriginIsKnownFromNowOn` (an insert naming no origin fails on `NOT NULL`, not on a trigger's message); `TestWhatWasRaisedStaysRaised` (each column but the closure's refused; a closure admitted; a reopen refused; DELETE, TRUNCATE and a candidate's cascading delete each refused, the finding read back after each; revised: D-SAFE-6); `TestAJevFindingRestsOnItsAnswer` (a missing request, a status but `ok`, the probe lane, another set, a raiser that is not `jev:` and the set, and no valid `true`, each refused alone; revised: D-HMB-11); `TestTheJevRefs` (the ref expression, `repo.JEV_REF_SQL`, evaluated for 1, 9,999, 10,000, 10,001 and 123,456: never cut; revised: D-HMB-12); `TestTheProvenances` (`system` admitted on `jev_requests`, refused by `jev_signals_provenance_check`, and a signal on a `system` request refused; revised: D-SAFE-5); `TestTheArmingSwitchIsSeededOff` (read through the shipped reader); `TestFlipCountsAboveN` | D1 | Section 7 |
| `test_jev_findings.py` (new): the findings canary (markers in `detail_md`, `remediation`, `close_note`, `role_assessments.summary` and in operator and `'unknown'` titles are found only in their own columns; a model title only in `findings.title` and `jev_requests.state`; no log at DEBUG; no job payload, result or error); `TestOnlyModelFindingsAreAsked`; `TestAFindingIsUnchangedByEveryOutcome`; `TestAskedOnceAndReplayed` | D2 | M10, M11 |
| `test_jev_ops.py` (new): the ops canary (markers in every placeholder class and secrets of every shape are found only in `jobs.error`, read from `information_schema`, a column of an unsorted type failing it); `jev_requests.state` holds `TOKENS` only; venue, shadow and programme kinds, code-triaged errors and `NULL finished_at` jobs are never asked; each triaged job's row is byte-identical after every outcome | D3 | M6, M8, M9 |
| `test_jev_arming.py` (new): P5, P8 (integration half), P11 (gates identical on real rows), P12, the re-judge end to end; `TestTheHarnessAgreesWithTheArming` (`status`'s line equals `armed_calibration` on the same rows) | D4 | Section 10 |
| `test_jev_dark.py` gains the findings and ops areas, the detail switch and the arming switch: seeded, nothing; each alone, nothing; the documented conjunctions plan exactly their asks; **ops on with the detail switch off, nothing planned and nothing sent** (revised: D-SAFE-1); arming alone, nothing | D2–D4 | Dark |
| `test_jev_evaluations.py` gains an end-to-end evaluation of each new set from synthetic labels (each row equal to its recomputation), and one under M2's population flips | D2/D3 | C9 measures them |
| `test_jev_harness.py::TestTheForwardReportUnderTheRegimePlan` | D1 | M4 |
| `test_jev_repo.py`: each new read held to what it returns, every filter by a case only it refuses | D2–D4 | The reads |
| `TestPreviewIsThePlanners` (preview's subjects and states equal to the planner's and the handler's on the same rows) | D2/D3 | The operator sees what would leave |

### SDK (`tests/sdk`, `-m sdk`)

| Test | PR | Proves |
|---|---|---|
| `test_jev_findings_ops_over_http.py`: one finding title and one skeleton through the planner, handler, lane, real client and SDK to the fake server; each request's state exactly `{"title": …}` and `{"error": […], "job_kind": …}`; the skeleton's row recorded under provenance `system`, and sent only with the detail switch on; a second ask makes no HTTP request | D2/D3 | What leaves is what was built |

### Existing tests the build must change (revised: D-HMB-01)

The first draft listed these by reading, and missed most of them. They are now
found mechanically. D1's skeleton was applied to a scratch copy of `23dee2b`:

- the constants (`PLAN_VERSION` 2, `DEV_SPLIT_TENTHS` 5, `GATE_CI` 0.999375,
  `GATE_FAMILY` 20, `MAX_LOOKS`, `STATISTIC_FLOORS` in place of
  `LANE_TARGETS`, the regime plan apart);
- M2's population and M5's worst case;
- the `--split` rules;
- the shares and the settings message, and `system`;
- `flags.jev_arm_card_check`;
- `raise_finding`'s keyword-only `origin` at its two callers;
- the title sets' read by column list;
- the detail-switch rule in the planner;
- migration 0015 as drafted.

The unit and integration suites were then run on that copy and on an
unmodified copy. The unmodified copy passed both: 8,595 passed and 3 skipped
in the unit suite, and 1,258 passed and 1 skipped in the integration suite.
Every failure on the D1 copy is below. Each lands in D1, or D1's CI fails. The SDK suite was not run there; by
reading, it pins the plan only through `GOLDEN_PLAN_HASH` by name
(`test_jev_research_over_http.py`), which moves with the re-pin.

**Unit: 86 cases in eight files, and `test_jev_prereg.py` whole.**

| Test | Cases | What changes, and why |
|---|---|---|
| `tests/unit/test_jev_prereg.py` | the module | Collection fails at module level: `_MOVED` reads `jev_prereg.LANE_TARGETS`. The module is rewritten for v2 (section 13's first table), version 1's hash kept in `RELEASED_PLAN_HASHES` |
| `tests/unit/test_jev_calibration.py::TestUsable` | 26 | `_usable_row` no longer passes under v2. Its keyword comparison, 60 against 30, fails the exact sign test at 1/1600, and M5 needs the three `*_not_compared` counts it lacks. Every case built from it moves: `test_an_evaluation_that_meets_every_condition_is_usable`, `test_every_reason_has_a_case`, `test_each_reason_alone_makes_it_unusable` for all 14 reasons, `test_what_counts_as_a_used_test_set`, `test_an_older_row_of_its_key_does_not_supersede_it`, the five `test_the_held_out_bound_is_the_searchs_own_rule` cases, `test_a_baseline_is_beaten_by_the_exact_sign_test_alone`, `test_no_pin_and_no_plan_match_nothing` and `test_a_row_never_recorded_is_never_the_newest`. The row is rebuilt to pass v2 |
| `tests/unit/test_jev_catalogue.py::TestTheSettings::test_a_budget_that_leaves_a_lane_no_call_is_refused` | 9 (budgets 1 to 9) | The refusal names the lanes with the smallest share, no longer "the probe lane's" |
| `tests/unit/test_jev_catalogue.py::TestTheVocabulary` | 5 | `test_the_provenances` (`system`), `test_the_slices_are_the_designed_ones`, and `test_a_lanes_share_is_rounded_down` at 500 for guardrail, research (175 becomes 125) and ops (0 becomes 50) |
| `tests/unit/test_jev_eval.py` | 11 | `TestTheThreshold::test_a_guardrail_is_measured_by_the_precision_of_true` and the two `TestAThresholdTheTestSplitRefutes::test_usable_only_where_the_test_split_bears_it_out` cases: the fixtures chose a threshold at 0.995 and three tenths. Four `TestWhatTheTextSays::test_beats_only_by_the_exact_sign_test_at_the_gate` cases: the text names the level, and the counts that beat move from 8 to 11. `TestTheFlips::test_a_pair_of_an_unscored_item_is_not_counted`: M2 counts it, so the test inverts. `TestTheFlips::test_the_window_is_read_as_the_decimals_written`: its threshold is no longer chosen under the new split and level. `TestTheCommitARecordNames::test_record_refuses_before_reading_the_ledger` and `TestTheCommandsThatWrite::test_three_commands_write_and_the_rest_only_read`: `--split` is now required |
| `tests/unit/test_jev_stats.py` | 2 | `TestTheThreshold::test_an_acting_class_is_measured_by_its_precision` and `TestTheSignTest::test_eight_of_eight_beats_at_the_gate_and_seven_of_eight_does_not` read `jev_prereg.GATE_CI`; at 0.999375 eight of eight no longer beats. The draft's "the `jev_stats` tests pass their level as an argument" was false, and is struck |
| `tests/unit/test_jev_flags.py::TestTheReadersReadTheSeededKeys` | 2 | `test_every_key_read_is_one_migration_0012_seeds` reads the seeds of 0012 and 0015 (renamed to match), and `test_the_readers_ask_for_those_keys_and_no_others` calls `flags.jev_arm_card_check` |
| `tests/unit/test_jev_forward.py` | 3 | `test_the_result_holds_no_state_and_no_price`, `TestASessionIsRecordedOnce::test_a_session_already_recorded_asks_nothing` and `TestWhatTheAskCameTo::test_an_answer_is_recorded_and_the_job_completes`: the result gains `regime_plan_version` and `regime_plan_hash` (M4); `PLAN_IN_FORCE` with them. Still labels, counts, ids and plans |
| `tests/unit/test_jev_jobs.py` | 25 | The title sets' `load` reads `jev_repo.get_hypothesis_title`, and the fakes stub `repo.get_hypothesis`: `TestTheAsk` (7) and `TestWhatIsNotAsked` (17) move to the projection. `TestTheCardCheckChangesNothing::test_the_scan_reaches_the_road_and_the_ledger` names `repo.get_hypothesis` in its reached set, and names `jev_repo.get_hypothesis_title` instead |
| `tests/unit/test_jev_plan.py::TestTheAsks` | 3 | `test_never_beyond_the_lanes_share`, `test_one_call_left_plans_one_ask` and `test_finished_asks_do_not_count_against_the_lane` hold the guardrail share at a budget of 10 to 3; at 25% it is 2 |

The two hold tests in `TestTheAsks`, `test_nothing_that_calls_is_asked_while_an_authentication_failure_holds` and `test_a_refused_screen_still_plans_its_repairs`, failed on the scratch copy only while it carried the first draft's general hold fix. That fix is withdrawn (section 5.2), and both pass unchanged.

**Integration: 31 cases in four files.**

| Test | Cases | What changes, and why |
|---|---|---|
| `tests/integration/test_jev_evaluations.py::TestEveryRuleBites` | 18 | Of the eleven flip cases of `BROKEN`, read by `test_a_row_that_breaks_a_rule_is_refused`, the six "below 0" cases (`flip_rate_n`, `flip_rate_low_margin_n`, `flip_rate_near_threshold_n` and the three `*_not_compared`) now expect `jev_evaluations_flip_counts_are_counts`. The five others, the three "above n" cases and the two "more re-asks … than items" cases, leave `BROKEN`: under M2 they are lawful, and `test_phase_d_schema.py::TestFlipCountsAboveN` admits them. The six `test_each_case_breaks_its_rule_alone` cases move with them. `test_every_rule_0014_adds_has_a_case` reads every CHECK on a fully migrated database, so it holds 0015's new rule to a case |
| `tests/integration/test_jev_evaluations.py::TestTheSchemaAdmitsWhatTheHarnessComputes::test_a_chosen_threshold[precision]` | 1 | Under v2 its development items choose no precision threshold (`none_found`). The fixture grows to choose one |
| `tests/integration/test_jev_evaluations.py::TestTheLedgerTheJobsWrote::test_the_test_split_leaves_the_development_item_out` | 1 | At five tenths an item the fixture placed in the test split lands in the development split. The fixture's subjects are re-chosen by `split_of` |
| `tests/integration/test_jev_evaluations.py::TestTheCommandsOnPostgres::test_a_reading_command_runs_where_postgres_refuses_a_write[evaluate]` | 1 | `READERS`' `evaluate` names no `--split`, and becomes `--split dev` |
| `tests/integration/test_jev_evaluations.py::TestTheCommandsOnPostgres::test_a_dry_run_records_nothing` | 1 | It runs `--split all` without `--record` through `execute`. Under M3, enforced in `execute`, that is refused, and the test becomes a `--split dev` dry run. On the scratch copy the rule sat in `main`, which `execute` bypasses, so this case passed there. Enforced where section 3.2 puts it, it moves |
| `tests/integration/test_jev_research.py::TestTheTitleAsksChangeNothing::test_every_outcome_leaves_the_programmes_tables_alone` | 5 | Its `repo.raise_finding(conn, …)` names no `origin`, which is keyword-only with no default. It passes `origin="model"` |
| `tests/integration/test_jev_schema.py::TestTheSwitchesAreSeededOff::test_every_switch_is_seeded_as_the_design_says` | 1 | `SEEDED_SWITCHES` gains `"jev_arm_card_check": False` |
| `tests/integration/test_jev_schema.py::TestTheVocabulariesAgree::test_the_schema_holds_the_lanes_and_provenances_it_was_designed_with` | 1 | `jev_requests_provenance_check` holds `system` and `jev_signals_provenance_check` does not, by design (section 7). The test reads the two vocabularies apart |
| `tests/integration/test_programme_panel_atomicity.py::test_a_finding_that_fails_to_write_takes_its_view_with_it` | 2 | `_taken_ref`'s direct `INSERT INTO findings` names `origin` (`'model'`, the runner it stands in for), or it fails on `NOT NULL` before any ref is taken; the test must still fail on the ref's unique violation, which is what it is for. Its clean-up, on its own connection, deletes its candidate (cascading to the findings) and its taken finding, which 0015 refuses. It retires the candidate instead (`status = 'retired'`, out of every active read) and leaves the finding, as the Jev ledger's tests leave their rows under unique refs |

**Unaffected, though they look as if they might be.** All of these passed on
the D1 copy:

- **The upgrade tests.** `test_jev_evaluations.py::TestTheMigration` and
  `test_jev_schema.py`'s upgrade cases build directories truncated at 0013 or
  0014 (`_migrations_up_to`), so 0015's presence moves nothing.
- **`tests/unit/test_jev_jobs.py`'s synthetic `raise_finding`.** It is a source
  string in a scan's tree, never executed against a database.
- **`gate_ci_level = 0.995` in `test_jev_evaluations.py`'s `_measured()` row.**
  0014 checks only that the level is between 0 and 1.
- **`tests/unit/test_programme_convene.py`'s `raise_finding` fakes.** They take
  `**kwargs`, so they accept `origin` unchanged.
- **`tests/integration/test_programme.py`'s direct closures.** Each is still
  refused, by 0008's CHECK as before.

---

## 14. CLAUDE.md rows to add

### Safety rule 5

The runner list gains `jev_arming`:

> … may not import its runner (`tick`, `author`, `client`, `main`, `panel`,
> `jev_client`, `jev_lane`, `jev_forward`, `jev_jobs`, `jev_plan`, `jev_eval`,
> `jev_arming`, `web_fetch` and `web_ingest`) …

The rule's substance and the amendment's status are unchanged.

### Architecture table (`src/programme` row)

The row gains:

- `jev_redact`: the job-error skeleton, pure;
- `jev_chips`: code triage and the chips, pure, API-importable;
- `jev_arming`: the one acting reader of a calibration, runner-only.

### Database

Migration 0015 gives `findings` its `origin`: `'unknown'` before 0015, then
`'model'`, `'operator'` or `'jev'`. It adds:

- `source_request_id`, and a trigger holding a Jev finding to a valid `true`
  of a canonical card request;
- the rules that keep a Jev finding non-blocking;
- a trigger keeping what was raised, which refuses every change but the
  closure's, and a reopen;
- the refusal of DELETE and TRUNCATE on `findings`;
- the arming switch;
- provenance `system` on `jev_requests` alone, so `jev_signals` still refuses
  it;
- 0014's flip counts freed from `n`.

### Commands

`python -m src.programme.jev_eval preview --set S` and `… suggestions`
(statuses, never an answer). `evaluate --split dev|test|all`, where `--split`
has no default and a look at held-out items needs `--record`.

### Known limitations

Phase D is built dark. Findings routing and ops triage are suggestion-only.
Ops skeletons go only while the detail switch is on. `findings.owner` is not
expected to beat the raiser it is measured against. The card check is armed by
a switch and a usable evaluation, and will not be armed for years.

### Structural guarantees

| Guarantee | Mechanism |
|---|---|
| **The analysis was versioned before the answers, and every look through the harness's commands is recorded and counted** (revised: D-HMB-14) | Plan v2 was released while the ledger was empty (D1): floors by statistic, a family of 20, a 50/50 split, flips over the population, re-asks not compared counted against the limits, the regime's plan kept apart. `jev_eval.execute` refuses a dry look at the test split; `usable` refuses a fifth look of a set, version and question, under any model; `GATE_CI` is spent across family and looks (0.999375). The harness binds only its own commands: `jev_eval.evaluate()`, the function, computes a test-split evaluation and records nothing, and anyone who reads the test split by hand is outside the protocol (open item 79). `test_jev_prereg.py::TestTheGateFamily`, `test_jev_eval.py::TestLooks`, `test_jev_calibration.py::TestUsable` |
| **A finding says who wrote it, and what was raised stays raised** | 0015: `origin` (`'unknown'` only before it, by trigger); `findings_keep_what_was_raised`, under which only the closure's columns change, a closed finding is never reopened, and 0008 still needs an operator to close; `trg_findings_no_delete` and `trg_findings_no_truncate`, so no writer removes a finding, a blocking veto included, and a candidate's delete fails with its findings; and every insert names its writer (`raise_finding`'s keyword-only `origin`). `tests/integration/test_phase_d_schema.py::TestWhatWasRaisedStaysRaised`, `test_jev_table_boundaries.py::test_every_insert_into_findings_names_its_origin` |
| **Jev's code writes exactly what it is allowed to** | A walk from every Jev handler, follow-up and the planner finds exactly the allow-listed `(table, writer)` pairs, and no write of `system_flags` or of a job the programme did not claim. `test_jev_table_boundaries.py::TestWhatJevCodeCanWrite`, `::test_nothing_in_the_programme_writes_a_switch`, `test_job_ownership.py::test_nothing_in_the_programme_changes_a_job_it_did_not_claim` |
| **Only a model-written finding's title is sent, and the Jev side reads no detail** (revised: D-SAFE-2) | `FindingTitleState` holds a title alone; the read and the admission take `origin = 'model'`; the title sets read hypotheses and findings by column list (`jev_repo.get_finding_title`, `get_hypothesis_title`), never through `repo`'s `SELECT *` readers; a reach walk from every Jev root refuses any reachable SQL that reads `*` from `hypotheses`, `findings` or `role_assessments`, or names a detail column of them. `tests/integration/test_jev_findings.py`, `test_jev_table_boundaries.py::test_the_jev_side_never_reads_detail` |
| **A suggestion changes nothing, and never lowers anything** | Findings and ops answers have no follow-up. Chips are pure, stored nowhere and shown in phase E. The severity chip only escalates; on a finding that blocks, the owner chip names only a role that holds a veto; a duplicate chip points only to an older finding that blocks at least as much. `test_jev_chips.py`, `test_jev_jobs.py::TestWhatAnAnswerMayChange` |
| **Job errors reach Jev only as skeletons of a closed vocabulary, only while the detail switch is on, and never as `internal`** (revised: D-SAFE-1, D-SAFE-5) | `jev_redact.skeleton` is an allow-list with pinned rules; `JobErrorState` is a `Literal` of its tokens; `ops.job_error` declares `internal_detail`, which `TEXT_FREE_LANES` requires, so the road and the planner read `jev_send_internal_detail`; `dump_state` still reads what every ops ask would send; the vocabulary, part by part, provably cannot satisfy the code screen's instruction rules, read rule by rule; a skeleton is recorded as `system`, which `jev_signals` refuses. `tests/unit/test_jev_redact.py`, `tests/unit/test_jev_questions.py::TestTheTextFreeLanes`, `tests/integration/test_jev_ops.py`, `test_phase_d_schema.py::TestTheProvenances` |
| **Code triages first, and venue, programme and account data are never sent** | `jev_chips.code_cause` places every known shape (held to the raise sites); only `TRIAGED_KINDS`' residue is asked; reconciliation and data-health chips are code's alone. `test_jev_chips.py`, `test_job_ownership.py::test_triaged_kinds_are_the_workers_and_no_others` |
| **An armed card check only adds a finding that cannot block** | `jev_calibration.card_addition`, through `jev_arming` alone, behind `jev_arm_card_check` and the newest person-labelled usable evaluation (`ARMABLE` is one pair). One `jev:guardrail.card` finding at `medium` per active candidate, held non-blocking by CHECK and to a valid `true` of a canonical card request by trigger; `J-` refs, never cut. A re-judge is asked with no key, so it can only replay. `test_jev_calibration.py::TestTheCardAddition`, `::TestArming`, `tests/unit/test_jev_arming.py`, `tests/integration/test_jev_arming.py`, `test_jev_plan.py::TestRejudges` |
| **The calibration crosses into one acting module** | `jev_calibration`'s importers are `jev_eval` and `jev_arming`; every path from `jev_jobs` and `main` runs through `jev_arming`; the planner, the lane, the forward clock, the web modules and the model runners reach it not at all (open item 67). `test_import_boundaries.py::test_what_acts_reaches_the_calibration_only_through_the_arming` |

### docs/08

docs/08 gains:

- a "Phase D, as built" subsection per PR;
- the Lanes rows for Findings routing, Ops triage and Guardrails rewritten as
  in sections 1, 6 and 10;
- the arming switch in "Switches, all fail closed";
- 0015 in the schema section;
- the Delivery row;
- fact 7's defaults and the Inputs-needed defaults restated with ops: a
  skeleton is this system's own text and goes only while the detail switch is
  on (unless the owner answers section 11, Q15 otherwise, in which case those
  defaults are amended before D3 merges);
- `system` in the provenance vocabulary: computed in code from this system's
  records, which can quote an outsider; never `internal`, and refused by
  `jev_signals`;
- open items 71 to 82:
  - 71: the Jev duplicate question is deferred.
  - 72: card labels are exposed after the first armed finding.
  - 73: the worker records `str(exc)` without its class, so no ops keyword
    reads a class name.
  - 74: the daily report's blocking count is not veto-aware.
  - 75 (revised: D-HMB-04; the draft's 75, re-judges counted against the
    guardrail share, is closed by leaving re-judges out of `pending_asks`):
    findings labels can echo the register. The findings page shows the raiser
    and the severity beside every title, the values the recorded baseline
    reads, and nothing records which labeller has read it. No findings set
    arms in D.
  - 76: pre-0015 findings read `'unknown'` and are never asked.
  - 77: the vocabulary bounds what a skeleton can say; a change is a new set
    version.
  - 78 (revised: D-HMB-06): looks are counted per set, version and question
    across every model, so after four looks a set's question cannot arm under
    any pin until a new set version.
  - 79: the harness enforces only its own commands; `jev_eval.evaluate()`
    and reading the test split by hand are outside the protocol.
  - 80: near-threshold flips above a threshold of 0.30 rest on the uniform
    stratum alone (measurement Q12), and a margin-banded stratum is a later
    plan's.
  - 81 (revised: D-HMB-08): ops items are dated over the rows their population
    reads, so an occurrence of a skeleton before the pin's first observation
    does not mark it possibly in training. For private records the date
    carries no information about training, and a skeleton that is also a
    public library message is in training whatever its date.
  - 82 (revised: D-SAFE-1): the detail switch is one switch for all of this
    system's detail. Switched on for ops, it lets any later set declaring
    `internal_detail` send too, once that set's own area is on.

---

## 15. Critiques declined

Every one of the twenty-three issues was checked against the code and docs/08
at `23dee2b`, and every one is real. **None is declined outright.** Where an
issue offered more than one fix, this design took one, and the alternatives it
did not take are listed below with the reason. The table says where each issue
is resolved.

### 15.1 Where each issue is resolved

| Id | Resolved by | Sections |
|---|---|---|
| D-SAFE-1 | `ops.job_error` registered with `internal_detail`; `TEXT_FREE_LANES` requires it; `dump_state` checks every ops set's output whatever its `internal_detail`; the planner's detail rule live for ops; the "ops on, detail off" dark case; owner question Q15; open item 82 | 0, 1, 2.1, 2.4, 2.5, 5.2, 6.3 (M25), 8, 11, 13, 14 |
| D-SAFE-2 | `jev_repo.get_hypothesis_title` in place of `repo.get_hypothesis`; the detail-read test as a reach walk, proved on synthetic trees that call `repo.get_hypothesis` and `repo.list_findings` | 1, 5.1, 5.3, 6.3 (M10), 9.2, 10.1, 13, 14 |
| D-SAFE-3 | On a blocking finding, `route_chip` shows only a role in `VETO_ROLES`; a property test over random registers; owner question Q16 | 0 (D5), 6.3 (M24), 6.4, 11, 13, 14 |
| D-SAFE-4 | A re-judge is asked with `api_key=None`, by a `rejudge` payload marker, and completes as `not_on_record` when nothing is on record under the pin in force; P9 moves the pin | 0 (D19), 5.1, 5.2, 5.3, 5.5, 10.4, 10.6, 13 |
| D-SAFE-5 | Provenance `system`, on `jev_requests` alone; `jev_signals` refuses it by CHECK; `STATE_ADDRESSED` names it | 0 (D8), 2.1, 2.4, 6.3 (M26), 7, 11, 13, 14 |
| D-SAFE-6 | 0015 refuses DELETE and TRUNCATE on `findings`, and a reopen; M2's mechanism corrected; the panel atomicity test's clean-up retires instead of deleting | 0 (D21), 6.2, 6.3 (M2, M23), 7, 13, 14 |
| D-SAFE-7 | The two real API tests named, each proved on a synthetic tree | 9.2, 13 |
| D-HMB-01 | D1's moved tests found by running both suites on a scratch copy carrying D1's skeleton: 86 unit cases in eight files, `test_jev_prereg.py` whole, and 31 integration cases in four files; the `jev_stats` claim struck | header, 7, 12, 13 |
| D-HMB-02 | Every part of every vocabulary word, HTTP token and exception name held to `NEVER_IN_VOCABULARY`; other job kinds and table names kept out of the vocabulary's source; every word alone and every ordered pair run through the three rules | 4.3, 4.6 |
| D-HMB-03 | The outlook restated with every condition of `usable`: the baseline table, the stated assumption about the raiser, flip pairs counted in canonical requests, the re-ask ceiling, the supply of subjects; `findings.owner` said plainly not to be expected to beat the raiser; owner question Q3 | 3.6, 10.7, 11, 14 |
| D-HMB-04 | `suggestions` prints statuses, never an answer, a probability, a chip or a Jev finding's ref; the "cleanest labels" claim withdrawn; open item 75; owner question Q17 | 0 (D23), 3.5, 6.4, 9.3, 11, 13, 14 |
| D-HMB-05 | As D-SAFE-4 | as D-SAFE-4 |
| D-HMB-06 | Looks counted per set, version and question across every model; open item 78 restated | 0 (D1), 3.2 (M3), 3.7, 10.2, 13, 14 |
| D-HMB-07 | `job_error_text` and `job_error_from_text`; `label_problems` checks a `STATE_ADDRESSED` subject through the state its text names | 1, 2.1, 3.5, 3.7, 12, 13 |
| D-HMB-08 | Ops items dated over the rows their population reads; the reasoning recorded; owner question Q14; open item 81 | 3.4, 3.7, 11, 13, 14 |
| D-HMB-09 | Runs collapsed again after the truncation; the literal `[more]` inputs in the fixed corpus | 4.2, 4.6 |
| D-HMB-10 | Every ops keyword held to an evidence corpus of real messages; `sqlstate`, `postgres`, `asyncpg` and the exception class names dropped; the code-defect label reads the messages builtins write | 3.4, 13 |
| D-HMB-11 | The CHECK renamed `findings_jev_names_its_request`; the trigger `findings_jev_rests_on_its_answer` holds a Jev finding to a valid `true` of a canonical card request | 0 (D21), 6.3 (M27), 7, 13, 14 |
| D-HMB-12 | `lpad(n, greatest(4, length(n)), '0')`, one constant `repo.JEV_REF_SQL`, evaluated at 10,000 and beyond | 0 (D22), 7, 13 |
| D-HMB-13 | Eight sets after D2 and nine after D3; the test name corrected | 2.6, 13 |
| D-HMB-14 | The guarantee reworded to the harness's own commands, pointing to open item 79 | 14 |
| D-HMB-15 | P5 names what it compares, and asserts the jobs' arming fields apart | 10.6 |
| D-HMB-16 | As D-SAFE-2 | as D-SAFE-2 |

### 15.2 Alternatives not taken, and why

- **D-SAFE-1, "a single switch instead".** The default here follows the
  operator's recorded defaults (docs/08 fact 7, and "Inputs needed"): only
  code-computed features and titles go without the detail switch. Sending ops
  under its area switch alone would change those defaults, which is the
  owner's to do, so it is put as Q15. If the owner chooses it, docs/08 is
  amended before D3 merges.
- **D-SAFE-3, "or not at all".** Hiding the owner chip on every blocking
  finding would also hide a suggestion that the finding belongs to another
  veto role. That suggestion argues for no release: the finding still blocks
  under a veto either way. The stricter choice is left to the owner as Q16.
- **D-SAFE-5, "at minimum, a test and a sentence in docs/08".** Not taken,
  because the full fix costs one CHECK widened under its own name, as 0013
  did, and buys a database refusal (`jev_signals_provenance_check`) that no
  test of `record_signal` can give.
- **D-SAFE-6, "or refuse that too", meaning a refusal on `candidates`
  DELETE.** Not added. Nothing in `src/` deletes a candidate (checked). A
  candidate's delete already fails whenever the candidate has a finding,
  because the cascade fires `trg_findings_no_delete`. A candidate with no
  finding removes nothing that was raised. `candidates` is not a table phase D
  writes or reads for its rules, and a rule on it would be reviewed with the
  programme's lifecycle, not with Jev.
- **D-HMB-02, "or forbid underscores in VOCABULARY".** Not taken. The subject
  text carries underscores whatever the vocabulary holds (`ingest_bars`,
  `ingest_reference_bars`, `http_429`), so the check has to read parts anyway.
  Holding every part to the forbidden words also covers HTTP tokens and
  exception names, which a rule on `VOCABULARY` alone would not.
- **D-HMB-04, "record per labeller when answers or the register were shown,
  and refuse those labels for arming".** Not built in D. No findings set can
  arm in D (`ARMABLE` is the card alone), and the card's exposure is open item
  72's. With `suggestions` showing no answer, the only exposure left in D is
  the findings register, which arms nothing. Recording exposure is put to the
  owner (Q17) before any findings set becomes armable.
- **D-HMB-05, "put the pin in the payload and complete as superseded on a
  mismatch".** Not taken alone. `run_ask` would check the pin, and the road
  would then read it again, so a pin changed between the two reads would
  still reach a call. Asking with no key closes the window by construction,
  since every call the road makes is behind its key check. The pin may still
  be written into the payload for the record. It is not the control.
- **D-HMB-06, "include pins in the family" or "a new pin needs a new plan
  version".** Not taken. Pins are not known when the plan is registered, so a
  family counting them has no fixed size, and the level could not be written
  as a literal. A new plan version sets aside every lane's history, which is
  the cost section 3.1 exists to avoid. Counting looks across models keeps the
  family as `_gated_family` already counts it.
- **D-HMB-08, "keep dating every occurrence, and state what it does".** Not
  taken as the default. One recurring vendor error would make every ops
  evaluation an upper bound for good, so no ops threshold could ever be
  searched. The date of a private row carries nothing about training. Both
  readings are put to the owner (Q14), and the consequence of the one chosen
  is stated beside each ops evaluation.
- **D-HMB-10, "hold each keyword to a skeleton produced from a raise-site
  message (the AST-collected corpus)".** Taken in substance, with a different
  corpus. Messages from the triaged modules' own raise sites are code-triaged
  by `code_cause` and never reach the population the baseline reads. The
  baseline reads the residue: library and builtin messages passed through.
  So the evidence corpus is real messages of that residue, produced or built
  from the libraries' own classes, and a keyword must fire on one of them.
- **D-HMB-11, "or rename the constraint to what it checks".** Both done: the
  CHECK is renamed `findings_jev_names_its_request`, and the trigger carries
  the old name's claim.
- **D-HMB-12, "or format the ref in Python as `_next_ref` does".** Not taken.
  Counting and formatting in the one INSERT keeps the ref's count and its row
  one statement. The expression is a constant, so a test can still evaluate
  it at any count.
- **D-HMB-16, "or drop `hypotheses.card` from the claim".** Not taken: the
  card is kept off the Jev side instead, and the claim holds.

### 15.3 Found while verifying, beyond the critiques

The scratch run behind D-HMB-01 also showed three things the critiques did
not name. Each is fixed above.

- **The first draft's general hold fix changed phase C's behaviour.** It
  generalised `_plan_asks`' screen-only exception, and two phase C planner
  tests failed. The re-judge rule is now a step of its own (section 5.2).
- **0015's triggers must compare `origin` NULL-safely.** With `<>`, an insert
  naming no origin raised the Jev trigger's error rather than the column's
  `NOT NULL` (section 7).
- **The draft said `test_programme_convene.py`'s fakes must accept
  `origin`.** They take `**kwargs` and pass unchanged (section 13).
