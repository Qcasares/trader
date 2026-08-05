"use client";

/**
 * One hypothesis card.
 *
 * Rendered field by field in the operating prompt's own order, because the
 * order is the argument: mechanism, then why it persists, then how it would be
 * shown wrong. A card that reads well until "falsification test" and then goes
 * vague is a card whose weakness is visible, and burying that field would hide
 * exactly the thing worth seeing.
 *
 * Rebuilt on shadcn primitives to match `system/page.tsx` and
 * `backtests/page.tsx`. `.assumptions`/`.assumption-row` are kept — they are
 * tuned and the field ordering above depends on nothing about their markup.
 * What changed: sections are `Card`s; the candidates list is a sortable
 * `DataTable`, using the same `unknown`-badge-for-synthetic convention
 * `backtests/page.tsx` already established rather than a lookalike pill; a
 * candidate's lifecycle state and the synthetic-evidence flag are both
 * `StatusBadge`; and the back link moved to a `Button` at the foot of the
 * page, matching `backtests/[id]/page.tsx`.
 */

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { ApiError, api, type Candidate, type Hypothesis } from "@/lib/api";
import { Skeleton } from "@/components/Skeleton";
import { AiBadge } from "@/components/GateChecklist";
import { DataTable } from "@/components/DataTable";
import { StatusBadge, type Status } from "@/components/StatusBadge";
import { fmtInstant } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

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

/**
 * A candidate's lifecycle state, on the same four states every other page
 * uses. None of them is `settled` — this is a workflow position, not a
 * measurement that met a bar — so only `rejected` earns the loud badge.
 */
const CANDIDATE_STATUS: Record<Candidate["status"], Status> = {
  active: "mute",
  held: "mute",
  rejected: "blocked",
  retired: "mute",
};

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

  const candidates = hypothesis.candidates ?? [];

  return (
    <>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="mb-1">
            <span className="font-mono">{hypothesis.ref}</span> {hypothesis.title}
          </h1>
          <p className="subtitle flex flex-wrap items-center gap-2">
            <AiBadge origin={hypothesis.origin} />
            <span className="text-ink-muted">
              Owner {hypothesis.owner || "unassigned"} · {hypothesis.status} ·{" "}
              {hypothesis.variants_tried} variant
              {hypothesis.variants_tried === 1 ? "" : "s"} tried
            </span>
          </p>
        </div>
      </div>

      {hypothesis.origin === "model" ? (
        <p className="banner banner-info">
          Drafted by {hypothesis.model || "a model"}. Every figure this card
          could be judged on comes from the engine, not from here — a card
          asserting a performance number is refused before it is stored.
        </p>
      ) : null}

      {hypothesis.parent_ref ? (
        <p className="text-sm text-ink-muted">
          Revises{" "}
          <Link href={`/programme/hypotheses/${hypothesis.parent_ref}`}>
            {hypothesis.parent_ref}
          </Link>
          . Counted as a revision, not as a new idea.
        </p>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>The card</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="assumptions">
            {CARD_FIELDS.map(([key, label]) => (
              <div className="assumption-row" key={key}>
                <dt>{label}</dt>
                <dd>
                  {hypothesis.card[key] || (
                    <span className="text-ink-muted">—</span>
                  )}
                </dd>
              </div>
            ))}
          </dl>
        </CardContent>
      </Card>

      <Card className="mt-3">
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center justify-between gap-2">
            <span>Candidates</span>
            <span className="text-sm font-normal text-ink-muted">
              {candidates.length} configuration
              {candidates.length === 1 ? "" : "s"}
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {candidates.length === 0 ? (
            <p className="text-sm text-ink-muted">
              No configuration has been tested against this hypothesis yet.
            </p>
          ) : (
            <DataTable
              rows={candidates}
              getRowId={(c) => c.id}
              initialSort={[{ id: "stage", desc: true }]}
              columns={[
                {
                  id: "strategy",
                  header: "Strategy",
                  sortable: true,
                  sortValue: (c) => c.strategy_name,
                  cell: (c) => (
                    <Link href={`/programme/candidates/${c.id}`}>
                      {c.strategy_name}
                    </Link>
                  ),
                },
                {
                  id: "window",
                  header: "Window",
                  sortable: true,
                  sortValue: (c) => c.start_session,
                  className: "font-mono text-ink-muted whitespace-nowrap",
                  cell: (c) => `${c.start_session} → ${c.end_session}`,
                },
                {
                  id: "source",
                  header: "Source",
                  sortable: true,
                  sortValue: (c) => c.data_source,
                  className: "font-mono",
                  cell: (c) => (
                    <span className="flex flex-wrap items-center gap-1.5">
                      {c.data_source}
                      {c.evidence_is_synthetic ? (
                        <StatusBadge status="unknown">synthetic</StatusBadge>
                      ) : null}
                    </span>
                  ),
                },
                {
                  id: "stage",
                  header: "Stage",
                  sortable: true,
                  sortValue: (c) => c.stage,
                  headerClassName: "text-right",
                  className: "text-right font-mono tabular-nums",
                  cell: (c) => c.stage,
                },
                {
                  id: "status",
                  header: "Status",
                  sortable: true,
                  sortValue: (c) => c.status,
                  cell: (c) => (
                    <StatusBadge status={CANDIDATE_STATUS[c.status]}>
                      {c.status}
                    </StatusBadge>
                  ),
                },
              ]}
            />
          )}
        </CardContent>
      </Card>

      {hypothesis.decision ? (
        <Card className="mt-3">
          <CardHeader>
            <CardTitle>Decision</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-body">
              <strong>{hypothesis.decision}</strong>
              {hypothesis.decided_at
                ? ` · ${fmtInstant(hypothesis.decided_at)}`
                : null}
            </p>
            <p className="mb-0 text-sm text-ink-muted">
              {hypothesis.decision_rationale || "No rationale recorded."}
            </p>
          </CardContent>
        </Card>
      ) : null}

      <p className="mt-4">
        <Button asChild variant="ghost" size="sm">
          <Link href="/programme/hypotheses">
            <ArrowLeft aria-hidden="true" />
            Hypothesis ledger
          </Link>
        </Button>
      </p>
    </>
  );
}
