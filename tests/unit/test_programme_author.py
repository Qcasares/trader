"""
test_programme_author.py
------------------------
What happens to model output before it becomes a row.

Three checks stand between a reply and the database, and each is here in both
directions: something that should get through, and the specific thing it exists
to stop.

The performance-claim check is the one worth stating plainly. The entire
arrangement rests on the model never asserting a number — every figure in a
programme artefact must trace to a row the engine wrote. A card claiming "a
Sharpe of about 1.2" would sit in the ledger for months, rendered in the same
typeface as a measured one, and nothing downstream would be able to tell them
apart. So it is refused at the only moment it is cheap to refuse.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from src.programme.author import (
    Configuration,
    HypothesisCard,
    PerformanceClaimError,
    find_performance_claim,
    reject_performance_claims,
    validate_configuration,
)
from src.programme.client import ModelOutputError, parse_json_object
from src.programme.gates import REQUIRED_CARD_FIELDS


def _valid_card_payload() -> dict[str, str]:
    payload = {
        "title": "Cross-asset trend persistence",
        "economic_mechanism": (
            "Institutional rebalancing is slow, so a price move is absorbed "
            "over weeks rather than instantly"
        ),
        "why_it_persists": (
            "Mandated rebalancing bands force the other side to trade against "
            "their own view, and the constraint does not go away"
        ),
        "instruments": "Liquid asset-class ETFs",
        "trading_horizon": "Monthly",
        "entry_exit_concept": (
            "Hold an asset while it trades above its long moving average and "
            "hold cash otherwise, rebalanced monthly"
        ),
        "expected_return_source": "A premium for bearing rebalancing pressure",
        "expected_risks": "Whipsaw in range-bound regimes; gap risk overnight",
        "expected_turnover": "Roughly twelve rebalances a year",
        "expected_capacity": "Constrained by ETF depth, not by the signal",
        "data_requirements": "Daily adjusted closes for the universe",
        "alternative_explanations": (
            "A disguised long equity beta bet dressed as a timing rule"
        ),
        "simplest_baseline": "Equal-weight buy and hold over the same universe",
        "falsification_test": (
            "If the signal is randomly permuted across symbols the result "
            "should collapse to the baseline; if it does not, the effect is "
            "not the one described"
        ),
        "acceptance_criteria": "sharpe >= 0.3",
        "rejection_criteria": "sharpe < 0",
        "limitations": "Universe is available only from 2006",
    }
    assert set(REQUIRED_CARD_FIELDS) <= set(payload)
    return payload


class TestCardShape:
    def test_a_complete_card_parses(self) -> None:
        card = HypothesisCard(**_valid_card_payload()).as_card()
        assert "title" not in card
        assert all(card[f] for f in REQUIRED_CARD_FIELDS)

    def test_an_invented_field_is_refused(self) -> None:
        payload = _valid_card_payload()
        payload["expected_sharpe"] = "1.4"
        with pytest.raises(ValidationError):
            HypothesisCard(**payload)

    def test_a_missing_field_is_refused(self) -> None:
        payload = _valid_card_payload()
        del payload["falsification_test"]
        with pytest.raises(ValidationError):
            HypothesisCard(**payload)

    def test_a_one_word_mechanism_is_refused(self) -> None:
        payload = _valid_card_payload()
        payload["economic_mechanism"] = "momentum"
        with pytest.raises(ValidationError):
            HypothesisCard(**payload)


class TestPerformanceClaims:
    @pytest.mark.parametrize(
        "text",
        [
            "We expect a Sharpe ratio of about 1.2 over the period",
            "Returns of roughly 18% a year",
            "The maximum drawdown should stay under 12%",
            "This is profitable in 8 of 10 years",
            "An annualised 14 per cent is the target",
        ],
    )
    def test_a_numeric_claim_is_caught(self, text: str) -> None:
        assert find_performance_claim(text) is not None

    @pytest.mark.parametrize(
        "text",
        [
            "A premium for bearing rebalancing pressure",
            "Roughly twelve rebalances a year",
            "Capacity is constrained by ETF depth",
            "Hold while price exceeds its 210 session moving average",
            "The universe has 5 symbols",
        ],
    )
    def test_ordinary_design_prose_is_left_alone(self, text: str) -> None:
        assert find_performance_claim(text) is None

    def test_a_card_asserting_a_figure_is_rejected(self) -> None:
        card = HypothesisCard(**_valid_card_payload()).as_card()
        card["expected_return_source"] = "A Sharpe of 1.4 from the trend premium"
        with pytest.raises(PerformanceClaimError) as exc:
            reject_performance_claims(card)
        assert "expected_return_source" in str(exc.value)

    def test_the_rejection_quotes_what_it_objected_to(self) -> None:
        """
        "Rejected: performance claim" teaches an operator nothing. The offending
        fragment lets them judge whether the check was right.
        """
        card = {"expected_risks": "we expect a Sharpe of 1.4 here"}
        with pytest.raises(PerformanceClaimError) as exc:
            reject_performance_claims(card)
        assert "Sharpe" in str(exc.value)

    def test_a_clean_card_passes(self) -> None:
        reject_performance_claims(HypothesisCard(**_valid_card_payload()).as_card())

    def test_the_acceptance_bar_is_allowed_to_be_numeric(self) -> None:
        """
        A threshold the model commits to being judged against is the opposite
        of a claim about a result, and the gate parses it directly.
        """
        card = HypothesisCard(**_valid_card_payload()).as_card()
        card["acceptance_criteria"] = "sharpe >= 0.4"
        card["rejection_criteria"] = "max_drawdown < -0.35"
        reject_performance_claims(card)

    def test_a_claim_smuggled_into_another_field_is_still_caught(self) -> None:
        card = HypothesisCard(**_valid_card_payload()).as_card()
        card["expected_risks"] = "Drawdowns beyond 30% have never occurred"
        with pytest.raises(PerformanceClaimError):
            reject_performance_claims(card)


class TestConfigurationValidation:
    def _config(self, **overrides: object) -> Configuration:
        payload: dict[str, object] = {
            "strategy": "asset_class_trend_following",
            "params": {"sma_period": 210},
            "start_session": "2010-01-04",
            "end_session": "2020-12-31",
            "preregistered_criteria": [
                {"metric": "sharpe", "op": ">=", "value": 0.3}
            ],
        }
        payload.update(overrides)
        return Configuration(**payload)  # type: ignore[arg-type]

    def test_a_registered_strategy_with_valid_params_passes(self) -> None:
        validate_configuration(self._config())

    def test_an_unregistered_strategy_is_refused(self) -> None:
        with pytest.raises(ValueError, match="unknown strategy"):
            validate_configuration(self._config(strategy="alpha_machine"))

    def test_an_out_of_schema_parameter_is_refused(self) -> None:
        """
        The strategy's own pydantic model is the arbiter, so this check cannot
        drift from what the engine accepts.
        """
        with pytest.raises(ValueError, match="invalid parameters"):
            validate_configuration(self._config(params={"lookback_weeks": 40}))

    def test_an_out_of_bounds_parameter_is_refused(self) -> None:
        with pytest.raises(ValueError, match="invalid parameters"):
            validate_configuration(self._config(params={"sma_period": 100_000}))

    def test_a_malformed_criterion_is_refused(self) -> None:
        with pytest.raises(ValueError, match="metric, op and value"):
            validate_configuration(
                self._config(preregistered_criteria=[{"metric": "sharpe"}])
            )

    def test_preregistering_nothing_is_refused_at_the_schema(self) -> None:
        with pytest.raises(ValidationError):
            self._config(preregistered_criteria=[])

    def test_the_benchmark_strategy_is_available_to_propose(self) -> None:
        """Gate 1 -> 2 cannot pass without it, so it must be registered."""
        validate_configuration(
            self._config(strategy="buy_and_hold", params={"symbols": ["SPY"]})
        )


class TestReplyParsing:
    def test_a_bare_object_parses(self) -> None:
        assert parse_json_object('{"a": 1}') == {"a": 1}

    def test_a_fenced_object_parses(self) -> None:
        text = "Here you go:\n```json\n{\"a\": 1}\n```"
        assert parse_json_object(text) == {"a": 1}

    def test_prose_alone_is_an_error(self) -> None:
        with pytest.raises(ModelOutputError):
            parse_json_object("I would suggest a momentum strategy.")

    def test_a_json_array_is_an_error(self) -> None:
        with pytest.raises(ModelOutputError):
            parse_json_object(json.dumps([1, 2, 3]))

    def test_a_truncated_object_is_an_error(self) -> None:
        """A partial proposal is an error, not a proposal with fields missing."""
        with pytest.raises(ModelOutputError):
            parse_json_object('{"strategy": "asset_class_trend_following", "par')
