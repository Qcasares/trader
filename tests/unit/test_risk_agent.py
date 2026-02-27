"""
test_risk_agent.py
------------------
Unit tests for RiskAgent: position sizing, daily loss limit, cooldown,
concentration limit, stop-loss detection, and Claude override rules.
"""

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.risk import (
    DEFAULT_BASE_POSITION_USD,
    DEFAULT_COOLDOWN_MINUTES,
    DEFAULT_MAX_CONCENTRATION_PCT,
    DEFAULT_MAX_DAILY_LOSS_USD,
    DEFAULT_MAX_POSITION_USD,
    DEFAULT_MAX_SINGLE_TRADE_USD,
    DEFAULT_STOP_LOSS_PCT,
    MIN_TRADE_USD,
    RiskAgent,
    RiskDecision,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent(**kwargs) -> RiskAgent:
    """Create a RiskAgent with a dummy API key and optional overrides."""
    with patch("src.agents.risk.AsyncAnthropic"):
        return RiskAgent(api_key="sk-ant-test-key", **kwargs)


# ---------------------------------------------------------------------------
# AC-4: Position sizing
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPositionSizing:

    def test_base_at_zero_confidence(self):
        """AC-4: confidence=0.0 → $25 (base)"""
        agent = _make_agent()
        amount = agent._compute_position_size(0.0)
        assert amount == DEFAULT_BASE_POSITION_USD

    def test_max_at_full_confidence(self):
        """AC-4: confidence=1.0 → $150 (max, capped by max_single_trade)"""
        agent = _make_agent()
        amount = agent._compute_position_size(1.0)
        assert amount == min(DEFAULT_MAX_POSITION_USD, DEFAULT_MAX_SINGLE_TRADE_USD)

    def test_midpoint_at_half_confidence(self):
        """AC-4: confidence=0.5 → $87.50 (midpoint)"""
        agent = _make_agent()
        amount = agent._compute_position_size(0.5)
        expected = DEFAULT_BASE_POSITION_USD + (DEFAULT_MAX_POSITION_USD - DEFAULT_BASE_POSITION_USD) * 0.5
        assert amount == round(expected, 2)

    def test_clamps_negative_confidence(self):
        """Position sizing clamps negative confidence to 0."""
        agent = _make_agent()
        amount = agent._compute_position_size(-0.5)
        assert amount == DEFAULT_BASE_POSITION_USD

    def test_clamps_above_one_confidence(self):
        """Position sizing clamps confidence > 1.0 to 1.0."""
        agent = _make_agent()
        amount = agent._compute_position_size(1.5)
        assert amount == min(DEFAULT_MAX_POSITION_USD, DEFAULT_MAX_SINGLE_TRADE_USD)


# ---------------------------------------------------------------------------
# AC-5: Daily loss limit
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDailyLossLimit:

    def test_blocks_all_trades_when_breached(self):
        """AC-5: daily_pnl=-200 → all buy signals rejected"""
        agent = _make_agent()
        signal = {"ticker": "ETH", "action": "buy", "confidence": 0.8}

        decision = agent._assess_signal(
            signal=signal,
            daily_loss_breached=True,
            daily_pnl=-200.0,
            recent_trades={},
            portfolio_positions={},
            portfolio_total=1000.0,
        )

        assert decision.approved is False
        assert "Daily loss limit" in decision.reason

    def test_allows_trades_within_limit(self):
        """AC-5: daily_pnl=-50 → trades allowed"""
        agent = _make_agent()
        signal = {"ticker": "ETH", "action": "buy", "confidence": 0.8}

        decision = agent._assess_signal(
            signal=signal,
            daily_loss_breached=False,
            daily_pnl=-50.0,
            recent_trades={},
            portfolio_positions={},
            portfolio_total=1000.0,
        )

        assert decision.approved is True


# ---------------------------------------------------------------------------
# AC-5: Cooldown
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCooldown:

    def test_rejects_recent_trade(self):
        """AC-5: Trade 5 min ago → rejected (cooldown is 15 min)"""
        agent = _make_agent()
        five_min_ago = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        recent_trades = {"ETH": five_min_ago}

        reason = agent._check_cooldown("ETH", recent_trades)

        assert reason is not None
        assert "Cooldown" in reason

    def test_allows_expired_cooldown(self):
        """AC-5: Trade 20 min ago → allowed (cooldown expired)"""
        agent = _make_agent()
        twenty_min_ago = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
        recent_trades = {"ETH": twenty_min_ago}

        reason = agent._check_cooldown("ETH", recent_trades)

        assert reason is None

    def test_allows_no_previous_trade(self):
        """No previous trade for ticker → no cooldown"""
        agent = _make_agent()
        reason = agent._check_cooldown("ETH", {})
        assert reason is None


# ---------------------------------------------------------------------------
# AC-5: Concentration limit
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConcentrationLimit:

    def test_rejects_over_concentration(self):
        """AC-5: Position already at 40% → buy rejected"""
        agent = _make_agent()
        positions = {"ETH": {"value_usd": 400.0}}

        result = agent._check_concentration(
            ticker="ETH",
            proposed_amount=100.0,
            portfolio_positions=positions,
            portfolio_total=1000.0,
        )

        # 400 + 100 = 500, total becomes 1100 → ETH would be 500/1100 = 45.5% > 40%
        # Available room = 1100*0.40 - 400 = 40 → reduced to 40
        assert result is not None
        assert result < 100.0

    def test_reduces_to_fit(self):
        """AC-5: Near limit → amount reduced to stay within bounds"""
        agent = _make_agent()
        positions = {"ETH": {"value_usd": 350.0}}

        result = agent._check_concentration(
            ticker="ETH",
            proposed_amount=100.0,
            portfolio_positions=positions,
            portfolio_total=1000.0,
        )

        # New total = 1100, max allowed = 1100*0.4 = 440, room = 440-350 = 90
        assert result is not None
        assert result < 100.0
        assert result >= MIN_TRADE_USD

    def test_allows_within_limit(self):
        """AC-5: Position well within limit → full amount allowed"""
        agent = _make_agent()
        positions = {"ETH": {"value_usd": 50.0}}

        result = agent._check_concentration(
            ticker="ETH",
            proposed_amount=50.0,
            portfolio_positions=positions,
            portfolio_total=1000.0,
        )

        assert result == 50.0

    def test_rejects_when_no_room(self):
        """AC-5: Already over limit → returns None"""
        agent = _make_agent()
        positions = {"ETH": {"value_usd": 450.0}}

        result = agent._check_concentration(
            ticker="ETH",
            proposed_amount=50.0,
            portfolio_positions=positions,
            portfolio_total=1000.0,
        )

        # New total=1050, max=1050*0.4=420, room=420-450=-30 → None
        assert result is None


# ---------------------------------------------------------------------------
# AC-5: Stop-loss detection
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStopLoss:

    def test_triggers_on_large_drop(self):
        """AC-5: 10% drop from entry → stop-loss sell generated"""
        agent = _make_agent()
        positions = {
            "BTC": {
                "entry_price": 100.0,
                "current_price": 89.0,  # 11% drop
                "value_usd": 890.0,
            }
        }

        alerts = agent._check_stop_losses(positions, 1000.0)

        assert len(alerts) == 1
        assert alerts[0].ticker == "BTC"
        assert alerts[0].action == "sell"
        assert alerts[0].stop_loss_triggered is True
        assert alerts[0].approved is True

    def test_no_trigger_small_drop(self):
        """AC-5: 5% drop → no stop-loss alert"""
        agent = _make_agent()
        positions = {
            "ETH": {
                "entry_price": 100.0,
                "current_price": 95.0,  # 5% drop
                "value_usd": 950.0,
            }
        }

        alerts = agent._check_stop_losses(positions, 1000.0)

        assert len(alerts) == 0

    def test_no_trigger_price_increase(self):
        """Price went up → no stop-loss"""
        agent = _make_agent()
        positions = {
            "SOL": {
                "entry_price": 100.0,
                "current_price": 110.0,
                "value_usd": 110.0,
            }
        }

        alerts = agent._check_stop_losses(positions, 500.0)

        assert len(alerts) == 0


# ---------------------------------------------------------------------------
# AC-6: Claude override is one-way (reject only)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestClaudeOverride:

    def test_cannot_override_rejection(self):
        """AC-6: Rule rejected + Claude approved → still rejected"""
        agent = _make_agent()
        rule_decision = RiskDecision(
            ticker="ETH",
            approved=False,
            action="buy",
            proposed_amount_usd=100.0,
            adjusted_amount_usd=None,
            reason="Daily loss limit reached.",
        )
        claude_rec = {"ticker": "ETH", "approved": True, "adjusted_amount_usd": 100.0, "rationale": "Looks fine"}

        merged = agent._merge_claude_decision(rule_decision, claude_rec)

        assert merged.approved is False
        assert "Daily loss limit" in merged.reason

    def test_can_downgrade_approval(self):
        """AC-6: Rule approved + Claude rejected → rejected"""
        agent = _make_agent()
        rule_decision = RiskDecision(
            ticker="ETH",
            approved=True,
            action="buy",
            proposed_amount_usd=100.0,
            adjusted_amount_usd=100.0,
            reason="All risk checks passed.",
        )
        claude_rec = {"ticker": "ETH", "approved": False, "rationale": "Market too volatile"}

        merged = agent._merge_claude_decision(rule_decision, claude_rec)

        assert merged.approved is False
        assert "Claude override" in merged.reason

    def test_can_reduce_amount(self):
        """AC-6: Rule $100 + Claude $50 → $50"""
        agent = _make_agent()
        rule_decision = RiskDecision(
            ticker="ETH",
            approved=True,
            action="buy",
            proposed_amount_usd=100.0,
            adjusted_amount_usd=100.0,
            reason="All risk checks passed.",
        )
        claude_rec = {"ticker": "ETH", "approved": True, "adjusted_amount_usd": 50.0, "rationale": "Reducing size"}

        merged = agent._merge_claude_decision(rule_decision, claude_rec)

        assert merged.approved is True
        assert merged.adjusted_amount_usd == 50.0

    def test_cannot_increase_amount(self):
        """AC-6: Rule $50 + Claude $100 → stays $50"""
        agent = _make_agent()
        rule_decision = RiskDecision(
            ticker="ETH",
            approved=True,
            action="buy",
            proposed_amount_usd=50.0,
            adjusted_amount_usd=50.0,
            reason="All risk checks passed.",
        )
        claude_rec = {"ticker": "ETH", "approved": True, "adjusted_amount_usd": 100.0, "rationale": "Go bigger"}

        merged = agent._merge_claude_decision(rule_decision, claude_rec)

        assert merged.approved is True
        assert merged.adjusted_amount_usd == 50.0

    def test_empty_claude_rec_returns_original(self):
        """No Claude recommendation → original decision unchanged"""
        agent = _make_agent()
        rule_decision = RiskDecision(
            ticker="ETH",
            approved=True,
            action="buy",
            proposed_amount_usd=100.0,
            adjusted_amount_usd=100.0,
            reason="All risk checks passed.",
        )

        merged = agent._merge_claude_decision(rule_decision, {})

        assert merged.approved is True
        assert merged.adjusted_amount_usd == 100.0


# ---------------------------------------------------------------------------
# Execute edge case: no signals
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_execute_no_signals():
    """Empty trade signals → success=True, empty decisions"""
    agent = _make_agent()

    result = await agent.execute({"trade_signals": []})

    assert result.success is True
    assert result.data["decisions_count"] == 0
    assert result.data["approved_count"] == 0
