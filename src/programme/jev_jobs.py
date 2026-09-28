"""
jev_jobs.py
-----------
What becomes of a Jev job once its one ask has come back, and the re-ask job.

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
as the error (:func:`ask_verdict`): the probe's rule (``main.probe_verdict``),
for every other ask. Retried only where another attempt could change the
answer — no response, a rate limit or a vendor fault, or a switch turned off
while the job ran — and never for a standing refusal, which would be refused
again.

Re-asks measure the noise
~~~~~~~~~~~~~~~~~~~~~~~~~
Jev is not deterministic (docs/08, fact 1), so a threshold is only worth
something beside the rate at which its answers flip. :func:`run_reask` asks a
canonical request's exact state and questions again, as a probe: recorded in
the probe lane, never replayed and never the answer anybody reads, and spent
from the probe lane's share of the budget. The requests re-asked are the
pre-registered sample (``jev_prereg.reask_sample``), planned by ``jev_plan``;
the flip rates are the harness's to compute, from the pairs the ledger holds.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

import asyncpg

from src.programme import flags, jev_catalogue, jev_lane, jev_questions, jev_repo
from src.programme.job_errors import RETRIED_ERROR_KINDS, JobFailedError

logger = logging.getLogger(__name__)

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


def ask_verdict(result: jev_lane.AskResult) -> tuple[str | None, bool]:
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

    state = question_set.state_model.model_validate_json(
        json.dumps(canonical["state"], ensure_ascii=False)
    )
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
    error, retry = ask_verdict(result)
    if error is not None:
        raise JobFailedError(error, retry=retry)
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
    }


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


__all__ = ["NOT_ASKED", "ask_verdict", "run_reask"]
