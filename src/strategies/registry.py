"""
registry.py
-----------
Name -> strategy class lookup.

The API, the CLI, and the worker all resolve strategies by name, so there is
exactly one registry and it is populated by decorating classes at import time.
``src/strategies/__init__.py`` imports every strategy module so that importing
the package is enough to populate it.
"""

from __future__ import annotations

import logging
from typing import Any, TypeVar

from src.strategies.base import Strategy

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, type[Strategy]] = {}

T = TypeVar("T", bound=type[Strategy])


def register(cls: T) -> T:
    """Class decorator adding a strategy to the registry."""
    name = getattr(cls, "name", None)
    if not name:
        raise ValueError(f"{cls.__name__} must define a non-empty `name`")
    if not hasattr(cls, "params_model"):
        raise ValueError(f"{cls.__name__} must define `params_model`")
    existing = _REGISTRY.get(name)
    if existing is not None and existing is not cls:
        raise ValueError(
            f"strategy name {name!r} already registered by {existing.__name__}"
        )
    _REGISTRY[name] = cls
    logger.debug("Registered strategy %s -> %s", name, cls.__name__)
    return cls


def get_strategy_class(name: str) -> type[Strategy]:
    """Look up a strategy class by name, or raise with the valid options."""
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"unknown strategy {name!r}; registered: {sorted(_REGISTRY)}"
        ) from None


def build_strategy(name: str, params: dict[str, Any] | None = None) -> Strategy:
    """Instantiate a registered strategy with validated parameters."""
    return get_strategy_class(name)(params)


def list_strategies() -> list[str]:
    """Registered strategy names, sorted."""
    return sorted(_REGISTRY)


def describe_all() -> list[dict[str, Any]]:
    """Full descriptors for every registered strategy, for ``GET /api/strategies``."""
    return [_REGISTRY[name]().describe() for name in list_strategies()]


def _clear_for_tests() -> None:  # pragma: no cover - test helper
    _REGISTRY.clear()
