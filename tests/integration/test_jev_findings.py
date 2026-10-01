"""
test_jev_findings.py
--------------------
Phase D2 on PostgreSQL: the findings sets asked about a finding's title,
through the programme's own loop, and the harness's two read surfaces.

The planner and the drain run as shipped; so do the handler, the lane, the
validator, the ledger and the schema. Nothing is replaced but the vendor — the
research tests' fake of ``jev_client.ask``, answering each question as they
script it. What must hold:

* **What preview shows is what would leave** (docs/09, section 13,
  ``TestPreviewIsThePlanners``): on the same rows, preview's subjects are the
  planner's, in its order, and each state it prints is the state the handler
  hands the road — for the findings sets and the two title sets alike.
* **Suggestions show how each ask came out and no answer**: on a ledger the
  shipped jobs wrote, each model-written finding reads as answered, an
  operator's and an older unnamed writer's as not asked and why, and Jev's
  findings are counted and never named; no title is printed.

Each test runs on a database of its own, derived from ``TEST_DATABASE_URL``:
the ledger and the findings register refuse DELETE. Every title is invented.
Skipped unless ``TEST_DATABASE_URL`` is set.
"""

from __future__ import annotations

import contextlib
import json
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
from src.programme import (  # noqa: E402
    flags,
    jev_client,
    jev_eval,
    jev_jobs,
    jev_lane,
    jev_plan,
    jev_questions,
)
from src.programme.job_errors import JobFailedError  # noqa: E402
from tests.integration.test_jev_research import (  # noqa: E402
    KEY,
    _loop,
    _Vendor,
)

TEST_DSN = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="TEST_DATABASE_URL not set")

FINDINGS = f"{flags.JEV_AREA_PREFIX}findings"
RESEARCH = f"{flags.JEV_AREA_PREFIX}research"
GUARDRAILS = f"{flags.JEV_AREA_PREFIX}guardrails"

#: The switches every test starts with: the programme, Jev and the findings
#: area; a test that reads the title sets switches their areas on itself.
ON: dict[str, Any] = {
    flags.PROGRAMME_ENABLED: True,
    flags.JEV_ENABLED: True,
    FINDINGS: True,
}

OWNER = jev_questions.FINDINGS_OWNER
SEVERITY = jev_questions.FINDINGS_SEVERITY

#: The sets preview reads: every title set.
PREVIEWED = (
    "findings.owner",
    "findings.severity",
    "research.hypothesis",
    "guardrail.card",
)

#: A marker planted in every title, which no output of the harness may show.
CANARY = "CANARY-77d2"

#: When the findings below were raised, unless a test says otherwise.
RAISED = datetime(2026, 9, 28, 9, tzinfo=UTC)


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
    dsn = _derived("jev_findings")
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


@pytest.fixture
def vendor(monkeypatch: pytest.MonkeyPatch) -> _Vendor:
    fake = _Vendor()
    monkeypatch.setattr(jev_client, "ask", fake.ask)
    return fake


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


async def _finding(
    conn: asyncpg.Connection,
    title: str,
    *,
    origin: str = "model",
    at: datetime = RAISED,
    raised_by: str = "independent_risk",
    severity: str = "high",
    detail: str = "",
    remediation: str = "",
) -> str:
    """
    A finding raised at ``at`` by ``origin``; returns its ref. ``'unknown'``
    is a finding raised before migration 0015 named its writer, which the
    migration's trigger refuses on a new row, so it is written with the trigger
    switched off for that statement and on again at once.
    """
    ref = f"F-{uuid.uuid4().hex[:8]}"
    async with conn.transaction():
        if origin == "unknown":
            await conn.execute(
                "ALTER TABLE findings DISABLE TRIGGER trg_findings_origin_is_known"
            )
        await conn.execute(
            """
            INSERT INTO findings (
                id, ref, raised_by, severity, title, detail_md, remediation,
                opened_at, origin
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            uuid.uuid4(),
            ref,
            raised_by,
            severity,
            title,
            detail,
            remediation,
            at,
            origin,
        )
        if origin == "unknown":
            await conn.execute(
                "ALTER TABLE findings ENABLE TRIGGER trg_findings_origin_is_known"
            )
    return ref


async def _hypothesis(
    conn: asyncpg.Connection, title: str, *, origin: str = "model", at: datetime
) -> str:
    """A hypothesis written at ``at``; returns its ref."""
    ref = f"H-{uuid.uuid4().hex[:8]}"
    await conn.execute(
        "INSERT INTO hypotheses (id, ref, title, owner, origin, created_at) "
        "VALUES ($1, $2, $3, 'programme', $4, $5)",
        uuid.uuid4(),
        ref,
        title,
        origin,
        at,
    )
    return ref


async def _jev_finding(conn: asyncpg.Connection, title: str) -> str:
    """A finding Jev raised, lawful in every respect, holding ``title``."""
    from tests.integration.test_jev_schema import _insert
    from tests.integration.test_phase_d_schema import _jev_finding_row

    row = await _jev_finding_row(conn, title=title)
    await _insert(conn, "findings", row)
    return row["ref"]


async def _register(conn: asyncpg.Connection) -> dict[str, str]:
    """
    A register: model-written findings — two holding one title, one at the
    cap — an operator's, an older unnamed writer's, one over the cap, and
    the same shapes of hypothesis title. Returns each ref by what it is.
    """
    cap = jev_questions.FINDING_TITLE_MAX_CHARS
    hold = f"Invented Fills Assumed at Prices No Venue Gave {CANARY}"
    refs = {
        "older": await _finding(conn, hold, at=RAISED),
        "newer": await _finding(conn, hold, at=RAISED + timedelta(hours=2)),
        "at_cap": await _finding(
            conn, (f"Invented Long Finding {CANARY} " * 20)[:cap], at=RAISED
        ),
        "plain": await _finding(
            conn, f"Invented Borrow Never Located {CANARY}", at=RAISED
        ),
        "operator": await _finding(
            conn, f"An Operator's Invented Finding {CANARY}", origin="operator"
        ),
        "unknown": await _finding(
            conn, f"An Invented Finding From Before {CANARY}", origin="unknown"
        ),
        "over": await _finding(conn, "O" * (cap + 1)),
    }
    for n in range(3):
        await _hypothesis(
            conn,
            f"Invented Carry in Fictional Futures {n} {CANARY}",
            at=RAISED + timedelta(minutes=n),
        )
    await _hypothesis(
        conn, f"An Operator's Invented Idea {CANARY}", origin="operator", at=RAISED
    )
    return refs


async def _payload(conn: asyncpg.Connection, key: str) -> dict[str, Any]:
    raw = await conn.fetchval("SELECT payload FROM jobs WHERE dedupe_key = $1", key)
    return json.loads(raw) if isinstance(raw, str) else dict(raw)


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

    @pytest.mark.parametrize("name", PREVIEWED)
    async def test_the_subjects_and_states_are_the_planners_and_the_handlers(
        self,
        db: tuple[str, asyncpg.Connection],
        monkeypatch: pytest.MonkeyPatch,
        name: str,
    ) -> None:
        dsn, conn = db
        for area in (RESEARCH, GUARDRAILS):
            await flag_repo.set_flag(conn, area, True, "test")
        await _register(conn)
        question_set = jev_questions.REGISTRY[name]
        now = datetime.now(UTC)

        report = await jev_eval.preview_report(
            conn,
            question_set=question_set,
            limit=jev_plan.ASKS_PER_PASS[name],
            day=now.date(),
        )
        assert report["would_plan"] is True, report["not_planned_because"]
        planned = await jev_plan.plan(conn, now=now, key_available=True)
        keys = [key for key in planned if key.startswith(f"jev_ask:{name}@")]
        payloads = [await _payload(conn, key) for key in keys]
        assert payloads, "the planner planned nothing to compare"
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
        assert [question_set.dump_state(k["state"]) for k in sent] == [
            subject["state"] for subject in report["subjects"]
        ]
        assert all(s["not_sent_because"] is None for s in report["subjects"])

    async def test_an_area_off_is_named_and_its_subjects_still_shown(
        self, db: tuple[str, asyncpg.Connection]
    ) -> None:
        """What an operator reads before switching the area on."""
        _, conn = db
        await flag_repo.set_flag(conn, FINDINGS, False, "test")
        refs = await _register(conn)
        report = await jev_eval.preview_report(
            conn, question_set=OWNER, limit=10, day=datetime.now(UTC).date()
        )
        assert report["would_plan"] is False
        assert report["not_planned_because"] == ["jev_area_findings is off"]
        shown = {subject["source_id"] for subject in report["subjects"]}
        assert shown == {refs["newer"], refs["at_cap"], refs["plain"]}
        for left_out in ("older", "operator", "unknown", "over"):
            assert refs[left_out] not in shown, left_out


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
        refs = await _register(conn)
        jev = await _jev_finding(conn, f"An Invented Finding Jev Raised {CANARY}")
        await _loop(monkeypatch, dsn)

        report = await jev_eval.suggestions_report(conn)
        statuses = {row["ref"]: row["asks"] for row in report["findings"]}
        for asked in ("newer", "at_cap", "plain"):
            assert statuses[refs[asked]] == {
                OWNER.name: "answered",
                SEVERITY.name: "answered",
            }, asked
        # The older finding holds the same title, answered once for both.
        assert statuses[refs["older"]] == statuses[refs["newer"]]
        assert set(statuses[refs["operator"]].values()) == {
            "not asked: written by an operator"
        }
        assert set(statuses[refs["unknown"]].values()) == {
            "not asked: written before migration 0015 named its writer"
        }
        assert set(statuses[refs["over"]].values()) == {
            "not asked: over the 200-character cap"
        }
        assert jev not in statuses and report["jev_findings_raised"] == 1
        shown = json.dumps(report) + jev_eval.format_suggestions(report)
        assert CANARY not in shown and jev not in shown
        calls = [vendor_call["state"] for vendor_call in vendor.calls]
        assert {state["title"] for state in calls if "title" in state} == {
            f"Invented Fills Assumed at Prices No Venue Gave {CANARY}",
            (f"Invented Long Finding {CANARY} " * 20)[
                : jev_questions.FINDING_TITLE_MAX_CHARS
            ],
            f"Invented Borrow Never Located {CANARY}",
        }, "only the population's titles were sent"
