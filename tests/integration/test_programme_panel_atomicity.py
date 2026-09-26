"""
test_programme_panel_atomicity.py
---------------------------------
A role's view and its findings reach the ledger together or not at all.

``tick._convene`` counts a role as heard once its ``role_assessments`` row
exists, and never asks a heard role again. The view and each finding it raised
used to be separate autocommit statements, so a failure between them — a clash
on ``findings.ref``, whose next value is ``COUNT(*) + 1`` and collides when two
runners overlap — left the role heard and its objection nowhere. The next pass
skipped it, the gate found nothing blocking, and a veto role's critical finding
was lost to an automatic promotion.

The unit suite proves the runner's logic against a fake that rolls back. What a
fake cannot prove is the rollback itself, so this drives the shipped ``_advance``
against Postgres: a real unique violation inside the real transaction, the rows
it does and does not leave behind, and then the next pass. It runs twice — on a
connection of its own, which is how the runner holds one, and inside a caller's
transaction, where the role's block is a savepoint and the caller's writes must
survive it.

    createdb trader_test
    TEST_DATABASE_URL=postgresql://localhost/trader_test \\
        pytest tests/integration/test_programme_panel_atomicity.py
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import date, timedelta
from typing import Any

import pytest

pytest.importorskip("asyncpg")

import asyncpg  # noqa: E402

from src.programme import models, panel, repo, tick  # noqa: E402
from src.programme.gates import (  # noqa: E402
    MIN_BARS_PER_SYMBOL,
    REQUIRED_CARD_FIELDS,
    evaluate,
)
from src.programme.roles import (  # noqa: E402
    Assessment,
    ProposedFinding,
    Role,
    roles_for_stage,
)

TEST_DSN = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DSN,
    reason="TEST_DATABASE_URL not set; skipping panel atomicity tests",
)

API_KEY = "sk-test-not-a-real-key"

SETTINGS = models.build_settings(
    models.ANTHROPIC,
    models.DEFAULT_MODEL,
    models.DEFAULT_EFFORT,
    models.DEFAULT_MAX_TOKENS,
)

#: A symbol no other fixture uses, so the bars seeded here are this file's own.
SYMBOL = "PANELATOM"
SOURCE = "test"
START = date(2023, 1, 2)
END = date(2023, 12, 29)

#: Stage 0 summons a veto role, which is what makes a lost finding matter.
VETO_ROLE = "data_engineering"


@pytest.fixture(scope="module", autouse=True)
def migrated() -> None:
    from src.db.migrate import migrate

    asyncio.run(migrate(TEST_DSN))


async def _seed_candidate(conn: asyncpg.Connection) -> str:
    """A stage-0 candidate whose gate passes, so only the panel can stop it."""
    hyp_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO hypotheses (id, ref, title, owner, card) "
        "VALUES ($1,$2,'Panel atomicity fixture','test',$3::jsonb)",
        hyp_id,
        f"H-ATOM-{uuid.uuid4().hex[:8]}",
        json.dumps({name: "stated for the fixture" for name in REQUIRED_CARD_FIELDS}),
    )
    day, seeded = START, 0
    while seeded < MIN_BARS_PER_SYMBOL + 5:
        if day.weekday() < 5:
            await conn.execute(
                """
                INSERT INTO daily_bars (symbol, session, source, open, high,
                    low, close, volume, adj_close)
                VALUES ($1,$2,$3,100,101,99,100,1000000,100)
                ON CONFLICT DO NOTHING
                """,
                SYMBOL,
                day,
                SOURCE,
            )
            seeded += 1
        day += timedelta(days=1)
    return await repo.create_candidate(
        conn,
        hypothesis_id=str(hyp_id),
        strategy_name="buy_and_hold",
        params={"symbols": [SYMBOL]},
        universe=[SYMBOL],
        start_session=START,
        end_session=END,
        data_source="yfinance",
    )


async def _taken_ref(conn: asyncpg.Connection) -> str:
    """
    Open a programme-wide finding and return its reference.

    Programme-wide — no candidate — so it blocks nothing here. It exists only
    to be the reference another runner took first.
    """
    ref = f"F-ATOM-{uuid.uuid4().hex[:8]}"
    await conn.execute(
        "INSERT INTO findings (id, ref, candidate_id, raised_by, severity, title) "
        "VALUES ($1,$2,NULL,'operations','low','fixture: a reference already taken')",
        uuid.uuid4(),
        ref,
    )
    return ref


def _veto() -> Assessment:
    return Assessment(
        verdict="object",
        summary="The universe is selected after the fact; the result is survivors.",
        findings=[
            ProposedFinding(
                severity="critical",
                title="the universe excludes delisted instruments",
                detail="Every symbol still trades today, so this measures "
                "survivors and not the stated mechanism.",
                remediation="Rebuild the universe from point-in-time membership.",
            )
        ],
    )


def _actions(report: tick.TickReport, action: str) -> list[dict[str, Any]]:
    return [a for a in report.actions if a["action"] == action]


async def _heard(conn: asyncpg.Connection, candidate_id: str) -> set[str]:
    rows = await conn.fetch(
        "SELECT role FROM role_assessments WHERE candidate_id = $1",
        uuid.UUID(candidate_id),
    )
    return {r["role"] for r in rows}


async def _findings(conn: asyncpg.Connection, candidate_id: str) -> list[tuple]:
    rows = await conn.fetch(
        "SELECT raised_by, severity, status FROM findings WHERE candidate_id = $1",
        uuid.UUID(candidate_id),
    )
    return [(r["raised_by"], r["severity"], r["status"]) for r in rows]


@pytest.mark.parametrize(
    "inside_a_transaction",
    [False, True],
    ids=["own_connection", "inside_a_callers_transaction"],
)
async def test_a_finding_that_fails_to_write_takes_its_view_with_it(
    monkeypatch: pytest.MonkeyPatch, inside_a_transaction: bool
) -> None:
    asked: list[str] = []

    async def assess(role: Role, *args: Any) -> Assessment:
        asked.append(role.key)
        if role.key == VETO_ROLE:
            return _veto()
        return Assessment(verdict="support", summary="The card names a mechanism.")

    monkeypatch.setattr(panel, "assess", assess)

    # Another runner takes the reference between this one's COUNT and its
    # INSERT. Postgres then refuses the finding exactly as it would in
    # production; only the timing is arranged.
    clash: dict[str, str | None] = {"ref": None}
    next_ref = repo._next_ref

    async def overlapping(conn: asyncpg.Connection, table: str, prefix: str) -> str:
        if table == "findings" and clash["ref"]:
            return clash["ref"]
        return await next_ref(conn, table, prefix)

    monkeypatch.setattr(repo, "_next_ref", overlapping)

    conn = await asyncpg.connect(TEST_DSN)
    outer = conn.transaction() if inside_a_transaction else None
    candidate_id = taken = ""
    try:
        if outer is not None:
            await outer.start()
        candidate_id = await _seed_candidate(conn)
        clash["ref"] = taken = await _taken_ref(conn)
        facts = await repo.load_facts(conn, candidate_id)
        assert facts is not None
        assert evaluate(facts).passed, "the control: without a finding it promotes"

        # Pass one: the veto role objects and its finding is refused.
        first = tick.TickReport()
        candidate = await repo.get_candidate(conn, candidate_id)
        await tick._advance(conn, candidate, first, 1, API_KEY, SETTINGS)

        assert await _findings(conn, candidate_id) == []
        assert await _heard(conn, candidate_id) == {
            role.key for role in roles_for_stage(0)
        } - {VETO_ROLE}, "the view went with its finding; the others stayed"
        assert (await repo.get_candidate(conn, candidate_id))["stage"] == 0
        (unrecorded,) = _actions(first, "assessment_unrecorded")
        assert unrecorded["role"] == VETO_ROLE
        (held,) = _actions(first, "promotion_withheld")
        assert VETO_ROLE in held["reason"]

        # Pass two: the reference is free. Only the lost role is asked, its
        # finding opens, and the real gate refuses on it.
        clash["ref"] = None
        asked.clear()
        second = tick.TickReport()
        candidate = await repo.get_candidate(conn, candidate_id)
        await tick._advance(conn, candidate, second, 1, API_KEY, SETTINGS)

        assert asked == [VETO_ROLE]
        assert await _findings(conn, candidate_id) == [(VETO_ROLE, "critical", "open")]
        assert (await repo.get_candidate(conn, candidate_id))["stage"] == 0
        # The gate passed on the first pass and the panel's hold withheld it;
        # on the second the gate itself refused, on the veto.
        evaluations = await conn.fetch(
            "SELECT passed, promoted FROM gate_evaluations "
            "WHERE candidate_id = $1 ORDER BY id",
            uuid.UUID(candidate_id),
        )
        assert [(r["passed"], r["promoted"]) for r in evaluations] == [
            (True, False),
            (False, False),
        ]
    finally:
        if outer is not None:
            await outer.rollback()
        else:
            # Deleting the candidate cascades to its views, findings and
            # evaluations. The hypothesis stays: the ledger refuses deletes,
            # which is its point.
            if candidate_id:
                await conn.execute(
                    "DELETE FROM candidates WHERE id = $1", uuid.UUID(candidate_id)
                )
            if taken:
                await conn.execute("DELETE FROM findings WHERE ref = $1", taken)
            await conn.execute(
                "DELETE FROM daily_bars WHERE symbol = $1 AND source = $2",
                SYMBOL,
                SOURCE,
            )
        await conn.close()
