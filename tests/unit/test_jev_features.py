"""
test_jev_features.py
--------------------
The decision lane's state, computed from prices.

Three properties carry the weight, because each fails silently:

* **No look-ahead.** A state for a session must be the same whatever bars
  follow it. Appending a crash after the session must not move a label; the
  test also shows the crash does move the labels at its own end, so a
  descriptor that peeked would be caught rather than agreeing by accident. On
  the synthetic market the check is stronger still: the future is not hidden
  behind the panel's cutoff but absent from the rows the panel is built from.
* **Missing is None.** Short history, no bar on the session, an unusable price
  or a symbol the panel does not hold each make the whole state ``None``, which
  the lane records as not measured. A partial or stale state would be a guess,
  and an answer to a guess looks like evidence.
* **Nothing identifying leaves.** No symbol, no date, no figure: the model has
  world knowledge, and any of the three lets it recall what happened next.

Prices are mostly built from deterministic returns rather than a random walk,
so that every expected label follows from the construction and can be checked
by hand. The synthetic market ``test_parity.py`` uses supplies the rest: real
NYSE sessions, instruments that list on different days, and a crash.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.core.panel import LookAheadError, PricePanel
from src.data import SyntheticSource, bars_to_rows
from src.programme import jev_features as features
from src.programme import jev_questions as jq

ROOT = Path(__file__).resolve().parents[2]
FEATURES = ROOT / "src" / "programme" / "jev_features.py"
SLEEVES = {"equities": "AAA", "bonds": "BBB", "commodities": "CCC"}
N = features.MIN_HISTORY_SESSIONS + 120

#: The windows and edges the descriptors are defined by, all in jev_questions.
DEFINITIONS = (
    "TREND_AVERAGE_SESSIONS",
    "TREND_NEAR_BAND",
    "VOLATILITY_SESSIONS",
    "VOLATILITY_HISTORY_SESSIONS",
    "DRAWDOWN_HIGH_SESSIONS",
    "DRAWDOWN_SHALLOW",
    "DRAWDOWN_DEEP",
    "DRAWDOWN_SEVERE",
    "MOMENTUM_SESSIONS",
    "MOMENTUM_FLAT_BAND",
)


def _closes(returns: np.ndarray) -> np.ndarray:
    """Closes from daily log returns, starting at 100."""
    return 100.0 * np.exp(np.concatenate([[0.0], np.cumsum(returns)]))


def _zigzag(n: int, drift: float, swing: float) -> np.ndarray:
    """``n`` log returns alternating ``drift + swing`` and ``drift - swing``."""
    return drift + swing * np.where(np.arange(n) % 2 == 0, 1.0, -1.0)


def calm_advance(n: int = N) -> np.ndarray:
    """
    A steady rise whose last 20 sessions are the calmest of its history.

    Every other 20-session window holds at least one of the earlier, wider
    swings, so the latest volatility reading is the unique minimum.
    """
    tail = 20
    return _closes(
        np.concatenate(
            [_zigzag(n - 1 - tail, 0.001, 0.01), _zigzag(tail, 0.001, 0.002)]
        )
    )


def stressed_decline(n: int = N) -> np.ndarray:
    """A calm rise, then 80 sessions falling half a percent a day, violently."""
    tail = 80
    return _closes(
        np.concatenate(
            [_zigzag(n - 1 - tail, 0.0005, 0.005), _zigzag(tail, -0.005, 0.03)]
        )
    )


def flat(n: int = N) -> np.ndarray:
    """A price that never moves: every reading of every descriptor is a tie."""
    return np.full(n, 100.0)


def _panel(
    closes: dict[str, np.ndarray], sessions: pd.DatetimeIndex | None = None
) -> PricePanel:
    """A panel whose every series ends on the last of ``sessions``."""
    length = max(len(c) for c in closes.values())
    if sessions is None:
        sessions = pd.bdate_range("2010-01-04", periods=length)
    rows = []
    for symbol, values in closes.items():
        for day, close in zip(sessions[-len(values) :], values, strict=True):
            rows.append(
                (symbol, day.date(), close, close, close, close, 1_000_000.0, close)
            )
    return PricePanel.from_bars(rows)


def _last(panel: PricePanel) -> date:
    return panel.sessions[-1].date()


def _sleeve(trend: str, quintile: int, drawdown: str, momentum: str) -> jq.SleeveState:
    return jq.SleeveState(
        trend=trend,  # type: ignore[arg-type]
        volatility_quintile=quintile,  # type: ignore[arg-type]
        drawdown=drawdown,  # type: ignore[arg-type]
        momentum=momentum,  # type: ignore[arg-type]
    )


CALM_ADVANCE = _sleeve("above", 1, "none", "up")
STRESSED_DECLINE = _sleeve("below", 5, "severe", "down")
FLAT = _sleeve("near", 3, "none", "flat")


# ---------------------------------------------------------------------------
# End to end, from a panel
# ---------------------------------------------------------------------------


class TestTheDescriptorsFollowThePrices:
    def test_each_sleeve_is_described_from_its_own_prices(self) -> None:
        panel = _panel(
            {"AAA": calm_advance(), "BBB": flat(), "CCC": stressed_decline()}
        )
        state = features.regime_state(panel, _last(panel), SLEEVES)
        assert state == jq.RegimeState(
            equities=CALM_ADVANCE, bonds=FLAT, commodities=STRESSED_DECLINE
        )

    def test_the_sleeves_are_read_through_the_mapping(self) -> None:
        panel = _panel(
            {"AAA": calm_advance(), "BBB": flat(), "CCC": stressed_decline()}
        )
        swapped = {"equities": "CCC", "bonds": "AAA", "commodities": "BBB"}
        state = features.regime_state(panel, _last(panel), swapped)
        assert state is not None
        assert (state.equities, state.bonds, state.commodities) == (
            STRESSED_DECLINE,
            CALM_ADVANCE,
            FLAT,
        )

    def test_it_is_deterministic(self) -> None:
        panel = _panel(
            {"AAA": calm_advance(), "BBB": flat(), "CCC": stressed_decline()}
        )
        first = features.regime_state(panel, _last(panel), SLEEVES)
        second = features.regime_state(panel, _last(panel), SLEEVES)
        assert first is not None and first == second
        assert first.model_dump_json() == second.model_dump_json()

    def test_it_reads_adjusted_closes_not_raw_ones(self) -> None:
        """
        Signals use ``adj_close``; money uses ``close`` (CLAUDE.md). Here the
        two disagree completely — one rises, the other never moves — and the
        state follows the adjusted series every time.
        """
        sessions = pd.bdate_range("2010-01-04", periods=N)
        rising, level = calm_advance(), flat()
        rows = []
        for symbol, raw, adjusted in (
            ("AAA", level, rising),
            ("BBB", rising, level),
            ("CCC", level, level),
        ):
            for day, close, adj in zip(sessions, raw, adjusted, strict=True):
                rows.append((symbol, day.date(), close, close, close, close, 1e6, adj))
        panel = PricePanel.from_bars(rows)
        state = features.regime_state(panel, sessions[-1].date(), SLEEVES)
        assert state == jq.RegimeState(
            equities=CALM_ADVANCE, bonds=FLAT, commodities=FLAT
        )

    def test_a_gap_inside_the_window_is_skipped_as_the_panel_skips_it(self) -> None:
        """
        A day with no bar for one symbol, earlier than the session, is not
        missing data for the state: the window is the last closes there are,
        exactly as ``PricePanel.series`` and ``PricePanel.sma`` count them.
        """
        sessions = pd.bdate_range("2010-01-04", periods=N)
        values = calm_advance()
        gap = N - 50
        rows = []
        for symbol, series in (("AAA", flat()), ("BBB", values), ("CCC", flat())):
            for i, (day, close) in enumerate(zip(sessions, series, strict=True)):
                if symbol == "BBB" and i == gap:
                    continue
                rows.append(
                    (symbol, day.date(), close, close, close, close, 1e6, close)
                )
        panel = PricePanel.from_bars(rows)
        state = features.regime_state(panel, sessions[-1].date(), SLEEVES)
        assert state is not None
        observed = np.delete(values, gap)[-features.MIN_HISTORY_SESSIONS :]
        assert state.bonds == features.describe(observed)
        ratio = values[-1] / panel.sma("BBB", jq.TREND_AVERAGE_SESSIONS) - 1.0
        assert state.bonds.trend == features.trend_label(ratio)


class TestNoLookAhead:
    def test_bars_after_the_session_do_not_move_the_state(self) -> None:
        crash = _closes(_zigzag(100, -0.01, 0.03))[1:] * calm_advance()[-1] / 100.0
        before = {"AAA": calm_advance(), "BBB": flat(), "CCC": calm_advance()}
        after = {k: np.concatenate([v, crash]) for k, v in before.items()}
        sessions = pd.bdate_range("2010-01-04", periods=N + len(crash))

        short = _panel(before, sessions[:N])
        long = _panel(after, sessions)
        session = sessions[N - 1].date()

        state = features.regime_state(short, session, SLEEVES)
        assert state is not None
        assert features.regime_state(long, session, SLEEVES) == state

        # The premise: the bars that follow are not benign. At their own end
        # they describe a different market, so a descriptor that read them for
        # the earlier session would have produced a different state.
        later = features.regime_state(long, _last(long), SLEEVES)
        assert later is not None and later.equities != state.equities

    def test_history_before_the_window_does_not_move_the_state(self) -> None:
        """
        The state is a function of the trailing window alone. Years of wild
        prices before it change nothing — not even a boundary case.
        """
        prices = {"AAA": calm_advance(), "BBB": flat(), "CCC": stressed_decline()}
        wild = _closes(_zigzag(500, 0.002, 0.08))
        sessions = pd.bdate_range("2008-01-01", periods=N + len(wild))
        longer = {
            k: np.concatenate([wild * v[0] / wild[-1], v]) for k, v in prices.items()
        }
        plain = _panel(prices, sessions)
        preceded = _panel(longer, sessions)
        assert _last(plain) == _last(preceded)
        assert features.regime_state(plain, _last(plain), SLEEVES) == (
            features.regime_state(preceded, _last(preceded), SLEEVES)
        )

    def test_a_session_past_the_panel_is_refused_not_guessed(self) -> None:
        panel = _panel({"AAA": flat(), "BBB": flat(), "CCC": flat()})
        with pytest.raises(LookAheadError):
            features.regime_state(panel, date(2099, 1, 1), SLEEVES)


class TestMissingIsNone:
    def test_the_history_needed_is_1260_readings_of_20_sessions(self) -> None:
        assert features.MIN_HISTORY_SESSIONS == 1_280
        assert features.MIN_HISTORY_SESSIONS == (
            jq.VOLATILITY_HISTORY_SESSIONS + jq.VOLATILITY_SESSIONS
        )
        # Every other descriptor reaches less far back, so this one number is
        # the whole requirement.
        for reach in (
            jq.TREND_AVERAGE_SESSIONS,
            jq.DRAWDOWN_HIGH_SESSIONS,
            jq.MOMENTUM_SESSIONS + 1,
        ):
            assert reach <= features.MIN_HISTORY_SESSIONS

    def test_one_close_short_is_missing_and_exactly_enough_is_not(self) -> None:
        need = features.MIN_HISTORY_SESSIONS
        panel = _panel({"AAA": flat(need), "BBB": flat(need), "CCC": flat(need)})
        assert features.regime_state(panel, _last(panel), SLEEVES) is not None
        previous = panel.sessions[-2].date()
        assert features.regime_state(panel, previous, SLEEVES) is None

    def test_one_short_sleeve_makes_the_whole_state_missing(self) -> None:
        """Not a partial state: a regime judged on two sleeves of three is a
        guess at the third."""
        short = features.MIN_HISTORY_SESSIONS - 1
        panel = _panel({"AAA": calm_advance(), "BBB": flat(), "CCC": flat(short)})
        assert features.regime_state(panel, _last(panel), SLEEVES) is None

    def test_a_sleeve_with_no_close_on_the_session_is_missing(self) -> None:
        """
        A failed ingest leaves yesterday's bar as the latest. Describing it as
        today's would be a stale state presented as a current one.
        """
        sessions = pd.bdate_range("2010-01-04", periods=N)
        rows = []
        for symbol in ("AAA", "BBB", "CCC"):
            values = flat()
            for day, close in zip(sessions, values, strict=True):
                if symbol == "CCC" and day == sessions[-1]:
                    continue
                rows.append(
                    (symbol, day.date(), close, close, close, close, 1e6, close)
                )
        panel = PricePanel.from_bars(rows)
        assert features.regime_state(panel, sessions[-1].date(), SLEEVES) is None
        assert features.regime_state(panel, sessions[-2].date(), SLEEVES) is not None

    def test_a_raw_close_on_the_session_is_not_an_adjusted_one(self) -> None:
        """
        The session's own bar has to carry the adjusted close the descriptors
        are computed from. A raw close alone would let the state be built from
        the previous day's adjusted series and labelled as today's.
        """
        sessions = pd.bdate_range("2010-01-04", periods=N)
        rows = []
        for symbol in ("AAA", "BBB", "CCC"):
            for day, close in zip(sessions, flat(), strict=True):
                adjusted = (
                    float("nan") if symbol == "BBB" and day == sessions[-1] else close
                )
                rows.append(
                    (symbol, day.date(), close, close, close, close, 1e6, adjusted)
                )
        panel = PricePanel.from_bars(rows)
        assert panel.value_on("BBB", sessions[-1].date(), "close") == 100.0
        assert features.regime_state(panel, sessions[-1].date(), SLEEVES) is None

    def test_a_day_the_market_was_shut_is_missing(self) -> None:
        panel = _panel({"AAA": flat(), "BBB": flat(), "CCC": flat()})
        saturday = panel.sessions[-1].date()
        while saturday.weekday() != 5:
            saturday = date.fromordinal(saturday.toordinal() - 1)
        assert features.regime_state(panel, saturday, SLEEVES) is None

    def test_a_day_before_every_bar_is_missing(self) -> None:
        panel = _panel({"AAA": flat(), "BBB": flat(), "CCC": flat()})
        assert features.regime_state(panel, date(1990, 1, 2), SLEEVES) is None

    def test_a_symbol_the_panel_does_not_hold_is_missing(self) -> None:
        panel = _panel({"AAA": flat(), "BBB": flat(), "CCC": flat()})
        sleeves = {**SLEEVES, "commodities": "ZZZ"}
        assert features.regime_state(panel, _last(panel), sleeves) is None

    @pytest.mark.parametrize("bad", [0.0, -5.0, float("inf")])
    def test_an_unusable_close_in_the_window_is_missing(self, bad: float) -> None:
        values = flat()
        values[-100] = bad
        panel = _panel({"AAA": flat(), "BBB": values, "CCC": flat()})
        assert features.regime_state(panel, _last(panel), SLEEVES) is None

    def test_an_unusable_close_before_the_window_is_not_read(self) -> None:
        values = flat()
        values[0] = 0.0
        panel = _panel({"AAA": flat(), "BBB": values, "CCC": flat()})
        assert features.regime_state(panel, _last(panel), SLEEVES) is not None


class TestTheMapping:
    @pytest.mark.parametrize(
        "sleeves",
        [
            {"equities": "AAA", "bonds": "BBB"},
            {**SLEEVES, "gold": "DDD"},
            {"stocks": "AAA", "bonds": "BBB", "commodities": "CCC"},
            {"equities": "AAA", "bonds": "AAA", "commodities": "CCC"},
            {**SLEEVES, "bonds": ""},
            {**SLEEVES, "bonds": None},
            [("equities", "AAA"), ("bonds", "BBB"), ("commodities", "CCC")],
        ],
        ids=[
            "a-sleeve-missing",
            "a-sleeve-extra",
            "a-sleeve-renamed",
            "two-sleeves-one-symbol",
            "an-empty-symbol",
            "no-symbol",
            "not-a-mapping",
        ],
    )
    def test_a_mapping_the_state_cannot_be_built_from_is_an_error(
        self, sleeves: object
    ) -> None:
        """
        A caller's mistake, not missing data: it raises rather than recording
        ``missing`` every session until somebody notices.
        """
        panel = _panel({"AAA": flat(), "BBB": flat(), "CCC": flat()})
        with pytest.raises(ValueError):
            features.regime_state(panel, _last(panel), sleeves)  # type: ignore[arg-type]


class TestNothingIdentifyingLeaves:
    def test_the_state_names_no_symbol_no_date_and_no_figure(self) -> None:
        sessions = pd.bdate_range("2010-01-04", periods=N)
        panel = _panel(
            {"SPY": calm_advance(), "IEF": flat(), "GSG": stressed_decline()}, sessions
        )
        state = features.regime_state(
            panel,
            sessions[-1].date(),
            {"equities": "SPY", "bonds": "IEF", "commodities": "GSG"},
        )
        assert state is not None
        text = state.model_dump_json()
        for symbol in ("SPY", "IEF", "GSG"):
            assert symbol not in text
        assert not re.search(r"\d{4}-\d{2}-\d{2}", text)
        assert not re.search(r"\d\.\d", text), "a figure reached the state"
        assert list(state.model_dump()) == list(jq.SLEEVES)

    def test_the_features_compute_with_the_definitions_the_question_hashes(
        self,
    ) -> None:
        """
        The windows and edges are bound from ``jev_questions``, where they are
        written into the regime question, not redefined here. A copy here could
        drift from the text the golden hash pins; a shared binding cannot.
        """
        for name in DEFINITIONS:
            assert getattr(features, name) is getattr(jq, name), name

    def test_the_definitions_are_imported_never_restated(self) -> None:
        """
        The check above cannot see a restatement of a small integer: Python
        caches them, so a local ``TREND_AVERAGE_SESSIONS = 200`` would be the
        same object as the imported one. The source can: every definition is
        imported from ``jev_questions``, none is assigned here, and the only
        numbers written in the module are the arithmetic's own — 0, 1, 2, and
        the 5 of "quintile" — so no window is spelled inline either.
        """
        tree = ast.parse(FEATURES.read_text(encoding="utf-8"))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module == "src.programme.jev_questions"
            for alias in node.names
        }
        assert set(DEFINITIONS) <= imported

        assigned = set()
        for node in ast.walk(tree):
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign | ast.AugAssign):
                targets = [node.target]
            assigned |= {t.id for t in targets if isinstance(t, ast.Name)}
        assert not assigned & set(DEFINITIONS)

        numbers = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, int | float)
            and not isinstance(node.value, bool)
        }
        assert numbers <= {0, 1, 2, 5}, numbers


# ---------------------------------------------------------------------------
# On the synthetic market: real sessions, staggered listings, a crash
# ---------------------------------------------------------------------------

MARKET = {"equities": "SPY", "bonds": "IEF", "commodities": "GSG"}
END = date(2020, 6, 30)


@pytest.fixture(scope="module")
def market_rows() -> list[tuple]:
    """Seeded synthetic bars on the NYSE calendar, built as test_parity does.

    GSG lists in 2006, so the commodities sleeve is the one short of history
    until mid-2011; the regimes the source imposes include a crash ending on
    2020-03-23."""
    bars = SyntheticSource().fetch(list(MARKET.values()), date(2005, 1, 3), END)
    return bars_to_rows(bars)


def _sessions_of(rows: list[tuple], symbol: str) -> list[date]:
    return [row[1] for row in rows if row[0] == symbol]


class TestOnTheSyntheticMarket:
    def test_the_state_begins_when_the_latest_listing_has_its_history(
        self, market_rows: list[tuple]
    ) -> None:
        """
        The commodities sleeve lists last, so the first state is on its
        1,280th session, and on the session before there is none — although
        the other two sleeves have had their history for years.
        """
        panel = PricePanel.from_bars(market_rows)
        gsg = _sessions_of(market_rows, "GSG")
        first = gsg[features.MIN_HISTORY_SESSIONS - 1]
        assert len(_sessions_of(market_rows, "SPY")) > len(gsg)
        assert features.regime_state(panel, first, MARKET) is not None
        assert features.regime_state(panel, gsg[len(gsg) // 4], MARKET) is None
        before = gsg[features.MIN_HISTORY_SESSIONS - 2]
        assert features.regime_state(panel, before, MARKET) is None

    def test_no_state_depends_on_a_bar_that_had_not_happened(
        self, market_rows: list[tuple]
    ) -> None:
        """
        Twice a year for nine years, and on the day the crash ends: the state
        from the whole panel equals the state from a panel built only from the
        bars on or before the session. The future is not hidden behind a
        cutoff here — it is not in the rows at all.
        """
        panel = PricePanel.from_bars(market_rows)
        gsg = _sessions_of(market_rows, "GSG")
        sample = gsg[features.MIN_HISTORY_SESSIONS - 1 :: 126] + [date(2020, 3, 23)]
        assert len(sample) > 15
        for session in sample:
            known = PricePanel.from_bars(r for r in market_rows if r[1] <= session)
            state = features.regime_state(known, session, MARKET)
            assert state is not None, session
            assert features.regime_state(panel, session, MARKET) == state, session

    def test_the_crash_reads_as_stress_and_the_advance_before_it_does_not(
        self, market_rows: list[tuple]
    ) -> None:
        """
        The source imposes a drift of -220% a year from 2020-02-19 to
        2020-03-23 on an index rising 9% a year. At its end the equities
        sleeve is below its average, falling and well off its high; at the end
        of 2019 it was above, rising and near it. Volatility is not asserted:
        the source's volatility is constant, so its quintile is noise.
        """
        panel = PricePanel.from_bars(market_rows)
        crash = features.regime_state(panel, date(2020, 3, 23), MARKET)
        calm = features.regime_state(panel, date(2019, 12, 31), MARKET)
        assert crash is not None and calm is not None
        assert crash.equities.trend == "below"
        assert crash.equities.momentum == "down"
        assert crash.equities.drawdown in ("deep", "severe")
        assert calm.equities.trend == "above"
        assert calm.equities.momentum == "up"
        assert calm.equities.drawdown in ("none", "shallow")


# ---------------------------------------------------------------------------
# The labels, at their edges
# ---------------------------------------------------------------------------


class TestTheEdges:
    @pytest.mark.parametrize(
        ("ratio", "label"),
        [
            (0.0, "near"),
            (0.01, "near"),
            (-0.01, "near"),
            (0.0100001, "above"),
            (-0.0100001, "below"),
            (0.25, "above"),
            (-0.25, "below"),
        ],
    )
    def test_trend_is_near_within_one_percent_inclusive(
        self, ratio: float, label: str
    ) -> None:
        assert features.trend_label(ratio) == label

    @pytest.mark.parametrize(
        ("drawdown", "label"),
        [
            (0.0, "none"),
            (0.0199999, "none"),
            (0.02, "shallow"),
            (0.0999999, "shallow"),
            (0.10, "deep"),
            (0.20, "deep"),
            (0.2000001, "severe"),
            (0.9, "severe"),
        ],
    )
    def test_drawdown_buckets(self, drawdown: float, label: str) -> None:
        assert features.drawdown_label(drawdown) == label

    @pytest.mark.parametrize(
        ("change", "label"),
        [
            (0.0, "flat"),
            (0.0099999, "flat"),
            (-0.0099999, "flat"),
            (0.01, "up"),
            (-0.01, "down"),
            (0.3, "up"),
        ],
    )
    def test_momentum_is_flat_strictly_inside_one_percent(
        self, change: float, label: str
    ) -> None:
        assert features.momentum_label(change) == label

    @pytest.mark.parametrize(
        "function",
        [features.trend_label, features.drawdown_label, features.momentum_label],
    )
    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
    def test_a_number_that_is_not_one_is_refused(
        self, function: object, value: float
    ) -> None:
        """A NaN compares false with everything and would fall through to
        whichever label a function returns last."""
        with pytest.raises(ValueError):
            function(value)  # type: ignore[operator]

    def test_a_negative_drawdown_is_refused(self) -> None:
        with pytest.raises(ValueError):
            features.drawdown_label(-0.01)


class TestTheVolatilityQuintile:
    @pytest.mark.parametrize(
        ("latest", "quintile"),
        [
            (0.5, 1),
            (19.5, 1),
            (20.5, 2),
            (50.5, 3),
            (79.5, 4),
            (80.5, 5),
            (100.0, 5),
        ],
    )
    def test_the_latest_reading_is_ranked_among_all_of_them(
        self, latest: float, quintile: int
    ) -> None:
        readings = np.array([*range(1, 100), latest], dtype=float)
        assert features.volatility_quintile(readings) == quintile

    def test_a_history_of_ties_sits_in_the_middle(self) -> None:
        """Nothing is calm or turbulent relative to itself."""
        assert features.volatility_quintile(np.zeros(1_260)) == 3

    def test_the_extremes_are_the_end_quintiles(self) -> None:
        readings = np.linspace(1.0, 2.0, 1_260)
        assert features.volatility_quintile(readings) == 5
        assert features.volatility_quintile(readings[::-1].copy()) == 1

    def test_a_quintile_is_a_plain_int(self) -> None:
        """A numpy integer would pass the Literal and fail strict validation
        somewhere further from its cause."""
        quintile = features.volatility_quintile(np.linspace(1.0, 2.0, 100))
        assert type(quintile) is int

    @pytest.mark.parametrize(
        "readings",
        [np.array([]), np.array([1.0, np.nan]), np.ones((2, 2))],
        ids=["empty", "a-nan", "two-dimensional"],
    )
    def test_readings_that_cannot_be_ranked_are_refused(
        self, readings: np.ndarray
    ) -> None:
        with pytest.raises(ValueError):
            features.volatility_quintile(readings)


class TestDescribe:
    def test_it_takes_exactly_the_window(self) -> None:
        with pytest.raises(ValueError):
            features.describe(flat(features.MIN_HISTORY_SESSIONS - 1))
        with pytest.raises(ValueError):
            features.describe(flat(features.MIN_HISTORY_SESSIONS + 1))

    @pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
    def test_it_refuses_a_price_that_is_not_one(self, bad: float) -> None:
        window = flat(features.MIN_HISTORY_SESSIONS)
        window[5] = bad
        with pytest.raises(ValueError):
            features.describe(window)

    def test_it_describes_the_constructions(self) -> None:
        window = features.MIN_HISTORY_SESSIONS
        assert features.describe(calm_advance(window)) == CALM_ADVANCE
        assert features.describe(stressed_decline(window)) == STRESSED_DECLINE
        assert features.describe(flat(window)) == FLAT


def _flat_with(changes: dict[int, float]) -> np.ndarray:
    """The flat window, with the closes at the given negative offsets changed."""
    window = flat(features.MIN_HISTORY_SESSIONS)
    for offset, value in changes.items():
        window[offset] = value
    return window


def _quiet_after_a_jump(quiet: int) -> np.ndarray:
    """
    Years of swings, one jump of 20%, then ``quiet`` returns of exactly zero.

    Zero exactly: the flat closes are one value repeated, so their log
    differences are 0.0 and every reading of them is 0.0, with no rounding to
    decide which of several near-ties is lowest.
    """
    returns = features.MIN_HISTORY_SESSIONS - 1
    return _closes(
        np.concatenate(
            [_zigzag(returns - quiet - 1, 0.0, 0.01), [0.2], np.zeros(quiet)]
        )
    )


class TestEachWindowIsExactlyAsLongAsDefined:
    """
    The constructions above would read the same with a window a session longer
    or shorter. These would not: each puts one extreme close just inside a
    window and then just outside it, and reads the one descriptor that window
    defines.
    """

    def test_the_average_is_of_exactly_the_last_200_closes(self) -> None:
        edge = -jq.TREND_AVERAGE_SESSIONS
        inside = features.describe(_flat_with({edge: 10_000.0}))
        outside = features.describe(_flat_with({edge - 1: 10_000.0}))
        assert (inside.trend, outside.trend) == ("below", "near")

    def test_the_high_is_of_exactly_the_last_252_closes(self) -> None:
        edge = -jq.DRAWDOWN_HIGH_SESSIONS
        inside = features.describe(_flat_with({edge: 10_000.0}))
        outside = features.describe(_flat_with({edge - 1: 10_000.0}))
        assert (inside.drawdown, outside.drawdown) == ("severe", "none")

    def test_momentum_is_measured_from_exactly_63_sessions_back(self) -> None:
        base = -1 - jq.MOMENTUM_SESSIONS
        labels = [
            features.describe(_flat_with({base + shift: 50.0})).momentum
            for shift in (-1, 0, 1)
        ]
        assert labels == ["flat", "up", "flat"]

    def test_volatility_is_of_exactly_the_last_20_returns(self) -> None:
        """
        The jump just before the last 20 returns leaves the latest reading the
        calmest of the history; the jump as the oldest of them makes it one of
        the most turbulent. Read from prices rather than returns, both would
        be flat.
        """
        outside = features.describe(_quiet_after_a_jump(jq.VOLATILITY_SESSIONS))
        inside = features.describe(_quiet_after_a_jump(jq.VOLATILITY_SESSIONS - 1))
        assert (outside.volatility_quintile, inside.volatility_quintile) == (1, 5)

    def test_volatility_is_ranked_among_every_reading_of_the_window(self) -> None:
        """
        A quiet final stretch after years of swings: 160 identical readings
        of zero at the end of 1,260. Among all of them the latest is in the
        calmest fifth; ranked among only the last year's 252 it would sit in
        the second.
        """
        swings = _closes(_zigzag(1_100, 0.0, 0.01))
        quiet = np.full(features.MIN_HISTORY_SESSIONS - len(swings), swings[-1])
        state = features.describe(np.concatenate([swings, quiet]))
        assert state.volatility_quintile == 1


def test_the_features_load_no_client_and_no_io() -> None:
    """Pure: importing the module, in a fresh interpreter, reaches nothing that
    performs I/O, and none of the runner."""
    forbidden = (
        "aiohttp",
        "anthropic",
        "asyncpg",
        "httpx",
        "httpx2",
        "requests",
        "typesafe_sdk",
        "yfinance",
        "src.db",
        "src.data",
        "src.programme.client",
        "src.programme.jev_client",
        "src.programme.jev_lane",
    )
    code = (
        "import sys, src.programme.jev_features\n"
        f"forbidden = {forbidden!r}\n"
        "print(sorted(m for m in sys.modules "
        "if any(m == f or m.startswith(f + '.') for f in forbidden)))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "[]", result.stdout
