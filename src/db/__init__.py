"""
db
--
Database access for the systematic engine.

``repos`` holds one query module per concern. Import from there rather than
from this package: a wildcard surface invites the next person to reach for
whatever is exported, which is how the legacy ``get_daily_pnl`` — a function
that summed cash flow and called it P&L — stayed reachable long after it was
known to be wrong.

That function, the rest of ``repositories.py`` and the ``DatabasePool`` wrapper
were deleted along with the crypto agent pipeline they served. The engine uses
asyncpg pools directly (``src/api/deps.py``, ``src/worker/main.py``) and gets
its P&L from ``repos.marks``.
"""

from src.db import repos  # noqa: F401

__all__ = ["repos"]
