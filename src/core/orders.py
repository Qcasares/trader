"""
orders.py
---------
Target weights -> concrete order intents.

This module is the single float-to-Decimal boundary in the system and the one
piece of logic that *must* be shared verbatim between the backtest driver and
the live driver. If backtesting and live trading each did their own
weights-to-orders conversion, the two would drift — differently rounded
quantities, differently ordered fills, different dust — and the backtest would
stop being a prediction of the live system.

Output ordering is deterministic (sells first, then buys, each sorted by
symbol) for two reasons: sells must precede buys so the cash they release is
available, and a stable order is what lets the parity test compare two lists
with ``==``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from src.core.types import (
    OrderIntent,
    OrderType,
    PortfolioState,
    Side,
    TargetWeights,
    quantize_qty,
    quantize_usd,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RebalanceConstraints:
    """
    Limits applied between a strategy's intent and an actual order.

    ``max_weight_per_asset`` is the concentration cap. It has to be applied
    here, in shared code, rather than in the live path alone — otherwise the
    backtest measures an uncapped strategy while the live system runs a capped
    one, and the two results are not comparable.
    """

    #: Skip rebalancing a position whose dollar delta is below this. Prevents
    #: churning a few cents of commission on every cycle.
    min_trade_usd: Decimal = Decimal("1.00")

    #: Hard cap on any single position as a fraction of equity.
    max_weight_per_asset: float = 1.0

    #: Whether the venue supports fractional shares. Alpaca does for most US
    #: equities; when False, quantities are floored to whole shares.
    allow_fractional: bool = True

    #: Positions below this dollar value are closed entirely rather than
    #: trimmed, so the book does not accumulate unsellable dust.
    dust_threshold_usd: Decimal = Decimal("1.00")


def apply_concentration_cap(
    targets: TargetWeights, constraints: RebalanceConstraints
) -> TargetWeights:
    """
    Clamp every weight to ``max_weight_per_asset``.

    Excess weight becomes cash rather than being redistributed. Redistribution
    would silently change the strategy's intent — if a trend-following model
    wants 100% in the one asset above its moving average, capping it at 40%
    means 60% cash, not 60% spread across assets the model explicitly rejected.
    """
    cap = constraints.max_weight_per_asset
    if cap >= 1.0:
        return targets
    capped = {s: min(w, cap) for s, w in targets.weights.items()}
    dropped = sum(targets.weights.values()) - sum(capped.values())
    if dropped > 1e-9:
        logger.info(
            "Concentration cap %.2f moved %.4f of equity to cash", cap, dropped
        )
    return TargetWeights(weights=capped, rationale=targets.rationale)


def weights_to_orders(
    state: PortfolioState,
    targets: TargetWeights,
    prices: dict[str, float],
    constraints: RebalanceConstraints | None = None,
) -> list[OrderIntent]:
    """
    Convert desired weights into the orders that move the portfolio there.

    Parameters
    ----------
    state:
        Current holdings and equity. ``equity`` is the weighting denominator.
    targets:
        Desired allocation. Any currently-held symbol absent from
        ``targets.weights`` is liquidated.
    prices:
        Reference price per symbol, used to convert dollars to shares. In the
        backtest this is the fill price the simulator will use; live it is the
        last close. Both paths must pass the *same* price for a given session
        or the resulting quantities will differ.
    constraints:
        Concentration cap, minimum trade size, fractional-share support.

    Returns
    -------
    Deterministically ordered list: sells (sorted by symbol) then buys (sorted
    by symbol).
    """
    constraints = constraints or RebalanceConstraints()
    capped = apply_concentration_cap(targets, constraints)
    equity = state.equity

    if equity <= 0:
        logger.warning("Equity is %s; refusing to generate orders", equity)
        return []

    # Every symbol we either hold or want to hold.
    symbols = sorted(set(capped.weights) | set(state.held_symbols))

    sells: list[OrderIntent] = []
    buys: list[OrderIntent] = []

    for symbol in symbols:
        price = prices.get(symbol)
        if price is None or price <= 0:
            if symbol in capped.weights:
                logger.warning(
                    "No usable price for %s; skipping its target of %.4f",
                    symbol,
                    capped.weights[symbol],
                )
            continue

        price_dec = Decimal(str(price))
        current_qty = state.qty_of(symbol)
        current_value = quantize_usd(current_qty * price_dec)

        target_weight = capped.weights.get(symbol, 0.0)
        target_value = quantize_usd(Decimal(str(target_weight)) * equity)

        # A position we want to exit, or one small enough to be dust, is closed
        # by quantity rather than notional so no fractional remainder is left.
        wants_exit = target_weight <= 0
        is_dust = (
            target_value < constraints.dust_threshold_usd and current_qty > 0
        )
        if (wants_exit or is_dust) and current_qty > 0:
            qty = _round_qty(current_qty, constraints)
            if qty > 0:
                sells.append(
                    OrderIntent(
                        symbol=symbol,
                        side=Side.SELL,
                        qty=qty,
                        order_type=OrderType.MARKET,
                        reason=(
                            "liquidate: below target"
                            if wants_exit
                            else "liquidate: position below dust threshold"
                        ),
                    )
                )
            continue

        delta_value = target_value - current_value
        if abs(delta_value) < constraints.min_trade_usd:
            continue

        delta_qty = _round_qty(abs(delta_value) / price_dec, constraints)
        if delta_qty <= 0:
            continue

        side = Side.BUY if delta_value > 0 else Side.SELL

        # Never sell more than we hold — rounding could otherwise produce a
        # quantity a hair above the position and get rejected by the broker.
        if side is Side.SELL:
            delta_qty = min(delta_qty, _round_qty(current_qty, constraints))
            if delta_qty <= 0:
                continue

        intent = OrderIntent(
            symbol=symbol,
            side=side,
            qty=delta_qty,
            order_type=OrderType.MARKET,
            reason=f"rebalance to {target_weight:.4f} of equity",
        )
        (buys if side is Side.BUY else sells).append(intent)

    return sells + buys


def _round_qty(qty: Decimal, constraints: RebalanceConstraints) -> Decimal:
    """Round a share quantity to what the venue will accept."""
    if constraints.allow_fractional:
        return quantize_qty(qty)
    return Decimal(int(qty))


def realised_weights(
    state: PortfolioState, prices: dict[str, float]
) -> dict[str, float]:
    """
    Actual portfolio weights, for comparing intent against outcome.

    Divergence between this and the last target is the drift the next
    rebalance corrects; a large gap is a signal that fills are not landing
    where the model assumed.
    """
    if state.equity <= 0:
        return {}
    out: dict[str, float] = {}
    for symbol, position in state.positions.items():
        price = prices.get(symbol)
        if price is None or position.is_flat:
            continue
        value = position.qty * Decimal(str(price))
        out[symbol] = float(value / state.equity)
    return out
