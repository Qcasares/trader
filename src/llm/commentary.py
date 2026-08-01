"""
commentary.py
-------------
The demoted LLM.

This is what "demote the agents to research and commentary" means in code. The
model reads a decision that has **already been made and recorded**, and writes
prose about it. It has no tools, no function calling, no broker access, and no
route to an order — that last one enforced by
``tests/unit/test_import_boundaries.py``, which fails the build if anything
under ``src/core``, ``src/strategies``, ``src/engine``, ``src/execution``,
``src/data``, ``src/worker`` or ``src/api`` imports an LLM client, this
package included.

``src/worker`` matters most of that list and was the last to be covered: it is
the only process that places an order. If commentary is ever wanted after a
backtest completes, it belongs in a separate job rather than in the process
holding the broker credentials.

The consequence is worth stating plainly: a completely successful prompt
injection against this module produces misleading prose in the ``commentary``
table. It cannot move money, because there is no code path from here to an
order.

Inputs are numbers we computed
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The prompt is built from a decision row and its metrics — figures the
deterministic engine produced. No external text is fetched. If that ever
changes, it goes through :mod:`src.llm.sanitize` first, and the residual risk
becomes social: a human reading injected commentary could be talked into
flipping the kill switch. Hence the badge in the UI and the typed confirmation
on every control action.
"""

from __future__ import annotations

import json
import logging
import secrets
from dataclasses import dataclass
from datetime import date
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)

#: Haiku is ample for describing numbers that are already computed.
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """\
You are a reporting assistant for a systematic trading system. You explain \
decisions that have already been made and executed. You do not make \
recommendations, you do not predict, and nothing you write causes any action.

Rules:
- Describe only what the supplied figures show. Never infer a cause the data \
does not support.
- If a Sharpe ratio is marked not statistically significant, say so plainly \
rather than reporting the number as a result.
- If the data source is synthetic, state in the first sentence that these are \
generated prices and say nothing about real-world performance.
- Never suggest a parameter change, a trade, or a deployment.
- Two short paragraphs at most. Plain prose, no headings, no bullet lists.
"""


@dataclass(frozen=True, slots=True)
class CommentaryRequest:
    """What to write about."""

    scope: str  # "backtest" | "decision" | "session"
    ref_id: str
    payload: dict[str, Any]


class CommentaryError(RuntimeError):
    """Generation failed. Never fatal — commentary is decoration."""


async def generate_commentary(
    conn: asyncpg.Connection,
    request: CommentaryRequest,
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
) -> str | None:
    """
    Produce commentary and store it.

    Returns ``None`` when no API key is configured, rather than raising:
    commentary is a nicety, and a system that cannot trade because it cannot
    write prose about trading has its priorities inverted.
    """
    if not api_key:
        logger.info("No ANTHROPIC_API_KEY; skipping commentary generation")
        return None

    prompt = build_prompt(request)
    try:
        body = await _call_model(prompt, api_key, model)
    except Exception as exc:  # noqa: BLE001 - never fatal
        logger.warning("Commentary generation failed: %s", exc)
        return None

    await conn.execute(
        "INSERT INTO commentary (scope, ref_id, model, body_md) "
        "VALUES ($1, $2, $3, $4)",
        request.scope,
        request.ref_id,
        model,
        body,
    )
    return body


def build_prompt(request: CommentaryRequest) -> str:
    """
    Render the request as a prompt.

    Everything here is a figure the engine computed. The nonce-fenced block
    exists for the day this includes external text; today there is none, and
    that is the point.
    """
    nonce = secrets.token_hex(4)
    facts = json.dumps(request.payload, indent=2, default=str, sort_keys=True)
    return (
        f"Write commentary on this {request.scope}. These figures were "
        f"computed by the trading engine and are authoritative.\n\n"
        f"<<<FACTS-{nonce}>>>\n{facts}\n<<<END-FACTS-{nonce}>>>\n"
    )


def backtest_request(run: dict[str, Any]) -> CommentaryRequest:
    """Build a request from a completed backtest run."""
    metrics = run.get("metrics") or {}
    return CommentaryRequest(
        scope="backtest",
        ref_id=str(run["id"]),
        payload={
            "strategy": run.get("strategy_name"),
            "universe": run.get("universe"),
            "window": f"{run.get('start_session')} to {run.get('end_session')}",
            "data_source": run.get("data_source"),
            "is_synthetic_data": run.get("data_source") == "synthetic",
            "total_return": metrics.get("total_return"),
            "cagr": metrics.get("cagr"),
            "volatility": metrics.get("volatility"),
            "sharpe": metrics.get("sharpe"),
            "sharpe_standard_error": metrics.get("sharpe_stderr"),
            "sharpe_is_statistically_significant": metrics.get(
                "sharpe_is_significant"
            ),
            "max_drawdown": metrics.get("max_drawdown"),
            "exposure": metrics.get("exposure"),
            "effective_start_full_universe": metrics.get("effective_start"),
            "cost_stress_multiplier": metrics.get("cost_stress_multiplier"),
            "n_rebalances": metrics.get("n_rebalances"),
        },
    )


def decision_request(
    decision: dict[str, Any], session: date
) -> CommentaryRequest:
    """Build a request from a live decision that has already been recorded."""
    return CommentaryRequest(
        scope="decision",
        ref_id=str(decision["id"]),
        payload={
            "session": session.isoformat(),
            "target_weights": decision.get("target_weights"),
            "rationale": decision.get("rationale"),
            "order_count": len(decision.get("order_intents") or []),
            "status": decision.get("status"),
        },
    )


async def _call_model(prompt: str, api_key: str, model: str) -> str:
    """
    Send the prompt.

    The client is imported lazily so the engine has no import-time dependency
    on an LLM SDK — the whole system must run, and be testable, without one.
    Note there are no tools passed: the model can emit text and nothing else.
    """
    try:
        from anthropic import AsyncAnthropic
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise CommentaryError(
            "anthropic is not installed; commentary is unavailable"
        ) from exc

    client = AsyncAnthropic(api_key=api_key)
    response = await client.messages.create(
        model=model,
        max_tokens=600,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    parts = [block.text for block in response.content if block.type == "text"]
    return "\n".join(parts).strip()


async def latest_for(
    conn: asyncpg.Connection, scope: str, ref_id: str
) -> dict[str, Any] | None:
    """Most recent commentary for one subject."""
    row = await conn.fetchrow(
        "SELECT scope, ref_id, model, body_md, created_at FROM commentary "
        "WHERE scope = $1 AND ref_id = $2 ORDER BY created_at DESC LIMIT 1",
        scope,
        ref_id,
    )
    if row is None:
        return None
    return {
        "scope": row["scope"],
        "ref_id": row["ref_id"],
        "model": row["model"],
        "body_md": row["body_md"],
        "created_at": row["created_at"].isoformat(),
        # The UI renders this as a badge. Commentary is output, never input.
        "disclaimer": "Generated commentary — not a trading input.",
    }
