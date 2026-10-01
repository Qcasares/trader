"""
jev_catalogue.py
----------------
What the programme may send to TypeSafe AI's Jev, and how much of it. Pure data
and pure validation: no SDK, no I/O, no clock.

Its own module for the reason ``models.py`` is. The API has to show the pinned
model, the limits and the base URL, and has to validate what an operator types
into the configuration form, and it may not import ``jev_client.py`` — the one
module that holds ``typesafe_sdk``, which ``tests/unit/test_import_boundaries.py``
keeps out of every process that can move money. So the vocabulary lives here,
and this is one of the two files in the repository permitted to spell the
vendor's host.

Three facts about the vendor decide what is in here (docs/08-jev-integration.md
records the evidence for each):

* **An alias moves, and answers are compared per model.** ``jev-latest`` and
  ``jev-preview`` point at whatever TypeSafe last released. A threshold is
  measured per question set, per question and per model, so an answer given
  under an alias belongs to no model anybody could name afterwards. Only a
  versioned id in :data:`KNOWN_MODELS` is accepted, and the aliases are refused
  by name so the refusal says why.
* **The vendor's limits are published, and ours sit beneath them.** 64k tokens
  for the state plus every question, and 32k for the state plus the single
  longest one. A token count cannot be known without the vendor's tokenizer,
  so it is estimated from bytes, and the limits here leave an eighth of the
  vendor's headroom unused for the estimate to be wrong in.
* **The base URL is passed, never resolved.** The SDK reads
  ``TYPESAFE_BASE_URL`` from the environment with no host check, so one
  environment variable would send the key and every request anywhere.
  :data:`JEV_BASE_URL` is the only value ``jev_client.py`` passes.

Nothing here defaults on a caller's behalf. Each ``*_problem`` function returns
a sentence naming what is wrong rather than repairing it, exactly as
``models.settings_problem`` does, because a setting that silently corrects
itself is one an operator cannot reason about.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date
from types import MappingProxyType

#: Where Jev answers. Passed explicitly to the SDK on every construction, so
#: ``TYPESAFE_BASE_URL`` in an environment is never read. No path: the SDK
#: appends the endpoint itself.
JEV_BASE_URL = "https://api.typesafe.ai"

#: The shape of a versioned model id, ``jev-MAJOR.MINOR.PATCH``.
#:
#: ``re.ASCII`` and ``\Z`` rather than the obvious ``$``: in Python, ``$`` also
#: matches before a trailing newline, so ``"jev-1.13.0\n"`` would pass, and
#: without ``re.ASCII`` ``\d`` accepts any Unicode digit. Neither is a model id
#: the vendor issued. :func:`model_problem` also requires membership of
#: :data:`KNOWN_MODELS`, so the pattern is a second line rather than the only
#: one, but a caller that uses it alone deserves one that means what it says.
PINNED_MODEL = re.compile(r"^jev-\d+\.\d+\.\d+\Z", re.ASCII)

#: Versioned ids this repository has chosen to call. A new release is added
#: here after it has been evaluated on this repository's own labels — not typed
#: into a form — because every threshold is measured per model.
KNOWN_MODELS: tuple[str, ...] = ("jev-1.13.0",)

#: When each known model was first observed answering: the earliest day this
#: repository has evidence the model existed. TypeSafe discloses no training
#: cutoff (docs/08, fact 6), so the harness (phase C9) treats this as the
#: latest day the model could have been trained on: an item dated on or
#: before it, or not dated at all, may be in its training data, and an
#: evaluation holding one is an upper bound that carries no threshold
#: (``jev_eval``, and migration 0014's
#: ``jev_evaluations_no_threshold_on_an_upper_bound``). ``jev-1.13.0``'s is
#: the dispatch-only key check's run, which found it answering the
#: connectivity probe on 26 September 2026: a conservative bound, since the
#: model was released before it. A model added to :data:`KNOWN_MODELS`
#: without a day here fails ``tests/unit/test_jev_catalogue.py::
#: TestTheModelIsPinned::test_every_known_model_has_a_first_observation``.
MODEL_FIRST_OBSERVED: Mapping[str, date] = MappingProxyType(
    {"jev-1.13.0": date(2026, 9, 26)}
)

#: Names the docs use that do not pin a release. ``jev-latest`` tracks the
#: newest stable release and ``jev-preview`` moves ahead of it; the docs also
#: write ``jev`` and ``jev-1.13``, and whether the API accepts either is
#: unknown. Each is refused by name, so the message says "alias" rather than
#: leaving an operator to work out why a plausible id was rejected.
REFUSED_ALIASES = frozenset({"jev-latest", "jev-preview", "jev", "jev-1.13"})

#: What migration 0012 seeds ``jev_model`` with.
DEFAULT_MODEL = "jev-1.13.0"

# ---------------------------------------------------------------------------
# Limits: the vendor's, and ours beneath them
# ---------------------------------------------------------------------------

#: The vendor's documented ceilings, as of 25 September 2026. The docs say the
#: rate limits "can change without notice"; they are recorded so the margins
#: below are visibly margins rather than numbers from nowhere.
VENDOR_MAX_TOTAL_TOKENS = 64_000
VENDOR_MAX_STATE_PLUS_LONGEST_QUESTION = 32_000
VENDOR_REQUESTS_PER_MINUTE = 1_200
VENDOR_TOKENS_PER_SECOND = 250_000

#: Ours. The token limits are applied to an estimate that is deliberately high
#: for the text this repository sends (see :func:`estimate_tokens`), and the
#: gap to the vendor's figures is where an estimate that came out low still
#: lands inside the vendor's limit rather than in a 422.
MAX_TOTAL_TOKENS = 56_000
MAX_STATE_PLUS_LONGEST_QUESTION = 28_000

#: The client-side rate limiter's ceilings. Below the vendor's, so a burst the
#: limiter lets through is not one the vendor answers with a 429.
CLIENT_REQUESTS_PER_MINUTE = 1_000
CLIENT_TOKENS_PER_SECOND = 200_000

#: Bytes per token assumed by :func:`estimate_tokens`.
BYTES_PER_TOKEN_ESTIMATE = 3

#: What migration 0012 seeds ``jev_daily_request_budget`` and
#: ``jev_max_state_tokens`` with.
DEFAULT_DAILY_REQUEST_BUDGET = 500
DEFAULT_MAX_STATE_TOKENS = 8_000

#: The largest daily request budget the settings accept. Twenty times the
#: seeded 500. The budget is a spend control on a process that runs unattended,
#: and a figure above this is a typo or a loop rather than a plan; an operator
#: who needs more raises it here, in review.
MAX_DAILY_REQUEST_BUDGET = 10_000

# ---------------------------------------------------------------------------
# Vocabulary shared by the migration, the switches and the lanes
# ---------------------------------------------------------------------------

#: Every lane a request can be recorded under, in the order migration 0012's
#: CHECK constraint lists them. ``probe`` re-asks questions to measure how far
#: repeated answers move, and is excluded from every canonical use.
LANES: tuple[str, ...] = (
    "research",
    "guardrail",
    "findings",
    "ops",
    "signals",
    "decision",
    "probe",
)

#: Where a request's state came from. Only ``internal`` — computed in code from
#: this system's own rows — can ever reach the decision lane; ``web`` is what an
#: outsider can write; ``operator`` is what a person typed; and ``model`` is
#: text the programme's own generative model wrote, such as a hypothesis title
#: (migration 0013). Not ``internal``: the phase F signal loader trusts
#: ``internal``, and must never have to know that it sometimes means text a
#: model wrote. ``system`` (migration 0015, phase D) is this system's own
#: records, computed in code, which can quote an outsider — a job error's
#: skeleton, whose residue is a library's message repeating a vendor's reply —
#: so it is never ``internal`` either, and ``jev_signals`` refuses it by CHECK:
#: no answer recorded as ``system`` can rest under a signal.
PROVENANCES: tuple[str, ...] = ("web", "internal", "operator", "model", "system")

#: What a request's state describes, one per state model
#: (``jev_questions.STATE_SUBJECT``). A text subject — a web excerpt, a
#: hypothesis title — is addressed by the sha256 of its text, so a replay can
#: never answer for another subject, and a label joins its answer exactly.
SUBJECT_TYPES: tuple[str, ...] = ("probe", "session", "web_excerpt", "hypothesis_title")

#: The percent of ``jev_daily_request_budget`` each recorded lane may spend in
#: a UTC day, beside the budget itself. A probe is recorded in the probe lane
#: whatever its set, so it spends the probe slice. Code, not a setting: no
#: UPDATE can raise one, and so no lane can spend another's share — the
#: forward clock's decision slice is what stays when a research backlog has
#: spent its own. A lane with no set gets nothing until it has one. Integer
#: percents, rounded down, so a budget below :data:`MIN_DAILY_REQUEST_BUDGET`
#: would leave a lane with a share no call at all, and is refused.
#:
#: Phase D (docs/09, section 5.4) takes ten points each from research and the
#: guardrails, which at the seeded 500 still cover the README's first day, for
#: the findings and ops lanes, whose sets arrive in D2 and D3; the decision
#: lane's twenty is untouched, so no findings or ops backlog can take the
#: forward clock's calls.
LANE_BUDGET_PERCENT: Mapping[str, int] = MappingProxyType(
    {
        "research": 25,
        "guardrail": 25,
        "findings": 10,
        "ops": 10,
        "signals": 0,
        "decision": 20,
        "probe": 10,
    }
)

#: The smallest daily request budget other than zero: the least at which every
#: lane with a share gets at least one call once its share is rounded down —
#: ten, for the 10% of the findings, ops and probe lanes. A budget from one to
#: nine would leave those lanes none and, below five, the decision lane none,
#: while reading as a budget that permits calls; ``settings_problem`` refuses
#: it, so it reads as zero, which says what it does. Derived from the shares,
#: so it moves with them.
MIN_DAILY_REQUEST_BUDGET = max(
    -(-100 // share) for share in LANE_BUDGET_PERCENT.values() if share
)


def smallest_shares() -> tuple[str, ...]:
    """
    The lanes with the smallest share above none, in :data:`LANES`' order:
    the ones a budget below :data:`MIN_DAILY_REQUEST_BUDGET` leaves with no
    call first, which ``settings_problem``'s refusal names. Read from the
    table, so the refusal names whichever lanes the shares make smallest.
    """
    least = min(share for share in LANE_BUDGET_PERCENT.values() if share)
    return tuple(lane for lane in LANES if LANE_BUDGET_PERCENT[lane] == least)


def _listed(names: Sequence[str]) -> str:
    """``names`` as prose: "a", "a and b", "a, b and c"."""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]

#: The operator's area switches, one ``jev_area_<area>`` flag each.
AREAS: tuple[str, ...] = (
    "research",
    "ops",
    "findings",
    "guardrails",
    "signals",
    "decisions",
)

#: Which area switch gates each lane. The probe lane answers to ``jev_enabled``
#: alone: it measures the vendor, not an area's work, and it is the check that
#: a key and a pinned model work at all before any area is switched on.
LANE_AREA: dict[str, str | None] = {
    "research": "research",
    "guardrail": "guardrails",
    "findings": "findings",
    "ops": "ops",
    "signals": "signals",
    "decision": "decisions",
    "probe": None,
}


def estimate_tokens(text: str) -> int:
    """
    A token count for ``text`` that errs high: one token per three ASCII bytes,
    and one for every byte of anything else.

    A subword tokenizer spends about four characters of English prose on a
    token, so three ASCII bytes to a token over-counts prose by about a third.
    Anything outside ASCII is charged the byte-level worst case, a token a
    byte: the vendor's tokenizer is undisclosed, its training language is
    English, and byte-level vocabularies spend up to a token per byte on
    non-Latin scripts — three times what counting them at three bytes would
    allow, far past the margin between :data:`MAX_TOTAL_TOKENS` and the
    vendor's limit. What this still does not bound is ASCII built from short,
    unusual runs, such as long digit strings; the decision lane sends labels
    rather than figures for that reason among others. Never less than a third
    of the UTF-8 bytes, so it can only have grown from what it was.
    """
    if not isinstance(text, str):
        raise TypeError(f"estimate_tokens takes text, got {type(text).__name__}")
    size = len(text.encode("utf-8"))
    ascii_bytes = len(text.encode("ascii", "ignore"))
    # Integer ceiling: float division loses exactness long before a request
    # this large would be sent, but there is no reason to find out where.
    return -(-ascii_bytes // BYTES_PER_TOKEN_ESTIMATE) + (size - ascii_bytes)


def model_problem(model: object) -> str | None:
    """
    Why ``model`` may not be requested, or ``None`` if it may.

    ``None`` only for a string in :data:`KNOWN_MODELS`. An alias is refused by
    name, whatever its case or surrounding whitespace, so the reason reaches the
    operator as "that is an alias" rather than as an unrecognised id.
    """
    if not isinstance(model, str):
        return f"the Jev model must be a string, got {model!r}"
    if model.strip().lower() in REFUSED_ALIASES:
        return (
            f"{model!r} is an alias, and aliases are refused: the model behind "
            "one changes whenever TypeSafe releases, with no change here, and "
            "every threshold is measured per model. Pin a versioned id from "
            f"{list(KNOWN_MODELS)}"
        )
    if PINNED_MODEL.match(model) is None:
        return (
            f"{model!r} is not a pinned model id; a pinned id has the form "
            f"jev-MAJOR.MINOR.PATCH, one of {list(KNOWN_MODELS)}"
        )
    if model not in KNOWN_MODELS:
        return (
            f"{model!r} is not in the catalogue {list(KNOWN_MODELS)}. A new "
            "release is added to jev_catalogue.KNOWN_MODELS once it has been "
            "evaluated on this repository's labels, because a threshold "
            "measured on one model says nothing about another"
        )
    return None


def _count_problem(name: str, value: object, ceiling: int) -> str | None:
    """Why ``value`` is not a whole number from 0 to ``ceiling``, or ``None``."""
    if isinstance(value, bool) or not isinstance(value, int):
        # `True` is an int in Python and is not a count. The same quiet
        # wrongness `models.settings_problem` refuses for max_tokens.
        return f"{name} must be an integer, got {value!r}"
    if value < 0:
        return f"{name} must be zero or more, got {value}"
    if value > ceiling:
        return f"{name} must be at most {ceiling}, got {value}"
    return None


def request_size_problem(
    state_json: str,
    question_jsons: Mapping[str, str],
    max_state_tokens: int,
) -> str | None:
    """
    Why a request of this size may not be sent, or ``None`` if it may.

    ``state_json`` is the state as it will be serialised and ``question_jsons``
    each question's serialised form, keyed by question name. The names are not
    counted: the vendor does not send them to the model.

    Three limits, each on the estimate: the state against the operator's
    ``jev_max_state_tokens``, the state plus the longest question against
    :data:`MAX_STATE_PLUS_LONGEST_QUESTION`, and the state plus every question
    against :data:`MAX_TOTAL_TOKENS`. A state limit of zero, or anything that is
    not a positive integer, refuses every request: it is what the switch reads
    as when the stored setting cannot be read, and a limit that cannot be read
    does not permit a request of any size.
    """
    if (
        isinstance(max_state_tokens, bool)
        or not isinstance(max_state_tokens, int)
        or max_state_tokens <= 0
    ):
        return (
            f"the state limit is {max_state_tokens!r}; every request is refused "
            "until jev_max_state_tokens is a positive integer"
        )
    if not question_jsons:
        return "a request needs at least one question"

    state_tokens = estimate_tokens(state_json)
    if state_tokens > max_state_tokens:
        return (
            f"the state is about {state_tokens} tokens, over the "
            f"{max_state_tokens} allowed by jev_max_state_tokens"
        )

    sizes = {key: estimate_tokens(text) for key, text in question_jsons.items()}
    longest = max(sizes, key=sizes.__getitem__)
    if state_tokens + sizes[longest] > MAX_STATE_PLUS_LONGEST_QUESTION:
        return (
            f"the state and question {longest!r} come to about "
            f"{state_tokens + sizes[longest]} tokens, over the "
            f"{MAX_STATE_PLUS_LONGEST_QUESTION} allowed for the state plus the "
            f"longest question (the vendor's limit is "
            f"{VENDOR_MAX_STATE_PLUS_LONGEST_QUESTION})"
        )
    total = state_tokens + sum(sizes.values())
    if total > MAX_TOTAL_TOKENS:
        return (
            f"the state and {len(sizes)} questions come to about {total} "
            f"tokens, over the {MAX_TOTAL_TOKENS} allowed in total (the "
            f"vendor's limit is {VENDOR_MAX_TOTAL_TOKENS})"
        )
    return None


def settings_problem(
    model: object, daily_budget: object, max_state_tokens: object
) -> str | None:
    """
    Why these Jev settings cannot be used, or ``None`` if they can.

    One function, so the configuration form's refusal and the runner's read
    apply the same rule. Validating at the form and trusting the row at the
    runner is how a value refused by the form still reaches a request, because
    a row can be written by something other than the form.

    Zero is a legal budget and a legal state limit. Each means "make no calls",
    which is a setting an operator may choose on purpose; it is also what the
    switches read as when the stored value cannot be read. A budget from one to
    ``MIN_DAILY_REQUEST_BUDGET - 1`` is not: each lane spends at most its
    share, rounded down, and such a budget leaves some lane none while looking
    like one that permits calls.
    """
    problem = model_problem(model)
    if problem is not None:
        return problem
    problem = _count_problem(
        "jev_daily_request_budget", daily_budget, MAX_DAILY_REQUEST_BUDGET
    )
    if problem is not None:
        return problem
    # An integer by now: _count_problem refused anything else.
    if isinstance(daily_budget, int) and 0 < daily_budget < MIN_DAILY_REQUEST_BUDGET:
        smallest = smallest_shares()
        named = (
            f"the {_listed(smallest)} lane's share"
            if len(smallest) == 1
            else f"the {_listed(smallest)} lanes' shares"
        )
        return (
            f"jev_daily_request_budget must be 0, for no calls, or at least "
            f"{MIN_DAILY_REQUEST_BUDGET}, got {daily_budget}: each lane spends at "
            "most its share of the budget, rounded down, and below "
            f"{MIN_DAILY_REQUEST_BUDGET} {named} would be none"
        )
    # A state larger than the sub-limit could never be sent with any question
    # at all, so the sub-limit is a fact about the vendor, not a policy here.
    return _count_problem(
        "jev_max_state_tokens", max_state_tokens, MAX_STATE_PLUS_LONGEST_QUESTION
    )


def lane_budget(daily_budget: int, lane: str) -> int:
    """
    How many calls ``lane`` may make in a UTC day under ``daily_budget``: its
    :data:`LANE_BUDGET_PERCENT` of the budget, rounded down.

    Rounded down, never up, so the slices together never exceed the budget and
    a small budget floors them: at a budget of 9 a 10% share — the findings,
    ops and probe lanes' — is none, which is why :func:`settings_problem`
    refuses any budget from one to :data:`MIN_DAILY_REQUEST_BUDGET` less one.
    A lane outside the vocabulary is a :class:`ValueError`, not a slice of
    nothing: the schema refuses to record one, so asking is a caller's defect.
    """
    if lane not in LANE_BUDGET_PERCENT:
        raise ValueError(f"{lane!r} is not a lane; the lanes are {list(LANES)}")
    if isinstance(daily_budget, bool) or not isinstance(daily_budget, int):
        raise TypeError(f"a daily budget is a count of calls, got {daily_budget!r}")
    if daily_budget <= 0:
        return 0
    return daily_budget * LANE_BUDGET_PERCENT[lane] // 100


__all__ = [
    "AREAS",
    "BYTES_PER_TOKEN_ESTIMATE",
    "CLIENT_REQUESTS_PER_MINUTE",
    "CLIENT_TOKENS_PER_SECOND",
    "DEFAULT_DAILY_REQUEST_BUDGET",
    "DEFAULT_MAX_STATE_TOKENS",
    "DEFAULT_MODEL",
    "JEV_BASE_URL",
    "KNOWN_MODELS",
    "LANES",
    "LANE_AREA",
    "LANE_BUDGET_PERCENT",
    "MAX_DAILY_REQUEST_BUDGET",
    "MAX_STATE_PLUS_LONGEST_QUESTION",
    "MAX_TOTAL_TOKENS",
    "MIN_DAILY_REQUEST_BUDGET",
    "MODEL_FIRST_OBSERVED",
    "PINNED_MODEL",
    "PROVENANCES",
    "REFUSED_ALIASES",
    "SUBJECT_TYPES",
    "VENDOR_MAX_STATE_PLUS_LONGEST_QUESTION",
    "VENDOR_MAX_TOTAL_TOKENS",
    "VENDOR_REQUESTS_PER_MINUTE",
    "VENDOR_TOKENS_PER_SECOND",
    "estimate_tokens",
    "lane_budget",
    "model_problem",
    "request_size_problem",
    "settings_problem",
    "smallest_shares",
]
