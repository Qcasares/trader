"""
test_dependency_sources_agree.py
--------------------------------
That ``pyproject.toml`` and ``requirements.txt`` describe the same application.

Two files list this project's runtime dependencies because two build systems
read different ones, and neither offers a way to point at the other:

    Docker, CI      ->  requirements.txt
    Vercel          ->  pyproject.toml   [project.dependencies]

Vercel's Python builder prefers ``pyproject.toml`` whenever one exists and
ignores ``requirements.txt`` entirely. The build log is explicit —
"Installing required dependencies from pyproject.toml..." — so a pyproject
declaring no dependencies installs nothing, the build still *succeeds*, and
every request dies at import with ``ModuleNotFoundError: No module named
'asyncpg'``.

That is not hypothetical either. It is what the first live deployment did:
built cleanly, deployed, returned 500 to everything, and the only clue was in
the runtime log rather than the build. A green build proving nothing about
whether the application can import itself is exactly the kind of gap this
file exists to close.

Duplication is the cost of the two builders disagreeing. Silent divergence is
not, so it is checked here instead of remembered.
"""

from __future__ import annotations

import pathlib
import re
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "pyproject.toml"
REQUIREMENTS = ROOT / "requirements.txt"

#: Strip extras and version specifiers: "uvicorn[standard]>=0.30.0" -> "uvicorn"
_NAME = re.compile(r"^([A-Za-z0-9._-]+)")


def _normalise(spec: str) -> str:
    match = _NAME.match(spec.strip())
    assert match, f"cannot parse dependency {spec!r}"
    # PEP 503: distribution names compare case-insensitively with - _ . equal.
    return re.sub(r"[-_.]+", "-", match.group(1)).lower()


def _from_pyproject() -> set[str]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return {_normalise(d) for d in data["project"]["dependencies"]}


def _from_requirements() -> set[str]:
    names: set[str] = set()
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        names.add(_normalise(line))
    return names


class TestBothSourcesAgree:
    def test_neither_source_is_empty(self) -> None:
        # Guards the guard. An empty pyproject list is the precise bug this
        # file exists to prevent, and it would otherwise make every set
        # comparison below pass trivially.
        assert len(_from_pyproject()) >= 10, _from_pyproject()
        assert len(_from_requirements()) >= 10, _from_requirements()

    def test_pyproject_is_not_missing_anything(self) -> None:
        missing = _from_requirements() - _from_pyproject()
        assert not missing, (
            f"pyproject.toml is missing {sorted(missing)}. Vercel installs from "
            "this file and ignores requirements.txt, so anything absent here is "
            "absent at runtime — a build that succeeds and a function that "
            "cannot import itself."
        )

    def test_requirements_is_not_missing_anything(self) -> None:
        missing = _from_pyproject() - _from_requirements()
        assert not missing, (
            f"requirements.txt is missing {sorted(missing)}. Docker and CI "
            "install from that file, so the container would lack what Vercel "
            "has — and CI would stop testing what deploys."
        )

    def test_asyncpg_is_in_both(self) -> None:
        """
        The specific package whose absence took down the first deployment.
        Named explicitly so the regression has a test of its own rather than
        only a set comparison.
        """
        assert "asyncpg" in _from_pyproject()
        assert "asyncpg" in _from_requirements()


class TestTheRuntimeSetStaysDeployable:
    def test_no_test_tooling_leaked_into_the_runtime_set(self) -> None:
        """
        Both files are the *deployable* set. pytest and Jupyter belong in
        requirements-dev.txt: in a serverless bundle they would spend a large
        part of a 250MB limit on things no request imports.
        """
        dev_only = {"pytest", "pytest-asyncio", "pytest-cov", "httpx", "ipython",
                    "jupyter", "playwright"}
        for label, names in (
            ("pyproject.toml", _from_pyproject()),
            ("requirements.txt", _from_requirements()),
        ):
            leaked = dev_only & names
            assert not leaked, f"{label} carries dev-only packages: {sorted(leaked)}"

    def test_no_llm_sdk_in_either(self) -> None:
        """
        `anthropic` is deliberately absent from both. The engine must run, and
        be testable, with no LLM library present; src/llm/commentary.py imports
        it lazily and returns None without it.
        """
        both = _from_pyproject() | _from_requirements()
        assert "anthropic" not in both
        assert not {"openai", "transformers", "torch"} & both
