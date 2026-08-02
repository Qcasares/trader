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

const apiBase =
  process.env.NEXT_PUBLIC_API_BASE ??
  (process.env.VERCEL ? DEPLOYED_API_BASE : LOCAL_API_BASE);

const nextConfig: NextConfig = {
  reactStrictMode: true,
  env: {
    NEXT_PUBLIC_API_BASE: apiBase,
  },
};

export default nextConfig;
