-- 0009_shadow.sql
--
-- Stage 3: the strategy decides on a schedule and submits nothing.
--
-- The operating prompt asks shadow mode to evidence stable operation, correct
-- decision timing, complete logs and reconciled hypothetical positions. Three
-- of those are satisfied by a log. The fourth needs a book, and the design
-- decision worth recording is that **there is no stored book**.
--
-- A persisted book would be a second source of truth about a portfolio that
-- exists only on paper, free to drift from the decisions that produced it, and
-- checking it against them would be the reconciliation rather than the thing
-- reconciled. So the book is *derived*: every shadow run seeds a fresh
-- `SimulatedBroker` with the opening balance and replays this table in session
-- order, filling each session's intents at the next session's open. The book
-- being reproducible from the log is then a property of the arrangement rather
-- than a claim to be tested.
--
-- That also buys the decision-lag rule for free. Intents recorded against
-- session S fill at S+1's open, which is the same rule `SimulatedBroker`
-- enforces in a backtest, applied by the same code. The most recent decision
-- has no next session and stays pending, which is correct rather than a gap.
--
-- What this is not
-- ~~~~~~~~~~~~~~~~
-- It is not broker paper trading, and the gate does not let it count as such.
-- No venue is contacted, no order exists, and the halting limits are seeded
-- from the paper book's marks rather than this one's — so a shadow run does not
-- exercise them. Proving those is stage 4's job, and the reason stage 4 is a
-- separate stage.

CREATE TABLE IF NOT EXISTS shadow_decisions (
    id            UUID PRIMARY KEY,
    candidate_id  UUID NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    -- The deployment the decision was computed against. Held disabled: it
    -- exists so the shipped `dry_run` has something to read, and
    -- `_enabled_deployments` filters on status, so it can never be picked up by
    -- the live loop.
    deployment_id UUID NOT NULL REFERENCES deployments(id) ON DELETE CASCADE,
    session       DATE NOT NULL,

    -- Whether the strategy's own schedule said to rebalance on this session.
    --
    -- `dry_run` decides unconditionally by design — it answers "what would you
    -- do if you rebalanced now" — so it returns intents every session. This
    -- column is what distinguishes a decision the schedule would have acted on
    -- from a preview, and only the former is replayed into the book.
    rebalanced    BOOLEAN NOT NULL DEFAULT FALSE,

    target_weights JSONB NOT NULL DEFAULT '{}'::JSONB,
    -- Post-gate intents. They come from `Driver.decide`, so `apply_risk` has
    -- already run on them; nothing here re-derives an order.
    order_intents JSONB NOT NULL DEFAULT '[]'::JSONB,
    risk_events   JSONB NOT NULL DEFAULT '[]'::JSONB,
    rationale     TEXT NOT NULL DEFAULT '',
    -- Book equity at this session, as the replay computed it. Recorded so the
    -- UI can draw a curve without re-running the replay, and so a divergence
    -- between two runs of the same log is visible rather than silent.
    equity        NUMERIC,
    -- Buys the simulated venue trimmed for want of cash. A real venue rejects
    -- these outright, so a non-empty list means the shadow book and a live one
    -- would have diverged however identical the intents were. Gate 3 -> 4 reads
    -- it.
    underfunded   JSONB NOT NULL DEFAULT '[]'::JSONB,
    error         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- One decision per candidate per session. A retried job must not be able
    -- to append a second entry for a day already recorded: the replay is
    -- ordered by session, and a duplicate would fill the same intents twice.
    CONSTRAINT shadow_decisions_unique UNIQUE (candidate_id, session)
);

CREATE INDEX IF NOT EXISTS idx_shadow_decisions_candidate
    ON shadow_decisions (candidate_id, session);
