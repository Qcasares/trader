"use client";

/**
 * SecretField.tsx
 * ---------------
 * Setting a credential you can never read back.
 *
 * The shape of this control is decided by one fact: there is no endpoint that
 * returns a secret. Not "the UI chooses not to show it" — the capability does
 * not exist on the server. So this is deliberately not a text input that loads
 * its current value, edits it, and saves it back. It cannot be.
 *
 * What it is instead:
 *
 * - **Write-only.** The field is always empty on load. It is not pre-filled
 *   with dots pretending to be the stored value, which is the conventional
 *   pattern and a small lie: those dots imply a length and a value that the
 *   page does not have.
 * - **Identified, not revealed.** When a credential is stored the page shows a
 *   fingerprint — a truncated digest of the plaintext — so an operator can tell
 *   *which* key is in there. Deliberately not the last four characters, which
 *   is the usual shortcut and is four real characters of a real credential.
 * - **Asymmetric, like every other control here.** Setting a credential takes a
 *   deliberate act and a visible confirmation; clearing one is a single button
 *   with no ceremony. Removing a credential is the safe direction, and a
 *   deployment whose key is wrong is exactly the one that most needs to be able
 *   to delete what it can no longer read.
 *
 * `type="password"` and `autoComplete="off"` keep the value out of shoulder
 * view and out of the browser's saved-password store, where a model API key has
 * no business being.
 */

import { useState } from "react";
import { Eye, EyeOff, Trash2 } from "lucide-react";
import { api, type SecretDescription } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { StatusBadge } from "@/components/StatusBadge";
import { fmtInstant } from "@/lib/format";

/** Human-facing names. The wire name is a database key, not a label. */
const TITLES: Record<string, string> = {
  anthropic_api_key: "Anthropic API key",
};

const NOTES: Record<string, string> = {
  anthropic_api_key:
    "Used by the AI programme to propose hypotheses and convene the specialist panel. Without it the runner still reconciles experiments, evaluates gates and promotes candidates — it simply proposes nothing new.",
};

export function SecretField({
  secret,
  disabled,
  onChanged,
}: {
  secret: SecretDescription;
  disabled: boolean;
  onChanged: () => void;
}) {
  const [value, setValue] = useState("");
  const [reveal, setReveal] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const title = TITLES[secret.name] ?? secret.name;

  const save = async () => {
    if (!value.trim()) return;
    setBusy(true);
    try {
      await api.setSecret(secret.name, value.trim());
      // Cleared immediately on success. The credential has been sent; keeping
      // it in a React state field afterwards leaves it in memory and in the
      // DOM for no purpose the operator asked for.
      setValue("");
      setReveal(false);
      setSaved(true);
      setError(null);
      onChanged();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const clear = async () => {
    setBusy(true);
    try {
      await api.clearSecret(secret.name);
      setSaved(false);
      setError(null);
      onChanged();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="border-t border-line pt-3 first:border-t-0 first:pt-0">
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <span className="text-md">{title}</span>
        {secret.configured ? (
          <StatusBadge status="settled">stored</StatusBadge>
        ) : (
          // `unknown`, not `blocked`. An unset credential is not a failure: the
          // programme has a documented, correct behaviour without one. It is a
          // state nobody has supplied yet, which is exactly what amber means
          // everywhere else in this interface.
          <StatusBadge status="unknown">not set</StatusBadge>
        )}
        {secret.configured && secret.fingerprint ? (
          <span className="font-mono text-xs text-ink-muted">
            {secret.fingerprint}
          </span>
        ) : null}
      </div>

      {NOTES[secret.name] ? (
        <p className="mt-0 mb-2 text-sm text-ink-muted text-pretty">
          {NOTES[secret.name]}
        </p>
      ) : null}

      {secret.configured && secret.updated_at ? (
        <p className="mt-0 mb-2 text-xs text-ink-muted">
          set by {secret.updated_by} at {fmtInstant(secret.updated_at)}
        </p>
      ) : null}

      {error ? <p className="banner banner-bad">{error}</p> : null}
      {saved ? (
        <p className="banner banner-info">
          Stored. The programme picks it up on its next pass.
        </p>
      ) : null}

      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-[16rem] flex-1">
          <Label htmlFor={`secret-${secret.name}`}>
            {secret.configured ? "Replace it" : "Set it"}
          </Label>
          <div className="relative">
            <Input
              id={`secret-${secret.name}`}
              // Never pre-filled, not even with placeholder dots: the page does
              // not know the stored value or its length, and dots would imply
              // both.
              value={value}
              onChange={(e) => {
                setSaved(false);
                setValue(e.target.value);
              }}
              type={reveal ? "text" : "password"}
              autoComplete="off"
              spellCheck={false}
              disabled={disabled || busy}
              placeholder={disabled ? "unavailable on this deployment" : "paste the key"}
              className="pr-9 font-mono"
            />
            <button
              type="button"
              onClick={() => setReveal((r) => !r)}
              // Reveals what the operator is currently typing, never what is
              // stored. A paste is worth being able to check; there is nothing
              // else here to show.
              aria-label={reveal ? "Hide what you typed" : "Show what you typed"}
              className="absolute top-1/2 right-2 -translate-y-1/2 text-ink-faint hover:text-ink"
            >
              {reveal ? (
                <EyeOff aria-hidden="true" className="size-3.5" />
              ) : (
                <Eye aria-hidden="true" className="size-3.5" />
              )}
            </button>
          </div>
        </div>
        <Button
          type="button"
          onClick={save}
          disabled={disabled || busy || !value.trim()}
        >
          {secret.configured ? "Replace" : "Store"}
        </Button>
        {secret.configured ? (
          <Button
            type="button"
            variant="outline"
            onClick={clear}
            disabled={busy}
            aria-label={`Clear the ${title}`}
          >
            <Trash2 aria-hidden="true" />
            Clear
          </Button>
        ) : null}
      </div>
    </div>
  );
}
