"""
alpaca_server.py
----------------
A minimal stand-in for Alpaca's trading API.

Exists so :class:`~src.execution.alpaca.AlpacaBroker` can be tested over real
HTTP — real serialisation, real status codes, real error bodies — rather than
against mocks of our own code. A mocked ``aiohttp`` would only prove the mock
matches our expectation of Alpaca, which is exactly the assumption most worth
testing.

It models the behaviours that actually bite:

- ``client_order_id`` uniqueness, which is what makes a retried job safe
- notional-vs-qty order forms
- rejection of ``opg``/``cls`` on fractional and notional orders
- partial failure from ``DELETE /v2/orders``
- insufficient buying power
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from aiohttp import web

KEY_ID = "test-key-id"
SECRET_KEY = "test-secret-key"


class FakeAlpaca:
    """In-memory Alpaca. Start with :meth:`start`, stop with :meth:`stop`."""

    def __init__(
        self,
        cash: str = "100000",
        equity: str = "100000",
        market_open: bool = True,
    ) -> None:
        self.cash = Decimal(cash)
        self.equity = Decimal(equity)
        self.market_open = market_open
        self.positions: dict[str, dict[str, Any]] = {}
        self.orders: dict[str, dict[str, Any]] = {}
        self.client_order_ids: set[str] = set()
        self.submitted: list[dict[str, Any]] = []

        #: When set, DELETE /v2/orders reports these ids as failing to cancel,
        #: so the adapter's partial-failure handling can be exercised.
        self.uncancellable: set[str] = set()
        #: When set, order submission is refused with insufficient buying power.
        self.reject_all = False

        self._runner: web.AppRunner | None = None
        self.port = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> str:
        app = web.Application(middlewares=[self._auth_middleware])
        app.router.add_get("/v2/account", self._account)
        app.router.add_get("/v2/positions", self._get_positions)
        app.router.add_delete("/v2/positions/{symbol}", self._close_position)
        app.router.add_post("/v2/orders", self._submit_order)
        app.router.add_get("/v2/orders/{order_id}", self._get_order)
        app.router.add_get(
            "/v2/orders:by_client_order_id", self._get_order_by_client_id
        )
        app.router.add_delete("/v2/orders", self._cancel_all)
        app.router.add_get("/v2/clock", self._clock)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
        return f"http://127.0.0.1:{self.port}"

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    # ------------------------------------------------------------------
    # Middleware
    # ------------------------------------------------------------------

    @web.middleware
    async def _auth_middleware(self, request: web.Request, handler: Any) -> Any:
        """Reject bad credentials the way Alpaca does, with a 401."""
        if (
            request.headers.get("APCA-API-KEY-ID") != KEY_ID
            or request.headers.get("APCA-API-SECRET-KEY") != SECRET_KEY
        ):
            return web.json_response(
                {"message": "access key verification failed"}, status=401
            )
        return await handler(request)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _account(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "cash": str(self.cash),
                "equity": str(self.equity),
                "buying_power": str(self.cash),
                "currency": "USD",
                "trading_blocked": False,
                "account_blocked": False,
            }
        )

    async def _get_positions(self, request: web.Request) -> web.Response:
        return web.json_response(list(self.positions.values()))

    async def _close_position(self, request: web.Request) -> web.Response:
        symbol = request.match_info["symbol"]
        if symbol not in self.positions:
            return web.json_response({"message": "position not found"}, status=404)
        del self.positions[symbol]
        return web.json_response({"status": "closed"})

    async def _submit_order(self, request: web.Request) -> web.Response:
        body = await request.json()
        self.submitted.append(body)

        if self.reject_all:
            return web.json_response(
                {"message": "insufficient buying power"}, status=403
            )

        tif = body.get("time_in_force", "day")
        is_fractional_or_notional = "notional" in body or (
            "qty" in body and Decimal(str(body["qty"])) % 1 != 0
        )
        if is_fractional_or_notional and tif != "day":
            # Alpaca's real constraint: fractional/notional are DAY-only.
            return web.json_response(
                {
                    "message": (
                        "time_in_force must be 'day' for fractional or "
                        "notional orders"
                    )
                },
                status=422,
            )

        client_order_id = body.get("client_order_id")
        if client_order_id:
            if client_order_id in self.client_order_ids:
                return web.json_response(
                    {"message": "client_order_id must be unique"}, status=422
                )
            self.client_order_ids.add(client_order_id)

        order_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        order = {
            "id": order_id,
            "client_order_id": client_order_id or order_id,
            "symbol": body["symbol"],
            "side": body["side"],
            "type": body.get("type", "market"),
            "time_in_force": tif,
            "qty": body.get("qty"),
            "notional": body.get("notional"),
            "status": "accepted",
            "submitted_at": now,
            "filled_qty": "0",
            "filled_avg_price": None,
            "filled_at": None,
        }
        self.orders[order_id] = order
        return web.json_response(order)

    async def _get_order(self, request: web.Request) -> web.Response:
        order = self.orders.get(request.match_info["order_id"])
        if order is None:
            return web.json_response({"message": "order not found"}, status=404)
        return web.json_response(order)

    async def _get_order_by_client_id(self, request: web.Request) -> web.Response:
        wanted = request.query.get("client_order_id")
        for order in self.orders.values():
            if order.get("client_order_id") == wanted:
                return web.json_response(order)
        return web.json_response({"message": "order not found"}, status=404)

    async def _cancel_all(self, request: web.Request) -> web.Response:
        """
        Alpaca returns 207 with a per-order status array, so a partial failure
        is normal and must be handled rather than treated as total success.
        """
        results = []
        for order_id, order in list(self.orders.items()):
            if order["status"] in {"filled", "canceled"}:
                continue
            if order_id in self.uncancellable:
                results.append({"id": order_id, "status": 500})
                continue
            order["status"] = "canceled"
            results.append({"id": order_id, "status": 204})
        return web.json_response(results, status=207)

    async def _clock(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "is_open": self.market_open,
                "next_open": "2026-08-03T13:30:00Z",
                "next_close": "2026-08-03T20:00:00Z",
            }
        )

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    def fill(self, order_id: str, price: str, qty: str | None = None) -> None:
        """Mark an order filled, as the venue would once it executes."""
        order = self.orders[order_id]
        filled_qty = qty or order.get("qty")
        if filled_qty is None and order.get("notional"):
            filled_qty = str(Decimal(order["notional"]) / Decimal(price))
        order["status"] = "filled"
        order["filled_qty"] = str(filled_qty)
        order["filled_avg_price"] = price
        order["filled_at"] = datetime.now(UTC).isoformat()

        symbol = order["symbol"]
        signed = Decimal(str(filled_qty)) * (
            Decimal("1") if order["side"] == "buy" else Decimal("-1")
        )
        existing = Decimal(self.positions.get(symbol, {}).get("qty", "0"))
        new_qty = existing + signed
        if new_qty == 0:
            self.positions.pop(symbol, None)
        else:
            self.positions[symbol] = {
                "symbol": symbol,
                "qty": str(new_qty),
                "avg_entry_price": price,
                "market_value": str(new_qty * Decimal(price)),
            }

    def set_position(self, symbol: str, qty: str, price: str) -> None:
        self.positions[symbol] = {
            "symbol": symbol,
            "qty": qty,
            "avg_entry_price": price,
            "market_value": str(Decimal(qty) * Decimal(price)),
        }
