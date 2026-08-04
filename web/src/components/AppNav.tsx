"use client";

/**
 * AppNav.tsx
 * ----------
 * The navigation, and the reason it is a sidebar.
 *
 * This app has fifteen routes. The top bar it replaces showed five, so
 * two thirds of the application — every hypothesis, finding, experiment and
 * report in the AI programme, and the configuration page that decides what the
 * programme is pointed at — were reachable only by already knowing they were
 * there, or by finding an inline link on some other page. Discoverability was
 * not a polish problem; whole surfaces were effectively unlisted.
 *
 * Grouping is by *what the operator is doing*, not by URL shape:
 *
 * - **Research** is the lab: define a strategy, measure it.
 * - **Operations** is the running system: what it holds, whether it is alive,
 *   what it is configured to do.
 * - **Programme** is the AI's own workflow, which has its own vocabulary and
 *   its own ledger, and which an operator visits for different reasons than
 *   either of the above.
 *
 * Detail routes (`/backtests/[id]`, `/programme/hypotheses/[ref]`) are
 * deliberately absent. They are reached from a list, they are unbounded in
 * number, and a nav that grows with the data is a nav nobody can scan.
 * `isActive` still lights their parent, so descending into one never leaves the
 * sidebar looking like you are nowhere.
 *
 * Density is the same argument as everywhere else here: 28px rows and 12px
 * labels, so the whole application fits above the fold on a laptop and the
 * sidebar never itself needs scrolling.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  FlaskConical,
  Gauge,
  Lightbulb,
  ListChecks,
  Settings2,
  ShieldAlert,
  SlidersHorizontal,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

type Item = {
  href: string;
  label: string;
  icon: LucideIcon;
  /**
   * Whether a deeper path should light this item. False for the section roots
   * that share a prefix with their own children — `/programme` must not stay
   * lit while you are on `/programme/findings`, or two items are active at
   * once and neither tells you where you are.
   */
  matchNested?: boolean;
};

const GROUPS: { heading: string; items: Item[] }[] = [
  {
    heading: "Research",
    items: [
      { href: "/", label: "Strategies", icon: FlaskConical },
      { href: "/backtests", label: "Backtests", icon: Activity, matchNested: true },
    ],
  },
  {
    heading: "Operations",
    items: [
      { href: "/portfolio", label: "Portfolio", icon: Wallet },
      { href: "/system", label: "System", icon: Gauge },
      { href: "/system/configuration", label: "Configuration", icon: Settings2 },
    ],
  },
  {
    heading: "Programme",
    items: [
      { href: "/programme", label: "Overview", icon: Lightbulb },
      {
        href: "/programme/hypotheses",
        label: "Hypotheses",
        icon: ListChecks,
        matchNested: true,
      },
      { href: "/programme/findings", label: "Findings", icon: ShieldAlert },
      { href: "/programme/report", label: "Daily report", icon: Activity },
      { href: "/programme/config", label: "Parameters", icon: SlidersHorizontal },
    ],
  },
];

function isActive(pathname: string, item: Item): boolean {
  if (pathname === item.href) return true;
  if (!item.matchNested) return false;
  return pathname.startsWith(`${item.href}/`);
}

export function AppNav({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();

  return (
    <nav aria-label="Sections" className="flex flex-col gap-4">
      {GROUPS.map((group) => (
        <div key={group.heading}>
          <h2 className="mb-1 px-2 text-xs font-medium tracking-[0.045em] text-ink-faint uppercase">
            {group.heading}
          </h2>
          <ul className="m-0 list-none p-0">
            {group.items.map((item) => {
              const active = isActive(pathname, item);
              const Icon = item.icon;
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    onClick={onNavigate}
                    // `aria-current` rather than colour alone. The active row is
                    // also the only one with a filled background and a left
                    // rule, so "where am I" survives with no colour at all.
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "flex items-center gap-2 rounded-sm border-l-2 border-transparent px-2 py-1.5 text-sm no-underline transition-colors",
                      active
                        ? "border-l-brand bg-panel-2 text-ink"
                        : "text-ink-muted hover:bg-panel-2 hover:text-ink",
                    )}
                  >
                    <Icon aria-hidden="true" className="size-3.5 shrink-0" />
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}
