"""
signal.py
---------
SignalAgent — multi-factor trade signal generator.

Fuses upstream sentiment scores, technical analysis signals, and volume data
into actionable BUY/SELL/HOLD recommendations with confidence scores.
Uses Claude Sonnet for final reasoning and confluence validation.
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from anthropic import AsyncAnthropic

from src.agents.base import AgentResult, AgentRole, BaseAgent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

# Default fusion weights
DEFAULT_SENTIMENT_WEIGHT = 0.40
DEFAULT_TECHNICAL_WEIGHT = 0.40
DEFAULT_VOLUME_WEIGHT = 0.20

# Anomaly-adjusted weights (sentiment downweighted when manipulation suspected)
ANOMALY_SENTIMENT_WEIGHT = 0.10
ANOMALY_TECHNICAL_WEIGHT = 0.55
ANOMALY_VOLUME_WEIGHT = 0.35

# Thresholds
DEFAULT_MIN_CONFIDENCE = 0.55
DIRECTIONAL_THRESHOLD = 0.15  # Minimum score magnitude for buy/sell


@dataclass
class TradeSignal:
    """Fused trade recommendation for a single ticker."""

    ticker: str
    action: str                # "buy" | "sell" | "hold"
    combined_score: float      # -1.0 (strong sell) … +1.0 (strong buy)
    confidence: float          # 0.0 … 1.0
    sentiment_score: float     # -1.0 … +1.0 from SentimentAgent
    technical_score: float     # -1.0 … +1.0 from TechnicalAgent
    volume_signal: float       # 0.0 … 1.0 volume amplification
    rationale: str
    anomaly_adjusted: bool     # True if anomaly weights were used


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class SignalAgent(BaseAgent):
    """
    Specialist agent for multi-factor signal fusion.

    Combines:
    - Sentiment data (40% weight, or 10% if anomaly detected)
    - Technical signals (40% weight, or 55% if anomaly)
    - Volume data (20% weight, or 35% if anomaly)

    Requires at least 2 confirming signal domains for a directional trade.
    Minimum confidence threshold (default 0.55) must be met.
    Uses Claude Sonnet for final reasoning and signal validation.
    """

    def __init__(
        self,
        api_key: str,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    ) -> None:
        super().__init__(
            role=AgentRole.SIGNAL,
            model="claude-sonnet-4-6",
            api_key=api_key,
        )
        self._client = AsyncAnthropic(api_key=api_key)
        self._min_confidence = min_confidence

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    def system_prompt(self) -> str:
        return (
            "You are a quantitative crypto trading signal analyst.\n\n"
            "You receive pre-computed fusion scores combining sentiment analysis, "
            "technical indicators, and volume data for multiple crypto assets. "
            "Your task is to validate these scores, assess confluence, and produce "
            "final trade recommendations.\n\n"
            "Guidelines:\n"
            "- BUY: combined_score > 0.15 AND at least 2 domains confirm bullish\n"
            "- SELL: combined_score < -0.15 AND at least 2 domains confirm bearish\n"
            "- HOLD: insufficient confluence, low confidence, or mixed signals\n"
            "- Be conservative — only recommend trades with genuine multi-factor support\n"
            "- Consider anomaly flags: if sentiment manipulation suspected, weight "
            "technical and volume signals more heavily\n"
            "- Momentum matters: strong recent momentum in the same direction adds confidence\n\n"
            "Return ONLY a JSON array of objects:\n"
            '[{"ticker": "...", "action": "buy|sell|hold", '
            '"confidence": 0.0-1.0, "rationale": "..."}]'
        )

    async def execute(self, context: dict[str, Any]) -> AgentResult:
        """
        Run one signal fusion cycle.

        Parameters
        ----------
        context : dict
            Expected keys:
                ticker_sentiments — dict of {ticker: TickerSentiment dict}
                technical_signals — dict of {ticker: TechnicalSignal dict}
                anomaly_tickers   — list of tickers with suspected manipulation
                min_confidence    — optional override (default 0.55)

        Returns
        -------
        AgentResult with keys:
            trade_signals — list of TradeSignal dicts
            signal_count  — number of signals generated
        """
        cycle_start = time.monotonic()
        errors: list[str] = []
        tokens_used = 0

        # Extract upstream data
        ticker_sentiments: dict[str, dict[str, Any]] = context.get(
            "ticker_sentiments", {}
        )
        technical_signals: dict[str, dict[str, Any]] = context.get(
            "technical_signals", {}
        )
        anomaly_tickers: set[str] = set(context.get("anomaly_tickers", []))
        min_conf = context.get("min_confidence", self._min_confidence)

        if not ticker_sentiments and not technical_signals:
            self._logger.warning("No upstream data available for signal fusion")
            return self._build_result(
                success=True,
                data={"trade_signals": [], "signal_count": 0},
                errors=["No upstream data available"],
                duration_ms=(time.monotonic() - cycle_start) * 1000,
            )

        # Find tickers present in BOTH sentiment and technical data
        sentiment_tickers = set(ticker_sentiments.keys())
        technical_tickers = set(technical_signals.keys())
        common_tickers = sentiment_tickers & technical_tickers

        if not common_tickers:
            self._logger.warning(
                "No overlapping tickers between sentiment (%s) and technical (%s)",
                sentiment_tickers,
                technical_tickers,
            )
            return self._build_result(
                success=True,
                data={"trade_signals": [], "signal_count": 0},
                errors=["No tickers with both sentiment and technical data"],
                duration_ms=(time.monotonic() - cycle_start) * 1000,
            )

        # Compute fusion scores for each common ticker
        fusion_data: list[dict[str, Any]] = []

        for ticker in sorted(common_tickers):
            sent = ticker_sentiments[ticker]
            tech = technical_signals[ticker]
            is_anomaly = ticker in anomaly_tickers

            fusion = self._compute_fusion(ticker, sent, tech, is_anomaly)
            fusion_data.append(fusion)

        # Call Claude Sonnet for final reasoning
        trade_signals, claude_tokens, claude_err = (
            await self._reason_with_claude(fusion_data, min_conf)
        )
        tokens_used += claude_tokens
        if claude_err:
            errors.append(claude_err)

        duration_ms = (time.monotonic() - cycle_start) * 1000
        self._logger.info(
            "Signal cycle: %d tickers fused, %d actionable signals, %.0f ms",
            len(fusion_data),
            sum(1 for s in trade_signals if s.action != "hold"),
            duration_ms,
        )

        return self._build_result(
            success=True,
            data={
                "trade_signals": [self._signal_to_dict(s) for s in trade_signals],
                "signal_count": len(trade_signals),
            },
            errors=errors,
            duration_ms=duration_ms,
            tokens_used=tokens_used,
        )

    # ------------------------------------------------------------------
    # Fusion logic
    # ------------------------------------------------------------------

    def _compute_fusion(
        self,
        ticker: str,
        sentiment: dict[str, Any],
        technical: dict[str, Any],
        is_anomaly: bool,
    ) -> dict[str, Any]:
        """Compute weighted fusion score for a single ticker."""
        # Extract sentiment score (-1 to +1)
        sentiment_score = float(sentiment.get("composite_score", 0.0))
        sentiment_momentum = float(sentiment.get("momentum", 0.0))

        # Extract technical score: map direction + strength to -1..+1
        direction = technical.get("direction", "neutral")
        strength = float(technical.get("strength", 0.0))

        if direction == "bullish":
            technical_score = strength
        elif direction == "bearish":
            technical_score = -strength
        else:
            technical_score = 0.0

        # Extract volume signal
        volume_surge = technical.get("volume_surge", False)
        volume_ratio = float(technical.get("volume_ratio", 1.0))

        if volume_surge:
            # Amplify based on volume ratio, capped contribution
            volume_signal = 0.5 * min(volume_ratio / 3.0, 1.0)
        else:
            volume_signal = 0.0

        # Select weights based on anomaly status
        if is_anomaly:
            sw = ANOMALY_SENTIMENT_WEIGHT
            tw = ANOMALY_TECHNICAL_WEIGHT
            vw = ANOMALY_VOLUME_WEIGHT
        else:
            sw = DEFAULT_SENTIMENT_WEIGHT
            tw = DEFAULT_TECHNICAL_WEIGHT
            vw = DEFAULT_VOLUME_WEIGHT

        # Compute combined score
        combined = sw * sentiment_score + tw * technical_score + vw * volume_signal
        combined = max(-1.0, min(1.0, combined))  # Clamp

        # Check confluence: how many domains confirm the same direction?
        confirming = 0
        if combined > 0:
            # Bullish direction
            if sentiment_score > 0:
                confirming += 1
            if technical_score > 0:
                confirming += 1
            if volume_signal > 0:
                confirming += 1
        elif combined < 0:
            # Bearish direction
            if sentiment_score < 0:
                confirming += 1
            if technical_score < 0:
                confirming += 1
            # Volume doesn't confirm bearish direction on its own
        # neutral combined: confirming stays 0

        return {
            "ticker": ticker,
            "sentiment_score": round(sentiment_score, 4),
            "sentiment_momentum": round(sentiment_momentum, 4),
            "technical_score": round(technical_score, 4),
            "technical_direction": direction,
            "volume_signal": round(volume_signal, 4),
            "volume_surge": volume_surge,
            "volume_ratio": round(volume_ratio, 2),
            "combined_score": round(combined, 4),
            "confirming_domains": confirming,
            "is_anomaly": is_anomaly,
            "weights_used": {"sentiment": sw, "technical": tw, "volume": vw},
        }

    # ------------------------------------------------------------------
    # Claude reasoning
    # ------------------------------------------------------------------

    async def _reason_with_claude(
        self,
        fusion_data: list[dict[str, Any]],
        min_confidence: float,
    ) -> tuple[list[TradeSignal], int, Optional[str]]:
        """Use Claude Sonnet to reason about fusion scores and produce signals."""
        prompt = (
            "Evaluate the following multi-factor fusion data and produce trade "
            "recommendations for each ticker.\n\n"
            f"Minimum confidence threshold: {min_confidence}\n"
            "Minimum confirming domains for directional trade: 2\n\n"
            f"Fusion data:\n{json.dumps(fusion_data, indent=2)}\n\n"
            "For each ticker, decide BUY, SELL, or HOLD with confidence and rationale."
        )

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=self.system_prompt(),
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            tokens = response.usage.input_tokens + response.usage.output_tokens

            match = re.search(r"\[.*\]", raw, re.DOTALL)
            if not match:
                self._logger.warning("Claude returned non-JSON response for signals")
                return (
                    self._fallback_signals(fusion_data, min_confidence),
                    tokens,
                    "Claude returned non-JSON — used rule-based fallback",
                )

            parsed: list[dict[str, Any]] = json.loads(match.group())
            claude_by_ticker = {
                item["ticker"]: item for item in parsed if "ticker" in item
            }

            signals: list[TradeSignal] = []
            for fd in fusion_data:
                ticker = fd["ticker"]
                claude_rec = claude_by_ticker.get(ticker, {})

                action = claude_rec.get("action", "hold").lower()
                confidence = float(claude_rec.get("confidence", 0.5))
                rationale = claude_rec.get("rationale", "")

                # Enforce confidence gating
                if confidence < min_confidence:
                    action = "hold"
                    rationale = (
                        f"Below confidence threshold ({confidence:.2f} < "
                        f"{min_confidence}). {rationale}"
                    )

                # Enforce confluence requirement
                if fd["confirming_domains"] < 2 and action != "hold":
                    action = "hold"
                    rationale = (
                        f"Insufficient confluence ({fd['confirming_domains']} "
                        f"confirming domains). {rationale}"
                    )

                if action not in ("buy", "sell", "hold"):
                    action = "hold"

                signals.append(
                    TradeSignal(
                        ticker=ticker,
                        action=action,
                        combined_score=fd["combined_score"],
                        confidence=round(confidence, 4),
                        sentiment_score=fd["sentiment_score"],
                        technical_score=fd["technical_score"],
                        volume_signal=fd["volume_signal"],
                        rationale=rationale,
                        anomaly_adjusted=fd["is_anomaly"],
                    )
                )

            return signals, tokens, None

        except Exception as exc:
            self._logger.warning("Claude signal reasoning failed: %s", exc)
            return (
                self._fallback_signals(fusion_data, min_confidence),
                0,
                f"Claude reasoning failed: {exc} — used rule-based fallback",
            )

    # ------------------------------------------------------------------
    # Rule-based fallback
    # ------------------------------------------------------------------

    def _fallback_signals(
        self,
        fusion_data: list[dict[str, Any]],
        min_confidence: float,
    ) -> list[TradeSignal]:
        """Rule-based signal generation when Claude is unavailable."""
        signals: list[TradeSignal] = []

        for fd in fusion_data:
            combined = fd["combined_score"]
            confirming = fd["confirming_domains"]

            # Simple rule-based action
            if combined > DIRECTIONAL_THRESHOLD and confirming >= 2:
                action = "buy"
                confidence = min(0.5 + abs(combined) * 0.5, 0.9)
            elif combined < -DIRECTIONAL_THRESHOLD and confirming >= 2:
                action = "sell"
                confidence = min(0.5 + abs(combined) * 0.5, 0.9)
            else:
                action = "hold"
                confidence = 0.4

            # Enforce confidence gating
            if confidence < min_confidence:
                action = "hold"
                rationale = (
                    f"Rule-based fallback: below confidence threshold "
                    f"({confidence:.2f} < {min_confidence})"
                )
            elif action == "hold":
                rationale = (
                    f"Rule-based fallback: insufficient directional strength or "
                    f"confluence ({confirming} domains)"
                )
            else:
                rationale = (
                    f"Rule-based fallback: {action} signal with "
                    f"{confirming} confirming domains, score={combined:.3f}"
                )

            signals.append(
                TradeSignal(
                    ticker=fd["ticker"],
                    action=action,
                    combined_score=combined,
                    confidence=round(confidence, 4),
                    sentiment_score=fd["sentiment_score"],
                    technical_score=fd["technical_score"],
                    volume_signal=fd["volume_signal"],
                    rationale=rationale,
                    anomaly_adjusted=fd["is_anomaly"],
                )
            )

        return signals

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _signal_to_dict(signal: TradeSignal) -> dict[str, Any]:
        return {
            "ticker": signal.ticker,
            "action": signal.action,
            "combined_score": signal.combined_score,
            "confidence": signal.confidence,
            "sentiment_score": signal.sentiment_score,
            "technical_score": signal.technical_score,
            "volume_signal": signal.volume_signal,
            "rationale": signal.rationale,
            "anomaly_adjusted": signal.anomaly_adjusted,
        }
