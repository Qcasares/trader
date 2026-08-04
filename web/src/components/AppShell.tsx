"use client";

/**
 * AppShell.tsx
 * ------------
 * Sidebar on a desktop, a sheet on a phone, and nothing at all on the login
 * screen.
 *
 * The last clause is the only interesting one. Rendering navigation to a
 * signed-out visitor lists every section of the application to someone who
 * cannot open any of them, and a nav full of links that all bounce to `/login`
 * is worse than no nav: it reads as a broken application rather than a locked
 * one.
 *
 * The layout is a two-column grid rather than a fixed-position aside so the
 * main column is a real grid track. A fixed sidebar plus a margin on the
 * content is the same thing until the viewport is narrow or the content is a
 * wide table, at which point the margin and the sidebar disagree about how much
 * room there is.
 */

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Menu } from "lucide-react";
import { AppNav } from "@/components/AppNav";
import { SessionControls } from "@/components/SessionControls";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";

function Brand() {
  return (
    <Link href="/" className="brand">
      <span className="brand-mark" aria-hidden="true" />
      Systematic Trading
    </Link>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  if (pathname === "/login") {
    return <main className="mx-auto w-full max-w-md px-4 py-10">{children}</main>;
  }

  return (
    <div className="min-h-dvh md:grid md:grid-cols-[13rem_1fr]">
      {/* Desktop rail. Sticky rather than scrolling with the page: the whole
          nav fits in a viewport by design, so the operator never loses it while
          reading a long table. */}
      <aside className="sticky top-0 hidden h-dvh flex-col gap-4 border-r border-line bg-panel px-2 py-3 md:flex">
        <div className="px-2">
          <Brand />
        </div>
        <div className="flex-1 overflow-y-auto">
          <AppNav />
        </div>
        <div className="border-t border-line px-2 pt-2">
          <SessionControls />
        </div>
      </aside>

      {/* Phone bar. The trigger is a real button with a name, not a bare
          glyph — an icon-only control with no accessible name is invisible to
          a screen reader and ambiguous to everyone else. */}
      <header className="sticky top-0 z-50 flex items-center gap-2 border-b border-line bg-panel px-3 py-2 md:hidden">
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="Open navigation">
              <Menu aria-hidden="true" />
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="w-60 bg-panel px-2 py-3">
            <SheetTitle className="px-2">
              <Brand />
            </SheetTitle>
            {/* Closing on navigate: a sheet that stays open over the page you
                just asked for hides the thing you were trying to reach. */}
            <div className="mt-4">
              <AppNav onNavigate={() => setOpen(false)} />
            </div>
            <div className="mt-4 border-t border-line px-2 pt-2">
              <SessionControls />
            </div>
          </SheetContent>
        </Sheet>
        <Brand />
      </header>

      <main className="min-w-0 px-4 py-5 md:px-6">{children}</main>
    </div>
  );
}
