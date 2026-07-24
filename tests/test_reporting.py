"""Completeness metrics must be derived from real results, never invented."""

from __future__ import annotations

from backend.core.contracts import CompletenessMetric, ExecutionPlan, ExpertResult
from backend.core.reporting import build_completeness, build_report_record


def _plan(*step_ids_and_agents: tuple[str, str]) -> ExecutionPlan:
    steps = [
        {
            "id": step_id,
            "agent": agent,
            "objective": f"{agent} objective",
            "inputs": {},
            "depends_on": [],
            "expected_output": "out",
        }
        for step_id, agent in step_ids_and_agents
    ]
    return ExecutionPlan.model_validate(
        {
            "goal": "分析并成文",
            "intent": "执行",
            "complexity": "high",
            "selected_agents": [
                {"agent": agent, "reason": "需要"}
                for agent in {agent for _sid, agent in step_ids_and_agents}
            ],
            "steps": steps,
            "needs_clarification": False,
            "clarification_question": None,
        }
    )


def test_completeness_from_fully_completed_plan() -> None:
    plan = _plan(("research_1", "research"), ("report_1", "report"))
    results = {
        "research_1": ExpertResult(
            task_id="research_1",
            agent="research",
            status="completed",
            summary="研究结论",
            evidence=[{"validation_status": "verified"}],
            metadata={"validation_status": "verified"},
        ),
        "report_1": ExpertResult(
            task_id="report_1",
            agent="report",
            status="completed",
            summary="报告摘要",
            metadata={"report": "完整报告正文"},
        ),
    }

    metric = build_completeness(plan, results)

    assert isinstance(metric, CompletenessMetric)
    assert metric.planned_steps == 2
    assert metric.completed_steps == 2
    assert metric.completion_ratio == 1.0
    assert metric.evidence_coverage_ratio == 1.0
    assert metric.validation_summary == {"verified": 1}
    assert metric.note == "执行完成度，非质量评分"
    # No subjective quality/depth score is fabricated.
    assert not any(
        key in metric.model_dump()
        for key in ("quality", "depth", "professionalism", "score", "rating")
    )


def test_completeness_reflects_failed_and_blocked_steps() -> None:
    plan = _plan(
        ("research_1", "research"),
        ("risk_1", "risk"),
        ("report_1", "report"),
    )
    results = {
        "research_1": ExpertResult(
            task_id="research_1",
            agent="research",
            status="completed",
            summary="ok",
        ),
        "risk_1": ExpertResult(
            task_id="risk_1",
            agent="risk",
            status="failed",
            summary="",
            error="boom",
        ),
        "report_1": ExpertResult(
            task_id="report_1",
            agent="report",
            status="blocked",
            summary="",
            error="dependency failed",
        ),
    }

    metric = build_completeness(plan, results)

    assert metric.planned_steps == 3
    assert metric.completed_steps == 1
    assert metric.failed_steps == 1
    assert metric.blocked_steps == 1
    assert metric.completion_ratio == round(1 / 3, 4)
    assert metric.evidence_coverage_ratio == round(1 / 3, 4)


def test_build_report_record_titles_from_goal() -> None:
    plan = _plan(("research_1", "research"))
    results = {
        "research_1": ExpertResult(
            task_id="research_1",
            agent="research",
            status="completed",
            summary="ok",
        )
    }
    aggregation = _minimal_aggregation()

    record = build_report_record("task-1", plan, aggregation, results)

    assert record["task_id"] == "task-1"
    assert record["title"] == "分析并成文"
    assert record["completeness"]["completion_ratio"] == 1.0
    assert record["aggregation"]["user_goal"] == "分析并成文"


def _minimal_aggregation():
    from backend.core.contracts import AggregationResult, DirectAnswer, ResultBlock

    return AggregationResult(
        user_goal="分析并成文",
        completion_status="completed",
        output_mode="data_analysis",
        direct_answer=DirectAnswer(
            headline="标题",
            explanation="说明",
            confidence="medium",
            stance="neutral",
        ),
        content_blocks=[
            ResultBlock(
                id="b1",
                type="narrative",
                title="叙述",
                importance="primary",
                data={"text": "内容"},
            )
        ],
    )
