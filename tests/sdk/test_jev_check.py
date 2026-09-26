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
from functools import partial
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


async def run_check(
    monkeypatch: pytest.MonkeyPatch, transport: Redirect, key: str = KEY
) -> jev_check.CheckReport:
    """
    ``jev_check.check`` against the fake vendor.

    The check takes no transport — production code never hands the client one
    — so the client's two calls are patched to carry this test's.
    """
    monkeypatch.setattr(
        jev_client, "list_models", partial(jev_client.list_models, transport=transport)
    )
    monkeypatch.setattr(jev_client, "ask", partial(jev_client.ask, transport=transport))
    return await jev_check.check(key)


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
    async def test_a_working_key_passes_on_the_listing_the_vendor_really_sends(
        self,
        monkeypatch: pytest.MonkeyPatch,
        server: FakeTypeSafe,
        transport: Redirect,
    ) -> None:
        """
        TypeSafe lists the moving aliases only, and accepts the versioned pin
        unlisted (docs/08, "Models and versions"). A check that looked for the
        pin in the listing would fail every working key.
        """
        server.script(listed("jev-latest", "jev-preview"), answered(probe_body()))

        report = await run_check(monkeypatch, transport)

        assert report.passed, report.lines
        assert report.exit_code == jev_check.OK
        assert [s.url for s in transport.sent] == [MODELS_URL, SYSTEM_ONE_URL]
        assert json.loads(transport.sent[1].body)["model"] == PIN
        assert report.lines[-1] == "PASS"
        assert any("as expected" in line for line in report.lines)

    @pytest.mark.parametrize(
        "names",
        [(), ("jev-latest",), ("jev-1.12.0", PIN)],
        ids=["none", "alias", "pin"],
    )
    async def test_the_listing_never_decides_the_pin(
        self,
        monkeypatch: pytest.MonkeyPatch,
        server: FakeTypeSafe,
        transport: Redirect,
        names: tuple[str, ...],
    ) -> None:
        server.script(listed(*names), answered(probe_body()))

        report = await run_check(monkeypatch, transport)

        assert report.passed, report.lines
        assert [s.url for s in transport.sent] == [MODELS_URL, SYSTEM_ONE_URL]

    async def test_the_pin_is_proven_by_the_answer(
        self, monkeypatch: pytest.MonkeyPatch, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        """An answer from any model but the pin fails, whatever was listed."""
        server.script(listed(PIN), answered(probe_body(model="jev-1.14.0")))

        report = await run_check(monkeypatch, transport)

        assert not report.passed
        assert report.exit_code == jev_check.FAILED
        assert any("model_mismatch" in line for line in report.lines)

    async def test_a_refused_key_stops_before_a_question_is_asked(
        self, monkeypatch: pytest.MonkeyPatch, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        server.script(Reply(status=401, body=b'{"detail":"no"}', headers=JSON))

        report = await run_check(monkeypatch, transport)

        assert not report.passed
        assert report.exit_code == jev_check.FAILED
        assert [s.url for s in transport.sent] == [MODELS_URL]
        assert any("console.typesafe.ai" in line for line in report.lines)

    async def test_no_response_is_no_verdict_rather_than_a_refused_key(
        self, monkeypatch: pytest.MonkeyPatch, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        """A network failure says nothing about the key, and must not claim to."""
        transport.routes.extend([Route(port=closed_port()), Route(port=closed_port())])

        report = await run_check(monkeypatch, transport)

        assert report.verdict == "no_verdict"
        assert report.exit_code == jev_check.NO_VERDICT
        assert not any("refused" in line for line in report.lines), report.lines
        assert report.lines[-1] == "NO VERDICT"

    @pytest.mark.parametrize("status", [429, 503, 529])
    async def test_a_vendor_that_could_not_answer_is_no_verdict(
        self,
        monkeypatch: pytest.MonkeyPatch,
        server: FakeTypeSafe,
        transport: Redirect,
        status: int,
    ) -> None:
        server.script(Reply(status=status, body=b'{"error":"busy"}', headers=JSON))

        report = await run_check(monkeypatch, transport)

        assert report.exit_code == jev_check.NO_VERDICT, report.lines
        assert {s.url for s in transport.sent} == {MODELS_URL}

    async def test_a_probe_the_vendor_could_not_answer_is_no_verdict(
        self, monkeypatch: pytest.MonkeyPatch, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        server.script(
            listed("jev-latest"),
            Reply(status=503, body=b'{"error":"overloaded"}', headers=JSON),
        )

        report = await run_check(monkeypatch, transport)

        assert report.exit_code == jev_check.NO_VERDICT, report.lines
        assert any("server" in line for line in report.lines)

    async def test_the_answer_is_judged_as_the_lane_judges_it(
        self, monkeypatch: pytest.MonkeyPatch, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        """
        A 2xx the SDK could not read goes to the validator, as it does in the
        lane, and passes on its content; the SDK's objection is printed beside.
        """
        body = json.loads(probe_body())
        del body["usage"]
        server.script(listed("jev-latest"), answered(json.dumps(body).encode()))

        report = await run_check(monkeypatch, transport)

        assert report.passed, report.lines
        assert any("response_shape" in line for line in report.lines)
        assert any("as expected" in line for line in report.lines)

    async def test_the_wrong_answer_fails(
        self, monkeypatch: pytest.MonkeyPatch, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        server.script(listed(PIN), answered(probe_body(p=0.03)))

        report = await run_check(monkeypatch, transport)

        assert not report.passed
        assert report.exit_code == jev_check.FAILED
        assert report.lines[-1] == "FAIL"
        assert any("expected true" in line for line in report.lines)

    async def test_an_answer_the_lane_would_not_measure_fails(
        self, monkeypatch: pytest.MonkeyPatch, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        server.script(listed(PIN), answered(probe_body(model="jev-latest")))

        report = await run_check(monkeypatch, transport)

        assert not report.passed
        assert any("not measured" in line for line in report.lines)

    async def test_a_refused_probe_fails(
        self, monkeypatch: pytest.MonkeyPatch, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        server.script(
            listed(PIN),
            Reply(status=422, body=b'{"detail":[{"msg":"bad"}]}', headers=JSON),
        )

        report = await run_check(monkeypatch, transport)

        assert not report.passed
        assert report.exit_code == jev_check.FAILED
        assert any("invalid_request" in line for line in report.lines)

    @pytest.mark.parametrize(
        "replies",
        [
            pytest.param((listed(PIN), answered(probe_body())), id="pass"),
            pytest.param(
                (Reply(status=401, body=KEY.encode(), headers=JSON),), id="refused"
            ),
            pytest.param((listed(PIN), answered(b"not json")), id="garbled"),
            pytest.param((listed(PIN, KEY), answered(probe_body())), id="listed"),
            pytest.param(
                (listed(PIN), answered(probe_body(model=KEY))), id="model-field"
            ),
            pytest.param(
                (listed(PIN), answered(probe_body(answers={KEY: {"type": "noul"}}))),
                id="answer-key",
            ),
        ],
    )
    async def test_the_key_is_never_printed(
        self,
        monkeypatch: pytest.MonkeyPatch,
        server: FakeTypeSafe,
        transport: Redirect,
        replies: tuple[Reply, ...],
    ) -> None:
        """Even a vendor that echoes the key back cannot get it printed."""
        server.script(*replies)
        report = await run_check(monkeypatch, transport)
        assert KEY not in "\n".join(report.lines)

    async def test_no_run_of_a_long_key_is_printed_either(
        self, monkeypatch: pytest.MonkeyPatch, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        """
        The validator quotes a vendor's string truncated, and a truncated key is
        a prefix no log masks. Every run of it long enough to matter is withheld.
        """
        long_key = "sk-test-" + "7f3a9c1e5b" * 8
        server.script(listed(PIN), answered(probe_body(model=long_key)))

        report = await run_check(monkeypatch, transport, key=long_key)

        printed = "\n".join(report.lines)
        assert not any(
            long_key[i : i + jev_check.MIN_WITHHELD] in printed
            for i in range(len(long_key) - jev_check.MIN_WITHHELD + 1)
        ), printed
