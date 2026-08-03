"""
client.py
---------
The model client. The only one in the system.

Imported lazily, exactly as ``src/llm/commentary.py`` does it, so the package
can be imported and tested without an LLM SDK installed. ``anthropic`` lives in
``requirements-programme.txt`` and in neither of the other two requirements
files, because the engine must run and be testable without one anywhere near
it.

No tools are passed. The model can emit text and nothing else — it cannot call
a function, reach a broker, or write a row. Everything it produces is parsed,
validated and written by code in this package that it does not control.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

#: Sonnet, because the work here is judgement about research design rather than
#: describing figures that are already computed. Commentary uses Haiku for the
#: latter and that remains the right choice there.
DEFAULT_MODEL = "claude-sonnet-5"

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


class ModelUnavailableError(RuntimeError):
    """No API key, or no SDK. Never fatal — the tick continues without it."""


class ModelOutputError(ValueError):
    """The model returned something that is not the requested JSON."""


@dataclass(frozen=True, slots=True)
class ModelCall:
    """One request, kept small enough to log whole."""

    system: str
    prompt: str
    max_tokens: int = 2000


async def ask_json(
    call: ModelCall, api_key: str | None, model: str = DEFAULT_MODEL
) -> dict[str, Any]:
    """
    Send a prompt and parse the JSON object it returns.

    Raises rather than returning a default. A tick that cannot reach the model
    should record that it could not, not proceed on an empty proposal that
    later reads like a considered one.
    """
    if not api_key:
        raise ModelUnavailableError("ANTHROPIC_API_KEY is not set")

    try:
        from anthropic import AsyncAnthropic
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ModelUnavailableError(
            "anthropic is not installed; install requirements-programme.txt"
        ) from exc

    client = AsyncAnthropic(api_key=api_key)
    response = await client.messages.create(
        model=model,
        max_tokens=call.max_tokens,
        system=call.system,
        messages=[{"role": "user", "content": call.prompt}],
    )
    text = "\n".join(
        block.text for block in response.content if block.type == "text"
    ).strip()
    return parse_json_object(text)


def parse_json_object(text: str) -> dict[str, Any]:
    """
    Pull one JSON object out of a model's reply.

    Tolerant of a fenced block or a sentence of preamble, because those are
    formatting slips rather than semantic ones, and intolerant of anything
    else. What it will not do is guess at a partial object: a truncated
    proposal is an error, not a proposal with fields missing.
    """
    candidate = text
    match = _JSON_BLOCK.search(text)
    if match:
        candidate = match.group(0)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ModelOutputError(f"reply is not JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ModelOutputError(f"expected a JSON object, got {type(parsed).__name__}")
    return parsed
