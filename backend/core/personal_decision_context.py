"""Build the privacy-minimized orchestration context for personal tasks."""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.core.personal_constraint_evaluator import (
    PersonalConstraintEvaluator,
    PersonalConstraintResult,
)
from backend.core.profile_requirement_resolver import (
    ProfileFieldRequirements,
    ProfileRequirementResolver,
)
from backend.core.task_spec import TaskSpec
from backend.core.user_profile import UserInvestmentProfile


class PersonalPrivacyBoundary(BaseModel):
    shared_with_manager: list[str] = Field(default_factory=list)
    shared_with_risk: list[str] = Field(default_factory=list)
    shared_with_research: list[str] = Field(default_factory=list)
    shared_with_quant: list[str] = Field(default_factory=list)
    shared_with_macro: list[str] = Field(default_factory=list)
    not_shared_with_non_risk_agents: list[str] = Field(default_factory=list)
    raw_values_exposed_in_results: bool = False


class PersonalDecisionContext(BaseModel):
    requirements: ProfileFieldRequirements
    constraints: PersonalConstraintResult
    privacy_boundary: PersonalPrivacyBoundary

    def minimal_summary(self) -> dict:
        summary = self.constraints.minimal_summary()
        # Backward-compatible marker: the derived value is never disclosed.
        summary["monthly_surplus_cny"] = "not_shared"
        return summary


class PersonalDecisionContextBuilder:
    """Resolve requirements and evaluate constraints from canonical profile data."""

    def __init__(
        self,
        resolver: ProfileRequirementResolver | None = None,
        evaluator: PersonalConstraintEvaluator | None = None,
    ) -> None:
        self.resolver = resolver or ProfileRequirementResolver()
        self.evaluator = evaluator or PersonalConstraintEvaluator()

    def build(
        self,
        task_spec: TaskSpec,
        profile: UserInvestmentProfile | None,
    ) -> PersonalDecisionContext | None:
        requirements = self.resolver.required_fields_for(task_spec, profile)
        if requirements.decision_kind == "not_applicable":
            return None
        constraints = self.evaluator.evaluate(profile, requirements)
        return PersonalDecisionContext(
            requirements=requirements,
            constraints=constraints,
            privacy_boundary=PersonalPrivacyBoundary(
                shared_with_manager=[
                    "constraint codes",
                    "constraint severity",
                    "capacity level",
                    "field names only",
                ],
                shared_with_risk=[
                    "constraint codes",
                    "constraint severity",
                    "capacity level",
                    "field names only",
                ],
                shared_with_research=[],
                shared_with_quant=[],
                shared_with_macro=[],
                not_shared_with_non_risk_agents=constraints.fields_used,
                raw_values_exposed_in_results=False,
            ),
        )
