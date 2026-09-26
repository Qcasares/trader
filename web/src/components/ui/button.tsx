import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { Slot } from "radix-ui"

import { cn } from "@/lib/utils"

/**
 * Three changes from the stock new-york button. `shadcn add` would undo each
 * of them, which is why web/DESIGN.md K-8 keeps a log:
 *
 * - **No focus ring.** Stock draws its own focus indicator — the border turns
 *   `ring` and a 3px box-shadow of `ring` at 50% (20% or 40% on
 *   `destructive`) — and removes the outline to make room for it. The ring
 *   measured 1.50–2.94:1 against the card, under the 3:1 a focus indicator
 *   needs, so it goes, and the button takes the one indicator every control
 *   here has: the 2px accent outline at 2px offset from `globals.css` (owner
 *   decision OD-3, A-4).
 * - **`transition-colors`, not `transition-all`.** `all` animated the
 *   outline's width in with it, so the indicator grew for 150ms before it
 *   was there.
 * - **A ghost or outline button rendered as a link is the link colour**
 *   (`[a&]:text-primary`; `primary` is the accent, which every other link
 *   is). Stock leaves both variants' text to whatever holds them, which suits
 *   an action and not a way out: the back links, the per-row "view" and the
 *   header "Configuration" are links, and had the link colour from the
 *   legacy `a` rule until that rule stopped reaching components (K-15),
 *   after which they read as plain words. As a `<button>` — the sheet's
 *   trigger, a form's Cancel — each keeps the text colour, and on hover
 *   every one of them still turns to it.
 */
const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 rounded-md text-sm font-medium whitespace-nowrap transition-colors disabled:pointer-events-none disabled:opacity-50 aria-invalid:border-destructive [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-primary/90",
        destructive:
          "bg-destructive text-white hover:bg-destructive/90 dark:bg-destructive/60",
        outline:
          "border bg-background shadow-xs [a&]:text-primary hover:bg-accent hover:text-accent-foreground dark:border-input dark:bg-input/30 dark:hover:bg-input/50",
        secondary:
          "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        ghost:
          "[a&]:text-primary hover:bg-accent hover:text-accent-foreground dark:hover:bg-accent/50",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-4 py-2 has-[>svg]:px-3",
        xs: "h-6 gap-1 rounded-md px-2 text-xs has-[>svg]:px-1.5 [&_svg:not([class*='size-'])]:size-3",
        sm: "h-8 gap-1.5 rounded-md px-3 has-[>svg]:px-2.5",
        lg: "h-10 rounded-md px-6 has-[>svg]:px-4",
        icon: "size-9",
        "icon-xs": "size-6 rounded-md [&_svg:not([class*='size-'])]:size-3",
        "icon-sm": "size-8",
        "icon-lg": "size-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant = "default",
  size = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot.Root : "button"

  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
