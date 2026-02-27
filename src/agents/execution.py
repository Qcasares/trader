"""
execution.py
------------
ExecutionAgent — submits approved trades to bankr.bot and tracks results.

Receives approved RiskDecisions from the orchestrator context, constructs
natural-language prompts, submits them via BankrClient, and records
fill prices and slippage for each execution.
"""

import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Optional

from src.agents.base import AgentResult, AgentRole, BaseAgent
from src.bankr_client import BankrAPIError, BankrClient, Chain, TradeResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ExecutionResult:
    """Result of a single trade execution attempt."""

    ticker: str
    action: str                        # "buy" | "sell"
    amount_usd: float
    success: bool
    job_id: Optional[str] = None
    response: str = ""
    slippage_pct: Optional[float] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Patterns to extract dollar amounts from bankr.bot response text.
# Examples: "$1,234.56", "at $0.0423", "price: 1234.56"
_PRICE_PATTERNS = [
    re.compile(r"\$([0-9,]+\.?[0-9]*)"),          # $1,234.56
    re.compile(r"at\s+([0-9,]+\.?[0-9]*)"),        # at 1234.56
    re.compile(r"price[:\s]+\$?([0-9,]+\.?[0-9]*)"),  # price: 1234.56
]


def _extract_fill_price(response: str) -> Optional[float]:
    """
    Best-effort extraction of a fill price from bankr.bot response text.

    Returns the first dollar-amount found, or None if nothing parseable.
    """
    for pattern in _PRICE_PATTERNS:
        match = pattern.search(response)
        if match:
            try:
                raw = match.group(1).replace(",", "")
                price = float(raw)
                if price > 0:
                    return price
            except (ValueError, IndexError):
                continue
    logger.debug("Could not extract fill price from response: %s", response[:120])
    return None


def _calculate_slippage(expected: float, actual: float) -> float:
    """
    Calculate slippage as a percentage.

    Returns abs(actual - expected) / expected * 100.
    """
    if expected <= 0:
        return 0.0
    return abs(actual - expected) / expected * 100.0


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class ExecutionAgent(BaseAgent):
    """
    Submits approved trade signals to bankr.bot via the BankrClient.

    Context expectations:
        risk_decisions : list[dict]
            List of RiskDecision dicts from RiskAgent.  Only approved=True
            decisions are executed.
        chain : str, optional
            Chain name (default "Base").  Must match a Chain enum value.
        expected_prices : dict[str, float], optional
            Mapping of ticker → expected price for slippage calculation.
        dry_run : bool, optional
            Override dry-run flag (defaults to True for safety).
    """

    def __init__(
        self,
        api_key: str,
        bankr_api_key: str,
        dry_run: bool = True,
    ) -> None:
        super().__init__(
            role=AgentRole.EXECUTION,
            model="claude-haiku-4-5-20251001",
            api_key=api_key,
        )
        self._bankr_api_key = bankr_api_key
        self._dry_run = dry_run

    def system_prompt(self) -> str:
        return (
            "You are an execution specialist for an automated crypto trading bot. "
            "Your job is to translate approved trade decisions into bankr.bot API "
            "prompts, submit them, and track fill prices and slippage. "
            "You prioritise reliability and accurate record-keeping. "
            "If a trade fails, you log the error and continue with remaining trades."
        )

    async def execute(self, context: dict[str, Any]) -> AgentResult:
        """
        Execute approved trades from risk_decisions in context.

        Parameters
        ----------
        context : dict
            Must contain 'risk_decisions' (list of RiskDecision dicts).
            Optional: 'chain' (str), 'expected_prices' (dict),
                      'dry_run' (bool).
        """
        start = time.time()

        # --- Extract inputs from context ---
        risk_decisions = context.get("risk_decisions", [])
        chain_name = context.get("chain", "Base")
        expected_prices = context.get("expected_prices", {})
        dry_run = context.get("dry_run", self._dry_run)

        # Resolve chain enum
        try:
            chain = Chain(chain_name)
        except ValueError:
            self._logger.warning(
                "Unknown chain '%s', defaulting to Base", chain_name
            )
            chain = Chain.BASE

        # --- Filter for approved decisions ---
        approved = []
        for decision in risk_decisions:
            if decision.get("approved", False):
                approved.append(decision)
            else:
                self._logger.info(
                    "Skipping rejected decision: %s %s — %s",
                    decision.get("action", "?"),
                    decision.get("ticker", "?"),
                    decision.get("reason", "no reason"),
                )

        if not approved:
            self._logger.info("No approved risk decisions to execute.")
            return self._build_result(
                success=True,
                data={"executions": [], "summary": "No approved trades"},
                duration_ms=(time.time() - start) * 1000,
            )

        # --- Execute each approved trade ---
        executions: list[dict] = []
        errors: list[str] = []
        any_success = False

        for decision in approved:
            ticker = decision.get("ticker", "UNKNOWN")
            action = decision.get("action", "hold")
            amount_usd = _get_trade_amount(decision)

            if action not in ("buy", "sell"):
                self._logger.info(
                    "Skipping non-tradeable action '%s' for %s", action, ticker
                )
                continue

            self._logger.info(
                "Executing %s %s $%.2f on %s (dry_run=%s)",
                action, ticker, amount_usd, chain.value, dry_run,
            )

            result = await self._execute_single_trade(
                ticker=ticker,
                action=action,
                amount_usd=amount_usd,
                chain=chain,
                dry_run=dry_run,
                expected_price=expected_prices.get(ticker),
            )

            executions.append(_result_to_dict(result))

            if result.success:
                any_success = True
            else:
                error_msg = f"{action} {ticker}: {result.error}"
                errors.append(error_msg)

        elapsed = (time.time() - start) * 1000

        summary = (
            f"Executed {len(executions)} trades: "
            f"{sum(1 for e in executions if e['success'])} succeeded, "
            f"{sum(1 for e in executions if not e['success'])} failed"
        )

        return self._build_result(
            success=any_success or len(executions) == 0,
            data={"executions": executions, "summary": summary},
            errors=errors,
            duration_ms=elapsed,
        )

    # ------------------------------------------------------------------
    # Internal trade execution
    # ------------------------------------------------------------------

    async def _execute_single_trade(
        self,
        ticker: str,
        action: str,
        amount_usd: float,
        chain: Chain,
        dry_run: bool,
        expected_price: Optional[float],
    ) -> ExecutionResult:
        """Submit a single trade to bankr.bot and build an ExecutionResult."""
        try:
            async with BankrClient(
                api_key=self._bankr_api_key, dry_run=dry_run
            ) as client:
                if action == "buy":
                    trade_result: TradeResult = await client.buy(
                        token=ticker, amount_usd=amount_usd, chain=chain
                    )
                else:  # sell
                    trade_result = await client.sell(
                        token=ticker, amount_usd=amount_usd, chain=chain
                    )

            # --- Extract fill price and compute slippage ---
            fill_price = _extract_fill_price(trade_result.response)
            slippage_pct: Optional[float] = None

            if fill_price is not None and expected_price is not None:
                slippage_pct = _calculate_slippage(expected_price, fill_price)
                self._logger.info(
                    "%s %s fill=%.6f expected=%.6f slippage=%.2f%%",
                    action, ticker, fill_price, expected_price, slippage_pct,
                )
            elif fill_price is None:
                self._logger.debug(
                    "No fill price extracted for %s %s", action, ticker
                )

            return ExecutionResult(
                ticker=ticker,
                action=action,
                amount_usd=amount_usd,
                success=True,
                job_id=trade_result.job_id,
                response=trade_result.response,
                slippage_pct=slippage_pct,
                error=None,
            )

        except BankrAPIError as exc:
            self._logger.error(
                "BankrAPIError executing %s %s: %s", action, ticker, exc
            )
            return ExecutionResult(
                ticker=ticker,
                action=action,
                amount_usd=amount_usd,
                success=False,
                job_id=None,
                response="",
                slippage_pct=None,
                error=str(exc),
            )

        except Exception as exc:
            self._logger.error(
                "Unexpected error executing %s %s: %s", action, ticker, exc
            )
            return ExecutionResult(
                ticker=ticker,
                action=action,
                amount_usd=amount_usd,
                success=False,
                job_id=None,
                response="",
                slippage_pct=None,
                error=f"Unexpected: {exc}",
            )


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _get_trade_amount(decision: dict) -> float:
    """
    Return the trade amount from a RiskDecision dict.

    Prefers adjusted_amount_usd (may have been reduced by risk controls),
    falls back to proposed_amount_usd.
    """
    adjusted = decision.get("adjusted_amount_usd")
    if adjusted is not None:
        return float(adjusted)
    return float(decision.get("proposed_amount_usd", 0.0))


def _result_to_dict(result: ExecutionResult) -> dict:
    """Serialise an ExecutionResult to a plain dict for AgentResult.data."""
    return {
        "ticker": result.ticker,
        "action": result.action,
        "amount_usd": result.amount_usd,
        "success": result.success,
        "job_id": result.job_id,
        "response": result.response,
        "slippage_pct": result.slippage_pct,
        "error": result.error,
    }
