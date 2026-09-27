# Decision log — `web/DESIGN.md`

<!-- Moved here from DESIGN.md §12 on 2026-09-26, the table verbatim, so that the contract an agent reads before every UI change
     carries its rules and not their history. Read this file when changing a rule, a token or a pattern (CLAUDE.md).
     repo:tests/unit/test_design_tokens.py reads the table below and fails if a rule's status here differs from its
     status in DESIGN.md, or if an APPROVED row names no owner, date or basis. -->

Section numbers (§n) are `DESIGN.md`'s; `REFERENCE §n`, `Q-n` and `FX-n` point into `REFERENCE.md`; `OD-n` is an owner
decision, quoted below and summarised in `DESIGN.md` §0.2. Paths are relative to `web/` unless prefixed `repo:`, and code citations are to
commit `0ec084f`, as in `DESIGN.md`.

One row per rule defined in `DESIGN.md`, and one per owner decision. **Date** is when the rule was adopted: for an owner
decision, the day it was answered; for a rule adopted from `repo:CLAUDE.md` or a test, the date of the commit that
introduced its text (`git log -S`); for an INFERRED rule, the day it was recorded. **Owner** is who approved it:
Quentin Casares, for an owner decision (OD-1), and for a rule adopted from `repo:CLAUDE.md` or a test as the owner of
the repository that holds it (`repo:docs/08-jev-integration.md:4`). An INFERRED row has no owner until one approves it.
To approve one, the owner's decision is recorded as an OD-n row (its basis says where it was given: "owner decision, in
session", or in the review of a pull request), and the rule's row here and the rule itself in `DESIGN.md` change to
APPROVED, citing it. `DESIGN.md` §13 (a) fails if the two statuses differ, or if an APPROVED row names no owner, no date
or no such basis.

## Owner decisions, verbatim

Answered by the owner, Quentin Casares, in the session of 2026-09-26, through a structured question, and quoted as
decided. Each has an APPROVED row below, and each rule it settles is APPROVED in `DESIGN.md`.

- OD-1, **Ownership and location** (answers Q-28 and Q-1): "The owner approves design rules. The design system lives in
  `web/`: `web/REFERENCE.md`, `web/DESIGN.md`, `web/design-tokens.json`, `web/examples/`, and a short routing rule in
  `web/CLAUDE.md`. The root `DESIGN.md` becomes a pointer to `web/DESIGN.md`. Rules stay INFERRED until the owner
  approves them in the decision log."
- OD-2, **Alarm state on `/system`** (answers Q-30): "Red (the blocked colour) is reserved for 'live money reachable':
  a live-trading gate open, real money able to move. A halted kill switch is a safe state and renders as a strong amber
  'stopped' — prominent, not alarming."
- OD-3, **Canonical components** (answers Q-4, Q-5 and Q-6): "shadcn components are canonical; the legacy base-layer
  rules that restyle them are scoped away. One card (hairline border), one chip style, and on every control the accent
  focus outline that already passes 3:1 non-text contrast (the shadcn ring at 1.5–2.9:1 goes)."
- OD-4, **Absent values** (answers Q-10 and settles H-17): "An absence says why: 'not measured' for a metric never
  computed, 'no data' for an observation that never arrived, 'missing' plus the reason for a required field. Never a
  bare dash, never 0."

Answered by the owner, Quentin Casares, in the session of 2026-09-27, through four structured questions put when a
generic frontend taste skill (`design-taste-frontend`) was invoked on this UI and its directives met this contract,
which sends such a conflict to the owner (`web/CLAUDE.md`). Each is quoted as asked and as answered: the question, then
the label of the option chosen and its description. Each has an APPROVED row below, and each rule it settles is
APPROVED in `DESIGN.md`. What the skill asked that was decided under the rules rather than asked, and why, is
`design/notes.md` §0.5.

- OD-5, **Typeface** (settles T-10). Question: "Typeface: the web contract (T-10) says system font stacks, no web
  font. The skill wants Geist + Geist Mono for dashboards (it bans Inter, which we don't use). Which should the UI
  use?" Answer: "Geist + Geist Mono (Recommended)" — "Self-hosted from the geist npm package through next/font: no
  request to any third party, and every OS renders identical glyphs, which also makes screenshot comparisons stable
  across machines. Figures stay tabular. Replaces T-10."
- OD-6, **Motion** (settles M-3, M-10, M-11). Question: "Motion: the contract (M-3) says motion only reports a change,
  no page-load choreography. The skill (intensity 6) wants spring physics, staggered reveals and perpetual
  micro-animations. I will not put movement on the kill switch or live gates, or animate anything in a way that
  implies liveness (a dead worker must look dead). Within that, how much motion?" Answer: "State-bound motion
  (Recommended)" — "CSS only, no new dependency: a tactile press on buttons, a short staggered fade-in when a list
  first loads (with a reduced-motion alternative), and a live dot that pulses only while the worker's heartbeat is
  fresh and goes still when it is stale. Nothing loops unless it reports real state." The preview the owner saw:
  `.status-live[data-fresh=true]` breathe 2.4s `var(--ease)` infinite; stale = still; `button:active`
  `translateY(1px)`; list children rise 200ms `var(--ease)` with `animation-delay: calc(var(--i) * 40ms)`;
  `prefers-reduced-motion`: opacity only.
- OD-7, **Layout** (settles S-7 and L-4's Summary grid). Question: "Surfaces and layout: the contract keeps hairline
  cards (C-8a, approved) and no shadows (S-7). The skill wants asymmetric bento grids, large radii and soft tinted
  shadows. What should summary pages (System, Programme, Portfolio) look like?" Answer: "Asymmetric, hairline
  (Recommended)" — "Keep hairline cards, 6px radius and no shadows; lay summary pages out as an asymmetric grid (e.g.
  2fr/1fr) grouping what belongs together. Data pages keep full-width tables. Phones fall back to one column."
- OD-8, **Density** (settles S-2, and answers Q-12). Question: "Density: today tables are 12px, body 14px, headings
  19-23px (a dense control plane). The skill's baseline is density 4, a daily-app feel: larger text and more space.
  Which?" Answer: "Dense data, airier prose (Recommended)" — "Tables, figures and metadata stay 12-13px so a screen
  holds a full job list; body prose moves to 15px with more space between sections; hierarchy by weight and colour,
  not size." The preview the owner saw said "Section gap 16px -> 24px", and misstated the current value: S-2 put page
  sections 12px apart, and 16px is the page header to the first section (S-3). The answer's own words ask only for
  "more space between sections"; the 24px is the target the preview named, and the option the owner chose carried it.
  So page sections are 24px apart — but the owner was shown a step from 16px to 24px, half again, and what ships is a
  step from 12px, double. That difference is the owner's to settle, and is put to them as Q-37.

## The log

| ID | Rule (short) | Status | Date | Owner | Basis | Reason |
|---|---|---|---|---|---|---|
| OD-1 | Ownership and location: the owner approves; the system lives in `web/`; the root `DESIGN.md` is a pointer | **APPROVED** | 2026-09-26 | Quentin Casares | owner decision, in session (Q-28, Q-1) | answered in session |
| OD-2 | Red is reserved for "live money reachable"; a halted kill switch is a strong amber "stopped" | **APPROVED** | 2026-09-26 | Quentin Casares | owner decision, in session (Q-30) | answered in session |
| OD-3 | shadcn canonical; legacy base rules scoped away; one card (hairline), one chip; the accent focus outline on every control | **APPROVED** | 2026-09-26 | Quentin Casares | owner decision, in session (Q-4, Q-5, Q-6) | answered in session |
| OD-4 | An absence says why: "not measured", "no data", "missing" + reason; never a bare dash, never 0 | **APPROVED** | 2026-09-26 | Quentin Casares | owner decision, in session (Q-10, H-17) | answered in session |
| OD-5 | Typeface: Geist and Geist Mono, self-hosted from the `geist` package through `next/font`; figures stay tabular | **APPROVED** | 2026-09-27 | Quentin Casares | owner decision, in session (T-10; the taste skill) | answered in session; its reason, "every OS renders identical glyphs", fails for ✓, ✕ and ■, which neither face carries (Q-36) |
| OD-6 | Motion: state-bound, CSS only — a press, a first-load stagger with a reduced-motion alternative, a live dot only while the heartbeat is fresh; nothing loops unless it reports real state | **APPROVED** | 2026-09-27 | Quentin Casares | owner decision, in session (M-3; the taste skill) | answered in session, within the question's own condition: no movement on the kill switch or the live gates |
| OD-7 | Layout: hairline cards, 6px radius, no shadows; summary pages an asymmetric 2fr/1fr grid; data pages full width; phones one column | **APPROVED** | 2026-09-27 | Quentin Casares | owner decision, in session (C-8a, S-7; the taste skill) | answered in session |
| OD-8 | Density: tables, figures and metadata 12–13px; body prose 15px; sections 24px apart; hierarchy by weight and colour | **APPROVED** | 2026-09-27 | Quentin Casares | owner decision, in session (Q-12; the taste skill) | answered in session; the 24px is the chosen option's preview target, and that preview misstated today's section gap as 16px, where S-2 had 12px (Q-37) |
| D-PREC | Precedence order for conflicting sources | INFERRED | 2026-09-26 | — | the article ("current tokens beat screenshots for exact values") | stops a shipped defect becoming doctrine |
| C-1 | Colour only through tokens; allow-list for the rest | INFERRED | 2026-09-26 | — | REFERENCE §2.3; `globals.css:166-172` | zero literals at `0ec084f`; keep it so |
| C-2 | Product utility names in product code | INFERRED | 2026-09-26 | — | EC §1.3 | one vocabulary per layer |
| C-3 | shadcn `accent` is not the brand | INFERRED | 2026-09-26 | — | `globals.css:183-189` | avoids brand-filled hovers |
| C-4 | A missing measurement is `unknown`, not `fail` | **APPROVED** | 2026-08-03 | Quentin Casares | `repo:CLAUDE.md:301`; `test_programme_scorecard.py::TestUnknownIsNotFail` (ee547f4) | repo rule, tested on the scorecard's rows |
| C-4r | …rendered as the `unknown` chip, never `blocked`, never as "stopped" | INFERRED | 2026-09-26 | — | `StatusBadge.tsx:14-25` | the test does not read the page |
| C-5 | Six statuses, fixed meanings; on a safety control `blocked` means live money reachable; a promotion gate not yet passed is `caution`, its unmet criteria `blocked` | INFERRED | 2026-09-26 | — | `StatusBadge.tsx:14-25, :48-50`; `promotionGateStatus`; OD-2; Q-33 | consistency is what makes the amber trustworthy; the gate chip is amber as it shipped (`.pill-warn`), since red past the safety controls is Q-33 |
| C-6 | Attention by chroma; failure louder than success | INFERRED | 2026-09-26 | — | `globals.css:36-40, :75-77`; `repo:PRODUCT.md:83-86` | the operator came for what is wrong |
| C-7 | Accent only for action, selection, focus, links | INFERRED | 2026-09-26 | — | `globals.css:62-65` | restraint |
| C-8 | Every border names its colour; a base default | INFERRED | 2026-09-26 | — | REFERENCE §2.5; ES P-1 | a bare `border` fell back to `currentColor`; the default ships since the adopting change |
| C-8a | The card's edge is a hairline `--border` | **APPROVED** | 2026-09-26 | Quentin Casares | OD-3 | answered in session |
| C-9 | Missing role tokens (`--blocked-ink`, tints, `--chip-edge`); `--scrim` landed 2026-09-27 | INFERRED, PROPOSED | 2026-09-26 | — | REFERENCE §2.2-2.3 | literals without a role; the scrim's value is this contract's, the taste skill's "no pure black" adopted under this rule |
| C-10 | Both schemes checked | INFERRED | 2026-09-26 | — | `0ec084f:DESIGN.md:11-16` | light is a peer |
| C-11 | Nothing moves toward the stated anti-references | INFERRED | 2026-09-26 | — | `repo:PRODUCT.md:52-68`; `0ec084f:DESIGN.md:226-231`; `globals.css:15-21` | the brand's prohibited looks need a rule |
| C-12 | On a safety control, red means live money reachable; halted is a strong amber "stopped" | **APPROVED** | 2026-09-26 | Quentin Casares | OD-2 | answered in session |
| C-12r | "stopped" is its own `StatusBadge` state: amber, heavier than `unknown`, glyph and word | INFERRED | 2026-09-26 | — | OD-2; C-4r; A-6 | a known state must not read as "not measured"; its tokens are PROPOSED (Q-34) |
| T-1 | Seven sizes; nothing under 11px | INFERRED | 2026-09-26 | — | `globals.css:99-109`; REFERENCE §3.3 | 3.6px chart text on phones |
| T-2 | Read utilities by value | INFERRED | 2026-09-26 | — | `globals.css:246-252`; O-9 | remapped names mislead |
| T-3 | Sans for words, mono for figures | INFERRED | 2026-09-26 | — | `0ec084f:DESIGN.md:129-132`; Q-11 | mono prose reads as data |
| T-4 | Tabular, right-aligned figures | INFERRED | 2026-09-26 | — | `globals.css:307-311`; `repo:PRODUCT.md:119-120` | column comparison |
| T-5 | One h1 in every state; section titles are h2 | INFERRED | 2026-09-26 | — | axe (REFERENCE §6.7) | heading outline |
| T-6 | One caps treatment, `--track-caps` .045em | INFERRED, PROPOSED | 2026-09-26 | — | REFERENCE §3.6 | three tracking values |
| T-7 | Line-height tokens | INFERRED, PROPOSED | 2026-09-26 | — | REFERENCE §3.4; Q-14 | 3–4 line-heights per size |
| T-8 | Prose ≤75ch | INFERRED | 2026-09-26 | — | `0ec084f:DESIGN.md:134-135` | readability |
| T-9 | Fixed rem, no clamp | INFERRED | 2026-09-26 | — | `globals.css:99-102` | one desk, one DPI |
| T-10 | Geist and Geist Mono, self-hosted, leading the tokens; the package's fallbacks, then the former system stacks, behind; figures tabular; ✓ ✕ ■ from each OS | **APPROVED** | 2026-09-27 | Quentin Casares | OD-5 | answered in session; replaces "system stacks, no web font"; the glyph exception is recorded, not decided (Q-36) |
| T-11 | What counts as prose: a running sentence — an intro, a card's paragraph, a banner — is 15px at T-8's measure; a caption, hint, timestamp, label, count, id, cell or chip keeps 11–13px; prose is never as heavy as a title | INFERRED | 2026-09-27 | — | OD-8 ("body prose moves to 15px"; "hierarchy by weight and colour, not size"); T-8; review of 2026-09-27 | OD-8 named body prose and not what counts as prose: intros were 15px on two pages and 13px on three, every sentence on the summary pages 12–13px, and a banner kept as "secondary prose" at 13px |
| S-1 | 4px scale; no new off-scale steps | INFERRED | 2026-09-26 | — | `globals.css:111-119`; Q-13 | 6px is 246 uses off-scale |
| S-2 | Sections 24px apart, never 0 | **APPROVED** | 2026-09-27 | Quentin Casares | OD-8 (answers Q-12) | answered in session; 12px on every page until then (REFERENCE §4.2); 24px is the preview's target, shown as a step from 16px (Q-37) |
| S-3 | Header → first block 16px | INFERRED | 2026-09-26 | — | REFERENCE §4.2 | six measured variants |
| S-4 | Label → control 8px | INFERRED | 2026-09-26 | — | REFERENCE §4.2; Q-13 | five values at `0ec084f` |
| S-5 | Padding 16 / 12 / 8 | INFERRED | 2026-09-26 | — | REFERENCE §4.3 | as shipped |
| S-6 | Two radii, plus fully round for the one chip | INFERRED | 2026-09-26 | — | REFERENCE §4.7; OD-3 | as shipped |
| S-7 | No shadows in product code | **APPROVED** | 2026-09-27 | Quentin Casares | OD-7 | the question put S-7 as "no shadows" and the owner kept it; hard-coded black alpha (REFERENCE §2.3, §4.7) |
| S-8 | 1px borders; nav rule the exception | INFERRED | 2026-09-26 | — | REFERENCE §4.7 | as shipped |
| S-9 | Named z-index scale | INFERRED | 2026-09-26 | — | `globals.css:132-138`; Q-25 | never an arbitrary 999 |
| S-10 | No box in a box | INFERRED | 2026-09-26 | — | `globals.css:460-462`; Q-18 | the second border lies |
| L-1 | One shell | INFERRED | 2026-09-26 | — | REFERENCE §4.4 | as shipped |
| L-2 | Min-width breakpoints sm/md/lg only | INFERRED | 2026-09-26 | — | REFERENCE §4.5 | the legacy max-width block is half-inert |
| L-3 | Data full width; prose capped | INFERRED | 2026-09-26 | — | REFERENCE §4.4; Q-15 | no measure exists |
| L-4 | Reuse the listed grids; the Summary grid is OD-7's | INFERRED | 2026-09-27 | — | REFERENCE §4.6; OD-7 (the Summary row); S-2 (the Two-up gap) | eight grids already; the Summary grid added and the Two-up gap raised to 24px on 2026-09-27 |
| L-5 | No painted empty metric track | INFERRED | 2026-09-26 | — | O-18 | reads as a missing value |
| L-6 | No sideways document scroll | INFERRED | 2026-09-26 | — | `0ec084f:DESIGN.md:146-150` | as stated |
| L-7 | One page-header pattern | INFERRED | 2026-09-26 | — | REFERENCE §6.3 item 13 | three intro styles |
| K-1 | One owner per job; extend before creating | INFERRED | 2026-09-26 | — | the article; REFERENCE §6.3 | 13 duplicate families |
| K-2 | Pages never map status to colour | INFERRED | 2026-09-26 | — | `StatusBadge.tsx:4-12` | its own contract |
| K-3 | Full state set incl. active, invalid, busy | INFERRED | 2026-09-26 | — | `0ec084f:DESIGN.md:157`; EC §5.2 | missing at `0ec084f` |
| K-4 | Button variant by job | INFERRED | 2026-09-26 | — | `0ec084f:DESIGN.md:159-164`; Q-7, Q-8 | asymmetry visible |
| K-5 | Forms submit on Enter; inline errors | INFERRED | 2026-09-26 | — | REFERENCE §6.5 | only `/login` does |
| K-6 | Table headers, `aria-sort`, unknowns last, wrap prose | INFERRED | 2026-09-26 | — | O-12, O-20; `DataTable.tsx:114-120` | three header styles |
| K-7 | Banner tone by meaning; caveat above figure | INFERRED | 2026-09-26 | — | `globals.css:490-501`; REFERENCE §7 | synthetic banner below the chart |
| K-8 | Vendored edits fix a defect, bind a token or carry an owner decision, and are logged | INFERRED | 2026-09-27 | — | `ui/card.tsx:5-16`; Q-24; OD-6 (the press) | `shadcn add` overwrites; the press is the first edit an owner decided |
| K-9 | Icons lucide, hidden when decorative, distinct; the set is Q-35 | INFERRED | 2026-09-27 | — | EC §4.3, §7.2; `components.json` (`iconLibrary: lucide`) | `Activity` used twice; the taste skill asks for Phosphor or Radix (Q-35) |
| K-10 | One lit nav item per route | INFERRED | 2026-09-26 | — | `AppNav.tsx:24-28` | two pages light none |
| K-11 | `TypedConfirm`; no `window.prompt` | INFERRED | 2026-09-26 | — | REFERENCE §6.3 item 12 | two confirm patterns |
| K-12 | One back-link pattern | INFERRED | 2026-09-26 | — | REFERENCE §6.3 item 11 | 4 of 5 uses |
| K-13 | `AiBadge` meaning visible | INFERRED | 2026-09-26 | — | `GateChecklist.tsx:112-124` | meaning only in `title` |
| K-14 | New instances follow 5.3's order of parts; its measurements are observations | INFERRED | 2026-09-26 | — | the article; REFERENCE §6.1, §6.3 | a shipped value is not doctrine |
| K-15 | Legacy element rules never style shadcn/Radix components | **APPROVED** | 2026-09-26 | Quentin Casares | OD-3 | answered in session |
| K-16 | shadcn canonical: `Card`, `StatusBadge`, `Button`, the fields; legacy classes retire | **APPROVED** | 2026-09-26 | Quentin Casares | OD-3 | answered in session |
| M-1 | 140/200ms; nothing that runs once over 250ms; two loops, each bound to its state; bridge Tailwind defaults | INFERRED, PROPOSED | 2026-09-27 | — | `globals.css:124-130`; OD-6 (the pulse) | 150ms and 300/500ms at `0ec084f`; the loop clause since OD-6 |
| M-2 | `--ease` only | INFERRED | 2026-09-26 | — | `globals.css:125-128` | as stated |
| M-3 | Motion reports a state or a change; nothing loops unless it reports real state | **APPROVED** | 2026-09-27 | Quentin Casares | OD-6 | answered in session; replaces "no page-load choreography" |
| M-4 | No class that compiles to nothing | INFERRED | 2026-09-26 | — | REFERENCE §6.6; Q-17 | 55 dead classes |
| M-5 | Changed values acknowledged | INFERRED | 2026-09-26 | — | `globals.css:780-787`; Q-17 | `.changed` never applied |
| M-6 | Reduced-motion alternatives | INFERRED | 2026-09-26 | — | `globals.css:886-903` | `.changed` has none |
| M-7 | Cadence documented per page | INFERRED | 2026-09-26 | — | REFERENCE §6.5 | docs say ten seconds |
| M-8 | Busy states; skeletons not spinners | INFERRED | 2026-09-26 | — | `0ec084f:DESIGN.md:184-186` | label swap only |
| M-9 | Stopping is one action | INFERRED | 2026-09-26 | — | `repo:PRODUCT.md:88-92` | as stated |
| M-10 | The live pulse: the worker's heartbeat chip breathes only while that heartbeat is fresh, still when stale; 2.4s on `--ease` | **APPROVED** | 2026-09-27 | Quentin Casares | OD-6 | answered in session; the preview named 2.4s on `--ease` |
| M-10r | The pulse's drawing and terms: the row alive (fresh and saying so), last refresh and the reading's age (under two polls), all three; the runner too; never a past day; rows in id order; a halo that never dims the chip; still under reduced motion | INFERRED | 2026-09-27 | — | OD-6 (the pulse); `repo:CLAUDE.md` "A dead worker looks dead"; the geometry, strength and conjunction are this contract's | split from M-10, whose APPROVED text had carried them; the reading's age joined the conjunction the same day, after a refresh that hung kept a halo breathing over a reading that had stopped getting newer; then the stored status, after a clean shutdown breathed for a minute, and the id order, after two workers trading places restarted their halos |
| M-11 | Safety controls never move: no press, pulse or entrance; `STILL` on every Button there | **APPROVED** | 2026-09-27 | Quentin Casares | OD-6 (the question's own condition); C-12 (OD-2) | the owner answered within "I will not put movement on the kill switch or live gates" |
| M-12 | A list's first arrival: a 4px rise and fade, 40ms apart, capped at 320ms; never on a poll, nor on a moved row; a fade in place under reduced motion | INFERRED | 2026-09-27 | — | OD-6 (the stagger); the step, cap and delays are this contract's | the owner chose a stagger, not its values; the preview's 40ms step is kept and the cap at the ninth row added |
| A-1 | WCAG 2.2 AA | INFERRED | 2026-09-26 | — | `repo:PRODUCT.md:101` | as stated |
| A-2 | 4.5:1 in every state and backdrop | INFERRED | 2026-09-26 | — | REFERENCE §2.6 | four failing pairs |
| A-3 | 3:1 for boundaries and focus | INFERRED | 2026-09-26 | — | WCAG 1.4.11 | inputs 1.37–1.97 |
| A-4 | One focus indicator, the accent outline, on every control | **APPROVED** | 2026-09-26 | Quentin Casares | OD-3 | answered in session |
| A-4r | The outline appears at once and is never suppressed without replacement | INFERRED | 2026-09-26 | — | A-4; `0ec084f:DESIGN.md:219-220` | nav links transition it in |
| A-5 | Underline in-text links, and only those | INFERRED | 2026-09-26 | — | axe `link-in-text-block` | 1.98:1 dark; a link that stands alone is drawn by its own component |
| A-6 | Glyph + word for every status | INFERRED | 2026-09-26 | — | `repo:PRODUCT.md:109-111` | colour-blind reading |
| A-7 | Keyboard: focusable scrollers, Enter, `aria-sort` | INFERRED | 2026-09-26 | — | axe `scrollable-region-focusable` | mobile tables unreachable; on 2026-09-27 the pipeline board with no candidate on it, which axe reported and the seeded captures never reach |
| A-8 | Document structure | INFERRED | 2026-09-26 | — | axe (four rules) | as found |
| A-9 | Live regions | INFERRED | 2026-09-26 | — | REFERENCE §6.7 | 27 silent error banners |
| A-10 | 24px targets | INFERRED | 2026-09-26 | — | REFERENCE §6.7 | five candidates under |
| A-11 | One hidden-text utility | INFERRED | 2026-09-26 | — | REFERENCE §6.3 | two exist |
| A-12 | Placeholders `--muted` | INFERRED | 2026-09-26 | — | `globals.css:590-594` | as shipped |
| A-13 | Charts named, values also in text | INFERRED | 2026-09-26 | — | WCAG 1.1.1; `EquityChart.tsx:96-97` | the name gives only dates |
| E-1 | No overflow at 390px, device-width check | INFERRED | 2026-09-26 | — | REFERENCE §4.9 | 784px candidate page |
| E-2 | Long strings wrap | INFERRED | 2026-09-26 | — | O-13, O-20 | overflow and overprint |
| E-3 | Honesty fields visible at 390px | INFERRED | 2026-09-26 | — | ES P-12 | off-screen at `0ec084f` |
| E-4 | Input size per breakpoint, none under 13px | INFERRED | 2026-09-26 | — | Q-16, Q-29 | iOS zoom; 12px desktop inputs |
| E-5 | Chart labels fit, ≥11px | INFERRED | 2026-09-26 | — | O-15 | "$" clipped |
| E-6 | Number edge cases (null, NaN, Infinity) | INFERRED | 2026-09-26 | — | H-3; Q-21 | `?? 0` and "—" at `0ec084f` |
| E-7 | Loading ≠ empty ≠ absent | INFERRED | 2026-09-26 | — | REFERENCE §6.5 | portfolio |
| E-8 | Capped counts say so | INFERRED | 2026-09-26 | — | O-16 | "Fills (500)" |
| E-9 | Failed load keeps h1 | INFERRED | 2026-09-26 | — | REFERENCE §6.5 | endless "Loading…" |
| E-10 | Bounded page length | INFERRED | 2026-09-26 | — | Q-27 | 8,708px page |
| E-11 | Both schemes per run | INFERRED | 2026-09-26 | — | Q-19 | — |
| E-12 | Wrap points compare across machines, except chips carrying ✓ ✕ ■; pixels within one OS and browser, once the fonts have loaded and the motion has stopped | INFERRED | 2026-09-27 | — | REFERENCE §3.1; OD-5; Q-36 | DejaVu captures before the face was bundled; the faces lack three status glyphs; the live pulse froze at a different phase in each capture |
| E-13 | Never show a figure as current when it is not | INFERRED | 2026-09-26 | — | REFERENCE §6.5; `repo:CLAUDE.md:53-55` | last-good figures stayed unmarked; on `/programme` until 2026-09-27 |
| H-1 | Never render a Sharpe without its SE | **APPROVED** | 2026-08-02 | Quentin Casares | `repo:CLAUDE.md:100-102` (4943156) | repo rule |
| H-1r | "x ± se" in one element; significance as a word, from the stored flag; SE survives sorting | INFERRED | 2026-09-26 | — | REFERENCE §7; `test_browser_journey.py:46-50` (the tearsheet's banner, by hand) | colour + `title` on the list at `0ec084f` |
| H-2 | Never quote a searched Sharpe undeflated | **APPROVED** | 2026-08-03 | Quentin Casares | `repo:CLAUDE.md:103-108` (ee547f4) | repo rule |
| H-2r | Deflated Sharpe and trial count beside the best Sharpe; stored, never recomputed | INFERRED | 2026-09-26 | — | REFERENCE §7 | no surface |
| H-3 | Unmeasured is never zero; a genuine zero stays a zero | **APPROVED** | 2026-08-03 | Quentin Casares | `repo:CLAUDE.md:109-112, :300` (ee547f4); `test_programme_scorecard.py::TestNothingUnmeasuredReadsAsZero` | repo rule, tested on the scorecard |
| H-3r | An absence says why: "not measured", "no data"; never a bare dash, never 0 | **APPROVED** | 2026-09-26 | Quentin Casares | OD-4 | answered in session |
| H-3s | No substituted default; unknowns sort last and filter apart | INFERRED | 2026-09-26 | — | REFERENCE §7 | `?? 252` at `0ec084f` |
| H-4 | Every performance figure carries its cost assumption | **APPROVED** | 2026-08-02 | Quentin Casares | `repo:CLAUDE.md:113-114` (4943156) | repo rule |
| H-4r | Cost stress beside every return, Sharpe, drawdown | INFERRED | 2026-09-26 | — | REFERENCE §7 | the candidate card lacks it |
| H-5 | Every metric carries `effective_start` | **APPROVED** | 2026-08-02 | Quentin Casares | `repo:CLAUDE.md:115-117` (4943156) | repo rule |
| H-5r | Effective start on every result; warm-up shaded | INFERRED | 2026-09-26 | — | REFERENCE §7 | the backtests list lacked it |
| H-6 | Every annualised figure carries its session count | **APPROVED** | 2026-08-02 | Quentin Casares | `repo:CLAUDE.md:118-123` (4943156) | repo rule |
| H-6r | "Annualised on N sessions/year"; never a default 252 | INFERRED | 2026-09-26 | — | REFERENCE §7; `test_browser_journey.py:46-50` ("Annualised on", by hand) | `?? 252` at `0ec084f` |
| H-7 | Synthetic data is labelled everywhere | **APPROVED** | 2026-08-02 | Quentin Casares | `repo:CLAUDE.md:124-125` (4943156) | repo rule |
| H-7r | `synthetic` chip in every page header and above charts, any status | INFERRED | 2026-09-26 | — | REFERENCE §7; `test_browser_journey.py:46-50` ("Synthetic data", by hand) | below the chart; missing when queued or failed |
| H-8 | Say when the backtest was kinder than the venue | **APPROVED** | 2026-08-02 | Quentin Casares | `repo:CLAUDE.md:126-131` (4943156) | repo rule |
| H-8r | Underfunded-buy count, worst shortfall and the `cash_buffer_pct` remedy on backtest detail | INFERRED, PROPOSED field | 2026-09-26 | — | REFERENCE §7; `repo:CLAUDE.md:130-131` | no API field |
| H-9 | Shadow equity is not a result, and the UI says so | INFERRED | 2026-09-26 | — | `repo:CLAUDE.md:470-472` (ee547f4) | a Known-limitations statement, not a rule; no test reads the page |
| H-9r | Label it wherever shadow equity appears | INFERRED | 2026-09-26 | — | REFERENCE §7 | present |
| H-10 | A missing measurement is `unknown`, not `fail` | **APPROVED** | 2026-08-03 | Quentin Casares | `repo:CLAUDE.md:300-301` (ee547f4); `test_programme_scorecard.py` | repo rule, tested |
| H-10r | Scorecard status and `observed_display` rendered verbatim | INFERRED | 2026-09-26 | — | REFERENCE §7 | met |
| H-11 | The frontend holds no model client; no vendor host or TypeSafe endpoint in `web/src` | **APPROVED** | 2026-09-26 | Quentin Casares | `repo:CLAUDE.md:307-308` (0ec084f); five tests (§9) | tests, except a non-TypeSafe npm model SDK, which none refuses |
| H-12 | One shared percent formatter; one format per quantity; capped counts say so | INFERRED | 2026-09-26 | — | REFERENCE §7; Q-22; the consequence recorded with the owner decisions | 100× drawdown at `0ec084f` |
| H-13 | Refusals name what is missing | INFERRED | 2026-09-26 | — | O-23; `repo:PRODUCT.md:49-50` | positive descriptions at `0ec084f` |
| H-14 | Multiple-testing counter | INFERRED | 2026-09-26 | — | `page.tsx:141-150` | as shipped |
| H-15 | Model output never styled as fact | INFERRED | 2026-09-26 | — | `globals.css:522-524` | as stated |
| H-16 | The scorecard has no overall score | **APPROVED** | 2026-08-03 | Quentin Casares | `test_programme_scorecard.py::TestTheRecommendation::test_there_is_no_overall_score` (ee547f4) | test, data layer |
| H-16r | The page derives no score, rank or consensus either | INFERRED | 2026-09-26 | — | `candidates/[id]/page.tsx:312`, :593-594 | said on the page |
| H-17 | A missing required field reads "missing" plus the reason | **APPROVED** | 2026-09-26 | Quentin Casares | OD-4 | answered in session |
| H-18 | What the UI says about the system matches `CLAUDE.md` | INFERRED | 2026-09-26 | — | `programme/page.tsx:463-467`; `repo:CLAUDE.md:458-465` | "shadow-mode operation is not built" was false |
| G-1 | Three live-order gates, three answers, never combined | INFERRED | 2026-09-26 | — | Safety rule 1, `repo:CLAUDE.md:44-52` (4943156); `system/page.tsx:14-16` | as shipped |
| G-2 | A fail-closed switch is shown failing closed; unreadable state is unknown; stopped is amber | INFERRED | 2026-09-26 | — | Safety rules 2, 7, `repo:CLAUDE.md:53-55`, :90-94; OD-2 | the last value stayed after a failed poll; the programme's switch kept "enabled" so until 2026-09-27 |
| G-3 | Stopping is one action; starting is a typed phrase, never pre-filled | INFERRED | 2026-09-26 | — | `repo:PRODUCT.md:88-92`; `system/page.tsx:6-9` | `window.prompt` for autonomy |
| G-4 | Alive is a fresh heartbeat that says `'alive'`, decided once (`isAlive`), worded by `livenessWord`, rows in id order | INFERRED | 2026-09-27 | — | `repo:CLAUDE.md` "A dead worker looks dead" (4943156); `lib/heartbeat.ts`; review of 2026-09-27 | from `stale` alone as first written, when the stored status was held to be only ever 'alive'; a clean shutdown writes 'stopped' with a fresh `last_seen`, and read by its age a stopped process was a green "stopped" with a live halo on `/system` and "alive" on `/programme` for a minute |
| G-5 | Requested and effective values both shown | INFERRED | 2026-09-26 | — | `repo:CLAUDE.md:295` (ee547f4); `programme/page.tsx:26-30` | as shipped |
| G-6 | Queued work is reported as queued | INFERRED | 2026-09-26 | — | `programme/page.tsx:245-251`; `repo:docs/08-jev-integration.md:624` | as shipped |
| G-7 | A promotion never implies an override | INFERRED | 2026-09-26 | — | `repo:CLAUDE.md:290` (ee547f4); `candidates/[id]/page.tsx:165-176` | as shipped |
| J-1 | Probabilities and `model_answered` inline, never tooltip-only | INFERRED (planned) | 2026-09-26 | — | `repo:docs/08-jev-integration.md:616`; Q-23 | phase E not started |
| J-2 | `confidence` = "concentration, not probability correct"; Noul "n/a" | INFERRED (planned) | 2026-09-26 | — | `:617-618`, `:49`; OD-4 | "n/a" is outside OD-4's three words |
| J-3 | "choice ≠ argmax" badge, as `unknown` | INFERRED (planned) | 2026-09-26 | — | `:619`, `:216-217` | a mismatch is an abstention |
| J-4 | "Not measured" is a third filter state; unknowns never sort low | INFERRED (planned) | 2026-09-26 | — | `:620` | as specified |
| J-5 | Vendor accuracy "not published by TypeSafe" | INFERRED (planned) | 2026-09-26 | — | `:621` | as specified |
| J-6 | "contaminated" badge explains a refusal | INFERRED (planned) | 2026-09-26 | — | `:602-605`, `:634-635` | as specified |
| J-7 | Backfilled renders as not measured, marked, with the live fraction | INFERRED (planned) | 2026-09-26 | — | `:515-518`, `:590-591`, `:635` | marker wording is this contract's |
| J-8 | "not calibrated" until an evaluation passes | INFERRED (planned) | 2026-09-26 | — | `:276-280` | as specified |
| J-9 | "forward experiment, not validated by walk-forward" | INFERRED (planned) | 2026-09-26 | — | `:606-610` | as specified |
| J-10 | Catalogue: https links, no abstracts, no `dangerouslySetInnerHTML` | INFERRED (planned) | 2026-09-26 | — | `:622-623` | as specified |
| J-11 | "suggested reviewer … Jev (automated, cannot block)" | INFERRED (planned) | 2026-09-26 | — | `:632-633` | as specified |
| J-12 | No control turns model output into an order | **APPROVED** | 2026-08-02 | Quentin Casares | `repo:CLAUDE.md:70-87` (rule 5, 4943156) | rule 5, enforced on `src/`, not the page |
| J-12r | …nor into a deployment change or a promotion | INFERRED | 2026-09-26 | — | this contract; `repo:CLAUDE.md:290` | extends rule 5 |
| J-13 | No TypeSafe endpoint, vendor host or TypeSafe-named package in the frontend | **APPROVED** | 2026-09-26 | Quentin Casares | `repo:CLAUDE.md:307-308` (0ec084f); the tests in H-11 | tests; the general "no model SDK" is untested |
| J-14 | Jev work is enqueued and shown as queued | INFERRED (planned) | 2026-09-26 | — | `:624` | as specified |
| J-15 | Typed `ENABLE JEV`, audited; off is one action | INFERRED (planned) | 2026-09-26 | — | `:629-630` | as specified |
| J-16 | Evaluations with uncertainty, floor, n, flip rate; public sets an upper bound | INFERRED (planned) | 2026-09-26 | — | `:594-601`, `:513`, `:905` | the Jev form of H-1 |
| J-17 | Triage chips resume nothing, touch no kill switch | INFERRED (planned) | 2026-09-26 | — | `:542` | as specified |
| J-18 | Routing suggestions never written into `severity` or `status`; never a veto | INFERRED (planned) | 2026-09-26 | — | `:541` | as specified |
| J-19 | Signal model and threshold beside the contaminated badge and live fraction | INFERRED (planned) | 2026-09-26 | — | `:634-635` | as specified |
| J-20 | The recorded departure from vendor guidance on the strategy page | INFERRED (planned) | 2026-09-26 | — | `:285-289` | as specified |
| J-21 | A "Jev" nav group, a catalogue page, one `JevAnswer` | INFERRED (planned) | 2026-09-26 | — | `:626-631` | as specified |
| D-TOK-1 | Pointer to the token file, no YAML tokens | INFERRED | 2026-09-26 | — | §11 | one checked copy beside the CSS |
| D-TOK-2 | One JSON, light in `$extensions` | INFERRED | 2026-09-26 | — | §11 | mirrors the CSS shape |
| D-TOK-3 | `globals.css` is the source of truth | INFERRED | 2026-09-26 | — | `0ec084f:DESIGN.md:6-7`; Q-2 | the runtime reads CSS |
| D-TOK-4 | File name `design-tokens.json` | INFERRED | 2026-09-26 | — | §11 | the requested name |
| D-TOK-5 | Lives in `web/`; the root `DESIGN.md` is a pointer | **APPROVED** | 2026-09-26 | Quentin Casares | OD-1 | answered in session; Tailwind is told not to read the documents as source |
| D-TOK-6 | The token file names what it does not hold (Tailwind defaults) | INFERRED | 2026-09-26 | — | `compiled:57-86`, :2528-2557; Q-31 | breakpoints are untokenised |
| D-EX-1 | Approved PNGs stay out of the web image | INFERRED | 2026-09-26 | — | `repo:web/Dockerfile` | `COPY . .` would ship them |
| D-ALLOW-1 | The allow-list entries are recorded debt awaiting the owner, and only shrink | INFERRED | 2026-09-26 | — | §13 (a); Q-32 | the article asks for approved exceptions |
