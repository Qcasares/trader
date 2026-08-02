"""
llm
---
The demoted LLM: commentary only.

Nothing in this package may be imported by ``src/core``, ``src/strategies``,
``src/engine``, ``src/execution`` or ``src/data``. That boundary is enforced by
``tests/unit/test_import_boundaries.py`` and is what closes the
prompt-injection path recorded as C-1 in ``docs/02-security-audit.md``: a
successful injection here produces misleading prose, not a trade.
"""

from src.llm.commentary import (  # noqa: F401
    CommentaryRequest,
    backtest_request,
    build_prompt,
    decision_request,
    generate_commentary,
    latest_for,
)
from src.llm.sanitize import fence, looks_like_injection, sanitize  # noqa: F401

__all__ = [
    "CommentaryRequest",
    "backtest_request",
    "build_prompt",
    "decision_request",
    "fence",
    "generate_commentary",
    "latest_for",
    "looks_like_injection",
    "sanitize",
]
