"use client";

/**
 * One hypothesis card.
 *
 * Rendered field by field in the operating prompt's own order, because the
 * order is the argument: mechanism, then why it persists, then how it would be
 * shown wrong. A card that reads well until "falsification test" and then goes
 * vague is a card whose weakness is visible, and burying that field would hide
 * exactly the thing worth seeing.
 */

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ApiError, api, type Hypothesis } from "@/lib/api";
import { Skeleton } from "@/components/Skeleton";
import { AiBadge } from "@/components/GateChecklist";

/** Section 7.1's order, with a readable label for each. */
const CARD_FIELDS: [string, string][] = [
  ["economic_mechanism", "Economic mechanism"],
  ["why_it_persists", "Why the opportunity persists"],
  ["instruments", "Instruments and universe"],
  ["trading_horizon", "Trading horizon"],
  ["entry_exit_concept", "Entry and exit concept"],
  ["expected_return_source", "Expected source of return"],
  ["expected_risks", "Expected risks"],
  ["expected_turnover", "Expected turnover"],
  ["expected_capacity", "Expected capacity"],
  ["data_requirements", "Data requirements"],
  ["alternative_explanations", "Alternative explanations"],
  ["simplest_baseline", "Simplest credible baseline"],
  ["falsification_test", "Falsification test"],
  ["acceptance_criteria", "Acceptance criteria"],
  ["rejection_criteria", "Rejection criteria"],
  ["limitations", "Known limitations"],
];

export default function HypothesisPage({
  params,
}: {
  params: Promise<{ ref: string }>;
}) {
  const { ref } = use(params);
  const router = useRouter();
  const [hypothesis, setHypothesis] = useState<Hypothesis | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setHypothesis(await api.hypothesis(ref));
      setError(null);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.isUnauthorized) {
        router.push("/login");
        return;
      }
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [ref, router]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) return <p className="banner banner-bad">{error}</p>;
  if (!hypothesis) return <Skeleton rows={6} label={`Loading ${ref}`} />;

  return (
    <>
      <p className="muted">
        <Link href="/programme/hypotheses">← Hypothesis ledger</Link>
      </p>
      <h1>
        <span className="mono">{hypothesis.ref}</span> {hypothesis.title}
      </h1>
      <p className="subtitle row">
        <AiBadge origin={hypothesis.origin} />
        <span className="muted">
          Owner {hypothesis.owner || "unassigned"} · {hypothesis.status} ·{" "}
          {hypothesis.variants_tried} variant
          {hypothesis.variants_tried === 1 ? "" : "s"} tried
        </span>
      </p>

      {hypothesis.origin === "model" ? (
        <p className="banner banner-info">
          Drafted by {hypothesis.model || "a model"}. Every figure this card
          could be judged on comes from the engine, not from here — a card
          asserting a performance number is refused before it is stored.
        </p>
      ) : null}

      {hypothesis.parent_ref ? (
        <p className="muted">
          Revises{" "}
          <Link href={`/programme/hypotheses/${hypothesis.parent_ref}`}>
            {hypothesis.parent_ref}
          </Link>
          . Counted as a revision, not as a new idea.
        </p>
      ) : null}

      <section className="card">
        <div className="card-head">
          <h2>The card</h2>
        </div>
        <dl className="assumptions">
          {CARD_FIELDS.map(([key, label]) => (
            <div className="assumption-row" key={key}>
              <dt>{label}</dt>
              <dd>{hypothesis.card[key] || <span className="muted">—</span>}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="card">
        <div className="card-head spread">
          <h2>Candidates</h2>
          <span className="muted">
            {(hypothesis.candidates ?? []).length} configuration
            {(hypothesis.candidates ?? []).length === 1 ? "" : "s"}
          </span>
        </div>
        {(hypothesis.candidates ?? []).length === 0 ? (
          <p className="muted">
            No configuration has been tested against this hypothesis yet.
          </p>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Strategy</th>
                  <th>Window</th>
                  <th>Source</th>
                  <th className="num">Stage</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {(hypothesis.candidates ?? []).map((candidate) => (
                  <tr key={candidate.id}>
                    <td>
                      <Link href={`/programme/candidates/${candidate.id}`}>
                        {candidate.strategy_name}
                      </Link>
                    </td>
                    <td className="mono muted">
                      {candidate.start_session} → {candidate.end_session}
                    </td>
                    <td className="mono">
                      {candidate.data_source}
                      {candidate.evidence_is_synthetic ? (
                        <span className="pill pill-warn">synthetic</span>
                      ) : null}
                    </td>
                    <td className="num mono">{candidate.stage}</td>
                    <td>{candidate.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {hypothesis.decision ? (
        <section className="card">
          <div className="card-head">
            <h2>Decision</h2>
          </div>
          <p>
            <strong>{hypothesis.decision}</strong>
            {hypothesis.decided_at
              ? ` · ${hypothesis.decided_at.slice(0, 10)}`
              : null}
          </p>
          <p className="muted">{hypothesis.decision_rationale || "No rationale recorded."}</p>
        </section>
      ) : null}
    </>
  );
}
