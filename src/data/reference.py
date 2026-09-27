"""
reference.py
------------
The reference sleeves: which instruments the forward clock describes, which
vendor their history is kept under, and how much of it.

Constants and nothing else, so both processes can read them: the worker reads
them today, and the programme will from phase C4. The worker's
``ingest_reference_bars`` job (``src/worker/maintenance_jobs.py``) fetches and
stores these symbols; the programme is to describe them, and may do no more
than read, since nothing in ``src/programme`` writes ``daily_bars`` and the
programme may not import the worker that does
(``tests/unit/test_import_boundaries.py::test_nothing_in_the_programme_writes_daily_bars``).
A job's payload cannot name a symbol: the job takes its symbols from here.

The instruments never reach Jev. The regime state holds enumerated labels and
no tickers, so :data:`REFERENCE_SLEEVES` is the only record of which
instruments a regime series describes, and changing a sleeve's symbol starts a
new series.
"""

from __future__ import annotations

from types import MappingProxyType

#: The vendor the reference bars are stored under. ``daily_bars`` keys on
#: ``(symbol, session, source)`` so that vendors coexist, and the forward
#: clock is to read this source alone, so a second vendor's idea of a price
#: can never be stitched into a regime state.
REFERENCE_SOURCE = "yfinance"

#: Each regime sleeve's instrument. The keys are ``jev_questions.SLEEVES``, and
#: ``tests/unit/test_reference_bars.py`` holds them equal.
REFERENCE_SLEEVES = MappingProxyType(
    {"equities": "SPY", "bonds": "IEF", "commodities": "GSG"}
)

#: What the reference job fetches, whatever its payload says: the sleeves'
#: symbols, sorted.
REFERENCE_SYMBOLS: tuple[str, ...] = tuple(sorted(REFERENCE_SLEEVES.values()))

#: Calendar days of history refetched, and so kept on one adjustment basis:
#: 2,200 days hold between 1,510 and 1,524 NYSE sessions across the calendar,
#: over the 1,280 closes ``jev_features.regime_state`` needs a sleeve to have.
#: The live ingest refetches at least this much of every symbol it owns too
#: (``maintenance_jobs.refetch_start``), so whichever job writes a symbol, a
#: stored series is never stitched from two fetches' ideas of its history.
#: ``tests/unit/test_reference_bars.py::test_the_window_covers_the_regime_history``
#: holds it across the calendar.
REFERENCE_WINDOW_DAYS = 2_200

#: Below this many stored rows up to the session, a symbol the live ingest owns
#: is backfilled rather than left to it. Above the 1,280 closes a regime state
#: needs, and below the fewest sessions any backfill writes — a window of
#: :data:`REFERENCE_WINDOW_DAYS` short of the live ingest's own ten-day
#: lookback, which a backfill never enters — so one backfill is enough and the
#: symbol is not fetched again every session.
REFERENCE_MIN_ROWS = 1_300

#: The reference job's queue priority. Below every kind on the live path
#: (``src/worker/scheduling.PRIORITY``, whose lowest is 5), so a reference
#: fetch due in the same minute as ``ingest_bars`` is claimed after it: the
#: worker runs one job at a time, and the live ingest must not wait on this
#: one. A priority orders claims and preempts nothing already running, so the
#: planner schedules the job no earlier than ``ingest_bars``, and the job
#: refuses to run before then in any case
#: (``maintenance_jobs.reference_window``). Above a queued backtest's 0, whose
#: result can wait. Every enqueue of the job must pass this constant by name
#: (``tests/unit/test_reference_bars.py``).
REFERENCE_PRIORITY = 1

__all__ = [
    "REFERENCE_MIN_ROWS",
    "REFERENCE_PRIORITY",
    "REFERENCE_SLEEVES",
    "REFERENCE_SOURCE",
    "REFERENCE_SYMBOLS",
    "REFERENCE_WINDOW_DAYS",
]
