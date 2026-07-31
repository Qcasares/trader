import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // The FastAPI control plane runs on its own host (Fly/Railway/Render); a
  // Next.js server cannot hold the trading loop and does not try to.
  env: {
    NEXT_PUBLIC_API_BASE: process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000",
  },
};

export default nextConfig;
