/**
 * fresh.ts
 * --------
 * Whether a reading is still young enough to be called current.
 *
 * The live pulse (web/DESIGN.md M-10, M-10r) claims that the heartbeat it
 * sits on is being heard now. The pages used to derive that claim from two
 * things: the row's own `stale`, and whether their last refresh had *failed*.
 * Neither says how old the reading is. A refresh that never settles has not
 * failed, a tab the browser throttles polls late, a laptop that slept has not
 * polled at all — and in each the reading on screen stops getting newer while
 * nothing fails, so the halo went on breathing "alive" over it. The API's
 * reads now time out (`READ_TIMEOUT_MS` in `api.ts`), which turns a hang into
 * a failure; this bounds the claim itself, whatever kept a newer reading from
 * arriving.
 *
 * `useFresh(readAt, maxAgeMs)` is true from the moment a reading arrives until
 * it is `maxAgeMs` old, and false from then until the next one. The pages
 * pass twice their poll interval: one poll may be late, not two.
 *
 * One timer per reading, set for the moment it expires, rather than a clock
 * that ticks: the page re-renders once when its reading goes stale, not every
 * second. It looks again when the tab becomes visible, because a browser may
 * hold a hidden tab's timers back for a minute, and the first thing an
 * operator coming back to the tab reads must not be a halo that a late timer
 * has not yet taken down.
 */

import { useEffect, useState } from "react";

export function useFresh(
  readAt: string | null | undefined,
  maxAgeMs: number,
): boolean {
  const parsed = readAt == null ? Number.NaN : Date.parse(readAt);
  const at = Number.isNaN(parsed) ? null : parsed;
  // The reading this hook has seen outlive its bound, by its timestamp, so a
  // newer reading is fresh again without anything having to be reset.
  const [expired, setExpired] = useState<number | null>(null);

  useEffect(() => {
    if (at === null) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const check = () => {
      clearTimeout(timer);
      const left = at + maxAgeMs - Date.now();
      if (left <= 0) setExpired(at);
      // A timer can fire a moment early; look again rather than trust it.
      else timer = setTimeout(check, left);
    };
    check();
    document.addEventListener("visibilitychange", check);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", check);
    };
  }, [at, maxAgeMs]);

  return at !== null && expired !== at;
}
