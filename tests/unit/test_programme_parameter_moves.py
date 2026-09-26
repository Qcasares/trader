"""
test_programme_parameter_moves.py
---------------------------------
The two experiments that move a candidate's parameters — the neighbourhood run
and the walk-forward grid — move them only as far as the strategy's own schema
allows.

Both once moved every numeric parameter by a fixed factor regardless. A
concentration cap of 1.0 — the default in every strategy that has one — became
1.2 in the neighbourhood and 1.3 in the grid, and the strategy refuses both.
The neighbourhood experiment was rejected before it was queued, so at the
default cap no candidate passed gate 1 → 2. The grid's defect sat behind that
one: a study was queued, failed in the worker at the first point it could not
build, and was queued again on every pass, so gate 2 → 3 could never pass —
for the default cap as soon as the neighbourhood was fixed, and already for a
configuration that survived 1.2 and not 1.3, such as an SMA period of 800.
Nothing said so except a note in a test that had worked around it.
"""

from __future__ import annotations

import asyncio
import itertools
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.programme import tick
from src.programme.tick import (
    NEIGHBOURHOOD_FACTOR,
    _grid_around,
    _neighbouring_params,
)
from src.strategies import get_strategy_class, list_strategies, refused_grid_point


def _defaults(name: str) -> dict:
    return get_strategy_class(name).params_model().model_dump(mode="json")


@pytest.mark.parametrize("name", sorted(list_strategies()))
def test_every_strategys_default_neighbourhood_is_one_it_accepts(name: str) -> None:
    """
    The regression, over the whole registry: from each strategy's defaults the
    neighbourhood is a configuration the strategy will run, and it differs from
    the defaults, so the experiment tests something.
    """
    model = get_strategy_class(name).params_model
    defaults = _defaults(name)
    nudged, moves = _neighbouring_params(model, defaults)
    model.model_validate(nudged)
    assert any(move != "held" for move in moves.values()), (name, moves)
    assert nudged != defaults


def test_a_cap_at_its_ceiling_moves_down_and_the_rest_up() -> None:
    model = get_strategy_class("asset_class_trend_following").params_model
    nudged, moves = _neighbouring_params(
        model, {**_defaults("asset_class_trend_following"), "sma_period": 210}
    )
    assert moves == {"sma_period": "up", "max_weight_per_asset": "down"}
    assert nudged["sma_period"] == round(210 * NEIGHBOURHOOD_FACTOR)
    assert nudged["max_weight_per_asset"] == pytest.approx(1 / NEIGHBOURHOOD_FACTOR)


def test_an_integer_at_its_ceiling_moves_down() -> None:
    model = get_strategy_class("time_series_momentum").params_model
    params = {**_defaults("time_series_momentum"), "lookback_sessions": 1000}
    nudged, moves = _neighbouring_params(model, params)
    assert moves["lookback_sessions"] == "down"
    assert nudged["lookback_sessions"] == round(1000 / NEIGHBOURHOOD_FACTOR)


def test_an_integer_moves_by_at_least_one() -> None:
    """1.2 of 1 rounds back to 1, which would move nothing."""
    model = get_strategy_class("buy_and_hold").params_model
    nudged, moves = _neighbouring_params(model, _defaults("buy_and_hold"))
    assert moves == {"min_history": "up"}
    assert nudged["min_history"] == 2


def test_a_rule_across_parameters_is_honoured() -> None:
    """
    ``top_n`` may not exceed the universe. With three symbols and ``top_n`` of
    three, up is refused by the schema's own rule, so it moves down.
    """
    model = get_strategy_class("cross_sectional_momentum").params_model
    params = {
        **_defaults("cross_sectional_momentum"),
        "symbols": ["SPY", "EFA", "EEM"],
        "top_n": 3,
    }
    nudged, moves = _neighbouring_params(model, params)
    assert moves["top_n"] == "down"
    assert nudged["top_n"] == 2
    model.model_validate(nudged)


class _Pinned(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fixed: int = Field(default=5, ge=5, le=5)
    label: str = "x"
    enabled: bool = True
    weights: list[float] = [0.5, 0.5]


class _Ordered(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fast: int = 10
    slow: int = 12

    @model_validator(mode="after")
    def _fast_below_slow(self) -> _Ordered:
        if self.fast >= self.slow:
            raise ValueError("fast must be below slow")
        return self


def test_a_parameter_the_schema_lets_move_neither_way_is_held() -> None:
    nudged, moves = _neighbouring_params(_Pinned, _Pinned().model_dump())
    assert moves == {"fixed": "held"}
    assert nudged == _Pinned().model_dump()


def test_only_numbers_move_and_never_a_boolean() -> None:
    params = _Pinned().model_dump()
    nudged, moves = _neighbouring_params(_Pinned, params)
    assert set(moves) == {"fixed"}
    for key in ("label", "enabled", "weights"):
        assert nudged[key] == params[key]


def test_each_step_sees_the_steps_before_it() -> None:
    """
    fast 10 → 12 is refused beside slow 12, so fast moves down to 8; then slow
    moves up to 14, which the ordering allows.
    """
    nudged, moves = _neighbouring_params(_Ordered, {"fast": 10, "slow": 12})
    assert moves == {"fast": "down", "slow": "up"}
    assert nudged == {"fast": 8, "slow": 14}
    _Ordered.model_validate(nudged)


def _rejected(candidate: dict) -> str:
    """
    The one rejection ``_enqueue_backtest`` notes for a neighbourhood run.

    Both rejections return before the connection is touched, so none is given.
    """
    report = tick.TickReport()
    asyncio.run(
        tick._enqueue_backtest(None, candidate, "parameter_neighbourhood", report)
    )
    (rejected,) = report.actions
    assert rejected["action"] == "experiment_rejected", report.actions
    return rejected["error"]


def test_a_configuration_the_schema_refuses_is_rejected_for_itself() -> None:
    """
    Not for its neighbourhood: every step from a refused configuration is
    refused too, and "nothing the schema lets move" would name the wrong cause.
    """
    error = _rejected(
        {
            "id": "c",
            "strategy_name": "asset_class_trend_following",
            "params": {"sma_period": "long"},
        }
    )
    assert "sma_period" in error
    assert "configuration itself" not in error


def test_a_neighbourhood_that_moves_nothing_is_rejected(monkeypatch) -> None:
    """Equal to the configuration, it would read as stability and test nothing."""
    monkeypatch.setattr(
        tick,
        "_neighbouring_params",
        lambda model, params: (dict(params), {"sma_period": "held"}),
    )
    error = _rejected(
        {
            "id": "c",
            "strategy_name": "asset_class_trend_following",
            "params": _defaults("asset_class_trend_following"),
        }
    )
    assert "configuration itself" in error


# ---------------------------------------------------------------------------
# The walk-forward grid
# ---------------------------------------------------------------------------


def _combinations(params: dict, grid: dict) -> list[dict]:
    """What the study builds: every point of the grid over the configuration."""
    keys = sorted(grid)
    return [
        {**params, **dict(zip(keys, values, strict=True))}
        for values in itertools.product(*(grid[k] for k in keys))
    ]


@pytest.mark.parametrize("name", sorted(list_strategies()))
def test_every_strategys_default_grid_is_one_it_accepts_whole(name: str) -> None:
    """
    The regression, over the whole registry and through the study's own call:
    every combination is built with ``build_strategy``, as ``_run_segment``
    builds it, and the configuration itself is a point on every axis.
    """
    from src.strategies import build_strategy

    model = get_strategy_class(name).params_model
    defaults = _defaults(name)
    grid = _grid_around(model, defaults)
    assert grid, name
    for key, points in grid.items():
        assert defaults[key] in points, (name, key, points)
    for combination in _combinations(defaults, grid):
        build_strategy(name, combination)


def test_a_cap_at_its_ceiling_keeps_the_points_below_it() -> None:
    model = get_strategy_class("asset_class_trend_following").params_model
    grid = _grid_around(model, _defaults("asset_class_trend_following"))
    assert grid["max_weight_per_asset"] == pytest.approx([0.7, 1.0])
    assert grid["sma_period"] == [147, 210, 273]


def test_an_integer_at_its_ceiling_keeps_the_points_below_it() -> None:
    model = get_strategy_class("time_series_momentum").params_model
    params = {**_defaults("time_series_momentum"), "lookback_sessions": 1000}
    assert _grid_around(model, params)["lookback_sessions"] == [700, 1000]


def test_an_integer_at_its_floor_keeps_the_points_above_it() -> None:
    model = get_strategy_class("time_series_momentum").params_model
    params = {**_defaults("time_series_momentum"), "lookback_sessions": 2}
    # 0.7 of 2 is 1, below the floor of 2; 1.3 of it rounds back to 2.
    assert _grid_around(model, params)["lookback_sessions"] == [2]


class _Budget(BaseModel):
    """Two parameters whose sum is bounded: each point passes alone."""

    model_config = ConfigDict(extra="forbid")
    fast: int = 10
    slow: int = 12

    @model_validator(mode="after")
    def _within_budget(self) -> _Budget:
        if self.fast + self.slow > 25:
            raise ValueError("fast + slow may not exceed 25")
        return self


def test_a_combination_refused_whole_is_found() -> None:
    params = _Budget().model_dump()
    grid = _grid_around(_Budget, params)
    assert grid == {"fast": [7, 10, 13], "slow": [8, 12, 15]}
    assert refused_grid_point(_Budget, params, grid) == {"fast": 13, "slow": 15}


def test_a_grid_accepted_whole_has_nothing_refused() -> None:
    model = get_strategy_class("asset_class_trend_following").params_model
    params = _defaults("asset_class_trend_following")
    assert refused_grid_point(model, params, _grid_around(model, params)) is None


def test_an_empty_grid_is_the_configuration_alone() -> None:
    """What the study runs for ``{}``: one candidate, the configuration."""
    model = get_strategy_class("asset_class_trend_following").params_model
    params = _defaults("asset_class_trend_following")
    assert refused_grid_point(model, params, {}) is None
    assert refused_grid_point(model, {**params, "sma_period": 1}, {}) == {}


def test_a_configuration_refused_alone_is_refused_first() -> None:
    """
    The study builds the configuration on its own before any point, so a grid
    that overrides the refused value does not rescue it: every combination
    would pass and the study would still fail at its first build.
    """
    model = get_strategy_class("asset_class_trend_following").params_model
    params = {**_defaults("asset_class_trend_following"), "sma_period": 1}
    grid = {"sma_period": [100, 200]}
    assert refused_grid_point(model, params, grid) == {}


def test_a_grid_point_the_schema_does_not_know_is_refused() -> None:
    """A misspelt parameter would fail the study at its first build."""
    model = get_strategy_class("asset_class_trend_following").params_model
    params = _defaults("asset_class_trend_following")
    assert refused_grid_point(model, params, {"sma": [100]}) == {"sma": 100}


def _walkforward_refusal(candidate: dict) -> str:
    """
    The one refusal ``_enqueue_walkforward`` notes, from the grid alone.

    The grid is judged before the backtest it studies is looked up, so no
    connection is given.
    """
    report = tick.TickReport()
    asyncio.run(tick._enqueue_walkforward(None, candidate, report))
    (refused,) = report.actions
    assert refused["action"] == "walkforward_refused", report.actions
    return refused["reason"]


def _real_candidate(strategy_name: str, params: dict) -> dict:
    return {
        "id": "c",
        "strategy_name": strategy_name,
        "params": params,
        "data_source": "yfinance",
        "evidence_is_synthetic": False,
    }


def test_a_study_with_a_combination_refused_whole_is_never_queued(
    monkeypatch,
) -> None:
    """
    Queued, it would fail in the worker, and the failed experiment would be
    queued again on every pass after.
    """
    monkeypatch.setattr(
        tick,
        "get_strategy_class",
        lambda name: SimpleNamespace(params_model=_Budget),
    )
    reason = _walkforward_refusal(_real_candidate("budget", _Budget().model_dump()))
    assert "{'fast': 13, 'slow': 15}" in reason


def test_a_study_of_a_configuration_the_schema_refuses_is_refused_for_it() -> None:
    reason = _walkforward_refusal(
        _real_candidate("asset_class_trend_following", {"sma_period": "long"})
    )
    assert "sma_period" in reason
