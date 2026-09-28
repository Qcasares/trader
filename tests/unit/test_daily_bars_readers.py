"""
test_daily_bars_readers.py
--------------------------
Who reads ``daily_bars``, what each reads, and that no old row is read as
money.

The live ingest refetches each symbol it owns over its whole stored span, and
the reference job does the same for the symbols it owns, so every stored row
takes the ``adj_close`` of the latest fetch that returned it: a signal read
from the table is the signal a backtest of the same days computes. Raw prices
are another matter. Yahoo's ``Close`` is split-adjusted, so each fetch carries
a split into the raw open, high, low and close of every earlier session. The
ingests refresh raw prices whole only inside ``INGEST_LOOKBACK_DAYS``, as the
ingest always did, and leave an older row's as first written, but a split
inside that window still reprices its rows, as it always has — so anything that
read an old row's close as money could see that money change after the fact.

Nothing does, and this file holds that two ways.

* **The inventory.** Every SQL statement in the product that reads or writes
  the table is named below by file and function, with what it reads and what
  an old row is to it. A statement the inventory does not name fails the build
  until someone has written down what it reads, and a name that no longer
  matches a statement fails it too, so the account cannot go stale.
* **The property.** The one reader whose old rows reach a decision is the live
  panel, which the decision and the dry run both read through
  ``Driver.decide``. For every registered strategy, scrambling the raw prices
  of every row before the session — as a split would, and worse — leaves the
  orders exactly where they were: money is sized from the session's own close
  (``Driver._prices``) and a strategy reads history only as ``adj_close``.
  Scrambling the session's own close moves them, which is what shows the
  harness can see a raw price at all.

The scan reads string literals, f-string parts included, and the one text a
``+`` chain or a ``str.join`` of literals assembles, because that is where SQL
lives; SQL's ``TABLE daily_bars`` shorthand as a read; and asyncpg's table
copies, which take the table as an argument and hold no SQL at all, a copy of
a table it cannot read counted as one of this. It reads spellings, and is not
a sandbox. It covers ``src/``, ``api/``, ``scripts/`` and the entry points a
workflow runs with the database credential — the trees
``test_jev_table_boundaries`` reads.
"""

from __future__ import annotations

import ast
import dataclasses
import random
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType

import pytest

from src.core.clock import SimClock
from src.core.panel import PricePanel
from src.core.types import Bar, PortfolioState, Position
from src.data import SyntheticSource, bars_to_rows
from src.data.synthetic import SymbolSpec
from src.engine import Driver, DriverConfig
from src.execution.simulated import SimulatedBroker
from src.strategies import build_strategy, list_strategies
from tests.unit.test_import_boundaries import _assembled

ROOT = Path(__file__).resolve().parents[2]

SCANNED_TREES = (ROOT / "src", ROOT / "api", ROOT / "scripts")
SCANNED_ENTRY_POINTS = (ROOT / "tests" / "e2e" / "broker_check.py",)

_TABLE = r"""(?:only\s+)?(?:"?\w+"?\.)?"?daily_bars"?(?![\w])"""
#: A query reading the table. The SELECT is required as well as the FROM, so
#: prose such as "computable from daily_bars volume" is not read as a query.
_READ = re.compile(rf"(?s)\bselect\b.*\b(?:from|join)\s+{_TABLE}", re.IGNORECASE)
#: ``TABLE daily_bars``, SQL's shorthand for ``SELECT * FROM daily_bars``,
#: where a statement or a subquery can start, so prose about "the table
#: daily_bars" is not read as one.
_READ_TABLE = re.compile(
    rf"(?:^|[;(]|\bunion(?:\s+all)?|\bintersect|\bexcept)\s*table\s+{_TABLE}",
    re.IGNORECASE,
)
_WRITE = re.compile(
    r"\b(?:insert\s+into|update|delete\s+from|copy|truncate(?:\s+table)?"
    r"|merge\s+into|drop\s+table(?:\s+if\s+exists)?"
    rf"|alter\s+table(?:\s+if\s+exists)?)\s+{_TABLE}",
    re.IGNORECASE,
)

#: asyncpg's table-copying calls, which take the table as an argument and
#: build the SQL inside the driver, so no string anywhere names the read or
#: the write: what each is, by the method's name.
COPY_CALLS = MappingProxyType(
    {
        "copy_from_table": "read",
        "copy_to_table": "write",
        "copy_records_to_table": "write",
    }
)

#: What an old row is to each reader, by the function that holds the query.
READERS: dict[tuple[str, str], str] = {
    ("src/worker/live_job.py", "_load_panel"): (
        "open, high, low, close, volume and adj_close for a strategy's universe "
        "up to the session: the panel the live decision and the dry run read "
        "through Driver.decide. An old row reaches a strategy only as "
        "adj_close; money is the session's own close (Driver._prices), which "
        "sizes the orders and prices the risk gate. Held below for every "
        "registered strategy."
    ),
    ("src/worker/shadow_job.py", "_price_map"): (
        "open and close from the first applied shadow decision to the session, "
        "to fill and mark the replayed shadow book. Old rows price a "
        "hypothetical book, never money: the replay writes no order, fill or "
        "mark (test_shadow.py asserts the orders table stays empty), a "
        "shadow_decisions row is written once and never rewritten, and the "
        "book's equity is labelled as proving operation, not performance. The "
        "ingests leave raw prices older than INGEST_LOOKBACK_DAYS as first "
        "written, so a split reprices at most that window of a replay, as it "
        "always did (tests/integration/test_reference_bars.py)."
    ),
    ("src/worker/maintenance_jobs.py", "_stored_coverage"): (
        "each symbol's first and latest stored session, its row count, and "
        "whether the job's session is stored, to plan a refetch and to know "
        "which sleeves have their close; no price"
    ),
    ("src/worker/maintenance_jobs.py", "_stored_keys"): (
        "the stored (symbol, session) pairs in a span, to count the rows a "
        "fetch left behind; no price"
    ),
    ("src/programme/repo.py", "load_facts"): (
        "rows per symbol in a candidate's window, for gate 0 -> 1; no price"
    ),
    ("src/programme/reports.py", "_data_health"): (
        "rows and symbols across the table, and the newest session of each "
        "symbol the operator's enabled deployments trade, for the report's data "
        "health; no price"
    ),
    ("src/programme/jev_clock.py", "load_regime_panel"): (
        "adj_close alone, of the reference sleeves under REFERENCE_SOURCE, "
        "dated from REFERENCE_WINDOW_DAYS before the session to the session "
        "itself: the forward clock's regime state, labels computed from ratios "
        "and log returns, which leave the programme as labels and never reach "
        "money. No raw price is read; the panel's raw fields are NaN"
    ),
    ("scripts/deployment_status.py", "_report_database"): (
        "rows and the first and last session per symbol; no price"
    ),
}

#: The only writers: the two ingests, both in the worker.
WRITERS: dict[tuple[str, str], str] = {
    ("src/worker/maintenance_jobs.py", "_refresh_bars"): (
        "both ingests' refresh of a span: a row inside INGEST_LOOKBACK_DAYS "
        "replaced whole, as ever; an older stored row only its adj_close; a "
        "missing row inserted"
    ),
    ("src/worker/maintenance_jobs.py", "_insert_missing_bars"): (
        "the reference job's backfill of a symbol the live ingest owns: "
        "ON CONFLICT DO NOTHING, so no stored row changes, and ending before "
        "the live ingest's lookback, so it never writes the session's close"
    ),
}


def _texts(node: ast.AST) -> list[str]:
    """
    The strings a node holds: a literal, an f-string with its parts joined,
    or the one text a ``+`` chain or a ``str.join`` of a literal list makes of
    its strings (``test_import_boundaries._assembled``), since a statement
    assembled that way names the table in no literal of its own.
    """
    if isinstance(node, ast.JoinedStr):
        return [
            "".join(
                part.value
                for part in node.values
                if isinstance(part, ast.Constant) and isinstance(part.value, str)
            )
        ]
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    assembled = _assembled(node)
    return [assembled] if assembled is not None else []


def _copied(node: ast.AST) -> str | None:
    """
    ``"read"`` or ``"write"`` for an asyncpg table copy of the table, or of a
    table named by anything but a literal, which is counted too: a statement
    the scan cannot read is one it cannot say reads no price.
    """
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
    if name not in COPY_CALLS:
        return None
    table = node.args[0] if node.args else None
    for keyword in node.keywords:
        if keyword.arg == "table_name":
            table = keyword.value
    if (
        isinstance(table, ast.Constant)
        and isinstance(table.value, str)
        and not re.search(r'(?:^|\.)"?daily_bars"?$', table.value)
    ):
        return None
    return COPY_CALLS[name]


def _statements(source: str) -> set[tuple[str, str]]:
    """``(function, "read" | "write")`` for each statement naming the table."""
    found: set[tuple[str, str]] = set()

    def visit(node: ast.AST, function: str) -> None:
        for child in ast.iter_child_nodes(node):
            inner = (
                child.name
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
                else function
            )
            for text in _texts(child):
                if _READ.search(text) or _READ_TABLE.search(text):
                    found.add((inner, "read"))
                if _WRITE.search(text):
                    found.add((inner, "write"))
            copied = _copied(child)
            if copied is not None:
                found.add((inner, copied))
            if not isinstance(child, ast.JoinedStr):
                visit(child, inner)

    visit(ast.parse(source), "<module>")
    return found


def _scanned() -> list[Path]:
    files = [
        path
        for tree in SCANNED_TREES
        for path in sorted(tree.rglob("*.py"))
        if "__pycache__" not in path.parts
    ]
    return files + [path for path in SCANNED_ENTRY_POINTS if path.is_file()]


def _every_statement() -> set[tuple[str, str, str]]:
    return {
        (str(path.relative_to(ROOT)), function, kind)
        for path in _scanned()
        for function, kind in _statements(path.read_text(encoding="utf-8"))
    }


# ---------------------------------------------------------------------------
# The inventory
# ---------------------------------------------------------------------------


def test_every_reader_of_the_table_is_accounted_for() -> None:
    found = {(f, fn) for f, fn, kind in _every_statement() if kind == "read"}
    unaccounted = sorted(found - set(READERS))
    gone = sorted(set(READERS) - found)
    assert not unaccounted, (
        "a statement reads daily_bars that this inventory does not account "
        "for. Say what it reads and whether an old row reaches money through "
        f"it, since the ingest re-bases old rows: {unaccounted}"
    )
    assert not gone, f"the inventory names readers that no longer read: {gone}"


def test_only_the_two_ingests_write_the_table() -> None:
    found = {(f, fn) for f, fn, kind in _every_statement() if kind == "write"}
    assert found == set(WRITERS), (
        "daily_bars is written somewhere other than the worker's two ingests, "
        f"or one of them moved: {sorted(found ^ set(WRITERS))}"
    )


@pytest.mark.parametrize(
    "source, expected",
    [
        (
            'async def f(c):\n    await c.fetch("SELECT close FROM daily_bars")',
            {("f", "read")},
        ),
        (
            'def g():\n    return f"SELECT {cols} FROM public.daily_bars"',
            {("g", "read")},
        ),
        (
            'SQL = """INSERT INTO daily_bars (symbol) VALUES ($1)"""',
            {("<module>", "write")},
        ),
        (
            "class C:\n    async def h(self, c):\n"
            '        await c.execute("UPDATE daily_bars SET close = 1")',
            {("h", "write")},
        ),
        (
            "async def k(c):\n"
            '    await c.fetch("SELECT 1 FROM x JOIN daily_bars b ON true")',
            {("k", "read")},
        ),
        (
            'async def m(c):\n    await c.execute("DROP TABLE IF EXISTS daily_bars")',
            {("m", "write")},
        ),
        (
            'async def n(c):\n    await c.execute("ALTER TABLE daily_bars ADD x int")',
            {("n", "write")},
        ),
        # asyncpg's table copies name the table as an argument, not in SQL.
        (
            "async def _closes(conn, out):\n"
            '    await conn.copy_from_table("daily_bars", columns=["close"], '
            "output=out)",
            {("_closes", "read")},
        ),
        (
            "async def _export(conn, out):\n"
            '    await conn.copy_from_table(table_name="public.daily_bars", '
            "output=out)",
            {("_export", "read")},
        ),
        (
            "async def _load(conn, rows):\n"
            '    await conn.copy_records_to_table("daily_bars", records=rows)',
            {("_load", "write")},
        ),
        (
            "async def _any(conn, table, out):\n"
            "    await conn.copy_from_table(table, output=out)",
            {("_any", "read")},
        ),
        # SQL's TABLE shorthand for SELECT * FROM.
        (
            'async def _all(conn):\n    return await conn.fetch("TABLE daily_bars")',
            {("_all", "read")},
        ),
        (
            "async def _both(conn):\n"
            '    return await conn.fetch("SELECT * FROM x UNION TABLE daily_bars")',
            {("_both", "read")},
        ),
        # A statement assembled from literals, the table in none of them alone.
        (
            "async def _joined(conn):\n"
            '    await conn.execute(" ".join(["INSERT INTO", "daily_bars", '
            '"VALUES ($1)"]))',
            {("_joined", "write")},
        ),
        (
            "async def _added(conn):\n"
            '    await conn.execute("INSERT INTO" + " daily_bars VALUES ($1)")',
            {("_added", "write")},
        ),
        (
            "async def _read(conn):\n"
            '    return await conn.fetch("SELECT close FROM " + "daily_bars")',
            {("_read", "read")},
        ),
    ],
)
def test_the_scan_finds_each_statement(source: str, expected: set) -> None:
    assert _statements(source) == expected


@pytest.mark.parametrize(
    "source",
    [
        '"""Reads ``daily_bars``; the worker writes into ``daily_bars``."""',
        'note = "computable from daily_bars volume; not wired to this card"',
        'Evidence("daily_bars", "SPY", {})',
        'await c.fetch("SELECT * FROM daily_bars_audit")',
        "# SELECT close FROM daily_bars",
        '"""Every row of the table daily_bars is refreshed."""',
        'await c.copy_from_table("fills", output=out)',
        'await c.execute("DROP TABLE IF EXISTS daily_bars_old")',
        'label = "Prices: " + "daily_bars"',
    ],
)
def test_the_scan_ignores_what_is_not_a_statement_on_the_table(source: str) -> None:
    assert _statements(source) == set()


# ---------------------------------------------------------------------------
# The property: no old raw price reaches an order
# ---------------------------------------------------------------------------

#: The first session of a month, so every monthly strategy rebalances.
SESSION = date(2012, 6, 1)
HISTORY_START = date(2007, 1, 3)


def _bars(universe: list[str]) -> list[Bar]:
    specs = tuple(
        SymbolSpec(symbol, date(1995, 1, 3), 40.0 + 7 * i, 0.07 - 0.01 * i, 0.18, 0.02)
        for i, symbol in enumerate(universe)
    )
    source = SyntheticSource(specs=specs, apply_regimes=False)
    return source.fetch(universe, HISTORY_START, SESSION)


def _rescaled(bars: list[Bar], which: str) -> list[Bar]:
    """
    Raw prices rescaled row by row: ``"before"`` every row before the session,
    ``"on"`` the session's own. ``adj_close`` is untouched.
    """
    rng = random.Random(20260927)
    out = []
    for bar in bars:
        if (bar.session < SESSION) if which == "before" else (bar.session == SESSION):
            factor = rng.uniform(0.2, 5.0)
            bar = dataclasses.replace(
                bar,
                open=bar.open * factor,
                high=bar.high * factor,
                low=bar.low * factor,
                close=bar.close * factor,
                volume=bar.volume / factor,
            )
        out.append(bar)
    return out


def _decide(strategy_name: str, bars: list[Bar], state: PortfolioState):
    strategy = build_strategy(strategy_name, {})
    panel = PricePanel.from_bars(bars_to_rows(bars), as_of=SESSION)
    driver = Driver(
        strategy, SimulatedBroker(), SimClock([SESSION]), DriverConfig(run_ref="basis")
    )
    return driver.decide(panel, SESSION, state)


def _state(universe: list[str], bars: list[Bar]) -> PortfolioState:
    """Cash and one holding, so a decision can both buy and sell."""
    held = universe[-1]
    close = next(b.close for b in bars if b.symbol == held and b.session == SESSION)
    return PortfolioState(
        cash=Decimal("60000"),
        positions={held: Position(held, Decimal("300"), Decimal("50"))},
        equity=Decimal("60000") + Decimal(str(close)) * 300,
        as_of=SESSION,
    )


@pytest.mark.parametrize("strategy_name", list_strategies())
def test_no_old_raw_price_reaches_an_order(strategy_name: str) -> None:
    universe = build_strategy(strategy_name, {}).universe()
    bars = _bars(universe)
    state = _state(universe, bars)

    as_stored = _decide(strategy_name, bars, state)
    rebased = _decide(strategy_name, _rescaled(bars, "before"), state)

    assert as_stored.rebalanced and as_stored.intents, (
        f"{strategy_name} ordered nothing on {SESSION}, so this proves nothing"
    )
    assert rebased.raw_targets == as_stored.raw_targets
    assert rebased.targets == as_stored.targets
    assert rebased.risk_events == as_stored.risk_events
    assert rebased.intents == as_stored.intents, (
        f"{strategy_name}'s orders moved when only rows before {SESSION} "
        "changed their raw prices: something on the decision path reads an old "
        "row's raw price, which a split rewrites now the ingest re-bases history"
    )


@pytest.mark.parametrize("strategy_name", list_strategies())
def test_the_sessions_own_close_does_reach_the_orders(strategy_name: str) -> None:
    """Guards the property above: the harness sees a raw price when one is read."""
    universe = build_strategy(strategy_name, {}).universe()
    bars = _bars(universe)
    state = _state(universe, bars)

    as_stored = _decide(strategy_name, bars, state)
    moved = _decide(strategy_name, _rescaled(bars, "on"), state)

    assert moved.intents != as_stored.intents
