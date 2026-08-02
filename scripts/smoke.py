#!/usr/bin/env python3
"""
smoke.py
--------
Prove a deployment actually works, against its real URL.

    python scripts/smoke.py https://your-api.vercel.app
    API_PASSWORD=... python scripts/smoke.py https://your-api.vercel.app

Not a test of the code — the suite does that, on every push. This tests the
*deployment*: the parts that only exist once something is hosted, and that a
green CI run says nothing about. Every failure this catches is one whose error
message points somewhere other than its cause, which is why each check prints
the actual remedy rather than a stack trace.

    reachable            the URL resolves and answers
    database             migrations applied, connection string accepted
    login                session cookie issued *and accepted on the next call*
    strategies           the registry loaded
    backtest             a run reaches 'succeeded' — proving something,
                         somewhere, actually executes queued jobs
    honesty              the result carries its standard error, its cost
                         assumption and its annualisation basis

Exits non-zero on the first failure, so it can gate a release.

Depends only on the standard library. A smoke test that needs its own install
is one you cannot run from the machine you happen to be sitting at.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from typing import Any

TIMEOUT = 30
#: A backtest is ~2s; a cold start plus the queue can add a lot more.
BACKTEST_DEADLINE = 180


class CheckError(Exception):
    """A check failed. The message is the remedy, not the symptom."""


def _opener() -> Any:
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar())
    )


class Client:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.opener = _opener()

    def call(
        self, path: str, body: dict | None = None, method: str | None = None
    ) -> tuple[int, Any]:
        status, payload, _ = self.call_full(path, body, method)
        return status, payload

    def call_full(
        self, path: str, body: dict | None = None, method: str | None = None
    ) -> tuple[int, Any, list[str]]:
        """As :meth:`call`, plus the raw ``Set-Cookie`` headers.

        The cookie's *attributes* are what distinguish two failures that look
        identical from the outside, so they have to be readable.
        """
        url = f"{self.base}{path}"
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            url,
            data=data,
            method=method or ("POST" if data else "GET"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with self.opener.open(request, timeout=TIMEOUT) as response:
                raw = response.read().decode()
                cookies = response.headers.get_all("Set-Cookie") or []
                return response.status, (json.loads(raw) if raw else None), cookies
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode()
            try:
                return exc.code, json.loads(raw), []
            except ValueError:
                return exc.code, raw, []
        except urllib.error.URLError as exc:
            raise CheckError(
                f"cannot reach {url}: {exc.reason}. Check the URL, and that the "
                f"deployment finished building."
            ) from exc


def check(label: str, fn: Any) -> Any:
    print(f"  {label:.<24}", end=" ", flush=True)
    try:
        result = fn()
    except CheckError as exc:
        print("FAIL")
        print(f"\n  {exc}\n")
        raise SystemExit(1) from exc
    print("ok" + (f"  {result}" if isinstance(result, str) else ""))
    return result


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(f"usage: {sys.argv[0]} https://your-api.example.com")
    client = Client(sys.argv[1])
    password = os.environ.get("API_PASSWORD", "")

    print(f"\nSmoke-testing {client.base}\n")

    def reachable() -> str:
        status, body = client.call("/api/v1/health")
        if status != 200:
            raise CheckError(
                f"/api/v1/health returned {status}. The function is deployed but "
                f"failing to start — check the runtime logs for an import error; "
                f"a missing src/ in the bundle looks exactly like this."
            )
        return f"v{body.get('version', '?')}"

    def database() -> str:
        status, body = client.call("/api/v1/ready")
        if status == 503:
            raise CheckError(
                "the API cannot reach its database. Either DATABASE_URL is wrong, "
                "or the connection string carries a parameter asyncpg refuses "
                "(a provider default). Check the logs for 'unrecognized "
                "configuration parameter'."
            )
        if status != 200:
            raise CheckError(f"/api/v1/ready returned {status}: {body}")
        return "connected"

    def login() -> str:
        if not password:
            raise CheckError(
                "set API_PASSWORD to the password whose bcrypt hash you put in "
                "ADMIN_PASSWORD_HASH."
            )
        status, body, cookies = client.call_full(
            "/api/v1/auth/login", {"password": password}
        )
        if status == 401:
            raise CheckError(
                "password rejected. If you are sure it is right, the hash was "
                "probably truncated: a bcrypt hash starts $2b$12$ and a shell "
                "expands $2 and $1. Quote it."
            )
        if status != 200:
            raise CheckError(f"login returned {status}: {body}")

        # The half that actually matters. Login can succeed and hand back a
        # cookie that is never sent again, and on screen that is
        # indistinguishable from a rejected password.
        status, _ = client.call("/api/v1/auth/me")
        if status == 200:
            return "session accepted"

        # Two different causes produce this, and they have opposite fixes, so
        # read the cookie's own attributes rather than guessing.
        header = " ".join(cookies).lower()
        if "secure" in header and client.base.startswith("http://"):
            raise CheckError(
                "the cookie is marked Secure and this URL is plain http, so no "
                "client will store it. Over https this is fine — deployments "
                "are https, so you are probably pointing at a local server "
                "with CORS_ORIGINS set. Use https, or unset CORS_ORIGINS "
                "locally."
            )
        if "samesite=lax" in header or "samesite" not in header:
            raise CheckError(
                "the session cookie was issued but not sent on the next call. "
                "Set SESSION_COOKIE_SAMESITE=none — the UI and the API are on "
                "different sites, and no browser sends a 'lax' cookie "
                "cross-site."
            )
        raise CheckError(
            f"the session cookie was issued but not accepted. Cookie "
            f"attributes: {' '.join(cookies) or '(none sent)'}"
        )

    def strategies() -> str:
        status, body = client.call("/api/v1/strategies")
        if status != 200:
            raise CheckError(f"/api/v1/strategies returned {status}: {body}")
        if not body:
            raise CheckError(
                "the strategy registry is empty; src/strategies failed to import"
            )
        return ", ".join(s["name"] for s in body)

    def backtest() -> str:
        status, created = client.call(
            "/api/v1/backtests",
            {
                "strategy": "asset_class_trend_following",
                "start": "2018-01-01",
                "end": "2020-12-31",
                "data_source": "synthetic",
            },
        )
        if status != 202:
            raise CheckError(f"could not queue a backtest ({status}): {created}")
        run_id = created["run_id"]

        deadline = time.time() + BACKTEST_DEADLINE
        drained = False
        while time.time() < deadline:
            _, run = client.call(f"/api/v1/backtests/{run_id}")
            if run["status"] == "succeeded":
                return f"{run['metrics']['n_sessions']} sessions"
            if run["status"] == "failed":
                raise CheckError(f"the backtest failed: {run['error']}")

            # Nothing runs queued work on a host with no worker unless the
            # drain is enabled, so ask once and report precisely if it is not.
            if run["status"] == "queued" and not drained:
                drained = True
                code, _ = client.call("/api/v1/system/drain", {})
                if code == 404:
                    raise CheckError(
                        "the run is queued and nothing will ever execute it. On "
                        "a serverless host set SERVERLESS_DRAIN_ENABLED=true; "
                        "elsewhere, start the worker (python -m src.worker.main)."
                    )
            time.sleep(3)
        raise CheckError(
            f"backtest {run_id} did not finish within {BACKTEST_DEADLINE}s"
        )

    def honesty() -> str:
        _, runs = client.call("/api/v1/backtests?limit=1")
        metrics = runs[0]["metrics"]
        missing = [
            field
            for field in ("sharpe_stderr", "cost_stress_multiplier", "periods_per_year")
            if metrics.get(field) is None
        ]
        if missing:
            raise CheckError(
                f"results are missing {missing}. A Sharpe without its standard "
                f"error is a number that will be believed."
            )
        verdict = (
            "significant" if metrics["sharpe_is_significant"] else "NOT significant"
        )
        return (
            f"sharpe {metrics['sharpe']:+.3f} +/- "
            f"{metrics['sharpe_stderr']:.3f} ({verdict})"
        )

    check("reachable", reachable)
    check("database", database)
    check("login", login)
    check("strategies", strategies)
    check("backtest", backtest)
    check("honesty", honesty)

    print("\n  All checks passed — the deployment works end to end.")
    print(
        "\n  Note: that run used synthetic prices, which say nothing about any\n"
        "  strategy. No result in this repository has ever been produced from\n"
        "  observed market data.\n"
    )


if __name__ == "__main__":
    main()
