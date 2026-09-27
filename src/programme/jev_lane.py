"""
jev_lane.py
-----------
The programme's one road to TypeSafe AI's Jev: gate, pin, hash, look up, call
once, validate, write. The only other road is ``jev_check``, the operator's
key check, by dispatch and recording nothing; ``tests/unit/test_jev_lane.py``
holds ``jev_client`` to those two importers.

Runner-only: it calls ``jev_client``, which holds TypeSafe's SDK, and
``tests/unit/test_import_boundaries.py`` keeps both out of every process that
can move money, the API included. Every lane asks Jev through :func:`ask`, so
the rules below are applied once rather than remembered by every lane.

Record once, replay forever
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Jev is not deterministic. There is no seed, no temperature and no idempotency
key, and byte-identical requests have been seen to flip a label
(docs/08-jev-integration.md, fact 1). So an answer is an event that happened
once, not a function that can be called again to check it. Every request is
hashed — the pinned model, the state with its keys sorted, and the questions
in the order asked, options included — and before anything is sent the ledger
is asked whether that exact request already has an ``ok`` answer. If it does,
the answer is read back and nothing is sent: a second call would not confirm
the first, it would be a second answer with an equal claim to be right. The
unique index ``jev_requests_canonical`` makes the rule the database's as well
as this module's.

A probe is the exception, deliberately. It asks again on purpose, to measure
how far repeated answers move, so it never replays and is never replayed: its
rows are written in the ``probe`` lane, which the canonical index leaves out.

The road, not its callers, holds the rules
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Every rule a lane could forget is applied here, on every ask, so a lane added
later — a planner, a harness, a job nobody has written yet — cannot forget it.
The loops that call this still read their own switches; the road no longer
depends on them having done so.

What each step does, and what it writes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
In order, the first that applies decides:

0. **The arguments**, before any switch is read, so a caller's mistake shows
   while Jev is off: the registered set, exactly its state model, a subject
   that is the state model's own subject type, and, for text, the sha256 of
   exactly the text sent (a session is an ISO date). Raises; writes nothing.
1. **Switched off** — ``programme_enabled``, ``jev_enabled``, the area switch
   for the set's own lane, and for a set that carries this system's detail
   ``jev_send_internal_detail``: each read by its own fail-closed reader, none
   derived from another. ``disabled``; nothing is written. A switch that is off
   is a standing state, not an event per request, and a ledger that grew a row
   for every question a lane did not ask would bury the ones it did.
2. **No usable model** — ``jev_model`` reads as ``None``. ``refused_model``,
   and nothing is written, because nothing honest can be: every row names the
   model it requested, and there is none to name.
3. **The web gate**, for a web set. Text quarantined under any source is
   ``quarantined``. Text without a valid, clear answer from the registered
   injection screen under the pin is ``unscreened`` — for every web set but the
   screen itself, probes included, and before any replay, so a stored answer
   about text that has since been quarantined is not read back either. With no
   screen registered, or none of the screen's shape, every web ask is
   unscreened: the gate fails closed.
4. **Content blocked** — a call about exactly this text was answered with a
   content block, so it is not sent again, by any set, a probe of one
   included, and nor is an answer about it read back. ``content_blocked``.
   Text only — a web excerpt or a hypothesis title, the states a content
   filter could object to. An enumerated state is labels computed in code, a
   403 page about one is likelier an edge's than a verdict on its content,
   and holding it for good would take that state out of the forward clock,
   so it is held by nothing: its failure is recorded, and it is asked again.
5. **Replayed** — the canonical answer exists. Nothing is written or sent. A
   canonical row recorded by another pack raises before anything is sent: no
   answer crosses from one question set to another (open item 15).
6. **No key.** ``no_key``. A replay needs no key, which is why the key is asked
   for only after the ledger has been.
7. **The vendor's standing refusals** — an authentication failure recorded
   since 00:00 UTC is ``auth_held``, in every lane, the connectivity probe's
   included, however the key has changed since; a 422 recorded for this set,
   version and model is ``set_refused`` until a new version. After the replay
   and the key, because they exist to stop calls and those make none.
8. **Over budget** — the calls made today have reached
   ``jev_daily_request_budget``, or the recorded lane's slice of it
   (``jev_catalogue.LANE_BUDGET_PERCENT``). A ``refused_budget`` row, and no
   call.
9. **Too large** — :func:`jev_catalogue.request_size_problem` refuses it under
   ``jev_max_state_tokens``. A ``refused_limits`` row, and no call.

Steps 8 and 9 are written because they are requests the programme wanted to
send and did not, for reasons an operator should see on the status page and
can act on. Every earlier step writes nothing: a switch that is off, a missing
key, a quarantine and each standing refusal are states rather than events — the
refusals derive from rows already written, which is what holds them — a model
nobody can name cannot be recorded as requested, and a replayed answer is
already on record.

Then the call, and always a row for it, because a call is spent whether or not
anything useful came back. A 2xx with a body is judged by
:func:`jev_validate.validate_body`, from the raw body, and recorded ``ok`` or
``invalid`` with one answer per question asked. Anything else is ``error``,
recorded with its status, its body and the class of what the SDK raised. The
request and its answers are one write (:func:`jev_repo.record_exchange`).

A 2xx the SDK itself could not read is judged the same way, because the
SDK's parse is not the one a threshold stands on (docs/08, fact 3) and the
client keeps the body exactly as it arrived rather than as the SDK parsed it.
Where the two disagree it is over what the validator deliberately leaves
alone — a ``usage`` block that never decides anything, an answer to a question
nobody asked — so the validator's verdict is the status, and the SDK's
objection is kept beside it in ``error_class`` and ``error_kind``, whatever the
status turns out to be.

Two writers, one answer
~~~~~~~~~~~~~~~~~~~~~~~
Two asks of the same request in flight at once can both find nothing, both
call, and both try to record an ``ok``. The index lets one in; the other gets
a unique violation naming it, and replays the winner, which is the answer
everybody else will read. Its own answer is dropped, and logged with its
vendor request id. The daily budget does not count that call — only a row can
be counted — and the same is true of the budget check generally: it and the
call are not one step, so asks in flight together can overspend it by at most
their number. The programme asks one at a time. A winner recorded by another
question set's pack raises instead of being replayed, like a canonical row of
another pack found before the call — but after this call, not before it: the
call was made and billed, and like every lost race's it is dropped unrecorded,
logged with its vendor request id (docs/08 open item 17).

The transport
~~~~~~~~~~~~~
``transport`` is a test seam, handed through to ``jev_client.ask`` unchanged so
the SDK's tests can drive this module over real HTTP to a local server. Nothing
in ``src/`` passes one: ``tests/unit/test_jev_lane.py`` reads every call site.
"""

from __future__ import annotations

import copy
import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal

import asyncpg
from pydantic import BaseModel

from src.programme import (
    flags,
    jev_catalogue,
    jev_client,
    jev_questions,
    jev_repo,
    jev_validate,
)
from src.programme.jev_hash import request_hash, state_hash, text_sha256
from src.programme.jev_questions import QuestionSet
from src.programme.jev_validate import ValidatedAnswer, Validation

logger = logging.getLogger(__name__)

#: The lane every probe is recorded in, whatever its question set's own lane.
#: The canonical index leaves it out, so a probe is never an answer anybody
#: replays.
PROBE_LANE = "probe"

#: What each probe is known to answer, per question, by the set and version
#: whose words it answers. A probe proves more than that a call went through:
#: that the pinned model, reading the state it was given, said what anybody
#: would. ``tests/unit/test_jev_lane.py`` requires an entry for every
#: registered probe-lane set, so bumping a probe's version without deciding
#: what its new words should answer fails the build.
PROBE_EXPECTED: dict[tuple[str, int], dict[str, str]] = {
    ("probe.connectivity", 1): {"about_the_sun": "true"},
}

#: The largest value the ledger's INT columns hold. A count or a latency the
#: client reports beyond it is not one anybody measured, and writing it would
#: fail the insert that records a call already made.
MAX_INT_COLUMN = 2**31 - 1

#: Text Postgres cannot store in a ``text`` column: NUL, and the lone
#: surrogates a lenient decoder can leave in a Python string.
_UNSTORABLE = re.compile("[\x00\ud800-\udfff]")

AskStatus = Literal[
    "disabled",
    "refused_model",
    "quarantined",
    "unscreened",
    "content_blocked",
    "no_key",
    "auth_held",
    "set_refused",
    "refused_budget",
    "refused_limits",
    "ok",
    "invalid",
    "error",
]

#: The statuses that record nothing and send nothing: standing states, read
#: from switches, settings and rows already written, rather than events.
UNRECORDED_STATUSES: frozenset[str] = frozenset(
    {
        "disabled",
        "refused_model",
        "quarantined",
        "unscreened",
        "content_blocked",
        "no_key",
        "auth_held",
        "set_refused",
    }
)


@dataclass(frozen=True)
class AskResult:
    """
    What asking came to.

    ``status`` is the recorded request's status, or one of
    :data:`UNRECORDED_STATUSES`, which record nothing. ``request_row_id`` is
    the ``jev_requests`` row that holds the answer — on a replay, the canonical
    row it was read from — and ``None`` when nothing was written. ``answers``
    maps each question asked to its answer, in the order asked; a caller reads
    ``valid`` first, and an answer that is not valid is not measured, whatever
    else it holds. ``replayed`` says the answer came from the ledger and no
    call was made. ``error_kind`` is the client's classification of a call
    that failed, and ``None`` on a replay, which made no call; the canonical
    row keeps whatever the SDK said of the call that made it.
    """

    status: AskStatus
    request_row_id: int | None = None
    answers: dict[str, ValidatedAnswer] = field(default_factory=dict)
    replayed: bool = False
    error_kind: str | None = None


# The request's identity — ``state_hash`` and ``request_hash`` — lives in
# ``jev_hash``, which anything may import without importing the client, and is
# imported above under the names it always had here.


# ---------------------------------------------------------------------------
# Asking
# ---------------------------------------------------------------------------


async def ask(
    conn: asyncpg.Connection,
    *,
    question_set: QuestionSet,
    state: BaseModel,
    subject_type: str,
    subject_id: str,
    as_of: datetime,
    api_key: str | None,
    transport: object | None = None,
    probe: bool = False,
) -> AskResult:
    """
    Ask ``question_set`` about ``state``, once, and return what was answered.

    ``subject_type`` and ``subject_id`` say what the state describes, and
    ``as_of`` the instant it describes, which is not the instant it is sent.
    ``probe`` asks again on purpose (see the module docstring); a set whose own
    lane is the probe lane is always a probe.

    The arguments are checked before anything else, the switches included, so
    a caller's mistake is found whether Jev is on or off: a lane written while
    every switch is off is still held to the rules it will run under. The set
    must be the registered one — words that are not in the registry have no
    golden hash, and a threshold measured on them would describe questions
    nobody reviewed — and the state exactly its ``state_model``, because a
    subclass can carry a field the registered model refused (``TypeError``).
    The subject must be the state model's own subject type, and a text
    subject's id the sha256 of exactly the text sent (``ValueError``).

    Every early return, and what it writes, is in the module docstring. A
    database error is not one of them: it propagates, and no call is made
    after it. Nor is an answer recorded by another question set's pack, which
    raises ``ValueError`` naming both: before anything is sent when it is the
    canonical row a replay would read, and after the call when it is the winner
    of a race this call lost, whose call was made, billed and is dropped
    unrecorded (docs/08 open item 17).
    """
    sent_state = _checked(question_set, state, subject_type, subject_id, as_of)
    is_probe = probe or question_set.lane == PROBE_LANE
    lane = PROBE_LANE if is_probe else question_set.lane

    if not await _switched_on(conn, question_set):
        logger.debug("Jev is off for %s; asked nothing", question_set.name)
        return AskResult(status="disabled")

    model = await flags.jev_model(conn)
    if model is None:
        return AskResult(status="refused_model")

    stated = state_hash(sent_state)
    gated = await _web_gate(conn, question_set, subject_id, stated, model)
    if gated is not None:
        logger.info("Jev %s: the web gate held this ask (%s)", question_set.name, gated)
        return AskResult(status=gated)

    # Text only (see the module docstring). The connectivity probe's state is
    # enumerated, so a block recorded against it holds nothing either.
    if _is_text(question_set) and await jev_repo.content_blocked(conn, stated):
        logger.warning(
            "Jev %s: the vendor blocked this text before; not sent again",
            question_set.name,
        )
        return AskResult(status="content_blocked")

    questions = question_set.as_request_questions()
    hashed = request_hash(model, sent_state, questions)

    if not is_probe:
        canonical = await jev_repo.find_canonical(conn, hashed)
        if canonical is not None:
            _refuse_another_pack(question_set, canonical)
            logger.debug(
                "Jev %s answer replayed from request %s",
                question_set.name,
                canonical["id"],
            )
            return await _replay(conn, canonical, questions)

    if not api_key or not api_key.strip():
        logger.warning(
            "Jev is on for %s but no TypeSafe key is set, in the vault or the "
            "environment; asked nothing",
            question_set.name,
        )
        return AskResult(status="no_key")

    held = await _standing_refusal(conn, question_set, model)
    if held is not None:
        return AskResult(status=held)

    request = {
        "request_hash": hashed,
        "state_hash": stated,
        "question_set": question_set.name,
        "question_set_version": question_set.version,
        "pack_hash": question_set.pack_hash,
        "lane": lane,
        "provenance": question_set.provenance,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "as_of": as_of,
        "state": sent_state,
        "questions": questions,
        "model_requested": model,
    }

    budget = await flags.jev_daily_request_budget(conn)
    spent = await jev_repo.requests_today(conn)
    if spent >= budget:
        logger.warning(
            "Jev budget spent: %d of %d calls made today; %s refused",
            spent,
            budget,
            question_set.name,
        )
        return await _refused(conn, request, "refused_budget")
    share = jev_catalogue.lane_budget(budget, lane)
    spent_here = await jev_repo.requests_today(conn, lane)
    if spent_here >= share:
        logger.warning(
            "Jev %s lane's share spent: %d of its %d calls made today; %s refused",
            lane,
            spent_here,
            share,
            question_set.name,
        )
        return await _refused(conn, request, "refused_budget")

    limit = await flags.jev_max_state_tokens(conn)
    problem = jev_catalogue.request_size_problem(
        json.dumps(sent_state, ensure_ascii=False),
        {key: json.dumps(q, ensure_ascii=False) for key, q in questions.items()},
        limit,
    )
    if problem is not None:
        logger.warning("Jev %s refused before sending: %s", question_set.name, problem)
        return await _refused(conn, request, "refused_limits")

    requested_at = datetime.now(UTC)
    # Copies, so that nothing the client does to what it is handed can change
    # what is recorded: the row must be the request that was hashed.
    call = await jev_client.ask(
        api_key=api_key,
        model=model,
        state=copy.deepcopy(sent_state),
        questions=question_set.as_request_questions(),
        transport=transport,
    )
    status, validation = _judged(call, questions, model)
    answers = validation.answers if validation is not None else ()
    _log_outcome(question_set.name, status, validation, call)

    exchange = {
        **request,
        "status": status,
        "requested_at": requested_at,
        "model_answered": validation.model_answered if validation else None,
        "vendor_request_id": _storable(call.request_id),
        "http_status": call.http_status,
        "error_class": call.error_class,
        "error_kind": call.error_kind,
        "raw_body": _storable(call.raw_body),
        "input_tokens": _int_column(
            validation.input_tokens if validation else call.input_tokens
        ),
        "output_tokens": _int_column(
            validation.output_tokens if validation else call.output_tokens
        ),
        "latency_ms": _int_column(call.latency_ms),
    }
    try:
        row_id = await jev_repo.record_exchange(conn, exchange, answers)
    except asyncpg.UniqueViolationError as exc:
        if not jev_repo.is_canonical_conflict(exc):
            raise
        winner = await jev_repo.find_canonical(conn, hashed)
        if winner is None:
            raise
        if winner["pack_hash"] != question_set.pack_hash:
            # Said before raising, with the one identifier the vendor could
            # match to this call: it was made, and no row will record it.
            logger.error(
                "Jev %s: the canonical answer this call raced for was recorded "
                "by another question set's pack (request %s); this call's "
                "answer is dropped unrecorded (vendor request id %s)",
                question_set.name,
                winner["id"],
                call.request_id,
            )
            _refuse_another_pack(question_set, winner)
        logger.warning(
            "Jev %s: another writer recorded this request's answer first "
            "(request %s); replaying it and dropping this call's (vendor "
            "request id %s)",
            question_set.name,
            winner["id"],
            call.request_id,
        )
        return await _replay(conn, winner, questions)

    return AskResult(
        status=status,
        request_row_id=row_id,
        answers={answer.question_key: answer for answer in answers},
        error_kind=call.error_kind,
    )


async def run_probe(
    conn: asyncpg.Connection, api_key: str | None, transport: object | None = None
) -> dict[str, Any]:
    """
    The connectivity probe: the handler for the ``jev_probe`` job.

    Asks ``probe.connectivity`` about its one fixed sentence, as a probe, and
    reports what came back beside what it should have been. It proves the key,
    the pin, the call and the validator end to end, and it is the check to run
    before any area is switched on, which is why the probe answers to
    ``programme_enabled`` and ``jev_enabled`` alone.

    Returns what the probe found: the status, the row, each answer as
    recorded, and ``as_expected`` — ``None`` unless every answer the probe
    knows is valid, since an answer that was not measured neither agrees nor
    disagrees with anything. The ``jev_probe`` job succeeds on nothing less
    than an expected answer; every other outcome fails it, with the reason as
    its error (``main.probe_verdict``), which is what the jobs page shows.
    """
    question_set = jev_questions.PROBE_CONNECTIVITY
    result = await ask(
        conn,
        question_set=question_set,
        state=jev_questions.ProbeState(),
        subject_type="probe",
        subject_id="connectivity",
        as_of=datetime.now(UTC),
        api_key=api_key,
        transport=transport,
        probe=True,
    )
    expected = PROBE_EXPECTED.get((question_set.name, question_set.version), {})
    return {
        "question_set": question_set.name,
        "question_set_version": question_set.version,
        "status": result.status,
        "request_id": result.request_row_id,
        "error_kind": result.error_kind,
        "answers": {key: _summary(answer) for key, answer in result.answers.items()},
        "as_expected": _as_expected(result.answers, expected),
    }


# ---------------------------------------------------------------------------
# The steps
# ---------------------------------------------------------------------------


def _checked(
    question_set: Any,
    state: Any,
    subject_type: Any,
    subject_id: Any,
    as_of: Any,
) -> dict[str, Any]:
    """The state as it will be sent, once every argument has been checked."""
    if not isinstance(question_set, QuestionSet):
        raise TypeError(f"question_set must be a QuestionSet, got {question_set!r}")
    if jev_questions.REGISTRY.get(question_set.name) != question_set:
        raise ValueError(
            f"question set {question_set.name!r} v{question_set.version} is not "
            "the registered one; only a set in jev_questions.REGISTRY, whose "
            "words its golden hash pins, may be asked"
        )
    for name, value in (("subject_type", subject_type), ("subject_id", subject_id)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be non-empty text, got {value!r}")
        if _UNSTORABLE.search(value):
            raise ValueError(
                f"{name} holds a NUL or a lone surrogate, which the ledger cannot "
                "store; a call is recorded after it is made, so a request whose "
                "row could not be written is never sent"
            )
    if not isinstance(as_of, datetime):
        raise TypeError(f"as_of must be a datetime, got {as_of!r}")
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError(
            "as_of must be timezone-aware: it names the instant the state "
            "describes, and a naive time names none"
        )
    # TypeError unless the state is exactly the set's state model; and what
    # would be sent is read back through that model, so it cannot carry a
    # value the model's fields forbid.
    sent_state = question_set.dump_state(state)
    if _holds_unstorable(sent_state):
        # jsonb refuses \u0000. Neither the text nor its path is named: the
        # state goes to no log, and an error's text reaches the jobs page.
        raise ValueError(
            "the state holds a NUL or a lone surrogate, which the ledger cannot "
            "store; a call is recorded after it is made, so a request whose row "
            "could not be written is never sent"
        )
    _check_subject(question_set, sent_state, subject_type, subject_id)
    return sent_state


def _check_subject(
    question_set: QuestionSet,
    sent_state: Mapping[str, Any],
    subject_type: str,
    subject_id: str,
) -> None:
    """
    The subject is the one the state describes: the state model's own subject
    type, and for text, the sha256 of exactly the text sent.

    Content-addressed because a replay is found by the request hash, which
    names no subject: without this, the same excerpt filed under two ids would
    be answered once and recorded against one of them, and a label on the
    other would never meet its answer. With it, the canonical row for a text
    always carries that text's subject. Neither the text nor its hash is put in
    the error, which reaches the jobs page.
    """
    model = question_set.state_model
    expected = jev_questions.STATE_SUBJECT.get(model)
    if expected is None:
        raise ValueError(
            f"{model.__name__} has no subject type in jev_questions.STATE_SUBJECT"
        )
    if subject_type != expected:
        raise ValueError(
            f"subject_type must be {expected!r} for a {model.__name__}, the "
            f"subject its state describes; got {subject_type!r}"
        )
    field = jev_questions.TEXT_SUBJECT_FIELD.get(model)
    if field is not None:
        if subject_id != text_sha256(sent_state[field]):
            raise ValueError(
                f"subject_id must be the sha256 of the `{field}` sent: a text "
                "subject is its content, so a replay cannot answer for another "
                "subject and a label joins its answer exactly"
            )
    elif question_set.provenance == "web":
        # Registration forbids it; a set placed in the registry by hand could
        # still try, and the web gate has nothing to address it by.
        raise ValueError(
            f"{question_set.name} is a web set whose state is not "
            "content-addressed text"
        )
    elif expected == "session" and not _is_iso_date(subject_id):
        raise ValueError(
            f"a session subject is its date as YYYY-MM-DD, got {subject_id!r}"
        )


def _is_iso_date(text: str) -> bool:
    """Whether ``text`` is a calendar date written exactly as YYYY-MM-DD."""
    try:
        return date.fromisoformat(text).isoformat() == text
    except ValueError:
        return False


def _holds_unstorable(value: Any) -> bool:
    """Whether any key or text anywhere in ``value`` is text Postgres refuses."""
    if isinstance(value, str):
        return _UNSTORABLE.search(value) is not None
    if isinstance(value, Mapping):
        return any(
            _holds_unstorable(key) or _holds_unstorable(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_holds_unstorable(item) for item in value)
    return False


async def _switched_on(conn: asyncpg.Connection, question_set: QuestionSet) -> bool:
    """
    The programme's switch, Jev's master switch, the area switch for the set's
    own lane, and for a set carrying this system's detail the detail switch.

    Each is read here, on every ask, through its own fail-closed reader, and
    none is derived from another: the loops that call this read the first two
    as well, and a caller that did not — a planner, a harness, anything added
    later — is held to them anyway. The set's lane rather than the lane a probe
    is recorded in: an area an operator switched off is asked nothing, probes
    of its questions included. Only a set whose own lane is the probe lane
    answers to the programme and the master switch alone.
    """
    if not await flags.programme_enabled(conn):
        return False
    if not await flags.jev_enabled(conn):
        return False
    area = jev_catalogue.LANE_AREA[question_set.lane]
    if area is not None and not await flags.jev_area_enabled(conn, area):
        return False
    return not question_set.internal_detail or await flags.jev_send_internal_detail(
        conn
    )


async def _web_gate(
    conn: asyncpg.Connection,
    question_set: QuestionSet,
    content_sha256: str,
    stated: str,
    model: str,
) -> AskStatus | None:
    """
    Whether a web set may be asked about this text: ``None`` if it may, or why
    not.

    Text quarantined under any source is not asked about, by any set, the
    screen included. Otherwise every web set but the screen needs the screen's
    clear answer about exactly this state — from the version registered now and
    the pinned model, a canonical answer and not a probe's — and while no
    screen is registered there is none to have, so every web ask is refused.
    Checked for probes as for any ask, and before any replay: an answer read
    back about text since quarantined is the text, asked about again.

    ``content_sha256`` is the subject id, which :func:`_check_subject` has
    already held to the sha256 of the text sent.

    The screen's exemption, and its answers' standing, go to a set of the
    screen's shape alone (:func:`jev_questions.screen_problem`): one question,
    ``addressed_to_ai``, a Noul. Registration refuses any other under the
    screen's name; one placed in the registry by hand clears nothing, and is
    itself asked nothing about unscreened text, since a second question in it
    would be answered about text nobody screened.
    """
    if question_set.provenance != "web":
        return None
    if await jev_repo.content_quarantined(conn, content_sha256) is not None:
        return "quarantined"
    if question_set.name == jev_questions.SCREEN_SET_NAME:
        if jev_questions.screen_problem(question_set) is None:
            return None
        return "unscreened"
    screen = jev_questions.REGISTRY.get(jev_questions.SCREEN_SET_NAME)
    if screen is None or jev_questions.screen_problem(screen) is not None:
        return "unscreened"
    clean = await jev_repo.screened_clean(
        conn, state_hash=stated, pack_hash=screen.pack_hash, model=model
    )
    return None if clean else "unscreened"


def _is_text(question_set: QuestionSet) -> bool:
    """
    Whether ``question_set`` asks about text a content filter could object to:
    a content-addressed text state, a web excerpt or a hypothesis title
    (:data:`jev_questions.TEXT_SUBJECT_FIELD`). Only such a state is held by a
    content block; an enumerated one is labels computed in code.
    """
    return question_set.state_model in jev_questions.TEXT_SUBJECT_FIELD


async def _standing_refusal(
    conn: asyncpg.Connection, question_set: QuestionSet, model: str
) -> AskStatus | None:
    """
    A refusal the vendor has already given and would give again: ``None``, or
    the status that holds this ask.

    An authentication failure since 00:00 UTC holds every lane until then: a
    refused key is refused on every call, and each would spend the budget to
    learn it again. The ledger keeps no trace of which key failed, so a key
    replaced after the failure is held too, the connectivity probe's included:
    until 00:00 UTC only the operator's dispatch-only check,
    ``python -m src.programme.jev_check`` by ``jev-check.yml``, can prove it. A
    422 for this set, version and model holds the set until a new version
    changes its words, or a new pin its judge. Both derive from rows already
    written, so no process writes a switch, and neither writes one of its own.
    """
    if await jev_repo.auth_failed_today(conn):
        logger.warning(
            "Jev %s held: an authentication failure was recorded today, and "
            "asks resume at 00:00 UTC",
            question_set.name,
        )
        return "auth_held"
    if await jev_repo.set_refused(
        conn,
        question_set=question_set.name,
        version=question_set.version,
        model=model,
    ):
        logger.warning(
            "Jev %s v%s held: the vendor refused its request with a 422 under "
            "%s; a new version is needed",
            question_set.name,
            question_set.version,
            model,
        )
        return "set_refused"
    return None


def _refuse_another_pack(question_set: QuestionSet, row: Mapping[str, Any]) -> None:
    """
    Raise unless ``row``, a canonical answer about to be read back, was
    recorded by this set's own pack.

    The request hash names no set, so two sets asking identical words about an
    identical state share one canonical row. The registry refuses a second set
    with a registered set's questions, and the suite refuses a version whose
    words repeat a released one's; this is the third line, for a row written by
    hand or by a set since retired. Loud, because serving one set another's
    answer is a defect, not a case to settle (docs/08 open item 15).
    """
    if row["pack_hash"] != question_set.pack_hash:
        raise ValueError(
            f"the canonical answer to this request (request {row['id']}) was "
            f"recorded by {row['question_set']} v{row['question_set_version']} "
            f"(pack {str(row['pack_hash'])[:12]}), not by {question_set.name} "
            f"v{question_set.version} (pack {question_set.pack_hash[:12]}); no "
            "answer crosses from one question set to another"
        )


async def _refused(
    conn: asyncpg.Connection, request: Mapping[str, Any], status: AskStatus
) -> AskResult:
    """A request refused before it was sent: its row, and no call."""
    row_id = await jev_repo.record_exchange(conn, {**request, "status": status}, ())
    return AskResult(status=status, request_row_id=row_id)


def _judged(
    call: Any, questions: Mapping[str, dict], model: str
) -> tuple[AskStatus, Validation | None]:
    """
    The status a call is recorded under, and its validation where it has one.

    Only a 2xx with a body is judged, whether or not the SDK raised over it
    (see the module docstring); anything else is an ``error`` and answered
    nothing. The validator reads the bytes as they arrived, not the stored
    text: a body that is not UTF-8, or holds a raw NUL, is repaired for the
    ledger, and judged repaired it would become a canonical answer for good.
    """
    status = call.http_status
    answered = (
        isinstance(status, int)
        and not isinstance(status, bool)
        and 200 <= status <= 299
        and call.wire_body is not None
    )
    if not answered:
        return "error", None
    validation = jev_validate.validate_body(call.wire_body, questions, model)
    return validation.status, validation


def _log_outcome(
    name: str, status: str, validation: Validation | None, call: Any
) -> None:
    # The validator's problem has no column, so this line is where it is kept.
    # Neither the state nor the body is logged: what is sent to a vendor does
    # not also go to wherever the logs go.
    if status == "error":
        logger.warning(
            "Jev %s call failed: %s (%s), HTTP %s",
            name,
            call.error_kind,
            call.error_class,
            call.http_status,
        )
        return
    if call.error_kind is not None:
        # The client read a response the SDK would not. Said on every call,
        # because the likeliest cause is the SDK and the vendor disagreeing
        # about the response's shape, which would repeat on every call.
        logger.warning(
            "Jev %s: the SDK could not read the response (%s, %s); the "
            "validator judged it %s",
            name,
            call.error_kind,
            call.error_class,
            status,
        )
    if status == "invalid":
        problem = validation.problem if validation else None
        logger.warning("Jev %s response refused whole: %s", name, problem)
    elif validation is not None and validation.problem:
        logger.info("Jev %s answered, with notes: %s", name, validation.problem)


async def _replay(
    conn: asyncpg.Connection,
    canonical: Mapping[str, Any],
    questions: Mapping[str, dict],
) -> AskResult:
    """The canonical answer, read back rather than asked for again."""
    recorded = {
        row["question_key"]: row
        for row in await jev_repo.answers_for(conn, canonical["id"])
    }
    return AskResult(
        status="ok",
        request_row_id=canonical["id"],
        answers={
            key: _answer_from(recorded[key], question)
            for key, question in questions.items()
            if key in recorded
        },
        replayed=True,
    )


def _answer_from(
    row: Mapping[str, Any], question: Mapping[str, Any]
) -> ValidatedAnswer:
    """
    A recorded answer as the validator first returned it.

    The probabilities come back from a ``jsonb`` column, which keeps keys in an
    order of its own, so they are put back in the order asked: a replay of an
    answer keyed by the options reads the same way round as the answer it
    replays. One keyed otherwise was not measured, and the vendor's order is in
    the row's ``raw_body``.
    """
    values = {name: row[name] for name in jev_repo.ANSWER_FIELDS}
    values["probabilities"] = _in_asked_order(values["probabilities"], question)
    return ValidatedAnswer(**values)


def _in_asked_order(probabilities: Any, question: Mapping[str, Any]) -> Any:
    if not isinstance(probabilities, Mapping):
        return probabilities
    criteria = question.get("criteria")
    if question.get("type") == "score" and isinstance(criteria, Sequence):
        options = [str(level) for level in range(len(criteria))]
    elif isinstance(criteria, Mapping):
        options = list(criteria)
    else:
        return dict(probabilities)
    if set(probabilities) != set(options):
        return dict(probabilities)
    return {option: probabilities[option] for option in options}


# ---------------------------------------------------------------------------
# Values the ledger can hold
# ---------------------------------------------------------------------------


def _storable(text: str | None) -> str | None:
    """
    ``text`` with anything Postgres cannot store replaced by U+FFFD.

    A body is kept verbatim wherever it can be, and a NUL cannot be: a 403
    page carrying one would otherwise fail the insert recording a call that was
    made. The validator has already read the verbatim text, so this changes
    only what is stored, and a JSON body — the only kind that can be ``ok`` —
    cannot carry a raw NUL at all.
    """
    if text is None:
        return None
    stored = _UNSTORABLE.sub("\ufffd", text)
    if stored != text:
        logger.warning(
            "A Jev response held text the ledger cannot store; kept with "
            "U+FFFD in its place"
        )
    return stored


def _int_column(value: Any) -> int | None:
    """``value`` if it is a count an INT column holds, else ``None``."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= MAX_INT_COLUMN else None


# ---------------------------------------------------------------------------
# The probe's report
# ---------------------------------------------------------------------------


def _summary(answer: ValidatedAnswer) -> dict[str, Any]:
    """One answer for the job's result: what it measured, or why it did not."""
    summary: dict[str, Any] = {
        "type": answer.question_type,
        "valid": answer.valid,
        "invalid_reason": answer.invalid_reason,
        "argmax": answer.argmax,
        "margin": answer.margin,
    }
    if answer.question_type == "noul":
        summary["noul"] = answer.noul
    else:
        summary["confidence"] = answer.confidence
        summary["probabilities"] = answer.probabilities
        if answer.question_type == "choice":
            summary["choice"] = answer.choice
        else:
            summary["score"] = answer.score
    return summary


def _as_expected(
    answers: Mapping[str, ValidatedAnswer], expected: Mapping[str, str]
) -> bool | None:
    if not expected:
        return None
    agreed = []
    for key, argmax in expected.items():
        answer = answers.get(key)
        if answer is None or not answer.valid:
            return None
        agreed.append(answer.argmax == argmax)
    return all(agreed)


__all__ = [
    "MAX_INT_COLUMN",
    "PROBE_EXPECTED",
    "PROBE_LANE",
    "UNRECORDED_STATUSES",
    "AskResult",
    "AskStatus",
    "ask",
    "request_hash",
    "run_probe",
    "state_hash",
]
