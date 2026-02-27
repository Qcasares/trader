"""
research.py
-----------
ResearchAgent — fast market scanner.

Collects trending tokens from CoinGecko and social posts from
Twitter/Reddit/Farcaster, manages per-source rate-limit budgets,
uses Claude Haiku to assess news significance and filter noise,
then writes raw enriched data for downstream agents.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import aiohttp
from anthropic import AsyncAnthropic

from src.agents.base import AgentResult, AgentRole, BaseAgent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class TrendingToken:
    """A token surfaced by CoinGecko trending endpoint."""

    coingecko_id: str
    name: str
    symbol: str
    market_cap_rank: Optional[int]
    price_change_24h: Optional[float]
    volume_24h: Optional[float]


@dataclass
class SocialPost:
    """A social-media post from any supported source."""

    source: str  # "twitter" | "reddit" | "farcaster"
    post_id: str
    text: str
    author: str
    follower_count: int
    timestamp: float  # Unix epoch seconds
    url: str
    mentioned_tickers: list[str] = field(default_factory=list)


@dataclass
class RateLimitBudget:
    """Tracks remaining calls for a single API source."""

    source: str
    max_calls_per_cycle: int
    calls_used: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.max_calls_per_cycle - self.calls_used)

    def consume(self, n: int = 1) -> bool:
        """Consume n calls. Returns False if budget exhausted."""
        if self.remaining < n:
            return False
        self.calls_used += n
        return True

    def reset(self) -> None:
        self.calls_used = 0


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

_COINGECKO_TRENDING = "https://api.coingecko.com/api/v3/search/trending"
_COINGECKO_COIN = "https://api.coingecko.com/api/v3/coins/{coin_id}"


class ResearchAgent(BaseAgent):
    """
    Specialist agent for market research and data collection.

    Responsibilities:
    - Fetch trending tokens from CoinGecko
    - Collect social posts mentioning watchlist tokens
    - Manage per-source rate-limit budgets
    - Use Claude Haiku to score news significance and filter noise
    - Produce a clean research snapshot for downstream agents
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        watchlist: list[dict[str, Any]],
        coingecko_api_key: Optional[str] = None,
        twitter_bearer_token: Optional[str] = None,
        reddit_client_id: Optional[str] = None,
        reddit_client_secret: Optional[str] = None,
    ) -> None:
        super().__init__(role=AgentRole.RESEARCH, model=model, api_key=api_key)
        self._client = AsyncAnthropic(api_key=api_key)
        self._watchlist = watchlist
        self._cg_key = coingecko_api_key
        self._twitter_token = twitter_bearer_token
        self._reddit_id = reddit_client_id
        self._reddit_secret = reddit_client_secret

        # Per-source rate-limit budgets (calls per 15-minute cycle)
        self._budgets: dict[str, RateLimitBudget] = {
            "coingecko": RateLimitBudget("coingecko", max_calls_per_cycle=10),
            "twitter": RateLimitBudget("twitter", max_calls_per_cycle=5),
            "reddit": RateLimitBudget("reddit", max_calls_per_cycle=8),
            "farcaster": RateLimitBudget("farcaster", max_calls_per_cycle=6),
        }

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    def system_prompt(self) -> str:
        return (
            "You are a specialist crypto market research analyst.\n\n"
            "Your role is to evaluate incoming market data — trending tokens, "
            "news headlines, and social posts — for their potential market impact.\n\n"
            "Guidelines:\n"
            "- Focus on on-chain catalysts: protocol upgrades, listings, partnerships, "
            "exploit disclosures, regulatory actions.\n"
            "- Distinguish primary sources (official announcements) from rumours.\n"
            "- Score significance 0.0–1.0: 0.0 = noise/spam, 0.5 = noteworthy, "
            "1.0 = high-impact catalyst.\n"
            "- Flag potential manipulation: coordinated pumping language, "
            "low-follower accounts spreading identical text.\n"
            "- Be concise and structured. Return only valid JSON when asked."
        )

    async def execute(self, context: dict[str, Any]) -> AgentResult:
        """
        Run one research cycle.

        Parameters
        ----------
        context : dict
            Orchestrator context. May contain ``hours_back`` and ``watchlist``.

        Returns
        -------
        AgentResult with keys:
            trending_tokens   — list of TrendingToken dicts
            social_posts      — list of SocialPost dicts
            significance_map  — {post_id: score} from Claude
            budget_status     — remaining calls per source
        """
        cycle_start = time.monotonic()
        errors: list[str] = []
        tokens_used = 0

        # Reset per-cycle budgets
        for budget in self._budgets.values():
            budget.reset()

        watchlist = context.get("watchlist", self._watchlist)
        enabled_tokens = [t for t in watchlist if t.get("enabled", True)]
        tickers = [t["ticker"] for t in enabled_tokens]

        # ----- Collect data -------------------------------------------------
        trending: list[TrendingToken] = []
        posts: list[SocialPost] = []

        async with aiohttp.ClientSession() as session:
            cg_result, cg_err = await self._fetch_trending_coingecko(session)
            trending.extend(cg_result)
            if cg_err:
                errors.append(cg_err)

            twitter_result, tw_err = await self._fetch_twitter_posts(
                session, tickers
            )
            posts.extend(twitter_result)
            if tw_err:
                errors.append(tw_err)

            reddit_result, rd_err = await self._fetch_reddit_posts(
                session, tickers
            )
            posts.extend(reddit_result)
            if rd_err:
                errors.append(rd_err)

            fc_result, fc_err = await self._fetch_farcaster_posts(
                session, tickers
            )
            posts.extend(fc_result)
            if fc_err:
                errors.append(fc_err)

        # ----- Claude significance scoring ----------------------------------
        significance_map: dict[str, float] = {}
        claude_tokens = 0

        if posts:
            significance_map, claude_tokens, score_err = (
                await self._score_significance(posts)
            )
            tokens_used += claude_tokens
            if score_err:
                errors.append(score_err)

        duration_ms = (time.monotonic() - cycle_start) * 1000

        self._logger.info(
            "Research cycle complete: %d trending tokens, %d posts, "
            "%d scored, %.0f ms",
            len(trending),
            len(posts),
            len(significance_map),
            duration_ms,
        )

        return self._build_result(
            success=True,
            data={
                "trending_tokens": [self._token_to_dict(t) for t in trending],
                "social_posts": [self._post_to_dict(p) for p in posts],
                "significance_map": significance_map,
                "budget_status": {
                    src: b.remaining for src, b in self._budgets.items()
                },
                "enabled_tickers": tickers,
            },
            errors=errors,
            duration_ms=duration_ms,
            tokens_used=tokens_used,
        )

    # ------------------------------------------------------------------
    # Data fetchers
    # ------------------------------------------------------------------

    async def _fetch_trending_coingecko(
        self, session: aiohttp.ClientSession
    ) -> tuple[list[TrendingToken], Optional[str]]:
        """Fetch top trending tokens from CoinGecko."""
        if not self._budgets["coingecko"].consume(1):
            return [], "CoinGecko budget exhausted"

        headers: dict[str, str] = {}
        if self._cg_key:
            headers["x-cg-demo-api-key"] = self._cg_key

        try:
            async with session.get(
                _COINGECKO_TRENDING, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return [], f"CoinGecko HTTP {resp.status}"
                data = await resp.json()

            tokens: list[TrendingToken] = []
            for item in data.get("coins", [])[:10]:
                coin = item.get("item", {})
                tokens.append(
                    TrendingToken(
                        coingecko_id=coin.get("id", ""),
                        name=coin.get("name", ""),
                        symbol=coin.get("symbol", "").upper(),
                        market_cap_rank=coin.get("market_cap_rank"),
                        price_change_24h=coin.get("data", {}).get(
                            "price_change_percentage_24h", {}).get("usd"),
                        volume_24h=None,
                    )
                )
            return tokens, None

        except Exception as exc:
            return [], f"CoinGecko error: {exc}"

    async def _fetch_twitter_posts(
        self, session: aiohttp.ClientSession, tickers: list[str]
    ) -> tuple[list[SocialPost], Optional[str]]:
        """Fetch recent tweets mentioning watchlist tickers via Twitter v2 API."""
        if not self._twitter_token:
            return [], None  # Not configured — silent skip
        if not self._budgets["twitter"].consume(1):
            return [], "Twitter budget exhausted"

        query = " OR ".join(f"${t}" for t in tickers[:5])
        url = "https://api.twitter.com/2/tweets/search/recent"
        params = {
            "query": f"({query}) -is:retweet lang:en",
            "max_results": 20,
            "tweet.fields": "created_at,author_id,text,public_metrics",
            "expansions": "author_id",
            "user.fields": "public_metrics",
        }
        headers = {"Authorization": f"Bearer {self._twitter_token}"}

        try:
            async with session.get(
                url,
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    return [], f"Twitter HTTP {resp.status}"
                data = await resp.json()

            users = {
                u["id"]: u
                for u in data.get("includes", {}).get("users", [])
            }
            posts: list[SocialPost] = []
            import re

            for tweet in data.get("data", []):
                author_id = tweet.get("author_id", "")
                user = users.get(author_id, {})
                followers = (
                    user.get("public_metrics", {}).get("followers_count", 0)
                )
                text = tweet.get("text", "")
                found = [
                    t for t in tickers if re.search(rf"\${t}\b", text, re.IGNORECASE)
                ]
                posts.append(
                    SocialPost(
                        source="twitter",
                        post_id=tweet.get("id", ""),
                        text=text,
                        author=user.get("username", author_id),
                        follower_count=followers,
                        timestamp=time.time(),
                        url=f"https://twitter.com/i/web/status/{tweet.get('id', '')}",
                        mentioned_tickers=found,
                    )
                )
            return posts, None

        except Exception as exc:
            return [], f"Twitter error: {exc}"

    async def _fetch_reddit_posts(
        self, session: aiohttp.ClientSession, tickers: list[str]
    ) -> tuple[list[SocialPost], Optional[str]]:
        """Fetch hot posts from r/CryptoCurrency and r/ethfinance via Reddit API."""
        if not (self._reddit_id and self._reddit_secret):
            return [], None  # Not configured
        if not self._budgets["reddit"].consume(1):
            return [], "Reddit budget exhausted"

        subreddits = ["CryptoCurrency", "ethfinance", "solana"]
        posts: list[SocialPost] = []
        import re

        try:
            # Obtain OAuth token
            token_resp = await session.post(
                "https://www.reddit.com/api/v1/access_token",
                data={"grant_type": "client_credentials"},
                auth=aiohttp.BasicAuth(self._reddit_id, self._reddit_secret),
                headers={"User-Agent": "crypto-trader-bot/0.1"},
                timeout=aiohttp.ClientTimeout(total=10),
            )
            token_data = await token_resp.json()
            token = token_data.get("access_token", "")
            if not token:
                return [], "Reddit OAuth failed"

            headers = {
                "Authorization": f"Bearer {token}",
                "User-Agent": "crypto-trader-bot/0.1",
            }

            for sub in subreddits:
                if not self._budgets["reddit"].consume(1):
                    break
                url = f"https://oauth.reddit.com/r/{sub}/hot.json?limit=10"
                async with session.get(
                    url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()

                for child in data.get("data", {}).get("children", []):
                    d = child.get("data", {})
                    title = d.get("title", "")
                    body = d.get("selftext", "")
                    combined = f"{title} {body}"
                    found = [
                        t for t in tickers
                        if re.search(rf"\b{t}\b", combined, re.IGNORECASE)
                    ]
                    if not found:
                        continue
                    posts.append(
                        SocialPost(
                            source="reddit",
                            post_id=d.get("id", ""),
                            text=combined[:500],
                            author=d.get("author", "unknown"),
                            follower_count=d.get("score", 0),
                            timestamp=d.get("created_utc", time.time()),
                            url=f"https://reddit.com{d.get('permalink', '')}",
                            mentioned_tickers=found,
                        )
                    )

            return posts, None

        except Exception as exc:
            return [], f"Reddit error: {exc}"

    async def _fetch_farcaster_posts(
        self, session: aiohttp.ClientSession, tickers: list[str]
    ) -> tuple[list[SocialPost], Optional[str]]:
        """Fetch recent casts from Farcaster's Neynar API."""
        if not self._budgets["farcaster"].consume(1):
            return [], "Farcaster budget exhausted"

        import re

        posts: list[SocialPost] = []
        try:
            # Farcaster public search via Neynar (no key for public casts)
            for ticker in tickers[:3]:
                if not self._budgets["farcaster"].consume(1):
                    break
                url = "https://api.neynar.com/v2/farcaster/cast/search"
                params = {"q": f"${ticker}", "limit": 10}
                async with session.get(
                    url, params=params, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()

                for cast in data.get("result", {}).get("casts", []):
                    text = cast.get("text", "")
                    author = cast.get("author", {})
                    found = [
                        t for t in tickers
                        if re.search(rf"\${t}\b", text, re.IGNORECASE)
                    ]
                    posts.append(
                        SocialPost(
                            source="farcaster",
                            post_id=cast.get("hash", ""),
                            text=text,
                            author=author.get("username", "unknown"),
                            follower_count=author.get("follower_count", 0),
                            timestamp=time.time(),
                            url=f"https://warpcast.com/{author.get('username', '')}",
                            mentioned_tickers=found or [ticker],
                        )
                    )

            return posts, None

        except Exception as exc:
            return [], f"Farcaster error: {exc}"

    # ------------------------------------------------------------------
    # Claude scoring
    # ------------------------------------------------------------------

    async def _score_significance(
        self, posts: list[SocialPost]
    ) -> tuple[dict[str, float], int, Optional[str]]:
        """Use Claude Haiku to score the significance of each post 0.0–1.0."""
        import json

        # Batch posts to limit token usage
        batch = posts[:20]
        post_summaries = [
            {
                "id": p.post_id,
                "source": p.source,
                "text": p.text[:200],
                "followers": p.follower_count,
            }
            for p in batch
        ]

        prompt = (
            "Score each post's market significance for crypto traders on a scale "
            "0.0–1.0 (0=noise/spam, 0.5=noteworthy, 1.0=high-impact catalyst).\n\n"
            f"Posts:\n{json.dumps(post_summaries, indent=2)}\n\n"
            "Return ONLY a JSON object mapping post id to score, e.g. "
            '{"abc123": 0.7, "def456": 0.1}'
        )

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=512,
                system=self.system_prompt(),
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            # Extract JSON from the response
            import re
            match = re.search(r"\{[^{}]+\}", raw, re.DOTALL)
            if not match:
                return {}, response.usage.input_tokens + response.usage.output_tokens, \
                    "Claude returned non-JSON significance scores"

            scores: dict[str, float] = json.loads(match.group())
            tokens = response.usage.input_tokens + response.usage.output_tokens
            return scores, tokens, None

        except Exception as exc:
            return {}, 0, f"Claude significance scoring error: {exc}"

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _token_to_dict(t: TrendingToken) -> dict[str, Any]:
        return {
            "coingecko_id": t.coingecko_id,
            "name": t.name,
            "symbol": t.symbol,
            "market_cap_rank": t.market_cap_rank,
            "price_change_24h": t.price_change_24h,
            "volume_24h": t.volume_24h,
        }

    @staticmethod
    def _post_to_dict(p: SocialPost) -> dict[str, Any]:
        return {
            "source": p.source,
            "post_id": p.post_id,
            "text": p.text,
            "author": p.author,
            "follower_count": p.follower_count,
            "timestamp": p.timestamp,
            "url": p.url,
            "mentioned_tickers": p.mentioned_tickers,
        }
