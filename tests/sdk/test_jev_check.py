"""
test_jev_check.py
-----------------
``jev_client.list_models`` and ``python -m src.programme.jev_check`` against the
real ``typesafe_sdk``, over real HTTP to the fake vendor in ``conftest``.

The check is what an operator runs to learn whether a key works before anything
depends on it, so each test asks the question that matters for that: did it go
to TypeSafe's host whatever the environment said, did it stop before spending a
question on a key or an account that cannot answer it, did it judge the answer
the way the lane would, and did it keep the key out of everything it printed.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

pytest.importorskip("typesafe_sdk")

from src.programme import jev_catalogue, jev_check, jev_client  # noqa: E402
from tests.sdk.conftest import (  # noqa: E402
    FakeTypeSafe,
    Redirect,
    Reply,
    Route,
    closed_port,
)

pytestmark = pytest.mark.sdk

PIN = jev_catalogue.DEFAULT_MODEL
KEY = "sk-test-0b7c4e2f9a1d5c38"
REQUEST_ID = "req_7d2e19c0b4aa"
JSON = {"Content-Type": "application/json", "x-typesafe-request-id": REQUEST_ID}
MODELS_URL = jev_catalogue.JEV_BASE_URL + "/v1/models"
SYSTEM_ONE_URL = jev_catalogue.JEV_BASE_URL + "/v1/systemone"


def models_body(*names: str) -> bytes:
    return json.dumps(
        {
            "models": [
                {"name": n, "description": "", "release_date": "2026-09-15"}
                for n in names
            ]
        }
    ).encode()


def probe_body(p: float = 0.97, **fields: Any) -> bytes:
    body: dict[str, Any] = {
        "model": PIN,
        "answers": {"about_the_sun": {"type": "noul", "noul": p}},
        "usage": {"input_tokens": 41, "output_tokens": 1},
    }
    body.update(fields)
    return json.dumps(body).encode()


def listed(*names: str) -> Reply:
    return Reply(status=200, body=models_body(*names), headers=JSON)


def answered(body: bytes) -> Reply:
    return Reply(status=200, body=body, headers=JSON)


class TestTheListingGoesToTypeSafe:
    async def test_the_environment_cannot_move_the_host_or_the_model(
        self,
        monkeypatch: pytest.MonkeyPatch,
        server: FakeTypeSafe,
        transport: Redirect,
    ) -> None:
        monkeypatch.setenv("TYPESAFE_BASE_URL", "https://evil.example")
        monkeypatch.setenv("TYPESAFE_DEFAULT_MODEL", "jev-latest")
        monkeypatch.setenv("TYPESAFE_API_KEY", "sk-from-the-environment")
        server.script(listed(PIN))

        result = await jev_client.list_models(api_key=KEY, transport=transport)

        (sent,) = transport.sent
        assert (sent.method, sent.url) == ("GET", MODELS_URL)
        assert sent.header("Authorization") == f"Bearer {KEY}"
        assert sent.body == b""
        assert result.names == (PIN,)
        assert result.http_status == 200
        assert result.request_id == REQUEST_ID
        assert result.error_kind is None

    async def test_an_account_offered_nothing_is_an_empty_tuple_not_unknown(
        self, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        server.script(listed())
        result = await jev_client.list_models(api_key=KEY, transport=transport)
        assert result.names == ()

    @pytest.mark.parametrize(
        ("reply", "kind"),
        [
            pytest.param(
                Reply(
                    status=401,
                    body=b'{"detail":{"message":"Cannot authenticate"}}',
                    headers=JSON,
                ),
                "auth",
                id="401",
            ),
            pytest.param(
                Reply(
                    status=403,
                    body=b'{"detail":{"message":"Must supply an API key!"}}',
                    headers=JSON,
                ),
                "auth",
                id="403-json",
            ),
            pytest.param(
                Reply(status=403, body=b"<html>blocked</html>"),
                "content_block",
                id="403-html",
            ),
            pytest.param(
                Reply(status=503, body=b'{"error":"overloaded"}', headers=JSON),
                "server",
                id="503",
            ),
        ],
    )
    async def test_a_refusal_is_classed_and_names_nothing(
        self,
        server: FakeTypeSafe,
        transport: Redirect,
        reply: Reply,
        kind: str,
    ) -> None:
        server.script(reply)
        result = await jev_client.list_models(api_key=KEY, transport=transport)
        assert result.names is None
        assert result.error_kind == kind
        assert result.http_status == reply.status

    async def test_no_response_leaves_no_evidence(
        self, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        transport.routes.extend([Route(port=closed_port()), Route(port=closed_port())])
        result = await jev_client.list_models(api_key=KEY, transport=transport)
        assert result.names is None
        assert result.error_kind == "connection"
        assert (result.http_status, result.request_id) == (None, None)

    async def test_a_key_that_is_not_text_is_refused_before_anything_is_sent(
        self, transport: Redirect
    ) -> None:
        with pytest.raises(TypeError):
            await jev_client.list_models(api_key=None, transport=transport)  # type: ignore[arg-type]
        assert transport.sent == []


class TestTheCheck:
    async def test_a_working_key_passes(
        self, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        server.script(listed("jev-1.12.0", PIN), answered(probe_body()))

        report = await jev_check.check(KEY, transport=transport)

        assert report.passed, report.lines
        assert [s.url for s in transport.sent] == [MODELS_URL, SYSTEM_ONE_URL]
        assert json.loads(transport.sent[1].body)["model"] == PIN
        assert report.lines[-1] == "PASS"
        assert any("as expected" in line for line in report.lines)

    async def test_a_refused_key_stops_before_a_question_is_asked(
        self, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        server.script(Reply(status=401, body=b'{"detail":"no"}', headers=JSON))

        report = await jev_check.check(KEY, transport=transport)

        assert not report.passed
        assert [s.url for s in transport.sent] == [MODELS_URL]
        assert any("console.typesafe.ai" in line for line in report.lines)

    async def test_a_pin_the_account_is_not_offered_stops_before_a_question(
        self, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        server.script(listed("jev-1.12.0"))

        report = await jev_check.check(KEY, transport=transport)

        assert not report.passed
        assert [s.url for s in transport.sent] == [MODELS_URL]
        assert any(f"pinned model {PIN}" in line for line in report.lines)

    async def test_the_wrong_answer_fails(
        self, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        server.script(listed(PIN), answered(probe_body(p=0.03)))

        report = await jev_check.check(KEY, transport=transport)

        assert not report.passed
        assert report.lines[-1] == "FAIL"
        assert any("expected true" in line for line in report.lines)

    async def test_an_answer_the_lane_would_not_measure_fails(
        self, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        server.script(listed(PIN), answered(probe_body(model="jev-latest")))

        report = await jev_check.check(KEY, transport=transport)

        assert not report.passed
        assert any("not measured" in line for line in report.lines)

    async def test_a_failed_probe_fails(
        self, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        server.script(
            listed(PIN),
            Reply(status=422, body=b'{"detail":[{"msg":"bad"}]}', headers=JSON),
        )

        report = await jev_check.check(KEY, transport=transport)

        assert not report.passed
        assert any("invalid_request" in line for line in report.lines)

    @pytest.mark.parametrize(
        "replies",
        [
            pytest.param((listed(PIN), answered(probe_body())), id="pass"),
            pytest.param(
                (Reply(status=401, body=KEY.encode(), headers=JSON),), id="refused"
            ),
            pytest.param((listed(PIN), answered(b"not json")), id="garbled"),
        ],
    )
    async def test_the_key_is_never_printed(
        self,
        server: FakeTypeSafe,
        transport: Redirect,
        replies: tuple[Reply, ...],
    ) -> None:
        """Even a vendor that echoes the key back cannot get it printed."""
        server.script(*replies)
        report = await jev_check.check(KEY, transport=transport)
        assert KEY not in "\n".join(report.lines)
