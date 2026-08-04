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
 * - **An absent timestamp is never a fabricated one.** `null` renders as an
 *   em dash, not as the epoch and not as "now".
 * - **The precision shown is the precision that means something.** Seconds,
 *   because a control-plane change is an event an operator correlates with
 *   other events; microseconds are noise at that job.
 *
 * Rendered in the viewer's own locale and zone deliberately. This is a
 * single-operator instrument, and the question being asked is "was that before
 * or after I went to lunch" rather than "what did the server's clock say".
 */
export function fmtInstant(iso: string | null | undefined): string {
  if (!iso) return "—";
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
  if (!iso) return "—";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  return at.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}
