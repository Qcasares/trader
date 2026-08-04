"use client";

/**
 * The hypothesis ledger.
 *
 * Rejected hypotheses are listed alongside open ones and are never hidden by
 * default. That is not a UI preference: the proportion of failed experiments
 * retained is one of the programme's own integrity metrics, and a ledger that
 * quietly drops its failures reports that metric as perfect while being
 * worthless. The schema enforces the same thing — a DELETE on `hypotheses` is
 * a no-op — so the list and the store agree.
 *
 * `variants_tried` is shown on every row for the same reason a backtest count
 * is shown on the strategy list: a result selected from twenty attempts is not
 * the same evidence as a result from one, and the count is the only thing on
 * the page that says which happened.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ApiError, api, type Hypothesis } from "@/lib/api";
import { Skeleton } from "@/components/Skeleton";
import { AiBadge } from "@/components/GateChecklist";

const STATUS_PILL: Record<Hypothesis["status"], string> = {
  open: "pill pill-mute",
  accepted: "pill pill-good",
  rejected: "pill pill-bad",
  superseded: "pill pill-warn",
};

export default function HypothesisLedgerPage() {
  const router = useRouter();
  const [rows, setRows] = useState<Hypothesis[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>("");

  const refresh = useCallback(async () => {
    try {
      setRows(await api.hypotheses(filter || undefined));
      setError(null);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.isUnauthorized) {
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [router, filter]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (error && !rows) return <p className="banner banner-bad">{error}</p>;
  if (!rows) return <Skeleton rows={5} label="Loading the ledger" />;

  const rejected = rows.filter((r) => r.status === "rejected").length;

  return (
    <>
      <h1>Hypothesis ledger</h1>
      <p className="subtitle">
        Every idea this programme has had, including the ones that failed. The
        schema refuses to delete a row, so the record of what was tried cannot
        be tidied into a record of what worked.
      </p>

      {error ? <p className="banner banner-bad">{error}</p> : null}

      <div className="row">
        <label htmlFor="status-filter" className="muted">
          Status
        </label>
        <select
          id="status-filter"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        >
          <option value="">All ({rows.length})</option>
          <option value="open">Open</option>
          <option value="accepted">Accepted</option>
          <option value="rejected">Rejected</option>
          <option value="superseded">Superseded</option>
        </select>
        {filter === "" && rejected > 0 ? (
          <span className="muted">{rejected} rejected, shown deliberately</span>
        ) : null}
      </div>

      {rows.length === 0 ? (
        <p className="muted">
          Nothing yet. Enable the programme and run a pass, or add a card
          yourself.
        </p>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Ref</th>
                <th>Title</th>
                <th>Owner</th>
                <th className="num">Variants</th>
                <th>Status</th>
                <th>Proposed</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.ref}>
                  <td className="mono">
                    <Link href={`/programme/hypotheses/${row.ref}`}>{row.ref}</Link>
                  </td>
                  <td>
                    {row.title} <AiBadge origin={row.origin} />
                  </td>
                  <td className="muted">{row.owner || <span className="muted">unassigned</span>}</td>
                  <td
                    className="num mono"
                    title="How many configurations this idea has spawned. Every extra one is another draw."
                  >
                    {row.variants_tried}
                  </td>
                  <td>
                    <span className={STATUS_PILL[row.status]}>{row.status}</span>
                  </td>
                  <td className="muted mono">{row.created_at.slice(0, 10)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
