/**
 * Skeleton
 * --------
 * What a page shows while it is fetching.
 *
 * A spinner in the middle of an empty page tells an operator that something is
 * happening and nothing about what. A skeleton in the shape of the thing being
 * loaded tells them what is arriving and how much of it, which on a page that
 * polls every ten seconds is the difference between waiting and watching.
 *
 * `aria-busy` and the visually-hidden label carry the same information to a
 * screen reader, which sees no shape at all.
 *
 * The sweep animation has a `prefers-reduced-motion` alternative in
 * `globals.css` — a steady opacity pulse rather than nothing. Removing it
 * outright would leave a static grey block that reads as a broken layout.
 */

export function Skeleton({
  rows = 3,
  label = "Loading",
}: {
  rows?: number;
  label?: string;
}) {
  return (
    <div aria-busy="true" aria-live="polite">
      <span className="visually-hidden">{label}</span>
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          className={
            "skeleton skeleton-row " +
            // Varied widths: a stack of identical bars reads as a loading
            // graphic, varied ones read as text that has not arrived.
            (i % 3 === 0 ? "skeleton-w-70" : i % 3 === 1 ? "" : "skeleton-w-40")
          }
        />
      ))}
    </div>
  );
}

/**
 * The metric grid's loading shape. Used where the page's first content is a
 * row of figures rather than prose, so the skeleton matches what replaces it.
 */
export function SkeletonMetrics({ count = 4 }: { count?: number }) {
  return (
    <div aria-busy="true" aria-live="polite">
      <span className="visually-hidden">Loading</span>
      <dl className="metric-grid">
        {Array.from({ length: count }, (_, i) => (
          <div className="metric" key={i}>
            <dt>
              <span className="skeleton skeleton-w-40" />
            </dt>
            <dd>
              <span className="skeleton skeleton-w-70" />
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
