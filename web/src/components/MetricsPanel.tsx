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
import { fmtNum, fmtPct, fmtUsd } from "@/lib/format";
import { Absent } from "@/components/Absent";
import { StatusBadge } from "@/components/StatusBadge";

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

      {/* The engine's verdict, and only when it gave one: a null
          `sharpe_is_significant` is no verdict, not a "false". */}
      {metrics.sharpe_is_significant === false &&
        metrics.sharpe != null &&
        metrics.sharpe_stderr != null && (
          <p className="banner banner-warn">
            <strong>Not statistically significant.</strong> The Sharpe estimate
            ({fmtNum(metrics.sharpe)}) is within two standard errors of zero
            (± {fmtNum(metrics.sharpe_stderr)}). This is not evidence the
            strategy works.
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
        <Metric label="Total return" value={figure(metrics.total_return, fmtPct)} />
        <Metric label="CAGR" value={figure(metrics.cagr, fmtPct)} />
        <Metric label="Volatility" value={figure(metrics.volatility, fmtPct)} />
        <Metric
          label="Sharpe"
          value={
            // Never one without the other (CLAUDE.md): a Sharpe whose standard
            // error was not recorded is not shown bare.
            metrics.sharpe == null || metrics.sharpe_stderr == null ? (
              <Absent kind="not-measured" />
            ) : (
              `${fmtNum(metrics.sharpe)} ± ${fmtNum(metrics.sharpe_stderr)}`
            )
          }
          badge={
            metrics.sharpe_is_significant === false ? "not significant" : undefined
          }
        />
        <Metric label="Sortino" value={figure(metrics.sortino, fmtNum)} />
        <Metric label="Max drawdown" value={figure(metrics.max_drawdown, fmtPct)} />
        <Metric label="Calmar" value={figure(metrics.calmar, (v) => fmtNum(v, 2))} />
        <Metric label="Exposure" value={figure(metrics.exposure, (v) => fmtPct(v, 1))} />
        <Metric label="Rebalances" value={figure(metrics.n_rebalances, String)} />
        <Metric label="Fills" value={figure(metrics.n_fills, String)} />
        <Metric
          label="Turnover"
          value={figure(metrics.turnover_annual, (v) => `${fmtNum(v, 2)}×/yr`)}
        />
        <Metric label="Final equity" value={figure(metrics.final_equity, fmtUsd)} />
      </dl>

      {/* Above the list, not in it: a `dl` holds only its term and definition
          groups, and a heading inside one is a structure assistive technology
          cannot read as a list (axe: definition-list, WCAG 1.3.1). */}
      <h3>Assumptions this result depends on</h3>
      <dl className="assumptions">
        <Row label="Data source" value={run.data_source} />
        <Row
          label="Requested window"
          value={`${run.start_session} → ${run.end_session}`}
        />
        <Row
          label="Effective start"
          value={metrics.effective_start ?? <Absent kind="not-measured" />}
          hint="First session the whole universe was tradeable, warm-up included."
        />
        <Row
          label="Slippage"
          value={
            // Not `?? 0`. The runs the programme queued before a run's cost
            // model was stored whole record only a stress multiplier, and for
            // those this cell used to read "0 bps" — a frictionless fill —
            // while the worker applied its own default. A cost assumption the
            // run did not record is missing, not zero.
            typeof run.cost_model.slippage_bps === "number" ? (
              `${run.cost_model.slippage_bps} bps`
            ) : (
              <Absent
                kind="missing"
                reason="not recorded on this run; the engine applied its own default, not zero"
              />
            )
          }
        />
        <Row
          label="Cost stress"
          value={
            // Every result carries its multiplier (CLAUDE.md); one that does
            // not is missing it, and 1× would be the cheapest guess going.
            metrics.cost_stress_multiplier == null ? (
              <Absent kind="missing" reason="not recorded with these figures" />
            ) : (
              `${metrics.cost_stress_multiplier}×`
            )
          }
          hint="Re-run at 3× and check the sign does not flip before trusting this."
        />
        <Row
          label="Annualised on"
          value={
            // Not `?? 252`: a count nobody recorded is not the NYSE year, and
            // for a venue that never closes, 252 moves volatility and the
            // Sharpe by about a fifth.
            metrics.periods_per_year == null ? (
              <Absent kind="not-measured" />
            ) : (
              `${metrics.periods_per_year} sessions/year`
            )
          }
          hint="252 is the NYSE year. A venue that never closes has 365, and annualising it on 252 understates volatility by about 20%."
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

/**
 * A figure, or the words for one that was never computed. The API sends null
 * for a figure the run did not record, where it used to send a zero or 252
 * (`BacktestMetrics` in `lib/api.ts`), so every figure here passes through
 * this rather than straight into a formatter.
 */
function figure(value: number | null, format: (value: number) => string) {
  return value == null ? <Absent kind="not-measured" /> : format(value);
}

function Metric({
  label,
  value,
  badge,
}: {
  label: string;
  value: React.ReactNode;
  badge?: string;
}) {
  return (
    <div className="metric">
      <dt>{label}</dt>
      <dd>
        {value}
        {/* The one chip, as the backtests list draws the same caveat. It was
            the legacy `.badge`: the same amber in a second type system. */}
        {badge && (
          <StatusBadge status="unknown" className="mt-1 flex">
            {badge}
          </StatusBadge>
        )}
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
  value: React.ReactNode;
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
