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

#: The decision and execution path.
PROTECTED_PACKAGES = ("core", "strategies", "engine", "execution", "data")


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
