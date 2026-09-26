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
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

pytest.importorskip("asyncpg")

import asyncpg  # noqa: E402

from src.db import migrate as migrations  # noqa: E402
from src.programme import jev_repo  # noqa: E402

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
                status, raw_body, latency_ms, requested_at, available_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb,
                    $12::json, $13, $14, $15, $16, $17, $18, $19, $20)
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
