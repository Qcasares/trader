# web/CLAUDE.md — design system routing

<!-- Claude Code loads this file once it reads a file under web/. The root CLAUDE.md's `web/` row points here too,
     because a task that starts from a root-level honesty rule can reach the UI before it opens a web/ file.
     Keep this short: the rules live in DESIGN.md, their history and reasons in design/, the evidence in REFERENCE.md.
     Whether the routing actually loads is checked by hand (design/checks.md (e), M-ROUTE). -->

## Interface work

Before creating or changing UI, always read `DESIGN.md` in this directory — the contract, every rule with its status —
then inspect the closest example in `examples/README.md`. No example is approved yet: take proportion and composition
from one, never exact values, and never anything in its "Known exceptions" column.

Only when the change touches a token, a rule or a pattern, also read `REFERENCE.md` (the evidence) and
`design/decision-log.md` (each rule's status, owner and basis). `design/notes.md` keeps each rule's first wording, its
reasons and what shipped; `design/checks.md` is how each check runs.

The honesty rules in the root `CLAUDE.md` are UI requirements here, and so are the safety rules the pages render (the
three live-order gates, the fail-closed switches). `DESIGN.md` §9–§10 map each one to the component that renders it.

Use the canonical components before adding one (`DESIGN.md` §5.1: the shadcn `Card`, `StatusBadge`, `Button` and
fields; `Absent` for a value that does not exist) and the semantic tokens (`src/app/globals.css`, mirrored in
`design-tokens.json`). No colour literal and no Tailwind arbitrary value outside the allow-list in
`tests/unit/test_design_tokens.py` (repository root).

If the sources conflict, or do not cover a consequential choice, ask the owner instead of guessing; `DESIGN.md` D-PREC
says which source wins. Rules marked APPROVED bind. Rules marked INFERRED are defaults awaiting the owner: follow them
and say so. Only the owner, Quentin Casares, approves a rule or an example (OD-1); never mark anything approved
yourself. A rule's status changes in `DESIGN.md` and the decision log together, or the token test fails. For a pattern
nothing here covers, offer about three variants and let the owner choose.

Before completion:

- run `pytest tests/unit/test_design_tokens.py tests/unit/test_web_components.py tests/unit/test_web_formatting.py -q`
  from the repository root, and `npm run typecheck && npm run build` in `web/`;
- capture the changed routes (desktop and mobile, both schemes) and run the axe scan (`design/checks.md` (b), (c)), and
  the keyboard walk if a control or a colour changed; if the change touches a loading, error, empty or open-sheet
  state, capture that state by hand — the scripts do not;
- compare the result with the rules and the closest example;
- report every intentional exception by rule ID, with its reason and evidence.
