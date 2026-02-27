-- schema.sql
-- PostgreSQL schema for the multi-agent crypto trading bot.
-- 9 tables mirroring agent dataclass structures.

-- =========================================================================
-- 1. raw_social_posts — mirrors ResearchAgent.SocialPost
-- =========================================================================
CREATE TABLE raw_social_posts (
    id          SERIAL PRIMARY KEY,
    source      TEXT NOT NULL,              -- "twitter" | "reddit" | "farcaster"
    post_id     TEXT NOT NULL UNIQUE,
    text        TEXT NOT NULL,
    author      TEXT NOT NULL,
    follower_count INT NOT NULL DEFAULT 0,
    posted_at   TIMESTAMPTZ NOT NULL,
    url         TEXT NOT NULL DEFAULT '',
    mentioned_tickers TEXT[] NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =========================================================================
-- 2. price_candles — mirrors TechnicalAgent.CandleData
-- =========================================================================
CREATE TABLE price_candles (
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

-- =========================================================================
-- 3. sentiment_scores — mirrors SentimentAgent.PostSentiment + TickerSentiment
-- =========================================================================
CREATE TABLE sentiment_scores (
    id              SERIAL PRIMARY KEY,
    ticker          TEXT NOT NULL,
    post_id         TEXT,                       -- NULL for aggregate-only rows
    source          TEXT,
    raw_score       NUMERIC,
    confidence      NUMERIC,
    method          TEXT,                       -- "vader" | "finbert" | "claude"
    follower_weight NUMERIC,
    weighted_score  NUMERIC,
    composite_score NUMERIC,
    post_count      INT,
    source_breakdown JSONB,
    momentum        NUMERIC,
    anomaly_detected BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =========================================================================
-- 4. technical_signals — mirrors TechnicalAgent.TechnicalIndicators + TechnicalSignal
-- =========================================================================
CREATE TABLE technical_signals (
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
    obv_trend       TEXT,                       -- "rising" | "falling" | "flat"
    volume_surge    BOOLEAN DEFAULT FALSE,
    volume_ratio    NUMERIC DEFAULT 1.0,
    current_price   NUMERIC,
    price_change_pct NUMERIC,
    direction       TEXT,                       -- "bullish" | "bearish" | "neutral"
    strength        NUMERIC,
    patterns        JSONB DEFAULT '[]'::JSONB,
    rationale       TEXT DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =========================================================================
-- 5. trade_signals — mirrors SignalAgent.TradeSignal
-- =========================================================================
CREATE TABLE trade_signals (
    id              SERIAL PRIMARY KEY,
    ticker          TEXT NOT NULL,
    action          TEXT NOT NULL,              -- "buy" | "sell" | "hold"
    combined_score  NUMERIC NOT NULL,
    confidence      NUMERIC NOT NULL,
    sentiment_score NUMERIC NOT NULL,
    technical_score NUMERIC NOT NULL,
    volume_signal   NUMERIC NOT NULL,
    rationale       TEXT DEFAULT '',
    anomaly_adjusted BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =========================================================================
-- 6. risk_decisions — mirrors RiskAgent.RiskDecision
-- =========================================================================
CREATE TABLE risk_decisions (
    id                  SERIAL PRIMARY KEY,
    ticker              TEXT NOT NULL,
    approved            BOOLEAN NOT NULL,
    action              TEXT NOT NULL,          -- "buy" | "sell" | "hold"
    proposed_amount_usd NUMERIC NOT NULL,
    adjusted_amount_usd NUMERIC,               -- NULL if rejected
    reason              TEXT DEFAULT '',
    stop_loss_triggered BOOLEAN DEFAULT FALSE,
    trade_signal_id     INT REFERENCES trade_signals(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =========================================================================
-- 7. trade_results — mirrors ExecutionAgent.ExecutionResult
-- =========================================================================
CREATE TABLE trade_results (
    id               SERIAL PRIMARY KEY,
    ticker           TEXT NOT NULL,
    action           TEXT NOT NULL,             -- "buy" | "sell"
    amount_usd       NUMERIC NOT NULL,
    success          BOOLEAN NOT NULL,
    job_id           TEXT,
    response         TEXT DEFAULT '',
    slippage_pct     NUMERIC,                  -- NULL if unparseable
    error            TEXT,
    risk_decision_id INT REFERENCES risk_decisions(id),
    executed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =========================================================================
-- 8. portfolio_snapshots
-- =========================================================================
CREATE TABLE portfolio_snapshots (
    id                  SERIAL PRIMARY KEY,
    total_value_usd     NUMERIC NOT NULL DEFAULT 0,
    positions           JSONB NOT NULL DEFAULT '{}'::JSONB,
    daily_pnl_usd       NUMERIC NOT NULL DEFAULT 0,
    cumulative_pnl_usd  NUMERIC NOT NULL DEFAULT 0,
    max_drawdown_pct    NUMERIC NOT NULL DEFAULT 0,
    snapshot_time       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =========================================================================
-- 9. agent_heartbeats
-- =========================================================================
CREATE TABLE agent_heartbeats (
    id               SERIAL PRIMARY KEY,
    agent_role       TEXT NOT NULL UNIQUE,      -- matches AgentRole enum values
    last_seen        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status           TEXT NOT NULL DEFAULT 'idle',  -- "idle" | "running" | "error"
    cycles_completed INT NOT NULL DEFAULT 0,
    last_error       TEXT,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =========================================================================
-- Indexes
-- =========================================================================
CREATE INDEX idx_trade_signals_ticker_created ON trade_signals (ticker, created_at);
CREATE INDEX idx_risk_decisions_ticker_created ON risk_decisions (ticker, created_at);
CREATE INDEX idx_trade_results_ticker_executed ON trade_results (ticker, executed_at);
CREATE INDEX idx_price_candles_ticker_timestamp ON price_candles (ticker, timestamp);
CREATE INDEX idx_sentiment_scores_ticker_created ON sentiment_scores (ticker, created_at);
CREATE INDEX idx_technical_signals_ticker_created ON technical_signals (ticker, created_at);
CREATE INDEX idx_portfolio_snapshots_time ON portfolio_snapshots (snapshot_time);
