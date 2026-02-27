"""
portfolio.py
------------
PortfolioAgent — tracks positions, calculates P&L, detects drawdowns,
and uses Claude Sonnet for qualitative portfolio analysis.

Runs on a 30-minute cadence. Reads trade history and position data from
the shared PostgreSQL database, computes metrics, and persists a snapshot.
"""

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional

from anthropic import AsyncAnthropic

from src.agents.base import AgentResult, AgentRole, BaseAgent
from src.db.connection import DatabasePool
from src.db.repositories import (
    get_daily_pnl,
    get_latest_portfolio_snapshot,
    get_portfolio_positions,
    get_trade_history,
    insert_portfolio_snapshot,
)

logger = logging.getLogger(__name__)


class PortfolioAgent(BaseAgent):
    """
    Specialist agent for portfolio tracking and performance analysis.

    Responsibilities:
    - Position tracking with current market prices
    - Daily and cumulative P&L calculation
    - Max drawdown detection (peak-to-trough)
    - Claude Sonnet qualitative analysis with graceful fallback
    - Portfolio snapshot persistence to database

    Uses Claude Sonnet for analysis but falls back to a rule-based summary
    if the API call fails — the agent never crashes on Claude errors.
    """

    def __init__(self, api_key: str, db_pool: DatabasePool) -> None:
        super().__init__(
            role=AgentRole.PORTFOLIO,
            model="claude-sonnet-4-6",
            api_key=api_key,
        )
        self._client = AsyncAnthropic(api_key=api_key)
        self._db = db_pool

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    def system_prompt(self) -> str:
        return (
            "You are a portfolio analyst for an automated crypto trading bot.\n\n"
            "You receive portfolio metrics including positions, P&L, drawdown, "
            "and recent trade history. Your task is to provide a concise "
            "qualitative assessment of the portfolio's health and risk.\n\n"
            "Analyse:\n"
            "- Position concentration: is the portfolio over-exposed to any asset?\n"
            "- P&L trends: is performance improving or deteriorating?\n"
            "- Drawdown severity: how concerning is the current drawdown level?\n"
            "- Trade quality: are recent trades profitable on average?\n"
            "- Risk outlook: should the bot be more aggressive or conservative?\n\n"
            "Return ONLY a JSON object:\n"
            '{"analysis": "2-3 sentence summary", '
            '"risk_level": "low|medium|high", '
            '"recommendations": ["action1", "action2"]}'
        )

    async def execute(self, context: dict[str, Any]) -> AgentResult:
        """
        Run one portfolio analysis cycle.

        Parameters
        ----------
        context : dict
            Expected keys:
                current_prices     — dict {ticker: float} with latest prices
                portfolio_total_usd — float, total portfolio value (optional)

        Returns
        -------
        AgentResult with keys:
            snapshot          — dict of the saved portfolio snapshot
            daily_pnl_usd     — float, today's P&L
            cumulative_pnl_usd — float, running total P&L
            max_drawdown_pct  — float, worst peak-to-trough decline
            analysis          — str, Claude or rule-based summary
            trade_count       — int, trades in last 24h
        """
        cycle_start = time.monotonic()
        errors: list[str] = []
        tokens_used = 0

        current_prices: dict[str, float] = context.get("current_prices", {})
        portfolio_total_override: Optional[float] = context.get(
            "portfolio_total_usd"
        )

        # --- Step 1: Query database for current state ---
        daily_pnl = await self._safe_get_daily_pnl()
        positions = await self._safe_get_positions()
        previous_snapshot = await self._safe_get_latest_snapshot()
        trade_history = await self._safe_get_trade_history()

        # --- Step 2: Update positions with current prices ---
        positions = self._update_positions_with_prices(positions, current_prices)

        # --- Step 3: Compute portfolio metrics ---
        total_value = portfolio_total_override or self._compute_total_value(
            positions
        )
        cumulative_pnl = self._compute_cumulative_pnl(
            previous_snapshot, daily_pnl
        )
        peak_value = self._compute_peak_value(previous_snapshot, total_value)
        max_drawdown = self._compute_drawdown(
            total_value, peak_value, previous_snapshot
        )

        metrics = {
            "total_value_usd": round(total_value, 2),
            "positions": positions,
            "daily_pnl_usd": round(daily_pnl, 2),
            "cumulative_pnl_usd": round(cumulative_pnl, 2),
            "max_drawdown_pct": round(max_drawdown, 4),
            "trade_count": len(trade_history),
        }

        # --- Step 4: Claude analysis with fallback ---
        analysis, claude_tokens, claude_err = await self._analyse_with_claude(
            metrics, trade_history
        )
        tokens_used += claude_tokens
        if claude_err:
            errors.append(claude_err)
            analysis = self._build_rule_based_summary(metrics)

        # --- Step 5: Save snapshot to database ---
        snapshot_data = {
            "total_value_usd": metrics["total_value_usd"],
            "positions": positions,
            "daily_pnl_usd": metrics["daily_pnl_usd"],
            "cumulative_pnl_usd": metrics["cumulative_pnl_usd"],
            "max_drawdown_pct": metrics["max_drawdown_pct"],
        }
        snapshot_id = await self._safe_insert_snapshot(snapshot_data)
        if snapshot_id is None:
            errors.append("Failed to persist portfolio snapshot")

        duration_ms = (time.monotonic() - cycle_start) * 1000
        self._logger.info(
            "Portfolio cycle: value=$%.2f, daily_pnl=$%.2f, "
            "cumulative=$%.2f, drawdown=%.2f%%, %d trades, %.0f ms",
            total_value,
            daily_pnl,
            cumulative_pnl,
            max_drawdown,
            len(trade_history),
            duration_ms,
        )

        return self._build_result(
            success=True,
            data={
                "snapshot": snapshot_data,
                "daily_pnl_usd": metrics["daily_pnl_usd"],
                "cumulative_pnl_usd": metrics["cumulative_pnl_usd"],
                "max_drawdown_pct": metrics["max_drawdown_pct"],
                "analysis": analysis,
                "trade_count": len(trade_history),
            },
            errors=errors,
            duration_ms=duration_ms,
            tokens_used=tokens_used,
        )

    # ------------------------------------------------------------------
    # Database helpers (safe wrappers — never crash on DB errors)
    # ------------------------------------------------------------------

    async def _safe_get_daily_pnl(self) -> float:
        try:
            return await get_daily_pnl(self._db)
        except Exception as exc:
            self._logger.warning("Failed to get daily P&L: %s", exc)
            return 0.0

    async def _safe_get_positions(self) -> dict[str, Any]:
        try:
            return await get_portfolio_positions(self._db)
        except Exception as exc:
            self._logger.warning("Failed to get positions: %s", exc)
            return {}

    async def _safe_get_latest_snapshot(self) -> Optional[dict[str, Any]]:
        try:
            return await get_latest_portfolio_snapshot(self._db)
        except Exception as exc:
            self._logger.warning("Failed to get latest snapshot: %s", exc)
            return None

    async def _safe_get_trade_history(self) -> list[dict[str, Any]]:
        try:
            return await get_trade_history(self._db, since_hours=24)
        except Exception as exc:
            self._logger.warning("Failed to get trade history: %s", exc)
            return []

    async def _safe_insert_snapshot(
        self, data: dict[str, Any]
    ) -> Optional[int]:
        try:
            return await insert_portfolio_snapshot(self._db, data)
        except Exception as exc:
            self._logger.warning("Failed to insert snapshot: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Position and metric calculations
    # ------------------------------------------------------------------

    @staticmethod
    def _update_positions_with_prices(
        positions: dict[str, Any], current_prices: dict[str, float]
    ) -> dict[str, Any]:
        """Update position values using latest market prices."""
        updated: dict[str, Any] = {}
        for ticker, pos in positions.items():
            pos = dict(pos) if not isinstance(pos, dict) else pos
            quantity = float(pos.get("quantity", 0))
            entry_price = float(pos.get("entry_price", 0))

            if ticker in current_prices:
                current_price = current_prices[ticker]
                pos["current_price"] = current_price
                pos["value_usd"] = round(quantity * current_price, 2)
            updated[ticker] = pos
        return updated

    @staticmethod
    def _compute_total_value(positions: dict[str, Any]) -> float:
        """Sum all position values to get total portfolio value."""
        total = 0.0
        for pos in positions.values():
            total += float(pos.get("value_usd", 0) if isinstance(pos, dict) else 0)
        return total

    @staticmethod
    def _compute_cumulative_pnl(
        previous_snapshot: Optional[dict[str, Any]], daily_pnl: float
    ) -> float:
        """Compute running cumulative P&L."""
        if previous_snapshot is None:
            return daily_pnl

        prev_cumulative = float(
            previous_snapshot.get("cumulative_pnl_usd", 0)
        )
        prev_daily = float(previous_snapshot.get("daily_pnl_usd", 0))

        # If this is a new day, add today's P&L to previous cumulative.
        # If same day, replace the daily component.
        prev_time = previous_snapshot.get("snapshot_time")
        now = datetime.now(timezone.utc)

        if prev_time is not None:
            if isinstance(prev_time, str):
                try:
                    prev_time = datetime.fromisoformat(
                        prev_time.replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    prev_time = None
            if isinstance(prev_time, datetime):
                if prev_time.date() == now.date():
                    # Same day: cumulative = prev_cumulative - prev_daily + daily
                    return prev_cumulative - prev_daily + daily_pnl

        # New day or no timestamp: add today's P&L on top
        return prev_cumulative + daily_pnl

    @staticmethod
    def _compute_peak_value(
        previous_snapshot: Optional[dict[str, Any]], current_value: float
    ) -> float:
        """Determine peak portfolio value for drawdown calculation."""
        if previous_snapshot is None:
            return current_value

        prev_total = float(previous_snapshot.get("total_value_usd", 0))
        prev_drawdown = float(previous_snapshot.get("max_drawdown_pct", 0))

        # Reconstruct approximate peak from previous drawdown
        if prev_drawdown > 0 and prev_total > 0:
            # peak = prev_total / (1 - drawdown/100)
            peak = prev_total / (1 - prev_drawdown / 100)
        else:
            peak = prev_total

        return max(peak, current_value)

    @staticmethod
    def _compute_drawdown(
        current_value: float,
        peak_value: float,
        previous_snapshot: Optional[dict[str, Any]],
    ) -> float:
        """
        Compute max drawdown percentage.

        max_drawdown = max(previous_max_drawdown, current_drawdown)
        current_drawdown = (peak - current) / peak * 100
        """
        previous_max = 0.0
        if previous_snapshot is not None:
            previous_max = float(
                previous_snapshot.get("max_drawdown_pct", 0)
            )

        if peak_value <= 0:
            return previous_max

        current_drawdown = max(
            0.0, (peak_value - current_value) / peak_value * 100
        )
        return max(previous_max, current_drawdown)

    # ------------------------------------------------------------------
    # Claude analysis
    # ------------------------------------------------------------------

    async def _analyse_with_claude(
        self,
        metrics: dict[str, Any],
        trade_history: list[dict[str, Any]],
    ) -> tuple[str, int, Optional[str]]:
        """
        Call Claude Sonnet for qualitative portfolio analysis.

        Returns (analysis_text, tokens_used, error_or_none).
        """
        # Summarise trade history for the prompt (avoid sending raw DB rows)
        trade_summary = []
        for t in trade_history[:20]:  # Cap at 20 most recent
            trade_summary.append({
                "ticker": t.get("ticker"),
                "action": t.get("action"),
                "amount_usd": float(t.get("amount_usd", 0)),
                "success": t.get("success"),
                "slippage_pct": t.get("slippage_pct"),
            })

        prompt = (
            "Analyse the following portfolio state and provide your "
            "assessment.\n\n"
            f"Portfolio metrics:\n{json.dumps(metrics, indent=2, default=str)}\n\n"
            f"Recent trades (last 24h):\n{json.dumps(trade_summary, indent=2)}\n\n"
            "Provide your analysis, risk level, and recommendations."
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

            # Try to extract JSON analysis
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                parsed = json.loads(match.group())
                analysis = parsed.get("analysis", raw)
                risk_level = parsed.get("risk_level", "unknown")
                recommendations = parsed.get("recommendations", [])
                return (
                    f"[{risk_level.upper()}] {analysis}"
                    + (
                        f" Recommendations: {', '.join(recommendations)}"
                        if recommendations
                        else ""
                    ),
                    tokens,
                    None,
                )

            # Claude returned text but not JSON — use raw text
            return raw, tokens, None

        except Exception as exc:
            self._logger.warning("Claude portfolio analysis failed: %s", exc)
            return (
                "",
                0,
                f"Claude analysis failed: {exc} — using rule-based summary",
            )

    # ------------------------------------------------------------------
    # Rule-based fallback
    # ------------------------------------------------------------------

    @staticmethod
    def _build_rule_based_summary(metrics: dict[str, Any]) -> str:
        """Generate a simple summary when Claude is unavailable."""
        total = metrics.get("total_value_usd", 0)
        daily_pnl = metrics.get("daily_pnl_usd", 0)
        cumulative = metrics.get("cumulative_pnl_usd", 0)
        drawdown = metrics.get("max_drawdown_pct", 0)
        trade_count = metrics.get("trade_count", 0)
        positions = metrics.get("positions", {})

        # Determine risk level
        if drawdown > 5:
            risk = "HIGH"
        elif drawdown > 2 or daily_pnl < -50:
            risk = "MEDIUM"
        else:
            risk = "LOW"

        parts = [f"[{risk}]"]
        parts.append(f"Portfolio: ${total:.2f}.")
        parts.append(f"Daily P&L: ${daily_pnl:+.2f}.")
        parts.append(f"Cumulative: ${cumulative:+.2f}.")

        if drawdown > 0:
            parts.append(f"Max drawdown: {drawdown:.2f}%.")

        parts.append(f"{trade_count} trades in 24h.")
        parts.append(f"{len(positions)} open positions.")

        return " ".join(parts)
