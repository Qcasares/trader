"use client";

/**
 * System control plane.
 *
 * The kill switch is the only control here that has to work when the operator
 * is stressed, so it is one button with one required field. Re-enabling is
 * deliberately harder than stopping: the API demands a typed confirmation
 * string, which this page makes the operator produce rather than pre-filling.
 *
 * Rebuilt on shadcn primitives. Two things the rewrite is careful about, both
 * of which a stock component set would have got wrong:
 *
 * - **The gates are reported separately, never combined.** Live orders need
 *   three independent conditions and deriving any one from another is a
 *   weakening. Three rows, three answers, no summary pill.
 * - **A worker's liveness comes from heartbeat age, not its stored status.**
 *   That column is only ever written `'alive'`, so rendering it directly showed
 *   a green badge for a process that died an hour ago.
 *
 * Three more, since the owner's decisions of 2026-09-26:
 *
 * - **Red means live money reachable, and nothing else, on this page's safety
 *   controls** (web/DESIGN.md OD-2, C-12). A halted kill switch is the safe
 *   state and reads as a strong amber "stopped". It used to be the same red
 *   `✕` as an open live-trading gate, so the page an operator reads under
 *   stress drew the safest condition it has and the most dangerous one alike —
 *   and a fresh deployment, which the migration leaves halted, opened on a red
 *   chip. The mapping lives in `StatusBadge` (`killSwitchStatus`,
 *   `liveGateStatus`); this page asks for a state, never a colour.
 * - **A switch that cannot be read is not shown as its last value.** The kill
 *   switch fails closed on the server; the page used to fail open, keeping the
 *   last good reading on screen, chips and all, under an error banner. When a
 *   refresh fails now, the kill switch and the gates read "not read", beside
 *   what they last were, and everything else is marked stale with the time it
 *   was read (DESIGN.md G-2, E-13).
 * - **The page keeps its heading in every state.** A first load that failed
 *   used to leave "Loading system status…" on screen for ever, with no `h1`
 *   and no error; it now says what failed (E-9, T-5).
 */

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { CircleSlash, Settings2 } from "lucide-react";
import {
  ApiError,
  api,
  type JobSummary,
  type SystemStatus,
  type VenueCancel,
  type VenueCancelVenue,
} from "@/lib/api";
import {
  StatusBadge,
  jobStatus,
  killSwitchStatus,
  liveGateStatus,
  livenessStatus,
  type Status,
} from "@/components/StatusBadge";
import { fmtAge, fmtInstant } from "@/lib/format";
import { DataTable } from "@/components/DataTable";
import { Skeleton } from "@/components/Skeleton";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const CONFIRM_PHRASE = "ENABLE TRADING";

/** How often the page re-reads the control plane. */
const POLL_MS = 5000;

/** Job statuses, loudest first. The order the status column sorts in. */
const JOB_ORDER = ["failed", "expired", "running", "queued", "succeeded"];

/** One answer from the API, kept whole so its parts cannot come from two reads. */
interface Reading {
  status: SystemStatus;
  jobs: JobSummary[];
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

/**
 * What became of the cancel this stop queued at the venue, in a sentence that
 * says what is still true there.
 *
 * The switch has two halves: the flag stops new orders, and a worker job
 * cancels this system's own orders already sent (src/worker/kill_job.py) —
 * not the account's whole book, so an order placed at the venue by hand is
 * left alone. Until that job has succeeded at every venue, "stopped" must not
 * read as "nothing in flight", the one belief an operator reaching for this
 * switch must not hold. So the state decides the sentence before anything
 * else does; only a confirmed cancel says none of this system's orders is
 * open, and says it of the present, not of a count one attempt made; a venue
 * that was not reached is named; and a cancel no worker is alive to run says
 * so. test_web_components.py ties these to the route.
 */
function venueCancelSentence(
  cancel: VenueCancel | null | undefined,
  noWorkerAlive: boolean,
): string {
  const noWorker = noWorkerAlive
    ? " No worker is running, so it will not finish until one does."
    : "";
  if (cancel == null || cancel.status === "not_queued") {
    return (
      "No cancel was queued at the venue for this stop, so any order this " +
      "system placed that is still open there stands until it fills or is " +
      "cancelled at the venue."
    );
  }
  switch (cancel.status) {
    case "succeeded":
      return cancel.venues.length === 0
        ? "No deployment of the operator's trades at a venue, so there was nothing to cancel."
        : cancel.venues.map(venueSentence).join(" ");
    case "failed":
      return (
        "The worker could not confirm that this system's orders at the venue " +
        `were cancelled: ${sentence(cancel.error ?? "no reason was recorded")} ` +
        "Orders there may stand; check the venue."
      );
    case "running":
      return (
        "The worker is cancelling this system's orders still open at the " +
        `venue, attempt ${cancel.attempts} of ${cancel.max_attempts}.${noWorker}`
      );
    case "queued":
      return cancel.error && cancel.attempts < cancel.max_attempts
        ? `Cancelling at the venue failed on attempt ${cancel.attempts} of ` +
            `${cancel.max_attempts} and will be tried again: ` +
            `${sentence(cancel.error)}${noWorker}`
        : "The worker has been asked to cancel this system's orders still " +
            `open at the venue.${noWorker}`;
    case "cancelled":
      return (
        "The cancel at the venue was withdrawn before it finished, so any " +
        "order this system placed that is still open there stands."
      );
  }
}

function venueSentence(venue: VenueCancelVenue): string {
  if (!venue.reached) {
    return (
      `The ${venue.mode} venue was not reached (${venue.reason}), so any ` +
      "order this system placed there stands."
    );
  }
  const foreign =
    venue.foreign_open === 0
      ? ""
      : ` ${venue.foreign_open} open order${venue.foreign_open === 1 ? "" : "s"} ` +
        "this system did not place, left alone.";
  return (
    `None of this system's orders is open at the ${venue.mode} venue; the ` +
    `orders page shows which were cancelled and which filled.${foreign}`
  );
}

/**
 * The state of a safety condition — or, when the page cannot read it now,
 * that it is not read, beside what it last was.
 *
 * Never the last value on its own: "enabled" on a page that has lost the API
 * is a control plane defaulting to "go" because it cannot find out, which is
 * the one thing the switch behind it is built never to do.
 */
function SafetyState({
  status,
  word,
  stale,
}: {
  status: Status;
  word: string;
  stale: boolean;
}) {
  if (!stale) return <StatusBadge status={status}>{word}</StatusBadge>;
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <StatusBadge status="unknown">not read</StatusBadge>
      <span className="text-xs font-normal text-ink-muted">last read: {word}</span>
    </span>
  );
}

/**
 * One of the three independent conditions a live order needs. Open is the
 * dangerous direction, and `liveGateStatus` makes it the one red chip here.
 */
function Gate({
  name,
  open,
  note,
  stale,
}: {
  name: string;
  open: boolean;
  note: string;
  stale: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-line py-2 last:border-b-0">
      <div className="min-w-0">
        <div className="font-mono text-sm">{name}</div>
        <div className="text-xs text-ink-muted text-pretty">{note}</div>
      </div>
      <SafetyState
        status={liveGateStatus(open)}
        word={open ? "open" : "closed"}
        stale={stale}
      />
    </div>
  );
}

export default function SystemPage() {
  const router = useRouter();
  const [reading, setReading] = useState<Reading | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  // A failed engage or release is not a failed read: the state on screen may
  // still be current, so it is said where the control is and marks nothing
  // stale.
  const [actionError, setActionError] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [status, jobs] = await Promise.all([api.systemStatus(), api.jobs()]);
      setReading({ status, jobs, readAt: new Date().toISOString() });
      setFailure(null);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.isUnauthorized) {
        router.push("/login");
        return;
      }
      const message = err instanceof Error ? err.message : String(err);
      // Kept from the first failure of a run of them, so the banner says how
      // long the states have been unread, and is not re-announced on every
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
   * The switch answers a change with its new state, which is shown at once;
   * then the whole page is re-read, so nothing on it claims a time it was not
   * read at.
   */
  const adopt = (status: SystemStatus) => {
    setReading((previous) => (previous === null ? previous : { ...previous, status }));
    void refresh();
  };

  const engage = async () => {
    if (!reason.trim()) return;
    setBusy(true);
    try {
      adopt(await api.kill(reason.trim()));
      setReason("");
      setActionError(null);
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const release = async () => {
    setBusy(true);
    try {
      adopt(await api.resume("released from control plane"));
      setConfirm("");
      setActionError(null);
    } catch (err: unknown) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const stale = reading !== null && failure !== null;

  return (
    <>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="mb-1">System</h1>
          <p className="m-0 text-base text-ink-muted">
            Control plane and worker health.
          </p>
        </div>
        <Button variant="outline" size="sm" asChild>
          <Link href="/system/configuration">
            <Settings2 aria-hidden="true" />
            Configuration
          </Link>
        </Button>
      </div>

      {reading === null ? (
        failure ? (
          <p className="banner banner-bad" role="alert">
            The control plane could not be read: {sentence(failure.message)} The
            kill switch and the gates are not shown, because there is nothing
            current to show.
          </p>
        ) : (
          <Skeleton rows={6} label="Loading system status" />
        )
      ) : (
        <Loaded
          reading={reading}
          failure={stale ? failure : null}
          actionError={actionError}
          reason={reason}
          setReason={setReason}
          confirm={confirm}
          setConfirm={setConfirm}
          busy={busy}
          engage={engage}
          release={release}
        />
      )}
    </>
  );
}

function Loaded({
  reading,
  failure,
  actionError,
  reason,
  setReason,
  confirm,
  setConfirm,
  busy,
  engage,
  release,
}: {
  reading: Reading;
  /** Set when the latest refresh failed: everything below is as of `readAt`. */
  failure: Failure | null;
  actionError: string | null;
  reason: string;
  setReason: (value: string) => void;
  confirm: string;
  setConfirm: (value: string) => void;
  busy: boolean;
  engage: () => void;
  release: () => void;
}) {
  const { status, jobs, readAt } = reading;
  const stale = failure !== null;
  const noWorkerAlive = status.workers.every((w) => w.stale);
  const bothGatesOpen = status.live_trading_enabled && status.alpaca_allow_live;

  return (
    <>
      {failure ? (
        <p className="banner banner-warn" role="status" data-stale="true">
          <strong>Stale.</strong> Refreshing has failed since{" "}
          {fmtInstant(failure.since)}: {sentence(failure.message)} Everything
          below was read at {fmtInstant(readAt)}. The kill switch and the gates
          read &ldquo;not read&rdquo; rather than their last value, because
          either may have changed since.
        </p>
      ) : null}

      <div className="grid gap-3 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex flex-wrap items-center gap-2">
              Trading
              <SafetyState
                status={killSwitchStatus(status.trading_enabled)}
                word={status.trading_enabled ? "enabled" : "stopped"}
                stale={stale}
              />
            </CardTitle>
            {/*
              What "stopped" means, in the worker's terms: the two job kinds
              that can reach a venue fail on the switch, and nothing else does
              (src/worker/main.py). Said because the state is safe, and a safe
              state an operator cannot interpret is one they will "fix".

              And what became of the orders already sent. `POST /system/kill`
              also queues a worker job that cancels them at the venue
              (src/api/routers/system.py, src/worker/kill_job.py); the second
              sentence reports that job, never assumes it, and says positions
              stay. test_web_components.py ties this to the route.
            */}
            {!status.trading_enabled && !stale ? (
              <>
                <p className="m-0 text-sm text-pretty">
                  No live decision is taken and no order is submitted, to paper
                  or to live, until trading is re-enabled. Backtests, marks and
                  reconciliation carry on.
                </p>
                <p className="m-0 text-sm text-pretty">
                  {venueCancelSentence(status.venue_cancel, noWorkerAlive)}{" "}
                  Positions already held are not closed.
                </p>
              </>
            ) : null}
            {status.kill_reason ? (
              <p className="m-0 text-sm text-ink-muted">{status.kill_reason}</p>
            ) : null}
          </CardHeader>
          <CardContent>
            {status.updated_at && (
              <p className="mt-0 mb-3 text-xs text-ink-muted">
                last changed by {status.updated_by} at{" "}
                {fmtInstant(status.updated_at)}
              </p>
            )}

            {actionError ? (
              <p className="banner banner-bad" role="alert">
                {actionError}
              </p>
            ) : null}

            {status.trading_enabled ? (
              <div className="space-y-2">
                <Label htmlFor="kill-reason">
                  Reason for stopping (recorded in the audit log)
                </Label>
                <Input
                  id="kill-reason"
                  value={reason}
                  placeholder="e.g. reconciliation mismatch on SPY"
                  onChange={(e) => setReason(e.target.value)}
                />
                <Button
                  variant="destructive"
                  onClick={engage}
                  disabled={busy || !reason.trim()}
                >
                  <CircleSlash aria-hidden="true" />
                  Engage kill switch
                </Button>
              </div>
            ) : (
              <div className="space-y-2">
                <Label htmlFor="kill-confirm">
                  Type <code>{CONFIRM_PHRASE}</code> to re-enable trading
                </Label>
                <Input
                  id="kill-confirm"
                  value={confirm}
                  placeholder={CONFIRM_PHRASE}
                  onChange={(e) => setConfirm(e.target.value)}
                />
                <Button
                  onClick={release}
                  disabled={busy || confirm !== CONFIRM_PHRASE}
                >
                  Re-enable trading
                </Button>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Gates on a live order</CardTitle>
            <p className="m-0 text-sm text-ink-muted text-pretty">
              Three independent conditions, plus the kill switch. Deriving any
              one from another is a weakening, so each is reported on its own.
            </p>
          </CardHeader>
          <CardContent>
            <Gate
              name="LIVE_TRADING_ENABLED"
              open={status.live_trading_enabled}
              note="The environment gate."
              stale={stale}
            />
            <Gate
              name="ALPACA_ALLOW_LIVE"
              open={status.alpaca_allow_live}
              note="The allow-live gate, set separately from the one above."
              stale={stale}
            />
            <div className="flex items-baseline justify-between gap-3 border-b border-line py-2">
              <div className="min-w-0">
                <div className="font-mono text-sm">deployment mode</div>
                <div className="text-xs text-ink-muted text-pretty">
                  The third condition. Not reported by this endpoint, so it is
                  shown as unknown rather than guessed from the two above.
                </div>
              </div>
              <StatusBadge status="unknown">not reported</StatusBadge>
            </div>
            <div className="flex items-baseline justify-between gap-3 pt-2">
              <span className="text-sm text-ink-muted">Broker credentials</span>
              <SafetyState
                status={status.broker_configured ? "settled" : "mute"}
                word={status.broker_configured ? "present" : "absent"}
                stale={stale}
              />
            </div>
            {bothGatesOpen ? (
              <p className="mt-3 mb-0 text-sm text-blocked text-pretty">
                {stale ? "When last read, both" : "Both"} environment gates{" "}
                {stale ? "were" : "are"} open: a deployment in live mode reaches
                real money whenever trading is enabled.
              </p>
            ) : (
              <p className="mt-3 mb-0 text-sm text-settled">
                {stale
                  ? "When last read, no real order could be placed in this configuration."
                  : "No real order can be placed in this configuration."}
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="mt-3">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            Workers
            {stale ? <StatusBadge status="unknown">stale</StatusBadge> : null}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {/*
            Keyed off whether any worker is *live*, not whether the table has
            rows. A heartbeat row persists after the process dies, so "has ever
            checked in" is a different question from "is running now".
          */}
          {noWorkerAlive && (
            <p className="banner banner-warn">
              <strong>No worker is alive.</strong>{" "}
              {status.workers.length === 0
                ? "None has ever checked in."
                : "The last heartbeat is stale."}{" "}
              Backtests will queue and never run, no end-of-day mark will be
              written, and both halting limits go inert while that is true. A
              dead worker produces no error anywhere — absence of action looks
              exactly like nothing needing to be done.
            </p>
          )}
          {status.workers.length > 0 && (
            <Table label="Workers">
              <TableHeader>
                <TableRow>
                  <TableHead>Worker</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Last seen</TableHead>
                  <TableHead className="text-right">Age</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {status.workers.map((worker) => (
                  <TableRow key={worker.worker_id}>
                    <TableCell className="font-mono">{worker.worker_id}</TableCell>
                    <TableCell>
                      <StatusBadge status={livenessStatus(worker.stale)}>
                        {worker.stale ? "no heartbeat" : worker.status}
                      </StatusBadge>
                    </TableCell>
                    <TableCell className="text-ink-muted">
                      {fmtInstant(worker.last_seen)}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {fmtAge(worker.age_seconds)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card className="mt-3">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            Jobs
            {stale ? <StatusBadge status="unknown">stale</StatusBadge> : null}
          </CardTitle>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(status.jobs).map(([key, count]) => (
              <StatusBadge key={key} status={jobStatus(key)}>
                {key}: {count}
              </StatusBadge>
            ))}
          </div>
        </CardHeader>
        <CardContent>
          <DataTable
            rows={jobs}
            getRowId={(job) => job.id}
            filterPlaceholder="Filter jobs"
            empty="No jobs yet."
            initialSort={[{ id: "created", desc: true }]}
            columns={[
              {
                id: "kind",
                header: "Kind",
                sortable: true,
                sortValue: (job) => job.kind,
                className: "font-mono",
                cell: (job) => job.kind,
              },
              {
                id: "status",
                header: "Status",
                sortable: true,
                // Sorted by how much attention it deserves, not alphabetically.
                // `failed` before `queued` is the order an operator scans in;
                // alphabetical would bury it under `expired` and `queued`.
                sortValue: (job) => JOB_ORDER.indexOf(job.status),
                cell: (job) => (
                  <StatusBadge status={jobStatus(job.status)}>
                    {job.status}
                  </StatusBadge>
                ),
              },
              {
                id: "attempts",
                header: "Attempts",
                sortable: true,
                sortValue: (job) => job.attempts,
                headerClassName: "text-right",
                className: "text-right font-mono tabular-nums",
                cell: (job) => `${job.attempts}/${job.max_attempts}`,
              },
              {
                id: "error",
                header: "Error",
                // Deliberately unsortable: there is no meaningful order over
                // free text, and a sort button implies there is one. Wraps:
                // table cells are `nowrap`, and an error set on one line ran
                // 176px into the next column and printed over its timestamp.
                className: "max-w-[36ch] whitespace-normal text-blocked text-pretty",
                cell: (job) => job.error ?? "",
              },
              {
                id: "created",
                header: "Created",
                sortable: true,
                sortValue: (job) => job.created_at ?? "",
                className: "text-ink-muted whitespace-nowrap",
                cell: (job) => fmtInstant(job.created_at),
              },
            ]}
          />
        </CardContent>
      </Card>
    </>
  );
}
