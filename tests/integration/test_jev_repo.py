"""
test_jev_repo.py
----------------
``jev_repo`` against real PostgreSQL: what the lanes write, and what the
control plane reads.

The repo's promises are transactional — a request and its answers are one write
or none, a savepoint inside a caller's transaction, and the loser of a race for
the canonical row can read the winner — and a fake that rolls back proves only
the fake. So every test here drives the shipped functions against the shipped
schema.

Runs on two databases of its own, derived from ``TEST_DATABASE_URL`` the way
``test_deployment_enable_gate.py`` derives ``_enable``. It has to: the ledger
refuses DELETE and TRUNCATE, so nothing written here could be cleared from a
shared database afterwards.

* ``<name>_jev_repo``: every test runs inside a transaction that is rolled back,
  so each starts from an empty ledger and a count is a count of its own rows.
* ``<name>_jev_repo_commits``: for what can only be shown committed — a real
  transaction rather than a savepoint, and a race between two connections.

Skipped unless ``TEST_DATABASE_URL`` is set.

    TEST_DATABASE_URL=postgresql://localhost/trader_test \\
        pytest tests/integration/test_jev_repo.py
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import math
import os
import types
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

pytest.importorskip("asyncpg")

import asyncpg  # noqa: E402

from src.db import migrate as migrations  # noqa: E402
from src.db.repos import jobs as job_repo  # noqa: E402
from src.programme import jev_clock, jev_repo  # noqa: E402
from src.programme.jev_hash import text_sha256  # noqa: E402

TEST_DSN = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DSN, reason="TEST_DATABASE_URL not set; skipping Jev repo tests"
)

MODEL = "jev-1.13.0"

#: One question of each type, in an order no sort would produce, and a Choice
#: whose options ``jsonb`` would reorder (it sorts keys by length, then bytes).
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
    },
    "in_scope": {
        "type": "noul",
        "instructions": "Do these descriptors describe a listed market?",
    },
    "severity": {
        "type": "score",
        "instructions": "How far from normal are these descriptors?",
        "criteria": ["normal", "unusual", "extreme"],
    },
}
OPTIONS = list(QUESTIONS["regime"]["criteria"])

STATE = {
    "equities_trend": "above",
    "bonds_trend": "below",
    "equities": {"volatility_quintile": "2", "drawdown": "shallow"},
}

#: What the vendor answers to ``QUESTIONS``, cleanly.
BODY = json.dumps(
    {
        "model": MODEL,
        "answers": {
            "regime": {
                "type": "choice",
                "choice": "risk_on",
                "confidence": 0.49,
                "probabilities": {
                    "risk_on": 0.62,
                    "neutral": 0.21,
                    "risk_off": 0.12,
                    "insufficient_evidence": 0.05,
                },
            },
            "in_scope": {"type": "noul", "noul": 0.83},
            "severity": {
                "type": "score",
                "score": 0.4,
                "confidence": 0.55,
                "legend": {"0": "normal", "1": "unusual", "2": "extreme"},
                "probabilities": {"0": 0.7, "1": 0.2, "2": 0.1},
            },
        },
        "usage": {"input_tokens": 212, "output_tokens": 0},
    }
)

REFUSED = ("refused_budget", "refused_limits", "refused_model")

#: How the stamp is switched off for a backdated row. See ``_backdated``.
STAMP_TRIGGER = "trg_jev_requests_available_at"


@dataclasses.dataclass(frozen=True)
class Answer:
    """
    What ``record_answers`` reads, standing in for ``jev_validate``'s
    ``ValidatedAnswer`` so these tests do not depend on the validator's rules.
    ``TestTheValidatorsAnswersFitTheLedger`` holds the two to each other.
    """

    question_key: str
    question_type: str
    noul: Any = None
    choice: Any = None
    score: Any = None
    probabilities: Any = None
    confidence: Any = None
    argmax: Any = None
    margin: Any = None
    valid: bool = True
    invalid_reason: str | None = None


#: The three answers ``BODY`` validates to, in the order asked.
ANSWERS = (
    Answer(
        "regime",
        "choice",
        choice="risk_on",
        probabilities={
            "risk_on": 0.62,
            "neutral": 0.21,
            "risk_off": 0.12,
            "insufficient_evidence": 0.05,
        },
        confidence=0.49,
        argmax="risk_on",
        margin=0.41,
    ),
    Answer("in_scope", "noul", noul=0.83, argmax="true", margin=0.66),
    Answer(
        "severity",
        "score",
        score=0.4,
        probabilities={"0": 0.7, "1": 0.2, "2": 0.1},
        confidence=0.55,
        argmax="0",
        margin=0.5,
    ),
)


# ---------------------------------------------------------------------------
# Databases
# ---------------------------------------------------------------------------


def _derived(suffix: str) -> str:
    base, _, tail = TEST_DSN.partition("?")
    return f"{base}_{suffix}?{tail}" if tail else f"{base}_{suffix}"


async def _fresh_database(suffix: str) -> str:
    """An empty, migrated database named after ``TEST_DATABASE_URL``'s."""
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
    await migrations.migrate(dsn)
    return dsn


@pytest.fixture(scope="module")
def databases() -> dict[str, str]:
    async def setup() -> dict[str, str]:
        return {
            "rolled_back": await _fresh_database("jev_repo"),
            "committed": await _fresh_database("jev_repo_commits"),
        }

    return asyncio.run(setup())


@pytest.fixture
async def conn(databases: dict[str, str]):
    """A connection whose every write is rolled back when the test ends."""
    connection = await asyncpg.connect(databases["rolled_back"])
    transaction = connection.transaction()
    await transaction.start()
    try:
        yield connection
    finally:
        await transaction.rollback()
        await connection.close()


@pytest.fixture
async def committing(databases: dict[str, str]):
    """A connection with no transaction open: what it writes, it commits."""
    connection = await asyncpg.connect(databases["committed"])
    try:
        yield connection
    finally:
        await connection.close()


@pytest.fixture
async def other(databases: dict[str, str]):
    """A second connection to the committing database: another writer."""
    connection = await asyncpg.connect(databases["committed"])
    try:
        yield connection
    finally:
        await connection.close()


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


def _hash() -> str:
    return hashlib.sha256(uuid.uuid4().bytes).hexdigest()


def _fields(status: str = "ok", **overrides: Any) -> dict[str, Any]:
    """``record_request``'s arguments for a request of ``status``, as it arrives."""
    fields: dict[str, Any] = {
        "request_hash": _hash(),
        "state_hash": _hash(),
        "question_set": "decision.regime",
        "question_set_version": 1,
        "pack_hash": "9" * 64,
        "lane": "decision",
        "provenance": "internal",
        "subject_type": "session",
        "subject_id": "2026-09-25",
        "as_of": datetime(2026, 9, 25, 20, tzinfo=UTC),
        "state": STATE,
        "questions": QUESTIONS,
        "model_requested": MODEL,
        "status": status,
        "requested_at": datetime.now(UTC),
        "model_answered": MODEL,
        "vendor_request_id": f"req_{uuid.uuid4().hex[:16]}",
        "http_status": 200,
        "raw_body": BODY,
        "input_tokens": 212,
        "output_tokens": 0,
        "latency_ms": 140,
    }
    if status == "error":
        fields.update(
            model_answered=None,
            vendor_request_id=None,
            http_status=None,
            raw_body=None,
            error_class="TypeSafeAPITimeoutError",
            error_kind="timeout",
            input_tokens=None,
            output_tokens=None,
            latency_ms=20_000,
        )
    elif status in REFUSED:
        fields.update(
            model_answered=None,
            vendor_request_id=None,
            http_status=None,
            raw_body=None,
            input_tokens=None,
            output_tokens=None,
            latency_ms=None,
        )
    fields.update(overrides)
    return fields


def _invalid(answer: Answer, reason: str) -> Answer:
    return dataclasses.replace(answer, valid=False, invalid_reason=reason)


async def _record(
    conn: asyncpg.Connection,
    status: str = "ok",
    answers: tuple[Answer, ...] | None = None,
    **overrides: Any,
) -> int:
    """One exchange through the shipped writer. An ok one gets ``ANSWERS``."""
    if answers is None:
        answers = ANSWERS if status == "ok" else ()
    return await jev_repo.record_exchange(conn, _fields(status, **overrides), answers)


async def _count(conn: asyncpg.Connection, table: str, where: str, *args: Any) -> int:
    return await conn.fetchval(f"SELECT COUNT(*) FROM {table} WHERE {where}", *args)


async def _backdated(
    conn: asyncpg.Connection, available_at: datetime, status: str = "ok", **overrides
) -> int:
    """
    A request row stamped ``available_at``, as one recorded then would be.

    The stamp cannot be forged — that is its point — so the only way to hold a
    row from before midnight is to write it with the stamp switched off. The
    switch is DDL inside the test's own transaction, and goes back with it.
    """
    fields = _fields(status, **overrides)
    await conn.execute(f"ALTER TABLE jev_requests DISABLE TRIGGER {STAMP_TRIGGER}")
    try:
        return await conn.fetchval(
            """
            INSERT INTO jev_requests (
                request_hash, state_hash, question_set, question_set_version,
                pack_hash, lane, provenance, subject_type, subject_id, as_of,
                state, questions, model_requested, model_answered, http_status,
                status, raw_body, latency_ms, requested_at, available_at,
                error_class, error_kind
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb,
                    $12::json, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22)
            RETURNING id
            """,
            fields["request_hash"],
            fields["state_hash"],
            fields["question_set"],
            fields["question_set_version"],
            fields["pack_hash"],
            fields["lane"],
            fields["provenance"],
            fields["subject_type"],
            fields["subject_id"],
            fields["as_of"],
            json.dumps(fields["state"]),
            json.dumps(fields["questions"]),
            fields["model_requested"],
            fields["model_answered"],
            fields["http_status"],
            fields["status"],
            fields["raw_body"],
            fields["latency_ms"],
            fields["requested_at"],
            available_at,
            fields.get("error_class"),
            fields.get("error_kind"),
        )
    finally:
        await conn.execute(f"ALTER TABLE jev_requests ENABLE TRIGGER {STAMP_TRIGGER}")


async def _utc_midnight(conn: asyncpg.Connection) -> datetime:
    return await conn.fetchval("SELECT date_trunc('day', now(), 'UTC')")


def _canonical_hash(model: str, state: Any, questions: Any) -> str:
    """
    A request hash as the lane defines one: state keys sorted, question and
    option order kept. Not the lane's code — the property tested is only that
    what the ledger stores recomputes the hash of what was sent.
    """
    body = {
        "model": model,
        "state": json.loads(json.dumps(state, sort_keys=True)),
        "questions": questions,
    }
    text = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Writing a request
# ---------------------------------------------------------------------------


class TestRecordRequest:
    async def test_a_request_reads_back_as_it_was_written(
        self, conn: asyncpg.Connection
    ) -> None:
        fields = _fields()
        before = await conn.fetchval("SELECT clock_timestamp()")
        request_id = await jev_repo.record_request(conn, **fields)
        after = await conn.fetchval("SELECT clock_timestamp()")

        stored = await jev_repo.get_request(conn, request_id)
        assert stored is not None
        for key, value in fields.items():
            assert stored[key] == value, key
        assert before <= stored["available_at"] <= after

    async def test_the_questions_come_back_in_the_order_they_were_asked(
        self, conn: asyncpg.Connection
    ) -> None:
        request_id = await jev_repo.record_request(conn, **_fields())
        stored = await jev_repo.get_request(conn, request_id)
        assert list(stored["questions"]) == list(QUESTIONS)
        assert list(stored["questions"]["regime"]["criteria"]) == OPTIONS

    async def test_the_stored_request_recomputes_its_own_hash(
        self, conn: asyncpg.Connection
    ) -> None:
        """
        What "record once, replay forever" rests on: the row is the request.
        The control shows the check has teeth — the same questions after a trip
        through ``jsonb`` hash to something else.
        """
        sent = _canonical_hash(MODEL, STATE, QUESTIONS)
        request_id = await jev_repo.record_request(conn, **_fields(request_hash=sent))
        stored = await jev_repo.get_request(conn, request_id)

        recomputed = _canonical_hash(
            stored["model_requested"], stored["state"], stored["questions"]
        )
        assert recomputed == stored["request_hash"] == sent

        through_jsonb = json.loads(
            await conn.fetchval("SELECT $1::jsonb::text", json.dumps(QUESTIONS))
        )
        assert _canonical_hash(MODEL, STATE, through_jsonb) != sent

    async def test_available_at_is_not_the_callers_to_give(
        self, conn: asyncpg.Connection
    ) -> None:
        with pytest.raises(TypeError, match="available_at"):
            await jev_repo.record_request(
                conn, **_fields(), available_at=datetime(2000, 1, 3, tzinfo=UTC)
            )

    async def test_a_request_never_sent_is_dated_by_the_database(
        self, conn: asyncpg.Connection
    ) -> None:
        fields = _fields("refused_budget")
        del fields["requested_at"]
        request_id = await jev_repo.record_request(conn, **fields)
        stored = await jev_repo.get_request(conn, request_id)
        assert stored["requested_at"] == await conn.fetchval("SELECT now()")
        assert stored["requested_at"] <= stored["available_at"]

    async def test_a_state_sent_as_text_is_stored_as_the_text_it_was(
        self, conn: asyncpg.Connection
    ) -> None:
        """The SDK sends a string state as a JSON string, and so is it kept."""
        text = 'Job 42 failed: {"error": "timeout"}'
        request_id = await jev_repo.record_request(conn, **_fields(state=text))
        stored = await jev_repo.get_request(conn, request_id)
        assert stored["state"] == text
        assert (
            await conn.fetchval(
                "SELECT jsonb_typeof(state) FROM jev_requests WHERE id = $1", request_id
            )
            == "string"
        )

    async def test_a_read_only_mapping_is_written_as_the_object_it_holds(
        self, conn: asyncpg.Connection
    ) -> None:
        frozen = types.MappingProxyType(
            {
                key: types.MappingProxyType(dict(question))
                for key, question in QUESTIONS.items()
            }
        )
        request_id = await jev_repo.record_request(conn, **_fields(questions=frozen))
        stored = await jev_repo.get_request(conn, request_id)
        assert stored["questions"] == QUESTIONS
        assert list(stored["questions"]["regime"]["criteria"]) == OPTIONS

    @pytest.mark.parametrize("number", (math.nan, math.inf), ids=("nan", "inf"))
    async def test_a_number_json_cannot_spell_was_never_sent(
        self, conn: asyncpg.Connection, number: float
    ) -> None:
        fields = _fields(state={**STATE, "ratio": number})
        with pytest.raises(ValueError):
            await jev_repo.record_request(conn, **fields)
        assert (
            await _count(
                conn, "jev_requests", "request_hash = $1", fields["request_hash"]
            )
            == 0
        )


# ---------------------------------------------------------------------------
# Writing answers
# ---------------------------------------------------------------------------


class TestRecordAnswers:
    async def test_answers_come_back_in_the_order_asked(
        self, conn: asyncpg.Connection
    ) -> None:
        request_id = await _record(conn)
        stored = await jev_repo.answers_for(conn, request_id)

        assert [a["question_key"] for a in stored] == [a.question_key for a in ANSWERS]
        for row, answer in zip(stored, ANSWERS, strict=True):
            assert {name: row[name] for name in jev_repo.ANSWER_FIELDS} == (
                dataclasses.asdict(answer)
            )
            assert row["request_id"] == request_id

    async def test_what_the_vendor_sent_that_no_column_can_hold_is_null(
        self, conn: asyncpg.Connection
    ) -> None:
        """
        ``True`` stored as 1.0 is exactly the confusion the validator refuses,
        and a NaN is not a number anything downstream may compare. The verbatim
        body keeps what was actually sent.
        """
        answers = (
            Answer("in_scope", "noul", noul=True, valid=False, invalid_reason="bool"),
            Answer(
                "severity",
                "score",
                score=math.inf,
                confidence=math.nan,
                margin=math.nan,
                probabilities={"0": math.nan, "1": math.inf, "2": -math.inf},
                valid=False,
                invalid_reason="not_finite",
            ),
            Answer(
                "regime",
                "choice",
                choice=3,
                confidence="0.5",
                valid=False,
                invalid_reason="type_mismatch",
            ),
        )
        request_id = await _record(conn, "invalid", answers)
        stored = {
            a["question_key"]: a for a in await jev_repo.answers_for(conn, request_id)
        }

        assert stored["in_scope"]["noul"] is None
        assert (
            stored["severity"]["score"],
            stored["severity"]["confidence"],
            stored["severity"]["margin"],
        ) == (None, None, None)
        assert stored["severity"]["probabilities"] == {
            "0": "NaN",
            "1": "Infinity",
            "2": "-Infinity",
        }
        assert (stored["regime"]["choice"], stored["regime"]["confidence"]) == (
            None,
            None,
        )

    async def test_a_genuine_zero_is_kept_as_one(
        self, conn: asyncpg.Connection
    ) -> None:
        answers = (Answer("in_scope", "noul", noul=0.0, argmax="false", margin=1.0),)
        request_id = await _record(conn, answers=answers)
        (noul,) = await jev_repo.answers_for(conn, request_id)
        assert noul["noul"] == 0.0
        assert noul["noul"] is not None

    async def test_a_wrong_type_from_this_system_is_an_error_not_a_null(
        self, conn: asyncpg.Connection
    ) -> None:
        """
        The argmax is ours. A score level computed as the integer 2 rather than
        the key ``"2"`` is a bug in this system, and a NULL would hide it.
        """
        fields = _fields()
        answers = (dataclasses.replace(ANSWERS[2], argmax=2),)
        with pytest.raises(asyncpg.DataError):
            await jev_repo.record_exchange(conn, fields, answers)
        assert (
            await _count(
                conn, "jev_requests", "request_hash = $1", fields["request_hash"]
            )
            == 0
        )

    async def test_no_answers_write_nothing(self, conn: asyncpg.Connection) -> None:
        request_id = await jev_repo.record_request(conn, **_fields("error"))
        await jev_repo.record_answers(conn, request_id, [])
        assert await jev_repo.answers_for(conn, request_id) == []


# ---------------------------------------------------------------------------
# A request and its answers are one write
# ---------------------------------------------------------------------------

#: Ways the answers of an exchange fail to write after its request row has, each
#: refused by the database itself.
BROKEN_ANSWERS = {
    "one-question-answered-twice": (ANSWERS[0], ANSWERS[0]),
    "invalid-without-a-reason": (
        ANSWERS[0],
        dataclasses.replace(ANSWERS[1], valid=False),
    ),
    "a-noul-with-a-confidence": (dataclasses.replace(ANSWERS[1], confidence=0.9),),
}


class TestAnExchangeIsOneWrite:
    async def test_a_request_and_its_answers_are_written_together(
        self, conn: asyncpg.Connection
    ) -> None:
        fields = _fields()
        request_id = await jev_repo.record_exchange(conn, fields, ANSWERS)
        stored = await jev_repo.get_request(conn, request_id)
        assert stored["request_hash"] == fields["request_hash"]
        assert len(await jev_repo.answers_for(conn, request_id)) == len(ANSWERS)

    @pytest.mark.parametrize("answers", BROKEN_ANSWERS.values(), ids=BROKEN_ANSWERS)
    async def test_a_failed_answer_takes_its_request_with_it(
        self,
        committing: asyncpg.Connection,
        other: asyncpg.Connection,
        answers: tuple[Answer, ...],
    ) -> None:
        """
        On a connection of its own, as the runner holds one: a real transaction,
        so nothing is committed, and another connection sees no request row.
        """
        fields = _fields()
        with pytest.raises(asyncpg.IntegrityConstraintViolationError):
            await jev_repo.record_exchange(committing, fields, answers)

        assert not committing.is_in_transaction()
        for connection in (committing, other):
            assert (
                await _count(
                    connection,
                    "jev_requests",
                    "request_hash = $1",
                    fields["request_hash"],
                )
                == 0
            )

    @pytest.mark.parametrize("answers", BROKEN_ANSWERS.values(), ids=BROKEN_ANSWERS)
    async def test_inside_a_callers_transaction_it_is_a_savepoint(
        self,
        committing: asyncpg.Connection,
        other: asyncpg.Connection,
        answers: tuple[Answer, ...],
    ) -> None:
        """
        The exchange's rows go back and the caller's stay: the caller's
        transaction is still usable afterwards, and commits what it wrote.
        """
        callers = _fields("refused_budget")
        failed = _fields()
        async with committing.transaction():
            kept = await jev_repo.record_request(committing, **callers)
            with pytest.raises(asyncpg.IntegrityConstraintViolationError):
                await jev_repo.record_exchange(committing, failed, answers)
            # Usable: an aborted transaction would refuse this statement.
            assert await jev_repo.get_request(committing, kept) is not None

        assert await jev_repo.get_request(other, kept) is not None
        assert (
            await _count(
                other, "jev_requests", "request_hash = $1", failed["request_hash"]
            )
            == 0
        )

    async def test_an_ok_request_without_answers_is_refused_before_it_is_written(
        self, conn: asyncpg.Connection
    ) -> None:
        """
        It would be found as canonical, answer nothing, and hold the index
        against the real answer for good.
        """
        fields = _fields()
        with pytest.raises(ValueError, match="with its answers"):
            await jev_repo.record_exchange(conn, fields, [])
        assert (
            await _count(
                conn, "jev_requests", "request_hash = $1", fields["request_hash"]
            )
            == 0
        )

    @pytest.mark.parametrize("status", ("invalid", "error", *REFUSED))
    async def test_a_request_that_answered_nothing_is_recorded_without_answers(
        self, conn: asyncpg.Connection, status: str
    ) -> None:
        request_id = await jev_repo.record_exchange(conn, _fields(status), [])
        assert (await jev_repo.get_request(conn, request_id))["status"] == status


class TestTheCanonicalRace:
    async def test_the_loser_of_a_race_replays_the_winner(
        self, committing: asyncpg.Connection, other: asyncpg.Connection
    ) -> None:
        """
        Two runners record the same request. The loser's insert waits on the
        winner's uncommitted index entry, fails when the winner commits, and —
        its own transaction intact, because the exchange was a savepoint — reads
        the winner's answer instead of keeping its own.
        """
        request_hash = _hash()
        winner = committing.transaction()
        await winner.start()
        try:
            won = await jev_repo.record_exchange(
                committing, _fields(request_hash=request_hash), ANSWERS
            )
            async with other.transaction():
                loser = asyncio.create_task(
                    jev_repo.record_exchange(
                        other, _fields(request_hash=request_hash), ANSWERS[:1]
                    )
                )
                await asyncio.sleep(0.2)
                assert not loser.done(), "the loser should be waiting on the winner"
                await winner.commit()

                with pytest.raises(asyncpg.UniqueViolationError) as lost:
                    await loser
                assert jev_repo.is_canonical_conflict(lost.value)

                canonical = await jev_repo.find_canonical(other, request_hash)
                assert canonical is not None
                assert canonical["id"] == won
                replayed = await jev_repo.answers_for(other, canonical["id"])
                assert len(replayed) == len(ANSWERS)
        finally:
            if committing.is_in_transaction():
                await winner.rollback()

        assert (
            await _count(
                other,
                "jev_requests",
                "request_hash = $1 AND status = 'ok'",
                request_hash,
            )
            == 1
        )

    async def test_any_other_violation_is_not_a_race_to_settle(
        self, conn: asyncpg.Connection
    ) -> None:
        with pytest.raises(asyncpg.UniqueViolationError) as refused:
            await jev_repo.record_exchange(
                conn, _fields(), BROKEN_ANSWERS["one-question-answered-twice"]
            )
        assert not jev_repo.is_canonical_conflict(refused.value)

    async def test_nothing_but_a_unique_violation_is_one(self) -> None:
        assert not jev_repo.is_canonical_conflict(ValueError("jev_requests_canonical"))


# ---------------------------------------------------------------------------
# Reads for the lane
# ---------------------------------------------------------------------------


class TestFindCanonical:
    async def test_the_ok_answer_outside_the_probe_lane_is_the_record(
        self, conn: asyncpg.Connection
    ) -> None:
        request_hash = _hash()
        await _record(conn, "error", request_hash=request_hash)
        await _record(conn, "invalid", request_hash=request_hash)
        await _record(conn, lane="probe", request_hash=request_hash)
        canonical = await _record(conn, request_hash=request_hash)
        await _record(conn, lane="probe", request_hash=request_hash)

        found = await jev_repo.find_canonical(conn, request_hash)
        assert found is not None
        assert found["id"] == canonical
        assert found["state"] == STATE
        assert list(found["questions"]["regime"]["criteria"]) == OPTIONS

    @pytest.mark.parametrize(
        "recorded",
        (
            (),
            ({"lane": "probe"},),
            ({"status": "invalid"}, {"status": "error"}),
            tuple({"status": status} for status in REFUSED),
        ),
        ids=("nothing", "only-probes", "only-failures", "only-refusals"),
    )
    async def test_there_is_none_without_one(
        self, conn: asyncpg.Connection, recorded: tuple[dict[str, Any], ...]
    ) -> None:
        request_hash = _hash()
        for overrides in recorded:
            await _record(conn, **{**overrides, "request_hash": request_hash})
        assert await jev_repo.find_canonical(conn, request_hash) is None


class TestRequestsToday:
    async def test_it_counts_the_calls_made_and_not_the_refusals(
        self, conn: asyncpg.Connection
    ) -> None:
        for status in ("ok", "invalid", "error", *REFUSED):
            await _record(conn, status)
        await _record(conn, lane="probe")
        assert await jev_repo.requests_today(conn) == 4

    async def test_it_counts_from_utc_midnight_whatever_the_session_zone(
        self, conn: asyncpg.Connection
    ) -> None:
        """
        Fourteen hours from UTC, midnight falls fourteen or ten hours away from
        UTC's, so a count from the session's midnight disagrees about one of the
        two rows either side of it at any hour of the day.
        """
        await conn.execute("SET LOCAL TIME ZONE 'Pacific/Kiritimati'")
        midnight = await _utc_midnight(conn)
        await _backdated(conn, midnight - timedelta(seconds=1))
        await _backdated(conn, midnight + timedelta(seconds=1))
        assert await jev_repo.requests_today(conn) == 1

    async def test_the_day_is_read_from_the_stamp_not_from_the_caller(
        self, conn: asyncpg.Connection
    ) -> None:
        """
        ``requested_at`` is the caller's to set, so a budget counted from it
        could be dodged by claiming yesterday.
        """
        midnight = await _utc_midnight(conn)
        # Two recorded today that claim yesterday, one recorded yesterday that
        # claims today: the stamp says two, the claims say one.
        for _ in range(2):
            await _record(conn, requested_at=midnight - timedelta(days=1))
        await _backdated(
            conn, midnight - timedelta(hours=1), requested_at=datetime.now(UTC)
        )
        assert await jev_repo.requests_today(conn) == 2

    async def test_a_lane_counts_its_own_calls(self, conn: asyncpg.Connection) -> None:
        """
        Each lane's slice of the budget is compared against its own count: the
        calls recorded in it, a probe in the probe lane whatever set it asked.
        """
        for lane in ("research", "research", "decision", "probe"):
            await _record(conn, lane=lane)
        await _record(conn, "error", lane="research")
        await _record(conn, "refused_budget", lane="research")
        await _record(conn, lane="probe", question_set="decision.regime")

        assert await jev_repo.requests_today(conn, "research") == 3
        assert await jev_repo.requests_today(conn, "decision") == 1
        assert await jev_repo.requests_today(conn, "probe") == 2
        assert await jev_repo.requests_today(conn, "guardrail") == 0
        assert await jev_repo.requests_today(conn) == 6

    async def test_a_lane_counts_from_utc_midnight(
        self, conn: asyncpg.Connection
    ) -> None:
        midnight = await _utc_midnight(conn)
        await _backdated(conn, midnight - timedelta(seconds=1), lane="research")
        await _backdated(conn, midnight + timedelta(seconds=1), lane="research")
        assert await jev_repo.requests_today(conn, "research") == 1


# ---------------------------------------------------------------------------
# Reads for the road: what the vendor refused, and what may be sent
# ---------------------------------------------------------------------------

#: How the client records each failure (``jev_client.ERROR_KINDS``): the status
#: and the body that came back, and the class of what the SDK raised.
FAILURES: dict[str, tuple[int | None, str | None, str]] = {
    "auth": (401, '{"detail":"invalid key"}', "TypeSafeAuthenticationError"),
    "content_block": (403, "<html>blocked</html>", "TypeSafePermissionDeniedError"),
    "invalid_request": (422, '{"detail":[]}', "TypeSafeUnprocessableEntityError"),
    "rate_limited": (429, '{"detail":"slow down"}', "TypeSafeRateLimitError"),
    "server": (503, '{"error":"busy"}', "TypeSafeInternalServerError"),
    "timeout": (None, None, "TypeSafeAPITimeoutError"),
}


def _failed(kind: str, **overrides: Any) -> dict[str, Any]:
    """An ``error`` row's fields for a call that failed as ``kind``."""
    http_status, raw_body, error_class = FAILURES[kind]
    return {
        "http_status": http_status,
        "raw_body": raw_body,
        "error_class": error_class,
        "error_kind": kind,
        **overrides,
    }


REGIME_V1 = {"question_set": "decision.regime", "version": 1, "model": MODEL}


class TestTheStandingRefusals:
    """
    ``auth_failed_today``, ``set_refused`` and ``content_blocked``: what the
    vendor has refused and would refuse again, read from the rows its refusals
    left (docs/08, fact 4). Nothing writes a switch when the vendor refuses; the
    row is what holds.
    """

    async def test_an_authentication_failure_in_any_lane_holds_today(
        self, conn: asyncpg.Connection
    ) -> None:
        assert await jev_repo.auth_failed_today(conn) is False
        await _record(conn, "error", lane="research", **_failed("auth"))
        assert await jev_repo.auth_failed_today(conn) is True

    @pytest.mark.parametrize("kind", sorted(set(FAILURES) - {"auth"}))
    async def test_no_other_failure_is_an_authentication_failure(
        self, conn: asyncpg.Connection, kind: str
    ) -> None:
        await _record(conn, "error", **_failed(kind))
        assert await jev_repo.auth_failed_today(conn) is False

    async def test_an_authentication_failure_holds_until_utc_midnight(
        self, conn: asyncpg.Connection
    ) -> None:
        """
        Counted from UTC midnight by the database's stamp, like the budget, and
        in a session fourteen hours from UTC, where the session's own midnight
        would disagree about one of the two rows either side of it.
        """
        await conn.execute("SET LOCAL TIME ZONE 'Pacific/Kiritimati'")
        midnight = await _utc_midnight(conn)
        await _backdated(
            conn, midnight - timedelta(seconds=1), "error", **_failed("auth")
        )
        assert await jev_repo.auth_failed_today(conn) is False
        await _backdated(
            conn, midnight + timedelta(seconds=1), "error", **_failed("auth")
        )
        assert await jev_repo.auth_failed_today(conn) is True

    async def test_an_authentication_failure_is_dated_by_the_stamp(
        self, conn: asyncpg.Connection
    ) -> None:
        """A failure recorded today that claims yesterday still holds today."""
        yesterday = await _utc_midnight(conn) - timedelta(hours=1)
        await _record(conn, "error", requested_at=yesterday, **_failed("auth"))
        assert await jev_repo.auth_failed_today(conn) is True

    async def test_a_422_holds_its_set_version_and_model_and_nothing_else(
        self, conn: asyncpg.Connection
    ) -> None:
        await _record(conn, "error", **_failed("invalid_request"))
        assert await jev_repo.set_refused(conn, **REGIME_V1) is True
        for other in (
            {"version": 2},
            {"question_set": "probe.connectivity"},
            {"model": "jev-1.14.0"},
        ):
            assert await jev_repo.set_refused(conn, **{**REGIME_V1, **other}) is False

    async def test_a_422_holds_for_good(self, conn: asyncpg.Connection) -> None:
        """Not for the day: the same words would be refused again tomorrow."""
        long_ago = await _utc_midnight(conn) - timedelta(days=90)
        await _backdated(conn, long_ago, "error", **_failed("invalid_request"))
        assert await jev_repo.set_refused(conn, **REGIME_V1) is True

    @pytest.mark.parametrize("kind", sorted(set(FAILURES) - {"invalid_request"}))
    async def test_only_a_422_refuses_a_set(
        self, conn: asyncpg.Connection, kind: str
    ) -> None:
        await _record(conn, "error", **_failed(kind))
        assert await jev_repo.set_refused(conn, **REGIME_V1) is False

    async def test_a_content_block_holds_its_state_for_every_set(
        self, conn: asyncpg.Connection
    ) -> None:
        """
        Matched by the state alone, whichever set's call was blocked, a probe's
        included: what was blocked is the text, not the question about it.
        """
        blocked, other = _hash(), _hash()
        await _record(
            conn,
            "error",
            state_hash=blocked,
            lane="probe",
            question_set="research.excerpt",
            **_failed("content_block"),
        )
        assert await jev_repo.content_blocked(conn, blocked) is True
        assert await jev_repo.content_blocked(conn, other) is False

    @pytest.mark.parametrize("kind", sorted(set(FAILURES) - {"content_block"}))
    async def test_no_other_failure_blocks_a_state(
        self, conn: asyncpg.Connection, kind: str
    ) -> None:
        state_hash = _hash()
        await _record(conn, "error", state_hash=state_hash, **_failed(kind))
        assert await jev_repo.content_blocked(conn, state_hash) is False


#: The injection screen's words, as a pack hash, and its answers about a text:
#: addressed to people, addressed to an AI, and a tie, which is no answer.
SCREEN_PACK = "5" * 64
CLEAR = Answer("addressed_to_ai", "noul", noul=0.03, argmax="false", margin=0.94)
FLAGGED = Answer("addressed_to_ai", "noul", noul=0.97, argmax="true", margin=0.94)
TIED = Answer(
    "addressed_to_ai",
    "noul",
    noul=0.5,
    margin=0.0,
    valid=False,
    invalid_reason="tie",
)


def _text() -> str:
    """An excerpt no other test has stored."""
    return f"Item 2.02 Results of Operations, filing {uuid.uuid4().hex}."


async def _document(
    conn: asyncpg.Connection, text: str, source: str = "sec_edgar_rss"
) -> int:
    """A document holding ``text``, addressed by it, as the schema requires."""
    return await conn.fetchval(
        "INSERT INTO web_documents (source, url, content_sha256, excerpt) "
        "VALUES ($1, 'https://example.invalid/filing', $2, $3) "
        "RETURNING id",
        source,
        text_sha256(text),
        text,
    )


async def _quarantine(conn: asyncpg.Connection, document_id: int) -> None:
    await conn.execute(
        "UPDATE web_documents SET quarantined = TRUE, "
        "quarantine_reason = 'addressed to an AI' WHERE id = $1",
        document_id,
    )


async def _screened(
    conn: asyncpg.Connection,
    state_hash: str,
    answer: Answer = CLEAR,
    status: str = "ok",
    **overrides: Any,
) -> int:
    """The screen's recorded answer about the text whose state is ``state_hash``."""
    fields = {
        "state_hash": state_hash,
        "question_set": "guardrail.injection",
        "pack_hash": SCREEN_PACK,
        "lane": "guardrail",
        "provenance": "web",
        "subject_type": "web_excerpt",
        "subject_id": _hash(),
        **overrides,
    }
    return await _record(conn, status, answers=(answer,), **fields)


class TestTheWebReads:
    """
    ``content_quarantined`` and ``screened_clean``: whether text may be asked
    about at all, and whether the injection screen has cleared it.
    """

    async def test_content_is_quarantined_by_its_hash_under_any_source(
        self, conn: asyncpg.Connection
    ) -> None:
        text, other = _text(), _text()
        await _document(conn, text)
        assert await jev_repo.content_quarantined(conn, text_sha256(text)) is None

        from_elsewhere = await _document(conn, text, source="another_feed")
        await _quarantine(conn, from_elsewhere)
        await _document(conn, other)

        found = await jev_repo.content_quarantined(conn, text_sha256(text))
        assert found == from_elsewhere
        assert await jev_repo.content_quarantined(conn, text_sha256(other)) is None
        assert await jev_repo.content_quarantined(conn, _hash()) is None

    async def test_the_lookup_is_by_the_address_the_lane_computes(
        self, conn: asyncpg.Connection
    ) -> None:
        """
        The lane looks quarantine up by ``jev_hash.text_sha256`` of the text it
        is about to send, and a document is stored under the sha256 of its
        excerpt, by CHECK: so text beyond ASCII, stored and quarantined, is
        found by exactly the address the lane computes.
        """
        text = f"Momentum été ✓ 日本 {uuid.uuid4().hex}"
        document = await _document(conn, text)
        await _quarantine(conn, document)
        assert await jev_repo.content_quarantined(conn, text_sha256(text)) == document

    async def test_a_clear_canonical_answer_is_clean(
        self, conn: asyncpg.Connection
    ) -> None:
        state_hash = _hash()
        await _screened(conn, state_hash)
        assert await jev_repo.screened_clean(
            conn, state_hash=state_hash, pack_hash=SCREEN_PACK, model=MODEL
        )

    @pytest.mark.parametrize(
        "recorded",
        [
            {"answer": FLAGGED},
            {"answer": TIED},
            {"answer": dataclasses.replace(CLEAR, question_key="about_trading")},
            {"lane": "probe"},
            {
                "status": "invalid",
                "answer": _invalid(CLEAR, "model_mismatch"),
            },
            # A request refused whole whose answer still reads as clear: only
            # the request's status keeps it from counting.
            {"status": "invalid", "answer": CLEAR},
            # An answer not measured that still names the clear argmax: only
            # its validity keeps it from counting.
            {"answer": _invalid(CLEAR, "noul_invalid")},
            {"pack_hash": "6" * 64},
            {"model_requested": "jev-1.14.0", "model_answered": "jev-1.14.0"},
            {"state_hash": "other"},
        ],
        ids=[
            "flagged",
            "a-tie",
            "another-question",
            "a-probe",
            "a-response-refused-whole",
            "a-response-refused-whole-with-a-clear-answer",
            "an-invalid-answer-with-the-clear-argmax",
            "another-version-of-the-screen",
            "another-model",
            "another-text",
        ],
    )
    async def test_nothing_else_is_clean(
        self, conn: asyncpg.Connection, recorded: dict[str, Any]
    ) -> None:
        """
        Flagged, not measured, about another question, a probe's, refused
        whole, from other words, from another judge, or about other text: each
        leaves the text unscreened. Each case is barred by one filter of the
        query alone where the schema allows it, so dropping any one of them
        lets a case through: a response refused whole with a clear answer on
        it, and an invalid answer that still names ``false``, among them.
        """
        state_hash = _hash()
        overrides = dict(recorded)
        if overrides.get("state_hash") == "other":
            overrides["state_hash"] = _hash()
        await _screened(conn, overrides.pop("state_hash", state_hash), **overrides)
        assert not await jev_repo.screened_clean(
            conn, state_hash=state_hash, pack_hash=SCREEN_PACK, model=MODEL
        )


def _row(text: str, source: str = "sec_edgar_rss") -> jev_repo.DocumentRow:
    return jev_repo.DocumentRow(
        source=source, url="https://example.invalid/feed", excerpt=text
    )


class TestTheDocumentWriter:
    """
    What ``insert_documents`` hands back, and ``get_document`` reads: the id a
    document is stored under, which a caller that labels a document or keys a
    job by one (phase C7) is to trust, whether this call stored it or an
    earlier one did (the scope of phase C6, item 5).
    """

    async def test_a_document_already_stored_comes_back_under_its_own_id(
        self, conn: asyncpg.Connection
    ) -> None:
        """
        A row stored before comes back with the id it was stored under and
        ``inserted`` false, a new one with an id of its own, each tuple in the
        order the rows were given, which is not the order they are written in.
        """
        high, middle, low = sorted(
            (_text(), _text(), _text()), key=text_sha256, reverse=True
        )
        first = await jev_repo.insert_documents(conn, [_row(high), _row(low)])
        assert [(content, inserted) for _, content, inserted in first] == [
            (text_sha256(high), True),
            (text_sha256(low), True),
        ]
        ids = {content: document_id for document_id, content, _ in first}

        again = await jev_repo.insert_documents(
            conn, [_row(high), _row(middle), _row(low)]
        )

        assert again[0] == (ids[text_sha256(high)], text_sha256(high), False)
        assert again[2] == (ids[text_sha256(low)], text_sha256(low), False)
        new_id, content, inserted = again[1]
        assert (content, inserted) == (text_sha256(middle), True)
        assert new_id not in ids.values()

    async def test_a_batch_is_written_in_the_unique_indexs_order(
        self, conn: asyncpg.Connection
    ) -> None:
        """
        Given the higher content address first, the lower is written first:
        the lock order that keeps two writers from waiting on each other
        (``test_web_ingest.py::TestTwoWritersAtOnce``), read here off the ids.
        """
        high, low = sorted((_text(), _text()), key=text_sha256, reverse=True)
        stored = await jev_repo.insert_documents(conn, [_row(high), _row(low)])
        (high_id, _, _), (low_id, _, _) = stored
        assert low_id < high_id

    async def test_each_id_reads_back_as_the_document_it_names(
        self, conn: asyncpg.Connection
    ) -> None:
        texts = [_text(), _text()]
        stored = await jev_repo.insert_documents(
            conn, [_row(texts[0]), _row(texts[1], source="another_feed")]
        )
        for (document_id, content, _), text in zip(stored, texts, strict=True):
            document = await jev_repo.get_document(conn, document_id)
            assert document is not None
            assert document["id"] == document_id
            assert (document["content_sha256"], document["excerpt"]) == (content, text)
            assert document["title"] is None and document["published_at"] is None
            assert document["quarantined"] is False
        missing = max(document_id for document_id, _, _ in stored) + 1_000
        assert await jev_repo.get_document(conn, missing) is None


# ---------------------------------------------------------------------------
# Reads for the control plane
# ---------------------------------------------------------------------------


class TestStatusSummary:
    async def test_a_day_with_no_calls_has_measured_nothing(
        self, conn: asyncpg.Connection
    ) -> None:
        summary = await jev_repo.status_summary(conn)
        assert summary["since"] == await _utc_midnight(conn)
        assert (summary["requests"], summary["calls"], summary["answers"]) == (0, 0, 0)
        assert summary["by_status"] == summary["by_lane"] == {}
        assert summary["latency_ms"] == {"n": 0, "p50": None, "p95": None}
        assert summary["validity_rate"] is None

    async def test_it_counts_the_day_and_measures_what_was_called(
        self, conn: asyncpg.Connection
    ) -> None:
        await _record(
            conn,
            latency_ms=100,
            answers=(ANSWERS[0], _invalid(ANSWERS[1], "tie")),
        )
        await _record(conn, lane="probe", latency_ms=200, answers=(ANSWERS[1],))
        await _record(conn, "error", lane="research", latency_ms=300)
        await _record(
            conn,
            "invalid",
            latency_ms=400,
            answers=(_invalid(ANSWERS[0], "model_mismatch"),),
        )
        # A refusal is not a call, whatever latency it carries.
        await _record(conn, "refused_budget", lane="research", latency_ms=9_999)

        summary = await jev_repo.status_summary(conn)

        assert summary["by_status"] == {
            "ok": 2,
            "invalid": 1,
            "error": 1,
            "refused_budget": 1,
        }
        assert summary["by_lane"] == {"decision": 2, "probe": 1, "research": 2}
        assert summary["by_lane_status"] == {
            "decision": {"ok": 1, "invalid": 1},
            "probe": {"ok": 1},
            "research": {"error": 1, "refused_budget": 1},
        }
        assert (summary["requests"], summary["calls"]) == (5, 4)
        # percentile_cont over 100, 200, 300 and 400, interpolating.
        assert summary["latency_ms"] == {
            "n": 4,
            "p50": pytest.approx(250.0),
            "p95": pytest.approx(385.0),
        }
        assert (summary["answers"], summary["valid_answers"]) == (4, 2)
        assert summary["validity_rate"] == 0.5

    async def test_a_day_of_only_invalid_answers_measures_zero_not_nothing(
        self, conn: asyncpg.Connection
    ) -> None:
        await _record(
            conn, "invalid", answers=(_invalid(ANSWERS[0], "model_mismatch"),)
        )
        summary = await jev_repo.status_summary(conn)
        assert summary["validity_rate"] == 0.0

    async def test_yesterday_is_not_today(self, conn: asyncpg.Connection) -> None:
        midnight = await _utc_midnight(conn)
        yesterday = await _backdated(
            conn, midnight - timedelta(minutes=1), latency_ms=5_000
        )
        await jev_repo.record_answers(conn, yesterday, (ANSWERS[0],))
        await _record(conn, latency_ms=100, answers=(_invalid(ANSWERS[0], "tie"),))

        summary = await jev_repo.status_summary(conn)
        assert (summary["requests"], summary["calls"]) == (1, 1)
        assert summary["latency_ms"] == {"n": 1, "p50": 100.0, "p95": 100.0}
        assert (summary["answers"], summary["validity_rate"]) == (1, 0.0)


class TestReads:
    async def test_an_unknown_request_is_none(self, conn: asyncpg.Connection) -> None:
        assert await jev_repo.get_request(conn, -1) is None

    async def test_requests_are_listed_newest_first_and_narrowed_by_what_is_given(
        self, conn: asyncpg.Connection
    ) -> None:
        first = await _record(conn)
        second = await _record(conn, "error", lane="research")
        third = await _record(conn, "error")
        fourth = await _record(conn, lane="research")

        def ids(rows: list[dict[str, Any]]) -> list[int]:
            return [row["id"] for row in rows]

        assert ids(await jev_repo.list_requests(conn)) == [fourth, third, second, first]
        assert ids(await jev_repo.list_requests(conn, lane="research")) == [
            fourth,
            second,
        ]
        assert ids(await jev_repo.list_requests(conn, status="error")) == [
            third,
            second,
        ]
        assert ids(
            await jev_repo.list_requests(conn, lane="research", status="error")
        ) == [second]
        assert ids(await jev_repo.list_requests(conn, limit=2)) == [fourth, third]
        assert await jev_repo.list_requests(conn, lane="ops") == []

        listed = (await jev_repo.list_requests(conn, limit=1))[0]
        assert listed["state"] == STATE
        assert list(listed["questions"]) == list(QUESTIONS)

    async def test_a_page_is_at_least_one_row_and_at_most_the_ceiling(
        self, conn: asyncpg.Connection
    ) -> None:
        await conn.execute(
            """
            INSERT INTO jev_requests (
                request_hash, state_hash, question_set, question_set_version,
                pack_hash, lane, provenance, subject_type, subject_id, as_of,
                state, questions, model_requested, status, requested_at
            )
            SELECT md5(i::text), md5(i::text), 'decision.regime', 1, $1,
                   'decision', 'internal', 'session', i::text, now(),
                   '{}'::jsonb, '{}'::json, $2, 'refused_budget', now()
            FROM generate_series(1, $3::int) AS i
            """,
            "9" * 64,
            MODEL,
            jev_repo.MAX_LIMIT + 1,
        )
        assert len(await jev_repo.list_requests(conn, limit=0)) == 1
        assert len(await jev_repo.list_requests(conn, limit=10_000)) == (
            jev_repo.MAX_LIMIT
        )


# ---------------------------------------------------------------------------
# Labels and evaluations
# ---------------------------------------------------------------------------


def _label(**overrides: Any) -> dict[str, Any]:
    label: dict[str, Any] = {
        "question_set": "research.catalogue",
        "question_set_version": 1,
        "question_key": "asset_class",
        "subject_type": "catalogue_entry",
        "subject_id": "time-series-momentum",
        "label": "futures",
        "labelled_by": "operator:quentin",
    }
    label.update(overrides)
    return label


class TestLabels:
    async def test_a_label_is_recorded_with_its_labeller_and_when(
        self, conn: asyncpg.Connection
    ) -> None:
        label_id = await jev_repo.record_label(conn, **_label(note="from the paper"))
        stored = await conn.fetchrow("SELECT * FROM jev_labels WHERE id = $1", label_id)
        assert (stored["label"], stored["labelled_by"], stored["note"]) == (
            "futures",
            "operator:quentin",
            "from the paper",
        )
        assert stored["labelled_at"] == await conn.fetchval("SELECT now()")

    async def test_a_model_is_not_a_labeller(self, conn: asyncpg.Connection) -> None:
        with pytest.raises(asyncpg.CheckViolationError):
            async with conn.transaction():
                await jev_repo.record_label(
                    conn, **_label(labelled_by="jev:research.catalogue")
                )

    async def test_a_labeller_does_not_revise_a_label(
        self, conn: asyncpg.Connection
    ) -> None:
        await jev_repo.record_label(conn, **_label())
        with pytest.raises(asyncpg.UniqueViolationError):
            async with conn.transaction():
                await jev_repo.record_label(conn, **_label(label="equities"))
        # Another labeller may disagree; the disagreement is a measurement.
        await jev_repo.record_label(
            conn, **_label(label="equities", labelled_by="source:pwb-readme@3f2a9c1")
        )


async def _evaluation(conn: asyncpg.Connection, **overrides: Any) -> int:
    row: dict[str, Any] = {
        "question_set": "research.catalogue",
        "question_set_version": 1,
        "question_key": "asset_class",
        "model": MODEL,
        "dataset_ref": "readme-61",
        "dataset_sha256": "a" * 64,
        "possibly_in_training": True,
        "n": 61,
        "n_per_class": json.dumps({"equities": 40, "futures": 21}),
        "code_commit": "0ec084f",
    }
    row.update(overrides)
    columns = list(row)
    placeholders = [
        f"${i}::jsonb" if column in ("n_per_class", "calibration_bins") else f"${i}"
        for i, column in enumerate(columns, start=1)
    ]
    return await conn.fetchval(
        f"INSERT INTO jev_evaluations ({', '.join(columns)}) "
        f"VALUES ({', '.join(placeholders)}) RETURNING id",
        *row.values(),
    )


class TestEvaluations:
    async def test_evaluations_are_listed_newest_first_and_narrowed(
        self, conn: asyncpg.Connection
    ) -> None:
        first = await _evaluation(conn)
        second = await _evaluation(conn, question_key="mechanism")
        third = await _evaluation(conn, model="jev-1.14.0")
        fourth = await _evaluation(conn, question_set_version=2)

        def ids(rows: list[dict[str, Any]]) -> list[int]:
            return [row["id"] for row in rows]

        assert ids(await jev_repo.list_evaluations(conn)) == [
            fourth,
            third,
            second,
            first,
        ]
        assert ids(
            await jev_repo.list_evaluations(
                conn,
                question_set="research.catalogue",
                question_set_version=1,
                question_key="asset_class",
                model=MODEL,
            )
        ) == [first]
        assert ids(await jev_repo.list_evaluations(conn, model="jev-1.14.0")) == [third]
        assert ids(await jev_repo.list_evaluations(conn, limit=1)) == [fourth]

    async def test_what_was_not_measured_comes_back_as_none_and_a_zero_as_zero(
        self, conn: asyncpg.Connection
    ) -> None:
        bins = [{"low": 0.9, "high": 1.0, "n": 12, "accuracy": 0.75}]
        await _evaluation(conn, flip_rate=0.0, calibration_bins=json.dumps(bins))
        (evaluation,) = await jev_repo.list_evaluations(conn)
        assert evaluation["flip_rate"] == 0.0
        assert evaluation["accuracy"] is None
        assert evaluation["threshold"] is None
        assert evaluation["n_per_class"] == {"equities": 40, "futures": 21}
        assert evaluation["calibration_bins"] == bins


# ---------------------------------------------------------------------------
# The contract with the validator
# ---------------------------------------------------------------------------


def _validated_answer_fields() -> set[str]:
    validate = pytest.importorskip("src.programme.jev_validate")
    answer_type = validate.ValidatedAnswer
    if dataclasses.is_dataclass(answer_type):
        return {field.name for field in dataclasses.fields(answer_type)}
    return set(answer_type.model_fields)


class TestTheValidatorsAnswersFitTheLedger:
    """
    ``record_answers`` reads ``ANSWER_FIELDS`` off whatever it is given, and the
    stand-in above has exactly those. These hold the validator's type to the
    same names, and put what it produces through the shipped writer into the
    shipped schema: the one place the validator's output meets the ledger's
    constraints before a lane does.
    """

    def test_the_stand_in_has_the_fields_the_repo_reads(self) -> None:
        names = tuple(field.name for field in dataclasses.fields(Answer))
        assert names == jev_repo.ANSWER_FIELDS

    def test_the_validated_answer_has_the_fields_the_repo_reads(self) -> None:
        assert _validated_answer_fields() == set(jev_repo.ANSWER_FIELDS)

    @pytest.mark.parametrize(
        "body",
        (
            BODY,
            # SDK issue #15: the vendor's choice is not its own argmax.
            BODY.replace('"choice": "risk_on"', '"choice": "neutral"'),
            # A Noul carrying a confidence it should not have.
            BODY.replace('"noul": 0.83}', '"noul": 0.83, "confidence": 0.9}'),
            BODY.replace(MODEL, "jev-1.14.0"),
            json.dumps({"model": MODEL, "answers": {}}),
            "<html><body>Request blocked.</body></html>",
        ),
        ids=("clean", "choice-not-argmax", "noul-confidence", "model", "empty", "html"),
    )
    async def test_what_the_validator_produces_is_recorded_as_produced(
        self, conn: asyncpg.Connection, body: str
    ) -> None:
        validate = pytest.importorskip("src.programme.jev_validate")
        validation = validate.validate_body(body, QUESTIONS, MODEL)
        fields = _fields(
            validation.status,
            raw_body=body,
            model_answered=validation.model_answered,
        )

        request_id = await jev_repo.record_exchange(conn, fields, validation.answers)

        stored = await jev_repo.get_request(conn, request_id)
        assert stored["status"] == validation.status
        rows = await jev_repo.answers_for(conn, request_id)
        assert [row["question_key"] for row in rows] == [
            answer.question_key for answer in validation.answers
        ]
        for row, answer in zip(rows, validation.answers, strict=True):
            for name in jev_repo.ANSWER_FIELDS:
                expected = getattr(answer, name)
                if name == "probabilities" and expected is not None:
                    expected = dict(expected)
                assert row[name] == expected, (answer.question_key, name)


# ---------------------------------------------------------------------------
# The reads the forward clock, the planner and the harness make (phase C4)
# ---------------------------------------------------------------------------
#
# Every one of these once ran on Postgres only as plumbing, or not at all:
# the planner's unit rig fakes them, and a wrong filter in any of them passed
# every suite (docs/08, C4's review). Each is held here to what it counts.


async def _job(
    conn: asyncpg.Connection,
    kind: str,
    *,
    status: str = "queued",
    key: str | None = None,
    payload: dict[str, Any] | None = None,
) -> uuid.UUID:
    """A job through the shipped writer, then moved to ``status``."""
    job_id = await job_repo.enqueue(
        conn, kind, payload or {}, dedupe_key=key or f"test:{uuid.uuid4()}"
    )
    assert job_id is not None
    if status != "queued":
        await conn.execute("UPDATE jobs SET status = $2 WHERE id = $1", job_id, status)
    return job_id


class TestPendingJobs:
    async def test_only_queued_and_running_jobs_of_the_kinds_count(
        self, conn: asyncpg.Connection
    ) -> None:
        """
        What the planner subtracts from a lane's share: calls already coming.
        A finished job made its call, if any, and ``requests_today`` counts
        it; counted again here, a lane's history would use up its share for
        good.
        """
        before = await jev_repo.pending_jobs(conn, ["jev_regime"])
        for status in ("queued", "running", "succeeded", "failed", "cancelled"):
            await _job(conn, "jev_regime", status=status)
        await _job(conn, "jev_probe")
        await _job(conn, "jev_reask", status="running")
        await _job(conn, "ingest_reference_bars")

        assert await jev_repo.pending_jobs(conn, ["jev_regime"]) == before + 2
        assert await jev_repo.pending_jobs(conn, ["jev_probe", "jev_reask"]) >= 2
        assert await jev_repo.pending_jobs(conn, ["no_such_kind"]) == 0


class TestTheCanonicalRequestsOfADay:
    async def test_exactly_the_ok_rows_outside_the_probe_lane_stamped_inside(
        self, conn: asyncpg.Connection
    ) -> None:
        """
        What the re-ask sample is drawn from: the canonical answers — ``ok``,
        outside the probe lane — stamped in the window, the start in and the
        end out; never a probe, a refused answer or a failed call.
        """
        start = datetime(2026, 9, 27, tzinfo=UTC)
        end = start + timedelta(days=1)
        inside = await _backdated(conn, start)
        await jev_repo.record_answers(conn, inside, ANSWERS)
        late_in_day = await _backdated(conn, end - timedelta(microseconds=1))
        await jev_repo.record_answers(conn, late_in_day, ANSWERS)
        for available_at, status, overrides in (
            (start + timedelta(hours=1), "ok", {"lane": "probe"}),
            (start + timedelta(hours=2), "invalid", {}),
            (start + timedelta(hours=3), "error", {}),
            (start - timedelta(microseconds=1), "ok", {}),
            (end, "ok", {}),
        ):
            await _backdated(conn, available_at, status, **overrides)

        found = await jev_repo.canonical_requests_between(conn, start=start, end=end)

        assert [row["id"] for row in found] == [inside, late_in_day]

    async def test_only_the_valid_answers_margins_are_read(
        self, conn: asyncpg.Connection
    ) -> None:
        """
        The low-margin stratum reads the margins of valid answers alone: an
        invalid answer's margin, where one was recorded, is not a lead the
        model stated.
        """
        start = datetime(2026, 9, 27, tzinfo=UTC)
        request_id = await _backdated(conn, start + timedelta(hours=1))
        await jev_repo.record_answers(
            conn,
            request_id,
            (ANSWERS[0], _invalid(ANSWERS[1], "tie"), ANSWERS[2]),
        )

        (row,) = await jev_repo.canonical_requests_between(
            conn, start=start, end=start + timedelta(days=1)
        )

        assert sorted(row["valid_margins"]) == sorted(
            [ANSWERS[0].margin, ANSWERS[2].margin]
        )


def _regime_answer(argmax: str, margin: float) -> Answer:
    """The regime question answered with ``argmax`` leading by ``margin``."""
    return dataclasses.replace(ANSWERS[0], choice=argmax, argmax=argmax, margin=margin)


class TestProbePairs:
    """
    The flip report's pairs: each canonical answer beside its re-ask, one row
    per canonical request, whatever the re-ask came to. It once joined only
    re-asks recorded ``ok`` and answered by the canonical's model, so a
    re-ask refused whole — the vendor answering as another model — or failed
    was in no count, and a vendor that malformed every re-ask read as though
    none had been made (docs/08, C4's review).
    """

    async def _canonical(self, conn: asyncpg.Connection, **overrides: Any) -> dict:
        fields = {"request_hash": _hash(), "pack_hash": "9" * 64, **overrides}
        request_id = await _record(
            conn, answers=(_regime_answer("risk_on", 0.41),), **fields
        )
        return {"id": request_id, **fields}

    async def _reask(
        self,
        conn: asyncpg.Connection,
        canonical: dict,
        status: str = "ok",
        answers: tuple[Answer, ...] | None = None,
        **overrides: Any,
    ) -> int:
        return await _record(
            conn,
            status,
            answers=answers,
            request_hash=canonical["request_hash"],
            pack_hash=canonical["pack_hash"],
            lane="probe",
            **overrides,
        )

    async def test_every_re_ask_is_a_pair_whatever_it_came_to(
        self, conn: asyncpg.Connection
    ) -> None:
        flipped = await self._canonical(conn)
        refused_whole = await self._canonical(conn)
        failed_then_answered = await self._canonical(conn)
        refused_before_sending = await self._canonical(conn)
        failed = await self._canonical(conn)

        answered = await self._reask(
            conn, flipped, answers=(_regime_answer("neutral", 0.2),)
        )
        invalid = await self._reask(
            conn,
            refused_whole,
            "invalid",
            answers=(_invalid(ANSWERS[0], "model_mismatch"),),
            model_answered="jev-latest",
        )
        await self._reask(conn, failed_then_answered, "error")
        retried = await self._reask(
            conn, failed_then_answered, answers=(_regime_answer("risk_on", 0.3),)
        )
        refused = await self._reask(conn, refused_before_sending, "refused_budget")
        timed_out = await self._reask(conn, failed, "error")

        pairs = await jev_repo.probe_pairs(
            conn,
            question_set="decision.regime",
            version=1,
            question_key="regime",
            model=MODEL,
        )

        by_canonical = {pair["canonical_request_id"]: pair for pair in pairs}
        expected = {
            flipped["id"]: (answered, "ok", True, "neutral"),
            refused_whole["id"]: (invalid, "invalid", False, "risk_on"),
            failed_then_answered["id"]: (retried, "ok", True, "risk_on"),
            refused_before_sending["id"]: (refused, "refused_budget", None, None),
            failed["id"]: (timed_out, "error", None, None),
        }
        assert set(by_canonical) == set(expected), "a re-ask is in no pair"
        for canonical_id, (probe_id, status, valid, argmax) in expected.items():
            pair = by_canonical[canonical_id]
            assert (
                pair["probe_request_id"],
                pair["probe_status"],
                pair["probe_valid"],
                pair["probe_argmax"],
            ) == (probe_id, status, valid, argmax), canonical_id
            assert pair["canonical_valid"] is True
            assert pair["canonical_argmax"] == "risk_on"
            assert pair["lag_seconds"] > 0

    async def test_what_is_not_a_re_ask_of_the_answer_is_no_pair(
        self, conn: asyncpg.Connection
    ) -> None:
        """
        A probe of another pack, a probe asking another judge, and a probe
        stamped before the answer are not re-asks of it; nor is a canonical
        answer of another set.
        """
        other_pack = await self._canonical(conn)
        await self._reask(
            conn,
            {**other_pack, "pack_hash": "8" * 64},
            answers=(_regime_answer("neutral", 0.2),),
        )
        other_judge = await self._canonical(conn)
        await self._reask(
            conn,
            other_judge,
            answers=(_regime_answer("neutral", 0.2),),
            model_requested="jev-1.14.0",
            model_answered="jev-1.14.0",
        )
        early = {"request_hash": _hash(), "pack_hash": "9" * 64}
        await self._reask(conn, early, answers=(_regime_answer("neutral", 0.2),))
        await self._canonical(conn, **early)
        other_set = await self._canonical(conn, question_set="decision.other")
        await self._reask(conn, other_set, answers=(_regime_answer("neutral", 0.2),))

        pairs = await jev_repo.probe_pairs(
            conn,
            question_set="decision.regime",
            version=1,
            question_key="regime",
            model=MODEL,
        )

        assert pairs == []


class TestFirstJobSession:
    async def test_the_series_starts_at_its_own_versions_first_job(
        self, conn: asyncpg.Connection
    ) -> None:
        """
        A version bump starts a new series; counted from the first job of any
        version, its sessions since the old version's first job would all
        read as absent.
        """
        for session, name, version in (
            ("2026-09-10", "decision.regime", 1),
            ("2026-09-14", "decision.regime", 1),
            ("2026-09-01", "decision.regime", 0),
            ("2026-08-25", "decision.other", 1),
            ("not-a-date", "decision.regime", 1),
        ):
            await _job(
                conn,
                "jev_regime",
                payload={"session": session, "set": name, "version": version},
            )

        assert await jev_repo.first_job_session(
            conn, "jev_regime", question_set="decision.regime", version=1
        ) == date(2026, 9, 10)
        assert await jev_repo.first_job_session(conn, "jev_regime") == (
            date(2026, 8, 25)
        )
        assert await jev_repo.first_job_session(conn, "no_such_kind") is None


class TestTheDatabaseClock:
    async def test_it_is_the_moment_of_the_read_not_the_transaction(
        self, conn: asyncpg.Connection
    ) -> None:
        """
        ``jev_clock.database_now`` decides whether a session may still be
        asked. Inside a transaction ``now()`` is the moment it began, so a
        handler holding one open across the cutoff would read a time before
        it; ``clock_timestamp()`` is the moment of the read.
        """
        began = await conn.fetchval("SELECT now()")
        first = await jev_clock.database_now(conn)
        await asyncio.sleep(0.05)
        second = await jev_clock.database_now(conn)
        assert await conn.fetchval("SELECT now()") == began
        assert began <= first < second


class TestThePlannerOnAQueueWithHistory:
    async def test_finished_jobs_do_not_use_up_the_share(
        self, conn: asyncpg.Connection
    ) -> None:
        """
        At a budget of 10 the decision lane has 2 calls a day. Three finished
        regime jobs from earlier days are history, not calls coming, so the
        next two sessions are still planned; had they been counted as
        waiting, the planner would never plan a session again.
        """
        from src.db.repos import flags as flag_repo
        from src.programme import flags, jev_catalogue, jev_plan

        for key, value in {
            flags.PROGRAMME_ENABLED: True,
            flags.JEV_ENABLED: True,
            f"{flags.JEV_AREA_PREFIX}decisions": True,
            flags.JEV_MODEL: jev_catalogue.DEFAULT_MODEL,
            flags.JEV_DAILY_REQUEST_BUDGET: 10,
        }.items():
            await flag_repo.set_flag(conn, key, value, "test")
        assert jev_catalogue.lane_budget(10, "decision") == 2
        await conn.execute("DELETE FROM jobs WHERE kind = 'jev_regime'")
        for status in ("succeeded", "failed", "succeeded"):
            await _job(conn, "jev_regime", status=status)

        now = datetime(2026, 9, 28, 14, 0, tzinfo=UTC)
        planned = await jev_plan.plan(conn, now=now, key_available=True)

        assert [key for key in planned if key.startswith("jev_regime")] == [
            "jev_regime:decision.regime@1:2026-09-28",
            "jev_regime:decision.regime@1:2026-09-29",
        ]
