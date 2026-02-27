---
phase: 01-signal-risk-agents
plan: 02
subsystem: agents
tags: [risk-management, position-sizing, stop-loss, cooldown, concentration, claude-sonnet]

# Dependency graph
requires:
  - phase: 01-signal-risk-agents/01-01
    provides: TradeSignal dataclass consumed by RiskAgent
provides:
  - RiskAgent with 5 risk controls
  - RiskDecision dataclass for downstream consumption
  - Rule-based fallback when Claude unavailable
affects: [phase-2-execution-agent, phase-4-orchestrator]

# Tech tracking
tech-stack:
  added: [anthropic AsyncAnthropic]
  patterns: [one-way Claude override (reject only), stateless risk via context dict, linear position sizing, stop-loss detection]

key-files:
  created: [src/agents/risk.py]
  modified: [src/agents/__init__.py]

key-decisions:
  - "RiskAgent is fully stateless — no SQLite, all state via context dict"
  - "Claude can downgrade (approve→reject) but CANNOT upgrade (reject→approve)"
  - "MIN_TRADE_USD = $5.00 prevents dust transactions"

patterns-established:
  - "Position sizing: base + (max - base) * confidence, capped at max_single_trade"
  - "Daily loss limit blocks ALL signals when breached"
  - "Cooldown per ticker using ISO timestamp comparison"
  - "Concentration check reduces or rejects buys exceeding 40% allocation"
  - "Stop-loss: generates sell RiskDecision for positions dropping > 8%"
  - "One-way Claude merge: can add caution, cannot remove it"

# Metrics
duration: ~10min
started: 2026-02-27
completed: 2026-02-27
---

# Phase 1 Plan 02: RiskAgent Summary

**Risk management agent with 5 safety controls (position sizing, daily loss, cooldown, concentration, stop-loss) and one-way Claude override — 677 lines.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~10 min |
| Started | 2026-02-27 |
| Completed | 2026-02-27 |
| Tasks | 2 completed |
| Files modified | 2 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Position Sizing Based on Confidence | Pass | Linear scale $25–$150 by confidence, capped at max_single_trade. Verified: 0.0→$25, 0.5→$87.50, 1.0→$150 |
| AC-2: Daily Loss Limit Enforcement | Pass | All signals rejected when daily_pnl <= -$200. Verified with test |
| AC-3: Trade Cooldown Per Ticker | Pass | ISO timestamp comparison with 15-min window. Remaining time in reason |
| AC-4: Portfolio Concentration Limit | Pass | Reduces buy amount or rejects if >40% allocation. Verified with 35%+20% scenario |
| AC-5: Stop-Loss Flag Detection | Pass | Generates sell RiskDecision for positions dropping >8%. Verified: 10% drop triggers, 5% does not |
| AC-6: Claude Sonnet Risk Reasoning | Pass | Structured prompt with decisions + portfolio state. JSON parsing with merge logic |
| AC-7: Graceful Fallback on Claude Failure | Pass | Returns pre-computed rule-based decisions on API failure |

## Accomplishments

- Created `RiskAgent` extending `BaseAgent` with full `execute()` → `AgentResult` pipeline
- Implemented 5 independent risk controls: position sizing, daily loss, cooldown, concentration, stop-loss
- One-way Claude merge: can reject approved trades, reduce sizes, but cannot override hard rejections
- Fully stateless design — all portfolio state comes via context dict (no SQLite dependency)
- 12/12 verification checks passed including edge cases

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/agents/risk.py` | Created (677 lines) | RiskAgent class with 5 risk controls, Claude reasoning, fallback |
| `src/agents/__init__.py` | Modified | Added RiskAgent and RiskDecision exports |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Fully stateless (no SQLite) | Agents communicate via context dict per architecture; DB is Phase 3 | Orchestrator must provide daily_pnl, recent_trades, portfolio_positions |
| One-way Claude override | Risk rules are non-negotiable; Claude adds caution, never removes it | Ensures hard limits can never be bypassed by LLM reasoning |
| MIN_TRADE_USD = $5.00 | Prevents dust transactions that cost more in fees than value | Amount check runs after all other adjustments |

## Deviations from Plan

"None — plan executed exactly as written"

## Issues Encountered

"None"

## Next Phase Readiness

**Ready:**
- Phase 1 complete: both SignalAgent and RiskAgent importable and verified
- All 7 risk controls verified (5 AC + fallback + Claude merge)
- Decision pipeline: SignalAgent → RiskAgent → (ExecutionAgent in Phase 2)

**Concerns:**
- None

**Blockers:**
- None — ready for Phase 2 (bankr.bot Client & Execution Agent)

---
*Phase: 01-signal-risk-agents, Plan: 02*
*Completed: 2026-02-27*
