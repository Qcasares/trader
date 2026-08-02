"""
risk.py
-------
The shared risk gate.

Ported from ``src/agents/risk.py`` (``_check_cooldown`` at :378,
``_check_concentration`` at :414, ``_check_stop_losses`` at :463, and the
daily-loss check at :291), reframed from dollar amounts to **target weights**
and rewritten as pure functions.

Why it lives here rather than in either driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Sharing only ``target_weights`` between backtest and live shares the easy 10%.
The two paths mostly diverge in what happens *after* the strategy speaks — the
clamps, the caps, the "should we trade at all" decision. If the backtest
measures an uncapped strategy while the live system runs a capped one, the
backtest is not a prediction of anything. So the gate is one function, called
by one driver, on both paths.

Every clamp emits a :class:`RiskEvent` in deterministic order. The event stream
is what the UI shows *and* what the parity test compares: two paths reaching
the same weights by different routes is a bug you would otherwise never see.

Three deliberate changes from the original
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
1. ``_compute_position_size`` is **not** ported. Confidence-scaled dollar
   sizing is incompatible with target weights — size is now
   ``weight × equity``, and keeping both would mean two systems disagreeing
   about how big a position is.
2. The concentration check computed ``new_total = portfolio_total + proposed``,
   inflating the denominator. That is right for adding new money and wrong for
   a rebalance, where the cash is already inside equity. Fixed.
3. Stop-losses are **opt-in and off by default**. An 8% stop on a monthly
   rebalancer is not a safety feature, it is a different strategy — one whose
   backtest must model the stop. Enabling it silently would make every
   existing backtest describe something other than what runs.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from src.core.types import PortfolioState, TargetWeights

logger = logging.getLogger(__name__)


class RiskCode(StrEnum):
    """Why the gate intervened. Stable strings — the UI and tests key off them."""

    MAX_WEIGHT_CLAMP = "max_weight_clamp"
    GROSS_EXPOSURE_CLAMP = "gross_exposure_clamp"
    DAILY_LOSS_BREACH = "daily_loss_breach"
    DRAWDOWN_BREACH = "drawdown_breach"
    COOLDOWN = "cooldown"
    STOP_LOSS = "stop_loss"
    KILL_SWITCH = "kill_switch"
    CASH_BUFFER = "cash_buffer"


class Severity(StrEnum):
    INFO = "info"
    WARN = "warn"
    BLOCK = "block"


@dataclass(frozen=True, slots=True)
class RiskEvent:
    """One intervention. Ordered deterministically so it can be diffed."""

    code: RiskCode
    severity: Severity
    message: str
    symbol: str | None = None
    #: Whether it actually changed the output, as opposed to merely being
    #: evaluated. A limit that never binds is not a limit that is working.
    binding: bool = False


@dataclass(frozen=True, slots=True)
class RiskLimits:
    """
    Configured limits. Defaults are permissive by design.

    A default that silently constrains would mean the first backtest anyone
    runs measures something other than the strategy they wrote.
    """

    #: Cap on any single position as a fraction of equity.
    max_weight_per_symbol: float = 1.0
    #: Cap on total invested fraction. 1.0 = no leverage, which this engine
    #: does not support anyway.
    max_gross_exposure: float = 1.0
    #: Halt trading once the session's loss exceeds this. None disables.
    max_daily_loss_usd: Decimal | None = None
    #: Halt once drawdown from peak exceeds this fraction. None disables.
    max_drawdown_pct: float | None = None
    #: Minimum gap between trades in the same symbol. Zero disables.
    cooldown_minutes: int = 0
    #: Per-position stop. **Off by default** — see the module docstring.
    stop_loss_pct: float | None = None
    #: Fraction of equity held back so a gap between decision and fill does not
    #: produce an insufficient-buying-power rejection.
    cash_buffer_pct: float = 0.0


@dataclass(frozen=True, slots=True)
class RiskState:
    """Everything the gate needs that is not in the portfolio itself."""

    session: date
    day_start_equity: Decimal = Decimal("0")
    current_equity: Decimal = Decimal("0")
    peak_equity: Decimal = Decimal("0")
    last_trade_at: Mapping[str, datetime] = field(default_factory=dict)
    entry_prices: Mapping[str, Decimal] = field(default_factory=dict)
    current_prices: Mapping[str, Decimal] = field(default_factory=dict)
    kill_switch_active: bool = False
    now: datetime | None = None

    @property
    def daily_pnl(self) -> Decimal:
        """Change in marked equity, not cash flow."""
        if self.day_start_equity <= 0:
            return Decimal("0")
        return self.current_equity - self.day_start_equity

    @property
    def drawdown(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return float(self.current_equity / self.peak_equity) - 1.0


@dataclass(frozen=True, slots=True)
class RiskGateResult:
    """Approved weights plus the ordered record of how they got that way."""

    weights: TargetWeights
    events: tuple[RiskEvent, ...]

    @property
    def blocked(self) -> bool:
        return any(e.severity is Severity.BLOCK for e in self.events)

    @property
    def binding_events(self) -> tuple[RiskEvent, ...]:
        return tuple(e for e in self.events if e.binding)


def apply_risk(
    targets: TargetWeights,
    portfolio: PortfolioState,
    state: RiskState,
    limits: RiskLimits,
) -> RiskGateResult:
    """
    Run every check in a fixed order and return the approved allocation.

    Order is fixed because it is compared: two paths that reach identical
    weights via different clamps have diverged, and only the event stream
    reveals it.

    A blocking check returns 100% cash rather than the previous allocation.
    "Stop trading" must mean flat, not frozen — a frozen book keeps its
    exposure to whatever caused the halt.
    """
    events: list[RiskEvent] = []

    # --- Blocking checks, in escalating order of seriousness ---------------

    if state.kill_switch_active:
        events.append(
            RiskEvent(
                RiskCode.KILL_SWITCH,
                Severity.BLOCK,
                "Kill switch engaged; liquidating to cash.",
                binding=True,
            )
        )
        return RiskGateResult(TargetWeights({}, "halted: kill switch"), tuple(events))

    if limits.max_daily_loss_usd is not None:
        loss = -state.daily_pnl
        if loss >= limits.max_daily_loss_usd:
            events.append(
                RiskEvent(
                    RiskCode.DAILY_LOSS_BREACH,
                    Severity.BLOCK,
                    f"Daily loss ${loss:.2f} reached the "
                    f"${limits.max_daily_loss_usd:.2f} limit.",
                    binding=True,
                )
            )
            return RiskGateResult(
                TargetWeights({}, "halted: daily loss limit"), tuple(events)
            )

    if limits.max_drawdown_pct is not None:
        drawdown = state.drawdown
        if drawdown <= -abs(limits.max_drawdown_pct):
            events.append(
                RiskEvent(
                    RiskCode.DRAWDOWN_BREACH,
                    Severity.BLOCK,
                    f"Drawdown {drawdown:.1%} breached the "
                    f"{-abs(limits.max_drawdown_pct):.1%} limit.",
                    binding=True,
                )
            )
            return RiskGateResult(
                TargetWeights({}, "halted: max drawdown"), tuple(events)
            )

    # --- Adjusting checks --------------------------------------------------

    weights = dict(targets.weights)

    if limits.stop_loss_pct is not None:
        for symbol in sorted(weights):
            entry = state.entry_prices.get(symbol)
            current = state.current_prices.get(symbol)
            if not entry or not current or entry <= 0:
                continue
            move = float(current / entry) - 1.0
            if move <= -abs(limits.stop_loss_pct):
                weights[symbol] = 0.0
                events.append(
                    RiskEvent(
                        RiskCode.STOP_LOSS,
                        Severity.WARN,
                        f"{symbol} is {move:.1%} below entry; exiting.",
                        symbol=symbol,
                        binding=True,
                    )
                )

    if limits.cooldown_minutes > 0 and state.now is not None:
        window = timedelta(minutes=limits.cooldown_minutes)
        for symbol in sorted(weights):
            last = state.last_trade_at.get(symbol)
            if last is None:
                continue
            elapsed = state.now - last
            if elapsed < window:
                held = float(portfolio.qty_of(symbol))
                # Hold the existing position rather than trading it again.
                current_weight = _current_weight(symbol, portfolio, state)
                if abs(weights[symbol] - current_weight) > 1e-9:
                    weights[symbol] = current_weight
                    events.append(
                        RiskEvent(
                            RiskCode.COOLDOWN,
                            Severity.INFO,
                            f"{symbol} traded {elapsed.total_seconds() / 60:.0f} "
                            f"minute(s) ago; holding at {current_weight:.4f}.",
                            symbol=symbol,
                            binding=True,
                        )
                    )
                    logger.debug("cooldown holds %s at %s (qty %s)", symbol,
                                 current_weight, held)

    if limits.max_weight_per_symbol < 1.0:
        cap = limits.max_weight_per_symbol
        for symbol in sorted(weights):
            if weights[symbol] > cap:
                events.append(
                    RiskEvent(
                        RiskCode.MAX_WEIGHT_CLAMP,
                        Severity.INFO,
                        f"{symbol} capped from {weights[symbol]:.4f} to {cap:.4f}; "
                        "the excess becomes cash.",
                        symbol=symbol,
                        binding=True,
                    )
                )
                weights[symbol] = cap

    gross = sum(weights.values())
    effective_max = limits.max_gross_exposure * (1.0 - limits.cash_buffer_pct)
    if gross > effective_max + 1e-9 and gross > 0:
        # Scale proportionally: the strategy's *relative* preferences are its
        # opinion, and the gate has no business re-ranking them.
        scale = effective_max / gross
        weights = {s: w * scale for s, w in weights.items()}
        code = (
            RiskCode.CASH_BUFFER
            if limits.cash_buffer_pct > 0 and limits.max_gross_exposure >= 1.0
            else RiskCode.GROSS_EXPOSURE_CLAMP
        )
        events.append(
            RiskEvent(
                code,
                Severity.INFO,
                f"Gross exposure {gross:.4f} scaled by {scale:.4f} to "
                f"{effective_max:.4f}.",
                binding=True,
            )
        )

    weights = {s: w for s, w in weights.items() if w > 1e-9}
    return RiskGateResult(
        TargetWeights(weights, targets.rationale), tuple(events)
    )


def _current_weight(
    symbol: str, portfolio: PortfolioState, state: RiskState
) -> float:
    """Present weight of a holding, for the cooldown hold."""
    if portfolio.equity <= 0:
        return 0.0
    price = state.current_prices.get(symbol)
    if price is None or price <= 0:
        return 0.0
    return float(portfolio.qty_of(symbol) * price / portfolio.equity)


def describe(events: tuple[RiskEvent, ...]) -> str:
    """One line per binding event, for logs and the UI."""
    binding = [e for e in events if e.binding]
    if not binding:
        return "no risk limits bound"
    return "; ".join(f"[{e.code.value}] {e.message}" for e in binding)
