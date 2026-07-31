"""
data
----
Market data sources. Two real ones that are deliberately not interchangeable,
and one synthetic generator for engine verification.
"""

from src.data.base import (  # noqa: F401
    Coverage,
    DataSourceError,
    InsufficientDataError,
    PriceSource,
    bars_to_rows,
)
from src.data.cryptocom_source import (  # noqa: F401
    CryptoComSource,
    continuous_sessions,
)
from src.data.synthetic import SyntheticSource  # noqa: F401
from src.data.yfinance_source import YFinanceSource  # noqa: F401

__all__ = [
    "Coverage",
    "CryptoComSource",
    "DataSourceError",
    "InsufficientDataError",
    "PriceSource",
    "SyntheticSource",
    "YFinanceSource",
    "bars_to_rows",
    "continuous_sessions",
]
