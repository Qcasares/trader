"""
test_deployment_enable_gate.py
------------------------------
``POST /api/v1/deployments/{id}/enable`` asks the deployment gate again.

It used to flip ``status`` to ``enabled`` and check nothing. The gate lived in
``create_deployment`` alone, which only ever writes a *disabled* row, so the
check sat in front of the step that could not trade and was absent from the
one that could. Two things walk straight past a gate placed like that:

- a row that did not come through ``create``. The programme inserts its shadow
  deployments directly, under ``owner_id='programme'``, and any row can be
  written by hand;
- a row whose evidence changed after it was created — a newer walk-forward of
  the same parameters that comes back NOT ROBUST supersedes the study that
  admitted it.

Every refusal here also asserts the row is still ``disabled`` afterwards. A
4xx that had already flipped the status would be a refusal in name only.

Runs against a real PostgreSQL database of its own, derived from
``TEST_DATABASE_URL`` as the live-path suite derives ``_live``, so the enabled
rows these tests leave behind cannot be picked up by another suite's worker.
Skipped unless ``TEST_DATABASE_URL`` is set.
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
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="TEST_DATABASE_URL not set")

PASSWORD = "test-password-123"
STRATEGY = "asset_class_trend_following"
CONFIRM = {"confirm": "ENABLE DEPLOYMENT"}


def _gate_dsn() -> str:
    base, _, tail = TEST_DSN.partition("?")
    return f"{base}_enable?{tail}" if tail else f"{base}_enable"


@pytest.fixture(scope="module")
def dsn():
    from src.db.migrate import migrate

    async def setup() -> str:
        admin = await asyncpg.connect(TEST_DSN)
        # The name comes from before the query string: a Unix-socket DSN puts
        # the socket path after it, and splitting the whole URL on "/" would
        # return that instead of the database.
        name = _gate_dsn().partition("?")[0].rsplit("/", 1)[-1]
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
        await admin.execute(f'CREATE DATABASE "{name}"')
        await admin.close()
        await migrate(_gate_dsn())
        return _gate_dsn()

    return asyncio.run(setup())


@pytest.fixture(scope="module")
def client(dsn):
    from src.config import get_settings

    os.environ["DATABASE_URL"] = dsn
    os.environ["SESSION_SECRET"] = "c" * 48
    os.environ["ADMIN_PASSWORD_HASH"] = hash_password(PASSWORD)
    # The live-mode test depends on this being off, and it is the default a
    # test must never inherit a different answer for.
    os.environ.pop("LIVE_TRADING_ENABLED", None)
    get_settings.cache_clear()

    from src.api.main import create_app

    with TestClient(create_app()) as test_client:
        assert (
            test_client.post(
                "/api/v1/auth/login", json={"password": PASSWORD}
            ).status_code
            == 200
        )
        yield test_client


def _run(dsn: str, fn):
    """Run ``fn(conn)`` on a fresh connection and return its result."""

    async def go():
        conn = await asyncpg.connect(dsn)
        try:
            return await fn(conn)
        finally:
            await conn.close()

    return asyncio.run(go())


async def _backtest(
    conn, params: dict, *, status: str = "succeeded", source: str = "yfinance"
) -> uuid.UUID:
    run_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO backtest_runs (id, strategy_name, params, universe,
            start_session, end_session, initial_cash, data_source,
            cost_model, status, metrics)
        VALUES ($1,$2,$3::jsonb,$4,$5,$6,100000,$7,'{}'::jsonb,$8,'{}'::jsonb)
        """,
        run_id,
        STRATEGY,
        json.dumps(params),
        ["SPY", "IEF"],
        date(2015, 1, 1),
        date(2019, 12, 31),
        source,
        status,
    )
    return run_id


async def _walkforward(
    conn, run_id: uuid.UUID, params: dict, *, robust: bool = True
) -> uuid.UUID:
    """A completed study, with params stored sorted as the real writers do."""
    wf_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO walkforward_runs (id, backtest_run_id, strategy_name,
            params, param_grid, start_session, end_session, train_months,
            test_months, data_source, status, is_robust, degradation, n_folds)
        VALUES ($1,$2,$3,$4::jsonb,'{}'::jsonb,$5,$6,36,12,'yfinance',
                'succeeded',$7,$8,4)
        """,
        wf_id,
        run_id,
        STRATEGY,
        json.dumps(params, sort_keys=True),
        date(2015, 1, 1),
        date(2019, 12, 31),
        robust,
        0.05 if robust else 1.85,
    )
    return wf_id


async def _deployment(
    conn,
    run_id: uuid.UUID | None,
    params: dict,
    *,
    owner: str = "default",
    mode: str = "paper",
) -> str:
    """A disabled deployment written straight to the table, not via the API."""
    deployment_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO deployments (id, owner_id, strategy_name, params, mode,
            capital_usd, risk_limits, approved_backtest_run_id, status)
        VALUES ($1,$2,$3,$4::jsonb,$5,10000,'{}'::jsonb,$6,'disabled')
        """,
        deployment_id,
        owner,
        STRATEGY,
        json.dumps(params),
        mode,
        run_id,
    )
    return str(deployment_id)


def _status(dsn: str, deployment_id: str) -> str:
    return _run(
        dsn,
        lambda c: c.fetchval(
            "SELECT status FROM deployments WHERE id = $1", uuid.UUID(deployment_id)
        ),
    )


def _enable(client, deployment_id: str):
    return client.post(f"/api/v1/deployments/{deployment_id}/enable", json=CONFIRM)


class TestEnableStillWorks:
    def test_a_deployment_with_its_evidence_in_place_enables(self, client, dsn) -> None:
        """
        The control. A gate that refuses everything is not discriminating.

        The parameters are deliberately multi-key and out of sorted order.
        ``enable`` reads them back from ``jsonb``, which reorders keys, and the
        walk-forward stores them sorted; this proves the round trip still finds
        the study that ``create`` found, rather than refusing a legitimate
        deployment for a key-order difference.
        """
        params = {"symbols": ["SPY", "IEF"], "sma_period": 201, "rebalance": "monthly"}

        async def seed(conn):
            run_id = await _backtest(conn, params)
            await _walkforward(conn, run_id, params)
            return run_id

        run_id = _run(dsn, seed)
        created = client.post(
            "/api/v1/deployments",
            json={
                "strategy": STRATEGY,
                "params": params,
                "capital_usd": 10000,
                "approved_backtest_run_id": str(run_id),
            },
        )
        assert created.status_code == 201, created.text
        deployment_id = created.json()["id"]
        assert created.json()["status"] == "disabled"

        response = _enable(client, deployment_id)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "enabled"
        assert _status(dsn, deployment_id) == "enabled"


class TestEnableAsksTheGate:
    def test_a_row_with_no_approved_backtest_is_refused(self, client, dsn) -> None:
        """
        Written by hand with no backtest at all.

        The column is nullable, whatever its schema comment says about the
        gate living there, so ``create`` requiring the field was the only thing
        stopping this row — and ``create`` is not how it got here. The
        walk-forward is in place, so the backtest is the only thing missing.
        """
        params = {"sma_period": 202}

        async def seed(conn):
            run_id = await _backtest(conn, params)
            await _walkforward(conn, run_id, params)
            return await _deployment(conn, None, params)

        deployment_id = _run(dsn, seed)
        response = _enable(client, deployment_id)
        assert response.status_code == 422, response.text
        assert "backtest" in response.json()["detail"]
        assert _status(dsn, deployment_id) == "disabled"

    def test_a_row_backed_by_a_failed_backtest_is_refused(self, client, dsn) -> None:
        params = {"sma_period": 203}

        async def seed(conn):
            run_id = await _backtest(conn, params, status="failed")
            await _walkforward(conn, run_id, params)
            return await _deployment(conn, run_id, params)

        deployment_id = _run(dsn, seed)
        response = _enable(client, deployment_id)
        assert response.status_code == 422, response.text
        assert "not 'succeeded'" in response.json()["detail"]
        assert _status(dsn, deployment_id) == "disabled"

    def test_a_study_that_later_fails_supersedes_the_one_that_admitted_it(
        self, client, dsn
    ) -> None:
        """
        Created legitimately, then the evidence changed.

        The gate reads the *most recent* completed study of these parameters.
        Re-running the walk-forward over a longer window and getting NOT ROBUST
        is exactly the result that should stop a deployment, and before this
        change it only stopped one that had not been created yet.
        """
        params = {"sma_period": 204}

        async def seed(conn):
            run_id = await _backtest(conn, params)
            await _walkforward(conn, run_id, params)
            return run_id

        run_id = _run(dsn, seed)
        created = client.post(
            "/api/v1/deployments",
            json={
                "strategy": STRATEGY,
                "params": params,
                "capital_usd": 10000,
                "approved_backtest_run_id": str(run_id),
            },
        )
        assert created.status_code == 201, created.text
        deployment_id = created.json()["id"]

        _run(dsn, lambda c: _walkforward(c, run_id, params, robust=False))

        response = _enable(client, deployment_id)
        assert response.status_code == 422, response.text
        assert "NOT ROBUST" in response.json()["detail"]
        assert _status(dsn, deployment_id) == "disabled"

    def test_a_study_that_no_longer_exists_vouches_for_nothing(
        self, client, dsn
    ) -> None:
        params = {"sma_period": 205}

        async def seed(conn):
            run_id = await _backtest(conn, params)
            wf_id = await _walkforward(conn, run_id, params)
            return run_id, wf_id

        run_id, wf_id = _run(dsn, seed)
        created = client.post(
            "/api/v1/deployments",
            json={
                "strategy": STRATEGY,
                "params": params,
                "capital_usd": 10000,
                "approved_backtest_run_id": str(run_id),
            },
        )
        assert created.status_code == 201, created.text
        deployment_id = created.json()["id"]

        _run(
            dsn, lambda c: c.execute("DELETE FROM walkforward_runs WHERE id=$1", wf_id)
        )

        response = _enable(client, deployment_id)
        assert response.status_code == 422, response.text
        assert "walk-forward" in response.json()["detail"]
        assert _status(dsn, deployment_id) == "disabled"

    def test_a_live_row_is_refused_without_the_environment_gate(
        self, client, dsn
    ) -> None:
        """
        ``create`` refuses mode=live without LIVE_TRADING_ENABLED, so a live
        row can only arrive some other way — and then nothing asked.

        Every other piece of evidence is in place, so the refusal can only be
        the environment gate. That gate is one of the three conditions between
        this system and real money; skipping it at the step that turns a
        deployment on would leave two.
        """
        params = {"sma_period": 206}

        async def seed(conn):
            run_id = await _backtest(conn, params)
            await _walkforward(conn, run_id, params)
            return await _deployment(conn, run_id, params, mode="live")

        deployment_id = _run(dsn, seed)
        response = _enable(client, deployment_id)
        assert response.status_code == 403, response.text
        assert "LIVE_TRADING_ENABLED" in response.json()["detail"]
        assert _status(dsn, deployment_id) == "disabled"


class TestEnableRefusesOtherOwners:
    def test_a_programme_shadow_deployment_stays_disabled(self, client, dsn) -> None:
        """
        Shadow mode reaches no venue.

        The programme creates its shadow deployments disabled and relies on
        them staying so. The worker's ``_enabled_deployments`` now filters on
        owner as well (``TestTheWorkerTradesOnlyTheOperatorsRows`` below), but
        this route is the first refusal. This row carries a complete, valid gate —
        the same evidence the programme's 2 -> 3 gate requires — so the gate
        alone would let it through. Only the ownership check refuses it.
        """
        params = {"sma_period": 207}

        async def seed(conn):
            run_id = await _backtest(conn, params)
            await _walkforward(conn, run_id, params)
            return await _deployment(conn, run_id, params, owner="programme")

        deployment_id = _run(dsn, seed)
        response = _enable(client, deployment_id)
        assert response.status_code == 409, response.text
        detail = response.json()["detail"]
        assert "'programme'" in detail
        assert "shadow" in detail
        assert _status(dsn, deployment_id) == "disabled"

    def test_ownership_is_the_reason_given_before_the_evidence(
        self, client, dsn
    ) -> None:
        """
        A shadow row missing its evidence is refused for being a shadow row.

        Answering 422 "no walk-forward" would invite the operator to go and
        produce one, after which the next click would succeed.
        """
        params = {"sma_period": 208}

        async def seed(conn):
            run_id = await _backtest(conn, params)
            return await _deployment(conn, run_id, params, owner="programme")

        deployment_id = _run(dsn, seed)
        response = _enable(client, deployment_id)
        assert response.status_code == 409, response.text
        assert _status(dsn, deployment_id) == "disabled"


class TestTheWorkerTradesOnlyTheOperatorsRows:
    """
    The second refusal, where the order is actually placed.

    The route above is one path to ``status='enabled'``; an ``UPDATE`` is
    another, and the worker is what reaches the venue. Its selection used to be
    ``WHERE status='enabled'`` and nothing else, so a programme row flipped by
    any path but this API would have been traded on the operator's account,
    against the operator's marks. Both queries that pick deployments for venue
    work — the live decision and the maintenance jobs (ingest, marks,
    reconcile) — now ask whose the row is.
    """

    def test_an_enabled_programme_row_is_not_selected(self, dsn) -> None:
        from src.worker import live_job, maintenance_jobs

        params = {"sma_period": 209}

        async def go(conn):
            run_id = await _backtest(conn, params)
            ours = await _deployment(conn, run_id, params)
            theirs = await _deployment(conn, run_id, params, owner="programme")
            await conn.execute(
                "UPDATE deployments SET status = 'enabled' WHERE id = ANY($1)",
                [uuid.UUID(ours), uuid.UUID(theirs)],
            )
            try:
                live_all = {
                    str(r["id"])
                    for r in await live_job._enabled_deployments(conn, None)
                }
                live_named = {
                    str(r["id"])
                    for r in await live_job._enabled_deployments(conn, [ours, theirs])
                }
                maintained = {
                    str(r["id"])
                    for r in await maintenance_jobs._enabled_deployment_rows(conn)
                }
            finally:
                # Other tests in this module read enabled rows; leave none.
                await conn.execute(
                    "UPDATE deployments SET status = 'disabled' WHERE id = ANY($1)",
                    [uuid.UUID(ours), uuid.UUID(theirs)],
                )
            return ours, theirs, live_all, live_named, maintained

        ours, theirs, live_all, live_named, maintained = _run(dsn, go)
        # The control: the operator's row is still found, so the refusal below
        # is the owner filter and not a query that finds nothing.
        for selected in (live_all, live_named, maintained):
            assert ours in selected
            assert theirs not in selected
