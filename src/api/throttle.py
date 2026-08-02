"""
throttle.py
-----------
Failed-login backoff.

There is one account and one password. Guessing it is therefore the whole
attack against this control plane, and the control plane can move money.

bcrypt already costs an attacker roughly 100ms per attempt, which is a real
defence but not a sufficient one: 100ms serially is ten guesses a second, and
nothing stopped an attacker opening fifty connections and doing it in parallel.

Why per-source rather than global
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A global counter is strictly stronger against brute force and strictly worse
in practice: an attacker who cannot guess the password can still lock the
operator out of their own kill switch by failing on purpose. Losing access to
the halt button during an incident is a worse outcome than the brute force
this would prevent, so the counter is keyed by source address.

That is a real trade-off, not a free win: an attacker who can rotate source
addresses evades it. It raises the cost from "a shell loop" to "a proxy pool",
which is the honest description of what this buys.

Limitations, stated rather than discovered later
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
State is in-process. Two API replicas each keep their own counter, and a
restart clears it. For a single-operator deployment that is proportionate;
anything more would mean a shared store, and inventing one to defend an
account that does not exist yet is the kind of complexity this codebase keeps
refusing.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

#: Failures tolerated before backoff begins. Generous enough to survive a
#: fat-fingered password and a stale saved credential.
FREE_ATTEMPTS = 5

#: Backoff doubles per failure past the free allowance, from this base.
BASE_DELAY_SECONDS = 2.0

#: Ceiling on a single lockout. Long enough to make guessing hopeless, short
#: enough that a legitimate operator who tripped it can wait it out rather than
#: redeploying to clear it.
MAX_DELAY_SECONDS = 300.0

#: Failures older than this stop counting, so a single bad day does not lock a
#: source out permanently.
WINDOW_SECONDS = 900.0


@dataclass
class _Record:
    failures: int = 0
    first_failure: float = 0.0
    blocked_until: float = 0.0


@dataclass
class LoginThrottle:
    """
    Tracks failed logins per source address.

    Deliberately not a general rate limiter. It counts *failures* only, so a
    working session is never throttled however many requests it makes, and the
    only thing it can delay is guessing.
    """

    _records: dict[str, _Record] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def retry_after(self, source: str, now: float | None = None) -> float:
        """
        Seconds this source must wait, or ``0.0`` if it may attempt now.
        """
        now = now if now is not None else time.time()
        with self._lock:
            record = self._records.get(source)
            if record is None:
                return 0.0
            if now - record.first_failure > WINDOW_SECONDS:
                # The window lapsed; forget it entirely rather than decaying,
                # which keeps the rule easy to reason about under pressure.
                del self._records[source]
                return 0.0
            return max(0.0, record.blocked_until - now)

    def record_failure(self, source: str, now: float | None = None) -> float:
        """Count a failed attempt and return the resulting wait, in seconds."""
        now = now if now is not None else time.time()
        with self._lock:
            record = self._records.get(source)
            if record is None or now - record.first_failure > WINDOW_SECONDS:
                record = _Record(first_failure=now)
                self._records[source] = record

            record.failures += 1
            over = record.failures - FREE_ATTEMPTS
            if over <= 0:
                return 0.0

            delay = min(BASE_DELAY_SECONDS * (2 ** (over - 1)), MAX_DELAY_SECONDS)
            record.blocked_until = now + delay
            logger.warning(
                "Login backoff: %d failures from %s; blocked for %.0fs",
                record.failures,
                source,
                delay,
            )
            return delay

    def record_success(self, source: str) -> None:
        """Clear a source's history. A correct password ends the suspicion."""
        with self._lock:
            self._records.pop(source, None)

    def reset(self) -> None:
        """Drop all state. For tests and for an operator-initiated restart."""
        with self._lock:
            self._records.clear()


#: Process-wide instance. Module-level rather than injected because it must
#: outlive individual requests and there is exactly one API process per replica.
throttle = LoginThrottle()
