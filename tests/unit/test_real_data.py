"""
test_real_data.py
-----------------
The engine, run on prices a market actually printed.

Everything else in this suite runs on ``SyntheticSource``. That was an honest
choice — the generator labels itself synthetic everywhere it appears — but it
means the ingest -> ``PricePanel`` -> ``Driver`` -> risk gate -> metrics path
had never been exercised on data that could surprise it. A generator you wrote
cannot violate an assumption you did not know you had made.

``tests/fixtures/cryptocom_candles.json`` holds 24 daily candles for four spot
pairs, captured verbatim from the Crypto.com Exchange public API with their
provenance recorded alongside. These are real observed prices.

What this file does and does not establish
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
It establishes that the machinery is correct on real inputs: bars round-trip
without silent rescaling, the look-ahead guard holds, decision lag is real,
the ledger balances, and the backtest and live paths emit identical orders.

It establishes **nothing whatsoever about any strategy**. Twenty-four sessions
is seven weeks. The Sharpe standard error over that window is roughly ±1.4, so
any Sharpe it produces is indistinguishable from zero and from most other
numbers. :func:`test_metrics_refuse_to_call_a_seven_week_sharpe_significant`
asserts the engine says so itself rather than leaving it to a reader.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from src.core.calendar import sessions as nyse_sessions
from src.core.clock import SimClock
from src.core.panel import LookAheadError, PricePanel
from src.core.risk import RiskCode, RiskLimits, Severity
from src.core.types import CostModel, TradingMode
from src.data import CryptoComSource, bars_to_rows, continuous_sessions
from src.engine import Driver, DriverConfig
from src.engine.metrics import metrics_from_records
from src.execution.simulated import SimulatedBroker
from src.strategies import build_strategy

# Imported rather than re-implemented: the live-path stand-in and the
# position reconstruction must be the same ones the synthetic parity test
# uses, or "parity holds on real data" would be a claim about a different fake.
from tests.unit.test_parity import FakeLiveBroker, _positions_at

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "cryptocom_candles.json"

UNIVERSE = ["BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT"]
FIRST_SESSION = date(2026, 7, 8)
LAST_SESSION = date(2026, 7, 31)

#: A market that never closes. Used for annualisation, and asserted rather
#: than assumed by ``test_continuous_sessions_include_the_weekend``.
CRYPTO_PERIODS_PER_YEAR = 365

#: Short enough to produce signals inside a 24-session window. The reference
#: 210 is impossible here, which is precisely why no strategy conclusion can
#: be drawn from this fixture.
SMA_PERIOD = 5

#: A crypto taker fee is nothing like a commission-free equity broker: 0.075%
#: per side. Used where the size of the cost matters to what is being tested.
_CRYPTO_COSTS = CostModel(commission_pct=Decimal("0.00075"), slippage_bps=5.0)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def raw_payload() -> dict:
    return json.loads(FIXTURE.read_text())


@pytest.fixture(scope="module")
def source() -> CryptoComSource:
    return CryptoComSource.from_fixture(FIXTURE)


@pytest.fixture(scope="module")
def bars(source: CryptoComSource) -> list:
    return source.fetch(UNIVERSE, FIRST_SESSION, LAST_SESSION)


@pytest.fixture(scope="module")
def panel(bars: list) -> PricePanel:
    return PricePanel.from_bars(bars_to_rows(bars))


@pytest.fixture(scope="module")
def sessions() -> list[date]:
    return continuous_sessions(FIRST_SESSION, LAST_SESSION)


def _strategy():
    return build_strategy(
        "asset_class_trend_following",
        {"symbols": UNIVERSE, "sma_period": SMA_PERIOD, "rebalance": "daily"},
    )


def _run(
    broker,
    risk_limits: RiskLimits | None = None,
    peak_equity: Decimal | None = None,
) -> list:
    """Walk every session, returning the record list."""

    async def go():
        strategy = _strategy()
        sessions_list = continuous_sessions(FIRST_SESSION, LAST_SESSION)
        config = DriverConfig(
            run_ref="realdata", risk_limits=risk_limits or RiskLimits()
        )
        driver = Driver(
            strategy,
            broker,
            SimClock(sessions_list),
            config,
            peak_equity=peak_equity,
        )
        source = CryptoComSource.from_fixture(FIXTURE)
        panel = PricePanel.from_bars(
            bars_to_rows(source.fetch(UNIVERSE, FIRST_SESSION, LAST_SESSION))
        )
        # Deliberately the plain ``run`` rather than a hand-rolled loop that
        # advances the clock: see test_driver_run_stamps_the_right_session.
        return await driver.run(panel, sessions_list)

    return asyncio.run(go())


# ---------------------------------------------------------------------------
# Ingestion — the numbers survive the trip
# ---------------------------------------------------------------------------


def test_fixture_is_labelled_as_observed(raw_payload: dict) -> None:
    """Provenance travels with the data or the data is not evidence."""
    meta = raw_payload["_provenance"]
    assert meta["endpoint"] == "public/get-candlestick"
    assert meta["captured_at"]
    assert meta["timeframe"] == "1D"


def test_every_symbol_has_the_full_window(bars: list) -> None:
    per_symbol: dict[str, list[date]] = {}
    for bar in bars:
        per_symbol.setdefault(bar.symbol, []).append(bar.session)

    assert sorted(per_symbol) == sorted(UNIVERSE)
    for symbol, days in per_symbol.items():
        assert days == sorted(days), f"{symbol} bars are not ascending"
        assert len(days) == 24, symbol
        assert days[0] == FIRST_SESSION
        assert days[-1] == LAST_SESSION


def test_observed_closes_survive_ingestion_unchanged(
    raw_payload: dict, panel: PricePanel
) -> None:
    """
    Every observed close reaches the panel bit-for-bit.

    Not a spot check: a silent rescale, a stray fill-forward or an off-by-one
    session alignment would each show up in exactly one of these and in none of
    the aggregate assertions elsewhere in the file.
    """
    for symbol, rows in raw_payload["instruments"].items():
        for row in rows:
            session = datetime.fromisoformat(
                row["timestamp"].replace("Z", "+00:00")
            ).date()
            for field in ("open", "high", "low", "close"):
                assert panel.value_on(symbol, session, field) == pytest.approx(
                    float(row[field]), abs=0.0, rel=0.0
                ), f"{symbol} {session} {field}"


def test_adj_close_equals_close_by_construction(bars: list) -> None:
    """
    A spot pair has no splits and pays no dividends.

    Asserted rather than trusted, because this is the *only* case in the system
    where the two may coincide. On equities the same equality would mean the
    adjusted series had been silently dropped.
    """
    for bar in bars:
        assert bar.adj_close == bar.close, bar
        assert bar.source == "cryptocom"


def test_panel_has_no_gaps(panel: PricePanel) -> None:
    """No NaN anywhere: a hole would be filled forward and never noticed."""
    for field in panel.fields:
        for symbol in UNIVERSE:
            series = panel.series(symbol, field)
            assert len(series) == 24, f"{symbol}/{field}"
            assert not series.isna().any(), f"{symbol}/{field}"


# ---------------------------------------------------------------------------
# The 24/7 calendar
# ---------------------------------------------------------------------------


def test_continuous_sessions_include_the_weekend() -> None:
    """
    Crypto trades on Saturdays; the NYSE calendar does not know that.

    2026-07-11 and 2026-07-12 are a Saturday and a Sunday, and the fixture
    carries real candles for both. Routing crypto through the equity calendar
    would silently discard two sevenths of the data — the sort of bug that
    produces a plausible-looking equity curve rather than an error.
    """
    saturday, sunday = date(2026, 7, 11), date(2026, 7, 12)
    assert saturday.weekday() == 5
    assert sunday.weekday() == 6

    crypto = continuous_sessions(FIRST_SESSION, LAST_SESSION)
    assert len(crypto) == 24
    assert saturday in crypto and sunday in crypto

    equity_days = nyse_sessions(FIRST_SESSION, LAST_SESSION)
    assert saturday not in equity_days
    assert sunday not in equity_days
    assert len(equity_days) < len(crypto)


def test_continuous_sessions_rejects_a_reversed_range() -> None:
    with pytest.raises(ValueError, match="precedes start"):
        continuous_sessions(LAST_SESSION, FIRST_SESSION)


# ---------------------------------------------------------------------------
# The look-ahead guard, on real prices
# ---------------------------------------------------------------------------


def test_panel_refuses_to_reveal_tomorrow(panel: PricePanel) -> None:
    mid = date(2026, 7, 20)
    sliced = panel.at(mid)

    assert sliced.value_on("BTC_USDT", mid, "close") == pytest.approx(65256.31)
    with pytest.raises(LookAheadError):
        sliced.value_on("BTC_USDT", date(2026, 7, 21), "close")
    with pytest.raises(LookAheadError):
        sliced.at(date(2026, 7, 21))


def test_sma_on_real_prices_matches_a_hand_computation(panel: PricePanel) -> None:
    """
    The signal the strategy sees, computed independently.

    BTC's five closes to 2026-07-12 inclusive: 63816.82, 63786.40 and the three
    before them. If the panel's SMA disagreed with the arithmetic mean of the
    visible window the trend filter would fire at the wrong times, and nothing
    else in the suite would catch it.
    """
    as_of = date(2026, 7, 12)
    sliced = panel.at(as_of)
    window = sliced.series("BTC_USDT", "adj_close").tail(SMA_PERIOD)

    assert len(window) == SMA_PERIOD
    assert sliced.sma("BTC_USDT", SMA_PERIOD) == pytest.approx(
        float(window.mean()), rel=1e-12
    )

    # 2026-07-12 is the fifth session in the fixture, so it is the *first* on
    # which a five-session average exists. One session earlier the window is
    # short, and the panel returns None rather than a partial average that
    # would quietly bias the very first signal the strategy ever sees.
    assert panel.at(date(2026, 7, 11)).sma("BTC_USDT", SMA_PERIOD) is None
    assert panel.at(date(2026, 7, 12)).sma("BTC_USDT", SMA_PERIOD) is not None


# ---------------------------------------------------------------------------
# The driver, end to end
# ---------------------------------------------------------------------------


def test_driver_runs_the_whole_window(sessions: list[date]) -> None:
    records = _run(SimulatedBroker(initial_cash=100_000, cost_model=CostModel()))

    assert [r.session for r in records] == sessions
    assert all(r.equity > 0 for r in records)
    # A daily cadence rebalances on every session it is asked about.
    assert sum(1 for r in records if r.rebalanced) == len(sessions)
    # And it must actually trade, or the rest of the run proves nothing.
    assert sum(len(r.fills) for r in records) > 0


def test_decision_lag_holds_on_real_data(sessions: list[date]) -> None:
    """
    Nothing fills on the session that decided it.

    The constraint the backtest exists to respect: live at 15:45 you do not
    know today's close, so an order decided from it cannot fill today.
    """
    records = _run(SimulatedBroker(initial_cash=100_000, cost_model=CostModel()))
    by_session = {r.session: r for r in records}

    first_intent = next(r.session for r in records if r.intents)
    first_fill = next((r.session for r in records if r.fills), None)
    assert first_fill is not None
    assert first_fill > first_intent

    for index, session in enumerate(sessions):
        record = by_session[session]
        if not record.fills:
            continue
        previous = by_session[sessions[index - 1]]
        staged = {i.symbol for i in previous.intents}
        assert {f.symbol for f in record.fills} <= staged, session


def test_ledger_balances_on_every_session() -> None:
    """Equity is cash plus marked positions, to the cent, throughout."""
    broker = SimulatedBroker(initial_cash=100_000, cost_model=CostModel())
    records = _run(broker)

    for record in records:
        assert record.equity - record.cash == record.invested_value
        assert record.cash >= Decimal("0"), f"{record.session} went short of cash"


def test_risk_gate_ran_and_did_not_bind(sessions: list[date]) -> None:
    """
    Default limits are permissive, so the run measures the strategy.

    Worth pinning: if a default ever started binding, every backtest in the
    system would quietly become a measurement of the gate instead.
    """
    records = _run(SimulatedBroker(initial_cash=100_000, cost_model=CostModel()))
    rebalances = [r for r in records if r.rebalanced]

    assert rebalances
    for record in rebalances:
        assert record.raw_targets is not None
        assert record.targets is not None
        assert not [e for e in record.risk_events if e.binding]
        assert dict(record.targets.weights) == dict(record.raw_targets.weights)


# ---------------------------------------------------------------------------
# Where the simulated venue is kinder than a real one
# ---------------------------------------------------------------------------


def test_underfunded_buys_are_reported_not_swallowed() -> None:
    """
    The backtest must say when it did something a venue would have refused.

    Sizing happens against equity marked at session T's close; the fill lands
    at T+1's open after slippage and commission. A fully-invested target is
    therefore under-funded by the overnight gap every time the market opens up,
    and ``SimulatedBroker`` trims the buy where Alpaca would reject it.

    ``test_parity_holds_on_real_prices`` cannot see this: the order *intents*
    are identical on both paths and it is the fills that diverge. So the venue
    records each trim instead.
    """
    broker = SimulatedBroker(initial_cash=100_000, cost_model=_CRYPTO_COSTS)
    records = _run(broker)

    buys = [i for r in records for i in r.intents if i.side.value == "buy"]
    trims = broker.underfunded_buys

    assert buys, "the run must place buys or this proves nothing"
    assert trims, (
        "expected the cash cap to bind on a 100%-invested target with no "
        "cash buffer; if it no longer does, the divergence has been fixed "
        "elsewhere and this test should say so"
    )
    for trim in trims:
        assert trim.filled_qty < trim.requested_qty
        assert 0.0 < trim.shortfall_fraction < 0.05
        assert trim.symbol in UNIVERSE


def test_a_cash_buffer_removes_the_divergence() -> None:
    """
    The cure already exists and is off by default.

    ``RiskLimits.cash_buffer_pct`` holds back a slice of equity so the gap
    between the decision price and the fill price cannot underfund the order.
    Pinned here because the default is deliberately permissive — an unconfigured
    backtest measures the strategy, not the gate — which means the operator has
    to be told the setting exists and works.
    """
    buffered = SimulatedBroker(initial_cash=100_000, cost_model=_CRYPTO_COSTS)
    _run(buffered, risk_limits=RiskLimits(cash_buffer_pct=0.02))

    unbuffered = SimulatedBroker(initial_cash=100_000, cost_model=_CRYPTO_COSTS)
    _run(unbuffered)

    assert unbuffered.underfunded_buys
    assert not buffered.underfunded_buys


# ---------------------------------------------------------------------------
# Parity, on observed prices
# ---------------------------------------------------------------------------


def test_parity_holds_on_real_prices(panel: PricePanel, sessions: list[date]) -> None:
    """
    Backtest and live emit identical orders from identical real history.

    ``tests/unit/test_parity.py`` makes this claim on generated prices. Real
    prices have gaps, ties and reversals a generator does not produce, so the
    same claim on observed data is a stronger one.
    """

    async def backtest() -> list:
        clock = SimClock(sessions)
        sim = SimulatedBroker(initial_cash=100_000, cost_model=CostModel())
        driver = Driver(_strategy(), sim, clock, DriverConfig(run_ref="realdata"))
        out = []
        for session in sessions:
            out.append(await driver.step(panel, session))
            clock.advance()
        return out

    records = asyncio.run(backtest())
    rebalances = [r for r in records if r.intents]
    assert rebalances, "the run must place orders or parity proves nothing"

    # Replay each order-placing session on the live path, seeded with the book
    # as the backtest itself held it at that moment. A live adapter keeps no
    # ledger — it is *told* the account by the venue — so the state has to be
    # reconstructed per session rather than read off the end of the run.
    mismatches: list[str] = []
    for record in rebalances:
        fake = FakeLiveBroker(
            cash=record.cash,
            equity=record.equity,
            positions=_positions_at(records, record.session),
        )
        driver = Driver(
            _strategy(),
            fake,
            SimClock([record.session]),
            DriverConfig(run_ref="realdata"),
        )
        asyncio.run(driver.step(panel, record.session))
        if fake.submitted != record.intents:
            mismatches.append(
                f"{record.session}: backtest={record.intents} "
                f"live={fake.submitted}"
            )

    assert not mismatches, (
        f"{len(mismatches)} of {len(rebalances)} sessions diverged between "
        f"backtest and live on observed prices:\n" + "\n".join(mismatches[:3])
    )


# ---------------------------------------------------------------------------
# Honesty
# ---------------------------------------------------------------------------


def test_metrics_refuse_to_call_a_seven_week_sharpe_significant() -> None:
    """
    Twenty-four sessions cannot support a performance claim, and the engine
    is required to say so without being asked.

    This is the honesty rule from ``CLAUDE.md`` under test: a Sharpe rendered
    without its standard error is a number pretending to be a result.
    """
    records = _run(SimulatedBroker(initial_cash=100_000, cost_model=CostModel()))
    metrics = metrics_from_records(
        records, periods_per_year=CRYPTO_PERIODS_PER_YEAR
    )

    assert metrics.n_sessions == 24
    assert metrics.periods_per_year == CRYPTO_PERIODS_PER_YEAR
    assert metrics.sharpe_stderr > 1.0
    assert not metrics.sharpe_is_significant
    assert "[NOT significant vs zero]" in metrics.summary()


def test_annualisation_is_recorded_not_assumed() -> None:
    """
    A 24/7 market has 365 sessions a year, not 252.

    Annualising continuous returns on the NYSE year understates volatility by
    sqrt(365/252) — about 20%, which flatters the Sharpe by the same factor.
    The metric carries the assumption so the two cannot be confused.
    """
    records = _run(SimulatedBroker(initial_cash=100_000, cost_model=CostModel()))
    nyse_year = metrics_from_records(records)
    crypto_year = metrics_from_records(
        records, periods_per_year=CRYPTO_PERIODS_PER_YEAR
    )

    assert nyse_year.periods_per_year == 252
    assert crypto_year.periods_per_year == 365
    assert crypto_year.volatility == pytest.approx(
        nyse_year.volatility * (365 / 252) ** 0.5, rel=1e-9
    )


def test_clock_is_the_injected_one(sessions: list[date]) -> None:
    """
    A backtest records when an event *would* have happened.

    If the simulated broker reached for the wall clock, every fill in a 2007
    backtest would be stamped with today's date and the audit trail would be
    fiction.
    """
    broker = SimulatedBroker(initial_cash=100_000, cost_model=CostModel())
    records = _run(broker)
    fills = [f for r in records for f in r.fills]

    assert fills
    today = datetime.now(tz=UTC).date()
    for fill in fills:
        assert fill.filled_at.date() in sessions
        # The exact instant SimClock reports for that session's close, to the
        # second. Anything reaching for the wall clock would land elsewhere.
        assert fill.filled_at == datetime(
            fill.filled_at.year,
            fill.filled_at.month,
            fill.filled_at.day,
            21,
            tzinfo=UTC,
        )

    # Not "every stamp is in the past": this fixture's last session may be
    # today, whose 21:00 close has not happened yet. The property that matters
    # is that the stamps track sessions rather than collapsing onto today.
    assert len({f.filled_at.date() for f in fills}) > 1
    assert {f.filled_at.date() for f in fills} != {today}


def test_driver_run_stamps_the_right_session() -> None:
    """
    Every fill carries the session it actually happened on.

    ``Driver.run`` used to leave the injected ``SimClock`` parked on its first
    session, so a whole backtest's fills shared one timestamp. It went unnoticed
    because the CLI, the worker and the walk-forward each hand-rolled the walk
    with their own ``clock.advance()`` — three copies of a workaround for a bug
    in the method they were avoiding. Running the engine on real data through
    the obvious API is what surfaced it.
    """
    broker = SimulatedBroker(initial_cash=100_000, cost_model=CostModel())
    records = _run(broker)

    fills_by_session = {
        r.session: {f.filled_at.date() for f in r.fills} for r in records if r.fills
    }
    assert len(fills_by_session) > 1, "need fills on several sessions to test this"
    for session, stamps in fills_by_session.items():
        assert stamps == {session}, f"{session} fills stamped {stamps}"


def test_simulated_broker_stays_in_paper_or_backtest_mode() -> None:
    broker = SimulatedBroker(initial_cash=100_000, cost_model=CostModel())
    assert broker.mode is TradingMode.BACKTEST


# ---------------------------------------------------------------------------
# The halting limits, driven end to end
# ---------------------------------------------------------------------------
#
# ``tests/unit/test_risk_gate.py`` exercises ``apply_risk`` with a hand-built
# ``RiskState``. That proved the gate's arithmetic and nothing about whether
# the ``RiskState`` the driver actually assembles carries the fields the
# arithmetic reads. It did not: ``day_start_equity``, ``current_equity`` and
# ``peak_equity`` were never populated, so ``daily_pnl`` and ``drawdown`` both
# short-circuited to zero and neither limit could fire however it was set.
#
# These drive the real driver over real prices instead, and — because a limit
# that always fires is as useless as one that never does — check both
# directions.


def test_a_daily_loss_limit_halts_trading() -> None:
    broker = SimulatedBroker(initial_cash=100_000, cost_model=CostModel())
    records = _run(broker, risk_limits=RiskLimits(max_daily_loss_usd=Decimal("500")))

    breaches = [
        e
        for r in records
        for e in r.risk_events
        if e.code is RiskCode.DAILY_LOSS_BREACH
    ]
    assert breaches, "a $500 daily-loss limit never fired over a 10% drawdown"
    assert all(e.severity is Severity.BLOCK for e in breaches)

    # A blocking check means flat, not frozen: a halted book must not keep the
    # exposure that caused the halt.
    for record in records:
        if any(e.code is RiskCode.DAILY_LOSS_BREACH for e in record.risk_events):
            assert record.targets is not None
            assert dict(record.targets.weights) == {}


def test_a_drawdown_limit_halts_trading() -> None:
    broker = SimulatedBroker(initial_cash=100_000, cost_model=CostModel())
    records = _run(broker, risk_limits=RiskLimits(max_drawdown_pct=0.03))

    breaches = [
        e for r in records for e in r.risk_events if e.code is RiskCode.DRAWDOWN_BREACH
    ]
    assert breaches, "a 3% drawdown limit never fired over a 10% drawdown"


def test_limits_that_should_not_bind_do_not() -> None:
    """
    The other direction. A gate that halts unconditionally would pass every
    assertion above while making the system untradeable.
    """
    baseline = _run(SimulatedBroker(initial_cash=100_000, cost_model=CostModel()))
    generous = _run(
        SimulatedBroker(initial_cash=100_000, cost_model=CostModel()),
        risk_limits=RiskLimits(
            max_daily_loss_usd=Decimal("10000000"), max_drawdown_pct=0.99
        ),
    )

    for records in (baseline, generous):
        assert not [
            e
            for r in records
            for e in r.risk_events
            if e.code
            in (RiskCode.DAILY_LOSS_BREACH, RiskCode.DRAWDOWN_BREACH)
        ]
    # And the generous run must be indistinguishable from no limits at all.
    assert [r.equity for r in generous] == [r.equity for r in baseline]


def test_peak_equity_is_seeded_not_rediscovered() -> None:
    """
    A live process is rebuilt for each session and must be told where the peak
    was, or every restart resets the drawdown to zero and the limit is inert.
    """
    broker = SimulatedBroker(initial_cash=100_000, cost_model=CostModel())
    seeded = _run(
        broker,
        risk_limits=RiskLimits(max_drawdown_pct=0.03),
        peak_equity=Decimal("500000"),
    )
    breaches = [
        e for r in seeded for e in r.risk_events if e.code is RiskCode.DRAWDOWN_BREACH
    ]
    # Against a $500k peak the very first session is already 80% down, so the
    # seed must bind immediately rather than being recomputed from this run.
    assert breaches
    assert seeded[0].risk_events, "the seeded peak did not reach the gate"
