"""
test_web_fetch.py
-----------------
``src/programme/web_fetch.py``, the programme's one road to the web, over real
local HTTPS: a server with a certificate authority of its own
(``tests/fakes/web_server.py``), reached through the fetcher's test seam, with
every control the module promises still the shipped one.

The seam changes two things and no more. The resolver the global-only check
wraps sends the allow-listed host to 127.0.0.1 and an ephemeral port, and the
TLS context trusts the local authority and still verifies. Because 127.0.0.1
is exactly what the address check refuses, the tests that need the local
server admit that one address (the ``loopback`` fixture); the address tests do
not, and prove the check refuses it before any connection is made.

Each control has a test that fails when the control is removed:

* the input is an allow-list entry, by identity and as written, or a
  ``ValueError`` before any session exists — the entry edited in place to any
  other page included — and the fetch uses the values written;
* no redirect of any 3xx is followed — not to a listener, a lookalike host or
  the cloud metadata address;
* the environment's proxies and ``.netrc`` apply to nothing;
* a name that resolves to an address that is not global is refused;
* TLS is verified, against the system's trust store by default;
* the headers are fixed, and no cookie or credential is sent;
* the size is capped as declared, as received and as inflated, a gzip bomb
  included;
* the type, the charset and the encoding are strict, and only 200 is read;
* a slow drip times out, a dropped connection is not tried again, and
  cancellation propagates;
* nothing reaches a log but the status, the size and the hash;
* production never passes the seam, and nothing in ``src/programme`` turns TLS
  verification off, by any spelling the scan knows.
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import gzip
import hashlib
import ipaddress
import logging
import textwrap
import time
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any

import aiohttp
import pytest
from aiohttp.abc import AbstractResolver

from src.programme import web_fetch, web_sources
from src.programme.web_fetch import Fetched, FetchFailure
from tests.fakes.web_server import (
    LOOPBACK,
    Authority,
    FakeHTTPS,
    Listener,
    Reply,
    RoutingResolver,
)
from tests.unit.test_jev_client_offline import Seam, _modules, _seam_scan, _tree

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

SOURCE = web_sources.ALLOWED_SOURCES["pwb-readme"]
HOST = SOURCE.host
PATH = "/paperswithbacktest/awesome-systematic-trading/main/README.md"
CAP = SOURCE.max_bytes
TEXT = ("Content-Type", "text/plain; charset=utf-8")
GZIP = ("Content-Encoding", "gzip")

#: A sentence that must never reach a log, whatever becomes of the fetch.
SENTINEL = "a sentence no log line may ever carry"

#: The headers the fetcher sends, written out, so a changed value fails here
#: rather than being compared with itself. ``Accept-Encoding`` is ``gzip`` alone
#: because the fetcher inflates nothing else: asking for ``br`` or ``deflate``
#: would have every answer refused as ``content_encoding``.
FIXED_HEADERS = {
    "User-Agent": "trader-research/1",
    "Accept": "text/plain",
    "Accept-Encoding": "gzip",
}

#: Where a test points what must never be reached.
CAPTURE_HOST = "capture.test"
LOOKALIKE_HOST = "raw.githubusercontent.com.evil.test"


@pytest.fixture(scope="module")
def authority() -> Any:
    made = Authority()
    yield made
    made.close()


@pytest.fixture
def loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Admit 127.0.0.1, where the local servers listen, and nothing else the
    address check refuses. The address tests below do without this, and show
    the check refusing exactly this address.
    """
    real = web_fetch.address_permitted
    monkeypatch.setattr(
        web_fetch, "address_permitted", lambda host: host == LOOPBACK or real(host)
    )


async def _fetch(
    authority: Authority,
    reply: Reply,
    *,
    routes: dict[str, tuple[str, int]] | None = None,
    trusted: bool = True,
    hostnames: tuple[str, ...] = (HOST,),
) -> tuple[Fetched | FetchFailure, FakeHTTPS, RoutingResolver]:
    """Fetch the allow-listed source from a local server presenting ``hostnames``."""
    async with FakeHTTPS(authority.server_context(*hostnames), reply) as server:
        resolver = RoutingResolver({HOST: (LOOPBACK, server.port), **(routes or {})})

        def session() -> aiohttp.ClientSession:
            return web_fetch._session(
                resolver=resolver,
                ssl_context=authority.client_context() if trusted else None,
            )

        outcome = await web_fetch.fetch(SOURCE, session_factory=session)
    return outcome, server, resolver


def _gzipped(body: bytes) -> Reply:
    return Reply(headers=(TEXT, GZIP), body=gzip.compress(body))


# ---------------------------------------------------------------------------
# A page fetched whole
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("loopback")
class TestASuccess:
    async def test_the_page_is_fetched_whole_and_parses(
        self, authority: Authority
    ) -> None:
        """
        The fetcher and the parser meet: a synthetic README served over TLS
        comes back as the text sent, hashed and measured as it was served.
        """
        from tests.unit.test_web_sources import _readme

        body = _readme().encode("utf-8")
        outcome, _, _ = await _fetch(authority, Reply(body=body))
        assert isinstance(outcome, Fetched)
        assert outcome.source is SOURCE
        assert outcome.text == body.decode("utf-8")
        assert outcome.sha256 == hashlib.sha256(body).hexdigest()
        assert outcome.bytes == len(body)
        assert outcome.fetched_at.tzinfo is UTC
        assert datetime.now(UTC) - outcome.fetched_at < timedelta(minutes=1)
        assert web_sources.parse_pwb_readme(outcome.text).rows > 0

    async def test_the_request_is_fixed(self, authority: Authority) -> None:
        """
        One GET of the allow-listed path, with the headers the module names and
        those HTTP itself requires: no cookie, no credential, no proxy header.
        """
        _, server, resolver = await _fetch(authority, Reply(body=b"x"))
        [request] = server.requests
        assert (request.method, request.target, request.version) == (
            "GET",
            PATH,
            "HTTP/1.1",
        )
        assert request.headers == (
            ("Host", HOST),
            ("User-Agent", "trader-research/1"),
            ("Accept", "text/plain"),
            ("Accept-Encoding", "gzip"),
            # aiohttp's own, for a connection that is never reused.
            ("Connection", "close"),
        )
        assert dict(web_fetch.REQUEST_HEADERS) == FIXED_HEADERS
        assert resolver.asked == [HOST]

    async def test_gzip_is_inflated(self, authority: Authority) -> None:
        body = ("Invented Title\n" * 400).encode()
        outcome, _, _ = await _fetch(authority, _gzipped(body))
        assert isinstance(outcome, Fetched)
        assert outcome.text == body.decode()
        assert outcome.bytes == len(body)
        assert outcome.sha256 == hashlib.sha256(body).hexdigest()

    @pytest.mark.parametrize("framing", ["length", "chunked", "close"])
    async def test_exactly_the_cap_is_read(
        self, authority: Authority, framing: str
    ) -> None:
        outcome, _, _ = await _fetch(authority, Reply(body=b"a" * CAP, framing=framing))
        assert isinstance(outcome, Fetched) and outcome.bytes == CAP

    async def test_gzip_inflating_to_exactly_the_cap_is_read(
        self, authority: Authority
    ) -> None:
        outcome, _, _ = await _fetch(authority, _gzipped(b"b" * CAP))
        assert isinstance(outcome, Fetched) and outcome.bytes == CAP

    async def test_a_charset_is_read_in_any_case(self, authority: Authority) -> None:
        reply = Reply(
            headers=(("content-type", 'TEXT/PLAIN; Charset="UTF-8"'),), body=b"x"
        )
        outcome, _, _ = await _fetch(authority, reply)
        assert isinstance(outcome, Fetched)

    def test_the_text_stays_out_of_the_repr(self) -> None:
        fetched = Fetched(
            source=SOURCE,
            text=SENTINEL,
            sha256="0" * 64,
            bytes=1,
            fetched_at=datetime.now(UTC),
        )
        assert SENTINEL not in repr(fetched)


# ---------------------------------------------------------------------------
# Nothing is followed
# ---------------------------------------------------------------------------

REDIRECTS = (300, 301, 302, 303, 304, 305, 307, 308)
TARGETS = (
    f"https://{CAPTURE_HOST}/next",
    f"https://{LOOKALIKE_HOST}/paperswithbacktest/README.md",
    "http://169.254.169.254/latest/meta-data/",
)


@pytest.mark.usefixtures("loopback")
class TestNoRedirectIsFollowed:
    @pytest.mark.parametrize("status", REDIRECTS)
    @pytest.mark.parametrize("target", TARGETS)
    async def test_a_redirect_is_refused_and_not_followed(
        self, authority: Authority, status: int, target: str
    ) -> None:
        """
        Every 3xx is a failure, and nothing is asked for again: not the
        listener a redirect names, not a host that looks like the real one,
        and not the cloud metadata service, which a followed redirect would
        reach by address, around the resolver's check.
        """
        async with Listener() as capture:
            routes = {
                CAPTURE_HOST: (LOOPBACK, capture.port),
                LOOKALIKE_HOST: (LOOPBACK, capture.port),
            }
            reply = Reply(
                status=status, reason="Moved", headers=(("Location", target),)
            )
            outcome, server, resolver = await _fetch(authority, reply, routes=routes)
        assert outcome == FetchFailure("redirect", status)
        assert len(server.requests) == 1
        assert resolver.asked == [HOST]
        assert capture.connections == 0


# ---------------------------------------------------------------------------
# Only 200
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("loopback")
class TestOnly200IsRead:
    @pytest.mark.parametrize(
        "status",
        [201, 202, 203, 204, 206, 400, 401, 403, 404, 410, 418, 429, 500, 502, 503],
    )
    async def test_every_other_status_is_a_failure(
        self, authority: Authority, status: int
    ) -> None:
        # A 204 carries no body by definition, and a server that sent one
        # would be refused for breaking HTTP instead.
        body = b"" if status == 204 else SENTINEL.encode()
        reply = Reply(status=status, reason="Other", body=body)
        outcome, _, _ = await _fetch(authority, reply)
        assert outcome == FetchFailure("status", status)


# ---------------------------------------------------------------------------
# The size
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("loopback")
class TestTheSizeIsCapped:
    async def test_a_declared_length_over_the_cap_is_refused_before_reading(
        self, authority: Authority
    ) -> None:
        reply = Reply(body=b"", declared_length=CAP + 1)
        outcome, _, _ = await _fetch(authority, reply)
        assert outcome == FetchFailure("too_large", 200)

    @pytest.mark.parametrize("framing", ["chunked", "close"])
    async def test_an_undeclared_body_is_cut_at_the_cap(
        self, authority: Authority, framing: str
    ) -> None:
        reply = Reply(body=b"a" * (CAP + 1), framing=framing)
        outcome, _, _ = await _fetch(authority, reply)
        assert outcome == FetchFailure("too_large", 200)

    async def test_a_gzip_bomb_is_cut_at_the_cap(
        self, authority: Authority, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        A small body that inflates to 64 times the cap: the cap is on what it
        inflates to, and the inflater is never asked for more than one byte
        past it, so no more than that is ever held. A cap checked only after
        each chunk was inflated whole would give the same answer, having held
        a chunk's worth of zeros inflated a thousandfold first; the inflater is
        watched to tell the two apart.
        """
        asked: list[tuple[int, int]] = []
        inflater = zlib.decompressobj

        class Watched:
            def __init__(self, *args: Any) -> None:
                self._inner = inflater(*args)

            def decompress(self, data: bytes, max_length: int = 0) -> bytes:
                out = self._inner.decompress(data, max_length)
                asked.append((max_length, len(out)))
                return out

            def __getattr__(self, name: str) -> Any:
                return getattr(self._inner, name)

        monkeypatch.setattr(web_fetch.zlib, "decompressobj", Watched)
        reply = _gzipped(b"\0" * (CAP * 64))
        assert len(reply.body) < CAP // 8, "the bomb must be small on the wire"
        outcome, _, _ = await _fetch(authority, reply)
        assert outcome == FetchFailure("too_large", 200)
        assert asked, "the inflater was not used"
        assert all(0 < limit <= CAP + 1 for limit, _ in asked), asked
        assert max(size for _, size in asked) <= CAP + 1

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param(gzip.compress(b"text")[:-6], id="cut short"),
            pytest.param(gzip.compress(b"text") + b"more", id="followed by more"),
            pytest.param(gzip.compress(b"text") * 2, id="two members"),
            pytest.param(b"\x1f\x8b\x08\x00not gzip at all", id="corrupt"),
        ],
    )
    async def test_a_gzip_stream_must_end_where_the_body_ends(
        self, authority: Authority, body: bytes
    ) -> None:
        outcome, _, _ = await _fetch(authority, Reply(headers=(TEXT, GZIP), body=body))
        assert outcome == FetchFailure("protocol", 200)


# ---------------------------------------------------------------------------
# The type, the charset and the encoding
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("loopback")
class TestTheTypeAndTheEncodingAreStrict:
    @pytest.mark.parametrize(
        "headers",
        [
            pytest.param((("Content-Type", "text/html; charset=utf-8"),), id="html"),
            pytest.param((("Content-Type", "text/plain"),), id="no charset"),
            pytest.param(
                (("Content-Type", "text/plain; charset=iso-8859-1"),), id="latin-1"
            ),
            pytest.param(
                (("Content-Type", "application/octet-stream"),), id="octet-stream"
            ),
            pytest.param((TEXT, TEXT), id="two types"),
            pytest.param((), id="no type"),
        ],
    )
    async def test_a_type_not_allowed_is_refused(
        self, authority: Authority, headers: tuple[tuple[str, str], ...]
    ) -> None:
        reply = Reply(headers=headers, body=SENTINEL.encode())
        outcome, _, _ = await _fetch(authority, reply)
        assert outcome == FetchFailure("content_type", 200)

    @pytest.mark.parametrize(
        "coding", ["br", "deflate", "zstd", "compress", "gzip, gzip"]
    )
    async def test_a_coding_other_than_gzip_is_refused(
        self, authority: Authority, coding: str
    ) -> None:
        reply = Reply(headers=(TEXT, ("Content-Encoding", coding)), body=b"x")
        outcome, _, _ = await _fetch(authority, reply)
        assert outcome == FetchFailure("content_encoding", 200)

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param(b"caf\xe9", id="latin-1"),
            pytest.param(b"\xff\xfe", id="not a start byte"),
            pytest.param(b"\xc0\xaf", id="overlong"),
            pytest.param(b"\xed\xa0\x80", id="a surrogate"),
            pytest.param(b"caf\xc3", id="cut mid-character"),
        ],
    )
    async def test_a_body_that_is_not_utf_8_is_refused(
        self, authority: Authority, body: bytes
    ) -> None:
        outcome, _, _ = await _fetch(authority, Reply(body=body))
        assert outcome == FetchFailure("not_utf8", 200)


# ---------------------------------------------------------------------------
# TLS
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("loopback")
class TestTLSIsVerified:
    async def test_the_default_trusts_only_the_system_store(
        self, authority: Authority
    ) -> None:
        """
        With no context handed in, the session verifies against the system's
        trust store, which has never heard of the local authority.
        """
        outcome, server, _ = await _fetch(authority, Reply(body=b"x"), trusted=False)
        assert outcome == FetchFailure("tls", None)
        assert server.requests == []

    async def test_a_certificate_for_another_name_is_refused(
        self, authority: Authority
    ) -> None:
        outcome, server, _ = await _fetch(
            authority, Reply(body=b"x"), hostnames=("elsewhere.test",)
        )
        assert outcome == FetchFailure("tls", None)
        assert server.requests == []


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------


class TestOnlyGlobalAddressesAreReached:
    async def test_a_name_resolving_to_loopback_is_refused_before_connecting(
        self, authority: Authority
    ) -> None:
        """
        Without the loopback fixture, the shipped check stands: the host
        resolves to 127.0.0.1, the answer is refused, and the listener there
        is never connected to.
        """
        async with Listener() as capture:
            resolver = RoutingResolver({HOST: (LOOPBACK, capture.port)})

            def session() -> aiohttp.ClientSession:
                return web_fetch._session(
                    resolver=resolver, ssl_context=authority.client_context()
                )

            outcome = await web_fetch.fetch(SOURCE, session_factory=session)
        assert outcome == FetchFailure("address", None)
        assert resolver.asked == [HOST]
        assert capture.connections == 0

    @pytest.mark.parametrize(
        "address",
        [
            "10.0.0.5",
            "172.16.0.1",
            "192.168.1.1",
            "169.254.169.254",
            "::1",
            "fd00::1",
            "::ffff:127.0.0.1",
        ],
    )
    async def test_a_private_answer_is_refused_before_any_connection(
        self, authority: Authority, address: str
    ) -> None:
        """
        The same, end to end, for what a hostile name would answer with: the
        private networks, the metadata service, IPv6's loopback and unique
        local addresses, and loopback mapped into IPv6. Refused before a socket
        is opened, so it is quick; a connection attempted to any of them would
        be refused or wait out the connect timeout, and fail as something else.
        """
        resolver = RoutingResolver({HOST: (address, 443)})

        def session() -> aiohttp.ClientSession:
            return web_fetch._session(
                resolver=resolver, ssl_context=authority.client_context()
            )

        started = time.monotonic()
        outcome = await web_fetch.fetch(SOURCE, session_factory=session)
        assert outcome == FetchFailure("address", None)
        assert resolver.asked == [HOST]
        assert time.monotonic() - started < web_fetch.CONNECT_TIMEOUT_SECONDS

    @pytest.mark.parametrize(
        "answers",
        [
            pytest.param(["10.0.0.5"], id="private"),
            pytest.param(["169.254.169.254"], id="metadata"),
            pytest.param(["8.8.8.8", "127.0.0.1"], id="one bad of two"),
            pytest.param(["2606:4700::1111", "fd00::1"], id="unique local"),
            pytest.param(["::ffff:169.254.169.254"], id="mapped metadata"),
        ],
    )
    async def test_the_whole_answer_is_refused(self, answers: list[str]) -> None:
        """
        A name that resolves to a global address and a private one is refused
        whole, rather than trimmed to the global one: it is not a name to
        trust with either.
        """
        guard = web_fetch.GlobalOnlyResolver(_Answering(answers))
        with pytest.raises(web_fetch.NonGlobalAddressError):
            await guard.resolve(HOST, 443)

    async def test_a_global_answer_is_passed_through_whole(self) -> None:
        answers = ["8.8.8.8", "2606:4700::1111"]
        guard = web_fetch.GlobalOnlyResolver(_Answering(answers))
        assert [a["host"] for a in await guard.resolve(HOST, 443)] == answers

    async def test_no_answer_is_a_connection_failure(self) -> None:
        guard = web_fetch.GlobalOnlyResolver(_Answering([]))
        with pytest.raises(OSError) as refused:
            await guard.resolve(HOST, 443)
        assert not isinstance(refused.value, web_fetch.NonGlobalAddressError)

    @pytest.mark.parametrize(
        ("host", "permitted"),
        [
            ("8.8.8.8", True),
            ("185.199.108.133", True),
            ("2606:4700::1111", True),
            ("2001:4860:4860::8888", True),
            ("127.0.0.1", False),
            ("127.1.2.3", False),
            ("10.0.0.5", False),
            ("172.16.0.1", False),
            ("192.168.1.1", False),
            ("169.254.169.254", False),
            ("100.64.0.1", False),
            ("0.0.0.0", False),
            ("255.255.255.255", False),
            ("224.0.1.1", False),
            ("240.0.0.1", False),
            ("192.0.2.1", False),
            ("198.18.0.1", False),
            ("::1", False),
            ("::", False),
            ("fe80::1", False),
            ("fe80::1%eth0", False),
            ("fd00::1", False),
            ("fec0::1", False),
            ("ff02::1", False),
            ("::ffff:127.0.0.1", False),
            ("::ffff:169.254.169.254", False),
            ("64:ff9b::a9fe:a9fe", False),
            ("64:ff9b::808:808", False),
            ("2002:a9fe:a9fe::", False),
            ("2001:0:4136:e378:8000:63bf:3fff:fdd2", False),
            ("raw.githubusercontent.com", False),
            ("", False),
        ],
    )
    def test_which_addresses_are_permitted(self, host: str, permitted: bool) -> None:
        assert web_fetch.address_permitted(host) is permitted

    @pytest.mark.parametrize(
        ("address", "carried"),
        [
            ("::ffff:127.0.0.1", "127.0.0.1"),
            ("2002:a9fe:a9fe::", "169.254.169.254"),
            ("64:ff9b::a9fe:a9fe", "169.254.169.254"),
            ("2001:0:4136:e378:8000:63bf:3fff:fdd2", "192.0.2.45"),
        ],
    )
    def test_what_an_address_carries_is_checked_whatever_the_tables_say(
        self, address: str, carried: str
    ) -> None:
        """
        The check on the IPv4 address each prefix carries stands whatever a
        release's tables say of the prefix, and they differ: on 3.11.15 they
        read the mapped prefix through, refuse 6to4 and Teredo as private
        whatever they carry, and call NAT64 global and reserved. Here an
        address the tables call global in every respect is refused for what
        it carries alone.
        """

        class Lenient(ipaddress.IPv6Address):
            is_global = True
            is_private = False
            is_loopback = False
            is_link_local = False
            is_multicast = False
            is_reserved = False
            is_unspecified = False
            is_site_local = False

        lenient = Lenient(address)
        assert not ipaddress.ip_address(carried).is_global
        assert web_fetch._permitted(lenient) is False
        assert web_fetch._permitted(Lenient("2606:4700::1111")) is True


class _Answering(AbstractResolver):
    """An inner resolver that answers every name with the addresses given."""

    def __init__(self, hosts: list[str]) -> None:
        self.hosts = hosts

    async def resolve(self, host: str, port: int = 0, family: Any = 0) -> list[Any]:
        return [
            {
                "hostname": host,
                "host": address,
                "port": port,
                "family": 0,
                "proto": 0,
                "flags": 0,
            }
            for address in self.hosts
        ]

    async def close(self) -> None:
        return None


# ---------------------------------------------------------------------------
# The environment applies to nothing
# ---------------------------------------------------------------------------

PROXY_VARIABLES = (
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "ALL_PROXY",
    "all_proxy",
)


@pytest.mark.usefixtures("loopback")
class TestTheEnvironmentAppliesToNothing:
    async def test_a_proxy_in_the_environment_sees_nothing(
        self,
        authority: Authority,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """
        Every proxy variable points at a listener, with no exemption for any
        host, and a ``.netrc`` holds a password for the allow-listed host. The
        fetch goes where the resolver says, the listener is never reached, and
        no credential is sent.
        """
        netrc = _netrc(tmp_path)
        async with Listener() as capture:
            for variable in PROXY_VARIABLES:
                monkeypatch.setenv(variable, f"http://{LOOPBACK}:{capture.port}")
            monkeypatch.delenv("NO_PROXY", raising=False)
            monkeypatch.delenv("no_proxy", raising=False)
            monkeypatch.setenv("NETRC", str(netrc))
            outcome, server, _ = await _fetch(authority, Reply(body=b"x"))
        assert isinstance(outcome, Fetched)
        assert capture.connections == 0
        [request] = server.requests
        assert not {"authorization", "proxy-authorization"} & request.header_names()

    async def test_a_netrc_sends_no_credential(
        self,
        authority: Authority,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        for variable in (*PROXY_VARIABLES, "NO_PROXY", "no_proxy"):
            monkeypatch.delenv(variable, raising=False)
        monkeypatch.setenv("NETRC", str(_netrc(tmp_path)))
        outcome, server, _ = await _fetch(authority, Reply(body=b"x"))
        assert isinstance(outcome, Fetched)
        [request] = server.requests
        assert request.header("Authorization") is None

    async def test_the_session_is_built_as_documented(self) -> None:
        session = web_fetch._session()
        try:
            assert session.trust_env is False
            assert isinstance(session.cookie_jar, aiohttp.DummyCookieJar)
            assert session.auto_decompress is False
            assert dict(session.headers) == FIXED_HEADERS
            assert session.timeout.total == web_fetch.TOTAL_TIMEOUT_SECONDS
            assert session.timeout.connect == web_fetch.CONNECT_TIMEOUT_SECONDS
            connector = session.connector
            assert isinstance(connector, aiohttp.TCPConnector)
            assert connector.force_close and connector.limit == 1
        finally:
            await session.close()


def _netrc(directory: Path) -> Path:
    path = directory / "netrc"
    path.write_text(
        f"machine {HOST} login someone password not-a-real-secret\n"
        "default login someone password not-a-real-secret\n"
    )
    path.chmod(0o600)
    return path


# ---------------------------------------------------------------------------
# Time, one attempt, and cancellation
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("loopback")
class TestTime:
    def test_the_timeouts_fit_inside_the_shutdown_grace(self) -> None:
        from src.programme import main

        assert web_fetch.CONNECT_TIMEOUT_SECONDS == 5.0
        assert web_fetch.TOTAL_TIMEOUT_SECONDS == 20.0
        assert web_fetch.TOTAL_TIMEOUT_SECONDS < main.JEV_SHUTDOWN_GRACE_SECONDS

    async def test_a_slow_drip_times_out(
        self, authority: Authority, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        A server that sends a byte every few hundredths of a second never
        trips a read timeout; the total does. Shortened here, as read at each
        fetch, so the test does not wait twenty seconds — to a second and a
        half, ample for a local handshake, against a drip of ten seconds, so
        the status says the timeout fell while the body dripped.
        """
        monkeypatch.setattr(web_fetch, "TOTAL_TIMEOUT_SECONDS", 1.5)
        reply = Reply(body=b"a" * 200, chunk=1, delay=0.05)
        started = time.monotonic()
        outcome, _, _ = await _fetch(authority, reply)
        assert outcome == FetchFailure("timeout", 200)
        assert time.monotonic() - started < 6

    async def test_a_dropped_connection_is_not_retried(
        self, authority: Authority
    ) -> None:
        """
        aiohttp sends an idempotent request again when the connection closes
        before a response. One attempt is one: the server sees one connection
        and one request, and the fetch fails.
        """
        outcome, server, _ = await _fetch(authority, Reply(drop=True))
        assert outcome == FetchFailure("connection", None)
        assert server.connections == 1 and len(server.requests) == 1

    async def test_cancellation_propagates(self, authority: Authority) -> None:
        async with FakeHTTPS(
            authority.server_context(HOST), Reply(stall=True)
        ) as server:
            resolver = RoutingResolver({HOST: (LOOPBACK, server.port)})

            def session() -> aiohttp.ClientSession:
                return web_fetch._session(
                    resolver=resolver, ssl_context=authority.client_context()
                )

            task = asyncio.create_task(web_fetch.fetch(SOURCE, session_factory=session))
            await asyncio.wait_for(server.arrived.wait(), 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


# ---------------------------------------------------------------------------
# A response that breaks HTTP
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("loopback")
class TestABrokenResponse:
    @pytest.mark.parametrize(
        "raw",
        [
            pytest.param(b"garbage\r\n\r\n", id="no status line"),
            pytest.param(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/plain; charset=utf-8\r\n"
                b"Content-Length: 50\r\n\r\nshort",
                id="shorter than declared",
            ),
            pytest.param(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/plain; charset=utf-8\r\n"
                b"Transfer-Encoding: chunked\r\n\r\nzz\r\nbad\r\n",
                id="a bad chunk",
            ),
        ],
    )
    async def test_it_is_a_protocol_failure(
        self, authority: Authority, raw: bytes
    ) -> None:
        outcome, _, _ = await _fetch(authority, Reply(raw=raw))
        assert outcome.kind == "protocol", outcome


# ---------------------------------------------------------------------------
# Only an allow-list entry is fetched
# ---------------------------------------------------------------------------


class _Duck:
    """Every attribute an allowed source has, and not one."""

    def __init__(self, source: web_sources.AllowedSource) -> None:
        for f in dataclasses.fields(source):
            setattr(self, f.name, getattr(source, f.name))


class TestOnlyTheAllowListIsFetched:
    @pytest.mark.parametrize(
        "candidate",
        [
            pytest.param(dataclasses.replace(SOURCE), id="an equal copy"),
            pytest.param(
                dataclasses.replace(
                    SOURCE, url=f"https://{CAPTURE_HOST}/x", host=CAPTURE_HOST
                ),
                id="the same name, another page",
            ),
            pytest.param(SOURCE.url, id="its URL as a string"),
            pytest.param(_Duck(SOURCE), id="a lookalike object"),
            pytest.param(None, id="nothing"),
        ],
    )
    async def test_anything_else_is_refused_before_any_session(
        self, candidate: Any
    ) -> None:
        built: list[int] = []

        async with Listener() as capture:
            resolver = RoutingResolver(
                {HOST: (LOOPBACK, capture.port), CAPTURE_HOST: (LOOPBACK, capture.port)}
            )

            def session() -> aiohttp.ClientSession:
                built.append(1)
                return web_fetch._session(resolver=resolver)

            with pytest.raises(ValueError):
                await web_fetch.fetch(candidate, session_factory=session)
        assert built == []
        assert resolver.asked == []
        assert capture.connections == 0

    @pytest.mark.parametrize(
        ("edits", "complaint"),
        [
            pytest.param(
                {"url": SOURCE.url.replace("https://", "http://")},
                "https",
                id="to plain http",
            ),
            pytest.param(
                {"url": f"https://{CAPTURE_HOST}/any/page.txt", "host": CAPTURE_HOST},
                "as web_sources wrote",
                id="to another https page",
            ),
            pytest.param(
                {"max_bytes": web_sources.MAX_SOURCE_BYTES},
                "as web_sources wrote",
                id="to a larger cap",
            ),
            pytest.param(
                {"content_types": ("text/html",)},
                "as web_sources wrote",
                id="to another type",
            ),
        ],
    )
    async def test_an_entry_edited_in_place_is_refused(
        self, edits: dict[str, Any], complaint: str
    ) -> None:
        """
        The entry is frozen, but ``object.__setattr__`` edits a frozen
        dataclass anyway. Checking the entry's rules again caught an edit that
        broke one; an entry pointed at another well-formed https page broke
        none and was fetched. The fetcher now compares the entry with the
        values ``web_sources`` wrote, so any edit is refused, before any
        session exists and with nothing connected to.
        """
        originals = {name: getattr(SOURCE, name) for name in edits}
        built: list[int] = []
        async with Listener() as capture:
            resolver = RoutingResolver({CAPTURE_HOST: (LOOPBACK, capture.port)})

            def session() -> aiohttp.ClientSession:
                built.append(1)
                return web_fetch._session(resolver=resolver)

            for name, value in edits.items():
                object.__setattr__(SOURCE, name, value)
            try:
                with pytest.raises(ValueError, match=complaint):
                    await web_fetch.fetch(SOURCE, session_factory=session)
            finally:
                for name, value in originals.items():
                    object.__setattr__(SOURCE, name, value)
        assert (built, resolver.asked, capture.connections) == ([], [], 0)
        assert web_sources.as_written(SOURCE) is not None

    async def test_an_entry_edited_through_its_slots_is_refused(self) -> None:
        """
        A slot's descriptor edits the entry without ``__setattr__`` at all; the
        URL and the host moved together keep every rule an entry is held to.
        """
        url, host = SOURCE.url, SOURCE.host
        type(SOURCE).url.__set__(SOURCE, f"https://{CAPTURE_HOST}/page.txt")
        type(SOURCE).host.__set__(SOURCE, CAPTURE_HOST)
        try:
            assert web_sources.allowed_source_problem(SOURCE.name, SOURCE) is None
            with pytest.raises(ValueError, match="as web_sources wrote"):
                await web_fetch.fetch(SOURCE)
        finally:
            type(SOURCE).url.__set__(SOURCE, url)
            type(SOURCE).host.__set__(SOURCE, host)
        assert (SOURCE.url, SOURCE.host) == (url, host)

    async def test_a_list_rebound_to_another_page_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        A name that holds the list rebound to one holding another page — the
        fetcher's own, as ``vars(web_fetch)`` or ``globals()`` would — passes
        the identity check against that name, and is refused by the record of
        what ``web_sources`` wrote.
        """
        other = dataclasses.replace(
            SOURCE, url=f"https://{CAPTURE_HOST}/page.txt", host=CAPTURE_HOST
        )
        monkeypatch.setattr(
            web_fetch, "ALLOWED_SOURCES", MappingProxyType({other.name: other})
        )
        with pytest.raises(ValueError, match="as web_sources wrote"):
            await web_fetch.fetch(other)

    @pytest.mark.usefixtures("loopback")
    async def test_the_fetch_uses_the_values_written(
        self, authority: Authority, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        What is checked is what is fetched: the request is made with the values
        the check returned, never read again from the live entry, which another
        task could edit between the check and the request.
        """
        written = web_sources.as_written(SOURCE)
        assert written is not None
        moved = written._replace(url=f"https://{HOST}/written/path.md")
        monkeypatch.setattr(web_fetch.web_sources, "as_written", lambda s: moved)
        _, server, _ = await _fetch(authority, Reply(body=b"x"))
        [request] = server.requests
        assert request.target == "/written/path.md"


# ---------------------------------------------------------------------------
# The logs
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("loopback")
class TestNothingFetchedReachesALog:
    async def test_the_body_stays_out_whatever_happens(
        self, authority: Authority, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        A page's words go to the parser and nowhere else. Every outcome here
        carries the sentinel in its body; the logs hold status, size and hash,
        and not one word of it.
        """
        body = f"{SENTINEL}\n".encode() * 3
        replies = [
            Reply(body=body),
            _gzipped(body),
            Reply(headers=(("Content-Type", "text/html; charset=utf-8"),), body=body),
            Reply(body=body + b"\xff"),
            Reply(body=body * (CAP // len(body) + 1), framing="chunked"),
            Reply(status=500, reason="Error", body=body),
        ]
        with caplog.at_level(logging.DEBUG):
            outcomes = [(await _fetch(authority, r))[0] for r in replies]
        assert [o.kind for o in outcomes if isinstance(o, FetchFailure)] == [
            "content_type",
            "not_utf8",
            "too_large",
            "status",
        ]
        said = "\n".join(record.getMessage() for record in caplog.records)
        assert caplog.records, "nothing was logged, so this proves nothing"
        assert SENTINEL not in said
        assert "no log line" not in said
        fetched = outcomes[0]
        assert isinstance(fetched, Fetched)
        assert f"{fetched.bytes} bytes, sha256 {fetched.sha256}" in said


# ---------------------------------------------------------------------------
# The seam, and TLS, in the source
# ---------------------------------------------------------------------------

FETCH_SEAM = Seam("src.programme.web_fetch", "fetch", "session_factory")

#: The session builder's two test parameters, held to the same rule: a test
#: may hand ``_session`` a resolver or a TLS context; production calls it
#: with nothing.
BUILDER_SEAMS = (
    Seam("src.programme.web_fetch", "_session", "resolver"),
    Seam("src.programme.web_fetch", "_session", "ssl_context"),
)

#: A stand-in for the fetcher, shaped as the real one is.
FETCHER_STUB = (
    "async def fetch(source, *, session_factory=None):\n    ...\n"
    "def _session(*, resolver=None, ssl_context=None):\n    ...\n"
)


def _web_offences(caller: str, seam: Seam = FETCH_SEAM) -> list[str]:
    files = {
        "src/programme/web_fetch.py": FETCHER_STUB,
        "src/programme/web_ingest.py": textwrap.dedent(caller),
    }
    return _seam_scan(_modules(files), seam)[0]


class TestTheSeam:
    def test_production_code_never_passes_one(self) -> None:
        """
        ``session_factory`` decides where a request goes and whom it trusts, so
        it is a test's alone. Read from ``src/`` by the scan that holds
        ``jev_client``'s transport, forwarding and ``**kwargs`` included.
        """
        modules = _tree(SRC)
        assert FETCH_SEAM.module in modules
        for seam in (FETCH_SEAM, *BUILDER_SEAMS):
            offences, seams = _seam_scan(modules, seam)
            assert not offences, "\n".join(offences)
            assert (seam.module, seam.function) in seams

    @pytest.mark.parametrize(
        ("caller", "complaint"),
        [
            (
                """
                from src.programme import web_fetch

                async def ingest(source, make):
                    return await web_fetch.fetch(source, session_factory=make)
                """,
                "does not default to None",
            ),
            (
                """
                from src.programme import web_fetch

                MAKE = object()

                async def ingest(source):
                    return await web_fetch.fetch(source, session_factory=MAKE)
                """,
                "not a parameter",
            ),
            (
                """
                from src.programme import web_fetch

                async def ingest(source, **options):
                    return await web_fetch.fetch(source, **options)
                """,
                "spreads arguments",
            ),
            (
                """
                from src.programme import web_fetch

                async def ingest(source):
                    return await getattr(web_fetch, "fetch")(source)
                """,
                "through getattr",
            ),
            (
                """
                import functools
                from src.programme import web_fetch

                FETCH = functools.partial(web_fetch.fetch, session_factory=None)
                """,
                "other than to call it",
            ),
            (
                """
                from src.programme.web_fetch import fetch as get

                async def ingest(source):
                    return await get(source, session_factory=lambda: None)
                """,
                "passes lambda",
            ),
        ],
    )
    def test_the_scan_finds_each_spelling(self, caller: str, complaint: str) -> None:
        [offence] = _web_offences(caller)
        assert "src/programme/web_ingest.py" in offence
        assert complaint in offence

    def test_forwarding_the_seam_or_leaving_it_out_is_allowed(self) -> None:
        caller = """
        from src.programme import web_fetch

        async def ingest(source, *, session_factory=None):
            return await web_fetch.fetch(source, session_factory=session_factory)

        async def run(source):
            await ingest(source)
            await web_fetch.fetch(source)
            await web_fetch.fetch(source, session_factory=None)
        """
        assert _web_offences(caller) == []

    @pytest.mark.parametrize("seam", BUILDER_SEAMS, ids=lambda s: s.parameter)
    def test_the_builder_is_called_with_nothing(self, seam: Seam) -> None:
        caller = f"""
        from src.programme import web_fetch

        def build(thing):
            return web_fetch._session({seam.parameter}=thing)
        """
        [offence] = _web_offences(caller, seam)
        assert "does not default to None" in offence


#: Keywords that decide TLS verification where they are passed.
_TLS_KEYWORDS = frozenset(
    {"ssl", "ssl_context", "verify", "verify_ssl", "check_hostname", "cert_reqs"}
)

#: Attributes of a context that decide verification: nothing in the programme
#: sets them, whatever the value, since a default context's are the verifying
#: ones.
_TLS_ATTRIBUTES = frozenset({"check_hostname", "verify_mode"})

#: Names that disable verification, or name what does, wherever they appear —
#: ``_create_stdlib_context`` is an unverified context too — including as a
#: string handed to ``setattr`` or ``getattr``.
_TLS_NAMES = frozenset(
    {
        "CERT_NONE",
        "CERT_OPTIONAL",
        "_create_unverified_context",
        "_create_stdlib_context",
        *_TLS_ATTRIBUTES,
    }
)

#: What makes a connection or a client, into which no argument may be spread,
#: since a spread keyword is one no scan can read.
_TLS_CALLEES = frozenset(
    {
        "TCPConnector",
        "ClientSession",
        "AsyncClient",
        "Client",
        "AsyncHTTPTransport",
        "HTTPTransport",
        "SSLContext",
        "create_default_context",
        "wrap_socket",
        "create_connection",
        "open_connection",
        "start_tls",
        "request",
        "get",
        "post",
        "urlopen",
    }
)


def _tls_disabled(relative: str, source: str) -> list[str]:
    """
    Every place in ``source`` that can switch TLS verification off:

    * ``ssl.SSLContext(...)`` built with anything but ``PROTOCOL_TLS_CLIENT``,
      since the bare constructor, and every other protocol, verifies nothing;
    * ``ssl``, ``ssl_context``, ``verify``, ``verify_ssl``, ``check_hostname``
      or ``cert_reqs`` passed anything but ``True``, ``None``, a call to
      ``create_default_context``, a keyword-only parameter of the enclosing
      function that defaults to ``None`` (a test seam the seam scan holds), or
      a choice between those — so ``False``, ``0``, a name bound to ``False``
      and an unverified context are all refused;
    * any assignment to a context's ``check_hostname`` or ``verify_mode``;
    * arguments spread with ``**`` into a call that makes a connection or a
      client, a dict literal included;
    * ``CERT_NONE``, ``CERT_OPTIONAL``, the unverified context builders, and the
      two attributes, by name, attribute or string, so ``setattr(ctx,
      "check_hostname", False)`` and ``getattr(ssl, "CERT_NONE")`` are found.

    A scan of spellings, not a sandbox; the behavioural tests of the fetcher
    and of the Jev client over an untrusted local server hold the rest.
    """
    found: list[str] = []
    tree = ast.parse(source)

    def callee(node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    def seams(function: ast.AST | None) -> set[str]:
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return set()
        arguments = function.args
        return {
            argument.arg
            for argument, default in zip(
                arguments.kwonlyargs, arguments.kw_defaults, strict=True
            )
            if isinstance(default, ast.Constant) and default.value is None
        }

    def allowed(value: ast.expr, parameters: set[str]) -> bool:
        if isinstance(value, ast.Constant):
            return value.value is True or value.value is None
        if isinstance(value, ast.Call):
            return callee(value.func) == "create_default_context"
        if isinstance(value, ast.Name):
            return value.id in parameters
        if isinstance(value, ast.IfExp):
            return allowed(value.body, parameters) and allowed(value.orelse, parameters)
        return False

    def visit(node: ast.AST, function: ast.AST | None) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            function = node
        where = f"{relative}:{getattr(node, 'lineno', '?')}"
        if isinstance(node, ast.Call):
            name = callee(node.func)
            if name == "SSLContext":
                protocol = node.args[0] if node.args else None
                for keyword in node.keywords:
                    if keyword.arg == "protocol":
                        protocol = keyword.value
                if protocol is None or callee(protocol) != "PROTOCOL_TLS_CLIENT":
                    found.append(f"{where}: SSLContext without PROTOCOL_TLS_CLIENT")
            for keyword in node.keywords:
                if keyword.arg in _TLS_KEYWORDS and not allowed(
                    keyword.value, seams(function)
                ):
                    found.append(f"{where}: {keyword.arg}={ast.unparse(keyword.value)}")
                if keyword.arg is None and name in _TLS_CALLEES:
                    found.append(f"{where}: arguments spread into {name}")
        elif isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and target.attr in _TLS_ATTRIBUTES:
                    found.append(f"{where}: assigns {target.attr}")
        elif isinstance(node, ast.Name) and node.id in _TLS_NAMES:
            found.append(f"{where}: {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr in _TLS_NAMES:
            if not isinstance(node.ctx, ast.Store):
                found.append(f"{where}: {node.attr}")
        elif isinstance(node, ast.Constant) and node.value in _TLS_NAMES:
            found.append(f"{where}: {node.value!r}")
        for child in ast.iter_child_nodes(node):
            visit(child, function)

    visit(tree, None)
    return found


class TestTLSIsNeverTurnedOff:
    def test_nothing_in_the_programme_turns_verification_off(self) -> None:
        offenders: list[str] = []
        paths = sorted((SRC / "programme").rglob("*.py"))
        assert any(p.name == "web_fetch.py" for p in paths)
        for path in paths:
            relative = path.relative_to(ROOT).as_posix()
            offenders += _tls_disabled(relative, path.read_text("utf-8"))
        assert not offenders, "\n".join(offenders)

    @pytest.mark.parametrize(
        "source",
        [
            "aiohttp.TCPConnector(ssl=False)",
            "session.get(url, ssl=False)",
            "aiohttp.TCPConnector(verify_ssl=False)",
            "httpx2.AsyncClient(verify=False)",
            "context = ssl.create_default_context()\ncontext.check_hostname = False",
            "context.verify_mode = ssl.CERT_NONE",
            "from ssl import CERT_NONE\nmode = CERT_NONE",
            "context = ssl._create_unverified_context()",
            "mode = getattr(ssl, 'CERT_NONE')",
            # What review found the first scan could not see.
            "aiohttp.TCPConnector(ssl=ssl.SSLContext())",
            "aiohttp.TCPConnector(ssl=ssl.SSLContext(ssl.PROTOCOL_TLS))",
            "context = ssl.SSLContext(protocol=ssl.PROTOCOL_TLS_SERVER)",
            "OFF = False\naiohttp.TCPConnector(ssl=OFF)",
            'aiohttp.TCPConnector(**{"ssl": False})',
            "options = {}\naiohttp.TCPConnector(**options)",
            'setattr(ctx, "check_hostname", False)',
            "ctx.verify_mode = 0",
            "ctx.check_hostname = True if strict else False",
            "httpx2_module.AsyncClient(verify=ssl.SSLContext())",
            "httpx2_module.AsyncClient(verify=make_context())",
            "context = ssl._create_stdlib_context()",
            "ssl.wrap_socket(sock, cert_reqs=ssl.CERT_OPTIONAL)",
            "def build(context=None):\n    return aiohttp.TCPConnector(ssl=context)",
        ],
    )
    def test_the_scan_finds_each_spelling(self, source: str) -> None:
        assert _tls_disabled("src/programme/x.py", source)

    def test_the_scan_leaves_verification_alone(self) -> None:
        source = (
            "aiohttp.TCPConnector(ssl=True)\n"
            "context = ssl.create_default_context()\n"
            "context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)\n"
            "httpx2_module.AsyncClient(verify=ssl.create_default_context())\n"
            "def build(*, ssl_context=None):\n"
            "    return aiohttp.TCPConnector(\n"
            "        ssl=ssl_context if ssl_context is not None else True\n"
            "    )\n"
        )
        assert _tls_disabled("src/programme/x.py", source) == []
