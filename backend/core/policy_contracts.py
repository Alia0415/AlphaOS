"""Contracts for deterministic request-boundary decisions."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


PolicyDecisionType = Literal[
    "allowed_research",
    "out_of_domain",
    "personalized_recommendation",
    "trading_execution",
    "guaranteed_return",
]


class PolicyDecision(BaseModel):
    """A user-visible, auditable request policy decision."""

    decision: PolicyDecisionType
    allowed: bool
    domain: str
    policy_tags: list[str] = Field(default_factory=list)
    reason: str
    safe_response: str | None = None
    suggested_research_tasks: list[str] = Field(default_factory=list)
