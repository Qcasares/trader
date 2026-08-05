"""
secrets.py
----------
Reading and writing the encrypted secrets table.

The only module that touches `secrets.ciphertext`. Everything above it deals in
plaintext-in, plaintext-out or in the *description* of a secret, never in the
stored token.

Two rules shape the interface:

1. **Nothing here returns a secret unless the caller asked to use it.**
   :func:`describe` exists so the API can render "configured, fingerprint abcd"
   without a decrypt happening anywhere in the request that serves the browser.
   :func:`get` is the only function that decrypts, and the only caller that
   needs it is the programme runner.

2. **A read that cannot be completed returns nothing rather than something.**
   A missing row, an unset key, a token written under a previous key — all read
   as "no secret", with the reason logged. The programme already degrades
   correctly without a model: it reconciles, evaluates gates and promotes, and
   proposes nothing. Falling back to a stale or partial value would be worse
   than that, because it would spend money at a vendor under a credential
   nobody chose.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg

from src import crypto

logger = logging.getLogger(__name__)

#: The model API key. Named rather than free-form so a typo cannot quietly
#: create a second secret nothing reads — the same reason `programme_config`
#: refuses an unknown key.
ANTHROPIC_API_KEY = "anthropic_api_key"

#: Every secret this system knows how to store.
KNOWN_SECRETS: tuple[str, ...] = (ANTHROPIC_API_KEY,)


@dataclass(frozen=True, slots=True)
class SecretDescription:
    """What a secret is, without what it is."""

    name: str
    configured: bool
    fingerprint: str | None
    updated_by: str | None
    updated_at: datetime | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "configured": self.configured,
            "fingerprint": self.fingerprint,
            "updated_by": self.updated_by,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


async def describe(conn: asyncpg.Connection, name: str) -> SecretDescription:
    """
    Whether a secret is set, and which one it is — never what it is.

    Deliberately does not take a key and cannot decrypt. The endpoint that
    renders the configuration page calls this, so there is no code path from a
    browser request to a plaintext credential even if the API process holds the
    key to produce one.
    """
    row = await conn.fetchrow(
        "SELECT fingerprint, updated_by, updated_at FROM secrets WHERE name = $1",
        name,
    )
    if row is None:
        return SecretDescription(name, False, None, None, None)
    return SecretDescription(
        name=name,
        configured=True,
        fingerprint=row["fingerprint"],
        updated_by=row["updated_by"],
        updated_at=row["updated_at"],
    )


async def set_secret(
    conn: asyncpg.Connection, name: str, plaintext: str, key: str | None, actor: str
) -> SecretDescription:
    """
    Encrypt and store, replacing whatever was there.

    Encryption happens before the write and outside the transaction's success
    path: :func:`crypto.encrypt` raises on a missing or malformed key, so a
    deployment with no `SECRETS_KEY` fails at the form with a sentence naming
    the problem, rather than storing something it cannot read back.
    """
    if name not in KNOWN_SECRETS:
        raise ValueError(f"unknown secret {name!r}; known: {list(KNOWN_SECRETS)}")

    ciphertext = crypto.encrypt(plaintext, key)
    marker = crypto.fingerprint(plaintext)

    await conn.execute(
        """
        INSERT INTO secrets (name, ciphertext, fingerprint, updated_by, updated_at)
        VALUES ($1, $2, $3, $4, NOW())
        ON CONFLICT (name) DO UPDATE
        SET ciphertext = EXCLUDED.ciphertext,
            fingerprint = EXCLUDED.fingerprint,
            updated_by = EXCLUDED.updated_by,
            updated_at = NOW()
        """,
        name,
        ciphertext,
        marker,
        actor,
    )
    return await describe(conn, name)


async def clear_secret(conn: asyncpg.Connection, name: str) -> None:
    """
    Remove it. The row goes rather than being blanked.

    A row with an empty value would read as "configured" to every count and
    every badge while decrypting to nothing, which is the state this feature
    exists to make impossible. The schema refuses an empty ciphertext for the
    same reason.
    """
    await conn.execute("DELETE FROM secrets WHERE name = $1", name)


async def get(conn: asyncpg.Connection, name: str, key: str | None) -> str | None:
    """
    The plaintext secret, or ``None`` if it cannot be produced.

    The one function that decrypts, and it fails closed in every direction: no
    row, no key, a malformed key, or a token that does not authenticate all
    return ``None`` with the reason logged. The caller — the programme runner —
    already treats an absent key as "do everything that does not need a model",
    which is a correct pass rather than a degraded one.

    The broad ``except`` is deliberate and matches `flags.trading_enabled`: a
    control that guesses when it cannot determine the answer is not a control.
    """
    try:
        row = await conn.fetchrow(
            "SELECT ciphertext FROM secrets WHERE name = $1", name
        )
    except Exception as exc:  # noqa: BLE001 - deliberately broad; see docstring
        logger.error("Cannot read secret %s (%s); treating it as absent", name, exc)
        return None

    if row is None:
        return None

    try:
        return crypto.decrypt(row["ciphertext"], key)
    except crypto.SecretUnavailableError as exc:
        logger.error("Secret %s is stored but unreadable: %s", name, exc)
        return None
    except crypto.SecretCorruptError as exc:
        # Worth its own branch and its own sentence: this is what a rotated
        # SECRETS_KEY looks like, and "invalid token" would send an operator
        # looking at the wrong thing entirely.
        logger.error("Secret %s cannot be decrypted: %s", name, exc)
        return None
