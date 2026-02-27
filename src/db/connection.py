"""
connection.py
-------------
Async PostgreSQL connection pool manager using asyncpg.

Usage:
    pool = DatabasePool()
    await pool.connect()
    # ... use pool.fetch(), pool.execute(), pool.fetchrow() ...
    await pool.close()
"""

import logging
import os
from typing import Any, Optional

import asyncpg

logger = logging.getLogger(__name__)


class DatabasePool:
    """
    Manages an asyncpg connection pool for the trading bot.

    Reads DATABASE_URL from environment.  Call connect() before use
    and close() on shutdown.
    """

    def __init__(self, database_url: Optional[str] = None) -> None:
        self._database_url = database_url or os.environ.get("DATABASE_URL", "")
        if not self._database_url:
            raise ValueError(
                "DATABASE_URL is required. Set it in the environment or pass "
                "it to DatabasePool(database_url=...)."
            )
        self._pool: Optional[asyncpg.Pool] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(
        self, min_size: int = 2, max_size: int = 10
    ) -> None:
        """Create the connection pool."""
        if self._pool is not None:
            logger.warning("DatabasePool.connect() called but pool already exists")
            return

        logger.info("Connecting to PostgreSQL (pool min=%d max=%d)", min_size, max_size)
        self._pool = await asyncpg.create_pool(
            self._database_url,
            min_size=min_size,
            max_size=max_size,
        )
        logger.info("PostgreSQL connection pool created")

    async def close(self) -> None:
        """Gracefully shut down the connection pool."""
        if self._pool is not None:
            logger.info("Closing PostgreSQL connection pool")
            await self._pool.close()
            self._pool = None

    # ------------------------------------------------------------------
    # Pool access
    # ------------------------------------------------------------------

    @property
    def pool(self) -> asyncpg.Pool:
        """Return the active connection pool.

        Raises RuntimeError if the pool has not been created yet.
        """
        if self._pool is None:
            raise RuntimeError(
                "DatabasePool is not connected. Call await pool.connect() first."
            )
        return self._pool

    # ------------------------------------------------------------------
    # Convenience shortcuts
    # ------------------------------------------------------------------

    async def execute(self, query: str, *args: Any) -> str:
        """Execute a query and return the status string."""
        return await self.pool.execute(query, *args)

    async def fetch(self, query: str, *args: Any) -> list[asyncpg.Record]:
        """Execute a query and return all rows."""
        return await self.pool.fetch(query, *args)

    async def fetchrow(
        self, query: str, *args: Any
    ) -> Optional[asyncpg.Record]:
        """Execute a query and return the first row (or None)."""
        return await self.pool.fetchrow(query, *args)

    async def fetchval(self, query: str, *args: Any) -> Any:
        """Execute a query and return the first column of the first row."""
        return await self.pool.fetchval(query, *args)
