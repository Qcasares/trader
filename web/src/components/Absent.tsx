/**
 * Absent.tsx
 * ----------
 * The one way this interface says a value does not exist.
 *
 * The owner's decision of 2026-09-26: an absence says why. Three words, one
 * reason each —
 *
 * - **not measured**: a metric that was never computed;
 * - **no data**: an observation that never arrived;
 * - **missing**, with the reason: a required field nobody supplied, and what
 *   its absence blocks.
 *
 * Never a bare dash, and never a zero. Beside right-aligned numbers a dash
 * reads as a minus sign, and a zero is a measurement: an unmeasured figure
 * rendered as `0` asserts a value nobody observed, which is the lie CLAUDE.md's
 * honesty rules exist to prevent. `?? 0`, `?? 252` and a bare "—" are refused
 * in `web/src` by `tests/unit/test_web_formatting.py`; this is what to write
 * instead. A genuine zero stays a zero — this is for null and undefined, never
 * for a figure that happens to be small.
 *
 * Rendered as the `.no-data` label (sans, small caps, muted) so it cannot be
 * read as a figure even inside a monospace numeric cell. A screen reader hears
 * the word and then a visually hidden sentence saying what kind of absence it
 * is — the words are terse, and a listener does not see the styling that
 * tells a sighted reader this is a label rather than a value. The sentences
 * are true in every place an absence appears (a figure, a seed, a card field),
 * so none of them claims "not zero" about something that was never a number.
 * `data-absent` carries the kind, for tests and for anything that has to count
 * absences without reading prose.
 */

import { ABSENCE_WORDS, type AbsenceKind } from "@/lib/format";

/** Read after the word by assistive technology. */
const DESCRIPTIONS: Record<AbsenceKind, string> = {
  "not-measured": "Never computed, so there is no value to show.",
  "no-data": "Nothing has been recorded for this.",
  missing: "Required, and not supplied.",
};

type Props =
  | { kind: "not-measured" | "no-data"; reason?: string }
  | { kind: "missing"; reason: string };

export function Absent({ kind, reason }: Props) {
  return (
    // `whitespace-normal`: table cells here are `nowrap`, and two words that
    // may wrap keep a column of figures as narrow as its figures.
    <span data-absent={kind} className="whitespace-normal">
      <span className="no-data">{ABSENCE_WORDS[kind]}</span>
      {reason ? (
        <span className="font-sans text-sm text-ink-muted"> — {reason}</span>
      ) : null}
      <span className="visually-hidden"> {DESCRIPTIONS[kind]}</span>
    </span>
  );
}
