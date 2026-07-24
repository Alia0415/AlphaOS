"""Normalized research-task contract created before Manager planning."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


TaskType = Literal[
    "personal_investment_decision",
    "market_research",
    "company_research",
    "factor_research",
    "historical_analysis",
    "risk_review",
    "comparison",
    "formal_report",
]
SubjectType = Literal[
    "personal_finance",
    "company",
    "industry",
    "factor",
    "market",
    "macro_theme",
    "research_thesis",
]


class TaskSpec(BaseModel):
    """The sole normalized research goal supplied to the Manager."""

    task_type: TaskType
    subject_type: SubjectType
    subjects: list[str] = Field(default_factory=list)
    market: str | None = None
    research_goal: str = Field(min_length=1)
    expected_result_type: str = Field(min_length=1)
    start_date: str | None = None
    end_date: str | None = None
    time_range_description: str | None = None
    evidence_requirements: list[str] = Field(default_factory=list)
    requested_validation_level: str = "research_draft"
    assumptions: list[str] = Field(default_factory=list)
    defaulted_fields: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    execution_decision: Literal[
        "execute",
        "execute_with_defaults",
        "clarify",
    ]
    clarification_question: str | None = None

    @model_validator(mode="after")
    def clarification_is_explicit(self) -> "TaskSpec":
        if self.execution_decision == "clarify" and not (
            self.clarification_question and self.clarification_question.strip()
        ):
            raise ValueError(
                "clarification_question is required when execution_decision=clarify"
            )
        return self
