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
from datetime import date
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

    def test_every_known_model_has_a_first_observation(self) -> None:
        """
        The harness (phase C9) computes ``possibly_in_training`` against the
        day a model was first observed, since TypeSafe discloses no training
        cutoff. A model added to the catalogue without saying when it was
        first seen would have every item judged against nothing, so it must
        say; and nothing outside the catalogue has a day, which would be a
        model nobody may call being given a cutoff.
        """
        assert set(catalogue.MODEL_FIRST_OBSERVED) == set(catalogue.KNOWN_MODELS)
        for model, day in catalogue.MODEL_FIRST_OBSERVED.items():
            assert type(day) is date, (model, day)

    def test_jev_1_13_0_was_first_observed_by_the_key_check(self) -> None:
        """docs/08: the dispatch-only key check found it answering on 26 September
        2026, the earliest day this repository has evidence of it."""
        assert catalogue.MODEL_FIRST_OBSERVED["jev-1.13.0"] == date(2026, 9, 26)

    def test_the_first_observations_cannot_be_changed_at_runtime(self) -> None:
        with pytest.raises(TypeError):
            catalogue.MODEL_FIRST_OBSERVED["jev-1.13.0"] = date(2030, 1, 1)  # type: ignore[index]


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
            # Anything else is a token a byte: two bytes each in UTF-8,
            ("é", 2),
            ("éé", 4),
            ("aé", 3),
            # three bytes each,
            ("日本語", 9),
            # and four.
            ("\U0001f600", 4),
        ],
    )
    def test_ascii_is_three_bytes_a_token_and_the_rest_a_token_a_byte(
        self, text: str, tokens: int
    ) -> None:
        assert catalogue.estimate_tokens(text) == tokens

    def test_it_charges_wide_text_the_byte_level_worst_case(self) -> None:
        """
        A byte-level tokenizer can spend a token on every byte of a non-Latin
        script. Counting characters would undercount such text ninefold, and
        counting three bytes to a token threefold — far past the margin under
        the vendor's limits — and it is exactly the text a web lane will send.
        """
        wide = "日" * 300
        assert len(wide) == 300
        assert catalogue.estimate_tokens(wide) == 900
        assert catalogue.estimate_tokens("a" * 300) == 100

    def test_it_never_charges_less_than_either_bound(self) -> None:
        """Over mixed scripts: never below a token a non-ASCII byte, nor below
        a third of all the bytes, which is where the estimate began."""
        import random

        alphabet = (
            "abcXYZ0123456789 ,.{}\"\\"
            "éüßñ" "αβγ" "дж" "שׁ" "ع" "日本" "한" "ไ" "\U0001f600"
        )
        generator = random.Random(20260926)
        for _ in range(2_000):
            text = "".join(
                generator.choice(alphabet) for _ in range(generator.randint(0, 60))
            )
            size = len(text.encode("utf-8"))
            wide = size - len(text.encode("ascii", "ignore"))
            estimate = catalogue.estimate_tokens(text)
            assert estimate >= wide, text
            assert estimate >= -(-size // catalogue.BYTES_PER_TOKEN_ESTIMATE), text

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
        state = "é" * 3_000  # 6,000 bytes, none of them ASCII: 6,000 tokens
        assert catalogue.request_size_problem(state, {"q": "{}"}, 6_000) is None
        assert catalogue.request_size_problem(state, {"q": "{}"}, 5_999) is not None

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

    @pytest.mark.parametrize("budget", range(1, 10))
    def test_a_budget_that_leaves_a_lane_no_call_is_refused(self, budget: int) -> None:
        """
        Each lane spends at most its share, rounded down, so from one to nine
        the probe lane's is none — and, below five, the decision lane's —
        while the setting reads like a budget that permits calls. Refused,
        with the reason, so the runner reads it as the 0 it amounts to.
        """
        problem = catalogue.settings_problem(catalogue.DEFAULT_MODEL, budget, 8_000)
        assert problem is not None and "jev_daily_request_budget" in problem
        assert "at least 10" in problem and "probe lane" in problem, problem

    def test_the_smallest_budget_but_zero_gives_every_lane_with_a_share_a_call(
        self,
    ) -> None:
        """
        Derived from the shares rather than written down, and held to them
        here both ways: at the minimum every lane with a share has a call, and
        one below it some lane has none.
        """
        least = catalogue.MIN_DAILY_REQUEST_BUDGET
        assert least == 10
        assert catalogue.settings_problem(catalogue.DEFAULT_MODEL, least, 0) is None
        shares = catalogue.LANE_BUDGET_PERCENT
        shared = [lane for lane, share in shares.items() if share]
        assert all(catalogue.lane_budget(least, lane) >= 1 for lane in shared)
        assert any(catalogue.lane_budget(least - 1, lane) == 0 for lane in shared)

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
        """
        Migration 0013 adds ``model``: text the programme's own model wrote,
        kept apart from ``internal``, which the phase F loader is to trust.
        Migration 0015 adds ``system`` (phase D): this system's own records,
        computed in code, which can quote an outsider — on ``jev_requests``
        alone, so ``jev_signals`` still refuses it.
        """
        assert catalogue.PROVENANCES == (
            "web",
            "internal",
            "operator",
            "model",
            "system",
        )

    def test_subject_types(self) -> None:
        assert catalogue.SUBJECT_TYPES == (
            "probe",
            "session",
            "web_excerpt",
            "hypothesis_title",
        )

    def test_the_lane_slices_cover_every_lane_and_sum_to_at_most_100(self) -> None:
        """
        One share per lane, no lane left out and none invented, and together at
        most the whole budget, so no lane's spending can reach into another's.
        """
        slices = catalogue.LANE_BUDGET_PERCENT
        assert set(slices) == set(catalogue.LANES)
        assert all(
            type(share) is int and 0 <= share <= 100 for share in slices.values()
        )
        assert sum(slices.values()) <= 100

    def test_the_slices_are_the_designed_ones(self) -> None:
        """
        Pinned lane by lane: the decision lane's twenty is the forward clock's
        reserve, and a lane with no set yet has none.
        """
        assert dict(catalogue.LANE_BUDGET_PERCENT) == {
            "research": 35,
            "guardrail": 35,
            "findings": 0,
            "ops": 0,
            "signals": 0,
            "decision": 20,
            "probe": 10,
        }

    def test_the_slices_cannot_be_changed_at_runtime(self) -> None:
        with pytest.raises(TypeError):
            catalogue.LANE_BUDGET_PERCENT["research"] = 100  # type: ignore[index]

    @pytest.mark.parametrize(
        ("budget", "lane", "share"),
        [
            (500, "decision", 100),
            (500, "guardrail", 175),
            (500, "research", 175),
            (500, "probe", 50),
            (500, "ops", 0),
            (9, "probe", 0),
            (10, "probe", 1),
            (19, "probe", 1),
            (1, "decision", 0),
            (0, "research", 0),
            (catalogue.MAX_DAILY_REQUEST_BUDGET, "probe", 1_000),
        ],
    )
    def test_a_lanes_share_is_rounded_down(
        self, budget: int, lane: str, share: int
    ) -> None:
        assert catalogue.lane_budget(budget, lane) == share

    def test_the_shares_never_exceed_the_budget(self) -> None:
        for budget in range(0, 1_001):
            total = sum(catalogue.lane_budget(budget, lane) for lane in catalogue.LANES)
            assert total <= budget, budget

    def test_a_lane_that_does_not_exist_has_no_share_to_give(self) -> None:
        with pytest.raises(ValueError, match="lane"):
            catalogue.lane_budget(500, "decisions")

    @pytest.mark.parametrize("budget", [True, 500.0, "500", None])
    def test_a_budget_is_a_count(self, budget: object) -> None:
        with pytest.raises(TypeError):
            catalogue.lane_budget(budget, "probe")  # type: ignore[arg-type]

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
