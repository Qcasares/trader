"use client";

/**
 * Single-operator login. One password, one signed session cookie.
 *
 * The last page to move onto the design system, and the only one still carrying
 * an inline `style` attribute.
 *
 * It is deliberately not built from a catalogue login component, and the reason
 * is worth recording because it will come up again. Every login in the 21st.dev
 * catalogue solves multi-tenant SaaS authentication: an email field, social
 * providers, remember-me, forgot-password, create-account. This system has one
 * operator, one password checked against a bcrypt hash in the environment, no
 * account store, no recovery flow and no providers. Importing one would have
 * meant shipping four controls that do nothing, and a page whose buttons lie
 * about what the system can do is a worse page, not a more finished-looking one.
 *
 * What it takes from the catalogue is the arrangement rather than the code: a
 * single centred card, the mark above the heading, the field and its error in
 * one column, the action at full width beneath.
 *
 * Two things here are load-bearing rather than decorative:
 *
 * - **The error is rendered verbatim.** `api.login` distinguishes a wrong
 *   password from an unreachable API, and the second message names the URL it
 *   tried and the origin it came from. Replacing either with a friendly
 *   "something went wrong" would remove the only diagnosis available at the one
 *   moment nobody can reach the rest of the interface to look for another.
 * - **The form does not lock itself after a failure.** The most common cause of
 *   a failure here is a typo, and a form that disables itself on error is a form
 *   that cannot be retried.
 */

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function LoginPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.login(password);
      router.push("/");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };

  return (
    // Narrower than the rest of the app on purpose. Every other page is a
    // dense readout that wants the full column; this one is a single field, and
    // a 680px-wide box around one password input reads as an unfinished form.
    <div className="mx-auto flex min-h-[70dvh] max-w-sm flex-col justify-center">
      <div className="mb-5 flex items-center gap-2">
        <span className="brand-mark" aria-hidden="true" />
        <span className="text-md">Systematic Trading</span>
      </div>

      <h1 className="mb-1">Sign in</h1>
      <p className="mb-4 text-base text-ink-muted">
        Operator access to the control plane.
      </p>

      <Card>
        <CardContent>
          <form onSubmit={submit} className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                value={password}
                autoFocus
                autoComplete="current-password"
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>

            {error ? <p className="banner banner-bad m-0">{error}</p> : null}

            <Button type="submit" className="w-full" disabled={busy || !password}>
              {busy ? "Signing in…" : "Sign in"}
            </Button>
          </form>
        </CardContent>
      </Card>

      <p className="mt-4 text-sm text-ink-muted text-pretty">
        One operator, one password, and no way to recover it from here: it is a
        bcrypt hash in the deployment&apos;s environment, so changing it means
        changing <code>ADMIN_PASSWORD_HASH</code>. A session lasts twelve hours
        and is signed rather than stored, which means it cannot be revoked
        individually before then — rotating <code>SESSION_SECRET</code> ends all
        of them at once.
      </p>
    </div>
  );
}
