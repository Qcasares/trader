"""
jev_repo.py
-----------
Every query the Jev ledger answers: what the lanes write, and what the control
plane will read; and, for the forward clock, its planner and the harness, what
the queue says about their jobs, since a job's error is the durable record of
why a session went unmeasured.

No SDK and no model client, so ``src/api`` may import it. It reads and writes
rows and knows nothing about how an answer was obtained: ``jev_client``, which
holds the SDK, and ``jev_lane``, which calls it, sit above it, and nothing here
imports either.

The tables are append-only by trigger (migration 0012), so there is no update
and no delete here to find. Three conventions carry the weight:

* **A request and its answers are one write.** :func:`record_exchange` writes
  both in one transaction, which inside a caller's transaction is a savepoint.
  Written apart, a failure between them would leave an ``ok`` request with no
  answers. The replay would read it as a call that answered nothing, and the
  canonical index would refuse the real answer every time it was asked again,
  so the hole would be permanent.

* **The canonical answer is looked up, never asked for twice.**
  :func:`find_canonical` returns the one ``ok`` row for a request hash outside
  the probe lane. Jev is not deterministic, so a second call would not check the
  first; it would be a second, different answer with an equal claim to be right.

* **Nothing unmeasured reads as zero.** A number the vendor sent that is not a
  finite real is stored as NULL, never coerced, and a latency percentile over no
  calls or a validity rate over no answers is ``None``.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

import asyncpg

from src.programme.jev_questions import SCREEN_CLEAR_ARGMAX, SCREEN_QUESTION

if TYPE_CHECKING:
    from src.programme.jev_validate import ValidatedAnswer

#: The partial unique index that makes an answer canonical: one ``ok`` row per
#: request hash, outside the probe lane. A lane that loses the race to record a
#: request gets a ``UniqueViolationError`` naming it, and replays the winner.
CANONICAL_INDEX = "jev_requests_canonical"

#: Statuses that record a call actually made, which are the ones the daily
#: budget spends. A refused row is a request that was never sent, and the schema
#: refuses one that carries a response.
CALL_STATUSES = ("ok", "invalid", "error")

#: What :func:`record_answers` reads from each answer, in column order. They are
#: the fields of ``jev_validate.ValidatedAnswer``, and the integration suite
#: holds the two to each other. :func:`answers_for` returns rows carrying the
#: same names, so a replay can rebuild the answers it did not ask for again.
ANSWER_FIELDS = (
    "question_key",
    "question_type",
    "noul",
    "choice",
    "score",
    "probabilities",
    "confidence",
    "argmax",
    "margin",
    "valid",
    "invalid_reason",
)

#: The most rows one read returns. A read is a page for a screen, and nothing
#: needs the whole ledger in one response.
MAX_LIMIT = 500

#: UTC midnight today, by the database's clock. The daily budget resets here
#: and the status page counts from here. It is compared against
#: ``available_at``, which the database stamps, rather than ``requested_at``,
#: which the caller supplies: a budget counted from a column the caller chooses
#: is a budget the caller can dodge.
_TODAY = "date_trunc('day', now(), 'UTC')"


def is_canonical_conflict(exc: BaseException) -> bool:
    """
    Whether ``exc`` is another writer's canonical answer having arrived first.

    Only this violation means "replay the winner". Any other unique violation —
    two answers to one question, say — is a bug to surface, not a race to settle.
    """
    return (
        isinstance(exc, asyncpg.UniqueViolationError)
        and getattr(exc, "constraint_name", None) == CANONICAL_INDEX
    )


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


async def record_request(
    conn: asyncpg.Connection,
    *,
    request_hash: str,
    state_hash: str,
    question_set: str,
    question_set_version: int,
    pack_hash: str,
    lane: str,
    provenance: str,
    subject_type: str,
    subject_id: str,
    as_of: datetime,
    state: Any,
    questions: Mapping[str, Any],
    model_requested: str,
    status: str,
    requested_at: datetime | None = None,
    model_answered: str | None = None,
    vendor_request_id: str | None = None,
    http_status: int | None = None,
    error_class: str | None = None,
    error_kind: str | None = None,
    raw_body: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    latency_ms: int | None = None,
) -> int:
    """
    Write one request row and return its id.

    ``available_at`` is not a parameter. The database stamps it on insert, and a
    value offered here would be overwritten anyway; accepting one would only
    suggest otherwise. ``requested_at`` defaults to the database's clock, for a
    request refused before it could be sent.

    ``state`` and ``questions`` are the values that were sent — the objects the
    lane hashed, not JSON text of them — and are serialised here. The SDK takes
    text as a state as well as an object, so a string is stored as the JSON
    string it was sent as. The questions keep their order, options included,
    because the order is inside the request hash; the column is ``json`` rather
    than ``jsonb`` so that it stays kept. Neither may hold a NaN or an infinity,
    which JSON cannot spell and so no request can have carried.

    The schema checks the rest of the row against its status (see migration
    0012): an ``ok`` or ``invalid`` row carries the 2xx and the body it was
    validated from, an ``ok`` row was answered by the model it asked, and a row
    with no HTTP status carries nothing a response would have. A request row
    must not exist without its answers either (see the module docstring), so a
    caller writes it in one transaction with :func:`record_answers`, or calls
    :func:`record_exchange`, which does.
    """
    request_id = await conn.fetchval(
        """
        INSERT INTO jev_requests (
            request_hash, state_hash, question_set, question_set_version,
            pack_hash, lane, provenance, subject_type, subject_id, as_of,
            state, questions, model_requested, model_answered,
            vendor_request_id, http_status, status, error_class, error_kind,
            raw_body, input_tokens, output_tokens, latency_ms, requested_at
        )
        VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
            $11::jsonb, $12::json, $13, $14, $15, $16, $17, $18, $19,
            $20, $21, $22, $23, COALESCE($24::timestamptz, now())
        )
        RETURNING id
        """,
        request_hash,
        state_hash,
        question_set,
        question_set_version,
        pack_hash,
        lane,
        provenance,
        subject_type,
        subject_id,
        as_of,
        _sent_json(state),
        _sent_json(questions),
        model_requested,
        model_answered,
        vendor_request_id,
        http_status,
        status,
        error_class,
        error_kind,
        raw_body,
        input_tokens,
        output_tokens,
        latency_ms,
        requested_at,
    )
    return int(request_id)


async def record_answers(
    conn: asyncpg.Connection,
    request_id: int,
    answers: Sequence[ValidatedAnswer],
) -> None:
    """
    Write one row per answer, in the order given, which is the order asked.

    Invalid answers are written too, with their reason: an answer that failed
    validation is a fact about the model worth keeping, and downstream reads it
    as not measured. What the vendor sent is stored as sent wherever the column
    can hold it faithfully, and as NULL where it cannot. A NaN, an infinity or a
    boolean is not a number the column may hold — ``True`` stored as 1.0 is
    exactly the confusion the validator refuses — and JSON has no spelling for
    a non-finite number, so inside ``probabilities`` one is kept as its name.
    The verbatim body is on the request row either way.

    What this system computed — the key, the type, the argmax, validity and its
    reason — is written as given, so a wrong type is an error here rather than a
    NULL nobody notices. The margin is ours too, but a non-finite one measures
    nothing, so it is stored as NULL like any other. The schema then refuses a
    valid answer missing its value, argmax or margin, and a valid Choice that is
    not its own argmax.
    """
    if not answers:
        return
    await conn.executemany(
        """
        INSERT INTO jev_answers (
            request_id, question_key, question_type, noul, choice, score,
            probabilities, confidence, argmax, margin, valid, invalid_reason
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $10, $11, $12)
        """,
        [_answer_args(request_id, answer) for answer in answers],
    )


async def record_exchange(
    conn: asyncpg.Connection,
    request_fields: Mapping[str, Any],
    answers: Sequence[ValidatedAnswer],
) -> int:
    """
    Write a request and all its answers, or neither, and return the request id.

    ``request_fields`` are :func:`record_request`'s keyword arguments.

    One transaction; inside a caller's, a savepoint, which is also what is
    wanted — a failure takes this exchange's rows back and leaves the caller's
    transaction usable, so a lane that loses the race for the canonical row can
    go on to read the winner in the same transaction (see
    :func:`is_canonical_conflict`).

    An ``ok`` request with no answers is refused before anything is written. It
    is the one row the replay could never recover from: it would be found as
    canonical, answer nothing, and hold the index against the real answer.
    """
    if request_fields.get("status") == "ok" and not answers:
        raise ValueError(
            "an ok request must be recorded with its answers; an ok row with "
            "none would be replayed as a call that answered nothing"
        )
    async with conn.transaction():
        request_id = await record_request(conn, **request_fields)
        await record_answers(conn, request_id, answers)
    return request_id


async def record_label(
    conn: asyncpg.Connection,
    *,
    question_set: str,
    question_set_version: int,
    question_key: str,
    subject_type: str,
    subject_id: str,
    label: str,
    labelled_by: str,
    note: str | None = None,
) -> int:
    """
    Record one label and return its id.

    ``labelled_by`` is ``operator:<name>`` or ``source:<dataset>@<sha>``, and the
    schema refuses anything else — a model above all, since a label Jev wrote
    would measure its agreement with itself. A second label from the same
    labeller for the same item is a ``UniqueViolationError``: labels are ground
    truth, and ground truth revised after seeing the answers is not.
    """
    label_id = await conn.fetchval(
        """
        INSERT INTO jev_labels (
            question_set, question_set_version, question_key, subject_type,
            subject_id, label, labelled_by, note
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING id
        """,
        question_set,
        question_set_version,
        question_key,
        subject_type,
        subject_id,
        label,
        labelled_by,
        note,
    )
    return int(label_id)


# ---------------------------------------------------------------------------
# Reads for the lane
# ---------------------------------------------------------------------------


async def find_canonical(
    conn: asyncpg.Connection, request_hash: str
) -> dict[str, Any] | None:
    """
    The recorded answer to this exact request, or ``None`` if there is none.

    Only an ``ok`` row outside the probe lane is canonical. A probe re-asks on
    purpose and is never replayed; an invalid or failed request answered
    nothing that could be.
    """
    row = await conn.fetchrow(
        "SELECT * FROM jev_requests "
        "WHERE request_hash = $1 AND status = 'ok' AND lane <> 'probe'",
        request_hash,
    )
    return _decode_request(row) if row is not None else None


async def requests_today(conn: asyncpg.Connection, lane: str | None = None) -> int:
    """
    Calls made since UTC midnight: in every lane, probes included, or in the
    recorded ``lane`` alone.

    What the daily budget and each lane's slice of it are compared against, so
    it counts what costs: a row that records a call. Refusals are not calls,
    and a replay writes no row. A probe is recorded in the probe lane whatever
    its set, so it spends the probe lane's slice.
    """
    if lane is None:
        count = await conn.fetchval(
            f"SELECT COUNT(*) FROM jev_requests "
            f"WHERE available_at >= {_TODAY} AND status = ANY($1::text[])",
            list(CALL_STATUSES),
        )
    else:
        count = await conn.fetchval(
            f"SELECT COUNT(*) FROM jev_requests "
            f"WHERE available_at >= {_TODAY} AND status = ANY($1::text[]) "
            f"AND lane = $2",
            list(CALL_STATUSES),
            lane,
        )
    return int(count or 0)


# ---------------------------------------------------------------------------
# Reads for the road: what the vendor has refused, and what may be sent
# ---------------------------------------------------------------------------
#
# ``jev_lane.ask`` asks each of these before it sends anything. Each is
# derived from the ledger, so nothing writes a switch when the vendor refuses
# something: the refusal is a row, and the row is what holds. Each is answered
# from an index migration 0013 adds, so a road that grows a check per ask does
# not grow a scan per ask.


async def auth_failed_today(conn: asyncpg.Connection) -> bool:
    """
    Whether any call since UTC midnight failed authentication.

    A refused key is refused again on every call until somebody changes it, so
    one such failure holds every lane until 00:00 UTC rather than spending the
    day's budget learning the same thing (docs/08, fact 4). Counted from the
    database's stamp, like the budget. Nothing records which key failed, so a
    key replaced since is held until then as well; the operator's
    dispatch-only ``jev_check``, which records nothing, is what proves it.
    """
    return bool(
        await conn.fetchval(
            f"SELECT EXISTS (SELECT 1 FROM jev_requests "
            f"WHERE error_kind = 'auth' AND available_at >= {_TODAY})"
        )
    )


async def set_refused(
    conn: asyncpg.Connection, *, question_set: str, version: int, model: str
) -> bool:
    """
    Whether the vendor has refused a request of this set, at this version, to
    this model, as unprocessable (a 422).

    A 422 says the request itself is malformed by the vendor's reading, and the
    same words sent again will be refused again, so the set is held until a new
    version changes them — or a new pin, since another model is another judge.
    Permanent by design: a set held by a spurious 422 costs a reworded version,
    which is the safe direction (docs/08, fact 4).
    """
    return bool(
        await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM jev_requests "
            "WHERE question_set = $1 AND question_set_version = $2 "
            "AND model_requested = $3 AND error_kind = 'invalid_request')",
            question_set,
            version,
            model,
        )
    )


async def content_blocked(conn: asyncpg.Connection, state_hash: str) -> bool:
    """
    Whether a call about exactly this state was answered with a content block:
    a 403 whose body is not JSON (docs/08, fact 4).

    Matched by the state hash, across every set and lane, so text the vendor
    blocked for one question is not sent again for another. The lane asks it
    only about text, a web excerpt or a hypothesis title: an enumerated state
    has nothing in it a content filter could object to. An unverified
    precaution, resting on one third-party report; for text, holding is the
    safe direction.
    """
    return bool(
        await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM jev_requests "
            "WHERE state_hash = $1 AND error_kind = 'content_block')",
            state_hash,
        )
    )


async def content_quarantined(
    conn: asyncpg.Connection, content_sha256: str
) -> int | None:
    """
    The id of a quarantined document holding exactly this content, under any
    source, or ``None`` if there is none.

    Quarantine is by content: the same words stored from a second source are
    the same words, and a screen they could escape by moving would not be one.
    Exact because the schema holds ``content_sha256`` to be the sha256 of the
    document's ``excerpt`` (``web_documents_content_is_its_excerpt``, migration
    0013), which is ``jev_hash.text_sha256`` of the text a web set asks about;
    and indexed on quarantined documents alone, which is all this reads.
    """
    document_id = await conn.fetchval(
        "SELECT id FROM web_documents "
        "WHERE content_sha256 = $1 AND quarantined ORDER BY id LIMIT 1",
        content_sha256,
    )
    return int(document_id) if document_id is not None else None


async def screened_clean(
    conn: asyncpg.Connection, *, state_hash: str, pack_hash: str, model: str
) -> bool:
    """
    Whether the injection screen, in the version whose pack is ``pack_hash``
    and under ``model``, found exactly this state addressed to people.

    That is: a canonical request — ``ok``, outside the probe lane — about this
    state, from that pack, answered by that model, whose screen question has a
    valid answer whose argmax is the clear one. An answer that flagged the
    text, that was not measured, that another version or another model gave,
    or that a probe gave, is not clean: each leaves the text unscreened.
    """
    return bool(
        await conn.fetchval(
            "SELECT EXISTS ("
            " SELECT 1 FROM jev_requests r"
            " JOIN jev_answers a ON a.request_id = r.id"
            " WHERE r.state_hash = $1 AND r.pack_hash = $2"
            " AND r.status = 'ok' AND r.lane <> 'probe'"
            " AND r.model_answered = $3"
            " AND a.question_key = $4 AND a.valid AND a.argmax = $5)",
            state_hash,
            pack_hash,
            model,
            SCREEN_QUESTION,
            SCREEN_CLEAR_ARGMAX,
        )
    )


# ---------------------------------------------------------------------------
# Reads for the control plane
# ---------------------------------------------------------------------------


async def get_request(
    conn: asyncpg.Connection, request_id: int
) -> dict[str, Any] | None:
    row = await conn.fetchrow("SELECT * FROM jev_requests WHERE id = $1", request_id)
    return _decode_request(row) if row is not None else None


async def list_requests(
    conn: asyncpg.Connection,
    *,
    lane: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    The most recent requests, newest first, optionally of one lane or status.

    The filters are added only when given, rather than written as
    ``$1 IS NULL OR lane = $1``, which a prepared plan cannot use an index for.
    """
    clauses: list[str] = []
    args: list[Any] = []
    for column, value in (("lane", lane), ("status", status)):
        if value is not None:
            args.append(value)
            clauses.append(f"{column} = ${len(args)}")
    args.append(_page(limit))
    where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
    rows = await conn.fetch(
        f"SELECT * FROM jev_requests {where}ORDER BY id DESC LIMIT ${len(args)}",
        *args,
    )
    return [_decode_request(row) for row in rows]


async def answers_for(
    conn: asyncpg.Connection, request_id: int
) -> list[dict[str, Any]]:
    """Every answer recorded for a request, in the order the questions were asked."""
    rows = await conn.fetch(
        "SELECT * FROM jev_answers WHERE request_id = $1 ORDER BY id",
        request_id,
    )
    return [_decode_answer(row) for row in rows]


async def status_summary(conn: asyncpg.Connection) -> dict[str, Any]:
    """
    Today's traffic, from UTC midnight, for the status page.

    Counts are counts: a status or lane with no rows is simply absent, and reads
    as zero, which it is. The measurements are different. A latency percentile
    over no calls and a validity rate over no answers are ``None``, because
    nothing was measured, and 0 would report instant and perfectly invalid
    service. The validity rate is per answer rather than per request, so an
    ``ok`` request with one choice that was not its own argmax shows up in it.

    One statement, so every figure comes from the same snapshot: a page whose
    request count and validity rate were read a write apart would not add up.
    """
    row = await conn.fetchrow(
        f"""
        WITH today AS (
            SELECT id, lane, status, latency_ms
            FROM jev_requests
            WHERE available_at >= {_TODAY}
        ),
        calls AS (
            SELECT latency_ms
            FROM today
            WHERE status = ANY($1::text[]) AND latency_ms IS NOT NULL
        ),
        answers AS (
            SELECT a.valid
            FROM jev_answers a
            JOIN today t ON t.id = a.request_id
        )
        SELECT
            {_TODAY} AS since,
            (SELECT COALESCE(jsonb_agg(jsonb_build_array(lane, status, n)),
                             '[]'::jsonb)
               FROM (SELECT lane, status, COUNT(*) AS n
                       FROM today GROUP BY lane, status) AS grouped) AS counts,
            (SELECT COUNT(*) FROM calls) AS timed_calls,
            (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms)
               FROM calls) AS p50,
            (SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)
               FROM calls) AS p95,
            (SELECT COUNT(*) FROM answers) AS answers,
            (SELECT COUNT(*) FROM answers WHERE valid) AS valid_answers
        """,
        list(CALL_STATUSES),
    )
    by_status: dict[str, int] = {}
    by_lane: dict[str, int] = {}
    by_lane_status: dict[str, dict[str, int]] = {}
    for lane, status, n in _loads(row["counts"]):
        by_status[status] = by_status.get(status, 0) + int(n)
        by_lane[lane] = by_lane.get(lane, 0) + int(n)
        by_lane_status.setdefault(lane, {})[status] = int(n)
    answered = int(row["answers"])
    valid = int(row["valid_answers"])
    return {
        "since": row["since"],
        "requests": sum(by_status.values()),
        "calls": sum(by_status.get(status, 0) for status in CALL_STATUSES),
        "by_status": by_status,
        "by_lane": by_lane,
        "by_lane_status": by_lane_status,
        "latency_ms": {
            "n": int(row["timed_calls"]),
            "p50": row["p50"],
            "p95": row["p95"],
        },
        "answers": answered,
        "valid_answers": valid,
        "validity_rate": valid / answered if answered else None,
    }


# ---------------------------------------------------------------------------
# Reads for the forward clock, the planner and the harness (phase C4)
# ---------------------------------------------------------------------------
#
# Inside the programme only ``jev_lane`` writes ``jev_signals`` and only this
# module reads it (``tests/unit/test_jev_table_boundaries.py``), so every
# question anything asks of a signal is one of these.


async def signal_exists(
    conn: asyncpg.Connection, *, signal: str, symbol: str, session: date
) -> bool:
    """Whether a signal is recorded for this series and session, of any status."""
    return bool(
        await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM jev_signals "
            "WHERE signal = $1 AND symbol = $2 AND session = $3)",
            signal,
            symbol,
            session,
        )
    )


async def get_signal(
    conn: asyncpg.Connection, *, signal: str, symbol: str, session: date
) -> dict[str, Any] | None:
    """The signal recorded for this series and session, or ``None``."""
    row = await conn.fetchrow(
        "SELECT * FROM jev_signals WHERE signal = $1 AND symbol = $2 AND session = $3",
        signal,
        symbol,
        session,
    )
    return dict(row) if row is not None else None


async def signals_between(
    conn: asyncpg.Connection,
    *,
    signal: str,
    symbol: str,
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    """
    Every signal of one series with a session from ``start`` to ``end``
    inclusive, in session order, each with the answer it rests on and the
    request that answer came from: the request's id, hash, state hash, subject
    and state, and the answer's validity, reason, argmax and margin.

    A replayed session's request is the one first asked about another
    session, whose subject is that session: the harness reads a replay off
    exactly that. ``backfilled`` is the database's, generated from its own
    stamp, never a writer's.
    """
    rows = await conn.fetch(
        """
        SELECT s.signal, s.symbol, s.session, s.status, s.value, s.answer_id,
               s.lane, s.provenance, s.pack_hash, s.model, s.decision_cutoff,
               s.available_at, s.backfilled,
               a.question_key, a.valid, a.invalid_reason, a.argmax, a.margin,
               r.id AS request_id, r.request_hash, r.state_hash, r.subject_type,
               r.subject_id, r.state, r.status AS request_status,
               r.available_at AS answered_at
        FROM jev_signals s
        LEFT JOIN jev_answers a ON a.id = s.answer_id
        LEFT JOIN jev_requests r ON r.id = a.request_id
        WHERE s.signal = $1 AND s.symbol = $2
          AND s.session >= $3 AND s.session <= $4
        ORDER BY s.session
        """,
        signal,
        symbol,
        start,
        end,
    )
    found = []
    for row in rows:
        record = dict(row)
        record["state"] = _loads(record["state"])
        found.append(record)
    return found


async def canonical_requests_between(
    conn: asyncpg.Connection, *, start: datetime, end: datetime
) -> list[dict[str, Any]]:
    """
    The canonical requests — ``ok``, outside the probe lane — made readable
    from ``start`` up to but not including ``end``, by the database's stamp,
    each with the margins of its valid answers, which is what the re-ask
    sample's low-margin stratum reads (``jev_prereg.reask_stratum``).
    """
    rows = await conn.fetch(
        """
        SELECT r.id, r.request_hash, r.state_hash, r.question_set,
               r.question_set_version, r.pack_hash, r.lane, r.provenance,
               r.subject_type, r.subject_id, r.model_requested,
               r.model_answered, r.as_of, r.available_at,
               COALESCE(
                   array_agg(a.margin ORDER BY a.id)
                       FILTER (WHERE a.valid AND a.margin IS NOT NULL),
                   '{}'::double precision[]
               ) AS valid_margins
        FROM jev_requests r
        LEFT JOIN jev_answers a ON a.request_id = r.id
        WHERE r.status = 'ok' AND r.lane <> 'probe'
          AND r.available_at >= $1 AND r.available_at < $2
        GROUP BY r.id
        ORDER BY r.id
        """,
        start,
        end,
    )
    return [
        {**dict(row), "valid_margins": [float(m) for m in row["valid_margins"]]}
        for row in rows
    ]


async def probe_pairs(
    conn: asyncpg.Connection,
    *,
    question_set: str,
    version: int,
    question_key: str,
    model: str,
) -> list[dict[str, Any]]:
    """
    Each canonical answer to one question that was asked again, beside the
    re-ask: a probe of the same request hash and pack, asked of the model that
    answered, later. One row per canonical request, whatever became of its
    re-ask — answered and valid, refused whole, failed or refused before it
    was sent — since a flip rate counts the pairs whose two answers were both
    measured and says how many were not, and a re-ask left out of both would
    make a vendor that malformed every re-ask read as though none had been
    made. Where a re-ask job left more than one row (a failed attempt and a
    retry), the row that carries a response is the pair's, and otherwise the
    first.

    ``probe_status`` is the re-ask's request status; ``probe_valid`` and
    ``probe_argmax`` are ``None`` where it recorded no answer to this
    question. ``lag_seconds`` is the probe's stamp less the canonical one, both
    the database's.
    """
    rows = await conn.fetch(
        """
        SELECT DISTINCT ON (c.id)
               c.id AS canonical_request_id, c.request_hash,
               p.id AS probe_request_id, p.status AS probe_status,
               EXTRACT(EPOCH FROM (p.available_at - c.available_at))
                   AS lag_seconds,
               ca.valid AS canonical_valid, ca.argmax AS canonical_argmax,
               ca.margin AS canonical_margin,
               pa.valid AS probe_valid, pa.argmax AS probe_argmax
        FROM jev_requests c
        JOIN jev_answers ca ON ca.request_id = c.id AND ca.question_key = $3
        JOIN jev_requests p
          ON p.request_hash = c.request_hash AND p.pack_hash = c.pack_hash
         AND p.lane = 'probe'
         AND p.model_requested = c.model_answered
         AND p.available_at > c.available_at
        LEFT JOIN jev_answers pa ON pa.request_id = p.id AND pa.question_key = $3
        WHERE c.status = 'ok' AND c.lane <> 'probe'
          AND c.question_set = $1 AND c.question_set_version = $2
          AND c.model_answered = $4
        ORDER BY c.id, (p.status IN ('ok', 'invalid')) DESC, p.id
        """,
        question_set,
        version,
        question_key,
        model,
    )
    return [{**dict(row), "lag_seconds": float(row["lag_seconds"])} for row in rows]


async def probe_series(
    conn: asyncpg.Connection, *, question_set: str, since: datetime
) -> list[dict[str, Any]]:
    """
    Every probe of ``question_set`` recorded since ``since``, by the database's
    stamp, with its answers: the daily connectivity probe's series, a request
    that failed included, since a day it did not answer is part of the series.
    """
    rows = await conn.fetch(
        """
        SELECT r.id, r.available_at, r.status, r.question_set_version,
               r.model_requested, r.model_answered, r.error_kind,
               a.question_key, a.valid, a.noul, a.argmax, a.invalid_reason
        FROM jev_requests r
        LEFT JOIN jev_answers a ON a.request_id = r.id
        WHERE r.question_set = $1 AND r.lane = 'probe' AND r.available_at >= $2
        ORDER BY r.id, a.id
        """,
        question_set,
        since,
    )
    return [dict(row) for row in rows]


async def job_outcomes(
    conn: asyncpg.Connection, dedupe_keys: Sequence[str]
) -> dict[str, dict[str, Any]]:
    """
    The job row behind each of ``dedupe_keys`` that has one: its kind, status,
    attempts, error, times and result.

    A job's error is the durable record of why its work did not happen — for
    the forward clock, why a session is absent — since no row is written for
    a session it did not measure. A key with no job is not in the result.
    """
    if not dedupe_keys:
        return {}
    rows = await conn.fetch(
        """
        SELECT dedupe_key, kind, status, attempts, max_attempts, error, payload,
               result, scheduled_for, started_at, finished_at, created_at
        FROM jobs WHERE dedupe_key = ANY($1::text[])
        """,
        list(dedupe_keys),
    )
    found = {}
    for row in rows:
        job = dict(row)
        job["payload"] = _loads(job["payload"])
        job["result"] = _loads(job["result"])
        found[job["dedupe_key"]] = job
    return found


async def pending_jobs(conn: asyncpg.Connection, kinds: Sequence[str]) -> int:
    """How many jobs of ``kinds`` are queued or running: calls already coming."""
    count = await conn.fetchval(
        "SELECT COUNT(*) FROM jobs "
        "WHERE kind = ANY($1::text[]) AND status IN ('queued', 'running')",
        list(kinds),
    )
    return int(count or 0)


async def first_job_session(
    conn: asyncpg.Connection,
    kind: str,
    *,
    question_set: str | None = None,
    version: int | None = None,
) -> date | None:
    """
    The earliest session any job of ``kind`` was planned for, read from its
    payload, or ``None``: where the forward report's count of sessions starts.

    With ``question_set`` and ``version``, only the jobs whose payload names
    that set and version count: a version bump starts a new series, whose
    sessions begin at its own first job, not at the first job of the version
    before it, which would count every session between them as absent. A
    payload whose session is not a date, which only a hand-written row could
    carry, is skipped rather than allowed to fail the read.
    """
    rows = await conn.fetch(
        """
        SELECT DISTINCT payload->>'session' AS session FROM jobs
        WHERE kind = $1
          AND ($2::text IS NULL OR payload->>'set' = $2)
          AND ($3::int IS NULL OR payload->>'version' = $3::text)
        """,
        kind,
        question_set,
        version,
    )
    sessions = []
    for row in rows:
        try:
            sessions.append(date.fromisoformat(str(row["session"])))
        except ValueError:
            continue
    return min(sessions, default=None)


async def list_evaluations(
    conn: asyncpg.Connection,
    *,
    question_set: str | None = None,
    question_set_version: int | None = None,
    question_key: str | None = None,
    model: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    Recorded evaluations, newest first, narrowed by whatever is given.

    Measurements come back exactly as stored: ``None`` for one that was not
    measured, which a caller must render as such and never as 0.
    """
    clauses: list[str] = []
    args: list[Any] = []
    for column, value in (
        ("question_set", question_set),
        ("question_set_version", question_set_version),
        ("question_key", question_key),
        ("model", model),
    ):
        if value is not None:
            args.append(value)
            clauses.append(f"{column} = ${len(args)}")
    args.append(_page(limit))
    where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
    rows = await conn.fetch(
        f"SELECT * FROM jev_evaluations {where}"
        f"ORDER BY created_at DESC, id DESC LIMIT ${len(args)}",
        *args,
    )
    out = []
    for row in rows:
        evaluation = dict(row)
        for key in ("n_per_class", "calibration_bins"):
            evaluation[key] = _loads(evaluation[key])
        out.append(evaluation)
    return out


# ---------------------------------------------------------------------------
# Encoding and decoding
# ---------------------------------------------------------------------------


def _answer_args(request_id: int, answer: Any) -> tuple[Any, ...]:
    return (
        request_id,
        answer.question_key,
        answer.question_type,
        _finite(answer.noul),
        _text(answer.choice),
        _finite(answer.score),
        _json_or_none(answer.probabilities),
        _finite(answer.confidence),
        answer.argmax,
        _finite(answer.margin),
        answer.valid,
        answer.invalid_reason,
    )


def _sent_json(value: Any) -> str:
    """
    JSON text of a value that was sent, in the order it was sent.

    A mapping that is not a dict — a read-only view of a frozen question set,
    say — is written as the object it is rather than refused, and a non-finite
    number raises: no request could have carried one.
    """
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, default=_mapping_as_object
    )


def _mapping_as_object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError(f"{type(value).__name__} is not JSON a request could carry")


def _finite(value: Any) -> float | None:
    """A finite real number, or None. Never a coerced stand-in for one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _json_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(_representable(value), ensure_ascii=False, allow_nan=False)


def _representable(value: Any) -> Any:
    """``value`` with every non-finite float replaced by its name, recursively."""
    if isinstance(value, float) and not math.isfinite(value):
        if math.isnan(value):
            return "NaN"
        return "Infinity" if value > 0 else "-Infinity"
    if isinstance(value, Mapping):
        return {key: _representable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_representable(item) for item in value]
    return value


def _loads(value: Any) -> Any:
    """asyncpg hands json and jsonb over as text unless a codec is registered."""
    return json.loads(value) if isinstance(value, str) else value


def _decode_request(row: asyncpg.Record) -> dict[str, Any]:
    request = dict(row)
    request["state"] = _loads(request["state"])
    # json.loads keeps document order, and the column kept the order asked.
    request["questions"] = _loads(request["questions"])
    return request


def _decode_answer(row: asyncpg.Record) -> dict[str, Any]:
    answer = dict(row)
    answer["probabilities"] = _loads(answer["probabilities"])
    return answer


def _page(limit: int) -> int:
    return max(1, min(int(limit), MAX_LIMIT))
