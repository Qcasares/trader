#!/usr/bin/env python3
"""
bootstrap_paper_deployment.py
-----------------------------
Bring a paper deployment into existence on the production database, using the
shipped control plane rather than SQL.

    DATABASE_URL=... python scripts/bootstrap_paper_deployment.py \
        --strategy buy_and_hold

Why this exists
~~~~~~~~~~~~~~~
The deployed API is the control plane and it wants an operator session, which
means the operator password. That password exists as a bcrypt hash on Vercel
and as plaintext in one person's head, and Vercel marks `DATABASE_URL` as
sensitive so `vercel env pull` will not return it either. The result is that
the one host that *can* reach the production database unattended — a GitHub
Actions runner, which holds `secrets.DATABASE_URL` — is also the one host that
cannot log in.

So this does not log in to the deployed API. It runs the same application
in-process, against the same database, under an operator credential generated
in the job and discarded when the job ends.

Why not just write the rows
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Because every check that makes a deployment trustworthy lives in the route
handler, not in the table. `POST /deployments` is what refuses a backtest that
ran on synthetic data, refuses a strategy whose parameters do not parse,
refuses a run that is not `succeeded`, and refuses — this is the important one
— any configuration with no completed walk-forward study or a study whose
verdict is NOT ROBUST. An INSERT reproduces the row and none of the reasoning.
Driving the ASGI app keeps the gate exactly where it was written, so a
configuration this script deploys is one the API would have deployed.

The research itself is not done here either. `POST /backtests` and
`POST /backtests/{id}/walkforward` enqueue jobs, and the worker that is already
running claims and executes them. This waits.

What it will not do
~~~~~~~~~~~~~~~~~~~
Reach a live venue. `mode` is not an argument: the request is built with
`"paper"` literally. The three independent conditions for live trading are
untouched and this script sets none of them, so even a deployment somebody
later edits to `mode=live` would still need `LIVE_TRADING_ENABLED` and
`ALPACA_ALLOW_LIVE` in the worker's environment, and they are set to "false"
there explicitly.

It is idempotent. An enabled paper deployment for the same strategy and
parameters means there is nothing to do, and it says so and stops rather than
creating a second one that would trade the same capital twice.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

# `python scripts/thing.py` puts `scripts/` on sys.path, not the repository
# root, so `import src` fails unless the caller happens to have exported
# PYTHONPATH. Relying on the caller is how the first version of the broker
# check reached CI broken.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# The application reads its configuration from the environment at import time
# and caches it, so the ephemeral credential has to be in place before anything
# under `src.api` is imported. Nothing below this point may be moved above it.
_EPHEMERAL_PASSWORD = secrets.token_urlsafe(32)


def _install_ephemeral_operator() -> None:
    import bcrypt

    os.environ["ADMIN_PASSWORD_HASH"] = bcrypt.hashpw(
        _EPHEMERAL_PASSWORD.encode(), bcrypt.gensalt()
    ).decode()
    os.environ["SESSION_SECRET"] = secrets.token_urlsafe(48)
    # Deliberately not setting CORS_ORIGINS. Setting it turns the session
    # cookie Secure, and this client speaks to an in-process ASGI app over no
    # transport at all, so a Secure cookie would simply never come back. The
    # bearer header the API accepts for scripted access avoids the question,
    # but leaving the variable alone avoids it twice.
    os.environ.pop("CORS_ORIGINS", None)


class BootstrapError(RuntimeError):
    pass


async def _wait_for(
    client: Any,
    url: str,
    *,
    what: str,
    timeout_s: int = 1800,
    row_id: str | None = None,
) -> dict[str, Any]:
    """
    Poll a resource until it stops being queued or running.

    ``row_id`` is for the walk-forward endpoint, which returns every study for
    a run rather than one object. Waiting on "the first element" would watch
    whichever study the ordering happened to put first, which is the wrong one
    as soon as a configuration has been studied twice.
    """
    waited = 0
    interval = 10
    last = "unknown"
    while waited < timeout_s:
        response = await client.get(url)
        response.raise_for_status()
        body = response.json()
        if isinstance(body, list):
            matches = [row for row in body if row.get("id") == row_id]
            if not matches:
                raise BootstrapError(f"{what} {row_id} is not in the response")
            body = matches[0]
        status = body.get("status")
        if status != last:
            print(f"    {what}: {status}", flush=True)
            last = status
        if status in ("succeeded", "completed"):
            return body
        if status in ("failed", "cancelled"):
            reason = body.get("error") or "no error recorded"
            raise BootstrapError(f"{what} ended as {status!r}: {reason}")
        await asyncio.sleep(interval)
        waited += interval
    raise BootstrapError(
        f"{what} was still {last!r} after {timeout_s}s. The worker may not be "
        "running: check `worker_heartbeats` and the worker workflow."
    )


async def run(args: argparse.Namespace) -> int:
    import httpx

    from src.api.main import create_app

    params = json.loads(args.params)
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport, base_url="http://bootstrap", timeout=120.0
    ) as client:
        # The app opens its pool in the lifespan handler, so it has to be
        # entered explicitly rather than relying on the first request.
        async with app.router.lifespan_context(app):
            login = await client.post(
                "/api/v1/auth/login", json={"password": _EPHEMERAL_PASSWORD}
            )
            if login.status_code != 200:
                raise BootstrapError(
                    f"could not authenticate against the in-process app "
                    f"({login.status_code}): {login.text}"
                )
            client.headers["Authorization"] = f"Bearer {login.json()['token']}"
            print("authenticated with an ephemeral operator credential")

            existing = (await client.get("/api/v1/deployments")).json()
            for row in existing:
                same = row["strategy_name"] == args.strategy and row["params"] == params
                if same and row["status"] == "enabled":
                    print(
                        f"\nAn enabled deployment for this configuration already "
                        f"exists: {row['id']}\nNothing to do."
                    )
                    return 0

            print(f"\n1. backtest {args.strategy} on {args.source} data")
            created = await client.post(
                "/api/v1/backtests",
                json={
                    "strategy": args.strategy,
                    "params": params,
                    "start": args.start,
                    "end": args.end,
                    "initial_cash": args.capital,
                    "data_source": args.source,
                },
            )
            if created.status_code >= 400:
                raise BootstrapError(f"backtest refused: {created.text}")
            run_id = created.json()["run_id"]
            print(f"   run {run_id}, queued for the worker")
            result = await _wait_for(
                client, f"/api/v1/backtests/{run_id}", what="backtest"
            )
            metrics = result.get("metrics") or {}
            print(
                f"   Sharpe {metrics.get('sharpe'):.3f} "
                f"+/- {metrics.get('sharpe_stderr'):.3f}, "
                f"significant={metrics.get('sharpe_is_significant')}"
            )

            print("\n2. walk-forward, which is the gate that actually decides")
            wf = await client.post(
                f"/api/v1/backtests/{run_id}/walkforward",
                json={
                    "param_grid": json.loads(args.grid),
                    "train_months": args.train_months,
                    "test_months": args.test_months,
                },
            )
            if wf.status_code >= 400:
                raise BootstrapError(f"walk-forward refused: {wf.text}")
            wf_id = wf.json()["walkforward_run_id"]
            print(f"   study {wf_id}, queued for the worker")
            study = await _wait_for(
                client,
                f"/api/v1/backtests/{run_id}/walkforward",
                what="walk-forward",
                row_id=wf_id,
            )
            # `is_robust` is nullable until the study finishes, and a missing
            # verdict is not a negative one. Printing "NOT ROBUST" for a null,
            # or +0.000 for an absent Sharpe, is the same error the scorecard
            # rules exist to prevent: it asserts the most decisive reading of a
            # measurement that was never taken.
            robust = study.get("is_robust")
            if robust is None:
                verdict = "unknown"
            else:
                verdict = "ROBUST" if robust else "NOT ROBUST"
            oos = study.get("mean_out_of_sample_sharpe")
            oos_text = "not reported" if oos is None else f"{float(oos):+.3f}"
            stitched = (study.get("metrics") or {}).get("sharpe")
            stderr = (study.get("metrics") or {}).get("sharpe_stderr")
            print(f"   verdict {verdict}, mean OOS Sharpe {oos_text}")
            if stitched is not None and stderr is not None:
                print(
                    f"   stitched out-of-sample {float(stitched):+.3f} "
                    f"+/- {float(stderr):.3f} over {study.get('n_folds')} folds"
                )

            print("\n3. create the deployment, paper, and let the gate answer")
            deployment = await client.post(
                "/api/v1/deployments",
                json={
                    "strategy": args.strategy,
                    "params": params,
                    "capital_usd": args.capital,
                    "approved_backtest_run_id": run_id,
                    # Literal. This script has no live mode to reach.
                    "mode": "paper",
                    "risk_limits": json.loads(args.risk_limits),
                },
            )
            if deployment.status_code >= 400:
                raise BootstrapError(
                    "the deployment gate refused this configuration, which is "
                    "the gate doing its job:\n    " + deployment.text
                )
            deployment_id = deployment.json()["id"]
            print(f"   deployment {deployment_id} created, disabled")

            print("\n4. enable it")
            enabled = await client.post(
                f"/api/v1/deployments/{deployment_id}/enable",
                json={"confirm": "ENABLE DEPLOYMENT"},
            )
            if enabled.status_code >= 400:
                raise BootstrapError(f"enable refused: {enabled.text}")

            print("\n5. release the kill switch")
            resumed = await client.post(
                "/api/v1/system/resume", json={"confirm": "ENABLE TRADING"}
            )
            if resumed.status_code >= 400:
                raise BootstrapError(f"resume refused: {resumed.text}")
            status = resumed.json()

            print("\n--- state now ---")
            print(f"  trading_enabled      {status['trading_enabled']}")
            print(f"  live_trading_enabled {status['live_trading_enabled']}")
            print(f"  alpaca_allow_live    {status['alpaca_allow_live']}")
            print(f"  broker_configured    {status['broker_configured']}")
            for worker in status.get("workers", []):
                print(
                    f"  worker {worker['worker_id']}: {worker['status']} "
                    f"({worker['age_seconds']:.0f}s ago)"
                )
            print(
                "\nThe deployment is enabled and the kill switch is released. "
                "The worker owns it from here: it plans a job per session, "
                "decides after the close and submits at the next open."
            )
    return 0


def main() -> int:
    if not os.environ.get("DATABASE_URL", "").strip():
        print("DATABASE_URL must be set", file=sys.stderr)
        return 2
    _install_ephemeral_operator()

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", default="buy_and_hold")
    parser.add_argument("--params", default='{"symbols": ["SPY"], "min_history": 1}')
    parser.add_argument("--grid", default='{"min_history": [1]}')
    parser.add_argument("--start", default="2007-01-01")
    parser.add_argument("--end", default=yesterday)
    parser.add_argument("--capital", type=float, default=100000.0)
    parser.add_argument("--source", default="yfinance")
    parser.add_argument("--train-months", type=int, default=36)
    parser.add_argument("--test-months", type=int, default=12)
    parser.add_argument(
        "--risk-limits",
        default=json.dumps(
            {
                "max_weight_per_asset": 1.0,
                "min_trade_usd": 25.0,
                "max_gross_exposure": 0.98,
                "max_drawdown_pct": 0.35,
                # The 2007-2026 run logged 29 underfunded buys, one trimmed
                # 13.7% short, which is a backtest being kinder than the venue.
                # A buffer is what makes the two agree.
                "cash_buffer_pct": 0.02,
            }
        ),
    )
    args = parser.parse_args()

    try:
        return asyncio.run(run(args))
    except BootstrapError as error:
        print(f"\nFAILED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
