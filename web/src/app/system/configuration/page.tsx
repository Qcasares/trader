"use client";

/**
 * System configuration.
 *
 * Which model the AI programme is pointed at, how hard it is asked to think,
 * the ceiling on a reply, and how often it runs. Four settings that used to be
 * an environment variable and a constant.
 *
 * Three things this page refuses to do, each for a reason the rest of the
 * system already applies elsewhere:
 *
 * 1. **It does not offer an effort level the chosen model rejects.** Effort is
 *    a per-model capability, not one global list — Haiku 4.5 has no effort
 *    parameter and sending one is an error on every subsequent pass. So the
 *    selector is built from the model, and when a model has none it is
 *    disabled and says why rather than quietly doing nothing.
 * 2. **It does not hide the providers it cannot reach.** They are listed,
 *    disabled, with what taking them would require. "No adapter is written" is
 *    a different answer from "this does not exist", and an operator who cannot
 *    tell them apart goes looking for the wrong thing.
 * 3. **It does not render a broken stored value as a working one.** If the
 *    runner would refuse what is stored, the banner says so in the runner's own
 *    words, because that deployment's programme is about to do nothing and the
 *    page is the only place that can say why.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  ApiError,
  api,
  type SystemConfiguration,
  type SystemConfigurationBody,
} from "@/lib/api";
import { Skeleton } from "@/components/Skeleton";
import { SecretField } from "@/components/SecretField";

/** Money, at the precision a per-call figure actually carries. */
function usd(value: number): string {
  return value >= 0.01 ? `$${value.toFixed(2)}` : `$${value.toFixed(4)}`;
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/** A cadence, in the unit an operator thinks in. */
function describeCadence(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "—";
  if (seconds % 3600 === 0) {
    const hours = seconds / 3600;
    return `${plural(hours, "hour")} between passes`;
  }
  if (seconds % 60 === 0) {
    return `${plural(seconds / 60, "minute")} between passes`;
  }
  return `${plural(seconds, "second")} between passes`;
}

/**
 * Coerce a stored row into something an input can hold.
 *
 * Stored values arrive as `unknown` because a row can hold what the runner
 * refuses. The draft has to start somewhere, so it starts at whatever is there
 * when that is the right type and at the seeded default when it is not — and
 * the banner above the form still reports the stored value as unusable, so the
 * substitution is visible rather than silent.
 */
function asString(value: unknown, fallback: string): string {
  return typeof value === "string" ? value : fallback;
}

function asNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

export default function SystemConfigurationPage() {
  const router = useRouter();
  const [config, setConfig] = useState<SystemConfiguration | null>(null);
  const [draft, setDraft] = useState<SystemConfigurationBody | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  const adopt = useCallback((next: SystemConfiguration) => {
    setConfig(next);
    setDraft({
      provider: asString(next.stored.provider, next.defaults.provider),
      model: asString(next.stored.model, next.defaults.model),
      effort: asString(next.stored.effort, next.defaults.effort),
      max_tokens: asNumber(next.stored.max_tokens, next.defaults.max_tokens),
      tick_seconds: asNumber(next.stored.tick_seconds, next.defaults.tick_seconds),
    });
  }, []);

  const refresh = useCallback(async () => {
    try {
      adopt(await api.systemConfiguration());
      setError(null);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.isUnauthorized) {
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [adopt, router]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const chosen = useMemo(
    () => config?.models.find((m) => m.id === draft?.model) ?? null,
    [config, draft],
  );

  const providerModels = useMemo(
    () => config?.models.filter((m) => m.provider === draft?.provider) ?? [],
    [config, draft],
  );

  /**
   * The same rule the API applies, applied here so the operator hears it before
   * the request rather than after it. The API is still authoritative — this
   * only decides whether the button is worth pressing.
   */
  const problem = useMemo((): string | null => {
    if (!config || !draft) return null;
    const provider = config.providers.find((p) => p.key === draft.provider);
    if (!provider) return `Unknown provider ${draft.provider}.`;
    if (!provider.available) return `${provider.title} is not available. ${provider.note}`;
    if (!chosen) return `Unknown model ${draft.model}.`;
    if (chosen.efforts.length > 0 && !chosen.efforts.includes(draft.effort)) {
      return (
        `${chosen.title} does not accept the ${draft.effort} effort level. ` +
        `It accepts ${chosen.efforts.join(", ")}.`
      );
    }
    if (!Number.isInteger(draft.max_tokens)) return "The token ceiling must be a whole number.";
    if (draft.max_tokens < config.limits.min_max_tokens) {
      return `The token ceiling must be at least ${config.limits.min_max_tokens}. Below that a complete JSON reply cannot fit, and a truncated one is an error rather than a proposal with fields missing.`;
    }
    if (draft.max_tokens > chosen.max_output) {
      return `${chosen.title} caps output at ${chosen.max_output.toLocaleString()} tokens.`;
    }
    if (!Number.isInteger(draft.tick_seconds)) return "The cadence must be a whole number of seconds.";
    if (draft.tick_seconds < config.limits.min_tick_seconds) {
      return `The cadence must be at least ${config.limits.min_tick_seconds} seconds. Every pass can cost a model call, and what a pass can achieve is bounded by what the worker has finished since the last one.`;
    }
    if (draft.tick_seconds > config.limits.max_tick_seconds) {
      return `The cadence must be at most ${config.limits.max_tick_seconds} seconds.`;
    }
    return null;
  }, [chosen, config, draft]);

  const changed = useMemo(() => {
    if (!config || !draft) return [];
    const stored: Record<string, unknown> = config.stored;
    return (Object.keys(draft) as (keyof SystemConfigurationBody)[]).filter(
      (key) => stored[key] !== draft[key],
    );
  }, [config, draft]);

  const set = <K extends keyof SystemConfigurationBody>(
    key: K,
    value: SystemConfigurationBody[K],
  ) => {
    setSaved(false);
    setDraft((d) => (d ? { ...d, [key]: value } : d));
  };

  /**
   * Changing provider re-points the model, because a model belongs to exactly
   * one provider and leaving the old one selected would offer a pairing the
   * API refuses. The effort level is deliberately left alone: it is legal for
   * most models, and silently rewriting it would change a setting the operator
   * did not touch.
   */
  const setProvider = (key: string) => {
    if (!config || !draft) return;
    const first = config.models.find((m) => m.provider === key);
    setSaved(false);
    setDraft({ ...draft, provider: key, model: first ? first.id : draft.model });
  };

  const save = async () => {
    if (!draft || problem) return;
    setBusy(true);
    try {
      adopt(await api.setSystemConfiguration(draft));
      setSaved(true);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (error && !config) return <p className="banner banner-bad">{error}</p>;
  if (!config || !draft) return <Skeleton rows={5} label="Loading the configuration" />;

  const passesPerDay = draft.tick_seconds > 0 ? 86400 / draft.tick_seconds : 0;
  const perCallCeiling = chosen
    ? (draft.max_tokens / 1_000_000) * chosen.output_usd_per_mtok
    : null;
  const provenance = config.provenance[
    "programme_model"
  ] as { updated_by: string; updated_at: string | null } | undefined;

  return (
    <>
      <h1>Configuration</h1>
      <p className="subtitle">
        What the AI programme sends, and how often it sends it. These are read
        from the control plane on every pass, so a change here takes effect on
        the next one rather than on the next deploy.
      </p>

      {error ? <p className="banner banner-bad">{error}</p> : null}
      {saved ? <p className="banner banner-info">Saved. In effect from the next pass.</p> : null}

      {!config.usable && config.settings_problem ? (
        <p className="banner banner-bad">
          <strong>The programme is not calling a model.</strong> What is stored
          cannot be used: {config.settings_problem}. Until this is fixed the
          runner will still reconcile experiments, evaluate gates and promote
          candidates — it will simply propose nothing new, and the only other
          sign of that is a line in a log.
        </p>
      ) : null}

      {config.tick_problem ? (
        <p className="banner banner-warn">
          The stored cadence is unusable ({config.tick_problem}), so the runner
          is falling back to its documented default. Unlike the model settings,
          the cadence fails <em>slow</em> rather than closed: halting the
          programme over a mistyped interval would be a worse failure than
          running it hourly.
        </p>
      ) : null}

      <section className="card">
        <div className="card-head spread">
          <h2>Model</h2>
          {provenance ? (
            <span className="muted">
              {provenance.updated_by === "migration"
                ? "still the seeded default — nobody has reviewed this"
                : `last changed by ${provenance.updated_by}`}
            </span>
          ) : null}
        </div>

        <div className="field-grid">
          <label>
            <span>Provider</span>
            <select
              value={draft.provider}
              onChange={(e) => setProvider(e.target.value)}
            >
              {/* Same reason as the model select below. */}
              {config.providers.some((p) => p.key === draft.provider) ? null : (
                <option value={draft.provider}>{draft.provider} — unknown</option>
              )}
              {config.providers.map((p) => (
                <option key={p.key} value={p.key} disabled={!p.available}>
                  {p.title}
                  {p.available ? "" : " — no adapter"}
                </option>
              ))}
            </select>
            <span className="hint">
              Only one is implemented. The rest are listed so their absence is a
              stated fact rather than a gap.
            </span>
          </label>

          <label>
            <span>Model</span>
            <select
              value={draft.model}
              onChange={(e) => set("model", e.target.value)}
            >
              {/*
                A `select` whose value matches no option renders the *first*
                one, so a stored model that is not in the catalogue would
                display as whatever happens to sit at the top of the list —
                the page would show a working model while the runner refused
                to call anything. The stored value gets its own option so it
                is shown as what it is.
              */}
              {chosen === null ? (
                <option value={draft.model}>{draft.model} — not in the catalogue</option>
              ) : null}
              {providerModels.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.title}
                </option>
              ))}
            </select>
            <span className="hint">
              {chosen
                ? `${usd(chosen.input_usd_per_mtok)} in / ${usd(
                    chosen.output_usd_per_mtok,
                  )} out per million tokens, read ${config.prices_as_of}.`
                : "Not in the catalogue."}
            </span>
          </label>

          <label>
            <span>Effort</span>
            <select
              value={draft.effort}
              disabled={!chosen || chosen.efforts.length === 0}
              onChange={(e) => set("effort", e.target.value)}
            >
              {config.efforts.map((level) => (
                <option
                  key={level}
                  value={level}
                  disabled={
                    chosen !== null &&
                    chosen.efforts.length > 0 &&
                    !chosen.efforts.includes(level)
                  }
                >
                  {level}
                </option>
              ))}
            </select>
            <span className="hint">
              {chosen && chosen.efforts.length === 0
                ? `${chosen.title} has no effort parameter. The stored value is kept for the day the model changes and is not sent.`
                : "Cheapest on the left. Controls how much the model thinks before answering, and most of what a pass costs."}
            </span>
          </label>

          <label>
            <span>Token ceiling per call</span>
            <input
              type="number"
              value={draft.max_tokens}
              min={config.limits.min_max_tokens}
              max={chosen?.max_output}
              step={100}
              onChange={(e) => set("max_tokens", Number(e.target.value))}
            />
            <span className="hint">
              A cap, not a request size. Each prompt asks for what it needs; this
              is the most any of them may get.
            </span>
          </label>
        </div>

        {chosen?.note ? <p className="banner banner-info">{chosen.note}</p> : null}
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Cadence</h2>
        </div>
        <div className="field-grid">
          <label>
            <span>Seconds between scheduled passes</span>
            <input
              type="number"
              value={draft.tick_seconds}
              min={config.limits.min_tick_seconds}
              max={config.limits.max_tick_seconds}
              step={60}
              onChange={(e) => set("tick_seconds", Number(e.target.value))}
            />
            <span className="hint">
              {describeCadence(draft.tick_seconds)}, so at most{" "}
              {Math.floor(passesPerDay)} a day. An operator can force an
              immediate pass from the Programme page at any time.
            </span>
          </label>
        </div>
      </section>

      <section className="card">
        <div className="card-head">
          <h2>What this costs</h2>
        </div>
        <dl className="assumptions">
          <div className="assumption-row">
            <dt>Output, at most, per model call</dt>
            <dd>{perCallCeiling === null ? "—" : usd(perCallCeiling)}</dd>
          </div>
          <div className="assumption-row">
            <dt>Scheduled passes per day, at most</dt>
            <dd>{Math.floor(passesPerDay)}</dd>
          </div>
          <div className="assumption-row">
            <dt>Effort actually sent</dt>
            <dd>
              {/*
                Three different answers, and collapsing any two of them would
                mislead: the model has no effort parameter, or the settings
                would not produce a request at all, or this is the level.
              */}
              {chosen === null ? (
                <span className="pill pill-bad">no request is made</span>
              ) : chosen.efforts.length === 0 ? (
                <span className="pill pill-mute">not applicable</span>
              ) : (
                draft.effort
              )}
            </dd>
          </div>
          <div className="assumption-row">
            <dt>Prices read</dt>
            <dd>{config.prices_as_of}</dd>
          </div>
        </dl>
        <p className="muted">
          The first figure is a ceiling on the <em>output</em> of one call and
          nothing more. It excludes input tokens, which depend on how much of
          the ledger a prompt carries, and it excludes the panel: a pass that
          convenes a stage&apos;s specialists makes one call per role. Read it as
          the floor of what a bill could be, not an estimate of what it will be
          — and a pass makes no call at all when there is nothing new to judge.
        </p>
      </section>

      <div className="row">
        <button
          type="button"
          className="primary"
          onClick={save}
          disabled={busy || changed.length === 0 || problem !== null}
        >
          Save {changed.length || ""} change{changed.length === 1 ? "" : "s"}
        </button>
        {problem ? <span className="muted">{problem}</span> : null}
        {!problem && changed.length > 0 ? (
          <span className="muted">Changing: {changed.join(", ")}.</span>
        ) : null}
      </div>

      <section className="card">
        <div className="card-head">
          <h2>Credentials</h2>
        </div>
        <p className="muted">
          Stored encrypted, and never readable back. There is no endpoint that
          returns a credential, so the most this page can ever show is that one
          is set and which one it is. The fingerprint answers &quot;is this the
          key I think it is&quot; without being any part of the key.
        </p>
        {config.secrets_key_problem ? (
          <p className="banner banner-warn">
            <strong>This deployment cannot store a credential.</strong>{" "}
            {config.secrets_key_problem}. Generate one with{" "}
            <code>python -m src.db.secrets_cli keygen</code> and set it as{" "}
            <code>SECRETS_KEY</code> for the API and the programme — and not for
            the worker, which holds the broker credentials and must not be able
            to decrypt a model key. Until then the programme falls back to
            <code> ANTHROPIC_API_KEY</code> from its own environment, which is
            how this worked before.
          </p>
        ) : null}
        {config.secrets.map((secret) => (
          <SecretField
            key={secret.name}
            secret={secret}
            disabled={config.secrets_key_problem !== null}
            onChanged={() => void refresh()}
          />
        ))}
      </section>

      <section className="card">
        <div className="card-head">
          <h2>The other controls</h2>
        </div>
        <p className="muted">
          Listed rather than duplicated. A control with two places to set it is
          a control with two answers to what it is set to.
        </p>
        <dl className="assumptions">
          <div className="assumption-row">
            <dt>Kill switch</dt>
            <dd>
              <Link href="/system">System</Link>
            </dd>
          </div>
          <div className="assumption-row">
            <dt>Programme switch and autonomy ceiling</dt>
            <dd>
              <Link href="/programme">Programme</Link>
            </dd>
          </div>
          <div className="assumption-row">
            <dt>Research parameters, section 2</dt>
            <dd>
              <Link href="/programme/config">Programme configuration</Link>
            </dd>
          </div>
        </dl>
      </section>
    </>
  );
}
