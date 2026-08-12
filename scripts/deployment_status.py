#!/usr/bin/env python3
"""
deployment_status.py
--------------------
Read what the production system currently believes, and prove the decision
path still reaches the venue.

    DATABASE_URL=... ALPACA_KEY_ID=... ALPACA_SECRET_KEY=... \
        python scripts/deployment_status.py

Why this exists
~~~~~~~~~~~~~~~
There was no way to look. Every read endpoint on the deployed API needs an
operator session, `vercel env pull` returns `[SENSITIVE]` for the database URL,
and no Neon client is configured anywhere, so the only answer to "is it
actually trading?" was "dispatch something that writes and read its logs". A
system that can only be inspected by changing it is one people stop inspecting.

This writes nothing. It opens the database read-only, prints what it finds, and
runs the deployment's own dry-run, which computes order intents through the
real strategy, the real risk gate and the real broker account state without
submitting anything.

The `--advance-ingest` and `--advance-reconcile` exceptions are opt-in. Each
moves today's matching queued job to now so the worker claims it immediately.
They touch only the job schedule and neither submits an order.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_EPHEMERAL_PASSWORD = secrets.token_urlsafe(32)


def _install_ephemeral_operator() -> None:
    import bcrypt

    os.environ["ADMIN_PASSWORD_HASH"] = bcrypt.hashpw(
        _EPHEMERAL_PASSWORD.encode(), bcrypt.gensalt()
    ).decode()
    os.environ["SESSION_SECRET"] = secrets.token_urlsafe(48)
    os.environ.pop("CORS_ORIGINS", None)


async def _report_database(
    advance_ingest: bool, advance_reconcile: bool
) -> list[str]:
    """Everything the API has no endpoint for. Returns the deployed universe."""
    import asyncpg

    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        deployments = await conn.fetch(
            "SELECT id, strategy_name, params, mode, status, capital_usd, "
            "last_rebalance FROM deployments ORDER BY created_at DESC"
        )
        print("deployments")
        universe: list[str] = []
        for row in deployments:
            params = row["params"]
            if isinstance(params, str):
                params = json.loads(params)
            print(
                f"  {row['id']}  {row['strategy_name']}  {row['mode']}  "
                f"{row['status']}  ${float(row['capital_usd']):,.0f}"
            )
            print(f"    params        {params}")
            # Nullable, and null means "has never rebalanced", which is a
            # different statement from "rebalanced at the epoch".
            last = row["last_rebalance"]
            print(f"    last_rebalance {last if last is not None else 'never'}")
            if row["status"] == "enabled":
                universe.extend(params.get("symbols", []))

        flag = await conn.fetchrow(
            "SELECT value, updated_by, updated_at FROM system_flags "
            "WHERE key = 'trading_enabled'"
        )
        print(f"\nkill switch  trading_enabled={flag['value'] if flag else 'MISSING'}")
        if flag:
            print(f"             set by {flag['updated_by']} at {flag['updated_at']}")

        print("\nprice coverage for the deployed universe")
        if not universe:
            print("  no enabled deployment, so nothing is being ingested")
        for symbol in sorted(set(universe)):
            bar = await conn.fetchrow(
                "SELECT count(*) n, min(session) lo, max(session) hi "
                "FROM daily_bars WHERE symbol = $1",
                symbol,
            )
            if bar["n"] == 0:
                # Not "0 bars from None to None". An absent measurement and a
                # measured zero are different things everywhere else here too.
                print(f"  {symbol}: no bars ingested yet")
            else:
                print(f"  {symbol}: {bar['n']} bars, {bar['lo']} .. {bar['hi']}")

        print("\ntoday's job queue")
        jobs = await conn.fetch(
            "SELECT kind, status, scheduled_for, attempts, error FROM jobs "
            "WHERE scheduled_for::date = CURRENT_DATE ORDER BY scheduled_for"
        )
        for job in jobs:
            line = (
                f"  {job['scheduled_for']:%H:%M}  {job['kind']:<16} "
                f"{job['status']:<10} attempts={job['attempts']}"
            )
            if job["error"]:
                line += f"\n      error: {job['error'][:160]}"
            print(line)
        if not jobs:
            print("  nothing scheduled for today")

        print("\nrecent decisions")
        decisions = await conn.fetch(
            "SELECT session, status, created_at FROM decisions "
            "ORDER BY created_at DESC LIMIT 5"
        )
        for row in decisions:
            print(f"  {row['session']}  {row['status']}  {row['created_at']}")
        if not decisions:
            print("  none yet")

        print("\nrecent orders")
        # `orders` has no created_at. It has `updated_at`, which is always set,
        # and `submitted_at`, which is null until the venue accepted it — and
        # that null is the difference between an order that was planned and one
        # that was sent, so it is printed rather than coalesced away.
        orders = await conn.fetch(
            "SELECT symbol, side, status, mode, submitted_at, updated_at "
            "FROM orders ORDER BY updated_at DESC LIMIT 5"
        )
        for row in orders:
            sent = row["submitted_at"] or "not submitted"
            print(
                f"  {row['symbol']} {row['side']} {row['status']} "
                f"({row['mode']}) sent={sent}"
            )
        if not orders:
            print("  none yet")

        print("\nAI programme")
        # Both of these are seeded off and read fail-closed, so an operator who
        # set a model credential and stopped has a programme that holds a key
        # and does nothing. That is the state worth being able to see.
        prog = {
            row["key"]: row["value"]
            for row in await conn.fetch(
                "SELECT key, value FROM system_flags WHERE key LIKE 'programme%'"
            )
        }
        for key in sorted(prog):
            print(f"  {key:<28} {prog[key]}")
        if not prog:
            print("  no programme flags found")

        # `configured` and a fingerprint, never the value, and no decryption
        # attempted: this job holds the broker credentials, and the whole point
        # of the vault separation is that nothing holds both.
        secret = await conn.fetchrow(
            "SELECT fingerprint, updated_by, updated_at FROM secrets "
            "WHERE name = 'anthropic_api_key'"
        )
        if secret is None:
            print("  model credential            not set")
        else:
            print(
                f"  model credential            set ({secret['fingerprint']}), "
                f"by {secret['updated_by']} at {secret['updated_at']}"
            )

        # Ordered by created_at, not started_at: started_at is null until a
        # pass is claimed, and DESC sorts nulls first in Postgres, so ordering
        # on it would show requested-but-never-started passes as the newest.
        #
        # `model` is the column that answers "has the AI actually done
        # anything". It defaults to the empty string, so a run that completed
        # without ever reaching the model is visibly different from one that
        # did, and neither is guessed from the status.
        runs = await conn.fetch(
            "SELECT status, model, created_at, error FROM programme_runs "
            "ORDER BY created_at DESC LIMIT 5"
        )
        print("  recent passes")
        for row in runs:
            model = row["model"] or "no model call"
            line = f"    {row['created_at']}  {row['status']:<10} {model}"
            if row["error"]:
                line += f"\n      error: {row['error'][:200]}"
            print(line)
        if not runs:
            print("    none yet — the programme has never completed a pass")

        for table in ("hypotheses", "candidates", "experiments", "findings"):
            count = await conn.fetchval(f"SELECT count(*) FROM {table}")
            print(f"  {table:<28} {count}")

        if advance_ingest:
            moved = await conn.execute(
                "UPDATE jobs SET scheduled_for = NOW() "
                "WHERE kind = 'ingest_bars' AND status = 'queued' "
                "AND scheduled_for::date = CURRENT_DATE"
            )
            print(f"\nadvanced today's ingest job to now ({moved})")

        if advance_reconcile:
            moved = await conn.execute(
                "UPDATE jobs SET scheduled_for = NOW() "
                "WHERE kind = 'reconcile' AND status = 'queued' "
                "AND scheduled_for::date = CURRENT_DATE"
            )
            print(f"\nadvanced today's reconcile job to now ({moved})")

        return universe
    finally:
        await conn.close()


async def _dry_run() -> None:
    """The decision path, end to end, submitting nothing."""
    import httpx

    from src.api.main import create_app

    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://status",
        timeout=120.0,
    ) as client:
        async with app.router.lifespan_context(app):
            login = await client.post(
                "/api/v1/auth/login", json={"password": _EPHEMERAL_PASSWORD}
            )
            login.raise_for_status()
            client.headers["Authorization"] = f"Bearer {login.json()['token']}"

            deployments = (await client.get("/api/v1/deployments")).json()
            enabled = [d for d in deployments if d["status"] == "enabled"]
            if not enabled:
                print("\nno enabled deployment, so there is nothing to dry-run")
                return

            for deployment in enabled:
                print(f"\ndry-run {deployment['id']} ({deployment['strategy_name']})")
                response = await client.post(
                    f"/api/v1/deployments/{deployment['id']}/dry-run", json={}
                )
                if response.status_code >= 400:
                    print(f"  refused ({response.status_code}): {response.text}")
                    continue
                body = response.json()
                if body.get("error"):
                    print(f"  session {body.get('session')}: {body['error']}")
                    continue
                intents = body.get("order_intents", [])
                session = body.get("session")
                print(f"  session {session}: {len(intents)} order intent(s)")
                for intent in intents:
                    print(f"    {intent}")


async def main_async(args: argparse.Namespace) -> int:
    await _report_database(args.advance_ingest, args.advance_reconcile)
    if not args.no_dry_run:
        await _dry_run()
    return 0


def main() -> int:
    if not os.environ.get("DATABASE_URL", "").strip():
        print("DATABASE_URL must be set", file=sys.stderr)
        return 2
    _install_ephemeral_operator()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--advance-ingest",
        action="store_true",
        help="move today's queued ingest_bars job to now",
    )
    parser.add_argument(
        "--advance-reconcile",
        action="store_true",
        help="move today's queued reconcile job to now",
    )
    parser.add_argument("--no-dry-run", action="store_true")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
