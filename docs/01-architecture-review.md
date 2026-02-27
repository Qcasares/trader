# Architecture Review Report

**Date:** 2026-02-26
**Reviewer:** Architecture Review Agent
**Document:** `BANKR_TRADING_BOT_POC.md` v1.0

---

## Executive Summary

The POC specification describes a functionally complete crypto trading bot with a sound signal pipeline, but the architecture as written is a **monolithic async loop with zero LLM reasoning** in the analytical pipeline. The spec delegates all intelligence to bankr.bot's execution layer while using static algorithms (VADER, RSI, MACD) for signal generation. For the multi-agent transformation, this represents an opportunity to inject Claude-powered reasoning at every analytical stage.

---

## Architectural Weaknesses Identified

### 1. Monolithic Orchestration

The entire pipeline (data collection, sentiment, technical analysis, signal fusion, risk assessment, execution) runs in a single `while True` loop in `main.py`. This creates:

- **Single point of failure**: any uncaught exception kills the entire bot
- **Cadence coupling**: all stages must complete within the 15-minute window
- **No independent scaling**: can't run sentiment analysis more frequently than price polling

### 2. No LLM Reasoning in the Pipeline

Despite being described as an "AI-powered" trading bot, the analytical pipeline uses only static algorithms. VADER and FinBERT are pre-trained models with no contextual reasoning about market conditions, news context, or cross-token correlations. The Claude models should be injected at decision points.

### 3. Volume Data is Non-functional

The CoinGecko OHLCV endpoint does not return volume data. The spec acknowledges this with a placeholder `[1.0] * len(closes)`, making the volume component (20% of signal weight) permanently silent.

### 4. P&L Tracking is Broken

The `pnl_usd` column in the trades table defaults to `0.0` and is never updated with actual profit/loss. This means the daily loss limit check (`SUM(pnl_usd)`) always returns 0, rendering the safety control non-functional.

### 5. Stop-loss Declared but Not Implemented

The config includes `stop_loss_pct: 8.0` but no code monitors open positions against their entry price. The risk manager stores the value but never acts on it.

### 6. DRY_RUN Safety Gap

Dry-run mode prepends `[SIMULATION - DO NOT EXECUTE]` to the prompt but still sends it to the live bankr.bot API. The API may or may not respect this prefix, creating ambiguity about whether real trades could execute.

---

## Recommended Agent Topology

### 5+2 Agent Architecture

| Agent | Model | Role | Cadence |
|---|---|---|---|
| **Research Agent** | Haiku | Market scanning, trending tokens, news gathering | 5 min |
| **Sentiment Agent** | Haiku | Social NLP with VADER/FinBERT + Claude interpretation | On new data |
| **Technical Agent** | Haiku | RSI, MACD, Bollinger, volume analysis with pattern reasoning | 3 min |
| **Signal Agent** | Sonnet | Multi-factor fusion, trade decision reasoning | 15 min |
| **Risk Agent** | Sonnet | Position sizing, loss limits, portfolio risk assessment | On signal |
| **Execution Agent** | Haiku | bankr.bot API interaction, order management | On approval |
| **Portfolio Agent** | Sonnet | Position tracking, P&L analysis, rebalancing | 30 min |

### Model Selection Rationale

- **Haiku** for data-intensive, low-latency tasks (ingestion, scoring, execution) — fast and cheap
- **Sonnet** for reasoning-heavy tasks (signal fusion, risk assessment, portfolio analysis) — better at complex multi-factor reasoning
- **Opus** reserved for potential future use: market regime detection, strategy adaptation

### Agent Communication

Agents communicate via a shared PostgreSQL database (replacing SQLite). Each agent reads from tables written by upstream agents and writes results for downstream consumers.

```
Research Agent  ──writes──→  raw_social_posts, market_events
     │
     ▼
Sentiment Agent ──writes──→  sentiment_scores
     │
     ▼
Technical Agent ──writes──→  technical_signals
     │
     ▼
Signal Agent    ──reads all──→ writes trade_signals
     │
     ▼
Risk Agent      ──reads signals──→ writes risk_decisions
     │
     ▼
Execution Agent ──reads approved──→ writes trade_results
     │
     ▼
Portfolio Agent ──reads all──→ writes portfolio_snapshots
```

---

## Implementation Sequence

### Phase 1: Foundation (Current)
- Project scaffold with agent base class
- Configuration with model assignments
- Shared state store schema

### Phase 2: Data Layer
- Replace SQLite with PostgreSQL (Neon free tier)
- Implement CoinGecko `/market_chart` endpoint for real volume data
- Add tweet deduplication with `since_id`

### Phase 3: Agent Implementation
- Implement each agent as a subclass of `BaseAgent`
- Wire up Anthropic SDK calls with agent-specific system prompts
- Implement inter-agent message passing

### Phase 4: Orchestration
- Build the orchestrator that manages agent lifecycles
- Implement independent cadence scheduling per agent
- Add agent health monitoring and heartbeats

### Phase 5: Safety and Testing
- Fix P&L tracking with actual trade outcome monitoring
- Implement stop-loss monitoring agent
- End-to-end integration tests with mocked APIs

---

## Key Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Claude API costs at 15-min cycles | Medium | Use Haiku for high-frequency agents, cache prompts |
| Agent coordination failures | High | Implement agent heartbeat monitoring, dead-letter queue |
| Rate limit exhaustion | High | Centralise API credentials per agent, budget tracking |
| Signal quality degradation | Medium | Log all agent reasoning, compare agent vs static signals |

---

*End of Architecture Review Report*
