"""
test_orchestrator.py
--------------------
Unit tests for AgentOrchestrator: pipeline order, context accumulation,
graceful degradation, heartbeat recording, and shutdown.
"""

from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.base import AgentResult, AgentRole
from src.orchestrator import PIPELINE_ORDER, AgentOrchestrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_orchestrator(dry_run: bool = True) -> AgentOrchestrator:
    """Create an AgentOrchestrator with mocked agents and db pool."""
    config: dict[str, Any] = {
        "loop": {"interval_minutes": 15},
        "risk": {},
        "position": {},
        "agents": {},
        "watchlist": [],
    }
    api_keys = {
        "anthropic": "sk-ant-test-key",
        "bankr": "bk_test_key",
    }
    mock_pool = AsyncMock()

    with patch("src.orchestrator.ResearchAgent"), \
         patch("src.orchestrator.SentimentAgent"), \
         patch("src.orchestrator.TechnicalAgent"), \
         patch("src.orchestrator.SignalAgent"), \
         patch("src.orchestrator.RiskAgent"), \
         patch("src.orchestrator.ExecutionAgent"), \
         patch("src.orchestrator.PortfolioAgent"):
        orch = AgentOrchestrator(
            config=config,
            api_keys=api_keys,
            db_pool=mock_pool,
            dry_run=dry_run,
        )

    return orch


def _mock_agent(role: AgentRole, success: bool = True, data: Optional[dict] = None):
    """Create a mock agent that returns a canned AgentResult."""
    agent = AsyncMock()
    agent.role = role
    agent.execute = AsyncMock(return_value=AgentResult(
        agent=role,
        success=success,
        data=data or {},
        errors=[] if success else ["Test error"],
        tokens_used=100,
    ))
    return agent


# ---------------------------------------------------------------------------
# AC-9: Pipeline order
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPipelineOrder:

    def test_pipeline_order_correct(self):
        """AC-9: PIPELINE_ORDER matches expected 6-agent sequence."""
        expected = [
            AgentRole.RESEARCH,
            AgentRole.SENTIMENT,
            AgentRole.TECHNICAL,
            AgentRole.SIGNAL,
            AgentRole.RISK,
            AgentRole.EXECUTION,
        ]
        assert PIPELINE_ORDER == expected

    async def test_run_cycle_executes_all_agents(self):
        """AC-9: run_cycle() calls execute() on each agent in pipeline order."""
        orch = _make_orchestrator()

        # Replace all agents with mocks
        called_order: list[str] = []
        for role in PIPELINE_ORDER:
            mock_ag = _mock_agent(role, data={"test": role.value})

            async def _track_execute(ctx, _role=role):
                called_order.append(_role.value)
                return AgentResult(agent=_role, success=True, data={"test": _role.value}, errors=[], tokens_used=50)

            mock_ag.execute = AsyncMock(side_effect=_track_execute)
            orch._agents[role] = mock_ag

        # Patch heartbeat recording to no-op
        orch._record_heartbeat = AsyncMock()

        await orch.run_cycle()

        assert called_order == [r.value for r in PIPELINE_ORDER]

    async def test_context_accumulation(self):
        """AC-9: Each agent's output is merged into context for downstream agents."""
        orch = _make_orchestrator()

        # Research returns data that should appear in context for Sentiment
        orch._agents[AgentRole.RESEARCH] = _mock_agent(
            AgentRole.RESEARCH, data={"research_data": {"ETH": {}}, "current_prices": {"ETH": 3500.0}}
        )
        orch._agents[AgentRole.SENTIMENT] = _mock_agent(
            AgentRole.SENTIMENT, data={"sentiment_scores": {"ETH": 0.6}}
        )
        orch._agents[AgentRole.TECHNICAL] = _mock_agent(
            AgentRole.TECHNICAL, data={"technical_signals": {"ETH": {"direction": "bullish"}}}
        )
        orch._agents[AgentRole.SIGNAL] = _mock_agent(
            AgentRole.SIGNAL, data={"trade_signals": []}
        )
        orch._agents[AgentRole.RISK] = _mock_agent(
            AgentRole.RISK, data={"risk_decisions": []}
        )
        orch._agents[AgentRole.EXECUTION] = _mock_agent(
            AgentRole.EXECUTION, data={"trade_results": []}
        )
        orch._record_heartbeat = AsyncMock()

        summary = await orch.run_cycle()
        context = summary["context"]

        # Promoted keys from upstream agents should be in context
        assert "current_prices" in context
        assert "research_data" in context
        assert "sentiment_scores" in context
        assert "technical_signals" in context
        assert "trade_signals" in context
        assert "risk_decisions" in context
        assert "trade_results" in context


# ---------------------------------------------------------------------------
# AC-10: Graceful degradation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGracefulDegradation:

    async def test_agent_failure_does_not_crash_pipeline(self):
        """AC-10: One agent raises → others still execute."""
        orch = _make_orchestrator()

        # Research raises an exception
        failing_agent = AsyncMock()
        failing_agent.role = AgentRole.RESEARCH
        failing_agent.execute = AsyncMock(side_effect=RuntimeError("API timeout"))
        orch._agents[AgentRole.RESEARCH] = failing_agent

        # Other agents succeed
        for role in PIPELINE_ORDER[1:]:
            orch._agents[role] = _mock_agent(role, data={"test": True})

        orch._record_heartbeat = AsyncMock()

        summary = await orch.run_cycle()

        # Research failed
        assert summary["results"]["research"]["success"] is False
        assert "RuntimeError" in summary["results"]["research"]["errors"][0]

        # All other agents still ran successfully
        for role in PIPELINE_ORDER[1:]:
            assert summary["results"][role.value]["success"] is True

    async def test_heartbeat_recorded_after_each_agent(self):
        """AC-10: _record_heartbeat is called once per agent in the pipeline."""
        orch = _make_orchestrator()

        for role in PIPELINE_ORDER:
            orch._agents[role] = _mock_agent(role, data={})

        orch._record_heartbeat = AsyncMock()

        await orch.run_cycle()

        # One heartbeat call per pipeline agent
        assert orch._record_heartbeat.call_count == len(PIPELINE_ORDER)

        # Verify each agent role was recorded
        recorded_roles = [call.args[0] for call in orch._record_heartbeat.call_args_list]
        assert recorded_roles == [r.value for r in PIPELINE_ORDER]


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestShutdown:

    def test_shutdown_stops_loop(self):
        """shutdown() sets _running=False."""
        orch = _make_orchestrator()
        orch._running = True

        orch.shutdown()

        assert orch._running is False
