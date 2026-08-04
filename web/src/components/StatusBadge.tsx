import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/**
 * The one place a domain state becomes a colour.
 *
 * Every page in this app renders status, and until now each decided its own
 * mapping inline — `job.status === "succeeded" ? "pill-good" : ...` in one
 * file, a slightly different ternary in the next. That is how "not measured"
 * ends up grey on one page and amber on another, and the whole argument for the
 * amber is that it is *consistent enough to be trusted*. So the mapping lives
 * here and the pages ask for a state rather than a colour.
 *
 * The four states are deliberately not a rating scale:
 *
 * - `settled`  — measured, and it met the bar. The quietest thing here.
 * - `blocked`  — measured, and it did not. The loudest.
 * - `unknown`  — **not measured.** Not a middling result and not a zero.
 * - `mute`     — real, reported, and simply not interesting.
 *
 * `unknown` is the one that earns this component's existence. An unmeasured
 * probability of backtest overfitting rendered as `0.00` is the single most
 * flattering lie this system could tell, and an unmeasured one rendered in the
 * quietest grey available is the same lie told more politely. If you find
 * yourself reaching for `mute` to mean "we don't know", reach for `unknown`.
 */
export type Status = "settled" | "unknown" | "blocked" | "mute";

export function StatusBadge({
  status,
  children,
  className,
}: {
  status: Status;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <Badge variant={status} className={cn("font-mono", className)}>
      {children}
    </Badge>
  );
}

/**
 * A job or run status, as the worker writes it.
 *
 * `queued` and `running` are `mute` rather than `unknown`: the system knows
 * exactly what is happening, it simply has not finished. Reserve `unknown` for
 * an answer nobody has.
 */
export function jobStatus(status: string): Status {
  if (status === "succeeded") return "settled";
  if (status === "failed" || status === "expired") return "blocked";
  return "mute";
}

/**
 * A worker heartbeat.
 *
 * Takes `stale` rather than the stored `status` column, which is only ever
 * written `'alive'` and therefore cannot report death. A dead worker produces
 * no error anywhere: backtests queue, no mark is written, and both halting
 * limits go inert, all silently. That is why staleness is the input.
 */
export function livenessStatus(stale: boolean): Status {
  return stale ? "blocked" : "settled";
}
