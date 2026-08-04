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
 */

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { CircleSlash, Settings2 } from "lucide-react";
import { ApiError, api, type JobSummary, type SystemStatus } from "@/lib/api";
import { StatusBadge, jobStatus, livenessStatus } from "@/components/StatusBadge";
import { fmtInstant } from "@/lib/format";
import { DataTable } from "@/components/DataTable";
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

/** Job statuses, loudest first. The order the status column sorts in. */
const JOB_ORDER = ["failed", "expired", "running", "queued", "succeeded"];

/** Heartbeat age, in the largest unit that still reads as a number. */
function fmtAge(seconds: number): string {
  if (!Number.isFinite(seconds)) return "—";
  if (seconds < 90) return `${Math.round(seconds)}s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)}m`;
  return `${Math.round(seconds / 3600)}h`;
}

/**
 * One of the three independent conditions a live order needs.
 *
 * `open` is the dangerous direction here, so an open gate is the loud badge.
 * The usual instinct — green for "on" — would make the configuration that can
 * move real money the calm-looking one.
 */
function Gate({ name, open, note }: { name: string; open: boolean; note: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-line py-2 last:border-b-0">
      <div className="min-w-0">
        <div className="font-mono text-sm">{name}</div>
        <div className="text-xs text-ink-muted text-pretty">{note}</div>
      </div>
      <StatusBadge status={open ? "blocked" : "settled"}>
        {open ? "open" : "closed"}
      </StatusBadge>
    </div>
  );
}

export default function SystemPage() {
  const router = useRouter();
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [nextStatus, nextJobs] = await Promise.all([
        api.systemStatus(),
        api.jobs(),
      ]);
      setStatus(nextStatus);
      setJobs(nextJobs);
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
    const timer = setInterval(refresh, 5000);
    return () => clearInterval(timer);
  }, [refresh]);

  const engage = async () => {
    if (!reason.trim()) return;
    setBusy(true);
    try {
      setStatus(await api.kill(reason.trim()));
      setReason("");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const release = async () => {
    setBusy(true);
    try {
      setStatus(await api.resume("released from control plane"));
      setConfirm("");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (!status) return <p className="muted">Loading system status…</p>;

  const noWorkerAlive = status.workers.every((w) => w.stale);

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

      {error && <p className="banner banner-bad">{error}</p>}

      <div className="grid gap-3 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              Trading
              <StatusBadge status={status.trading_enabled ? "settled" : "blocked"}>
                {status.trading_enabled ? "enabled" : "halted"}
              </StatusBadge>
            </CardTitle>
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

            {status.trading_enabled ? (
              <div className="space-y-2">
                <Label htmlFor="kill-reason">
                  Reason for halting (recorded in the audit log)
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
            />
            <Gate
              name="ALPACA_ALLOW_LIVE"
              open={status.alpaca_allow_live}
              note="The allow-live gate, set separately from the one above."
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
              <StatusBadge status={status.broker_configured ? "settled" : "mute"}>
                {status.broker_configured ? "present" : "absent"}
              </StatusBadge>
            </div>
            {(!status.live_trading_enabled || !status.alpaca_allow_live) && (
              <p className="mt-3 mb-0 text-sm text-settled">
                No real order can be placed in this configuration.
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="mt-3">
        <CardHeader>
          <CardTitle>Workers</CardTitle>
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
            <Table>
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
          <CardTitle>Jobs</CardTitle>
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
                // free text, and a sort button implies there is one.
                className: "max-w-[36ch] text-blocked text-pretty",
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
