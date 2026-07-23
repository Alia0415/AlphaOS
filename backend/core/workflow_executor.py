"""Dependency-aware execution of Manager-generated task graphs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor

from backend.core.contracts import (
    AgentId,
    ExecutionEvent,
    ExecutionPlan,
    ExpertResult,
    ExpertTask,
)

ExpertHandler = Callable[[ExpertTask], ExpertResult]


class WorkflowExecutor:
    """Execute dependency-ready steps in parallel batches."""

    def __init__(
        self,
        handlers: Mapping[AgentId, ExpertHandler] | None = None,
    ) -> None:
        self._handlers = dict(handlers or {})

    def execute(
        self,
        plan: ExecutionPlan,
    ) -> tuple[list[ExecutionEvent], list[ExpertResult]]:
        if plan.needs_clarification:
            return [], []

        step_by_id = {step.id: step for step in plan.steps}
        pending = set(step_by_id)
        results: dict[str, ExpertResult] = {}
        events: list[ExecutionEvent] = []

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
            for step in sorted(blocked, key=lambda item: item.id):
                result = ExpertResult(
                    step_id=step.id,
                    agent=step.agent,
                    status="blocked",
                    error="A dependency did not complete successfully.",
                )
                results[step.id] = result
                pending.remove(step.id)
                events.append(
                    _event(
                        events,
                        result,
                        "blocked",
                        "Step blocked because a dependency failed.",
                    )
                )

            ready = [
                step_by_id[step_id]
                for step_id in pending
                if all(dependency in results for dependency in step_by_id[step_id].depends_on)
            ]
            if not ready:
                if pending:
                    raise RuntimeError("No executable steps remain in the task graph")
                break

            ready.sort(key=lambda item: item.id)
            tasks: list[ExpertTask] = []
            for step in ready:
                task = ExpertTask(
                    step_id=step.id,
                    agent=step.agent,
                    objective=step.objective,
                    expected_output=step.expected_output,
                    dependency_results={
                        dependency: results[dependency].output
                        for dependency in step.depends_on
                    },
                )
                tasks.append(task)
                events.append(
                    ExecutionEvent(
                        sequence=len(events) + 1,
                        step_id=step.id,
                        agent=step.agent,
                        status="started",
                        message="Step execution started.",
                    )
                )

            with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
                futures = [
                    pool.submit(self._execute_task, task)
                    for task in tasks
                ]
                batch_results = [future.result() for future in futures]

            for result in batch_results:
                results[result.step_id] = result
                pending.remove(result.step_id)
                status = "completed" if result.status == "completed" else "failed"
                events.append(
                    _event(
                        events,
                        result,
                        status,
                        (
                            "Step execution completed."
                            if status == "completed"
                            else "Step execution failed."
                        ),
                    )
                )

        ordered_results = [
            results[step.id]
            for step in plan.steps
            if step.id in results
        ]
        return events, ordered_results

    def _execute_task(self, task: ExpertTask) -> ExpertResult:
        handler = self._handlers.get(task.agent, _placeholder_handler)
        try:
            result = handler(task)
            if result.step_id != task.step_id or result.agent != task.agent:
                raise ValueError("Expert result does not match its assigned task")
            return result
        except Exception as exc:
            return ExpertResult(
                step_id=task.step_id,
                agent=task.agent,
                status="failed",
                error=str(exc),
            )


def _placeholder_handler(task: ExpertTask) -> ExpertResult:
    """Return a deterministic placeholder until real experts are implemented."""

    return ExpertResult(
        step_id=task.step_id,
        agent=task.agent,
        status="completed",
        output={
            "mode": "placeholder",
            "objective": task.objective,
            "expected_output": task.expected_output,
            "dependency_results": task.dependency_results,
        },
    )


def _event(
    events: list[ExecutionEvent],
    result: ExpertResult,
    status: str,
    message: str,
) -> ExecutionEvent:
    return ExecutionEvent(
        sequence=len(events) + 1,
        step_id=result.step_id,
        agent=result.agent,
        status=status,
        message=message,
    )
