"""
test_jev_client.py
------------------
``jev_client.ask`` against the real ``typesafe_sdk``, over real HTTP.

The client exists to distrust the SDK's defaults, and each distrust is tested
here by setting the environment or the server up to exploit it:

* ``TYPESAFE_BASE_URL`` and ``TYPESAFE_DEFAULT_MODEL`` are set to somewhere
  else and to an alias, and the request still goes to the vendor's host, with
  the pin, carrying the key it was handed and nothing merged into the body;
* the server answers every error the vendor documents, and several it does
  not, and each lands in its ``error_kind`` with the evidence the ledger needs:
  the status, the body exactly as sent and the request id — or none of the
  three when there was no response;
* retries are counted at the server, and ``Retry-After`` is sent and not
  deferred to;
* the SDK's logger is set to DEBUG, before and after a call and in a fresh
  process, and nothing it would log reaches a handler.

Every request asserted on is the one the client built for
``https://api.typesafe.ai``, recorded by ``conftest.Redirect`` before a copy
was delivered to the local fake.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("typesafe_sdk")

import typesafe_sdk  # noqa: E402

from src.programme import (  # noqa: E402
    jev_catalogue,
    jev_client,
    jev_questions,
    jev_validate,
)
from src.programme.jev_client import JevCall  # noqa: E402
from tests.sdk.conftest import (  # noqa: E402
    ENDPOINT,
    FakeTypeSafe,
    Redirect,
    Reply,
    Route,
    Truncating,
    closed_port,
)

pytestmark = pytest.mark.sdk

ROOT = Path(__file__).resolve().parents[2]

MODEL = jev_catalogue.DEFAULT_MODEL
KEY = "sk-test-5f1c9e0a7b3d4c21"
REQUEST_ID = "req_01a0da8e66f5"
JSON = "application/json"

PROBE = jev_questions.get("probe.connectivity")
REGIME = jev_questions.get("decision.regime")

#: The live API's answers to a missing key (403) and a bad key (401), as the
#: probes docs/08 describes recorded them, with the messages cut short.
MISSING_KEY_403 = (
    b'{"detail":{"error_type":"authentication_error",'
    b'"message":"Must supply an API key! ..."}}'
)
BAD_KEY_401 = (
    b'{"detail":{"error_type":"authentication_error",'
    b'"message":"Cannot authenticate with the server..."}}'
)
#: What a web application firewall in front of an API typically sends.
WAF_403 = (
    b"<html><head><title>403 Forbidden</title></head>"
    b"<body><h1>Request blocked</h1></body></html>"
)


def probe_body(**fields: Any) -> bytes:
    """A well-formed answer to the probe set, with ``fields`` replaced."""
    body: dict[str, Any] = {
        "model": MODEL,
        "answers": {"about_the_sun": {"type": "noul", "noul": 0.97}},
        "usage": {"input_tokens": 41, "output_tokens": 1},
    }
    body.update(fields)
    return json.dumps(body).encode()


def reply(
    body: bytes = b"",
    *,
    status: int = 200,
    content_type: str | None = JSON,
    request_id: str | None = REQUEST_ID,
    delay: float = 0.0,
    **headers: str,
) -> Reply:
    """A scripted response; ``headers`` are sent beside the two named ones."""
    sent = dict(headers)
    if content_type is not None:
        sent["Content-Type"] = content_type
    if request_id is not None:
        sent["x-typesafe-request-id"] = request_id
    return Reply(status=status, body=body, headers=sent, delay=delay)


async def ask_probe(transport: Redirect, **overrides: Any) -> JevCall:
    """Ask the probe set, as the connectivity job will."""
    arguments: dict[str, Any] = {
        "api_key": KEY,
        "model": MODEL,
        "state": PROBE.dump_state(PROBE.state_model()),
        "questions": PROBE.as_request_questions(),
        "transport": transport,
    }
    arguments.update(overrides)
    return await jev_client.ask(**arguments)


def body_pairs(body: bytes) -> list[tuple[str, Any]]:
    """The top level of a JSON body as its name/value pairs, duplicates kept."""
    return json.loads(body, object_pairs_hook=lambda pairs: pairs)


# ---------------------------------------------------------------------------
# What leaves
# ---------------------------------------------------------------------------


class TestWhatLeavesIsWhatWasHashed:
    """The request that leaves is the vendor's host, the pin, the key, the state."""

    async def test_the_environment_cannot_move_the_host_the_model_or_the_key(
        self,
        server: FakeTypeSafe,
        transport: Redirect,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Each of these is read by the SDK when its argument is not passed.
        monkeypatch.setenv("TYPESAFE_BASE_URL", "https://evil.example")
        monkeypatch.setenv("TYPESAFE_DEFAULT_MODEL", "jev-latest")
        monkeypatch.setenv("TYPESAFE_API_KEY", "sk-from-the-environment")
        server.script(reply(probe_body()))

        call = await ask_probe(transport)

        assert call.error_kind is None
        [sent] = transport.sent
        assert (sent.method, sent.url) == ("POST", ENDPOINT)
        assert sent.url == "https://api.typesafe.ai/v1/systemone"
        assert json.loads(sent.body)["model"] == MODEL
        assert sent.header("authorization") == f"Bearer {KEY}"

    async def test_the_body_is_the_state_the_model_and_the_questions_and_no_more(
        self, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        # Out of sorted order on purpose, at every level: the body must carry
        # the order the lane hashed.
        state = {"zulu": "last", "alpha": {"yankee": 2, "bravo": 1}}
        questions = {
            "second": {"type": "noul", "instructions": "Is `zulu` last?"},
            **REGIME.as_request_questions(),
        }
        server.script(reply(probe_body()))

        await ask_probe(transport, state=state, questions=questions)

        [sent] = transport.sent
        top = body_pairs(sent.body)
        assert [name for name, _ in top] == ["state", "model", "questions"]
        body = json.loads(sent.body)
        assert body["model"] == MODEL
        assert list(body["state"]) == ["zulu", "alpha"]
        assert list(body["state"]["alpha"]) == ["yankee", "bravo"]
        assert list(body["questions"]) == ["second", "regime"]
        assert body["questions"] == questions
        assert list(body["questions"]["regime"]["criteria"]) == list(
            REGIME.as_request_questions()["regime"]["criteria"]
        )

    async def test_the_key_travels_only_as_the_bearer_credential(
        self, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        server.script(reply(probe_body()))

        await ask_probe(transport)

        [sent] = transport.sent
        carrying = [name for name, value in sent.headers if KEY in value]
        assert carrying == ["authorization"]
        assert KEY.encode() not in sent.body
        assert sent.header("cookie") is None

    async def test_each_attempt_is_timed_out_at_ten_seconds(
        self, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        server.script(reply(probe_body()))

        await ask_probe(transport)

        [sent] = transport.sent
        assert sent.timeout == {
            "connect": 10.0,
            "read": 10.0,
            "write": 10.0,
            "pool": 10.0,
        }

    async def test_a_redirect_is_not_followed(
        self, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        # A redirect would carry the request, and a client that follows it
        # decides where the state goes on the server's say-so.
        server.script(
            reply(
                b"",
                status=307,
                content_type=None,
                Location="https://evil.example/v1/systemone",
            )
        )

        call = await ask_probe(transport)

        assert len(transport.sent) == 1
        assert len(server.received) == 1
        assert (call.http_status, call.error_kind) == (307, "client")
        assert call.error_class == "TypeSafeAPIError"

    async def test_the_http_client_is_closed_after_every_call(
        self, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        server.script(reply(probe_body()), reply(WAF_403, status=403))

        await ask_probe(transport)
        await ask_probe(transport)
        await ask_probe(transport, api_key="")

        assert transport.closes == 3


# ---------------------------------------------------------------------------
# A successful call
# ---------------------------------------------------------------------------


class TestASuccessIsRecordedAsItArrived:
    async def test_the_evidence_is_the_response_byte_for_byte(
        self, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        # Spacing and key order no serialiser would reproduce: a body rebuilt
        # from a parse would not match it.
        body = (
            b'{ "usage" : {"output_tokens":1,"input_tokens":41},\n'
            b'  "answers":{"about_the_sun":{"noul":0.97,"type":"noul"}},'
            b' "model":"jev-1.13.0"}'
        )
        server.script(reply(body))

        call = await ask_probe(transport)

        assert call == JevCall(
            http_status=200,
            raw_body=body.decode(),
            request_id=REQUEST_ID,
            latency_ms=call.latency_ms,
            error_class=None,
            error_kind=None,
            input_tokens=41,
            output_tokens=1,
        )
        assert isinstance(call.latency_ms, int)
        assert call.latency_ms >= 0

    async def test_the_validator_is_handed_what_the_wire_carried(
        self, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        # The SDK resolves a name given twice by keeping the last, so this
        # parses cleanly as an answer from the pin. It is not one: the first
        # `model` is an alias. Only the body as sent can show that.
        body = (
            b'{"model":"jev-latest","model":"jev-1.13.0",'
            b'"answers":{"about_the_sun":{"type":"noul","noul":0.97}},'
            b'"usage":{"input_tokens":41,"output_tokens":1}}'
        )
        server.script(reply(body))

        call = await ask_probe(transport)

        assert call.error_kind is None, "the SDK accepted it, as documented"
        assert call.raw_body == body.decode()
        validation = jev_validate.validate_body(
            call.raw_body, PROBE.as_request_questions(), MODEL
        )
        assert validation.status == "invalid"
        assert [a.invalid_reason for a in validation.answers] == ["unparseable"]

    async def test_a_nan_the_sdk_reads_as_a_number_reaches_the_validator_as_text(
        self, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        body = (
            b'{"model":"jev-1.13.0",'
            b'"answers":{"about_the_sun":{"type":"noul","noul":NaN}},'
            b'"usage":{"input_tokens":41,"output_tokens":1}}'
        )
        server.script(reply(body))

        call = await ask_probe(transport)

        assert call.error_kind is None, "the SDK accepted it, as documented"
        assert call.raw_body == body.decode()
        validation = jev_validate.validate_body(
            call.raw_body, PROBE.as_request_questions(), MODEL
        )
        assert validation.status == "invalid"

    async def test_a_success_is_read_as_utf8_whatever_it_declares(
        self, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        # The SDK read these bytes as JSON, which is UTF-8, whatever the header
        # says. The ledger reads them the same way, or an accented letter the
        # vendor sent would be recorded as two others.
        body = (
            '{"model":"jev-1.13.0",'
            '"answers":{"about_the_sun":{"type":"noul","noul":0.97}},'
            '"usage":{"input_tokens":41,"output_tokens":1},"note":"caf\u00e9"}'
        ).encode()
        server.script(reply(body, content_type="application/json; charset=latin-1"))

        call = await ask_probe(transport)

        assert call.error_kind is None
        assert call.raw_body == body.decode("utf-8")
        assert "caf\u00e9" in call.raw_body

    async def test_a_missing_request_id_is_none_not_an_exception(
        self, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        # The SDK's own `response.request_id` raises here.
        server.script(reply(probe_body(), request_id=None))

        call = await ask_probe(transport)

        assert (call.http_status, call.error_kind, call.request_id) == (200, None, None)

    async def test_a_blank_request_id_is_none(
        self, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        server.script(reply(probe_body(), request_id="  "))

        call = await ask_probe(transport)

        assert call.request_id is None

    @pytest.mark.parametrize(
        ("usage", "expected"),
        [
            ({"input_tokens": 41, "output_tokens": 1}, (41, 1)),
            ({"input_tokens": 0, "output_tokens": 0}, (0, 0)),
            ({"input_tokens": -5, "output_tokens": 1}, (None, 1)),
            ({"input_tokens": 41, "output_tokens": 2**31}, (41, None)),
            ({"input_tokens": 2**31 - 1, "output_tokens": None}, (2**31 - 1, None)),
            ({}, (None, None)),
        ],
    )
    async def test_a_token_count_the_ledger_cannot_hold_is_none(
        self,
        server: FakeTypeSafe,
        transport: Redirect,
        usage: dict[str, Any],
        expected: tuple[int | None, int | None],
    ) -> None:
        # The SDK reads these as integers and checks nothing else.
        server.script(reply(probe_body(usage=usage)))

        call = await ask_probe(transport)

        assert call.error_kind is None
        assert (call.input_tokens, call.output_tokens) == expected


# ---------------------------------------------------------------------------
# Failures
# ---------------------------------------------------------------------------

#: status, body, content type, error_kind, the SDK's class.
FAILURES = [
    (401, BAD_KEY_401, JSON, "auth", "TypeSafeAuthenticationError"),
    (401, b"Unauthorized", "text/plain", "auth", "TypeSafeAuthenticationError"),
    # A missing key: the live API's 403, not the documented 401.
    (403, MISSING_KEY_403, JSON, "auth", "TypeSafePermissionDeniedError"),
    # The body decides, not the label on it.
    (403, MISSING_KEY_403, "text/html", "auth", "TypeSafePermissionDeniedError"),
    (403, b'"Forbidden"', JSON, "auth", "TypeSafePermissionDeniedError"),
    (403, WAF_403, "text/html", "content_block", "TypeSafePermissionDeniedError"),
    (403, WAF_403, JSON, "content_block", "TypeSafePermissionDeniedError"),
    (403, b"Forbidden", "text/plain", "content_block", "TypeSafePermissionDeniedError"),
    (403, b"", None, "content_block", "TypeSafePermissionDeniedError"),
    (
        422,
        b'{"detail":[{"loc":["body","questions"],"msg":"Field required"}]}',
        JSON,
        "invalid_request",
        "TypeSafeUnprocessableEntityError",
    ),
    (
        429,
        b'{"detail":"Too many requests"}',
        JSON,
        "rate_limited",
        "TypeSafeRateLimitError",
    ),
    (
        500,
        b'{"detail":"Internal error"}',
        JSON,
        "server",
        "TypeSafeInternalServerError",
    ),
    (501, b"Not Implemented", "text/plain", "server", "TypeSafeInternalServerError"),
    (
        502,
        b"<html>Bad Gateway</html>",
        "text/html",
        "server",
        "TypeSafeInternalServerError",
    ),
    (503, b"", None, "server", "TypeSafeInternalServerError"),
    (504, b"upstream timeout", "text/plain", "server", "TypeSafeInternalServerError"),
    (529, b'{"detail":"Overloaded"}', JSON, "server", "TypeSafeInternalServerError"),
    (400, b'{"detail":"Bad request"}', JSON, "client", "TypeSafeBadRequestError"),
    (404, b'{"detail":"Not Found"}', JSON, "client", "TypeSafeNotFoundError"),
    (408, b"Request Timeout", "text/plain", "client", "TypeSafeAPIError"),
    (409, b'{"detail":"Conflict"}', JSON, "client", "TypeSafeAPIError"),
]


class TestEveryFailureIsClassedWithItsEvidence:
    """Every failure is a JevCall, never an exception, with what came back."""

    @pytest.mark.parametrize(
        ("status", "body", "content_type", "kind", "error_class"),
        FAILURES,
        ids=[f"{status}-{kind}" for status, _, _, kind, _ in FAILURES],
    )
    async def test_an_http_error(
        self,
        server: FakeTypeSafe,
        transport: Redirect,
        status: int,
        body: bytes,
        content_type: str | None,
        kind: str,
        error_class: str,
    ) -> None:
        server.script(reply(body, status=status, content_type=content_type))

        call = await ask_probe(transport)

        assert call == JevCall(
            http_status=status,
            raw_body=body.decode(),
            request_id=REQUEST_ID,
            latency_ms=call.latency_ms,
            error_class=error_class,
            error_kind=kind,
            input_tokens=None,
            output_tokens=None,
        )
        assert isinstance(call.latency_ms, int)

    def test_every_kind_the_table_uses_is_in_the_vocabulary(self) -> None:
        assert {kind for *_, kind, _ in FAILURES} <= set(jev_client.ERROR_KINDS)

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param(
                b'{"model":"jev-1.13.0",'
                b'"answers":{"about_the_sun":{"type":"noul","noul":0.97}}}',
                id="no-usage",
            ),
            pytest.param(probe_body(answers=[]), id="answers-not-an-object"),
            pytest.param(
                probe_body(usage={"input_tokens": 41.0, "output_tokens": 1}),
                id="a-count-that-is-not-an-integer",
            ),
            pytest.param(b"<html>ok</html>", id="not-json"),
            pytest.param(b"", id="empty"),
        ],
    )
    async def test_a_2xx_the_sdk_cannot_read_is_response_shape(
        self, server: FakeTypeSafe, transport: Redirect, body: bytes
    ) -> None:
        server.script(reply(body))

        call = await ask_probe(transport)

        assert call.error_kind == "response_shape"
        assert call.error_class == "TypeSafeAPIResponseValidationError"
        assert (call.http_status, call.request_id) == (200, REQUEST_ID)
        assert call.raw_body == body.decode()

    async def test_a_json_error_body_is_kept_as_sent_not_as_parsed(
        self, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        # The SDK hands its exception this body parsed: spacing gone, the
        # repeated name collapsed. The ledger gets the one that arrived.
        body = b'{ "detail" : "first",\n  "detail":[{"msg":"second"}] }'
        server.script(reply(body, status=422))

        call = await ask_probe(transport)

        assert call.error_kind == "invalid_request"
        assert call.raw_body == body.decode()

    async def test_a_body_is_read_as_utf8_whatever_it_declares(
        self, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        # A charset-honouring read would turn this into valid JSON, and hand
        # the validator a body the vendor's JSON contract does not allow.
        body = probe_body().decode().encode("utf-16")
        server.script(reply(body, content_type="application/json; charset=utf-16"))

        call = await ask_probe(transport)

        assert call.raw_body == body.decode("utf-8", "replace").replace(
            "\x00", "\ufffd"
        )
        validation = jev_validate.validate_body(
            call.raw_body, PROBE.as_request_questions(), MODEL
        )
        assert validation.status == "invalid"

    @pytest.mark.parametrize(
        ("body", "stored"),
        [
            (b"<html>blocked\x00</html>", "<html>blocked\ufffd</html>"),
            (b"caf\xe9 blocked", "caf\ufffd blocked"),
        ],
    )
    async def test_bytes_postgres_cannot_store_are_marked_not_dropped(
        self, server: FakeTypeSafe, transport: Redirect, body: bytes, stored: str
    ) -> None:
        server.script(
            reply(body, status=403, content_type="text/html; charset=latin-1")
        )

        call = await ask_probe(transport)

        assert call.raw_body == stored
        assert call.error_kind == "content_block"

    async def test_a_refused_connection_leaves_no_evidence(
        self, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        port = closed_port()
        transport.routes.extend([Route(port=port), Route(port=port)])

        call = await ask_probe(transport)

        assert call.error_kind == "connection"
        assert call.error_class == "TypeSafeAPIConnectionError"
        assert (call.http_status, call.raw_body, call.request_id) == (None, None, None)
        assert isinstance(call.latency_ms, int), "a request was attempted"
        assert server.received == []

    async def test_a_timeout_leaves_no_evidence(
        self, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        server.script(reply(probe_body(), delay=2.0))
        transport.routes.extend([Route(read_timeout=0.2), Route(read_timeout=0.2)])

        call = await ask_probe(transport)

        assert call.error_kind == "timeout"
        assert call.error_class == "TypeSafeAPITimeoutError"
        assert (call.http_status, call.raw_body, call.request_id) == (None, None, None)

    async def test_the_evidence_is_the_final_attempts_not_an_earlier_one(
        self, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        # The first attempt got a 503 with a body and a request id; the retry
        # got no response. The outcome rests on the retry, so nothing of the
        # 503 may be recorded as though it answered it.
        server.script(reply(b"busy", status=503, content_type="text/plain"))
        transport.routes.extend([Route(), Route(port=closed_port())])

        call = await ask_probe(transport)

        assert len(server.received) == 1
        assert call.error_kind == "connection"
        assert (call.http_status, call.raw_body, call.request_id) == (None, None, None)

    async def test_after_a_successful_retry_the_evidence_is_the_answer(
        self, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        server.script(
            reply(b"busy", status=503, content_type="text/plain", request_id="req_a"),
            reply(probe_body(), request_id="req_b"),
        )

        call = await ask_probe(transport)

        assert call.error_kind is None
        assert (call.http_status, call.request_id) == (200, "req_b")
        assert call.raw_body == probe_body().decode()
        # The latency is the call's, from the first attempt, so it spans the
        # backoff between the two.
        first, second = server.received
        assert call.latency_ms is not None
        assert call.latency_ms >= int((second.at - first.at) * 1000)

    async def test_a_response_cut_off_mid_body_leaves_no_evidence(
        self, transport: Redirect, truncating: Truncating
    ) -> None:
        # A status and a request id arrived, and then the connection closed:
        # there is no response to record, so none of it is recorded.
        transport.routes.extend([Route(port=truncating.port)] * 2)

        call = await ask_probe(transport)

        assert truncating.connections == 2
        assert (call.error_kind, call.error_class) == (
            "connection",
            "TypeSafeAPIConnectionError",
        )
        assert (call.http_status, call.raw_body, call.request_id) == (None, None, None)

    async def test_a_defect_before_sending_is_a_client_error_and_nothing_is_sent(
        self,
        server: FakeTypeSafe,
        transport: Redirect,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        class Broken(jev_client.RateLimiter):
            async def acquire(self, tokens: int) -> None:
                raise RuntimeError("a defect")

        monkeypatch.setattr(
            jev_client,
            "_LIMITER",
            Broken(requests_per_minute=1, tokens_per_second=1),
        )

        call = await ask_probe(transport)

        assert (call.error_kind, call.error_class) == ("client", "RuntimeError")
        assert (call.http_status, call.raw_body, call.latency_ms) == (None, None, None)
        assert transport.sent == []

    async def test_a_failure_to_close_does_not_lose_the_answer(
        self, server: FakeTypeSafe
    ) -> None:
        class FailingClose(Redirect):
            async def aclose(self) -> None:
                await super().aclose()
                raise RuntimeError("close failed")

        server.script(reply(probe_body()))

        call = await ask_probe(FailingClose(server.port))

        assert (call.http_status, call.error_kind) == (200, None)
        assert call.raw_body == probe_body().decode()

    @pytest.mark.parametrize("api_key", ["", "   ", "sk bad key", "sk-\x07bell"])
    async def test_a_key_the_sdk_refuses_is_a_client_error_and_nothing_is_sent(
        self,
        server: FakeTypeSafe,
        transport: Redirect,
        monkeypatch: pytest.MonkeyPatch,
        api_key: str,
    ) -> None:
        # A usable key in the environment changes nothing: the SDK is always
        # handed one, so it never goes looking.
        monkeypatch.setenv("TYPESAFE_API_KEY", KEY)

        call = await ask_probe(transport, api_key=api_key)

        assert call == JevCall(
            http_status=None,
            raw_body=None,
            request_id=None,
            latency_ms=None,
            error_class="TypeSafeError",
            error_kind="client",
            input_tokens=None,
            output_tokens=None,
        )
        assert transport.sent == []

    async def test_a_state_that_cannot_be_encoded_is_a_client_error(
        self, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        call = await ask_probe(transport, state={"text": object()})

        assert (call.error_kind, call.error_class) == ("client", "TypeSafeError")
        assert call.latency_ms is None
        assert transport.sent == []

    async def test_a_defect_reading_an_answer_still_returns_the_wire_evidence(
        self,
        server: FakeTypeSafe,
        transport: Redirect,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The vendor answered and was paid; a defect on this side must not lose
        # the body, and must not surface as an exception the lane cannot record.
        def broken(value: object) -> int | None:
            raise RuntimeError("a defect")

        monkeypatch.setattr(jev_client, "_count", broken)
        server.script(reply(probe_body()))

        call = await ask_probe(transport)

        assert (call.error_kind, call.error_class) == ("client", "RuntimeError")
        assert (call.http_status, call.request_id) == (200, REQUEST_ID)
        assert call.raw_body == probe_body().decode()

    async def test_cancellation_is_not_swallowed(
        self, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        server.script(reply(probe_body(), delay=5.0))
        task = asyncio.create_task(ask_probe(transport))
        deadline = time.monotonic() + 3.0
        while not server.received and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        assert server.received, "the request never arrived"

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert transport.closes == 1


# ---------------------------------------------------------------------------
# Retries
# ---------------------------------------------------------------------------


class TestRetriesAreCapped:
    # Written out, not read from the client: a status dropped from the policy
    # must fail here, not quietly leave the table.
    @pytest.mark.parametrize("status", [429, 500, 502, 503, 504, 529])
    async def test_a_transient_status_is_retried_once(
        self, server: FakeTypeSafe, transport: Redirect, status: int
    ) -> None:
        server.script(reply(b"", status=status, content_type=None))

        call = await ask_probe(transport)

        assert call.http_status == status
        assert len(server.received) == 2
        assert "x-typesafe-retry-count" not in server.received[0].headers
        assert server.received[1].headers["x-typesafe-retry-count"] == "1"

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 408, 409, 422, 501, 505])
    async def test_any_other_status_is_not_retried(
        self, server: FakeTypeSafe, transport: Redirect, status: int
    ) -> None:
        server.script(reply(b"", status=status, content_type=None))

        call = await ask_probe(transport)

        assert call.http_status == status
        assert len(server.received) == 1

    async def test_a_refused_connection_is_retried_once(
        self, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        port = closed_port()
        transport.routes.extend([Route(port=port)] * 3)

        await ask_probe(transport)

        assert len(transport.sent) == 2

    async def test_retry_after_is_not_deferred_to(
        self, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        # Both spellings, at a delay well inside the retry budget, so an SDK
        # honouring either would wait ten seconds here before retrying.
        server.script(
            reply(
                b'{"detail":"Too many requests"}',
                status=429,
                **{"Retry-After": "10", "retry-after-ms": "10000"},
            )
        )

        call = await ask_probe(transport)

        assert call.error_kind == "rate_limited"
        first, second = server.received
        assert second.at - first.at < 3.0

    def test_the_policy_is_the_one_documented(self) -> None:
        policy = jev_client._retry_policy(typesafe_sdk)

        assert isinstance(policy, typesafe_sdk.RetryPolicy)
        assert policy.max_retries == 1
        assert policy.timeout == 20.0
        assert policy.respect_retry_after is False
        assert policy.http_statuses == {429, 500, 502, 503, 504, 529}

    async def test_every_attempt_is_admitted_by_the_rate_limiter(
        self,
        server: FakeTypeSafe,
        transport: Redirect,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        charged: list[int] = []

        class Recording(jev_client.RateLimiter):
            async def acquire(self, tokens: int) -> None:
                charged.append(tokens)
                await super().acquire(tokens)

        monkeypatch.setattr(
            jev_client,
            "_LIMITER",
            Recording(requests_per_minute=1000, tokens_per_second=200_000),
        )
        server.script(reply(b"", status=503, content_type=None), reply(probe_body()))

        await ask_probe(transport)

        estimate = jev_catalogue.estimate_tokens(transport.sent[0].body.decode())
        assert charged == [estimate, estimate]


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

STATE_MARKER = "state-marker-4f7d0b2e"
ANSWER_MARKER = "answer-marker-9c1a5e37"


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def captured() -> Any:
    """Every record any logger emits, at DEBUG, for the length of a test."""
    root = logging.getLogger()
    handler = _Capture()
    level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        root.removeHandler(handler)
        root.setLevel(level)


def _leaks(records: list[logging.LogRecord]) -> list[str]:
    return [
        f"{r.name}: {r.getMessage()[:120]}"
        for r in records
        if r.name.startswith("typesafe_sdk")
        or any(m in r.getMessage() for m in (STATE_MARKER, ANSWER_MARKER, KEY))
    ]


class TestNothingReachesALog:
    """At DEBUG the SDK logs whole bodies. None of it may reach a handler."""

    async def test_an_sdk_logger_set_to_debug_before_the_call_is_silenced(
        self, server: FakeTypeSafe, transport: Redirect, captured: _Capture
    ) -> None:
        sdk_logger = logging.getLogger("typesafe_sdk")
        sdk_logger.setLevel(logging.DEBUG)
        direct = _Capture()
        sdk_logger.addHandler(direct)
        server.script(
            reply(probe_body(note=ANSWER_MARKER)),
            reply(WAF_403, status=403, content_type="text/html"),
        )

        for _ in range(2):
            await ask_probe(transport, state={"text": STATE_MARKER})

        assert _leaks(captured.records) == []
        assert direct.records == []
        assert any(r.name.startswith("httpx2") for r in captured.records), (
            "the capture saw nothing at all, so it proves nothing"
        )

    async def test_the_sdk_logger_is_held_above_critical(
        self, server: FakeTypeSafe, transport: Redirect
    ) -> None:
        # So the SDK does not even build the records: it checks its level
        # before formatting a body.
        logging.getLogger("typesafe_sdk").setLevel(logging.DEBUG)
        server.script(reply(probe_body()))

        await ask_probe(transport)

        sdk_logger = logging.getLogger("typesafe_sdk")
        assert sdk_logger.level == logging.CRITICAL + 1
        assert not sdk_logger.isEnabledFor(logging.CRITICAL)

    async def test_a_level_set_after_the_call_does_not_turn_it_back_on(
        self, server: FakeTypeSafe, transport: Redirect, captured: _Capture
    ) -> None:
        server.script(reply(probe_body()))
        await ask_probe(transport)

        # A logging configuration applied later, by anything.
        sdk_logger = logging.getLogger("typesafe_sdk")
        sdk_logger.setLevel(logging.DEBUG)
        direct = _Capture()
        sdk_logger.addHandler(direct)
        sdk_logger.debug("body=%s", STATE_MARKER)
        sdk_logger.critical("body=%s", STATE_MARKER)

        assert _leaks(captured.records) == []
        assert direct.records == []

    async def test_the_log_level_variable_is_off_after_a_call(
        self,
        server: FakeTypeSafe,
        transport: Redirect,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("TYPESAFE_LOG_LEVEL", "debug")
        server.script(reply(probe_body()))

        await ask_probe(transport)

        assert os.environ["TYPESAFE_LOG_LEVEL"] == "off"

    def test_a_fresh_process_told_to_log_at_debug_logs_nothing(self) -> None:
        # The SDK reads TYPESAFE_LOG_LEVEL once, when it is first imported,
        # which only a new interpreter can show.
        script = f"""
import asyncio, json, logging, sys

records = []

class Capture(logging.Handler):
    def emit(self, record):
        records.append([record.name, record.getMessage()])

logging.getLogger().addHandler(Capture())
logging.getLogger().setLevel(logging.DEBUG)
assert "typesafe_sdk" not in sys.modules

import httpx2
from src.programme import jev_client

def vendor(request):
    return httpx2.Response(
        200,
        json={{
            "model": {MODEL!r},
            "answers": {{"q": {{"type": "noul", "noul": 0.9}}}},
            "usage": {{"input_tokens": 3, "output_tokens": 1}},
            "note": {ANSWER_MARKER!r},
        }},
        headers={{"x-typesafe-request-id": "req_1"}},
    )

call = asyncio.run(
    jev_client.ask(
        api_key={KEY!r},
        model={MODEL!r},
        state={{"text": {STATE_MARKER!r}}},
        questions={{"q": {{"type": "noul", "instructions": "Is it?"}}}},
        transport=httpx2.MockTransport(vendor),
    )
)
print(json.dumps({{"status": call.http_status, "records": records}}))
"""
        env = {
            **os.environ,
            "TYPESAFE_LOG_LEVEL": "debug",
            "PYTHONPATH": str(ROOT),
        }
        done = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert done.returncode == 0, done.stderr
        outcome = json.loads(done.stdout.strip().splitlines()[-1])
        assert outcome["status"] == 200
        leaks = [
            f"{name}: {message[:120]}"
            for name, message in outcome["records"]
            if name.startswith("typesafe_sdk")
            or any(m in message for m in (STATE_MARKER, ANSWER_MARKER, KEY))
        ]
        assert leaks == []
        assert STATE_MARKER not in done.stderr
        assert outcome["records"], "the capture saw nothing at all"
