"""
test_execution_agent.py
-----------------------
Unit tests for ExecutionAgent: filtering approved decisions,
handling BankrClient errors, fill price extraction, and slippage calculation.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.execution import (
    ExecutionAgent,
    ExecutionResult,
    _calculate_slippage,
    _extract_fill_price,
    _get_trade_amount,
)
from src.bankr_client import BankrAPIError, TradeResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent(dry_run: bool = True) -> ExecutionAgent:
    """Create an ExecutionAgent with dummy keys."""
    return ExecutionAgent(
        api_key="sk-ant-test-key",
        bankr_api_key="bk_test_key",
        dry_run=dry_run,
    )


def _mock_bankr_client(success: bool = True, response: str = "Bought $50 of ETH at $3,456.78"):
    """Create a mock BankrClient context manager."""
    mock_client = AsyncMock()
    trade_result = TradeResult(
        success=success,
        response=response,
        job_id="test-job-123",
        raw_payload={"status": "completed"},
    )
    mock_client.buy = AsyncMock(return_value=trade_result)
    mock_client.sell = AsyncMock(return_value=trade_result)
    return mock_client


# ---------------------------------------------------------------------------
# AC-7: Filters approved decisions only
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExecutionFiltering:

    async def test_filters_approved_only(self, sample_risk_decisions):
        """AC-7: 2 approved + 1 rejected → 2 executions"""
        agent = _make_agent()
        mock_client = _mock_bankr_client()

        with patch("src.agents.execution.BankrClient") as MockBankr:
            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_client)
            ctx.__aexit__ = AsyncMock(return_value=False)
            MockBankr.return_value = ctx

            result = await agent.execute({"risk_decisions": sample_risk_decisions})

        assert result.success is True
        executions = result.data["executions"]
        # 2 approved (ETH buy, BTC sell), 1 rejected (SOL hold)
        assert len(executions) == 2

    async def test_no_approved_returns_empty(self):
        """AC-7: All rejected → no trades executed"""
        agent = _make_agent()
        decisions = [
            {"ticker": "ETH", "approved": False, "action": "hold", "proposed_amount_usd": 0.0, "reason": "Hold"},
        ]

        result = await agent.execute({"risk_decisions": decisions})

        assert result.success is True
        assert result.data["executions"] == []
        assert "No approved" in result.data["summary"]

    async def test_bankr_error_does_not_crash(self):
        """AC-7: BankrAPIError on one trade → logged, continues to next"""
        agent = _make_agent()
        decisions = [
            {"ticker": "ETH", "approved": True, "action": "buy", "proposed_amount_usd": 50.0, "adjusted_amount_usd": 50.0},
            {"ticker": "BTC", "approved": True, "action": "sell", "proposed_amount_usd": 30.0, "adjusted_amount_usd": 30.0},
        ]

        call_count = 0

        async def _side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise BankrAPIError("API rate limit")
            return TradeResult(
                success=True,
                response="Sold $30 of BTC",
                job_id="job-456",
                raw_payload={},
            )

        mock_client = AsyncMock()
        mock_client.buy = AsyncMock(side_effect=BankrAPIError("API rate limit"))
        mock_client.sell = AsyncMock(return_value=TradeResult(
            success=True, response="Sold $30 of BTC", job_id="job-456", raw_payload={}
        ))

        with patch("src.agents.execution.BankrClient") as MockBankr:
            ctx = AsyncMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_client)
            ctx.__aexit__ = AsyncMock(return_value=False)
            MockBankr.return_value = ctx

            result = await agent.execute({"risk_decisions": decisions})

        executions = result.data["executions"]
        assert len(executions) == 2
        assert executions[0]["success"] is False  # ETH buy failed
        assert executions[1]["success"] is True   # BTC sell succeeded


# ---------------------------------------------------------------------------
# Fill price extraction
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFillPriceExtraction:

    def test_extracts_dollar_amount(self):
        """Extract first dollar amount from response text"""
        price = _extract_fill_price("Bought $50.00 of ETH at $3,456.78 on Base")
        assert price == 50.0

    def test_extracts_simple_dollar(self):
        """Extract $0.0423 from response"""
        price = _extract_fill_price("Bought at $0.0423")
        assert price == 0.0423

    def test_returns_none_for_no_price(self):
        """No parseable price → None"""
        price = _extract_fill_price("Transaction completed successfully")
        assert price is None

    def test_extracts_first_match(self):
        """Multiple dollar amounts → first one extracted"""
        price = _extract_fill_price("Spent $50.00, got tokens at $3,500.00")
        assert price == 50.0


# ---------------------------------------------------------------------------
# Slippage calculation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSlippageCalculation:

    def test_zero_slippage(self):
        """Same expected and actual → 0% slippage"""
        assert _calculate_slippage(100.0, 100.0) == 0.0

    def test_positive_slippage(self):
        """Actual higher than expected → positive slippage %"""
        slippage = _calculate_slippage(100.0, 102.0)
        assert abs(slippage - 2.0) < 0.01

    def test_negative_slippage(self):
        """Actual lower than expected → still positive (absolute)"""
        slippage = _calculate_slippage(100.0, 98.0)
        assert abs(slippage - 2.0) < 0.01

    def test_zero_expected_returns_zero(self):
        """Expected price = 0 → 0% slippage (avoid division by zero)"""
        assert _calculate_slippage(0.0, 100.0) == 0.0


# ---------------------------------------------------------------------------
# Trade amount helper
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetTradeAmount:

    def test_prefers_adjusted(self):
        """Adjusted amount preferred over proposed"""
        decision = {"adjusted_amount_usd": 75.0, "proposed_amount_usd": 100.0}
        assert _get_trade_amount(decision) == 75.0

    def test_falls_back_to_proposed(self):
        """No adjusted → use proposed"""
        decision = {"adjusted_amount_usd": None, "proposed_amount_usd": 100.0}
        assert _get_trade_amount(decision) == 100.0

    def test_defaults_to_zero(self):
        """Neither present → 0.0"""
        assert _get_trade_amount({}) == 0.0
