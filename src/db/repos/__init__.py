"""
repos
-----
Query modules for the systematic engine, one per concern.

Kept separate from the legacy ``src/db/repositories.py``, which serves the
crypto agent pipeline and whose ``get_daily_pnl`` is unsalvageable — it sums
buy/sell cash flow, so a $100 purchase reads as a $100 loss. P&L here is a
change in marked equity, computed from ``daily_marks``.
"""

from src.db.repos import backtests, flags, jobs  # noqa: F401

__all__ = ["backtests", "flags", "jobs"]
