"""
test_cost_model_record.py
-------------------------
That the cost model a run records is the cost model the engine applies.

A backtest's cost model lived in two places that did not have to agree: the
run's row, which recorded whatever its creator passed, and the worker, which
filled any key the row lacked from literals of its own — ``cost.get(
"slippage_bps", 5.0)``. The programme passed a stress multiplier alone, so
every run it queued was produced at 5 bps of slippage, a 25-dollar minimum
trade and no concentration cap, and recorded none of the three. The backtest
page could only say the slippage was missing, and each figure the programme's
gates promoted on was quoted without the cost assumption behind it — the
honesty rule CLAUDE.md states as "never quote a performance figure without its
cost assumption".

The fix gives the defaults one home, ``DEFAULT_COST_MODEL``, and one reader,
``complete_cost_model``: ``create_run`` stores its result and both jobs read
their costs through it. This file holds the three in step — the defaults are
the engine's own rather than new numbers, each job reads every key the record
carries and no other, and a job fed a row applies exactly what the row says.
The programme's side, that its runs and experiments store the whole model, is
``tests/integration/test_programme_cost_model.py``.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
import uuid
from datetime import date

import pytest

from src.core.orders import RebalanceConstraints
from src.core.types import CostModel
from src.db.repos.backtests import (
    DEFAULT_COST_MODEL,
    UnknownCostKeyError,
    complete_cost_model,
)

# ---------------------------------------------------------------------------
# The defaults are the engine's, not new numbers
# ---------------------------------------------------------------------------


def test_the_defaults_are_what_the_engine_already_applied() -> None:
    """
    Recording a default is only honest if it is the value that was applied.
    Slippage, the multiplier and the cap are the engine's own dataclass
    defaults; the minimum trade is the 25 dollars the worker has always
    fallen back on, which ``RebalanceConstraints`` does not default to.
    """
    assert DEFAULT_COST_MODEL["slippage_bps"] == CostModel().slippage_bps == 5.0
    assert DEFAULT_COST_MODEL["stress_multiplier"] == CostModel().stress_multiplier
    assert (
        DEFAULT_COST_MODEL["max_weight_per_asset"]
        == RebalanceConstraints().max_weight_per_asset
    )
    assert DEFAULT_COST_MODEL["min_trade_usd"] == 25.0


def test_a_request_that_names_no_cost_gets_the_same_defaults() -> None:
    """The API's form defaults and the worker's are one set, not two copies."""
    pytest.importorskip("fastapi")
    from src.api.schemas import CreateBacktestRequest

    request = CreateBacktestRequest(strategy="buy_and_hold")
    assert {
        "slippage_bps": request.slippage_bps,
        "stress_multiplier": request.cost_stress,
        "min_trade_usd": request.min_trade_usd,
        "max_weight_per_asset": request.max_weight_per_asset,
    } == dict(DEFAULT_COST_MODEL)


def test_the_defaults_cannot_be_edited_at_runtime() -> None:
    with pytest.raises(TypeError):
        DEFAULT_COST_MODEL["slippage_bps"] = 0.0  # type: ignore[index]


# ---------------------------------------------------------------------------
# complete_cost_model
# ---------------------------------------------------------------------------


def test_a_recorded_value_is_kept_and_a_missing_one_filled() -> None:
    assert complete_cost_model({"stress_multiplier": 3.0}) == {
        **DEFAULT_COST_MODEL,
        "stress_multiplier": 3.0,
    }
    assert complete_cost_model(None) == dict(DEFAULT_COST_MODEL)
    assert complete_cost_model({}) == dict(DEFAULT_COST_MODEL)


def test_a_genuine_zero_is_kept_as_a_zero() -> None:
    """Zero slippage is a choice somebody made, not a key to fill."""
    assert complete_cost_model({"slippage_bps": 0.0})["slippage_bps"] == 0.0


def test_a_cost_the_worker_does_not_apply_is_refused() -> None:
    """
    Recorded, a commission the engine never saw would read as an assumption the
    result was produced under: the missing slippage's lie, the other way round.
    """
    with pytest.raises(UnknownCostKeyError, match="commission_pct"):
        complete_cost_model({"stress_multiplier": 1.0, "commission_pct": 0.001})


def test_the_result_is_a_copy() -> None:
    recorded = {"stress_multiplier": 2.0}
    completed = complete_cost_model(recorded)
    completed["slippage_bps"] = 99.0
    assert recorded == {"stress_multiplier": 2.0}
    assert DEFAULT_COST_MODEL["slippage_bps"] == 5.0


# ---------------------------------------------------------------------------
# Each job reads every recorded key, through the record, and no other
# ---------------------------------------------------------------------------


def _cost_reads(function) -> tuple[set[str], list[str], bool]:
    """
    What ``function`` reads from its ``cost`` mapping.

    Returns the subscripted keys, every ``cost.get(...)`` (a fallback is a
    second default, the thing being removed), and whether ``cost`` is bound to
    ``complete_cost_model(...)`` rather than to the raw row.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    keys: set[str] = set()
    fallbacks: list[str] = []
    completed = False
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "cost"
            and isinstance(node.slice, ast.Constant)
        ):
            keys.add(node.slice.value)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "cost"
            and node.func.attr == "get"
        ):
            fallbacks.append(ast.unparse(node))
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "cost" for t in node.targets)
            and isinstance(node.value, ast.Call)
        ):
            callee = node.value.func
            name = (
                callee.attr
                if isinstance(callee, ast.Attribute)
                else getattr(callee, "id", "")
            )
            completed = name == "complete_cost_model"
    return keys, fallbacks, completed


@pytest.mark.parametrize("module_name", ["backtest_job", "walkforward_job"])
def test_each_job_reads_the_recorded_cost_model_and_nothing_else(
    module_name: str,
) -> None:
    """
    The contract, read from the jobs' own source as ``test_risk_limits_contract``
    reads the risk gate's: a key a job reads that the record does not carry
    is an assumption applied and written nowhere; a key the record carries that
    no job reads is one written down and never applied.
    """
    pytest.importorskip("pandas")
    import importlib

    module = importlib.import_module(f"src.worker.{module_name}")
    keys, fallbacks, completed = _cost_reads(module._execute)
    assert completed, (
        f"{module_name}._execute no longer binds `cost` to complete_cost_model(); "
        "a job that reads the raw row applies defaults the row does not record"
    )
    assert not fallbacks, (
        f"{module_name}._execute reads its costs with a fallback of its own "
        f"{fallbacks}: a second answer to what the run's costs were"
    )
    assert keys == set(DEFAULT_COST_MODEL), (
        f"{module_name}._execute reads {sorted(keys)}; the record carries "
        f"{sorted(DEFAULT_COST_MODEL)}"
    )


def test_the_contract_reader_sees_a_fallback_and_a_raw_read() -> None:
    """Guards the guard: a reader that finds nothing passes everything."""

    def raw(run):
        cost = run["cost_model"] or {}
        return cost.get("slippage_bps", 5.0), cost["stress_multiplier"]

    keys, fallbacks, completed = _cost_reads(raw)
    assert keys == {"stress_multiplier"}
    assert fallbacks == ["cost.get('slippage_bps', 5.0)"]
    assert completed is False


# ---------------------------------------------------------------------------
# A job fed a row applies what the row says
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "recorded",
    [
        # What the programme stored before the fix: the multiplier alone.
        {"stress_multiplier": 3.0},
        # Every key, none at its default.
        {
            "slippage_bps": 12.5,
            "stress_multiplier": 2.0,
            "min_trade_usd": 40.0,
            "max_weight_per_asset": 0.5,
        },
    ],
    ids=["partial", "complete"],
)
def test_the_backtest_job_applies_what_the_record_says(
    recorded: dict, monkeypatch
) -> None:
    """
    Driven through the shipped job on a short synthetic run, with the two
    constructors that receive the costs wrapped so what they were given can be
    read back. The applied values must be the completed record's, key for key.
    """
    pytest.importorskip("pandas")
    from src.worker import backtest_job

    seen: dict[str, dict] = {}

    def cost_model(**kwargs):
        seen["cost_model"] = kwargs
        return CostModel(**kwargs)

    def constraints(**kwargs):
        seen["constraints"] = kwargs
        return RebalanceConstraints(**kwargs)

    monkeypatch.setattr(backtest_job, "CostModel", cost_model)
    monkeypatch.setattr(backtest_job, "RebalanceConstraints", constraints)

    result = backtest_job._execute(
        {
            "id": uuid.uuid4(),
            "strategy_name": "buy_and_hold",
            "params": {"symbols": ["SPY"]},
            "data_source": "synthetic",
            "start_session": date(2020, 1, 2),
            "end_session": date(2020, 3, 31),
            "initial_cash": 100000.0,
            "cost_model": dict(recorded),
        }
    )

    expected = complete_cost_model(recorded)
    applied = {
        "slippage_bps": seen["cost_model"]["slippage_bps"],
        "stress_multiplier": seen["cost_model"]["stress_multiplier"],
        "min_trade_usd": float(seen["constraints"]["min_trade_usd"]),
        "max_weight_per_asset": seen["constraints"]["max_weight_per_asset"],
    }
    assert applied == expected
    # And the figures say which multiplier they were produced under.
    assert result["metrics"]["cost_stress_multiplier"] == expected["stress_multiplier"]
