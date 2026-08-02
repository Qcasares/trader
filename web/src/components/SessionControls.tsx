"use client";

/**
 * SessionControls.tsx
 * -------------------
 * Signing out.
 *
 * `api.logout` existed from the beginning and no page ever called it, so there
 * was no way to end a session short of clearing cookies by hand. The session
 * is signed rather than stored, which means it cannot be revoked server-side
 * either — a token stays valid for its full 12 hours no matter what. Clearing
 * the cookie is therefore the only control available, and it needs to exist.
 *
 * It matters more since the cookie became `SameSite=None` for the deployed
 * topology: it is now sent on cross-site requests, so leaving one live on a
 * shared machine is a larger loan than it was.
 */

import { useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { ApiError, api } from "@/lib/api";

export function SessionControls() {
  const pathname = usePathname();
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  // Nothing to sign out of on the way in.
  if (pathname === "/login") return null;

  const signOut = async () => {
    setBusy(true);
    try {
      await api.logout();
    } catch (err: unknown) {
      // A logout that cannot reach the API still has to get the operator off
      // this screen. Failing closed here would mean an unreachable backend
      // leaves someone stuck in an apparently-authenticated UI.
      if (!(err instanceof ApiError)) throw err;
    } finally {
      router.push("/login");
      // The cookie is HttpOnly, so client-side state is not the authority on
      // whether it is gone. Reload rather than trusting the router's cache.
      router.refresh();
      setBusy(false);
    }
  };

  return (
    <button onClick={signOut} disabled={busy} className="linklike">
      {busy ? "Signing out…" : "Sign out"}
    </button>
  );
}
