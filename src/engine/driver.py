"""
driver.py
---------
The one driver.

There is no ``BacktestDriver`` and no ``LiveDriver``. There is a single
:class:`Driver` with an injected broker and clock:

- backtest -> ``Driver(strategy, SimulatedBroker(...), SimClock(sessions))``
- paper    -> ``Driver(strategy, AlpacaBroker(...), RealClock())``

"The backtest is the live path with two objects swapped" is a much stronger
correctness claim than "both call the same functions", and it is what
``tests/unit/test_parity.py`` pins down.

Decision lag
~~~~~~~~~~~~
Targets are computed from session T's close and executed at session T+1's open.
This is not a modelling nicety — it is forced by reality. Live at 15:45 ET you
do not yet know today's official close, so any backtest that decides and fills
on the same bar is describing a system you cannot build. ``SimulatedBroker``
enforces it by queueing rather than filling, so the mistake is unavailable
rather than merely discouraged.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from src.core.clock import Clock
from src.core.orders import RebalanceConstraints, weights_to_orders
from src.core.panel import PricePanel
from src.core.risk import RiskEvent, RiskLimits, RiskState, apply_risk
from src.core.types import (
    Fill,
    OrderIntent,
    PortfolioState,
    TargetWeights,
    quantize_usd,
)
from src.execution.base import BrokerAdapter, TradingHaltedError
from src.execution.simulated import SimulatedBroker
from src.strategies.base import Strategy

logger = logging.getLogger(__name__)


def client_order_id(run_ref: str, session: date, symbol: str) -> str:
    """
    Deterministic order identifier.

    Buys three things at once: idempotency on the live path (a broker rejects a
    duplicate client order ID, so a retried job cannot double-trade), a natural
    join key for diffing a live decision against its shadow backtest, and an
    audit trail a human can read.
    """
    return f"{run_ref}:{session:%Y%m%d}:{symbol}"


@dataclass(frozen=True, slots=True)
class DriverConfig:
    """Execution settings that are not the strategy's business."""

    constraints: RebalanceConstraints = field(default_factory=RebalanceConstraints)

    #: Sessions between deciding and executing. 1 = decide on close, fill next
    #: open. Zero is only legitimate in tests that deliberately probe the
    #: same-bar case; it is not achievable live.
    decision_lag_sessions: int = 1

    #: Stamped into every client order ID.
    run_ref: str = "run"

    #: The shared risk gate. Defaults are permissive, so an unconfigured run
    #: measures the strategy rather than the gate.
    risk_limits: RiskLimits = field(default_factory=RiskLimits)


@dataclass(slots=True)
class SessionRecord:
    """Everything that happened on one session. One row of the audit trail."""

    session: date
    equity: Decimal
    cash: Decimal
    fills: list[Fill] = field(default_factory=list)
    intents: list[OrderIntent] = field(default_factory=list)
    targets: TargetWeights | None = None
    #: What the strategy asked for, before the risk gate. Keeping both makes it
    #: visible when a limit changed the answer rather than merely being checked.
    raw_targets: TargetWeights | None = None
    risk_events: tuple[RiskEvent, ...] = ()
    rebalanced: bool = False
    rationale: str = ""
    halted: bool = False

    @property
    def invested_value(self) -> Decimal:
        return quantize_usd(self.equity - self.cash)


class Driver:
    """
    Advances a strategy one session at a time against a broker.

    The driver owns the *sequence* — fill, mark, decide, stage — and nothing
    else. It computes no signals and applies no strategy logic.
    """

    def __init__(
        self,
        strategy: Strategy,
        broker: BrokerAdapter,
        clock: Clock,
        config: DriverConfig | None = None,
    ) -> None:
        self.strategy = strategy
        self.broker = broker
        self.clock = clock
        self.config = config or DriverConfig()
        self._last_rebalance: date | None = None
        self._logger = logging.getLogger(f"driver.{strategy.name}")

    @property
    def last_rebalance(self) -> date | None:
        return self._last_rebalance

    # ------------------------------------------------------------------
    # One session
    # ------------------------------------------------------------------

    async def step(
        self,
        panel: PricePanel,
        session: date,
        halted: bool = False,
    ) -> SessionRecord:
        """
        Process a single session.

        Order of operations matters and is fixed:

        1. Fill anything staged by the *previous* session, at today's open.
        2. Mark the book to today's close.
        3. Read portfolio state.
        4. If it is a rebalance session, compute targets and stage orders.

        ``halted`` is the kill switch. When set, staged orders are cancelled
        and nothing new is submitted — but steps 1-3 still run, so the equity
        curve stays continuous and the book is still marked. A kill switch that
        also stopped accounting would leave you blind at the worst moment.
        """
        open_prices = self._prices(panel, session, "open")
        close_prices = self._prices(panel, session, "close")

        # 1. Execute what was staged yesterday, at today's open.
        fills = await self._settle(open_prices, session)

        # 2 & 3. Mark and read state.
        state = await self._portfolio_state(close_prices, session)

        record = SessionRecord(
            session=session,
            equity=state.equity,
            cash=state.cash,
            fills=fills,
            halted=halted,
        )

        if halted:
            cancelled = await self.broker.cancel_all()
            record.rationale = (
                f"Trading halted; cancelled {cancelled} staged order(s)."
            )
            return record

        # 4. Decide.
        if not self.strategy.should_rebalance(session, self._last_rebalance):
            return record

        raw_targets = self.strategy.target_weights(panel.at(session), state, session)

        # The shared gate. Identical on both paths — a backtest that measured
        # an ungated strategy would not describe the live system.
        gated = apply_risk(
            raw_targets,
            state,
            self._risk_state(session, close_prices, halted=False),
            self.config.risk_limits,
        )
        targets = gated.weights
        intents = weights_to_orders(
            state=state,
            targets=targets,
            prices=close_prices,
            constraints=self.config.constraints,
        )

        record.rebalanced = True
        record.targets = targets
        record.raw_targets = raw_targets
        record.risk_events = gated.events
        record.intents = intents
        record.rationale = targets.rationale
        self._last_rebalance = session

        for intent in intents:
            try:
                await self.broker.submit(intent)
            except TradingHaltedError:
                self._logger.warning(
                    "%s: broker halted mid-submission; %d order(s) not staged",
                    session,
                    len(intents) - intents.index(intent),
                )
                record.halted = True
                break

        return record

    # ------------------------------------------------------------------
    # Full backtest
    # ------------------------------------------------------------------

    async def run(
        self,
        panel: PricePanel,
        sessions: Sequence[date],
    ) -> list[SessionRecord]:
        """
        Walk every session in order, returning one record each.

        Sessions before the strategy's warm-up is satisfied are still stepped —
        they mark the book and keep the equity curve continuous — but the
        strategy will naturally decline to allocate, because
        ``PricePanel.is_available`` reports insufficient history.
        """
        records: list[SessionRecord] = []
        for session in sessions:
            records.append(await self.step(panel, session))
        return records

    def effective_start(
        self, panel: PricePanel, sessions: Sequence[date]
    ) -> date | None:
        """
        First session on which the strategy's *whole* universe is tradeable.

        Reported alongside every metric. Without it, a backtest of the five
        asset-class ETFs starting in 2000 quietly reports the Sharpe of a
        single-asset SPY timing strategy for its first several years, because
        EFA/IEF/VNQ/GSG had not listed yet.
        """
        need = self.strategy.min_history_per_symbol
        universe = self.strategy.universe()
        for session in sessions:
            sliced = panel.at(session)
            if all(sliced.is_available(s, min_history=need) for s in universe):
                return session
        return None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _settle(
        self, open_prices: dict[str, float], session: date
    ) -> list[Fill]:
        """Fill staged orders. Only the simulated broker settles synchronously."""
        if isinstance(self.broker, SimulatedBroker):
            self.broker.mark(open_prices)
            return self.broker.execute_pending(open_prices, at=self.clock.now())
        # Live brokers fill asynchronously; the reconciliation job records the
        # fills. Nothing to do here.
        return []

    async def _portfolio_state(
        self, close_prices: dict[str, float], session: date
    ) -> PortfolioState:
        if isinstance(self.broker, SimulatedBroker):
            self.broker.mark(close_prices)
        account = await self.broker.get_account()
        positions = await self.broker.get_positions()
        return PortfolioState(
            cash=account.cash,
            positions=positions,
            equity=account.equity,
            as_of=session,
        )

    def _risk_state(
        self, session: date, prices: dict[str, float], halted: bool
    ) -> RiskState:
        """Assemble what the gate needs beyond the portfolio itself."""
        return RiskState(
            session=session,
            current_prices={
                symbol: Decimal(str(price)) for symbol, price in prices.items()
            },
            kill_switch_active=halted,
            now=self.clock.now(),
        )

    def _prices(
        self, panel: PricePanel, session: date, field_name: str
    ) -> dict[str, float]:
        """
        Raw (unadjusted) prices for one session, used for execution and marking.

        Signals use adjusted closes; money uses raw prices. Mixing them would
        make the ledger disagree with the broker by the cumulative dividend
        adjustment, which on IEF or VNQ is a large number over 20 years.
        """
        out: dict[str, float] = {}
        for symbol in self.strategy.universe():
            try:
                value = panel.value_on(symbol, session, field_name)
            except KeyError:
                continue
            if value is not None and value > 0:
                out[symbol] = value
        return out
