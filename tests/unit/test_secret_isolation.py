"""
test_secret_isolation.py
------------------------
That the worker cannot decrypt a model credential.

The vault moves the model API key out of one process's environment and into a
table every process can read. Encryption is what makes that acceptable, and the
encryption is only worth anything if the process that must not read the key does
not hold the key.

That process is the worker. It holds the broker credentials, it is the only
thing in this system that submits an order, and
``tests/unit/test_import_boundaries.py`` already forbids it from importing an
LLM client. None of that helps if it can simply `SELECT ciphertext` and decrypt.

So the separation is expressed in key distribution, and asserted here against
the shipped ``docker-compose.yml`` rather than left as an intention in a
docstring. A comment saying the worker does not get the key is not the same
thing as the worker not getting the key.
"""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"


def _service_block(name: str) -> str:
    """
    The YAML block for one service.

    Parsed by indentation rather than with a YAML library, because pyyaml is not
    a dependency of this project and adding one to read six lines would be a
    worse trade than a regex with a test guarding it.
    """
    text = COMPOSE.read_text(encoding="utf-8")
    match = re.search(rf"^  {re.escape(name)}:\n(.*?)(?=^  \S|\Z)", text, re.S | re.M)
    assert match, f"no service {name!r} in docker-compose.yml"
    return match.group(1)


class TestTheWorkerCannotDecryptASecret:
    def test_the_scan_finds_the_services(self) -> None:
        # Guards the guard: if the compose layout changes shape, every
        # assertion below would otherwise pass against an empty string.
        for name in ("worker", "api", "programme"):
            assert len(_service_block(name)) > 40, name

    def test_the_worker_has_the_encryption_key_blanked(self) -> None:
        """
        Explicitly emptied, not merely absent.

        Every service shares `env_file: .env`, so leaving SECRETS_KEY unstated
        in the worker's own `environment:` would inherit whatever the operator
        put in the shared file. Absence is not isolation here; only the override
        is.
        """
        block = _service_block("worker")
        assert re.search(r'^\s+SECRETS_KEY:\s*""\s*$', block, re.M), (
            "the worker must blank SECRETS_KEY in its own environment block. "
            "It shares env_file: .env with every other service, so without the "
            "override it inherits the key that decrypts model credentials — and "
            "it is the one process that submits orders."
        )

    def test_the_worker_has_the_model_key_blanked_too(self) -> None:
        """
        Belt and braces, and cheap. Even with the vault in place a deployment
        may still set ANTHROPIC_API_KEY in `.env` for the programme's fallback
        path, and the worker would inherit that directly — no decryption
        required.
        """
        block = _service_block("worker")
        assert re.search(r'^\s+ANTHROPIC_API_KEY:\s*""\s*$', block, re.M), (
            "the worker must blank ANTHROPIC_API_KEY; the programme's fallback "
            "path means that variable can legitimately be present in .env"
        )

    @pytest.mark.parametrize("service", ["api", "programme"])
    def test_the_services_that_need_it_do_not_blank_it(self, service: str) -> None:
        """
        The other direction, and the reason this file is not just one assertion.

        A future edit that blanked the key everywhere would pass the tests above
        while quietly disabling the feature: the API could no longer store a
        credential and the programme could no longer read one. Both would report
        it honestly, and both would be broken.
        """
        block = _service_block(service)
        assert not re.search(r'^\s+SECRETS_KEY:\s*""\s*$', block, re.M), (
            f"{service} needs SECRETS_KEY: the API encrypts with it and the "
            "programme decrypts with it. Blanking it here disables the vault."
        )
