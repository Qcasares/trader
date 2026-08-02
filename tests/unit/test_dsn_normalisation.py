"""
test_dsn_normalisation.py
-------------------------
That a connection string copied from a managed Postgres provider actually
connects.

asyncpg forwards any DSN query parameter it does not recognise to the server as
a runtime setting, and Postgres refuses the connection:
``UndefinedObjectError: unrecognized configuration parameter``. A DSN that
works perfectly with ``psql`` therefore fails here, naming a parameter the
operator never chose and cannot act on.

That is not a hypothetical. Neon — the Postgres in Vercel's own marketplace,
and so the likeliest database for a deployment of this — hands out
``...?sslmode=require&channel_binding=require`` by default. Pasted into the
environment as-is, every request fails at connection time. It was verified
against a real Postgres before this was written, not inferred from the docs.

The tests below therefore pin two things: that the parameters asyncpg *does*
support survive untouched, and that the ones it cannot honour are removed
rather than passed through.
"""

from __future__ import annotations

import pytest

from src.config import _UNSUPPORTED_DSN_PARAMS, normalise_dsn

NEON = (
    "postgresql://u:p@ep-cool-name-123456.eu-central-1.aws.neon.tech/neondb"
    "?sslmode=require&channel_binding=require"
)


class TestParametersAsyncpgCannotHonour:
    def test_the_neon_default_becomes_connectable(self) -> None:
        result = normalise_dsn(NEON)
        assert "channel_binding" not in result
        # …and the rest of the DSN is intact, host and credentials included.
        assert result.startswith("postgresql://u:p@ep-cool-name-123456")
        assert "/neondb" in result

    def test_ssl_requirements_are_preserved(self) -> None:
        # Dropping sslmode while stripping channel_binding would turn a
        # connection-refused into a silent downgrade to plaintext, which is a
        # far worse outcome than the bug being fixed.
        assert "sslmode=require" in normalise_dsn(NEON)

    @pytest.mark.parametrize("param", sorted(_UNSUPPORTED_DSN_PARAMS))
    def test_each_unsupported_parameter_is_removed(self, param: str) -> None:
        dsn = f"postgresql://h/db?{param}=whatever"
        assert param not in normalise_dsn(dsn)

    def test_a_dsn_of_only_unsupported_params_loses_its_query(self) -> None:
        # Not left as a dangling "?", which some parsers treat as a malformed
        # URI rather than an empty query.
        assert normalise_dsn("postgresql://h/db?channel_binding=require") == (
            "postgresql://h/db"
        )

    def test_matching_is_case_insensitive(self) -> None:
        assert "Channel_Binding" not in normalise_dsn(
            "postgresql://h/db?Channel_Binding=require"
        )


class TestEverythingElseIsLeftAlone:
    def test_a_plain_dsn_is_untouched(self) -> None:
        dsn = "postgresql://trader@localhost:5432/trader"
        assert normalise_dsn(dsn) is dsn or normalise_dsn(dsn) == dsn

    def test_supported_parameters_survive(self) -> None:
        # asyncpg implements these; removing them would change behaviour for
        # no reason. sslrootcert in particular is what makes verify-full work.
        dsn = (
            "postgresql://h/db?sslmode=verify-full&sslrootcert=/etc/ca.pem"
            "&application_name=trader"
        )
        result = normalise_dsn(dsn)
        assert "sslmode=verify-full" in result
        assert "sslrootcert=/etc/ca.pem" in result
        assert "application_name=trader" in result

    def test_an_unknown_but_valid_server_setting_survives(self) -> None:
        # asyncpg's forwarding behaviour is a feature for real GUCs; only the
        # named libpq-only parameters are dropped, not anything unrecognised.
        assert "statement_timeout=5000" in normalise_dsn(
            "postgresql://h/db?statement_timeout=5000"
        )

    def test_the_empty_dsn_is_handled(self) -> None:
        # get_settings calls this before checking for emptiness.
        assert normalise_dsn("") == ""


class TestItIsWiredIn:
    def test_get_settings_normalises(self, monkeypatch) -> None:
        """
        The function existing is not the fix; being called is. get_settings is
        the single place every process reads the DSN from.
        """
        from src.api.security import hash_password
        from src.config import get_settings

        monkeypatch.setenv("DATABASE_URL", NEON)
        monkeypatch.setenv("SESSION_SECRET", "x" * 48)
        monkeypatch.setenv("ADMIN_PASSWORD_HASH", hash_password("unused"))
        get_settings.cache_clear()
        try:
            assert "channel_binding" not in get_settings().database_url
        finally:
            get_settings.cache_clear()

    def test_the_migration_runner_normalises(self) -> None:
        # Migrations connect with a raw DSN rather than through Settings, so
        # they need the same treatment or `migrate_cli` fails where the API
        # succeeds.
        import inspect

        from src.db import migrate as migrate_module

        source = inspect.getsource(migrate_module)
        assert "normalise_dsn" in source, (
            "migrate connects with its own DSN; without normalisation "
            "migrate_cli fails against a database the API can reach"
        )
