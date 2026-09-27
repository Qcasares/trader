"use client";

/**
 * The AI programme overview.
 *
 * Four things live here: is it on, is its process alive, what is in the
 * pipeline, and what it has actually done lately.
 *
 * Since the owner's decisions of 2026-09-27 (OD-6, OD-7) they sit in an
 * asymmetric grid, grouped rather than stacked. The main column is whether it
 * is on and what holds a promotion back — the ceiling, the findings, the
 * configuration still TBD — beside the controls those govern. The side column
 * is the runner: is its process alive, and what did it last do. The board
 * runs the full width beneath, since it scrolls sideways by design.
 *
 * Each caveat sits above the figure it qualifies (K-7), and a runner that is
 * not alive qualifies the switch: "enabled" means nothing while no process
 * acts on it. So that warning opens the Autonomy card, above the switch and
 * the "Run a pass now" it would ignore, rather than sitting in the runner's
 * card — which, one column on a phone, comes after all of them. It once sat
 * there, and an operator on a phone read "enabled" and the controls first and
 * the only sign of a dead process below them.
 *
 * Two things move, and both report state: the runner's badge pulses only
 * while its heartbeat is alive, this page's last read succeeded and that read
 * is younger than two polls; and the board's columns rise into place once,
 * when it first loads.
 *
 * The reading is /system's, since 2026-09-27 (web/DESIGN.md G-2, E-13): one
 * answer, kept whole with the time it arrived. A refresh that fails marks it
 * stale — a banner says since when and as of when, the switch reads "not
 * read" beside what it last was, the runner's card and the board say "stale",
 * and nothing pulses — where it used to keep "✓ enabled" and a breathing
 * "✓ alive" under a bare error, a switch that fails closed on the server
 * failing open on the screen. An action that fails is not a read that did,
 * and is said beside the controls without marking anything stale. And the
 * page keeps its heading in every state (E-9), where a first load that failed
 * left a banner and nothing else.
 *
 * The autonomy switch follows the same asymmetry as the kill switch. Turning
 * the programme off takes one click; turning it on takes a typed phrase. The
 * reason is the same too: a control that is equally easy in both directions
 * gets flipped by accident in the direction that costs money.
 *
 * The board shows stages 0 to 8. Shadow operation, stage 3, is built; broker
 * paper trading and the production stages after it are not, so their gates
 * report the missing capability rather than a verdict. Stages 4 and up are
 * rendered anyway, and the page says why nothing gets past them rather than
 * leaving an operator to wonder. It used to say shadow-mode operation was the
 * thing not built — the one stage past validation that is.
 *
 * Rebuilt on shadcn primitives, matching `/system` and `/backtests`. Five
 * things the rewrite is careful about:
 *
 * - **Runner liveness comes from `isAlive` (`lib/heartbeat.ts`), never from
 *   the row's staleness or its stored status alone**, and is drawn by the
 *   same `livenessStatus` the worker table on `/system` uses — one decision
 *   and one mapping, not two that can drift apart. Alive is fresh *and*
 *   saying so: a runner that shut down cleanly stamps a fresh `last_seen`
 *   beside `'stopped'`, and read by its age alone it showed "✓ alive" for a
 *   minute after it stopped.
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
 *   correct. It scrolls sideways in a focusable region named "Pipeline, scrolls
 *   sideways" while
 *   it is wider than its card (L-6, A-7), by the table scroller's own measure
 *   (`useOverflows`): with no candidate on it there was nothing inside to tab
 *   to, and a keyboard could not scroll it at all.
 * - **The synthetic-evidence tooltip is now visible text**, not a `title`
 *   attribute nothing keyboard-only can reach — the same fix `/portfolio`
 *   made for its own honesty hints.
 *
 * Prose is the body's 15px (OD-8, T-11): the intro, what a card explains, a
 * banner. Chips, metric keys, labels, the ceiling's hint and the board's
 * cards keep their 11–13px steps.
 *
 * The footer link row to the hypothesis ledger, findings, report and config
 * pages is dropped: `AppNav`'s sidebar already lists all four under
 * "Programme", so the row only duplicated navigation that now exists
 * everywhere else in the app too.
 */

import { useCallback, useEffect, useRef, useState } from "react";
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
import {
  SafetyState,
  StatusBadge,
  livenessStatus,
} from "@/components/StatusBadge";
import { AiBadge } from "@/components/GateChecklist";
import { fmtAge, fmtInstant } from "@/lib/format";
import { useFresh } from "@/lib/fresh";
import { isAlive, livenessWord } from "@/lib/heartbeat";
import { useOverflows } from "@/lib/overflow";
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

/** How often the page re-reads the programme. */
const POLL_MS = 10000;

/**
 * The last stage whose operation is built: shadow mode. The gates out of the
 * stages above it report the missing capability rather than a verdict
 * (`_MISSING_CAPABILITY` in src/programme/gates.py).
 */
const LAST_BUILT_STAGE = 3;

/** One answer from the API, kept whole so its parts cannot come from two reads. */
interface Reading {
  status: ProgrammeStatus;
  board: PipelineBoard;
  /** When the answer arrived. The states are current as of this, not as of now. */
  readAt: string;
}

/** Refreshes that have not produced a reading, since the first of them. */
interface Failure {
  message: string;
  since: string;
}

function sentence(message: string): string {
  const trimmed = message.trim();
  return /[.!?]$/.test(trimmed) ? trimmed : `${trimmed}.`;
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
  const [reading, setReading] = useState<Reading | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  // A failed switch, ceiling or pass request is not a failed read: the state
  // on screen may still be current, so it is said beside the controls and
  // marks nothing stale.
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  // Refreshes can overlap — a poll, the one after a ceiling change or a
  // switch — and settle in any order. An outcome applies only if no later
  // refresh has settled already, so a read that timed out cannot mark stale a
  // page a newer read has brought up to date, nor a slow answer put an older
  // one back.
  const asked = useRef(0);
  const settled = useRef(0);

  const refresh = useCallback(async () => {
    const turn = ++asked.current;
    try {
      const [status, board] = await Promise.all([
        api.programmeStatus(),
        api.pipeline(),
      ]);
      if (turn < settled.current) return;
      settled.current = turn;
      setReading({ status, board, readAt: new Date().toISOString() });
      setFailure(null);
    } catch (err: unknown) {
      if (turn < settled.current) return;
      settled.current = turn;
      if (err instanceof ApiError && err.isUnauthorized) {
        router.push("/login");
        return;
      }
      const message = err instanceof Error ? err.message : String(err);
      // Kept from the first failure of a run of them, so the banner says how
      // long the reading has been stale, and is not re-announced on every
      // failed poll.
      setFailure((previous) =>
        previous !== null && previous.message === message
          ? previous
          : { message, since: new Date().toISOString() },
      );
    }
  }, [router]);

  useEffect(() => {
    void refresh();
    const timer = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  /**
   * The switch answers a change with the programme's state, which is newer
   * than every refresh already in flight; taking a turn for it drops any of
   * those that read the switch before the change and would land after it,
   * putting the old state back. Then the whole page is re-read, so nothing on
   * it claims a time it was not read at.
   */
  const adopt = (next: ProgrammeStatus) => {
    settled.current = ++asked.current;
    setReading((previous) =>
      previous === null ? previous : { ...previous, status: next },
    );
    void refresh();
  };

  const enable = async () => {
    setBusy(true);
    try {
      adopt(
        await api.setProgrammeEnabled(
          true,
          reason.trim() || "enabled from the control plane",
          confirm,
        ),
      );
      setConfirm("");
      setReason("");
      setActionError(null);
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const disable = async () => {
    setBusy(true);
    try {
      adopt(
        await api.setProgrammeEnabled(
          false,
          reason.trim() || "disabled from the control plane",
        ),
      );
      setReason("");
      setActionError(null);
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const setCeiling = async (next: number) => {
    if (!reading) return;
    // Raising needs the phrase; lowering needs nothing. Prompting rather than
    // pre-filling, for the same reason the kill switch does it: a confirmation
    // the UI supplies confirms nothing.
    let confirm = "";
    if (next > reading.status.max_auto_stage) {
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
      setActionError(null);
      // `refresh` marks the reading stale itself when it cannot read the page,
      // and clears the mark when it can; the action's own outcome is said
      // apart from that, so a ceiling that was set never hides a page that
      // then failed to read itself.
      await refresh();
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : String(err));
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
      setActionError(null);
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="mb-1">AI programme</h1>
          <p className="intro m-0 text-body text-ink-muted">
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

      {reading === null ? (
        failure ? (
          <p className="banner banner-bad" role="alert">
            The programme could not be read: {sentence(failure.message)} Its
            switch and its runner are not shown, because there is nothing
            current to show.
          </p>
        ) : (
          <Skeleton rows={6} label="Loading the programme" />
        )
      ) : (
        <Loaded
          reading={reading}
          failure={failure}
          actionError={actionError}
          note={note}
          reason={reason}
          setReason={setReason}
          confirm={confirm}
          setConfirm={setConfirm}
          busy={busy}
          enable={enable}
          disable={disable}
          setCeiling={setCeiling}
          tick={tick}
        />
      )}
    </>
  );
}

function Loaded({
  reading,
  failure,
  actionError,
  note,
  reason,
  setReason,
  confirm,
  setConfirm,
  busy,
  enable,
  disable,
  setCeiling,
  tick,
}: {
  reading: Reading;
  /** Set when the latest refresh failed: everything below is as of `readAt`. */
  failure: Failure | null;
  actionError: string | null;
  note: string | null;
  reason: string;
  setReason: (value: string) => void;
  confirm: string;
  setConfirm: (value: string) => void;
  busy: boolean;
  enable: () => void;
  disable: () => void;
  setCeiling: (next: number) => void;
  tick: () => void;
}) {
  const { status, board, readAt } = reading;
  const stale = failure !== null;
  // Younger than two polls, the runner's pulse's third condition. A refresh
  // that fails marks the page `stale`; one still waiting marks nothing until
  // it times out, and a throttled tab or a sleeping laptop polls late or not
  // at all, so the pulse needs the reading to be recent, not merely unrefuted
  // (web/DESIGN.md M-10r).
  const fresh = useFresh(readAt, 2 * POLL_MS);
  // Measured, so the board is a focusable, named region while it is wider
  // than its card, and nothing but a board when it is not (L-6, A-7).
  const boardRef = useRef<HTMLDivElement>(null);
  const boardScrolls = useOverflows(boardRef);

  const runner = status.runner;
  const byStage = new Map<number, Candidate[]>();
  for (const candidate of board.candidates) {
    byStage.set(candidate.stage, [...(byStage.get(candidate.stage) ?? []), candidate]);
  }

  return (
    <>
      {failure ? (
        <p className="banner banner-warn" role="status" data-stale="true">
          <strong>Stale.</strong> Refreshing has failed since{" "}
          {fmtInstant(failure.since)}: {sentence(failure.message)} Everything
          below was read at {fmtInstant(readAt)}. The programme&apos;s switch
          reads &ldquo;not read&rdquo; rather than its last value, because it
          may have changed since.
        </p>
      ) : null}
      <div className="summary-grid">
        {/*
          Main: the switch, the ceiling and what holds a promotion back, beside
          the controls they govern. Side: the runner — is its process alive, and
          what did it last do. Wide: the board, which scrolls sideways by design.
          Source order is reading order, so a phone shows the switch first.
        */}
        <div className="summary-main">
          <Card>
            <CardHeader>
              <CardTitle className="flex flex-wrap items-center gap-2">
                Autonomy
                <SafetyState
                  status={status.enabled ? "settled" : "mute"}
                  word={status.enabled ? "enabled" : "disabled"}
                  stale={stale}
                />
              </CardTitle>
              <p className="m-0 max-w-prose text-body text-ink-muted text-pretty">
                The switch fails closed. A missing row, an unreadable value or a
                database error all read as disabled, in the API and in the runner
                alike — a control that defaults to &quot;go&quot; when it cannot
                determine the answer is not a control.
              </p>
            </CardHeader>
            <CardContent>
              {/*
                Each caveat sits above the figure it qualifies (K-7). A runner
                that is not alive qualifies the whole card — "enabled" above,
                the switch and "Run a pass now" below — so its warning comes
                first, here, and not in the runner's card beside: one column on
                a phone, that card follows every control in this one. Not alive
                is `isAlive`'s: a heartbeat gone stale, and a runner that shut
                down cleanly, whose row is fresh for a minute after it stopped.
              */}
              {runner === null ? (
                <p className="banner banner-warn">
                  No runner has ever checked in. The programme will appear
                  enabled and do nothing until one does.
                </p>
              ) : !isAlive(runner) ? (
                <p className="banner banner-warn">
                  The runner is not alive ({livenessWord(runner)}), last heard
                  from {fmtAge(runner.age_seconds)} ago. The programme will
                  appear enabled and do nothing until the process is back.
                </p>
              ) : null}

              {status.blocking_findings > 0 ? (
                <p className="banner banner-warn">
                  {status.blocking_findings} open finding
                  {status.blocking_findings === 1 ? "" : "s"} from a role holding a
                  veto {status.blocking_findings === 1 ? "is" : "are"} blocking
                  promotions. <Link href="/programme/findings">Review them</Link>.
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

              <dl className="metric-grid">
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

              <p className="mt-3 max-w-prose text-body text-ink-muted text-pretty">
                Four independent things must agree before the runner promotes
                anything: the gate passes, the stage does not require an operator,
                the ceiling below permits it, and every specialist the panel was
                due to hear has reported. The ceiling cannot be raised past
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
                    <SelectTrigger
                      id="ceiling"
                      className="w-56"
                      aria-describedby={
                        status.max_auto_stage > 0 ? "ceiling-hint" : undefined
                      }
                    >
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
                {/* The ceiling's hint, tied to it: a hint keeps its small step
                    (T-11), however much it reads like a sentence. */}
                {status.max_auto_stage > 0 ? (
                  <p id="ceiling-hint" className="m-0 text-sm text-ink-muted">
                    Raising this needs a typed confirmation; lowering it does not.
                  </p>
                ) : null}
              </div>

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
                    {/* Wraps: the 224px field and the button beside it are
                        wider than a 390px phone leaves the card (E-1). */}
                    <div className="flex flex-wrap gap-2">
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
              {/*
                An action's answer is said under the controls that asked for
                it. At the top of the page it was 1,257px above "Run a pass
                now" on a 390px phone: announced, and off screen.
              */}
              {actionError ? (
                <p className="banner banner-bad mt-3 mb-0" role="alert">
                  {actionError}
                </p>
              ) : null}
              {note ? (
                <p className="banner banner-info mt-3 mb-0" role="status">
                  {note}
                </p>
              ) : null}
            </CardContent>
          </Card>
        </div>

        <div className="summary-side">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                Runner
                {stale ? <StatusBadge status="unknown">stale</StatusBadge> : null}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {/* The last thing in its card, so the grid's bottom margin, there
                  for what follows a grid elsewhere, would only pad the card.
                  A runner that is not alive is warned of in the Autonomy
                  card, above the controls it makes idle (K-7). */}
              <dl className="metric-grid mb-0">
                <Metric label="Runner">
                  {runner === null ? (
                    <StatusBadge status="unknown">never seen</StatusBadge>
                  ) : (
                    // The pulse claims "alive, as of a reading that is
                    // current": a runner that is not alive — stale, or shut
                    // down cleanly — stills it, and so does a refresh of this
                    // page that failed, and so does a reading two polls old,
                    // which a refresh that never came back leaves. A dead
                    // runner looks dead, and so does one this page can no
                    // longer see.
                    <StatusBadge
                      status={livenessStatus(runner)}
                      pulse={isAlive(runner) && !stale && fresh}
                    >
                      {livenessWord(runner)} ({fmtAge(runner.age_seconds)})
                    </StatusBadge>
                  )}
                </Metric>
                <Metric label="Last pass">
                  {status.last_run
                    ? `${status.last_run.status} · ${status.last_run.actions.length} actions`
                    : "none yet"}
                </Metric>
              </dl>
            </CardContent>
          </Card>
        </div>

        <div className="summary-wide">
          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <CardTitle className="flex items-center gap-2">
                  Pipeline
                  {stale ? <StatusBadge status="unknown">stale</StatusBadge> : null}
                </CardTitle>
                <span className="text-sm text-ink-muted">
                  {board.candidates.length} candidate
                  {board.candidates.length === 1 ? "" : "s"}
                </span>
              </div>
              <p className="m-0 max-w-prose text-body text-ink-muted text-pretty">
                Shadow operation, stage {LAST_BUILT_STAGE}, is built: a candidate
                there decides on a schedule against a disabled deployment and
                reaches no venue. Stages {LAST_BUILT_STAGE + 1} and above are shown
                for completeness — broker paper trading and the production stages
                are not built, so their gates report the missing capability rather
                than a verdict. Stage {board.first_human_gated_stage} onwards
                always needs an operator.
              </p>
            </CardHeader>
            <CardContent>
              {/*
                A sideways scroller, and so a focusable region named "Pipeline, scrolls
                sideways"
                while it is wider than its card (L-6, A-7): with no candidate
                on the board there is no link inside it to tab to, and axe
                reported it as a region a keyboard cannot scroll.
              */}
              <div
                ref={boardRef}
                className="flex snap-x snap-proximity gap-3 overflow-x-auto pb-2"
                tabIndex={boardScrolls ? 0 : undefined}
                role={boardScrolls ? "region" : undefined}
                aria-label={boardScrolls ? "Pipeline, scrolls sideways" : undefined}
              >
                {board.stages.map((stage) => {
                  const cards = byStage.get(stage.stage) ?? [];
                  const unreachable = stage.stage > LAST_BUILT_STAGE;
                  return (
                    // `enter-stagger`: each column's head and cards rise once,
                    // when the board first loads. No poll unmounts the board —
                    // a failed one keeps it, marked stale — columns are keyed
                    // by stage and cards by candidate id, so a card rises
                    // again only when it arrives in a column: a new candidate,
                    // or a promotion.
                    <div
                      key={stage.stage}
                      className="enter-stagger flex w-52 flex-none snap-start flex-col gap-2"
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
                        // An empty stage is a count of zero, said as a word: a
                        // lone dash is how this interface once wrote "unknown".
                        <p
                          className={
                            "m-0 text-xs " +
                            (unreachable ? "text-ink-faint" : "text-ink-muted")
                          }
                        >
                          none
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
        </div>
      </div>
    </>
  );
}
