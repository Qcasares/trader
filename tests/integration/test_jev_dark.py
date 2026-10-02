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
* **Each area asks its own sets** (phases C7 and C8): the guardrails area
  joins the matrix. From an empty ledger only the research area's ingest
  stores text, so a text the ingest stored is screened and, once cleared,
  described only with both areas on. A text already stored is another
  matter, and the design's section 8 is the rule: the guardrails area alone
  screens a stored text the screen has not answered, sending it, and the
  research area alone describes one the screen cleared earlier
  (:class:`TestATextAlreadyStoredIsAskedAboutByEachAreasOwnSets`). The first
  record of C7+C8 said either area alone sends nothing about a stored text,
  which held only from an empty ledger.
* **The research area on its own fetches nothing** (phase C6): with it on and
  the programme or Jev off, or with no key, no page is fetched and no job
  planned.
* **The findings area asks about model-written findings, and only with the
  programme and Jev** (phase D2): it joins the matrix, with a model-written
  finding and an operator's stored before the loop runs; the findings sets
  ask about the first exactly when the programme, Jev and the findings area
  are all on, and never about the second.
* **The ops area asks about a failed job's error, and only with the detail
  switch** (phase D3): a failed job whose error code leaves to Jev is stored
  before every case of the matrix, where the ops area is off, and is asked
  about in none; the programme, Jev, the ops area and the detail switch make
  a matrix of their own (:class:`TestTheOpsMatrix`), in which the ops set
  asks about the job's skeleton exactly when all four are on, so the ops area
  on with the detail switch off plans and sends nothing (docs/09, owner item
  9.1's default). A failed job stored while dark is asked nothing. The arming
  switch has no consumer until D4 and plans nothing of its own
  (:class:`TestTheArmingSwitchHasNoConsumerYet`); until D3 that class held
  the ops area and the detail switch to the same.

The client is a fake of ``jev_client.ask`` counting calls, and the fetcher a
fake of ``web_fetch.fetch`` counting fetches and handing over a synthetic page.
Runs on databases of its own, derived from ``TEST_DATABASE_URL``, since the
ledger refuses DELETE. Skipped unless ``TEST_DATABASE_URL`` is set.
"""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import json
import os
import uuid
from collections.abc import AsyncIterator, Sequence
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
    jev_chips,
    jev_client,
    jev_clock,
    jev_prereg,
    jev_questions,
    jev_repo,
    repo,
    web_fetch,
)
from src.programme import main as programme_main  # noqa: E402
from src.programme.jev_hash import text_sha256  # noqa: E402
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
GUARDRAILS = f"{flags.JEV_AREA_PREFIX}guardrails"
FINDINGS = f"{flags.JEV_AREA_PREFIX}findings"
OPS = f"{flags.JEV_AREA_PREFIX}ops"
DETAIL = flags.JEV_SEND_INTERNAL_DETAIL

#: The two findings stored before a matrix case runs: one the programme's
#: model raised, which the findings sets ask about, and an operator's, which
#: they never do. Invented.
MODEL_FINDING = "Invented Fills Assumed at Prices No Venue Gave"
OPERATORS_FINDING = "An Operator's Invented Finding"

#: The failed job stored before a case runs (phase D3): a backtest, a kind
#: whose errors code triages, failing with an invented error code leaves to
#: Jev, whose skeleton holds enough words to be asked about.
FAILED_KIND = "backtest"
FAILED_ERROR = 'duplicate key value violates unique constraint "invented_key"'


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
    """
    ``jev_client.ask``, answering every question cleanly, counting calls: a
    Noul ``true``, but the injection screen and the card check ``false``, so
    a text screened is cleared rather than quarantined.
    """

    #: The Noul questions answered ``false``.
    CLEARED = frozenset({"addressed_to_ai", "performance_claim"})

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def ask(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        answers: dict[str, Any] = {}
        for key, question in kwargs["questions"].items():
            if question["type"] == "noul":
                noul = 0.02 if key in self.CLEARED else 0.99
                answers[key] = {"type": "noul", "noul": noul}
            else:
                # The first option at 0.7 and the rest sharing 0.3, however
                # many there are: the regime has four, the catalogue more.
                options = list(question["criteria"])
                rest = round(0.3 / (len(options) - 1), 6)
                probabilities = dict.fromkeys(options, rest)
                probabilities[options[0]] = round(1 - rest * (len(options) - 1), 6)
                answers[key] = {
                    "type": "choice",
                    "choice": options[0],
                    "confidence": 0.5,
                    "probabilities": probabilities,
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


async def _raise_findings(conn: asyncpg.Connection) -> None:
    """:data:`MODEL_FINDING` and :data:`OPERATORS_FINDING`, as each writer raises it."""
    await repo.raise_finding(
        conn, None, "independent_risk", "high", MODEL_FINDING, origin="model"
    )
    await repo.raise_finding(
        conn, None, "operations", "high", OPERATORS_FINDING, origin="operator"
    )


async def _fail_a_job(conn: asyncpg.Connection) -> uuid.UUID:
    """
    :data:`FAILED_ERROR`, a job that failed an hour ago by the database's
    clock, stored through the shipped writer and ended as the queue ends one;
    returns its id.
    """
    job_id = await job_repo.enqueue(
        conn, FAILED_KIND, {}, dedupe_key=f"test:{uuid.uuid4()}"
    )
    assert job_id is not None
    await conn.execute(
        "UPDATE jobs SET status = 'failed', attempts = 1, error = $2, "
        "started_at = now() - interval '1 hour', "
        "finished_at = now() - interval '1 hour' WHERE id = $1",
        job_id,
        FAILED_ERROR,
    )
    return job_id


async def _job_row(conn: asyncpg.Connection, job_id: uuid.UUID) -> dict[str, Any]:
    """Every column of the job ``job_id``."""
    return dict(await conn.fetchrow("SELECT * FROM jobs WHERE id = $1", job_id))


def _failed_state() -> dict[str, Any]:
    """What the ops set would send about :data:`FAILED_ERROR`: its skeleton."""
    tokens = jev_chips.residue_skeleton(FAILED_KIND, FAILED_ERROR)
    assert tokens is not None
    return jev_questions.OPS_JOB_ERROR.dump_state(
        jev_questions.JobErrorState(job_kind=FAILED_KIND, error=tokens)
    )


def _about_jobs(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The states of the calls about a failed job's error."""
    return [call["state"] for call in calls if "error" in call["state"]]


async def _planned(
    conn: asyncpg.Connection, stored: Sequence[uuid.UUID] = ()
) -> set[str]:
    """The dedupe key of every job but those the test stored itself."""
    rows = await conn.fetch(
        "SELECT dedupe_key FROM jobs WHERE NOT (id = ANY($1::uuid[]))", list(stored)
    )
    return {row["dedupe_key"] for row in rows}


def _finding_asks(on: tuple[str, ...], day: Any) -> set[str]:
    """The findings sets' asks a lit loop plans about the model's finding."""
    if FINDINGS not in on:
        return set()
    return {
        jev_repo.ask_job_key(name, 1, "finding_title", text_sha256(MODEL_FINDING), day)
        for name in ("findings.owner", "findings.severity")
    }


#: A payload each programme kind would accept, so a claim would run it.
_PAYLOADS: dict[str, dict[str, Any]] = {
    "jev_probe": {},
    "jev_regime": {"session": "2026-09-28", "set": "decision.regime", "version": 1},
    "jev_reask": {"request_id": 1},
    "jev_web_ingest": {"source": "pwb-readme"},
    "jev_ask": {
        "set": "guardrail.injection",
        "version": 1,
        "subject_type": "web_excerpt",
        "subject_id": hashlib.sha256(b"An Invented Title").hexdigest(),
        "source_id": 1,
        **(jev_prereg.plans_in_force("guardrail.injection", 1) or {}),
    },
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

    async def test_findings_stored_while_dark_are_asked_nothing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        seeded: tuple[str, asyncpg.Connection],
        client: _Client,
        fetcher: _Fetcher,
    ) -> None:
        """Phase D2: the findings area is seeded off, so a stored finding waits."""
        dsn, conn = seeded
        await _raise_findings(conn)
        await _run_the_loop(monkeypatch, dsn)
        assert await conn.fetchval("SELECT COUNT(*) FROM jobs") == 0
        assert client.calls == [] and fetcher.fetched == []
        assert set((await _jev_rows(conn)).values()) == {0}

    async def test_a_job_that_failed_while_dark_is_asked_nothing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        seeded: tuple[str, asyncpg.Connection],
        client: _Client,
        fetcher: _Fetcher,
    ) -> None:
        """
        Phase D3: the ops area and the detail switch are seeded off, so a
        failed job's error waits, and the job is left as it failed.
        """
        dsn, conn = seeded
        job_id = await _fail_a_job(conn)
        before = await _job_row(conn, job_id)
        await _run_the_loop(monkeypatch, dsn)
        assert await _planned(conn, [job_id]) == set()
        assert await _job_row(conn, job_id) == before
        assert client.calls == [] and fetcher.fetched == []
        assert set((await _jev_rows(conn)).values()) == {0}


#: The switches the matrix turns on and off, each alone and in every company.
SWITCHES = (PROGRAMME, JEV, DECISIONS, RESEARCH, GUARDRAILS, FINDINGS)


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
        web ingest, which fetches its page once and asks nothing. From phases
        C7 and C8, from this empty ledger, a text the ingest stored is asked
        about only with both the guardrails and the research areas on —
        screened, then, once cleared, described — since only the research
        area stores one and only the guardrails area screens it. Text already
        stored is asked about by each area's own sets alone: the next class.
        From phase D2 a model-written finding and an operator's are stored
        first: the findings sets ask about the first's title exactly when the
        findings area is on with the programme and Jev, and never the second's.
        From phase D3 a failed job whose error code leaves to Jev is stored
        too, and with the ops area off in every case here nothing asks about
        it (:class:`TestTheOpsMatrix` turns it on).
        """
        dsn, conn = seeded
        await _raise_findings(conn)
        failed = await _fail_a_job(conn)
        await _set(conn, {switch: switch in on for switch in SWITCHES})
        now = datetime.now(UTC)

        await _run_the_loop(monkeypatch, dsn)

        keys = await _planned(conn, [failed])
        assert _about_jobs(client.calls) == [], "a failed job's error was sent"
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
        asks: set[str] = set()
        contents = [
            row["content_sha256"]
            for row in await conn.fetch(
                "SELECT DISTINCT content_sha256 FROM web_documents "
                "WHERE NOT quarantined"
            )
        ]
        if RESEARCH in on and GUARDRAILS in on:
            for content in contents:
                for name in ("guardrail.injection", "research.catalogue"):
                    asks.add(
                        jev_repo.ask_job_key(
                            name, 1, "web_excerpt", content, now.astimezone(UTC).date()
                        )
                    )
        about_text = [c for c in client.calls if "excerpt" in c["state"]]
        assert len(about_text) == len(asks), "a text was asked about, or not, wrongly"
        findings = _finding_asks(on, now.astimezone(UTC).date())
        about_findings = [
            c for c in client.calls if c["state"].get("title") == MODEL_FINDING
        ]
        assert len(about_findings) == len(findings), "a finding asked about wrongly"
        assert not [
            c for c in client.calls if c["state"].get("title") == OPERATORS_FINDING
        ], "an operator's finding was sent"
        asks |= findings
        assert len(client.calls) == 1 + len(asks)
        clock = set()
        if DECISIONS in on:
            for session in jev_clock.sessions_to_plan(now):
                clock.add(jev_clock.reference_job_key(session))
                clock.add(jev_clock.regime_job_key(DECISION_REGIME, session))
        assert keys == probe | clock | ingest | asks


#: The switches the ops matrix turns on and off, each alone and in every
#: company: the programme, Jev, the ops area and the detail switch.
OPS_SWITCHES = (PROGRAMME, JEV, OPS, DETAIL)


def _ops_combinations() -> list[tuple[str, ...]]:
    return [
        combo
        for size in range(len(OPS_SWITCHES) + 1)
        for combo in itertools.combinations(OPS_SWITCHES, size)
    ]


class TestTheOpsMatrix:
    @pytest.mark.parametrize(
        "on", _ops_combinations(), ids=lambda on: "+".join(on) or "none"
    )
    async def test_a_failed_job_is_asked_about_only_with_all_four(
        self,
        monkeypatch: pytest.MonkeyPatch,
        seeded: tuple[str, asyncpg.Connection],
        client: _Client,
        fetcher: _Fetcher,
        on: tuple[str, ...],
    ) -> None:
        """
        Phase D3 (docs/09, section 13): a failed job whose error code leaves
        to Jev is stored, and the programme, Jev, the ops area and the detail
        switch are set as the case says, every other area off. Nothing unless
        the programme and Jev are both on; those two plan and send the daily
        probe; the ops set's ask about the job's skeleton is planned, and the
        skeleton alone sent, exactly when the ops area and the detail switch
        are on as well, each read through its own fail-closed reader — the ops
        area on with the detail switch off plans nothing (owner item 9.1's
        default). The failed job itself is left as it failed.
        """
        dsn, conn = seeded
        failed = await _fail_a_job(conn)
        before = await _job_row(conn, failed)
        await _set(conn, {switch: switch in on for switch in OPS_SWITCHES})
        now = datetime.now(UTC)

        await _run_the_loop(monkeypatch, dsn)

        keys = await _planned(conn, [failed])
        assert await _job_row(conn, failed) == before, "the failed job was changed"
        if not (PROGRAMME in on and JEV in on):
            assert keys == set()
            assert client.calls == [] and fetcher.fetched == []
            assert set((await _jev_rows(conn)).values()) == {0}
            return
        probe = {f"jev_probe:{now.date().isoformat()}"}
        asks: set[str] = set()
        if OPS in on and DETAIL in on:
            state = _failed_state()
            address = jev_questions.job_error_subject(
                jev_questions.JobErrorState(
                    job_kind=state["job_kind"], error=tuple(state["error"])
                )
            )
            asks = {
                jev_repo.ask_job_key(
                    "ops.job_error", 1, "job_error", address, now.date()
                )
            }
            assert _about_jobs(client.calls) == [state], "not the skeleton alone"
            job = await conn.fetchrow(
                "SELECT status, payload FROM jobs WHERE dedupe_key = $1", *asks
            )
            assert job["status"] == "succeeded"
            assert json.loads(job["payload"])["source_id"] == str(failed)
        else:
            assert _about_jobs(client.calls) == [], "a failed job's error was sent"
        assert keys == probe | asks
        assert len(client.calls) == 1 + len(asks)
        assert fetcher.fetched == []


class TestTheArmingSwitchHasNoConsumerYet:
    """
    The arming switch exists from phase D1 and has no consumer until D4, so
    with every other switch on — the ops area and the detail switch among
    them, a model-written finding and a failed job stored for their sets to
    ask about — the loop plans and sends exactly the same with it on as off;
    and on alone it plans nothing: the docs/09 section 13 matrix's "the
    arming switch alone plans nothing". Until phase D3 this class held the
    ops area and the detail switch to the same, which D3 gave a consumer;
    :class:`TestTheOpsMatrix` holds them now.
    """

    async def test_with_every_other_switch_on_it_changes_nothing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        seeded: tuple[str, asyncpg.Connection],
        client: _Client,
        fetcher: _Fetcher,
    ) -> None:
        dsn, conn = seeded
        await _raise_findings(conn)
        failed = await _fail_a_job(conn)
        await _set(conn, {**dict.fromkeys(SWITCHES, True), OPS: True, DETAIL: True})
        await _run_the_loop(monkeypatch, dsn)
        planned = await _planned(conn, [failed])
        sent = len(client.calls)
        assert any(key.startswith("jev_ask:findings.") for key in planned)
        assert any(key.startswith("jev_ask:ops.job_error@") for key in planned)

        await _set(conn, {flags.JEV_ARM_CARD_CHECK: True})
        await _run_the_loop(monkeypatch, dsn)
        assert await _planned(conn, [failed]) == planned, (
            "the arming switch planned something"
        )
        assert len(client.calls) == sent, "the arming switch sent something"

    async def test_on_alone_it_plans_nothing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        seeded: tuple[str, asyncpg.Connection],
        client: _Client,
        fetcher: _Fetcher,
    ) -> None:
        dsn, conn = seeded
        await _raise_findings(conn)
        failed = await _fail_a_job(conn)
        await _set(conn, {flags.JEV_ARM_CARD_CHECK: True})
        await _run_the_loop(monkeypatch, dsn)
        assert await _planned(conn, [failed]) == set()
        assert client.calls == [] and fetcher.fetched == []
        assert set((await _jev_rows(conn)).values()) == {0}


#: Two invented excerpts stored before the areas are set: one the screen
#: cleared earlier, and one it has not answered. Neither is on the page the
#: fake fetcher hands over.
CLEARED_EARLIER = "Invented Breadth Signals in Imaginary Sector Funds"
NOT_SCREENED = "Made-Up Auction Cycles in Fictional Sovereign Notes"


async def _store(conn: asyncpg.Connection, excerpt: str) -> None:
    await jev_repo.insert_documents(
        conn,
        [
            jev_repo.DocumentRow(
                source="another_feed",
                url="https://example.invalid/feed",
                excerpt=excerpt,
            )
        ],
    )


def _asked_about(calls: list[dict[str, Any]], excerpt: str) -> list[list[str]]:
    """The questions of each call about ``excerpt``, in the order sent."""
    return [
        sorted(call["questions"])
        for call in calls
        if call["state"] == {"excerpt": excerpt}
    ]


class TestATextAlreadyStoredIsAskedAboutByEachAreasOwnSets:
    """
    The matrix above starts from an empty ledger, where text is stored only
    when the research area ingests it in the same run, so it could not see
    what each area does on its own with text already stored. The road reads a
    set's own lane's area and no other (design section 8; ``jev_lane``), and
    the planner plans each set behind it: the guardrails area alone screens a
    stored text the screen has not answered, and so sends it; the research
    area alone describes a text the screen cleared earlier. Turning research
    off stops the catalogue and the ingest, not the screen. C7+C8's review
    found the first record saying either area alone sends nothing about a
    stored text.
    """

    @pytest.mark.parametrize(
        ("guardrails", "research"),
        list(itertools.product((False, True), repeat=2)),
        ids=["neither", "research", "guardrails", "both"],
    )
    async def test_each_area_asks_its_own_sets_about_what_is_stored(
        self,
        monkeypatch: pytest.MonkeyPatch,
        seeded: tuple[str, asyncpg.Connection],
        client: _Client,
        fetcher: _Fetcher,
        guardrails: bool,
        research: bool,
    ) -> None:
        dsn, conn = seeded
        await _set(conn, {PROGRAMME: True, JEV: True, GUARDRAILS: True})
        await _store(conn, CLEARED_EARLIER)
        await _run_the_loop(monkeypatch, dsn)
        assert _asked_about(client.calls, CLEARED_EARLIER) == [["addressed_to_ai"]]

        await _store(conn, NOT_SCREENED)
        await _set(conn, {GUARDRAILS: guardrails, RESEARCH: research})
        client.calls.clear()
        await _run_the_loop(monkeypatch, dsn)

        described = [["asset_class", "mechanism"]]
        screened = [["addressed_to_ai"]]
        assert _asked_about(client.calls, CLEARED_EARLIER) == (
            described if research else []
        ), "the catalogue follows the research area alone"
        assert _asked_about(client.calls, NOT_SCREENED) == (
            screened + (described if research else []) if guardrails else []
        ), "the screen follows the guardrails area alone, and sends the text"
        assert (len(fetcher.fetched) == 1) is research


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
