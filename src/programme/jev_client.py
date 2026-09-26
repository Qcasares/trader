"""
jev_client.py
-------------
The one place that talks to TypeSafe AI's Jev, and the only module in the
repository that imports ``typesafe_sdk``. Runner-only: nothing in ``src/api``,
``src/worker`` or the decision path may import it, and
``tests/unit/test_import_boundaries.py`` keeps it that way.

The SDK is imported lazily, inside :func:`ask`, exactly as ``client.py``
imports ``anthropic``: this module imports, and its refusals can be tested,
where ``typesafe_sdk`` is not installed, which is everywhere but the
programme's own image.

The SDK is authentic (docs/08-jev-integration.md, fact 2), and several of its
defaults are wrong for a system that records every answer and trades on some
of them. Each is overridden here rather than trusted:

* **The host is passed, never resolved.** The SDK reads ``TYPESAFE_BASE_URL``
  with no host check, so one environment variable would send the key and every
  state anywhere. ``jev_catalogue.JEV_BASE_URL`` is passed on every
  construction and the variable is never consulted.
* **The model is passed, never defaulted.** The SDK falls back to
  ``TYPESAFE_DEFAULT_MODEL``, then to the alias ``jev-latest``. An alias is
  refused here before the SDK is touched, and the pin is passed both to the
  client and to the call.
* **Nothing reaches a log.** At DEBUG the SDK logs whole request and response
  bodies, and it reads ``TYPESAFE_LOG_LEVEL`` once, at import. The variable is
  set to ``off`` before that import, and the ``typesafe_sdk`` logger is then
  forced above CRITICAL and given a filter that drops every record, on every
  call, so a logging configuration applied later cannot turn it back on.
* **Nothing is merged into the request.** ``extra_body`` is merged last and
  shallowly, so it can replace the state, the model or the questions that were
  hashed and recorded. ``extra_headers`` and ``response_model`` are no safer.
  None of the three is named here, and ``tests/unit/test_jev_client_offline.py``
  keeps it so.
* **One retry, a bounded budget, and no deference to ``Retry-After``.** The
  default policy makes three attempts at a POST with no idempotency key, and
  whether a retried call is billed is undocumented; it also honours
  ``Retry-After`` with no cap, so a server could hold a pass for as long as it
  liked. Here: one retry — for 429, the transient 5xx statuses, a connection
  that failed and an attempt that timed out — inside a 20 s budget, with each
  attempt timed out at 10 s. A call is billed at most twice.

What comes back is evidence for the ledger, and it is taken from the wire
rather than from the SDK's parse of it. The SDK resolves a name given twice by
keeping the last, reads ``NaN`` as a number, and hands its errors a body it has
already parsed, so a JSON error body would reach the ledger re-serialised and a
malformed 200 would reach the validator as something it never was. The HTTP
client is therefore built here, with a hook that keeps the final attempt's
response exactly as it arrived, and :class:`JevCall` carries that: the status,
the body and the request-id header of the response the outcome rests on, or
none of the three when the final attempt got no response at all.

:func:`ask` never raises for anything the vendor or the network does. A call
that was made has to be recorded whatever came back, and a lane that received
an exception instead would have no row to write for a request that may have
been billed. It raises only where nothing was sent: for a caller's mistake it
can see first — an alias or an unknown model, or a key that is not text — and
where the SDK is not installed. Cancellation is never swallowed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import ModuleType
from typing import TYPE_CHECKING, Any

from src.programme import jev_catalogue
from src.programme.jev_validate import MAX_TOKEN_COUNT

if TYPE_CHECKING:
    import httpx2

logger = logging.getLogger(__name__)

__all__ = [
    "ERROR_KINDS",
    "MAX_RETRIES",
    "REQUEST_ID_HEADER",
    "REQUEST_TIMEOUT_SECONDS",
    "RETRY_BUDGET_SECONDS",
    "RETRY_STATUSES",
    "JevCall",
    "JevModels",
    "RateLimiter",
    "ask",
    "list_models",
]

# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

#: Retries after the first attempt. One: a transient failure gets a second
#: chance, and a call is never billed more than twice.
MAX_RETRIES = 1

#: Everything one :func:`ask` may spend, retries and backoff included. The SDK
#: will not start a retry whose delay would reach it.
RETRY_BUDGET_SECONDS = 20.0

#: Each attempt's timeout, for connecting, writing, reading and waiting for a
#: pooled connection alike.
REQUEST_TIMEOUT_SECONDS = 10.0

#: The statuses worth a second attempt: rate limiting and the transient server
#: errors, 529 ("overloaded") among them. Not 408, which the SDK retries by
#: default, and not the rest of the 5xx range: a 501 will say the same thing
#: again.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504, 529})

#: Where the vendor puts its request id. Read from the headers directly: the
#: SDK's ``response.request_id`` raises when the header is absent.
REQUEST_ID_HEADER = "x-typesafe-request-id"

#: How a failed call is classed, so a lane can act on the class without
#: parsing anything. ``auth``: the key was refused (401, or a 403 with a JSON
#: body, which is what the live API sends for a missing key). ``content_block``:
#: a 403 whose body is not JSON, possibly a block on the content of the state
#: rather than on the key. ``invalid_request``: the request failed the vendor's
#: validation (422). ``rate_limited``: 429. ``server``: any 5xx, 529 included.
#: ``timeout`` and ``connection``: no response at all. ``response_shape``: a 2xx
#: the SDK could not read. ``client``: everything else — any other status, a
#: key refused before sending, or a failure on this side of the wire.
ERROR_KINDS: tuple[str, ...] = (
    "auth",
    "content_block",
    "invalid_request",
    "rate_limited",
    "server",
    "timeout",
    "connection",
    "response_shape",
    "client",
)

#: The SDK's logger, and the level it is held at: above CRITICAL, which the SDK
#: itself calls ``off``.
_SDK_LOGGER = "typesafe_sdk"
_SILENCED = logging.CRITICAL + 1


# ---------------------------------------------------------------------------
# The outcome of one call
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class JevCall:
    """
    What one call to Jev produced, in the shape the ledger records it.

    ``http_status``, ``raw_body`` and ``request_id`` all describe the response
    the outcome rests on — the final attempt's — and are all ``None`` when that
    attempt got no response. ``request_id`` is also ``None`` when a response
    came back without the header, and ``http_status`` is what tells the two
    apart.

    ``raw_body`` is the body as it arrived, read as UTF-8 whatever the response
    declared, because JSON is UTF-8 (RFC 8259) and because the validator is
    handed exactly this text. Where the bytes are not text Postgres can store —
    a byte that is not UTF-8, or a NUL — the byte becomes U+FFFD, which marks
    where. An empty body is ``""``: a response that said nothing, which is not
    the same as no response.

    ``latency_ms`` runs from the moment the first attempt was sent to the moment
    the call finished, retry and backoff included, and is ``None`` when nothing
    was ever sent. Zero would report an instant answer from a vendor that was
    never asked.

    ``error_class`` is the exception's class name and ``error_kind`` one of
    :data:`ERROR_KINDS`; both are ``None`` for a call that succeeded. Neither
    holds exception text, which is not evidence and has, in SDK releases before
    0.7.1, carried the key.

    The token counts are the vendor's, and ``None`` unless the SDK read a
    successful response and each is a count the ledger's INT columns hold.
    """

    http_status: int | None
    raw_body: str | None
    request_id: str | None
    latency_ms: int | None
    error_class: str | None
    error_kind: str | None
    input_tokens: int | None
    output_tokens: int | None


@dataclass(frozen=True, slots=True)
class JevModels:
    """
    What asking the vendor which models a key may use produced.

    ``names`` is the model names the vendor listed, in its order, and ``None``
    unless the call succeeded: an empty tuple is a key that may use nothing,
    which is not the same as not knowing. The other fields describe the
    response exactly as :class:`JevCall`'s do, and for the same reasons.
    """

    http_status: int | None
    names: tuple[str, ...] | None
    request_id: str | None
    error_class: str | None
    error_kind: str | None


# ---------------------------------------------------------------------------
# The client-side rate limiter
# ---------------------------------------------------------------------------


class RateLimiter:
    """
    A sliding-window limit on requests a minute and estimated tokens a second.

    The vendor's limits are 1,200 requests a minute and 250,000 tokens a second,
    and "can change without notice"; the catalogue's ceilings sit beneath both,
    so a burst this lets through is not one the vendor answers with a 429 —
    which this client, not deferring to ``Retry-After``, would retry too soon.

    Every request that leaves the process is admitted here first, a retry
    included, because the vendor counts requests rather than calls. Admission
    is checked and recorded with no ``await`` between the two, so concurrent
    callers on one event loop cannot both take the last place. It holds no
    asyncio primitive, so it is not bound to the loop it was first used on.

    A request estimated at more than a whole second's allowance waits for the
    token window to empty and then goes alone. The catalogue's size limits
    make that impossible for anything the lanes send; the rule is here so that
    such a request is late rather than stuck forever.
    """

    REQUEST_WINDOW_SECONDS = 60.0
    TOKEN_WINDOW_SECONDS = 1.0

    def __init__(
        self,
        *,
        requests_per_minute: int,
        tokens_per_second: int,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
    ) -> None:
        if requests_per_minute < 1 or tokens_per_second < 1:
            raise ValueError("a rate limit must admit something")
        self._max_requests = requests_per_minute
        self._max_tokens = tokens_per_second
        self._clock = clock
        self._sleep = sleep
        self._requests: deque[float] = deque()
        self._tokens: deque[tuple[float, int]] = deque()
        self._spent = 0

    async def acquire(self, tokens: int) -> None:
        """Wait until one more request of ``tokens`` fits both windows, then take it."""
        charge = min(max(tokens, 0), self._max_tokens)
        while True:
            now = self._clock()
            delay = self._delay(now, charge)
            if delay <= 0:
                self._requests.append(now)
                self._tokens.append((now, charge))
                self._spent += charge
                return
            await self._sleep(delay)

    def _delay(self, now: float, charge: int) -> float:
        """How long until a request of ``charge`` tokens fits, or 0 if it does."""
        while self._requests and now - self._requests[0] >= self.REQUEST_WINDOW_SECONDS:
            self._requests.popleft()
        while self._tokens and now - self._tokens[0][0] >= self.TOKEN_WINDOW_SECONDS:
            self._spent -= self._tokens.popleft()[1]

        delay = 0.0
        surplus = len(self._requests) - self._max_requests + 1
        if surplus > 0:
            # The oldest `surplus` admissions have to leave the minute first.
            leaving = self._requests[surplus - 1]
            delay = leaving + self.REQUEST_WINDOW_SECONDS - now
        excess = self._spent + charge - self._max_tokens
        if excess > 0:
            freed = 0
            for at, spent in self._tokens:
                freed += spent
                if freed >= excess:
                    delay = max(delay, at + self.TOKEN_WINDOW_SECONDS - now)
                    break
        return delay


#: One limiter for the process: the vendor's limits are per key, and the
#: programme holds one key.
_LIMITER = RateLimiter(
    requests_per_minute=jev_catalogue.CLIENT_REQUESTS_PER_MINUTE,
    tokens_per_second=jev_catalogue.CLIENT_TOKENS_PER_SECOND,
)


# ---------------------------------------------------------------------------
# The call
# ---------------------------------------------------------------------------


async def ask(
    *,
    api_key: str,
    model: str,
    state: Any,
    questions: Mapping[str, Mapping[str, Any]],
    transport: httpx2.AsyncBaseTransport | None = None,
) -> JevCall:
    """
    Put ``questions`` about ``state`` to ``model``, once, and return what happened.

    ``state`` and ``questions`` are sent as given, in the order given: the lane
    has already hashed them, and the request that leaves must be the request
    that was hashed.

    ``transport`` is a test seam and nothing else. Production code never passes
    one, and ``tests/unit/test_jev_client_offline.py`` reads ``src/`` to prove
    it: with no transport the HTTP client builds its own, honouring the
    environment's proxy settings as the SDK would.

    Raises ``ValueError`` for a model the catalogue refuses and ``TypeError``
    for a key that is not text, both before the SDK is imported. A key that is
    text but empty or malformed is refused by the SDK, before anything is sent,
    and comes back as a ``client`` error: the SDK is never left to find a key of
    its own in ``TYPESAFE_API_KEY``, because it is always handed one.
    """
    problem = jev_catalogue.model_problem(model)
    if problem is not None:
        raise ValueError(problem)
    if not isinstance(api_key, str):
        raise TypeError(f"the TypeSafe key must be text, got {type(api_key).__name__}")

    sdk, httpx2_module = _load_sdk()
    wire = _Wire()
    http: Any = None
    client: Any = None
    result: Any = None
    failure: Exception | None = None
    try:
        http = httpx2_module.AsyncClient(
            timeout=REQUEST_TIMEOUT_SECONDS,
            transport=transport,
            follow_redirects=False,
            event_hooks={"request": [wire.sending], "response": [wire.received]},
        )
        client = sdk.AsyncTypeSafeClient(
            api_key=api_key,
            base_url=jev_catalogue.JEV_BASE_URL,
            model=model,
            retry=_retry_policy(sdk),
            timeout=REQUEST_TIMEOUT_SECONDS,
            http_client=http,
        )
        result = await client.system_one(state, questions, model=model)
    except Exception as error:  # noqa: BLE001 - every failure is evidence, see above
        failure = error
    finally:
        finished = time.monotonic()
        # Closed on every path, cancellation included. The SDK client closes
        # the HTTP client it was given; before it exists, that is done here.
        await _close(client if client is not None else http)

    latency_ms = _elapsed_ms(wire.started, finished)
    if failure is None:
        try:
            return _answered(result, latency_ms)
        except Exception as error:  # noqa: BLE001 - a defect here is not the vendor's
            # The vendor answered and the answer could not be read out of the
            # SDK's result. It is recorded from the wire like any failure, so
            # the body that was billed for still reaches the ledger.
            failure = error
    return _failed(sdk, failure, wire.response, latency_ms)


async def list_models(
    *,
    api_key: str,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> JevModels:
    """
    Ask the vendor which models ``api_key`` may use, once.

    The check that settles whether a key is TypeSafe's and whether the pin is
    offered to it, before a single question is asked with it. It spends no
    tokens. Built exactly as :func:`ask` builds its client — the host passed,
    the pin passed, the logger silenced, one retry, no redirects — because a
    key is as exposed by a listing as by a question.

    Raises ``TypeError`` for a key that is not text, before the SDK is
    imported, and nothing for anything the vendor or the network does.
    ``transport`` is a test seam, as it is for :func:`ask`.
    """
    if not isinstance(api_key, str):
        raise TypeError(f"the TypeSafe key must be text, got {type(api_key).__name__}")

    sdk, httpx2_module = _load_sdk()
    wire = _Wire()
    http: Any = None
    client: Any = None
    result: Any = None
    failure: Exception | None = None
    try:
        http = httpx2_module.AsyncClient(
            timeout=REQUEST_TIMEOUT_SECONDS,
            transport=transport,
            follow_redirects=False,
            event_hooks={"request": [wire.sending], "response": [wire.received]},
        )
        client = sdk.AsyncTypeSafeClient(
            api_key=api_key,
            base_url=jev_catalogue.JEV_BASE_URL,
            # Passed so the SDK never reads TYPESAFE_DEFAULT_MODEL, even for a
            # call that sends no model.
            model=jev_catalogue.DEFAULT_MODEL,
            retry=_retry_policy(sdk),
            timeout=REQUEST_TIMEOUT_SECONDS,
            http_client=http,
        )
        result = await client.models.list()
    except Exception as error:  # noqa: BLE001 - every failure is evidence
        failure = error
    finally:
        await _close(client if client is not None else http)

    if failure is None:
        try:
            response = result.raw_http_response
            return JevModels(
                http_status=response.status_code,
                names=tuple(str(model.name) for model in result.models),
                request_id=_request_id(response),
                error_class=None,
                error_kind=None,
            )
        except Exception as error:  # noqa: BLE001 - a defect here is not the vendor's
            failure = error
    response = wire.response
    raw_body = None if response is None else _storable(response.content)
    kind = _kind(sdk, failure, raw_body)
    logger.warning(
        "Jev model listing failed: %s (%s, HTTP %s)",
        kind,
        type(failure).__name__,
        None if response is None else response.status_code,
    )
    return JevModels(
        http_status=None if response is None else response.status_code,
        names=None,
        request_id=_request_id(response),
        error_class=type(failure).__name__,
        error_kind=kind,
    )


def _answered(result: Any, latency_ms: int | None) -> JevCall:
    """The call for a response the SDK read."""
    response = result.raw_http_response
    return JevCall(
        http_status=response.status_code,
        raw_body=_storable(response.content),
        request_id=_request_id(response),
        latency_ms=latency_ms,
        error_class=None,
        error_kind=None,
        input_tokens=_count(result.usage.input_tokens),
        output_tokens=_count(result.usage.output_tokens),
    )


def _failed(
    sdk: ModuleType, failure: Exception, response: Any, latency_ms: int | None
) -> JevCall:
    """The call for a failure, with the final attempt's response if it got one."""
    raw_body = None if response is None else _storable(response.content)
    kind = _kind(sdk, failure, raw_body)
    status = None if response is None else response.status_code
    if kind == "client" and not isinstance(failure, sdk.TypeSafeError):
        # Not the vendor and not the network: a defect on this side. Logged by
        # class alone, like every failure here, since exception text can carry
        # what was sent.
        logger.error("Jev call failed on this side: %s", type(failure).__name__)
    else:
        logger.warning(
            "Jev call failed: %s (%s, HTTP %s)", kind, type(failure).__name__, status
        )
    return JevCall(
        http_status=status,
        raw_body=raw_body,
        request_id=_request_id(response),
        latency_ms=latency_ms,
        error_class=type(failure).__name__,
        error_kind=kind,
        input_tokens=None,
        output_tokens=None,
    )


def _kind(sdk: ModuleType, failure: Exception, raw_body: str | None) -> str:
    """Which of :data:`ERROR_KINDS` ``failure`` is. The order matters: see below."""
    # A subclass of TypeSafeAPIError, so it is tested before the status classes.
    if isinstance(failure, sdk.TypeSafeAPIResponseValidationError):
        return "response_shape"
    if isinstance(failure, sdk.TypeSafeAuthenticationError):
        return "auth"
    if isinstance(failure, sdk.TypeSafePermissionDeniedError):
        # The live API answers a missing key with a JSON 403, not the documented
        # 401. A 403 that is not JSON did not come from that code path, and a
        # block on the content is the precaution docs/08 takes for it. Decided
        # from the stored body, so the row itself shows why.
        return "auth" if _is_json(raw_body) else "content_block"
    if isinstance(failure, sdk.TypeSafeUnprocessableEntityError):
        return "invalid_request"
    if isinstance(failure, sdk.TypeSafeRateLimitError):
        return "rate_limited"
    if isinstance(failure, sdk.TypeSafeInternalServerError):
        return "server"
    # A subclass of TypeSafeAPIConnectionError, so it is tested first.
    if isinstance(failure, sdk.TypeSafeAPITimeoutError):
        return "timeout"
    if isinstance(failure, sdk.TypeSafeAPIConnectionError):
        return "connection"
    return "client"


# ---------------------------------------------------------------------------
# The wire
# ---------------------------------------------------------------------------


class _Wire:
    """
    What one call put on the wire and got back, kept by the HTTP client's hooks.

    ``response`` is the current attempt's response, cleared as each attempt is
    sent, so after the call it is the final attempt's — or ``None`` when that
    attempt got none, even if an earlier attempt did. The evidence recorded
    for a call is the response its outcome rests on, never a stale one.
    """

    def __init__(self) -> None:
        self.started: float | None = None
        self.response: Any = None

    async def sending(self, request: Any) -> None:
        # Estimated from the bytes actually sent. A body that is not UTF-8
        # cannot come from the SDK's encoder; if one did, replacement only
        # raises the estimate, which is the safe direction.
        tokens = jev_catalogue.estimate_tokens(
            request.content.decode("utf-8", "replace")
        )
        await _LIMITER.acquire(tokens)
        self.response = None
        if self.started is None:
            self.started = time.monotonic()

    async def received(self, response: Any) -> None:
        # Read here, so the bytes kept are the bytes the SDK then parses.
        await response.aread()
        self.response = response


def _load_sdk() -> tuple[ModuleType, ModuleType]:
    """
    ``typesafe_sdk`` and ``httpx2``, with the SDK's logging off.

    ``TYPESAFE_LOG_LEVEL`` is set before the import, because the SDK applies it
    once, at import. The logger is then silenced on every call regardless,
    because the variable does nothing if something imported the SDK first, and
    a level does nothing against a logging configuration applied later.
    """
    os.environ["TYPESAFE_LOG_LEVEL"] = "off"
    try:
        import httpx2
        import typesafe_sdk
    except ImportError as error:
        raise ImportError(
            "typesafe_sdk is not installed in this process. Only the programme's "
            "image installs it, from requirements-programme.lock, and no other "
            "process may."
        ) from error
    sdk_logger = logging.getLogger(_SDK_LOGGER)
    sdk_logger.setLevel(_SILENCED)
    sdk_logger.addFilter(_drop_every_record)
    return typesafe_sdk, httpx2


def _drop_every_record(record: logging.LogRecord) -> bool:
    """
    A filter that refuses everything the SDK logs.

    A logger's own filters run before any handler, including the handlers of
    the loggers it propagates to, so this holds against a level set later, a
    handler added later, or a root logger at DEBUG. Adding it twice is a no-op.
    """
    return False


def _retry_policy(sdk: ModuleType) -> Any:
    """The retry policy described in the module docstring, built from the SDK."""
    return sdk.RetryPolicy(
        max_retries=MAX_RETRIES,
        timeout=RETRY_BUDGET_SECONDS,
        respect_retry_after=False,
        http_statuses=set(RETRY_STATUSES),
    )


async def _close(resource: Any) -> None:
    """
    Close the client, never losing the call's outcome to the close.

    A failure to close is logged by class and dropped: the call has already
    happened, and what it produced is what has to reach the ledger.
    """
    if resource is None:
        return
    try:
        await resource.aclose()
    except Exception as error:  # noqa: BLE001 - see the docstring
        logger.warning("closing the Jev HTTP client failed: %s", type(error).__name__)


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------


def _storable(content: bytes) -> str:
    """
    A body as text Postgres can store: UTF-8, with every undecodable byte and
    every NUL replaced by U+FFFD. Verbatim for anything else.
    """
    return content.decode("utf-8", "replace").replace("\x00", "\ufffd")


def _is_json(text: str | None) -> bool:
    """Whether ``text`` is a JSON document. An empty or absent body is not."""
    if text is None:
        return False
    try:
        json.loads(text)
    except (ValueError, RecursionError):
        return False
    return True


def _request_id(response: Any) -> str | None:
    """The vendor's request id, or ``None`` for no response or no usable header."""
    if response is None:
        return None
    value = response.headers.get(REQUEST_ID_HEADER)
    if value is None or not value.strip():
        return None
    return value


def _count(value: object) -> int | None:
    """
    A token count the ledger's INT columns can hold, or ``None``.

    The SDK reads the counts as integers and checks nothing else, so a negative
    count, or one past the column, reaches here. Neither is a count anybody was
    billed for, and writing one would fail the insert that records the call.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= MAX_TOKEN_COUNT else None


def _elapsed_ms(started: float | None, finished: float) -> int | None:
    """Milliseconds since the first attempt was sent, or ``None`` if none was."""
    if started is None:
        return None
    return max(0, round((finished - started) * 1000))
