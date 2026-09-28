"""
web_fetch.py
------------
The programme's one road to the web: fetch one allow-listed page, once, and
return its text or the reason it could not. Runner-only — nothing in
``src/api``, ``src/worker`` or the decision path may import it
(``RUNNER_ONLY`` in ``tests/unit/test_import_boundaries.py``) — and the only
module in ``src/programme`` that imports ``aiohttp``. One module imports it,
the ingest job, ``web_ingest``, which stores what the page holds and calls
nothing, and no other takes it from there, by name, attribute or lookup
(``test_import_boundaries.py::test_only_the_ingest_job_imports_the_web_fetcher``).

It fetches exactly the allow-list and follows nothing. Each control is here
rather than trusted to a default, and each is held by a test in
``tests/unit/test_web_fetch.py`` that fails when the control is removed:

========================  ===================================================
Control                   Rule
========================  ===================================================
Input                     :func:`fetch` takes a member of
                          ``web_sources.ALLOWED_SOURCES``, by identity and as
                          the module wrote it (``web_sources.as_written``),
                          and raises before a socket opens for anything else —
                          an equal copy, or the entry itself edited in place
                          to any other page, included. It fetches with the
                          values written, never the live entry's. No function
                          takes a URL.
Method, redirects         ``GET``, with ``allow_redirects=False``: any 3xx is
                          ``FetchFailure("redirect")`` and is never followed.
Environment               ``trust_env=False``: no proxy variable and no
                          ``.netrc`` applies, so nothing in the environment can
                          send the request, or a credential, elsewhere.
Addresses                 :class:`GlobalOnlyResolver` refuses the whole answer
                          when any address a name resolves to is not global —
                          loopback, private, link-local (the cloud metadata
                          service among them), multicast, reserved, or an IPv4
                          one of those inside an IPv6 address. aiohttp connects
                          to exactly the addresses the resolver returned, so
                          there is no second lookup to rebind.
TLS                       aiohttp's default: the system's trust store, the
                          host name checked. Nothing in ``src/programme``
                          turns verification off (a scan).
Headers                   Fixed: :data:`REQUEST_HEADERS`, no cookies
                          (``DummyCookieJar``), no credentials.
Size                      A declared length over the source's cap is refused
                          before reading; the body is streamed and counted as
                          it arrives and again once decompressed, and the read
                          stops at the cap. gzip is inflated here, a bounded
                          amount at a time, so a small body that inflates to
                          gigabytes never does.
Type, encoding            One ``Content-Type`` in the source's list, declaring
                          ``charset=utf-8``; the body decoded strictly.
Status                    200 only.
Time                      5 s to connect, 20 s in all, inside the 35 s the
                          programme gives a running job at shutdown; one
                          attempt, aiohttp's own reconnect-and-resend
                          switched off.
Output                    :class:`Fetched` or :class:`FetchFailure`. Never
                          raises for anything the network or the server does;
                          cancellation propagates. Logs the status, the size
                          and the hash, never the body.
Test seam                 ``session_factory``, which production never passes:
                          ``test_web_fetch.py`` reads ``src/`` to prove it, as
                          ``jev_client``'s transport is proved.
========================  ===================================================
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import socket
import ssl
import zlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType

import aiohttp
from aiohttp.abc import AbstractResolver, ResolveResult

from src.programme import web_sources
from src.programme.web_sources import ALLOWED_SOURCES, AllowedSource, WrittenSource

logger = logging.getLogger(__name__)

__all__ = [
    "CONNECT_TIMEOUT_SECONDS",
    "FAILURE_KINDS",
    "READ_CHUNK_BYTES",
    "REQUEST_HEADERS",
    "TOTAL_TIMEOUT_SECONDS",
    "FetchFailure",
    "Fetched",
    "GlobalOnlyResolver",
    "NonGlobalAddressError",
    "SessionFactory",
    "address_permitted",
    "fetch",
]

# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

#: Seconds to establish a connection, TLS included.
CONNECT_TIMEOUT_SECONDS = 5.0

#: Seconds for everything, reading the body included. Under the programme's
#: 35 s shutdown grace (``main.JEV_SHUTDOWN_GRACE_SECONDS``), so a fetch in
#: flight at shutdown finishes, one way or the other, before the process goes.
TOTAL_TIMEOUT_SECONDS = 20.0

#: Every header the request carries, beside the ``Host`` the URL implies. gzip
#: is accepted because it is inflated here, under the cap; nothing else is, so
#: a server that sends another coding is refused rather than trusted.
REQUEST_HEADERS: Mapping[str, str] = MappingProxyType(
    {
        "User-Agent": "trader-research/1",
        "Accept": "text/plain",
        "Accept-Encoding": "gzip",
    }
)

#: How much of the body is read from the socket at a time.
READ_CHUNK_BYTES = 64 * 1024

#: Why a fetch failed. ``redirect``: a 3xx, never followed. ``status``: any
#: other status but 200. ``content_encoding``: a coding other than gzip or none.
#: ``content_type``: not exactly one declared type the source allows, with its
#: charset. ``too_large``: over the source's cap, declared, received or
#: inflated. ``not_utf8``: a body that is not strict UTF-8. ``timeout``,
#: ``tls``, ``address`` (a name resolved to an address this fetcher will not
#: connect to) and ``connection``: no usable response. ``protocol``: a response
#: that broke HTTP or gzip. ``client``: a failure on this side, a defect,
#: logged at ERROR.
FAILURE_KINDS: tuple[str, ...] = (
    "redirect",
    "status",
    "content_encoding",
    "content_type",
    "too_large",
    "not_utf8",
    "timeout",
    "tls",
    "address",
    "connection",
    "protocol",
    "client",
)

#: IPv6's well-known NAT64 prefix, whose low 32 bits are an IPv4 address that
#: a translator would connect to.
_NAT64 = ipaddress.IPv6Network("64:ff9b::/96")


# ---------------------------------------------------------------------------
# The outcome
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Fetched:
    """
    A page fetched whole: its text, and the sha256 and size in bytes of the
    body it was decoded from, after any gzip was inflated. ``fetched_at`` is
    when the body finished arriving, in UTC. The text is left out of the
    ``repr``, so a fetch that is logged whole logs no web text.
    """

    source: AllowedSource
    text: str = field(repr=False)
    sha256: str
    bytes: int
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class FetchFailure:
    """
    Why a fetch produced no page: ``kind``, one of :data:`FAILURE_KINDS`, and
    the response's status where there was one. Nothing else: no exception
    text and no body, which could carry the page's words into a job's error.
    """

    kind: str
    http_status: int | None = None

    def __post_init__(self) -> None:
        if self.kind not in FAILURE_KINDS:
            raise ValueError(f"{self.kind!r} is not one of FAILURE_KINDS")


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------


class NonGlobalAddressError(OSError):
    """A name resolved to an address this fetcher will not connect to."""


def address_permitted(host: str) -> bool:
    """
    Whether the fetcher may connect to ``host``, an address as a resolver
    returns one.

    Global, by ``ipaddress``, and none of the ranges ``is_global`` lets through
    that no page is served from: multicast, reserved and unspecified. An IPv6
    address that carries an IPv4 one — mapped, 6to4, Teredo, the NAT64 prefix —
    is permitted only if that address is too, since a translator would connect
    to it. That check stands whatever a release's tables say of the prefix,
    and the tables differ: on the Python the programme runs on (3.11.15) they
    read the mapped prefix through to the address it carries, refuse the 6to4
    and Teredo prefixes as private whatever they carry, and call the NAT64
    prefix global but reserved, so ``is_reserved`` refuses it
    (``tests/unit/test_web_fetch.py::TestOnlyGlobalAddressesAreReached``).
    Anything that does not parse as an address is refused.
    """
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return _permitted(address)


def _permitted(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if (
        not address.is_global
        or address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        return False
    if isinstance(address, ipaddress.IPv6Address):
        if address.is_site_local:
            return False
        carried = [address.ipv4_mapped, address.sixtofour]
        if address.teredo is not None:
            carried += list(address.teredo)
        if address in _NAT64:
            carried.append(ipaddress.IPv4Address(int(address) & 0xFFFF_FFFF))
        return all(_permitted(v4) for v4 in carried if v4 is not None)
    return True


class GlobalOnlyResolver(AbstractResolver):
    """
    A resolver that answers only with global addresses, or not at all.

    It asks ``inner`` and refuses the whole answer if any address in it is not
    permitted (:func:`address_permitted`), rather than dropping that address
    and connecting to the rest: a name that resolves to both a public address
    and the metadata service is not one to trust with either. The refusal is
    :class:`NonGlobalAddressError`, which aiohttp reports as a DNS failure and the
    fetcher classes as ``address``.
    """

    def __init__(self, inner: AbstractResolver) -> None:
        self._inner = inner

    async def resolve(
        self, host: str, port: int = 0, family: socket.AddressFamily = socket.AF_INET
    ) -> list[ResolveResult]:
        answers = await self._inner.resolve(host, port, family)
        if not answers:
            raise OSError("the name resolved to no address")
        refused = sum(1 for answer in answers if not address_permitted(answer["host"]))
        if refused:
            raise NonGlobalAddressError(
                f"{refused} of {len(answers)} addresses the name resolved to are "
                "not global"
            )
        return answers

    async def close(self) -> None:
        await self._inner.close()


# ---------------------------------------------------------------------------
# The fetch
# ---------------------------------------------------------------------------

#: What ``session_factory`` is: a function that builds a session. A test seam.
SessionFactory = Callable[[], aiohttp.ClientSession]


async def fetch(
    source: AllowedSource, *, session_factory: SessionFactory | None = None
) -> Fetched | FetchFailure:
    """
    Fetch ``source``, once, and return its text or why not.

    ``source`` must be the very object ``ALLOWED_SOURCES`` holds under its
    name, holding the values ``web_sources`` wrote; anything else — an equal
    copy, a string, a source with the same name and another URL, the entry
    itself edited in place — raises ``ValueError`` before any socket is
    opened, since that is a caller's mistake and not the network's. The fetch
    then uses the values written, which nothing can edit, so what is checked
    is what is fetched.

    Never raises for anything the network or the server does: every such
    outcome is a :class:`FetchFailure`. A defect on this side is one too, as
    ``client``, logged at ERROR by its class alone. ``asyncio.CancelledError``
    propagates.

    ``session_factory`` is a test seam and nothing else: production code never
    passes one (``tests/unit/test_web_fetch.py::TestTheSeam``), and without it
    the session is :func:`_session`'s, called with nothing, with every control
    above.
    """
    written = _require_allowed(source)
    status: int | None = None
    outcome: Fetched | FetchFailure
    try:
        session = _session() if session_factory is None else session_factory()
        async with session:
            async with session.get(written.url, allow_redirects=False) as response:
                status = response.status
                outcome = await _read(source, written, response)
    except Exception as error:  # noqa: BLE001 - every failure is an outcome
        outcome = _failure(source, error, status)
    if isinstance(outcome, Fetched):
        logger.info(
            "fetched %s: HTTP 200, %d bytes, sha256 %s",
            source.name,
            outcome.bytes,
            outcome.sha256,
        )
    elif outcome.kind != "client":
        logger.warning(
            "fetch of %s failed: %s (HTTP %s)",
            source.name,
            outcome.kind,
            outcome.http_status,
        )
    return outcome


def _require_allowed(source: object) -> WrittenSource:
    """
    The values ``web_sources`` wrote for ``source``, or ``ValueError`` unless
    it is an allow-list entry, the entry itself, well formed and unedited.

    Well formed is not enough: an entry edited in place to another https page
    is well formed, and was fetched until the fetcher compared it with what
    was written. ``tests/unit/test_web_fetch.py::TestOnlyTheAllowListIsFetched``.
    """
    if (
        not isinstance(source, AllowedSource)
        or not isinstance(source.name, str)
        or ALLOWED_SOURCES.get(source.name) is not source
    ):
        raise ValueError(
            "web_fetch fetches a member of web_sources.ALLOWED_SOURCES, the "
            "entry itself, and nothing else"
        )
    problem = web_sources.allowed_source_problem(source.name, source)
    if problem is not None:
        raise ValueError(f"the allow-list entry {source.name!r} {problem}")
    written = web_sources.as_written(source)
    if written is None:
        raise ValueError(
            f"the allow-list entry {source.name!r} is not as web_sources wrote "
            "it: it was edited, or replaced, after the module loaded"
        )
    return written


def _session(
    *,
    resolver: AbstractResolver | None = None,
    ssl_context: ssl.SSLContext | None = None,
) -> aiohttp.ClientSession:
    """
    The session a fetch runs in, with every control this module promises.

    Production calls it with nothing. A test may hand it the resolver the
    global-only check wraps, to reach a local server, and a TLS context that
    trusts that server's certificate authority, which still verifies; the
    check itself, the environment, the cookies, the headers and the timeouts
    are this function's in every case. ``tests/unit/test_web_fetch.py`` reads
    ``src/`` to prove nothing but a test passes either.
    """
    inner = resolver if resolver is not None else aiohttp.ThreadedResolver()
    connector = aiohttp.TCPConnector(
        resolver=GlobalOnlyResolver(inner),
        ssl=ssl_context if ssl_context is not None else True,
        use_dns_cache=False,
        force_close=True,
        limit=1,
    )
    session = aiohttp.ClientSession(
        connector=connector,
        headers=dict(REQUEST_HEADERS),
        cookie_jar=aiohttp.DummyCookieJar(),
        trust_env=False,
        auto_decompress=False,
        raise_for_status=False,
        timeout=aiohttp.ClientTimeout(
            total=TOTAL_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS
        ),
    )
    # aiohttp sends an idempotent request a second time, on a new connection,
    # when the first is dropped before a response. One attempt means one: the
    # flag is the one aiohttp's own test client clears, and
    # ``test_web_fetch.py::TestTime::test_a_dropped_connection_is_not_retried``
    # fails if a release renames it.
    session._retry_connection = False
    return session


async def _read(
    source: AllowedSource, written: WrittenSource, response: aiohttp.ClientResponse
) -> Fetched | FetchFailure:
    """Judge the response's head, then read its body under the cap."""
    status = response.status
    if 300 <= status <= 399:
        return FetchFailure("redirect", status)
    if status != 200:
        return FetchFailure("status", status)
    coding = _content_coding(response)
    if coding is None:
        return FetchFailure("content_encoding", status)
    if not _type_allowed(written, response):
        return FetchFailure("content_type", status)
    declared = response.content_length
    if declared is not None and declared > written.max_bytes:
        return FetchFailure("too_large", status)
    body = await _body(response, coding, written.max_bytes)
    if isinstance(body, str):
        return FetchFailure(body, status)
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return FetchFailure("not_utf8", status)
    return Fetched(
        source=source,
        text=text,
        sha256=hashlib.sha256(body).hexdigest(),
        bytes=len(body),
        fetched_at=datetime.now(UTC),
    )


def _content_coding(response: aiohttp.ClientResponse) -> str | None:
    """``"identity"`` or ``"gzip"``, or ``None`` for anything else."""
    codings = [
        token.strip().lower()
        for value in response.headers.getall("Content-Encoding", [])
        for token in value.split(",")
        if token.strip()
    ]
    if not codings or codings == ["identity"]:
        return "identity"
    if codings in (["gzip"], ["x-gzip"]):
        return "gzip"
    return None


def _type_allowed(written: WrittenSource, response: aiohttp.ClientResponse) -> bool:
    """Exactly one ``Content-Type``, a type the source allows, its charset declared."""
    values = response.headers.getall("Content-Type", [])
    if len(values) != 1:
        return False
    media, _, parameters = values[0].partition(";")
    if media.strip().lower() not in written.content_types:
        return False
    charsets = [
        value.strip().strip('"').lower()
        for name, _, value in (p.partition("=") for p in parameters.split(";"))
        if name.strip().lower() == "charset"
    ]
    return charsets == [written.charset]


async def _body(response: aiohttp.ClientResponse, coding: str, cap: int) -> bytes | str:
    """
    The body, inflated if it is gzip, or the kind of failure that stopped it.

    Both what arrives and what it inflates to are counted against ``cap``, and
    reading stops at the first byte over it. The inflater is asked for at most
    one byte more than the cap allows at a time, so a small body that inflates
    without limit never occupies more than that. A gzip stream must end where
    the body ends: cut short, or followed by anything, it is ``protocol``.
    """
    received = 0
    body = bytearray()
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS) if coding == "gzip" else None
    try:
        async for chunk in response.content.iter_chunked(READ_CHUNK_BYTES):
            received += len(chunk)
            if received > cap:
                return "too_large"
            if inflater is None:
                body += chunk
                continue
            if inflater.eof:
                return "protocol"
            pending = chunk
            while pending:
                body += inflater.decompress(pending, cap + 1 - len(body))
                if len(body) > cap:
                    return "too_large"
                if inflater.eof:
                    if inflater.unconsumed_tail or inflater.unused_data:
                        return "protocol"
                    break
                pending = inflater.unconsumed_tail
    except zlib.error:
        return "protocol"
    if inflater is not None and not inflater.eof:
        return "protocol"
    return bytes(body)


def _failure(
    source: AllowedSource, error: Exception, status: int | None
) -> FetchFailure:
    """The failure an exception amounts to, logged by its class alone."""
    kind = _kind(error)
    if kind == "client":
        logger.error(
            "fetch of %s failed on this side: %s", source.name, type(error).__name__
        )
    return FetchFailure(kind, status)


def _kind(error: BaseException) -> str:
    """Class an exception from aiohttp, the socket or TLS into a failure kind."""
    if _caused_by(error, NonGlobalAddressError):
        return "address"
    if isinstance(error, TimeoutError) or _caused_by(error, TimeoutError):
        return "timeout"
    if isinstance(error, aiohttp.ClientSSLError) or _caused_by(error, ssl.SSLError):
        return "tls"
    if isinstance(error, (aiohttp.ClientPayloadError, aiohttp.ClientResponseError)):
        return "protocol"
    if isinstance(error, (aiohttp.ClientConnectionError, OSError)):
        return "connection"
    if isinstance(error, aiohttp.ClientError):
        return "protocol"
    return "client"


def _caused_by(error: BaseException, cls: type[BaseException]) -> bool:
    """Whether ``cls`` is anywhere in ``error``'s chain of causes."""
    seen: set[int] = set()
    pending: list[BaseException | None] = [error]
    while pending:
        current = pending.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, cls):
            return True
        os_error = getattr(current, "os_error", None)
        pending += [
            current.__cause__,
            current.__context__,
            os_error if isinstance(os_error, BaseException) else None,
        ]
    return False
