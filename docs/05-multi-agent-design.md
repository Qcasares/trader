# Multi-Agent System Design

**Date:** 2026-02-26
**Document:** Specialist Agent Architecture for Crypto Trading Bot

---

## Design Philosophy

The trading bot is operated by a team of **specialist AI agents**, each backed by an appropriate Claude model. Rather than a monolithic loop where static algorithms make decisions, each agent brings focused expertise and LLM-powered reasoning to its domain. The orchestrator coordinates agent execution, manages data flow, and ensures the pipeline produces high-quality trade decisions.

---

## Agent Roster

### 1. Research Agent (`research`)

**Model:** `claude-haiku-4-5-20251001`
**Cadence:** Every 5 minutes
**Purpose:** Market scanning, trending token discovery, news event detection

**Responsibilities:**
- Fetch trending tokens from CoinGecko
- Collect social media posts from Twitter, Reddit, Farcaster
- Identify breaking news and market-moving events
- Track tweet/post deduplication via `since_id`
- Manage API rate limit budgets for all social sources

**System Prompt Focus:**
- Crypto market awareness and terminology
- News significance assessment (is this tweet noise or signal?)
- Source credibility evaluation

**Inputs:** API credentials, watchlist config, rate limit state
**Outputs:** `raw_social_posts` table, `market_events` table

---

### 2. Sentiment Agent (`sentiment`)

**Model:** `claude-haiku-4-5-20251001`
**Cadence:** Triggered by new data in `raw_social_posts`
**Purpose:** NLP sentiment scoring with contextual interpretation

**Responsibilities:**
- Run VADER sentiment on short social text (with crypto lexicon)
- Run FinBERT on financial-vocabulary posts (>80 chars with financial terms)
- Apply source credibility weighting (follower count, engagement)
- Use Claude to interpret ambiguous or sarcastic sentiment
- Detect sentiment anomalies (sudden floods suggesting coordinated manipulation)
- Track sentiment momentum (is score improving/declining vs previous cycles?)

**System Prompt Focus:**
- Crypto-specific language understanding (irony, slang, memes)
- Distinguishing genuine sentiment from coordinated campaigns
- Financial text interpretation

**Inputs:** Unprocessed rows from `raw_social_posts`
**Outputs:** `sentiment_scores` table with `vader_score`, `finbert_score`, `combined_score`

---

### 3. Technical Agent (`technical`)

**Model:** `claude-haiku-4-5-20251001`
**Cadence:** Every 3 minutes
**Purpose:** Price and volume analysis with pattern recognition

**Responsibilities:**
- Fetch price/volume data from CoinGecko `/market_chart` endpoint
- Calculate RSI (14-period), MACD (12/26/9), Bollinger Bands (20/2σ)
- Calculate OBV and volume ratio for surge detection
- Use Claude to identify chart patterns and interpret indicator confluence
- Detect volume surges (>2x average) as independent events

**System Prompt Focus:**
- Technical analysis expertise (indicator interpretation, divergences)
- Multi-timeframe analysis
- Volume-price relationship understanding

**Inputs:** Price candle history, volume data
**Outputs:** `technical_signals` table, `price_candles` table

---

### 4. Signal Agent (`signal`)

**Model:** `claude-sonnet-4-6`
**Cadence:** Every 15 minutes
**Purpose:** Multi-factor signal fusion and trade decision reasoning

**Responsibilities:**
- Read latest sentiment scores (with 2-cycle momentum check)
- Read latest technical signals
- Read volume data and surge events
- Apply weighted fusion: sentiment 40% + technical 40% + volume 20%
- Use Claude Sonnet for nuanced reasoning about signal confluence
- Generate trade recommendations with detailed rationale
- Enforce minimum confidence threshold (0.55)

**System Prompt Focus:**
- Multi-factor decision making
- Risk-reward assessment
- Market context integration (is this a trending market? ranging? volatile?)
- Explicit reasoning chains with confidence calibration

**Inputs:** `sentiment_scores`, `technical_signals`, `price_candles`, `market_events`
**Outputs:** `trade_signals` table with action, confidence, rationale

---

### 5. Risk Agent (`risk`)

**Model:** `claude-sonnet-4-6`
**Cadence:** Triggered by new approved signals
**Purpose:** Position sizing, risk assessment, portfolio-level controls

**Responsibilities:**
- Evaluate proposed trade against daily loss limit ($200)
- Check per-trade cap ($150)
- Enforce 15-minute cooldown between trades
- Monitor stop-loss levels on open positions
- Check portfolio concentration limits (40% max per token)
- Account for chain-specific gas costs in position sizing
- Use Claude Sonnet to reason about portfolio-level risk

**System Prompt Focus:**
- Risk management principles (Kelly criterion, drawdown management)
- Portfolio theory (diversification, correlation)
- Financial controls and compliance
- Conservative bias — when in doubt, reject

**Inputs:** `trade_signals`, current portfolio state, trade history
**Outputs:** `risk_decisions` table with approved/rejected, adjusted amounts, reasoning

---

### 6. Execution Agent (`execution`)

**Model:** `claude-haiku-4-5-20251001`
**Cadence:** Triggered by approved risk decisions
**Purpose:** bankr.bot API interaction and order management

**Responsibilities:**
- Construct bankr.bot prompts from approved trade signals
- Submit trades via POST `/agent/prompt`
- Poll job status via GET `/agent/job/{jobId}`
- Parse execution results and extract actual fill prices
- Calculate slippage (expected vs actual)
- Handle execution failures with appropriate retry logic
- Log all execution details for audit trail

**System Prompt Focus:**
- Precise prompt construction for bankr.bot
- Error handling and retry decision making
- Execution quality assessment

**Inputs:** Approved `risk_decisions`
**Outputs:** `trade_results` table with execution details, slippage, status

---

### 7. Portfolio Agent (`portfolio`)

**Model:** `claude-sonnet-4-6`
**Cadence:** Every 30 minutes
**Purpose:** Position tracking, P&L analysis, performance reporting

**Responsibilities:**
- Track all open positions with entry prices and current market values
- Calculate unrealised P&L by marking positions to market
- Calculate realised P&L from completed trades
- Monitor portfolio performance vs buy-and-hold benchmark
- Detect drawdown patterns and recommend strategy adjustments
- Generate portfolio snapshots for audit and reporting

**System Prompt Focus:**
- Portfolio management and attribution analysis
- Performance measurement and benchmarking
- Tax-relevant record keeping
- Strategic portfolio insights

**Inputs:** `trade_results`, current prices, portfolio history
**Outputs:** `portfolio_snapshots` table, P&L reports

---

## Orchestrator Design

### `AgentOrchestrator`

The orchestrator is the central coordinator. It:

1. **Initialises all agents** with their configured models and credentials
2. **Manages scheduling** — each agent runs on its own cadence
3. **Routes messages** between agents via the shared database
4. **Monitors health** via heartbeat checks
5. **Handles failures** — restarts stalled agents, logs errors

```
┌─────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR                          │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│  │ Research  │  │ Sentiment│  │Technical │             │
│  │  (5 min)  │  │ (on data)│  │ (3 min)  │             │
│  └─────┬─────┘  └─────┬────┘  └─────┬────┘             │
│        │              │              │                   │
│        └──────────────┼──────────────┘                   │
│                       ▼                                  │
│              ┌──────────────┐                            │
│              │    Signal    │                            │
│              │  (15 min)    │                            │
│              └──────┬───────┘                            │
│                     ▼                                    │
│              ┌──────────────┐                            │
│              │     Risk     │                            │
│              │ (on signal)  │                            │
│              └──────┬───────┘                            │
│                     ▼                                    │
│              ┌──────────────┐                            │
│              │  Execution   │                            │
│              │ (on approval)│                            │
│              └──────┬───────┘                            │
│                     ▼                                    │
│              ┌──────────────┐                            │
│              │  Portfolio   │                            │
│              │  (30 min)    │                            │
│              └──────────────┘                            │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │          SHARED STATE (PostgreSQL)               │    │
│  │  raw_social_posts | price_candles | sentiments  │    │
│  │  trade_signals | risk_decisions | trade_results  │    │
│  │  portfolio_snapshots | agent_heartbeats          │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

### Agent Lifecycle

```
INIT → IDLE → RUNNING → COMPLETED → IDLE → ...
                │                      │
                └──→ FAILED ──→ RETRY ─┘
                                  │
                                  └──→ DEAD (after 3 retries)
```

### Scheduling Strategy

The orchestrator uses `asyncio` tasks with independent sleep intervals:

```python
async def run_agent_loop(agent: BaseAgent, interval_seconds: int):
    while True:
        try:
            await agent.execute(context)
            update_heartbeat(agent.role)
        except Exception as e:
            log_agent_error(agent.role, e)
        await asyncio.sleep(interval_seconds)
```

Event-driven agents (Sentiment, Risk, Execution) poll for new upstream data every 30 seconds rather than sleeping for a fixed interval.

---

## Claude API Usage and Cost Control

### Estimated Token Usage Per Cycle

| Agent | Calls/Cycle | Avg Tokens/Call | Model | Est. Cost/Call |
|---|---|---|---|---|
| Research | 3 (per token) | 1,500 | Haiku | $0.0015 |
| Sentiment | 3 (per token) | 2,000 | Haiku | $0.002 |
| Technical | 3 (per token) | 1,000 | Haiku | $0.001 |
| Signal | 1 | 4,000 | Sonnet | $0.024 |
| Risk | 0-1 | 2,000 | Sonnet | $0.012 |
| Execution | 0-1 | 500 | Haiku | $0.0005 |
| Portfolio | 0.5 (every 30 min) | 3,000 | Sonnet | $0.018 |

**Estimated daily cost (3 tokens, 96 cycles):** ~$8-15/day

### Cost Control Mechanisms

1. **Prompt caching**: Use Anthropic's prompt caching for system prompts (static per agent)
2. **Context trimming**: Only pass relevant data, not full history
3. **Skip cycles**: If no new data since last run, skip the Claude call
4. **Haiku for deterministic tasks**: Don't use Sonnet/Opus when the output is formulaic

---

## Error Handling and Resilience

### Per-Agent Error Handling

Each agent implements:
- **Input validation**: Verify upstream data exists and is fresh
- **Output validation**: Verify agent response contains expected fields
- **Timeout**: Maximum execution time per cycle (configurable, default 60s)
- **Retry with backoff**: Exponential backoff on Claude API failures
- **Circuit breaker**: After 3 consecutive failures, halt agent and alert

### Graceful Degradation

If an upstream agent fails:
- **Research fails**: Sentiment agent uses cached data (stale but available)
- **Sentiment fails**: Signal agent uses technical-only signal (reduced confidence)
- **Technical fails**: Signal agent uses sentiment-only signal (reduced confidence)
- **Signal fails**: No trades execute (safe default)
- **Risk fails**: No trades execute (safe default)
- **Execution fails**: Signal marked as `execution_failed`, retried next cycle
- **Portfolio fails**: No impact on trading, only on reporting

---

## Migration Path from Monolith

### Step 1: Extract Agent Classes
Create concrete agent classes extending `BaseAgent`. Initially, agents call the existing static functions (VADER, RSI, etc.) and add Claude reasoning on top.

### Step 2: Add Database Layer
Replace SQLite with PostgreSQL. Each agent reads/writes to its own tables.

### Step 3: Independent Scheduling
Replace the monolithic `while True` loop with per-agent async tasks.

### Step 4: Add Claude Reasoning
Gradually inject Claude calls into each agent's `execute()` method, replacing hardcoded logic with LLM-reasoned decisions.

### Step 5: Monitoring and Observability
Add structured logging, heartbeats, and performance metrics per agent.

---

*End of Multi-Agent System Design Document*
