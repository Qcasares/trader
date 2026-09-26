"""
test_jev_catalogue.py
---------------------
What the programme may send to Jev, and how much of it.

``src/programme/jev_catalogue.py`` is pure, and the API will import it to show
the pinned model and to validate the configuration form, so every rule in it is
a unit test. The properties worth asserting are the ones whose failure is
silent:

* an alias is refused by name, in every spelling that would reach the vendor as
  one, because an answer given under an alias belongs to no model anybody can
  name afterwards;
* the pinned-id pattern means what it says. ``$`` matches before a trailing
  newline and ``\\d`` matches any Unicode digit, and neither is a model id;
* our limits sit beneath the vendor's, and the estimate they are applied to
  counts bytes, not characters;
* a state limit that cannot be read refuses every request;
* the form and the runner share one rule, and the values migration 0012 seeds
  pass it.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from src.programme import jev_catalogue as catalogue

ROOT = Path(__file__).resolve().parents[2]


def _text(tokens: int) -> str:
    """ASCII text the estimate counts as exactly ``tokens`` tokens."""
    return "x" * (catalogue.BYTES_PER_TOKEN_ESTIMATE * tokens)


class TestTheModelIsPinned:
    def test_the_default_is_a_known_model(self) -> None:
        assert catalogue.DEFAULT_MODEL == "jev-1.13.0"
        assert catalogue.DEFAULT_MODEL in catalogue.KNOWN_MODELS
        assert catalogue.model_problem(catalogue.DEFAULT_MODEL) is None

    def test_every_known_model_has_the_pinned_shape(self) -> None:
        for model in catalogue.KNOWN_MODELS:
            assert catalogue.PINNED_MODEL.match(model), model
            assert catalogue.model_problem(model) is None, model

    @pytest.mark.parametrize(
        "alias",
        [
            *sorted(catalogue.REFUSED_ALIASES),
            # The same aliases as a form or an environment might deliver them.
            "JEV-LATEST",
            " jev-latest",
            "jev-preview\n",
            "Jev-1.13",
        ],
    )
    def test_an_alias_is_refused_by_name(self, alias: str) -> None:
        """
        The refusal has to say "alias". An operator shown "not a pinned id"
        for ``jev-latest`` — the id every vendor example uses — reads it as a
        bug here rather than as the rule it is.
        """
        problem = catalogue.model_problem(alias)
        assert problem is not None and "alias" in problem, (alias, problem)

    @pytest.mark.parametrize("model", ["jev-1.13.1", "jev-1.12.0", "jev-2.0.0"])
    def test_a_release_nobody_evaluated_is_refused(self, model: str) -> None:
        """Pinned in shape, but a threshold measured on one model says
        nothing about another, so a release is added in review, not in a form."""
        problem = catalogue.model_problem(model)
        assert problem is not None and "not in the catalogue" in problem

    @pytest.mark.parametrize(
        "model",
        [
            "jev-1.13.0 ",
            "jev-1.13.0\n",
            "Jev-1.13.0",
            "jev-v1.13.0",
            "jev-1.13.0-preview",
            "jev-1.13",
            # The gateways' spellings (docs/08, fact 8): the direct API is the
            # only route this repository uses, and none of these is its id.
            "typesafe/jev-1.13",
            "typesafe-jev-1.13.0",
            "typesafe-ai/jev",
            "jev-1.13-20260917",
            "",
        ],
    )
    def test_a_near_miss_is_refused(self, model: str) -> None:
        assert catalogue.model_problem(model) is not None

    @pytest.mark.parametrize("model", [None, 1, True, b"jev-1.13.0", ["jev-1.13.0"]])
    def test_anything_but_a_string_is_refused(self, model: object) -> None:
        problem = catalogue.model_problem(model)
        assert problem is not None and "string" in problem

    @pytest.mark.parametrize(
        "model",
        [
            "jev-1.13.0\n",
            # Arabic-Indic and full-width digits are ``\d`` to Python's re.
            "jev-١.١٣.٠",
            "jev-１.１３.０",
        ],
    )
    def test_the_pattern_refuses_what_the_obvious_pattern_accepts(
        self, model: str
    ) -> None:
        """
        ``^jev-\\d+\\.\\d+\\.\\d+$`` is the obvious spelling, and it accepts
        all three of these. ``model_problem`` also requires catalogue
        membership, so the pattern is a second line; but a caller that uses
        the pattern on its own is owed one that means what it says.
        """
        obvious = re.compile(r"^jev-\d+\.\d+\.\d+$")
        assert obvious.match(model), "the premise of this test has changed"
        assert catalogue.PINNED_MODEL.match(model) is None

    def test_the_pattern_accepts_every_pinned_shape(self) -> None:
        for model in ("jev-1.13.0", "jev-10.0.12", "jev-0.0.0"):
            assert catalogue.PINNED_MODEL.match(model), model

    def test_no_alias_is_a_known_model(self) -> None:
        assert not catalogue.REFUSED_ALIASES & set(catalogue.KNOWN_MODELS)


class TestTheBaseUrl:
    def test_it_is_the_vendors_host_over_https_and_nothing_more(self) -> None:
        """
        The SDK appends the endpoint path itself, and honours a
        ``TYPESAFE_BASE_URL`` from the environment with no host check unless
        a base URL is passed. What is passed is this, and it has to be exactly
        the vendor's origin: a path, a port or a user part here would all be
        sent somewhere, with the key.
        """
        parts = urlsplit(catalogue.JEV_BASE_URL)
        assert parts.scheme == "https"
        assert parts.hostname == "api.typesafe.ai"
        assert parts.port is None
        assert parts.username is None and parts.password is None
        assert (parts.path, parts.query, parts.fragment) == ("", "", "")


class TestTheLimitsSitBeneathTheVendors:
    def test_the_vendor_figures_are_the_documented_ones(self) -> None:
        # Pinned so an edit to a vendor figure is a deliberate, reviewed act:
        # the margins below are only margins if these are true.
        assert catalogue.VENDOR_MAX_TOTAL_TOKENS == 64_000
        assert catalogue.VENDOR_MAX_STATE_PLUS_LONGEST_QUESTION == 32_000
        assert catalogue.VENDOR_REQUESTS_PER_MINUTE == 1_200
        assert catalogue.VENDOR_TOKENS_PER_SECOND == 250_000

    def test_ours_are_strictly_beneath_theirs(self) -> None:
        assert catalogue.MAX_TOTAL_TOKENS < catalogue.VENDOR_MAX_TOTAL_TOKENS
        assert (
            catalogue.MAX_STATE_PLUS_LONGEST_QUESTION
            < catalogue.VENDOR_MAX_STATE_PLUS_LONGEST_QUESTION
        )
        assert (
            catalogue.CLIENT_REQUESTS_PER_MINUTE < catalogue.VENDOR_REQUESTS_PER_MINUTE
        )
        assert catalogue.CLIENT_TOKENS_PER_SECOND < catalogue.VENDOR_TOKENS_PER_SECOND

    def test_the_sub_limit_fits_inside_the_total(self) -> None:
        assert catalogue.MAX_STATE_PLUS_LONGEST_QUESTION <= catalogue.MAX_TOTAL_TOKENS


class TestTheTokenEstimate:
    @pytest.mark.parametrize(
        ("text", "tokens"),
        [
            ("", 0),
            ("a", 1),
            ("abc", 1),
            ("abcd", 2),
            ("abcdef", 2),
            # Two bytes each in UTF-8.
            ("é", 1),
            ("éé", 2),
            # Three bytes each.
            ("日本語", 3),
            # Four bytes.
            ("\U0001f600", 2),
        ],
    )
    def test_it_is_a_ceiling_of_utf8_bytes_over_three(
        self, text: str, tokens: int
    ) -> None:
        assert catalogue.estimate_tokens(text) == tokens

    def test_it_charges_wide_text_for_its_width(self) -> None:
        """
        Counting characters would undercount every non-Latin script by up to
        three times, which is exactly the text a web lane will one day send.
        """
        wide = "日" * 300
        assert len(wide) == 300
        assert catalogue.estimate_tokens(wide) == 300
        assert catalogue.estimate_tokens("a" * 300) == 100

    def test_it_takes_text_not_bytes(self) -> None:
        with pytest.raises(TypeError):
            catalogue.estimate_tokens(b"abc")  # type: ignore[arg-type]


class TestTheRequestSize:
    def test_a_small_request_fits(self) -> None:
        assert (
            catalogue.request_size_problem(
                '{"text": "hello"}', {"q": '{"type": "noul"}'}, 8_000
            )
            is None
        )

    def test_the_state_limit_is_the_operators_and_is_inclusive(self) -> None:
        questions = {"q": _text(10)}
        assert catalogue.request_size_problem(_text(500), questions, 500) is None
        problem = catalogue.request_size_problem(_text(500) + "x", questions, 500)
        assert problem is not None and "jev_max_state_tokens" in problem

    def test_the_state_plus_the_longest_question(self) -> None:
        limit = catalogue.MAX_STATE_PLUS_LONGEST_QUESTION
        state = _text(10_000)
        fits = {"short": _text(5), "long": _text(limit - 10_000)}
        assert catalogue.request_size_problem(state, fits, 20_000) is None

        over = {"short": _text(5), "long": _text(limit - 10_000) + "x"}
        problem = catalogue.request_size_problem(state, over, 20_000)
        assert problem is not None
        assert "'long'" in problem and str(limit) in problem

    def test_the_state_plus_every_question(self) -> None:
        """Each question fits beside the state on its own; together they do not."""
        limit = catalogue.MAX_TOTAL_TOKENS
        fits = {"a": _text(20_000), "b": _text(20_000), "c": _text(limit - 40_000)}
        assert catalogue.request_size_problem("", fits, 1) is None

        over = {**fits, "c": _text(limit - 40_000) + "x"}
        problem = catalogue.request_size_problem("", over, 1)
        assert problem is not None and "in total" in problem and str(limit) in problem

    def test_question_names_are_not_counted(self) -> None:
        """The vendor does not send the names to the model."""
        name = "n" * 300_000
        assert catalogue.request_size_problem("{}", {name: "{}"}, 10) is None

    def test_wide_state_is_charged_by_the_byte(self) -> None:
        state = "é" * 3_000  # 6,000 bytes: 2,000 tokens
        assert catalogue.request_size_problem(state, {"q": "{}"}, 2_000) is None
        assert catalogue.request_size_problem(state, {"q": "{}"}, 1_999) is not None

    @pytest.mark.parametrize("limit", [0, -1, True, False, 1.5, "8000", None])
    def test_a_limit_that_cannot_be_read_refuses_every_request(
        self, limit: object
    ) -> None:
        """
        Zero is what ``flags.jev_max_state_tokens`` reads as when the stored
        setting is missing or unreadable. A limit nobody can read does not
        permit a request of any size — not even an empty one.
        """
        problem = catalogue.request_size_problem("", {"q": "{}"}, limit)  # type: ignore[arg-type]
        assert problem is not None and "jev_max_state_tokens" in problem

    def test_a_request_needs_a_question(self) -> None:
        problem = catalogue.request_size_problem("{}", {}, 8_000)
        assert problem is not None and "question" in problem


class TestTheSettings:
    def test_the_seeded_settings_are_usable(self) -> None:
        """
        Migration 0012 seeds these. If they did not validate, a fresh database
        would ship a lane that refuses every call the day it is switched on.
        """
        assert catalogue.DEFAULT_DAILY_REQUEST_BUDGET == 500
        assert catalogue.DEFAULT_MAX_STATE_TOKENS == 8_000
        assert (
            catalogue.settings_problem(
                catalogue.DEFAULT_MODEL,
                catalogue.DEFAULT_DAILY_REQUEST_BUDGET,
                catalogue.DEFAULT_MAX_STATE_TOKENS,
            )
            is None
        )

    def test_the_model_rule_is_the_same_rule(self) -> None:
        problem = catalogue.settings_problem("jev-latest", 500, 8_000)
        assert problem == catalogue.model_problem("jev-latest")

    def test_zero_is_a_setting_meaning_no_calls(self) -> None:
        assert catalogue.settings_problem(catalogue.DEFAULT_MODEL, 0, 0) is None

    def test_the_ceilings_are_inclusive(self) -> None:
        assert (
            catalogue.settings_problem(
                catalogue.DEFAULT_MODEL,
                catalogue.MAX_DAILY_REQUEST_BUDGET,
                catalogue.MAX_STATE_PLUS_LONGEST_QUESTION,
            )
            is None
        )

    @pytest.mark.parametrize(
        "budget",
        [True, False, -1, catalogue.MAX_DAILY_REQUEST_BUDGET + 1, 500.0, "500", None],
    )
    def test_a_budget_that_is_not_a_count_is_refused(self, budget: object) -> None:
        # `True` is an int in Python and is not a count of requests.
        problem = catalogue.settings_problem(catalogue.DEFAULT_MODEL, budget, 8_000)
        assert problem is not None and "jev_daily_request_budget" in problem

    @pytest.mark.parametrize(
        "limit",
        [
            True,
            -1,
            catalogue.MAX_STATE_PLUS_LONGEST_QUESTION + 1,
            8_000.0,
            "8000",
            None,
        ],
    )
    def test_a_state_limit_that_is_not_a_count_is_refused(self, limit: object) -> None:
        problem = catalogue.settings_problem(catalogue.DEFAULT_MODEL, 500, limit)
        assert problem is not None and "jev_max_state_tokens" in problem


class TestTheVocabulary:
    def test_the_lanes_are_the_migrations(self) -> None:
        """In the order migration 0012's CHECK constraint lists them."""
        assert catalogue.LANES == (
            "research",
            "guardrail",
            "findings",
            "ops",
            "signals",
            "decision",
            "probe",
        )

    def test_the_provenances(self) -> None:
        assert catalogue.PROVENANCES == ("web", "internal", "operator")

    def test_the_areas(self) -> None:
        assert catalogue.AREAS == (
            "research",
            "ops",
            "findings",
            "guardrails",
            "signals",
            "decisions",
        )

    def test_every_lane_has_an_area_entry_and_nothing_else_does(self) -> None:
        assert set(catalogue.LANE_AREA) == set(catalogue.LANES)

    def test_each_lane_answers_to_its_own_switch(self) -> None:
        """
        Pinned pair by pair. The two tests below would both pass if two lanes
        swapped switches, and then switching on research would run the
        guardrails, which an operator switched on nothing to get.
        """
        assert catalogue.LANE_AREA == {
            "research": "research",
            "guardrail": "guardrails",
            "findings": "findings",
            "ops": "ops",
            "signals": "signals",
            "decision": "decisions",
            "probe": None,
        }

    def test_every_area_gates_exactly_one_lane(self) -> None:
        gated = [a for a in catalogue.LANE_AREA.values() if a is not None]
        assert sorted(gated) == sorted(catalogue.AREAS)

    def test_the_probe_answers_to_the_master_switch_alone(self) -> None:
        ungated = [lane for lane, a in catalogue.LANE_AREA.items() if a is None]
        assert ungated == ["probe"]


def test_the_catalogue_loads_no_client_and_no_io() -> None:
    """
    The API will import this module. Importing it, in a fresh interpreter,
    must load nothing that can reach a network, a database or a model.
    """
    forbidden = (
        "aiohttp",
        "anthropic",
        "asyncpg",
        "httpx",
        "httpx2",
        "requests",
        "typesafe_sdk",
        "urllib3",
        "src.db",
        "src.programme.client",
        "src.programme.jev_client",
        "src.programme.jev_lane",
    )
    code = (
        "import sys, src.programme.jev_catalogue\n"
        f"forbidden = {forbidden!r}\n"
        "print(sorted(m for m in sys.modules "
        "if any(m == f or m.startswith(f + '.') for f in forbidden)))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "[]", result.stdout
