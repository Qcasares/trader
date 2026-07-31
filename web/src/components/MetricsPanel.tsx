"use client";

/**
 * MetricsPanel.tsx
 * ----------------
 * Performance figures, rendered with the caveats attached rather than beside.
 *
 * Three deliberate choices:
 *
 * 1. Sharpe is always shown as `value ± stderr`, never bare. Five years of
 *    daily data gives a standard error around 0.45, so a Sharpe of 0.5 is
 *    indistinguishable from zero — and a number displayed alone will be read
 *    as a fact.
 * 2. A Sharpe inside two standard errors of zero gets an explicit "not
 *    significant" badge, not a subtle colour change.
 * 3. The cost assumption and the effective start date sit in the same panel as
 *    the returns. A performance figure without them is not a performance
 *    figure.
 */

import type { BacktestMetrics, BacktestRun } from "@/lib/api";
import { fmtNum, fmtPct, fmtUsd } from "@/lib/api";

interface Props {
  run: BacktestRun;
  metrics: BacktestMetrics;
}

export function MetricsPanel({ run, metrics }: Props) {
  const truncated =
    metrics.effective_start !== null &&
    metrics.start !== null &&
    metrics.effective_start > metrics.start;

  return (
    <section className="metrics">
      {run.data_source === "synthetic" && (
        <p className="banner banner-warn">
          <strong>Synthetic data.</strong> These prices were generated, not
          observed. Nothing here says anything about how this strategy would
          have performed.
        </p>
      )}

      {!metrics.sharpe_is_significant && (
        <p className="banner banner-warn">
          <strong>Not statistically significant.</strong> The Sharpe estimate
          ({fmtNum(metrics.sharpe)}) is within two standard errors of zero
          (± {fmtNum(metrics.sharpe_stderr)}). This is not evidence the strategy
          works.
        </p>
      )}

      {truncated && (
        <p className="banner banner-info">
          <strong>Universe incomplete before {metrics.effective_start}.</strong>{" "}
          The run starts at {metrics.start}, but not every instrument existed
          (or had enough history for the signal) until later. Figures spanning
          the whole window describe a smaller strategy than the one named.
        </p>
      )}

      <dl className="metric-grid">
        <Metric label="Total return" value={fmtPct(metrics.total_return)} />
        <Metric label="CAGR" value={fmtPct(metrics.cagr)} />
        <Metric label="Volatility" value={fmtPct(metrics.volatility)} />
        <Metric
          label="Sharpe"
          value={`${fmtNum(metrics.sharpe)} ± ${fmtNum(metrics.sharpe_stderr)}`}
          badge={metrics.sharpe_is_significant ? undefined : "not significant"}
        />
        <Metric label="Sortino" value={fmtNum(metrics.sortino)} />
        <Metric label="Max drawdown" value={fmtPct(metrics.max_drawdown)} />
        <Metric label="Calmar" value={fmtNum(metrics.calmar, 2)} />
        <Metric label="Exposure" value={fmtPct(metrics.exposure, 1)} />
        <Metric label="Rebalances" value={String(metrics.n_rebalances)} />
        <Metric label="Fills" value={String(metrics.n_fills)} />
        <Metric
          label="Turnover"
          value={`${fmtNum(metrics.turnover_annual, 2)}×/yr`}
        />
        <Metric label="Final equity" value={fmtUsd(metrics.final_equity)} />
      </dl>

      <dl className="assumptions">
        <h3>Assumptions this result depends on</h3>
        <Row label="Data source" value={run.data_source} />
        <Row
          label="Requested window"
          value={`${run.start_session} → ${run.end_session}`}
        />
        <Row
          label="Effective start"
          value={metrics.effective_start ?? "—"}
          hint="First session the whole universe was tradeable, warm-up included."
        />
        <Row
          label="Slippage"
          value={`${run.cost_model.slippage_bps ?? 0} bps`}
        />
        <Row
          label="Cost stress"
          value={`${metrics.cost_stress_multiplier}×`}
          hint="Re-run at 3× and check the sign does not flip before trusting this."
        />
        <Row
          label="Decision lag"
          value={`${run.decision_lag_sessions} session(s)`}
          hint="Decide on the close, execute at the next open — as live would."
        />
        <Row label="Engine" value={run.engine_version} />
      </dl>
    </section>
  );
}

function Metric({
  label,
  value,
  badge,
}: {
  label: string;
  value: string;
  badge?: string;
}) {
  return (
    <div className="metric">
      <dt>{label}</dt>
      <dd>
        {value}
        {badge && <span className="badge">{badge}</span>}
      </dd>
    </div>
  );
}

function Row({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="assumption-row">
      <dt>{label}</dt>
      <dd>
        {value}
        {hint && <span className="hint">{hint}</span>}
      </dd>
    </div>
  );
}
