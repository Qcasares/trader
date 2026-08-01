"""
conftest.py
-----------
Shared fixtures.

Nearly everything that used to live here — mock Anthropic clients, sample
sentiment scores, fabricated technical signals, sample risk decisions —
supported the crypto agent tests, and went with them. Those fixtures were also
the mechanism by which the old suite passed while the pipeline it tested did
not run: ``tests/integration/test_dry_run_e2e.py`` fabricated payload keys the
agents never actually emitted, so 84 green tests described a system that could
not work.

What remains is the one fake still in use. The systematic suite prefers real
dependencies — real Postgres, the real NYSE calendar, a fake Alpaca server
answering real HTTP — because mocking a boundary only proves the mock matches
your assumption about it.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_bankr_session():
    """
    AsyncMock of ``aiohttp.ClientSession`` for ``BankrClient`` tests.

    ``src/bankr_client.py`` is kept as the reference for a future crypto broker
    adapter and is not reachable from any strategy, so a mocked transport is
    proportionate here in a way it would not be on the order path.
    """
    session = AsyncMock()

    # POST /agent/prompt -> returns a jobId
    post_response = AsyncMock()
    post_response.status = 200
    post_response.json = AsyncMock(return_value={"jobId": "test-job-123"})
    post_ctx = AsyncMock()
    post_ctx.__aenter__ = AsyncMock(return_value=post_response)
    post_ctx.__aexit__ = AsyncMock(return_value=False)
    session.post = MagicMock(return_value=post_ctx)

    # GET /agent/job/{id} -> returns a completed job
    get_response = AsyncMock()
    get_response.status = 200
    get_response.json = AsyncMock(
        return_value={
            "status": "completed",
            "response": "Bought $50.00 of ETH at $3,456.78 on Base",
            "jobId": "test-job-123",
        }
    )
    get_ctx = AsyncMock()
    get_ctx.__aenter__ = AsyncMock(return_value=get_response)
    get_ctx.__aexit__ = AsyncMock(return_value=False)
    session.get = MagicMock(return_value=get_ctx)

    return session
