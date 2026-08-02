"""
test_panel.py
-------------
Look-ahead prevention and availability windows.

These are the tests that stop the backtest from lying. A mutation run confirmed
they have teeth: deleting the guard in ``PricePanel.at`` makes
``test_cannot_reslice_into_the_future`` fail rather than passing quietly.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.core.panel import LookAheadError, PricePanel


def _rows(symbol: str, start: str, n: int, first_value: float = 100.0):
    """Ascending series so ordering assertions are unambiguous."""
    index = pd.bdate_range(start, periods=n)
    return [
        (symbol, ts.date(), first_value + i, first_value + i, first_value + i,
         first_value + i, 1_000_000.0, first_value + i)
        for i, ts in enumerate(index)
    ]


@pytest.fixture
def panel() -> PricePanel:
    return PricePanel.from_bars(_rows("SPY", "2020-01-01", 300))


class TestLookAheadPrevention:
    def test_cannot_reslice_into_the_future(self, panel: PricePanel) -> None:
        with pytest.raises(LookAheadError):
            panel.at(date(2099, 1, 1))

    def test_cannot_read_a_session_beyond_as_of(self, panel: PricePanel) -> None:
        narrowed = panel.at(date(2020, 3, 2))
        with pytest.raises(LookAheadError):
            narrowed.value_on("SPY", date(2020, 6, 1))

    def test_reslicing_narrows_visible_history(self, panel: PricePanel) -> None:
        full = len(panel)
        narrowed = panel.at(date(2020, 3, 2))
        assert len(narrowed) < full
        assert narrowed.sessions.max().date() <= date(2020, 3, 2)

    def test_narrowed_panel_cannot_widen_back(self, panel: PricePanel) -> None:
        """A strategy holding a narrowed panel must not recover the full one."""
        narrowed = panel.at(date(2020, 3, 2))
        with pytest.raises(LookAheadError):
            narrowed.at(date(2020, 6, 1))

    def test_sma_uses_only_visible_history(self, panel: PricePanel) -> None:
        """The same lookback at two cutoffs must give different answers."""
        early = panel.at(date(2020, 6, 1)).sma("SPY", 20)
        late = panel.at(date(2020, 12, 1)).sma("SPY", 20)
        assert early is not None and late is not None
        assert late > early, "ascending series must yield a rising SMA"


class TestAvailabilityWindows:
    """
    A symbol that has not listed yet is excluded from the universe, never
    treated as cash. Getting this wrong turns a five-asset equal-weight
    strategy into a one-asset strategy with an 80% cash drag.
    """

    @pytest.fixture
    def staggered(self) -> PricePanel:
        rows = _rows("SPY", "2020-01-01", 300) + _rows("GSG", "2021-01-01", 40)
        return PricePanel.from_bars(rows)

    def test_late_lister_is_unavailable_before_inception(
        self, staggered: PricePanel
    ) -> None:
        early = staggered.at(date(2020, 6, 1))
        assert early.is_available("SPY", min_history=100)
        assert not early.is_available("GSG", min_history=1)

    def test_insufficient_history_is_not_availability(
        self, staggered: PricePanel
    ) -> None:
        """Listed but short of the lookback still means "cannot trade"."""
        assert staggered.is_available("GSG", min_history=10)
        assert not staggered.is_available("GSG", min_history=210)

    def test_available_symbols_filters_the_universe(
        self, staggered: PricePanel
    ) -> None:
        got = staggered.available_symbols(["SPY", "GSG"], min_history=210)
        assert got == ("SPY",)

    def test_first_session_detects_inception(self, staggered: PricePanel) -> None:
        assert staggered.first_session("SPY") == date(2020, 1, 1)
        assert staggered.first_session("GSG") == date(2021, 1, 1)

    def test_sma_returns_none_rather_than_a_partial_average(
        self, staggered: PricePanel
    ) -> None:
        """
        None means "no signal". A partial average would be a number, and a
        number gets traded on.
        """
        assert staggered.sma("GSG", 210) is None
        assert staggered.sma("GSG", 10) is not None


class TestPanelConstruction:
    def test_rejects_empty_input(self) -> None:
        with pytest.raises(ValueError):
            PricePanel.from_bars([])

    def test_unknown_symbol_raises(self, panel: PricePanel) -> None:
        with pytest.raises(KeyError):
            panel.series("NOPE")

    def test_unknown_field_raises(self, panel: PricePanel) -> None:
        with pytest.raises(KeyError):
            panel.frame("nonexistent_field")
