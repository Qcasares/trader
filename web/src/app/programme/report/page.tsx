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
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ApiError, api, fmtUsd, type DailyReport } from "@/lib/api";

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
    return <span className="muted">no data</span>;
  }
  return <>{money ? fmtUsd(value) : value.toLocaleString()}{suffix}</>;
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
  if (!report) return <p className="muted">Loading the report…</p>;

  return (
    <>
      <p className="muted">
        <Link href="/programme">← Programme</Link>
      </p>
      <h1>Daily report</h1>
      <p className="subtitle">
        Assembled from rows. Nothing on this page was written by a model, and no
        figure that does not exist is shown as zero.
      </p>

      {error ? <p className="banner banner-bad">{error}</p> : null}

      <div className="row">
        <label htmlFor="on" className="muted">
          Session
        </label>
        <input
          id="on"
          type="date"
          value={on}
          onChange={(e) => setOn(e.target.value)}
        />
        <span className="muted mono">{report.session}</span>
      </div>

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
          Nothing crossed a threshold today. That is not the same as everything
          being well — the sections below say what is actually known.
        </p>
      )}

      <section className="card">
        <div className="card-head">
          <h2>Portfolio</h2>
        </div>
        {report.portfolio.note ? (
          <p className="muted">{report.portfolio.note}</p>
        ) : null}
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
            <dd>{report.portfolio.as_of ?? "—"}</dd>
          </div>
        </dl>
      </section>

      <section className="card">
        <div className="card-head spread">
          <h2>Programme</h2>
          <span
            className={
              report.programme.severe_findings > 0
                ? "pill pill-warn"
                : "pill pill-mute"
            }
          >
            {report.programme.open_findings} open finding
            {report.programme.open_findings === 1 ? "" : "s"}
          </span>
        </div>
        <dl className="metric-grid">
          {Object.entries(report.programme.by_stage).map(([stage, count]) => (
            <div className="metric" key={stage}>
              <dt>Stage {stage}</dt>
              <dd>{count}</dd>
            </div>
          ))}
        </dl>
        {report.programme.promotions_today.length > 0 ? (
          <p>
            Promoted today:{" "}
            {report.programme.promotions_today
              .map((p) => `stage ${p.to_stage} by ${p.approved_by}`)
              .join(", ")}
          </p>
        ) : (
          <p className="muted">No promotions today.</p>
        )}
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Operations</h2>
        </div>
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
          <p className="muted">No process has ever reported a heartbeat.</p>
        ) : (
          <ul>
            {report.operations.workers.map((worker) => (
              <li key={worker.worker_id}>
                <span className="mono">{worker.worker_id}</span>{" "}
                <span className={worker.stale ? "pill pill-bad" : "pill pill-good"}>
                  {worker.stale ? "stale" : "alive"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Data health</h2>
        </div>
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
            <dd>{report.data_health.latest_session ?? "—"}</dd>
          </div>
          <div className="metric">
            <dt>Days behind</dt>
            <dd>
              <Figure value={report.data_health.sessions_behind} />
            </dd>
          </div>
        </dl>
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Sections this system cannot produce</h2>
        </div>
        <p className="muted">
          Listed rather than dropped. A report showing only what it can measure
          reads as complete, and an operator seeing no execution section would
          reasonably assume execution was clean.
        </p>
        <dl className="assumptions">
          {Object.entries(report.unavailable_sections).map(([name, reason]) => (
            <div className="assumption-row" key={name}>
              <dt className="mono">{name}</dt>
              <dd className="muted">{reason}</dd>
            </div>
          ))}
        </dl>
      </section>
    </>
  );
}
