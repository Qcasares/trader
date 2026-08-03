"""
The AI programme.

A third process, alongside the API and the worker. It is the only part of this
system permitted to hold a model client, and it is the only part forbidden from
importing anything that can submit an order — the mirror image of the guarantee
``tests/unit/test_import_boundaries.py`` already enforces on ``src/api`` and
``src/worker``, and enforced by the same test.

It talks to the rest of the system through Postgres rows and by enqueuing work
into the existing ``jobs`` table. It proposes; the engine measures;
:mod:`src.programme.gates` decides.

    python -m src.programme.main
"""

from __future__ import annotations
