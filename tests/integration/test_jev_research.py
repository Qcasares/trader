"""
test_jev_research.py
--------------------
Phases C7 and C8 on PostgreSQL, through the programme's own loop.

The planner and the drain run as shipped, every pass of them; so do the
handlers, the lane, the validator, the ledger and the schema. Nothing is
replaced but the vendor — a fake of ``jev_client.ask`` that answers each
question about each text as a test scripts it — and the page, handed over by a
stand-in for ``web_fetch.fetch``, except in the canary, which fetches it with
the real fetcher over local HTTPS as C6's canary does, admitting 127.0.0.1 in
the address check inside the test alone. What must hold:

* **Ingest, then the screen, then the catalogue.** A page read is screened,
  content by content, and only what the screen cleared is described; what it
  found addressed to an AI system is quarantined, in the design's words.
* **A held text is never described.** A screen answer that measured nothing —
  a tie — is canonical, so the text is never screened again under this version
  and pin, and never cleared.
* **Quarantine is by content**, across two sources, from one ask.
* **Three failed calls retire a subject**, and a subject is planned again by
  its own key: not twice a day, not while a job for it waits, and again on a
  later day while it has failed fewer than three times.
* **The source's labels are recorded once.**
* **A block's quarantine survives a failed write** (section 10d of the scope):
  the job's next attempt, refused by the road for the block on record, makes
  it; and when every attempt fails, a later day's pass plans the screen for
  the blocked content again, and that makes it, with no call.
* **Every answer is recorded with its plans** (section 10a), however its job
  ends: a response refused whole, and an answer whose follow-up failed on
  every attempt, are named by their failed job beside the plans its payload
  was planned under, and the queue keeps an attempt's record when a later
  one records nothing.
* **The hypothesis and card asks change nothing**: the hypotheses, candidates
  and findings tables are what they were whatever Jev answers, or fails to.
* **The canary**: a token in every title of a page read, screened and
  described is in ``web_documents.excerpt`` and ``jev_requests.state`` and in
  no other text or JSON column of any table, no log record at DEBUG, and no
  job's payload, result or error — a title refused when its state is built
  included, whose error pydantic's message would have quoted.

Each test runs on a database of its own, derived from ``TEST_DATABASE_URL``:
the ledger refuses DELETE. Every title is invented, since the catalogue the
excerpts come from publishes no licence. Skipped unless ``TEST_DATABASE_URL``
is set.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
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
    jev_plan,
    jev_prereg,
    jev_questions,
    jev_repo,
    repo,
    web_fetch,
    web_sources,
)
from src.programme import main as programme_main  # noqa: E402
from src.programme.jev_hash import text_sha256  # noqa: E402
from src.programme.main import Programme  # noqa: E402
from tests.fakes import pwb_readme  # noqa: E402
from tests.fakes.web_server import (  # noqa: E402
    LOOPBACK,
    Authority,
    FakeHTTPS,
    Reply,
    RoutingResolver,
)
from tests.integration.test_web_ingest import (  # noqa: E402
    _columns_holding,
    _logged,
    _token,
)

TEST_DSN = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="TEST_DATABASE_URL not set")

KEY = "ts-test-key-not-a-secret"
PIN = "jev-1.13.0"
SOURCE = pwb_readme.SOURCE
RESEARCH = f"{flags.JEV_AREA_PREFIX}research"
GUARDRAILS = f"{flags.JEV_AREA_PREFIX}guardrails"

#: The switches every test starts with: the programme, Jev, and both areas the
#: asks need; the forward clock's area stays off.
ON: dict[str, Any] = {
    flags.PROGRAMME_ENABLED: True,
    flags.JEV_ENABLED: True,
    RESEARCH: True,
    GUARDRAILS: True,
}

SCREEN = jev_questions.GUARDRAIL_INJECTION
CATALOGUE = jev_questions.RESEARCH_CATALOGUE
HYPOTHESIS = jev_questions.RESEARCH_HYPOTHESIS
CARD = jev_questions.GUARDRAIL_CARD

#: The plans in force for the screen, as the planner writes them into a job.
_IN_FORCE = jev_prereg.plans_in_force(SCREEN.name, SCREEN.version) or {}

#: Invented titles. The fake vendor finds ``ADDRESSED`` addressed to an AI
#: system, and ties on ``TIED``.
CLEAN = "Quiet Momentum in Invented Mid-Cap Shares"
OTHER = "Term Spreads and the Patient Fictional Lender"
ADDRESSED = "Seasonal Carry in Made-Up Grain Futures"
TIED = "Volatility Timing Across Imaginary Pairs"

#: Passes of the loop: the last only plans, since stopping ends its drain.
PASSES = 6


# ---------------------------------------------------------------------------
# The database and the loop
# ---------------------------------------------------------------------------


def _derived(suffix: str) -> str:
    base, _, tail = TEST_DSN.partition("?")
    return f"{base}_{suffix}?{tail}" if tail else f"{base}_{suffix}"


def _name(dsn: str) -> str:
    return dsn.partition("?")[0].rsplit("/", 1)[-1]


async def _drop(dsn: str) -> None:
    admin = await asyncpg.connect(TEST_DSN)
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{_name(dsn)}" WITH (FORCE)')
    finally:
        await admin.close()


@pytest.fixture
async def db() -> AsyncIterator[tuple[str, asyncpg.Connection]]:
    """A database of the test's own, migrated, with :data:`ON` set."""
    dsn = _derived("jev_research")
    await _drop(dsn)
    admin = await asyncpg.connect(TEST_DSN)
    try:
        await admin.execute(f'CREATE DATABASE "{_name(dsn)}"')
    finally:
        await admin.close()
    await migrations.migrate(dsn)
    conn = await asyncpg.connect(dsn)
    try:
        for key, value in ON.items():
            await flag_repo.set_flag(conn, key, value, "test")
        yield dsn, conn
    finally:
        await conn.close()
        await _drop(dsn)


async def _release(conn: asyncpg.Connection) -> None:
    """A queued retry made due now: the queue's backoff, as if it had passed."""
    await conn.execute(
        "UPDATE jobs SET scheduled_for = now() "
        "WHERE status = 'queued' AND scheduled_for > now()"
    )


async def _loop(
    monkeypatch: pytest.MonkeyPatch, dsn: str, passes: int = PASSES
) -> None:
    """
    The programme's Jev loop as shipped, planner and drain, for ``passes``
    passes with a key available, each retry released before the next drain.
    """
    monkeypatch.setattr(programme_main, "JEV_POLL_SECONDS", 0.01)
    monkeypatch.setattr(programme_main, "JEV_PLAN_SECONDS", 0.0)
    programme = Programme(dsn, api_key=None, secrets_key="", typesafe_key=KEY)
    programme._pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
    drain = programme._drain_jev
    seen = 0

    async def counted() -> bool:
        nonlocal seen
        seen += 1
        if seen >= passes:
            programme.stop()
        assert programme._pool is not None
        async with programme._pool.acquire() as conn:
            await _release(conn)
        return await drain()

    monkeypatch.setattr(programme, "_drain_jev", counted)
    try:
        await asyncio.wait_for(programme._jev_loop(), timeout=120)
    finally:
        await programme._pool.close()
    assert seen == passes


async def _plan_and_drain(
    conn: asyncpg.Connection, dsn: str, now: datetime
) -> list[str]:
    """One planner pass at ``now``, every job it planned made due, one drain."""
    planned = await jev_plan.plan(conn, now=now, key_available=True)
    await _release(conn)
    programme = Programme(dsn, api_key=None, secrets_key="", typesafe_key=KEY)
    programme._pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
    try:
        await programme._drain_jev()
    finally:
        await programme._pool.close()
    return planned


def _page(monkeypatch: pytest.MonkeyPatch, titles: dict[str, list[str]]) -> None:
    """The page the ingest reads, handed over in place of a fetch."""
    page = pwb_readme.fetched(pwb_readme.readme(pwb_readme.sections(titles)))

    async def fetch(source: Any, **kwargs: Any) -> Any:
        assert kwargs == {}, "the job handed the fetcher a seam"
        return page

    monkeypatch.setattr(web_fetch, "fetch", fetch)


# ---------------------------------------------------------------------------
# The vendor
# ---------------------------------------------------------------------------


class _Vendor:
    """
    ``jev_client.ask``, answering each question about each text as scripted,
    and counting calls. A Noul about a text answers ``noul[text]``, or 0.03,
    the probe's 0.99; a Choice puts 0.7 on its first option. ``failing[text]``
    makes every call about that text a timeout, a content block, a response
    refused whole (``invalid``: another model answered), a 422
    (``invalid_request``) or a refused key (``auth``), and
    ``failing_for[(text, key)]`` only the calls that ask question ``key``.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.noul: dict[str, float] = {}
        self.failing: dict[str, str] = {}
        self.failing_for: dict[tuple[str, str], str] = {}

    def about(self, text: str) -> list[dict[str, Any]]:
        """The calls about ``text``."""
        return [call for call in self.calls if _text_of(call["state"]) == text]

    async def ask(self, **kwargs: Any) -> jev_client.JevCall:
        self.calls.append(kwargs)
        text = _text_of(kwargs["state"])
        failing = self.failing.get(text or "")
        for key in kwargs["questions"]:
            failing = self.failing_for.get((text or "", key), failing)
        if failing == "timeout":
            return jev_client.JevCall(
                http_status=None,
                raw_body=None,
                request_id=None,
                latency_ms=10_000,
                error_class="TypeSafeAPITimeoutError",
                error_kind="timeout",
                input_tokens=None,
                output_tokens=None,
            )
        if failing in ("invalid_request", "auth"):
            # A 422, which holds the set's version under the pin, or a 401,
            # which holds every lane until midnight: each a standing refusal.
            body = json.dumps({"error": {"type": failing, "message": "refused"}})
            return jev_client.JevCall(
                http_status=422 if failing == "invalid_request" else 401,
                raw_body=body,
                request_id="req_refused",
                latency_ms=30,
                error_class=(
                    "TypeSafeUnprocessableEntityError"
                    if failing == "invalid_request"
                    else "TypeSafeAuthenticationError"
                ),
                error_kind=failing,
                input_tokens=None,
                output_tokens=None,
                wire_body=body.encode("utf-8"),
            )
        if failing == "content_block":
            body = "<html>blocked</html>"
            return jev_client.JevCall(
                http_status=403,
                raw_body=body,
                request_id="req_blocked",
                latency_ms=40,
                error_class="TypeSafePermissionDeniedError",
                error_kind="content_block",
                input_tokens=None,
                output_tokens=None,
                wire_body=body.encode("utf-8"),
            )
        answers: dict[str, Any] = {}
        for key, question in kwargs["questions"].items():
            if question["type"] == "noul":
                p = 0.99 if key == "about_the_sun" else self.noul.get(text or "", 0.03)
                answers[key] = {"type": "noul", "noul": p}
            else:
                options = list(question["criteria"])
                rest = round(0.3 / (len(options) - 1), 6)
                probabilities = {option: rest for option in options}
                probabilities[options[0]] = round(1 - rest * (len(options) - 1), 6)
                answers[key] = {
                    "type": "choice",
                    "choice": options[0],
                    "confidence": 0.5,
                    "probabilities": probabilities,
                }
        model = "jev-0.0.1" if failing == "invalid" else kwargs["model"]
        body = json.dumps({"model": model, "answers": answers, "usage": {}})
        return jev_client.JevCall(
            http_status=200,
            raw_body=body,
            request_id="req_research",
            latency_ms=50,
            error_class=None,
            error_kind=None,
            input_tokens=None,
            output_tokens=None,
            wire_body=body.encode("utf-8"),
        )


def _text_of(state: Any) -> str | None:
    if isinstance(state, dict):
        return state.get("excerpt", state.get("title"))
    return None


@pytest.fixture
def vendor(monkeypatch: pytest.MonkeyPatch) -> _Vendor:
    fake = _Vendor()
    monkeypatch.setattr(jev_client, "ask", fake.ask)
    return fake


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


async def _requests(
    conn: asyncpg.Connection, question_set: Any, text: str
) -> list[dict[str, Any]]:
    """Every request of ``question_set`` about ``text``, oldest first."""
    rows = await conn.fetch(
        "SELECT id, status, lane, error_kind FROM jev_requests "
        "WHERE question_set = $1 AND subject_id = $2 ORDER BY id",
        question_set.name,
        text_sha256(text),
    )
    return [dict(row) for row in rows]


async def _documents(conn: asyncpg.Connection, text: str) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        "SELECT id, source, quarantined, quarantine_reason FROM web_documents "
        "WHERE content_sha256 = $1 ORDER BY id",
        text_sha256(text),
    )
    return [dict(row) for row in rows]


async def _asks(conn: asyncpg.Connection, question_set: Any, text: str) -> list[Any]:
    """Every ``jev_ask`` job of ``question_set`` about ``text``."""
    rows = await conn.fetch(
        "SELECT * FROM jobs WHERE kind = 'jev_ask' AND payload->>'set' = $1 "
        "AND payload->>'subject_id' = $2 ORDER BY created_at",
        question_set.name,
        text_sha256(text),
    )
    return [dict(row) for row in rows]


def _tomorrow(days: int = 1) -> datetime:
    return datetime.now(UTC) + timedelta(days=days)


# ---------------------------------------------------------------------------
# Ingest, then the screen, then the catalogue
# ---------------------------------------------------------------------------


class TestTheScreenComesFirst:
    async def test_ingest_then_the_screen_then_the_catalogue(
        self,
        monkeypatch: pytest.MonkeyPatch,
        db: tuple[str, asyncpg.Connection],
        vendor: _Vendor,
    ) -> None:
        dsn, conn = db
        vendor.noul = {ADDRESSED: 0.87, TIED: 0.5}
        _page(
            monkeypatch,
            {
                "Equities": [CLEAN],
                "Bonds": [OTHER],
                "Commodities": [ADDRESSED],
                "Currencies": [TIED],
            },
        )
        await _loop(monkeypatch, dsn)

        for text in (CLEAN, OTHER, ADDRESSED, TIED):
            (screened,) = await _requests(conn, SCREEN, text)
            assert screened["status"] == "ok", text
        for text in (CLEAN, OTHER):
            (described,) = await _requests(conn, CATALOGUE, text)
            assert described["status"] == "ok"
            (screened,) = await _requests(conn, SCREEN, text)
            assert described["id"] > screened["id"], "described before it was cleared"
        for text in (ADDRESSED, TIED):
            assert await _requests(conn, CATALOGUE, text) == [], text

        (addressed,) = await _documents(conn, ADDRESSED)
        (request,) = await _requests(conn, SCREEN, ADDRESSED)
        assert addressed["quarantined"] is True
        assert addressed["quarantine_reason"] == (
            f"jev guardrail.injection v1: addressed_to_ai p=0.87 (request "
            f"{request['id']}, {PIN}); not calibrated"
        )
        for text in (CLEAN, OTHER, TIED):
            assert [d["quarantined"] for d in await _documents(conn, text)] == [False]

        jobs = await conn.fetch("SELECT * FROM jobs WHERE kind = 'jev_ask'")
        assert len(jobs) == 6
        for job in jobs:
            assert job["status"] == "succeeded", job["error"]
            result = json.loads(job["result"])
            assert result["plan_hash"] == jev_prereg.GOLDEN_PLAN_HASH
            name = result["set"]
            assert (
                result["set_plan_hash"]
                == (jev_prereg.GOLDEN_SET_PLAN_HASHES[(name, 1)])
            )
        texts = [_text_of(call["state"]) for call in vendor.calls]
        assert sorted(t for t in texts if t) == sorted(
            [CLEAN, OTHER, ADDRESSED, TIED, CLEAN, OTHER]
        )

    async def test_a_held_text_is_never_described(
        self,
        monkeypatch: pytest.MonkeyPatch,
        db: tuple[str, asyncpg.Connection],
        vendor: _Vendor,
    ) -> None:
        """
        A tie measured nothing, and it is canonical: the text is neither screened
        again nor described, today or on any later day, under this version and
        pin.
        """
        dsn, conn = db
        vendor.noul = {TIED: 0.5}
        _page(monkeypatch, {"Currencies": [TIED]})
        await _loop(monkeypatch, dsn)
        for days in (1, 2):
            await _plan_and_drain(conn, dsn, _tomorrow(days))
        (screened,) = await _requests(conn, SCREEN, TIED)
        assert screened["status"] == "ok"
        assert await _requests(conn, CATALOGUE, TIED) == []
        assert await _asks(conn, CATALOGUE, TIED) == []
        assert len(vendor.about(TIED)) == 1


class TestQuarantineIsByContent:
    async def test_one_ask_quarantines_every_source_holding_the_text(
        self,
        monkeypatch: pytest.MonkeyPatch,
        db: tuple[str, asyncpg.Connection],
        vendor: _Vendor,
    ) -> None:
        dsn, conn = db
        await jev_repo.insert_documents(
            conn,
            [
                jev_repo.DocumentRow(
                    source="another_feed",
                    url="https://example.invalid/feed",
                    excerpt=ADDRESSED,
                )
            ],
        )
        vendor.noul = {ADDRESSED: 0.91}
        _page(monkeypatch, {"Commodities": [ADDRESSED], "Equities": [CLEAN]})
        await _loop(monkeypatch, dsn)

        documents = await _documents(conn, ADDRESSED)
        assert sorted(d["source"] for d in documents) == ["another_feed", "pwb-readme"]
        assert all(d["quarantined"] for d in documents)
        assert len({d["quarantine_reason"] for d in documents}) == 1
        assert len(await _requests(conn, SCREEN, ADDRESSED)) == 1
        assert len(await _asks(conn, SCREEN, ADDRESSED)) == 1
        assert len(vendor.about(ADDRESSED)) == 1


class TestRetiringAndReplanning:
    async def test_three_failed_calls_retire_a_subject(
        self,
        monkeypatch: pytest.MonkeyPatch,
        db: tuple[str, asyncpg.Connection],
        vendor: _Vendor,
    ) -> None:
        """
        One job, three attempts, each a call that timed out: three failed calls,
        and no later day asks again. The other text is screened and described.
        """
        dsn, conn = db
        vendor.failing = {CLEAN: "timeout"}
        _page(monkeypatch, {"Equities": [CLEAN], "Bonds": [OTHER]})
        await _loop(monkeypatch, dsn)

        (job,) = await _asks(conn, SCREEN, CLEAN)
        assert (job["status"], job["attempts"]) == ("failed", 3), job["error"]
        failed = await _requests(conn, SCREEN, CLEAN)
        assert [(r["status"], r["error_kind"]) for r in failed] == [
            ("error", "timeout")
        ] * 3
        for days in (1, 2):
            planned = await _plan_and_drain(conn, dsn, _tomorrow(days))
            assert not [k for k in planned if text_sha256(CLEAN) in k], planned
        assert len(vendor.about(CLEAN)) == 3
        assert [r["status"] for r in await _requests(conn, CATALOGUE, OTHER)] == ["ok"]

    async def test_a_subject_is_planned_again_by_its_own_key(
        self,
        monkeypatch: pytest.MonkeyPatch,
        db: tuple[str, asyncpg.Connection],
        vendor: _Vendor,
    ) -> None:
        """
        A response refused whole fails its job for good with one failed call:
        not planned again the same day, planned the next; and a subject whose
        job is still waiting is not planned again on any day.
        """
        dsn, conn = db
        vendor.failing = {CLEAN: "invalid"}
        _page(monkeypatch, {"Equities": [CLEAN]})
        await _loop(monkeypatch, dsn)
        (job,) = await _asks(conn, SCREEN, CLEAN)
        assert job["status"] == "failed" and job["attempts"] == 1
        assert [r["status"] for r in await _requests(conn, SCREEN, CLEAN)] == [
            "invalid"
        ]

        now = datetime.now(UTC)
        again = await jev_plan.plan(conn, now=now, key_available=True)
        assert not [k for k in again if text_sha256(CLEAN) in k]
        tomorrow = _tomorrow()
        later = await jev_plan.plan(conn, now=tomorrow, key_available=True)
        assert (
            jev_repo.ask_job_key(
                SCREEN.name, 1, "web_excerpt", text_sha256(CLEAN), tomorrow.date()
            )
            in later
        )

        waiting = text_sha256(OTHER)
        await jev_repo.insert_documents(
            conn,
            [
                jev_repo.DocumentRow(
                    source="pwb-readme",
                    url=web_sources.as_written(SOURCE).url,
                    excerpt=OTHER,
                )
            ],
        )
        await job_repo.enqueue(
            conn,
            "jev_ask",
            {
                "set": SCREEN.name,
                "version": 1,
                "subject_type": "web_excerpt",
                "subject_id": waiting,
                "source_id": 1,
                **_IN_FORCE,
            },
            scheduled_for=_tomorrow(5),
            dedupe_key=jev_repo.ask_job_key(
                SCREEN.name, 1, "web_excerpt", waiting, date(2026, 1, 1)
            ),
        )
        for days in (2, 3):
            planned = await jev_plan.plan(conn, now=_tomorrow(days), key_available=True)
            assert not [k for k in planned if waiting in k], planned


class TestTheSourcesLabels:
    async def test_labels_are_recorded_once(
        self,
        monkeypatch: pytest.MonkeyPatch,
        db: tuple[str, asyncpg.Connection],
        vendor: _Vendor,
    ) -> None:
        """
        A title under one heading is labelled with it; one under two is not;
        reading the same page again records nothing new.
        """
        dsn, conn = db
        await flag_repo.set_flag(conn, GUARDRAILS, False, "test")
        _page(
            monkeypatch,
            {"Equities": [CLEAN], "Bonds": [OTHER], "Multi-asset": [CLEAN]},
        )
        await _loop(monkeypatch, dsn, passes=2)
        first = [dict(r) for r in await conn.fetch("SELECT * FROM jev_labels")]
        assert [(r["subject_id"], r["label"]) for r in first] == [
            (text_sha256(OTHER), "bonds")
        ]
        (label,) = first
        assert (label["question_set"], label["question_set_version"]) == (
            CATALOGUE.name,
            CATALOGUE.version,
        )
        assert label["question_key"] == "asset_class"
        assert label["labelled_by"].startswith("source:pwb-readme@")
        assert label["note"] == "the README's own section heading"

        await job_repo.enqueue(
            conn, "jev_web_ingest", {"source": "pwb-readme"}, dedupe_key="again"
        )
        await _plan_and_drain(conn, dsn, datetime.now(UTC))
        again = [dict(r) for r in await conn.fetch("SELECT * FROM jev_labels")]
        assert again == first
        job = await conn.fetchrow("SELECT * FROM jobs WHERE dedupe_key = 'again'")
        assert json.loads(job["result"])["labels"] == {
            "recorded": 0,
            "already": 1,
            "several_headings": 1,
        }


# ---------------------------------------------------------------------------
# A block's quarantine survives a failed write (scope, section 10d)
# ---------------------------------------------------------------------------


def _flaky_quarantine(monkeypatch: pytest.MonkeyPatch, failures: int) -> dict[str, int]:
    """``quarantine_content`` failing its first ``failures`` calls, as a
    database error would, after which it is the shipped one."""
    real = jev_repo.quarantine_content
    left = {"failures": failures}

    async def flaky(conn: Any, content: str, reason: str) -> int:
        if left["failures"]:
            left["failures"] -= 1
            raise asyncpg.exceptions.DeadlockDetectedError("deadlock detected")
        return await real(conn, content, reason)

    monkeypatch.setattr(jev_repo, "quarantine_content", flaky)
    return left


class TestABlocksQuarantineSurvivesAFailedWrite:
    async def test_the_next_attempt_makes_it_with_no_call(
        self,
        monkeypatch: pytest.MonkeyPatch,
        db: tuple[str, asyncpg.Connection],
        vendor: _Vendor,
    ) -> None:
        """
        The block's error row commits on its own; the quarantine after it
        fails once; the retry is refused by the road for the block on record,
        makes no call, and quarantines the content naming the block's request.
        """
        dsn, conn = db
        vendor.failing = {CLEAN: "content_block"}
        _flaky_quarantine(monkeypatch, failures=1)
        _page(monkeypatch, {"Equities": [CLEAN]})
        await _loop(monkeypatch, dsn)

        (block,) = await _requests(conn, SCREEN, CLEAN)
        assert block["error_kind"] == "content_block"
        (document,) = await _documents(conn, CLEAN)
        assert document["quarantined"] is True
        assert document["quarantine_reason"] == (
            f"vendor content block on request {block['id']} (a 403 whose body is "
            "not JSON; an unverified precaution, docs/08 fact 4)"
        )
        (job,) = await _asks(conn, SCREEN, CLEAN)
        assert (job["status"], job["attempts"]) == ("failed", 2)
        assert job["error"].endswith("its content is quarantined (1 documents)")
        assert "deadlock" not in job["error"]
        assert len(vendor.about(CLEAN)) == 1

    async def test_a_later_pass_plans_the_repair_when_every_attempt_failed(
        self,
        monkeypatch: pytest.MonkeyPatch,
        db: tuple[str, asyncpg.Connection],
        vendor: _Vendor,
    ) -> None:
        """
        The screen cleared the text, the catalogue's call was blocked, and the
        quarantine failed on every attempt: the catalogue's job fails for good
        and the content stays in use. The screen has answered it ``ok``, so
        only the block on record brings it back: a later day's pass plans the
        screen for it, which the road refuses for the block with no call, and
        whose follow-up quarantines it.
        """
        dsn, conn = db
        vendor.failing_for = {(CLEAN, "asset_class"): "content_block"}
        left = _flaky_quarantine(monkeypatch, failures=3)
        _page(monkeypatch, {"Equities": [CLEAN]})
        await _loop(monkeypatch, dsn)
        assert [r["status"] for r in await _requests(conn, SCREEN, CLEAN)] == ["ok"]
        (job,) = await _asks(conn, CATALOGUE, CLEAN)
        assert (job["status"], job["attempts"]) == ("failed", 3)
        assert left["failures"] == 0
        assert [d["quarantined"] for d in await _documents(conn, CLEAN)] == [False]

        tomorrow = _tomorrow()
        planned = await _plan_and_drain(conn, dsn, tomorrow)
        assert [k for k in planned if text_sha256(CLEAN) in k] == [
            jev_repo.ask_job_key(
                SCREEN.name, 1, "web_excerpt", text_sha256(CLEAN), tomorrow.date()
            )
        ]
        (document,) = await _documents(conn, CLEAN)
        (block,) = await _requests(conn, CATALOGUE, CLEAN)
        assert document["quarantined"] is True
        assert (
            f"vendor content block on request {block['id']}"
            in (document["quarantine_reason"])
        )
        assert len(vendor.about(CLEAN)) == 2, "the repair made a call"

    @pytest.mark.parametrize("hold", ["invalid_request", "auth"])
    async def test_the_repair_is_planned_whatever_the_vendor_holds(
        self,
        monkeypatch: pytest.MonkeyPatch,
        db: tuple[str, asyncpg.Connection],
        vendor: _Vendor,
        hold: str,
    ) -> None:
        """
        C7+C8's review: the planner held back every ask of a set the vendor
        refused with a 422, and every ask while an authentication failure held
        the day, because the road would refuse each before any call. Not the
        repair: the road refuses it for the block, with no call, before it
        reads a standing refusal, and its follow-up quarantines. A 422 holds
        the screen until a new version, so the content stayed in use for as
        long; now the repair is planned under either hold, and makes no call.
        """
        dsn, conn = db
        vendor.failing_for = {(CLEAN, "asset_class"): "content_block"}
        left = _flaky_quarantine(monkeypatch, failures=3)
        _page(monkeypatch, {"Equities": [CLEAN]})
        await _loop(monkeypatch, dsn)
        assert left["failures"] == 0
        assert [d["quarantined"] for d in await _documents(conn, CLEAN)] == [False]

        # The same day, the screen's ask about another excerpt draws the hold.
        await jev_repo.insert_documents(
            conn,
            [
                jev_repo.DocumentRow(
                    source="another_feed",
                    url="https://example.invalid/feed",
                    excerpt=TIED,
                )
            ],
        )
        vendor.failing = {TIED: hold}
        await _plan_and_drain(conn, dsn, datetime.now(UTC))
        (refused,) = await _requests(conn, SCREEN, TIED)
        assert refused["error_kind"] == hold
        model = await flags.jev_model(conn)
        assert model is not None
        held = (
            await jev_repo.auth_failed_today(conn)
            if hold == "auth"
            else await jev_repo.set_refused(
                conn, question_set=SCREEN.name, version=SCREEN.version, model=model
            )
        )
        assert held, f"the {hold} hold is not in force"

        calls = len(vendor.about(CLEAN)) + len(vendor.about(TIED))
        tomorrow = _tomorrow()
        planned = await _plan_and_drain(conn, dsn, tomorrow)
        assert [k for k in planned if k.startswith("jev_ask:")] == [
            jev_repo.ask_job_key(
                SCREEN.name, 1, "web_excerpt", text_sha256(CLEAN), tomorrow.date()
            )
        ], "the repair was held back, or an ask that calls was planned"
        (document,) = await _documents(conn, CLEAN)
        assert document["quarantined"] is True
        assert len(vendor.about(CLEAN)) + len(vendor.about(TIED)) == calls, (
            "the repair made a call"
        )


# ---------------------------------------------------------------------------
# The screen's own quarantine survives a failed write (C7+C8's review)
# ---------------------------------------------------------------------------


class TestTheScreensQuarantineSurvivesAFailedWrite:
    async def test_a_later_pass_quarantines_it_with_no_call_and_none_resends_it(
        self,
        monkeypatch: pytest.MonkeyPatch,
        db: tuple[str, asyncpg.Connection],
        vendor: _Vendor,
    ) -> None:
        """
        A valid ``true`` from the screen quarantines its text, and the answer
        is canonical and committed before the quarantine is written. With the
        write failing on every attempt, the first cut left the text in use for
        good — answered ``ok``, so never planned again — and the next day's
        re-ask, sampled in the low-margin stratum, sent it to the vendor
        again as a probe. Now a later day's pass plans the screen for it with
        no call, whose job quarantines it on the answer on record, in the
        screen's words; no re-ask is planned for flagged text; and the vendor
        sees it once.
        """
        dsn, conn = db
        vendor.noul = {ADDRESSED: 0.55}
        left = _flaky_quarantine(monkeypatch, failures=3)
        _page(monkeypatch, {"Commodities": [ADDRESSED]})
        await _loop(monkeypatch, dsn)
        (screened,) = await _requests(conn, SCREEN, ADDRESSED)
        assert screened["status"] == "ok"
        (job,) = await _asks(conn, SCREEN, ADDRESSED)
        assert (job["status"], job["attempts"]) == ("failed", 3), job["error"]
        assert left["failures"] == 0
        assert [d["quarantined"] for d in await _documents(conn, ADDRESSED)] == [False]
        assert len(vendor.about(ADDRESSED)) == 1

        tomorrow = _tomorrow()
        planned = await _plan_and_drain(conn, dsn, tomorrow)
        assert not [k for k in planned if k.startswith("jev_reask")], planned
        assert [k for k in planned if text_sha256(ADDRESSED) in k] == [
            jev_repo.ask_job_key(
                SCREEN.name, 1, "web_excerpt", text_sha256(ADDRESSED), tomorrow.date()
            )
        ], "the screen's flag was never acted on"
        (document,) = await _documents(conn, ADDRESSED)
        assert document["quarantined"] is True
        assert document["quarantine_reason"] == (
            f"jev guardrail.injection v1: addressed_to_ai p=0.55 (request "
            f"{screened['id']}, {PIN}); not calibrated"
        )
        for days in (2, 3):
            planned = await _plan_and_drain(conn, dsn, _tomorrow(days))
            assert not [k for k in planned if text_sha256(ADDRESSED) in k], planned
        assert len(vendor.about(ADDRESSED)) == 1, "flagged text was sent again"
        assert [r["lane"] for r in await _requests(conn, SCREEN, ADDRESSED)] == [
            "guardrail"
        ]

    async def test_a_flag_made_under_another_pin_is_acted_on_with_no_call(
        self,
        monkeypatch: pytest.MonkeyPatch,
        db: tuple[str, asyncpg.Connection],
        vendor: _Vendor,
    ) -> None:
        """
        The answer on record is read before any ask, not replayed by one: with
        the pin moved since, a replay would find no canonical answer and ask
        the new model about the flagged text. Quarantine is one-way and by
        content, so the flag stands whoever is pinned now, and the repair
        quarantines in its words with no call.
        """
        dsn, conn = db
        vendor.noul = {ADDRESSED: 0.55}
        _flaky_quarantine(monkeypatch, failures=3)
        _page(monkeypatch, {"Commodities": [ADDRESSED]})
        await _loop(monkeypatch, dsn)
        (screened,) = await _requests(conn, SCREEN, ADDRESSED)
        assert [d["quarantined"] for d in await _documents(conn, ADDRESSED)] == [False]

        newer = "jev-1.14.0"
        monkeypatch.setattr(jev_catalogue, "KNOWN_MODELS", (PIN, newer))
        await flag_repo.set_flag(conn, flags.JEV_MODEL, newer, "test")
        assert await flags.jev_model(conn) == newer
        await _plan_and_drain(conn, dsn, _tomorrow())
        (document,) = await _documents(conn, ADDRESSED)
        assert document["quarantined"] is True
        assert document["quarantine_reason"] == (
            f"jev guardrail.injection v1: addressed_to_ai p=0.55 (request "
            f"{screened['id']}, {PIN}); not calibrated"
        )
        assert len(vendor.about(ADDRESSED)) == 1, "the new pin was asked about it"


# ---------------------------------------------------------------------------
# Every answer is recorded with the plans it was recorded under (section 10a)
# ---------------------------------------------------------------------------


def _plans_of(row: Any) -> dict[str, Any]:
    """The analysis plans a job's payload or result names."""
    found = json.loads(row) if isinstance(row, str) else row
    return {key: found[key] for key in _IN_FORCE}


class TestEveryAnswerIsRecordedWithItsPlans:
    """
    Section 10a of the scope, for every outcome that records an answer, a job
    that fails included: the plans a ``jev_ask`` job is asked under are in
    its payload from the moment it is planned, and its row names the request
    its attempt recorded beside them. The first build wrote them only into a
    succeeding job's result, so a response refused whole, which the harness
    counts, and an answer whose follow-up failed were recorded under no plan.
    """

    async def test_a_response_refused_whole(
        self,
        monkeypatch: pytest.MonkeyPatch,
        db: tuple[str, asyncpg.Connection],
        vendor: _Vendor,
    ) -> None:
        dsn, conn = db
        assert _IN_FORCE, "the screen has no plan to record"
        vendor.failing = {CLEAN: "invalid"}
        _page(monkeypatch, {"Equities": [CLEAN]})
        await _loop(monkeypatch, dsn)
        (request,) = await _requests(conn, SCREEN, CLEAN)
        assert request["status"] == "invalid"
        (job,) = await _asks(conn, SCREEN, CLEAN)
        assert (job["status"], job["attempts"]) == ("failed", 1)
        assert _plans_of(job["payload"]) == _IN_FORCE
        assert job["result"] is not None, "the refused answer names no plan"
        result = json.loads(job["result"])
        assert (result["status"], result["request_id"]) == ("invalid", request["id"])
        assert _plans_of(result) == _IN_FORCE

    async def test_an_answer_whose_follow_up_failed_on_every_attempt(
        self,
        monkeypatch: pytest.MonkeyPatch,
        db: tuple[str, asyncpg.Connection],
        vendor: _Vendor,
    ) -> None:
        dsn, conn = db
        vendor.noul = {ADDRESSED: 0.87}
        _flaky_quarantine(monkeypatch, failures=3)
        _page(monkeypatch, {"Commodities": [ADDRESSED]})
        await _loop(monkeypatch, dsn)
        (request,) = await _requests(conn, SCREEN, ADDRESSED)
        assert request["status"] == "ok"
        (job,) = await _asks(conn, SCREEN, ADDRESSED)
        assert (job["status"], job["attempts"]) == ("failed", 3), job["error"]
        assert "deadlock" not in job["error"]
        assert _plans_of(job["payload"]) == _IN_FORCE
        assert job["result"] is not None, "the answer names no plan"
        result = json.loads(job["result"])
        assert (result["status"], result["request_id"]) == ("ok", request["id"])
        assert _plans_of(result) == _IN_FORCE

    async def test_the_queue_keeps_what_a_failed_attempt_recorded(
        self, db: tuple[str, asyncpg.Connection]
    ) -> None:
        """
        ``job_repo.fail`` on PostgreSQL: a failure that carries a record
        stores it beside the error; a later attempt that carries none leaves
        it in place; a success replaces it, as it always did.
        """
        _, conn = db
        job_id = await job_repo.enqueue(conn, "jev_ask", {}, max_attempts=3)
        stored = "SELECT status, error, result FROM jobs WHERE id = $1"

        await job_repo.claim(conn, "test", kinds=["jev_ask"])
        record = {"status": "ok", "request_id": 7, **_IN_FORCE}
        assert await job_repo.fail(conn, job_id, "first", result=record) == "queued"
        row = await conn.fetchrow(stored, job_id)
        assert (row["error"], json.loads(row["result"])) == ("first", record)

        await conn.execute(
            "UPDATE jobs SET scheduled_for = now() WHERE id = $1", job_id
        )
        await job_repo.claim(conn, "test", kinds=["jev_ask"])
        assert await job_repo.fail(conn, job_id, "second") == "queued"
        row = await conn.fetchrow(stored, job_id)
        assert (row["error"], json.loads(row["result"])) == ("second", record)

        await conn.execute(
            "UPDATE jobs SET scheduled_for = now() WHERE id = $1", job_id
        )
        await job_repo.claim(conn, "test", kinds=["jev_ask"])
        await job_repo.complete(conn, job_id, {"status": "ok", "request_id": 7})
        row = await conn.fetchrow(stored, job_id)
        assert row["status"] == "succeeded" and row["error"] is None
        assert json.loads(row["result"]) == {"status": "ok", "request_id": 7}

    async def test_a_failure_that_records_nothing_stores_nothing(
        self, db: tuple[str, asyncpg.Connection]
    ) -> None:
        """Every caller that passes no record — the worker's — writes none."""
        _, conn = db
        job_id = await job_repo.enqueue(conn, "jev_ask", {}, max_attempts=1)
        await job_repo.claim(conn, "test", kinds=["jev_ask"])
        assert await job_repo.fail(conn, job_id, "no record") == "failed"
        assert (
            await conn.fetchval("SELECT result FROM jobs WHERE id = $1", job_id) is None
        )


# ---------------------------------------------------------------------------
# The hypothesis and card asks change nothing
# ---------------------------------------------------------------------------

#: A title the programme's model wrote, invented.
MODEL_TITLE = "Invented Carry in Fictional Bond Futures"


async def _shadow(conn: asyncpg.Connection) -> dict[str, list[str]]:
    """Every row of the tables no answer may change, as text."""
    return {
        table: [
            json.dumps(dict(row), default=str, sort_keys=True)
            for row in await conn.fetch(f"SELECT * FROM {table} ORDER BY id")
        ]
        for table in ("hypotheses", "candidates", "findings")
    }


class TestTheTitleAsksChangeNothing:
    @pytest.mark.parametrize(
        "outcome", ["true", "false", "invalid", "timeout", "content_block"]
    )
    async def test_every_outcome_leaves_the_programmes_tables_alone(
        self,
        monkeypatch: pytest.MonkeyPatch,
        db: tuple[str, asyncpg.Connection],
        vendor: _Vendor,
        outcome: str,
    ) -> None:
        dsn, conn = db
        written = await repo.create_hypothesis(
            conn, MODEL_TITLE, {}, "programme", origin="model", model="a-model"
        )
        await repo.create_hypothesis(
            conn, "An Operator's Invented Idea", {}, "operator", origin="operator"
        )
        await repo.create_hypothesis(
            conn, "A" * (jev_questions.TITLE_MAX_CHARS + 1), {}, "p", origin="model"
        )
        candidate = await repo.create_candidate(
            conn,
            written["id"],
            "buy_and_hold",
            {},
            ["SPY"],
            date(2020, 1, 2),
            date(2021, 1, 4),
            "synthetic",
        )
        await repo.raise_finding(conn, candidate, "risk_officer", "high", "Invented")
        before = await _shadow(conn)
        if outcome in ("true", "false"):
            vendor.noul = {MODEL_TITLE: 0.97 if outcome == "true" else 0.03}
        else:
            vendor.failing = {MODEL_TITLE: outcome}

        async def no_page(source: Any, **kwargs: Any) -> Any:
            return web_fetch.FetchFailure("timeout")

        monkeypatch.setattr(web_fetch, "fetch", no_page)
        await _loop(monkeypatch, dsn)

        assert await _shadow(conn) == before
        asked = await conn.fetch(
            "SELECT DISTINCT subject_id FROM jev_requests "
            "WHERE subject_type = 'hypothesis_title'"
        )
        assert {row["subject_id"] for row in asked} == {text_sha256(MODEL_TITLE)}
        jobs = await conn.fetch("SELECT payload FROM jobs WHERE kind = 'jev_ask'")
        assert {json.loads(j["payload"])["set"] for j in jobs} == {
            HYPOTHESIS.name,
            CARD.name,
        }
        assert {json.loads(j["payload"])["subject_id"] for j in jobs} == {
            text_sha256(MODEL_TITLE)
        }
        assert (
            await conn.fetchval("SELECT COUNT(*) FROM web_documents WHERE quarantined")
            == 0
        )


# ---------------------------------------------------------------------------
# The canary
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def authority() -> Any:
    """The local certificate authority the canary's page is served under."""
    made = Authority()
    yield made
    made.close()


@contextlib.asynccontextmanager
async def _served(
    monkeypatch: pytest.MonkeyPatch, authority: Any, text: str
) -> AsyncIterator[FakeHTTPS]:
    """
    The page served over local HTTPS and fetched by the shipped fetcher, as
    C6's canary fetches it: the fetcher's seam routes its fixed host to the
    local server and trusts the local authority, and the address check admits
    127.0.0.1, where the server listens, here and nowhere else.
    """
    real_fetch = web_fetch.fetch
    real_permitted = web_fetch.address_permitted
    async with FakeHTTPS(
        authority.server_context(SOURCE.host), Reply(body=text.encode("utf-8"))
    ) as server:
        resolver = RoutingResolver({SOURCE.host: (LOOPBACK, server.port)})

        async def over_local_https(source: Any, **kwargs: Any) -> Any:
            assert kwargs == {}, "the job handed the fetcher a seam"
            return await real_fetch(
                source,
                session_factory=lambda: web_fetch._session(
                    resolver=resolver, ssl_context=authority.client_context()
                ),
            )

        monkeypatch.setattr(web_fetch, "fetch", over_local_https)
        monkeypatch.setattr(
            web_fetch,
            "address_permitted",
            lambda host: host == LOOPBACK or real_permitted(host),
        )
        yield server


class TestTheCanary:
    async def test_web_text_is_in_two_columns_and_nowhere_else(
        self,
        monkeypatch: pytest.MonkeyPatch,
        db: tuple[str, asyncpg.Connection],
        vendor: _Vendor,
        authority: Any,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """
        docs/08 invariant I7, end to end: every title of a page carries a token
        under one marker, the page is read, screened and described through the
        loop, and the marker is in ``web_documents.excerpt`` and
        ``jev_requests.state`` — the text stored, and the state each set was
        asked about — and in no other text or JSON column of any table, read
        from ``information_schema``; in no log record at DEBUG; and in no job's
        payload, result or error. One title is refused as its state is built,
        by a validator whose message quotes it, and its job's error names the
        document and nothing more.
        """
        dsn, conn = db
        caplog.set_level(logging.DEBUG)
        marker = _token()
        titles: dict[str, list[str]] = {}
        tokens: list[str] = []
        for heading, listed in pwb_readme.TITLES.items():
            for title in listed:
                tokens.append(f"{marker}{chr(ord('a') + len(tokens))}")
                titles.setdefault(heading, []).append(f"{tokens[-1]} {title}")
        refused = f"{marker}z Refused When Its State Is Built"
        titles["Derivatives"].append(refused)

        real_state = jev_questions.WebExcerptState

        def built(*, excerpt: str) -> jev_questions.WebExcerptState:
            if excerpt == refused:
                # Too long for the state: pydantic's message quotes the input.
                return real_state(excerpt=excerpt * 20)
            return real_state(excerpt=excerpt)

        monkeypatch.setattr(jev_questions, "WebExcerptState", built)
        page = pwb_readme.readme(pwb_readme.sections(titles))
        async with _served(monkeypatch, authority, page) as server:
            await _loop(monkeypatch, dsn)
            assert len(server.requests) == 1, "the page was not fetched once"

        found = await _columns_holding(conn, marker)
        assert set(found) == {"web_documents.excerpt", "jev_requests.state"}, found
        assert found["web_documents.excerpt"] == len(tokens) + 1
        assert found["jev_requests.state"] == 2 * len(tokens), (
            "each title but the refused one, screened and described"
        )
        columns = await conn.fetch(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND data_type IN ('json', 'jsonb', "
            "'text', 'character varying')"
        )
        read = {f"{r['table_name']}.{r['column_name']}" for r in columns}
        assert {
            "programme_runs.actions",
            "jobs.payload",
            "jobs.result",
            "jobs.error",
            "jev_labels.subject_id",
        } <= read
        jobs = [dict(r) for r in await conn.fetch("SELECT * FROM jobs")]
        for job in jobs:
            for field in ("payload", "result", "error"):
                assert marker not in json.dumps(job[field], default=str), job["kind"]
        (refusal,) = [
            job
            for job in jobs
            if job["kind"] == "jev_ask"
            and json.loads(job["payload"])["subject_id"] == text_sha256(refused)
        ]
        assert refusal["status"] == "failed"
        assert "text does not make the state" in refusal["error"]
        assert _logged(caplog.records, marker) == []
        assert any(
            record.name == "src.programme.web_ingest" for record in caplog.records
        ), "the ingest's own log line was not captured, so the scan read nothing"
        assert sum(job["kind"] == "jev_ask" for job in jobs) == 2 * len(tokens) + 1
