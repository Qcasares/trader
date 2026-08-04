"""
test_model_request.py
---------------------
What ``ask_json`` actually puts on the wire.

This file installs a fake ``anthropic`` module, which the rest of this suite
avoids on principle — mocking a boundary only proves the mock matches your
assumption about it. It is proportionate here for a reason the other boundaries
do not share: the assertion is about the **request this code builds**, not about
what the vendor does with it. The fake never simulates the vendor's behaviour;
it records a dict and hands back a fixed reply.

The alternative is no coverage at all. ``anthropic`` is deliberately absent from
``requirements.txt`` and ``requirements-dev.txt`` — the whole unit suite runs
with no SDK present, which is the arrangement that keeps the engine testable
without one — so there is nothing to call, and the two lines worth testing are
exactly the two that produce a vendor 400 when wrong:

* ``output_config.effort`` must be omitted for a model that has no effort
  parameter, and present for one that does;
* ``max_tokens`` must be the smaller of what the prompt needs and what the
  operator allowed.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from src.programme import models
from src.programme.client import ModelCall, ModelUnavailableError, ask_json


class _Reply:
    """A response shaped like the one block of text the client reads."""

    def __init__(self, text: str) -> None:
        block = types.SimpleNamespace(type="text", text=text)
        self.content = [block]


class _Messages:
    def __init__(self, recorder: dict[str, Any], reply: str) -> None:
        self._recorder = recorder
        self._reply = reply

    async def create(self, **kwargs: Any) -> _Reply:
        self._recorder.clear()
        self._recorder.update(kwargs)
        return _Reply(self._reply)


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Installs the fake SDK and yields the kwargs of the last request."""
    recorder: dict[str, Any] = {}

    class FakeAsyncAnthropic:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key
            self.messages = _Messages(recorder, '{"ok": true}')

    module = types.ModuleType("anthropic")
    module.AsyncAnthropic = FakeAsyncAnthropic  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "anthropic", module)
    return recorder


CALL = ModelCall(system="s", prompt="p", max_tokens=2000)


def _settings(model: str, effort: str = "high", max_tokens: int = 2500):
    return models.build_settings(models.ANTHROPIC, model, effort, max_tokens)


class TestEffortIsSentOnlyWhereItIsAccepted:
    async def test_a_model_with_effort_gets_output_config(self, sent) -> None:
        choice = next(c for c in models.MODELS if c.efforts)
        await ask_json(CALL, "key", _settings(choice.id, choice.efforts[-1]))
        assert sent["output_config"] == {"effort": choice.efforts[-1]}

    async def test_a_model_without_effort_gets_no_output_config(self, sent) -> None:
        """
        Sending ``output_config`` to a model with no effort parameter is a 400,
        and it would be a 400 on every pass — a configuration change that
        silently stops the programme proposing anything.
        """
        choice = next(c for c in models.MODELS if not c.efforts)
        await ask_json(CALL, "key", _settings(choice.id))
        assert "output_config" not in sent

    async def test_the_chosen_model_is_the_model_sent(self, sent) -> None:
        await ask_json(CALL, "key", _settings("claude-opus-5", "low"))
        assert sent["model"] == "claude-opus-5"


class TestTheCeilingBinds:
    async def test_the_operators_ceiling_wins_when_it_is_lower(self, sent) -> None:
        """
        The ceiling is a spend control, so it beats the caller's request. A
        prompt asking for more than the operator allowed gets the operator's
        number, not its own.
        """
        await ask_json(CALL, "key", _settings(models.DEFAULT_MODEL, max_tokens=1000))
        assert sent["max_tokens"] == 1000

    async def test_the_call_wins_when_it_asks_for_less(self, sent) -> None:
        await ask_json(CALL, "key", _settings(models.DEFAULT_MODEL, max_tokens=8000))
        assert sent["max_tokens"] == CALL.max_tokens


class TestItRefusesRatherThanGuesses:
    async def test_no_api_key_raises(self, sent) -> None:
        with pytest.raises(ModelUnavailableError, match="ANTHROPIC_API_KEY"):
            await ask_json(CALL, None, _settings(models.DEFAULT_MODEL))
        assert not sent

    async def test_a_provider_with_no_client_raises_before_any_request(
        self, sent
    ) -> None:
        """
        The catalogue refuses an unavailable provider at the form, so this path
        is reachable only by a row written some other way. It still refuses,
        because "something upstream would have caught it" is not a reason to
        send a request under a configuration nobody chose.
        """
        settings = models.ModelSettings(
            provider="bedrock",
            model=models.DEFAULT_MODEL,
            effort="high",
            max_tokens=2500,
        )
        with pytest.raises(ModelUnavailableError, match="no client"):
            await ask_json(CALL, "key", settings)
        assert not sent


class TestNoToolsReachTheModel:
    async def test_the_request_grants_no_ability_to_act(self, sent) -> None:
        """
        The structural version of this lives in ``test_import_boundaries.py``,
        which refuses the string in the source. This is the same guarantee
        observed at the wire: whatever the code does, nothing that could let the
        model call a function comes out of it.
        """
        await ask_json(CALL, "key", _settings(models.DEFAULT_MODEL))
        assert "tools" not in sent
        assert "tool_choice" not in sent
        assert set(sent) <= {
            "model",
            "max_tokens",
            "system",
            "messages",
            "output_config",
        }
