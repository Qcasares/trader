"""
test_jev_check_offline.py
-------------------------
``python -m src.programme.jev_check`` where the SDK is not installed.

The check's SDK behaviour is tested over real HTTP in ``tests/sdk``. What is
tested here is what must hold everywhere, including the unit suite's
environment, which has no SDK: with no key there is nothing to ask and nothing
is imported, and the exit code says so rather than looking like a refusal.
"""

from __future__ import annotations

import sys

import pytest

from src.programme import jev_check


@pytest.mark.parametrize("value", [None, "", "   "])
def test_no_key_is_its_own_exit_code_and_asks_nothing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
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

    assert jev_check.main() == jev_check.NO_KEY
    assert jev_check.KEY_VARIABLE in capsys.readouterr().out
    assert "typesafe_sdk" not in sys.modules


def test_the_exit_codes_are_distinct() -> None:
    assert len({jev_check.OK, jev_check.FAILED, jev_check.NO_KEY}) == 3


def test_it_reads_the_programmes_variable_and_not_the_resellers() -> None:
    assert jev_check.KEY_VARIABLE == "TYPESAFE_API_KEY"
