"""
test_bankr_client.py
--------------------
Unit tests for BankrClient: API key validation, dry-run prefix,
and prompt format for buy/sell methods.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bankr_client import BankrClient, Chain


# ---------------------------------------------------------------------------
# AC-8: API key validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAPIKeyValidation:

    def test_invalid_key_raises(self):
        """AC-8: Key without 'bk_' prefix → ValueError"""
        with pytest.raises(ValueError, match="Invalid API key"):
            BankrClient(api_key="sk_wrong_key")

    def test_valid_key_accepted(self):
        """Key starting with 'bk_' → client created successfully"""
        client = BankrClient(api_key="bk_test_key")
        assert client._api_key == "bk_test_key"

    def test_empty_key_raises(self):
        """Empty string → ValueError"""
        with pytest.raises(ValueError, match="Invalid API key"):
            BankrClient(api_key="")


# ---------------------------------------------------------------------------
# AC-8: Dry-run prefix
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDryRunPrefix:

    async def test_dry_run_prefixes_prompt(self, mock_bankr_session):
        """AC-8: dry_run=True → prompt prefixed with simulation note"""
        client = BankrClient(api_key="bk_test_key", dry_run=True)
        client._session = mock_bankr_session

        await client._submit_prompt("Buy $50 of ETH on Base")

        # Check the posted JSON contains the prefixed prompt
        call_args = mock_bankr_session.post.call_args
        posted_json = call_args[1]["json"] if "json" in call_args[1] else call_args.kwargs["json"]
        assert posted_json["prompt"].startswith("[SIMULATION")

    async def test_live_mode_no_prefix(self, mock_bankr_session):
        """dry_run=False → prompt NOT prefixed"""
        client = BankrClient(api_key="bk_test_key", dry_run=False)
        client._session = mock_bankr_session

        await client._submit_prompt("Buy $50 of ETH on Base")

        call_args = mock_bankr_session.post.call_args
        posted_json = call_args[1]["json"] if "json" in call_args[1] else call_args.kwargs["json"]
        assert not posted_json["prompt"].startswith("[SIMULATION")
        assert "Buy $50 of ETH on Base" in posted_json["prompt"]


# ---------------------------------------------------------------------------
# Prompt format
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPromptFormat:

    async def test_buy_prompt_format(self, mock_bankr_session):
        """Buy(ETH, 50, Base) → 'Buy $50.00 of ETH on Base'"""
        client = BankrClient(api_key="bk_test_key", dry_run=False)
        client._session = mock_bankr_session

        await client.buy(token="ETH", amount_usd=50.0, chain=Chain.BASE)

        call_args = mock_bankr_session.post.call_args
        posted_json = call_args[1]["json"] if "json" in call_args[1] else call_args.kwargs["json"]
        assert "Buy $50.00 of ETH on Base" in posted_json["prompt"]

    async def test_sell_prompt_format(self, mock_bankr_session):
        """Sell(ETH, 50, Base) → 'Sell $50.00 of ETH on Base'"""
        client = BankrClient(api_key="bk_test_key", dry_run=False)
        client._session = mock_bankr_session

        await client.sell(token="ETH", amount_usd=50.0, chain=Chain.BASE)

        call_args = mock_bankr_session.post.call_args
        posted_json = call_args[1]["json"] if "json" in call_args[1] else call_args.kwargs["json"]
        assert "Sell $50.00 of ETH on Base" in posted_json["prompt"]

    async def test_buy_different_chain(self, mock_bankr_session):
        """Buy on Solana → prompt contains 'on Solana'"""
        client = BankrClient(api_key="bk_test_key", dry_run=False)
        client._session = mock_bankr_session

        await client.buy(token="SOL", amount_usd=25.0, chain=Chain.SOLANA)

        call_args = mock_bankr_session.post.call_args
        posted_json = call_args[1]["json"] if "json" in call_args[1] else call_args.kwargs["json"]
        assert "on Solana" in posted_json["prompt"]
