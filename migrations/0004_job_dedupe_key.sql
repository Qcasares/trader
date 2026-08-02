-- 0004_job_dedupe_key.sql
--
-- Make scheduled jobs idempotent.
--
-- The session planner emits a fixed set of jobs for a trading day. It has to
-- be safe to run repeatedly — on worker startup, after a restart, on a retry —
-- without enqueuing the same work twice. Two `live_decision` jobs for one
-- session would compute the same decision twice; two `submit_orders` jobs
-- would attempt to send the same batch twice. The deterministic client order
-- id makes the second submission harmless at the venue, but relying on the
-- broker to reject our duplicates is not a design, it is a hope.
--
-- So a scheduled job carries `dedupe_key = "{kind}:{session}"` and a unique
-- index refuses the second insert.
--
-- The index is *partial*. Ad-hoc jobs — a backtest queued from the UI — have
-- no natural key and must be enqueueable many times, so they leave the column
-- NULL and the constraint does not apply to them.

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS dedupe_key TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_dedupe_key
    ON jobs (dedupe_key)
    WHERE dedupe_key IS NOT NULL;

COMMENT ON COLUMN jobs.dedupe_key IS
    'Stable identity for a scheduled job, "{kind}:{session}". NULL for ad-hoc '
    'jobs, which may legitimately repeat.';
