"""
flags.py
--------
The programme's switch, the identity it reports liveness under, and the
switches for TypeSafe AI's Jev.

Its own module for a structural reason rather than a tidiness one. The API
needs to read this switch to render the control, and the runner needs to read
it to decide whether to act — but the API must not import the runner, which
transitively pulls in the model client and the whole tick. Two modules needing
one constant is how a process ends up importing a package it has no business
holding. The Jev switches are here for the same reason: ``jev_lane`` reads
them before every request, the configuration page will render them, and
``jev_lane`` and ``jev_client`` are runner-only, the second being the one
module that holds TypeSafe's SDK.

Fail closed, exactly like ``flags.trading_enabled``. It would be easy to argue
the stakes are lower here, since this process writes rows rather than placing
orders. That is wrong twice over: a runaway programme fills the job queue the
live decision path shares, and it spends money at a model API on every pass. A
control that defaults to "go" when it cannot determine the answer is not a
control, whatever it is controlling.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import asyncpg

from src.db.repos import flags as flag_repo
from src.programme import jev_catalogue, models

logger = logging.getLogger(__name__)

#: Seeded ``false`` by migration 0007.
PROGRAMME_ENABLED = "programme_enabled"

#: Which model the programme is pointed at, how hard it is asked to think, and
#: the token ceiling on a reply. Seeded by migration 0010.
PROGRAMME_PROVIDER = "programme_provider"
PROGRAMME_MODEL = "programme_model"
PROGRAMME_EFFORT = "programme_effort"
PROGRAMME_MAX_TOKENS = "programme_max_tokens"

#: How long between scheduled passes. Seeded by migration 0010.
PROGRAMME_TICK_SECONDS = "programme_tick_seconds"

#: Every key this module owns, in the order the configuration page renders them.
SETTING_KEYS = (
    PROGRAMME_PROVIDER,
    PROGRAMME_MODEL,
    PROGRAMME_EFFORT,
    PROGRAMME_MAX_TOKENS,
    PROGRAMME_TICK_SECONDS,
)

#: How far the runner may promote without an operator. Seeded ``0`` by
#: migration 0008.
PROGRAMME_MAX_AUTO_STAGE = "programme_max_auto_stage"

#: What an unreadable ceiling is read as: promote nothing.
NO_AUTOMATIC_PROMOTION = 0

#: The programme writes liveness into ``worker_heartbeats`` under this id
#: rather than into a table of its own, so the API's existing staleness
#: derivation covers it without a second rule that could disagree with the
#: first.
PROGRAMME_WORKER_ID = "programme"


async def programme_enabled(conn: asyncpg.Connection) -> bool:
    """
    Whether the programme may act. Any failure to establish it means no.

    Deliberately not derived from ``trading_enabled``: they are separate
    switches, and an operator who halts trading has not necessarily halted
    research. Deriving one from the other would make a single flag do two jobs
    and make it harder to reason about either — the same mistake the broker
    factory once made with the three live-trading gates.
    """
    try:
        value = await flag_repo.get_flag(conn, PROGRAMME_ENABLED)
    except Exception as exc:  # noqa: BLE001 - deliberately broad; see docstring
        logger.error(
            "Cannot read the programme switch (%s); treating it as DISABLED", exc
        )
        return False
    return value is True


async def max_auto_stage(conn: asyncpg.Connection) -> int:
    """
    The highest stage the runner may promote into without an operator.

    Clamped to ``[0, FIRST_HUMAN_GATED_STAGE - 1]`` on the way out, so the
    stored value is a ceiling within a ceiling. Two independent limits rather
    than one: a single number in a database row is one mistaken ``UPDATE`` away
    from authorising a model to move capital, and the constant in
    :mod:`src.programme.gates` cannot be changed by an UPDATE at all.

    Anything that is not an integer — a missing row, a string, a null, a
    database error — is read as zero. Fail closed, in the direction of
    promoting nothing.
    """
    from src.programme.gates import FIRST_HUMAN_GATED_STAGE

    ceiling = FIRST_HUMAN_GATED_STAGE - 1
    try:
        value = await flag_repo.get_flag(conn, PROGRAMME_MAX_AUTO_STAGE)
    except Exception as exc:  # noqa: BLE001 - deliberately broad; see docstring
        logger.error("Cannot read the autonomy ceiling (%s); promoting nothing", exc)
        return NO_AUTOMATIC_PROMOTION
    if isinstance(value, bool) or not isinstance(value, int):
        # `True` is an int in Python and is not a stage. A ceiling that reads
        # as 1 because someone stored a boolean is exactly the kind of quiet
        # wrongness this whole module exists to refuse.
        if value is not None:
            logger.error(
                "Autonomy ceiling is not an integer (%r); promoting nothing",
                value,
            )
        return NO_AUTOMATIC_PROMOTION
    return max(NO_AUTOMATIC_PROMOTION, min(int(value), ceiling))


async def model_settings(conn: asyncpg.Connection) -> models.ModelSettings | None:
    """
    What the programme should send, or ``None`` if that cannot be established.

    ``None`` means **make no model call**, and that is the fail-closed direction
    here rather than an obvious one, so it is worth stating why. The tempting
    alternative is to fall back to the module defaults on an unreadable row. But
    the runner is not paralysed without a model: reconciliation, gate evaluation
    and promotion all run without one, and a tick that does them and records
    that it could not reach a model is a correct tick. Substituting a default
    instead spends money at a vendor under a configuration nobody chose, and
    writes the result into the ledger as though somebody had. Between "do less"
    and "spend under a guess", the control has to pick the first.

    A missing row is treated the same way. Migration 0010 seeds all four, so an
    absent one means something removed it, and inventing a replacement is how a
    deleted setting stops looking like a deleted setting.
    """
    try:
        stored = {
            key: await flag_repo.get_flag(conn, key)
            for key in (
                PROGRAMME_PROVIDER,
                PROGRAMME_MODEL,
                PROGRAMME_EFFORT,
                PROGRAMME_MAX_TOKENS,
            )
        }
    except Exception as exc:  # noqa: BLE001 - deliberately broad; see docstring
        logger.error("Cannot read the model settings (%s); no model call", exc)
        return None

    problem = models.settings_problem(
        stored[PROGRAMME_PROVIDER],
        stored[PROGRAMME_MODEL],
        stored[PROGRAMME_EFFORT],
        stored[PROGRAMME_MAX_TOKENS],
    )
    if problem is not None:
        logger.error("Model settings are unusable (%s); no model call", problem)
        return None
    return models.build_settings(
        stored[PROGRAMME_PROVIDER],
        stored[PROGRAMME_MODEL],
        stored[PROGRAMME_EFFORT],
        stored[PROGRAMME_MAX_TOKENS],
    )


async def tick_seconds(conn: asyncpg.Connection) -> int:
    """
    How long between scheduled passes.

    Falls back to the documented default rather than to zero, because this one
    is not a safety control in the same direction as the others: an unreadable
    value that halted the loop would take the programme down over a setting,
    while an unreadable value that ticks hourly costs at most one pass an hour
    — and every pass is still gated by ``programme_enabled`` and by
    ``model_settings`` above, both of which fail closed. Failing *slow* is the
    conservative direction for a cadence.
    """
    try:
        value = await flag_repo.get_flag(conn, PROGRAMME_TICK_SECONDS)
    except Exception as exc:  # noqa: BLE001 - deliberately broad; see docstring
        logger.error("Cannot read the tick interval (%s); using the default", exc)
        return models.DEFAULT_TICK_SECONDS

    problem = models.tick_seconds_problem(value)
    if problem is not None:
        logger.error("Tick interval is unusable (%s); using the default", problem)
        return models.DEFAULT_TICK_SECONDS
    return int(value)


# ---------------------------------------------------------------------------
# Jev
# ---------------------------------------------------------------------------
#
# Every key below is seeded by migration 0012 in its off position, and every
# reader treats what it cannot establish as that position. None of them
# substitutes a default: a setting that cannot be read means no request, never
# a request made under a value nobody chose.

#: The master switch. While it is off Jev is asked nothing, the connectivity
#: probe included. Seeded ``false``.
JEV_ENABLED = "jev_enabled"

#: The one model a request may name. Seeded ``"jev-1.13.0"``.
JEV_MODEL = "jev_model"

#: One switch per area of work, ``jev_area_<area>`` for each of
#: :data:`jev_catalogue.AREAS`. Seeded ``false``.
JEV_AREA_PREFIX = "jev_area_"

#: How many requests the programme may send TypeSafe in a UTC day. Seeded
#: ``500``.
JEV_DAILY_REQUEST_BUDGET = "jev_daily_request_budget"

#: The largest state, in estimated tokens, one request may carry. Seeded
#: ``8000``.
JEV_MAX_STATE_TOKENS = "jev_max_state_tokens"

#: Whether hypothesis cards and findings are sent in full rather than as
#: titles. Seeded ``false``.
JEV_SEND_INTERNAL_DETAIL = "jev_send_internal_detail"

#: Every key the Jev readers consult. The area switches are derived from the
#: catalogue, so an area cannot be added there without its switch appearing
#: here, and ``tests/unit/test_jev_flags.py`` holds the whole set to what
#: migration 0012 seeds. The reason is the failure mode: a reader pointed at a
#: key nobody seeded reads as off forever, and says nothing about it.
JEV_KEYS: tuple[str, ...] = (
    JEV_ENABLED,
    *(f"{JEV_AREA_PREFIX}{area}" for area in jev_catalogue.AREAS),
    JEV_MODEL,
    JEV_DAILY_REQUEST_BUDGET,
    JEV_MAX_STATE_TOKENS,
    JEV_SEND_INTERNAL_DETAIL,
)

#: What a count that cannot be established is read as. A real setting rather
#: than a sentinel: a budget of zero permits no request and a state limit of
#: zero admits none, which is the direction every doubt should fall.
NO_JEV_REQUESTS = 0


async def _switch(conn: asyncpg.Connection, key: str) -> bool:
    """
    Whether the Jev switch ``key`` is on: a stored JSON ``true``, and nothing
    else.

    ``programme_enabled``'s rule, written once for every Jev switch so that
    none of them can drift into reading ``"true"`` or ``1`` as on. Both are
    plausible things for a hand-written ``UPDATE`` to store, and a switch that
    came on because of one is a switch nobody turned on.
    """
    try:
        value = await flag_repo.get_flag(conn, key)
    except Exception as exc:  # noqa: BLE001 - deliberately broad; see the module
        logger.error("Cannot read %s (%s); treating it as OFF", key, exc)
        return False
    if value is not None and not isinstance(value, bool):
        # Said out loud, because an operator who stored the string "true" has
        # every reason to believe the switch is on.
        logger.error("%s is not a boolean (%r); treating it as OFF", key, value)
    return value is True


async def jev_enabled(conn: asyncpg.Connection) -> bool:
    """
    Whether Jev may be asked anything at all. Any failure to establish it
    means no.

    Above every area switch and the probe, so that one control stops every
    request without an operator having to find six others under pressure.

    Deliberately not derived from ``programme_enabled``, in either direction,
    for the reason ``programme_enabled`` is not derived from the kill switch:
    they are separate controls, and one flag doing two jobs makes both harder
    to reason about. A caller that must respect both asks both.
    """
    return await _switch(conn, JEV_ENABLED)


async def jev_area_enabled(conn: asyncpg.Connection, area: str) -> bool:
    """
    Whether Jev may work in ``area``: the master switch and the area's own
    switch, each a stored JSON ``true``.

    Two switches because they answer different questions. The area switch
    says the operator wants Jev's help with, say, findings; the master switch
    says Jev may be called at all, and turning it off has to stop every area
    without anyone remembering which of them were on.

    ``area`` must be one of :data:`jev_catalogue.AREAS`. Anything else — a
    lane's name where its area's belongs (``"guardrail"`` for
    ``"guardrails"``), another case, a typo — is off, and no row is read for
    it: a key built from an unknown name is a row migration 0012 never seeded,
    which reads as off today and as on the day somebody inserts it by hand to
    make a lane work. :data:`jev_catalogue.LANE_AREA` maps each lane to its
    area.
    """
    if not isinstance(area, str) or area not in jev_catalogue.AREAS:
        logger.error(
            "%r is not a Jev area (the areas are %s); treating it as OFF",
            area,
            ", ".join(jev_catalogue.AREAS),
        )
        return False
    if not await jev_enabled(conn):
        return False
    return await _switch(conn, f"{JEV_AREA_PREFIX}{area}")


async def jev_model(conn: asyncpg.Connection) -> str | None:
    """
    The model every Jev request names, or ``None``, meaning no request.

    Only a versioned id the catalogue knows comes back, and the catalogue's
    own rule, :func:`jev_catalogue.model_problem`, decides it, so the
    configuration form and the runner cannot disagree about what is allowed.
    The alias is the case that matters. ``jev-latest`` names whatever TypeSafe
    released last, every threshold here is measured per model, and an answer
    recorded under an alias belongs to a model nobody could name afterwards.

    No default is substituted, for the reason ``model_settings`` gives: a
    missing row means something removed it, and a request made under
    :data:`jev_catalogue.DEFAULT_MODEL` regardless would be made under a
    setting nobody chose, and recorded as though somebody had.
    """
    try:
        value = await flag_repo.get_flag(conn, JEV_MODEL)
    except Exception as exc:  # noqa: BLE001 - deliberately broad; see the module
        logger.error("Cannot read %s (%s); no Jev request", JEV_MODEL, exc)
        return None
    if value is None:
        logger.error("%s is missing or null; no Jev request", JEV_MODEL)
        return None
    problem = jev_catalogue.model_problem(value)
    if problem is not None:
        logger.error("%s is unusable (%s); no Jev request", JEV_MODEL, problem)
        return None
    return value


def _budget_problem(value: object) -> str | None:
    # The catalogue's one rule for the three settings, asked about the budget
    # alone. The model and the state limit are given values it documents as
    # legal, its own default and zero, so any sentence it returns is about the
    # budget — and the form, which asks the same function, cannot accept a
    # budget the runner refuses or the other way round.
    return jev_catalogue.settings_problem(jev_catalogue.DEFAULT_MODEL, value, 0)


def _state_limit_problem(value: object) -> str | None:
    # As `_budget_problem`, asked about the state limit.
    return jev_catalogue.settings_problem(jev_catalogue.DEFAULT_MODEL, 0, value)


async def _count(
    conn: asyncpg.Connection, key: str, problem_of: Callable[[object], str | None]
) -> int:
    """A whole-number Jev setting, or :data:`NO_JEV_REQUESTS`."""
    try:
        value = await flag_repo.get_flag(conn, key)
    except Exception as exc:  # noqa: BLE001 - deliberately broad; see the module
        logger.error("Cannot read %s (%s); reading it as 0, no Jev request", key, exc)
        return NO_JEV_REQUESTS
    problem = problem_of(value)
    if problem is not None:
        logger.error(
            "%s is unusable (%s); reading it as 0, no Jev request", key, problem
        )
        return NO_JEV_REQUESTS
    return value


async def jev_daily_request_budget(conn: asyncpg.Connection) -> int:
    """
    How many requests the programme may send TypeSafe in a UTC day, where zero
    means none.

    Zero on a database error, a missing row, and anything the catalogue
    refuses: a boolean (``True`` is an int in Python and is not a count), a
    string, a float, a negative number, or a figure above
    :data:`jev_catalogue.MAX_DAILY_REQUEST_BUDGET`. The rule is applied here,
    at the runner, and not only at the form, because a row can be written by
    something other than the form, and this one exists to bound spend in a
    process nobody is watching.

    Above the ceiling reads as zero rather than as the ceiling. Clamping would
    permit the largest spend the catalogue allows on the strength of a value it
    refuses, and a setting that quietly corrects itself is one an operator
    cannot reason about. Zero stops the calls, and the log says why.
    """
    return await _count(conn, JEV_DAILY_REQUEST_BUDGET, _budget_problem)


async def jev_max_state_tokens(conn: asyncpg.Connection) -> int:
    """
    The largest state, in estimated tokens, a request may carry, where zero
    refuses every request.

    Zero on the same failures as the budget, and above
    :data:`jev_catalogue.MAX_STATE_PLUS_LONGEST_QUESTION`, the catalogue's
    limit on a state and its longest question together, since a larger state
    could not be sent with any question at all.
    :func:`jev_catalogue.request_size_problem` refuses every request under a
    limit of zero, so a limit nobody can read admits nothing, not even an empty
    state.
    """
    return await _count(conn, JEV_MAX_STATE_TOKENS, _state_limit_problem)


async def jev_send_internal_detail(conn: asyncpg.Connection) -> bool:
    """
    Whether hypothesis cards and findings go to TypeSafe in full rather than
    as titles. Any failure to establish it means titles.

    The permissive direction is the one that sends more of this system's own
    text to a vendor whose zero-retention terms are for enterprise accounts
    only, and whose agreement lets it derive telemetry from whatever it is sent
    (docs/08-jev-integration.md, fact 7). An unreadable switch sends less.
    """
    return await _switch(conn, JEV_SEND_INTERNAL_DETAIL)
