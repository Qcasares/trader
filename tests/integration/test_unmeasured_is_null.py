"""
test_unmeasured_is_null.py
--------------------------
The API serves a figure nobody recorded as ``null``, never as a number.

CLAUDE.md: an unmeasured metric is never zero — and never 252 either. The
backtest endpoints filled a stored result's missing keys from the response
model's defaults: 252 sessions a year, no fills, a Sharpe of 0.0 with a
standard error of 0.0, costs at 1x. The page had learnt to render "not
measured" for a missing session count and could never show it, because the API
never sent one missing. The deployment gate did the same in prose: refusing a
walk-forward study that recorded no stitched curve, it explained itself with a
Sharpe of +0.000 ± 0.000, and a study with no degradation on record was a 500.

A finished run carries every key (``PerformanceMetrics.to_dict``), so the rows
here are what an older engine or a hand-written row leaves: a result with keys
missing. Real Postgres, because the JSONB round trip is part of what is tested.

    TEST_DATABASE_URL=postgresql://localhost/trader_test \
        pytest tests/integration/test_unmeasured_is_null.py
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
    reason="TEST_DATABASE_URL not set; skipping API integration tests",
)

PASSWORD = "test-password-123"


@pytest.fixture(scope="module")
def client():
    from src.config import get_settings
    from src.db.migrate import migrate

    os.environ["DATABASE_URL"] = TEST_DSN
    os.environ["SESSION_SECRET"] = "a" * 48
    os.environ["ADMIN_PASSWORD_HASH"] = hash_password(PASSWORD)
    os.environ.pop("LIVE_TRADING_ENABLED", None)
    get_settings.cache_clear()

    asyncio.run(migrate(TEST_DSN))

    from src.api.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def authed(client):
    response = client.post("/api/v1/auth/login", json={"password": PASSWORD})
    assert response.status_code == 200
    return client


def _run(coro):
    return asyncio.run(coro)


async def _insert_run(
    metrics: dict | None,
    *,
    strategy: str = "buy_and_hold",
    params: dict | None = None,
    data_source: str = "synthetic",
) -> uuid.UUID:
    """A succeeded run whose stored result is exactly ``metrics``."""
    conn = await asyncpg.connect(TEST_DSN)
    try:
        run_id = uuid.uuid4()
        await conn.execute(
            """
            INSERT INTO backtest_runs (id, strategy_name, params, universe,
                start_session, end_session, initial_cash, data_source,
                cost_model, status, metrics)
            VALUES ($1,$2,$3::jsonb,$4,$5,$6,100000,$7,$8::jsonb,'succeeded',
                    $9::jsonb)
            """,
            run_id,
            strategy,
            json.dumps(params or {"symbols": ["SPY"]}, sort_keys=True),
            ["SPY"],
            date(2015, 1, 2),
            date(2016, 12, 30),
            data_source,
            json.dumps({"slippage_bps": 5.0, "stress_multiplier": 1.0}),
            None if metrics is None else json.dumps(metrics),
        )
        return run_id
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# The backtest endpoints
# ---------------------------------------------------------------------------


class TestAFigureNobodyRecordedIsNull:
    def test_an_empty_result_serialises_every_figure_as_null(self, authed) -> None:
        """
        Every declared field, read off the response model rather than listed
        here, so a field added later with a numeric default fails this test
        instead of joining the defaults it replaced.
        """
        from src.api.schemas import BacktestMetrics

        run_id = _run(_insert_run({}))
        metrics = authed.get(f"/api/v1/backtests/{run_id}").json()["metrics"]

        assert set(metrics) == set(BacktestMetrics.model_fields)
        invented = {key: value for key, value in metrics.items() if value is not None}
        assert not invented, (
            f"the API reported figures nobody recorded: {invented}. An "
            "unmeasured metric is never a number (CLAUDE.md)."
        )

    def test_the_two_the_page_was_waiting_for(self, authed) -> None:
        """
        The design review's finding: the page renders "not measured" for a
        missing session count, and the API sent 252; it titles the fills card
        with the run's fill count, and the API sent 0.
        """
        recorded = {
            "start": "2015-01-02",
            "end": "2016-12-30",
            "sharpe": 0.41,
            "sharpe_stderr": 0.62,
            "sharpe_is_significant": False,
            "effective_start": "2015-01-02",
            "cost_stress_multiplier": 1.0,
        }
        run_id = _run(_insert_run(recorded))
        metrics = authed.get(f"/api/v1/backtests/{run_id}").json()["metrics"]

        assert metrics["periods_per_year"] is None
        assert metrics["n_fills"] is None
        # What was recorded arrives as recorded.
        for key, value in recorded.items():
            assert metrics[key] == value, key

    def test_a_genuine_zero_stays_a_zero(self, authed) -> None:
        """The other half of the rule: a measured zero is not an absence."""
        recorded = {
            "n_fills": 0,
            "n_rebalances": 0,
            "total_return": 0.0,
            "sharpe": 0.0,
            "sharpe_stderr": 0.31,
            "sharpe_is_significant": False,
            "total_commission": 0.0,
            "periods_per_year": 365,
            "cost_stress_multiplier": 1.0,
        }
        run_id = _run(_insert_run(recorded))
        metrics = authed.get(f"/api/v1/backtests/{run_id}").json()["metrics"]
        for key, value in recorded.items():
            assert metrics[key] == value, key
            assert metrics[key] is not None, key

    def test_the_list_serves_the_same_nulls(self, authed) -> None:
        run_id = _run(_insert_run({"sharpe": 0.2, "sharpe_stderr": 0.4}))
        runs = authed.get(
            "/api/v1/backtests",
            params={"strategy": "buy_and_hold", "limit": 200},
        ).json()
        (row,) = [r for r in runs if r["id"] == str(run_id)]
        assert row["metrics"]["periods_per_year"] is None
        assert row["metrics"]["n_fills"] is None
        assert row["metrics"]["cost_stress_multiplier"] is None
        assert row["metrics"]["sharpe_is_significant"] is None

    def test_a_run_with_no_result_has_no_metrics_at_all(self, authed) -> None:
        """Unchanged, and the control for the rows above: not an empty set."""
        run_id = _run(_insert_run(None))
        assert authed.get(f"/api/v1/backtests/{run_id}").json()["metrics"] is None


# ---------------------------------------------------------------------------
# The deployment gate's refusal
# ---------------------------------------------------------------------------


class TestARefusalQuotesNothingNobodyMeasured:
    """
    ``_why_not_robust`` read the stitched Sharpe with ``.get("sharpe", 0.0)``.
    A study that stored no metrics was therefore refused with "the stitched
    out-of-sample Sharpe is +0.000 ± 0.000" — a precise-looking zero, with an
    error bar no real estimate has. The refusal was right; its reason was
    invented.
    """

    STRATEGY = "asset_class_trend_following"

    def _not_robust_study(self, sma_period: int, degradation: float | None) -> str:
        params = {"sma_period": sma_period}

        async def seed() -> uuid.UUID:
            run_id = await _insert_run(
                {}, strategy=self.STRATEGY, params=params, data_source="yfinance"
            )
            conn = await asyncpg.connect(TEST_DSN)
            try:
                await conn.execute(
                    """
                    INSERT INTO walkforward_runs (id, backtest_run_id,
                        strategy_name, params, param_grid, start_session,
                        end_session, train_months, test_months, data_source,
                        status, is_robust, degradation, n_folds)
                    VALUES ($1,$2,$3,$4::jsonb,'{}'::jsonb,$5,$6,36,12,
                            'yfinance','succeeded',FALSE,$7,4)
                    """,
                    uuid.uuid4(),
                    run_id,
                    self.STRATEGY,
                    json.dumps(params, sort_keys=True),
                    date(2015, 1, 2),
                    date(2016, 12, 30),
                    degradation,
                )
            finally:
                await conn.close()
            return run_id

        return str(_run(seed()))

    def _deploy(self, authed, sma_period: int, run_id: str):
        return authed.post(
            "/api/v1/deployments",
            json={
                "strategy": self.STRATEGY,
                "params": {"sma_period": sma_period},
                "capital_usd": 10000,
                "approved_backtest_run_id": run_id,
            },
        )

    def test_a_study_with_no_stitched_curve_is_not_quoted_as_zero(self, authed) -> None:
        run_id = self._not_robust_study(173, degradation=0.9)
        response = self._deploy(authed, 173, run_id)

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "NOT ROBUST" in detail
        assert "+0.000" not in detail and "± 0.000" not in detail, detail
        assert "was not measured" in detail, detail
        # A figure that was recorded is still quoted.
        assert "+0.900" in detail, detail

    def test_a_study_with_no_degradation_is_refused_not_crashed(self, authed) -> None:
        run_id = self._not_robust_study(174, degradation=None)
        response = self._deploy(authed, 174, run_id)

        assert response.status_code == 422, response.text
        assert "Degradation, for context, was not measured" in response.json()["detail"]
