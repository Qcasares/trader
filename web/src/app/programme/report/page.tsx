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
 * Rebuilt on shadcn primitives. `.metric-grid`, `.assumptions` and `.banner`
 * are kept verbatim — they are tuned, and a report page is exactly the density
 * they were built for. What changed is every place a status used to be a
 * legacy `.pill`: worker liveness now goes through the same `StatusBadge` and
 * `livenessStatus` helper the system page uses, so a stale worker reads the
 * same colour on both pages rather than each page inventing its own amber.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ApiError, api, fmtUsd, type DailyReport } from "@/lib/api";
import { SkeletonMetrics } from "@/components/Skeleton";
import { StatusBadge, livenessStatus } from "@/components/StatusBadge";
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

/** A figure, or the words that say it does not exist. Never a zero stand-in. */
function Figure({
  value,
  money = false,
  suffix = "",
}: {
  value: number | null;
  money?: boolean;
  suffix?: string;
}) {
  if (value === null || value === undefined) {
    return <span className="no-data">no data</span>;
  }
  return (
    <>
      {money ? fmtUsd(value) : value.toLocaleString()}
      {suffix}
    </>
  );
}

/** Heartbeat age, in the largest unit that still reads as a number. */
/**
 * A heartbeat age.
 *
 * The unreachable branch returns the page's own absence marker rather than a
 * bare dash: this renders in a right-aligned column, where a dash sits in the
 * minus-sign position. `age_seconds` is non-nullable in the API contract so the
 * branch should never fire, which is exactly why it must not be the one place
 * that quietly disagrees with the convention if it ever does.
 */
function fmtAge(seconds: number): string {
  if (!Number.isFinite(seconds)) return "no data";
  if (seconds < 90) return `${Math.round(seconds)}s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)}m`;
  return `${Math.round(seconds / 3600)}h`;
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
          <p className="m-0 text-base text-ink-muted text-pretty">
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
                <Figure value={report.portfolio.equity} money />
              </dd>
            </div>
            <div className="metric">
              <dt>Cash</dt>
              <dd>
                <Figure value={report.portfolio.cash} money />
              </dd>
            </div>
            <div className="metric">
              <dt>Daily P&amp;L</dt>
              <dd>
                <Figure value={report.portfolio.daily_pnl} money />
              </dd>
            </div>
            <div className="metric">
              <dt>Cumulative P&amp;L</dt>
              <dd>
                <Figure value={report.portfolio.cumulative_pnl} money />
              </dd>
            </div>
            <div className="metric">
              <dt>Drawdown</dt>
              <dd>
                <Figure value={report.portfolio.drawdown_pct} suffix="%" />
              </dd>
            </div>
            <div className="metric">
              <dt>As of</dt>
              <dd>
                {report.portfolio.as_of ?? (
                  <span className="no-data">no data</span>
                )}
              </dd>
            </div>
          </dl>
        </CardContent>
      </Card>

      <Card className="mt-3">
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
          {report.programme.promotions_today.length > 0 ? (
            <p className="m-0">
              Promoted today:{" "}
              {report.programme.promotions_today
                .map((p) => `stage ${p.to_stage} by ${p.approved_by}`)
                .join(", ")}
            </p>
          ) : (
            <p className="m-0 text-ink-muted">No promotions today.</p>
          )}
        </CardContent>
      </Card>

      <Card className="mt-3">
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
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Worker</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Age</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {report.operations.workers.map((worker) => (
                  <TableRow key={worker.worker_id}>
                    <TableCell className="font-mono">
                      {worker.worker_id}
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={livenessStatus(worker.stale)}>
                        {worker.stale ? "stale" : "alive"}
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

      <Card className="mt-3">
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
                  <span className="no-data">none ingested</span>
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

      <Card className="mt-3">
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
