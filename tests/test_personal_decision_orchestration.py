from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import main as main_module
from backend.core.contracts import AgentId, ExecutionPlan, ExpertResult
from backend.core.evidence_validator import EvidenceValidator
from backend.core.personal_decision_context import PersonalDecisionContextBuilder
from backend.core.result_aggregator import ResultAggregator
from backend.core.task_spec import TaskSpec
from backend.core.user_profile import UserInvestmentProfile


def _spec() -> TaskSpec:
    return TaskSpec(
        task_type="personal_investment_decision",
        subject_type="personal_finance",
        research_goal="我能否承受这个产品的历史波动？",
        expected_result_type="direct_answer",
        evidence_requirements=["历史波动", "个人现实约束"],
        execution_decision="execute_with_defaults",
    )


def _context():
    profile = UserInvestmentProfile(
        investment_horizon_months=60,
        liquidity_need="low",
        emergency_fund_cny=20_000,
        monthly_essential_expenses_cny=8_000,
        monthly_debt_payment_cny=2_000,
        max_acceptable_loss_ratio=0.25,
        onboarding_completed=True,
    )
    return PersonalDecisionContextBuilder().build(_spec(), profile)


def test_personal_constraints_reach_aggregation_without_risk_agent() -> None:
    context = _context()
    assert context is not None
    plan = ExecutionPlan.model_validate(
        {
            "goal": "研究产品历史波动与个人承受边界",
            "intent": "personal research",
            "task_type": "personal_investment_decision",
            "expected_result_type": "direct_answer",
            "complexity": "low",
            "selected_agents": [
                {"agent": "research", "reason": "获取历史波动事实"}
            ],
            "steps": [
                {
                    "id": "research_1",
                    "agent": "research",
                    "objective": "分析历史波动",
                    "inputs": {
                        "symbols": ["000001.SZ"],
                        "start_date": "20240101",
                        "end_date": "20241231",
                        "fields": [],
                    },
                    "depends_on": [],
                    "expected_output": "历史波动事实",
                }
            ],
            "personal_context": context.model_dump(mode="json"),
        }
    )
    results = {
        "research_1": ExpertResult(
            task_id="research_1",
            agent=AgentId.RESEARCH,
            status="completed",
            summary="历史波动分析完成。",
            evidence=[
                {
                    "type": "market_metrics",
                    "daily_volatility": 0.03,
                    "maximum_drawdown": -0.18,
                }
            ],
            data_sources=[{"name": "mock-market-data"}],
            metadata={"validation_status": "historically_analyzed"},
        )
    }

    evidence = EvidenceValidator().validate(_spec(), plan, results)
    aggregation = ResultAggregator().aggregate(_spec(), plan, evidence)
    block = next(
        item
        for item in aggregation.content_blocks
        if item.type == "personal_constraints"
    )

    assert [agent.value for agent in aggregation.execution_summary.selected_agents] == [
        "research"
    ]
    assert block.data["fields_used"]
    assert any(
        item["code"] == "emergency_fund_low"
        for item in block.data["constraints"]
    )
    assert block.data["privacy_boundary"]["shared_with_research"] == []
    assert block.data["evidence_origin"] == "core.personal_constraint_evaluator"


def test_non_personal_plan_has_no_personal_constraint_evidence() -> None:
    spec = TaskSpec(
        task_type="market_research",
        subject_type="market",
        research_goal="分析市场",
        expected_result_type="direct_answer",
        execution_decision="execute",
    )
    plan = ExecutionPlan(
        goal="分析市场",
        intent="market",
        complexity="low",
    )
    evidence = EvidenceValidator().validate(spec, plan, {})
    aggregation = ResultAggregator().aggregate(spec, plan, evidence)

    assert evidence.personal_constraints is None
    assert all(
        block.type != "personal_constraints"
        for block in aggregation.content_blocks
    )


class RecordingManager:
    def __init__(self) -> None:
        self.calls = []

    def create_plan(self, task_spec, prompt, profile_context=None):
        self.calls.append((task_spec, prompt, profile_context))
        return ExecutionPlan(
            goal=task_spec.research_goal,
            intent="重新治理后的个人研究",
            task_type=task_spec.task_type,
            expected_result_type=task_spec.expected_result_type,
            complexity="low",
        )


def test_profile_clarification_resume_rechecks_complete_governance_chain() -> None:
    client = TestClient(main_module.app)
    created = client.post(
        "/api/tasks/sessions",
        json={"prompt": "我有10万元，想投资新能源，应该怎么安排？"},
    )
    task_id = created.json()["task_id"]
    assert created.json()["action_required"] == "profile_onboarding_required"

    profile_response = client.put(
        "/api/user-profile",
        json={
            "investment_horizon_months": 60,
            "liquidity_need": "medium",
            "emergency_fund_cny": 60_000,
            "monthly_essential_expenses_cny": 8_000,
            "monthly_debt_payment_cny": 2_000,
            "max_acceptable_loss_ratio": 0.2,
            "onboarding_completed": True,
        },
    )
    assert profile_response.status_code == 200
    recording_manager = RecordingManager()

    with (
        patch.object(
            main_module.policy_gate,
            "evaluate",
            wraps=main_module.policy_gate.evaluate,
        ) as gate,
        patch.object(
            main_module.task_interpreter,
            "interpret",
            wraps=main_module.task_interpreter.interpret,
        ) as interpreter,
        patch.object(
            main_module.personal_context_builder,
            "build",
            wraps=main_module.personal_context_builder.build,
        ) as context_builder,
        patch.object(main_module, "manager", recording_manager),
    ):
        resumed = client.post(
            f"/api/tasks/{task_id}/clarify",
            json={"answers": {"goal_scope": "只做研究边界分析"}},
        )

    assert resumed.status_code == 200
    assert resumed.json()["plan"]["needs_clarification"] is False
    assert gate.call_count == 1
    assert interpreter.call_count == 1
    assert context_builder.call_count == 1
    assert len(recording_manager.calls) == 1
    _, resumed_prompt, summary = recording_manager.calls[0]
    assert "用户澄清" in resumed_prompt
    assert summary["status"] == "evaluated"
    detail = client.get(f"/api/tasks/{task_id}").json()
    assert detail["status"] == "planned"
    assert detail["plan"]["personal_context"]["constraints"]["status"] == "evaluated"
