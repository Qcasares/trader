import type { NextConfig } from "next";

/**
 * Where the control plane lives.
 *
 * The FastAPI API runs as its own deployment — a Next.js server cannot hold
 * the trading loop and does not try to — so the browser needs its origin.
 *
 * Three cases, and each has to be right on its own:
 *
 * - `NEXT_PUBLIC_API_BASE` set: use it. This is what a Vercel project setting
 *   or a `.env.local` provides, and it wins over everything below.
 * - Building on Vercel with nothing set: the deployed API. Without this the
 *   build inlines `http://localhost:8000`, and every call from an HTTPS page
 *   is then blocked as mixed content — a UI that loads perfectly and can do
 *   nothing, with the reason visible only in the browser console.
 * - Anywhere else: localhost, because that is what `npm run dev` should talk
 *   to. Defaulting to the deployed API here would point a fresh clone's dev
 *   server at production, which is a worse failure than a broken build.
 *
 * `VERCEL` is set to "1" by Vercel during a build and by nothing else, which
 * is what makes the middle case distinguishable from the last.
 *
 * Hardcoding a URL is fine here and only here: a `NEXT_PUBLIC_` value is
 * compiled into the JavaScript every visitor downloads, so it is public by
 * construction. It is not a credential, and it is deliberately not in
 * `.env.production`, which this repository gitignores as a secrets file.
 */
const DEPLOYED_API_BASE = "https://trader-vert-xi.vercel.app";
const LOCAL_API_BASE = "http://localhost:8000";

/**
 * Two normalisations, both for values a platform injects rather than a person
 * types:
 *
 * - Empty counts as unset. `??` alone would accept `""`, and an empty base
 *   turns every call into a relative fetch against the UI's own origin — a
 *   page full of quiet 404s. A blueprint variable that failed to resolve
 *   arrives as exactly this.
 * - A bare hostname gains `https://`. Render's `fromService`/`host` provides
 *   the API's hostname without a scheme; `fetch` needs one.
 */
const raw = (process.env.NEXT_PUBLIC_API_BASE ?? "").trim();
const explicit = raw && !raw.includes("://") ? `https://${raw}` : raw;

const apiBase =
  explicit || (process.env.VERCEL ? DEPLOYED_API_BASE : LOCAL_API_BASE);

/**
 * Whether the browser talks to the API directly or through this server.
 *
 * Direct is the simpler arrangement and it is what the code did first. It also
 * does not work in Safari or Firefox, for a reason that has nothing to do with
 * this application: `vercel.app` and `onrender.com` are on the Public Suffix
 * List, so `trader-ui-x.vercel.app` and `trader-y.vercel.app` are different
 * *sites*, the session cookie is third-party, and those browsers block
 * third-party cookies by default. The failure is the worst kind — `/auth/login`
 * returns 200 and sets the cookie, the browser drops it, and every call after
 * it gets 401, so a correct password looks like a rejected one and the app
 * bounces straight back to the login screen.
 *
 * `SESSION_COOKIE_SAMESITE=none` does not save it. SameSite governs whether a
 * cookie *may* be sent cross-site; third-party cookie blocking governs whether
 * it is stored at all, and blocking wins.
 *
 * So when `API_PROXY` is set, the browser calls this origin at `/api/...` and
 * the rewrite below forwards to the API. The cookie is then first-party and
 * every browser keeps it. The cost is that API traffic takes one extra hop
 * through a Next.js function; for a single operator that is nothing, and it
 * buys a UI that works in the browser people actually use.
 *
 * The alternative fix is a custom domain with the UI and API on sibling
 * subdomains, which makes them the same site properly. That is better, and it
 * needs a domain; this needs nothing.
 */
const proxyApi = (process.env.API_PROXY ?? "").trim() === "1";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  env: {
    // Empty means "same origin": `api.ts` builds `${BASE}${path}`, so an empty
    // base yields a relative URL, which is exactly what the proxy needs.
    NEXT_PUBLIC_API_BASE: proxyApi ? "" : apiBase,
  },
  async rewrites() {
    if (!proxyApi) return [];
    return [
      {
        source: "/api/:path*",
        destination: `${apiBase}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
