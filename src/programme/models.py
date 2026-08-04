"""
models.py
---------
What the programme may be pointed at: a provider, a model, an effort level and
a token ceiling. Pure data and pure validation, no SDK, no I/O.

Its own module for the same structural reason ``flags.py`` is its own module.
The API has to render this catalogue to draw the selector and has to validate
what comes back from it, and the runner has to read the same catalogue to build
the request. The API may not import ``src.programme.client`` — that is asserted
by ``tests/unit/test_import_boundaries.py``, because importing it would drag the
model SDK into the process that commands the worker. Two callers needing one
vocabulary is how a process ends up holding a client it has no business holding,
so the vocabulary lives here and neither caller imports the other.

Three things in here are facts about a vendor's API rather than opinions, and
getting any of them wrong is a 400 at request time rather than a warning:

* **Effort is per-model.** ``output_config.effort`` is accepted by the Claude 5
  family and by Opus 4.6/4.8, and rejected by Haiku 4.5, which has no effort
  parameter at all. ``xhigh`` arrived with Opus 4.7 and is refused by anything
  older. So the supported levels are a property of the model, not a global list,
  and a selector that offers all five for every model is a selector that
  produces errors.
* **Max output is per-model.** 128K everywhere in this catalogue except Haiku
  4.5, which caps at 64K.
* **The price is dated.** Sonnet 5 carries an introductory rate that expires,
  and a figure quoted without the date it was true is the kind of number this
  repository refuses to render elsewhere. Every price here carries
  :data:`PRICES_AS_OF`.

Nothing here defaults on a caller's behalf. :func:`settings_problem` returns a
sentence naming what is wrong rather than repairing it, because a configuration
that silently corrects itself is one an operator cannot reason about.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: When the prices and capabilities below were read from the vendor's
#: documentation. Quoted alongside every figure, because a price with no date is
#: a claim about the present that nobody checked.
PRICES_AS_OF = "2026-06-24"

#: The effort ladder, cheapest first. Order matters: the UI renders it in this
#: order and the operator reads left to right as "more spend".
EFFORT_LEVELS: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")


@dataclass(frozen=True, slots=True)
class Provider:
    """
    A route to a model, and whether this deployment can actually take it.

    ``available`` is false for every provider but one, and that is reported
    rather than hidden. A selector listing only what works tells an operator
    nothing about why the others are missing, and "no adapter is implemented"
    is a different answer from "this provider does not exist" — the same reason
    the programme's unbuilt gate stages return *not met, capability absent*
    instead of quietly passing.
    """

    key: str
    title: str
    available: bool
    #: Why it is unavailable, and what taking it would require. Empty when the
    #: provider is available.
    note: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "available": self.available,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class ModelChoice:
    """One model, with the three things that decide whether a request is valid."""

    id: str
    title: str
    provider: str
    #: Effort levels this model accepts. Empty means the model has no effort
    #: parameter and ``output_config`` must be omitted entirely.
    efforts: tuple[str, ...]
    #: Hard ceiling on ``max_tokens`` for this model.
    max_output: int
    input_usd_per_mtok: float
    output_usd_per_mtok: float
    note: str = ""

    def supports_effort(self, effort: str) -> bool:
        return effort in self.efforts

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "provider": self.provider,
            "efforts": list(self.efforts),
            "max_output": self.max_output,
            "input_usd_per_mtok": self.input_usd_per_mtok,
            "output_usd_per_mtok": self.output_usd_per_mtok,
            "note": self.note,
        }


ANTHROPIC = "anthropic"

PROVIDERS: tuple[Provider, ...] = (
    Provider(
        key=ANTHROPIC,
        title="Anthropic API",
        available=True,
        note="",
    ),
    Provider(
        key="bedrock",
        title="Amazon Bedrock",
        available=False,
        note=(
            "No adapter. Reaching it needs the AnthropicBedrockMantle client "
            "in requirements-programme.txt, an AWS region, and model ids "
            "carrying an 'anthropic.' prefix — the bare ids below are refused "
            "there, so this is a code change rather than a setting."
        ),
    ),
    Provider(
        key="vertex",
        title="Google Vertex AI",
        available=False,
        note=(
            "No adapter. Needs the AnthropicVertex client, a GCP project and "
            "region, and application default credentials rather than an API key."
        ),
    ),
    Provider(
        key="foundry",
        title="Microsoft Foundry",
        available=False,
        note="No adapter. Needs the AnthropicFoundry client and a resource name.",
    ),
)

PROVIDERS_BY_KEY: dict[str, Provider] = {p.key: p for p in PROVIDERS}

#: The models this deployment offers, most capable first.
#:
#: Deliberately short. Every entry here is one an operator has a reason to pick:
#: the top of the range, the default, a cheaper tier, and the one with no effort
#: parameter at all. A catalogue that mirrors the vendor's full list is a
#: catalogue nobody has checked the capabilities of.
MODELS: tuple[ModelChoice, ...] = (
    ModelChoice(
        id="claude-fable-5",
        title="Claude Fable 5",
        provider=ANTHROPIC,
        efforts=EFFORT_LEVELS,
        max_output=128_000,
        input_usd_per_mtok=10.0,
        output_usd_per_mtok=50.0,
        note=(
            "The most capable, and five times the output price of Sonnet 5. "
            "Thinking is always on and cannot be disabled. Requires 30-day "
            "data retention; an organisation set to zero retention has every "
            "request refused with a 400."
        ),
    ),
    ModelChoice(
        id="claude-opus-5",
        title="Claude Opus 5",
        provider=ANTHROPIC,
        efforts=EFFORT_LEVELS,
        max_output=128_000,
        input_usd_per_mtok=5.0,
        output_usd_per_mtok=25.0,
        note="Thinking is on by default. Safety classifiers can decline a request.",
    ),
    ModelChoice(
        id="claude-opus-4-8",
        title="Claude Opus 4.8",
        provider=ANTHROPIC,
        efforts=EFFORT_LEVELS,
        max_output=128_000,
        input_usd_per_mtok=5.0,
        output_usd_per_mtok=25.0,
        note="The previous Opus. Here as a fallback if Opus 5 behaves unexpectedly.",
    ),
    ModelChoice(
        id="claude-sonnet-5",
        title="Claude Sonnet 5",
        provider=ANTHROPIC,
        efforts=EFFORT_LEVELS,
        max_output=128_000,
        input_usd_per_mtok=3.0,
        output_usd_per_mtok=15.0,
        note=(
            "The default. An introductory rate of $2.00/$10.00 applied through "
            f"2026-08-31; the standard price is quoted here so a bill after "
            f"that date is not a surprise. Prices read {PRICES_AS_OF}."
        ),
    ),
    ModelChoice(
        id="claude-haiku-4-5",
        title="Claude Haiku 4.5",
        provider=ANTHROPIC,
        efforts=(),
        max_output=64_000,
        input_usd_per_mtok=1.0,
        output_usd_per_mtok=5.0,
        note=(
            "Has no effort parameter: sending one is a 400, so the effort "
            "selector is disabled when this is chosen. 200K context rather "
            "than 1M. Cheap enough to tick hourly without thinking about it, "
            "and the weakest judgement in the list."
        ),
    ),
)

MODELS_BY_ID: dict[str, ModelChoice] = {m.id: m for m in MODELS}

#: Sonnet, because the work here is judgement about research design rather than
#: describing figures that are already computed. Commentary uses Haiku for the
#: latter and that remains the right choice there.
DEFAULT_MODEL = "claude-sonnet-5"

#: The vendor's own default. Chosen precisely because it is the default: any
#: other value would be this repository inventing a setting and then rendering
#: it as though somebody had agreed it.
DEFAULT_EFFORT = "high"

#: A ceiling, not a request size. Every :class:`~src.programme.client.ModelCall`
#: asks for what its own prompt needs; this caps the largest of them.
DEFAULT_MAX_TOKENS = 2500

#: Floor on ``max_tokens``. Below this a JSON reply of the shape ``author.py``
#: requires cannot fit, and a truncated object is an error rather than a
#: proposal with fields missing.
MIN_MAX_TOKENS = 512

#: How long between scheduled passes, and the floor on it.
#:
#: Hourly because the work a pass can do is bounded by what the worker has
#: finished since the last one, and a backtest takes minutes. The floor exists
#: because this number is a spend control: a tick costs a model call, and a
#: setting of one second would spend continuously.
DEFAULT_TICK_SECONDS = 3600
MIN_TICK_SECONDS = 60
MAX_TICK_SECONDS = 86_400


@dataclass(frozen=True, slots=True)
class ModelSettings:
    """
    Everything needed to make one request, resolved and already validated.

    Constructed only by :func:`build_settings`, which refuses rather than
    repairs. A settings object therefore either describes a request the vendor
    will accept, or does not exist.
    """

    provider: str
    model: str
    effort: str
    max_tokens: int

    @property
    def choice(self) -> ModelChoice:
        return MODELS_BY_ID[self.model]

    @property
    def effort_applies(self) -> bool:
        """Whether ``output_config.effort`` may be sent for this model."""
        return self.choice.supports_effort(self.effort)

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "effort": self.effort,
            "max_tokens": self.max_tokens,
        }


def settings_problem(
    provider: Any, model: Any, effort: Any, max_tokens: Any
) -> str | None:
    """
    Why these values cannot be used, or ``None`` if they can.

    One function, so the API's refusal and the runner's fail-closed read apply
    the same rule. The alternative — validating in the endpoint and trusting the
    row in the runner — is how a value that was rejected at the form still ends
    up in a request, because the row can be written by something other than the
    form.
    """
    entry = PROVIDERS_BY_KEY.get(provider) if isinstance(provider, str) else None
    if entry is None:
        return f"unknown provider {provider!r}; known: {sorted(PROVIDERS_BY_KEY)}"
    if not entry.available:
        return f"provider {entry.key!r} is not available: {entry.note}"

    choice = MODELS_BY_ID.get(model) if isinstance(model, str) else None
    if choice is None:
        return f"unknown model {model!r}; known: {sorted(MODELS_BY_ID)}"
    if choice.provider != entry.key:
        return f"model {choice.id!r} is not offered by provider {entry.key!r}"

    if not isinstance(effort, str) or effort not in EFFORT_LEVELS:
        return f"unknown effort {effort!r}; known: {list(EFFORT_LEVELS)}"
    if choice.efforts and effort not in choice.efforts:
        return (
            f"model {choice.id!r} does not accept effort {effort!r}; "
            f"it accepts {list(choice.efforts)}"
        )
    # A model with no effort parameter is not an error, because some effort
    # value has to be stored for the day the model changes. It is simply not
    # sent — see `ModelSettings.effort_applies`.

    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int):
        # `True` is an int in Python and is not a token count. The same quiet
        # wrongness `flags.max_auto_stage` refuses.
        return f"max_tokens must be an integer, got {max_tokens!r}"
    if max_tokens < MIN_MAX_TOKENS:
        return f"max_tokens must be at least {MIN_MAX_TOKENS}, got {max_tokens}"
    if max_tokens > choice.max_output:
        return (
            f"max_tokens {max_tokens} exceeds the {choice.max_output} ceiling "
            f"for {choice.id!r}"
        )
    return None


def build_settings(
    provider: Any, model: Any, effort: Any, max_tokens: Any
) -> ModelSettings:
    """Validate and construct. Raises :class:`ValueError` naming the problem."""
    problem = settings_problem(provider, model, effort, max_tokens)
    if problem is not None:
        raise ValueError(problem)
    return ModelSettings(
        provider=str(provider),
        model=str(model),
        effort=str(effort),
        max_tokens=int(max_tokens),
    )


def tick_seconds_problem(value: Any) -> str | None:
    """Why this tick interval cannot be used, or ``None``."""
    if isinstance(value, bool) or not isinstance(value, int):
        return f"tick interval must be an integer number of seconds, got {value!r}"
    if value < MIN_TICK_SECONDS:
        return (
            f"tick interval must be at least {MIN_TICK_SECONDS}s; a shorter "
            "one spends at a model API faster than the worker can finish the "
            "backtests a pass depends on"
        )
    if value > MAX_TICK_SECONDS:
        return f"tick interval must be at most {MAX_TICK_SECONDS}s, got {value}"
    return None


def catalogue() -> dict[str, Any]:
    """The whole vocabulary, for the selector to render."""
    return {
        "providers": [p.as_dict() for p in PROVIDERS],
        "models": [m.as_dict() for m in MODELS],
        "efforts": list(EFFORT_LEVELS),
        "prices_as_of": PRICES_AS_OF,
        "limits": {
            "min_max_tokens": MIN_MAX_TOKENS,
            "min_tick_seconds": MIN_TICK_SECONDS,
            "max_tick_seconds": MAX_TICK_SECONDS,
        },
        "defaults": {
            "provider": ANTHROPIC,
            "model": DEFAULT_MODEL,
            "effort": DEFAULT_EFFORT,
            "max_tokens": DEFAULT_MAX_TOKENS,
            "tick_seconds": DEFAULT_TICK_SECONDS,
        },
    }


__all__ = [
    "ANTHROPIC",
    "DEFAULT_EFFORT",
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_MODEL",
    "DEFAULT_TICK_SECONDS",
    "EFFORT_LEVELS",
    "MAX_TICK_SECONDS",
    "MIN_MAX_TOKENS",
    "MIN_TICK_SECONDS",
    "MODELS",
    "MODELS_BY_ID",
    "PRICES_AS_OF",
    "PROVIDERS",
    "PROVIDERS_BY_KEY",
    "ModelChoice",
    "ModelSettings",
    "Provider",
    "build_settings",
    "catalogue",
    "settings_problem",
    "tick_seconds_problem",
]
