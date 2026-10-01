"""
author.py
---------
What the model is allowed to write, and what happens to it before it is stored.

The model does two things in this slice. It drafts hypothesis cards, and it
proposes a configuration — a registered strategy, a parameter set, a universe
and a window — for a hypothesis that has one. It does not measure anything, it
does not conclude anything, and it does not decide anything.

Three checks stand between its reply and the database, and each exists because
of a specific way this could go wrong:

1. **Shape.** The reply is parsed into a pydantic model with ``extra="forbid"``.
   A field nobody asked for is a rejection, not a stored surprise.
2. **Parameters.** A proposed configuration is instantiated through the
   registry, so it is validated by the strategy's own ``params_model``. A
   hallucinated parameter name is an error here rather than a backtest of a
   configuration nobody designed.
3. **Numbers.** A card asserting a performance figure is rejected outright. The
   whole arrangement rests on the model never asserting a number, and the
   cheapest place to enforce that is at the point the prose is written. A card
   claiming "a Sharpe of about 1.2" would, months later, be indistinguishable
   in the UI from a measured one. The title is read too, by the same rule:
   until phase C8 it was the one field the check passed unread (F11).

The check itself lives in :mod:`src.programme.claims`, pure, from phase C8, so
the API, the harness and the analysis plan can read it without loading this
module, which prompts a generative model. Every name is re-exported here, and
each is the claims module's own object: there is one rule, not two.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from src.programme.claims import (
    NUMERIC_BY_DESIGN,
    PERFORMANCE_TERMS,
    PerformanceClaimError,
    find_performance_claim,
    reject_performance_claims,
)
from src.programme.client import ModelCall, ask_json
from src.programme.gates import REQUIRED_CARD_FIELDS
from src.programme.models import ModelSettings
from src.strategies import build_strategy, describe_all, get_strategy_class

logger = logging.getLogger(__name__)

#: Re-exported from :mod:`src.programme.claims`, where they moved in phase C8:
#: every import of them from here still works, and reads the one rule.
__all__ = [
    "NUMERIC_BY_DESIGN",
    "PERFORMANCE_TERMS",
    "Configuration",
    "HypothesisCard",
    "PerformanceClaimError",
    "find_performance_claim",
    "propose_configuration",
    "propose_hypothesis",
    "reject_performance_claims",
    "validate_configuration",
]


# ---------------------------------------------------------------------------
# The shapes the model may return
# ---------------------------------------------------------------------------


class HypothesisCard(BaseModel):
    """
    A hypothesis card, section 7.1.

    ``extra="forbid"`` because a model that invents a field is a model whose
    other fields deserve a second look, and because the gate checks presence of
    a fixed list — an unexpected key would be stored and never read.
    """

    model_config = {"extra": "forbid"}

    title: str = Field(min_length=8)
    economic_mechanism: str = Field(min_length=20)
    why_it_persists: str = Field(min_length=20)
    instruments: str = Field(min_length=2)
    trading_horizon: str = Field(min_length=2)
    entry_exit_concept: str = Field(min_length=20)
    expected_return_source: str = Field(min_length=10)
    expected_risks: str = Field(min_length=10)
    expected_turnover: str = Field(min_length=2)
    expected_capacity: str = Field(min_length=2)
    data_requirements: str = Field(min_length=5)
    alternative_explanations: str = Field(min_length=10)
    simplest_baseline: str = Field(min_length=10)
    falsification_test: str = Field(min_length=20)
    acceptance_criteria: str = Field(min_length=10)
    rejection_criteria: str = Field(min_length=10)
    limitations: str = ""

    def as_card(self) -> dict[str, Any]:
        card = self.model_dump()
        card.pop("title")
        return card


class Configuration(BaseModel):
    """A hypothesis turned into something the engine can run."""

    model_config = {"extra": "forbid"}

    strategy: str
    params: dict[str, Any] = Field(default_factory=dict)
    start_session: str
    end_session: str
    rationale: str = ""
    #: The acceptance test, fixed here and immutable once the experiment row
    #: exists. Each entry is {"metric", "op", "value"}.
    preregistered_criteria: list[dict[str, Any]] = Field(min_length=1)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_CARD_SYSTEM = """\
You are the quantitative research lead of a systematic trading programme. You \
write hypothesis cards. You do not measure anything, you do not report \
results, and nothing you write causes a trade.

Rules, all of them hard:
- Never state a performance figure. No Sharpe ratio, no return, no drawdown, \
no win rate, not as a target and not as an expectation. Figures come from the \
backtest engine; a card that contains one is rejected outright.
- The economic mechanism must name who is on the other side of the trade and \
why they accept the worse expected outcome.
- The falsification test must be a specific, runnable check that would show \
the hypothesis is wrong. "It stops working" is not one.
- The simplest credible baseline must be simpler than the hypothesis, and it \
must be something the described engine could actually run.
- Reply with a single JSON object and nothing else.
"""

_CONFIG_SYSTEM = """\
You are the quantitative research lead choosing how to test a hypothesis with \
the strategy implementations that already exist. You do not write code and you \
cannot invent a strategy.

Rules:
- `strategy` must be one of the registered names given to you.
- `params` must use only the parameters in that strategy's schema, within the \
stated bounds.
- `preregistered_criteria` is the acceptance test, fixed now, before the run. \
It cannot be changed afterwards. Each entry is {"metric", "op", "value"} where \
op is one of >=, >, <=, <, ==, !=. Available metrics include sharpe, cagr, \
total_return, max_drawdown, volatility, turnover_annual and exposure.
- Choose criteria a mediocre strategy would fail. A threshold everything \
clears is not a test.
- Reply with a single JSON object and nothing else.
"""


async def propose_hypothesis(
    api_key: str | None,
    settings: ModelSettings,
    context: str,
    existing_titles: list[str],
) -> tuple[str, dict[str, Any]]:
    """
    Draft one hypothesis card. Returns ``(title, card)``.

    Raises :class:`PerformanceClaimError` or ``ValidationError`` rather than
    returning a degraded card. A rejected draft is recorded as a rejected draft
    in the tick's actions; it is not quietly repaired. The title is screened
    with the card, by the same rule: a title carrying a figure is refused here,
    by code, before anything is stored (``tests/unit/test_claims.py``).
    """
    prompt = (
        "Propose one new trading hypothesis for this programme.\n\n"
        f"Programme context:\n{context}\n\n"
        "Hypotheses already in the ledger, which you must not restate:\n"
        + ("\n".join(f"- {t}" for t in existing_titles) or "- (none yet)")
        + "\n\nReturn a JSON object with exactly these keys: title, "
        + ", ".join(HypothesisCard.model_fields.keys() - {"title"})
        + "."
    )
    payload = await ask_json(
        ModelCall(system=_CARD_SYSTEM, prompt=prompt, max_tokens=5000),
        api_key,
        settings,
    )
    card_model = HypothesisCard(**payload)
    card = card_model.as_card()
    reject_performance_claims({"title": card_model.title, **card})
    missing = [f for f in REQUIRED_CARD_FIELDS if not str(card.get(f, "")).strip()]
    if missing:
        raise ValueError(f"card is missing required fields: {missing}")
    return card_model.title, card


async def propose_configuration(
    api_key: str | None,
    settings: ModelSettings,
    hypothesis: dict[str, Any],
) -> Configuration:
    """
    Choose a registered strategy and parameters to test a hypothesis with.

    The returned configuration has already been instantiated through the
    registry, so its parameters are valid by the strategy's own definition
    rather than by this module's opinion of them.
    """
    catalogue = describe_all()
    prompt = (
        "Choose how to test this hypothesis using one of the registered "
        "strategies.\n\n"
        f"Hypothesis: {hypothesis.get('title')}\n"
        f"Card: {hypothesis.get('card')}\n\n"
        f"Registered strategies and their parameter schemas:\n{catalogue}\n\n"
        "Return a JSON object with keys: strategy, params, start_session "
        "(YYYY-MM-DD), end_session (YYYY-MM-DD), rationale, "
        "preregistered_criteria."
    )
    payload = await ask_json(
        ModelCall(system=_CONFIG_SYSTEM, prompt=prompt, max_tokens=3000),
        api_key,
        settings,
    )
    config = Configuration(**payload)
    validate_configuration(config)
    return config


def validate_configuration(config: Configuration) -> None:
    """
    Check a proposal against the registry, raising with the reason.

    Separate from :func:`propose_configuration` so the API can apply exactly
    the same check to an operator-authored configuration. One definition of
    valid, used by both paths.
    """
    try:
        get_strategy_class(config.strategy)
    except KeyError as exc:
        raise ValueError(str(exc)) from None
    try:
        build_strategy(config.strategy, config.params)
    except ValidationError as exc:
        raise ValueError(f"invalid parameters: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - surfaced verbatim
        raise ValueError(f"invalid parameters: {exc}") from exc

    for criterion in config.preregistered_criteria:
        if not {"metric", "op", "value"} <= set(criterion):
            raise ValueError(
                "each preregistered criterion needs metric, op and value; "
                f"got {sorted(criterion)}"
            )
