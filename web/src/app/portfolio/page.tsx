"use client";

/**
 * Portfolio.
 *
 * The live account: equity, P&L, drawdown against the high-water mark, and the
 * positions implied by recorded fills.
 *
 * Three rules govern this page, all learned elsewhere in the system:
 *
 * 1. **Unknown is not zero.** Every money field arrives nullable, and a null is
 *    rendered as an absence — never as $0.00. A flat line at zero is exactly
 *    what a broken mark writer would also draw, so the two states must not look
 *    the same.
 *
 * 2. **Paper and live are never mixed.** Separate accounts, separate curves.
 *    The mode is on screen at all times rather than implied by a setting
 *    somewhere else — and the mode on screen is the one the API *answered*
 *    for, not the one the page asked about. Switching used to relabel the
 *    figures already on screen: click "live" and the paper account's equity
 *    sat under the "Live account" banner with "Mode: live" beside it until the
 *    live request answered, indefinitely if it failed, and a slow paper answer
 *    arriving after the click could overwrite the live one. Now a switch
 *    clears the figures to the loading state, an answer for a mode no longer
 *    selected is dropped, and an answer for a different mode than the one
 *    asked for is refused rather than shown.
 *
 * 3. **A figure is never shown as current when it is not.** The page polls
 *    every fifteen seconds. When a poll fails, the last good reading stays on
 *    screen — it is still the best information there is — but marked stale,
 *    with the time it was read and the time the refresh failed, instead of an
 *    error banner above figures that go on looking live. The kill switch's
 *    rule, applied to a read: a view that cannot determine the answer must
 *    not keep presenting its last one as the answer.
 *
 * Three things changed in the shadcn rebuild, each for a reason worth keeping:
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
 *
 * Since the owner's decision of 2026-09-27 (OD-7) the page is an asymmetric
 * grid rather than a stack: the account's figures in the main column and the
 * positions the fills imply beside them, which together are the account now,
 * then the equity curve across the full width beneath — the account over
 * time, and a time series wants the room. The banners stay above the grid,
 * because each is about everything in it. Nothing here rises into place
 * (OD-6): the positions are a handful of rows, and switching account clears
 * them to the loading state by design, so an entrance would replay on every
 * switch for a list that gains nothing from one. Its prose is the body's 15px
 * (OD-8, T-11) — the intro, the two sentences under the figures, the empty
 * positions' explanation, the banners — and the figures, the positions and
 * the time a reading arrived keep their smaller steps.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Absent } from "@/components/Absent";
import { EquityChart } from "@/components/EquityChart";
import { DataTable } from "@/components/DataTable";
import { SkeletonMetrics } from "@/components/Skeleton";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  ApiError,
  api,
  type EquityPoint,
  type Portfolio,
  type PortfolioMark,
  type PortfolioMode,
} from "@/lib/api";
import { fmtInstant, fmtPct, fmtUsd } from "@/lib/format";

const MODES: PortfolioMode[] = ["paper", "live"];

/** How often the page re-reads the account. */
const POLL_MS = 15000;

/** One answer from the API, kept whole so its parts cannot come from two reads. */
interface Reading {
  /** The account the API answered for — what the page labels the figures with. */
  mode: PortfolioMode;
  portfolio: Portfolio;
  marks: PortfolioMark[];
  /** When the answer arrived. The figures are current as of this, not as of now. */
  readAt: string;
}

/** Refreshes that have not produced a reading, since the first of them. */
interface Failure {
  message: string;
  since: string;
}

export default function PortfolioPage() {
  const router = useRouter();
  const [mode, setMode] = useState<PortfolioMode>("paper");
  const [reading, setReading] = useState<Reading | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);

  useEffect(() => {
    // False once this mode is no longer the one selected. A request already in
    // flight when the operator switches still resolves, and its answer — for
    // the account they just switched away from — must land nowhere.
    let selected = true;

    const refresh = async () => {
      try {
        const [next, history] = await Promise.all([
          api.portfolio(mode),
          api.portfolioHistory(mode),
        ]);
        if (!selected) return;
        if (next.mode !== mode || history.mode !== mode) {
          throw new Error(
            `Asked for the ${mode} account and the API answered for ` +
              `${next.mode === mode ? history.mode : next.mode}. Nothing ` +
              "from that answer is shown.",
          );
        }
        setReading({
          mode: next.mode,
          portfolio: next,
          marks: history.marks,
          readAt: new Date().toISOString(),
        });
        setFailure(null);
      } catch (err: unknown) {
        if (!selected) return;
        if (err instanceof ApiError && err.isUnauthorized) {
          router.push("/login");
          return;
        }
        const message = err instanceof Error ? err.message : String(err);
        // Kept from the first failure of a run of them, so the banner says how
        // long the figures have been stale — and does not change, and so is
        // not re-announced, on every failed poll.
        setFailure((previous) =>
          previous !== null && previous.message === message
            ? previous
            : { message, since: new Date().toISOString() },
        );
      }
    };

    void refresh();
    const timer = setInterval(refresh, POLL_MS);
    return () => {
      selected = false;
      clearInterval(timer);
    };
  }, [mode, router]);

  const choose = (next: PortfolioMode) => {
    if (next === mode) return;
    // Cleared in the same render that changes the label, so there is no frame
    // in which one account's figures sit under the other's name.
    setMode(next);
    setReading(null);
    setFailure(null);
  };

  // Belt and braces: a reading for any account but the selected one is never
  // rendered, whatever path put it in state.
  const shown = reading !== null && reading.mode === mode ? reading : null;
  const stale = shown !== null && failure !== null;

  // A mark has the same shape as an equity point, so the backtest's chart
  // draws the live curve with no second component and no translation layer.
  const points: EquityPoint[] = (shown?.marks ?? []).map((m) => ({
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
          <p className="intro m-0 text-body text-ink-muted">
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
              onClick={() => choose(m)}
            >
              {m}
            </Button>
          ))}
        </div>
      </div>

      {failure && !shown ? (
        <p className="banner banner-bad" role="alert">
          The {mode} account could not be read: {sentence(failure.message)}
        </p>
      ) : null}

      {stale ? (
        <p className="banner banner-warn" role="status" data-stale="true">
          <strong>Stale.</strong> Refreshing has failed since{" "}
          {fmtInstant(failure.since)}: {sentence(failure.message)} The figures
          below are the {shown.mode} account as read at{" "}
          {fmtInstant(shown.readAt)}, and may no longer be current.
        </p>
      ) : null}

      {mode === "live" && (
        <p className="banner banner-warn">
          <strong>Live account.</strong> Reaching a live venue takes three
          independent conditions and this view is read-only, but figures here
          are real money if any of it is.
        </p>
      )}

      {shown === null ? (
        // Loading, and nothing else: the previous account's figures are gone
        // and this one's have not arrived. A failed first read has said so
        // above and leaves nothing here to mistake for figures.
        failure ? null : <SkeletonMetrics count={8} />
      ) : (
        <>
          {shown.portfolio.note && (
            <p className="banner banner-info">
              <strong>No marks recorded yet.</strong> The equity curve begins
              once the worker has run an end-of-day mark. Nothing is wrong —
              there is simply nothing to report, which is a different state
              from zero.
            </p>
          )}

          <div className="summary-grid">
            {/*
              Main: the account's figures. Side: the positions the recorded
              fills imply. Together they are the account now; the curve
              beneath, full width because a time series wants the room, is
              the account over time. Source order is reading order, so a
              phone shows the figures first.
            */}
            <div className="summary-main">
              <Card>
                <CardContent>
                  <p className="mt-0 mb-2 flex flex-wrap items-center gap-2 text-sm text-ink-muted">
                    {stale ? (
                      <StatusBadge status="unknown">stale</StatusBadge>
                    ) : null}
                    <span>
                      {stale ? "Last read" : "Read"} at {fmtInstant(shown.readAt)}
                    </span>
                  </p>
                  <dl className="metric-grid">
                    <Metric label="Equity" value={money(shown.portfolio.equity)} />
                    <Metric label="Cash" value={money(shown.portfolio.cash)} />
                    <Metric
                      label="Daily P&L"
                      value={money(shown.portfolio.daily_pnl)}
                    />
                    <Metric
                      label="Cumulative P&L"
                      value={money(shown.portfolio.cumulative_pnl)}
                    />
                    <Metric
                      label="Drawdown"
                      value={
                        shown.portfolio.drawdown_pct == null ? (
                          <Absent kind="no-data" />
                        ) : (
                          fmtPct(shown.portfolio.drawdown_pct)
                        )
                      }
                    />
                    <Metric
                      label="Peak equity"
                      value={money(shown.portfolio.peak_equity)}
                    />
                    <Metric
                      label="As of"
                      value={shown.portfolio.as_of ?? <Absent kind="no-data" />}
                    />
                    <Metric label="Mode" value={shown.mode} />
                  </dl>
                  {/*
                    Said out loud rather than hidden in a `title`. Both sentences
                    are corrections of the obvious wrong reading of the figure
                    above them, which makes them the last thing that should need
                    a hover to find.
                  */}
                  <p className="mt-3 mb-0 max-w-prose text-body text-ink-muted text-pretty">
                    P&amp;L is the change in marked equity less net deposits, never
                    a sum of cash flow. Drawdown is measured against the high-water
                    mark, not the opening balance.
                  </p>
                </CardContent>
              </Card>
            </div>

            <div className="summary-side">
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    Positions
                    {stale ? (
                      <StatusBadge status="unknown">stale</StatusBadge>
                    ) : null}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {shown.portfolio.positions.length > 0 ? (
                    <DataTable
                      label="Positions"
                      rows={shown.portfolio.positions}
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
                          // The head may wrap: in the side column its two words
                          // on one line were what pushed the table past it.
                          headerClassName: "text-right whitespace-normal",
                          className: "text-right font-mono tabular-nums",
                          // Words rather than a dash: beside a column of numbers
                          // a bare dash reads as a minus sign, which is the one
                          // thing an absent price must never be mistaken for.
                          cell: (p) =>
                            p.avg_entry_price == null ? (
                              <Absent kind="no-data" />
                            ) : (
                              fmtUsd(p.avg_entry_price)
                            ),
                        },
                      ]}
                    />
                  ) : (
                    // A plain sentence, not `.chart-empty`: that class's 48px
                    // padding is for a placeholder the width of a chart, and in
                    // this column it left the sentence 12 characters to a line.
                    <p className="m-0 max-w-prose text-body text-ink-muted text-pretty">
                      No open positions. These are derived from recorded fills
                      rather than read from a snapshot, so an empty table means no
                      fill has been recorded — not that a snapshot has gone stale.
                    </p>
                  )}
                </CardContent>
              </Card>
            </div>

            <div className="summary-wide">
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    Equity
                    {stale ? (
                      <StatusBadge status="unknown">stale</StatusBadge>
                    ) : null}
                  </CardTitle>
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
            </div>
          </div>
        </>
      )}
    </>
  );
}

/** An error message ended as a sentence, so the text after it reads as one. */
function sentence(message: string): string {
  const trimmed = message.trim();
  return /[.!?]$/.test(trimmed) ? trimmed : `${trimmed}.`;
}

/** An absent amount says so. Unknown and zero must not look alike. */
function money(value: number | null | undefined): React.ReactNode {
  return value == null ? <Absent kind="no-data" /> : fmtUsd(value);
}

function Metric({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="metric">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
