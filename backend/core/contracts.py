"""Typed contracts shared by AlphaOS planning and execution."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


RESEARCH_DISCLAIMER = "本结果仅用于研究与演示，不构成投资建议、荐股或收益承诺。"


class AgentId(str, Enum):
    """Stable identifiers for experts in the complete expert pool."""

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
    inputs: dict[str, Any] = Field(default_factory=dict)
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

    @model_validator(mode="after")
    def clarification_is_actionable(self) -> "ExecutionPlan":
        if self.needs_clarification and not (
            self.clarification_question and self.clarification_question.strip()
        ):
            raise ValueError(
                "clarification_question is required when needs_clarification is true"
            )
        return self


class ExpertTask(BaseModel):
    """Uniform task packet sent by the workflow executor to one expert."""

    task_id: str = Field(min_length=1)
    agent: AgentId
    objective: str = Field(min_length=1)
    original_user_request: str = Field(min_length=1)
    inputs: dict[str, Any] = Field(default_factory=dict)
    dependency_results: dict[str, "ExpertResult"] = Field(default_factory=dict)

    @property
    def step_id(self) -> str:
        """Backward-compatible in-process name for older handlers."""

        return self.task_id


class ExpertResult(BaseModel):
    """Uniform, validated result returned by every expert."""

    task_id: str = Field(min_length=1)
    agent: AgentId
    status: Literal["completed", "failed", "blocked"]
    summary: str = ""
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    data_sources: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None

    @model_validator(mode="after")
    def failure_has_an_error(self) -> "ExpertResult":
        if self.status in {"failed", "blocked"} and not self.error:
            raise ValueError("failed and blocked expert results require an error")
        return self

    @property
    def step_id(self) -> str:
        """Backward-compatible in-process name for event ordering."""

        return self.task_id

    @property
    def output(self) -> dict[str, Any]:
        """Expose the complete structured result, never a flattened text blob."""

        return self.model_dump(mode="json")


class ExecutionEvent(BaseModel):
    """Ordered, frontend-ready orchestration event."""

    type: Literal[
        "plan_created",
        "clarification_required",
        "step_started",
        "tool_called",
        "step_completed",
        "step_failed",
        "synthesis_started",
        "task_completed",
    ]
    step_id: str | None = None
    agent: AgentId | None = None
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskExecutionResponse(BaseModel):
    """Complete response returned by ``POST /api/tasks``."""

    plan: ExecutionPlan
    events: list[ExecutionEvent]
    results: dict[str, ExpertResult]
    final_answer: str
    duration_ms: int = Field(ge=0)
    disclaimer: str = RESEARCH_DISCLAIMER
