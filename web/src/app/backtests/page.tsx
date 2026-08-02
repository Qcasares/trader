"use client";

/** Backtest history. Sharpe is never shown without its error bar. */

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ApiError, api, fmtNum, fmtPct, type BacktestRun } from "@/lib/api";

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

  if (loading) return <p className="muted">Loading…</p>;
  if (error) return <p className="banner banner-bad">{error}</p>;

  return (
    <>
      <h1>Backtests</h1>
      <p className="subtitle">
        {runs.length} run{runs.length === 1 ? "" : "s"}. Every Sharpe is shown
        with its standard error — a figure inside two of them is not evidence.
      </p>

      {runs.length === 0 ? (
        <p className="muted">
          Nothing yet. <Link href="/">Configure a strategy</Link> to run one.
        </p>
      ) : (
        <div className="card table-scroll">
          <table>
            <thead>
              <tr>
                <th>Strategy</th>
                <th>Window</th>
                <th>Source</th>
                <th>Status</th>
                <th className="num">Return</th>
                <th className="num">Sharpe</th>
                <th className="num">Max DD</th>
                <th className="num">Cost</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id}>
                  <td>{run.strategy_name}</td>
                  <td>
                    {run.start_session} → {run.end_session}
                  </td>
                  <td>
                    {run.data_source === "synthetic" ? (
                      <span className="pill pill-warn">synthetic</span>
                    ) : (
                      run.data_source
                    )}
                  </td>
                  <td>
                    <span
                      className={`pill ${
                        run.status === "succeeded"
                          ? "pill-good"
                          : run.status === "failed"
                            ? "pill-bad"
                            : "pill-mute"
                      }`}
                    >
                      {run.status}
                    </span>
                  </td>
                  <td className="num">
                    {run.metrics ? fmtPct(run.metrics.total_return) : "—"}
                  </td>
                  <td className="num">
                    {run.metrics ? (
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
                      "—"
                    )}
                  </td>
                  <td className="num">
                    {run.metrics ? fmtPct(run.metrics.max_drawdown) : "—"}
                  </td>
                  <td className="num">
                    {run.metrics
                      ? `${run.metrics.cost_stress_multiplier}×`
                      : "—"}
                  </td>
                  <td>
                    <Link href={`/backtests/${run.id}`}>view</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
