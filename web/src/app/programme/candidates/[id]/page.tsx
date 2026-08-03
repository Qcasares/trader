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
 */

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ApiError,
  api,
  type Candidate,
  type FindingsPage,
  type RoleAssessment,
  type Scorecard,
  type ShadowHistory,
} from "@/lib/api";
import { AiBadge, GateChecklist } from "@/components/GateChecklist";

const CONFIRM_PHRASE = "PROMOTE";

const CONCLUSION_PILL: Record<string, string> = {
  pass: "pill pill-good",
  fail: "pill pill-bad",
  inconclusive: "pill pill-warn",
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
  if (!candidate) return <p className="muted">Loading candidate…</p>;

  const gate = candidate.gate ?? null;
  const canPromote = Boolean(gate?.passed) && candidate.status === "active";

  return (
    <>
      <p className="muted">
        <Link href="/programme">← Pipeline</Link>
      </p>
      <h1>{candidate.hypothesis_title}</h1>
      <p className="subtitle row">
        <Link className="mono" href={`/programme/hypotheses/${candidate.hypothesis_ref}`}>
          {candidate.hypothesis_ref}
        </Link>
        <AiBadge origin={candidate.hypothesis_origin} />
        <span className="muted">
          Stage {candidate.stage}
          {candidate.stage_name ? ` · ${candidate.stage_name}` : null} ·{" "}
          {candidate.status}
        </span>
      </p>

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

      <section className="card">
        <div className="card-head">
          <h2>Configuration</h2>
        </div>
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
            <dd className="mono">{candidate.universe.join(", ") || "—"}</dd>
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
      </section>

      {gate ? <GateChecklist gate={gate} /> : null}

      {card ? (
        <section className="card">
          <div className="card-head spread">
            <h2>Scorecard</h2>
            <span className="muted">
              {card.measured} measured, {card.not_measured} not measured,{" "}
              {card.failing} failing
            </span>
          </div>
          <p className="muted">
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
                        <span className="muted">not measured</span>
                      ) : (
                        String(row.observed_display)
                      )}
                    </td>
                    <td className="muted">{row.target}</td>
                    <td>
                      <span
                        className={
                          row.status === "pass"
                            ? "pill pill-good"
                            : row.status === "fail"
                              ? "pill pill-bad"
                              : "pill pill-mute"
                        }
                      >
                        {row.status}
                      </span>
                    </td>
                    <td className="muted">{row.commentary}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      <section className="card">
        <div className="card-head spread">
          <h2>Experiments</h2>
          <span className="muted">
            {(candidate.experiments ?? []).length} recorded
          </span>
        </div>
        {(candidate.experiments ?? []).length === 0 ? (
          <p className="muted">
            None yet. The runner queues exactly the experiments the gate is
            missing, and never one because a result might be interesting.
          </p>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Ref</th>
                  <th>Kind</th>
                  <th>Status</th>
                  <th>Conclusion</th>
                  <th>Registered</th>
                </tr>
              </thead>
              <tbody>
                {(candidate.experiments ?? []).map((experiment) => (
                  <tr key={experiment.ref}>
                    <td className="mono">
                      <Link href={`/programme/experiments/${experiment.ref}`}>
                        {experiment.ref}
                      </Link>
                    </td>
                    <td>{experiment.kind}</td>
                    <td>{experiment.status}</td>
                    <td>
                      {experiment.conclusion ? (
                        <span className={CONCLUSION_PILL[experiment.conclusion]}>
                          {experiment.conclusion}
                        </span>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td className="muted mono">
                      {experiment.created_at.slice(0, 10)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {shadow && shadow.sessions.length > 0 ? (
        <section className="card">
          <div className="card-head spread">
            <h2>Shadow sessions</h2>
            <span className="muted">
              {shadow.sessions.length} of {shadow.required} required
            </span>
          </div>
          <p className="muted">
            The strategy deciding on a schedule and submitting nothing. The book
            is not stored: it is rebuilt from these rows on every run, filling
            each session&apos;s intents at the next session&apos;s open. Equity
            is that derived book&apos;s value against a fixed notional, and is
            not a P&amp;L — over this many sessions a return would carry a
            standard error several times its own size.
          </p>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Session</th>
                  <th>Rebalanced</th>
                  <th className="num">Intents</th>
                  <th className="num">Book equity</th>
                  <th>Notes</th>
                </tr>
              </thead>
              <tbody>
                {shadow.sessions.map((entry) => (
                  <tr key={entry.session}>
                    <td className="mono">{entry.session}</td>
                    <td>{entry.rebalanced ? "yes" : "—"}</td>
                    <td className="num mono">{entry.order_intents.length}</td>
                    <td className="num mono">
                      {entry.equity === null ? "—" : entry.equity.toFixed(2)}
                    </td>
                    <td>
                      {entry.error ? (
                        <span className="pill pill-bad">{entry.error}</span>
                      ) : entry.underfunded.length > 0 ? (
                        <span
                          className="pill pill-warn"
                          title="A real venue would have rejected these outright."
                        >
                          {entry.underfunded.length} buy trimmed
                        </span>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      <section className="card">
        <div className="card-head spread">
          <h2>Findings</h2>
          <Link href="/programme/findings" className="muted">
            Full register
          </Link>
        </div>
        {(findings?.findings ?? []).length === 0 ? (
          <p className="muted">Nothing raised against this candidate.</p>
        ) : (
          <ul className="gate-list">
            {(findings?.findings ?? []).map((finding) => {
              const blocks =
                finding.status === "open" &&
                (findings?.blocking_severities ?? []).includes(finding.severity) &&
                (findings?.veto_roles ?? []).includes(finding.raised_by);
              return (
                <li className="gate-criterion" key={finding.ref}>
                  <span className={blocks ? "pill pill-bad" : "pill pill-mute"}>
                    {blocks ? "blocks" : finding.status}
                  </span>
                  <div>
                    <p className="gate-criterion-desc">
                      <span className="mono">{finding.ref}</span> {finding.title}
                    </p>
                    <p className="muted gate-criterion-detail">
                      {finding.raised_by} · {finding.severity}
                      {finding.remediation ? ` · fix: ${finding.remediation}` : ""}
                    </p>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section className="card">
        <div className="card-head spread">
          <h2>Specialist assessments</h2>
          <span className="muted">{assessments.length} recorded</span>
        </div>
        <p className="muted">
          Each role was shown the same brief and answered independently. Nothing
          here is summarised into a consensus, and nothing here is read by the
          gate — only a finding has force. Two roles reaching opposite
          conclusions is information, not a defect.
        </p>
        {assessments.length === 0 ? (
          <p className="muted">
            The panel has not convened. It needs an API key, and it runs once per
            stage rather than once per pass.
          </p>
        ) : (
          <ul className="gate-list">
            {assessments.map((assessment) => (
              <li className="gate-criterion" key={assessment.id}>
                <span
                  className={
                    assessment.verdict === "object"
                      ? "pill pill-bad"
                      : assessment.verdict === "concern"
                        ? "pill pill-warn"
                        : assessment.verdict === "support"
                          ? "pill pill-good"
                          : "pill pill-mute"
                  }
                >
                  {assessment.verdict}
                </span>
                <div>
                  <p className="gate-criterion-desc">{assessment.role}</p>
                  <p className="muted gate-criterion-detail">
                    {assessment.summary}
                  </p>
                  <p className="muted gate-criterion-evidence">
                    stage {assessment.stage} · {assessment.model || "unknown model"}{" "}
                    · {assessment.created_at.slice(0, 10)}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Decision</h2>
        </div>
        <p className="muted">
          Every decision is recorded with its rationale and the gate evaluation
          that backed it. Rejecting and holding need a reason and nothing else;
          promoting needs a passed gate and a typed confirmation.
        </p>
        <div className="row">
          <input
            type="text"
            value={rationale}
            onChange={(e) => setRationale(e.target.value)}
            placeholder="Rationale"
          />
          <button
            type="button"
            onClick={() => close("hold")}
            disabled={busy || candidate.status !== "active"}
          >
            Hold
          </button>
          <button
            type="button"
            onClick={() => close("reject")}
            disabled={busy || candidate.status !== "active"}
          >
            Reject
          </button>
        </div>
        <div className="row">
          <input
            type="text"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            placeholder={`Type ${CONFIRM_PHRASE}`}
            disabled={!canPromote}
          />
          <button
            type="button"
            onClick={promote}
            disabled={busy || !canPromote || confirm !== CONFIRM_PHRASE}
          >
            Promote to stage {gate ? gate.to_stage : candidate.stage + 1}
          </button>
          {!canPromote ? (
            <span className="muted">
              {candidate.status !== "active"
                ? `This candidate is ${candidate.status}.`
                : "Available once the gate passes."}
            </span>
          ) : null}
        </div>
      </section>
    </>
  );
}
