# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Automated cryptocurrency trading bot using the **bankr.bot Agent API**. Combines technical analysis (RSI, MACD, Bollinger Bands) with dual-layer social sentiment analysis (VADER + FinBERT) to generate trade signals. Trade execution, wallet management, and gas handling are fully delegated to bankr.bot.

Full spec: `BANKR_TRADING_BOT_POC.md`

## Safety Rules

1. **ALWAYS** verify `DRY_RUN=true` in `.env` before running trade-execution code.
2. All trade amounts **must** pass through `RiskManager.assess()` before execution.
3. The bankr.bot API key starts with `bk_`. If missing from env, raise clearly.
4. Never hardcode API keys — use `os.environ.get()` or `python-dotenv`.
5. Never commit `.env`.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt
python -c "import nltk; nltk.download('vader_lexicon')"

# Run bot
python src/main.py --dry-run     # Safe mode, no real trades
python src/main.py --live        # Live trading — USE WITH CAUTION

# Run all tests
pytest tests/ -v

# Run a single test file
pytest tests/test_sentiment.py -v

# Run a single test
pytest tests/test_sentiment.py::test_function_name -v
```

## Architecture — Multi-Agent System

Seven specialist AI agents coordinated by an `AgentOrchestrator`. Each agent extends `BaseAgent` (`src/agents/base.py`), wraps a Claude model with a focused system prompt, and communicates via shared database state.

```
┌──────────────────────────────────────────────────────┐
│                   ORCHESTRATOR                        │
│                                                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐          │
│  │ Research  │  │Sentiment │  │Technical │          │
│  │ Haiku/5m  │  │Haiku/data│  │ Haiku/3m │          │
│  └─────┬─────┘  └────┬─────┘  └────┬─────┘          │
│        └──────────────┼─────────────┘                │
│                       ▼                              │
│              ┌──────────────┐                        │
│              │    Signal    │                        │
│              │ Sonnet/15m   │                        │
│              └──────┬───────┘                        │
│                     ▼                                │
│              ┌──────────────┐                        │
│              │     Risk     │                        │
│              │Sonnet/signal │                        │
│              └──────┬───────┘                        │
│                     ▼                                │
│              ┌──────────────┐                        │
│              │  Execution   │                        │
│              │Haiku/approval│                        │
│              └──────┬───────┘                        │
│                     ▼                                │
│              ┌──────────────┐                        │
│              │  Portfolio   │                        │
│              │ Sonnet/30m   │                        │
│              └──────────────┘                        │
│                                                      │
│  ┌────────────────────────────────────────────────┐  │
│  │         SHARED STATE (PostgreSQL)              │  │
│  │  raw_social_posts | price_candles | sentiments │  │
│  │  trade_signals | risk_decisions | trade_results│  │
│  │  portfolio_snapshots | agent_heartbeats        │  │
│  └────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────┘
```

### Agent roster

| Agent | Model | Cadence | Responsibility |
|---|---|---|---|
| Research | Haiku | 5 min | Market scanning, trending tokens, social data collection |
| Sentiment | Haiku | On new data | VADER + FinBERT NLP, sarcasm detection, manipulation filtering |
| Technical | Haiku | 3 min | RSI (14), MACD (12/26/9), Bollinger Bands (20/2σ), OBV |
| Signal | Sonnet | 15 min | Multi-factor fusion (sentiment 40% + technical 40% + volume 20%) |
| Risk | Sonnet | On signal | Position sizing, daily loss limit, cooldown, portfolio concentration |
| Execution | Haiku | On approval | bankr.bot prompt construction, job polling, slippage tracking |
| Portfolio | Sonnet | 30 min | P&L tracking, drawdown detection, performance vs benchmark |

### Key modules (all under `src/`)

| Module | Responsibility |
|---|---|
| `agents/` | Specialist agent classes — see [Agent Development](#agent-development) |
| `agents/base.py` | `BaseAgent` ABC, `AgentRole` enum, `AgentResult`/`AgentMessage` dataclasses |
| `bankr_client.py` | Async bankr.bot REST client — prompt submission + job polling |
| `sentiment_engine.py` | VADER (social text) + FinBERT (financial text) dual-layer NLP |
| `technical_analysis.py` | RSI, MACD, Bollinger Bands, OBV calculations |
| `social_collector.py` | Twitter, Reddit, Farcaster, CoinGecko data fetchers |
| `signal_engine.py` | Weighted fusion: sentiment 40% + technical 40% + volume 20% |
| `risk_manager.py` | Daily loss limit, cooldown, position caps, stop-loss |
| `docs/` | Design documents (`05-multi-agent-design.md`, etc.) |

### Signal flow

- Multi-factor confluence: at least 2 confirming signals from different domains required
- Minimum confidence threshold: 0.55 before any trade is dispatched
- Volume amplifies directional score — it does not independently trigger trades
- Graceful degradation: if Research or Sentiment fail, Signal agent runs with reduced confidence; if Signal or Risk fail, no trades execute (safe default)

### bankr.bot API pattern

```
POST /agent/prompt  → returns jobId
GET  /agent/job/{jobId}  → poll until status == "completed"
```

Prompts are plain English: `"Buy $50 of ETH on Base"`

## Database

**Current:** SQLite at `data/bot_state.db` (auto-created by `RiskManager._init_db()`).
**Target:** PostgreSQL (required for multi-agent shared state). Migration replaces SQLite with PostgreSQL; each agent reads/writes its own tables.

Legacy tables: `trades`, `signals`, `portfolio_snapshots`

Multi-agent tables: `raw_social_posts`, `price_candles`, `sentiment_scores`, `technical_signals`, `trade_signals`, `risk_decisions`, `trade_results`, `portfolio_snapshots`, `agent_heartbeats`

Useful queries:
- Why did the bot trade X? → `SELECT * FROM trade_signals WHERE ticker='X'`
- Today's P&L → `SELECT SUM(pnl_usd) FROM trade_results WHERE executed_at >= CURRENT_DATE`
- Agent health → `SELECT * FROM agent_heartbeats ORDER BY last_seen DESC`

## Configuration

- `.env` — API keys (bankr, Twitter, CoinGecko, Neynar)
- `config/bot_config.yaml` — watchlist, risk thresholds, loop interval, position sizing

## Python Conventions

- Python 3.11+, type hints on all functions
- Async/await throughout (`aiohttp`, `asyncio`)
- `logging` module (not `print`) for all output
- Dataclasses for structured data (`TradeResult`, `TechnicalSignal`, `SentimentResult`, `TradeSignal`, `RiskDecision`)
- Supported chains: Base, Ethereum, Polygon, Solana, Unichain (see `Chain` enum in `bankr_client.py`)

## Agent Development

### Creating a new agent

1. Add a role to `AgentRole` enum in `src/agents/base.py`
2. Create `src/agents/<role>.py` extending `BaseAgent`
3. Implement `execute(context) -> AgentResult` and `system_prompt() -> str`
4. Register the agent in the orchestrator with its model and cadence

```python
class MyAgent(BaseAgent):
    def __init__(self, api_key: str) -> None:
        super().__init__(AgentRole.MY_ROLE, "claude-haiku-4-5-20251001", api_key)

    def system_prompt(self) -> str:
        return "You are a specialist in ..."

    async def execute(self, context: dict[str, Any]) -> AgentResult:
        # Do work, call Claude if needed, return self._build_result(...)
        return self._build_result(success=True, data={...})
```

### Model assignments

- **Haiku** (`claude-haiku-4-5-20251001`): Fast/cheap agents — Research, Sentiment, Technical, Execution
- **Sonnet** (`claude-sonnet-4-6`): Reasoning-heavy agents — Signal, Risk, Portfolio

### Agent communication

Agents do not call each other directly. They communicate through shared database tables. The orchestrator passes a `context` dict to each agent's `execute()` containing relevant upstream data. Use `AgentMessage` for structured inter-agent messages routed by the orchestrator.
