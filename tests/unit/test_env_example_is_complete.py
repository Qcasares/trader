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

ROOT = pathlib.Path(__file__).resolve().parents[2]
ENV_EXAMPLE = ROOT / ".env.example"

#: Every way this codebase reads an environment variable, subscript access
#: included — ``os.environ["BANKR_API_KEY"]`` is a real call site and matching
#: only ``.get`` would report it as undocumented.
_READS = re.compile(
    r'(?:os\.environ\.get|os\.getenv|_bool_env|_int_env)\(\s*"([A-Z][A-Z0-9_]*)"'
    r'|os\.environ\[\s*"([A-Z][A-Z0-9_]*)"\s*\]'
)

#: Assignments in .env.example, commented-out ones included — a variable
#: documented but left blank still counts as documented.
_DOCUMENTED = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]*)\s*=", re.MULTILINE)

#: Read by tests and tooling rather than by the application, so their absence
#: from an operator's .env is correct.
_NOT_OPERATOR_FACING = frozenset({"TEST_DATABASE_URL", "E2E_BASE_URL", "E2E_PASSWORD",
                                  "E2E_SHOTS", "E2E_CHROMIUM", "API_PASSWORD"})


#: Read by a dependency rather than by us, so they have no call site to find.
#:
#: The Anthropic SDK reads ANTHROPIC_API_KEY itself. `src/llm/commentary.py`
#: only mentions it in the log line it emits when commentary is skipped — and
#: that is deliberate: the SDK is imported lazily and the engine must run, and
#: be testable, with no LLM library present at all.
_READ_BY_A_DEPENDENCY = frozenset({"ANTHROPIC_API_KEY"})


def _read_by_source() -> set[str]:
    names: set[str] = set()
    for path in (ROOT / "src").rglob("*.py"):
        for groups in _READS.findall(path.read_text(encoding="utf-8")):
            names.update(name for name in groups if name)
    return (names | _READ_BY_A_DEPENDENCY) - _NOT_OPERATOR_FACING


def _documented() -> set[str]:
    return set(_DOCUMENTED.findall(ENV_EXAMPLE.read_text(encoding="utf-8")))


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


class TestTheDangerousDefaultsAreSafe:
    """
    The example is what people copy. Every value in it that could reach real
    money must be inert as shipped.
    """

    @pytest.mark.parametrize(
        "setting", ["LIVE_TRADING_ENABLED", "ALPACA_ALLOW_LIVE"]
    )
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
        text = ENV_EXAMPLE.read_text(encoding="utf-8")
        for name in (
            "SESSION_SECRET",
            "ADMIN_PASSWORD_HASH",
            "POSTGRES_PASSWORD",
            "ALPACA_KEY_ID",
            "ALPACA_SECRET_KEY",
            "CRON_SECRET",
            "ANTHROPIC_API_KEY",
            "BANKR_API_KEY",
        ):
            match = re.search(rf"^{name}=(.*)$", text, re.MULTILINE)
            assert match, f"{name} is missing from .env.example"
            assert not match.group(1).strip(), (
                f"{name} ships with a value; credentials must be blank"
            )
