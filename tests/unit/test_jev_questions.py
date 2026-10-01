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
  have, spells out a rule over the labels in place of what each regime means,
  or gives its escape a condition of its own instead of the complement of a
  clear fit.
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
import warnings
from collections.abc import Callable, Iterator
from datetime import date, datetime
from decimal import Decimal
from enum import Enum, StrEnum
from pathlib import Path
from typing import (
    Annotated,
    Any,
    Generic,
    Literal,
    NamedTuple,
    NewType,
    TypeVar,
    get_args,
    get_origin,
)

import pytest
from pydantic import (
    AfterValidator,
    AnyUrl,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    GetCoreSchemaHandler,
    PlainSerializer,
    PlainValidator,
    SecretStr,
    StringConstraints,
    ValidationError,
    WrapSerializer,
    WrapValidator,
    computed_field,
    create_model,
    field_serializer,
    field_validator,
    model_serializer,
    model_validator,
    root_validator,
    validator,
)
from pydantic.dataclasses import dataclass as pydantic_dataclass
from pydantic_core import core_schema
from typing_extensions import TypedDict

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


#: Every registered set, exactly: its version, lane, provenance and state
#: model. Phase B's probe and regime; phase C7's injection screen and
#: catalogue, asked about web text; phase C8's two sets asked about the titles
#: the programme's own model writes.
REGISTERED: dict[str, tuple[int, str, str, type[BaseModel]]] = {
    "probe.connectivity": (1, "probe", "internal", jq.ProbeState),
    "decision.regime": (1, "decision", "internal", jq.RegimeState),
    "guardrail.injection": (1, "guardrail", "web", jq.WebExcerptState),
    "research.catalogue": (1, "research", "web", jq.WebExcerptState),
    "research.hypothesis": (1, "research", "model", jq.HypothesisTitleState),
    "guardrail.card": (1, "guardrail", "model", jq.HypothesisTitleState),
}


class TestTheRegistry:
    def test_the_registry_is_exactly_the_six_sets(self) -> None:
        """
        An exact pin, both ways: a set added, removed, moved to another lane
        or provenance, or given another state is a reviewer's edit here, with
        its words, its golden and its released rows beside it.
        """
        assert {
            name: (qs.version, qs.lane, qs.provenance, qs.state_model)
            for name, qs in jq.REGISTRY.items()
        } == REGISTERED
        assert jq.PROBE_CONNECTIVITY is PROBE
        assert jq.DECISION_REGIME is REGIME
        assert jq.GUARDRAIL_INJECTION is jq.get(jq.SCREEN_SET_NAME)
        assert jq.RESEARCH_CATALOGUE is jq.get("research.catalogue")
        assert jq.RESEARCH_HYPOTHESIS is jq.get("research.hypothesis")
        assert jq.GUARDRAIL_CARD is jq.get("guardrail.card")
        assert not any(qs.internal_detail for qs in jq.REGISTRY.values())

    def test_the_registered_screen_is_the_screen(self) -> None:
        """
        The lane lets the screen alone ask about unscreened text and reads its
        valid ``false`` as clean, so the registered screen must be of the
        screen's shape (``screen_problem``), and its ``false`` must be the
        answer that means the text is written for people.
        """
        screen = jq.get(jq.SCREEN_SET_NAME)
        assert jq.screen_problem(screen) is None
        ((key, question),) = screen.questions
        assert (key, question["type"]) == (jq.SCREEN_QUESTION, "noul")
        assert jq.SCREEN_CLEAR_ARGMAX == "false"
        assert question["criteria"]["false"].startswith(
            "`excerpt` is written for human readers"
        )

    def test_the_two_title_sets_share_the_catalogues_options(self) -> None:
        """
        Word for word, option for option, so the programme's hypotheses can be
        compared with what is published; the instructions differ, which keeps
        each set's questions its own (open item 15).
        """
        catalogue = dict(jq.RESEARCH_CATALOGUE.questions)
        hypothesis = dict(jq.RESEARCH_HYPOTHESIS.questions)
        assert list(catalogue) == list(hypothesis) == ["asset_class", "mechanism"]
        for key in catalogue:
            assert catalogue[key]["criteria"] == hypothesis[key]["criteria"]
            assert list(catalogue[key]["criteria"]) == list(
                hypothesis[key]["criteria"]
            )
            assert catalogue[key]["instructions"] != hypothesis[key]["instructions"]
        assert dict(catalogue["asset_class"]["criteria"]) == dict(
            jq.ASSET_CLASS_CRITERIA
        )
        assert dict(catalogue["mechanism"]["criteria"]) == dict(jq.MECHANISM_CRITERIA)

    def test_other_mechanism_is_an_option_and_not_a_second_escape(self) -> None:
        assert jq.RESEARCH_CATALOGUE.escape_options == {
            "asset_class": "insufficient_evidence",
            "mechanism": "insufficient_evidence",
        }
        assert "other_mechanism" in jq.MECHANISM_CRITERIA
        assert "other_mechanism" not in jq.ESCAPE_OPTIONS

    def test_the_heading_labels_are_the_catalogue_options(self) -> None:
        """
        The README's seven headings are its own grouping, recorded as labels
        of ``research.catalogue``'s ``asset_class`` (``web_ingest``): each
        heading's label must be an option of that question, in the same
        order, and together they are every option but the escape, so no label
        names a class the question cannot answer and no class has no heading.
        """
        from src.programme import web_sources

        options = list(jq.ASSET_CLASS_CRITERIA)
        escape = jq.RESEARCH_CATALOGUE.escape_options["asset_class"]
        assert options[-1] == escape
        assert list(web_sources.HEADING_LABELS.values()) == options[:-1]

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


#: Every released version's pack hash, kept as history apart from the words it
#: pins. A version bump appends a row; no row is ever edited or removed.
#: ``GOLDEN_PACK_HASHES`` in the module holds the current versions only and
#: sits beside the words, so re-recording it is exactly the edit a developer
#: makes when a hash test fails. Changing a released version's words therefore
#: also takes an edit to this table's history, which a reviewer sees for what it
#: is: answers to the old words and the new would pool under one version.
RELEASED_PACK_HASHES: dict[tuple[str, int], str] = {
    ("probe.connectivity", 1): (
        "5d5d091e936ae7b0a2006d2d2a92f90c7a08b0bbe55453550ef2c08c2370560e"
    ),
    ("decision.regime", 1): (
        "5a773b26917236fd8cf0174dfde9cc9fe81d0af4027a3eb0a2261f54dc6acff9"
    ),
    # Phase C7 and C8: the hashes design section 5 computed from these words.
    ("guardrail.injection", 1): (
        "85229106585af6df8c8ca06ffd3389f1f193518bad04f27a948814da84068ab6"
    ),
    ("research.catalogue", 1): (
        "d38726771baf313f3ff28f19059f075258d58ba34854d8ee29b2547418a3976d"
    ),
    ("research.hypothesis", 1): (
        "35124e7667f7a2b3883c35d7e82806d349e8fe71ac769f644cba5f944eb0e0eb"
    ),
    ("guardrail.card", 1): (
        "3f98bbc1511995b4ba35563f271a3d043eb4db43e23912d035785605e0ebd455"
    ),
}


#: Every released version's questions hash (``QuestionSet.questions_hash``):
#: the part of the request hash a set contributes, which names no set. Kept as
#: history apart from the words, like ``RELEASED_PACK_HASHES``, append-only,
#: and pairwise distinct, so no two released versions — of one set or of two,
#: registered now or retired — ever send identical questions. Two that did
#: would share one canonical answer about an identical state (docs/08 open
#: item 15). A version bump that changed only a lane or a provenance, or only
#: the version, would repeat its predecessor's row and is refused.
RELEASED_QUESTION_HASHES: dict[tuple[str, int], str] = {
    ("probe.connectivity", 1): (
        "8bf87c9201dca8cdffc44b433a8bf729ce11b1413defbe471e934305d26bb38c"
    ),
    ("decision.regime", 1): (
        "6dce8dbea5303a4836a4677ca3090272c29ae3f9a11e44387009ddc9fd815c9f"
    ),
    ("guardrail.injection", 1): (
        "99cdb40396c439a2c6cdb37e91c0f9df0eeeda72fc01b68c80d78a851c00f746"
    ),
    ("research.catalogue", 1): (
        "d26085158868df35d2b8ecfc6ffb31f7a3fa7de52bcbc3a9b1a9554c8ebbfc18"
    ),
    ("research.hypothesis", 1): (
        "5a75a21d2acc4800f9c197939ede7fe5f7a79a897a46fa56706cb4d603513a57"
    ),
    ("guardrail.card", 1): (
        "47c322e70d5b3f5cdb69bb6547150c54d2d99197fb922e785917e7f11b42c130"
    ),
}


def _question_hash_problems(
    registry: dict[str, QuestionSet], released: dict[tuple[str, int], str]
) -> list[str]:
    """How the registered sets and the released questions hashes disagree."""
    problems: list[str] = []
    for question_set in registry.values():
        key = (question_set.name, question_set.version)
        if key not in released:
            problems.append(f"{key} is not in RELEASED_QUESTION_HASHES: append it")
        elif released[key] != question_set.questions_hash:
            problems.append(
                f"{key} asks questions hashing to {question_set.questions_hash}, "
                f"but was released as {released[key]}"
            )
    seen: dict[str, tuple[str, int]] = {}
    for key, value in released.items():
        if value in seen:
            problems.append(
                f"{key} asks exactly the questions {seen[value]} asked: two "
                "released versions would share one canonical answer"
            )
        seen.setdefault(value, key)
    return problems


def _release_problems(module: types.ModuleType) -> list[str]:
    """How the registered sets in ``module`` differ from what was released."""
    problems: list[str] = []
    for question_set in module.REGISTRY.values():
        key = (question_set.name, question_set.version)
        released = RELEASED_PACK_HASHES.get(key)
        if released is None:
            problems.append(f"{key} is not in RELEASED_PACK_HASHES: append it")
            continue
        if question_set.pack_hash != released:
            problems.append(
                f"{key} hashes to {question_set.pack_hash}, but was released as "
                f"{released}: a released version's words are frozen, so bump "
                "the version and append a row"
            )
        if module.GOLDEN_PACK_HASHES.get(key) != released:
            problems.append(f"{key}'s golden disagrees with its release")
        newest = max(v for (n, v) in RELEASED_PACK_HASHES if n == question_set.name)
        if question_set.version != newest:
            problems.append(f"{key} is registered, but v{newest} was released")
    return problems


class TestTheGoldenHashes:
    def test_every_registered_set_is_its_released_words(self) -> None:
        assert _release_problems(jq) == []

    def test_rewording_a_released_version_is_refused_with_its_golden_redone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        The edit a developer makes when a hash test fails: new words, and the
        golden re-recorded to match. The module's own table agrees with itself
        afterwards; the release history does not.
        """
        source = MODULE.read_text(encoding="utf-8")
        question = "Which market regime do these descriptors show?"
        assert source.count(question) == 1
        reworded = question.replace("show?", "indicate?")
        variant = _execute_variant(monkeypatch, source.replace(question, reworded))
        key = ("decision.regime", 1)
        variant.GOLDEN_PACK_HASHES[key] = variant.DECISION_REGIME.pack_hash
        assert variant.DECISION_REGIME.pack_hash != RELEASED_PACK_HASHES[key]
        assert any("words are frozen" in p for p in _release_problems(variant))

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


class TestOpenItem15:
    """
    No answer crosses question sets. The request hash is the hash of the pinned
    model, the state and the questions, and names no set, so two sets asking
    identical questions about an identical state would share one canonical row
    and the second would be answered with the first's. Three independent
    mechanisms: the registry refuses a set asking a registered set's questions
    (here); the released questions hashes are append-only and pairwise
    distinct, which covers words no longer in code (here); and the lane raises
    on a canonical row of another pack (``test_jev_lane.py::TestNoAnswerCrossesSets``).
    """

    def test_identical_questions_under_another_name_are_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(jq, "REGISTRY", dict(jq.REGISTRY))
        for question_set in list(jq.REGISTRY.values()):
            copy_of = dataclasses.replace(
                question_set,
                name=f"{question_set.lane}.copy",
                purpose="The same words under another name.",
            )
            assert jq.question_set_problem(copy_of) is None
            with pytest.raises(ValueError, match="open item 15"):
                jq._register(copy_of)
            assert copy_of.name not in jq.REGISTRY

    @pytest.mark.parametrize(
        "change",
        [
            {"lane": "research", "provenance": "model"},
            {"provenance": "operator"},
            {"version": 2},
        ],
        ids=["lane-and-provenance", "provenance", "version"],
    )
    def test_the_rule_reads_the_words_not_the_label(
        self, monkeypatch: pytest.MonkeyPatch, change: dict[str, Any]
    ) -> None:
        """
        Another lane, provenance or version is another pack and the same
        request: what the model reads is the words, and the words are what is
        compared.
        """
        monkeypatch.setattr(jq, "REGISTRY", dict(jq.REGISTRY))
        relabelled = dataclasses.replace(
            PROBE, name="research.sun", purpose="The same words, relabelled.", **change
        )
        assert relabelled.pack_hash != PROBE.pack_hash
        problem = jq.registration_problem(relabelled, jq.REGISTRY)
        assert problem is not None and "open item 15" in problem

    def test_other_words_are_another_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(jq, "REGISTRY", dict(jq.REGISTRY))
        key, question = PROBE.questions[0]
        reworded = dataclasses.replace(
            PROBE,
            name="probe.moon",
            questions=(
                (key, {**question, "instructions": "Is the sentence in `text` true?"}),
            ),
        )
        assert jq.registration_problem(reworded, jq.REGISTRY) is None

    def test_every_registered_set_is_its_released_question_hash(self) -> None:
        assert _question_hash_problems(jq.REGISTRY, RELEASED_QUESTION_HASHES) == []

    def test_released_question_hashes_are_pairwise_distinct(self) -> None:
        values = list(RELEASED_QUESTION_HASHES.values())
        assert len(set(values)) == len(values)
        assert set(RELEASED_QUESTION_HASHES) == set(RELEASED_PACK_HASHES), (
            "every released version has both rows, and nothing else does"
        )

    def test_a_version_bump_must_change_the_words(self) -> None:
        """
        The bump a developer might make to move a set to another lane, with its
        words untouched: its row would repeat its predecessor's, and the check
        that holds every row distinct refuses it, although the predecessor is
        no longer registered.
        """
        bumped = dataclasses.replace(REGIME, version=2, lane="research")
        registry = {REGIME.name: bumped}
        released = {
            **RELEASED_QUESTION_HASHES,
            (bumped.name, bumped.version): bumped.questions_hash,
        }
        problems = _question_hash_problems(registry, released)
        assert any("asks exactly the questions" in p for p in problems), problems

    def test_the_check_catches_a_row_that_disagrees(self) -> None:
        wrong = {**RELEASED_QUESTION_HASHES, ("decision.regime", 1): "0" * 64}
        problems = _question_hash_problems(jq.REGISTRY, wrong)
        assert any("was released as" in p for p in problems), problems

    def test_the_hash_is_the_part_of_the_request_a_set_contributes(self) -> None:
        for question_set in jq.REGISTRY.values():
            text = json.dumps(
                question_set.as_request_questions(),
                separators=(",", ":"),
                ensure_ascii=False,
            )
            assert question_set.questions_hash == (
                hashlib.sha256(text.encode("utf-8")).hexdigest()
            )


_TEST_CONFIG = ConfigDict(extra="forbid", frozen=True, strict=True)


class _Titled(BaseModel):
    model_config = _TEST_CONFIG
    title: str


class _Detailed(BaseModel):
    model_config = _TEST_CONFIG
    title: str
    body: str


class _Noted(BaseModel):
    model_config = _TEST_CONFIG
    title: str
    notes: dict[str, str] = {}


class _Nested(BaseModel):
    model_config = _TEST_CONFIG
    title: str
    card: _Titled


class _Labelled(BaseModel):
    model_config = _TEST_CONFIG
    title: str
    kind: Literal["idea", "finding"]
    urgent: bool


# ---------------------------------------------------------------------------
# Shapes the detail rule must read as text, and shapes it may read as none
# ---------------------------------------------------------------------------
#
# Each is a state model of a plain ``title`` and one more field, or a title of
# another shape, built for these tests alone. The rule fails closed, so the
# first list is every way found to carry text past a rule that read only
# ``str`` — a dataclass, a TypedDict, a URL, a validator that stands in for its
# type — and the second is what it must still let through, so that failing
# closed does not become refusing everything.


@dataclasses.dataclass(frozen=True)
class _CardDataclass:
    body: str


@pydantic_dataclass(frozen=True)
class _CardPydanticDataclass:
    body: str


class _CardTypedDict(TypedDict):
    body: str


class _CardNamedTuple(NamedTuple):
    body: str


class _Colour(Enum):
    RED = "red"


_Body = NewType("_Body", str)

_T = TypeVar("_T")


@pydantic_dataclass(frozen=True)
class _Box(Generic[_T]):
    """A generic container whose type argument holds no text, and whose other
    field does: read through its argument, it would look like none."""

    value: _T
    note: str


class _SpelledInt(int):
    """An integer that brings a schema of its own, and is sent as words."""

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.no_info_after_validator_function(
            cls,
            handler(int),
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda value: f"the number {int(value)}"
            ),
        )


class _Loose(BaseModel):
    """Labels only, but it keeps keys nobody declared."""

    model_config = ConfigDict(extra="allow", frozen=True)
    kind: Literal["idea"]


class _Labels(BaseModel):
    model_config = _TEST_CONFIG
    kind: Literal["idea", "finding"]
    urgent: bool
    count: int


def _beside_a_title(name: str, annotation: Any, **config: Any) -> type[BaseModel]:
    """A state model of a plain ``title`` and one field, ``other``."""
    return create_model(
        name,
        __config__=ConfigDict(**{**_TEST_CONFIG, **config}),
        __module__=__name__,
        title=(str, ...),
        other=(annotation, ...),
    )


def _titled_as(name: str, annotation: Any) -> type[BaseModel]:
    """A state model whose only field is a ``title`` of another shape."""
    return create_model(
        name,
        __config__=_TEST_CONFIG,
        __module__=__name__,
        title=(annotation, ...),
    )


class _ComputedField(BaseModel):
    model_config = _TEST_CONFIG
    title: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def summary(self) -> int:
        return 1


class _FieldSerializer(BaseModel):
    model_config = _TEST_CONFIG
    title: str
    count: int

    @field_serializer("count")
    def _spelled(self, value: int) -> int:
        return value


class _ModelSerializer(BaseModel):
    model_config = _TEST_CONFIG
    title: str

    @model_serializer
    def _whole(self) -> dict[str, Any]:
        return {"title": self.title}


class _FieldValidatedBefore(BaseModel):
    model_config = _TEST_CONFIG
    title: str
    count: int

    @field_validator("count", mode="before")
    @classmethod
    def _check(cls, value: Any) -> Any:
        return value


class _FieldValidatedAfter(BaseModel):
    model_config = _TEST_CONFIG
    title: str
    count: int

    @field_validator("count", mode="after")
    @classmethod
    def _check(cls, value: int) -> int:
        return value


class _FieldValidatedWrap(BaseModel):
    model_config = _TEST_CONFIG
    title: str
    count: int

    @field_validator("count", mode="wrap")
    @classmethod
    def _check(cls, value: Any, handler: Callable[[Any], Any]) -> Any:
        return handler(value)


class _FieldValidatedPlain(BaseModel):
    model_config = _TEST_CONFIG
    title: str
    count: int

    @field_validator("count", mode="plain")
    @classmethod
    def _check(cls, value: Any) -> Any:
        return value


class _EveryFieldValidatedAfter(BaseModel):
    model_config = _TEST_CONFIG
    title: str
    count: int

    @field_validator("*", mode="after")
    @classmethod
    def _check(cls, value: Any) -> Any:
        return value


class _ModelValidatedBefore(BaseModel):
    model_config = _TEST_CONFIG
    title: str
    count: int

    @model_validator(mode="before")
    @classmethod
    def _check(cls, data: Any) -> Any:
        return data


class _ModelValidatedAfter(BaseModel):
    model_config = _TEST_CONFIG
    title: str
    count: int

    @model_validator(mode="after")
    def _check(self) -> _ModelValidatedAfter:
        return self


class _ModelValidatedWrap(BaseModel):
    model_config = _TEST_CONFIG
    title: str
    count: int

    @model_validator(mode="wrap")
    @classmethod
    def _check(cls, data: Any, handler: Callable[[Any], Any]) -> Any:
        return handler(data)


with warnings.catch_warnings():
    # pydantic's own validators of before version 2, which it still runs and
    # warns about: the rule reads them as it reads their successors.
    warnings.simplefilter("ignore")

    class _DeprecatedValidator(BaseModel):
        model_config = _TEST_CONFIG
        title: str
        count: int

        @validator("count")
        def _post(cls, value: int) -> int:  # noqa: N805
            return value

    class _DeprecatedRootValidator(BaseModel):
        model_config = _TEST_CONFIG
        title: str
        count: int

        @root_validator(skip_on_failure=True)
        def _post(cls, values: dict[str, Any]) -> dict[str, Any]:  # noqa: N805
            return values

    _JsonEncoded = _beside_a_title(
        "_JsonEncoded", int, json_encoders={int: lambda value: "detail"}
    )


#: State models that can carry text beyond a plain title, each refused without
#: ``internal_detail`` and admitted with it.
CARRIES_TEXT: dict[str, type[BaseModel]] = {
    "a-str": _Detailed,
    "a-dict-of-str": _Noted,
    "a-model-with-a-title": _Nested,
    "bytes": _beside_a_title("_Bytes", bytes),
    "any": _beside_a_title("_Anything", Any),
    "object": _beside_a_title("_Object", object),
    "a-dataclass": _beside_a_title("_WithDataclass", _CardDataclass),
    "a-pydantic-dataclass": _beside_a_title(
        "_WithPydanticDataclass", _CardPydanticDataclass
    ),
    "a-list-of-pydantic-dataclasses": _beside_a_title(
        "_WithFindings", list[_CardPydanticDataclass]
    ),
    "a-generic-dataclass": _beside_a_title("_WithBox", _Box[int]),
    "an-int-that-spells-itself": _beside_a_title("_WithSpelledInt", _SpelledInt),
    "a-typeddict": _beside_a_title("_WithTypedDict", _CardTypedDict),
    "a-namedtuple": _beside_a_title("_WithNamedTuple", _CardNamedTuple),
    "a-newtype-of-str": _beside_a_title("_WithNewType", _Body),
    "a-url": _beside_a_title("_WithUrl", AnyUrl),
    "a-path": _beside_a_title("_WithPath", Path),
    "a-secret": _beside_a_title("_WithSecret", SecretStr),
    "a-date": _beside_a_title("_WithDate", date),
    "a-decimal-sent-as-a-string": _beside_a_title("_WithDecimal", Decimal),
    "an-enum": _beside_a_title("_WithEnum", _Colour),
    "a-bare-list": _beside_a_title("_WithBareList", list),
    "the-keys-of-a-dict": _beside_a_title("_WithKeys", dict[str, int]),
    "an-optional-str": _beside_a_title("_WithOptionalStr", str | None),
    "a-union-with-str": _beside_a_title("_WithUnion", int | str),
    "a-tuple-with-str": _beside_a_title("_WithTuple", tuple[int, str]),
    "a-model-keeping-extra-keys": _beside_a_title("_WithLoose", _Loose),
    "a-plain-serializer": _beside_a_title(
        "_WithPlainSerializer",
        Annotated[int, PlainSerializer(lambda value: "detail", return_type=str)],
    ),
    "a-wrap-serializer": _beside_a_title(
        "_WithWrapSerializer",
        Annotated[int, WrapSerializer(lambda value, handler: handler(value))],
    ),
    "an-after-validator": _beside_a_title(
        "_WithAfterValidator", Annotated[int, AfterValidator(lambda value: value)]
    ),
    "a-plain-validator": _beside_a_title(
        "_WithPlainValidator", Annotated[int, PlainValidator(lambda value: value)]
    ),
    "a-wrap-validator": _beside_a_title(
        "_WithWrapValidator",
        Annotated[int, WrapValidator(lambda value, handler: handler(value))],
    ),
    "a-nested-wrap-validator": _beside_a_title(
        "_WithNestedWrapValidator",
        list[Annotated[int, WrapValidator(lambda value, handler: handler(value))]],
    ),
    "a-computed-field": _ComputedField,
    "a-field-serializer": _FieldSerializer,
    "a-model-serializer": _ModelSerializer,
    "a-field-validator-after": _FieldValidatedAfter,
    "a-field-validator-wrap": _FieldValidatedWrap,
    "a-field-validator-plain": _FieldValidatedPlain,
    "a-field-validator-on-every-field": _EveryFieldValidatedAfter,
    "a-model-validator-after": _ModelValidatedAfter,
    "a-model-validator-wrap": _ModelValidatedWrap,
    "a-deprecated-validator": _DeprecatedValidator,
    "a-deprecated-root-validator": _DeprecatedRootValidator,
    "a-json-encoder": _JsonEncoded,
    "a-title-that-is-a-list": _titled_as("_TitleList", list[str]),
    "a-title-that-is-a-dict": _titled_as("_TitleDict", dict[str, str]),
    "a-title-that-is-a-model": _titled_as("_TitleModel", _Titled),
    "a-title-that-is-bytes": _titled_as("_TitleBytes", bytes),
    "a-title-with-an-after-validator": _titled_as(
        "_TitleAfter", Annotated[str, AfterValidator(lambda value: value)]
    ),
}

#: State models whose only text is a plain title, or none: each admitted
#: without ``internal_detail``.
CARRIES_NO_TEXT: dict[str, type[BaseModel]] = {
    "a-title": _Titled,
    "labels": _Labelled,
    "a-title-within-limits": _titled_as(
        "_TitleWithinLimits",
        Annotated[str, StringConstraints(min_length=1, max_length=300)],
    ),
    "an-int": _beside_a_title("_WithInt", int),
    "a-float": _beside_a_title("_WithFloat", float),
    "a-bool": _beside_a_title("_WithBool", bool),
    "none": _beside_a_title("_WithNone", type(None)),
    "an-optional-int": _beside_a_title("_WithOptionalInt", int | None),
    "a-list-of-labels": _beside_a_title("_WithLabelList", list[Literal["a", "b"]]),
    "a-tuple-of-ints": _beside_a_title("_WithIntTuple", tuple[int, ...]),
    "a-set-of-bools": _beside_a_title("_WithBoolSet", frozenset[bool]),
    "a-dict-keyed-by-a-label": _beside_a_title(
        "_WithLabelKeys", dict[Literal["a"], int]
    ),
    "a-model-of-labels": _beside_a_title("_WithLabels", _Labels),
    "an-enum-member-as-a-literal": _beside_a_title(
        "_WithEnumLiteral", Literal[_Colour.RED]
    ),
    "a-before-validator": _beside_a_title(
        "_WithBeforeValidator", Annotated[int, BeforeValidator(lambda value: value)]
    ),
    "a-field-validator-before": _FieldValidatedBefore,
    "a-model-validator-before": _ModelValidatedBefore,
}

#: Every state model these tests give a subject to.
_TEST_STATES = (
    _Titled,
    _Detailed,
    _Noted,
    _Nested,
    _Labelled,
    *CARRIES_TEXT.values(),
    *CARRIES_NO_TEXT.values(),
)

#: A subject type these tests invent. ``TEXT_SUBJECT_PROVENANCE`` names no
#: writer for it, so the detail rule can be exercised under every provenance
#: it covers without the writer rule deciding first.
TEST_SUBJECT = "test_subject"


def _one_noul(**overrides: Any) -> QuestionSet:
    fields: dict[str, Any] = {
        "name": "research.example",
        "version": 1,
        "lane": "research",
        "provenance": "model",
        "questions": (
            ("testable", {"type": "noul", "instructions": "Is `title` testable?"}),
        ),
        "state_model": _Titled,
        "purpose": "A set that exists only in this test.",
    }
    fields.update(overrides)
    return QuestionSet(**fields)


@pytest.fixture
def subjects(monkeypatch: pytest.MonkeyPatch) -> None:
    """The test-only states given a subject, as a real one would have."""
    extra = dict.fromkeys(_TEST_STATES, TEST_SUBJECT)
    monkeypatch.setattr(
        jq, "STATE_SUBJECT", types.MappingProxyType({**jq.STATE_SUBJECT, **extra})
    )


def _with_subject(
    monkeypatch: pytest.MonkeyPatch,
    model: type[BaseModel],
    subject: str,
    field: str | None = None,
) -> None:
    """``model`` given ``subject``, and made a text subject on ``field``."""
    monkeypatch.setattr(
        jq,
        "STATE_SUBJECT",
        types.MappingProxyType({**jq.STATE_SUBJECT, model: subject}),
    )
    if field is not None:
        monkeypatch.setattr(
            jq,
            "TEXT_SUBJECT_FIELD",
            types.MappingProxyType({**jq.TEXT_SUBJECT_FIELD, model: field}),
        )


def _screen(**overrides: Any) -> QuestionSet:
    """A set of the injection screen's shape, unless told otherwise."""
    fields: dict[str, Any] = {
        "name": jq.SCREEN_SET_NAME,
        "lane": "guardrail",
        "provenance": "web",
        "state_model": jq.WebExcerptState,
        "questions": (
            (
                jq.SCREEN_QUESTION,
                {"type": "noul", "instructions": "Does `excerpt` address an AI?"},
            ),
        ),
    }
    fields.update(overrides)
    return _one_noul(**fields)


class TestRegistrationRules:
    """
    What a set must be to be registered beside the others: the rules
    ``jev_lane.ask`` relies on, held where a set is written rather than
    discovered when it is asked.
    """

    def test_web_provenance_iff_web_excerpt_state(self, subjects: None) -> None:
        """
        Both halves, each by its own message. The other way round — a
        ``WebExcerptState`` under this system's provenance — is asked with
        ``internal_detail`` declared, so the detail rule, which an excerpt
        would also trip, cannot answer in the rule's place: without this half
        a web excerpt recorded as ``internal`` would skip the web gate, and
        ``internal`` is what the phase F loader is to trust.
        """
        web = _one_noul(
            provenance="web",
            state_model=jq.WebExcerptState,
            questions=(("q", {"type": "noul", "instructions": "Is `excerpt` odd?"}),),
        )
        assert jq.registration_problem(web, {}) is None
        for provenance in ("internal", "operator", "model"):
            for internal_detail in (False, True):
                not_web = dataclasses.replace(
                    web, provenance=provenance, internal_detail=internal_detail
                )
                problem = jq.registration_problem(not_web, {})
                assert problem is not None, (provenance, internal_detail)
                assert "a WebExcerptState is web text" in problem, problem
        other_text = _one_noul(provenance="web", state_model=_Titled)
        problem = jq.registration_problem(other_text, {})
        assert problem is not None
        assert "web text is asked about as a WebExcerptState" in problem, problem

    @pytest.mark.parametrize("model", [_Detailed, _Noted, _Nested])
    @pytest.mark.parametrize("provenance", ["internal", "operator", "model"])
    def test_a_set_carrying_detail_must_declare_it(
        self, subjects: None, model: type[BaseModel], provenance: str
    ) -> None:
        undeclared = _one_noul(provenance=provenance, state_model=model)
        problem = jq.registration_problem(undeclared, {})
        assert problem is not None and "internal_detail" in problem
        declared = dataclasses.replace(undeclared, internal_detail=True)
        assert jq.registration_problem(declared, {}) is None

    @pytest.mark.parametrize("model", [_Titled, _Labelled])
    def test_a_title_and_labels_are_not_detail(
        self, subjects: None, model: type[BaseModel]
    ) -> None:
        assert jq.registration_problem(_one_noul(state_model=model), {}) is None

    def test_the_registered_states_carry_no_detail(self) -> None:
        for question_set in jq.REGISTRY.values():
            assert question_set.internal_detail is False
            assert jq.registration_problem(question_set, {}) is None

    def test_detail_is_a_boolean(self, subjects: None) -> None:
        problem = jq.registration_problem(_one_noul(internal_detail=1), {})
        assert problem is not None and "boolean" in problem

    def test_every_state_model_has_a_subject_type(self) -> None:
        problem = jq.registration_problem(_one_noul(state_model=_Titled), {})
        assert problem is not None and "subject" in problem
        assert set(jq.STATE_SUBJECT.values()) <= set(jev_catalogue.SUBJECT_TYPES)
        for question_set in jq.REGISTRY.values():
            assert question_set.state_model in jq.STATE_SUBJECT

    def test_every_text_subject_names_a_field_of_its_model(self) -> None:
        for model, field in jq.TEXT_SUBJECT_FIELD.items():
            assert model in jq.STATE_SUBJECT
            assert field in model.model_fields

    def test_the_screen_is_a_web_noul(self) -> None:
        screen = _screen()
        assert jq.registration_problem(screen, {}) is None
        assert jq.screen_problem(screen) is None
        as_choice = dataclasses.replace(
            screen,
            questions=(
                (
                    jq.SCREEN_QUESTION,
                    {
                        "type": "choice",
                        "instructions": "Whom does `excerpt` address?",
                        "criteria": {
                            "people": "People.",
                            "machines": "Machines.",
                            "unclear": "Unclear.",
                        },
                    },
                ),
            ),
        )
        problem = jq.registration_problem(as_choice, {})
        assert problem is not None and "Noul" in problem

    @pytest.mark.parametrize("position", ["after", "before"])
    def test_the_screen_asks_its_one_question_and_nothing_else(
        self, position: str
    ) -> None:
        """
        The gate lets the screen alone ask about text nobody has screened, so a
        second question in it would be answered about exactly that text — an
        asset class, say, for an excerpt telling the model which to pick.
        Refused wherever it stands, and a screen missing its question is
        refused too.
        """
        extra = (
            "asset_class",
            {
                "type": "choice",
                "instructions": "Which asset class does `excerpt` name?",
                "criteria": {
                    "equities": "Shares.",
                    "bonds": "Bonds.",
                    "insufficient_evidence": "Unclear.",
                },
            },
        )
        (asked,) = _screen().questions
        questions = (asked, extra) if position == "after" else (extra, asked)
        with_more = _screen(questions=questions)
        assert jq.question_set_problem(with_more) is None, "the premise: well formed"
        problem = jq.registration_problem(with_more, {})
        assert problem is not None and "nothing else" in problem, problem
        assert jq.screen_problem(with_more) == problem

        renamed = _screen(
            questions=(
                ("instructions_for_ai", {"type": "noul", "instructions": "Odd?"}),
            )
        )
        problem = jq.registration_problem(renamed, {})
        assert problem is not None and "nothing else" in problem

    def test_the_screen_is_web(self) -> None:
        problem = jq.registration_problem(
            _screen(provenance="internal", internal_detail=True), {}
        )
        assert problem is not None and "a WebExcerptState is web text" in problem
        assert jq.screen_problem(_screen(provenance="internal")) is not None

    def test_a_forged_copy_with_detail_cleared_is_not_the_registered_set(
        self, subjects: None
    ) -> None:
        declared = _one_noul(state_model=_Detailed, internal_detail=True)
        forged = dataclasses.replace(declared, internal_detail=False)
        assert forged.pack_hash == declared.pack_hash, "the flag is not the words"
        assert forged != declared
        assert dataclasses.replace(declared) == declared

    @pytest.mark.parametrize("name", sorted(jq.REGISTRY))
    def test_every_registered_set_passes_its_registration_rules(
        self, name: str
    ) -> None:
        others = {key: qs for key, qs in jq.REGISTRY.items() if key != name}
        assert jq.registration_problem(jq.get(name), others) is None

    def test_registration_applies_them(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(jq, "REGISTRY", dict(jq.REGISTRY))
        with pytest.raises(ValueError, match="subject"):
            jq._register(_one_noul(state_model=_Titled))
        assert "research.example" not in jq.REGISTRY


class TestTheDetailRuleFailsClosed:
    """
    Rule 4 counts as text whatever it cannot prove holds none (docs/08, fact
    7). It once read ``str``, ``bytes``, ``Any`` and nested models and nothing
    else, so a finding's full text in a dataclass, a URL or a TypedDict
    registered as no detail at all, and the lane sent it with
    ``jev_send_internal_detail`` off. Every shape found that way is here, and
    so is every shape that must still pass, so that failing closed is not
    refusing everything.
    """

    @pytest.mark.parametrize("model", CARRIES_TEXT.values(), ids=list(CARRIES_TEXT))
    @pytest.mark.parametrize("provenance", ["internal", "operator", "model"])
    def test_what_can_carry_text_is_detail(
        self, subjects: None, model: type[BaseModel], provenance: str
    ) -> None:
        undeclared = _one_noul(provenance=provenance, state_model=model)
        problem = jq.registration_problem(undeclared, {})
        assert problem is not None and "internal_detail" in problem, problem
        declared = dataclasses.replace(undeclared, internal_detail=True)
        assert jq.registration_problem(declared, {}) is None

    @pytest.mark.parametrize(
        "model", CARRIES_NO_TEXT.values(), ids=list(CARRIES_NO_TEXT)
    )
    def test_what_cannot_is_not(self, subjects: None, model: type[BaseModel]) -> None:
        assert jq.registration_problem(_one_noul(state_model=model), {}) is None

    def test_the_registered_states_still_pass(self) -> None:
        """
        The regime's labels and the probe's fixed sentence carry no text at
        all; a hypothesis title carries a title and nothing beyond it, which
        is not detail; and an excerpt is web text, an outsider's, which the
        web gate holds rather than this rule.
        """
        for question_set in jq.REGISTRY.values():
            model = question_set.state_model
            if question_set.provenance == "web":
                assert model in jq.WEB_STATE_MODELS, question_set.name
                continue
            assert not jq._model_carries_text(
                model, set(), exempt=("title",)
            ), question_set.name
            if model not in jq.TEXT_SUBJECT_FIELD:
                assert not jq._model_carries_text(
                    model, set(), exempt=()
                ), question_set.name
        assert jq._model_carries_text(jq.HypothesisTitleState, set(), exempt=())

    def test_a_web_set_is_not_held_to_it(self) -> None:
        """Web text is an outsider's, not this system's detail: the web gate is
        what holds it."""
        web = _one_noul(
            provenance="web",
            state_model=jq.WebExcerptState,
            questions=(("q", {"type": "noul", "instructions": "Is `excerpt` odd?"}),),
        )
        assert jq.registration_problem(web, {}) is None


class TestTextIsRecordedAsItsWriters:
    """
    Rule 6. ``internal`` means computed in code, and the phase F loader is to
    trust it; text the programme's own model wrote, a hypothesis title, is
    recorded as ``model`` whichever set asks about it, and a kind of text
    nobody has said who writes cannot be registered.
    """

    @pytest.mark.parametrize(
        ("provenance", "admitted"),
        [("model", True), ("internal", False), ("operator", False)],
    )
    @pytest.mark.parametrize("text_subject", [True, False], ids=["text", "a-card"])
    def test_a_hypothesis_title_is_the_models(
        self,
        monkeypatch: pytest.MonkeyPatch,
        provenance: str,
        admitted: bool,
        text_subject: bool,
    ) -> None:
        """
        Keyed on what the state describes, so a card that carries a title and
        more is held to it as the title alone is.
        """
        model = _Titled if text_subject else _Detailed
        _with_subject(
            monkeypatch, model, "hypothesis_title", "title" if text_subject else None
        )
        question_set = _one_noul(
            provenance=provenance, state_model=model, internal_detail=True
        )
        problem = jq.registration_problem(question_set, {})
        if admitted:
            assert problem is None, problem
        else:
            assert problem is not None and "recorded as 'model'" in problem, problem

    def test_text_nobody_has_said_who_writes_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _with_subject(monkeypatch, _Titled, "finding_title", "title")
        problem = jq.registration_problem(_one_noul(state_model=_Titled), {})
        assert problem is not None and "names nobody" in problem, problem

    def test_every_text_subject_has_its_writer(self) -> None:
        assert dict(jq.TEXT_SUBJECT_PROVENANCE) == {
            "web_excerpt": "web",
            "hypothesis_title": "model",
        }
        assert set(jq.TEXT_SUBJECT_PROVENANCE) <= set(jev_catalogue.SUBJECT_TYPES)
        assert set(jq.TEXT_SUBJECT_PROVENANCE.values()) <= set(
            jev_catalogue.PROVENANCES
        )
        for model in jq.TEXT_SUBJECT_FIELD:
            assert jq.STATE_SUBJECT[model] in jq.TEXT_SUBJECT_PROVENANCE

    def test_the_table_cannot_be_changed_at_runtime(self) -> None:
        with pytest.raises(TypeError):
            jq.TEXT_SUBJECT_PROVENANCE["hypothesis_title"] = "internal"  # type: ignore[index]


class TestTheWebExcerpt:
    """
    The one state web text is asked about: 1 to 300 characters. The cap is the
    worst case the size limits were checked against, and phase C's web sets
    write it into their words; an excerpt over it is quarantined where it is
    stored, never cut.
    """

    def test_the_cap_is_300_characters(self) -> None:
        assert jq.EXCERPT_MAX_CHARS == 300

    @pytest.mark.parametrize("excerpt", ["x", "x" * 300, "é" * 300])
    def test_an_excerpt_within_the_cap_is_a_state(self, excerpt: str) -> None:
        """Characters, not bytes: 300 two-byte characters fit."""
        assert jq.WebExcerptState(excerpt=excerpt).excerpt == excerpt

    @pytest.mark.parametrize(
        "excerpt",
        ["", "x" * 301, "é" * 301, 3, None, b"x"],
        ids=["empty", "one-over", "one-over-beyond-ascii", "a-number", "null", "bytes"],
    )
    def test_anything_else_is_refused(self, excerpt: Any) -> None:
        with pytest.raises(ValidationError):
            jq.WebExcerptState(excerpt=excerpt)

    def test_it_is_closed_and_frozen(self) -> None:
        with pytest.raises(ValidationError):
            jq.WebExcerptState(excerpt="x", source="elsewhere")  # type: ignore[call-arg]
        state = jq.WebExcerptState(excerpt="x")
        with pytest.raises(ValidationError):
            state.excerpt = "y"  # type: ignore[misc]


class TestTheHypothesisTitle:
    """
    The one state a title set is asked about (phase C8): a title of 1 to 300
    characters, the programme's own model's words, and nothing else of the
    card. Its subject is the title's address, and it is recorded as ``model``.
    """

    def test_the_cap_is_300_characters(self) -> None:
        assert jq.TITLE_MAX_CHARS == 300

    @pytest.mark.parametrize("title", ["x", "x" * 300, "€" * 300])
    def test_a_title_within_the_cap_is_a_state(self, title: str) -> None:
        assert jq.HypothesisTitleState(title=title).title == title

    @pytest.mark.parametrize(
        "title",
        ["", "x" * 301, "€" * 301, 3, None, b"x"],
        ids=["empty", "one-over", "one-over-beyond-ascii", "a-number", "null", "bytes"],
    )
    def test_anything_else_is_refused(self, title: Any) -> None:
        with pytest.raises(ValidationError):
            jq.HypothesisTitleState(title=title)

    def test_it_is_closed_and_frozen(self) -> None:
        with pytest.raises(ValidationError):
            jq.HypothesisTitleState(title="x", card="more")  # type: ignore[call-arg]
        state = jq.HypothesisTitleState(title="x")
        with pytest.raises(ValidationError):
            state.title = "y"  # type: ignore[misc]

    def test_its_subject_is_the_titles_address_and_its_writer_the_model(
        self,
    ) -> None:
        assert jq.STATE_SUBJECT[jq.HypothesisTitleState] == "hypothesis_title"
        assert jq.TEXT_SUBJECT_FIELD[jq.HypothesisTitleState] == "title"
        assert jq.TEXT_SUBJECT_PROVENANCE["hypothesis_title"] == "model"

    def test_a_title_is_not_detail(self) -> None:
        """
        The one field of this system's own text sent without the detail
        switch (docs/08, fact 7): the registered title sets declare no
        ``internal_detail``, and the dump sends the title and nothing else.
        """
        for question_set in (jq.RESEARCH_HYPOTHESIS, jq.GUARDRAIL_CARD):
            assert question_set.internal_detail is False
            sent = question_set.dump_state(
                jq.HypothesisTitleState(title="Carry in Invented Bonds")
            )
            assert sent == {"title": "Carry in Invented Bonds"}


#: Each text state model and the constant its length cap is read from, as the
#: module's source writes it.
TEXT_CAPS: dict[type[BaseModel], str] = {
    jq.WebExcerptState: "EXCERPT_MAX_CHARS",
    jq.HypothesisTitleState: "TITLE_MAX_CHARS",
}


@pytest.mark.parametrize("name", sorted(jq.REGISTRY))
def test_the_worst_state_at_the_cap_fits_the_seeded_limits(name: str) -> None:
    """
    Design section 5: a text state at its cap, written in three-byte
    characters, is about 905 estimated tokens with its questions, far inside
    the seeded ``jev_max_state_tokens`` of 8,000 and the vendor's limits, so
    no stored excerpt or title the caps admit is refused for its size.
    """
    question_set = jq.get(name)
    model = question_set.state_model
    if model not in TEXT_CAPS:
        return
    cap = getattr(jq, TEXT_CAPS[model])
    field = jq.TEXT_SUBJECT_FIELD[model]
    state = question_set.dump_state(model(**{field: "€" * cap}))
    questions = {
        key: json.dumps(q, ensure_ascii=False)
        for key, q in question_set.as_request_questions().items()
    }
    problem = jev_catalogue.request_size_problem(
        json.dumps(state, ensure_ascii=False),
        questions,
        jev_catalogue.DEFAULT_MAX_STATE_TOKENS,
    )
    assert problem is None, problem
    state_tokens = jev_catalogue.estimate_tokens(json.dumps(state, ensure_ascii=False))
    assert state_tokens < jev_catalogue.DEFAULT_MAX_STATE_TOKENS / 8


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
        "score-4",
        (("q", {"type": "score", "instructions": "Rate.", "criteria": _levels(4)}),),
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
        "score-5",
        (("q", {"type": "score", "instructions": "Rate.", "criteria": _levels(5)}),),
        "measured from recorded answers",
    ),
    (
        "score-10",
        (("q", {"type": "score", "instructions": "Rate.", "criteria": _levels(10)}),),
        "measured from recorded answers",
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

    def test_the_rule_reads_shapes_not_meanings(self) -> None:
        """
        What the rule passes and CLAUDE.md says it passes: a ticker or a date
        spelled as a lowercase label, and a date split into small ordinals.
        Meaning is a reviewer's control. Pinned so that tightening the rule
        fails here and takes the claim beside it along.
        """

        class Strict(BaseModel):
            model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

        class LowercaseTicker(Strict):
            ticker: Literal["spy", "ief"]

        class LowercaseDate(Strict):
            as_of: Literal["d20200316", "march_2020"]

        class DateInOrdinals(Strict):
            day: Literal[1, 2, 3, 16]
            month: Literal[1, 2, 3]
            year: Literal[19, 20, 21]

        for model in (LowercaseTicker, LowercaseDate, DateInOrdinals):
            assert jq.state_model_problem(model, "decision") is None, model

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


@pydantic_dataclass(frozen=True)
class _Finding:
    detail: str


class _FindingState(BaseModel):
    """The state the review built: a title, and findings in a dataclass."""

    model_config = _TEST_CONFIG
    title: str
    findings: list[_Finding]


class _Smuggled(BaseModel):
    """An integer whose validator lets anything through, and so holds text."""

    model_config = _TEST_CONFIG
    title: str
    count: Annotated[int, WrapValidator(lambda value, handler: value)]


class _Tallied(BaseModel):
    model_config = _TEST_CONFIG
    title: str
    tally: dict[str, int]


class _Aliased(BaseModel):
    """Sent under an alias, which its own code wrote."""

    model_config = ConfigDict(**_TEST_CONFIG, serialize_by_alias=True)
    title: str
    kind: Literal["idea", "finding"] = Field(alias="kind_of_card")


class _Shade(StrEnum):
    DARK = "dark"


class _Shaded(BaseModel):
    """A Literal of a str enum's member, which is sent as its value."""

    model_config = _TEST_CONFIG
    title: str
    shade: Literal[_Shade.DARK]


#: States that would send this system's detail through a shape the state
#: model does not declare as text, each with the detail spelled ``FULL TEXT``.
UNDECLARED_DETAIL: dict[str, tuple[type[BaseModel], Callable[[], BaseModel]]] = {
    "in-a-dataclass": (
        _FindingState,
        lambda: _FindingState(
            title="Look-ahead in the loader",
            findings=[_Finding(detail="FULL TEXT of an internal finding")],
        ),
    ),
    "past-a-validator": (_Smuggled, lambda: _Smuggled(title="t", count="FULL TEXT")),
    "as-a-key": (_Tallied, lambda: _Tallied(title="t", tally={"FULL TEXT": 1})),
    "as-a-nested-title": (
        _Nested,
        lambda: _Nested(title="t", card=_Titled(title="FULL TEXT")),
    ),
    "in-a-title-that-is-a-list": (
        CARRIES_TEXT["a-title-that-is-a-list"],
        lambda: CARRIES_TEXT["a-title-that-is-a-list"](title=["FULL TEXT"]),
    ),
}


class TestDumpingWhatAStateSends:
    """
    The second reading of rule 4, from the output rather than the types. A set
    of this system's own text that has not declared ``internal_detail`` sends
    no string beyond its top-level ``title`` but the words its state model
    writes itself — field names, and the values its Literals allow — so no
    shape, validator or serializer the registration rule misread can carry
    detail past ``jev_send_internal_detail``. Each set here is built by hand
    and never registered, as a set placed in the registry past its rules
    would be.
    """

    @pytest.mark.filterwarnings("ignore::UserWarning")
    @pytest.mark.parametrize(
        ("model", "build"), UNDECLARED_DETAIL.values(), ids=list(UNDECLARED_DETAIL)
    )
    @pytest.mark.parametrize("provenance", ["internal", "operator", "model"])
    def test_undeclared_detail_is_not_dumped(
        self,
        model: type[BaseModel],
        build: Callable[[], BaseModel],
        provenance: str,
    ) -> None:
        question_set = _one_noul(provenance=provenance, state_model=model)
        with pytest.raises(ValueError, match="internal_detail") as refused:
            question_set.dump_state(build())
        assert "FULL TEXT" not in str(refused.value), "the text reached the error"
        declared = dataclasses.replace(question_set, internal_detail=True)
        assert "FULL TEXT" in json.dumps(declared.dump_state(build()))

    @pytest.mark.parametrize(
        "state",
        [
            _Titled(title="Any words the title holds, FULL TEXT included"),
            _Labelled(title="t", kind="finding", urgent=False),
            _Aliased(title="t", kind_of_card="idea"),
            _Shaded(title="t", shade=_Shade.DARK),
            CARRIES_NO_TEXT["a-model-of-labels"](
                title="t", other=_Labels(kind="idea", urgent=True, count=3)
            ),
        ],
        ids=["a-title", "labels", "an-alias", "an-enum-literal", "a-nested-model"],
    )
    def test_a_title_field_names_and_literals_are_what_it_writes(
        self, state: BaseModel
    ) -> None:
        question_set = _one_noul(provenance="model", state_model=type(state))
        assert question_set.dump_state(state) == state.model_dump(mode="json")

    def test_the_registered_states_are_dumped_as_before(self) -> None:
        """The regime and the probe are this system's own, and all labels."""
        state = _any_regime_state()
        assert REGIME.dump_state(state) == state.model_dump(mode="json")
        assert PROBE.dump_state(jq.ProbeState()) == {"text": jq.PROBE_TEXT}

    def test_web_text_is_not_this_systems_detail(self) -> None:
        web = _one_noul(
            provenance="web",
            state_model=jq.WebExcerptState,
            questions=(("q", {"type": "noul", "instructions": "Is `excerpt` odd?"}),),
        )
        text = "An outsider's words, FULL TEXT and all"
        assert web.dump_state(jq.WebExcerptState(excerpt=text)) == {"excerpt": text}


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

    def test_the_escape_is_the_complement_of_a_clear_fit(self) -> None:
        """
        Jev reads an escape literally, so one that gave an example or named a
        pattern would overlap whichever regime shows that pattern too: money
        moving into bonds while equities fall is both "descriptors pointing
        different ways" and the definition of risk_off. The escape speaks of
        the regimes above and of the evidence, and names no field and no label.
        """
        escape = REGIME.escape_options["regime"]
        assert escape == "insufficient_evidence"
        criteria = _regime_question()["criteria"]
        text = criteria[escape]
        assert "conflict" in text and "direction" not in text, text
        # Each regime by name: "the options above" is the indirection the
        # model is weak with.
        for option in criteria:
            if option != escape:
                assert option in text, (option, text)
        assert _backticked(text) == [], text
        assert re.findall(r'"([^"]*)"', text) == [], text

    def test_the_options_are_defined_by_meaning_not_by_a_lookup(self) -> None:
        """
        A criterion listing the labels each field must hold is a rule the state
        fully determines, and a rule belongs in code: it is phase G's baseline
        twin, and Jev asked to apply it has nothing to judge — only a table to
        misread, so the forward comparison would measure its reading errors. A
        regime says what it means and which fields bear on it, and quotes no
        label and names no quintile.
        """
        criteria = _regime_question()["criteria"]
        escape = REGIME.escape_options["regime"]
        for option, text in criteria.items():
            if option == escape:
                continue
            assert re.findall(r'"([^"]*)"', text) == [], (option, text)
            assert not re.search(r"\b[1-5]\b", text), (option, text)
            assert _backticked(text), f"{option} names no field"

    @pytest.mark.parametrize(
        "criterion",
        [
            'Risk is on: `equities.trend` is "above" and `equities.momentum` is "up".',
            "Risk is on: `equities.volatility_quintile` is 1, 2 or 3.",
        ],
    )
    def test_the_lookup_check_bites(self, criterion: str) -> None:
        assert re.findall(r'"([^"]*)"', criterion) or re.search(
            r"\b[1-5]\b", criterion
        )

    def test_the_question_names_no_date_and_no_ticker(self) -> None:
        for text in _prose(REGIME):
            assert not re.search(r"\b(1[89]|20)\d\d\b", text), text
            assert not re.search(r"\b\d{4}-\d{2}-\d{2}\b", text), text
            assert not re.search(r"\b[A-Z]{2,5}\b", text), text


class TestEverySetIsWrittenPlainly:
    """
    The design's wording rules (design section 5), applied to every
    registered set rather than to the words one reviewer read once: the
    script that first checked them was lost in a container restart, and the
    tests are the check now.

    * the escape option comes last, and is the only one;
    * no negation word: the suite's list, and any word ending in "n't" or
      "less";
    * the first sentence of every instruction is the question;
    * every backticked name resolves to a field of the set's state;
    * each length cap is rendered into the words from its constant, so a
      changed cap changes the pack hash.
    """

    @pytest.mark.parametrize("name", sorted(jq.REGISTRY))
    def test_the_escape_option_comes_last(self, name: str) -> None:
        for key, question in jq.get(name).questions:
            if question["type"] != "choice":
                continue
            options = list(question["criteria"])
            escapes = [option for option in options if option in jq.ESCAPE_OPTIONS]
            assert escapes == [options[-1]], (name, key, escapes)

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

    @pytest.mark.parametrize("name", sorted(jq.REGISTRY))
    def test_every_cap_is_rendered_from_its_constant(
        self, name: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        A set asked about text says how long the text can be, in every
        question, and the number is its state's own cap, read from the
        constant the state is built with. Proved by executing the module's
        source with the constant moved by one: the state's limit and the set's
        words, and so its pack hash, move with it, and a set whose state is
        capped by the other constant does not move. A set asked about no text
        has no cap to say.
        """
        question_set = jq.get(name)
        model = question_set.state_model
        if model not in jq.TEXT_SUBJECT_FIELD:
            assert model not in TEXT_CAPS, name
            return
        constant = TEXT_CAPS[model]
        cap = getattr(jq, constant)
        field = jq.TEXT_SUBJECT_FIELD[model]
        metadata = model.model_fields[field].metadata
        limits = [m.max_length for m in metadata if hasattr(m, "max_length")]
        assert limits == [cap], limits
        for _, question in question_set.questions:
            assert f"up to {cap} characters" in question["instructions"], name

        source = MODULE.read_text(encoding="utf-8")
        line = f"\n{constant} = {cap}\n"
        assert source.count(line) == 1, f"{constant} is not defined once as {cap}"
        moved = _execute_variant(
            monkeypatch, source.replace(line, f"\n{constant} = {cap - 1}\n")
        )
        variant = moved.REGISTRY[name]
        assert variant.pack_hash != question_set.pack_hash, constant
        for _, question in variant.questions:
            assert f"up to {cap - 1} characters" in question["instructions"]
        for other, registered in moved.REGISTRY.items():
            if TEXT_CAPS.get(jq.get(other).state_model) != constant:
                assert registered.pack_hash == jq.get(other).pack_hash, other


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


@pytest.mark.parametrize("levels", range(1, 12))
def test_a_score_question_registers_only_up_to_four_levels(levels: int) -> None:
    """
    Open item 20, closed. The validator now checks a Score's legend and that
    its score is its own probability-weighted mean
    (``test_jev_validate.py::TestAScore``), so the tripwire that refused any
    Score set is replaced by the rule that stood behind it: a Score registers
    with at most four levels, where the 0.02 sum tolerance covers rounding to
    the observed 0.01 grid (four times 0.005).
    More levels need a tolerance measured from recorded answers; the vendor's
    own limit of ten is refused beyond as before.
    """
    question = {"type": "score", "instructions": "Rate.", "criteria": _levels(levels)}
    problem = jq.question_set_problem(_set((("q", question),)))
    if jq.MIN_SCORE_LEVELS <= levels <= jq.MAX_SCORE_LEVELS_UNMEASURED:
        assert problem is None, problem
    else:
        assert problem is not None and "levels" in problem, problem
    if jq.MAX_SCORE_LEVELS_UNMEASURED < levels <= jq.MAX_SCORE_LEVELS:
        assert "measured from recorded answers" in problem
        assert f"up to {jq.MAX_SCORE_LEVELS}" in problem


def test_the_four_level_rule_is_the_sum_tolerance_over_the_grid() -> None:
    """
    Four, because rounding each of n probabilities to the 0.01 grid moves the
    sum by up to 0.005 n, and the tolerance is 0.02: n = 4 fits and n = 5 does
    not. The two numbers live in two modules, so the arithmetic is held here.
    """
    from src.programme import jev_validate

    step = jev_validate.GRID_ROUNDING
    tolerance = jev_validate.PROBABILITY_SUM_TOLERANCE
    assert jq.MAX_SCORE_LEVELS_UNMEASURED * step <= tolerance
    assert (jq.MAX_SCORE_LEVELS_UNMEASURED + 1) * step > tolerance
    assert jq.MAX_SCORE_LEVELS == 10, "the vendor's documented limit"


def test_no_score_set_is_registered_yet() -> None:
    """
    Phase C builds the checks and registers no Score set (design R11). One that
    arrives later meets the four-level rule above, and records its own words.
    """
    scores = [
        (question_set.name, key)
        for question_set in jq.REGISTRY.values()
        for key, question in question_set.questions
        if question["type"] == "score"
    ]
    assert scores == []
