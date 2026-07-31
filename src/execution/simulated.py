"""
simulated.py
------------
``SimulatedBroker`` — the backtest's execution venue.

It implements the same :class:`~src.execution.base.BrokerAdapter` protocol as
the live Alpaca adapter, which is the point: the backtest is not a separate
code path that happens to resemble live trading, it is the live path with this
object substituted.

Submitted orders are *queued*, not filled. The driver fills them explicitly at
the next session's open via :meth:`execute_pending`. That mirrors reality — you
decide on tonight's close and find out your fill price tomorrow morning — and
it makes the single most common backtest lie (filling at the price you used to
decide) structurally impossible.

The one place this venue is *kinder* than a real one
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A buy that cannot be funded is trimmed to fit available cash. A real venue
rejects it. That difference is invisible to ``tests/unit/test_parity.py``,
which compares ``OrderIntent`` lists — and the intents *are* identical; it is
the fills that diverge.

It is not hypothetical. Sizing happens against equity marked at session T's
close, and the fill lands at T+1's open after slippage and commission, so a
fully-invested target is under-funded by exactly the overnight gap every time
the market opens up. On the observed-price run in ``tests/unit/test_real_data``
this bound on **13 of 27 buys**.

So :attr:`SimulatedBroker.underfunded_buys` records every trim and each one
logs a warning. The cure is :attr:`~src.core.risk.RiskLimits.cash_buffer_pct`,
which is deliberately still off by default — a default that silently
constrained would make every backtest measure the gate rather than the
strategy. The point here is that the backtest must *say* when it did something
the live venue would not have done, not quietly paper over it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.core.clock import Clock
from src.core.types import (
    AccountState,
    CostModel,
    Fill,
    OrderAck,
    OrderIntent,
    OrderState,
    OrderStatus,
    Position,
    Side,
    TradingMode,
    quantize_qty,
    quantize_usd,
    utcnow,
)
from src.execution.base import BrokerBase, OrderRejectedError, TradingHaltedError

logger = logging.getLogger(__name__)


class InsufficientCashError(OrderRejectedError):
    """A buy could not be funded. Mirrors Alpaca's buying-power rejection."""


@dataclass(frozen=True, slots=True)
class UnderfundedBuy:
    """
    A buy the simulated venue trimmed to fit cash.

    Recorded because a real venue would have rejected the order outright, so
    every entry here is a session on which the backtest and the live system
    would have diverged in holdings while agreeing exactly on intent.
    """

    symbol: str
    requested_qty: Decimal
    filled_qty: Decimal
    price: Decimal
    cash_available: Decimal
    at: datetime

    @property
    def shortfall_fraction(self) -> float:
        """How much of the intended order went unfilled, as a fraction."""
        if self.requested_qty <= 0:
            return 0.0
        return float((self.requested_qty - self.filled_qty) / self.requested_qty)


class SimulatedBroker(BrokerBase):
    """
    An in-memory ledger with a cost model.

    Parameters
    ----------
    initial_cash:
        Starting balance.
    cost_model:
        Commission and slippage assumptions.
    allow_fractional:
        Whether fractional share quantities are accepted. Mirrors the venue
        constraint so the backtest exercises the same rounding as live.
    """

    def __init__(
        self,
        initial_cash: Decimal | float | str = Decimal("100000"),
        cost_model: CostModel | None = None,
        allow_fractional: bool = True,
        clock: Clock | None = None,
    ) -> None:
        super().__init__(TradingMode.BACKTEST)
        self._cash = quantize_usd(Decimal(str(initial_cash)))
        self._initial_cash = self._cash
        self._costs = cost_model or CostModel()
        self._allow_fractional = allow_fractional
        # Timestamps come from the injected clock so a backtest records when an
        # event *would* have happened, not when the simulation ran.
        self._clock = clock

        self._positions: dict[str, Position] = {}
        self._marks: dict[str, Decimal] = {}
        self._pending: dict[str, OrderIntent] = {}
        self._orders: dict[str, OrderStatus] = {}
        self._fills: list[Fill] = []
        self._halted = False
        self._seq = 0
        self._underfunded: list[UnderfundedBuy] = []

    # ------------------------------------------------------------------
    # Divergence reporting
    # ------------------------------------------------------------------

    @property
    def underfunded_buys(self) -> tuple[UnderfundedBuy, ...]:
        """
        Every buy this venue trimmed that a real one would have rejected.

        A non-empty list means the backtest and the live system would have
        ended the run holding different books, however identical their order
        intents were. Read it before believing a result.
        """
        return tuple(self._underfunded)

    # ------------------------------------------------------------------
    # BrokerAdapter surface
    # ------------------------------------------------------------------

    async def get_account(self) -> AccountState:
        equity = self.equity
        return AccountState(
            cash=self._cash,
            equity=equity,
            buying_power=max(self._cash, Decimal("0")),
        )

    async def get_positions(self) -> dict[str, Position]:
        return {s: p for s, p in self._positions.items() if not p.is_flat}

    async def submit(self, intent: OrderIntent) -> OrderAck:
        if self._halted:
            raise TradingHaltedError("SimulatedBroker is halted; refusing to queue")

        if intent.qty is not None and not self._allow_fractional:
            if intent.qty != intent.qty.to_integral_value():
                raise OrderRejectedError(
                    f"{intent.symbol}: fractional qty {intent.qty} rejected "
                    "by a venue that does not support fractional shares"
                )

        self._seq += 1
        order_id = f"sim-{self._seq:06d}"
        self._pending[order_id] = intent
        self._orders[order_id] = OrderStatus(
            broker_order_id=order_id,
            symbol=intent.symbol,
            side=intent.side,
            state=OrderState.SUBMITTED,
            filled_qty=Decimal("0"),
            avg_fill_price=None,
        )
        return OrderAck(
            broker_order_id=order_id,
            symbol=intent.symbol,
            side=intent.side,
            state=OrderState.SUBMITTED,
            submitted_at=self._now(),
        )

    def _now(self) -> datetime:
        return self._clock.now() if self._clock is not None else utcnow()

    async def get_order(self, broker_order_id: str) -> OrderStatus:
        try:
            return self._orders[broker_order_id]
        except KeyError:
            raise OrderRejectedError(f"unknown order {broker_order_id}") from None

    async def cancel_all(self) -> int:
        """Cancel every queued order. The kill switch's second layer."""
        count = len(self._pending)
        for order_id in list(self._pending):
            previous = self._orders[order_id]
            self._orders[order_id] = OrderStatus(
                broker_order_id=order_id,
                symbol=previous.symbol,
                side=previous.side,
                state=OrderState.CANCELED,
                filled_qty=previous.filled_qty,
                avg_fill_price=previous.avg_fill_price,
            )
        self._pending.clear()
        if count:
            logger.info("SimulatedBroker cancelled %d queued order(s)", count)
        return count

    # ------------------------------------------------------------------
    # Simulation control
    # ------------------------------------------------------------------

    def halt(self, halted: bool = True) -> None:
        """Engage or clear the simulated kill switch."""
        self._halted = halted

    def execute_pending(
        self, prices: dict[str, float], at: datetime
    ) -> list[Fill]:
        """
        Fill every queued order at ``prices``, applying slippage and commission.

        Orders are filled in submission order, which is sells-then-buys because
        that is the order ``weights_to_orders`` emits. A buy that cannot be
        funded is *partially* filled down to available cash rather than
        rejected outright — matching what a notional order does at a real
        broker, and avoiding a backtest that silently skips trades the live
        system would have made.
        """
        fills: list[Fill] = []
        slip = Decimal(str(self._costs.slippage_fraction()))

        for order_id, intent in list(self._pending.items()):
            raw_price = prices.get(intent.symbol)
            if raw_price is None or raw_price <= 0:
                self._reject(order_id, intent, "no price available")
                continue

            reference = Decimal(str(raw_price))
            # Slippage always works against us: buys fill higher, sells lower.
            direction = Decimal("1") if intent.side is Side.BUY else Decimal("-1")
            fill_price = reference * (Decimal("1") + direction * slip)

            qty = self._resolve_qty(intent, fill_price)
            if qty is None or qty <= 0:
                self._reject(order_id, intent, "resolved quantity was zero")
                continue

            if intent.side is Side.BUY:
                requested = qty
                available = self._cash
                qty = self._cap_buy_to_cash(qty, fill_price)
                if qty <= 0:
                    self._reject(order_id, intent, "insufficient cash")
                    continue
                if qty < requested:
                    self._record_underfunded(
                        intent.symbol, requested, qty, fill_price, available, at
                    )
            else:
                held = self._position_qty(intent.symbol)
                qty = min(qty, held)
                if qty <= 0:
                    self._reject(order_id, intent, "no position to sell")
                    continue

            commission = self._costs.commission_for(qty, fill_price)
            fill = Fill(
                broker_order_id=order_id,
                symbol=intent.symbol,
                side=intent.side,
                qty=quantize_qty(qty),
                price=fill_price,
                commission=commission,
                filled_at=at,
            )
            self._apply_fill(fill)
            fills.append(fill)
            self._fills.append(fill)

            self._orders[order_id] = OrderStatus(
                broker_order_id=order_id,
                symbol=intent.symbol,
                side=intent.side,
                state=OrderState.FILLED,
                filled_qty=fill.qty,
                avg_fill_price=fill.price,
                fills=(fill,),
            )
            del self._pending[order_id]

        return fills

    def mark(self, prices: dict[str, float]) -> None:
        """Update mark-to-market prices used for equity."""
        for symbol, price in prices.items():
            if price is not None and price > 0:
                self._marks[symbol] = Decimal(str(price))

    # ------------------------------------------------------------------
    # Ledger
    # ------------------------------------------------------------------

    @property
    def cash(self) -> Decimal:
        return self._cash

    @property
    def initial_cash(self) -> Decimal:
        return self._initial_cash

    @property
    def equity(self) -> Decimal:
        """Cash plus mark-to-market value of all positions."""
        total = self._cash
        for symbol, position in self._positions.items():
            if position.is_flat:
                continue
            mark = self._marks.get(symbol, position.avg_entry_price)
            total += position.qty * mark
        return quantize_usd(total)

    @property
    def fills(self) -> list[Fill]:
        return list(self._fills)

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_qty(
        self, intent: OrderIntent, fill_price: Decimal
    ) -> Decimal | None:
        if intent.qty is not None:
            return intent.qty
        if intent.notional is not None and fill_price > 0:
            return quantize_qty(intent.notional / fill_price)
        return None

    def _record_underfunded(
        self,
        symbol: str,
        requested: Decimal,
        filled: Decimal,
        price: Decimal,
        cash: Decimal,
        at: datetime,
    ) -> None:
        """
        Note a trim, loudly.

        A warning rather than a debug line on purpose: this is the backtest
        being more forgiving than the venue, and the only thing worse than the
        divergence is not knowing about it.
        """
        event = UnderfundedBuy(
            symbol=symbol,
            requested_qty=requested,
            filled_qty=filled,
            price=price,
            cash_available=cash,
            at=at,
        )
        self._underfunded.append(event)
        logger.warning(
            "%s %s: buy trimmed from %s to %s (%.3f%% short) to fit $%s cash — "
            "a live venue would have rejected this order",
            at.date(),
            symbol,
            requested,
            filled,
            event.shortfall_fraction * 100,
            cash,
        )

    def _cap_buy_to_cash(self, qty: Decimal, price: Decimal) -> Decimal:
        """
        Trim a buy so it fits available cash, including its commission.

        Solves ``qty * price + commission(qty) <= cash`` by trying the full
        size, then the cash-implied size. Two passes is enough because the
        commission models in use are linear in quantity.
        """
        cost = qty * price + self._costs.commission_for(qty, price)
        if cost <= self._cash:
            return qty
        if price <= 0:
            return Decimal("0")
        affordable = quantize_qty(self._cash / price)
        while affordable > 0:
            cost = affordable * price + self._costs.commission_for(
                affordable, price
            )
            if cost <= self._cash:
                return affordable
            affordable = quantize_qty(affordable * Decimal("0.999"))
        return Decimal("0")

    def _position_qty(self, symbol: str) -> Decimal:
        position = self._positions.get(symbol)
        return position.qty if position is not None else Decimal("0")

    def _apply_fill(self, fill: Fill) -> None:
        gross = fill.qty * fill.price
        existing = self._positions.get(fill.symbol)
        current_qty = existing.qty if existing else Decimal("0")
        current_avg = existing.avg_entry_price if existing else Decimal("0")

        if fill.side is Side.BUY:
            self._cash = quantize_usd(self._cash - gross - fill.commission)
            new_qty = current_qty + fill.qty
            # Weighted-average entry price, so unrealised P&L is meaningful.
            new_avg = (
                (current_qty * current_avg + gross) / new_qty
                if new_qty > 0
                else Decimal("0")
            )
        else:
            self._cash = quantize_usd(self._cash + gross - fill.commission)
            new_qty = current_qty - fill.qty
            new_avg = current_avg if new_qty > 0 else Decimal("0")

        self._positions[fill.symbol] = Position(
            symbol=fill.symbol,
            qty=quantize_qty(new_qty),
            avg_entry_price=new_avg,
        )
        self._marks[fill.symbol] = fill.price

    def _reject(self, order_id: str, intent: OrderIntent, reason: str) -> None:
        logger.debug("Sim reject %s %s: %s", intent.side.value, intent.symbol, reason)
        self._orders[order_id] = OrderStatus(
            broker_order_id=order_id,
            symbol=intent.symbol,
            side=intent.side,
            state=OrderState.REJECTED,
            filled_qty=Decimal("0"),
            avg_fill_price=None,
        )
        self._pending.pop(order_id, None)
