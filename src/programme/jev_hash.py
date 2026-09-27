"""
jev_hash.py
-----------
The hashes a Jev request, its questions and a text subject are known by. Pure:
``hashlib`` and ``json``, and nothing else, so that the programme's modules —
the lane, the registry, the evaluation harness phase C adds — and the API once
it reads the ledger may import it without importing the client that holds
TypeSafe's SDK. Not the worker or the decision path: they may load nothing of
``src/programme``, a pure module included
(``test_import_boundaries.py::test_the_order_path_cannot_reach_the_programme_at_all``).

The request hash moved here from ``jev_lane`` unchanged, and ``jev_lane``
re-exports it, so every existing caller keeps working and a row written before
the move still recomputes its own hash after it. That is the property a replay
rests on: the ledger finds an answer by the hash of the request that left, so a
formula that drifted would stop finding answers already paid for, and would
find nothing wrong in doing so. ``tests/unit/test_jev_hash.py`` pins it to a
value computed by phase B's code.

Three decisions, each held by a test:

* **A state's keys are sorted, at every depth; a question's are not.** The
  state is a record of values, and ``jsonb`` reorders its keys anyway. The
  order of the questions and of their options is part of what the model reads,
  so two orders are two requests.
* **Compact, ``ensure_ascii=False``, and no NaN.** The text hashed is the text a
  reader would write down, and JSON cannot spell a NaN or an infinity, so no
  request could have carried one.
* **A text subject is its content.** :func:`text_sha256` is the address the
  lane requires of a web excerpt or a hypothesis title, and what
  ``web_documents.content_sha256`` holds — by CHECK, which computes the same
  sha256 of the stored excerpt (migration 0013) — so a label, an answer and a
  document about the same words join exactly, whichever source or set they
  came from.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def state_hash(state: Any) -> str:
    """sha256 of ``state`` with its keys sorted, compact, as UTF-8."""
    return _sha256(_canonical(_keys_sorted(state)))


def request_hash(model: str, state: Any, questions: Mapping[str, Any]) -> str:
    """
    sha256 of the canonical request, ``{model, state, questions}``: the key a
    replay is found by.

    The state's keys are sorted, at every depth, because their order carries
    nothing: the state is a record of values, and the ledger's ``jsonb`` column
    reorders them anyway. The questions are not sorted, nor their options,
    because their order is part of what the model reads — moving an option has
    been seen to move an ambiguous answer — so two orders are two requests.
    Lists keep their order everywhere; in a state, order is data.

    Compact and ``ensure_ascii=False``, like the pack hash, so the text hashed
    is the text a reader would write down. A NaN or an infinity raises: JSON
    cannot spell either, so no request could have carried one.

    It names no question set. Two sets sending identical words about an
    identical state did send the same request; which set may read the answer
    is a separate question, and the lane answers it by the pack hash
    (docs/08 open item 15).
    """
    return _sha256(
        _canonical(
            {"model": model, "state": _keys_sorted(state), "questions": questions}
        )
    )


def questions_hash(questions: Mapping[str, Any]) -> str:
    """
    sha256 of the questions exactly as the request hash serialises them: the
    part of a request that a question set contributes, in its order.

    Two sets with the same questions hash send byte-identical questions, so
    about an identical state and under one model they send the same request and
    would share its one canonical answer. The registry refuses a second set
    with a hash already registered, and the test suite holds every released
    version's hash to be distinct from every other's (open item 15).
    """
    return _sha256(_canonical(questions))


def text_sha256(text: str) -> str:
    """
    sha256 of ``text`` as UTF-8: the content address of a text subject.

    A web excerpt's subject id, a hypothesis title's, and the
    ``content_sha256`` of the document an excerpt was stored in are all this,
    so the lane can require that a subject is exactly the text it sends, and a
    label joins the answer to the words it labels. :class:`TypeError` for
    anything but text; text that is not valid Unicode raises too, and the lane
    refuses such text before it is ever hashed.
    """
    if not isinstance(text, str):
        raise TypeError(f"a text subject is text, got {type(text).__name__}")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _keys_sorted(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _keys_sorted(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_keys_sorted(item) for item in value]
    return value


def _canonical(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = [
    "questions_hash",
    "request_hash",
    "state_hash",
    "text_sha256",
]
