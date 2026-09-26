"""
test_dependency_boundaries.py
-----------------------------
That a model SDK is installed only where it may be imported, and only from
where it should come.

``tests/unit/test_import_boundaries.py`` forbids the API, the worker and the
decision path from importing a model client. That is a rule about source, and
it holds exactly as long as nobody writes the import. CLAUDE.md claims a second
half — "two images rather than one, so the boundary holds at runtime as well as
in review: the worker container could not import an LLM client if its code
tried" — and until this file only two places of that claim were checked:
``test_dependency_sources_agree`` reads requirements.txt and pyproject.toml.
Nothing read requirements-dev.txt, the shared Dockerfile, the compose file, or
``worker.yml`` — which is not a test harness but the worker itself, running on
a GitHub runner with the broker credentials. Any of them could have installed
``anthropic`` beside those credentials with every test green.

The second concern is supply chain. TypeSafe AI's official Python SDK is
``typesafe-sdk`` on PyPI, and lookalikes exist under names a hurried reader
would accept: ``typesafe-ai`` on PyPI, a third party's shim, and an npm
package called ``typesafe-sdk`` that TypeSafe did not publish. The real SDK
will be installed into the one process that holds a model credential, which
makes it the most valuable name in this repository to typosquat. So the name
is pinned exactly, the index is PyPI's, and the hosts a lookalike serves from
appear nowhere.

Not every refused name is a lookalike. ``cooksafe`` is TypeSafe's own cookbook
helper, published from ``typesafe-ai/CookSafe``, and ``@typesafe-ai/sdk`` is
TypeSafe's own npm SDK. Both are refused regardless: the deployable sets and
the frontend must hold no TypeSafe client code at all, genuine or not, and the
programme — the one process allowed a client — is allowed the SDK and nothing
beside it. ``cooksafe`` names no licence on PyPI and its source is private.

The files are parsed rather than grepped — requirement names to PEP 508 and
PEP 503, ``-r`` includes followed, ``pip install`` lines read from Dockerfiles
and workflows — and every parser is tested against synthetic lines first. A
parser that read nothing would pass every prohibition below.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import tomllib
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROGRAMME_REQUIREMENTS = ROOT / "requirements-programme.txt"
DEPLOYABLE_REQUIREMENTS = ("requirements.txt", "requirements-dev.txt")
PROGRAMME_DOCKERFILE = ROOT / "Dockerfile.programme"
PROGRAMME_WORKFLOW = ROOT / ".github" / "workflows" / "programme.yml"
PYPROJECT = ROOT / "pyproject.toml"
COMPOSE = ROOT / "docker-compose.yml"

SKIPPED_DIRECTORIES = frozenset(
    {
        ".git",
        ".venv",
        "node_modules",
        ".next",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
    }
)

#: Distributions that are, or exist to carry, a model client (PEP 503 names).
#:
#: The distribution-name twin of ``FORBIDDEN_PREFIXES`` in the import test:
#: what may not be imported by the API and the worker should not be installed
#: in their images either.
#:
#: ``httpx2`` is deliberately absent, although it is ``typesafe-sdk``'s
#: transport. It is a general-purpose HTTP client, like the ``aiohttp`` the
#: worker already holds for the Alpaca adapter, and starlette's TestClient now
#: warns, wherever it is imported without it, that ``httpx`` is deprecated and
#: ``httpx2`` wanted instead. Listing it here would refuse that migration in
#: requirements-dev.txt and ``ci.yml`` while refusing no model: an HTTP client
#: is not a model client until it is pointed at a vendor, and pointing one is
#: what ``test_nothing_that_can_move_money_names_a_model_vendor_host`` in the
#: import test catches.
MODEL_SDKS = frozenset(
    {
        "anthropic",
        "openai",
        "transformers",
        "torch",
        "nltk",
        "typesafe-sdk",
        "typesafe-ai",
        "cooksafe",
        "litellm",
        "langchain",
        "langchain-core",
        "langchain-community",
        "langchain-openai",
        "langchain-anthropic",
        "llama-index",
        "cohere",
        "mistralai",
        "groq",
        "ollama",
        "google-generativeai",
        "google-genai",
        "google-cloud-aiplatform",
    }
)

#: TypeSafe's official Python SDK, and the one TypeSafe name that may appear.
TYPESAFE_SDK = "typesafe-sdk"

#: PyPI. ``--index-url`` naming it is redundant rather than a change.
DEFAULT_INDEX = "https://pypi.org/simple"

#: The same source changes, spelled as configuration pip and uv read.
SOURCE_VARIABLES = (
    "PIP_INDEX_URL",
    "PIP_EXTRA_INDEX_URL",
    "PIP_FIND_LINKS",
    "PIP_TRUSTED_HOST",
    "PIP_NO_INDEX",
    "UV_INDEX",
    "UV_DEFAULT_INDEX",
    "UV_EXTRA_INDEX_URL",
    "UV_FIND_LINKS",
)
SOURCE_CONFIG_FILES = frozenset({"pip.conf", "pip.ini", "uv.toml"})

#: Every lookalike host docs/08-jev-integration.md names in fact 9: the
#: resellers that put a third party in the data path and the payment path, the
#: two sites that invite a user to paste a real TypeSafe key, and the index a
#: third party claims once served the SDK. The doc says none of them appears in
#: anything that ships, and ``test_every_host_the_doc_names_is_scanned`` holds
#: this list to the doc, because the two drifted apart once already.
LOOKALIKE_HOSTS = (
    "jevtypesafeai.com",
    "jev-api.com",
    "thejevai.com",
    "jevmodel.org",
    "jev-ai.pro",
    "jev.works",
    "jev.guru",
    "pypi.typesafe.ai",
)

#: Hostnames fact 9 names that are not lookalikes: TypeSafe's own domain, and
#: the historic, unrelated Typesafe Inc.
NOT_LOOKALIKES = frozenset({"typesafe.ai", "typesafe.com"})

LOOKALIKE_DOC = ROOT / "docs" / "08-jev-integration.md"


# ---------------------------------------------------------------------------
# Reading requirements as pip reads them
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Line:
    """One logical requirements line: a named requirement, a reference, or an option."""

    name: str | None = None
    reference: str | None = None
    option: str | None = None
    value: str | None = None


@dataclass(frozen=True)
class Entry:
    where: str
    line: Line


#: pip's own comment rule: ``#`` at the start of a line or after whitespace, so
#: the ``#egg=`` fragment of a URL survives.
_COMMENT = re.compile(r"(^|\s+)#.*$")

#: A PEP 508 name, then extras, a version, a marker, ``@ url`` — or nothing.
_REQUIREMENT = re.compile(
    r"(?P<name>[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)\s*"
    r"(?P<rest>(?:[\[(;<>=!~@].*)?)"
)
_ARCHIVES = (".whl", ".tar.gz", ".tgz", ".tar.bz2", ".zip")

_SHORT_OPTIONS = {
    "-r": "--requirement",
    "-c": "--constraint",
    "-i": "--index-url",
    "-f": "--find-links",
    "-e": "--editable",
}
_INCLUDES = frozenset({"--requirement", "--constraint"})

#: ``pip install`` options that consume the next token, so it is not read as
#: a package name.
_VALUE_OPTIONS = frozenset(
    {
        *_SHORT_OPTIONS.values(),
        "--extra-index-url",
        "--trusted-host",
        "--target",
        "-t",
        "--prefix",
        "--root",
        "--cache-dir",
        "--python-version",
        "--platform",
        "--implementation",
        "--abi",
        "--progress-bar",
        "--upgrade-strategy",
        "--only-binary",
        "--no-binary",
        "--config-settings",
        "-C",
        "--src",
        "--report",
        "--log",
        "--hash",
        "--proxy",
        "--cert",
        "--timeout",
        "--retries",
        "--exists-action",
        "--python",
        "--root-user-action",
    }
)


def _normalise(name: str) -> str:
    """PEP 503: case-insensitive, with runs of ``-``, ``_`` and ``.`` equal."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _parse_requirement(text: str) -> Line:
    text = text.strip()
    match = _REQUIREMENT.fullmatch(text)
    if match is None or (not match["rest"] and text.lower().endswith(_ARCHIVES)):
        # A URL, a path or an archive: fetched from wherever it points.
        return Line(reference=text)
    rest = re.sub(r"^\[[^\]]*\]\s*", "", match["rest"])
    reference = rest[1:].split(";")[0].strip() if rest.startswith("@") else None
    return Line(name=_normalise(match["name"]), reference=reference)


def _option_line(option: str, value: str | None) -> Line:
    option = _SHORT_OPTIONS.get(option, option)
    if option == "--editable" and value is not None:
        egg = re.search(r"[#&]egg=([A-Za-z0-9._-]+)", value)
        return Line(
            name=_normalise(egg[1]) if egg else None,
            reference=value,
            option=option,
            value=value,
        )
    return Line(option=option, value=value)


def _split_option(token: str) -> tuple[str, str | None]:
    """``--index-url=x`` and ``-ix`` carry their value; ``--index-url`` does not."""
    if token.startswith("--") and "=" in token:
        option, value = token.split("=", 1)
        return option, value
    if not token.startswith("--") and len(token) > 2 and token[:2] in _SHORT_OPTIONS:
        return token[:2], token[2:]
    return token, None


def _parse_line(text: str) -> Line | None:
    """One logical requirements line, or None if pip would ignore it."""
    text = _COMMENT.sub("", text).strip()
    if not text:
        return None
    if text.startswith("-"):
        tokens = shlex.split(text)
        option, value = _split_option(tokens[0])
        if value is None and len(tokens) > 1:
            value = tokens[1]
        return _option_line(option, value)
    # pip's break_args_options: the requirement ends at the first token that
    # is an option, such as a per-requirement ``--hash=...``.
    words: list[str] = []
    for word in text.split(" "):
        if word.startswith("-"):
            break
        words.append(word)
    return _parse_requirement(" ".join(words))


def _logical_lines(text: str) -> Iterator[tuple[int, str]]:
    """pip's join_lines: a trailing backslash continues a line, but not a comment."""
    pending: list[str] = []
    first = 0
    for number, raw in enumerate(text.splitlines(), start=1):
        if raw.endswith("\\") and not _COMMENT.match(raw):
            if not pending:
                first = number
            pending.append(raw[:-1])
            continue
        if _COMMENT.match(raw):
            raw = f" {raw}"
        if pending:
            yield first, "".join([*pending, raw])
            pending = []
        else:
            yield number, raw
    if pending:
        yield first, "".join(pending)


def _label(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def _include(base: Path, entry: Entry, seen: frozenset[Path]) -> list[Entry]:
    target = base / (entry.line.value or "")
    assert target.is_file(), (
        f"{entry.where} includes {entry.line.value!r}, which does not exist. An "
        "include that cannot be read is an install that cannot be checked."
    )
    return _read(target, _seen=seen)


def _read(
    path: Path, *, follow: bool = True, _seen: frozenset[Path] = frozenset()
) -> list[Entry]:
    """Every line of a requirements file and, unless told not to, of its includes."""
    path = path.resolve()
    if path in _seen:
        return []
    entries: list[Entry] = []
    for number, raw in _logical_lines(path.read_text(encoding="utf-8")):
        line = _parse_line(raw)
        if line is None:
            continue
        entry = Entry(f"{_label(path)}:{number}", line)
        entries.append(entry)
        if follow and line.option in _INCLUDES:
            entries.extend(_include(path.parent, entry, _seen | {path}))
    return entries


def _pyproject_entries() -> list[Entry]:
    """Every dependency ``pyproject.toml`` declares. Vercel installs from it."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    project = data.get("project", {})
    specs = list(project.get("dependencies", []))
    for group in project.get("optional-dependencies", {}).values():
        specs.extend(group)
    for group in data.get("dependency-groups", {}).values():
        specs.extend(s for s in group if isinstance(s, str))
    lines = (_parse_line(spec) for spec in specs)
    return [Entry("pyproject.toml", line) for line in lines if line is not None]


# ---------------------------------------------------------------------------
# Reading `pip install` out of Dockerfiles and workflows
# ---------------------------------------------------------------------------

_PIP_INSTALL = re.compile(r"\bpip3?\s+install\b(?P<args>.*)")
_SHELL_BREAK = re.compile(r"&&|\|\||[;|]")


def _pip_installs(text: str) -> list[list[str]]:
    """The arguments of every ``pip install`` in a Dockerfile or a workflow."""
    installs: list[list[str]] = []
    for raw in re.sub(r"\\\n", " ", text).splitlines():
        if raw.lstrip().startswith("#"):
            continue
        for segment in _SHELL_BREAK.split(raw):
            match = _PIP_INSTALL.search(segment)
            if match is None:
                continue
            try:
                installs.append(shlex.split(match["args"], comments=True))
            except ValueError:
                installs.append(match["args"].split())
    return installs


def _install_lines(tokens: Sequence[str]) -> list[Line]:
    """A ``pip install`` command, as the requirements lines it amounts to."""
    lines: list[Line] = []
    queue = list(tokens)
    while queue:
        token = queue.pop(0)
        if not token.startswith("-"):
            lines.append(_parse_requirement(token))
            continue
        option, value = _split_option(token)
        option = _SHORT_OPTIONS.get(option, option)
        if value is None and option in _VALUE_OPTIONS and queue:
            value = queue.pop(0)
        lines.append(_option_line(option, value))
    return lines


def _installed_by(path: Path) -> list[Entry]:
    """What a Dockerfile or workflow installs, with its ``-r`` files followed.

    Both run from the repository root — a workflow's checkout, the image's
    ``COPY`` of the same file names — so includes resolve against it.
    """
    entries: list[Entry] = []
    for tokens in _pip_installs(path.read_text(encoding="utf-8")):
        for line in _install_lines(tokens):
            entry = Entry(f"{_label(path)}: pip install", line)
            entries.append(entry)
            if line.option in _INCLUDES:
                entries.extend(_include(ROOT, entry, frozenset()))
    return entries


def _uncommented(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


# ---------------------------------------------------------------------------
# The rules, as functions the synthetic tests can reach
# ---------------------------------------------------------------------------


def _is_foreign_source(line: Line) -> bool:
    """Whether a line makes pip fetch from somewhere other than PyPI."""
    if line.option in {"--extra-index-url", "--find-links", "--trusted-host"}:
        return True
    if line.option == "--no-index":
        return True
    if line.option == "--index-url":
        return (line.value or "").rstrip("/") != DEFAULT_INDEX
    # The project itself (``pip install .``, ``-e .``) is the one local path
    # that is not a package source.
    return line.reference is not None and line.reference.rstrip("/") not in {"", "."}


def _claims_to_be_typesafe(name: str) -> bool:
    """
    Whether a package name presents itself as TypeSafe AI's.

    Genuine or not: ``cooksafe`` and ``@typesafe-ai/sdk`` are TypeSafe's own
    and answer yes. The question is whether a name carries TypeSafe client
    code, and the callers refuse every one but ``typesafe-sdk`` in the
    programme's file.

    Deliberately not a substring test on ``typesafe``: ``typesafety`` on PyPI
    and ``typesafe-i18n`` on npm are real, unrelated libraries, and a rule that
    fires on them gets switched off.
    """
    lowered = name.lower()
    scope, _, bare = lowered.rpartition("/")
    bare = _normalise(bare)
    return (
        bare
        in {
            "typesafe",
            "typesafe-ai",
            "typesafeai",
            "typesafe-sdk",
            "typesafe-api",
            "typesafe-client",
            "jev",
            "jev-sdk",
            "jev-ai",
        }
        or any(m in lowered for m in ("cooksafe", "jevtypesafe", "systemone"))
        or scope.startswith(("@typesafe", "@jev"))
    )


def _installs_a_model_sdk(line: Line) -> bool:
    """Whether a requirement names a model SDK or anything presenting as TypeSafe's.

    The one predicate every "no model SDK here" rule below applies, so that the
    synthetic test which proves test tooling may install ``httpx2`` exercises
    the same judgement the rules over the real files make.
    """
    name = line.name
    return name is not None and (name in MODEL_SDKS or _claims_to_be_typesafe(name))


def _deployable_offenders(path: Path) -> list[str]:
    """What a deployable requirements file, or one it includes, must not install."""
    entries = _read(path)
    offenders = [
        f"{e.where}: {e.line.name}" for e in entries if _installs_a_model_sdk(e.line)
    ]
    offenders += [
        f"{e.where}: includes {e.line.value}"
        for e in entries
        if e.line.option in _INCLUDES
        and Path(e.line.value or "").name == PROGRAMME_REQUIREMENTS.name
    ]
    return offenders


def _workflow_offenders(path: Path) -> list[str]:
    """What a workflow other than programme.yml installs that it must not."""
    offenders = [
        f"{e.where}: {e.line.name}"
        for e in _installed_by(path)
        if _installs_a_model_sdk(e.line)
    ]
    if PROGRAMME_REQUIREMENTS.name in _uncommented(path.read_text(encoding="utf-8")):
        offenders.append(f"{_label(path)} names {PROGRAMME_REQUIREMENTS.name}")
    return offenders


#: A character that continues a hostname label. Beside a match it means the
#: text names some other host: ``notjev.works``, ``jev.worksheet``.
_HOST_CHARACTER = "[a-z0-9_-]"


def _host_pattern(host: str) -> re.Pattern[bytes]:
    """``host`` or a subdomain of it, but not the middle of a longer name."""
    c = _HOST_CHARACTER
    return re.compile(rf"(?<!{c}){re.escape(host)}(?!{c}|\.{c})".encode())


_LOOKALIKE_PATTERNS = {host: _host_pattern(host) for host in LOOKALIKE_HOSTS}

#: Brand tokens distinctive enough to match as plain substrings, under any
#: domain. ``jevtypesafeai`` names no word and no legitimate host, so matching
#: it anywhere costs no false positives and catches the same operator's site
#: moved to ``.net`` or ``.io`` — which the hostname list alone would not.
LOOKALIKE_TOKENS = ("jevtypesafeai",)


def _lookalike_hosts(data: bytes) -> list[str]:
    """
    Every lookalike host the bytes name, as itself or as any subdomain of it.

    Matched as a hostname, not a substring. Several of these are short enough
    to sit inside ordinary words — ``jev.works`` is the start of
    ``jev.worksheet`` — and a scan that fires on those gets switched off. So
    ``https://jev.works/key``, ``api.jev.works`` and ``key@jev.works`` name the
    site; ``notjev.works`` and ``jev.works.example`` are other domains.
    """
    lowered = data.lower()
    hosts = [
        host for host, pattern in _LOOKALIKE_PATTERNS.items() if pattern.search(lowered)
    ]
    tokens = [token for token in LOOKALIKE_TOKENS if token.encode() in lowered]
    return hosts + tokens


def _hosts_the_doc_names(path: Path) -> set[str]:
    """Every hostname in fact 9 of docs/08, the section the scan answers to."""
    text = path.read_text(encoding="utf-8")
    section = re.search(r"^### 9\. Lookalike.*?(?=^#{1,3} |\Z)", text, re.S | re.M)
    assert section, f"{_label(path)} has no '### 9. Lookalike' section"
    return {
        token.lower()
        for token in re.findall(r"`([^`\s]+)`", section[0])
        if re.fullmatch(r"(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}", token)
    }


def _npm_names(path: Path) -> set[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if path.name == "package-lock.json":
        names = {k.rpartition("node_modules/")[2] for k in data.get("packages", {})}
        names |= set(data.get("dependencies", {}))
        return names - {""}
    groups = ("dependencies", "devDependencies", "peerDependencies")
    return {n for g in (*groups, "optionalDependencies") for n in data.get(g, {})}


def _compose_services(text: str) -> dict[str, str]:
    """Each service's block, by indentation — pyyaml is not a dependency here."""
    section = re.search(r"^services:\n(.*?)(?=^\S|\Z)", text, re.S | re.M)
    assert section, "docker-compose.yml has no services section"
    return {
        match[1]: _uncommented(match[2])
        for match in re.finditer(
            r"^  ([\w-]+):\n(.*?)(?=^  [\w-]+:\n|\Z)", section[1], re.S | re.M
        )
    }


def _repository_files(keep: Callable[[Path], bool], *, tests: bool) -> list[Path]:
    found: list[Path] = []
    for directory, subdirectories, names in os.walk(ROOT):
        subdirectories[:] = sorted(
            d
            for d in subdirectories
            if d not in SKIPPED_DIRECTORIES
            and (tests or Path(directory, d) != ROOT / "tests")
        )
        found.extend(p for p in (Path(directory, n) for n in sorted(names)) if keep(p))
    return found


def _requirements_files() -> list[Path]:
    return _repository_files(
        lambda p: p.name.startswith("requirements") and p.suffix == ".txt",
        tests=True,
    )


def _dockerfiles() -> list[Path]:
    return _repository_files(lambda p: p.name.startswith("Dockerfile"), tests=False)


def _workflows() -> list[Path]:
    directory = ROOT / ".github" / "workflows"
    return sorted([*directory.glob("*.yml"), *directory.glob("*.yaml")])


# ---------------------------------------------------------------------------
# The parsers, tested against lines that must read a particular way
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("anthropic>=0.40.0", Line(name="anthropic")),
        ("Anthropic", Line(name="anthropic")),
        ("typesafe_sdk==1.2", Line(name="typesafe-sdk")),
        ("TypeSafe.SDK[async]>=1; python_version >= '3.11'", Line(name="typesafe-sdk")),
        ("typesafe_ai~=0.1", Line(name="typesafe-ai")),
        ("uvicorn[standard]>=0.30.0", Line(name="uvicorn")),
        ("exchange_calendars>=4.13.0", Line(name="exchange-calendars")),
        ("pkg (>=1.0)", Line(name="pkg")),
        ("  requests   # the Crypto.com adapter", Line(name="requests")),
        ("typesafe-sdk>=1 --hash=sha256:abc", Line(name="typesafe-sdk")),
        (
            "typesafe-sdk @ https://evil.example/typesafe_sdk-1-py3-none-any.whl",
            Line(
                name="typesafe-sdk",
                reference="https://evil.example/typesafe_sdk-1-py3-none-any.whl",
            ),
        ),
        (
            "typesafe-sdk[async]@https://evil.example/t.whl ; os_name == 'posix'",
            Line(name="typesafe-sdk", reference="https://evil.example/t.whl"),
        ),
        ("https://evil.example/t.whl", Line(reference="https://evil.example/t.whl")),
        (
            "./wheels/typesafe_sdk-1.0.whl",
            Line(reference="./wheels/typesafe_sdk-1.0.whl"),
        ),
        ("typesafe_sdk-1.0.tar.gz", Line(reference="typesafe_sdk-1.0.tar.gz")),
        ("# anthropic>=0.40.0", None),
        ("", None),
        ("-r requirements.txt", Line(option="--requirement", value="requirements.txt")),
        ("-rrequirements.txt", Line(option="--requirement", value="requirements.txt")),
        ("--requirement=base.txt", Line(option="--requirement", value="base.txt")),
        ("-c constraints.txt", Line(option="--constraint", value="constraints.txt")),
    ],
)
def test_the_requirement_parser_reads_a_line_as_pip_does(
    text: str, expected: Line | None
) -> None:
    """
    The existing reader in ``test_dependency_sources_agree`` stops at the first
    character outside ``[A-Za-z0-9._-]`` and skips every line starting with
    ``-``. That is right for the file it reads, and blind to a direct URL
    reference, an ``--extra-index-url`` or an include — the three ways a
    requirements file can install something its names do not show.
    """
    assert _parse_line(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "anthropic>=0.40.0",
        "Typesafe_SDK",
        "TypeSafe.SDK[async]>=1; python_version >= '3.11'",
        "typesafe-sdk @ https://example.com/t.whl",
        "typesafe_ai~=0.1",
        "pkg (>=1.0)",
        "uvicorn[standard]>=0.30.0",
        "exchange_calendars>=4.13.0",
    ],
)
def test_the_requirement_parser_agrees_with_packaging(text: str) -> None:
    """
    ``packaging`` is the reference implementation of PEP 508 and 503. It is
    not a dependency of this project, so it is an oracle here rather than the
    parser: the suite must run on what CI installs, and pytest happens to
    bring it.
    """
    requirements = pytest.importorskip("packaging.requirements")
    utils = pytest.importorskip("packaging.utils")
    expected = utils.canonicalize_name(requirements.Requirement(text).name)
    line = _parse_line(text)
    assert line is not None and line.name == expected


@pytest.mark.parametrize(
    ("text", "foreign"),
    [
        ("-i https://pypi.typesafe.ai/simple", True),
        ("-ihttps://pypi.typesafe.ai/simple", True),
        ("--index-url=https://evil.example/simple", True),
        ("--extra-index-url https://pypi.org/simple", True),
        ("-f ./wheels", True),
        ("--find-links=https://evil.example/wheels", True),
        ("--trusted-host evil.example", True),
        ("--no-index", True),
        ("-e git+https://github.com/x/typesafe-sdk#egg=typesafe_sdk", True),
        ("typesafe-sdk @ https://evil.example/t.whl", True),
        ("https://evil.example/t.whl", True),
        ("--index-url https://pypi.org/simple/", False),
        ("-e .", False),
        ("typesafe-sdk>=1.0", False),
        ("-r requirements.txt", False),
    ],
)
def test_the_source_rule_sees_every_way_to_change_where_pip_looks(
    text: str, foreign: bool
) -> None:
    line = _parse_line(text)
    assert line is not None and _is_foreign_source(line) is foreign


def test_the_include_follower_reaches_everything_an_include_brings_in(
    tmp_path: Path,
) -> None:
    """Includes chain, may cycle, and must not be allowed to point at nothing."""
    (tmp_path / "a.txt").write_text("-r b.txt\nrequests\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("--requirement=c.txt\n", encoding="utf-8")
    (tmp_path / "c.txt").write_text(
        "anthropic>=0.40 \\\n  ; python_version >= '3.11'\n-r a.txt\n",
        encoding="utf-8",
    )
    names = {e.line.name for e in _read(tmp_path / "a.txt")}
    assert {"requests", "anthropic"} <= names
    assert "anthropic" not in {
        e.line.name for e in _read(tmp_path / "a.txt", follow=False)
    }

    (tmp_path / "broken.txt").write_text("-r missing.txt\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="does not exist"):
        _read(tmp_path / "broken.txt")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "RUN pip install --no-cache-dir -r requirements-programme.txt \\\n"
            " && apt-get purge -y gcc",
            [["--no-cache-dir", "-r", "requirements-programme.txt"]],
        ),
        (
            "      - run: pip install -r requirements.txt -r requirements-dev.txt",
            [["-r", "requirements.txt", "-r", "requirements-dev.txt"]],
        ),
        (
            "        run: |\n"
            "          pip install -r requirements.txt\n"
            "          python -m pip install 'anthropic>=0.40' # the SDK\n",
            [["-r", "requirements.txt"], ["anthropic>=0.40"]],
        ),
        ("RUN pip install a && uv pip install typesafe-sdk", [["a"], ["typesafe-sdk"]]),
        ("# pip install anthropic\nRUN pipx install ruff", []),
    ],
)
def test_the_install_reader_finds_every_pip_install(
    text: str, expected: list[list[str]]
) -> None:
    assert _pip_installs(text) == expected


def test_an_install_command_reads_as_requirements_lines() -> None:
    lines = _install_lines(
        [
            "--no-cache-dir",
            "-r",
            "requirements.txt",
            "--extra-index-url",
            "https://pypi.typesafe.ai/simple",
            "typesafe-ai",
        ]
    )
    assert Line(option="--requirement", value="requirements.txt") in lines
    assert any(_is_foreign_source(line) for line in lines)
    assert Line(name="typesafe-ai") in lines
    assert "https://pypi.typesafe.ai/simple" not in {line.name for line in lines}


def test_the_npm_reader_sees_manifests_and_every_lockfile_entry(
    tmp_path: Path,
) -> None:
    """A transitive dependency is in the lockfile and nowhere in the manifest."""
    manifest = tmp_path / "package.json"
    manifest.write_text(
        json.dumps(
            {"dependencies": {"next": "15"}, "devDependencies": {"typesafe-sdk": "1"}}
        ),
        encoding="utf-8",
    )
    lock = tmp_path / "package-lock.json"
    lock.write_text(
        json.dumps(
            {
                "packages": {
                    "": {},
                    "node_modules/@typesafe/sdk": {},
                    "node_modules/next/node_modules/cooksafe": {},
                }
            }
        ),
        encoding="utf-8",
    )
    assert _npm_names(manifest) == {"next", "typesafe-sdk"}
    assert _npm_names(lock) == {"@typesafe/sdk", "cooksafe"}


def test_the_compose_reader_separates_services() -> None:
    text = (
        "services:\n"
        "  api:\n"
        "    build: .\n"
        "  # The programme, behind a profile. Dockerfile.programme is its image.\n"
        "  worker:\n"
        "    build:\n"
        "      dockerfile: Dockerfile.programme\n"
        "volumes:\n"
        "  pgdata:\n"
    )
    services = _compose_services(text)
    assert set(services) == {"api", "worker"}
    assert "Dockerfile.programme" in services["worker"]
    assert "Dockerfile.programme" not in services["api"], "a comment is not config"


@pytest.mark.parametrize(
    ("name", "claims"),
    [
        ("typesafe-sdk", True),
        ("Typesafe_AI", True),
        ("typesafe", True),
        ("@typesafe/sdk", True),
        ("@typesafe-ai/client", True),
        # TypeSafe's own npm SDK and cookbook helper: genuine, and still
        # TypeSafe client code.
        ("@typesafe-ai/sdk", True),
        ("cooksafe", True),
        ("jev-sdk", True),
        ("systemone-client", True),
        ("typesafety", False),
        ("typesafe-i18n", False),
        ("typesafe-actions", False),
        ("anthropic", False),
    ],
)
def test_the_typesafe_name_rule(name: str, claims: bool) -> None:
    assert _claims_to_be_typesafe(name) is claims


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "pip install --index-url https://PyPI.TypeSafe.ai/simple",
            ["pypi.typesafe.ai"],
        ),
        ("BASE = 'https://jev-api.com/v1'", ["jev-api.com"]),
        (
            "https://JevTypeSafeAI.com/api/v1/decide",
            ["jevtypesafeai.com", "jevtypesafeai"],
        ),
        ("https://jevtypesafeai.net/api/v1/decide", ["jevtypesafeai"]),
        ("https://api.JevTypeSafeAI.io", ["jevtypesafeai"]),
        ("https://JevTypeSafeAI.example", ["jevtypesafeai"]),
        ("https://thejevai.com/v1", ["thejevai.com"]),
        ("https://jevmodel.org", ["jevmodel.org"]),
        ("https://jev-ai.pro/pricing", ["jev-ai.pro"]),
        ('base_url="https://jev.guru"', ["jev.guru"]),
        ("https://jev.works/key", ["jev.works"]),
        ("https://JEV.WORKS:443/", ["jev.works"]),
        ("api.jev.works", ["jev.works"]),
        ("support@jev.guru", ["jev.guru"]),
        ("Paste your key at jev.works.", ["jev.works"]),
        ("jev.guru, then jev.works", ["jev.works", "jev.guru"]),
        # TypeSafe's own API, and hosts that merely begin or end the same way.
        ("https://api.typesafe.ai", []),
        ("see jev.worksheet", []),
        ("https://notjev.works", []),
        ("https://jev.works.example", []),
        ("jev.gurus", []),
        ("https://my-jev-api.com", []),
        ("https://jev-api.community", []),
        ("https://jev-ai.promo", []),
    ],
)
def test_the_lookalike_host_scan(text: str, expected: list[str]) -> None:
    assert _lookalike_hosts(text.encode()) == expected


def test_the_doc_reader_finds_the_hosts_in_fact_9(tmp_path: Path) -> None:
    """The reader behind the next test, on a section shaped like the real one."""
    doc = tmp_path / "08.md"
    doc.write_text(
        "### 8. Before\n`before.example.com`\n"
        "### 9. Lookalike domains and packages\n"
        "Official: `typesafe.ai` and its `api.` subdomain; PyPI `typesafe-sdk`;\n"
        "npm `@typesafe-ai/sdk`. Resellers: `Jev-API.com`, and `jev.works`.\n"
        "Set `JEV_API_KEY`, never `pypi.typesafe.ai`.\n"
        "### 10. After\n`after.example.com`\n",
        encoding="utf-8",
    )
    assert _hosts_the_doc_names(doc) == {
        "typesafe.ai",
        "jev-api.com",
        "jev.works",
        "pypi.typesafe.ai",
    }


# ---------------------------------------------------------------------------
# The boundaries
# ---------------------------------------------------------------------------


def test_the_scan_finds_what_it_is_meant_to_read() -> None:
    """
    Guards the guard. Every rule below is a prohibition, and a prohibition
    over nothing passes. So the positive direction is asserted first: the one
    file, the one image and the one workflow that *should* install the SDK are
    found to install it by the same readers the prohibitions use.
    """
    names = {path.name for path in _requirements_files()}
    assert {"requirements.txt", "requirements-dev.txt"} <= names, names
    assert PROGRAMME_REQUIREMENTS.name in names

    declared = {e.line.name for e in _read(PROGRAMME_REQUIREMENTS, follow=False)}
    assert "anthropic" in declared, declared
    dev = {e.line.name for e in _read(ROOT / "requirements-dev.txt")}
    assert "asyncpg" in dev, "the include follower did not reach requirements.txt"
    assert "asyncpg" in {e.line.name for e in _pyproject_entries()}

    for path in (PROGRAMME_DOCKERFILE, PROGRAMME_WORKFLOW):
        installed = {e.line.name for e in _installed_by(path)}
        assert "anthropic" in installed, f"{_label(path)} installs {installed}"

    assert "programme" in _compose_services(COMPOSE.read_text(encoding="utf-8"))
    assert len(_workflows()) >= 4
    assert {_label(p) for p in _dockerfiles()} >= {"Dockerfile", "Dockerfile.programme"}


def test_a_model_sdk_is_declared_only_by_the_programme_requirements() -> None:
    """
    Declared, not merely installed: ``anthropic`` appears as a requirement in
    one file. A second declaration somewhere else — pyproject.toml, which is
    what Vercel installs for the API, or a new requirements file — would put
    it in a process that is forbidden to import it, and the import test would
    be the only thing left standing between them.
    """
    entries = [
        entry
        for path in _requirements_files()
        if path.resolve() != PROGRAMME_REQUIREMENTS.resolve()
        for entry in _read(path, follow=False)
    ] + _pyproject_entries()
    offenders = [
        f"{e.where}: {e.line.name}" for e in entries if _installs_a_model_sdk(e.line)
    ]
    assert not offenders, (
        "a model SDK is declared outside requirements-programme.txt:\n"
        + "\n".join(offenders)
    )


@pytest.mark.parametrize("filename", DEPLOYABLE_REQUIREMENTS)
def test_the_deployable_sets_install_no_model_sdk(filename: str) -> None:
    """
    The same rule through includes. ``requirements-dev.txt`` is what a
    developer and three workflows install; if it, or anything it includes,
    reached the programme's file, the SDK would be in every process on the
    machine without either file naming it.
    """
    offenders = _deployable_offenders(ROOT / filename)
    assert not offenders, f"{filename} installs a model SDK:\n" + "\n".join(offenders)


def test_test_tooling_may_install_httpx2(tmp_path: Path) -> None:
    """
    starlette's TestClient warns, wherever it is imported without ``httpx2``,
    that ``httpx`` is deprecated there and ``httpx2`` wanted instead. Following
    that instruction — in requirements-dev.txt and in ``ci.yml``'s ``pip
    install pytest pytest-asyncio httpx`` — once failed three of the rules in
    this file, because ``httpx2`` was listed as a model SDK for being
    ``typesafe-sdk``'s transport. It is a general HTTP client; when starlette
    drops the fallback, that edit is the only fix, and the rules must take it.

    So the migration is made to copies of the real files and put through the
    same rules, beside a control that the SDK itself is still refused.
    """
    for source in ROOT.glob("requirements*.txt"):
        (tmp_path / source.name).write_text(
            source.read_text(encoding="utf-8"), encoding="utf-8"
        )
    dev = tmp_path / "requirements-dev.txt"
    text = dev.read_text(encoding="utf-8")
    # Made to the copy while the real file still declares httpx; once the real
    # file has migrated there is nothing to rewrite, and the same rules are put
    # to it as it stands. Either way the file under test declares httpx2.
    migrated = re.sub(r"(?m)^httpx\b(?!2)[^\n]*", "httpx2", text)
    dev.write_text(migrated, encoding="utf-8")
    assert "httpx2" in {e.line.name for e in _read(dev)}, "the reader missed it"
    assert _deployable_offenders(dev) == []
    assert not _installs_a_model_sdk(Line(name="httpx2"))

    workflow = tmp_path / "ci.yml"
    workflow.write_text(
        "      - run: |\n"
        "          pip install -r requirements.txt\n"
        "          pip install pytest pytest-asyncio httpx2\n",
        encoding="utf-8",
    )
    assert "httpx2" in {e.line.name for e in _installed_by(workflow)}
    assert _workflow_offenders(workflow) == []

    dev.write_text(migrated + "typesafe-sdk\n", encoding="utf-8")
    assert [o.rpartition(": ")[2] for o in _deployable_offenders(dev)] == [
        "typesafe-sdk"
    ]


def test_typesafe_is_only_ever_its_official_sdk() -> None:
    """
    ``typesafe-sdk``, from PyPI, in the programme's file — and no other name
    that presents itself as TypeSafe's, anywhere.

    Exact because a typosquat is one character away, and from PyPI because a
    correct name fetched from the wrong place is the same attack.
    """
    entries = [e for p in _requirements_files() for e in _read(p, follow=False)]
    entries += _pyproject_entries()
    offenders: list[str] = []
    for entry in entries:
        name = entry.line.name
        if name is None or not _claims_to_be_typesafe(name):
            continue
        if name != TYPESAFE_SDK:
            offenders.append(f"{entry.where}: {name} is not TypeSafe's SDK")
        elif not entry.where.startswith(f"{PROGRAMME_REQUIREMENTS.name}:"):
            offenders.append(f"{entry.where}: {name} outside the programme's file")
        elif entry.line.reference is not None:
            offenders.append(f"{entry.where}: {name} from {entry.line.reference}")
    assert not offenders, "\n".join(offenders)


def test_nothing_points_pip_at_another_index() -> None:
    """
    Every requirement comes from PyPI, by name, however it is installed.

    ``--extra-index-url`` is the classic dependency-confusion route: pip takes
    the highest version from *either* index, so a lookalike index that serves
    ``typesafe-sdk`` 99.0 wins. ``--find-links``, ``--trusted-host``, a direct
    URL and the ``PIP_*`` and ``UV_*`` variables are the same change by other
    spellings, and a committed ``pip.conf`` is the same change by none.
    """
    entries = [e for p in _requirements_files() for e in _read(p, follow=False)]
    entries += _pyproject_entries()
    for path in (*_dockerfiles(), *_workflows()):
        entries += _installed_by(path)
    offenders = [
        f"{e.where}: {e.line.option or ''} {e.line.value or e.line.reference}"
        for e in entries
        if _is_foreign_source(e.line)
    ]
    for path in (*_dockerfiles(), *_workflows(), COMPOSE):
        text = _uncommented(path.read_text(encoding="utf-8"))
        offenders += [f"{_label(path)}: {v}" for v in SOURCE_VARIABLES if v in text]
    offenders += [
        f"{_label(p)} is committed"
        for p in _repository_files(lambda p: p.name in SOURCE_CONFIG_FILES, tests=True)
    ]
    uv = (
        tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
        .get("tool", {})
        .get("uv", {})
    )
    offenders += [
        f"pyproject.toml: [tool.uv] {key}"
        for key in (
            "index",
            "index-url",
            "extra-index-url",
            "find-links",
            "default-index",
        )
        if key in uv
    ]
    assert not offenders, "something changes where pip fetches from:\n" + "\n".join(
        offenders
    )


def test_only_the_programme_image_installs_the_programme_set() -> None:
    """
    The runtime half of the import boundary, in the image the API and the
    worker share. If ``Dockerfile`` installed requirements-programme.txt, the
    SDK would sit in the container that holds the broker credentials, and a
    source-level test would be the only thing between it and an import.

    Read three ways, because one is not enough: what its ``pip install`` lines
    install through their includes, whether a command names the programme's
    file at all (``uv pip sync`` would not be a ``pip install``), and whether
    one globs the requirements files and so installs every one of them.
    """
    offenders: list[str] = []
    for path in _dockerfiles():
        if path.resolve() == PROGRAMME_DOCKERFILE.resolve():
            continue
        offenders += [
            f"{e.where}: {e.line.name}"
            for e in _installed_by(path)
            if _installs_a_model_sdk(e.line)
        ]
        text = _uncommented(path.read_text(encoding="utf-8"))
        if PROGRAMME_REQUIREMENTS.name in text:
            offenders.append(f"{_label(path)} names {PROGRAMME_REQUIREMENTS.name}")
        if re.search(r"requirements[\w.-]*\*", text):
            offenders.append(f"{_label(path)} globs the requirements files")
    assert not offenders, (
        "an image other than Dockerfile.programme installs a model SDK:\n"
        + "\n".join(offenders)
    )


def test_only_the_programme_service_builds_the_programme_image() -> None:
    """
    The image separation is only as good as which service uses which image.
    ``build: .`` is the shared Dockerfile; pointing the worker at
    ``Dockerfile.programme`` would undo the separation above in one line.
    """
    services = _compose_services(COMPOSE.read_text(encoding="utf-8"))
    assert PROGRAMME_DOCKERFILE.name in services["programme"]
    offenders = [
        name
        for name, block in services.items()
        if name != "programme"
        and (PROGRAMME_DOCKERFILE.name in block or PROGRAMME_REQUIREMENTS.name in block)
    ]
    assert not offenders, (
        f"services other than the programme build its image: {offenders}"
    )


def test_only_the_programme_workflow_installs_a_model_sdk() -> None:
    """
    The deployment is two GitHub Actions workflows and a Vercel function, not
    the compose file. ``worker.yml`` runs the worker with the broker
    credentials; ``broker-check.yml`` and ``deployment-status.yml`` hold them
    too; ``ci.yml`` is where "the unit suite runs without an SDK" is actually
    true or not. Read off the directory rather than a list, as
    ``test_secret_isolation`` does, so a new workflow is covered on arrival.
    """
    offenders = [
        offender
        for path in _workflows()
        if path.resolve() != PROGRAMME_WORKFLOW.resolve()
        for offender in _workflow_offenders(path)
    ]
    assert not offenders, (
        "a workflow other than programme.yml installs a model SDK:\n"
        + "\n".join(offenders)
    )


def test_no_npm_package_claims_to_be_typesafe() -> None:
    """
    TypeSafe does publish an npm package, ``@typesafe-ai/sdk``, and it is
    refused with the rest. The frontend must hold no model client — a call
    from the browser needs the key in the browser — so every name presenting
    itself as TypeSafe's is refused, the official one included, in a manifest
    or anywhere in a lockfile. The one a hurried ``npm i`` reaches for is
    worse: the unscoped ``typesafe-sdk`` on npm borrows the official *PyPI*
    name and is a third party's empty placeholder.
    """
    manifests = _repository_files(
        lambda p: p.name in {"package.json", "package-lock.json"}, tests=True
    )
    assert any(_label(p) == "web/package-lock.json" for p in manifests), manifests
    offenders = [
        f"{_label(path)}: {name}"
        for path in manifests
        for name in sorted(_npm_names(path))
        if _claims_to_be_typesafe(name)
    ]
    assert not offenders, "\n".join(offenders)


def test_every_host_the_doc_names_is_scanned() -> None:
    """
    docs/08 fact 9 lists the lookalike hosts and says Phase A keeps every one
    of them out of anything that ships. The scan once read three of the eight,
    so ``base_url="https://jev.guru"`` — one of the two sites that ask for a
    real key — passed it while the doc said otherwise. A host added to the doc
    is now a host this file must scan, or this test names it.
    """
    named = _hosts_the_doc_names(LOOKALIKE_DOC)
    assert {"jev.works", "pypi.typesafe.ai"} <= named, named
    unscanned = sorted(named - NOT_LOOKALIKES - set(LOOKALIKE_HOSTS))
    assert not unscanned, (
        f"{_label(LOOKALIKE_DOC)} fact 9 names hosts LOOKALIKE_HOSTS does not "
        f"scan for: {unscanned}"
    )


def test_no_lookalike_host_appears_in_anything_that_ships() -> None:
    """
    The hosts a lookalike SDK or index would be served from. Nothing that
    runs, builds or installs this system has a reason to name them; tests do,
    which is why ``tests/`` is the one tree not read.
    """
    shipped = [
        *(
            path
            for tree in ("src", "web/src")
            for path in _repository_files(lambda p: True, tests=False)
            if path.is_relative_to(ROOT / tree)
        ),
        *_requirements_files(),
        *_dockerfiles(),
        *_workflows(),
        PYPROJECT,
        COMPOSE,
        ROOT / "vercel.json",
        *_repository_files(
            lambda p: p.name in {"package.json", "package-lock.json"}, tests=False
        ),
    ]
    labels = {_label(p) for p in shipped}
    assert {"src/api/main.py", "web/src/lib/api.ts", "requirements.txt"} <= labels
    offenders = [
        f"{_label(path)}: {host}"
        for path in shipped
        if path.is_file()
        for host in _lookalike_hosts(path.read_bytes())
    ]
    assert not offenders, (
        "a lookalike TypeSafe host appears in shipped code or configuration:\n"
        + "\n".join(offenders)
    )
