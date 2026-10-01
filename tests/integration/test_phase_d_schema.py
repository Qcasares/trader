"""
test_phase_d_schema.py
----------------------
Migration 0015, phase D's schema (docs/09-jev-phase-d-design.md, section 7),
against real PostgreSQL.

0015 does five things, and each is a rule the database enforces, so none of it
can be proved without the database:

* ``findings.origin``: who wrote each finding. ``'unknown'`` for the rows
  stored before 0015 and for nothing raised after it; ``'model'``,
  ``'operator'``, or ``'jev'`` — the card check's finding, which phase D4
  raises, held never to block and to rest on a valid ``true`` of a canonical
  ``guardrail.card`` request.
* What was raised stays raised: only the closure's columns change, a closed
  finding is never reopened, and DELETE and TRUNCATE are refused, a
  candidate's cascading delete with them.
* The card check's arming switch, seeded off.
* Provenance ``system`` on ``jev_requests`` alone: ``jev_signals`` still
  refuses it.
* Plan v2's flips: a flip rate counts the set's population (M2), so its pairs
  are no longer bounded by the n scored items, and stay counts.

Each refusal is asserted by attempting the forbidden write and naming the rule
that refuses it, and each case is shown to break its rule alone: with that one
rule dropped, in a transaction rolled back after, the write is admitted.
PostgreSQL checks a row's BEFORE triggers before its CHECKs, and its CHECKs in
the order of their names, so a case that broke two rules could pass while the
rule it is for is gone. ``TestEveryRuleBites::test_every_rule_0015_adds_has_a_case``
reads what 0015 adds from the catalogue, against a database at 0014, so a rule
added without a case fails it.

Rows are written with plain SQL rather than through ``repo``, so what is tested
is the schema, which holds whatever writes to it; ``TestOriginIsKnownFromNowOn``
also drives the shipped ``repo.raise_finding`` and ``repo.close_finding``. Every
title is invented.

Runs on databases of its own, derived from ``TEST_DATABASE_URL`` as
``test_jev_schema.py``'s are: from 0015 no finding can be deleted, and the Jev
ledger never could be, so rows written here could never be cleared from a
shared database. Skipped unless ``TEST_DATABASE_URL`` is set.

    TEST_DATABASE_URL=postgresql://localhost/trader_test \\
        pytest tests/integration/test_phase_d_schema.py
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest

pytest.importorskip("asyncpg")

import asyncpg  # noqa: E402

from src.db import migrate as migrations  # noqa: E402
from src.programme import flags, repo  # noqa: E402
from tests.integration.test_jev_evaluations import (  # noqa: E402
    BROKEN as EVALUATION_CASES,
)
from tests.integration.test_jev_evaluations import (  # noqa: E402
    _insert as _insert_evaluation,
)
from tests.integration.test_jev_evaluations import _measured  # noqa: E402
from tests.integration.test_jev_schema import (  # noqa: E402
    PROVENANCES,
    REQUEST_PROVENANCES,
    VALID_ANSWERS,
    _answer_row,
    _candidate,
    _exchange,
    _fresh_database,
    _insert,
    _migrations_up_to,
    _request_row,
    _signal_for,
    _unique,
    _vocabulary,
)

TEST_DSN = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DSN, reason="TEST_DATABASE_URL not set; skipping phase D schema tests"
)

#: The set a Jev finding rests on, and the question whose ``true`` it needs.
CARD = "guardrail.card"
CLAIM = "performance_claim"

#: The columns a finding's closure writes, and the only ones that may change.
CLOSURE = ("status", "closed_at", "closed_by", "close_note")


# ---------------------------------------------------------------------------
# Databases and rows
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def dsn() -> str:
    async def setup() -> str:
        fresh = await _fresh_database("phase_d_schema")
        await migrations.migrate(fresh)
        return fresh

    return asyncio.run(setup())


@pytest.fixture
async def conn(dsn: str) -> AsyncIterator[asyncpg.Connection]:
    connection = await asyncpg.connect(dsn)
    try:
        yield connection
    finally:
        await connection.close()


@asynccontextmanager
async def _rolled_back(conn: asyncpg.Connection) -> AsyncIterator[None]:
    """A transaction that never commits: whatever happens in it, nothing stays."""
    transaction = conn.transaction()
    await transaction.start()
    try:
        yield
    finally:
        await transaction.rollback()


async def _refused(conn: asyncpg.Connection, write: Awaitable[Any]) -> None:
    """
    Run ``write`` under a savepoint, so its refusal leaves the caller's
    transaction usable and the error can be inspected by ``pytest.raises``.
    """
    async with conn.transaction():
        await write


def _finding_row(**overrides: Any) -> dict[str, Any]:
    """A finding the programme's model raised through a role's panel seat."""
    row: dict[str, Any] = {
        "id": uuid.uuid4(),
        "ref": _unique("F-D1"),
        "candidate_id": None,
        "raised_by": "independent_risk",
        "severity": "high",
        "title": "The drawdown limit was never exercised",
        "detail_md": "Synthetic detail.",
        "remediation": "Synthetic remediation.",
        "origin": "model",
    }
    row.update(overrides)
    return row


#: A valid ``true`` to the card's question, shaped as the validator writes one.
VALID_TRUE: dict[str, Any] = {
    **VALID_ANSWERS["noul"],
    "question_key": CLAIM,
    "noul": 0.91,
    "argmax": "true",
    "margin": 0.82,
}

#: ``_card_request``'s default answer.
_TRUE = object()


async def _card_request(
    conn: asyncpg.Connection,
    *,
    request: dict[str, Any] | None = None,
    answer: Any = _TRUE,
) -> asyncpg.Record:
    """
    A canonical ``guardrail.card`` request answered with a valid ``true``: what
    a Jev finding must rest on. ``request`` overrides the request's row, and
    ``answer`` the answer's (``None`` for no answer at all).
    """
    row = _request_row(
        **{
            "question_set": CARD,
            "lane": "guardrail",
            "provenance": "model",
            "subject_type": "hypothesis_title",
            "subject_id": uuid.uuid4().hex * 2,
            "state": {"title": "A synthetic card title"},
            **(request or {}),
        }
    )
    stored = await _insert(conn, "jev_requests", row)
    if answer is not None:
        fields = VALID_TRUE if answer is _TRUE else {**VALID_TRUE, **answer}
        await _insert(conn, "jev_answers", _answer_row(stored["id"], **fields))
    return stored


async def _jev_finding_row(
    conn: asyncpg.Connection,
    *,
    request: dict[str, Any] | None = None,
    answer: Any = _TRUE,
    **overrides: Any,
) -> dict[str, Any]:
    """A finding Jev's answer raised, lawful in every respect but ``overrides``."""
    stored = await _card_request(conn, request=request, answer=answer)
    row = _finding_row(
        candidate_id=(await _candidate(conn))["id"],
        raised_by=f"jev:{stored['question_set']}",
        severity="medium",
        origin="jev",
        source_request_id=stored["id"],
    )
    row.update(overrides)
    return row


async def _finding(conn: asyncpg.Connection, **overrides: Any) -> asyncpg.Record:
    return await _insert(conn, "findings", _finding_row(**overrides))


async def _read(conn: asyncpg.Connection, finding_id: uuid.UUID) -> asyncpg.Record:
    return await conn.fetchrow("SELECT * FROM findings WHERE id = $1", finding_id)


# ---------------------------------------------------------------------------
# The rules 0015 adds, and a write that breaks each alone
# ---------------------------------------------------------------------------

#: Every rule 0015 adds or rewrites, by its name in the catalogue, with the
#: table it is on.
RULES: dict[str, str] = {
    "findings.origin NOT NULL": "findings",
    "findings_origin_check": "findings",
    "findings_jev_is_raised_by_jev": "findings",
    "findings_jev_names_its_request": "findings",
    "findings_jev_never_blocks": "findings",
    "findings_jev_is_on_a_candidate": "findings",
    "findings_source_request_id_fkey": "findings",
    "findings_one_per_jev_answer": "findings",
    "trg_findings_origin_is_known": "findings",
    "trg_findings_jev_rests_on_its_answer": "findings",
    "trg_findings_keep_what_was_raised": "findings",
    "trg_findings_no_delete": "findings",
    "trg_findings_no_truncate": "findings",
    "jev_requests_provenance_check": "jev_requests",
    "jev_evaluations_counts_within_n": "jev_evaluations",
    "jev_evaluations_flip_counts_are_counts": "jev_evaluations",
}

#: The rules no write can break alone, and why each is still there.
IMPLIED: dict[str, str] = {
    "findings_source_request_id_fkey": (
        "a backstop: a Jev finding's trigger refuses a request it cannot see "
        "before the key is checked, a finding of any other origin names no "
        "request (findings_jev_names_its_request), its request cannot change "
        "(findings_keep_what_was_raised), and jev_requests refuses DELETE. The "
        "missing request's case breaks it with the trigger"
    ),
}


def _drop(rule: str) -> str:
    """The statement that removes ``rule``, for a transaction rolled back after."""
    table = RULES[rule]
    if rule.endswith(" NOT NULL"):
        column = rule.removesuffix(" NOT NULL").split(".", 1)[1]
        return f"ALTER TABLE {table} ALTER COLUMN {column} DROP NOT NULL"
    if rule.startswith("trg_"):
        return f"DROP TRIGGER {rule} ON {table}"
    if rule == "findings_one_per_jev_answer":
        return f"DROP INDEX {rule}"
    return f'ALTER TABLE {table} DROP CONSTRAINT "{rule}"'


@dataclass(frozen=True)
class Case:
    """
    One write that breaks one rule of 0015's.

    ``rules`` is the rule it is for, first, and any it can only break beside
    it (``IMPLIED``). ``says`` is what the refusal names: the constraint for a
    CHECK or an index, the column for NOT NULL, and a phrase of its message for
    a trigger, which names no constraint.
    """

    name: str
    rules: tuple[str, ...]
    refused: type[BaseException]
    says: str
    write: Callable[[asyncpg.Connection], Awaitable[Any]]

    def names_its_rule(self, error: BaseException) -> bool:
        if isinstance(error, asyncpg.NotNullViolationError):
            return error.column_name == self.says
        if isinstance(
            error, asyncpg.CheckViolationError | asyncpg.UniqueViolationError
        ):
            return error.constraint_name == self.says
        return self.says in str(error)


async def _no_origin(conn: asyncpg.Connection) -> None:
    row = _finding_row()
    del row["origin"]
    await _insert(conn, "findings", row)


def _origin(origin: str) -> Callable[[asyncpg.Connection], Awaitable[Any]]:
    async def write(conn: asyncpg.Connection) -> None:
        await _finding(conn, origin=origin)

    return write


async def _model_raised_as_jev(conn: asyncpg.Connection) -> None:
    await _finding(conn, raised_by=f"jev:{CARD}")


async def _model_naming_a_request(conn: asyncpg.Connection) -> None:
    request = await _card_request(conn)
    await _finding(conn, source_request_id=request["id"])


def _jev(
    *,
    request: dict[str, Any] | None = None,
    answer: Any = _TRUE,
    **overrides: Any,
) -> Callable[[asyncpg.Connection], Awaitable[Any]]:
    """A Jev finding, lawful but for what is passed."""

    async def write(conn: asyncpg.Connection) -> None:
        row = await _jev_finding_row(conn, request=request, answer=answer)
        row.update(overrides)
        await _insert(conn, "findings", row)

    return write


async def _missing_request(conn: asyncpg.Connection) -> None:
    row = await _jev_finding_row(conn)
    beyond = await conn.fetchval("SELECT COALESCE(MAX(id), 0) + 1000 FROM jev_requests")
    row["source_request_id"] = beyond
    await _insert(conn, "findings", row)


async def _second_on_one_answer(conn: asyncpg.Connection) -> None:
    row = await _jev_finding_row(conn)
    await _insert(conn, "findings", row)
    await _insert(conn, "findings", {**row, "id": uuid.uuid4(), "ref": _unique("J")})


#: What each column but the closure's is changed to, given the stored row.
EDITS: dict[str, Callable[[asyncpg.Connection, asyncpg.Record], Awaitable[Any]]] = {}


def _edit(column: str):
    def register(
        value: Callable[[asyncpg.Connection, asyncpg.Record], Awaitable[Any]],
    ) -> Callable[[asyncpg.Connection, asyncpg.Record], Awaitable[Any]]:
        EDITS[column] = value
        return value

    return register


@_edit("id")
async def _(conn: asyncpg.Connection, row: asyncpg.Record) -> Any:
    return uuid.uuid4()


@_edit("ref")
async def _(conn: asyncpg.Connection, row: asyncpg.Record) -> Any:
    return _unique("F-D1")


@_edit("candidate_id")
async def _(conn: asyncpg.Connection, row: asyncpg.Record) -> Any:
    return (await _candidate(conn))["id"]


@_edit("raised_by")
async def _(conn: asyncpg.Connection, row: asyncpg.Record) -> Any:
    return "compliance"


@_edit("severity")
async def _(conn: asyncpg.Connection, row: asyncpg.Record) -> Any:
    return "low"


@_edit("title")
async def _(conn: asyncpg.Connection, row: asyncpg.Record) -> Any:
    return "A quieter title"


@_edit("detail_md")
async def _(conn: asyncpg.Connection, row: asyncpg.Record) -> Any:
    return "Rewritten detail."


@_edit("remediation")
async def _(conn: asyncpg.Connection, row: asyncpg.Record) -> Any:
    return "Rewritten remediation."


@_edit("opened_at")
async def _(conn: asyncpg.Connection, row: asyncpg.Record) -> Any:
    return datetime(2020, 1, 2, tzinfo=UTC)


@_edit("origin")
async def _(conn: asyncpg.Connection, row: asyncpg.Record) -> Any:
    return "operator"


@_edit("source_request_id")
async def _(conn: asyncpg.Connection, row: asyncpg.Record) -> Any:
    return (await _card_request(conn))["id"]


async def _stored_for(conn: asyncpg.Connection, column: str) -> asyncpg.Record:
    """
    A stored finding whose ``column`` can change with every other rule still
    met: a Jev finding for its request, which only a Jev finding names, and a
    model's on a candidate for the rest.
    """
    if column == "source_request_id":
        return await _insert(conn, "findings", await _jev_finding_row(conn))
    return await _finding(conn, candidate_id=(await _candidate(conn))["id"])


def _change(column: str) -> Callable[[asyncpg.Connection], Awaitable[Any]]:
    async def write(conn: asyncpg.Connection) -> None:
        stored = await _stored_for(conn, column)
        value = await EDITS[column](conn, stored)
        await conn.execute(
            f"UPDATE findings SET {column} = $1 WHERE id = $2", value, stored["id"]
        )

    return write


async def _closed(conn: asyncpg.Connection) -> asyncpg.Record:
    return await _finding(
        conn,
        status="accepted",
        closed_by="operator:quentin",
        closed_at=datetime.now(UTC),
        close_note="Accepted for the record.",
    )


async def _reopen(conn: asyncpg.Connection) -> None:
    stored = await _closed(conn)
    await conn.execute(
        "UPDATE findings SET status = 'open' WHERE id = $1", stored["id"]
    )


async def _delete(conn: asyncpg.Connection) -> None:
    stored = await _finding(conn)
    await conn.execute("DELETE FROM findings WHERE id = $1", stored["id"])


async def _delete_candidate(conn: asyncpg.Connection) -> None:
    candidate = await _candidate(conn)
    await _finding(conn, candidate_id=candidate["id"])
    await conn.execute("DELETE FROM candidates WHERE id = $1", candidate["id"])


async def _truncate(conn: asyncpg.Connection) -> None:
    await _finding(conn)
    await conn.execute("TRUNCATE findings")


async def _provenance_nobody_writes(conn: asyncpg.Connection) -> None:
    await _insert(conn, "jev_requests", _request_row(provenance="robot"))


def _evaluation(overrides: dict[str, Any]) -> Callable[[asyncpg.Connection], Any]:
    async def write(conn: asyncpg.Connection) -> None:
        await _insert_evaluation(conn, _measured(**overrides))

    return write


#: The trigger that holds a Jev finding to its answer, and what it says.
RESTS = "trg_findings_jev_rests_on_its_answer"
RESTS_SAYS = "rests on a valid true answer to a canonical guardrail.card request"

#: A request status other than ``ok``, each shaped as it really arrives.
NOT_OK = ("invalid", "error", "refused_budget", "refused_limits", "refused_model")

CASES: tuple[Case, ...] = (
    # Who wrote it.
    Case(
        "an insert naming no origin",
        ("findings.origin NOT NULL",),
        asyncpg.NotNullViolationError,
        "origin",
        _no_origin,
    ),
    Case(
        "an origin nobody writes",
        ("findings_origin_check",),
        asyncpg.CheckViolationError,
        "findings_origin_check",
        _origin("robot"),
    ),
    Case(
        "'unknown' raised from 0015 on",
        ("trg_findings_origin_is_known",),
        asyncpg.RaiseError,
        "names its writer",
        _origin("unknown"),
    ),
    Case(
        "a model's finding raised under a Jev raiser",
        ("findings_jev_is_raised_by_jev",),
        asyncpg.CheckViolationError,
        "findings_jev_is_raised_by_jev",
        _model_raised_as_jev,
    ),
    Case(
        "a model's finding naming a request",
        ("findings_jev_names_its_request",),
        asyncpg.CheckViolationError,
        "findings_jev_names_its_request",
        _model_naming_a_request,
    ),
    # A Jev finding never blocks, belongs to a candidate, and is one per answer.
    *(
        Case(
            f"a Jev finding at {severity}",
            ("findings_jev_never_blocks",),
            asyncpg.CheckViolationError,
            "findings_jev_never_blocks",
            _jev(severity=severity),
        )
        for severity in ("high", "critical")
    ),
    Case(
        "a Jev finding on no candidate",
        ("findings_jev_is_on_a_candidate",),
        asyncpg.CheckViolationError,
        "findings_jev_is_on_a_candidate",
        _jev(candidate_id=None),
    ),
    Case(
        "a second Jev finding on one candidate from one answer",
        ("findings_one_per_jev_answer",),
        asyncpg.UniqueViolationError,
        "findings_one_per_jev_answer",
        _second_on_one_answer,
    ),
    # A Jev finding rests on a valid true of a canonical card request.
    Case(
        "a Jev finding on a request nobody recorded",
        (RESTS, "findings_source_request_id_fkey"),
        asyncpg.ForeignKeyViolationError,
        "is not visible to this transaction",
        _missing_request,
    ),
    *(
        Case(
            f"a Jev finding on a request that is {status}",
            (RESTS,),
            asyncpg.RaiseError,
            RESTS_SAYS,
            _jev(request={"status": status}),
        )
        for status in NOT_OK
    ),
    Case(
        "a Jev finding on a probe",
        (RESTS,),
        asyncpg.RaiseError,
        RESTS_SAYS,
        _jev(request={"lane": "probe"}),
    ),
    Case(
        "a Jev finding on another set's true",
        (RESTS,),
        asyncpg.RaiseError,
        RESTS_SAYS,
        _jev(request={"question_set": "guardrail.other"}),
    ),
    Case(
        "a Jev finding raised under another set's name",
        (RESTS,),
        asyncpg.RaiseError,
        RESTS_SAYS,
        _jev(raised_by="jev:research.hypothesis"),
    ),
    Case(
        "a Jev finding on a valid false",
        (RESTS,),
        asyncpg.RaiseError,
        RESTS_SAYS,
        _jev(answer={"noul": 0.09, "argmax": "false"}),
    ),
    Case(
        "a Jev finding on an invalid answer naming true",
        (RESTS,),
        asyncpg.RaiseError,
        RESTS_SAYS,
        _jev(answer={"valid": False, "invalid_reason": "legend_mismatch"}),
    ),
    Case(
        "a Jev finding on a true to another question",
        (RESTS,),
        asyncpg.RaiseError,
        RESTS_SAYS,
        _jev(answer={"question_key": "addressed_to_ai"}),
    ),
    Case(
        "a Jev finding on a request with no answer",
        (RESTS,),
        asyncpg.RaiseError,
        RESTS_SAYS,
        _jev(answer=None),
    ),
    # What was raised stays raised.
    *(
        Case(
            f"a change of {column}",
            ("trg_findings_keep_what_was_raised",),
            asyncpg.RaiseError,
            "changes only by its closure",
            _change(column),
        )
        for column in EDITS
    ),
    Case(
        "a reopen",
        ("trg_findings_keep_what_was_raised",),
        asyncpg.RaiseError,
        "never reopened",
        _reopen,
    ),
    Case(
        "a DELETE",
        ("trg_findings_no_delete",),
        asyncpg.RaiseError,
        "DELETE is refused",
        _delete,
    ),
    Case(
        "a candidate's delete, cascading to its finding",
        ("trg_findings_no_delete",),
        asyncpg.RaiseError,
        "DELETE is refused",
        _delete_candidate,
    ),
    Case(
        "a TRUNCATE",
        ("trg_findings_no_truncate",),
        asyncpg.RaiseError,
        "TRUNCATE is refused",
        _truncate,
    ),
    # The provenance CHECK, rewritten to admit `system`, still refuses the rest.
    Case(
        "a request of a provenance nobody writes",
        ("jev_requests_provenance_check",),
        asyncpg.CheckViolationError,
        "jev_requests_provenance_check",
        _provenance_nobody_writes,
    ),
    # Plan v2's flips: counts, and no longer bounded by n.
    *(
        Case(
            name,
            (constraint,),
            asyncpg.CheckViolationError,
            constraint,
            _evaluation(overrides),
        )
        for name, overrides, constraint in EVALUATION_CASES
        if constraint == "jev_evaluations_flip_counts_are_counts"
    ),
)


async def _rules(conn: asyncpg.Connection) -> dict[tuple[str, str], str]:
    """
    Every rule of the public schema, by table and name, with its definition:
    constraints, indexes, triggers with their functions' source, rewrite
    rules, and the columns that may not be NULL.
    """
    rules: dict[tuple[str, str], str] = {}
    for row in await conn.fetch(
        """
        SELECT c.conrelid::regclass::text AS tbl, c.conname AS name,
               pg_get_constraintdef(c.oid) AS definition
          FROM pg_constraint c
          JOIN pg_namespace n ON n.oid = c.connamespace
         WHERE n.nspname = 'public' AND c.contype IN ('c', 'f', 'u', 'p', 'x')
        """
    ):
        rules[(row["tbl"], row["name"])] = row["definition"]
    for row in await conn.fetch(
        "SELECT tablename, indexname, indexdef FROM pg_indexes "
        "WHERE schemaname = 'public'"
    ):
        rules[(row["tablename"], row["indexname"])] = row["indexdef"]
    for row in await conn.fetch(
        """
        SELECT t.tgrelid::regclass::text AS tbl, t.tgname AS name,
               pg_get_triggerdef(t.oid) || pg_get_functiondef(t.tgfoid) AS definition
          FROM pg_trigger t
          JOIN pg_class r ON r.oid = t.tgrelid
          JOIN pg_namespace n ON n.oid = r.relnamespace
         WHERE n.nspname = 'public' AND NOT t.tgisinternal
        """
    ):
        rules[(row["tbl"], row["name"])] = row["definition"]
    for row in await conn.fetch(
        "SELECT tablename, rulename, definition FROM pg_rules "
        "WHERE schemaname = 'public'"
    ):
        rules[(row["tablename"], row["rulename"])] = row["definition"]
    for row in await conn.fetch(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND is_nullable = 'NO'"
    ):
        name = f"{row['table_name']}.{row['column_name']} NOT NULL"
        rules[(row["table_name"], name)] = "NOT NULL"
    return rules


class TestEveryRuleBites:
    @pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
    async def test_a_write_that_breaks_a_rule_is_refused(
        self, conn: asyncpg.Connection, case: Case
    ) -> None:
        async with _rolled_back(conn):
            with pytest.raises(case.refused) as refused:
                await case.write(conn)
            assert case.names_its_rule(refused.value), refused.value

    @pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
    async def test_each_case_breaks_its_rule_alone(
        self, conn: asyncpg.Connection, case: Case
    ) -> None:
        """
        With the rule dropped — and, for a case ``IMPLIED`` names, the rule it
        is implied by — the write is admitted, in a transaction rolled back
        after, so nothing it did and nothing dropped survives the test.
        """
        async with _rolled_back(conn):
            for rule in case.rules:
                await conn.execute(_drop(rule))
            await case.write(conn)

    def test_every_case_is_a_rule_0015_adds(self) -> None:
        for case in CASES:
            assert set(case.rules) <= set(RULES), case.name
            assert set(case.rules[1:]) <= set(IMPLIED), case.name

    async def test_every_rule_0015_adds_has_a_case(
        self, conn: asyncpg.Connection, tmp_path: Any
    ) -> None:
        """
        What 0015 adds or rewrites, read from the catalogue: a database at 0014
        beside this one, fully migrated. Each rule has a case here that breaks
        it alone, or, for a rewritten rule of 0014's whose cases are C9's, one
        in ``test_jev_evaluations.py``'s ``BROKEN``, which runs on a fully
        migrated database too; or it is ``IMPLIED``, with the reason.
        """
        directories = _migrations_up_to(tmp_path, 14)
        at_0014 = await _fresh_database("phase_d_rules_at_0014")
        await migrations.migrate(at_0014, directory=directories[14])
        before_conn = await asyncpg.connect(at_0014)
        try:
            before = await _rules(before_conn)
        finally:
            await before_conn.close()
        after = await _rules(conn)

        assert set(before) <= set(after), sorted(set(before) - set(after))
        changed = {
            key for key, definition in after.items() if before.get(key) != definition
        }
        assert {name: table for table, name in changed} == RULES

        covered = {rule for case in CASES for rule in case.rules[:1]}
        covered |= {constraint for _, _, constraint in EVALUATION_CASES}
        assert set(RULES) == (covered & set(RULES)) | set(IMPLIED)


# ---------------------------------------------------------------------------
# The migration over a database at 0014
# ---------------------------------------------------------------------------


async def _rows_at_0014(conn: asyncpg.Connection) -> dict[str, Any]:
    """
    Rows as a database at 0014 holds them: findings open, closed and
    programme-wide, written before ``origin`` existed; evaluations; a request.
    """
    candidate = await _candidate(conn)
    findings = [
        await _insert(
            conn,
            "findings",
            {
                "id": uuid.uuid4(),
                "ref": _unique("F-0014"),
                "candidate_id": candidate["id"],
                "raised_by": "independent_risk",
                "severity": "high",
                "title": "Raised before 0015",
                "detail_md": "Synthetic detail.",
            },
        ),
        await _insert(
            conn,
            "findings",
            {
                "id": uuid.uuid4(),
                "ref": _unique("F-0014"),
                "candidate_id": candidate["id"],
                "raised_by": "compliance",
                "severity": "medium",
                "title": "Closed before 0015",
                "status": "remediated",
                "closed_at": datetime(2026, 9, 1, tzinfo=UTC),
                "closed_by": "operator:quentin",
                "close_note": "Fixed.",
            },
        ),
        await _insert(
            conn,
            "findings",
            {
                "id": uuid.uuid4(),
                "ref": _unique("F-0014"),
                "candidate_id": None,
                "raised_by": "programme_director",
                "severity": "low",
                "title": "Programme-wide, before 0015",
            },
        ),
    ]
    evaluations = [await _insert_evaluation(conn, _measured())]
    request, _ = await _exchange(conn)
    return {
        "candidate": candidate,
        "findings": findings,
        "evaluations": evaluations,
        "request": request,
    }


class TestTheMigration:
    async def test_it_applies_on_top_of_a_database_already_at_0014(
        self, tmp_path: Any
    ) -> None:
        """
        Taken to 0014 first and given rows, the database goes to 0015 through
        the shipped runner: every row as it was, each finding's writer
        ``'unknown'`` with no request named, and the arming switch off.
        """
        directories = _migrations_up_to(tmp_path, 14, 15)
        dsn = await _fresh_database("phase_d_upgrade")
        first = await migrations.migrate(dsn, directory=directories[14])
        assert [m.version for m in first] == list(range(1, 15))
        on_disk = {m.version: m for m in migrations.discover()}

        conn = await asyncpg.connect(dsn)
        try:
            before = await _rows_at_0014(conn)
            applied = await migrations.migrate(dsn, directory=directories[15])

            assert [str(m) for m in applied] == ["0015_jev_phase_d"]
            assert (
                await conn.fetchval(
                    "SELECT checksum FROM schema_migrations WHERE version = 15"
                )
                == on_disk[15].checksum
            )
            assert await migrations.migrate(dsn, directory=directories[15]) == []

            for finding in before["findings"]:
                after = await _read(conn, finding["id"])
                assert {key: after[key] for key in finding.keys()} == dict(finding)
                assert after["origin"] == "unknown"
                assert after["source_request_id"] is None
            for evaluation in before["evaluations"]:
                assert (
                    await conn.fetchrow(
                        "SELECT * FROM jev_evaluations WHERE id = $1", evaluation["id"]
                    )
                    == evaluation
                )
            assert (
                await conn.fetchrow(
                    "SELECT * FROM jev_requests WHERE id = $1", before["request"]["id"]
                )
                == before["request"]
            )
            assert await flags.jev_arm_card_check(conn) is False

            # From here, a finding names its writer, and none is removed.
            with pytest.raises(asyncpg.NotNullViolationError):
                await _no_origin(conn)
            with pytest.raises(asyncpg.RaiseError, match="DELETE is refused"):
                await conn.execute(
                    "DELETE FROM findings WHERE id = $1", before["findings"][0]["id"]
                )
            assert await _read(conn, before["findings"][0]["id"]) is not None
        finally:
            await conn.close()

    async def test_it_fails_whole_over_a_row_its_rules_refuse(
        self, tmp_path: Any
    ) -> None:
        """
        No writer has ever raised a finding under a ``jev:`` raiser — the API
        takes a role's key and the tick its own — so no database holds one.
        Were one to, it would read ``'unknown'`` beside a Jev raiser, which
        ``findings_jev_is_raised_by_jev`` refuses: 0015 fails whole, in its
        transaction, and the database stays at 0014 for somebody to look at.
        """
        directories = _migrations_up_to(tmp_path, 14, 15)
        dsn = await _fresh_database("phase_d_upgrade_refused")
        await migrations.migrate(dsn, directory=directories[14])
        conn = await asyncpg.connect(dsn)
        try:
            await _insert(
                conn,
                "findings",
                {
                    "id": uuid.uuid4(),
                    "ref": _unique("F-0014"),
                    "raised_by": f"jev:{CARD}",
                    "severity": "medium",
                    "title": "A raiser no writer uses",
                },
            )
            with pytest.raises(asyncpg.CheckViolationError) as refused:
                await migrations.migrate(dsn, directory=directories[15])
            assert refused.value.constraint_name == "findings_jev_is_raised_by_jev"
            assert (
                await conn.fetchval("SELECT MAX(version) FROM schema_migrations") == 14
            )
            assert (
                await conn.fetch(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'findings' AND column_name = 'origin'"
                )
                == []
            )
            assert (
                await conn.fetchval(
                    "SELECT COUNT(*) FROM system_flags WHERE key = 'jev_arm_card_check'"
                )
                == 0
            )
            assert await _vocabulary(conn, "jev_requests_provenance_check") == set(
                PROVENANCES
            )
        finally:
            await conn.close()


# ---------------------------------------------------------------------------
# Who wrote it
# ---------------------------------------------------------------------------


class TestOriginIsKnownFromNowOn:
    async def test_an_insert_naming_no_origin_fails_on_not_null(
        self, conn: asyncpg.Connection
    ) -> None:
        """
        On the column, not on a trigger's message: a BEFORE trigger runs before
        NOT NULL is checked, which is why every comparison of ``origin`` in
        0015's triggers is NULL-safe (docs/09, section 7).
        """
        with pytest.raises(asyncpg.NotNullViolationError) as refused:
            await _no_origin(conn)
        assert refused.value.column_name == "origin"
        assert refused.value.table_name == "findings"

    async def test_the_column_has_no_default(self, conn: asyncpg.Connection) -> None:
        column = await conn.fetchrow(
            "SELECT is_nullable, column_default FROM information_schema.columns "
            "WHERE table_name = 'findings' AND column_name = 'origin'"
        )
        assert dict(column) == {"is_nullable": "NO", "column_default": None}

    async def test_unknown_is_refused_by_its_trigger(
        self, conn: asyncpg.Connection
    ) -> None:
        stored = _finding_row(origin="unknown")
        with pytest.raises(asyncpg.RaiseError, match="names its writer"):
            await _insert(conn, "findings", stored)
        assert await _read(conn, stored["id"]) is None

    @pytest.mark.parametrize("origin", ["model", "operator"])
    async def test_each_writer_is_admitted(
        self, conn: asyncpg.Connection, origin: str
    ) -> None:
        stored = await _finding(conn, origin=origin)
        assert (await _read(conn, stored["id"]))["origin"] == origin

    @pytest.mark.parametrize("origin", ["model", "operator"])
    async def test_raise_finding_writes_the_origin_it_is_given(
        self, conn: asyncpg.Connection, origin: str
    ) -> None:
        """The shipped writer, on the shipped schema."""
        candidate = await _candidate(conn)
        raised = await repo.raise_finding(
            conn,
            str(candidate["id"]),
            "independent_risk",
            "high",
            "A synthetic finding",
            origin=origin,
        )
        row = await conn.fetchrow(
            "SELECT origin, source_request_id FROM findings WHERE ref = $1",
            raised["ref"],
        )
        assert dict(row) == {"origin": origin, "source_request_id": None}

    @pytest.mark.parametrize("origin", ["jev", "unknown", "robot"])
    async def test_raise_finding_refuses_any_other_writer_before_the_insert(
        self, conn: asyncpg.Connection, origin: str
    ) -> None:
        before = await conn.fetchval("SELECT COUNT(*) FROM findings")
        with pytest.raises(ValueError, match="written by one of"):
            await repo.raise_finding(
                conn,
                None,
                "independent_risk",
                "high",
                "A synthetic finding",
                origin=origin,
            )
        assert await conn.fetchval("SELECT COUNT(*) FROM findings") == before


# ---------------------------------------------------------------------------
# What was raised stays raised
# ---------------------------------------------------------------------------


class TestWhatWasRaisedStaysRaised:
    @pytest.mark.parametrize("column", list(EDITS))
    async def test_each_column_but_the_closures_is_refused(
        self, conn: asyncpg.Connection, column: str
    ) -> None:
        stored = await _stored_for(conn, column)
        value = await EDITS[column](conn, stored)
        with pytest.raises(asyncpg.RaiseError, match="changes only by its closure"):
            await conn.execute(
                f"UPDATE findings SET {column} = $1 WHERE id = $2", value, stored["id"]
            )
        assert await _read(conn, stored["id"]) == stored

    def test_every_column_is_either_the_closures_or_refused(self) -> None:
        """A column 0008 or 0015 gives the table is in one list or the other."""
        assert set(EDITS).isdisjoint(CLOSURE)

    async def test_every_column_of_the_table_is_covered(
        self, conn: asyncpg.Connection
    ) -> None:
        columns = {
            row["column_name"]
            for row in await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'findings'"
            )
        }
        assert columns == set(EDITS) | set(CLOSURE)

    async def test_a_closure_is_admitted(self, conn: asyncpg.Connection) -> None:
        """Through the shipped close, as the API calls it."""
        stored = await _finding(conn)
        await repo.close_finding(
            conn, stored["ref"], "remediated", "operator:quentin", "Fixed."
        )
        closed = await _read(conn, stored["id"])
        assert closed["status"] == "remediated"
        assert closed["closed_by"] == "operator:quentin"
        assert closed["close_note"] == "Fixed."
        assert closed["closed_at"] is not None
        assert {k: closed[k] for k in EDITS} == {k: stored[k] for k in EDITS}

    async def test_a_reopen_is_refused(self, conn: asyncpg.Connection) -> None:
        """0008's CHECK admits ``open`` always; 0015's trigger is what refuses it."""
        stored = await _closed(conn)
        with pytest.raises(asyncpg.RaiseError, match="never reopened"):
            await conn.execute(
                "UPDATE findings SET status = 'open', closed_by = NULL, "
                "closed_at = NULL WHERE id = $1",
                stored["id"],
            )
        assert await _read(conn, stored["id"]) == stored

    async def test_a_delete_is_refused(self, conn: asyncpg.Connection) -> None:
        stored = await _finding(conn, severity="critical", raised_by="independent_risk")
        with pytest.raises(asyncpg.RaiseError, match="DELETE is refused"):
            await conn.execute("DELETE FROM findings WHERE id = $1", stored["id"])
        assert await _read(conn, stored["id"]) == stored

    async def test_a_truncate_is_refused(self, conn: asyncpg.Connection) -> None:
        stored = await _finding(conn)
        with pytest.raises(asyncpg.RaiseError, match="TRUNCATE is refused"):
            await conn.execute("TRUNCATE findings")
        assert await _read(conn, stored["id"]) == stored

    async def test_a_candidates_cascading_delete_is_refused(
        self, conn: asyncpg.Connection
    ) -> None:
        """
        0008 cascades a candidate's delete to its findings, so a blocking veto
        could be removed by removing what it blocks. The cascade's DELETE meets
        the same trigger, and the candidate stays with it.
        """
        candidate = await _candidate(conn)
        stored = await _finding(conn, candidate_id=candidate["id"])
        with pytest.raises(asyncpg.RaiseError, match="DELETE is refused"):
            await conn.execute("DELETE FROM candidates WHERE id = $1", candidate["id"])
        assert await _read(conn, stored["id"]) == stored
        assert (
            await conn.fetchval(
                "SELECT COUNT(*) FROM candidates WHERE id = $1", candidate["id"]
            )
            == 1
        )

    async def test_a_candidate_with_no_finding_can_still_be_deleted(
        self, conn: asyncpg.Connection
    ) -> None:
        """0015 refuses removing what was raised, and nothing else (docs/09, 15.2)."""
        candidate = await _candidate(conn)
        await conn.execute("DELETE FROM candidates WHERE id = $1", candidate["id"])
        assert (
            await conn.fetchval(
                "SELECT COUNT(*) FROM candidates WHERE id = $1", candidate["id"]
            )
            == 0
        )


# ---------------------------------------------------------------------------
# A Jev finding
# ---------------------------------------------------------------------------


class TestAJevFindingRestsOnItsAnswer:
    async def test_a_finding_on_a_valid_true_is_admitted(
        self, conn: asyncpg.Connection
    ) -> None:
        """The pair to every refusal below, from the same builder."""
        row = await _jev_finding_row(conn)
        stored = await _insert(conn, "findings", row)
        assert (stored["origin"], stored["raised_by"], stored["severity"]) == (
            "jev",
            f"jev:{CARD}",
            "medium",
        )

    async def test_one_per_candidate_per_answer(self, conn: asyncpg.Connection) -> None:
        """The index is per candidate: one answer may raise one on each."""
        row = await _jev_finding_row(conn)
        await _insert(conn, "findings", row)
        other = (await _candidate(conn))["id"]
        await _insert(
            conn,
            "findings",
            {**row, "id": uuid.uuid4(), "ref": _unique("J"), "candidate_id": other},
        )

    @pytest.mark.parametrize(
        "case",
        [case for case in CASES if RESTS in case.rules],
        ids=lambda case: case.name,
    )
    async def test_each_way_of_not_resting_on_it_is_refused(
        self, conn: asyncpg.Connection, case: Case
    ) -> None:
        before = await conn.fetchval("SELECT COUNT(*) FROM findings")
        with pytest.raises(case.refused) as refused:
            await _refused(conn, case.write(conn))
        assert case.says in str(refused.value)
        assert await conn.fetchval("SELECT COUNT(*) FROM findings") == before

    async def test_a_low_jev_finding_is_admitted(
        self, conn: asyncpg.Connection
    ) -> None:
        await _insert(conn, "findings", await _jev_finding_row(conn, severity="low"))


# ---------------------------------------------------------------------------
# Refs
# ---------------------------------------------------------------------------


class TestTheJevRefs:
    @pytest.mark.parametrize(
        ("count", "ref"),
        [
            (1, "J-0001"),
            (9_999, "J-9999"),
            (10_000, "J-10000"),
            (10_001, "J-10001"),
            (123_456, "J-123456"),
        ],
    )
    async def test_the_ref_is_never_cut(
        self, conn: asyncpg.Connection, count: int, ref: str
    ) -> None:
        """``repo.JEV_REF_SQL``, evaluated for ``n`` as its one user computes it."""
        computed = await conn.fetchval(
            f"SELECT 'J-' || {repo.JEV_REF_SQL} FROM (SELECT $1::text AS n) AS next",
            str(count),
        )
        assert computed == ref

    async def test_lpad_alone_would_cut_it(self, conn: asyncpg.Connection) -> None:
        """Why the expression is what it is: PostgreSQL's lpad truncates."""
        assert await conn.fetchval("SELECT lpad('10001', 4, '0')") == "1000"


# ---------------------------------------------------------------------------
# Provenance `system`
# ---------------------------------------------------------------------------


async def _system_exchange(
    conn: asyncpg.Connection,
) -> tuple[asyncpg.Record, asyncpg.Record]:
    """An ``ok`` request recorded as ``system``, with a valid answer to it."""
    return await _exchange(conn, request={"provenance": "system"})


class TestTheProvenances:
    async def test_system_is_admitted_on_jev_requests(
        self, conn: asyncpg.Connection
    ) -> None:
        request, _ = await _system_exchange(conn)
        assert request["provenance"] == "system"

    async def test_jev_signals_refuses_system(self, conn: asyncpg.Connection) -> None:
        """
        A signal copying its request's provenance passes the origin trigger,
        and ``jev_signals_provenance_check``, as 0013 wrote it, refuses it.
        """
        signal = _signal_for(*await _system_exchange(conn))
        assert signal["provenance"] == "system"
        with pytest.raises(asyncpg.CheckViolationError) as refused:
            await _insert(conn, "jev_signals", signal)
        assert refused.value.constraint_name == "jev_signals_provenance_check"

    async def test_that_refusal_is_the_signals_check_alone(
        self, conn: asyncpg.Connection
    ) -> None:
        async with _rolled_back(conn):
            await conn.execute(
                "ALTER TABLE jev_signals DROP CONSTRAINT jev_signals_provenance_check"
            )
            await _insert(
                conn, "jev_signals", _signal_for(*await _system_exchange(conn))
            )

    async def test_a_signal_on_a_system_request_is_refused(
        self, conn: asyncpg.Connection
    ) -> None:
        """Claiming another provenance meets the trigger that holds it to its
        request's."""
        signal = _signal_for(*await _system_exchange(conn), provenance="internal")
        with pytest.raises(asyncpg.RaiseError, match="lane, provenance and pack"):
            await _insert(conn, "jev_signals", signal)

    async def test_the_two_vocabularies(self, conn: asyncpg.Connection) -> None:
        assert await _vocabulary(conn, "jev_requests_provenance_check") == set(
            REQUEST_PROVENANCES
        )
        assert await _vocabulary(conn, "jev_signals_provenance_check") == set(
            PROVENANCES
        )
        assert "system" not in PROVENANCES


# ---------------------------------------------------------------------------
# The arming switch
# ---------------------------------------------------------------------------


class TestTheArmingSwitchIsSeededOff:
    async def test_it_reads_off_through_the_shipped_reader(
        self, conn: asyncpg.Connection
    ) -> None:
        assert await flags.jev_arm_card_check(conn) is False

    async def test_it_is_seeded_as_json_false_by_the_migration(
        self, conn: asyncpg.Connection
    ) -> None:
        row = await conn.fetchrow(
            "SELECT value, updated_by FROM system_flags WHERE key = $1",
            flags.JEV_ARM_CARD_CHECK,
        )
        assert json.loads(row["value"]) is False
        assert row["updated_by"] == "migration"


# ---------------------------------------------------------------------------
# Plan v2's flips
# ---------------------------------------------------------------------------


class TestFlipCountsAboveN:
    """
    Under plan v2 a flip rate counts every canonical request of the question
    under the pin, labelled or not (M2), so its pairs, and the re-asks it could
    not compare, can outnumber the n scored items. Each row here 0014 refused.
    """

    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param({"flip_rate_n": 201}, id="flip_rate_n above n"),
            pytest.param(
                {"flip_rate_low_margin_n": 201}, id="flip_rate_low_margin_n above n"
            ),
            pytest.param(
                {"flip_rate_near_threshold_n": 201},
                id="flip_rate_near_threshold_n above n",
            ),
            pytest.param(
                {"flip_rate_not_compared": 106},
                id="more re-asks in the two strata than items",
            ),
            pytest.param(
                {"flip_rate_near_threshold_not_compared": 166},
                id="more re-asks near the threshold than items",
            ),
            pytest.param(
                {
                    "flip_rate_n": 2_000,
                    "flip_rate_not_compared": 300,
                    "flip_rate_low_margin_n": 1_500,
                    "flip_rate_low_margin_not_compared": 250,
                    "flip_rate_near_threshold_n": 900,
                    "flip_rate_near_threshold_not_compared": 400,
                },
                id="every stratum above n at once",
            ),
        ],
    )
    async def test_a_population_larger_than_n_is_admitted(
        self, conn: asyncpg.Connection, overrides: dict[str, Any]
    ) -> None:
        row = _measured(**overrides)
        assert row["n"] == 200
        stored = await _insert_evaluation(conn, row)
        assert {key: stored[key] for key in overrides} == overrides
