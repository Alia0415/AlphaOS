"""Typed contracts for the AlphaOS skill runtime."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class SkillMode(str, Enum):
    """How a skill is used by its owning expert."""

    INSTRUCTION = "instruction"
    EXECUTABLE = "executable"
    HYBRID = "hybrid"


class SkillStatus(str, Enum):
    """Terminal status of one skill invocation."""

    COMPLETED = "completed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class SkillSpec(BaseModel):
    """Immutable, reviewable metadata for an allowlisted runtime skill."""

    id: str = Field(min_length=1, pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    mode: SkillMode
    enabled: bool = True
    owner_agents: list[str] = Field(min_length=1)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    source_repository: str = Field(min_length=1)
    source_ref: str = ""
    license: str = Field(min_length=1)
    runtime_path: str = Field(min_length=1)
    expected_entrypoint: str = Field(min_length=1)
    allowed_references: list[str] = Field(default_factory=list)
    required_references: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    required_task_inputs: list[str] = Field(default_factory=list)
    optional_task_inputs: list[str] = Field(default_factory=list)

    @field_validator(
        "owner_agents",
        "allowed_references",
        "required_references",
        "capabilities",
        "required_task_inputs",
        "optional_task_inputs",
    )
    @classmethod
    def values_must_be_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("SkillSpec list values must be unique")
        return values

    @model_validator(mode="after")
    def required_references_are_allowlisted(self) -> "SkillSpec":
        if not set(self.required_references).issubset(self.allowed_references):
            raise ValueError("Required references must also be allowlisted")
        return self


class SkillInvocation(BaseModel):
    """One authorized request from an expert to a runtime skill."""

    invocation_id: str = Field(min_length=1)
    skill_id: str = Field(min_length=1)
    agent: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    inputs: dict[str, Any] = Field(default_factory=dict)


class SkillResult(BaseModel):
    """Uniform result returned by every instruction or executable skill."""

    invocation_id: str = Field(min_length=1)
    skill_id: str = Field(min_length=1)
    status: SkillStatus
    summary: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None

    @model_validator(mode="after")
    def non_success_has_an_error(self) -> "SkillResult":
        if self.status in {SkillStatus.FAILED, SkillStatus.UNAVAILABLE} and not self.error:
            raise ValueError("failed and unavailable skill results require an error")
        return self
