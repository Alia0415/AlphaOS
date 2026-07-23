"""Typed contracts shared by AlphaOS planning and execution."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class AgentId(str, Enum):
    """Stable identifiers for experts available to the Manager Agent."""

    RESEARCH = "research"
    QUANT = "quant"
    RISK = "risk"
    PORTFOLIO = "portfolio"
    MACRO = "macro"
    REPORT = "report"


class AgentSelection(BaseModel):
    """An expert selected by the Manager and why it is needed."""

    agent: AgentId
    reason: str = Field(min_length=1)


class PlanStep(BaseModel):
    """One node in a dependency-aware execution plan."""

    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    agent: AgentId
    objective: str = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list, max_length=8)
    expected_output: str = Field(min_length=1)

    @field_validator("depends_on")
    @classmethod
    def dependencies_must_be_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("depends_on cannot contain duplicate step IDs")
        return values


class ExecutionPlan(BaseModel):
    """Validated task graph generated dynamically by the Manager Agent."""

    goal: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    complexity: Literal["low", "medium", "high"]
    selected_agents: list[AgentSelection] = Field(default_factory=list)
    steps: list[PlanStep] = Field(default_factory=list, max_length=8)
    needs_clarification: bool = False
    clarification_question: str | None = None


class ExpertTask(BaseModel):
    """Task packet sent by the workflow executor to one expert."""

    step_id: str
    agent: AgentId
    objective: str
    expected_output: str
    dependency_results: dict[str, Any] = Field(default_factory=dict)


class ExpertResult(BaseModel):
    """Structured result returned by an expert execution."""

    step_id: str
    agent: AgentId
    status: Literal["completed", "failed", "blocked"]
    output: Any = None
    error: str | None = None


class ExecutionEvent(BaseModel):
    """Ordered status transition emitted while executing a task graph."""

    sequence: int = Field(ge=1)
    step_id: str
    agent: AgentId
    status: Literal["started", "completed", "failed", "blocked"]
    message: str


class TaskExecutionResponse(BaseModel):
    """Complete response returned by ``POST /api/tasks``."""

    plan: ExecutionPlan
    execution_events: list[ExecutionEvent]
    expert_results: list[ExpertResult]
    final_answer: str
