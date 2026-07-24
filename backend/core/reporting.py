"""Evidence-derived completeness metrics and report records.

Completeness is a factual measure of *how much of the plan actually ran and
produced traceable evidence*. It is deliberately NOT a quality, depth, or
professionalism score — the system never fabricates subjective judgements.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from backend.core.contracts import (
    AggregationResult,
    CompletenessMetric,
    ExecutionPlan,
    ExpertResult,
)


def _validation_status(result: ExpertResult) -> str | None:
    status = result.metadata.get("validation_status")
    if isinstance(status, str) and status:
        return status
    for evidence in result.evidence:
        if isinstance(evidence, dict):
            candidate = evidence.get("validation_status")
            if isinstance(candidate, str) and candidate:
                return candidate
    return None


def _has_evidence(result: ExpertResult) -> bool:
    if result.status != "completed":
        return False
    if result.evidence:
        return True
    if result.summary and result.summary.strip():
        return True
    report = result.metadata.get("report")
    return isinstance(report, str) and bool(report.strip())


def build_completeness(
    plan: ExecutionPlan,
    results: Mapping[str, ExpertResult],
) -> CompletenessMetric:
    """Derive execution completeness strictly from real plan steps and results."""

    planned = len(plan.steps)
    normalized = {
        step_id: ExpertResult.model_validate(result)
        for step_id, result in results.items()
    }
    step_results = [
        normalized[step.id] for step in plan.steps if step.id in normalized
    ]

    completed = sum(1 for r in step_results if r.status == "completed")
    failed = sum(1 for r in step_results if r.status == "failed")
    blocked = sum(1 for r in step_results if r.status == "blocked")
    evidence_steps = sum(1 for r in step_results if _has_evidence(r))

    completion_ratio = round(completed / planned, 4) if planned else 0.0
    evidence_coverage_ratio = (
        round(evidence_steps / planned, 4) if planned else 0.0
    )

    validation_summary: dict[str, int] = {}
    for result in step_results:
        status = _validation_status(result)
        if status:
            validation_summary[status] = validation_summary.get(status, 0) + 1

    return CompletenessMetric(
        planned_steps=planned,
        completed_steps=completed,
        failed_steps=failed,
        blocked_steps=blocked,
        completion_ratio=completion_ratio,
        evidence_coverage_ratio=evidence_coverage_ratio,
        validation_summary=validation_summary,
    )


def build_report_record(
    task_id: str,
    plan: ExecutionPlan,
    aggregation: AggregationResult,
    results: Mapping[str, ExpertResult],
) -> dict[str, Any]:
    """Assemble a persistable report snapshot: title, completeness, aggregation."""

    completeness = build_completeness(plan, results)
    return {
        "task_id": task_id,
        "title": plan.goal,
        "completeness": completeness.model_dump(mode="json"),
        "aggregation": aggregation.model_dump(mode="json"),
    }
