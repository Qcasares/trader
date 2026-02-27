"""
bankr_client.py
---------------
Async Python client for the bankr.bot Agent API.
Wraps the prompt/job polling pattern and exposes typed trade methods.
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

BANKR_BASE_URL = "https://api.bankr.bot/agent"
POLL_INTERVAL_SECONDS = 2
MAX_POLL_ATTEMPTS = 60  # 2 minutes maximum wait


class Chain(str, Enum):
    BASE = "Base"
    ETHEREUM = "Ethereum"
    POLYGON = "Polygon"
    SOLANA = "Solana"
    UNICHAIN = "Unichain"


@dataclass
class TradeResult:
    success: bool
    response: str
    job_id: str
    raw_payload: dict


class BankrAPIError(Exception):
    """Raised when bankr.bot returns an error response."""
    pass


class BankrClient:
    """
    Async client for the bankr.bot Agent API.

    Usage:
        client = BankrClient(api_key=os.environ["BANKR_API_KEY"])
        result = await client.buy(token="ETH", amount_usd=50, chain=Chain.BASE)
    """

    def __init__(self, api_key: str, dry_run: bool = True):
        """
        Initialise the bankr client.

        Parameters
        ----------
        api_key : str
            The bankr.bot API key beginning with 'bk_'.
        dry_run : bool
            When True, prompts are prefixed with a simulation note and
            NO real trades are submitted. Defaults to True for safety.
        """
        if not api_key.startswith("bk_"):
            raise ValueError(
                "Invalid API key format. bankr.bot keys begin with 'bk_'."
            )
        self._api_key = api_key
        self._dry_run = dry_run
        self._headers = {
            "Content-Type": "application/json",
            "X-API-Key": self._api_key,
        }
        self._session: Optional[aiohttp.ClientSession] = None
        logger.info(
            "BankrClient initialised. dry_run=%s", self._dry_run
        )

    async def __aenter__(self):
        self._session = aiohttp.ClientSession(headers=self._headers)
        return self

    async def __aexit__(self, *args):
        if self._session:
            await self._session.close()

    # ------------------------------------------------------------------
    # Core async job workflow
    # ------------------------------------------------------------------

    async def _submit_prompt(self, prompt: str) -> str:
        """Submit a prompt to bankr and return the job ID."""
        if self._dry_run:
            prompt = f"[SIMULATION — DO NOT EXECUTE] {prompt}"

        async with self._session.post(
            f"{BANKR_BASE_URL}/prompt",
            json={"prompt": prompt},
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise BankrAPIError(
                    f"Prompt submission failed ({resp.status}): {body}"
                )
            data = await resp.json()
            job_id = data["jobId"]
            logger.debug("Prompt submitted. jobId=%s", job_id)
            return job_id

    async def _poll_job(self, job_id: str) -> dict:
        """Poll until the job reaches a terminal state."""
        for attempt in range(MAX_POLL_ATTEMPTS):
            async with self._session.get(
                f"{BANKR_BASE_URL}/job/{job_id}"
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise BankrAPIError(
                        f"Job poll failed ({resp.status}): {body}"
                    )
                job = await resp.json()
                status = job.get("status")

                if status == "completed":
                    logger.info(
                        "Job %s completed. response=%s",
                        job_id,
                        job.get("response", "")[:80],
                    )
                    return job

                if status in ("failed", "cancelled"):
                    raise BankrAPIError(
                        f"Job {job_id} ended with status={status}: "
                        f"{job.get('error', 'No error detail')}"
                    )

            await asyncio.sleep(POLL_INTERVAL_SECONDS)

        raise BankrAPIError(
            f"Job {job_id} did not complete within "
            f"{MAX_POLL_ATTEMPTS * POLL_INTERVAL_SECONDS}s."
        )

    async def execute_prompt(self, prompt: str) -> TradeResult:
        """Submit a natural-language prompt and await the result."""
        job_id = await self._submit_prompt(prompt)
        job = await self._poll_job(job_id)
        return TradeResult(
            success=True,
            response=job.get("response", ""),
            job_id=job_id,
            raw_payload=job,
        )

    # ------------------------------------------------------------------
    # Typed trading methods
    # ------------------------------------------------------------------

    async def get_portfolio(self) -> TradeResult:
        """Retrieve the complete portfolio across all chains."""
        return await self.execute_prompt("Show my complete portfolio")

    async def get_balance(self, chain: Chain = Chain.BASE) -> TradeResult:
        """Get ETH/SOL balance on a specific chain."""
        return await self.execute_prompt(
            f"What is my balance on {chain.value}?"
        )

    async def get_price(self, token: str, chain: Chain = Chain.BASE) -> TradeResult:
        """Look up the current price of a token."""
        return await self.execute_prompt(
            f"What is the current price of {token} on {chain.value}?"
        )

    async def buy(
        self,
        token: str,
        amount_usd: float,
        chain: Chain = Chain.BASE,
    ) -> TradeResult:
        """
        Buy a token with a USD-denominated amount.

        Parameters
        ----------
        token : str
            Token ticker or name, e.g. 'ETH', 'BNKR', 'PEPE'.
        amount_usd : float
            USD value to spend.
        chain : Chain
            Target chain for the trade.
        """
        prompt = (
            f"Buy ${amount_usd:.2f} of {token} on {chain.value}"
        )
        logger.info("Executing BUY: %s", prompt)
        return await self.execute_prompt(prompt)

    async def sell(
        self,
        token: str,
        amount_usd: float,
        chain: Chain = Chain.BASE,
    ) -> TradeResult:
        """Sell a token for a USD-denominated amount."""
        prompt = (
            f"Sell ${amount_usd:.2f} of {token} on {chain.value}"
        )
        logger.info("Executing SELL: %s", prompt)
        return await self.execute_prompt(prompt)

    async def sell_percentage(
        self,
        token: str,
        percentage: float,
        chain: Chain = Chain.BASE,
    ) -> TradeResult:
        """Sell a percentage of the current holding."""
        prompt = (
            f"Sell {percentage:.0f}% of my {token} on {chain.value}"
        )
        logger.info("Executing SELL PERCENTAGE: %s", prompt)
        return await self.execute_prompt(prompt)

    async def swap(
        self,
        from_token: str,
        to_token: str,
        amount: float,
        chain: Chain = Chain.BASE,
    ) -> TradeResult:
        """Swap one token for another."""
        prompt = (
            f"Swap {amount} {from_token} to {to_token} on {chain.value}"
        )
        return await self.execute_prompt(prompt)

    async def set_limit_order(
        self,
        token: str,
        direction: str,
        trigger_price_usd: float,
        amount_usd: float,
        chain: Chain = Chain.BASE,
    ) -> TradeResult:
        """Set a limit order (buy or sell at a specific price)."""
        prompt = (
            f"{direction.capitalize()} ${amount_usd:.2f} of {token} "
            f"on {chain.value} when price reaches ${trigger_price_usd:.4f}"
        )
        return await self.execute_prompt(prompt)

    async def set_stop_loss(
        self,
        token: str,
        drop_percentage: float,
        chain: Chain = Chain.BASE,
    ) -> TradeResult:
        """Set a stop-loss as a percentage drop from the current price."""
        prompt = (
            f"Set a stop loss on {token} on {chain.value} "
            f"if it drops {drop_percentage:.0f}%"
        )
        return await self.execute_prompt(prompt)
