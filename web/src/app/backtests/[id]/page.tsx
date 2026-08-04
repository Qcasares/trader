"use client";

/**
 * Backtest detail.
 *
 * Polls while the run is queued or running, because a 25-year backtest takes
 * long enough that a static page would just look broken.
 */

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
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
      <div className="spread">
        <div>
          <h1>{run.strategy_name}</h1>
          <p className="subtitle mono">
            {run.id} · {run.universe.join(" ")}
          </p>
        </div>
        <StatusPill status={run.status} />
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
          <EquityChart
            points={equity}
            effectiveStart={run.metrics.effective_start}
          />
          <MetricsPanel run={run} metrics={run.metrics} />

          <h2>Fills ({orders.length})</h2>
          <div className="card table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Session</th>
                  <th>Symbol</th>
                  <th>Side</th>
                  <th className="num">Qty</th>
                  <th className="num">Price</th>
                  <th className="num">Notional</th>
                  <th className="num">Commission</th>
                </tr>
              </thead>
              <tbody>
                {orders.slice(0, 200).map((order, index) => (
                  <tr key={`${order.session}-${order.symbol}-${index}`}>
                    <td>{order.session}</td>
                    <td>{order.symbol}</td>
                    <td>
                      <span
                        className={`pill ${
                          order.side === "buy" ? "pill-good" : "pill-warn"
                        }`}
                      >
                        {order.side}
                      </span>
                    </td>
                    <td className="num">{order.qty.toFixed(4)}</td>
                    <td className="num">{fmtUsd(order.price)}</td>
                    <td className="num">{fmtUsd(order.notional)}</td>
                    <td className="num">{fmtUsd(order.commission)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {orders.length > 200 && (
              <p className="muted" style={{ marginTop: 8 }}>
                Showing the 200 most recent of {orders.length}.
              </p>
            )}
          </div>
        </>
      )}

      <p style={{ marginTop: 20 }}>
        <Link href="/backtests">← All backtests</Link>
      </p>
    </>
  );
}

function StatusPill({ status }: { status: string }) {
  const tone =
    status === "succeeded"
      ? "pill-good"
      : status === "failed"
        ? "pill-bad"
        : status === "running"
          ? "pill-warn"
          : "pill-mute";
  return <span className={`pill ${tone}`}>{status}</span>;
}
