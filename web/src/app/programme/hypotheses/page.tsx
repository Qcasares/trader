"use client";

/**
 * The hypothesis ledger.
 *
 * Rejected hypotheses are listed alongside open ones and are never hidden by
 * default. That is not a UI preference: the proportion of failed experiments
 * retained is one of the programme's own integrity metrics, and a ledger that
 * quietly drops its failures reports that metric as perfect while being
 * worthless. The schema enforces the same thing — a DELETE on `hypotheses` is
 * a no-op — so the list and the store agree.
 *
 * `variants_tried` is shown on every row for the same reason a backtest count
 * is shown on the strategy list: a result selected from twenty attempts is not
 * the same evidence as a result from one, and the count is the only thing on
 * the page that says which happened.
 *
 * Rebuilt on `DataTable` for sorting and a free-text filter, alongside the
 * server-side status filter the API already supported. Two things this
 * rebuild is careful about:
 *
 * - **Status does not borrow `unknown`.** `unknown` on this system means "not
 *   measured", not "amber warning" — `superseded` is a known, reported
 *   outcome, so it maps to the same quiet `mute` badge as `open` rather than
 *   to the state reserved for an absent measurement.
 * - **The "every extra variant is another draw" explanation used to live in a
 *   `title=` tooltip on the cell**, which a screen reader and a mouse-free
 *   operator both miss. It is now visible text next to the table, because it
 *   is the same multiple-testing warning this codebase makes visible
 *   everywhere else a search could flatter its own best result.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ApiError, api, type Hypothesis } from "@/lib/api";
import { Skeleton } from "@/components/Skeleton";
import { AiBadge } from "@/components/GateChecklist";
import { StatusBadge, type Status } from "@/components/StatusBadge";
import { DataTable } from "@/components/DataTable";
import { fmtInstant } from "@/lib/format";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

/**
 * Hypothesis status onto the four house states. `rejected` is the loud one
 * because it is measured and it failed; `open` and `superseded` are both
 * `mute` — real, reported states with nothing unmeasured about either.
 */
const STATUS: Record<Hypothesis["status"], Status> = {
  open: "mute",
  accepted: "settled",
  rejected: "blocked",
  superseded: "mute",
};

export default function HypothesisLedgerPage() {
  const router = useRouter();
  const [rows, setRows] = useState<Hypothesis[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>("");

  const refresh = useCallback(async () => {
    try {
      setRows(await api.hypotheses(filter || undefined));
      setError(null);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.isUnauthorized) {
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [router, filter]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (error && !rows) return <p className="banner banner-bad">{error}</p>;
  if (!rows) return <Skeleton rows={5} label="Loading the ledger" />;

  const rejected = rows.filter((r) => r.status === "rejected").length;

  return (
    <>
      <div className="mb-4">
        <h1 className="mb-1">Hypothesis ledger</h1>
        <p className="m-0 text-base text-ink-muted">
          Every idea this programme has had, including the ones that failed.
          The schema refuses to delete a row, so the record of what was tried
          cannot be tidied into a record of what worked.
        </p>
      </div>

      {error ? <p className="banner banner-bad">{error}</p> : null}

      <Card>
        <CardHeader>
          <CardTitle>Ledger</CardTitle>
          <p className="m-0 text-sm text-ink-muted text-pretty">
            Variants counts how many configurations an idea has spawned —
            every extra one is another draw, and a result selected from many
            is not the same evidence as a result from one.
          </p>
          <div className="flex flex-wrap items-center gap-3 pt-1">
            <Select
              value={filter || "all"}
              onValueChange={(v) => setFilter(v === "all" ? "" : v)}
            >
              <SelectTrigger size="sm" className="w-44" aria-label="Status">
                <SelectValue placeholder="All statuses" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All ({rows.length})</SelectItem>
                <SelectItem value="open">Open</SelectItem>
                <SelectItem value="accepted">Accepted</SelectItem>
                <SelectItem value="rejected">Rejected</SelectItem>
                <SelectItem value="superseded">Superseded</SelectItem>
              </SelectContent>
            </Select>
            {filter === "" && rejected > 0 ? (
              <span className="text-sm text-ink-muted">
                {rejected} rejected, shown deliberately
              </span>
            ) : null}
          </div>
        </CardHeader>
        <CardContent>
          <DataTable
            rows={rows}
            getRowId={(row) => row.ref}
            filterPlaceholder="Filter by ref, title or owner"
            empty="Nothing yet. Enable the programme and run a pass, or add a card yourself."
            initialSort={[{ id: "proposed", desc: true }]}
            columns={[
              {
                id: "ref",
                header: "Ref",
                sortable: true,
                sortValue: (row) => row.ref,
                className: "font-mono",
                cell: (row) => (
                  <Link href={`/programme/hypotheses/${row.ref}`}>
                    {row.ref}
                  </Link>
                ),
              },
              {
                id: "title",
                header: "Title",
                sortable: true,
                sortValue: (row) => row.title,
                cell: (row) => (
                  <span className="inline-flex items-center gap-2">
                    {row.title}
                    <AiBadge origin={row.origin} />
                  </span>
                ),
              },
              {
                id: "owner",
                header: "Owner",
                sortable: true,
                // Empty is missing, not the empty string sorting to the top.
                sortValue: (row) => row.owner || undefined,
                className: "text-ink-muted",
                cell: (row) => row.owner || "unassigned",
              },
              {
                id: "variants",
                header: "Variants",
                sortable: true,
                sortValue: (row) => row.variants_tried,
                headerClassName: "text-right",
                className: "text-right font-mono tabular-nums",
                cell: (row) => row.variants_tried,
              },
              {
                id: "status",
                header: "Status",
                sortable: true,
                sortValue: (row) => row.status,
                cell: (row) => (
                  <StatusBadge status={STATUS[row.status]}>
                    {row.status}
                  </StatusBadge>
                ),
              },
              {
                id: "proposed",
                header: "Proposed",
                sortable: true,
                sortValue: (row) => row.created_at,
                className: "text-ink-muted whitespace-nowrap",
                cell: (row) => fmtInstant(row.created_at),
              },
            ]}
          />
        </CardContent>
      </Card>
    </>
  );
}
