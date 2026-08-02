"use client";

/**
 * Portfolio.
 *
 * The live account: equity, P&L, drawdown against the high-water mark, and the
 * positions implied by recorded fills.
 *
 * Two rules govern this page, both learned elsewhere in the system:
 *
 * 1. **Unknown is not zero.** Every money field arrives nullable, and a null
 *    renders as an em dash with an explanatory banner — never as $0.00. A flat
 *    line at zero is exactly what a broken mark writer would also draw, so the
 *    two states must not look the same.
 *
 * 2. **Paper and live are never mixed.** Separate accounts, separate curves.
 *    The mode is on screen at all times rather than implied by a setting
 *    somewhere else.
 */

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { EquityChart } from "@/components/EquityChart";
import {
  ApiError,
  api,
  fmtPct,
  fmtUsd,
  type EquityPoint,
  type Portfolio,
  type PortfolioMark,
  type PortfolioMode,
} from "@/lib/api";

const MODES: PortfolioMode[] = ["paper", "live"];

export default function PortfolioPage() {
  const router = useRouter();
  const [mode, setMode] = useState<PortfolioMode>("paper");
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [marks, setMarks] = useState<PortfolioMark[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [next, history] = await Promise.all([
        api.portfolio(mode),
        api.portfolioHistory(mode),
      ]);
      setPortfolio(next);
      setMarks(history.marks);
      setError(null);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.isUnauthorized) {
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [mode, router]);

  useEffect(() => {
    void refresh();
    const timer = setInterval(refresh, 15000);
    return () => clearInterval(timer);
  }, [refresh]);

  // A mark has the same shape as an equity point, so the backtest's chart
  // draws the live curve with no second component and no translation layer.
  const points: EquityPoint[] = marks.map((m) => ({
    session: m.session,
    equity: m.equity,
    cash: m.cash,
    drawdown_pct: m.drawdown_pct,
  }));

  return (
    <main>
      <div className="spread">
        <div>
          <h1>Portfolio</h1>
          <p className="subtitle">
            The account, not a backtest. P&amp;L is a change in marked equity.
          </p>
        </div>
        <div className="row">
          {MODES.map((m) => (
            <button
              key={m}
              className={m === mode ? "primary" : undefined}
              onClick={() => setMode(m)}
            >
              {m}
            </button>
          ))}
        </div>
      </div>

      {error && <p className="banner banner-bad">{error}</p>}

      {portfolio?.note && (
        <p className="banner banner-info">
          <strong>No marks recorded yet.</strong> The equity curve begins once
          the worker has run an end-of-day mark. Nothing is wrong — there is
          simply nothing to report, which is a different state from zero.
        </p>
      )}

      {mode === "live" && (
        <p className="banner banner-warn">
          <strong>Live account.</strong> Reaching a live venue takes three
          independent conditions and this view is read-only, but figures here
          are real money if any of it is.
        </p>
      )}

      <dl className="metric-grid">
        <Metric label="Equity" value={money(portfolio?.equity)} />
        <Metric label="Cash" value={money(portfolio?.cash)} />
        <Metric
          label="Daily P&L"
          value={money(portfolio?.daily_pnl)}
          hint="Change in marked equity less net deposits — never a sum of cash flow."
        />
        <Metric
          label="Cumulative P&L"
          value={money(portfolio?.cumulative_pnl)}
        />
        <Metric
          label="Drawdown"
          value={
            portfolio?.drawdown_pct == null
              ? "—"
              : fmtPct(portfolio.drawdown_pct)
          }
          hint="Measured against the high-water mark, not the opening balance."
        />
        <Metric label="Peak equity" value={money(portfolio?.peak_equity)} />
        <Metric label="As of" value={portfolio?.as_of ?? "—"} />
        <Metric label="Mode" value={mode} />
      </dl>

      <h2>Equity</h2>
      {points.length >= 2 ? (
        <EquityChart points={points} />
      ) : (
        <p className="chart-empty">
          A curve needs at least two marks; {points.length} recorded.
        </p>
      )}

      <h2>Positions</h2>
      <div className="card">
        {portfolio && portfolio.positions.length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th className="num">Quantity</th>
                <th className="num">Average entry</th>
              </tr>
            </thead>
            <tbody>
              {portfolio.positions.map((p) => (
                <tr key={p.symbol}>
                  <td>{p.symbol}</td>
                  <td className="num">{p.qty.toFixed(6)}</td>
                  <td className="num">
                    {p.avg_entry_price == null
                      ? "—"
                      : fmtUsd(p.avg_entry_price)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="chart-empty">
            No open positions. These are derived from recorded fills rather
            than read from a snapshot, so an empty table means no fill has been
            recorded — not that a snapshot has gone stale.
          </p>
        )}
      </div>
    </main>
  );
}

/** Null renders as an em dash. Unknown and zero must not look alike. */
function money(value: number | null | undefined): string {
  return value == null ? "—" : fmtUsd(value);
}

function Metric({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="metric" title={hint}>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
