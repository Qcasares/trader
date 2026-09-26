"""
test_jev_client_offline.py
--------------------------
What can be proved about ``src/programme/jev_client.py`` without the SDK.

The client's behaviour against the real ``typesafe_sdk`` is tested in
``tests/sdk``, which only CI's ``programme sdk`` job can run. This file runs in
the main job, where no model SDK is installed, and holds the client to what
has to be true there and everywhere:

* it imports without the SDK, because it imports the SDK lazily;
* it refuses an alias, an unknown model or a key that is not text before the
  SDK is touched, and sets ``TYPESAFE_LOG_LEVEL`` to ``off`` before the SDK's
  first import, since the SDK reads that variable once, at import;
* its rate limiter admits what its windows allow and no more;
* its request is never rewritten: it names none of ``extra_body``,
  ``extra_headers`` or ``response_model``, the SDK's three routes to sending
  something other than what was hashed;
* nothing in ``src/`` hands it a transport. ``transport`` is a test seam, and a
  production caller that passed one would decide where the state and the key
  go. A lane may forward the seam, as long as what it forwards is its own
  parameter, defaulting to ``None`` — which this file checks through every
  forwarder to the callers at the end of the chain.

The two source scans read spellings, as ``test_import_boundaries.py`` does. They
are not a sandbox: a seam passed through a variable or a partial, or a field
name assembled at run time, is a reviewer's to catch.
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import importlib.abc
import json
import os
import random
import subprocess
import sys
import textwrap
import types
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from src.programme import jev_catalogue, jev_client
from src.programme.jev_client import ERROR_KINDS, JevCall, RateLimiter
from src.programme.jev_validate import MAX_TOKEN_COUNT

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
CLIENT = SRC / "programme" / "jev_client.py"
CLIENT_SOURCE = CLIENT.read_text(encoding="utf-8")

MODEL = jev_catalogue.DEFAULT_MODEL
KEY = "sk-test-5f1c9e0a7b3d4c21"
QUESTIONS = {"q": {"type": "noul", "instructions": "Is it?"}}


# ---------------------------------------------------------------------------
# The contract other modules are written against
# ---------------------------------------------------------------------------


class TestTheContract:
    def test_a_call_carries_the_fields_the_lane_records(self) -> None:
        assert [f.name for f in dataclasses.fields(JevCall)] == [
            "http_status",
            "raw_body",
            "request_id",
            "latency_ms",
            "error_class",
            "error_kind",
            "input_tokens",
            "output_tokens",
        ]

    def test_a_call_cannot_be_edited_after_the_fact(self) -> None:
        call = JevCall(None, None, None, None, "TypeSafeError", "client", None, None)
        with pytest.raises(dataclasses.FrozenInstanceError):
            call.error_kind = "auth"  # type: ignore[misc]

    def test_the_error_kinds_are_the_documented_vocabulary(self) -> None:
        assert set(ERROR_KINDS) == {
            "auth",
            "content_block",
            "invalid_request",
            "rate_limited",
            "server",
            "timeout",
            "connection",
            "response_shape",
            "client",
        }
        assert len(ERROR_KINDS) == len(set(ERROR_KINDS))

    def test_the_retry_policy_is_bounded_as_documented(self) -> None:
        # docs/08, fact 2: one retry, a 20 s budget, 10 s an attempt, and not
        # 408 (which the SDK retries by default) or the rest of the 5xx range.
        assert jev_client.MAX_RETRIES == 1
        assert jev_client.RETRY_BUDGET_SECONDS == 20.0
        assert jev_client.REQUEST_TIMEOUT_SECONDS == 10.0
        assert frozenset({429, 500, 502, 503, 504, 529}) == jev_client.RETRY_STATUSES


# ---------------------------------------------------------------------------
# Importing, refusing, and the SDK's log level
# ---------------------------------------------------------------------------


class _Withhold(importlib.abc.MetaPathFinder):
    """
    Refuses to import ``names``, noting ``TYPESAFE_LOG_LEVEL`` as each is asked for.

    Placed first on ``sys.meta_path``, so it sees an import before any finder
    that could satisfy it.
    """

    def __init__(self, *names: str) -> None:
        self.names = names
        self.asked: list[tuple[str, str | None]] = []

    def find_spec(self, name: str, path: Any = None, target: Any = None) -> None:
        if name.partition(".")[0] in self.names:
            self.asked.append((name, os.environ.get("TYPESAFE_LOG_LEVEL")))
            raise ImportError(f"{name} is withheld by the test")
        return None


@pytest.fixture
def withheld(monkeypatch: pytest.MonkeyPatch) -> _Withhold:
    """The SDK made unimportable, with every attempt to import it noted."""
    finder = _Withhold("typesafe_sdk")
    for name in list(sys.modules):
        if name.partition(".")[0] == "typesafe_sdk":
            monkeypatch.delitem(sys.modules, name)
    # httpx2 is imported first; a stand-in lets the import reach the SDK.
    monkeypatch.setitem(sys.modules, "httpx2", types.ModuleType("httpx2"))
    monkeypatch.setattr(sys, "meta_path", [finder, *sys.meta_path])
    monkeypatch.delenv("TYPESAFE_LOG_LEVEL", raising=False)
    return finder


class TestTheSDKIsImportedLateAndSilenced:
    def test_the_client_imports_where_no_sdk_can(self) -> None:
        # A fresh interpreter, because this one may have imported either.
        script = textwrap.dedent(
            """
            import importlib.abc, json, sys

            asked = []

            class Refuse(importlib.abc.MetaPathFinder):
                def find_spec(self, name, path=None, target=None):
                    if name.partition(".")[0] in ("typesafe_sdk", "httpx2"):
                        asked.append(name)
                        raise ImportError(name)
                    return None

            sys.meta_path.insert(0, Refuse())
            import src.programme.jev_client
            print(json.dumps(asked))
            """
        )
        done = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env={**os.environ, "PYTHONPATH": str(ROOT)},
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert done.returncode == 0, done.stderr
        assert json.loads(done.stdout.strip().splitlines()[-1]) == []

    async def test_the_log_level_is_off_before_the_sdk_is_first_imported(
        self, withheld: _Withhold, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Whatever an operator set: the SDK applies the variable at import.
        monkeypatch.setenv("TYPESAFE_LOG_LEVEL", "debug")

        with pytest.raises(ImportError):
            await jev_client.ask(
                api_key=KEY, model=MODEL, state={}, questions=QUESTIONS
            )

        assert withheld.asked == [("typesafe_sdk", "off")]

    async def test_a_missing_sdk_says_where_the_sdk_belongs(
        self, withheld: _Withhold
    ) -> None:
        with pytest.raises(ImportError, match="requirements-programme.lock") as raised:
            await jev_client.ask(
                api_key=KEY, model=MODEL, state={}, questions=QUESTIONS
            )

        assert isinstance(raised.value.__cause__, ImportError)

    @pytest.mark.parametrize(
        "model",
        [
            *sorted(jev_catalogue.REFUSED_ALIASES),
            "JEV-LATEST",
            " jev-latest ",
            "jev-9.9.9",
            "jev-1.13.0\n",
            "",
            None,
            1.13,
        ],
    )
    async def test_a_model_the_catalogue_refuses_is_refused_before_the_sdk(
        self, withheld: _Withhold, model: object
    ) -> None:
        with pytest.raises(ValueError) as raised:
            await jev_client.ask(
                api_key=KEY, model=model, state={}, questions=QUESTIONS
            )  # type: ignore[arg-type]

        assert str(raised.value) == jev_catalogue.model_problem(model)
        assert withheld.asked == []
        assert "TYPESAFE_LOG_LEVEL" not in os.environ

    @pytest.mark.parametrize("api_key", [None, b"sk-bytes", 42])
    async def test_a_key_that_is_not_text_is_refused_before_the_sdk(
        self, withheld: _Withhold, api_key: object
    ) -> None:
        # The SDK reads TYPESAFE_API_KEY when it is handed None. It is never
        # handed None.
        with pytest.raises(TypeError):
            await jev_client.ask(
                api_key=api_key, model=MODEL, state={}, questions=QUESTIONS
            )  # type: ignore[arg-type]

        assert withheld.asked == []


# ---------------------------------------------------------------------------
# The rate limiter
# ---------------------------------------------------------------------------


@dataclass
class FakeTime:
    """A clock that moves only when the limiter sleeps, or when told to."""

    now: float = 0.0
    sleeps: list[float] = field(default_factory=list)

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _limiter(
    time: FakeTime, requests: int = 1000, tokens: int = 200_000
) -> RateLimiter:
    return RateLimiter(
        requests_per_minute=requests,
        tokens_per_second=tokens,
        clock=time.clock,
        sleep=time.sleep,
    )


class TestTheRateLimiter:
    async def test_a_burst_up_to_the_limit_is_admitted_at_once(self) -> None:
        time = FakeTime()
        limiter = _limiter(time, requests=3)

        for _ in range(3):
            await limiter.acquire(10)

        assert time.sleeps == []

    async def test_the_next_request_waits_until_the_oldest_leaves_the_minute(
        self,
    ) -> None:
        time = FakeTime()
        limiter = _limiter(time, requests=3)
        for at in (0.0, 10.0, 20.0):
            time.now = at
            await limiter.acquire(10)

        time.now = 30.0
        await limiter.acquire(10)
        assert time.sleeps == [30.0], "until the one at 0 is a minute old"
        assert time.now == 60.0

        # The window slides: the next place frees when the one at 10 leaves.
        await limiter.acquire(10)
        assert time.sleeps == [30.0, 10.0]

    async def test_tokens_wait_until_enough_of_the_second_has_passed(self) -> None:
        time = FakeTime()
        limiter = _limiter(time, tokens=250)
        for at in (0.0, 0.2):
            time.now = at
            await limiter.acquire(100)

        time.now = 0.4
        await limiter.acquire(100)

        assert time.sleeps == [pytest.approx(0.6)], "until the first leaves at 1.0"

    async def test_only_as_many_requests_leave_as_the_new_one_needs(self) -> None:
        time = FakeTime()
        limiter = _limiter(time, tokens=300)
        for at in (0.0, 0.5, 0.9):
            time.now = at
            await limiter.acquire(100)

        time.now = 0.95
        await limiter.acquire(150)

        # 150 needs two of the three to leave, so it waits for the one at 0.5.
        assert time.sleeps == [pytest.approx(0.55)]

    async def test_the_longer_of_the_two_waits_is_the_one_taken(self) -> None:
        time = FakeTime()
        limiter = _limiter(time, requests=1, tokens=100)
        await limiter.acquire(100)

        time.now = 0.5
        await limiter.acquire(100)

        assert time.sleeps == [pytest.approx(59.5)], "the minute, not the second"

    async def test_a_request_bigger_than_a_second_goes_alone_rather_than_never(
        self,
    ) -> None:
        time = FakeTime()
        limiter = _limiter(time, tokens=100)
        await limiter.acquire(10)

        time.now = 0.5
        await limiter.acquire(500)
        assert time.now == pytest.approx(1.0), "it waited for the window to empty"

        # It was charged the whole second, so the next request waits it out.
        await limiter.acquire(1)
        assert time.now == pytest.approx(2.0)

    async def test_a_negative_estimate_charges_nothing(self) -> None:
        # Nothing, rather than a credit: two full requests still take two
        # seconds' allowance.
        time = FakeTime()
        limiter = _limiter(time, tokens=100)
        await limiter.acquire(-500)
        await limiter.acquire(100)
        assert time.sleeps == []

        await limiter.acquire(100)
        assert time.sleeps == [1.0]

    async def test_concurrent_callers_cannot_both_take_the_last_place(self) -> None:
        time = FakeTime()
        limiter = _limiter(time, requests=1)

        await asyncio.gather(limiter.acquire(1), limiter.acquire(1))

        assert time.sleeps == [60.0]

    def test_a_limit_must_admit_something(self) -> None:
        with pytest.raises(ValueError):
            RateLimiter(requests_per_minute=0, tokens_per_second=1)
        with pytest.raises(ValueError):
            RateLimiter(requests_per_minute=1, tokens_per_second=0)

    def test_the_process_limiter_holds_the_catalogues_ceilings(self) -> None:
        # Beneath the vendor's, which a 429 would otherwise enforce.
        limiter = jev_client._LIMITER
        assert limiter._max_requests == jev_catalogue.CLIENT_REQUESTS_PER_MINUTE
        assert limiter._max_tokens == jev_catalogue.CLIENT_TOKENS_PER_SECOND
        assert (
            jev_catalogue.CLIENT_REQUESTS_PER_MINUTE
            < jev_catalogue.VENDOR_REQUESTS_PER_MINUTE
        )
        assert (
            jev_catalogue.CLIENT_TOKENS_PER_SECOND
            < jev_catalogue.VENDOR_TOKENS_PER_SECOND
        )


# ---------------------------------------------------------------------------
# The values a call is recorded with
# ---------------------------------------------------------------------------


class TestTheRecordedValues:
    @pytest.mark.parametrize(
        ("content", "stored"),
        [
            (b'{"model":"jev-1.13.0"}', '{"model":"jev-1.13.0"}'),
            (b"", ""),
            ("caf\u00e9 \u2603".encode(), "caf\u00e9 \u2603"),
            (b"a\x00b", "a\ufffdb"),
            (b"caf\xe9", "caf\ufffd"),
            (b"\xff\xfe{\x00}\x00", "\ufffd\ufffd{\ufffd}\ufffd"),
        ],
    )
    def test_a_body_is_kept_verbatim_where_postgres_can_store_it(
        self, content: bytes, stored: str
    ) -> None:
        assert jev_client._storable(content) == stored

    def test_every_body_becomes_storable_text(self) -> None:
        # Postgres text holds neither NUL nor an unpaired surrogate.
        rng = random.Random(20260926)
        for _ in range(2000):
            content = rng.randbytes(rng.randrange(0, 64))
            text = jev_client._storable(content)
            assert "\x00" not in text
            text.encode("utf-8")
            try:
                verbatim = content.decode("utf-8")
            except UnicodeDecodeError:
                continue
            if "\x00" not in verbatim:
                assert text == verbatim

    @pytest.mark.parametrize(
        ("text", "is_json"),
        [
            ('{"detail":{"error_type":"authentication_error"}}', True),
            ("[1, 2]", True),
            ('"Forbidden"', True),
            ("403", True),
            ("<html><body>Request blocked</body></html>", False),
            ("Forbidden", False),
            ("", False),
            ("   ", False),
            (None, False),
        ],
    )
    def test_whether_a_body_is_json(self, text: str | None, is_json: bool) -> None:
        assert jev_client._is_json(text) is is_json

    def test_a_body_too_deep_to_parse_is_not_json_rather_than_an_exception(
        self,
    ) -> None:
        assert jev_client._is_json("[" * 100_000 + "]" * 100_000) is False

    @pytest.mark.parametrize(
        ("value", "count"),
        [
            (0, 0),
            (41, 41),
            (MAX_TOKEN_COUNT, MAX_TOKEN_COUNT),
            (MAX_TOKEN_COUNT + 1, None),
            (-1, None),
            (True, None),
            (1.0, None),
            ("41", None),
            (None, None),
        ],
    )
    def test_a_token_count_is_one_the_ledger_can_hold(
        self, value: object, count: int | None
    ) -> None:
        assert jev_client._count(value) == count

    @pytest.mark.parametrize(
        ("headers", "request_id"),
        [
            ({"x-typesafe-request-id": "req_01a0da8e66f5"}, "req_01a0da8e66f5"),
            ({}, None),
            ({"x-typesafe-request-id": ""}, None),
            ({"x-typesafe-request-id": "  "}, None),
        ],
    )
    def test_a_request_id_is_the_header_or_none(
        self, headers: dict[str, str], request_id: str | None
    ) -> None:
        response = types.SimpleNamespace(headers=headers)
        assert jev_client._request_id(response) == request_id

    def test_no_response_has_no_request_id(self) -> None:
        assert jev_client._request_id(None) is None

    @pytest.mark.parametrize(
        ("started", "finished", "latency"),
        [(None, 5.0, None), (1.0, 1.25, 250), (1.0, 1.0, 0), (2.0, 1.0, 0)],
    )
    def test_latency_is_unmeasured_until_something_is_sent(
        self, started: float | None, finished: float, latency: int | None
    ) -> None:
        assert jev_client._elapsed_ms(started, finished) == latency


# ---------------------------------------------------------------------------
# The request is never rewritten
# ---------------------------------------------------------------------------

#: The SDK's three ways to send something other than the state, model and
#: questions that were hashed. ``extra_body`` is merged last and shallowly, so
#: it can replace any of the three; ``extra_headers`` rides beside them; and
#: ``response_model`` swaps the SDK's parse for one of the caller's.
REQUEST_REWRITING_FIELDS = frozenset({"extra_body", "extra_headers", "response_model"})


def _request_rewrites(source: str) -> list[str]:
    """
    Every place ``source`` names a request-rewriting field, or could.

    A keyword, or the field's name as a string anywhere, which covers a dict
    key, a subscript and ``getattr`` alike; and a ``**`` spread into any call,
    which could carry any of them without naming it. The string must *be* the
    field's name, so a docstring that mentions one does not trip it.
    """
    offences: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg is None:
                    offences.append(f"line {node.lineno}: a ** spread into a call")
                elif keyword.arg in REQUEST_REWRITING_FIELDS:
                    offences.append(f"line {node.lineno}: keyword {keyword.arg}=")
        elif isinstance(node, ast.Constant) and node.value in REQUEST_REWRITING_FIELDS:
            offences.append(f"line {node.lineno}: string {node.value!r}")
    return offences


class TestTheRequestIsNeverRewritten:
    def test_the_client_names_no_field_that_rewrites_the_request(self) -> None:
        offences = _request_rewrites(CLIENT_SOURCE)
        assert not offences, (
            "src/programme/jev_client.py names a field that would send something "
            "other than the request the lane hashed:\n" + "\n".join(offences)
        )

    @pytest.mark.parametrize(
        "source",
        [
            "await client.system_one(state, questions, extra_body={'model': m})",
            "await client.system_one(state, questions, extra_headers=h)",
            "await client.system_one(state, questions, response_model=Loose)",
            "options = {'extra_body': {'state': other}}",
            "options['extra_headers'] = h",
            "setattr(request, 'response_model', Loose)",
            "await client.system_one(state, questions, **options)",
        ],
    )
    def test_the_scan_finds_each_spelling(self, source: str) -> None:
        assert _request_rewrites(source)

    def test_the_scan_does_not_trip_on_prose(self) -> None:
        source = '"""extra_body is merged last, so it is never passed."""\n'
        assert _request_rewrites(source) == []

    def test_the_sdk_is_handed_its_host_its_model_and_its_key(self) -> None:
        # The behaviour is proved against the real SDK in tests/sdk; this is
        # the tripwire in the job that cannot install it. Each argument left
        # out is one the SDK fills from the environment or its own default.
        #
        # Every construction is held to it, not only the first: ``ask`` builds
        # one to put a question, ``list_models`` another to check a key. The
        # model is the checked pin in ``ask`` and the catalogue's pin in
        # ``list_models``, which sends none but must still never let the SDK
        # read TYPESAFE_DEFAULT_MODEL. A construction anywhere else is a new
        # way to reach the vendor, and fails here until it is reviewed.
        tree = ast.parse(CLIENT_SOURCE)
        constructions: dict[str, ast.Call] = {}
        system_ones: list[ast.Call] = []
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(function):
                if not (
                    isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                ):
                    continue
                if node.func.attr == "AsyncTypeSafeClient":
                    assert function.name not in constructions, function.name
                    constructions[function.name] = node
                elif node.func.attr == "system_one":
                    system_ones.append(node)
        assert set(constructions) == {"ask", "list_models"}, sorted(constructions)
        pins = {"ask": "model", "list_models": "jev_catalogue.DEFAULT_MODEL"}
        for name, construct in constructions.items():
            given = {k.arg: ast.unparse(k.value) for k in construct.keywords}
            assert given["base_url"] == "jev_catalogue.JEV_BASE_URL", name
            assert given["api_key"] == "api_key", name
            assert given["model"] == pins[name], name
        [system_one] = system_ones
        assert {k.arg: ast.unparse(k.value) for k in system_one.keywords} == {
            "model": "model"
        }


# ---------------------------------------------------------------------------
# The transport seam
# ---------------------------------------------------------------------------

SEAM_MODULE = "src.programme.jev_client"
SEAM_FUNCTION = "ask"
SEAM_PARAMETER = "transport"

_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


@dataclass(frozen=True)
class _Param:
    """A seam parameter: its name, and its position if it can be passed by one."""

    name: str
    position: int | None


@dataclass
class _Module:
    name: str
    path: str
    tree: ast.Module
    is_package: bool
    parents: dict[ast.AST, ast.AST] = field(default_factory=dict)
    bindings: dict[str, str] = field(default_factory=dict)
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = field(
        default_factory=dict
    )

    @classmethod
    def parse(cls, relative: str, source: str) -> _Module:
        parts = list(Path(relative).with_suffix("").parts)
        is_package = parts[-1] == "__init__"
        if is_package:
            parts = parts[:-1]
        module = cls(".".join(parts), relative, ast.parse(source), is_package)
        for node in ast.walk(module.tree):
            for child in ast.iter_child_nodes(node):
                module.parents[child] = node
        module.bindings = module._bindings()
        module.functions = {
            node.name: node for node in module.tree.body if isinstance(node, _FUNCTIONS)
        }
        return module

    def _bindings(self) -> dict[str, str]:
        """Each imported name, as the dotted path it stands for. Any scope."""
        package = self.name if self.is_package else self.name.rpartition(".")[0]
        bound: dict[str, str] = {}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname:
                        bound[alias.asname] = alias.name
                    else:
                        head = alias.name.partition(".")[0]
                        bound[head] = head
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = package.split(".")
                    base = base[: len(base) - (node.level - 1)]
                    origin = ".".join([*base, *([node.module] if node.module else [])])
                else:
                    origin = node.module or ""
                for alias in node.names:
                    if alias.name != "*":
                        bound[alias.asname or alias.name] = f"{origin}.{alias.name}"
        return bound

    def dotted(self, node: ast.expr) -> str | None:
        """The full dotted path a name or attribute chain refers to, if known."""
        attributes: list[str] = []
        while isinstance(node, ast.Attribute):
            attributes.append(node.attr)
            node = node.value
        if not isinstance(node, ast.Name):
            return None
        if node.id in self.bindings:
            head = self.bindings[node.id]
        elif node.id in self.functions and not attributes:
            head = f"{self.name}.{node.id}"
        else:
            return None
        return ".".join([head, *reversed(attributes)])

    def enclosing(self, node: ast.AST) -> ast.AST | None:
        """The function or lambda ``node`` is inside, if any."""
        current = self.parents.get(node)
        while current is not None and not isinstance(
            current, (*_FUNCTIONS, ast.Lambda)
        ):
            current = self.parents.get(current)
        return current


def _target(
    dotted: str | None, modules: Mapping[str, _Module]
) -> tuple[str, str] | None:
    """``(module, function)`` for a dotted path that names a module's function."""
    if dotted is None:
        return None
    module, _, function = dotted.rpartition(".")
    return (module, function) if module in modules else None


def _parameters(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
) -> dict[str, tuple[int | None, ast.expr | None]]:
    """Each parameter's position (``None`` if keyword-only) and default."""
    positional = [*fn.args.posonlyargs, *fn.args.args]
    defaults: list[ast.expr | None] = [None] * (
        len(positional) - len(fn.args.defaults)
    ) + list(fn.args.defaults)
    found: dict[str, tuple[int | None, ast.expr | None]] = {
        arg.arg: (index, default)
        for index, (arg, default) in enumerate(zip(positional, defaults, strict=True))
    }
    for arg, default in zip(fn.args.kwonlyargs, fn.args.kw_defaults, strict=True):
        found[arg.arg] = (None, default)
    return found


def _is_none(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _rebinds(fn: ast.AST, name: str) -> bool:
    """Whether ``fn`` assigns, deletes or declares ``name`` anywhere in its body."""
    for node in ast.walk(fn):
        if isinstance(node, ast.Name) and node.id == name:
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                return True
        elif isinstance(node, (ast.Global, ast.Nonlocal)) and name in node.names:
            return True
    return False


def _forwarded(
    module: _Module, call: ast.Call, value: ast.expr
) -> tuple[tuple[str, str], _Param] | str:
    """
    The function forwarding ``value`` and the parameter it forwards; or, when
    ``value`` is not a forwarded seam, why not.
    """
    if not isinstance(value, ast.Name):
        return f"passes {ast.unparse(value)} as the transport"
    fn = module.enclosing(call)
    if fn is None:
        return f"passes {value.id}, a module-level name, as the transport"
    if not isinstance(fn, _FUNCTIONS) or module.parents.get(fn) is not module.tree:
        return (
            f"forwards {value.id} from a lambda, a method or a nested function, "
            "which this test cannot follow to its callers"
        )
    parameters = _parameters(fn)
    if value.id not in parameters:
        return f"passes {value.id}, which is not a parameter of {fn.name}"
    position, default = parameters[value.id]
    if not _is_none(default):
        return f"forwards {fn.name}'s {value.id}, which does not default to None"
    if _rebinds(fn, value.id):
        return f"{fn.name} rebinds {value.id} before forwarding it"
    return (module.name, fn.name), _Param(value.id, position)


def _seam_scan(
    modules: Mapping[str, _Module],
) -> tuple[list[str], dict[tuple[str, str], _Param]]:
    """
    Every place in ``modules`` that could hand ``jev_client.ask`` a transport,
    and every seam followed to find them.

    A seam is a function whose transport parameter reaches the client: the
    client's ``ask`` to begin with, then every function that forwards its own
    ``None``-defaulting parameter into a seam, and so on until nothing new is
    found. A call to a seam may leave the transport out, pass ``None``, or
    forward the caller's own parameter; anything else is an offence. So is
    spreading ``*args`` or ``**kwargs`` into a seam, which hides what it
    passes, and naming the client's ``ask`` other than to call it, or fetching
    it with ``getattr``: either way the call that receives it cannot be read.
    """
    offences: set[str] = set()
    client = modules.get(SEAM_MODULE)
    root = client.functions.get(SEAM_FUNCTION) if client else None
    if root is None:
        return [f"{SEAM_MODULE}.{SEAM_FUNCTION} is not defined"], {}
    position, default = _parameters(root).get(SEAM_PARAMETER, (0, None))
    if position is not None or not _is_none(default) or _rebinds(root, SEAM_PARAMETER):
        offences.add(
            f"{SEAM_MODULE}.{SEAM_FUNCTION} must take {SEAM_PARAMETER} as a "
            "keyword-only parameter defaulting to None, and never rebind it"
        )

    seams = {(SEAM_MODULE, SEAM_FUNCTION): _Param(SEAM_PARAMETER, None)}
    grown = True
    while grown:
        grown = False
        for module in modules.values():
            for call in ast.walk(module.tree):
                if not isinstance(call, ast.Call):
                    continue
                target = _target(module.dotted(call.func), modules)
                if target not in seams:
                    continue
                where = f"{module.path}:{call.lineno}"
                if any(isinstance(a, ast.Starred) for a in call.args) or any(
                    k.arg is None for k in call.keywords
                ):
                    offences.add(f"{where}: spreads arguments into {'.'.join(target)}")
                    continue
                seam = seams[target]
                value = next(
                    (k.value for k in call.keywords if k.arg == seam.name), None
                )
                if value is None and seam.position is not None:
                    if len(call.args) > seam.position:
                        value = call.args[seam.position]
                if value is None or _is_none(value):
                    continue
                forwarded = _forwarded(module, call, value)
                if isinstance(forwarded, str):
                    offences.add(f"{where}: {forwarded}")
                elif forwarded[0] not in seams:
                    seams[forwarded[0]] = forwarded[1]
                    grown = True

    for module in modules.values():
        for node in ast.walk(module.tree):
            if _fetches_the_client_by_name(module, node):
                offences.add(
                    f"{module.path}:{node.lineno}: reaches jev_client.ask through "
                    "getattr, so the transport it is given cannot be read"
                )
            if not isinstance(node, (ast.Name, ast.Attribute)):
                continue
            if _target(module.dotted(node), modules) != (SEAM_MODULE, SEAM_FUNCTION):
                continue
            parent = module.parents.get(node)
            if not (isinstance(parent, ast.Call) and parent.func is node):
                offences.add(
                    f"{module.path}:{node.lineno}: names jev_client.ask other than "
                    "to call it, so the transport it is given cannot be read"
                )
    return sorted(offences), seams


def _fetches_the_client_by_name(module: _Module, node: ast.AST) -> bool:
    """Whether ``node`` is ``getattr(<the client module>, "ask", ...)``."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
        and module.dotted(node.args[0]) == SEAM_MODULE
        and isinstance(node.args[1], ast.Constant)
        and node.args[1].value == SEAM_FUNCTION
    )


def _transport_offences(modules: Mapping[str, _Module]) -> list[str]:
    """The offences alone, which is all the synthetic cases below look at."""
    return _seam_scan(modules)[0]


def _modules(sources: Mapping[str, str]) -> dict[str, _Module]:
    parsed = [_Module.parse(path, source) for path, source in sources.items()]
    return {module.name: module for module in parsed}


def _tree(root: Path) -> dict[str, _Module]:
    return _modules(
        {
            path.relative_to(ROOT).as_posix(): path.read_text(encoding="utf-8")
            for path in sorted(root.rglob("*.py"))
            if "__pycache__" not in path.parts
        }
    )


#: A stand-in for the client, shaped as the real one is.
CLIENT_STUB = (
    "async def ask(*, api_key, model, state, questions, transport=None):\n    ...\n"
)


def _offences(**sources: str) -> list[str]:
    """Scan ``sources``, keyed by module path with ``/`` as ``__``, beside the stub."""
    files = {"src/programme/jev_client.py": CLIENT_STUB}
    files.update(
        {
            name.replace("__", "/") + ".py": textwrap.dedent(s)
            for name, s in sources.items()
        }
    )
    return _transport_offences(_modules(files))


class TestNothingInSrcHandsTheClientATransport:
    def test_production_code_never_passes_one(self) -> None:
        modules = _tree(SRC)
        assert SEAM_MODULE in modules
        offences, seams = _seam_scan(modules)
        followed = ", ".join(sorted(".".join(seam) for seam in seams))
        assert not offences, (
            "Production code can hand jev_client.ask a transport. It is a test "
            "seam: a transport decides where the state and the key are sent. "
            f"Seams followed: {followed}.\n" + "\n".join(offences)
        )

    @pytest.mark.parametrize(
        ("imports", "callee"),
        [
            ("from src.programme import jev_client", "jev_client.ask"),
            ("from src.programme import jev_client as jc", "jc.ask"),
            ("import src.programme.jev_client", "src.programme.jev_client.ask"),
            ("import src.programme.jev_client as jc", "jc.ask"),
            ("from src.programme.jev_client import ask", "ask"),
            ("from src.programme.jev_client import ask as jev_ask", "jev_ask"),
            ("from . import jev_client", "jev_client.ask"),
            ("from .jev_client import ask", "ask"),
        ],
    )
    def test_every_spelling_of_the_client_is_followed(
        self, imports: str, callee: str
    ) -> None:
        source = f"""
        import httpx2
        {imports}

        async def run(conn):
            return await {callee}(
                api_key="k", model="m", state={{}}, questions={{}},
                transport=httpx2.AsyncHTTPTransport(),
            )
        """
        [offence] = _offences(src__programme__jev_lane=source)
        assert (
            "src/programme/jev_lane.py:6: passes httpx2.AsyncHTTPTransport()" in offence
        )

    def test_an_import_inside_a_function_is_followed(self) -> None:
        source = """
        async def run(conn, made):
            from src.programme import jev_client
            return await jev_client.ask(transport=made)
        """
        [offence] = _offences(src__programme__jev_lane=source)
        assert "does not default to None" in offence

    def test_forwarding_the_seam_is_allowed(self) -> None:
        lane = """
        from src.programme import jev_client

        async def ask(conn, *, question_set, transport=None, probe=False):
            return await jev_client.ask(
                api_key="k", model="m", state={}, questions={}, transport=transport
            )

        async def run_probe(conn, api_key, transport=None):
            return await ask(conn, question_set=None, transport=transport, probe=True)
        """
        main = """
        from src.programme import jev_lane

        async def handle(conn, job):
            await jev_lane.run_probe(conn, "key")
            await jev_lane.run_probe(conn, "key", None)
            await jev_lane.ask(conn, question_set=None, transport=None)
        """
        assert _offences(src__programme__jev_lane=lane, src__programme__main=main) == []

    def test_a_transport_handed_to_a_forwarder_is_found(self) -> None:
        lane = """
        from src.programme import jev_client

        async def ask(conn, *, transport=None):
            return await jev_client.ask(transport=transport)
        """
        main = """
        import httpx2
        from src.programme import jev_lane

        async def handle(conn):
            await jev_lane.ask(conn, transport=httpx2.AsyncHTTPTransport())
        """
        [offence] = _offences(src__programme__jev_lane=lane, src__programme__main=main)
        assert offence.startswith("src/programme/main.py:6:")

    def test_forwarding_is_followed_through_every_forwarder(self) -> None:
        helper = """
        from src.programme import jev_client

        async def call(*, transport=None):
            return await jev_client.ask(transport=transport)
        """
        lane = """
        from src.programme.jev_call import call

        async def ask(conn, *, transport=None):
            return await call(transport=transport)
        """
        main = """
        from src.programme import jev_lane

        async def handle(conn, transport):
            await jev_lane.ask(conn, transport=transport)
        """
        [offence] = _offences(
            src__programme__jev_call=helper,
            src__programme__jev_lane=lane,
            src__programme__main=main,
        )
        assert offence.startswith("src/programme/main.py:5:")
        assert "does not default to None" in offence

    @pytest.mark.parametrize(
        ("lane", "complaint"),
        [
            (
                """
                from src.programme import jev_client
                DEFAULT = object()

                async def ask(conn, *, transport=DEFAULT):
                    return await jev_client.ask(transport=transport)
                """,
                "does not default to None",
            ),
            (
                """
                import httpx2
                from src.programme import jev_client

                async def ask(conn, *, transport=None):
                    transport = transport or httpx2.AsyncHTTPTransport()
                    return await jev_client.ask(transport=transport)
                """,
                "rebinds transport",
            ),
            (
                """
                from src.programme import jev_client
                TRANSPORT = None

                async def ask(conn):
                    return await jev_client.ask(transport=TRANSPORT)
                """,
                "not a parameter",
            ),
            (
                """
                from src.programme import jev_client

                class Lane:
                    async def ask(self, *, transport=None):
                        return await jev_client.ask(transport=transport)
                """,
                "cannot follow",
            ),
            (
                """
                from src.programme import jev_client

                async def ask(conn, **options):
                    return await jev_client.ask(**options)
                """,
                "spreads arguments",
            ),
        ],
    )
    def test_a_forwarder_that_could_carry_a_transport_is_found(
        self, lane: str, complaint: str
    ) -> None:
        [offence] = _offences(src__programme__jev_lane=lane)
        assert complaint in offence

    @pytest.mark.parametrize(
        "call",
        [
            "await jev_lane.run_probe(conn, 'key', made)",
            "await jev_lane.run_probe(*arguments)",
        ],
    )
    def test_a_transport_passed_by_position_or_spread_is_found(self, call: str) -> None:
        lane = """
        from src.programme import jev_client

        async def run_probe(conn, api_key, transport=None):
            return await jev_client.ask(api_key=api_key, transport=transport)
        """
        main = f"""
        from src.programme import jev_lane

        async def handle(conn, made, arguments):
            {call}
        """
        [offence] = _offences(src__programme__jev_lane=lane, src__programme__main=main)
        assert offence.startswith("src/programme/main.py:5:")

    def test_the_client_fetched_by_name_is_found(self) -> None:
        source = """
        from src.programme import jev_client

        async def run(made):
            return await getattr(jev_client, "ask")(transport=made)
        """
        [offence] = _offences(src__programme__jev_lane=source)
        assert "through getattr" in offence

    def test_the_client_passed_around_as_a_value_is_found(self) -> None:
        source = """
        import functools
        from src.programme import jev_client

        ASK = functools.partial(jev_client.ask, transport=object())
        """
        [offence] = _offences(src__programme__jev_lane=source)
        assert "other than to call it" in offence

    def test_a_transport_given_to_anything_else_is_not_its_business(self) -> None:
        source = """
        import httpx2

        async def fetch(url):
            async with httpx2.AsyncClient(transport=httpx2.AsyncHTTPTransport()) as c:
                return await c.get(url)
        """
        assert _offences(src__programme__web_ingest=source) == []

    @pytest.mark.parametrize(
        "stub",
        [
            "async def ask(*, transport=object()):\n    ...\n",
            "async def ask(transport=None):\n    ...\n",
            "async def ask(*, transport=None):\n    transport = 1\n",
            "async def call(*, transport=None):\n    ...\n",
        ],
    )
    def test_the_client_itself_must_keep_the_seam_closed_by_default(
        self, stub: str
    ) -> None:
        assert _transport_offences(_modules({"src/programme/jev_client.py": stub}))
