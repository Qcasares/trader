/**
 * format.ts
 * ---------
 * Every figure and instant this interface renders is formatted here, and the
 * words for a value that does not exist are defined here.
 *
 * One file, because two copies of a formatter are two answers to what a figure
 * says. The daily report once appended "%" to `drawdown_pct`, a fraction, and
 * so rendered a 5.12% drawdown as "-0.051%" — while /portfolio, formatting the
 * same stored value through `fmtPct`, rendered "-5.12%". A drawdown reported a
 * hundred times too small is the kind of error that reads as good news.
 * `tests/unit/test_web_formatting.py` now refuses a percentage built anywhere
 * in `web/src` but this file.
 *
 * Three rules:
 *
 * - **Fractions are stored; percentages are rendered.** Every ratio the API
 *   returns — returns, drawdowns, volatility, exposure — is a fraction, and
 *   `fmtPct` is the only place one becomes a percentage.
 * - **An absent value is not formatted.** The number formatters take numbers.
 *   A null is the caller's to render, as `<Absent>` (`components/Absent.tsx`),
 *   which says *why* it is absent rather than borrowing a zero or a dash.
 * - **The precision shown is the precision that means something.**
 */

// ---------------------------------------------------------------------------
// Absence
// ---------------------------------------------------------------------------

/**
 * Why a value is absent. The owner's decision of 2026-09-26: an absence says
 * why, in one of three ways, and is never a bare dash and never a zero.
 */
export type AbsenceKind = "not-measured" | "no-data" | "missing";

export const ABSENCE_WORDS: Record<AbsenceKind, string> = {
  /** A metric that was never computed. */
  "not-measured": "not measured",
  /** An observation that never arrived. */
  "no-data": "no data",
  /** A required field nobody supplied. Always rendered with its reason. */
  missing: "missing",
};

// ---------------------------------------------------------------------------
// Numbers
// ---------------------------------------------------------------------------

/**
 * A stored fraction as a percentage: `-0.0512` renders "-5.12%".
 *
 * The only place in `web/src` a "%" is attached to a number. Anything that
 * wants a percentage passes the fraction it was given and lets this scale it.
 */
export const fmtPct = (fraction: number, digits = 2) =>
  `${(fraction * 100).toFixed(digits)}%`;

/**
 * Dollars, to the cent unless asked otherwise. A chart's scale passes
 * `digits = 0`: its ticks are positions rather than amounts anyone reads to the
 * cent, and the cents were what pushed the widest of them past its margin.
 */
export const fmtUsd = (value: number, digits = 2) =>
  value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: Math.min(digits, 2),
    maximumFractionDigits: digits,
  });

export const fmtNum = (value: number, digits = 3) => value.toFixed(digits);

/**
 * A heartbeat age, in the largest unit that still reads as a number.
 *
 * `age_seconds` is not nullable in the API contract, so the non-finite branch
 * should never fire — which is exactly why it must not be the one place that
 * quietly disagrees with the absence rule if it ever does. It lands in
 * right-aligned columns, where a bare dash would sit in the minus-sign
 * position. Three pages used to carry their own copy of this function, and
 * they disagreed about exactly that branch.
 */
export function fmtAge(seconds: number): string {
  if (!Number.isFinite(seconds)) return ABSENCE_WORDS["no-data"];
  if (seconds < 90) return `${Math.round(seconds)}s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)}m`;
  return `${Math.round(seconds / 3600)}h`;
}

// ---------------------------------------------------------------------------
// Instants
// ---------------------------------------------------------------------------

/**
 * Rendering an instant the operator can read at a glance.
 *
 * The API returns ISO 8601 with microseconds and an offset —
 * `2026-08-04T15:57:03.666843+00:00` — which is the right thing for a wire
 * format and the wrong thing under a heading that says "last changed by".
 * Nobody reads six decimal places of a second, and the width of the string
 * pushes the thing beside it off the line.
 *
 * Two rules, both of which this codebase already applies to numbers:
 *
 * - **An absent timestamp is never a fabricated one.** `null` renders as the
 *   words "no data" — not as the epoch, not as "now", and not as a dash. A
 *   caller that can hold a null should render `<Absent kind="no-data" />`
 *   itself; the words here keep a string-typed caller honest if one slips
 *   through.
 * - **The precision shown is the precision that means something.** Seconds,
 *   because a control-plane change is an event an operator correlates with
 *   other events; microseconds are noise at that job.
 *
 * Rendered in the viewer's own locale and zone deliberately. This is a
 * single-operator instrument, and the question being asked is "was that before
 * or after I went to lunch" rather than "what did the server's clock say".
 */
export function fmtInstant(iso: string | null | undefined): string {
  if (!iso) return ABSENCE_WORDS["no-data"];
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  return at.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/**
 * The same instant, without the date.
 *
 * For rows that all happened today and where repeating the date on each is
 * three columns of identical text.
 */
export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return ABSENCE_WORDS["no-data"];
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  return at.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}
