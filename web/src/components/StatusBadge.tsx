import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/**
 * The one place a domain state becomes a colour, and the one chip.
 *
 * Every page in this app renders status, and until now each decided its own
 * mapping inline — `job.status === "succeeded" ? "pill-good" : ...` in one
 * file, a slightly different ternary in the next. That is how "not measured"
 * ends up grey on one page and amber on another, and the whole argument for the
 * amber is that it is *consistent enough to be trusted*. So the mapping lives
 * here and the pages ask for a state rather than a colour. Since the owner's
 * decision of 2026-09-26 (web/DESIGN.md OD-3) it is also the only chip: the
 * legacy `.pill` and `.badge` classes, which drew the same states in a second
 * type system, are gone.
 *
 * The six states are deliberately not a rating scale:
 *
 * - `settled`  — measured, and it met the bar. The quietest thing here.
 * - `blocked`  — measured, and it did not; refused or failed. The loudest.
 *   On a safety control it means one thing only: live money reachable.
 * - `caution`  — measured, not met *yet*, and not an alarm: a promotion gate
 *   still waiting on evidence somebody can go and produce. `unknown`'s amber
 *   under a ▲, because it asks to be read and it was measured.
 * - `unknown`  — **not measured.** Not a middling result and not a zero.
 * - `mute`     — real, reported, and simply not interesting.
 * - `stopped`  — a safety switch that is off. Known, safe, and not to be
 *   missed: an amber plate, where every other state is a neutral chip.
 *
 * `unknown` is the one that earns this component's existence. An unmeasured
 * probability of backtest overfitting rendered as `0.00` is the single most
 * flattering lie this system could tell, and an unmeasured one rendered in the
 * quietest grey available is the same lie told more politely. If you find
 * yourself reaching for `mute` to mean "we don't know", reach for `unknown`.
 * And never reach for `unknown` to mean "stopped" or "not yet": a halted kill
 * switch and an unmet gate are not unanswered questions, and none of the
 * three may look like another.
 */
export type Status =
  | "settled"
  | "caution"
  | "unknown"
  | "blocked"
  | "mute"
  | "stopped";

export function StatusBadge({
  status,
  children,
  className,
  title,
}: {
  status: Status;
  children: React.ReactNode;
  className?: string;
  /** A longer reading, for hover. Never the only place the meaning is. */
  title?: string;
}) {
  return (
    <Badge variant={status} className={cn("font-mono", className)} title={title}>
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
 *
 * `failed` and `expired` stay `blocked`. The owner reserved red on a *safety
 * control* for live money reachable (OD-2); whether that reaches past the
 * safety controls is open (web/DESIGN.md C-5, Q-33), and moving a failure to
 * amber would render it in the colour of "not measured".
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

/**
 * The kill switch.
 *
 * Halted is `stopped`, never `blocked`. It is the safe state — the worker
 * makes no live decision and submits no order to any venue while it holds —
 * and it is also the state the migration leaves a fresh deployment in, so the
 * page an operator reads most often was painting its safest condition in the
 * colour of danger. The owner's decision of 2026-09-26 (web/DESIGN.md OD-2,
 * C-12): red is reserved for live money reachable, and a halted switch is a
 * strong amber "stopped", prominent and not alarming.
 */
export function killSwitchStatus(tradingEnabled: boolean): Status {
  return tradingEnabled ? "settled" : "stopped";
}

/**
 * One of the independent conditions a live order needs.
 *
 * Open is the dangerous direction, so an open gate is `blocked`: on a safety
 * control that is the one state red is kept for (OD-2, C-12). The usual
 * instinct — green for "on" — would make the configuration that can move real
 * money the calm-looking one.
 */
export function liveGateStatus(open: boolean): Status {
  return open ? "blocked" : "settled";
}

/**
 * A promotion gate in the AI programme, taken whole — not a live-order gate.
 *
 * One that has not passed is `caution`, the amber ▲ "N unmet" it shipped as
 * (`.pill-warn`), and not `blocked`. Each unmet criterion inside it stays
 * `blocked`, because that criterion was measured and refused; the gate is the
 * sum of them, and its state is "not yet". Nothing is failing that needs an
 * operator now, and the way forward is to produce the evidence. The chip went
 * red once, on its way onto this component, and red is the owner's to extend
 * past the safety controls, which the owner has not done (web/DESIGN.md C-5,
 * Q-33).
 */
export function promotionGateStatus(passed: boolean): Status {
  return passed ? "settled" : "caution";
}
