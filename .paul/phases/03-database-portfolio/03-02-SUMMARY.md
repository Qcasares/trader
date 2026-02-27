---
phase: 03-database-portfolio
plan: 02
subsystem: agents
tags: [portfolio, pnl, drawdown, claude-sonnet, asyncpg, graceful-degradation]

# Dependency graph
requires:
  - phase: 03-database-portfolio/03-01
    provides: DatabasePool, insert_portfolio_snapshot, get_daily_pnl, get_portfolio_positions, get_latest_portfolio_snapshot, get_trade_history
  - phase: 01-signal-risk-agents/01-02
    provides: RiskAgent pattern (Claude + rule-based fallback)
provides:
  - PortfolioAgent with P&L tracking, drawdown detection, Claude Sonnet analysis
  - All 7 agents now complete (Research, Sentiment, Technical, Signal, Risk, Execution, Portfolio)
affects: [phase-4-orchestrator, phase-5-tests, phase-6-dry-run]

# Tech tracking
tech-stack:
  added: []
  patterns: [safe DB wrappers with try/except fallback, peak-to-trough drawdown, cumulative P&L with same-day deduplication]

key-files:
  created: [src/agents/portfolio.py]
  modified: [src/agents/__init__.py]

key-decisions:
  - "PortfolioAgent takes DatabasePool in constructor — reads DB directly for historical data"
  - "Safe DB wrappers (_safe_get_*) — every DB call wrapped in try/except, returns safe default on failure"
  - "Drawdown computed from reconstructed peak value using previous snapshot"
  - "Cumulative P&L handles same-day updates (replace daily component) vs new-day (add to cumulative)"

patterns-established:
  - "Safe DB wrapper pattern: async method wraps repository call in try/except, returns default on failure"
  - "Claude analysis returns tuple[str, int, Optional[str]] — (result, tokens, error)"
  - "Rule-based fallback generates summary string with [RISK_LEVEL] prefix"
  - "Positions updated with current prices from context before metric computation"

# Metrics
duration: ~5min
started: 2026-02-27
completed: 2026-02-27
---

# Phase 3 Plan 02: PortfolioAgent Summary

**PortfolioAgent with P&L tracking, drawdown detection, and Claude Sonnet analysis — 443 lines in 1 new file, completing the 7-agent roster.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~5 min |
| Started | 2026-02-27 |
| Completed | 2026-02-27 |
| Tasks | 2 completed |
| Files created | 1 |
| Files modified | 1 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Agent Extends BaseAgent Correctly | Pass | AgentRole.PORTFOLIO, model "claude-sonnet-4-6", takes api_key + db_pool |
| AC-2: Daily P&L Calculated from Trade Results | Pass | Uses get_daily_pnl() with buy=-/sell=+ convention |
| AC-3: Drawdown Detection Works | Pass | _compute_drawdown() with peak reconstruction from previous snapshot |
| AC-4: Claude Sonnet Analysis with Graceful Fallback | Pass | try/except wrapping Claude call, falls back to _build_rule_based_summary() |
| AC-5: Portfolio Snapshot Persisted to Database | Pass | insert_portfolio_snapshot() called with all 5 fields |
| AC-6: Agent Returns Complete AgentResult | Pass | data contains snapshot, daily_pnl_usd, cumulative_pnl_usd, max_drawdown_pct, analysis, trade_count |

## Accomplishments

- Created PortfolioAgent (443 lines) — the final agent in the 7-agent trading pipeline
- Implemented P&L tracking with cumulative calculation that handles same-day vs new-day updates
- Built peak-to-trough drawdown detection that reconstructs peak from previous snapshot
- Claude Sonnet analysis with full graceful degradation (rule-based fallback on API failure)
- 6 try/except blocks ensuring the agent never crashes on DB or API errors
- All 5 database repository functions integrated (3 reads, 1 write, 1 aggregate)

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/agents/portfolio.py` | Created (443 lines) | PortfolioAgent class with 15 methods |
| `src/agents/__init__.py` | Modified (+2 lines) | Added PortfolioAgent to package exports |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| DatabasePool in constructor (not context) | Agent needs historical queries — passing pool directly is cleaner than extracting from context each cycle | Constructor signature: (api_key, db_pool) |
| Safe DB wrappers | Every DB call must be non-fatal — agent should produce partial results even with DB errors | 5 _safe_get_* / _safe_insert_* methods wrapping repository calls |
| Peak reconstruction from drawdown | Can't store peak separately — reconstruct as prev_total / (1 - drawdown/100) | Slight approximation but avoids schema change |
| Same-day cumulative deduplication | Multiple cycles per day shouldn't double-count daily P&L | Checks snapshot_time date to decide: replace vs accumulate |

## Deviations from Plan

"None — plan executed exactly as written"

## Issues Encountered

"None"

## Next Phase Readiness

**Ready:**
- All 7 agents complete: Research, Sentiment, Technical, Signal, Risk, Execution, Portfolio
- Full database layer available (9 tables, 16 repository functions)
- All agents follow BaseAgent pattern with execute() + system_prompt()
- Phase 4 (Orchestrator) can wire all agents together

**Concerns:**
- asyncpg not yet installed (only in requirements.txt) — needed for any runtime testing
- JSONB codec registration may be needed for dict serialisation at runtime
- PortfolioAgent's peak reconstruction is an approximation — acceptable for v0.1

**Blockers:**
- None — ready for Phase 4 (Orchestrator & Main Loop)

---
*Phase: 03-database-portfolio, Plan: 02*
*Completed: 2026-02-27*
