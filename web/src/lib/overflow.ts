/**
 * overflow.ts
 * -----------
 * Whether an element's content is wider than the element, kept current.
 *
 * What makes a sideways scroller a focusable, named region while — and only
 * while — it scrolls (web/DESIGN.md L-6, A-7): a keyboard cannot scroll a
 * region it cannot focus, and axe reports one it cannot reach as
 * `scrollable-region-focusable`; a region that fits, given a tab stop, is a
 * stop that does nothing. Two scrollers use it: the shadcn `Table`'s container
 * (`components/ui/table.tsx`, where it was written) and the pipeline board on
 * /programme, which scrolled in a plain div and was unreachable whenever it
 * held no candidate to tab to (found in review, 2026-09-27).
 *
 * Measured on the element and on its first child, since content arriving —
 * rows, cards — widens what scrolls without resizing the box it scrolls in.
 */

import { useEffect, useState, type RefObject } from "react";

export function useOverflows(ref: RefObject<HTMLElement | null>): boolean {
  const [overflows, setOverflows] = useState(false);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const measure = () => setOverflows(element.scrollWidth > element.clientWidth + 1);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    if (element.firstElementChild) observer.observe(element.firstElementChild);
    return () => observer.disconnect();
  }, [ref]);
  return overflows;
}
