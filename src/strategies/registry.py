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

import itertools
import logging
from collections.abc import Iterator, Sequence
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

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


def refused_grid_point(
    params_model: type[BaseModel],
    params: dict[str, Any],
    grid: dict[str, Sequence[Any]],
) -> dict[str, Any] | None:
    """
    The first point of a walk-forward study the strategy's schema refuses, or
    ``None`` when it accepts every one.

    A study builds the configuration on its own first, then each point of its
    grid over it in turn, and fails at the first the schema refuses, after
    every backtest before it has run. Checked in that order — the
    configuration as the point ``{}``, then every combination whole and in the
    order ``engine.walkforward.expand_grid`` expands them — because a rule
    across parameters can refuse a pair whose values each pass alone, and a
    configuration refused alone is refused before any point is built.
    """
    for point in _study_points(grid):
        try:
            params_model.model_validate({**params, **point})
        except ValidationError:
            return point
    return None


def _study_points(grid: dict[str, Sequence[Any]]) -> Iterator[dict[str, Any]]:
    yield {}
    if grid:
        keys = sorted(grid)
        for values in itertools.product(*(grid[k] for k in keys)):
            yield dict(zip(keys, values, strict=True))


def list_strategies() -> list[str]:
    """Registered strategy names, sorted."""
    return sorted(_REGISTRY)


def describe_all() -> list[dict[str, Any]]:
    """Full descriptors for every registered strategy, for ``GET /api/strategies``."""
    return [_REGISTRY[name]().describe() for name in list_strategies()]


def _clear_for_tests() -> None:  # pragma: no cover - test helper
    _REGISTRY.clear()
