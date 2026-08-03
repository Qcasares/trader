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

logger = logging.getLogger(__name__)

#: Seeded ``false`` by migration 0007.
PROGRAMME_ENABLED = "programme_enabled"

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
