"""
test_jev_ops.py
---------------
Phase D3 on PostgreSQL: ``ops.job_error`` asked about a failed job's error as
its skeleton, through the programme's own loop, and the harness's two read
surfaces' jobs half.

The planner and the drain run as shipped; so do the handler, code's triage,
the redactor, the lane, the validator, the ledger and the schema. Nothing is
replaced but the vendor — the research tests' fake of ``jev_client.ask``, which
reads a job error's state as its text, ``jev_questions.job_error_text``, so a
test can script a failure for it. What must hold:

* **The canary** (docs/09, section 13; design M8): markers planted in failed
  jobs' errors — one code leaves to Jev, another, one code places, one too
  short to ask about, one of a kind code alone places — and in a failed job's
  payload and result are found in that job's own column alone after the loop
  has asked about every skeleton it may, read from ``information_schema``:
  never in ``jev_requests.state`` or any other text or JSON column of any
  table, any log record at DEBUG, any call the vendor saw, or any other job's
  payload, result or error. What left is each skeleton, and nothing else.
* **Only what code leaves to Jev is asked about**: each skeleton once, by its
  newest job, and planned again on no later day; never an error code places,
  one too short to ask about, one of a kind code alone places, one that
  failed on or before the day the pin was first observed, one older than the
  week, or one an expired lease left with no finish time. Asked again by an
  older job of the same skeleton, it is replayed from its row, with no call.
* **A job is unchanged by every outcome** (docs/09, section 6.1): an answer,
  a refusal, a timeout, a block, a 422 or a refused key leave the failed job,
  the findings register, the hypotheses, the candidates, the assessments and
  the switches exactly as they were.
* **What preview shows is what would leave** (``TestPreviewIsThePlanners``):
  on the same rows, preview's subjects are the planner's, in its order, and
  each state it prints is the state the handler hands the road; with the
  detail switch off it says so and the planner plans nothing.
* **Suggestions show how each ask came out and no answer**: on a ledger the
  shipped jobs wrote, each failed job of the week by its id and kind, with
  code's chip, and how the ask of its skeleton came out; no error, no
  skeleton and no answer printed.

Each test runs on a database of its own, derived from ``TEST_DATABASE_URL``:
the ledger refuses DELETE. Every error is invented. Skipped unless
``TEST_DATABASE_URL`` is set.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

pytest.importorskip("asyncpg")

import asyncpg  # noqa: E402

from src.db import migrate as migrations  # noqa: E402
from src.db.repos import flags as flag_repo  # noqa: E402
from src.db.repos import jobs as job_repo  # noqa: E402
from src.programme import (  # noqa: E402
    flags,
    jev_chips,
    jev_client,
    jev_eval,
    jev_jobs,
    jev_lane,
    jev_plan,
    jev_questions,
    jev_repo,
)
from src.programme.job_errors import JobFailedError  # noqa: E402
from tests.integration import test_jev_research as research  # noqa: E402
from tests.integration.test_jev_research import (  # noqa: E402
    KEY,
    _loop,
    _plan_and_drain,
    _Vendor,
)
from tests.integration.test_web_ingest import (  # noqa: E402
    _columns_holding,
    _logged,
    _token,
)

TEST_DSN = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="TEST_DATABASE_URL not set")

OPS_AREA = f"{flags.JEV_AREA_PREFIX}ops"
DETAIL = flags.JEV_SEND_INTERNAL_DETAIL

#: The switches every test starts with: the programme, Jev, the ops area and
#: the detail switch, which the ops set declares (docs/09, owner item 9.1).
ON: dict[str, Any] = {
    flags.PROGRAMME_ENABLED: True,
    flags.JEV_ENABLED: True,
    OPS_AREA: True,
    DETAIL: True,
}

OPS = jev_questions.OPS_JOB_ERROR

#: Invented failed jobs' errors, each with a slot a marker or an invented
#: identifier is formatted into: three code leaves to Jev, each a skeleton
#: long enough to ask about; one code places; one too short to ask about; and
#: one of a kind whose errors code alone places.
ERRORS = {
    "left": ("ingest_bars", "[Errno 111] Connection refused while reading {}"),
    "other": ("backtest", 'duplicate key value violates unique constraint "{}"'),
    "third": (
        "ingest_reference_bars",
        "[Errno 104] Connection reset by peer while sending {}",
    ),
    "placed": ("backtest", "unknown backtest run {}"),
    "short": ("walkforward", "Invented {}"),
    "untriaged": ("live_decision", "Invented failure {}"),
}

#: A clock the planner is run at where a test needs one: within a week of
#: the midnight after the pin was first observed, so the rule's read starts
#: where the population does.
NOW = datetime(2026, 10, 1, 15, tzinfo=UTC)


# ---------------------------------------------------------------------------
# The database
# ---------------------------------------------------------------------------


def _derived(suffix: str) -> str:
    base, _, tail = TEST_DSN.partition("?")
    return f"{base}_{suffix}?{tail}" if tail else f"{base}_{suffix}"


def _name(dsn: str) -> str:
    return dsn.partition("?")[0].rsplit("/", 1)[-1]


async def _drop(dsn: str) -> None:
    admin = await asyncpg.connect(TEST_DSN)
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{_name(dsn)}" WITH (FORCE)')
    finally:
        await admin.close()


@pytest.fixture
async def db() -> AsyncIterator[tuple[str, asyncpg.Connection]]:
    """A database of the test's own, migrated, with :data:`ON` set."""
    dsn = _derived("jev_ops")
    await _drop(dsn)
    admin = await asyncpg.connect(TEST_DSN)
    try:
        await admin.execute(f'CREATE DATABASE "{_name(dsn)}"')
    finally:
        await admin.close()
    await migrations.migrate(dsn)
    conn = await asyncpg.connect(dsn)
    try:
        for key, value in ON.items():
            await flag_repo.set_flag(conn, key, value, "test")
        yield dsn, conn
    finally:
        await conn.close()
        await _drop(dsn)


def _text_of(state: Any) -> str | None:
    """
    The research vendor's reading of a state's text, and a job error's state
    read as its text, so ``failing`` can script a failure for a skeleton.
    """
    if isinstance(state, dict) and "error" in state:
        return jev_questions.job_error_text(
            jev_questions.JobErrorState(
                job_kind=state["job_kind"], error=tuple(state["error"])
            )
        )
    return _READ_TEXT(state)


_READ_TEXT = research._text_of


@pytest.fixture
def vendor(monkeypatch: pytest.MonkeyPatch) -> _Vendor:
    fake = _Vendor()
    monkeypatch.setattr(jev_client, "ask", fake.ask)
    monkeypatch.setattr(research, "_text_of", _text_of)
    return fake


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


def _identifier() -> str:
    """An invented identifier the redactor reduces to ``[id]``."""
    return f"m{uuid.uuid4().hex[:8]}9"


async def _failed(
    conn: asyncpg.Connection,
    name: str,
    finished_at: datetime | None,
    *,
    fill: str | None = None,
    payload: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    started_at: datetime | None = None,
) -> uuid.UUID:
    """
    A job of :data:`ERRORS`' ``name`` through the shipped writer, then ended
    as the queue ends one: failed, with its error — ``fill``, or an invented
    identifier, in its slot — when it finished, which an expired lease leaves
    unset, and when it was first claimed.
    """
    kind, error = ERRORS[name]
    job_id = await job_repo.enqueue(
        conn, kind, payload or {}, dedupe_key=f"test:{uuid.uuid4()}"
    )
    assert job_id is not None
    await conn.execute(
        "UPDATE jobs SET status = 'failed', attempts = 1, error = $2, "
        "finished_at = $3, started_at = $4, result = $5::jsonb WHERE id = $1",
        job_id,
        error.format(_identifier() if fill is None else fill),
        finished_at,
        started_at or finished_at,
        None if result is None else json.dumps(result),
    )
    return job_id


async def _state(conn: asyncpg.Connection, job_id: uuid.UUID) -> dict[str, Any]:
    """The state the job's error would be sent as, read through code's rule."""
    row = await jev_repo.get_failed_job(conn, job_id)
    assert row is not None
    tokens = jev_chips.residue_skeleton(row["kind"], row["error"])
    assert tokens is not None, row["kind"]
    return OPS.dump_state(
        jev_questions.JobErrorState(job_kind=row["kind"], error=tokens)
    )


def _address(state: dict[str, Any]) -> str:
    return jev_questions.job_error_subject(
        jev_questions.JobErrorState(
            job_kind=state["job_kind"], error=tuple(state["error"])
        )
    )


async def _payload(conn: asyncpg.Connection, key: str) -> dict[str, Any]:
    raw = await conn.fetchval("SELECT payload FROM jobs WHERE dedupe_key = $1", key)
    return json.loads(raw) if isinstance(raw, str) else dict(raw)


def _ops_asks(planned: list[str]) -> list[str]:
    return [key for key in planned if key.startswith(f"jev_ask:{OPS.name}@")]


async def _db_now(conn: asyncpg.Connection) -> datetime:
    return await conn.fetchval("SELECT now()")


def _sent(vendor: _Vendor) -> list[dict[str, Any]]:
    """The states of the calls the vendor saw about a job's error."""
    return [call["state"] for call in vendor.calls if "error" in call["state"]]


# ---------------------------------------------------------------------------
# The canary
# ---------------------------------------------------------------------------


class TestTheCanary:
    async def test_each_marker_is_in_its_own_jobs_column_and_nowhere_else(
        self,
        db: tuple[str, asyncpg.Connection],
        monkeypatch: pytest.MonkeyPatch,
        vendor: _Vendor,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """
        docs/09, section 13, and design M8: what leaves about a failed job is
        its kind and its error's skeleton, recorded as the state asked about;
        the error itself, and the job's payload and result, stay in the job's
        own row, read from ``information_schema``; and nothing is logged at
        DEBUG, carried by another job, or seen by the vendor.
        """
        dsn, conn = db
        names = ("left", "other", "placed", "short", "untriaged")
        markers = {name: _token() for name in (*names, "payload", "result")}
        at = await _db_now(conn) - timedelta(hours=1)
        planted: dict[str, tuple[uuid.UUID, str]] = {}
        for n, name in enumerate(names):
            job_id = await _failed(
                conn,
                name,
                at - timedelta(minutes=n),
                fill=markers[name],
                payload={"invented": markers["payload"]} if name == "left" else None,
                result={"invented": markers["result"]} if name == "left" else None,
            )
            planted[name] = (job_id, "error")
            if name == "left":
                planted["payload"] = (job_id, "payload")
                planted["result"] = (job_id, "result")
        states = [await _state(conn, planted[name][0]) for name in ("left", "other")]
        caplog.clear()
        caplog.set_level(logging.DEBUG)
        await _loop(monkeypatch, dsn)

        for name, marker in markers.items():
            assert await _columns_holding(conn, marker) == {
                f"jobs.{planted[name][1]}": 1
            }, name
        for job in await conn.fetch("SELECT * FROM jobs"):
            for field in ("payload", "result", "error"):
                written = json.dumps(job[field], default=str)
                for name, marker in markers.items():
                    if marker in written:
                        assert (job["id"], field) == planted[name], (name, field)
        asks = await conn.fetch(
            "SELECT status, error FROM jobs WHERE kind = 'jev_ask' ORDER BY created_at"
        )
        assert [job["status"] for job in asks] == ["succeeded"] * 2, [
            job["error"] for job in asks
        ]
        assert sorted(_sent(vendor), key=json.dumps) == sorted(states, key=json.dumps)
        recorded = await conn.fetch(
            "SELECT state FROM jev_requests WHERE question_set = $1", OPS.name
        )
        assert sorted(
            (json.loads(row["state"]) for row in recorded), key=json.dumps
        ) == (sorted(states, key=json.dumps))
        seen = json.dumps(vendor.calls, default=str)
        for marker in markers.values():
            assert marker not in seen
            assert _logged(caplog.records, marker) == []
        assert any(
            record.name == "src.programme.jev_plan" for record in caplog.records
        ), "the planner's own log line was not captured, so the scan read nothing"


# ---------------------------------------------------------------------------
# Only what code leaves to Jev is asked about
# ---------------------------------------------------------------------------


class TestOnlyWhatCodeLeavesToJevIsAsked:
    async def test_each_skeleton_once_by_its_newest_job_and_replayed(
        self, db: tuple[str, asyncpg.Connection], vendor: _Vendor
    ) -> None:
        """
        docs/09, sections 5.2 and 5.3: of the failed jobs of a triaged kind
        that finished within the week and after the midnight following the
        pin's first observation, each skeleton code leaves to Jev, long
        enough to ask about, is asked once, by its newest job, and planned
        again on no later day; nothing else is. Asked again by the older job
        of the same skeleton, it is replayed from its row, with no call.
        """
        dsn, conn = db
        newest = await _failed(conn, "left", NOW - timedelta(hours=1))
        older = await _failed(conn, "left", NOW - timedelta(hours=5))
        other = await _failed(conn, "other", NOW - timedelta(hours=2))
        for name in ("placed", "short", "untriaged"):
            await _failed(conn, name, NOW - timedelta(hours=3))
        # The population starts at the midnight after the pin's first day.
        await _failed(conn, "third", datetime(2026, 9, 26, 23, 59, tzinfo=UTC))
        # An expired lease leaves no finish time.
        await _failed(conn, "third", None, started_at=NOW - timedelta(hours=1))
        expected = [await _state(conn, newest), await _state(conn, other)]
        assert expected[0] == await _state(conn, older)

        planned = await _plan_and_drain(conn, dsn, NOW)
        payloads = [await _payload(conn, key) for key in _ops_asks(planned)]
        assert [(p["subject_id"], p["source_id"]) for p in payloads] == [
            (_address(expected[0]), str(newest)),
            (_address(expected[1]), str(other)),
        ]
        assert _sent(vendor) == expected
        asked = await conn.fetch(
            "SELECT subject_type, subject_id, lane, provenance, status "
            "FROM jev_requests WHERE question_set = $1 ORDER BY id",
            OPS.name,
        )
        assert [tuple(row) for row in asked] == [
            ("job_error", _address(state), "ops", "system", "ok") for state in expected
        ]

        planned = await _plan_and_drain(conn, dsn, NOW + timedelta(days=1))
        assert _ops_asks(planned) == [], "a skeleton answered was planned again"
        calls = len(vendor.calls)
        replayed = await jev_jobs.run_ask(
            conn, {**payloads[0], "source_id": str(older)}, KEY
        )
        assert replayed["replayed"] is True and replayed["status"] == "ok"
        assert len(vendor.calls) == calls, "the replay made a call"

    async def test_a_job_older_than_the_week_is_not_read(
        self, db: tuple[str, asyncpg.Connection], vendor: _Vendor
    ) -> None:
        """The rule reads a week back from its clock (``jev_plan.OPS_WINDOW``)."""
        dsn, conn = db
        later = datetime(2026, 10, 20, 15, tzinfo=UTC)
        await _failed(conn, "left", later - jev_plan.OPS_WINDOW)
        inside = await _failed(
            conn, "other", later - jev_plan.OPS_WINDOW + timedelta(seconds=1)
        )
        planned = await _plan_and_drain(conn, dsn, later)
        payloads = [await _payload(conn, key) for key in _ops_asks(planned)]
        assert [p["source_id"] for p in payloads] == [str(inside)]
        assert _sent(vendor) == [await _state(conn, inside)]


# ---------------------------------------------------------------------------
# Nothing an answer says changes anything
# ---------------------------------------------------------------------------

#: How a call can come out, as the research tests' vendor makes each.
OUTCOMES = (
    "answered",
    "timeout",
    "invalid",
    "content_block",
    "invalid_request",
    "auth",
)


async def _snapshot(
    conn: asyncpg.Connection, jobs: list[uuid.UUID]
) -> dict[str, list[dict[str, Any]]]:
    """The failed jobs and the programme's own rows, every column."""
    taken = {
        "jobs": [
            dict(row)
            for row in await conn.fetch(
                "SELECT * FROM jobs WHERE id = ANY($1::uuid[]) ORDER BY id", jobs
            )
        ]
    }
    for table, order in (
        ("findings", "ref"),
        ("hypotheses", "ref"),
        ("candidates", "id"),
        ("role_assessments", "id"),
        ("system_flags", "key"),
    ):
        taken[table] = [
            dict(row)
            for row in await conn.fetch(f"SELECT * FROM {table} ORDER BY {order}")
        ]
    return taken


class TestAJobIsUnchangedByEveryOutcome:
    @pytest.mark.parametrize("outcome", OUTCOMES)
    async def test_the_job_and_the_register_are_what_they_were(
        self,
        db: tuple[str, asyncpg.Connection],
        monkeypatch: pytest.MonkeyPatch,
        vendor: _Vendor,
        outcome: str,
    ) -> None:
        """
        docs/09, section 6.1: an ops answer has no follow-up, so no Jev path
        changes a failed job — its status, error, attempts, result or times —
        nor a finding, a hypothesis, a candidate, an assessment or a switch,
        whatever the vendor answers or refuses.
        """
        dsn, conn = db
        at = await _db_now(conn) - timedelta(hours=1)
        job = await _failed(
            conn, "left", at, payload={"invented": 1}, result={"invented": 2}
        )
        placed = await _failed(conn, "placed", at)
        state = await _state(conn, job)
        if outcome != "answered":
            vendor.failing[_text_of(state) or ""] = outcome
        before = await _snapshot(conn, [job, placed])
        await _loop(monkeypatch, dsn)
        assert state in _sent(vendor), "the job's error was never asked about"
        assert await _snapshot(conn, [job, placed]) == before


# ---------------------------------------------------------------------------
# What preview shows is what would leave
# ---------------------------------------------------------------------------


class TestPreviewIsThePlanners:
    """
    docs/09, section 13: preview runs the planner's read and the handler's
    rules from copies, since the harness may load neither; on the same rows
    its subjects are the planner's, in order, and each state it prints is the
    one the handler hands the road.
    """

    async def _rows(self, conn: asyncpg.Connection) -> dict[str, uuid.UUID]:
        rows = {}
        for hours, name in enumerate(
            ("left", "other", "placed", "short", "untriaged", "third"), start=1
        ):
            rows[name] = await _failed(conn, name, NOW - timedelta(hours=hours))
        rows["older"] = await _failed(conn, "left", NOW - timedelta(hours=9))
        return rows

    async def test_the_subjects_and_states_are_the_planners_and_the_handlers(
        self,
        db: tuple[str, asyncpg.Connection],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _, conn = db
        rows = await self._rows(conn)
        report = await jev_eval.preview_report(
            conn,
            question_set=OPS,
            limit=jev_plan.ASKS_PER_PASS[OPS.name],
            day=NOW.date(),
            now=NOW,
        )
        assert report["would_plan"] is True, report["not_planned_because"]
        planned = await jev_plan.plan(conn, now=NOW, key_available=True)
        payloads = [await _payload(conn, key) for key in _ops_asks(planned)]
        assert len(payloads) == 3, "the planner planned the wrong skeletons"
        assert [
            (subject["subject_id"], subject["source_id"])
            for subject in report["subjects"]
        ] == [(p["subject_id"], p["source_id"]) for p in payloads]

        sent: list[dict[str, Any]] = []

        async def road(conn: Any, **kwargs: Any) -> jev_lane.AskResult:
            sent.append(kwargs)
            return jev_lane.AskResult("disabled")

        monkeypatch.setattr(jev_lane, "ask", road)
        for payload in payloads:
            with contextlib.suppress(JobFailedError):
                await jev_jobs.run_ask(conn, payload, KEY)
        assert [OPS.dump_state(k["state"]) for k in sent] == [
            subject["state"] for subject in report["subjects"]
        ]
        assert all(s["not_sent_because"] is None for s in report["subjects"])
        listed = {job["job_id"]: job for job in report["failed_jobs"]}
        assert set(listed) == {
            str(rows[name])
            for name in ("left", "other", "placed", "short", "third", "older")
        }, "the rule reads a triaged kind's failed jobs, and only those"
        assert (listed[str(rows["placed"])]["code_cause"]) == "code_defect"
        assert listed[str(rows["short"])]["subject_id"] is None
        assert (
            listed[str(rows["older"])]["subject_id"]
            == (listed[str(rows["left"])]["subject_id"])
        )

    async def test_the_detail_switch_off_is_named_and_nothing_is_planned(
        self, db: tuple[str, asyncpg.Connection]
    ) -> None:
        """
        docs/09, owner item 9.1, its chosen default: the ops area on with the
        detail switch off plans nothing; preview names the switch, and still
        shows what would be sent, which is what an operator reads before
        switching it on.
        """
        _, conn = db
        await flag_repo.set_flag(conn, DETAIL, False, "test")
        rows = await self._rows(conn)
        report = await jev_eval.preview_report(
            conn, question_set=OPS, limit=10, day=NOW.date(), now=NOW
        )
        assert report["would_plan"] is False
        assert report["not_planned_because"] == ["jev_send_internal_detail is off"]
        assert [s["source_id"] for s in report["subjects"]] == [
            str(rows[name]) for name in ("left", "other", "third")
        ]
        planned = await jev_plan.plan(conn, now=NOW, key_available=True)
        assert _ops_asks(planned) == [], "planned with the detail switch off"


# ---------------------------------------------------------------------------
# Suggestions show how each ask came out, and no answer
# ---------------------------------------------------------------------------


class TestSuggestionsOnPostgres:
    async def test_statuses_from_a_ledger_the_shipped_jobs_wrote(
        self,
        db: tuple[str, asyncpg.Connection],
        monkeypatch: pytest.MonkeyPatch,
        vendor: _Vendor,
    ) -> None:
        dsn, conn = db
        now = await _db_now(conn)
        marker = _token()
        ids = {
            "newest": await _failed(conn, "left", now - timedelta(hours=1)),
            "older": await _failed(conn, "left", now - timedelta(hours=2)),
            "placed": await _failed(conn, "placed", now - timedelta(hours=3)),
            "short": await _failed(conn, "short", now - timedelta(hours=4)),
            "untriaged": await _failed(conn, "untriaged", now - timedelta(hours=5)),
            # An expired lease after an attempt that wrote its error: of the
            # skeleton asked about, and of one nobody asked about.
            "lease_asked": await _failed(
                conn, "left", None, started_at=now - timedelta(hours=6)
            ),
            "lease_alone": await _failed(
                conn,
                "third",
                None,
                fill=marker,
                started_at=now - timedelta(hours=7),
            ),
        }
        await _loop(monkeypatch, dsn)

        report = await jev_eval.suggestions_report(conn)
        jobs = {job["job_id"]: job for job in report["failed_jobs"]}
        assert set(jobs) == {str(job_id) for job_id in ids.values()}
        statuses = {name: jobs[str(ids[name])]["asks"][OPS.name] for name in ids}
        assert statuses == {
            "newest": "answered",
            "older": "answered",
            "placed": "not asked: code places its error",
            "short": "not asked: too few words of the vocabulary to ask about",
            "untriaged": "not asked: code alone places this kind's errors",
            "lease_asked": "answered",
            "lease_alone": "not asked: no finish time, so the planner does not read it",
        }
        codes = {name: (jobs[str(ids[name])]["code"]) for name in ids}
        assert codes["placed"] == "code_defect"
        assert codes["untriaged"] == "unclassified"
        assert {codes[name] for name in ("newest", "short", "lease_alone")} == {
            "left to Jev"
        }
        shown = json.dumps(report) + jev_eval.format_suggestions(report)
        for word in (marker, "Errno", "errno", "nvented", "[word]", "backtest run"):
            assert word not in shown, word
        assert report["switches"][DETAIL] is True
        assert report["holds"][f"{OPS.name} refused under the pin"] is False
