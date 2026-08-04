"use client";

/**
 * Portfolio.
 *
 * The live account: equity, P&L, drawdown against the high-water mark, and the
 * positions implied by recorded fills.
 *
 * Two rules govern this page, both learned elsewhere in the system:
 *
 * 1. **Unknown is not zero.** Every money field arrives nullable, and a null is
 *    rendered as an absence — never as $0.00. A flat line at zero is exactly
 *    what a broken mark writer would also draw, so the two states must not look
 *    the same.
 *
 * 2. **Paper and live are never mixed.** Separate accounts, separate curves.
 *    The mode is on screen at all times rather than implied by a setting
 *    somewhere else.
 *
 * Three things changed in the rebuild, each for a reason worth keeping:
 *
 * - **The page no longer renders its own `<main>`.** `AppShell` provides one,
 *   and this was the only page that also brought its own — two `main` landmarks
 *   in the accessibility tree, where the whole point of the landmark is that
 *   there is exactly one.
 *
 * - **The two honesty hints are visible prose rather than `title` tooltips.**
 *   "P&L is a change in marked equity, never a sum of cash flow" is precisely
 *   the kind of statement this system exists to make out loud; hiding it behind
 *   a hover that no keyboard reaches made it decoration. A Radix tooltip would
 *   have been accessible but would have added a tab stop per metric to a grid
 *   of eight.
 *
 * - **`.metric-grid` is kept, not reimplemented.** It is dense, tuned, and
 *   already correct. Rebuilding it out of utilities would have produced a
 *   parallel lookalike and two places to change the same thing.
 */

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { EquityChart } from "@/components/EquityChart";
import { DataTable } from "@/components/DataTable";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
    <>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="mb-1">Portfolio</h1>
          <p className="m-0 text-base text-ink-muted">
            The account, not a backtest. P&amp;L is a change in marked equity.
          </p>
        </div>
        {/*
          `aria-pressed` rather than a tab list: these are two buttons that
          change which account is being read, not two panels of one document.
          A screen reader announces the current one as pressed, which the old
          colour-only distinction did not convey at all.
        */}
        <div className="flex gap-1.5" role="group" aria-label="Account mode">
          {MODES.map((m) => (
            <Button
              key={m}
              size="sm"
              variant={m === mode ? "default" : "outline"}
              aria-pressed={m === mode}
              onClick={() => setMode(m)}
            >
              {m}
            </Button>
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

      <Card>
        <CardContent>
          <dl className="metric-grid">
            <Metric label="Equity" value={money(portfolio?.equity)} />
            <Metric label="Cash" value={money(portfolio?.cash)} />
            <Metric label="Daily P&L" value={money(portfolio?.daily_pnl)} />
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
            />
            <Metric label="Peak equity" value={money(portfolio?.peak_equity)} />
            <Metric label="As of" value={portfolio?.as_of ?? "—"} />
            <Metric label="Mode" value={mode} />
          </dl>
          {/*
            Said out loud rather than hidden in a `title`. Both sentences are
            corrections of the obvious wrong reading of the figure above them,
            which makes them the last thing that should need a hover to find.
          */}
          <p className="mt-3 mb-0 text-sm text-ink-muted text-pretty">
            P&amp;L is the change in marked equity less net deposits, never a
            sum of cash flow. Drawdown is measured against the high-water mark,
            not the opening balance.
          </p>
        </CardContent>
      </Card>

      <Card className="mt-3">
        <CardHeader>
          <CardTitle>Equity</CardTitle>
        </CardHeader>
        <CardContent>
          {points.length >= 2 ? (
            <EquityChart points={points} />
          ) : (
            <p className="chart-empty">
              A curve needs at least two marks; {points.length} recorded.
            </p>
          )}
        </CardContent>
      </Card>

      <Card className="mt-3">
        <CardHeader>
          <CardTitle>Positions</CardTitle>
        </CardHeader>
        <CardContent>
          {portfolio && portfolio.positions.length > 0 ? (
            <DataTable
              rows={portfolio.positions}
              getRowId={(p) => p.symbol}
              initialSort={[{ id: "symbol", desc: false }]}
              columns={[
                {
                  id: "symbol",
                  header: "Symbol",
                  sortable: true,
                  sortValue: (p) => p.symbol,
                  className: "font-mono",
                  cell: (p) => p.symbol,
                },
                {
                  id: "qty",
                  header: "Quantity",
                  sortable: true,
                  sortValue: (p) => p.qty,
                  headerClassName: "text-right",
                  className: "text-right font-mono tabular-nums",
                  cell: (p) => p.qty.toFixed(6),
                },
                {
                  id: "entry",
                  header: "Average entry",
                  sortable: true,
                  sortValue: (p) => p.avg_entry_price ?? undefined,
                  headerClassName: "text-right",
                  className: "text-right font-mono tabular-nums",
                  // `no-data` rather than an em dash, because this column is
                  // right-aligned: beside a column of numbers a bare dash reads
                  // as a minus sign, which is the one thing an absent price
                  // must never be mistaken for. The metric grid above is
                  // left-aligned, where a dash is unambiguous, and keeps it.
                  cell: (p) =>
                    p.avg_entry_price == null ? (
                      <span className="no-data">no data</span>
                    ) : (
                      fmtUsd(p.avg_entry_price)
                    ),
                },
              ]}
            />
          ) : (
            <p className="chart-empty">
              No open positions. These are derived from recorded fills rather
              than read from a snapshot, so an empty table means no fill has
              been recorded — not that a snapshot has gone stale.
            </p>
          )}
        </CardContent>
      </Card>
    </>
  );
}

/** Null renders as an em dash. Unknown and zero must not look alike. */
function money(value: number | null | undefined): string {
  return value == null ? "—" : fmtUsd(value);
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
