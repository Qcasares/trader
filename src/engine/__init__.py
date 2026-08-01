"""
engine
------
The execution sequence and its measurement.

``Driver`` is the single code path for backtest and live; ``metrics`` turns the
resulting session records into statistics. Neither imports a broker
implementation beyond the protocol, and neither imports an LLM client.
"""

from src.engine.driver import (  # noqa: F401
    Decision,
    Driver,
    DriverConfig,
    SessionRecord,
    client_order_id,
)
from src.engine.metrics import (  # noqa: F401
    PerformanceMetrics,
    compute_metrics,
    metrics_from_records,
    sharpe_standard_error,
)

__all__ = [
    "Decision",
    "Driver",
    "DriverConfig",
    "SessionRecord",
    "client_order_id",
    "PerformanceMetrics",
    "compute_metrics",
    "metrics_from_records",
    "sharpe_standard_error",
]
