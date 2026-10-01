"""
test_jev_findings_ops_over_http.py
----------------------------------
One finding's title asked about end to end, with nothing replaced but the
vendor (docs/09, section 13; phase D3 adds the job-error skeleton's half).

``tests/integration/test_jev_findings.py`` drives phase D2 through the
programme's loop against a fake of ``jev_client.ask``. This drives the
shipped planner and the shipped ``jev_ask`` handler through the lane, the real
client, the real ``typesafe_sdk`` and ``httpx2``, real HTTP to the fake
TypeSafe server in ``conftest.py``, the validator and the ledger on a real
Postgres: a model-written finding's title asked about by ``findings.owner``
and ``findings.severity`` — each request's state exactly ``{"title": …}``,
nothing of the finding's detail, remediation, raiser or severity beside it —
and an operator's finding asked nothing; then the same title, held by a
second finding, asked again and replayed from its row, with no request
leaving at all.

The handler calls ``jev_lane.ask`` through the module attribute with every
keyword spelled and no transport; the transport is bound here by replacing
that attribute with the real ``ask`` given the test's transport, which is the
one thing that differs from production.

Needs both the SDK and a database: skipped without ``typesafe_sdk`` and without
``TEST_DATABASE_URL``. Runs on a database of its own, since the ledger and the
findings register refuse DELETE. Every title is invented.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest

pytest.importorskip("typesafe_sdk")

import asyncpg  # noqa: E402

from src.db import migrate as migrations  # noqa: E402
from src.db.repos import flags as flag_repo  # noqa: E402
from src.programme import (  # noqa: E402
    flags,
    jev_catalogue,
    jev_jobs,
    jev_lane,
    jev_plan,
    jev_prereg,
    jev_repo,
    repo,
)
from src.programme.jev_hash import text_sha256  # noqa: E402
from src.programme.jev_questions import (  # noqa: E402
    FINDINGS_OWNER,
    FINDINGS_SEVERITY,
)
from tests.sdk.conftest import ENDPOINT, FakeTypeSafe, Redirect, Reply  # noqa: E402

TEST_DSN = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = [
    pytest.mark.sdk,
    pytest.mark.skipif(not TEST_DSN, reason="TEST_DATABASE_URL not set"),
]

MODEL = jev_catalogue.DEFAULT_MODEL
KEY = "ts-test-key-not-a-secret"
TITLE = "Invented Fills Assumed at Prices No Venue Gave"
DETAIL = "Invented detail no request may carry"
OPERATORS = "An Operator's Invented Finding"


def _own_dsn() -> str:
    base, _, tail = TEST_DSN.partition("?")
    return f"{base}_jev_findings_sdk?{tail}" if tail else f"{base}_jev_findings_sdk"


@pytest.fixture(scope="module")
def dsn() -> str:
    async def setup() -> str:
        name = _own_dsn().partition("?")[0].rsplit("/", 1)[-1]
        admin = await asyncpg.connect(TEST_DSN)
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            await admin.execute(f'CREATE DATABASE "{name}"')
        finally:
            await admin.close()
        await migrations.migrate(_own_dsn())
        return _own_dsn()

    return asyncio.run(setup())


@pytest.fixture
async def conn(dsn: str) -> AsyncIterator[asyncpg.Connection]:
    """The programme, Jev and the findings area on, every setting seeded."""
    connection = await asyncpg.connect(dsn)
    try:
        for key, value in {
            flags.PROGRAMME_ENABLED: True,
            flags.JEV_ENABLED: True,
            f"{flags.JEV_AREA_PREFIX}findings": True,
            flags.JEV_MODEL: MODEL,
            flags.JEV_DAILY_REQUEST_BUDGET: jev_catalogue.DEFAULT_DAILY_REQUEST_BUDGET,
            flags.JEV_MAX_STATE_TOKENS: jev_catalogue.DEFAULT_MAX_STATE_TOKENS,
        }.items():
            await flag_repo.set_flag(connection, key, value, "test")
        yield connection
    finally:
        await connection.close()


@pytest.fixture
def routed(monkeypatch: pytest.MonkeyPatch, transport: Redirect) -> Redirect:
    """``jev_lane.ask`` as shipped, handed the test's transport."""
    real = jev_lane.ask

    async def ask(conn: Any, **kwargs: Any) -> jev_lane.AskResult:
        assert "transport" not in kwargs, "the handler passed a transport itself"
        return await real(conn, **kwargs, transport=transport)

    monkeypatch.setattr(jev_lane, "ask", ask)
    return transport


def _reply(question_set: Any, request_id: str) -> Reply:
    """The first option of each question at 0.64, the rest sharing the rest."""
    answers = {}
    for key, question in question_set.as_request_questions().items():
        options = list(question["criteria"])
        rest = round(0.36 / (len(options) - 1), 4)
        probabilities = dict.fromkeys(options, rest)
        probabilities[options[0]] = round(1 - rest * (len(options) - 1), 4)
        answers[key] = {
            "type": "choice",
            "choice": options[0],
            "confidence": 0.5,
            "probabilities": probabilities,
        }
    body = {
        "model": MODEL,
        "answers": answers,
        "usage": {"input_tokens": 300, "output_tokens": 1},
    }
    return Reply(
        status=200,
        body=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "x-typesafe-request-id": request_id,
        },
    )


async def _ask_job(conn: asyncpg.Connection, name: str) -> dict[str, Any]:
    (row,) = await conn.fetch(
        "SELECT payload FROM jobs WHERE kind = 'jev_ask' AND payload->>'set' = $1",
        name,
    )
    return json.loads(row["payload"])


class TestOneFindingTitleOverHTTP:
    async def test_the_title_alone_leaves_and_a_second_ask_replays(
        self, conn: asyncpg.Connection, server: FakeTypeSafe, routed: Redirect
    ) -> None:
        raised = await repo.raise_finding(
            conn,
            None,
            "independent_risk",
            "critical",
            TITLE,
            DETAIL,
            "Invented remediation no request may carry",
            origin="model",
        )
        await repo.raise_finding(
            conn, None, "operations", "high", OPERATORS, origin="operator"
        )
        server.script(
            _reply(FINDINGS_OWNER, "req_owner"),
            _reply(FINDINGS_SEVERITY, "req_severity"),
        )

        await jev_plan.plan(conn, now=datetime.now(UTC), key_available=True)
        owner_payload = await _ask_job(conn, FINDINGS_OWNER.name)
        severity_payload = await _ask_job(conn, FINDINGS_SEVERITY.name)
        for payload in (owner_payload, severity_payload):
            assert payload["source_id"] == raised["ref"]
            assert payload["subject_id"] == text_sha256(TITLE)
        owned = await jev_jobs.run_ask(conn, owner_payload, KEY)
        rated = await jev_jobs.run_ask(conn, severity_payload, KEY)
        assert owned["status"] == rated["status"] == "ok"
        assert owned["answers"]["owning_role"]["argmax"] == "quant_research"
        assert rated["answers"]["severity"]["argmax"] == "low"
        assert owned["plan_hash"] == jev_prereg.GOLDEN_PLAN_HASH

        first, second = routed.sent
        assert first.url == second.url == ENDPOINT
        for sent in (first, second):
            wire = json.loads(sent.body)
            assert wire["model"] == MODEL
            assert wire["state"] == {"title": TITLE}, "more than the title left"
            # The questions name every role and severity as options, so the
            # finding's own raiser and severity are judged in the state, and
            # its detail and the operator's finding in the whole body.
            for withheld in ("independent_risk", "critical"):
                assert withheld not in json.dumps(wire["state"])
            body = sent.body.decode("utf-8")
            assert DETAIL not in body and OPERATORS not in body
        assert list(json.loads(first.body)["questions"]) == ["owning_role"]
        assert list(json.loads(second.body)["questions"]) == ["severity"]

        for result, question_set in (
            (owned, FINDINGS_OWNER),
            (rated, FINDINGS_SEVERITY),
        ):
            row = await jev_repo.get_request(conn, result["request_id"])
            assert (row["question_set"], row["status"]) == (question_set.name, "ok")
            assert (row["lane"], row["provenance"]) == ("findings", "model")
            assert (row["subject_type"], row["subject_id"]) == (
                "finding_title",
                text_sha256(TITLE),
            )
            assert row["http_status"] == 200 and row["model_answered"] == MODEL

        # The same title raised again: asked again, it is replayed from the
        # row, and no request leaves.
        again = await repo.raise_finding(
            conn, None, "platform", "low", TITLE, origin="model"
        )
        replayed = await jev_jobs.run_ask(
            conn, {**owner_payload, "source_id": again["ref"]}, KEY
        )
        assert replayed["replayed"] is True
        assert replayed["request_id"] == owned["request_id"]
        assert len(routed.sent) == len(server.received) == 2, (
            "the title asked again sent a request"
        )
        findings = await conn.fetch(
            "SELECT ref, severity, status, raised_by FROM findings ORDER BY ref"
        )
        assert [(f["severity"], f["status"]) for f in findings] == [
            ("critical", "open"),
            ("high", "open"),
            ("low", "open"),
        ], "an answer changed a finding"
