"use client";

/**
 * The findings register.
 *
 * The page has one job beyond listing: making it obvious which findings
 * actually stop something. Three conditions decide that — open, high or
 * critical, raised by a role holding a veto — and all three come from the API
 * rather than being restated here, so the badge this page draws and the
 * criterion the gate applies cannot drift apart.
 *
 * Closing is an operator act and nothing else can do it. That is enforced by a
 * CHECK constraint in the database, not by this form; the form exists because
 * the constraint has to be satisfiable by somebody.
 *
 * `accepted` sits beside `remediated` on purpose. Deciding to live with a known
 * defect is a real decision and it is not the same as fixing one, and a
 * register that collapsed them would describe a programme with no outstanding
 * problems.
 *
 * Rebuilt on `DataTable` for sorting and a free-text filter. Two things this
 * rebuild is careful about:
 *
 * - **A blocking finding sorts to the top, not the alphabet.** The severity
 *   column's `sortValue` is a rank, not the severity word: a finding that
 *   `blocks()` gets rank 0–3, everything else 10–13, so a "blocking" veto from
 *   a role that holds one always sorts above a bare "critical" from a role
 *   that does not, and severity breaks ties within each group. Ascending is
 *   the default direction throughout this app for exactly this shape of rank
 *   (see `JOB_ORDER` on the system page) — the worst thing is rank zero, so
 *   the first click needs no override.
 * - **Prose stays prose.** `detail_md`, `remediation` and the close form do
 *   not fit a table cell, so the table is the sortable, filterable list of
 *   every finding and selecting one opens its full record — and the closing
 *   form — beneath it, rather than cramming a form into a row.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ApiError, api, type Finding, type FindingsPage } from "@/lib/api";
import { Skeleton } from "@/components/Skeleton";
import { DataTable } from "@/components/DataTable";
import { StatusBadge, type Status } from "@/components/StatusBadge";
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

/** Lower is more urgent. Blocking findings occupy 0–3, everything else 10–13. */
const SEVERITY_URGENCY: Record<Finding["severity"], number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

/**
 * Severity onto the four house states. `unknown` stays reserved for "not
 * measured" — a severity is a real, assessed magnitude, never an absence —
 * so `high`/`critical` map to `blocked` and `low`/`medium` to `mute`. The
 * word itself still tells the two apart within each pair; the badge draws the
 * attention split the four states can actually carry.
 */
const SEVERITY_STATUS: Record<Finding["severity"], Status> = {
  low: "mute",
  medium: "mute",
  high: "blocked",
  critical: "blocked",
};

const FINDING_STATUS: Record<Finding["status"], Status> = {
  open: "mute",
  remediated: "settled",
  accepted: "mute",
  withdrawn: "mute",
};

const CLOSURES = ["remediated", "accepted", "withdrawn"] as const;

export default function FindingsPage() {
  const router = useRouter();
  const [page, setPage] = useState<FindingsPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [onlyOpen, setOnlyOpen] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [closing, setClosing] = useState(false);
  const [closure, setClosure] = useState<string>("remediated");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setPage(await api.findings({ onlyOpen }));
      setError(null);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.isUnauthorized) {
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [router, onlyOpen]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const close = async (ref: string) => {
    if (!note.trim()) {
      setError("A note is required. A closure without one is not a record.");
      return;
    }
    setBusy(true);
    try {
      await api.closeFinding(ref, closure, note.trim());
      setClosing(false);
      setNote("");
      await refresh();
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (error && !page) return <p className="banner banner-bad">{error}</p>;
  if (!page) return <Skeleton rows={5} label="Loading the register" />;

  const vetoRoles = new Set(page.veto_roles);
  const blockingSeverities = new Set(page.blocking_severities);
  const blocks = (finding: Finding) =>
    finding.status === "open" &&
    blockingSeverities.has(finding.severity) &&
    vetoRoles.has(finding.raised_by);

  const blocking = page.findings.filter(blocks).length;
  const titles = new Map(page.roles.map((r) => [r.key, r.title]));
  const current = page.findings.find((f) => f.ref === selected) ?? null;

  return (
    <>
      <div className="mb-4">
        <h1 className="mb-1">Findings</h1>
        <p className="m-0 text-base text-ink-muted">
          A veto is a row, not an opinion. A finding blocks a promotion when it
          is open, at high or critical severity, and raised by a role holding a
          veto. Nothing reads its text to decide.
        </p>
      </div>

      {error ? <p className="banner banner-bad">{error}</p> : null}

      {blocking > 0 ? (
        <p className="banner banner-warn">
          {blocking} finding{blocking === 1 ? "" : "s"} currently blocking a
          promotion. Only an operator can close one — the database refuses any
          other closer, which is what stops a role retracting its own veto.
        </p>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Register</CardTitle>
          <div className="flex items-center gap-2">
            <input
              id="only-open"
              type="checkbox"
              checked={onlyOpen}
              onChange={(e) => setOnlyOpen(e.target.checked)}
              className="size-3.5"
            />
            <Label htmlFor="only-open" className="text-sm font-normal text-ink-muted">
              Open only
            </Label>
            {/*
              The old page showed this count and the rebuild dropped it. On a
              register whose whole purpose is an accurate tally of what is and
              is not outstanding, "how many are there" is the question the page
              answers, and a filter box is not a substitute for it.
            */}
            <span className="text-sm text-ink-muted">
              {page.findings.length} shown
            </span>
          </div>
        </CardHeader>
        <CardContent>
          <DataTable
            rows={page.findings}
            getRowId={(f) => f.ref}
            filterPlaceholder="Filter by ref, title or role"
            empty="Nothing on the register. That is either a clean programme or a panel that has not run."
            initialSort={[{ id: "severity", desc: false }]}
            columns={[
              {
                id: "severity",
                header: "Severity",
                sortable: true,
                sortValue: (f) => (blocks(f) ? 0 : 10) + SEVERITY_URGENCY[f.severity],
                cell: (f) => (
                  <div className="flex flex-wrap items-center gap-1">
                    <StatusBadge status={SEVERITY_STATUS[f.severity]}>
                      {f.severity}
                    </StatusBadge>
                    {blocks(f) ? (
                      <StatusBadge status="blocked">blocking</StatusBadge>
                    ) : null}
                  </div>
                ),
              },
              {
                id: "ref",
                header: "Ref",
                sortable: true,
                sortValue: (f) => f.ref,
                className: "font-mono",
                cell: (f) => f.ref,
              },
              {
                id: "title",
                header: "Title",
                sortable: true,
                sortValue: (f) => f.title,
                cell: (f) => f.title,
              },
              {
                id: "raised_by",
                header: "Raised by",
                sortable: true,
                sortValue: (f) => titles.get(f.raised_by) ?? f.raised_by,
                cell: (f) => (
                  <span>
                    {titles.get(f.raised_by) ?? f.raised_by}
                    {vetoRoles.has(f.raised_by) ? (
                      <span className="text-ink-faint"> (holds a veto)</span>
                    ) : null}
                  </span>
                ),
              },
              {
                id: "status",
                header: "Status",
                sortable: true,
                sortValue: (f) => f.status,
                cell: (f) => (
                  <StatusBadge status={FINDING_STATUS[f.status]}>
                    {f.status}
                  </StatusBadge>
                ),
              },
              {
                id: "opened",
                header: "Opened",
                sortable: true,
                sortValue: (f) => f.opened_at,
                className: "text-ink-muted whitespace-nowrap",
                cell: (f) => fmtInstant(f.opened_at),
              },
              {
                id: "candidate",
                header: "Candidate",
                cell: (f) =>
                  f.candidate_id ? (
                    <Link href={`/programme/candidates/${f.candidate_id}`}>
                      view
                    </Link>
                  ) : (
                    "—"
                  ),
              },
              {
                id: "open_detail",
                header: "",
                className: "text-right",
                cell: (f) => (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setSelected(f.ref);
                      setClosing(false);
                      setNote("");
                    }}
                  >
                    view
                  </Button>
                ),
              },
            ]}
          />
        </CardContent>
      </Card>

      {current ? (
        <Card className="mt-3">
          <CardHeader>
            <CardTitle className="flex flex-wrap items-baseline gap-2">
              <span className="font-mono text-sm">{current.ref}</span>
              {current.title}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="m-0 text-sm text-ink-muted">
              Raised by {titles.get(current.raised_by) ?? current.raised_by}
              {vetoRoles.has(current.raised_by) ? " (holds a veto)" : ""} ·{" "}
              {fmtInstant(current.opened_at)}
            </p>

            {current.detail_md ? <p className="m-0">{current.detail_md}</p> : null}
            {current.remediation ? (
              <p className="m-0 text-sm text-ink-muted">
                <strong className="text-ink">Remediation:</strong>{" "}
                {current.remediation}
              </p>
            ) : null}

            {current.status !== "open" ? (
              <p className="m-0 text-sm text-ink-muted">
                Closed as {current.status} by {current.closed_by} —{" "}
                {current.close_note || "no note"}
              </p>
            ) : closing ? (
              <div className="flex flex-wrap items-end gap-2">
                <div className="space-y-1">
                  <Label htmlFor="closure">Closure</Label>
                  <Select value={closure} onValueChange={setClosure}>
                    <SelectTrigger id="closure" size="sm" className="w-40">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {CLOSURES.map((value) => (
                        <SelectItem key={value} value={value}>
                          {value}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="min-w-[24ch] flex-1 space-y-1">
                  <Label htmlFor="close-note">Note</Label>
                  <Input
                    id="close-note"
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="What changed, or why this is being accepted"
                  />
                </div>
                <Button onClick={() => close(current.ref)} disabled={busy}>
                  Close it
                </Button>
                <Button variant="ghost" onClick={() => setClosing(false)}>
                  Cancel
                </Button>
              </div>
            ) : (
              <Button size="sm" onClick={() => setClosing(true)}>
                Close this finding
              </Button>
            )}
          </CardContent>
        </Card>
      ) : null}
    </>
  );
}
