"use client";

/**
 * Programme configuration.
 *
 * The operating prompt's section 2, thirty-three keys. Its first rule about this
 * table is that a value nobody supplied is recorded as TBD rather than
 * invented, so an empty field renders as TBD here and stores as NULL — never as
 * an empty string that later reads like a deliberate choice.
 *
 * Critical unknowns are separated from the rest because the prompt asks for
 * exactly that separation: an absent reporting timezone should not block useful
 * work, and an absent maximum drawdown should.
 *
 * Rebuilt on shadcn primitives, one change beyond the markup: TBD now reads as
 * `StatusBadge status="unknown"` everywhere, critical or not. The legacy page
 * dimmed a non-critical TBD to a grey "mute" pill — the same neutral-grey
 * treatment the rest of this migration exists to remove, because "not
 * measured" told quietly is still the same lie. Which section a key sits in
 * already carries how much a gap matters; the badge only needs to say whether
 * one exists.
 */

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ApiError,
  api,
  type ProgrammeConfig,
  type ProgrammeConfigItem,
} from "@/lib/api";
import { Skeleton } from "@/components/Skeleton";
import { StatusBadge } from "@/components/StatusBadge";
import { DataTable, type Column } from "@/components/DataTable";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

/** Shared by the critical and the everything-else table, so both sort and filter the same way. */
function configColumns(
  draft: Record<string, string>,
  onChange: (key: string, value: string) => void,
): Column<ProgrammeConfigItem>[] {
  return [
    {
      id: "key",
      header: "Key",
      sortable: true,
      sortValue: (item) => item.key,
      className: "font-mono whitespace-nowrap",
      cell: (item) => item.key,
    },
    {
      id: "value",
      header: "Value",
      className: "min-w-[18ch]",
      cell: (item) => (
        <Input
          value={draft[item.key] ?? item.value ?? ""}
          placeholder="TBD"
          onChange={(e) => onChange(item.key, e.target.value)}
          aria-label={item.key}
          className="h-8"
        />
      ),
    },
    {
      id: "state",
      header: "State",
      sortable: true,
      // TBD first on an ascending sort — the state an operator is scanning
      // for is the gap, not the confirmation that a key is already set.
      sortValue: (item) => (item.value === null ? 0 : 1),
      cell: (item) =>
        item.value === null ? (
          <StatusBadge status="unknown">TBD</StatusBadge>
        ) : (
          <StatusBadge status="settled">set</StatusBadge>
        ),
    },
    {
      id: "notes",
      header: "Notes",
      className: "max-w-[40ch] text-ink-muted text-pretty",
      cell: (item) => item.notes,
    },
  ];
}

export default function ProgrammeConfigPage() {
  const router = useRouter();
  const [config, setConfig] = useState<ProgrammeConfig | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setConfig(await api.programmeConfig());
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
  }, [refresh]);

  const change = (key: string, value: string) => {
    setSaved(false);
    setDraft((d) => ({ ...d, [key]: value }));
  };

  const save = async () => {
    if (Object.keys(draft).length === 0) return;
    setBusy(true);
    try {
      setConfig(await api.setProgrammeConfig(draft));
      setDraft({});
      setSaved(true);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (error && !config) return <p className="banner banner-bad">{error}</p>;
  if (!config) return <Skeleton rows={6} label="Loading the configuration" />;

  const critical = config.items.filter((i) => i.is_critical);
  const rest = config.items.filter((i) => !i.is_critical);
  const changes = Object.keys(draft).length;
  const columns = configColumns(draft, change);

  return (
    <>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="mb-1">Programme configuration</h1>
          <p className="m-0 text-base text-ink-muted text-pretty">
            An empty field is TBD, and TBD is what it stays. Nothing here
            substitutes a plausible default for a value nobody supplied,
            because a guessed risk limit is indistinguishable from an agreed
            one once it is in the table.
          </p>
        </div>
        <Button onClick={save} disabled={busy || changes === 0}>
          Save {changes || ""} change{changes === 1 ? "" : "s"}
        </Button>
      </div>

      {error ? <p className="banner banner-bad">{error}</p> : null}
      {saved ? <p className="banner banner-info">Saved.</p> : null}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-baseline gap-2">
            Critical
            <span className="text-sm font-normal text-ink-muted">
              {config.critical_unknowns.length} still TBD
            </span>
          </CardTitle>
          <p className="m-0 text-sm text-ink-muted text-pretty">
            These bound what the programme may do or how a figure is
            interpreted. The runner works without them; a recommendation that
            depends on one is not worth making until it is set.
          </p>
        </CardHeader>
        <CardContent>
          <DataTable
            rows={critical}
            getRowId={(item) => item.key}
            filterPlaceholder="Filter critical keys"
            empty="No critical keys."
            initialSort={[{ id: "state", desc: false }]}
            columns={columns}
          />
        </CardContent>
      </Card>

      <Card className="mt-3">
        <CardHeader>
          <CardTitle>Everything else</CardTitle>
        </CardHeader>
        <CardContent>
          <DataTable
            rows={rest}
            getRowId={(item) => item.key}
            filterPlaceholder="Filter keys"
            empty="No further keys."
            initialSort={[{ id: "key", desc: false }]}
            columns={columns}
          />
        </CardContent>
      </Card>
    </>
  );
}
