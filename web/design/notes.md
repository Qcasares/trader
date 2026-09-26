# Notes — the reasons and the record behind `web/DESIGN.md`

<!-- Split out of DESIGN.md on 2026-09-26, verbatim but for the statuses, when the contract was cut to its rules so an
     agent can read it before every UI change. Read this file when changing a token, a rule or a pattern
     (web/CLAUDE.md). -->

Nothing here binds. `DESIGN.md` is the contract, and where its wording and the wording below differ, `DESIGN.md`
governs; each rule's status, date, owner and basis are in `decision-log.md`.

What this file is: `DESIGN.md` §0–§11 as adopted on 2026-09-26, before the contract was cut to its rules. Each rule
appears as it was first written — the fuller statement, its *Basis*, what shipped at `0ec084f` (*At `0ec084f`*) and what
the adopting change did (*Today*) — under the ID it keeps in `DESIGN.md`, without the status, which lives in the
contract and the log. The as-shipped tables (anatomy measurements, states, responsive behaviour, the axe findings),
the vendored-edit log (K-8), the full component table (§5.1), the token table with its `components/ui` names and JSON
paths (§1), the Jev table with its sources (§10) and the reasons for the look (§0.4) are here and nowhere else.

Section numbers are `DESIGN.md`'s, and "above", "here" and "this contract" mean `DESIGN.md`. §12, the decision log, is
now `decision-log.md`; §13, the checks, is `checks.md`. When a rule changes, change `DESIGN.md` and the log, and this
file where the reason or the record changes: a *Today* that has stopped being true is worse than none.

## How the contract introduced itself

Paths are relative to `web/` unless prefixed `repo:`. Code citations (`globals.css:N`, `components/…:N`, `repo:…:N`)
are to commit `0ec084f`; `0ec084f:DESIGN.md:N` is line N of the former root `DESIGN.md`, kept verbatim in REFERENCE
Appendix A. `REFERENCE §n`, `Q-n` and `FX-n` point into `REFERENCE.md`. Exact token values live in `design-tokens.json`;
the scale tables below quote them for reading convenience, and **if a quoted value ever disagrees with the token file,
the token file wins** (and §13 (a) fails if the token file disagrees with `globals.css`).

This contract describes the target the adopting change reached. Where a rule records what shipped at `0ec084f`, it
says so; where the adopting change fixed that, it cites the `FX-n` of REFERENCE §0, which records where each fix was
re-measured on 2026-09-26 (§13 (b), (c)). A *Today* note describes the adopting change's final tree.

## The front matter, as first written

```yaml
# Implementation contract for web/. APPROVED rules bind now. INFERRED rules are the defaults an agent follows, and says
# it followed, until the owner approves them in the decision log (§12; OD-1).
status: adopted                      # OD-1, 2026-09-26
adopted: 2026-09-26
owner: Quentin Casares               # OD-1: the owner approves rules, tokens, components, examples and the log
written_against: 0ec084f             # the commit whose UI REFERENCE.md measures; the adopting change fixed FX-1..FX-23
scope: web/src/**
tokens: design-tokens.json           # DTCG 2025.10: the exact machine values. Not repeated as YAML here (D-TOK-1)
token_source_of_truth: src/app/globals.css   # D-TOK-3, Q-2
evidence: REFERENCE.md
examples: examples/README.md
routing: CLAUDE.md
checks: "§13"
product: ../PRODUCT.md
replaces: ../DESIGN.md               # OD-1: now a pointer here; its former text is REFERENCE.md Appendix A
```

## 0. How to read this contract

### 0.1 The status of a rule

Each rule carries exactly one status:

| Status | Meaning |
|---|---|
| **APPROVED** | Decided by the owner (OD-n, §0.2), already a rule in `repo:CLAUDE.md`, or enforced by an existing test. Restated here because the UI is where it is kept or broken. |
| **INFERRED** | Drafted from the evidence and from stated intent (`0ec084f:DESIGN.md`, `repo:PRODUCT.md`, code comments). The recommended default: an agent follows it *and says so*. It binds once the owner approves it in §12. |

A rule that introduces a token, component or value that does not exist yet is also flagged **PROPOSED**. A rule that
cannot be settled because sources disagree names its question (`Q-n`), and the agent asks rather than guesses.

Only the owner changes a status (OD-1). An agent never marks a rule APPROVED, and `repo:tests/unit/test_design_tokens.py`
refuses an APPROVED row in §12 that names no owner, date or basis, and a rule whose status here differs from its row.

### 0.2 Owner decisions

The owner, Quentin Casares, answered these in the session of 2026-09-26, through a structured question. Each is quoted
as decided. §12 records each as an APPROVED row, and each rule it settles is APPROVED where it appears.

- **OD-1** — **Ownership and location** (answers Q-28 and Q-1). "The owner approves design rules. The design
  system lives in `web/`: `web/REFERENCE.md`, `web/DESIGN.md`, `web/design-tokens.json`, `web/examples/`, and a short
  routing rule in `web/CLAUDE.md`. The root `DESIGN.md` becomes a pointer to `web/DESIGN.md`. Rules stay INFERRED until
  the owner approves them in the decision log." *Settles:* D-TOK-5, the statuses in §0.1, and who promotes an example
  (§13 (d)).
- **OD-2** — **Alarm state on `/system`** (answers Q-30). "Red (the blocked colour) is reserved for 'live
  money reachable': a live-trading gate open, real money able to move. A halted kill switch is a safe state and renders
  as a strong amber 'stopped' — prominent, not alarming." *Settles:* C-12, and which state of a switch is loud in G-2.
  *Leaves open:* whether "reserved" reaches past the safety controls (Q-33).
- **OD-3** — **Canonical components** (answers Q-4, Q-5 and Q-6). "shadcn components are canonical; the
  legacy base-layer rules that restyle them are scoped away. One card (hairline border), one chip style, and on every
  control the accent focus outline that already passes 3:1 non-text contrast (the shadcn ring at 1.5–2.9:1 goes)."
  *Settles:* K-15, K-16, C-8a, A-4, and the chip radius in S-6.
- **OD-4** — **Absent values** (answers Q-10 and settles H-17). "An absence says why: 'not measured' for a
  metric never computed, 'no data' for an observation that never arrived, 'missing' plus the reason for a required
  field. Never a bare dash, never 0." *Settles:* H-3r and H-17.

Recorded with these, as already following from the honesty rules rather than as a question put to the owner: a
percentage is formatted from the stored fraction by one shared formatter, never by appending "%" to a raw fraction.
H-12 carries it, and stays INFERRED for that reason.

### 0.3 Precedence

- **D-PREC** — When sources disagree, the higher one wins:
  1. `repo:CLAUDE.md` rules, the tests that enforce them, and the owner decisions (§0.2).
  2. Token values in `globals.css`, mirrored by `design-tokens.json` — for exact values.
  3. This contract: APPROVED rules, then INFERRED rules.
  4. Approved examples (`examples/README.md`) — for proportion, density and composition. **None is approved yet.** For
     interaction behaviour, the component that owns the job (§5.1) beats any screenshot (the article: "a reviewed
     component beats an old marketing graphic for interaction behavior").
  5. Shipped screens (status "shipped — awaiting owner approval") — evidence of what exists, never a source of values.
  6. Anything else (the retired Primer palette, screenshots from other tools, the article).

  Where two sources at the same level disagree, or none covers a consequential choice, stop and ask the owner. The
  former root `DESIGN.md` is historical (OD-1): it is the stated intent INFERRED rules cite, not a level in this order,
  and where it disagrees with a rule here the disagreement is an open question (REFERENCE §9.2), never a precedent.
  `repo:PRODUCT.md` is the product brief; a rule here that disagrees with it is a question for the owner too.

### 0.4 Why it looks like this

The reasons behind the palette, the type and the motion were written down before this contract, in the former root
`DESIGN.md`, and they are still the reasons: dark by default because the operator works "late, in a room lit by the
screen", with light "a full peer, not an afterthought" (`0ec084f:DESIGN.md:11-16`); attention carried by chroma, so a
refusal is louder than a pass, because "an operator opens this to find out what is wrong" (:70-74); `--unknown` amber
and not grey, because an unmeasured figure in the quietest colour available is "the easiest thing on the page to miss"
(:89-99); figures in mono and words in sans (:129-132); motion that "reports a change and does nothing else" (:193).
REFERENCE Appendix A has the full text. The rules below cite the lines they adopt.

---

## 1. Colour — semantic tokens named by job

The existing names are kept; this table documents the job each already does (REFERENCE §2.1). By the article's test
("`color-text-primary` explains intent; `dark-gray` only describes the current value"), most names state a role
(`--bg`, `--panel`, `--text`, `--accent`, `--blocked`, `--unknown`, `--settled`), but `--panel-2` is an ordinal, and
`--accent-dim`, `--border-strong`, `--muted` and `--faint` describe a look or a level rather than a job; the "Job" column
is what supplies the role. Renaming them is a code change and is not proposed here.

"Utility for product code" names the product utility to use. Six of them were not used anywhere at `0ec084f` (`bg-bg`,
`bg-brand`, `text-brand`, `text-brand-ink`, `bg-brand-dim`, `border-blocked`; REFERENCE §2.1): the page background is
set by `body` (`globals.css:299`), and the accent reaches product code as `border-l-brand` (`AppNav.tsx:129`), the link
colour (`globals.css:752`) and shadcn's `bg-primary` / `ring` inside `Button`.

| Job | CSS token (unchanged) | Utility for product code | Utility inside `components/ui` | JSON path |
|---|---|---|---|---|
| Page background | `--bg` | `bg-bg` (unused; `body` sets it) | `bg-background` | `color.surface.bg` |
| Raised surface: card, sidebar, header, sheet, metric cell | `--panel` | `bg-panel` | `bg-card`, `bg-popover` | `color.surface.panel` |
| Inset / hover / chip surface, active nav | `--panel-2` | `bg-panel-2` | `bg-secondary`, `bg-muted`, `bg-accent` | `color.surface.panel-2` |
| Hairline divider, container edge, the card's edge (C-8a) | `--border` | `border-line` | `border-border` | `color.surface.border` |
| Control boundary, table-head rule | `--border-strong` | `border-line-strong` | `border-input` | `color.surface.border-strong` |
| Primary text | `--text` | `text-ink` | `text-foreground` | `color.ink.text` |
| Secondary text, labels, placeholders | `--muted` | `text-ink-muted` | `text-muted-foreground` | `color.ink.muted` |
| De-emphasised but read (unreachable stages, nav group heads) | `--faint` | `text-ink-faint` | — | `color.ink.faint` |
| Committing action, selection, focus, link | `--accent` | `bg-brand`, `text-brand` | `bg-primary`, `ring` | `color.accent.accent` |
| Text on an accent fill | `--accent-ink` | `text-brand-ink` | `text-primary-foreground` | `color.accent.accent-ink` |
| Accent hover (legacy only) | `--accent-dim` | `bg-brand-dim` | — | `color.accent.accent-dim` |
| Refused or failed; on a safety control, live money reachable (C-12) | `--blocked` | `text-blocked`, `border-blocked` | `bg-destructive`, `text-destructive` | `color.signal.blocked` |
| Not measured, indeterminate, model-authored; under ▲, a gate not yet passed (`caution`, C-5) | `--unknown` | `text-unknown` | — | `color.signal.unknown` |
| A safety switch that is off: the fill of the `stopped` chip (C-12r). **PROPOSED** (Q-34): shipped by the adopting change, not yet approved | `--stopped` | `bg-stopped`, `border-stopped` (inside `StatusBadge` only) | — | `color.signal.stopped` |
| Text and glyph on a `--stopped` plate. **PROPOSED** (Q-34) | `--stopped-ink` | `text-stopped-ink` (inside `StatusBadge` only) | — | `color.signal.stopped-ink` |
| Met, passed, alive | `--settled` | `text-settled` | — | `color.signal.settled` |

Values, both themes: `design-tokens.json` (`$value` = the unconditional `:root` palette, which is the dark one;
`$extensions["com.github.qcasares.trader"].light` = the `prefers-color-scheme: light` palette).

**Roles that are missing** — each is PROPOSED, each names only a value that already ships, except where marked "value
TBD", which the owner must choose. (`--stopped` and `--stopped-ink`, in the table above, are PROPOSED too, but they are
not missing: the adopting change declared them in `globals.css` for C-12r, and they wait on Q-34.)

| PROPOSED token | Replaces | Value |
|---|---|---|
| `--blocked-ink` | `text-white` (`ui/button.tsx:14`), `oklch(0.99 0 0)` (`globals.css:632`) | **TBD** — must clear 4.5:1 on the destructive fill at rest *and* hover in both themes; white gives 5.65/9.21 at rest and **3.22** on dark hover (REFERENCE §2.6) |
| `--scrim` | `bg-black/50` (`ui/sheet.tsx:39`) | black at 50 %, as shipped |
| `--warn-surface` / `--warn-edge` | `.banner-warn` mixes | `--unknown` at 10 % / 42 % (`globals.css:490-493`) |
| `--info-surface` / `--info-edge` | `.banner-info` mixes | `--accent` at 10 % / 38 % (`:494-497`) |
| `--bad-surface` / `--bad-edge` | `.banner-bad` mixes | `--blocked` at 12 % / 48 % (`:498-501`) |
| `--chip-edge` | chip borders at 40 / 45 / 52 % | 40 %, the `StatusBadge` edge (`ui/badge.tsx:61-63`), now that it is the one chip (OD-3) |

Rules:

- **C-1** — Colour reaches the DOM only through the tokens above: no hex/`rgb()`/`hsl()`/`oklch()` literal, no
  Tailwind palette colour (`text-white`, `bg-black/50`, `bg-red-500`), no arbitrary colour (`bg-[#…]`) in `web/src`
  outside the allow-list in `repo:tests/unit/test_design_tokens.py`. *Basis:* REFERENCE §2.3 (zero literals in TSX at
  `0ec084f`); `globals.css:166-172` "One palette, defined once". *Check:* §13 (a).
- **C-2** — Product code uses the product utility names (`bg-panel`, `text-ink-muted`, `border-line`,
  `border-l-brand`); the shadcn names stay inside `components/ui`. *Basis:* the codebase already does this —
  `text-ink-muted` ×89 in product code (and once in `ui/badge.tsx:65`), shadcn names only in `ui/` (REFERENCE §2.1;
  EC §1.3).
- **C-3** — shadcn's `accent` is `--panel-2` here, never the brand; brand is `brand` or `primary`. *Basis:*
  `globals.css:183-189`.
- **C-4** — A missing measurement is `unknown`, not `fail`. *Basis:* `repo:CLAUDE.md:301`;
  `repo:tests/unit/test_programme_scorecard.py::TestUnknownIsNotFail`, which tests the scorecard's rows in Python — not
  the page.
- **C-4r** — It renders as `StatusBadge status="unknown"` (amber, `?`), never `blocked`, and never in the
  treatment of a stopped switch (C-12r). *Basis:* `components/StatusBadge.tsx:14-25`; `globals.css:89`.
- **C-5** — The four statuses mean exactly: `settled` measured and met; `blocked` measured and not met, or
  refused or failed — and on a safety control only a state in which live money is reachable (C-12); `unknown` not
  measured (and model-authored); `mute` real, reported, not interesting — including `queued`/`running`, which are known
  states. Never `mute` for "we don't know", and never `unknown` for a known state such as a stopped switch (C-12r).
  *Basis:* `components/StatusBadge.tsx:14-25, :48-50`; `globals.css:88-90`; OD-2. *Open:* whether OD-2's reservation
  also takes red from failed or expired jobs, a stale heartbeat, and refusals and failures elsewhere is Q-33; until it
  is answered they stay `blocked`, because moving them to amber would render "failed" in the colour of "not measured".
  *Today:* six states, not four. `stopped` is C-12r's. `caution` is a promotion gate taken whole that has not passed
  (`promotionGateStatus`, `GateChecklist`'s summary chip): `unknown`'s amber under ▲, the `.pill-warn` the chip was
  at `0ec084f`. The chip turned `blocked` on its way onto `StatusBadge` (FX-9) and is amber again, because red past
  the safety controls is Q-33; each unmet criterion in the gate stays `blocked`, measured and refused.
- **C-6** — Attention is carried by chroma: `blocked` is the loudest thing on a page and `settled` the
  quietest; success is never styled louder than a failure beside it. *Basis:* `globals.css:36-40, :75-77`;
  `repo:PRODUCT.md:83-86`; `0ec084f:DESIGN.md:70-74`.
- **C-7** — Accent is for the committing action, selection, focus and links; never decorative; about a tenth
  of any surface at most. *Basis:* `globals.css:62-65`; `0ec084f:DESIGN.md:18-20, :56`.
- **C-8** — Every bordered element names its border colour, and the base layer defaults a bare `border` to
  the hairline — `*, ::before, ::after { border-color: var(--border); }` — so it can never fall back to `currentColor`,
  which at `0ec084f` outlined every shadcn Card and the sheet in the text colour. *Basis:* REFERENCE §2.5; ES P-1.
  *Today:* the base default ships (the adopting change; FX-8), and the card names its edge as well (C-8a).
- **C-8a** — The card's edge is a hairline: 1px `--border`, never the text colour. *Basis:* OD-3 ("One card
  (hairline border)"). *At `0ec084f`:* the shadcn Card rendered `currentColor`, 15.4–16.6:1 against the page
  (superseded, FX-8).
- **C-9** — PROPOSED · The missing roles in the table above become tokens before any new use of the literal
  they replace. *Basis:* REFERENCE §2.2-2.3. The one role the adopting change did add, `--stopped` with `--stopped-ink`,
  replaced no literal: it is C-12r's plate, PROPOSED until the owner answers Q-34.
- **C-10** — Light is a peer, not a fallback: every colour pairing is checked in both schemes. *Basis:*
  `0ec084f:DESIGN.md:11-16`. *Check:* §13 (b), (c).
- **C-11** — No palette, surface or type change moves toward the stated anti-references: navy-and-gold with a
  serif wordmark; monospace green on black (monospace *numerals* are fine, the terminal aesthetic is not); cream, sand
  or any warm near-white surface, or neutrals tinted warm; the GitHub Primer palette and the generic SaaS blue. A new
  hue or surface is checked against this list before it lands. *Basis:* `repo:PRODUCT.md:52-68`;
  `0ec084f:DESIGN.md:29-31`, :57, :226-231; `globals.css:15-21`, :45-47; REFERENCE §8.1.
- **C-12** — On a safety control — the three live-order gates and the kill switch on `/system` — red
  (`blocked`) means one thing: live money is reachable, a live-trading gate open, real money able to move. A halted kill
  switch is a safe state and renders as a strong amber "stopped": prominent, not alarming. *Basis:* OD-2 (Q-30). *At
  `0ec084f`:* an open gate was red, as it stays (`system/page.tsx:56-72`); a halted kill switch was the red `✕ halted`
  (:163-164), superseded (FX-12).
- **C-12r** — The stopped state is a `StatusBadge` state of its own, not `unknown`: `unknown` means not
  measured (C-4r), and a stopped switch is a known state. It carries its own glyph and the word "stopped" (A-6), in a
  treatment heavier than the `unknown` chip, so that "stopped" and "not measured" can never be read as one another. A
  page asks for the state, never for the colour (K-2): `killSwitchStatus` and `liveGateStatus` in `StatusBadge.tsx` map
  the two safety controls. The programme switch fails closed as well (`repo:CLAUDE.md:90-94`), and its off state
  (`mute` "disabled" at `0ec084f`) is safe for the same reason, so it is never red either. *Basis:* OD-2; C-4r; C-5; A-6.
  *Today:* shipped by the adopting change (FX-12) as an amber plate with dark ink and the ■ glyph — the `stopped`
  variant, on tokens of its own, `--stopped` and `--stopped-ink`, because light `--unknown` is darkened for text and
  reads brown as a fill. This rule asked for the amber of `--unknown` "unless the owner approves a token of its own";
  the tokens are PROPOSED until the owner answers Q-34.
- Open, not a rule: whether dark `--bg` should stay `#0e1116`, Primer's value (Q-3).

## 2. Typography

**Scale** (exact values from `design-tokens.json` `type.size`; line-height as rendered, REFERENCE §3.2-3.4). "Job"
quotes the stated source (`globals.css:103-109`, `0ec084f:DESIGN.md:112-120`); "as shipped" marks an observation that
is not yet a rule. Line-heights come from Tailwind's defaults and element rules, not from a token (T-7, Q-14).

| Token | rem | px | Utility | Line-height as rendered | Job |
|---|---|---|---|---|---|
| `--t-xs` | 0.6875 | 11 | `text-xs` | 14.67 (Tailwind default ratio) | uppercase labels, metric keys, pills (`0ec084f:DESIGN.md:114`); as shipped also table heads |
| `--t-sm` | 0.75 | 12 | `text-sm` (**not 14px**) | 17.14 | table cells, dense metadata (`globals.css:104`); as shipped also shadcn buttons, labels and desktop inputs — which the stated source puts at 13px (Q-29) |
| `--t-base` | 0.8125 | 13 | `text-base` (**not 16px**) | 19.5 | secondary prose, inputs, buttons (`0ec084f:DESIGN.md:116`); as shipped also banners, legacy controls and phone-width shadcn inputs |
| `--t-body` | 0.875 | 14 | `text-body` | 21.7 (body 1.55) | body |
| `--t-md` | 1 | 16 | `text-md` | inherited | h3, metric values |
| `--t-lg` | 1.1875 | 19 | `text-lg` | 24.7 (1.3) | h2; h1 at ≤640px |
| `--t-xl` | 1.4375 | 23 | `text-xl` | 28.75 (1.25) | h1 |

**Families:** `--sans` for words, `--mono` for figures (`design-tokens.json` `type.family`). **Weights in use:** 400,
500, 600 (REFERENCE §3.5).

- **T-1** — Sizes come from the seven steps only; no `text-[Npx]`; nothing renders below 11 CSS px —
  including SVG chart text at 390px wide (3.6px at `0ec084f`; superseded, FX-20: the chart draws in CSS pixels and sets
  its axis text at `--t-sm`). *Basis:* `globals.css:99-109`; REFERENCE §3.3. *Check:* §13 (a) refuses new arbitrary
  sizes; (b) measures chart text, and passed at 390px on 2026-09-26.
- **T-2** — Read a size utility by its value here, not by its upstream meaning: `text-sm` is 12px and
  `text-base` 13px, so vendored shadcn classes render one step smaller than shadcn intends. *Basis:*
  `globals.css:246-252`; O-9. The consequence for controls — 12px shadcn buttons, labels and desktop inputs against the
  13px `0ec084f:DESIGN.md:116` states — is Q-29, which OD-3 did not settle.
- **T-3** — Words in sans, figures/identifiers/code in mono. A sentence is never set in mono (Q-11 decides
  the shipped exceptions: assumption values, hypothesis fields, all inputs). *Basis:* `0ec084f:DESIGN.md:129-132`;
  `repo:PRODUCT.md:59-60`; `globals.css:636-640`.
- **T-4** — Every figure uses tabular numerals; numeric columns are right-aligned with their header.
  *Basis:* `globals.css:307-311, :653`; `repo:PRODUCT.md:119-120`.
- **T-5** — One `h1` per page in every state (loaded, loading, error, empty). Section titles are real
  headings (`h2`), at one size and weight; no level is skipped. OD-3 settles the card, not its title's element or
  weight (Q-9). *Basis:* axe `heading-order`, `page-has-heading-one` (REFERENCE §6.7); REFERENCE §3.5. *Today:*
  `CardTitle` renders an `h2` (FX-15), and axe finds no skipped level on any route; `/system` keeps its `h1` when its
  first load fails (FX-23); the other pages' loading and error states are not captured, so not re-measured.
- **T-6** — PROPOSED `--track-caps: .045em` (the value used six times, `globals.css:518`): one uppercase
  treatment — 11px, uppercase, `--track-caps` — for metric keys, table heads, nav group heads and stage heads. Retires
  `tracking-[0.03em]` and `.04em`. Chips are not uppercase: the one chip is `StatusBadge` (OD-3). *Basis:*
  REFERENCE §3.6. *Today:* the adopting change gave the shadcn `TableHead` its own caps treatment, with Tailwind's
  `tracking-wider` (0.05em): a fourth value, which `--track-caps` would retire too.
- **T-7** — PROPOSED line-height tokens, one per size step; values are the owner's choice (Q-14). Until then
  no new literal line-height. *Basis:* REFERENCE §3.4.
- **T-8** — Running prose is capped at 65–75ch; tables and dense metadata run as wide as they need.
  *Basis:* `0ec084f:DESIGN.md:134-135`.
- **T-9** — Type sizes are fixed rem: no `clamp()`, no viewport units. The ≤640px h1 step (19px) is the one
  responsive size. *Basis:* `globals.css:99-102, :883`; `0ec084f:DESIGN.md:109-110`.
- **T-10** — System stacks, no web font. Consequence: text width and wrapping are only comparable between
  captures made on the same OS (E-12). *Basis:* `globals.css:92-97`; REFERENCE §3.1.

## 3. Spacing, radius, borders, elevation, stacking

**Spacing scale** (`design-tokens.json` `rhythm.space`; Tailwind's step is 4px × n and is not bridged, so map by value):

| Token | px | Tailwind step | Observed job (REFERENCE §4.2-4.3) |
|---|---|---|---|
| `--s-1` | 4 | `1` | h1→intro (`mb-1`), metric key→value, legacy `.pill` glyph gap (`globals.css:680`; the `StatusBadge` glyph gap and chip rows are 6px, `gap-1.5`, `ui/badge.tsx:37`, `system/page.tsx:323`) |
| `--s-2` | 8 | `2` | table cell padding, label→control (`space-y-2`) |
| `--s-3` | 12 | `3` | **section→section**, card inner gap, metric cell padding, banner padding |
| `--s-4` | 16 | `4` | card padding, header→first block (`mb-4`), phone gutter |
| `--s-5` | 24 | `6` | desktop gutter (`md:px-6`) |
| `--s-6` | 32 | `8` | legacy h2 top margin, which is what set the sidebar's group headings 48px apart with the nav's 16px gap; `AppNav` states it itself (`mt-8`) since K-15 scoped the rule away |
| `--s-7` | 48 | `12` | empty-chart padding, footer bottom |

**Radius:** `--radius` 6px (containers and shadcn controls), `--radius-sm` 4px (nav rows, sort buttons, legacy
controls, skip link, focus outline). **Stacking:** `--z-sticky` 100, `--z-dropdown` 200, `--z-backdrop` 300,
`--z-modal` 400, `--z-toast` 500. `--z-sticky` has no user since the adopting change deleted the legacy `.topbar`; it is
kept, as the token for the next sticky element, rather than deleted and re-added.

- **S-1** — Spacing uses the scale: Tailwind steps `0`, `1`, `2`, `3`, `4`, `6`, `8`, `12`, plus `px` for a
  hairline gap only (1px is not an `--s-*` step; it is the metric grid's gap, `globals.css:508`). Nothing new at `0.5`,
  `1.5`, `2.5`, `5`, `7`, `9`, `10`; whether 6px (`1.5`, 246 uses) joins the scale is Q-13. *Basis:*
  `globals.css:111-119`; REFERENCE §4.1. *Check:* none yet — §13 (a) does not scan spacing steps ("Not covered").
- **S-2** — Page sections are 12px apart (`gap-3`/`mt-3`/`space-y-3`), never 0. *Basis:* measured on every
  page (REFERENCE §4.2); disagrees with `0ec084f:DESIGN.md:139-140` ("sections breathe at `--s-6`") — Q-12. The two
  0px joins at `0ec084f` each involved a legacy `.card` (superseded, FX-8): both measured 12px on 2026-09-26 — the
  candidate page's gate under its Configuration card, and `/system/configuration`'s Credentials card under the "Save
  changes" row.
- **S-3** — Page header block → first section: 16px (`mb-4`, 11 pages); the `.subtitle` 24px margin is the
  exception to retire. *Basis:* REFERENCE §4.2.
- **S-4** — Label → control: 8px (`space-y-2`); the legacy `label { margin-bottom: 12px }` never reaches a
  shadcn `Label` (K-15). *Basis:* five values render at `0ec084f` (3/4/6/8/12px, REFERENCE §4.2). Three of them are on
  the scale (4px findings, 8px `/system`, `/programme`, candidate; 12px from the legacy rule); 8px is this contract's
  choice among them, not the only candidate, and 6px waits on Q-13.
- **S-5** — Padding: card and section 16px; metric cell and banner 12px; table cell 8px. *Basis:* REFERENCE
  §4.3.
- **S-6** — Radii: `--radius` for containers and controls, `--radius-sm` for small interactive items, and
  fully round for the one chip, `StatusBadge` (the chip clause follows OD-3). No 2px or 10px literal in new work.
  *Basis:* REFERENCE §4.7; OD-3.
- **S-7** — No shadows in product code: hierarchy comes from the surface steps (`bg` → `panel` → `panel-2`)
  and hairlines. Tailwind's default shadows (hard-coded black alpha) stay confined to `components/ui`. *Basis:*
  REFERENCE §2.3, §4.7. *Check:* §13 (a).
- **S-8** — Borders are 1px; the active nav item's 2px accent rule is the only heavier one. *Basis:*
  REFERENCE §4.7.
- **S-9** — Stacking uses the named scale, never an arbitrary number; whether to bridge it into Tailwind or
  accept `z-50` is Q-25. *Basis:* `globals.css:132-138`; `0ec084f:DESIGN.md:152-153`.
- **S-10** — No bordered box inside a bordered box. Whether the metric grid and pipeline cards are
  exceptions is Q-18. *Basis:* `globals.css:460-462`; `0ec084f:DESIGN.md:142-144`.

## 4. Layout, grid, breakpoints

- **L-1** — `AppShell` is the only shell. Desktop (≥`md`, 768px): 208px sticky sidebar + `main` with 24px
  gutters. Phone: 53px sticky header + a 240px left `Sheet`. `/login` is bare. *Basis:* REFERENCE §4.4.
- **L-2** — Breakpoints are min-width only: `sm` 40rem (640px), `md` 48rem (768px, the shell switch), `lg`
  64rem (1024px). No `xl`/`2xl`, no new `max-width` queries; the legacy block at `globals.css:877-884` migrates onto
  these. *Basis:* REFERENCE §4.5. These values are Tailwind 4.3.3's defaults (`compiled:2528`, :2536, :2557); nothing
  in `globals.css` declares them, so `design-tokens.json` does not hold them, the precedence rule "the token file wins"
  cannot apply to them, and no check guards them (Q-31).
- **L-3** — Data runs full width; prose is capped in `ch` (T-8). Whether `main` gets a maximum width is Q-15.
  *Basis:* REFERENCE §4.4.
- **L-4** — Reuse the observed grids before defining a new one; a new one is added here:

  | Grid | Definition | For |
  |---|---|---|
  | Metric grid | `repeat(auto-fit, minmax(170px, 1fr))`, 1px hairline gaps | a set of headline figures |
  | Field grid | `repeat(auto-fill, minmax(200px, 1fr))`, gap 0 16px | settings forms |
  | Form grid | `grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3` | generated parameter forms |
  | Assumption rows | `190px 1fr`, one column ≤640px | "what this figure depends on" |
  | Gate rows | `84px 1fr`, one column ≤640px | criterion lists with a status chip |
  | Two-up | `grid gap-3 lg:grid-cols-2` | paired cards |
  | Page header row | `mb-4 flex flex-wrap items-end justify-between gap-3` | h1 + intro + actions |
  | Board | horizontal scroll, 208px columns, gap 12px, `scroll-snap-type: x` | the pipeline |

- **L-5** — A metric grid never paints an empty track (a 766×66px `--border` block on Portfolio at
  `0ec084f`). *Basis:* O-18; ES P-16.
- **L-6** — The document never scrolls sideways; wide content scrolls inside its own focusable, labelled
  region (A-7). *Basis:* `0ec084f:DESIGN.md:146-150`; REFERENCE §4.9.
- **L-7** — Page header: `h1` + at most one intro paragraph (one style, 68ch, `--muted`) + actions or the
  page's status chip, bottom-aligned right. Replaces the three intro styles (REFERENCE §6.3 item 13).

## 5. Components — anatomy, states, reuse

### 5.1 Who owns which job

"Canonical" means OD-3 chose it; "shipped" means it exists and nobody has approved it as the pattern yet.

| Job | Owner (file) | Status | Merge into the owner, then delete |
|---|---|---|---|
| Shell, navigation | `AppShell`, `AppNav` | shipped | — |
| Section surface | `Card` (`ui/card.tsx`), hairline `--border` edge, title an `h2` | **canonical** (OD-3, K-16, C-8a) | done: the legacy `.card` and `.card-head` are gone (`/system/configuration`, `GateChecklist`; FX-8) |
| Domain status | `StatusBadge` + its mappers (`jobStatus`, `livenessStatus`, `killSwitchStatus`, `liveGateStatus`, `promotionGateStatus`) | **canonical** (OD-3, K-16); the `stopped` state of C-12r lives here (FX-12) | done: `.pill-*` and `.badge` are gone (FX-9). Still to merge: the per-page status maps (`CANDIDATE_STATUS` ×2, `CONCLUSION_STATUS` ×2, …) into one mapper module |
| Model-authored marker | `AiBadge` (`GateChecklist.tsx:117-124`) | shipped; renders through the one chip | `.badge` for "AI-authored" |
| Action | `Button` (`ui/button.tsx`) | **canonical** (OD-3, K-16) | legacy `button`, `button.primary`, `.linklike`, raw `<button>` in sort headers and the reveal toggle |
| Field | `Input`, `Label`, `Select` (`ui/`) | **canonical** (OD-3, K-16) | legacy `label > span`, native `select`, `.hint` |
| List of rows | `DataTable` | shipped | raw rows (the scorecard's, which since FX-17 scroll inside the shadcn `Table`); direct `Table` except small static tables |
| Caveat / error / note | **`Banner`** (tone `warn`/`info`/`bad`) | **PROPOSED** — wraps the shipped `.banner-*` look, adds live-region roles (A-9) | 27 hand-written `.banner-bad`; unused `ui/alert` |
| Headline figure | **`Metric`** (`value \| null`, format, unit, hint) | **PROPOSED** | the three local `Metric` helpers; hand-written `.metric` blocks |
| Absent value | `Absent` (`components/Absent.tsx`; `kind` = `not-measured`, `no-data`, or `missing` with a `reason`) | shipped by the adopting change (FX-7); the words are OD-4's (H-3r, H-17) | every "—", `?? 0`, `?? 252` |
| Sharpe | **`SharpeFigure`** (estimate, SE, significant) | **PROPOSED** | the three Sharpe renderings (H-1r) |
| Formatting | `lib/format.ts`: the one place a stored fraction becomes a percentage (`fmtPct`, H-12) and the one home of the absence words (`ABSENCE_WORDS`, OD-4) | shipped | at `0ec084f`: `fmtAge` ×3, `money()`, `usd()`, `Figure` (REFERENCE §6.3 item 8) |
| Equity curve | `EquityChart` | shipped | — |
| Loading | `Skeleton` (`components/Skeleton.tsx`) | shipped | unused `ui/skeleton.tsx` |
| Gate | `GateChecklist` | shipped; on `Card` + `StatusBadge` since the adopting change (FX-8, FX-9) | — |
| Committing confirmation | **`TypedConfirm`** (phrase, tone, onConfirm) | **PROPOSED** | three hand-built typed inputs; `window.prompt` ("RAISE AUTONOMY") |
| Page header | **`PageHeader`** (title, intro, actions) | **PROPOSED** | the 9-file header row + 3 plain divs |
| Back link | ghost `Button` + `ArrowLeft` at the page foot (4 of 5 uses) | shipped | the report's top text link |
| Credential | `SecretField` | shipped | — |
| Element defaults (`button`, `label`, `input`/`select`/`textarea`, `h1`–`h3`, `th`/`td`, `li`, `p`) | the legacy `@layer base` sheet, `globals.css:291-904` | scoped to the legacy markup (K-15, OD-3; FX-10) | goes as the last legacy page migrates |
| Jev answer | **`JevAnswer`** | **PROPOSED**, planned (`repo:docs/08-jev-integration.md:631`) | — |

### 5.2 Rules

- **K-1** — One owner per job (5.1). Extend the owner — a variant or a prop — before creating a sibling; a
  new component needs a row in 5.1 and an entry in the decision log. *Basis:* the article ("a near-duplicate component
  appears instead of extending the owner"); REFERENCE §6.3 lists 13 near-duplicate families.
- **K-2** — A page never maps a domain state to a colour: it asks `StatusBadge` for a `Status` and always
  passes a written label. *Basis:* `components/StatusBadge.tsx:4-12`.
- **K-3** — Every interactive component implements default, hover, `:focus-visible`, active and disabled,
  plus invalid (`aria-invalid`) for fields and busy (`aria-busy` + changed label) for committing actions. At `0ec084f`
  shadcn buttons had no active style, `aria-invalid` was never set, and no component had a busy state. *Basis:*
  `0ec084f:DESIGN.md:157`; REFERENCE §6.2 / EC §5.2.
- **K-4** — Button variant by job: `default` (filled accent) = the committing action; `outline` = other
  actions; `ghost` = navigation, back, per-row "view"; `link` = inline. Whether stopping actions are filled
  `destructive` is Q-8; whether a disabled primary keeps its fill is Q-7. *Basis:* `0ec084f:DESIGN.md:159-164`;
  `repo:PRODUCT.md:88-92`.
- **K-5** — A field and its committing button share a `<form>`; Enter submits; errors render inline next to
  the field, tied with `aria-describedby` and `aria-invalid`. *Basis:* REFERENCE §6.5 (only `/login` has a form).
- **K-6** — Tables: sortable headers look exactly like plain headers (11px caps, T-6), expose `aria-sort`,
  and sort unknowns last in both directions (as `DataTable.tsx:114-120` already does); the filter searches every
  column's visible text; cells holding prose wrap. *Basis:* REFERENCE §6.1, O-12, O-20.
- **K-7** — Banner tone follows meaning — `warn` for a caveat or an unmeasured state, `info` for an
  explanation, `bad` for a failure; a caveat about a figure sits *above* the figure. *Basis:* `globals.css:490-501`;
  REFERENCE §7 (synthetic banner below the chart).
- **K-8** — Vendored `components/ui` files change only to fix a defect or to bind to tokens, and each change is
  logged here, because `shadcn add` overwrites them (Q-24). *Basis:* `ui/card.tsx:5-16`. The log — each file's own
  comment says why, and `shadcn add` would undo every line of it:
  - `card.tsx`: 16px padding and the 6px radius (before this contract); the edge names the hairline, `border-border`
    (C-8a); `CardTitle` renders an `h2` (T-5).
  - `badge.tsx`: no focus ring (A-4); the `settled`, `unknown`, `blocked` and `mute` variants (before this contract),
    the `stopped` plate (C-12r) and `caution`, `unknown`'s classes under the ▲ glyph (C-5).
  - `button.tsx`: no focus ring (A-4); `transition-colors` instead of `transition-all`, which animated the outline in;
    a `ghost` or `outline` button rendered as a link takes the link colour (`[a&]:text-primary`), which the legacy
    `a` rule supplied until K-15 scoped it away (as a `<button>` each keeps the text colour).
  - `input.tsx`: no focus ring (A-4); mono, tabular and the text colour stated in the component, where the legacy
    `input` rule used to supply them (K-15).
  - `select.tsx`: no focus ring and no suppressed outline on the trigger or an option (A-4); no `tw-animate-css`
    classes (M-4).
  - `sheet.tsx`: no enter or exit animation (M-4); the close button is a 32px target with the one focus indicator,
    its icon `aria-hidden` (A-4, A-10).
  - `table.tsx`: the head is the 11px caps label ruled in `--border-strong`, rows rule in the hairline (K-6, K-15); the
    container is a focusable region, named by the `label` prop, while — and only while — the table overflows (A-7).
  - `dropdown-menu.tsx`, `tooltip.tsx` (both unused): no animation classes (M-4); no suppressed outline on a menu
    item (A-4).
- **K-9** — Icons are lucide, `aria-hidden` when decorative (including inside `ui/`), one distinct icon per
  nav destination. Sizes as shipped: 14px (`size-3.5`) in nav rows and in controls that are not a `Button`
  (`AppNav.tsx:133`, `DataTable.tsx:155`, `SecretField.tsx:176,178`); 16px inside a `Button`, which sizes any unsized
  icon (`[&_svg:not([class*='size-'])]:size-4`, `ui/button.tsx:8`; `compiled:2654-2657`); 12px for the sort glyphs
  (`size-3`, `DataTable.tsx:196-202`). Whether these become one size is not settled. *Basis:* REFERENCE §6.1; EC §1.4(e),
  §4.3 (`Activity` twice), §7.2.
- **K-10** — Every route lights exactly one nav item; detail routes light their parent. *Basis:*
  `components/AppNav.tsx:24-28`; the candidate and experiment pages light none (REFERENCE §6.1).
- **K-11** — Committing or raising actions confirm through `TypedConfirm`; `window.prompt` is not used.
  *Basis:* REFERENCE §6.3 item 12; `repo:PRODUCT.md:88-92`.
- **K-12** — One back-link pattern: ghost `Button` + `ArrowLeft` at the page foot. *Basis:* 4 of 5 uses
  (REFERENCE §6.3 item 11).
- **K-13** — Model-authored content always shows `AiBadge`, rendered through the one chip, with its meaning
  visible, not only in `title`. *Basis:* `GateChecklist.tsx:112-124`; `globals.css:522-524`.
- **K-14** — A new instance of a component follows the *order of parts* in 5.3. Its measurements are
  observations, not rules: reuse one only where no other rule, question or stated source disagrees with it, and never
  one listed in 5.3's "Open / do not copy" column. *Basis:* the article ("'The three approved screens use 24 px between
  cards' is an observation … Mixing the two turns accidental legacy choices into doctrine"); the shipped measurements
  cited in 5.3.
- **K-15** — The legacy element rules in `@layer base` do not decide how a shadcn or Radix component looks.
  At `0ec084f` they did: every shadcn `<button>` got a 1px `--border-strong` edge, the ghost menu trigger and the
  sheet's close button a `--panel-2` fill and 7px 16px padding (`globals.css:604-615`; ES §3, O-4); a shadcn `Label`
  outside `space-y` took a 12px bottom margin that pushed the findings checkbox 6.6px off its label
  (`globals.css:573`; O-21); the sheet's `h2` title took 19px and wrapped the wordmark (`globals.css:397`; O-24)
  (all superseded, FX-10). The element rules stay for the legacy markup that still uses them and go as it migrates; the
  mechanism is an engineering choice. *Basis:* OD-3 ("the legacy base-layer rules that restyle them are scoped away");
  ES P-4; EC I-3. *Today:* scoping ended two jobs the legacy rules had been doing that nobody had written down, and
  the before/after comparison caught both: the `h2` rule's 32px top margin held the sidebar's groups 48px apart
  (they closed up to 16px), and the `a` rule coloured every ghost or outline `Button` rendered as a link (the back
  links, the per-row "view", the header "Configuration" fell back to the text colour). Each component now states
  its own: `AppNav`'s headings carry `mt-8`, and `ui/button.tsx` gives those two variants the link colour when they
  render as a link (K-8). `repo:tests/unit/test_web_components.py` holds both.
- **K-16** — shadcn components are canonical: a section surface is the `Card` (with the hairline edge of
  C-8a), a status is the one chip, `StatusBadge`, and actions and fields are the shadcn `Button`, `Input`, `Label` and
  `Select`. The legacy `.card`, `.pill-*` and `.badge` retire into them (FX-8, FX-9), and no new code uses a legacy
  class. *Basis:* OD-3 (Q-4, Q-5).

### 5.3 Anatomy as shipped

Measured at `0ec084f` (REFERENCE §6.1, §6.3; ES §3-4). **Observations, not rules** (K-14): the order of parts is the
pattern to follow; a measurement is reused only where nothing in the last column, and no other rule or stated source,
disagrees with it. OD-3 settled what the "Open" column used to ask about the card's edge and the chip.

| Component | Parts, in order | Measurements as shipped | Open / do not copy |
|---|---|---|---|
| `Card` | container → header (title, then count or chips, then right-aligned action) → content | `--panel` fill; 1px border, which is `--border` (C-8a; `currentColor` at `0ec084f`, FX-8); radius 6px; 16px vertical padding, 16px inner horizontal; 12px gap; 8px between the header's rows (`gap-2`, `ui/card.tsx:35`); title 14px/600 | title element, size and weight (T-5, Q-9) |
| `StatusBadge` | glyph (empty alternative text) → word, 6px apart | 11px, 500, mono, lowercase as written; padding 2px 8px; about 20.7px tall; `--panel-2` fill; signal-colour text and a 40 % signal edge, except `mute`: `--border` edge, `--muted` text (`ui/badge.tsx:61-65`); fully round | `stopped` (C-12r) came after the survey: a `--stopped` plate and edge, `--stopped-ink` text at 600, glyph ■; its tokens wait on Q-34. So did `caution` (C-5): `unknown`'s amber text and edge under ▲, what `.pill-warn` drew for a gate not yet passed |
| `Button` | optional icon (16px, `aria-hidden`; `ui/button.tsx:8`) → label, 8px apart (6px at `sm`, :26) | default 36px tall, `sm` 32px; 12px/500; radius 6px | text size (Q-29); disabled fill (Q-7), stop fill (Q-8); the legacy 1px `--border-strong` edge and, on `ghost`/`icon`, the `--panel-2` fill and 7px 16px padding (K-15; superseded, FX-10) |
| Field | `Label` → control → hint → error | label 12px/500; control 36px, 12px mono at ≥768px and 13px below, padding 4px 12px, `--border-strong` edge, radius 6px; hint 12px `--muted` | control text size (Q-29, Q-16; E-4 asks for nothing under 13px); label gap (S-4, Q-13); prose in mono (Q-11); input boundary 1.87–1.97:1 (A-3) |
| `Banner` (PROPOSED wrapper of `.banner-*`) | optional bold lead sentence → body → optional remedy link | 1px tone edge; tone surface fill; radius 6px; padding 12px; 13px text; 12px below | — |
| `Metric` (PROPOSED) in a metric grid | key → value → optional chip | cell `--panel`, padding 12px; key 11px uppercase `--muted`, 0.045em; value 16px mono, line-height 1.3; grid gaps 1px on `--border` | empty tracks (L-5) |
| `DataTable` | card title → filter (320×32) → table → empty or filtered-empty sentence | head 11px caps; cells 12px, padding 8px; rows about 49px with chips; numeric cells right-aligned mono | sortable head style (K-6) |
| `PageHeader` (PROPOSED) | h1 → one intro → actions or status chip, bottom-right | h1 23px/400, 4px below; intro 13–14px `--muted`, capped at 68ch on the 7 `.subtitle` pages and `/programme`, uncapped on the 6 `m-0 text-base` pages (EC §5.4 item 14); 16px to the first section (24px on the 3 `.subtitle`-last pages, S-3) | h1 weight (Q-9); intro measure (L-7, T-8) |
| `TypedConfirm` (PROPOSED) | label "Type PHRASE to …" → input (placeholder = the phrase) → commit button, disabled until the phrase matches | as `Button` and Field | — |
| Assumption row | term → value → hint | grid 190px + 1fr (one column ≤640px); padding 8px 0; gap 12px; hairline between rows; term 14px `--muted`; value 13px; hint 12px | value face (Q-11) |
| Gate criterion | chip → description → detail → evidence link | grid 84px + 1fr (one column ≤640px); padding 12px 0; description 14px; detail 13px `--muted`, ≤70ch; evidence 11px mono | the chip is `StatusBadge` (OD-3; `.pill` at `0ec084f`, FX-9); `aria-label` on a role-less span (A-8) |

### 5.4 States as shipped

The article asks for component states; K-3 asks every interactive component for the full set. This is what existed at
`0ec084f`, from code, so K-3's gaps are visible. Observations, not rules; a dash means the state has no style of its
own. **Every `:focus-visible` cell below is superseded by A-4** (OD-3; FX-11): each control now takes the 2px accent
outline at 2px offset.

| Component | Hover | `:focus-visible` | Active / current | Disabled | Invalid | Busy |
|---|---|---|---|---|---|---|
| `Button` default | fill `primary/90` (`ui/button.tsx:12`) | 1px border in `ring` + 3px ring at `ring/50` (:8) | — (the legacy `button:active` fill loses to the fill utility, EC I-24) | opacity .5, no pointer events, fill kept (:8) | `destructive` border + ring (:8); never set by app code | label swap only ("Queueing…", `page.tsx:291`) |
| `Button` destructive | fill `destructive/90` (:14) | ring `destructive/20` light, `/40` dark (:14) | — | as default | — | — |
| `Button` outline | light `bg-accent` (= `--panel-2`), dark `input/50` (:16) | as default | — | as default | — | — |
| `Button` ghost | light `bg-accent`, dark `accent/50` (:20) | as default | — | as default | — | — |
| `Button` link | underline (:21) | as default | — | as default | — | — |
| Legacy `button` | edge `--accent`, fill `--panel` (`globals.css:616`) | global 2px outline, 2px offset (:314-318) | fill `--panel-2` (:617) | opacity .45, edge `--border` (:620); `.primary` keeps its accent fill | — | — |
| `Input`, `SelectTrigger` | `SelectTrigger` dark only: `input/50` (`ui/select.tsx:40`) | border `ring` + 3px ring `ring/50` (`ui/input.tsx:12`; `ui/select.tsx:40`) | — | opacity .5 (`ui/input.tsx:11`; `ui/select.tsx:40`) | `destructive` border + ring (`ui/input.tsx:13`) | — |
| Legacy `input`, `select` | edge `--border-strong` (`globals.css:588`) | global outline | — | opacity .5 (:589) | — | — |
| Nav item | fill `--panel-2`, text `--text` (`AppNav.tsx:130`) | global outline, colour transitioning from `currentColor` (EC §7.4) | `aria-current="page"`: fill `--panel-2`, text `--text`, 2px accent left rule (:125, :129) | — | — | — |
| Table row | shadcn `muted/50` (`ui/table.tsx:60`); legacy `--panel-2` (`globals.css:652`) | — | — | — | — | — |
| Pipeline card (a link) | edge `--border-strong`, fill `--panel-2` (`programme/page.tsx:107`) | global outline | — | — | — | — |
| Link (`a`) | `text-decoration-thickness: 2px`, which draws nothing because no link is underlined (`globals.css:753`; superseded, FX-16: a link in running text is underlined, so hover thickens a line that is drawn there, A-5) | global outline | — | — | — | — |
| Sheet close | opacity .7 → 1 (`ui/sheet.tsx:78`) | 2px `ring`, 2px offset, on `:focus` (:78) | fill `bg-secondary` while open (:78) | — | — | — |
| Region loading | — | — | — | — | — | `Skeleton`: `aria-busy`, `aria-live="polite"`, hidden label (`Skeleton.tsx:27-28`, :50-51) |

## 6. Interaction, motion, reduced motion

- **M-1** — Durations: `--fast` 140ms for hover/focus/colour, `--base` 200ms for a value-changed mark;
  nothing over 250ms. PROPOSED: bridge Tailwind's default transition duration and curve to `--fast`/`--ease` (150ms
  and `cubic-bezier(0.4,0,0.2,1)` at `0ec084f`; the sheet *declared* 300/500ms, `ui/sheet.tsx:63`, but nothing it
  transitioned moved, REFERENCE §6.6, and the adopting change removed the declaration with the classes, FX-22). Note the source's own range, "150-250ms" (`globals.css:125`), excludes
  `--fast` = 140ms. *Basis:* `globals.css:124-130`; `0ec084f:DESIGN.md:190-192`; REFERENCE §6.6.
- **M-2** — Easing is `--ease` (`cubic-bezier(0.16, 1, 0.3, 1)`) only: no bounce, no elastic. *Basis:*
  `globals.css:125-128`.
- **M-3** — Motion reports a change and does nothing else: no page-load choreography. *Basis:*
  `0ec084f:DESIGN.md:193`.
- **M-4** — No class that compiles to nothing. The 55 `animate-in`/`fade-*`/`zoom-*`/`slide-*` classes either
  gain their library or go (Q-17). *Basis:* REFERENCE §6.6. *Today:* they went (FX-22), and
  `repo:tests/unit/test_web_components.py` refuses one unless `tw-animate-css` is both installed and imported.
- **M-5** — A polled value that changes is acknowledged (the `.changed` mark or its successor), because a
  figure that changes silently has to be diffed against memory (Q-17). *Basis:* `globals.css:780-787`;
  `0ec084f:DESIGN.md:194-197`.
- **M-6** — `prefers-reduced-motion` gets an alternative, not a removal: the skeleton's opacity fade (exists);
  the value-changed mark needs a static alternative (at `0ec084f` it would last 0.01ms). *Basis:*
  `globals.css:886-903`; `repo:PRODUCT.md:116`.
- **M-7** — Each polling page states its cadence in its docblock and the docs match (2 / 5 / 10 / 15s at
  `0ec084f`; `Skeleton.tsx:9` and `0ec084f:DESIGN.md:195` say ten). *Basis:* REFERENCE §6.5.
- **M-8** — While a committing request is in flight the button disables and says what is happening
  ("Queueing…"), and the region is `aria-busy`. Loading is a skeleton in the shape of what is coming, never a spinner.
  *Basis:* REFERENCE §6.2; `0ec084f:DESIGN.md:184-186`.
- **M-9** — Stopping takes one action; starting or committing takes a deliberate one (a typed phrase). The
  API enforces the asymmetry; the UI makes it visible in the control's shape. *Basis:* `repo:PRODUCT.md:88-92`.

## 7. Accessibility

- **A-1** — Target: WCAG 2.2 AA, verified by computation and by axe, not by eye. *Basis:*
  `repo:PRODUCT.md:101`; `0ec084f:DESIGN.md:205-206`.
- **A-2** — Text ≥4.5:1 in **every** state (rest, hover, active, focus) and on every backdrop it can sit on,
  in both themes. 4.5:1 is the minimum for all text: nothing renders at 24px, and the one 19px/600 text (the mobile
  sheet title) is not bold under axe-core's `boldValue: 700` (REFERENCE §2.6). Must fix: legacy primary hover (4.06 /
  3.01), destructive hover dark (3.22), primary hover light (4.39), accent link in a warn banner on the page background
  light (4.31). *Basis:* REFERENCE §2.6.
- **A-3** — Non-text ≥3:1 for the boundary that identifies a control (inputs measure 1.37–1.97) and for
  focus indicators. Chart marks that carry data meet it (equity line 7.63 / 5.35, drawdown edge 6.36 / 9.21 against
  `--panel`); the 1.37 / 1.41 grid lines are decorative. *Basis:* WCAG 1.4.11; REFERENCE §2.6; EC §7.8.
- **A-4** — One focus indicator, on every control: the accent outline, 2px at 2px offset
  (`globals.css:314-318`), which measures 5.01–8.34:1 against its backdrops in both themes. The shadcn ring
  (1.50–2.94:1) goes, and so does the sheet close's `focus:ring-2` on `:focus` (`ui/sheet.tsx:78`) (superseded, FX-11).
  "Every control" includes each internal stop of a native date input, whose calendar stop showed no indicator at
  `0ec084f` (REFERENCE §6.7). *Basis:* OD-3 (Q-6); WCAG 1.4.11; `0ec084f:DESIGN.md:219-220`; `repo:PRODUCT.md:117-118`.
- **A-4r** — The outline is visible at once, not transitioned in from `currentColor` (nav links at
  `0ec084f`, EC §7.4), and nothing suppresses it without the same outline in its place. *Basis:* A-4;
  `0ec084f:DESIGN.md:219-220` ("Never suppressed without replacement"). *Check:* the keyboard walk, §13 (c).
- **A-5** — A link inside running text is underlined. *Basis:* axe `link-in-text-block` (1.98:1 in dark).
  *Today:* underlined in a paragraph, list item, table cell, definition or banner
  (`:where(p, li, td, dd, .banner) a:where(:not([data-slot]))` in `globals.css`; FX-16), and nowhere else. The
  adopting change first underlined every link on the site, wider than this rule asks; the report's "← Programme" and
  the skip link were the ones it reached that nothing opted out. The sidebar's rows sit in list items and say
  `no-underline`; a `Button` rendered as a link carries a `data-slot` and keeps the button's look.
- **A-6** — Colour is never the only channel: each status carries a glyph and a word; each glyph uses the
  empty-alternative form (`content: "✓" / ""`) so the word is what is announced. *Basis:* `repo:PRODUCT.md:109-111`;
  `globals.css:262-273`.
- **A-7** — Keyboard: every control is reachable and operable; the skip link stays the first stop and lands
  on `#content` (`layout.tsx:24-26`; measured, ES §6.5); every scroll container holding data is focusable
  (`tabIndex={0}`, `role="region"`, `aria-label`); Enter submits (K-5); sortable headers carry `aria-sort`; an open
  sheet holds focus inside it and nothing behind it is tabbable (axe's `aria-hidden-focus` needs review there, ES
  §6.2). *Basis:* axe `scrollable-region-focusable`; REFERENCE §6.7. *Today:* the shadcn `Table` container is that
  region while its table overflows (FX-17), named where the caller passes `label` (`/system`, the candidate
  scorecard). `DataTable` passes none, so its scrollers take focus when they overflow but are not named yet.
- **A-8** — Structure: one `h1` per page and state; no skipped heading level; a `<dl>` contains only
  `dt`/`dd` groups; every `th` has text (visually hidden where the column is actions); `aria-label` only on an element
  with a role; a dialog (the mobile sheet) has a title and a description. *Basis:* axe `definition-list`,
  `heading-order`, `page-has-heading-one`, `empty-table-header`, `aria-prohibited-attr`; EC §4.6 (no description).
  *Today:* card titles are `h2` and `MetricsPanel`'s heading sits outside its `dl` (FX-15); a column of per-row
  actions names itself through `DataTable`'s `hideHeader` (FX-18); the gate's chips carry their word and no
  `aria-label` (FX-9); the sheet has a description (FX-19).
- **A-9** — Announcements: failures `role="alert"`; saves and notes `role="status"`; loading `aria-busy`
  (exists). *Basis:* REFERENCE §6.7 (27 unannounced error banners).
- **A-10** — Targets are ≥24×24 CSS px, or meet one of WCAG 2.5.8's exceptions (spacing, inline). To check:
  the phone header brand, the findings checkbox, "Full register", "← Programme", the candidate page's ref link — the
  evidence did not evaluate the exceptions, so these are candidates, not confirmed failures. *Basis:* REFERENCE §6.7.
- **A-11** — One visually-hidden utility (`sr-only`). *Basis:* REFERENCE §6.3 item 9.
- **A-12** — Placeholders are `--muted`, held to the body ratio. *Basis:* `globals.css:590-594`.
- **A-13** — A chart is an image with a name that says what it shows, and every value a reader needs from it
  is also available as text beside it (as the metric grids do on backtest detail and `/portfolio`). At `0ec084f` the
  name gave only the date range (`EquityChart.tsx:96-97`), and the caption described the encoding, not the figures
  (:163-172). *Basis:* WCAG 1.1.1; REFERENCE §6.7. *Today:* unchanged; the adopting change redrew the chart (FX-20)
  but not its name or caption.

**axe findings at `0ec084f`** (axe-core 4.13.0, REFERENCE §6.7), and what the adopting change did about each. §13 (c)'s
baseline, which held the route-level ones, is empty, and the run now fails on any violation:

| axe rule | Impact | Where | Fix | Rule |
|---|---|---|---|---|
| `definition-list` | serious | backtest detail | move the `h3` out of `dl.assumptions` (`MetricsPanel.tsx:85-86`); done, FX-15 | A-8 |
| `scrollable-region-focusable` | serious | mobile `/system`, candidate | focusable, labelled scroll regions; done, FX-17 | A-7 |
| `link-in-text-block` | serious | `/programme`, dark | underline in-text links; done, FX-16 | A-5 |
| `heading-order` | moderate | `/`, backtest detail, `/programme` | section titles become `h2`; done, FX-15 | T-5, A-8 |
| `page-has-heading-one` | moderate | loading and API-unreachable states | keep the `h1` in every state; done on `/system` (FX-23), open elsewhere | T-5, E-9 |
| `empty-table-header` | minor | backtests, findings | a visually hidden header; done, FX-18 ("Open", "Details") | A-8 |
| (review) `aria-prohibited-attr` | — | `span.pill[aria-label]` | a role, or a visible word; done, FX-9 (the chip's word, no `aria-label`; axe silent on 2026-09-26) | A-8 |
| (review) `aria-hidden-focus` | — | behind the open mobile sheet | confirm nothing behind the sheet is tabbable | A-7 |

§13 (c) captures routes in their default state only, so the `page-has-heading-one` row (a loading and an error state)
and the sheet row are not guarded by its baseline; they stay on the manual list until states are captured (§13 (b),
"What (b) does not capture").

## 8. Responsive rules and edge cases

### 8.0 Responsive behaviour as shipped

What changes with width at `0ec084f`, from code and the 1440 / 390 captures. Observations, not rules.

| Width | What changes | Source |
|---|---|---|
| ≤ 640px | h1 drops to 19px; assumption and gate rows become one column | `globals.css:877-884` |
| ≥ 640px (`sm`) | the run form's field grid goes to 2 columns | `page.tsx:190`, :205 |
| < 768px | shell: 53px sticky header, menu button, 240px left sheet; `main` gutter 16px; shadcn inputs 13px | `AppShell.tsx:68`, :75, :92; `ui/input.tsx:11` |
| ≥ 768px (`md`) | shell: 208px sticky sidebar; `main` gutter 24px; shadcn inputs 12px | `AppShell.tsx:49`, :53, :92; `ui/input.tsx:11` |
| ≥ 1024px (`lg`) | the run form goes to 3 columns; `/system`'s first two cards sit side by side | `page.tsx:190`, :205; `system/page.tsx:158` |
| every width | tables and the pipeline scroll inside their own containers; the chart scales with its container, so its 10-unit axis text is about 3.6px at 390px (superseded, FX-20: the chart draws at its measured width, 240px tall at the least) | `DataTable.tsx:167`; `ui/table.tsx:9-11`; `programme/page.tsx:471`; `EquityChart.tsx:93-95`; EC §9.3 |
| 390px, measured | the candidate page widens to 784px (659px for C3; superseded, FX-21); on `/backtests` only Strategy and part of Window are visible at load | ES O-13, §4.3 |

- **E-1** — At 390×844 no page is wider than the device, **measured against the device width**
  (`scrollWidth > innerWidth` misses it under mobile emulation). *Basis:* REFERENCE §4.9. *Check:* §13 (b). *Today:* met
  on all 15 routes in both schemes (2026-09-26); the candidate page was the one exception (FX-21).
- **E-2** — Long unbroken strings — JSON, ids, hashes, error text — wrap (`overflow-wrap: anywhere`) or
  truncate with the full value reachable; they never widen the page or overprint a column. *Basis:* O-13, O-20.
  *Today:* an assumption row's value wraps anywhere (FX-21), which covers the candidate's parameters and the
  experiment's manifest and costs; the jobs table's error text still overprints its neighbour (O-20).
- **E-3** — At 390px a result's honesty fields — data source/synthetic, Sharpe ± SE, cost, effective start,
  sessions/year — are visible without horizontal scrolling. *Basis:* REFERENCE §4.9 (they start off-screen on
  `/backtests`); ES P-12. Since FX-4 the list carries effective start and session count in its Window cell rather than
  in new columns. *Today:* not met — the 2026-09-26 capture at 390px still shows only Strategy and Window at load, and
  Source, Sharpe ± SE and Cost are a sideways scroll away.
- **E-4** — Inputs keep one size per breakpoint and nothing below 13px, which the shipped 12px desktop inputs
  break (`ui/input.tsx:11`; Q-29); whether phones get 16px is Q-16.
- **E-5** — Chart labels never clip (at `0ec084f` a six-digit "$" was lost) and render ≥11 CSS px at every
  width. *Basis:* O-15; REFERENCE §3.3. *Today:* met (FX-20): the chart draws in CSS pixels at `--t-sm`, reserves its
  label margin from the labels it holds, and puts the effective-start label on whichever side of its line has room,
  on two lines when one does not fit.
- **E-6** — Number edge cases: `null`/`undefined` → `Absent`; `NaN`/±`Infinity` → "not measured". (A
  genuine zero renders as `0` — that clause is H-3, APPROVED; Q-21 asks about the autonomy ceiling's "nothing".)
- **E-7** — Loading, empty and absent are three different renderings: skeleton / an empty-state sentence /
  `Absent` words. At `0ec084f`, `/portfolio` showed "—" and "No open positions" while it was still loading. *Basis:*
  REFERENCE §6.5.
- **E-8** — A count in a title is the total; a capped list says it is capped ("200 of 779 shown"). *Basis:*
  O-16 ("Fills (500)" beside a metric of 779 at `0ec084f`; superseded, FX-3).
- **E-9** — A failed first load shows the error and keeps the page's `h1`; nothing waits forever on
  "Loading…". *Basis:* REFERENCE §6.5. *Today:* `/system` does (FX-23); the other pages are unchanged.
- **E-10** — Long tables paginate or window; page length is bounded (Q-27). *Basis:* ES §4.4 (8,708px).
- **E-11** — Every screenshot run covers both schemes (C-10); a manual theme switch is Q-19.
- **E-12** — Compare screenshots only against captures from the same OS and font stack; the capture VM renders
  DejaVu (REFERENCE §3.1).
- **E-13** — A figure is never shown as current when it is not. When a refresh fails, what it would have
  refreshed is marked stale with the time it was last read — on `/system` that includes the kill-switch chip and the
  three gates. When the subject changes (the `/portfolio` paper/live toggle), the previous subject's figures are cleared
  to the loading state rather than relabelled, and the label shown is the one the response carries
  (`Portfolio.mode`, `lib/api.ts:141`), not the one requested. *Basis:* REFERENCE §6.5 (both derived from code);
  `repo:CLAUDE.md:53-55` ("a control that defaults to 'go' when it cannot determine the answer is not a control").
  *Today:* the adopting change did `/portfolio` (FX-5) and `/system`, where the kill switch and the gates read "not
  read" beside their last reading (FX-23); `/programme` still keeps the last good figures unmarked.

## 9. The honesty rules as UI rules

Each honesty rule in `repo:CLAUDE.md` appears twice. **H-n** is the rule itself: APPROVED, except H-9 below. **H-nr**
is how this contract renders it: INFERRED until the owner approves it, except where an owner decision already has
(H-3r). One qualification: the manual browser journey already fails a run whose tearsheet lacks "Synthetic data", "Not
statistically significant" or "Annualised on" (`repo:tests/e2e/test_browser_journey.py:46-50`, :129-132, :150-153), so
that much of H-1r, H-6r and H-7r is enforced by an existing test, by hand, on backtest detail only. *Today* cites
REFERENCE §7 at `0ec084f`, and the `FX-n` of the adopting change.

- **H-1** — Never render a Sharpe without its standard error (`repo:CLAUDE.md:100-102`).
- **H-1r** — Estimate and SE in one element (e.g. "0.303 ± 0.226"); a non-significant estimate carries the
  *word* "not significant" (an `unknown` chip), not colour or `title`; significance is the stored
  `sharpe_is_significant`, never recomputed in the browser; sorting never drops the SE from view. *Implemented by:*
  PROPOSED `SharpeFigure`, for `MetricsPanel`, the backtests list and the experiment page. *Today:* met in `MetricsPanel`
  (and asserted by the browser journey); the backtests list says it in words since the adopting change (FX-4); the
  experiment page splits Sharpe, SE and significance into separate cells.
- **H-2** — Never quote a Sharpe from a search without deflating it (`repo:CLAUDE.md:103-108`).
- **H-2r** — Any Sharpe that is the best of several trials shows the deflated Sharpe and the trial count
  beside it; the UI displays the stored statistic and never recomputes it (the input must be per-observation).
  *Implemented by:* PROPOSED walk-forward view. *Today:* no surface shows it.
- **H-3** — An unmeasured metric is never zero, and a genuine zero stays a zero (`repo:CLAUDE.md:109-112`;
  tested per `:300`, `repo:tests/unit/test_programme_scorecard.py::TestNothingUnmeasuredReadsAsZero`).
- **H-3r** — An absence says why: "not measured" for a metric never computed, "no data" for an observation
  that never arrived. Never a bare dash, never 0. *Basis:* OD-4 (Q-10). *Implemented by:* `Absent`
  (`components/Absent.tsx`, FX-7), with its words in `lib/format.ts` `ABSENCE_WORDS`. *Check:*
  `repo:tests/unit/test_web_formatting.py` refuses a bare dash as a value. *Today:* the "0 bps" and "252
  sessions/year" defaults in `MetricsPanel` are gone (FX-2), and so is every bare "—" (FX-7): `/system` now uses the
  shared `fmtAge`, and the test's allow-list holds only `EquityChart`'s two axis divisors, which are never rendered. At
  `0ec084f` "—" rendered in 18 places (REFERENCE §7). The words are set as the `.no-data` label (11px capitals,
  `--muted`); OD-4 chose the words, not that treatment (REFERENCE Q-10).
- **H-3s** — Nor a substituted default: `?? 252` is the same lie as `?? 0` at a different number. Unknowns
  sort last and are a filter state of their own. *Implemented by:* `DataTable`'s sort (exists). *Check:*
  `repo:tests/unit/test_web_formatting.py` refuses a nullish or falsy fallback to a number literal.
- **H-4** — Never quote a performance figure without its cost assumption (`repo:CLAUDE.md:113-114`).
- **H-4r** — Cost stress (×) — and slippage where the figure depends on it — in the same card or row as any
  return, Sharpe or drawdown. *Implemented by:* `MetricsPanel`, the backtests list's "Cost" column, the candidate
  Configuration card. *Today:* missing on the candidate card. A run the programme queued records no slippage
  (`repo:src/programme/tick.py` omits `slippage_bps`, and the worker applies its own 5 bps), and `MetricsPanel` now says
  so — "missing — not recorded on this run; the engine applied its own default, not zero" — instead of "0 bps"
  (`repo:src/worker/backtest_job.py` reads `cost.get("slippage_bps", 5.0)`); recording it is a backend change.
  *Since FX-25:* it is made. `repo:src/db/repos/backtests.py` names the worker's defaults once (`DEFAULT_COST_MODEL`),
  `create_run` stores every run's cost model whole, the worker reads its costs through the same function, and the
  programme records the whole model on each run and experiment it queues; runs queued before still read "missing".
- **H-5** — Never quote a metric without `effective_start` (`repo:CLAUDE.md:115-117`).
- **H-5r** — Every result shows its effective start (or states that it equals the requested start); charts
  shade the warm-up. *Implemented by:* `EquityChart`'s warm-up band, `MetricsPanel`'s row, the backtests list. *Today:*
  on the backtests list since the adopting change (FX-4).
- **H-6** — Never quote an annualised figure without its session count (`repo:CLAUDE.md:118-123`).
- **H-6r** — "Annualised on N sessions/year" beside annualised figures; a missing count renders `Absent`,
  never 252. *Implemented by:* `MetricsPanel`, the experiment page, the backtests list. *Today:* the `?? 252` default is
  gone (FX-2) and the list shows the count (FX-4). The API still fills one in: `repo:src/api/schemas.py` defaults
  `periods_per_year` to 252 (and `n_fills` to 0), so the page's "not measured" branch cannot fire until the backend
  stops substituting. *Since FX-24:* it has stopped: every figure of `BacktestMetrics` is `null` when the run did not
  record it, and `lib/api.ts` types it so.
- **H-7** — Synthetic data is labelled everywhere it appears (`repo:CLAUDE.md:124-125`).
- **H-7r** — A `synthetic` chip in the page header of every run, candidate and experiment page, whatever the
  run's status, and above any chart of synthetic data. *Implemented by:* `StatusBadge status="unknown"` in
  `PageHeader`. *Today:* the banner sits below the chart; it is absent for queued and failed runs; experiments show it
  inside JSON only.
- **H-8** — The backtest must say when it was kinder than the venue (`repo:CLAUDE.md:126-131`).
- **H-8r** — PROPOSED field · Underfunded-buy count and worst shortfall on backtest detail, next to the
  fills; pluralised correctly; a non-empty list names the remedy the rule gives, "set `RiskLimits.cash_buffer_pct`"
  (`:130-131`), as a refusal says what would satisfy it (`repo:PRODUCT.md:49-50`). *Implemented by:* a PROPOSED field
  on `BacktestRun` and a `MetricsPanel` row; the shadow card (exists). *Today:* no field in `lib/api.ts:175-224`; the
  shadow card's note is pluralised since the adopting change (FX-14).
- **H-9** — Shadow equity "is not a result and the UI says so" (`repo:CLAUDE.md:470-472`) — stated in
  "Known limitations", not a rule, and untested.
- **H-9r** — The shadow book is labelled operation-not-performance wherever its equity appears.
  *Implemented by:* the candidate's shadow card. *Today:* present (`candidates/[id]/page.tsx:453-458`).
- **H-10** — A missing measurement is `unknown`, not `fail` (`repo:CLAUDE.md:300-301`;
  `repo:tests/unit/test_programme_scorecard.py`).
- **H-10r** — The scorecard renders the API's status and `observed_display` verbatim; the UI never
  re-derives a status. *Today:* met.
- **H-11** — "The frontend holds no model client" (`repo:CLAUDE.md:308`), and no model vendor's host or
  TypeSafe endpoint is spelled in `web/src` (`:307`). Tests: `repo:tests/unit/test_import_boundaries.py`
  `::test_nothing_that_can_move_money_names_a_model_vendor_host` and `::test_only_the_jev_modules_spell_the_typesafe_endpoint`;
  `repo:tests/unit/test_dependency_boundaries.py::test_no_npm_package_claims_to_be_typesafe` and
  `::test_no_lookalike_host_appears_in_anything_that_ships`; `repo:tests/unit/test_secret_isolation.py`
  `::TestTheLookalikeNameIsNeverUsed`. The frontend never calls a model; model output arrives only as stored rows
  through the API. **Gap:** the npm test refuses only TypeSafe-named packages, and an SDK's host sits in
  `node_modules`, so an `openai` or `@anthropic-ai/sdk` dependency in `web/package.json` would pass every test (§13 (a),
  "Not covered").

Rendering rules that answer the same honesty premise (`repo:CLAUDE.md:98`) but are not `CLAUDE.md` rules:

- **H-12** — Scale and caps: a percentage is formatted from the stored fraction by the one shared formatter,
  `fmtPct` in `lib/format.ts`, and never by appending "%" to a raw fraction; one format per quantity across pages
  (Q-22); a capped count says so (E-8). *Basis:* REFERENCE §7 (the report's drawdown was 100× too small at `0ec084f`;
  superseded, FX-1); `repo:PRODUCT.md:46`; the consequence recorded with the owner decisions (§0.2). *Check:*
  `repo:tests/unit/test_web_formatting.py` refuses a "%" or a `* 100` anywhere in `web/src` but `lib/format.ts`.
- **H-13** — A refusal lists the unmet criteria as unmet — by what is missing — not by the criterion's
  positive description; a rejected candidate never shows "hold". *Basis:* O-23; `repo:PRODUCT.md:49-50`.
- **H-14** — The multiple-testing counter stays beside each strategy and turns `unknown` at 20 runs. *Basis:*
  `page.tsx:141-150`; `repo:PRODUCT.md:29-34`.
- **H-15** — Model-authored content is marked (K-13) and is never styled as a measured fact. *Basis:*
  `globals.css:522-524`.
- **H-16** — The scorecard has no overall score: it carries no `score` or `grade`. *Basis:*
  `repo:tests/unit/test_programme_scorecard.py::TestTheRecommendation::test_there_is_no_overall_score` (the data layer).
- **H-16r** — The page never derives one either — no composite, rank or traffic light across dimensions, and
  no consensus across the specialist panel ("Nothing here is summarised into a consensus",
  `candidates/[id]/page.tsx:593-594`). Counts ("7 measured, 10 not measured, 5 failing") are not a score. *Basis:*
  `candidates/[id]/page.tsx:312`; "A veto is a row, not an opinion" (`repo:CLAUDE.md:294`).
- **H-17** — A missing *required* field reads "missing" plus the reason — what it is required for, such as
  gate 0→1 on a hypothesis card — never the absence word of an optional field, a bare dash, or 0. *Basis:* OD-4.
  *Implemented by:* `<Absent kind="missing" reason="…">`; the hypothesis page's list of required fields is compared
  with `REQUIRED_CARD_FIELDS` by `repo:tests/unit/test_web_formatting.py`. *Today:* the hypothesis card does this since
  the adopting change (FX-13); at `0ec084f` it rendered "—" for 10 required fields and 1 optional one (ES §4.10).
- **H-18** — What the UI says about the system's own capability matches `repo:CLAUDE.md`. At `0ec084f`,
  `/programme` said stages ≥4 cannot be reached because "shadow-mode operation is not built"
  (`programme/page.tsx:463-467`), while stage 3 is shadow mode and is built, and what is unbuilt is the stage 4–8 gates
  (`repo:CLAUDE.md:458-465`; `repo:src/programme/gates.py:49`); superseded, FX-6. *Basis:* REFERENCE §7; the honesty
  premise, `repo:CLAUDE.md:98`.

### 9.1 Safety and control-plane rendering

The safety rules in `repo:CLAUDE.md` bind the API and the worker, and the tests prove them there. The page is where an
operator reads them, so each has a rendering rule. The source rule is APPROVED; the rendering is INFERRED, except the
colour of a safety control's states, which OD-2 decided (C-12). REFERENCE §7.1 records how each rendered at `0ec084f`.

- **G-1** — The three live-order conditions are shown as three separate answers, never combined into one
  chip or summary, and a condition the API does not report is `unknown`, never inferred from the other two. An open
  gate is red (C-12). *Basis:* Safety rule 1, "deriving one from another is a weakening" (`repo:CLAUDE.md:44-52`);
  `system/page.tsx:14-16`, :240-249.
- **G-2** — A switch that fails closed is shown failing closed: if its state cannot be read, the page shows
  it as unknown (E-13), never as its last value and never as "enabled". Its stopped state is the strong amber
  "stopped" of C-12, never red. *Basis:* Safety rules 2 and 7 (`repo:CLAUDE.md:53-55`, :90-94); OD-2. *Today:* the kill
  switch on `/system` does both (FX-12, FX-23): an unread switch is the `unknown` chip "not read", with its last
  reading beside it. The programme switch on `/programme` does not yet (E-13).
- **G-3** — Stopping takes one action; starting takes a typed phrase that the page never pre-fills (ENABLE
  TRADING, ENABLE PROGRAMME, PROMOTE, RAISE AUTONOMY), through `TypedConfirm` (K-11). *Basis:* `repo:PRODUCT.md:88-92`;
  `system/page.tsx:6-9`; `programme/page.tsx:208-216`.
- **G-4** — Liveness is read from `stale`, never from a stored status, for workers and the runner alike, through
  `livenessStatus`. *Basis:* the guarantee "A dead worker looks dead" (`repo:CLAUDE.md:281`);
  `components/StatusBadge.tsx:58-68`.
- **G-5** — Where a setting has a requested and an effective value (the autonomy ceiling), both are shown
  and the effective one is never presented as the requested one or the reverse. *Basis:* the guarantee "The runner
  cannot promote past its ceiling … the stored value never masquerades as the effective one" (`repo:CLAUDE.md:295`);
  `programme/page.tsx:26-30`, :225-232.
- **G-6** — A control that asks the API to do something slow reports that it was queued, not done ("the API
  never runs one inline"), and never waits on the answer inline. *Basis:* `programme/page.tsx:245-251`;
  `repo:docs/08-jev-integration.md:624` for Jev (J-14).
- **G-7** — A promotion control never implies an override: it stays disabled until the gate has passed, and a
  409 is shown as the list of what is missing (H-13), never as a generic error. *Basis:* the guarantee "A human approval
  confirms a pass, it does not override a failure" (`repo:CLAUDE.md:290`); `candidates/[id]/page.tsx:165-176`, :240-249.

## 10. Jev UI rules (planned — phase E, `repo:docs/08-jev-integration.md:612-635`)

No page shows a Jev answer; phase E is "Not started" (`:647`). Phase B, being built on another branch, adds the first
Jev text under `web/`: a "TypeSafe (Jev) API key" title and note on `SecretField`, which J-13's tests already cover
(REFERENCE §1). These rules bind the first page that shows a Jev answer. Rule 5's Jev amendment is proposed, not in
force (`repo:CLAUDE.md:84-87`).

| ID | Rule | Source | Implemented by | Status |
|---|---|---|---|---|
| J-1 | Probabilities and `model_answered` are shown inline, never only in a tooltip | `docs/08:616` | `JevAnswer` | INFERRED |
| J-2 | `confidence` is labelled "concentration, not probability correct"; a Noul shows "n/a", because it has no confidence field. "n/a" is not one of OD-4's three words: those cover a value that could exist and does not, and this is a field the answer type does not have. The owner confirms the word at phase E (Q-23) | `:617-618`, `:49` | `JevAnswer` | INFERRED |
| J-3 | A "choice ≠ argmax" badge wherever the returned choice differs from the recomputed argmax; such an answer counts as an abstention, so the badge is `unknown` | `:619`, `:216-217` | `JevAnswer` + `StatusBadge` | INFERRED |
| J-4 | "Not measured" is a third filter state (not a yes/no), and an unknown never sorts as a low | `:620` | `DataTable` (sort exists) + filter | INFERRED |
| J-5 | Vendor accuracy is shown as "not published by TypeSafe" | `:621` | Jev status page | INFERRED |
| J-6 | Contaminated evidence shows a "contaminated" badge on candidates, backtests and the metrics panel; the badge explains a refusal, it does not replace one | `:634-635`, `:602-605` | `StatusBadge status="blocked"` | INFERRED |
| J-7 | A backfilled answer renders as not measured (OD-4's words), with a "backfilled" marker and the live fraction | `:590-591`, `:635`, `:515-518` | `Absent` + `JevAnswer` | INFERRED (the "backfilled" marker wording is this contract's) |
| J-8 | Every lane without a passing evaluation reads "not calibrated" | `:276-280` | Jev status page, `JevAnswer` | INFERRED |
| J-9 | A forward experiment reads "forward experiment, not validated by walk-forward" everywhere, with results as a paired difference with session count and SE | `:606-610` | deployment views | INFERRED |
| J-10 | The catalogue page opens outbound links over https only, republishes no abstract, and uses no `dangerouslySetInnerHTML` | `:622-623` | catalogue page | INFERRED |
| J-11 | The findings column reads "suggested reviewer … Jev (automated, cannot block)" | `:632-633` | findings `DataTable` | INFERRED |
| J-12 | No UI control turns model output (Jev included) into an order | `repo:CLAUDE.md:70-87` (rule 5; the amendment is not in force) | — | APPROVED (a restatement of rule 5, which import tests enforce on `src/`, not on the page) |
| J-12r | …nor into a deployment change or a promotion | extends rule 5; `repo:CLAUDE.md:290` (a promotion confirms a pass) | — | INFERRED |
| J-13 | `web/src` spells no TypeSafe endpoint and no vendor host; no npm manifest carries a TypeSafe-named package | `repo:CLAUDE.md:307-308`; the tests in H-11 | — | APPROVED (tests). "Installs no model SDK" in general is `:308`'s statement, not a test: see the H-11 gap |
| J-14 | The API never calls Jev: a probe or any Jev action enqueues work and the page says it was queued, never waits on an answer inline (G-6) | `:624` | Jev status page | INFERRED |
| J-15 | The Jev switches take a typed `ENABLE JEV` (`TypedConfirm`, G-3) and write an audit entry; switching off is one action | `:629-630` | Jev status page | INFERRED |
| J-16 | An evaluation is never shown without its uncertainty and its floor: balanced accuracy, per-class Wilson intervals, Brier score, the majority and the keyword baselines, and n — the Jev form of H-1 — with the flip rate where measured; a result on a public set is labelled "possibly in training" and an upper bound | `:594-601`, `:513`, `:905` | Jev status page | INFERRED |
| J-17 | Ops-triage chips on System > Jobs are display only: nothing on or beside a chip resumes a job or touches the kill switch | `:542` | jobs `DataTable` | INFERRED |
| J-18 | Findings-routing suggestions (owning role, likely duplicate, suggested severity) are shown as suggestions and never written into `severity` or `status`; a finding Jev raises shows its `jev:<set>` origin and never reads as a veto | `:541` | findings `DataTable` | INFERRED |
| J-19 | Beside the contaminated badge and the live fraction (J-6, J-7), candidates, backtests and the metrics panel show the signal model and the threshold | `:634-635` | `MetricsPanel`, candidate, backtests list | INFERRED |
| J-20 | When the direct-decision lane exists, the strategy's page states the recorded departure from the vendor's guidance (autonomy above 0.9, paper only) | `:285-289` | strategy page | INFERRED |
| J-21 | Navigation gains a "Jev" group (status, answers, the labelling queue, signals) and a catalogue page under Programme; every page shows answers through one shared `JevAnswer` | `:626-631` | `AppNav`; `JevAnswer` | INFERRED |

**A constraint on these files:** `repo:tests/unit/test_secret_isolation.py::TestTheLookalikeNameIsNeverUsed` reads
every file directly under `web/` — this one included — and fails on the lookalike reseller's name for the Jev key. The
rules above therefore never spell it; the Jev credential's name is `TYPESAFE_API_KEY`.

## 11. Tokens and these files

- **D-TOK-1** — This file points to `design-tokens.json` instead of carrying YAML tokens (the Google Labs
  form). Why: the runtime reads only CSS; the JSON is the interchange copy that §13 (a) holds equal to `globals.css` on
  every run; a YAML copy would be a third home for 40 values and 14 light overrides that nothing reads and nothing
  checks. The article's own division: "The token file owns exact machine values; DESIGN.md explains when and why to
  apply them."
- **D-TOK-2** — One token file, both themes: `$value` holds the unconditional `:root` (dark) value and the
  light value sits in `$extensions["com.github.qcasares.trader"].light` — the same shape as the CSS (one declaration,
  one override block). DTCG 2025.10's format module has no modes; its Resolver module expresses themes as separate
  files per context (a statement about the DTCG specifications, not verified from this environment, which cannot reach
  them). If a tool that needs the Resolver form is adopted, split into base + light files then.
- **D-TOK-3** — `globals.css` stays the source of truth (`0ec084f:DESIGN.md:6-7`); edit it first, then the
  JSON; the test names every token that disagrees (Q-2).
- **D-TOK-4** — Keep the requested name `design-tokens.json`; DTCG recommends `.tokens.json` for new files.
- **D-TOK-5** — The design system lives in `web/` beside the code it governs — `REFERENCE.md`, `DESIGN.md`,
  `design-tokens.json`, `examples/` and the routing rule in `CLAUDE.md` — and the root `DESIGN.md` is a pointer to this
  file. *Basis:* OD-1 (Q-1). Files placed directly in `web/` are read by
  `repo:tests/unit/test_secret_isolation.py::TestTheLookalikeNameIsNeverUsed` (§10). They are also where Tailwind looks
  for classes, since it scans every file under `web/` that git does not ignore: read as source, these documents put 29
  rules no component uses into the shipped stylesheet (`.bg-red-500`, and `.text-[Npx]` from a sentence forbidding it).
  `globals.css` therefore excludes them with `@source not`, and §13 (a) fails if a document here is not excluded.
- **D-TOK-6** — The token file mirrors what `globals.css` declares, and says what it does not hold: the
  values Tailwind 4.3.3 supplies by default and the UI depends on — breakpoints, `--spacing`, the `text-xs/sm/base`
  line-heights, the 150ms default transition (`compiled:57-86`, :2528-2557). Declaring them in `globals.css`, so that
  they become tokens the test can check, is Q-31.
- **D-EX-1** — Approved PNGs stay out of the web image: when the first one is copied into `examples/`,
  `web/.dockerignore` gains `examples/` (`web/Dockerfile` runs `COPY . .`). Vercel serves only what the build emits and
  `web/public`, so it never publishes them. *Basis:* the article's "Keep it small"; `repo:web/Dockerfile`.
- **D-ALLOW-1** — The allow-lists in `repo:tests/unit/test_design_tokens.py` started as the debt recorded at
  `0ec084f` — 35 arbitrary values (38 occurrences), one colour literal, two palette colours — each with the rule it
  breaks. They are exceptions awaiting the owner, not approved ones (Q-32). The counts only ever go down. The adopting
  change took out the four shadcn focus rings (`focus-visible:ring-[3px]`, A-4) and the colour literal
  (`button.danger`'s white, with the legacy button rules, K-15), leaving 31 arbitrary values in 34 places and the two
  palette colours; the test holds those exact counts. Every entry added later needs its own row here.
