# Setup Guide

Complete setup instructions for the automated crypto trading bot.

## Prerequisites

- Python 3.9+ (tested with 3.9.6 and 3.11+)
- PostgreSQL 14+
- API keys for: Anthropic, bankr.bot, CoinGecko, Twitter/X (optional), Neynar (optional)

## 1. Clone and Install

```bash
git clone <repo-url> trader
cd trader

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Download NLTK data for sentiment analysis
python3 -c "import nltk; nltk.download('vader_lexicon')"
```

### Dependency Notes

| Package | Purpose | Required |
|---------|---------|----------|
| anthropic | Claude API for agent intelligence | Yes |
| aiohttp | Async HTTP for bankr.bot API | Yes |
| asyncpg | Async PostgreSQL driver | Yes |
| python-dotenv | .env file loading | Yes |
| pyyaml | Config file parsing | Yes |
| nltk | VADER sentiment analysis | Yes |
| transformers + torch | FinBERT sentiment (downloads ~500MB model on first run) | Yes |
| pandas, numpy | Data processing for technical analysis | Yes |
| tweepy | Twitter data collection | Optional |
| praw | Reddit data collection | Optional |

## 2. Environment Variables

Copy the example file and fill in your keys:

```bash
cp .env.example .env
```

Edit `.env`:

```bash
# Required — bot will not start without these
ANTHROPIC_API_KEY=sk-ant-your_key_here
BANKR_API_KEY=bk_your_key_here          # Must start with "bk_"
DATABASE_URL=postgresql://user:password@localhost:5432/trader

# Required for data collection
COINGECKO_API_KEY=CG-your_key_here       # Free tier at coingecko.com/en/api

# Optional — enhances social sentiment coverage
TWITTER_BEARER_TOKEN=your_bearer_token   # developer.twitter.com
NEYNAR_API_KEY=your_neynar_key           # neynar.com (Farcaster data)

# Safety flag — keep "true" until you're ready for live trading
DRY_RUN=true

# Logging
LOG_LEVEL=INFO
```

### Getting API Keys

| Key | Where | Notes |
|-----|-------|-------|
| ANTHROPIC_API_KEY | [console.anthropic.com](https://console.anthropic.com) | Requires billing. Uses Haiku (cheap) + Sonnet (reasoning). |
| BANKR_API_KEY | [bankr.bot/api](https://bankr.bot/api) | Must start with `bk_`. Handles wallet + gas + execution. |
| DATABASE_URL | Your PostgreSQL instance | Format: `postgresql://user:pass@host:port/dbname` |
| COINGECKO_API_KEY | [coingecko.com/en/api](https://www.coingecko.com/en/api) | Free demo tier is sufficient. |
| TWITTER_BEARER_TOKEN | [developer.twitter.com](https://developer.twitter.com) | Optional. Requires approved developer account. |
| NEYNAR_API_KEY | [neynar.com](https://neynar.com) | Optional. For Farcaster social data. |

## 3. Database Setup

### Create the Database

```bash
# Connect to PostgreSQL
psql -U postgres

# Create database and user
CREATE DATABASE trader;
CREATE USER trader_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE trader TO trader_user;
\q
```

### Run the Schema

```bash
psql -U trader_user -d trader -f src/db/schema.sql
```

This creates 9 tables:

| Table | Purpose |
|-------|---------|
| `raw_social_posts` | Twitter, Reddit, Farcaster posts collected by ResearchAgent |
| `price_candles` | OHLCV price data from CoinGecko |
| `sentiment_scores` | VADER + FinBERT NLP scores per ticker |
| `technical_signals` | RSI, MACD, Bollinger Bands, OBV indicators |
| `trade_signals` | Multi-factor fusion decisions from SignalAgent |
| `risk_decisions` | Approved/rejected trades from RiskAgent |
| `trade_results` | Execution outcomes from bankr.bot |
| `portfolio_snapshots` | P&L tracking, drawdown detection |
| `agent_heartbeats` | Health monitoring (one row per agent) |

### Verify Schema

```bash
psql -U trader_user -d trader -c "\dt"
```

You should see all 9 tables listed.

## 4. Configuration

Edit `config/bot_config.yaml` to customize:

### Watchlist

```yaml
watchlist:
  - ticker: ETH
    coingecko_id: ethereum
    chain: Base
    enabled: true
  - ticker: SOL
    coingecko_id: solana
    chain: Solana
    enabled: true
  - ticker: BNKR
    coingecko_id: bankr-bot
    chain: Base
    enabled: false       # Enable when comfortable
```

Supported chains: `Base`, `Ethereum`, `Polygon`, `Solana`, `Unichain`

### Risk Controls

```yaml
risk:
  max_daily_loss_usd: 200.0    # Stop all trading after $200 daily loss
  max_single_trade_usd: 150.0  # Cap per trade
  cooldown_minutes: 15          # Wait between trades on same ticker
  stop_loss_pct: 8.0            # Sell if position drops 8%
  min_confidence: 0.55          # Minimum signal confidence to trade

position:
  base_usd: 25.0               # Minimum trade size
  max_usd: 150.0               # Maximum trade size (scales with confidence)
```

### Loop Timing

```yaml
loop:
  interval_minutes: 15          # Main pipeline runs every 15 min
  sentiment_hours_back: 1       # Look at last 1 hour of social data
  technical_candles: 50         # Use 50 candles for indicator calculation
```

## 5. Running the Bot

### Dry-Run Mode (Safe — Default)

```bash
python3 src/main.py --dry-run
```

All trade prompts are prefixed with `[SIMULATION — DO NOT EXECUTE]`. No real money moves.

### Live Trading Mode

Requires **two** safety gates:

1. Pass `--live` flag
2. Set `DRY_RUN=false` in `.env`

```bash
# In .env, change:
DRY_RUN=false

# Then run:
python3 src/main.py --live
```

If either gate is missing, the bot refuses to start.

### CLI Options

```
python3 src/main.py [OPTIONS]

Options:
  --dry-run              Safe mode, no real trades (default)
  --live                 Live trading — REAL MONEY AT RISK
  --log-level LEVEL      DEBUG, INFO, WARNING, ERROR
  --config PATH          Config file path (default: config/bot_config.yaml)
```

### Stopping the Bot

Press `Ctrl+C` (sends SIGINT). The bot will:

1. Finish the current cycle
2. Close database connections
3. Exit cleanly

## 6. Running Tests

```bash
# All tests (84 total)
python3 -m pytest tests/ -v

# Unit tests only (65 tests)
python3 -m pytest tests/unit/ -v

# Integration tests only (19 tests)
python3 -m pytest tests/integration/ -v

# Single test file
python3 -m pytest tests/unit/test_risk_agent.py -v

# Single test
python3 -m pytest tests/unit/test_risk_agent.py::TestPositionSizing::test_base_at_zero_confidence -v
```

Tests use mocks for all external services — no API keys or database needed.

## 7. How It Works

The bot runs a 7-agent pipeline every 15 minutes:

```
Research → Sentiment → Technical → Signal → Risk → Execution
                                                        ↓
                                                   Portfolio (every 30 min)
```

| Step | Agent | What It Does |
|------|-------|-------------|
| 1 | Research | Scans Twitter, Reddit, Farcaster, CoinGecko for market data |
| 2 | Sentiment | Runs VADER + FinBERT NLP on collected posts |
| 3 | Technical | Calculates RSI, MACD, Bollinger Bands, OBV from price data |
| 4 | Signal | Fuses scores (40% sentiment + 40% technical + 20% volume) |
| 5 | Risk | Enforces position sizing, loss limits, cooldowns |
| 6 | Execution | Submits approved trades to bankr.bot API |
| 7 | Portfolio | Tracks P&L, drawdown, positions (runs every 2nd cycle) |

Each agent passes results via a shared context dict. If any agent fails, the pipeline continues with available data (graceful degradation).

## 8. Monitoring

### Agent Health

```sql
SELECT agent_role, status, last_seen, cycles_completed, last_error
FROM agent_heartbeats
ORDER BY last_seen DESC;
```

### Today's Trades

```sql
SELECT ticker, action, amount_usd, success, slippage_pct, executed_at
FROM trade_results
WHERE executed_at >= CURRENT_DATE
ORDER BY executed_at DESC;
```

### Today's P&L

```sql
SELECT SUM(
  CASE WHEN action = 'sell' THEN amount_usd ELSE -amount_usd END
) AS daily_pnl
FROM trade_results
WHERE executed_at >= CURRENT_DATE AND success = true;
```

### Why Did It Trade X?

```sql
SELECT ts.ticker, ts.action, ts.confidence, ts.rationale,
       rd.approved, rd.reason, rd.adjusted_amount_usd
FROM trade_signals ts
JOIN risk_decisions rd ON rd.trade_signal_id = ts.id
WHERE ts.ticker = 'ETH'
ORDER BY ts.created_at DESC
LIMIT 5;
```

### Portfolio History

```sql
SELECT snapshot_time, total_value_usd, daily_pnl_usd,
       cumulative_pnl_usd, max_drawdown_pct
FROM portfolio_snapshots
ORDER BY snapshot_time DESC
LIMIT 10;
```

## 9. Project Structure

```
trader/
├── config/
│   └── bot_config.yaml          # Watchlist, risk limits, agent models
├── docs/                         # Architecture and design documents
├── src/
│   ├── agents/
│   │   ├── base.py              # BaseAgent ABC, AgentRole enum, AgentResult
│   │   ├── research.py          # Market scanning, social data collection
│   │   ├── sentiment.py         # VADER + FinBERT NLP analysis
│   │   ├── technical.py         # RSI, MACD, Bollinger Bands, OBV
│   │   ├── signal.py            # Multi-factor fusion, Claude reasoning
│   │   ├── risk.py              # Position sizing, 5 risk controls
│   │   ├── execution.py         # bankr.bot trade submission
│   │   └── portfolio.py         # P&L tracking, drawdown detection
│   ├── db/
│   │   ├── schema.sql           # PostgreSQL 9-table schema
│   │   ├── connection.py        # Async connection pool
│   │   └── repositories.py      # 16 typed query functions
│   ├── bankr_client.py          # Async bankr.bot API client
│   ├── orchestrator.py          # Agent coordination, pipeline execution
│   └── main.py                  # CLI entry point
├── tests/
│   ├── conftest.py              # Shared test fixtures
│   ├── unit/                    # 65 unit tests
│   └── integration/             # 19 integration tests
├── .env.example                 # Environment variable template
├── .gitignore
├── requirements.txt
└── pyproject.toml
```

## 10. Troubleshooting

### Bot Won't Start

| Error | Fix |
|-------|-----|
| `Missing required environment variables` | Check `.env` has ANTHROPIC_API_KEY, BANKR_API_KEY, DATABASE_URL |
| `BANKR_API_KEY must start with 'bk_'` | Verify your bankr.bot key format |
| `LIVE mode requested but DRY_RUN env is 'true'` | Set `DRY_RUN=false` in `.env` for live mode |
| `Config file not found` | Ensure `config/bot_config.yaml` exists |
| `connection refused` on database | Check PostgreSQL is running and DATABASE_URL is correct |

### Import Errors

```bash
# If nltk data missing
python3 -c "import nltk; nltk.download('vader_lexicon')"

# If torch/transformers missing (FinBERT)
pip install transformers torch
```

### Test Failures

```bash
# Run with verbose output
python3 -m pytest tests/ -v --tb=long

# Tests don't need API keys or database — if they fail,
# it's likely a dependency issue
pip install -r requirements.txt
```
