"use client";

/**
 * Programme configuration.
 *
 * The operating prompt's section 2, thirty-three keys. Its first rule about this
 * table is that a value nobody supplied is recorded as TBD rather than
 * invented, so an empty field renders as TBD here and stores as NULL — never as
 * an empty string that later reads like a deliberate choice.
 *
 * Critical unknowns are separated from the rest because the prompt asks for
 * exactly that separation: an absent reporting timezone should not block useful
 * work, and an absent maximum drawdown should.
 */

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, api, type ProgrammeConfig } from "@/lib/api";
import { Skeleton } from "@/components/Skeleton";

function ConfigRow({
  item,
  draft,
  onChange,
}: {
  item: ProgrammeConfig["items"][number];
  draft: string | undefined;
  onChange: (key: string, value: string) => void;
}) {
  const current = draft ?? item.value ?? "";
  return (
    <tr>
      <td className="mono">{item.key}</td>
      <td>
        <input
          type="text"
          value={current}
          placeholder="TBD"
          onChange={(e) => onChange(item.key, e.target.value)}
          aria-label={item.key}
        />
      </td>
      <td>
        {item.value === null ? (
          <span className={item.is_critical ? "pill pill-unknown" : "pill pill-mute"}>
            TBD
          </span>
        ) : (
          <span className="pill pill-good">set</span>
        )}
      </td>
      <td className="muted">{item.notes}</td>
    </tr>
  );
}

export default function ProgrammeConfigPage() {
  const router = useRouter();
  const [config, setConfig] = useState<ProgrammeConfig | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setConfig(await api.programmeConfig());
      setError(null);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.isUnauthorized) {
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [router]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const change = (key: string, value: string) => {
    setSaved(false);
    setDraft((d) => ({ ...d, [key]: value }));
  };

  const save = async () => {
    if (Object.keys(draft).length === 0) return;
    setBusy(true);
    try {
      setConfig(await api.setProgrammeConfig(draft));
      setDraft({});
      setSaved(true);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (error && !config) return <p className="banner banner-bad">{error}</p>;
  if (!config) return <Skeleton rows={6} label="Loading the configuration" />;

  const critical = config.items.filter((i) => i.is_critical);
  const rest = config.items.filter((i) => !i.is_critical);

  return (
    <>
      <h1>Programme configuration</h1>
      <p className="subtitle">
        An empty field is TBD, and TBD is what it stays. Nothing here substitutes
        a plausible default for a value nobody supplied, because a guessed risk
        limit is indistinguishable from an agreed one once it is in the table.
      </p>

      {error ? <p className="banner banner-bad">{error}</p> : null}
      {saved ? <p className="banner banner-info">Saved.</p> : null}

      <section className="card">
        <div className="card-head spread">
          <h2>Critical</h2>
          <span className="muted">
            {config.critical_unknowns.length} still TBD
          </span>
        </div>
        <p className="muted">
          These bound what the programme may do or how a figure is interpreted.
          The runner works without them; a recommendation that depends on one is
          not worth making until it is set.
        </p>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Key</th>
                <th>Value</th>
                <th>State</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {critical.map((item) => (
                <ConfigRow
                  key={item.key}
                  item={item}
                  draft={draft[item.key]}
                  onChange={change}
                />
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Everything else</h2>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Key</th>
                <th>Value</th>
                <th>State</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {rest.map((item) => (
                <ConfigRow
                  key={item.key}
                  item={item}
                  draft={draft[item.key]}
                  onChange={change}
                />
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className="row">
        <button
          type="button"
          onClick={save}
          disabled={busy || Object.keys(draft).length === 0}
        >
          Save {Object.keys(draft).length || ""} change
          {Object.keys(draft).length === 1 ? "" : "s"}
        </button>
      </div>
    </>
  );
}
