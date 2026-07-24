from __future__ import annotations

import pytest

from backend import main as main_module
from backend.core.agent_registry import AgentRegistry
from backend.core.contracts import ExecutionPlan
from backend.core.personal_decision_context import PersonalDecisionContextBuilder
from backend.core.plan_validator import PlanValidationError, validate_execution_plan
from backend.core.task_spec import TaskSpec
from backend.core.user_profile import UserInvestmentProfile


def _spec() -> TaskSpec:
    return TaskSpec(
        task_type="personal_investment_decision",
        subject_type="personal_finance",
        research_goal="我能否承受这个产品的历史波动？",
        expected_result_type="direct_answer",
        evidence_requirements=["个人约束"],
        execution_decision="execute_with_defaults",
    )


def _profile() -> UserInvestmentProfile:
    return UserInvestmentProfile(
        investment_horizon_months=60,
        liquidity_need="low",
        emergency_fund_cny=98_765,
        monthly_essential_expenses_cny=8_765,
        monthly_debt_payment_cny=1_234,
        max_acceptable_loss_ratio=0.25,
        onboarding_completed=True,
    )


@pytest.mark.parametrize("agent", ["research", "quant", "macro"])
def test_non_risk_agents_reject_private_profile_fields(agent: str) -> None:
    inputs = {"monthly_after_tax_income_cny": 12_345}
    if agent == "research":
        inputs.update(
            symbols=["000001.SZ"],
            start_date="20240101",
            end_date="20241231",
            fields=[],
        )
    plan = ExecutionPlan.model_validate(
        {
            "goal": "测试隐私边界",
            "intent": "privacy",
            "complexity": "low",
            "selected_agents": [{"agent": agent, "reason": "测试"}],
            "steps": [
                {
                    "id": f"{agent}_1",
                    "agent": agent,
                    "objective": "执行研究",
                    "inputs": inputs,
                    "depends_on": [],
                    "expected_output": "结果",
                }
            ],
        }
    )

    with pytest.raises(PlanValidationError):
        validate_execution_plan(plan, AgentRegistry())


def test_context_is_only_attached_to_risk_and_contains_no_raw_values() -> None:
    context = PersonalDecisionContextBuilder().build(_spec(), _profile())
    assert context is not None
    plan = ExecutionPlan.model_validate(
        {
            "goal": "研究产品波动和个人约束",
            "intent": "personal",
            "task_type": "personal_investment_decision",
            "complexity": "medium",
            "selected_agents": [
                {"agent": "research", "reason": "历史波动"},
                {"agent": "macro", "reason": "市场环境"},
                {"agent": "risk", "reason": "解释个人约束"},
            ],
            "steps": [
                {
                    "id": "research_1",
                    "agent": "research",
                    "objective": "历史波动",
                    "inputs": {
                        "symbols": ["000001.SZ"],
                        "start_date": "20240101",
                        "end_date": "20241231",
                        "fields": [],
                    },
                    "depends_on": [],
                    "expected_output": "市场事实",
                },
                {
                    "id": "macro_1",
                    "agent": "macro",
                    "objective": "市场环境",
                    "inputs": {"research_goal": "市场环境"},
                    "depends_on": [],
                    "expected_output": "宏观事实",
                },
                {
                    "id": "risk_1",
                    "agent": "risk",
                    "objective": "个人约束",
                    "inputs": {"risk_mode": "personal_capacity"},
                    "depends_on": [],
                    "expected_output": "约束解释",
                },
            ],
        }
    )
    attached = main_module._attach_personal_context(plan, context)

    assert "risk_context" not in attached.steps[0].inputs
    assert "risk_context" not in attached.steps[1].inputs
    assert attached.steps[2].inputs["risk_mode"] == "personal_capacity"
    serialized = attached.model_dump_json()
    for raw_value in ("98765", "8765", "1234"):
        assert raw_value not in serialized
    assert attached.personal_context.privacy_boundary.shared_with_research == []
    assert attached.personal_context.privacy_boundary.shared_with_quant == []
    assert attached.personal_context.privacy_boundary.shared_with_macro == []


def test_personal_risk_step_requires_explicit_personal_capacity_mode() -> None:
    plan = ExecutionPlan.model_validate(
        {
            "goal": "个人承受能力研究",
            "intent": "personal",
            "task_type": "personal_investment_decision",
            "complexity": "low",
            "selected_agents": [{"agent": "risk", "reason": "解释约束"}],
            "steps": [
                {
                    "id": "risk_1",
                    "agent": "risk",
                    "objective": "解释个人约束",
                    "inputs": {"risk_context": {}},
                    "depends_on": [],
                    "expected_output": "约束解释",
                }
            ],
        }
    )

    with pytest.raises(PlanValidationError, match="personal_capacity"):
        validate_execution_plan(plan, AgentRegistry())
