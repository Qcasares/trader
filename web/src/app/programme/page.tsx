"use client";

/**
 * The AI programme overview.
 *
 * Four things live here, in the order an operator needs them: is it on, is
 * its process alive, what is in the pipeline, and what it has actually done
 * lately.
 *
 * The autonomy switch follows the same asymmetry as the kill switch. Turning
 * the programme off takes one click; turning it on takes a typed phrase. The
 * reason is the same too: a control that is equally easy in both directions
 * gets flipped by accident in the direction that costs money.
 *
 * The board shows stages 0 to 8. Stages 3 and up are rendered but cannot be
 * reached yet, and the page says so rather than leaving an operator to wonder
 * why nothing crosses the line.
 *
 * Rebuilt on shadcn primitives, matching `/system` and `/backtests`. Five
 * things the rewrite is careful about:
 *
 * - **Runner liveness comes from `runner.stale`, never from a stored status
 *   string**, using the same `livenessStatus` helper the worker table on
 *   `/system` uses — one mapping from staleness to colour, not two that can
 *   drift apart.
 * - **Requested and effective autonomy are now both shown.** The API's
 *   `/autonomy` endpoint has always returned both — the stored request and
 *   the value clamped to the hard cap — but the previous page discarded the
 *   response and re-read only the effective figure. That made the distinction
 *   architecturally real and invisible at once; the confirmation banner below
 *   the selector now states both explicitly.
 * - **A run history was drafted and removed again.** `api.programmeRuns` and
 *   the `ProgrammeRun` type exist and no page uses them, and an operator asking
 *   "is this thing doing anything" wants the history rather than the single
 *   latest pass. But adding it here put a third request into a loop that polls
 *   every ten seconds for as long as the tab is open, which is a change in what
 *   this page costs rather than in how it looks. It belongs in its own change,
 *   scoped and argued on its own terms.
 * - **The pipeline board is rebuilt in Tailwind rather than the legacy
 *   `.pipeline`/`.pill`/`.card` classes**, to match the utility-first layout
 *   `/system`, `/backtests` and `/portfolio` already settled on. `.metric-grid`
 *   and the `.banner-*` classes are kept — they are dense, tuned, and already
 *   correct.
 * - **The synthetic-evidence tooltip is now visible text**, not a `title`
 *   attribute nothing keyboard-only can reach — the same fix `/portfolio`
 *   made for its own honesty hints.
 *
 * The footer link row to the hypothesis ledger, findings, report and config
 * pages is dropped: `AppNav`'s sidebar already lists all four under
 * "Programme", so the row only duplicated navigation that now exists
 * everywhere else in the app too.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Settings2 } from "lucide-react";
import {
  ApiError,
  api,
  type Candidate,
  type PipelineBoard,
  type ProgrammeStatus,
} from "@/lib/api";
import { Skeleton } from "@/components/Skeleton";
import { DataTable } from "@/components/DataTable";
import { StatusBadge, jobStatus, livenessStatus } from "@/components/StatusBadge";
import { AiBadge } from "@/components/GateChecklist";
import { fmtInstant } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const CONFIRM_PHRASE = "ENABLE PROGRAMME";

/** The last stage this slice can evidence. Above it, gates report why not. */
const LAST_BUILT_STAGE = 3;

function fmtAge(seconds: number): string {
  if (!Number.isFinite(seconds)) return "—";
  if (seconds < 90) return `${Math.round(seconds)}s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)}m`;
  return `${Math.round(seconds / 3600)}h`;
}

function Metric({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="metric">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function CandidateCard({ candidate }: { candidate: Candidate }) {
  return (
    <Link
      href={`/programme/candidates/${candidate.id}`}
      className="flex flex-col gap-1 rounded-md border border-line bg-panel p-3 no-underline transition-colors hover:border-line-strong hover:bg-panel-2"
    >
      <span className="font-mono text-xs text-ink-muted">
        {candidate.hypothesis_ref}
      </span>
      <span className="text-sm leading-snug text-ink">
        {candidate.hypothesis_title}
      </span>
      <span className="font-mono text-xs text-ink-muted">
        {candidate.strategy_name}
      </span>
      <div className="flex flex-wrap items-center gap-1.5">
        <AiBadge origin={candidate.hypothesis_origin} />
        {candidate.evidence_is_synthetic ? (
          <span className="flex items-center gap-1.5">
            <StatusBadge status="unknown">synthetic</StatusBadge>
            <span className="text-[11px] text-ink-faint">
              cannot reach shadow mode
            </span>
          </span>
        ) : null}
        {candidate.status !== "active" ? (
          <StatusBadge status="mute">{candidate.status}</StatusBadge>
        ) : null}
      </div>
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
      // The response carries both the value stored and the value the runner
      // will actually honour. They can differ — the hard cap clamps on the
      // way out, not on the way in — and both are worth saying rather than
      // just re-reading the effective figure on refresh.
      const result = await api.setAutonomy(next, "set from the control plane", confirm);
      setNote(
        result.requested === result.effective
          ? `Autonomy ceiling set to stage ${result.effective}.`
          : `Requested stage ${result.requested}; effective stage stays ` +
              `${result.effective}. The hard cap is stage ${result.hard_cap} and a ` +
              "stored request above it is never treated as the effective value.",
      );
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
  if (!status || !board) return <Skeleton rows={6} label="Loading the programme" />;

  const runner = status.runner;
  const byStage = new Map<number, Candidate[]>();
  for (const candidate of board.candidates) {
    byStage.set(candidate.stage, [...(byStage.get(candidate.stage) ?? []), candidate]);
  }

  return (
    <>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="mb-1">AI programme</h1>
          <p className="m-0 max-w-[68ch] text-base text-ink-muted text-pretty">
            A third process proposes hypotheses, queues the experiments its
            gates require, and promotes candidates whose evidence is complete.
            It holds the only model client in this system and cannot reach an
            order.
          </p>
        </div>
        <Button variant="outline" size="sm" asChild>
          <Link href="/programme/config">
            <Settings2 aria-hidden="true" />
            Configuration
          </Link>
        </Button>
      </div>

      {error ? <p className="banner banner-bad">{error}</p> : null}
      {note ? <p className="banner banner-info">{note}</p> : null}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            Autonomy
            <StatusBadge status={status.enabled ? "settled" : "mute"}>
              {status.enabled ? "enabled" : "disabled"}
            </StatusBadge>
          </CardTitle>
          <p className="m-0 text-sm text-ink-muted text-pretty">
            The switch fails closed. A missing row, an unreadable value or a
            database error all read as disabled, in the API and in the runner
            alike — a control that defaults to &quot;go&quot; when it cannot
            determine the answer is not a control.
          </p>
        </CardHeader>
        <CardContent>
          <dl className="metric-grid">
            <Metric label="Runner">
              {runner === null ? (
                <StatusBadge status="unknown">never seen</StatusBadge>
              ) : (
                <StatusBadge status={livenessStatus(runner.stale)}>
                  {runner.stale ? "stale" : "alive"} ({fmtAge(runner.age_seconds)})
                </StatusBadge>
              )}
            </Metric>
            <Metric label="Last pass">
              {status.last_run
                ? `${status.last_run.status} · ${status.last_run.actions.length} actions`
                : "none yet"}
            </Metric>
            <Metric label="Promotes without an operator up to">
              {status.max_auto_stage === 0
                ? "nothing"
                : `stage ${status.max_auto_stage}`}
            </Metric>
            <Metric label="Open findings">
              {status.open_findings}
              {status.blocking_findings > 0 ? (
                <span className="ml-2">
                  <StatusBadge status="blocked">
                    {status.blocking_findings} blocking
                  </StatusBadge>
                </span>
              ) : null}
            </Metric>
            <Metric label="Configuration TBD">{status.unknown_count}</Metric>
            <Metric label="Critical TBD">{status.critical_unknowns.length}</Metric>
          </dl>

          <p className="mt-3 text-sm text-ink-muted text-pretty">
            Three independent things must agree before the runner promotes
            anything: the gate passes, the stage does not require an operator,
            and the ceiling below permits it. The ceiling cannot be raised past
            stage {status.autonomy_hard_cap} whatever is stored, because stage{" "}
            {status.autonomy_hard_cap + 1} is where the programme&apos;s own
            decision would expose capital.
          </p>

          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-2">
              <Label htmlFor="ceiling">Autonomy ceiling</Label>
              <Select
                value={String(status.max_auto_stage)}
                onValueChange={(v) => void setCeiling(Number(v))}
                disabled={busy}
              >
                <SelectTrigger id="ceiling" className="w-56">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Array.from(
                    { length: status.autonomy_hard_cap + 1 },
                    (_, stage) => (
                      <SelectItem key={stage} value={String(stage)}>
                        {stage === 0 ? "0 — promote nothing" : `up to stage ${stage}`}
                      </SelectItem>
                    ),
                  )}
                </SelectContent>
              </Select>
            </div>
            {status.max_auto_stage > 0 ? (
              <p className="m-0 text-sm text-ink-muted">
                Raising this needs a typed confirmation; lowering it does not.
              </p>
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
              The runner&apos;s heartbeat is {fmtAge(runner.age_seconds)} old.
              The programme will appear enabled and do nothing until the
              process is back.
            </p>
          ) : null}

          {status.critical_unknowns.length > 0 ? (
            <p className="banner banner-warn">
              Critical configuration still TBD:{" "}
              <span className="mono">{status.critical_unknowns.join(", ")}</span>.{" "}
              <Link href="/programme/config">Set it</Link> — nothing invents
              these values.
            </p>
          ) : null}

          <div className="mt-4 flex flex-wrap items-end gap-3">
            <div className="space-y-2">
              <Label htmlFor="programme-reason">
                Reason (recorded in the audit log)
              </Label>
              <Input
                id="programme-reason"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Reason (recorded in the audit log)"
                className="w-72"
              />
            </div>
            {status.enabled ? (
              <Button variant="destructive" onClick={disable} disabled={busy}>
                Disable the programme
              </Button>
            ) : (
              <div className="space-y-2">
                <Label htmlFor="programme-confirm">
                  Type <code>{CONFIRM_PHRASE}</code> to enable
                </Label>
                <div className="flex gap-2">
                  <Input
                    id="programme-confirm"
                    value={confirm}
                    onChange={(e) => setConfirm(e.target.value)}
                    placeholder={CONFIRM_PHRASE}
                    className="w-56"
                  />
                  <Button
                    onClick={enable}
                    disabled={busy || confirm !== CONFIRM_PHRASE}
                  >
                    Enable the programme
                  </Button>
                </div>
              </div>
            )}
            <Button variant="outline" onClick={tick} disabled={busy}>
              Run a pass now
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card className="mt-3">
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle>Pipeline</CardTitle>
            <span className="text-sm text-ink-muted">
              {board.candidates.length} candidate
              {board.candidates.length === 1 ? "" : "s"}
            </span>
          </div>
          <p className="m-0 text-sm text-ink-muted text-pretty">
            Stages {LAST_BUILT_STAGE + 1} and above are shown for completeness
            and cannot be reached in this slice: shadow-mode operation is not
            built, so their gates report the missing capability rather than a
            verdict. Stage {board.first_human_gated_stage} onwards always
            needs an operator.
          </p>
        </CardHeader>
        <CardContent>
          <div className="flex snap-x snap-proximity gap-3 overflow-x-auto pb-2">
            {board.stages.map((stage) => {
              const cards = byStage.get(stage.stage) ?? [];
              const unreachable = stage.stage > LAST_BUILT_STAGE;
              return (
                <div
                  key={stage.stage}
                  className="flex w-52 flex-none snap-start flex-col gap-2"
                >
                  <h3
                    className={
                      "m-0 flex min-h-[34px] flex-wrap items-center gap-1.5 border-b border-line pb-2 text-xs font-medium tracking-[0.03em] uppercase " +
                      (unreachable ? "text-ink-faint" : "text-ink-muted")
                    }
                  >
                    <span className="font-mono normal-case tracking-normal">
                      {stage.stage}
                    </span>
                    {stage.name}
                    {stage.stage >= board.first_human_gated_stage ? (
                      <StatusBadge status="unknown">operator</StatusBadge>
                    ) : null}
                  </h3>
                  {cards.length === 0 ? (
                    <p
                      className={
                        "m-0 text-xs " +
                        (unreachable ? "text-ink-faint" : "text-ink-muted")
                      }
                    >
                      —
                    </p>
                  ) : (
                    cards.map((candidate) => (
                      <CandidateCard key={candidate.id} candidate={candidate} />
                    ))
                  )}
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

    </>
  );
}
