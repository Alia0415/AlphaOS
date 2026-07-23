"""Pure task-graph execution for Manager-generated AlphaOS plans."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from backend.agents.report_agent import ReportAgent
from backend.agents.research_agent import ResearchAgent
from backend.agents.risk_agent import RiskAgent
from backend.core.agent_registry import AgentRegistry
from backend.core.contracts import (
    AgentId,
    ExecutionEvent,
    ExecutionPlan,
    ExpertResult,
    ExpertTask,
)

ExpertHandler = Callable[[ExpertTask], ExpertResult]


class WorkflowExecutor:
    """Execute exactly the nodes and edges supplied by an arbitrary valid DAG."""

    def __init__(
        self,
        handlers: Mapping[AgentId, ExpertHandler] | None = None,
        registry: AgentRegistry | None = None,
    ) -> None:
        self._registry = registry or AgentRegistry()
        self._handlers = (
            dict(handlers) if handlers is not None else _default_handlers()
        )

    def execute(
        self,
        plan: ExecutionPlan,
        original_user_request: str | None = None,
    ) -> tuple[list[ExecutionEvent], dict[str, ExpertResult]]:
        """Run plan nodes in dependency-ready parallel batches.

        The executor never adds, removes, reorders, or selects business steps.
        """

        if plan.needs_clarification:
            return [], {}

        step_by_id = {step.id: step for step in plan.steps}
        pending = set(step_by_id)
        results: dict[str, ExpertResult] = {}
        events: list[ExecutionEvent] = []
        user_request = (original_user_request or plan.goal).strip()

        while pending:
            blocked = [
                step_by_id[step_id]
                for step_id in pending
                if any(
                    dependency in results
                    and results[dependency].status != "completed"
                    for dependency in step_by_id[step_id].depends_on
                )
            ]
            if blocked:
                for step in sorted(blocked, key=lambda item: item.id):
                    result = ExpertResult(
                        task_id=step.id,
                        agent=step.agent,
                        status="blocked",
                        summary="步骤因必需依赖失败而被阻断。",
                        error="A required dependency did not complete successfully.",
                    )
                    results[step.id] = result
                    pending.remove(step.id)
                    events.append(
                        _event(
                            "step_failed",
                            step.id,
                            step.agent,
                            "步骤因必需依赖失败而被阻断。",
                            {"status": "blocked"},
                        )
                    )
                # Re-evaluate descendants so a newly blocked result cannot run.
                continue

            ready = [
                step_by_id[step_id]
                for step_id in pending
                if all(
                    dependency in results
                    for dependency in step_by_id[step_id].depends_on
                )
            ]
            if not ready:
                if pending:
                    raise RuntimeError("No executable steps remain in the task graph")
                break

            ready.sort(key=lambda item: item.id)
            tasks: list[ExpertTask] = []
            for step in ready:
                task = ExpertTask(
                    task_id=step.id,
                    agent=step.agent,
                    objective=step.objective,
                    original_user_request=user_request,
                    inputs=step.inputs,
                    dependency_results={
                        dependency: results[dependency]
                        for dependency in step.depends_on
                    },
                )
                tasks.append(task)
                events.append(
                    _event(
                        "step_started",
                        step.id,
                        step.agent,
                        f"{self._registry.get(step.agent).name} 开始执行任务。",
                    )
                )

            with ThreadPoolExecutor(max_workers=max(1, len(tasks))) as pool:
                futures = [pool.submit(self._execute_task, task) for task in tasks]
                batch_results = [future.result() for future in futures]

            for result in batch_results:
                results[result.task_id] = result
                pending.remove(result.task_id)
                for call in result.tool_calls:
                    events.append(
                        _event(
                            "tool_called",
                            result.task_id,
                            result.agent,
                            f"{result.agent.value} 调用了 {call.get('tool', 'tool')}。",
                            {"tool": call.get("tool"), "status": call.get("status")},
                        )
                    )
                event_type = (
                    "step_completed"
                    if result.status == "completed"
                    else "step_failed"
                )
                events.append(
                    _event(
                        event_type,
                        result.task_id,
                        result.agent,
                        (
                            f"{result.agent.value} 步骤执行完成。"
                            if result.status == "completed"
                            else f"{result.agent.value} 步骤执行失败。"
                        ),
                    )
                )

        # Dict insertion order is normalized to the plan, not completion timing.
        return events, {
            step.id: results[step.id]
            for step in plan.steps
            if step.id in results
        }

    def _execute_task(self, task: ExpertTask) -> ExpertResult:
        if not self._registry.is_enabled(task.agent):
            return _failure(
                task,
                f"Expert '{task.agent.value}' is disabled and cannot execute.",
            )
        handler = self._handlers.get(task.agent)
        if handler is None:
            return _failure(
                task,
                f"No real implementation is registered for '{task.agent.value}'.",
            )
        try:
            raw_result: Any = handler(task)
            result = ExpertResult.model_validate(raw_result)
            if result.task_id != task.task_id or result.agent != task.agent:
                raise ValueError("Expert result does not match its assigned task")
            return result
        except Exception:
            return _failure(task, "Expert execution raised an internal error.")


def _default_handlers() -> dict[AgentId, ExpertHandler]:
    return {
        AgentId.RESEARCH: ResearchAgent(),
        AgentId.RISK: RiskAgent(),
        AgentId.REPORT: ReportAgent(),
    }


def _failure(task: ExpertTask, error: str) -> ExpertResult:
    return ExpertResult(
        task_id=task.task_id,
        agent=task.agent,
        status="failed",
        summary="专家步骤未成功执行。",
        limitations=[error],
        error=error,
    )


def _event(
    event_type: str,
    step_id: str | None,
    agent: AgentId | None,
    message: str,
    metadata: dict[str, Any] | None = None,
) -> ExecutionEvent:
    return ExecutionEvent(
        type=event_type,
        step_id=step_id,
        agent=agent,
        message=message,
        metadata=metadata or {},
    )
