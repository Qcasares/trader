"""
migrate.py
----------
A small forward-only migration runner over plain SQL files.

Deliberately not Alembic. This codebase uses raw asyncpg with no ORM; adding
Alembic would drag in SQLAlchemy purely to manage DDL we are perfectly capable
of writing by hand. Numbered ``.sql`` files plus a ``schema_migrations`` table
is the whole mechanism.

Each migration runs inside a transaction, so a failure leaves the database at
the previous version rather than half-migrated. A checksum is stored and
verified on every run: editing an already-applied migration is a mistake that
silently desynchronises environments, so it is reported as an error rather than
ignored.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import asyncpg

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"

_FILENAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")

_BOOTSTRAP = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    INT PRIMARY KEY,
    name       TEXT        NOT NULL,
    checksum   TEXT        NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


class MigrationError(RuntimeError):
    """A migration could not be applied, or the on-disk set is inconsistent."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    path: Path
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()

    def __str__(self) -> str:
        return f"{self.version:04d}_{self.name}"


def discover(directory: Path | None = None) -> list[Migration]:
    """Load migrations from disk, ordered by version."""
    directory = directory or MIGRATIONS_DIR
    if not directory.is_dir():
        raise MigrationError(f"migrations directory not found: {directory}")

    found: list[Migration] = []
    seen: dict[int, str] = {}
    for path in sorted(directory.glob("*.sql")):
        match = _FILENAME.match(path.name)
        if not match:
            raise MigrationError(
                f"{path.name} does not match NNNN_lower_snake_case.sql"
            )
        version = int(match.group(1))
        if version in seen:
            raise MigrationError(
                f"duplicate migration version {version}: "
                f"{seen[version]} and {path.name}"
            )
        seen[version] = path.name
        found.append(
            Migration(
                version=version,
                name=match.group(2),
                path=path,
                sql=path.read_text(encoding="utf-8"),
            )
        )
    return found


async def applied_versions(conn: asyncpg.Connection) -> dict[int, str]:
    """Version -> checksum for everything already applied."""
    rows = await conn.fetch("SELECT version, checksum FROM schema_migrations")
    return {row["version"]: row["checksum"] for row in rows}


async def migrate(
    dsn_or_conn: str | asyncpg.Connection,
    directory: Path | None = None,
    dry_run: bool = False,
) -> list[Migration]:
    """
    Apply every pending migration in order. Returns those applied.

    Idempotent: running twice applies nothing the second time.
    """
    owns_connection = isinstance(dsn_or_conn, str)
    conn = await asyncpg.connect(dsn_or_conn) if owns_connection else dsn_or_conn
    try:
        await conn.execute(_BOOTSTRAP)
        on_disk = discover(directory)
        already = await applied_versions(conn)

        # Verify nothing already applied has been edited since.
        for migration in on_disk:
            recorded = already.get(migration.version)
            if recorded is not None and recorded != migration.checksum:
                raise MigrationError(
                    f"{migration} has been modified since it was applied "
                    f"(recorded {recorded[:12]}, on-disk {migration.checksum[:12]}). "
                    "Write a new migration instead of editing an applied one."
                )

        pending = [m for m in on_disk if m.version not in already]
        if not pending:
            logger.info("Database is up to date (%d migrations applied)", len(already))
            return []

        if dry_run:
            logger.info("Would apply: %s", ", ".join(str(m) for m in pending))
            return pending

        applied: list[Migration] = []
        for migration in pending:
            logger.info("Applying %s", migration)
            async with conn.transaction():
                await conn.execute(migration.sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (version, name, checksum) "
                    "VALUES ($1, $2, $3)",
                    migration.version,
                    migration.name,
                    migration.checksum,
                )
            applied.append(migration)
        logger.info("Applied %d migration(s)", len(applied))
        return applied
    finally:
        if owns_connection:
            await conn.close()


async def current_version(dsn_or_conn: str | asyncpg.Connection) -> int:
    """Highest applied version, or 0 on a fresh database."""
    owns_connection = isinstance(dsn_or_conn, str)
    conn = await asyncpg.connect(dsn_or_conn) if owns_connection else dsn_or_conn
    try:
        await conn.execute(_BOOTSTRAP)
        value = await conn.fetchval("SELECT MAX(version) FROM schema_migrations")
        return int(value or 0)
    finally:
        if owns_connection:
            await conn.close()
