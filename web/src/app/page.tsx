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
 *
 * Rebuilt on shadcn primitives to match System and Backtests: each strategy is
 * a Card, status pills become StatusBadge, and the parameter/run-settings
 * inputs are Label + Input + Select rather than bare `<label><input>` pairs.
 * The schema-driven field logic, the multiple-testing counter and both
 * honesty banners (synthetic data, cost stress) are unchanged — only their
 * markup. The one presentational addition is that each parameter's
 * `schema.description` now renders as a visible `.hint` line under its label
 * instead of an inaccessible `title=` tooltip, since it is documentation of
 * what the field accepts, not decoration.
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
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

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
      <div className="mb-4">
        <h1 className="mb-1">Strategies</h1>
        <p className="subtitle">
          Deterministic, backtestable rules. Parameters are tunable here and
          take effect on the next run — no redeploy.
        </p>
      </div>

      <div className="space-y-3">
        {strategies.map((strategy) => (
          <Card key={strategy.name}>
            <CardHeader>
              <CardTitle className="flex flex-wrap items-center gap-2">
                {strategy.name}
                <StatusBadge status="mute">v{strategy.version}</StatusBadge>
                <BacktestCount count={strategy.backtest_count} />
                <Button
                  variant="outline"
                  size="sm"
                  className="ml-auto"
                  onClick={() =>
                    setSelected(
                      selected === strategy.name ? null : strategy.name,
                    )
                  }
                >
                  {selected === strategy.name ? "Hide" : "Configure & run"}
                </Button>
              </CardTitle>
              <p className="m-0 text-sm text-ink-muted text-pretty">
                {strategy.description}
              </p>
              <p className="mono m-0 text-xs text-ink-faint">
                {strategy.universe.join(" · ")} — warm-up{" "}
                {strategy.warmup_sessions} sessions
              </p>
              {strategy.source && (
                <p className="m-0 text-xs text-ink-faint">
                  Source: {strategy.source}
                </p>
              )}
            </CardHeader>
            {selected === strategy.name && active && (
              <CardContent>
                <RunForm strategy={active} />
              </CardContent>
            )}
          </Card>
        ))}
      </div>
    </>
  );
}

/**
 * A visible count of how many times this strategy has been backtested.
 *
 * The tune-rerun-look-at-Sharpe loop is how people fool themselves. Showing
 * the roll count makes the multiple-testing problem impossible to ignore.
 * `unknown` (amber) carries the same weight here as it does for synthetic
 * data on the Backtests page — a state the operator should not skim past.
 */
function BacktestCount({ count }: { count: number }) {
  if (count === 0) return <StatusBadge status="mute">never run</StatusBadge>;
  const heavy = count >= 20;
  return (
    <StatusBadge status={heavy ? "unknown" : "mute"}>
      {count} backtest{count === 1 ? "" : "s"} run
      {heavy ? " — mind the multiple testing" : ""}
    </StatusBadge>
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
    <div>
      <h3 className="mb-2 text-sm font-medium">Parameters</h3>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
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

      <Separator className="my-4" />

      <h3 className="mb-2 text-sm font-medium">Run settings</h3>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <div className="space-y-1.5">
          <Label htmlFor="start">Start</Label>
          <Input
            id="start"
            type="date"
            value={start}
            onChange={(e) => setStart(e.target.value)}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="end">End</Label>
          <Input
            id="end"
            type="date"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="cash">Initial cash (USD)</Label>
          <Input
            id="cash"
            type="number"
            value={cash}
            min={1000}
            step={1000}
            onChange={(e) => setCash(Number(e.target.value))}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="source">Data source</Label>
          <Select value={source} onValueChange={setSource}>
            <SelectTrigger id="source" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="synthetic">
                synthetic (engine verification only)
              </SelectItem>
              <SelectItem value="yfinance">
                yfinance (real history, research only)
              </SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="slippage">Slippage (bps)</Label>
          <Input
            id="slippage"
            type="number"
            value={slippage}
            min={0}
            step={0.5}
            onChange={(e) => setSlippage(Number(e.target.value))}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="cost-stress">Cost stress (×)</Label>
          <Input
            id="cost-stress"
            type="number"
            value={costStress}
            min={0}
            step={0.5}
            onChange={(e) => setCostStress(Number(e.target.value))}
          />
        </div>
      </div>

      {source === "synthetic" && (
        <p className="banner banner-warn mt-4">
          Synthetic prices are generated, not observed. Useful for checking the
          engine; meaningless as evidence about a strategy.
        </p>
      )}
      {costStress === 1 && (
        <p className="banner banner-info mt-4">
          Run this again at 3× cost stress before believing the result. A
          strategy whose sign flips under realistic costs does not have an
          edge.
        </p>
      )}
      {error && <p className="banner banner-bad mt-4">{error}</p>}

      <Button className="mt-2" onClick={submit} disabled={busy}>
        {busy ? "Queueing…" : "Run backtest"}
      </Button>
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
  const fieldId = `param-${name}`;

  // A closed set of values is rendered as a closed control. Falling through to
  // a free-text box would let the operator type something the API rejects with
  // a 422 they cannot act on.
  if (Array.isArray(schema.enum) && schema.enum.length > 0) {
    return (
      <div className="space-y-1.5">
        <Label htmlFor={fieldId}>{label}</Label>
        <Select
          value={typeof value === "string" ? value : String(value ?? "")}
          onValueChange={onChange}
        >
          <SelectTrigger id={fieldId} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {schema.enum.map((option) => (
              <SelectItem key={String(option)} value={String(option)}>
                {String(option)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {schema.description && <span className="hint">{schema.description}</span>}
      </div>
    );
  }

  if (schema.type === "array") {
    const list = Array.isArray(value) ? (value as string[]) : [];
    return (
      <div className="space-y-1.5">
        <Label htmlFor={fieldId}>{label} (comma separated)</Label>
        <Input
          id={fieldId}
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
        {schema.description && <span className="hint">{schema.description}</span>}
      </div>
    );
  }

  if (schema.type === "integer" || schema.type === "number") {
    return (
      <div className="space-y-1.5">
        <Label htmlFor={fieldId}>{label}</Label>
        <Input
          id={fieldId}
          type="number"
          value={typeof value === "number" ? value : ""}
          min={schema.minimum ?? schema.exclusiveMinimum}
          max={schema.maximum ?? schema.exclusiveMaximum}
          step={schema.type === "integer" ? 1 : "any"}
          onChange={(e) => onChange(Number(e.target.value))}
        />
        {schema.description && <span className="hint">{schema.description}</span>}
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      <Label htmlFor={fieldId}>{label}</Label>
      <Input
        id={fieldId}
        value={typeof value === "string" ? value : String(value ?? "")}
        onChange={(e) => onChange(e.target.value)}
      />
      {schema.description && <span className="hint">{schema.description}</span>}
    </div>
  );
}
