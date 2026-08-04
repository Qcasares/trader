"""
flags.py
--------
The programme's switch, and the identity it reports liveness under.

Its own module for a structural reason rather than a tidiness one. The API
needs to read this switch to render the control, and the runner needs to read
it to decide whether to act — but the API must not import the runner, which
transitively pulls in the model client and the whole tick. Two modules needing
one constant is how a process ends up importing a package it has no business
holding.

Fail closed, exactly like ``flags.trading_enabled``. It would be easy to argue
the stakes are lower here, since this process writes rows rather than placing
orders. That is wrong twice over: a runaway programme fills the job queue the
live decision path shares, and it spends money at a model API on every pass. A
control that defaults to "go" when it cannot determine the answer is not a
control, whatever it is controlling.
"""

from __future__ import annotations

import logging

import asyncpg

from src.db.repos import flags as flag_repo
from src.programme import models

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
        logger.error(
            "Cannot read the autonomy ceiling (%s); promoting nothing", exc
        )
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
