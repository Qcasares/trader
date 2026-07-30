"""
core
----
Value types and pure logic shared by the backtest and live paths.

Nothing in this package may import from ``src.agents``, ``src.execution``, or
any LLM client. That boundary is enforced by ``tests/unit/test_import_boundaries.py``
and is what closes the prompt-injection path recorded as C-1 in
``docs/02-security-audit.md``: if no model output can reach this code, no model
output can move money.
"""

from src.core.types import (  # noqa: F401
    AccountState,
    Bar,
    CostModel,
    Fill,
    OrderAck,
    OrderIntent,
    OrderState,
    OrderStatus,
    OrderType,
    PortfolioState,
    Position,
    Side,
    TargetWeights,
    TradingMode,
    quantize_qty,
    quantize_usd,
)

__all__ = [
    "AccountState",
    "Bar",
    "CostModel",
    "Fill",
    "OrderAck",
    "OrderIntent",
    "OrderState",
    "OrderStatus",
    "OrderType",
    "PortfolioState",
    "Position",
    "Side",
    "TargetWeights",
    "TradingMode",
    "quantize_qty",
    "quantize_usd",
]
