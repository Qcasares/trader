"use client";

/**
 * One experiment record.
 *
 * The preregistered criteria are rendered **above** the outcome, and that
 * ordering is the whole point of the page. The criteria are fixed before the
 * run and the database refuses to update them afterwards; showing them second
 * would let a reader absorb the result first and then read the bar as though it
 * had been chosen to fit. Reading them in the order they were written is what
 * makes the conclusion mean anything.
 *
 * The conclusion itself is computed, not typed: it is the criteria evaluated
 * against the metrics the engine produced. Nothing on this page was decided by
 * reading prose.
 */

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ApiError, api, type Experiment } from "@/lib/api";
import { Skeleton } from "@/components/Skeleton";

const CONCLUSION_PILL: Record<string, string> = {
  pass: "pill pill-good",
  fail: "pill pill-bad",
  inconclusive: "pill pill-unknown",
};

/** Metrics worth surfacing, with the honesty fields kept next to their figure. */
const HEADLINE: [string, string][] = [
  ["sharpe", "Sharpe"],
  ["sharpe_stderr", "Sharpe standard error"],
  ["sharpe_is_significant", "Significant vs zero"],
  ["cagr", "CAGR"],
  ["volatility", "Volatility"],
  ["max_drawdown", "Max drawdown"],
  ["turnover_annual", "Annual turnover"],
  ["effective_start", "Effective start"],
  ["cost_stress_multiplier", "Cost stress multiplier"],
  ["periods_per_year", "Sessions per year"],
  ["n_sessions", "Sessions"],
];

function show(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "number") return String(Number(value.toFixed(4)));
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export default function ExperimentPage({
  params,
}: {
  params: Promise<{ ref: string }>;
}) {
  const { ref } = use(params);
  const router = useRouter();
  const [experiment, setExperiment] = useState<Experiment | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setExperiment(await api.experiment(ref));
      setError(null);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.isUnauthorized) {
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [ref, router]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) return <p className="banner banner-bad">{error}</p>;
  if (!experiment) return <Skeleton rows={5} label={`Loading ${ref}`} />;

  const outcome = experiment.outcome ?? {};
  const hasOutcome = Object.keys(outcome).length > 0;

  return (
    <>
      <p className="muted">
        <Link href={`/programme/candidates/${experiment.candidate_id}`}>
          ← Candidate
        </Link>
      </p>
      <h1>
        <span className="mono">{experiment.ref}</span> {experiment.kind}
      </h1>
      <p className="subtitle row">
        <span className="muted">{experiment.status}</span>
        {experiment.conclusion ? (
          <span className={CONCLUSION_PILL[experiment.conclusion]}>
            {experiment.conclusion}
          </span>
        ) : null}
      </p>

      <section className="card">
        <div className="card-head">
          <h2>Preregistered criteria</h2>
        </div>
        <p className="muted">
          Fixed when the experiment was registered, before it ran. The database
          refuses to change them afterwards, which is what stops an acceptance
          test being written once the answer is known.
        </p>
        {experiment.preregistered_criteria.length === 0 ? (
          <p className="banner banner-bad">
            None recorded. This should be impossible — the schema requires them.
          </p>
        ) : (
          <ul className="mono">
            {experiment.preregistered_criteria.map((criterion, index) => (
              <li key={`${criterion.metric}-${index}`}>
                {criterion.metric} {criterion.op} {criterion.value}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Outcome</h2>
        </div>
        {!hasOutcome ? (
          <p className="muted">
            Not yet. The engine has not finished, or the run failed —{" "}
            {experiment.error || "no error recorded"}.
          </p>
        ) : (
          <dl className="metric-grid">
            {HEADLINE.filter((entry) => entry[0] in outcome).map(([key, label]) => (
              <div className="metric" key={key}>
                <dt>{label}</dt>
                <dd>{show(outcome[key])}</dd>
              </div>
            ))}
          </dl>
        )}
        {hasOutcome && outcome.sharpe_is_significant === false ? (
          <p className="banner banner-warn">
            This Sharpe is not distinguishable from zero at two standard errors.
            Read it as no evidence of an edge, not as a small one.
          </p>
        ) : null}
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Reproducibility</h2>
        </div>
        <dl className="assumptions">
          <div className="assumption-row">
            <dt>Code commit</dt>
            <dd className="mono">
              {experiment.code_commit || (
                <span className="muted">
                  not recorded — the deployment did not supply one
                </span>
              )}
            </dd>
          </div>
          <div className="assumption-row">
            <dt>Seed</dt>
            <dd className="mono">{show(experiment.seed)}</dd>
          </div>
          <div className="assumption-row">
            <dt>Universe</dt>
            <dd className="mono">{experiment.universe.join(", ") || "—"}</dd>
          </div>
          <div className="assumption-row">
            <dt>Dataset manifest</dt>
            <dd className="mono">{JSON.stringify(experiment.dataset_manifest)}</dd>
          </div>
          <div className="assumption-row">
            <dt>Cost assumptions</dt>
            <dd className="mono">{JSON.stringify(experiment.cost_assumptions)}</dd>
          </div>
          <div className="assumption-row">
            <dt>Engine rows</dt>
            <dd className="mono">
              {experiment.backtest_run_id ? (
                <Link href={`/backtests/${experiment.backtest_run_id}`}>
                  backtest run
                </Link>
              ) : null}
              {experiment.walkforward_run_id ? " walk-forward study" : null}
              {!experiment.backtest_run_id && !experiment.walkforward_run_id
                ? "—"
                : null}
            </dd>
          </div>
        </dl>
      </section>
    </>
  );
}
