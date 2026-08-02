-- 0001_baseline.sql
-- The nine legacy crypto-agent tables, verbatim from src/db/schema.sql.
--
-- This exists so the migration framework has a known starting point on a
-- database that was set up by hand per SETUP.md. Every statement is
-- IF NOT EXISTS, so applying it to an existing database is a no-op rather
-- than an error.
--
-- These tables belong to the legacy pipeline and are not used by the
-- systematic engine. They are left in place rather than dropped: the crypto
-- agents still reference them, and dropping tables is not something a
-- migration should do casually.

CREATE TABLE IF NOT EXISTS raw_social_posts (
    id          SERIAL PRIMARY KEY,
    source      TEXT NOT NULL,
    post_id     TEXT NOT NULL UNIQUE,
    text        TEXT NOT NULL,
    author      TEXT NOT NULL,
    follower_count INT NOT NULL DEFAULT 0,
    posted_at   TIMESTAMPTZ NOT NULL,
    url         TEXT NOT NULL DEFAULT '',
    mentioned_tickers TEXT[] NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS price_candles (
    id          SERIAL PRIMARY KEY,
    ticker      TEXT NOT NULL,
    timestamp   TIMESTAMPTZ NOT NULL,
    open        NUMERIC NOT NULL,
    high        NUMERIC NOT NULL,
    low         NUMERIC NOT NULL,
    close       NUMERIC NOT NULL,
    volume      NUMERIC NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (ticker, timestamp)
);

CREATE TABLE IF NOT EXISTS sentiment_scores (
    id              SERIAL PRIMARY KEY,
    ticker          TEXT NOT NULL,
    post_id         TEXT,
    source          TEXT,
    raw_score       NUMERIC,
    confidence      NUMERIC,
    method          TEXT,
    follower_weight NUMERIC,
    weighted_score  NUMERIC,
    composite_score NUMERIC,
    post_count      INT,
    source_breakdown JSONB,
    momentum        NUMERIC,
    anomaly_detected BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS technical_signals (
    id              SERIAL PRIMARY KEY,
    ticker          TEXT NOT NULL,
    rsi_14          NUMERIC,
    macd_line       NUMERIC,
    macd_signal     NUMERIC,
    macd_histogram  NUMERIC,
    bb_upper        NUMERIC,
    bb_middle       NUMERIC,
    bb_lower        NUMERIC,
    bb_position     NUMERIC,
    obv             NUMERIC,
    obv_trend       TEXT,
    volume_surge    BOOLEAN DEFAULT FALSE,
    volume_ratio    NUMERIC DEFAULT 1.0,
    current_price   NUMERIC,
    price_change_pct NUMERIC,
    direction       TEXT,
    strength        NUMERIC,
    patterns        JSONB DEFAULT '[]'::JSONB,
    rationale       TEXT DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS trade_signals (
    id              SERIAL PRIMARY KEY,
    ticker          TEXT NOT NULL,
    action          TEXT NOT NULL,
    combined_score  NUMERIC NOT NULL,
    confidence      NUMERIC NOT NULL,
    sentiment_score NUMERIC NOT NULL,
    technical_score NUMERIC NOT NULL,
    volume_signal   NUMERIC NOT NULL,
    rationale       TEXT DEFAULT '',
    anomaly_adjusted BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS risk_decisions (
    id                  SERIAL PRIMARY KEY,
    ticker              TEXT NOT NULL,
    approved            BOOLEAN NOT NULL,
    action              TEXT NOT NULL,
    proposed_amount_usd NUMERIC NOT NULL,
    adjusted_amount_usd NUMERIC,
    reason              TEXT DEFAULT '',
    stop_loss_triggered BOOLEAN DEFAULT FALSE,
    trade_signal_id     INT REFERENCES trade_signals(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS trade_results (
    id               SERIAL PRIMARY KEY,
    ticker           TEXT NOT NULL,
    action           TEXT NOT NULL,
    amount_usd       NUMERIC NOT NULL,
    success          BOOLEAN NOT NULL,
    job_id           TEXT,
    response         TEXT DEFAULT '',
    slippage_pct     NUMERIC,
    error            TEXT,
    risk_decision_id INT REFERENCES risk_decisions(id),
    executed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id                  SERIAL PRIMARY KEY,
    total_value_usd     NUMERIC NOT NULL DEFAULT 0,
    positions           JSONB NOT NULL DEFAULT '{}'::JSONB,
    daily_pnl_usd       NUMERIC NOT NULL DEFAULT 0,
    cumulative_pnl_usd  NUMERIC NOT NULL DEFAULT 0,
    max_drawdown_pct    NUMERIC NOT NULL DEFAULT 0,
    snapshot_time       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_heartbeats (
    id               SERIAL PRIMARY KEY,
    agent_role       TEXT NOT NULL UNIQUE,
    last_seen        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status           TEXT NOT NULL DEFAULT 'idle',
    cycles_completed INT NOT NULL DEFAULT 0,
    last_error       TEXT,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trade_signals_ticker_created
    ON trade_signals (ticker, created_at);
CREATE INDEX IF NOT EXISTS idx_risk_decisions_ticker_created
    ON risk_decisions (ticker, created_at);
CREATE INDEX IF NOT EXISTS idx_trade_results_ticker_executed
    ON trade_results (ticker, executed_at);
CREATE INDEX IF NOT EXISTS idx_price_candles_ticker_timestamp
    ON price_candles (ticker, timestamp);
CREATE INDEX IF NOT EXISTS idx_sentiment_scores_ticker_created
    ON sentiment_scores (ticker, created_at);
CREATE INDEX IF NOT EXISTS idx_technical_signals_ticker_created
    ON technical_signals (ticker, created_at);
CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_time
    ON portfolio_snapshots (snapshot_time);
