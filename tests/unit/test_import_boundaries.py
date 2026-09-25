"""
test_import_boundaries.py
-------------------------
Structural closure of the prompt-injection path recorded as C-1 in
``docs/02-security-audit.md``.

The original design let unsanitised social-media text flow into trade
reasoning, which is a path from "anyone can post" to "money moves". Sanitising
the text would be a mitigation; removing the path is a fix.

So: no module that computes or executes an order may import an LLM client. Not
"should not" — cannot, with a test that fails the build. A successful prompt
injection can then produce, at most, misleading prose in the commentary table.

"Computes or executes" includes the *processes*, not only the pure decision
code. ``src/worker`` is the only thing in this system that places an order, so
it is the package where an LLM import would matter most.

This is an AST scan rather than a runtime import check so it catches the import
even in a module that is never executed by the rest of the suite.

A scan is only as good as its scanner, and a scanner that silently finds
nothing passes every test in this file. That is not hypothetical: the check
that the API does not import the programme runner compared ``node.module``
against a set of module names, so ``from src.programme import tick`` — module
``src.programme``, name ``tick`` — went straight through it. Every scan below
is therefore one function applied to the real tree *and*, in this same file,
to synthetic sources that must trip it. A resolver that loses a route fails
its own test before it can pass a real one.

The boundary is also drawn ahead of the code it bounds. TypeSafe AI's System
One ("Jev") will be reached through ``src/programme/jev_client.py``, the one
module that may import ``typesafe_sdk``, with the constant base URL in
``src/programme/jev_catalogue.py`` so the API can show it without holding a
client. Neither exists yet. The names are refused here first, so the first
commit that adds them lands against a boundary rather than before one.
"""

from __future__ import annotations

import ast
import functools
import os
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

#: Packages that must never appear anywhere in the decision or execution path.
#:
#: Matched on whole dotted segments — ``name == prefix`` or
#: ``name.startswith(prefix + ".")`` — rather than on the first segment alone.
#: The first-segment rule could express ``anthropic`` and could not express
#: ``google.generativeai``: split on ".", that is ``google``, which bans every
#: Google library or none of them. The same rule is why ``jev`` refuses ``jev``
#: and ``jev.client`` and leaves ``src.programme.jev_catalogue`` alone.
FORBIDDEN_PREFIXES = (
    # Anthropic's SDK, and what remains of the deleted agent pipeline's stack.
    "anthropic",
    "openai",
    "transformers",
    "nltk",
    "torch",
    # TypeSafe AI's System One. ``typesafe_sdk`` is the official client and
    # ``httpx2`` is the HTTP library it is built on, so holding the transport
    # is most of the way to holding the client. The rest are the names a
    # lookalike or a typosquat would use. The real SDK will be imported in
    # exactly one place, ``src/programme/jev_client.py``, which the process
    # boundary already puts out of reach of everything this list protects.
    "typesafe_sdk",
    "typesafe_ai",
    "typesafe",
    "httpx2",
    "jev",
    "cooksafe",
    # Other model clients. None is in use; they are listed so that "we
    # switched vendor" is a decision this file forces rather than one it
    # misses.
    "litellm",
    "langchain",
    "langchain_core",
    "langchain_community",
    "langchain_openai",
    "langchain_anthropic",
    "llama_index",
    "cohere",
    "mistralai",
    "groq",
    "ollama",
    "google.generativeai",
    "google.genai",
    "vertexai",
)

#: Pure computation that turns market data into orders.
DECISION_PATH = ("core", "strategies", "engine", "execution", "data")

#: The processes that can actually move money.
#:
#: These were missing, and their absence was the most important gap in this
#: file: ``src/worker`` is, in CLAUDE.md's own words, "the only process that
#: runs backtests or places orders", and it was the one package not guarded
#: against importing an LLM client. ``src/api`` is what commands it.
#:
#: They are held to the same prohibition as the decision path even though,
#: unlike it, they legitimately perform I/O. If commentary generation is ever
#: wanted after a backtest it belongs in its own job or process, not inside
#: the module that submits orders — and this test is where that decision gets
#: made deliberately rather than by accident.
ORDER_PROCESSES = ("worker", "api")

PROTECTED_PACKAGES = DECISION_PATH + ORDER_PROCESSES

#: Modules outside ``src/`` that run inside a protected process.
#:
#: ``api/index.py`` *is* the control plane on Vercel, and a scan rooted at
#: ``src/`` cannot see it: an import added there would reach the deployed API
#: with every test in this file green. The two scripts build the same
#: application in-process, from the workflows that hold the broker
#: credentials. All three are walked as part of ``api``.
ENTRY_POINTS: Mapping[str, tuple[str, ...]] = {
    "api": (
        "api.index",
        "scripts.bootstrap_paper_deployment",
        "scripts.deployment_status",
    ),
}

#: The one package allowed to hold a model client, and therefore the one
#: package that must not be able to reach an order.
#:
#: This is the mirror image of everything above, and it is the guarantee the AI
#: programme rests on. ``src/programme`` runs as its own process precisely so
#: it can import ``anthropic`` without that import landing in the API or the
#: worker. The price of that permission is this prohibition: it may enqueue a
#: job row and read results, and it may not import the code that fills an order
#: or the process that submits one.
#:
#: ``src.strategies`` is deliberately *not* forbidden. The programme validates
#: every proposed configuration through the strategy's own ``params_model``,
#: which is what stops a hallucinated parameter reaching the engine — and doing
#: that requires importing the registry. Strategies are pure by their own test
#: two functions down, so importing them grants no ability to act.
MODEL_HOLDING_PACKAGE = "programme"

#: Packages that can place or simulate an order.
ORDER_CAPABLE_MODULES = ("src.execution", "src.worker")

#: Modules of ``src/programme`` that belong to the runner process alone.
#:
#: ``client`` and ``jev_client`` hold the SDKs. ``author`` and ``panel`` import
#: ``client`` at module level, ``tick`` and ``main`` import those, and
#: ``jev_lane`` will import ``jev_client``. The two Jev modules do not exist
#: yet. Matching is on the *imported name*, not on a file being present, so
#: ``from src.programme import jev_client`` is refused today.
RUNNER_ONLY = (
    "src.programme.tick",
    "src.programme.author",
    "src.programme.client",
    "src.programme.main",
    "src.programme.panel",
    "src.programme.jev_client",
    "src.programme.jev_lane",
)

#: The commentary layer. It imports its client lazily, so it is a route to a
#: model that never names one.
COMMENTARY_LAYER = ("src.llm",)

#: The deleted agent pipeline, also as ``agents`` for an import written with
#: ``src/`` itself on the path.
LEGACY_AGENTS = ("src.agents", "agents")

#: What ``src/core`` may not reach: it is value types, and anything may import it.
CORE_MUST_NOT_REACH = ("src.engine", "src.execution")

#: What a strategy may not reach: anything that performs I/O.
STRATEGY_IO = (
    "aiohttp",
    "requests",
    "httpx",
    "httpx2",
    "asyncpg",
    "socket",
    "urllib",
    "urllib3",
    "http",
    "yfinance",
    "src.db",
    "src.data",
    "src.execution",
)

#: Request fields that would let a model act rather than only write text.
TOOL_GRANTING_FIELDS = frozenset({"tools", "tool_choice"})

#: The TypeSafe endpoint, and the only two files allowed to spell it.
TYPESAFE_ENDPOINT_MARKERS = ("api.typesafe.ai", "/v1/systemone")
TYPESAFE_ENDPOINT_HOLDERS = frozenset(
    {"src/programme/jev_catalogue.py", "src/programme/jev_client.py"}
)

#: Product code: what runs, as opposed to what tests it.
PRODUCT_TREES = ("src", "web/src")
SKIPPED_DIRECTORIES = frozenset({"node_modules", ".next", "__pycache__"})


# ---------------------------------------------------------------------------
# The scanner
# ---------------------------------------------------------------------------


def _matches(name: str, prefixes: Iterable[str]) -> bool:
    """Whether ``name`` is, or is inside, one of ``prefixes``."""
    return any(name == p or name.startswith(f"{p}.") for p in prefixes)


def _is_import_call(node: ast.Call) -> bool:
    """``importlib.import_module(...)``, ``import_module(...)``, ``__import__(...)``."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in {"import_module", "__import__"}
    if isinstance(func, ast.Attribute):
        return func.attr in {"import_module", "__import__"}
    return False


def _import_literal(node: ast.Call) -> str | None:
    """The absolute module an import call names, when it names one literally."""
    if not node.args:
        return None
    target = node.args[0]
    if isinstance(target, ast.Constant) and isinstance(target.value, str):
        # A relative literal needs its package argument to resolve. Returning
        # None sends it to the computed-import test, which refuses it.
        return None if target.value.startswith(".") else target.value
    return None


def _resolve_from(node: ast.ImportFrom, package: str) -> str | None:
    """The absolute module a ``from ... import`` statement reads from."""
    if node.level == 0:
        return node.module
    parts = package.split(".") if package else []
    up = node.level - 1
    if up >= len(parts):
        # Beyond the top-level package: an ImportError at runtime, which is
        # a crash rather than a capability.
        return None
    base = parts[: len(parts) - up]
    if node.module:
        base.append(node.module)
    return ".".join(base)


def _imported_names(
    source: str, module: str, *, is_package: bool = False
) -> frozenset[str]:
    """
    Every absolute dotted name an import in ``source`` can load.

    Each rule here is a hole an earlier version of this file had:

    * ``from a.b import c`` yields ``a.b`` *and* ``a.b.c``. The source alone
      cannot say whether ``c`` is an attribute or a submodule, and when it is a
      submodule Python loads it. Reading ``node.module`` alone is how
      ``from src.programme import tick`` passed the runner check.
    * ``import a, b`` is two imports. Joining them into ``"a,b"`` and testing
      set membership, as three checks here did, misses both.
    * Relative imports resolve against the importing module's package, so
      ``from ...programme import tick`` in ``src/api/routers`` is
      ``src.programme.tick``.
    * ``ast.walk`` reaches function bodies and ``if TYPE_CHECKING:`` blocks.
      An import one call away is still a capability the process holds; a
      type-checking-only import is counted too, which errs towards refusal.
    * ``importlib.import_module("x")`` and ``__import__("x")`` with a literal
      are imports by another spelling. With anything *but* a literal they
      cannot be read, and ``test_nothing_guarded_imports_by_a_computed_name``
      refuses them instead.
    """
    package = module if is_package else module.rpartition(".")[0]
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_from(node, package)
            if base is None:
                continue
            names.add(base)
            names.update(f"{base}.{a.name}" for a in node.names if a.name != "*")
        elif isinstance(node, ast.Call) and _is_import_call(node):
            literal = _import_literal(node)
            if literal is not None:
                names.add(literal)
    return frozenset(names)


def _offending(names: Iterable[str], prefixes: Sequence[str]) -> list[str]:
    """
    The imported names inside ``prefixes``, without their own children.

    ``from anthropic import AsyncAnthropic`` yields ``anthropic`` and
    ``anthropic.AsyncAnthropic``; reporting both says one thing twice.
    """
    hits = {n for n in names if _matches(n, prefixes)}
    return sorted(n for n in hits if not any(n.startswith(f"{h}.") for h in hits))


def _computed_imports(source: str) -> list[str]:
    """Every import call whose target is not a readable literal."""
    return [
        f"line {node.lineno}: {ast.unparse(node)}"
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and _is_import_call(node)
        and _import_literal(node) is None
    ]


def _tool_grants(source: str) -> list[str]:
    """
    Every place ``source`` could hand a model a tool.

    A keyword (``tools=[...]``) or the field's name as a string anywhere — which
    covers ``request["tools"] = ...`` and ``{"tools": [...]}`` alike. The
    string must *be* the field name, so a docstring that mentions tools does
    not trip it.
    """
    offences: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            offences.extend(
                f"keyword {k.arg}="
                for k in node.keywords
                if k.arg in TOOL_GRANTING_FIELDS
            )
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in TOOL_GRANTING_FIELDS:
                offences.append(f"string literal {node.value!r}")
    return offences


def _endpoint_mentions(relative: str, data: bytes) -> list[str]:
    """The TypeSafe endpoint markers in a file that is not allowed to hold them."""
    if relative in TYPESAFE_ENDPOINT_HOLDERS:
        return []
    lowered = data.lower()
    return [m for m in TYPESAFE_ENDPOINT_MARKERS if m.encode() in lowered]


# ---------------------------------------------------------------------------
# The import graph
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ImportGraph:
    """Which modules of one tree each module of it can load, and what it names."""

    sources: Mapping[str, str]
    names: Mapping[str, frozenset[str]]
    edges: Mapping[str, frozenset[str]]


def _prefixes(name: str) -> list[str]:
    parts = name.split(".")
    return [".".join(parts[:i]) for i in range(1, len(parts) + 1)]


def _build_graph(sources: Mapping[str, tuple[str, bool]]) -> ImportGraph:
    """
    Resolve every import in ``sources`` to the modules of the tree it loads.

    ``sources`` maps a dotted module name to its text and whether it is a
    package's ``__init__``.

    Loading ``src.programme.repo`` runs ``src/__init__.py`` and
    ``src/programme/__init__.py`` first, so an edge is drawn to every module
    that an imported name *or any dotted prefix of one* names. That one rule
    does three jobs. A package ``__init__`` that imported the runner would put
    it behind every sibling, and the walk sees that. ``from
    src.programme.gates import VETO_ROLES`` names ``...gates.VETO_ROLES``,
    which is not a module, so the edge stops at ``gates``; ``from src.programme
    import panel`` names ``src.programme.panel``, which is. And a module's own
    enclosing packages are edges too, because they run before it does.
    """
    names = {
        module: _imported_names(text, module, is_package=is_package)
        for module, (text, is_package) in sources.items()
    }
    edges: dict[str, frozenset[str]] = {}
    for module, imported in names.items():
        targets = set(_prefixes(module)[:-1])
        for name in imported:
            targets.update(_prefixes(name))
        edges[module] = frozenset(t for t in targets if t in sources and t != module)
    return ImportGraph(
        sources={m: text for m, (text, _) in sources.items()},
        names=names,
        edges=edges,
    )


def _module_name(path: Path) -> tuple[str, bool]:
    parts = path.relative_to(ROOT).with_suffix("").parts
    if parts[-1] == "__init__":
        return ".".join(parts[:-1]), True
    return ".".join(parts), False


def _entry_point_path(module: str) -> Path:
    return ROOT.joinpath(*module.split(".")).with_suffix(".py")


@functools.cache
def _real_graph() -> ImportGraph:
    paths = sorted(SRC.rglob("*.py"))
    paths += [
        path
        for modules in ENTRY_POINTS.values()
        for path in map(_entry_point_path, modules)
        if path.is_file()
    ]
    sources: dict[str, tuple[str, bool]] = {}
    for path in paths:
        module, is_package = _module_name(path)
        sources[module] = (path.read_text(encoding="utf-8"), is_package)
    return _build_graph(sources)


def _package_modules(graph: ImportGraph, package: str) -> list[str]:
    """Every module of ``src/<package>``, plus the entry points that run it."""
    modules = [m for m in graph.names if _matches(m, (f"src.{package}",))]
    modules += [m for m in ENTRY_POINTS.get(package, ()) if m in graph.names]
    return sorted(modules)


def _walk(graph: ImportGraph, starts: Iterable[str]) -> dict[str, str | None]:
    """Every module reachable from ``starts``, each with the module that loads it."""
    parents: dict[str, str | None] = dict.fromkeys(starts)
    queue = deque(parents)
    while queue:
        module = queue.popleft()
        for target in sorted(graph.edges[module]):
            if target not in parents:
                parents[target] = module
                queue.append(target)
    return parents


def _route(parents: Mapping[str, str | None], module: str) -> str:
    chain = [module]
    while (parent := parents[chain[-1]]) is not None:
        chain.append(parent)
    return " -> ".join(reversed(chain))


def _reachable_offences(
    graph: ImportGraph, starts: Iterable[str], prefixes: Sequence[str]
) -> list[str]:
    """
    Every forbidden import anywhere in the closure of ``starts``, with its route.

    The walk is breadth-first from all of ``starts`` at once, so each offence
    is reported once, by the shortest route from anything in the package.
    """
    parents = _walk(graph, starts)
    return [
        f"{_route(parents, module)} imports {name}"
        for module in sorted(parents)
        for name in _offending(graph.names[module], prefixes)
    ]


def _direct_offences(package: str, prefixes: Sequence[str]) -> list[str]:
    """One module at a time: what each module of ``package`` itself imports."""
    graph = _real_graph()
    modules = _package_modules(graph, package)
    assert modules, f"the scan found no modules in src/{package}"
    return [
        f"{module} imports {name}"
        for module in modules
        for name in _offending(graph.names[module], prefixes)
    ]


def _synthetic(tree: Mapping[str, str]) -> ImportGraph:
    """A graph from ``{"src/api/x.py": source}``, for routes the real tree lacks."""
    return _build_graph(
        {
            module: (text, is_package)
            for path, text in tree.items()
            for module, is_package in [_module_name(ROOT / path)]
        }
    )


def _product_files(*trees: str) -> list[Path]:
    files: list[Path] = []
    for tree in trees:
        for directory, subdirectories, names in os.walk(ROOT / tree):
            subdirectories[:] = sorted(
                d for d in subdirectories if d not in SKIPPED_DIRECTORIES
            )
            files.extend(Path(directory) / name for name in sorted(names))
    return files


# ---------------------------------------------------------------------------
# The scanner, tested against sources that must trip it
# ---------------------------------------------------------------------------

_API = "src.api.routers.programme"


def _cases(prefixes: Sequence[str], module: str, *cases: tuple[str, ...]) -> list:
    """``pytest.param`` rows for one rule, from ``(id, source, *expected)``."""
    return [pytest.param(prefixes, module, *rest, id=name) for name, *rest in cases]


#: (prefixes, importing module, source, the name that must be reported)
_OFFENDING = [
    # A model client, by every spelling.
    *_cases(
        FORBIDDEN_PREFIXES,
        "src.worker.job",
        ("llm-import", "import anthropic", "anthropic"),
        ("llm-from", "from anthropic import AsyncAnthropic", "anthropic"),
        ("llm-lazy", "def f():\n    from anthropic import Anthropic", "anthropic"),
        ("jev-sdk-in-a-list", "import os, typesafe_sdk", "typesafe_sdk"),
        ("jev-sdk-submodule", "from typesafe_sdk.v1 import decide", "typesafe_sdk.v1"),
        ("jev-lookalike", "import typesafe_ai", "typesafe_ai"),
        ("jev-lookalike-package", "import typesafe.client", "typesafe.client"),
        ("jev-transport", "import httpx2", "httpx2"),
        ("jev-bare", "from jev import decide", "jev"),
        ("jev-cooksafe", "import cooksafe", "cooksafe"),
        ("dotted-parent", "from google import generativeai", "google.generativeai"),
        ("dotted-import", "import google.generativeai as genai", "google.generativeai"),
        ("dotted-new-sdk", "from google.genai import Client", "google.genai"),
        ("langchain-core", "import langchain_core", "langchain_core"),
        ("by-literal-name", "importlib.import_module('typesafe_sdk')", "typesafe_sdk"),
        ("by-dunder-import", "__import__('openai')", "openai"),
    ),
    # The runner, from the API. The first three passed the old check.
    *_cases(
        RUNNER_ONLY,
        _API,
        ("runner-from-package", "from src.programme import tick", "src.programme.tick"),
        ("runner-in-a-list", "import os, src.programme.author", "src.programme.author"),
        ("runner-relative", "from ...programme import client", "src.programme.client"),
        (
            "runner-panel",
            "from src.programme import repo, panel",
            "src.programme.panel",
        ),
        ("runner-module", "from src.programme.main import run", "src.programme.main"),
        (
            "jev-client-before-it-exists",
            "from src.programme import jev_client",
            "src.programme.jev_client",
        ),
        (
            "jev-lane-lazily",
            "def f():\n    import src.programme.jev_lane",
            "src.programme.jev_lane",
        ),
    ),
    # The commentary layer. The old substring check missed the first.
    *_cases(
        COMMENTARY_LAYER,
        "src.worker.job",
        ("commentary-from-src", "from src import llm", "src.llm"),
        ("commentary-relative", "from ..llm import sanitize", "src.llm"),
        ("commentary-import", "import src.llm.commentary", "src.llm.commentary"),
    ),
    *_cases(
        LEGACY_AGENTS,
        "src.engine.x",
        ("agents-from-src", "from src import agents", "src.agents"),
        ("agents-import", "import src.agents.sentiment", "src.agents.sentiment"),
    ),
    # An order, from the programme.
    *_cases(
        ORDER_CAPABLE_MODULES,
        "src.programme.tick",
        ("order-from-src", "from src import worker", "src.worker"),
        ("order-relative", "from ..execution.alpaca import X", "src.execution.alpaca"),
        ("order-aliased", "import src.worker.live_job as live", "src.worker.live_job"),
    ),
    # Core reaching up. The old text search missed the first two.
    *_cases(
        CORE_MUST_NOT_REACH,
        "src.core.risk",
        ("core-from-src", "from src import engine", "src.engine"),
        ("core-import", "import src.execution.base", "src.execution.base"),
        ("core-relative", "from ..engine.driver import Driver", "src.engine.driver"),
    ),
    *_cases(
        STRATEGY_IO,
        "src.strategies.momentum",
        ("io-urllib", "from urllib.request import urlopen", "urllib.request"),
        ("io-http", "import http.client", "http.client"),
        ("io-database", "from src.db import repos", "src.db"),
    ),
]

#: (prefixes, importing module, source) that must report nothing.
_INNOCENT = [
    *_cases(
        FORBIDDEN_PREFIXES,
        "src.worker.job",
        ("google-but-not-a-model", "import google.cloud.storage"),
        ("jev-is-a-segment-not-a-substring", "import jevons"),
        ("the-jev-catalogue-is-not-jev", "from src.programme import jev_catalogue"),
        ("near-misses", "import typesafety, httpx"),
    ),
    *_cases(
        RUNNER_ONLY,
        _API,
        (
            "every-module-the-api-may-read",
            "from src.programme import repo, flags, gates, models, roles, reports, "
            "scorecard, jev_catalogue",
        ),
        ("an-attribute-named-like-a-runner", "from src.programme.gates import tick"),
    ),
    *_cases(
        COMMENTARY_LAYER,
        "src.worker.job",
        ("a-substring-is-not-a-package", "from src.llmish import x"),
    ),
    *_cases(
        CORE_MUST_NOT_REACH,
        "src.core.risk",
        ("a-docstring-is-not-an-import", '"""Nothing here does from src.engine."""'),
    ),
]


@pytest.mark.parametrize(("prefixes", "module", "source", "expected"), _OFFENDING)
def test_the_scanner_sees_every_spelling_of_an_import(
    prefixes: Sequence[str], module: str, source: str, expected: str
) -> None:
    """
    Every scan in this file is ``_offending(_imported_names(...))``. If that
    composition misses a spelling, every test built on it passes vacuously.
    """
    found = _offending(_imported_names(source, module), prefixes)
    assert expected in found, f"{source!r} in {module} should report {expected}"


@pytest.mark.parametrize(("prefixes", "module", "source"), _INNOCENT)
def test_the_scanner_does_not_invent_an_import(
    prefixes: Sequence[str], module: str, source: str
) -> None:
    """The other direction: a scanner that flags everything gets switched off."""
    assert _offending(_imported_names(source, module), prefixes) == []


_INIT = {
    "src/__init__.py": "",
    "src/api/__init__.py": "",
    "src/programme/__init__.py": "",
}

#: (tree, start, prefixes, the offence the walk must report)
_ROUTES = [
    pytest.param(
        {
            **_INIT,
            "src/api/x.py": "from src.programme import repo\n",
            "src/programme/__init__.py": "from src.programme import tick\n",
            "src/programme/repo.py": "",
            "src/programme/tick.py": "import anthropic\n",
        },
        "src.api.x",
        FORBIDDEN_PREFIXES,
        "src.api.x -> src.programme -> src.programme.tick imports anthropic",
        id="through-a-package-init",
    ),
    pytest.param(
        {
            **_INIT,
            "src/api/x.py": "import src.programme.repo\n",
            "src/programme/__init__.py": "from . import tick\n",
            "src/programme/repo.py": "",
            "src/programme/tick.py": "import anthropic\n",
        },
        "src.api.x",
        FORBIDDEN_PREFIXES,
        "src.api.x -> src.programme -> src.programme.tick imports anthropic",
        id="a-dotted-import-runs-every-package-on-the-way",
    ),
    pytest.param(
        {
            **_INIT,
            "src/worker/x.py": "from src.db.repos import jobs\n",
            "src/db/__init__.py": "import src.llm.commentary\n",
            "src/db/repos/__init__.py": "",
            "src/db/repos/jobs.py": "",
        },
        "src.worker.x",
        COMMENTARY_LAYER,
        "src.worker.x -> src.db imports src.llm.commentary",
        id="an-enclosing-package-of-the-imported-module",
    ),
    pytest.param(
        {
            **_INIT,
            "src/worker/__init__.py": "import anthropic\n",
            "src/worker/x.py": "",
        },
        "src.worker.x",
        FORBIDDEN_PREFIXES,
        "src.worker.x -> src.worker imports anthropic",
        id="the-importing-module-s-own-package",
    ),
    pytest.param(
        {
            **_INIT,
            "src/api/x.py": "from src.programme.roles import ROLES\n",
            "src/programme/roles.py": (
                "ROLES = ()\ndef assess():\n    from src.programme.client import ask\n"
            ),
            "src/programme/client.py": "import typesafe_sdk\n",
        },
        "src.api.x",
        FORBIDDEN_PREFIXES,
        "src.api.x -> src.programme.roles -> src.programme.client imports typesafe_sdk",
        id="lazily-two-hops-the-historical-hole",
    ),
    pytest.param(
        {
            **_INIT,
            "src/api/routers/x.py": "from ...programme import models\n",
            "src/programme/models.py": "from . import jev_client\n",
            "src/programme/jev_client.py": "from typesafe_sdk import Client\n",
        },
        "src.api.routers.x",
        FORBIDDEN_PREFIXES,
        "src.api.routers.x -> src.programme.models -> src.programme.jev_client "
        "imports typesafe_sdk",
        id="relative-imports-both-levels",
    ),
    pytest.param(
        {
            **_INIT,
            "src/api/routers/x.py": "from ...programme import models\n",
            "src/programme/models.py": "from . import jev_client\n",
        },
        "src.api.routers.x",
        RUNNER_ONLY,
        "src.api.routers.x -> src.programme.models imports src.programme.jev_client",
        id="a-runner-module-that-does-not-exist-yet",
    ),
    pytest.param(
        {
            **_INIT,
            "src/api/__init__.py": "from .routers import programme\n",
            "src/api/routers/programme.py": "from src.llm import commentary\n",
            "src/llm/commentary.py": "",
        },
        "src.api",
        COMMENTARY_LAYER,
        "src.api -> src.api.routers.programme imports src.llm",
        id="a-package-init-importing-relatively",
    ),
    pytest.param(
        {
            **_INIT,
            "src/worker/x.py": (
                "import importlib\nimportlib.import_module('src.programme.tick')\n"
            ),
            "src/programme/tick.py": "import anthropic\n",
        },
        "src.worker.x",
        FORBIDDEN_PREFIXES,
        "src.worker.x -> src.programme.tick imports anthropic",
        id="a-module-loaded-by-literal-name",
    ),
]

#: (tree, start, prefixes) whose walk must report nothing.
_DEAD_ENDS = [
    pytest.param(
        {
            **_INIT,
            "src/api/x.py": "from src.programme.gates import tick\n",
            "src/programme/gates.py": "tick = 1\n",
            "src/programme/tick.py": "import anthropic\n",
        },
        "src.api.x",
        FORBIDDEN_PREFIXES + RUNNER_ONLY,
        id="an-attribute-is-not-the-module-it-is-named-after",
    ),
    pytest.param(
        {
            **_INIT,
            "src/api/x.py": "from src.programme import repo\n",
            "src/programme/repo.py": "",
            "src/programme/client.py": "import anthropic\n",
        },
        "src.api.x",
        FORBIDDEN_PREFIXES,
        id="a-sibling-is-not-loaded-by-its-package",
    ),
]


@pytest.mark.parametrize(("tree", "start", "prefixes", "expected"), _ROUTES)
def test_the_resolver_follows_every_route_a_module_can_be_loaded_by(
    tree: Mapping[str, str], start: str, prefixes: Sequence[str], expected: str
) -> None:
    offences = _reachable_offences(_synthetic(tree), [start], prefixes)
    assert expected in offences, offences


@pytest.mark.parametrize(("tree", "start", "prefixes"), _DEAD_ENDS)
def test_the_resolver_does_not_invent_a_route(
    tree: Mapping[str, str], start: str, prefixes: Sequence[str]
) -> None:
    assert _reachable_offences(_synthetic(tree), [start], prefixes) == []


def test_the_resolver_sees_the_real_tree() -> None:
    """
    Guards the guard on the real tree. A resolver that found no edges would
    pass every closure test below, so it must find the ones that exist: the
    worker reaches the broker it drives, the API reaches the programme rows it
    reads, and the Vercel entry point reaches the API it serves.
    """
    graph = _real_graph()
    assert len(graph.names) >= 60, sorted(graph.names)
    assert "src.execution.alpaca" in _walk(graph, ["src.worker.main"])
    assert "src.programme.repo" in _walk(graph, _package_modules(graph, "api"))
    assert "src.api.main" in graph.edges["api.index"]


def test_the_entry_points_outside_src_still_exist() -> None:
    """
    ``ENTRY_POINTS`` is a list, and a list goes stale silently: a renamed script
    would drop out of the walk while every test stayed green. If this fails,
    point the entry at the new name rather than deleting it.
    """
    missing = [
        m
        for ms in ENTRY_POINTS.values()
        for m in ms
        if not _entry_point_path(m).is_file()
    ]
    assert not missing, missing


@pytest.mark.parametrize(
    ("source", "computed"),
    [
        ("import importlib\nimportlib.import_module(name)", True),
        ("__import__(name)", True),
        ("from importlib import import_module\nimport_module(f'src.{x}')", True),
        ("importlib.import_module('.jev_client', __package__)", True),
        ("importlib.import_module('src.programme.repo')", False),
        ("frame.eval('a + b')", False),
    ],
)
def test_the_computed_import_scan(source: str, computed: bool) -> None:
    assert bool(_computed_imports(source)) is computed


@pytest.mark.parametrize(
    ("source", "granted"),
    [
        ("client.messages.create(model=m, tools=[])", True),
        ('request["tools"] = [spec]', True),
        ('request = {"tool_choice": {"type": "auto"}}', True),
        ("request = dict(tool_choice='auto')", True),
        ('"""The model is passed no tools."""', False),
        ("client.messages.create(model=m, max_tokens=1)", False),
    ],
)
def test_the_tool_grant_scan(source: str, granted: bool) -> None:
    assert bool(_tool_grants(source)) is granted


@pytest.mark.parametrize(
    ("relative", "text", "expected"),
    [
        (
            "src/worker/live_job.py",
            'URL = "https://API.TypeSafe.ai/v1/SystemOne"',
            ["api.typesafe.ai", "/v1/systemone"],
        ),
        ("web/src/lib/api.ts", "fetch(`${base}/V1/SYSTEMONE`)", ["/v1/systemone"]),
        ("src/programme/jev_lane.py", 'PATH = "/v1/systemone"', ["/v1/systemone"]),
        ("src/programme/jev_catalogue.py", 'BASE_URL = "https://api.typesafe.ai"', []),
        ("src/programme/jev_client.py", 'PATH = "/v1/systemone"', []),
        ("src/api/routers/system.py", "# TypeSafe AI's System One", []),
    ],
)
def test_the_endpoint_scan(relative: str, text: str, expected: list[str]) -> None:
    assert _endpoint_mentions(relative, text.encode()) == expected


# ---------------------------------------------------------------------------
# The boundaries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("package", PROTECTED_PACKAGES)
def test_decision_path_never_imports_an_llm(package: str) -> None:
    """No LLM client may be reachable from code that can move money."""
    offenders = _direct_offences(package, FORBIDDEN_PREFIXES)
    assert not offenders, (
        "LLM/NLP imports found in the decision path — this reopens the "
        "prompt-injection route from untrusted text to an order:\n"
        + "\n".join(offenders)
    )


@pytest.mark.parametrize("package", PROTECTED_PACKAGES)
def test_decision_path_never_imports_the_legacy_agents(package: str) -> None:
    """
    The legacy ``src.agents`` package is non-deterministic by construction.
    Anything importing it becomes unbacktestable, which defeats the point.

    Imports are parsed rather than the text grepped: a docstring that
    *mentions* src.agents (as core/__init__.py does, to explain the boundary)
    is documentation, not a dependency.
    """
    offenders = _direct_offences(package, LEGACY_AGENTS)
    assert not offenders, (
        "decision-path modules import the legacy agent package:\n"
        + "\n".join(offenders)
    )


@pytest.mark.parametrize("package", PROTECTED_PACKAGES)
def test_decision_path_never_imports_the_commentary_layer(package: str) -> None:
    """
    ``src.llm`` imports its client lazily, so a module could route to a model
    through it without ever naming ``anthropic``. Blocking the direct import
    alone would leave that door open, so the package itself is off-limits to
    anything that can produce an order.
    """
    offenders = _direct_offences(package, COMMENTARY_LAYER)
    assert not offenders, (
        "the decision path imports the commentary layer, which reopens a route "
        "from model output to an order:\n" + "\n".join(offenders)
    )


def test_commentary_layer_passes_no_tools_to_the_model() -> None:
    """
    The model must be able to emit text and nothing else. A ``tools=`` argument
    would give it the ability to act, which is exactly what demoting it was
    meant to remove.
    """
    source = (SRC / "llm" / "commentary.py").read_text(encoding="utf-8")
    offenders = _tool_grants(source)
    assert not offenders, "commentary must not pass tools to the model:\n" + "\n".join(
        offenders
    )


def test_the_programme_cannot_reach_an_order() -> None:
    """
    The reverse boundary.

    ``src/programme`` is the only package permitted a model client, so it is
    the only one that must be unable to place an order. Without this the
    arrangement is merely a convention: nothing would stop a future tick from
    importing ``AlpacaBroker`` to "check something", and the separation that
    justifies the model client's existence would be gone with one import.

    Walked rather than read a file at a time, because the indirect route is
    short: ``src/engine/__init__.py`` loads the driver, and the driver loads
    ``src.execution``. A programme module reaching for
    ``src.engine.statistics`` would bring the execution package with it while
    naming neither.
    """
    graph = _real_graph()
    starts = _package_modules(graph, MODEL_HOLDING_PACKAGE)
    assert starts, "the scan found no modules in src/programme"
    offenders = _reachable_offences(graph, starts, ORDER_CAPABLE_MODULES)
    assert not offenders, (
        "the programme package can reach order-placing code, which removes the "
        "separation that lets it hold a model client at all:\n" + "\n".join(offenders)
    )


def test_shadow_mode_lives_in_the_worker_because_of_that_boundary() -> None:
    """
    The boundary above is why ``shadow_job`` is where it is.

    Shadow mode runs the shipped live decision path, so it must import
    ``src.worker.live_job``. The programme cannot, so it enqueues a
    ``shadow_decision`` job and the worker runs it. If someone later moves that
    module into ``src/programme`` to keep the programme's code together, the
    test above fails — and this one says why, so the fix is to move it back
    rather than to relax the rule.
    """
    assert (SRC / "worker" / "shadow_job.py").is_file(), (
        "src/worker/shadow_job.py is missing; shadow mode cannot live in "
        "src/programme because that package may not import the worker"
    )
    assert not (SRC / "programme" / "shadow_job.py").exists()


def test_the_api_does_not_import_the_programme_runner() -> None:
    """
    The API may read the programme's rows; it may not become the runner.

    ``src/api/routers/programme.py`` imports ``src.programme.repo``,
    ``.flags`` and ``.gates`` — queries, a switch and pure logic. Importing
    any of ``RUNNER_ONLY`` would pull a model client into the API process
    transitively, defeating the check above without ever naming
    ``anthropic``. This is why the switch lives in its own module rather than
    beside the loop that reads it.

    This check once compared ``node.module`` against that set. The module of
    ``from src.programme import tick`` is ``src.programme``, so the most
    natural way to write the import was the one spelling it could not see.
    ``panel`` was also missing from the set, though it imports ``client`` at
    module level.
    """
    offenders = _direct_offences("api", RUNNER_ONLY)
    assert not offenders, (
        "the API imports the programme runner, which drags a model client into "
        "the process that commands the worker:\n" + "\n".join(offenders)
    )


def test_the_programme_modules_the_api_imports_hold_no_client() -> None:
    """
    The transitive half of the rule above.

    A per-file scan reads one module's own import statements. That is enough
    for a direct ``import anthropic`` and not enough for an indirect one.
    ``src/api`` legitimately imports modules out of ``src/programme`` —
    ``repo``, ``flags``, ``gates``, ``models``, ``roles``, ``reports`` and
    ``scorecard`` — and if any of *those* grew an SDK import, the API process
    would hold a model client while no file in ``src/api`` named it.

    So the closure is walked rather than one level of it. This found a real
    hole when it was written: ``src/api/routers/programme.py`` imports
    ``src.programme.roles`` for the role vocabulary the findings page renders,
    and ``roles`` imported ``src.programme.client`` at module level — so the API
    reached a model client through two hops while every check above passed.
    ``assess`` now lives in ``panel.py``, which nothing in ``src/api`` imports.

    It is also why the model catalogue is a module of its own rather than a few
    constants in ``client.py``, and why the Jev base URL will live in
    ``jev_catalogue.py`` rather than in ``jev_client.py``: the API needs the
    vocabulary, and the only safe way to share a vocabulary with a package that
    holds an SDK is to put it somewhere the SDK is forbidden.

    The first version of this walk was a hand-rolled frontier over
    ``src/programme`` alone: it resolved ``from src.programme import x`` by
    name, did not follow a package ``__init__``, relative imports or anything
    outside that one directory. It now uses the same graph as every other
    closure here, from every module of ``src/api`` and every entry point that
    serves it.
    """
    graph = _real_graph()
    starts = _package_modules(graph, "api")
    reached = _walk(graph, starts)
    programme = [m for m in reached if _matches(m, (f"src.{MODEL_HOLDING_PACKAGE}",))]
    assert programme, "the scan found no src.programme imports in src/api at all"
    offenders = _reachable_offences(graph, starts, FORBIDDEN_PREFIXES + RUNNER_ONLY)
    assert not offenders, (
        "src/api reaches an LLM client through src.programme:\n"
        + "\n".join(offenders)
        + "\n\nEvery module in that chain is loaded by the API process. Move "
        "the vocabulary the API needs into a module that holds no client, as "
        "src/programme/models.py does."
    )


@pytest.mark.parametrize("package", PROTECTED_PACKAGES)
def test_nothing_that_can_move_money_reaches_a_model_transitively(package: str) -> None:
    """
    The per-file checks above, over the whole closure of every protected module.

    Each of them reads one file. Every one of their prohibitions can be walked
    around by one intermediate module — a helper in ``src/db`` that imported
    ``src.llm``, a package ``__init__`` that imported the runner — and the
    direct check would stay green because the file it reads did not change.
    """
    graph = _real_graph()
    starts = _package_modules(graph, package)
    assert starts, f"the scan found no modules in src/{package}"
    forbidden = FORBIDDEN_PREFIXES + COMMENTARY_LAYER + LEGACY_AGENTS + RUNNER_ONLY
    offenders = _reachable_offences(graph, starts, forbidden)
    assert not offenders, (
        f"src/{package} reaches a model client, the commentary layer or the "
        "programme runner through an intermediate module:\n" + "\n".join(offenders)
    )


@pytest.mark.parametrize("package", (*DECISION_PATH, "worker"))
def test_the_order_path_cannot_reach_the_programme_at_all(package: str) -> None:
    """
    The decision path and the worker may not load any of ``src/programme``.

    ``src/api`` may, and the tests above hold it to the modules that carry no
    client. The worker and the decision path have no such need, and the
    allowance is zero rather than "the pure modules" because a pure module is
    one import away from not being one — the API has already had to find that
    out once, through ``roles``.

    Shadow mode is the case in point. It is programme work that runs in the
    worker, and it does so by importing nothing from the programme: the
    programme enqueues a row and the worker reads it. If the worker ever needs
    something from ``src/programme``, the fix is to move that thing out of it.
    """
    graph = _real_graph()
    starts = _package_modules(graph, package)
    assert starts, f"the scan found no modules in src/{package}"
    offenders = _reachable_offences(graph, starts, (f"src.{MODEL_HOLDING_PACKAGE}",))
    assert not offenders, f"src/{package} loads the AI programme's code:\n" + "\n".join(
        offenders
    )


def test_nothing_guarded_imports_by_a_computed_name() -> None:
    """
    Every check above reads import statements, and one call hides an import
    from all of them: ``importlib.import_module(name)``. A literal name is read
    as an import (see ``_imported_names``); a computed one cannot be read at
    all, so it is refused anywhere a protected process or the programme can
    reach.
    """
    graph = _real_graph()
    starts = [
        m
        for p in (*PROTECTED_PACKAGES, MODEL_HOLDING_PACKAGE)
        for m in _package_modules(graph, p)
    ]
    offenders = [
        f"{module}: {call}"
        for module in sorted(_walk(graph, starts))
        for call in _computed_imports(graph.sources[module])
    ]
    assert not offenders, (
        "an import by a computed name is invisible to every boundary in this "
        "file:\n" + "\n".join(offenders)
    )


def test_the_model_client_passes_no_tools() -> None:
    """
    The programme's model may emit text and nothing else.

    ``commentary.py`` is checked above for the same thing. ``client.py``
    assembles its request as a dict so that ``output_config`` can be omitted
    for a model with no effort parameter, so a keyword-only scan would not see
    ``request["tools"] = ...`` — and "the model cannot call a function" is the
    guarantee that makes a model client acceptable in this system at all.
    """
    source = (SRC / MODEL_HOLDING_PACKAGE / "client.py").read_text(encoding="utf-8")
    offenders = _tool_grants(source)
    assert not offenders, (
        "src/programme/client.py names a tool-granting request field, which "
        "would give the model the ability to act rather than only to write "
        "text:\n" + "\n".join(offenders)
    )


def test_every_module_holding_a_model_client_passes_no_tools() -> None:
    """
    The two tests above name their files, and the next client will be a third.

    So the rule is read off the code rather than off a list: any module that
    imports a model SDK is a client, and no client may name a tool-granting
    field. ``jev_client.py`` is covered the day it is written.
    """
    graph = _real_graph()
    holders = sorted(
        m for m, names in graph.names.items() if _offending(names, FORBIDDEN_PREFIXES)
    )
    assert {"src.llm.commentary", "src.programme.client"} <= set(holders), holders
    offenders = [
        f"{module}: {grant}"
        for module in holders
        for grant in _tool_grants(graph.sources[module])
    ]
    assert not offenders, (
        "a module holding a model client names a tool-granting field:\n"
        + "\n".join(offenders)
    )


def test_only_the_jev_modules_spell_the_typesafe_endpoint() -> None:
    """
    Every other check here is about imports, and a model can be reached
    without one. ``aiohttp`` is already installed in the worker's image for the
    Alpaca adapter, and ``session.post("https://api.typesafe.ai/v1/systemone")``
    would put a model's answer inside the process that submits orders with
    every import scan green.

    So the endpoint is a string with two permitted homes: the catalogue, which
    holds the base URL as data the API may display, and the client, which is
    the one thing that calls it. ``web/src`` is scanned too, because a call
    from the browser needs the key in the browser.
    """
    files = _product_files(*PRODUCT_TREES)
    relatives = {p.relative_to(ROOT).as_posix() for p in files}
    assert "src/api/main.py" in relatives and "web/src/lib/api.ts" in relatives, (
        "the scan did not find the product trees it is meant to read"
    )
    offenders = [
        f"{path.relative_to(ROOT).as_posix()}: {marker}"
        for path in files
        for marker in _endpoint_mentions(
            path.relative_to(ROOT).as_posix(), path.read_bytes()
        )
    ]
    assert not offenders, (
        "the TypeSafe endpoint is spelled outside src/programme/jev_catalogue.py "
        "and src/programme/jev_client.py — a route to the model that no import "
        "check can see:\n" + "\n".join(offenders)
    )


def test_strategies_do_not_perform_io() -> None:
    """
    Strategies must be pure. An HTTP call or a DB read inside
    ``target_weights`` would make the backtest unreproducible and the parity
    test meaningless.

    Walked rather than read a file at a time: a strategy importing a helper
    that opened a socket is exactly as impure as one that opened it itself.
    """
    graph = _real_graph()
    starts = _package_modules(graph, "strategies")
    offenders = _reachable_offences(graph, starts, STRATEGY_IO)
    assert not offenders, "strategies must not perform I/O:\n" + "\n".join(offenders)


def test_core_does_not_depend_on_execution_or_engine() -> None:
    """
    Dependency direction: engine -> core, never core -> engine. Keeps the
    value types importable by anything without dragging in a broker.

    This was a text search for three strings, so ``from src import engine``
    passed it and a docstring explaining the rule would have failed it.
    """
    graph = _real_graph()
    starts = _package_modules(graph, "core")
    offenders = _reachable_offences(graph, starts, CORE_MUST_NOT_REACH)
    assert not offenders, "core must not depend on engine/execution:\n" + "\n".join(
        offenders
    )
