"""
test_shadow.py
--------------
Shadow mode, end to end, against a real database.

The claims worth testing are structural rather than numerical, because nothing
about twenty sessions of a hypothetical book says anything about a strategy:

* No order exists. A shadow session decides and records; the ``orders`` table
  stays empty and the deployment stays disabled, so the live loop can never
  pick it up.
* The book is derived from the log, not stored. Running the same session twice
  must produce the same book, and it does because it is rebuilt each time.
* Decision lag holds. Intents recorded against session S fill at S+1's open,
  by the same ``execute_pending`` a backtest uses.
* The schedule is the shadow's own. ``last_rebalance`` is read from the shadow
  log, not from the deployment, whose schedule belongs to a live run that is
  not happening.

    createdb trader_test
    TEST_DATABASE_URL=postgresql://localhost/trader_test \\
        pytest tests/integration/test_shadow.py
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

pytest.importorskip("asyncpg")

import asyncpg  # noqa: E402

from src.programme.repo import SHADOW_RISK_LIMITS  # noqa: E402

TEST_DSN = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DSN,
    reason="TEST_DATABASE_URL not set; skipping shadow integration tests",
)

SYMBOLS = ("SPY", "IEF")
FIRST = date(2024, 1, 2)
SESSIONS = 40


def _run(coro):
    return asyncio.run(coro)


async def _with_conn(fn):
    conn = await asyncpg.connect(TEST_DSN)
    try:
        return await fn(conn)
    finally:
        await conn.close()


@pytest.fixture(scope="module", autouse=True)
def migrated():
    from src.db.migrate import migrate

    os.environ["DATABASE_URL"] = TEST_DSN
    asyncio.run(migrate(TEST_DSN))


def _sessions() -> list[date]:
    """Weekday sessions, which is close enough for a fixture with no holidays."""
    out: list[date] = []
    day = FIRST
    while len(out) < SESSIONS:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


async def _seed_bars(conn) -> list[date]:
    """A gently trending series, enough for a short moving average to exist."""
    sessions = _sessions()
    for index, session in enumerate(sessions):
        for offset, symbol in enumerate(SYMBOLS):
            price = Decimal("100") + Decimal(index) + Decimal(offset * 10)
            await conn.execute(
                """
                INSERT INTO daily_bars (symbol, session, source, open, high,
                    low, close, volume, adj_close)
                VALUES ($1,$2,'test',$3,$4,$5,$6,1000000,$6)
                ON CONFLICT DO NOTHING
                """,
                symbol,
                session,
                price,
                price + 1,
                price - 1,
                price,
            )
    return sessions


async def _seed_candidate(conn) -> tuple[str, uuid.UUID]:
    """A candidate at stage 3 with a disabled deployment, as promotion creates."""
    hyp_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO hypotheses (id, ref, title, owner, card) "
        "VALUES ($1,$2,'Shadow fixture','test','{}'::jsonb)",
        hyp_id,
        f"H-SHADOW-{uuid.uuid4().hex[:8]}",
    )
    run_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO backtest_runs (id, strategy_name, params, universe,
            start_session, end_session, initial_cash, data_source, cost_model,
            status)
        VALUES ($1,'buy_and_hold','{"symbols":["SPY","IEF"]}'::jsonb,$2,$3,$4,
                100000,'test','{}'::jsonb,'succeeded')
        """,
        run_id,
        list(SYMBOLS),
        FIRST,
        FIRST + timedelta(days=60),
    )
    deployment_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO deployments (id, owner_id, strategy_name, params, mode,
            capital_usd, risk_limits, approved_backtest_run_id, status)
        VALUES ($1,'programme','buy_and_hold',
                '{"symbols":["SPY","IEF"]}'::jsonb,
                'paper',0,$3::jsonb,$2,'disabled')
        """,
        deployment_id,
        run_id,
        # Exactly what `repo.ensure_shadow_deployment` writes. Without the cash
        # buffer every buy is trimmed to fit and gate 3 -> 4 refuses the
        # candidate, which is the gate reporting a real divergence rather than
        # a threshold set too tight.
        json.dumps(SHADOW_RISK_LIMITS),
    )
    candidate_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO candidates (id, hypothesis_id, strategy_name, params,
            universe, start_session, end_session, data_source, stage,
            deployment_id)
        VALUES ($1,$2,'buy_and_hold',
                '{"symbols":["SPY","IEF"]}'::jsonb,
                $3,$4,$5,'test',3,$6)
        """,
        candidate_id,
        hyp_id,
        list(SYMBOLS),
        FIRST,
        FIRST + timedelta(days=60),
        deployment_id,
    )
    return str(candidate_id), deployment_id


@pytest.fixture(scope="module")
def fixture():
    async def build(conn):
        sessions = await _seed_bars(conn)
        candidate_id, deployment_id = await _seed_candidate(conn)
        return sessions, candidate_id, deployment_id

    return _run(_with_conn(build))


def _shadow(candidate_id: str, session: date) -> dict:
    from src.worker.shadow_job import run_shadow_decision

    async def go(conn):
        return await run_shadow_decision(
            conn, {"candidate_id": candidate_id, "session": session.isoformat()}
        )

    return _run(_with_conn(go))


class TestAShadowSessionSubmitsNothing:
    def test_it_records_a_decision(self, fixture) -> None:
        sessions, candidate_id, _ = fixture
        result = _shadow(candidate_id, sessions[10])
        assert result["error"] is None
        assert result["session"] == sessions[10].isoformat()

    def test_no_order_is_created(self, fixture) -> None:
        """
        The whole point of stage 3. `dry_run` submits nothing, and this asserts
        it against the table rather than trusting the docstring.
        """
        sessions, candidate_id, _ = fixture
        _shadow(candidate_id, sessions[11])

        async def count(conn):
            return await conn.fetchval("SELECT COUNT(*) FROM orders")

        assert _run(_with_conn(count)) == 0

    def test_the_deployment_stays_disabled(self, fixture) -> None:
        """
        `_enabled_deployments` filters on status, so a disabled row cannot be
        picked up by the live loop however long it sits there.
        """
        _, _, deployment_id = fixture

        async def status(conn):
            return await conn.fetchval(
                "SELECT status FROM deployments WHERE id = $1", deployment_id
            )

        assert _run(_with_conn(status)) == "disabled"

    def test_a_repeat_is_inert(self, fixture) -> None:
        """
        A retried job must not append a second entry for a day already
        recorded: the replay is ordered by session and would fill the same
        intents twice.
        """
        sessions, candidate_id, _ = fixture
        _shadow(candidate_id, sessions[12])
        _shadow(candidate_id, sessions[12])

        async def count(conn):
            return await conn.fetchval(
                "SELECT COUNT(*) FROM shadow_decisions "
                "WHERE candidate_id = $1 AND session = $2",
                uuid.UUID(candidate_id),
                sessions[12],
            )

        assert _run(_with_conn(count)) == 1


class TestTheBookIsDerived:
    def test_the_first_session_rebalances(self, fixture) -> None:
        """
        `last_rebalance` is read from the shadow log, which is empty at the
        start — so the schedule fires, as it would on a live first session.
        """
        sessions, candidate_id, _ = fixture
        result = _shadow(candidate_id, sessions[0])
        assert result["rebalanced"] is True
        assert result["order_intents"] > 0

    def test_it_starts_from_the_opening_balance(self, fixture) -> None:
        from src.worker.shadow_job import SHADOW_INITIAL_CASH

        sessions, candidate_id, _ = fixture
        result = _shadow(candidate_id, sessions[1])
        # Session 1 replays session 0's intents at session 1's open, so equity
        # has moved off the opening balance by the cost of crossing the spread.
        assert result["equity"] is not None
        assert result["equity"] <= float(SHADOW_INITIAL_CASH)

    def test_replaying_twice_gives_the_same_book(self, fixture) -> None:
        """
        The reconciliation, such as it is. The book is not stored, so two runs
        over the same log must agree — if they did not, the log would not
        determine the portfolio and nothing downstream could be trusted.
        """
        sessions, candidate_id, _ = fixture
        first = _shadow(candidate_id, sessions[3])
        second = _shadow(candidate_id, sessions[3])
        assert first["equity"] == second["equity"]

    def test_the_decision_lag_holds(self, fixture) -> None:
        """
        Intents recorded against S fill at S+1's open. So a session run before
        any intent has been recorded has an untouched book, and one run after
        does not.
        """
        sessions, candidate_id, _ = fixture
        from src.worker.shadow_job import SHADOW_INITIAL_CASH

        async def fresh(conn):
            await conn.execute(
                "DELETE FROM shadow_decisions WHERE candidate_id = $1",
                uuid.UUID(candidate_id),
            )

        _run(_with_conn(fresh))

        # Nothing recorded yet: the book is entirely cash.
        untouched = _shadow(candidate_id, sessions[5])
        assert untouched["equity"] == pytest.approx(float(SHADOW_INITIAL_CASH))

        # Now session 5's intents exist, so session 6 fills them at its open.
        filled = _shadow(candidate_id, sessions[6])
        assert filled["equity"] != pytest.approx(float(SHADOW_INITIAL_CASH))


class TestTheGateReadsIt:
    def test_a_short_history_does_not_pass(self, fixture) -> None:
        from src.programme.gates import evaluate
        from src.programme.repo import load_facts

        sessions, candidate_id, _ = fixture

        async def go(conn):
            await conn.execute(
                "DELETE FROM shadow_decisions WHERE candidate_id = $1",
                uuid.UUID(candidate_id),
            )
            return await load_facts(conn, candidate_id)

        facts = _run(_with_conn(go))
        result = evaluate(facts)
        assert not result.passed
        assert "shadow_sessions" in {c.id for c in result.unmet}

    def test_a_full_history_passes(self, fixture) -> None:
        from src.programme.gates import MIN_SHADOW_SESSIONS, evaluate
        from src.programme.repo import load_facts

        sessions, candidate_id, _ = fixture
        for session in sessions[:MIN_SHADOW_SESSIONS]:
            _shadow(candidate_id, session)

        async def go(conn):
            return await load_facts(conn, candidate_id)

        facts = _run(_with_conn(go))
        result = evaluate(facts)
        assert len(facts.shadow) >= MIN_SHADOW_SESSIONS
        assert result.passed, [c.as_dict() for c in result.unmet]

    def test_the_gate_does_not_need_an_operator_at_this_stage(
        self, fixture
    ) -> None:
        """Stage 4 is broker paper trading, still below the canary line."""
        from src.programme.gates import evaluate
        from src.programme.repo import load_facts

        _, candidate_id, _ = fixture

        async def go(conn):
            return await load_facts(conn, candidate_id)

        assert not evaluate(_run(_with_conn(go))).requires_human
