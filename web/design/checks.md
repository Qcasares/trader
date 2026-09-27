# Checks — the validation loop for `web/`

<!-- Moved here from DESIGN.md §13 on 2026-09-26, verbatim except where it named its own file, so that the contract an
     agent reads before every UI change stays short. DESIGN.md §13 keeps the list of checks and what every UI change
     reports; this file is how each check runs, what it covers and what it does not. -->

Section numbers (§n) are `DESIGN.md`'s; `REFERENCE §n`, `EC`, `ES` and `Q-n` point into `REFERENCE.md`. Paths are
relative to `web/` unless prefixed `repo:`.

The article: "Do not ask the producing agent to be the only judge. Let it run the first comparison, then use
deterministic checks and a person with approval authority." Here the person with approval authority is the owner
(OD-1).

| Article check | Here | Failure signal | Runs in |
|---|---|---|---|
| Token use | (a) `repo:tests/unit/test_design_tokens.py` | a colour literal, palette colour or arbitrary value outside the allow-list; `design-tokens.json` ≠ `globals.css`; an APPROVED rule with no owner, date or basis, or a status that differs between a rule and its row in `design/decision-log.md` | CI (the unit suite) |
| Honesty formatting | `repo:tests/unit/test_web_formatting.py` and `repo:tests/unit/test_fill_count_contract.py` (both the adopting change's) | a "%" or `* 100` outside `lib/format.ts`; `?? 0`, `?? 252` or a bare "—" where `Absent` belongs; a hypothesis page whose required fields differ from the gate's; a fills count that differs from the stored rows (H-12, H-3r, H-3s, H-17, E-8) | CI (the unit suite) |
| Component reuse | review of imports against `DESIGN.md` §5.1; the (a) allow-lists can only shrink | a new sibling beside an owner; a legacy class in new code (K-16); a new allow-list entry with no decision-log row | PR review |
| Responsive behaviour | (b) `repo:tests/e2e/design_capture.py`, desktop 1440×900 + mobile 390×844, both schemes | overflow past the device width, text under 11px, not exactly one h1, console errors | by hand, stack running |
| Accessibility | (c) `repo:tests/e2e/design_axe.py` and the keyboard walk `repo:tests/e2e/design_focus.py`, plus screen-reader review | an axe rule not in the baseline; a focus stop without the accent outline, or with one under 3:1 (A-4) | by hand, stack running |
| Visual consistency | the (b) captures side by side with the closest example in `examples/README.md` | unexplained drift in density, alignment, type or composition | owner review |
| Product correctness | existing acceptance tests; `repo:tests/e2e/test_browser_journey.py`, which asserts the tearsheet's honesty banners and, since the adopting change, one stored drawdown rendered alike on two pages, a `/portfolio` account switch that never relabels the old figures, and a failed refresh marked stale | looks right, answers the wrong question | CI + owner (the journey is run by hand) |
| The deployed system | `repo:tests/e2e/live` (`workflow_dispatch` only, `.github/workflows/smoke.yml`); `repo:docs/08-jev-integration.md:905` plans the Jev pages' check there | a page that works locally and not behind the deployment's proxy, headers or build | by hand, on dispatch |
| The routing loads | (e) M-ROUTE | an agent edits `web/` without having read `CLAUDE.md` and `DESIGN.md` here first, or changes a token, a rule or a pattern without having read `REFERENCE.md` and `design/decision-log.md` | by hand, at rollout and after any change to the routing |

Every UI change reports three things:

- the rules it changed (IDs in `DESIGN.md`);
- the intentional exceptions (rule ID, reason, evidence);
- the output of (a), and of (b) and (c) for the changed routes.

### (a) Token lint and decision log — `repo:tests/unit/test_design_tokens.py`

Standard library and pytest only, because CI's unit job installs only `requirements.txt`. It reads `web/src`,
`globals.css`, `DESIGN.md`, the design documents beside it and the examples manifest at test time, so it judges
whatever the tree holds. Its convention is `test_import_boundaries.py`'s: a scanner that silently finds nothing passes
every test, so each scanner is first applied to synthetic sources that must trip it and sources that must not.

What it asserts:

1. **The scanners.** Arbitrary values are found inside `className`, `headerClassName`, `cn()`, `cva()` variants,
   template-literal branches and `!important`, and not in bracketed *variants*, prose, comparison operands or comments;
   palette colours and shadows are told from token utilities (`bg-accent` is shadcn's accent, `--panel-2` here, so not a
   palette colour); colour literals are found in TS and in CSS outside the two token blocks, and not in comments, HTML
   entities or `href="#…"`.
2. **The scan reads what it is meant to.** Named files are walked, `node_modules` and `.next` are not, and every source
   file that passes a class list yields class tokens — so a scanner that stopped reading `className` or `cva()` fails
   here rather than passing everything.
3. **The debt only shrinks.** Three allow-lists hold exact counts per file and token: `ARBITRARY_VALUES`,
   `PALETTE_COLOURS`, `COLOUR_LITERALS`. More than allowed fails as new debt; fewer fails as "shrink the allow-list
   entry", so the list records what is left, never what used to be. No shadow utility appears outside `components/ui/`.
4. **The token file is the stylesheet.** `design-tokens.json` is valid DTCG 2025.10 (types, names, aliases, colour,
   dimension, duration and bézier shapes); every `:root` custom property is mirrored exactly once with its value; a
   token carries a light value if and only if the light block declares one; every hex is the clipped OKLCH conversion,
   computed and never typed; the `@theme inline` mapping is mirrored. A property added to `globals.css` fails with the
   JSON entry to paste.
5. **Only the owner approves an example.** An `approved` row in the examples manifest has an owner, an ISO date and its
   files present.
6. **Only the owner approves a rule.** Every rule defined in `DESIGN.md` has one row in `design/decision-log.md` with
   the same status, and no other design document defines one; an APPROVED row names an owner, an ISO date and a basis
   that is an owner decision, `repo:CLAUDE.md` or a test.
7. **These documents are not stylesheet source.** Every design document in `web/` — `DESIGN.md`, `REFERENCE.md`,
   `CLAUDE.md`, `design-tokens.json`, `examples/`, `design/` — is excluded from Tailwind's scan by an `@source not` in
   `globals.css` (D-TOK-5); a document added without one fails, naming the line to add.

**Changing a token.** Edit `globals.css` first, then the JSON: `$value`, the light value and `hex` together. The hex is
computed:

```bash
python -c "from tests.unit.test_design_tokens import _oklch_hex; print(_oklch_hex(0.52, 0.11, 232))"
```

**Adding an allow-list entry** needs a decision-log row naming the rule it breaks and why, and the entry's reason
string cites that rule. **Removing debt** fails the test until the entry is shrunk or deleted (D-ALLOW-1).

**Not covered**, stated so nobody assumes it:

- raw lengths inside `globals.css` rules (`7px 9px`, `3px`, `10px`; REFERENCE §4.1);
- Tailwind scale values that bypass a token (`w-52`, `h-8`);
- **spacing steps off the scale** (S-1): `py-0.5`, `py-1.5`/`gap-1.5`/`space-y-1.5`, `px-2.5`, `py-5`, `pl-7`, `pr-9`,
  `py-10` are all in use (EC §3.1) and nothing counts them, so the article's "hard-coded … spacing" signal has no
  check. The same exact-count allow-list the arbitrary values use would freeze today's uses and refuse new ones;
- classes assembled outside `className`/`headerClassName`/`cn()`/`cva()`, which the scanner would miss;
- **a model SDK in `web/package.json`** (H-11). `repo:CLAUDE.md:308` says the frontend holds no model client, but
  `test_no_npm_package_claims_to_be_typesafe` refuses only TypeSafe-named packages, and an SDK's vendor host lives in
  `node_modules`, where the host scan does not look. The fix belongs in `repo:tests/unit/test_dependency_boundaries.py`:
  apply `MODEL_SDKS`, with the npm spellings (`openai`, `@anthropic-ai/sdk`, …), to every npm manifest and lockfile.

It runs under the unit suite in CI (`pytest tests/unit`), and first as its own named step, "Design system", with
`repo:tests/unit/test_web_components.py`, `repo:tests/unit/test_web_formatting.py` and
`repo:tests/unit/test_fill_count_contract.py` (`.github/workflows/ci.yml`), so its failure says what broke, as the
parity and boundary steps do.

### (b) Captures and layout checks — `repo:tests/e2e/design_capture.py`

The 15 routes, each at desktop 1440×900 (`is_mobile=False`) and mobile 390×844 (`is_mobile=True`, `has_touch=True`), in
light and dark (`page.emulate_media`; the app switches only on `prefers-color-scheme`), full page at device scale 1 —
one image pixel is one CSS pixel. It waits for `networkidle`, then for no `[aria-busy=true]` skeleton, then for every
finite animation to end (`settle`: a list's entrance, M-12), then 700ms, and hides Next's dev overlay. It shoots with
`animations="disabled"`: the live pulse (M-10r) never ends, and left running it froze at a different phase in each
capture, so two captures of one state differed inside the worker's chip; cancelled for the shot, the halo draws still.
Captures are named `<slug>__<desktop|mobile>__<light|dark>.png`, the names the examples manifest uses. Not part of a pytest suite and not in CI, for the reason the browser journey is not: it needs a running
Postgres, API, worker and Next.js.

```bash
# the stack running and seeded; Playwright for Python in the venv, as the browser journey assumes
.venv/bin/pip install playwright==1.56.0          # the version the evidence used
E2E_BASE_URL=http://localhost:3000 E2E_IDS=.screenshots/design/ids.json \
    .venv/bin/python tests/e2e/design_capture.py
```

| Variable | Meaning |
|---|---|
| `E2E_BASE_URL` | the web app; default `http://localhost:3000` |
| `E2E_PASSWORD` | the operator password; the default is the browser journey's, imported from `test_browser_journey.py` rather than typed a second time (`repo:CLAUDE.md` safety rule 6) |
| `E2E_CHROMIUM` | the browser; default `/opt/pw-browsers/chromium`, because this environment blocks `playwright install` |
| `E2E_SHOTS` | output directory; default `.screenshots/design`, already in `.gitignore` |
| `E2E_IDS` | JSON of pinned detail ids: `run_ok`, `hyp_full`, `cand_stage1`, `exp_fail` |
| `E2E_ONLY` | the slugs to run, comma-separated |

| Check | Assertion | Rule |
|---|---|---|
| `overflow` | no element whose box passes the **device** width (390 or 1440) unless an ancestor scroller contains it | E-1, E-2 |
| `small-text` | every visible text node renders ≥11 CSS px; for SVG, the font size × the `getScreenCTM()` scale | T-1, E-5 |
| `one-h1` | `main h1` count = 1 | T-5 |
| `console` | no console error, page error or ≥400 response, except `/api/v1/system/drain`, which is documented | E-9 |

The run exits 1 on any failure not listed in `repo:tests/e2e/design_baseline.json`, and prints every listed failure
that no longer occurs, so the baseline only shrinks. It held four entries at `0ec084f` — the candidate page's mobile
overflow (both schemes; E-1, E-2) and backtest detail's mobile chart text (both schemes; T-1, E-5) — and is empty
since the adopting change fixed both (FX-21, FX-20; its run of 2026-09-26 passed all 60 captures).

**What (b) does not capture:**

- **States.** Only the 15 routes in their default state. The loading, API-unreachable, failed, queued, open-sheet,
  stage-0-blocked and rejected states the evidence captured (ES §1) are not reproduced, so the article's "missing
  states" signal has no check, and four of the five example candidates cannot be re-captured in the repository
  (`examples/README.md`, "Regenerating the candidates").
- **Pseudo-element text.** `small-text` walks text nodes, so a glyph drawn with `::before` — each chip's — is not
  measured (T-1). The 10px `.pill::before` glyph (`globals.css:690`) it could not see went with FX-9.
- **Stale data.** (b) forces neither a failed refresh nor a paper→live switch. The browser journey does, for
  `/portfolio` (its steps 10 and 11) and `/system` (step 12); for `/programme`, E-13 and G-2 are held by
  `repo:tests/unit/test_web_taste.py` reading the code, and were measured by hand on 2026-09-27 with the API failing
  after a first read (the switch "not read", the stale banner, the runner still, and all of it back on recovery).
- **A process that has just stopped.** Nothing stops the worker or the runner during a run, so the minute in which a
  clean shutdown's row is fresh and says `'stopped'` (G-4) is checked by `repo:tests/unit/test_web_taste.py` and
  `repo:tests/unit/test_worker_liveness.py`, and was captured by hand on 2026-09-27.
- **The seed.** Captures are comparable with an example, and the baselines hold, only on the seeded dataset with pinned
  ids (`evidence_screens.md` §0.4). The seed is not in the repository; without `E2E_IDS`, detail ids come from the
  first link on each list page, which is good enough for looking but not for the baselines. Porting the seed and the
  state captures are the two missing pieces.

**What a person does with the output:** open the captures of the changed routes beside the closest example (same scheme
and viewport); look for drift in density, alignment, type and composition; compare text width and wrapping only between
captures from the same OS (E-12).

### (c) Accessibility — `repo:tests/e2e/design_axe.py`, keyboard, screen reader

`axe-core` 4.13.0, the version the evidence used, comes from its own npm package, `repo:tests/e2e/design/`, for the
reason `tests/e2e/live` is its own package: Vercel builds `web/`, and nothing it builds should install test tooling. The
script imports its routes, id resolution, sign-in and readiness wait from `design_capture.py`, so the two can never
scan different pages, and runs `axe.run({exclude: [['nextjs-portal']]}, {resultTypes: ['violations', 'incomplete']})`
after `settle` once more: a row a poll has just mounted is still fading in, and axe measures it part way (1.5–4.3:1 on
`/system` 150ms after its rows mounted, none from 300ms).

```bash
npm ci --prefix tests/e2e/design
E2E_BASE_URL=http://localhost:3000 .venv/bin/python tests/e2e/design_axe.py
```

For each capture, the violated rule ids must be a subset of that capture's entry in
`repo:tests/e2e/design_axe_baseline.json`; any other rule makes the run exit 1, and every baselined rule that no longer
fires is printed. The baseline holds rule ids, not node targets: targets follow markup and data, and a rule is what
`DESIGN.md` §7 decides. `incomplete` results go to `axe_report.json` for review and are not asserted. The baseline was
generated from
the evidence's 60 route captures at `0ec084f`: 24 captures, with `definition-list` (backtest detail ×4),
`heading-order` (`/`, backtest detail, `/programme`, ×4 each), `empty-table-header` (`/backtests`, findings, ×4 each),
`link-in-text-block` (`/programme`, dark ×2) and `scrollable-region-focusable` (`/system` and the candidate page, mobile
×2 each). It is empty: the adopting change fixed every one (the axe table in `design/notes.md` §7), and its run of
2026-09-26 found no violation on any capture. An entry added later names the rule it breaks and has a row in the
decision log.

What axe does not cover, which stays with a person:

- **Keyboard walk.** Every tab stop, including each internal stop of a date input, shows the accent outline (A-4) at
  ≥3:1 against its backdrop, at once (A-4r); tab order never moves backwards. At `0ec084f` the shadcn ring measured
  2.16–2.94:1 (1.50–2.03:1 on destructive buttons) and the date input's calendar stop showed nothing.
  `repo:tests/e2e/design_focus.py` now walks six pages in both schemes — and the candidate page when `E2E_IDS` pins
  one, for the back link, the gate and the scorecard's scroll region none of the six has — and fails a stop without a
  solid 2px accent outline or with one under 3:1: on 2026-09-26, 402 stops on the seven, none failing, all 16
  date-input stops outlined, the lowest 4.55:1 (light) and 6.29:1 (dark). Pages it does not walk, and the open sheet,
  stay with a person.
- **Contrast axe could not judge.** Re-run the evidence's contrast census (11,420 text nodes, 0 enabled below 4.5:1 at
  `0ec084f`) for any change to colour, backdrop or opacity. Hover and active states need the computed pairs in
  REFERENCE §2.6, because a static census cannot see them.
- **Screen reader** (not tested so far; ES §6.5). With VoiceOver or NVDA, read the five examples and confirm: each
  status is announced as its word, not its glyph; the error, save and note announcements (A-9); scroll regions are
  named (A-7); the heading outline (T-5); each chart's name and the text that carries its values (A-13); an `Absent`
  value announces its word and that it is not a zero.
- **The open sheet** (never walked, ES §6.5): focus stays inside it, nothing behind it is tabbable (axe's
  `aria-hidden-focus` needs review, ES §6.2), and its close button shows the accent outline (A-4, A-7).
- **Mobile keyboard** (not tested, ES §6.5): an external keyboard on the 390px layout reaches the menu button, every
  sheet link and every scroll region.
- **States axe never sees.** The baseline covers route captures only, so `page-has-heading-one` on the loading and
  API-unreachable states (ES §6.1) stays a manual item until (b) captures states. So does `/programme` with no
  candidate on its board, the state in which the board's scroller had nothing inside to focus and axe reported
  `scrollable-region-focusable` (found in review, 2026-09-27; A-7). Every sideways scroller is now held by
  `repo:tests/unit/test_web_taste.py`, and the empty board was scanned by hand the same day, clean.

### (d) How the owner approves and promotes an example

Only the owner approves (OD-1). An agent never changes a Status to `approved`, never copies a file into `examples/`,
and never moves a rule in `DESIGN.md` from INFERRED to APPROVED.

1. **Candidate.** A change arrives as a pull request carrying the (b) captures of every route it touches (desktop and
   mobile, both schemes), the (c) output, the (a) result, the changed rule IDs and every intentional exception. For a
   new pattern, the article's advice applies: ask for about three variants before polishing; the selection is a human
   design decision.
2. **Review.** The owner compares the captures with the closest example and the rules. For each "Known exception" the
   candidate fixes, the owner confirms the fix; each new exception is either accepted, and recorded, or refused.
3. **Promote.** On approval: copy the chosen PNGs from the capture directory into `examples/` under their capture
   names; set the manifest row's `Status` to `approved`, `Owner` to the approver, `Approved on` to the date
   (`YYYY-MM-DD`), `Source (commit)` to the commit the capture was taken from, and `Files` to the copied names in
   backticks; trim "Known exceptions" to what is still true. If the approval settles a rule, set its row in
   `design/decision-log.md` to APPROVED with the date, the owner and the basis, and its status where `DESIGN.md`
   defines it. Update the source's label in REFERENCE §1. Test 5 of (a) refuses an `approved` row with no owner, no date or missing files; test 6 refuses a rule
   whose two statuses differ.
4. **Demote.** When the route changes, an approved example is re-captured and re-approved, or its row becomes
   `historical` (the files stay, labelled). It is never overwritten silently. A candidate that is looked at and refused
   becomes `rejected`, with the reason in "Known exceptions".
5. **Keep it small.** Add an example only to settle a recurring ambiguity (the article: "A library of approved patterns
   compounds consistency; a library of every output compounds errors"). Screenshots live in git, so each approval weighs
   about as much as its PNGs (Q-20; D-EX-1).

### (e) Rolling it out

**M-ROUTE — does the routing load? A manual check, because it cannot be automated here.** The article's rollout step:
"wire the routing rule, keep CLAUDE.md short and test Claude actually loads the sources". Claude Code loads
`web/CLAUDE.md` only once it reads a file under `web/`, and a task that starts from the repository root with no path
reaches the UI only if the root `CLAUDE.md` sends it here. Checking that would mean driving Claude Code itself and
inspecting what it read before its first edit, which no suite in this repository can do, so a person runs it:

1. From the repository root, start a fresh Claude Code session with a UI task phrased without a path — for example,
   "make the experiment page show the Sharpe with its standard error in one place".
2. Before it edits anything, ask which files it read and why. Record whether `web/CLAUDE.md` and `web/DESIGN.md` were
   read before the first edit, and whether it named the rules it was following. This task changes no token, rule or
   pattern, so it has no need of `web/REFERENCE.md` or `web/design/decision-log.md`; record whether it read them anyway.
3. Repeat in a fresh session with a task that names a file under `web/`
   ("in `web/src/app/programme/experiments/[ref]/page.tsx`, …"), and in a third with a task that changes a token or a
   rule ("give the `unknown` chip's edge its own token", say), which should also read `web/REFERENCE.md` and
   `web/design/decision-log.md` before its first edit.
4. **Pass:** every session read `web/CLAUDE.md` and `web/DESIGN.md` before its first edit, and the third read the
   evidence and the log as well. A path-less miss means the root pointer is not carrying it: strengthen the root
   `CLAUDE.md` row, rather than lengthening `web/CLAUDE.md`. (Until 2026-09-26 every session was asked to read
   `REFERENCE.md` too; at about 100KB beside a 129KB contract, that was the cost this split removed.)
5. Record the date, the three prompts, the files read and the result in the pull request that changes the routing, and
   re-run it whenever the root `CLAUDE.md` or `web/CLAUDE.md` changes.

**The pilot.** Run three task types through the loop: a new component (`Metric` or `SharpeFigure`, `DESIGN.md` §5.1); a change to
an existing screen (the experiment page's split Sharpe cells, H-1r); a responsive repair (the backtests list's honesty
fields at 390px, E-3 — the candidate page's overflow, the first choice, was fixed by the adopting change, FX-21). For each, count the review rounds, new allow-list entries, duplicate components, axe or keyboard regressions,
and first-pass acceptances. OD-1 has assigned the owner of tokens, components, examples and the decision log: the owner.
