from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend import main as main_module
from backend.core.contracts import (
    AgentId,
    ExecutionPlan,
    ExpertResult,
    ValidationStatus,
)
from backend.core.evidence_validator import EvidenceValidator
from backend.core.policy_gate import PolicyGate
from backend.core.result_aggregator import ResultAggregator
from backend.core.result_policy_checker import ResultPolicyChecker
from backend.core.task_interpreter import TaskInterpreter


gate = PolicyGate()
interpreter = TaskInterpreter()


@pytest.mark.parametrize(
    ("prompt", "decision", "allowed"),
    [
        ("今天天气怎么样？", "out_of_domain", False),
        ("高温天气会影响哪些行业？", "allowed_research", True),
        ("建议买入三只股票。", "personalized_recommendation", False),
        ("替我自动下单买入 000001.SZ。", "trading_execution", False),
        ("推荐三只明天一定上涨的股票。", "guaranteed_return", False),
        ("分析贵州茅台最近三年的财务表现。", "allowed_research", True),
        ("计算 R020 因子在 2024 年的历史值。", "allowed_research", True),
        ("对一个量化策略做风险分析。", "allowed_research", True),
    ],
)
def test_policy_gate_is_deterministic(
    prompt: str,
    decision: str,
    allowed: bool,
) -> None:
    result = gate.evaluate(prompt)

    assert result.decision == decision
    assert result.allowed is allowed


def test_task_interpreter_recognizes_company_factor_and_risk_tasks() -> None:
    policy = gate.evaluate("分析贵州茅台最近三年的财务表现和主要风险。")
    company = interpreter.interpret(
        "分析贵州茅台最近三年的财务表现和主要风险。",
        policy,
    )
    factor = interpreter.interpret(
        "计算 000001.SZ、000002.SZ 在 2024 年的 R020。",
        gate.evaluate("计算 000001.SZ、000002.SZ 在 2024 年的 R020。"),
    )
    risk = interpreter.interpret(
        "对高换手成交量策略做风险分析。",
        gate.evaluate("对高换手成交量策略做风险分析。"),
    )

    assert company.task_type == "company_research"
    assert company.subjects == ["贵州茅台"]
    assert company.time_range_description == "最近三年"
    assert factor.task_type == "factor_research"
    assert factor.subjects == ["R020", "000001.SZ", "000002.SZ"]
    assert factor.start_date == "20240101"
    assert factor.end_date == "20241231"
    assert risk.task_type == "risk_review"
    assert "agent" not in type(company).model_fields
    assert "skill" not in type(company).model_fields


def test_task_interpreter_clarifies_missing_identifiers_and_dates() -> None:
    stock = interpreter.interpret(
        "分析这只股票的财务表现。",
        gate.evaluate("分析这只股票的财务表现。"),
    )
    factor = interpreter.interpret(
        "帮我计算 R020。",
        gate.evaluate("帮我计算 R020。"),
    )

    assert stock.execution_decision == "clarify"
    assert stock.missing_fields == ["company_or_stock_code"]
    assert factor.execution_decision == "clarify"
    assert {"subjects", "date_range"} <= set(factor.missing_fields)
    assert not factor.start_date and not factor.end_date


def test_task_interpreter_recognizes_personal_decision_and_clarifies_constraints() -> None:
    prompt = "我有10万元，想投资新能源，应该怎么安排？"
    task = interpreter.interpret(prompt, gate.evaluate(prompt))

    assert task.task_type == "personal_investment_decision"
    assert task.subject_type == "personal_finance"
    assert task.execution_decision == "clarify"
    assert {
        "investment_horizon",
        "emergency_fund",
        "income_and_expenses",
        "loss_tolerance",
    } <= set(task.missing_fields)
    assert "不会直接给出配置方案" in (task.clarification_question or "")


def test_task_interpreter_keeps_stock_price_performance_as_market_research() -> None:
    prompt = "分析000001.SZ过去一年的股价表现"
    task = interpreter.interpret(prompt, gate.evaluate(prompt))

    assert task.task_type == "market_research"
    assert task.subject_type == "market"
    assert task.subjects == ["000001.SZ"]
    assert task.execution_decision != "clarify"


def test_task_interpreter_keeps_industry_opportunity_as_industry_research() -> None:
    prompt = "分析新能源行业未来一年的投资机会"
    task = interpreter.interpret(prompt, gate.evaluate(prompt))

    assert task.task_type == "market_research"
    assert task.subject_type == "industry"
    assert task.subjects == ["新能源行业"]
    assert task.time_range_description == "未来一年"
    assert task.execution_decision != "clarify"


def _factor_spec():
    prompt = "计算 000001.SZ、000002.SZ 在 2024 年的 R020，并检查失效风险。"
    return interpreter.interpret(prompt, gate.evaluate(prompt))


def _factor_plan() -> ExecutionPlan:
    return ExecutionPlan.model_validate(
        {
            "goal": "计算 R020 并检查风险",
            "intent": "factor_research",
            "task_type": "factor_research",
            "expected_result_type": "factor_research",
            "task_summary": "计算并检查风险",
            "complexity": "medium",
            "selected_agents": [
                {"agent": "quant", "reason": "计算因子"},
                {"agent": "risk", "reason": "检查失效风险"},
            ],
            "steps": [
                {
                    "id": "quant_1",
                    "agent": "quant",
                    "objective": "计算 R020",
                    "inputs": {},
                    "depends_on": [],
                    "expected_output": "因子结果",
                },
                {
                    "id": "risk_1",
                    "agent": "risk",
                    "objective": "检查风险",
                    "inputs": {},
                    "depends_on": ["quant_1"],
                    "expected_output": "风险结果",
                },
            ],
        }
    )


def _factor_result() -> ExpertResult:
    return ExpertResult(
        task_id="quant_1",
        agent=AgentId.QUANT,
        status="completed",
        summary="R020 已完成公式计算。",
        evidence=[
            {
                "validation_status": "computed_not_validated",
                "data": {
                    "factor_id": "R020",
                    "observation_count": 100,
                    "coverage_ratio": 0.9,
                },
            }
        ],
        assumptions=["OHLCV 口径一致。"],
        risks=["市场状态变化可能使历史关系失效。"],
        limitations=["未完成 IC 和样本外检验。"],
        data_sources=[
            {
                "name": "PandaData",
                "symbols": ["000001.SZ", "000002.SZ"],
                "start_date": "20240101",
                "end_date": "20241231",
            }
        ],
        metadata={"validation_status": "computed_not_validated"},
    )


def test_evidence_validator_preserves_unvalidated_status_and_detects_gaps() -> None:
    spec = _factor_spec()
    plan = _factor_plan()
    validation = EvidenceValidator().validate(
        spec,
        plan,
        {"quant_1": _factor_result()},
    )

    assert validation.overall_validation_status == ValidationStatus.COMPUTED_NOT_VALIDATED
    assert any("risk_1" in item for item in validation.missing_evidence)
    assert validation.assumptions[0].text == "OHLCV 口径一致。"
    assert validation.risks
    assert validation.limitations
    assert validation.data_scope


def test_evidence_validator_rejects_false_upstream_reference() -> None:
    spec = _factor_spec()
    plan = _factor_plan()
    risk = ExpertResult(
        task_id="risk_1",
        agent=AgentId.RISK,
        status="completed",
        summary="风险审查完成。",
        evidence=[{"source_step": "missing_quant"}],
    )
    validation = EvidenceValidator().validate(
        spec,
        plan,
        {"quant_1": _factor_result(), "risk_1": risk},
    )

    assert any("不存在的上游步骤" in item for item in validation.conflicts)


def test_new_aggregator_uses_task_skeleton_and_separates_three_boundaries() -> None:
    spec = _factor_spec()
    plan = _factor_plan().model_copy(
        update={
            "steps": [_factor_plan().steps[0]],
            "selected_agents": [_factor_plan().selected_agents[0]],
        }
    )
    validation = EvidenceValidator().validate(
        spec,
        plan,
        {"quant_1": _factor_result()},
    )
    aggregation = ResultAggregator().aggregate(spec, plan, validation)
    types = [block.type for block in aggregation.content_blocks]

    assert types[:2] == ["task_understanding", "validation_summary"]
    assert {"risk_list", "assumption_list", "limitations"} <= set(types)
    assert aggregation.validation.status == ValidationStatus.COMPUTED_NOT_VALIDATED
    assert "尚不能证明" in aggregation.direct_answer.explanation
    assert "不代表推荐" in " ".join(aggregation.validation.unsupported_claims)


def test_result_policy_checker_rewrites_recommendation_and_unbacked_return() -> None:
    spec = _factor_spec()
    plan = _factor_plan().model_copy(
        update={
            "steps": [_factor_plan().steps[0]],
            "selected_agents": [_factor_plan().selected_agents[0]],
        }
    )
    unsafe = _factor_result().model_copy(
        update={
            "summary": "建议买入因子排名前十的股票，预计收益为 12%。",
        }
    )
    validation = EvidenceValidator().validate(spec, plan, {"quant_1": unsafe})
    aggregation = ResultAggregator().aggregate(spec, plan, validation)
    checked = ResultPolicyChecker().check(aggregation)
    serialized = checked.model_dump_json()

    assert "建议买入" not in serialized
    assert "预计收益为 12%" not in serialized
    assert checked.metadata["policy_rewrite"] is True
    assert "未完成可支持该收益数值的真实历史测试" in serialized


def test_boundary_api_does_not_call_manager_or_experts() -> None:
    with patch.object(
        main_module.manager,
        "create_plan",
        side_effect=AssertionError("Manager must not be called"),
    ):
        response = TestClient(main_module.app).post(
            "/api/tasks",
            json={"prompt": "今天天气怎么样？"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["plan"] is None
    assert body["results"] == {}
    assert body["aggregation"]["result_type"] == "boundary_response"
    assert body["aggregation"]["completion_status"] == "rejected"
    assert all(event["type"] != "plan_created" for event in body["events"])


def test_personal_decision_api_clarifies_without_manager_or_experts() -> None:
    with patch.object(
        main_module.manager,
        "create_plan",
        side_effect=AssertionError("Manager must not plan before clarification"),
    ):
        response = TestClient(main_module.app).post(
            "/api/tasks",
            json={"prompt": "我有10万元，想投资新能源，应该怎么安排？"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["plan"] is None
    assert body["results"] == {}
    assert body["aggregation"]["result_type"] == "clarification"
    assert body["aggregation"]["completion_status"] == "needs_clarification"
    assert "投资期限" in body["final_answer"]
    assert all(event["type"] != "plan_created" for event in body["events"])
