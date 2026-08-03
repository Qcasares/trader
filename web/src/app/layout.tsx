import type { Metadata } from "next";
import Link from "next/link";
import { SessionControls } from "@/components/SessionControls";
import "./globals.css";

export const metadata: Metadata = {
  title: "Systematic Trading Control Plane",
  description:
    "Research lab and control plane for deterministic, backtestable trading strategies.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <header className="topbar">
          <Link href="/" className="brand">
            <span className="brand-mark" aria-hidden="true" />
            Systematic Trading
          </Link>
          <nav>
            <Link href="/">Strategies</Link>
            <Link href="/backtests">Backtests</Link>
            <Link href="/portfolio">Portfolio</Link>
            <Link href="/programme">Programme</Link>
            <Link href="/system">System</Link>
            <SessionControls />
          </nav>
        </header>
        <main>{children}</main>
        <footer className="footer">
          Paper trading only. Live execution requires three independent
          conditions — the deployment&apos;s mode, LIVE_TRADING_ENABLED and
          ALPACA_ALLOW_LIVE — and the database kill switch on top of them.
        </footer>
      </body>
    </html>
  );
}
