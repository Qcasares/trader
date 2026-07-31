"""
alpaca.py
---------
Alpaca broker adapter — paper by default, live only behind two gates.

Why a thin client rather than ``alpaca-py``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
``alpaca-py`` is synchronous (built on ``requests``) while this codebase is
asyncio throughout, so using it means wrapping every call in
``asyncio.to_thread`` and inheriting a client that is not documented as
thread-safe. A target-weight rebalancer needs eight endpoints — account,
positions, submit, get order, cancel all, close position, clock, bars — all
plainly documented. Writing them against ``aiohttp`` (already a dependency)
costs less than the wrapper would, keeps one concurrency model, and makes the
whole path testable against a local fake server.

The trade-off is real and worth stating: we give up the SDK's pagination,
retry and msgpack handling. For daily rebalancing on a handful of ETFs none of
those matter. If this ever needs minute bars in bulk, revisit.

Safety
~~~~~~
Constructing a client against the live endpoint requires **three** independent
conditions: ``mode=live``, ``LIVE_TRADING_ENABLED`` set in the environment, and
an explicit ``allow_live=True`` argument. The database kill switch is a fourth,
checked by the caller before every submission. Defaults land on paper.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import aiohttp

from src.core.types import (
    AccountState,
    Fill,
    OrderAck,
    OrderIntent,
    OrderState,
    OrderStatus,
    Position,
    Side,
    TradingMode,
)
from src.execution.base import (
    BrokerBase,
    BrokerError,
    OrderRejectedError,
    TradingHaltedError,
)

logger = logging.getLogger(__name__)

PAPER_BASE_URL = "https://paper-api.alpaca.markets"
LIVE_BASE_URL = "https://api.alpaca.markets"

#: Alpaca order status -> our OrderState.
_STATE_MAP: dict[str, OrderState] = {
    "new": OrderState.SUBMITTED,
    "accepted": OrderState.SUBMITTED,
    "pending_new": OrderState.PENDING,
    "accepted_for_bidding": OrderState.SUBMITTED,
    "partially_filled": OrderState.PARTIALLY_FILLED,
    "filled": OrderState.FILLED,
    "done_for_day": OrderState.EXPIRED,
    "canceled": OrderState.CANCELED,
    "cancelled": OrderState.CANCELED,
    "expired": OrderState.EXPIRED,
    "replaced": OrderState.CANCELED,
    "rejected": OrderState.REJECTED,
    "suspended": OrderState.PENDING,
    "calculated": OrderState.PENDING,
    "stopped": OrderState.PENDING,
}


class AlpacaBroker(BrokerBase):
    """
    Execution against Alpaca's trading API.

    Parameters
    ----------
    key_id, secret_key:
        Credentials. Read from the environment by the caller, never stored in
        the database — ``accounts.credential_ref`` holds the variable *name*.
    mode:
        ``PAPER`` or ``LIVE``. Anything else is refused.
    live_enabled:
        The ``LIVE_TRADING_ENABLED`` environment gate.
    allow_live:
        A second, explicit acknowledgement in code. Both must be true to reach
        the live endpoint, so a misconfigured environment variable alone cannot
        route real orders.
    """

    def __init__(
        self,
        key_id: str,
        secret_key: str,
        mode: TradingMode = TradingMode.PAPER,
        live_enabled: bool = False,
        allow_live: bool = False,
        base_url: str | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        if mode not in (TradingMode.PAPER, TradingMode.LIVE):
            raise ValueError(f"AlpacaBroker supports PAPER or LIVE, got {mode}")
        super().__init__(mode)

        if mode is TradingMode.LIVE:
            self._guard_live(live_enabled)
            if not allow_live:
                raise TradingHaltedError(
                    "Live mode requires allow_live=True in addition to "
                    "LIVE_TRADING_ENABLED. Refusing to place real orders."
                )

        if not key_id or not secret_key:
            raise ValueError("Alpaca credentials are required")

        self._base = (
            base_url
            or (LIVE_BASE_URL if mode is TradingMode.LIVE else PAPER_BASE_URL)
        ).rstrip("/")
        self._headers = {
            "APCA-API-KEY-ID": key_id,
            "APCA-API-SECRET-KEY": secret_key,
            "Content-Type": "application/json",
        }
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._session: aiohttp.ClientSession | None = None

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    async def __aenter__(self) -> AlpacaBroker:
        self._session = aiohttp.ClientSession(
            headers=self._headers, timeout=self._timeout
        )
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    async def _request(
        self, method: str, path: str, **kwargs: Any
    ) -> Any:
        """One HTTP call, with Alpaca's error body surfaced verbatim."""
        owns_session = self._session is None
        session = self._session or aiohttp.ClientSession(
            headers=self._headers, timeout=self._timeout
        )
        url = f"{self._base}{path}"
        try:
            async with session.request(method, url, **kwargs) as response:
                text = await response.text()
                if response.status == 204 or not text:
                    return None
                try:
                    body = await response.json(content_type=None)
                except Exception:  # noqa: BLE001 - non-JSON error body
                    body = {"message": text}

                if response.status >= 400:
                    message = (
                        body.get("message", text) if isinstance(body, dict) else text
                    )
                    if response.status in (403, 422):
                        raise OrderRejectedError(
                            f"Alpaca rejected {method} {path}: {message}"
                        )
                    raise BrokerError(
                        f"Alpaca {method} {path} returned {response.status}: {message}"
                    )
                return body
        except aiohttp.ClientError as exc:
            raise BrokerError(f"Alpaca request failed: {exc}") from exc
        finally:
            if owns_session:
                await session.close()

    # ------------------------------------------------------------------
    # BrokerAdapter surface
    # ------------------------------------------------------------------

    async def get_account(self) -> AccountState:
        data = await self._request("GET", "/v2/account")
        return AccountState(
            cash=Decimal(str(data.get("cash", "0"))),
            equity=Decimal(str(data.get("equity", "0"))),
            buying_power=Decimal(str(data.get("buying_power", "0"))),
            currency=data.get("currency", "USD"),
            is_blocked=bool(
                data.get("trading_blocked") or data.get("account_blocked")
            ),
            # Retained for reporting only. FINRA retired the Pattern Day Trader
            # rule effective 2026-06-04 and Alpaca removed the designation, so
            # no logic keys off this — it may be absent entirely.
            pattern_day_trader=bool(data.get("pattern_day_trader", False)),
        )

    async def get_positions(self) -> dict[str, Position]:
        data = await self._request("GET", "/v2/positions") or []
        out: dict[str, Position] = {}
        for row in data:
            symbol = row["symbol"]
            out[symbol] = Position(
                symbol=symbol,
                qty=Decimal(str(row.get("qty", "0"))),
                avg_entry_price=Decimal(str(row.get("avg_entry_price", "0"))),
            )
        return out

    async def submit(
        self, intent: OrderIntent, client_order_id: str | None = None
    ) -> OrderAck:
        """
        Place one order.

        ``time_in_force`` is always ``day``: Alpaca does not accept ``opg`` or
        ``cls`` for fractional or notional orders, which rules out
        market-on-open staging. The live path therefore submits plain market
        orders shortly after the open, and the backtest's cost model has to
        represent "open plus a few minutes" rather than the official opening
        print. That gap is real and is why the cost model carries a slippage
        term rather than assuming the open.
        """
        payload: dict[str, Any] = {
            "symbol": intent.symbol,
            "side": intent.side.value,
            "type": intent.order_type.value,
            "time_in_force": "day",
        }
        if intent.qty is not None:
            payload["qty"] = _decimal_str(intent.qty)
        else:
            payload["notional"] = _decimal_str(intent.notional)
        if intent.limit_price is not None:
            payload["limit_price"] = _decimal_str(intent.limit_price)
        if client_order_id:
            # Deterministic id => the venue rejects a duplicate, so a retried
            # job cannot double-trade.
            payload["client_order_id"] = client_order_id

        data = await self._request("POST", "/v2/orders", json=payload)
        return OrderAck(
            broker_order_id=str(data["id"]),
            symbol=data.get("symbol", intent.symbol),
            side=intent.side,
            state=_STATE_MAP.get(data.get("status", ""), OrderState.SUBMITTED),
            submitted_at=_parse_ts(data.get("submitted_at")) or _now(),
            raw=data,
        )

    async def get_order(self, broker_order_id: str) -> OrderStatus:
        data = await self._request("GET", f"/v2/orders/{broker_order_id}")
        return self._to_status(data)

    async def get_order_by_client_id(self, client_order_id: str) -> OrderStatus:
        """Look up by our deterministic id — used when reconciling a retry."""
        data = await self._request(
            "GET", "/v2/orders:by_client_order_id",
            params={"client_order_id": client_order_id},
        )
        return self._to_status(data)

    async def cancel_all(self) -> int:
        """
        Cancel every open order. The kill switch's second layer.

        Must not raise on partial success: cancelling four of five orders and
        reporting the fifth is far better than aborting and leaving all five
        live.
        """
        try:
            data = await self._request("DELETE", "/v2/orders") or []
        except BrokerError as exc:
            logger.error("cancel_all failed: %s", exc)
            return 0

        cancelled = 0
        failed = 0
        for row in data if isinstance(data, list) else []:
            if int(row.get("status", 500)) < 300:
                cancelled += 1
            else:
                failed += 1
                logger.error(
                    "Could not cancel order %s: status %s",
                    row.get("id"),
                    row.get("status"),
                )
        if failed:
            logger.error(
                "cancel_all: %d cancelled, %d STILL LIVE — check the venue",
                cancelled,
                failed,
            )
        return cancelled

    async def close_position(self, symbol: str) -> None:
        """
        Liquidate a position entirely.

        Used for exits rather than a notional sell: a notional order cannot
        clear the last fractional remainder, which is how books accumulate
        unsellable $0.03 positions.
        """
        await self._request("DELETE", f"/v2/positions/{symbol}")

    async def get_clock(self) -> dict[str, Any]:
        """
        The venue's own view of market hours.

        Cross-checked against our ``exchange_calendars`` schedule before
        trading. A disagreement means an unscheduled closure our static
        calendar does not know about, and the correct response is to halt
        rather than to trust the calendar.
        """
        return await self._request("GET", "/v2/clock") or {}

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _to_status(self, data: dict[str, Any]) -> OrderStatus:
        filled_qty = Decimal(str(data.get("filled_qty") or "0"))
        avg_price_raw = data.get("filled_avg_price")
        avg_price = Decimal(str(avg_price_raw)) if avg_price_raw else None
        side = Side(data.get("side", "buy"))

        fills: tuple[Fill, ...] = ()
        if filled_qty > 0 and avg_price is not None:
            fills = (
                Fill(
                    broker_order_id=str(data["id"]),
                    symbol=data["symbol"],
                    side=side,
                    qty=filled_qty,
                    price=avg_price,
                    commission=Decimal("0"),  # Alpaca is commission-free
                    filled_at=_parse_ts(data.get("filled_at")) or _now(),
                ),
            )

        return OrderStatus(
            broker_order_id=str(data["id"]),
            symbol=data["symbol"],
            side=side,
            state=_STATE_MAP.get(data.get("status", ""), OrderState.PENDING),
            filled_qty=filled_qty,
            avg_fill_price=avg_price,
            fills=fills,
        )

    async def wait_for_terminal(
        self, broker_order_id: str, timeout: float = 60.0, poll: float = 2.0
    ) -> OrderStatus:
        """Poll until the order settles or the timeout elapses."""
        deadline = asyncio.get_running_loop().time() + timeout
        status = await self.get_order(broker_order_id)
        while not status.is_terminal:
            if asyncio.get_running_loop().time() >= deadline:
                logger.warning(
                    "Order %s still %s after %.0fs", broker_order_id,
                    status.state.value, timeout,
                )
                return status
            await asyncio.sleep(poll)
            status = await self.get_order(broker_order_id)
        return status


def _decimal_str(value: Decimal | None) -> str:
    """
    Serialise a Decimal for the wire in plain fixed-point notation.

    ``Decimal.normalize()`` alone is a trap: it turns ``Decimal("10")`` into
    ``Decimal("1E+1")``, whose ``str()`` is ``"1E+1"``. Every round quantity —
    10 shares, 100 shares — would reach the venue in scientific notation.
    ``format(..., "f")`` after normalising strips trailing zeros while
    guaranteeing fixed-point, so 10 stays "10" and 0.000000001 stays
    "0.000000001" rather than "1E-9".
    """
    if value is None:
        return "0"
    return format(value.normalize(), "f")


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def _now() -> datetime:
    return datetime.now(UTC)
