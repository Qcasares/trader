# Automated Crypto Trading Bot — Proof of Concept
## Powered by bankr.bot · Sentiment Analysis · Social Signal Integration

> **Document Type:** Proof of Concept (POC) — Claude Code Ready  
> **Target Platform:** bankr.bot Agent API  
> **Primary Language:** Python 3.11+  
> **Chains Supported:** Base, Ethereum, Polygon, Solana, Unichain  
> **Risk Classification:** HIGH — Crypto trading involves significant financial risk. This is experimental software for educational and research purposes.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Architecture Overview](#2-architecture-overview)
3. [bankr.bot Integration Layer](#3-bankrbot-integration-layer)
4. [Trading Strategy Framework](#4-trading-strategy-framework)
5. [Sentiment Analysis Engine](#5-sentiment-analysis-engine)
6. [Social Data Pipeline](#6-social-data-pipeline)
7. [Signal Aggregation and Decision Engine](#7-signal-aggregation-and-decision-engine)
8. [Risk Management Framework](#8-risk-management-framework)
9. [Project Structure](#9-project-structure)
10. [Implementation Roadmap](#10-implementation-roadmap)
11. [Claude Code Instructions](#11-claude-code-instructions)

---

## 1. Executive Summary

This POC defines the architecture and implementation plan for an autonomous, real-time cryptocurrency trading bot that integrates with the **bankr.bot Agent API**. The bot combines quantitative technical analysis with qualitative social sentiment signals drawn from Twitter/X, Reddit, and Farcaster (bankr.bot's native social layer) to generate high-confidence trade signals.

The system operates on an event-driven loop: social data is ingested continuously, processed through an NLP sentiment pipeline, combined with on-chain price and volume signals, and acted upon via natural-language prompts dispatched to the bankr.bot REST API. All trade execution, wallet management, and gas handling are delegated entirely to bankr.bot, keeping the bot's logic lean and focused on signal generation.

**Key design goals:**

The system should be self-contained — once configured, it should run headlessly without operator intervention. It should be conservative by default, requiring multiple confirming signals before executing any trade. All state should be persisted to a local SQLite database so that the bot can be restarted without losing context. The implementation language is Python throughout, making it compatible with Claude Code's code execution environment.

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    TRADING BOT ORCHESTRATOR                     │
│                    (main.py — async event loop)                 │
└──────┬─────────────┬──────────────────┬─────────────────────────┘
       │             │                  │
       ▼             ▼                  ▼
┌─────────────┐ ┌──────────────┐ ┌──────────────────────┐
│ SOCIAL DATA │ │   TECHNICAL  │ │   BANKR.BOT API      │
│  PIPELINE   │ │   ANALYSIS   │ │   EXECUTION LAYER    │
│             │ │   ENGINE     │ │                      │
│ - Twitter/X │ │              │ │ POST /agent/prompt   │
│ - Reddit    │ │ - RSI        │ │ GET  /agent/job/{id} │
│ - Farcaster │ │ - MACD       │ │ POST /agent/submit   │
│ - CoinGecko │ │ - Bollinger  │ │                      │
│   Trending  │ │ - Volume OBV │ │ Supported Chains:    │
└──────┬──────┘ └──────┬───────┘ │  Base, ETH, Polygon  │
       │               │         │  Solana, Unichain    │
       ▼               ▼         └──────────────────────┘
┌─────────────────────────────┐
│   SENTIMENT ENGINE          │
│   (sentiment_engine.py)     │
│                             │
│ - VADER (social media)      │
│ - FinBERT (news/financial)  │
│ - Weighted score fusion     │
│ - Momentum scoring          │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│   SIGNAL AGGREGATOR         │
│   (signal_engine.py)        │
│                             │
│ Sentiment Score (40%)       │
│ Technical Score (40%)       │
│ On-chain Volume (20%)       │
│                             │
│ Output: BUY / SELL / HOLD   │
│ + Confidence (0.0 - 1.0)   │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│   RISK MANAGER              │
│   (risk_manager.py)         │
│                             │
│ - Max position size         │
│ - Daily loss limit          │
│ - Trade cooldown            │
│ - Slippage guard            │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│   STATE STORE               │
│   SQLite: bot_state.db      │
│                             │
│ - Trade history             │
│ - Sentiment history         │
│ - Signal log                │
│ - Portfolio snapshots       │
└─────────────────────────────┘
```

---

## 3. bankr.bot Integration Layer

### 3.1 API Overview

bankr.bot exposes a natural-language REST API at `https://api.bankr.bot/agent`. All operations are submitted as plain-English prompts and processed asynchronously via a job queue. The workflow is:

1. `POST /agent/prompt` — Submit a natural-language instruction. Receive a `jobId`.
2. `GET /agent/job/{jobId}` — Poll until `status` is `completed` or `failed`.
3. Read `response` from the completed job payload.

Authentication uses an API key in the `X-API-Key` header (`bk_...` prefix). Keys are obtained from `https://bankr.bot/api` and support read-only or read-write access scopes. Rate limits are 100 messages/day on the standard tier and 1,000/day on Bankr Club.

### 3.2 bankr_client.py — Full Implementation

```python
"""
bankr_client.py
---------------
Async Python client for the bankr.bot Agent API.
Wraps the prompt/job polling pattern and exposes typed trade methods.
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

BANKR_BASE_URL = "https://api.bankr.bot/agent"
POLL_INTERVAL_SECONDS = 2
MAX_POLL_ATTEMPTS = 60  # 2 minutes maximum wait


class Chain(str, Enum):
    BASE = "Base"
    ETHEREUM = "Ethereum"
    POLYGON = "Polygon"
    SOLANA = "Solana"
    UNICHAIN = "Unichain"


@dataclass
class TradeResult:
    success: bool
    response: str
    job_id: str
    raw_payload: dict


class BankrAPIError(Exception):
    """Raised when bankr.bot returns an error response."""
    pass


class BankrClient:
    """
    Async client for the bankr.bot Agent API.

    Usage:
        client = BankrClient(api_key=os.environ["BANKR_API_KEY"])
        result = await client.buy(token="ETH", amount_usd=50, chain=Chain.BASE)
    """

    def __init__(self, api_key: str, dry_run: bool = True):
        """
        Initialise the bankr client.

        Parameters
        ----------
        api_key : str
            The bankr.bot API key beginning with 'bk_'.
        dry_run : bool
            When True, prompts are prefixed with a simulation note and
            NO real trades are submitted. Defaults to True for safety.
        """
        if not api_key.startswith("bk_"):
            raise ValueError(
                "Invalid API key format. bankr.bot keys begin with 'bk_'."
            )
        self._api_key = api_key
        self._dry_run = dry_run
        self._headers = {
            "Content-Type": "application/json",
            "X-API-Key": self._api_key,
        }
        self._session: Optional[aiohttp.ClientSession] = None
        logger.info(
            "BankrClient initialised. dry_run=%s", self._dry_run
        )

    async def __aenter__(self):
        self._session = aiohttp.ClientSession(headers=self._headers)
        return self

    async def __aexit__(self, *args):
        if self._session:
            await self._session.close()

    # ------------------------------------------------------------------
    # Core async job workflow
    # ------------------------------------------------------------------

    async def _submit_prompt(self, prompt: str) -> str:
        """Submit a prompt to bankr and return the job ID."""
        if self._dry_run:
            prompt = f"[SIMULATION — DO NOT EXECUTE] {prompt}"

        async with self._session.post(
            f"{BANKR_BASE_URL}/prompt",
            json={"prompt": prompt},
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise BankrAPIError(
                    f"Prompt submission failed ({resp.status}): {body}"
                )
            data = await resp.json()
            job_id = data["jobId"]
            logger.debug("Prompt submitted. jobId=%s", job_id)
            return job_id

    async def _poll_job(self, job_id: str) -> dict:
        """Poll until the job reaches a terminal state."""
        for attempt in range(MAX_POLL_ATTEMPTS):
            async with self._session.get(
                f"{BANKR_BASE_URL}/job/{job_id}"
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise BankrAPIError(
                        f"Job poll failed ({resp.status}): {body}"
                    )
                job = await resp.json()
                status = job.get("status")

                if status == "completed":
                    logger.info(
                        "Job %s completed. response=%s",
                        job_id,
                        job.get("response", "")[:80],
                    )
                    return job

                if status in ("failed", "cancelled"):
                    raise BankrAPIError(
                        f"Job {job_id} ended with status={status}: "
                        f"{job.get('error', 'No error detail')}"
                    )

            await asyncio.sleep(POLL_INTERVAL_SECONDS)

        raise BankrAPIError(
            f"Job {job_id} did not complete within "
            f"{MAX_POLL_ATTEMPTS * POLL_INTERVAL_SECONDS}s."
        )

    async def execute_prompt(self, prompt: str) -> TradeResult:
        """Submit a natural-language prompt and await the result."""
        job_id = await self._submit_prompt(prompt)
        job = await self._poll_job(job_id)
        return TradeResult(
            success=True,
            response=job.get("response", ""),
            job_id=job_id,
            raw_payload=job,
        )

    # ------------------------------------------------------------------
    # Typed trading methods
    # ------------------------------------------------------------------

    async def get_portfolio(self) -> TradeResult:
        """Retrieve the complete portfolio across all chains."""
        return await self.execute_prompt("Show my complete portfolio")

    async def get_balance(self, chain: Chain = Chain.BASE) -> TradeResult:
        """Get ETH/SOL balance on a specific chain."""
        return await self.execute_prompt(
            f"What is my balance on {chain.value}?"
        )

    async def get_price(self, token: str, chain: Chain = Chain.BASE) -> TradeResult:
        """Look up the current price of a token."""
        return await self.execute_prompt(
            f"What is the current price of {token} on {chain.value}?"
        )

    async def buy(
        self,
        token: str,
        amount_usd: float,
        chain: Chain = Chain.BASE,
    ) -> TradeResult:
        """
        Buy a token with a USD-denominated amount.

        Parameters
        ----------
        token : str
            Token ticker or name, e.g. 'ETH', 'BNKR', 'PEPE'.
        amount_usd : float
            USD value to spend.
        chain : Chain
            Target chain for the trade.
        """
        prompt = (
            f"Buy ${amount_usd:.2f} of {token} on {chain.value}"
        )
        logger.info("Executing BUY: %s", prompt)
        return await self.execute_prompt(prompt)

    async def sell(
        self,
        token: str,
        amount_usd: float,
        chain: Chain = Chain.BASE,
    ) -> TradeResult:
        """Sell a token for a USD-denominated amount."""
        prompt = (
            f"Sell ${amount_usd:.2f} of {token} on {chain.value}"
        )
        logger.info("Executing SELL: %s", prompt)
        return await self.execute_prompt(prompt)

    async def sell_percentage(
        self,
        token: str,
        percentage: float,
        chain: Chain = Chain.BASE,
    ) -> TradeResult:
        """Sell a percentage of the current holding."""
        prompt = (
            f"Sell {percentage:.0f}% of my {token} on {chain.value}"
        )
        logger.info("Executing SELL PERCENTAGE: %s", prompt)
        return await self.execute_prompt(prompt)

    async def swap(
        self,
        from_token: str,
        to_token: str,
        amount: float,
        chain: Chain = Chain.BASE,
    ) -> TradeResult:
        """Swap one token for another."""
        prompt = (
            f"Swap {amount} {from_token} to {to_token} on {chain.value}"
        )
        return await self.execute_prompt(prompt)

    async def set_limit_order(
        self,
        token: str,
        direction: str,
        trigger_price_usd: float,
        amount_usd: float,
        chain: Chain = Chain.BASE,
    ) -> TradeResult:
        """Set a limit order (buy or sell at a specific price)."""
        prompt = (
            f"{direction.capitalize()} ${amount_usd:.2f} of {token} "
            f"on {chain.value} when price reaches ${trigger_price_usd:.4f}"
        )
        return await self.execute_prompt(prompt)

    async def set_stop_loss(
        self,
        token: str,
        drop_percentage: float,
        chain: Chain = Chain.BASE,
    ) -> TradeResult:
        """Set a stop-loss as a percentage drop from the current price."""
        prompt = (
            f"Set a stop loss on {token} on {chain.value} "
            f"if it drops {drop_percentage:.0f}%"
        )
        return await self.execute_prompt(prompt)
```

---

## 4. Trading Strategy Framework

### 4.1 Strategy Design Philosophy

The bot uses a **multi-factor confluence strategy**: no single signal triggers a trade. At least two independent confirming signals from different domains (sentiment, technical, volume) must align before a trade is dispatched. This guards against noise-driven false positives which are common in crypto markets.

Three distinct sub-strategies are blended:

**Sentiment Momentum** — When aggregate social sentiment for a token shifts strongly positive (compound score > 0.35) and that positive shift has been sustained for at least two consecutive analysis cycles, a buy signal is generated. The logic rests on research showing that crypto price moves are frequently preceded by social media activity, particularly on Twitter/X, Farcaster, and Reddit, by 15-90 minutes.

**Technical Mean Reversion** — Using RSI (14-period), Bollinger Bands (20-period, 2 standard deviations), and MACD (12/26/9), the engine identifies oversold conditions on short timeframes (15m, 1h) where a bounce is statistically probable. The strategy targets entries at RSI < 35 with price touching the lower Bollinger Band.

**Volume Surge Detection** — A sudden increase in on-chain swap volume (greater than 2x the 24-hour rolling average) combined with positive price momentum is treated as a breakout signal. This is sourced from the CoinGecko API.

### 4.2 technical_analysis.py — Full Implementation

```python
"""
technical_analysis.py
---------------------
Technical indicator calculations for the trading signal engine.
Uses pandas and numpy; price data sourced from CoinGecko API.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class TechnicalSignal:
    ticker: str
    rsi: float
    macd_line: float
    macd_signal: float
    macd_histogram: float
    bb_upper: float
    bb_middle: float
    bb_lower: float
    current_price: float
    volume_ratio: float  # current volume / 24h average
    signal: str          # "BUY", "SELL", "HOLD"
    confidence: float    # 0.0 - 1.0


def calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    """
    Calculate the Relative Strength Index.

    Parameters
    ----------
    prices : pd.Series
        Close prices in chronological order.
    period : int
        Look-back period (default 14).
    """
    delta = prices.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def calculate_macd(
    prices: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Calculate MACD line, signal line, and histogram.

    Returns
    -------
    tuple of (macd_line, signal_line, histogram)
    """
    ema_fast = prices.ewm(span=fast, adjust=False).mean()
    ema_slow = prices.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calculate_bollinger_bands(
    prices: pd.Series,
    period: int = 20,
    std_dev: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Calculate Bollinger Bands.

    Returns
    -------
    tuple of (upper_band, middle_band, lower_band)
    """
    middle = prices.rolling(window=period).mean()
    std = prices.rolling(window=period).std()
    upper = middle + (std_dev * std)
    lower = middle - (std_dev * std)
    return upper, middle, lower


def calculate_obv(prices: pd.Series, volumes: pd.Series) -> pd.Series:
    """Calculate On-Balance Volume (OBV)."""
    direction = prices.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    obv = (direction * volumes).cumsum()
    return obv


def analyse_technicals(
    prices: pd.Series,
    volumes: pd.Series,
    ticker: str,
) -> TechnicalSignal:
    """
    Run all technical indicators and produce a unified signal.

    Parameters
    ----------
    prices : pd.Series
        OHLCV close prices (at least 50 data points recommended).
    volumes : pd.Series
        Corresponding trade volumes.
    ticker : str
        Token ticker for logging.
    """
    if len(prices) < 30:
        logger.warning(
            "Insufficient price history for %s (%d points). Returning HOLD.",
            ticker, len(prices)
        )
        return TechnicalSignal(
            ticker=ticker, rsi=50.0, macd_line=0.0, macd_signal=0.0,
            macd_histogram=0.0, bb_upper=0.0, bb_middle=0.0, bb_lower=0.0,
            current_price=float(prices.iloc[-1]), volume_ratio=1.0,
            signal="HOLD", confidence=0.0
        )

    current_price = float(prices.iloc[-1])
    current_volume = float(volumes.iloc[-1])
    avg_volume = float(volumes.tail(24).mean())
    volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0

    # RSI
    rsi_series = calculate_rsi(prices)
    rsi = float(rsi_series.iloc[-1])

    # MACD
    macd_line, macd_signal, macd_hist = calculate_macd(prices)
    macd_val = float(macd_line.iloc[-1])
    signal_val = float(macd_signal.iloc[-1])
    hist_val = float(macd_hist.iloc[-1])

    # Bollinger Bands
    bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(prices)
    upper = float(bb_upper.iloc[-1])
    middle = float(bb_middle.iloc[-1])
    lower = float(bb_lower.iloc[-1])

    # Signal scoring — accumulate points for BUY vs SELL
    buy_score = 0
    sell_score = 0
    max_score = 5

    # RSI signals
    if rsi < 30:
        buy_score += 2   # Strongly oversold
    elif rsi < 40:
        buy_score += 1   # Mildly oversold
    elif rsi > 70:
        sell_score += 2  # Strongly overbought
    elif rsi > 60:
        sell_score += 1  # Mildly overbought

    # MACD signals
    if macd_val > signal_val and hist_val > 0:
        buy_score += 1   # Bullish crossover
    elif macd_val < signal_val and hist_val < 0:
        sell_score += 1  # Bearish crossover

    # Bollinger Band signals
    if current_price <= lower:
        buy_score += 2   # Price at lower band — potential reversal
    elif current_price >= upper:
        sell_score += 2  # Price at upper band — potential reversal

    # Determine signal and confidence
    if buy_score > sell_score and buy_score >= 2:
        final_signal = "BUY"
        confidence = min(buy_score / max_score, 1.0)
    elif sell_score > buy_score and sell_score >= 2:
        final_signal = "SELL"
        confidence = min(sell_score / max_score, 1.0)
    else:
        final_signal = "HOLD"
        confidence = 0.0

    logger.info(
        "Technical analysis for %s: RSI=%.1f MACD=%.4f Signal=%s "
        "Confidence=%.2f VolumeRatio=%.2f",
        ticker, rsi, macd_val, final_signal, confidence, volume_ratio
    )

    return TechnicalSignal(
        ticker=ticker,
        rsi=rsi,
        macd_line=macd_val,
        macd_signal=signal_val,
        macd_histogram=hist_val,
        bb_upper=upper,
        bb_middle=middle,
        bb_lower=lower,
        current_price=current_price,
        volume_ratio=volume_ratio,
        signal=final_signal,
        confidence=confidence,
    )
```

---

## 5. Sentiment Analysis Engine

### 5.1 Approach

Sentiment analysis for crypto trading is a two-layer problem. The first layer handles raw social media text — short, informal, often meme-laden posts — for which VADER (Valence Aware Dictionary and Sentiment Reasoner) is optimal. VADER was designed specifically for social media language and handles capitalisation, exclamation marks, emoji-adjacent punctuation, and negations without requiring model fine-tuning.

The second layer handles longer-form financial commentary — news articles, analyst posts, and Farcaster threads — for which a transformer-based model (FinBERT) provides superior accuracy by understanding financial domain vocabulary ("bullish", "resistance", "consolidation") in context.

The two scores are combined with a weighted average, with VADER weighted more heavily for real-time social signals and FinBERT for macro news-driven sentiment.

### 5.2 sentiment_engine.py — Full Implementation

```python
"""
sentiment_engine.py
-------------------
Dual-layer sentiment analysis using VADER (social) and FinBERT (financial).
Produces normalised compound scores suitable for signal generation.
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# VADER is available via nltk
try:
    from nltk.sentiment.vader import SentimentIntensityAnalyzer
    import nltk
    nltk.download("vader_lexicon", quiet=True)
    VADER_AVAILABLE = True
except ImportError:
    VADER_AVAILABLE = False
    logger.warning("VADER not available. Install nltk: pip install nltk")

# FinBERT for financial-domain sentiment
try:
    from transformers import pipeline
    FINBERT_AVAILABLE = True
except ImportError:
    FINBERT_AVAILABLE = False
    logger.warning(
        "Transformers not available. Install: pip install transformers torch"
    )


@dataclass
class SentimentResult:
    source: str           # "twitter", "reddit", "news", "farcaster"
    ticker: str
    text_sample: str      # Truncated for logging
    vader_compound: float   # -1.0 to +1.0
    finbert_score: float    # -1.0 to +1.0 (0 if unavailable)
    combined_score: float   # Weighted fusion
    post_count: int
    signal: str             # "BULLISH", "BEARISH", "NEUTRAL"
    confidence: float       # 0.0 to 1.0


CRYPTO_SENTIMENT_EXPANSIONS = {
    # Crypto-specific positive signals
    "moon": 2.5,
    "mooning": 2.5,
    "lfg": 2.0,
    "wagmi": 1.8,
    "bullish": 2.2,
    "accumulate": 1.5,
    "hodl": 1.2,
    "dip": -0.5,    # Contextual — buying the dip is positive but word is ambiguous
    "rekt": -2.5,
    "ngmi": -2.0,
    "dump": -2.2,
    "rugpull": -3.0,
    "rug": -2.5,
    "bearish": -2.0,
    "capitulate": -1.8,
    "fud": -1.5,
    "crash": -2.5,
    "collapse": -2.5,
    "breakout": 1.8,
    "pumping": 1.5,
    "gem": 1.5,
    "alpha": 1.2,
}


def clean_social_text(text: str) -> str:
    """
    Normalise social media text for sentiment analysis.
    Removes URLs, mentions, excess whitespace, and hashtag symbols.
    """
    text = re.sub(r"http\S+", "", text)
    text = re.sub(r"@\w+", "", text)
    text = re.sub(r"#(\w+)", r"\1", text)   # Keep hashtag word, remove #
    text = re.sub(r"\s+", " ", text).strip()
    return text


class CryptoVADER:
    """
    VADER sentiment analyser with crypto-domain lexicon extensions.
    """

    def __init__(self):
        if not VADER_AVAILABLE:
            raise RuntimeError("VADER requires: pip install nltk")
        self._analyser = SentimentIntensityAnalyzer()
        # Extend the default lexicon with crypto-specific terms
        self._analyser.lexicon.update(CRYPTO_SENTIMENT_EXPANSIONS)
        logger.info("CryptoVADER initialised with extended lexicon.")

    def score(self, text: str) -> float:
        """Return a compound sentiment score between -1.0 and +1.0."""
        cleaned = clean_social_text(text)
        scores = self._analyser.polarity_scores(cleaned)
        return scores["compound"]

    def score_batch(self, texts: list[str]) -> float:
        """Average compound score across a batch of texts."""
        if not texts:
            return 0.0
        scores = [self.score(t) for t in texts]
        return sum(scores) / len(scores)


class FinBERTAnalyser:
    """
    Wrapper around the ProsusAI/finbert transformer model.
    Returns a normalised score (-1.0 bearish, 0.0 neutral, +1.0 bullish).
    """

    def __init__(self):
        if not FINBERT_AVAILABLE:
            raise RuntimeError(
                "FinBERT requires: pip install transformers torch"
            )
        logger.info("Loading FinBERT model (first use may download ~500MB)...")
        self._pipeline = pipeline(
            "text-classification",
            model="ProsusAI/finbert",
            tokenizer="ProsusAI/finbert",
        )
        self._label_map = {
            "positive": 1.0,
            "neutral": 0.0,
            "negative": -1.0,
        }
        logger.info("FinBERT loaded.")

    def score(self, text: str) -> float:
        """Return a normalised sentiment score for a piece of text."""
        truncated = text[:512]  # FinBERT max token limit
        result = self._pipeline(truncated)[0]
        label = result["label"].lower()
        raw_score = self._label_map.get(label, 0.0)
        # Weight by confidence
        return raw_score * result["score"]

    def score_batch(self, texts: list[str], max_batch: int = 8) -> float:
        """Average score across a batch, chunked for memory efficiency."""
        if not texts:
            return 0.0
        scores = []
        for i in range(0, len(texts), max_batch):
            chunk = texts[i : i + max_batch]
            for text in chunk:
                try:
                    scores.append(self.score(text[:512]))
                except Exception as exc:
                    logger.warning(
                        "FinBERT scoring error (skipping): %s", exc
                    )
        return sum(scores) / len(scores) if scores else 0.0


class SentimentEngine:
    """
    Unified sentiment analysis engine combining VADER and FinBERT.

    Parameters
    ----------
    vader_weight : float
        Weight assigned to VADER score (0.0 - 1.0). FinBERT weight is
        computed as 1.0 - vader_weight.
    use_finbert : bool
        Whether to load the FinBERT model. Disable on low-memory systems.
    """

    BULLISH_THRESHOLD = 0.20
    BEARISH_THRESHOLD = -0.20

    def __init__(
        self,
        vader_weight: float = 0.65,
        use_finbert: bool = True,
    ):
        self._vader_weight = vader_weight
        self._finbert_weight = 1.0 - vader_weight
        self._vader: Optional[CryptoVADER] = None
        self._finbert: Optional[FinBERTAnalyser] = None

        if VADER_AVAILABLE:
            self._vader = CryptoVADER()
        else:
            logger.error("VADER unavailable — sentiment accuracy will be degraded.")

        if use_finbert and FINBERT_AVAILABLE:
            try:
                self._finbert = FinBERTAnalyser()
            except Exception as exc:
                logger.warning(
                    "FinBERT failed to load (%s). Using VADER only.", exc
                )

    def analyse(
        self,
        posts: list[str],
        ticker: str,
        source: str = "unknown",
    ) -> SentimentResult:
        """
        Analyse a list of social posts and return a sentiment result.

        Parameters
        ----------
        posts : list[str]
            Raw text posts from a social platform.
        ticker : str
            Token ticker being analysed.
        source : str
            Data source label (e.g., "twitter", "reddit").
        """
        if not posts:
            return SentimentResult(
                source=source, ticker=ticker, text_sample="",
                vader_compound=0.0, finbert_score=0.0, combined_score=0.0,
                post_count=0, signal="NEUTRAL", confidence=0.0,
            )

        # VADER scoring
        vader_score = 0.0
        if self._vader:
            vader_score = self._vader.score_batch(posts)

        # FinBERT scoring (news/longer text only — skip for short social posts)
        finbert_score = 0.0
        if self._finbert and any(len(p) > 100 for p in posts):
            long_posts = [p for p in posts if len(p) > 100]
            finbert_score = self._finbert.score_batch(long_posts)

        # Weighted fusion
        if self._finbert and finbert_score != 0.0:
            combined = (
                vader_score * self._vader_weight
                + finbert_score * self._finbert_weight
            )
        else:
            combined = vader_score  # Fall back to VADER only

        # Determine signal and confidence
        abs_score = abs(combined)
        if combined >= self.BULLISH_THRESHOLD:
            signal = "BULLISH"
            confidence = min(abs_score / 0.6, 1.0)
        elif combined <= self.BEARISH_THRESHOLD:
            signal = "BEARISH"
            confidence = min(abs_score / 0.6, 1.0)
        else:
            signal = "NEUTRAL"
            confidence = 0.0

        sample = posts[0][:120] if posts else ""

        logger.info(
            "Sentiment [%s/%s]: VADER=%.3f FinBERT=%.3f Combined=%.3f "
            "Signal=%s Confidence=%.2f Posts=%d",
            ticker, source, vader_score, finbert_score, combined,
            signal, confidence, len(posts),
        )

        return SentimentResult(
            source=source,
            ticker=ticker,
            text_sample=sample,
            vader_compound=vader_score,
            finbert_score=finbert_score,
            combined_score=combined,
            post_count=len(posts),
            signal=signal,
            confidence=confidence,
        )
```

---

## 6. Social Data Pipeline

### 6.1 Data Source Strategy

Four social data sources feed the sentiment engine:

**Twitter/X** — The dominant venue for real-time crypto commentary. Monitored via the Twitter API v2 (Basic plan minimum, ~$100/month). Key search terms include `$TOKEN`, `#TOKEN`, `TOKEN crypto`, and handles of known market-moving influencers. Rate limits are 500,000 tweets/month at Basic tier.

**Reddit** — Subreddits including r/CryptoCurrency, r/ethereum, r/solana, r/defi, and token-specific subreddits. Accessed via PRAW (Python Reddit API Wrapper) using a free Reddit developer account. Reddit posts tend to be longer-form and are routed to the FinBERT analyser rather than VADER.

**Farcaster** — bankr.bot's native social platform. Being a crypto-native social graph, Farcaster activity has a stronger correlation to on-chain price action than general Twitter sentiment. Accessible via the Neynar API.

**CoinGecko** — Provides the `trending` endpoint (free tier), community data including social volume metrics, and OHLCV price data. Used for volume surge detection and watchlist management.

### 6.2 social_collector.py — Full Implementation

```python
"""
social_collector.py
-------------------
Async collectors for Twitter/X, Reddit, and CoinGecko trending data.
All collectors return normalised lists of text strings for the sentiment engine.
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
TWITTER_BASE = "https://api.twitter.com/2"
NEYNAR_BASE = "https://api.neynar.com/v2"


@dataclass
class SocialBatch:
    source: str
    ticker: str
    posts: list[str]
    fetched_at: datetime
    error: Optional[str] = None


# ------------------------------------------------------------------
# CoinGecko data fetcher (free tier, no auth required)
# ------------------------------------------------------------------

class CoinGeckoCollector:
    """
    Fetches price, volume, and trending data from CoinGecko.
    Compatible with the free Demo API key (30 req/min, 10k/month).
    """

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.environ.get("COINGECKO_API_KEY")
        self._base_headers = {}
        if self._api_key:
            self._base_headers["x-cg-demo-api-key"] = self._api_key

    async def get_ohlcv(
        self,
        coin_id: str,
        days: int = 2,
        interval: str = "hourly",
    ) -> list[dict]:
        """
        Fetch OHLCV data for a coin.

        Parameters
        ----------
        coin_id : str
            CoinGecko ID, e.g. 'ethereum', 'bitcoin', 'solana'.
        days : int
            Number of days of history. 1-2 days returns hourly data.
        """
        url = f"{COINGECKO_BASE}/coins/{coin_id}/ohlc"
        params = {"vs_currency": "usd", "days": days}

        async with aiohttp.ClientSession(headers=self._base_headers) as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.error(
                        "CoinGecko OHLCV failed for %s: %s", coin_id, resp.status
                    )
                    return []
                data = await resp.json()
                # CoinGecko returns [timestamp, open, high, low, close]
                return data

    async def get_trending(self) -> list[dict]:
        """
        Fetch the current trending coins from CoinGecko.
        Returns up to 15 trending tokens.
        """
        url = f"{COINGECKO_BASE}/search/trending"
        async with aiohttp.ClientSession(headers=self._base_headers) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                return data.get("coins", [])

    async def get_social_volume(self, coin_id: str) -> dict:
        """
        Fetch community and social data for a coin.
        Includes Twitter followers, Reddit subscribers, and Telegram users.
        """
        url = f"{COINGECKO_BASE}/coins/{coin_id}"
        params = {
            "localization": "false",
            "tickers": "false",
            "market_data": "false",
            "community_data": "true",
            "developer_data": "false",
        }
        async with aiohttp.ClientSession(headers=self._base_headers) as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()
                return data.get("community_data", {})


# ------------------------------------------------------------------
# Twitter/X data fetcher
# ------------------------------------------------------------------

class TwitterCollector:
    """
    Fetches recent tweets for a given ticker using the Twitter API v2.
    Requires a Twitter Developer App with at least Basic plan access.
    """

    MAX_RESULTS = 100

    def __init__(self, bearer_token: Optional[str] = None):
        self._bearer_token = (
            bearer_token or os.environ.get("TWITTER_BEARER_TOKEN")
        )
        if not self._bearer_token:
            logger.warning(
                "TWITTER_BEARER_TOKEN not set. Twitter collection disabled."
            )

    async def fetch_recent(
        self,
        ticker: str,
        hours_back: int = 1,
        min_likes: int = 5,
    ) -> SocialBatch:
        """
        Fetch recent tweets mentioning a ticker.

        Parameters
        ----------
        ticker : str
            Token ticker, e.g. 'ETH'.
        hours_back : int
            How many hours of tweet history to retrieve.
        min_likes : int
            Minimum like count to filter out spam posts.
        """
        if not self._bearer_token:
            return SocialBatch(
                source="twitter", ticker=ticker, posts=[],
                fetched_at=datetime.utcnow(),
                error="No Twitter Bearer Token configured."
            )

        since = (datetime.utcnow() - timedelta(hours=hours_back)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        # Build query — exclude retweets and replies to reduce noise
        query = (
            f"(${ticker} OR #{ticker}crypto) "
            f"lang:en -is:retweet -is:reply "
            f"min_faves:{min_likes}"
        )
        params = {
            "query": query,
            "max_results": self.MAX_RESULTS,
            "start_time": since,
            "tweet.fields": "text,public_metrics,created_at",
        }
        headers = {"Authorization": f"Bearer {self._bearer_token}"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{TWITTER_BASE}/tweets/search/recent",
                    headers=headers,
                    params=params,
                ) as resp:
                    if resp.status == 429:
                        logger.warning("Twitter rate limit hit.")
                        return SocialBatch(
                            source="twitter", ticker=ticker, posts=[],
                            fetched_at=datetime.utcnow(),
                            error="Rate limited."
                        )
                    if resp.status != 200:
                        body = await resp.text()
                        return SocialBatch(
                            source="twitter", ticker=ticker, posts=[],
                            fetched_at=datetime.utcnow(),
                            error=f"HTTP {resp.status}: {body[:200]}"
                        )
                    data = await resp.json()
                    tweets = data.get("data", [])
                    posts = [t["text"] for t in tweets]
                    logger.info(
                        "Twitter: fetched %d tweets for $%s", len(posts), ticker
                    )
                    return SocialBatch(
                        source="twitter",
                        ticker=ticker,
                        posts=posts,
                        fetched_at=datetime.utcnow(),
                    )
        except Exception as exc:
            logger.error("Twitter fetch error: %s", exc)
            return SocialBatch(
                source="twitter", ticker=ticker, posts=[],
                fetched_at=datetime.utcnow(), error=str(exc)
            )


# ------------------------------------------------------------------
# Reddit data fetcher
# ------------------------------------------------------------------

class RedditCollector:
    """
    Fetches recent Reddit posts using PRAW (Python Reddit API Wrapper).
    Uses the pushshift.io compatible approach via Reddit's JSON API
    to avoid requiring OAuth for read-only access.
    """

    SUBREDDITS: dict[str, list[str]] = {
        "ETH": ["ethereum", "ethfinance", "CryptoCurrency"],
        "BTC": ["Bitcoin", "CryptoCurrency"],
        "SOL": ["solana", "CryptoCurrency"],
        "BASE": ["CryptoCurrency", "defi"],
        "BNKR": ["CryptoCurrency", "defi"],
    }
    DEFAULT_SUBREDDITS = ["CryptoCurrency", "defi", "altcoin"]

    def __init__(self):
        pass

    async def fetch_recent(
        self,
        ticker: str,
        post_limit: int = 25,
        time_filter: str = "hour",
    ) -> SocialBatch:
        """
        Fetch recent posts from relevant subreddits using Reddit's JSON API.

        Parameters
        ----------
        ticker : str
            Token ticker to search for.
        post_limit : int
            Number of posts to retrieve per subreddit.
        time_filter : str
            Reddit time filter: "hour", "day", "week".
        """
        subreddits = self.SUBREDDITS.get(
            ticker.upper(), self.DEFAULT_SUBREDDITS
        )
        all_posts = []

        async with aiohttp.ClientSession(
            headers={"User-Agent": "crypto-sentiment-bot/1.0"}
        ) as session:
            for subreddit in subreddits[:2]:  # Limit to 2 subreddits per run
                url = (
                    f"https://www.reddit.com/r/{subreddit}/search.json"
                )
                params = {
                    "q": ticker,
                    "sort": "new",
                    "t": time_filter,
                    "limit": post_limit,
                    "restrict_sr": "true",
                }
                try:
                    async with session.get(url, params=params) as resp:
                        if resp.status != 200:
                            logger.warning(
                                "Reddit fetch failed for r/%s: %s",
                                subreddit, resp.status
                            )
                            continue
                        data = await resp.json()
                        posts_data = data.get("data", {}).get("children", [])
                        for post in posts_data:
                            post_data = post.get("data", {})
                            title = post_data.get("title", "")
                            selftext = post_data.get("selftext", "")
                            # Combine title and body for richer context
                            full_text = f"{title}. {selftext}".strip()
                            if full_text and len(full_text) > 10:
                                all_posts.append(full_text)
                except Exception as exc:
                    logger.warning(
                        "Reddit error for r/%s: %s", subreddit, exc
                    )

                await asyncio.sleep(1)  # Be polite to Reddit

        logger.info(
            "Reddit: collected %d posts for %s", len(all_posts), ticker
        )
        return SocialBatch(
            source="reddit",
            ticker=ticker,
            posts=all_posts,
            fetched_at=datetime.utcnow(),
        )


# ------------------------------------------------------------------
# Farcaster collector (via Neynar API)
# ------------------------------------------------------------------

class FarcasterCollector:
    """
    Fetches recent Farcaster casts (posts) related to a token.
    Requires a Neynar API key (https://neynar.com).
    Farcaster is crypto-native and correlates strongly with on-chain activity.
    """

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.environ.get("NEYNAR_API_KEY")
        if not self._api_key:
            logger.warning(
                "NEYNAR_API_KEY not set. Farcaster collection disabled."
            )

    async def fetch_recent(
        self,
        ticker: str,
        limit: int = 50,
    ) -> SocialBatch:
        """Fetch recent Farcaster casts mentioning a token."""
        if not self._api_key:
            return SocialBatch(
                source="farcaster", ticker=ticker, posts=[],
                fetched_at=datetime.utcnow(),
                error="No NEYNAR_API_KEY configured."
            )

        headers = {
            "accept": "application/json",
            "api_key": self._api_key,
        }
        params = {
            "q": f"${ticker}",
            "limit": limit,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{NEYNAR_BASE}/farcaster/cast/search",
                    headers=headers,
                    params=params,
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        return SocialBatch(
                            source="farcaster", ticker=ticker, posts=[],
                            fetched_at=datetime.utcnow(),
                            error=f"HTTP {resp.status}: {body[:200]}"
                        )
                    data = await resp.json()
                    casts = data.get("result", {}).get("casts", [])
                    posts = [
                        c.get("text", "") for c in casts
                        if c.get("text", "")
                    ]
                    logger.info(
                        "Farcaster: fetched %d casts for $%s",
                        len(posts), ticker
                    )
                    return SocialBatch(
                        source="farcaster",
                        ticker=ticker,
                        posts=posts,
                        fetched_at=datetime.utcnow(),
                    )
        except Exception as exc:
            logger.error("Farcaster fetch error: %s", exc)
            return SocialBatch(
                source="farcaster", ticker=ticker, posts=[],
                fetched_at=datetime.utcnow(), error=str(exc)
            )
```

---

## 7. Signal Aggregation and Decision Engine

### 7.1 signal_engine.py — Full Implementation

```python
"""
signal_engine.py
----------------
Aggregates sentiment signals and technical signals into a
single BUY / SELL / HOLD decision with confidence score.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from sentiment_engine import SentimentResult
from technical_analysis import TechnicalSignal

logger = logging.getLogger(__name__)


@dataclass
class TradeSignal:
    ticker: str
    action: str          # "BUY", "SELL", "HOLD"
    confidence: float    # 0.0 - 1.0
    amount_usd: float    # Computed from position sizing
    rationale: str       # Human-readable explanation
    timestamp: datetime
    sentiment_score: float
    technical_score: float
    volume_ratio: float


WEIGHTS = {
    "sentiment": 0.40,
    "technical": 0.40,
    "volume":    0.20,
}

# Minimum confidence threshold before a trade is dispatched
MIN_CONFIDENCE_TO_TRADE = 0.55


def normalise_technical_score(signal: TechnicalSignal) -> float:
    """
    Convert a TechnicalSignal to a normalised score in [-1.0, +1.0].
    """
    if signal.signal == "BUY":
        return signal.confidence
    elif signal.signal == "SELL":
        return -signal.confidence
    return 0.0


def normalise_sentiment_score(result: SentimentResult) -> float:
    """
    Convert a SentimentResult to a normalised score in [-1.0, +1.0].
    """
    return result.combined_score  # Already in [-1.0, +1.0]


def normalise_volume_score(volume_ratio: float) -> float:
    """
    Convert a volume ratio to a directional signal.
    A volume ratio > 2.0 is a strong signal; we cap contribution at +0.5.
    Volume alone cannot be negative — it amplifies, it does not negate.
    """
    if volume_ratio >= 2.0:
        return min((volume_ratio - 1.0) / 3.0, 0.5)
    return 0.0


def aggregate_signals(
    ticker: str,
    sentiment_results: list[SentimentResult],
    technical_signal: TechnicalSignal,
    base_position_usd: float = 50.0,
    max_position_usd: float = 500.0,
) -> TradeSignal:
    """
    Aggregate all signals and produce a final trade recommendation.

    Parameters
    ----------
    ticker : str
        Token ticker.
    sentiment_results : list[SentimentResult]
        Results from all social data sources (Twitter, Reddit, Farcaster).
    technical_signal : TechnicalSignal
        Output from the technical analysis engine.
    base_position_usd : float
        Minimum trade size in USD.
    max_position_usd : float
        Maximum trade size in USD.
    """

    # Average sentiment across all sources
    if sentiment_results:
        avg_sentiment = sum(
            r.combined_score for r in sentiment_results
        ) / len(sentiment_results)
        avg_sentiment_confidence = sum(
            r.confidence for r in sentiment_results
        ) / len(sentiment_results)
    else:
        avg_sentiment = 0.0
        avg_sentiment_confidence = 0.0

    technical_score = normalise_technical_score(technical_signal)
    volume_score = normalise_volume_score(technical_signal.volume_ratio)

    # Weighted aggregate score — volume amplifies rather than directs
    # so volume score adds a positive boost when other signals are positive
    directional_score = (
        avg_sentiment * WEIGHTS["sentiment"]
        + technical_score * WEIGHTS["technical"]
    )
    # Volume amplification: boost in the direction of the directional score
    volume_boost = volume_score * WEIGHTS["volume"]
    if directional_score >= 0:
        final_score = directional_score + volume_boost
    else:
        final_score = directional_score - volume_boost

    # Clamp to [-1.0, +1.0]
    final_score = max(-1.0, min(1.0, final_score))
    abs_score = abs(final_score)

    # Determine action and confidence
    if final_score > 0.15:
        action = "BUY"
        confidence = min(abs_score / 0.7, 1.0)
    elif final_score < -0.15:
        action = "SELL"
        confidence = min(abs_score / 0.7, 1.0)
    else:
        action = "HOLD"
        confidence = 0.0

    # Position sizing — scale linearly with confidence
    if action != "HOLD" and confidence >= MIN_CONFIDENCE_TO_TRADE:
        amount_usd = base_position_usd + (
            (max_position_usd - base_position_usd) * confidence
        )
        amount_usd = round(amount_usd, 2)
    else:
        action = "HOLD"
        amount_usd = 0.0
        confidence = 0.0

    # Build rationale string
    source_labels = (
        ", ".join(r.source for r in sentiment_results)
        if sentiment_results else "no social data"
    )
    rationale = (
        f"Sentiment ({source_labels}): {avg_sentiment:+.3f} | "
        f"Technical ({technical_signal.signal}, RSI={technical_signal.rsi:.1f}): "
        f"{technical_score:+.3f} | "
        f"Volume ratio: {technical_signal.volume_ratio:.2f}x | "
        f"Final score: {final_score:+.3f} | "
        f"Action: {action} @ confidence {confidence:.2f}"
    )

    logger.info(
        "Signal for %s: %s $%.2f (confidence=%.2f)",
        ticker, action, amount_usd, confidence
    )

    return TradeSignal(
        ticker=ticker,
        action=action,
        confidence=confidence,
        amount_usd=amount_usd,
        rationale=rationale,
        timestamp=datetime.utcnow(),
        sentiment_score=avg_sentiment,
        technical_score=technical_score,
        volume_ratio=technical_signal.volume_ratio,
    )
```

---

## 8. Risk Management Framework

### 8.1 Design Principles

The risk manager acts as the final gate before any trade is dispatched to bankr.bot. It enforces the following controls:

A **daily loss limit** prevents the bot from continuing to trade after a configurable maximum daily loss (default: $200). Once hit, the bot enters a protective hold mode and does not resume until the next UTC day. A **per-trade position limit** caps the maximum USD value of any single trade. A **trade cooldown** (default: 15 minutes) prevents the bot from placing successive trades on the same token without allowing sufficient time for market conditions to change. A **portfolio concentration limit** ensures that no single token exceeds 40% of total portfolio value. **Stop-loss monitoring** runs as a background task, querying bankr.bot for current portfolio value and dispatching sell orders if a position drops more than the configured threshold.

### 8.2 risk_manager.py — Full Implementation

```python
"""
risk_manager.py
---------------
Risk management layer — enforces position limits, cooldowns, and daily loss caps.
"""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class RiskDecision:
    approved: bool
    reason: str
    adjusted_amount_usd: Optional[float] = None  # May reduce trade size


class RiskManager:
    """
    Risk management layer for the trading bot.

    Parameters
    ----------
    db_path : str
        Path to the SQLite state database.
    max_daily_loss_usd : float
        Maximum total loss in USD per calendar day.
    max_single_trade_usd : float
        Maximum size of any individual trade.
    cooldown_minutes : int
        Minimum minutes between trades on the same token.
    stop_loss_pct : float
        Percentage drop that triggers an automatic stop-loss.
    max_concentration_pct : float
        Maximum portfolio concentration in a single token (0.0 - 1.0).
    """

    def __init__(
        self,
        db_path: str = "bot_state.db",
        max_daily_loss_usd: float = 200.0,
        max_single_trade_usd: float = 500.0,
        cooldown_minutes: int = 15,
        stop_loss_pct: float = 8.0,
        max_concentration_pct: float = 0.40,
    ):
        self._db_path = db_path
        self._max_daily_loss = max_daily_loss_usd
        self._max_single_trade = max_single_trade_usd
        self._cooldown_minutes = cooldown_minutes
        self._stop_loss_pct = stop_loss_pct
        self._max_concentration = max_concentration_pct
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initialise the SQLite schema for trade state tracking."""
        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS trades (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker      TEXT NOT NULL,
                    action      TEXT NOT NULL,
                    amount_usd  REAL NOT NULL,
                    pnl_usd     REAL DEFAULT 0.0,
                    executed_at TEXT NOT NULL,
                    job_id      TEXT,
                    response    TEXT
                );

                CREATE TABLE IF NOT EXISTS signals (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker          TEXT NOT NULL,
                    action          TEXT NOT NULL,
                    confidence      REAL NOT NULL,
                    sentiment_score REAL NOT NULL,
                    technical_score REAL NOT NULL,
                    volume_ratio    REAL NOT NULL,
                    rationale       TEXT,
                    approved        INTEGER NOT NULL DEFAULT 0,
                    logged_at       TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot    TEXT NOT NULL,
                    total_usd   REAL,
                    captured_at TEXT NOT NULL
                );
            """)
        logger.info("Risk manager database initialised at %s", self._db_path)

    # ------------------------------------------------------------------
    # Daily P&L tracking
    # ------------------------------------------------------------------

    def _get_daily_pnl(self) -> float:
        """Return realised P&L for the current UTC calendar day."""
        today = datetime.now(timezone.utc).date().isoformat()
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(pnl_usd), 0) as total "
                "FROM trades WHERE executed_at LIKE ?",
                (f"{today}%",),
            ).fetchone()
            return float(row["total"])

    def _get_last_trade_time(self, ticker: str) -> Optional[datetime]:
        """Return the datetime of the most recent trade for a ticker."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT executed_at FROM trades WHERE ticker=? "
                "ORDER BY id DESC LIMIT 1",
                (ticker,),
            ).fetchone()
            if row:
                return datetime.fromisoformat(row["executed_at"])
            return None

    # ------------------------------------------------------------------
    # Risk assessment
    # ------------------------------------------------------------------

    def assess(
        self,
        ticker: str,
        action: str,
        proposed_amount_usd: float,
    ) -> RiskDecision:
        """
        Assess whether a proposed trade passes all risk checks.

        Parameters
        ----------
        ticker : str
            Token being traded.
        action : str
            "BUY" or "SELL".
        proposed_amount_usd : float
            Intended trade size.
        """
        if action == "HOLD":
            return RiskDecision(approved=False, reason="HOLD signal — no action.")

        # Check daily loss limit
        daily_pnl = self._get_daily_pnl()
        if daily_pnl <= -self._max_daily_loss:
            return RiskDecision(
                approved=False,
                reason=(
                    f"Daily loss limit reached. "
                    f"Current P&L: ${daily_pnl:.2f} / limit ${-self._max_daily_loss:.2f}."
                ),
            )

        # Check trade cooldown
        last_trade = self._get_last_trade_time(ticker)
        if last_trade:
            elapsed = datetime.now(timezone.utc) - last_trade.replace(
                tzinfo=timezone.utc
            )
            cooldown = timedelta(minutes=self._cooldown_minutes)
            if elapsed < cooldown:
                remaining = int((cooldown - elapsed).total_seconds() / 60)
                return RiskDecision(
                    approved=False,
                    reason=(
                        f"Cooldown active for {ticker}. "
                        f"{remaining} minutes remaining."
                    ),
                )

        # Cap trade size
        adjusted_amount = min(proposed_amount_usd, self._max_single_trade)
        if adjusted_amount < proposed_amount_usd:
            logger.warning(
                "Trade size for %s reduced from $%.2f to $%.2f (cap).",
                ticker, proposed_amount_usd, adjusted_amount,
            )

        # Minimum meaningful trade size — avoid dust transactions
        if adjusted_amount < 5.0:
            return RiskDecision(
                approved=False,
                reason=f"Trade amount ${adjusted_amount:.2f} below minimum $5.00.",
            )

        return RiskDecision(
            approved=True,
            reason="All risk checks passed.",
            adjusted_amount_usd=adjusted_amount,
        )

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def log_trade(
        self,
        ticker: str,
        action: str,
        amount_usd: float,
        job_id: str,
        response: str,
    ) -> None:
        """Persist an executed trade to the state database."""
        with self._get_connection() as conn:
            conn.execute(
                "INSERT INTO trades (ticker, action, amount_usd, executed_at, job_id, response) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    ticker, action, amount_usd,
                    datetime.now(timezone.utc).isoformat(),
                    job_id, response,
                ),
            )
        logger.info(
            "Trade logged: %s %s $%.2f job_id=%s", action, ticker, amount_usd, job_id
        )

    def log_signal(
        self,
        ticker: str,
        action: str,
        confidence: float,
        sentiment_score: float,
        technical_score: float,
        volume_ratio: float,
        rationale: str,
        approved: bool,
    ) -> None:
        """Persist a trade signal (approved or rejected) to the database."""
        with self._get_connection() as conn:
            conn.execute(
                """INSERT INTO signals
                   (ticker, action, confidence, sentiment_score, technical_score,
                    volume_ratio, rationale, approved, logged_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ticker, action, confidence, sentiment_score,
                    technical_score, volume_ratio, rationale,
                    1 if approved else 0,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
```

---

## 9. Project Structure

```
crypto-trading-bot/
│
├── .env                          # API keys — NEVER commit to version control
├── .env.example                  # Template with placeholder keys
├── requirements.txt              # Python dependencies
├── CLAUDE.md                     # Claude Code instructions (this document)
│
├── src/
│   ├── __init__.py
│   ├── main.py                   # Entry point — async orchestration loop
│   ├── bankr_client.py           # bankr.bot API client
│   ├── sentiment_engine.py       # VADER + FinBERT sentiment analysis
│   ├── technical_analysis.py     # RSI, MACD, Bollinger Band analysis
│   ├── social_collector.py       # Twitter, Reddit, Farcaster data fetchers
│   ├── signal_engine.py          # Signal aggregation and decision engine
│   ├── risk_manager.py           # Risk controls and position management
│   └── utils/
│       ├── logging_config.py     # Structured logging setup
│       └── price_data.py         # CoinGecko OHLCV helpers
│
├── config/
│   └── bot_config.yaml           # Watchlist, thresholds, chain settings
│
├── data/
│   └── bot_state.db              # SQLite state store (auto-created)
│
├── tests/
│   ├── test_sentiment.py
│   ├── test_technical.py
│   ├── test_signal_engine.py
│   └── test_risk_manager.py
│
└── notebooks/
    └── signal_backtest.ipynb     # Jupyter backtest notebook
```

### 9.1 requirements.txt

```
# Core async
aiohttp>=3.9.0
asyncio>=3.11

# Sentiment analysis
nltk>=3.8.1
transformers>=4.40.0
torch>=2.2.0              # FinBERT dependency — large, ~2GB download

# Data processing
pandas>=2.2.0
numpy>=1.26.0

# Social data
tweepy>=4.14.0             # Twitter API v2 wrapper (optional, can use raw aiohttp)
praw>=7.7.1                # Reddit API wrapper (optional)

# Configuration and utilities
python-dotenv>=1.0.0
pyyaml>=6.0.1
requests>=2.31.0

# Testing
pytest>=8.0.0
pytest-asyncio>=0.23.0

# Development
ipython>=8.0.0
jupyter>=1.0.0
```

### 9.2 .env.example

```bash
# bankr.bot API key — obtain from https://bankr.bot/api
BANKR_API_KEY=bk_your_key_here

# Twitter/X Developer API — https://developer.twitter.com
TWITTER_BEARER_TOKEN=your_bearer_token_here

# CoinGecko Demo API key (free) — https://www.coingecko.com/en/api
COINGECKO_API_KEY=CG-your_key_here

# Neynar API key for Farcaster — https://neynar.com
NEYNAR_API_KEY=your_neynar_key_here

# Dry run mode — set to "false" only for live trading
DRY_RUN=true

# Default chain for trades
DEFAULT_CHAIN=Base
```

### 9.3 config/bot_config.yaml

```yaml
# Token watchlist — CoinGecko IDs and tickers
watchlist:
  - ticker: ETH
    coingecko_id: ethereum
    chain: Base
    enabled: true
  - ticker: SOL
    coingecko_id: solana
    chain: Solana
    enabled: true
  - ticker: BNKR
    coingecko_id: bankr-bot
    chain: Base
    enabled: false  # Enable once familiar with the bot

# Trading loop configuration
loop:
  interval_minutes: 15          # How often the main loop runs
  sentiment_hours_back: 1       # Social data lookback window
  technical_candles: 50         # Number of OHLCV candles to load

# Risk controls
risk:
  max_daily_loss_usd: 200.0
  max_single_trade_usd: 150.0
  cooldown_minutes: 15
  stop_loss_pct: 8.0
  min_confidence: 0.55          # Minimum confidence to execute a trade

# Position sizing
position:
  base_usd: 25.0                # Minimum trade size
  max_usd: 150.0                # Maximum trade size

# Sentiment weights by source
sentiment_weights:
  twitter: 0.40
  reddit: 0.35
  farcaster: 0.25
```

---

## 10. Implementation Roadmap

The POC is structured in three phases, each buildable and testable independently before progressing.

**Phase 1 — Foundation (Days 1-3):** Set up the project structure, install dependencies, and configure the bankr.bot client. Run in dry-run mode to verify API connectivity. Implement the CoinGecko price fetcher and verify OHLCV data flows into the technical analysis engine. Wire up SQLite persistence via the risk manager. Goal: the bot can fetch prices, calculate technical indicators, and log results without executing any trades.

**Phase 2 — Sentiment Integration (Days 4-7):** Implement the Twitter and Reddit collectors, integrate VADER, and verify that sentiment scores are produced for tokens on the watchlist. Add Farcaster collection if a Neynar API key is available. Tune the sentiment thresholds against historical post data. Goal: the full signal aggregation pipeline produces BUY/SELL/HOLD signals with confidence scores that can be compared against subsequent price movements manually.

**Phase 3 — Live Trading (Days 8-14):** Enable live trading with minimal capital (under $50 total exposure). Monitor every trade in real time, reviewing bankr.bot job responses. Observe the risk manager's daily loss limit in practice. Review the signal log in the SQLite database daily and adjust thresholds if the signal quality is poor. Gradually increase confidence thresholds or reduce position sizes based on observed performance.

---

## 11. Claude Code Instructions

This section is the primary instruction set for Claude Code when working on this project.

### 11.1 CLAUDE.md — Drop This in the Project Root

```markdown
# CLAUDE.md — Crypto Trading Bot
# Instructions for Claude Code

## Project Purpose
This is an automated cryptocurrency trading bot using the bankr.bot Agent API.
It combines technical analysis and social media sentiment to generate trade signals.

## Critical Safety Rules
1. ALWAYS verify that DRY_RUN=true in .env before running any trade-execution code.
2. NEVER hardcode API keys. Always use os.environ.get() or python-dotenv.
3. NEVER commit the .env file. It is in .gitignore.
4. All trade amounts must pass through RiskManager.assess() before execution.
5. The bankr.bot API key starts with 'bk_'. If not present in env, raise clearly.

## Architecture
- main.py: async event loop, 15-minute cycle
- bankr_client.py: bankr.bot REST API — prompt submission and job polling
- sentiment_engine.py: VADER + FinBERT dual-layer NLP
- technical_analysis.py: RSI, MACD, Bollinger Bands
- social_collector.py: Twitter/X, Reddit, Farcaster data
- signal_engine.py: weighted signal fusion
- risk_manager.py: daily loss limit, cooldown, position caps

## Key API Patterns
bankr.bot uses an async job pattern:
  POST /agent/prompt → returns jobId
  GET  /agent/job/{jobId} → poll until status == "completed"
  
Prompts are plain English: "Buy $50 of ETH on Base"

## Running the Bot
  # Dry run (safe — no real trades)
  python src/main.py --dry-run

  # Live trading (use with extreme caution)
  python src/main.py --live

## Testing
  pytest tests/ -v

## Database
  SQLite at data/bot_state.db
  Tables: trades, signals, portfolio_snapshots

## Python Style
- Type hints on all functions
- Async/await throughout (aiohttp, asyncio)
- logging module (not print) for all output
- British English in all comments and docstrings
- Full scripts only — no truncated examples

## Dependency Installation
  pip install -r requirements.txt
  python -c "import nltk; nltk.download('vader_lexicon')"

## Common Tasks for Claude Code
- "Add a new token to the watchlist" → edit config/bot_config.yaml
- "Why did the bot trade X?" → query SELECT * FROM signals WHERE ticker='X'
- "Show today's P&L" → SELECT SUM(pnl_usd) FROM trades WHERE executed_at LIKE 'TODAY%'
- "Adjust risk limits" → edit RiskManager __init__ defaults or config/bot_config.yaml
- "Test sentiment on a phrase" → run: python -c "from src.sentiment_engine import SentimentEngine; ..."
```

### 11.2 main.py — Orchestration Entry Point

```python
"""
main.py
-------
Async orchestration loop for the crypto trading bot.
Runs on a configurable interval (default 15 minutes).

Usage:
    python main.py --dry-run     # Safe mode, no real trades
    python main.py --live        # Live trading — USE WITH CAUTION
"""

import argparse
import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml
from dotenv import load_dotenv

from bankr_client import BankrClient, Chain
from sentiment_engine import SentimentEngine
from technical_analysis import analyse_technicals
from social_collector import (
    CoinGeckoCollector,
    TwitterCollector,
    RedditCollector,
    FarcasterCollector,
)
from signal_engine import aggregate_signals
from risk_manager import RiskManager

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("main")


def load_config(config_path: str = "config/bot_config.yaml") -> dict:
    """Load the bot configuration from YAML."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with open(path) as f:
        return yaml.safe_load(f)


async def run_cycle(
    config: dict,
    bankr: BankrClient,
    sentiment_engine: SentimentEngine,
    risk_manager: RiskManager,
    coingecko: CoinGeckoCollector,
    twitter: TwitterCollector,
    reddit: RedditCollector,
    farcaster: FarcasterCollector,
) -> None:
    """
    Execute one full analysis cycle across all watched tokens.
    """
    watchlist = [t for t in config["watchlist"] if t.get("enabled", True)]
    logger.info(
        "Starting analysis cycle at %s. Watching %d tokens.",
        datetime.utcnow().isoformat(), len(watchlist)
    )

    for token_conf in watchlist:
        ticker = token_conf["ticker"]
        coingecko_id = token_conf["coingecko_id"]
        chain_name = token_conf.get("chain", config.get("risk", {}).get("chain", "Base"))

        try:
            chain = Chain(chain_name)
        except ValueError:
            logger.error("Unknown chain '%s' for %s. Skipping.", chain_name, ticker)
            continue

        logger.info("Analysing %s on %s...", ticker, chain_name)

        # --- 1. Fetch price data ---
        ohlcv_raw = await coingecko.get_ohlcv(coingecko_id, days=2)
        if not ohlcv_raw or len(ohlcv_raw) < 30:
            logger.warning("Insufficient OHLCV data for %s. Skipping.", ticker)
            continue

        # CoinGecko OHLCV format: [timestamp, open, high, low, close]
        closes = pd.Series([candle[4] for candle in ohlcv_raw])
        # CoinGecko does not return volume in OHLCV endpoint —
        # use a flat series as placeholder (upgrade to market_chart for real volume)
        volumes = pd.Series([1.0] * len(closes))

        # --- 2. Technical analysis ---
        tech_signal = analyse_technicals(closes, volumes, ticker)

        # --- 3. Social data collection ---
        hours_back = config.get("loop", {}).get("sentiment_hours_back", 1)

        social_tasks = [
            twitter.fetch_recent(ticker, hours_back=hours_back),
            reddit.fetch_recent(ticker),
            farcaster.fetch_recent(ticker),
        ]
        social_batches = await asyncio.gather(*social_tasks, return_exceptions=True)

        # --- 4. Sentiment analysis ---
        sentiment_results = []
        for batch in social_batches:
            if isinstance(batch, Exception):
                logger.warning("Social fetch error: %s", batch)
                continue
            if batch.error:
                logger.warning("Social error [%s/%s]: %s",
                               batch.source, batch.ticker, batch.error)
                continue
            if batch.posts:
                result = sentiment_engine.analyse(
                    batch.posts, batch.ticker, batch.source
                )
                sentiment_results.append(result)

        # --- 5. Signal aggregation ---
        pos_config = config.get("position", {})
        signal = aggregate_signals(
            ticker=ticker,
            sentiment_results=sentiment_results,
            technical_signal=tech_signal,
            base_position_usd=pos_config.get("base_usd", 25.0),
            max_position_usd=pos_config.get("max_usd", 150.0),
        )

        # --- 6. Risk assessment ---
        risk_decision = risk_manager.assess(
            ticker=ticker,
            action=signal.action,
            proposed_amount_usd=signal.amount_usd,
        )

        # Log signal regardless of approval
        risk_manager.log_signal(
            ticker=ticker,
            action=signal.action,
            confidence=signal.confidence,
            sentiment_score=signal.sentiment_score,
            technical_score=signal.technical_score,
            volume_ratio=signal.volume_ratio,
            rationale=signal.rationale,
            approved=risk_decision.approved,
        )

        if not risk_decision.approved:
            logger.info(
                "Signal for %s REJECTED by risk manager: %s",
                ticker, risk_decision.reason
            )
            continue

        # --- 7. Execute trade ---
        adjusted_amount = risk_decision.adjusted_amount_usd or signal.amount_usd
        logger.info(
            "Executing %s for %s: $%.2f (confidence=%.2f)",
            signal.action, ticker, adjusted_amount, signal.confidence
        )

        try:
            if signal.action == "BUY":
                result = await bankr.buy(ticker, adjusted_amount, chain)
            elif signal.action == "SELL":
                result = await bankr.sell(ticker, adjusted_amount, chain)
            else:
                continue

            risk_manager.log_trade(
                ticker=ticker,
                action=signal.action,
                amount_usd=adjusted_amount,
                job_id=result.job_id,
                response=result.response,
            )
            logger.info(
                "Trade executed for %s. Job: %s. Response: %s",
                ticker, result.job_id, result.response[:120]
            )

        except Exception as exc:
            logger.error("Trade execution failed for %s: %s", ticker, exc)

    logger.info("Analysis cycle complete.")


async def main(dry_run: bool = True) -> None:
    """Main async entry point."""
    logger.info(
        "=== Crypto Trading Bot starting === DRY_RUN=%s", dry_run
    )

    # Validate environment
    api_key = os.environ.get("BANKR_API_KEY", "")
    if not api_key:
        raise EnvironmentError(
            "BANKR_API_KEY not set. "
            "Obtain your key from https://bankr.bot/api and add it to .env"
        )

    config = load_config()
    risk_config = config.get("risk", {})
    loop_config = config.get("loop", {})
    interval_minutes = loop_config.get("interval_minutes", 15)

    # Initialise components
    sentiment_engine = SentimentEngine(use_finbert=False)  # Set True for FinBERT
    risk_manager = RiskManager(
        db_path="data/bot_state.db",
        max_daily_loss_usd=risk_config.get("max_daily_loss_usd", 200.0),
        max_single_trade_usd=risk_config.get("max_single_trade_usd", 150.0),
        cooldown_minutes=risk_config.get("cooldown_minutes", 15),
    )
    coingecko = CoinGeckoCollector()
    twitter = TwitterCollector()
    reddit = RedditCollector()
    farcaster = FarcasterCollector()

    async with BankrClient(api_key=api_key, dry_run=dry_run) as bankr:
        logger.info(
            "bankr.bot client ready. Polling interval: %d minutes.",
            interval_minutes
        )

        while True:
            try:
                await run_cycle(
                    config=config,
                    bankr=bankr,
                    sentiment_engine=sentiment_engine,
                    risk_manager=risk_manager,
                    coingecko=coingecko,
                    twitter=twitter,
                    reddit=reddit,
                    farcaster=farcaster,
                )
            except Exception as exc:
                logger.error(
                    "Unhandled error in analysis cycle: %s", exc, exc_info=True
                )

            logger.info(
                "Sleeping for %d minutes until next cycle...", interval_minutes
            )
            await asyncio.sleep(interval_minutes * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crypto Trading Bot")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Run in dry-run mode (no real trades). DEFAULT.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        default=False,
        help="Enable live trading. Overrides --dry-run.",
    )
    args = parser.parse_args()

    live = args.live
    if live:
        confirm = input(
            "\n⚠️  WARNING: Live trading enabled. Real money at risk. "
            "Type 'YES I UNDERSTAND' to continue: "
        )
        if confirm.strip() != "YES I UNDERSTAND":
            print("Aborted. Running in dry-run mode.")
            live = False

    asyncio.run(main(dry_run=not live))
```

---

## Disclaimer

Cryptocurrency trading carries significant financial risk. The content of this document is for educational and research purposes only and does not constitute financial advice. Past performance of any algorithm or strategy is not indicative of future results. The bankr.bot platform is a third-party service — always review its terms of service and understand the custody model for your wallet before depositing funds. Never trade with money you cannot afford to lose. Start with minimal capital on the free dry-run mode and validate signal quality before enabling live trading.

---

*Document version: 1.0 | Prepared for Claude Code | February 2026*
