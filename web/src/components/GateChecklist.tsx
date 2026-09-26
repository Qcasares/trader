"use client";

/**
 * GateChecklist
 * -------------
 * A promotion gate, criterion by criterion.
 *
 * The design rule here is that an unmet criterion must say what would meet it.
 * A red cross next to "walk-forward robust" tells an operator they are blocked
 * and nothing else; the detail line tells them a study of *these* parameters is
 * missing, which is a thing they can go and do.
 *
 * Evidence is rendered as the table and row it came from rather than as a bare
 * number. Every figure in this programme traces to a row the deterministic
 * engine wrote, and showing the provenance beside the value is what makes that
 * claim checkable instead of merely asserted.
 */

import Link from "next/link";
import type { GateCriterion, GateEvidence, GateResult } from "@/lib/api";
import { StatusBadge, promotionGateStatus } from "@/components/StatusBadge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/** Where a piece of evidence can be looked at, when the UI has a page for it. */
function evidenceHref(evidence: GateEvidence): string | null {
  if (!evidence.row_id) return null;
  if (evidence.table === "backtest_runs") return `/backtests/${evidence.row_id}`;
  if (evidence.table === "experiments") {
    return `/programme/experiments/${evidence.row_id}`;
  }
  if (evidence.table === "hypotheses") {
    return `/programme/hypotheses/${evidence.row_id}`;
  }
  return null;
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function Criterion({ criterion }: { criterion: GateCriterion }) {
  const href = criterion.evidence ? evidenceHref(criterion.evidence) : null;
  const value = criterion.evidence ? renderValue(criterion.evidence.value) : "";
  return (
    <li className="gate-criterion">
      {/* The word is what a screen reader hears. It used to be overridden by
          an `aria-label` on a span with no role, which is not reliably read
          at all (axe: aria-prohibited-attr). */}
      <StatusBadge status={criterion.met ? "settled" : "blocked"}>
        {criterion.met ? "met" : "unmet"}
      </StatusBadge>
      <div>
        <p className="gate-criterion-desc">{criterion.description}</p>
        {criterion.detail ? (
          <p className="muted gate-criterion-detail">{criterion.detail}</p>
        ) : null}
        {criterion.evidence ? (
          <p className="muted mono gate-criterion-evidence">
            {href ? (
              <Link href={href}>{criterion.evidence.table}</Link>
            ) : (
              criterion.evidence.table
            )}
            {value ? ` · ${value}` : null}
          </p>
        ) : null}
      </div>
    </li>
  );
}

/**
 * The gate as a section of the candidate page, on the one card and the one
 * chip (owner decision of 2026-09-26, web/DESIGN.md OD-3, K-16). It used to be
 * the legacy `.card` with `.pill`s, which sat 0px under the shadcn card above
 * it with a different edge, a 19px title against the page's 14px ones, and
 * its states in a second type system.
 *
 * A gate that has not passed is `caution` — amber, under a ▲ — as it was
 * before the chip moved onto `StatusBadge`, where for a while it was the red
 * of a failure. Each unmet criterion in it is `blocked`: that one was measured
 * and refused. The gate as a whole is a promotion that has not happened yet,
 * and red on the candidate page is kept for a refused criterion, a rejected
 * candidate and a finding that blocks (`promotionGateStatus`; web/DESIGN.md
 * C-5, Q-33).
 */
export function GateChecklist({
  gate,
  className,
}: {
  gate: GateResult;
  className?: string;
}) {
  const unmet = gate.criteria.filter((c) => !c.met).length;
  return (
    <Card className={cn("mt-3", className)}>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center justify-between gap-2">
          <span>
            Gate: {gate.from_stage_name} → {gate.to_stage_name}
          </span>
          <StatusBadge status={promotionGateStatus(gate.passed)}>
            {gate.passed ? "passed" : `${unmet} unmet`}
          </StatusBadge>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {gate.passed && gate.requires_human ? (
          <p className="banner banner-warn">
            Every criterion is met, and this promotion still needs an operator.
            Stage {gate.to_stage} is where the programme&apos;s own decision would
            expose capital, and no model may make that decision.
          </p>
        ) : null}

        {!gate.passed ? (
          <p className="banner banner-info">
            A promotion confirms a passed gate. It cannot override a failed one —
            the API refuses, for an operator exactly as for the runner. The route
            forward is to produce the missing evidence.
          </p>
        ) : null}

        <ul className="gate-list">
          {gate.criteria.map((criterion) => (
            <Criterion key={criterion.id} criterion={criterion} />
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

/**
 * Marks a field a model wrote.
 *
 * The same convention `src/llm/commentary.py` established: model output is
 * output, never input. A hypothesis card drafted by a model and one written by
 * a person are stored identically and must not *look* identical.
 *
 * Drawn through the one chip, in the amber `StatusBadge` gives what nobody has
 * measured (web/DESIGN.md C-5, K-13); it was the legacy `.badge`, the same
 * amber in a second type system.
 */
export function AiBadge({ origin }: { origin: "model" | "operator" }) {
  if (origin !== "model") return null;
  return (
    <StatusBadge status="unknown" title="Drafted by a model. Never a trading input.">
      AI-authored
    </StatusBadge>
  );
}
