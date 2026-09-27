"use client";

/**
 * The daily trading report, §8.11.
 *
 * No model wrote any part of this page. A daily report is the artefact an
 * operator skims fastest and trusts most, which makes it the worst possible
 * place for generated prose.
 *
 * Two rules govern the rendering. A null figure shows as "no data" and never
 * as zero — the most common state of this system is having no marks at all,
 * and a flat line at zero equity would be describing a portfolio that had lost
 * everything. And the sections the system cannot produce are listed with their
 * reason rather than dropped, because a report showing only what it can
 * measure reads as complete.
 *
 * Every figure is formatted by `lib/format.ts`, the same functions /portfolio
 * uses for the same stored values. `drawdown_pct` is a fraction, and this page
 * once appended "%" to it directly — a 5.12% drawdown read "-0.051%" here and
 * "-5.12%" on /portfolio, the report being the one an operator skims fastest.
 *
 * Rebuilt on shadcn primitives. `.metric-grid`, `.assumptions` and `.banner`
 * are kept verbatim — they are tuned, and a report page is exactly the density
 * they were built for. What changed is every place a status used to be a
 * legacy `.pill`: worker liveness now goes through the same `StatusBadge` and
 * `livenessStatus` helper the system page uses, so a stale worker reads the
 * same colour on both pages rather than each page inventing its own amber.
 *
 * And since 2026-09-27 through the same decision as well: a process is alive
 * only while its heartbeat is fresh and says so (`isAlive`,
 * `lib/heartbeat.ts`), so one that shut down cleanly reads "shut down" here as
 * it does on /system, where it used to read "alive" for the minute its
 * shutdown kept its row fresh. The rows are in the order of their ids. The
 * report is a record of its day, not a reading, so nothing on it pulses.
 * Its intro is prose, at the body's 15px (T-11).
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ApiError, api, type DailyReport } from "@/lib/api";
import { fmtAge, fmtPct, fmtUsd } from "@/lib/format";
import { Absent } from "@/components/Absent";
import { SkeletonMetrics } from "@/components/Skeleton";
import { StatusBadge, livenessStatus } from "@/components/StatusBadge";
import { byWorkerId, livenessWord } from "@/lib/heartbeat";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

/**
 * A figure, or the words that say it does not exist. Never a zero stand-in.
 *
 * Takes a formatter rather than a unit suffix. A suffix is how the drawdown
 * came to be a raw fraction with "%" after it; a formatter from
 * `lib/format.ts` is the only thing that knows how its unit is scaled.
 */
function Figure({
  value,
  format = (n) => n.toLocaleString(),
}: {
  value: number | null;
  format?: (value: number) => string;
}) {
  if (value === null || value === undefined) {
    return <Absent kind="no-data" />;
  }
  return <>{format(value)}</>;
}

export default function DailyReportPage() {
  const router = useRouter();
  const [report, setReport] = useState<DailyReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [on, setOn] = useState("");

  const load = useCallback(async () => {
    try {
      setReport(await api.dailyReport(on || undefined));
      setError(null);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.isUnauthorized) {
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [router, on]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error && !report) return <p className="banner banner-bad">{error}</p>;
  if (!report) return <SkeletonMetrics count={6} />;

  return (
    <>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <Link
            href="/programme"
            className="mb-1 block text-sm text-ink-muted hover:text-ink"
          >
            ← Programme
          </Link>
          <h1 className="mb-1">Daily report</h1>
          <p className="intro m-0 text-body text-ink-muted">
            Assembled from rows. Nothing on this page was written by a model,
            and no figure that does not exist is shown as zero.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Label htmlFor="on" className="text-ink-muted">
            Session
          </Label>
          <Input
            id="on"
            type="date"
            value={on}
            onChange={(e) => setOn(e.target.value)}
            className="h-8 w-auto"
          />
          <span className="font-mono text-sm text-ink-muted">
            {report.session}
          </span>
        </div>
      </div>

      {error ? <p className="banner banner-bad">{error}</p> : null}

      {report.required_actions.length > 0 ? (
        <div className="banner banner-warn">
          <p>Required actions</p>
          <ul>
            {report.required_actions.map((action) => (
              <li key={action}>{action}</li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="banner banner-info">
          Nothing crossed a threshold today. That is not the same as
          everything being well — the sections below say what is actually
          known.
        </p>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Portfolio</CardTitle>
          {report.portfolio.note ? (
            <p className="m-0 text-sm text-ink-muted text-pretty">
              {report.portfolio.note}
            </p>
          ) : null}
        </CardHeader>
        <CardContent>
          <dl className="metric-grid">
            <div className="metric">
              <dt>Equity</dt>
              <dd>
                <Figure value={report.portfolio.equity} format={fmtUsd} />
              </dd>
            </div>
            <div className="metric">
              <dt>Cash</dt>
              <dd>
                <Figure value={report.portfolio.cash} format={fmtUsd} />
              </dd>
            </div>
            <div className="metric">
              <dt>Daily P&amp;L</dt>
              <dd>
                <Figure value={report.portfolio.daily_pnl} format={fmtUsd} />
              </dd>
            </div>
            <div className="metric">
              <dt>Cumulative P&amp;L</dt>
              <dd>
                <Figure value={report.portfolio.cumulative_pnl} format={fmtUsd} />
              </dd>
            </div>
            <div className="metric">
              <dt>Drawdown</dt>
              <dd>
                <Figure value={report.portfolio.drawdown_pct} format={fmtPct} />
              </dd>
            </div>
            <div className="metric">
              <dt>As of</dt>
              <dd>
                {report.portfolio.as_of ?? <Absent kind="no-data" />}
              </dd>
            </div>
          </dl>
        </CardContent>
      </Card>

      <Card className="mt-6">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            Programme
            <StatusBadge
              status={
                report.programme.severe_findings > 0
                  ? "blocked"
                  : report.programme.open_findings > 0
                    ? "mute"
                    : "settled"
              }
            >
              {report.programme.open_findings} open finding
              {report.programme.open_findings === 1 ? "" : "s"}
            </StatusBadge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="metric-grid">
            {Object.entries(report.programme.by_stage).map(
              ([stage, count]) => (
                <div className="metric" key={stage}>
                  <dt>Stage {stage}</dt>
                  <dd>{count}</dd>
                </div>
              ),
            )}
          </dl>
          {/* A list of promotions, and in its place the word that there were
              none: data, so 13px set here rather than the body's 15px, which
              since OD-8 is for prose. The two share a size, as they share a
              place. */}
          {report.programme.promotions_today.length > 0 ? (
            <p className="m-0 text-base">
              Promoted today:{" "}
              {report.programme.promotions_today
                .map((p) => `stage ${p.to_stage} by ${p.approved_by}`)
                .join(", ")}
            </p>
          ) : (
            <p className="m-0 text-base text-ink-muted">No promotions today.</p>
          )}
        </CardContent>
      </Card>

      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Operations</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="metric-grid">
            <div className="metric">
              <dt>Decisions</dt>
              <dd>{report.operations.decisions}</dd>
            </div>
            <div className="metric">
              <dt>Orders submitted</dt>
              <dd>{report.operations.orders_submitted}</dd>
            </div>
            <div className="metric">
              <dt>Shadow sessions</dt>
              <dd>{report.operations.shadow_sessions}</dd>
            </div>
            <div className="metric">
              <dt>Shadow failures</dt>
              <dd>{report.operations.shadow_failures}</dd>
            </div>
          </dl>
          {report.operations.workers.length === 0 ? (
            <p className="m-0 text-ink-muted">
              No process has ever reported a heartbeat.
            </p>
          ) : (
            <Table label="Workers">
              <TableHeader>
                <TableRow>
                  <TableHead>Worker</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Age</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {byWorkerId(report.operations.workers).map((worker) => (
                  <TableRow key={worker.worker_id}>
                    <TableCell className="font-mono">
                      {worker.worker_id}
                    </TableCell>
                    <TableCell>
                      {/* No `pulse`: a report is an artefact of its day, not a live reading. */}
                      <StatusBadge status={livenessStatus(worker)}>
                        {livenessWord(worker)}
                      </StatusBadge>
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {fmtAge(worker.age_seconds)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Data health</CardTitle>
        </CardHeader>
        <CardContent>
          {report.data_health.note ? (
            <p className="banner banner-warn">{report.data_health.note}</p>
          ) : null}
          <dl className="metric-grid">
            <div className="metric">
              <dt>Symbols</dt>
              <dd>{report.data_health.symbols}</dd>
            </div>
            <div className="metric">
              <dt>Bars</dt>
              <dd>{report.data_health.rows.toLocaleString()}</dd>
            </div>
            <div className="metric">
              <dt>Latest session</dt>
              <dd>
                {report.data_health.latest_session ?? (
                  <Absent kind="no-data" reason="nothing has been ingested" />
                )}
              </dd>
            </div>
            <div className="metric">
              <dt>Days behind</dt>
              <dd>
                <Figure value={report.data_health.sessions_behind} />
              </dd>
            </div>
          </dl>
        </CardContent>
      </Card>

      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Sections this system cannot produce</CardTitle>
          <p className="m-0 text-sm text-ink-muted text-pretty">
            Listed rather than dropped. A report showing only what it can
            measure reads as complete, and an operator seeing no execution
            section would reasonably assume execution was clean.
          </p>
        </CardHeader>
        <CardContent>
          <dl className="assumptions">
            {Object.entries(report.unavailable_sections).map(
              ([name, reason]) => (
                <div className="assumption-row" key={name}>
                  <dt className="mono">{name}</dt>
                  <dd className="text-ink-muted">{reason}</dd>
                </div>
              ),
            )}
          </dl>
        </CardContent>
      </Card>
    </>
  );
}
