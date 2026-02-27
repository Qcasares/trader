# Project: trader

## Description
An automated crypto trading bot that combines technical indicators with social sentiment analysis to generate and execute trade signals via the bankr.bot API and CLI.

## Core Value
Traders can automatically execute crypto trades based on AI-driven sentiment and technical analysis without manual monitoring with the aim of making as much profit as possible in the shortest amount of time as possible.

## Requirements

### Validated
- Multi-factor signal fusion (sentiment 40% + technical 40% + volume 20%) — Phase 1
- Confidence gating (min 0.55 threshold) — Phase 1
- Multi-domain confluence requirement (>= 2 confirming) — Phase 1
- Anomaly-aware weight adjustment — Phase 1
- Position sizing ($25–$150 linear by confidence) — Phase 1
- Daily loss limit ($200) — Phase 1
- Trade cooldown (15 min per ticker) — Phase 1
- Portfolio concentration limit (40%) — Phase 1
- Stop-loss detection (8% drop) — Phase 1
- Claude Sonnet reasoning for Signal and Risk agents — Phase 1
- Rule-based fallback on Claude API failure — Phase 1
- bankr.bot async API client with typed trade methods — Phase 2
- Trade execution agent with job polling and slippage tracking — Phase 2
- Dry-run safety (prompt prefixing, default enabled) — Phase 2
- PostgreSQL 9-table schema with async connection pool — Phase 3
- Typed repository layer (9 inserts + 7 queries) — Phase 3
- Portfolio tracking with P&L calculation and drawdown detection — Phase 3
- Agent orchestrator with scheduled cadences — Phase 4
- Graceful degradation across all agents — Phase 4
- Health monitoring via heartbeat table — Phase 4
- Live trading mode with safety confirmation — Phase 4

- 65 unit tests covering signal fusion, risk rules, execution, bankr client, orchestrator — Phase 5
- Shared test fixtures with mock isolation (no external dependencies) — Phase 5
- End-to-end dry-run pipeline validation (19 integration tests, 84 total) — Phase 6

### Must Have
(none remaining)

### Should Have
(none remaining)

### Nice to Have
(none remaining)

## Constraints
- All trades must pass RiskAgent.assess() before execution
- DRY_RUN=true must be verified before trade-execution code
- No hardcoded API keys
- python3 (3.9.6) for execution; python (3.14) lacks required deps

## Key Decisions

| Decision | Phase | Impact |
|----------|-------|--------|
| Agents communicate via context dict, not direct calls | 1 | Orchestrator passes shared state |
| RiskAgent is stateless — no SQLite | 1 | All portfolio state via context |
| Claude override is one-way (reject only) | 1 | Hard limits cannot be bypassed |
| python3 (3.9.6) used for execution | 1 | python (3.14) has PEP 668 restrictions |
| No Claude calls in ExecutionAgent | 2 | Logic is deterministic — prompt construction + submission |
| Per-trade BankrClient context manager | 2 | Clean session lifecycle, safe isolation |
| Best-effort fill price extraction | 2 | slippage_pct may be None — downstream must handle |
| Raw asyncpg with parameterised queries — no ORM | 3 | Full SQL control, minimal overhead |
| JSONB for nested data (positions, patterns) | 3 | Flexible schema without join tables |
| PortfolioAgent takes DatabasePool in constructor | 3 | Direct DB access for historical queries |
| Safe DB wrappers — every call non-fatal | 3 | Agent produces partial results on DB errors |
| Sequential pipeline: Research → Sentiment → Technical → Signal → Risk → Execution | 4 | Deterministic execution order with data dependencies |
| Portfolio on separate 30-min cadence (every 2nd cycle) | 4 | Expensive analysis doesn't run every cycle |
| Context key promotion for downstream convenience | 4 | Well-known keys (current_prices, trade_signals) promoted to top-level |
| CLI --dry-run default, --live requires DRY_RUN=false in env | 4 | Double safety gate for live trading |
| conftest.py shared fixtures for all test types | 5 | Reusable mocks for unit + integration tests |
| AgentResult mock requires agent=role field | 5 | Dataclass has positional agent field |
| Python 3.9 compat: Optional[dict] not dict \| None | 5 | Union syntax unsupported in 3.9 |
| sys.exit mocks need side_effect=SystemExit(1) | 6 | MagicMock doesn't halt execution flow |
| AsyncMock resolves synchronously — no concurrent scheduling | 6 | Shutdown tests use run_cycle override, not asyncio.gather |

## Success Criteria
- Automated trade execution with zero manual intervention
- All trades gated by 5 risk controls
- Graceful degradation on API or data failures

---
*Created: 2026-02-26*
*Last updated: 2026-02-27 after Phase 6 — v0.1 milestone complete*
