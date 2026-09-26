"""
jev_questions.py
----------------
The questions the programme may put to Jev, as versioned, hashed sets, and the
shape of the state each one is asked about. Pure data and pure validation: no
SDK, no I/O, no clock.

A question set is the unit everything downstream is measured in. A threshold
is per set, per question and per model (docs/08-jev-integration.md, fact 5); a
stored answer is joined to its set by the pack hash; an evaluation is of one
version. So a set is frozen three ways:

* **Its words.** Every registered set has a golden hash in
  :data:`GOLDEN_PACK_HASHES`, and a test compares them. Changing one character
  of an instruction or a criterion without bumping the version fails the build,
  because otherwise answers to the old words would be pooled with answers to
  the new ones, and every threshold measured on the pool would describe a
  question nobody asks any more.
* **Its option order.** The hash is taken without ``sort_keys``, because order
  is part of what the model reads. A pre-registered study found moving an
  option from first to last shifted one ambiguous task by 3.5 points; freezing
  the order is cheap insurance, not a response to a large measured effect.
* **Its state.** Each set names the pydantic model its state must be an
  instance of. For the regime set the descriptors' definitions — the windows
  and the bucket edges — are written into the instructions from the constants
  below, which ``jev_features.py`` computes with, and written exactly: a band
  moved from 1% to 1.2% changes the words. So changing a window changes the
  hash, and the golden test fails until the version is bumped: the definition
  of the state is hashed with the question.

Every Choice carries exactly one escape option, last. Jev always answers: an
independent study had a cake recipe classed as a technical issue at 0.94, and
flagged none of 30 out-of-scope messages until it was given somewhere else to
put them, when it flagged 21. An escape option helps; it does not solve the
problem, which is why an escape answer is consumed downstream as a hold. Last
in every set, so the escape's position is one thing fewer that differs when two
sets' answers are compared.

The words follow what the vendor documents about how Jev reads: literally, and
weakly through indirection. So a question is written plainly and positively —
it is answered exactly as written, and a negation misread is an answer
inverted — and it names each state field it refers to by its backticked path,
``equities.trend``, as TypeSafe's own guidance does, rather than by a
description the model would have to resolve.

The decision lane's state is enumerated, and nothing else. No dates, no
sessions, no tickers, no free text and no exact figures: the model holds world
knowledge with no disclosed cutoff, and a date, a ticker or a precise return is
a fingerprint of the day it describes, which lets a model recall what happened
next instead of judging what it was shown. :func:`state_model_problem` refuses
a decision-lane state model that could carry any of them, at registration.

The API may import this module to show the catalogue of questions. It holds no
client and names no host, so it can.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Any, Literal, get_args, get_origin

from pydantic import BaseModel, ConfigDict, field_validator

from src.programme import jev_catalogue

# ---------------------------------------------------------------------------
# Rules a question set is held to
# ---------------------------------------------------------------------------

QUESTION_TYPES: tuple[str, ...] = ("noul", "choice", "score")

#: The escape options a Choice may carry. Exactly one, and last.
ESCAPE_OPTIONS: tuple[str, ...] = ("none_of_these", "insufficient_evidence", "unclear")

#: Limits the vendor's prose documentation states and its OpenAPI spec does
#: not encode. Where the two disagree the stricter reading is enforced here,
#: before a request is ever built, rather than discovered as a 422.
MAX_CHOICE_OPTIONS = 255
MIN_SCORE_LEVELS = 2
MAX_SCORE_LEVELS = 10

#: A Choice needs this many options besides its escape. With one, it is a Noul
#: asked in a more expensive shape.
MIN_CHOICE_OPTIONS = 2

#: Lanes whose state must be enumerated: every field a Literal, a boolean or a
#: model built from them. The decision lane because its answers are the only
#: ones that could ever reach an order; the probe lane because its state is a
#: fixed sentence and a probe carrying anything else is not a probe.
ENUMERATED_LANES = frozenset({"decision", "probe"})

#: Lanes whose enumerated values must also look like labels, not like data.
LABELLED_LANES = frozenset({"decision"})

#: The largest integer a decision-lane label may be. Ordinals such as a
#: quintile fit; a four-digit number reads as a year.
MAX_ENUMERATED_INT = 100

_SET_NAME = re.compile(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*")
_KEY = re.compile(r"[a-z][a-z0-9_]{0,63}")
_LABEL = re.compile(r"[a-z][a-z0-9_]*")
_QUESTION_FIELDS = frozenset({"type", "instructions", "criteria"})
_NOUL_CRITERIA = frozenset({"true", "false"})

# ---------------------------------------------------------------------------
# The regime descriptors: their vocabulary and their definitions
# ---------------------------------------------------------------------------

#: The sleeves a regime state describes, in the order it lists them. Generic
#: labels: which instrument stands for each is the caller's choice and never
#: enters the state.
SLEEVES: tuple[str, ...] = ("equities", "bonds", "commodities")

Trend = Literal["above", "near", "below"]
VolatilityQuintile = Literal[1, 2, 3, 4, 5]
Drawdown = Literal["none", "shallow", "deep", "severe"]
Momentum = Literal["up", "flat", "down"]

#: Trend: the latest close against its simple average over this many sessions,
#: "near" when within this fraction of it either side, inclusive.
TREND_AVERAGE_SESSIONS = 200
TREND_NEAR_BAND = 0.01

#: Volatility: the standard deviation of this many daily log returns, ranked
#: within the same measure's own last ``VOLATILITY_HISTORY_SESSIONS`` values.
VOLATILITY_SESSIONS = 20
VOLATILITY_HISTORY_SESSIONS = 1260

#: Drawdown: the fall from the highest close of this many sessions. Below
#: ``DRAWDOWN_SHALLOW`` is "none"; from it to below ``DRAWDOWN_DEEP`` is
#: "shallow"; from ``DRAWDOWN_DEEP`` to ``DRAWDOWN_SEVERE`` inclusive is "deep";
#: anything larger is "severe".
DRAWDOWN_HIGH_SESSIONS = 252
DRAWDOWN_SHALLOW = 0.02
DRAWDOWN_DEEP = 0.10
DRAWDOWN_SEVERE = 0.20

#: Momentum: the return over this many sessions, "flat" when its size is
#: strictly less than this fraction.
MOMENTUM_SESSIONS = 63
MOMENTUM_FLAT_BAND = 0.01

#: Every state model shares this configuration. ``extra="forbid"`` because a key
#: nobody declared is a field nobody reviewed; ``frozen`` because the state that
#: was hashed must be the state that was sent; ``strict`` because a lax boolean
#: reads 1, "true" and "yes" as True, and a boolean is the one field type the
#: enumerated lanes allow besides a Literal. A Literal compares by equality in
#: either mode — ``True`` passes as 1 — which is why the quintile has a
#: validator of its own.
_STATE_CONFIG = ConfigDict(extra="forbid", frozen=True, strict=True)


class SleeveState(BaseModel):
    """Four enumerated descriptors of one sleeve, computed in ``jev_features``."""

    model_config = _STATE_CONFIG

    trend: Trend
    volatility_quintile: VolatilityQuintile
    drawdown: Drawdown
    momentum: Momentum

    @field_validator("volatility_quintile", mode="before")
    @classmethod
    def _a_quintile_is_an_integer(cls, value: object) -> object:
        # pydantic compares Literal members by equality, so True passes as 1
        # and 3.0 as 3, even in strict mode. Neither is a quintile, and a bool
        # arriving here means a caller computed the wrong thing.
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"a quintile is an integer from 1 to 5, got {value!r}")
        return value


class RegimeState(BaseModel):
    """
    The decision lane's state: one :class:`SleeveState` per sleeve, nothing else.

    Built only by ``jev_features.regime_state``. There is no field for the
    session, the symbols or any figure, and :func:`state_model_problem` refuses
    one if it is added.
    """

    model_config = _STATE_CONFIG

    equities: SleeveState
    bonds: SleeveState
    commodities: SleeveState


#: The probe's fixed, trivially true state.
PROBE_TEXT = "The sun rises in the east."


class ProbeState(BaseModel):
    """
    The connectivity probe's state: one fixed sentence, and nothing else.

    A Literal with a default, so ``ProbeState()`` is the only state there is.
    ``validate_default`` makes a default that drifted from the Literal an error
    at construction rather than a silently different probe.
    """

    model_config = ConfigDict(**_STATE_CONFIG, validate_default=True)

    text: Literal[PROBE_TEXT] = PROBE_TEXT


# ---------------------------------------------------------------------------
# The question set
# ---------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class QuestionSet:
    """
    A named, versioned set of questions, and the state they are asked about.

    ``questions`` is an ordered tuple of ``(key, question)`` pairs, each
    question the plain dict the vendor accepts. Key order and option order are
    part of the set. The dicts are deep-copied on the way in, so a literal the
    caller still holds cannot change a set after it is built, and
    :meth:`as_request_questions` deep-copies on the way out, so a request
    cannot change the set it was built from.
    """

    name: str
    version: int
    lane: str
    provenance: str
    questions: tuple[tuple[str, dict], ...]
    state_model: type[BaseModel]
    purpose: str

    def __post_init__(self) -> None:
        if isinstance(self.questions, Mapping):
            # Iterating a mapping yields its keys, and a two-letter key unpacks
            # into a (key, question) pair of single characters. Refused by
            # name rather than left to surface as a baffling registration error.
            raise TypeError(
                "questions is an ordered tuple of (key, question) pairs, not a "
                "mapping: the order is part of the set"
            )
        pairs = tuple(
            (key, copy.deepcopy(question)) for key, question in self.questions
        )
        object.__setattr__(self, "questions", pairs)

    def __eq__(self, other: object) -> bool:
        # Not the generated equality. That compares the question dicts, and dict
        # equality ignores order — {"a": 1, "b": 2} == {"b": 2, "a": 1} — so two
        # sets presenting the same options in different orders compared equal
        # while hashing differently. Order is part of a set, so equality is
        # decided on the ordered serialisation the pack hash is taken of.
        if not isinstance(other, QuestionSet):
            return NotImplemented
        return (
            self.pack_hash == other.pack_hash
            and self.state_model is other.state_model
            and self.purpose == other.purpose
        )

    def __hash__(self) -> int:
        # Equal sets have equal pack hashes, so this agrees with __eq__. The
        # generated hash would have hashed the question dicts, which have none,
        # and raised.
        return hash(self.pack_hash)

    def as_request_questions(self) -> dict[str, dict]:
        """The questions as the SDK takes them: a fresh copy, in order."""
        return {key: copy.deepcopy(question) for key, question in self.questions}

    def dump_state(self, state: BaseModel) -> dict[str, Any]:
        """
        ``state`` as it is sent, ``model_dump(mode="json")``, if it may be.

        Only an instance of exactly :attr:`state_model`. ``isinstance`` would
        admit a subclass, and a subclass can add a computed field that the
        dump then sends: a ``RegimeState`` subclass with an ``as_of`` property
        passes ``isinstance`` and puts a date in the decision lane's state,
        past every check :func:`state_model_problem` made of the class that
        was registered. :class:`TypeError` otherwise.

        What would be sent is read back through the model from its JSON, as a
        stored state would be, so an instance built with ``model_construct``,
        which skips validation, cannot send a value its fields forbid. From
        the JSON rather than the dict because a strict model reads a date only
        from JSON text, and a research lane's state may carry one.
        """
        if type(state) is not self.state_model:
            raise TypeError(
                f"{self.name} takes a {self.state_model.__name__}, exactly; got "
                f"{type(state).__name__}"
            )
        dumped = state.model_dump(mode="json")
        self.state_model.model_validate_json(json.dumps(dumped, ensure_ascii=False))
        return dumped

    @property
    def pack_hash(self) -> str:
        """
        sha256 of the set's identity and its exact words, in their order.

        ``json.dumps`` without ``sort_keys``: sorting would make two sets that
        present their options in different orders hash alike, and the order is
        part of what the model reads. ``purpose`` and ``state_model`` are not
        hashed — the first is prose for people, and the second's meaning is
        carried by the instructions that describe it. Computed on every read
        rather than cached, so it always describes the words a request built
        from this set would carry.
        """
        payload = {
            "name": self.name,
            "version": self.version,
            "lane": self.lane,
            "provenance": self.provenance,
            "questions": [[key, question] for key, question in self.questions],
        }
        text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @property
    def escape_options(self) -> dict[str, str]:
        """For every Choice question, the key of its escape option."""
        found: dict[str, str] = {}
        for key, question in self.questions:
            if question.get("type") != "choice":
                continue
            escapes = [o for o in question.get("criteria", {}) if o in ESCAPE_OPTIONS]
            if len(escapes) != 1:
                raise ValueError(
                    f"question {key!r} of {self.name!r} carries escape options "
                    f"{escapes}; a registered Choice carries exactly one"
                )
            found[key] = escapes[0]
        return found


# ---------------------------------------------------------------------------
# Validation, applied at registration
# ---------------------------------------------------------------------------


def _text_problem(value: object, what: str) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return f"{what} must be non-empty text, got {value!r}"
    if value != value.strip():
        return f"{what} has leading or trailing whitespace"
    return None


def _choice_problem(where: str, criteria: object) -> str | None:
    if not isinstance(criteria, dict) or not criteria:
        return f"{where} needs criteria mapping each option to its description"
    for option, description in criteria.items():
        if not isinstance(option, str) or _KEY.fullmatch(option) is None:
            return f"{where} has option {option!r}; an option is a lowercase key"
        problem = _text_problem(description, f"{where}'s option {option!r}")
        if problem is not None:
            return problem
    escapes = [option for option in criteria if option in ESCAPE_OPTIONS]
    if len(escapes) != 1:
        return (
            f"{where} carries escape options {escapes}; a Choice carries exactly "
            f"one of {list(ESCAPE_OPTIONS)}, because Jev always answers and, "
            "without somewhere to put 'none of these', puts it somewhere wrong"
        )
    if list(criteria)[-1] != escapes[0]:
        return f"{where}'s escape option {escapes[0]!r} must be its last option"
    if len(criteria) - 1 < MIN_CHOICE_OPTIONS:
        return (
            f"{where} needs at least {MIN_CHOICE_OPTIONS} options besides its "
            "escape; with one it is a Noul"
        )
    if len(criteria) > MAX_CHOICE_OPTIONS:
        return (
            f"{where} has {len(criteria)} options; the vendor's documentation "
            f"allows at most {MAX_CHOICE_OPTIONS}"
        )
    return None


def _score_problem(where: str, criteria: object) -> str | None:
    if not isinstance(criteria, list):
        return f"{where} needs criteria listing its levels, lowest first"
    if not MIN_SCORE_LEVELS <= len(criteria) <= MAX_SCORE_LEVELS:
        return (
            f"{where} has {len(criteria)} levels; the vendor's documentation "
            f"allows {MIN_SCORE_LEVELS} to {MAX_SCORE_LEVELS}"
        )
    for index, level in enumerate(criteria):
        problem = _text_problem(level, f"{where}'s level {index}")
        if problem is not None:
            return problem
    return None


def _noul_problem(where: str, question: dict) -> str | None:
    if "criteria" not in question:
        return None
    criteria = question["criteria"]
    if not isinstance(criteria, dict) or not criteria:
        return f"{where} has criteria {criteria!r}; omit them or describe true/false"
    unknown = set(criteria) - _NOUL_CRITERIA
    if unknown:
        return f"{where}'s criteria name {sorted(unknown)}; a Noul has true and false"
    for outcome, description in criteria.items():
        problem = _text_problem(description, f"{where}'s {outcome!r} criterion")
        if problem is not None:
            return problem
    return None


def _question_problem(key: str, question: object) -> str | None:
    where = f"question {key!r}"
    if not isinstance(question, dict):
        return f"{where} must be a dict, got {type(question).__name__}"
    kind = question.get("type")
    if kind not in QUESTION_TYPES:
        return f"{where} has type {kind!r}; one of {list(QUESTION_TYPES)}"
    unknown = set(question) - _QUESTION_FIELDS
    if unknown:
        return f"{where} has fields {sorted(unknown)} the vendor does not define"
    # The OpenAPI spec makes instructions optional; the prose documentation
    # requires them. The stricter reading wins.
    problem = _text_problem(question.get("instructions"), f"{where}'s instructions")
    if problem is not None:
        return problem
    if kind == "noul":
        return _noul_problem(where, question)
    if kind == "choice":
        return _choice_problem(where, question.get("criteria"))
    return _score_problem(where, question.get("criteria"))


def _config_problem(model: type[BaseModel], path: str) -> str | None:
    config = model.model_config
    if config.get("extra") != "forbid":
        return (
            f"{path} must forbid extra fields: a key nobody declared in a state "
            "is a field nobody reviewed"
        )
    if config.get("frozen") is not True:
        return f"{path} must be frozen: the state that was hashed is the one sent"
    return None


def _serialisation_problem(model: type[BaseModel], path: str) -> str | None:
    """
    Why ``model`` could send what its fields do not declare, or ``None``.

    A state goes to the vendor as ``model_dump(mode="json")``, and pydantic has
    two sanctioned ways to put into that dump what no field annotation shows: a
    computed field adds a key, and a serializer replaces a value. Either would
    carry a date past a check that reads annotations — a serializer does not
    even appear in the model's JSON schema — so an enumerated lane refuses both
    outright rather than trying to read what they return.
    """
    if model.model_computed_fields:
        return (
            f"{path} has computed fields {sorted(model.model_computed_fields)}; "
            "a computed field is sent like a field and declared like none"
        )
    decorators = model.__pydantic_decorators__
    if decorators.field_serializers or decorators.model_serializers:
        return (
            f"{path} has a serializer, which can send a value its fields do not declare"
        )
    return None


def _describe(annotation: object) -> str:
    return getattr(annotation, "__name__", None) or repr(annotation)


def _literal_value_problem(value: object, path: str, labelled: bool) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        if labelled and _LABEL.fullmatch(value) is None:
            return (
                f"{path} allows {value!r}; a decision-lane value is a lowercase "
                "word, which keeps dates, tickers and sentences out of the state"
            )
        return None
    if isinstance(value, int):
        if labelled and not 0 <= value <= MAX_ENUMERATED_INT:
            return (
                f"{path} allows {value}; a decision-lane number is an ordinal "
                f"from 0 to {MAX_ENUMERATED_INT}, and a four-digit one is a year"
            )
        return None
    return (
        f"{path} allows {value!r}, a {type(value).__name__}; an enumerated value "
        "is a string, an integer or a boolean"
    )


def _enumerated_problem(
    annotation: object, path: str, labelled: bool, seen: set[type]
) -> str | None:
    origin = get_origin(annotation)
    if origin is Annotated:
        return _enumerated_problem(get_args(annotation)[0], path, labelled, seen)
    if origin is Literal:
        for value in get_args(annotation):
            problem = _literal_value_problem(value, path, labelled)
            if problem is not None:
                return problem
        return None
    if annotation is bool:
        return None
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _model_problem(annotation, path, labelled, seen)
    return (
        f"{path} is {_describe(annotation)}, which is not enumerated: this lane's "
        "state holds Literal values, booleans and models built from them, and "
        "nothing that can carry free text, a date or an exact figure"
    )


def _model_problem(
    model: type[BaseModel], path: str, labelled: bool, seen: set[type]
) -> str | None:
    if model in seen:
        return None
    seen.add(model)
    problem = _config_problem(model, path) or _serialisation_problem(model, path)
    if problem is not None:
        return problem
    for name, field in model.model_fields.items():
        problem = _enumerated_problem(
            field.annotation, f"{path}.{name}", labelled, seen
        )
        if problem is not None:
            return problem
    return None


def state_model_problem(state_model: object, lane: str) -> str | None:
    """
    Why ``state_model`` may not carry this lane's state, or ``None``.

    Every state model forbids extra fields and is frozen. In the enumerated
    lanes every field, however deeply nested, is a Literal, a boolean or a
    model built from them; ``Optional``, containers, ``str``, numbers and dates
    are refused, because each can carry what an enumeration cannot, and so are
    computed fields and serializers, which send what no field declares. In the
    decision lane every Literal value must also look like a label — a lowercase
    word, or a small integer — so an enumeration of dates or tickers is refused
    too.

    It reads shapes, not meanings. A ticker spelled as a lowercase word is a
    label to it, and a reviewer is the control for that.
    """
    if not (isinstance(state_model, type) and issubclass(state_model, BaseModel)):
        return f"the state model must be a pydantic model class, got {state_model!r}"
    if lane not in ENUMERATED_LANES:
        return _config_problem(state_model, state_model.__name__)
    return _model_problem(
        state_model, state_model.__name__, lane in LABELLED_LANES, set()
    )


def question_set_problem(question_set: QuestionSet) -> str | None:
    """
    Why ``question_set`` may not be registered, or ``None`` if it may.

    The vendor's prose limits, the escape rule, the lane and provenance
    vocabulary, the size of the questions alone, and the state model. A
    decision-lane set takes internal provenance only: its state is computed in
    code from this system's own rows, which is what keeps text an outsider can
    write away from an order (C-1 in docs/02-security-audit.md).
    """
    qs = question_set
    if not isinstance(qs.name, str) or _SET_NAME.fullmatch(qs.name) is None:
        return f"set name {qs.name!r} must look like 'lane.subject'"
    if isinstance(qs.version, bool) or not isinstance(qs.version, int):
        return f"version must be an integer, got {qs.version!r}"
    if qs.version < 1:
        return f"version must be 1 or more, got {qs.version}"
    if qs.lane not in jev_catalogue.LANES:
        return f"lane {qs.lane!r} is not one of {list(jev_catalogue.LANES)}"
    if qs.provenance not in jev_catalogue.PROVENANCES:
        return (
            f"provenance {qs.provenance!r} is not one of "
            f"{list(jev_catalogue.PROVENANCES)}"
        )
    if qs.lane == "decision" and qs.provenance != "internal":
        return (
            f"a decision-lane set takes internal provenance only, not "
            f"{qs.provenance!r}: its state must be computed in code, where no "
            "outsider can write it"
        )
    problem = _text_problem(qs.purpose, "purpose")
    if problem is not None:
        return problem
    if not qs.questions:
        return "a set needs at least one question"

    keys = [key for key, _ in qs.questions]
    for key in keys:
        if not isinstance(key, str) or _KEY.fullmatch(key) is None:
            return f"question key {key!r} must be a lowercase key"
    if len(set(keys)) != len(keys):
        return f"question keys repeat: {keys}"
    for key, question in qs.questions:
        problem = _question_problem(key, question)
        if problem is not None:
            return problem

    # The questions alone, against a state of nothing. A set that fails this
    # could never be sent with any state at all.
    sizes = {key: json.dumps(q, ensure_ascii=False) for key, q in qs.questions}
    problem = jev_catalogue.request_size_problem(
        "", sizes, jev_catalogue.MAX_STATE_PLUS_LONGEST_QUESTION
    )
    if problem is not None:
        return problem

    return state_model_problem(qs.state_model, qs.lane)


# ---------------------------------------------------------------------------
# The sets
# ---------------------------------------------------------------------------


def _percent(fraction: float) -> str:
    """
    ``fraction`` as a percentage, exactly: 0.01 is "1%" and 0.012 is "1.2%".

    Exact rather than rounded, because this rendering is what puts a bucket
    edge inside the pack hash. ``f"{0.012:.0%}"`` is "1%", so a band moved from
    1% to 1.2% would have changed what ``jev_features`` computes while leaving
    the question's words, and so its hash, exactly as they were. Read from the
    float's shortest ``repr``, so the text is the number the code holds.
    """
    if not isinstance(fraction, float):
        raise TypeError(f"a bucket edge is a float, got {fraction!r}")
    digits = format(Decimal(repr(fraction)).scaleb(2).normalize(), "f")
    return f"{digits}%"


def _paths(fields: tuple[str, ...]) -> str:
    """State field names as backticked paths, listed in prose."""
    named = [f"`{field}`" for field in fields]
    return ", ".join(named[:-1]) + " and " + named[-1]


#: The regime question's instructions: the question, then what each descriptor
#: means. Plain and positive, since it is answered exactly as written, and each
#: field named by its backticked path. The legend is rendered from the
#: constants ``jev_features`` computes with, which is what puts the state's
#: definition inside the hash.
_REGIME_INSTRUCTIONS = (
    "Which market regime do these descriptors show? The state describes the "
    f"asset classes {_paths(SLEEVES)}, each with the same descriptors, "
    "computed from adjusted daily closing prices. `trend` compares the latest "
    f"close with the average close of the last {TREND_AVERAGE_SESSIONS} trading "
    f'days: "above", "near" (within {_percent(TREND_NEAR_BAND)}) or "below". '
    "`volatility_quintile` ranks the volatility of the last "
    f"{VOLATILITY_SESSIONS} daily returns against its own history over the last "
    f"{VOLATILITY_HISTORY_SESSIONS:,} trading days, from 1 (the calmest fifth) "
    "to 5 (the most turbulent fifth). `drawdown` is the fall from the highest "
    f"close of the last {DRAWDOWN_HIGH_SESSIONS} trading days: "
    f'"none" (under {_percent(DRAWDOWN_SHALLOW)}), '
    f'"shallow" ({_percent(DRAWDOWN_SHALLOW)} to {_percent(DRAWDOWN_DEEP)}), '
    f'"deep" ({_percent(DRAWDOWN_DEEP)} to {_percent(DRAWDOWN_SEVERE)}) or '
    f'"severe" (over {_percent(DRAWDOWN_SEVERE)}). `momentum` is the direction '
    f"of the return over the last {MOMENTUM_SESSIONS} trading days: "
    f'"up", "flat" (a move smaller than {_percent(MOMENTUM_FLAT_BAND)} either '
    'way) or "down".'
)

#: The regimes, in their frozen order, escape last. Each regime names every
#: descriptor it depends on by path, and no two of them can hold at once:
#: risk_on and neutral disagree on equities' trend or momentum, and risk_off
#: needs a drawdown the other two exclude. So a state fits one regime or none,
#: and a state that fits none is one whose descriptors pull apart. The escape
#: is described as exactly that, because that is the state in which an
#: allocator should hold.
_REGIME_CRITERIA: dict[str, str] = {
    "risk_on": (
        'Investors are taking on risk: `equities.trend` is "above", '
        '`equities.momentum` is "up", `equities.drawdown` is "none" or '
        '"shallow", `equities.volatility_quintile` is 1, 2 or 3, and '
        '`commodities.momentum` is "up" or "flat".'
    ),
    "neutral": (
        "The market is calm and moving sideways: `equities.trend` is "
        '"near" or `equities.momentum` is "flat", `equities.drawdown` is '
        '"none" or "shallow", and `equities.volatility_quintile` is 2, 3 or 4.'
    ),
    "risk_off": (
        'Investors are seeking safety: `equities.trend` is "below", '
        '`equities.momentum` is "down", `equities.drawdown` is "deep" or '
        '"severe", `equities.volatility_quintile` is 4 or 5, and '
        '`bonds.momentum` is "up" or "flat".'
    ),
    "insufficient_evidence": (
        "The descriptors conflict: some fit one regime and others fit another. "
        'For example, `equities.trend` is "above" while `equities.drawdown` is '
        '"deep", or `equities.momentum` and `bonds.momentum` are both "down". '
        "Choose this option whenever the descriptors point in different "
        "directions."
    ),
}

REGISTRY: dict[str, QuestionSet] = {}


def _register(question_set: QuestionSet) -> QuestionSet:
    problem = question_set_problem(question_set)
    if problem is not None:
        raise ValueError(
            f"question set {question_set.name!r} v{question_set.version} is "
            f"refused: {problem}"
        )
    if question_set.name in REGISTRY:
        raise ValueError(f"question set {question_set.name!r} is registered twice")
    REGISTRY[question_set.name] = question_set
    return question_set


PROBE_CONNECTIVITY = _register(
    QuestionSet(
        name="probe.connectivity",
        version=1,
        lane="probe",
        provenance="internal",
        questions=(
            (
                "about_the_sun",
                {
                    "type": "noul",
                    "instructions": "Is the sentence in `text` about the sun?",
                },
            ),
        ),
        state_model=ProbeState,
        purpose=(
            "Proves that a key, the pinned model and the response validator "
            "work end to end, on a fixed state whose answer is known. The "
            "handler for the jev_probe job; excluded from every canonical use."
        ),
    )
)

DECISION_REGIME = _register(
    QuestionSet(
        name="decision.regime",
        version=1,
        lane="decision",
        provenance="internal",
        questions=(
            (
                "regime",
                {
                    "type": "choice",
                    "instructions": _REGIME_INSTRUCTIONS,
                    "criteria": _REGIME_CRITERIA,
                },
            ),
        ),
        state_model=RegimeState,
        purpose=(
            "Classifies the market regime from code-computed descriptors of "
            "three asset-class sleeves. Recorded going forward; nothing "
            "consumes it until the Rule 5 amendment in docs/08 is in force, "
            "and a missing, invalid or escape answer then means hold."
        ),
    )
)

#: The pack hash of every registered set, pinned. A test requires each
#: registered set to hash to its entry and every entry to be registered, so
#: editing a set's words without bumping its version fails the build, and so
#: does bumping the version without recording the new hash here.
GOLDEN_PACK_HASHES: dict[tuple[str, int], str] = {
    ("probe.connectivity", 1): (
        "5d5d091e936ae7b0a2006d2d2a92f90c7a08b0bbe55453550ef2c08c2370560e"
    ),
    ("decision.regime", 1): (
        "7b79d2419f7fdd25bdd1c6ce4442820d1a6e57a94b67d26787a37aaaf04eb52e"
    ),
}


def get(name: str) -> QuestionSet:
    """The registered set called ``name``. :class:`KeyError` if there is none."""
    try:
        return REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"no question set {name!r}; registered: {sorted(REGISTRY)}"
        ) from None


__all__ = [
    "DECISION_REGIME",
    "DRAWDOWN_DEEP",
    "DRAWDOWN_HIGH_SESSIONS",
    "DRAWDOWN_SEVERE",
    "DRAWDOWN_SHALLOW",
    "ENUMERATED_LANES",
    "ESCAPE_OPTIONS",
    "GOLDEN_PACK_HASHES",
    "LABELLED_LANES",
    "MAX_CHOICE_OPTIONS",
    "MAX_ENUMERATED_INT",
    "MAX_SCORE_LEVELS",
    "MIN_CHOICE_OPTIONS",
    "MIN_SCORE_LEVELS",
    "MOMENTUM_FLAT_BAND",
    "MOMENTUM_SESSIONS",
    "PROBE_CONNECTIVITY",
    "PROBE_TEXT",
    "QUESTION_TYPES",
    "REGISTRY",
    "SLEEVES",
    "TREND_AVERAGE_SESSIONS",
    "TREND_NEAR_BAND",
    "VOLATILITY_HISTORY_SESSIONS",
    "VOLATILITY_SESSIONS",
    "Drawdown",
    "Momentum",
    "ProbeState",
    "QuestionSet",
    "RegimeState",
    "SleeveState",
    "Trend",
    "VolatilityQuintile",
    "get",
    "question_set_problem",
    "state_model_problem",
]
