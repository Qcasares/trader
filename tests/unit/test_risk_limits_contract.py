"""
test_risk_limits_contract.py
----------------------------
That a deployment's stored risk limits and the limits the worker enforces are
the same set of things.

``risk_limits`` used to be an unvalidated ``dict`` on the create-deployment
request. Anything sent was stored and echoed back by the API, while the worker
read a fixed set of keys — so ``max_drawdown`` instead of ``max_drawdown_pct``
produced a deployment that *displayed* a drawdown limit and had none. The
control looked configured, the screen agreed, and it could never bind.

That is the same argument ``risk_limits_from`` makes on the read side: "a limit
that the API accepts and stores but that this function forgets is worse than
one that does not exist". Forbidding unknown keys closes the write side.

Closing it once is not enough, though, because the two halves live in different
modules. A field added to the request model but never read by the worker
recreates the original bug exactly — an accepted, stored, inert limit — and a
key read by the worker but missing from the model becomes unsettable. So the
sets are compared here, mechanically, against the shipped source.
"""

from __future__ import annotations

import ast
import inspect

import pytest

pytest.importorskip("pydantic")

from src.api.routers.deployments import RiskLimitsRequest  # noqa: E402
from src.worker import live_job  # noqa: E402

#: The two worker functions that translate a stored limits dict into the
#: objects the shared gate and the order sizer actually use.
READERS = ("risk_limits_from", "_constraints_from")


def _keys_read_by(function_name: str) -> set[str]:
    """
    Every ``limits.get("...")`` key in a function, read from its real source.

    Parsed rather than hand-listed: a hand-maintained list is one more thing
    that drifts, and it would drift in the same direction as the bug.
    """
    tree = ast.parse(inspect.getsource(getattr(live_job, function_name)))
    keys: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "get":
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        if isinstance(node.args[0].value, str):
            keys.add(node.args[0].value)
    return keys


def _all_keys_read() -> set[str]:
    keys: set[str] = set()
    for name in READERS:
        keys |= _keys_read_by(name)
    return keys


class TestTheModelMatchesWhatTheWorkerReads:
    def test_the_parser_found_something(self) -> None:
        # Guards the guard. If the source shape changes so that no keys are
        # extracted, every assertion below would pass vacuously and the drift
        # check would be silently switched off.
        assert len(_all_keys_read()) >= 5, _all_keys_read()

    def test_every_settable_limit_is_read_by_the_worker(self) -> None:
        settable = set(RiskLimitsRequest.model_fields)
        unread = settable - _all_keys_read()
        assert not unread, (
            f"the API accepts {sorted(unread)} but no worker function reads "
            "them; they would be stored, shown as configured, and never bind — "
            "the exact bug forbidding unknown keys was meant to end"
        )

    def test_every_limit_the_worker_reads_is_settable(self) -> None:
        settable = set(RiskLimitsRequest.model_fields)
        unsettable = _all_keys_read() - settable
        assert not unsettable, (
            f"the worker reads {sorted(unsettable)} but the API has no field "
            "for them, so they can only ever take their default"
        )


class TestUnknownKeysAreRefused:
    def test_a_typo_is_rejected_not_stored(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            # One character from `max_drawdown_pct`, and previously accepted.
            RiskLimitsRequest(max_drawdown=0.2)

    def test_a_valid_configuration_still_works(self) -> None:
        limits = RiskLimitsRequest(
            max_drawdown_pct=0.2, max_daily_loss_usd=500.0, cash_buffer_pct=0.02
        )
        assert limits.max_drawdown_pct == 0.2
        assert limits.cash_buffer_pct == 0.02

    def test_the_empty_configuration_is_valid(self) -> None:
        # Existing deployments store `{}`; it must keep meaning "all defaults".
        assert RiskLimitsRequest().max_drawdown_pct is None


class TestBoundsRuleOutTheUnreachable:
    """
    These are not tidiness. Each excluded value causes a failure somewhere
    other than where it was configured, which is the worst place for it.
    """

    @pytest.mark.parametrize("value", [1.5, 2.0])
    def test_leverage_is_refused(self, value: float) -> None:
        from pydantic import ValidationError

        # `TargetWeights` refuses to construct a levered allocation, so a
        # gross-exposure cap above 1.0 cannot bind. It can, however, let a
        # cooldown hold inflate the weights past the clamp and raise inside
        # the worker instead of here.
        with pytest.raises(ValidationError):
            RiskLimitsRequest(max_gross_exposure=value)

    def test_a_full_cash_buffer_is_refused(self) -> None:
        from pydantic import ValidationError

        # 1.0 means "hold everything back", i.e. a deployment that can never
        # take a position. Silently valid, permanently inert.
        with pytest.raises(ValidationError):
            RiskLimitsRequest(cash_buffer_pct=1.0)

    def test_a_zero_daily_loss_limit_is_refused(self) -> None:
        from pydantic import ValidationError

        # Halting on any loss whatsoever is far more likely a mistake than an
        # intention, and `None` already means "disabled".
        with pytest.raises(ValidationError):
            RiskLimitsRequest(max_daily_loss_usd=0.0)

    def test_a_drawdown_limit_above_100_percent_is_refused(self) -> None:
        from pydantic import ValidationError

        # Expressed as a fraction. Someone typing 20 for "20%" gets a limit
        # that can never trigger; better a 422 than a silent no-op.
        with pytest.raises(ValidationError):
            RiskLimitsRequest(max_drawdown_pct=20.0)
