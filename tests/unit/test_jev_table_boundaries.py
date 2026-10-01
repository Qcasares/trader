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
import re
from pathlib import Path

import pytest

from tests.unit.test_import_boundaries import _assembled, _table_writes

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
