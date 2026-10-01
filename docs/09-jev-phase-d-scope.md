# Jev phase D: the build scope

The binding scope handed to the agents that build D1 to D4, beside the
design it binds, `docs/09-jev-phase-d-design.md`. It is written to the
builder, so it says "you". Section 9 lists what the owner reviews before
anything phase D builds is switched on.

YOUR PART: phase D of the Jev integration. That is findings routing, ops triage, and the card check armed, built as four pull requests, D1 to D4, each dark. Build it as `docs/09-jev-phase-d-design.md` specifies, in its revised form. Its sections 2 (the words, final), 3 (the plans), 4 (the redactor), 7 (migration 0015) and 13 (the tests) are BINDING.

Where this file and the design differ, this file wins. Where the code at your base differs from both, the code is the truth, and you say so. Every switch stays seeded off. Nothing is switched on, and no call is made to TypeSafe.

Safety rule 5 does not change in phase D. No LLM or Jev output may reach an order, and the Rule 5 amendment stays PROPOSED until phase F. Phase D touches nothing in the decision path, the signals, the worker, the engine or the three live-money gates.

0. READ FIRST, AT YOUR BASE (`origin/main`, 23dee2b or later)
   - CLAUDE.md:
     - safety rules 1, 4, 5 and 7;
     - the honesty rules;
     - every structural-guarantee row that names Jev, the programme's ledger or `findings`.
   - docs/08:
     - fact 7 and its "Defaults that follow". Only code-computed features and titles go without `jev_send_internal_detail`;
     - "Switches, all fail closed";
     - "Lanes", the Findings routing, Ops triage and Guardrails rows;
     - "The Rule 5 amendment — PROPOSED";
     - "Delivery";
     - "Phase C, as built", above all C1+C2, C4, C7+C8 and C9;
     - "Inputs needed from the operator";
     - open items 54 to 70, and item 67 most of all: arming a threshold is phase D's change, and it moves `jev_calibration` across the boundary test that keeps it out of everything that acts.
   - the design (`docs/09-jev-phase-d-design.md`), all of it. Section 15 lists what review changed and why, and section 13's last table lists the existing tests D1 moves.
   - The code, by name:
     - `jev_questions`: `QuestionSet.dump_state`, `registration_problem`, `_model_carries_text`, `_sends_undeclared_text`, `_OWN_TEXT_PROVENANCES`, `STATE_SUBJECT`, `TEXT_SUBJECT_FIELD`, `TEXT_SUBJECT_PROVENANCE`;
     - `jev_lane`: `_checked`, `_check_subject`, `_switched_on`, and the order in `ask` (the canonical replay comes before the key check, and every call comes after it);
     - `jev_jobs`: `ASKABLE`, `run_ask`, `_ask_payload`, `_load_hypothesis`;
     - `jev_plan`: `_plan_asks` and its screen-only hold exception, `_Room`, `_plan_reasks`;
     - `jev_repo`: `hypotheses_to_ask`, `pending_asks`, `ask_job_key`, `item_dates`, `subject_texts`;
     - `jev_eval`: `build_evaluation`'s flip block, `label_problems`, `_parser`, `execute`, `possibly_in_training`;
     - `jev_calibration` (`usable`, `_beats`, `_flips_within`, `card_verdict`), `jev_prereg`, `jev_catalogue`, `jev_stats`, `flags`;
     - `gates` (`VETO_ROLES`, `FindingFact.blocks`), `tick` (`_convene`'s `raise_finding`), `repo` (`raise_finding`, `close_finding`, `get_hypothesis`, `list_findings`, `_next_ref`), `roles` (`system_prompt`, `MAX_FINDINGS_PER_ASSESSMENT`), `web_sources` (`code_screen`, `SKELETON_SPACES`), `job_errors`, `main`;
     - `src/db/repos/jobs.py` (`fail`) and `src/worker/main.py`, which records `str(exc)` with no class;
     - migrations 0008 (`findings`: no DELETE rule, `ON DELETE CASCADE` from `candidates`, a CHECK that admits `open` always), 0012, 0013 and 0014;
     - `tests/unit/test_import_boundaries.py` (`RUNNER_ONLY`, `test_the_api_does_not_import_the_programme_runner`, `test_the_programme_modules_the_api_imports_hold_no_client`, `PLANNER_MUST_NOT_REACH`, `HARNESS_MUST_NOT_REACH`, `PURE_PROGRAMME_MODULES`, `test_nothing_that_acts_loads_the_calibration`, `_synthetic`);
     - `test_jev_table_boundaries.py`, `test_job_ownership.py`, and `test_jev_jobs.py`'s `_Reach` and `TestTheCardCheckChangesNothing`.

1. KEEP EVERY EARLIER GUARANTEE
   - There is one road, `jev_lane.ask`, which records once and replays forever. Every switch is read by the road on every ask, each through its own fail-closed reader, none derived from another.
   - The planner is the only producer of a job that can make a call. Each job attempt makes one call at most. The claim reads `JEV_HANDLERS` at claim time, and the 35 s shutdown grace stands.
   - Every answer is recorded beside the plans in force (`plans_in_force`, in payload and result). C9 measures. `card_verdict` never gives less friction armed than unarmed, and `document_path` takes no calibration. The screen stays unarmed.
   - The ledger stays append-only.
   - No `jev_*` or `web_*` module reaches a model runner (I8). `src/api` loads no runner module.
   - Jev never writes a finding's severity or status, never closes a finding, is never in `VETO_ROLES`, never resumes, retries, cancels or fails a job, and never touches the kill switch or any switch.
   - The UI is phase E's. D adds no route and no API read. The API's one change is a literal `origin="operator"` on a write it already makes.
   - Fixtures are synthetic. The paperswithbacktest README carries no licence.

2. D1 — PLAN V2 AND THE FOUNDATIONS (calls nothing, registers no set)
   a. Plan v2 (design 3.2), released while the ledger is empty. Version 1's hash stays in `RELEASED_PLAN_HASHES`.
      - `PLAN_VERSION` 2.
      - `STATISTIC_FLOORS` replaces `LANE_TARGETS`: covered accuracy at least 0.80, and covered precision of the acting class at least 0.90, each a one-sided Wilson lower bound at `GATE_CI`. A set plan may raise a floor, never lower it.
      - `GATE_FAMILY` 20, `DEV_SPLIT_TENTHS` 5, `MAX_LOOKS` 4.
      - `GATE_CI` 0.999375, written as a literal and held to 1 − 0.05/(20 × 4).
      - M2: flips are counted over every canonical request of the question under the pin.
      - M5: a re-ask that could not be compared counts against the flip limits, in the worst case.
      - **Looks are counted per set, version and question across every model**, the identity `_gated_family` counts, so a new pin restores no look.
   b. The regime's plan, apart (M4): `REGIME_PLAN_VERSION` 1, `regime_plan()`, `regime_plan_hash()` and `GOLDEN_REGIME_PLAN_HASH`, with a released history kept in the test. `jev_forward`'s result gains `regime_plan_version` and `regime_plan_hash`. `forward` scores agreement under the regime plan.
   c. `--split` has no default, and takes `dev`, `test` or `all`. `test` and `all` need `--record`, and `dev` never records. **Enforce this in `jev_eval.execute`**, which `main` and every caller reach. `usable` gains the `looks` reason and M5.
   d. Migration `0015_jev_phase_d.sql`, exactly as design section 7 gives it.
      - `findings.origin`: `NOT NULL`, the default dropped once existing rows read `'unknown'`, and an insert trigger refusing `'unknown'`.
      - `source_request_id`, with the CHECK `findings_jev_names_its_request`, and the trigger `findings_jev_rests_on_its_answer`: a Jev finding rests on a valid `true` to an `ok`, non-probe `guardrail.card` request, `raised_by` being `'jev:' ||` that set.
      - The CHECKs `findings_jev_is_raised_by_jev`, `findings_jev_never_blocks` and `findings_jev_is_on_a_candidate`, and the unique index `findings_one_per_jev_answer`.
      - `findings_keep_what_was_raised`: only the closure's columns change, and **a closed finding is never reopened**.
      - **`trg_findings_no_delete` and `trg_findings_no_truncate`**: no writer removes a finding, and a candidate's cascading delete fails with it.
      - `jev_arm_card_check` seeded `false`.
      - **`system` added to `jev_requests_provenance_check` alone**, under its own name. `jev_signals_provenance_check` stays as 0013 wrote it.
      - 0014's flip conjuncts moved out of `jev_evaluations_counts_within_n` into `jev_evaluations_flip_counts_are_counts`.
      - Every comparison of `origin` in a trigger is NULL-safe.
      - It applies over 0014 holding rows, or fails whole. Never edit an applied migration.
   e. `repo.raise_finding(..., *, origin)` is keyword-only with no default. The tick passes `"model"` and the API passes `"operator"`.
   f. `jev_repo.get_hypothesis_title(conn, ref)` returns `ref, title, origin, created_at` and nothing else. It is the title sets' `load` in place of `repo.get_hypothesis`, whose `SELECT *` hands the Jev side the card.
   g. Registry rules:
      - `STATE_ADDRESSED` is a mapping from a state model to its writer's provenance, empty in D1. `_check_subject` holds `subject_id == state_hash(sent_state)` for it.
      - `TEXT_FREE_LANES = {"ops"}`. Registration **requires** `internal_detail` for an ops set, and requires its state be text-free with no exemption.
      - `dump_state` runs `_sends_undeclared_text`, with no `title` exempted, for every set in these lanes **whatever its `internal_detail`**.
      - `"system"` joins `jev_catalogue.PROVENANCES` and `_OWN_TEXT_PROVENANCES`.
      - Prove each rule with test-only sets.
   h. `flags.jev_arm_card_check`, through `flags._switch`: on only for a stored JSON `true`. `JEV_KEYS` gains it.
   i. `LANE_BUDGET_PERCENT`: research 25, guardrail 25, findings 10, ops 10, signals 0, decision 20, probe 10. `MIN_DAILY_REQUEST_BUDGET` stays 10. The settings refusal names the lanes with the smallest share.
   j. The planner's one general rule: a set declaring `internal_detail` is planned only while `jev_send_internal_detail` is on, read through its own reader. `_plan_asks`' screen-only hold exception stays word for word. **Do not generalise it.** The first draft did, and two phase C tests failed.
   k. Boundary tests (design 9.2 and 13), each proved on synthetic trees:
      - **the detail-read reach walk**, using `_Reach`, from every Jev root;
      - the write allow-list walk;
      - the switch-write scan;
      - the scan for a job the programme did not claim.
   l. Every existing test D1 moves, as design section 13's last table lists them: 86 unit cases in eight files, `test_jev_prereg.py` rewritten, and 31 integration cases in four files. That table was found by running both suites on a scratch copy carrying D1's skeleton. It is a floor: re-derive it against your build, and add any failure it missed.
      - `test_programme_panel_atomicity.py`'s clean-up retires its candidate and leaves its findings.
      - `test_a_dry_run_records_nothing` becomes a `--split dev` dry run.

3. D2 — FINDINGS ROUTING (the findings area, seeded off)
   - `FindingTitleState`, a title of 1 to 200 characters. A test holds `FINDING_TITLE_MAX_CHARS` equal to `roles.ProposedFinding.title`'s `max_length`.
   - `findings.owner` v1 and `findings.severity` v1, word for word as design 2.2 and 2.3 give them, provenance `model`. Pack hashes `7e97f8b11d80494d5ecb978bc04240226229993d2f73617b1fccdf7ea4437c8c` and `a9cae8cdafff291715982ea74dc3fe05f3e0da1ba8ffdd03cc428df585e830e0`; questions hashes `2989fecdce44b1ff9bd1c216b5eb1f33bbc76fc15427403e83defac412239ff3` and `0504d4817b84e44db3fc268f4d64bfd0d4d0e4ec62856f84595ccd9bab08db9e`. Re-pin them from the merged words, and they must match.
   - The set plans have the recorded-value baseline, `findings.recorded`, reading `raised_by` and `severity` of the earliest model-written finding holding the title. Neither column is ever exported.
   - `ASKABLE` entries load through `jev_repo.get_finding_title` (`ref, title, origin, opened_at` only). They admit `origin = 'model'` within the cap, refused by the cap and never by pydantic. Neither set has a follow-up.
   - The planner's rules read `findings_to_ask`, under the findings area, at 10 a pass each, from the findings share.
   - `jev_chips` is pure and API-importable.
     - `severity_chip` only escalates.
     - **`route_chip`, on a finding that blocks, names only a role in `VETO_ROLES`.** A property test over random registers holds it, mirroring the severity chip's.
     - `duplicate_chips` points only from a newer finding to an older one that blocks at least as much.
   - The harness's `finding_title` subject: its dates, texts and population; `preview`; and `suggestions`. **`suggestions` prints whether each subject was asked and how the ask came out, never an argmax, a probability, a chip or a Jev finding's ref.**
   - The findings canary, the SDK case, and the dark matrix with the findings area.

4. D3 — OPS TRIAGE (the ops area AND the detail switch, both seeded off)
   - `jev_redact`, pure, with the rules of design 4.2.
     - Placeholders are taken before the split, in square brackets.
     - **Runs are collapsed, then the skeleton is truncated to 47 tokens plus `[more]`, then runs are collapsed again.**
     - `finished_at` is required.
   - The vocabulary (design 4.3):
     - At most 400 words, never drawn from the job kinds outside `TRIAGED_KINDS` or from table names.
     - **Every underscore part of every word and HTTP token, and every capital-split part of every exception name, is held to `NEVER_IN_VOCABULARY`.**
     - Every word alone and every ordered pair are run through `hidden_characters`, `markup_in_cell` and `instruction_phrase`, each read directly.
     - The vocabulary has a golden and a released history.
   - `jev_chips.code_cause` runs over a pinned, hashed table of shapes held to the raise sites. It returns `None` only for a triaged kind's residue. The reconciliation, data-health and ingest chips are code's, never sent.
   - `JobErrorState` (a `Literal` job kind and a `Literal` token tuple), `job_error_subject`, and **`job_error_text` with `job_error_from_text`**, whose round trip a test holds.
   - **`ops.job_error` v1, provenance `system`, `internal_detail=True`**, word for word as design 2.4 gives it. Pack hash `1e625e8f0965342d12907dbc27fb78e66db44086bb0b6428359c8ab9c512b512` (recomputed under `system`), questions hash `e24fe30799ea8252dd3eac4dba6df02cb7fd9a0aaf4d4d11007fedc7df6a617a`. `STATE_ADDRESSED = {JobErrorState: "system"}`.
   - The plan's population is failed jobs of `TRIAGED_KINDS` finished after the pin's first observation, left to Jev by `code_cause`, with at least three content tokens. **Items are dated over these same rows.**
   - `OPS_KEYWORDS` (design 3.4) are **each held to an evidence corpus of real messages**: builtins' messages triggered in the test, and library exceptions built from their own classes. A keyword no message produces is dropped, so `sqlstate`, `postgres`, `asyncpg` and the class names go. The code-defect label comes before `data_missing`.
   - The `ASKABLE` entry is addressed by state.
   - The planner rule runs under ops ∧ the detail switch.
   - The harness's `job_error` subject. **`label_problems` reads a `STATE_ADDRESSED` subject through `job_error_from_text`.**
   - The ops canary, and the SDK case, recorded as `system`.
   - **The dark matrix: ops on with the detail switch off plans nothing and sends nothing.**
   - Review D3 as this system's own text leaving it for the first time.

5. D4 — THE CARD CHECK ARMED (the arming switch, seeded off)
   - Pure, in `jev_calibration`: `ARMABLE` (one pair, `guardrail.card` and `performance_claim`), `Arming`, `arming` and `card_addition`.
   - `jev_arming` is runner-only and is the one acting reader of a calibration. It reads every switch, the pin, the registered set and the newest evaluation of its identity. That evaluation must be person-labelled (`operator:`), and `usable` must pass under the plans in force, looks counted across models. Nothing is cached, and a failed read raises, failing the attempt for a retry.
   - `repo.raise_card_finding` writes one non-blocking finding per active candidate of the title's model-written hypotheses:
     - `origin 'jev'`, `raised_by 'jev:guardrail.card'` and severity `'medium'`, each a literal;
     - `source_request_id`;
     - `ON CONFLICT DO NOTHING`;
     - a `J-` ref from **`repo.JEV_REF_SQL`, `lpad(n, greatest(4, length(n)), '0')`**, never cut.
     `active_model_candidates` names its columns.
   - Re-judges:
     - `_plan_rejudges` is a step of its own, behind the guardrails area and the arming switch. It plans under holds and takes no share. Its key is `rejudge_job_key`, and `pending_asks` leaves re-judges out.
     - A re-judge's payload is the nine names plus `"rejudge": true`, for `guardrail.card` alone. **`run_ask` asks it with `api_key=None`.** It replays, or completes as `not_on_record` having sent and written nothing, a pin moved between the plan and the claim included.
   - The boundary move (open item 67), in four tests: the calibration's importers are exactly `jev_eval` and `jev_arming`; nothing else that acts reaches it; every path from `jev_jobs` and `main` runs through `jev_arming`; `jev_jobs` alone imports `jev_arming`.
     - `RUNNER_ONLY` and Safety rule 5's list gain `jev_arming`.
     - `PLANNER_MUST_NOT_REACH` gains `jev_arming` and `jev_calibration`. `HARNESS_MUST_NOT_REACH` gains `jev_arming`.
   - P1 to P12 (design 10.6). **P5 compares every table but `findings`, `jev_evaluations` and `jev_labels`, and `jobs` but `result`, and asserts the arming fields apart. P9 moves the pin between the plan and the run, and asserts zero calls.**
   - The arming line in `status` and `report`.

6. TESTS
   - Design section 13 is binding. Its tags give the PR each test lands in.
   - Every scan is proved on synthetic trees that must trip it and trees that must not.
     - The detail-read walk trips on a handler calling `repo.get_hypothesis` or `repo.list_findings`.
     - The two API tests trip on `from src.programme import jev_arming` in a module of `src/api`.
   - Mutation-check every new control: remove each in turn, and a named test fails.
     - Each 0015 rule: every rule and every conjunct no other rule implies has a case breaking it alone.
     - `TEXT_FREE_LANES`, the redactor's rules, `route_chip`'s orientation, `api_key=None` on a re-judge, the detail switch in the planner, and `system` refused by `jev_signals`.
   - Run ruff, the unit suite, parity, the integration suite on real PostgreSQL and the SDK job (`-m sdk`), and get every one green in each PR.
   - Drop every database you create.

7. DOCS
   - docs/08:
     - a "Phase D, as built" subsection for each PR;
     - the Lanes rows for Findings routing, Ops triage and Guardrails rewritten;
     - the arming switch, and the detail switch's reach over ops, in "Switches, all fail closed";
     - 0015 in the schema section;
     - `system` in the provenance vocabulary;
     - fact 7's defaults and "Inputs needed" restated with ops, after the owner answers item 9.1 below;
     - Delivery marking phase D done;
     - open items 71 to 82, as design section 14 numbers them. They start after 70, the highest at base.
   - CLAUDE.md:
     - Safety rule 5's runner list gains `jev_arming`;
     - the `src/programme` architecture row gains `jev_redact`, `jev_chips` and `jev_arming`;
     - the database paragraph covers 0015;
     - the Commands block gains `preview`, `suggestions` and the `--split` rule;
     - Known limitations: phase D is dark, ops goes only behind the detail switch, `findings.owner` is not expected to beat the raiser, and the card check will not be armed for years;
     - the structural-guarantee rows of design section 14, worded as there. Looks are "counted through the harness's commands", not every look.

8. THE PULL-REQUEST SPLIT
   - Four PRs, each dark, each with its own docs/08 subsection and CLAUDE.md rows.
   - **D1 merges first, before any Jev area is first switched on.** Plan v2 is free only while the ledger is empty.
   - D2 and D3 follow, in either order.
   - D4 comes last, so the allow-list of what Jev code may write is final.

   | PR | Depends on | Dark because |
   |---|---|---|
   | D1 | — | It registers no set, plans and asks nothing, and the arming switch has no consumer |
   | D2 | D1 | The findings area is seeded off |
   | D3 | D1 | The ops area and the detail switch are both seeded off |
   | D4 | D1, D2, D3 | The arming switch is seeded off, and no usable evaluation can exist for years |

9. BEFORE ANYTHING IS SWITCHED ON: WHAT THE OWNER MUST REVIEW
   Nothing in phase D switches anything on. Before an operator first switches on any Jev area, the detail switch or the arming switch, the owner reviews these and answers each. They are design section 11's questions, and the items D leaves open.
   9.1 **Ops and the detail switch.** A skeleton goes only while `jev_send_internal_detail` is on (chosen, after fact 7's defaults), or under the ops area alone, which would amend fact 7 before D3 merges. One detail switch covers every set that declares `internal_detail` (open item 82).
   9.2 **Plan v2, before D1 merges**: R1 and R2 required; M1 to M5 recommended, each separable; looks counted across models.
   9.3 **The regime's baseline rule and sleeves** (docs/08 "Inputs needed" 2). These are still the agent's defaults. Review them before the decisions area is first switched on. A change is a free `REGIME_PLAN_VERSION` bump until the first regime answer.
   9.4 **The words**: the three sets, word for word, before their area is first switched on. A rewording after that is a new version, and it re-asks every subject.
   9.5 **The redactor**: the vocabulary, `NEVER_IN_VOCABULARY`, the secret words, the shapes table, `OPS_KEYWORDS` and the evidence corpus. A change after the first ops answer is a new set version (open item 77). Read `preview --set ops.job_error` on real failed jobs before the ops area goes on.
   9.6 **What leaves, read first.** Run `preview` for each area and read exactly what it would send, and which switches it would need.
   9.7 **The findings sets.** Keep or drop `findings.severity`, which is expected never to reach 0.80, and `findings.owner`, which is not expected to beat the raiser.
   9.8 **Ops provenance `system`**, refused by `jev_signals`, or `internal`.
   9.9 **The triaged kinds**: research and ingest only. Venue, shadow and programme kinds get code chips alone.
   9.10 **The owner chip on a blocking finding**: only a role holding a veto (chosen), or never.
   9.11 **How ops items are dated**: over the population's rows (chosen), or over every occurrence (open item 81).
   9.12 **Label exposure**: `suggestions` now shows no answer. Nothing records who has read the findings register, which shows the raiser and severity beside each title (open item 75), or Jev's findings on it once armed (open item 72). Accept that for D, where no findings set can arm, or ask for exposure to be recorded first.
   9.13 **Who labels for arming** (a person only). **Shares** (25/25/10/10/20/10). **Duplicates**: code-exact only, with the Jev question deferred (open item 71).
   9.14 **The armed effect**: a finding that never blocks (chosen), or a hold, once phase E gives a held candidate a release route.
   9.15 **Time to arm**: years, at 1,300 to 2,800 labels and 3,000 to 6,000 titles asked. Accept it, or revisit the card's target while no card answer exists.
   9.16 **The arming switch's granularity**: one per armable pair, set through phase E's typed confirmation.
   9.17 **Left for their own review, not phase D's**:
   - the worker's error naming its class (open item 73);
   - the daily report's blocking count, which is not veto-aware (open item 74).
   9.18 **The switching order**: `programme_enabled`, then `jev_enabled`, then one area at a time, then for ops the detail switch, and the arming switch last. Each is read through its own fail-closed reader, and none implies another.
