"use client";

/**
 * DataTable.tsx
 * -------------
 * A sortable, filterable table.
 *
 * Adapted from Origin UI's "Basic data table made with TanStack Table", found
 * on 21st.dev. What is taken from it is the architecture — TanStack Table for
 * state, shadcn's `Table` for the markup, a header button that toggles sort —
 * and the dependency choice that comes with it.
 *
 * What is deliberately *not* taken is most of the component. The original
 * ships row selection, a delete flow behind an AlertDialog, column visibility
 * through a dropdown, and pagination. This app's tables are a jobs queue and a
 * backtest list: nothing here is deletable from the UI, there are no bulk
 * actions, and the lists are short enough that pagination would add a control
 * to press before you can see the thing you came for. Pasting all of it would
 * have meant four more Radix packages to carry for behaviour with no caller.
 *
 * Three things this adds that the original does not have, because they are
 * this product's rules rather than general ones:
 *
 * - **`sortValue`.** A column showing a badge or a formatted date must not sort
 *   by its rendered string, or "Aug 04" files under A and status sorts
 *   alphabetically rather than by severity. Columns supply the value they sort
 *   on, separately from the value they display.
 *
 * - **Sorting is opt-in per column.** A column with no meaningful order — a
 *   free-text error message — gets no sort button rather than a button that
 *   produces an arbitrary order and implies one exists.
 *
 * - **The empty state distinguishes "nothing" from "nothing matching".** A
 *   filtered-to-zero table that says "No jobs yet" is telling the operator the
 *   queue is empty when it is not, which is the same class of lie as rendering
 *   an unmeasured figure as a zero.
 *
 * TanStack Table is pinned to v8 deliberately. `npm install` resolves v9, which
 * is a different API — `useTable` and `create*RowModel` behind a feature-flag
 * system rather than `useReactTable` and `get*RowModel`. v8 is what the source
 * component targets and what the shadcn data-table documentation is written
 * against, so it is the version whose behaviour can be checked against a
 * reference rather than inferred. Moving to v9 is a deliberate migration with
 * its own docs to read, not a version bump to take by accident.
 *
 * One piece of motion, opt-in (`stagger`, owner decision OD-6): the rows rise
 * into place a few at a time when the table first fills. Only a page whose
 * rows stay mounted across its polls, under stable keys, should ask for it —
 * a row that mounts again rises again, and an entrance replayed on every poll
 * is motion that reports nothing. The table itself takes care of the other
 * way a row replays: being moved (see `moved` below).
 *
 * And a name (`label`), required: a table wider than its container scrolls
 * in a region that takes keyboard focus (`ui/table.tsx`), and a focus stop
 * with no name is announced as nothing at all (web/DESIGN.md A-7, L-6). Which
 * tables overflow depends on the column they sit in and the reader's zoom,
 * not on the page, so every table is named, not only the ones seen to
 * scroll.
 */

import { useMemo, useState } from "react";
import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ChevronsUpDown, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export type Column<T> = {
  /** Stable key, also the accessor when `value` is omitted. */
  id: string;
  /**
   * What the column is called. Never empty: a header cell with no text is a
   * column a screen reader announces as nothing, and axe reported exactly that
   * on the per-row "view" columns (web/DESIGN.md A-8). A column whose meaning
   * is plain from its cells names itself here and sets `hideHeader`.
   */
  header: string;
  /** Keep the header for assistive technology only (`sr-only`). */
  hideHeader?: boolean;
  /** What the cell renders. */
  cell: (row: T) => React.ReactNode;
  /**
   * What the row sorts and filters on. Falls back to the rendered cell only
   * when that cell is already a plain string — see the note above about badges
   * and dates sorting by their own appearance.
   */
  sortValue?: (row: T) => string | number | undefined;
  /** Omit to make the column unsortable, which is the honest default for prose. */
  sortable?: boolean;
  /** Set true only where the largest value is the one worth seeing first. */
  sortDescFirst?: boolean;
  className?: string;
  headerClassName?: string;
};

/**
 * Whether a row shown both before and now has changed places with another.
 *
 * Rows that arrived or left do not count: an arrival is inserted where it
 * belongs and leaves every other row where it was. Only a row that React has
 * to move — out of the document and back in further along — does, and that
 * is what restarts the browser's animation on it.
 */
function moved(before: readonly string[], after: readonly string[]): boolean {
  const now = new Set(after);
  const then = new Set(before);
  const kept = before.filter((id) => now.has(id));
  const order = after.filter((id) => then.has(id));
  return kept.some((id, at) => id !== order[at]);
}

function same(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((id, at) => id === b[at]);
}

export function DataTable<T>({
  rows,
  columns,
  getRowId,
  label,
  filterPlaceholder,
  empty = "Nothing here yet.",
  initialSort,
  stagger = false,
}: {
  rows: T[];
  columns: Column<T>[];
  getRowId: (row: T) => string;
  /**
   * What the table is called, e.g. "Jobs": the name its scroller is announced
   * by when the table is wider than the column it sits in (A-7).
   */
  label: string;
  /** Omit to hide the filter box entirely on tables too short to need one. */
  filterPlaceholder?: string;
  empty?: string;
  initialSort?: SortingState;
  /**
   * Rows rise into place when the table first fills (`.enter-stagger`, OD-6).
   * Only for a table that stays mounted across its page's polls and whose
   * `getRowId` is stable, so each row mounts once; the page that asks for it
   * says why that holds there.
   */
  stagger?: boolean;
}) {
  const [sorting, setSorting] = useState<SortingState>(initialSort ?? []);
  const [filter, setFilter] = useState("");
  // A row that arrives later rises too, since an arrival is a change worth
  // showing — until a row the table already shows first moves. The browser
  // restarts a CSS animation on an element that is moved in the document, so
  // a moved row would replay its entrance for a change that brought nothing
  // new: a sort or a filter the operator chose, or a refresh that changed
  // what a row sorts by — a finding closed on the register falls below the
  // blocking ones, and used to rise again as if it had just arrived. After
  // the first move the table stays still; an entrance that could not tell a
  // move from an arrival would be motion that reports nothing (M-12).
  const [rearranged, setRearranged] = useState(false);

  const defs = useMemo<ColumnDef<T>[]>(
    () =>
      columns.map((column) => ({
        id: column.id,
        accessorFn: (row: T) =>
          column.sortValue ? column.sortValue(row) : "",
        enableSorting: column.sortable ?? false,
        // An unmeasured figure sorts to the end in *both* directions rather
        // than to whichever end is smallest. This is the sort-order form of the
        // rule the badges follow: a backtest with no metrics has not got the
        // worst Sharpe in the list, it has no Sharpe, and letting it settle at
        // the bottom of an ascending sort would read as the former.
        sortUndefined: "last",
        // TanStack sorts numeric columns *descending* on the first click. That
        // is a reasonable default for a leaderboard and the wrong one here: the
        // status column sorts on a severity index where 0 is `failed`, so
        // descending-first means the first click buries the failures under the
        // successes — the exact opposite of why anyone clicks it. Ascending
        // first, unless a column asks otherwise.
        sortDescFirst: column.sortDescFirst ?? false,
        header: column.header,
        cell: ({ row }) => column.cell(row.original),
      })),
    [columns],
  );

  const table = useReactTable({
    data: rows,
    columns: defs,
    state: { sorting, globalFilter: filter },
    onSortingChange: (next) => {
      setRearranged(true);
      setSorting(next);
    },
    onGlobalFilterChange: setFilter,
    getRowId,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });

  const visible = table.getRowModel().rows;
  const filtering = filter.trim().length > 0;

  // The order this table last rendered, compared during render rather than in
  // an effect. An effect runs after React has committed the move, with the
  // entrance still on the body, and the browser has restarted the moved row's
  // animation by then; set here, the flag is part of the render that moves
  // the row, so React commits the move with the class already gone (React's
  // pattern for adjusting state when what a component renders changes).
  const order = visible.map((row) => row.id);
  const [shown, setShown] = useState(order);
  if (!same(shown, order)) {
    setShown(order);
    if (stagger && !rearranged && moved(shown, order)) setRearranged(true);
  }

  return (
    <div className="space-y-2">
      {filterPlaceholder ? (
        <div className="relative max-w-xs">
          <Search
            aria-hidden="true"
            className="pointer-events-none absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-ink-faint"
          />
          <Input
            value={filter}
            onChange={(e) => {
              setRearranged(true);
              setFilter(e.target.value);
            }}
            placeholder={filterPlaceholder}
            aria-label={filterPlaceholder}
            className="h-8 pl-7"
          />
        </div>
      ) : null}

      <Table label={label}>
        <TableHeader>
          {table.getHeaderGroups().map((group) => (
            <TableRow key={group.id}>
              {group.headers.map((header) => {
                const column = columns.find((c) => c.id === header.column.id);
                const sortable = header.column.getCanSort();
                const direction = header.column.getIsSorted();
                return (
                  <TableHead key={header.id} className={column?.headerClassName}>
                    {sortable ? (
                      <button
                        type="button"
                        onClick={header.column.getToggleSortingHandler()}
                        // The header is the control, so it announces the
                        // order it is in rather than leaving a bare glyph to
                        // carry it.
                        aria-label={`${column?.header}, ${
                          direction === "asc"
                            ? "sorted ascending"
                            : direction === "desc"
                              ? "sorted descending"
                              : "not sorted"
                        }`}
                        className="-ml-1 inline-flex items-center gap-1 rounded-sm px-1 py-0.5 hover:text-ink"
                      >
                        {column?.header}
                        {direction === "asc" ? (
                          <ArrowUp aria-hidden="true" className="size-3" />
                        ) : direction === "desc" ? (
                          <ArrowDown aria-hidden="true" className="size-3" />
                        ) : (
                          <ChevronsUpDown
                            aria-hidden="true"
                            className="size-3 text-ink-faint"
                          />
                        )}
                      </button>
                    ) : column?.hideHeader ? (
                      <span className="sr-only">{column.header}</span>
                    ) : (
                      column?.header
                    )}
                  </TableHead>
                );
              })}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody className={cn(stagger && !rearranged && "enter-stagger")}>
          {visible.length === 0 ? (
            <TableRow>
              <TableCell
                colSpan={columns.length}
                className="py-6 text-center text-ink-muted"
              >
                {/* "Nothing matching" and "nothing at all" are different
                    facts, and only one of them means the queue is empty. */}
                {filtering ? `No rows match “${filter}”.` : empty}
              </TableCell>
            </TableRow>
          ) : (
            visible.map((row) => (
              <TableRow key={row.id}>
                {row.getVisibleCells().map((cell) => {
                  const column = columns.find((c) => c.id === cell.column.id);
                  return (
                    <TableCell key={cell.id} className={cn(column?.className)}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  );
                })}
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  );
}
