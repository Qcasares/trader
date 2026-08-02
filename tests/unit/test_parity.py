"""
test_parity.py
--------------
**The test that justifies the architecture.**

Claim: given identical market history and an identical portfolio, the backtest
path and the live path emit byte-identical orders. If this cannot be made to
pass, "one driver, two injected dependencies" is a fiction and the backtest is
not a prediction of the live system.

The two paths differ only in the injected ``BrokerAdapter``:

- backtest -> ``SimulatedBroker`` (in-memory ledger)
- live     -> ``FakeLiveBroker`` (mimics an async venue; records submissions)

Everything between the panel and the ``OrderIntent`` list is shared code, so
any divergence here is a real bug in the shared path rather than a test
artifact.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from src.core.calendar import sessions as nyse_sessions
from src.core.clock import SimClock
from src.core.orders import RebalanceConstraints
from src.core.panel import PricePanel
from src.core.types import (
    AccountState,
    CostModel,
    OrderAck,
    OrderIntent,
    OrderState,
    OrderStatus,
    Position,
    TradingMode,
)
from src.data import SyntheticSource, bars_to_rows
from src.engine import Driver, DriverConfig, client_order_id
from src.execution.base import BrokerBase
from src.execution.simulated import SimulatedBroker
from src.strategies import build_strategy

UNIVERSE = ["SPY", "EFA", "IEF", "VNQ", "GSG"]
START = date(2005, 1, 1)
END = date(2015, 12, 31)


class FakeLiveBroker(BrokerBase):
    """
    Stands in for a real venue.

    Holds no ledger: it is *told* the account and positions, exactly as a live
    adapter is told them by the broker's API. It records what was submitted so
    the test can compare intents.
    """

    def __init__(
        self,
        cash: Decimal,
        equity: Decimal,
        positions: dict[str, Position],
    ) -> None:
        super().__init__(TradingMode.PAPER)
        self._cash = cash
        self._equity = equity
        self._positions = dict(positions)
        self.submitted: list[OrderIntent] = []
        self._seq = 0

    def set_state(
        self, cash: Decimal, equity: Decimal, positions: dict[str, Position]
    ) -> None:
        self._cash = cash
        self._equity = equity
        self._positions = dict(positions)

    async def get_account(self) -> AccountState:
        return AccountState(
            cash=self._cash, equity=self._equity, buying_power=self._cash
        )

    async def get_positions(self) -> dict[str, Position]:
        return {s: p for s, p in self._positions.items() if not p.is_flat}

    async def submit(self, intent: OrderIntent) -> OrderAck:
        self._seq += 1
        self.submitted.append(intent)
        return OrderAck(
            broker_order_id=f"fake-{self._seq}",
            symbol=intent.symbol,
            side=intent.side,
            state=OrderState.SUBMITTED,
            submitted_at=datetime.now(UTC),
        )

    async def get_order(self, broker_order_id: str) -> OrderStatus:  # pragma: no cover
        raise NotImplementedError

    async def cancel_all(self) -> int:
        return 0


@pytest.fixture(scope="module")
def panel() -> PricePanel:
    bars = SyntheticSource().fetch(UNIVERSE, START, END)
    return PricePanel.from_bars(bars_to_rows(bars))


@pytest.fixture(scope="module")
def trading_sessions() -> list[date]:
    return nyse_sessions(START, END)


def _config() -> DriverConfig:
    return DriverConfig(
        constraints=RebalanceConstraints(min_trade_usd=Decimal("25")),
        run_ref="parity",
    )


class TestBacktestLiveParity:
    """Identical inputs must produce identical orders on both paths."""

    def test_identical_order_intents_across_full_history(
        self, panel: PricePanel, trading_sessions: list[date]
    ) -> None:
        """
        Run the whole history on the backtest path, then replay each rebalance
        session on the live path seeded with the backtest's own portfolio
        state. Every emitted order must match exactly.
        """
        strategy_bt = build_strategy("asset_class_trend_following")
        clock = SimClock(trading_sessions)
        sim = SimulatedBroker(
            initial_cash=100_000, cost_model=CostModel(slippage_bps=5.0)
        )
        driver_bt = Driver(strategy_bt, sim, clock, _config())

        async def run_backtest() -> list:
            records = []
            for session in trading_sessions:
                records.append(await driver_bt.step(panel, session))
                clock.advance()
            return records

        records = asyncio.run(run_backtest())
        rebalances = [r for r in records if r.rebalanced]
        assert len(rebalances) > 100, "expected a monthly rebalance over 11 years"

        # Replay each rebalance on the "live" path.
        mismatches: list[str] = []
        compared = 0
        for record in rebalances:
            strategy_live = build_strategy("asset_class_trend_following")
            fake = FakeLiveBroker(
                cash=record.cash,
                equity=record.equity,
                positions=_positions_at(records, record.session),
            )
            live_clock = SimClock([record.session])
            driver_live = Driver(strategy_live, fake, live_clock, _config())

            asyncio.run(driver_live.step(panel, record.session))

            if fake.submitted != record.intents:
                mismatches.append(
                    f"{record.session}: backtest={_fmt(record.intents)} "
                    f"live={_fmt(fake.submitted)}"
                )
            compared += 1

        assert compared > 100
        assert not mismatches, (
            f"{len(mismatches)} of {compared} rebalance sessions diverged "
            f"between backtest and live:\n" + "\n".join(mismatches[:5])
        )

    def test_repeated_runs_are_byte_identical(
        self, panel: PricePanel, trading_sessions: list[date]
    ) -> None:
        """Determinism: the same backtest twice must give the same orders."""
        sessions = trading_sessions[:600]

        def run() -> list[tuple]:
            strategy = build_strategy("asset_class_trend_following")
            clock = SimClock(sessions)
            broker = SimulatedBroker(initial_cash=100_000)
            driver = Driver(strategy, broker, clock, _config())

            async def go() -> list[tuple]:
                out = []
                for session in sessions:
                    record = await driver.step(panel, session)
                    out.append((record.session, tuple(record.intents)))
                    clock.advance()
                return out

            return asyncio.run(go())

        assert run() == run()

    def test_client_order_ids_are_deterministic_and_unique(self) -> None:
        """
        Deterministic IDs give idempotency: a retried live job cannot
        double-trade, because the venue rejects a duplicate client order ID.
        """
        first = client_order_id("run7", date(2020, 3, 2), "SPY")
        assert first == "run7:20200302:SPY"
        assert first == client_order_id("run7", date(2020, 3, 2), "SPY")
        assert first != client_order_id("run7", date(2020, 4, 1), "SPY")
        assert first != client_order_id("run8", date(2020, 3, 2), "SPY")


def _positions_at(records: list, session: date) -> dict[str, Position]:
    """
    Reconstruct holdings as they stood when ``session``'s decision was made.

    Fills from every earlier session are applied; the decision session's own
    fills settled at its open and so are included too.
    """
    holdings: dict[str, Decimal] = {}
    entry: dict[str, Decimal] = {}
    for record in records:
        if record.session > session:
            break
        for fill in record.fills:
            sign = Decimal("1") if fill.side.value == "buy" else Decimal("-1")
            prior = holdings.get(fill.symbol, Decimal("0"))
            holdings[fill.symbol] = prior + sign * fill.qty
            if sign > 0:
                prior_cost = prior * entry.get(fill.symbol, Decimal("0"))
                total = prior + fill.qty
                entry[fill.symbol] = (
                    (prior_cost + fill.qty * fill.price) / total
                    if total > 0
                    else Decimal("0")
                )
    return {
        symbol: Position(symbol, qty, entry.get(symbol, Decimal("0")))
        for symbol, qty in holdings.items()
        if qty != 0
    }


def _fmt(intents: list[OrderIntent]) -> str:
    return "[" + ", ".join(f"{i.side.value}:{i.symbol}:{i.qty}" for i in intents) + "]"
