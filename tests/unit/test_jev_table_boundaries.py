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
* **Web text is written by one module, and quarantined by one statement.**
  From phase C6, only ``jev_repo`` writes ``web_documents`` — its
  ``insert_documents``, for the ingest job, and ``quarantine_content``, the
  one update the table's trigger allows — and no other function anywhere
  updates it, so quarantine stays one-way and by content wherever it is
  decided.
* **Labels are written by one module.** From phase C7, only ``jev_repo``
  writes ``jev_labels``, by its two inserts — ``record_label`` and the web
  ingest's ``record_label_once`` — so no label, which is ground truth, is
  written by a path nobody reviewed, and none is ever rewritten.
* **A finding says who wrote it, and what was raised stays raised.** From
  phase D1 (migration 0015), every insert into ``findings`` names its
  ``origin``, ``repo.raise_finding`` takes it keyword-only with no default,
  its two callers pass ``'model'`` (the tick) and ``'operator'`` (the API) as
  literals, and the one update of the table sets the closure's columns alone.

The scan reads strings, because that is where SQL lives: literals, f-strings,
and the one text a chain of ``+`` or a ``str.join`` of literals assembles,
since a statement assembled that way names its table in no literal of its own;
a table named in an identifier or a comment is not a query. The writes are read
by ``test_import_boundaries._table_writes``, the scanner that holds
``daily_bars`` to the worker, with the table as its argument: a write whose
table it cannot read — interpolated, formatted, a verb whose table is joined
on from elsewhere, a bulk writer handed a name — counts as a write of the
table, since it could be one; an insert that goes on ``ON CONFLICT … DO
UPDATE`` counts as an update; and a string that is the table's name and
nothing else counts as a write, because asyncpg's bulk writers take the table
as a bare argument and build the SQL inside the driver. The first cut read
each literal on its own, and a second writer of ``web_documents``, or a second
update of it, assembled by ``+`` passed both of its rules (C6's review). It
reads ``src/`` and the protected processes' entry points outside it —
``api/``, ``scripts/`` and ``tests/e2e/broker_check.py`` — the trees
``test_import_boundaries`` walks. Each scanner is also run over synthetic
sources that must trip it, so a scanner that quietly finds nothing fails its
own test first. It reads spellings, and is not a sandbox.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import re
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_import_boundaries import _assembled, _synthetic, _table_writes

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


def _strings(source: str) -> list[tuple[int, str]]:
    """
    Every string literal in ``source``, f-string parts joined, and the one
    text each chain of ``+`` or ``str.join`` of literals assembles
    (``test_import_boundaries._assembled``), since a query assembled that way
    names its table in no literal of its own.
    """
    tree = ast.parse(source)
    inner = {
        id(side)
        for node in ast.walk(tree)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add)
        for side in (node.left, node.right)
        if isinstance(side, ast.BinOp) and isinstance(side.op, ast.Add)
    }
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            text = "".join(
                part.value
                for part in node.values
                if isinstance(part, ast.Constant) and isinstance(part.value, str)
            )
            found.append((node.lineno, text))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.append((node.lineno, node.value))
        elif id(node) not in inner and (assembled := _assembled(node)) is not None:
            found.append((node.lineno, assembled))
    return found


def _tables_named(source: str) -> list[str]:
    return [
        f"line {line}: {match}"
        for line, text in _strings(source)
        for match in _TABLE.findall(text)
    ]


def _signal_writes(source: str) -> list[str]:
    """
    Every write of ``jev_signals`` in ``source``, and every write whose table
    the scan cannot read, which could be one (``_table_writes``). A string
    that is the table's name and nothing else counts too: asyncpg's bulk
    writers take the table bare — ``copy_records_to_table("jev_signals",
    ...)``, ``copy_to_table`` — and build the SQL inside the driver.
    """
    return [
        f"line {write.line}: {write.verb} {write.shown}"
        for write in _table_writes(source, "jev_signals", bare_name=True)
    ]


#: The one module that may write ``web_documents``, and the one function in it
#: that may update the table: the one-way quarantine by content.
DOCUMENTS_WRITER = PROGRAMME / "jev_repo.py"
QUARANTINE_FUNCTION = "quarantine_content"

#: Every write ``jev_repo`` makes to ``web_documents``: the function it is in
#: and the statement's verb. Nothing else, there or anywhere.
DOCUMENTS_WRITES = frozenset(
    {("insert_documents", "insert into"), (QUARANTINE_FUNCTION, "update")}
)


#: The one module that writes ``jev_labels`` (phase C7), and every write it
#: makes: ``record_label``, for a label written once, and
#: ``record_label_once``, the web ingest's, which a labeller that has labelled
#: the item already leaves as it was.
LABELS_WRITER = PROGRAMME / "jev_repo.py"
LABELS_WRITES = frozenset(
    {("record_label", "insert into"), ("record_label_once", "insert into")}
)


#: The one module that writes ``jev_evaluations`` (phase C9), and its one
#: write: ``record_evaluation``, for ``jev_eval evaluate --record``.
EVALUATIONS_WRITER = PROGRAMME / "jev_repo.py"
EVALUATIONS_WRITES = frozenset({("record_evaluation", "insert into")})


def _evaluation_writes(source: str) -> list[tuple[int, str, str | None]]:
    """
    Every write of ``jev_evaluations`` in ``source``, and every write whose
    table the scan cannot read, which could be one (``_table_writes``).
    """
    return [
        (write.line, write.verb, write.function)
        for write in _table_writes(source, "jev_evaluations", bare_name=True)
    ]


def _label_writes(source: str) -> list[tuple[int, str, str | None]]:
    """
    Every write of ``jev_labels`` in ``source``, and every write whose table
    the scan cannot read, which could be one (``_table_writes``, as for
    ``web_documents`` below).
    """
    return [
        (write.line, write.verb, write.function)
        for write in _table_writes(source, "jev_labels", bare_name=True)
    ]


def _document_writes(source: str) -> list[tuple[int, str, str | None]]:
    """
    Every write of ``web_documents`` in ``source``, and every write whose
    table the scan cannot read, which could be one: its line, its verb, and
    the function it is in (``_table_writes``). An insert that goes on
    ``ON CONFLICT ... DO UPDATE`` is an update as well, and a string that is
    the table's name and nothing else counts, verb ``bulk``, as asyncpg's bulk
    writers take the table bare.
    """
    return [
        (write.line, write.verb, write.function)
        for write in _table_writes(source, "web_documents", bare_name=True)
    ]


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
        "a module other than src/programme/jev_lane.py writes jev_signals, or "
        "writes a table this scan cannot read; name the table in the SQL:\n"
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


def test_only_the_repo_writes_web_documents() -> None:
    """
    Web text reaches ``web_documents`` through ``jev_repo`` alone: the ingest
    job hands it rows, and a module that wrote the table itself would store
    text by rules nobody reviewed — a second column, a title, a quarantine
    decided somewhere else. Across ``src/`` and the protected entry points.
    """
    offenders = [
        f"{_label(path)} line {line}: {verb} web_documents"
        for path in _scanned()
        if path != DOCUMENTS_WRITER
        for line, verb, _ in _document_writes(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        "a module other than src/programme/jev_repo.py writes web_documents, or "
        "writes a table this scan cannot read; name the table in the SQL:\n"
        + "\n".join(offenders)
    )


def test_only_the_repo_writes_jev_labels() -> None:
    """
    A label is ground truth, and a label a model could write would measure
    its agreement with itself: the schema refuses a model as a labeller, and
    this keeps every write of ``jev_labels`` in ``jev_repo``, whose two
    inserts the web ingest's labels and an operator's go through (phase C7).
    """
    offenders = [
        f"{_label(path)} line {line}: {verb} jev_labels"
        for path in _scanned()
        if path != LABELS_WRITER
        for line, verb, _ in _label_writes(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        "a module other than src/programme/jev_repo.py writes jev_labels, or "
        "writes a table this scan cannot read; name the table in the SQL:\n"
        + "\n".join(offenders)
    )


def test_the_repo_writes_jev_labels_by_its_two_inserts_alone() -> None:
    """No update, no upsert that rewrites a label, nothing the scan cannot read."""
    writes = _label_writes(LABELS_WRITER.read_text(encoding="utf-8"))
    assert {(function, verb) for _, verb, function in writes} == LABELS_WRITES


@pytest.mark.parametrize(
    "source",
    [
        'await conn.execute("INSERT INTO jev_labels (label) VALUES ($1)")',
        'await conn.execute("INSERT INTO public.jev_labels (label) VALUES ($1)")',
        'q = "INSERT INTO " + "jev_labels (label) VALUES ($1)"',
        'q = " ".join(["INSERT INTO", "jev_labels", "(label) VALUES ($1)"])',
        'await conn.execute(f"INSERT INTO {TABLE} (label) VALUES ($1)")',
        'await conn.copy_records_to_table("jev_labels", records=rows)',
        "await conn.execute(\"UPDATE jev_labels SET label = 'bonds'\")",
        'q = "INSERT INTO jev_labels (x) VALUES (1) ON CONFLICT (x) DO UPDATE SET x=2"',
    ],
)
def test_the_label_write_scan_finds_each_spelling(source: str) -> None:
    assert _label_writes(source), source


@pytest.mark.parametrize(
    "source",
    [
        'await conn.fetch("SELECT * FROM jev_labels")',
        '"""Labels are written to jev_labels by jev_repo alone."""',
        'await conn.execute("INSERT INTO jev_labels_audit (x) VALUES (1)")',
    ],
)
def test_the_label_write_scan_ignores_what_does_not_write_labels(source: str) -> None:
    assert _label_writes(source) == [], source


def test_only_the_repo_writes_jev_evaluations() -> None:
    """
    An evaluation is what a threshold may one day rest on, so the row that
    says how well Jev did is written by one function, ``record_evaluation``,
    which names every column, and the schema holds what it may say (migration
    0014). Nothing else in the scanned trees writes the table (phase C9).
    """
    offenders = [
        f"{_label(path)} line {line}: {verb} jev_evaluations"
        for path in _scanned()
        if path != EVALUATIONS_WRITER
        for line, verb, _ in _evaluation_writes(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        "a module other than src/programme/jev_repo.py writes jev_evaluations, "
        "or writes a table this scan cannot read; name the table in the SQL:\n"
        + "\n".join(offenders)
    )


def test_the_repo_writes_jev_evaluations_by_record_evaluation_alone() -> None:
    """Appended, never rewritten: one insert, and no update or upsert."""
    writes = _evaluation_writes(EVALUATIONS_WRITER.read_text(encoding="utf-8"))
    assert {(function, verb) for _, verb, function in writes} == EVALUATIONS_WRITES


@pytest.mark.parametrize(
    "source",
    [
        'await conn.execute("INSERT INTO jev_evaluations (n) VALUES ($1)")',
        'q = "INSERT INTO " + "jev_evaluations (n) VALUES ($1)"',
        'q = " ".join(["INSERT INTO", "jev_evaluations", "(n) VALUES ($1)"])',
        'await conn.execute(f"INSERT INTO jev_evaluations ({cols}) VALUES (1)")',
        'await conn.copy_records_to_table("jev_evaluations", records=rows)',
        'await conn.execute("UPDATE jev_evaluations SET accuracy = 0.99")',
    ],
)
def test_the_evaluation_write_scan_finds_each_spelling(source: str) -> None:
    assert _evaluation_writes(source), source


@pytest.mark.parametrize(
    "source",
    [
        'await conn.fetch("SELECT * FROM jev_evaluations")',
        '"""Evaluations are written to jev_evaluations by jev_repo alone."""',
    ],
)
def test_the_evaluation_write_scan_ignores_what_does_not_write_one(
    source: str,
) -> None:
    assert _evaluation_writes(source) == [], source


def test_the_one_update_of_web_documents_is_quarantine_content() -> None:
    """
    The repo's writes of the table are exactly its insert and its quarantine,
    and the one update is ``quarantine_content``'s, which quarantines by
    content, one-way, and touches nothing else: with the test above, it is
    the only update of ``web_documents`` in ``src/``. A second update, even
    one the trigger would pass, would be a quarantine decided by other rules —
    an ``ON CONFLICT … DO UPDATE`` on the insert among them, which the first
    cut read as an insert alone — and a write whose table the scan cannot
    read, here, would be one it cannot rule out.
    """
    writes = _document_writes(DOCUMENTS_WRITER.read_text(encoding="utf-8"))
    assert {(function, verb) for _, verb, function in writes} == DOCUMENTS_WRITES
    updates = [write for write in writes if write[1] == "update"]
    assert [function for _, _, function in updates] == [QUARANTINE_FUNCTION], updates


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
        'q = "SELECT * FROM jev_" + "answers"',
        'q = "".join(["SELECT value FROM ", "jev_", "signals"])',
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
        # Assembled, the table named in no literal alone, or not read at all.
        '_S = "INSERT INTO" + " jev_signals (signal) VALUES ($1)"',
        'q = "".join(("UPDATE ", "jev_", "signals SET value = 1"))',
        'q = "DELETE FROM jev_" + "signals"',
        'q = " ".join(["INSERT INTO", "jev_signals", "VALUES ($1)"])',
        'T = "jev_" + "signals"\nawait conn.execute(f"INSERT INTO {T} VALUES ($1)")',
        'await conn.execute("INSERT INTO " + table + " VALUES ($1)")',
        "await conn.copy_records_to_table(TABLE, records=r)",
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


@pytest.mark.parametrize(
    "source",
    [
        'await conn.execute("UPDATE web_documents SET quarantined = TRUE")',
        'await conn.execute("update public.web_documents set quarantined = true")',
        "await conn.execute('UPDATE \"web_documents\" SET quarantined = TRUE')",
        'await conn.execute("UPDATE ONLY web_documents SET quarantined = TRUE")',
        'q = f"INSERT INTO web_documents ({columns}) VALUES ($1)"',
        'await conn.execute("DELETE FROM web_documents WHERE id = $1")',
        'await conn.execute("TRUNCATE TABLE web_documents")',
        'q = "COPY web_documents FROM STDIN"',
        'q = "MERGE INTO web_documents d USING x ON true WHEN MATCHED THEN DELETE"',
        'await conn.copy_records_to_table("web_documents", records=r)',
        'T = "web_documents"\nawait conn.execute(f"UPDATE {T} SET quarantined = TRUE")',
        'await conn.execute("DROP TABLE IF EXISTS web_documents")',
        'await conn.execute("ALTER TABLE web_documents DISABLE TRIGGER ALL")',
        # Assembled from literals, the table named in none of them alone:
        # test_import_boundaries' daily_bars spellings, the table swapped.
        '_DOCS = " ".join(["INSERT INTO", "web_documents", "VALUES ($1)"])',
        '_DOCS = "INSERT INTO" + " web_documents (source) VALUES ($1)"',
        'q = "UPDATE" + " " + "web_documents SET quarantined = TRUE"',
        'q = "".join(("MERGE INTO ", "web_", "documents USING s ON true"))',
        'q = "".join(("UPDATE ", "web", "_documents SET quarantined = TRUE"))',
        'q = "UPDATE web_" + "documents SET quarantined = TRUE"',
        'q = "DELETE FROM " + f"{schema}.web_documents"',
        'q = "update" + " web_documents set quarantined = true"',
        'q = " ".join(["copy", "web_documents", "from stdin"])',
        'q = "WITH s AS (SELECT 1) INSERT INTO" + " web_documents SELECT * FROM s"',
        'Q = "INSERT INTO "\nawait conn.execute(Q + "web_documents VALUES ($1)")',
        'T = "web_" + "documents"\nawait conn.execute(f"UPDATE {T} SET x = 1")',
        # A table the scan cannot read: interpolated, formatted, handed on.
        'await conn.execute(f"UPDATE {schema}.web_documents SET quarantined = TRUE")',
        "await conn.execute(f\"UPDATE {'web_documents'} SET quarantined = TRUE\")",
        'await conn.execute("INSERT INTO " + table + " VALUES ($1)")',
        'await conn.execute("UPDATE %s SET quarantined = TRUE" % table)',
        'await conn.execute("UPDATE {} SET quarantined = TRUE".format(table))',
        "await conn.copy_records_to_table(TABLE, records=r)",
        'PARTS = ["UPDATE", TABLE, "SET quarantined = TRUE"]',
        'VERB = "TRUNCATE"',
        'await conn.execute("INSERT INTO" + TABLE + " VALUES ($1)")',
        'note = "copied " + conn.copy_records_to_table(TABLE, records=r)',
        # The bare name a bulk writer takes, however it is handed on.
        'TABLE = "public.web_documents"',
    ],
)
def test_the_documents_write_scan_finds_each_spelling(source: str) -> None:
    """
    Every spelling of a write to ``web_documents``, and of a write whose table
    the scan cannot read, which could be one: the first cut read each literal
    on its own, and a statement assembled by ``+`` or ``str.join`` named the
    table in none of them (C6's review).
    """
    assert _document_writes(source), source


@pytest.mark.parametrize(
    "source",
    [
        'await conn.fetch("SELECT * FROM web_documents WHERE quarantined")',
        'await conn.execute("UPDATE web_documents_audit SET x = 1")',
        '"""What web_documents holds, and why."""',
        'constraint = "web_documents_one_snapshot"',
        'q = "SELECT * FROM " + "web_documents"',
        'label = "Documents: " + "web_documents"',
        'note = "the next " + "update"',
        'await conn.execute("INSERT INTO jev_answers " + "VALUES ($1)")',
        'await conn.execute("INSERT INTO web_documents_audit" + " VALUES ($1)")',
        'await conn.copy_records_to_table("jev_labels", records=r)',
        '"""Where ``DO UPDATE`` would ask the trigger, and ``INSERT`` would not."""',
    ],
)
def test_the_documents_write_scan_ignores_what_does_not_write(source: str) -> None:
    assert _document_writes(source) == []


@pytest.mark.parametrize(
    ("conflict", "verbs"),
    [
        ("DO UPDATE SET quarantined = TRUE", {"insert into", "update"}),
        ("DO NOTHING", {"insert into"}),
    ],
)
def test_an_upsert_of_web_documents_is_an_update(conflict: str, verbs: set) -> None:
    """
    ``INSERT … ON CONFLICT … DO UPDATE`` on the table updates a stored document,
    which the trigger would pass for a quarantine: a second quarantine, by
    rules nobody reviewed, that the one-update rule must count. The first cut
    counted it as an insert only (C6's review). ``DO NOTHING`` updates nothing.
    """
    source = (
        "async def insert_documents(conn):\n"
        "    await conn.execute(\n"
        '        "INSERT INTO web_documents (source) VALUES ($1) "\n'
        f'        "ON CONFLICT (source, content_sha256) {conflict}"\n'
        "    )\n"
    )
    found = {(verb, function) for _, verb, function in _document_writes(source)}
    assert found == {(verb, "insert_documents") for verb in verbs}


@pytest.mark.parametrize(
    ("source", "verbs"),
    [
        ('q = "INSERT INTO" + " web_documents VALUES ($1)"', {"insert into"}),
        ('q = "".join(("UPDATE ", "web", "_documents SET x = 1"))', {"update"}),
        ("q = f\"UPDATE {'web_documents'} SET x = 1\"", {"update"}),
        ('q = f"UPDATE {schema}.web_documents SET x = 1"', {"update", "unread"}),
        ('q = "DROP TABLE IF EXISTS web_documents"', {"drop table if exists"}),
        ('await c.copy_records_to_table("public.web_documents", records=r)', {"bulk"}),
        ("await c.copy_records_to_table(T, records=r)", {"unread"}),
        ('q = "INSERT INTO " + table + " VALUES ($1)"', {"unread"}),
    ],
)
def test_the_documents_write_scan_reads_each_verb(source: str, verbs: set) -> None:
    """
    What each write is: a statement assembled from literals is read whole, as
    one statement, and a literal interpolated into an f-string as its text; a
    table the scan cannot read is ``unread``, whatever else it reads.
    """
    assert {verb for _, verb, _ in _document_writes(source)} == verbs


def test_the_documents_write_scan_names_the_function_it_is_in() -> None:
    source = (
        "async def quarantine_content(conn):\n"
        "    await conn.execute('UPDATE web_documents SET quarantined = TRUE')\n"
        "async def elsewhere(conn):\n"
        "    def nested():\n"
        "        return 'UPDATE web_documents SET quarantined = TRUE'\n"
        "    return nested()\n"
        "QUERY = 'DELETE FROM web_documents'\n"
    )
    assert [(verb, function) for _, verb, function in _document_writes(source)] == [
        ("update", "quarantine_content"),
        ("update", "nested"),
        ("delete from", None),
    ]


# ---------------------------------------------------------------------------
# findings: who wrote it, and what was raised stays raised (phase D1)
# ---------------------------------------------------------------------------
#
# Migration 0015 holds both in the schema (``findings.origin`` NOT NULL with no
# default, ``findings_keep_what_was_raised``); these hold the code to them, so
# a writer is caught in review rather than by the first insert that fails in
# production. ``tests/integration/test_phase_d_schema.py`` is the schema's side.

#: The columns a finding's closure writes, and the only ones an update of
#: ``findings`` may set (docs/09, M1).
FINDINGS_CLOSURE = frozenset({"status", "closed_at", "closed_by", "close_note"})

#: Who calls ``repo.raise_finding``, and the writer each names (docs/09, M22).
FINDING_CALLERS = frozenset(
    {
        ("src/programme/tick.py", "model"),
        ("src/api/routers/programme.py", "operator"),
    }
)

_FINDINGS_TABLE = r'(?:"?\w+"?\.)?"?findings"?'
_FINDINGS_UPDATE = re.compile(
    rf"\bupdate\s+(?:only\s+)?{_FINDINGS_TABLE}\s+set\b", re.IGNORECASE
)

#: What ends an ``UPDATE``'s ``SET`` list where it stands outside every
#: parenthesis and string literal.
_SET_LIST_END = re.compile(r"(?<![\w$])(?:where|from|returning)(?![\w$])", re.I)


def _set_list(statement: str) -> str | None:
    """
    The ``SET`` list of an ``UPDATE findings`` in ``statement``, each string
    literal in it read as an empty one, up to the ``WHERE``, ``FROM`` or
    ``RETURNING`` that ends it outside every parenthesis and literal, or a
    ``;``; ``None`` if ``statement`` updates no finding. The first cut ended
    the list at the first of those words anywhere, inside a subquery or a
    literal too, so a column set after one was never read (D1's review,
    D1RS-5).
    """
    head = _FINDINGS_UPDATE.search(statement)
    if head is None:
        return None
    text, kept, depth, index = statement, [], 0, head.end()
    while index < len(text):
        character = text[index]
        if character == "'":
            close = index + 1
            while close < len(text):
                if text.startswith("''", close):
                    close += 2
                elif text[close] == "'":
                    break
                else:
                    close += 1
            kept.append("''")
            index = close + 1
            continue
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif depth == 0 and (
            character == ";" or _SET_LIST_END.match(text, index) is not None
        ):
            break
        kept.append(character)
        index += 1
    return "".join(kept)
_FINDINGS_INSERT = re.compile(
    rf"\binsert\s+into\s+{_FINDINGS_TABLE}\s*\((?P<columns>[^)]*)\)",
    re.IGNORECASE | re.DOTALL,
)
_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]*")


def _top_level(text: str) -> list[str]:
    """``text`` split on the commas outside any parentheses."""
    parts: list[str] = []
    depth = 0
    current = ""
    for character in text:
        depth += {"(": 1, ")": -1}.get(character, 0)
        if character == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += character
    parts.append(current)
    return parts


def _identifiers(names: list[str]) -> set[str] | None:
    """The column names, unquoted and lower-cased, or ``None`` if one is not."""
    columns = {name.strip().strip('"').lower() for name in names}
    if not all(_IDENTIFIER.fullmatch(column) for column in columns):
        return None
    return columns


def _set_columns(statement: str) -> set[str] | None:
    """The columns an ``UPDATE findings`` sets, or ``None`` where unreadable."""
    listed = _set_list(statement)
    if listed is None:
        return None
    columns: set[str] = set()
    for assignment in _top_level(listed):
        target = assignment.split("=", 1)[0].strip()
        names = _top_level(target[1:-1]) if target.startswith("(") else [target]
        read = _identifiers(names)
        if read is None:
            return None
        columns |= read
    return columns


def _inserted_columns(statement: str) -> set[str] | None:
    """The column list of an ``INSERT INTO findings``, ``None`` if it has none."""
    match = _FINDINGS_INSERT.search(statement)
    if match is None:
        return None
    return _identifiers(match.group("columns").split(","))


def _findings_writes(source: str) -> list[tuple[int, str, str | None]]:
    """
    Every write of ``findings`` in ``source`` (``_table_writes``, which also
    reports a write whose table it cannot read), each with the whole statement
    that makes it where the scan can read one: the longest string on the
    write's line that is an insert into, or an update of, the table.
    """
    texts: dict[int, list[str]] = {}
    for line, text in _strings(source):
        texts.setdefault(line, []).append(text)
    pattern = {"insert into": _FINDINGS_INSERT, "update": _FINDINGS_UPDATE}
    found: list[tuple[int, str, str | None]] = []
    for write in _table_writes(source, "findings"):
        statements = [
            text
            for text in texts.get(write.line, [])
            if write.verb in pattern and pattern[write.verb].search(text)
        ]
        found.append(
            (write.line, write.verb, max(statements, key=len) if statements else None)
        )
    return found


def _findings_offences(source: str) -> list[str]:
    """
    What in ``source`` breaks 0015's rules as code can: a write of
    ``findings`` that is not an insert or an update, or whose statement the
    scan cannot read; an update that sets a column the closure does not own;
    and an insert that does not name its writer.
    """
    offences: list[str] = []
    for line, verb, statement in _findings_writes(source):
        if verb not in ("insert into", "update") or statement is None:
            offences.append(f"line {line}: {verb} findings, which the scan cannot read")
        elif verb == "update":
            columns = _set_columns(statement)
            if columns is None or not columns <= FINDINGS_CLOSURE:
                offences.append(f"line {line}: an update setting {columns}")
        else:
            columns = _inserted_columns(statement)
            if columns is None or "origin" not in columns:
                offences.append(f"line {line}: an insert naming no origin")
    return offences


def _called(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _repo_names(tree: ast.AST) -> set[str]:
    """The names an import in ``tree`` binds to the programme's ``repo``."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "repo" or alias.name.endswith(".repo"):
                    names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "src.programme.repo" and alias.asname:
                    names.add(alias.asname)
    return names


def _raise_finding_calls(source: str) -> list[tuple[int, str | None]]:
    """
    Every call of ``raise_finding`` in ``source``, with the ``origin`` it
    passes when that is a string literal, ``None`` otherwise: a variable, a
    spread ``**kwargs`` or ``*args``, or no origin at all. A reference to the
    function that is not a call is ``None`` too, since stored under another
    name its calls are ones this scan cannot read.

    So is the function taken by its name (D1's review, D1RS-6): the literal
    ``"raise_finding"`` wherever it stands — ``getattr(repo,
    "raise_finding")``, ``attrgetter("raise_finding")`` — and the ``repo``
    module read by a name the scan cannot read or as a namespace
    (``getattr(repo, name)``, ``vars(repo)``, ``repo.__dict__``), as
    ``test_job_ownership._enqueues`` reads ``enqueue``.
    """
    tree = ast.parse(source)
    repos = _repo_names(tree)
    called = {
        id(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _called(node.func) == "raise_finding"
    }
    found: list[tuple[int, str | None]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == "raise_finding":
            found.append((node.lineno, None))
        elif (
            isinstance(node, ast.Attribute)
            and node.attr == "__dict__"
            and isinstance(node.value, ast.Name)
            and node.value.id in repos
        ):
            found.append((node.lineno, None))
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in ("getattr", "vars")
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id in repos
            and (
                node.func.id == "vars"
                or len(node.args) < 2
                or not isinstance(node.args[1], ast.Constant)
            )
        ):
            found.append((node.lineno, None))
        if isinstance(node, ast.Call) and id(node.func) in called:
            spread = any(keyword.arg is None for keyword in node.keywords) or any(
                isinstance(argument, ast.Starred) for argument in node.args
            )
            origin = next(
                (keyword.value for keyword in node.keywords if keyword.arg == "origin"),
                None,
            )
            literal = (
                origin.value
                if isinstance(origin, ast.Constant) and isinstance(origin.value, str)
                else None
            )
            found.append((node.lineno, None if spread else literal))
        elif (
            isinstance(node, ast.Name | ast.Attribute)
            and _called(node) == "raise_finding"
            and id(node) not in called
        ):
            found.append((node.lineno, None))
    return found


def test_every_update_of_findings_sets_closure_columns_only() -> None:
    """
    What was raised stays raised (docs/09, M1): the only update of a finding
    is its closure, which 0015's trigger enforces and an operator alone may
    make. Across ``src/`` and the protected entry points, every update of the
    table sets ``status``, ``closed_at``, ``closed_by`` or ``close_note`` and
    nothing else, and no write of it is anything but an insert or an update
    the scan can read: a delete, a truncate, an upsert that rewrites a row,
    and a write whose table or columns it cannot read are all refused.
    """
    offenders = [
        f"{_label(path)} {offence}"
        for path in _scanned()
        for offence in _findings_offences(path.read_text(encoding="utf-8"))
        if "insert naming no origin" not in offence
    ]
    assert not offenders, "\n".join(offenders)
    updates = [
        _label(path)
        for path in _scanned()
        for _, verb, _ in _findings_writes(path.read_text(encoding="utf-8"))
        if verb == "update"
    ]
    assert updates == ["src/programme/repo.py"], updates


def test_every_insert_into_findings_names_its_origin() -> None:
    """
    Migration 0015 dropped the column's default, so an insert that names no
    writer fails on NOT NULL; this finds it before it runs (docs/09, M11).
    """
    offenders = [
        f"{_label(path)} {offence}"
        for path in _scanned()
        for offence in _findings_offences(path.read_text(encoding="utf-8"))
        if "insert naming no origin" in offence
    ]
    assert not offenders, "\n".join(offenders)
    inserts = [
        _label(path)
        for path in _scanned()
        for _, verb, _ in _findings_writes(path.read_text(encoding="utf-8"))
        if verb == "insert into"
    ]
    assert inserts == ["src/programme/repo.py"], inserts


@pytest.mark.parametrize(
    "source",
    [
        "await conn.execute(\"UPDATE findings SET severity = 'low' WHERE id = $1\")",
        'await conn.execute("UPDATE public.findings SET title = $2 WHERE ref = $1")',
        'q = "UPDATE findings SET status = $2, " + "raised_by = $3 WHERE ref = $1"',
        'q = " ".join(["UPDATE findings", "SET detail_md = $1"])',
        'await conn.execute("UPDATE findings SET (status, severity) = ($1, $2)")',
        'await conn.execute(f"UPDATE findings SET {column} = $1 WHERE ref = $2")',
        'await conn.execute(f"UPDATE {TABLE} SET status = $1")',
        "q = 'INSERT INTO findings (ref, origin) VALUES ($1, $2) "
        "ON CONFLICT (ref) DO UPDATE SET severity = EXCLUDED.severity'",
        'await conn.execute("DELETE FROM findings WHERE ref = $1")',
        'await conn.execute("TRUNCATE findings")',
        'await conn.copy_records_to_table("findings", records=rows)',
        'await conn.execute("INSERT INTO findings (id, ref, title) VALUES ($1,$2,$3)")',
        'await conn.execute("INSERT INTO findings SELECT * FROM old_findings")',
        'q = "INSERT INTO findings " + "(id, ref) VALUES ($1, $2)"',
        # D1's review (D1RS-5): a word that ends a SET list, standing in a
        # subquery or a string literal before a later column, ended the
        # first cut's reading of the list there.
        "q = 'UPDATE findings SET close_note = (SELECT note FROM notes LIMIT 1), "
        "severity = $2 WHERE ref = $1'",
        "q = \"UPDATE findings SET close_note = 'kept where it was', "
        "severity = 'low' WHERE ref = $1\"",
        "q = \"UPDATE findings SET close_note = 'from the panel', "
        "raised_by = 'compliance' WHERE ref = $1\"",
        "q = \"UPDATE findings SET close_note = 'it''s returning', "
        "status = 'open', severity = 'low' WHERE ref = $1\"",
        "q = 'UPDATE findings SET status = $2, close_note = coalesce($3, (SELECT n "
        "FROM notes WHERE id = 1)), title = $4 WHERE ref = $1'",
    ],
)
def test_the_findings_scan_finds_each_offence(source: str) -> None:
    assert _findings_offences(source), source


@pytest.mark.parametrize(
    "source",
    [
        'await conn.execute("UPDATE findings SET status=$2, closed_by=$3, '
        'close_note=$4, closed_at=NOW() WHERE ref=$1")',
        "q = \"UPDATE findings SET close_note = 'from where it stood; returning', "
        "status = $2, closed_at = (SELECT now() FROM clock) WHERE ref = $1\"",
        'q = "INSERT INTO findings (id, ref, origin) VALUES ($1, $2, $3)"',
        "await conn.fetch(\"SELECT * FROM findings WHERE status = 'open'\")",
        '"""Findings are closed by an operator, through the closure alone."""',
        'await conn.execute("UPDATE findings_audit SET severity = $1")',
        'await conn.execute("INSERT INTO findings_audit (ref) VALUES ($1)")',
        'ref = await _next_ref(conn, "findings", "F")',
    ],
)
def test_the_findings_scan_passes_what_keeps_the_rules(source: str) -> None:
    assert _findings_offences(source) == [], source


def test_raise_finding_takes_origin_keyword_only_with_no_default() -> None:
    """
    Every caller names the writer, by keyword (docs/09, M22): a positional
    slot could be filled by accident, and a default would let a new caller
    write ``'model'`` without saying so.
    """
    from src.programme import repo

    parameter = inspect.signature(repo.raise_finding).parameters["origin"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty
    assert repo.FINDING_WRITERS == ("model", "operator")


@pytest.mark.parametrize("origin", ["jev", "unknown", "", "Model", "operator:quentin"])
async def test_raise_finding_refuses_a_writer_it_does_not_know(origin: str) -> None:
    """
    Refused before the connection is touched: no ref taken, no row tried.
    ``'jev'`` is the card check's, which phase D4's writer alone raises, and
    ``'unknown'`` means raised before 0015.
    """
    from src.programme import repo

    class Untouched:
        def __getattr__(self, name: str) -> None:
            raise AssertionError(f"the connection was used: {name}")

    with pytest.raises(ValueError, match="written by one of"):
        await repo.raise_finding(
            Untouched(), None, "independent_risk", "high", "A title", origin=origin
        )


def test_its_callers_pass_literals() -> None:
    """
    The tick passes ``'model'`` — what a role says through its panel seat, the
    programme's model wrote — and the API ``'operator'``, each as a literal,
    so which writer a call names is read in review, not computed. No other
    module in the scanned trees calls it, and none stores it under another
    name.
    """
    calls = {
        (_label(path), origin)
        for path in _scanned()
        for _, origin in _raise_finding_calls(path.read_text(encoding="utf-8"))
    }
    assert calls == FINDING_CALLERS


@pytest.mark.parametrize(
    ("source", "origins"),
    [
        (
            'await repo.raise_finding(conn, None, "r", "high", "t", origin="model")',
            ["model"],
        ),
        ('await raise_finding(conn, origin="operator")', ["operator"]),
        ("await repo.raise_finding(conn, origin=ORIGIN)", [None]),
        ("await repo.raise_finding(conn, **row)", [None]),
        ('await repo.raise_finding(conn, *args, origin="model")', [None]),
        ("await repo.raise_finding(conn, None, 'r', 'high', 't')", [None]),
        ("write = repo.raise_finding", [None]),
        ("WRITERS = {'finding': raise_finding}", [None]),
        ("await repo.raise_card_finding(conn)", []),
        # D1's review (D1RS-6): the writer taken by its name, a literal the
        # first cut never read, or off the module by one it cannot read.
        (
            "await getattr(repo, 'raise_finding')"
            "(conn, None, 'r', 'high', 't', origin='model')",
            [None],
        ),
        ("write = operator.attrgetter('raise_finding')(repo)", [None]),
        ("from src.programme import repo\nwrite = getattr(repo, NAME)", [None]),
        ("from src.programme import repo as r\nnames = vars(r)", [None]),
        ("from src.programme import repo\nnames = repo.__dict__", [None]),
        ("from src.programme import repo\nlimit = getattr(repo, 'LIMIT')", []),
    ],
)
def test_the_caller_scan_reads_each_spelling(
    source: str, origins: list[str | None]
) -> None:
    assert [origin for _, origin in _raise_finding_calls(source)] == origins


# ---------------------------------------------------------------------------
# What Jev's code reaches (phase D1, docs/09 section 9.2)
# ---------------------------------------------------------------------------
#
# Two walks over the import graph with ``test_jev_jobs.py``'s ``_Reach``, which
# follows a reference however it is spelled and reads the code each module it
# enters runs when imported, and one scan of every programme module's source.

#: Every table whose detail the Jev side never reads, with its detail columns:
#: a hypothesis's card and the decision's rationale, a finding's detail, its
#: remediation and its closing note, and an assessment's summary and evidence.
DETAIL_COLUMNS: dict[str, frozenset[str]] = {
    "hypotheses": frozenset({"card", "decision_rationale"}),
    "findings": frozenset({"detail_md", "remediation", "close_note"}),
    "role_assessments": frozenset({"summary", "evidence"}),
}

#: A statement's comments and its string literals, which name no table and no
#: column: ``lane = 'findings'`` compares a value.
_SQL_COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)
_SQL_LITERAL = re.compile(r"'(?:[^']|'')*'")

#: One token of a statement as the detail scan reads it: a parenthesis, a
#: comma, a dot, a star, a number or a parameter, a piece the scan cannot
#: read — an interpolation, marked by a NUL, or a placeholder ``%`` or
#: ``str.format`` fills — a guarded table named where a table may stand,
#: schema-qualified or quoted and never as a column's qualifier, or a word.
_SQL_TOKEN = re.compile(
    r"(?P<open>\()|(?P<close>\))|(?P<comma>,)|(?P<star>\*)"
    r"|(?P<unread>\x00|%(?:\(\w+\))?s|\{\w*\})"
    r"|(?P<value>\$?\d+(?:\.\d+)?)"
    r"|(?P<table>(?<![\w.$\"])(?:\"?(?:\w+|\x00)\"?\.)?\"?"
    r"(?P<guarded>" + "|".join(DETAIL_COLUMNS) + r")\"?(?![\w$\"])(?!\s*\.))"
    r"|(?P<word>\"[^\"]+\"|[A-Za-z_][\w$]*)|(?P<dot>\.)",
    re.IGNORECASE,
)

#: The words a statement begins with, its comments and parentheses read past.
#: The scan judges no other text, so prose that names a table is not a read.
_STATEMENT_WORDS = frozenset(
    {"select", "with", "insert", "update", "delete", "merge", "copy", "table"}
    | {"values", "explain"}
)

#: The words a clause begins with, which say whether a comma at that depth
#: is in a ``FROM`` list, where a table may follow it.
_CLAUSES = frozenset(
    {"select", "from", "where", "join", "using", "on", "group", "order", "set"}
    | {"having", "values", "returning", "into", "limit", "union", "window"}
)

#: Words that end a table's reference rather than name its alias.
_NOT_AN_ALIAS = _CLAUSES | frozenset(
    {"inner", "left", "right", "full", "outer", "cross", "natural", "offset"}
    | {"intersect", "except", "for", "fetch", "lateral", "tablesample", "and"}
    | {"or", "to", "with", "default", "do", "when", "then", "else", "end"}
)

#: The words before a guarded table that make it a table written, defined or
#: locked rather than read: ``INSERT INTO``, ``UPDATE``, ``TRUNCATE``,
#: ``ALTER TABLE`` and their kin.
_TABLE_WRITERS = frozenset(
    {"into", "update", "truncate", "references", "on", "exists", "alter"}
    | {"drop", "lock", "create", "as"}
)

#: asyncpg's bulk reader, which takes a table as an argument and builds the
#: SQL inside the driver, so no string names the read.
_BULK_READERS = frozenset({"copy_from_table"})


def _sql_tokens(statement: str) -> list[tuple[str, str]]:
    """``statement``'s tokens, lower-cased, its comments and literals removed."""
    text = _SQL_LITERAL.sub("''", _SQL_COMMENT.sub(" ", statement))
    tokens: list[tuple[str, str]] = []
    for match in _SQL_TOKEN.finditer(text):
        kind = match.lastgroup or ""
        if kind == "guarded":
            kind, value = "table", match.group("guarded")
        else:
            value = match.group(0)
        tokens.append((kind, value.lower().strip('"')))
    return tokens


def _matching_open(tokens: list[tuple[str, str]], close: int) -> int | None:
    """The index of the parenthesis the one at ``close`` closes."""
    depth = 0
    for index in range(close, -1, -1):
        kind = tokens[index][0]
        depth += {"close": 1, "open": -1}.get(kind, 0)
        if depth == 0:
            return index
    return None


def _select_star(tokens: list[tuple[str, str]], star: int) -> bool:
    """
    Whether the ``*`` at ``star`` stands for columns — ``SELECT *``, ``x.*``,
    ``(x).*``, ``, *``, ``SELECT ALL *``, ``DISTINCT ON (…) *``, ``RETURNING *``
    — rather than multiplying, or counting as ``COUNT(*)`` does.
    """
    if star == 0:
        return True
    kind, value = tokens[star - 1]
    if kind in ("dot", "comma"):
        return True
    if kind == "word":
        return value in ("select", "all", "distinct", "returning")
    if kind == "close":
        opened = _matching_open(tokens, star - 1)
        before = [] if opened is None else tokens[max(0, opened - 2) : opened]
        return [value for _, value in before] == ["distinct", "on"]
    return False


def _star_qualifier(tokens: list[tuple[str, str]], star: int) -> str | None:
    """The name a qualified ``*`` expands — ``f`` of ``f.*`` or ``(f).*`` —
    ``""`` for one the scan cannot name, ``None`` for an unqualified one."""
    if star == 0 or tokens[star - 1][0] != "dot":
        return None
    kind, value = tokens[star - 2] if star > 1 else ("", "")
    if kind in ("word", "table"):
        return value
    if kind == "close":
        opened = _matching_open(tokens, star - 2)
        inside = tokens[opened + 1 : star - 2] if opened is not None else []
        if len(inside) == 1 and inside[0][0] in ("word", "table"):
            return inside[0][1]
    return ""


#: What the scan calls a table it reads and cannot name: ``FROM {table}``.
_UNNAMED = "a table the scan cannot name"


@dataclasses.dataclass
class _Statement:
    """One statement as the detail scan reads it."""

    tokens: list[tuple[str, str]]
    #: Each name a guarded table read goes by — its own, and its alias — and
    #: the table, :data:`_UNNAMED` for a table the scan cannot name; the same
    #: for a guarded table written.
    reads: dict[str, str] = dataclasses.field(default_factory=dict)
    written: dict[str, str] = dataclasses.field(default_factory=dict)
    #: Where a table or an alias is named rather than used.
    declared: set[int] = dataclasses.field(default_factory=set)
    #: The tables read whole: ``TABLE t``, ``COPY t TO``.
    whole: set[str] = dataclasses.field(default_factory=set)
    #: The tables read by a ``SELECT`` whose column list holds a piece the
    #: scan cannot read, and whether a ``RETURNING`` list holds one.
    unread_lists: set[str] = dataclasses.field(default_factory=set)
    unread_returning: bool = False
    #: Where its ``RETURNING`` begins, if it has one.
    returning: int | None = None


def _parsed(statement: str) -> _Statement | None:
    """
    ``statement``'s guarded tables, each read or written, the names each goes
    by, and the column lists it cannot read; ``None`` for a text whose first
    word is no statement's and no piece the scan cannot read, which is prose,
    never a read. A text that opens with such a piece — ``f"{cols} FROM
    hypotheses"`` — opens in a column list, and is judged for the guarded
    tables it names alone, so a message that interpolates a name before the
    word "from" is not taken for a read. See :func:`_detail_read`.
    """
    tokens = _sql_tokens(statement)
    words = [value for kind, value in tokens if kind not in ("open", "close")]
    if not words:
        return None
    opens_a_statement = words[0] in _STATEMENT_WORDS
    if not opens_a_statement and words[0][:1] not in ("\x00", "%", "{"):
        return None
    parsed = _Statement(tokens)
    clause: dict[int, str] = {}
    # The column lists open at each depth, a SELECT's until its FROM and a
    # RETURNING's to the end, and whether each holds a piece the scan cannot
    # read; kept past its FROM, for the tables that FROM reads.
    open_lists: set[int] = set() if opens_a_statement else {0}
    unread_list: dict[int, bool] = {0: False}
    depth = 0
    for index, (kind, value) in enumerate(tokens):
        if kind == "open":
            depth += 1
            continue
        if kind == "close":
            clause.pop(depth, None)
            open_lists.discard(depth)
            unread_list.pop(depth, None)
            depth -= 1
            continue
        if kind == "word" and value in _CLAUSES:
            clause[depth] = value
        if kind == "word" and value in ("select", "returning"):
            open_lists.add(depth)
            unread_list[depth] = False
            if value == "returning" and parsed.returning is None:
                parsed.returning = index
        elif kind == "word" and value in ("from", "union", "intersect", "except"):
            open_lists.discard(depth)
        if kind not in ("table", "unread"):
            continue
        previous = [
            v
            for k, v in tokens[:index]
            if k not in ("open", "close") and v not in ("only", "lateral")
        ]
        last = previous[-1] if previous else None
        earlier = previous[-2] if len(previous) > 1 else None
        rest = tokens[index + 1 :]
        if last == "copy":
            copied = [v for k, v in rest if k == "word"][:1] == ["to"]
            is_read, is_written = copied, not copied
            if copied and rest[:1] != [("open", "(")]:
                parsed.whole.add(value if kind == "table" else _UNNAMED)
        elif (last == "from" and earlier == "delete") or (
            last == "table" and earlier in _TABLE_WRITERS
        ):
            is_read, is_written = False, True
        elif last in ("from", "join", "using", "table"):
            is_read, is_written = True, False
            if last == "table":
                parsed.whole.add(value if kind == "table" else _UNNAMED)
        elif last == "," and clause.get(depth) in ("from", "join", "on", "using"):
            is_read, is_written = True, False
        else:
            is_read, is_written = False, last in _TABLE_WRITERS
        if kind == "unread":
            if not (is_read or is_written):
                for open_depth in open_lists:
                    if open_depth <= depth:
                        unread_list[open_depth] = True
                if parsed.returning is not None:
                    parsed.unread_returning = True
                continue
            if not (is_read and opens_a_statement):
                continue
            value = _UNNAMED
        if not (is_read or is_written):
            continue
        parsed.declared.add(index)
        names = parsed.reads if is_read else parsed.written
        names[value] = value
        if is_read and unread_list.get(depth):
            parsed.unread_lists.add(value)
        offset = 2 if rest[:1] == [("word", "as")] else 1
        alias = rest[offset - 1 : offset]
        if alias and alias[0][0] == "word" and alias[0][1] not in _NOT_AN_ALIAS:
            names[alias[0][1]] = value
            parsed.declared.add(index + offset)
    parsed.whole &= {_UNNAMED, *parsed.reads.values()}
    return parsed


def _tables_read(statement: str) -> set[str]:
    """The guarded tables ``statement`` reads from."""
    parsed = _parsed(statement)
    return set() if parsed is None else set(parsed.reads.values()) - {_UNNAMED}


def _detail_columns(table: str) -> frozenset[str]:
    """A guarded table's detail columns; for one the scan cannot name, all."""
    if table == _UNNAMED:
        return frozenset().union(*DETAIL_COLUMNS.values())
    return DETAIL_COLUMNS[table]


def _detail_read(statement: str) -> str | None:
    """
    What in ``statement`` reads detail from ``hypotheses``, ``findings`` or
    ``role_assessments``, or ``None``.

    A statement reads a guarded table wherever it names it as a table read
    from: after ``FROM``, ``JOIN`` or ``USING``, after a comma in a ``FROM``
    list, as the ``TABLE`` shorthand, or copied out by ``COPY … TO``. Such a
    statement, whatever its first word — an ``INSERT … SELECT``, an
    ``UPDATE … FROM``, a ``COPY (…)`` — reads detail when it holds a ``*``
    that is not another table's, a detail column of a table it reads, or a
    table it reads, by its name or alias, as a whole row: ``to_jsonb(h)``,
    ``SELECT f``, ``(f).*``. So does a ``SELECT`` whose column list holds a
    piece the scan cannot read, interpolated or a placeholder, where its
    ``FROM`` reads a guarded table, since the piece could be any column. A
    table it reads but cannot name (``FROM {table}``) could be any of the
    three: a ``*``, a detail column of any of them, or its whole row, read
    from it, is a read. A table written reads nothing but what its
    ``RETURNING`` names, so an insert that writes ``detail_md`` and an update
    that sets ``close_note`` read no detail. Comments and string literals are
    read past, and a text whose first word is no statement's is prose.

    The first cut judged a statement only when its first word was ``SELECT``
    or ``WITH``, found a table only after ``FROM``, ``JOIN``, ``INTO`` or
    ``UPDATE``, and read neither a whole row nor a column list it could not
    read (D1's review, D1RS-2 and D1RT-3).
    """
    parsed = _parsed(statement)
    if parsed is None:
        return None
    tokens, returning = parsed.tokens, parsed.returning
    returned = parsed.written if returning is not None else {}
    if not parsed.reads and not returned:
        return None
    if parsed.whole:
        return f"reads every column of {sorted(parsed.whole)}"
    if parsed.unread_lists:
        return f"a column list on {sorted(parsed.unread_lists)} the scan cannot read"
    if parsed.unread_returning and returned:
        tables = sorted(set(returned.values()))
        return f"a returning list on {tables} the scan cannot read"
    for index, (kind, value) in enumerate(tokens):
        in_returning = returning is not None and index > returning
        names = {**parsed.reads, **(returned if in_returning else {})}
        if kind == "star" and _select_star(tokens, index):
            qualifier = _star_qualifier(tokens, index)
            if not qualifier and names:
                return f"reads * from {sorted(set(names.values()))}"
            if qualifier and qualifier in names:
                return f"reads * from {names[qualifier]}"
        elif (
            kind in ("word", "table")
            and index not in parsed.declared
            and value in names
            and tokens[index + 1 : index + 2] != [("dot", ".")]
        ):
            return f"reads the whole row of {names[value]}"
        if kind == "word":
            for table in sorted(set(names.values())):
                if value in _detail_columns(table):
                    return f"reads {value} from {table}"
    return None


def _reach_from(graph: Any, roots: list[tuple[str, str]]) -> Any:
    """``_Reach`` started from these definitions rather than whole modules."""
    from tests.unit.test_jev_jobs import _Reach

    reach = _Reach(graph)
    for module, name in roots:
        reach.define(module, name)
    while reach.pending:
        where, node = reach.pending.pop()
        reach.read(where, node)
    return reach


def _spans(nodes: Any) -> list[tuple[int, int]]:
    return [
        (node.lineno, getattr(node, "end_lineno", node.lineno))
        for node in nodes
        if hasattr(node, "lineno")
    ]


def _module_constants(tree: ast.Module) -> dict[str, str]:
    """
    Each name ``tree`` binds once, at its top level, to a string literal, and
    nowhere else rebinds: what an f-string interpolating it reads as its
    text, so a column list held in a constant is read where it is used.
    """
    bound: dict[str, int] = {}

    def bind(name: str) -> None:
        bound[name] = bound.get(name, 0) + 1

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            bind(node.id)
        elif isinstance(node, ast.arg):
            bind(node.arg)
        elif isinstance(node, ast.alias):
            bind(node.asname or node.name.partition(".")[0])
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            bind(node.name)
        elif isinstance(node, ast.Global | ast.Nonlocal):
            for name in node.names:
                bind(name)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bind(node.name)
    constants: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        else:
            continue
        if (
            isinstance(target, ast.Name)
            and bound.get(target.id) == 1
            and isinstance(value, ast.Constant)
            and isinstance(value.value, str)
        ):
            constants[target.id] = value.value
    return constants


def _sql_texts(source: str) -> list[tuple[int, str]]:
    """
    Every text in ``source`` that could be a statement, with its line: each
    string literal; each f-string, a literal or a module's string constant it
    interpolates read as its text and anything else marked by a NUL; and the
    one text each chain of ``+`` or ``str.join`` of a literal sequence
    assembles, its pieces read the same way. A piece of an f-string or a
    chain is read in its whole rather than on its own, and a docstring, which
    no connection runs, is not read at all.
    """
    tree = ast.parse(source)
    constants = _module_constants(tree)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(
            node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
        )
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }

    def inlined(part: ast.FormattedValue) -> ast.expr | None:
        """What a plain interpolation holds, where its text can be read."""
        if part.conversion != -1 or part.format_spec is not None:
            return None
        value = part.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value
        if isinstance(value, ast.Name) and value.id in constants:
            return value
        if isinstance(value, ast.JoinedStr):
            return value
        return None

    def piece(node: ast.AST) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name) and node.id in constants:
            return constants[node.id]
        if isinstance(node, ast.JoinedStr):
            texts = []
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    texts.append(part.value)
                elif isinstance(part, ast.FormattedValue) and (
                    held := inlined(part)
                ):
                    texts.append(piece(held) or "\x00")
                else:
                    texts.append("\x00")
            return "".join(texts)
        return None

    def consumed(node: ast.AST) -> set[int]:
        """The nodes read as part of ``node``'s text, and never on their own."""
        ids: set[int] = set()
        if isinstance(node, ast.JoinedStr):
            for part in node.values:
                ids.add(id(part))
                held = inlined(part) if isinstance(part, ast.FormattedValue) else None
                if held is not None:
                    ids.add(id(held))
                    ids |= consumed(held)
        return ids

    def chain(node: ast.AST) -> tuple[list[ast.expr], set[int]] | None:
        """The pieces of a chain of ``+``, and the inner ``+`` nodes it holds."""
        if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add)):
            return None
        pieces: list[ast.expr] = []
        inner: set[int] = set()
        for side in (node.left, node.right):
            nested = chain(side)
            if nested is None:
                pieces.append(side)
            else:
                pieces.extend(nested[0])
                inner |= nested[1] | {id(side)}
        return pieces, inner

    skipped: set[int] = set()
    texts: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if id(node) in skipped or id(node) in docstrings:
            continue
        pieces: list[ast.expr] | None = None
        separator = ""
        if (found := chain(node)) is not None:
            pieces = found[0]
            skipped |= found[1]
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "join"
            and isinstance(node.func.value, ast.Constant)
            and isinstance(node.func.value.value, str)
            and len(node.args) == 1
            and isinstance(node.args[0], ast.List | ast.Tuple | ast.Set)
        ):
            pieces, separator = list(node.args[0].elts), node.func.value.value
        if pieces is not None:
            read = [piece(p) for p in pieces]
            if any(text is not None for text in read):
                skipped |= {id(p) for p in pieces if piece(p) is not None}
                skipped |= {i for p in pieces for i in consumed(p)}
                assembled = separator.join("\x00" if t is None else t for t in read)
                texts.append((node.lineno, assembled))
            continue
        if isinstance(node, ast.JoinedStr):
            skipped |= consumed(node)
            texts.append((node.lineno, piece(node) or ""))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            texts.append((node.lineno, node.value))
    return texts


def _bulk_reads(source: str) -> list[tuple[int, str]]:
    """
    Every call of asyncpg's bulk reader in ``source`` that copies detail out,
    with its line: a guarded table copied whole, or with a column list that is
    not a literal free of its detail columns; and a table the scan cannot
    read, which could be one.
    """
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute | ast.Name)
            and _called(node.func) in _BULK_READERS
        ):
            continue
        target = node.args[0] if node.args else None
        columns = None
        for keyword in node.keywords:
            if keyword.arg == "table_name":
                target = keyword.value
            elif keyword.arg == "columns":
                columns = keyword.value
        if not (isinstance(target, ast.Constant) and isinstance(target.value, str)):
            found.append((node.lineno, "copies a table the scan cannot read"))
            continue
        table = target.value.rpartition(".")[2].strip('"').lower()
        if table not in DETAIL_COLUMNS:
            continue
        listed = (
            [e.value for e in columns.elts if isinstance(e, ast.Constant)]
            if isinstance(columns, ast.List | ast.Tuple)
            else None
        )
        if (
            listed is None
            or len(listed) != len(columns.elts)  # type: ignore[union-attr]
            or {str(c).lower() for c in listed} & DETAIL_COLUMNS[table]
        ):
            found.append((node.lineno, f"copies the detail of {table}"))
    return found


def _detail_reads(graph: Any, roots: list[tuple[str, str]]) -> list[str]:
    """
    Every reached definition holding a statement that reads detail
    (``_detail_read``), or a bulk copy that does (``_bulk_reads``).
    """
    reach = _reach_from(graph, roots)
    found: dict[str, None] = {}
    judged: dict[str, list[tuple[int, str]]] = {}
    for (module, name), nodes in sorted(reach.reached.items(), key=lambda i: i[0]):
        if module not in judged:
            source = graph.sources[module]
            judged[module] = [
                (line, read)
                for line, text in _sql_texts(source)
                if (read := _detail_read(text))
            ] + _bulk_reads(source)
        for first, last in _spans(nodes):
            for line, read in judged[module]:
                if first <= line <= last:
                    found[f"{module}.{name} (line {line}): {read}"] = None
    unread = (f"a load the scan cannot read: {load}" for load in reach.unreadable)
    found.update(dict.fromkeys(unread))
    return list(found)


def _jev_roots() -> list[tuple[str, str]]:
    """
    Every root on the Jev side that acts: each ``JEV_HANDLERS`` handler, each
    ``ASKABLE`` set's ``load``, ``admit``, ``build`` and ``follow_up``, and the
    planner. Read from the objects themselves, so a handler or a set added
    later is a root without anyone remembering to add it.
    """
    from src.programme import jev_jobs, jev_plan, main

    roots = {
        (handler.__module__, handler.__name__)
        for handler in main.JEV_HANDLERS.values()
    }
    for askable in jev_jobs.ASKABLE.values():
        for part in (askable.load, askable.admit, askable.build, askable.follow_up):
            if part is not None:
                roots.add((part.__module__, part.__name__))
    roots.add((jev_plan.__name__, jev_plan.plan.__name__))
    return sorted(roots)


#: The harness's commands, every one reached through ``execute``, which
#: ``main`` and every caller reach.
HARNESS_ROOTS = [
    ("src.programme.jev_eval", "execute"),
    ("src.programme.jev_eval", "main"),
]


def test_the_roots_are_every_handler_every_askable_part_and_the_planner() -> None:
    """Guards the guard: the walks below start where the Jev side acts."""
    roots = set(_jev_roots())
    assert {
        ("src.programme.jev_jobs", "run_ask"),
        ("src.programme.jev_jobs", "run_reask"),
        ("src.programme.jev_forward", "collect"),
        ("src.programme.jev_jobs", "_load_hypothesis"),
        ("src.programme.jev_jobs", "_screen_follow_up"),
        ("src.programme.jev_plan", "plan"),
    } <= roots
    assert {module for module, _ in roots} <= {
        "src.programme.main",
        "src.programme.jev_jobs",
        "src.programme.jev_forward",
        "src.programme.jev_plan",
    }


def test_the_jev_side_never_reads_detail() -> None:
    """
    docs/09, D-SAFE-2 and D-HMB-16: from every handler, every askable set's
    load, admission, state and follow-up, the planner and every harness
    command, no reachable function reads ``*`` from ``hypotheses``,
    ``findings`` or ``role_assessments``, or names a detail column of them in
    a SELECT or a RETURNING. At ``23dee2b`` every title ask read the card
    through ``repo.get_hypothesis``; the title sets now read by column list
    (``jev_repo.get_hypothesis_title``).
    """
    from tests.unit.test_import_boundaries import _real_graph

    offences = _detail_reads(_real_graph(), [*_jev_roots(), *HARNESS_ROOTS])
    assert not offences, "the Jev side reads detail:\n" + "\n".join(offences)


def test_the_detail_walk_reaches_the_reads_it_judges() -> None:
    """
    Guards the guard: the walk reaches the Jev side's reads of hypotheses —
    the title sets' and the planner's — and judges statements on the tables it
    guards, so a walk that reached nothing could not pass for one that found
    nothing.
    """
    from tests.unit.test_import_boundaries import _real_graph

    graph = _real_graph()
    reach = _reach_from(graph, [*_jev_roots(), *HARNESS_ROOTS])
    assert {
        ("src.programme.jev_repo", "get_hypothesis_title"),
        ("src.programme.jev_repo", "hypotheses_to_ask"),
        ("src.programme.jev_eval", "evaluate"),
    } <= set(reach.reached)
    judged = {
        text
        for _, text in _sql_texts(graph.sources["src.programme.jev_repo"])
        if "hypotheses" in _tables_read(text)
    }
    assert any("FROM hypotheses" in text for text in judged), judged
    # The title reads interpolate a module constant, which is read as its
    # text, so the scan judges their column lists rather than skipping them.
    assert any("encode(sha256(convert_to(h.title" in text for text in judged)


#: A synthetic ``repo``: the two ``SELECT *`` readers the walk must refuse, a
#: title read by column list, and writers of detail, which read none.
_DETAIL_REPO = '''
async def get_hypothesis(conn, ref):
    return await conn.fetchrow("SELECT * FROM hypotheses WHERE ref = $1", ref)

async def list_findings(conn, where=""):
    return await conn.fetch(f"SELECT * FROM findings {where} ORDER BY opened_at")

async def get_hypothesis_title(conn, ref):
    return await conn.fetchrow(
        "SELECT ref, title, origin, created_at FROM hypotheses WHERE ref = $1", ref
    )

async def raise_finding(conn, detail):
    await conn.execute(
        "INSERT INTO findings (title, detail_md, remediation) VALUES ($1, $2, $3)",
        "t", detail, "r",
    )

async def close_finding(conn, ref, note):
    await conn.execute("UPDATE findings SET close_note = $2 WHERE ref = $1", ref, note)

async def count_findings(conn):
    return await conn.fetchval("SELECT COUNT(*) FROM findings")
'''


def _detail_tree(handler: str) -> dict[str, str]:
    return {
        "src/__init__.py": "",
        "src/programme/__init__.py": "",
        "src/programme/repo.py": _DETAIL_REPO,
        "src/programme/jev_jobs.py": handler,
    }


_HANDLER_ROOT = [("src.programme.jev_jobs", "handle")]


@pytest.mark.parametrize(
    "handler",
    [
        pytest.param(
            "from src.programme import repo\n"
            "async def handle(conn):\n"
            "    return await repo.get_hypothesis(conn, 'H-1')\n",
            id="repo.get_hypothesis",
        ),
        pytest.param(
            "from src.programme import repo\n"
            "async def handle(conn):\n"
            "    return await repo.list_findings(conn)\n",
            id="repo.list_findings",
        ),
        pytest.param(
            "from src.programme.repo import get_hypothesis as load\n"
            "LOADERS = {'title': load}\n"
            "async def handle(conn):\n"
            "    return await LOADERS['title'](conn, 'H-1')\n",
            id="stored-under-another-name",
        ),
        pytest.param(
            "async def handle(conn):\n"
            "    return await conn.fetchrow('SELECT card FROM hypotheses')\n",
            id="a-detail-column-of-its-own",
        ),
        pytest.param(
            "async def handle(conn):\n"
            "    return await conn.fetch(\n"
            "        'SELECT f.title, f.remediation FROM findings f '\n"
            "        'JOIN candidates c ON c.id = f.candidate_id'\n"
            "    )\n",
            id="a-detail-column-through-a-join",
        ),
        pytest.param(
            "async def handle(conn):\n"
            "    return await conn.fetch('SELECT a.* FROM role_assessments a')\n",
            id="an-alias-star",
        ),
        pytest.param(
            "async def handle(conn):\n"
            "    return await conn.fetch('SELECT summary FROM role_assessments')\n",
            id="an-assessments-summary",
        ),
        pytest.param(
            "async def handle(conn):\n"
            "    return await conn.fetchrow(\n"
            "        'UPDATE findings SET status = $1 RETURNING *', 'remediated'\n"
            "    )\n",
            id="returning-star",
        ),
        pytest.param(
            "async def handle(conn):\n"
            "    q = 'SELECT ref, ' + 'decision_rationale FROM hypotheses'\n"
            "    return await conn.fetch(q)\n",
            id="assembled-by-plus",
        ),
        # D1's review (D1RS-2, D1RT-3): what the first cut read only when a
        # statement's first word was SELECT or WITH, its tables named after
        # FROM, JOIN, INTO or UPDATE, and ``*`` or a column by its name.
        *(
            pytest.param(
                f"async def handle(conn, cols='card', table='t'):\n    {call}\n",
                id=name,
            )
            for name, call in (
                (
                    "an-insert-that-selects-the-card",
                    "await conn.execute(\"INSERT INTO jev_requests (state) SELECT "
                    "jsonb_build_object('card', card) FROM hypotheses\")",
                ),
                (
                    "a-comma-join-naming-the-card",
                    "return await conn.fetch('SELECT h.card FROM candidates c, "
                    "hypotheses h WHERE h.id = c.hypothesis_id')",
                ),
                (
                    "a-comma-join-star",
                    "return await conn.fetch('SELECT f.* FROM jobs j, findings f')",
                ),
                (
                    "to_jsonb-of-the-row",
                    "return await conn.fetch('SELECT to_jsonb(h) FROM hypotheses h')",
                ),
                (
                    "the-row-as-a-value",
                    "return await conn.fetch('SELECT f FROM findings f')",
                ),
                (
                    "row_to_json-of-the-row",
                    "return await conn.fetch("
                    "'SELECT row_to_json(a) FROM role_assessments a')",
                ),
                (
                    "json_agg-of-the-row",
                    "return await conn.fetch('SELECT json_agg(f) FROM findings f')",
                ),
                (
                    "the-row-expanded",
                    "return await conn.fetch('SELECT (f).* FROM findings f')",
                ),
                (
                    "the-table-as-its-row",
                    "return await conn.fetch('SELECT hypotheses FROM hypotheses')",
                ),
                ("the-table-shorthand", "return await conn.fetch('TABLE hypotheses')"),
                (
                    "a-leading-line-comment",
                    "return await conn.fetch('-- titles\\nSELECT * FROM hypotheses')",
                ),
                (
                    "a-leading-block-comment",
                    "return await conn.fetch('/* t */ SELECT card FROM hypotheses')",
                ),
                (
                    "a-leading-parenthesis",
                    "return await conn.fetch('(SELECT * FROM findings) UNION ALL "
                    "(SELECT * FROM findings)')",
                ),
                (
                    "a-copy-of-a-query",
                    "await conn.execute("
                    "'COPY (SELECT card FROM hypotheses) TO STDOUT')",
                ),
                (
                    "a-copy-of-the-table",
                    "await conn.execute('COPY findings TO STDOUT')",
                ),
                (
                    "a-computed-column-list",
                    "return await conn.fetch(f'SELECT {cols} FROM hypotheses')",
                ),
                (
                    "a-percent-placeholder",
                    "return await conn.fetch('SELECT %s FROM hypotheses' % '*')",
                ),
                (
                    "a-format-placeholder",
                    "return await conn.fetch("
                    "'SELECT {} FROM hypotheses'.format(cols))",
                ),
                (
                    "an-update-from-the-card",
                    "await conn.execute('UPDATE jobs SET result = to_jsonb(h.card) "
                    "FROM hypotheses h WHERE h.ref = $1', 'H-1')",
                ),
                (
                    "select-all-star",
                    "return await conn.fetch('SELECT ALL * FROM findings')",
                ),
                (
                    "a-delete-using-the-card",
                    "await conn.execute('DELETE FROM jobs USING hypotheses h "
                    "WHERE h.card IS NULL')",
                ),
                (
                    "returning-the-whole-row",
                    "return await conn.fetchrow('UPDATE findings SET status = $1 "
                    "RETURNING to_jsonb(findings)', 'x')",
                ),
                (
                    "a-star-from-a-table-it-cannot-read",
                    "return await conn.fetch(f'SELECT * FROM {table}')",
                ),
                (
                    "a-copy-of-the-table-by-asyncpg",
                    "await conn.copy_from_table('hypotheses', output='h.csv')",
                ),
                (
                    "a-copy-by-asyncpg-of-a-table-it-cannot-read",
                    "await conn.copy_from_table(table, output='t.csv')",
                ),
                (
                    "a-detail-column-of-a-table-it-cannot-name",
                    "return await conn.fetch(f'SELECT summary FROM {table}')",
                ),
                (
                    "a-computed-list-from-a-table-it-cannot-name",
                    "return await conn.fetch(f'SELECT {cols} FROM {table} t')",
                ),
                (
                    "the-whole-row-of-a-table-it-cannot-name",
                    "return await conn.fetch(f'SELECT to_jsonb(t) FROM {table} t')",
                ),
                (
                    "a-star-in-a-common-table-expression",
                    "return await conn.fetch('WITH x AS (SELECT * FROM findings) "
                    "SELECT x.title FROM x')",
                ),
                (
                    "a-returning-list-it-cannot-read",
                    "return await conn.fetchrow(f'UPDATE findings SET status = $1 "
                    "RETURNING {cols}', 'x')",
                ),
            )
        ),
        pytest.param(
            "COLUMNS = 'ref, card'\n"
            "async def handle(conn):\n"
            "    return await conn.fetch(f'SELECT {COLUMNS} FROM hypotheses')\n",
            id="a-module-constant-naming-the-card",
        ),
    ],
)
def test_the_detail_walk_finds_each_read(handler: str) -> None:
    graph = _synthetic(_detail_tree(handler))
    assert _detail_reads(graph, _HANDLER_ROOT), "the walk missed a read of detail"


@pytest.mark.parametrize(
    "handler",
    [
        pytest.param(
            "from src.programme import repo\n"
            "async def handle(conn):\n"
            "    return await repo.get_hypothesis_title(conn, 'H-1')\n",
            id="the-title-by-column-list",
        ),
        pytest.param(
            "from src.programme import repo\n"
            "async def handle(conn):\n"
            "    await repo.raise_finding(conn, 'code-built words')\n"
            "    await repo.close_finding(conn, 'F-1', 'a note')\n"
            "    return await repo.count_findings(conn)\n",
            id="writes-and-a-count",
        ),
        pytest.param(
            "from src.programme import repo\n"
            "async def handle(conn):\n"
            "    return None\n"
            "async def elsewhere(conn):\n"
            "    return await repo.get_hypothesis(conn, 'H-1')\n",
            id="a-reader-nothing-reached-calls",
        ),
        *(
            pytest.param(
                f"async def handle(conn, where='TRUE'):\n    {call}\n", id=name
            )
            for name, call in (
                (
                    "a-count",
                    "return await conn.fetchval("
                    "'SELECT 2 * COUNT(*) FROM findings WHERE origin = $1', 'm')",
                ),
                (
                    "columns-qualified-by-an-alias",
                    "return await conn.fetch('SELECT h.ref, h.title FROM hypotheses h "
                    "WHERE h.origin = $1', 'model')",
                ),
                (
                    "a-lane-named-like-a-table",
                    "return await conn.fetch(\"SELECT id FROM jev_requests WHERE "
                    "lane = 'findings'\")",
                ),
                (
                    "another-tables-star-beside-a-title",
                    "return await conn.fetch('SELECT c.*, h.ref, h.title FROM "
                    "candidates c JOIN hypotheses h ON h.id = c.hypothesis_id')",
                ),
                (
                    "an-interpolated-filter",
                    "return await conn.fetch(f'SELECT h.ref FROM hypotheses h "
                    "WHERE {where} ORDER BY h.ref')",
                ),
                (
                    "a-write-of-detail-with-a-subquery-for-its-candidate",
                    "await conn.execute('INSERT INTO findings (title, detail_md, "
                    "origin, candidate_id) SELECT $1, $2, $3, c.id FROM "
                    "candidates c WHERE c.ref = $4', 't', 'd', 'jev', 'C-1')",
                ),
                (
                    "a-closure-of-a-finding",
                    "await conn.execute('UPDATE findings SET close_note = $2 "
                    "WHERE ref = $1 RETURNING ref', 'F-1', 'n')",
                ),
                (
                    "columns-from-a-table-it-cannot-name",
                    "return await conn.fetch(f'SELECT f.id, fa.noul FROM {where} "
                    "ORDER BY f.id')",
                ),
                (
                    "an-interpolated-flag-beside-a-subquery-it-cannot-name",
                    "return await conn.fetch(f'SELECT c.id, {where} AS blocked, "
                    "EXISTS (SELECT 1 FROM {where}) AS flagged FROM content c')",
                ),
                (
                    "a-message-that-interpolates-before-from",
                    "raise ValueError(f'{where!r} is refused; pin one from {where}')",
                ),
            )
        ),
        pytest.param(
            "ADDRESS = \"encode(sha256(convert_to(h.title, 'UTF8')), 'hex')\"\n"
            "async def handle(conn):\n"
            "    return await conn.fetch(\n"
            "        f'SELECT {ADDRESS} AS subject_id FROM hypotheses h'\n"
            "    )\n",
            id="a-module-constant-read-as-its-text",
        ),
        pytest.param(
            "async def handle(conn):\n"
            '    """Reads nothing from findings, not * nor detail_md."""\n'
            "    return None\n",
            id="a-docstring",
        ),
    ],
)
def test_the_detail_walk_passes_what_reads_no_detail(handler: str) -> None:
    graph = _synthetic(_detail_tree(handler))
    assert _detail_reads(graph, _HANDLER_ROOT) == []


# ---------------------------------------------------------------------------
# What Jev's code can write
# ---------------------------------------------------------------------------

MIGRATIONS = ROOT / "migrations"

#: Every ``(table, writer)`` pair reachable from the Jev side that acts, and
#: no other (docs/09, section 7): the ledger's writers, the web ingest's, the
#: one label writer the ingest reaches, and the queue's ``enqueue``. Phase D4
#: adds one, ``findings`` from ``repo.raise_card_finding``. The writer is the
#: definition the SQL is in: the ledger's request and answers are written by
#: ``record_request`` and ``record_answers``, which ``record_exchange`` alone
#: calls, as one write (the design names ``record_exchange``).
ALLOWED_WRITES = frozenset(
    {
        ("jev_requests", "src.programme.jev_repo.record_request"),
        ("jev_answers", "src.programme.jev_repo.record_answers"),
        ("jev_signals", "src.programme.jev_lane.record_signal"),
        ("web_documents", "src.programme.jev_repo.insert_documents"),
        ("web_documents", "src.programme.jev_repo.quarantine_content"),
        ("jev_labels", "src.programme.jev_repo.record_label_once"),
        ("jobs", "src.db.repos.jobs.enqueue"),
    }
)

#: Tables the Jev side never writes, named in the failure so that a reader
#: sees at once what a new pair would mean.
NEVER_WRITTEN = (
    "findings",
    "hypotheses",
    "candidates",
    "programme_decisions",
    "system_flags",
)


def _schema_tables() -> list[str]:
    """Every table the migrations create."""
    names: set[str] = set()
    for path in sorted(MIGRATIONS.glob("*.sql")):
        names.update(
            re.findall(
                r"\bcreate\s+table\s+(?:if\s+not\s+exists\s+)?\"?(\w+)\"?",
                path.read_text(encoding="utf-8"),
                re.IGNORECASE,
            )
        )
    return sorted(names)


#: A table no module names: the scanner run for it finds only the writes whose
#: table it cannot read, which do not depend on the table asked about.
_NO_TABLE = "a_table_no_module_names"


def _texts_the_scanner_reads(source: str) -> str:
    """
    Every text ``_table_writes`` can read in ``source``, joined by NULs: each
    string literal, each f-string with its literal interpolations read as
    their text, and each text a chain of ``+`` or a ``str.join`` of a literal
    sequence assembles, its separator included — read by the scanner's own
    helpers, inner chains too, so the texts the scanner reads are among them.
    A table named in none of them, case aside, as the scanner's patterns
    ignore case, is a table it cannot find written here; and since no table's
    name holds a NUL, no name is found across two texts.
    """
    from tests.unit.test_import_boundaries import _assembled, _literal_text

    texts: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant | ast.JoinedStr):
            text = _literal_text(node)
        else:
            text = _assembled(node)
        if text is not None:
            texts.append(text)
    return "\x00".join(texts)


def _writes_reached(
    graph: Any, roots: list[tuple[str, str]], tables: list[str]
) -> set[tuple[str, str]]:
    """
    Every ``(table, writer)`` pair a reached definition holds, the writer the
    reached definition: each write of a table the migrations create, and each
    write whose table the scan cannot read, as ``("unread", writer)``. A load
    the scan cannot read is a pair of its own.

    The scanner is run for a table only where the texts it reads name it,
    case aside (``_texts_the_scanner_reads``), which saves running it for
    every table on every module and skips nothing it would find. The first
    cut looked for the table's lower-case name in the module's raw text, so a
    write the scanner reads — the name in capitals, or split across ``+`` or
    ``str.join`` — was never looked for (D1's review, D1RS-1).
    """
    from tests.unit.test_import_boundaries import UNREAD

    reach = _reach_from(graph, roots)
    by_module: dict[str, list[tuple[int, str]]] = {}
    for module, _ in reach.reached:
        if module in by_module:
            continue
        source = graph.sources[module]
        texts = _texts_the_scanner_reads(source)
        writes: set[tuple[int, str]] = set()
        for table in [*tables, _NO_TABLE]:
            named = re.search(re.escape(table), texts, re.IGNORECASE)
            if table != _NO_TABLE and named is None:
                continue
            for write in _table_writes(source, table):
                writes.add((write.line, UNREAD if write.verb == UNREAD else table))
        by_module[module] = sorted(writes)
    pairs: set[tuple[str, str]] = set()
    for (module, name), nodes in reach.reached.items():
        for first, last in _spans(nodes):
            for line, table in by_module[module]:
                if first <= line <= last:
                    pairs.add((table, f"{module}.{name}"))
    pairs |= {("a load the scan cannot read", load) for load in reach.unreadable}
    return pairs


class TestWhatJevCodeCanWrite:
    """
    docs/09 section 7 and M6/M7: from every ``JEV_HANDLERS`` handler, every
    ``ASKABLE`` follow-up and the planner, the reachable ``(table, writer)``
    pairs are exactly the allow-list. Nothing reachable writes ``findings``,
    ``hypotheses``, ``candidates``, ``programme_decisions`` or
    ``system_flags``, and no write of the queue but ``enqueue``.
    """

    def test_exactly_these_writers(self) -> None:
        from tests.unit.test_import_boundaries import _real_graph

        pairs = _writes_reached(_real_graph(), _jev_roots(), _schema_tables())
        beyond = sorted(pairs - ALLOWED_WRITES)
        missing = sorted(ALLOWED_WRITES - pairs)
        assert pairs == ALLOWED_WRITES, (
            f"the Jev side writes beyond its allow-list; never {NEVER_WRITTEN}:\n"
            + "\n".join(f"{table} <- {writer}" for table, writer in beyond)
            + "\nexpected but not reached:\n"
            + "\n".join(f"{table} <- {writer}" for table, writer in missing)
        )

    def test_the_schema_is_read(self) -> None:
        """Guards the guard: a walk over no tables would find no writes."""
        tables = _schema_tables()
        assert {"findings", "jobs", "jev_requests", "system_flags"} <= set(tables)

    @pytest.mark.parametrize(
        ("handler", "pair"),
        [
            pytest.param(
                "from src.programme import repo\n"
                "async def handle(conn):\n"
                "    await repo.raise_finding(conn, 'x')\n",
                ("findings", "src.programme.repo.raise_finding"),
                id="a-finding",
            ),
            pytest.param(
                "async def handle(conn):\n"
                "    await conn.execute(\"UPDATE system_flags SET value = 'true'\")\n",
                ("system_flags", "src.programme.jev_jobs.handle"),
                id="a-switch",
            ),
            pytest.param(
                "async def handle(conn):\n"
                "    await conn.execute('UPDATE jobs SET status = $1', 'queued')\n",
                ("jobs", "src.programme.jev_jobs.handle"),
                id="a-job",
            ),
            pytest.param(
                "async def handle(conn, table):\n"
                "    await conn.execute(f'DELETE FROM {table}')\n",
                ("unread", "src.programme.jev_jobs.handle"),
                id="a-table-it-cannot-read",
            ),
            pytest.param(
                "from src.programme import repo\n"
                "WRITE = {'close': repo.close_finding}\n"
                "async def handle(conn):\n"
                "    await WRITE['close'](conn, 'F-1', 'n')\n",
                ("findings", "src.programme.repo.close_finding"),
                id="stored-under-another-name",
            ),
            # Every spelling the shared scanner reads is looked for (D1's
            # review, D1RS-1): the first cut looked for a table only where its
            # lower-case name stood in the module's raw text, so a name in
            # capitals, or split across ``+`` or ``str.join``, went unread.
            pytest.param(
                "async def handle(conn):\n"
                "    await conn.execute(\"UPDATE PROGRAMME_DECISIONS SET r = 'x'\")\n",
                ("programme_decisions", "src.programme.jev_jobs.handle"),
                id="a-table-in-capitals",
            ),
            pytest.param(
                "async def handle(conn):\n"
                "    await conn.execute(\"UPDATE SYSTEM_FLAGS SET value = 'true'\")\n",
                ("system_flags", "src.programme.jev_jobs.handle"),
                id="a-switch-in-capitals",
            ),
            pytest.param(
                "async def handle(conn):\n"
                "    await conn.execute(\"UPDATE Candidates SET status = 'x'\")\n",
                ("candidates", "src.programme.jev_jobs.handle"),
                id="a-table-mixed-case",
            ),
            pytest.param(
                "async def handle(conn):\n"
                "    await conn.execute('INSERT INTO Deployments (id) VALUES (1)')\n",
                ("deployments", "src.programme.jev_jobs.handle"),
                id="an-insert-mixed-case",
            ),
            pytest.param(
                "async def handle(conn):\n"
                "    await conn.execute(\n"
                '        "UPDATE programme_" + "decisions SET rationale = \'x\'"\n'
                "    )\n",
                ("programme_decisions", "src.programme.jev_jobs.handle"),
                id="a-name-split-by-plus",
            ),
            pytest.param(
                "async def handle(conn):\n"
                "    await conn.execute(''.join(['DELETE FROM system_', 'flags']))\n",
                ("system_flags", "src.programme.jev_jobs.handle"),
                id="a-name-split-by-join",
            ),
            pytest.param(
                "async def handle(conn):\n"
                "    await conn.execute('s'.join(['UPDATE sy', 'tem_flags SET x']))\n",
                ("system_flags", "src.programme.jev_jobs.handle"),
                id="a-name-the-separator-completes",
            ),
            pytest.param(
                "async def handle(conn):\n"
                "    await conn.execute(f\"DELETE FROM system_{'flags'}\")\n",
                ("system_flags", "src.programme.jev_jobs.handle"),
                id="a-name-completed-by-a-literal-interpolated",
            ),
        ],
    )
    def test_the_walk_finds_each_writer(
        self, handler: str, pair: tuple[str, str]
    ) -> None:
        graph = _synthetic(_detail_tree(handler))
        assert pair in _writes_reached(graph, _HANDLER_ROOT, _schema_tables())

    def test_the_walk_passes_a_reader(self) -> None:
        handler = (
            "from src.programme import repo\n"
            "async def handle(conn):\n"
            "    return await repo.get_hypothesis_title(conn, 'H-1')\n"
        )
        graph = _synthetic(_detail_tree(handler))
        tables = ["findings", "hypotheses", "jobs", "system_flags"]
        assert _writes_reached(graph, _HANDLER_ROOT, tables) == set()

    @pytest.mark.parametrize(
        ("source", "table"),
        [
            ('await c.execute("INSERT INTO jev_signals VALUES ($1)")', "jev_signals"),
            ('q = "".join(("UPDATE ", "jev_", "signals SET v = 1"))', "jev_signals"),
            ('q = "DELETE FROM jev_" + "signals"', "jev_signals"),
            ("q = f\"UPDATE {'web_documents'} SET x = TRUE\"", "web_documents"),
            ('q = "".join(("UPDATE ", "web", "_documents SET x"))', "web_documents"),
            ('q = "MERGE INTO web_documents d USING x ON true"', "web_documents"),
            ('q = "UPDATE PROGRAMME_DECISIONS SET r = 1"', "programme_decisions"),
            ('q = "UPDATE programme_" + "decisions SET r = 1"', "programme_decisions"),
            ("q = ''.join(['DELETE FROM system_', 'flags'])", "system_flags"),
            ("q = 's'.join(['UPDATE sy', 'tem_flags SET x = 1'])", "system_flags"),
            ("q = f\"DELETE FROM system_{'flags'}\"", "system_flags"),
            ('q = "UPDATE ONLY public.\\"Candidates\\" SET x = 1"', "candidates"),
            ('await c.copy_records_to_table("Findings", records=r)', "findings"),
        ],
    )
    def test_the_walk_looks_for_every_table_the_scanner_finds(
        self, source: str, table: str
    ) -> None:
        """
        Guards the guard's shortcut: wherever the shared scanner finds a write
        of a table, the texts the walk reads before running it name the table,
        so the shortcut never skips a write it would have found.
        """
        found = [w for w in _table_writes(source, table) if w.verb != "unread"]
        assert found, f"the scanner reads no write of {table} in {source!r}"
        texts = _texts_the_scanner_reads(source)
        assert re.search(re.escape(table), texts, re.IGNORECASE), texts


# ---------------------------------------------------------------------------
# No switch is written from the programme
# ---------------------------------------------------------------------------

#: The functions that write a switch, all in ``src/db/repos/flags.py``.
SWITCH_WRITERS = frozenset({"set_flag", "engage_kill_switch", "release_kill_switch"})


def _switch_writes(source: str) -> list[str]:
    """
    Every write of ``system_flags`` in ``source`` (the shared scanner, a
    string that is the table's name and nothing else included), and every
    reference to a function that writes a switch: by name, by attribute, or
    as a literal handed to ``getattr``.
    """
    found = [
        f"line {write.line}: {write.verb} system_flags"
        for write in _table_writes(source, "system_flags", bare_name=True)
    ]
    for node in ast.walk(ast.parse(source)):
        name = None
        if isinstance(node, ast.Name):
            name = node.id
        elif isinstance(node, ast.Attribute):
            name = node.attr
        elif isinstance(node, ast.alias):
            name = node.name.rsplit(".", 1)[-1]
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            name = node.value
        if name in SWITCH_WRITERS:
            found.append(f"line {getattr(node, 'lineno', '?')}: {name}")
    return found


def _switch_writes_reached(graph: Any, modules: list[str]) -> list[str]:
    """
    Every definition reached from the whole of each of ``modules`` — by
    ``test_jev_jobs.py``'s ``_Reach``, however the reference is spelled, the
    code each module it enters runs when imported included — that holds a
    write of ``system_flags``, or a write whose table the scanner cannot
    read, and every load the walk cannot read. A switch written through a
    wrapper, an API route that calls ``set_flag`` among them, is a write the
    wrapper holds, so the walk finds it where a scan of the programme's own
    text cannot (D1's review, D1RS-4).
    """
    from tests.unit.test_jev_jobs import _Reach

    reach = _Reach(graph)
    for module in modules:
        reach.whole(module)
    while reach.pending:
        where, node = reach.pending.pop()
        reach.read(where, node)
    writes: dict[str, list[Any]] = {}
    found: dict[str, None] = {}
    for (module, name), nodes in sorted(reach.reached.items(), key=lambda i: i[0]):
        if module not in writes:
            writes[module] = _table_writes(
                graph.sources[module], "system_flags", bare_name=True
            )
        for first, last in _spans(nodes):
            for write in writes[module]:
                if first <= write.line <= last:
                    shown = f"{write.verb} system_flags"
                    found[f"{module}.{name} (line {write.line}): {shown}"] = None
    unread = (f"a load the scan cannot read: {load}" for load in reach.unreadable)
    found.update(dict.fromkeys(unread))
    return list(found)


def test_nothing_in_the_programme_writes_a_switch() -> None:
    """
    docs/09, M7: Jev, and the programme around it, never touches a switch —
    the kill switch, the programme's, Jev's own or the arming switch. Every
    switch is an operator's, written through the API, and 0015 seeds the one
    D1 adds. Across every module of ``src/programme``: its own text, and from
    D1's review everything it reaches, so a switch written through a wrapper
    the programme imports — the API's routes wrap ``set_flag``, and nothing
    keeps the programme from importing them — is refused too.
    """
    from tests.unit.test_import_boundaries import _real_graph

    offenders = [
        f"{_label(path)} {offence}"
        for path in _python_files(PROGRAMME)
        for offence in _switch_writes(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, "\n".join(offenders)
    graph = _real_graph()
    programme = sorted(
        module
        for module in graph.sources
        if module == "src.programme" or module.startswith("src.programme.")
    )
    assert "src.programme.flags" in programme and "src.programme.tick" in programme
    reached = _switch_writes_reached(graph, programme)
    assert not reached, "the programme reaches a switch's writer:\n" + "\n".join(
        reached
    )


@pytest.mark.parametrize(
    "source",
    [
        "await conn.execute(\"UPDATE system_flags SET value = 'true' WHERE key = $1\")",
        "await conn.execute('INSERT INTO system_flags (key, value) VALUES ($1, $2)')",
        "q = 'DELETE FROM ' + 'system_flags'",
        "await conn.copy_records_to_table('system_flags', records=rows)",
        "await flag_repo.set_flag(conn, 'jev_enabled', True, 'x')",
        "from src.db.repos.flags import engage_kill_switch",
        "release = flag_repo.release_kill_switch",
        "await getattr(flag_repo, 'set_flag')(conn, 'k', True, 'x')",
    ],
)
def test_the_switch_scan_finds_each_spelling(source: str) -> None:
    assert _switch_writes(source), source


@pytest.mark.parametrize(
    "source",
    [
        "await flags.jev_enabled(conn)",
        "await conn.fetchrow('SELECT value FROM system_flags WHERE key = $1', k)",
        '"""The switches are an operator\'s, read through flags."""',
    ],
)
def test_the_switch_scan_ignores_a_read(source: str) -> None:
    assert _switch_writes(source) == [], source


#: A synthetic tree: the switches' writer and reader, and an API route that
#: wraps the writer, as ``src/api/routers/programme.py``'s ``set_enabled`` and
#: ``set_autonomy`` do.
_SWITCH_TREE = {
    "src/__init__.py": "",
    "src/db/__init__.py": "",
    "src/db/repos/__init__.py": "",
    "src/db/repos/flags.py": (
        "async def set_flag(conn, key, value, actor):\n"
        "    await conn.execute(\n"
        "        'INSERT INTO system_flags (key, value) VALUES ($1, $2) '\n"
        "        'ON CONFLICT (key) DO UPDATE SET value = $2', key, value\n"
        "    )\n"
        "async def get_flag(conn, key):\n"
        "    return await conn.fetchval(\n"
        "        'SELECT value FROM system_flags WHERE key = $1', key\n"
        "    )\n"
    ),
    "src/api/__init__.py": "",
    "src/api/routers/__init__.py": "",
    "src/api/routers/programme.py": (
        "from src.db.repos import flags\n"
        "async def set_enabled(body, session, conn):\n"
        "    await flags.set_flag(conn, 'programme_enabled', body, 'operator')\n"
    ),
    "src/programme/__init__.py": "",
}


@pytest.mark.parametrize(
    "module",
    [
        pytest.param(
            "from src.api.routers.programme import set_enabled\n"
            "async def go(conn):\n"
            "    await set_enabled(True, None, conn)\n",
            id="the-apis-route-imported",
        ),
        pytest.param(
            "from src.api.routers import programme as api\n"
            "async def go(conn):\n"
            "    await api.set_enabled(True, None, conn)\n",
            id="the-apis-route-off-its-module",
        ),
        pytest.param(
            "from src.api.routers import programme as api\n"
            "TURN_ON = [api.set_enabled]\n",
            id="the-apis-route-stored",
        ),
        pytest.param(
            "from src.db.repos import flags\n"
            "WRITE = flags.set_flag\n",
            id="the-writer-stored",
        ),
    ],
)
def test_the_switch_reach_finds_a_wrapped_writer(module: str) -> None:
    """
    D1's review (D1RS-4): the per-file scan reads each module's own text, so
    a switch written through a wrapper the programme can import — the API's
    own routes — passed it. The reach walk follows the reference into the
    wrapper and finds the write there.
    """
    graph = _synthetic({**_SWITCH_TREE, "src/programme/x.py": module})
    assert _switch_writes(module) == [] or "set_flag" in module
    assert _switch_writes_reached(graph, ["src.programme.x"])


def test_the_switch_reach_passes_a_reader() -> None:
    module = (
        "from src.db.repos import flags\n"
        "async def read(conn):\n"
        "    return await flags.get_flag(conn, 'programme_enabled')\n"
    )
    graph = _synthetic({**_SWITCH_TREE, "src/programme/x.py": module})
    assert _switch_writes_reached(graph, ["src.programme.x"]) == []
