"""
test_jev_check_offline.py
-------------------------
``python -m src.programme.jev_check`` where the SDK is not installed.

The check's SDK behaviour is tested over real HTTP in ``tests/sdk``. What is
tested here is what must hold everywhere, including the unit suite's
environment, which has no SDK: with no key there is nothing to ask and nothing
is imported, the exit code says which verdict it was, and nothing ``main``
prints — a report line, or an exception it caught — carries the key.
"""

from __future__ import annotations

import importlib.abc
import sys
from collections.abc import Iterator

import pytest

from src.programme import jev_check

KEY = "sk-test-5e1d0c9b8a7f6e5d4c3b"


class _Watch(importlib.abc.MetaPathFinder):
    """Records every attempt to import the SDK, whether or not it is installed."""

    def __init__(self) -> None:
        self.attempts: list[str] = []

    def find_spec(self, name: str, path: object, target: object = None) -> None:
        if name.split(".")[0] == "typesafe_sdk":
            self.attempts.append(name)
        return None


@pytest.fixture
def watch() -> Iterator[_Watch]:
    watcher = _Watch()
    sys.meta_path.insert(0, watcher)
    try:
        yield watcher
    finally:
        sys.meta_path.remove(watcher)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_no_key_is_its_own_exit_code_and_asks_nothing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    watch: _Watch,
    value: str | None,
) -> None:
    if value is None:
        monkeypatch.delenv(jev_check.KEY_VARIABLE, raising=False)
    else:
        monkeypatch.setenv(jev_check.KEY_VARIABLE, value)

    async def refuse(**_: object) -> None:
        raise AssertionError("nothing may be asked without a key")

    monkeypatch.setattr(jev_check.jev_client, "list_models", refuse)
    monkeypatch.setattr(jev_check.jev_client, "ask", refuse)
    # A module imported earlier in the session is found in sys.modules without
    # a finder being asked, so the SDK is taken out of it for the call.
    for name in [n for n in sys.modules if n.split(".")[0] == "typesafe_sdk"]:
        monkeypatch.delitem(sys.modules, name)

    assert jev_check.main() == jev_check.NO_KEY
    assert jev_check.KEY_VARIABLE in capsys.readouterr().out
    assert watch.attempts == []


def test_the_exit_codes_are_distinct() -> None:
    codes = {jev_check.OK, jev_check.FAILED, jev_check.NO_KEY, jev_check.NO_VERDICT}
    assert len(codes) == 4


@pytest.mark.parametrize(
    ("verdict", "code"),
    [
        ("pass", jev_check.OK),
        ("fail", jev_check.FAILED),
        ("no_verdict", jev_check.NO_VERDICT),
    ],
)
def test_main_exits_with_the_verdict_and_never_prints_the_key(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    verdict: jev_check.Verdict,
    code: int,
) -> None:
    """
    ``main`` is what the workflow runs with the real secret. Whatever the lines
    a check came to hold — here, the key itself, as a vendor could echo it —
    none of it reaches the output.
    """
    monkeypatch.setenv(jev_check.KEY_VARIABLE, KEY)

    async def checked(api_key: str) -> jev_check.CheckReport:
        assert api_key == KEY
        report = jev_check.CheckReport(verdict=verdict)
        report.lines.extend([f"models listed for this key: {api_key}", api_key[:14]])
        return report

    monkeypatch.setattr(jev_check, "check", checked)

    assert jev_check.main() == code
    out, err = capsys.readouterr()
    assert KEY not in out + err
    assert KEY[: jev_check.MIN_WITHHELD] not in out + err


def test_a_failure_is_reported_by_class_and_never_by_its_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """SDK releases before 0.7.1 put the key in exception text."""
    monkeypatch.setenv(jev_check.KEY_VARIABLE, KEY)

    async def broken(api_key: str) -> jev_check.CheckReport:
        raise RuntimeError(f"could not authenticate with {api_key}")

    monkeypatch.setattr(jev_check, "check", broken)

    assert jev_check.main() == jev_check.FAILED
    out, err = capsys.readouterr()
    assert "RuntimeError" in out
    assert KEY not in out + err


class TestWithheld:
    def test_the_key_and_every_long_run_of_it_are_withheld(self) -> None:
        line = f"a {KEY} b {KEY[:20]} c {KEY[5 : 5 + jev_check.MIN_WITHHELD]} d"
        shown = jev_check.withheld(line, KEY)
        for start in range(len(KEY) - jev_check.MIN_WITHHELD + 1):
            assert KEY[start : start + jev_check.MIN_WITHHELD] not in shown, shown
        assert shown.startswith("a *** b *** c *** d")

    def test_short_runs_and_other_text_survive(self) -> None:
        line = "request id req_7d2e19c0b4aa, model jev-1.13.0, sk-test"
        assert jev_check.withheld(line, KEY) == line

    def test_a_short_key_is_withheld_whole(self) -> None:
        assert jev_check.withheld("key abc123 here", "abc123") == "key *** here"

    def test_no_key_withholds_nothing(self) -> None:
        assert jev_check.withheld("anything", "") == "anything"


def test_it_reads_the_programmes_variable_and_not_the_resellers() -> None:
    assert jev_check.KEY_VARIABLE == "TYPESAFE_API_KEY"
