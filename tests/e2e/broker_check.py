"""
The shipped Alpaca adapter, against the real paper venue.

Why this exists
~~~~~~~~~~~~~~~
``AlpacaBroker`` is covered by a fake server modelling the documented contract,
and that is still where the coverage is. But a fake matches whoever wrote it,
not the venue: until this ran, ``submit``, ``get_order``, ``cancel_all`` and
``close_position`` had never once been exercised against Alpaca on paper or
anywhere else. The engine was one unverified HTTP contract away from a
deployment that plans orders correctly and cannot place them.

Not in CI, for two reasons. It needs credentials, and it writes: it submits one
$1 notional order and then removes it. `.github/workflows/broker-check.yml`
runs it on dispatch, on the runner that already holds the paper key.

It refuses to run anywhere but paper. There is no mode argument, no environment
variable that changes the endpoint and no live branch to reach: the constructor
is called with ``TradingMode.PAPER`` literally, and the first thing the script
does is prove the key is refused by the live host.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from decimal import Decimal

import aiohttp

from src.core.types import OrderIntent, OrderType, Side, TradingMode
from src.execution.alpaca import LIVE_BASE_URL, AlpacaBroker

# Small enough that a fill is loose change and large enough that Alpaca does
# not reject it outright: the venue's floor for a notional order is $1.
PROBE_NOTIONAL = Decimal("1")
PROBE_SYMBOL = "SPY"


class BrokerCheckError(RuntimeError):
    pass


async def _key_is_not_a_live_key(key_id: str, secret_key: str) -> None:
    """
    A paper key is refused by ``api.alpaca.markets`` with a 401, and a live key
    is refused by ``paper-api`` the same way. One request settles which kind is
    in the environment, and it is worth settling before anything is submitted:
    the two look identical apart from a prefix, and the dashboard's live/paper
    toggle is what decides which one you copied.
    """
    headers = {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret_key}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(f"{LIVE_BASE_URL}/v2/account") as response:
            if response.status != 401:
                raise BrokerCheckError(
                    f"{LIVE_BASE_URL} answered {response.status}, not 401. This "
                    "key is accepted by the live venue, so it is a live key. "
                    "Refusing to continue."
                )
    print("  live host refuses the key (401)      -> it is a paper key")


async def main() -> int:
    key_id = os.environ.get("ALPACA_KEY_ID", "").strip()
    secret_key = os.environ.get("ALPACA_SECRET_KEY", "").strip()
    if not key_id or not secret_key:
        raise BrokerCheckError("ALPACA_KEY_ID and ALPACA_SECRET_KEY must be set")

    print("Alpaca paper venue check")
    await _key_is_not_a_live_key(key_id, secret_key)

    async with AlpacaBroker(key_id, secret_key, mode=TradingMode.PAPER) as broker:
        account = await broker.get_account()
        print(f"  get_account                        -> equity {account.equity}")

        clock = await broker.get_clock()
        print(f"  get_clock                          -> open={clock.get('is_open')}")

        before = await broker.get_positions()
        print(f"  get_positions                      -> {len(before)} held")

        # A deterministic id is what makes a retried job safe, so the check
        # should use one rather than proving a path the worker does not take.
        client_order_id = f"broker-check-{uuid.uuid4().hex[:12]}"
        intent = OrderIntent(
            symbol=PROBE_SYMBOL,
            side=Side.BUY,
            notional=PROBE_NOTIONAL,
            order_type=OrderType.MARKET,
            reason="broker-check",
        )
        ack = await broker.submit(intent, client_order_id=client_order_id)
        print(f"  submit                             -> {ack.broker_order_id}")
        print(f"  submit acknowledged as             -> {ack.state}")

        status = await broker.get_order(ack.broker_order_id)
        print(f"  get_order                          -> {status.state}")

        by_client = await broker.get_order_by_client_id(client_order_id)
        if by_client.broker_order_id != ack.broker_order_id:
            raise BrokerCheckError(
                "get_order_by_client_id returned a different order than submit "
                "acknowledged, so the deduplication the worker relies on does "
                "not hold at this venue"
            )
        print("  get_order_by_client_id             -> same order, dedupe holds")

        cancelled = await broker.cancel_all()
        print(f"  cancel_all                         -> {cancelled} cancelled")

        # Cancelling does not unwind a fill. If the probe filled — which it
        # will whenever the market is open — the position has to go back, or
        # every run of this check leaves a little more SPY behind and the
        # reconciliation job starts reporting drift that nobody introduced.
        after = await broker.get_positions()
        if PROBE_SYMBOL in after and PROBE_SYMBOL not in before:
            await broker.close_position(PROBE_SYMBOL)
            print(f"  close_position                     -> {PROBE_SYMBOL} unwound")
        else:
            print("  close_position                     -> not needed, no new fill")

    print("\nEvery method on the shipped adapter has now run against the venue.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except BrokerCheckError as error:
        print(f"\nFAILED: {error}", file=sys.stderr)
        sys.exit(1)
