import type { Metadata } from "next";
import { AppShell } from "@/components/AppShell";
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
        {/*
          A skip link, first in the tab order and visible only when focused.
          The sidebar is roughly a dozen links, and without this a keyboard
          user tabs through all of them on every single page before reaching
          the content — which is exactly the cost that made the old top bar
          "only five links" feel like a virtue.
        */}
        <a href="#content" className="skip-link">
          Skip to content
        </a>
        <AppShell>
          <div id="content">{children}</div>
        </AppShell>
        <footer className="footer">
          Paper trading only. Live execution requires three independent
          conditions: the deployment&apos;s mode, LIVE_TRADING_ENABLED and
          ALPACA_ALLOW_LIVE. The database kill switch sits on top of all three
          and fails closed.
        </footer>
      </body>
    </html>
  );
}
