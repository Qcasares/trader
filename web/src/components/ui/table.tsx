"use client"

import * as React from "react"

import { cn } from "@/lib/utils"

/*
 * Changed from stock, and logged in web/DESIGN.md (K-8). Each part now
 * carries its whole look itself: until the owner's decision of 2026-09-26
 * (OD-3, K-15) the legacy `th`, `td` and `table` element rules in
 * `globals.css` filled in whatever these left unset, and the result was the
 * page's look rather than the component's.
 *
 * - **The head is the 11px caps label** the rest of the site uses for keys
 *   (DESIGN.md T-6), ruled in `--border-strong`. It used to get both from the
 *   legacy `th` rule, which also put a bordered, grey, 13px title-case chip
 *   around every sort button — so one header row set its labels two ways. A
 *   control placed in a head now takes the head's type, case included, which
 *   a `<button>` would otherwise reset.
 * - **Rows rule themselves in the hairline**; the legacy `td` border used to
 *   paint over theirs.
 * - **A table that scrolls sideways can be scrolled from the keyboard.** Its
 *   container becomes a focusable, named region while — and only while — its
 *   table is wider than it, so a table that fits costs no tab stop. axe
 *   reported the unreachable scroller on /system and the candidate page at
 *   phone width (DESIGN.md A-7).
 */

/** Whether the element's content is wider than the element, kept current. */
function useOverflows(ref: React.RefObject<HTMLElement | null>): boolean {
  const [overflows, setOverflows] = React.useState(false)
  React.useEffect(() => {
    const element = ref.current
    if (!element) return
    const measure = () =>
      setOverflows(element.scrollWidth > element.clientWidth + 1)
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    // The table as well as its container: rows arriving widen the content
    // without resizing the box it scrolls in.
    if (element.firstElementChild) observer.observe(element.firstElementChild)
    return () => observer.disconnect()
  }, [ref])
  return overflows
}

function Table({
  className,
  label,
  ...props
}: React.ComponentProps<"table"> & {
  /** What the scroller is called when it takes focus, e.g. "Workers". */
  label?: string
}) {
  const container = React.useRef<HTMLDivElement>(null)
  const scrolls = useOverflows(container)
  return (
    <div
      ref={container}
      data-slot="table-container"
      className="relative w-full overflow-x-auto"
      tabIndex={scrolls ? 0 : undefined}
      role={scrolls && label ? "region" : undefined}
      aria-label={scrolls && label ? `${label}, scrolls sideways` : undefined}
    >
      <table
        data-slot="table"
        className={cn("w-full caption-bottom text-sm tabular-nums", className)}
        {...props}
      />
    </div>
  )
}

function TableHeader({ className, ...props }: React.ComponentProps<"thead">) {
  return (
    <thead
      data-slot="table-header"
      className={cn("[&_tr]:border-b [&_tr]:border-line-strong", className)}
      {...props}
    />
  )
}

function TableBody({ className, ...props }: React.ComponentProps<"tbody">) {
  return (
    <tbody
      data-slot="table-body"
      className={cn("[&_tr:last-child]:border-0", className)}
      {...props}
    />
  )
}

function TableFooter({ className, ...props }: React.ComponentProps<"tfoot">) {
  return (
    <tfoot
      data-slot="table-footer"
      className={cn(
        "border-t bg-muted/50 font-medium [&>tr]:last:border-b-0",
        className
      )}
      {...props}
    />
  )
}

function TableRow({ className, ...props }: React.ComponentProps<"tr">) {
  return (
    <tr
      data-slot="table-row"
      className={cn(
        "border-b border-border transition-colors hover:bg-muted/50 has-aria-expanded:bg-muted/50 data-[state=selected]:bg-muted",
        className
      )}
      {...props}
    />
  )
}

function TableHead({ className, ...props }: React.ComponentProps<"th">) {
  return (
    <th
      data-slot="table-head"
      className={cn(
        "h-10 px-2 text-left align-middle text-xs font-medium tracking-wider whitespace-nowrap text-foreground uppercase [&:has([role=checkbox])]:pr-0 [&>[role=checkbox]]:translate-y-[2px] [&>button]:uppercase",
        className
      )}
      {...props}
    />
  )
}

function TableCell({ className, ...props }: React.ComponentProps<"td">) {
  return (
    <td
      data-slot="table-cell"
      className={cn(
        "p-2 align-middle whitespace-nowrap [&:has([role=checkbox])]:pr-0 [&>[role=checkbox]]:translate-y-[2px]",
        className
      )}
      {...props}
    />
  )
}

function TableCaption({
  className,
  ...props
}: React.ComponentProps<"caption">) {
  return (
    <caption
      data-slot="table-caption"
      className={cn("mt-4 text-sm text-muted-foreground", className)}
      {...props}
    />
  )
}

export {
  Table,
  TableHeader,
  TableBody,
  TableFooter,
  TableHead,
  TableRow,
  TableCell,
  TableCaption,
}
