# Design

The design system for the web UI lives in `web/`, beside the code it governs (owner decision OD-1, 2026-09-26):

- [`web/DESIGN.md`](web/DESIGN.md) — the implementation contract, short enough to read before every UI change:
  semantic tokens, component rules, accessibility, and the honesty and safety rules as UI rules, each with its status.
- [`web/design/`](web/design/) — beside it: the decision log, the notes behind each rule (its first wording, basis
  and what shipped), and how each check runs.
- [`web/REFERENCE.md`](web/REFERENCE.md) — the evidence: what the UI measurably is, where it disagrees with its own
  documents, and the questions still open.
- [`web/design-tokens.json`](web/design-tokens.json) — the exact values, a DTCG mirror of `web/src/app/globals.css`
  that `tests/unit/test_design_tokens.py` holds equal to it.
- [`web/examples/`](web/examples/README.md) — approved screens, of which there are none yet.
- [`web/CLAUDE.md`](web/CLAUDE.md) — when an agent reads the above, and how it checks its work.

Strategy, users and principles live in [PRODUCT.md](PRODUCT.md).

This file used to hold the visual rationale itself: why the default is dark, why attention is carried by chroma, why
an unmeasured figure is amber rather than grey. That text is kept verbatim, with its line numbers, as Appendix A of
`web/REFERENCE.md`, where the design notes cite it as `0ec084f:DESIGN.md:N`. Nothing in it was product rather than
design: each principle it restated — absence is a state, the uncomfortable state gets the attention, stopping is
easier than starting, the anti-references — is stated in PRODUCT.md already.
