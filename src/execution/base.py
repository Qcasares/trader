"""
base.py
-------
The ``BrokerAdapter`` protocol.

This is the seam that keeps venue specifics out of strategies. The backtest
runs against ``SimulatedBroker``; paper trading runs against ``AlpacaBroker``;
a future crypto adapter wraps the existing client in ``src/bankr_client.py``.
None of them are visible to a ``Strategy``, which only ever emits weights.

Every adapter must implement :meth:`cancel_all` and must honour it promptly —
it is the second half of the kill switch, and the half that deals with orders
already in flight.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from src.core.types import (
    AccountState,
    OrderAck,
    OrderIntent,
    OrderStatus,
    Position,
    TradingMode,
)

logger = logging.getLogger(__name__)


class BrokerError(RuntimeError):
    """Any failure originating from a venue."""


class OrderRejectedError(BrokerError):
    """The venue refused an order outright."""


class TradingHaltedError(BrokerError):
    """Raised when the kill switch or a mode guard blocks a submission."""


@runtime_checkable
class BrokerAdapter(Protocol):
    """Minimum surface every execution venue must provide."""

    @property
    def mode(self) -> TradingMode:
        """Which surface this adapter targets."""
        ...

    async def get_account(self) -> AccountState:
        """Cash, equity, buying power, and account-level flags."""
        ...

    async def get_positions(self) -> dict[str, Position]:
        """Current holdings, keyed by symbol."""
        ...

    async def submit(self, intent: OrderIntent) -> OrderAck:
        """
        Send one order. Raises :class:`OrderRejectedError` if the venue refuses it
        and :class:`TradingHaltedError` if trading is disabled.
        """
        ...

    async def get_order(self, broker_order_id: str) -> OrderStatus:
        """Current state of a previously submitted order."""
        ...

    async def cancel_all(self) -> int:
        """
        Cancel every open order. Returns how many were cancelled.

        The kill switch calls this. It must not raise on a partially successful
        cancellation — cancelling four of five orders and reporting the failure
        is far better than aborting and leaving all five live.
        """
        ...


class BrokerBase:
    """
    Shared plumbing for adapters.

    Concrete adapters inherit this for the mode guard, then satisfy
    :class:`BrokerAdapter` structurally.
    """

    def __init__(self, mode: TradingMode) -> None:
        self._mode = mode
        self._logger = logging.getLogger(f"broker.{mode.value}")

    @property
    def mode(self) -> TradingMode:
        return self._mode

    def _guard_live(self, live_enabled: bool) -> None:
        """
        Refuse to operate in ``LIVE`` mode unless explicitly enabled.

        Defence in depth alongside the database kill switch: the flag can be
        flipped by anyone with API access, whereas this requires redeploying
        with a changed environment variable.
        """
        if self._mode is TradingMode.LIVE and not live_enabled:
            raise TradingHaltedError(
                "Live trading requested but LIVE_TRADING_ENABLED is not set. "
                "Refusing to place real orders."
            )
