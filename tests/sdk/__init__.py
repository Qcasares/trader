"""
The Jev client's tests against the real ``typesafe_sdk``, and one call end to
end from the lane to the ledger.

Run where ``requirements-programme.lock`` is installed: CI's ``programme sdk``
job runs ``pytest tests/sdk -m sdk``. Everywhere else each module skips itself
with ``importorskip``, and the end-to-end module also skips without
``TEST_DATABASE_URL``.
"""
