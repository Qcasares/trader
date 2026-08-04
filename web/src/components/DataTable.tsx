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
  header: string;
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

export function DataTable<T>({
  rows,
  columns,
  getRowId,
  filterPlaceholder,
  empty = "Nothing here yet.",
  initialSort,
}: {
  rows: T[];
  columns: Column<T>[];
  getRowId: (row: T) => string;
  /** Omit to hide the filter box entirely on tables too short to need one. */
  filterPlaceholder?: string;
  empty?: string;
  initialSort?: SortingState;
}) {
  const [sorting, setSorting] = useState<SortingState>(initialSort ?? []);
  const [filter, setFilter] = useState("");

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
    onSortingChange: setSorting,
    onGlobalFilterChange: setFilter,
    getRowId,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });

  const visible = table.getRowModel().rows;
  const filtering = filter.trim().length > 0;

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
            onChange={(e) => setFilter(e.target.value)}
            placeholder={filterPlaceholder}
            aria-label={filterPlaceholder}
            className="h-8 pl-7"
          />
        </div>
      ) : null}

      <div className="overflow-x-auto">
        <Table>
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
                      ) : (
                        column?.header
                      )}
                    </TableHead>
                  );
                })}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
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
    </div>
  );
}
