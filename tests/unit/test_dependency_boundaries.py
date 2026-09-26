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

Phase B added two things for these rules to read. The first is
``requirements-programme.lock``, the programme's set as it is actually
installed: every package pinned to one version and every file to a sha256. It
counts as the programme's file wherever a rule below names one, and has rules
of its own. Every entry is exactly pinned and hash-pinned; TypeSafe's SDK is
the one release, and the two files of it, whose provenance was checked;
nothing its source declares is missing; it was resolved for the Python that
installs it; and wherever it is installed, it is installed hash-checked and
from wheels alone.

The second is the one exception to "only programme.yml": CI's ``programme
sdk`` job installs the lock, to test the Jev client against the SDK it will
really run on. It may because it holds nothing else — no secret, and a token
that can only read — and runs nothing but the SDK's tests. So ``ci.yml`` is
read job by job: a job there that references any secret may not install a
model SDK, and the job that runs the unit suite may not install one at all.
"""

from __future__ import annotations

import ast
import itertools
import json
import os
import re
import shlex
import sys
import tomllib
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROGRAMME_REQUIREMENTS = ROOT / "requirements-programme.txt"
PROGRAMME_LOCK = ROOT / "requirements-programme.lock"

#: The programme's set: the file a person edits, and the lock resolved from it
#: that everything building, deploying or testing the programme installs. Where
#: a rule below says "the programme's file", it means either.
PROGRAMME_SET = (PROGRAMME_REQUIREMENTS, PROGRAMME_LOCK)
PROGRAMME_SET_NAMES = frozenset(path.name for path in PROGRAMME_SET)

DEPLOYABLE_REQUIREMENTS = ("requirements.txt", "requirements-dev.txt")
PROGRAMME_DOCKERFILE = ROOT / "Dockerfile.programme"
PROGRAMME_WORKFLOW = ROOT / ".github" / "workflows" / "programme.yml"

#: The one other workflow allowed a model SDK, and only in a job holding nothing
#: else. Read job by job, where every other workflow is read whole.
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

#: The dispatch-only key check (``python -m src.programme.jev_check``). The
#: third workflow allowed the lock, and the only one allowed a secret beside
#: it: the model key, since checking that key is the whole of its job. Held to
#: exactly that by ``test_the_jev_check_holds_the_model_key_and_nothing_else``.
JEV_CHECK_WORKFLOW = ROOT / ".github" / "workflows" / "jev-check.yml"
JEV_CHECK_SECRET = "TYPESAFE_API_KEY"
JEV_CHECK_COMMAND = "python -m src.programme.jev_check"

#: Everything that installs the programme's set, and so what the lock must have
#: been resolved for.
LOCK_INSTALLERS = (
    PROGRAMME_DOCKERFILE,
    PROGRAMME_WORKFLOW,
    CI_WORKFLOW,
    JEV_CHECK_WORKFLOW,
)

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

#: The one release of it permitted, and the files of that release pip may take.
#:
#: 0.7.1 is the floor: 0.5.7, 0.6.0 and 0.7.0 all echo an explicitly passed key
#: into connection-error text, given a key with an illegal header character.
#: PyPI holds two files for it, and each carries a PEP 740 attestation from
#: typesafe-ai/typesafe-sdk-python's publish.yml at v0.7.1 whose subject digest
#: is its hash here (docs/08, fact 2). The wheel is the file pip installs; the
#: sdist is here because uv lists every file of a release, and ``--only-binary
#: :all:`` keeps pip from using it. A digest outside this set is a file nobody
#: checked, so moving the pin means checking the new release's provenance and
#: writing its digests here.
TYPESAFE_SDK_VERSION = "0.7.1"
TYPESAFE_SDK_WHEEL = (
    "sha256:9d04eee13b5f64bbbe6f8e96cf40e3f39ca4efc934a1f4f39490cb9a43e9d2ad"
)
TYPESAFE_SDK_FILES = frozenset(
    {
        TYPESAFE_SDK_WHEEL,
        "sha256:495ce9d81733b4f95edcb156e95042a7ec4bfd59972a1150ffa8ce1e11f85a54",
    }
)

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
    #: The logical line as written, its comment removed, where there was one.
    text: str = ""


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
        text = _COMMENT.sub("", raw).strip()
        entry = Entry(f"{_label(path)}:{number}", line, text)
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


def _installs_in(text: str, where: str) -> list[Entry]:
    """
    What the ``pip install`` commands in some text install, includes followed.

    Includes resolve against the repository root: a workflow runs from its
    checkout, and an image ``COPY``s the same file names.
    """
    entries: list[Entry] = []
    for tokens in _pip_installs(text):
        for line in _install_lines(tokens):
            entry = Entry(where, line)
            entries.append(entry)
            if line.option in _INCLUDES:
                entries.extend(_include(ROOT, entry, frozenset()))
    return entries


def _installed_by(path: Path) -> list[Entry]:
    """What a Dockerfile or workflow installs, with its ``-r`` files followed."""
    text = path.read_text(encoding="utf-8")
    return _installs_in(text, f"{_label(path)}: pip install")


def _uncommented(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


# ---------------------------------------------------------------------------
# Reading a lock as pip reads it in hash-checking mode
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Pin:
    """One logical line of a lock: what pip installs, and the digests it must match."""

    where: str
    #: The requirement as written, or empty when the whole line is an option.
    requirement: str
    name: str | None = None
    #: The one version ``==`` names, or None when the line allows more than one.
    version: str | None = None
    reference: str | None = None
    hashes: tuple[str, ...] = ()
    #: Anything else on the line, or the whole line when it is an option.
    options: tuple[str, ...] = ()


#: ``==`` and one version with no wildcard: what ``--require-hashes`` demands
#: of every requirement it installs.
_EXACT = re.compile(r"==\s*(?P<version>[A-Za-z0-9][A-Za-z0-9.+!_-]*)")

#: A well-formed sha256 digest, as ``--hash`` spells it.
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")


def _pin(where: str, text: str) -> Pin:
    """
    One logical line of a lock, split as pip's ``break_args_options`` splits
    it: the requirement runs to the first word that is an option, and what
    follows are that requirement's own options — ``--hash`` in either of the
    spellings pip accepts, ``--hash=sha256:...`` or ``--hash sha256:...``.
    """
    words = text.split()
    requirement: list[str] = []
    while words and not words[0].startswith("-"):
        requirement.append(words.pop(0))
    if not requirement:
        return Pin(where, "", options=(text,))
    hashes: list[str] = []
    options: list[str] = []
    while words:
        option, value = _split_option(words.pop(0))
        if option != "--hash":
            options.append(option if value is None else f"{option}={value}")
        elif value is not None:
            hashes.append(value)
        else:
            hashes.append(words.pop(0) if words else "")
    spec = " ".join(requirement)
    line = _parse_requirement(spec)
    match = _REQUIREMENT.fullmatch(spec)
    rest = re.sub(r"^\[[^\]]*\]\s*", "", match["rest"]) if match else ""
    exact = _EXACT.fullmatch(rest.split(";")[0].strip())
    return Pin(
        where,
        spec,
        name=line.name,
        version=exact["version"] if exact and line.reference is None else None,
        reference=line.reference,
        hashes=tuple(hashes),
        options=tuple(options),
    )


def _pins(path: Path) -> list[Pin]:
    """Every logical line of a lock, its comments and blank lines aside."""
    pins: list[Pin] = []
    for number, raw in _logical_lines(path.read_text(encoding="utf-8")):
        text = _COMMENT.sub("", raw).strip()
        if text:
            pins.append(_pin(f"{_label(path)}:{number}", text))
    return pins


#: The Python a lock was resolved for, as uv and as pip-tools record it.
_RESOLVED_FOR = re.compile(
    r"--python-version[= ](?P<uv>\d+\.\d+)"
    r"|autogenerated by pip-compile with Python (?P<pip_tools>\d+\.\d+)"
)


def _lock_header(path: Path) -> str:
    """The comments a lock opens with: its tool's record of how it was made."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(itertools.takewhile(lambda line: line.startswith("#"), lines))


def _resolved_for(header: str) -> str | None:
    match = _RESOLVED_FOR.search(header)
    return (match["uv"] or match["pip_tools"]) if match else None


# ---------------------------------------------------------------------------
# Reading a workflow job by job
# ---------------------------------------------------------------------------

#: A mapping key alone on its line, which is how every job id here is written.
_KEY = re.compile(r"(?P<key>[A-Za-z_][\w-]*)\s*:")

#: A GitHub Actions expression, ``${{ ... }}``.
_EXPRESSION = re.compile(r"\$\{\{(.*?)\}\}", re.S)

#: What, inside an expression, hands a job a credential: the secrets context in
#: any spelling (``secrets.NAME``, ``secrets['NAME']``, ``toJSON(secrets)``),
#: or the job's own token.
_CREDENTIAL = re.compile(r"\bsecrets\b|\bgithub\.token\b")

#: ``secrets: inherit`` or a ``secrets:`` mapping, handing a called workflow
#: every secret or some, with no expression to show for it.
_SECRETS_KEY = re.compile(r"^\s*secrets\s*:", re.M)

#: ``pytest`` as a word of a command: not ``pytest-asyncio``, not a path.
_PYTEST = re.compile(r"(?<![\w./-])pytest(?![\w./-])")


def _bare(line: str) -> str:
    """A line without its trailing comment, for reading its key and its depth."""
    return re.sub(r"\s+#.*$", "", line).rstrip()


def _depth(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_structure(line: str) -> bool:
    """Whether a line can open or close a mapping: not blank, not a comment."""
    bare = _bare(line)
    return bool(bare.strip()) and not bare.lstrip().startswith("#")


def _workflow_jobs(text: str) -> tuple[str, dict[str, str]]:
    """
    A workflow's top level — everything outside ``jobs:``, which every job
    inherits — and each job's block, by its id.

    Read by indentation, as the compose reader is and for the same reason:
    pyyaml is not a dependency here. The jobs are the keys at the first depth
    under ``jobs:``, whatever that depth is. Comments are kept, because a
    comment line inside a ``run: |`` block is shell, and GitHub expands the
    expressions in it; they are simply never allowed to open or close a
    block. A ``jobs:`` in flow style reads as having no jobs, which the
    callers refuse rather than pass. ``test_the_job_reader_agrees_with_yaml``
    holds this to a real YAML parser over every real workflow.
    """
    top: list[str] = []
    jobs: dict[str, list[str]] = {}
    current = top
    in_jobs = False
    indent: int | None = None
    for line in text.splitlines():
        if not _is_structure(line):
            current.append(line)
            continue
        bare = _bare(line)
        depth = _depth(bare)
        if depth == 0:
            in_jobs = re.fullmatch(r"jobs\s*:", bare) is not None
            current = top
            if not in_jobs:
                top.append(line)
            continue
        if in_jobs:
            indent = depth if indent is None else indent
            key = _KEY.fullmatch(bare.strip())
            if depth == indent and key:
                current = jobs.setdefault(key["key"], [])
        current.append(line)
    return "\n".join(top), {job: "\n".join(lines) for job, lines in jobs.items()}


def _child_indent(block: str) -> int | None:
    """The depth of a job's own keys: that of the line after its id."""
    lines = [_bare(line) for line in block.splitlines() if _is_structure(line)]
    return _depth(lines[1]) if len(lines) > 1 else None


def _permissions(block: str, indent: int) -> str | None:
    """
    The ``permissions:`` a block declares at ``indent``, as text, or None.

    Its value inline — ``read-all``, ``{}``, ``{ contents: read }`` — or the
    mapping indented beneath it.
    """
    lines = block.splitlines()
    for number, line in enumerate(lines):
        bare = _bare(line)
        declared = re.fullmatch(r"permissions\s*:(?P<inline>.*)", bare.strip())
        if declared is None or _depth(bare) != indent or not _is_structure(line):
            continue
        if declared["inline"].strip():
            return declared["inline"].strip()
        body: list[str] = []
        for following in lines[number + 1 :]:
            if not _is_structure(following):
                continue
            if _depth(_bare(following)) <= indent:
                break
            body.append(_bare(following).strip())
        return "\n".join(body)
    return None


def _token_problem(job: str, top: str) -> str | None:
    """
    Why a job's ``GITHUB_TOKEN`` could write, or None when it cannot.

    The job's own ``permissions:`` if it declares any, else the workflow's.
    With neither, the token takes the repository's default, which an
    administrator can set to write — so an absent block is a problem, not
    whatever the default happens to be today.
    """
    indent = _child_indent(job)
    declared = None if indent is None else _permissions(job, indent)
    if declared is None:
        declared = _permissions(top, 0)
    if declared is None:
        return "takes the repository default, which can write: no permissions block"
    value = declared.strip()
    if value in {"{}", "read-all"}:
        return None
    if value == "write-all":
        return "can write (write-all)"
    grants = re.findall(r"([\w-]+)\s*:\s*([\w-]+)", value)
    if not grants:
        return f"is granted {value!r}, which this reader cannot judge read-only"
    writes = [
        f"{scope}: {level}" for scope, level in grants if level not in {"read", "none"}
    ]
    return f"can write ({', '.join(writes)})" if writes else None


def _credentials(job: str, top: str) -> list[str]:
    """
    Every credential a job is handed, by its own text or by the workflow's.

    Expressions are read in comment lines too: inside a ``run: |`` block a
    ``#`` line is shell, and GitHub substitutes a secret into it before the
    shell ever sees it. A YAML comment that happens to hold one is refused
    with them, which costs nothing.
    """
    found: list[str] = []
    for text in (job, top):
        found += [
            f"${{{{ {expression.strip()} }}}}"
            for expression in _EXPRESSION.findall(text)
            if _CREDENTIAL.search(expression)
        ]
        found += [
            line.strip()
            for line in _uncommented(text).splitlines()
            if _SECRETS_KEY.match(line)
        ]
    return found


def _pytest_runs(text: str) -> list[list[str]]:
    """
    The arguments of every ``pytest`` a block of a workflow runs.

    Read as a word rather than as the first word of a command, so that
    ``python -m pytest`` and ``timeout 600 pytest`` are runs too. What is not a
    run is skipped: a comment, a ``pip install`` naming the package, and a
    ``name:``, which is a label.
    """
    runs: list[list[str]] = []
    for raw in re.sub(r"\\\n", " ", _uncommented(text)).splitlines():
        if re.match(r"\s*(?:-\s+)?name\s*:", raw):
            continue
        for segment in _SHELL_BREAK.split(raw):
            if _PIP_INSTALL.search(segment):
                continue
            for word in _PYTEST.finditer(segment):
                rest = segment[word.end() :]
                try:
                    runs.append(shlex.split(rest, comments=True))
                except ValueError:
                    runs.append(rest.split())
    return runs


def _marker(args: Sequence[str]) -> str | None:
    """The ``-m`` expression a pytest run selects by, or None. The last one wins."""
    selected: str | None = None
    for index, token in enumerate(args):
        if token == "-m":
            selected = args[index + 1] if index + 1 < len(args) else None
        elif token.startswith("-m") and not token.startswith("--"):
            selected = token[2:]
    return selected


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


def _names_the_programme_set(text: str) -> list[str]:
    """
    The programme's files some configuration names outside its comments.

    Naming one is refused as installing one. ``uv pip sync`` or ``pip download``
    is not a ``pip install``, and a file that names the lock has no other
    reason to.
    """
    uncommented = _uncommented(text)
    return sorted(name for name in PROGRAMME_SET_NAMES if name in uncommented)


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
        and Path(e.line.value or "").name in PROGRAMME_SET_NAMES
    ]
    return offenders


def _image_offenders(path: Path) -> list[str]:
    """
    What an image other than the programme's installs, or names, that it must
    not. Read three ways, because one is not enough: what its ``pip install``
    lines install through their includes, whether it names the programme's
    files at all (``uv pip sync`` would not be a ``pip install``), and whether
    it globs the requirements files and so installs every one of them.
    """
    offenders = [
        f"{e.where}: {e.line.name}"
        for e in _installed_by(path)
        if _installs_a_model_sdk(e.line)
    ]
    text = _uncommented(path.read_text(encoding="utf-8"))
    offenders += [f"{_label(path)} names {n}" for n in _names_the_programme_set(text)]
    if re.search(r"requirements[\w.-]*\*", text):
        offenders.append(f"{_label(path)} globs the requirements files")
    return offenders


def _workflow_offenders(path: Path) -> list[str]:
    """What a workflow read whole (any but programme.yml and ci.yml) may not install."""
    offenders = [
        f"{e.where}: {e.line.name}"
        for e in _installed_by(path)
        if _installs_a_model_sdk(e.line)
    ]
    text = path.read_text(encoding="utf-8")
    offenders += [f"{_label(path)} names {n}" for n in _names_the_programme_set(text)]
    return offenders


def _sdk_installed(block: str, where: str) -> list[str]:
    """
    What in a block of configuration puts a model SDK in its process, as
    phrases: the SDKs it installs, through includes, and the programme's files
    it names. Empty when there is nothing.
    """
    installed = sorted(
        {
            e.line.name
            for e in _installs_in(block, where)
            if e.line.name is not None and _installs_a_model_sdk(e.line)
        }
    )
    named = _names_the_programme_set(block)
    return [
        *([f"installs {', '.join(installed)}"] if installed else []),
        *([f"names {', '.join(named)}"] if named else []),
    ]


def _ci_job_offenders(path: Path) -> list[str]:
    """
    ``ci.yml``'s rule, job by job: a model SDK only in a job that holds nothing
    else, and that runs nothing but the SDK's tests.

    Holding nothing is two conditions. No secret reaches the job, by its own
    text or by the workflow's: a job that tests a model client beside a
    credential is a process holding both, which is what programme.yml alone
    may be. And its token can only read, since a token that can write to the
    repository is a credential by another name. Running nothing but the SDK's
    tests keeps the other half of the bargain: wherever the suite runs, the
    SDK is absent, so a test that quietly depends on it fails.
    """
    text = path.read_text(encoding="utf-8")
    top, jobs = _workflow_jobs(text)
    assert jobs, f"{_label(path)}: the job reader found no jobs, so it read nothing"
    offenders = [
        f"{_label(path)} names {name} outside any job, where every job inherits it"
        for name in _names_the_programme_set(top)
    ]
    for job, block in jobs.items():
        where = f"{_label(path)} job {job}"
        sdk = _sdk_installed(block, f"{where}: pip install")
        if not sdk:
            continue
        holding = f"{where} {' and '.join(sdk)}"
        offenders += [f"{holding}, yet holds {c}" for c in _credentials(block, top)]
        problem = _token_problem(block, top)
        if problem is not None:
            offenders.append(f"{holding}, yet its token {problem}")
        runs = _pytest_runs(block)
        offenders += [
            f"{holding}, yet runs `pytest {' '.join(args)}`, not the SDK's tests alone"
            for args in runs
            if _marker(args) != "sdk"
        ]
        if not any(_marker(args) == "sdk" for args in runs):
            offenders.append(f"{holding}, yet runs no SDK tests, its only reason to")
    return offenders


def _triggers(top: str) -> set[str]:
    """
    The events a workflow runs on, read from its ``on:``: inline
    (``on: push``, ``on: [push, pull_request]``) or as the keys beneath it.
    """
    lines = top.splitlines()
    for number, line in enumerate(lines):
        bare = _bare(line)
        declared = re.fullmatch(r"(?:on|\"on\"|'on')\s*:(?P<inline>.*)", bare.strip())
        if declared is None or _depth(bare) != 0 or not _is_structure(line):
            continue
        inline = declared["inline"].strip()
        if inline:
            return {t.strip() for t in inline.strip("[]").split(",") if t.strip()}
        events: set[str] = set()
        indent: int | None = None
        for following in lines[number + 1 :]:
            if not _is_structure(following):
                continue
            depth = _depth(_bare(following))
            if depth == 0:
                break
            indent = depth if indent is None else indent
            key = _KEY.fullmatch(_bare(following).strip())
            if depth == indent and key:
                events.add(key["key"])
        return events
    return set()


def _jev_check_offenders(path: Path) -> list[str]:
    """
    The key check's rule: dispatch only, one job, a token that can only read,
    the model key and no other credential, and nothing run but the check.

    It installs the programme's lock because it runs the programme's own
    client, and that is safe only while nothing else in the process is worth
    taking — the same bargain as CI's SDK job, with the one credential its job
    requires. A schedule would spend the key on nobody's behalf; a second
    secret would make it a process holding a model client beside something
    else, which is what programme.yml alone may be.
    """
    text = path.read_text(encoding="utf-8")
    top, jobs = _workflow_jobs(text)
    where = _label(path)
    offenders: list[str] = []
    triggers = _triggers(top)
    if triggers != {"workflow_dispatch"}:
        offenders.append(f"{where} runs on {sorted(triggers)}, not dispatch alone")
    if len(jobs) != 1:
        offenders.append(f"{where} has {len(jobs)} jobs, not one")
    allowed = f"${{{{ secrets.{JEV_CHECK_SECRET} }}}}"
    for job, block in jobs.items():
        label = f"{where} job {job}"
        offenders += [
            f"{label} holds {credential}, beside the model key"
            for credential in _credentials(block, top)
            if credential != allowed
        ]
        if allowed not in _credentials(block, top):
            offenders.append(
                f"{label} is not handed {JEV_CHECK_SECRET}, its one secret"
            )
        problem = _token_problem(block, top)
        if problem is not None:
            offenders.append(f"{label}'s token {problem}")
        offenders += [
            f"{label} runs `pytest {' '.join(args)}`" for args in _pytest_runs(block)
        ]
        commands = re.findall(
            r"(?<![\w./-])python3?(?:\.\d+)?\s+(?:-m\s+[\w.]+|[\w./-]+\.py)",
            _uncommented(block),
        )
        offenders += [
            f"{label} runs `{command}`, not the check"
            for command in commands
            if " ".join(command.split()) != JEV_CHECK_COMMAND
        ]
        if JEV_CHECK_COMMAND not in [" ".join(c.split()) for c in commands]:
            offenders.append(f"{label} does not run `{JEV_CHECK_COMMAND}`")
    return offenders


def _suite_jobs(path: Path) -> dict[str, str]:
    """The jobs of a workflow that run the unit or the integration suite."""
    _, jobs = _workflow_jobs(path.read_text(encoding="utf-8"))
    return {
        job: block
        for job, block in jobs.items()
        if any(
            arg.startswith(("tests/unit", "tests/integration"))
            for args in _pytest_runs(block)
            for arg in args
        )
    }


def _lock_problems(pins: Sequence[Pin]) -> list[str]:
    """
    Every way a lock fails to be one: an entry pip could install at more than
    one version, from somewhere other than the index by name, or from a file
    whose digest the lock does not list. ``--require-hashes`` refuses most of
    these at install time; refusing them here names the line, and holds the
    lock to what it claims before anything tries to install it.
    """
    problems: list[str] = []
    seen: set[str] = set()
    for pin in pins:
        if not pin.requirement:
            problems.append(f"{pin.where}: `{pin.options[0]}`; a lock holds pins")
            continue
        label = pin.name or pin.requirement
        if pin.reference is not None:
            problems.append(f"{pin.where}: {label} is fetched from {pin.reference}")
        elif pin.version is None:
            problems.append(f"{pin.where}: `{pin.requirement}` is not one version")
        if not pin.hashes:
            problems.append(f"{pin.where}: {label} carries no hash")
        problems += [
            f"{pin.where}: {label} carries {digest!r}, not a sha256 digest"
            for digest in pin.hashes
            if not _SHA256.fullmatch(digest)
        ]
        problems += [f"{pin.where}: {label} carries {o}" for o in pin.options]
        if pin.name is not None and pin.name in seen:
            problems.append(f"{pin.where}: {pin.name} is pinned twice")
        seen.add(pin.name or "")
    return problems


def _typesafe_problems(pins: Sequence[Pin]) -> list[str]:
    """Whether the lock holds exactly the release, and the files, that were checked."""
    found = [pin for pin in pins if pin.name == TYPESAFE_SDK]
    if len(found) != 1:
        return [f"the lock pins {TYPESAFE_SDK} {len(found)} times, not once"]
    pin = found[0]
    problems: list[str] = []
    if pin.version != TYPESAFE_SDK_VERSION:
        problems.append(
            f"{pin.where}: {TYPESAFE_SDK} is pinned to {pin.version}, "
            f"not {TYPESAFE_SDK_VERSION}"
        )
    if TYPESAFE_SDK_WHEEL not in pin.hashes:
        problems.append(f"{pin.where}: the attested wheel's digest is not listed")
    problems += [
        f"{pin.where}: {digest} is not a file of the attested release"
        for digest in pin.hashes
        if digest not in TYPESAFE_SDK_FILES
    ]
    return problems


def _lock_gaps(source: Path, pins: Sequence[Pin]) -> list[str]:
    """
    What ``source`` declares, through its includes, that the lock does not
    satisfy — and any model SDK the lock carries that ``source`` never asked
    for.

    Nothing else notices a gap. A package added to requirements.txt and never
    locked installs cleanly under ``--require-hashes``, since the lock is the
    whole of what pip is asked for; CI's main job installs requirements.txt
    itself and passes; and the programme's image, which installs nothing but
    the lock, lacks the package until something imports it in production.
    Versions are judged by ``packaging``, an oracle here as in the parser test
    above.
    """
    requirements = pytest.importorskip("packaging.requirements")
    locked = {pin.name: pin for pin in pins if pin.name is not None}
    gaps: list[str] = []
    for entry in _read(source):
        name = entry.line.name
        if name is None or entry.line.reference is not None:
            continue
        pin = locked.get(name)
        if pin is None:
            gaps.append(f"{entry.where}: {name} is declared and not locked")
            continue
        declared = " ".join(
            itertools.takewhile(lambda w: not w.startswith("-"), entry.text.split())
        )
        wanted = requirements.Requirement(declared).specifier
        if pin.version is None or not wanted.contains(pin.version, prereleases=True):
            gaps.append(
                f"{entry.where}: `{declared}` is declared and the lock pins "
                f"{name} {pin.version}"
            )
    asked = {e.line.name for e in _read(source, follow=False)}
    gaps += [
        f"{pin.where}: {pin.name} is a model SDK {source.name} does not declare"
        for pin in pins
        if pin.name is not None
        and _installs_a_model_sdk(Line(name=pin.name))
        and pin.name not in asked
    ]
    return gaps


def _lock_installs(text: str) -> list[list[Line]]:
    """Every ``pip install`` in some text that installs the lock, as lines."""
    commands = [_install_lines(tokens) for tokens in _pip_installs(text)]
    return [
        lines
        for lines in commands
        if any(
            line.option in _INCLUDES
            and Path(line.value or "").name == PROGRAMME_LOCK.name
            for line in lines
        )
    ]


def _programme_install_problems(path: Path) -> list[str]:
    """
    How a Dockerfile or workflow installs the programme's set, if it does.

    As the lock, and never as requirements-programme.txt, whose ranges pip
    would resolve afresh on every build. With ``--require-hashes``, so that a
    missing digest is an error rather than a fetch of whatever the index
    serves. And with ``--only-binary :all:``, because pip does not hash-check
    what it fetches to build an sdist: the build backend arrives unverified,
    and the sdist's own build code runs.
    """
    label = _label(path)
    problems: list[str] = []
    for tokens in _pip_installs(path.read_text(encoding="utf-8")):
        lines = _install_lines(tokens)
        included = {Path(ln.value or "").name for ln in lines if ln.option in _INCLUDES}
        if PROGRAMME_REQUIREMENTS.name in included:
            problems.append(
                f"{label} installs {PROGRAMME_REQUIREMENTS.name}, not the lock"
            )
        if PROGRAMME_LOCK.name not in included:
            continue
        if Line(option="--require-hashes") not in lines:
            problems.append(f"{label} installs the lock without --require-hashes")
        if Line(option="--only-binary", value=":all:") not in lines:
            problems.append(f"{label} installs the lock without --only-binary :all:")
    return problems


def _installing_pythons(path: Path) -> list[str]:
    """The Python versions a Dockerfile or a workflow installs the lock into."""
    text = path.read_text(encoding="utf-8")
    if path.name.startswith("Dockerfile"):
        if not _lock_installs(text):
            return []
        return re.findall(r"(?m)^FROM\s+python:(\d+\.\d+)", _uncommented(text))
    _, jobs = _workflow_jobs(text)
    versions: list[str] = []
    for block in jobs.values():
        if not _lock_installs(block):
            continue
        for value in re.findall(
            r"(?m)^\s*python-version:\s*(.+?)\s*$", _uncommented(block)
        ):
            variable = re.fullmatch(r"\$\{\{\s*env\.(\w+)\s*\}\}", value)
            if variable:
                defined = re.search(
                    rf"(?m)^\s*{variable[1]}:\s*[\"']?([^\"'\s]+)[\"']?\s*$", text
                )
                value = defined[1] if defined else value
            versions.append(value.strip("\"'"))
    return versions


def _python_mismatches(lock: Path, installers: Sequence[Path]) -> list[str]:
    """
    Where the lock is installed into a Python other than the one it was
    resolved for. A resolution is per interpreter: a dependency behind
    ``python_version < "3.12"`` is in a 3.11 lock and absent from a 3.12 one,
    and an image or a job moved to another Python without regenerating the
    lock installs a tree nobody resolved.
    """
    resolved = _resolved_for(_lock_header(lock))
    if resolved is None:
        return [f"{_label(lock)} does not record the Python it was resolved for"]
    problems: list[str] = []
    for path in installers:
        versions = _installing_pythons(path)
        if not versions:
            problems.append(f"{_label(path)} installs the lock into no Python seen")
        problems += [
            f"{_label(path)} installs the lock into Python {version}; it was "
            f"resolved for {resolved}"
            for version in versions
            if version != resolved
        ]
    return problems


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
    """Every requirements file pip could be pointed at: sources, inputs and locks."""
    return _repository_files(
        lambda p: (
            p.name.startswith("requirements") and p.suffix in {".txt", ".in", ".lock"}
        ),
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
        (
            "RUN pip install --require-hashes --only-binary :all: \\\n"
            "    -r requirements-programme.lock",
            [
                [
                    "--require-hashes",
                    "--only-binary",
                    ":all:",
                    "-r",
                    "requirements-programme.lock",
                ]
            ],
        ),
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

    hashed = _install_lines(
        ["--require-hashes", "--only-binary=:all:", "-r", "requirements-programme.lock"]
    )
    assert Line(option="--require-hashes") in hashed, "it took the next token"
    assert Line(option="--only-binary", value=":all:") in hashed
    assert not any(_is_foreign_source(line) for line in hashed)


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
# The lock readers, tested against lines that must read a particular way
# ---------------------------------------------------------------------------

_DIGEST_A = "sha256:" + "a" * 64
_DIGEST_B = "sha256:" + "b" * 64


def test_the_lock_reader_reads_a_pin_as_pip_does(tmp_path: Path) -> None:
    """
    uv's layout: a pin continued over its hash lines, then ``# via`` comments
    that must not read as requirements. And pip's other spelling of a hash,
    ``--hash sha256:...``, which it accepts and a lock may therefore hold.
    """
    lock = tmp_path / "requirements-programme.lock"
    lock.write_text(
        "# This file was autogenerated by uv via the following command:\n"
        "#    uv pip compile requirements-programme.txt --generate-hashes\n"
        "httpx2==2.13.1 \\\n"
        f"    --hash={_DIGEST_A} \\\n"
        f"    --hash={_DIGEST_B}\n"
        "    # via\n"
        "    #   anthropic\n"
        "    #   typesafe-sdk\n"
        f"Typing_Extensions==4.16.0 --hash {_DIGEST_A}\n"
        f"uvicorn[standard]==0.54.0 ; sys_platform != 'win32' --hash={_DIGEST_B}\n",
        encoding="utf-8",
    )
    assert [(p.where, p.name, p.version, p.hashes) for p in _pins(lock)] == [
        ("requirements-programme.lock:3", "httpx2", "2.13.1", (_DIGEST_A, _DIGEST_B)),
        ("requirements-programme.lock:9", "typing-extensions", "4.16.0", (_DIGEST_A,)),
        ("requirements-programme.lock:10", "uvicorn", "0.54.0", (_DIGEST_B,)),
    ]
    assert _lock_problems(_pins(lock)) == []


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("a==1.0\n", "carries no hash"),
        (f"a>=1.0 --hash={_DIGEST_A}\n", "`a>=1.0` is not one version"),
        (f"a==1.* --hash={_DIGEST_A}\n", "`a==1.*` is not one version"),
        (f"a==1.0,<2 --hash={_DIGEST_A}\n", "is not one version"),
        (f"a --hash={_DIGEST_A}\n", "`a` is not one version"),
        ("a==1.0 --hash=md5:0cc175b9c0f1b6a831c399e269772661\n", "not a sha256"),
        ("a==1.0 --hash=sha256:abc\n", "not a sha256"),
        ("a==1.0 --hash\n", "not a sha256"),
        ("--index-url https://pypi.org/simple\n", "a lock holds pins"),
        ("-r requirements.txt\n", "a lock holds pins"),
        (f"a @ https://x.example/a.whl --hash={_DIGEST_A}\n", "is fetched from"),
        (f"https://x.example/a.whl --hash={_DIGEST_A}\n", "is fetched from"),
        (f"a==1.0 --hash={_DIGEST_A} --config-settings=x=y\n", "--config-settings"),
        (
            f"a==1.0 --hash={_DIGEST_A}\nA==1.0 --hash={_DIGEST_B}\n",
            "a is pinned twice",
        ),
    ],
)
def test_the_lock_rule_refuses_anything_pip_could_install_unchecked(
    tmp_path: Path, text: str, fragment: str
) -> None:
    lock = tmp_path / "x.lock"
    lock.write_text(text, encoding="utf-8")
    problems = _lock_problems(_pins(lock))
    assert any(fragment in problem for problem in problems), problems


@pytest.mark.parametrize(
    ("line", "fragment"),
    [
        (f"typesafe-sdk==0.7.1 --hash={TYPESAFE_SDK_WHEEL}", None),
        (
            "typesafe_sdk==0.7.1 --hash=sha256:495ce9d81733b4f95edcb156e95042a7ec4b"
            f"fd59972a1150ffa8ce1e11f85a54 --hash={TYPESAFE_SDK_WHEEL}",
            None,
        ),
        (f"typesafe-sdk==0.7.0 --hash={TYPESAFE_SDK_WHEEL}", "not 0.7.1"),
        (f"typesafe-sdk==0.7.1 --hash={_DIGEST_A}", "attested wheel"),
        (
            f"typesafe-sdk==0.7.1 --hash={TYPESAFE_SDK_WHEEL} --hash={_DIGEST_A}",
            "not a file of the attested release",
        ),
        (f"typesafe-sdk>=0.7.1 --hash={TYPESAFE_SDK_WHEEL}", "pinned to None"),
        (f"anthropic==1.8.0 --hash={_DIGEST_A}", "0 times"),
        (
            f"typesafe-sdk==0.7.1 --hash={TYPESAFE_SDK_WHEEL}\n"
            f"typesafe-sdk==0.7.1 --hash={TYPESAFE_SDK_WHEEL}",
            "2 times",
        ),
    ],
)
def test_the_typesafe_pin_rule(tmp_path: Path, line: str, fragment: str | None) -> None:
    """
    Exactly the release whose provenance was checked, and no file of it that
    was not. An extra digest in the lock is how a file nobody checked becomes
    one pip will accept, and it is a one-line change that is easy to miss in
    a review of two thousand lines of hashes.
    """
    lock = tmp_path / "x.lock"
    lock.write_text(line + "\n", encoding="utf-8")
    problems = _typesafe_problems(_pins(lock))
    if fragment is None:
        assert problems == []
    else:
        assert any(fragment in problem for problem in problems), problems


def test_the_lock_gap_rule(tmp_path: Path) -> None:
    """
    Every declared name locked at a version its declarations accept, includes
    followed, and no model SDK in the lock that the programme did not ask for.
    """
    (tmp_path / "base.txt").write_text(
        "pandas>=2.2\nuvicorn[standard]>=0.30.0\npydantic>=2.7\n", encoding="utf-8"
    )
    source = tmp_path / "requirements-programme.txt"
    source.write_text(
        "-r base.txt\nanthropic>=0.40.0\ntypesafe-sdk==0.7.1\npydantic>=2.12.0\n",
        encoding="utf-8",
    )
    pinned = {
        "pandas": "3.0.6",
        "uvicorn": "0.54.0",
        "anthropic": "1.8.0",
        "typesafe-sdk": "0.7.1",
        "pydantic": "2.13.5",
    }

    def gaps(**changes: str | None) -> list[str]:
        lock = tmp_path / "x.lock"
        lines = [
            f"{name}=={version} --hash={_DIGEST_A}"
            for name, version in {**pinned, **changes}.items()
            if version is not None
        ]
        lock.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return _lock_gaps(source, _pins(lock))

    assert gaps() == []
    assert gaps(pandas=None) == ["base.txt:1: pandas is declared and not locked"]
    # Satisfies requirements.txt's floor, and not the programme's own.
    assert gaps(pydantic="2.11.0") == [
        "requirements-programme.txt:4: `pydantic>=2.12.0` is declared and the lock "
        "pins pydantic 2.11.0"
    ]
    assert len(gaps(**{"typesafe-sdk": "0.7.0"})) == 1
    assert gaps(openai="1.0.0") == [
        "x.lock:6: openai is a model SDK requirements-programme.txt does not declare"
    ]


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (
            "# This file was autogenerated by uv via the following command:\n"
            "#    uv pip compile requirements-programme.txt --generate-hashes "
            "--python-version 3.11 --python-platform x86_64-manylinux_2_28 "
            "-o requirements-programme.lock\n",
            "3.11",
        ),
        ("#    uv pip compile x.txt --python-version=3.12 -o x.lock\n", "3.12"),
        (
            "#\n# This file is autogenerated by pip-compile with Python 3.13\n"
            "# by the following command:\n#\n#    pip-compile --generate-hashes\n#\n",
            "3.13",
        ),
        ("# hand-written\n", None),
        ("", None),
    ],
)
def test_the_lock_records_the_python_it_was_resolved_for(
    tmp_path: Path, header: str, expected: str | None
) -> None:
    lock = tmp_path / "x.lock"
    lock.write_text(header + f"a==1.0 --hash={_DIGEST_A}\n", encoding="utf-8")
    assert _resolved_for(_lock_header(lock)) == expected


def test_the_job_reader_splits_a_workflow_by_job() -> None:
    """
    Comments and blank lines never open or close a block, however they are
    indented, and the jobs are the keys at the first depth under ``jobs:``,
    two spaces or four.
    """
    text = (
        "# A header comment.\n"
        "name: CI\n"
        "env:\n"
        "  PYTHON_VERSION: '3.11'\n"
        "jobs:\n"
        "    # A comment about the first job.\n"
        "    first-job:   # trailing\n"
        "        runs-on: ubuntu-latest\n"
        "        steps:\n"
        "            - run: |\n"
        "                pip install a\n"
        "\n"
        "                pytest tests/unit\n"
        "# A comment at the margin, between the jobs.\n"
        "    second_job:\n"
        "        permissions: read-all\n"
        "concurrency:\n"
        "  group: x\n"
    )
    top, jobs = _workflow_jobs(text)
    assert list(jobs) == ["first-job", "second_job"]
    assert "pip install a" in jobs["first-job"]
    assert "pytest tests/unit" in jobs["first-job"]
    assert "permissions" in jobs["second_job"]
    assert "PYTHON_VERSION" in top and "group: x" in top
    assert "runs-on" not in top
    assert _child_indent(jobs["first-job"]) == 8

    assert _workflow_jobs("name: x\njobs: {a: {runs-on: x}}\n")[1] == {}


@pytest.mark.parametrize(
    ("job", "top", "problem"),
    [
        ("  a:\n    permissions:\n      contents: read\n", "", None),
        ("  a:\n    permissions:   # read only\n      contents: read\n", "", None),
        ("  a:\n    permissions: read-all\n", "", None),
        ("  a:\n    permissions: {}\n", "", None),
        ("  a:\n    permissions: { contents: read, issues: none }\n", "", None),
        ("  a:\n    runs-on: x\n", "permissions:\n  contents: read\n", None),
        ("  a:\n    runs-on: x\n", "", "no permissions block"),
        ("  a:\n    permissions:\n      contents: write\n", "", "contents: write"),
        (
            "  a:\n    permissions:\n      contents: read\n      id-token: write\n",
            "",
            "id-token: write",
        ),
        ("  a:\n    permissions: write-all\n", "", "write-all"),
        (
            "  a:\n    runs-on: x\n",
            "permissions:\n  contents: read\n  packages: write\n",
            "packages: write",
        ),
        # The job's own block replaces the workflow's, as GitHub applies them.
        ("  a:\n    permissions: read-all\n", "permissions: write-all\n", None),
        # A key called permissions deeper in the job is not the job's.
        (
            "  a:\n    steps:\n      - with:\n          permissions: read-all\n",
            "",
            "no permissions block",
        ),
    ],
)
def test_the_token_reader(job: str, top: str, problem: str | None) -> None:
    found = _token_problem(job, top)
    if problem is None:
        assert found is None
    else:
        assert found is not None and problem in found, found


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("        run: pytest tests/unit -q", [["tests/unit", "-q"]]),
        (
            "      - run: python -m pytest tests/sdk -m sdk",
            [["tests/sdk", "-m", "sdk"]],
        ),
        (
            "          timeout 600 pytest -q tests/integration",
            [["-q", "tests/integration"]],
        ),
        (
            "          pytest tests/sdk -msdk && pytest tests/unit",
            [["tests/sdk", "-msdk"], ["tests/unit"]],
        ),
        ("        run: pytest -q  # all of it", [["-q"]]),
        ("    name: pytest", []),
        ("      - name: Run pytest", []),
        ("        run: pip install pytest pytest-asyncio", []),
        ("      - uses: org/pytest-action@v1", []),
        ("          # pytest tests/unit", []),
        ("          cat pytest.ini", []),
    ],
)
def test_the_pytest_reader(text: str, expected: list[list[str]]) -> None:
    assert _pytest_runs(text) == expected


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["tests/sdk", "-m", "sdk", "-q"], "sdk"),
        (["-msdk"], "sdk"),
        (["-m", "sdk or unit"], "sdk or unit"),
        (["-m", "unit", "-m", "sdk"], "sdk"),
        (["-munit", "-msdk"], "sdk"),
        (["-msdk", "-m", "unit"], "unit"),
        (["-q", "tests/unit"], None),
        (["-m"], None),
        (["--maxfail", "1"], None),
    ],
)
def test_the_marker_reader(args: list[str], expected: str | None) -> None:
    assert _marker(args) == expected


def test_the_job_reader_agrees_with_yaml() -> None:
    """
    The job reader is indentation, like the compose reader, because pyyaml is
    not a dependency here. uvicorn[standard] happens to bring it, so it is an
    oracle, as ``packaging`` is above: every real workflow must split into the
    jobs a YAML parser sees, each with the same ``pip install`` commands and
    the same judgement of its token.

    It also proves every workflow parses. The first draft of the SDK job said
    ``run: pip install --only-binary :all: -r ...``, which YAML reads as a
    mapping, so the workflow would not have loaded and nothing in it would
    have run — while every line-reading rule in this file passed it.
    """
    yaml = pytest.importorskip("yaml")
    workflows = _workflows()
    assert len(workflows) >= 4
    for path in workflows:
        text = path.read_text(encoding="utf-8")
        document = yaml.safe_load(text)
        top, jobs = _workflow_jobs(text)
        assert set(jobs) == set(document["jobs"]), _label(path)
        for job, block in jobs.items():
            parsed = document["jobs"][job]
            commands = "\n".join(
                step["run"] for step in parsed.get("steps", []) if "run" in step
            )
            where = f"{_label(path)} job {job}"
            assert _pip_installs(block) == _pip_installs(commands), where
            declared = parsed.get("permissions", document.get("permissions"))
            writes = (
                declared is None
                or declared == "write-all"
                or (isinstance(declared, str) and declared != "read-all")
                or (
                    isinstance(declared, dict)
                    and any(v not in {"read", "none"} for v in declared.values())
                )
            )
            assert (_token_problem(block, top) is not None) is writes, where


# ---------------------------------------------------------------------------
# The rules, bitten: synthetic files each rule must refuse
# ---------------------------------------------------------------------------

_LOCK_INSTALL = (
    "pip install --require-hashes --only-binary :all: -r requirements-programme.lock"
)

#: CI's SDK job as shipped, in miniature.
_SDK_JOB = (
    "  sdk:\n"
    "    runs-on: ubuntu-latest\n"
    "    permissions:\n"
    "      contents: read\n"
    "    steps:\n"
    "      - uses: actions/checkout@v4\n"
    "      - run: |\n"
    f"          {_LOCK_INSTALL}\n"
    "      - run: pip install pytest pytest-asyncio\n"
    "      - run: pytest tests/sdk -m sdk -q\n"
)

#: CI's main job, in miniature: the unit suite, and no SDK.
_UNIT_JOB = (
    "  test:\n"
    "    runs-on: ubuntu-latest\n"
    "    steps:\n"
    "      - run: pip install -r requirements.txt pytest\n"
    "      - run: pytest tests/unit -q\n"
)


def _ci(*jobs: str, top: str = "") -> str:
    return "name: CI\non: pull_request\n" + top + "jobs:\n" + "".join(jobs)


def _with(job: str, before: str, added: str) -> str:
    """``job`` with ``added`` inserted before its first line starting ``before``."""
    assert before in job, before
    return job.replace(before, added + before, 1)


@pytest.mark.parametrize(
    ("workflow", "fragments"),
    [
        pytest.param(_ci(_SDK_JOB, _UNIT_JOB), [], id="as-shipped"),
        pytest.param(
            _ci(
                _SDK_JOB,
                _with(_UNIT_JOB, "    steps:", "    env:\n      X: ${{ secrets.X }}\n"),
            ),
            [],
            id="a-secret-in-another-job-is-that-jobs-business",
        ),
        pytest.param(
            _ci(_SDK_JOB, top="permissions:\n  contents: read\n").replace(
                "    permissions:\n      contents: read\n", ""
            ),
            [],
            id="a-read-only-token-inherited-from-the-workflow",
        ),
        pytest.param(
            _ci(
                _with(
                    _SDK_JOB, "    steps:", "    env:\n      KEY: ${{ secrets.ANY }}\n"
                )
            ),
            ["job sdk", "secrets.ANY"],
            id="a-job-env-secret",
        ),
        pytest.param(
            _ci(
                _with(
                    _SDK_JOB,
                    "      - run: pip install pytest",
                    "      - uses: actions/cache@v4\n"
                    "        with:\n"
                    "          key: ${{ secrets.CACHE_KEY }}\n",
                )
            ),
            ["secrets.CACHE_KEY"],
            id="a-step-input-secret",
        ),
        pytest.param(
            _ci(
                _with(
                    _SDK_JOB, "    steps:", "    env:\n      K: ${{ secrets['K'] }}\n"
                )
            ),
            ["secrets['K']"],
            id="the-index-spelling",
        ),
        pytest.param(
            _ci(
                _with(
                    _SDK_JOB,
                    "    steps:",
                    "    env:\n      A: ${{ toJSON(secrets) }}\n",
                )
            ),
            ["toJSON(secrets)"],
            id="every-secret-at-once",
        ),
        pytest.param(
            _ci(
                _with(
                    _SDK_JOB, "    steps:", "    env:\n      T: ${{ github.token }}\n"
                )
            ),
            ["github.token"],
            id="the-jobs-own-token",
        ),
        pytest.param(
            _ci(
                _with(
                    _SDK_JOB,
                    "      - run: pip install pytest",
                    "          # ${{ secrets.IN_A_SHELL_COMMENT }}\n",
                )
            ),
            ["secrets.IN_A_SHELL_COMMENT"],
            id="a-secret-in-a-shell-comment-is-still-substituted",
        ),
        pytest.param(
            _ci(_SDK_JOB, top="env:\n  KEY: ${{ secrets.KEY }}\n"),
            ["job sdk", "secrets.KEY"],
            id="a-workflow-env-secret-reaches-every-job",
        ),
        pytest.param(
            _ci(_with(_SDK_JOB, "    steps:", "    secrets: inherit\n")),
            ["secrets: inherit"],
            id="secrets-inherit",
        ),
        pytest.param(
            _ci(_SDK_JOB.replace("    permissions:\n      contents: read\n", "")),
            ["no permissions block"],
            id="a-token-left-at-the-repository-default",
        ),
        pytest.param(
            _ci(_SDK_JOB.replace("contents: read", "contents: write")),
            ["contents: write"],
            id="a-token-that-can-write",
        ),
        pytest.param(
            _ci(
                _SDK_JOB.replace(
                    "contents: read", "contents: read\n      id-token: write"
                )
            ),
            ["id-token: write"],
            id="a-token-that-can-mint-an-oidc-credential",
        ),
        pytest.param(
            _ci(_SDK_JOB + "      - run: pytest tests/unit -q\n"),
            ["pytest tests/unit -q"],
            id="the-unit-suite-beside-the-sdk",
        ),
        pytest.param(
            _ci(_SDK_JOB.replace("-m sdk", '-m "sdk or unit"')),
            ["sdk or unit"],
            id="a-marker-that-takes-in-more",
        ),
        pytest.param(
            _ci(_SDK_JOB.replace("      - run: pytest tests/sdk -m sdk -q\n", "")),
            ["runs no SDK tests"],
            id="the-sdk-for-nothing",
        ),
        pytest.param(
            _ci(
                _SDK_JOB,
                _with(
                    _UNIT_JOB,
                    "      - run: pytest",
                    f"      - run: |\n          {_LOCK_INSTALL}\n",
                ),
            ),
            ["job test", "no permissions block", "pytest tests/unit -q"],
            id="the-main-job-given-the-lock",
        ),
        pytest.param(
            _ci(
                _with(
                    _UNIT_JOB,
                    "      - run: pytest",
                    "      - run: pip install anthropic\n"
                    "        env:\n"
                    "          DATABASE_URL: ${{ secrets.DATABASE_URL }}\n",
                )
            ),
            ["job test installs anthropic", "secrets.DATABASE_URL"],
            id="an-sdk-by-name-beside-a-secret",
        ),
        pytest.param(
            _ci(
                _with(
                    _UNIT_JOB,
                    "      - run: pytest",
                    "      - run: uv pip sync requirements-programme.lock\n"
                    "        env:\n"
                    "          K: ${{ secrets.K }}\n",
                )
            ),
            ["names requirements-programme.lock", "secrets.K"],
            id="the-lock-by-another-command",
        ),
        pytest.param(
            _ci(_UNIT_JOB, top="env:\n  LOCK: requirements-programme.lock\n"),
            ["outside any job"],
            id="the-lock-named-for-every-job",
        ),
    ],
)
def test_ci_refuses_a_model_sdk_beside_anything_else(
    tmp_path: Path, workflow: str, fragments: list[str]
) -> None:
    """
    The rule ``ci.yml`` is held to, put to synthetic workflows: the shipped
    shape passes, and each way a credential can reach the job that holds the
    SDK is refused — the job's own secrets in every spelling, the workflow's,
    a token that can write — as is the SDK beside any test but its own. A
    secret in some other job is that job's business: the rule is per job
    because GitHub gives each job its own runner.
    """
    path = tmp_path / "ci.yml"
    path.write_text(workflow, encoding="utf-8")
    offenders = _ci_job_offenders(path)
    if not fragments:
        assert offenders == []
    else:
        missing = [f for f in fragments if not any(f in o for o in offenders)]
        assert offenders and not missing, (missing, offenders)


def test_the_programme_set_is_refused_wherever_the_programme_is_not(
    tmp_path: Path,
) -> None:
    """
    The Phase A rules, put to the lock. It is the programme's file by another
    name, and each rule that refused requirements-programme.txt must refuse it
    the same way: in a deployable requirements file, in the shared image, and
    in a workflow read whole — ``worker.yml`` being the worker itself.
    """
    lock = tmp_path / PROGRAMME_LOCK.name
    lock.write_text(PROGRAMME_LOCK.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("requests\n", encoding="utf-8")

    dev = tmp_path / "requirements-dev.txt"
    dev.write_text(f"-r requirements.txt\n-r {lock.name}\n", encoding="utf-8")
    assert {"anthropic", TYPESAFE_SDK} <= {
        o.rpartition(": ")[2] for o in _deployable_offenders(dev)
    }
    assert f"requirements-dev.txt:2: includes {lock.name}" in _deployable_offenders(dev)

    image = tmp_path / "Dockerfile"
    image.write_text(
        f"FROM python:3.11-slim\nCOPY {lock.name} ./\nRUN {_LOCK_INSTALL}\n",
        encoding="utf-8",
    )
    offenders = _image_offenders(image)
    assert f"Dockerfile names {lock.name}" in offenders
    assert {"anthropic", TYPESAFE_SDK} <= {o.rpartition(": ")[2] for o in offenders}

    image.write_text(
        f"FROM python:3.11-slim\nRUN uv pip sync {lock.name}\n", encoding="utf-8"
    )
    assert _image_offenders(image) == [f"Dockerfile names {lock.name}"]

    worker = tmp_path / "worker.yml"
    worker.write_text(_ci(_SDK_JOB), encoding="utf-8")
    assert {"anthropic", TYPESAFE_SDK} <= {
        o.rpartition(": ")[2] for o in _workflow_offenders(worker)
    }


@pytest.mark.parametrize(
    ("text", "problems"),
    [
        (f"RUN {_LOCK_INSTALL}\n", []),
        (
            "RUN pip install --only-binary=:all: --require-hashes \\\n"
            "    -r ./requirements-programme.lock\n",
            [],
        ),
        (
            "RUN pip install --only-binary :all: -r requirements-programme.lock\n",
            ["x installs the lock without --require-hashes"],
        ),
        (
            "RUN pip install --require-hashes -r requirements-programme.lock\n",
            ["x installs the lock without --only-binary :all:"],
        ),
        (
            "RUN pip install --require-hashes --only-binary numpy "
            "-r requirements-programme.lock\n",
            ["x installs the lock without --only-binary :all:"],
        ),
        (
            "RUN pip install -r requirements-programme.txt\n",
            ["x installs requirements-programme.txt, not the lock"],
        ),
        ("RUN pip install -r requirements.txt\n", []),
    ],
)
def test_the_programme_set_is_installed_only_as_the_lock_hash_checked(
    tmp_path: Path, text: str, problems: list[str]
) -> None:
    path = tmp_path / "x"
    path.write_text(text, encoding="utf-8")
    assert _programme_install_problems(path) == problems


def test_the_python_check_bites(tmp_path: Path) -> None:
    """An image or a job moved to another Python while the lock stays behind."""
    lock = tmp_path / "x.lock"
    lock.write_text(
        "#    uv pip compile x.txt --generate-hashes --python-version 3.11\n",
        encoding="utf-8",
    )
    image = tmp_path / "Dockerfile.programme"
    image.write_text(f"FROM python:3.11-slim\nRUN {_LOCK_INSTALL}\n", encoding="utf-8")
    workflow = tmp_path / "ci.yml"
    workflow.write_text(
        _ci(
            _SDK_JOB.replace(
                "    steps:\n",
                "    steps:\n      - uses: actions/setup-python@v5\n"
                "        with:\n          python-version: ${{ env.PYTHON_VERSION }}\n",
            ),
            top='env:\n  PYTHON_VERSION: "3.11"\n',
        ),
        encoding="utf-8",
    )
    assert _installing_pythons(workflow) == ["3.11"]
    assert _python_mismatches(lock, [image, workflow]) == []

    image.write_text(f"FROM python:3.12-slim\nRUN {_LOCK_INSTALL}\n", encoding="utf-8")
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace('"3.11"', '"3.13"'),
        encoding="utf-8",
    )
    assert _python_mismatches(lock, [image, workflow]) == [
        "Dockerfile.programme installs the lock into Python 3.12; it was resolved "
        "for 3.11",
        "ci.yml installs the lock into Python 3.13; it was resolved for 3.11",
    ]

    image.write_text("FROM python:3.11-slim\nRUN pip install requests\n", "utf-8")
    assert _python_mismatches(lock, [image]) == [
        "Dockerfile.programme installs the lock into no Python seen"
    ]
    lock.write_text(f"a==1.0 --hash={_DIGEST_A}\n", encoding="utf-8")
    assert _python_mismatches(lock, []) == [
        "x.lock does not record the Python it was resolved for"
    ]


# ---------------------------------------------------------------------------
# The boundaries
# ---------------------------------------------------------------------------


def test_the_scan_finds_what_it_is_meant_to_read() -> None:
    """
    Guards the guard. Every rule below is a prohibition, and a prohibition
    over nothing passes. So the positive direction is asserted first: the
    files, the image and the jobs that *should* install the SDK are found to
    install it by the same readers the prohibitions use.
    """
    names = {path.name for path in _requirements_files()}
    assert {"requirements.txt", "requirements-dev.txt"} <= names, names
    assert PROGRAMME_SET_NAMES <= names, names

    declared = {e.line.name for e in _read(PROGRAMME_REQUIREMENTS, follow=False)}
    assert {"anthropic", TYPESAFE_SDK} <= declared, declared
    dev = {e.line.name for e in _read(ROOT / "requirements-dev.txt")}
    assert "asyncpg" in dev, "the include follower did not reach requirements.txt"
    assert "asyncpg" in {e.line.name for e in _pyproject_entries()}

    locked = {pin.name for pin in _pins(PROGRAMME_LOCK)}
    assert {"anthropic", TYPESAFE_SDK, "asyncpg", "httpx2"} <= locked, locked
    assert len(locked) >= 50, "the lock reader read a fraction of the lock"

    for path in (PROGRAMME_DOCKERFILE, PROGRAMME_WORKFLOW):
        installed = {e.line.name for e in _installed_by(path)}
        assert {"anthropic", TYPESAFE_SDK} <= installed, f"{_label(path)}: {installed}"

    _, jobs = _workflow_jobs(CI_WORKFLOW.read_text(encoding="utf-8"))
    sdk_jobs = [job for job, block in jobs.items() if _sdk_installed(block, job)]
    assert len(sdk_jobs) == 1, f"ci.yml jobs installing a model SDK: {sdk_jobs}"
    assert _suite_jobs(CI_WORKFLOW), "the scan found no job running the unit suite"
    assert not set(sdk_jobs) & set(_suite_jobs(CI_WORKFLOW))

    assert "programme" in _compose_services(COMPOSE.read_text(encoding="utf-8"))
    assert len(_workflows()) >= 4
    assert {_label(p) for p in _dockerfiles()} >= {"Dockerfile", "Dockerfile.programme"}


def test_a_model_sdk_is_declared_only_by_the_programme_requirements() -> None:
    """
    Declared, not merely installed: ``anthropic`` appears as a requirement in
    the programme's two files — the one a person edits and the lock resolved
    from it — and nowhere else. A declaration somewhere else — pyproject.toml,
    which is what Vercel installs for the API, a new requirements file, a new
    lock — would put it in a process that is forbidden to import it, and the
    import test would be the only thing left standing between them.
    """
    programme = {path.resolve() for path in PROGRAMME_SET}
    entries = [
        entry
        for path in _requirements_files()
        if path.resolve() not in programme
        for entry in _read(path, follow=False)
    ] + _pyproject_entries()
    offenders = [
        f"{e.where}: {e.line.name}" for e in entries if _installs_a_model_sdk(e.line)
    ]
    assert not offenders, (
        "a model SDK is declared outside the programme's requirements:\n"
        + "\n".join(offenders)
    )


@pytest.mark.parametrize("filename", DEPLOYABLE_REQUIREMENTS)
def test_the_deployable_sets_install_no_model_sdk(filename: str) -> None:
    """
    The same rule through includes. ``requirements-dev.txt`` is what a
    developer and three workflows install; if it, or anything it includes,
    reached the programme's file or its lock, the SDK would be in every process
    on the machine without either file naming it.
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
    ``typesafe-sdk``, from PyPI, in the programme's file or its lock — and no
    other name that presents itself as TypeSafe's, anywhere.

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
        elif entry.where.partition(":")[0] not in PROGRAMME_SET_NAMES:
            offenders.append(f"{entry.where}: {name} outside the programme's file")
        elif entry.line.reference is not None:
            offenders.append(f"{entry.where}: {name} from {entry.line.reference}")
    assert not offenders, "\n".join(offenders)


def test_typesafe_sdk_is_the_release_whose_provenance_was_checked() -> None:
    """
    The one release, and the files of it, that docs/08 fact 2 checked: a PEP
    740 attestation binding each file to typesafe-ai/typesafe-sdk-python's
    publish.yml at v0.7.1, and a wheel byte-identical to that tag.

    Held in both files. The source's pin is what a regenerated lock will
    resolve, and the lock's digests are what pip will accept; either moving
    alone is a release nobody checked, one change away from installation.
    """
    declared = [p for p in _pins(PROGRAMME_REQUIREMENTS) if p.name == TYPESAFE_SDK]
    assert [p.version for p in declared] == [TYPESAFE_SDK_VERSION], (
        f"{PROGRAMME_REQUIREMENTS.name} must pin {TYPESAFE_SDK}=="
        f"{TYPESAFE_SDK_VERSION} exactly: {[p.requirement for p in declared]}"
    )
    problems = _typesafe_problems(_pins(PROGRAMME_LOCK))
    assert not problems, "\n".join(problems)


def test_the_lock_pins_every_file_it_installs() -> None:
    """
    Every package at one version, from the index by name, with a sha256 for
    every file pip may take. The SDK's attestation covers the SDK alone: its
    dependencies — ``httpx2``, a young fork; ``pydantic-core``, which is native
    code — are attested by nobody, so the whole tree is locked, not the one
    package whose provenance was checked (docs/08, fact 2).
    """
    pins = _pins(PROGRAMME_LOCK)
    assert len(pins) >= 50, "the lock reader read a fraction of the lock"
    problems = _lock_problems(pins)
    assert not problems, f"{PROGRAMME_LOCK.name} does not lock:\n" + "\n".join(problems)


def test_the_lock_covers_what_the_programme_declares() -> None:
    """
    The lock is the programme's set only while it is the closure of its
    source. Change requirements.txt or requirements-programme.txt and forget
    the lock, and the image installs the old tree without a word: the lock is
    the whole of what pip is asked for, so ``--require-hashes`` has nothing to
    object to. Regenerate it with the command at its top.
    """
    gaps = _lock_gaps(PROGRAMME_REQUIREMENTS, _pins(PROGRAMME_LOCK))
    assert not gaps, (
        f"{PROGRAMME_LOCK.name} is stale; regenerate it with the command at its "
        "top:\n" + "\n".join(gaps)
    )


#: The one module that imports TypeSafe's SDK.
JEV_CLIENT = ROOT / "src" / "programme" / "jev_client.py"


def _third_party_imports(path: Path) -> set[str]:
    """
    The top-level name of every module ``path`` imports that is neither the
    standard library nor this repository's own, wherever the import sits: at
    the top, inside a function, or under ``TYPE_CHECKING``.
    """
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.partition(".")[0])
    return {name for name in names if name not in sys.stdlib_module_names} - {"src"}


def test_the_jev_client_imports_only_what_the_programme_declares() -> None:
    """
    ``jev_client`` imports ``typesafe_sdk``, and ``httpx2`` to build the SDK's
    HTTP client itself, both by name, so both are declared in the programme's
    file rather than left to arrive with something else. A package that is
    only inherited is one a regeneration of the lock can drop without a word:
    the day TypeSafe's SDK stops depending on it, the lock stops installing it
    and the client stops importing, with nothing here having said it needed
    it. The import name is read as the distribution's, which holds for these
    two; one whose names differ would need mapping here.
    """
    imported = {_normalise(name) for name in _third_party_imports(JEV_CLIENT)}
    # Guards the guard: both imports are lazy, and a scan of the module's top
    # level alone would find neither and pass.
    assert {"typesafe-sdk", "httpx2"} <= imported, imported
    declared = {e.line.name for e in _read(PROGRAMME_REQUIREMENTS) if e.line.name}
    missing = sorted(imported - declared)
    assert not missing, (
        f"{_label(JEV_CLIENT)} imports {missing}, which "
        f"{PROGRAMME_REQUIREMENTS.name} does not declare; declare it and "
        "regenerate the lock with the command at its top"
    )


def test_the_lock_was_resolved_for_the_python_that_installs_it() -> None:
    """
    The image's base tag, programme.yml's interpreter and ``ci.yml``'s
    ``PYTHON_VERSION`` are three places to move Python, and the lock records a
    fourth. Moving any of them alone installs a tree resolved for another
    interpreter.
    """
    problems = _python_mismatches(PROGRAMME_LOCK, LOCK_INSTALLERS)
    assert not problems, "\n".join(problems)


def test_the_programme_set_is_installed_as_the_lock_hash_checked() -> None:
    """
    Everything that builds, deploys or tests the programme installs the lock,
    and nothing installs the programme's set any other way: hash-checked, so
    a file whose digest the lock does not list is refused whichever index,
    proxy or cache served it, and wheels only, because the hash check does not
    reach what pip fetches to build an sdist. Every package in the lock
    publishes a wheel for the platforms these run on, so refusing sdists costs
    nothing, and a future one that does not fails its build loudly.
    """
    for path in LOCK_INSTALLERS:
        assert _lock_installs(path.read_text(encoding="utf-8")), (
            f"{_label(path)} does not install {PROGRAMME_LOCK.name}"
        )
    problems = [
        problem
        for path in (*_dockerfiles(), *_workflows())
        for problem in _programme_install_problems(path)
    ]
    assert not problems, "\n".join(problems)


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
    worker share. If ``Dockerfile`` installed the programme's file or its lock,
    the SDK would sit in the container that holds the broker credentials, and
    a source-level test would be the only thing between it and an import.
    """
    offenders = [
        offender
        for path in _dockerfiles()
        if path.resolve() != PROGRAMME_DOCKERFILE.resolve()
        for offender in _image_offenders(path)
    ]
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
    forbidden = {PROGRAMME_DOCKERFILE.name, *PROGRAMME_SET_NAMES}
    offenders = [
        name
        for name, block in services.items()
        if name != "programme" and any(marker in block for marker in forbidden)
    ]
    assert not offenders, (
        f"services other than the programme build its image: {offenders}"
    )


def test_only_the_programme_workflow_installs_a_model_sdk() -> None:
    """
    The deployment is two GitHub Actions workflows and a Vercel function, not
    the compose file. ``worker.yml`` runs the worker with the broker
    credentials; ``broker-check.yml`` and ``deployment-status.yml`` hold them
    too. Read off the directory rather than a list, as
    ``test_secret_isolation`` does, so a new workflow is covered on arrival.

    ``ci.yml`` is the one other workflow allowed an SDK, in one job, and is
    read job by job in the test below rather than whole here.
    """
    exempt = {
        PROGRAMME_WORKFLOW.resolve(),
        CI_WORKFLOW.resolve(),
        JEV_CHECK_WORKFLOW.resolve(),
    }
    offenders = [
        offender
        for path in _workflows()
        if path.resolve() not in exempt
        for offender in _workflow_offenders(path)
    ]
    assert not offenders, (
        "a workflow other than programme.yml installs a model SDK:\n"
        + "\n".join(offenders)
    )


def test_ci_holds_a_model_sdk_only_in_a_job_that_holds_nothing_else() -> None:
    """
    CI's ``programme sdk`` job installs the lock to test the Jev client against
    the SDK it will run on, and may for one reason: nothing in that job is
    worth taking. No secret reaches it, its token can only read, and it runs
    the SDK's tests and nothing else. The rule is per job, not per workflow,
    because GitHub gives each job its own runner — and so a job in this file
    that references any secret, or holds a token that can write, may not
    install a model SDK at all.
    """
    offenders = _ci_job_offenders(CI_WORKFLOW)
    assert not offenders, (
        "a job in ci.yml holds a model SDK beside something else:\n"
        + "\n".join(offenders)
    )


def test_the_jev_check_holds_the_model_key_and_nothing_else() -> None:
    """
    ``jev-check.yml`` is the third workflow that installs the lock, and the
    only one handed a secret beside it — the model key, since asking TypeSafe
    whether that key works is its whole job. Dispatch only, one job, a token
    that can only read, no other credential, and nothing run but the check.
    """
    assert JEV_CHECK_WORKFLOW.is_file(), f"{_label(JEV_CHECK_WORKFLOW)} is missing"
    assert _lock_installs(JEV_CHECK_WORKFLOW.read_text(encoding="utf-8"))
    offenders = _jev_check_offenders(JEV_CHECK_WORKFLOW)
    assert not offenders, "\n".join(offenders)


_JEV_CHECK = (
    "name: jev-check\n"
    "on:\n"
    "  workflow_dispatch:\n"
    "permissions:\n"
    "  contents: read\n"
    "jobs:\n"
    "  jev-check:\n"
    "    runs-on: ubuntu-latest\n"
    "    permissions:\n"
    "      contents: read\n"
    "    steps:\n"
    "      - uses: actions/checkout@v4\n"
    "      - run: |\n"
    f"          {_LOCK_INSTALL}\n"
    "      - name: Ask\n"
    "        env:\n"
    "          TYPESAFE_API_KEY: ${{ secrets.TYPESAFE_API_KEY }}\n"
    f"        run: {JEV_CHECK_COMMAND}\n"
)


@pytest.mark.parametrize(
    ("mutate", "fragment"),
    [
        pytest.param(lambda t: t, None, id="as-shipped"),
        pytest.param(
            lambda t: t.replace(
                "          TYPESAFE_API_KEY:",
                "          DATABASE_URL: ${{ secrets.DATABASE_URL }}\n"
                "          TYPESAFE_API_KEY:",
            ),
            "secrets.DATABASE_URL",
            id="the-database",
        ),
        pytest.param(
            lambda t: t.replace(
                "          TYPESAFE_API_KEY:",
                "          ALPACA_KEY_ID: ${{ secrets.ALPACA_KEY_ID }}\n"
                "          TYPESAFE_API_KEY:",
            ),
            "secrets.ALPACA_KEY_ID",
            id="a-venue-key",
        ),
        pytest.param(
            lambda t: t.replace("    steps:", "    secrets: inherit\n    steps:", 1),
            "secrets: inherit",
            id="every-secret",
        ),
        pytest.param(
            lambda t: t.replace(
                "  workflow_dispatch:\n",
                "  workflow_dispatch:\n  schedule:\n    - cron: '0 * * * *'\n",
            ),
            "not dispatch alone",
            id="a-schedule",
        ),
        pytest.param(
            lambda t: t.replace("on:\n  workflow_dispatch:\n", "on: [push]\n"),
            "not dispatch alone",
            id="on-push",
        ),
        pytest.param(
            lambda t: t.replace("      contents: read", "      contents: write"),
            "can write",
            id="a-writing-token",
        ),
        pytest.param(
            lambda t: t.replace("permissions:\n  contents: read\n", "").replace(
                "    permissions:\n      contents: read\n", ""
            ),
            "repository default",
            id="no-permissions",
        ),
        pytest.param(
            lambda t: t + "      - run: pytest tests/unit -q\n",
            "runs `pytest",
            id="a-test-suite",
        ),
        pytest.param(
            lambda t: t.replace(JEV_CHECK_COMMAND, "python -m src.programme.main"),
            "not the check",
            id="the-programme-instead",
        ),
        pytest.param(
            lambda t: t.replace(
                "        env:\n"
                "          TYPESAFE_API_KEY: ${{ secrets.TYPESAFE_API_KEY }}\n",
                "",
            ),
            "its one secret",
            id="no-key",
        ),
        pytest.param(
            lambda t: t + "  second:\n    runs-on: ubuntu-latest\n",
            "jobs, not one",
            id="a-second-job",
        ),
    ],
)
def test_the_jev_check_rule_bites(
    tmp_path: Path, mutate: Callable[[str], str], fragment: str | None
) -> None:
    path = tmp_path / "jev-check.yml"
    path.write_text(mutate(_JEV_CHECK), encoding="utf-8")
    offenders = _jev_check_offenders(path)
    if fragment is None:
        assert offenders == [], offenders
    else:
        assert any(fragment in o for o in offenders), (fragment, offenders)


def test_the_unit_suite_runs_where_no_model_sdk_is_installed() -> None:
    """
    CLAUDE.md: the unit suite "runs on requirements-dev.txt alone — every
    gate, validator and parser in src/programme is testable with no SDK
    present". That is checked only while the job that runs it has no SDK to
    lean on; install one there and a test that quietly imports it passes in CI
    and fails on every developer's machine. The integration suite is held to
    the same, since it runs in the same job.
    """
    suites = _suite_jobs(CI_WORKFLOW)
    assert suites, "the scan found no job in ci.yml running the unit suite"
    offenders = [
        f"ci.yml job {job} {what}"
        for job, block in suites.items()
        for what in _sdk_installed(block, job)
    ]
    assert not offenders, "\n".join(offenders)


def test_the_marker_ci_selects_is_registered() -> None:
    """
    The SDK job selects its tests with ``-m sdk``. The marker is registered in
    pyproject.toml so the tests carrying it do not warn, and so that the name
    the job selects and the name the tests carry are one name, written down.
    """
    options = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["pytest"]
    registered = {
        m.partition(":")[0].strip() for m in options["ini_options"]["markers"]
    }
    _, jobs = _workflow_jobs(CI_WORKFLOW.read_text(encoding="utf-8"))
    selected = {
        _marker(args)
        for block in jobs.values()
        if _sdk_installed(block, "ci.yml")
        for args in _pytest_runs(block)
    }
    assert selected == {"sdk"}, selected
    assert selected <= registered, registered


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
    assert {
        "src/api/main.py",
        "web/src/lib/api.ts",
        "requirements.txt",
        PROGRAMME_LOCK.name,
    } <= labels
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
