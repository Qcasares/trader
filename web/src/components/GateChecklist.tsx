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
      <span
        className={criterion.met ? "pill pill-good" : "pill pill-bad"}
        aria-label={criterion.met ? "met" : "not met"}
      >
        {criterion.met ? "met" : "unmet"}
      </span>
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

export function GateChecklist({ gate }: { gate: GateResult }) {
  const unmet = gate.criteria.filter((c) => !c.met).length;
  return (
    <section className="card">
      <div className="card-head spread">
        <h2>
          Gate: {gate.from_stage_name} → {gate.to_stage_name}
        </h2>
        <span className={gate.passed ? "pill pill-good" : "pill pill-warn"}>
          {gate.passed ? "passed" : `${unmet} unmet`}
        </span>
      </div>

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
    </section>
  );
}

/**
 * Marks a field a model wrote.
 *
 * The same convention `src/llm/commentary.py` established: model output is
 * output, never input. A hypothesis card drafted by a model and one written by
 * a person are stored identically and must not *look* identical.
 */
export function AiBadge({ origin }: { origin: "model" | "operator" }) {
  if (origin !== "model") return null;
  return (
    <span className="badge" title="Drafted by a model. Never a trading input.">
      AI-authored
    </span>
  );
}
