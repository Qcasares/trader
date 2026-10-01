"""
jev_jobs.py
-----------
The ``jev_ask`` job, which asks one registered set about one stored text
(phases C7 and C8); what becomes of its answer; and the re-ask job.

Runner-only: it asks through ``jev_lane``, which holds the client
(``tests/unit/test_import_boundaries.py``). Every handler here and in
``jev_forward`` makes at most one ask an attempt, which is what the
programme's shutdown grace is sized for (``main.JEV_SHUTDOWN_GRACE_SECONDS``)
and what ``tests/unit/test_job_ownership.py::TestEveryJevHandlerMakesAtMostOneCall``
holds. Per attempt, not per job: an attempt whose call got no response is
retried (:func:`ask_verdict`) and asks again, since an ``error`` row is no
answer to replay.

A job's verdict is its status
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The jobs page shows a job's status and its error, and nothing reads the
result column, so an ask that came to nothing fails its job, with the reason
as the error (:func:`ask_verdict`, which lives in ``job_errors`` from phase C7
so the forward clock can read it without loading this module and the web
modules it reads; re-exported here). Retried only where another attempt could
change the answer — no response, a rate limit or a vendor fault, or a switch
turned off while the job ran — and never for a standing refusal, which would
be refused again.

The ``jev_ask`` job
~~~~~~~~~~~~~~~~~~~
:func:`run_ask` asks one of the sets in :data:`ASKABLE` about one subject, once:
a stored web excerpt (``guardrail.injection``, ``research.catalogue``), a
hypothesis title the programme's own model wrote (``research.hypothesis``,
``guardrail.card``), from phase D2 the title of a finding the programme's
model raised (``findings.owner``, ``findings.severity``), or, from phase D3,
the skeleton of a failed research or ingest job's error (``ops.job_error``).
Its payload names the subject, the row it was read from
and the analysis plans it was planned under (:data:`PLAN_KEYS`), never its
text, and the handler reads the text again from that row. In order; the first
that applies decides:

==  =========================================================  ================
#   Condition                                                  Outcome
==  =========================================================  ================
0   The payload is anything but the nine names, or its set is   fail, no retry
    not one :data:`ASKABLE` holds, or its subject type is not
    that set's
1   The payload's version is not the registered set's          complete,
                                                               ``superseded``
2   The set has no analysis plan (``jev_prereg``)              fail, no retry
3   The plans the payload names are not the plans in force     complete,
                                                               ``superseded``
4   The row is not stored, or its text is not the subject      fail, no retry
5   The row may not be asked about (below)                     fail, no retry
6   The state cannot be built, or, for a subject addressed by  fail, no retry,
    its state, the state built is not the subject              no text quoted
7   The ask, once; then its follow-up; then its verdict        as
                                                               :func:`ask_verdict`
==  =========================================================  ================

Step 5 for a web excerpt: content quarantined under any source is asked
nothing; then the code screen reads the stored excerpt again, as it stands
now, and a hit quarantines the content (``web_sources.quarantine_reason``) and
fails the job — a rule added to the screen since the page was read applies
before any model is asked; then an earlier answer of the injection screen
that found the content addressed to an AI system, whose quarantine failed to
write, quarantines it in the screen's words and fails the job (below). For a
hypothesis: only one the programme's model
wrote is sent (``origin = 'model'``; an operator's text would be a subject of
its own, docs/08 open item 28), and only a title within
``jev_questions.TITLE_MAX_CHARS``, refused by that number before any state is
built, so the refusal is the cap's and never pydantic's. The row is read by
column list (``jev_repo.get_hypothesis_title``: its ref, title, origin and
creation time, and nothing else), never through ``repo.get_hypothesis``,
whose ``SELECT *`` would hand this side the card (docs/09, D-SAFE-2). For a
finding (phase D2) the same, by its own cap: only one the programme's model
wrote — never an operator's, Jev's, or one raised before migration 0015 named
its writer — and only a title within ``jev_questions.FINDING_TITLE_MAX_CHARS``,
read by column list (``jev_repo.get_finding_title``: its ref, title, origin
and when it was opened), never its detail, remediation, close note, raiser or
recorded severity.

For a failed job (phase D3), read by its id (``jev_repo.get_failed_job``: its
id, kind, status, error and finish time, and nothing else), each refused alone
and asked nothing: a job that did not fail; one of a kind code alone places
(anything but ``jev_redact.TRIAGED_KINDS``: a venue's, the shadow replay's,
the programme's own); one with no finish time, which an expired lease leaves;
one whose error code's table places (``jev_chips.code_cause``); and one whose
skeleton holds too few words of the vocabulary to ask about
(``jev_redact.admissible``). The error is read by those two lines and by the
one that builds the state, ``jev_redact.skeleton``, and by nothing else: the
state is the skeleton and the job's kind, and the subject is that state's
address (``jev_questions.job_error_subject``), so it is held to the subject
once the state is built (step 6) rather than before admission, as a text's
address is. Nothing quotes the error; an error is named by its job's id.

Step 6: pydantic's ``ValidationError`` quotes the input it refused, so it is
replaced by an error naming the document's id or the hypothesis's ref and
nothing else; no web text and no title reaches ``jobs.error``. For the same
reason anything else steps 4 to 7 raise — a read, a quarantine's write, the ask
or its follow-up — is reported by its class, its SQLSTATE and its constraint
alone (``job_errors.described``), and retried.

The plans an answer was recorded under
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The harness scores an answer only under the analysis plans in force when it
was recorded — the global plan's version and hash and the set's own plan's
(``jev_prereg.plans_in_force``) — and never by a baseline chosen after it. So
they are recorded for every answer however its job ends, twice over. The
planner writes them into the payload, and step 3 asks nothing under any
others: every row any attempt of the job records — an answer, a response
refused whole, a failed call — was recorded under the plans its payload has
named since before the first attempt, whatever becomes of the job. And the
job's row names the request its attempt recorded beside them: in the result
of a job that succeeds, and in the result :class:`JobFailedError` carries for
one that fails after its ask recorded a row — a response refused whole, which
the harness counts, or an answer whose follow-up failed, which is canonical
and in the ledger whether or not the follow-up is ever made. An attempt that
recorded nothing leaves an earlier attempt's record in place
(``job_repo.fail``). A set with no plan is asked nothing.

What an answer changes
~~~~~~~~~~~~~~~~~~~~~~
==========================  ==================================  =================
Set                         Answer                              Follow-up
==========================  ==================================  =================
``guardrail.injection``     valid, argmax ``true``              the content is
                                                                quarantined, by
                                                                content, under
                                                                every source,
                                                                worded as below
\\                           valid, argmax ``false``             none; the
                                                                catalogue may now
                                                                be asked
\\                           invalid, or a tie, in an ``ok``     none: held, under
                            response                            this version and
                                                                pin, since the
                                                                canonical row
                                                                replays
any web set                 a content block, this call's or     the content is
                            one on record                       quarantined
``research.catalogue``,     anything else                       none: recorded,
``research.hypothesis``,                                        and acted on by
``guardrail.card``,                                             nothing
``findings.owner``,
``findings.severity``,
``ops.job_error``
==========================  ==================================  =================

The injection screen's quarantine says what it was, and that it is not
calibrated: ``jev guardrail.injection v1: addressed_to_ai p=0.87 (request N,
<model>); not calibrated``. A content block's says it is a precaution: ``vendor
content block on request N (a 403 whose body is not JSON; an unverified
precaution, docs/08 fact 4)``. The block is found two ways, so a quarantine
that failed to write is made by a later attempt: this call's own ``error`` row
of kind ``content_block``, or — on any later ask about the same text, which the
road refuses before a call as ``content_blocked`` — the earliest block on record
for the content (``jev_repo.content_block_request``). The error row commits on
its own before the follow-up runs, so a write that fails between them leaves
the block on record and the content in use; the job then fails for a retry,
and the retry, or tomorrow's screen, which ``jev_repo.documents_to_screen``
plans for blocked content still in use, quarantines it. The screen's own
``true`` is canonical and committed before its quarantine is written too, so
it is read back the same way: before any ask about stored web text, a re-ask's
included, the answer on record (``jev_repo.screen_flag``) quarantines content
still in use, in the screen's words, and the job fails asking nothing
(:func:`screen_stored_excerpt`); ``documents_to_screen`` plans that repair for
flagged content still in use, and ``jev_plan`` re-asks no flagged text. No
title is ever quarantined: quarantine is a web document's, and a blocked title
is held by the road alone. Nothing that writes ``hypotheses``, ``candidates`` or
``findings`` is reachable from here: a card check's answer is recorded and
acts on nothing, and so is a findings set's — a suggested owner or severity
is in the ledger alone, never written to a finding, and the chips phase E
shows are computed from the ledger at read time (``jev_chips``) — and the ops
set's: a suggested cause retries, resumes, cancels and fails no job, and
changes no switch (``tests/unit/test_jev_jobs.py::TestTheCardCheckChangesNothing``).

Re-asks measure the noise
~~~~~~~~~~~~~~~~~~~~~~~~~
Jev is not deterministic (docs/08, fact 1), so a threshold is only worth
something beside the rate at which its answers flip. :func:`run_reask` asks a
canonical request's exact state and questions again, as a probe: recorded in
the probe lane, never replayed and never the answer anybody reads, and spent
from the probe lane's share of the budget. The requests re-asked are the
pre-registered sample (``jev_prereg.reask_sample``), planned by ``jev_plan``;
the flip rates are the harness's to compute, from the pairs the ledger holds.
A re-ask of web text reads the stored excerpt through the code screen first,
as :func:`run_ask` does, and quarantines it on a hit without asking; and a
content block met by a re-ask of web text quarantines the content, as a block
met by any web ask does. Its answer never quarantines: a probe measures, and
acts on nothing.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any

import asyncpg
from pydantic import BaseModel, ValidationError

from src.programme import (
    flags,
    jev_catalogue,
    jev_chips,
    jev_lane,
    jev_prereg,
    jev_questions,
    jev_redact,
    jev_repo,
    web_sources,
)
from src.programme.jev_hash import text_sha256
from src.programme.job_errors import (
    NOT_ASKED,
    JobFailedError,
    ask_verdict,
    described,
)

logger = logging.getLogger(__name__)

#: The analysis plans a ``jev_ask`` job is planned and asked under, by the
#: names ``jev_prereg.plans_in_force`` gives them: the global plan's version
#: and hash, and the set's own plan's.
PLAN_KEYS = ("plan_version", "plan_hash", "set_plan_version", "set_plan_hash")

#: The names a ``jev_ask`` payload carries, and nothing else: the set and its
#: version, the subject, the row the subject's text is read from, and the
#: plans it was planned under. Never the text: the handler reads it again from
#: that row.
ASK_PAYLOAD_KEYS = frozenset(
    {"set", "version", "subject_type", "subject_id", "source_id", *PLAN_KEYS}
)

#: The reason the injection screen's ``true`` quarantines its text: the set and
#: version that asked, its question, the probability it gave, the request and
#: the model that answered, and that none of it is calibrated.
SCREEN_REASON = (
    "jev {set} v{version}: {question} p={p} (request {request}, {model}); not "
    "calibrated"
)

#: The reason a content block quarantines its text, ``{request}`` the block's
#: request row.
CONTENT_BLOCK_REASON = (
    "vendor content block on {request} (a 403 whose body is not JSON; an "
    "unverified precaution, docs/08 fact 4)"
)


@dataclass(frozen=True)
class Askable:
    """
    How a ``jev_ask`` job of one set finds what it asks about, and what its
    answer changes.

    ``subject_type`` is what the set's state describes. ``load`` reads the row
    the payload's ``source_id`` names — a stored document by its id, a
    hypothesis or a finding by its ref, a job by its id — or returns ``None``;
    ``address`` is the subject the row holds, from the row and the state built
    from it (docs/09, section 5.1): for text, the sha256 of the text, the
    state unread and ``None`` before one is built, held to the subject before
    ``admit``; for a subject addressed by its state
    (``jev_questions.STATE_ADDRESSED``), the state's own hash, held to it once
    the state is built. ``admit`` refuses, by raising, what may not be asked
    about, before any state is built; ``build`` makes the state, ``as_of``
    the instant it describes, ``what`` names the row in an error by its id
    alone, and ``follow_up``, where there is one, is what the answer changes.
    """

    subject_type: str
    load: Callable[[asyncpg.Connection, object], Awaitable[Mapping[str, Any] | None]]
    address: Callable[[Mapping[str, Any], BaseModel | None], object]
    admit: Callable[[asyncpg.Connection, Mapping[str, Any]], Awaitable[None]]
    build: Callable[[Mapping[str, Any]], BaseModel]
    as_of: Callable[[Mapping[str, Any]], datetime]
    what: Callable[[Mapping[str, Any]], str]
    follow_up: (
        Callable[
            [asyncpg.Connection, Mapping[str, Any], jev_lane.AskResult],
            Awaitable[dict[str, Any]],
        ]
        | None
    )


# ---------------------------------------------------------------------------
# Stored web excerpts (phase C7)
# ---------------------------------------------------------------------------


async def _load_document(
    conn: asyncpg.Connection, source_id: object
) -> Mapping[str, Any] | None:
    if isinstance(source_id, bool) or not isinstance(source_id, int):
        raise JobFailedError(
            f"a web excerpt's row is a stored document, named by its id; got "
            f"{type(source_id).__name__}",
            retry=False,
        )
    return await jev_repo.get_document(conn, source_id)


async def screen_stored_excerpt(
    conn: asyncpg.Connection, content_sha256: str, excerpt: str, what: str
) -> None:
    """
    Refuse, by raising, to ask about a stored excerpt that may not be asked
    about: content quarantined under any source; text the code screen, as it
    stands now, flags; or content the injection screen found addressed to an
    AI system on an earlier request (``jev_repo.screen_flag``). Either of the
    last two is quarantined here, by content, before the job fails. All
    without a retry. ``what`` names the row, never its text.

    The screen's flag is read because its answer is canonical, and committed
    before its quarantine is written: a write that failed on every attempt
    left the text in use, and the answer on record says it should not be.
    Read here, before any ask, the quarantine is made by the next job about
    the text — the screen's repair, which ``jev_repo.documents_to_screen``
    plans, or any other — and no ask, a re-ask's probe included, sends the
    flagged text to the vendor again.
    """
    if await jev_repo.content_quarantined(conn, content_sha256) is not None:
        raise JobFailedError(
            f"{what}'s content is quarantined, and nothing asks about it again; "
            "nothing was asked",
            retry=False,
        )
    rule = web_sources.code_screen(excerpt)
    if rule is not None:
        reason = web_sources.quarantine_reason(rule)
        count = await jev_repo.quarantine_content(conn, content_sha256, reason)
        raise JobFailedError(
            f"the code screen flags {what} ({reason}), and its content is now "
            f"quarantined ({count} documents); nothing was asked",
            retry=False,
        )
    flag = await jev_repo.screen_flag(conn, content_sha256)
    if flag is not None:
        count = await _quarantine_as_screened(
            conn,
            content_sha256,
            what,
            version=flag["question_set_version"],
            p=flag["noul"],
            request=flag["request_id"],
            model=flag["model_answered"],
        )
        raise JobFailedError(
            f"{what}'s content was flagged by Jev's injection screen on request "
            f"{flag['request_id']} (not calibrated), and it is now quarantined "
            f"({count} documents); nothing was asked",
            retry=False,
        )


async def _admit_excerpt(conn: asyncpg.Connection, row: Mapping[str, Any]) -> None:
    await screen_stored_excerpt(
        conn, row["content_sha256"], row["excerpt"], _document(row)
    )


def _document(row: Mapping[str, Any]) -> str:
    return f"document {row['id']}"


def _excerpt_state(row: Mapping[str, Any]) -> BaseModel:
    return jev_questions.WebExcerptState(excerpt=row["excerpt"])


async def quarantine_if_blocked(
    conn: asyncpg.Connection, content_sha256: str, result: jev_lane.AskResult
) -> dict[str, Any]:
    """
    Quarantine web text the vendor blocked, and say so; ``{}`` otherwise.

    A block is this call's ``error`` row of kind ``content_block``, or, when the
    road refused the ask as ``content_blocked``, the earliest block on record
    for the content: so a quarantine whose write failed after the block's row
    committed is made by whichever ask about the text comes next. Web text
    only: a caller never passes a title, which no document holds.
    """
    if result.status == "error" and result.error_kind == "content_block":
        request = result.request_row_id
    elif result.status == "content_blocked":
        request = await jev_repo.content_block_request(
            conn, subject_type="web_excerpt", subject_id=content_sha256
        )
    else:
        return {}
    named = "an earlier request" if request is None else f"request {request}"
    reason = CONTENT_BLOCK_REASON.format(request=named)
    count = await jev_repo.quarantine_content(conn, content_sha256, reason)
    logger.warning(
        "Jev: the vendor blocked web content on %s; %d documents quarantined",
        named,
        count,
    )
    return {"quarantined": count, "quarantined_by": "content_block"}


async def _excerpt_follow_up(
    conn: asyncpg.Connection, row: Mapping[str, Any], result: jev_lane.AskResult
) -> dict[str, Any]:
    """Any web set's follow-up: a content block quarantines; nothing else."""
    return await quarantine_if_blocked(conn, row["content_sha256"], result)


async def _screen_follow_up(
    conn: asyncpg.Connection, row: Mapping[str, Any], result: jev_lane.AskResult
) -> dict[str, Any]:
    """
    The injection screen's: a content block quarantines; so does a valid
    ``true``, worded as the screen's and not calibrated; anything else changes
    nothing — a valid ``false`` is what lets the catalogue ask, and an answer
    that is not valid holds the text, since its canonical row replays.
    """
    blocked = await quarantine_if_blocked(conn, row["content_sha256"], result)
    if blocked:
        return blocked
    answer = result.answers.get(jev_questions.SCREEN_QUESTION)
    if (
        result.status != "ok"
        or answer is None
        or not answer.valid
        or answer.argmax != jev_questions.SCREEN_FLAG_ARGMAX
    ):
        return {}
    request = (
        None
        if result.request_row_id is None
        else await jev_repo.get_request(conn, result.request_row_id)
    )
    count = await _quarantine_as_screened(
        conn,
        row["content_sha256"],
        _document(row),
        version=jev_questions.GUARDRAIL_INJECTION.version,
        p=answer.noul,
        request=result.request_row_id,
        model=None if request is None else request["model_answered"],
    )
    return {"quarantined": count, "quarantined_by": "jev_screen"}


async def _quarantine_as_screened(
    conn: asyncpg.Connection,
    content_sha256: str,
    what: str,
    *,
    version: int,
    p: float | None,
    request: int | None,
    model: str | None,
) -> int:
    """
    Quarantine content the injection screen found addressed to an AI system,
    by content, in the screen's own words, and log it as they are worded: an
    uncalibrated argmax, never "an injection found" (design section 10.3), in
    the run logs as in the row. Returns how many documents it quarantined.
    """
    shown = _probability(p)
    reason = SCREEN_REASON.format(
        set=jev_questions.SCREEN_SET_NAME,
        version=version,
        question=jev_questions.SCREEN_QUESTION,
        p=shown,
        request=request,
        model=model,
    )
    count = await jev_repo.quarantine_content(conn, content_sha256, reason)
    logger.info(
        "%s quarantined by Jev's injection screen (%s p=%s, request %s, %s; "
        "not calibrated); %d documents",
        what,
        jev_questions.SCREEN_QUESTION,
        shown,
        request,
        model,
        count,
    )
    return count


def _probability(p: float | None) -> str:
    """A screen's probability as its reason writes it; absent, said so."""
    return "not recorded" if p is None else f"{p:.2f}"


# ---------------------------------------------------------------------------
# Hypothesis titles (phase C8)
# ---------------------------------------------------------------------------


async def _load_hypothesis(
    conn: asyncpg.Connection, source_id: object
) -> Mapping[str, Any] | None:
    """
    The hypothesis a title set asks about, by its ref: its ref, title, origin
    and creation time, and nothing else (``jev_repo.get_hypothesis_title``).
    Never ``repo.get_hypothesis``, whose ``SELECT *`` would hand this side the
    card and every column a later migration adds (docs/09, D-SAFE-2).
    """
    if not isinstance(source_id, str) or not source_id.strip():
        raise JobFailedError(
            f"a hypothesis title's row is a hypothesis, named by its ref; got "
            f"{type(source_id).__name__}",
            retry=False,
        )
    return await jev_repo.get_hypothesis_title(conn, source_id)


async def _admit_title(conn: asyncpg.Connection, row: Mapping[str, Any]) -> None:
    """
    Only a title the programme's own model wrote, within the cap. The cap is
    read here, from ``TITLE_MAX_CHARS``, before any state is built: the state's
    own limit would refuse an overlong title too, but as pydantic's error, and
    the refusal is to be the cap's.
    """
    what = _hypothesis(row)
    if row["origin"] != "model":
        raise JobFailedError(
            f"{what} was written by {row['origin']!r}, not by the programme's "
            "model; only a model-written title is sent (docs/08 open item 28); "
            "nothing was asked",
            retry=False,
        )
    title = row["title"]
    if isinstance(title, str) and len(title) > jev_questions.TITLE_MAX_CHARS:
        raise JobFailedError(
            f"{what}'s title is {len(title)} characters, over the "
            f"{jev_questions.TITLE_MAX_CHARS} a title state carries; a title is "
            "not sent over its cap, and never cut; nothing was asked",
            retry=False,
        )


def _hypothesis(row: Mapping[str, Any]) -> str:
    return f"hypothesis {row['ref']}"


def _title_state(row: Mapping[str, Any]) -> BaseModel:
    return jev_questions.HypothesisTitleState(title=row["title"])


def _created_at(row: Mapping[str, Any]) -> datetime:
    """When the hypothesis was written: the instant its title describes."""
    value = row["created_at"]
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


# ---------------------------------------------------------------------------
# Finding titles (phase D2)
# ---------------------------------------------------------------------------


async def _load_finding(
    conn: asyncpg.Connection, source_id: object
) -> Mapping[str, Any] | None:
    """
    The finding a findings set asks about, by its ref: its ref, title, origin
    and when it was opened, and nothing else (``jev_repo.get_finding_title``).
    Never ``repo.list_findings``, whose ``SELECT *`` would hand this side the
    finding's detail, its remediation and its close note (docs/09, section
    5.1), nor anything that reads who raised it or its recorded severity,
    which the baseline compares an answer with.
    """
    if not isinstance(source_id, str) or not source_id.strip():
        raise JobFailedError(
            f"a finding title's row is a finding, named by its ref; got "
            f"{type(source_id).__name__}",
            retry=False,
        )
    return await jev_repo.get_finding_title(conn, source_id)


async def _admit_finding(conn: asyncpg.Connection, row: Mapping[str, Any]) -> None:
    """
    Only a title the programme's own model wrote, within the cap. An
    operator's finding, a Jev finding and one raised before migration 0015
    named its writer (``'unknown'``) are never sent (docs/08 open item 76).
    The cap is read here, from ``FINDING_TITLE_MAX_CHARS``, before any state is
    built: the state's own limit would refuse an overlong title too, but as
    pydantic's error, and the refusal is to be the cap's.
    """
    what = _finding(row)
    if row["origin"] != "model":
        raise JobFailedError(
            f"{what} was written by {row['origin']!r}, not by the programme's "
            "model; only a model-written finding's title is sent; nothing was "
            "asked",
            retry=False,
        )
    title = row["title"]
    if isinstance(title, str) and len(title) > jev_questions.FINDING_TITLE_MAX_CHARS:
        raise JobFailedError(
            f"{what}'s title is {len(title)} characters, over the "
            f"{jev_questions.FINDING_TITLE_MAX_CHARS} a finding-title state "
            "carries; a title is not sent over its cap, and never cut; nothing "
            "was asked",
            retry=False,
        )


def _finding(row: Mapping[str, Any]) -> str:
    return f"finding {row['ref']}"


def _finding_state(row: Mapping[str, Any]) -> BaseModel:
    return jev_questions.FindingTitleState(title=row["title"])


def _opened_at(row: Mapping[str, Any]) -> datetime:
    """When the finding was raised: the instant its title describes."""
    value = row["opened_at"]
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


# ---------------------------------------------------------------------------
# A failed job's error, as a skeleton (phase D3)
# ---------------------------------------------------------------------------


async def _load_failed_job(
    conn: asyncpg.Connection, source_id: object
) -> Mapping[str, Any] | None:
    """
    The job the ops set asks about, by its id: its id, kind, status, error
    and when it finished, and nothing else (``jev_repo.get_failed_job``).
    """
    try:
        job_id = uuid.UUID(source_id) if isinstance(source_id, str) else None
    except ValueError:
        job_id = None
    if job_id is None:
        raise JobFailedError(
            f"a job error's row is a job, named by its id; got "
            f"{type(source_id).__name__}",
            retry=False,
        )
    return await jev_repo.get_failed_job(conn, job_id)


async def _admit_failed_job(conn: asyncpg.Connection, row: Mapping[str, Any]) -> None:
    """
    Only a failed job of a triaged kind, with a finish time, whose error code
    leaves to Jev and whose skeleton holds enough words to ask about — the
    population the planner plans from (``jev_chips.residue_skeleton``) — each
    refused alone, before any state is built (docs/09, section 5.1). The
    planner plans no other; a job refused here was named by hand, or left the
    population between the plan and the claim because code's table or the
    redactor moved. The error is read by ``code_cause`` and the redactor
    alone, and never quoted: each refusal names the job by its id and says
    which rule refused it, in words ``jev_chips``' shapes place.
    """
    job_id = row["id"]
    if row["status"] != "failed":
        raise JobFailedError(
            f"job {job_id} is {row['status']!r}, not failed; only a failed job's "
            "error is asked about; nothing was asked",
            retry=False,
        )
    if row["kind"] not in jev_redact.TRIAGED_KINDS:
        raise JobFailedError(
            f"job {job_id} is of the kind {row['kind']!r}, whose errors code "
            "alone places; nothing was asked",
            retry=False,
        )
    if row["finished_at"] is None:
        raise JobFailedError(
            f"job {job_id} has no finish time; only a job that finished failing "
            "is asked about; nothing was asked",
            retry=False,
        )
    cause = jev_chips.code_cause(row["kind"], row["error"])
    if cause is not None:
        raise JobFailedError(
            f"job {job_id}'s error is placed by code ({cause}), and only what "
            "code cannot place is asked about; nothing was asked",
            retry=False,
        )
    if not jev_redact.admissible(jev_redact.skeleton(row["error"])):
        raise JobFailedError(
            f"job {job_id}'s error reduces to fewer than "
            f"{jev_redact.MIN_CONTENT_TOKENS} words of the vocabulary, too few to "
            "ask about; nothing was asked",
            retry=False,
        )


def _job(row: Mapping[str, Any]) -> str:
    return f"job {row['id']}"


def _job_error_state(row: Mapping[str, Any]) -> BaseModel:
    """The job's kind and its error's skeleton, and nothing else of the job."""
    return jev_questions.JobErrorState(
        job_kind=row["kind"], error=jev_redact.skeleton(row["error"])
    )


def _job_error_address(row: Mapping[str, Any], state: BaseModel | None) -> object:
    """The subject a job holds: its state's address, once the state is built."""
    if not isinstance(state, jev_questions.JobErrorState):
        return None
    return jev_questions.job_error_subject(state)


def _finished_at(row: Mapping[str, Any]) -> datetime:
    """When the job finished failing: the instant its error describes."""
    value = row["finished_at"]
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


def _text_address(text: object) -> str | None:
    """A text subject's address: the sha256 of the text, or ``None``."""
    return text_sha256(text) if isinstance(text, str) else None


_EXCERPT = {
    "subject_type": "web_excerpt",
    "load": _load_document,
    "address": lambda row, state: _text_address(row["excerpt"]),
    "admit": _admit_excerpt,
    "build": _excerpt_state,
    "as_of": lambda row: row["fetched_at"],
    "what": _document,
}

_TITLE = {
    "subject_type": "hypothesis_title",
    "load": _load_hypothesis,
    "address": lambda row, state: _text_address(row["title"]),
    "admit": _admit_title,
    "build": _title_state,
    "as_of": _created_at,
    "what": _hypothesis,
}

_FINDING = {
    "subject_type": "finding_title",
    "load": _load_finding,
    "address": lambda row, state: _text_address(row["title"]),
    "admit": _admit_finding,
    "build": _finding_state,
    "as_of": _opened_at,
    "what": _finding,
}

_JOB_ERROR = {
    "subject_type": "job_error",
    "load": _load_failed_job,
    "address": _job_error_address,
    "admit": _admit_failed_job,
    "build": _job_error_state,
    "as_of": _finished_at,
    "what": _job,
}

#: Every set a ``jev_ask`` job asks, by name, and how. Exactly the registered
#: sets asked about text, and the one about a skeleton: the web sets, the two
#: title sets, from phase D2 the two findings sets, and from phase D3 the ops
#: set (``tests/unit/test_jev_jobs.py``). None but the web sets has a
#: follow-up: a hypothesis, a candidate, a finding or a job is changed by
#: nothing Jev answers, and a suggested owner, severity or cause is recorded
#: in the ledger alone (docs/09, section 6.1).
ASKABLE: Mapping[str, Askable] = MappingProxyType(
    {
        jev_questions.SCREEN_SET_NAME: Askable(**_EXCERPT, follow_up=_screen_follow_up),
        "research.catalogue": Askable(**_EXCERPT, follow_up=_excerpt_follow_up),
        "research.hypothesis": Askable(**_TITLE, follow_up=None),
        "guardrail.card": Askable(**_TITLE, follow_up=None),
        "findings.owner": Askable(**_FINDING, follow_up=None),
        "findings.severity": Askable(**_FINDING, follow_up=None),
        "ops.job_error": Askable(**_JOB_ERROR, follow_up=None),
    }
)


# ---------------------------------------------------------------------------
# The job
# ---------------------------------------------------------------------------


async def run_ask(
    conn: asyncpg.Connection, payload: dict[str, Any], api_key: str | None
) -> dict[str, Any]:
    """
    The ``jev_ask`` job: one set asked about one stored text, at most once an
    attempt. See the module docstring for every outcome.

    ``payload`` is ``{"set", "version", "subject_type", "subject_id",
    "source_id"}`` and the plans it was planned under (:data:`PLAN_KEYS`).
    Returns the subject, the plans, what the ask came to and, per question,
    what was measured — labels and numbers, never text; and a failure after
    the ask recorded a row carries the same record (:class:`JobFailedError`).
    """
    name, version, subject_type, subject_id, source_id, planned = _ask_payload(payload)
    askable = ASKABLE.get(name)
    question_set = jev_questions.REGISTRY.get(name)
    if askable is None or question_set is None:
        raise JobFailedError(
            f"a jev_ask job asks one of {sorted(ASKABLE)}, and this one names {name!r}",
            retry=False,
        )
    # Row 0 before row 1: a job naming a subject its set is not asked about is
    # malformed whatever version it names, and never merely superseded.
    if subject_type != askable.subject_type:
        raise JobFailedError(
            f"{name} is asked about a {askable.subject_type!r}, and this job "
            f"names a {subject_type!r}",
            retry=False,
        )
    asked_about = {
        "set": name,
        "version": version,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "source_id": source_id,
        **planned,
    }
    if version != question_set.version:
        logger.info(
            "jev_ask for %s v%s superseded: v%s is registered",
            name,
            version,
            question_set.version,
        )
        return {
            **asked_about,
            "status": "superseded",
            "registered_version": question_set.version,
        }
    plans = jev_prereg.plans_in_force(name, version)
    if plans is None:
        raise JobFailedError(
            f"{name} v{version} has no analysis plan (jev_prereg), and no answer "
            "is recorded with none in force; nothing was asked",
            retry=False,
        )
    if planned != plans:
        # Asked under other plans, every row this job records would be
        # recorded under plans its payload does not name.
        logger.info("jev_ask for %s superseded: its plans are no longer in force", name)
        return {**asked_about, "status": "superseded", "plans_in_force": plans}

    asked: jev_lane.AskResult | None = None
    try:
        row, asked = await _ask_once(
            conn, askable, question_set, subject_id, source_id, api_key
        )
        follow_up = askable.follow_up
        followed = {} if follow_up is None else await follow_up(conn, row, asked)
    except JobFailedError:
        raise
    except Exception as error:  # noqa: BLE001 - reported by class, never by message
        raise JobFailedError(
            f"asking {name} about the row {source_id!r} failed "
            f"({described(error)}); its text is not quoted",
            retry=True,
            result=_recorded(asked_about, asked),
        ) from None

    error, retry = ask_verdict(asked)
    if error is not None:
        raise JobFailedError(
            error + _quarantine_note(followed),
            retry=retry,
            result=_recorded(asked_about, asked, followed),
        )
    return _record(asked_about, asked, followed)


async def _ask_once(
    conn: asyncpg.Connection,
    askable: Askable,
    question_set: jev_questions.QuestionSet,
    subject_id: str,
    source_id: object,
    api_key: str | None,
) -> tuple[Mapping[str, Any], jev_lane.AskResult]:
    """
    Steps 4 to 7 of the module docstring's table, up to the answer: the row
    read, its text held to the subject, admitted, built into a state and asked
    about once. Returns the row and what the ask came to; :func:`run_ask` runs
    the follow-up and reads the verdict, so that a follow-up which fails still
    knows the answer it followed.
    """
    row = await askable.load(conn, source_id)
    if row is None:
        raise JobFailedError(
            f"the row {source_id!r} this job names is not stored; nothing was asked",
            retry=False,
        )
    what = askable.what(row)
    by_state = question_set.state_model in jev_questions.STATE_ADDRESSED
    if not by_state:
        _hold_to_subject(askable.address(row, None), subject_id, what)
    await askable.admit(conn, row)
    state = _built(askable, row, what)
    if by_state:
        _hold_to_subject(askable.address(row, state), subject_id, what)
    asked = await jev_lane.ask(
        conn,
        question_set=question_set,
        state=state,
        subject_type=askable.subject_type,
        subject_id=subject_id,
        as_of=askable.as_of(row),
        api_key=api_key,
        probe=False,
    )
    return row, asked


def _hold_to_subject(address: object, subject_id: str, what: str) -> None:
    """
    The row holds the subject the job names: a text's address before
    admission, a state's once it is built (``Askable.address``). Neither the
    text nor the state is quoted.
    """
    if address != subject_id:
        raise JobFailedError(
            f"{what} does not hold the text whose address this job names; "
            "nothing was asked",
            retry=False,
        )


def _record(
    asked_about: Mapping[str, Any],
    asked: jev_lane.AskResult,
    followed: Mapping[str, Any],
) -> dict[str, Any]:
    """
    What an attempt recorded, for the job's row: the subject, the plans it
    was asked under, what the ask came to and, per question, what was
    measured — labels and numbers, never text — and what the follow-up
    changed.
    """
    return {
        **asked_about,
        "status": asked.status,
        "request_id": asked.request_row_id,
        "replayed": asked.replayed,
        "answers": {key: _measured(answer) for key, answer in asked.answers.items()},
        **followed,
    }


def _recorded(
    asked_about: Mapping[str, Any],
    asked: jev_lane.AskResult | None,
    followed: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """
    :func:`_record` for an attempt that fails, where its ask wrote or read a
    row; ``None`` where it recorded nothing, so the queue keeps whatever an
    earlier attempt recorded (``job_repo.fail``).
    """
    if asked is None or asked.request_row_id is None:
        return None
    return _record(asked_about, asked, followed or {})


def _ask_payload(
    payload: object,
) -> tuple[str, int, str, str, object, dict[str, Any]]:
    """
    The nine names a ``jev_ask`` payload carries, checked, and nothing else:
    the set, its version, the subject, its row, and the plans, the last
    returned as a mapping by :data:`PLAN_KEYS`.
    """
    if not isinstance(payload, Mapping) or set(payload) != ASK_PAYLOAD_KEYS:
        raise JobFailedError(
            "a jev_ask job's payload is {set, version, subject_type, subject_id, "
            "source_id} and the plans it was planned under (plan_version, "
            "plan_hash, set_plan_version, set_plan_hash), and nothing else, and "
            "this one is not; nothing was asked",
            retry=False,
        )
    name, version = payload["set"], payload["version"]
    subject_type, subject_id = payload["subject_type"], payload["subject_id"]
    if (
        not isinstance(name, str)
        or not _is_count(version)
        or not isinstance(subject_type, str)
        or not _is_sha256(subject_id)
    ):
        raise JobFailedError(
            "a jev_ask job names a set by name, its version by number, and a "
            "subject by its type and the sha256 of its text; nothing was asked",
            retry=False,
        )
    planned = {key: payload[key] for key in PLAN_KEYS}
    if not (
        _is_count(planned["plan_version"])
        and _is_sha256(planned["plan_hash"])
        and _is_count(planned["set_plan_version"])
        and _is_sha256(planned["set_plan_hash"])
    ):
        raise JobFailedError(
            "a jev_ask job names each plan it was planned under by its version, "
            "a number, and its sha256; nothing was asked",
            retry=False,
        )
    return name, version, subject_type, subject_id, payload["source_id"], planned


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(ch in "0123456789abcdef" for ch in value)
    )


def _built(askable: Askable, row: Mapping[str, Any], what: str) -> BaseModel:
    """
    The state, built from the row, or a refusal that quotes none of it:
    pydantic's ``ValidationError`` repeats the input it refused, and a job's
    error is shown on the jobs page.
    """
    try:
        return askable.build(row)
    except ValidationError:
        raise JobFailedError(
            f"{what}'s text does not make the state its set is asked about, so "
            "nothing was asked; the validator's message quotes the text, and is "
            "not repeated",
            retry=False,
        ) from None


def _measured(answer: Any) -> dict[str, Any]:
    """One answer for the job's result: labels and numbers, never text."""
    measured = {
        "valid": answer.valid,
        "invalid_reason": answer.invalid_reason,
        "argmax": answer.argmax,
        "margin": answer.margin,
    }
    if answer.question_type == "noul":
        measured["noul"] = answer.noul
    return measured


def _quarantine_note(followed: Mapping[str, Any]) -> str:
    if not followed.get("quarantined"):
        return ""
    return f"; its content is quarantined ({followed['quarantined']} documents)"


# ---------------------------------------------------------------------------
# Re-asks
# ---------------------------------------------------------------------------


async def run_reask(
    conn: asyncpg.Connection, payload: dict[str, Any], api_key: str | None
) -> dict[str, Any]:
    """
    The ``jev_reask`` job: ask one canonical request again, once, as a probe.

    The payload names the request, ``{"request_id": N}``, and nothing else is
    read from it. The request must be canonical — ``ok``, outside the probe
    lane — or the job fails without a retry. It completes ``superseded``, asking
    nothing, when its set is no longer registered, the registered set's pack is
    not the one it was asked under, or the pinned model is not the one that
    answered: an answer to other words, or from another judge, measures
    nothing about this one. Otherwise its state is rebuilt from the row through
    the set's own state model, and asked about the row's own subject and
    instant through the road, every switch and refusal applying as to any ask.

    Web text is read through the code screen first, as ``run_ask`` reads it:
    content quarantined since is asked nothing, and text the screen now flags
    is quarantined and asked nothing (:func:`screen_stored_excerpt`). And a
    content block met by a re-ask of web text quarantines it
    (:func:`quarantine_if_blocked`). Web text only: a hypothesis title is held
    by the road, and no document holds it. The answer itself never
    quarantines anything: a probe measures. Since a state may now hold text, a
    state that no longer validates fails the job without quoting the
    validator, and anything else the screen, the ask or the follow-up raises
    is reported by its class alone and retried, as in :func:`run_ask`.

    Returns the two requests and, per question, whether the argmax moved:
    ``None`` where either answer was not measured, which is neither a flip nor
    agreement.
    """
    request_id = payload.get("request_id")
    if isinstance(request_id, bool) or not isinstance(request_id, int):
        raise JobFailedError(
            f"a re-ask names its request by id, got {request_id!r}", retry=False
        )
    canonical = await jev_repo.get_request(conn, request_id)
    if canonical is None:
        raise JobFailedError(f"request {request_id} is not in the ledger", retry=False)
    if canonical["status"] != "ok" or canonical["lane"] == jev_lane.PROBE_LANE:
        raise JobFailedError(
            f"request {request_id} is a {canonical['status']} row in lane "
            f"{canonical['lane']!r}, not a canonical answer; only a canonical "
            "answer is re-asked",
            retry=False,
        )

    question_set = jev_questions.REGISTRY.get(canonical["question_set"])
    model = await flags.jev_model(conn)
    superseded = _superseded(canonical, question_set, model)
    if superseded is not None:
        logger.info("Re-ask of request %s superseded: %s", request_id, superseded)
        return {"request_id": request_id, "status": "superseded", "why": superseded}
    assert question_set is not None  # _superseded says so otherwise

    try:
        result, followed = await _reask_once(conn, canonical, question_set, api_key)
    except JobFailedError:
        raise
    except Exception as error:  # noqa: BLE001 - reported by class, never by message
        raise JobFailedError(
            f"re-asking request {request_id} failed ({described(error)}); its "
            "state is not quoted",
            retry=True,
        ) from None
    error, retry = ask_verdict(result)
    if error is not None:
        raise JobFailedError(error + _quarantine_note(followed), retry=retry)
    recorded = {
        row["question_key"]: row for row in await jev_repo.answers_for(conn, request_id)
    }
    flipped: dict[str, bool | None] = {}
    for key, answer in result.answers.items():
        first = recorded.get(key)
        if first is None or not first["valid"] or not answer.valid:
            flipped[key] = None
        else:
            flipped[key] = answer.argmax != first["argmax"]
    return {
        "request_id": request_id,
        "probe_request_id": result.request_row_id,
        "status": result.status,
        "flipped": flipped,
        **followed,
    }


async def _reask_once(
    conn: asyncpg.Connection,
    canonical: Mapping[str, Any],
    question_set: jev_questions.QuestionSet,
    api_key: str | None,
) -> tuple[jev_lane.AskResult, dict[str, Any]]:
    """
    One re-ask of ``canonical``: web text through the code screen, the state
    rebuilt, the one ask as a probe, and, for web text, the content-block
    follow-up. Returns what the ask came to and what the follow-up changed.
    """
    request_id = canonical["id"]
    web = question_set.state_model in jev_questions.WEB_STATE_MODELS
    if web:
        await screen_stored_excerpt(
            conn,
            canonical["subject_id"],
            canonical["state"]["excerpt"],
            f"the excerpt request {request_id} asked about",
        )
    try:
        state = question_set.state_model.model_validate_json(
            json.dumps(canonical["state"], ensure_ascii=False)
        )
    except ValidationError:
        raise JobFailedError(
            f"request {request_id}'s state does not make {question_set.name}'s "
            "state, so nothing was asked; the validator's message quotes the "
            "state, and is not repeated",
            retry=False,
        ) from None
    result = await jev_lane.ask(
        conn,
        question_set=question_set,
        state=state,
        subject_type=canonical["subject_type"],
        subject_id=canonical["subject_id"],
        as_of=canonical["as_of"],
        api_key=api_key,
        probe=True,
    )
    followed = (
        await quarantine_if_blocked(conn, canonical["subject_id"], result)
        if web
        else {}
    )
    return result, followed


def _superseded(
    canonical: Mapping[str, Any],
    question_set: jev_questions.QuestionSet | None,
    model: str | None,
) -> str | None:
    """Why a canonical request can no longer be asked again as itself, or None."""
    if question_set is None:
        return f"{canonical['question_set']} is no longer registered"
    if question_set.pack_hash != canonical["pack_hash"]:
        return (
            f"{question_set.name} is registered as v{question_set.version}, "
            f"not the v{canonical['question_set_version']} this answered"
        )
    # No usable pin is not another pin: the road refuses the ask itself, and
    # the job fails saying so, rather than retiring the re-ask as superseded.
    if model is not None and jev_catalogue.model_problem(model) is None:
        if model != canonical["model_requested"]:
            return (
                f"the pin is {model}, and this was asked of "
                f"{canonical['model_requested']}"
            )
    return None


__all__ = [
    "ASKABLE",
    "ASK_PAYLOAD_KEYS",
    "CONTENT_BLOCK_REASON",
    "NOT_ASKED",
    "PLAN_KEYS",
    "SCREEN_REASON",
    "Askable",
    "ask_verdict",
    "quarantine_if_blocked",
    "run_ask",
    "run_reask",
    "screen_stored_excerpt",
]
