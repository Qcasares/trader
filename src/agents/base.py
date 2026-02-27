"""
base.py
-------
Base class for all specialist trading agents.
Each agent wraps a Claude model with a focused system prompt
and domain-specific tools.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class AgentRole(str, Enum):
    RESEARCH = "research"
    SENTIMENT = "sentiment"
    TECHNICAL = "technical"
    SIGNAL = "signal"
    RISK = "risk"
    EXECUTION = "execution"
    PORTFOLIO = "portfolio"


@dataclass
class AgentMessage:
    """Message passed between agents via the orchestrator."""

    sender: AgentRole
    recipient: AgentRole
    payload: dict[str, Any]
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    correlation_id: Optional[str] = None


@dataclass
class AgentResult:
    """Standardised result returned by every agent after a cycle."""

    agent: AgentRole
    success: bool
    data: dict[str, Any]
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    model_used: str = ""
    tokens_used: int = 0


class BaseAgent(ABC):
    """
    Abstract base for specialist trading agents.

    Each agent:
    - Has a role (AgentRole) and a configured Claude model
    - Receives context from the orchestrator
    - Produces a typed AgentResult
    - Logs all activity to the shared state store
    """

    def __init__(
        self,
        role: AgentRole,
        model: str,
        api_key: str,
    ) -> None:
        self._role = role
        self._model = model
        self._api_key = api_key
        self._logger = logging.getLogger(f"agent.{role.value}")

    @property
    def role(self) -> AgentRole:
        return self._role

    @property
    def model(self) -> str:
        return self._model

    @abstractmethod
    async def execute(self, context: dict[str, Any]) -> AgentResult:
        """
        Run one cycle of the agent's work.

        Parameters
        ----------
        context : dict
            Shared context from the orchestrator containing relevant
            data for this agent's domain.

        Returns
        -------
        AgentResult with the agent's output data.
        """
        ...

    @abstractmethod
    def system_prompt(self) -> str:
        """Return the system prompt that defines this agent's expertise."""
        ...

    def _build_result(
        self,
        success: bool,
        data: dict[str, Any],
        errors: Optional[list[str]] = None,
        duration_ms: float = 0.0,
        tokens_used: int = 0,
    ) -> AgentResult:
        """Helper to construct a standardised AgentResult."""
        return AgentResult(
            agent=self._role,
            success=success,
            data=data,
            errors=errors or [],
            duration_ms=duration_ms,
            model_used=self._model,
            tokens_used=tokens_used,
        )
