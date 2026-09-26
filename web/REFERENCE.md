# REFERENCE — web/ design evidence

**Status: adopted 2026-09-26 (owner decision OD-1, `DESIGN.md` §0.2). Observations only.** This file records what the
web UI *is*: the values it uses, the roles those values play, the patterns that recur, and where the UI disagrees with
its own documents. It contains no rules. Rules live in `DESIGN.md`, and they bind only once the owner has approved them
(the article this system follows, Prompt 1: "'The three approved screens use 24 px between cards' is an observation.
'All card groups must use 24 px' is a rule that a human should approve"). Sections 8 and 9 are the only parts that go
past observation. Section 8 names patterns that approved or stated rules already forbid, with the evidence that they
occur. Section 9 asks the owner questions, and records the four the owner has answered.

Read it when a change touches a token, a rule or a pattern, not before every UI change (`CLAUDE.md`). Beside it:
`design/notes.md` keeps each rule's first wording, its basis and what shipped, and `design/decision-log.md` each
rule's status, date, owner and basis.

The observations were measured at commit `0ec084f`. The change that adopted this file fixed some of what they record;
each such observation is kept, as history, and marked **superseded (FX-n)** where it appears. §0 lists them.

## How to read the citations

| Key | Meaning |
|---|---|
| `globals.css:N` | `web/src/app/globals.css`, line N, at commit `0ec084f` (HEAD on 2026-09-26). Other code paths are relative to `web/src/`, at the same commit. |
| `repo:path:N` | A path from the repository root, at `0ec084f` (`repo:CLAUDE.md:109`). |
| `0ec084f:DESIGN.md:N` | Line N of the root `DESIGN.md` as it stood at `0ec084f` (`git show 0ec084f:DESIGN.md`). The adopting change reduced that file to a pointer; its full text is Appendix A below, with the original line numbers. |
| `OD-n` | An owner decision, 2026-09-26: `DESIGN.md` §0.2, and verbatim with its row in `design/decision-log.md`. |
| `FX-n` | An observation the adopting change superseded (§0). |
| `EC §n` / `I-n` | `evidence_code.md` section n / its inconsistency n (§11). Build output of `next build`, Tailwind 4.3.3, Next 15.5.22, measured at 1280×800 and 390px with **fixture** API data. |
| `ES §n` / `O-n` | `evidence_screens.md` section n / its observation n (§5). `next dev` against a real API and Postgres with **seeded synthetic** data, 1440×900 and 390×844, both schemes. |
| `shot:name` | `design/shots/name.png` (DPR 1, so 1 image px = 1 CSS px). `shot-code:name` is `design/evidence/shots_code/name.png`. |
| `probe Pn` | `design/capture_data/probes.json` and the `probe_*.json` files beside it. |
| [computed] | WCAG 2.x contrast or OKLCH→sRGB arithmetic on cited values (`design/tools/contrast.py`, `design/scripts/colour.py`). The hex arithmetic is also `_oklch_hex` in `repo:tests/unit/test_design_tokens.py`. |

`EC`, `ES`, `shot:`, `probe` and `design/…` name the records of the 2026-09-26 survey. They are kept outside the
repository (where to keep them is Q-20), so every observation below restates the value that was measured: this file
stands on its own, and the records are what would let someone re-check a measurement. `tests/e2e/design_capture.py`
regenerates the route captures under the same names.

Capture caveat that affects every screenshot: no web font is loaded (EC §2.1), and on the capture VM both system stacks
resolved to **DejaVu Sans / DejaVu Sans Mono** (ES §0.3). Sizes, colours and spacing are exact. Glyph shapes, text widths
and wrap points are DejaVu's, not what macOS or Windows would show.

---

## 0. What the adopting change superseded

The change that landed this system in `web/` also fixed defects this file observed: FX-1 to FX-7, FX-13 and FX-14 are
its honesty half; FX-8 to FX-12, FX-15 to FX-19, FX-22 and FX-23 its component half; FX-20 and FX-21 the two layout
failures the capture check (`design/checks.md` (b)) had baselined. FX-24 and FX-25 are the backend half, made after
the first re-measurement below and confirmed by their tests. The observations stay, because they are what the rules were
drawn from, and each is marked where it appears. Measurements in §2-§7 are still as of `0ec084f` unless a row here
says otherwise.

**Re-measured on 2026-09-26**, on the change's final tree, against a copy of the survey's seeded database with the
same pinned ids (`design/checks.md` (b), (c)): `design_capture.py` found none of the four failures its baseline held,
`design_axe.py` found no violation on any of the 60 captures (the baseline held ten), and the keyboard walk
(`design_focus.py`) found all 340 stops on its six pages outlined, in both schemes, the lowest at 4.55:1 (light) and
6.29:1 (dark) against its backdrop (§6.7); the browser journey (`repo:tests/e2e/test_browser_journey.py`) passed all
twelve of its steps against the same stack. **And again**, the same day, on a fresh copy, once FX-24 and FX-25 had
landed and the comparison of the first captures with the survey's had sent back what FX-9, FX-10 and FX-16 took
that nobody chose (the gate chip's amber, the sidebar's spacing, the link colour of a `Button` rendered as a link,
the underline's reach): all 60 captures passed, axe found no violation on any, the keyboard walk found all 402
stops on seven pages outlined (the six, and the candidate page), lowest 4.55:1 and 6.29:1, and the journey passed
its twelve steps. "Confirmed by" says where each fix was seen. A fix the seeded
data cannot show (FX-1: no marks exist; FX-14: no shadow session exists) is confirmed by the test that holds it and
by reading the code. None was reopened.

| # | What changed | Rule | Observed at `0ec084f` in | Confirmed by |
|---|---|---|---|---|
| FX-1 | `/programme/report` formats drawdown with the shared percent formatter, and `repo:tests/unit/test_web_formatting.py` refuses a "%" attached to a figure anywhere in `web/src` but `lib/format.ts` | H-12 | §7 "Scaling and capping"; §8.2 item 4 | the test; the browser journey's step 9, which serves a drawdown of -0.0512 and reads "-5.12%" on both pages |
| FX-2 | `MetricsPanel` renders an unmeasured slippage or session count as an absence, not "0 bps" (`?? 0`) or "252 sessions/year" (`?? 252`) | H-3r, H-6r | §7 table; §8.2 item 1 | the test (no numeric fallback); the seeded run records both, so its capture shows "5 bps" and "252 sessions/year" |
| FX-3 | The backtest page's fills title is the run's total (`metrics.n_fills`), not the API's page limit (500); `repo:tests/unit/test_fill_count_contract.py` holds the metric equal to the stored rows | E-8 | §7 "Scaling and capping"; §8.2 item 4 | `backtests-id__*`: "Fills (779)" and "Showing the 200 most recent of 779." |
| FX-4 | The backtests list states significance as a word (a "not significant" chip, from the stored flag), and its Window cell carries each run's effective start and session count | H-1r, H-5r, H-6r | §7 table; §8.2 items 2 and 3 | `backtests__*` |
| FX-5 | `/portfolio` marks figures from a failed refresh as stale, and labels the account with the mode the response carries | E-13 (the `/portfolio` half) | §6.5 | `portfolio__*` ("Read at …"); the journey's steps 10 and 11 (a paper→live switch, a failed poll) |
| FX-6 | `/programme` no longer says shadow mode is unbuilt: stage 3 is shadow mode, and the stage 4–8 gates are what is unbuilt | H-18 | §7 "Other honesty observations" | `programme__*` |
| FX-7 | An absence component, `Absent`, renders OD-4's words where "—", `?? 0` and `?? 252` stood, and `repo:tests/unit/test_web_formatting.py` refuses a new bare dash or numeric fallback in `web/src` (its allow-list holds only `EquityChart`'s two axis divisors, which are never rendered); where a dash meant *false* or "nothing to note", a word says so; `lib/format.ts` holds the one `fmtAge`, which `/system` uses too | H-3r, H-3s, `DESIGN.md` §5.1 | §6.3 item 8; §7 | `portfolio__*`, `programme__*`, `programme-experiments-ref__*`, `backtests__*`; the test |
| FX-8 | One card: shadcn `Card` with a hairline `--border` edge; the legacy `.card` and the `currentColor` edge go | K-16, C-8a (OD-3) | §2.5; §6.3 item 2 | every capture; both former 0px joins measure 12px; `repo:tests/unit/test_web_components.py` |
| FX-9 | One chip: `StatusBadge`; the legacy `.pill-*` and `.badge` go. A gate's summary chip keeps the amber it shipped with, as the `caution` state (▲, `promotionGateStatus`); it was the red `blocked` for a while on the way, and each unmet criterion in it is `blocked` | K-16 (OD-3); C-5 | §3.6; §6.3 item 1 | `programme-candidates-id__*`, `system-configuration__*`, `backtests-id__*`; the test |
| FX-10 | The legacy `@layer base` element rules no longer reach shadcn or Radix components (button edge and fill, label margin, sheet title). Two jobs they did for components go on, stated by the components: the sidebar's groups sit 48px apart (`AppNav`'s `mt-8`, the legacy `h2` margin), and a ghost or outline `Button` rendered as a link is the link colour (`ui/button.tsx`, the legacy `a` rule's) | K-15 (OD-3) | §3.1; §3.5; §4.2; §4.8; §5; §6.3 item 3 | the sort headers and buttons on every list; the findings checkbox, 0.6px off its label's centre (6.6px before); `dashboard__desktop__*` (the sidebar) and each detail page's back link; the test |
| FX-11 | One focus indicator on every control: the 2px accent outline at 2px offset; the shadcn ring and the sheet close's ring go | A-4 (OD-3) | §2.6; §2.7; §6.7 | `design_focus.py`; the test, which recomputes the outline's contrast |
| FX-12 | On `/system`, a halted kill switch renders a strong amber "stopped"; red is left to a state in which live money is reachable | C-12 (OD-2) | §2.1; §7.1 | `system__*`; the journey's steps 7 and 12; the test |
| FX-13 | A hypothesis card's missing required field says "missing" and what it blocks (gate 0→1), apart from the one optional field; the page's list of required fields is compared with `REQUIRED_CARD_FIELDS` by `repo:tests/unit/test_web_formatting.py` | H-17 (OD-4) | §7 "Other honesty observations" | H-0003, the incomplete card, opened apart from the route captures: "MISSING — gate 0 → 1 refuses the card without it" on each required field, "no data" on the optional one |
| FX-14 | The shadow sessions' underfunded-buy note is pluralised ("1 buy trimmed", "2 buys trimmed") | H-8r | §7 table | the code (`candidates/[id]/page.tsx`) |
| FX-15 | A card's title is an `h2` (`CardTitle`), and `MetricsPanel`'s heading sits outside its `dl`, so no page skips from `h1` to `h3` and the `dl` holds only `dt`/`dd` | T-5, A-8 | §6.7 (axe `heading-order`, `definition-list`); §3.5 | axe; the test |
| FX-16 | A link in running text — a paragraph, list item, table cell, definition or banner — is underlined, so it is not told apart by colour alone, and hover thickens the line that is now drawn; a link that stands alone is not (the rule first underlined every link, the report's "← Programme" and the skip link with them) | A-5 | §6.7 (axe `link-in-text-block`; "Links have no visible hover state") | axe; every capture; the test |
| FX-17 | A table that scrolls sideways is a focusable, named region while — and only while — it overflows (shadcn `Table` and its `label`); the candidate scorecard now scrolls inside it | A-7 | §6.7 (axe `scrollable-region-focusable`); §4.9 | axe, on `/system` and the candidate page at 390px |
| FX-18 | The per-row "view" columns name themselves for assistive technology ("Open", "Details") and hide the name visually (`DataTable`'s `hideHeader`) | A-8 | §6.7 (axe `empty-table-header`) | axe, on `/backtests` and findings |
| FX-19 | The mobile sheet has a description (`SheetDescription`) | A-8 | §6.7 "Dialog" | the code; the route captures never open the sheet |
| FX-20 | `EquityChart` draws in CSS pixels at its measured width: axis text at `--t-sm` (12px) at every width, the label margin sized from the labels it holds, whole-dollar ticks | T-1, E-5 | §3.3; §6.1 `EquityChart` row (O-15) | `backtests-id__mobile__*`, whose `small-text` check now passes |
| FX-21 | An assumption value wraps anywhere (`overflow-wrap: anywhere`), so the candidate's JSON parameters no longer widen the page | E-1, E-2 | §4.9 | `programme-candidates-id__mobile__*`: 390px wide, and its `overflow` check passes |
| FX-22 | The 55 `tw-animate-css` classes are gone; `repo:tests/unit/test_web_components.py` refuses one unless the package is installed and imported | M-4 | §6.6 | the test |
| FX-23 | `/system` shows a failed refresh as stale: the kill switch and the gates read "not read" beside their last reading, and the rest is marked with the time it was read; a failed first load keeps the `h1` and says what failed | E-13 (the `/system` half), G-2, E-9 | §6.5 | the journey's step 12 |
| FX-24 | The API serves a backtest figure the run did not record as `null`, not as a default (252 sessions a year, no fills, a Sharpe of 0 ± 0, costs at 1x), so the page's "not measured" branches can fire; the deployment gate's refusal no longer quotes an unrecorded stitched Sharpe as +0.000 ± 0.000 | H-3, H-3s, H-6r | §7 "Defaults the page cannot see through" | `repo:tests/integration/test_unmeasured_is_null.py` |
| FX-25 | Every backtest the programme queues, and its experiment, records the whole cost model the worker applies — slippage, stress, minimum trade, concentration cap — so the backtest page quotes the slippage rather than "missing"; the programme's walk-forward experiments record the cost model the study runs at | H-4, H-4r | §7 "Defaults the page cannot see through" | `repo:tests/integration/test_programme_cost_model.py`; `repo:tests/unit/test_cost_model_record.py` |

## 1. Source inventory and approval status

The status labels come from the article ("approved, historical, experimental or inspiration-only"), plus the three
this repository needs. **No screen is approved yet.** Only the owner, Quentin Casares, approves a screen or a rule
(OD-1), and none of the screens has been. Four owner decisions (OD-1 to OD-4, 2026-09-26) settle rules, not screens.

| Label | Meaning here |
|---|---|
| approved | Already a rule in `repo:CLAUDE.md`, enforced by a test in `repo:tests/`, or decided by the owner and recorded in `design/decision-log.md` (OD-n). |
| shipped — awaiting owner approval | Renders in production code at `0ec084f`. Nobody has approved it as a pattern to copy. |
| stated intent — awaiting owner approval | A committed document or code comment says it is intended. No approval record exists, and the rendering sometimes disagrees. |
| planned — not built | Specified for a future phase. |
| historical | Named as superseded, by the code itself or by an owner decision. |
| inspiration-only | Informs the process, not the visuals. |

| Source | What it holds | Status |
|---|---|---|
| `web/src/app/globals.css` (904 lines) | The 40 custom properties (`:root`, :43-139), 14 light overrides (:141-164), the Tailwind mapping (`@theme inline`, :202-260), and the legacy element and class sheet (`@layer base`, :291-904) | shipped — awaiting owner approval. `0ec084f:DESIGN.md:6-7` calls it the source of truth. |
| `web/src/components/**`, `web/src/app/**` | 10 product components, 13 vendored shadcn "new-york" components (`repo:web/components.json:3`), 15 routes | shipped — awaiting owner approval |
| `design/shots/` | 60 route captures (15 routes × desktop/mobile × light/dark), 42 state captures, 80 keyboard images, 2 probe crops (ES §1) | shipped — awaiting owner approval. Synthetic data; DejaVu fonts. |
| `design/evidence/shots_code/` | 26 captures against a fixture API (EC header) | shipped — awaiting owner approval. Fixture values. |
| Owner decisions OD-1 to OD-4, 2026-09-26 | Answered by the owner in the session, through a structured question: OD-1 who approves and where the system lives (Q-28, Q-1); OD-2 which state of a safety control is red (Q-30); OD-3 the canonical card, chip and focus indicator (Q-4, Q-5, Q-6); OD-4 the absence words (Q-10, H-17). Wording verbatim in `design/decision-log.md`; summarised in `DESIGN.md` §0.2. | approved (owner) |
| `repo:CLAUDE.md` Honesty rules (:96-131) | Eight rules on what a figure must carry | approved (repo rules) |
| `repo:CLAUDE.md` Safety rule 5 (:70-87) | No LLM output reaches an order. The Jev amendment is proposed, not in force (:84-87). | approved |
| `repo:CLAUDE.md` structural guarantees (:300-301) | Unmeasured is never rendered as zero; a missing measurement is `unknown`, not `fail`. Tested by `test_programme_scorecard.py` on the scorecard's rows (Python), not on the rendered page. | approved (test) |
| `repo:tests/unit/test_programme_scorecard.py::TestTheRecommendation::test_there_is_no_overall_score` | The scorecard has no `score` or `grade`: "Collapsing seventeen dimensions into one number lets a strong Sharpe outvote an unmeasured capacity." The candidate page says the same in its own copy (`candidates/[id]/page.tsx:312`; `shot:programme-candidates-id--stage0-blocked__desktop__dark`). | approved (test, data layer) |
| `repo:CLAUDE.md` Safety rules 1, 2 and 7 (:44-55, :90-94) | Three independent live-order gates, "deriving one from another is a weakening"; the kill switch and the programme switch fail closed. `/system` and `/programme` render these (7.1). | approved (repo rules; enforced at the API and worker, not on the page) |
| `repo:CLAUDE.md` structural guarantees with a UI consequence (:281, :290, :291, :295) | A dead worker looks dead (liveness from `stale`); a human approval confirms a pass and a failed gate answers 409 with the unmet criteria; synthetic evidence cannot reach operation; the stored autonomy ceiling never masquerades as the effective one | approved (tests at the API and programme layer; the rendering is untested) |
| `repo:tests/e2e/test_browser_journey.py:46-50, :129-132, :150-153` | The tearsheet must show "Synthetic data", "Not statistically significant" and "Annualised on"; the run exits 1 otherwise. Run by hand, not in CI (:8-12). | approved (test, manual) |
| `repo:CLAUDE.md` (:307-308) and `repo:tests/unit/test_import_boundaries.py::test_nothing_that_can_move_money_names_a_model_vendor_host`, `::test_only_the_jev_modules_spell_the_typesafe_endpoint`, `repo:tests/unit/test_dependency_boundaries.py::test_no_npm_package_claims_to_be_typesafe`, `::test_no_lookalike_host_appears_in_anything_that_ships`, `repo:tests/unit/test_secret_isolation.py::TestTheLookalikeNameIsNeverUsed` | `web/src` names no model vendor's host and spells no TypeSafe endpoint; no npm manifest or lockfile carries a TypeSafe-named package; no lookalike host appears in `web/src` or a package file; no file directly under `web/` (so any `web/*.md` this system adds) spells the lookalike reseller's key name. `:308` also says "the frontend holds no model client", but **no test refuses a non-TypeSafe model SDK in `web/package.json`**: `test_no_npm_package_claims_to_be_typesafe` applies only `_claims_to_be_typesafe` (`test_dependency_boundaries.py:447-478`, :1179-1199), and an SDK's host lives in `node_modules`, which the host scan does not read. | approved (tests), with that gap |
| `repo:CLAUDE.md:470-472` ("Known limitations") | "the shadow book's equity is not a result and the UI says so" | stated intent — awaiting owner approval: a description of current behaviour in the Known limitations section, not a rule, and no test reads the page. The candidate page's shadow card does say it (`candidates/[id]/page.tsx:453-458`). |
| `0ec084f:DESIGN.md` (the root `DESIGN.md`, 231 lines; Appendix A) | Theme rationale, token tables, component and motion intent, a contrast table | historical: superseded by `web/DESIGN.md` (OD-1) and reduced to a pointer by the adopting change. Its statements remain stated intent, which INFERRED rules cite. Thirteen of them are contradicted by the code or the rendering at `0ec084f`: :38 (`--border` for hairlines; shadcn cards render `currentColor`, FX-8), :116 (13px inputs and buttons; shadcn renders 12px at ≥768px), :129-132, :134 (`td.prose` 42ch), :139 (4px base; 6px gaps), :139-140 (sections at `--s-6`; 12px rendered), :157, :159-162, :163, :180-182, :194-197, :215, :219-220 (one focus ring; two render, FX-11) (ES §7; EC §11 I-23, I-24, I-39, I-41; 3.2 below). The root `CLAUDE.md` never mentioned it (grep, 2026-09-26). |
| `repo:PRODUCT.md` (120 lines) | Users, purpose, personality, anti-references, five principles, accessibility | stated intent — awaiting owner approval: it is the product brief, not a record of design approvals. Four of its statements disagree with the code at `0ec084f`: :65-68 (the palette "is GitHub Primer near-verbatim" and "is being replaced", while `globals.css:15-17` says it "used to be"), :72-76 (absence never a dash; "—" renders in 18 places), :109-111 (a second channel for every status; backtests-list significance is colour and `title` only, FX-4), :117-118 (a visible focus ring on every control; the date input's calendar stop shows none). OD-4 approves the rendering half of :72-76, and OD-3 the focus half of :117-118. |
| Parallel work, 2026-09-26 | Phase B of `docs/08` is being built on another branch: `src/programme/jev_*.py`, `migrations/0012_jev.sql`, Jev tests, and one change under `web/`, which gives `components/SecretField.tsx` a "TypeSafe (Jev) API key" title and note (+9 lines after line 45). Every citation here is to `0ec084f`, so once that lands, `SecretField.tsx` lines from 46 on read 9 lower. | context only, not a source: noted so phase E is not assumed further off than it is |
| Design comments in code (`globals.css:3-41`, `:166-201`, `:275-290`; `components/StatusBadge.tsx:4-26`; `components/ui/card.tsx:5-15`) | Intent recorded beside the values | stated intent. Several are stale (I-41). |
| `repo:docs/08-jev-integration.md` "Web UI rules" (:612-635), with :276-280, :590-591, :602-610 | UI obligations for any page that shows a Jev answer | planned — not built. Phase E is "Not started" (:647). Owner: Quentin Casares (:4). |
| The GitHub Primer palette (`globals.css:16`: "#0e1116, #4493f8, #3fb950") | The palette the stylesheet says it replaced | historical |
| Kevin Riedl, "Claude Code Design System: 4 Parts for On-Brand UI", Wavect, 2 Sep 2026 (`https://wavect.io/blog/claude-code-design-system-files/`) | The four-part process these files follow ("the article") | inspiration-only |
| `evidence_code.md`, `evidence_screens.md` | The measurement records every line below cites | evidence, not a source of rules |

---

## 2. Colours

### 2.1 Tokens: values, samples and observed roles

All 14 colour tokens are OKLCH in `globals.css`. Hex values are [computed], clipped to sRGB the way Chromium paints them.
`*` means outside sRGB: with CSS Color 4 gamut mapping, light `--blocked` would be `#940000` and light `--unknown`
`#824a00` (EC §1.2). "Pixel" values were sampled from screenshots and match the computed hex (ES §0.3).

| Token | Dark `oklch()` → hex (line) | Light `oklch()` → hex (line) | Pixel sample | Role the file states | Observed use |
|---|---|---|---|---|---|
| `--bg` | `0.178 0.011 255` → `#0e1116` (:48) | `0.977 0.003 255` → `#f6f7f9` (:143) | (14,17,22) outside a card, `shot:backtests__desktop__dark` | "surfaces" (:44-47); "Page" (`0ec084f:DESIGN.md:35`) | body background (`globals.css:299`) |
| `--panel` | `0.221 0.013 255` → `#171b21` (:49) | `1 0 0` → `#ffffff` (:144) | (23,27,33) | "Cards, top bar" (`0ec084f:DESIGN.md:36`) | cards, sidebar, phone header, sheet, metric cells; 115 backgrounds (ES §2.3) |
| `--panel-2` | `0.262 0.015 255` → `#20252c` (:50) | `0.958 0.004 255` → `#eff1f4` (:145) | — | "Inputs, pills, row hover" (`0ec084f:DESIGN.md:37`) | the most common background, 275 (ES §2.3): chips, active nav item, legacy inputs, row hover, legacy buttons |
| `--border` | `0.322 0.016 255` → `#2e343c` (:51) | `0.885 0.006 255` → `#d6d9dd` (:146) | (46,52,60) on a row separator at (549,267) | "Hairlines" (`0ec084f:DESIGN.md:38`) | legacy cards, table rows, sidebar edge, metric-grid gaps and background |
| `--border-strong` | `0.412 0.018 255` → `#444c55` (:52) | `0.800 0.010 255` → `#b9bec4` (:147) | — | "Buttons, table head rule" (`0ec084f:DESIGN.md:39`) | legacy button border (on every `<button>`, O-4), `th` bottom rule, shadcn input border; 68 backgrounds as `input/30` in dark |
| `--text` | `0.955 0.004 255` → `#eef0f3` (:58) | `0.240 0.014 255` → `#1b2026` (:149) | card edge (238,240,243) dark / (27,32,38) light (O-1) | "ink" (:54-57); "Body" | 1,827 text elements (ES §2.3). Also the border of every shadcn Card (2.5; superseded, FX-8). |
| `--muted` | `0.723 0.013 255` → `#a0a6ae` (:59) | `0.487 0.016 255` → `#5a6069` (:150) | — | "Secondary prose, labels, placeholders" (`0ec084f:DESIGN.md:46`) | 549 text elements |
| `--faint` | `0.645 0.012 255` → `#898e95` (:60) | `0.528 0.014 255` → `#666c73` (:151) | — | "Unreachable lifecycle stages" (`0ec084f:DESIGN.md:47`) | 73 text elements: nav group headings, stages 4-8 |
| `--accent` | `0.740 0.093 232` → `#6ab5dc` (:66) | `0.520 0.110 232` → `#00739d`* (:153) | (106,181,220) / (0,115,157) on the primary button | "Primary action, current selection, focus. Nothing decorative" (:62-65) | 56 text elements (links), 23 fills; focus outline; equity line |
| `--accent-ink` | `0.185 0.020 232` → `#09141a` (:67) | `0.995 0.004 232` → `#fbfeff`* (:154) | — | text on accent (`--color-primary-foreground`, :211) | 8 text elements |
| `--accent-dim` | `0.560 0.070 232` → `#477c97` (:68) | `0.660 0.080 232` → `#5d9bbb` (:155) | — | none stated | legacy `button.primary:hover` only (:631) |
| `--blocked` | `0.725 0.185 30` → `#ff705c`* (:88) | `0.404 0.190 30` → `#950000`* (:160) | (149,0,0) on the Reject button, light | "refused, failed, halted — loudest" (:88) | 23 text elements, 2 fills at 60 % (dark destructive button) |
| `--unknown` | `0.800 0.140 78` → `#efb146` (:89) | `0.464 0.130 70` → `#854800`* (:161) | — | "not measured, indeterminate" (:89); model-authored content (`.badge`, :522-536) | 177 text elements: unknown chips, `.badge`, "mind the multiple testing" |
| `--settled` | `0.660 0.072 158` → `#6ca081` (:90) | `0.524 0.075 158` → `#427759` (:162) | — | "met, passed, alive — quietest" (:90) | 173 text elements: settled chips, "No real order can be placed…" |

- `--unknown` is the only token whose hue differs between the themes: 78 in dark, 70 in light (EC §1.2).
- The role `globals.css:88` states for `--blocked` includes "halted". OD-2 takes that out on a safety control: a halted
  kill switch is a safe state, rendered as a strong amber "stopped", and red there means live money is reachable
  (superseded, FX-12; `DESIGN.md` C-12). The stated role is observed as written at `0ec084f`.
- The adopting change added two colour tokens the survey never measured, for that "stopped" chip: `--stopped`,
  `0.800 0.140 78` → `#efb146` (dark `--unknown`'s value, used in both schemes), and `--stopped-ink`,
  `0.185 0.020 78` → `#181208` [computed]. Ink on the plate is 9.79:1; the plate against `--panel` is 9.09:1 in dark and
  1.90:1 in light. Both are PROPOSED until the owner answers Q-34.
- The three signal colours are ordered by chroma: settled 0.072 < unknown 0.140 < blocked 0.185 (`globals.css:75-77`).
- The utility names that reach each token are in EC §1.3. For example, `--panel-2` is reached as `bg-secondary`,
  `bg-muted`, `bg-accent` and `bg-panel-2`. Product code uses the product names: `text-ink-muted` ×89 outside
  `components/ui/`, plus once inside it (`ui/badge.tsx:65`; the inventory's ×90 counts both). The shadcn names appear
  only in `components/ui/` (EC §1.3), but the product names are not confined to product code: the four status variants
  of `ui/badge.tsx:61-65` use `bg-panel-2`, `border-line`, `text-settled`, `text-unknown`, `text-blocked`,
  `text-ink-muted`.
- Six product utilities exist in the `@theme` mapping and are used nowhere in `web/src` (grep, 2026-09-26): `bg-bg`,
  `bg-brand`, `text-brand`, `text-brand-ink`, `bg-brand-dim`, `border-blocked` (the last only in `ui/badge.tsx:63`).
  The page background reaches the DOM through `body { background: var(--bg) }` (`globals.css:299`), and the accent
  through `border-l-brand` (`AppNav.tsx:129`), `a { color: var(--accent) }` (`globals.css:752`) and shadcn's
  `bg-primary` / `ring`.

### 2.2 Derived colours in use

These are `color-mix(in oklab, X p%, transparent)` or Tailwind `/NN`, which renders X at alpha p (EC §1.4(a)).

| Where | Mix | Source |
|---|---|---|
| `.banner-warn` / `-info` / `-bad` | fill 10 / 10 / 12 %, border 42 / 38 / 48 % of unknown / accent / blocked | `globals.css:490-501` |
| `.badge` border (superseded, FX-9) | unknown 45 % | `:535` |
| `.pill-good` / `-warn`,`-unknown` / `-bad` borders (superseded, FX-9) | 45 / 45 / 52 % | `:695`, `:703`, `:711` |
| shadcn `Badge` signal borders | `/40` | `components/ui/badge.tsx:61-63` |
| Drawdown fill; warm-up band | blocked 26 %; muted 12 % | `:565`, `:567` |
| `.changed` flash; skeleton midpoint | accent 26 %; panel-2 60 % into border | `:785`, `:763` |
| Focus ring (shadcn; superseded, FX-11) | `ring-ring/50`; destructive `/20` light, `/40` dark | `ui/button.tsx:8,14`; EC §7.4 |
| Destructive and primary fills | `bg-destructive/60` (dark), `/90` hover; `bg-primary/90` hover | `ui/button.tsx:14`; EC §1.4(a) |
| Input fill (dark only); row hover | `bg-input/30`; `bg-muted/50` | `ui/input.tsx:11`; `ui/table.tsx:60` |

Measured: the light `.banner-warn` inside a card composites to `#f3ede5`, pixel (242,236,229) (ES §0.3).

### 2.3 Colours that do not come from a token

- `text-white` on the destructive Button (`ui/button.tsx:14`), measured `rgb(255,255,255)` on 2 rendered text elements
  (ES §2.3).
- `bg-black/50`, the sheet overlay (`ui/sheet.tsx:39`).
- `color: oklch(0.99 0 0)` in `button.danger` (`globals.css:632`). No element uses `.danger` (EC §5.3).
- Tailwind's default shadows, whose black alpha is hard-coded (`shadow-xs`, `shadow-md`, `shadow-lg`), appear only in
  `components/ui/` (EC §1.4(a); verified by `repo:tests/unit/test_design_tokens.py`).
- There are **no** hex, `rgb()`, `hsl()` or `oklch()` literals in any `.ts` or `.tsx` file, no `style=` attribute and
  no `dangerouslySetInnerHTML` in `web/src` (grep, 2026-09-26).

### 2.4 How the theme is chosen

- The unconditional `:root` block holds the dark values (`globals.css:43-139`). `@media (prefers-color-scheme: light)`
  redefines the 14 colour tokens and nothing else (:141-164).
- There is no class, attribute, storage or `matchMedia` switch (EC §1.1).
- Tailwind's `dark:` variant is also media-based (compiled `@media (prefers-color-scheme: dark)`). It is used 13 times,
  all in vendored files (EC §1.1).
- `html { color-scheme: dark light }` (`globals.css:295`).

### 2.5 Border colour when none is named

Tailwind 4's preflight sets `border: 0 solid` and leaves the colour at `currentColor`, and `globals.css` sets no
default (EC §3.5). Every element that uses a bare `border` utility is therefore outlined in its **text** colour:

- **shadcn Card**: dark `#eef0f3`, light `#1b2026`, 15.4–16.6:1 against the page (O-1; `shot:backtests__desktop__dark`
  at (232,170)). Superseded, FX-8: OD-3 makes the card's edge the hairline `--border`.
- **Legacy `.card`**: `--border`, 1.3–1.5:1 against the page (O-1). Superseded, FX-8: OD-3 retires it for the shadcn
  `Card`.
- **Sheet edge**: `currentColor`. Not covered by OD-3, which names the card; C-8 in `DESIGN.md` still applies.
- **Outline link-buttons in light**: the link colour, `#00739d` (EC §3.5; ES §4.6).

Both card borders appear on one page, `/programme/candidates/[id]` (`shot-code:dark-1280-candidate`; superseded, FX-8).

### 2.6 Contrast of pairs the UI renders

Thresholds are WCAG 2.x: text 4.5:1 (3:1 for large text: 24px and over, or 18.66px and over if bold), non-text 3:1.

- No text renders at 24px (the h1 is 23px/400).
- At 18.66px or more with a weight above 400 there is only the mobile sheet title (19px/600, ES §3). axe-core 4.13.0
  counts text as bold only at weight ≥700 (`boldValue: 700`,
  `repo:tests/e2e/design/node_modules/axe-core/axe.js:27206`, :32618, once `npm ci --prefix tests/e2e/design` has run), so under the checker used here that title is not large text either. No text on the site qualifies as large.
- Every pair measured below 4.5:1 is 14px or smaller, so none qualifies as large on any reading (EC §7.8).

- **Census.** The screen census checked 11,420 text nodes in their static state and found **0 enabled nodes below
  4.5:1** (ES §6.3).
  - Lowest in dark: 5.13:1, a settled chip.
  - Lowest in light: 4.59:1, an accent link inside a warn banner that sits in a card, and 4.62:1, a settled chip.
- **Pairs below 4.5:1 [computed]** (EC §7.8), all interaction states or placements the census could not see:

  | Pair | Dark | Light |
  |---|---|---|
  | legacy `button.primary:hover` text | 4.06 | 3.01 |
  | destructive Button hover text | 3.22 | 7.94 |
  | shadcn primary hover text | 6.92 | 4.39 |
  | accent link in a warn banner placed directly on the page background | 7.06 | 4.31 |

  The census measured the last pair at 4.59:1, because on `/programme` the banner sits on a card, not on the page.
- **Non-text [computed]:**
  - Input boundary against the card: shadcn 1.97 / 1.87; legacy 1.37 / 1.41.
  - Chart grid lines: 1.37 / 1.41.
  - Focus ring (shadcn, accent at 50 %) against the card: 2.89 / 2.16 (superseded, FX-11: the ring goes).
  - Destructive focus ring: 2.03 (40 %) / 1.50 (20 %) (superseded, FX-11).
  - Legacy 2px outline: 7.63–8.34 dark, 5.01–5.35 light (EC §7.8; ES §6.4-6.5). OD-3 makes it the one indicator on
    every control (FX-11).
- **Links against body text:** 1.98:1 dark, 3.07:1 light. Links are never underlined (EC §7.7; O-7).

### 2.7 Where the colour evidence contradicts stated intent

- Dark `--bg` converts to `#0e1116`. That is exactly the hex `globals.css:16` names as the retired Primer value ("It
  used to be GitHub Primer near-verbatim — #0e1116, #4493f8, #3fb950"). `repo:PRODUCT.md:65-68` names no hex; it says
  the current palette "is GitHub Primer near-verbatim" and "is being replaced", so the two documents disagree about
  whether the replacement happened. Accent and settled did change (`#6ab5dc` vs Primer's `#4493f8`; `#6ca081` vs
  `#3fb950`) (ES §2.1; O-17).
- `0ec084f:DESIGN.md:215` publishes "`--blocked` pill, light 6.4". The computed value is 8.16 (clipped) or 8.23
  (gamut-mapped). The other seven published ratios reproduce within ±0.05 (EC §7.8).
- `0ec084f:DESIGN.md:163` says "Disabled controls never keep a saturated fill". Both disabled primaries keep the accent fill,
  at opacity 0.5 (shadcn, `ui/button.tsx:8`) and 0.45 (legacy, `globals.css:620`) (O-5).
- `0ec084f:DESIGN.md:219-220` says "One focus ring". Two indicators render, three counting the sheet close (O-8;
  6.7 below). Superseded, FX-11: OD-3 keeps the accent outline and removes the rest.

---

## 3. Typography

### 3.1 Families

- `--sans: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif` (`globals.css:97`).
- `--mono: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace` (`globals.css:96`).
- No web font, `next/font` or `@font-face` exists (EC §2.1). The rendered face is whatever the host resolves (DejaVu on
  the capture VM, ES §0.3).
- The monospace face is applied to:
  - `input`, `select` and `textarea`, by the legacy base rule (`globals.css:584`), measured on every page (where that
    rule reaches a shadcn field, superseded, FX-10);
  - every `StatusBadge` (`components/StatusBadge.tsx:39`);
  - assumption-row values, including full sentences (`globals.css:549`; O-14);
  - `font-mono` ×46 and `.mono` ×19 (EC §2.6).
- The most frequent rendered text style is **12px / 17.14px / 400 / monospace**, on 1,443 desktop elements (ES §2.3).

### 3.2 The scale, and what the Tailwind names mean here

| Token | Value (line) | Tailwind name | Note |
|---|---|---|---|
| `--t-xs` | 0.6875rem = 11px (:103) | `text-xs` | line-height 14.67px (Tailwind default `calc(1/0.75)`) |
| `--t-sm` | 0.75rem = 12px (:104) | `text-sm` | **12px here, not Tailwind's 14px**; line-height 17.14px |
| `--t-base` | 0.8125rem = 13px (:105) | `text-base` | **13px here, not 16px**; line-height 19.5px |
| `--t-body` | 0.875rem = 14px (:106) | `text-body` | body: 14px / 21.7px (line-height 1.55, :303) |
| `--t-md` | 1rem = 16px (:107) | `text-md` | h3, metric values |
| `--t-lg` | 1.1875rem = 19px (:108) | `text-lg` (never used as a utility) | h2; h1 at ≤640px (:883) |
| `--t-xl` | 1.4375rem = 23px (:109) | `text-xl` (never used as a utility) | h1 |

Sources: ES §2.2 and EC §2.3. The remapping of `text-sm`, `text-base` and `text-xs` is recorded as O-9.

**Control text: stated intent and rendering disagree.** `0ec084f:DESIGN.md:116` gives `--t-base` (13px) to "Secondary
prose, inputs, buttons". The legacy controls follow it (`input` 13px, `globals.css:585`; `button` 13px, `:611`). The
shadcn controls do not: `Button` is `text-sm` = 12px (`ui/button.tsx:8`), `Label` 12px (`ui/label.tsx:16`), and `Input`
is `text-base md:text-sm` = 13px below 768px and 12px from 768px up (`ui/input.tsx:11`; ES §4.2). This is Q-29.

### 3.3 Sizes that render

| Size | Desktop elements (pages) | Mobile | Where |
|---|---|---|---|
| 10px | 8 (1) | 8 (1) | chart axis labels (`.axis`, `globals.css:562`); `.effective-label` (:569); pill glyph (:690) |
| 11px | 583 (14) | 541 (14) | chips, `th`, metric labels, `.no-data`, nav group headings |
| 12px | 1955 (15) | 1815 (15) | table cells, buttons, labels, nav links, inputs (desktop) |
| 13px | 134 (15) | 134 (15) | banners, legacy inputs, assumption values, inputs (mobile) |
| 14px | 136 (14) | 122 (14) | body, card titles, subtitles |
| 16px | 49 (7) | 49 (7) | metric values, some h3 |
| 19px | 6 (2) | 23 (15) | legacy h2; **every h1 on mobile** (`globals.css:883`) |
| 23px | 17 (15) | 0 | h1 on desktop |

Source: ES §2.3. Chart text is 10 SVG user units in a 900-unit `viewBox`, so its rendered size scales with the
container: about 11px at 1280px wide and **3.6px at 390px** (EC §7.8, §9.3). Superseded, FX-20: the chart now draws in
CSS pixels, and its text is 12px at every width.

### 3.4 Line heights

No line-height is tokenised. The same size renders with several, because remapped Tailwind sizes keep upstream ratios
and element rules set their own (EC §1.3; ES §2.3):

- 12px renders at 17.14, 18.6, 16.5 and 12px.
- 11px renders at 14.67, 17.05, 15.71 and 14.3px.
- 13px renders at 20.15, 19.5 and 18.57px.

Literal line-heights in the sheet: body 1.55, h1 1.25, h2 1.3, `.metric dd` 1.3, `.pipeline-card-title` 1.35
(EC §1.4(c)).

### 3.5 Weights and hierarchy

- **h1, h2 and h3 render at 400.** Preflight sets `font-weight: inherit` and the product rules set no weight (EC §2.4).
- **`CardTitle` renders at 600**, at 14px/14px, as a `<div>` (`ui/card.tsx:43-51`, :47). Every shadcn section title is
  therefore heavier than the page's h1 (EC §2.4; I-8). The element is superseded (FX-15: it is an `h2`); the weight is
  not (Q-9).
- 500 (`font-medium`, 12 uses) is used by Button, Badge, Label, `TableHead`, the nav group heading, the pipeline stage
  head and the strategy form's h3 (EC §2.4).
- 700 appears once: the raw scorecard `th`, which gets the browser default because no rule sets a weight (EC §9.1).
- Heading outline per route: EC §2.7.
  - Only `/system/configuration` has an h2 outline.
  - Most pages go h1 → `CardTitle` divs, or h1 → h3 (superseded, FX-15).
  - On desktop, three nav `<h2>`s ("Research", "Operations", "Programme") precede the page h1 in DOM order.
  - The mobile sheet title is an h2 caught by the legacy h2 rule: 19px/24.7px/600, so the brand wraps to two lines
    (ES §3; O-24). Superseded, FX-10.

### 3.6 Case and tracking

- Uppercase with tracking is used by `th`, `.metric dt`, `.badge`, `.pill` (0.045em, `globals.css:518`, :532, :645, :686)
  and `.no-data` (0.04em, :665). The `.badge` and `.pill` uses are superseded (FX-9).
- In utilities it is used by the nav group heading (`tracking-[0.045em]`, `AppNav.tsx:110`) and the pipeline stage head
  (`tracking-[0.03em]`, `programme/page.tsx:482`). Measured: 0.495px against 0.33px (ES §4.8).
- The same status vocabulary renders in two treatments on one page (EC §2.5; probe P4b):
  - `StatusBadge`: 11px mono, 500, as written.
  - `.pill` and `.badge`: 11px sans, 400, UPPERCASE, 0.495px.

  Superseded, FX-9: OD-3 keeps the `StatusBadge` treatment as the one chip.

### 3.7 Numerals

- `font-variant-numeric: tabular-nums` applies to `.mono, code, kbd, table, input, select, textarea`
  (`globals.css:309-311`) and to `.num` (:653). The utility `tabular-nums` is used 17 times (EC §2.6).
- Numeric cells are right-aligned (`text-right` ×36) and monospace (EC §2.6; ES §4.3).

---

## 4. Spacing, grid and alignment

### 4.1 The spacing scale, and the steps actually used

- Tokens: `--s-1`…`--s-7` = 4, 8, 12, 16, 24, 32, 48px (`globals.css:113-119`), used only inside the legacy sheet.
- Tailwind's step is `--spacing: .25rem`, so the utilities are 4px × n. These two scales are **not bridged** (EC §1.3):
  - `gap-3` = 12px = `--s-3`;
  - but `py-5` = 20px, which is no `--s-*` value, and `--s-5` = 24px = Tailwind `6`.
- Gap census, desktop dark (ES §2.3): 8px (261), **6px (246)**, 12px (120), 4px (61), 16px (28), 1px (8, metric grids).
- Steps off the 4px scale in TSX (EC §3.1):
  - 2px `py-0.5`;
  - 6px `py-1.5`, `gap-1.5`, `space-y-1.5`;
  - 10px `px-2.5`;
  - 20px `py-5`;
  - 28px `pl-7`;
  - 36px `pr-9`;
  - 40px `py-10`.
- Raw lengths in the sheet: 1, 2, 3, 7 and 9px (EC §1.4(c)).

### 4.2 Recurring gaps (measured at 1280×800 dark unless stated)

| Relationship | Observed | Exceptions | Source |
|---|---|---|---|
| Card to card | **12px on every page** (`mt-3` ×26, `space-y-3`, `gap-3`, `.card` margin-bottom) | **0px** in two places: Configuration Card → gate `section.card` on the candidate page; "Save changes" row → Credentials card on `/system/configuration`. The legacy `.card` in both joins is superseded (FX-8), and both gaps measured 12px on 2026-09-26 | EC §3.2; probe P3, P4 |
| Page header to first block | 16px (`mb-4`) on 11 pages | 24px on `/`, `/backtests`, `/system/configuration`, from `.subtitle`'s 24px bottom margin (`globals.css:447`) | EC §3.2 |
| Last header text line to first block | 18.5 / 27.69 / 40 / 43.69 / 62.5 / 66.5px | the values depend on which of three intro patterns is used, and on wrapping | EC §3.2 |
| Banner to next block | 12px (`.banner` margin-bottom, `globals.css:482`) | — | EC §3.2 |
| Label to control | 6px (`space-y-1.5`: `/`, `/login`); 8px (`space-y-2`: `/system`, `/programme`, candidate); 4px (`space-y-1`: findings) | 12px where a shadcn `Label` catches the legacy `label { margin-bottom: 12px }` (`globals.css:573`; `SecretField.tsx:145`, `findings:182`, `report:124`; superseded, FX-10); 3px (`label > span`, `/system/configuration`) | EC §3.2 |
| Back link after the last card | 16px (`mt-4`) | — | EC §3.2 |

### 4.3 Card padding

- **shadcn `Card`:** `py-4 gap-3`, with `px-4` on header and content. Measured: padding 16px 0, inner 16px, gap 12px
  (`ui/card.tsx:22`, :35, :80; ES §4.2).
- **Legacy `.card`:** 16px on all sides (`globals.css:456`). Superseded, FX-8.
- Metric cell: 12px (`globals.css:516`). Pipeline card: 12px, from `p-3` (`programme/page.tsx:107`). The `.pipeline-card`
  rule at :839 is never used (EC §5.3).
- Banner: 12px (:481). The chart's empty state: 48px (:559).

### 4.4 The shell

Source: `components/AppShell.tsx`, measured (EC §4.2; ES §3).

- **Grid:** `md:grid-cols-[13rem_1fr]` (:49).
- **Desktop `<aside>`:**
  - 208px wide; padding 12px 8px; gap 16px;
  - `--panel` fill with a right `--border` edge;
  - `sticky top-0 h-dvh`, so full-page screenshots show it ending at y=900 (ES §0.3).
- **Phone `<header>`:** 390×53, padding 8px 12px, sticky, `z-50`.
- **`<main>`:**
  - padding 20px top, 24px sides at ≥768px and 16px below;
  - **no max-width**: `<main>` is 1,072px wide at a 1280px viewport (EC §4.2), and cards are 1,184px wide at 1440px
    (ES §4.2).
- **Prose measures** exist only where set:
  - `.subtitle` 68ch (`globals.css:448`);
  - `max-w-[68ch]` (`programme/page.tsx:273`);
  - gate detail 70ch (:874);
  - `td.prose` 42ch (:659), which is unused.
- **Footer:** outside the shell (`layout.tsx:30-35`), so it always sits below the first viewport. It is 83.6px tall on
  desktop and 158px on mobile (ES §1).
- **Login:** a bare `main` of 448px (`max-w-md`) holding a 384px column (`max-w-sm`), with 40px top padding
  (EC §4.2).

### 4.5 Breakpoints

| Breakpoint | Compiles to | Uses |
|---|---|---|
| `sm:` | `min-width: 40rem` (640px) | 4: `page.tsx:190,205`; `ui/sheet.tsx:65,67` |
| `md:` | `min-width: 48rem` (768px) | 6: the shell (`AppShell.tsx:49` ×2, :53, :68, :92); `ui/input.tsx:11` |
| `lg:` | `min-width: 64rem` (1024px) | 3: `page.tsx:190,205`; `system/page.tsx:158` |
| `xl:`, `2xl:` | — | 0 |
| legacy `@media (max-width: 640px)` | `globals.css:877-884` | Live: assumption and gate rows drop to one column; h1 becomes 19px. Inert: `main` padding (utilities win) and `.topbar` (never rendered). |

Source: EC §4.4.

### 4.6 Grid patterns

| Pattern | Definition | Where |
|---|---|---|
| Metric grid | `repeat(auto-fit, minmax(170px, 1fr))`, 1px gap on a `--border` background (`globals.css:505-514`) | portfolio, programme, report, experiment, `MetricsPanel`. Unfilled tracks paint a solid `--border` block (766×66px on Portfolio: probe P7; O-18). |
| Field grid | `repeat(auto-fill, minmax(200px, 1fr))`, gap `0 16px` (:598-602) | `/system/configuration` |
| Assumption rows | `190px 1fr`, one column at ≤640px (:540-546, :879) | `MetricsPanel`, candidate, experiment, hypothesis, report, configuration |
| Gate rows | `84px 1fr`, one column at ≤640px (:862-869, :882) | `GateChecklist`, findings and assessments on the candidate page |
| Form grid | `grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3` | `page.tsx:190, 205` |
| Two-up cards | `grid gap-3 lg:grid-cols-2` | `system/page.tsx:158` |
| Page header row | `mb-4 flex flex-wrap items-end justify-between gap-3` | 9 files (EC §4.5). `/`, `/findings` and `/hypotheses` use a plain `mb-4` div. |
| Pipeline board | `flex snap-x gap-3 overflow-x-auto pb-2`; 208px columns | `programme/page.tsx:471-479`. The board is 1,968px wide inside 1,150px (desktop) or 324px (mobile) (ES §4.8). |

`.grid` is both Tailwind's `display: grid` and a legacy SVG stroke rule (`globals.css:561`), so every Tailwind `grid`
element also gets the stroke declaration (EC §5.3; I-4).

### 4.7 Radii, borders, elevation, stacking

- **Radius census** (ES §2.3): 4px (221), 6px (184), fully round (183, badges), 2px (15), 10px (9, legacy chips).
  - 6px: containers and shadcn controls.
  - 4px: legacy controls, nav rows, sort buttons, skip link, focus outline.
  - Full: shadcn `Badge`.
  - 10px: legacy `.pill` and `.badge` (superseded, FX-9).
  - 2px: brand mark and sheet close (EC §3.3).
- **Borders** are 1px everywhere except the active nav item's 2px left rule in `--accent` (`AppNav.tsx:127,129`)
  (EC §3.5).
- **Shadows:** `globals.css` defines none. Tailwind's defaults appear only in `components/ui/`: the Sheet, menus,
  select and controls (EC §3.4).
- **Stacking:**
  - `--z-*` = 100…500 (`globals.css:134-138`). Only `--z-toast` renders, on the skip link.
  - Everything else layered uses `z-50`: phone header, sheet, select, menu, tooltip (EC §4.7).
  - The desktop sticky aside has no z-index.

### 4.8 Alignment

- **Numbers in table columns:** right-aligned, monospace, tabular. Numeric column headers are right-aligned to match,
  through `headerClassName: "text-right"` (e.g. `backtests/page.tsx:145`) (EC §2.6). Figures in a metric grid are
  left-aligned: `.metric dd` sets a face and size but no alignment (`globals.css:519-520`).
- **Page header row:** aligns the title block and the actions or status badge by their bottom edge (`items-end`)
  (ES §4.4).
- **Two stacked tables on `/programme/config`** do not share column positions: State starts at x=913 in one and x=900 in
  the other (probe P9; O-22).
- **Findings "Open only" checkbox:** sits 6.6px below the centre of its label (probe P5; O-21), pushed by the legacy
  label margin (superseded, FX-10: 0.6px on 2026-09-26).

### 4.9 Overflow

- **Desktop 1440px:**
  - The findings table is 1,345px inside a 1,150px container, so 195px is hidden and the Opened timestamp is cut mid-string
    (probe P5b; O-19).
  - The pipeline board scrolls by design.
  - The jobs "Error" text overprints the "Created" column by 176px, because `TableCell` forces `nowrap` (probe P2; O-20).
- **Mobile 390px:**
  - No route overflows the document **except the candidate page**. There, an unbroken JSON parameter string widens the
    page to 784px, or 659px for candidate C3 (`shot:programme-candidates-id__mobile__dark`; O-13). Superseded, FX-21.
  - Everywhere else, tables and the board scroll inside their containers. On `/backtests` that leaves only Strategy and
    part of Window visible at load; Source, Status, Sharpe ± SE and Cost are off to the right (ES §4.3).
  - The check `scrollWidth > innerWidth` missed this overflow, because mobile emulation widens `innerWidth` to fit;
    it showed only when measured against the device width (ES §6.7).

---

## 5. Logo and wordmark

There is no logo asset. No image, SVG, favicon or icon file exists in `web/` (find, 2026-09-26). The mark is typographic:

| Placement | Anatomy | Source |
|---|---|---|
| Sidebar, top left | `.brand` link: 10×10 `.brand-mark` square in `--accent`, radius 2px, then the text "Systematic Trading"; gap 8px (`--s-2`); 14px/21.7px, weight 600, −0.01em (−0.14px) | `AppShell.tsx:31-38`; `globals.css:334-349`; ES §3 |
| Phone header, beside the menu button | the same `.brand` link, 167×21.7px, which is under the 24px target size | `AppShell.tsx:89`; ES §6.6 |
| Mobile sheet title | the brand inside a Radix `Dialog.Title` (an h2), which the legacy h2 rule sets at 19px/600; it wraps to two lines, 49.4px tall. Superseded, FX-10: the legacy h2 rule no longer reaches a Radix title | `AppShell.tsx:75-79`; `shot:probe__dashboard__nav-sheet-header__mobile__dark`; O-24 |
| Login, above the h1 | mark plus "Systematic Trading" at `text-md` (16px), weight 400 (a plain `span`, not `.brand`), `flex items-center gap-2`, 20px (`mb-5`) above the h1; not a link | `login/page.tsx:66-69` |
| Document title | "Systematic Trading Control Plane" | `layout.tsx:6` |

- The wordmark therefore renders at three size/weight pairs: 14px/600 (sidebar, phone header), 19px/600 (sheet
  title, wrapped; superseded, FX-10) and 16px/400 (login).

- No clear-space, minimum-size or placement rule exists in `0ec084f:DESIGN.md`, `repo:PRODUCT.md`, `repo:CLAUDE.md`, `docs/`
  or `web/src` (grep, 2026-09-26).
- The only wordmark statement in the repo is an anti-reference: "serif wordmark, borrowed gravitas"
  (`repo:PRODUCT.md:54-56`).

---

## 6. Recurring components and compositions

### 6.1 Product components (`web/src/components/`)

| Component | Job, in its own words | Imports | Measured anatomy |
|---|---|---|---|
| `AppShell` | "Sidebar on a desktop, a sheet on a phone, and nothing at all on the login screen" (:6-7) | 1 | 4.4 above |
| `AppNav` | grouped navigation (:6-32) | 2 | row 191×29.14 (the comment at :30 says 28px); 12px text; padding 6px 8px; radius 4px; 14px icon; active = `bg-panel-2`, `text-ink`, 2px accent left rule, `aria-current` (ES §3). On the candidate and experiment detail pages no item is lit (EC §4.3). |
| `DataTable` | "A sortable, filterable table" (TanStack v8) (:6, :38-44) | 10 | header 11px uppercase 500; sortable headers are **13px mixed-case bordered buttons**, 24.6px tall (legacy `button` rule; superseded, FX-10); rows 49px; cells 12px, padding 8px; filter input 320×32; unmeasured values sort last (:120) (ES §4.3; EC §5.1) |
| `EquityChart` | equity and drawdown as inline SVG, no library (:6-12) | 2 | `viewBox` 900×340; padding {16,16,28,68}; 70/30 split; equity line accent 1.5; drawdown blocked 26 % fill; warm-up band plus dashed `--unknown` line plus the label "full universe from {date}"; no hover, tooltip or keyboard access (EC §9.3). Labels of six-digit values start 7.9px outside the SVG, so their "$" is clipped (probe P1; O-15). Superseded, FX-20: drawn in CSS pixels, with the label margin sized from the labels. |
| `GateChecklist` (+ `AiBadge`) | "A promotion gate, criterion by criterion" (:6) | 1 (+4) | legacy classes only: `section.card`, h2 19px, `.pill` (superseded, FX-8, FX-9); criterion grid 84px + 1fr, padding 12px 0 (ES §4.11) |
| `MetricsPanel` | "Performance figures, rendered with the caveats attached" (:6) | 1 | banners, metric grid (labels 11px uppercase, values 16px mono), "not significant" `.badge` (superseded, FX-9), assumption rows (label 14px sans `--muted`, value 13px mono) (ES §4.4) |
| `SecretField` | "Setting a credential you can never read back" (:6) | 1 | stored / not-set badge; fingerprint; a reveal toggle drawn as a bordered 48×30 box inside the input (legacy `button` rule; superseded, FX-10) (EC §3.5) |
| `SessionControls` | sign out (:6) | 2 | `button.linklike`, 14px `--muted` (ES §3) |
| `Skeleton` | "What a page shows while it is fetching" (:4) | 12 | `aria-busy`, `aria-live="polite"`, a visually hidden label; 28px rows; 1.4s sweep (EC §5.1) |
| `StatusBadge` | "The one place a domain state becomes a colour" (:5) | 13 | shadcn `Badge`, fully round, padding 2px 8px, 20.66px tall, 11px mono 500, glyph plus word 6px apart (`gap-1.5`, `ui/badge.tsx:37`); `Status` = `settled`, `unknown`, `blocked`, `mute` (:27) (probe P4b). The three signal variants take a 40 % signal edge and signal text; `mute` takes the `--border` edge and `--muted` text (`ui/badge.tsx:61-65`). OD-3 makes it the one chip (FX-9). OD-2 adds a strong amber "stopped", which `DESIGN.md` C-12r places here (FX-12). |

### 6.2 Vendored components (`components/ui/`, shadcn new-york)

Source: EC §5.2.

- **Imported:** Button 14, Card 14, Input 10, Label 8, Select 4, Table 3, Separator 2, Sheet 1, Badge 1 (only through
  `StatusBadge`).
- **Never imported:** `alert`, `dropdown-menu`, `skeleton`, `tooltip`.
- **Never used:** the Button `secondary` variant and the `xs`, `lg`, `icon-xs`, `icon-sm` and `icon-lg` sizes;
  `CardDescription`, `CardAction`, `CardFooter`, `TableCaption`, `TableFooter`, `SheetDescription`.
- **Retuned in place:** `card.tsx:5-16` records a change to `gap-3 py-4 px-4 rounded-md`.

### 6.3 Near-duplicate families

Each exists twice or more (EC §5.4):

1. **Status chip:**
   - `StatusBadge`: mono, as written, 500, border at 40 %, radius full.
   - `.pill-*`: sans, UPPERCASE, 400, 45/52 %, 10px.
   - `.badge` ("AI-authored", "not significant").
   - Same glyphs (✓ ✕ ▲ ? •), same tokens (O-3).

   Superseded, FX-9: OD-3 keeps `StatusBadge`.
2. **Surface:** shadcn `Card` (14 files; border `--text`; title 14px/600 `div`) and legacy `.card`
   (`/system/configuration` ×5, `GateChecklist`; border `--border`; h2 19px/400) (O-2). `ui/card.tsx:5-15` says the
   matching padding and radius keep the two "indistinguishable". They are not (O-1, O-2). Superseded, FX-8: OD-3 keeps
   the shadcn `Card`, with a hairline `--border` edge.
3. **Button:**
   - shadcn `Button`: primary 6px radius, 12px text, 36px tall.
   - legacy `button.primary`: 4px radius, 13px text, 36.14px tall.
   - `.linklike`.
   - raw `<button>` in the sort headers and the reveal toggle.
   - The legacy rule adds a `--border-strong` hairline to every shadcn button (O-4; superseded, FX-10).
4. **Form field:**
   - shadcn `Input`, `Label`, `Select`: 36px tall, 12px text (13px at <768px), `--border-strong` border, radius 6px.
   - legacy `<label><span>` with native `select`: 33px, 13px, `--border` border, `--panel-2` fill, radius 4px.
   - a native checkbox (findings).
5. **Skeleton:** `components/Skeleton.tsx` (sweep) and `ui/skeleton.tsx` (pulse, unused).
6. **Table:** `DataTable`, direct `Table` (`system`, `report`), a raw `<table>` (the scorecard, `candidates/[id]:325-360`),
   and `.table-scroll`.
7. **Metric:** a local helper three times (`MetricsPanel.tsx:122-140`, `portfolio:263-270`, `programme:94-101`), plus
   hand-written `<div class="metric">` blocks in `report` (×15) and `experiments/[ref]:156`.
8. **Formatter:**
   - `fmtAge` ×3: two return "—", one "no data" (partly superseded, FX-7: `lib/format.ts` holds the shared one;
     `/system` keeps its own copy).
   - Four money formatters (`fmtUsd`, `money()`, `usd()`, `Figure`).
   - Quantities at 4 or 6 decimal places (EC §9.2).
9. **Hidden text:** `.visually-hidden` and `sr-only`.
10. **Error banner:** `.banner-bad` (27 uses) and the unused `ui/alert` (`role="alert"`).
11. **Back link:** a ghost Button with `ArrowLeft` at the foot (4 pages) and a text link "← Programme" at the top
    (`report:111-116`).
12. **Confirm-to-commit:** a typed phrase in an Input ("ENABLE TRADING", "ENABLE PROGRAMME", "PROMOTE") and
    `window.prompt` ("RAISE AUTONOMY", `programme:213-216`).
13. **Intro paragraph:** `.subtitle` (7 pages), `m-0 text-base text-ink-muted` (6 pages), and `m-0 max-w-[68ch] …`
    (1 page).

Pages also keep their own status maps beside `StatusBadge`. `CANDIDATE_STATUS` and `CONCLUSION_STATUS` are each defined
twice (EC §5.1).

### 6.4 Compositions that recur

| Composition | Anatomy as rendered | Best seen in |
|---|---|---|
| Page header | h1 (23px/400) + one intro paragraph (13–14px `--muted`) + right-aligned actions or status chip, bottom-aligned | `shot:backtests-id__desktop__dark`, `shot:programme__desktop__dark` |
| Card stack | full-width Cards 12px apart; title row = `CardTitle` + count or chips + right-aligned action | `shot:dashboard__desktop__light` |
| Caveats before figures | warn / info / bad banners stacked above a metric grid, then assumption rows | `shot-code:crop-backtest-detail-top`; `shot:backtests-id__desktop__dark` |
| Refusal that names its remedy | gate header with "▲ N UNMET"; an info banner explaining the route forward; met and unmet rows each with detail and evidence; a disabled commit button with "Available once the gate passes." | `shot:programme-candidates-id--stage0-blocked__desktop__dark` |
| Typed confirmation | a reason or phrase Input + a destructive or primary Button; the commit stays disabled until the phrase matches (`system/page.tsx:212`, `programme/page.tsx:439`, `candidates/[id]/page.tsx:685`). The stopping actions differ: "Engage kill switch" stays disabled until a reason is typed (`system/page.tsx:193`); "Disable the programme" needs nothing and sends a default reason (`programme/page.tsx:195`, :421) | `/system` (ENABLE TRADING), `/programme` (ENABLE PROGRAMME), candidate (PROMOTE) |
| Board | nine 208px stage columns scrolling inside a Card; stages ≥4 in `--faint`; "? operator" chips on stages ≥5 | `shot:programme__desktop__dark` |
| Table in a card | Card title + filter + DataTable; the empty text inside the Card | `shot:backtests__desktop__dark`, `shot:programme-findings__desktop__dark` |

### 6.5 States observed per route

Each route's loading, empty, error, polling and lit-nav behaviour is in EC §10. The captured states are listed in
ES §1. The notable observations:

- **`/portfolio` has no loading state.** Until the first response it shows "—" in every figure and the empty-positions
  sentence (EC §6.2, §10).
- **`/system`:** a failing first request leaves "Loading system status…" on screen (`system:135`; EC §10). Superseded,
  FX-23.
- **The loading and API-unreachable states render no h1** (axe `page-has-heading-one`; ES §6.1).
- **A queued run polls every 2s.** Each poll logs a 404 from `POST /system/drain`, which is documented as normal (ES §4.4).
- **Polling cadences:** 2s (a running backtest), 5s (`/system`), 10s (`/programme`), 15s (`/portfolio`, candidate).
  `Skeleton.tsx:9` and `0ec084f:DESIGN.md:195` describe a single "every ten seconds" cadence (EC §8).
- **Enter submits nothing outside `/login`:** that is the only `<form>` in the app (EC §7.3).
- **A failed refresh leaves the last good figures on screen, unmarked** [derived from code, not captured]. `/system`,
  `/programme` and `/portfolio` keep their previous state when a poll throws and add a `.banner-bad` above it
  (`system/page.tsx:95-101`, :156; `programme/page.tsx:155-161`, :288; `portfolio/page.tsx:74-80`, :128). On `/system` that
  includes the kill-switch chip and the three gates. The `/portfolio` half is superseded (FX-5), and so is the `/system`
  half (FX-23); `/programme` is not.
- **`/portfolio` labels the previous account's figures with the new mode** [derived from code, not captured]. The
  "Mode" cell shows the requested mode from component state (`portfolio/page.tsx:166`), not the `mode` the API
  returns (`lib/api.ts:141`), and switching paper → live keeps the paper figures until the live request answers, or
  indefinitely if it fails (:65-80, :119-120), under the "Live account" banner (:138-144). Superseded, FX-5.

### 6.6 Motion observed

- **Tokens:** `--ease: cubic-bezier(0.16, 1, 0.3, 1)`, `--fast: 140ms`, `--base: 200ms` (`globals.css:128-130`). The legacy
  transitions use 140ms with `--ease` (EC §8).
- **Tailwind transitions** use 150ms and `cubic-bezier(0.4, 0, 0.2, 1)`. The sheet *declares* 500ms to open and 300ms
  to close (`ui/sheet.tsx:63`), but nothing moves: its slide and fade classes compile to nothing (below) and none of the
  properties it transitions changes, so the capture measured `animationName: none` and no running animation (EC §4.6,
  §8).
- **55 animation classes compile to nothing.** They sit in the vendored menu, select, sheet and tooltip, and
  `tw-animate-css` is not installed. The open sheet has `animationName: none` and no running animations (EC §8).
  Superseded, FX-22: the classes are gone, and nothing moves, as before.
- **Keyframes that exist:**
  - `sweep` (the skeleton, 1.4s);
  - `mark` (`.changed`, 200ms), which **no element ever receives**;
  - `fade`, the skeleton's reduced-motion alternative (EC §8).
- **Reduced motion:** `@media (prefers-reduced-motion: reduce)` sets every animation and transition to 0.01ms and gives
  the skeleton a 1.6s opacity fade (`globals.css:890-903`). The comment at :886-889 says "a changed value still needs to
  announce itself". No rule gives `.changed` an alternative, so under reduced motion it would last 0.01ms [derived].

### 6.7 Accessibility observed

- **Structure:**
  - `lang="en"`.
  - A skip link, first in the tab order.
  - Landmarks: `aside` (desktop), `header` (phone), `nav aria-label="Sections"`, one `main`, `footer` (EC §7.1).
- **axe-core 4.13.0, 102 runs** (ES §6.1):

  | Rule | Impact | Where |
  |---|---|---|
  | `definition-list` | serious | backtest detail: an `h3` inside `dl.assumptions` (`MetricsPanel.tsx:85-86`); superseded, FX-15 |
  | `scrollable-region-focusable` | serious | mobile only: table scrollers on `/system` and the candidate page; superseded, FX-17 |
  | `link-in-text-block` | serious | dark only: "Review them." and "Set it" on `/programme`, 1.98:1, no underline; superseded, FX-16 |
  | `heading-order` | moderate | dashboard, backtest detail, programme (h1 → h3); superseded, FX-15 |
  | `page-has-heading-one` | moderate | the loading and API-unreachable states; superseded on `/system` only (FX-23), and states are not captured, so not re-measured |
  | `empty-table-header` | minor | the action column on backtests and findings; superseded, FX-18 |

- **axe needs review** (ES §6.2):
  - `color-contrast`: 2,380 nodes axe could not judge. The census in 2.6 fills this gap.
  - `aria-prohibited-attr`: `aria-label` on a role-less `span.pill` (`GateChecklist.tsx:46-51`). Superseded, FX-9: the
    criterion's chip is `StatusBadge`, which carries its word and no `aria-label`; axe reported nothing there on
    2026-09-26 (§0).
  - `aria-hidden-focus`: behind the open sheet.
- **Keyboard** (ES §6.5):
  - Tab order is DOM order and never goes backwards.
  - 32 of 34 stops on `/` show an indicator. The date input's calendar stop shows **none**
    (`shot:kbd__dashboard__desktop__dark__22-date-picker--closeup`).
  - The shadcn ring measures 2.16–2.94:1, and 1.50–2.03:1 on destructive buttons. The legacy outline measures
    5.01–8.34:1. Superseded, FX-11: OD-3 keeps the outline on every control and removes the ring.
  - Nav links start their focus outline in their own text colour and transition it to accent; the 150ms transition
    is [derived] from `transition-colors` (EC §7.4).
- **Names and state** (EC §7.2, §7.5):
  - No `aria-sort` exists on any sortable header.
  - Error banners are not announced (no live region), and neither are "Saved." or "Stored…".
  - Meaning is carried by `title` attributes in two places (`backtests:154-158`, `GateChecklist.tsx:120`).
- **Target size under 24px at 390px** (WCAG 2.5.8; ES §6.6):
  - the phone header brand link;
  - the findings checkbox (14×14);
  - "Full register" (70.6×17.1);
  - "← Programme";
  - the candidate page's "H-0001" link.
  - SC 2.5.8's spacing and inline exceptions were not evaluated (ES §6.6), so this is a list of candidates, not of
    failures.
- **Charts:** the SVG is `role="img"` named "Equity curve from {first} to {last}" (`EquityChart.tsx:96-97`), with a
  `<figcaption>` that describes the encoding but no values (:163-172). There is no keyboard, pointer or tooltip access to
  a value (EC §9.3). On both pages that draw it, the headline figures also appear as text in a metric grid.
- **Focus, a third implementation:** the sheet's close button replaces the outline with `focus:ring-2 ring-offset-2`
  in `--accent` (`ui/sheet.tsx:78`), on `:focus` rather than `:focus-visible`. It was not reached by the keyboard walks
  (the sheet was not opened during them, ES §6.5), so it is unmeasured. Superseded, FX-11.
- **Links have no visible hover state:** `a:hover` sets only `text-decoration-thickness` (`globals.css:753`), and no
  link draws a decoration (EC §7.7) [derived]. Superseded, FX-16.
- **Dialog:** the mobile sheet renders no description; `aria-describedby` is null (EC §4.6). Superseded, FX-19.
- **Not tested:** mobile keyboard, screen readers (ES §6.5), the open sheet's focus containment (axe `aria-hidden-focus`
  is a needs-review item, ES §6.2).

---

## 7. Honesty rendering, observed against `repo:CLAUDE.md:96-131`

| Rule (line) | Where it is rendered | Where it is not, or is broken | Evidence |
|---|---|---|---|
| Sharpe with its standard error (:100) | `MetricsPanel`: "0.303 ± 0.226", a "not significant" `.badge` and a warn banner | Backtests list: non-significance is shown only by the `muted` colour (2.15:1 / 2.59:1 from the significant state) and a `title` tooltip (superseded, FX-4: stated as a word); the sort uses the bare estimate. Experiment page: Sharpe, SE and "Significant vs zero" sit in separate cells. | EC §6.1 |
| Deflate a searched Sharpe (:103) | nowhere | "deflat" and "overfit" appear nowhere in `web/src`; there is no walk-forward view; a walk-forward row prints as plain text | EC §6.1 |
| Unmeasured is never zero (:109) | `.no-data` words: "no data", "not measured" (scorecard) and 13 other phrasings | "0 bps" from `slippage_bps ?? 0` (`MetricsPanel.tsx:99`); "252 sessions/year" from `periods_per_year ?? 252` (:108) (both superseded, FX-2); "—" in 18 places, including a right-aligned numeric column (`system:50,309`); "—" meaning *false* once (`candidates:478`) (all but `/system`'s superseded, FX-7); loading shown as data on `/portfolio` | EC §6.2; O-6; probe P17 |
| Cost assumption (:113) | `MetricsPanel` "Slippage" and "Cost stress"; backtests list "Cost" column; run-form banner at 1× | no cost row on the candidate "Configuration" card | EC §6.4 |
| `effective_start` (:115) | `MetricsPanel` banner and row; chart warm-up band and label; experiment headline | backtests list (Window shows the requested window beside Return, Sharpe and Max DD; superseded, FX-4) | EC §6.5 |
| Session count (:118) | `MetricsPanel` "Annualised on {n} sessions/year"; experiment "Sessions per year" | backtests list (superseded, FX-4) | EC §6.6 |
| Synthetic labelled everywhere (:124) | run form, backtests list, `MetricsPanel`, pipeline card, hypothesis, candidate | backtest-detail header and chart (the banner sits below the chart); queued and failed synthetic runs; the experiment page (inside JSON only) | EC §6.3 |
| Kinder than the venue (:126) | shadow sessions: "{n} buy trimmed" (no plural form; superseded, FX-14) | backtests: `BacktestRun` and `BacktestMetrics` carry no underfunded field (`lib/api.ts:175-224`) | EC §6.7 |

Scaling and capping observed in the same survey:

- **Drawdown:** −0.0512 renders as "-0.051%" on `/programme/report` (`report/page.tsx:197` appends "%" to a fraction)
  and as "-5.12%" on `/portfolio` (EC §6.2; I-25). Superseded, FX-1.
- **CAGR** is −0.0316 (a fraction) on the experiment page and "2.04%" on backtest detail (O-26). Not among the
  adopting change's fixes; Q-22.
- **Fills:** "Fills (500)" is the API's default page limit; the same page's metric says 779 (O-16). Superseded, FX-3.

Other honesty observations:

- **Required and optional absences look the same.** On H-0003, 11 of 16 card rows render "—": the 10 missing
  *required* fields that gate 0→1 refuses on are indistinguishable from the optional "Known limitations" (ES §4.10;
  `hypotheses/[ref]/page.tsx:146-148`). OD-4 settles how each should read (`DESIGN.md` H-17). Superseded, FX-13.
- **Copy that misstates the system.** `/programme` says stages 4 and above cannot be reached because "shadow-mode
  operation is not built" (`programme/page.tsx:463-467`), and its docblock says "Stages 3 and up … cannot be reached
  yet" (:15-17). Stage 3 *is* shadow mode (`repo:src/programme/gates.py:49`), and `repo:CLAUDE.md:458-465` says the
  programme carries a candidate through shadow operation and that what is unbuilt is the stage 4–8 gates (EC I-41).
  Superseded, FX-6.
- **No overall score, said on the page.** The scorecard card reads "Seventeen dimensions and deliberately no overall
  score" (`candidates/[id]/page.tsx:312`), the rendering of the test in §1.
- **The specialist panel is not summarised.** "Nothing here is summarised into a consensus, and nothing here is read by
  the gate — only a finding has force" (`candidates/[id]/page.tsx:593-594`).
- **Defaults the page cannot see through** [derived from code, recorded while the adopting change was built]. The API
  substitutes two values before the page receives them: `repo:src/api/schemas.py` defaults `periods_per_year` to 252 and
  `n_fills` to 0. The page now renders a missing session count as "not measured" (FX-2), but the API never sends one
  missing, so that branch cannot fire. And a run the programme queues records no slippage (`repo:src/programme/tick.py`
  sets only the stress multiplier), while the worker fills in 5 bps (`repo:src/worker/backtest_job.py`,
  `cost.get("slippage_bps", 5.0)`); the page says so ("missing — not recorded on this run; the engine applied its own
  default, not zero") where it used to say "0 bps". Both are backend changes. Superseded, FX-24 and FX-25: the API
  sends `null` for a figure the run did not record, and the programme records the whole cost model on every run it
  queues. A run queued before that still records the multiplier alone, and still reads "missing".

### 7.1 Safety and control-plane rendering observed

Observations of how the page renders the safety rules and the programme's guarantees (§1). None of this is tested at
the page.

| What | Rendered | Source |
|---|---|---|
| The three live-order gates | three separate rows, each with its own chip, "no summary pill"; the third (deployment mode) is "not reported" and shown `? unknown` "rather than guessed from the two above"; an *open* gate is the `blocked` (loud) chip because open is the dangerous direction | `system/page.tsx:14-16`, :56-75, :230-255 |
| The kill switch | `✕ halted` (`blocked`) or `✓ enabled` (`settled`): here the *safe* state is the loud chip, the opposite of the gate rows' logic. Superseded, FX-12: OD-2 renders halted as a strong amber "stopped" and keeps red for an open gate | `system/page.tsx:163-164` |
| Stopping and starting | engaging the kill switch needs a typed reason; re-enabling needs the typed phrase ENABLE TRADING; disabling the programme is one click; enabling it needs ENABLE PROGRAMME; raising autonomy needs RAISE AUTONOMY through `window.prompt` | `system/page.tsx:190-215`; `programme/page.tsx:208-216`, :420-443 |
| Worker and runner liveness | from `stale`, never from the stored status ("only ever written 'alive'") | `components/StatusBadge.tsx:58-68`; `system/page.tsx:302-304`; `programme/page.tsx:312-313` |
| Autonomy ceiling | the requested and the effective stage are both stated after a change; "a stored request above [the hard cap] is never treated as the effective value" | `programme/page.tsx:26-30`, :225-232 |
| A refused promotion | the promote control stays disabled until the gate passes; a 409 shows "The gate has not passed…" and a "Still missing:" list | `candidates/[id]/page.tsx:165-176`, :240-249, :681-695 |
| Queued work | "Run a pass now" reports "Pass requested… the API never runs one inline" | `programme/page.tsx:245-251` |
| Paper only | every page's footer: "Paper trading only. Live execution requires three independent conditions… The database kill switch sits on top of all three and fails closed." | `layout.tsx:30-35` |

---

## 8. Patterns this UI must avoid

Each of these is already forbidden by an approved rule or a stated intent, cited. None is approved *as a design rule*
until the owner says so; the status of each source is in §1.

### 8.1 Visual anti-references (stated intent)

The repository names the looks this product must not wear. They are the brand's prohibited patterns in the article's
sense.

| Anti-reference | Stated in | Observed today |
|---|---|---|
| Navy-and-gold institutional finance: deep navy, gold accents, serif wordmark, "borrowed gravitas" | `repo:PRODUCT.md:54-56`; `0ec084f:DESIGN.md:229`; `globals.css:20` | not present: steel accent at hue 232, system sans wordmark (§2.1, §5) |
| Terminal-green-on-black, "Bloomberg cosplay": monospace green on pure black; "monospace numerals are correct here; the phosphor-terminal aesthetic is not" | `repo:PRODUCT.md:57-60`; `0ec084f:DESIGN.md:229-230`; `globals.css:20-21` | not present as a palette; but the most frequent text style is 12px monospace (§3.1) and sentences render in mono (O-14), which is the half of this anti-reference PRODUCT.md:59-60 allows only for numerals |
| Cream, sand, paper, any warm near-white body; warm-tinted neutrals | `repo:PRODUCT.md:61-63`; `0ec084f:DESIGN.md:29-31`, :230; `globals.css:45-47` | not present: light `--bg` is hue 255 at chroma 0.003 (`globals.css:143`) |
| GitHub Primer near-verbatim (`#0e1116`, `#4493f8`, `#3fb950`), and "the SaaS blue" | `globals.css:15-21`; `0ec084f:DESIGN.md:57`, :230-231; `repo:PRODUCT.md:65-68` | **partly present**: dark `--bg` still converts to Primer's `#0e1116` (2.7; Q-3) |

`DESIGN.md` C-11 carries these four. Other stated prohibitions carried by `DESIGN.md` rules: spinners
(`0ec084f:DESIGN.md:184-186`, M-8), bounce and elastic motion (`globals.css:125-127`, M-2), a card inside a card
(`globals.css:460-462`, S-10), `clamp()` type (`globals.css:99-102`, T-9).

### 8.2 Honesty patterns to avoid

The evidence shows each of these occurring today. The rendering rules that answer each one are in `DESIGN.md` §9–§10.

1. **An absent value dressed as a value.**
   - Seen: "0 bps" from `?? 0`, "252 sessions/year" from `?? 252` (`MetricsPanel.tsx:99,108`; superseded, FX-2); "—"
     beside right-aligned numbers (`system:309`); a loading page showing "—" and "No open positions"
     (`portfolio:149-165`).
   - Forbidden by: `repo:CLAUDE.md:109-112` (approved), `:300-301` (approved, test); OD-4 (approved: "Never a bare dash,
     never 0"); `repo:PRODUCT.md:72-76` and `0ec084f:DESIGN.md:180-182` (stated intent: "never as a dash").
2. **A figure without what it depends on — a Sharpe without its standard error, a return without its cost, window or
   session count.**
   - Seen:
     - the experiment page puts the Sharpe and its SE in separate cells, and the backtests list sorts on the bare
       estimate (EC §6.1);
     - the backtests list quotes Return, Sharpe and Max DD with no `effective_start` or session count (superseded,
       FX-4);
     - the synthetic label sits below the equity chart and is absent for queued or failed runs;
     - the candidate Configuration card has no cost row (EC §6.3-6.6).
   - Forbidden by: `repo:CLAUDE.md:100,113,115,118,124` (approved); `repo:PRODUCT.md:78-82` (stated).
3. **Meaning carried only by colour, hover or a tooltip.**
   - Seen: significance as `muted` colour (2.15:1) plus `title` (`backtests:150-158`; superseded, FX-4); in-text links
     distinguished by colour alone, 1.98:1 (axe `link-in-text-block`); "AI-authored" explained only in a `title`
     (`GateChecklist.tsx:120`).
   - Forbidden by: `repo:PRODUCT.md:101-111` (stated); `repo:docs/08-jev-integration.md:616` for Jev (planned: "never
     only in a tooltip").
4. **A capped, rescaled or reformatted number presented as the true one.**
   - Seen: "Fills (500)" beside "FILLS 779" (superseded, FX-3); drawdown 100× apart across two pages (superseded, FX-1);
     CAGR as a fraction on one page and a percent on another (O-16, O-26; EC §6.2).
   - Forbidden by: `repo:PRODUCT.md:46` "it does not round" and principle 2, :78-82 (stated); the honesty rules' premise,
     `repo:CLAUDE.md:98` (approved).
5. **The unflattering fact left off the page, or placed where it is least likely to be read.**
   - Seen: no surface shows a deflated Sharpe, PBO, walk-forward verdicts or backtest underfunded buys; the synthetic
     banner is below the chart; a gate recommendation lists unmet criteria by their *positive* descriptions, and a
     rejected candidate's scorecard still says "hold" (EC §6.1, §6.3, §6.7; O-23).
   - Forbidden by: `repo:CLAUDE.md:103-108,126-131` (approved); `repo:PRODUCT.md:83-86` "The uncomfortable state gets the
     attention" and :49-50 "A refusal always says what would satisfy it" (stated).

---

## 9. Questions for the owner

Each question was opened because the sources disagree or say nothing. `DESIGN.md` marks each affected rule INFERRED and
cites the question here. The owner answered seven of them on 2026-09-26 (§9.1); the answers are owner decisions OD-1
to OD-4, recorded in `DESIGN.md` §0.2 and `design/decision-log.md`, and the rules they settle are APPROVED there.

### 9.1 Answered

| # | Question, as asked | Why it was open (evidence at `0ec084f`) | Answer (owner decision, 2026-09-26) | What stays open |
|---|---|---|---|---|
| Q-1 | Where does the design system live, and does it replace the root `DESIGN.md`? The draft proposes `web/` (`CLAUDE.md`, `REFERENCE.md`, `DESIGN.md`, `design-tokens.json`, `examples/`), with the root `DESIGN.md` reduced to a pointer. | Root `DESIGN.md` exists; the root `CLAUDE.md` never references it; two `DESIGN.md` files would be two sources. | In `web/`: `web/REFERENCE.md`, `web/DESIGN.md`, `web/design-tokens.json`, `web/examples/`, and a short routing rule in `web/CLAUDE.md`. The root `DESIGN.md` becomes a pointer to `web/DESIGN.md` (OD-1). | — |
| Q-28 | Who owns tokens, components, examples and the decision log? | `repo:PRODUCT.md:9` describes one operator; `repo:docs/08-jev-integration.md:4` names Quentin Casares as owner of that document; the repository is `github.com/Qcasares/trader` (`git remote`). No design owner is recorded. The article splits the review of REFERENCE and DESIGN — design owns visual truth, engineering owns feasibility — and with one operator both fall to one person unless a second reviewer is named. | The owner, Quentin Casares, approves design rules; a rule stays INFERRED until the owner approves it in the decision log (OD-1). | No second reviewer is named, so the article's split (design owns visual truth, engineering owns feasibility) falls to one person. |
| Q-30 | On a safety control, which state gets the loud chip? | `/system` makes an *open* live-order gate `blocked` because open is the dangerous direction (`system/page.tsx:56-72`), but makes the kill switch's *halted* (safe) state `blocked` and *enabled* `settled` (:163-164). `globals.css:88` defines `--blocked` as "refused, failed, halted"; `repo:PRODUCT.md:83-86` says the uncomfortable state gets the attention. Both readings are defensible; the page uses both (7.1). | "Red (the blocked colour) is reserved for 'live money reachable': a live-trading gate open, real money able to move. A halted kill switch is a safe state and renders as a strong amber 'stopped' — prominent, not alarming." (OD-2) | Whether "reserved" reaches past the safety controls: Q-33. |
| Q-4 | Which card is canonical? Its border (`--border` hairline, or the text colour it renders today), its title (14px/600 `div`, or 19px/400 `h2`), its padding. | Two surface systems, 0px joins between them (2.5, 6.3 item 2, 4.2). | The shadcn `Card`, with a hairline border (OD-3: "shadcn components are canonical … One card (hairline border)"). Its padding is the shadcn card's. | The title's element and weight: `DESIGN.md` T-5 (a real `h2`) and Q-9. |
| Q-5 | Which status chip is canonical: lowercase mono with full radius, or UPPERCASE sans with 10px? | Two chip systems on one page (3.6, 6.3 item 1). | One chip style, and shadcn components are canonical (OD-3). The chip is therefore `StatusBadge`, the shadcn-based one, whose shipped treatment is lowercase as written, mono, fully round, with a 40 % signal edge. | — |
| Q-6 | Which focus indicator: the 2px outline at 2px offset, or the border plus ring (and at what alpha)? | `0ec084f:DESIGN.md:219-220` says one ring; two render; the ring measures 1.50–2.94:1 (2.6, 6.7). | "On every control the accent focus outline that already passes 3:1 non-text contrast (the shadcn ring at 1.5–2.9:1 goes)" (OD-3): the 2px accent outline at 2px offset. | The date input's internal stops are drawn by the browser; whether the outline reaches them is for the next keyboard walk (`design/checks.md` (c)). |
| Q-10 | What is the absence vocabulary, word by word? | `repo:CLAUDE.md:109-111` fixes "not measured" (scorecard) and "no data" (report); 13 other phrasings and "—" also render (EC §6.2). | "An absence says why: 'not measured' for a metric never computed, 'no data' for an observation that never arrived, 'missing' plus the reason for a required field. Never a bare dash, never 0." (OD-4, which also settles `DESIGN.md` H-17.) | The words' treatment, which OD-4 did not settle: `Absent` sets them as the `.no-data` label (11px sans capitals, `--muted`, `DESIGN.md` §5.1), which in a metric grid sits close to the key above it. |

The observations each question was asked on stay in §2-§7 as measured at `0ec084f`, marked superseded where the
adopting change acted on the answer (§0).

### 9.2 Open

**Answer these first; each blocks a rule or a component:** Q-2 (source of truth), Q-7 and Q-8 (filled controls), Q-29
(control text size), Q-33 (how far red is reserved), Q-22 (percent or fraction) and Q-3 (the Primer background). The
rest can wait for the pilot (`design/checks.md` (e)).

| # | Question | Why it is open (evidence) |
|---|---|---|
| Q-2 | Is `globals.css` the source of truth, with the JSON as a tested mirror, or should the JSON generate the CSS? | `0ec084f:DESIGN.md:6-7` names the CSS. The article says "the token file owns exact machine values". |
| Q-3 | Is dark `--bg` = `#0e1116` intended? | It is the Primer value `globals.css:16` says was retired; `repo:PRODUCT.md:65-68` still describes the palette as Primer "being replaced" (2.7). Primer is one of the stated anti-references (8.1). |
| Q-7 | Does a disabled primary keep its fill? | `0ec084f:DESIGN.md:163` says no; both implementations keep it (2.7). |
| Q-8 | Are stopping actions filled? | `0ec084f:DESIGN.md:159-162` says the committing action is the only filled control. Measured: filled destructive "Disable the programme", "Engage kill switch", and "Reject" beside a filled "Promote" (I-23). |
| Q-9 | Should h1 be heavier than it is? | The page h1 renders at 400, lighter than every 600 `CardTitle` (3.5). |
| Q-11 | May prose render in monospace? | Assumption values and hypothesis sentences are mono (O-14); `0ec084f:DESIGN.md:129-132` says only `.num` and `.mono` cells are. |
| Q-12 | How far apart are page sections? | Rendered: 12px everywhere (4.2). `0ec084f:DESIGN.md:139-140`: "sections breathe at `--s-6`" (32px). |
| Q-13 | Does 6px join the scale, or migrate to 4 or 8? | 6px is the second most common gap (246) and is not on the 4px scale (4.1). |
| Q-14 | Should line-heights become tokens, and at which values? | Three or four line-heights per size render (3.4). |
| Q-15 | What is the content width? | `<main>` has no max-width (1,184px at 1440). `globals.css:368-371` says "the measure moved to the shell"; `login/page.tsx:62-64` cites a "680px-wide" column that does not exist (4.4). |
| Q-16 | Should mobile inputs be 16px? | They render at 13px (`text-base`); iOS Safari zooms into inputs under 16px on focus (ES §9 P-13). This is a token change, and part of Q-29. |
| Q-17 | Implement `.changed` or drop it from `0ec084f:DESIGN.md:193-197`? | 6.6. The question's first half — install `tw-animate-css` or delete its 55 dead classes — was settled in code by the adopting change, which deleted them (FX-22): nothing moved before or after, and installing the package would have added a 500ms sheet slide against `DESIGN.md` M-1's 250ms ceiling. `.changed` is still applied nowhere. |
| Q-18 | Does "a card inside a card is always a mistake" cover the metric grid and the pipeline cards? | `globals.css:460-462` resets only `.card .card`; both nested boxes render (I-19). |
| Q-19 | Should there be a manual theme switch? | OS preference only (2.4). |
| Q-20 | Where are the evidence records and screenshots kept once adopted: committed, or regenerated by `design/checks.md` (b)? | The 184 PNGs and two evidence files live outside the repository today, and this file cites them (see "How to read the citations"). |
| Q-21 | Is "nothing" acceptable for an autonomy ceiling of 0? | `repo:CLAUDE.md:110-111` says "keep a genuine zero as a zero"; `programme:323-325` renders 0 as "nothing" (EC §6.2). |
| Q-22 | Percent or fraction, per quantity? | CAGR, volatility and drawdown are each shown both ways (7). Recorded with the owner decisions as already following from the honesty rules: a percentage is formatted from the stored fraction by one shared formatter, never by appending "%" to a raw fraction (the report's drawdown fix, FX-1). That settles the mechanism, not which quantities display as percentages. |
| Q-23 | Should the Jev UI rules enter `DESIGN.md` now, or at phase E? | Planned (`repo:docs/08-jev-integration.md:612-635`, with the honesty rules at :585-610 and the lane limits at :539-544); no Jev UI exists, but phase B modules are being built on another branch (§1). `DESIGN.md` §10 now carries J-1 to J-21. |
| Q-24 | May vendored `components/ui` files be edited in place? | `card.tsx:5-16` is retuned; `shadcn add` would overwrite it (6.2). |
| Q-25 | Bridge `--z-*` into Tailwind, or accept `z-50`? | The named scale is unused except by the skip link (4.7). |
| Q-26 | What are the wordmark's clear space and minimum size, and may it wrap? | Nothing specifies them; it wraps in the mobile sheet title (5). |
| Q-27 | Should long tables be paginated? | Backtest detail is 8,708px tall, almost all of it a 200-row fills table (ES §4.4). |
| Q-29 | What size is control text: 12px or 13px, and 16px on phones? | `0ec084f:DESIGN.md:116` says inputs and buttons are 13px; legacy controls are 13px; shadcn `Button`, `Label` and desktop `Input` render 12px, phone `Input` 13px (3.2). `design/notes.md` §5.3 records 12px as shipped and E-4 asks for no input under 13px, so the two cannot both hold. Q-16 is the phone half. OD-3 makes the shadcn controls canonical, but says nothing about their size, so this stays open. |
| Q-31 | Should the values Tailwind supplies by default become declared tokens? | Breakpoints (40/48/64rem, `compiled:2528`, :2536, :2557), `--spacing` 0.25rem, the `text-xs/sm/base` line-heights and the 150ms default transition shape the UI but are not declared in `globals.css`, so `design-tokens.json` does not hold them and no check guards them (EC §1.3). |
| Q-32 | Are the 33 allow-list entries left in `test_design_tokens.py` (31 arbitrary values in 34 places, 2 palette colours) accepted as the debt? | The article asks for "an approved exception"; they are recorded debt with reasons, and no owner has accepted them (`DESIGN.md` D-ALLOW-1). There were 38 at `0ec084f`; the adopting change removed the four shadcn focus rings (FX-11) and the one colour literal, `button.danger`'s white (FX-10). |
| Q-33 | Does OD-2's "reserved" reach past the safety controls? | OD-2 answers Q-30, which asked about safety controls, and settles them. Read alone, "reserved" would also take red from the other things `/system` shows in it, failed or expired jobs (`jobStatus`) and a stale heartbeat (`livenessStatus`, `components/StatusBadge.tsx:52-68`), and from every refusal and failure elsewhere (unmet criteria, failed runs, blocking findings, the destructive Reject). Moving those to amber would render "failed" in the colour of "not measured", which `DESIGN.md` C-4r keeps apart. Until the owner answers, `DESIGN.md` C-5 keeps them `blocked`. One of them moved and moved back: a gate's summary chip ("3 unmet") was the amber `.pill-warn`, turned `blocked` on its way onto `StatusBadge`, and is amber again as the `caution` state (▲), a gate not yet passed, while each unmet criterion in it stays `blocked`, measured and refused (C-5; `GateChecklist.tsx`, `promotionGateStatus`). Whether a gate carries red, and whether the state is called `caution`, are this question's. So is a specialist's `concern` verdict, which still draws `unknown` ("?") as it did at `0ec084f`: a known verdict in the chip for no measurement. |
| Q-34 | Does the stopped state keep tokens of its own, `--stopped` (`oklch(0.800 0.140 78)`, `#efb146`) and `--stopped-ink` (`oklch(0.185 0.020 78)`, `#181208`)? | `DESIGN.md` C-12r asked for the amber of `--unknown` "unless the owner approves a token of its own"; the adopting change shipped one, PROPOSED, because light `--unknown` is darkened for text and reads brown as a fill. One value in both schemes: ink on the plate 9.79:1; the plate against `--panel` 9.09:1 in dark but 1.90:1 in light, so there the word and the ■ glyph carry the state, not the plate's edge. |

---

## Appendix A. The former root `DESIGN.md`, verbatim at `0ec084f`

**Status: historical** (§1). This was the repository's design document until the adopting change reduced it to a
pointer (OD-1). It is kept here, unedited and with its original line numbers, because the rules in `DESIGN.md` cite it
as stated intent (`0ec084f:DESIGN.md:N` is line N below), and because its reasons — why the default is dark, why
attention is carried by chroma, why `--unknown` is amber and not grey — are still the reasons. It is not a set of rules:
where it disagrees with `DESIGN.md`, the rule or open question there governs, and §1 lists the thirteen statements the
rendering at `0ec084f` contradicts. The same text is `git show 0ec084f:DESIGN.md`.

```text
  1  # Design
  2
  3  Visual system for the systematic trading control plane. Strategy, users and
  4  principles live in [PRODUCT.md](PRODUCT.md); this file is how it looks and why.
  5
  6  Source of truth is `web/src/app/globals.css`. If the two disagree, the
  7  stylesheet is right and this file is stale.
  8
  9  ## Theme
 10
 11  **Dark by default, light supported.** Chosen from one sentence about the room
 12  rather than from taste: *one person at a desk, late, in a room lit by the
 13  screen, reading a table of numbers to decide whether a month of compute
 14  produced anything real.* A screen-lit room and a long session force dark; the
 15  light theme exists because daytime happens and is a full peer, not an
 16  afterthought.
 17
 18  Colour strategy: **restrained**. Tinted neutrals plus one accent that never
 19  exceeds about a tenth of the surface. The signal colours below are not part of
 20  that budget; they appear only where there is a state to report.
 21
 22  ## Colour
 23
 24  OKLCH throughout, so lightness is perceptual and the two themes can be reasoned
 25  about in the same units.
 26
 27  ### Surfaces
 28
 29  Graphite with a small chroma toward the accent's own hue (255), not the default
 30  drift toward warm. Warm-tinting neutrals "because the brand feels that way" is
 31  the move every project makes at once.
 32
 33  | Token | Dark | Light | Use |
 34  |---|---|---|---|
 35  | `--bg` | `0.178 0.011 255` | `0.977 0.003 255` | Page |
 36  | `--panel` | `0.221 0.013 255` | `1 0 0` | Cards, top bar |
 37  | `--panel-2` | `0.262 0.015 255` | `0.958 0.004 255` | Inputs, pills, row hover |
 38  | `--border` | `0.322 0.016 255` | `0.885 0.006 255` | Hairlines |
 39  | `--border-strong` | `0.412 0.018 255` | `0.800 0.010 255` | Buttons, table head rule |
 40
 41  ### Ink
 42
 43  | Token | Dark | Light | Use |
 44  |---|---|---|---|
 45  | `--text` | `0.955 0.004 255` | `0.240 0.014 255` | Body |
 46  | `--muted` | `0.723 0.013 255` | `0.487 0.016 255` | Secondary prose, labels, placeholders |
 47  | `--faint` | `0.645 0.012 255` | `0.528 0.014 255` | Unreachable lifecycle stages |
 48
 49  `--faint` still clears 4.5:1. It is de-emphasis, not decoration, and everything
 50  it is used on is read.
 51
 52  ### Accent
 53
 54  `0.740 0.093 232` dark, `0.520 0.110 232` light. A low-chroma steel.
 55
 56  Reserved for primary actions, current selection and focus. Never decorative.
 57  Deliberately not the SaaS blue this project's palette used to be borrowed from,
 58  and low enough in chroma to sit beside the signal colours without competing.
 59
 60  ### Signal
 61
 62  Three states, and the ordering is the point.
 63
 64  | Token | Dark | Light | Chroma | Means |
 65  |---|---|---|---|---|
 66  | `--blocked` | `0.725 0.185 30` | `0.404 0.190 30` | highest | Refused, failed, halted |
 67  | `--unknown` | `0.800 0.140 78` | `0.464 0.130 70` | middle | Not measured, indeterminate |
 68  | `--settled` | `0.660 0.072 158` | `0.524 0.075 158` | lowest | Met, passed, alive |
 69
 70  **Attention is carried by chroma, not lightness.** `--blocked` is the most
 71  saturated thing on any screen and `--settled` the least, which inverts the usual
 72  dashboard instinct where success is the bright colour. An operator opens this to
 73  find out what is wrong; a page where "passed" shouts and "refused" murmurs is
 74  optimised for the wrong reader.
 75
 76  **Lightness is spent on accessibility instead.** The three are held at least
 77  0.06 apart in L, so they remain distinguishable in greyscale and under
 78  protanopia and deuteranopia. Hues additionally sit on the blue/orange axis,
 79  which is the one that survives both.
 80
 81  Every value was solved for, not chosen. Each clears 4.5:1 against `--panel-2`,
 82  which is what a pill actually renders on. The first draft tinted each pill with
 83  16% of its own hue; that coupled the contrast target to the lightness target and
 84  made them jointly unsatisfiable on dark, with `blocked` and `settled` both
 85  pinned near L 0.70. Three values failed a measured check. Dropping the tint for
 86  a neutral chip freed lightness entirely and is quieter on a status-dense page
 87  besides.
 88
 89  ### `--unknown` is not grey, and that is the most important decision here
 90
 91  An unmeasured figure used to render in the same muted grey as "nothing to say
 92  about this". Those are different facts. The system's first principle is that
 93  absence is a state rather than a zero, and rendering the most important honest
 94  state in the quietest colour available made it the easiest thing on the page to
 95  miss.
 96
 97  The same amber marks model-authored content (`.badge`). The link is deliberate:
 98  a model-drafted hypothesis card and an unmeasured metric are both *not
 99  established fact*, and they should read as the same category of thing.
100
101  ## Typography
102
103  System stacks. `ui-sans-serif` for everything, `ui-monospace` for figures.
104
105  A product UI does not need a display face. One well-tuned sans carrying
106  headings, labels, buttons and prose is one fewer thing that can drift out of
107  tune, and the register permits it.
108
109  **Fixed rem, never `clamp()`.** Users read this at one DPI at one desk. A
110  heading that resizes with the viewport looks worse inside a panel, not better.
111
112  | Token | Size | Use |
113  |---|---|---|
114  | `--t-xs` | 11px | Uppercase labels, metric keys, pills |
115  | `--t-sm` | 12px | Table cells, dense metadata |
116  | `--t-base` | 13px | Secondary prose, inputs, buttons |
117  | `--t-body` | 14px | Body |
118  | `--t-md` | 16px | h3, metric values |
119  | `--t-lg` | 19px | h2 |
120  | `--t-xl` | 23px | h1 |
121
122  Ratio about 1.2. Tighter than a marketing page on purpose: there are many type
123  roles on these screens and exaggerated contrast between them reads as noise.
124
125  `font-variant-numeric: tabular-nums` on every figure. Numbers here are read down
126  a column and compared with the one above; proportional digits turn a glance into
127  a reading task.
128
129  **Tables set in sans, not monospace.** Only `.num` and `.mono` cells opt into
130  the monospace face. A table set entirely in monospace turns every label and
131  sentence inside it into pseudo-data: "Risk-adjusted return" renders with a
132  hyphen the width of an en dash and reads as a formula.
133
134  Prose is capped at 65–75ch (`.subtitle`, `.gate-criterion-detail`, `td.prose`).
135  Tables and dense metadata are exempt and run as wide as they need.
136
137  ## Spacing and layout
138
139  4px base, `--s-1` through `--s-7`. Varied deliberately: sections breathe at
140  `--s-6`, table rows hold at `--s-2`.
141
142  Cards are used where a boundary is real and not as the default container. A card
143  inside a card is reset to nothing, because the second border says "separate
144  thing" about something that is part of the first.
145
146  The pipeline board scrolls inside its own container rather than widening the
147  page. Nine stage columns never fit a laptop, and a body that scrolls sideways
148  makes every other page feel broken. Stages the system cannot yet evidence are
149  dimmed rather than hidden, so the lifecycle reads as one thing with an end the
150  operator has not reached.
151
152  Z-index is a named scale: `--z-sticky` 100 → `--z-dropdown` 200 →
153  `--z-backdrop` 300 → `--z-modal` 400 → `--z-toast` 500. Never an arbitrary 999.
154
155  ## Components
156
157  Every interactive element has default, hover, focus, active and disabled.
158
159  **Buttons carry the asymmetry between stopping and starting.** The committing
160  action is the only filled control on a screen (`button.primary`, accent fill);
161  everything else is an outline. The shape says which way is which before the
162  label is read, which is the visual half of a rule the API already enforces.
163  Disabled controls never keep a saturated fill: a disabled button that still
164  looks primary invites the click it is about to refuse.
165
166  **Pills are neutral chips.** `--panel-2` background with coloured text, a
167  coloured border and a leading glyph. Colour is never the only channel:
168
169  | State | Glyph | Colour |
170  |---|---|---|
171  | met, pass, alive | `✓` | `--settled` |
172  | unmet, fail, blocked | `✕` | `--blocked` |
173  | caution, N unmet | `▲` | `--unknown` |
174  | not measured, unknown | `?` | `--unknown` |
175  | neutral, open | `•` | `--muted` |
176
177  Each glyph is set with an empty alternative text (`content: "✓" / ""`) so a
178  screen reader announces the label rather than the decoration.
179
180  **Absent figures say so.** `.no-data` renders the words rather than a dash:
181  beside right-aligned numbers a dash reads as a minus sign, and an absent
182  measurement must never be mistakable for a value.
183
184  **Skeletons, not spinners.** A skeleton in the shape of what is arriving tells
185  an operator how much of it there is; a spinner tells them only that something is
186  happening.
187
188  ## Motion
189
190  150–250ms, `cubic-bezier(0.16, 1, 0.3, 1)`. Exponential ease-out only. No
191  bounce, no elastic: a control panel that springs is a control panel you distrust.
192
193  Motion reports a change and does nothing else. There are no page-load sequences.
194  The two animations that exist are the skeleton sweep and `.changed`, which marks
195  a value that has just updated: on a page that polls every ten seconds, a figure
196  changing with no acknowledgement is a figure the operator has to diff against
197  memory.
198
199  `prefers-reduced-motion` gets an alternative rather than a removal. The skeleton
200  becomes a steady opacity pulse, which still reads as "loading" without
201  translating anything across the screen.
202
203  ## Accessibility
204
205  WCAG 2.2 AA, verified by computation rather than by eye. Every pair below was
206  measured; three of the first-draft values failed and were solved for.
207
208  | Pair | Dark | Light |
209  |---|---|---|
210  | `--text` on `--bg` | 16.6 | 15.4 |
211  | `--muted` on `--panel` | 7.0 | 6.3 |
212  | `--faint` on `--panel-2` | 4.7 | 4.7 |
213  | accent link on `--bg` | 8.3 | 5.0 |
214  | `--accent-ink` on accent | 8.2 | 5.3 |
215  | `--blocked` pill | 5.7 | 6.4 |
216  | `--unknown` pill | 8.1 | 6.4 |
217  | `--settled` pill | 5.1 | 4.6 |
218
219  One focus ring, applied via `:focus-visible` to every interactive element,
220  2px accent at 2px offset. Never suppressed without replacement.
221
222  Placeholders use `--muted`, not `--faint`. The first draft used the latter and
223  measured 3.32:1, which is the exact failure the surrounding comment claimed to
224  prevent.
225
226  ## Anti-references
227
228  Recorded in PRODUCT.md and repeated here because they are visual decisions:
229  navy-and-gold institutional finance, terminal-green-on-black, and cream or
230  warm-neutral paper backgrounds. The palette this replaced was GitHub Primer
231  near-verbatim.
```
