import type { Metadata } from "next";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
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
    /*
      The type is Geist and Geist Mono (web/DESIGN.md OD-5, T-10), from the
      `geist` package through `next/font/local`: the font files are bundled
      into the build and served from this app's own origin, so no page asks a
      third party for its type. `.variable`, not `.className`: each defines a
      custom property here on <html> — `--font-geist-sans`, `--font-geist-mono`
      — which `--sans` and `--mono` in globals.css lead with, so the face
      arrives through the tokens every rule and utility already reads rather
      than through a class that would bypass them. Take either away and the
      token that leads with it stops resolving, and the page falls back to the
      browser's serif; tests/unit/test_web_taste.py holds both here.
    */
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`}>
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
