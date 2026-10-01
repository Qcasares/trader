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
import hashlib
import inspect
import json
import pathlib
import re
import typing
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from src.db.repos import jobs as job_repo
from src.db.repos import secrets as secret_repo
from src.engine.scheduler import JobKind, plan_session
from src.programme import flags, jev_prereg
from src.programme import main as programme_main
from src.programme.main import JEV_HANDLERS, JobFailedError, Programme
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


#: The module ``enqueue`` is defined in, as an import names it.
JOBS_MODULE = JOBS_REPO.removesuffix(".py").replace("/", ".")


def _modules_bound(relative: str, tree: ast.AST) -> dict[str, str]:
    """Each name an import in ``tree`` binds, and the dotted name it binds."""
    package = list(pathlib.PurePosixPath(relative).with_suffix("").parts[:-1])
    bound: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                head = alias.name.partition(".")[0]
                bound[alias.asname or head] = alias.name if alias.asname else head
        elif isinstance(node, ast.ImportFrom):
            up = node.level - 1 if node.level else 0
            base = (package[: len(package) - up] if node.level else []) + (
                node.module.split(".") if node.module else []
            )
            for alias in node.names:
                if alias.name != "*":
                    bound[alias.asname or alias.name] = ".".join([*base, alias.name])
    return bound


def _dotted(node: ast.AST, bound: dict[str, str]) -> str | None:
    """The dotted name an expression reads, where imports alone say it."""
    if isinstance(node, ast.Name):
        return bound.get(node.id)
    if isinstance(node, ast.Attribute):
        head = _dotted(node.value, bound)
        return f"{head}.{node.attr}" if head is not None else None
    return None


def _enqueues(relative: str, source: str) -> tuple[set[str], list[str]]:
    """
    The kinds ``source`` enqueues by literal name, and every use of ``enqueue``
    this scan cannot read a kind from.

    A call's kind is its second positional argument or its ``kind=``. Anything
    else — a computed kind, ``enqueue`` bound to another name, handed on
    uncalled or imported under an alias — is reported, because a kind this
    scan cannot see is a kind nobody has checked has an owner. So is the
    function taken by its name rather than spelled: the literal
    ``"enqueue"`` wherever it stands — ``getattr(job_repo, "enqueue")``,
    ``vars(job_repo)["enqueue"]``, ``attrgetter("enqueue")`` — and the jobs
    module, however it was imported, read by a name computed at run time or
    as a whole namespace (``getattr(job_repo, name)``, ``vars(job_repo)``,
    ``job_repo.__dict__``). The first cut read the spelled calls alone, so a
    second producer of ``jev_web_ingest`` through ``getattr`` passed every
    ownership test (C6's review). It reads spellings, and is not a sandbox.
    """
    kinds: set[str] = set()
    unread: list[str] = []
    tree = ast.parse(source)
    bound = _modules_bound(relative, tree)

    def the_jobs_module(node: ast.AST) -> bool:
        return _dotted(node, bound) == JOBS_MODULE

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == "enqueue":
            unread.append(f"{relative}:{node.lineno}: 'enqueue', looked up by name")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "getattr" and len(node.args) >= 2:
                name = node.args[1]
                if the_jobs_module(node.args[0]) and not (
                    isinstance(name, ast.Constant) and isinstance(name.value, str)
                ):
                    unread.append(f"{relative}:{node.lineno}: {ast.unparse(node)}")
            elif node.func.id == "vars" and node.args and the_jobs_module(node.args[0]):
                unread.append(f"{relative}:{node.lineno}: {ast.unparse(node)}")
        elif isinstance(node, ast.Attribute) and node.attr == "__dict__":
            if the_jobs_module(node.value):
                unread.append(f"{relative}:{node.lineno}: {ast.unparse(node)}")
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
            # Looked up by its name, as a literal (C6's review): each finds the
            # function with no call or attribute the scan reads spelled
            # "enqueue", so the kind it is called with is never read.
            (
                'await getattr(job_repo, "enqueue")(conn, "jev_web_ingest", {})',
                set(),
                1,
            ),
            ('await vars(job_repo)["enqueue"](conn, "jev_web_ingest", {})', set(), 1),
            ('await job_repo.__dict__["enqueue"](conn, "jev_probe", {})', set(), 1),
            ('add = operator.attrgetter("enqueue")(job_repo)', set(), 1),
            # ...or by a name computed at run time, off the jobs module however
            # it was imported: every attribute of it read by a name the scan
            # cannot, or the whole of its namespace.
            (
                "from src.db.repos import jobs as job_repo\n"
                'NAME = "enq" + "ueue"\n'
                'await getattr(job_repo, NAME)(conn, "jev_web_ingest", {})',
                set(),
                1,
            ),
            (
                "import src.db.repos.jobs as queue\nadd = getattr(queue, NAME)",
                set(),
                1,
            ),
            ("from src.db.repos import jobs\nfunctions = vars(jobs)", set(), 1),
            ("from src.db import repos\nfunctions = repos.jobs.__dict__", set(), 1),
            ("import src.db.repos.jobs\nadd = getattr(src.db.repos.jobs, N)", set(), 1),
            # ...and what reads another name, or another module, is not one.
            (
                "from src.db.repos import jobs as job_repo\n"
                'lease = getattr(job_repo, "DEFAULT_LEASE")',
                set(),
                0,
            ),
            ("value = getattr(settings, name)", set(), 0),
            ('"""Calls enqueue once, by name."""', set(), 0),
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
    """
    Answers the switches' one query from ``rows``; nothing else. It says it is
    in no transaction, as a pooled connection the loop hands over is, and
    opens one that does nothing, for a handler that writes through fakes.
    """

    def __init__(self, rows: dict[str, str]) -> None:
        self.rows = rows

    async def fetchrow(self, query: str, *args: object) -> dict[str, str] | None:
        assert query == FLAG_QUERY, f"unexpected SQL: {query!r}"
        (key,) = args
        return {"value": self.rows[key]} if key in self.rows else None

    def is_in_transaction(self) -> bool:
        return False

    def transaction(self, **options: object) -> _NoTransaction:
        return _NoTransaction()


class _NoTransaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: object) -> bool:
        return False


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


def _job(
    kind: str = "jev_probe", payload: dict[str, Any] | None = None
) -> job_repo.Job:
    return job_repo.Job(
        id=uuid.uuid4(),
        kind=kind,
        payload={} if payload is None else payload,
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
        #: What each failure stored beside its error, in the same order.
        self.failed_results: list[Any] = []
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
        json.dumps(arguments["result"])  # what the real one writes as jsonb
        self.failed.append(
            (arguments["job_id"], arguments["error"], arguments["retry"])
        )
        self.failed_results.append(arguments["result"])
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

    @pytest.mark.parametrize("retry", [True, False])
    async def test_a_handlers_verdict_fails_the_job_as_it_says(
        self, monkeypatch: pytest.MonkeyPatch, retry: bool
    ) -> None:
        """A job whose work came to nothing is failed, never completed."""

        async def refused(conn, payload, api_key):
            raise JobFailedError("the probe failed: auth (request 9)", retry=retry)

        monkeypatch.setitem(JEV_HANDLERS, "jev_probe", refused)
        job = _job()
        queue = _Queue(job)
        programme = _programme(monkeypatch, queue, _on())

        assert await programme._drain_jev() is True

        assert queue.completed == []
        assert queue.failed == [(job.id, "the probe failed: auth (request 9)", retry)]
        assert queue.failed_results == [None]

    async def test_what_a_failed_attempt_recorded_is_kept_beside_its_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        A handler whose attempt recorded something before it failed — an
        ask's answer and the plans it was recorded under — hands it over on
        its ``JobFailedError``, and the loop stores it with the error, so a
        job that failed still names its answer's plans
        (``jev_jobs.run_ask``; section 10a of the C7+C8 scope).
        """
        record = {"status": "invalid", "request_id": 9, "plan_hash": "ab" * 32}

        async def refused(conn, payload, api_key):
            raise JobFailedError(
                "the response was refused whole (request 9)",
                retry=False,
                result=record,
            )

        monkeypatch.setitem(JEV_HANDLERS, "jev_ask", refused)
        job = _job("jev_ask")
        queue = _Queue(job)
        programme = _programme(monkeypatch, queue, _on())

        assert await programme._drain_jev() is True

        assert queue.failed == [
            (job.id, "the response was refused whole (request 9)", False)
        ]
        assert queue.failed_results == [record]

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

    async def test_the_ingest_job_is_handed_no_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        The web ingest asks Jev nothing, so it needs no key (docs/08, C6). The
        loop resolves one for every Jev job; ``main._jev_web_ingest`` drops it,
        and ``web_ingest.run_job`` has no parameter it could arrive by. Run
        through the drain with a key in the vault and another in the
        environment, the job is handed its connection and its payload and
        nothing else, and neither key is in either.
        """
        from src.programme import web_ingest

        assert list(inspect.signature(web_ingest.run_job).parameters) == [
            "conn",
            "payload",
        ]
        source = (SRC / "programme" / "web_ingest.py").read_text("utf-8")
        assert "api_key" not in source and "secret" not in source.lower()

        vault_key, env_key = "ts-vault-key-0123456789", "ts-env-key-9876543210"
        seen: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

        async def run_job(*args: Any, **kwargs: Any) -> dict[str, Any]:
            seen.append((args, kwargs))
            return {"source": "pwb-readme"}

        monkeypatch.setattr(web_ingest, "run_job", run_job)
        job = _job("jev_web_ingest", {"source": "pwb-readme"})
        queue = _Queue(job)
        programme = _programme(
            monkeypatch, queue, _on(), vault_key=vault_key, env_key=env_key
        )

        assert await programme._drain_jev() is True

        ((args, kwargs),) = seen
        assert kwargs == {}, "the ingest job was handed a keyword"
        conn, payload = args
        assert conn is programme._pool.conn  # type: ignore[union-attr]
        assert payload == {"source": "pwb-readme"}
        assert all(key not in repr(args) for key in (vault_key, env_key))
        assert queue.completed == [(job.id, {"source": "pwb-readme"})]

    @pytest.mark.parametrize(
        ("vault_key", "env_key"),
        [
            pytest.param(None, None, id="none-anywhere"),
            pytest.param("", None, id="an-empty-vault-entry"),
            pytest.param(None, "  \n", id="a-blank-environment"),
        ],
    )
    async def test_the_ingest_job_is_not_run_without_a_key(
        self,
        monkeypatch: pytest.MonkeyPatch,
        vault_key: str | None,
        env_key: str | None,
    ) -> None:
        """
        The planner plans the ingest only while a key is set, since a page
        fetched for a lane that cannot ask about it is a fetch for nothing
        (design R28), and a job queued before the key went is claimed after
        it (open item 53). The wrapper reads the key for whether it is there,
        as the road reads it, and refuses the job for good without running it,
        as the probe refuses; the key still goes no further.
        """
        from src.programme import web_ingest

        ran: list[Any] = []

        async def run_job(*args: Any, **kwargs: Any) -> dict[str, Any]:
            ran.append((args, kwargs))
            return {}

        monkeypatch.setattr(web_ingest, "run_job", run_job)
        job = _job("jev_web_ingest", {"source": "pwb-readme"})
        queue = _Queue(job)
        programme = _programme(
            monkeypatch, queue, _on(), vault_key=vault_key, env_key=env_key
        )

        assert await programme._drain_jev() is True

        assert ran == [], "the ingest ran with no key to ask about what it fetched"
        ((failed_id, error, retry),) = queue.failed
        assert (failed_id, retry) == (job.id, False)
        assert error.startswith("no TypeSafe key is set")
        assert error.endswith("nothing was fetched")
        assert queue.completed == []

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

        async def plan() -> list[str]:
            return []

        monkeypatch.setattr(programme, "_drain_jev", failing_drain)
        monkeypatch.setattr(programme, "_plan_jev", plan)
        await asyncio.wait_for(programme._jev_loop(), timeout=5)
        assert attempts == 3


# ---------------------------------------------------------------------------
# The planner runs beside the drain, and never in its way
# ---------------------------------------------------------------------------


class TestThePlannerStep:
    async def test_the_planner_outlives_an_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        A planner that fails every time is logged, and the drain goes ahead on
        every pass: a job already queued does not need planning again.
        """
        programme = _programme(monkeypatch, _Queue(), _on())
        monkeypatch.setattr(programme_main, "JEV_POLL_SECONDS", 0.01)
        monkeypatch.setattr(programme_main, "JEV_PLAN_SECONDS", 0.0)
        events: list[str] = []

        async def failing_plan() -> list[str]:
            events.append("plan")
            raise ConnectionResetError("the pool went away")

        async def drain() -> bool:
            events.append("drain")
            if events.count("drain") >= 3:
                programme.stop()
            return False

        monkeypatch.setattr(programme, "_plan_jev", failing_plan)
        monkeypatch.setattr(programme, "_drain_jev", drain)
        await asyncio.wait_for(programme._jev_loop(), timeout=5)
        assert events == ["plan", "drain"] * 3

    async def test_the_planner_runs_at_most_once_a_period(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        programme = _programme(monkeypatch, _Queue(), _on())
        monkeypatch.setattr(programme_main, "JEV_POLL_SECONDS", 0.01)
        monkeypatch.setattr(programme_main, "JEV_PLAN_SECONDS", 3600.0)
        events: list[str] = []

        async def plan() -> list[str]:
            events.append("plan")
            return []

        async def drain() -> bool:
            events.append("drain")
            if events.count("drain") >= 4:
                programme.stop()
            return False

        monkeypatch.setattr(programme, "_plan_jev", plan)
        monkeypatch.setattr(programme, "_drain_jev", drain)
        await asyncio.wait_for(programme._jev_loop(), timeout=5)
        assert events == ["plan", "drain", "drain", "drain", "drain"]

    @pytest.mark.parametrize(
        ("vault_key", "env_key", "available"),
        [
            ("vault-typesafe-key", None, True),
            (None, "env-typesafe-key", True),
            (None, None, False),
        ],
    )
    async def test_the_planner_learns_only_whether_a_key_exists(
        self,
        monkeypatch: pytest.MonkeyPatch,
        vault_key: str | None,
        env_key: str | None,
        available: bool,
    ) -> None:
        """
        The planner plans nothing without a key, and is never handed one: it
        is told a boolean, beside the time in UTC.
        """
        from src.programme import jev_plan

        programme = _programme(
            monkeypatch, _Queue(), _on(), vault_key=vault_key, env_key=env_key
        )
        seen: list[dict[str, Any]] = []

        async def plan(conn: Any, **kwargs: Any) -> list[str]:
            seen.append(kwargs)
            return []

        monkeypatch.setattr(jev_plan, "plan", plan)
        assert await programme._plan_jev() == []
        (kwargs,) = seen
        assert set(kwargs) == {"now", "key_available"}
        assert kwargs["key_available"] is available
        assert kwargs["now"].utcoffset() == timedelta(0)


# ---------------------------------------------------------------------------
# Every Jev job makes at most one call an attempt
# ---------------------------------------------------------------------------

#: The calls that reach TypeSafe: the road, and the probe that takes it.
ROAD = frozenset({"ask", "run_probe"})

_LOOPS = (
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


def _road_calls(tree: ast.AST) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _name(node.func) in ROAD
    ]


def _road_calls_in_loops(tree: ast.AST) -> list[str]:
    found = []
    for loop in ast.walk(tree):
        if isinstance(loop, _LOOPS):
            found += [ast.unparse(call) for call in _road_calls(loop)]
    return found


def _handler_modules() -> dict[str, pathlib.Path]:
    """
    The module holding each kind's work: its handler's, unwrapped, so a
    handler ``main`` wraps only to drop the key is read where its work is.
    """
    return {
        kind: pathlib.Path(inspect.getfile(inspect.unwrap(handler)))
        for kind, handler in JEV_HANDLERS.items()
    }


#: How many calls to the road each kind makes an attempt, at most. The web
#: ingest (phase C6) fetches a page and stores it, and calls nothing; the ask
#: (phases C7 and C8) asks one set about one text, once.
ROAD_CALLS: dict[str, int] = {
    "jev_probe": 1,
    "jev_regime": 1,
    "jev_reask": 1,
    "jev_web_ingest": 0,
    "jev_ask": 1,
}


def _module_symbols(tree: ast.Module) -> dict[str, ast.AST]:
    """Each name a module binds at its top level, to a definition or a value."""
    symbols: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            symbols[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    symbols[target.id] = node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            symbols[node.target.id] = node.value
    return symbols


def _reachable_road_calls(tree: ast.Module, handler: str) -> list[ast.Call]:
    """
    Every call to the road reachable from ``handler`` within its module: in
    its own body, and in every top-level definition or value it names, and
    they name, in turn — a follow-up held in a table the handler reads is
    reached through the table. Since phase C7 one module holds two handlers
    that ask, the re-ask and the ask, so the count is each handler's own and
    not its module's.
    """
    symbols = _module_symbols(tree)
    assert handler in symbols, f"{handler} is not defined at the module's top level"
    seen: set[str] = set()
    pending = [handler]
    calls: dict[int, ast.Call] = {}
    while pending:
        name = pending.pop()
        if name in seen or name not in symbols:
            continue
        seen.add(name)
        node = symbols[name]
        for call in _road_calls(node):
            calls[id(call)] = call
        pending += [
            child.id
            for child in ast.walk(node)
            if isinstance(child, ast.Name) and child.id in symbols
        ]
    return list(calls.values())


class TestEveryJevHandlerMakesAtMostOneCall:
    """
    One call an attempt, which is what the shutdown grace covers, and none
    for a job that calls nothing. Not one call a job: an attempt whose call got
    no response is retried and asks again (``jev_jobs.ask_verdict``), since an
    ``error`` row is no answer to replay.
    """

    def test_every_kind_says_how_many_calls_it_makes(self) -> None:
        assert set(ROAD_CALLS) == set(JEV_HANDLERS)
        assert all(calls in (0, 1) for calls in ROAD_CALLS.values())

    def test_no_handler_module_calls_the_road_in_a_loop(self) -> None:
        modules = set(_handler_modules().values()) | {SRC / "programme" / "jev_lane.py"}
        for path in sorted(modules):
            tree = ast.parse(path.read_text("utf-8"))
            assert _road_calls_in_loops(tree) == [], path.name

    def test_each_handler_takes_the_road_once(self) -> None:
        """
        One call site reachable from each handler that asks, and one ``ask``
        in the probe: two sites a handler can reach is a job that can take
        both. None reachable from the ingest job, which asks nothing. Counted
        per handler rather than per module since phase C7, when the ask joined
        the re-ask in ``jev_jobs``; the module as a whole holds exactly the
        sites its handlers reach, so no call sits there unread.
        """
        modules = _handler_modules()
        assert modules["jev_web_ingest"] == SRC / "programme" / "web_ingest.py"
        assert modules["jev_ask"] == SRC / "programme" / "jev_jobs.py"
        by_module: dict[pathlib.Path, set[int]] = {}
        trees: dict[pathlib.Path, ast.Module] = {}
        for kind, path in modules.items():
            tree = trees.setdefault(path, ast.parse(path.read_text("utf-8")))
            handler = inspect.unwrap(JEV_HANDLERS[kind]).__name__
            calls = _reachable_road_calls(tree, handler)
            assert len(calls) == ROAD_CALLS[kind], (
                kind,
                [ast.unparse(c) for c in calls],
            )
            by_module.setdefault(path, set()).update(id(c) for c in calls)
        for path, tree in trees.items():
            assert {id(c) for c in _road_calls(tree)} == by_module[path], (
                f"{path.name} holds a call to the road no handler of it reaches"
            )
        lane = ast.parse((SRC / "programme" / "jev_lane.py").read_text("utf-8"))
        (run_probe,) = [
            node
            for node in ast.walk(lane)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_probe"
        ]
        assert len(_road_calls(run_probe)) == 1

    def test_the_reach_follows_a_table_of_follow_ups(self) -> None:
        """
        Guards the guard: a second call hidden in a follow-up the handler
        reaches only through a module-level table is counted, and a call in a
        function nothing reaches is not the handler's.
        """
        tree = ast.parse(
            "async def follow(conn):\n"
            "    await jev_lane.ask(conn)\n"
            "async def unused(conn):\n"
            "    await jev_lane.ask(conn)\n"
            "TABLE = {'x': Askable(follow_up=follow)}\n"
            "async def handler(conn):\n"
            "    await jev_lane.ask(conn)\n"
            "    await TABLE['x'].follow_up(conn)\n"
        )
        assert len(_reachable_road_calls(tree, "handler")) == 2
        assert len(_reachable_road_calls(tree, "unused")) == 1

    def test_the_scan_sees_a_call_in_a_loop(self) -> None:
        tree = ast.parse(
            "async def h(conn):\n"
            "    for _ in range(2):\n"
            "        await jev_lane.ask(conn)\n"
            "    [await run_probe(conn) for _ in x]\n"
        )
        assert len(_road_calls_in_loops(tree)) == 2

    @pytest.mark.parametrize("kind", sorted(JEV_HANDLERS))
    async def test_every_jev_handler_makes_at_most_one_call(
        self, monkeypatch: pytest.MonkeyPatch, kind: str
    ) -> None:
        """
        Every outcome the road can return, with every error kind, run through
        every handler, counted: never more than one ask, and none from a job
        that calls nothing, which must then have run to its end, so that none
        is not a count of a handler that stopped early. The shutdown grace is
        sized for one call (``JEV_SHUTDOWN_GRACE_SECONDS``), and a job that
        asked twice is two answers with an equal claim to be right.
        """
        from src.programme import jev_client, jev_lane

        outcomes = [
            (status, kind_)
            for status in typing.get_args(jev_lane.AskStatus)
            for kind_ in (jev_client.ERROR_KINDS if status == "error" else (None,))
        ]
        handler = JEV_HANDLERS[kind]
        _prepare_handler(monkeypatch, kind)
        for status, error_kind in outcomes:
            asked: list[dict[str, Any]] = []

            async def ask(
                conn: Any,
                *,
                _status: str = status,
                _kind: str | None = error_kind,
                _asked: list[dict[str, Any]] = asked,
                **kwargs: Any,
            ) -> jev_lane.AskResult:
                _asked.append(kwargs)
                return jev_lane.AskResult(
                    _status,  # type: ignore[arg-type]
                    request_row_id=None
                    if _status in jev_lane.UNRECORDED_STATUSES
                    else 7,
                    error_kind=_kind,
                )

            async def probe(conn: Any, *args: Any, _asked=asked, **kwargs: Any) -> Any:
                _asked.append({"run_probe": args})
                raise AssertionError("the probe was run from another kind's handler")

            async def client_ask(*args: Any, _asked=asked, **kwargs: Any) -> Any:
                _asked.append({"client": kwargs})
                raise AssertionError("the client was called around the road")

            monkeypatch.setattr(jev_lane, "ask", ask)
            if kind != "jev_probe":
                monkeypatch.setattr(jev_lane, "run_probe", probe)
            monkeypatch.setattr(jev_client, "ask", client_ask)
            try:
                await handler(_Conn(_all_on()), dict(_PAYLOADS[kind]), "ts-key")
            except JobFailedError:
                assert ROAD_CALLS[kind], f"{kind} calls nothing and must run to its end"
            assert len(asked) == ROAD_CALLS[kind], (kind, status, error_kind, asked)

    def test_every_handler_has_a_counted_run(self) -> None:
        assert set(_PAYLOADS) == set(JEV_HANDLERS)


#: The excerpt the counted run of ``jev_ask`` asks the screen about. Invented.
_EXCERPT = "Quiet Momentum in Invented Mid-Cap Shares"

#: Each Jev kind's payload for the counted run above.
_PAYLOADS: dict[str, dict[str, Any]] = {
    "jev_probe": {},
    "jev_regime": {"session": "2026-09-28", "set": "decision.regime", "version": 1},
    "jev_reask": {"request_id": 41},
    "jev_web_ingest": {"source": "pwb-readme"},
    "jev_ask": {
        "set": "guardrail.injection",
        "version": 1,
        "subject_type": "web_excerpt",
        "subject_id": hashlib.sha256(_EXCERPT.encode("utf-8")).hexdigest(),
        "source_id": 7,
        **(jev_prereg.plans_in_force("guardrail.injection", 1) or {}),
    },
}


def _all_on() -> dict[str, str]:
    return {
        **_on(),
        f"{flags.JEV_AREA_PREFIX}decisions": "true",
        f"{flags.JEV_AREA_PREFIX}research": "true",
    }


def _prepare_handler(monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    """
    Everything a handler reads before it asks, answered so that it asks: the
    count above is of what happens at and after the road.
    """
    from src.programme import (
        jev_clock,
        jev_features,
        jev_lane,
        jev_questions,
        jev_repo,
        repo,
    )

    state = jev_questions.RegimeState(
        **{
            sleeve: jev_questions.SleeveState(
                trend="near", volatility_quintile=3, drawdown="none", momentum="flat"
            )
            for sleeve in jev_questions.SLEEVES
        }
    )

    if kind == "jev_regime":
        session = date(2026, 9, 28)

        async def no_signal(conn: Any, **kwargs: Any) -> bool:
            return False

        async def before_the_cutoff(conn: Any) -> datetime:
            return jev_clock.collect_at(session)

        async def nobody_trades(conn: Any) -> repo.TradedUniverse:
            return repo.TradedUniverse(frozenset(), ())

        async def no_jobs(conn: Any, keys: Any) -> dict[str, Any]:
            return {}

        async def a_panel(conn: Any, when: date, symbols: Any = None) -> object:
            return object()

        async def recorded(conn: Any, **kwargs: Any) -> jev_lane.SignalRecord:
            return jev_lane.SignalRecord("measured", "neutral", 1, False, True)

        monkeypatch.setattr(jev_repo, "signal_exists", no_signal)
        monkeypatch.setattr(jev_clock, "database_now", before_the_cutoff)
        monkeypatch.setattr(repo, "traded_universe", nobody_trades)
        monkeypatch.setattr(jev_repo, "job_outcomes", no_jobs)
        monkeypatch.setattr(jev_clock, "load_regime_panel", a_panel)
        monkeypatch.setattr(jev_features, "regime_state", lambda *a: state)
        monkeypatch.setattr(jev_lane, "record_signal", recorded)
    elif kind == "jev_reask":
        regime = jev_questions.DECISION_REGIME

        async def canonical(conn: Any, request_id: int) -> dict[str, Any]:
            return {
                "id": request_id,
                "status": "ok",
                "lane": regime.lane,
                "question_set": regime.name,
                "question_set_version": regime.version,
                "pack_hash": regime.pack_hash,
                "model_requested": "jev-1.13.0",
                "state": regime.dump_state(state),
                "subject_type": "session",
                "subject_id": "2026-09-25",
                "as_of": datetime(2026, 9, 25, 20, tzinfo=UTC),
            }

        async def pin(conn: Any) -> str:
            return "jev-1.13.0"

        async def no_answers(conn: Any, request_id: int) -> list[dict[str, Any]]:
            return []

        monkeypatch.setattr(jev_repo, "get_request", canonical)
        monkeypatch.setattr(flags, "jev_model", pin)
        monkeypatch.setattr(jev_repo, "answers_for", no_answers)
    elif kind == "jev_web_ingest":
        from src.programme import web_fetch
        from tests.fakes import pwb_readme

        page = pwb_readme.fetched(pwb_readme.readme())

        async def fetch(source: Any) -> Any:
            return page

        async def none_quarantined(conn: Any, contents: Any) -> dict[str, int]:
            return {}

        async def stored(conn: Any, rows: Any) -> list[tuple[int, str, bool]]:
            return [(n, row.content_sha256, True) for n, row in enumerate(rows, 1)]

        async def quarantined(conn: Any, content: str, reason: str) -> int:
            return 0

        async def usable_pin(conn: Any) -> str:
            return "jev-1.13.0"

        async def labelled(conn: Any, **label: Any) -> int:
            return 1

        monkeypatch.setattr(web_fetch, "fetch", fetch)
        monkeypatch.setattr(flags, "jev_model", usable_pin)
        monkeypatch.setattr(jev_repo, "earliest_quarantined", none_quarantined)
        monkeypatch.setattr(jev_repo, "insert_documents", stored)
        monkeypatch.setattr(jev_repo, "quarantine_content", quarantined)
        monkeypatch.setattr(jev_repo, "record_label_once", labelled)
    elif kind == "jev_ask":
        # The screen asked about a stored excerpt the code screen passes, so
        # every follow-up the road's outcome can reach runs: a block's, by
        # this call's row or the earliest on record, and the screen's own.
        async def document(conn: Any, document_id: int) -> dict[str, Any]:
            return {
                "id": document_id,
                "excerpt": _EXCERPT,
                "content_sha256": _PAYLOADS["jev_ask"]["subject_id"],
                "quarantined": False,
                "fetched_at": datetime(2026, 9, 28, 6, tzinfo=UTC),
            }

        async def not_quarantined(conn: Any, content: str) -> None:
            return None

        async def not_flagged(conn: Any, content: str) -> None:
            return None

        async def quarantine(conn: Any, content: str, reason: str) -> int:
            return 1

        async def earliest_block(conn: Any, **kwargs: Any) -> int:
            return 5

        async def answered(conn: Any, request_id: int) -> dict[str, Any]:
            return {"id": request_id, "model_answered": "jev-1.13.0"}

        monkeypatch.setattr(jev_repo, "get_document", document)
        monkeypatch.setattr(jev_repo, "content_quarantined", not_quarantined)
        monkeypatch.setattr(jev_repo, "screen_flag", not_flagged)
        monkeypatch.setattr(jev_repo, "quarantine_content", quarantine)
        monkeypatch.setattr(jev_repo, "content_block_request", earliest_block)
        monkeypatch.setattr(jev_repo, "get_request", answered)
    elif kind != "jev_probe":
        raise AssertionError(f"{kind} has no counted run: add one")


# ---------------------------------------------------------------------------
# The shared vocabulary of a job's failure
# ---------------------------------------------------------------------------


def test_the_retried_kinds_are_one_set_the_client_knows() -> None:
    from src.programme import jev_client, job_errors

    assert programme_main.PROBE_RETRIED_KINDS is job_errors.RETRIED_ERROR_KINDS
    assert job_errors.RETRIED_ERROR_KINDS <= set(jev_client.ERROR_KINDS)


def test_job_failed_error_is_one_class_wherever_it_is_imported() -> None:
    """
    Moved to ``job_errors`` so the handlers outside ``main`` can raise it, and
    re-exported from ``main``: two classes of one name would let a handler's
    verdict escape the ``except`` that turns it into a job's error.
    """
    from src.programme import jev_forward, jev_jobs, job_errors

    assert JobFailedError is job_errors.JobFailedError
    assert jev_forward.JobFailedError is job_errors.JobFailedError
    assert jev_jobs.JobFailedError is job_errors.JobFailedError


def test_the_programme_owns_the_forward_clock_and_the_reasks() -> None:
    assert set(JEV_HANDLERS) == {
        "jev_probe",
        "jev_regime",
        "jev_reask",
        "jev_web_ingest",
        "jev_ask",
    }
    kinds, _ = _every_enqueue()
    for kind in (
        "jev_probe",
        "jev_regime",
        "jev_reask",
        "ingest_reference_bars",
        "jev_web_ingest",
        "jev_ask",
    ):
        assert kinds.get(kind) == {"src/programme/jev_plan.py"}, (kind, kinds.get(kind))
    assert "ingest_reference_bars" in HANDLERS
    assert "jev_web_ingest" not in HANDLERS, "the web ingest is the programme's"


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


# ---------------------------------------------------------------------------
# The probe's verdict is its job's
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("result", "error", "retry"),
    [
        ({"status": "ok", "as_expected": True, "request_id": 1}, None, False),
        (
            {"status": "ok", "as_expected": False, "request_id": 1},
            "answered, but not as expected (request 1)",
            False,
        ),
        (
            {"status": "ok", "as_expected": None, "request_id": 1},
            "not measured (request 1)",
            False,
        ),
        (
            {"status": "invalid", "as_expected": None, "request_id": 2},
            "failed validation (request 2)",
            False,
        ),
        *[
            (
                {"status": "error", "error_kind": kind, "request_id": 3},
                f"the probe failed: {kind} (request 3)",
                kind in ("connection", "timeout", "rate_limited", "server"),
            )
            for kind in (
                "auth",
                "content_block",
                "invalid_request",
                "rate_limited",
                "server",
                "timeout",
                "connection",
                "response_shape",
                "client",
            )
        ],
        ({"status": "disabled"}, "switched off while the job ran", True),
        ({"status": "no_key"}, "no TypeSafe key is set", False),
        (
            {"status": "refused_budget"},
            "no call is left today in the request budget or in the probe "
            "lane's 10% share of it",
            False,
        ),
        ({"status": "refused_model"}, "not a usable pin", False),
        ({"status": "refused_limits"}, "over the size limits", False),
        # The vendor's standing refusals, remembered by the road from phase C:
        # each holds until the day, the words or the text changes, so none is
        # retried.
        (
            {"status": "auth_held"},
            "asks resume at 00:00 UTC, and a key replaced since is proved before "
            "then only by the dispatch-only key check (jev-check.yml)",
            False,
        ),
        ({"status": "set_refused"}, "a new version is needed", False),
        ({"status": "content_blocked"}, "blocked this state's content", False),
        ({"status": "quarantined"}, "quarantined", False),
        ({"status": "unscreened"}, "injection screen", False),
        ({"status": "surprising"}, "came to 'surprising'", False),
    ],
)
def test_every_probe_outcome_but_the_expected_answer_fails_the_job(
    result: dict[str, Any], error: str | None, retry: bool
) -> None:
    from src.programme.jev_client import ERROR_KINDS
    from src.programme.main import PROBE_RETRIED_KINDS, probe_verdict

    assert PROBE_RETRIED_KINDS <= set(ERROR_KINDS)
    found, again = probe_verdict(result)
    if error is None:
        assert found is None
    else:
        assert found is not None and error in found, found
    assert again is retry


def test_every_status_that_asked_nothing_says_why() -> None:
    """
    Every status the road can return without a call has a reason of its own,
    not the catch-all, and only a switch turned off mid-job is retried: every
    other one would be refused again.
    """
    from src.programme.jev_lane import UNRECORDED_STATUSES
    from src.programme.main import probe_verdict

    for status in (*UNRECORDED_STATUSES, "refused_budget", "refused_limits"):
        found, again = probe_verdict({"status": status})
        assert found is not None and "came to" not in found, (status, found)
        assert again is (status == "disabled"), status


def test_shutdown_waits_for_a_jev_call_and_not_for_the_kill() -> None:
    """
    Long enough for one call to finish — the client's whole retry budget and
    one more attempt — and short enough that the process is not killed first
    by programme.yml's ``--kill-after`` or compose's ``stop_grace_period``.
    """
    import re

    from src.programme import jev_client
    from src.programme.main import JEV_SHUTDOWN_GRACE_SECONDS

    root = pathlib.Path(__file__).resolve().parents[2]
    one_call = jev_client.RETRY_BUDGET_SECONDS + jev_client.REQUEST_TIMEOUT_SECONDS
    workflow = (root / ".github/workflows/programme.yml").read_text("utf-8")
    compose = (root / "docker-compose.yml").read_text("utf-8")
    (kill_after,) = re.findall(r"--kill-after=(\d+)", workflow)
    (grace,) = re.findall(r"stop_grace_period:\s*(\d+)s", compose)
    assert one_call < JEV_SHUTDOWN_GRACE_SECONDS < min(int(kill_after), int(grace))


# ---------------------------------------------------------------------------
# The programme changes no job it did not claim (phase D1)
# ---------------------------------------------------------------------------

#: Every function of the queue that changes a job's row.
JOB_CHANGERS = frozenset(
    {"enqueue", "claim", "extend_lease", "complete", "fail", "requeue_expired"}
)

#: The only state-changing queue calls in ``src/programme`` (docs/09, M6): the
#: loop's claim, completion, failure and lease of the jobs it claimed, and the
#: two producers' enqueue. Never ``requeue_expired``, which returns another
#: process's lapsed jobs to the queue: the worker's sweep, not the programme's.
PROGRAMME_JOB_CHANGES = frozenset(
    {
        ("src/programme/main.py", "claim"),
        ("src/programme/main.py", "complete"),
        ("src/programme/main.py", "fail"),
        ("src/programme/main.py", "extend_lease"),
        ("src/programme/jev_plan.py", "enqueue"),
        ("src/programme/tick.py", "enqueue"),
    }
)


def _job_changes(relative: str, source: str) -> tuple[set[str], list[str]]:
    """
    The queue's state-changing functions ``source`` refers to — called or not,
    by attribute, by an imported name, or by a literal handed to ``getattr`` —
    and every reference this scan cannot read: the queue module read by a
    computed name or as a namespace, and any write of the ``jobs`` table the
    SQL scanner finds, which goes around the module altogether.
    """
    from tests.unit.test_import_boundaries import _table_writes

    tree = ast.parse(source)
    bound = _modules_bound(relative, tree)
    found: set[str] = set()
    unread: list[str] = []

    def the_jobs_module(node: ast.AST) -> bool:
        return _dotted(node, bound) == JOBS_MODULE

    for node in ast.walk(tree):
        if isinstance(node, (ast.Attribute, ast.Name)):
            dotted = _dotted(node, bound)
            if dotted is not None and dotted.rpartition(".")[0] == JOBS_MODULE:
                if dotted.rpartition(".")[2] in JOB_CHANGERS:
                    found.add(dotted.rpartition(".")[2])
        elif isinstance(node, ast.ImportFrom) and node.module == JOBS_MODULE:
            found.update(a.name for a in node.names if a.name in JOB_CHANGERS)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "getattr" and len(node.args) >= 2:
                if the_jobs_module(node.args[0]):
                    name = node.args[1]
                    if isinstance(name, ast.Constant) and isinstance(name.value, str):
                        if name.value in JOB_CHANGERS:
                            found.add(name.value)
                    else:
                        unread.append(f"{relative}:{node.lineno}: {ast.unparse(node)}")
            elif node.func.id == "vars" and node.args and the_jobs_module(node.args[0]):
                unread.append(f"{relative}:{node.lineno}: {ast.unparse(node)}")
    for write in _table_writes(source, "jobs"):
        unread.append(f"{relative}:{write.line}: {write.verb} jobs")
    return found, unread


class TestTheProgrammeChangesOnlyTheJobsItClaimed:
    def test_nothing_in_the_programme_changes_a_job_it_did_not_claim(self) -> None:
        """
        docs/09, M6: Jev, and the programme around it, never resumes, retries,
        cancels or fails a job but its own. The loop's claim takes the kinds of
        ``JEV_HANDLERS`` alone, and the only state-changing calls of the queue
        in ``src/programme`` are the loop's, on the job it claimed, and the
        planner's and the tick's ``enqueue``; never ``requeue_expired``, and no
        SQL of its own on ``jobs``.
        """
        calls: set[tuple[str, str]] = set()
        unread: list[str] = []
        for path in sorted((SRC / "programme").rglob("*.py")):
            relative = path.relative_to(ROOT).as_posix()
            found, opaque = _job_changes(relative, path.read_text("utf-8"))
            calls |= {(relative, name) for name in found}
            unread += opaque
        assert not unread, "\n".join(unread)
        assert calls == PROGRAMME_JOB_CHANGES

    @pytest.mark.parametrize(
        ("source", "found", "unread"),
        [
            ("await job_repo.requeue_expired(conn)", {"requeue_expired"}, 0),
            ("await job_repo.fail(conn, job.id, 'e')", {"fail"}, 0),
            (
                "from src.db.repos.jobs import complete\n"
                "await complete(conn, job_id, {})",
                {"complete"},
                0,
            ),
            ("retry = job_repo.fail", {"fail"}, 0),
            ("await getattr(job_repo, 'claim')(conn, 'w')", {"claim"}, 0),
            ("await getattr(job_repo, NAME)(conn)", set(), 1),
            ("names = vars(job_repo)", set(), 1),
            ("await conn.execute(\"UPDATE jobs SET status = 'queued'\")", set(), 1),
            ("await conn.execute('DELETE FROM jobs WHERE id = $1', job_id)", set(), 1),
            ("await conn.copy_records_to_table('jobs', records=rows)", set(), 1),
            ("job = await job_repo.get(conn, job_id)", set(), 0),
            ("lease = job_repo.DEFAULT_LEASE", set(), 0),
            ("rows = await conn.fetch('SELECT id FROM jobs')", set(), 0),
            ("job.fail(reason)", set(), 0),
        ],
    )
    def test_the_scan_reads_each_spelling(
        self, source: str, found: set[str], unread: int
    ) -> None:
        prefix = "from src.db.repos import jobs as job_repo\n"
        changes, opaque = _job_changes("src/programme/x.py", prefix + source)
        assert changes == found
        assert len(opaque) == unread, opaque
