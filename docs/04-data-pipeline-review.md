# Data Pipeline Architecture Review

**Date:** 2026-02-26
**Reviewer:** Data Pipeline Architect Agent
**Document:** `BANKR_TRADING_BOT_POC.md` v1.0

---

## Executive Summary

The POC describes a functionally coherent single-process trading bot with a sound multi-factor signal philosophy. The async foundation, conservative 0.55 confidence floor, and graceful degradation patterns are all correct. However, the architecture has structural gaps that will cause silent failures in production: the CoinGecko OHLCV endpoint silently omits volume data; the 15-minute monolithic loop is too slow for the sentiment-momentum strategy; the SQLite persistence model creates both a reliability ceiling and a multi-agent coordination problem; and the Twitter API budget does not close for a multi-token watchlist.

---

## Pipeline Strengths

1. **Async-native foundation** — `aiohttp` with `asyncio.gather` for parallel social collection is correct
2. **Conservative signal philosophy** — Multi-factor confluence with 0.55 floor is appropriate for live-money
3. **Crypto-domain VADER extension** — Custom lexicon (`lfg`, `wagmi`, `rekt`, `ngmi`) materially improves Twitter accuracy
4. **Risk manager as final gate** — `RiskManager.assess()` as last checkpoint before execution is right
5. **Graceful degradation** — `SocialBatch.error` field allows partial failures without killing the loop
6. **DRY_RUN as first-class concept** — Simulation prefix is a pragmatic safety measure

---

## Pipeline Gaps

### Gap 1: Volume Data is Non-functional (CRITICAL)

The `main.py` comment reads:
```python
# CoinGecko does not return volume in OHLCV endpoint —
# use a flat series as placeholder
volumes = pd.Series([1.0] * len(closes))
```

This makes `volume_ratio` always `1.0`, OBV meaningless, and the volume component (20% of signal weight) permanently silent. The "Volume Surge Detection" strategy described in Section 4.1 cannot trigger.

**Fix:** Replace `/coins/{id}/ohlc` with `/coins/{id}/market_chart` which returns `prices`, `market_caps`, and `total_volumes` arrays with real data at the free tier.

### Gap 2: 15-Minute Loop Misaligned with Sentiment Strategy (HIGH)

The spec states social media leads price by 15-90 minutes. With the 15-min loop plus evaluation/execution latency, actual signal-to-trade lag is 17-25 minutes — potentially after the price move. Additionally:
- 1-hour lookback re-processes the same tweets every cycle without deduplication
- Volume surges dissipate in 5-10 minutes, invisible at 15-min resolution

**Fix:** Decouple ingestion (5-min), price polling (3-min), and signal evaluation (15-min) into separate agent cadences.

### Gap 3: Twitter API Budget Does Not Close (HIGH)

With 3 tokens x 96 cycles/day x 100 tweets/request = 864,000 tweets/month vs 500,000/month Basic tier cap.

**Fix:** Reduce `MAX_RESULTS` to 25-30, implement `since_id` deduplication, weight Farcaster more for bankr.bot-native tokens.

### Gap 4: CoinGecko Free Tier Ceiling (MEDIUM)

3 tokens x 96 cycles/day = 8,640 calls/month approaching the 10,000/month free limit. Adding trending calls pushes beyond.

**Fix:** Batch endpoints (`/coins/markets` with comma-separated IDs), cache trending for 30 min.

### Gap 5: Reddit JSON API Instability (MEDIUM)

The anonymous `reddit.com/search.json` endpoint is fragile since Reddit's 2023 API changes. Pushshift reference is outdated.

**Fix:** Replace with PRAW + OAuth2 for reliable authenticated access.

### Gap 6: SQLite Breaks Under Multi-Agent Parallelism (HIGH)

SQLite WAL mode allows one writer at a time. Multiple agents writing concurrently will produce `database is locked` errors.

**Fix:** Migrate to PostgreSQL for row-level locking, `LISTEN/NOTIFY`, and native JSONB.

### Gap 7: No Signal Deduplication (MEDIUM)

No mechanism detects that the same market condition generates the same BUY signal on consecutive cycles. The bot doesn't model "we are already long ETH."

### Gap 8: OBV Not Wired Into Signal (LOW)

`calculate_obv()` exists but is never called. `TechnicalSignal` has no `obv` field. The function is dead code.

### Gap 9: FinBERT Blocks the Event Loop (HIGH)

`FinBERTAnalyser.score()` is synchronous CPU-bound work called inside the async loop. On 3+ tokens, this blocks the event loop during inference.

**Fix:** Wrap in `asyncio.run_in_executor()` with a dedicated `ThreadPoolExecutor(max_workers=1)`.

---

## Data Quality Concerns

### DQ-1: Spam Filtering is Minimal
Current: `min_faves: 5` on Twitter, `len(text) > 10` on Reddit. Insufficient for crypto spam, coordinated pumps, and copy-paste bridge bots.

**Fix:** Add `-has:links`, minimum follower count (100), `author_id` filtering.

### DQ-2: 100-Character Routing Threshold is a Poor Proxy
Length doesn't indicate financial content quality. A 95-char analyst post has more signal than a 200-char spam post.

**Fix:** Route to FinBERT based on financial vocabulary presence, not length.

### DQ-3: No Source Credibility Weighting
All posts within a source are treated equally. A 5-like anonymous tweet = a 500k-follower analyst post.

**Fix:** Weight by `log(1 + followers_count)` before averaging.

### DQ-4: Sentiment History Missing
`SentimentResult` is point-in-time only. The spec requires "sustained for 2 consecutive cycles" but `signal_engine.py` doesn't check history.

**Fix:** Persist sentiment scores to database, query last N results before aggregation.

### DQ-5: Farcaster Sybil Resistance Unused
Farcaster has wallet-based identity but the collector treats all casts equally. Should use `reactions` and `follower_count`.

---

## Multi-Agent Data Architecture

### Recommended Agent Cadences

| Agent | Cadence | Data Owned |
|---|---|---|
| Ingestion Agent | 5 min | `raw_social_posts` |
| Price Agent | 3 min | `price_candles` |
| Sentiment Agent | On new data | `sentiment_scores` |
| Signal Agent | 15 min | `trade_signals` |
| Risk/Execution Agent | On signal | `trade_results` |

### Shared State: PostgreSQL Schema

```sql
CREATE TABLE agent_heartbeats (
    agent_name   TEXT PRIMARY KEY,
    last_seen_at TIMESTAMPTZ NOT NULL,
    status       TEXT NOT NULL DEFAULT 'healthy',
    metadata     JSONB
);

CREATE TABLE raw_social_posts (
    id              BIGSERIAL PRIMARY KEY,
    ticker          TEXT NOT NULL,
    source          TEXT NOT NULL,
    post_id         TEXT,
    post_text       TEXT NOT NULL,
    author_id       TEXT,
    follower_count  INTEGER,
    platform_score  INTEGER,
    fetched_at      TIMESTAMPTZ NOT NULL,
    processed_at    TIMESTAMPTZ,
    cycle_id        UUID NOT NULL
);

CREATE TABLE sentiment_scores (
    id              BIGSERIAL PRIMARY KEY,
    ticker          TEXT NOT NULL,
    source          TEXT NOT NULL,
    cycle_id        UUID NOT NULL,
    vader_score     FLOAT NOT NULL,
    finbert_score   FLOAT,
    combined_score  FLOAT NOT NULL,
    post_count      INTEGER NOT NULL,
    scored_at       TIMESTAMPTZ NOT NULL
);

CREATE TABLE price_candles (
    id          BIGSERIAL PRIMARY KEY,
    ticker      TEXT NOT NULL,
    candle_ts   TIMESTAMPTZ NOT NULL,
    close       FLOAT NOT NULL,
    volume      FLOAT NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL,
    UNIQUE (ticker, candle_ts)
);

CREATE TABLE trade_signals (
    id                  BIGSERIAL PRIMARY KEY,
    ticker              TEXT NOT NULL,
    cycle_id            UUID NOT NULL,
    action              TEXT NOT NULL,
    confidence          FLOAT NOT NULL,
    sentiment_score     FLOAT NOT NULL,
    technical_score     FLOAT NOT NULL,
    volume_ratio        FLOAT NOT NULL,
    rationale           TEXT,
    approved            BOOLEAN NOT NULL DEFAULT FALSE,
    generated_at        TIMESTAMPTZ NOT NULL,
    executed_at         TIMESTAMPTZ
);
```

### API Credential Ownership

| Agent | Credentials |
|---|---|
| Ingestion | `TWITTER_BEARER_TOKEN`, `NEYNAR_API_KEY`, Reddit OAuth |
| Price | `COINGECKO_API_KEY` |
| Sentiment | None (reads from DB) |
| Signal | None (reads from DB) |
| Risk/Execution | `BANKR_API_KEY` |

### Rate Limit Budget Tracking

Each agent should maintain a `RateLimitBudget` tracking monthly consumption against caps, with daily budget calculation based on remaining quota and days left in month.

---

## Priority Fix Order

1. **CRITICAL** — Volume data: Replace flat placeholder with `/market_chart` real data
2. **HIGH** — FinBERT blocking: Wrap in `run_in_executor()`
3. **HIGH** — Reddit collector: Replace with PRAW + OAuth2
4. **HIGH** — Twitter deduplication: Implement `since_id` tracking
5. **MEDIUM** — Sentiment history: Add persistence and 2-cycle momentum check
6. **MEDIUM** — PostgreSQL migration: Required before multi-agent deployment
7. **MEDIUM** — FinBERT routing: Financial vocabulary check over length
8. **LOW** — Post credibility weighting: Follower-based scoring
9. **LOW** — CoinGecko trending cache: 30-min cache

---

*End of Data Pipeline Architecture Review*
