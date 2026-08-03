"""
strategies
----------
Deterministic, backtestable trading strategies.

Importing this package populates the registry: every strategy module is
imported here so that ``list_strategies()`` is complete after a single
``import src.strategies``.
"""

# Import strategy modules for their registration side effects. Keep this list
# alphabetical and add to it whenever a strategy is added.
from src.strategies import (
    asset_class_trend_following,  # noqa: F401,E402
    buy_and_hold,  # noqa: F401,E402
)
from src.strategies.base import Strategy, StrategyParams  # noqa: F401
from src.strategies.registry import (  # noqa: F401
    build_strategy,
    describe_all,
    get_strategy_class,
    list_strategies,
    register,
)

__all__ = [
    "Strategy",
    "StrategyParams",
    "build_strategy",
    "describe_all",
    "get_strategy_class",
    "list_strategies",
    "register",
]
