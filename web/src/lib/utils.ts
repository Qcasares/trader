import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

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
