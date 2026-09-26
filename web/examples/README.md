# examples/ — manifest

**Status: adopted 2026-09-26 (owner decision OD-1, `../DESIGN.md` §0.2). No example is approved.** Each row below is a
*candidate*: a shipped screen, captured at commit `0ec084f`, that the owner has not approved. The article is explicit
that a pattern is promoted "after approval, not after generation", so this directory holds **no images yet**. The rows
name the survey's captures (`design/shots/`, kept outside the repository — `../REFERENCE.md` Q-20; 1 image px = 1 CSS
px); `tests/e2e/design_capture.py` regenerates the route captures under the same names. Only the owner, Quentin
Casares, promotes a row: by copying the chosen files here and editing the row (`../DESIGN.md` §13 (d)).
`tests/unit/test_design_tokens.py::test_the_examples_manifest_only_approves_what_an_owner_approved` refuses an
`approved` row that has no owner, no date or no file.

**How to use a candidate before it is approved.** Take proportion, density and composition from it. **Never take exact
values from it**; those come from `../design-tokens.json`. **Never copy anything in its "Known exceptions" column**;
each entry names the `../DESIGN.md` rule it breaks.

**The captures predate the adopting change.** That change fixed some of the exceptions below; each such exception is
marked *superseded (FX-n)*, from `../REFERENCE.md` §0. A candidate is re-captured before the owner looks at it, and the
re-capture, not the mark, is what shows whether the fix landed. The change's own run re-captured the 15 routes in
their default state on 2026-09-26 (`../REFERENCE.md` §0 says what each confirmed); the state files E2 to E5 depend on
were not re-captured, so a mark on an exception seen only in a state is confirmed by the route capture and the code.

**Chosen by coverage, not volume** (the article: "one dense dashboard, one marketing page, one form-heavy flow and one
mobile state"):

- This product has no marketing surface. Its only unauthenticated page is `/login`.
- In place of a marketing page, E3 covers a detail page with honesty banners, as this repository requires.
- E5 is the "at least one difficult state" the article's rollout asks for: a refused promotion.

| ID | Artifact | Route | Files (in `design/shots/` until approved) | Source (commit) | Status | Owner | Approved on | Reusable elements | Known exceptions |
|---|---|---|---|---|---|---|---|---|---|
| E1 | Dense dashboard: AI programme overview | `/programme` | `programme__desktop__dark.png`, `programme__desktop__light.png`, `programme__mobile__dark.png`, `programme__mobile__light.png` | `0ec084f`, captured 2026-09-26, seeded synthetic data | shipped — awaiting owner approval | — | — | page header + outline action; status card with a metric grid of chips and figures; caveat banners carrying their remedy link; reason input + stop/run action row; board with dimmed unreachable stages | text-colour card edges (superseded, FX-8); box in a box; links not underlined (superseded, FX-16); filled destructive stop; `window.prompt`; stage heads skip h2 (superseded, FX-15) (see E1 below) |
| E2 | Form-heavy flow: strategy run form | `/` | `dashboard__desktop__light.png`, `dashboard__desktop__dark.png`, `dashboard__mobile__light.png`, `dashboard__mobile__dark.png`; states `dashboard--loading__*`, `dashboard--api-unreachable__*` | `0ec084f`, 2026-09-26 | shipped — awaiting owner approval | — | — | card per strategy with version and multiple-testing chips; schema-generated 1/2/3-column field grid with hints; honesty banners directly above the one filled action | no `<form>`, so Enter does nothing; h1 → h3 (superseded, FX-15); legacy hairline on the primary (superseded, FX-10); date-picker stop shows no focus (superseded, FX-11); loading and error states lose the h1 |
| E3 | Detail page with metrics and honesty banners: backtest run | `/backtests/[id]` | `backtests-id__desktop__dark.png`, `backtests-id__desktop__light.png` (1440×8708), `backtests-id__mobile__dark.png`, `backtests-id__mobile__light.png`; states `backtests-id--failed__*`, `backtests-id--queued__*`; top crop `design/evidence/shots_code/crop-backtest-detail-top.png` (fixture data) | `0ec084f`, 2026-09-26 | shipped — awaiting owner approval | — | — | header with run id, universe and a bottom-right status chip; equity + drawdown chart with warm-up shading; caveats above the figures; "x ± se" with a not-significant chip; "assumptions this result depends on" rows | synthetic banner below the chart and absent when queued or failed; "0 bps"/"252" defaults (superseded, FX-2); "$" clipped (superseded, FX-20); `h3` inside `dl` (superseded, FX-15); painted empty track; "Fills (500)" (superseded, FX-3) |
| E4 | Mobile state: navigation sheet open | `/` at 390×844 | `dashboard--nav-open__mobile__dark.png`, `dashboard--nav-open__mobile__light.png`; closed state `dashboard__mobile__*`; crop `probe__dashboard__nav-sheet-header__mobile__dark.png` | `0ec084f`, 2026-09-26 | shipped — awaiting owner approval | — | — | 53px sticky header with an icon menu button; 240px left sheet holding the same grouped nav, active rule and Sign out as the desktop sidebar | brand wraps to two lines at 19px (superseded, FX-10); legacy chrome on the menu and close buttons (superseded, FX-10); animations compile to nothing (superseded, FX-22); a 21.7px-tall brand target |
| E5 | Difficult state: a refused promotion | `/programme/candidates/[id]` (candidate C3, stage 0) | `programme-candidates-id--stage0-blocked__desktop__dark.png`, `…__desktop__light.png`, `…__mobile__dark.png`, `…__mobile__light.png` (659px wide); related `programme-candidates-id__*` (784px mobile), `programme-candidates-id--rejected__*` | `0ec084f`, 2026-09-26 | shipped — awaiting owner approval | — | — | gate checklist with "▲ N UNMET", an info banner stating the route forward, met/unmet rows with detail and evidence; scorecard where unmeasured reads NOT MEASURED with `? unknown`; decision card: reason, Hold, Reject, typed PROMOTE, disabled promote with its reason | two chip systems and two card systems, 0px join (superseded, FX-8, FX-9); page overflows the phone (superseded, FX-21); recommendation lists unmet criteria as met; disabled promote keeps its fill; no nav item lit |

## Per-example detail

Each reusable element cites the rendering. Each exception cites the `../DESIGN.md` rule it breaks, so fixing it is a
change to that rule's component, not to the example.

### E1 — AI programme overview (`/programme`)

- **Reusable:**
  - h1 + one intro paragraph + outline "Configuration" link, bottom-aligned right.
  - "Autonomy" card: `✓ enabled` chip in the title, then a six-cell metric grid that mixes chips (`✓ alive (7s)`,
    `✕ 2 blocking`) with figures.
  - Explanatory prose capped at a measure; two warn banners, each ending in the link that resolves it.
  - Reason input, then the stop action and the run action.
  - "Pipeline" card: nine 208px stage columns, stages ≥4 in `--faint`, `? operator` on stages ≥5, and cards carrying
    `? synthetic` + "cannot reach shadow mode".
- **Known exceptions:**
  - Card edges in the text colour — C-8a (superseded, FX-8).
  - The metric grid and the pipeline cards are bordered boxes inside a card — S-10, Q-18.
  - "Review them." and "Set it" are not underlined (axe `link-in-text-block`, dark) — A-5 (superseded, FX-16).
  - Stage heads use 0.33px tracking — T-6.
  - h1 → h3 stage heads — T-5 (superseded, FX-15: the Pipeline card's title is an `h2`).
  - "Disable the programme" is the only filled control, and it is destructive — K-4, Q-8.
  - Raising autonomy uses `window.prompt` — K-11, G-3.
  - `text-[11px]` — T-1.
  - At 1440px, stage heads 5–8 are cut at the board's edge until scrolled.
  - The board's explanation says stages ≥4 are unreachable because "shadow-mode operation is not built"; stage 3 is
    shadow mode and is built (`programme/page.tsx:463-467`) — H-18 (superseded, FX-6).
  - A failed refresh leaves the last good figures on screen, unmarked (`programme/page.tsx:155-161`, :288) — E-13.

### E2 — Strategy run form (`/`)

- **Reusable:**
  - One card per strategy: name, `• v1.0`, and the multiple-testing chip, which turns `?` amber at 20 runs (H-14).
  - Description, universe line (mono, `--faint`), source line.
  - "Parameters" and "Run settings" as schema-generated fields in `grid-cols-1 sm:2 lg:3`, each with a 12px hint.
  - Warn banner (synthetic) and info banner (3× cost stress) directly above the single filled "Run backtest".
  - The other strategies collapsed behind outline "Configure & run".
- **Known exceptions:**
  - Inputs are not in a `<form>`, so Enter submits nothing — K-5.
  - Legacy `--border-strong` hairline on the filled primary — K-15 (superseded, FX-10).
  - h1 → h3 "Parameters" (axe `heading-order`) — T-5 (superseded, FX-15).
  - Label-to-control gap is 6px — S-4, Q-13.
  - Inputs are 12px on desktop and 13px on mobile — Q-16, Q-29.
  - The date input's calendar stop shows no focus — A-4 (superseded, FX-11: the keyboard walk of 2026-09-26 found all
    eight date-input stops on `/` outlined, in both schemes).
  - The loading and API-unreachable states render no h1 — E-9.
  - Card edges in the text colour — C-8a (superseded, FX-8).

### E3 — Backtest run (`/backtests/[id]`)

- **Reusable:**
  - Header: strategy name, run id · universe (mono), and a status chip bottom-right.
  - "Equity" card: equity line (accent) over drawdown (blocked 26 %), warm-up band + dashed `--unknown` line + "full
    universe from {date}", caption.
  - "Performance" card: warn "Synthetic data", warn "Not statistically significant", info "Universe incomplete" — all
    above a twelve-cell metric grid whose Sharpe reads "x ± se" (0.249 ± 0.190 in the seeded capture, ES §4.4) over a
    not-significant chip.
  - "Assumptions this result depends on": eight rows — data source, requested window, effective start, slippage, cost
    stress, annualised on, decision lag, engine (`MetricsPanel.tsx:87-116`).
  - "Failed." bad banner; "Queued — waiting for a worker." info banner.
  - Ghost back link at the foot.
- **Known exceptions:**
  - The synthetic banner is below the chart, and absent for queued or failed runs — H-7r.
  - "0 bps" and "252 sessions/year" defaults — H-3r, H-6r (superseded, FX-2).
  - Six-digit y-axis labels lose their "$" — E-5 (superseded, FX-20).
  - Axis text is 3.6px on a phone — T-1 (superseded, FX-20: 12px at every width).
  - `h3` inside `dl` (axe `definition-list`) — A-8 (superseded, FX-15).
  - Painted empty metric track — L-5.
  - "Fills (500)" beside FILLS 779 — E-8 (superseded, FX-3).
  - 8,708px page — E-10.
  - No underfunded-buys figure — H-8r.
  - Legacy `.badge` chip — K-16 (superseded, FX-9).

### E4 — Navigation sheet open (`/`, 390×844)

- **Reusable:**
  - Sticky 53px header: ghost icon button "Open navigation" + brand.
  - 240px sheet from the left over a dimmed page, holding the desktop sidebar's grouped nav (Research, Operations,
    Programme), the active item's `--panel-2` fill with a 2px accent rule, and Sign out at the foot.
  - The sheet closes on navigation (`AppShell.tsx:82`).
- **Known exceptions:**
  - The sheet title is an h2 caught by the legacy rule, so the brand renders at 19px/600 on two lines — K-15, Q-26
    (superseded, FX-10).
  - The menu and close buttons wear the legacy `button` border and fill — K-15 (superseded, FX-10).
  - The sheet has no description (`aria-describedby` null) — A-8 (superseded, FX-19).
  - Sheet edge in the text colour — C-8 (superseded: the base layer now defaults a bare `border` to the hairline).
  - Open and close animations compile to nothing — M-4 (superseded, FX-22: removed; the sheet appears at once, as it
    always did).
  - The brand link is 21.7px tall — A-10.
  - axe needs-review: `aria-hidden-focus` behind the sheet — A-7.

### E5 — Refused promotion (`/programme/candidates/[id]`, C3 at stage 0)

- **Reusable:**
  - Synthetic warn banner under the header.
  - The gate: "Gate: concept → rapid research" with `▲ 2 UNMET` (now `StatusBadge`'s amber `caution` chip `▲ 2 unmet`, each unmet row a `blocked` chip: FX-9, C-5; Q-33), then an info banner saying a promotion confirms a
    passed gate and cannot override a failed one, then met/unmet rows, each with a one-line detail and a mono evidence
    link.
  - Scorecard: "3 measured, 14 not measured, 1 failing"; the card's own statement that there is "deliberately no
    overall score" (H-16r); unmeasured cells read NOT MEASURED with a `? unknown` status and a sentence saying why.
  - "Specialist assessments": "Nothing here is summarised into a consensus" (H-16r).
  - Experiments, findings and assessments cards, each with its empty sentence.
  - Decision card: rationale input; outline Hold; destructive Reject; typed `PROMOTE`; disabled "Promote to stage 1"
    with "Available once the gate passes."
- **Known exceptions:**
  - Legacy `.pill` and `StatusBadge` on one page — K-16 (superseded, FX-9).
  - Legacy `section.card` joined to a shadcn `Card` with a 0px gap — K-16, S-2 (superseded, FX-8: 12px on C1's page,
    re-measured 2026-09-26).
  - The page is 659px wide on a 390px phone (784px for C1), from an unbroken JSON value — E-1, E-2 (superseded, FX-21:
    390px for C1 on 2026-09-26).
  - Raw scorecard `<table>` with weight-700 headers — K-6.
  - The recommendation lists unmet criteria by their *met* descriptions, and a rejected candidate still says "hold" —
    H-13.
  - The disabled promote keeps its accent fill — Q-7.
  - Reject is filled beside Promote — Q-8.
  - No nav item is lit — K-10.
  - `aria-label` on a role-less `span` — A-8 (superseded, FX-9).
  - Table scrollers cannot be focused on mobile — A-7 (superseded, FX-17).

## Regenerating the candidates

The files named above came from the survey's capture script (`design/scripts/capture.py`, `routes` and `states`)
against a stack seeded by its `02_seed_research.py` … `06_seed_queued.py`, as `evidence_screens.md` §10 lists; none of
these is in the repository (Q-20). `tests/e2e/design_capture.py` (`../DESIGN.md` §13 (b)) is the in-repository
version, and captures the 15 routes in their default state only. Four of the five candidates depend on state files it
cannot produce — E2 (`--loading`, `--api-unreachable`), E3 (`--failed`, `--queued`), E4 (`--nav-open`) and E5
(`--stage0-blocked`, `--rejected`) — so until those states are ported, a re-capture for approval has to be made by
hand, in the state the row names.
