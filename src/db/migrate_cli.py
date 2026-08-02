"""
migrate_cli.py
--------------
Apply database migrations.

    python -m src.db.migrate_cli            # apply pending
    python -m src.db.migrate_cli --dry-run  # show what would run
    python -m src.db.migrate_cli --version  # current schema version
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from src.db.migrate import MigrationError, current_version, discover, migrate

logger = logging.getLogger(__name__)


async def _run(args: argparse.Namespace) -> int:
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2

    try:
        if args.version:
            print(f"schema version: {await current_version(dsn)}")
            print("on disk:", ", ".join(str(m) for m in discover()))
            return 0

        applied = await migrate(dsn, dry_run=args.dry_run)
        if not applied:
            print("Database is up to date.")
        elif args.dry_run:
            print("Would apply:", ", ".join(str(m) for m in applied))
        else:
            print("Applied:", ", ".join(str(m) for m in applied))
        return 0
    except MigrationError as exc:
        print(f"migration error: {exc}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m src.db.migrate_cli")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
