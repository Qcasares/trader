"""
test_jev_table_boundaries.py
----------------------------
Who may name the Jev tables, and who may write the signals.

Two of the enforcements the proposed Rule 5 amendment rests on
(docs/08-jev-integration.md, "The Rule 5 amendment"). Both are about SQL, which
an import scan cannot see: a query is a string, and a module that never imports
``jev_repo`` can still ``SELECT`` from ``jev_answers`` or ``INSERT`` into
``jev_signals`` through the connection every process already holds.

* **Only ``src/db/repos/signals.py`` names a Jev table outside the programme.**
  The decision path is to reach typed Jev answers through that one reader, with
  its filter fixed — decision lane, internal provenance, available before the
  decision's cutoff, the area switch on. A second reader anywhere else would be
  a second filter, and the amendment's guarantee would hold only as long as the
  two agreed. The file does not exist yet (phase F); until it does, nothing
  outside ``src/programme`` may name a Jev table at all.
* **Only ``jev_lane`` writes ``jev_signals``.** A signal's origin is checked by
  a trigger (``jev_signals_rest_on_their_answer``), but which code may write one
  is checked here. The model-holding runners — ``client``, ``author``,
  ``panel`` and ``tick`` — may not even name the table, so on the signal path
  the cascade ends at Jev.

The scan reads string literals, f-string parts included, because that is where
SQL lives; a table named in an identifier or a comment is not a query. Each
scanner is also run over synthetic sources that must trip it, so a scanner
that quietly finds nothing fails its own test first.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
PROGRAMME = SRC / "programme"

#: Every table migration 0012 created for Jev.
JEV_TABLES = (
    "jev_requests",
    "jev_answers",
    "web_documents",
    "jev_signals",
    "jev_labels",
    "jev_evaluations",
)

#: The one module outside ``src/programme`` that may name a Jev table: the
#: decision path's reader, arriving in phase F.
SIGNALS_READER = SRC / "db" / "repos" / "signals.py"

#: The one module that may write ``jev_signals``.
SIGNALS_WRITER = PROGRAMME / "jev_lane.py"

#: The runners that hold a generative model client, which may not name the
#: signals table at all.
MODEL_RUNNERS = tuple(
    PROGRAMME / f"{name}.py" for name in ("client", "author", "panel", "tick")
)

_TABLE = re.compile(r"\b(" + "|".join(JEV_TABLES) + r")\b")
_SIGNAL_WRITE = re.compile(
    r"\b(?:insert\s+into|update|delete\s+from|copy|truncate(?:\s+table)?|merge\s+into)"
    r"\s+(?:only\s+)?(?:\"?\w+\"?\.)?\"?jev_signals\"?(?![\w])",
    re.IGNORECASE,
)


def _strings(source: str) -> list[tuple[int, str]]:
    """Every string literal in ``source``, with f-string parts joined."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.JoinedStr):
            text = "".join(
                part.value
                for part in node.values
                if isinstance(part, ast.Constant) and isinstance(part.value, str)
            )
            found.append((node.lineno, text))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.append((node.lineno, node.value))
    return found


def _tables_named(source: str) -> list[str]:
    return [
        f"line {line}: {match}"
        for line, text in _strings(source)
        for match in _TABLE.findall(text)
    ]


def _signal_writes(source: str) -> list[str]:
    return [
        f"line {line}: {match.group(0)}"
        for line, text in _strings(source)
        for match in _SIGNAL_WRITE.finditer(text)
    ]


def _python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _label(path: Path) -> str:
    return str(path.relative_to(ROOT))


# ---------------------------------------------------------------------------
# The rules, on the real tree
# ---------------------------------------------------------------------------


def test_only_the_signals_reader_names_a_jev_table_outside_the_programme() -> None:
    offenders = [
        f"{_label(path)} {named}"
        for path in _python_files(SRC)
        if PROGRAMME not in path.parents and path != SIGNALS_READER
        for named in _tables_named(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        "a module outside src/programme names a Jev table, which makes it a "
        "second reader of model output beside src/db/repos/signals.py:\n"
        + "\n".join(offenders)
    )


def test_only_the_lane_writes_signals() -> None:
    offenders = [
        f"{_label(path)} {write}"
        for path in _python_files(SRC)
        if path != SIGNALS_WRITER
        for write in _signal_writes(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        "a module other than src/programme/jev_lane.py writes jev_signals:\n"
        + "\n".join(offenders)
    )


def test_the_model_runners_never_name_the_signals() -> None:
    for path in MODEL_RUNNERS:
        assert path.is_file(), f"{_label(path)} is missing; update MODEL_RUNNERS"
        assert "jev_signals" not in path.read_text(encoding="utf-8"), (
            f"{_label(path)} names jev_signals. A module holding a generative "
            "model client must not be able to write, or even query, a signal: "
            "on the signal path the cascade ends at Jev."
        )


def test_the_scans_read_the_tree_they_claim() -> None:
    """Guards the guards: the programme names the tables, and the scan sees it."""
    seen = {
        table
        for path in _python_files(PROGRAMME)
        for named in _tables_named(path.read_text(encoding="utf-8"))
        for table in _TABLE.findall(named)
    }
    assert {"jev_requests", "jev_answers"} <= seen, seen
    assert (ROOT / "migrations" / "0012_jev.sql").is_file()
    migration = (ROOT / "migrations" / "0012_jev.sql").read_text(encoding="utf-8")
    for table in JEV_TABLES:
        assert re.search(rf"CREATE TABLE[^;]*\b{table}\b", migration), table


# ---------------------------------------------------------------------------
# The scanners, on sources that must trip them
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        'await conn.fetch("SELECT * FROM jev_answers")',
        'SQL = "select value from jev_signals where session = $1"',
        'q = f"SELECT {cols} FROM jev_requests WHERE lane = {lane!r}"',
        'await conn.execute("DELETE FROM web_documents")',
        '"""Reads jev_labels."""',
    ],
)
def test_the_table_scan_finds_each_spelling(source: str) -> None:
    assert _tables_named(source)


@pytest.mark.parametrize(
    "source",
    [
        "jev_signals_rest_on_their_answer = 1",
        "# SELECT * FROM jev_answers",
        'name = "jev_signals_view"',
        'kind = "jev_probe"',
    ],
)
def test_the_table_scan_ignores_what_is_not_a_query(source: str) -> None:
    assert _tables_named(source) == []


@pytest.mark.parametrize(
    "source",
    [
        'await conn.execute("INSERT INTO jev_signals (signal) VALUES ($1)")',
        'await conn.execute("insert into public.jev_signals values ($1)")',
        'await conn.execute("UPDATE jev_signals SET value = $1")',
        'await conn.execute(f"DELETE FROM jev_signals WHERE session = {s}")',
        'await conn.execute("TRUNCATE TABLE jev_signals")',
        'await conn.copy_records_to_table("x", records=r); q = "COPY jev_signals"',
        "await conn.execute('INSERT INTO \"jev_signals\" VALUES ($1)')",
    ],
)
def test_the_write_scan_finds_each_spelling(source: str) -> None:
    assert _signal_writes(source)


@pytest.mark.parametrize(
    "source",
    [
        'await conn.fetch("SELECT * FROM jev_signals")',
        'await conn.execute("INSERT INTO jev_signals_audit VALUES ($1)")',
        'await conn.execute("UPDATE jev_answers SET valid = false")',
    ],
)
def test_the_write_scan_ignores_what_does_not_write_signals(source: str) -> None:
    assert _signal_writes(source) == []
