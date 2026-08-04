"use client";

/**
 * page.tsx (/)
 * ------------
 * Strategy list and the run form.
 *
 * The parameter form is generated from each strategy's JSON Schema, which the
 * API derives from the strategy's own pydantic model. Adding a parameter in
 * Python makes it appear here with no frontend change — and, more importantly,
 * the same declaration that renders the field is the one that validates it, so
 * the form cannot drift from what the engine accepts.
 */

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ApiError,
  api,
  type JsonSchemaProperty,
  type StrategyDescriptor,
} from "@/lib/api";
import { Skeleton } from "@/components/Skeleton";

export default function StrategiesPage() {
  const router = useRouter();
  const [strategies, setStrategies] = useState<StrategyDescriptor[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .strategies()
      .then((list) => {
        setStrategies(list);
        if (list.length > 0) setSelected(list[0].name);
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.isUnauthorized) {
          router.push("/login");
          return;
        }
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => setLoading(false));
  }, [router]);

  if (loading) return <Skeleton rows={5} label="Loading strategies" />;
  if (error) return <p className="banner banner-bad">{error}</p>;

  const active = strategies.find((s) => s.name === selected) ?? null;

  return (
    <>
      <h1>Strategies</h1>
      <p className="subtitle">
        Deterministic, backtestable rules. Parameters are tunable here and take
        effect on the next run — no redeploy.
      </p>

      {strategies.map((strategy) => (
        <div key={strategy.name} className="card">
          <div className="card-head">
            <strong>{strategy.name}</strong>
            <span className="pill pill-mute">v{strategy.version}</span>
            <BacktestCount count={strategy.backtest_count} />
            <button
              style={{ marginLeft: "auto" }}
              onClick={() =>
                setSelected(selected === strategy.name ? null : strategy.name)
              }
            >
              {selected === strategy.name ? "Hide" : "Configure & run"}
            </button>
          </div>
          <p className="muted" style={{ margin: "6px 0" }}>
            {strategy.description}
          </p>
          <p className="mono muted" style={{ fontSize: 12 }}>
            {strategy.universe.join(" · ")} — warm-up{" "}
            {strategy.warmup_sessions} sessions
          </p>
          {strategy.source && (
            <p className="muted" style={{ fontSize: 12 }}>
              Source: {strategy.source}
            </p>
          )}
          {selected === strategy.name && active && <RunForm strategy={active} />}
        </div>
      ))}
    </>
  );
}

/**
 * A visible count of how many times this strategy has been backtested.
 *
 * The tune-rerun-look-at-Sharpe loop is how people fool themselves. Showing
 * the roll count makes the multiple-testing problem impossible to ignore.
 */
function BacktestCount({ count }: { count: number }) {
  if (count === 0) return <span className="pill pill-mute">never run</span>;
  const heavy = count >= 20;
  return (
    <span className={`pill ${heavy ? "pill-warn" : "pill-mute"}`}>
      {count} backtest{count === 1 ? "" : "s"} run
      {heavy ? " — mind the multiple testing" : ""}
    </span>
  );
}

function RunForm({ strategy }: { strategy: StrategyDescriptor }) {
  const router = useRouter();
  const [params, setParams] = useState<Record<string, unknown>>(strategy.params);
  const [start, setStart] = useState("1999-01-01");
  const [end, setEnd] = useState(new Date().toISOString().slice(0, 10));
  const [source, setSource] = useState("synthetic");
  const [slippage, setSlippage] = useState(5);
  const [costStress, setCostStress] = useState(1);
  const [cash, setCash] = useState(100000);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const created = await api.createBacktest({
        strategy: strategy.name,
        params,
        start,
        end,
        initial_cash: cash,
        data_source: source,
        slippage_bps: slippage,
        cost_stress: costStress,
      });
      router.push(`/backtests/${created.run_id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }, [strategy.name, params, start, end, cash, source, slippage, costStress, router]);

  const properties = strategy.params_schema.properties ?? {};

  return (
    <div style={{ marginTop: 14, borderTop: "1px solid var(--border)", paddingTop: 14 }}>
      <h3>Parameters</h3>
      <div className="field-grid">
        {Object.entries(properties).map(([key, schema]) => (
          <ParamField
            key={key}
            name={key}
            schema={schema}
            value={params[key]}
            onChange={(value) => setParams((prev) => ({ ...prev, [key]: value }))}
          />
        ))}
      </div>

      <h3>Run settings</h3>
      <div className="field-grid">
        <label>
          <span>Start</span>
          <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
        </label>
        <label>
          <span>End</span>
          <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
        </label>
        <label>
          <span>Initial cash (USD)</span>
          <input
            type="number"
            value={cash}
            min={1000}
            step={1000}
            onChange={(e) => setCash(Number(e.target.value))}
          />
        </label>
        <label>
          <span>Data source</span>
          <select value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="synthetic">synthetic (engine verification only)</option>
            <option value="yfinance">yfinance (real history, research only)</option>
          </select>
        </label>
        <label>
          <span>Slippage (bps)</span>
          <input
            type="number"
            value={slippage}
            min={0}
            step={0.5}
            onChange={(e) => setSlippage(Number(e.target.value))}
          />
        </label>
        <label>
          <span>Cost stress (×)</span>
          <input
            type="number"
            value={costStress}
            min={0}
            step={0.5}
            onChange={(e) => setCostStress(Number(e.target.value))}
          />
        </label>
      </div>

      {source === "synthetic" && (
        <p className="banner banner-warn">
          Synthetic prices are generated, not observed. Useful for checking the
          engine; meaningless as evidence about a strategy.
        </p>
      )}
      {costStress === 1 && (
        <p className="banner banner-info">
          Run this again at 3× cost stress before believing the result. A strategy
          whose sign flips under realistic costs does not have an edge.
        </p>
      )}
      {error && <p className="banner banner-bad">{error}</p>}

      <button className="primary" onClick={submit} disabled={busy}>
        {busy ? "Queueing…" : "Run backtest"}
      </button>
    </div>
  );
}

function ParamField({
  name,
  schema,
  value,
  onChange,
}: {
  name: string;
  schema: JsonSchemaProperty;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const label = schema.title ?? name;

  // A closed set of values is rendered as a closed control. Falling through to
  // a free-text box would let the operator type something the API rejects with
  // a 422 they cannot act on.
  if (Array.isArray(schema.enum) && schema.enum.length > 0) {
    return (
      <label>
        <span title={schema.description}>{label}</span>
        <select
          value={typeof value === "string" ? value : String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
        >
          {schema.enum.map((option) => (
            <option key={String(option)} value={String(option)}>
              {String(option)}
            </option>
          ))}
        </select>
      </label>
    );
  }

  if (schema.type === "array") {
    const list = Array.isArray(value) ? (value as string[]) : [];
    return (
      <label>
        <span title={schema.description}>{label} (comma separated)</span>
        <input
          value={list.join(", ")}
          onChange={(e) =>
            onChange(
              e.target.value
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean),
            )
          }
        />
      </label>
    );
  }

  if (schema.type === "integer" || schema.type === "number") {
    return (
      <label>
        <span title={schema.description}>{label}</span>
        <input
          type="number"
          value={typeof value === "number" ? value : ""}
          min={schema.minimum ?? schema.exclusiveMinimum}
          max={schema.maximum ?? schema.exclusiveMaximum}
          step={schema.type === "integer" ? 1 : "any"}
          onChange={(e) => onChange(Number(e.target.value))}
        />
      </label>
    );
  }

  return (
    <label>
      <span title={schema.description}>{label}</span>
      <input
        value={typeof value === "string" ? value : String(value ?? "")}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}
