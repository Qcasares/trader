"""
technical.py
------------
TechnicalAgent — price-action and indicator analyst.

Calculates RSI(14), MACD(12/26/9), Bollinger Bands(20/2σ), OBV, and
detects volume surges. Uses Claude Haiku to interpret indicator confluence
and identify chart patterns for each watchlist token.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
from anthropic import AsyncAnthropic

from src.agents.base import AgentResult, AgentRole, BaseAgent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class CandleData:
    """OHLCV candle."""

    timestamp: float
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class TechnicalIndicators:
    """Computed indicators for a single ticker."""

    ticker: str
    rsi_14: Optional[float]
    macd_line: Optional[float]
    macd_signal: Optional[float]
    macd_histogram: Optional[float]
    bb_upper: Optional[float]
    bb_middle: Optional[float]
    bb_lower: Optional[float]
    bb_position: Optional[float]   # 0.0 = at lower band, 1.0 = at upper band
    obv: Optional[float]
    obv_trend: Optional[str]       # "rising" | "falling" | "flat"
    volume_surge: bool
    volume_ratio: float            # current_vol / avg_vol
    current_price: Optional[float]
    price_change_pct: Optional[float]


@dataclass
class TechnicalSignal:
    """Claude-interpreted signal from indicator confluence."""

    ticker: str
    direction: str          # "bullish" | "bearish" | "neutral"
    strength: float         # 0.0 … 1.0
    patterns: list[str]     # detected chart patterns
    rationale: str
    indicators: TechnicalIndicators


# ---------------------------------------------------------------------------
# Indicator maths
# ---------------------------------------------------------------------------


def _ema(values: np.ndarray, period: int) -> np.ndarray:
    """Exponential moving average."""
    k = 2.0 / (period + 1)
    ema = np.zeros_like(values, dtype=float)
    ema[0] = values[0]
    for i in range(1, len(values)):
        ema[i] = values[i] * k + ema[i - 1] * (1 - k)
    return ema


def _rsi(closes: np.ndarray, period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def _macd(closes: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9
          ) -> tuple[Optional[float], Optional[float], Optional[float]]:
    if len(closes) < slow + signal:
        return None, None, None
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd_line = ema_fast - ema_slow
    macd_signal_line = _ema(macd_line, signal)
    histogram = macd_line - macd_signal_line
    return (
        round(float(macd_line[-1]), 6),
        round(float(macd_signal_line[-1]), 6),
        round(float(histogram[-1]), 6),
    )


def _bollinger(closes: np.ndarray, period: int = 20, std_dev: float = 2.0
               ) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    if len(closes) < period:
        return None, None, None, None
    window = closes[-period:]
    middle = float(np.mean(window))
    std = float(np.std(window, ddof=1))
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    current = float(closes[-1])
    band_width = upper - lower
    position = (current - lower) / band_width if band_width > 0 else 0.5
    return round(upper, 6), round(middle, 6), round(lower, 6), round(position, 4)


def _obv(closes: np.ndarray, volumes: np.ndarray) -> tuple[Optional[float], str]:
    if len(closes) < 2:
        return None, "flat"
    obv_values = np.zeros(len(closes))
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv_values[i] = obv_values[i - 1] + volumes[i]
        elif closes[i] < closes[i - 1]:
            obv_values[i] = obv_values[i - 1] - volumes[i]
        else:
            obv_values[i] = obv_values[i - 1]

    current = float(obv_values[-1])
    # Trend from last 5 candles
    if len(obv_values) >= 5:
        recent_slope = obv_values[-1] - obv_values[-5]
        trend = "rising" if recent_slope > 0 else "falling" if recent_slope < 0 else "flat"
    else:
        trend = "flat"
    return round(current, 2), trend


def _volume_surge(volumes: np.ndarray, lookback: int = 20, threshold: float = 2.0
                  ) -> tuple[bool, float]:
    if len(volumes) < lookback + 1:
        return False, 1.0
    avg_vol = float(np.mean(volumes[-(lookback + 1):-1]))
    current_vol = float(volumes[-1])
    ratio = current_vol / avg_vol if avg_vol > 0 else 1.0
    return ratio >= threshold, round(ratio, 2)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class TechnicalAgent(BaseAgent):
    """
    Specialist agent for technical analysis.

    For each enabled ticker:
    1. Computes RSI(14), MACD(12/26/9), Bollinger Bands(20/2σ), OBV
    2. Detects volume surges (>2× 20-period average)
    3. Sends indicator snapshot to Claude Haiku for confluence interpretation
    4. Returns a directional signal with strength and pattern labels
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        candle_count: int = 50,
    ) -> None:
        super().__init__(role=AgentRole.TECHNICAL, model=model, api_key=api_key)
        self._client = AsyncAnthropic(api_key=api_key)
        self._candle_count = candle_count

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    def system_prompt(self) -> str:
        return (
            "You are an expert crypto technical analyst.\n\n"
            "You receive a snapshot of price indicators for a crypto asset "
            "and must assess the current technical picture.\n\n"
            "Guidelines:\n"
            "- RSI: >70 = overbought (bearish bias), <30 = oversold (bullish bias), "
            "40–60 = neutral.\n"
            "- MACD: positive histogram = bullish momentum, negative = bearish. "
            "Look for crossovers and divergences.\n"
            "- Bollinger Bands: bb_position near 1.0 = near upper band (overbought), "
            "near 0.0 = near lower band (oversold). Band squeeze = low volatility / "
            "pending breakout.\n"
            "- OBV rising with price rising = healthy trend. OBV divergence = warning.\n"
            "- Volume surge (>2× avg) amplifies any signal.\n"
            "- Return ONLY a JSON object:\n"
            '  {"direction": "bullish|bearish|neutral", "strength": 0.0-1.0, '
            '"patterns": ["list of patterns"], "rationale": "brief explanation"}'
        )

    async def execute(self, context: dict[str, Any]) -> AgentResult:
        """
        Run one technical analysis cycle.

        Parameters
        ----------
        context : dict
            Must contain ``ohlcv_data`` mapping ticker -> list of OHLCV dicts.

        Returns
        -------
        AgentResult with keys:
            technical_signals  — {ticker: TechnicalSignal dict}
            indicators         — {ticker: TechnicalIndicators dict}
        """
        cycle_start = time.monotonic()
        errors: list[str] = []
        tokens_used = 0

        ohlcv_data: dict[str, list[dict[str, Any]]] = context.get("ohlcv_data", {})
        enabled_tickers: list[str] = context.get("enabled_tickers", [])

        signals: dict[str, TechnicalSignal] = {}
        indicators_map: dict[str, TechnicalIndicators] = {}

        for ticker in enabled_tickers:
            candles_raw = ohlcv_data.get(ticker, [])
            if not candles_raw:
                errors.append(f"No OHLCV data for {ticker}")
                continue

            try:
                indicators = self._compute_indicators(ticker, candles_raw)
                indicators_map[ticker] = indicators

                signal, signal_tokens, signal_err = await self._interpret_with_claude(
                    indicators
                )
                tokens_used += signal_tokens
                if signal_err:
                    errors.append(signal_err)
                    continue

                signals[ticker] = signal

            except Exception as exc:
                errors.append(f"Technical error for {ticker}: {exc}")
                self._logger.exception("Technical computation failed for %s", ticker)

        duration_ms = (time.monotonic() - cycle_start) * 1000
        self._logger.info(
            "Technical cycle: %d tickers analysed, %.0f ms, %d tokens",
            len(signals),
            duration_ms,
            tokens_used,
        )

        return self._build_result(
            success=True,
            data={
                "technical_signals": {
                    t: self._signal_to_dict(s) for t, s in signals.items()
                },
                "indicators": {
                    t: self._indicators_to_dict(ind)
                    for t, ind in indicators_map.items()
                },
            },
            errors=errors,
            duration_ms=duration_ms,
            tokens_used=tokens_used,
        )

    # ------------------------------------------------------------------
    # Indicator computation
    # ------------------------------------------------------------------

    def _compute_indicators(
        self, ticker: str, candles_raw: list[dict[str, Any]]
    ) -> TechnicalIndicators:
        """Compute all technical indicators from raw OHLCV data."""
        candles = sorted(candles_raw, key=lambda c: c.get("timestamp", 0))
        candles = candles[-self._candle_count :]

        closes = np.array([float(c["close"]) for c in candles])
        volumes = np.array([float(c["volume"]) for c in candles])

        rsi = _rsi(closes)
        macd_line, macd_sig, macd_hist = _macd(closes)
        bb_upper, bb_mid, bb_lower, bb_pos = _bollinger(closes)
        obv_val, obv_trend = _obv(closes, volumes)
        surge, vol_ratio = _volume_surge(volumes)

        price_change = None
        if len(closes) >= 2:
            price_change = round(
                (float(closes[-1]) - float(closes[-2])) / float(closes[-2]) * 100, 4
            )

        return TechnicalIndicators(
            ticker=ticker,
            rsi_14=rsi,
            macd_line=macd_line,
            macd_signal=macd_sig,
            macd_histogram=macd_hist,
            bb_upper=bb_upper,
            bb_middle=bb_mid,
            bb_lower=bb_lower,
            bb_position=bb_pos,
            obv=obv_val,
            obv_trend=obv_trend,
            volume_surge=surge,
            volume_ratio=vol_ratio,
            current_price=round(float(closes[-1]), 6) if len(closes) > 0 else None,
            price_change_pct=price_change,
        )

    # ------------------------------------------------------------------
    # Claude interpretation
    # ------------------------------------------------------------------

    async def _interpret_with_claude(
        self, indicators: TechnicalIndicators
    ) -> tuple[TechnicalSignal, int, Optional[str]]:
        """Send indicator snapshot to Claude Haiku for confluence interpretation."""
        import json

        ind_dict = self._indicators_to_dict(indicators)
        prompt = (
            f"Analyse the following technical indicators for {indicators.ticker} "
            f"and determine the directional bias:\n\n"
            f"{json.dumps(ind_dict, indent=2)}\n\n"
            "Return your assessment as the JSON format specified."
        )

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=512,
                system=self.system_prompt(),
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            tokens = response.usage.input_tokens + response.usage.output_tokens

            import re
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not match:
                return (
                    TechnicalSignal(
                        ticker=indicators.ticker,
                        direction="neutral",
                        strength=0.0,
                        patterns=[],
                        rationale="Claude returned non-JSON response",
                        indicators=indicators,
                    ),
                    tokens,
                    "Claude non-JSON response for technical signal",
                )

            parsed = json.loads(match.group())
            return (
                TechnicalSignal(
                    ticker=indicators.ticker,
                    direction=parsed.get("direction", "neutral"),
                    strength=float(parsed.get("strength", 0.0)),
                    patterns=parsed.get("patterns", []),
                    rationale=parsed.get("rationale", ""),
                    indicators=indicators,
                ),
                tokens,
                None,
            )

        except Exception as exc:
            return (
                TechnicalSignal(
                    ticker=indicators.ticker,
                    direction="neutral",
                    strength=0.0,
                    patterns=[],
                    rationale=str(exc),
                    indicators=indicators,
                ),
                0,
                f"Claude technical interpretation error for {indicators.ticker}: {exc}",
            )

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _indicators_to_dict(ind: TechnicalIndicators) -> dict[str, Any]:
        return {
            "ticker": ind.ticker,
            "current_price": ind.current_price,
            "price_change_pct": ind.price_change_pct,
            "rsi_14": ind.rsi_14,
            "macd_line": ind.macd_line,
            "macd_signal": ind.macd_signal,
            "macd_histogram": ind.macd_histogram,
            "bb_upper": ind.bb_upper,
            "bb_middle": ind.bb_middle,
            "bb_lower": ind.bb_lower,
            "bb_position": ind.bb_position,
            "obv": ind.obv,
            "obv_trend": ind.obv_trend,
            "volume_surge": ind.volume_surge,
            "volume_ratio": ind.volume_ratio,
        }

    @staticmethod
    def _signal_to_dict(sig: TechnicalSignal) -> dict[str, Any]:
        return {
            "ticker": sig.ticker,
            "direction": sig.direction,
            "strength": sig.strength,
            "patterns": sig.patterns,
            "rationale": sig.rationale,
        }
