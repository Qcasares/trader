"""
test_jev_schema.py
------------------
Migration 0012, the Jev ledger and its switches, against real PostgreSQL.

Every rule in it is a trigger, a CHECK or an index, so none of it can be proved
without the database that enforces it. Each refusal is asserted by attempting
the forbidden write and then reading the row back: an exception that had already
changed the row would be a refusal in name only.

Rows are written with plain SQL rather than through ``jev_repo``, so what is
tested is the schema, which holds whatever writes to it, and not one writer's
good manners.

Runs on databases of its own, derived from ``TEST_DATABASE_URL`` the way
``test_deployment_enable_gate.py`` derives ``_enable``. It has to: the ledger
refuses DELETE and TRUNCATE, so rows written here could never be cleared from a
shared database, and a second run would find the first run's canonical answers
already recorded. Skipped unless ``TEST_DATABASE_URL`` is set.

    TEST_DATABASE_URL=postgresql://localhost/trader_test \\
        pytest tests/integration/test_jev_schema.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

pytest.importorskip("asyncpg")

import asyncpg  # noqa: E402

from src.db import migrate as migrations  # noqa: E402
from src.programme import jev_repo  # noqa: E402

TEST_DSN = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DSN, reason="TEST_DATABASE_URL not set; skipping Jev schema tests"
)

MODEL = "jev-1.13.0"

#: One Choice question, its options in an order ``jsonb`` would not keep:
#: ``jsonb`` sorts keys by length and then bytes, so it would put ``neutral``
#: ahead of ``risk_on``.
OPTIONS = ["risk_on", "neutral", "risk_off", "insufficient_evidence"]
QUESTIONS = {
    "regime": {
        "type": "choice",
        "instructions": "Which regime do these descriptors describe?",
        "criteria": {
            "risk_on": "Trends up, volatility subdued.",
            "neutral": "Mixed descriptors.",
            "risk_off": "Trends down, volatility elevated.",
            "insufficient_evidence": "The descriptors do not support a call.",
        },
    }
}
PROBABILITIES = {
    "risk_on": 0.62,
    "neutral": 0.21,
    "risk_off": 0.12,
    "insufficient_evidence": 0.05,
}
BODY = json.dumps(
    {
        "model": MODEL,
        "answers": {
            "regime": {
                "type": "choice",
                "choice": "risk_on",
                "confidence": 0.49,
                "probabilities": PROBABILITIES,
            }
        },
        "usage": {"input_tokens": 212, "output_tokens": 0},
    }
)

LANES = ("research", "guardrail", "findings", "ops", "signals", "decision", "probe")
PROVENANCES = ("web", "internal", "operator")
REFUSED = ("refused_budget", "refused_limits", "refused_model")

#: Dates no honest stamp could carry: well before the ledger existed, and well
#: after anyone reading this.
PAST = datetime(2000, 1, 3, tzinfo=UTC)
FUTURE = datetime(2100, 1, 4, tzinfo=UTC)

#: The switches migration 0012 seeds, and the value each must start with.
SEEDED_SWITCHES = {
    "jev_enabled": False,
    "jev_model": "jev-1.13.0",
    "jev_area_research": False,
    "jev_area_ops": False,
    "jev_area_findings": False,
    "jev_area_guardrails": False,
    "jev_area_signals": False,
    "jev_area_decisions": False,
    "jev_daily_request_budget": 500,
    "jev_max_state_tokens": 8000,
    "jev_send_internal_detail": False,
}

#: Columns sent as JSON text, and the type each is cast to on the way in.
JSON_COLUMNS = {
    ("jev_requests", "state"): "jsonb",
    ("jev_requests", "questions"): "json",
    ("jev_answers", "probabilities"): "jsonb",
    ("jev_evaluations", "n_per_class"): "jsonb",
    ("jev_evaluations", "calibration_bins"): "jsonb",
    ("hypotheses", "card"): "jsonb",
    ("deployments", "params"): "jsonb",
    ("backtest_runs", "params"): "jsonb",
    ("walkforward_runs", "params"): "jsonb",
}


# ---------------------------------------------------------------------------
# Databases
# ---------------------------------------------------------------------------


def _derived(suffix: str) -> str:
    base, _, tail = TEST_DSN.partition("?")
    return f"{base}_{suffix}?{tail}" if tail else f"{base}_{suffix}"


async def _fresh_database(suffix: str) -> str:
    """An empty database named after ``TEST_DATABASE_URL``'s, plus ``suffix``."""
    dsn = _derived(suffix)
    # The name comes from before the query string: a Unix-socket DSN puts the
    # socket path after it, and splitting the whole URL on "/" would return
    # that instead of the database.
    name = dsn.partition("?")[0].rsplit("/", 1)[-1]
    admin = await asyncpg.connect(TEST_DSN)
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()
    return dsn


@pytest.fixture(scope="module")
def dsn() -> str:
    async def setup() -> str:
        fresh = await _fresh_database("jev_schema")
        await migrations.migrate(fresh)
        return fresh

    return asyncio.run(setup())


@pytest.fixture
async def conn(dsn: str):
    connection = await asyncpg.connect(dsn)
    try:
        yield connection
    finally:
        await connection.close()


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


async def _insert(
    conn: asyncpg.Connection, table: str, row: dict[str, Any]
) -> asyncpg.Record:
    columns = list(row)
    values: list[Any] = []
    placeholders: list[str] = []
    for position, column in enumerate(columns, start=1):
        cast = JSON_COLUMNS.get((table, column))
        value = row[column]
        if cast is not None and value is not None:
            value = json.dumps(value)
        values.append(value)
        placeholders.append(f"${position}::{cast}" if cast else f"${position}")
    return await conn.fetchrow(
        f"INSERT INTO {table} ({', '.join(columns)}) "
        f"VALUES ({', '.join(placeholders)}) RETURNING *",
        *values,
    )


async def _count(
    conn: asyncpg.Connection, table: str, where: str = "TRUE", *args: Any
) -> int:
    return await conn.fetchval(f"SELECT COUNT(*) FROM {table} WHERE {where}", *args)


async def _clock(conn: asyncpg.Connection) -> datetime:
    return await conn.fetchval("SELECT clock_timestamp()")


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _request_row(status: str = "ok", **overrides: Any) -> dict[str, Any]:
    """A request row of ``status``, shaped the way that status really arrives."""
    row: dict[str, Any] = {
        "request_hash": uuid.uuid4().hex + uuid.uuid4().hex,
        "state_hash": "5" * 64,
        "question_set": "decision.regime",
        "question_set_version": 1,
        "pack_hash": "9" * 64,
        "lane": "decision",
        "provenance": "internal",
        "subject_type": "session",
        "subject_id": "2026-09-25",
        "as_of": datetime(2026, 9, 25, 20, tzinfo=UTC),
        "state": {"equities_trend": "above", "equities_drawdown": "shallow"},
        "questions": QUESTIONS,
        "model_requested": MODEL,
        "model_answered": MODEL,
        "vendor_request_id": _unique("req"),
        "http_status": 200,
        "status": status,
        "raw_body": BODY,
        "input_tokens": 212,
        "output_tokens": 0,
        "latency_ms": 140,
        "requested_at": datetime.now(UTC),
    }
    if status == "invalid":
        row["raw_body"] = json.dumps({"model": MODEL, "answers": {}})
    elif status == "error":
        row.update(
            http_status=None,
            vendor_request_id=None,
            model_answered=None,
            raw_body=None,
            error_class="TypeSafeAPIConnectionError",
            error_kind="connection",
            latency_ms=10_000,
        )
    elif status in REFUSED:
        row.update(
            http_status=None,
            vendor_request_id=None,
            model_answered=None,
            raw_body=None,
            input_tokens=None,
            output_tokens=None,
            latency_ms=None,
        )
    row.update(overrides)
    return row


def _answer_row(request_id: int, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "request_id": request_id,
        "question_key": "regime",
        "question_type": "choice",
        "choice": "risk_on",
        "probabilities": PROBABILITIES,
        "confidence": 0.49,
        "argmax": "risk_on",
        "margin": 0.41,
        "valid": True,
    }
    row.update(overrides)
    return row


#: A valid answer of each type, shaped as the validator writes one. The Choice
#: is ``_answer_row``'s defaults.
VALID_ANSWERS: dict[str, dict[str, Any]] = {
    "noul": {
        "question_key": "in_scope",
        "question_type": "noul",
        "noul": 0.83,
        "choice": None,
        "probabilities": None,
        "confidence": None,
        "argmax": "true",
        "margin": 0.66,
    },
    "choice": {},
    "score": {
        "question_key": "severity",
        "question_type": "score",
        "choice": None,
        "score": 2.0,
        "probabilities": {"0": 0.1, "1": 0.2, "2": 0.7},
        "confidence": 0.55,
        "argmax": "2",
        "margin": 0.5,
    },
}

#: For each question type, what a valid answer of it cannot be without.
MEASURED = {
    "noul": ("noul", "argmax", "margin"),
    "choice": ("choice", "probabilities", "confidence", "argmax", "margin"),
    "score": ("score", "probabilities", "confidence", "argmax", "margin"),
}


async def _exchange(
    conn: asyncpg.Connection,
    *,
    request: dict[str, Any] | None = None,
    answer: dict[str, Any] | None = None,
) -> tuple[asyncpg.Record, asyncpg.Record]:
    """
    A request and one answer to it: by default a valid Choice on an ``ok``
    decision-lane request, the only kind a measured signal may rest on.
    """
    stored = await _insert(conn, "jev_requests", _request_row(**(request or {})))
    answered = await _insert(
        conn, "jev_answers", _answer_row(stored["id"], **(answer or {}))
    )
    return stored, answered


async def _answer(conn: asyncpg.Connection) -> asyncpg.Record:
    return (await _exchange(conn))[1]


def _signal_for(
    request: asyncpg.Record, answer: asyncpg.Record, **overrides: Any
) -> dict[str, Any]:
    """A measured signal whose origin is its answer's request, as it must be."""
    row: dict[str, Any] = {
        "signal": _unique("regime"),
        "symbol": "SPY",
        "session": date(2026, 9, 25),
        "status": "measured",
        "value": answer["choice"],
        "answer_id": answer["id"],
        "lane": request["lane"],
        "provenance": request["provenance"],
        "pack_hash": request["pack_hash"],
        "model": request["model_answered"],
        "decision_cutoff": FUTURE,
    }
    row.update(overrides)
    return row


async def _signal_row(conn: asyncpg.Connection, **overrides: Any) -> dict[str, Any]:
    return _signal_for(*await _exchange(conn), **overrides)


def _label_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "question_set": "research.catalogue",
        "question_set_version": 1,
        "question_key": "asset_class",
        "subject_type": "catalogue_entry",
        "subject_id": _unique("entry"),
        "label": "equities",
        "labelled_by": "operator:quentin",
    }
    row.update(overrides)
    return row


def _evaluation_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "question_set": "research.catalogue",
        "question_set_version": 1,
        "question_key": "asset_class",
        "model": MODEL,
        "dataset_ref": "readme-61",
        "dataset_sha256": "a" * 64,
        "possibly_in_training": True,
        "n": 61,
        "n_per_class": {"equities": 40, "bonds": 21},
        "code_commit": "0ec084f",
    }
    row.update(overrides)
    return row


def _document_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "source": "sec_edgar_rss",
        "url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent",
        "content_sha256": uuid.uuid4().hex + uuid.uuid4().hex,
        "title": "8-K, current report",
        "excerpt": "Item 2.02 Results of Operations and Financial Condition.",
    }
    row.update(overrides)
    return row


async def _candidate(conn: asyncpg.Connection) -> asyncpg.Record:
    hypothesis = await _insert(
        conn,
        "hypotheses",
        {"id": uuid.uuid4(), "ref": _unique("H-JEV"), "title": "Jev fixture"},
    )
    return await _insert(
        conn,
        "candidates",
        {
            "id": uuid.uuid4(),
            "hypothesis_id": hypothesis["id"],
            "strategy_name": "buy_and_hold",
            "start_session": date(2015, 1, 2),
            "end_session": date(2019, 12, 31),
            "data_source": "yfinance",
        },
    )


def _deployment_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": uuid.uuid4(),
        "owner_id": "default",
        "strategy_name": "buy_and_hold",
        "params": {"symbols": ["SPY"]},
        "mode": "paper",
        "capital_usd": 10_000,
        "status": "disabled",
    }
    row.update(overrides)
    return row


async def _backtest(conn: asyncpg.Connection, **overrides: Any) -> asyncpg.Record:
    row: dict[str, Any] = {
        "id": uuid.uuid4(),
        "strategy_name": "buy_and_hold",
        "params": {"symbols": ["SPY"]},
        "start_session": date(2015, 1, 2),
        "end_session": date(2019, 12, 31),
        "initial_cash": 100_000,
        "data_source": "yfinance",
    }
    row.update(overrides)
    return await _insert(conn, "backtest_runs", row)


async def _walkforward(conn: asyncpg.Connection, **overrides: Any) -> asyncpg.Record:
    row: dict[str, Any] = {
        "id": uuid.uuid4(),
        "strategy_name": "buy_and_hold",
        "params": {"symbols": ["SPY"]},
        "start_session": date(2015, 1, 2),
        "end_session": date(2019, 12, 31),
        "train_months": 36,
        "test_months": 12,
        "data_source": "yfinance",
    }
    row.update(overrides)
    return await _insert(conn, "walkforward_runs", row)


async def _run(conn: asyncpg.Connection, table: str, **overrides: Any):
    if table == "backtest_runs":
        return await _backtest(conn, **overrides)
    return await _walkforward(conn, **overrides)


# ---------------------------------------------------------------------------
# The ledger is append-only, loudly
# ---------------------------------------------------------------------------


async def _seed_request(conn: asyncpg.Connection) -> tuple[str, list[Any]]:
    row = await _insert(conn, "jev_requests", _request_row())
    return "id = $1", [row["id"]]


async def _seed_answer(conn: asyncpg.Connection) -> tuple[str, list[Any]]:
    return "id = $1", [(await _answer(conn))["id"]]


async def _seed_signal(conn: asyncpg.Connection) -> tuple[str, list[Any]]:
    row = await _insert(conn, "jev_signals", await _signal_row(conn))
    return "signal = $1 AND symbol = $2 AND session = $3", [
        row["signal"],
        row["symbol"],
        row["session"],
    ]


async def _seed_label(conn: asyncpg.Connection) -> tuple[str, list[Any]]:
    return "id = $1", [(await _insert(conn, "jev_labels", _label_row()))["id"]]


async def _seed_evaluation(conn: asyncpg.Connection) -> tuple[str, list[Any]]:
    row = await _insert(conn, "jev_evaluations", _evaluation_row())
    return "id = $1", [row["id"]]


async def _seed_document(conn: asyncpg.Connection) -> tuple[str, list[Any]]:
    return "id = $1", [(await _insert(conn, "web_documents", _document_row()))["id"]]


SEEDERS = {
    "jev_requests": _seed_request,
    "jev_answers": _seed_answer,
    "jev_signals": _seed_signal,
    "jev_labels": _seed_label,
    "jev_evaluations": _seed_evaluation,
    "web_documents": _seed_document,
}

#: The ledger proper: every row frozen as written.
LEDGER = ("jev_requests", "jev_answers", "jev_signals", "jev_labels", "jev_evaluations")

#: For each ledger table, the edit someone would actually want to make, and the
#: column a do-nothing UPDATE touches.
EDITS = {
    # Relabel a failed call as a success, or the reverse.
    "jev_requests": ("status", "'invalid'"),
    # Change what the model said.
    "jev_answers": ("choice", "'risk_off'"),
    # Move the cutoff past the stamp, so a late signal reads as live.
    "jev_signals": ("decision_cutoff", "'2100-01-01T00:00:00Z'"),
    # Revise the ground truth after seeing the answers.
    "jev_labels": ("label", "'bonds'"),
    # Improve a result.
    "jev_evaluations": ("accuracy", "0.99"),
}


class TestTheLedgerIsAppendOnly:
    @pytest.mark.parametrize("table", LEDGER)
    async def test_an_edit_is_refused_and_the_row_is_unchanged(
        self, conn: asyncpg.Connection, table: str
    ) -> None:
        where, args = await SEEDERS[table](conn)
        before = await conn.fetchrow(f"SELECT * FROM {table} WHERE {where}", *args)
        column, value = EDITS[table]

        with pytest.raises(
            asyncpg.RaiseError, match=f"{table} is append-only: UPDATE is refused"
        ):
            await conn.execute(
                f"UPDATE {table} SET {column} = {value} WHERE {where}", *args
            )
        after = await conn.fetchrow(f"SELECT * FROM {table} WHERE {where}", *args)
        assert after == before

    @pytest.mark.parametrize("table", LEDGER)
    async def test_even_an_update_that_changes_nothing_is_refused(
        self, conn: asyncpg.Connection, table: str
    ) -> None:
        """Refused on the attempt, not on a diff: there is no harmless edit."""
        await SEEDERS[table](conn)
        column, _ = EDITS[table]
        with pytest.raises(asyncpg.RaiseError, match="UPDATE is refused"):
            await conn.execute(f"UPDATE {table} SET {column} = {column}")

    @pytest.mark.parametrize("table", (*LEDGER, "web_documents"))
    async def test_a_blanket_delete_is_refused_and_removes_nothing(
        self, conn: asyncpg.Connection, table: str
    ) -> None:
        await SEEDERS[table](conn)
        count = await _count(conn, table)
        assert count > 0

        with pytest.raises(
            asyncpg.RaiseError, match=f"{table} is append-only: DELETE is refused"
        ):
            await conn.execute(f"DELETE FROM {table}")
        assert await _count(conn, table) == count

    @pytest.mark.parametrize("table", (*LEDGER, "web_documents"))
    async def test_a_truncate_is_refused_and_removes_nothing(
        self, conn: asyncpg.Connection, table: str
    ) -> None:
        """
        A row trigger never sees TRUNCATE, so each table has a statement one.

        CASCADE reaches the tables that reference this one, and Postgres fires
        the named table's trigger first, so the message names the table under
        test. Without its own trigger, the refusal would come from a table
        further down and name that one instead.
        """
        await SEEDERS[table](conn)
        count = await _count(conn, table)

        with pytest.raises(
            asyncpg.RaiseError, match=f"^{table} is append-only: TRUNCATE is refused"
        ):
            await conn.execute(f"TRUNCATE {table} CASCADE")
        assert await _count(conn, table) == count


# ---------------------------------------------------------------------------
# The database's clock, not the writer's
# ---------------------------------------------------------------------------


class TestAvailabilityIsStampedByTheDatabase:
    @pytest.mark.parametrize("table", ("jev_requests", "jev_signals"))
    @pytest.mark.parametrize(
        "offered", (PAST, FUTURE, None), ids=("past", "future", "omitted")
    )
    async def test_available_at_is_the_moment_of_the_insert_whatever_is_offered(
        self, conn: asyncpg.Connection, table: str, offered: datetime | None
    ) -> None:
        row = _request_row() if table == "jev_requests" else await _signal_row(conn)
        if offered is not None:
            row["available_at"] = offered

        before = await _clock(conn)
        stored = await _insert(conn, table, row)
        after = await _clock(conn)

        assert before <= stored["available_at"] <= after

    async def test_the_stamp_is_the_insert_and_not_the_start_of_its_transaction(
        self, conn: asyncpg.Connection
    ) -> None:
        """
        ``now()`` is when the transaction began. A writer holding one open across
        a decision cutoff would date its row before the row existed, which is
        the look-ahead the stamp is there to prevent.
        """
        async with conn.transaction():
            began = await conn.fetchval("SELECT now()")
            await conn.execute("SELECT pg_sleep(0.25)")
            stored = await _insert(conn, "jev_requests", _request_row())

        assert stored["available_at"] - began >= timedelta(seconds=0.25)


class TestBackfilledIsDerivedNotWritten:
    async def test_a_signal_recorded_before_its_cutoff_is_live(
        self, conn: asyncpg.Connection
    ) -> None:
        stored = await _insert(
            conn, "jev_signals", await _signal_row(conn, decision_cutoff=FUTURE)
        )
        assert stored["backfilled"] is False

    async def test_a_late_signal_is_backfilled_whatever_date_it_offers(
        self, conn: asyncpg.Connection
    ) -> None:
        cutoff = await _clock(conn) - timedelta(hours=1)
        row = await _signal_row(conn, decision_cutoff=cutoff)
        # The date an honest-looking backfill would claim: a day before the
        # cutoff, when the decision could have used it.
        row["available_at"] = cutoff - timedelta(days=1)

        stored = await _insert(conn, "jev_signals", row)

        assert stored["available_at"] > cutoff
        assert stored["backfilled"] is True

    async def test_backfilled_cannot_be_written_by_anyone(
        self, conn: asyncpg.Connection
    ) -> None:
        row = await _signal_row(conn, decision_cutoff=PAST)
        row["backfilled"] = False
        with pytest.raises(asyncpg.GeneratedAlwaysError):
            await _insert(conn, "jev_signals", row)


# ---------------------------------------------------------------------------
# Requests: record once
# ---------------------------------------------------------------------------


class TestTheCanonicalAnswerIsRecordedOnce:
    async def test_a_second_ok_answer_to_the_same_request_is_refused(
        self, conn: asyncpg.Connection
    ) -> None:
        request_hash = _request_row()["request_hash"]
        await _insert(conn, "jev_requests", _request_row(request_hash=request_hash))

        with pytest.raises(asyncpg.UniqueViolationError) as refused:
            await _insert(conn, "jev_requests", _request_row(request_hash=request_hash))
        assert refused.value.constraint_name == jev_repo.CANONICAL_INDEX
        assert (
            await _count(conn, "jev_requests", "request_hash = $1", request_hash) == 1
        )

    async def test_the_same_request_from_another_lane_is_still_the_same_request(
        self, conn: asyncpg.Connection
    ) -> None:
        """The hash is of what was sent. Which lane sent it does not change it."""
        request_hash = _request_row()["request_hash"]
        await _insert(conn, "jev_requests", _request_row(request_hash=request_hash))
        with pytest.raises(asyncpg.UniqueViolationError):
            await _insert(
                conn,
                "jev_requests",
                _request_row(request_hash=request_hash, lane="research"),
            )

    async def test_the_probe_lane_asks_again_as_often_as_it_likes(
        self, conn: asyncpg.Connection
    ) -> None:
        request_hash = _request_row()["request_hash"]
        for _ in range(3):
            await _insert(
                conn,
                "jev_requests",
                _request_row(request_hash=request_hash, lane="probe"),
            )
        assert (
            await _count(conn, "jev_requests", "request_hash = $1", request_hash) == 3
        )

    async def test_a_probe_does_not_take_the_canonical_place(
        self, conn: asyncpg.Connection
    ) -> None:
        request_hash = _request_row()["request_hash"]
        await _insert(
            conn, "jev_requests", _request_row(request_hash=request_hash, lane="probe")
        )
        await _insert(conn, "jev_requests", _request_row(request_hash=request_hash))
        with pytest.raises(asyncpg.UniqueViolationError):
            await _insert(conn, "jev_requests", _request_row(request_hash=request_hash))

    @pytest.mark.parametrize("status", ("invalid", "error", *REFUSED))
    async def test_a_request_that_was_not_answered_does_not_block_one_that_is(
        self, conn: asyncpg.Connection, status: str
    ) -> None:
        request_hash = _request_row()["request_hash"]
        for _ in range(2):
            await _insert(
                conn,
                "jev_requests",
                _request_row(status, request_hash=request_hash),
            )
        await _insert(conn, "jev_requests", _request_row(request_hash=request_hash))
        assert (
            await _count(conn, "jev_requests", "request_hash = $1", request_hash) == 3
        )

    async def test_the_questions_are_kept_in_the_order_they_were_asked(
        self, conn: asyncpg.Connection
    ) -> None:
        """
        ``questions`` is ``json``, not ``jsonb``. Option order is inside the
        request hash; ``jsonb`` would store these options as ``neutral``,
        ``risk_on``, ``risk_off``, ``insufficient_evidence``, a request nobody
        sent.
        """
        stored = await _insert(conn, "jev_requests", _request_row())
        criteria = json.loads(stored["questions"])["regime"]["criteria"]
        assert list(criteria) == OPTIONS


class TestARowCarriesOnlyTheResponseItGot:
    @pytest.mark.parametrize("status", ("ok", "invalid"))
    @pytest.mark.parametrize(
        "overrides",
        (
            {"http_status": 503},
            {"http_status": 199},
            {"http_status": 300},
            # What a request we got wrong comes back as. It is an error of
            # ours, not an answer of Jev's that failed validation.
            {"http_status": 422},
            {"raw_body": None},
        ),
        ids=("5xx", "below-2xx", "3xx", "422", "no-body"),
    )
    async def test_a_validated_row_needs_a_2xx_and_the_body_it_was_read_from(
        self, conn: asyncpg.Connection, status: str, overrides: dict[str, Any]
    ) -> None:
        row = _request_row(status, **overrides)
        with pytest.raises(asyncpg.CheckViolationError) as refused:
            await _insert(conn, "jev_requests", row)
        assert refused.value.constraint_name == "jev_requests_validated_has_its_body"
        assert (
            await _count(conn, "jev_requests", "request_hash = $1", row["request_hash"])
            == 0
        )

    @pytest.mark.parametrize("status", ("ok", "invalid"))
    async def test_a_validated_row_with_no_status_at_all_is_refused(
        self, conn: asyncpg.Connection, status: str
    ) -> None:
        """
        The case a plain ``BETWEEN`` would admit, because a CHECK that evaluates
        to NULL passes. Two rules refuse it independently — the validated-row
        rule says IS NOT NULL, and a body with no response is refused outright —
        and Postgres reports whichever it evaluates first, so either name is
        right. Each is enough on its own, which is the point of having both:
        this case survives relaxing either one, and fails only when both go.
        """
        row = _request_row(status, http_status=None)
        with pytest.raises(asyncpg.CheckViolationError) as refused:
            await _insert(conn, "jev_requests", row)
        assert refused.value.constraint_name in {
            "jev_requests_validated_has_its_body",
            "jev_requests_evidence_needs_a_response",
        }

    @pytest.mark.parametrize("status", ("ok", "invalid"))
    @pytest.mark.parametrize("http_status", (200, 299))
    async def test_every_2xx_is_a_status_a_validated_row_may_carry(
        self, conn: asyncpg.Connection, status: str, http_status: int
    ) -> None:
        stored = await _insert(
            conn, "jev_requests", _request_row(status, http_status=http_status)
        )
        assert (stored["status"], stored["http_status"]) == (status, http_status)

    @pytest.mark.parametrize(
        "answered_by", ("jev-1.14.0", None), ids=("another-model", "unnamed")
    )
    async def test_an_ok_row_was_answered_by_the_model_it_asked(
        self, conn: asyncpg.Connection, answered_by: str | None
    ) -> None:
        """
        A replay would present this row as the pinned model's answer. The
        response names its model and can name another one (fact 3).
        """
        row = _request_row(model_answered=answered_by)
        with pytest.raises(asyncpg.CheckViolationError) as refused:
            await _insert(conn, "jev_requests", row)
        assert refused.value.constraint_name == "jev_requests_ok_is_the_model_asked"

    async def test_an_answer_from_another_model_is_recorded_as_invalid(
        self, conn: asyncpg.Connection
    ) -> None:
        """Refused as canonical, kept as evidence of what the vendor did."""
        stored = await _insert(
            conn,
            "jev_requests",
            _request_row("invalid", model_answered="jev-1.14.0"),
        )
        assert (stored["model_requested"], stored["model_answered"]) == (
            MODEL,
            "jev-1.14.0",
        )

    @pytest.mark.parametrize("status", REFUSED)
    async def test_a_refused_request_got_no_response(
        self, conn: asyncpg.Connection, status: str
    ) -> None:
        """A call recorded as refused would be a call the daily budget never saw."""
        with pytest.raises(asyncpg.CheckViolationError) as refused:
            await _insert(conn, "jev_requests", _request_row(status, http_status=200))
        assert refused.value.constraint_name == "jev_requests_refused_got_no_response"

    @pytest.mark.parametrize("status", ("error", *REFUSED))
    @pytest.mark.parametrize(
        "evidence",
        (
            {"raw_body": "Connection reset by peer"},
            {"vendor_request_id": "req_1"},
            {"model_answered": MODEL},
        ),
        ids=("body", "request-id", "model"),
    )
    async def test_nothing_a_response_carries_is_stored_without_one(
        self, conn: asyncpg.Connection, status: str, evidence: dict[str, Any]
    ) -> None:
        """
        With no response, a body could only be text this system wrote, such as
        an exception message, where SDK releases before 0.7.1 echoed the key.
        """
        with pytest.raises(asyncpg.CheckViolationError) as refused:
            await _insert(conn, "jev_requests", _request_row(status, **evidence))
        assert refused.value.constraint_name == "jev_requests_evidence_needs_a_response"

    async def test_an_error_that_had_a_response_keeps_all_of_it(
        self, conn: asyncpg.Connection
    ) -> None:
        """The 403 whose body is not JSON: stored verbatim, status beside it."""
        stored = await _insert(
            conn,
            "jev_requests",
            _request_row(
                "error",
                http_status=403,
                raw_body="<html><body>Request blocked.</body></html>",
                error_class="TypeSafePermissionDeniedError",
                error_kind="content_block",
            ),
        )
        assert (stored["http_status"], stored["vendor_request_id"]) == (403, None)
        assert stored["raw_body"] == "<html><body>Request blocked.</body></html>"

    async def test_an_error_with_no_response_records_the_attempt(
        self, conn: asyncpg.Connection
    ) -> None:
        stored = await _insert(conn, "jev_requests", _request_row("error"))
        assert (stored["http_status"], stored["raw_body"]) == (None, None)
        assert stored["error_kind"] == "connection"

    @pytest.mark.parametrize(
        ("column", "value", "constraint"),
        (
            ("lane", "trading", "jev_requests_lane_check"),
            ("provenance", "model", "jev_requests_provenance_check"),
            ("status", "maybe", "jev_requests_status_check"),
        ),
    )
    async def test_the_vocabularies_are_closed(
        self, conn: asyncpg.Connection, column: str, value: str, constraint: str
    ) -> None:
        with pytest.raises(asyncpg.CheckViolationError) as refused:
            await _insert(conn, "jev_requests", _request_row(**{column: value}))
        assert refused.value.constraint_name == constraint


# ---------------------------------------------------------------------------
# Answers
# ---------------------------------------------------------------------------


class TestAnswers:
    async def test_a_noul_carries_no_confidence(self, conn: asyncpg.Connection) -> None:
        """Jev's Noul has no confidence field. A number here was never sent."""
        request = await _insert(conn, "jev_requests", _request_row())
        with pytest.raises(asyncpg.CheckViolationError) as refused:
            await _insert(
                conn,
                "jev_answers",
                _answer_row(
                    request["id"],
                    question_key="in_scope",
                    question_type="noul",
                    noul=0.83,
                    choice=None,
                    probabilities=None,
                    confidence=0.66,
                    argmax="true",
                    margin=0.66,
                ),
            )
        assert refused.value.constraint_name == "jev_answers_noul_has_no_confidence"

    async def test_a_noul_without_one_is_recorded(
        self, conn: asyncpg.Connection
    ) -> None:
        request = await _insert(conn, "jev_requests", _request_row())
        stored = await _insert(
            conn,
            "jev_answers",
            _answer_row(
                request["id"],
                question_key="in_scope",
                question_type="noul",
                noul=0.83,
                choice=None,
                probabilities=None,
                confidence=None,
                argmax="true",
                margin=0.66,
            ),
        )
        assert stored["confidence"] is None

    @pytest.mark.parametrize(
        "reason", (None, "", "   "), ids=("none", "empty", "blank")
    )
    async def test_an_invalid_answer_says_why(
        self, conn: asyncpg.Connection, reason: str | None
    ) -> None:
        request = await _insert(conn, "jev_requests", _request_row())
        with pytest.raises(asyncpg.CheckViolationError) as refused:
            await _insert(
                conn,
                "jev_answers",
                _answer_row(request["id"], valid=False, invalid_reason=reason),
            )
        assert refused.value.constraint_name == "jev_answers_invalid_says_why"

    async def test_an_invalid_answer_with_its_reason_is_recorded(
        self, conn: asyncpg.Connection
    ) -> None:
        request = await _insert(conn, "jev_requests", _request_row())
        stored = await _insert(
            conn,
            "jev_answers",
            _answer_row(request["id"], valid=False, invalid_reason="choice_not_argmax"),
        )
        assert (stored["valid"], stored["invalid_reason"]) == (
            False,
            "choice_not_argmax",
        )

    async def test_the_question_types_are_closed(
        self, conn: asyncpg.Connection
    ) -> None:
        # Invalid, so that the type is the only thing wrong with it: a valid
        # answer of an unknown type is also not a measurement of anything.
        request = await _insert(conn, "jev_requests", _request_row())
        with pytest.raises(asyncpg.CheckViolationError) as refused:
            await _insert(
                conn,
                "jev_answers",
                _answer_row(
                    request["id"],
                    question_type="text",
                    valid=False,
                    invalid_reason="type_mismatch",
                ),
            )
        assert refused.value.constraint_name == "jev_answers_question_type_check"

    async def test_a_question_is_answered_once_per_request(
        self, conn: asyncpg.Connection
    ) -> None:
        answer = await _answer(conn)
        with pytest.raises(asyncpg.UniqueViolationError) as refused:
            await _insert(conn, "jev_answers", _answer_row(answer["request_id"]))
        assert refused.value.constraint_name == "jev_answers_one_per_question"

    async def test_an_answer_belongs_to_a_request_that_exists(
        self, conn: asyncpg.Connection
    ) -> None:
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await _insert(conn, "jev_answers", _answer_row(-1))


class TestAValidAnswerIsAMeasurement:
    """
    Invalid answers are read as not measured; the schema holds the other side of
    that line, so a validator that regressed could not write a hollow row as
    valid.
    """

    @pytest.mark.parametrize("question_type", MEASURED)
    async def test_a_valid_answer_of_each_type_is_recorded(
        self, conn: asyncpg.Connection, question_type: str
    ) -> None:
        request = await _insert(conn, "jev_requests", _request_row())
        stored = await _insert(
            conn,
            "jev_answers",
            _answer_row(request["id"], **VALID_ANSWERS[question_type]),
        )
        assert (stored["question_type"], stored["valid"]) == (question_type, True)

    @pytest.mark.parametrize(
        ("question_type", "column"),
        [(kind, column) for kind, columns in MEASURED.items() for column in columns],
    )
    async def test_a_valid_answer_without_what_it_measured_is_refused(
        self, conn: asyncpg.Connection, question_type: str, column: str
    ) -> None:
        request = await _insert(conn, "jev_requests", _request_row())
        row = _answer_row(
            request["id"], **{**VALID_ANSWERS[question_type], column: None}
        )
        with pytest.raises(asyncpg.CheckViolationError) as refused:
            await _insert(conn, "jev_answers", row)
        expected = {"jev_answers_valid_is_measured"}
        if question_type == "choice" and column in ("choice", "argmax"):
            # A Choice with one side missing is also not its own argmax, and
            # Postgres names whichever rule it evaluates first.
            expected.add("jev_answers_valid_choice_is_its_argmax")
        assert refused.value.constraint_name in expected

    @pytest.mark.parametrize("question_type", MEASURED)
    async def test_an_invalid_answer_may_carry_nothing_but_its_reason(
        self, conn: asyncpg.Connection, question_type: str
    ) -> None:
        """An asked question the response left out: recorded, and not measured."""
        request = await _insert(conn, "jev_requests", _request_row())
        hollow = dict.fromkeys(MEASURED[question_type])
        stored = await _insert(
            conn,
            "jev_answers",
            _answer_row(
                request["id"],
                **{**VALID_ANSWERS[question_type], **hollow},
                valid=False,
                invalid_reason="missing",
            ),
        )
        assert {column: stored[column] for column in hollow} == hollow
        assert (stored["valid"], stored["invalid_reason"]) == (False, "missing")

    async def test_a_valid_answer_carries_no_reason(
        self, conn: asyncpg.Connection
    ) -> None:
        request = await _insert(conn, "jev_requests", _request_row())
        with pytest.raises(asyncpg.CheckViolationError) as refused:
            await _insert(
                conn,
                "jev_answers",
                _answer_row(request["id"], invalid_reason="near a tie"),
            )
        assert refused.value.constraint_name == "jev_answers_reason_means_invalid"

    async def test_a_valid_choice_is_its_own_argmax(
        self, conn: asyncpg.Connection
    ) -> None:
        """
        SDK issue #15: on ``jev-1.13.0`` the vendor's ``choice`` is sometimes
        0.01 below another option. Here it names ``neutral`` at 0.21 while
        ``risk_on`` holds 0.62.
        """
        request = await _insert(conn, "jev_requests", _request_row())
        with pytest.raises(asyncpg.CheckViolationError) as refused:
            await _insert(
                conn, "jev_answers", _answer_row(request["id"], choice="neutral")
            )
        assert refused.value.constraint_name == "jev_answers_valid_choice_is_its_argmax"

    async def test_the_vendors_choice_is_kept_on_the_answer_it_invalidated(
        self, conn: asyncpg.Connection
    ) -> None:
        request = await _insert(conn, "jev_requests", _request_row())
        stored = await _insert(
            conn,
            "jev_answers",
            _answer_row(
                request["id"],
                choice="neutral",
                valid=False,
                invalid_reason="choice_not_argmax",
            ),
        )
        assert (stored["choice"], stored["argmax"], stored["valid"]) == (
            "neutral",
            "risk_on",
            False,
        )


# ---------------------------------------------------------------------------
# Web documents: one way, with a reason
# ---------------------------------------------------------------------------


class TestQuarantineIsOneWay:
    async def test_a_document_starts_unquarantined(
        self, conn: asyncpg.Connection
    ) -> None:
        stored = await _insert(conn, "web_documents", _document_row())
        assert (stored["quarantined"], stored["quarantine_reason"]) == (False, None)

    async def test_it_can_be_quarantined_with_a_reason(
        self, conn: asyncpg.Connection
    ) -> None:
        stored = await _insert(conn, "web_documents", _document_row())
        await conn.execute(
            "UPDATE web_documents SET quarantined = TRUE, "
            "quarantine_reason = 'guardrail.injection v1: 0.97' WHERE id = $1",
            stored["id"],
        )
        after = await conn.fetchrow(
            "SELECT * FROM web_documents WHERE id = $1", stored["id"]
        )
        assert (after["quarantined"], after["quarantine_reason"]) == (
            True,
            "guardrail.injection v1: 0.97",
        )
        assert {k: v for k, v in after.items() if not k.startswith("quarantine")} == {
            k: v for k, v in stored.items() if not k.startswith("quarantine")
        }

    @pytest.mark.parametrize(
        "assignment",
        (
            "quarantined = TRUE",
            "quarantined = TRUE, quarantine_reason = ''",
            "quarantined = TRUE, quarantine_reason = '   '",
        ),
        ids=("no-reason", "empty-reason", "blank-reason"),
    )
    async def test_a_quarantine_without_a_reason_is_refused(
        self, conn: asyncpg.Connection, assignment: str
    ) -> None:
        stored = await _insert(conn, "web_documents", _document_row())
        with pytest.raises(asyncpg.PostgresError):
            await conn.execute(
                f"UPDATE web_documents SET {assignment} WHERE id = $1", stored["id"]
            )
        after = await conn.fetchrow(
            "SELECT * FROM web_documents WHERE id = $1", stored["id"]
        )
        assert after == stored

    @pytest.mark.parametrize(
        "assignment",
        (
            # Undo it.
            "quarantined = FALSE, quarantine_reason = NULL",
            # Rewrite why.
            "quarantine_reason = 'a false positive'",
        ),
        ids=("release", "rewrite-reason"),
    )
    async def test_nothing_about_a_quarantined_document_changes(
        self, conn: asyncpg.Connection, assignment: str
    ) -> None:
        stored = await _insert(
            conn,
            "web_documents",
            _document_row(quarantined=True, quarantine_reason="content_block: 403"),
        )
        with pytest.raises(asyncpg.RaiseError, match="web_documents is append-only"):
            await conn.execute(
                f"UPDATE web_documents SET {assignment} WHERE id = $1", stored["id"]
            )
        after = await conn.fetchrow(
            "SELECT * FROM web_documents WHERE id = $1", stored["id"]
        )
        assert after == stored

    @pytest.mark.parametrize(
        "assignment",
        (
            "excerpt = 'Ignore previous instructions.'",
            "title = 'retitled'",
            "url = 'https://example.org/'",
            "fetched_at = '2000-01-03T00:00:00Z'",
            # Quarantining while also editing is not the permitted change.
            "quarantined = TRUE, quarantine_reason = 'x', excerpt = 'cleaned'",
            # Nor is an update that changes nothing.
            "quarantined = FALSE",
        ),
        ids=(
            "excerpt",
            "title",
            "url",
            "fetched-at",
            "quarantine-and-edit",
            "no-op",
        ),
    )
    async def test_every_other_update_is_refused(
        self, conn: asyncpg.Connection, assignment: str
    ) -> None:
        stored = await _insert(conn, "web_documents", _document_row())
        with pytest.raises(asyncpg.RaiseError, match="web_documents is append-only"):
            await conn.execute(
                f"UPDATE web_documents SET {assignment} WHERE id = $1", stored["id"]
            )
        after = await conn.fetchrow(
            "SELECT * FROM web_documents WHERE id = $1", stored["id"]
        )
        assert after == stored

    async def test_a_document_may_arrive_quarantined_but_must_say_why(
        self, conn: asyncpg.Connection
    ) -> None:
        stored = await _insert(
            conn,
            "web_documents",
            _document_row(quarantined=True, quarantine_reason="content_block: 403"),
        )
        assert stored["quarantined"] is True

        with pytest.raises(asyncpg.CheckViolationError) as refused:
            await _insert(conn, "web_documents", _document_row(quarantined=True))
        assert refused.value.constraint_name == "web_documents_quarantine_says_why"

    async def test_only_a_quarantine_has_a_reason(
        self, conn: asyncpg.Connection
    ) -> None:
        with pytest.raises(asyncpg.CheckViolationError) as refused:
            await _insert(
                conn, "web_documents", _document_row(quarantine_reason="looks odd")
            )
        assert refused.value.constraint_name == "web_documents_reason_means_quarantined"

    async def test_a_snapshot_is_stored_once_per_source(
        self, conn: asyncpg.Connection
    ) -> None:
        stored = await _insert(conn, "web_documents", _document_row())
        with pytest.raises(asyncpg.UniqueViolationError):
            await _insert(
                conn,
                "web_documents",
                _document_row(content_sha256=stored["content_sha256"]),
            )
        # The same content from another source is another snapshot.
        await _insert(
            conn,
            "web_documents",
            _document_row(source="pwb_readme", content_sha256=stored["content_sha256"]),
        )


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------


class TestSignals:
    @pytest.mark.parametrize(
        "missing", ({"value": None}, {"answer_id": None}), ids=("value", "answer")
    )
    async def test_a_measured_signal_carries_its_value_and_its_answer(
        self, conn: asyncpg.Connection, missing: dict[str, Any]
    ) -> None:
        with pytest.raises(asyncpg.CheckViolationError) as refused:
            await _insert(conn, "jev_signals", await _signal_row(conn, **missing))
        assert refused.value.constraint_name == "jev_signals_measured_has_its_answer"

    @pytest.mark.parametrize("status", ("abstain", "invalid", "missing"))
    async def test_the_other_statuses_are_why_there_is_no_value(
        self, conn: asyncpg.Connection, status: str
    ) -> None:
        stored = await _insert(
            conn,
            "jev_signals",
            await _signal_row(conn, status=status, value=None, answer_id=None),
        )
        assert (stored["status"], stored["value"]) == (status, None)

    @pytest.mark.parametrize(
        ("column", "value", "constraint"),
        (
            ("status", "guessed", "jev_signals_status_check"),
            ("lane", "Decision", "jev_signals_lane_check"),
            ("provenance", "internet", "jev_signals_provenance_check"),
        ),
    )
    async def test_the_vocabularies_are_closed(
        self, conn: asyncpg.Connection, column: str, value: str, constraint: str
    ) -> None:
        # No answer, so the origin check has nothing to compare and the
        # vocabulary is all that stands in the way. With an answer, a lane or
        # provenance that is not the request's is refused before this.
        row = await _signal_row(conn, status="missing", value=None, answer_id=None)
        row[column] = value
        with pytest.raises(asyncpg.CheckViolationError) as refused:
            await _insert(conn, "jev_signals", row)
        assert refused.value.constraint_name == constraint

    async def test_one_signal_per_symbol_per_session(
        self, conn: asyncpg.Connection
    ) -> None:
        stored = await _insert(conn, "jev_signals", await _signal_row(conn))
        with pytest.raises(asyncpg.UniqueViolationError):
            await _insert(
                conn, "jev_signals", await _signal_row(conn, signal=stored["signal"])
            )


class TestASignalRestsOnItsAnswer:
    """
    The loader phase F builds will trust ``lane`` and ``provenance`` on this
    table. Were they the writer's to claim, a web-provenance answer could be
    written as an internal one and reach a decision: the prompt-injection route
    the loader's filter exists to close.
    """

    async def test_a_valid_answer_to_a_canonical_request_is_a_measurement(
        self, conn: asyncpg.Connection
    ) -> None:
        request, answer = await _exchange(conn)
        stored = await _insert(conn, "jev_signals", _signal_for(request, answer))
        assert (stored["status"], stored["value"], stored["answer_id"]) == (
            "measured",
            "risk_on",
            answer["id"],
        )

    @pytest.mark.parametrize("status", ("measured", "abstain"))
    @pytest.mark.parametrize(
        ("asked", "claimed"),
        (
            ({"provenance": "web"}, {"provenance": "internal"}),
            ({"lane": "signals"}, {"lane": "decision"}),
            ({}, {"pack_hash": "8" * 64}),
        ),
        ids=("web-claims-internal", "signals-claims-decision", "another-pack"),
    )
    async def test_its_origin_is_its_requests_and_not_the_writers_claim(
        self,
        conn: asyncpg.Connection,
        status: str,
        asked: dict[str, Any],
        claimed: dict[str, Any],
    ) -> None:
        request, answer = await _exchange(conn, request=asked)
        row = _signal_for(request, answer, status=status, **claimed)
        with pytest.raises(
            asyncpg.RaiseError, match="carries the lane, provenance and pack"
        ):
            await _insert(conn, "jev_signals", row)
        assert await _count(conn, "jev_signals", "signal = $1", row["signal"]) == 0

    @pytest.mark.parametrize(
        ("asked", "answered", "claimed"),
        (
            (
                {},
                {"choice": "neutral", "valid": False, "invalid_reason": "x"},
                {},
            ),
            ({"status": "invalid"}, {}, {}),
            ({"lane": "probe"}, {}, {}),
            ({}, {}, {"model": "jev-1.12.0"}),
        ),
        ids=("invalid-answer", "request-not-ok", "probe", "another-model"),
    )
    async def test_nothing_else_is_a_measurement(
        self,
        conn: asyncpg.Connection,
        asked: dict[str, Any],
        answered: dict[str, Any],
        claimed: dict[str, Any],
    ) -> None:
        """
        An invalid answer is not measured, a request that was not ``ok`` is not
        the canonical record, a probe is never canonical, and a signal naming a
        model other than the one that answered describes an answer nobody gave.
        """
        request, answer = await _exchange(conn, request=asked, answer=answered)
        row = _signal_for(request, answer, **claimed)
        with pytest.raises(
            asyncpg.RaiseError, match="only a valid answer to a canonical request"
        ):
            await _insert(conn, "jev_signals", row)
        assert await _count(conn, "jev_signals", "signal = $1", row["signal"]) == 0

    async def test_an_answer_that_is_not_a_measurement_is_recorded_as_one_not_made(
        self, conn: asyncpg.Connection
    ) -> None:
        request, answer = await _exchange(
            conn,
            answer={
                "argmax": None,
                "margin": 0.0,
                "valid": False,
                "invalid_reason": "tie",
            },
        )
        stored = await _insert(
            conn,
            "jev_signals",
            _signal_for(request, answer, status="invalid", value=None),
        )
        assert (stored["status"], stored["value"], stored["answer_id"]) == (
            "invalid",
            None,
            answer["id"],
        )


# ---------------------------------------------------------------------------
# Labels and evaluations
# ---------------------------------------------------------------------------


class TestLabels:
    @pytest.mark.parametrize(
        "labelled_by", ("operator:quentin", "source:pwb-readme@3f2a9c1")
    )
    async def test_a_person_or_a_dataset_at_a_hash_may_label(
        self, conn: asyncpg.Connection, labelled_by: str
    ) -> None:
        stored = await _insert(conn, "jev_labels", _label_row(labelled_by=labelled_by))
        assert stored["labelled_by"] == labelled_by
        assert stored["labelled_at"] is not None

    @pytest.mark.parametrize(
        "labelled_by",
        (
            "jev:research.catalogue",
            "programme:data_engineering",
            "model:jev-1.13.0",
            "Operator:quentin",
            "operator:",
            "source:pwb-readme",
            "source:@",
            "source:pwb-readme@",
            "source:@3f2a9c1",
            "",
        ),
    )
    async def test_nothing_else_may(
        self, conn: asyncpg.Connection, labelled_by: str
    ) -> None:
        with pytest.raises(asyncpg.CheckViolationError) as refused:
            await _insert(conn, "jev_labels", _label_row(labelled_by=labelled_by))
        assert refused.value.constraint_name == "jev_labels_by_a_person_or_a_dataset"

    async def test_a_labeller_labels_an_item_once_and_another_may_disagree(
        self, conn: asyncpg.Connection
    ) -> None:
        first = await _insert(conn, "jev_labels", _label_row())
        with pytest.raises(asyncpg.UniqueViolationError) as refused:
            await _insert(
                conn,
                "jev_labels",
                _label_row(subject_id=first["subject_id"], label="bonds"),
            )
        assert refused.value.constraint_name == "jev_labels_once_per_labeller"

        second = await _insert(
            conn,
            "jev_labels",
            _label_row(
                subject_id=first["subject_id"],
                label="bonds",
                labelled_by="operator:reviewer",
            ),
        )
        assert (first["label"], second["label"]) == ("equities", "bonds")


#: Every measurement column of jev_evaluations: nullable, and NULL until measured.
MEASUREMENTS = (
    "accuracy",
    "accuracy_wilson_low",
    "accuracy_wilson_high",
    "balanced_accuracy",
    "brier",
    "brier_ci_low",
    "brier_ci_high",
    "threshold",
    "coverage_at_threshold",
    "majority_baseline_accuracy",
    "keyword_baseline_accuracy",
    "flip_rate",
    "calibration_bins",
)


class TestEvaluations:
    async def test_what_was_not_measured_is_null_and_never_zero(
        self, conn: asyncpg.Connection
    ) -> None:
        stored = await _insert(conn, "jev_evaluations", _evaluation_row())
        assert {column: stored[column] for column in MEASUREMENTS} == dict.fromkeys(
            MEASUREMENTS
        )

    async def test_a_genuine_zero_is_kept_as_one(
        self, conn: asyncpg.Connection
    ) -> None:
        stored = await _insert(
            conn, "jev_evaluations", _evaluation_row(flip_rate=0.0, accuracy=0.0)
        )
        assert (stored["flip_rate"], stored["accuracy"]) == (0.0, 0.0)

    async def test_whether_the_model_may_have_seen_the_data_must_be_stated(
        self, conn: asyncpg.Connection
    ) -> None:
        row = _evaluation_row()
        del row["possibly_in_training"]
        with pytest.raises(asyncpg.NotNullViolationError):
            await _insert(conn, "jev_evaluations", row)

    async def test_a_count_cannot_be_negative(self, conn: asyncpg.Connection) -> None:
        with pytest.raises(asyncpg.CheckViolationError) as refused:
            await _insert(conn, "jev_evaluations", _evaluation_row(n=-1))
        assert refused.value.constraint_name == "jev_evaluations_n_check"


# ---------------------------------------------------------------------------
# Changes to existing tables
# ---------------------------------------------------------------------------


class TestModelSignalEvidenceIsSticky:
    async def test_a_candidate_starts_without_it(
        self, conn: asyncpg.Connection
    ) -> None:
        candidate = await _candidate(conn)
        assert candidate["evidence_uses_model_signals"] is False

    async def test_once_set_it_cannot_be_cleared(
        self, conn: asyncpg.Connection
    ) -> None:
        candidate = await _candidate(conn)
        await conn.execute(
            "UPDATE candidates SET evidence_uses_model_signals = TRUE WHERE id = $1",
            candidate["id"],
        )
        with pytest.raises(
            asyncpg.RaiseError, match="evidence_uses_model_signals cannot be cleared"
        ):
            await conn.execute(
                "UPDATE candidates SET evidence_uses_model_signals = FALSE "
                "WHERE id = $1",
                candidate["id"],
            )
        assert await conn.fetchval(
            "SELECT evidence_uses_model_signals FROM candidates WHERE id = $1",
            candidate["id"],
        )

    async def test_the_rest_of_the_candidate_still_moves(
        self, conn: asyncpg.Connection
    ) -> None:
        """Sticky is not frozen: a contaminated candidate can still be rejected."""
        candidate = await _candidate(conn)
        await conn.execute(
            "UPDATE candidates SET evidence_uses_model_signals = TRUE WHERE id = $1",
            candidate["id"],
        )
        await conn.execute(
            "UPDATE candidates SET status = 'rejected', "
            "evidence_uses_model_signals = TRUE WHERE id = $1",
            candidate["id"],
        )
        after = await conn.fetchrow(
            "SELECT status, evidence_uses_model_signals FROM candidates WHERE id = $1",
            candidate["id"],
        )
        assert (after["status"], after["evidence_uses_model_signals"]) == (
            "rejected",
            True,
        )


class TestAForwardExperimentIsPaperAndNeverTheOperatorsBook:
    async def test_every_deployment_is_walkforward_unless_it_says_otherwise(
        self, conn: asyncpg.Connection
    ) -> None:
        stored = await _insert(conn, "deployments", _deployment_row())
        assert stored["evidence_class"] == "walkforward"

    @pytest.mark.parametrize(
        ("mode", "owner_id"),
        (("live", "programme"), ("paper", "default"), ("live", "default")),
    )
    async def test_it_is_refused_live_or_on_default(
        self, conn: asyncpg.Connection, mode: str, owner_id: str
    ) -> None:
        with pytest.raises(asyncpg.CheckViolationError) as refused:
            await _insert(
                conn,
                "deployments",
                _deployment_row(
                    evidence_class="forward_experiment", mode=mode, owner_id=owner_id
                ),
            )
        assert (
            refused.value.constraint_name == "deployments_forward_experiment_is_paper"
        )

    async def test_it_is_allowed_on_paper_for_another_owner(
        self, conn: asyncpg.Connection
    ) -> None:
        stored = await _insert(
            conn,
            "deployments",
            _deployment_row(
                evidence_class="forward_experiment", mode="paper", owner_id="jev"
            ),
        )
        assert (stored["evidence_class"], stored["mode"], stored["owner_id"]) == (
            "forward_experiment",
            "paper",
            "jev",
        )

    @pytest.mark.parametrize(
        "assignment", ("mode = 'live'", "owner_id = 'default'"), ids=("live", "default")
    )
    async def test_an_admitted_one_cannot_be_moved_there_afterwards(
        self, conn: asyncpg.Connection, assignment: str
    ) -> None:
        stored = await _insert(
            conn,
            "deployments",
            _deployment_row(
                evidence_class="forward_experiment", mode="paper", owner_id="jev"
            ),
        )
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                f"UPDATE deployments SET {assignment} WHERE id = $1", stored["id"]
            )
        after = await conn.fetchrow(
            "SELECT * FROM deployments WHERE id = $1", stored["id"]
        )
        assert after == stored

    async def test_a_walkforward_deployment_is_unconstrained_as_before(
        self, conn: asyncpg.Connection
    ) -> None:
        """The CHECK binds forward experiments only; live stays the API's call."""
        stored = await _insert(
            conn, "deployments", _deployment_row(mode="live", owner_id="default")
        )
        assert stored["evidence_class"] == "walkforward"

    async def test_the_evidence_classes_are_closed(
        self, conn: asyncpg.Connection
    ) -> None:
        with pytest.raises(asyncpg.CheckViolationError) as refused:
            await _insert(
                conn,
                "deployments",
                _deployment_row(evidence_class="vibes", owner_id="jev"),
            )
        assert refused.value.constraint_name == "deployments_evidence_class_check"


#: The signal-provenance columns 0012 adds to both run tables.
PROVENANCE_COLUMNS = (
    "signals_live",
    "signals_backfilled_post_release",
    "signals_backfilled_pre_release",
    "signal_models",
    "signal_pack_hashes",
)
WHOLE_PROVENANCE = {
    "signals_live": 180,
    "signals_backfilled_post_release": 12,
    "signals_backfilled_pre_release": 0,
    "signal_models": [MODEL],
    "signal_pack_hashes": ["9" * 64],
}


class TestRunsRecordTheSignalsTheyUsed:
    @pytest.mark.parametrize("table", ("backtest_runs", "walkforward_runs"))
    async def test_a_run_that_used_no_model_signal_says_nothing(
        self, conn: asyncpg.Connection, table: str
    ) -> None:
        stored = await _run(conn, table)
        assert {column: stored[column] for column in PROVENANCE_COLUMNS} == (
            dict.fromkeys(PROVENANCE_COLUMNS)
        )

    @pytest.mark.parametrize("table", ("backtest_runs", "walkforward_runs"))
    async def test_a_run_that_used_them_says_everything(
        self, conn: asyncpg.Connection, table: str
    ) -> None:
        stored = await _run(conn, table, **WHOLE_PROVENANCE)
        assert {column: stored[column] for column in PROVENANCE_COLUMNS} == (
            WHOLE_PROVENANCE
        )

    @pytest.mark.parametrize("table", ("backtest_runs", "walkforward_runs"))
    @pytest.mark.parametrize("left_out", PROVENANCE_COLUMNS)
    async def test_half_a_provenance_is_refused(
        self, conn: asyncpg.Connection, table: str, left_out: str
    ) -> None:
        partial = {k: v for k, v in WHOLE_PROVENANCE.items() if k != left_out}
        with pytest.raises(asyncpg.CheckViolationError) as refused:
            await _run(conn, table, **partial)
        assert refused.value.constraint_name == f"{table}_signal_provenance_whole"

    @pytest.mark.parametrize("table", ("backtest_runs", "walkforward_runs"))
    async def test_a_count_cannot_be_negative(
        self, conn: asyncpg.Connection, table: str
    ) -> None:
        with pytest.raises(asyncpg.CheckViolationError) as refused:
            await _run(conn, table, **{**WHOLE_PROVENANCE, "signals_live": -1})
        assert refused.value.constraint_name == f"{table}_signal_counts_non_negative"


# ---------------------------------------------------------------------------
# The switches
# ---------------------------------------------------------------------------


async def _switches(conn: asyncpg.Connection) -> dict[str, tuple[Any, str]]:
    rows = await conn.fetch(
        "SELECT key, value, updated_by FROM system_flags WHERE key LIKE 'jev%'"
    )
    return {r["key"]: (json.loads(r["value"]), r["updated_by"]) for r in rows}


class TestTheSwitchesAreSeededOff:
    async def test_every_switch_is_seeded_as_the_design_says(
        self, conn: asyncpg.Connection
    ) -> None:
        """
        Compared as JSON, so a string ``"false"`` or an integer 0 is a failure: a
        reader that wants JSON ``true`` would read either as off today, and the
        seed would be right only by accident.
        """
        switches = await _switches(conn)
        assert {key: value for key, (value, _) in switches.items()} == SEEDED_SWITCHES
        for key, (value, _) in switches.items():
            assert type(value) is type(SEEDED_SWITCHES[key]), key
        assert {by for _, by in switches.values()} == {"migration"}

    async def test_they_read_as_off_through_the_shipped_readers(
        self, conn: asyncpg.Connection
    ) -> None:
        """
        The seed and the readers agree. A seed the readers could not parse would
        also read as off, so this pins the values that are not a switch: a
        budget the reader turned into 0 would mean no call ever, silently.
        """
        from src.programme import flags

        readers = (
            "jev_enabled",
            "jev_area_enabled",
            "jev_model",
            "jev_daily_request_budget",
            "jev_max_state_tokens",
            "jev_send_internal_detail",
        )
        if not all(hasattr(flags, name) for name in readers):
            pytest.skip("the Jev readers are not in src/programme/flags.py yet")

        assert await flags.jev_enabled(conn) is False
        for area in (
            "research",
            "ops",
            "findings",
            "guardrails",
            "signals",
            "decisions",
        ):
            assert await flags.jev_area_enabled(conn, area) is False, area
        assert await flags.jev_model(conn) == "jev-1.13.0"
        assert await flags.jev_daily_request_budget(conn) == 500
        assert await flags.jev_max_state_tokens(conn) == 8000
        assert await flags.jev_send_internal_detail(conn) is False

    async def test_the_seeded_settings_are_ones_the_catalogue_accepts(self) -> None:
        catalogue = pytest.importorskip("src.programme.jev_catalogue")
        assert catalogue.model_problem(SEEDED_SWITCHES["jev_model"]) is None
        assert SEEDED_SWITCHES["jev_model"] == catalogue.DEFAULT_MODEL
        assert (
            catalogue.settings_problem(
                SEEDED_SWITCHES["jev_model"],
                SEEDED_SWITCHES["jev_daily_request_budget"],
                SEEDED_SWITCHES["jev_max_state_tokens"],
            )
            is None
        )

    async def test_every_area_the_catalogue_names_has_a_seeded_switch(self) -> None:
        """
        An area switch that was never seeded reads as off forever, and the
        operator's control for it would write a row the migration never made.
        The first test here holds the seeded set to the database; this one holds
        it to the catalogue, which is what the readers and the form will use.
        """
        catalogue = pytest.importorskip("src.programme.jev_catalogue")
        seeded = {key for key in SEEDED_SWITCHES if key.startswith("jev_area_")}
        assert seeded == {f"jev_area_{area}" for area in catalogue.AREAS}
        gated = {area for area in catalogue.LANE_AREA.values() if area is not None}
        assert gated == set(catalogue.AREAS)


async def _vocabulary(conn: asyncpg.Connection, constraint: str) -> set[str]:
    definition = await conn.fetchval(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = $1",
        constraint,
    )
    return set(re.findall(r"'([^']+)'::text", definition))


class TestTheVocabulariesAgree:
    async def test_the_schema_holds_the_lanes_and_provenances_it_was_designed_with(
        self, conn: asyncpg.Connection
    ) -> None:
        for table in ("jev_requests", "jev_signals"):
            assert await _vocabulary(conn, f"{table}_lane_check") == set(LANES)
            assert await _vocabulary(conn, f"{table}_provenance_check") == set(
                PROVENANCES
            )

    async def test_the_catalogue_names_the_same_ones(
        self, conn: asyncpg.Connection
    ) -> None:
        """A lane the catalogue knows and the schema refuses would fail every write."""
        catalogue = pytest.importorskip("src.programme.jev_catalogue")
        assert set(catalogue.LANES) == await _vocabulary(
            conn, "jev_requests_lane_check"
        )
        assert set(catalogue.PROVENANCES) == await _vocabulary(
            conn, "jev_requests_provenance_check"
        )
        assert set(catalogue.LANE_AREA) == set(catalogue.LANES)


# ---------------------------------------------------------------------------
# The migration itself
# ---------------------------------------------------------------------------


async def _legacy_rows(conn: asyncpg.Connection) -> dict[str, Any]:
    """Rows as a database at 0011 holds them, for 0012 to adapt rather than refuse."""
    candidate = await _candidate(conn)
    backtest = await _backtest(conn)
    walkforward = await _walkforward(conn, backtest_run_id=backtest["id"])
    paper = await _insert(conn, "deployments", _deployment_row())
    live = await _insert(conn, "deployments", _deployment_row(mode="live"))
    return {
        "candidate": candidate["id"],
        "backtest": backtest["id"],
        "walkforward": walkforward["id"],
        "deployments": [paper["id"], live["id"]],
    }


class TestTheMigration:
    async def test_it_applies_on_top_of_a_database_already_at_0011(
        self, tmp_path
    ) -> None:
        """
        Production is at 0011, with rows in every table 0012 alters, so a clean
        apply to an empty database proves too little. This one is migrated to
        0011 first, given the rows, and then taken to 0012 by the shipped
        runner.
        """
        on_disk = {m.version: m for m in migrations.discover()}
        at_0011, at_0012 = tmp_path / "0011", tmp_path / "0012"
        for directory, last in ((at_0011, 11), (at_0012, 12)):
            directory.mkdir()
            for version, migration in on_disk.items():
                if version <= last:
                    shutil.copy(migration.path, directory / migration.path.name)

        dsn = await _fresh_database("jev_upgrade")
        first = await migrations.migrate(dsn, directory=at_0011)
        assert [m.version for m in first] == list(range(1, 12))

        conn = await asyncpg.connect(dsn)
        try:
            legacy = await _legacy_rows(conn)
            applied = await migrations.migrate(dsn, directory=at_0012)

            assert [str(m) for m in applied] == ["0012_jev"]
            assert (
                await conn.fetchval(
                    "SELECT checksum FROM schema_migrations WHERE version = 12"
                )
                == on_disk[12].checksum
            )
            assert await migrations.migrate(dsn, directory=at_0012) == []

            assert (
                await conn.fetchval(
                    "SELECT evidence_uses_model_signals FROM candidates WHERE id = $1",
                    legacy["candidate"],
                )
                is False
            )
            classes = await conn.fetch(
                "SELECT evidence_class FROM deployments WHERE id = ANY($1::uuid[])",
                legacy["deployments"],
            )
            assert [r["evidence_class"] for r in classes] == ["walkforward"] * 2
            for table, key in (
                ("backtest_runs", "backtest"),
                ("walkforward_runs", "walkforward"),
            ):
                row = await conn.fetchrow(
                    f"SELECT {', '.join(PROVENANCE_COLUMNS)} FROM {table} "
                    "WHERE id = $1",
                    legacy[key],
                )
                assert dict(row) == dict.fromkeys(PROVENANCE_COLUMNS), table
            assert set(await _switches(conn)) == set(SEEDED_SWITCHES)
        finally:
            await conn.close()
