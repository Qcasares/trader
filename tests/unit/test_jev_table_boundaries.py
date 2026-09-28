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
  the cascade ends at Jev; from phase C4 they name no Jev table at all, and
  neither do ``gates`` and ``repo``.
* **Inside the programme, one writer and one reader.** ``jev_lane`` writes the
  signals and reads none of them; ``jev_repo`` reads them and writes none; no
  other module of ``src/programme`` names the table.

The scan reads string literals, f-string parts included, because that is where
SQL lives; a table named in an identifier or a comment is not a query. A
literal that is the signals table's name and nothing else counts as a write,
because asyncpg's bulk writers take the table as a bare argument and build the
SQL inside the driver. It reads ``src/`` and the protected processes' entry
points outside it — ``api/``, ``scripts/`` and ``tests/e2e/broker_check.py`` —
the trees ``test_import_boundaries`` walks. Each scanner is also run over
synthetic sources that must trip it, so a scanner that quietly finds nothing
fails its own test first.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
PROGRAMME = SRC / "programme"

#: What the scans read: the trees and entry points that
#: ``test_import_boundaries`` walks as protected processes, since a query in the
#: API's Vercel entry point or in a script a workflow runs with the database
#: credential reads the ledger as surely as one in ``src/``.
SCANNED_TREES = (SRC, ROOT / "api", ROOT / "scripts")
SCANNED_ENTRY_POINTS = (ROOT / "tests" / "e2e" / "broker_check.py",)

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

#: A string that is the signals table's name and nothing else. asyncpg's bulk
#: writers take the table as a bare argument and build the SQL inside the
#: driver — ``copy_records_to_table("jev_signals", ...)``, ``copy_to_table`` —
#: and a constant interpolated into an f-string is the same string, so outside
#: the writer the name alone is read as a write.
_SIGNALS_NAME = re.compile(r'^\s*(?:"?\w+"?\.)?"?jev_signals"?\s*$', re.IGNORECASE)
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
    found = []
    for line, text in _strings(source):
        found += [f"line {line}: {m.group(0)}" for m in _SIGNAL_WRITE.finditer(text)]
        if _SIGNALS_NAME.match(text):
            found.append(f"line {line}: the table's name, as a bulk write takes it")
    return found


def _python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _scanned() -> list[Path]:
    files = [path for tree in SCANNED_TREES for path in _python_files(tree)]
    return files + [path for path in SCANNED_ENTRY_POINTS if path.is_file()]


def _label(path: Path) -> str:
    return str(path.relative_to(ROOT))


# ---------------------------------------------------------------------------
# The rules, on the real tree
# ---------------------------------------------------------------------------


def test_only_the_signals_reader_names_a_jev_table_outside_the_programme() -> None:
    offenders = [
        f"{_label(path)} {named}"
        for path in _scanned()
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
        for path in _scanned()
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


def test_the_model_runners_name_no_jev_table() -> None:
    """
    From phase C4 the rule above covers every Jev table, not only the signals
    (docs/08, phase C, I8): no Jev answer, no web text and no request may
    reach a generative model's prompt, and a runner that could read the
    ledger could put one there. Anywhere in the file, identifiers and comments
    included, as the rule above reads it.
    """
    for path in MODEL_RUNNERS:
        source = path.read_text(encoding="utf-8")
        named = [table for table in JEV_TABLES if re.search(rf"\b{table}\b", source)]
        assert not named, f"{_label(path)} names {named}"


#: The one module that reads ``jev_signals`` inside the programme.
SIGNALS_REPO = PROGRAMME / "jev_repo.py"

#: The programme's modules that decide promotions and hold its rows, which no
#: Jev table may reach until the phase that is to wire one in reviews it.
GATE_AND_ROWS = (PROGRAMME / "gates.py", PROGRAMME / "repo.py")

_SIGNAL_READ = re.compile(
    r"\b(?:from|join)\s+(?:only\s+)?(?:\"?\w+\"?\.)?\"?jev_signals\"?(?![\w])",
    re.IGNORECASE,
)


def test_inside_the_programme_only_the_lane_and_the_repo_name_the_signals() -> None:
    """
    One writer, ``jev_lane.record_signal``, and one reader, ``jev_repo``: every
    other module in ``src/programme`` reaches a signal through one of them, so
    a second query of the signals is a reviewer's edit to this test.
    """
    offenders = [
        f"{_label(path)} {named}"
        for path in _python_files(PROGRAMME)
        if path not in (SIGNALS_WRITER, SIGNALS_REPO)
        for named in _tables_named(path.read_text(encoding="utf-8"))
        if "jev_signals" in named
    ]
    assert not offenders, "\n".join(offenders)


def test_the_lane_writes_the_signals_and_reads_none() -> None:
    """
    ``record_signal`` reads back a row its insert found already there through
    ``jev_repo.get_signal``, so the lane holds the write and nothing else.
    """
    source = SIGNALS_WRITER.read_text(encoding="utf-8")
    reads = [
        f"line {line}: {match.group(0)}"
        for line, text in _strings(source)
        for match in _SIGNAL_READ.finditer(text)
    ]
    assert not reads, reads
    assert _signal_writes(source), "the scan no longer sees the lane's own write"


def test_the_repo_reads_the_signals_and_writes_none() -> None:
    source = SIGNALS_REPO.read_text(encoding="utf-8")
    assert _signal_writes(source) == []
    assert any(_SIGNAL_READ.search(text) for _, text in _strings(source))


def test_the_gates_and_the_programmes_rows_name_no_jev_table() -> None:
    for path in GATE_AND_ROWS:
        assert path.is_file(), _label(path)
        assert _tables_named(path.read_text(encoding="utf-8")) == [], _label(path)


@pytest.mark.parametrize(
    ("source", "reads"),
    [
        ('await conn.fetch("SELECT * FROM jev_signals")', True),
        ('q = "SELECT s.value FROM x JOIN public.jev_signals s ON true"', True),
        ('await conn.execute("INSERT INTO jev_signals (signal) VALUES ($1)")', False),
        ('await conn.fetch("SELECT * FROM jev_signals_audit")', False),
    ],
)
def test_the_read_scan_finds_a_read(source: str, reads: bool) -> None:
    found = any(_SIGNAL_READ.search(text) for _, text in _strings(source))
    assert found is reads


def test_the_scans_read_the_entry_points_too() -> None:
    """The protected processes' entry points outside ``src/`` are read."""
    scanned = set(_scanned())
    for path in (
        ROOT / "api" / "index.py",
        ROOT / "scripts" / "deployment_status.py",
        ROOT / "tests" / "e2e" / "broker_check.py",
        SRC / "db" / "migrate_cli.py",
    ):
        assert path in scanned, _label(path)


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
        'q = "COPY jev_signals FROM STDIN"',
        "await conn.execute('INSERT INTO \"jev_signals\" VALUES ($1)')",
        'await conn.copy_records_to_table("jev_signals", records=r)',
        'await conn.copy_records_to_table(table_name="jev_signals", records=r)',
        'await conn.copy_to_table("jev_signals", source=f, schema_name="public")',
        'T = "jev_signals"\nawait conn.execute(f"INSERT INTO {T} VALUES ($1)")',
        'await conn.copy_records_to_table("public.jev_signals", records=r)',
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
        'await conn.copy_records_to_table("jev_signals_audit", records=r)',
    ],
)
def test_the_write_scan_ignores_what_does_not_write_signals(source: str) -> None:
    assert _signal_writes(source) == []
