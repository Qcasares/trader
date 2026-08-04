import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { Slot } from "radix-ui"

import { cn } from "@/lib/utils"

/**
 * The stock shadcn variants, plus the three this system actually runs on.
 *
 * `settled` / `unknown` / `blocked` are not decoration and they are not
 * interchangeable with `default` / `secondary` / `destructive`:
 *
 * - **Every one carries a glyph as well as a hue**, so the colour could be
 *   removed entirely without losing the information. This interface is
 *   status-dense and roughly 8% of men have some red-green colour vision
 *   deficiency; a status conveyed by hue alone is a status those readers do not
 *   receive. The glyphs are set as `::before` content in `globals.css` with an
 *   empty alternative text (`content: "✓" / ""`), so assistive technology reads
 *   the label and not the decoration.
 *
 * - **`unknown` is amber, never grey.** "Not measured" is this system's most
 *   important state: rendering an unmeasured probability of backtest
 *   overfitting as a confident zero is the most flattering lie it could tell.
 *   shadcn's nearest fit is `secondary`, which is grey — quiet enough to be
 *   skimmed past, which is precisely the failure.
 *
 * - **`blocked` is the loudest and `settled` the quietest.** That inverts the
 *   usual dashboard instinct where success is the bright colour. An operator
 *   opens this to find out what is wrong.
 *
 * The chip surface stays neutral and the hue is carried by text and border.
 * Tinting each pill with its own hue made the 4.5:1 contrast target and the
 * lightness-separation target mutually unsatisfiable on dark — see the palette
 * note in `globals.css`.
 */
const badgeVariants = cva(
  "inline-flex w-fit shrink-0 items-center justify-center gap-1.5 overflow-hidden rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 [&>svg]:pointer-events-none [&>svg]:size-3",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-primary text-primary-foreground [a&]:hover:bg-primary/90",
        secondary:
          "border-transparent bg-secondary text-secondary-foreground [a&]:hover:bg-secondary/90",
        destructive:
          "border-transparent bg-destructive text-destructive-foreground [a&]:hover:bg-destructive/90",
        outline:
          "border-border text-foreground [a&]:hover:bg-accent [a&]:hover:text-accent-foreground",
        ghost: "border-transparent [a&]:hover:bg-accent [a&]:hover:text-accent-foreground",
        link: "border-transparent text-primary underline-offset-4 [a&]:hover:underline",

        /*
         * The glyph for these three is attached in `globals.css`, keyed off the
         * `data-variant` this component already sets. It is not a Tailwind
         * `before:content-[…]` utility because the glyph needs the two-value
         * form — `content: "✓" / ""` — whose second half is the alternative
         * text. Empty is what makes a screen reader announce the label and skip
         * the decoration, and a utility that emitted only the glyph would read
         * the status out twice, once as a symbol nobody asked for.
         */
        settled: "border-settled/40 bg-panel-2 text-settled",
        unknown: "border-unknown/40 bg-panel-2 text-unknown",
        blocked: "border-blocked/40 bg-panel-2 text-blocked",
        /** A state that is real, reported, and simply not interesting. */
        mute: "border-line bg-panel-2 text-ink-muted",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function Badge({
  className,
  variant = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"span"> &
  VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : "span"

  return (
    <Comp
      data-slot="badge"
      data-variant={variant}
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  )
}

export { Badge, badgeVariants }
