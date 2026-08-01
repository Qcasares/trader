"""
repos
-----
Query modules for the systematic engine, one per concern.

These replaced ``src/db/repositories.py``, deleted with the crypto agent
pipeline it served. Its ``get_daily_pnl`` summed buy/sell cash flow, so a $100
purchase read as a $100 loss and any daily-loss breaker built on it tripped
after two trades regardless of performance. P&L here is a change in marked
equity, from ``daily_marks`` — see ``marks.py``.
"""

from src.db.repos import backtests, flags, jobs, marks  # noqa: F401

__all__ = ["backtests", "flags", "jobs", "marks"]
