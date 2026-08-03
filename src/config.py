"""
config.py
---------
Typed settings from the environment.

Two safety properties are enforced here rather than left to discipline:

- ``live_trading_enabled`` defaults to ``False`` and is the *outer* of two
  gates. The inner gate is the database kill switch. Flipping the DB flag needs
  only API access; flipping this one needs a redeploy. Both must permit trading
  before a live order can leave the building.
- ``alpaca_allow_live`` is a third, independent flag. It exists because a
  derived gate is not a gate: deriving it from ``live_trading_enabled`` — as
  the broker factory once did — reduced three documented conditions to two.
  Each must now be set by a separate deliberate act.
- ``session_secret`` has no default. A signing key with a fallback value is a
  signing key an attacker already knows, so no session can be minted or
  verified without a real one — enforced at ``issue_session`` and
  ``verify_session`` rather than at startup, because a startup check binds one
  call site while this binds the operation. See :func:`session_secret_problem`.
"""

from __future__ import annotations

import functools
import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class ConfigError(RuntimeError):
    """A required setting is missing or invalid."""


#: libpq connection parameters that asyncpg does not implement.
#:
#: asyncpg forwards any query parameter it does not recognise to the server as
#: a runtime setting, and Postgres refuses the connection outright:
#: ``UndefinedObjectError: unrecognized configuration parameter``. So a DSN
#: that works with psql fails here, with an error naming a parameter the
#: operator did not choose and cannot act on.
#:
#: This is not hypothetical. Neon — the Postgres offered by Vercel's own
#: marketplace, and therefore the likeliest choice for a deployment of this —
#: puts ``channel_binding=require`` in the connection string it hands out by
#: default. Pasted straight into the environment, every request fails.
_UNSUPPORTED_DSN_PARAMS = frozenset(
    {"channel_binding", "gssencmode", "sslcompression", "krbsrvname"}
)


def normalise_dsn(dsn: str) -> str:
    """
    Strip connection parameters asyncpg cannot honour.

    Removing a parameter is not free and is not done silently. ``sslmode`` and
    ``sslrootcert`` *are* supported and are left alone; only the entries above
    are dropped, and each one logs a warning.

    ``channel_binding=require`` deserves its own note, because dropping it is a
    real if narrow loss. Under ``sslmode=require`` libpq does not verify the
    server certificate, and channel binding is what still frustrates a
    man-in-the-middle in that case. asyncpg cannot negotiate it, so the choice
    is between a connection that refuses to open and one that opens without
    it. The stronger answer is not channel binding anyway — it is
    ``sslmode=verify-full`` with the provider's CA, which authenticates the
    server properly, and the warning says so.
    """
    if "?" not in dsn:
        return dsn

    base, _, query = dsn.partition("?")
    kept: list[str] = []
    dropped: list[str] = []
    for pair in query.split("&"):
        if not pair:
            continue
        key = pair.split("=", 1)[0].strip().lower()
        (dropped if key in _UNSUPPORTED_DSN_PARAMS else kept).append(pair)

    if not dropped:
        return dsn

    for pair in dropped:
        logger.warning(
            "Dropping unsupported connection parameter %r from DATABASE_URL: "
            "asyncpg would forward it to the server and the connection would "
            "be refused. For transport security prefer sslmode=verify-full "
            "with your provider's CA certificate.",
            pair,
        )
    return f"{base}?{'&'.join(kept)}" if kept else base


#: Shortest key that may sign a session.
#:
#: Not a round number chosen for looks: the signature is HMAC-SHA256, whose
#: security is bounded by the key's entropy once the key is shorter than the
#: 32-byte block. Below this an attacker can search the keyspace rather than
#: the signature space.
MIN_SESSION_SECRET_LENGTH = 32


def session_secret_problem(secret: str) -> str | None:
    """
    Why ``secret`` may not sign a session, or ``None`` if it may.

    The single definition of the policy. ``src/api/security.py`` enforces it at
    the two primitives that touch the key, and :func:`missing_api_config`
    reports it — both from here, so the reported state and the enforced state
    cannot drift apart.

    Lives in ``config.py`` rather than beside its enforcement because the
    worker and the CLI import this module, and neither has any business
    pulling in ``bcrypt`` to find out whether a string is long enough.
    """
    if not secret or not secret.strip():
        return (
            "SESSION_SECRET is not set. Generate one with: "
            "python -c 'import secrets; print(secrets.token_urlsafe(48))'"
        )
    if len(secret) < MIN_SESSION_SECRET_LENGTH:
        return (
            f"SESSION_SECRET must be at least {MIN_SESSION_SECRET_LENGTH} "
            f"characters (got {len(secret)})"
        )
    return None


def missing_api_config(settings: Settings) -> list[str]:
    """
    Every prerequisite the HTTP API needs and does not have.

    A list rather than an exception, and *all* the gaps rather than the first.
    An operator configuring a deployment one variable at a time, redeploying
    between each, is the slowest possible way to discover three missing values;
    naming them together turns three round trips into one.

    Reported by ``/ready``. Not the enforcement — the signing primitives in
    ``src/api/security.py`` call :func:`session_secret_problem` themselves.
    Both read the policy from here, so a deployment cannot report a gap it does
    not have, or run with one it has not reported.
    """
    gaps: list[str] = []
    problem = session_secret_problem(settings.session_secret)
    if problem is not None:
        gaps.append(problem)
    if not settings.admin_password_hash:
        gaps.append(
            "ADMIN_PASSWORD_HASH is not set. Generate one with: python -c "
            "\"import bcrypt;print(bcrypt.hashpw(b'yourpassword', "
            'bcrypt.gensalt()).decode())"'
        )
    return gaps


def require_api_secrets(settings: Settings) -> None:
    """
    Raise unless the API has a signing key and an operator password.

    These used to be validated inside :func:`get_settings`, which every process
    calls — so the **worker** refused to start without an admin password hash it
    has no use for. It serves no HTTP and verifies no session. Requiring it
    there pushed the operator's credential onto a process that never needs it,
    and made a perfectly good worker deployment fail on a missing value that
    could not have affected it.

    It then moved to ``create_app``, and that was still one step too early. On
    a serverless host, environment variables are set *after* the first deploy,
    so raising here took down ``/health``, ``/ready`` and ``/`` — every
    endpoint whose purpose is to say what is wrong — and left
    ``FUNCTION_INVOCATION_FAILED`` as the only symptom. Exactly the failure
    already fixed for ``DATABASE_URL``; the same argument applies, and the same
    fix does.

    So ``create_app`` no longer calls this. What replaces it is stronger, not
    weaker, and the distinction is worth stating precisely. The property that
    matters has never been "the process refuses to start" — it is **nobody can
    obtain or present a valid session**. That now holds at
    :func:`src.api.security.issue_session` and
    :func:`src.api.security.verify_session` themselves, which raise rather than
    touch an unusable key. A startup check only ever constrained one call site;
    this constrains the operation, so a future caller that forgets to validate
    still cannot mint a session.

    The function stays because a process that genuinely wants to fail closed at
    boot should have one call to make, and because stating the policy in one
    raising form keeps ``ConfigError`` meaningful.
    """
    gaps = missing_api_config(settings)
    if gaps:
        raise ConfigError("; ".join(gaps))


def require_database_url(settings: Settings) -> None:
    """
    Refuse to run without a database. For processes that cannot work without one.

    The **worker** calls this and exits: it exists solely to claim jobs and
    write results, so starting without a database means running a loop that can
    never do anything, quietly, forever. Failing at boot is the honest outcome.

    The **API** deliberately does not. It used to — ``DATABASE_URL`` was
    required inside :func:`get_settings`, which runs at import — and on a
    serverless host that is the wrong trade. Environment variables are
    configured *after* the first deploy there, so the first deploy of any
    correctly-built application crashed at import, and every route returned an
    opaque ``FUNCTION_INVOCATION_FAILED`` with the real reason visible only in
    a runtime log. Including ``/health``, whose entire purpose is to answer
    when the database cannot.

    Now the app builds, ``/health`` answers 200, and ``/ready`` answers 503 —
    which is exactly the split those two endpoints already document, and it
    makes a half-configured deployment say what it is missing instead of
    looking broken.

    No security property moves. ``require_api_secrets`` still refuses to build
    an application without a signing key, because an empty secret is a working
    key that everybody knows. A missing ``DATABASE_URL`` cannot make anything
    insecure; it can only make it useless, and being loudly useless is fine.
    """
    if not settings.database_url:
        raise ConfigError(
            "DATABASE_URL is required. Example: "
            "postgresql://user:pass@localhost:5432/trader"
        )


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime configuration."""

    database_url: str
    session_secret: str
    admin_password_hash: str

    # Outer gate for real money. See module docstring.
    live_trading_enabled: bool = False

    #: The third, independent gate. ``LIVE_TRADING_ENABLED`` says the
    #: *deployment* may reach a live venue at all; this says a given process is
    #: authorised to place the order. They are separate variables on purpose:
    #: ``_alpaca_from_env`` used to derive ``allow_live`` from
    #: ``live_trading_enabled``, which collapsed the documented three
    #: independent conditions into two and made a stray LIVE_TRADING_ENABLED=true
    #: sufficient on its own — the exact scenario
    #: ``test_alpaca_broker.py`` claims to protect against.
    alpaca_allow_live: bool = False

    # Where the browser app is served from, for CORS.
    cors_origins: list[str] = field(default_factory=list)

    #: ``SameSite`` on the session cookie.
    #:
    #: ``lax`` is right when the browser app and the API are the same *site* —
    #: which includes different ports, so it covers local development
    #: (``localhost:3000`` calling ``localhost:8000``) and a shared parent
    #: domain such as ``app.example.com`` calling ``api.example.com``.
    #:
    #: It is wrong for the deployment this project actually targets. The
    #: frontend goes to Vercel and the API to a separate host, so the request
    #: is cross-*site*, and a browser will not attach a ``Lax`` cookie to a
    #: cross-site fetch. The failure is quiet and misleading: ``/auth/login``
    #: returns 200 and sets the cookie, and every authenticated call after it
    #: gets 401, which reads as "the password did not work" when in fact it
    #: did. ``none`` is the setting that permits it, and browsers reject
    #: ``SameSite=None`` unless ``Secure`` is also set — so ``none`` implies
    #: ``secure`` below rather than trusting an operator to set both.
    session_cookie_samesite: str = "lax"

    session_ttl_seconds: int = 60 * 60 * 12
    worker_poll_seconds: int = 2
    worker_id: str = "worker-1"

    #: Allow the API process to run queued **research** jobs itself.
    #:
    #: Off by default, and it must stay that way for any long-lived
    #: deployment. The API refusing to run a backtest inline is not fastidious:
    #: a backtest is CPU-bound pandas work, and running one in the request
    #: handler stalls every other request on that event loop — including the
    #: one an operator is using to hit the kill switch.
    #:
    #: On a serverless host there is no shared event loop to stall. Each
    #: invocation is its own process, and there is nowhere to put a long-lived
    #: worker, so without this a queued backtest is never executed by anything.
    #: That is the only situation in which this should be true.
    #:
    #: It never covers trading jobs. See ``DRAINABLE_KINDS``.
    serverless_drain_enabled: bool = False

    #: Shared secret allowing a scheduler (Vercel Cron) to call the drain
    #: endpoint without an operator session. Empty disables that route in.
    cron_secret: str = ""

    #: Connection pool bounds.
    #:
    #: The default suits a long-lived process: one pool, reused for the life of
    #: the deployment. It is actively wrong on a serverless host, where every
    #: cold start builds its own pool and none of them share. Ten instances
    #: awake at once means up to a hundred connections, and a managed free tier
    #: typically allows a small fraction of that — so the failure is not a slow
    #: API but ``too many clients already``, arriving exactly when traffic
    #: picks up.
    #:
    #: Set the maximum to 2-3 there, and prefer a provider's pooled endpoint
    #: (Neon and Supabase both publish one) which multiplexes properly instead
    #: of leaving each instance to guess.
    db_pool_min_size: int = 1
    db_pool_max_size: int = 10

    alpaca_key_id: str = ""
    alpaca_secret_key: str = ""
    alpaca_paper: bool = True

    @property
    def has_broker_credentials(self) -> bool:
        return bool(self.alpaca_key_id and self.alpaca_secret_key)


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and validate settings once per process."""
    # Read, not required. See `require_database_url` for why the API tolerates
    # its absence and the worker does not.
    database_url = normalise_dsn(os.environ.get("DATABASE_URL", "").strip())

    # Read, not validated. Validation happens in `require_api_secrets`, called
    # by `create_app`. See that function for why.
    session_secret = os.environ.get("SESSION_SECRET", "").strip()
    admin_password_hash = os.environ.get("ADMIN_PASSWORD_HASH", "").strip()

    origins_raw = os.environ.get("CORS_ORIGINS", "").strip()
    # A bare hostname is completed to an https origin. Render's Blueprint can
    # wire one service's hostname into another's environment (`fromService`,
    # property `host`), which is what lets CORS_ORIGINS point at the UI without
    # anyone pasting a URL — but the property is a hostname, no scheme, and a
    # browser's Origin header always carries one. Left unnormalised, the
    # comparison fails exactly like an unset value: login 200, everything
    # after 401. https specifically, because a cross-site cookie is
    # SameSite=None and therefore Secure — an http origin could never present
    # it anyway.
    cors_origins = [
        o if "://" in o else f"https://{o}"
        for o in (piece.strip() for piece in origins_raw.split(","))
        if o
    ]

    samesite = os.environ.get("SESSION_COOKIE_SAMESITE", "lax").strip().lower()
    if samesite not in {"lax", "strict", "none"}:
        # Rejected rather than defaulted. A typo silently falling back to `lax`
        # would produce exactly the cross-site 401 this setting exists to fix,
        # with the configuration appearing to say otherwise.
        raise ConfigError(
            f"SESSION_COOKIE_SAMESITE must be one of lax, strict, none "
            f"(got {samesite!r})"
        )

    live = _bool_env("LIVE_TRADING_ENABLED", False)
    allow_live = _bool_env("ALPACA_ALLOW_LIVE", False)
    if live:
        logger.warning(
            "LIVE_TRADING_ENABLED is set. Real orders become possible once the "
            "database kill switch also permits trading."
        )
    if live and allow_live:
        logger.warning(
            "LIVE_TRADING_ENABLED *and* ALPACA_ALLOW_LIVE are both set. A "
            "deployment in live mode will place REAL orders."
        )
    if allow_live and not live:
        # Harmless on its own, and worth saying so: an operator who set only
        # this one may believe live trading is armed when it is not.
        logger.info(
            "ALPACA_ALLOW_LIVE is set but LIVE_TRADING_ENABLED is not; live "
            "trading remains disabled."
        )

    return Settings(
        database_url=database_url,
        session_secret=session_secret,
        admin_password_hash=admin_password_hash,
        live_trading_enabled=live,
        cors_origins=cors_origins,
        session_cookie_samesite=samesite,
        session_ttl_seconds=_int_env("SESSION_TTL_SECONDS", 60 * 60 * 12),
        worker_poll_seconds=_int_env("WORKER_POLL_SECONDS", 2),
        worker_id=os.environ.get("WORKER_ID", "worker-1"),
        serverless_drain_enabled=_bool_env("SERVERLESS_DRAIN_ENABLED", False),
        cron_secret=os.environ.get("CRON_SECRET", "").strip(),
        db_pool_min_size=_int_env("DB_POOL_MIN_SIZE", 1),
        db_pool_max_size=_int_env("DB_POOL_MAX_SIZE", 10),
        alpaca_key_id=os.environ.get("ALPACA_KEY_ID", ""),
        alpaca_secret_key=os.environ.get("ALPACA_SECRET_KEY", ""),
        alpaca_paper=_bool_env("ALPACA_PAPER", True),
        alpaca_allow_live=allow_live,
    )
