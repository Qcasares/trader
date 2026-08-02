"""
types.py
--------
Core value types shared by the backtest and live paths.

Precision policy
~~~~~~~~~~~~~~~~
The backtest driver and the live driver must produce *identical* orders from
identical inputs (see ``tests/unit/test_parity.py``). That is only achievable
if the shared path is exact, so:

- Market data and indicator maths use ``float`` (pandas/numpy native).
- Portfolio accounting and order quantities use ``Decimal``.
- The float -> Decimal boundary happens in exactly one place,
  ``src/core/orders.weights_to_orders``, using the quantizers defined here.

Anything that crosses from "research maths" into "an instruction to a broker"
must go through :func:`quantize_qty` or :func:`quantize_usd`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from typing import Any

# ---------------------------------------------------------------------------
# Quantization
# ---------------------------------------------------------------------------

#: Alpaca supports fractional share quantities to 9 decimal places.
QTY_PRECISION = Decimal("0.000000001")

#: US dollar amounts are quantized to cents.
USD_PRECISION = Decimal("0.01")


def quantize_qty(value: Decimal | float | int | str) -> Decimal:
    """
    Quantize a share quantity to broker precision.

    Rounds *down* (toward zero) so a computed target can never round up into
    more buying power than the portfolio actually has.
    """
    return Decimal(str(value)).quantize(QTY_PRECISION, rounding=ROUND_DOWN)


def quantize_usd(value: Decimal | float | int | str) -> Decimal:
    """Quantize a dollar amount to cents using banker's rounding."""
    return Decimal(str(value)).quantize(USD_PRECISION, rounding=ROUND_HALF_EVEN)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"


class TradingMode(StrEnum):
    """
    Which execution surface a run targets.

    ``BACKTEST`` and ``PAPER`` are always safe. ``LIVE`` is additionally gated
    by the ``LIVE_TRADING_ENABLED`` environment variable — see
    ``src/execution/alpaca.py``.
    """

    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


class OrderState(StrEnum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Bar:
    """
    One daily OHLCV bar.

    ``adj_close`` is split- *and* dividend-adjusted. Strategies must use
    ``adj_close`` for signal computation; ``open``/``close`` are the raw prices
    used for fill simulation and position marking.
    """

    symbol: str
    session: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    adj_close: float
    source: str = ""


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Position:
    """A held position. ``qty`` may be fractional; negative means short."""

    symbol: str
    qty: Decimal
    avg_entry_price: Decimal

    @property
    def is_flat(self) -> bool:
        return self.qty == 0


@dataclass(frozen=True, slots=True)
class PortfolioState:
    """
    Immutable snapshot of the portfolio at a point in time.

    ``equity`` is cash plus the mark-to-market value of every position, and is
    the denominator for every target weight. It is stored rather than derived
    so that the backtest and the broker can each supply their own authoritative
    figure without the shared code having to re-price anything.
    """

    cash: Decimal
    positions: dict[str, Position]
    equity: Decimal
    as_of: date

    def qty_of(self, symbol: str) -> Decimal:
        pos = self.positions.get(symbol)
        return pos.qty if pos is not None else Decimal("0")

    @property
    def held_symbols(self) -> frozenset[str]:
        return frozenset(s for s, p in self.positions.items() if not p.is_flat)


@dataclass(frozen=True, slots=True)
class AccountState:
    """Broker-level account facts that the portfolio state does not carry."""

    cash: Decimal
    equity: Decimal
    buying_power: Decimal
    currency: str = "USD"
    is_blocked: bool = False
    pattern_day_trader: bool = False


# ---------------------------------------------------------------------------
# Strategy output
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TargetWeights:
    """
    A strategy's desired allocation, as fractions of total equity.

    Symbols absent from ``weights`` are targeted at zero — i.e. liquidated.
    The sum must not exceed 1.0; the remainder is cash. Leverage is not
    supported and is rejected at construction rather than silently clamped,
    because a strategy that thinks it is 2x levered and is not would produce a
    backtest that cannot be reproduced live.
    """

    weights: dict[str, float]
    rationale: str = ""

    def __post_init__(self) -> None:
        for symbol, weight in self.weights.items():
            if weight < 0:
                raise ValueError(
                    f"Negative weight {weight} for {symbol}; shorting is not "
                    "supported by this engine."
                )
        total = sum(self.weights.values())
        if total > 1.0 + 1e-9:
            raise ValueError(
                f"Target weights sum to {total:.6f}, which implies leverage. "
                "Leverage is not supported."
            )

    @property
    def cash_weight(self) -> float:
        return max(0.0, 1.0 - sum(self.weights.values()))


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OrderIntent:
    """
    A fully-specified instruction, before it reaches any broker.

    This is the object the parity test compares: given the same panel and the
    same portfolio state, the backtest driver and the live driver must produce
    an identical list of these.

    Exactly one of ``qty`` and ``notional`` is set.
    """

    symbol: str
    side: Side
    qty: Decimal | None = None
    notional: Decimal | None = None
    order_type: OrderType = OrderType.MARKET
    limit_price: Decimal | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if (self.qty is None) == (self.notional is None):
            raise ValueError(
                f"{self.symbol}: exactly one of qty or notional must be set "
                f"(got qty={self.qty}, notional={self.notional})"
            )
        if self.qty is not None and self.qty <= 0:
            raise ValueError(f"{self.symbol}: qty must be positive, got {self.qty}")
        if self.notional is not None and self.notional <= 0:
            raise ValueError(
                f"{self.symbol}: notional must be positive, got {self.notional}"
            )
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError(f"{self.symbol}: limit order requires a limit_price")


@dataclass(frozen=True, slots=True)
class OrderAck:
    """What a broker returns when an intent is accepted."""

    broker_order_id: str
    symbol: str
    side: Side
    state: OrderState
    submitted_at: datetime
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Fill:
    """A (possibly partial) execution against an order."""

    broker_order_id: str
    symbol: str
    side: Side
    qty: Decimal
    price: Decimal
    commission: Decimal
    filled_at: datetime

    @property
    def gross_usd(self) -> Decimal:
        return quantize_usd(self.qty * self.price)


@dataclass(frozen=True, slots=True)
class OrderStatus:
    """Current broker-side state of a previously submitted order."""

    broker_order_id: str
    symbol: str
    side: Side
    state: OrderState
    filled_qty: Decimal
    avg_fill_price: Decimal | None
    fills: tuple[Fill, ...] = ()

    @property
    def is_terminal(self) -> bool:
        return self.state in {
            OrderState.FILLED,
            OrderState.CANCELED,
            OrderState.REJECTED,
            OrderState.EXPIRED,
        }


# ---------------------------------------------------------------------------
# Cost model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CostModel:
    """
    Transaction costs applied by the simulated broker.

    Defaults model a commission-free US equity broker with a realistic spread
    cost on liquid ETFs. ``stress_multiplier`` exists so every backtest can be
    re-run at inflated cost without editing the strategy: a result that only
    survives at 1x cost is not a result.
    """

    commission_per_share: Decimal = Decimal("0")
    commission_pct: Decimal = Decimal("0")
    min_commission: Decimal = Decimal("0")
    slippage_bps: float = 5.0
    stress_multiplier: float = 1.0

    def slippage_fraction(self) -> float:
        """Slippage as a signed-magnitude fraction of price."""
        return (self.slippage_bps * self.stress_multiplier) / 10_000.0

    def commission_for(self, qty: Decimal, price: Decimal) -> Decimal:
        """Commission for a single fill, before quantization."""
        mult = Decimal(str(self.stress_multiplier))
        per_share = self.commission_per_share * abs(qty)
        pct = self.commission_pct * abs(qty) * price
        fee = (per_share + pct) * mult
        floor = self.min_commission * mult
        return quantize_usd(max(fee, floor) if abs(qty) > 0 else Decimal("0"))


def utcnow() -> datetime:
    """Timezone-aware current UTC time. Centralised so tests can patch it."""
    return datetime.now(UTC)
