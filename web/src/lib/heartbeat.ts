/**
 * heartbeat.ts
 * ------------
 * What a heartbeat row says about the process that writes it, decided once.
 *
 * `worker_heartbeats` holds one row per process: the worker, and the AI
 * programme's runner under the id `programme`. Its `status` column is
 * `'alive'` while the process runs and `'stopped'` once it has shut down
 * cleanly (`src/worker/main.py` `_mark_stopped`, `src/programme/main.py`
 * `_record_shutdown`). A process that crashes writes nothing, so its row goes
 * on saying `'alive'` for as long as it exists. The API therefore reports
 * `stale` beside the status, from the heartbeat's age against the database's
 * clock, and neither half is enough alone:
 *
 * - the status alone is the dead worker that looks alive, the failure the
 *   heartbeat exists to catch;
 * - the age alone is a process that shut down a moment ago: the shutdown
 *   stamps `last_seen`, so for the next minute its row is not stale. /system
 *   showed a green "✓ stopped" with a live halo, and /programme "✓ alive",
 *   until it aged out (found in review, 2026-09-27).
 *
 * So a process is alive only while its heartbeat is fresh *and* says
 * `'alive'`. Every page that shows a heartbeat — /system, /programme and the
 * daily report — asks here rather than deciding, and `livenessStatus` in
 * `StatusBadge.tsx` draws the answer (web/DESIGN.md G-4).
 * `tests/unit/test_web_taste.py` reads each function below and holds the
 * pages to them.
 */

/** A heartbeat row, as `/system/status`, `/programme/status` and the report carry one. */
export interface Heartbeat {
  /** Older than the API's threshold, measured on the database's clock. */
  stale: boolean;
  /**
   * The stored column: `'alive'` while the process runs, `'stopped'` once it
   * has shut down cleanly. Optional, because the web and the API deploy apart
   * and a daily report from an API older than the field carries none; a row
   * that does not say `'alive'` is not alive, whatever its age.
   */
  status?: string | null;
}

/** Alive: fresh, and saying so. The one test of liveness every page uses. */
export function isAlive(heartbeat: Heartbeat): boolean {
  return !heartbeat.stale && heartbeat.status === "alive";
}

/**
 * The word a heartbeat's chip carries.
 *
 * A clean shutdown reads "shut down" at any age: the stored status says what
 * happened, and "no heartbeat" would call an expected stop a disappearance.
 * Never the stored `'stopped'` itself, which is the kill switch's word on the
 * same page (web/DESIGN.md C-12r) — a worker that has stopped is not a halted
 * switch, and the two must not read alike. A stale row that last said
 * `'alive'` is a process that stopped writing without saying so: "no
 * heartbeat". A status nothing writes is shown as it is, never as "alive".
 */
export function livenessWord(heartbeat: Heartbeat): string {
  if (heartbeat.status === "stopped") return "shut down";
  if (heartbeat.stale) return "no heartbeat";
  if (heartbeat.status === "alive") return "alive";
  return heartbeat.status ? heartbeat.status : "status not reported";
}

/**
 * Heartbeat rows in a fixed order: by worker id, compared by code unit, so the
 * order is the same in every locale.
 *
 * The API answers newest first (`ORDER BY last_seen DESC`), which is the right
 * order for choosing the ten rows it sends and the wrong one for drawing them:
 * two live processes trade places on most polls, and a keyed row that React
 * moves is taken out of the document and put back, which restarts its CSS
 * animation — the live halo jumped back to the start of its breath on
 * whichever row moved (web/DESIGN.md M-10r). In this order a poll moves no row;
 * a process that starts or stops inserts or removes one and leaves the rest
 * where they are.
 */
export function byWorkerId<T extends { worker_id: string }>(
  rows: readonly T[],
): T[] {
  return [...rows].sort((a, b) =>
    a.worker_id < b.worker_id ? -1 : a.worker_id > b.worker_id ? 1 : 0,
  );
}

/**
 * The id the AI programme's runner writes its heartbeat under.
 *
 * It is `PROGRAMME_WORKER_ID` in `src/programme/flags.py`, and
 * `tests/unit/test_web_taste.py` holds the two equal. The runner shares the
 * worker's table so that one staleness rule covers both (the comment beside
 * that constant), which leaves every reader of the table to remember that one
 * of its rows is not a worker's.
 */
export const PROGRAMME_RUNNER_ID = "programme";

/**
 * Whether a heartbeat row is a worker's: a process that claims the worker's
 * jobs — backtests, the ingest, the marks, the live decision, and the kill
 * switch's cancel at the venue.
 *
 * The programme's runner is not one. It claims only its own kinds, so a
 * runner that is alive runs none of that. Counted as a worker, a live runner
 * beside a dead worker kept /system from saying that no worker is alive, and
 * kept the kill switch's cancel note from saying that nothing is running to
 * carry the cancel out (found in review, 2026-09-27). The daily report is not
 * affected: it names each silent process on its own and never says "a worker
 * is alive".
 */
export function isWorkerProcess(row: { worker_id: string }): boolean {
  return row.worker_id !== PROGRAMME_RUNNER_ID;
}
