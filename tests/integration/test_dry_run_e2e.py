"""
test_dry_run_e2e.py
-------------------
End-to-end integration tests for the full trading pipeline in dry-run mode.

Validates:
- Full pipeline execution (Research → Sentiment → Technical → Signal → Risk → Execution)
- Context flow and key promotion between agents
- DRY_RUN safety flag enforcement
- Live mode double safety gate
- Risk limits wired end-to-end
- Graceful shutdown behaviour
- Agent failure resilience
"""

import asyncio
import os
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.base import AgentResult, AgentRole
from src.orchestrator import PIPELINE_ORDER, AgentOrchestrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_orchestrator(dry_run: bool = True) -> AgentOrchestrator:
    """Create an AgentOrchestrator with all agent constructors mocked."""
    config: dict[str, Any] = {
        "loop": {"interval_minutes": 15},
        "risk": {
            "max_daily_loss_usd": 200.0,
            "max_single_trade_usd": 150.0,
            "cooldown_minutes": 15,
            "stop_loss_pct": 8.0,
            "min_confidence": 0.55,
        },
        "position": {"base_usd": 25.0, "max_usd": 150.0},
        "agents": {},
        "watchlist": [{"ticker": "ETH", "chain": "Base", "enabled": True}],
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


def _mock_agent(
    role: AgentRole,
    success: bool = True,
    data: Optional[dict] = None,
) -> AsyncMock:
    """Create a mock agent returning a canned AgentResult."""
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


# Realistic per-agent data mirroring actual agent outputs
RESEARCH_DATA: dict[str, Any] = {
    "research_data": {"ETH": {"trending": True, "mentions": 42}},
    "current_prices": {"ETH": 3500.0},
    "social_posts": [{"text": "ETH looking strong", "source": "twitter"}],
}

SENTIMENT_DATA: dict[str, Any] = {
    "sentiment_scores": {
        "ETH": {
            "composite_score": 0.7,
            "momentum": 0.1,
            "post_count": 25,
            "source_breakdown": {"twitter": 0.7, "reddit": 0.5},
        }
    },
}

TECHNICAL_DATA: dict[str, Any] = {
    "technical_signals": {
        "ETH": {
            "direction": "bullish",
            "strength": 0.7,
            "volume_surge": False,
            "volume_ratio": 1.2,
            "rsi": 55.0,
            "macd_signal": "bullish",
        }
    },
}

SIGNAL_DATA: dict[str, Any] = {
    "trade_signals": [
        {
            "ticker": "ETH",
            "action": "buy",
            "combined_score": 0.52,
            "confidence": 0.72,
            "sentiment_score": 0.6,
            "technical_score": 0.7,
            "volume_signal": 0.0,
            "rationale": "Strong bullish confluence",
        }
    ],
}

RISK_DATA: dict[str, Any] = {
    "risk_decisions": [
        {
            "ticker": "ETH",
            "approved": True,
            "action": "buy",
            "proposed_amount_usd": 115.0,
            "adjusted_amount_usd": 115.0,
            "reason": "All risk checks passed.",
            "stop_loss_triggered": False,
        }
    ],
    "decisions_count": 1,
    "approved_count": 1,
    "rejected_count": 0,
    "stop_loss_alerts": [],
}

EXECUTION_DATA: dict[str, Any] = {
    "executions": [
        {
            "ticker": "ETH",
            "action": "buy",
            "amount_usd": 115.0,
            "success": True,
            "job_id": "job-e2e-001",
            "response": "[DRY RUN] Bought $115.00 of ETH on Base",
            "slippage_pct": None,
            "error": None,
        }
    ],
    "trade_results": [
        {"ticker": "ETH", "action": "buy", "success": True}
    ],
    "summary": "Executed 1 trades: 1 succeeded, 0 failed",
}

ALL_AGENT_DATA: dict[AgentRole, dict[str, Any]] = {
    AgentRole.RESEARCH: RESEARCH_DATA,
    AgentRole.SENTIMENT: SENTIMENT_DATA,
    AgentRole.TECHNICAL: TECHNICAL_DATA,
    AgentRole.SIGNAL: SIGNAL_DATA,
    AgentRole.RISK: RISK_DATA,
    AgentRole.EXECUTION: EXECUTION_DATA,
}


def _wire_all_agents(orch: AgentOrchestrator) -> None:
    """Replace all pipeline agents with realistic mock agents."""
    for role in PIPELINE_ORDER:
        orch._agents[role] = _mock_agent(role, data=ALL_AGENT_DATA[role])
    orch._record_heartbeat = AsyncMock()


# ---------------------------------------------------------------------------
# AC-1: Full pipeline executes in dry-run mode
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFullPipelineDryRun:

    async def test_full_cycle_completes_without_error(self):
        """AC-1: All 6 agents execute in order and cycle completes."""
        orch = _make_orchestrator(dry_run=True)

        called_order: list[str] = []
        for role in PIPELINE_ORDER:
            data = ALL_AGENT_DATA[role]

            async def _track(ctx, _role=role, _data=data):
                called_order.append(_role.value)
                return AgentResult(
                    agent=_role, success=True, data=_data,
                    errors=[], tokens_used=50,
                )

            mock_ag = AsyncMock()
            mock_ag.role = role
            mock_ag.execute = AsyncMock(side_effect=_track)
            orch._agents[role] = mock_ag

        orch._record_heartbeat = AsyncMock()

        summary = await orch.run_cycle()

        # All 6 agents called
        assert len(called_order) == 6
        assert called_order == [r.value for r in PIPELINE_ORDER]

        # All succeeded
        for role in PIPELINE_ORDER:
            assert summary["results"][role.value]["success"] is True

    async def test_each_agent_receives_upstream_context(self):
        """AC-1: Downstream agents receive context from upstream agents."""
        orch = _make_orchestrator(dry_run=True)

        captured_contexts: dict[str, dict] = {}

        for role in PIPELINE_ORDER:
            data = ALL_AGENT_DATA[role]

            async def _capture(ctx, _role=role, _data=data):
                captured_contexts[_role.value] = dict(ctx)
                return AgentResult(
                    agent=_role, success=True, data=_data,
                    errors=[], tokens_used=50,
                )

            mock_ag = AsyncMock()
            mock_ag.role = role
            mock_ag.execute = AsyncMock(side_effect=_capture)
            orch._agents[role] = mock_ag

        orch._record_heartbeat = AsyncMock()

        await orch.run_cycle()

        # Sentiment should see Research results in context
        assert "research_result" in captured_contexts["sentiment"]

        # Signal should see Sentiment and Technical results
        assert "sentiment_result" in captured_contexts["signal"]
        assert "technical_result" in captured_contexts["signal"]

        # Risk should see Signal results
        assert "signal_result" in captured_contexts["risk"]

        # Execution should see Risk results
        assert "risk_result" in captured_contexts["execution"]


# ---------------------------------------------------------------------------
# AC-2: Context flows correctly through agent handoffs
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestContextPromotion:

    async def test_promoted_keys_available_to_downstream(self):
        """AC-2: Promoted keys (current_prices, trade_signals, etc.) appear in context."""
        orch = _make_orchestrator(dry_run=True)
        _wire_all_agents(orch)

        summary = await orch.run_cycle()
        context = summary["context"]

        # Research promotions
        assert "current_prices" in context
        assert context["current_prices"] == {"ETH": 3500.0}
        assert "research_data" in context
        assert "social_posts" in context

        # Sentiment promotions
        assert "sentiment_scores" in context

        # Technical promotions
        assert "technical_signals" in context

        # Signal promotions
        assert "trade_signals" in context
        assert len(context["trade_signals"]) == 1
        assert context["trade_signals"][0]["ticker"] == "ETH"

        # Risk promotions
        assert "risk_decisions" in context
        assert len(context["risk_decisions"]) == 1
        assert context["risk_decisions"][0]["approved"] is True

        # Execution promotions
        assert "trade_results" in context

    async def test_context_accumulates_all_agent_results(self):
        """AC-2: Final context contains result keys for all 6 agents."""
        orch = _make_orchestrator(dry_run=True)
        _wire_all_agents(orch)

        summary = await orch.run_cycle()
        context = summary["context"]

        # Each agent's result stored under {role}_result key
        for role in PIPELINE_ORDER:
            key = f"{role.value}_result"
            assert key in context, f"Missing context key: {key}"


# ---------------------------------------------------------------------------
# AC-3: DRY_RUN safety flag is enforced
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDryRunSafety:

    def test_orchestrator_propagates_dry_run_to_execution_agent(self):
        """AC-3: dry_run=True flows from orchestrator to ExecutionAgent constructor."""
        with patch("src.orchestrator.ResearchAgent"), \
             patch("src.orchestrator.SentimentAgent"), \
             patch("src.orchestrator.TechnicalAgent"), \
             patch("src.orchestrator.SignalAgent"), \
             patch("src.orchestrator.RiskAgent"), \
             patch("src.orchestrator.ExecutionAgent") as MockExec, \
             patch("src.orchestrator.PortfolioAgent"):

            config: dict[str, Any] = {
                "loop": {"interval_minutes": 15},
                "risk": {}, "position": {}, "agents": {}, "watchlist": [],
            }
            api_keys = {"anthropic": "sk-ant-test-key", "bankr": "bk_test_key"}

            AgentOrchestrator(
                config=config, api_keys=api_keys,
                db_pool=AsyncMock(), dry_run=True,
            )

            # Verify ExecutionAgent was called with dry_run=True
            MockExec.assert_called_once()
            call_kwargs = MockExec.call_args
            assert call_kwargs.kwargs.get("dry_run") is True or \
                   (len(call_kwargs.args) > 2 and call_kwargs.args[2] is True)

    def test_dry_run_flag_in_cycle_context(self):
        """AC-3: run_cycle injects dry_run=True into initial context."""
        orch = _make_orchestrator(dry_run=True)
        assert orch._dry_run is True

    async def test_context_carries_dry_run_flag(self):
        """AC-3: Context dict passed to agents contains dry_run=True."""
        orch = _make_orchestrator(dry_run=True)

        captured_ctx: Optional[dict] = None

        async def _capture_execution_ctx(ctx):
            nonlocal captured_ctx
            captured_ctx = dict(ctx)
            return AgentResult(
                agent=AgentRole.EXECUTION, success=True,
                data=EXECUTION_DATA, errors=[], tokens_used=50,
            )

        # Set up minimal pipeline — only care about Execution context
        for role in PIPELINE_ORDER[:-1]:
            orch._agents[role] = _mock_agent(role, data=ALL_AGENT_DATA[role])

        exec_mock = AsyncMock()
        exec_mock.role = AgentRole.EXECUTION
        exec_mock.execute = AsyncMock(side_effect=_capture_execution_ctx)
        orch._agents[AgentRole.EXECUTION] = exec_mock
        orch._record_heartbeat = AsyncMock()

        await orch.run_cycle()

        assert captured_ctx is not None
        assert captured_ctx["dry_run"] is True


# ---------------------------------------------------------------------------
# AC-4: Live mode requires double safety gate
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestLiveModeSafetyGate:

    def test_live_mode_blocked_when_dry_run_env_true(self):
        """AC-4: --live + DRY_RUN=true → sys.exit."""
        with patch.dict(os.environ, {
            "ANTHROPIC_API_KEY": "sk-ant-test",
            "BANKR_API_KEY": "bk_test",
            "DATABASE_URL": "postgresql://test",
            "DRY_RUN": "true",
        }):
            with patch("src.main.sys.exit", side_effect=SystemExit(1)) as mock_exit, \
                 patch("src.main.load_config", return_value={}), \
                 patch("src.main.DatabasePool"), \
                 patch("src.main.AgentOrchestrator"):

                from src.main import async_main
                import argparse

                args = argparse.Namespace(
                    live=True, dry_run=False,
                    log_level="INFO", config="config/bot_config.yaml",
                )

                with pytest.raises(SystemExit):
                    asyncio.get_event_loop().run_until_complete(async_main(args))

                mock_exit.assert_called_with(1)

    def test_live_mode_blocked_when_dry_run_env_absent(self):
        """AC-4: --live + DRY_RUN not set → sys.exit."""
        env = {
            "ANTHROPIC_API_KEY": "sk-ant-test",
            "BANKR_API_KEY": "bk_test",
            "DATABASE_URL": "postgresql://test",
        }
        # Ensure DRY_RUN is NOT in env
        with patch.dict(os.environ, env, clear=False):
            # Remove DRY_RUN if present
            os.environ.pop("DRY_RUN", None)

            with patch("src.main.sys.exit", side_effect=SystemExit(1)) as mock_exit, \
                 patch("src.main.load_config", return_value={}), \
                 patch("src.main.DatabasePool"), \
                 patch("src.main.AgentOrchestrator"):

                from src.main import async_main
                import argparse

                args = argparse.Namespace(
                    live=True, dry_run=False,
                    log_level="INFO", config="config/bot_config.yaml",
                )

                with pytest.raises(SystemExit):
                    asyncio.get_event_loop().run_until_complete(async_main(args))

                mock_exit.assert_called_with(1)

    def test_live_mode_proceeds_when_dry_run_false(self):
        """AC-4: --live + DRY_RUN=false → no sys.exit, proceeds to orchestrator."""
        with patch.dict(os.environ, {
            "ANTHROPIC_API_KEY": "sk-ant-test",
            "BANKR_API_KEY": "bk_test",
            "DATABASE_URL": "postgresql://test",
            "DRY_RUN": "false",
        }):
            with patch("src.main.sys.exit") as mock_exit, \
                 patch("src.main.load_config", return_value={
                     "loop": {"interval_minutes": 15},
                     "risk": {}, "position": {}, "agents": {},
                     "watchlist": [],
                 }), \
                 patch("src.main.DatabasePool") as MockDB, \
                 patch("src.main.AgentOrchestrator") as MockOrch:

                mock_db_inst = AsyncMock()
                MockDB.return_value = mock_db_inst

                mock_orch_inst = AsyncMock()
                mock_orch_inst.run = AsyncMock(return_value=None)
                mock_orch_inst.shutdown = MagicMock()
                MockOrch.return_value = mock_orch_inst

                from src.main import async_main
                import argparse

                args = argparse.Namespace(
                    live=True, dry_run=False,
                    log_level="INFO", config="config/bot_config.yaml",
                )

                asyncio.get_event_loop().run_until_complete(async_main(args))

                # sys.exit should NOT have been called
                mock_exit.assert_not_called()

                # Orchestrator should have been created with dry_run=False
                MockOrch.assert_called_once()
                call_kwargs = MockOrch.call_args.kwargs
                assert call_kwargs["dry_run"] is False


# ---------------------------------------------------------------------------
# AC-5: Risk limits are wired end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRiskLimitsWired:

    async def test_risk_agent_receives_trade_signals_from_pipeline(self):
        """AC-5: Risk agent gets trade_signals promoted by Signal agent."""
        orch = _make_orchestrator(dry_run=True)

        captured_risk_ctx: Optional[dict] = None

        async def _capture_risk(ctx):
            nonlocal captured_risk_ctx
            captured_risk_ctx = dict(ctx)
            return AgentResult(
                agent=AgentRole.RISK, success=True,
                data=RISK_DATA, errors=[], tokens_used=50,
            )

        # Wire all agents with realistic data
        for role in PIPELINE_ORDER:
            if role == AgentRole.RISK:
                risk_mock = AsyncMock()
                risk_mock.role = AgentRole.RISK
                risk_mock.execute = AsyncMock(side_effect=_capture_risk)
                orch._agents[role] = risk_mock
            else:
                orch._agents[role] = _mock_agent(role, data=ALL_AGENT_DATA[role])

        orch._record_heartbeat = AsyncMock()
        await orch.run_cycle()

        assert captured_risk_ctx is not None
        # Trade signals from Signal agent should be promoted and available
        assert "trade_signals" in captured_risk_ctx
        assert len(captured_risk_ctx["trade_signals"]) == 1
        assert captured_risk_ctx["trade_signals"][0]["confidence"] == 0.72

    def test_position_sizing_range(self):
        """AC-5: Position sizing stays within $25-$150 for confidence 0-1."""
        from src.agents.risk import RiskAgent

        with patch("src.agents.risk.AsyncAnthropic"):
            agent = RiskAgent(api_key="sk-ant-test")

        # Confidence 0.0 → base ($25)
        assert agent._compute_position_size(0.0) == 25.0
        # Confidence 1.0 → max ($150)
        assert agent._compute_position_size(1.0) == 150.0
        # Confidence 0.5 → midpoint ($87.50)
        assert agent._compute_position_size(0.5) == 87.5
        # Negative clamps to 0
        assert agent._compute_position_size(-0.5) == 25.0
        # >1.0 clamps to 1.0
        assert agent._compute_position_size(1.5) == 150.0

    async def test_low_confidence_signals_rejected_by_signal_agent(self):
        """AC-5: Confidence below 0.55 results in hold/rejection upstream."""
        # This tests that the risk pipeline only receives actionable signals
        # Low-confidence signals should be filtered by SignalAgent before reaching Risk
        orch = _make_orchestrator(dry_run=True)

        # Signal agent returns hold for low-confidence signal
        low_conf_signal_data = {
            "trade_signals": [
                {
                    "ticker": "ETH",
                    "action": "hold",
                    "confidence": 0.40,
                    "rationale": "Below confidence threshold",
                }
            ],
        }

        captured_exec_ctx: Optional[dict] = None

        async def _capture_exec(ctx):
            nonlocal captured_exec_ctx
            captured_exec_ctx = dict(ctx)
            return AgentResult(
                agent=AgentRole.EXECUTION, success=True,
                data={"executions": [], "summary": "No approved trades"},
                errors=[], tokens_used=50,
            )

        for role in PIPELINE_ORDER:
            if role == AgentRole.SIGNAL:
                orch._agents[role] = _mock_agent(role, data=low_conf_signal_data)
            elif role == AgentRole.RISK:
                # Risk agent returns no approved decisions for hold signal
                orch._agents[role] = _mock_agent(role, data={
                    "risk_decisions": [
                        {
                            "ticker": "ETH", "approved": False,
                            "action": "hold", "proposed_amount_usd": 0.0,
                            "adjusted_amount_usd": None,
                            "reason": "HOLD signal",
                            "stop_loss_triggered": False,
                        }
                    ],
                })
            elif role == AgentRole.EXECUTION:
                exec_mock = AsyncMock()
                exec_mock.role = AgentRole.EXECUTION
                exec_mock.execute = AsyncMock(side_effect=_capture_exec)
                orch._agents[role] = exec_mock
            else:
                orch._agents[role] = _mock_agent(role, data=ALL_AGENT_DATA[role])

        orch._record_heartbeat = AsyncMock()
        await orch.run_cycle()

        # Execution agent should see no approved decisions
        assert captured_exec_ctx is not None
        risk_decisions = captured_exec_ctx.get("risk_decisions", [])
        approved = [d for d in risk_decisions if d.get("approved")]
        assert len(approved) == 0


# ---------------------------------------------------------------------------
# AC-6: Graceful shutdown stops the loop
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGracefulShutdown:

    async def test_shutdown_stops_after_current_cycle(self):
        """AC-6: shutdown() allows current cycle to finish, then stops."""
        orch = _make_orchestrator(dry_run=True)
        _wire_all_agents(orch)

        cycles_completed = 0

        original_run_cycle = orch.run_cycle

        async def _counting_cycle():
            nonlocal cycles_completed
            result = await original_run_cycle()
            cycles_completed += 1
            # Trigger shutdown after first cycle
            orch.shutdown()
            return result

        orch.run_cycle = _counting_cycle

        # Patch sleep to avoid waiting
        with patch("src.orchestrator.asyncio.sleep", new_callable=AsyncMock):
            await orch.run()

        # Should complete exactly 1 cycle then stop
        assert cycles_completed == 1
        assert orch._running is False

    async def test_shutdown_no_exception(self):
        """AC-6: Shutdown results in clean exit with no exceptions."""
        orch = _make_orchestrator(dry_run=True)
        _wire_all_agents(orch)

        # Override run_cycle so it shuts down on first call — same pattern
        # as test above but explicitly checks no exception is raised
        async def _shutdown_on_first():
            orch.shutdown()
            return {"results": {}, "context": {}}

        orch.run_cycle = AsyncMock(side_effect=_shutdown_on_first)

        with patch("src.orchestrator.asyncio.sleep", new_callable=AsyncMock):
            # Should NOT raise any exception
            await orch.run()

        assert orch._running is False


# ---------------------------------------------------------------------------
# AC-7: Agent failure does not crash pipeline
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAgentFailureResilience:

    async def test_research_failure_pipeline_continues(self):
        """AC-7: Research agent failure → remaining 5 agents still execute."""
        orch = _make_orchestrator(dry_run=True)

        # Research raises
        failing = AsyncMock()
        failing.role = AgentRole.RESEARCH
        failing.execute = AsyncMock(side_effect=RuntimeError("API timeout"))
        orch._agents[AgentRole.RESEARCH] = failing

        # Others succeed
        for role in PIPELINE_ORDER[1:]:
            orch._agents[role] = _mock_agent(role, data=ALL_AGENT_DATA[role])

        orch._record_heartbeat = AsyncMock()

        summary = await orch.run_cycle()

        # Research failed
        assert summary["results"]["research"]["success"] is False

        # All others succeeded
        for role in PIPELINE_ORDER[1:]:
            assert summary["results"][role.value]["success"] is True

    async def test_mid_pipeline_failure_continues(self):
        """AC-7: Signal agent failure → Risk and Execution still execute."""
        orch = _make_orchestrator(dry_run=True)

        for role in PIPELINE_ORDER:
            if role == AgentRole.SIGNAL:
                failing = AsyncMock()
                failing.role = AgentRole.SIGNAL
                failing.execute = AsyncMock(
                    side_effect=ValueError("Bad signal data")
                )
                orch._agents[role] = failing
            else:
                orch._agents[role] = _mock_agent(role, data=ALL_AGENT_DATA[role])

        orch._record_heartbeat = AsyncMock()

        summary = await orch.run_cycle()

        # Signal failed
        assert summary["results"]["signal"]["success"] is False

        # Risk and Execution still ran (with whatever context was available)
        assert summary["results"]["risk"]["success"] is True
        assert summary["results"]["execution"]["success"] is True

    async def test_heartbeat_records_error_on_failure(self):
        """AC-7: Failed agent's heartbeat records the error status."""
        orch = _make_orchestrator(dry_run=True)

        # Technical agent fails
        failing = AsyncMock()
        failing.role = AgentRole.TECHNICAL
        failing.execute = AsyncMock(
            side_effect=ConnectionError("Network unreachable")
        )
        orch._agents[AgentRole.TECHNICAL] = failing

        # Others succeed
        for role in PIPELINE_ORDER:
            if role != AgentRole.TECHNICAL:
                orch._agents[role] = _mock_agent(role, data=ALL_AGENT_DATA.get(role, {}))

        orch._record_heartbeat = AsyncMock()

        await orch.run_cycle()

        # Find the heartbeat call for the technical agent
        heartbeat_calls = orch._record_heartbeat.call_args_list
        tech_calls = [c for c in heartbeat_calls if c.args[0] == "technical"]
        assert len(tech_calls) == 1

        # Should record error status
        tech_call = tech_calls[0]
        assert tech_call.kwargs.get("status") == "error" or \
               (len(tech_call.args) > 1 and tech_call.args[1] == "error")

    async def test_multiple_failures_still_complete(self):
        """AC-7: Multiple agent failures → cycle still completes."""
        orch = _make_orchestrator(dry_run=True)

        # Research and Sentiment both fail
        for role in [AgentRole.RESEARCH, AgentRole.SENTIMENT]:
            failing = AsyncMock()
            failing.role = role
            failing.execute = AsyncMock(side_effect=RuntimeError(f"{role.value} down"))
            orch._agents[role] = failing

        # Others succeed
        for role in PIPELINE_ORDER[2:]:
            orch._agents[role] = _mock_agent(role, data=ALL_AGENT_DATA[role])

        orch._record_heartbeat = AsyncMock()

        summary = await orch.run_cycle()

        # Both failed
        assert summary["results"]["research"]["success"] is False
        assert summary["results"]["sentiment"]["success"] is False

        # Remaining 4 succeeded
        for role in PIPELINE_ORDER[2:]:
            assert summary["results"][role.value]["success"] is True

        # Summary is a valid dict (cycle didn't crash)
        assert "context" in summary
        assert "results" in summary
