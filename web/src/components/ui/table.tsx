"use client"

import * as React from "react"

import { useOverflows } from "@/lib/overflow"
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
 *   phone width (DESIGN.md A-7). The name is required: an optional one left
 *   /portfolio's positions, moved into a narrow column on 2026-09-27, a tab
 *   stop announced as nothing between 1024 and ~1190px wide, and the jobs,
 *   backtests, findings and hypotheses tables the same on a phone. Which
 *   tables overflow depends on the column and the zoom, not on the page, so
 *   every table carries one. Whether it overflows is `useOverflows`
 *   (`lib/overflow.ts`), written here and moved out on 2026-09-27 so the
 *   pipeline board on /programme, which scrolled in a plain div, could be the
 *   same region by the same measure.
 * - **It scrolls sideways and never down.** `overflow-x: auto` alone makes the
 *   y axis `auto` too, and a row rising into place (`.enter-stagger`, M-12)
 *   starts 4px below where it ends: the last rows overhung the container's
 *   bottom edge for the length of the entrance, and wherever scrollbars take
 *   space (Chrome on Windows and Linux) a 15px vertical bar came and went,
 *   narrowing the table and shifting every column sideways, twice. Nothing in
 *   a table is meant to overhang it vertically, so the y axis clips.
 */

function Table({
  className,
  label,
  ...props
}: React.ComponentProps<"table"> & {
  /** What the scroller is called when it takes focus, e.g. "Workers". */
  label: string
}) {
  const container = React.useRef<HTMLDivElement>(null)
  const scrolls = useOverflows(container)
  return (
    <div
      ref={container}
      data-slot="table-container"
      className="relative w-full overflow-x-auto overflow-y-hidden"
      tabIndex={scrolls ? 0 : undefined}
      role={scrolls ? "region" : undefined}
      aria-label={scrolls ? `${label}, scrolls sideways` : undefined}
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
