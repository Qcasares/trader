"use client";

/**
 * System control plane.
 *
 * The kill switch is the only control here that has to work when the operator
 * is stressed, so it is one button with one required field. Re-enabling is
 * deliberately harder than stopping: the API demands a typed confirmation
 * string, which this page makes the operator produce rather than pre-filling.
 */

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, api, type JobSummary, type SystemStatus } from "@/lib/api";

const CONFIRM_PHRASE = "ENABLE TRADING";

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

  return (
    <>
      <h1>System</h1>
      <p className="subtitle">Control plane and worker health.</p>

      {error && <p className="banner banner-bad">{error}</p>}

      <div className="card">
        <div className="spread">
          <div>
            <h3 style={{ margin: 0 }}>Trading</h3>
            <p style={{ margin: "4px 0 0" }}>
              <span
                className={`pill ${
                  status.trading_enabled ? "pill-good" : "pill-bad"
                }`}
              >
                {status.trading_enabled ? "enabled" : "halted"}
              </span>
              {status.kill_reason && (
                <span className="muted"> — {status.kill_reason}</span>
              )}
            </p>
            {status.updated_at && (
              <p className="muted" style={{ fontSize: 12, margin: "4px 0 0" }}>
                last changed by {status.updated_by} at {status.updated_at}
              </p>
            )}
          </div>
        </div>

        <p className="banner banner-info" style={{ marginTop: 14 }}>
          Live orders require <em>three independent</em> conditions, plus this
          kill switch. Deriving any one from another is a weakening, so each is
          reported separately. Environment gate (LIVE_TRADING_ENABLED):{" "}
          <strong>{status.live_trading_enabled ? "open" : "closed"}</strong>.
          Allow-live gate (ALPACA_ALLOW_LIVE):{" "}
          <strong>{status.alpaca_allow_live ? "open" : "closed"}</strong>.
          The third is the deployment&apos;s own mode. Broker credentials:{" "}
          <strong>{status.broker_configured ? "present" : "absent"}</strong>.
          {(!status.live_trading_enabled || !status.alpaca_allow_live) &&
            " No real order can be placed in this configuration."}
        </p>

        {status.trading_enabled ? (
          <div style={{ marginTop: 12 }}>
            <label>
              <span>Reason for halting (recorded in the audit log)</span>
              <input
                value={reason}
                placeholder="e.g. reconciliation mismatch on SPY"
                onChange={(e) => setReason(e.target.value)}
              />
            </label>
            <button
              className="danger"
              onClick={engage}
              disabled={busy || !reason.trim()}
            >
              Engage kill switch
            </button>
          </div>
        ) : (
          <div style={{ marginTop: 12 }}>
            <label>
              <span>
                Type <code>{CONFIRM_PHRASE}</code> to re-enable trading
              </span>
              <input
                value={confirm}
                placeholder={CONFIRM_PHRASE}
                onChange={(e) => setConfirm(e.target.value)}
              />
            </label>
            <button
              onClick={release}
              disabled={busy || confirm !== CONFIRM_PHRASE}
            >
              Re-enable trading
            </button>
          </div>
        )}
      </div>

      <h2>Workers</h2>
      <div className="card">
        {status.workers.length === 0 ? (
          <p className="banner banner-warn">
            <strong>No worker has checked in.</strong> Backtests will queue and
            never run. A dead worker produces no error anywhere — absence of
            action looks exactly like nothing needing to be done.
          </p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Worker</th>
                <th>Status</th>
                <th>Last seen</th>
              </tr>
            </thead>
            <tbody>
              {status.workers.map((worker) => (
                <tr key={worker.worker_id}>
                  <td>{worker.worker_id}</td>
                  <td>
                    <span className="pill pill-good">{worker.status}</span>
                  </td>
                  <td>{worker.last_seen}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <h2>Jobs</h2>
      <div className="card">
        <div className="row" style={{ marginBottom: 10 }}>
          {Object.entries(status.jobs).map(([key, count]) => (
            <span
              key={key}
              className={`pill ${key === "failed" ? "pill-bad" : "pill-mute"}`}
            >
              {key}: {count}
            </span>
          ))}
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Kind</th>
                <th>Status</th>
                <th className="num">Attempts</th>
                <th>Error</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {jobs.slice(0, 25).map((job) => (
                <tr key={job.id}>
                  <td>{job.kind}</td>
                  <td>
                    <span
                      className={`pill ${
                        job.status === "succeeded"
                          ? "pill-good"
                          : job.status === "failed"
                            ? "pill-bad"
                            : "pill-mute"
                      }`}
                    >
                      {job.status}
                    </span>
                  </td>
                  <td className="num">
                    {job.attempts}/{job.max_attempts}
                  </td>
                  <td className="error">{job.error ?? ""}</td>
                  <td>{job.created_at ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
