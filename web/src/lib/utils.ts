import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/**
 * tailwind-merge, told the font sizes this project declares.
 *
 * globals.css names its type scale in `@theme inline` (`--text-xs` to
 * `--text-xl`). The default config recognises `base` and the t-shirt names as
 * sizes, and nothing else, so it reads any other `text-*` as a colour. For
 * `text-body`, the body-prose size (OD-8), that meant `cn("text-body",
 * "text-ink-muted")` dropped the size as a colour overridden by a later one,
 * while `cn("text-sm", "text-body")` kept both sizes and left the winner to
 * source order. Registering the name in the `text` theme scale, the one the
 * font-size group reads, makes it merge as a size. A size name the default
 * does not know belongs here, and `tests/unit/test_design_tokens.py` fails
 * until it is.
 */
const twMerge = extendTailwindMerge({
  extend: { theme: { text: ["body"] } },
});

/**
 * Merge class names, with later Tailwind utilities beating earlier ones.
 *
 * The shadcn convention, and the reason every component below takes a
 * `className`: a caller can override a utility without the component needing a
 * prop for it, and without two conflicting classes both landing in the DOM and
 * leaving the winner to source order.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
