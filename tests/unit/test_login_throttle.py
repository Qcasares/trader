"""
test_login_throttle.py
----------------------
Failed-login backoff.

One account, one password: guessing it is the whole attack against a control
plane that places orders. bcrypt costs an attacker ~100ms a guess, which is ten
a second serially and far more in parallel — a real defence, not a sufficient
one.

Both directions are tested. A throttle that blocked everything would satisfy
"brute force is prevented" while locking the operator out of their own kill
switch, which during an incident is the worse failure.
"""

from __future__ import annotations

from src.api.throttle import (
    BASE_DELAY_SECONDS,
    FREE_ATTEMPTS,
    MAX_DELAY_SECONDS,
    WINDOW_SECONDS,
    LoginThrottle,
)

SOURCE = "203.0.113.7"


def test_a_fresh_source_may_attempt_immediately() -> None:
    assert LoginThrottle().retry_after(SOURCE, now=0.0) == 0.0


def test_the_free_allowance_is_not_throttled() -> None:
    """
    A fat-fingered password and a stale saved credential must not lock anyone
    out. The allowance exists so the control is invisible in normal use.
    """
    t = LoginThrottle()
    for attempt in range(FREE_ATTEMPTS):
        assert t.record_failure(SOURCE, now=float(attempt)) == 0.0
    assert t.retry_after(SOURCE, now=float(FREE_ATTEMPTS)) == 0.0


def test_backoff_doubles_past_the_allowance() -> None:
    t = LoginThrottle()
    for attempt in range(FREE_ATTEMPTS):
        t.record_failure(SOURCE, now=0.0)

    assert t.record_failure(SOURCE, now=0.0) == BASE_DELAY_SECONDS
    assert t.record_failure(SOURCE, now=0.0) == BASE_DELAY_SECONDS * 2
    assert t.record_failure(SOURCE, now=0.0) == BASE_DELAY_SECONDS * 4


def test_backoff_is_capped() -> None:
    """
    Long enough to make guessing hopeless, short enough to wait out.

    Without a ceiling a doubling sequence reaches days, and an operator who
    tripped it would have to redeploy to reach their own kill switch.
    """
    t = LoginThrottle()
    for _ in range(FREE_ATTEMPTS + 40):
        delay = t.record_failure(SOURCE, now=0.0)
    assert delay == MAX_DELAY_SECONDS


def test_the_block_expires_on_its_own() -> None:
    t = LoginThrottle()
    for _ in range(FREE_ATTEMPTS + 1):
        t.record_failure(SOURCE, now=0.0)

    assert t.retry_after(SOURCE, now=0.0) == BASE_DELAY_SECONDS
    assert t.retry_after(SOURCE, now=BASE_DELAY_SECONDS - 0.5) > 0
    assert t.retry_after(SOURCE, now=BASE_DELAY_SECONDS + 0.1) == 0.0


def test_the_window_lapses() -> None:
    """A single bad day must not lock a source out permanently."""
    t = LoginThrottle()
    for _ in range(FREE_ATTEMPTS + 5):
        t.record_failure(SOURCE, now=0.0)
    assert t.retry_after(SOURCE, now=WINDOW_SECONDS + 1) == 0.0


def test_a_correct_password_clears_the_history() -> None:
    """Suspicion ends when the operator proves who they are."""
    t = LoginThrottle()
    for _ in range(FREE_ATTEMPTS + 3):
        t.record_failure(SOURCE, now=0.0)
    assert t.retry_after(SOURCE, now=0.0) > 0

    t.record_success(SOURCE)
    assert t.retry_after(SOURCE, now=0.0) == 0.0


def test_sources_are_independent() -> None:
    """
    Keyed by source, not global, on purpose.

    A global counter is stronger against brute force and worse in practice: an
    attacker who cannot guess the password could still lock the operator out of
    the halt button by failing on purpose. That is the worse incident.
    """
    t = LoginThrottle()
    for _ in range(FREE_ATTEMPTS + 5):
        t.record_failure("198.51.100.1", now=0.0)

    assert t.retry_after("198.51.100.1", now=0.0) > 0
    assert t.retry_after("203.0.113.7", now=0.0) == 0.0
