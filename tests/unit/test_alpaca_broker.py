"""
test_alpaca_broker.py
---------------------
``AlpacaBroker`` exercised over real HTTP against a fake venue.

Nothing here is mocked at the client boundary: the adapter opens a real
session, serialises a real payload, and parses a real response. Mocking
``aiohttp`` would only confirm the mock matches our assumptions about Alpaca —
and those assumptions are the part most likely to be wrong.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

pytest.importorskip("aiohttp")

from src.core.types import (  # noqa: E402
    OrderIntent,
    OrderState,
    Side,
    TradingMode,
)
from src.execution.alpaca import AlpacaBroker  # noqa: E402
from src.execution.base import (  # noqa: E402
    BrokerError,
    OrderRejectedError,
    TradingHaltedError,
)
from tests.fakes.alpaca_server import KEY_ID, SECRET_KEY, FakeAlpaca  # noqa: E402


async def _with_server(coro, **server_kwargs):
    """Run ``coro(broker, server)`` against a freshly started fake venue."""
    server = FakeAlpaca(**server_kwargs)
    base_url = await server.start()
    try:
        async with AlpacaBroker(
            KEY_ID, SECRET_KEY, mode=TradingMode.PAPER, base_url=base_url
        ) as broker:
            return await coro(broker, server)
    finally:
        await server.stop()


def run(coro, **server_kwargs):
    return asyncio.run(_with_server(coro, **server_kwargs))


class TestLiveGating:
    """Reaching the live endpoint must require several independent yeses."""

    def test_paper_is_the_default(self) -> None:
        broker = AlpacaBroker(KEY_ID, SECRET_KEY)
        assert broker.mode is TradingMode.PAPER
        assert "paper-api" in broker._base

    def test_live_refused_without_the_environment_gate(self) -> None:
        with pytest.raises(TradingHaltedError, match="LIVE_TRADING_ENABLED"):
            AlpacaBroker(
                KEY_ID, SECRET_KEY, mode=TradingMode.LIVE, live_enabled=False
            )

    def test_live_refused_without_explicit_acknowledgement(self) -> None:
        """
        The env gate alone is not enough. A stray LIVE_TRADING_ENABLED=true in
        a deployment must not be sufficient to route real orders.
        """
        with pytest.raises(TradingHaltedError, match="allow_live"):
            AlpacaBroker(
                KEY_ID,
                SECRET_KEY,
                mode=TradingMode.LIVE,
                live_enabled=True,
                allow_live=False,
            )

    def test_live_allowed_only_with_both(self) -> None:
        broker = AlpacaBroker(
            KEY_ID,
            SECRET_KEY,
            mode=TradingMode.LIVE,
            live_enabled=True,
            allow_live=True,
        )
        assert broker._base.endswith("api.alpaca.markets")
        assert "paper" not in broker._base

    def test_missing_credentials_rejected(self) -> None:
        with pytest.raises(ValueError, match="credentials"):
            AlpacaBroker("", "")

    def test_backtest_mode_is_not_a_venue(self) -> None:
        with pytest.raises(ValueError):
            AlpacaBroker(KEY_ID, SECRET_KEY, mode=TradingMode.BACKTEST)


class TestAccountAndPositions:
    def test_reads_account(self) -> None:
        async def check(broker, server):
            return await broker.get_account()

        account = run(check)
        assert account.cash == Decimal("100000")
        assert account.equity == Decimal("100000")
        assert account.currency == "USD"

    def test_reads_positions(self) -> None:
        async def check(broker, server):
            server.set_position("SPY", "10.5", "400")
            return await broker.get_positions()

        positions = run(check)
        assert positions["SPY"].qty == Decimal("10.5")
        assert positions["SPY"].avg_entry_price == Decimal("400")

    def test_bad_credentials_surface_as_a_broker_error(self) -> None:
        async def check():
            server = FakeAlpaca()
            base_url = await server.start()
            try:
                async with AlpacaBroker(
                    "wrong", "wrong", base_url=base_url
                ) as broker:
                    with pytest.raises(BrokerError):
                        await broker.get_account()
            finally:
                await server.stop()

        asyncio.run(check())


class TestOrderSubmission:
    def test_submits_a_quantity_order(self) -> None:
        async def check(broker, server):
            intent = OrderIntent(symbol="SPY", side=Side.BUY, qty=Decimal("10"))
            ack = await broker.submit(intent)
            return ack, server.submitted[-1]

        ack, payload = run(check)
        assert ack.state is OrderState.SUBMITTED
        assert payload["symbol"] == "SPY"
        assert payload["side"] == "buy"
        assert payload["qty"] == "10"
        # Alpaca rejects opg/cls for fractional and notional orders, so the
        # adapter always sends day and the backtest models "shortly after the
        # open" rather than the opening print.
        assert payload["time_in_force"] == "day"

    def test_submits_a_notional_order(self) -> None:
        async def check(broker, server):
            intent = OrderIntent(
                symbol="SPY", side=Side.BUY, notional=Decimal("5000.00")
            )
            await broker.submit(intent)
            return server.submitted[-1]

        payload = run(check)
        # Trailing zeros are stripped; the amount is identical.
        assert Decimal(payload["notional"]) == Decimal("5000.00")
        assert "qty" not in payload

    @pytest.mark.parametrize(
        "qty",
        ["10", "100", "1000", "0.000000001", "10.123456789", "1"],
    )
    def test_quantities_never_serialise_as_scientific_notation(
        self, qty: str
    ) -> None:
        """
        Regression: Decimal("10").normalize() is Decimal("1E+1"), and str() of
        that is "1E+1". Every round share count would have reached the venue in
        scientific notation. Only a real serialisation boundary catches this.
        """

        async def check(broker, server):
            await broker.submit(
                OrderIntent(symbol="SPY", side=Side.BUY, qty=Decimal(qty))
            )
            return server.submitted[-1]["qty"]

        wire = run(check)
        assert "E" not in wire.upper(), f"{wire!r} is scientific notation"
        assert Decimal(wire) == Decimal(qty)

    def test_deterministic_client_order_id_blocks_a_double_trade(self) -> None:
        """
        The idempotency property. A retried job resubmits the same id and the
        venue refuses it, so the position cannot be doubled.
        """

        async def check(broker, server):
            intent = OrderIntent(symbol="SPY", side=Side.BUY, qty=Decimal("10"))
            await broker.submit(intent, client_order_id="run1:20260731:SPY")
            with pytest.raises(OrderRejectedError, match="unique"):
                await broker.submit(intent, client_order_id="run1:20260731:SPY")
            return len(server.orders)

        assert run(check) == 1

    def test_insufficient_buying_power_is_a_rejection_not_a_crash(self) -> None:
        async def check(broker, server):
            server.reject_all = True
            intent = OrderIntent(symbol="SPY", side=Side.BUY, qty=Decimal("10"))
            with pytest.raises(OrderRejectedError, match="buying power"):
                await broker.submit(intent)

        run(check)

    def test_fill_is_reported_with_price_and_quantity(self) -> None:
        async def check(broker, server):
            intent = OrderIntent(symbol="SPY", side=Side.BUY, qty=Decimal("10"))
            ack = await broker.submit(intent)
            server.fill(ack.broker_order_id, price="401.25")
            return await broker.get_order(ack.broker_order_id)

        status = run(check)
        assert status.state is OrderState.FILLED
        assert status.is_terminal
        assert status.filled_qty == Decimal("10")
        assert status.avg_fill_price == Decimal("401.25")
        assert len(status.fills) == 1
        assert status.fills[0].price == Decimal("401.25")

    def test_lookup_by_client_order_id(self) -> None:
        async def check(broker, server):
            intent = OrderIntent(symbol="SPY", side=Side.BUY, qty=Decimal("3"))
            await broker.submit(intent, client_order_id="run9:20260731:SPY")
            return await broker.get_order_by_client_id("run9:20260731:SPY")

        assert run(check).symbol == "SPY"


class TestKillSwitchSecondLayer:
    """
    Cancelling in-flight orders. The database flag stops *new* orders; this is
    what deals with the ones already at the venue. Neither alone is enough.
    """

    def test_cancel_all_cancels_open_orders(self) -> None:
        async def check(broker, server):
            for symbol in ("SPY", "EFA", "IEF"):
                await broker.submit(
                    OrderIntent(symbol=symbol, side=Side.BUY, qty=Decimal("1"))
                )
            cancelled = await broker.cancel_all()
            states = {o["status"] for o in server.orders.values()}
            return cancelled, states

        cancelled, states = run(check)
        assert cancelled == 3
        assert states == {"canceled"}

    def test_partial_cancellation_reports_what_succeeded(self) -> None:
        """
        Cancelling four of five and reporting the fifth beats aborting and
        leaving all five live.
        """

        async def check(broker, server):
            acks = [
                await broker.submit(
                    OrderIntent(symbol=s, side=Side.BUY, qty=Decimal("1"))
                )
                for s in ("SPY", "EFA", "IEF")
            ]
            server.uncancellable = {acks[1].broker_order_id}
            cancelled = await broker.cancel_all()
            still_open = sum(
                1 for o in server.orders.values() if o["status"] == "accepted"
            )
            return cancelled, still_open

        cancelled, still_open = run(check)
        assert cancelled == 2
        assert still_open == 1

    def test_cancel_all_returns_zero_rather_than_raising_on_failure(self) -> None:
        """A kill switch that throws is a kill switch that did not fire."""

        async def check():
            broker = AlpacaBroker(
                KEY_ID, SECRET_KEY, base_url="http://127.0.0.1:1"
            )
            async with broker:
                assert await broker.cancel_all() == 0

        asyncio.run(check())

    def test_close_position_liquidates_entirely(self) -> None:
        """
        Exits use close_position, not a notional sell — a notional order cannot
        clear the last fractional remainder, which is how books accumulate
        unsellable dust.
        """

        async def check(broker, server):
            server.set_position("SPY", "10.123456789", "400")
            await broker.close_position("SPY")
            return await broker.get_positions()

        assert run(check) == {}


class TestClockCrossCheck:
    def test_reads_venue_clock(self) -> None:
        async def check(broker, server):
            return await broker.get_clock()

        clock = run(check)
        assert clock["is_open"] is True

    def test_closed_market_is_visible(self) -> None:
        """
        Our calendar cannot know about an unscheduled closure. Disagreement
        between it and the venue's clock is a reason to halt, not to proceed.
        """

        async def check(broker, server):
            return await broker.get_clock()

        assert run(check, market_open=False)["is_open"] is False
