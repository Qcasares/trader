"""
test_jev_dark.py
----------------
Jev is dark until an operator turns it on: planned, claimed and asked nothing.

Phase C4 is the first phase that can make a call nobody asked for by hand — a
planner that runs every minute and a regime job every session — so this holds
the whole programme loop, as shipped, against a database migrated to head with
the switches as the migrations seed them:

* **Seeded, nothing happens.** The planner and the Jev loop run for several
  passes, with a key available, and plan no job, send no request and write no
  Jev row.
* **A job put in the queue by hand stays there.** One of every kind the
  programme owns, due now, is neither claimed nor attempted while a switch is
  off, so a queue filled while the programme was dark cannot spend when it is
  lit.
* **Each switch alone does nothing, and so does every pair but one.** The
  programme and Jev together plan and send exactly the daily probe, which is
  what they are for (docs/08, the switch order); with the decisions area as
  well, the forward clock starts; with the research area, the day's web
  ingest is planned and fetches its page, and asks nothing.
* **The research area on its own fetches nothing** (phase C6): with it on and
  the programme or Jev off, or with no key, no page is fetched and no job
  planned.

The client is a fake of ``jev_client.ask`` counting calls, and the fetcher a
fake of ``web_fetch.fetch`` counting fetches and handing over a synthetic page.
Runs on databases of its own, derived from ``TEST_DATABASE_URL``, since the
ledger refuses DELETE. Skipped unless ``TEST_DATABASE_URL`` is set.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest

pytest.importorskip("asyncpg")

import asyncpg  # noqa: E402

from src.db import migrate as migrations  # noqa: E402
from src.db.repos import flags as flag_repo  # noqa: E402
from src.db.repos import jobs as job_repo  # noqa: E402
from src.programme import (  # noqa: E402
    flags,
    jev_catalogue,
    jev_client,
    jev_clock,
    web_fetch,
)
from src.programme import main as programme_main  # noqa: E402
from src.programme.jev_questions import DECISION_REGIME  # noqa: E402
from src.programme.main import JEV_HANDLERS, Programme  # noqa: E402
from tests.fakes import pwb_readme  # noqa: E402

TEST_DSN = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="TEST_DATABASE_URL not set")

KEY = "ts-test-key-not-a-secret"
PASSES = 5

#: Every table migration 0012 created for Jev.
JEV_TABLES = (
    "jev_requests",
    "jev_answers",
    "jev_signals",
    "web_documents",
    "jev_labels",
    "jev_evaluations",
)

PROGRAMME = flags.PROGRAMME_ENABLED
JEV = flags.JEV_ENABLED
DECISIONS = f"{flags.JEV_AREA_PREFIX}decisions"
RESEARCH = f"{flags.JEV_AREA_PREFIX}research"


def _derived(suffix: str) -> str:
    base, _, tail = TEST_DSN.partition("?")
    return f"{base}_{suffix}?{tail}" if tail else f"{base}_{suffix}"


def _name(dsn: str) -> str:
    return dsn.partition("?")[0].rsplit("/", 1)[-1]


async def _recreate(dsn: str) -> None:
    admin = await asyncpg.connect(TEST_DSN)
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{_name(dsn)}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{_name(dsn)}"')
    finally:
        await admin.close()
    await migrations.migrate(dsn)


async def _drop(dsn: str) -> None:
    admin = await asyncpg.connect(TEST_DSN)
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{_name(dsn)}" WITH (FORCE)')
    finally:
        await admin.close()


@pytest.fixture
async def seeded() -> AsyncIterator[tuple[str, asyncpg.Connection]]:
    """A database migrated to head and touched by nothing else: every seed."""
    dsn = _derived("jev_dark")
    await _recreate(dsn)
    connection = await asyncpg.connect(dsn)
    try:
        yield dsn, connection
    finally:
        await connection.close()
        await _drop(dsn)


class _Client:
    """``jev_client.ask``, answering every question cleanly, counting calls."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def ask(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        answers: dict[str, Any] = {}
        for key, question in kwargs["questions"].items():
            if question["type"] == "noul":
                answers[key] = {"type": "noul", "noul": 0.99}
            else:
                options = list(question["criteria"])
                answers[key] = {
                    "type": "choice",
                    "choice": options[0],
                    "confidence": 0.5,
                    "probabilities": dict(
                        zip(options, (0.7, 0.1, 0.1, 0.1), strict=True)
                    ),
                }
        body = json.dumps({"model": kwargs["model"], "answers": answers, "usage": {}})
        return jev_client.JevCall(
            http_status=200,
            raw_body=body,
            request_id="req_dark",
            latency_ms=50,
            error_class=None,
            error_kind=None,
            input_tokens=None,
            output_tokens=None,
            wire_body=body.encode("utf-8"),
        )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> _Client:
    fake = _Client()
    monkeypatch.setattr(jev_client, "ask", fake.ask)
    return fake


class _Fetcher:
    """``web_fetch.fetch``, handing over a synthetic page, counting fetches."""

    def __init__(self) -> None:
        self.fetched: list[Any] = []

    async def fetch(self, source: Any, **kwargs: Any) -> Any:
        self.fetched.append(source)
        return pwb_readme.fetched(pwb_readme.readme())


@pytest.fixture
def fetcher(monkeypatch: pytest.MonkeyPatch) -> _Fetcher:
    fake = _Fetcher()
    monkeypatch.setattr(web_fetch, "fetch", fake.fetch)
    return fake


async def _run_the_loop(
    monkeypatch: pytest.MonkeyPatch,
    dsn: str,
    passes: int = PASSES,
    key: str | None = KEY,
) -> None:
    """
    The programme's Jev loop as shipped, planner and drain, for ``passes``
    passes, with a TypeSafe key available throughout unless ``key`` is
    ``None``: dark must not depend on a missing key.
    """
    monkeypatch.setattr(programme_main, "JEV_POLL_SECONDS", 0.01)
    monkeypatch.setattr(programme_main, "JEV_PLAN_SECONDS", 0.0)
    programme = Programme(dsn, api_key=None, secrets_key="", typesafe_key=key)
    programme._pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
    drain = programme._drain_jev
    seen = 0

    async def counted() -> bool:
        nonlocal seen
        seen += 1
        if seen >= passes:
            programme.stop()
        return await drain()

    monkeypatch.setattr(programme, "_drain_jev", counted)
    try:
        await asyncio.wait_for(programme._jev_loop(), timeout=60)
    finally:
        await programme._pool.close()
    assert seen == passes


async def _jev_rows(conn: asyncpg.Connection) -> dict[str, int]:
    return {
        table: await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
        for table in JEV_TABLES
    }


async def _set(conn: asyncpg.Connection, values: dict[str, Any]) -> None:
    for key, value in values.items():
        await flag_repo.set_flag(conn, key, value, "test")


#: A payload each programme kind would accept, so a claim would run it.
_PAYLOADS: dict[str, dict[str, Any]] = {
    "jev_probe": {},
    "jev_regime": {"session": "2026-09-28", "set": "decision.regime", "version": 1},
    "jev_reask": {"request_id": 1},
    "jev_web_ingest": {"source": "pwb-readme"},
}


class TestSeededItIsDark:
    async def test_the_seeds_are_off(
        self, seeded: tuple[str, asyncpg.Connection]
    ) -> None:
        _, conn = seeded
        assert await flags.programme_enabled(conn) is False
        assert await flags.jev_enabled(conn) is False
        for area in jev_catalogue.AREAS:
            assert await flags.jev_area_enabled(conn, area) is False, area

    async def test_the_loop_plans_nothing_sends_nothing_writes_nothing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        seeded: tuple[str, asyncpg.Connection],
        client: _Client,
        fetcher: _Fetcher,
    ) -> None:
        dsn, conn = seeded
        await _run_the_loop(monkeypatch, dsn)
        assert await conn.fetchval("SELECT COUNT(*) FROM jobs") == 0
        assert client.calls == [] and fetcher.fetched == []
        assert set((await _jev_rows(conn)).values()) == {0}

    async def test_a_job_queued_by_hand_for_every_programme_kind_stays_queued(
        self,
        monkeypatch: pytest.MonkeyPatch,
        seeded: tuple[str, asyncpg.Connection],
        client: _Client,
        fetcher: _Fetcher,
    ) -> None:
        dsn, conn = seeded
        assert set(_PAYLOADS) == set(JEV_HANDLERS), "a new kind needs a payload here"
        ids = {
            kind: await job_repo.enqueue(conn, kind, payload)
            for kind, payload in _PAYLOADS.items()
        }
        await _run_the_loop(monkeypatch, dsn)
        for kind, job_id in ids.items():
            row = await conn.fetchrow(
                "SELECT status, attempts, locked_by, started_at FROM jobs "
                "WHERE id = $1",
                job_id,
            )
            assert row["status"] == "queued", kind
            assert row["attempts"] == 0, f"{kind}: an attempt was spent while dark"
            assert row["locked_by"] is None and row["started_at"] is None, kind
        assert await conn.fetchval("SELECT COUNT(*) FROM jobs") == len(ids)
        assert client.calls == [] and fetcher.fetched == []
        assert set((await _jev_rows(conn)).values()) == {0}


#: The switches the matrix turns on and off, each alone and in every company.
SWITCHES = (PROGRAMME, JEV, DECISIONS, RESEARCH)


def _combinations() -> list[tuple[str, ...]]:
    return [
        combo
        for size in range(len(SWITCHES) + 1)
        for combo in itertools.combinations(SWITCHES, size)
    ]


class TestTheSwitchMatrix:
    @pytest.mark.parametrize(
        "on", _combinations(), ids=lambda on: "+".join(on) or "none"
    )
    async def test_what_each_combination_plans_and_sends(
        self,
        monkeypatch: pytest.MonkeyPatch,
        seeded: tuple[str, asyncpg.Connection],
        client: _Client,
        fetcher: _Fetcher,
        on: tuple[str, ...],
    ) -> None:
        """
        Nothing unless both the programme and Jev are on. Those two alone plan
        and send the daily probe and nothing else; with the decisions area too,
        the forward clock's jobs are planned for the sessions ahead, each due
        at its own minute after a close; with the research area, the day's
        web ingest, which fetches its page once and asks nothing.
        """
        dsn, conn = seeded
        await _set(conn, {switch: switch in on for switch in SWITCHES})
        now = datetime.now(UTC)

        await _run_the_loop(monkeypatch, dsn)

        keys = {
            row["dedupe_key"] for row in await conn.fetch("SELECT dedupe_key FROM jobs")
        }
        lit = PROGRAMME in on and JEV in on
        if not lit:
            assert keys == set()
            assert client.calls == [] and fetcher.fetched == []
            assert set((await _jev_rows(conn)).values()) == {0}
            return

        probe = {f"jev_probe:{now.date().isoformat()}"}
        probes = [c for c in client.calls if c["questions"].keys() == {"about_the_sun"}]
        assert len(probes) == 1, "the daily probe is asked once, and only once"
        assert (await _jev_rows(conn))["jev_signals"] == 0
        ingest: set[str] = set()
        if RESEARCH in on:
            ingest = {f"jev_web_ingest:pwb-readme:{now.date().isoformat()}"}
            assert len(fetcher.fetched) == 1, "the day's page is fetched once"
            assert (await _jev_rows(conn))["web_documents"] > 0
        else:
            assert fetcher.fetched == []
            assert (await _jev_rows(conn))["web_documents"] == 0
        if DECISIONS not in on:
            assert keys == probe | ingest
            assert len(client.calls) == 1, "the web ingest asked something"
            return
        clock = set()
        for session in jev_clock.sessions_to_plan(now):
            clock.add(jev_clock.reference_job_key(session))
            clock.add(jev_clock.regime_job_key(DECISION_REGIME, session))
        assert keys == probe | clock | ingest


class TestTheResearchAreaAloneFetchesNothing:
    @pytest.mark.parametrize(
        ("on", "key"),
        [
            pytest.param((RESEARCH,), KEY, id="research-alone"),
            pytest.param((RESEARCH, PROGRAMME), KEY, id="research-and-programme"),
            pytest.param((RESEARCH, JEV), KEY, id="research-and-jev"),
            pytest.param((RESEARCH, PROGRAMME, JEV), None, id="everything-but-a-key"),
        ],
    )
    async def test_no_page_is_fetched_and_no_job_planned(
        self,
        monkeypatch: pytest.MonkeyPatch,
        seeded: tuple[str, asyncpg.Connection],
        client: _Client,
        fetcher: _Fetcher,
        on: tuple[str, ...],
        key: str | None,
    ) -> None:
        """
        The research area needs the programme and Jev, each read by its own
        reader, and the planner needs a key, though the ingest asks Jev
        nothing (design R28): with any of them missing the loop plans no job,
        fetches no page and writes no row.
        """
        dsn, conn = seeded
        await _set(conn, {switch: switch in on for switch in SWITCHES})

        await _run_the_loop(monkeypatch, dsn, key=key)

        assert await conn.fetchval("SELECT COUNT(*) FROM jobs") == 0
        assert fetcher.fetched == [] and client.calls == []
        assert set((await _jev_rows(conn)).values()) == {0}


class TestAJobQueuedBeforeTheKeyOrThePinWentFetchesNothing:
    """
    The planner plans the ingest only with a key and a usable pin (design
    R28), and a job it queued can be claimed after either went: the programme
    or Jev switched off between the plan and the claim, the key or the pin
    removed, and the switches back on (open item 53). Its handler reads both
    again, so such a job fails for good, fetching nothing, as the probe does
    (C6's review).
    """

    @pytest.mark.parametrize(
        ("pin", "key"),
        [
            pytest.param(None, None, id="no-key"),
            pytest.param("jev-latest", KEY, id="an-alias-where-the-pin-was"),
        ],
    )
    async def test_it_fails_for_good_and_fetches_nothing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        seeded: tuple[str, asyncpg.Connection],
        client: _Client,
        fetcher: _Fetcher,
        pin: str | None,
        key: str | None,
    ) -> None:
        dsn, conn = seeded
        await _set(conn, {PROGRAMME: True, JEV: True, RESEARCH: True})
        if pin is not None:
            await _set(conn, {flags.JEV_MODEL: pin})
        job_id = await job_repo.enqueue(
            conn,
            "jev_web_ingest",
            dict(_PAYLOADS["jev_web_ingest"]),
            dedupe_key=f"jev_web_ingest:pwb-readme:{datetime.now(UTC).date()}",
        )

        await _run_the_loop(monkeypatch, dsn, key=key)

        job = await conn.fetchrow(
            "SELECT status, attempts, error FROM jobs WHERE id = $1", job_id
        )
        assert (job["status"], job["attempts"]) == ("failed", 1), job["error"]
        assert job["error"].endswith("nothing was fetched"), job["error"]
        assert await conn.fetchval("SELECT COUNT(*) FROM jobs") == 1
        assert fetcher.fetched == [] and client.calls == []
        assert set((await _jev_rows(conn)).values()) == {0}
