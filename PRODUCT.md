# Product

## Register

product

## Users

One technical operator, alone, thinking carefully. Long sessions at a desk
rather than glances on a phone. They arrive with a specific question and the
question is almost always some form of *should I believe this?* — is this
backtest a result or an artefact, is this process actually alive, has this
candidate earned the next stage, is anything blocking that I have not seen.

They are the author of the system as well as its operator, so they know what
every number means and do not need it explained. What they need is for the
interface to make the *unflattering* facts as easy to find as the flattering
ones, because they are the only person checking.

The job to be done: tell a real result from a result that merely looks good,
and act on the difference.

## Product Purpose

A systematic trading platform. Deterministic, backtestable strategies with a
research lab, a live control plane, and an AI programme that proposes and
governs candidates without ever being able to place an order.

The product exists because a research UI is a machine for fooling yourself.
Edit a parameter, rerun, look at the Sharpe, repeat: do that twenty times and
the best result is the luckiest one. Every meaningful feature here is a defence
against that loop — walk-forward studies, preregistered acceptance criteria
that cannot be edited after the answer arrives, promotion gates that read rows
rather than prose, an append-only ledger that cannot be tidied.

Success is not that the operator ships a strategy. Success is that when a
strategy is bad, the interface says so plainly and early, and when a figure has
not been measured, the interface never lets it pass for zero.

## Brand Personality

**A laboratory instrument.** Exact, annotated, unflinching.

Calm in normal operation and unmissable when something is wrong. The tone of a
piece of equipment you trust precisely because it reports what it *cannot*
measure. It does not celebrate, it does not reassure, and it does not round.

Voice: plain, specific, and willing to be the bearer of bad news. Never
promotional. Never soothing. A refusal always says what would satisfy it, so
the operator learns what to produce rather than that they were told no.

## Anti-references

- **Navy-and-gold institutional finance.** Deep navy, gold accents, serif
  wordmark, borrowed gravitas. The first reflex in this category and a costume
  rather than a design.
- **Terminal-green-on-black.** The second reflex: having rejected navy-and-gold,
  everyone lands on Bloomberg cosplay — monospace green on pure black. Now as
  saturated as the thing it was avoiding. Monospace numerals are correct here;
  the phosphor-terminal *aesthetic* is not.
- **Cream, sand, paper and every warm near-white body.** The saturated default.
  Whatever warmth this system has is carried by type and by restraint, never by
  tinting the background toward parchment.

Noted separately, because it is a fact about the code rather than a stated
preference: the current palette is GitHub Primer near-verbatim. It is
recognisably another product's identity and is being replaced as part of this
work.

## Design Principles

1. **Absence is a state, not a zero.** An unmeasured figure is rendered as
   *not measured*, a missing figure as *no data*. Never as 0, never as a blank
   cell, never as a dash that could be mistaken for a value. The code already
   holds this line at every layer; the interface is the last place it can be
   broken, and the most consequential.

2. **Every number carries its provenance.** A Sharpe without its standard
   error, a return without its cost assumption, a metric without its window —
   these are not figures, they are decoration. If a value is on screen, what it
   depends on is within a glance of it.

3. **The uncomfortable state gets the attention.** Refusals, unmet criteria,
   blocking findings and stale processes are the information the operator came
   for. Success is the boring case and should look like it. This inverts the
   usual dashboard instinct, and it is deliberate.

4. **Stopping is easier than starting.** Every control is asymmetric: the safe
   direction takes one action, the committing direction takes a deliberate one.
   The API already enforces this; the interface must make the asymmetry
   *visible*, so the shape of a control tells you which way is which before you
   read the label.

5. **Density with provenance, not simplification.** This operator is reading
   evidence, not skimming a summary. Hiding detail to look calm would be a
   design that flatters the interface at the expense of the work. Earn calm
   through hierarchy and rhythm, never through omission.

## Accessibility & Inclusion

**WCAG 2.2 AA**, and colour is never the only channel.

Status is currently green / amber / red pills on every gate criterion, finding,
scorecard row and experiment conclusion. That is the textbook red-green
failure, and it matters more here than in most products: this interface is
status-dense, the statuses are the point, and roughly 8% of men have some form
of red-green colour vision deficiency.

Every status therefore carries a second channel — a shape, a mark, a written
label, or a position — such that the colour could be removed entirely without
losing information.

Also required:

- Body text ≥ 4.5:1, large text ≥ 3:1, placeholders held to the body ratio.
- `prefers-reduced-motion` honoured with a real alternative, not a removal.
- Every control reachable and operable by keyboard, with a visible focus ring
  that is not the browser default suppressed and never replaced.
- Numeric tables aligned and monospaced so figures can be compared down a
  column without reading each one.
