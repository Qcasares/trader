import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * Changed from stock, and logged in web/DESIGN.md (K-8):
 *
 * - **No focus ring.** Stock removes the outline and draws a 3px ring of
 *   `ring` at 50%, which measured 2.16:1 against a light card; the input now
 *   takes the one focus indicator, the accent outline from `globals.css`
 *   (owner decision OD-3, A-4). That includes a date input's calendar button,
 *   the stop on which the input matches no `:focus` at all.
 * - **Monospace, tabular, and the text colour, said here.** Every input was
 *   already set that way, but by the legacy `input` element rule reaching
 *   into this component; now that rule stops at legacy markup (K-15), the
 *   component keeps the look it shipped with. Whether a field holding a
 *   sentence should be monospace is open (web/REFERENCE.md Q-11).
 */
function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "h-9 w-full min-w-0 rounded-md border border-input bg-transparent px-3 py-1 font-mono text-base text-foreground tabular-nums shadow-xs transition-[color,box-shadow] selection:bg-primary selection:text-primary-foreground file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground placeholder:text-muted-foreground disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm dark:bg-input/30",
        "aria-invalid:border-destructive",
        className
      )}
      {...props}
    />
  )
}

export { Input }
