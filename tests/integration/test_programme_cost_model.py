"""
test_programme_cost_model.py
----------------------------
Every run the programme queues records the whole cost model it is run under.

The programme queued its backtests with a stress multiplier and nothing else.
The worker filled in 5 bps of slippage, a 25-dollar minimum trade and no
concentration cap, and none of it was written down, so the backtest page could
only say the slippage was missing — and every figure the programme's gates
promote on was quoted without the cost assumption it was produced under
(CLAUDE.md: never quote a performance figure without its cost assumption). Its
walk-forward experiments recorded no cost at all.

Driven through ``tick._enqueue_backtest`` and ``tick._enqueue_walkforward``, the
functions a pass calls, against real Postgres; read back from the rows and
through the API, which is where the page reads them. That the recorded values
are the ones the worker applies is ``tests/unit/test_cost_model_record.py``.

    TEST_DATABASE_URL=postgresql://localhost/trader_test \
        pytest tests/integration/test_programme_cost_model.py
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import date

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("asyncpg")

import asyncpg  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api.security import hash_password  # noqa: E402

TEST_DSN = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DSN,
    reason="TEST_DATABASE_URL not set; skipping programme integration tests",
)

PASSWORD = "test-password-123"

CARD = {
    "economic_mechanism": "slow institutional rebalancing",
    "why_it_persists": "mandated bands force the other side",
    "instruments": "asset-class ETFs",
    "trading_horizon": "monthly",
    "entry_exit_concept": "hold above the long average, cash below",
    "expected_return_source": "a premium for bearing rebalancing pressure",
    "expected_risks": "whipsaw in range-bound regimes",
    "expected_turnover": "roughly twelve rebalances a year",
    "expected_capacity": "constrained by ETF depth",
    "data_requirements": "daily adjusted closes",
    "alternative_explanations": "disguised equity beta",
    "simplest_baseline": "equal-weight buy and hold",
    "falsification_test": "permute the signal and the edge should vanish",
    "acceptance_criteria": "sharpe >= 0.3",
    "rejection_criteria": "sharpe < 0",
    "limitations": "universe listed from 2006",
}

#: The kinds ``_enqueue_backtest`` answers, each with its own configuration.
BACKTEST_KINDS = (
    "backtest",
    "cost_stress",
    "parameter_neighbourhood",
    "benchmark",
    "replication",
)


@pytest.fixture(scope="module")
def client():
    from src.config import get_settings
    from src.db.migrate import migrate

    os.environ["DATABASE_URL"] = TEST_DSN
    os.environ["SESSION_SECRET"] = "a" * 48
    os.environ["ADMIN_PASSWORD_HASH"] = hash_password(PASSWORD)
    get_settings.cache_clear()

    asyncio.run(migrate(TEST_DSN))

    from src.api.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def authed(client):
    assert (
        client.post("/api/v1/auth/login", json={"password": PASSWORD}).status_code
        == 200
    )
    return client


def _run(coro):
    return asyncio.run(coro)


async def _with_conn(fn):
    conn = await asyncpg.connect(TEST_DSN)
    try:
        return await fn(conn)
    finally:
        await conn.close()


def _candidate(authed) -> str:
    """
    A candidate on real-data terms, so the walk-forward is not refused.

    Its concentration cap is set below one because the neighbourhood run
    nudges every numeric parameter by 1.2, and a cap of 1.0 becomes 1.2, which
    the strategy refuses: at the default cap the programme cannot queue that
    experiment at all. That is a defect of its own, reported rather than fixed
    here; this file is about what a queued run records.
    """
    hypothesis = authed.post(
        "/api/v1/programme/hypotheses",
        json={"title": "Costs recorded in full", "owner": "test", "card": CARD},
    ).json()
    response = authed.post(
        "/api/v1/programme/candidates",
        json={
            "hypothesis_ref": hypothesis["ref"],
            "strategy": "asset_class_trend_following",
            "params": {"sma_period": 150, "max_weight_per_asset": 0.5},
            "start_session": "2010-01-04",
            "end_session": "2015-12-31",
            "data_source": "yfinance",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["candidate_id"]


async def _unqueue(conn, experiment_ref: str) -> None:
    """
    Take the experiment's job back off the shared queue.

    Nothing here runs a job, and the database is the whole suite's: a queued
    real-data backtest left behind is claimed by the next test that drains the
    queue, fails for want of a data host, and leaves that test's own job
    unrun.
    """
    await conn.execute(
        "DELETE FROM jobs WHERE id = (SELECT job_id FROM experiments WHERE ref = $1)",
        experiment_ref,
    )


def _enqueue(candidate_id: str, kind: str) -> dict:
    """One ``_enqueue_backtest`` call, and the two rows it wrote."""
    from src.programme import repo, tick

    async def go(conn):
        candidate = await repo.get_candidate(conn, candidate_id)
        report = tick.TickReport()
        await tick._enqueue_backtest(conn, candidate, kind, report)
        (queued,) = [a for a in report.actions if a["action"] == "experiment_queued"]
        await _unqueue(conn, queued["experiment"])
        experiment = await conn.fetchrow(
            "SELECT cost_assumptions, backtest_run_id FROM experiments WHERE ref = $1",
            queued["experiment"],
        )
        run = await conn.fetchrow(
            "SELECT id, cost_model FROM backtest_runs WHERE id = $1",
            experiment["backtest_run_id"],
        )
        return {
            "run_id": str(run["id"]),
            "run": json.loads(run["cost_model"]),
            "experiment": json.loads(experiment["cost_assumptions"]),
        }

    return _run(_with_conn(go))


class TestTheProgrammeRecordsTheWholeCostModel:
    @pytest.mark.parametrize("kind", BACKTEST_KINDS)
    def test_every_backtest_it_queues_records_every_cost(self, authed, kind) -> None:
        from src.db.repos.backtests import DEFAULT_COST_MODEL
        from src.programme.tick import STRESS_MULTIPLIER

        rows = _enqueue(_candidate(authed), kind)
        stress = STRESS_MULTIPLIER if kind == "cost_stress" else 1.0
        expected = {**DEFAULT_COST_MODEL, "stress_multiplier": stress}

        assert rows["run"] == expected, (
            f"a {kind} run recorded {rows['run']}; the worker applies "
            f"{expected}, and a cost it applies unrecorded is a performance "
            "figure quoted without its cost assumption"
        )
        # The experiment is the reproducibility record, and says the same.
        assert rows["experiment"] == rows["run"]

    def test_the_page_reads_a_slippage_it_can_quote(self, authed) -> None:
        """
        What ``MetricsPanel`` reads: `run.cost_model.slippage_bps`, a number,
        where for these runs it found nothing and had to say "missing".
        """
        rows = _enqueue(_candidate(authed), "backtest")
        run = authed.get(f"/api/v1/backtests/{rows['run_id']}").json()
        assert run["cost_model"]["slippage_bps"] == 5.0
        assert run["cost_model"]["min_trade_usd"] == 25.0
        assert run["cost_model"]["max_weight_per_asset"] == 1.0

    def test_its_walkforward_records_the_cost_model_the_study_applies(
        self, authed
    ) -> None:
        from src.db.repos.backtests import complete_cost_model
        from src.programme import repo, tick

        candidate_id = _candidate(authed)
        rows = _enqueue(candidate_id, "backtest")

        async def go(conn):
            # The study needs a succeeded backtest to be attached to.
            await conn.execute(
                "UPDATE backtest_runs SET status = 'succeeded' WHERE id = $1",
                uuid.UUID(rows["run_id"]),
            )
            candidate = await repo.get_candidate(conn, candidate_id)
            report = tick.TickReport()
            await tick._enqueue_walkforward(conn, candidate, report)
            (queued,) = [
                a for a in report.actions if a["action"] == "walkforward_queued"
            ]
            await _unqueue(conn, queued["experiment"])
            return json.loads(
                await conn.fetchval(
                    "SELECT cost_assumptions FROM experiments WHERE ref = $1",
                    queued["experiment"],
                )
            )

        assert _run(_with_conn(go)) == complete_cost_model(None)


class TestAStoredCostModelIsComplete:
    """``create_run`` is the one insert, so every caller gets this, not only
    the programme."""

    def _request(self, cost_model: dict):
        from src.db.repos.backtests import BacktestRequest

        return BacktestRequest(
            strategy_name="buy_and_hold",
            params={"symbols": ["SPY"]},
            universe=["SPY"],
            start_session=date(2015, 1, 2),
            end_session=date(2015, 12, 31),
            initial_cash=100000.0,
            data_source="synthetic",
            cost_model=cost_model,
        )

    def test_a_partial_model_is_stored_whole(self, client) -> None:
        from src.db.repos import backtests

        async def go(conn):
            run_id = await backtests.create_run(
                conn, self._request({"slippage_bps": 0.0})
            )
            return (await backtests.get_run(conn, run_id))["cost_model"]

        assert _run(_with_conn(go)) == {
            **backtests.DEFAULT_COST_MODEL,
            # A recorded zero is a choice, and stays one.
            "slippage_bps": 0.0,
        }

    def test_a_cost_the_worker_would_ignore_is_refused_and_nothing_stored(
        self, client
    ) -> None:
        from src.db.repos import backtests

        async def go(conn):
            before = await conn.fetchval("SELECT COUNT(*) FROM backtest_runs")
            with pytest.raises(backtests.UnknownCostKeyError):
                await backtests.create_run(
                    conn, self._request({"commission_pct": 0.001})
                )
            return before, await conn.fetchval("SELECT COUNT(*) FROM backtest_runs")

        before, after = _run(_with_conn(go))
        assert after == before
