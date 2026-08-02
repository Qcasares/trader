-- 0002_systematic.sql
-- Tables for the deterministic systematic engine.
--
-- Additive only. The legacy tables from 0001 are untouched.
--
-- Two design decisions worth stating explicitly:
--
-- 1. `daily_bars` stores RAW prices and carries `source` in the primary key,
--    so yfinance and Alpaca rows coexist for the same (symbol, session) and a
--    reconciliation job can compare them. A silent fallback between vendors
--    produces a continuous-looking series stitched from two different ideas of
--    what a price was; making them disagree loudly is the point.
--
-- 2. Every table that could plausibly become per-user carries `owner_id` from
--    the start, even though it is constant today. Retrofitting tenancy after
--    the fact means touching every query in the system.

-- =========================================================================
-- Market data
-- =========================================================================

CREATE TABLE daily_bars (
    symbol      TEXT        NOT NULL,
    session     DATE        NOT NULL,
    source      TEXT        NOT NULL,
    open        NUMERIC     NOT NULL,
    high        NUMERIC     NOT NULL,
    low         NUMERIC     NOT NULL,
    close       NUMERIC     NOT NULL,
    volume      NUMERIC     NOT NULL DEFAULT 0,
    -- Split- AND dividend-adjusted. Signals use this; the ledger uses `close`.
    adj_close   NUMERIC     NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, session, source)
);

-- BRIN suits an append-only table whose physical order tracks `session`.
CREATE INDEX idx_daily_bars_session ON daily_bars USING BRIN (session);
CREATE INDEX idx_daily_bars_symbol_session ON daily_bars (symbol, session DESC);

CREATE TABLE data_quality_alerts (
    id         BIGSERIAL PRIMARY KEY,
    symbol     TEXT NOT NULL,
    session    DATE,
    kind       TEXT NOT NULL,           -- 'source_divergence' | 'gap' | 'stale'
    detail     JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_data_quality_alerts_created ON data_quality_alerts (created_at DESC);

-- =========================================================================
-- Strategies and backtests
-- =========================================================================

CREATE TABLE backtest_runs (
    id                 UUID PRIMARY KEY,
    owner_id           TEXT        NOT NULL DEFAULT 'default',
    strategy_name      TEXT        NOT NULL,
    strategy_version   TEXT        NOT NULL DEFAULT '1.0',
    params             JSONB       NOT NULL DEFAULT '{}'::JSONB,
    universe           TEXT[]      NOT NULL DEFAULT '{}',
    start_session      DATE        NOT NULL,
    end_session        DATE        NOT NULL,
    initial_cash       NUMERIC     NOT NULL,
    data_source        TEXT        NOT NULL,
    cost_model         JSONB       NOT NULL DEFAULT '{}'::JSONB,
    -- Sessions between deciding and executing. 1 = decide on close, fill at
    -- the next open. Stamped so a stored result can never be reinterpreted
    -- under a different assumption.
    decision_lag_sessions INT      NOT NULL DEFAULT 1,
    engine_version     TEXT        NOT NULL DEFAULT '',
    status             TEXT        NOT NULL DEFAULT 'queued',
    metrics            JSONB,
    error              TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at         TIMESTAMPTZ,
    finished_at        TIMESTAMPTZ,
    CONSTRAINT backtest_runs_status_check
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled'))
);

CREATE INDEX idx_backtest_runs_strategy ON backtest_runs (strategy_name, created_at DESC);
CREATE INDEX idx_backtest_runs_status ON backtest_runs (status, created_at DESC);

CREATE TABLE backtest_equity (
    run_id       UUID    NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
    session      DATE    NOT NULL,
    equity       NUMERIC NOT NULL,
    cash         NUMERIC NOT NULL,
    drawdown_pct NUMERIC NOT NULL DEFAULT 0,
    PRIMARY KEY (run_id, session)
);

CREATE TABLE backtest_orders (
    id           BIGSERIAL PRIMARY KEY,
    run_id       UUID    NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
    session      DATE    NOT NULL,
    symbol       TEXT    NOT NULL,
    side         TEXT    NOT NULL,
    qty          NUMERIC NOT NULL,
    price        NUMERIC NOT NULL,
    notional     NUMERIC NOT NULL,
    commission   NUMERIC NOT NULL DEFAULT 0,
    reason       TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX idx_backtest_orders_run ON backtest_orders (run_id, session);

CREATE TABLE backtest_targets (
    run_id        UUID    NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
    session       DATE    NOT NULL,
    symbol        TEXT    NOT NULL,
    target_weight NUMERIC NOT NULL,
    PRIMARY KEY (run_id, session, symbol)
);

-- =========================================================================
-- Live / paper trading
-- =========================================================================

CREATE TABLE deployments (
    id            UUID PRIMARY KEY,
    owner_id      TEXT NOT NULL DEFAULT 'default',
    strategy_name TEXT NOT NULL,
    params        JSONB NOT NULL DEFAULT '{}'::JSONB,
    mode          TEXT NOT NULL DEFAULT 'paper',
    capital_usd   NUMERIC NOT NULL,
    risk_limits   JSONB NOT NULL DEFAULT '{}'::JSONB,
    -- A deployment cannot be created without a completed backtest. The gate
    -- lives in the schema, not only in the API, so the research lab sits
    -- upstream of the control plane rather than parallel to it.
    approved_backtest_run_id UUID REFERENCES backtest_runs(id),
    status        TEXT NOT NULL DEFAULT 'disabled',
    halt_reason   TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    enabled_at    TIMESTAMPTZ,
    disabled_at   TIMESTAMPTZ,
    CONSTRAINT deployments_mode_check CHECK (mode IN ('paper', 'live')),
    CONSTRAINT deployments_status_check
        CHECK (status IN ('disabled', 'enabled', 'halted'))
);

CREATE TABLE decisions (
    id             UUID PRIMARY KEY,
    deployment_id  UUID NOT NULL REFERENCES deployments(id) ON DELETE CASCADE,
    session        DATE NOT NULL,
    target_weights JSONB NOT NULL DEFAULT '{}'::JSONB,
    order_intents  JSONB NOT NULL DEFAULT '[]'::JSONB,
    rationale      TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'planned',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- One decision per deployment per session. This is the idempotency key:
    -- a retried job cannot produce a second day's worth of orders.
    UNIQUE (deployment_id, session)
);

CREATE TABLE orders (
    id               UUID PRIMARY KEY,
    deployment_id    UUID REFERENCES deployments(id) ON DELETE CASCADE,
    decision_id      UUID REFERENCES decisions(id) ON DELETE CASCADE,
    -- Deterministic: "{run_ref}:{session}:{symbol}". The venue rejects a
    -- duplicate, so a retry cannot double-trade.
    client_order_id  TEXT NOT NULL UNIQUE,
    broker_order_id  TEXT,
    mode             TEXT NOT NULL DEFAULT 'paper',
    symbol           TEXT NOT NULL,
    side             TEXT NOT NULL,
    order_type       TEXT NOT NULL DEFAULT 'market',
    qty              NUMERIC,
    notional         NUMERIC,
    status           TEXT NOT NULL DEFAULT 'pending',
    submitted_at     TIMESTAMPTZ,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    raw              JSONB NOT NULL DEFAULT '{}'::JSONB,
    CONSTRAINT orders_mode_check CHECK (mode IN ('paper', 'live'))
);

CREATE INDEX idx_orders_deployment ON orders (deployment_id, submitted_at DESC);

CREATE TABLE fills (
    id              UUID PRIMARY KEY,
    order_id        UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    qty             NUMERIC NOT NULL,
    price           NUMERIC NOT NULL,
    commission      NUMERIC NOT NULL DEFAULT 0,
    filled_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_fills_order ON fills (order_id);

-- Replaces the broken get_daily_pnl, which summed buy/sell cash flow and so
-- read a $100 purchase as a $100 loss. P&L is a change in marked equity:
--   daily_pnl = equity_t - equity_{t-1} - deposits + withdrawals
CREATE TABLE daily_marks (
    owner_id       TEXT    NOT NULL DEFAULT 'default',
    mode           TEXT    NOT NULL DEFAULT 'paper',
    session        DATE    NOT NULL,
    equity         NUMERIC NOT NULL,
    cash           NUMERIC NOT NULL,
    deposits       NUMERIC NOT NULL DEFAULT 0,
    withdrawals    NUMERIC NOT NULL DEFAULT 0,
    daily_pnl      NUMERIC NOT NULL DEFAULT 0,
    cumulative_pnl NUMERIC NOT NULL DEFAULT 0,
    drawdown_pct   NUMERIC NOT NULL DEFAULT 0,
    PRIMARY KEY (owner_id, mode, session)
);

CREATE TABLE positions_snapshot (
    owner_id        TEXT    NOT NULL DEFAULT 'default',
    mode            TEXT    NOT NULL DEFAULT 'paper',
    as_of           DATE    NOT NULL,
    symbol          TEXT    NOT NULL,
    qty             NUMERIC NOT NULL,
    avg_entry_price NUMERIC NOT NULL,
    market_price    NUMERIC NOT NULL,
    market_value    NUMERIC NOT NULL,
    unrealized_pnl  NUMERIC NOT NULL DEFAULT 0,
    PRIMARY KEY (owner_id, mode, as_of, symbol)
);

-- =========================================================================
-- Control plane
-- =========================================================================

-- Singleton-ish key/value store. The kill switch lives here.
CREATE TABLE system_flags (
    key        TEXT PRIMARY KEY,
    value      JSONB NOT NULL,
    updated_by TEXT NOT NULL DEFAULT 'system',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Fail closed: if the worker cannot read this row it must treat trading as
-- disabled, so the default state is explicit rather than inferred.
INSERT INTO system_flags (key, value, updated_by)
VALUES ('trading_enabled', 'false'::JSONB, 'migration')
ON CONFLICT (key) DO NOTHING;

CREATE TABLE jobs (
    id           UUID PRIMARY KEY,
    kind         TEXT        NOT NULL,
    payload      JSONB       NOT NULL DEFAULT '{}'::JSONB,
    status       TEXT        NOT NULL DEFAULT 'queued',
    priority     INT         NOT NULL DEFAULT 0,
    attempts     INT         NOT NULL DEFAULT 0,
    max_attempts INT         NOT NULL DEFAULT 3,
    locked_by    TEXT,
    lease_expires_at TIMESTAMPTZ,
    result       JSONB,
    error        TEXT,
    scheduled_for TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at   TIMESTAMPTZ,
    finished_at  TIMESTAMPTZ,
    CONSTRAINT jobs_status_check
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled'))
);

-- Partial index: the claim query only ever looks at queued rows.
CREATE INDEX idx_jobs_claimable ON jobs (priority DESC, scheduled_for)
    WHERE status = 'queued';
CREATE INDEX idx_jobs_lease ON jobs (lease_expires_at) WHERE status = 'running';

CREATE TABLE audit_log (
    id          BIGSERIAL PRIMARY KEY,
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    entity_type TEXT,
    entity_id   TEXT,
    detail      JSONB NOT NULL DEFAULT '{}'::JSONB,
    at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_log_at ON audit_log (at DESC);

CREATE TABLE worker_heartbeats (
    worker_id TEXT PRIMARY KEY,
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status    TEXT NOT NULL DEFAULT 'idle',
    detail    JSONB NOT NULL DEFAULT '{}'::JSONB
);

-- LLM output lands here and nowhere else. It is generated after a decision is
-- already recorded and is never an input to one.
CREATE TABLE commentary (
    id         BIGSERIAL PRIMARY KEY,
    scope      TEXT NOT NULL,
    ref_id     TEXT NOT NULL,
    model      TEXT NOT NULL DEFAULT '',
    body_md    TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
