"""
test_signal_agent.py
--------------------
Unit tests for SignalAgent deterministic logic: fusion weights,
confluence counting, fallback signals, and confidence gating.
"""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.signal import (
    ANOMALY_SENTIMENT_WEIGHT,
    ANOMALY_TECHNICAL_WEIGHT,
    ANOMALY_VOLUME_WEIGHT,
    DEFAULT_MIN_CONFIDENCE,
    DEFAULT_SENTIMENT_WEIGHT,
    DEFAULT_TECHNICAL_WEIGHT,
    DEFAULT_VOLUME_WEIGHT,
    DIRECTIONAL_THRESHOLD,
    SignalAgent,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent() -> SignalAgent:
    """Create a SignalAgent with a dummy API key."""
    with patch("src.agents.signal.AsyncAnthropic"):
        return SignalAgent(api_key="sk-ant-test-key")


# ---------------------------------------------------------------------------
# AC-1: Fusion logic with normal weights
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestComputeFusionNormal:

    def test_combined_score_correct(self):
        """AC-1: 0.40*0.6 + 0.40*0.7 + 0.20*0.0 = 0.52"""
        agent = _make_agent()
        sentiment = {"composite_score": 0.6, "momentum": 0.1}
        technical = {"direction": "bullish", "strength": 0.7, "volume_surge": False, "volume_ratio": 1.2}

        result = agent._compute_fusion("ETH", sentiment, technical, is_anomaly=False)

        expected = DEFAULT_SENTIMENT_WEIGHT * 0.6 + DEFAULT_TECHNICAL_WEIGHT * 0.7 + DEFAULT_VOLUME_WEIGHT * 0.0
        assert abs(result["combined_score"] - round(expected, 4)) < 0.001

    def test_confirming_domains_two_bullish(self):
        """AC-1: Both sentiment and technical bullish → confirming_domains=2"""
        agent = _make_agent()
        sentiment = {"composite_score": 0.6, "momentum": 0.0}
        technical = {"direction": "bullish", "strength": 0.7, "volume_surge": False, "volume_ratio": 1.0}

        result = agent._compute_fusion("ETH", sentiment, technical, is_anomaly=False)

        assert result["confirming_domains"] == 2

    def test_confirming_domains_with_volume(self):
        """AC-1: Bullish sentiment + technical + volume surge → 3 confirming domains"""
        agent = _make_agent()
        sentiment = {"composite_score": 0.5, "momentum": 0.0}
        technical = {"direction": "bullish", "strength": 0.6, "volume_surge": True, "volume_ratio": 3.0}

        result = agent._compute_fusion("ETH", sentiment, technical, is_anomaly=False)

        assert result["confirming_domains"] == 3

    def test_confirming_domains_bearish(self):
        """AC-1: Bearish sentiment + technical → 2 confirming (volume doesn't confirm bearish)"""
        agent = _make_agent()
        sentiment = {"composite_score": -0.5, "momentum": 0.0}
        technical = {"direction": "bearish", "strength": 0.6, "volume_surge": False, "volume_ratio": 1.0}

        result = agent._compute_fusion("ETH", sentiment, technical, is_anomaly=False)

        assert result["combined_score"] < 0
        assert result["confirming_domains"] == 2

    def test_confirming_domains_mixed_signals(self):
        """AC-1: Bullish sentiment + bearish technical → 1 confirming (no confluence)"""
        agent = _make_agent()
        sentiment = {"composite_score": 0.3, "momentum": 0.0}
        technical = {"direction": "bearish", "strength": 0.5, "volume_surge": False, "volume_ratio": 1.0}

        result = agent._compute_fusion("ETH", sentiment, technical, is_anomaly=False)

        # Combined might be slightly negative or positive depending on weights
        assert result["confirming_domains"] <= 1

    def test_normal_weights_used(self):
        """AC-1: Verify 0.40/0.40/0.20 weights when is_anomaly=False"""
        agent = _make_agent()
        sentiment = {"composite_score": 0.5, "momentum": 0.0}
        technical = {"direction": "bullish", "strength": 0.5, "volume_surge": False, "volume_ratio": 1.0}

        result = agent._compute_fusion("ETH", sentiment, technical, is_anomaly=False)

        assert result["weights_used"]["sentiment"] == DEFAULT_SENTIMENT_WEIGHT
        assert result["weights_used"]["technical"] == DEFAULT_TECHNICAL_WEIGHT
        assert result["weights_used"]["volume"] == DEFAULT_VOLUME_WEIGHT


# ---------------------------------------------------------------------------
# AC-2: Anomaly weights
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestComputeFusionAnomaly:

    def test_anomaly_weights_applied(self):
        """AC-2: When is_anomaly=True, weights are 0.10/0.55/0.35"""
        agent = _make_agent()
        sentiment = {"composite_score": 0.8, "momentum": 0.0}
        technical = {"direction": "bullish", "strength": 0.3, "volume_surge": False, "volume_ratio": 1.0}

        result = agent._compute_fusion("ETH", sentiment, technical, is_anomaly=True)

        assert result["weights_used"]["sentiment"] == ANOMALY_SENTIMENT_WEIGHT
        assert result["weights_used"]["technical"] == ANOMALY_TECHNICAL_WEIGHT
        assert result["weights_used"]["volume"] == ANOMALY_VOLUME_WEIGHT
        assert result["is_anomaly"] is True

    def test_anomaly_score_differs_from_normal(self):
        """AC-2: Anomaly-adjusted combined_score differs from normal weights"""
        agent = _make_agent()
        sentiment = {"composite_score": 0.8, "momentum": 0.0}
        technical = {"direction": "bullish", "strength": 0.3, "volume_surge": False, "volume_ratio": 1.0}

        normal = agent._compute_fusion("ETH", sentiment, technical, is_anomaly=False)
        anomaly = agent._compute_fusion("ETH", sentiment, technical, is_anomaly=True)

        assert normal["combined_score"] != anomaly["combined_score"]

    def test_anomaly_downweights_sentiment(self):
        """AC-2: High sentiment score has less impact when anomaly detected"""
        agent = _make_agent()
        sentiment = {"composite_score": 0.9, "momentum": 0.0}
        technical = {"direction": "neutral", "strength": 0.0, "volume_surge": False, "volume_ratio": 1.0}

        normal = agent._compute_fusion("ETH", sentiment, technical, is_anomaly=False)
        anomaly = agent._compute_fusion("ETH", sentiment, technical, is_anomaly=True)

        # With anomaly weights, high sentiment has much less impact
        assert anomaly["combined_score"] < normal["combined_score"]


# ---------------------------------------------------------------------------
# AC-3: Fallback signals
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFallbackSignals:

    def test_buy_with_confluence(self):
        """AC-3: Score > threshold + 2 confirming → buy"""
        agent = _make_agent()
        fusion_data = [{
            "ticker": "ETH",
            "combined_score": 0.20,
            "confirming_domains": 2,
            "sentiment_score": 0.5,
            "technical_score": 0.4,
            "volume_signal": 0.0,
            "is_anomaly": False,
        }]

        signals = agent._fallback_signals(fusion_data, DEFAULT_MIN_CONFIDENCE)

        assert len(signals) == 1
        assert signals[0].action == "buy"
        assert signals[0].confidence >= DEFAULT_MIN_CONFIDENCE

    def test_hold_low_confluence(self):
        """AC-3: Score > threshold but only 1 confirming → hold"""
        agent = _make_agent()
        fusion_data = [{
            "ticker": "ETH",
            "combined_score": 0.25,
            "confirming_domains": 1,
            "sentiment_score": 0.5,
            "technical_score": -0.1,
            "volume_signal": 0.0,
            "is_anomaly": False,
        }]

        signals = agent._fallback_signals(fusion_data, DEFAULT_MIN_CONFIDENCE)

        assert len(signals) == 1
        assert signals[0].action == "hold"

    def test_confidence_gating(self):
        """AC-3: Confidence below min → hold regardless of score/confluence"""
        agent = _make_agent()
        # Weak score → low confidence in fallback
        fusion_data = [{
            "ticker": "ETH",
            "combined_score": 0.16,  # Just above threshold
            "confirming_domains": 2,
            "sentiment_score": 0.3,
            "technical_score": 0.2,
            "volume_signal": 0.0,
            "is_anomaly": False,
        }]

        # Use a high min_confidence to force gating
        signals = agent._fallback_signals(fusion_data, min_confidence=0.95)

        assert len(signals) == 1
        assert signals[0].action == "hold"

    def test_sell_with_confluence(self):
        """AC-3: Negative score + 2 confirming → sell"""
        agent = _make_agent()
        fusion_data = [{
            "ticker": "BTC",
            "combined_score": -0.30,
            "confirming_domains": 2,
            "sentiment_score": -0.4,
            "technical_score": -0.5,
            "volume_signal": 0.0,
            "is_anomaly": False,
        }]

        signals = agent._fallback_signals(fusion_data, DEFAULT_MIN_CONFIDENCE)

        assert len(signals) == 1
        assert signals[0].action == "sell"
        assert signals[0].confidence >= DEFAULT_MIN_CONFIDENCE


# ---------------------------------------------------------------------------
# Execute edge case: no upstream data
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_execute_no_upstream_data():
    """Empty context → returns empty signals, success=True"""
    agent = _make_agent()

    result = await agent.execute({})

    assert result.success is True
    assert result.data["trade_signals"] == []
    assert result.data["signal_count"] == 0
