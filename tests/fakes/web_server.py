"""
web_server.py
-------------
A local HTTPS server with a certificate authority of its own, a plain listener
that counts whatever reaches it, and a resolver that routes a name to either.

Exists so ``src/programme/web_fetch.py`` is tested over real TLS and real HTTP
— a real handshake, real framing, real gzip — rather than against a mocked
``aiohttp``, which would only prove the mock matches an assumption about
aiohttp, the thing most worth testing. The server writes its responses byte by
byte, so a test can send what no well-behaved framework would: a length it
never honours, a body that drips, a gzip stream that never ends, a status line
that is not one, or nothing at all.

Nothing here reaches the network: the servers listen on 127.0.0.1, every
name is routed where a test says, and a name no route names fails to resolve.
A route to any other address is one the fetcher's address check must refuse
before a connection is made.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
import ssl
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aiohttp.abc import AbstractResolver, ResolveResult
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

LOOPBACK = "127.0.0.1"


# ---------------------------------------------------------------------------
# A certificate authority for one test module
# ---------------------------------------------------------------------------


def _key_usage(*, ca: bool) -> x509.KeyUsage:
    return x509.KeyUsage(
        digital_signature=True,
        content_commitment=False,
        key_encipherment=False,
        data_encipherment=False,
        key_agreement=False,
        key_cert_sign=ca,
        crl_sign=ca,
        encipher_only=False,
        decipher_only=False,
    )


class Authority:
    """
    A certificate authority nobody else trusts, and the certificates it signs.

    :meth:`client_context` trusts it and nothing else, and verifies as a
    default context does; :meth:`server_context` presents a certificate for
    the names given. A client using the system's trust store refuses every
    certificate this signs, which is what a test of verification needs.
    """

    def __init__(self) -> None:
        self._directory = tempfile.TemporaryDirectory(prefix="web-fetch-ca-")
        self._key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, "trader test authority")]
        )
        now = datetime.now(UTC)
        self._name = name
        self._certificate = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(self._key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=2))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
            .add_extension(_key_usage(ca=True), critical=True)
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(self._key.public_key()),
                critical=False,
            )
            .sign(self._key, hashes.SHA256())
        )
        self.pem = self._certificate.public_bytes(serialization.Encoding.PEM)

    def close(self) -> None:
        self._directory.cleanup()

    def client_context(self) -> ssl.SSLContext:
        """A verifying client context that trusts this authority alone."""
        return ssl.create_default_context(cadata=self.pem.decode("ascii"))

    def server_context(self, *hostnames: str) -> ssl.SSLContext:
        """A server context presenting a certificate this authority signed."""
        key = ec.generate_private_key(ec.SECP256R1())
        now = datetime.now(UTC)
        certificate = (
            x509.CertificateBuilder()
            .subject_name(
                x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostnames[0])])
            )
            .issuer_name(self._name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=2))
            .add_extension(
                x509.SubjectAlternativeName([x509.DNSName(h) for h in hostnames]),
                critical=False,
            )
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
            .add_extension(_key_usage(ca=False), critical=True)
            .add_extension(
                x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
                critical=False,
            )
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(
                    self._key.public_key()
                ),
                critical=False,
            )
            .sign(self._key, hashes.SHA256())
        )
        directory = Path(self._directory.name)
        stem = f"{hostnames[0]}-{certificate.serial_number}"
        certificate_file = directory / f"{stem}.crt"
        key_file = directory / f"{stem}.key"
        certificate_file.write_bytes(
            certificate.public_bytes(serialization.Encoding.PEM)
        )
        key_file.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certificate_file, key_file)
        return context


# ---------------------------------------------------------------------------
# What the server sends
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Reply:
    """
    One scripted response, written exactly as described.

    ``framing`` is how the body's end is told: ``"length"`` (a
    ``Content-Length``, ``declared_length`` if given, else the body's real
    length), ``"chunked"``, or ``"close"`` (neither: the body ends when the
    connection does). ``chunk`` bytes are written at a time with ``delay``
    seconds between them, which is a drip when it is slow. ``raw`` replaces
    the whole response with the bytes given. ``drop`` closes the connection
    without a word once the request has arrived; ``stall`` answers nothing and
    holds the connection open.
    """

    status: int = 200
    reason: str = "OK"
    headers: Sequence[tuple[str, str]] = (
        ("Content-Type", "text/plain; charset=utf-8"),
    )
    body: bytes = b""
    framing: str = "length"
    declared_length: int | None = None
    chunk: int = 16 * 1024
    delay: float = 0.0
    raw: bytes | None = None
    drop: bool = False
    stall: bool = False

    async def send(self, writer: asyncio.StreamWriter) -> None:
        if self.drop:
            return
        if self.stall:
            await asyncio.Event().wait()
        if self.raw is not None:
            writer.write(self.raw)
            await writer.drain()
            return
        lines = [f"HTTP/1.1 {self.status} {self.reason}"]
        lines += [f"{name}: {value}" for name, value in self.headers]
        if self.framing == "length":
            length = (
                len(self.body) if self.declared_length is None else self.declared_length
            )
            lines.append(f"Content-Length: {length}")
        elif self.framing == "chunked":
            lines.append("Transfer-Encoding: chunked")
        lines.append("Connection: close")
        writer.write(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))
        await writer.drain()
        for start in range(0, len(self.body), self.chunk):
            piece = self.body[start : start + self.chunk]
            if self.framing == "chunked":
                piece = f"{len(piece):x}\r\n".encode() + piece + b"\r\n"
            writer.write(piece)
            await writer.drain()
            if self.delay:
                await asyncio.sleep(self.delay)
        if self.framing == "chunked":
            writer.write(b"0\r\n\r\n")
            await writer.drain()


@dataclass(frozen=True)
class Request:
    """A request as it arrived: its line and its headers, in order."""

    method: str
    target: str
    version: str
    headers: tuple[tuple[str, str], ...]

    def header_names(self) -> set[str]:
        return {name.lower() for name, _ in self.headers}

    def header(self, name: str) -> str | None:
        wanted = name.lower()
        return next((v for n, v in self.headers if n.lower() == wanted), None)


def _parse(head: bytes) -> Request:
    text = head.decode("latin-1").rstrip("\r\n")
    line, *rest = text.split("\r\n")
    method, target, version = line.split(" ", 2)
    headers = tuple(
        (name.strip(), value.strip())
        for name, _, value in (h.partition(":") for h in rest if h)
    )
    return Request(method=method, target=target, version=version, headers=headers)


# ---------------------------------------------------------------------------
# The HTTPS server, and a listener that only counts
# ---------------------------------------------------------------------------


@dataclass
class FakeHTTPS:
    """
    A local HTTPS server answering every request with ``reply``, or with what
    ``reply(request)`` returns. ``connections`` counts the connections that
    completed a handshake; ``requests`` holds every request that arrived.
    """

    context: ssl.SSLContext
    reply: Reply | Callable[[Request], Reply] = field(default_factory=Reply)
    connections: int = 0
    requests: list[Request] = field(default_factory=list)
    port: int = 0
    _server: asyncio.Server | None = None
    _handlers: set[asyncio.Task[Any]] = field(default_factory=set)
    arrived: asyncio.Event = field(default_factory=asyncio.Event)

    async def __aenter__(self) -> FakeHTTPS:
        self._server = await asyncio.start_server(
            self._serve, LOOPBACK, 0, ssl=self.context
        )
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *_: object) -> None:
        assert self._server is not None
        self._server.close()
        for task in list(self._handlers):
            task.cancel()
        for task in list(self._handlers):
            with contextlib.suppress(BaseException):
                await task
        with contextlib.suppress(Exception):
            await self._server.wait_closed()

    async def _serve(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        task = asyncio.current_task()
        assert task is not None
        self._handlers.add(task)
        self.connections += 1
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            request = _parse(head)
            self.requests.append(request)
            self.arrived.set()
            reply = self.reply(request) if callable(self.reply) else self.reply
            await reply.send(writer)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, OSError):
            pass
        finally:
            self._handlers.discard(task)
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()


@dataclass
class Listener:
    """
    A plain TCP listener that counts every connection made to it, records what
    each sends, and closes it. Where a test points something that must never
    be reached: a proxy, a redirect's target, a refused address.
    """

    connections: int = 0
    received: bytearray = field(default_factory=bytearray)
    port: int = 0
    _server: asyncio.Server | None = None

    async def __aenter__(self) -> Listener:
        self._server = await asyncio.start_server(self._serve, LOOPBACK, 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *_: object) -> None:
        assert self._server is not None
        self._server.close()
        with contextlib.suppress(Exception):
            await self._server.wait_closed()

    async def _serve(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.connections += 1
        with contextlib.suppress(Exception):
            self.received += await asyncio.wait_for(reader.read(4096), 0.5)
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


# ---------------------------------------------------------------------------
# Names, routed
# ---------------------------------------------------------------------------


class RoutingResolver(AbstractResolver):
    """
    Answers each name with the address and port its route gives, and fails to
    resolve any other name, so a test can send the fetcher's fixed host to a
    local server on an ephemeral port. ``asked`` records every name looked up.
    """

    def __init__(self, routes: Mapping[str, tuple[str, int]]) -> None:
        self.routes = dict(routes)
        self.asked: list[str] = []

    async def resolve(
        self, host: str, port: int = 0, family: socket.AddressFamily = socket.AF_INET
    ) -> list[ResolveResult]:
        self.asked.append(host)
        if host not in self.routes:
            raise OSError(f"no route for {host}")
        address, routed = self.routes[host]
        return [
            {
                "hostname": host,
                "host": address,
                "port": routed,
                "family": socket.AF_INET6 if ":" in address else socket.AF_INET,
                "proto": 0,
                "flags": socket.AI_NUMERICHOST,
            }
        ]

    async def close(self) -> None:
        return None
