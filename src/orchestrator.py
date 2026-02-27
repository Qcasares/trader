"""
orchestrator.py
---------------
AgentOrchestrator — wires all 7 specialist agents into a coordinated
trading pipeline with scheduled cadences, context passing, health
monitoring, and graceful degradation.

Pipeline order:
    Research → Sentiment → Technical → Signal → Risk → Execution
    Portfolio runs on its own 30-minute cadence (every 2nd main cycle).
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

from src.agents.base import AgentResult, AgentRole, BaseAgent
from src.agents.execution import ExecutionAgent
from src.agents.portfolio import PortfolioAgent
from src.agents.research import ResearchAgent
from src.agents.risk import RiskAgent
from src.agents.sentiment import SentimentAgent
from src.agents.signal import SignalAgent
from src.agents.technical import TechnicalAgent
from src.db.connection import DatabasePool
from src.db.repositories import upsert_agent_heartbeat

logger = logging.getLogger(__name__)

# Pipeline execution order (Portfolio is handled separately)
PIPELINE_ORDER: list[AgentRole] = [
    AgentRole.RESEARCH,
    AgentRole.SENTIMENT,
    AgentRole.TECHNICAL,
    AgentRole.SIGNAL,
    AgentRole.RISK,
    AgentRole.EXECUTION,
]


class AgentOrchestrator:
    """
    Coordinates all 7 trading agents in a scheduled pipeline.

    Responsibilities:
    - Initialize agents with correct constructor arguments from config
    - Run the main trading pipeline every loop_interval minutes
    - Run the portfolio agent every 2nd cycle (30-minute cadence)
    - Pass shared context dict between agents (upstream → downstream)
    - Record heartbeats to agent_heartbeats table after each agent
    - Handle agent failures gracefully (log + continue with safe defaults)
    """

    def __init__(
        self,
        config: dict[str, Any],
        api_keys: dict[str, str],
        db_pool: DatabasePool,
        dry_run: bool = True,
    ) -> None:
        self._config = config
        self._db = db_pool
        self._dry_run = dry_run
        self._running = False
        self._cycle_count = 0
        self._cycles_per_agent: dict[str, int] = {}

        # Extract config sections
        loop_cfg = config.get("loop", {})
        risk_cfg = config.get("risk", {})
        position_cfg = config.get("position", {})
        agent_models = config.get("agents", {})
        watchlist = config.get("watchlist", [])
        sentiment_weights = config.get("sentiment_weights", None)

        self._loop_interval_seconds = loop_cfg.get("interval_minutes", 15) * 60

        # API keys
        anthropic_key = api_keys.get("anthropic", "")
        bankr_key = api_keys.get("bankr", "")
        coingecko_key = api_keys.get("coingecko")
        twitter_token = api_keys.get("twitter")
        reddit_id = api_keys.get("reddit_id")
        reddit_secret = api_keys.get("reddit_secret")

        # --- Initialize all 7 agents ---
        self._agents: dict[AgentRole, BaseAgent] = {}

        self._agents[AgentRole.RESEARCH] = ResearchAgent(
            model=agent_models.get("research", {}).get(
                "model", "claude-haiku-4-5-20251001"
            ),
            api_key=anthropic_key,
            watchlist=[w for w in watchlist if w.get("enabled", True)],
            coingecko_api_key=coingecko_key,
            twitter_bearer_token=twitter_token,
            reddit_client_id=reddit_id,
            reddit_client_secret=reddit_secret,
        )

        self._agents[AgentRole.SENTIMENT] = SentimentAgent(
            model=agent_models.get("sentiment", {}).get(
                "model", "claude-haiku-4-5-20251001"
            ),
            api_key=anthropic_key,
            source_weights=sentiment_weights,
        )

        self._agents[AgentRole.TECHNICAL] = TechnicalAgent(
            model=agent_models.get("technical", {}).get(
                "model", "claude-haiku-4-5-20251001"
            ),
            api_key=anthropic_key,
            candle_count=loop_cfg.get("technical_candles", 50),
        )

        self._agents[AgentRole.SIGNAL] = SignalAgent(
            api_key=anthropic_key,
            min_confidence=risk_cfg.get("min_confidence", 0.55),
        )

        self._agents[AgentRole.RISK] = RiskAgent(
            api_key=anthropic_key,
            max_daily_loss_usd=risk_cfg.get("max_daily_loss_usd", 200.0),
            max_single_trade_usd=risk_cfg.get("max_single_trade_usd", 150.0),
            cooldown_minutes=risk_cfg.get("cooldown_minutes", 15),
            stop_loss_pct=risk_cfg.get("stop_loss_pct", 8.0),
            base_position_usd=position_cfg.get("base_usd", 25.0),
            max_position_usd=position_cfg.get("max_usd", 150.0),
        )

        self._agents[AgentRole.EXECUTION] = ExecutionAgent(
            api_key=anthropic_key,
            bankr_api_key=bankr_key,
            dry_run=dry_run,
        )

        self._agents[AgentRole.PORTFOLIO] = PortfolioAgent(
            api_key=anthropic_key,
            db_pool=db_pool,
        )

        logger.info(
            "Orchestrator initialized: %d agents, loop=%ds, dry_run=%s",
            len(self._agents),
            self._loop_interval_seconds,
            dry_run,
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Run the trading loop indefinitely until shutdown() is called."""
        self._running = True
        logger.info(
            "Starting trading loop (interval=%ds, mode=%s)",
            self._loop_interval_seconds,
            "DRY-RUN" if self._dry_run else "LIVE",
        )

        while self._running:
            self._cycle_count += 1
            cycle_start = time.monotonic()
            logger.info("=== Cycle %d starting ===", self._cycle_count)

            # Run main trading pipeline
            cycle_summary = await self.run_cycle()

            # Run portfolio every 2nd cycle (30-min cadence if loop is 15 min)
            if self._cycle_count % 2 == 0:
                portfolio_result = await self.run_portfolio_cycle(
                    cycle_summary.get("context", {})
                )
                cycle_summary["portfolio"] = portfolio_result

            cycle_duration = time.monotonic() - cycle_start
            successful = sum(
                1 for r in cycle_summary.get("results", {}).values()
                if r.get("success", False)
            )
            total = len(cycle_summary.get("results", {}))

            logger.info(
                "=== Cycle %d complete: %d/%d agents OK, %.1fs ===",
                self._cycle_count,
                successful,
                total,
                cycle_duration,
            )

            # Sleep until next cycle (account for cycle duration)
            sleep_time = max(
                0, self._loop_interval_seconds - cycle_duration
            )
            if self._running and sleep_time > 0:
                logger.debug("Sleeping %.0fs until next cycle", sleep_time)
                try:
                    await asyncio.sleep(sleep_time)
                except asyncio.CancelledError:
                    logger.info("Sleep interrupted — shutting down")
                    break

        logger.info("Trading loop stopped after %d cycles", self._cycle_count)

    def shutdown(self) -> None:
        """Signal the main loop to stop after the current cycle completes."""
        logger.info("Shutdown requested — will stop after current cycle")
        self._running = False

    # ------------------------------------------------------------------
    # Pipeline execution
    # ------------------------------------------------------------------

    async def run_cycle(self) -> dict[str, Any]:
        """
        Execute one full trading pipeline cycle.

        Runs agents in order: Research → Sentiment → Technical →
        Signal → Risk → Execution. Each agent receives the accumulated
        context from all prior agents.

        Returns a summary dict with per-agent results and the final context.
        """
        context: dict[str, Any] = {
            "cycle_number": self._cycle_count,
            "dry_run": self._dry_run,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        results: dict[str, dict[str, Any]] = {}

        for role in PIPELINE_ORDER:
            agent = self._agents.get(role)
            if agent is None:
                logger.warning("Agent %s not found — skipping", role.value)
                continue

            result_summary = await self._execute_agent(agent, context)
            results[role.value] = result_summary

            # Merge agent output data into context for downstream agents
            if result_summary["success"] and result_summary.get("data"):
                context[f"{role.value}_result"] = result_summary["data"]

                # Promote commonly-used keys to top level for convenience
                self._promote_context_keys(context, role, result_summary["data"])

        return {"results": results, "context": context}

    async def run_portfolio_cycle(
        self, context: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Run the portfolio agent on its 30-minute cadence.

        Passes the accumulated context from the latest trading cycle.
        """
        agent = self._agents.get(AgentRole.PORTFOLIO)
        if agent is None:
            logger.warning("PortfolioAgent not found — skipping")
            return {"success": False, "error": "Agent not found"}

        return await self._execute_agent(agent, context)

    # ------------------------------------------------------------------
    # Agent execution with error handling
    # ------------------------------------------------------------------

    async def _execute_agent(
        self, agent: BaseAgent, context: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Execute a single agent with full error handling and heartbeat recording.

        Never raises — returns a summary dict with success/failure info.
        """
        role = agent.role
        role_name = role.value
        start = time.monotonic()

        try:
            logger.info("Running %s agent...", role_name)
            result: AgentResult = await agent.execute(context)
            duration_ms = (time.monotonic() - start) * 1000

            # Track cycles per agent
            self._cycles_per_agent[role_name] = (
                self._cycles_per_agent.get(role_name, 0) + 1
            )

            # Record heartbeat
            await self._record_heartbeat(
                role_name,
                status="ok" if result.success else "degraded",
                last_error=result.errors[0] if result.errors else None,
            )

            if result.success:
                logger.info(
                    "%s agent OK (%.0fms, %d tokens)",
                    role_name,
                    duration_ms,
                    result.tokens_used,
                )
            else:
                logger.warning(
                    "%s agent completed with errors: %s",
                    role_name,
                    result.errors,
                )

            return {
                "success": result.success,
                "data": result.data,
                "errors": result.errors,
                "duration_ms": round(duration_ms, 1),
                "tokens_used": result.tokens_used,
            }

        except Exception as exc:
            duration_ms = (time.monotonic() - start) * 1000
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.error(
                "%s agent FAILED (%.0fms): %s",
                role_name,
                duration_ms,
                error_msg,
            )

            # Record failure heartbeat
            await self._record_heartbeat(
                role_name,
                status="error",
                last_error=error_msg,
            )

            return {
                "success": False,
                "data": {},
                "errors": [error_msg],
                "duration_ms": round(duration_ms, 1),
                "tokens_used": 0,
            }

    # ------------------------------------------------------------------
    # Context promotion
    # ------------------------------------------------------------------

    @staticmethod
    def _promote_context_keys(
        context: dict[str, Any],
        role: AgentRole,
        data: dict[str, Any],
    ) -> None:
        """
        Promote commonly-used output keys to top-level context.

        This allows downstream agents to access upstream data without
        knowing the exact key structure of each agent's result.
        """
        promotions: dict[AgentRole, list[str]] = {
            AgentRole.RESEARCH: ["current_prices", "research_data", "social_posts"],
            AgentRole.SENTIMENT: ["sentiment_scores"],
            AgentRole.TECHNICAL: ["technical_signals"],
            AgentRole.SIGNAL: ["trade_signals"],
            AgentRole.RISK: ["risk_decisions"],
            AgentRole.EXECUTION: ["trade_results"],
        }

        for key in promotions.get(role, []):
            if key in data:
                context[key] = data[key]

    # ------------------------------------------------------------------
    # Heartbeat recording
    # ------------------------------------------------------------------

    async def _record_heartbeat(
        self,
        agent_role: str,
        status: str = "idle",
        last_error: Optional[str] = None,
    ) -> None:
        """Record an agent heartbeat to the database (non-fatal on error)."""
        try:
            await upsert_agent_heartbeat(
                self._db,
                {
                    "agent_role": agent_role,
                    "last_seen": datetime.now(timezone.utc),
                    "status": status,
                    "cycles_completed": self._cycles_per_agent.get(
                        agent_role, 0
                    ),
                    "last_error": last_error,
                },
            )
        except Exception as exc:
            logger.warning(
                "Failed to record heartbeat for %s: %s", agent_role, exc
            )
