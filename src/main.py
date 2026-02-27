"""
main.py
-------
CLI entry point for the automated crypto trading bot.

Usage:
    python src/main.py --dry-run     # Safe mode (default), no real trades
    python src/main.py --live        # Live trading — USE WITH CAUTION
"""

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from src.db.connection import DatabasePool
from src.orchestrator import AgentOrchestrator

logger = logging.getLogger("trader")

# Project root (one level up from src/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_config(config_path: Path) -> dict[str, Any]:
    """Load bot configuration from YAML file."""
    if not config_path.exists():
        logger.error("Config file not found: %s", config_path)
        sys.exit(1)

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    logger.info("Loaded config from %s", config_path)
    return config or {}


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Automated crypto trading bot using bankr.bot API",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Run in dry-run mode — no real trades (default)",
    )
    mode_group.add_argument(
        "--live",
        action="store_true",
        help="Run in live trading mode — USE WITH CAUTION",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Override logging level (default: from env or INFO)",
    )
    parser.add_argument(
        "--config",
        default="config/bot_config.yaml",
        help="Path to bot config YAML (default: config/bot_config.yaml)",
    )
    return parser.parse_args()


def validate_env() -> dict[str, str]:
    """
    Validate required environment variables and return API keys dict.

    Exits with error if required vars are missing.
    """
    required = {
        "ANTHROPIC_API_KEY": "Anthropic API key for agent intelligence",
        "BANKR_API_KEY": "bankr.bot API key (must start with bk_)",
        "DATABASE_URL": "PostgreSQL connection string",
    }

    missing = []
    for var, description in required.items():
        if not os.environ.get(var):
            missing.append(f"  {var} — {description}")

    if missing:
        logger.error(
            "Missing required environment variables:\n%s",
            "\n".join(missing),
        )
        sys.exit(1)

    # Validate bankr key format
    bankr_key = os.environ["BANKR_API_KEY"]
    if not bankr_key.startswith("bk_"):
        logger.error(
            "BANKR_API_KEY must start with 'bk_'. Got: %s...",
            bankr_key[:6],
        )
        sys.exit(1)

    return {
        "anthropic": os.environ["ANTHROPIC_API_KEY"],
        "bankr": bankr_key,
        "coingecko": os.environ.get("COINGECKO_API_KEY"),
        "twitter": os.environ.get("TWITTER_BEARER_TOKEN"),
        "reddit_id": os.environ.get("REDDIT_CLIENT_ID"),
        "reddit_secret": os.environ.get("REDDIT_CLIENT_SECRET"),
        "neynar": os.environ.get("NEYNAR_API_KEY"),
    }


def configure_logging(level: str) -> None:
    """Configure logging with consistent format."""
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Quieten noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("asyncpg").setLevel(logging.WARNING)


async def async_main(args: argparse.Namespace) -> None:
    """Async entry point — initializes everything and runs the loop."""

    # --- Determine mode ---
    dry_run = not args.live
    if not dry_run:
        env_dry_run = os.environ.get("DRY_RUN", "true").lower()
        if env_dry_run != "false":
            logger.error(
                "LIVE mode requested but DRY_RUN env is '%s' (must be 'false'). "
                "Set DRY_RUN=false in .env to enable live trading.",
                env_dry_run,
            )
            sys.exit(1)
        logger.warning(
            "╔══════════════════════════════════════════╗"
        )
        logger.warning(
            "║  LIVE TRADING MODE — REAL MONEY AT RISK  ║"
        )
        logger.warning(
            "╚══════════════════════════════════════════╝"
        )

    # --- Load config ---
    config_path = PROJECT_ROOT / args.config
    config = load_config(config_path)

    # --- Validate environment ---
    api_keys = validate_env()

    # --- Initialize database ---
    db_pool = DatabasePool(os.environ["DATABASE_URL"])
    await db_pool.connect()
    logger.info("Database connected")

    # --- Create orchestrator ---
    orchestrator = AgentOrchestrator(
        config=config,
        api_keys=api_keys,
        db_pool=db_pool,
        dry_run=dry_run,
    )

    # --- Register signal handlers for graceful shutdown ---
    loop = asyncio.get_running_loop()

    def handle_signal(sig: int) -> None:
        sig_name = signal.Signals(sig).name
        logger.info("Received %s — requesting graceful shutdown", sig_name)
        orchestrator.shutdown()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal, sig)

    # --- Log startup banner ---
    enabled_tickers = [
        t["ticker"]
        for t in config.get("watchlist", [])
        if t.get("enabled", True)
    ]
    interval = config.get("loop", {}).get("interval_minutes", 15)

    logger.info("=" * 50)
    logger.info("Crypto Trading Bot — %s", "DRY-RUN" if dry_run else "LIVE")
    logger.info("Loop interval: %d minutes", interval)
    logger.info("Enabled tickers: %s", ", ".join(enabled_tickers) or "none")
    logger.info("Agents: 7 (Research, Sentiment, Technical, Signal, Risk, Execution, Portfolio)")
    logger.info("=" * 50)

    # --- Run orchestrator ---
    try:
        await orchestrator.run()
    finally:
        logger.info("Shutting down — closing database pool")
        await db_pool.close()
        logger.info("Shutdown complete")


def main() -> None:
    """Synchronous entry point."""
    # Load .env from project root
    env_path = PROJECT_ROOT / ".env"
    load_dotenv(dotenv_path=env_path)

    # Parse CLI args
    args = parse_args()

    # Configure logging
    log_level = args.log_level or os.environ.get("LOG_LEVEL", "INFO")
    configure_logging(log_level)

    # Run async main
    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
