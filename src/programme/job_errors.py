"""
job_errors.py
-------------
How a programme job says it failed, which failed calls another attempt could
change, and what a job's one ask comes to as its verdict.

Its own module because every Jev handler needs it and the handlers are not
all in ``main.py``: the forward clock's (``jev_forward``) and the asks and
re-asks (``jev_jobs``) are modules of their own, and ``main`` imports them,
so the error they raise cannot live in ``main`` without a cycle. ``main``
re-exports :class:`JobFailedError`, so every existing import of it still
works. :func:`ask_verdict` moved here from ``jev_jobs`` in phase C7, which
re-exports it: ``jev_jobs`` now reads web text through the code screen, and
the forward clock, which reads ``ask_verdict`` too, may load no web module
at all (``test_import_boundaries.py::test_no_road_to_jev_reaches_the_road_to_the_web``).

Pure: the standard library, and nothing else. An ask's result is read by its
attributes, so the lane, which holds the client, is not imported.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


class JobFailedError(Exception):
    """
    A handler's verdict that its job failed, whether asking again could change
    it, and what the failed attempt recorded, where it recorded something.

    Raised rather than returned, so that a job whose work came to nothing is
    never recorded as ``succeeded`` with its reason buried in a result nobody
    reads. The jobs page shows status and error; this puts the verdict in both.

    ``result`` is for an attempt that wrote something worth naming before it
    failed: a ``jev_ask`` attempt whose ask recorded a row — a response refused
    whole, an answer whose follow-up failed — names the row and the analysis
    plans it was recorded under, so a job that failed still says under which
    plans its answer is to be scored. The programme writes it to the job's
    result beside the error, and an attempt that recorded nothing leaves an
    earlier one's in place (``job_repo.fail``).
    """

    def __init__(
        self, error: str, *, retry: bool, result: Mapping[str, Any] | None = None
    ) -> None:
        super().__init__(error)
        self.error = error
        self.retry = retry
        self.result = None if result is None else dict(result)


#: The failed calls another attempt could change: no response, a rate limit or
#: a vendor fault. A refused key, a refused request or an unreadable answer will
#: be refused again. ``tests/unit/test_job_ownership.py`` holds it to the
#: client's own vocabulary, ``jev_client.ERROR_KINDS``, which this module may
#: not import: only the lane and the key check import the client.
RETRIED_ERROR_KINDS: frozenset[str] = frozenset(
    {"connection", "timeout", "rate_limited", "server"}
)

#: Why each status that made no call made none, for a job's error. Only
#: ``disabled`` is retried: a switch turned off mid-job waits for the switch.
NOT_ASKED: Mapping[str, str] = {
    "disabled": "Jev, the programme or this set's area was switched off",
    "no_key": "no TypeSafe key is set (System > Configuration, or TYPESAFE_API_KEY)",
    "refused_model": "the model setting is not a usable pin",
    "refused_budget": (
        "no call is left today in the request budget or in this lane's share "
        "of it (jev_catalogue.LANE_BUDGET_PERCENT)"
    ),
    "refused_limits": "the request is over the size limits",
    "auth_held": (
        "an authentication failure was recorded today; asks resume at 00:00 UTC, "
        "and a key replaced since is proved before then only by the "
        "dispatch-only key check (jev-check.yml)"
    ),
    "set_refused": (
        "the vendor refused this set's request with a 422; a new version is needed"
    ),
    "content_blocked": "the vendor blocked this state's content; it is not sent again",
    "quarantined": "the text is quarantined, and nothing asks about it again",
    "unscreened": "the text has no clean answer from the injection screen",
}


class Asked(Protocol):
    """What :func:`ask_verdict` reads of ``jev_lane.AskResult``."""

    @property
    def status(self) -> str: ...

    @property
    def request_row_id(self) -> int | None: ...

    @property
    def error_kind(self) -> str | None: ...


def ask_verdict(result: Asked) -> tuple[str | None, bool]:
    """
    ``(None, False)`` for an ask that recorded an answer, ``ok``; otherwise the
    job's error and whether to try again.

    ``invalid`` — the response refused whole — fails without a retry: what the
    model sent is recorded, and asking again would buy a second answer rather
    than check the first. An ``error`` is retried only for no response, a rate
    limit or a vendor fault (:data:`RETRIED_ERROR_KINDS`), and a switch turned
    off mid-job waits for the switch; every other status is a standing state
    or a refusal that would be given again.
    """
    status = result.status
    where = (
        "" if result.request_row_id is None else f" (request {result.request_row_id})"
    )
    if status == "ok":
        return None, False
    if status == "invalid":
        return f"the response was refused whole{where}", False
    if status == "error":
        kind = result.error_kind
        return f"the call failed: {kind}{where}", kind in RETRIED_ERROR_KINDS
    reason = NOT_ASKED.get(str(status), f"it came to {status!r}")
    return f"nothing was asked: {reason}{where}", status == "disabled"


def described(error: BaseException) -> str:
    """
    An error by its class, its SQLSTATE and the constraint it names, and
    nothing it said: a driver's message can quote the value it could not take
    — asyncpg's ``DataError`` repeats the argument — and a job's error is shown
    on the jobs page, where web text and titles may not go.
    """
    parts = [type(error).__name__]
    sqlstate = getattr(error, "sqlstate", None)
    if isinstance(sqlstate, str) and sqlstate:
        parts.append(f"SQLSTATE {sqlstate}")
    constraint = getattr(error, "constraint_name", None)
    if isinstance(constraint, str) and constraint:
        parts.append(f"constraint {constraint}")
    return ", ".join(parts)


__all__ = [
    "NOT_ASKED",
    "RETRIED_ERROR_KINDS",
    "Asked",
    "JobFailedError",
    "ask_verdict",
    "described",
]
