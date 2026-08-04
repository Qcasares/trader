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
 *   from position in the order.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ApiError, api, fmtNum, fmtPct, type BacktestRun } from "@/lib/api";
import { DataTable } from "@/components/DataTable";
import { StatusBadge, jobStatus } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/Skeleton";

/** An absent figure. A bare dash beside right-aligned numbers reads as a minus. */
const NO_DATA = <span className="no-data">no data</span>;

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
            <DataTable
              rows={runs}
              getRowId={(run) => run.id}
              filterPlaceholder="Filter by strategy or source"
              initialSort={[{ id: "window", desc: true }]}
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
                  cell: (run) => `${run.start_session} → ${run.end_session}`,
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
                  sortValue: (run) => run.metrics?.total_return,
                  headerClassName: "text-right",
                  className: "text-right font-mono tabular-nums",
                  cell: (run) =>
                    run.metrics ? fmtPct(run.metrics.total_return) : NO_DATA,
                },
                {
                  id: "sharpe",
                  header: "Sharpe",
                  sortable: true,
                  sortValue: (run) => run.metrics?.sharpe,
                  headerClassName: "text-right",
                  className:
                    "text-right font-mono tabular-nums whitespace-nowrap",
                  cell: (run) =>
                    run.metrics ? (
                      <span
                        className={
                          run.metrics.sharpe_is_significant ? "" : "muted"
                        }
                        title={
                          run.metrics.sharpe_is_significant
                            ? "Clears two standard errors from zero"
                            : "Within two standard errors of zero — not significant"
                        }
                      >
                        {fmtNum(run.metrics.sharpe)} ±{" "}
                        {fmtNum(run.metrics.sharpe_stderr)}
                      </span>
                    ) : (
                      NO_DATA
                    ),
                },
                {
                  id: "drawdown",
                  header: "Max DD",
                  sortable: true,
                  sortValue: (run) => run.metrics?.max_drawdown,
                  headerClassName: "text-right",
                  className: "text-right font-mono tabular-nums",
                  cell: (run) =>
                    run.metrics ? fmtPct(run.metrics.max_drawdown) : NO_DATA,
                },
                {
                  id: "cost",
                  header: "Cost",
                  sortable: true,
                  sortValue: (run) => run.metrics?.cost_stress_multiplier,
                  headerClassName: "text-right",
                  className: "text-right font-mono tabular-nums",
                  cell: (run) =>
                    run.metrics
                      ? `${run.metrics.cost_stress_multiplier}×`
                      : NO_DATA,
                },
                {
                  id: "open",
                  header: "",
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
