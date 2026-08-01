import type { Metadata } from "next";
import Link from "next/link";
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
            <Link href="/system">System</Link>
          </nav>
        </header>
        <main>{children}</main>
        <footer className="footer">
          Paper trading only. No live credentials are configured, and live
          execution requires both an environment gate and the database kill
          switch to permit it.
        </footer>
      </body>
    </html>
  );
}
