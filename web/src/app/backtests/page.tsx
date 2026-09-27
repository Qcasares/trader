"use client";

/**
 * Backtest history.
 *
 * Sharpe is never shown without its error bar, and that is the page's whole
 * reason for existing in this shape. Five years of daily data gives a standard
 * error of roughly ±0.45, so a reported 0.50 is indistinguishable from zero; a
 * table of bare Sharpe ratios sorted descending is a machine for picking the
 * luckiest run and calling it the best one.
 *
 * Adding sorting sharpened that risk rather than softening it, so three things
 * guard against it:
 *
 * - **An unmeasured figure sorts to the end in both directions.** A run with no
 *   metrics has not got the worst Sharpe; it has no Sharpe. `sortUndefined`
 *   keeps it out of the ranking instead of settling it at the bottom of an
 *   ascending sort, where it would read as the former.
 * - **The error bar travels in the same cell as the figure**, so no sort can
 *   separate a number from its uncertainty.
 * - **Significance is marked on every row**, rather than left to be inferred
 *   from position in the order — and marked in words. It used to be a muted
 *   colour plus a `title` tooltip: 2.2:1 from the significant state on dark,
 *   invisible to anyone who cannot tell the two greys apart, and unreachable
 *   by keyboard. A non-significant estimate now carries a "not significant"
 *   chip beside its standard error, read from the stored
 *   `sharpe_is_significant` rather than recomputed here.
 *
 * Two more honesty rules bind a list of results as much as a tearsheet: every
 * metric carries the session the whole universe first existed, and every
 * annualised figure carries the session count it was annualised on. A result
 * spanning a smaller universe, or annualised on the wrong year, looks exactly
 * like one that does not until both are on the same row. So the Window cell
 * reads the way the tearsheet's assumptions do — requested window, effective
 * start, annualised on — rather than growing two columns, which pushed the
 * cost column out of view at laptop widths, and the cost assumption is an
 * honesty rule too.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ApiError, api, type BacktestRun } from "@/lib/api";
import { fmtNum, fmtPct } from "@/lib/format";
import { Absent } from "@/components/Absent";
import { DataTable } from "@/components/DataTable";
import { StatusBadge, jobStatus } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/Skeleton";

/**
 * A figure of a run that has none yet — queued, running or failed. Its metrics
 * were never computed, which is "not measured", not a zero and not a dash (a
 * dash beside right-aligned numbers reads as a minus).
 */
const NOT_MEASURED = <Absent kind="not-measured" />;

export default function BacktestsPage() {
  const router = useRouter();
  const [runs, setRuns] = useState<BacktestRun[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .backtests({ limit: 100 })
      .then(setRuns)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.isUnauthorized) {
          router.push("/login");
          return;
        }
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => setLoading(false));
  }, [router]);

  if (loading) return <Skeleton rows={6} label="Loading backtests" />;
  if (error) return <p className="banner banner-bad">{error}</p>;

  return (
    <>
      <h1>Backtests</h1>
      <p className="subtitle">
        {runs.length} run{runs.length === 1 ? "" : "s"}. Every Sharpe is shown
        with its standard error — a figure inside two of them is not evidence.
      </p>

      {runs.length === 0 ? (
        <Card>
          <CardContent className="py-6 text-center">
            <p className="mb-3 text-ink-muted">Nothing yet.</p>
            <Button asChild size="sm">
              <Link href="/">Configure a strategy</Link>
            </Button>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent>
            {/*
              `stagger`: the list is read once, when the page opens — nothing
              polls it — and the table mounts once, when the skeleton gives way
              to it, with each run keyed by its id. So the runs rise into
              place once, and never again for a reading.
            */}
            <DataTable
              label="Backtests"
              rows={runs}
              getRowId={(run) => run.id}
              filterPlaceholder="Filter by strategy or source"
              initialSort={[{ id: "window", desc: true }]}
              stagger
              columns={[
                {
                  id: "strategy",
                  header: "Strategy",
                  sortable: true,
                  sortValue: (run) => run.strategy_name,
                  cell: (run) => run.strategy_name,
                },
                {
                  id: "window",
                  header: "Window",
                  sortable: true,
                  sortValue: (run) => run.start_session,
                  className: "font-mono whitespace-nowrap",
                  cell: (run) => (
                    <>
                      {run.start_session} → {run.end_session}
                      {run.metrics ? (
                        <>
                          <span className="block text-xs text-ink-muted">
                            effective from{" "}
                            {run.metrics.effective_start ?? (
                              <Absent kind="not-measured" />
                            )}
                          </span>
                          {/* The year the Sharpe on this row was annualised
                              on. 252 is the NYSE year; a venue that never
                              closes has 365, and the difference moves
                              volatility and the Sharpe by about a fifth. */}
                          <span className="block text-xs text-ink-muted">
                            annualised on{" "}
                            {run.metrics.periods_per_year == null ? (
                              <Absent kind="not-measured" />
                            ) : (
                              `${run.metrics.periods_per_year}/yr`
                            )}
                          </span>
                        </>
                      ) : null}
                    </>
                  ),
                },
                {
                  id: "source",
                  header: "Source",
                  sortable: true,
                  sortValue: (run) => run.data_source,
                  cell: (run) =>
                    run.data_source === "synthetic" ? (
                      // Amber rather than neutral. Synthetic prices are
                      // generated, not observed: the run is real and the
                      // arithmetic is correct, but the result is not evidence
                      // about a strategy — which is why the API refuses to let
                      // one back a deployment.
                      <StatusBadge status="unknown">synthetic</StatusBadge>
                    ) : (
                      run.data_source
                    ),
                },
                {
                  id: "status",
                  header: "Status",
                  sortable: true,
                  sortValue: (run) => run.status,
                  cell: (run) => (
                    <StatusBadge status={jobStatus(run.status)}>
                      {run.status}
                    </StatusBadge>
                  ),
                },
                {
                  id: "return",
                  header: "Return",
                  sortable: true,
                  // A figure the run did not record is `null` from the API, and
                  // `undefined` here, so it sorts last like a run with none.
                  sortValue: (run) => run.metrics?.total_return ?? undefined,
                  headerClassName: "text-right",
                  className: "text-right font-mono tabular-nums",
                  cell: (run) =>
                    run.metrics?.total_return == null
                      ? NOT_MEASURED
                      : fmtPct(run.metrics.total_return),
                },
                {
                  id: "sharpe",
                  header: "Sharpe",
                  sortable: true,
                  sortValue: (run) => run.metrics?.sharpe ?? undefined,
                  headerClassName: "text-right",
                  className:
                    "text-right font-mono tabular-nums whitespace-nowrap",
                  cell: (run) =>
                    // Never a Sharpe without its standard error: if either was
                    // not recorded, neither is shown.
                    run.metrics?.sharpe == null ||
                    run.metrics.sharpe_stderr == null ? (
                      NOT_MEASURED
                    ) : (
                      <span className="inline-flex flex-col items-end gap-1">
                        <span
                          className={
                            run.metrics.sharpe_is_significant === false
                              ? "muted"
                              : ""
                          }
                        >
                          {fmtNum(run.metrics.sharpe)} ±{" "}
                          {fmtNum(run.metrics.sharpe_stderr)}
                        </span>
                        {/* The engine's verdict, and only when it gave one:
                            a null is no verdict, not a "false". */}
                        {run.metrics.sharpe_is_significant === false && (
                          <StatusBadge status="unknown">not significant</StatusBadge>
                        )}
                      </span>
                    ),
                },
                {
                  id: "drawdown",
                  header: "Max DD",
                  sortable: true,
                  sortValue: (run) => run.metrics?.max_drawdown ?? undefined,
                  headerClassName: "text-right",
                  className: "text-right font-mono tabular-nums",
                  cell: (run) =>
                    run.metrics?.max_drawdown == null
                      ? NOT_MEASURED
                      : fmtPct(run.metrics.max_drawdown),
                },
                {
                  id: "cost",
                  header: "Cost",
                  sortable: true,
                  sortValue: (run) =>
                    run.metrics?.cost_stress_multiplier ?? undefined,
                  headerClassName: "text-right",
                  className: "text-right font-mono tabular-nums",
                  cell: (run) =>
                    !run.metrics ? (
                      NOT_MEASURED
                    ) : run.metrics.cost_stress_multiplier == null ? (
                      // A result that does not carry its cost assumption is
                      // missing one; 1× would be the cheapest guess going.
                      <Absent kind="missing" reason="not recorded" />
                    ) : (
                      `${run.metrics.cost_stress_multiplier}×`
                    ),
                },
                {
                  id: "open",
                  header: "Open",
                  hideHeader: true,
                  className: "text-right",
                  cell: (run) => (
                    <Button asChild variant="ghost" size="sm">
                      <Link href={`/backtests/${run.id}`}>view</Link>
                    </Button>
                  ),
                },
              ]}
            />
          </CardContent>
        </Card>
      )}
    </>
  );
}
