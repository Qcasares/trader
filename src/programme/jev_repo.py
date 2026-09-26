"""
jev_repo.py
-----------
Every query the Jev ledger answers: what the lanes write, and what the control
plane will read.

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
from datetime import datetime
from typing import TYPE_CHECKING, Any

import asyncpg

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


async def requests_today(conn: asyncpg.Connection) -> int:
    """
    Calls made since UTC midnight, in every lane, probes included.

    What the daily budget is compared against, so it counts what costs: a row
    that records a call. Refusals are not calls, and a replay writes no row.
    """
    count = await conn.fetchval(
        f"SELECT COUNT(*) FROM jev_requests "
        f"WHERE available_at >= {_TODAY} AND status = ANY($1::text[])",
        list(CALL_STATUSES),
    )
    return int(count or 0)


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
