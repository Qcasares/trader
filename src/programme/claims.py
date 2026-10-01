"""
claims.py
---------
Whether a card asserts a performance figure: the code's own check, and the one
a hypothesis meets before it is stored.

Pure: the standard library, and nothing else, so anything may read it — the
author that runs it on every card, the API an operator's card could pass
through (docs/08 open item 32), and the analysis plan that names it as the
keyword baseline ``guardrail.card`` is measured against (``jev_prereg``).
Moved here verbatim from ``author.py`` in phase C8, where reading it meant
loading the module that prompts a generative model; ``author`` re-exports
every name, so ``author.find_performance_claim`` is this module's function and
every existing import still works. ``tests/unit/test_claims.py``.

Why a card may assert no figure
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The whole arrangement rests on the model never asserting a number, and the
cheapest place to enforce that is at the point the prose is written. A card
claiming "a Sharpe of about 1.2" would, months later, be indistinguishable in
the UI from a measured one. Phase C8 also asks Jev the same question about a
title (``guardrail.card``), in shadow: its answer is recorded, and acted on by
nothing, while this check refuses.
"""

from __future__ import annotations

import re
from typing import Any

#: Words whose appearance beside a number makes a sentence a performance claim.
#:
#: Turnover and capacity are deliberately absent: "roughly twelve rebalances a
#: year" and "around fifty million of capacity" are design estimates the card
#: is supposed to carry, and they are not claims about how well the thing did.
PERFORMANCE_TERMS = (
    "sharpe",
    "sortino",
    "calmar",
    "cagr",
    "return",
    "returns",
    "drawdown",
    "alpha",
    "profit",
    "profitable",
    "pnl",
    "p&l",
    "win rate",
    "hit rate",
    "annualised",
    "annualized",
    "outperform",
)

_NUMBER = re.compile(r"-?\d+(?:[.,]\d+)?%?")

#: How close a number must be to a performance word to count as a claim about
#: it. Wide enough to catch "a Sharpe ratio of roughly 1.2", narrow enough that
#: a number in an unrelated clause of the same paragraph is left alone.
_PROXIMITY = 40


class PerformanceClaimError(ValueError):
    """The model asserted a figure it is not permitted to assert."""


def find_performance_claim(text: str) -> str | None:
    """
    The first numeric performance assertion in ``text``, or ``None``.

    Returns the offending fragment rather than a boolean so the rejection can
    say what it objected to. An operator reading "rejected: contains a
    performance claim" learns nothing; one reading the sentence can judge
    whether the check was right.
    """
    lowered = text.lower()
    for match in _NUMBER.finditer(lowered):
        window_start = max(0, match.start() - _PROXIMITY)
        window = lowered[window_start : match.end() + _PROXIMITY]
        for term in PERFORMANCE_TERMS:
            if term in window:
                start = max(0, match.start() - _PROXIMITY)
                return text[start : match.end() + _PROXIMITY].strip()
    return None


#: Card fields that are *supposed* to contain a threshold.
#:
#: The acceptance and rejection criteria are the falsifiable bar, and the whole
#: design requires them to be numeric and machine-checkable — ``sharpe >= 0.3``
#: is parsed straight into an experiment's preregistered criteria. The
#: distinction the check is drawing is between a figure the model *asserts*
#: about a result and a figure it *commits to being judged against*. The first
#: is a claim; the second is the opposite of one.
NUMERIC_BY_DESIGN = ("acceptance_criteria", "rejection_criteria")


def reject_performance_claims(card: dict[str, Any]) -> None:
    """Raise if any field of a card asserts a figure."""
    for field_name, value in card.items():
        if field_name in NUMERIC_BY_DESIGN:
            continue
        if not isinstance(value, str):
            continue
        offending = find_performance_claim(value)
        if offending is not None:
            raise PerformanceClaimError(
                f"{field_name} asserts a performance figure: {offending!r}. "
                "Figures come from the engine, never from the card."
            )


__all__ = [
    "NUMERIC_BY_DESIGN",
    "PERFORMANCE_TERMS",
    "PerformanceClaimError",
    "find_performance_claim",
    "reject_performance_claims",
]
