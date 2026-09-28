"""
job_errors.py
-------------
How a programme job says it failed, and which failed calls another attempt
could change.

Its own module because every Jev handler needs it and the handlers are not
all in ``main.py``: the forward clock's (``jev_forward``) and the re-ask's
(``jev_jobs``) are modules of their own, and ``main`` imports them, so the
error they raise cannot live in ``main`` without a cycle. ``main`` re-exports
:class:`JobFailedError`, so every existing import of it still works.

Pure: the standard library, and nothing else.
"""

from __future__ import annotations


class JobFailedError(Exception):
    """
    A handler's verdict that its job failed, and whether asking again could
    change it.

    Raised rather than returned, so that a job whose work came to nothing is
    never recorded as ``succeeded`` with its reason buried in a result nobody
    reads. The jobs page shows status and error; this puts the verdict in both.
    """

    def __init__(self, error: str, *, retry: bool) -> None:
        super().__init__(error)
        self.error = error
        self.retry = retry


#: The failed calls another attempt could change: no response, a rate limit or
#: a vendor fault. A refused key, a refused request or an unreadable answer will
#: be refused again. ``tests/unit/test_job_ownership.py`` holds it to the
#: client's own vocabulary, ``jev_client.ERROR_KINDS``, which this module may
#: not import: only the lane and the key check import the client.
RETRIED_ERROR_KINDS: frozenset[str] = frozenset(
    {"connection", "timeout", "rate_limited", "server"}
)

__all__ = ["RETRIED_ERROR_KINDS", "JobFailedError"]
