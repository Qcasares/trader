"""
test_env_example_is_complete.py
-------------------------------
That ``.env.example`` describes every setting the code actually reads.

It is the only inventory of what this system can be configured with. When it
falls behind, a setting exists, changes behaviour, and is invisible to the
person deploying — which is how `SERVERLESS_DRAIN_ENABLED` came to be
*required* for the Vercel deployment while appearing nowhere an operator would
look. Seven settings had drifted out of it by the time this was written,
including all three that a serverless deploy cannot work without.

Enforced rather than remembered, because the failure is silent in both
directions: an undocumented setting is one nobody knows to set, and a
documented one that no longer exists is a lie that survives until someone
wastes an afternoon on it.

The check reads the shipped source for the real call sites rather than keeping
a hand-written list, since a hand-written list is one more thing that drifts —
in the same direction, for the same reason.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from src.db.repos import secrets as secret_repo

ROOT = pathlib.Path(__file__).resolve().parents[2]
ENV_EXAMPLE = ROOT / ".env.example"

#: Every way this codebase reads an environment variable, subscript access
#: included — ``os.environ["BANKR_API_KEY"]`` is a real call site and matching
#: only ``.get`` would report it as undocumented.
#:
#: A subscript that is assigned to is a write, not a read, and is not counted.
#: The Jev client sets ``TYPESAFE_LOG_LEVEL`` to ``off`` before the TypeSafe SDK
#: is imported, precisely so that whatever an operator sets changes nothing;
#: counting that line as a read would demand an entry here saying the opposite.
_READS = re.compile(
    r"""(?:os\.environ\.get|os\.getenv|_bool_env|_int_env)"""
    r"""\(\s*["']([A-Z][A-Z0-9_]*)["']"""
    r"""|os\.environ\[\s*["']([A-Z][A-Z0-9_]*)["']\s*\](?!\s*=(?!=))"""
)

#: Assignments in .env.example, commented-out ones included — a variable
#: documented but left blank still counts as documented.
_DOCUMENTED = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]*)\s*=", re.MULTILINE)

#: Read by tests and tooling rather than by the application, so their absence
#: from an operator's .env is correct.
_NOT_OPERATOR_FACING = frozenset(
    {
        "TEST_DATABASE_URL",
        "E2E_BASE_URL",
        "E2E_PASSWORD",
        "E2E_SHOTS",
        "E2E_CHROMIUM",
        "API_PASSWORD",
    }
)


#: Read by a dependency rather than by us, so they have no call site to find.
#:
#: The Anthropic SDK reads ANTHROPIC_API_KEY itself. `src/llm/commentary.py`
#: only mentions it in the log line it emits when commentary is skipped — and
#: that is deliberate: the SDK is imported lazily and the engine must run, and
#: be testable, with no LLM library present at all.
_READ_BY_A_DEPENDENCY = frozenset({"ANTHROPIC_API_KEY"})

#: A credential's name, by the endings this codebase gives them. Every
#: documented name that matches must ship blank. Derived rather than listed, so
#: the next credential is checked the day it is documented rather than the day
#: somebody remembers to add it to a list: TYPESAFE_API_KEY had to be added by
#: hand, and SECRETS_KEY, which decrypts every stored credential, had never been
#: checked at all.
_CREDENTIAL = re.compile(r"_(?:KEY|KEY_ID|SECRET|PASSWORD|PASSWORD_HASH|TOKEN)$")

#: The credentials this file is known to carry. Not the list that is checked —
#: that is derived with :data:`_CREDENTIAL` — but the floor the derivation must
#: reach, so that a change to the pattern cannot quietly check nothing.
_KNOWN_CREDENTIALS = (
    "SESSION_SECRET",
    "ADMIN_PASSWORD_HASH",
    "POSTGRES_PASSWORD",
    "SECRETS_KEY",
    "ALPACA_KEY_ID",
    "ALPACA_SECRET_KEY",
    "CRON_SECRET",
    "ANTHROPIC_API_KEY",
    "TYPESAFE_API_KEY",
    "BANKR_API_KEY",
)


def _reads_in(source: str) -> set[str]:
    return {name for groups in _READS.findall(source) for name in groups if name}


def _read_by_source() -> set[str]:
    names: set[str] = set()
    for path in (ROOT / "src").rglob("*.py"):
        names |= _reads_in(path.read_text(encoding="utf-8"))
    return (names | _READ_BY_A_DEPENDENCY) - _NOT_OPERATOR_FACING


def _documented() -> set[str]:
    return set(_DOCUMENTED.findall(ENV_EXAMPLE.read_text(encoding="utf-8")))


def _shipped_value(name: str) -> str | None:
    """What ``.env.example`` assigns ``name``, commented out or not."""
    match = re.search(
        rf"^\s*#?\s*{re.escape(name)}\s*=(.*)$",
        ENV_EXAMPLE.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    return None if match is None else match.group(1).strip()


class TestTheScanReadsWhatItClaims:
    """
    Guards the guard, from both sides. A scan that missed a spelling would pass
    an undocumented setting; one that counted a write as a read would demand
    documentation for a variable the code overrides.
    """

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ('os.environ.get("LOG_LEVEL", "INFO")', {"LOG_LEVEL"}),
            ("os.environ.get('LOG_LEVEL')", {"LOG_LEVEL"}),
            ('os.getenv("CRON_SECRET")', {"CRON_SECRET"}),
            (
                '_bool_env("SERVERLESS_DRAIN_ENABLED", False)',
                {"SERVERLESS_DRAIN_ENABLED"},
            ),
            ('_int_env("DB_POOL_MAX_SIZE", 10)', {"DB_POOL_MAX_SIZE"}),
            ('key = os.environ["BANKR_API_KEY"]', {"BANKR_API_KEY"}),
            ('if os.environ["WORKER_ID"] == "worker-1": ...', {"WORKER_ID"}),
            ('os.environ["TYPESAFE_LOG_LEVEL"] = "off"', set()),
            ('os.environ["TYPESAFE_LOG_LEVEL"]="off"', set()),
        ],
    )
    def test_it_counts_reads_and_not_writes(
        self, source: str, expected: set[str]
    ) -> None:
        assert _reads_in(source) == expected


class TestTheInventoryIsComplete:
    def test_the_scan_found_something(self) -> None:
        # Guards the guard. If the accessors are ever renamed, every assertion
        # below would pass vacuously against an empty set.
        assert len(_read_by_source()) >= 10, _read_by_source()

    def test_every_setting_the_code_reads_is_documented(self) -> None:
        missing = _read_by_source() - _documented()
        assert not missing, (
            f".env.example does not mention {sorted(missing)}. A setting that "
            "changes behaviour and appears nowhere an operator looks is one "
            "nobody knows to set — which is exactly how a required serverless "
            "flag stayed invisible."
        )

    def test_no_setting_is_assigned_twice(self) -> None:
        """
        One name, one assignment.

        A ``.env`` is last-assignment-wins, so a variable listed twice is a trap
        rather than a duplication: whoever fills in the first one and leaves the
        second blank ends up with the empty value and no error anywhere.

        ``ANTHROPIC_API_KEY`` was listed twice — once for the commentary layer
        and once for the AI programme, each with its own honest explanation of
        what that consumer does without it. Both were correct in isolation and
        together they silently produced a programme that proposed nothing.
        """
        assignments = _DOCUMENTED.findall(ENV_EXAMPLE.read_text(encoding="utf-8"))
        seen: dict[str, int] = {}
        for name in assignments:
            seen[name] = seen.get(name, 0) + 1
        duplicated = sorted(name for name, count in seen.items() if count > 1)
        assert not duplicated, (
            f".env.example assigns {duplicated} more than once. A .env is "
            "last-assignment-wins, so the earlier one is silently discarded — "
            "document a setting once and cross-reference it from the other "
            "section."
        )

    def test_nothing_documented_has_been_deleted(self) -> None:
        """
        The other direction. A variable in the example that no longer exists
        sends someone hunting for why setting it changed nothing.

        POSTGRES_PASSWORD is read by docker-compose rather than by Python, so
        it is legitimately here and not in the source scan.
        """
        compose_only = {"POSTGRES_PASSWORD"}
        stale = _documented() - _read_by_source() - compose_only
        assert not stale, (
            f".env.example documents {sorted(stale)}, which nothing reads any "
            "more. Delete them — a stale entry is a lie with a long half-life."
        )


class TestTheVaultAndTheEnvironmentAgree:
    """
    A credential the configuration page can store is one the programme also
    reads from its own environment, under the same name in capitals: the vault
    first and the environment second. Both halves have to be findable. A key
    the vault holds that this file never mentions is a fallback nobody knows
    exists, and a model key documented here that the vault cannot hold is one
    an operator can only supply with shell access to the host.

    When the TypeSafe key joined the vault, adding it here was a step to be
    remembered. It is now a step that cannot be forgotten.
    """

    def test_every_secret_the_vault_holds_is_documented_blank(self) -> None:
        for name in secret_repo.KNOWN_SECRETS:
            variable = name.upper()
            value = _shipped_value(variable)
            assert value is not None, (
                f"the vault holds {name!r}, and the programme falls back to "
                f"{variable} in its environment, but .env.example never "
                "mentions it"
            )
            assert not value, f"{variable} ships with a value; credentials are blank"

    def test_both_model_keys_can_be_set_from_the_configuration_page(self) -> None:
        vault = {name.upper() for name in secret_repo.KNOWN_SECRETS}
        assert {"ANTHROPIC_API_KEY", "TYPESAFE_API_KEY"} <= vault

    @pytest.mark.parametrize("name", secret_repo.KNOWN_SECRETS)
    def test_the_scheduled_programme_is_handed_every_fallback(self, name: str) -> None:
        """
        The environment half, where the programme actually runs. A fallback
        documented here and never passed to the scheduled job is one that
        works on a developer's machine and nowhere else, so the repository
        secret of the same name is handed through as ANTHROPIC_API_KEY always
        was. Only the programme's workflow: test_secret_isolation.py keeps
        every model key out of the worker's.
        """
        variable = name.upper()
        workflow = ROOT / ".github" / "workflows" / "programme.yml"
        assert re.search(
            rf"^\s+{variable}:\s*\$\{{\{{\s*secrets\.{variable}\s*\}}\}}\s*$",
            workflow.read_text(encoding="utf-8"),
            re.MULTILINE,
        ), (
            f"the vault holds {name!r} and the programme falls back to "
            f"{variable}, but programme.yml never hands it the repository "
            "secret of that name"
        )


class TestTheDangerousDefaultsAreSafe:
    """
    The example is what people copy. Every value in it that could reach real
    money must be inert as shipped.
    """

    @pytest.mark.parametrize("setting", ["LIVE_TRADING_ENABLED", "ALPACA_ALLOW_LIVE"])
    def test_live_gates_ship_false(self, setting: str) -> None:
        text = ENV_EXAMPLE.read_text(encoding="utf-8")
        assert re.search(rf"^{setting}=false\s*$", text, re.MULTILINE), (
            f"{setting} must ship as false in the file people copy"
        )

    def test_the_drain_ships_disabled(self) -> None:
        # Enabled by default it would run backtests inside the API process on
        # every deployment, including the ones that have a worker.
        text = ENV_EXAMPLE.read_text(encoding="utf-8")
        assert re.search(r"^SERVERLESS_DRAIN_ENABLED=false\s*$", text, re.MULTILINE)

    def test_no_secret_has_a_value(self) -> None:
        """
        Every credential ships empty. A placeholder that looks like a password
        is a password somebody will keep, and the API refusing to start beats
        it starting with a key an attacker can read on GitHub.
        """
        credentials = {name for name in _documented() if _CREDENTIAL.search(name)}
        unmatched = set(_KNOWN_CREDENTIALS) - credentials
        assert not unmatched, (
            f"{sorted(unmatched)} are credentials this file carries, and the "
            "pattern that finds credentials no longer finds them (or they have "
            "been removed from the file)"
        )
        for name in sorted(credentials):
            assert not _shipped_value(name), (
                f"{name} ships with a value; credentials must be blank"
            )
