"""
test_claims.py
--------------
The code's check that a card asserts no performance figure, in its own pure
module from phase C8 (``src/programme/claims.py``).

What must hold:

* **It moved, and nothing else did.** ``author`` re-exports every name, and
  each is the claims module's own object, not a copy: a second
  ``find_performance_claim`` would be a second rule, and the set plan that
  names this one as ``guardrail.card``'s keyword baseline would measure Jev
  against a rule the author no longer applied.
* **The title is screened too** (closes F11). ``propose_hypothesis`` checked
  the card's fields and passed its title unread, so a title carrying a figure
  reached the ledger, a row the UI renders in the same type as a measured
  figure. It is refused now, by code, before anything is stored.
* **It is pure.** The API, the harness and the plan may read it without
  loading a model client
  (``test_import_boundaries.py::test_the_pure_modules_load_nothing``).

The titles here are invented.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.programme import author, claims

#: Every name ``claims`` moved out of ``author``.
MOVED = (
    "PERFORMANCE_TERMS",
    "NUMERIC_BY_DESIGN",
    "PerformanceClaimError",
    "find_performance_claim",
    "reject_performance_claims",
)


def _card(**overrides: str) -> dict[str, str]:
    """A card the model might return, every field filled, and no figure."""
    card = {
        "title": "Slow Rebalancing Behind Invented Cross-Asset Trends",
        "economic_mechanism": (
            "Institutional rebalancing is slow, so a price move is absorbed "
            "over weeks rather than at once"
        ),
        "why_it_persists": (
            "Mandated rebalancing bands make the other side trade against "
            "their own view, and the constraint does not go away"
        ),
        "instruments": "Liquid asset-class funds",
        "trading_horizon": "Monthly",
        "entry_exit_concept": (
            "Hold an asset while it trades above its long average and hold "
            "cash otherwise, rebalanced monthly"
        ),
        "expected_return_source": "A premium for bearing rebalancing pressure",
        "expected_risks": "Whipsaw in sideways markets; gaps overnight",
        "expected_turnover": "Roughly twelve rebalances a year",
        "expected_capacity": "Bounded by fund depth, not by the signal",
        "data_requirements": "Daily adjusted closes for the universe",
        "alternative_explanations": "A disguised long equity bet in a timing rule",
        "simplest_baseline": "Equal-weight buy and hold over the same universe",
        "falsification_test": (
            "Permuting the signal across symbols should collapse the result to "
            "the baseline; if it does not, the effect is not the one described"
        ),
        "acceptance_criteria": "sharpe >= 0.3",
        "rejection_criteria": "sharpe < 0",
        "limitations": "The universe is available only from 2006",
    }
    card.update(overrides)
    return card


def _replying(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> None:
    """The model's reply, without a model: ``author.ask_json`` returns it."""

    async def ask_json(call: Any, api_key: Any, settings: Any) -> dict[str, Any]:
        return dict(payload)

    monkeypatch.setattr(author, "ask_json", ask_json)


async def _propose() -> tuple[str, dict[str, Any]]:
    settings: Any = object()  # read by nothing but the stand-in for the model
    return await author.propose_hypothesis("not-a-key", settings, "context", [])


class TestItMovedAndNothingElseDid:
    @pytest.mark.parametrize("name", MOVED)
    def test_author_re_exports_the_claims_modules_own_object(self, name: str) -> None:
        assert getattr(author, name) is getattr(claims, name)

    def test_the_function_the_plan_names_is_the_authors(self) -> None:
        assert author.find_performance_claim is claims.find_performance_claim

    def test_it_exports_exactly_what_moved(self) -> None:
        assert set(claims.__all__) == set(MOVED)

    def test_the_author_holds_no_copy_of_the_rule(self) -> None:
        """
        The rule is defined once: the author's source holds no definition of
        any moved name, and no terms or proximity of its own.
        """
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(author))
        defined = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        } | {
            target.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        assert defined.isdisjoint({*MOVED, "_NUMBER", "_PROXIMITY"}), defined


class TestTheRuleIsAsItWas:
    @pytest.mark.parametrize(
        "text",
        [
            "A Sharpe ratio of roughly 1.2 after costs",
            "Returns of 14% a year",
            "A drawdown never worse than -8%",
            "It would outperform the index by 3 points",
            "A win rate of 61",
        ],
    )
    def test_a_figure_beside_a_performance_word_is_a_claim(self, text: str) -> None:
        assert claims.find_performance_claim(text) is not None

    @pytest.mark.parametrize(
        "text",
        [
            "Roughly twelve rebalances a year",
            "A 200-day average of invented prices",
            "Momentum in invented mid-cap shares",
            "Sharpe ratios are reported by the engine",
        ],
    )
    def test_a_count_a_parameter_or_a_word_alone_is_not(self, text: str) -> None:
        assert claims.find_performance_claim(text) is None

    def test_the_criteria_may_hold_a_threshold(self) -> None:
        claims.reject_performance_claims(_card())

    def test_any_other_field_may_not(self) -> None:
        with pytest.raises(claims.PerformanceClaimError, match="expected_risks"):
            claims.reject_performance_claims(
                _card(expected_risks="A drawdown of 12% in a bad year")
            )


class TestTheTitleIsScreenedToo:
    async def test_a_title_carrying_a_figure_is_refused_by_code(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        F11: the card's fields were checked and its title was not. Refused
        before anything is returned, so nothing reaches the ledger.
        """
        _replying(monkeypatch, _card(title="Invented Carry With a Sharpe Ratio of 1.4"))
        with pytest.raises(claims.PerformanceClaimError, match="title asserts"):
            await _propose()

    async def test_a_title_with_no_figure_is_proposed_as_written(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        card = _card()
        _replying(monkeypatch, card)
        title, proposed = await _propose()
        assert title == card["title"]
        assert "title" not in proposed

    async def test_the_title_is_read_by_the_same_rule_as_the_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A count or a date in a title is not a claim, as in any field."""
        _replying(monkeypatch, _card(title="Twelve Invented Funds Since 2006"))
        title, _ = await _propose()
        assert title == "Twelve Invented Funds Since 2006"


def test_the_docstring_names_the_error_it_raises() -> None:
    """``PerformanceClaim`` named a class that does not exist."""
    doc = author.propose_hypothesis.__doc__ or ""
    assert ":class:`PerformanceClaimError`" in doc
    assert ":class:`PerformanceClaim`" not in doc
