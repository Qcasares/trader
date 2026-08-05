"""
crypto.py
---------
Encrypting a secret so the database is not the place it leaks from.

Pure: no I/O, no database, no environment reads. The key is passed in by the
caller, which is what lets this be tested without one and audited by reading a
hundred lines rather than a package.

What this protects against, precisely
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A model API key stored in a row is a key in every database dump, every backup,
every read replica, every ``SELECT *`` a support engineer runs, and every
read-only SQL injection. Encrypting it removes all of those, and that is a
worthwhile set: those are the ways a credential in a database actually escapes.

What it does **not** protect against is anyone who already holds the process
environment, because that is where the key lives. Nothing that can decrypt a
secret at runtime can also hide it from whoever controls the runtime. Any claim
otherwise is theatre, and it is worth writing down so nobody later mistakes this
for something stronger than it is.

The one thing it buys beyond database hygiene is **separation between
processes**. `SECRETS_KEY` is given to the API, which writes secrets, and to the
programme, which uses them. It is deliberately *withheld from the worker* — the
process that holds broker credentials and submits orders, and therefore the one
process that must never be able to read a model key even though it can read
every row in the database. The worker sees ciphertext and can do nothing with
it. That is the same boundary `tests/unit/test_import_boundaries.py` enforces on
imports, expressed in key distribution.

Why Fernet
~~~~~~~~~~
It is authenticated (AES-128-CBC with an HMAC-SHA256 tag), it is part of a
widely audited library, and it has almost no configuration surface to get wrong.
The alternative worth considering was an asymmetric sealed box, so that the API
could encrypt without being able to decrypt. `cryptography` ships no sealed-box
primitive, so that would have meant assembling X25519, HKDF and AES-GCM by hand.
A vetted symmetric construction beats a hand-rolled asymmetric one, and the
property it would have bought is thin here: the API already holds the session
signing key and unrestricted database access, so it is not a lower-trust process
than the one that would have held the private half.
"""

from __future__ import annotations

import hashlib
from typing import Final

#: Length of a Fernet key once base64-decoded. Fernet splits it into a 128-bit
#: signing key and a 128-bit encryption key.
_KEY_BYTES: Final = 32

#: How much of the digest a fingerprint shows. Twelve hex characters is 48 bits
#: — far too little to attack, far more than enough to tell two keys apart.
_FINGERPRINT_CHARS: Final = 12


class SecretUnavailableError(RuntimeError):
    """No usable key, so nothing can be encrypted or decrypted."""


class SecretCorruptError(ValueError):
    """The stored ciphertext did not decrypt under this key."""


def generate_key() -> str:
    """A new key, printable, for an operator to put in the environment."""
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode("ascii")


def key_problem(key: str | None) -> str | None:
    """
    Why this key cannot be used, or ``None`` if it can.

    Checked rather than assumed because the failure is otherwise silent and
    late: a malformed key raises inside the first encrypt, which is a request an
    operator is making while looking at a form, not a startup they are watching.
    """
    if not key:
        return "SECRETS_KEY is not set"
    try:
        import base64

        raw = base64.urlsafe_b64decode(key.encode("ascii"))
    except Exception:  # noqa: BLE001 - any decode failure is the same answer
        return "SECRETS_KEY is not valid url-safe base64"
    if len(raw) != _KEY_BYTES:
        return (
            f"SECRETS_KEY decodes to {len(raw)} bytes, not {_KEY_BYTES}; "
            "generate one with `python -m src.db.secrets_cli keygen`"
        )
    return None


def encrypt(plaintext: str, key: str | None) -> str:
    """
    Encrypt, or refuse.

    Raises rather than returning the plaintext, an empty string, or a sentinel.
    A function that silently declines to encrypt is how a credential ends up
    stored in the clear under a column named `ciphertext`.
    """
    problem = key_problem(key)
    if problem is not None:
        raise SecretUnavailableError(problem)
    if not plaintext:
        raise ValueError("refusing to encrypt an empty secret")

    from cryptography.fernet import Fernet

    assert key is not None  # narrowed by key_problem
    token = Fernet(key.encode("ascii")).encrypt(plaintext.encode("utf-8"))
    return token.decode("ascii")


def decrypt(token: str, key: str | None) -> str:
    """
    Decrypt, or raise.

    :class:`SecretCorruptError` rather than a generic failure when the token
    does not authenticate, because that is a specific and actionable state: the
    row was written under a different key. Rotating `SECRETS_KEY` without
    re-encrypting produces exactly this, and an operator reading "invalid token"
    would not know that.
    """
    problem = key_problem(key)
    if problem is not None:
        raise SecretUnavailableError(problem)

    from cryptography.fernet import Fernet, InvalidToken

    assert key is not None
    try:
        plaintext = Fernet(key.encode("ascii")).decrypt(token.encode("ascii"))
        return plaintext.decode("utf-8")
    except InvalidToken as exc:
        raise SecretCorruptError(
            "the stored secret did not decrypt under the current SECRETS_KEY; "
            "it was most likely written under a previous one, and rotating the "
            "key does not re-encrypt what is already stored"
        ) from exc


def fingerprint(plaintext: str) -> str:
    """
    A short, stable identifier for a secret that reveals nothing usable.

    The point is a question an operator genuinely needs answered — "is the key
    stored here the one I think it is?" — without the answer being the key.
    Truncated to 48 bits, it identifies without enabling: two fingerprints that
    match are the same secret, and a fingerprint alone is useless to whoever
    holds it.

    Deliberately *not* the last four characters of the key, which is the
    conventional shortcut. Those are four characters of the actual secret, and a
    credential is not made safer by showing only some of it.

    ``person`` is BLAKE2's personalisation parameter — a domain separator, not a
    salt, and it is not secret. The digest is therefore unkeyed, which is safe
    here only because the inputs are high-entropy API tokens: an attacker cannot
    work backwards from 48 bits to a random 100-bit key. Do not reuse this for
    anything guessable, such as a password or an account number, where an
    unkeyed digest is a lookup table away from being reversed.
    """
    digest = hashlib.blake2b(
        plaintext.encode("utf-8"), person=b"trader-secret", digest_size=16
    ).hexdigest()
    return digest[:_FINGERPRINT_CHARS]
