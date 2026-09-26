"""
test_jev_questions.py
---------------------
The question sets, their golden hashes, and the rules a set is registered under.

What must not be able to happen quietly:

* a set's words change and its answers go on pooling with answers to the old
  words. The golden test catches it, and the tests beside it prove the golden
  test bites for every character of every part of a set that is hashed, for
  every reordering of its options, and for every definition ``jev_features``
  computes with — including an edit smaller than a whole percent;
* a Choice goes out with nowhere to put "none of these";
* a decision-lane state grows a field that can carry a date, a ticker, a figure
  or free text, which would let a model that remembers markets recall the
  outcome instead of judging the state. Checked twice, independently of the
  module's own rule: by walking the declared fields, and by dumping every state
  there is and comparing what would be sent with what was given;
* the regime question asks with a negation, names a field the state does not
  have, or describes its escape as anything but the answer for conflicting
  descriptors.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import itertools
import json
import re
import subprocess
import sys
import types
from collections.abc import Callable, Iterator
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, get_args, get_origin

import pytest
from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    computed_field,
    field_serializer,
    model_serializer,
)

from src.programme import jev_catalogue
from src.programme import jev_questions as jq
from src.programme.jev_questions import QuestionSet

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "src" / "programme" / "jev_questions.py"
FEATURES = ROOT / "src" / "programme" / "jev_features.py"

REGIME = jq.get("decision.regime")
PROBE = jq.get("probe.connectivity")
REGIME_ORDER = ["risk_on", "neutral", "risk_off", "insufficient_evidence"]


def _golden(question_set: QuestionSet) -> str:
    return jq.GOLDEN_PACK_HASHES[(question_set.name, question_set.version)]


def _content(question_set: QuestionSet) -> tuple[Any, ...]:
    """What a set says, order included, read without its pack hash."""
    return (
        question_set.name,
        question_set.version,
        question_set.lane,
        question_set.provenance,
        json.dumps([list(pair) for pair in question_set.questions]),
    )


def _regime_question() -> dict:
    return REGIME.as_request_questions()["regime"]


def _flip(text: str, index: int) -> str:
    """``text`` with the one character at ``index`` changed."""
    index %= len(text)
    replacement = "x" if text[index] != "x" else "y"
    return text[:index] + replacement + text[index + 1 :]


class _TextState(BaseModel):
    """A permissive state, for testing question rules apart from state rules."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str


def _set(questions: tuple[tuple[str, Any], ...], **overrides: Any) -> QuestionSet:
    fields: dict[str, Any] = {
        "name": "research.example",
        "version": 1,
        "lane": "research",
        "provenance": "web",
        "questions": questions,
        "state_model": _TextState,
        "purpose": "A set that exists only in this test.",
    }
    fields.update(overrides)
    return QuestionSet(**fields)


def _choice(criteria: dict[str, str]) -> tuple[tuple[str, Any], ...]:
    return (
        ("pick", {"type": "choice", "instructions": "Pick.", "criteria": criteria}),
    )


GOOD_CHOICE = {"red": "It is red.", "blue": "It is blue.", "unclear": "It is unclear."}


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


class TestTheRegistry:
    def test_phase_b_registers_the_probe_and_the_regime(self) -> None:
        assert set(jq.REGISTRY) == {"probe.connectivity", "decision.regime"}
        assert jq.PROBE_CONNECTIVITY is PROBE
        assert jq.DECISION_REGIME is REGIME

    def test_an_unknown_name_is_a_key_error_naming_the_known_ones(self) -> None:
        with pytest.raises(KeyError, match="decision.regime"):
            jq.get("decision.regime_v1")

    @pytest.mark.parametrize("name", sorted(jq.REGISTRY))
    def test_every_registered_set_passes_its_own_rules(self, name: str) -> None:
        assert jq.question_set_problem(jq.get(name)) is None

    def test_registration_refuses_a_set_that_breaks_a_rule(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(jq, "REGISTRY", dict(jq.REGISTRY))
        broken = _set(_choice({"red": "It is red.", "blue": "It is blue."}))
        with pytest.raises(ValueError, match="escape"):
            jq._register(broken)
        assert "research.example" not in jq.REGISTRY

    def test_a_name_is_registered_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(jq, "REGISTRY", dict(jq.REGISTRY))
        with pytest.raises(ValueError, match="twice"):
            jq._register(dataclasses.replace(REGIME, version=2))

    def test_the_probe(self) -> None:
        assert (PROBE.lane, PROBE.provenance, PROBE.version) == ("probe", "internal", 1)
        assert PROBE.state_model is jq.ProbeState
        questions = PROBE.as_request_questions()
        assert [q["type"] for q in questions.values()] == ["noul"]
        assert PROBE.escape_options == {}

    def test_the_regime(self) -> None:
        assert (REGIME.lane, REGIME.provenance, REGIME.version) == (
            "decision",
            "internal",
            1,
        )
        assert REGIME.state_model is jq.RegimeState
        question = _regime_question()
        assert question["type"] == "choice"
        assert list(question["criteria"]) == REGIME_ORDER
        assert REGIME.escape_options == {"regime": "insufficient_evidence"}

    def test_every_registered_set_takes_the_lanes_and_provenances_the_schema_does(
        self,
    ) -> None:
        for question_set in jq.REGISTRY.values():
            assert question_set.lane in jev_catalogue.LANES
            assert question_set.provenance in jev_catalogue.PROVENANCES


# ---------------------------------------------------------------------------
# The golden hashes
# ---------------------------------------------------------------------------


def _with_question(
    qs: QuestionSet, index: int, question: dict, key: str | None = None
) -> QuestionSet:
    """``qs`` with its ``index``th question, and optionally its key, replaced."""
    pairs = list(qs.questions)
    old_key, _ = pairs[index]
    pairs[index] = (old_key if key is None else key, question)
    return dataclasses.replace(qs, questions=tuple(pairs))


def _renamed(criteria: dict, option: str, new: str) -> dict:
    """``criteria`` with ``option`` renamed in place, the order kept."""
    return {(new if o == option else o): d for o, d in criteria.items()}


def _every_one_character_edit(
    qs: QuestionSet,
) -> Iterator[tuple[str, QuestionSet]]:
    """
    Every set that differs from ``qs`` by one character of hashed text.

    The set's name, lane and provenance; each question's key, type and
    instructions; each option's key and description; each score level. Every
    character position of each, one at a time.
    """
    for field in ("name", "lane", "provenance"):
        text = getattr(qs, field)
        for i in range(len(text)):
            yield f"{field}[{i}]", dataclasses.replace(qs, **{field: _flip(text, i)})
    for index, (key, question) in enumerate(qs.questions):
        for i in range(len(key)):
            yield (
                f"{key}.key[{i}]",
                _with_question(qs, index, question, key=_flip(key, i)),
            )
        for field in ("type", "instructions"):
            text = question[field]
            for i in range(len(text)):
                edited = {**question, field: _flip(text, i)}
                yield f"{key}.{field}[{i}]", _with_question(qs, index, edited)
        criteria = question.get("criteria")
        if isinstance(criteria, dict):
            for option, description in criteria.items():
                for i in range(len(option)):
                    renamed = _renamed(criteria, option, _flip(option, i))
                    yield (
                        f"{key}.{option}.key[{i}]",
                        _with_question(qs, index, {**question, "criteria": renamed}),
                    )
                for i in range(len(description)):
                    edited = {**criteria, option: _flip(description, i)}
                    yield (
                        f"{key}.{option}[{i}]",
                        _with_question(qs, index, {**question, "criteria": edited}),
                    )
        elif isinstance(criteria, list):
            for level, text in enumerate(criteria):
                for i in range(len(text)):
                    levels = [*criteria]
                    levels[level] = _flip(text, i)
                    yield (
                        f"{key}.level{level}[{i}]",
                        _with_question(qs, index, {**question, "criteria": levels}),
                    )


def _hashed_characters(qs: QuestionSet) -> int:
    """How many characters of hashed text ``qs`` has, counted independently."""
    total = len(qs.name) + len(qs.lane) + len(qs.provenance)
    for key, question in qs.questions:
        total += len(key) + len(question["type"]) + len(question["instructions"])
        criteria = question.get("criteria")
        if isinstance(criteria, dict):
            total += sum(len(o) + len(d) for o, d in criteria.items())
        elif isinstance(criteria, list):
            total += sum(len(level) for level in criteria)
    return total


def _swap_first_two_options(qs: QuestionSet) -> QuestionSet:
    key, question = qs.questions[0]
    criteria = list(question["criteria"].items())
    criteria[0], criteria[1] = criteria[1], criteria[0]
    return dataclasses.replace(
        qs, questions=((key, {**question, "criteria": dict(criteria)}),)
    )


def _reorder_question_fields(qs: QuestionSet) -> QuestionSet:
    key, question = qs.questions[0]
    return dataclasses.replace(qs, questions=((key, dict(reversed(question.items()))),))


#: Each constant ``jev_features`` computes with, as the module's source spells
#: it, and an edit to it. The fractions move by less than a whole percent, which
#: a rendering rounded to whole percents would not show in the words.
DEFINITIONS: dict[str, tuple[str, str]] = {
    "TREND_AVERAGE_SESSIONS": ("200", "201"),
    "TREND_NEAR_BAND": ("0.01", "0.012"),
    "VOLATILITY_SESSIONS": ("20", "21"),
    "VOLATILITY_HISTORY_SESSIONS": ("1260", "1261"),
    "DRAWDOWN_HIGH_SESSIONS": ("252", "253"),
    "DRAWDOWN_SHALLOW": ("0.02", "0.025"),
    "DRAWDOWN_DEEP": ("0.10", "0.105"),
    "DRAWDOWN_SEVERE": ("0.20", "0.204"),
    "MOMENTUM_SESSIONS": ("63", "64"),
    "MOMENTUM_FLAT_BAND": ("0.01", "0.0101"),
}


def _constants_features_imports() -> set[str]:
    """The upper-case names ``jev_features.py`` imports from ``jev_questions``."""
    tree = ast.parse(FEATURES.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "src.programme.jev_questions"
        ):
            names |= {a.name for a in node.names if a.name.isupper()}
    return names


def _execute_variant(monkeypatch: pytest.MonkeyPatch, source: str) -> types.ModuleType:
    """Execute ``source`` as a fresh module, apart from the registered one."""
    variant = types.ModuleType("jev_questions_variant")
    monkeypatch.setitem(sys.modules, variant.__name__, variant)
    exec(compile(source, str(MODULE), "exec"), variant.__dict__)
    return variant


class TestTheGoldenHashes:
    def test_every_registered_set_has_a_golden_and_every_golden_a_set(self) -> None:
        """
        Both directions. A set without a golden is one whose words nobody
        pinned; a golden without a set is a version bumped without its new
        hash being recorded, or an old one left behind.
        """
        registered = {(qs.name, qs.version) for qs in jq.REGISTRY.values()}
        assert registered == set(jq.GOLDEN_PACK_HASHES)

    @pytest.mark.parametrize("name", sorted(jq.REGISTRY))
    def test_every_registered_set_hashes_to_its_golden(self, name: str) -> None:
        question_set = jq.get(name)
        assert question_set.pack_hash == _golden(question_set), (
            f"{name} v{question_set.version} no longer hashes to its golden. "
            "If its words changed on purpose, bump its version and record the "
            "new hash in GOLDEN_PACK_HASHES: answers to the old words must not "
            "pool with answers to the new ones."
        )

    @pytest.mark.parametrize("name", sorted(jq.REGISTRY))
    def test_changing_any_one_character_changes_the_hash(self, name: str) -> None:
        """
        Every character of every hashed string, one at a time: instructions,
        criteria text, option keys, the question key and type, and the set's
        name, lane and provenance. Each edit must move the hash off the golden,
        and no two edits may land on the same hash — which they would if some
        part of the set were missing from what is hashed, since editing it
        would then change nothing at all.
        """
        question_set = jq.get(name)
        edits = list(_every_one_character_edit(question_set))
        assert len(edits) == _hashed_characters(question_set)
        hashes = {edited.pack_hash for _, edited in edits}
        assert _golden(question_set) not in hashes
        assert len(hashes) == len(edits)

    def test_every_order_of_the_regime_options_hashes_differently(self) -> None:
        key, question = REGIME.questions[0]
        orders = list(itertools.permutations(question["criteria"].items()))
        assert len(orders) == 24
        hashes = {
            _with_question(REGIME, 0, {**question, "criteria": dict(order)}).pack_hash
            for order in orders
        }
        assert len(hashes) == len(orders)
        assert _golden(REGIME) in hashes, "the frozen order itself hashes to golden"

    @pytest.mark.parametrize("name", sorted(jq.REGISTRY))
    def test_every_other_lane_and_provenance_hashes_differently(
        self, name: str
    ) -> None:
        question_set = jq.get(name)
        for lane in jev_catalogue.LANES:
            if lane != question_set.lane:
                moved = dataclasses.replace(question_set, lane=lane)
                assert moved.pack_hash != _golden(question_set), lane
        for provenance in jev_catalogue.PROVENANCES:
            if provenance != question_set.provenance:
                moved = dataclasses.replace(question_set, provenance=provenance)
                assert moved.pack_hash != _golden(question_set), provenance

    @pytest.mark.parametrize(
        "edit",
        [
            lambda qs: dataclasses.replace(qs, version=2),
            _reorder_question_fields,
        ],
        ids=["version", "question-field-order"],
    )
    def test_the_version_and_the_field_order_are_hashed(
        self, edit: Callable[[QuestionSet], QuestionSet]
    ) -> None:
        edited = edit(REGIME)
        assert _content(edited) != _content(REGIME), "the edit changed nothing"
        assert edited.pack_hash != _golden(REGIME)
        assert edited != REGIME

    def test_the_hash_is_the_documented_formula(self) -> None:
        """
        Recomputed here from the spec's wording, independently of the module.
        The pack hash is stored beside every answer; if the formula drifted,
        rows written before and after would stop joining.
        """
        for question_set in jq.REGISTRY.values():
            payload = {
                "name": question_set.name,
                "version": question_set.version,
                "lane": question_set.lane,
                "provenance": question_set.provenance,
                "questions": [[k, q] for k, q in question_set.questions],
            }
            text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
            expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
            assert question_set.pack_hash == expected

    def test_the_formula_writes_text_beyond_ascii_as_itself(self) -> None:
        """
        ``ensure_ascii=False`` is part of the formula, and the registered sets
        happen to be plain ASCII, where it changes nothing. A research set
        reading web text will not be, and escaped and unescaped JSON hash
        differently.
        """
        question = {"type": "noul", "instructions": "Is this café’s menu in €?"}
        built = _set((("q", question),))
        payload = {
            "name": built.name,
            "version": built.version,
            "lane": built.lane,
            "provenance": built.provenance,
            "questions": [["q", question]],
        }
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        escaped = json.dumps(payload, separators=(",", ":"))
        assert raw != escaped, "the premise: this text is not ASCII"
        assert built.pack_hash == hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def test_option_order_is_hashed_because_nothing_sorts_it(self) -> None:
        """
        Two sets with the same options in different orders. Sorted keys would
        hash them alike — which is why the module must never sort.
        """
        swapped = _swap_first_two_options(REGIME)
        assert swapped.pack_hash != REGIME.pack_hash

        def payload(qs: QuestionSet) -> dict[str, Any]:
            return {"questions": [[k, q] for k, q in qs.questions]}

        assert json.dumps(payload(swapped), sort_keys=True) == json.dumps(
            payload(REGIME), sort_keys=True
        )

    def test_the_same_words_hash_alike_however_they_were_built(self) -> None:
        rebuilt = QuestionSet(
            name=REGIME.name,
            version=REGIME.version,
            lane=REGIME.lane,
            provenance=REGIME.provenance,
            questions=tuple(REGIME.as_request_questions().items()),
            state_model=REGIME.state_model,
            purpose="Different prose for people, which is not hashed.",
        )
        assert rebuilt.pack_hash == REGIME.pack_hash == _golden(REGIME)
        assert hash(rebuilt) == hash(REGIME)

    def test_the_definitions_listed_here_are_the_ones_the_features_use(
        self,
    ) -> None:
        """
        The test below is only as good as its list. The list is held to what
        ``jev_features.py`` actually imports, so a new window or edge there is
        a new row here, not a definition outside the hash.
        """
        assert _constants_features_imports() - {"SLEEVES"} == set(DEFINITIONS)

    @pytest.mark.parametrize("constant", sorted(DEFINITIONS))
    def test_every_definition_the_features_use_is_inside_the_hash(
        self, constant: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        The claim the module's docstring makes: a window or edge
        ``jev_features`` computes with is written into the regime question,
        exactly, so changing it in the source changes the registered set's
        hash and the golden test fails until the version is bumped.

        Proved by executing the module's own source with one constant edited,
        rather than by trusting that the text mentions the number. The
        fractions move by less than a whole percent, which the words would not
        show if they were rounded.
        """
        source = MODULE.read_text(encoding="utf-8")
        value, edited = DEFINITIONS[constant]
        line = f"\n{constant} = {value}\n"
        assert source.count(line) == 1, f"{constant} is not defined once as {value}"

        variant = _execute_variant(
            monkeypatch, source.replace(line, f"\n{constant} = {edited}\n")
        )
        assert variant.DECISION_REGIME.pack_hash != _golden(REGIME), constant

        # And the untouched source reproduces the golden, so the difference
        # above is the edit's and not an artefact of executing it here.
        original = _execute_variant(monkeypatch, source)
        assert original.DECISION_REGIME.pack_hash == _golden(REGIME)


class TestPercentagesAreWrittenExactly:
    @pytest.mark.parametrize(
        ("fraction", "text"),
        [
            (0.01, "1%"),
            (0.012, "1.2%"),
            (0.02, "2%"),
            (0.025, "2.5%"),
            (0.1, "10%"),
            (0.2, "20%"),
            (0.204, "20.4%"),
            (0.07, "7%"),
            (0.29, "29%"),
            (1.0, "100%"),
        ],
    )
    def test_as_the_code_holds_them(self, fraction: float, text: str) -> None:
        """``0.07 * 100`` is 7.000000000000001 in binary floating point; the
        rendering reads the decimal the source wrote instead."""
        assert jq._percent(fraction) == text

    @pytest.mark.parametrize("value", [1, True, Decimal("0.01"), "0.01"])
    def test_a_bucket_edge_is_a_float(self, value: object) -> None:
        with pytest.raises(TypeError):
            jq._percent(value)  # type: ignore[arg-type]


class TestEqualityRespectsOrder:
    """
    Dict equality ignores order, so the equality a dataclass generates called
    two sets with the same options in different orders equal while their pack
    hashes differed — equal objects with unequal hashes, which breaks every
    dict and set they are put in, and says two different questions are one.
    """

    def test_the_same_options_in_another_order_are_another_set(self) -> None:
        swapped = _swap_first_two_options(REGIME)
        assert swapped.questions[0][1] == REGIME.questions[0][1], (
            "the premise: as dicts, the two questions compare equal"
        )
        assert swapped != REGIME

    def test_equal_sets_hash_alike(self) -> None:
        rebuilt = dataclasses.replace(REGIME)
        assert rebuilt is not REGIME
        assert rebuilt == REGIME
        assert hash(rebuilt) == hash(REGIME)
        assert {REGIME: "found"}[rebuilt] == "found"

    def test_the_prose_and_the_state_model_are_part_of_the_set(self) -> None:
        assert dataclasses.replace(REGIME, purpose="Other prose.") != REGIME
        assert dataclasses.replace(REGIME, state_model=jq.ProbeState) != REGIME

    def test_a_set_is_not_equal_to_something_else(self) -> None:
        assert REGIME != REGIME.pack_hash
        assert REGIME != object()


# ---------------------------------------------------------------------------
# What a request is built from
# ---------------------------------------------------------------------------


class TestTheRequestQuestions:
    def test_order_is_preserved(self) -> None:
        questions = REGIME.as_request_questions()
        assert list(questions) == ["regime"]
        assert list(questions["regime"]) == ["type", "instructions", "criteria"]
        assert list(questions["regime"]["criteria"]) == REGIME_ORDER

    def test_a_request_cannot_change_the_set(self) -> None:
        questions = REGIME.as_request_questions()
        questions["regime"]["instructions"] = "Something else."
        questions["regime"]["criteria"]["risk_on"] = "Something else."
        questions["regime"]["criteria"].pop("insufficient_evidence")
        assert REGIME.pack_hash == _golden(REGIME)
        assert list(_regime_question()["criteria"]) == REGIME_ORDER

    def test_a_literal_the_caller_keeps_cannot_change_the_set(self) -> None:
        criteria = dict(GOOD_CHOICE)
        question = {"type": "choice", "instructions": "Pick.", "criteria": criteria}
        built = _set((("pick", question),))
        before = built.pack_hash
        criteria["red"] = "It is crimson."
        question["instructions"] = "Choose."
        assert built.pack_hash == before
        assert built.as_request_questions()["pick"]["instructions"] == "Pick."

    def test_it_is_plain_json_as_the_sdk_takes_it(self) -> None:
        for question_set in jq.REGISTRY.values():
            questions = question_set.as_request_questions()
            assert json.loads(json.dumps(questions)) == questions

    def test_questions_are_ordered_pairs_not_a_mapping(self) -> None:
        """
        Iterating a dict yields its keys, and a two-letter key unpacks into a
        pair of single characters — a set with question "a" asking "b".
        """
        with pytest.raises(TypeError, match="ordered tuple"):
            _set({"ab": {"type": "noul", "instructions": "It is red."}})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Escape options
# ---------------------------------------------------------------------------


class TestEveryChoiceCarriesAnEscape:
    @pytest.mark.parametrize("escape", jq.ESCAPE_OPTIONS)
    def test_each_escape_is_accepted_last(self, escape: str) -> None:
        built = _set(_choice({"red": "It is red.", "blue": "It is blue.", escape: "?"}))
        assert jq.question_set_problem(built) is None
        assert built.escape_options == {"pick": escape}

    def test_a_choice_without_an_escape_is_refused(self) -> None:
        problem = jq.question_set_problem(
            _set(_choice({"red": "It is red.", "blue": "It is blue."}))
        )
        assert problem is not None and "escape" in problem

    def test_two_escapes_are_refused(self) -> None:
        criteria = {**GOOD_CHOICE, "none_of_these": "Neither."}
        problem = jq.question_set_problem(_set(_choice(criteria)))
        assert problem is not None and "escape" in problem

    def test_the_escape_goes_last(self) -> None:
        criteria = {"unclear": "It is unclear.", "red": "It is red.", "blue": "Blue."}
        problem = jq.question_set_problem(_set(_choice(criteria)))
        assert problem is not None and "last" in problem

    @pytest.mark.parametrize(
        "criteria",
        [
            {"red": "It is red.", "blue": "It is blue."},
            {**GOOD_CHOICE, "none_of_these": "Neither."},
        ],
        ids=["no-escape", "two-escapes"],
    )
    def test_the_property_refuses_to_guess_for_an_unregistrable_set(
        self, criteria: dict[str, str]
    ) -> None:
        """With two escapes, the first is a guess at which one the lane
        should read as a hold."""
        built = _set(_choice(criteria))
        with pytest.raises(ValueError, match="exactly one"):
            _ = built.escape_options

    def test_a_noul_needs_no_escape(self) -> None:
        built = _set((("yes", {"type": "noul", "instructions": "It is red."}),))
        assert jq.question_set_problem(built) is None
        assert built.escape_options == {}

    def test_every_registered_choice_has_its_escape(self) -> None:
        for question_set in jq.REGISTRY.values():
            choices = {
                key for key, q in question_set.questions if q["type"] == "choice"
            }
            assert set(question_set.escape_options) == choices


# ---------------------------------------------------------------------------
# The vendor's prose limits, and the rest of a set's shape
# ---------------------------------------------------------------------------


def _levels(n: int) -> list[str]:
    return [f"Level {i}." for i in range(n)]


def _options(n: int) -> dict[str, str]:
    """``n`` options in all, the escape last."""
    options = {f"option_{i}": f"Option {i}." for i in range(n - 1)}
    return {**options, "none_of_these": "None of the options."}


ACCEPTED: list[tuple[str, tuple[tuple[str, Any], ...]]] = [
    ("noul", (("q", {"type": "noul", "instructions": "It is red."}),)),
    (
        "noul-with-criteria",
        (
            (
                "q",
                {
                    "type": "noul",
                    "instructions": "It is red.",
                    "criteria": {"true": "Red.", "false": "Another colour."},
                },
            ),
        ),
    ),
    (
        "score-2",
        (("q", {"type": "score", "instructions": "Rate.", "criteria": _levels(2)}),),
    ),
    (
        "score-10",
        (("q", {"type": "score", "instructions": "Rate.", "criteria": _levels(10)}),),
    ),
    ("choice-3", _choice(_options(3))),
    ("choice-255", _choice(_options(jq.MAX_CHOICE_OPTIONS))),
]

REFUSED: list[tuple[str, tuple[tuple[str, Any], ...], str]] = [
    ("no-questions", (), "at least one question"),
    ("not-a-dict", (("q", "Is it red?"),), "dict"),
    ("unknown-type", (("q", {"type": "rank", "instructions": "Rank."}),), "type"),
    ("no-instructions", (("q", {"type": "noul"}),), "instructions"),
    (
        "empty-instructions",
        (("q", {"type": "noul", "instructions": "  "}),),
        "instructions",
    ),
    (
        "padded-instructions",
        (("q", {"type": "noul", "instructions": " It is red."}),),
        "whitespace",
    ),
    (
        "instructions-not-text",
        (("q", {"type": "noul", "instructions": {"task": "red?"}}),),
        "instructions",
    ),
    (
        "unknown-field",
        (("q", {"type": "noul", "instructions": "It is red.", "instruction": "x"}),),
        "fields",
    ),
    (
        "noul-criteria-with-a-third-outcome",
        (
            (
                "q",
                {
                    "type": "noul",
                    "instructions": "It is red.",
                    "criteria": {"true": "Red.", "maybe": "Pinkish."},
                },
            ),
        ),
        "true and false",
    ),
    (
        "noul-criteria-empty",
        (("q", {"type": "noul", "instructions": "It is red.", "criteria": {}}),),
        "criteria",
    ),
    (
        "score-1",
        (("q", {"type": "score", "instructions": "Rate.", "criteria": _levels(1)}),),
        "levels",
    ),
    (
        "score-11",
        (("q", {"type": "score", "instructions": "Rate.", "criteria": _levels(11)}),),
        "levels",
    ),
    (
        "score-level-empty",
        (("q", {"type": "score", "instructions": "Rate.", "criteria": ["Low.", ""]}),),
        "level 1",
    ),
    (
        "score-levels-not-a-list",
        (
            (
                "q",
                {"type": "score", "instructions": "Rate.", "criteria": ("Lo.", "Hi.")},
            ),
        ),
        "levels",
    ),
    ("choice-256", _choice(_options(jq.MAX_CHOICE_OPTIONS + 1)), "at most"),
    ("choice-with-one-real-option", _choice(_options(2)), "besides its escape"),
    ("choice-option-undescribed", _choice({**GOOD_CHOICE, "red": ""}), "'red'"),
    (
        "choice-option-not-a-key",
        _choice({"Red": "It is red.", "blue": "Blue.", "unclear": "?"}),
        "'Red'",
    ),
    (
        "question-key-not-a-key",
        (("Is it red", {"type": "noul", "instructions": "It is red."}),),
        "key",
    ),
    (
        "question-keys-repeat",
        (
            ("q", {"type": "noul", "instructions": "It is red."}),
            ("q", {"type": "noul", "instructions": "It is blue."}),
        ),
        "repeat",
    ),
    (
        "question-too-long-to-send",
        (
            (
                "q",
                {
                    "type": "noul",
                    "instructions": "x"
                    * (
                        jev_catalogue.BYTES_PER_TOKEN_ESTIMATE
                        * jev_catalogue.MAX_STATE_PLUS_LONGEST_QUESTION
                    ),
                },
            ),
        ),
        "longest question",
    ),
]


class TestTheShapeOfASet:
    @pytest.mark.parametrize(
        "questions", [q for _, q in ACCEPTED], ids=[name for name, _ in ACCEPTED]
    )
    def test_the_limits_admit_what_the_vendor_documents(
        self, questions: tuple[tuple[str, Any], ...]
    ) -> None:
        assert jq.question_set_problem(_set(questions)) is None

    @pytest.mark.parametrize(
        ("questions", "reason"),
        [(q, r) for _, q, r in REFUSED],
        ids=[name for name, _, _ in REFUSED],
    )
    def test_the_stricter_reading_is_enforced(
        self, questions: tuple[tuple[str, Any], ...], reason: str
    ) -> None:
        problem = jq.question_set_problem(_set(questions))
        assert problem is not None and reason in problem, problem

    @pytest.mark.parametrize(
        ("overrides", "reason"),
        [
            ({"name": "regime"}, "lane.subject"),
            ({"name": "Decision.Regime"}, "lane.subject"),
            ({"name": "decision.regime\n"}, "lane.subject"),
            ({"version": 0}, "1 or more"),
            ({"version": True}, "integer"),
            ({"version": "1"}, "integer"),
            ({"lane": "decisions"}, "lane"),
            ({"provenance": "vendor"}, "provenance"),
            ({"purpose": ""}, "purpose"),
            ({"state_model": dict}, "pydantic model"),
        ],
        ids=lambda value: str(value),
    )
    def test_a_set_names_itself_in_the_shared_vocabulary(
        self, overrides: dict[str, Any], reason: str
    ) -> None:
        questions = (("q", {"type": "noul", "instructions": "It is red."}),)
        problem = jq.question_set_problem(_set(questions, **overrides))
        assert problem is not None and reason in problem, problem

    @pytest.mark.parametrize("provenance", ["web", "operator"])
    def test_a_decision_set_takes_internal_provenance_only(
        self, provenance: str
    ) -> None:
        """
        The decision lane's answers are the only ones that could ever reach an
        order, so its state must be computed in code from this system's own
        rows. Text an outsider can write has no route there (C-1).
        """
        problem = jq.question_set_problem(
            dataclasses.replace(REGIME, provenance=provenance)
        )
        assert problem is not None and "internal provenance" in problem


# ---------------------------------------------------------------------------
# The state models
# ---------------------------------------------------------------------------


def _leaves(model: type[BaseModel], path: str = "") -> Iterator[tuple[str, Any]]:
    """
    Every declared leaf annotation of a model, however deeply nested.

    Written here rather than borrowed from the module, so that the registered
    states are checked by something other than the rule under test.
    """
    for name, field in model.model_fields.items():
        annotation = field.annotation
        where = f"{path}{model.__name__}.{name}"
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            yield from _leaves(annotation, f"{where}->")
        else:
            yield where, annotation


def _unenumerated_leaves(model: type[BaseModel]) -> list[str]:
    """Every declared leaf that is not a Literal or a bool: free text, a date,
    a number, an Optional or a container, each able to carry the day."""
    return [
        f"{where}: {annotation!r}"
        for where, annotation in _leaves(model)
        if not (annotation is bool or get_origin(annotation) is Literal)
    ]


def _every_sleeve() -> list[dict[str, Any]]:
    """Every sleeve there is, as plain values: 3 x 5 x 4 x 3 = 180."""
    return [
        {"trend": t, "volatility_quintile": v, "drawdown": d, "momentum": m}
        for t, v, d, m in itertools.product(
            get_args(jq.Trend),
            get_args(jq.VolatilityQuintile),
            get_args(jq.Drawdown),
            get_args(jq.Momentum),
        )
    ]


def _what_is_sent_differs(model: type[BaseModel]) -> list[str]:
    """
    Every sleeve, in every position, built into ``model`` and dumped as the
    lane dumps it. Returns each dump that is not exactly what was given.

    This reads behaviour, not declarations: a computed field adds a key, and a
    serializer replaces a value, and neither shows in a field's annotation.
    """
    sleeves = _every_sleeve()
    differences = []
    for i, sleeve in enumerate(sleeves):
        given = {
            "equities": sleeve,
            "bonds": sleeves[(i + 61) % len(sleeves)],
            "commodities": sleeves[(i + 122) % len(sleeves)],
        }
        sent = model.model_validate(given).model_dump(mode="json")
        if sent != given or list(sent) != list(given):
            differences.append(f"{given} was sent as {sent}")
    return differences


class _SleeveWithADate(jq.SleeveState):
    as_of: date


class _RegimeWithASession(jq.RegimeState):
    session: str


class _RegimeWithADatedSleeve(jq.RegimeState):
    bonds: _SleeveWithADate


class _RegimeWithAnOptionalSleeve(jq.RegimeState):
    commodities: jq.SleeveState | None = None


class _RegimeWithATicker(jq.RegimeState):
    ticker: Literal["SPY", "IEF", "GSG"] = "SPY"


class _RegimeWithAComputedDate(jq.RegimeState):
    @computed_field  # type: ignore[prop-decorator]
    @property
    def as_of(self) -> str:
        return "2020-03-16"


class _SleeveWithASerializedTrend(jq.SleeveState):
    @field_serializer("trend")
    def _dated(self, value: str) -> str:
        return "2020-03-16"


class _RegimeWithASerializedSleeve(jq.RegimeState):
    equities: _SleeveWithASerializedTrend


class _RegimeWithAModelSerializer(jq.RegimeState):
    @model_serializer(mode="wrap")
    def _with_ticker(self, handler: Any) -> dict[str, Any]:
        return {**handler(self), "ticker": "SPY"}


def _frozen_model(name: str, annotation: Any, **config: Any) -> type[BaseModel]:
    settings = {"extra": "forbid", "frozen": True, **config}
    return type(
        name,
        (BaseModel,),
        {
            "__module__": __name__,
            "__annotations__": {"field": annotation},
            "model_config": ConfigDict(**settings),
        },
    )


class _Inner(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    note: str


class _Thawed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trend: Literal["up", "down"]


#: (id, annotation) pairs a decision-lane state may not hold, one field each.
UNENUMERATED: list[tuple[str, Any]] = [
    ("free-text", str),
    ("optional-label", Literal["up", "down"] | None),
    ("nested-free-text", _Inner),
    ("nested-model-not-frozen", _Thawed),
    ("a-date", date),
    ("a-datetime", datetime),
    ("a-float", float),
    ("an-int", int),
    ("a-decimal", Decimal),
    ("bytes", bytes),
    ("a-list-of-labels", list[Literal["up", "down"]]),
    ("a-mapping-of-labels", dict[str, Literal["up", "down"]]),
    ("anything", Any),
    ("a-ticker", Literal["SPY", "IEF"]),
    ("a-date-as-a-label", Literal["2020-03-16"]),
    ("a-year", Literal[2020]),
    ("a-sentence", Literal["risk on"]),
    ("a-none-label", Literal[None]),
]


class TestTheDecisionStateIsEnumerated:
    @pytest.mark.parametrize("model", [jq.RegimeState, jq.ProbeState])
    def test_no_leaf_is_text_a_date_or_a_figure(self, model: type[BaseModel]) -> None:
        """
        The check the spec asks for, walked independently of the module: every
        leaf of the registered decision and probe states is a Literal or a
        boolean, so no ``str`` field can carry free text or a ticker and no
        date or number can carry the day.
        """
        assert list(_leaves(model)), "the walk found no fields"
        assert _unenumerated_leaves(model) == []

    @pytest.mark.parametrize(
        ("model", "leak"),
        [
            (_RegimeWithASession, "_RegimeWithASession.session"),
            (_RegimeWithADatedSleeve, "_SleeveWithADate.as_of"),
            (_RegimeWithAnOptionalSleeve, "_RegimeWithAnOptionalSleeve.commodities"),
        ],
        ids=["a-session", "a-date-in-a-sleeve", "an-optional-sleeve"],
    )
    def test_the_walk_bites(self, model: type[BaseModel], leak: str) -> None:
        """The same walk finds a str, a nested date and an Optional."""
        found = _unenumerated_leaves(model)
        assert any(leak in entry for entry in found), found

    def test_every_regime_label_is_a_lowercase_word_or_a_small_ordinal(self) -> None:
        assert _unlabelled_values(jq.RegimeState) == []

    def test_the_label_check_bites(self) -> None:
        """A Literal is not enough: a Literal of tickers is still tickers."""
        assert _unlabelled_values(_RegimeWithATicker) != []

    def test_what_is_sent_is_exactly_what_was_given(self) -> None:
        """
        Every sleeve there is, in every position, dumped as the lane dumps it.
        What would reach the vendor is exactly the values the state was built
        from, key for key, and in the order of the sleeves.
        """
        assert _what_is_sent_differs(jq.RegimeState) == []

    @pytest.mark.parametrize(
        "model",
        [
            _RegimeWithAComputedDate,
            _RegimeWithASerializedSleeve,
            _RegimeWithAModelSerializer,
        ],
        ids=["a-computed-field", "a-field-serializer", "a-model-serializer"],
    )
    def test_the_dump_check_bites_where_the_walk_cannot(
        self, model: type[BaseModel]
    ) -> None:
        """
        Each of these declares the same enumerated fields, so a walk of the
        annotations passes them, and each sends something else.
        """
        assert _unenumerated_leaves(model) == []
        assert _what_is_sent_differs(model) != []

    def test_the_registered_states_pass_the_modules_rule(self) -> None:
        assert jq.state_model_problem(jq.RegimeState, "decision") is None
        assert jq.state_model_problem(jq.ProbeState, "probe") is None

    @pytest.mark.parametrize(
        "annotation",
        [a for _, a in UNENUMERATED],
        ids=[name for name, _ in UNENUMERATED],
    )
    def test_the_rule_refuses_what_could_carry_the_day(self, annotation: Any) -> None:
        model = _frozen_model("Leaky", annotation)
        problem = jq.state_model_problem(model, "decision")
        assert problem is not None and "Leaky.field" in problem, problem

    @pytest.mark.parametrize(
        ("model", "reason"),
        [
            (_RegimeWithASession, "session"),
            (_RegimeWithADatedSleeve, "as_of"),
            (_RegimeWithAnOptionalSleeve, "commodities"),
            (_RegimeWithATicker, "ticker"),
            (_RegimeWithAComputedDate, "computed"),
            (_RegimeWithASerializedSleeve, "serializer"),
            (_RegimeWithAModelSerializer, "serializer"),
        ],
        ids=[
            "a-session",
            "a-date-in-a-sleeve",
            "an-optional-sleeve",
            "a-ticker",
            "a-computed-field",
            "a-field-serializer",
            "a-model-serializer",
        ],
    )
    @pytest.mark.parametrize("lane", sorted(jq.ENUMERATED_LANES))
    def test_the_rule_refuses_every_leak_the_checks_above_find(
        self, model: type[BaseModel], reason: str, lane: str
    ) -> None:
        problem = jq.state_model_problem(model, lane)
        if lane not in jq.LABELLED_LANES and model is _RegimeWithATicker:
            # A fixed Literal is a fine probe state; the label rule is the
            # decision lane's.
            assert problem is None
            return
        assert problem is not None and reason in problem, problem

    def test_other_lanes_may_compute_and_serialise(self) -> None:
        """A research lane sends text by design; only the configuration binds."""
        assert jq.state_model_problem(_RegimeWithAComputedDate, "research") is None
        assert jq.state_model_problem(_RegimeWithASerializedSleeve, "ops") is None

    def test_the_rule_names_the_nested_path(self) -> None:
        problem = jq.state_model_problem(_frozen_model("Outer", _Inner), "decision")
        assert problem is not None and "Outer.field.note" in problem

    @pytest.mark.parametrize(
        ("config", "reason"),
        [({"extra": "ignore"}, "extra"), ({"frozen": False}, "frozen")],
    )
    def test_every_state_is_closed_and_frozen(
        self, config: dict[str, Any], reason: str
    ) -> None:
        model = _frozen_model("Open", Literal["up"], **config)
        for lane in jev_catalogue.LANES:
            problem = jq.state_model_problem(model, lane)
            assert problem is not None and reason in problem, (lane, problem)

    def test_the_label_rule_is_the_decision_lanes(self) -> None:
        """A sentence is a fine fixed probe state and no decision label."""
        model = _frozen_model("Sentence", Literal["The sun rises in the east."])
        assert jq.state_model_problem(model, "probe") is None
        assert jq.state_model_problem(model, "decision") is not None

    def test_other_lanes_may_carry_text(self) -> None:
        """A research lane classifies web text; its state is text by design."""
        assert jq.state_model_problem(_TextState, "research") is None
        assert jq.state_model_problem(_TextState, "decision") is not None
        assert jq.state_model_problem(_TextState, "probe") is not None

    def test_registration_applies_the_rule(self) -> None:
        leaky = dataclasses.replace(REGIME, state_model=_RegimeWithAComputedDate)
        problem = jq.question_set_problem(leaky)
        assert problem is not None and "computed" in problem

    def test_the_regime_state_is_the_sleeves_and_nothing_else(self) -> None:
        assert tuple(jq.RegimeState.model_fields) == jq.SLEEVES
        assert tuple(jq.SleeveState.model_fields) == (
            "trend",
            "volatility_quintile",
            "drawdown",
            "momentum",
        )

    @pytest.mark.parametrize("quintile", [True, 3.0, "3", 0, 6])
    def test_a_quintile_is_an_integer_from_one_to_five(self, quintile: object) -> None:
        """
        ``True`` and ``3.0`` compare equal to Literal members, and pydantic
        accepts them even in strict mode without the validator.
        """
        with pytest.raises(ValidationError):
            jq.SleeveState(
                trend="near",
                volatility_quintile=quintile,  # type: ignore[arg-type]
                drawdown="none",
                momentum="flat",
            )

    def test_a_state_is_closed_and_frozen(self) -> None:
        sleeve = jq.SleeveState(
            trend="near", volatility_quintile=3, drawdown="none", momentum="flat"
        )
        with pytest.raises(ValidationError):
            jq.SleeveState(
                trend="near",
                volatility_quintile=3,
                drawdown="none",
                momentum="flat",
                symbol="SPY",  # type: ignore[call-arg]
            )
        with pytest.raises(ValidationError):
            sleeve.trend = "above"  # type: ignore[misc]

    def test_a_stored_state_reads_back_as_the_state_it_was(self) -> None:
        """
        The lane stores ``model_dump(mode="json")``. Strict mode must still
        read that back, from the JSON text and from the decoded object, or a
        recorded state could never be re-validated.
        """
        state = jq.RegimeState.model_validate(
            {s: _every_sleeve()[i * 50] for i, s in enumerate(jq.SLEEVES)}
        )
        stored = state.model_dump(mode="json")
        assert jq.RegimeState.model_validate_json(json.dumps(stored)) == state
        assert jq.RegimeState.model_validate(stored) == state

    def test_the_probe_state_is_one_fixed_sentence(self) -> None:
        """
        Pinned here because the state is not in the pack hash, and the probe's
        answer is known only for this sentence: about the sun, and true.
        """
        assert jq.PROBE_TEXT == "The sun rises in the east."
        assert jq.ProbeState().model_dump(mode="json") == {"text": jq.PROBE_TEXT}
        with pytest.raises(ValidationError):
            jq.ProbeState(text="The moon rises in the east.")  # type: ignore[arg-type]

    def test_a_probe_default_that_drifted_is_an_error(self) -> None:
        """
        What ``validate_default`` is for: an edit that changed the default and
        not the Literal fails at construction, rather than making a probe that
        asks about a sentence its own type forbids.
        """
        drifted = type(
            "Drifted",
            (BaseModel,),
            {
                "__module__": __name__,
                "__annotations__": {"text": Literal["The sun rises in the east."]},
                "text": "The sun rises in the west.",
                "model_config": jq.ProbeState.model_config,
            },
        )
        with pytest.raises(ValidationError):
            drifted()

    @pytest.mark.parametrize("value", [1, "true", "yes", 0.0])
    def test_a_boolean_in_a_state_is_a_boolean(self, value: object) -> None:
        """
        What ``strict`` is for. A boolean is the one field type the enumerated
        lanes allow besides a Literal, and a lax one reads each of these as a
        boolean: a caller that computed the wrong thing would be told nothing.
        """
        flagged = type(
            "Flagged",
            (BaseModel,),
            {
                "__module__": __name__,
                "__annotations__": {"flag": bool},
                "model_config": jq._STATE_CONFIG,
            },
        )
        assert jq.state_model_problem(flagged, "decision") is None
        with pytest.raises(ValidationError):
            flagged(flag=value)
        assert flagged(flag=True).flag is True


def _any_regime_state() -> jq.RegimeState:
    sleeves = _every_sleeve()
    return jq.RegimeState.model_validate(
        {sleeve: sleeves[i * 60] for i, sleeve in enumerate(jq.SLEEVES)}
    )


class TestDumpingAState:
    """
    ``QuestionSet.dump_state`` is how a state becomes what is sent. The spec
    asks the lane for an instance of the set's state model; ``isinstance``
    admits a subclass, and a subclass can send what the registered class
    cannot.
    """

    def test_an_instance_of_the_model_is_dumped_as_json(self) -> None:
        state = _any_regime_state()
        assert REGIME.dump_state(state) == state.model_dump(mode="json")
        assert PROBE.dump_state(jq.ProbeState()) == {"text": jq.PROBE_TEXT}

    def test_a_subclass_is_refused_because_it_can_send_a_date(self) -> None:
        state = _RegimeWithAComputedDate.model_validate(
            _any_regime_state().model_dump()
        )
        assert isinstance(state, jq.RegimeState), "the premise: isinstance admits it"
        assert state.model_dump(mode="json")["as_of"] == "2020-03-16", (
            "the premise: its own dump carries a date"
        )
        with pytest.raises(TypeError, match="exactly"):
            REGIME.dump_state(state)

    def test_a_state_with_a_date_reads_back_from_its_json(self) -> None:
        """
        A research lane's state may carry a date. Under the shared strict
        configuration a date is read only from JSON text, so the read-back
        has to go through JSON, as a stored state's would.
        """
        dated = type(
            "Dated",
            (BaseModel,),
            {
                "__module__": __name__,
                "__annotations__": {"text": str, "published": date},
                "model_config": jq._STATE_CONFIG,
            },
        )
        built = _set(
            (("q", {"type": "noul", "instructions": "It is red."}),),
            state_model=dated,
        )
        assert jq.question_set_problem(built) is None
        state = dated(text="A filing.", published=date(2026, 9, 25))
        assert built.dump_state(state) == {
            "text": "A filing.",
            "published": "2026-09-25",
        }

    def test_another_sets_state_is_refused(self) -> None:
        with pytest.raises(TypeError):
            REGIME.dump_state(jq.ProbeState())
        with pytest.raises(TypeError):
            PROBE.dump_state(_any_regime_state())

    def test_a_state_built_without_validation_is_refused(self) -> None:
        """``model_construct`` skips validation; what would be sent does not."""
        good = _any_regime_state()
        forged = jq.RegimeState.model_construct(
            equities=jq.SleeveState.model_construct(
                trend="2020-03-16",
                volatility_quintile=3,
                drawdown="none",
                momentum="flat",
            ),
            bonds=good.bonds,
            commodities=good.commodities,
        )
        assert type(forged) is jq.RegimeState
        with pytest.raises(ValidationError):
            REGIME.dump_state(forged)


def _unlabelled_values(model: type[BaseModel]) -> list[str]:
    """Literal values that are not a lowercase word or an ordinal up to 100."""
    found = []
    for where, annotation in _leaves(model):
        for value in get_args(annotation):
            if isinstance(value, bool):
                continue
            if isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]*", value):
                continue
            if type(value) is int and 0 <= value <= 100:
                continue
            found.append(f"{where}: {value!r}")
    return found


# ---------------------------------------------------------------------------
# How the regime question is written
# ---------------------------------------------------------------------------

#: Words that negate. Jev reads literally, and the vendor answers a question as
#: written, so none may appear where the model reads prose.
NEGATIONS = frozenset(
    {
        "not",
        "no",
        "never",
        "none",
        "neither",
        "nor",
        "nothing",
        "nobody",
        "nowhere",
        "without",
        "cannot",
        "unless",
        "except",
        "lacks",
        "lacking",
        "absent",
    }
)


def _negations(text: str) -> list[str]:
    """
    Negating words in ``text``, outside double-quoted labels.

    A quoted label is state vocabulary, not prose: ``"none"`` is the name of
    the smallest drawdown bucket. Every quoted label is separately required to
    be a value the state can hold, so quotes cannot hide a sentence.
    """
    prose = re.sub(r'"[^"]*"', " ", text).lower()
    words = re.findall(r"[a-z]+(?:'[a-z]+)?", prose)
    return [
        w for w in words if w in NEGATIONS or w.endswith("n't") or w.endswith("less")
    ]


def _prose(question_set: QuestionSet) -> list[str]:
    texts: list[str] = []
    for _, question in question_set.questions:
        texts.append(question["instructions"])
        criteria = question.get("criteria")
        if isinstance(criteria, dict):
            texts.extend(criteria.values())
        elif isinstance(criteria, list):
            texts.extend(criteria)
    return texts


def _state_labels() -> set[str]:
    return {
        value
        for _, annotation in _leaves(jq.RegimeState)
        for value in get_args(annotation)
        if isinstance(value, str)
    }


def _field_paths(model: type[BaseModel], prefix: str = "") -> Iterator[str]:
    """Every dotted path into ``model``: ``equities``, ``equities.trend``, ..."""
    for name, field in model.model_fields.items():
        yield f"{prefix}{name}"
        annotation = field.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            yield from _field_paths(annotation, f"{prefix}{name}.")


def _backticked(text: str) -> list[str]:
    return re.findall(r"`([^`]*)`", text)


class TestTheRegimeQuestionIsWrittenPlainly:
    @pytest.mark.parametrize(
        "text",
        [
            'Equities are not "above".',
            "The trend isn't rising.",
            "Momentum without direction.",
            "The market is directionless.",
            "Nothing matches.",
        ],
    )
    def test_the_negation_check_bites(self, text: str) -> None:
        assert _negations(text), text

    def test_the_negation_check_reads_labels_as_labels(self) -> None:
        assert _negations('drawdown "none" or "shallow"') == []

    @pytest.mark.parametrize("name", sorted(jq.REGISTRY))
    def test_no_question_is_asked_with_a_negation(self, name: str) -> None:
        for text in _prose(jq.get(name)):
            assert not _negations(text), (_negations(text), text)

    @pytest.mark.parametrize("name", sorted(jq.REGISTRY))
    def test_the_instructions_open_with_the_question(self, name: str) -> None:
        """The judgment goes in the instructions, first, as a question."""
        for _, question in jq.get(name).questions:
            first = re.split(r"(?<=[.?])\s", question["instructions"])[0]
            assert first.endswith("?"), first

    def test_every_quoted_label_is_one_the_state_can_hold(self) -> None:
        """
        The question and the state must use one vocabulary. A criterion that
        named "shalow" would describe a state that never occurs, and the model
        would answer about it anyway.
        """
        quoted = {
            label for text in _prose(REGIME) for label in re.findall(r'"([^"]*)"', text)
        }
        assert quoted, "the regime question quotes no labels at all"
        assert quoted <= _state_labels(), quoted - _state_labels()

    @pytest.mark.parametrize("name", sorted(jq.REGISTRY))
    def test_every_field_the_question_names_is_one_the_state_has(
        self, name: str
    ) -> None:
        """
        Fields are named by backticked path, as TypeSafe's guidance has it. A
        path that does not resolve — ``equity.trend``, ``bonds.volatility`` —
        points the model at nothing, and it answers anyway.
        """
        question_set = jq.get(name)
        paths = set(_field_paths(question_set.state_model))
        known = paths | {path.rsplit(".", 1)[-1] for path in paths}
        named = {path for text in _prose(question_set) for path in _backticked(text)}
        assert named, f"{name} names no state field"
        assert named <= known, named - known

    def test_the_criteria_name_each_field_by_its_whole_path(self) -> None:
        """
        The legend may say `trend` once for every asset class. A criterion
        names which asset class it means, every time: the model is weak with
        indirection, and "its trend" is indirection.
        """
        for option, text in _regime_question()["criteria"].items():
            for path in _backticked(text):
                assert "." in path, (option, path)

    def test_the_legend_covers_the_whole_vocabulary(self) -> None:
        instructions = _regime_question()["instructions"]
        for sleeve in jq.SLEEVES:
            assert f"`{sleeve}`" in instructions, sleeve
        for descriptor in jq.SleeveState.model_fields:
            assert f"`{descriptor}`" in instructions, descriptor
        for label in _state_labels():
            assert f'"{label}"' in instructions, label

    def test_the_escape_is_the_answer_for_conflicting_descriptors(self) -> None:
        escape = REGIME.escape_options["regime"]
        assert escape == "insufficient_evidence"
        text = _regime_question()["criteria"][escape]
        assert "conflict" in text.lower()
        assert "Choose this option whenever the descriptors point in different" in (
            text
        )

    def test_the_question_names_no_date_and_no_ticker(self) -> None:
        for text in _prose(REGIME):
            assert not re.search(r"\b(1[89]|20)\d\d\b", text), text
            assert not re.search(r"\b\d{4}-\d{2}-\d{2}\b", text), text
            assert not re.search(r"\b[A-Z]{2,5}\b", text), text


def test_the_api_importable_modules_load_no_client_and_no_io() -> None:
    """
    The API will import this module and the catalogue. Importing both, in a
    fresh interpreter, must load nothing that can reach a network, a database
    or a model, and none of the runner.
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
        "yfinance",
        "src.db",
        "src.programme.client",
        "src.programme.jev_client",
        "src.programme.jev_lane",
        "src.programme.jev_features",
    )
    code = (
        "import sys\n"
        "import src.programme.jev_catalogue, src.programme.jev_questions\n"
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
