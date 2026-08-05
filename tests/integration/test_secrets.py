"""
test_secrets.py
---------------
The encrypted credential vault, against a real PostgreSQL database.

Skipped unless ``TEST_DATABASE_URL`` is set.

What needs a database rather than a unit test is everything about *stored*
state, and one property in particular that no amount of reading the code
establishes: **that the row on disk does not contain the credential**. That is
the whole claim of this feature, and the only honest way to check it is to write
a secret through the API and then read the raw column with SQL.

    createdb trader_test
    TEST_DATABASE_URL=postgresql://localhost/trader_test \\
        pytest tests/integration/test_secrets.py
"""

from __future__ import annotations

import asyncio
import os

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("asyncpg")

import asyncpg  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src import crypto  # noqa: E402
from src.api.security import hash_password  # noqa: E402
from src.db.repos import secrets as secret_repo  # noqa: E402

TEST_DSN = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DSN, reason="TEST_DATABASE_URL not set; skipping vault integration tests"
)

PASSWORD = "test-password-123"
SECRET = "sk-ant-api03-not-a-real-key-9876543210"
ENDPOINT = f"/api/v1/system/secrets/{secret_repo.ANTHROPIC_API_KEY}"

#: A throwaway Fernet key for the test database, and not a secret.
#:
#: Fixed rather than generated so a failing test leaves a reproducible database
#: behind rather than one encrypted under a key nobody has. It encrypts only the
#: fake credential below, in a database these tests create and delete. Do not
#: copy it into a deployment: `python -m src.db.secrets_cli keygen` exists so
#: nobody has to reach for a key they found in a repository.
KEY = "5-hqPTfVw2R3nvKm8sYbEjCLZxDuWANoIQGkptRe6cU="


@pytest.fixture(scope="module")
def client():
    from src.config import get_settings
    from src.db.migrate import migrate

    os.environ["DATABASE_URL"] = TEST_DSN
    os.environ["SESSION_SECRET"] = "a" * 48
    os.environ["ADMIN_PASSWORD_HASH"] = hash_password(PASSWORD)
    os.environ["SECRETS_KEY"] = KEY
    get_settings.cache_clear()

    asyncio.run(migrate(TEST_DSN))

    from src.api.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def authed(client):
    assert (
        client.post("/api/v1/auth/login", json={"password": PASSWORD}).status_code
        == 200
    )
    return client


def _run(coro):
    return asyncio.run(coro)


async def _with_conn(fn):
    conn = await asyncpg.connect(TEST_DSN)
    try:
        return await fn(conn)
    finally:
        await conn.close()


@pytest.fixture(autouse=True)
def clean(authed):
    _run(_with_conn(lambda c: c.execute("DELETE FROM secrets")))
    yield
    _run(_with_conn(lambda c: c.execute("DELETE FROM secrets")))


class TestTheStoredRowDoesNotContainTheCredential:
    def test_the_ciphertext_column_holds_no_plaintext(self, authed) -> None:
        """
        The claim the whole feature rests on, checked against the bytes on disk
        rather than against the code that wrote them.
        """
        assert authed.post(ENDPOINT, json={"value": SECRET}).status_code == 200

        async def read_raw(conn):
            return await conn.fetchrow(
                "SELECT ciphertext, fingerprint FROM secrets WHERE name = $1",
                secret_repo.ANTHROPIC_API_KEY,
            )

        row = _run(_with_conn(read_raw))
        assert row is not None
        assert SECRET not in row["ciphertext"]
        assert "sk-ant" not in row["ciphertext"]
        # And the fingerprint is not a shortcut to the secret either.
        assert SECRET[-4:] not in row["fingerprint"]

    def test_it_decrypts_back_under_the_right_key(self, authed) -> None:
        authed.post(ENDPOINT, json={"value": SECRET})
        got = _run(
            _with_conn(
                lambda c: secret_repo.get(c, secret_repo.ANTHROPIC_API_KEY, KEY)
            )
        )
        assert got == SECRET


class TestTheApiNeverHandsItBack:
    def test_the_set_response_carries_no_value(self, authed) -> None:
        body = authed.post(ENDPOINT, json={"value": SECRET}).json()
        assert SECRET not in str(body)
        assert body["configured"] is True
        assert body["fingerprint"] == crypto.fingerprint(SECRET)

    def test_the_configuration_page_carries_no_value(self, authed) -> None:
        authed.post(ENDPOINT, json={"value": SECRET})
        body = authed.get("/api/v1/system/configuration").json()
        assert SECRET not in str(body)
        stored = next(
            s for s in body["secrets"] if s["name"] == secret_repo.ANTHROPIC_API_KEY
        )
        assert stored["configured"] is True
        assert stored["fingerprint"] == crypto.fingerprint(SECRET)

    def test_there_is_no_read_endpoint(self, authed) -> None:
        """
        Not "the UI declines to call it" — it does not exist. A GET on the
        secret's own path is a 405, because only POST and DELETE are routed.
        """
        authed.post(ENDPOINT, json={"value": SECRET})
        assert authed.get(ENDPOINT).status_code in (404, 405)


class TestItRefusesTheWrongThings:
    def test_an_unauthenticated_caller_cannot_set_one(self, client) -> None:
        client.post("/api/v1/auth/logout")
        assert client.post(ENDPOINT, json={"value": SECRET}).status_code == 401

    def test_an_unknown_secret_name_is_a_404(self, authed) -> None:
        assert (
            authed.post(
                "/api/v1/system/secrets/aws_root_password", json={"value": "x"}
            ).status_code
            == 404
        )

    def test_an_empty_value_is_refused(self, authed) -> None:
        assert authed.post(ENDPOINT, json={"value": ""}).status_code == 422

    def test_an_unknown_field_is_refused(self, authed) -> None:
        response = authed.post(ENDPOINT, json={"value": SECRET, "name": "sneaky"})
        assert response.status_code == 422


class TestClearing:
    def test_it_removes_the_row_rather_than_blanking_it(self, authed) -> None:
        authed.post(ENDPOINT, json={"value": SECRET})
        assert authed.delete(ENDPOINT).status_code == 200

        rows = _run(
            _with_conn(lambda c: c.fetchval("SELECT COUNT(*) FROM secrets"))
        )
        assert rows == 0, (
            "a blanked row would read as configured everywhere while decrypting "
            "to nothing, which is the state this feature exists to make "
            "impossible"
        )

    def test_clearing_needs_no_encryption_key(self, authed) -> None:
        """
        A deployment whose key is wrong is exactly the one that most needs to be
        able to delete what it can no longer read.
        """
        authed.post(ENDPOINT, json={"value": SECRET})
        assert authed.delete(ENDPOINT).status_code == 200


class TestItFailsClosed:
    def test_a_secret_written_under_another_key_reads_as_absent(
        self, authed
    ) -> None:
        """
        What a rotated SECRETS_KEY looks like to the runner.

        `None`, not a partial value and not an exception that kills the tick.
        The programme already degrades correctly without a model: it reconciles,
        evaluates gates and promotes, and proposes nothing.
        """
        authed.post(ENDPOINT, json={"value": SECRET})
        other = crypto.generate_key()
        got = _run(
            _with_conn(
                lambda c: secret_repo.get(c, secret_repo.ANTHROPIC_API_KEY, other)
            )
        )
        assert got is None

    def test_no_key_at_all_reads_as_absent(self, authed) -> None:
        authed.post(ENDPOINT, json={"value": SECRET})
        got = _run(
            _with_conn(
                lambda c: secret_repo.get(c, secret_repo.ANTHROPIC_API_KEY, None)
            )
        )
        assert got is None, (
            "this is the worker's situation: it can read the row and holds no "
            "key, and must get nothing"
        )

    def test_an_absent_secret_is_none_not_an_error(self, authed) -> None:
        got = _run(
            _with_conn(
                lambda c: secret_repo.get(c, secret_repo.ANTHROPIC_API_KEY, KEY)
            )
        )
        assert got is None


class TestTheAuditTrail:
    def test_setting_records_the_fingerprint_and_never_the_value(
        self, authed
    ) -> None:
        authed.post(ENDPOINT, json={"value": SECRET})

        async def latest(conn):
            return await conn.fetchrow(
                "SELECT actor, action, detail::text AS detail FROM audit_log "
                "WHERE action = 'secret_set' ORDER BY at DESC LIMIT 1"
            )

        row = _run(_with_conn(latest))
        assert row is not None
        assert row["actor"].startswith("operator:")
        assert SECRET not in row["detail"], (
            "logging the credential would move it into the one table nobody "
            "thinks of as holding secrets"
        )
        assert crypto.fingerprint(SECRET) in row["detail"]
