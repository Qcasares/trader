"""
jev_validate.py
---------------
Whether what Jev sent back answers what was asked, answer by answer, and what
each answer measured. Pure: no SDK, no I/O, no clock. It never raises.

The SDK parses responses too, and its parse is not one a threshold can stand
on (docs/08-jev-integration.md, fact 3). On its untyped path ``answers``
defaults to ``{}``, so a 200 carrying no answers parses cleanly; an answer of a
type it does not model is dropped with a log line; probabilities and
``confidence`` are never range-checked, the maintainer's view being that the
API already guarantees them; and its decoder, like Python's, reads ``NaN`` and
``Infinity``, which are not JSON, and hands a ``NaN`` Noul to a strict model
that accepts it. So the lane gives this module the raw body, as text, and every
rule is applied here, reading the vendor's contract strictly wherever its own
descriptions disagree.

Three decisions carry the weight.

* **Judged whole, then answer by answer.** A body that is not strict JSON, is
  not an object, has no ``answers`` object, names a model other than the pin,
  or answers none of the questions asked is not a response to this request. It
  is refused whole: status ``invalid``, and every answer carries the one
  reason. The ledger holds only ``ok`` rows as canonical, so a refused
  response can be asked again. A body that is sound as a whole and gets one
  answer wrong is ``ok``, with that answer invalid: it is what the pinned model
  said, it is recorded once and replayed, and asking again would not check it —
  it would be a second answer with an equal claim to be right.

* **The argmax is ours.** On ``jev-1.13.0``, ``choice`` is sometimes not the
  most probable option: exactly 0.01 below another, in near-ties at low
  confidence (SDK issue #15). The most probable option is recomputed here from
  the probabilities. An answer whose choice disagrees with it, or whose
  probabilities have no single maximum, is an abstention. Both the vendor's
  choice and ours are kept, so the disagreement can be counted.

* **Invalid means not measured.** Every question asked gets exactly one
  :class:`ValidatedAnswer`, in the order asked. An invalid one carries its
  reason, from :data:`REASONS`, and is consumed downstream as not measured —
  never as 0, never as a default, never as the vendor's choice. What the
  vendor sent is kept on it wherever it is a well-formed value of its field,
  because an answer that failed is still a fact about the model; the verbatim
  body is on the request row either way.

Numbers are compared as the decimals the vendor wrote, not their binary
approximations, wherever the difference can decide a rule. In binary,
``1.02 - 1`` exceeds 0.02, so three probabilities of 0.34 would fail a tolerance
they meet exactly; and ``0.7 - 0.2`` is 0.49999999999999994, a margin that
would fall short of a threshold of 0.5 it meets.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Context, Decimal, localcontext
from types import MappingProxyType
from typing import Any, Literal

from src.programme import jev_catalogue

# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

#: The question types an answer can be judged against: the three migration
#: 0012's CHECK constraint and ``jev_questions`` name.
QUESTION_TYPES: tuple[str, ...] = ("noul", "choice", "score")

#: A Choice's or a Score's probabilities must sum to 1 within this, inclusive.
#: Values have been observed on a 0.01 grid, which TypeSafe does not document,
#: and rounding each option to it moves a sum by up to 0.005 an option: inside
#: the tolerance for the four options the regime set asks, and not necessarily
#: for a Score of ten levels, which is a reason to measure one before asking it.
PROBABILITY_SUM_TOLERANCE = Decimal("0.02")

#: The largest count the ledger's INT token columns hold. A count beyond it is
#: not one anybody was billed for, and writing it would fail the insert that
#: records the call.
MAX_TOKEN_COUNT = 2**31 - 1

#: Why a whole response is refused, in the order the checks run. Every answer
#: in a refused response carries the reason, and its status is ``invalid``.
RESPONSE_REASONS: Mapping[str, str] = MappingProxyType(
    {
        "bad_question": (
            "a question as asked cannot be checked, so no answer to it can be; "
            "a defect in the caller, not in the response"
        ),
        "unparseable": (
            "there is no body, or it is not strict JSON: not UTF-8, NaN or "
            "Infinity, a name given twice in one object, or not JSON at all"
        ),
        "not_an_object": "the body is JSON but not an object",
        "answers_not_an_object": "`answers` is absent or is not an object",
        "model_mismatch": (
            "`model` is not the pinned model, or the pin is not one the "
            "catalogue accepts"
        ),
        "no_answers": "none of the questions asked has an answer",
        "validator_error": (
            "this module failed on the body, a defect here and never expected; "
            "nothing in the response is measured"
        ),
    }
)

#: Why one answer is refused, in the order the rules are applied: the first
#: that fails is the one recorded. ``tie`` and ``choice_not_argmax`` are the
#: model's own answers, declined as abstentions; the rest are malformations.
ANSWER_REASONS: Mapping[str, str] = MappingProxyType(
    {
        "missing": "there is no answer under the key asked, or it is null",
        "type_mismatch": "the answer is not an object of the type asked",
        "noul_invalid": "`noul` is not a real number from 0 to 1",
        "probability_keys": (
            "`probabilities` is not an object keyed by exactly the options "
            'asked (Choice) or the levels "0" to "n-1" (Score)'
        ),
        "probability_invalid": "a probability is not a real number from 0 to 1",
        "probability_sum": "the probabilities do not sum to 1 within 0.02",
        "choice_not_in_criteria": "`choice` is not one of the options asked",
        "score_invalid": "`score` is not a real number from 0 to the top level",
        "confidence_invalid": "`confidence` is not a real number from 0 to 1",
        "tie": "no single option is most probable; for a Noul, exactly 0.5",
        "choice_not_argmax": (
            "`choice` is not the most probable option (SDK issue #15)"
        ),
    }
)

#: Every ``invalid_reason`` an answer can carry, and what it means.
REASONS: Mapping[str, str] = MappingProxyType({**RESPONSE_REASONS, **ANSWER_REASONS})

#: Exact for any sum of probabilities in any digit that could decide the
#: tolerance, whatever decimal context the calling thread has set.
_DECIMAL = Context(prec=64)

#: How much of a value the vendor controls is quoted in a note.
_SHOWN_CHARS = 60

#: How many unasked answers a note names before counting the rest.
_SHOWN_NAMES = 5

# ---------------------------------------------------------------------------
# What comes out
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidatedAnswer:
    """
    One question's answer, as the ledger records it in ``jev_answers``.

    ``valid`` is the field a consumer reads first. When it is false the answer
    is not measured, whatever else it holds: the other fields are what the
    vendor sent, kept for the record wherever each is a well-formed value of
    its field, and ``invalid_reason`` names the rule that failed.

    ``argmax`` and ``margin`` are this system's, recomputed rather than read:
    from the probabilities, the most probable option and its lead over the
    second; for a Noul, ``"true"`` above 0.5 and ``"false"`` below it, with a
    margin of ``|2p - 1|``. Both are ``None`` when the distribution failed a
    rule, and ``argmax`` is ``None`` on a tie. ``confidence`` is always ``None``
    for a Noul, which has none, so a number there would be one the vendor was
    never asked for. Where it exists it measures how concentrated the
    probabilities are, not how likely the answer is to be right.

    ``probabilities`` is a plain dict, as the ledger's writer takes it, and a
    fresh one on every validation.
    """

    question_key: str
    question_type: str
    noul: float | None
    choice: str | None
    score: float | None
    probabilities: dict[str, float] | None
    confidence: float | None
    argmax: str | None
    margin: float | None
    valid: bool
    invalid_reason: str | None


@dataclass(frozen=True)
class Validation:
    """
    A whole response, judged.

    ``status`` is ``"ok"`` when the response is sound as a whole — strict JSON,
    an object, an ``answers`` object, the pinned model, and an answer to at
    least one question asked — and ``"invalid"`` when it is not, in which case
    every answer carries the reason. ``ok`` says nothing about any one answer;
    each says that for itself.

    ``answers`` holds exactly one answer per question asked, in the order
    asked, whatever order or keys the vendor used. ``problem`` is ``None``, or
    notes of the form ``"<code>: <detail>"`` joined by ``"; "``: the reason the
    whole was refused, if it was; ``unasked_answers``, naming answers to
    questions nobody asked, which are ignored; ``usage_unreadable``, when the
    token counts are not counts. ``model_answered`` and the counts are read
    whenever the body is an object, refused or not: the call was made and
    billed either way.
    """

    status: Literal["ok", "invalid"]
    problem: str | None
    model_answered: str | None
    answers: tuple[ValidatedAnswer, ...]
    input_tokens: int | None
    output_tokens: int | None


# ---------------------------------------------------------------------------
# The judgement
# ---------------------------------------------------------------------------


def validate_body(
    raw_body: str | bytes | None,
    asked: Mapping[str, dict],
    pinned_model: str,
) -> Validation:
    """
    Judge ``raw_body`` as the answer to ``asked``, sent to ``pinned_model``.

    ``asked`` is the questions exactly as sent and in the order sent — what
    ``QuestionSet.as_request_questions()`` returns — and ``pinned_model`` the
    id the request carried.

    Never raises, whatever it is given. The lane has a call to record whatever
    came back, and an exception here would lose the record of a call that was
    made and billed. So a body breaking every rule comes back ``invalid``, and
    should this module itself fail on some body, that is caught too and every
    answer refused with ``validator_error``: not measured, which is the only
    safe reading of an answer nobody could check. The property test in
    ``tests/unit/test_jev_validate.py`` requires that it never happens.
    """
    try:
        return _validate(raw_body, asked, pinned_model)
    except Exception as error:
        return _failed(asked, error)


def _validate(raw_body: object, asked: object, pinned_model: object) -> Validation:
    questions, question_problem = _read_questions(asked)
    body, parse_problem = _parse(raw_body)
    # Read before any refusal: the call was made and billed either way, and
    # which model answered is worth knowing most when it was not the pin.
    seen, notes = _billed(body)

    if question_problem is not None:
        return _refused(questions, "bad_question", question_problem, notes, **seen)
    if parse_problem is not None:
        return _refused(questions, "unparseable", parse_problem)
    if not isinstance(body, dict):
        return _refused(questions, "not_an_object", f"the body is a JSON {_kind(body)}")

    model = body.get("model")
    answers = body.get("answers")
    if not isinstance(answers, dict):
        found = "absent" if answers is None else f"a JSON {_kind(answers)}"
        return _refused(
            questions, "answers_not_an_object", f"`answers` is {found}", notes, **seen
        )
    # The pin is checked as well as compared. A caller that pinned an alias
    # would otherwise accept an answer that echoed it, and an answer given
    # under an alias belongs to no model anybody could name afterwards.
    pin_problem = jev_catalogue.model_problem(pinned_model)
    if pin_problem is not None:
        detail = f"the pin is refused: {pin_problem}"
        return _refused(questions, "model_mismatch", detail, notes, **seen)
    if model != pinned_model:
        named = "names no model" if model is None else f"names {_shown(model)}"
        detail = f"the response {named}; the request pinned {pinned_model!r}"
        return _refused(questions, "model_mismatch", detail, notes, **seen)

    asked_keys = {question.key for question in questions}
    unasked = [name for name in answers if name not in asked_keys]
    if unasked:
        notes.insert(0, _unasked_note(unasked))
    # Nothing under any key asked is not an answer to this request, whatever
    # else the object holds. Refused whole rather than recorded as ``ok`` with
    # every answer missing, which the ledger would hold as canonical and
    # replay as unanswerable for good.
    if all(answers.get(question.key) is None for question in questions):
        detail = f"none of the questions asked ({len(questions)}) has an answer"
        return _refused(questions, "no_answers", detail, notes, **seen)

    return Validation(
        status="ok",
        problem="; ".join(notes) or None,
        answers=tuple(_answer(q, answers.get(q.key)) for q in questions),
        **seen,
    )


def _answer(question: _Question, raw: object) -> ValidatedAnswer:
    if raw is None:
        return _judged(question, reason="missing")
    if not isinstance(raw, dict) or raw.get("type") != question.kind:
        # An answer of another type is an answer to another question. Nothing
        # it holds is carried: none of it means what this question's fields do.
        return _judged(question, reason="type_mismatch")
    if question.kind == "noul":
        return _noul(question, raw)
    return _distribution(question, raw)


def _noul(question: _Question, raw: dict[str, Any]) -> ValidatedAnswer:
    # Whatever the body says about confidence is not read. A Noul has none,
    # and the ledger refuses one on a Noul row.
    value = _real(raw.get("noul"))
    if value is None or not 0.0 <= value <= 1.0:
        return _judged(question, noul=value, reason="noul_invalid")
    with localcontext(_DECIMAL):
        margin = float(abs(2 * _decimal(value) - 1))
    if value == 0.5:
        return _judged(question, noul=value, margin=margin, reason="tie")
    argmax = "true" if value > 0.5 else "false"
    return _judged(question, noul=value, argmax=argmax, margin=margin)


def _distribution(question: _Question, raw: dict[str, Any]) -> ValidatedAnswer:
    """A Choice or a Score: a distribution over what was asked, and a pick."""
    options = question.options
    sent = raw.get("probabilities")
    probabilities = _carried_probabilities(sent, options)
    confidence = _real(raw.get("confidence"))
    choice = _text(raw.get("choice")) if question.kind == "choice" else None
    score = _real(raw.get("score")) if question.kind == "score" else None

    reason: str | None = None
    argmax: str | None = None
    margin: float | None = None
    # Keys as a set: the options' order is frozen in what was asked, and the
    # vendor's order in the answer means nothing.
    if not isinstance(sent, dict) or set(sent) != set(options):
        reason = "probability_keys"
    elif probabilities is None or not all(_in_unit(p) for p in probabilities.values()):
        reason = "probability_invalid"
    elif not _sums_to_one(probabilities.values()):
        reason = "probability_sum"
    else:
        argmax, margin = _most_probable(probabilities, options)

    if reason is None and question.kind == "choice" and choice not in options:
        reason = "choice_not_in_criteria"
    if reason is None and question.kind == "score":
        # The score is the probability-weighted mean of levels 0 to n-1, so it
        # can fall between levels but never outside them.
        if score is None or not 0.0 <= score <= len(options) - 1:
            reason = "score_invalid"
    if reason is None and not _in_unit(confidence):
        reason = "confidence_invalid"
    if reason is None and argmax is None:
        reason = "tie"
    if reason is None and question.kind == "choice" and choice != argmax:
        reason = "choice_not_argmax"
    return _judged(
        question,
        choice=choice,
        score=score,
        probabilities=probabilities,
        confidence=confidence,
        argmax=argmax,
        margin=margin,
        reason=reason,
    )


def _most_probable(
    probabilities: Mapping[str, float], options: tuple[str, ...]
) -> tuple[str | None, float]:
    """
    The single most probable option, or ``None`` on a tie, and the lead of the
    most probable value over the next, as the decimals written. A tie is exact
    equality: values are compared as the floats stored, which are ordered as
    the decimals the vendor wrote are.
    """
    first, second = sorted(probabilities.values(), reverse=True)[:2]
    leaders = [option for option in options if probabilities[option] == first]
    with localcontext(_DECIMAL):
        margin = float(_decimal(first) - _decimal(second))
    return (leaders[0] if len(leaders) == 1 else None), margin


def _sums_to_one(values: Iterable[float]) -> bool:
    with localcontext(_DECIMAL):
        total = sum((_decimal(value) for value in values), Decimal(0))
        return abs(total - 1) <= PROBABILITY_SUM_TOLERANCE


def _carried_probabilities(
    sent: object, options: tuple[str, ...]
) -> dict[str, float] | None:
    """
    ``sent``, for the record, if it is an object of real numbers under text
    keys the ledger can store; ``None`` if it is not.

    In the order asked when its keys are the options asked, so a record reads
    the same way round whatever order the vendor used; otherwise as sent.
    """
    if not isinstance(sent, dict):
        return None
    carried: dict[str, float] = {}
    for name, value in sent.items():
        text, number = _text(name), _real(value)
        if text is None or number is None:
            return None
        carried[text] = number
    if set(carried) == set(options):
        return {option: carried[option] for option in options}
    return carried


def _judged(
    question: _Question,
    *,
    noul: float | None = None,
    choice: str | None = None,
    score: float | None = None,
    probabilities: dict[str, float] | None = None,
    confidence: float | None = None,
    argmax: str | None = None,
    margin: float | None = None,
    reason: str | None = None,
) -> ValidatedAnswer:
    # Validity is decided in one place: an answer is valid exactly when no
    # rule gave a reason to refuse it.
    return ValidatedAnswer(
        question_key=question.key,
        question_type=question.kind,
        noul=noul,
        choice=choice,
        score=score,
        probabilities=probabilities,
        confidence=confidence,
        argmax=argmax,
        margin=margin,
        valid=reason is None,
        invalid_reason=reason,
    )


def _refused(
    questions: list[_Question],
    reason: str,
    detail: str,
    notes: Iterable[str] = (),
    *,
    model_answered: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> Validation:
    """The whole response refused: every answer carries ``reason``."""
    return Validation(
        status="invalid",
        problem="; ".join([f"{reason}: {detail}", *notes]),
        model_answered=model_answered,
        answers=tuple(_judged(question, reason=reason) for question in questions),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _failed(asked: object, error: Exception) -> Validation:
    """What :func:`validate_body` returns if :func:`_validate` itself raised."""
    try:
        questions, _ = _read_questions(asked)
    except Exception:
        questions = []
    return _refused(
        questions,
        "validator_error",
        f"validation raised {type(error).__name__}, a defect in jev_validate",
    )


# ---------------------------------------------------------------------------
# The questions as asked
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Question:
    key: str
    kind: str
    #: The keys the answer's probabilities must have, exactly: a Choice's
    #: options in the order asked, or a Score's levels "0" to "n-1". Empty for
    #: a Noul.
    options: tuple[str, ...] = ()


def _read_questions(asked: object) -> tuple[list[_Question], str | None]:
    """
    The questions as asked, and ``None``; or as much as could be read of them,
    and why they cannot be checked against.

    A question the registry would refuse never reaches the vendor, whose SDK
    validates it first, so a problem here is a caller's defect. It refuses the
    whole response rather than one answer, because a request built wrongly is
    not one whose other answers anybody should trust either.
    """
    if not isinstance(asked, Mapping):
        return [], f"the questions asked are a {type(asked).__name__}, not a mapping"
    questions: list[_Question] = []
    problem: str | None = None
    for key, question in asked.items():
        read, why = _read_question(key, question)
        questions.append(read)
        problem = problem or why
    if not questions:
        problem = "no question was asked"
    return questions, problem


def _read_question(key: object, question: object) -> tuple[_Question, str | None]:
    kind = question.get("type") if isinstance(question, Mapping) else None
    shown = _shown(key)
    unread = _Question(
        key if isinstance(key, str) else str(key),
        kind if isinstance(kind, str) else "",
    )
    if _text(key) is None:
        # JSON answers only under text keys, and the ledger records each answer
        # under its key, so one it cannot store would fail that write.
        return unread, f"question key {shown} is not text the ledger can store"
    if not isinstance(question, Mapping):
        return unread, f"question {shown} is a {type(question).__name__}, not a mapping"
    if kind not in QUESTION_TYPES:
        return unread, f"question {shown} has type {_shown(kind)}"
    if kind == "noul":
        return _Question(key, kind), None
    # A margin is the lead over the second option, so each needs two. The
    # registry asks more of a question (jev_questions); this is only what
    # judging an answer needs.
    criteria = question.get("criteria")
    if kind == "choice":
        if (
            isinstance(criteria, Mapping)
            and len(criteria) >= 2
            and all(isinstance(option, str) for option in criteria)
        ):
            return _Question(key, kind, tuple(criteria)), None
        return unread, f"Choice {shown} needs criteria naming two or more options"
    if isinstance(criteria, (list, tuple)) and len(criteria) >= 2:
        return _Question(key, kind, tuple(str(i) for i in range(len(criteria)))), None
    return unread, f"Score {shown} needs criteria listing two or more levels"


# ---------------------------------------------------------------------------
# Reading the body
# ---------------------------------------------------------------------------


class _NotStrictJSONError(ValueError):
    """Raised by the decoder's hooks for text Python's json would accept."""


def _parse(raw_body: object) -> tuple[Any, str | None]:
    """
    The body decoded as strict JSON, and ``None``; or ``None``, and why not.

    Stricter than :func:`json.loads` in three ways (RFC 8259 is the standard):

    * ``NaN``, ``Infinity`` and ``-Infinity`` are not JSON numbers.
    * A name given twice in one object is refused, not resolved. RFC 8259 calls
      what a reader does with one unpredictable, so the answer recorded would
      depend on who read the body; Python keeps the last.
    * Bytes must be UTF-8. ``json.loads`` would also guess UTF-16 and UTF-32.

    A body nested past the recursion limit is refused like any other text that
    cannot be read: ``json`` raises :class:`RecursionError` for it, not a
    ``ValueError``.
    """
    if raw_body is None:
        return None, "there is no body"
    if isinstance(raw_body, (bytes, bytearray)):
        try:
            text = bytes(raw_body).decode("utf-8")
        except UnicodeDecodeError as error:
            return None, f"the body is not UTF-8 ({error.reason} at byte {error.start})"
    elif isinstance(raw_body, str):
        text = raw_body
    else:
        return None, f"the body is a {type(raw_body).__name__}, not text"
    try:
        body = json.loads(
            text, parse_constant=_refuse_constant, object_pairs_hook=_unique_names
        )
    except _NotStrictJSONError as error:
        return None, f"the body is not strict JSON: {error}"
    except (ValueError, RecursionError) as error:
        return None, f"the body is not JSON ({_shown(str(error))})"
    return body, None


def _refuse_constant(name: str) -> Any:
    raise _NotStrictJSONError(f"{name} is not a JSON number")


def _unique_names(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    decoded: dict[str, Any] = {}
    for name, value in pairs:
        if name in decoded:
            raise _NotStrictJSONError(f"an object gives the name {_shown(name)} twice")
        decoded[name] = value
    return decoded


def _billed(body: object) -> tuple[dict[str, Any], list[str]]:
    """
    Which model answered and what it counted, as ``Validation`` fields, with a
    note if the counts are unreadable. Nothing, when the body is not an object.
    """
    if not isinstance(body, dict):
        return {}, []
    input_tokens, output_tokens, usage_note = _usage(body.get("usage"))
    seen = {
        "model_answered": _text(body.get("model")),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
    return seen, [usage_note] if usage_note is not None else []


def _usage(usage: object) -> tuple[int | None, int | None, str | None]:
    if not isinstance(usage, dict):
        return None, None, "usage_unreadable: the response has no usage object"
    input_tokens = _count(usage.get("input_tokens"))
    output_tokens = _count(usage.get("output_tokens"))
    unread = [
        name
        for name, count in (
            ("input_tokens", input_tokens),
            ("output_tokens", output_tokens),
        )
        if count is None
    ]
    if not unread:
        return input_tokens, output_tokens, None
    return (
        input_tokens,
        output_tokens,
        f"usage_unreadable: {' and '.join(unread)} not a count from 0 to "
        f"{MAX_TOKEN_COUNT}",
    )


def _unasked_note(unasked: list[str]) -> str:
    named = ", ".join(_shown(name) for name in unasked[:_SHOWN_NAMES])
    rest = len(unasked) - _SHOWN_NAMES
    more = f" and {rest} more" if rest > 0 else ""
    return f"unasked_answers: ignored answers to questions not asked: {named}{more}"


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------


def _real(value: object) -> float | None:
    """
    ``value`` as a float if it is a finite real number, else ``None``.

    JSON has one kind of number, so an integer serves as well as a float. A
    boolean does not, though Python says ``True == 1``: ``true`` where a
    probability belongs is a malformed answer, not a certainty. Nor does an
    integer too large for a float, or a literal that overflows to infinity —
    ``1e999`` is valid JSON, and not a finite number.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _in_unit(value: float | None) -> bool:
    return value is not None and 0.0 <= value <= 1.0


def _decimal(value: float) -> Decimal:
    """
    The decimal the vendor wrote, recovered from the float it became: the
    shortest decimal that rounds to it, which is what ``repr`` gives.
    """
    return Decimal(repr(value))


def _count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= MAX_TOKEN_COUNT else None


def _text(value: object) -> str | None:
    """
    ``value`` if it is text the ledger can store, else ``None``.

    Postgres stores neither NUL nor an unpaired surrogate, in ``text`` or in
    ``jsonb``, and JSON can spell both (``\\u0000``, ``\\ud800``). One carried
    onto an answer would fail the write recording a call that was made and
    billed, so it is not carried; the verbatim body still holds it.
    """
    if not isinstance(value, str) or "\x00" in value:
        return None
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return None
    return value


def _shown(value: object) -> str:
    """``value`` quoted for a note, short: the vendor chooses how long it is."""
    text = repr(value)
    if len(text) <= _SHOWN_CHARS:
        return text
    return text[: _SHOWN_CHARS - 3] + "..."


def _kind(value: object) -> str:
    """What JSON calls the kind of a decoded value."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


__all__ = [
    "ANSWER_REASONS",
    "MAX_TOKEN_COUNT",
    "PROBABILITY_SUM_TOLERANCE",
    "QUESTION_TYPES",
    "REASONS",
    "RESPONSE_REASONS",
    "ValidatedAnswer",
    "Validation",
    "validate_body",
]
