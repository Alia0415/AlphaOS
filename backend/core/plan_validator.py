"""Semantic validation for Manager-generated execution plans."""

from __future__ import annotations

from backend.core.agent_registry import AgentRegistry
from backend.core.contracts import AgentId, ExecutionPlan


class PlanValidationError(ValueError):
    """Raised when a structurally valid plan violates graph invariants."""


def validate_execution_plan(
    plan: ExecutionPlan,
    registry: AgentRegistry,
) -> ExecutionPlan:
    """Validate registry membership and task-graph invariants."""

    if len(plan.steps) > 8:
        raise PlanValidationError("Execution plans may contain at most 8 steps")

    selected = [selection.agent for selection in plan.selected_agents]
    if len(selected) != len(set(selected)):
        raise PlanValidationError("selected_agents contains duplicate agents")

    unknown_selected = set(selected) - registry.ids(enabled_only=True)
    if unknown_selected:
        raise PlanValidationError(
            f"Unknown or disabled selected agents: {_format_agents(unknown_selected)}"
        )

    step_ids = [step.id for step in plan.steps]
    if len(step_ids) != len(set(step_ids)):
        raise PlanValidationError("All step IDs must be unique")

    known_step_ids = set(step_ids)
    used_agents: set[AgentId] = set()
    dependencies: dict[str, list[str]] = {}
    for step in plan.steps:
        if not registry.contains(step.agent, enabled_only=True):
            raise PlanValidationError(
                f"Unknown or disabled step agent: {step.agent.value}"
            )
        used_agents.add(step.agent)
        dependencies[step.id] = step.depends_on
        unknown_dependencies = set(step.depends_on) - known_step_ids
        if unknown_dependencies:
            names = ", ".join(sorted(unknown_dependencies))
            raise PlanValidationError(
                f"Step {step.id} references unknown dependencies: {names}"
            )
        if step.id in step.depends_on:
            raise PlanValidationError(f"Step {step.id} cannot depend on itself")

    if set(selected) != used_agents:
        raise PlanValidationError(
            "selected_agents must exactly match the agents used by plan steps"
        )

    _assert_acyclic(dependencies)
    return plan


def _assert_acyclic(dependencies: dict[str, list[str]]) -> None:
    state: dict[str, int] = {}

    def visit(step_id: str) -> None:
        current = state.get(step_id, 0)
        if current == 1:
            raise PlanValidationError("Task graph contains a dependency cycle")
        if current == 2:
            return
        state[step_id] = 1
        for dependency in dependencies[step_id]:
            visit(dependency)
        state[step_id] = 2

    for step_id in dependencies:
        visit(step_id)


def _format_agents(agents: set[AgentId]) -> str:
    return ", ".join(sorted(agent.value for agent in agents))
