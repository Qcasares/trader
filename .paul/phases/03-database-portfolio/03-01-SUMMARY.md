---
phase: 03-database-portfolio
plan: 01
subsystem: database
tags: [postgresql, asyncpg, schema, repository, async, connection-pool]

# Dependency graph
requires:
  - phase: 01-signal-risk-agents/01-01
    provides: TradeSignal, RiskDecision dataclass shapes
  - phase: 01-signal-risk-agents/01-02
    provides: RiskDecision dataclass shape
  - phase: 02-bankr-client-execution/02-02
    provides: ExecutionResult dataclass shape
provides:
  - 9-table PostgreSQL schema mirroring all agent data structures
  - Async connection pool manager via asyncpg
  - Typed repository layer with 9 insert + 7 query functions
affects: [phase-3-plan-02-portfolio-agent, phase-4-orchestrator, phase-5-tests]

# Tech tracking
tech-stack:
  added: [asyncpg>=0.29.0]
  patterns: [async connection pool, parameterised queries, JSONB for nested data, UPSERT for heartbeats]

key-files:
  created: [src/db/schema.sql, src/db/connection.py, src/db/repositories.py, src/db/__init__.py]
  modified: [requirements.txt]

key-decisions:
  - "Raw asyncpg with parameterised queries — no ORM"
  - "JSONB for nested structures (positions, patterns, source_breakdown)"
  - "UPSERT for agent_heartbeats (one row per agent_role)"
  - "ON CONFLICT DO NOTHING for idempotent social post and candle inserts"
  - "Daily P&L via buy=-/sell=+ convention on successful trades"

patterns-established:
  - "All repository functions take DatabasePool as first arg, return int (insert) or list[dict]/dict (query)"
  - "asyncpg Record → dict conversion via dict(record) helper"
  - "Composite indexes on (ticker, created_at/timestamp/executed_at) for time-series queries"
  - "Foreign keys: risk_decisions → trade_signals, trade_results → risk_decisions"

# Metrics
duration: ~5min
started: 2026-02-27
completed: 2026-02-27
---

# Phase 3 Plan 01: PostgreSQL Schema & Database Layer Summary

**9-table PostgreSQL schema with async connection pool and typed repository layer (9 inserts + 7 queries) — 704 lines across 4 files.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~5 min |
| Started | 2026-02-27 |
| Completed | 2026-02-27 |
| Tasks | 2 completed |
| Files created | 4 |
| Files modified | 1 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Schema Covers All Agent Data | Pass | 9/9 tables with fields mirroring all agent dataclasses |
| AC-2: Connection Pool Manager Works | Pass | DatabasePool with connect/close/pool + convenience methods |
| AC-3: Repository Insert Functions Exist | Pass | 9 insert functions (8 insert + 1 upsert), all return row id |
| AC-4: Repository Query Functions Exist | Pass | 7 query functions covering trades, P&L, portfolio, heartbeats, signals, history |
| AC-5: Schema Uses Proper Indexes | Pass | 7 composite indexes on time-series columns + UNIQUE on agent_role |
| AC-6: Package Exports Are Clean | Pass | 17 exports in __all__, DatabasePool + all functions |
| AC-7: asyncpg Dependency Added | Pass | asyncpg>=0.29.0 under # Database comment |

## Accomplishments

- Created 9-table PostgreSQL schema mirroring all 7 agent dataclass structures
- Built async connection pool manager with clean lifecycle and convenience shortcuts
- Implemented 16 typed repository functions (9 inserts + 7 queries) with parameterised queries
- Added proper indexes for time-series access patterns
- Foreign key relationships linking trade pipeline: trade_signals → risk_decisions → trade_results

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `src/db/schema.sql` | Created (170 lines) | 9 CREATE TABLE + 7 CREATE INDEX statements |
| `src/db/connection.py` | Created (102 lines) | DatabasePool class with asyncpg pool management |
| `src/db/repositories.py` | Created (391 lines) | 9 insert + 7 query functions with parameterised SQL |
| `src/db/__init__.py` | Created (41 lines) | Package exports for DatabasePool + all repository functions |
| `requirements.txt` | Modified | Added asyncpg>=0.29.0 dependency |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Raw asyncpg, no ORM | Minimal overhead, full SQL control, matches project's async-first style | Queries are explicit but require manual Record→dict conversion |
| JSONB for nested data | positions, patterns, source_breakdown are naturally nested | Flexible schema without additional join tables |
| UPSERT for heartbeats | One row per agent — maintain current state, not history | Simple health monitoring via single query |
| ON CONFLICT DO NOTHING for posts/candles | Idempotent inserts prevent duplicate data from repeated collection cycles | Returns None on conflict (caller should handle) |
| buy=-/sell=+ P&L convention | Natural cash-flow accounting: buys cost money, sells return money | Daily P&L query is a simple SUM |

## Deviations from Plan

"None — plan executed exactly as written"

## Issues Encountered

"None"

## Next Phase Readiness

**Ready:**
- Full database layer available for PortfolioAgent (Plan 03-02)
- insert/query functions cover all data the PortfolioAgent needs
- get_daily_pnl(), get_portfolio_positions(), get_latest_portfolio_snapshot() ready for P&L tracking
- get_trade_history() provides joined trade + risk data for analysis

**Concerns:**
- asyncpg not yet installed (only added to requirements.txt per plan boundaries)
- JSONB columns (positions, source_breakdown) need asyncpg codec registration for dict serialisation

**Blockers:**
- None — ready for Plan 03-02 (PortfolioAgent)

---
*Phase: 03-database-portfolio, Plan: 01*
*Completed: 2026-02-27*
