"""
test_jev_validate.py
--------------------
Whether what Jev sent back answers what was asked, and what each answer
measured.

``src/programme/jev_validate.py`` is pure, so every rule is a unit test, most of
them tables. The failures worth guarding against are the silent ones, and every
one of them fails by *accepting* something:

* text Python's json reads and JSON forbids — ``NaN``, ``Infinity``, a name
  given twice — must be refused, not read;
* ``True`` is not 1. A boolean where a probability belongs is a malformed
  answer, and Python's ``True == 1`` would otherwise make it a certainty;
* the argmax is recomputed, and a ``choice`` that is not it (SDK issue #15) is
  an abstention, not an answer;
* an answer that fails is recorded with its reason and read as not measured —
  never as 0 — and a response that fails whole is not canonical;
* answers come back one per question asked, in the order asked;
* nothing raises on any input, because the lane has a billed call to record
  whatever came back. A seeded random corpus proves it, and proves every
  verdict follows the rules, by a check written apart from the module.

Every validation any test here produces is also held to what migration 0012's
``jev_answers`` constraints and column types would refuse
(:func:`_assert_fits_the_ledger`), so a rule broken in the validator is caught
here, without Postgres, before the integration suite's round trip through the
real schema (``tests/integration/test_jev_repo.py``,
``TestTheValidatorsAnswersFitTheLedger``).
"""

from __future__ import annotations

import copy
import dataclasses
import decimal
import functools
import itertools
import json
import math
import random
import re
from collections.abc import Iterator, Mapping
from decimal import Decimal
from typing import Any

import pytest

from src.programme import jev_catalogue, jev_questions, jev_repo, jev_validate
from src.programme.jev_validate import (
    ANSWER_REASONS,
    MAX_TOKEN_COUNT,
    QUESTION_TYPES,
    REASONS,
    RESPONSE_REASONS,
    ValidatedAnswer,
    Validation,
    validate_body,
)

MODEL = jev_catalogue.DEFAULT_MODEL

OPTIONS = ("risk_on", "neutral", "risk_off", "insufficient_evidence")
LEVELS = ("calm", "unusual", "extreme")

#: One question of each type, in an order no sort would produce.
ASKED: dict[str, dict] = {
    "regime": {
        "type": "choice",
        "instructions": "Which regime do the descriptors show?",
        "criteria": {option: f"The {option} regime." for option in OPTIONS},
    },
    "in_scope": {
        "type": "noul",
        "instructions": "Do the descriptors describe a listed market?",
    },
    "severity": {
        "type": "score",
        "instructions": "How far from normal are the descriptors?",
        "criteria": list(LEVELS),
    },
}

#: What the vendor answers to ``ASKED``, cleanly, in the wire shapes the SDK's
#: generated schema documents.
CHOICE = {
    "type": "choice",
    "choice": "risk_on",
    "confidence": 0.49,
    "probabilities": {
        "risk_on": 0.62,
        "neutral": 0.21,
        "risk_off": 0.12,
        "insufficient_evidence": 0.05,
    },
}
NOUL = {"type": "noul", "noul": 0.83}
SCORE = {
    "type": "score",
    "score": 0.4,
    "confidence": 0.55,
    "legend": {"0": "calm", "1": "unusual", "2": "extreme"},
    "probabilities": {"0": 0.7, "1": 0.2, "2": 0.1},
}
CLEAN = {"regime": CHOICE, "in_scope": NOUL, "severity": SCORE}
USAGE = {"input_tokens": 212, "output_tokens": 0}

#: A field given this is removed rather than set.
DROP = object()

#: A value no body would carry, replaced in the JSON text by a spelling the
#: encoder would never produce.
SLOT = "\x01slot\x01"

VALUE_FIELDS = ("noul", "choice", "score", "probabilities", "confidence")

#: The reasons an answer of each type can carry, and no others.
REASONS_BY_TYPE: dict[str, set[str]] = {
    "noul": {"missing", "type_mismatch", "noul_invalid", "tie"},
    "choice": {
        "missing",
        "type_mismatch",
        "probability_keys",
        "probability_invalid",
        "probability_sum",
        "choice_not_in_criteria",
        "confidence_invalid",
        "tie",
        "choice_not_argmax",
    },
    "score": {
        "missing",
        "type_mismatch",
        "probability_keys",
        "probability_invalid",
        "probability_sum",
        "score_invalid",
        "confidence_invalid",
        "tie",
    },
}


# ---------------------------------------------------------------------------
# Building bodies
# ---------------------------------------------------------------------------


def _body(answers: Any = CLEAN, **top: Any) -> dict[str, Any]:
    """
    A clean response to ``ASKED``. ``answers`` replaces its answers, and each
    of ``top`` a top-level field; ``DROP`` removes either.
    """
    body: dict[str, Any] = {
        "model": MODEL,
        "answers": copy.deepcopy(answers),
        "usage": dict(USAGE),
    }
    if answers is DROP:
        del body["answers"]
    for name, value in top.items():
        if value is DROP:
            body.pop(name, None)
        else:
            body[name] = copy.deepcopy(value)
    return body


def _with(answer: dict[str, Any], **fields: Any) -> dict[str, Any]:
    """``answer`` with ``fields`` replaced; ``DROP`` removes one."""
    changed = copy.deepcopy(answer)
    for name, value in fields.items():
        if value is DROP:
            changed.pop(name, None)
        else:
            changed[name] = copy.deepcopy(value)
    return changed


def _spelled(path: tuple[str, ...], token: str, body: Any = None) -> str:
    """
    A body's JSON text with the value at ``path`` written exactly as ``token``,
    for spellings ``json.dumps`` will not produce: ``1e999``, ``NaN``, a
    5000-digit integer.
    """
    tree = copy.deepcopy(_body() if body is None else body)
    container = tree
    for step in path[:-1]:
        container = container[step]
    container[path[-1]] = SLOT
    text = json.dumps(tree, allow_nan=False)
    slot = json.dumps(SLOT)
    assert text.count(slot) == 1
    return text.replace(slot, token)


def _judge(body: Any, asked: Any = ASKED, pin: Any = MODEL) -> Validation:
    """Validate ``body``, as a dict dumped to text or as given, and check the
    result fits the ledger."""
    raw = json.dumps(body, allow_nan=False) if isinstance(body, dict) else body
    validation = validate_body(raw, asked, pin)
    _assert_fits_the_ledger(validation)
    return validation


def _by_key(validation: Validation) -> dict[str, ValidatedAnswer]:
    return {answer.question_key: answer for answer in validation.answers}


def _one(key: str, answer: Any) -> ValidatedAnswer:
    """``answer`` judged as the answer to ``key``, the rest of the body clean."""
    answers = copy.deepcopy(CLEAN)
    answers[key] = answer
    validation = _judge(_body(answers))
    assert validation.status == "ok", validation.problem
    return _by_key(validation)[key]


def _one_spelled(key: str, field: tuple[str, ...], token: str) -> ValidatedAnswer:
    validation = _judge(_spelled(("answers", key, *field), token))
    assert validation.status == "ok", validation.problem
    return _by_key(validation)[key]


def _carried(answer: ValidatedAnswer) -> dict[str, Any]:
    """Every value field an answer holds that is not ``None``."""
    names = (*VALUE_FIELDS, "argmax", "margin")
    return {
        name: getattr(answer, name)
        for name in names
        if getattr(answer, name) is not None
    }


def _spread(keys: list[str]) -> dict[str, float]:
    """A distribution over ``keys`` on a 0.01 grid summing to 1, first on top."""
    rest = Decimal(40 // (len(keys) - 1)) / 100
    top = 1 - rest * (len(keys) - 1)
    return {key: float(top if i == 0 else rest) for i, key in enumerate(keys)}


def _clean_body(asked: Mapping[str, dict]) -> dict[str, Any]:
    """A clean response to any well-formed ``asked``."""
    answers: dict[str, Any] = {}
    for key, question in asked.items():
        if question["type"] == "noul":
            answers[key] = dict(NOUL)
            continue
        if question["type"] == "choice":
            options = list(question["criteria"])
            answers[key] = {
                "type": "choice",
                "choice": options[0],
                "confidence": 0.5,
                "probabilities": _spread(options),
            }
            continue
        levels = [str(level) for level in range(len(question["criteria"]))]
        probabilities = _spread(levels)
        answers[key] = {
            "type": "score",
            "score": float(
                sum(Decimal(repr(p)) * int(k) for k, p in probabilities.items())
            ),
            "confidence": 0.5,
            "legend": dict(zip(levels, question["criteria"], strict=True)),
            "probabilities": probabilities,
        }
    return {"model": MODEL, "answers": answers, "usage": dict(USAGE)}


# ---------------------------------------------------------------------------
# What the ledger would refuse, checked without it
# ---------------------------------------------------------------------------


def _storable(text: object) -> bool:
    """Text Postgres can hold in ``text`` or ``jsonb``: no NUL, valid UTF-8."""
    if not isinstance(text, str) or "\x00" in text:
        return False
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _finite_float(value: object) -> bool:
    return type(value) is float and math.isfinite(value)


def _assert_fits_the_ledger(validation: Validation) -> None:
    """
    Each CHECK on ``jev_answers`` in migration 0012, each column type the
    writer feeds, and the shape ``Validation`` promises, on one validation.
    """
    assert type(validation) is Validation
    assert validation.status in ("ok", "invalid")
    assert validation.model_answered is None or _storable(validation.model_answered)
    for count in (validation.input_tokens, validation.output_tokens):
        assert count is None or (type(count) is int and 0 <= count <= 2**31 - 1)
    assert isinstance(validation.answers, tuple)
    if validation.status == "invalid":
        # Refused whole: the note says why, and every answer carries it.
        assert validation.problem, validation
        code = validation.problem.split(":", 1)[0]
        assert code in RESPONSE_REASONS, validation.problem
        assert all(a.invalid_reason == code for a in validation.answers)
    else:
        # A canonical row with no answers is one the replay could never use.
        assert validation.answers
        assert not {a.invalid_reason for a in validation.answers} & set(
            RESPONSE_REASONS
        )
        assert validation.problem is None or validation.problem.strip()
    for answer in validation.answers:
        assert type(answer) is ValidatedAnswer
        assert type(answer.valid) is bool
        # jev_answers_invalid_says_why and jev_answers_reason_means_invalid.
        assert (answer.invalid_reason is None) is answer.valid, answer
        assert answer.invalid_reason is None or answer.invalid_reason in REASONS
        # A Noul is never refused for its score, nor a Score for its choice.
        if answer.invalid_reason in ANSWER_REASONS:
            assert answer.invalid_reason in REASONS_BY_TYPE[answer.question_type]
        # jev_answers_question_type_check, and a key the ledger can store. A
        # question nobody could read may have neither, and the write refusing
        # it is the point: the caller's defect, surfaced where it would land.
        if answer.invalid_reason not in ("bad_question", "validator_error"):
            assert answer.question_type in QUESTION_TYPES, answer
            assert _storable(answer.question_key), answer
        # jev_answers_noul_has_no_confidence.
        if answer.question_type == "noul":
            assert answer.confidence is None, answer
        # DOUBLE PRECISION and jsonb columns: finite floats, text keys.
        for number in (answer.noul, answer.score, answer.confidence, answer.margin):
            assert number is None or _finite_float(number), answer
        if answer.probabilities is not None:
            assert type(answer.probabilities) is dict
            for name, value in answer.probabilities.items():
                assert _storable(name) and _finite_float(value), answer
        for text in (answer.choice, answer.argmax):
            assert text is None or _storable(text), answer
        if answer.valid:
            # jev_answers_valid_is_measured.
            assert answer.argmax is not None and answer.margin is not None
            required = {
                "noul": (answer.noul,),
                "choice": (answer.choice, answer.probabilities, answer.confidence),
                "score": (answer.score, answer.probabilities, answer.confidence),
            }[answer.question_type]
            assert all(value is not None for value in required), answer
            # jev_answers_valid_choice_is_its_argmax.
            if answer.question_type == "choice":
                assert answer.choice == answer.argmax, answer


# ---------------------------------------------------------------------------
# A clean response
# ---------------------------------------------------------------------------


class TestACleanResponseIsMeasured:
    def test_every_answer_is_valid_and_carries_what_was_sent(self) -> None:
        validation = _judge(_body())
        assert validation.status == "ok"
        assert validation.problem is None
        assert validation.model_answered == MODEL
        assert (validation.input_tokens, validation.output_tokens) == (212, 0)
        assert validation.answers == (
            ValidatedAnswer(
                question_key="regime",
                question_type="choice",
                noul=None,
                choice="risk_on",
                score=None,
                probabilities=CHOICE["probabilities"],
                confidence=0.49,
                argmax="risk_on",
                margin=0.41,
                valid=True,
                invalid_reason=None,
            ),
            ValidatedAnswer(
                question_key="in_scope",
                question_type="noul",
                noul=0.83,
                choice=None,
                score=None,
                probabilities=None,
                confidence=None,
                argmax="true",
                margin=0.66,
                valid=True,
                invalid_reason=None,
            ),
            ValidatedAnswer(
                question_key="severity",
                question_type="score",
                noul=None,
                choice=None,
                score=0.4,
                probabilities={"0": 0.7, "1": 0.2, "2": 0.1},
                confidence=0.55,
                argmax="0",
                margin=0.5,
                valid=True,
                invalid_reason=None,
            ),
        )

    def test_margins_are_the_decimals_written_not_their_binary_difference(
        self,
    ) -> None:
        """
        In binary, 0.62 - 0.21 is 0.41000000000000003 and 0.7 - 0.2 is
        0.49999999999999994. A margin threshold is measured on the decimals the
        vendor writes, and the second would fall short of 0.5 while meeting it.
        """
        assert 0.62 - 0.21 != 0.41 and 0.7 - 0.2 < 0.5 and 2 * 0.83 - 1 != 0.66
        regime, in_scope, severity = _judge(_body()).answers
        assert (regime.margin, in_scope.margin, severity.margin) == (0.41, 0.66, 0.5)

    @pytest.mark.parametrize(
        "encode",
        [str.encode, lambda text: bytearray(text, "utf-8")],
        ids=["bytes", "bytearray"],
    )
    def test_bytes_are_read_as_their_text(self, encode: Any) -> None:
        text = json.dumps(_body())
        assert _judge(encode(text)) == _judge(text)

    def test_an_escape_option_is_an_answer_like_any_other(self) -> None:
        """What an escape answer means — hold — is the consumer's to decide.
        Here it is measured like any other option."""
        answer = _one(
            "regime",
            _with(
                CHOICE,
                choice="insufficient_evidence",
                probabilities=dict(zip(OPTIONS, (0.1, 0.1, 0.2, 0.6), strict=True)),
            ),
        )
        assert answer.valid and answer.argmax == "insufficient_evidence"

    @pytest.mark.parametrize("name", sorted(jev_questions.REGISTRY))
    def test_the_registered_sets_can_be_answered(self, name: str) -> None:
        """The questions the shipped sets send are read as sent, so a real
        call is not the first time the two meet."""
        questions = jev_questions.get(name).as_request_questions()
        validation = _judge(_clean_body(questions), questions)
        assert validation.status == "ok", validation.problem
        assert [answer.question_key for answer in validation.answers] == list(questions)
        assert all(answer.valid for answer in validation.answers)

    def test_each_validation_builds_its_own_probabilities(self) -> None:
        text = json.dumps(_body())
        first = _by_key(validate_body(text, ASKED, MODEL))["regime"]
        first.probabilities["risk_on"] = 0.0  # type: ignore[index]
        second = _by_key(validate_body(text, ASKED, MODEL))["regime"]
        assert second.probabilities == CHOICE["probabilities"]

    def test_what_was_asked_is_not_changed(self) -> None:
        asked = copy.deepcopy(ASKED)
        _judge(_body(), asked)
        assert asked == ASKED


class TestAnswersComeBackInTheOrderAsked:
    @pytest.mark.parametrize("order", list(itertools.permutations(ASKED)))
    def test_the_order_asked_whatever_order_the_body_uses(
        self, order: tuple[str, ...]
    ) -> None:
        asked = {key: ASKED[key] for key in order}
        body = _body({key: CLEAN[key] for key in reversed(order)})
        validation = _judge(body, asked)
        assert [answer.question_key for answer in validation.answers] == list(order)
        assert all(answer.valid for answer in validation.answers)

    def test_a_missing_answer_keeps_its_place(self) -> None:
        answers = copy.deepcopy(CLEAN)
        del answers["in_scope"]
        validation = _judge(_body(answers))
        assert [(a.question_key, a.invalid_reason) for a in validation.answers] == [
            ("regime", None),
            ("in_scope", "missing"),
            ("severity", None),
        ]

    def test_probabilities_are_carried_in_the_order_asked(self) -> None:
        backwards = dict(reversed(CHOICE["probabilities"].items()))
        answer = _one("regime", _with(CHOICE, probabilities=backwards))
        assert answer.valid
        assert list(answer.probabilities or ()) == list(OPTIONS)


# ---------------------------------------------------------------------------
# The whole response
# ---------------------------------------------------------------------------

HTML_403 = (
    "<html><head><title>403 Forbidden</title></head>"
    "<body><h1>Request blocked.</h1></body></html>"
)


def _refused_whole(raw: Any, reason: str, **judge: Any) -> Validation:
    """``raw`` refused as a whole with ``reason``, every answer unmeasured."""
    validation = _judge(raw, **judge)
    assert validation.status == "invalid"
    assert validation.problem is not None
    assert validation.problem.startswith(f"{reason}: "), validation.problem
    assert validation.answers, "one answer per question asked, even refused"
    for answer in validation.answers:
        assert answer.invalid_reason == reason and not answer.valid
        assert _carried(answer) == {}, answer
    return validation


class TestAResponseThatIsNotJSONIsRefusedWhole:
    @pytest.mark.parametrize(
        "raw",
        [
            None,
            "",
            "  \n",
            HTML_403,
            "Must supply an API key!",
            json.dumps(_body())[:-7],
            json.dumps(_body()) + " }",
            json.dumps(_body()) * 2,
        ],
        ids=[
            "no-body",
            "empty",
            "whitespace",
            "html-403",
            "plain-text-403",
            "truncated",
            "trailing-garbage",
            "two-bodies",
        ],
    )
    def test_text_that_is_not_json(self, raw: Any) -> None:
        _refused_whole(raw, "unparseable")

    @pytest.mark.parametrize(
        ("path", "token"),
        [
            (("answers", "in_scope", "noul"), "NaN"),
            (("answers", "regime", "probabilities", "neutral"), "Infinity"),
            (("answers", "severity", "confidence"), "-Infinity"),
            (("usage", "input_tokens"), "NaN"),
        ],
        ids=["noul-nan", "probability-infinity", "confidence-minus-infinity", "usage"],
    )
    def test_nan_and_infinity_are_not_json_though_python_reads_them(
        self, path: tuple[str, ...], token: str
    ) -> None:
        """
        ``json.loads`` accepts all three, and so does the SDK's decoder, which
        hands a ``NaN`` Noul to a strict model that takes it. RFC 8259 has no
        spelling for any of them, and a body carrying one is not JSON — even
        where it sits outside the answers.
        """
        raw = _spelled(path, token)
        json.loads(raw)  # the trap: Python reads it
        _refused_whole(raw, "unparseable")

    def test_a_number_that_overflows_is_json_and_is_judged_by_answer(self) -> None:
        """``1e999`` is valid JSON that no float can hold. It is not refused
        whole: it is a value, judged where it stands."""
        answer = _one_spelled("in_scope", ("noul",), "1e999")
        assert answer.invalid_reason == "noul_invalid" and answer.noul is None

    @pytest.mark.parametrize(
        ("old", "new"),
        [
            (f'{{"model": "{MODEL}"', f'{{"model": "jev-1.14.0", "model": "{MODEL}"'),
            (f'{{"model": "{MODEL}"', f'{{"model": "{MODEL}", "model": "jev-1.14.0"'),
            (
                '"in_scope": {"type": "noul", "noul": 0.83}',
                '"in_scope": {"type": "noul", "noul": 0.17}, '
                '"in_scope": {"type": "noul", "noul": 0.83}',
            ),
            ('"risk_on": 0.62', '"risk_on": 0.01, "risk_on": 0.62'),
        ],
        ids=["model-pin-last", "model-pin-first", "answer", "option"],
    )
    def test_a_name_given_twice_is_refused_not_resolved(
        self, old: str, new: str
    ) -> None:
        """
        Python keeps the last and says nothing; RFC 8259 calls what a reader
        does unpredictable. The model that answered, or the probability an
        option had, would depend on who read the body.
        """
        text = json.dumps(_body())
        assert text.count(old) == 1
        raw = text.replace(old, new)
        json.loads(raw)  # the trap: Python reads it
        _refused_whole(raw, "unparseable")

    @pytest.mark.parametrize(
        "raw",
        [
            json.dumps(_body()).encode("utf-16"),
            json.dumps(_body()).encode("utf-32"),
            b'{"model": "\xff"}',
            '{"model": "\ud800"}'.encode("utf-8", "surrogatepass"),
            "\ufeff" + json.dumps(_body()),
            json.dumps(_body()).encode("utf-8-sig"),
        ],
        ids=[
            "utf-16",
            "utf-32",
            "invalid-utf-8",
            "encoded-surrogate",
            "bom",
            "bom-bytes",
        ],
    )
    def test_bytes_must_be_utf_8(self, raw: Any) -> None:
        """``json.loads`` would guess UTF-16 and UTF-32 from bytes; JSON
        exchanged between systems is UTF-8, without a byte-order mark."""
        _refused_whole(raw, "unparseable")

    @pytest.mark.parametrize(
        "raw",
        ["[" * 100_000 + "]" * 100_000, '{"model": ' + "1" * 5000 + "}"],
        ids=["nested-past-the-recursion-limit", "5000-digit-integer"],
    )
    def test_what_the_decoder_cannot_hold_is_refused_not_raised(self, raw: str) -> None:
        """``json`` raises ``RecursionError`` for the first and a
        ``ValueError`` about digit limits for the second."""
        _refused_whole(raw, "unparseable")

    @pytest.mark.parametrize(
        "raw",
        [42, 4.2, True, [], {}, memoryview(b"{}"), object()],
        ids=["int", "float", "bool", "list", "dict", "memoryview", "object"],
    )
    def test_a_body_is_text(self, raw: Any) -> None:
        """Even an already-decoded dict: the body judged is the body recorded,
        and a decoded one has lost what the rules read."""
        validation = validate_body(raw, ASKED, MODEL)
        _assert_fits_the_ledger(validation)
        assert validation.status == "invalid"
        assert validation.problem.startswith("unparseable: the body is a ")  # type: ignore[union-attr]

    def test_nothing_is_read_from_a_body_that_is_not_json(self) -> None:
        validation = _refused_whole(HTML_403, "unparseable")
        assert validation.model_answered is None
        assert (validation.input_tokens, validation.output_tokens) == (None, None)


class TestAResponseThatIsNotAnAnswerIsRefusedWhole:
    @pytest.mark.parametrize(
        "raw",
        ["null", "[]", json.dumps([_body()]), '"ok"', "200", "true"],
        ids=["null", "empty-array", "array", "string", "number", "true"],
    )
    def test_json_that_is_not_an_object(self, raw: str) -> None:
        _refused_whole(raw, "not_an_object")

    @pytest.mark.parametrize(
        "answers",
        [DROP, None, [CHOICE, NOUL, SCORE], "regime", 3],
        ids=["absent", "null", "array", "string", "number"],
    )
    def test_answers_that_are_not_an_object(self, answers: Any) -> None:
        validation = _refused_whole(_body(answers), "answers_not_an_object")
        # Read anyway: the call was made and billed.
        assert validation.model_answered == MODEL
        assert (validation.input_tokens, validation.output_tokens) == (212, 0)

    @pytest.mark.parametrize(
        "answers",
        [{}, {"elsewhere": NOUL}, {key: None for key in ASKED}],
        ids=["empty", "only-unasked", "all-null"],
    )
    def test_answers_to_none_of_the_questions_asked(self, answers: Any) -> None:
        """
        ``{}`` parses cleanly through the SDK, whose ``answers`` defaults to
        it. Refused whole — not ``ok`` with every answer missing, which the
        ledger would hold as canonical and replay as unanswered for good.
        """
        _refused_whole(_body(answers), "no_answers")

    def test_what_was_answered_instead_is_named(self) -> None:
        validation = _refused_whole(_body({"elsewhere": NOUL}), "no_answers")
        assert "unasked_answers: " in (validation.problem or "")
        assert "'elsewhere'" in (validation.problem or "")

    def test_one_answer_to_a_question_asked_is_enough_to_be_judged(self) -> None:
        validation = _judge(_body({"in_scope": NOUL}))
        assert validation.status == "ok"
        assert [a.invalid_reason for a in validation.answers] == [
            "missing",
            None,
            "missing",
        ]


class TestTheAnswersMustComeFromThePinnedModel:
    @pytest.mark.parametrize(
        "model",
        [
            "jev-1.14.0",
            "jev-1.12.0",
            "jev-latest",
            "jev-1.13",
            "JEV-1.13.0",
            MODEL + " ",
            MODEL + "\n",
        ],
    )
    def test_another_model_is_refused_and_named(self, model: str) -> None:
        """``response.model`` can differ from the model requested. An answer
        from another model belongs to no threshold measured here."""
        validation = _refused_whole(_body(model=model), "model_mismatch")
        assert validation.model_answered == model
        assert (validation.input_tokens, validation.output_tokens) == (212, 0)

    @pytest.mark.parametrize(
        "model",
        [DROP, None, 1.13, True, [MODEL], {"name": MODEL}],
        ids=["absent", "null", "number", "bool", "list", "object"],
    )
    def test_no_model_named_is_not_the_pin(self, model: Any) -> None:
        validation = _refused_whole(_body(model=model), "model_mismatch")
        assert validation.model_answered is None

    @pytest.mark.parametrize(
        "pin",
        ["jev-latest", "jev-preview", "jev-1.14.0", MODEL + "\n", None, ""],
    )
    def test_a_pin_the_catalogue_refuses_is_matched_by_nothing(self, pin: Any) -> None:
        """
        Even a response that echoes it. A caller that pinned an alias would
        otherwise accept an answer given under one, and an answer under an alias
        belongs to no model anybody can name afterwards.
        """
        validation = _refused_whole(_body(model=pin), "model_mismatch", pin=pin)
        assert "the pin is refused" in (validation.problem or "")


# ---------------------------------------------------------------------------
# Each answer
# ---------------------------------------------------------------------------


class TestEachAnswerIsJudgedAlone:
    @pytest.mark.parametrize("key", list(ASKED))
    def test_an_absent_answer_is_missing_and_the_rest_stand(self, key: str) -> None:
        answers = copy.deepcopy(CLEAN)
        del answers[key]
        validation = _judge(_body(answers))
        assert validation.status == "ok"
        for answer in validation.answers:
            if answer.question_key == key:
                assert answer.invalid_reason == "missing"
                assert _carried(answer) == {}
            else:
                assert answer.valid

    def test_a_null_answer_is_missing(self) -> None:
        answer = _one("in_scope", None)
        assert answer.invalid_reason == "missing" and _carried(answer) == {}

    @pytest.mark.parametrize(
        ("key", "answer"),
        [
            ("in_scope", CHOICE),
            ("in_scope", SCORE),
            ("regime", NOUL),
            ("regime", SCORE),
            ("severity", CHOICE),
            ("severity", NOUL),
            ("in_scope", _with(NOUL, type="Noul")),
            ("in_scope", _with(NOUL, type=DROP)),
            ("in_scope", _with(NOUL, type=None)),
            ("in_scope", 0.83),
            ("in_scope", True),
            ("regime", "risk_on"),
            ("severity", [0.7, 0.2, 0.1]),
            ("regime", {}),
        ],
        ids=[
            "noul-answered-as-choice",
            "noul-answered-as-score",
            "choice-answered-as-noul",
            "choice-answered-as-score",
            "score-answered-as-choice",
            "score-answered-as-noul",
            "type-in-another-case",
            "no-type",
            "null-type",
            "a-bare-number",
            "a-bare-boolean",
            "a-bare-string",
            "a-bare-array",
            "an-empty-object",
        ],
    )
    def test_an_answer_of_another_type_carries_nothing(
        self, key: str, answer: Any
    ) -> None:
        """An answer of another type answers another question: none of its
        fields mean what this question's fields do."""
        judged = _one(key, answer)
        assert judged.invalid_reason == "type_mismatch"
        assert judged.question_type == ASKED[key]["type"]
        assert _carried(judged) == {}

    def test_an_unasked_answer_is_ignored_and_noted(self) -> None:
        answers = copy.deepcopy(CLEAN)
        answers["surprise"] = NOUL
        validation = _judge(_body(answers))
        assert validation.status == "ok"
        assert [a.question_key for a in validation.answers] == list(ASKED)
        assert all(answer.valid for answer in validation.answers)
        assert validation.problem is not None
        assert validation.problem.startswith("unasked_answers: ")
        assert "'surprise'" in validation.problem

    def test_a_flood_of_unasked_answers_is_named_briefly(self) -> None:
        answers = copy.deepcopy(CLEAN)
        answers.update({f"extra_{index}": NOUL for index in range(40)})
        problem = _judge(_body(answers)).problem or ""
        assert "'extra_0'" in problem and "'extra_39'" not in problem
        assert "and 35 more" in problem


class TestANoul:
    @pytest.mark.parametrize(
        ("token", "reason", "noul", "argmax", "margin"),
        [
            ("0", None, 0.0, "false", 1.0),
            ("1", None, 1.0, "true", 1.0),
            ("0.0", None, 0.0, "false", 1.0),
            ("1.0", None, 1.0, "true", 1.0),
            ("0.01", None, 0.01, "false", 0.98),
            ("0.99", None, 0.99, "true", 0.98),
            ("0.49", None, 0.49, "false", 0.02),
            ("0.51", None, 0.51, "true", 0.02),
            ("8.3e-1", None, 0.83, "true", 0.66),
            ("0.5", "tie", 0.5, None, 0.0),
            ("0.50", "tie", 0.5, None, 0.0),
            ("5e-1", "tie", 0.5, None, 0.0),
            ("-0.01", "noul_invalid", -0.01, None, None),
            ("1.01", "noul_invalid", 1.01, None, None),
            ("2", "noul_invalid", 2.0, None, None),
            ("1e999", "noul_invalid", None, None, None),
            ("-1e999", "noul_invalid", None, None, None),
            ("1" + "0" * 400, "noul_invalid", None, None, None),
            ("true", "noul_invalid", None, None, None),
            ("false", "noul_invalid", None, None, None),
            ('"0.83"', "noul_invalid", None, None, None),
            ("null", "noul_invalid", None, None, None),
            ("[0.83]", "noul_invalid", None, None, None),
            ('{"p": 0.83}', "noul_invalid", None, None, None),
        ],
    )
    def test_a_noul_is_a_real_number_from_0_to_1(
        self,
        token: str,
        reason: str | None,
        noul: float | None,
        argmax: str | None,
        margin: float | None,
    ) -> None:
        """
        0 and 1 are allowed: Noul values have only been observed within 0.01 and
        0.99, and that is an observation, not a bound. Exactly 0.5 is no answer
        either way. What cannot be a probability is kept only if it is a finite
        real number — 1.01 is what the vendor said — and is never stood in for.
        """
        answer = _one_spelled("in_scope", ("noul",), token)
        assert (answer.invalid_reason, answer.noul, answer.argmax, answer.margin) == (
            reason,
            noul,
            argmax,
            margin,
        )
        assert answer.valid is (reason is None)

    def test_an_absent_noul_is_invalid(self) -> None:
        answer = _one("in_scope", _with(NOUL, noul=DROP))
        assert answer.invalid_reason == "noul_invalid" and _carried(answer) == {}

    def test_true_is_not_1(self) -> None:
        """Python's ``True == 1`` is the trap: a Noul of ``true`` would read as
        certain yes if the check were ``isinstance(value, (int, float))``."""
        assert True == 1 and isinstance(True, int)  # noqa: E712 — the trap
        assert _one("in_scope", _with(NOUL, noul=1)).valid
        refused = _one("in_scope", _with(NOUL, noul=True))
        assert refused.invalid_reason == "noul_invalid"
        assert refused.noul is None

    @pytest.mark.parametrize("confidence", [0.9, 0, 1, "high", True, None, [0.9]])
    def test_a_noul_has_no_confidence_whatever_the_body_says(
        self, confidence: Any
    ) -> None:
        """Jev's Noul has none, and the ledger refuses one on a Noul row: a
        number there would be one the vendor was never asked for."""
        answer = _one("in_scope", _with(NOUL, confidence=confidence))
        assert answer.valid and answer.confidence is None


def _choice(probabilities: tuple[float, ...], **fields: Any) -> dict[str, Any]:
    return _with(
        CHOICE, probabilities=dict(zip(OPTIONS, probabilities, strict=True)), **fields
    )


def _score(probabilities: tuple[float, ...], **fields: Any) -> dict[str, Any]:
    keys = [str(level) for level in range(len(probabilities))]
    return _with(
        SCORE, probabilities=dict(zip(keys, probabilities, strict=True)), **fields
    )


class TestProbabilities:
    @pytest.mark.parametrize(
        ("key", "answer", "reason"),
        [
            ("regime", _choice((0.6, 0.2, 0.12, 0.05)), "probability_sum"),
            ("regime", _choice((0.66, 0.2, 0.12, 0.05)), "probability_sum"),
            ("regime", _choice((0.62, 0.2, 0.12, 0.05)), None),
            ("regime", _choice((0.64, 0.2, 0.12, 0.05)), None),
            ("regime", _choice((0.609, 0.2, 0.12, 0.05)), "probability_sum"),
            ("regime", _choice((0.651, 0.2, 0.12, 0.05)), "probability_sum"),
            ("severity", _score((0.67, 0.2, 0.1)), "probability_sum"),
            ("severity", _score((0.73, 0.2, 0.1)), "probability_sum"),
            ("severity", _score((0.69, 0.2, 0.1)), None),
            ("severity", _score((0.71, 0.2, 0.1)), None),
        ],
        ids=[
            "choice-0.97",
            "choice-1.03",
            "choice-0.99",
            "choice-1.01",
            "choice-0.979",
            "choice-1.021",
            "score-0.97",
            "score-1.03",
            "score-0.99",
            "score-1.01",
        ],
    )
    def test_they_sum_to_1_within_0_02(
        self, key: str, answer: dict[str, Any], reason: str | None
    ) -> None:
        judged = _one(key, answer)
        assert judged.invalid_reason == reason
        if reason is not None:
            # Carried for the record, and nothing computed from them.
            assert judged.probabilities is not None
            assert (judged.argmax, judged.margin) == (None, None)

    @pytest.mark.parametrize(
        ("key", "answer"),
        [
            ("regime", _choice((0.26, 0.24, 0.24, 0.24))),
            ("regime", _choice((0.66, 0.2, 0.12, 0.04))),
            ("severity", _score((0.36, 0.34, 0.32), score=0.96)),
            ("severity", _score((0.36, 0.32, 0.30), score=0.92)),
        ],
        ids=["choice-0.98", "choice-1.02", "score-1.02", "score-0.98"],
    )
    def test_a_sum_exactly_on_the_tolerance_is_accepted(
        self, key: str, answer: dict[str, Any]
    ) -> None:
        """Each of these sums to exactly 0.98 or 1.02 as written, and each fails
        ``abs(sum - 1) <= 0.02`` in binary. The tolerance is inclusive, on the
        decimals."""
        values = list(answer["probabilities"].values())
        assert abs(sum(values) - 1) > 0.02  # the trap: binary refuses them
        assert _one(key, answer).valid

    @pytest.mark.parametrize(
        "probabilities",
        [
            {"risk_on": 0.62, "neutral": 0.21, "risk_off": 0.17},
            {**CHOICE["probabilities"], "sideways": 0.0},
            {
                "Risk_On": 0.62,
                "neutral": 0.21,
                "risk_off": 0.12,
                "insufficient_evidence": 0.05,
            },
            {
                "risk_on ": 0.62,
                "neutral": 0.21,
                "risk_off": 0.12,
                "insufficient_evidence": 0.05,
            },
            {"0": 0.62, "1": 0.21, "2": 0.12, "3": 0.05},
            {},
            DROP,
            None,
            [0.62, 0.21, 0.12, 0.05],
            "risk_on",
        ],
        ids=[
            "an-option-missing",
            "an-option-added",
            "an-option-renamed",
            "an-option-with-a-space",
            "keyed-by-position",
            "empty",
            "absent",
            "null",
            "array",
            "string",
        ],
    )
    def test_a_choice_is_keyed_by_exactly_the_options_asked(
        self, probabilities: Any
    ) -> None:
        answer = _one("regime", _with(CHOICE, probabilities=probabilities))
        assert answer.invalid_reason == "probability_keys"
        assert (answer.argmax, answer.margin) == (None, None)

    @pytest.mark.parametrize(
        "probabilities",
        [
            {"1": 0.7, "2": 0.2, "3": 0.1},
            {"0": 0.8, "1": 0.2},
            {"0": 0.7, "1": 0.2, "2": 0.1, "3": 0.0},
            {"00": 0.7, "01": 0.2, "02": 0.1},
            {" 0": 0.7, "1": 0.2, "2": 0.1},
            {"calm": 0.7, "unusual": 0.2, "extreme": 0.1},
            [0.7, 0.2, 0.1],
        ],
        ids=[
            "keyed-1-to-n",
            "a-level-missing",
            "a-level-added",
            "zero-padded",
            "with-a-space",
            "keyed-by-the-levels-words",
            "array",
        ],
    )
    def test_a_score_is_keyed_0_to_n_minus_1(self, probabilities: Any) -> None:
        answer = _one("severity", _with(SCORE, probabilities=probabilities))
        assert answer.invalid_reason == "probability_keys"
        assert (answer.argmax, answer.margin) == (None, None)

    def test_probabilities_keyed_wrongly_are_carried_as_sent(self) -> None:
        answer = _one("severity", _with(SCORE, probabilities={"1": 0.7, "2": 0.3}))
        assert answer.probabilities == {"1": 0.7, "2": 0.3}

    @pytest.mark.parametrize(
        ("value", "carried"),
        [
            (True, False),
            (False, False),
            ("0.21", False),
            (None, False),
            ([0.21], False),
            (-0.01, True),
            (1.01, True),
        ],
    )
    @pytest.mark.parametrize("key", ["regime", "severity"])
    def test_each_probability_is_a_real_number_from_0_to_1(
        self, key: str, value: Any, carried: bool
    ) -> None:
        """``true`` is not a probability of 1. A value that is a real number is
        kept for the record however wrong; one that is not leaves nothing a
        reader could mistake for a distribution."""
        base = CLEAN[key]
        probabilities = dict(base["probabilities"])
        second = list(probabilities)[1]
        probabilities[second] = value
        answer = _one(key, _with(base, probabilities=probabilities))
        assert answer.invalid_reason == "probability_invalid"
        assert (answer.probabilities is not None) is carried
        assert (answer.argmax, answer.margin) == (None, None)

    def test_a_probability_that_overflows_is_not_a_probability(self) -> None:
        answer = _one_spelled("regime", ("probabilities", "neutral"), "1e999")
        assert answer.invalid_reason == "probability_invalid"
        assert answer.probabilities is None

    def test_a_callers_decimal_context_changes_no_verdict(self) -> None:
        """
        Decimal arithmetic rounds to the calling thread's context, which any
        code in the process can change. At two digits, 0.665 + 0.2 + 0.12 +
        0.045 — exactly 1.03 — would round to 1.0 and pass; at one, every
        margin here would come out wrong.
        """
        over = _body({**CLEAN, "regime": _choice((0.665, 0.2, 0.12, 0.045))})
        with decimal.localcontext(prec=2):
            refused = validate_body(json.dumps(over), ASKED, MODEL)
        assert _by_key(refused)["regime"].invalid_reason == "probability_sum"
        with decimal.localcontext(prec=1):
            clean = validate_body(json.dumps(_body()), ASKED, MODEL)
        assert [answer.margin for answer in clean.answers] == [0.41, 0.66, 0.5]


class TestAChoice:
    @pytest.mark.parametrize(
        "choice",
        ["RISK_ON", "risk_on ", "", "sideways", None, DROP, 0, True, ["risk_on"]],
    )
    def test_the_choice_is_one_of_the_options_asked(self, choice: Any) -> None:
        answer = _one("regime", _with(CHOICE, choice=choice))
        assert answer.invalid_reason == "choice_not_in_criteria"
        assert answer.choice == (choice if isinstance(choice, str) else None)
        # The distribution was sound, so what it says is still recorded.
        assert (answer.argmax, answer.margin) == ("risk_on", 0.41)

    def test_a_choice_that_is_not_the_most_probable_is_an_abstention(self) -> None:
        """
        SDK issue #15: on jev-1.13.0 the vendor's ``choice`` is sometimes
        exactly 0.01 below another option, in near-ties at low confidence.
        Both are kept — the vendor's choice and ours — so the disagreement can
        be counted, and the answer is not measured.
        """
        answer = _one(
            "regime",
            _choice((0.41, 0.40, 0.12, 0.07), choice="neutral", confidence=0.02),
        )
        assert answer.invalid_reason == "choice_not_argmax" and not answer.valid
        assert (answer.choice, answer.argmax) == ("neutral", "risk_on")
        assert answer.margin == 0.01
        assert answer.probabilities == dict(
            zip(OPTIONS, (0.41, 0.40, 0.12, 0.07), strict=True)
        )

    @pytest.mark.parametrize(
        ("probabilities", "choice"),
        [
            ((0.4, 0.4, 0.12, 0.08), "risk_on"),
            ((0.4, 0.4, 0.12, 0.08), "neutral"),
            ((0.4, 0.4, 0.12, 0.08), "risk_off"),
            ((0.3, 0.3, 0.3, 0.1), "risk_on"),
        ],
        ids=["picking-the-first", "picking-the-second", "picking-neither", "three-way"],
    )
    def test_an_exact_tie_at_the_top_is_an_abstention(
        self, probabilities: tuple[float, ...], choice: str
    ) -> None:
        answer = _one("regime", _choice(probabilities, choice=choice))
        assert answer.invalid_reason == "tie"
        assert (answer.argmax, answer.margin) == (None, 0.0)

    @pytest.mark.parametrize("spelling", ["0.40", "4e-1", "0.4000000000000000001"])
    def test_a_tie_is_decided_on_the_value_not_its_spelling(
        self, spelling: str
    ) -> None:
        tied = _body({**CLEAN, "regime": _choice((0.4, 0.4, 0.12, 0.08))})
        path = ("answers", "regime", "probabilities", "neutral")
        answer = _by_key(_judge(_spelled(path, spelling, tied)))["regime"]
        assert answer.invalid_reason == "tie"

    def test_a_tie_below_the_top_is_no_tie(self) -> None:
        answer = _one("regime", _choice((0.62, 0.19, 0.19, 0.0)))
        assert answer.valid and answer.margin == 0.43


class TestAScore:
    @pytest.mark.parametrize(
        ("score", "probabilities", "reason", "argmax"),
        [
            (0, (1.0, 0.0, 0.0), None, "0"),
            (0.0, (0.9, 0.1, 0.0), None, "0"),
            (2, (0.0, 0.0, 1.0), None, "2"),
            (1.7, (0.1, 0.1, 0.8), None, "2"),
            (-0.01, (0.7, 0.2, 0.1), "score_invalid", "0"),
            (2.01, (0.1, 0.1, 0.8), "score_invalid", "2"),
            (3, (0.0, 0.0, 1.0), "score_invalid", "2"),
            (True, (0.1, 0.8, 0.1), "score_invalid", "1"),
            ("0.4", (0.7, 0.2, 0.1), "score_invalid", "0"),
            (None, (0.7, 0.2, 0.1), "score_invalid", "0"),
            (DROP, (0.7, 0.2, 0.1), "score_invalid", "0"),
        ],
        ids=[
            "0",
            "0.0",
            "the-top-level",
            "between-levels",
            "below-0",
            "above-the-top-level",
            "the-count-of-levels",
            "true",
            "a-string",
            "null",
            "absent",
        ],
    )
    def test_the_score_is_a_real_number_from_0_to_the_top_level(
        self,
        score: Any,
        probabilities: tuple[float, ...],
        reason: str | None,
        argmax: str,
    ) -> None:
        """The score is the probability-weighted mean of levels 0 to n-1: it can
        fall between levels and never outside them. The top level is n-1, not
        n, and ``true`` is not level 1."""
        answer = _one("severity", _score(probabilities, score=score))
        assert answer.invalid_reason == reason
        assert answer.argmax == argmax
        real = not isinstance(score, bool) and isinstance(score, (int, float))
        assert answer.score == (float(score) if real else None)

    def test_a_score_that_overflows_is_not_a_score(self) -> None:
        answer = _one_spelled("severity", ("score",), "1e999")
        assert answer.invalid_reason == "score_invalid" and answer.score is None

    def test_the_argmax_is_the_most_probable_level(self) -> None:
        answer = _one("severity", _score((0.1, 0.2, 0.7), score=1.6))
        assert answer.valid and (answer.argmax, answer.margin) == ("2", 0.5)

    def test_an_exact_tie_at_the_top_is_an_abstention(self) -> None:
        answer = _one("severity", _score((0.45, 0.45, 0.1), score=0.65))
        assert answer.invalid_reason == "tie"
        assert (answer.argmax, answer.margin) == (None, 0.0)


class TestConfidence:
    @pytest.mark.parametrize(
        ("confidence", "reason", "carried"),
        [
            (0, None, 0.0),
            (1, None, 1.0),
            (0.0, None, 0.0),
            (1.0, None, 1.0),
            (-0.01, "confidence_invalid", -0.01),
            (1.01, "confidence_invalid", 1.01),
            (True, "confidence_invalid", None),
            (False, "confidence_invalid", None),
            ("0.49", "confidence_invalid", None),
            ([0.49], "confidence_invalid", None),
            (None, "confidence_invalid", None),
            (DROP, "confidence_invalid", None),
        ],
    )
    @pytest.mark.parametrize("key", ["regime", "severity"])
    def test_confidence_is_a_real_number_from_0_to_1(
        self, key: str, confidence: Any, reason: str | None, carried: float | None
    ) -> None:
        """
        Never range-checked by the SDK. It measures how concentrated the
        probabilities are, not how likely the answer is to be right, and a
        Choice or Score without a readable one is not measured.
        """
        answer = _one(key, _with(CLEAN[key], confidence=confidence))
        assert (answer.invalid_reason, answer.confidence) == (reason, carried)

    def test_a_confidence_that_overflows_is_not_a_confidence(self) -> None:
        answer = _one_spelled("regime", ("confidence",), "1e999")
        assert answer.invalid_reason == "confidence_invalid"
        assert answer.confidence is None


class TestWhenTwoRulesFailTheFirstIsRecorded:
    """
    One reason per answer, the first rule in :data:`ANSWER_REASONS` order that
    fails, so the same malformation is always filed under the same name and a
    count of reasons means something.
    """

    @pytest.mark.parametrize(
        ("key", "answer", "first", "also"),
        [
            (
                "in_scope",
                _with(NOUL, type="score", noul=2),
                "type_mismatch",
                "noul_invalid",
            ),
            (
                "regime",
                _with(CHOICE, probabilities={"risk_on": True, "neutral": 0.4}),
                "probability_keys",
                "probability_invalid",
            ),
            (
                "regime",
                _choice((1.5, 0.2, 0.12, 0.05)),
                "probability_invalid",
                "probability_sum",
            ),
            (
                "regime",
                _choice((0.5, 0.2, 0.12, 0.05), choice="x"),
                "probability_sum",
                "choice_not_in_criteria",
            ),
            (
                "regime",
                _with(CHOICE, choice="x", confidence=2),
                "choice_not_in_criteria",
                "confidence_invalid",
            ),
            (
                "regime",
                _choice((0.4, 0.4, 0.12, 0.08), confidence=2),
                "confidence_invalid",
                "tie",
            ),
            (
                "regime",
                _choice((0.41, 0.40, 0.12, 0.07), choice="neutral", confidence=-1),
                "confidence_invalid",
                "choice_not_argmax",
            ),
            (
                "regime",
                _choice((0.4, 0.4, 0.12, 0.08), choice="risk_off"),
                "tie",
                "choice_not_argmax",
            ),
            (
                "severity",
                _score((0.5, 0.2, 0.1), score=5),
                "probability_sum",
                "score_invalid",
            ),
            (
                "severity",
                _with(SCORE, score=5, confidence=2),
                "score_invalid",
                "confidence_invalid",
            ),
            ("severity", _score((0.45, 0.45, 0.1), score=5), "score_invalid", "tie"),
        ],
    )
    def test_the_earlier_rule_is_the_reason(
        self, key: str, answer: dict[str, Any], first: str, also: str
    ) -> None:
        order = list(ANSWER_REASONS)
        assert order.index(first) < order.index(also)
        assert _one(key, answer).invalid_reason == first


# ---------------------------------------------------------------------------
# What the response costs, and what the ledger can hold
# ---------------------------------------------------------------------------


class TestUsageIsReadButNeverDecides:
    @pytest.mark.parametrize(
        ("usage", "counts", "noted"),
        [
            ({"input_tokens": 212, "output_tokens": 0}, (212, 0), False),
            (
                {"input_tokens": MAX_TOKEN_COUNT, "output_tokens": 0},
                (MAX_TOKEN_COUNT, 0),
                False,
            ),
            (
                {"input_tokens": MAX_TOKEN_COUNT + 1, "output_tokens": 0},
                (None, 0),
                True,
            ),
            ({"input_tokens": -1, "output_tokens": 0}, (None, 0), True),
            ({"input_tokens": True, "output_tokens": 0}, (None, 0), True),
            ({"input_tokens": 212.0, "output_tokens": 0}, (None, 0), True),
            ({"input_tokens": "212", "output_tokens": 0}, (None, 0), True),
            ({"input_tokens": 212}, (212, None), True),
            (DROP, (None, None), True),
            (None, (None, None), True),
            ([212, 0], (None, None), True),
        ],
        ids=[
            "counts",
            "the-largest-int",
            "past-int",
            "negative",
            "a-boolean",
            "a-float",
            "a-string",
            "output-absent",
            "absent",
            "null",
            "array",
        ],
    )
    def test_a_count_is_a_non_negative_integer_the_ledger_can_hold(
        self, usage: Any, counts: tuple[Any, Any], noted: bool
    ) -> None:
        """
        A count is an integer, as the SDK's strict schema has it, and fits the
        INT column, or the insert recording the call would fail. An unreadable
        count is ``None`` and noted — never 0, which would be a measurement of
        a free call — and the answers are judged exactly as before.
        """
        validation = _judge(_body(usage=usage))
        assert validation.status == "ok"
        assert all(answer.valid for answer in validation.answers)
        assert (validation.input_tokens, validation.output_tokens) == counts
        assert ("usage_unreadable: " in (validation.problem or "")) is noted


class TestOnlyWhatTheLedgerCanStoreIsCarried:
    """
    Postgres holds neither NUL nor an unpaired surrogate, in ``text`` or in
    ``jsonb``, and JSON can spell both. Carried onto an answer, either would
    fail the write that records a call already made and billed.
    """

    @pytest.mark.parametrize(
        "model", [MODEL + "\x00", "\ud800"], ids=["nul", "surrogate"]
    )
    def test_the_model_answered(self, model: str) -> None:
        validation = _refused_whole(_body(model=model), "model_mismatch")
        assert validation.model_answered is None

    @pytest.mark.parametrize(
        "choice", ["risk_on\x00", "\udfff"], ids=["nul", "surrogate"]
    )
    def test_a_choice(self, choice: str) -> None:
        answer = _one("regime", _with(CHOICE, choice=choice))
        assert answer.invalid_reason == "choice_not_in_criteria"
        assert answer.choice is None

    def test_a_probability_key(self) -> None:
        probabilities = {**CHOICE["probabilities"], "\x00": 0.0}
        answer = _one("regime", _with(CHOICE, probabilities=probabilities))
        assert answer.invalid_reason == "probability_keys"
        assert answer.probabilities is None


class TestTheProblemIsANoteForPeople:
    """
    ``problem`` goes to a log and an operator, not to a rule: each note starts
    with its code so it can be searched for, and what the vendor wrote is
    quoted briefly, because the vendor chooses how long it is.
    """

    def test_notes_are_coded_and_joined(self) -> None:
        answers = {**CLEAN, "surprise": NOUL}
        problem = _judge(_body(answers, usage=DROP)).problem or ""
        notes = problem.split("; ")
        assert [note.split(": ", 1)[0] for note in notes] == [
            "unasked_answers",
            "usage_unreadable",
        ]

    def test_what_the_vendor_wrote_is_quoted_briefly(self) -> None:
        model = "jev-" + "9" * 10_000
        refused = _refused_whole(_body(model=model), "model_mismatch")
        # Carried whole — it is what the vendor sent — and quoted briefly.
        assert refused.model_answered == model
        assert len(refused.problem or "") < 200
        flooded = _judge(_body({**CLEAN, "k" * 10_000: NOUL}))
        assert len(flooded.problem or "") < 200

    @pytest.mark.parametrize(
        ("raw", "named"),
        [
            ("null", "a JSON null"),
            ("[]", "a JSON array"),
            ('"ok"', "a JSON string"),
            ("200", "a JSON number"),
            ("true", "a JSON boolean"),
            (json.dumps(_body(DROP)), "`answers` is absent"),
            (json.dumps(_body([])), "`answers` is a JSON array"),
        ],
    )
    def test_what_was_found_is_named_in_json_terms(self, raw: str, named: str) -> None:
        assert named in (_judge(raw).problem or "")


# ---------------------------------------------------------------------------
# The questions as asked
# ---------------------------------------------------------------------------


class TestAQuestionThatCannotBeCheckedRefusesEverything:
    @pytest.mark.parametrize(
        "asked",
        [
            {**ASKED, "mood": {"type": "vibe", "instructions": "How is it?"}},
            {**ASKED, "mood": {"instructions": "How is it?"}},
            {**ASKED, "mood": "How is it?"},
            {"regime": {"type": "choice", "criteria": {"risk_on": "Up."}}},
            {"regime": {"type": "choice", "criteria": list(OPTIONS)}},
            {"regime": {"type": "choice"}},
            {"severity": {"type": "score", "criteria": ["only"]}},
            {"severity": {"type": "score", "criteria": {"0": "calm", "1": "wild"}}},
            {"severity": {"type": "score", "criteria": "calm, wild"}},
            {**ASKED, 1: {"type": "noul", "instructions": "Is it?"}},
            {**ASKED, "in\x00scope": {"type": "noul", "instructions": "Is it?"}},
            {**ASKED, "\ud800": {"type": "noul", "instructions": "Is it?"}},
        ],
        ids=[
            "a-type-nobody-defined",
            "no-type",
            "not-a-mapping",
            "a-choice-of-one",
            "a-choice-listing-options",
            "a-choice-with-no-criteria",
            "a-score-of-one-level",
            "a-score-mapping-levels",
            "a-score-of-a-string",
            "a-key-that-is-not-text",
            "a-key-with-nul",
            "a-key-with-a-lone-surrogate",
        ],
    )
    def test_every_answer_is_refused_with_the_question(self, asked: Any) -> None:
        """
        A question the registry would refuse never reaches the vendor, so one
        here is the caller's defect — and a request built wrongly is not one
        whose other answers should be trusted either. Refused, not raised.
        """
        validation = _refused_whole(_body(), "bad_question", asked=asked)
        assert len(validation.answers) == len(asked)
        # The call was still made and billed.
        assert (validation.input_tokens, validation.output_tokens) == (212, 0)

    @pytest.mark.parametrize(
        "asked", [{}, None, [("in_scope", ASKED["in_scope"])], "in_scope"]
    )
    def test_nothing_asked_is_nothing_to_answer(self, asked: Any) -> None:
        validation = _judge(_body(), asked)
        assert validation.status == "invalid" and validation.answers == ()
        assert (validation.problem or "").startswith("bad_question: ")


# ---------------------------------------------------------------------------
# The vocabulary
# ---------------------------------------------------------------------------

#: One body for each reason, so every name in the vocabulary is shown to be
#: reachable. ``validator_error`` has a test of its own.
REACHABLE: dict[str, tuple[Any, Any, Any]] = {
    "bad_question": (json.dumps(_body()), {"mood": {"type": "vibe"}}, MODEL),
    "unparseable": (HTML_403, ASKED, MODEL),
    "not_an_object": ("[]", ASKED, MODEL),
    "answers_not_an_object": (json.dumps(_body(DROP)), ASKED, MODEL),
    "model_mismatch": (json.dumps(_body(model="jev-1.14.0")), ASKED, MODEL),
    "no_answers": (json.dumps(_body({})), ASKED, MODEL),
    "missing": (json.dumps(_body({"regime": CHOICE})), ASKED, MODEL),
    "type_mismatch": (json.dumps(_body({**CLEAN, "in_scope": CHOICE})), ASKED, MODEL),
    "noul_invalid": (
        json.dumps(_body({**CLEAN, "in_scope": _with(NOUL, noul=2)})),
        ASKED,
        MODEL,
    ),
    "probability_keys": (
        json.dumps(_body({**CLEAN, "severity": _score((0.7, 0.3))})),
        ASKED,
        MODEL,
    ),
    "probability_invalid": (
        json.dumps(_body({**CLEAN, "regime": _choice((0.62, True, 0.12, 0.05))})),
        ASKED,
        MODEL,
    ),
    "probability_sum": (
        json.dumps(_body({**CLEAN, "regime": _choice((0.5, 0.21, 0.12, 0.05))})),
        ASKED,
        MODEL,
    ),
    "choice_not_in_criteria": (
        json.dumps(_body({**CLEAN, "regime": _with(CHOICE, choice="x")})),
        ASKED,
        MODEL,
    ),
    "score_invalid": (
        json.dumps(_body({**CLEAN, "severity": _with(SCORE, score=3)})),
        ASKED,
        MODEL,
    ),
    "confidence_invalid": (
        json.dumps(_body({**CLEAN, "severity": _with(SCORE, confidence=2)})),
        ASKED,
        MODEL,
    ),
    "tie": (
        json.dumps(_body({**CLEAN, "in_scope": _with(NOUL, noul=0.5)})),
        ASKED,
        MODEL,
    ),
    "choice_not_argmax": (
        json.dumps(_body({**CLEAN, "regime": _with(CHOICE, choice="neutral")})),
        ASKED,
        MODEL,
    ),
}


class TestTheVocabulary:
    def test_the_reasons_are_the_two_lists_and_they_do_not_overlap(self) -> None:
        assert dict(REASONS) == {**RESPONSE_REASONS, **ANSWER_REASONS}
        assert not set(RESPONSE_REASONS) & set(ANSWER_REASONS)
        assert all(description.strip() for description in REASONS.values())

    def test_every_reason_is_reachable(self) -> None:
        assert set(REACHABLE) | {"validator_error"} == set(REASONS)

    @pytest.mark.parametrize("reason", sorted(REACHABLE))
    def test_each_reason_is_produced_by_its_body(self, reason: str) -> None:
        raw, asked, pin = REACHABLE[reason]
        validation = _judge(raw, asked, pin)
        assert reason in {answer.invalid_reason for answer in validation.answers}

    def test_the_question_types_are_the_registrys(self) -> None:
        assert QUESTION_TYPES == jev_questions.QUESTION_TYPES

    def test_an_answer_has_the_fields_the_ledger_writes_in_its_order(self) -> None:
        """``jev_repo.record_answers`` reads these names off each answer, and a
        replay rebuilds answers from rows carrying them."""
        names = tuple(field.name for field in dataclasses.fields(ValidatedAnswer))
        assert names == jev_repo.ANSWER_FIELDS

    def test_an_answer_cannot_be_changed_once_judged(self) -> None:
        answer = _judge(_body()).answers[0]
        with pytest.raises(dataclasses.FrozenInstanceError):
            answer.valid = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Nothing raises
# ---------------------------------------------------------------------------


def _raise(*_: Any, **__: Any) -> Any:
    raise KeyError("a defect")


class TestAFailureOfTheValidatorIsNotMeasured:
    """
    The safety net, and proof it works. The corpus below requires it never to
    be needed; these require that if it is, nothing raises and nothing is
    measured.
    """

    def test_a_defect_while_judging_refuses_every_answer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(jev_validate, "_distribution", _raise)
        validation = validate_body(json.dumps(_body()), ASKED, MODEL)
        _assert_fits_the_ledger(validation)
        assert validation.status == "invalid"
        assert validation.problem is not None
        assert validation.problem.startswith("validator_error: ")
        assert "KeyError" in validation.problem
        assert [a.invalid_reason for a in validation.answers] == ["validator_error"] * 3

    def test_a_defect_reading_the_questions_refuses_everything(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(jev_validate, "_read_questions", _raise)
        validation = validate_body(json.dumps(_body()), ASKED, MODEL)
        _assert_fits_the_ledger(validation)
        assert validation.status == "invalid" and validation.answers == ()


def _slots(tree: Any) -> Iterator[tuple[Any, Any]]:
    """Every (container, key) in a decoded JSON tree, without recursion."""
    stack = [tree]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            items: Any = list(node.items())
        elif isinstance(node, list):
            items = list(enumerate(node))
        else:
            continue
        for key, value in items:
            yield node, key
            stack.append(value)


def _answer_objects(body: Any) -> list[dict[str, Any]]:
    answers = body.get("answers") if isinstance(body, dict) else None
    if not isinstance(answers, dict):
        return []
    return [answer for answer in answers.values() if isinstance(answer, dict)]


class _Fuzz:
    """
    Bodies a vendor, a proxy or a bug could send, from one seed, so a failure
    names the seed and case that caused it and reproduces.

    Most start as a clean response and are broken a few ways at once, because
    a body that is merely random is refused at the first check and exercises
    nothing after it. The rest are random JSON, garbled text, raw bytes, other
    encodings and things that are not bodies at all.
    """

    TEXTS = (
        "",
        " ",
        "noul",
        "choice",
        "score",
        "Noul",
        "risk_on",
        "neutral",
        "insufficient_evidence",
        "0",
        "1",
        "2",
        "3",
        "true",
        "model",
        "answers",
        "probabilities",
        MODEL,
        "jev-latest",
        "jev-1.14.0",
        "\x00",
        "\ud800",
        "é",
    )
    NUMBERS = (
        0,
        1,
        2,
        3,
        -1,
        0.0,
        -0.0,
        0.5,
        1.0,
        0.01,
        0.99,
        1.01,
        -0.01,
        0.34,
        1e-320,
        1e308,
        10**400,
        2**31,
        2**31 - 1,
        float("nan"),
        float("inf"),
        float("-inf"),
    )
    GARBAGE = '{}[],:"0123456789.eE-+ntrufalsNIy\\ '

    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)

    def chance(self, probability: float) -> bool:
        return self.rng.random() < probability

    def text(self) -> str:
        if self.chance(0.75):
            return self.rng.choice(self.TEXTS)
        return "".join(
            chr(self.rng.randint(1, 0x24F)) for _ in range(self.rng.randint(0, 6))
        )

    def scalar(self) -> Any:
        roll = self.rng.random()
        if roll < 0.15:
            return None
        if roll < 0.3:
            return self.chance(0.5)
        if roll < 0.55:
            return self.rng.choice(self.NUMBERS)
        if roll < 0.75:
            return round(self.rng.uniform(-0.5, 1.5), 2)
        return self.text()

    def value(self, depth: int = 0) -> Any:
        roll = self.rng.random()
        if depth >= 3 or roll < 0.6:
            return self.scalar()
        if roll < 0.8:
            return [self.value(depth + 1) for _ in range(self.rng.randint(0, 3))]
        return {
            self.text(): self.value(depth + 1) for _ in range(self.rng.randint(0, 3))
        }

    # -- the case ----------------------------------------------------------

    def case(self) -> tuple[Any, Any, Any, bool]:
        """A body, the questions it answers, the pin, and whether the
        questions are ones the rules can be written out for."""
        asked, readable = self.asked()
        clean = _clean_body(asked) if readable else _body()
        if asked is ASKED and self.chance(0.5):
            clean = _body()
        pin = MODEL
        if self.chance(0.04):
            pin = self.rng.choice(
                (None, "jev-latest", "jev-1.14.0", 1.13, "", MODEL + "\n")
            )
            if self.chance(0.5):
                # A response that echoes the refused pin, so only the
                # catalogue's refusal can refuse it.
                clean = {**clean, "model": pin}
        return self.body(clean), asked, pin, readable

    def asked(self) -> tuple[Any, bool]:
        roll = self.rng.random()
        if roll < 0.8:
            return ASKED, True
        if roll < 0.94:
            return self.rng.choice(REGISTERED), True
        if roll < 0.97:
            return self.value(), False
        broken = copy.deepcopy(ASKED)
        key = self.rng.choice(list(broken))
        broken[key] = self.rng.choice(
            (
                self.value(),
                {**broken[key], "type": self.text()},
                {**broken[key], "criteria": self.value()},
            )
        )
        return broken, False

    def body(self, clean: dict[str, Any]) -> Any:
        roll = self.rng.random()
        if roll < 0.62:
            return self.dumped(self.broken(clean))
        if roll < 0.72:
            return self.dumped(self.value())
        if roll < 0.84:
            return self.garbled(json.dumps(clean))
        if roll < 0.91:
            return self.rng.randbytes(self.rng.randint(0, 24))
        text = json.dumps(clean)
        return self.rng.choice(
            (
                None,
                0,
                1.5,
                True,
                [],
                clean,
                b"",
                bytearray(text, "utf-8"),
                memoryview(b"{}"),
                "[" * 50_000,
                '{"model": ' + "1" * 5000 + "}",
                text.encode("utf-16"),
                text.encode("utf-8-sig"),
                "\ufeff" + text,
            )
        )

    def dumped(self, value: Any) -> str | bytes:
        # allow_nan, so NaN and Infinity reach the validator as the tokens
        # Python writes; a lone surrogate reaches it escaped, or as bytes that
        # are not UTF-8.
        text = json.dumps(value, allow_nan=True, ensure_ascii=self.chance(0.5))
        if text.startswith("{") and self.chance(0.08):
            text = '{"model": ' + json.dumps(self.text()) + ", " + text[1:]
        numbers = list(NUMBER_VALUE.finditer(text))
        if numbers and self.chance(0.08):
            # Valid JSON no float holds, which json.dumps never writes.
            found = self.rng.choice(numbers)
            overflow = self.rng.choice(("1e999", "-1e999"))
            text = text[: found.start()] + overflow + text[found.end() :]
        if self.chance(0.2):
            return text.encode("utf-8", "surrogatepass")
        return text

    def garbled(self, text: str) -> str:
        chars = list(text)
        for _ in range(self.rng.randint(1, 3)):
            roll = self.rng.random()
            at = self.rng.randrange(len(chars) + 1)
            if roll < 0.3 and chars:
                del chars[min(at, len(chars) - 1)]
            elif roll < 0.6:
                chars.insert(at, self.rng.choice(self.GARBAGE))
            elif roll < 0.85 and chars:
                chars[min(at, len(chars) - 1)] = self.rng.choice(self.GARBAGE)
            else:
                chars = chars[:at]
        return "".join(chars)

    # -- breaking a clean response ----------------------------------------

    def broken(self, body: dict[str, Any]) -> Any:
        body = copy.deepcopy(body)
        breaks = [
            self._replace_anything,
            self._delete_anything,
            self._nudge_a_number,
            self._nudge_a_number,
            self._tie,
            self._repick,
            self._retype,
            self._misfile,
            self._unanswer,
            self._rekey,
            self._remodel,
            self._reusage,
            self._edge,
            self._edge,
        ]
        for _ in range(self.rng.randint(1, 3)):
            self.rng.choice(breaks)(body)
        return body

    def _replace_anything(self, body: dict[str, Any]) -> None:
        slots = list(_slots(body))
        if slots:
            container, key = self.rng.choice(slots)
            container[key] = self.value()

    def _delete_anything(self, body: dict[str, Any]) -> None:
        slots = [(c, k) for c, k in _slots(body) if isinstance(c, dict)]
        if slots:
            container, key = self.rng.choice(slots)
            del container[key]

    def _nudge_a_number(self, body: dict[str, Any]) -> None:
        slots = [
            (c, k)
            for c, k in _slots(body)
            if type(c[k]) in (int, float) and abs(c[k]) < 10
        ]
        if slots:
            container, key = self.rng.choice(slots)
            step = self.rng.choice(
                (-0.03, -0.02, -0.01, -0.005, 0.005, 0.01, 0.02, 0.5)
            )
            container[key] = round(container[key] + step, 3)

    def _tie(self, body: dict[str, Any]) -> None:
        # The top two levelled at their mean, so the sum still holds and the
        # tie is judged as a tie rather than filed under the sum.
        for answer in _answer_objects(body):
            probabilities = answer.get("probabilities")
            if isinstance(probabilities, dict):
                reals = [
                    k
                    for k, v in probabilities.items()
                    if type(v) in (int, float) and 0 <= v <= 1
                ]
                ranked = sorted(reals, key=probabilities.__getitem__, reverse=True)
                if len(ranked) >= 2:
                    pair = [Decimal(repr(float(probabilities[k]))) for k in ranked[:2]]
                    mean = float(sum(pair) / 2)
                    probabilities[ranked[0]] = probabilities[ranked[1]] = mean
                return

    def _repick(self, body: dict[str, Any]) -> None:
        for answer in _answer_objects(body):
            if "choice" in answer:
                options = list(answer.get("probabilities") or ()) or ["x"]
                answer["choice"] = (
                    self.rng.choice(options) if self.chance(0.7) else self.text()
                )
                return

    def _retype(self, body: dict[str, Any]) -> None:
        answers = _answer_objects(body)
        if answers:
            self.rng.choice(answers)["type"] = self.rng.choice(
                ("noul", "choice", "score", "Noul", None, self.text())
            )

    def _misfile(self, body: dict[str, Any]) -> None:
        answers = body.get("answers")
        if isinstance(answers, dict) and answers:
            key = self.rng.choice(list(answers))
            answers[self.rng.choice((self.text(), *ASKED))] = answers.pop(key)

    def _unanswer(self, body: dict[str, Any]) -> None:
        answers = body.get("answers")
        if isinstance(answers, dict) and answers:
            key = self.rng.choice(list(answers))
            if self.chance(0.5):
                answers[key] = None
            else:
                del answers[key]

    def _rekey(self, body: dict[str, Any]) -> None:
        for answer in _answer_objects(body):
            probabilities = answer.get("probabilities")
            if isinstance(probabilities, dict) and probabilities:
                key = self.rng.choice(list(probabilities))
                roll = self.rng.random()
                if roll < 0.4:
                    del probabilities[key]
                elif roll < 0.7:
                    probabilities[self.text()] = probabilities.pop(key)
                else:
                    probabilities[self.text()] = 0.0
                return

    def _remodel(self, body: dict[str, Any]) -> None:
        body["model"] = self.rng.choice(
            (MODEL, "jev-1.14.0", "jev-latest", None, 1, MODEL.upper(), self.text())
        )

    def _reusage(self, body: dict[str, Any]) -> None:
        body["usage"] = self.rng.choice(
            (
                None,
                {"input_tokens": True, "output_tokens": 0},
                {"input_tokens": 2**31, "output_tokens": -1},
                {"input_tokens": 1.5},
                self.value(),
            )
        )

    def _edge(self, body: dict[str, Any]) -> None:
        answers = _answer_objects(body)
        if not answers:
            return
        answer = self.rng.choice(answers)
        field = self.rng.choice(("noul", "score", "confidence", "choice"))
        answer[field] = self.rng.choice(
            (0, 1, 0.5, 2, 2.01, -0.01, 1.01, True, None, "0.5", 1e-320)
        )


REGISTERED = tuple(
    jev_questions.get(name).as_request_questions()
    for name in sorted(jev_questions.REGISTRY)
)

#: A decimal number written as an object's value, for the fuzzer to overflow.
NUMBER_VALUE = re.compile(r'(?<=": )-?\d+\.\d+')

SEEDS = range(8)
CASES_PER_SEED = 500


@functools.cache
def _corpus(seed: int) -> tuple[tuple[Any, Any, Any, bool], ...]:
    fuzz = _Fuzz(seed)
    return tuple(fuzz.case() for _ in range(CASES_PER_SEED))


# -- the rules, written out apart from the module ---------------------------


class _UnreadableError(Exception):
    """The body is not strict JSON."""


class _Pairs(list):  # type: ignore[type-arg]
    """An object's name/value pairs, as decoded, before names are checked."""


class _Constant(str):
    """``NaN``, ``Infinity`` or ``-Infinity``, as decoded."""

    __slots__ = ()


def _plain(node: Any) -> Any:
    if isinstance(node, _Constant):
        raise _UnreadableError(node)
    if isinstance(node, _Pairs):
        names = [name for name, _ in node]
        if len(names) != len(set(names)):
            raise _UnreadableError("a name given twice")
        return {name: _plain(value) for name, value in node}
    if isinstance(node, list):
        return [_plain(item) for item in node]
    return node


def _strict(raw: Any) -> Any:
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = bytes(raw).decode("utf-8")
        except UnicodeDecodeError as error:
            raise _UnreadableError from error
    if not isinstance(raw, str):
        raise _UnreadableError(type(raw).__name__)
    try:
        tree = json.loads(raw, object_pairs_hook=_Pairs, parse_constant=_Constant)
    except (ValueError, RecursionError) as error:
        raise _UnreadableError from error
    return _plain(tree)


def _is_real(value: Any) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False


def _expected_whole(
    raw: Any, asked: Mapping[str, Any], pin: Any
) -> tuple[str | None, Any]:
    """
    The reason the whole response is refused, or ``None``; and the body as
    strictly decoded, or ``None`` if it cannot be.
    """
    try:
        body = _strict(raw)
    except _UnreadableError:
        return "unparseable", None
    if type(body) is not dict:
        return "not_an_object", body
    if type(body.get("answers")) is not dict:
        return "answers_not_an_object", body
    if jev_catalogue.model_problem(pin) is not None or body.get("model") != pin:
        return "model_mismatch", body
    if all(body["answers"].get(key) is None for key in asked):
        return "no_answers", body
    return None, body


def _expected_billing(body: Any) -> tuple[Any, Any, Any, bool]:
    """What the call cost and who answered, and whether the counts are noted
    as unreadable: read from any object, whatever else is wrong with it."""
    if type(body) is not dict:
        return None, None, None, False
    model = body.get("model")
    usage = body.get("usage")
    if type(usage) is not dict:
        return (model if _storable(model) else None), None, None, True

    def count(value: Any) -> int | None:
        return value if type(value) is int and 0 <= value <= 2**31 - 1 else None

    counts = count(usage.get("input_tokens")), count(usage.get("output_tokens"))
    return (model if _storable(model) else None), *counts, None in counts


def _keys_of(question: Mapping[str, Any]) -> list[str]:
    if question["type"] == "choice":
        return list(question["criteria"])
    return [str(level) for level in range(len(question["criteria"]))]


def _expected_reason(question: Mapping[str, Any], sent: Any) -> str | None:
    """The first rule ``sent`` breaks, in the documented order, or ``None``."""
    kind = question["type"]
    if sent is None:
        return "missing"
    if type(sent) is not dict or sent.get("type") != kind:
        return "type_mismatch"
    if kind == "noul":
        noul = sent.get("noul")
        if not _is_real(noul) or not 0 <= float(noul) <= 1:
            return "noul_invalid"
        return "tie" if float(noul) == 0.5 else None
    keys = _keys_of(question)
    probabilities = sent.get("probabilities")
    if type(probabilities) is not dict or sorted(probabilities) != sorted(keys):
        return "probability_keys"
    values = list(probabilities.values())
    if not all(_is_real(v) and 0 <= float(v) <= 1 for v in values):
        return "probability_invalid"
    if abs(sum(Decimal(str(float(v))) for v in values) - 1) > Decimal("0.02"):
        return "probability_sum"
    choice = sent.get("choice")
    if kind == "choice" and (type(choice) is not str or choice not in keys):
        return "choice_not_in_criteria"
    score = sent.get("score")
    if kind == "score" and (
        not _is_real(score) or not 0 <= float(score) <= len(keys) - 1
    ):
        return "score_invalid"
    confidence = sent.get("confidence")
    if not _is_real(confidence) or not 0 <= float(confidence) <= 1:
        return "confidence_invalid"
    top = max(float(v) for v in values)
    leaders = [key for key in keys if float(probabilities[key]) == top]
    if len(leaders) != 1:
        return "tie"
    if kind == "choice" and choice != leaders[0]:
        return "choice_not_argmax"
    return None


def _assert_follows_the_rules(
    raw: Any, asked: Mapping[str, Any], pin: Any, validation: Validation, where: str
) -> None:
    whole, body = _expected_whole(raw, asked, pin)
    problem = validation.problem or ""
    model, input_tokens, output_tokens, usage_noted = _expected_billing(body)
    assert validation.model_answered == model, where
    assert (validation.input_tokens, validation.output_tokens) == (
        input_tokens,
        output_tokens,
    ), where
    assert ("usage_unreadable: " in problem) is usage_noted, (where, problem)
    if whole in (None, "no_answers"):
        unasked = [name for name in body["answers"] if name not in asked]
        assert ("unasked_answers: " in problem) is bool(unasked), (where, problem)
    else:
        assert "unasked_answers: " not in problem, (where, problem)
    if whole is not None:
        assert validation.status == "invalid", where
        assert problem.startswith(f"{whole}: "), (where, validation)
        return
    assert validation.status == "ok", (where, problem)
    assert [answer.question_key for answer in validation.answers] == list(asked), where
    for answer in validation.answers:
        question = asked[answer.question_key]
        sent = body["answers"].get(answer.question_key)
        expected = _expected_reason(question, sent)
        assert answer.invalid_reason == expected, (where, answer, sent)
        _assert_carries_what_was_sent(question, sent, answer, where)


def _real_or_none(value: Any) -> float | None:
    return float(value) if _is_real(value) else None


def _assert_carries_what_was_sent(
    question: Mapping[str, Any], sent: Any, answer: ValidatedAnswer, where: str
) -> None:
    """
    Whatever the vendor sent that is a well-formed value of its field, exactly
    as sent, and nothing else: never a value it did not send, never a stand-in
    for one it sent badly, and never an argmax or margin other than what the
    probabilities say.
    """
    if type(sent) is not dict or sent.get("type") != question["type"]:
        assert _carried(answer) == {}, (where, answer)
        return
    if question["type"] == "noul":
        assert answer.noul == _real_or_none(sent.get("noul")), where
        assert answer.confidence is None, where
        if answer.valid:
            noul = Decimal(str(answer.noul))
            assert answer.argmax == ("true" if noul > Decimal("0.5") else "false")
            assert answer.margin == float(abs(2 * noul - 1)), where
        return
    keys = _keys_of(question)
    kind = question["type"]
    assert answer.confidence == _real_or_none(sent.get("confidence")), where
    score = _real_or_none(sent.get("score")) if kind == "score" else None
    assert answer.score == score, where
    choice = sent.get("choice") if kind == "choice" else None
    assert answer.choice == (choice if _storable(choice) else None), where
    sent_probabilities = sent.get("probabilities")
    expected = None
    if type(sent_probabilities) is dict and all(
        _storable(key) and _is_real(value) for key, value in sent_probabilities.items()
    ):
        expected = {key: float(value) for key, value in sent_probabilities.items()}
    assert answer.probabilities == expected, where
    if expected is not None and sorted(expected) == sorted(keys):
        assert list(answer.probabilities or ()) == keys, where
    if answer.argmax is not None or answer.margin is not None:
        ranked = sorted((answer.probabilities or {}).values(), reverse=True)
        margin = Decimal(str(ranked[0])) - Decimal(str(ranked[1]))
        assert answer.margin == float(margin), where
        leaders = [k for k, v in (answer.probabilities or {}).items() if v == ranked[0]]
        assert answer.argmax == (leaders[0] if len(leaders) == 1 else None), where


class TestNothingRaisesOnAnyInput:
    """
    ``validate_body`` over a seeded corpus of broken, random, garbled and
    foreign bodies: it returns, it returns the same thing twice, it changes
    nothing it was given, its safety net is never what caught the case, what
    it returns fits the ledger, and — where the questions are well formed —
    its verdict on the whole and on every answer is the one the rules, written
    out independently above, give.
    """

    @pytest.mark.parametrize("seed", SEEDS)
    def test_every_verdict_follows_the_rules(self, seed: int) -> None:
        for index, (raw, asked, pin, readable) in enumerate(_corpus(seed)):
            where = f"seed {seed}, case {index}: {repr(raw)[:160]}"
            before = copy.deepcopy(asked)
            validation = validate_body(raw, asked, pin)
            assert validate_body(raw, asked, pin) == validation, where
            # In a list, so a NaN asked compares by identity: deepcopy keeps a
            # float, and NaN is not equal to itself.
            assert [asked] == [before], where
            _assert_fits_the_ledger(validation)
            assert "validator_error" not in (validation.problem or ""), where
            if readable:
                _assert_follows_the_rules(raw, asked, pin, validation, where)

    def test_the_corpus_reaches_every_rule(self) -> None:
        """
        A corpus refused at its first check would prove nothing about the
        rest. Every reason of the whole must turn up, every reason an answer
        can carry must turn up on every type it applies to, and valid answers
        of every type.
        """
        whole: set[str] = set()
        by_type: dict[str, set[str]] = {kind: set() for kind in QUESTION_TYPES}
        valid: set[str] = set()
        for seed in SEEDS:
            for raw, asked, pin, _ in _corpus(seed):
                validation = validate_body(raw, asked, pin)
                for answer in validation.answers:
                    reason = answer.invalid_reason
                    if reason is None:
                        valid.add(answer.question_type)
                    elif reason in RESPONSE_REASONS:
                        whole.add(reason)
                    else:
                        by_type[answer.question_type].add(reason)
        assert whole == set(RESPONSE_REASONS) - {"validator_error"}
        assert by_type == REASONS_BY_TYPE
        assert valid == set(QUESTION_TYPES)
