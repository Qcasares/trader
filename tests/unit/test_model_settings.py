"""
test_model_settings.py
----------------------
The catalogue an operator picks from, and the rule that decides whether a pick
is legal.

These are unit tests because ``src/programme/models.py`` is pure: no SDK, no
database, no network. That purity is the point of the module — it is what lets
the API import the vocabulary to draw the selector without importing the code
that holds a model client.

The properties worth asserting are not "the dataclass round-trips". They are
the ones where getting it wrong produces a 400 at a vendor on the next tick, in
a log nobody is reading:

* effort is a per-model capability, not a global list;
* a model with no effort parameter must never be sent one;
* every ceiling in the catalogue is a real ceiling;
* the API and the runner apply the same rule, because they call the same
  function.
"""

from __future__ import annotations

import pytest

from src.programme import models


class TestTheCatalogueIsInternallyConsistent:
    def test_every_model_names_a_known_provider(self) -> None:
        for choice in models.MODELS:
            assert choice.provider in models.PROVIDERS_BY_KEY, choice.id

    def test_every_model_is_offered_by_an_available_provider(self) -> None:
        """
        A catalogue entry nothing can reach is a selector option that produces
        an error on the next tick rather than at the moment it is chosen.
        """
        for choice in models.MODELS:
            assert models.PROVIDERS_BY_KEY[choice.provider].available, choice.id

    def test_every_effort_a_model_claims_is_a_known_level(self) -> None:
        for choice in models.MODELS:
            unknown = set(choice.efforts) - set(models.EFFORT_LEVELS)
            assert not unknown, f"{choice.id} claims {unknown}"

    def test_efforts_are_declared_in_the_ladder_order(self) -> None:
        """
        The UI renders the list as given and the operator reads it as "more
        spend to the right". A model that declared them in another order would
        render a ladder that goes the wrong way for that model alone.
        """
        order = {level: i for i, level in enumerate(models.EFFORT_LEVELS)}
        for choice in models.MODELS:
            positions = [order[e] for e in choice.efforts]
            assert positions == sorted(positions), choice.id

    def test_the_ceiling_leaves_room_for_the_floor(self) -> None:
        for choice in models.MODELS:
            assert choice.max_output >= models.MIN_MAX_TOKENS, choice.id

    def test_output_is_never_cheaper_than_input(self) -> None:
        # Not a law of nature, but true of every model this vendor sells, and a
        # cheap trip-wire for a transposed pair of numbers in the table.
        for choice in models.MODELS:
            assert choice.output_usd_per_mtok >= choice.input_usd_per_mtok, choice.id

    def test_every_price_carries_the_date_it_was_read(self) -> None:
        """
        The same rule the rest of this system applies to a Sharpe ratio: a
        figure without the assumption behind it will be read as a fact.
        """
        assert models.catalogue()["prices_as_of"] == models.PRICES_AS_OF
        assert models.PRICES_AS_OF

    def test_the_defaults_are_usable(self) -> None:
        """
        Migration 0010 seeds exactly these. If they do not validate, a fresh
        database ships a programme that refuses to call a model.
        """
        assert (
            models.settings_problem(
                models.ANTHROPIC,
                models.DEFAULT_MODEL,
                models.DEFAULT_EFFORT,
                models.DEFAULT_MAX_TOKENS,
            )
            is None
        )
        assert models.tick_seconds_problem(models.DEFAULT_TICK_SECONDS) is None


class TestEffortIsAPerModelCapability:
    """
    Haiku 4.5 has no effort parameter and sending one is a 400. That is the
    single most likely way this feature breaks in production, so it is asserted
    from both ends: the catalogue says so, and the settings object refuses to
    claim the field applies.
    """

    def test_at_least_one_model_has_no_effort_parameter(self) -> None:
        # Guards the guard. If every model gained effort, the tests below would
        # pass vacuously and the distinction would quietly stop being tested.
        assert any(not choice.efforts for choice in models.MODELS)

    def test_a_model_without_effort_never_has_it_applied(self) -> None:
        for choice in models.MODELS:
            if choice.efforts:
                continue
            settings = models.build_settings(
                choice.provider, choice.id, models.DEFAULT_EFFORT, 1024
            )
            assert settings.effort_applies is False

    def test_a_model_with_effort_has_it_applied(self) -> None:
        choice = next(c for c in models.MODELS if c.efforts)
        settings = models.build_settings(
            choice.provider, choice.id, choice.efforts[0], 1024
        )
        assert settings.effort_applies is True

    def test_storing_an_effort_for_an_effortless_model_is_not_an_error(self) -> None:
        """
        Deliberately permitted. Some value has to be stored for the day the
        model changes, and refusing the pairing would force an operator to
        re-choose an effort level every time they tried Haiku.
        """
        choice = next(c for c in models.MODELS if not c.efforts)
        assert models.settings_problem(choice.provider, choice.id, "max", 1024) is None

    def test_an_effort_the_model_rejects_is_refused(self) -> None:
        choice = next(c for c in models.MODELS if c.efforts)
        missing = set(models.EFFORT_LEVELS) - set(choice.efforts)
        if not missing:
            pytest.skip("every catalogue model with effort accepts every level")
        problem = models.settings_problem(
            choice.provider, choice.id, sorted(missing)[0], 1024
        )
        assert problem is not None and "does not accept effort" in problem


class TestTheValidatorRefusesRatherThanRepairs:
    def test_an_unknown_provider_is_named(self) -> None:
        problem = models.settings_problem(
            "openai", models.DEFAULT_MODEL, "high", 1024
        )
        assert problem is not None and "unknown provider" in problem

    def test_an_unimplemented_provider_says_what_is_missing(self) -> None:
        """
        The same shape as the programme's unbuilt gate stages: *not met,
        capability absent*, naming the capability. "No adapter" is a different
        answer from "no such provider", and an operator who cannot tell them
        apart will go looking for the wrong thing.
        """
        unavailable = next(p for p in models.PROVIDERS if not p.available)
        problem = models.settings_problem(
            unavailable.key, models.DEFAULT_MODEL, "high", 1024
        )
        assert problem is not None
        assert "not available" in problem
        assert unavailable.note.split(".")[0] in problem

    def test_an_unknown_model_is_named(self) -> None:
        problem = models.settings_problem(
            models.ANTHROPIC, "claude-imaginary-9", "high", 1024
        )
        assert problem is not None and "unknown model" in problem

    def test_a_retired_looking_id_is_not_quietly_accepted(self) -> None:
        # Date-suffixed aliases are a real habit and a real 404 at the vendor.
        problem = models.settings_problem(
            models.ANTHROPIC, "claude-sonnet-5-20260101", "high", 1024
        )
        assert problem is not None

    @pytest.mark.parametrize("value", [None, "2500", 2.5, True, False])
    def test_a_non_integer_ceiling_is_refused(self, value: object) -> None:
        """
        ``True`` is an int in Python and is not a token count. The autonomy
        ceiling learned this the hard way; the rule is repeated here rather
        than assumed.
        """
        problem = models.settings_problem(
            models.ANTHROPIC, models.DEFAULT_MODEL, "high", value
        )
        assert problem is not None and "integer" in problem

    def test_a_ceiling_below_the_floor_is_refused(self) -> None:
        problem = models.settings_problem(
            models.ANTHROPIC, models.DEFAULT_MODEL, "high", models.MIN_MAX_TOKENS - 1
        )
        assert problem is not None and "at least" in problem

    def test_a_ceiling_above_the_model_is_refused(self) -> None:
        choice = models.MODELS_BY_ID[models.DEFAULT_MODEL]
        problem = models.settings_problem(
            models.ANTHROPIC, choice.id, "high", choice.max_output + 1
        )
        assert problem is not None and "exceeds" in problem

    def test_build_settings_raises_with_the_same_sentence(self) -> None:
        """
        One rule, two entry points. The API returns the sentence as a 422 and
        the runner logs it before declining to call a model, and if those two
        could disagree a value refused at the form could still reach a request.
        """
        problem = models.settings_problem(models.ANTHROPIC, "nope", "high", 1024)
        with pytest.raises(ValueError) as caught:
            models.build_settings(models.ANTHROPIC, "nope", "high", 1024)
        assert str(caught.value) == problem


class TestTheCadenceIsASpendControl:
    @pytest.mark.parametrize("value", [None, "3600", 3600.0, True])
    def test_a_non_integer_interval_is_refused(self, value: object) -> None:
        assert models.tick_seconds_problem(value) is not None

    def test_an_interval_below_the_floor_is_refused(self) -> None:
        """
        The floor is not politeness. Every pass can cost a model call, and a
        one-second cadence spends continuously while producing nothing new —
        what a pass can achieve is bounded by what the worker finished since
        the last one, and a backtest takes minutes.
        """
        problem = models.tick_seconds_problem(models.MIN_TICK_SECONDS - 1)
        assert problem is not None and "at least" in problem

    def test_an_absurd_interval_is_refused(self) -> None:
        assert models.tick_seconds_problem(models.MAX_TICK_SECONDS + 1) is not None

    def test_the_floor_and_ceiling_are_the_right_way_round(self) -> None:
        assert models.MIN_TICK_SECONDS < models.MAX_TICK_SECONDS


class TestTheCatalogueSurvivesTheWire:
    def test_it_is_json_serialisable(self) -> None:
        import json

        json.dumps(models.catalogue())

    def test_it_carries_everything_the_selector_needs(self) -> None:
        payload = models.catalogue()
        assert {"providers", "models", "efforts", "defaults", "limits"} <= set(payload)
        assert payload["models"] and payload["providers"]
        for entry in payload["models"]:
            assert {"id", "efforts", "max_output", "provider"} <= set(entry)
