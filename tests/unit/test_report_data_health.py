"""
The daily report's data health reads the traded universe (docs/08 open item
38).

``reports.build_daily_report`` used to take the newest session in
``daily_bars`` across every symbol. From phase C4 the forward clock's reference
job writes SPY, IEF and GSG every session whether or not anything trades them,
so a fresh reference row read as current data while the live ingest for the
traded universe had failed, and ``sessions_behind`` said 0 of the stale panel
the live decision reads. The latest session is now the stalest traded symbol's
newest, and a universe that cannot be read is said to be unknown, never current.

No database: the connection answers the data-health queries from an in-memory
table and every other query of the report empty, and the traded universe is
read by the shipped ``repo.traded_universe``, building real strategies.
``tests/integration/test_jev_forward.py`` holds that reading to the worker's on
Postgres.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import Any

from src.programme import repo, reports

SESSION = date(2026, 9, 25)


class _Conn:
    """
    ``daily_bars`` as ``(symbol, session)`` pairs and ``deployments`` as rows;
    every other query the report makes answers empty, which it already
    handles, so what varies is the one thing under test.
    """

    def __init__(
        self,
        bars: list[tuple[str, date]],
        deployments: list[dict[str, Any]] | None = None,
    ) -> None:
        self.bars = bars
        self.deployments = deployments or []
        self.owners: list[str] = []

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        if "FROM deployments" in query:
            assert "status = 'enabled'" in query
            (owner,) = args
            self.owners.append(owner)
            return self.deployments
        if "MAX(session) AS latest" in query:
            symbols, session = args
            latest: dict[str, date] = {}
            for symbol, day in self.bars:
                if symbol in symbols and day <= session:
                    latest[symbol] = max(day, latest.get(symbol, day))
            return [{"symbol": s, "latest": d} for s, d in sorted(latest.items())]
        return []

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        if "COUNT(*) AS n" in query and "daily_bars" in query:
            (session,) = args
            stored = [(s, d) for s, d in self.bars if d <= session]
            return {"n": len(stored), "symbols": len({s for s, _ in stored})}
        return None

    async def fetchval(self, query: str, *args: Any) -> None:
        return None


def _deployment(ident: str, symbols: list[str] | None, name: str = "buy_and_hold"):
    params = {} if symbols is None else {"symbols": symbols}
    return {"id": ident, "strategy_name": name, "params": json.dumps(params)}


def _report(conn: _Conn) -> reports.DailyReport:
    return asyncio.run(reports.build_daily_report(conn, SESSION))


def _market_actions(report: reports.DailyReport) -> list[str]:
    return [a for a in report.actions if "market data" in a or "deployment" in a]


class TestTheLatestSessionIsTheTradedUniverses:
    def test_a_fresh_reference_row_does_not_make_stale_traded_data_current(
        self,
    ) -> None:
        """
        The case the item names: the reference sleeves current, the traded
        symbol ten sessions behind. Read across every symbol, this said 0.
        """
        conn = _Conn(
            [
                ("EFA", date(2026, 9, 10)),
                ("SPY", SESSION),
                ("IEF", SESSION),
                ("GSG", SESSION),
            ],
            [_deployment("d1", ["SPY", "EFA"])],
        )
        health = _report(conn).data_health
        assert health["latest_session"] == "2026-09-10"
        assert health["sessions_behind"] == 15
        assert health["traded_symbols"] == ["EFA", "SPY"]
        assert conn.owners == ["default"], "only the operator's book is traded"
        (action,) = _market_actions(_report(conn))
        assert action.startswith("the traded universe's market data is 15 day(s)")

    def test_current_traded_data_is_current(self) -> None:
        conn = _Conn(
            [("SPY", SESSION), ("EFA", SESSION), ("GSG", date(2026, 9, 1))],
            [_deployment("d1", ["SPY"]), _deployment("d2", ["EFA"])],
        )
        report = _report(conn)
        assert report.data_health["latest_session"] == SESSION.isoformat()
        assert report.data_health["sessions_behind"] == 0
        assert report.data_health["note"] is None
        assert _market_actions(report) == []

    def test_the_table_is_still_counted_whole(self) -> None:
        conn = _Conn(
            [("SPY", SESSION), ("IEF", SESSION), ("IEF", date(2026, 9, 24))],
            [_deployment("d1", ["SPY"])],
        )
        health = _report(conn).data_health
        assert (health["rows"], health["symbols"]) == (3, 2)


class TestWhatCannotBeReadIsNotCurrent:
    def test_nothing_traded_has_no_latest_session(self) -> None:
        """
        Bars stored and no deployment enabled: nothing reads them for a
        decision, so there is no session to be behind, and no action.
        """
        report = _report(_Conn([("SPY", SESSION), ("IEF", SESSION)]))
        health = report.data_health
        assert health["latest_session"] is None
        assert health["sessions_behind"] is None
        assert "no deployment of the operator's is enabled" in health["note"]
        assert _market_actions(report) == []

    def test_an_unreadable_deployment_is_unknown_never_current(self) -> None:
        conn = _Conn(
            [("SPY", SESSION)],
            [
                _deployment("d1", ["SPY"]),
                _deployment("d2", [], name="buy_and_hold"),
            ],
        )
        report = _report(conn)
        health = report.data_health
        assert health["latest_session"] is None, "a universe half-read is not current"
        assert health["unreadable_deployments"] == ["d2"]
        assert "d2" in health["note"]
        (action,) = _market_actions(report)
        assert "d2" in action and "cannot be built" in action

    def test_a_traded_symbol_without_a_bar_is_an_action(self) -> None:
        conn = _Conn([("SPY", SESSION)], [_deployment("d1", ["SPY", "QQQ"])])
        report = _report(conn)
        assert report.data_health["missing_symbols"] == ["QQQ"]
        assert report.data_health["latest_session"] is None
        (action,) = _market_actions(report)
        assert action.startswith("no market data ingested for QQQ")

    def test_no_bars_at_all_is_the_action_it_always_was(self) -> None:
        report = _report(_Conn([], [_deployment("d1", ["SPY"])]))
        assert report.data_health["rows"] == 0
        assert "no market data ingested at all" in report.actions
        assert report.data_health["note"] == (
            "no market data has been ingested; nothing can decide"
        )


class TestTheTradedUniverseIsTheWorkers:
    def test_it_builds_each_strategy_and_asks_its_universe(self) -> None:
        conn = _Conn([], [_deployment("d1", ["SPY"]), _deployment("d2", ["EFA"])])
        universe = asyncio.run(repo.traded_universe(conn))
        assert universe == repo.TradedUniverse(frozenset({"SPY", "EFA"}), ())

    def test_a_strategy_that_cannot_be_built_is_named(self) -> None:
        conn = _Conn(
            [],
            [
                _deployment("d1", ["SPY"]),
                _deployment("d2", None, name="a_strategy_nobody_registered"),
            ],
        )
        universe = asyncio.run(repo.traded_universe(conn))
        assert universe.symbols == frozenset({"SPY"})
        assert universe.unreadable == ("d2",)

    def test_it_reads_the_operators_rows_only(self) -> None:
        assert repo.TRADED_OWNER == "default"
