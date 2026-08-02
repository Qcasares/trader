"""
test_drain_boundary.py
----------------------
The line the serverless drain must not cross.

``POST /api/v1/system/drain`` lets the API process run queued jobs itself,
because a serverless host has nowhere to put a long-lived worker and a
submitted backtest would otherwise sit queued forever.

That is a real loosening of a real invariant, so it is fenced twice:

1. **Research jobs only.** "The worker is the only process that places an
   order" is what makes the kill-switch check, the three-gate design and the
   import boundary mean anything. A drainable ``submit_orders`` would let an
   HTTP request reach a venue, routing around all of it. The one-line change
   that would cause it — adding a key to ``DRAINABLE`` — is what this file
   watches.

2. **Off by default.** The API declining to run a backtest inline is not
   fastidiousness: it is CPU-bound pandas work, and on a long-lived server it
   stalls every other request on that event loop, including the one an
   operator is using to hit the kill switch. Only a serverless invocation,
   which has no other requests to stall, may turn it on.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from src.api.drain import DRAINABLE  # noqa: E402
from src.worker.main import HANDLERS  # noqa: E402

#: Kinds that can reach a broker. None may ever be drainable.
TRADING_KINDS = frozenset({"live_decision", "submit_orders"})


class TestOnlyResearchJobsAreDrainable:
    def test_no_trading_kind_is_drainable(self) -> None:
        overlap = TRADING_KINDS & set(DRAINABLE)
        assert not overlap, (
            f"{sorted(overlap)} would let an HTTP request place an order. The "
            "worker being the only process that reaches a venue is what makes "
            "the kill-switch check and the three live gates meaningful"
        )

    def test_the_trading_kinds_named_here_still_exist(self) -> None:
        # Guards the guard. If a kind is renamed, this test would keep passing
        # against a name nothing uses while the real one became drainable.
        missing = TRADING_KINDS - set(HANDLERS)
        assert not missing, (
            f"{sorted(missing)} are not worker job kinds any more; this test "
            "is now checking names that do not exist"
        )

    def test_drainable_kinds_are_real_job_kinds(self) -> None:
        unknown = set(DRAINABLE) - set(HANDLERS)
        assert not unknown, f"{sorted(unknown)} are not job kinds the worker knows"

    def test_something_is_actually_drainable(self) -> None:
        # A drain that can run nothing would leave every serverless deployment
        # silently queueing forever, which is the bug it exists to fix.
        assert "backtest" in DRAINABLE


class TestDisabledByDefault:
    def test_settings_default_to_off(self, monkeypatch) -> None:
        from src.api.security import hash_password
        from src.config import get_settings

        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/unused")
        monkeypatch.setenv("SESSION_SECRET", "d" * 48)
        monkeypatch.setenv("ADMIN_PASSWORD_HASH", hash_password("unused"))
        monkeypatch.delenv("SERVERLESS_DRAIN_ENABLED", raising=False)
        get_settings.cache_clear()
        try:
            assert get_settings().serverless_drain_enabled is False
        finally:
            get_settings.cache_clear()

    def test_compose_does_not_enable_it(self) -> None:
        # docker-compose runs a real worker, so draining from the API there
        # would duplicate work and reintroduce the event-loop stall.
        import pathlib

        compose = pathlib.Path("docker-compose.yml").read_text()
        assert "SERVERLESS_DRAIN_ENABLED" not in compose, (
            "the compose stack runs a worker; enabling drain there would run "
            "backtests inside the API process for no reason"
        )
