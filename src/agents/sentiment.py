"""
sentiment.py
------------
SentimentAgent — NLP-based social sentiment scorer.

Uses VADER for short text, FinBERT for financial-vocabulary text,
and Claude Haiku to interpret ambiguous or sarcastic content.
Applies source-credibility weighting, detects coordinated manipulation,
and tracks sentiment momentum across cycles.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from anthropic import AsyncAnthropic

from src.agents.base import AgentResult, AgentRole, BaseAgent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class PostSentiment:
    """Sentiment scores for a single social post."""

    post_id: str
    source: str
    ticker: str
    raw_score: float          # -1.0 (bearish) … +1.0 (bullish)
    confidence: float         # 0.0 … 1.0 model confidence
    method: str               # "vader" | "finbert" | "claude"
    follower_weight: float    # credibility-adjusted multiplier
    weighted_score: float     # raw_score * follower_weight


@dataclass
class TickerSentiment:
    """Aggregated sentiment for one ticker across all sources."""

    ticker: str
    composite_score: float    # -1.0 … +1.0
    post_count: int
    source_breakdown: dict[str, float]   # source -> avg score
    momentum: float           # composite_score – previous_cycle_score
    anomaly_detected: bool    # True if coordinated pumping suspected


# ---------------------------------------------------------------------------
# Lazy model loaders
# ---------------------------------------------------------------------------

_vader_analyzer: Any = None
_finbert_pipeline: Any = None


def _get_vader() -> Any:
    global _vader_analyzer
    if _vader_analyzer is None:
        import nltk
        nltk.download("vader_lexicon", quiet=True)
        from nltk.sentiment.vader import SentimentIntensityAnalyzer
        _vader_analyzer = SentimentIntensityAnalyzer()
    return _vader_analyzer


def _get_finbert() -> Any:
    global _finbert_pipeline
    if _finbert_pipeline is None:
        try:
            from transformers import pipeline
            _finbert_pipeline = pipeline(
                "text-classification",
                model="ProsusAI/finbert",
                top_k=None,
                truncation=True,
                max_length=512,
            )
        except Exception as exc:
            logger.warning("FinBERT load failed: %s — falling back to VADER", exc)
    return _finbert_pipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FINANCIAL_KEYWORDS = frozenset({
    "bullish", "bearish", "moon", "dump", "pump", "rug", "rekt",
    "long", "short", "leverage", "liquidate", "support", "resistance",
    "breakout", "reversal", "fibonacci", "volume", "macd", "rsi",
    "listing", "delisting", "airdrop", "staking", "yield", "liquidity",
})

CREDIBILITY_TIERS = [
    (1_000_000, 1.0),
    (100_000,   0.8),
    (10_000,    0.6),
    (1_000,     0.4),
    (0,         0.2),
]


def _credibility_weight(follower_count: int) -> float:
    for threshold, weight in CREDIBILITY_TIERS:
        if follower_count >= threshold:
            return weight
    return 0.2


def _is_financial_text(text: str) -> bool:
    words = set(text.lower().split())
    return bool(words & _FINANCIAL_KEYWORDS)


def _finbert_to_score(labels: list[dict[str, Any]]) -> tuple[float, float]:
    """Convert FinBERT multi-label output to a single score and confidence."""
    label_map = {"positive": 1.0, "neutral": 0.0, "negative": -1.0}
    score = 0.0
    confidence = 0.0
    for item in labels:
        label = item.get("label", "neutral").lower()
        prob = item.get("score", 0.0)
        score += label_map.get(label, 0.0) * prob
        if prob > confidence:
            confidence = prob
    return score, confidence


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class SentimentAgent(BaseAgent):
    """
    Specialist agent for multi-model sentiment analysis.

    Pipeline per post:
    1. VADER for short (<50 word) or non-financial text
    2. FinBERT for financial-vocabulary text
    3. Claude Haiku for ambiguous / sarcastic text (confidence < 0.6)

    Source credibility weighting based on follower tiers.
    Anomaly detection flags coordinated posts (>3 identical low-follower posts).
    Momentum calculated vs previous cycle's composite scores.
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        source_weights: Optional[dict[str, float]] = None,
    ) -> None:
        super().__init__(role=AgentRole.SENTIMENT, model=model, api_key=api_key)
        self._client = AsyncAnthropic(api_key=api_key)
        self._source_weights: dict[str, float] = source_weights or {
            "twitter": 0.40,
            "reddit": 0.35,
            "farcaster": 0.25,
        }
        # Cycle history for momentum calculation
        self._previous_scores: dict[str, float] = {}

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    def system_prompt(self) -> str:
        return (
            "You are a specialist crypto sentiment analyst.\n\n"
            "Your task is to determine the market sentiment of social media posts "
            "about crypto assets. You are given posts that automated models found "
            "ambiguous or sarcastic.\n\n"
            "Guidelines:\n"
            "- Return a sentiment score from -1.0 (extremely bearish) to "
            "+1.0 (extremely bullish). 0.0 = neutral.\n"
            "- Detect sarcasm, irony, and FUD. A post saying 'great, another rug' "
            "is bearish (-0.8), not positive.\n"
            "- Distinguish genuine excitement from hype manipulation.\n"
            "- Consider context: is the price discussed positively despite recent crash?\n"
            "- Return ONLY a JSON object: {\"score\": <float>, \"reasoning\": <string>}"
        )

    async def execute(self, context: dict[str, Any]) -> AgentResult:
        """
        Run one sentiment analysis cycle.

        Parameters
        ----------
        context : dict
            Must contain ``social_posts`` (list of post dicts from ResearchAgent)
            and ``enabled_tickers``.

        Returns
        -------
        AgentResult with keys:
            ticker_sentiments  — {ticker: TickerSentiment dict}
            post_sentiments    — list of PostSentiment dicts
            anomaly_tickers    — tickers with suspected manipulation
        """
        cycle_start = time.monotonic()
        errors: list[str] = []
        tokens_used = 0

        posts: list[dict[str, Any]] = context.get("social_posts", [])
        tickers: list[str] = context.get("enabled_tickers", [])

        if not posts:
            return self._build_result(
                success=True,
                data={
                    "ticker_sentiments": {},
                    "post_sentiments": [],
                    "anomaly_tickers": [],
                },
                duration_ms=(time.monotonic() - cycle_start) * 1000,
            )

        # Score each post
        post_sentiments: list[PostSentiment] = []
        ambiguous_posts: list[dict[str, Any]] = []

        for post in posts:
            sentiment = self._score_post_local(post)
            if sentiment.confidence < 0.6:
                ambiguous_posts.append(post)
            else:
                post_sentiments.append(sentiment)

        # Batch-process ambiguous posts through Claude
        if ambiguous_posts:
            claude_results, claude_tokens, claude_err = (
                await self._score_ambiguous_with_claude(ambiguous_posts)
            )
            tokens_used += claude_tokens
            post_sentiments.extend(claude_results)
            if claude_err:
                errors.append(claude_err)

        # Aggregate per ticker
        ticker_sentiments: dict[str, TickerSentiment] = {}
        anomaly_tickers: list[str] = []

        for ticker in tickers:
            ticker_posts = [
                ps for ps in post_sentiments
                if ps.ticker == ticker
            ]
            if not ticker_posts:
                continue

            ts, anomaly = self._aggregate_ticker(ticker, ticker_posts)
            ticker_sentiments[ticker] = ts
            if anomaly:
                anomaly_tickers.append(ticker)

        # Update momentum history
        self._previous_scores = {
            t: ts.composite_score for t, ts in ticker_sentiments.items()
        }

        duration_ms = (time.monotonic() - cycle_start) * 1000
        self._logger.info(
            "Sentiment cycle: %d posts scored, %d tickers, %d anomalies, %.0f ms",
            len(post_sentiments),
            len(ticker_sentiments),
            len(anomaly_tickers),
            duration_ms,
        )

        return self._build_result(
            success=True,
            data={
                "ticker_sentiments": {
                    t: self._ts_to_dict(ts)
                    for t, ts in ticker_sentiments.items()
                },
                "post_sentiments": [self._ps_to_dict(ps) for ps in post_sentiments],
                "anomaly_tickers": anomaly_tickers,
            },
            errors=errors,
            duration_ms=duration_ms,
            tokens_used=tokens_used,
        )

    # ------------------------------------------------------------------
    # Local model scoring
    # ------------------------------------------------------------------

    def _score_post_local(self, post: dict[str, Any]) -> PostSentiment:
        """Score a post using VADER or FinBERT based on text characteristics."""
        text: str = post.get("text", "")
        source: str = post.get("source", "unknown")
        followers: int = post.get("follower_count", 0)
        post_id: str = post.get("post_id", "")
        tickers: list[str] = post.get("mentioned_tickers", ["UNKNOWN"])
        ticker = tickers[0] if tickers else "UNKNOWN"

        word_count = len(text.split())
        use_finbert = word_count >= 20 and _is_financial_text(text)
        raw_score = 0.0
        confidence = 0.5
        method = "vader"

        if use_finbert:
            finbert = _get_finbert()
            if finbert is not None:
                try:
                    result = finbert(text[:512])
                    # pipeline with top_k=None returns list[list[dict]]
                    labels = result[0] if isinstance(result[0], list) else result
                    raw_score, confidence = _finbert_to_score(labels)
                    method = "finbert"
                except Exception as exc:
                    self._logger.debug("FinBERT inference error: %s", exc)

        if method == "vader":
            vader = _get_vader()
            scores = vader.polarity_scores(text)
            raw_score = scores["compound"]
            confidence = max(abs(raw_score), 0.3)

        weight = _credibility_weight(followers)
        return PostSentiment(
            post_id=post_id,
            source=source,
            ticker=ticker,
            raw_score=raw_score,
            confidence=confidence,
            method=method,
            follower_weight=weight,
            weighted_score=raw_score * weight,
        )

    # ------------------------------------------------------------------
    # Claude scoring for ambiguous posts
    # ------------------------------------------------------------------

    async def _score_ambiguous_with_claude(
        self, posts: list[dict[str, Any]]
    ) -> tuple[list[PostSentiment], int, Optional[str]]:
        """Use Claude Haiku to score ambiguous / sarcastic posts."""
        import json

        results: list[PostSentiment] = []
        total_tokens = 0

        # Process in small batches of 5 to limit prompt size
        for i in range(0, min(len(posts), 15), 5):
            batch = posts[i : i + 5]
            summaries = [
                {"id": p.get("post_id", ""), "text": p.get("text", "")[:300]}
                for p in batch
            ]

            prompt = (
                "These social posts had ambiguous or sarcastic sentiment. "
                "Score each from -1.0 (bearish) to +1.0 (bullish).\n\n"
                f"Posts:\n{json.dumps(summaries, indent=2)}\n\n"
                "Return ONLY a JSON array of objects: "
                '[{"id": "...", "score": 0.0, "reasoning": "..."}, ...]'
            )

            try:
                response = await self._client.messages.create(
                    model=self._model,
                    max_tokens=512,
                    system=self.system_prompt(),
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = response.content[0].text.strip()
                total_tokens += response.usage.input_tokens + response.usage.output_tokens

                import re
                match = re.search(r"\[.*\]", raw, re.DOTALL)
                if not match:
                    continue
                scored: list[dict[str, Any]] = json.loads(match.group())
                score_by_id = {item["id"]: item.get("score", 0.0) for item in scored}

                for post in batch:
                    post_id = post.get("post_id", "")
                    tickers: list[str] = post.get("mentioned_tickers", ["UNKNOWN"])
                    ticker = tickers[0] if tickers else "UNKNOWN"
                    raw_score = score_by_id.get(post_id, 0.0)
                    weight = _credibility_weight(post.get("follower_count", 0))
                    results.append(
                        PostSentiment(
                            post_id=post_id,
                            source=post.get("source", "unknown"),
                            ticker=ticker,
                            raw_score=raw_score,
                            confidence=0.75,
                            method="claude",
                            follower_weight=weight,
                            weighted_score=raw_score * weight,
                        )
                    )

            except Exception as exc:
                self._logger.warning("Claude sentiment batch error: %s", exc)

        return results, total_tokens, None

    # ------------------------------------------------------------------
    # Aggregation and anomaly detection
    # ------------------------------------------------------------------

    def _aggregate_ticker(
        self, ticker: str, post_sentiments: list[PostSentiment]
    ) -> tuple[TickerSentiment, bool]:
        """Aggregate post-level sentiments into a ticker-level summary."""
        source_scores: dict[str, list[float]] = {}
        for ps in post_sentiments:
            source_scores.setdefault(ps.source, []).append(ps.weighted_score)

        source_averages: dict[str, float] = {}
        composite = 0.0
        total_weight = 0.0

        for source, scores in source_scores.items():
            avg = sum(scores) / len(scores)
            source_averages[source] = avg
            src_weight = self._source_weights.get(source, 0.25)
            composite += avg * src_weight
            total_weight += src_weight

        composite = composite / total_weight if total_weight > 0 else 0.0

        prev = self._previous_scores.get(ticker, composite)
        momentum = composite - prev

        # Anomaly: >3 posts from accounts with <500 followers with near-identical scores
        low_cred = [ps for ps in post_sentiments if ps.follower_weight <= 0.2]
        anomaly_detected = False
        if len(low_cred) >= 3:
            scores = [ps.raw_score for ps in low_cred]
            score_range = max(scores) - min(scores)
            if score_range < 0.15:  # Suspiciously identical sentiment
                anomaly_detected = True
                self._logger.warning(
                    "Coordinated manipulation suspected for %s: "
                    "%d low-cred posts with score range %.3f",
                    ticker, len(low_cred), score_range,
                )

        return (
            TickerSentiment(
                ticker=ticker,
                composite_score=round(composite, 4),
                post_count=len(post_sentiments),
                source_breakdown={k: round(v, 4) for k, v in source_averages.items()},
                momentum=round(momentum, 4),
                anomaly_detected=anomaly_detected,
            ),
            anomaly_detected,
        )

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ps_to_dict(ps: PostSentiment) -> dict[str, Any]:
        return {
            "post_id": ps.post_id,
            "source": ps.source,
            "ticker": ps.ticker,
            "raw_score": ps.raw_score,
            "confidence": ps.confidence,
            "method": ps.method,
            "follower_weight": ps.follower_weight,
            "weighted_score": ps.weighted_score,
        }

    @staticmethod
    def _ts_to_dict(ts: TickerSentiment) -> dict[str, Any]:
        return {
            "ticker": ts.ticker,
            "composite_score": ts.composite_score,
            "post_count": ts.post_count,
            "source_breakdown": ts.source_breakdown,
            "momentum": ts.momentum,
            "anomaly_detected": ts.anomaly_detected,
        }
