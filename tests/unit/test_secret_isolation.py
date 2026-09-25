"""
test_secret_isolation.py
------------------------
That no process holds both the keys to a venue and the keys to a model.

The vault moves the model API key out of one process's environment and into a
table every process can read. Encryption is what makes that acceptable, and the
encryption is only worth anything if the process that must not read the key does
not hold the key.

That process is the worker. It holds the broker credentials, it is the only
thing in this system that submits an order, and
``tests/unit/test_import_boundaries.py`` already forbids it from importing an
LLM client. None of that helps if it can simply `SELECT ciphertext` and decrypt.

The rule runs in both directions, and the second one was unenforced for longer
than the first. The programme is the one process permitted a model client, and
the import test forbids it the code that places an order — which says nothing
about a broker key already in its environment. A venue key needs no import to
use; one HTTP request places an order. Under compose the programme shared
`env_file: .env` with the worker and inherited the broker pair outright.

So the separation is expressed in key distribution, and asserted here against
the shipped ``docker-compose.yml`` and the GitHub workflows rather than left as
an intention in a docstring. A comment saying the worker does not get the key is
not the same thing as the worker not getting the key.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"
SRC = ROOT / "src"

#: The key that decrypts the vault.
SECRETS_KEY = "SECRETS_KEY"

#: Model credentials. Each can legitimately sit in `.env`, because the programme
#: reads the vault first and its environment second, so each is a variable the
#: shared env_file hands to every compose service unless that service blanks it.
#:
#: TYPESAFE_API_KEY is the Jev credential. It is listed before the integration
#: that reads it lands, so the process boundary exists before the key does
#: rather than being retrofitted after one has already leaked into the worker.
MODEL_KEYS = ("ANTHROPIC_API_KEY", "TYPESAFE_API_KEY")

#: The Alpaca credential pair. Not trusted as written:
#: ``test_the_broker_keys_are_the_names_the_code_reads`` derives the set from
#: ``src/config.py`` and compares, so a renamed variable fails that test instead
#: of quietly turning every assertion below into a check on a name nothing reads.
BROKER_KEYS = ("ALPACA_KEY_ID", "ALPACA_SECRET_KEY")

#: Read by ``src/bankr_client.py``, the reference client nothing runs today. A
#: venue credential all the same — bankr.bot trades on a prompt — and
#: `.env.example` invites an operator to fill it in.
REFERENCE_VENUE_KEYS = ("BANKR_API_KEY",)

VENUE_KEYS = BROKER_KEYS + REFERENCE_VENUE_KEYS

#: Alpaca settings that are not credentials. ``ALPACA_ALLOW_LIVE`` is one of the
#: three live-money gates and ``ALPACA_PAPER`` picks the endpoint; holding
#: either grants nothing without a key pair, and every service states the gate
#: explicitly as "false".
ALPACA_FLAGS = frozenset({"ALPACA_PAPER", "ALPACA_ALLOW_LIVE"})

#: Every way this codebase reads an environment variable, subscript access
#: included. The same accessors ``test_env_example_is_complete.py`` scans for.
_ENV_READS = re.compile(
    r"""(?:os\.environ\.get|os\.getenv|_bool_env|_int_env)"""
    r"""\(\s*["']([A-Z][A-Z0-9_]*)["']"""
    r"""|os\.environ\[\s*["']([A-Z][A-Z0-9_]*)["']\s*\]"""
)


def _service_block(name: str) -> str:
    """
    The YAML block for one service.

    Parsed by indentation rather than with a YAML library, because pyyaml is not
    a dependency of this project and adding one to read six lines would be a
    worse trade than a regex with a test guarding it.
    """
    text = COMPOSE.read_text(encoding="utf-8")
    match = re.search(rf"^  {re.escape(name)}:\n(.*?)(?=^  \S|\Z)", text, re.S | re.M)
    assert match, f"no service {name!r} in docker-compose.yml"
    return match.group(1)


def _blanks(service: str, name: str) -> bool:
    """
    Whether a service sets ``name`` to the empty string in its own block.

    An empty string specifically. ``NAME:`` with no value is YAML null, which
    compose reads as "pass through the host shell's value" — the opposite of a
    blank, and it looks almost the same in review.
    """
    pattern = rf"""^\s+{re.escape(name)}:\s*(?:""|'')\s*$"""
    return bool(re.search(pattern, _service_block(service), re.M))


def _env_reads(path: pathlib.Path) -> set[str]:
    names: set[str] = set()
    for groups in _ENV_READS.findall(path.read_text(encoding="utf-8")):
        names.update(name for name in groups if name)
    return names


def _broker_credentials_in_source(source: str) -> set[str]:
    """
    The environment variables behind ``Settings.has_broker_credentials``.

    Two hops, both read off the source rather than off a list: the fields that
    property tests, then the variable ``get_settings`` reads into each of them.
    That property is what the worker's broker factory and the API's
    ``broker_configured`` both consult, so it is the definition of "the broker
    credentials" the running code actually uses.

    A field whose variable cannot be followed fails here, loudly, rather than
    shrinking the set — a guard that returns fewer names when the code changes
    shape is a guard that passes when it should not.
    """
    tree = ast.parse(source)
    settings = next(
        (n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Settings"),
        None,
    )
    assert settings is not None, "src/config.py no longer defines Settings"
    prop = next(
        (
            n
            for n in settings.body
            if isinstance(n, ast.FunctionDef) and n.name == "has_broker_credentials"
        ),
        None,
    )
    assert prop is not None, "Settings.has_broker_credentials is gone"
    fields = {
        n.attr
        for n in ast.walk(prop)
        if isinstance(n, ast.Attribute)
        and isinstance(n.value, ast.Name)
        and n.value.id == "self"
    }
    assert fields, "has_broker_credentials reads no field of Settings"

    loader = next(
        (
            n
            for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "get_settings"
        ),
        None,
    )
    assert loader is not None, "src/config.py no longer defines get_settings"
    builds = [
        n
        for n in ast.walk(loader)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "Settings"
    ]
    assert len(builds) == 1, "get_settings should build Settings exactly once"
    # A keyword may be a local (`live_trading_enabled=live`) rather than the
    # read itself, so one level of assignment is followed.
    assigned = {
        target.id: node.value
        for node in ast.walk(loader)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }

    found: dict[str, list[str]] = {}
    for keyword in builds[0].keywords:
        if keyword.arg not in fields:
            continue
        value = keyword.value
        if isinstance(value, ast.Name) and value.id in assigned:
            value = assigned[value.id]
        found[keyword.arg] = [
            c.value
            for c in ast.walk(value)
            if isinstance(c, ast.Constant)
            and isinstance(c.value, str)
            and re.fullmatch(r"[A-Z][A-Z0-9_]*", c.value)
        ]
    assert set(found) == fields and all(len(v) == 1 for v in found.values()), (
        "could not follow every field of has_broker_credentials to the one "
        f"environment variable it is read from: fields {sorted(fields)}, "
        f"found {found}. Teach this derivation the new shape rather than "
        "hard-coding the answer."
    )
    return {names[0] for names in found.values()}


class TestTheWorkerCannotDecryptASecret:
    def test_the_scan_finds_the_services(self) -> None:
        # Guards the guard: if the compose layout changes shape, every
        # assertion below would otherwise pass against an empty string.
        for name in ("worker", "api", "programme"):
            assert len(_service_block(name)) > 40, name

    @pytest.mark.parametrize("name", [SECRETS_KEY, *MODEL_KEYS])
    def test_the_worker_blanks_it(self, name: str) -> None:
        """
        Explicitly emptied, not merely absent.

        Every service shares `env_file: .env`, so leaving a key unstated in the
        worker's own `environment:` inherits whatever the operator put in the
        shared file. Absence is not isolation here; only the override is.

        SECRETS_KEY is what decrypts the vault. The model keys are belt and
        braces, and cheap: even with the vault in place a deployment may set
        one in `.env` for the programme's fallback path, and the worker would
        inherit that directly — no decryption required.
        """
        assert _blanks("worker", name), (
            f"the worker must blank {name} in its own environment block. It "
            "shares env_file: .env with every other service, so without the "
            "override it inherits a way to a model credential — and it is the "
            "one process that submits orders."
        )

    @pytest.mark.parametrize("service", ["api", "programme"])
    def test_the_services_that_need_it_do_not_blank_it(self, service: str) -> None:
        """
        The other direction, and the reason this file is not just one assertion.

        A future edit that blanked the key everywhere would pass the tests above
        while quietly disabling the feature: the API could no longer store a
        credential and the programme could no longer read one. Both would report
        it honestly, and both would be broken.
        """
        assert not _blanks(service, SECRETS_KEY), (
            f"{service} needs SECRETS_KEY: the API encrypts with it and the "
            "programme decrypts with it. Blanking it here disables the vault."
        )


class TestTheApiHoldsNoModelKey:
    """
    The API commands the worker and never calls a model. It stores a model
    credential, encrypted under SECRETS_KEY, and it reports whether one is set
    by reading the `secrets` row. Neither needs the plaintext in its
    environment, so compose blanks it there.
    """

    @pytest.mark.parametrize("name", MODEL_KEYS)
    def test_the_api_blanks_it(self, name: str) -> None:
        assert _blanks("api", name), (
            f"the api must blank {name}. It needs no model credential of its "
            "own, and the shared env_file would otherwise hand it one."
        )

    def test_only_the_programme_reads_a_model_key_from_the_environment(
        self,
    ) -> None:
        """
        Why the blanks above cannot make anything lie.

        Blanking a variable a process reads to *report* status would turn a
        truthful "configured" into a false "not configured". That is safe today
        because nothing outside ``src/programme`` reads a model key from the
        environment: the configuration page describes the vault row. An
        endpoint that one day reported "configured from environment" would have
        to read the variable in ``src/api`` — and fail here, which is the point
        at which to decide whether the API should hold it at all.
        """
        programme = SRC / "programme"
        seen_in_programme: set[str] = set()
        offenders = []
        for path in sorted(SRC.rglob("*.py")):
            reads = _env_reads(path) & set(MODEL_KEYS)
            if programme in path.parents:
                seen_in_programme |= reads
            elif reads:
                offenders.append(f"{path.relative_to(ROOT)} reads {sorted(reads)}")
        # Guards the guard: the programme's own fallback read must be visible,
        # or the scan is matching nothing and every offender goes unseen.
        assert "ANTHROPIC_API_KEY" in seen_in_programme, seen_in_programme
        assert not offenders, (
            f"{offenders}. A model key is read from the environment outside the "
            "programme. docker-compose.yml blanks these in the api and the "
            "worker, so that read now sees an empty string — and if it reports "
            "status, it reports a false one."
        )


class TestTheProgrammeCannotReachAVenue:
    """
    The worker's blanks, in the other direction.

    `src/programme` may not import `src.execution` or `src.worker`; that is the
    price of being the one package permitted a model client. The import test
    enforces it on source. This enforces it on keys, which is where it matters
    once the model is running: a process holding ALPACA_KEY_ID and
    ALPACA_SECRET_KEY can place an order with a hand-built HTTP request and no
    import at all.
    """

    @pytest.mark.parametrize("name", VENUE_KEYS)
    def test_the_programme_blanks_it(self, name: str) -> None:
        assert _blanks("programme", name), (
            f"the programme must blank {name}. It shares env_file: .env with "
            "the worker, so without the override the one process holding a "
            "model client also holds a key that can place an order."
        )

    @pytest.mark.parametrize("name", MODEL_KEYS)
    def test_the_programme_keeps_its_model_keys(self, name: str) -> None:
        """
        The other direction again. Blanking every key everywhere would pass
        every prohibition in this file while leaving the programme unable to
        fall back to its environment when the vault is empty.
        """
        assert not _blanks("programme", name), (
            f"the programme is the one process that needs {name}; blanking it "
            "there disables its environment fallback."
        )

    @pytest.mark.parametrize("name", BROKER_KEYS)
    def test_the_worker_keeps_the_broker_keys(self, name: str) -> None:
        assert not _blanks("worker", name), (
            f"the worker is the one process that submits orders and needs "
            f"{name}. Blanking it there stops trading while every isolation "
            "test still passes."
        )

    def test_the_broker_keys_are_the_names_the_code_reads(self) -> None:
        """
        Every assertion above is about a *name*, and a name is only worth
        checking while the code still reads it. Were ALPACA_KEY_ID renamed, the
        programme would blank a variable nothing reads, inherit the one the
        code does, and pass.
        """
        derived = _broker_credentials_in_source(
            (SRC / "config.py").read_text(encoding="utf-8")
        )
        assert derived == set(BROKER_KEYS), (
            f"src/config.py reads the broker credentials from {sorted(derived)}, "
            f"but this file checks {sorted(BROKER_KEYS)}. Update BROKER_KEYS "
            "and the blanks in docker-compose.yml together."
        )

    def test_no_alpaca_credential_is_read_anywhere_else(self) -> None:
        """
        The derivation above follows `get_settings`. A second read somewhere
        else — a script, the broker check, a module reaching past `Settings`
        for a token — would be a credential that derivation cannot see.
        """
        reads: set[str] = set()
        for folder in ("src", "scripts", "tests/e2e"):
            for path in (ROOT / folder).rglob("*.py"):
                reads |= {
                    name
                    for name in _env_reads(path)
                    if "ALPACA" in name or "APCA" in name
                }
        assert set(BROKER_KEYS) <= reads, reads
        unknown = reads - set(BROKER_KEYS) - ALPACA_FLAGS
        assert not unknown, (
            f"{sorted(unknown)} read from the environment and neither a known "
            "broker credential nor a known non-secret flag. If it is a "
            "credential, add it to BROKER_KEYS and blank it in the programme."
        )

    def test_the_reference_venue_key_is_still_called_that(self) -> None:
        assert set(REFERENCE_VENUE_KEYS) <= _env_reads(SRC / "bankr_client.py"), (
            "src/bankr_client.py no longer reads BANKR_API_KEY; update "
            "REFERENCE_VENUE_KEYS and the blank in docker-compose.yml together"
        )


class TestTheSameSeparationWhereTheseActuallyRun:
    """
    The compose file above is how this system runs locally. In the deployment it
    is two GitHub Actions workflows and a Vercel function, and the assertions
    above say nothing about any of them — so the guarantee held exactly where it
    was cheapest to check and nowhere that mattered.

    The mechanism differs. Compose services share `env_file: .env`, so isolation
    there has to be an explicit blank. A workflow job inherits nothing, so
    absence *is* isolation. What survives translation is the rule, not the
    override: the job that submits orders must not name a model key, the job
    that runs the model must not name a venue key, and the job that reads the
    vault must name the key that opens it.
    """

    WORKER = ROOT / ".github/workflows/worker.yml"
    PROGRAMME = ROOT / ".github/workflows/programme.yml"

    def test_the_scan_finds_the_workflows(self) -> None:
        for path in (self.WORKER, self.PROGRAMME):
            assert path.exists(), path

    @pytest.mark.parametrize("name", [SECRETS_KEY, *MODEL_KEYS])
    def test_the_worker_job_names_no_model_key(self, name: str) -> None:
        """
        Matched anywhere in the file, not only in an `env:` block. A step that
        exported one into `$GITHUB_ENV`, or a `secrets:` passed to a reusable
        workflow, would put it in the process just as effectively.
        """
        assert name not in self.WORKER.read_text(encoding="utf-8"), (
            f"worker.yml must not mention {name}. That job holds the broker "
            "credentials and is the only thing here that submits an order. It "
            "can already read every row in the database, so the key is the only "
            "thing stopping it reading a model credential."
        )

    @pytest.mark.parametrize("name", VENUE_KEYS)
    def test_the_programme_job_names_no_venue_key(self, name: str) -> None:
        """
        Anywhere in the file, for the same reason as the worker's test above.
        programme.yml's own header says the job "holds no broker credentials";
        this is what makes that sentence true rather than merely present.
        """
        assert name not in self.PROGRAMME.read_text(encoding="utf-8"), (
            f"programme.yml must not mention {name}. That job is the one "
            "process holding a model client, and a venue key needs no import "
            "to place an order."
        )

    def test_the_programme_job_is_passed_no_alpaca_secret_at_all(self) -> None:
        # Not only the two names above: a new secret called, say,
        # ALPACA_OAUTH_TOKEN would pass the parametrised test and still hand
        # the model's process a way to the venue.
        text = self.PROGRAMME.read_text(encoding="utf-8")
        found = re.findall(r"secrets\.((?:ALPACA|APCA)\w*)", text)
        assert not found, f"programme.yml is passed venue secrets {found}"

    def test_the_programme_job_carries_the_decryption_key(self) -> None:
        """
        The other direction, for the same reason as the compose test above: a
        change that removed the key everywhere would pass every prohibition here
        while quietly making the UI's vault unreadable by the one process that
        needs it.
        """
        assert re.search(
            r"^\s+SECRETS_KEY:\s*\$\{\{\s*secrets\.SECRETS_KEY\s*\}\}\s*$",
            self.PROGRAMME.read_text(encoding="utf-8"),
            re.M,
        ), (
            "programme.yml must pass SECRETS_KEY through. Without it the "
            "credential an operator sets from the UI is stored and never read, "
            "and the runner silently falls back to the environment."
        )


class TestTheRuleAndNotJustTheTwoFilesItWasWrittenAgainst:
    """
    The class above names `worker.yml` and `programme.yml` literally, which was
    right when they were the only two workflows. They are not any more:
    `broker-check.yml` and `deployment-status.yml` both hold the broker
    credentials, and both were added without anything checking them.

    The rule was never "worker.yml is special". It is that a process holding
    the keys to a venue must not also hold the key that decrypts a model
    credential, in either direction, because the combination is what turns a
    leak of one job into a leak of everything. So this reads the rule off the
    directory rather than off a list somebody has to remember to extend.
    """

    WORKFLOWS = sorted((ROOT / ".github/workflows").glob("*.yml"))
    BROKER_MARKERS = VENUE_KEYS
    VAULT_MARKERS = (SECRETS_KEY, *MODEL_KEYS)

    def test_the_scan_finds_workflows(self) -> None:
        assert len(self.WORKFLOWS) >= 4, [p.name for p in self.WORKFLOWS]

    def test_no_job_holds_both_a_venue_key_and_the_vault_key(self) -> None:
        offenders = []
        for path in self.WORKFLOWS:
            text = path.read_text(encoding="utf-8")
            # A workflow that only *mentions* a name in a comment is not
            # holding it. What puts a value in the process is a `secrets.`
            # reference, so that is what is matched.
            holds_broker = any(
                re.search(rf"secrets\.{marker}\b", text)
                for marker in self.BROKER_MARKERS
            )
            holds_vault = [
                marker
                for marker in self.VAULT_MARKERS
                if re.search(rf"secrets\.{marker}\b", text)
            ]
            if holds_broker and holds_vault:
                offenders.append(f"{path.name} also carries {holds_vault}")
        assert not offenders, (
            "these workflows hold both a venue credential and the vault key: "
            f"{offenders}. Split them into separate jobs. A process that can "
            "place an order and decrypt a model credential is the single "
            "compromise this separation exists to prevent, and it does not "
            "become safe because the job is dispatch-only."
        )


#: The name a lookalike reseller's integration uses for the Jev key.
_LOOKALIKE = "JEV_API_KEY"


def _product_files() -> list[pathlib.Path]:
    """
    Everything that runs, configures a process, or tells an operator what to
    set: the code, the images, compose, the deployment manifests, the workflows
    and the example environment. Not the docs or the tests, which may need to
    say the name in order to warn against it.
    """
    web = ROOT / "web"
    candidates = [
        *SRC.rglob("*.py"),
        *(ROOT / "api").rglob("*.py"),
        *(ROOT / "scripts").rglob("*.py"),
        *(p for p in (web / "src").rglob("*") if p.is_file()),
        *(p for p in web.glob("*") if p.is_file() and p.name != "package-lock.json"),
        *(ROOT / ".github/workflows").glob("*.yml"),
        *ROOT.glob("requirements*.txt"),
        *ROOT.glob("Dockerfile*"),
        COMPOSE,
        ROOT / ".env.example",
        ROOT / "render.yaml",
        ROOT / "vercel.json",
    ]
    return sorted({p for p in candidates if p.is_file()})


class TestTheLookalikeNameIsNeverUsed:
    """
    The Jev credential is TYPESAFE_API_KEY. JEV_API_KEY is what a lookalike
    reseller's integration calls it, and nothing here may read, pass or
    document a variable under that name.

    The failure it prevents is quiet. A key issued under the lookalike's name
    is a key for a service this system never chose, and code that reads it
    would send the programme's prompts there and spend there — while looking,
    from every log line, like a working integration.

    Matched case-insensitively: a pydantic-settings field called
    ``jev_api_key`` reads the variable without the upper-case literal ever
    appearing in the source.
    """

    def test_the_scan_covers_what_it_claims(self) -> None:
        files = _product_files()
        for required in (
            COMPOSE,
            ROOT / ".env.example",
            ROOT / ".github/workflows/programme.yml",
            ROOT / ".github/workflows/worker.yml",
            SRC / "config.py",
        ):
            assert required in files, required
        assert len(files) > 50, len(files)

    def test_no_product_file_names_it(self) -> None:
        offenders = [
            str(path.relative_to(ROOT))
            for path in _product_files()
            if re.search(
                _LOOKALIKE,
                path.read_text(encoding="utf-8", errors="replace"),
                re.I,
            )
        ]
        assert not offenders, (
            f"{offenders} name {_LOOKALIKE}. The Jev credential is "
            "TYPESAFE_API_KEY; the other name belongs to a lookalike reseller, "
            "and a key stored under it is a key for someone else's service."
        )
