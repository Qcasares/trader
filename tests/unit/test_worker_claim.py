"""
test_worker_claim.py
--------------------
Which rows in ``jobs`` the worker is allowed to take.

The queue is shared. The worker claims and runs jobs; the programme process
enqueues some of them, and is about to own kinds of its own that the worker
has no handler for. A worker that claims *every* queued row takes those too,
finds no handler, and fails them with ``retry=False`` — permanently, with the
error landing on another process's job while every one of the worker's own
jobs succeeds. Nothing about that looks like a fault from the worker's side.

``src/api/drain.py`` already claims with ``kinds=list(DRAINABLE)``. This pins
the worker to the same discipline: it passes exactly the keys of its dispatch
table, so a kind it cannot run stays queued for the process that can.

The end-to-end half, with a real queue and an unknown kind left untouched, is
``tests/integration/test_scheduling.py::TestTheWorkerClaimsOnlyWhatItCanRun``.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

from src.db.repos import jobs as job_repo
from src.worker import main
from src.worker.main import HANDLERS, Worker


class _Acquired:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _Pool:
    """Enough of an ``asyncpg.Pool`` for ``_drain`` to hand a connection on."""

    def acquire(self) -> _Acquired:
        return _Acquired()


def _kinds_passed_to_claim(monkeypatch) -> list[Any]:
    """Drain once against an empty queue and return every ``kinds`` argument."""
    signature = inspect.signature(job_repo.claim)
    seen: list[Any] = []

    async def claim(*args: Any, **kwargs: Any) -> None:
        # Bound against the real signature, so the argument is read the same
        # way whether it was passed by position or by keyword.
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        seen.append(bound.arguments["kinds"])
        return None

    monkeypatch.setattr(main.job_repo, "claim", claim)
    worker = Worker("postgresql://unused", "claim-test")
    worker._pool = _Pool()  # type: ignore[assignment]
    did_work = asyncio.run(worker._drain())
    assert did_work is False
    return seen


class TestTheWorkerClaimsOnlyWhatItCanRun:
    def test_claim_is_filtered_to_the_dispatch_table(self, monkeypatch) -> None:
        seen = _kinds_passed_to_claim(monkeypatch)

        assert seen, "the drain never asked the queue for a job"
        for kinds in seen:
            assert kinds is not None, (
                "the worker claims every kind in the queue, including ones it "
                "has no handler for; it would fail another process's jobs as "
                "'no handler' with no retry"
            )
            assert sorted(kinds) == sorted(HANDLERS), (
                f"claims {sorted(kinds)} but can run {sorted(HANDLERS)}"
            )
