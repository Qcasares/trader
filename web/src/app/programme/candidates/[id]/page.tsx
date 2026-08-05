"use client";

/**
 * Candidate detail: the gate, the evidence, and the two controls.
 *
 * The promote button is the point of the page and it is deliberately weak. It
 * confirms a gate that has already passed; when the gate has not passed the API
 * answers 409 and lists what is missing, and this page shows that list rather
 * than a generic failure. An operator who disagrees with a gate has the same
 * route forward as the runner does: produce the evidence.
 *
 * Rejecting needs no gate and no confirmation, which is the same asymmetry the
 * kill switch has. Stopping should be frictionless; advancing should not.
 *
 * Rebuilt on shadcn primitives to match `system/page.tsx` and
 * `backtests/page.tsx`. `.gate-list`/`.gate-criterion` (rendered by the
 * unmodified `GateChecklist`, and reused directly here for Findings and
 * Specialist assessments), `.assumptions`/`.assumption-row`, `.table-scroll`
 * and `.no-data` are kept — they are tuned and this page's honesty behaviour
 * depends on them. What changed:
 *
 * - **Sections are `Card`s**, so this reads as the same instrument as every
 *   other rebuilt page rather than a fourth layout.
 * - **Status is `StatusBadge` everywhere a status is rendered** — scorecard
 *   rows, experiment conclusions, finding severity, assessment verdicts, the
 *   candidate's own lifecycle state — driven by local mappings onto the same
 *   four states (`settled`/`unknown`/`blocked`/`mute`) every other page uses,
 *   rather than a `pill-*` ternary local to this file. The scorecard's
 *   "not measured" cell keeps its own words rather than becoming a generic
 *   "no data": that is the label the API's own `observed_display` carries for
 *   the reason CLAUDE.md states — it is the metric whose whole purpose is to
 *   be unflattering, and the codebase reserves "not measured" for it
 *   specifically.
 * - **Experiments and shadow sessions are `DataTable`s**, sortable by the
 *   columns worth sorting on; an absent conclusion or equity figure sorts out
 *   of the ranking rather than settling at either end, matching the rule
 *   `backtests/page.tsx` already established for a missing Sharpe.
 * - **The underfunded-buy note is visible text, not a `title` tooltip.** "A
 *   real venue would have rejected these outright" is exactly the kind of
 *   statement this system exists to say out loud, not hide behind a hover a
 *   keyboard never reaches.
 * - **The decision form uses `Label`/`Input`/`Button`**, matching the kill
 *   switch on `system/page.tsx` down to the typed-confirmation pattern for
 *   the one control that should be hard to use by accident.
 */

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import {
  ApiError,
  api,
  type Candidate,
  type Experiment,
  type FindingsPage,
  type RoleAssessment,
  type Scorecard,
  type ShadowHistory,
} from "@/lib/api";
import { Skeleton } from "@/components/Skeleton";
import { AiBadge, GateChecklist } from "@/components/GateChecklist";
import { DataTable } from "@/components/DataTable";
import { StatusBadge, type Status } from "@/components/StatusBadge";
import { fmtInstant } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";

const CONFIRM_PHRASE = "PROMOTE";

/** A candidate's lifecycle state. Only `rejected` is a measured failure. */
const CANDIDATE_STATUS: Record<Candidate["status"], Status> = {
  active: "mute",
  held: "mute",
  rejected: "blocked",
  retired: "mute",
};

/** An experiment's conclusion, on the same four states every other page uses. */
const CONCLUSION_STATUS: Record<NonNullable<Experiment["conclusion"]>, Status> = {
  pass: "settled",
  fail: "blocked",
  inconclusive: "unknown",
};

/**
 * A scorecard row's status. `unknown` here is a direct pass-through of the
 * API's own vocabulary — an absent measurement, never a soft fail.
 */
const SCORE_STATUS: Record<Scorecard["rows"][number]["status"], Status> = {
  pass: "settled",
  fail: "blocked",
  unknown: "unknown",
};

/** A specialist's verdict. `concern` is amber, not a failure — it is a flag a finding would have to raise to actually block. */
const VERDICT_STATUS: Record<RoleAssessment["verdict"], Status> = {
  support: "settled",
  concern: "unknown",
  object: "blocked",
  abstain: "mute",
};

export default function CandidatePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const router = useRouter();
  const [candidate, setCandidate] = useState<Candidate | null>(null);
  const [assessments, setAssessments] = useState<RoleAssessment[]>([]);
  const [findings, setFindings] = useState<FindingsPage | null>(null);
  const [shadow, setShadow] = useState<ShadowHistory | null>(null);
  const [card, setCard] = useState<Scorecard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [unmet, setUnmet] = useState<string[]>([]);
  const [confirm, setConfirm] = useState("");
  const [rationale, setRationale] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [nextCandidate, nextAssessments, nextFindings, nextShadow, nextCard] =
        await Promise.all([
          api.candidate(id),
          api.assessments(id),
          api.findings({ candidateId: id }),
          api.shadow(id),
          api.scorecard(id),
        ]);
      setCandidate(nextCandidate);
      setAssessments(nextAssessments);
      setFindings(nextFindings);
      setShadow(nextShadow);
      setCard(nextCard);
      setError(null);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.isUnauthorized) {
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [id, router]);

  useEffect(() => {
    void load();
    const timer = setInterval(load, 15000);
    return () => clearInterval(timer);
  }, [load]);

  const promote = async () => {
    setBusy(true);
    setUnmet([]);
    try {
      await api.promote(id, rationale.trim());
      setConfirm("");
      setRationale("");
      await load();
    } catch (err: unknown) {
      // 409 means the gate has not passed. The detail carries the criteria, so
      // the page can say what is missing rather than "conflict".
      if (err instanceof ApiError && err.status === 409) {
        setError(
          "The gate has not passed. A promotion confirms a pass; it cannot " +
            "override a failure.",
        );
        setUnmet(
          (candidate?.gate?.criteria ?? [])
            .filter((c) => !c.met)
            .map((c) => c.description),
        );
      } else {
        setError(err instanceof Error ? err.message : String(err));
      }
      await load();
    } finally {
      setBusy(false);
    }
  };

  const close = async (action: "reject" | "hold") => {
    if (!rationale.trim()) {
      setError("A rationale is required. A decision without one is not a record.");
      return;
    }
    setBusy(true);
    try {
      if (action === "reject") {
        await api.rejectCandidate(id, rationale.trim());
      } else {
        await api.holdCandidate(id, rationale.trim());
      }
      setRationale("");
      await load();
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (error && !candidate) return <p className="banner banner-bad">{error}</p>;
  if (!candidate) return <Skeleton rows={6} label="Loading this candidate" />;

  const gate = candidate.gate ?? null;
  const canPromote = Boolean(gate?.passed) && candidate.status === "active";
  const experiments = candidate.experiments ?? [];

  return (
    <>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="mb-1">{candidate.hypothesis_title}</h1>
          <p className="subtitle flex flex-wrap items-center gap-2">
            <Link
              className="font-mono"
              href={`/programme/hypotheses/${candidate.hypothesis_ref}`}
            >
              {candidate.hypothesis_ref}
            </Link>
            <AiBadge origin={candidate.hypothesis_origin} />
            <span className="text-ink-muted">
              Stage {candidate.stage}
              {candidate.stage_name ? ` · ${candidate.stage_name}` : null}
            </span>
          </p>
        </div>
        <StatusBadge status={CANDIDATE_STATUS[candidate.status]}>
          {candidate.status}
        </StatusBadge>
      </div>

      {error ? <p className="banner banner-bad">{error}</p> : null}
      {unmet.length > 0 ? (
        <div className="banner banner-warn">
          <p>Still missing:</p>
          <ul>
            {unmet.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {candidate.evidence_is_synthetic ? (
        <p className="banner banner-warn">
          This candidate&apos;s evidence includes synthetic prices. It may reach
          independent validation and cannot pass the gate into shadow mode: a
          generator has no regime to fail to generalise across, so nothing
          measured on it says anything about robustness. Re-run against a real
          source to go further.
        </p>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Configuration</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="assumptions">
            <div className="assumption-row">
              <dt>Strategy</dt>
              <dd className="mono">{candidate.strategy_name}</dd>
            </div>
            <div className="assumption-row">
              <dt>Parameters</dt>
              <dd className="mono">{JSON.stringify(candidate.params)}</dd>
            </div>
            <div className="assumption-row">
              <dt>Universe</dt>
              <dd className="mono">
                {candidate.universe.join(", ") || (
                  <span className="text-ink-muted">empty</span>
                )}
              </dd>
            </div>
            <div className="assumption-row">
              <dt>Window</dt>
              <dd className="mono">
                {candidate.start_session} → {candidate.end_session}
              </dd>
            </div>
            <div className="assumption-row">
              <dt>Data source</dt>
              <dd className="mono">{candidate.data_source}</dd>
            </div>
          </dl>
        </CardContent>
      </Card>

      {gate ? <GateChecklist gate={gate} /> : null}

      {card ? (
        <Card className="mt-3">
          <CardHeader>
            <CardTitle className="flex flex-wrap items-center justify-between gap-2">
              <span>Scorecard</span>
              <span className="text-sm font-normal text-ink-muted">
                {card.measured} measured, {card.not_measured} not measured,{" "}
                {card.failing} failing
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-ink-muted text-pretty">
              Seventeen dimensions and deliberately no overall score. Collapsing
              them into one number lets a strong Sharpe outvote an unmeasured
              capacity, and produces a figure nobody can trace to a row. A cell
              reading &ldquo;not measured&rdquo; is an absent measurement, not a
              zero and not a failure.
            </p>
            <p className="banner banner-info">
              Recommendation: <strong>{card.recommendation.replace(/_/g, " ")}</strong>{" "}
              — {card.recommendation_reason}
              {card.approvers.length > 0
                ? ` Needs: ${card.approvers.join(", ")}.`
                : null}
            </p>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Dimension</th>
                    <th>Metric</th>
                    <th className="num">Observed</th>
                    <th>Target</th>
                    <th>Status</th>
                    <th>Commentary</th>
                  </tr>
                </thead>
                <tbody>
                  {card.rows.map((row) => (
                    <tr key={row.metric}>
                      <td>{row.dimension}</td>
                      <td>{row.metric}</td>
                      <td className="num mono">
                        {row.observed === null ? (
                          <span className="no-data">not measured</span>
                        ) : (
                          String(row.observed_display)
                        )}
                      </td>
                      <td className="text-ink-muted">{row.target}</td>
                      <td>
                        <StatusBadge status={SCORE_STATUS[row.status]}>
                          {row.status}
                        </StatusBadge>
                      </td>
                      <td className="text-ink-muted">{row.commentary}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      ) : null}

      <Card className="mt-3">
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center justify-between gap-2">
            <span>Experiments</span>
            <span className="text-sm font-normal text-ink-muted">
              {experiments.length} recorded
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {experiments.length === 0 ? (
            <p className="text-sm text-ink-muted">
              None yet. The runner queues exactly the experiments the gate is
              missing, and never one because a result might be interesting.
            </p>
          ) : (
            <DataTable
              rows={experiments}
              getRowId={(e) => e.ref}
              initialSort={[{ id: "created", desc: true }]}
              columns={[
                {
                  id: "ref",
                  header: "Ref",
                  sortable: true,
                  sortValue: (e) => e.ref,
                  className: "font-mono",
                  cell: (e) => (
                    <Link href={`/programme/experiments/${e.ref}`}>{e.ref}</Link>
                  ),
                },
                {
                  id: "kind",
                  header: "Kind",
                  sortable: true,
                  sortValue: (e) => e.kind,
                  cell: (e) => e.kind,
                },
                {
                  id: "status",
                  header: "Status",
                  sortable: true,
                  sortValue: (e) => e.status,
                  cell: (e) => e.status,
                },
                {
                  id: "conclusion",
                  header: "Conclusion",
                  sortable: true,
                  // Missing sorts out of the ranking rather than to either
                  // end — a not-yet-concluded experiment is not the "worst"
                  // one.
                  sortValue: (e) => e.conclusion ?? undefined,
                  cell: (e) =>
                    e.conclusion ? (
                      <StatusBadge status={CONCLUSION_STATUS[e.conclusion]}>
                        {e.conclusion}
                      </StatusBadge>
                    ) : (
                      <span className="text-ink-muted">—</span>
                    ),
                },
                {
                  id: "created",
                  header: "Registered",
                  sortable: true,
                  sortValue: (e) => e.created_at,
                  className: "text-ink-muted whitespace-nowrap",
                  cell: (e) => fmtInstant(e.created_at),
                },
              ]}
            />
          )}
        </CardContent>
      </Card>

      {shadow && shadow.sessions.length > 0 ? (
        <Card className="mt-3">
          <CardHeader>
            <CardTitle className="flex flex-wrap items-center justify-between gap-2">
              <span>Shadow sessions</span>
              <span className="text-sm font-normal text-ink-muted">
                {shadow.sessions.length} of {shadow.required} required
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-ink-muted text-pretty">
              The strategy deciding on a schedule and submitting nothing. The
              book is not stored: it is rebuilt from these rows on every run,
              filling each session&apos;s intents at the next session&apos;s
              open. Equity is that derived book&apos;s value against a fixed
              notional, and is not a P&amp;L — over this many sessions a return
              would carry a standard error several times its own size.
            </p>
            <DataTable
              rows={shadow.sessions}
              getRowId={(s) => s.session}
              initialSort={[{ id: "session", desc: true }]}
              columns={[
                {
                  id: "session",
                  header: "Session",
                  sortable: true,
                  sortValue: (s) => s.session,
                  className: "font-mono whitespace-nowrap",
                  cell: (s) => s.session,
                },
                {
                  id: "rebalanced",
                  header: "Rebalanced",
                  sortable: true,
                  sortValue: (s) => (s.rebalanced ? 1 : 0),
                  cell: (s) => (s.rebalanced ? "yes" : "—"),
                },
                {
                  id: "intents",
                  header: "Intents",
                  sortable: true,
                  sortValue: (s) => s.order_intents.length,
                  headerClassName: "text-right",
                  className: "text-right font-mono tabular-nums",
                  cell: (s) => s.order_intents.length,
                },
                {
                  id: "equity",
                  header: "Book equity",
                  sortable: true,
                  sortValue: (s) => s.equity ?? undefined,
                  headerClassName: "text-right",
                  className: "text-right font-mono tabular-nums",
                  cell: (s) =>
                    s.equity === null ? (
                      <span className="no-data">no data</span>
                    ) : (
                      s.equity.toFixed(2)
                    ),
                },
                {
                  id: "notes",
                  header: "Notes",
                  cell: (s) =>
                    s.error ? (
                      <div>
                        <StatusBadge status="blocked">error</StatusBadge>
                        <p className="mt-1 mb-0 text-xs text-blocked text-pretty">
                          {s.error}
                        </p>
                      </div>
                    ) : s.underfunded.length > 0 ? (
                      <div>
                        <StatusBadge status="unknown">
                          {s.underfunded.length} buy trimmed
                        </StatusBadge>
                        {/* Said out loud rather than left behind a `title` a
                            keyboard never reaches: this is the exact honesty
                            fact `SimulatedBroker.underfunded_buys` exists to
                            surface. */}
                        <p className="mt-1 mb-0 text-xs text-ink-muted text-pretty">
                          A real venue would have rejected these outright.
                        </p>
                      </div>
                    ) : (
                      <span className="text-ink-muted">—</span>
                    ),
                },
              ]}
            />
          </CardContent>
        </Card>
      ) : null}

      <Card className="mt-3">
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center justify-between gap-2">
            <span>Findings</span>
            <Button asChild variant="link" size="sm" className="h-auto p-0">
              <Link href="/programme/findings">Full register</Link>
            </Button>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {(findings?.findings ?? []).length === 0 ? (
            <p className="text-sm text-ink-muted">
              Nothing raised against this candidate.
            </p>
          ) : (
            <ul className="gate-list">
              {(findings?.findings ?? []).map((finding) => {
                const blocks =
                  finding.status === "open" &&
                  (findings?.blocking_severities ?? []).includes(finding.severity) &&
                  (findings?.veto_roles ?? []).includes(finding.raised_by);
                return (
                  <li className="gate-criterion" key={finding.ref}>
                    <StatusBadge status={blocks ? "blocked" : "mute"}>
                      {blocks ? "blocks" : finding.status}
                    </StatusBadge>
                    <div>
                      <p className="gate-criterion-desc">
                        <span className="font-mono">{finding.ref}</span>{" "}
                        {finding.title}
                      </p>
                      <p className="text-ink-muted gate-criterion-detail">
                        {finding.raised_by} · {finding.severity}
                        {finding.remediation ? ` · fix: ${finding.remediation}` : ""}
                      </p>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card className="mt-3">
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center justify-between gap-2">
            <span>Specialist assessments</span>
            <span className="text-sm font-normal text-ink-muted">
              {assessments.length} recorded
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-ink-muted text-pretty">
            Each role was shown the same brief and answered independently.
            Nothing here is summarised into a consensus, and nothing here is
            read by the gate — only a finding has force. Two roles reaching
            opposite conclusions is information, not a defect.
          </p>
          {assessments.length === 0 ? (
            <p className="text-sm text-ink-muted">
              The panel has not convened. It needs an API key, and it runs once
              per stage rather than once per pass.
            </p>
          ) : (
            <ul className="gate-list">
              {assessments.map((assessment) => (
                <li className="gate-criterion" key={assessment.id}>
                  <StatusBadge status={VERDICT_STATUS[assessment.verdict]}>
                    {assessment.verdict}
                  </StatusBadge>
                  <div>
                    <p className="gate-criterion-desc">{assessment.role}</p>
                    <p className="text-ink-muted gate-criterion-detail">
                      {assessment.summary}
                    </p>
                    <p className="text-ink-muted gate-criterion-evidence mono">
                      stage {assessment.stage} ·{" "}
                      {assessment.model || "unknown model"} ·{" "}
                      {fmtInstant(assessment.created_at)}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card className="mt-3">
        <CardHeader>
          <CardTitle>Decision</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-ink-muted text-pretty">
            Every decision is recorded with its rationale and the gate
            evaluation that backed it. Rejecting and holding need a reason and
            nothing else; promoting needs a passed gate and a typed
            confirmation.
          </p>

          <div className="space-y-2">
            <Label htmlFor="candidate-rationale">Rationale</Label>
            <Input
              id="candidate-rationale"
              value={rationale}
              onChange={(e) => setRationale(e.target.value)}
              placeholder="Rationale"
            />
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => close("hold")}
                disabled={busy || candidate.status !== "active"}
              >
                Hold
              </Button>
              <Button
                type="button"
                variant="destructive"
                onClick={() => close("reject")}
                disabled={busy || candidate.status !== "active"}
              >
                Reject
              </Button>
            </div>
          </div>

          <Separator />

          <div className="space-y-2">
            <Label htmlFor="candidate-confirm">
              Type <code>{CONFIRM_PHRASE}</code> to promote to stage{" "}
              {gate ? gate.to_stage : candidate.stage + 1}
            </Label>
            <Input
              id="candidate-confirm"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              placeholder={CONFIRM_PHRASE}
              disabled={!canPromote}
            />
            <div className="flex flex-wrap items-center gap-3">
              <Button
                type="button"
                onClick={promote}
                disabled={busy || !canPromote || confirm !== CONFIRM_PHRASE}
              >
                Promote to stage {gate ? gate.to_stage : candidate.stage + 1}
              </Button>
              {!canPromote ? (
                <span className="text-sm text-ink-muted">
                  {candidate.status !== "active"
                    ? `This candidate is ${candidate.status}.`
                    : "Available once the gate passes."}
                </span>
              ) : null}
            </div>
          </div>
        </CardContent>
      </Card>

      <p className="mt-4">
        <Button asChild variant="ghost" size="sm">
          <Link href="/programme">
            <ArrowLeft aria-hidden="true" />
            Pipeline
          </Link>
        </Button>
      </p>
    </>
  );
}
