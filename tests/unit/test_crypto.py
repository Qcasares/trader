"""
test_crypto.py
--------------
The encryption behind operator-set credentials.

Unit tests because ``src/crypto.py`` is pure — the key is an argument, not an
environment read — so every property here is checkable without a database, a
server or a configured deployment.

What is worth asserting is not that Fernet works; that is the library's job and
it is well tested. It is the decisions layered on top: that a failure to encrypt
raises instead of returning something, that a rotated key is reported as a
rotated key rather than a generic error, and that the fingerprint identifies a
secret without carrying any of it.
"""

from __future__ import annotations

import pytest

from src import crypto

SECRET = "sk-ant-api03-not-a-real-key-0123456789"


@pytest.fixture
def key() -> str:
    return crypto.generate_key()


class TestItActuallyEncrypts:
    def test_round_trips(self, key: str) -> None:
        assert crypto.decrypt(crypto.encrypt(SECRET, key), key) == SECRET

    def test_the_ciphertext_does_not_contain_the_secret(self, key: str) -> None:
        """
        The one property the whole feature rests on. Asserted directly rather
        than trusted, because a construction that quietly stored plaintext under
        a column called `ciphertext` would pass every other test here.
        """
        token = crypto.encrypt(SECRET, key)
        assert SECRET not in token
        assert "sk-ant" not in token

    def test_the_same_secret_encrypts_differently_each_time(self, key: str) -> None:
        """
        Fernet carries a random IV, so equal plaintexts produce unequal tokens.
        Worth pinning: a deterministic ciphertext would let anyone with read
        access to the table confirm a guessed credential by comparing tokens.
        """
        assert crypto.encrypt(SECRET, key) != crypto.encrypt(SECRET, key)


class TestItRefusesRatherThanDegrades:
    @pytest.mark.parametrize("bad", [None, "", "not-base64!!", "c2hvcnQ="])
    def test_an_unusable_key_is_named(self, bad: str | None) -> None:
        assert crypto.key_problem(bad) is not None

    def test_a_good_key_has_no_problem(self, key: str) -> None:
        assert crypto.key_problem(key) is None

    @pytest.mark.parametrize("bad", [None, "", "nonsense"])
    def test_encrypting_without_a_usable_key_raises(self, bad: str | None) -> None:
        """
        Raises rather than returning the plaintext, an empty string or a
        sentinel. A function that silently declines to encrypt is how a
        credential ends up stored in the clear.
        """
        with pytest.raises(crypto.SecretUnavailableError):
            crypto.encrypt(SECRET, bad)

    def test_an_empty_secret_is_refused(self, key: str) -> None:
        """
        Clearing has its own path. A blank submission is far likelier to be a
        mistyped paste than an intention, and storing it would leave a row that
        reads as configured everywhere while decrypting to nothing.
        """
        with pytest.raises(ValueError):
            crypto.encrypt("", key)

    def test_a_rotated_key_says_so(self, key: str) -> None:
        """
        The specific, actionable failure. Rotating SECRETS_KEY does not
        re-encrypt what is already stored, so every existing secret stops
        decrypting — and an operator reading "invalid token" would go looking at
        the database rather than at what they just changed.
        """
        token = crypto.encrypt(SECRET, key)
        with pytest.raises(crypto.SecretCorruptError, match="SECRETS_KEY"):
            crypto.decrypt(token, crypto.generate_key())

    def test_a_tampered_token_does_not_decrypt(self, key: str) -> None:
        """Authenticated, not merely encrypted: a flipped byte is detected."""
        token = crypto.encrypt(SECRET, key)
        tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
        with pytest.raises(crypto.SecretCorruptError):
            crypto.decrypt(tampered, key)


class TestTheFingerprintIdentifiesWithoutRevealing:
    def test_it_is_stable(self) -> None:
        assert crypto.fingerprint(SECRET) == crypto.fingerprint(SECRET)

    def test_it_distinguishes(self) -> None:
        assert crypto.fingerprint(SECRET) != crypto.fingerprint(SECRET + "x")

    def test_it_contains_no_part_of_the_secret(self) -> None:
        """
        Deliberately not the last four characters, which is the conventional
        shortcut and is four characters of the real credential.
        """
        marker = crypto.fingerprint(SECRET)
        assert SECRET not in marker
        assert SECRET[-4:] not in marker
        assert "sk-ant" not in marker

    def test_it_is_short_enough_to_be_useless_alone(self) -> None:
        # 48 bits: enough to tell two keys apart, nowhere near enough to
        # reconstruct one.
        assert len(crypto.fingerprint(SECRET)) == 12


class TestTheKeyGenerator:
    def test_it_produces_a_usable_key(self) -> None:
        assert crypto.key_problem(crypto.generate_key()) is None

    def test_it_does_not_repeat(self) -> None:
        assert crypto.generate_key() != crypto.generate_key()
