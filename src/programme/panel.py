"""
panel.py
--------
Asking one role for its view. One function, and a boundary.

This is the half of the specialist panel that talks to a model. The other half
— who the twelve roles are, what each looks for, which of them hold a veto, how
an assessment is validated — is in :mod:`src.programme.roles`, and the split is
structural rather than tidy-minded.

``src/api`` imports ``roles`` because the findings page renders the vocabulary:
every role, its mandate, and whether raising a finding under its name blocks a
gate. While ``assess`` lived beside that vocabulary, importing it also imported
``src.programme.client``, so the process that commands the worker held a model
client through two hops without any file in ``src/api`` ever naming one. Every
check in ``tests/unit/test_import_boundaries.py`` passed while that was true,
because they all read one module's own imports.

That test now walks the closure, and this module is the reason it can. It is
the same move as ``src/programme/models.py`` and ``src/programme/flags.py``: a
vocabulary two processes need lives where the SDK is forbidden, and the code
that needs the SDK lives somewhere only the runner imports.

A lazy import inside ``assess`` would have hidden the SDK from the API process
without removing its reach, and this repository has already decided that
question once — ``src/llm`` is off-limits to the decision path *because* it
imports its client lazily, and blocking only the direct import would leave the
door open.
"""

from __future__ import annotations

import logging

from src.programme.client import ModelCall, ask_json
from src.programme.models import ModelSettings
from src.programme.roles import Assessment, Role, system_prompt, validate_assessment

logger = logging.getLogger(__name__)


async def assess(
    role: Role,
    api_key: str | None,
    settings: ModelSettings,
    facts_brief: str,
) -> Assessment:
    """
    Ask one role for its view.

    ``facts_brief`` is rendered from rows by the caller. This function never
    fetches anything: a role sees exactly what the programme decided to show
    it, and that decision is auditable in one place.
    """
    payload = await ask_json(
        ModelCall(
            system=system_prompt(role),
            prompt=(
                "Assess this candidate for promotion out of its current "
                "stage.\n\n"
                f"{facts_brief}\n\n"
                "Return a JSON object with keys: verdict, summary, findings."
            ),
            max_tokens=1500,
        ),
        api_key,
        settings,
    )
    assessment = Assessment(**payload)
    validate_assessment(assessment)
    return assessment
