"""Pure task-graph execution for Manager-generated AlphaOS plans."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast

from backend.agents.macro_agent import MacroAgent
from backend.agents.quant_agent import QuantAgent
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
        event_sink: Callable[[ExecutionEvent], None] | None = None,
    ) -> tuple[list[ExecutionEvent], dict[str, ExpertResult]]:
        """Run plan nodes in dependency-ready parallel batches.

        The executor never adds, removes, reorders, or selects business steps.
        When ``event_sink`` is provided, each emitted event is forwarded to it
        as it is produced (for streaming), without changing the batch semantics
        or the returned event list.
        """

        if plan.needs_clarification:
            return [], {}

        step_by_id = {step.id: step for step in plan.steps}
        pending = set(step_by_id)
        results: dict[str, ExpertResult] = {}
        events: list[ExecutionEvent] = []
        user_request = (original_user_request or plan.goal).strip()

        def emit(event: ExecutionEvent) -> None:
            events.append(event)
            if event_sink is not None:
                event_sink(event)

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
                    emit(
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
                emit(
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
                for internal_event in _safe_agent_events(result):
                    emit(
                        _event(
                            internal_event["type"],
                            result.task_id,
                            result.agent,
                            _agent_event_message(
                                internal_event["type"],
                                internal_event["metadata"].get("skill_id"),
                            ),
                            internal_event["metadata"],
                        )
                    )
                for call in result.tool_calls:
                    emit(
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
                emit(
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
        AgentId.QUANT: QuantAgent(),
        AgentId.RISK: RiskAgent(),
        AgentId.MACRO: MacroAgent(),
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
        type=cast(Any, event_type),
        step_id=step_id,
        agent=agent,
        message=message,
        metadata=metadata or {},
    )


_INTERNAL_EVENT_TYPES = {
    "skill_plan_created",
    "skill_started",
    "skill_completed",
    "skill_failed",
}
_SAFE_AGENT_EVENT_METADATA = {
    "skill_id",
    "status",
    "selected_skill_count",
    "skill_step_count",
    "scope",
}


def _safe_agent_events(result: ExpertResult) -> list[dict[str, Any]]:
    """Surface generic expert-internal events without raw data or instructions."""

    raw_events = result.metadata.get("agent_events", [])
    if not isinstance(raw_events, list):
        return []
    safe: list[dict[str, Any]] = []
    for item in raw_events:
        if not isinstance(item, dict) or item.get("type") not in _INTERNAL_EVENT_TYPES:
            continue
        raw_metadata = item.get("metadata", {})
        if not isinstance(raw_metadata, dict):
            raw_metadata = {}
        metadata = {
            key: raw_metadata.get(key)
            for key in _SAFE_AGENT_EVENT_METADATA
            if key in raw_metadata
        }
        metadata.setdefault("skill_id", item.get("skill_id"))
        safe.append({"type": item["type"], "metadata": metadata})
    return safe


def _agent_event_message(event_type: str, skill_id: Any) -> str:
    if event_type == "skill_plan_created":
        return "专家已创建内部 Skill Plan。"
    label = str(skill_id or "skill")
    messages = {
        "skill_started": f"{label} 开始执行。",
        "skill_completed": f"{label} 执行完成。",
        "skill_failed": f"{label} 执行失败。",
    }
    return messages[event_type]
