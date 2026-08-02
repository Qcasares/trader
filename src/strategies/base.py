"""
base.py
-------
The ``Strategy`` contract.

A strategy is a *pure function of visible history and current holdings*. It does
no I/O, reads no clock, and touches no database. Everything it is allowed to
know arrives as arguments, which is what makes the same object usable by both
the backtest driver and the live driver — and what makes the parity test in
``tests/unit/test_parity.py`` possible at all.

Parameters are declared as a pydantic model. That single declaration gives us
validation, a JSON Schema for the web form, and a stable serialisation for
storing which parameters produced which backtest.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import date
from typing import Any, ClassVar

from pydantic import BaseModel

from src.core.panel import PricePanel
from src.core.types import PortfolioState, TargetWeights

logger = logging.getLogger(__name__)


class StrategyParams(BaseModel):
    """Base class for strategy parameter models."""

    model_config = {"extra": "forbid", "frozen": True}


class Strategy(ABC):
    """
    Abstract base for every trading strategy.

    Subclasses declare ``name``, ``params_model``, and implement three methods.
    Registration happens via ``@register`` in ``src/strategies/registry.py``.
    """

    #: Stable identifier, used in URLs, the database, and the CLI.
    name: ClassVar[str]

    #: Bumped when the strategy's logic changes in a way that invalidates
    #: previously stored backtest results.
    version: ClassVar[str] = "1.0"

    #: Human-readable summary shown in the UI.
    description: ClassVar[str] = ""

    #: Provenance — the paper or reference implementation this came from.
    source: ClassVar[str] = ""

    #: Pydantic model defining the tunable parameters.
    params_model: ClassVar[type[StrategyParams]]

    def __init__(self, params: StrategyParams | dict[str, Any] | None = None) -> None:
        if params is None:
            self.params = self.params_model()
        elif isinstance(params, dict):
            self.params = self.params_model(**params)
        elif isinstance(params, self.params_model):
            self.params = params
        else:
            raise TypeError(
                f"{type(self).__name__} expects {self.params_model.__name__} or "
                f"dict, got {type(params).__name__}"
            )
        self._logger = logging.getLogger(f"strategy.{self.name}")

    # ------------------------------------------------------------------
    # Contract
    # ------------------------------------------------------------------

    @abstractmethod
    def universe(self) -> list[str]:
        """
        Every symbol this strategy may ever hold.

        Fixed for the lifetime of the instance — the driver uses it to decide
        which bars to load. Dynamic selection within that set belongs in
        :meth:`target_weights`, not here.
        """

    @abstractmethod
    def should_rebalance(
        self, session: date, last_rebalance: date | None
    ) -> bool:
        """
        Whether to recompute targets on ``session``.

        ``session`` is always a real trading session. ``last_rebalance`` is
        ``None`` before the first one.
        """

    @abstractmethod
    def target_weights(
        self,
        panel: PricePanel,
        state: PortfolioState,
        session: date,
    ) -> TargetWeights:
        """
        Desired allocation as fractions of equity.

        Must be pure: same inputs, same output, no side effects. ``panel`` is
        already truncated to ``session``, so future data is not merely
        discouraged — it is unreachable.

        Symbols omitted from the result are targeted at zero, i.e. liquidated.
        """

    # ------------------------------------------------------------------
    # Derived metadata
    # ------------------------------------------------------------------

    @property
    def warmup_sessions(self) -> int:
        """
        Sessions of history required before the first meaningful signal.

        Used to compute ``effective_start_date`` — the point at which the
        strategy is actually running as designed, rather than limping along on
        partial history. Reported alongside every backtest metric, because a
        Sharpe measured partly over a warm-up period is not the Sharpe of the
        strategy.
        """
        return 0

    @property
    def min_history_per_symbol(self) -> int:
        """
        Observations a symbol needs before it may enter the universe.

        Defaults to ``warmup_sessions``. A symbol below this threshold is
        *excluded* from weighting, not held at zero — see
        ``PricePanel.is_available`` for why that distinction matters.
        """
        return self.warmup_sessions

    # ------------------------------------------------------------------
    # Introspection for the API/UI
    # ------------------------------------------------------------------

    @classmethod
    def json_schema(cls) -> dict[str, Any]:
        """JSON Schema for the parameter model, rendered as the web form."""
        return cls.params_model.model_json_schema()

    @classmethod
    def default_params(cls) -> dict[str, Any]:
        """Default parameter values as a plain dict."""
        return cls.params_model().model_dump(mode="json")

    def params_dict(self) -> dict[str, Any]:
        """This instance's parameters, JSON-serialisable."""
        return self.params.model_dump(mode="json")

    def describe(self) -> dict[str, Any]:
        """Everything the API needs to render this strategy."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "source": self.source,
            "universe": self.universe(),
            "warmup_sessions": self.warmup_sessions,
            "params": self.params_dict(),
            "params_schema": self.json_schema(),
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"{type(self).__name__}(name={self.name!r}, params={self.params!r})"
