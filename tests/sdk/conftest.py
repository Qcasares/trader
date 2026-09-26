"""
conftest.py (tests/sdk)
-----------------------
A fake TypeSafe server answering real HTTP, and a transport that delivers the
Jev client's requests to it.

Nothing between ``jev_client.ask`` and the socket is replaced. The request is
built by the real SDK and the real ``httpx2``; :class:`Redirect` records it
exactly as it would have left for the vendor — URL, headers, body and timeouts
— and then sends a copy over a real connection to :class:`FakeTypeSafe`, an
aiohttp server that answers with real status codes, headers and bytes. So what
a test asserts about the request is what the vendor would have received, and
what it asserts about the evidence is what the client made of a real response.
Mocking the SDK instead would only prove the mock matched a reading of the
SDK, and the SDK's defaults are exactly what the client exists to distrust.

Everything here needs ``typesafe-sdk``, which only
``requirements-programme.lock`` installs. Where it is absent — the main CI job,
a developer's venv — each test module skips itself with ``importorskip``. This
file does not: ``pytest tests/sdk`` loads it before collecting anything, and a
skip raised while loading it is an error, not a skip. So it imports everywhere,
and imports ``httpx2`` only where the SDK that brings it is installed.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import logging
import socket
import time
from collections import deque
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field

import pytest
from aiohttp import web

from src.programme import jev_catalogue, jev_client

SDK_INSTALLED = importlib.util.find_spec("typesafe_sdk") is not None

if SDK_INSTALLED:
    import httpx2

    _TransportBase: type = httpx2.AsyncBaseTransport
else:  # nothing here runs; the class below must still be definable
    _TransportBase = object

#: Where the pinned client must always send a request, whatever else is set.
ENDPOINT = jev_catalogue.JEV_BASE_URL + "/v1/systemone"


# ---------------------------------------------------------------------------
# The fake vendor
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Reply:
    """One scripted response. ``delay`` holds it back, for timeouts."""

    status: int = 200
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)
    delay: float = 0.0


@dataclass(frozen=True)
class Received:
    """A request as the fake server read it off the socket."""

    method: str
    path: str
    headers: dict[str, str]
    body: bytes
    at: float


class FakeTypeSafe:
    """
    Answers every request from a script of :class:`Reply`.

    Replies are used in order, and the last one repeats, so a single reply is
    also the answer to every retry of it.
    """

    def __init__(self) -> None:
        self.replies: deque[Reply] = deque([Reply()])
        self.received: list[Received] = []
        self.port = 0
        self._runner: web.AppRunner | None = None

    def script(self, *replies: Reply) -> None:
        self.replies = deque(replies)

    async def start(self) -> None:
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", self._handle)
        # A client that gives up on a slow reply cancels the handler, so a
        # timed-out request does not hold the server open at teardown.
        self._runner = web.AppRunner(
            app, handler_cancellation=True, shutdown_timeout=0.1
        )
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    async def _handle(self, request: web.Request) -> web.Response:
        self.received.append(
            Received(
                method=request.method,
                path=request.path_qs,
                headers={k.lower(): v for k, v in request.headers.items()},
                body=await request.read(),
                at=time.monotonic(),
            )
        )
        reply = self.replies.popleft() if len(self.replies) > 1 else self.replies[0]
        if reply.delay:
            await asyncio.sleep(reply.delay)
        return web.Response(status=reply.status, body=reply.body, headers=reply.headers)


# ---------------------------------------------------------------------------
# The transport
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Sent:
    """A request exactly as the client built it, before it was redirected."""

    method: str
    url: str
    headers: list[tuple[str, str]]
    body: bytes
    timeout: dict[str, float | None] | None

    def header(self, name: str) -> str | None:
        values = [v for k, v in self.headers if k.lower() == name.lower()]
        assert len(values) <= 1, f"{name} sent {len(values)} times"
        return values[0] if values else None


@dataclass(frozen=True)
class Route:
    """
    Where one attempt goes instead of the fake server.

    ``port`` sends it elsewhere — a closed port, for a real refused connection.
    ``read_timeout`` replaces the client's ten seconds, so a real read timeout
    can happen in a fraction of one.
    """

    port: int | None = None
    read_timeout: float | None = None


class Redirect(_TransportBase):
    """
    Records each request as the client built it, then delivers a copy locally.

    The original request is not modified, so the client's own view of it — the
    URL its errors and log lines would name — stays the vendor's. ``routes``
    reroutes attempts one at a time, in order; an attempt with no route goes
    to the fake server. The client closes its transport after every call, so
    ``closes`` counts calls closed and the inner transport is rebuilt on use.
    """

    def __init__(self, port: int) -> None:
        self.port = port
        self.sent: list[Sent] = []
        self.routes: deque[Route] = deque()
        self.closes = 0
        self._inner: httpx2.AsyncHTTPTransport | None = None

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        self.sent.append(
            Sent(
                method=request.method,
                url=str(request.url),
                headers=list(request.headers.multi_items()),
                body=request.content,
                timeout=dict(request.extensions.get("timeout") or {}) or None,
            )
        )
        route = self.routes.popleft() if self.routes else Route()
        extensions = dict(request.extensions)
        if route.read_timeout is not None:
            extensions["timeout"] = {
                **extensions["timeout"],
                "read": route.read_timeout,
            }
        forwarded = httpx2.Request(
            request.method,
            request.url.copy_with(
                scheme="http", host="127.0.0.1", port=route.port or self.port
            ),
            headers=request.headers,
            content=request.content,
            extensions=extensions,
        )
        if self._inner is None:
            self._inner = httpx2.AsyncHTTPTransport()
        return await self._inner.handle_async_request(forwarded)

    async def aclose(self) -> None:
        self.closes += 1
        if self._inner is not None:
            await self._inner.aclose()
            self._inner = None


def closed_port() -> int:
    """A local port with nothing listening on it: connecting is refused."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class Truncating:
    """
    A server that sends a 200's headers and the start of its body, then hangs up.

    Below aiohttp, because aiohttp will not send a body shorter than the length
    it declares. The client sees a response begin and never finish, which is a
    connection failure, not an answer.
    """

    #: What arrives before the connection closes: a status, a request id, and
    #: eight of the thousand bytes promised.
    PARTIAL = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Length: 1000\r\n"
        b"x-typesafe-request-id: req_cut\r\n"
        b"\r\n"
        b'{"model"'
    )

    def __init__(self) -> None:
        self.connections = 0
        self.port = 0
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.connections += 1
        head = await reader.readuntil(b"\r\n\r\n")
        for line in head.decode("latin-1").split("\r\n"):
            name, _, value = line.partition(":")
            if name.strip().lower() == "content-length":
                await reader.readexactly(int(value))
        writer.write(self.PARTIAL)
        await writer.drain()
        writer.close()
        # The client may reset the connection first; either way it is closed.
        with contextlib.suppress(ConnectionError):
            await writer.wait_closed()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def server() -> AsyncIterator[FakeTypeSafe]:
    fake = FakeTypeSafe()
    await fake.start()
    try:
        yield fake
    finally:
        await fake.stop()


@pytest.fixture
def transport(server: FakeTypeSafe) -> Redirect:
    return Redirect(server.port)


@pytest.fixture
async def truncating() -> AsyncIterator[Truncating]:
    cut = Truncating()
    await cut.start()
    try:
        yield cut
    finally:
        await cut.stop()


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """
    Undo what :func:`jev_client.ask` does to the process, after every test.

    It sets ``TYPESAFE_LOG_LEVEL`` for the whole process, and it silences the
    ``typesafe_sdk`` logger, which is shared by every test here. Each test also
    gets an empty rate-limit window, so no test waits on another's requests.
    """
    monkeypatch.delenv("TYPESAFE_LOG_LEVEL", raising=False)
    monkeypatch.setattr(
        jev_client,
        "_LIMITER",
        jev_client.RateLimiter(
            requests_per_minute=jev_catalogue.CLIENT_REQUESTS_PER_MINUTE,
            tokens_per_second=jev_catalogue.CLIENT_TOKENS_PER_SECOND,
        ),
    )
    sdk_logger = logging.getLogger("typesafe_sdk")
    saved = (
        sdk_logger.level,
        list(sdk_logger.filters),
        list(sdk_logger.handlers),
        sdk_logger.propagate,
    )
    yield
    sdk_logger.setLevel(saved[0])
    sdk_logger.filters[:] = saved[1]
    sdk_logger.handlers[:] = saved[2]
    sdk_logger.propagate = saved[3]
