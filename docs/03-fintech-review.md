# Fintech Engineering Review

**Date:** 2026-02-26
**Reviewer:** Fintech Engineering Agent
**Document:** `BANKR_TRADING_BOT_POC.md` v1.0
**Severity Scale:** CRITICAL / HIGH / MEDIUM / LOW

---

## Executive Summary

The POC specification has **3 CRITICAL**, **6 HIGH**, and **5 MEDIUM** fintech engineering findings. The most consequential issue is that P&L tracking is non-functional: the `pnl_usd` column always defaults to `0.0`, making the daily loss limit — the bot's primary safety mechanism — permanently disabled.

---

## CRITICAL Findings

### FT-C1: Broken P&L Tracking

**Location:** `risk_manager.py` — `log_trade()` method, `trades` table schema

The `trades` table defines `pnl_usd REAL DEFAULT 0.0`. The `log_trade()` method inserts rows with this default and never updates them with actual profit/loss. Consequently:

- `get_daily_pnl()` always returns `0.0`
- The `max_daily_loss_usd` check never triggers
- The bot can lose unlimited money in a single day

**Impact:** The primary financial safety control is non-functional.

**Fix:** Implement trade outcome tracking:
1. On BUY: record entry price and amount in a `positions` table
2. On SELL: calculate P&L from entry price vs sell price
3. Update `pnl_usd` in the `trades` table with actual realised P&L
4. For unrealised P&L: periodically mark positions to market using CoinGecko price

### FT-C2: Missing Slippage Protection

**Location:** Trade execution flow

The bot submits a dollar amount (e.g., "$50 of ETH") to bankr.bot as a natural language prompt. There is no:
- Slippage tolerance parameter
- Minimum acceptable output amount
- Price verification before vs after execution

On volatile mid-cap tokens (BNKR), slippage of 5-15% is common. The bot could consistently lose money on every trade due to execution slippage alone.

**Fix:**
- Fetch current price before trade submission
- Calculate expected token amount
- After trade completes, verify actual execution price
- Log slippage percentage and halt trading if slippage exceeds threshold (e.g., 3%)

### FT-C3: Position Sizing Discontinuity at 0.55 Threshold

**Location:** `signal_engine.py` — `aggregate_signals()`, position sizing logic

Position sizing uses a linear interpolation between `base_usd` ($25) and `max_usd` ($150) based on confidence. At exactly 0.55 confidence, the position jumps from $0 (HOLD) to $25 (minimum trade). This creates a step function where a minuscule score change (0.549 -> 0.551) triggers a $25 trade.

**Fix:** Implement a graduated entry zone:
- 0.50-0.55: micro position ($10-$15) with reduced conviction
- 0.55-0.70: standard linear scaling ($25-$75)
- 0.70+: high conviction ($75-$150)

Or implement a confirmation requirement: score must exceed 0.55 for 2 consecutive cycles before trading.

---

## HIGH Findings

### FT-H1: Stop-loss Not Implemented

The config declares `stop_loss_pct: 8.0` and the risk manager stores this value, but no code monitors open positions against their entry price. A token could drop 50% with no automated exit.

**Fix:** Add a position monitoring loop that checks current price against entry price and triggers a SELL when the stop-loss threshold is breached.

### FT-H2: Concentration Limit Stored but Never Enforced

The spec mentions a 40% portfolio concentration limit but `assess()` does not check current portfolio composition before approving trades. The bot could go 100% into a single token.

**Fix:** Track portfolio allocation per token and reject BUY signals that would exceed the concentration limit.

### FT-H3: Gas Cost Asymmetry Across Chains

Gas costs vary dramatically across supported chains:
- Ethereum: $5-50+ per swap
- Base/Polygon: $0.01-0.10
- Solana: $0.001-0.01

A $25 minimum trade on Ethereum could have a 20-200% gas overhead, making the trade unprofitable by definition. The position sizing does not account for chain-specific gas costs.

**Fix:** Add per-chain minimum trade thresholds that ensure gas costs are < 5% of trade value.

### FT-H4: No Tax Audit Trail

The `trades` table lacks fields required for tax reporting:
- No acquisition cost basis
- No holding period tracking (short-term vs long-term)
- No realized gain/loss calculation
- No FIFO/LIFO accounting method

**Fix:** Add `cost_basis_usd`, `acquisition_date`, `disposal_date`, `holding_period_days`, and `realized_gain_usd` columns.

### FT-H5: SELL Logic is Incomplete

The spec focuses almost entirely on BUY signals. SELL signals are generated when conditions reverse, but there is no:
- Profit-taking strategy (e.g., sell 50% at 2x, rest at 3x)
- Time-based exit (positions held indefinitely if conditions don't reverse)
- Portfolio rebalancing trigger

### FT-H6: bankr.bot Job Failure Handling

If a bankr.bot job fails or times out, the bot logs a warning and continues. But the signal has already been marked as "approved" in the database. There is no retry mechanism and no way to distinguish "approved but failed to execute" from "approved and executed successfully."

**Fix:** Add `execution_status` field to signals/trades: `pending`, `submitted`, `completed`, `failed`, `timed_out`.

---

## MEDIUM Findings

### FT-M1: No Market Hours Awareness

Crypto trades 24/7, but liquidity varies significantly. Trading during low-liquidity periods (weekends, Asian market hours for Western tokens) increases slippage risk.

### FT-M2: Position Sizing Ignores Current Holdings

If the bot already holds ETH and generates another BUY signal, it will buy more without considering existing exposure. This compounds the concentration limit gap.

### FT-M3: No Drawdown Circuit Breaker

Beyond the daily loss limit ($200), there is no weekly or monthly drawdown circuit breaker. A series of daily $199 losses would not trigger any alert.

### FT-M4: Fee Accounting Missing

Trading fees (bankr.bot fees, DEX swap fees, gas) are not deducted from P&L calculations, overstating profitability.

### FT-M5: No Benchmark Comparison

The bot has no mechanism to compare its performance against a simple buy-and-hold strategy, making it impossible to evaluate whether active trading adds value.

---

## Recommended Financial Controls Checklist

- [ ] Fix P&L tracking with actual realised gains/losses
- [ ] Implement slippage monitoring with halt threshold
- [ ] Add stop-loss position monitoring
- [ ] Enforce concentration limits
- [ ] Add per-chain minimum trade sizes
- [ ] Track execution status lifecycle
- [ ] Implement drawdown circuit breaker
- [ ] Add tax-relevant fields to trade records

---

*End of Fintech Engineering Review*
