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
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ApiError, api, type Finding, type FindingsPage } from "@/lib/api";
import { Skeleton } from "@/components/Skeleton";

const SEVERITY_PILL: Record<Finding["severity"], string> = {
  low: "pill pill-mute",
  medium: "pill pill-mute",
  high: "pill pill-warn",
  critical: "pill pill-bad",
};

const STATUS_PILL: Record<Finding["status"], string> = {
  open: "pill pill-warn",
  remediated: "pill pill-good",
  accepted: "pill pill-mute",
  withdrawn: "pill pill-mute",
};

const CLOSURES = ["remediated", "accepted", "withdrawn"] as const;

export default function FindingsPage() {
  const router = useRouter();
  const [page, setPage] = useState<FindingsPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [onlyOpen, setOnlyOpen] = useState(false);
  const [closing, setClosing] = useState<string | null>(null);
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
      setClosing(null);
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

  return (
    <>
      <h1>Findings</h1>
      <p className="subtitle">
        A veto is a row, not an opinion. A finding blocks a promotion when it is
        open, at high or critical severity, and raised by a role holding a veto.
        Nothing reads its text to decide.
      </p>

      {error ? <p className="banner banner-bad">{error}</p> : null}

      {blocking > 0 ? (
        <p className="banner banner-warn">
          {blocking} finding{blocking === 1 ? "" : "s"} currently blocking a
          promotion. Only an operator can close one — the database refuses any
          other closer, which is what stops a role retracting its own veto.
        </p>
      ) : null}

      <div className="row">
        <label className="muted">
          <input
            type="checkbox"
            checked={onlyOpen}
            onChange={(e) => setOnlyOpen(e.target.checked)}
          />{" "}
          Open only
        </label>
        <span className="muted">{page.findings.length} shown</span>
      </div>

      {page.findings.length === 0 ? (
        <p className="muted">
          Nothing on the register. That is either a clean programme or a panel
          that has not run.
        </p>
      ) : (
        page.findings.map((finding) => (
          <section className="card" key={finding.ref}>
            <div className="card-head spread">
              <h2>
                <span className="mono">{finding.ref}</span> {finding.title}
              </h2>
              <span className="row">
                <span className={SEVERITY_PILL[finding.severity]}>
                  {finding.severity}
                </span>
                <span className={STATUS_PILL[finding.status]}>
                  {finding.status}
                </span>
                {blocks(finding) ? (
                  <span className="pill pill-bad">blocking</span>
                ) : null}
              </span>
            </div>

            <p className="muted">
              Raised by {titles.get(finding.raised_by) ?? finding.raised_by}
              {vetoRoles.has(finding.raised_by) ? " (holds a veto)" : ""} ·{" "}
              {finding.opened_at.slice(0, 10)}
              {finding.candidate_id ? (
                <>
                  {" · "}
                  <Link href={`/programme/candidates/${finding.candidate_id}`}>
                    candidate
                  </Link>
                </>
              ) : null}
            </p>

            {finding.detail_md ? <p>{finding.detail_md}</p> : null}
            {finding.remediation ? (
              <p className="muted">
                <strong>Remediation:</strong> {finding.remediation}
              </p>
            ) : null}

            {finding.status !== "open" ? (
              <p className="muted">
                Closed as {finding.status} by {finding.closed_by} —{" "}
                {finding.close_note || "no note"}
              </p>
            ) : closing === finding.ref ? (
              <div className="row">
                <select
                  value={closure}
                  onChange={(e) => setClosure(e.target.value)}
                  aria-label="Closure"
                >
                  {CLOSURES.map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
                <input
                  type="text"
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="What changed, or why this is being accepted"
                />
                <button
                  type="button"
                  onClick={() => close(finding.ref)}
                  disabled={busy}
                >
                  Close it
                </button>
                <button
                  type="button"
                  className="linklike"
                  onClick={() => setClosing(null)}
                >
                  Cancel
                </button>
              </div>
            ) : (
              <button type="button" onClick={() => setClosing(finding.ref)}>
                Close this finding
              </button>
            )}
          </section>
        ))
      )}
    </>
  );
}
