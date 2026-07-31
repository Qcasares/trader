"""
conftest.py
-----------
Shared pytest fixtures for the trading bot test suite.

All fixtures use unittest.mock — no external API calls or database connections.
"""

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Legacy collection guard
# ---------------------------------------------------------------------------
#
# The legacy agent tests import ``src.agents``, whose package ``__init__``
# imports ``anthropic`` at module scope. The systematic engine deliberately
# does not depend on an LLM SDK — that independence is the point, and
# ``tests/unit/test_import_boundaries.py`` fails the build if it is ever lost —
# so ``requirements-engine.txt`` omits it and CI installs only that.
#
# Without this guard, ``pytest tests/unit -q`` (the command CLAUDE.md
# documents as needing nothing but a checkout) dies during *collection* with a
# ModuleNotFoundError, taking the whole suite with it. A missing optional
# dependency should skip the tests that need it, not prevent the other 231
# from running.
#
# These files are listed rather than globbed: a new legacy test should have to
# be added here deliberately, and a rename should surface as a collection
# error rather than silently skipping.
_LEGACY_TESTS = (
    "unit/test_execution_agent.py",
    "unit/test_orchestrator.py",
    "unit/test_risk_agent.py",
    "unit/test_signal_agent.py",
    "integration/test_dry_run_e2e.py",
)

if importlib.util.find_spec("anthropic") is None:
    collect_ignore = list(_LEGACY_TESTS)


# ---------------------------------------------------------------------------
# Mock Anthropic client
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_anthropic_response():
    """Factory for creating mock Anthropic API responses."""

    def _make_response(
        content_text: str, input_tokens: int = 100, output_tokens: int = 50
    ):
        response = MagicMock()
        content_block = MagicMock()
        content_block.text = content_text
        response.content = [content_block]
        response.usage = MagicMock()
        response.usage.input_tokens = input_tokens
        response.usage.output_tokens = output_tokens
        return response

    return _make_response


@pytest.fixture
def mock_anthropic_client(mock_anthropic_response):
    """AsyncMock of AsyncAnthropic that returns configurable JSON responses."""
    client = AsyncMock()
    # Default: return a simple hold signal
    default_response = mock_anthropic_response(
        json.dumps(
            [{"ticker": "ETH", "action": "hold", "confidence": 0.4,
              "rationale": "test"}]
        )
    )
    client.messages.create = AsyncMock(return_value=default_response)
    return client


# ---------------------------------------------------------------------------
# Sample data fixtures — Sentiment
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_sentiment_data() -> dict[str, dict[str, Any]]:
    """Sample ticker_sentiments matching SentimentAgent output format."""
    return {
        "ETH": {
            "composite_score": 0.6,
            "momentum": 0.1,
            "post_count": 25,
            "source_breakdown": {"twitter": 0.7, "reddit": 0.5},
        },
        "BTC": {
            "composite_score": -0.3,
            "momentum": -0.05,
            "post_count": 40,
            "source_breakdown": {"twitter": -0.2, "reddit": -0.4},
        },
        "SOL": {
            "composite_score": 0.8,
            "momentum": 0.2,
            "post_count": 15,
            "source_breakdown": {"twitter": 0.9, "farcaster": 0.7},
        },
    }


# ---------------------------------------------------------------------------
# Sample data fixtures — Technical
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_technical_data() -> dict[str, dict[str, Any]]:
    """Sample technical_signals matching TechnicalAgent output format."""
    return {
        "ETH": {
            "direction": "bullish",
            "strength": 0.7,
            "volume_surge": False,
            "volume_ratio": 1.2,
            "rsi": 55.0,
            "macd_signal": "bullish",
        },
        "BTC": {
            "direction": "bearish",
            "strength": 0.5,
            "volume_surge": True,
            "volume_ratio": 2.5,
            "rsi": 30.0,
            "macd_signal": "bearish",
        },
        "SOL": {
            "direction": "bullish",
            "strength": 0.9,
            "volume_surge": True,
            "volume_ratio": 3.5,
            "rsi": 65.0,
            "macd_signal": "bullish",
        },
    }


# ---------------------------------------------------------------------------
# Sample data fixtures — Trade signals
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_trade_signals() -> list[dict[str, Any]]:
    """Sample trade signals from SignalAgent (buy, sell, hold variations)."""
    return [
        {
            "ticker": "ETH",
            "action": "buy",
            "combined_score": 0.52,
            "confidence": 0.72,
            "sentiment_score": 0.6,
            "technical_score": 0.7,
            "volume_signal": 0.0,
            "rationale": "Strong bullish confluence",
            "anomaly_adjusted": False,
        },
        {
            "ticker": "BTC",
            "action": "sell",
            "combined_score": -0.37,
            "confidence": 0.65,
            "sentiment_score": -0.3,
            "technical_score": -0.5,
            "volume_signal": 0.0,
            "rationale": "Bearish technical + sentiment",
            "anomaly_adjusted": False,
        },
        {
            "ticker": "SOL",
            "action": "hold",
            "combined_score": 0.05,
            "confidence": 0.40,
            "sentiment_score": 0.1,
            "technical_score": -0.05,
            "volume_signal": 0.0,
            "rationale": "Mixed signals",
            "anomaly_adjusted": False,
        },
    ]


# ---------------------------------------------------------------------------
# Sample data fixtures — Risk decisions
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_risk_decisions() -> list[dict[str, Any]]:
    """Sample risk decisions (approved and rejected)."""
    return [
        {
            "ticker": "ETH",
            "approved": True,
            "action": "buy",
            "proposed_amount_usd": 115.0,
            "adjusted_amount_usd": 115.0,
            "reason": "All risk checks passed.",
            "stop_loss_triggered": False,
        },
        {
            "ticker": "BTC",
            "approved": True,
            "action": "sell",
            "proposed_amount_usd": 106.25,
            "adjusted_amount_usd": 106.25,
            "reason": "All risk checks passed.",
            "stop_loss_triggered": False,
        },
        {
            "ticker": "SOL",
            "approved": False,
            "action": "hold",
            "proposed_amount_usd": 0.0,
            "adjusted_amount_usd": None,
            "reason": "HOLD signal — no action required.",
            "stop_loss_triggered": False,
        },
    ]


# ---------------------------------------------------------------------------
# Sample data fixtures — Portfolio positions
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_portfolio_positions() -> dict[str, dict[str, Any]]:
    """Sample portfolio positions for concentration and stop-loss tests."""
    return {
        "ETH": {
            "value_usd": 200.0,
            "entry_price": 3500.0,
            "current_price": 3400.0,
            "quantity": 0.0571,
        },
        "BTC": {
            "value_usd": 150.0,
            "entry_price": 95000.0,
            "current_price": 85000.0,  # ~10.5% drop → stop-loss trigger
            "quantity": 0.00158,
        },
        "BNKR": {
            "value_usd": 50.0,
            "entry_price": 0.05,
            "current_price": 0.048,
            "quantity": 1000.0,
        },
    }


# ---------------------------------------------------------------------------
# Mock bankr session
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_bankr_session():
    """AsyncMock of aiohttp.ClientSession for BankrClient tests."""
    session = AsyncMock()

    # Mock POST /agent/prompt → returns jobId
    post_response = AsyncMock()
    post_response.status = 200
    post_response.json = AsyncMock(return_value={"jobId": "test-job-123"})
    post_ctx = AsyncMock()
    post_ctx.__aenter__ = AsyncMock(return_value=post_response)
    post_ctx.__aexit__ = AsyncMock(return_value=False)
    session.post = MagicMock(return_value=post_ctx)

    # Mock GET /agent/job/{id} → returns completed job
    get_response = AsyncMock()
    get_response.status = 200
    get_response.json = AsyncMock(return_value={
        "status": "completed",
        "response": "Bought $50.00 of ETH at $3,456.78 on Base",
        "jobId": "test-job-123",
    })
    get_ctx = AsyncMock()
    get_ctx.__aenter__ = AsyncMock(return_value=get_response)
    get_ctx.__aexit__ = AsyncMock(return_value=False)
    session.get = MagicMock(return_value=get_ctx)

    return session


# ---------------------------------------------------------------------------
# Mock database pool
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db_pool():
    """AsyncMock of DatabasePool for orchestrator tests."""
    pool = AsyncMock()
    pool.connect = AsyncMock()
    pool.close = AsyncMock()
    pool.execute = AsyncMock(return_value="INSERT 0 1")
    pool.fetch = AsyncMock(return_value=[])
    pool.fetchrow = AsyncMock(return_value=None)
    pool.fetchval = AsyncMock(return_value=1)
    return pool


# ---------------------------------------------------------------------------
# Helper: recent trade timestamps
# ---------------------------------------------------------------------------


@pytest.fixture
def recent_trades_within_cooldown() -> dict[str, str]:
    """Recent trades dict where ETH was traded 5 minutes ago (within cooldown)."""
    five_min_ago = datetime.now(UTC) - timedelta(minutes=5)
    return {"ETH": five_min_ago.isoformat()}


@pytest.fixture
def recent_trades_expired_cooldown() -> dict[str, str]:
    """Recent trades dict where ETH was traded 20 minutes ago (expired cooldown)."""
    twenty_min_ago = datetime.now(UTC) - timedelta(minutes=20)
    return {"ETH": twenty_min_ago.isoformat()}
