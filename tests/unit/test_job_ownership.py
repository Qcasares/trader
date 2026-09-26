"""
test_job_ownership.py
---------------------
Every job kind has exactly one owner, and each process claims only its own.

``jobs`` is one queue with two consumers. The worker runs backtests, the live
decision and everything else that may reach a venue; the programme runs Jev's
work, which needs a model client the worker may never import. Each claims with
``kinds=`` its own dispatch table, because a process that claimed every row
would take the other's work, find no handler, fail it with ``retry=False`` and
retire it for good — with the error written into a job that was never its to
run, while every job of its own succeeded. Nothing about that looks like a
fault from the side that caused it.

So the tables must never overlap, and every kind anything puts in the queue
must be in exactly one of them: a kind in neither sits queued forever, which is
a failure that produces no error anywhere; a kind in both is claimed by
whichever process polls first. The planner's kinds are the worker's; every
other kind is read off the ``enqueue`` calls in ``src/`` themselves, so a new
one is covered the day it is written.

The worker's claim filter is pinned by ``tests/unit/test_worker_claim.py``; the
programme's is pinned here, with the two switches that gate it. The end-to-end
half, on real Postgres, is ``tests/integration/test_jev_lane.py``.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
import pathlib
import re
import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest

from src.db.repos import jobs as job_repo
from src.db.repos import secrets as secret_repo
from src.engine.scheduler import JobKind, plan_session
from src.programme import flags
from src.programme import main as programme_main
from src.programme.main import JEV_HANDLERS, Programme
from src.worker.main import HANDLERS, SCHEDULED_KINDS

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

#: Where ``enqueue`` is defined, and the one place allowed to insert a job.
JOBS_REPO = "src/db/repos/jobs.py"

#: The one caller allowed to pass a computed kind: the session planner's wire,
#: which enqueues ``PlannedJob.kind.value``. Its kinds are ``JobKind``'s
#: members, checked against the worker's table directly below.
PLANNER_WIRE = "src/worker/scheduling.py"

#: An ordinary NYSE session, for asking the planner what it emits.
SESSION = date(2021, 6, 16)


# ---------------------------------------------------------------------------
# The two tables
# ---------------------------------------------------------------------------


class TestEachKindHasOneOwner:
    def test_the_two_dispatch_tables_are_disjoint(self) -> None:
        both = set(HANDLERS) & set(JEV_HANDLERS)
        assert not both, (
            f"{sorted(both)} would be claimed by the worker and the programme "
            "alike, run by whichever polled first"
        )

    def test_the_programme_owns_the_probe(self) -> None:
        # Guards the guard: an empty table would make every check here true
        # of nothing.
        assert "jev_probe" in JEV_HANDLERS
        assert all(callable(handler) for handler in JEV_HANDLERS.values())

    def test_every_kind_the_planner_can_emit_is_a_worker_kind(self) -> None:
        emitted = {kind.value for kind in JobKind}
        missing = emitted - set(HANDLERS)
        assert not missing, f"the planner emits kinds no worker runs: {missing}"
        assert not emitted & set(JEV_HANDLERS)

    def test_what_the_planner_does_emit_is_the_workers(self) -> None:
        emitted = {job.kind.value for job in plan_session(SESSION)}
        assert emitted, "the planner emitted nothing, so this proves nothing"
        assert emitted <= set(HANDLERS)
        assert emitted == set(SCHEDULED_KINDS)

    def test_the_scheduled_kinds_are_the_workers(self) -> None:
        assert set(SCHEDULED_KINDS) <= set(HANDLERS)
        assert not set(SCHEDULED_KINDS) & set(JEV_HANDLERS)

    def test_the_api_drains_only_the_workers_kinds(self) -> None:
        """
        The serverless drain runs worker handlers inside the API process. A
        programme kind there would run Jev's work in the process that may not
        hold its client.
        """
        pytest.importorskip("fastapi")
        from src.api.drain import DRAINABLE

        assert set(DRAINABLE) <= set(HANDLERS)
        assert not set(DRAINABLE) & set(JEV_HANDLERS)


# ---------------------------------------------------------------------------
# Every kind anything enqueues
# ---------------------------------------------------------------------------


def _name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _enqueues(relative: str, source: str) -> tuple[set[str], list[str]]:
    """
    The kinds ``source`` enqueues by literal name, and every use of ``enqueue``
    this scan cannot read a kind from.

    A call's kind is its second positional argument or its ``kind=``. Anything
    else — a computed kind, ``enqueue`` bound to another name, handed on
    uncalled or imported under an alias — is reported, because a kind this
    scan cannot see is a kind nobody has checked has an owner.
    """
    kinds: set[str] = set()
    unread: list[str] = []
    tree = ast.parse(source)
    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _name(node.func) == "enqueue":
            called.add(id(node.func))
            kind = node.args[1] if len(node.args) >= 2 else None
            for keyword in node.keywords:
                if keyword.arg == "kind":
                    kind = keyword.value
            if isinstance(kind, ast.Constant) and isinstance(kind.value, str):
                kinds.add(kind.value)
            else:
                unread.append(f"{relative}:{node.lineno}: {ast.unparse(node)}")
    for node in ast.walk(tree):
        if isinstance(node, (ast.Attribute, ast.Name)) and _name(node) == "enqueue":
            if id(node) not in called:
                unread.append(f"{relative}:{node.lineno}: {ast.unparse(node)}")
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "enqueue" and alias.asname not in (None, "enqueue"):
                    unread.append(f"{relative}:{node.lineno}: import as {alias.asname}")
    return kinds, unread


def _every_enqueue() -> tuple[dict[str, set[str]], list[str]]:
    """Each literal kind enqueued in ``src/``, with the files that enqueue it."""
    kinds: dict[str, set[str]] = {}
    unread: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        if relative == JOBS_REPO:
            continue
        found, opaque = _enqueues(relative, path.read_text("utf-8"))
        for kind in found:
            kinds.setdefault(kind, set()).add(relative)
        if relative != PLANNER_WIRE:
            unread += opaque
    return kinds, unread


class TestTheEnqueueScan:
    @pytest.mark.parametrize(
        "source, kinds, unread",
        [
            ('await job_repo.enqueue(conn, "backtest", {})', {"backtest"}, 0),
            ('await enqueue(conn, "jev_probe")', {"jev_probe"}, 0),
            ('await job_repo.enqueue(conn, kind="walkforward")', {"walkforward"}, 0),
            ("await job_repo.enqueue(conn, kind)", set(), 1),
            ('await job_repo.enqueue(conn, f"{kind}")', set(), 1),
            ("await job_repo.enqueue(conn, **job)", set(), 1),
            ("add = job_repo.enqueue", set(), 1),
            ("from src.db.repos.jobs import enqueue as add", set(), 1),
            ("from src.db.repos.jobs import enqueue", set(), 0),
            ('await job_repo.claim(conn, "w", kinds=["x"])', set(), 0),
        ],
    )
    def test_it_reads_what_it_claims(
        self, source: str, kinds: set[str], unread: int
    ) -> None:
        found, opaque = _enqueues("src/x.py", source)
        assert found == kinds
        assert len(opaque) == unread, opaque

    def test_it_finds_the_real_enqueues(self) -> None:
        # Guards the scan: the programme and the API enqueue these today, so a
        # scan that found none of them is matching nothing.
        kinds, _ = _every_enqueue()
        assert {"backtest", "walkforward", "shadow_decision"} <= set(kinds), kinds
        assert "src/programme/tick.py" in kinds["shadow_decision"]


class TestEveryEnqueuedKindHasExactlyOneOwner:
    def test_every_kind_enqueued_in_src_is_owned_once(self) -> None:
        kinds, _ = _every_enqueue()
        owners = {"worker": set(HANDLERS), "programme": set(JEV_HANDLERS)}
        problems = []
        for kind, files in sorted(kinds.items()):
            owned_by = [name for name, table in owners.items() if kind in table]
            if len(owned_by) != 1:
                problems.append(
                    f"{kind!r} (enqueued by {sorted(files)}) is owned by "
                    f"{owned_by or 'nobody'}"
                )
        assert not problems, (
            "a kind nobody owns sits queued forever and says nothing; a kind "
            "two processes own is run by whichever polls first:\n" + "\n".join(problems)
        )

    def test_every_kind_is_enqueued_by_a_name_the_scan_can_read(self) -> None:
        _, unread = _every_enqueue()
        assert not unread, (
            "enqueue is called with a kind this test cannot read, so nothing "
            "checks that kind has an owner. Pass it as a literal:\n" + "\n".join(unread)
        )

    def test_nothing_puts_a_job_in_the_queue_but_enqueue(self) -> None:
        pattern = re.compile(r"insert\s+into\s+jobs\b", re.IGNORECASE)
        writers = [
            path.relative_to(ROOT).as_posix()
            for path in sorted(SRC.rglob("*.py"))
            if pattern.search(path.read_text("utf-8"))
        ]
        assert writers == [JOBS_REPO], (
            f"{writers}: a job inserted around enqueue is one the scans above never see"
        )


# ---------------------------------------------------------------------------
# The programme claims only its own kinds, and only while both switches are on
# ---------------------------------------------------------------------------

FLAG_QUERY = "SELECT value FROM system_flags WHERE key = $1"


class _Conn:
    """Answers the switches' one query from ``rows``; nothing else."""

    def __init__(self, rows: dict[str, str]) -> None:
        self.rows = rows

    async def fetchrow(self, query: str, *args: object) -> dict[str, str] | None:
        assert query == FLAG_QUERY, f"unexpected SQL: {query!r}"
        (key,) = args
        return {"value": self.rows[key]} if key in self.rows else None


class _Acquired:
    def __init__(self, conn: _Conn) -> None:
        self.conn = conn

    async def __aenter__(self) -> _Conn:
        return self.conn

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _Pool:
    """Enough of an ``asyncpg.Pool`` to hand a connection on."""

    def __init__(self, conn: _Conn) -> None:
        self.conn = conn

    def acquire(self) -> _Acquired:
        return _Acquired(self.conn)


def _job(kind: str = "jev_probe") -> job_repo.Job:
    return job_repo.Job(
        id=uuid.uuid4(),
        kind=kind,
        payload={},
        status="running",
        attempts=1,
        max_attempts=3,
        created_at=datetime.now(UTC),
    )


#: The real signatures, read before any test replaces the functions.
_SIGNATURES = {
    name: inspect.signature(getattr(job_repo, name))
    for name in ("claim", "complete", "fail", "extend_lease")
}


class _Queue:
    """
    ``job_repo``'s claim, complete, fail and extend_lease over a list, each
    bound against the real function's signature so an argument is read the same
    way whether it was passed by position or by keyword.
    """

    def __init__(self, *jobs: job_repo.Job, honour_kinds: bool = True) -> None:
        self.jobs = list(jobs)
        self.honour_kinds = honour_kinds
        self.claims: list[Any] = []
        self.completed: list[tuple[uuid.UUID, Any]] = []
        self.failed: list[tuple[uuid.UUID, str, bool]] = []
        self.extended: list[uuid.UUID] = []

    @staticmethod
    def _bound(name: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        bound = _SIGNATURES[name].bind(*args, **kwargs)
        bound.apply_defaults()
        return bound.arguments

    async def claim(self, *args: Any, **kwargs: Any) -> job_repo.Job | None:
        arguments = self._bound("claim", *args, **kwargs)
        self.claims.append(arguments)
        for job in self.jobs:
            if not self.honour_kinds or job.kind in (arguments["kinds"] or [job.kind]):
                self.jobs.remove(job)
                return job
        return None

    async def complete(self, *args: Any, **kwargs: Any) -> None:
        arguments = self._bound("complete", *args, **kwargs)
        json.dumps(arguments["result"])  # what the real one writes as jsonb
        self.completed.append((arguments["job_id"], arguments["result"]))

    async def fail(self, *args: Any, **kwargs: Any) -> str:
        arguments = self._bound("fail", *args, **kwargs)
        self.failed.append(
            (arguments["job_id"], arguments["error"], arguments["retry"])
        )
        return "queued" if arguments["retry"] else "failed"

    async def extend_lease(self, *args: Any, **kwargs: Any) -> None:
        arguments = self._bound("extend_lease", *args, **kwargs)
        self.extended.append(arguments["job_id"])


def _on(programme: str = "true", jev: str = "true") -> dict[str, str]:
    return {flags.PROGRAMME_ENABLED: programme, flags.JEV_ENABLED: jev}


def _programme(
    monkeypatch: pytest.MonkeyPatch,
    queue: _Queue,
    rows: dict[str, str],
    *,
    vault_key: str | None = None,
    env_key: str | None = "env-typesafe-key",
) -> Programme:
    for name in ("claim", "complete", "fail", "extend_lease"):
        monkeypatch.setattr(job_repo, name, getattr(queue, name))

    async def vault(conn: Any, name: str, key: Any) -> str | None:
        return vault_key if name == secret_repo.TYPESAFE_API_KEY else None

    monkeypatch.setattr(secret_repo, "get", vault)
    programme = Programme(
        "postgresql://unused",
        api_key=None,
        secrets_key="secrets-key",
        typesafe_key=env_key,
    )
    programme._pool = _Pool(_Conn(rows))  # type: ignore[assignment]
    return programme


class _Handler:
    """A stand-in handler that records what it was handed."""

    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self.result = {"status": "ok"} if result is None else result
        self.error = error
        self.seen: list[tuple[Any, dict[str, Any], str | None]] = []

    async def __call__(
        self, conn: Any, payload: dict[str, Any], api_key: str | None
    ) -> dict[str, Any]:
        self.seen.append((conn, payload, api_key))
        if self.error is not None:
            raise self.error
        return self.result


class TestTheProgrammeClaimsOnlyItsOwnKinds:
    async def test_the_claim_is_filtered_to_its_dispatch_table(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        queue = _Queue()
        programme = _programme(monkeypatch, queue, _on())

        assert await programme._drain_jev() is False

        assert queue.claims, "the drain never asked the queue for a job"
        for arguments in queue.claims:
            assert arguments["kinds"] is not None, (
                "the programme claims every kind in the queue, the worker's "
                "included; it would fail them as 'no handler' with no retry"
            )
            assert sorted(arguments["kinds"]) == sorted(JEV_HANDLERS)
            assert arguments["worker_id"] == flags.PROGRAMME_WORKER_ID

    async def test_a_worker_kind_in_the_queue_is_left_alone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backtest = _job("backtest")
        queue = _Queue(backtest)
        programme = _programme(monkeypatch, queue, _on())
        assert await programme._drain_jev() is False
        assert queue.jobs == [backtest]
        assert queue.failed == [] and queue.completed == []

    @pytest.mark.parametrize(
        "rows",
        [
            pytest.param(_on(jev="false"), id="jev off"),
            pytest.param(_on(programme="false"), id="programme off"),
            pytest.param(_on("false", "false"), id="both off"),
            pytest.param(_on(jev='"true"'), id="jev the string true"),
            pytest.param({flags.PROGRAMME_ENABLED: "true"}, id="jev row missing"),
            pytest.param({flags.JEV_ENABLED: "true"}, id="programme row missing"),
        ],
    )
    async def test_nothing_is_claimed_unless_both_switches_are_on(
        self, monkeypatch: pytest.MonkeyPatch, rows: dict[str, str]
    ) -> None:
        """
        Two independent switches, both required. Switching the programme off
        stops Jev's spend as it stops the tick's; switching Jev off stops Jev
        and not the tick. Either way the job is not claimed, so it keeps its
        attempts for when both are on.
        """
        queued = _job()
        queue = _Queue(queued)
        programme = _programme(monkeypatch, queue, rows)

        assert await programme._drain_jev() is False

        assert queue.claims == [], "a job was claimed with a switch off"
        assert queue.jobs == [queued]

    async def test_with_both_on_the_job_runs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        handler = _Handler({"status": "ok", "request_id": 7})
        monkeypatch.setitem(JEV_HANDLERS, "jev_probe", handler)
        job = _job()
        queue = _Queue(job)
        programme = _programme(monkeypatch, queue, _on())

        assert await programme._drain_jev() is True

        assert len(handler.seen) == 1
        assert queue.completed == [(job.id, {"status": "ok", "request_id": 7})]
        assert queue.failed == []

    async def test_a_switch_turned_off_mid_drain_stops_the_next_claim(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rows = _on()
        first, second = _job(), _job()

        async def switch_off(conn, payload, api_key):
            rows[flags.JEV_ENABLED] = "false"
            return {"status": "ok"}

        monkeypatch.setitem(JEV_HANDLERS, "jev_probe", switch_off)
        queue = _Queue(first, second)
        programme = _programme(monkeypatch, queue, rows)

        assert await programme._drain_jev() is True
        assert [job_id for job_id, _ in queue.completed] == [first.id]
        assert queue.jobs == [second]


class TestTheProgrammeRunsWhatItClaims:
    async def test_the_handler_is_handed_the_key_the_vault_holds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        handler = _Handler()
        monkeypatch.setitem(JEV_HANDLERS, "jev_probe", handler)
        queue = _Queue(_job())
        programme = _programme(
            monkeypatch, queue, _on(), vault_key="vault-key", env_key="env-key"
        )
        await programme._drain_jev()
        ((_, payload, api_key),) = handler.seen
        assert api_key == "vault-key"
        assert payload == {}

    async def test_the_environment_is_the_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        handler = _Handler()
        monkeypatch.setitem(JEV_HANDLERS, "jev_probe", handler)
        programme = _programme(monkeypatch, _Queue(_job()), _on(), env_key="env-key")
        await programme._drain_jev()
        assert handler.seen[0][2] == "env-key"

    async def test_a_handler_that_raises_fails_the_job_for_a_retry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        handler = _Handler(error=RuntimeError("the ledger was unreachable"))
        monkeypatch.setitem(JEV_HANDLERS, "jev_probe", handler)
        job = _job()
        queue = _Queue(job)
        programme = _programme(monkeypatch, queue, _on())

        await programme._drain_jev()

        assert queue.completed == []
        assert queue.failed == [(job.id, "the ledger was unreachable", True)]

    async def test_the_key_never_reaches_the_jobs_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        key = "ts-live-0123456789abcdef"
        handler = _Handler(error=ValueError(f"header value {key!r} is invalid"))
        monkeypatch.setitem(JEV_HANDLERS, "jev_probe", handler)
        queue = _Queue(_job())
        programme = _programme(monkeypatch, queue, _on(), vault_key=f"{key}\n")

        await programme._drain_jev()

        ((_, error, _),) = queue.failed
        assert key not in error
        assert "[redacted]" in error

    async def test_a_kind_it_cannot_run_is_refused_without_retry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Unreachable while the claim is filtered, and the insurance if the
        filter ever drifts: refused loudly rather than run by a guess.
        """
        stray = _job("jev_somethingelse")
        queue = _Queue(stray, honour_kinds=False)
        programme = _programme(monkeypatch, queue, _on())
        await programme._drain_jev()
        assert queue.failed == [(stray.id, "no handler for jev_somethingelse", False)]

    async def test_the_lease_is_kept_while_the_handler_runs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        The worker's sweep requeues any job whose lease lapses, whoever owns
        it, and a Jev job run twice is a call paid for twice.
        """
        monkeypatch.setattr(programme_main, "JEV_LEASE_REFRESH_SECONDS", 0.01)
        job = _job()
        queue = _Queue(job)

        async def long_running(conn, payload, api_key):
            # Runs until its lease has been pushed out twice, and gives up
            # after five seconds if it never is.
            async def extended_twice() -> None:
                while len(queue.extended) < 2:
                    await asyncio.sleep(0.005)

            await asyncio.wait_for(extended_twice(), timeout=5)
            return {"status": "ok"}

        monkeypatch.setitem(JEV_HANDLERS, "jev_probe", long_running)
        programme = _programme(monkeypatch, queue, _on())

        await programme._drain_jev()
        extended = len(queue.extended)
        await asyncio.sleep(0.05)

        assert queue.completed == [(job.id, {"status": "ok"})], (
            "the lease was not extended while the job ran"
        )
        assert set(queue.extended) == {job.id}
        assert len(queue.extended) == extended, "the lease outlived the job"

    async def test_the_loop_outlives_an_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        programme = _programme(monkeypatch, _Queue(), _on())
        monkeypatch.setattr(programme_main, "JEV_POLL_SECONDS", 0.01)
        attempts = 0

        async def failing_drain() -> bool:
            nonlocal attempts
            attempts += 1
            if attempts >= 3:
                programme.stop()
            raise ConnectionResetError("the pool went away")

        monkeypatch.setattr(programme, "_drain_jev", failing_drain)
        await asyncio.wait_for(programme._jev_loop(), timeout=5)
        assert attempts == 3


def test_the_programme_claims_as_itself() -> None:
    """
    Its jobs are locked by the id its heartbeat reports under, so the jobs page
    and the liveness row name the same process.
    """
    tree = ast.parse((SRC / "programme" / "main.py").read_text("utf-8"))
    claims = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _name(node.func) == "claim"
    ]
    assert len(claims) == 1, "the programme claims jobs in exactly one place"
    (claim,) = claims
    assert ast.unparse(claim.args[1]) == "PROGRAMME_WORKER_ID"
    kinds = [k for k in claim.keywords if k.arg == "kinds"]
    assert [ast.unparse(k.value) for k in kinds] == ["list(JEV_HANDLERS)"]
