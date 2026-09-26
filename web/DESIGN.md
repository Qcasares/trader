---
status: adopted                      # OD-1
adopted: 2026-09-26
owner: Quentin Casares               # approves rules, tokens, components, examples and the log (OD-1)
written_against: 0ec084f             # the commit REFERENCE.md measures
scope: web/src/**
tokens: design-tokens.json           # DTCG 2025.10, the exact values
token_source_of_truth: src/app/globals.css
decision_log: design/decision-log.md
notes: design/notes.md
checks: design/checks.md
evidence: REFERENCE.md
examples: examples/README.md
routing: CLAUDE.md
product: ../PRODUCT.md
replaces: ../DESIGN.md               # a pointer here; its former text is REFERENCE.md Appendix A
---

# DESIGN — implementation contract for `web/`

Read this before any UI change: it is every rule and its status. A rule's basis is in `design/decision-log.md`, its
longer reasons, as-shipped state and *Today* in `design/notes.md`, its evidence in `REFERENCE.md`, its checks in
`design/checks.md`; read those only to change a token, a rule or a pattern. Paths are from `web/` unless `repo:`; `Q-n`
and `FX-n` are in `REFERENCE.md`. **Where a table here disagrees with `design-tokens.json`, the token file wins.**

## 0. How to read this contract

### 0.1 The status of a rule

**APPROVED** binds: an owner decision, a `repo:CLAUDE.md` rule, or a test. **INFERRED** is the default an agent
follows *and says it followed* until the owner approves it. **PROPOSED** needs something that does not exist yet.
`Q-n` is a question to ask, not guess. Only the owner changes a status (OD-1).

### 0.2 Owner decisions

The owner, Quentin Casares, 2026-09-26; quoted verbatim in the decision log.

- **OD-1** · APPROVED · The owner approves design rules; the system lives in `web/` (this file, `REFERENCE.md`,
  `design-tokens.json`, `examples/`, routing in `CLAUDE.md`); the root `DESIGN.md` is a pointer; rules stay INFERRED
  until approved. *Settles:* D-TOK-5, §0.1, §13 (d).
- **OD-2** · APPROVED · Red is reserved for "live money reachable"; a halted kill switch is safe: a strong amber
  "stopped". *Settles:* C-12, G-2. *Open:* Q-33.
- **OD-3** · APPROVED · shadcn is canonical; the legacy base rules that restyle it are scoped away; one card (hairline
  border), one chip, and on every control the accent focus outline (≥3:1; the shadcn ring goes). *Settles:* K-15,
  K-16, C-8a, A-4, S-6's chip radius.
- **OD-4** · APPROVED · An absence says why: "not measured" (a metric never computed), "no data" (an observation that
  never arrived), "missing" plus the reason (a required field); never a bare dash, never 0. *Settles:* H-3r, H-17.

### 0.3 Precedence

- **D-PREC** · INFERRED · The higher source wins: (1) `repo:CLAUDE.md`, its tests, the owner decisions; (2)
  `globals.css` and `design-tokens.json` for exact values; (3) this contract; (4) approved examples (none yet) for
  proportion — for behaviour, the owning component (§5.1); (5) shipped screens, evidence and never values; (6) the
  rest. A disagreement within a level, a choice nothing covers, or a clash with `repo:PRODUCT.md` or the former root
  `DESIGN.md` (never a precedent) goes to the owner.

Why it looks as it does (dark first, attention by chroma, amber for unknown) is `design/notes.md` §0.4.

## 1. Colour — semantic tokens named by job

Tokens by job. The shadcn names inside `components/ui`, and each token's JSON path, are `design/notes.md` §1.

| Job | Token | Product code |
|---|---|---|
| Page background | `--bg` | `bg-bg` (`body` sets it) |
| Raised surface: card, sidebar, header, sheet, metric cell | `--panel` | `bg-panel` |
| Inset, hover, chip surface, active nav | `--panel-2` | `bg-panel-2` |
| Hairline, container and card edge | `--border` | `border-line` |
| Control boundary, table-head rule | `--border-strong` | `border-line-strong` |
| Primary text | `--text` | `text-ink` |
| Secondary text, labels, placeholders | `--muted` | `text-ink-muted` |
| De-emphasised but read | `--faint` | `text-ink-faint` |
| Committing action, selection, focus, link | `--accent` | `bg-brand`, `text-brand` |
| Text on an accent fill | `--accent-ink` | `text-brand-ink` |
| Accent hover (legacy only) | `--accent-dim` | `bg-brand-dim` |
| Refused or failed; on a safety control, live money reachable | `--blocked` | `text-blocked`, `border-blocked` |
| Not measured, indeterminate, model-authored; under ▲, a gate not yet passed (C-5) | `--unknown` | `text-unknown` |
| The `stopped` plate (C-12r), PROPOSED (Q-34) | `--stopped` | `bg-stopped`, `border-stopped` (in `StatusBadge`) |
| Text and glyph on it, PROPOSED (Q-34) | `--stopped-ink` | `text-stopped-ink` (in `StatusBadge`) |
| Met, passed, alive | `--settled` | `text-settled` |

**Missing roles**, PROPOSED (C-9): `--blocked-ink` for `text-white` on the destructive fill (value **TBD**: ≥4.5:1 at
rest and hover, both themes; white is 3.22 on dark hover); `--scrim` for `bg-black/50` (black at 50 %);
`--warn-surface`/`--warn-edge`, `--info-surface`/`--info-edge`, `--bad-surface`/`--bad-edge` for the banner mixes
(`--unknown` 10/42 %, `--accent` 10/38 %, `--blocked` 12/48 %); `--chip-edge` for the chip borders (40 %).

- **C-1** · INFERRED · Colour only through these tokens: no hex/`rgb()`/`hsl()`/`oklch()` literal, palette colour
  (`text-white`, `bg-red-500`) or arbitrary colour (`bg-[#…]`) in `web/src` outside the allow-list in
  `repo:tests/unit/test_design_tokens.py`. *Check:* §13 (a).
- **C-2** · INFERRED · Product code uses the product names (`bg-panel`, `text-ink-muted`, `border-line`,
  `border-l-brand`); the shadcn names stay inside `components/ui`.
- **C-3** · INFERRED · shadcn's `accent` is `--panel-2` here, never the brand; brand is `brand` or `primary`.
- **C-4** · APPROVED · A missing measurement is `unknown`, not `fail`.
- **C-4r** · INFERRED · It renders as `StatusBadge status="unknown"` (amber, `?`), never `blocked`, never as "stopped".
- **C-5** · INFERRED · `settled`: measured and met. `blocked`: not met, refused or failed — on a safety control, only
  live money reachable (C-12). `caution`: measured and not met *yet* — a promotion gate taken whole
  (`promotionGateStatus`), whose unmet criteria stay `blocked`; `unknown`'s amber under ▲, so the glyph tells "not
  yet" from "not measured" (A-6). `unknown`: not measured, or model-authored. `mute`: known, not interesting
  (`queued`, `running`). `stopped`: a safety switch that is off (C-12r). Never `mute` for "we don't know", never
  `unknown` for a known state. Failed jobs, stale heartbeats and other refusals stay `blocked` until Q-33.
- **C-6** · INFERRED · Attention by chroma: `blocked` is the loudest thing on a page, `settled` the quietest; success is
  never louder than a failure beside it.
- **C-7** · INFERRED · Accent is for the committing action, selection, focus and links; never decorative; at most about
  a tenth of a surface.
- **C-8** · INFERRED · Every bordered element names its colour; the base layer defaults a bare `border` to `--border`,
  never `currentColor`.
- **C-8a** · APPROVED · The card's edge is a 1px `--border` hairline, never the text colour (OD-3).
- **C-9** · INFERRED · PROPOSED · The missing roles become tokens before any new use of the literal they replace.
- **C-10** · INFERRED · Light is a peer: every colour pairing is checked in both schemes. *Check:* §13 (b), (c).
- **C-11** · INFERRED · Nothing moves toward the anti-references: navy-and-gold with a serif wordmark; monospace green
  on black (mono *numerals* are fine); cream, sand or any warm near-white, or warm-tinted neutrals; GitHub Primer; the
  generic SaaS blue. A new hue or surface is checked against this list.
- **C-12** · APPROVED · On a safety control — the three live-order gates and the kill switch on `/system` — red means
  one thing: live money is reachable. A halted kill switch is safe: a strong amber "stopped", prominent, not alarming
  (OD-2).
- **C-12r** · INFERRED · "Stopped" is a `StatusBadge` state of its own, its own glyph and word (A-6), heavier than
  `unknown` so the two never read alike; pages ask `killSwitchStatus` and `liveGateStatus` for it (K-2). The programme
  switch's off state is never red either. Tokens PROPOSED (Q-34).
- Open, not a rule: whether dark `--bg` stays Primer's `#0e1116` (Q-3).

## 2. Typography

| Token | px | Utility | Line-height | Job |
|---|---|---|---|---|
| `--t-xs` | 11 | `text-xs` | 14.67 | uppercase labels, metric keys, table heads |
| `--t-sm` | 12 | `text-sm` (**not 14**) | 17.14 | table cells, dense metadata; shadcn controls (Q-29) |
| `--t-base` | 13 | `text-base` (**not 16**) | 19.5 | secondary prose, inputs, buttons |
| `--t-body` | 14 | `text-body` | 21.7 | body |
| `--t-md` | 16 | `text-md` | inherited | h3, metric values |
| `--t-lg` | 19 | `text-lg` | 24.7 | h2; h1 at ≤640px |
| `--t-xl` | 23 | `text-xl` | 28.75 | h1 |

`--sans` for words, `--mono` for figures; weights 400, 500, 600. Line-heights are as rendered, not tokens (T-7).

- **T-1** · INFERRED · Only the seven sizes; no `text-[Npx]`; nothing under 11 CSS px, SVG chart text at 390px included.
  *Check:* §13 (a), (b).
- **T-2** · INFERRED · Read a utility by its value here: `text-sm` is 12px, `text-base` 13px, so shadcn renders a step
  smaller than it intends (Q-29).
- **T-3** · INFERRED · Words in sans; figures, identifiers and code in mono; never a sentence in mono (Q-11 decides the
  shipped exceptions).
- **T-4** · INFERRED · Figures use tabular numerals; numeric columns are right-aligned with their header.
- **T-5** · INFERRED · One `h1` per page in every state; section titles are `h2`, one size and weight; no skipped
  level (the title's element and weight are Q-9).
- **T-6** · INFERRED · PROPOSED `--track-caps: .045em`: one caps treatment (11px, uppercase, `--track-caps`) for metric
  keys, table, nav and stage heads, retiring the other tracking values. Chips are not uppercase.
- **T-7** · INFERRED · PROPOSED line-height tokens, values the owner's (Q-14); no new literal line-height meanwhile.
- **T-8** · INFERRED · Running prose is capped at 65–75ch; tables and dense metadata run as wide as they need.
- **T-9** · INFERRED · Fixed rem sizes, no `clamp()` or viewport units; the ≤640px h1 is the one responsive size.
- **T-10** · INFERRED · System font stacks, no web font; compare text width only within one OS (E-12).

## 3. Spacing, radius, borders, elevation, stacking

| Token | px | Tailwind | Job |
|---|---|---|---|
| `--s-1` | 4 | `1` | h1→intro, metric key→value |
| `--s-2` | 8 | `2` | table cell padding, label→control |
| `--s-3` | 12 | `3` | **section→section**, card gap, metric cell and banner padding |
| `--s-4` | 16 | `4` | card padding, header→first block, phone gutter |
| `--s-5` | 24 | `6` | desktop gutter |
| `--s-6` | 32 | `8` | a sidebar group heading's top margin (`AppNav`; the legacy h2's) |
| `--s-7` | 48 | `12` | empty-chart padding, footer bottom |

**Radius:** `--radius` 6px, `--radius-sm` 4px. **Stacking:** `--z-sticky` 100, `--z-dropdown` 200, `--z-backdrop`
300, `--z-modal` 400, `--z-toast` 500.

- **S-1** · INFERRED · Tailwind steps `0`, `1`, `2`, `3`, `4`, `6`, `8`, `12` only, and `px` for a hairline gap; nothing
  new at `0.5`, `1.5`, `2.5`, `5`, `7`, `9`, `10` (6px is Q-13). *Check:* none yet.
- **S-2** · INFERRED · Page sections are 12px apart (`gap-3`, `mt-3`, `space-y-3`), never 0 (Q-12).
- **S-3** · INFERRED · Page header → first section: 16px (`mb-4`); retire the `.subtitle` 24px.
- **S-4** · INFERRED · Label → control: 8px (`space-y-2`); 6px is Q-13.
- **S-5** · INFERRED · Padding: card and section 16px; metric cell and banner 12px; table cell 8px.
- **S-6** · INFERRED · `--radius` for containers and controls, `--radius-sm` for small interactive items, fully round
  for the chip (OD-3); no 2px or 10px literal.
- **S-7** · INFERRED · No shadows in product code: hierarchy is `bg` → `panel` → `panel-2` and hairlines; shadows stay
  in `components/ui`. *Check:* §13 (a).
- **S-8** · INFERRED · Borders are 1px; the active nav item's 2px accent rule is the only heavier one.
- **S-9** · INFERRED · Stacking uses the named scale, never an arbitrary number (Q-25).
- **S-10** · INFERRED · No bordered box inside a bordered box (the metric grid and pipeline cards are Q-18).

## 4. Layout, grid, breakpoints

- **L-1** · INFERRED · `AppShell` is the only shell: from `md` a 208px sticky sidebar and 24px gutters; below it a 53px
  sticky header and a 240px left `Sheet`. `/login` is bare.
- **L-2** · INFERRED · Min-width breakpoints only: `sm` 640px, `md` 768px (the shell switch), `lg` 1024px; no
  `xl`/`2xl`, no new `max-width` query (the legacy block migrates onto these). Tailwind defaults, untokenised (Q-31).
- **L-3** · INFERRED · Data runs full width; prose is capped in `ch` (T-8); a `main` maximum is Q-15.
- **L-4** · INFERRED · Reuse a grid here before defining one, and add a new one here:

  | Grid | Definition | For |
  |---|---|---|
  | Metric | `repeat(auto-fit, minmax(170px, 1fr))`, 1px hairline gaps | headline figures |
  | Field | `repeat(auto-fill, minmax(200px, 1fr))`, gap 0 16px | settings forms |
  | Form | `grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3` | parameter forms |
  | Assumption rows | `190px 1fr`, one column ≤640px | what a figure depends on |
  | Gate rows | `84px 1fr`, one column ≤640px | criteria with a chip |
  | Two-up | `grid gap-3 lg:grid-cols-2` | paired cards |
  | Page header | `mb-4 flex flex-wrap items-end justify-between gap-3` | h1, intro, actions |
  | Board | sideways scroll, 208px columns, gap 12px, `scroll-snap-type: x` | the pipeline |

- **L-5** · INFERRED · A metric grid never paints an empty track.
- **L-6** · INFERRED · The document never scrolls sideways; wide content scrolls in its own focusable, labelled region.
- **L-7** · INFERRED · Page header: `h1`, at most one intro (68ch, `--muted`), then actions or the status chip,
  bottom-right.

## 5. Components — anatomy, states, reuse

### 5.1 Who owns which job

Canonical: chosen by OD-3. Shipped: not yet approved as the pattern. What each owner still absorbs is
`design/notes.md` §5.1.

- **Canonical:** section surface `Card` (hairline edge, `h2` title); domain status `StatusBadge` and its mappers
  (`jobStatus`, `livenessStatus`, `killSwitchStatus`, `liveGateStatus`, `promotionGateStatus`); action `Button`; field
  `Input`, `Label`, `Select`.
- **Shipped:** shell `AppShell`, `AppNav`; model-authored marker `AiBadge`; rows `DataTable`; absent value `Absent`
  (`not-measured`, `no-data`, `missing` with a `reason`); formatting `lib/format.ts` (`fmtPct`, `ABSENCE_WORDS`);
  equity curve `EquityChart`; loading `Skeleton`; gate `GateChecklist`; credential `SecretField`; back link, a ghost
  `Button` with `ArrowLeft` at the page foot; element defaults, the legacy `@layer base` sheet, for legacy markup only
  (K-15).
- **PROPOSED:** caveat/error/note `Banner` (`warn`/`info`/`bad`, live-region roles, A-9); headline figure `Metric`
  (`value | null`, format, unit, hint); Sharpe `SharpeFigure` (estimate, SE, significant); committing confirmation
  `TypedConfirm` (phrase, tone, onConfirm); page header `PageHeader` (title, intro, actions); Jev answer `JevAnswer`.

### 5.2 Rules

- **K-1** · INFERRED · One owner per job: extend it (a variant, a prop) before adding a sibling; a new component needs
  a row in 5.1 and in the decision log.
- **K-2** · INFERRED · A page never maps a state to a colour: it asks `StatusBadge` for a `Status` and passes a label.
- **K-3** · INFERRED · Every interactive component has default, hover, `:focus-visible`, active and disabled; fields
  add invalid (`aria-invalid`), committing actions busy (`aria-busy`, a changed label).
- **K-4** · INFERRED · Button variant by job: `default` the committing action, `outline` other actions, `ghost`
  navigation and per-row "view", `link` inline. A filled `destructive` stop is Q-8, a disabled primary's fill Q-7.
- **K-5** · INFERRED · A field and its committing button share a `<form>`; Enter submits; errors render inline, tied by
  `aria-describedby` and `aria-invalid`.
- **K-6** · INFERRED · Sortable headers look like plain ones (T-6), expose `aria-sort`, and sort unknowns last both
  ways; the filter searches every column's visible text; prose cells wrap.
- **K-7** · INFERRED · Banner tone by meaning (`warn` a caveat or unmeasured state, `info` an explanation, `bad` a
  failure); a caveat about a figure sits *above* it.
- **K-8** · INFERRED · `components/ui` changes only to fix a defect or bind to tokens, each change commented in the file
  and logged (`design/notes.md` K-8), since `shadcn add` overwrites it (Q-24).
- **K-9** · INFERRED · Icons are lucide, `aria-hidden` when decorative, one per nav destination; one size is not
  settled (the shipped sizes are `design/notes.md` K-9).
- **K-10** · INFERRED · Every route lights exactly one nav item; a detail route lights its parent.
- **K-11** · INFERRED · Committing or raising actions confirm through `TypedConfirm`, never `window.prompt`.
- **K-12** · INFERRED · One back link: ghost `Button` + `ArrowLeft` at the page foot.
- **K-13** · INFERRED · Model-authored content always shows `AiBadge`, its meaning visible, not only in `title`.
- **K-14** · INFERRED · A new instance follows 5.3's order of parts. Shipped measurements (`design/notes.md` §5.3) are
  observations: reuse one only where nothing disagrees, never one 5.3 says not to copy.
- **K-15** · APPROVED · The legacy `@layer base` element rules never decide how a shadcn or Radix component looks; they
  serve only the legacy markup and go as it migrates; the mechanism is an engineering choice (OD-3).
- **K-16** · APPROVED · shadcn is canonical: the `Card` (C-8a), the one chip `StatusBadge`, the `Button`, `Input`,
  `Label` and `Select`. The legacy `.card`, `.pill-*` and `.badge` retire into them; no new code uses a legacy class
  (OD-3).

### 5.3 Anatomy

| Component | Parts, in order | Do not copy |
|---|---|---|
| `Card` | container → header (title, count or chips, right-aligned action) → content | title element and weight (Q-9) |
| `StatusBadge` | glyph (empty alt text) → word, 6px apart | — |
| `Button` | optional 16px icon → label, 8px apart (6px at `sm`) | text size (Q-29); disabled and stop fills (Q-7, Q-8) |
| Field | `Label` → control → hint → error | control size (Q-29, Q-16); label gap (Q-13); mono prose (Q-11); a boundary under 3:1 |
| `Banner` | optional bold lead → body → optional remedy link | — |
| `Metric`, in a metric grid | key → value → optional chip | empty tracks (L-5) |
| `DataTable` | card title → filter → table → empty or filtered-empty sentence | — |
| `PageHeader` | h1 → one intro → actions or status chip | h1 weight (Q-9) |
| `TypedConfirm` | "Type PHRASE to …" → input (placeholder the phrase) → button, disabled until it matches | — |
| Assumption row | term → value → hint | value face (Q-11) |
| Gate criterion | chip → description → detail → evidence link | `aria-label` on a role-less span |

### 5.4 States

K-3 is the rule; what each component had at `0ec084f` is `design/notes.md` §5.4.

## 6. Interaction, motion, reduced motion

- **M-1** · INFERRED · `--fast` 140ms for hover, focus and colour; `--base` 200ms for a value-changed mark; nothing
  over 250ms. PROPOSED: bridge Tailwind's default transition to `--fast`/`--ease`.
- **M-2** · INFERRED · Easing is `--ease` (`cubic-bezier(0.16, 1, 0.3, 1)`) only; no bounce, no elastic.
- **M-3** · INFERRED · Motion reports a change and does nothing else: no page-load choreography.
- **M-4** · INFERRED · No class that compiles to nothing: an animation class has its library installed and imported, or
  goes (Q-17). *Check:* `repo:tests/unit/test_web_components.py`.
- **M-5** · INFERRED · A polled value that changes is acknowledged (the `.changed` mark or its successor; Q-17).
- **M-6** · INFERRED · Reduced motion gets an alternative, not a removal; the value-changed mark needs a static one.
- **M-7** · INFERRED · A polling page states its cadence in its docblock, and the docs match.
- **M-8** · INFERRED · In flight, a committing button disables and says what is happening ("Queueing…") and its region
  is `aria-busy`; loading is a skeleton shaped like what is coming, never a spinner.
- **M-9** · INFERRED · Stopping takes one action; starting or committing a deliberate one (a typed phrase); the
  control's shape shows the asymmetry the API enforces.

## 7. Accessibility

- **A-1** · INFERRED · WCAG 2.2 AA, verified by computation and axe, not by eye.
- **A-2** · INFERRED · Text ≥4.5:1 in every state (rest, hover, active, focus), on every backdrop, both themes. To fix:
  legacy primary hover (4.06/3.01), dark destructive hover (3.22), light primary hover (4.39), an accent link in a warn
  banner on the light page (4.31).
- **A-3** · INFERRED · Non-text ≥3:1 for a control's boundary (inputs are 1.37–1.97) and for focus indicators; data
  marks in charts meet it, grid lines are decorative.
- **A-4** · APPROVED · One focus indicator on every control, each internal stop of a date input included: the accent
  outline, 2px at 2px offset (5.01–8.34:1). The shadcn ring goes (OD-3).
- **A-4r** · INFERRED · The outline appears at once, not transitioned in, and is never suppressed without the same
  outline in its place. *Check:* §13 (c).
- **A-5** · INFERRED · A link in running text — a paragraph, list item, table cell, definition or banner — is
  underlined; one that stands alone (navigation, the wordmark, a pipeline card, a back link, the skip link) is not.
- **A-6** · INFERRED · Never colour alone: each status has a glyph and a word, the glyph `content: "✓" / ""` so the
  word is announced.
- **A-7** · INFERRED · Every control keyboard-reachable; the skip link first, to `#content`; each data scroller
  focusable (`tabIndex={0}`, `role="region"`, `aria-label`); Enter submits; `aria-sort` on sortable heads; an open
  sheet holds focus, nothing behind it tabbable.
- **A-8** · INFERRED · One `h1` per page and state; no skipped heading level; a `<dl>` holds only `dt`/`dd`; every `th`
  has text (hidden for an actions column); `aria-label` only with a role; a dialog has a title and a description.
- **A-9** · INFERRED · Failures `role="alert"`, saves and notes `role="status"`, loading `aria-busy`.
- **A-10** · INFERRED · Targets ≥24×24 CSS px or a WCAG 2.5.8 exception. To check: the phone brand, the findings
  checkbox, "Full register", "← Programme", the candidate ref link.
- **A-11** · INFERRED · One visually-hidden utility (`sr-only`).
- **A-12** · INFERRED · Placeholders are `--muted`, held to the body ratio.
- **A-13** · INFERRED · A chart is named for what it shows, and every value a reader needs from it is also text beside
  it.

The axe findings at `0ec084f`, and their fixes, are `design/notes.md` §7.

## 8. Responsive rules and edge cases

What changes with width as shipped is `design/notes.md` §8.0.

- **E-1** · INFERRED · At 390×844 no page is wider than the device, **measured against the device width**
  (`scrollWidth > innerWidth` misses it under emulation). *Check:* §13 (b).
- **E-2** · INFERRED · Long unbroken strings (JSON, ids, hashes, errors) wrap (`overflow-wrap: anywhere`) or truncate
  with the full value reachable; never widen the page or overprint a column.
- **E-3** · INFERRED · At 390px a result's honesty fields (source, Sharpe ± SE, cost, effective start, sessions/year)
  show without sideways scrolling. Not met on `/backtests`.
- **E-4** · INFERRED · One input size per breakpoint, none under 13px (the 12px desktop inputs break it, Q-29); 16px on
  phones is Q-16.
- **E-5** · INFERRED · Chart labels never clip and are ≥11 CSS px at every width.
- **E-6** · INFERRED · `null`/`undefined` → `Absent`; `NaN`/±`Infinity` → "not measured"; a genuine zero is `0` (H-3;
  Q-21).
- **E-7** · INFERRED · Loading, empty and absent differ: a skeleton, an empty-state sentence, `Absent`.
- **E-8** · INFERRED · A count in a title is the total; a capped list says so ("200 of 779 shown").
- **E-9** · INFERRED · A failed first load shows the error and keeps the `h1`; nothing waits forever on "Loading…".
- **E-10** · INFERRED · Long tables paginate or window; page length is bounded (Q-27).
- **E-11** · INFERRED · Every screenshot run covers both schemes; a manual theme switch is Q-19.
- **E-12** · INFERRED · Compare screenshots only within one OS and font stack (the capture VM renders DejaVu).
- **E-13** · INFERRED · Nothing shows as current when it is not: a failed refresh marks what it would have refreshed
  stale, with when it was last read (the kill switch and gates too); a changed subject (paper/live) clears the old
  figures to loading, labelled as the response says (`Portfolio.mode`). `/programme` does not yet.

## 9. The honesty rules as UI rules

**H-n** is a `repo:CLAUDE.md` honesty rule, **H-nr** its rendering; H-12 to H-18 serve the same premise.

- **H-1** · APPROVED · Never render a Sharpe without its standard error.
- **H-1r** · INFERRED · Estimate and SE in one element ("0.303 ± 0.226"); non-significance as the *word* "not
  significant" (an `unknown` chip), from the stored `sharpe_is_significant`, never recomputed; no sort drops the SE.
  *By:* PROPOSED `SharpeFigure`.
- **H-2** · APPROVED · Never quote a Sharpe from a search without deflating it.
- **H-2r** · INFERRED · The best of several trials shows the stored deflated Sharpe and the trial count beside it, never
  recomputed. *By:* PROPOSED walk-forward view.
- **H-3** · APPROVED · An unmeasured metric is never zero, and a genuine zero stays a zero.
- **H-3r** · APPROVED · An absence says why ("not measured", "no data"), never a bare dash or 0 (OD-4). *By:* `Absent`
  and `ABSENCE_WORDS`. *Check:* `repo:tests/unit/test_web_formatting.py`.
- **H-3s** · INFERRED · Nor a substituted default: `?? 252` is the same lie as `?? 0` at a different number. Unknowns
  sort last and filter apart. *Check:* `test_web_formatting.py` refuses a fallback to a number literal.
- **H-4** · APPROVED · Never quote a performance figure without its cost assumption.
- **H-4r** · INFERRED · Cost stress (×), and slippage where it matters, in the same card or row as any return, Sharpe or
  drawdown. *By:* `MetricsPanel`, the backtests list, the candidate Configuration card.
- **H-5** · APPROVED · Never quote a metric without `effective_start`.
- **H-5r** · INFERRED · Every result shows its effective start (or that it equals the requested start); charts shade the
  warm-up.
- **H-6** · APPROVED · Never quote an annualised figure without its session count.
- **H-6r** · INFERRED · "Annualised on N sessions/year" beside annualised figures; a missing count is `Absent`, never
  252.
- **H-7** · APPROVED · Synthetic data is labelled everywhere it appears.
- **H-7r** · INFERRED · A `synthetic` chip in the header of every run, candidate and experiment page, whatever its
  status, and above any chart of synthetic data.
- **H-8** · APPROVED · The backtest must say when it was kinder than the venue.
- **H-8r** · INFERRED · PROPOSED field · Backtest detail shows the underfunded-buy count and worst shortfall beside the
  fills, pluralised, and names the remedy: "set `RiskLimits.cash_buffer_pct`".
- **H-9** · INFERRED · Shadow equity "is not a result and the UI says so": a stated limitation, not a rule, untested.
- **H-9r** · INFERRED · Shadow equity is labelled operation, not performance, wherever it appears.
- **H-10** · APPROVED · C-4, as an honesty rule.
- **H-10r** · INFERRED · The scorecard renders the API's status and `observed_display` verbatim, never re-derived.
- **H-11** · APPROVED · "The frontend holds no model client"; `web/src` spells no model vendor's host or TypeSafe
  endpoint. Tests and their gap: `design/notes.md` H-11.
- **H-12** · INFERRED · Percentages come from the stored fraction through `fmtPct` alone, never by appending "%"; one
  format per quantity (Q-22); a capped count says so (E-8). *Check:* `test_web_formatting.py`.
- **H-13** · INFERRED · A refusal names what is missing, not the criterion's positive description; a rejected
  candidate never shows "hold".
- **H-14** · INFERRED · The multiple-testing counter stays beside each strategy and turns `unknown` at 20 runs.
- **H-15** · INFERRED · Model-authored content is marked (K-13) and never styled as a measured fact.
- **H-16** · APPROVED · The scorecard has no overall score: no `score`, no `grade`.
- **H-16r** · INFERRED · Nor does the page derive one: no composite, rank or traffic light, no panel consensus; counts
  are not a score.
- **H-17** · APPROVED · A missing *required* field reads "missing" and what it is required for (gate 0→1, say), never
  an optional field's word, a dash or 0 (OD-4). *Check:* `test_web_formatting.py`.
- **H-18** · INFERRED · What the UI says about the system's own capability matches `repo:CLAUDE.md`.

### 9.1 Safety and control-plane rendering

The safety rules bind the API and worker, where they are tested; these render them.

- **G-1** · INFERRED · The three live-order conditions are three answers, never one chip or summary; one the API does
  not report is `unknown`, never inferred. An open gate is red (C-12).
- **G-2** · INFERRED · A fail-closed switch shows failing closed: unreadable is unknown (E-13), never its last value or
  "enabled"; stopped is amber (C-12), never red. Not yet on `/programme`.
- **G-3** · INFERRED · Stopping is one action; starting a typed phrase never pre-filled (ENABLE TRADING, ENABLE
  PROGRAMME, PROMOTE, RAISE AUTONOMY), through `TypedConfirm`.
- **G-4** · INFERRED · Liveness from `stale`, never a stored status, through `livenessStatus`.
- **G-5** · INFERRED · A requested and an effective value (the autonomy ceiling) are both shown, never one as the other.
- **G-6** · INFERRED · A request for slow work reports it queued, not done, and never waits on it inline.
- **G-7** · INFERRED · A promotion control never implies an override: disabled until the gate passes; a 409 shows what
  is missing (H-13), not a generic error.

## 10. Jev UI rules (planned — phase E, `repo:docs/08-jev-integration.md:612-635`)

These bind the first page to show a Jev answer, through one `JevAnswer`; Rule 5's Jev amendment is not in force.
Sources are in the decision log, components in `design/notes.md` §10.

| ID | Rule | Status |
|---|---|---|
| **J-1** | Probabilities and `model_answered` are inline, never only in a tooltip | INFERRED |
| **J-2** | `confidence` reads "concentration, not probability correct"; a Noul has none and shows "n/a", a word the owner confirms at phase E (Q-23) | INFERRED |
| **J-3** | A "choice ≠ argmax" badge wherever the choice differs from the recomputed argmax; it is an abstention, so `unknown` | INFERRED |
| **J-4** | "Not measured" is a third filter state; an unknown never sorts as a low | INFERRED |
| **J-5** | Vendor accuracy reads "not published by TypeSafe" | INFERRED |
| **J-6** | A "contaminated" badge on candidates, backtests and the metrics panel explains a refusal, never replaces it | INFERRED |
| **J-7** | A backfilled answer renders as not measured, marked "backfilled", with the live fraction | INFERRED (the marker wording is this contract's) |
| **J-8** | A lane without a passing evaluation reads "not calibrated" | INFERRED |
| **J-9** | A forward experiment reads "forward experiment, not validated by walk-forward", results a paired difference with sessions and SE | INFERRED |
| **J-10** | The catalogue: https links only, no republished abstract, no `dangerouslySetInnerHTML` | INFERRED |
| **J-11** | The findings column reads "suggested reviewer … Jev (automated, cannot block)" | INFERRED |
| **J-12** | No UI control turns model output (Jev included) into an order | APPROVED (rule 5; tested on `src/`, not the page) |
| **J-12r** | …nor into a deployment change or a promotion | INFERRED |
| **J-13** | `web/src` spells no TypeSafe endpoint or vendor host; no npm manifest has a TypeSafe-named package | APPROVED (the H-11 tests; a model SDK in general is untested) |
| **J-14** | Any Jev action enqueues work and the page says it was queued, never waiting inline (G-6) | INFERRED |
| **J-15** | The Jev switches take a typed `ENABLE JEV` (G-3) and are audited; off is one action | INFERRED |
| **J-16** | An evaluation shows balanced accuracy, per-class Wilson intervals, Brier score, the majority and keyword baselines, n, and the flip rate where measured; a public-set result reads "possibly in training", an upper bound | INFERRED |
| **J-17** | Ops-triage chips on System > Jobs are display only: nothing beside one resumes a job or touches the kill switch | INFERRED |
| **J-18** | Findings-routing suggestions stay suggestions, never written into `severity` or `status`; a Jev finding shows its `jev:<set>` origin and never reads as a veto | INFERRED |
| **J-19** | Candidates, backtests and the metrics panel show the signal model and threshold beside those | INFERRED |
| **J-20** | With a direct-decision lane, the strategy page states the recorded departure from the vendor's guidance (autonomy above 0.9, paper only) | INFERRED |
| **J-21** | A "Jev" nav group (status, answers, labelling queue, signals) and a catalogue page under Programme | INFERRED |

Never spell the lookalike reseller's name for the Jev key in a file directly under `web/`, this one included:
`test_secret_isolation.py` fails on it. The key is `TYPESAFE_API_KEY`.

## 11. Tokens and these files

- **D-TOK-1** · INFERRED · This file points to `design-tokens.json`, the checked interchange copy, rather than carrying
  YAML tokens; the runtime reads only CSS.
- **D-TOK-2** · INFERRED · One token file for both themes, the light value in the `light` extension; split it only for a
  tool that needs DTCG's Resolver form.
- **D-TOK-3** · INFERRED · `globals.css` is the source of truth: edit it first, then the JSON (Q-2).
- **D-TOK-4** · INFERRED · Keep the name `design-tokens.json` (DTCG suggests `.tokens.json`).
- **D-TOK-5** · APPROVED · The system lives in `web/` beside its code (`REFERENCE.md`, `DESIGN.md`,
  `design-tokens.json`, `examples/`, `design/`, `CLAUDE.md`), the root `DESIGN.md` a pointer (OD-1); `globals.css`
  keeps each document out of Tailwind's scan, or §13 (a) fails.
- **D-TOK-6** · INFERRED · The token file names the Tailwind defaults the UI depends on and it does not hold
  (breakpoints, `--spacing`, the small sizes' line-heights, the 150ms transition); declaring them is Q-31.
- **D-EX-1** · INFERRED · Approved PNGs stay out of the web image: the first one in `examples/` adds it to
  `web/.dockerignore`.
- **D-ALLOW-1** · INFERRED · The allow-lists in `repo:tests/unit/test_design_tokens.py` are recorded debt awaiting the
  owner (Q-32), each naming the rule it breaks; they only shrink, and a new entry needs a decision-log row.

## 12. Decision log

`design/decision-log.md`: every rule's status, date, owner, basis and reason. A status changes there and here
together, or §13 (a) fails.

## 13. Checks — the validation loop

`design/checks.md`: (a) `repo:tests/unit/test_design_tokens.py` and the web unit tests, in CI; (b) captures,
`design_capture.py`; (c) axe and the keyboard walk; (d) the owner's approval of an example or rule; (e) M-ROUTE. Every
UI change reports the rules it changed, each intentional exception (ID, reason, evidence), and the output of (a), and
of (b) and (c) for its routes.
