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
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"

#: Packages that must never appear anywhere in the decision or execution path.
FORBIDDEN_PREFIXES = ("anthropic", "openai", "transformers", "nltk", "torch")

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


def _module_files(package: str) -> list[Path]:
    root = SRC / package
    return sorted(root.rglob("*.py")) if root.is_dir() else []


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
    return roots


@pytest.mark.parametrize("package", PROTECTED_PACKAGES)
def test_decision_path_never_imports_an_llm(package: str) -> None:
    """No LLM client may be reachable from code that can move money."""
    offenders: list[str] = []
    for path in _module_files(package):
        for root in _imported_roots(path):
            if root in FORBIDDEN_PREFIXES:
                offenders.append(f"{path.relative_to(SRC)} imports {root}")
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
    """
    offenders: list[str] = []
    for path in _module_files(package):
        # Parse imports rather than grepping the text: a docstring that
        # *mentions* src.agents (as core/__init__.py does, to explain the
        # boundary) is documentation, not a dependency.
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
            elif isinstance(node, ast.Import):
                module = ",".join(a.name for a in node.names)
            if "src.agents" in module or module.startswith("agents"):
                offenders.append(f"{path.relative_to(SRC)} imports {module}")
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
    offenders: list[str] = []
    for path in _module_files(package):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
            elif isinstance(node, ast.Import):
                module = ",".join(a.name for a in node.names)
            if "src.llm" in module:
                offenders.append(f"{path.relative_to(SRC)} imports {module}")
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
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                assert keyword.arg not in {"tools", "tool_choice"}, (
                    "commentary must not pass tools to the model"
                )


def test_the_programme_cannot_reach_an_order() -> None:
    """
    The reverse boundary.

    ``src/programme`` is the only package permitted a model client, so it is
    the only one that must be unable to place an order. Without this the
    arrangement is merely a convention: nothing would stop a future tick from
    importing ``AlpacaBroker`` to "check something", and the separation that
    justifies the model client's existence would be gone with one import.
    """
    offenders: list[str] = []
    for path in _module_files(MODEL_HOLDING_PACKAGE):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
            elif isinstance(node, ast.Import):
                module = ",".join(a.name for a in node.names)
            for forbidden in ORDER_CAPABLE_MODULES:
                if module == forbidden or module.startswith(f"{forbidden}."):
                    offenders.append(f"{path.relative_to(SRC)} imports {module}")
    assert not offenders, (
        "the programme package can reach order-placing code, which removes the "
        "separation that lets it hold a model client at all:\n"
        + "\n".join(offenders)
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
    ``.tick``, ``.author``, ``.client`` or ``.main`` would pull the model
    client into the API process transitively, defeating the check above without
    ever naming ``anthropic``. This is why the switch lives in its own module
    rather than beside the loop that reads it.
    """
    runner_only = {
        "src.programme.tick",
        "src.programme.author",
        "src.programme.client",
        "src.programme.main",
    }
    offenders: list[str] = []
    for path in _module_files("api"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
            elif isinstance(node, ast.Import):
                module = ",".join(a.name for a in node.names)
            if module in runner_only:
                offenders.append(f"{path.relative_to(SRC)} imports {module}")
    assert not offenders, (
        "the API imports the programme runner, which drags a model client into "
        "the process that commands the worker:\n" + "\n".join(offenders)
    )


def test_the_programme_modules_the_api_imports_hold_no_client() -> None:
    """
    The transitive half of the rule above.

    Every scan in this file is per-file: it reads one module's own import
    statements. That is enough for a direct ``import anthropic`` and not enough
    for an indirect one. ``src/api`` legitimately imports four modules out of
    ``src/programme`` — ``repo``, ``flags``, ``gates`` and ``models`` — and if
    any of *those* grew an SDK import, the API process would hold a model client
    and every test above would still pass, because no file in ``src/api`` would
    name it.

    So the closure is walked rather than one level of it. This found a real
    hole when it was written: ``src/api/routers/programme.py`` imports
    ``src.programme.roles`` for the role vocabulary the findings page renders,
    and ``roles`` imported ``src.programme.client`` at module level — so the API
    reached a model client through two hops while every check above passed.
    ``roles`` now imports it inside ``assess``, where only the caller that needs
    it pays for it.

    It is also why the model catalogue is a module of its own rather than a few
    constants in ``client.py``: the API needs that vocabulary to draw the
    selector and to validate what comes back from it, and the only safe way to
    share a vocabulary with a package that holds an SDK is to put it somewhere
    the SDK is forbidden.
    """
    frontier: list[str] = []
    for path in _module_files("api"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module == f"src.{MODEL_HOLDING_PACKAGE}":
                    frontier.extend(a.name for a in node.names)
                elif node.module.startswith(f"src.{MODEL_HOLDING_PACKAGE}."):
                    frontier.append(node.module.split(".")[2])

    seen: set[str] = set()
    offenders: list[str] = []
    while frontier:
        name = frontier.pop()
        if name in seen:
            continue
        seen.add(name)
        path = SRC / MODEL_HOLDING_PACKAGE / f"{name}.py"
        if not path.is_file():  # pragma: no cover - not a module of its own
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            # `ast.walk` reaches function bodies, so a lazily imported SDK is
            # caught here as readily as a top-level one. That is deliberate: an
            # import one function call away is still a capability this process
            # holds.
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for module in names:
                if module.split(".")[0] in FORBIDDEN_PREFIXES:
                    offenders.append(f"{path.relative_to(SRC)} imports {module}")
                elif module.startswith(f"src.{MODEL_HOLDING_PACKAGE}."):
                    frontier.append(module.split(".")[2])

    assert seen, "the scan found no src.programme imports in src/api at all"
    assert not offenders, (
        "src/api reaches an LLM client through src.programme:\n"
        + "\n".join(sorted(set(offenders)))
        + "\n\nEvery module in that chain is loaded by the API process. Move "
        "the vocabulary the API needs into a module that holds no client, as "
        "src/programme/models.py does."
    )


def test_the_model_client_passes_no_tools() -> None:
    """
    The programme's model may emit text and nothing else.

    ``commentary.py`` is checked two tests up for a ``tools=`` keyword.
    ``client.py`` needs its own check and a wider one, because it no longer
    passes keyword arguments: the request is assembled as a dict so that
    ``output_config`` can be omitted for a model with no effort parameter. A
    keyword-only scan would not see ``request["tools"] = ...``, and "the model
    cannot call a function" is the guarantee that makes a model client
    acceptable in this system at all.
    """
    forbidden = {"tools", "tool_choice"}
    source = (SRC / MODEL_HOLDING_PACKAGE / "client.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg in forbidden:
                    offenders.append(f"keyword {keyword.arg}=")
        elif isinstance(node, ast.Constant) and node.value in forbidden:
            # Covers `request["tools"] = ...` and `{"tools": [...]}` alike: in
            # a module this small, the string appearing at all is the signal.
            offenders.append(f"string literal {node.value!r}")
    assert not offenders, (
        "src/programme/client.py names a tool-granting request field, which "
        "would give the model the ability to act rather than only to write "
        "text:\n" + "\n".join(offenders)
    )


def test_strategies_do_not_perform_io() -> None:
    """
    Strategies must be pure. An HTTP call or a DB read inside
    ``target_weights`` would make the backtest unreproducible and the parity
    test meaningless.
    """
    io_roots = {"aiohttp", "requests", "httpx", "asyncpg", "socket", "urllib"}
    offenders: list[str] = []
    for path in _module_files("strategies"):
        for root in _imported_roots(path):
            if root in io_roots:
                offenders.append(f"{path.relative_to(SRC)} imports {root}")
    assert not offenders, "strategies must not perform I/O:\n" + "\n".join(offenders)


def test_core_does_not_depend_on_execution_or_engine() -> None:
    """
    Dependency direction: engine -> core, never core -> engine. Keeps the
    value types importable by anything without dragging in a broker.
    """
    offenders: list[str] = []
    for path in _module_files("core"):
        text = path.read_text(encoding="utf-8")
        for forbidden in ("from src.engine", "from src.execution", "import src.engine"):
            if forbidden in text:
                offenders.append(f"{path.relative_to(SRC)}: {forbidden}")
    assert not offenders, "core must not depend on engine/execution:\n" + "\n".join(
        offenders
    )
