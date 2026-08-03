"use client";

/**
 * The AI programme overview.
 *
 * Three things live here, in the order an operator needs them: is it on, is its
 * process alive, and what is in the pipeline.
 *
 * The autonomy switch follows the same asymmetry as the kill switch. Turning
 * the programme off takes one click; turning it on takes a typed phrase. The
 * reason is the same too: a control that is equally easy in both directions
 * gets flipped by accident in the direction that costs money.
 *
 * The board shows stages 0 to 8. Stages 3 and up are rendered but cannot be
 * reached yet, and the page says so rather than leaving an operator to wonder
 * why nothing crosses the line.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ApiError,
  api,
  type Candidate,
  type PipelineBoard,
  type ProgrammeStatus,
} from "@/lib/api";
import { AiBadge } from "@/components/GateChecklist";

const CONFIRM_PHRASE = "ENABLE PROGRAMME";

/** The last stage this slice can evidence. Above it, gates report why not. */
const LAST_BUILT_STAGE = 3;

function fmtAge(seconds: number): string {
  if (!Number.isFinite(seconds)) return "—";
  if (seconds < 90) return `${Math.round(seconds)}s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)}m`;
  return `${Math.round(seconds / 3600)}h`;
}

function CandidateCard({ candidate }: { candidate: Candidate }) {
  return (
    <Link href={`/programme/candidates/${candidate.id}`} className="pipeline-card">
      <span className="mono pipeline-card-ref">{candidate.hypothesis_ref}</span>
      <span className="pipeline-card-title">{candidate.hypothesis_title}</span>
      <span className="muted mono pipeline-card-meta">
        {candidate.strategy_name}
      </span>
      <span className="row">
        <AiBadge origin={candidate.hypothesis_origin} />
        {candidate.evidence_is_synthetic ? (
          <span
            className="pill pill-warn"
            title="Synthetic evidence cannot pass the gate into shadow mode."
          >
            synthetic
          </span>
        ) : null}
        {candidate.status !== "active" ? (
          <span className="pill pill-mute">{candidate.status}</span>
        ) : null}
      </span>
    </Link>
  );
}

export default function ProgrammePage() {
  const router = useRouter();
  const [status, setStatus] = useState<ProgrammeStatus | null>(null);
  const [board, setBoard] = useState<PipelineBoard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [nextStatus, nextBoard] = await Promise.all([
        api.programmeStatus(),
        api.pipeline(),
      ]);
      setStatus(nextStatus);
      setBoard(nextBoard);
      setError(null);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.isUnauthorized) {
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [router]);

  useEffect(() => {
    void refresh();
    const timer = setInterval(refresh, 10000);
    return () => clearInterval(timer);
  }, [refresh]);

  const enable = async () => {
    setBusy(true);
    try {
      setStatus(
        await api.setProgrammeEnabled(
          true,
          reason.trim() || "enabled from the control plane",
          confirm,
        ),
      );
      setConfirm("");
      setReason("");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const disable = async () => {
    setBusy(true);
    try {
      setStatus(
        await api.setProgrammeEnabled(
          false,
          reason.trim() || "disabled from the control plane",
        ),
      );
      setReason("");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const setCeiling = async (next: number) => {
    if (!status) return;
    // Raising needs the phrase; lowering needs nothing. Prompting rather than
    // pre-filling, for the same reason the kill switch does it: a confirmation
    // the UI supplies confirms nothing.
    let confirm = "";
    if (next > status.max_auto_stage) {
      const typed = window.prompt(
        `Raising the autonomy ceiling to stage ${next} lets the runner promote ` +
          "candidates without an operator. Type RAISE AUTONOMY to confirm.",
      );
      if (typed === null) return;
      confirm = typed;
    }
    setBusy(true);
    try {
      await api.setAutonomy(next, "set from the control plane", confirm);
      await refresh();
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const tick = async () => {
    setBusy(true);
    setNote(null);
    try {
      await api.requestTick();
      setNote(
        "Pass requested. The runner picks it up within a few seconds; the API " +
          "never runs one inline.",
      );
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (error && !status) return <p className="banner banner-bad">{error}</p>;
  if (!status || !board) return <p className="muted">Loading the programme…</p>;

  const runner = status.runner;
  const byStage = new Map<number, Candidate[]>();
  for (const candidate of board.candidates) {
    byStage.set(candidate.stage, [...(byStage.get(candidate.stage) ?? []), candidate]);
  }

  return (
    <>
      <h1>AI programme</h1>
      <p className="subtitle">
        A third process proposes hypotheses, queues the experiments its gates
        require, and promotes candidates whose evidence is complete. It holds
        the only model client in this system and cannot reach an order.
      </p>

      {error ? <p className="banner banner-bad">{error}</p> : null}
      {note ? <p className="banner banner-info">{note}</p> : null}

      <section className="card">
        <div className="card-head spread">
          <h2>Autonomy</h2>
          <span className={status.enabled ? "pill pill-good" : "pill pill-mute"}>
            {status.enabled ? "enabled" : "disabled"}
          </span>
        </div>

        <p className="muted">
          The switch fails closed. A missing row, an unreadable value or a
          database error all read as disabled, in the API and in the runner
          alike — a control that defaults to &quot;go&quot; when it cannot
          determine the answer is not a control.
        </p>

        <dl className="metric-grid">
          <div className="metric">
            <dt>Runner</dt>
            <dd>
              {runner === null
                ? "never seen"
                : runner.stale
                  ? `stale (${fmtAge(runner.age_seconds)})`
                  : `alive (${fmtAge(runner.age_seconds)})`}
            </dd>
          </div>
          <div className="metric">
            <dt>Last pass</dt>
            <dd>
              {status.last_run
                ? `${status.last_run.status} · ${status.last_run.actions.length} actions`
                : "none yet"}
            </dd>
          </div>
          <div className="metric">
            <dt>Promotes without an operator up to</dt>
            <dd>
              {status.max_auto_stage === 0
                ? "nothing"
                : `stage ${status.max_auto_stage}`}
            </dd>
          </div>
          <div className="metric">
            <dt>Open findings</dt>
            <dd>
              {status.open_findings}
              {status.blocking_findings > 0
                ? ` (${status.blocking_findings} blocking)`
                : null}
            </dd>
          </div>
          <div className="metric">
            <dt>Configuration TBD</dt>
            <dd>{status.unknown_count}</dd>
          </div>
          <div className="metric">
            <dt>Critical TBD</dt>
            <dd>{status.critical_unknowns.length}</dd>
          </div>
        </dl>

        <p className="muted">
          Three independent things must agree before the runner promotes
          anything: the gate passes, the stage does not require an operator, and
          the ceiling below permits it. The ceiling cannot be raised past stage{" "}
          {status.autonomy_hard_cap} whatever is stored, because stage{" "}
          {status.autonomy_hard_cap + 1} is where the programme&apos;s own
          decision would expose capital.
        </p>

        <div className="row">
          <label htmlFor="ceiling" className="muted">
            Autonomy ceiling
          </label>
          <select
            id="ceiling"
            value={String(status.max_auto_stage)}
            onChange={(e) => void setCeiling(Number(e.target.value))}
            disabled={busy}
          >
            {Array.from(
              { length: status.autonomy_hard_cap + 1 },
              (_, stage) => (
                <option key={stage} value={stage}>
                  {stage === 0 ? "0 — promote nothing" : `up to stage ${stage}`}
                </option>
              ),
            )}
          </select>
          {status.max_auto_stage > 0 ? (
            <span className="muted">
              Raising this needs a typed confirmation; lowering it does not.
            </span>
          ) : null}
        </div>

        {status.blocking_findings > 0 ? (
          <p className="banner banner-warn">
            {status.blocking_findings} open finding
            {status.blocking_findings === 1 ? "" : "s"} from a role holding a
            veto {status.blocking_findings === 1 ? "is" : "are"} blocking
            promotions. <Link href="/programme/findings">Review them</Link>.
          </p>
        ) : null}

        {runner?.stale ? (
          <p className="banner banner-warn">
            The runner&apos;s heartbeat is {fmtAge(runner.age_seconds)} old. The
            programme will appear enabled and do nothing until the process is
            back.
          </p>
        ) : null}

        {status.critical_unknowns.length > 0 ? (
          <p className="banner banner-warn">
            Critical configuration still TBD:{" "}
            <span className="mono">{status.critical_unknowns.join(", ")}</span>.{" "}
            <Link href="/programme/config">Set it</Link> — nothing invents these
            values.
          </p>
        ) : null}

        <div className="row">
          <input
            type="text"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Reason (recorded in the audit log)"
          />
          {status.enabled ? (
            <button type="button" onClick={disable} disabled={busy}>
              Disable the programme
            </button>
          ) : (
            <>
              <input
                type="text"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                placeholder={`Type ${CONFIRM_PHRASE}`}
              />
              <button
                type="button"
                onClick={enable}
                disabled={busy || confirm !== CONFIRM_PHRASE}
              >
                Enable the programme
              </button>
            </>
          )}
          <button type="button" onClick={tick} disabled={busy}>
            Run a pass now
          </button>
        </div>
      </section>

      <section className="card">
        <div className="card-head spread">
          <h2>Pipeline</h2>
          <span className="muted">{board.candidates.length} candidates</span>
        </div>
        <p className="muted">
          Stages {LAST_BUILT_STAGE + 1} and above are shown for completeness and
          cannot be reached in this slice: shadow-mode operation is not built, so
          their gates report the missing capability rather than a verdict. Stage{" "}
          {board.first_human_gated_stage} onwards always needs an operator.
        </p>
        <div className="pipeline">
          {board.stages.map((stage) => {
            const cards = byStage.get(stage.stage) ?? [];
            return (
              <div className="pipeline-column" key={stage.stage}>
                <h3 className="pipeline-head">
                  <span className="mono">{stage.stage}</span> {stage.name}
                  {stage.stage >= board.first_human_gated_stage ? (
                    <span className="pill pill-warn">operator</span>
                  ) : null}
                </h3>
                {cards.length === 0 ? (
                  <p className="muted pipeline-empty">—</p>
                ) : (
                  cards.map((candidate) => (
                    <CandidateCard key={candidate.id} candidate={candidate} />
                  ))
                )}
              </div>
            );
          })}
        </div>
      </section>

      <p className="row">
        <Link href="/programme/hypotheses">Hypothesis ledger</Link>
        <Link href="/programme/findings">Findings</Link>
        <Link href="/programme/config">Programme configuration</Link>
      </p>
    </>
  );
}
