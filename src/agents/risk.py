"""
risk.py
-------
RiskAgent — final safety gate before trade execution.

Evaluates trade signals from SignalAgent against position sizing rules,
daily loss limits, cooldown periods, concentration limits, and stop-loss
thresholds. Uses Claude Sonnet for final risk reasoning and validation.
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from anthropic import AsyncAnthropic

from src.agents.base import AgentResult, AgentRole, BaseAgent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default risk parameters (matching config/bot_config.yaml)
# ---------------------------------------------------------------------------

DEFAULT_MAX_DAILY_LOSS_USD = 200.0
DEFAULT_MAX_SINGLE_TRADE_USD = 150.0
DEFAULT_COOLDOWN_MINUTES = 15
DEFAULT_STOP_LOSS_PCT = 8.0
DEFAULT_MAX_CONCENTRATION_PCT = 0.40
DEFAULT_BASE_POSITION_USD = 25.0
DEFAULT_MAX_POSITION_USD = 150.0
MIN_TRADE_USD = 5.0  # Minimum meaningful trade size


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class RiskDecision:
    """Risk assessment result for a single trade signal."""

    ticker: str
    approved: bool
    action: str                          # "buy" | "sell" | "hold"
    proposed_amount_usd: float
    adjusted_amount_usd: Optional[float] = None  # May be reduced
    reason: str = ""
    stop_loss_triggered: bool = False


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class RiskAgent(BaseAgent):
    """
    Specialist agent for risk management and position control.

    Enforces:
    - Position sizing: linear scale from base ($25) to max ($150) by confidence
    - Daily loss limit: $200 max daily loss, blocks all trades when breached
    - Trade cooldown: 15 min per ticker between trades
    - Concentration limit: 40% max portfolio allocation per ticker
    - Stop-loss: 8% drop from entry triggers automatic sell alert

    Uses Claude Sonnet for final reasoning. Claude can downgrade (approve →
    reject) but CANNOT override hard rejections — risk rules are absolute.
    """

    def __init__(
        self,
        api_key: str,
        max_daily_loss_usd: float = DEFAULT_MAX_DAILY_LOSS_USD,
        max_single_trade_usd: float = DEFAULT_MAX_SINGLE_TRADE_USD,
        cooldown_minutes: int = DEFAULT_COOLDOWN_MINUTES,
        stop_loss_pct: float = DEFAULT_STOP_LOSS_PCT,
        max_concentration_pct: float = DEFAULT_MAX_CONCENTRATION_PCT,
        base_position_usd: float = DEFAULT_BASE_POSITION_USD,
        max_position_usd: float = DEFAULT_MAX_POSITION_USD,
    ) -> None:
        super().__init__(
            role=AgentRole.RISK,
            model="claude-sonnet-4-6",
            api_key=api_key,
        )
        self._client = AsyncAnthropic(api_key=api_key)
        self._max_daily_loss = max_daily_loss_usd
        self._max_single_trade = max_single_trade_usd
        self._cooldown_minutes = cooldown_minutes
        self._stop_loss_pct = stop_loss_pct
        self._max_concentration = max_concentration_pct
        self._base_position = base_position_usd
        self._max_position = max_position_usd

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    def system_prompt(self) -> str:
        return (
            "You are a quantitative risk manager for a crypto trading bot.\n\n"
            "You receive pre-computed risk assessments for trade signals. Your task "
            "is to validate these assessments, add qualitative reasoning, and produce "
            "final risk decisions.\n\n"
            "Core principles:\n"
            "- Capital preservation takes absolute priority over profit maximisation\n"
            "- You may REJECT trades that rule-based checks approved (add caution)\n"
            "- You may REDUCE position sizes below what rules allow\n"
            "- You CANNOT approve trades that rule-based checks rejected\n"
            "- Hard limits (daily loss, cooldown, concentration) are non-negotiable\n"
            "- When uncertain, default to rejection or size reduction\n\n"
            "Guidelines:\n"
            "- Consider correlation risk: multiple buys in related assets increase exposure\n"
            "- Consider market conditions: high volatility warrants smaller positions\n"
            "- Anomaly-flagged signals deserve extra scrutiny\n"
            "- Stop-loss alerts should be acted on promptly\n\n"
            "Return ONLY a JSON array of objects:\n"
            '[{"ticker": "...", "approved": true|false, '
            '"adjusted_amount_usd": N.NN, "rationale": "..."}]'
        )

    async def execute(self, context: dict[str, Any]) -> AgentResult:
        """
        Run one risk assessment cycle.

        Parameters
        ----------
        context : dict
            Expected keys:
                trade_signals      — list of TradeSignal dicts from SignalAgent
                daily_pnl_usd     — float, today's realised P&L (default 0.0)
                recent_trades      — dict {ticker: ISO timestamp} for last trade
                portfolio_positions — dict {ticker: {"value_usd", "entry_price",
                                     "current_price", "quantity"}}
                portfolio_total_usd — float, total portfolio value

        Returns
        -------
        AgentResult with keys:
            risk_decisions   — list of RiskDecision dicts
            decisions_count  — total number of decisions
            approved_count   — number of approved trades
            rejected_count   — number of rejected trades
            stop_loss_alerts — list of stop-loss sell decisions
        """
        cycle_start = time.monotonic()
        errors: list[str] = []
        tokens_used = 0

        # Extract context data with safe defaults
        trade_signals: list[dict[str, Any]] = context.get("trade_signals", [])
        daily_pnl: float = float(context.get("daily_pnl_usd", 0.0))
        recent_trades: dict[str, str] = context.get("recent_trades", {})
        portfolio_positions: dict[str, dict[str, Any]] = context.get(
            "portfolio_positions", {}
        )
        portfolio_total: float = float(context.get("portfolio_total_usd", 0.0))

        if not trade_signals:
            self._logger.warning("No trade signals available for risk assessment")
            return self._build_result(
                success=True,
                data={
                    "risk_decisions": [],
                    "decisions_count": 0,
                    "approved_count": 0,
                    "rejected_count": 0,
                    "stop_loss_alerts": [],
                },
                errors=["No trade signals available"],
                duration_ms=(time.monotonic() - cycle_start) * 1000,
            )

        # Check daily loss limit — blocks ALL trades if breached
        daily_loss_breached = daily_pnl <= -self._max_daily_loss
        if daily_loss_breached:
            self._logger.warning(
                "Daily loss limit breached: P&L $%.2f <= -$%.2f",
                daily_pnl,
                self._max_daily_loss,
            )

        # Assess each trade signal
        decisions: list[RiskDecision] = []

        for signal in trade_signals:
            decision = self._assess_signal(
                signal=signal,
                daily_loss_breached=daily_loss_breached,
                daily_pnl=daily_pnl,
                recent_trades=recent_trades,
                portfolio_positions=portfolio_positions,
                portfolio_total=portfolio_total,
            )
            decisions.append(decision)

        # Check for stop-loss alerts
        stop_loss_alerts = self._check_stop_losses(
            portfolio_positions, portfolio_total
        )
        decisions.extend(stop_loss_alerts)

        # Call Claude Sonnet for final reasoning
        portfolio_state = {
            "daily_pnl_usd": daily_pnl,
            "portfolio_total_usd": portfolio_total,
            "positions": portfolio_positions,
            "daily_loss_breached": daily_loss_breached,
        }

        final_decisions, claude_tokens, claude_err = (
            await self._reason_with_claude(decisions, portfolio_state, daily_pnl)
        )
        tokens_used += claude_tokens
        if claude_err:
            errors.append(claude_err)

        approved_count = sum(1 for d in final_decisions if d.approved)
        rejected_count = sum(1 for d in final_decisions if not d.approved)
        stop_loss_count = sum(1 for d in final_decisions if d.stop_loss_triggered)

        duration_ms = (time.monotonic() - cycle_start) * 1000
        self._logger.info(
            "Risk cycle: %d decisions (%d approved, %d rejected, %d stop-loss), "
            "%.0f ms",
            len(final_decisions),
            approved_count,
            rejected_count,
            stop_loss_count,
            duration_ms,
        )

        return self._build_result(
            success=True,
            data={
                "risk_decisions": [
                    self._decision_to_dict(d) for d in final_decisions
                ],
                "decisions_count": len(final_decisions),
                "approved_count": approved_count,
                "rejected_count": rejected_count,
                "stop_loss_alerts": [
                    self._decision_to_dict(d)
                    for d in final_decisions
                    if d.stop_loss_triggered
                ],
            },
            errors=errors,
            duration_ms=duration_ms,
            tokens_used=tokens_used,
        )

    # ------------------------------------------------------------------
    # Signal assessment
    # ------------------------------------------------------------------

    def _assess_signal(
        self,
        signal: dict[str, Any],
        daily_loss_breached: bool,
        daily_pnl: float,
        recent_trades: dict[str, str],
        portfolio_positions: dict[str, dict[str, Any]],
        portfolio_total: float,
    ) -> RiskDecision:
        """Assess a single trade signal against all risk rules."""
        ticker = signal.get("ticker", "UNKNOWN")
        action = signal.get("action", "hold").lower()
        confidence = float(signal.get("confidence", 0.0))

        # Skip hold signals — no risk assessment needed
        if action == "hold":
            return RiskDecision(
                ticker=ticker,
                approved=False,
                action="hold",
                proposed_amount_usd=0.0,
                reason="HOLD signal — no action required.",
            )

        # Compute position size based on confidence
        proposed_amount = self._compute_position_size(confidence)

        # --- Check 1: Daily loss limit ---
        if daily_loss_breached:
            return RiskDecision(
                ticker=ticker,
                approved=False,
                action=action,
                proposed_amount_usd=proposed_amount,
                reason=(
                    f"Daily loss limit reached. Current P&L: "
                    f"${daily_pnl:.2f} / limit: -${self._max_daily_loss:.2f}."
                ),
            )

        # --- Check 2: Trade cooldown ---
        cooldown_rejection = self._check_cooldown(ticker, recent_trades)
        if cooldown_rejection:
            return RiskDecision(
                ticker=ticker,
                approved=False,
                action=action,
                proposed_amount_usd=proposed_amount,
                reason=cooldown_rejection,
            )

        # --- Check 3: Concentration limit (buys only) ---
        adjusted_amount = proposed_amount
        if action == "buy":
            adjusted_amount = self._check_concentration(
                ticker, proposed_amount, portfolio_positions, portfolio_total
            )
            if adjusted_amount is None:
                return RiskDecision(
                    ticker=ticker,
                    approved=False,
                    action=action,
                    proposed_amount_usd=proposed_amount,
                    reason=(
                        f"Concentration limit breached. {ticker} would exceed "
                        f"{self._max_concentration * 100:.0f}% of portfolio."
                    ),
                )

        # --- Check 4: Minimum trade size ---
        if adjusted_amount < MIN_TRADE_USD:
            return RiskDecision(
                ticker=ticker,
                approved=False,
                action=action,
                proposed_amount_usd=proposed_amount,
                reason=(
                    f"Trade amount ${adjusted_amount:.2f} below minimum "
                    f"${MIN_TRADE_USD:.2f}."
                ),
            )

        # All checks passed
        return RiskDecision(
            ticker=ticker,
            approved=True,
            action=action,
            proposed_amount_usd=proposed_amount,
            adjusted_amount_usd=round(adjusted_amount, 2),
            reason="All risk checks passed.",
        )

    # ------------------------------------------------------------------
    # Position sizing
    # ------------------------------------------------------------------

    def _compute_position_size(self, confidence: float) -> float:
        """
        Scale position linearly from base to max based on confidence.

        Formula: base + (max - base) * confidence
        Capped at max_single_trade_usd.
        """
        confidence = max(0.0, min(1.0, confidence))
        amount = self._base_position + (
            (self._max_position - self._base_position) * confidence
        )
        amount = min(amount, self._max_single_trade)
        return round(amount, 2)

    # ------------------------------------------------------------------
    # Cooldown check
    # ------------------------------------------------------------------

    def _check_cooldown(
        self, ticker: str, recent_trades: dict[str, str]
    ) -> Optional[str]:
        """Check if ticker is within cooldown period. Returns reason or None."""
        last_trade_str = recent_trades.get(ticker)
        if not last_trade_str:
            return None

        try:
            last_trade_time = datetime.fromisoformat(
                last_trade_str.replace("Z", "+00:00")
            )
            if last_trade_time.tzinfo is None:
                last_trade_time = last_trade_time.replace(tzinfo=timezone.utc)

            now = datetime.now(timezone.utc)
            elapsed = now - last_trade_time
            cooldown = timedelta(minutes=self._cooldown_minutes)

            if elapsed < cooldown:
                remaining = int((cooldown - elapsed).total_seconds() / 60)
                return (
                    f"Cooldown active for {ticker}. "
                    f"{remaining} minute(s) remaining."
                )
        except (ValueError, TypeError) as exc:
            self._logger.warning(
                "Could not parse last trade time for %s: %s", ticker, exc
            )

        return None

    # ------------------------------------------------------------------
    # Concentration check
    # ------------------------------------------------------------------

    def _check_concentration(
        self,
        ticker: str,
        proposed_amount: float,
        portfolio_positions: dict[str, dict[str, Any]],
        portfolio_total: float,
    ) -> Optional[float]:
        """
        Check concentration limit. Returns adjusted amount or None if rejected.

        If the proposed buy would push the ticker above the concentration limit,
        reduce the amount to stay within bounds. Returns None if even the
        minimum trade would breach the limit.
        """
        current_value = float(
            portfolio_positions.get(ticker, {}).get("value_usd", 0.0)
        )
        new_total = portfolio_total + proposed_amount

        if new_total <= 0:
            return proposed_amount

        # What's the max this ticker can hold?
        max_allowed_value = new_total * self._max_concentration
        available_room = max_allowed_value - current_value

        if available_room <= 0:
            return None

        if proposed_amount <= available_room:
            return proposed_amount

        # Reduce to fit within concentration limit
        adjusted = available_room
        if adjusted < MIN_TRADE_USD:
            return None

        self._logger.info(
            "Concentration limit: reducing %s buy from $%.2f to $%.2f",
            ticker,
            proposed_amount,
            adjusted,
        )
        return round(adjusted, 2)

    # ------------------------------------------------------------------
    # Stop-loss detection
    # ------------------------------------------------------------------

    def _check_stop_losses(
        self,
        portfolio_positions: dict[str, dict[str, Any]],
        portfolio_total: float,
    ) -> list[RiskDecision]:
        """Check all positions for stop-loss triggers."""
        alerts: list[RiskDecision] = []

        for ticker, position in portfolio_positions.items():
            entry_price = float(position.get("entry_price", 0.0))
            current_price = float(position.get("current_price", 0.0))
            value_usd = float(position.get("value_usd", 0.0))

            if entry_price <= 0 or current_price <= 0:
                continue

            drop_pct = (entry_price - current_price) / entry_price * 100

            if drop_pct > self._stop_loss_pct:
                self._logger.warning(
                    "Stop-loss triggered for %s: %.1f%% drop (threshold: %.1f%%)",
                    ticker,
                    drop_pct,
                    self._stop_loss_pct,
                )
                alerts.append(
                    RiskDecision(
                        ticker=ticker,
                        approved=True,
                        action="sell",
                        proposed_amount_usd=value_usd,
                        adjusted_amount_usd=value_usd,
                        reason=(
                            f"Stop-loss triggered: {ticker} dropped {drop_pct:.1f}% "
                            f"from entry (threshold: {self._stop_loss_pct:.1f}%). "
                            f"Sell entire position."
                        ),
                        stop_loss_triggered=True,
                    )
                )

        return alerts

    # ------------------------------------------------------------------
    # Claude reasoning
    # ------------------------------------------------------------------

    async def _reason_with_claude(
        self,
        decisions: list[RiskDecision],
        portfolio_state: dict[str, Any],
        daily_pnl: float,
    ) -> tuple[list[RiskDecision], int, Optional[str]]:
        """Use Claude Sonnet to reason about risk decisions."""
        decisions_data = [self._decision_to_dict(d) for d in decisions]

        prompt = (
            "Evaluate the following risk assessment decisions and provide "
            "final validation.\n\n"
            "CRITICAL RULES:\n"
            "- You CANNOT approve trades that were rejected by rule-based checks\n"
            "- You CAN reject trades that were approved (add caution)\n"
            "- You CAN reduce position sizes below approved amounts\n"
            "- Hard rejections (daily loss, cooldown, concentration) are final\n\n"
            f"Daily P&L: ${daily_pnl:.2f}\n"
            f"Portfolio state:\n{json.dumps(portfolio_state, indent=2)}\n\n"
            f"Pre-computed decisions:\n{json.dumps(decisions_data, indent=2)}\n\n"
            "For each decision, provide your assessment. You may add rationale, "
            "reduce amounts, or downgrade approved → rejected."
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
                self._logger.warning(
                    "Claude returned non-JSON response for risk decisions"
                )
                return (
                    decisions,
                    tokens,
                    "Claude returned non-JSON — used rule-based decisions",
                )

            parsed: list[dict[str, Any]] = json.loads(match.group())
            claude_by_ticker = {
                item["ticker"]: item for item in parsed if "ticker" in item
            }

            final_decisions: list[RiskDecision] = []
            for decision in decisions:
                claude_rec = claude_by_ticker.get(decision.ticker, {})
                final = self._merge_claude_decision(decision, claude_rec)
                final_decisions.append(final)

            return final_decisions, tokens, None

        except Exception as exc:
            self._logger.warning("Claude risk reasoning failed: %s", exc)
            return (
                decisions,
                0,
                f"Claude reasoning failed: {exc} — used rule-based decisions",
            )

    def _merge_claude_decision(
        self,
        rule_decision: RiskDecision,
        claude_rec: dict[str, Any],
    ) -> RiskDecision:
        """
        Merge Claude's recommendation with rule-based decision.

        Claude can only make decisions MORE conservative, never less.
        """
        if not claude_rec:
            return rule_decision

        claude_approved = claude_rec.get("approved", rule_decision.approved)
        claude_amount = claude_rec.get(
            "adjusted_amount_usd", rule_decision.adjusted_amount_usd
        )
        claude_rationale = claude_rec.get("rationale", "")

        # Rule 1: Claude CANNOT upgrade rejected → approved
        if not rule_decision.approved:
            return RiskDecision(
                ticker=rule_decision.ticker,
                approved=False,
                action=rule_decision.action,
                proposed_amount_usd=rule_decision.proposed_amount_usd,
                adjusted_amount_usd=rule_decision.adjusted_amount_usd,
                reason=(
                    f"{rule_decision.reason} "
                    f"Claude: {claude_rationale}"
                    if claude_rationale
                    else rule_decision.reason
                ),
                stop_loss_triggered=rule_decision.stop_loss_triggered,
            )

        # Rule 2: Claude CAN downgrade approved → rejected
        if not claude_approved:
            return RiskDecision(
                ticker=rule_decision.ticker,
                approved=False,
                action=rule_decision.action,
                proposed_amount_usd=rule_decision.proposed_amount_usd,
                adjusted_amount_usd=None,
                reason=(
                    f"Claude override: rejected. {claude_rationale}"
                ),
                stop_loss_triggered=rule_decision.stop_loss_triggered,
            )

        # Rule 3: Claude CAN reduce amounts (not increase)
        final_amount = rule_decision.adjusted_amount_usd
        if claude_amount is not None and final_amount is not None:
            claude_amount = float(claude_amount)
            if claude_amount < final_amount:
                final_amount = round(claude_amount, 2)

                # Check minimum after reduction
                if final_amount < MIN_TRADE_USD:
                    return RiskDecision(
                        ticker=rule_decision.ticker,
                        approved=False,
                        action=rule_decision.action,
                        proposed_amount_usd=rule_decision.proposed_amount_usd,
                        adjusted_amount_usd=None,
                        reason=(
                            f"Claude reduced amount to ${final_amount:.2f}, "
                            f"below minimum ${MIN_TRADE_USD:.2f}. "
                            f"{claude_rationale}"
                        ),
                        stop_loss_triggered=rule_decision.stop_loss_triggered,
                    )

        return RiskDecision(
            ticker=rule_decision.ticker,
            approved=True,
            action=rule_decision.action,
            proposed_amount_usd=rule_decision.proposed_amount_usd,
            adjusted_amount_usd=final_amount,
            reason=(
                f"{rule_decision.reason} Claude: {claude_rationale}"
                if claude_rationale
                else rule_decision.reason
            ),
            stop_loss_triggered=rule_decision.stop_loss_triggered,
        )

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _decision_to_dict(decision: RiskDecision) -> dict[str, Any]:
        return {
            "ticker": decision.ticker,
            "approved": decision.approved,
            "action": decision.action,
            "proposed_amount_usd": decision.proposed_amount_usd,
            "adjusted_amount_usd": decision.adjusted_amount_usd,
            "reason": decision.reason,
            "stop_loss_triggered": decision.stop_loss_triggered,
        }
