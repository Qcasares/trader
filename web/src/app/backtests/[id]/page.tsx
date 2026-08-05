"use client";

/**
 * Backtest detail.
 *
 * Polls while the run is queued or running, because a 25-year backtest takes
 * long enough that a static page would just look broken.
 *
 * Rebuilt on shadcn primitives to match `system/page.tsx` and
 * `backtests/page.tsx`. The polling logic, `MetricsPanel` (which already
 * carries all four honesty figures — cost assumption, effective start,
 * periods per year and the Sharpe standard error, in the same cell as the
 * figure they qualify) and `EquityChart` are untouched: nothing here changed
 * what they compute or say, only how the page around them is composed.
 * Three things changed:
 *
 * - **Sections are `Card`s** rather than the bare `.spread` header and inline
 *   `<h2>`s the old page used, so this page reads as the same instrument as
 *   System and Backtests rather than a third layout.
 * - **The status pill is `StatusBadge`**, driven by the same `jobStatus`
 *   mapping every other page uses, instead of a local `pill-*` ternary that
 *   only this file maintained.
 * - **Fills are a `DataTable`.** The 200-row cap stays (a 25-year daily
 *   rebalance can produce thousands of fills, and the table is not
 *   virtualised), but the fills within it are now filterable and sortable —
 *   qty, price, notional and commission are never null on a recorded fill,
 *   so no column here needs the "no data" treatment the orders/portfolio
 *   tables do.
 */

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { EquityChart } from "@/components/EquityChart";
import { MetricsPanel } from "@/components/MetricsPanel";
import {
  ApiError,
  api,
  fmtUsd,
  type BacktestOrder,
  type BacktestRun,
  type EquityPoint,
} from "@/lib/api";
import { Skeleton } from "@/components/Skeleton";
import { DataTable } from "@/components/DataTable";
import { StatusBadge, jobStatus } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function BacktestDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [run, setRun] = useState<BacktestRun | null>(null);
  const [equity, setEquity] = useState<EquityPoint[]>([]);
  const [orders, setOrders] = useState<BacktestOrder[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const fetched = await api.backtest(id);
      setRun(fetched);
      if (fetched.status === "succeeded") {
        const [curve, fills] = await Promise.all([
          api.equity(id),
          api.orders(id),
        ]);
        setEquity(curve);
        setOrders(fills);
      }
      return fetched.status;
    } catch (err: unknown) {
      if (err instanceof ApiError && err.isUnauthorized) {
        window.location.href = "/login";
        return "failed";
      }
      setError(err instanceof Error ? err.message : String(err));
      return "failed";
    }
  }, [id]);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    const tick = async () => {
      const status = await load();
      if (cancelled) return;
      // Keep polling only while there is something left to happen.
      if (status === "queued" || status === "running") {
        // On a serverless deployment there is no worker process, so nothing
        // would ever pick this job up. Nudge the API into running it.
        // Deliberately unawaited-on-failure: where a worker *does* exist the
        // endpoint is disabled and answers 404, which is the normal case and
        // not worth a line on screen. The page polls correctly either way.
        if (status === "queued") {
          try {
            await api.drain();
          } catch {
            /* no drain here; a worker has it */
          }
          if (cancelled) return;
        }
        timer = setTimeout(tick, 2000);
      }
    };
    void tick();

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [load]);

  if (error) return <p className="banner banner-bad">{error}</p>;
  if (!run) return <Skeleton rows={6} label="Loading this run" />;

  return (
    <>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="mb-1">{run.strategy_name}</h1>
          <p className="subtitle mono">
            {run.id} · {run.universe.join(" ")}
          </p>
        </div>
        <StatusBadge status={jobStatus(run.status)}>{run.status}</StatusBadge>
      </div>

      {(run.status === "queued" || run.status === "running") && (
        <p className="banner banner-info">
          {run.status === "queued"
            ? "Queued — waiting for a worker."
            : "Running. This page refreshes itself."}
        </p>
      )}

      {run.status === "failed" && (
        <p className="banner banner-bad">
          <strong>Failed.</strong> {run.error}
        </p>
      )}

      {run.status === "succeeded" && run.metrics && (
        <>
          <Card>
            <CardHeader>
              <CardTitle>Equity</CardTitle>
            </CardHeader>
            <CardContent>
              <EquityChart
                points={equity}
                effectiveStart={run.metrics.effective_start}
              />
            </CardContent>
          </Card>

          <Card className="mt-3">
            <CardHeader>
              <CardTitle>Performance</CardTitle>
            </CardHeader>
            <CardContent>
              <MetricsPanel run={run} metrics={run.metrics} />
            </CardContent>
          </Card>

          <Card className="mt-3">
            <CardHeader>
              <CardTitle>Fills ({orders.length})</CardTitle>
            </CardHeader>
            <CardContent>
              <DataTable
                rows={orders.slice(0, 200).map((order, index) => ({
                  ...order,
                  // `DataTable.getRowId` takes one argument, and fills have no
                  // natural id — two legs of the same rebalance can otherwise
                  // share session, symbol, side, qty and price. The index
                  // travels on the row instead so identity survives sorting.
                  rowKey: `${order.session}-${order.symbol}-${index}`,
                }))}
                getRowId={(order) => order.rowKey}
                filterPlaceholder="Filter fills by symbol"
                empty="No fills recorded."
                initialSort={[{ id: "session", desc: false }]}
                columns={[
                  {
                    id: "session",
                    header: "Session",
                    sortable: true,
                    sortValue: (o) => o.session,
                    className: "font-mono whitespace-nowrap",
                    cell: (o) => o.session,
                  },
                  {
                    id: "symbol",
                    header: "Symbol",
                    sortable: true,
                    sortValue: (o) => o.symbol,
                    className: "font-mono",
                    cell: (o) => o.symbol,
                  },
                  {
                    id: "side",
                    header: "Side",
                    sortable: true,
                    sortValue: (o) => o.side,
                    cell: (o) => (
                      <span
                        className={`font-mono text-xs ${
                          o.side === "buy" ? "text-settled" : "text-unknown"
                        }`}
                      >
                        {o.side}
                      </span>
                    ),
                  },
                  {
                    id: "qty",
                    header: "Qty",
                    sortable: true,
                    sortValue: (o) => o.qty,
                    headerClassName: "text-right",
                    className: "text-right font-mono tabular-nums",
                    cell: (o) => o.qty.toFixed(4),
                  },
                  {
                    id: "price",
                    header: "Price",
                    sortable: true,
                    sortValue: (o) => o.price,
                    headerClassName: "text-right",
                    className: "text-right font-mono tabular-nums",
                    cell: (o) => fmtUsd(o.price),
                  },
                  {
                    id: "notional",
                    header: "Notional",
                    sortable: true,
                    sortValue: (o) => o.notional,
                    headerClassName: "text-right",
                    className: "text-right font-mono tabular-nums",
                    cell: (o) => fmtUsd(o.notional),
                  },
                  {
                    id: "commission",
                    header: "Commission",
                    sortable: true,
                    sortValue: (o) => o.commission,
                    headerClassName: "text-right",
                    className: "text-right font-mono tabular-nums",
                    cell: (o) => fmtUsd(o.commission),
                  },
                ]}
              />
              {orders.length > 200 && (
                <p className="mt-2 mb-0 text-sm text-ink-muted">
                  Showing the 200 most recent of {orders.length}.
                </p>
              )}
            </CardContent>
          </Card>
        </>
      )}

      <p className="mt-4">
        <Button asChild variant="ghost" size="sm">
          <Link href="/backtests">
            <ArrowLeft aria-hidden="true" />
            All backtests
          </Link>
        </Button>
      </p>
    </>
  );
}
