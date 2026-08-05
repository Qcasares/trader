"""
secrets_cli.py
--------------
Generating the key that encrypts operator-set credentials.

    python -m src.db.secrets_cli keygen

Its own entry point rather than a line in the README, because a key an operator
has to produce by hand is a key someone eventually produces badly — a passphrase,
a UUID, a base64-encoded word. Fernet requires exactly 32 bytes of url-safe
base64, and the generator is the only thing that should decide what goes in.

It prints and stores nothing. The key belongs in the environment of the API and
of the programme, and specifically **not** the worker: that process holds broker
credentials and submits orders, so it must not be able to decrypt a model key
even though it can read every row in the database.
"""

from __future__ import annotations

import sys

from src.crypto import generate_key

_USAGE = """usage: python -m src.db.secrets_cli keygen

Prints a new SECRETS_KEY. Put it in .env, which is gitignored.

Rotating it does NOT re-encrypt what is already stored: existing secrets stop
decrypting and must be set again from System > Configuration. That is a
deliberate property — a rotation that silently re-encrypted would need the old
key and the new one in the same place at the same time.
"""


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or args[0] != "keygen":
        print(_USAGE, file=sys.stderr)
        return 2
    # To stdout alone, so `SECRETS_KEY=$(python -m src.db.secrets_cli keygen)`
    # works and nothing else on the line ends up inside the key.
    print(generate_key())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
