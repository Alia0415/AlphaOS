from __future__ import annotations

import re
from typing import Any

import pytest

from backend.agents.research_agent import ResearchAgent
from backend.core.agent_registry import AgentRegistry
from backend.core.contracts import AgentId, ExecutionPlan, ExpertResult, ExpertTask
from backend.core.plan_validator import (
    PlanValidationError,
    validate_execution_plan,
)
from backend.core.workflow_executor import WorkflowExecutor


class MockArk:
    def __init__(
        self,
        response: str = "已形成不含未经验证数值的定性行业研究框架。",
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.prompts: list[str] = []

    def chat(self, prompt: str, model: str | None = None) -> str:
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return self.response


class MarketDataMustNotBeCalled:
    def __init__(self) -> None:
        self.calls = 0

    def get_market_data(self, **kwargs: Any) -> Any:
        self.calls += 1
        raise AssertionError("industry research must not request market data")


def _industry_inputs(**overrides: Any) -> dict[str, Any]:
    inputs = {
        "industry": "新能源",
        "time_range": "未来一年",
        "research_goal": "判断行业投资机会",
    }
    inputs.update(overrides)
    return inputs


def _research_plan(inputs: dict[str, Any]) -> ExecutionPlan:
    return ExecutionPlan.model_validate(
        {
            "goal": "研究新能源行业",
            "intent": "行业研究",
            "complexity": "medium",
            "selected_agents": [
                {"agent": "research", "reason": "需要行业研究"}
            ],
            "steps": [
                {
                    "id": "research_1",
                    "agent": "research",
                    "objective": "分析新能源行业机会",
                    "inputs": inputs,
                    "depends_on": [],
                    "expected_output": "结构化行业研究框架",
                }
            ],
        }
    )


def _industry_task(inputs: dict[str, Any] | None = None) -> ExpertTask:
    return ExpertTask(
        task_id="research_1",
        agent=AgentId.RESEARCH,
        objective="分析新能源行业基本面和行业财务风险",
        original_user_request="研究未来一年新能源行业的投资机会",
        inputs=inputs or _industry_inputs(focus="产业链竞争格局"),
    )


def test_registry_exposes_industry_research_inputs() -> None:
    accepted = set(AgentRegistry().get(AgentId.RESEARCH).accepted_inputs)

    assert {"industry", "time_range", "research_goal", "focus"}.issubset(
        accepted
    )
    assert {
        "symbol",
        "symbols",
        "start_date",
        "end_date",
        "fields",
        "scope",
    }.issubset(accepted)


def test_validator_accepts_industry_research() -> None:
    plan = _research_plan(_industry_inputs())

    assert validate_execution_plan(plan, AgentRegistry()) is plan


@pytest.mark.parametrize(
    ("inputs", "message"),
    [
        (_industry_inputs(industry=""), "non-empty industry"),
        (_industry_inputs(industry=123), "non-empty industry"),
        (_industry_inputs(symbols=["000001.SZ"]), "cannot include symbol"),
        (_industry_inputs(scope="financials"), "cannot include dossier scope"),
        (_industry_inputs(time_range=123), "time_range"),
        (_industry_inputs(research_goal=123), "research_goal"),
        (_industry_inputs(focus=""), "focus"),
    ],
)
def test_validator_rejects_invalid_industry_research(
    inputs: dict[str, Any],
    message: str,
) -> None:
    plan = _research_plan(inputs)

    with pytest.raises(PlanValidationError, match=message):
        validate_execution_plan(plan, AgentRegistry())


def test_macro_and_research_parallel_dag_validates_and_executes_exactly() -> None:
    plan = ExecutionPlan.model_validate(
        {
            "goal": "分析新能源行业未来一年的机会",
            "intent": "并行获取宏观与行业研究证据",
            "complexity": "high",
            "selected_agents": [
                {"agent": "macro", "reason": "需要宏观与政策环境"},
                {"agent": "research", "reason": "需要行业研究框架"},
            ],
            "steps": [
                {
                    "id": "macro_1",
                    "agent": "macro",
                    "objective": "分析宏观、政策、周期和流动性环境",
                    "inputs": _industry_inputs(),
                    "depends_on": [],
                    "expected_output": "宏观环境证据",
                },
                {
                    "id": "research_1",
                    "agent": "research",
                    "objective": "分析行业需求、产业链和竞争格局",
                    "inputs": _industry_inputs(),
                    "depends_on": [],
                    "expected_output": "行业研究框架",
                },
            ],
        }
    )
    validated = validate_execution_plan(plan, AgentRegistry())

    def macro_handler(task: ExpertTask) -> ExpertResult:
        return ExpertResult(
            task_id=task.task_id,
            agent=task.agent,
            status="completed",
            summary="宏观分析完成。",
        )

    market_data = MarketDataMustNotBeCalled()
    research = ResearchAgent(
        data_client=market_data,
        ark_client=MockArk(),
    )
    events, results = WorkflowExecutor(
        handlers={
            AgentId.MACRO: macro_handler,
            AgentId.RESEARCH: research.execute,
        }
    ).execute(validated, "分析新能源行业未来一年的机会")

    assert {item.agent for item in plan.selected_agents} == {
        step.agent for step in plan.steps
    }
    assert all(step.depends_on == [] for step in plan.steps)
    assert list(results) == ["macro_1", "research_1"]
    assert all(result.status == "completed" for result in results.values())
    assert [(event.step_id, event.type) for event in events[:2]] == [
        ("macro_1", "step_started"),
        ("research_1", "step_started"),
    ]
    assert {result.agent for result in results.values()} == {
        AgentId.MACRO,
        AgentId.RESEARCH,
    }
    assert market_data.calls == 0


def test_industry_research_uses_ark_without_market_data() -> None:
    market_data = MarketDataMustNotBeCalled()
    ark = MockArk("已完成定性行业框架，所有结论仍需外部证据验证。")

    result = ResearchAgent(
        data_client=market_data,
        ark_client=ark,
    ).execute(_industry_task())

    assert result.status == "completed"
    assert result.summary == "已完成定性行业框架，所有结论仍需外部证据验证。"
    assert result.evidence[0]["type"] == "industry_research_framework"
    assert result.evidence[0]["industry"] == "新能源"
    assert result.evidence[0]["time_range"] == "未来一年"
    assert result.evidence[0]["research_goal"] == "判断行业投资机会"
    assert result.evidence[0]["focus"] == "产业链竞争格局"
    assert result.metadata["mode"] == "industry_research"
    assert result.metadata["original_user_request"] == (
        "研究未来一年新能源行业的投资机会"
    )
    assert result.metadata["ark_fallback_used"] is False
    assert market_data.calls == 0
    assert len(ark.prompts) == 1
    assert "original_user_request" in ark.prompts[0]
    assert "不得给出具体增长率" in ark.prompts[0]


def test_industry_research_falls_back_safely_when_ark_fails() -> None:
    market_data = MarketDataMustNotBeCalled()
    result = ResearchAgent(
        data_client=market_data,
        ark_client=MockArk(error=RuntimeError("offline")),
    ).execute(_industry_task())

    assert result.status == "completed"
    assert result.metadata["analysis_source"] == "deterministic_framework"
    assert result.metadata["ark_fallback_used"] is True
    assert result.evidence[0]["dimensions"] == [
        "需求与增长驱动",
        "产业链与竞争格局",
        "政策与监管",
        "技术与成本变化",
        "估值与市场预期",
        "主要风险",
    ]
    assert any("未接入独立行业基本面数据库" in item for item in result.limitations)
    assert any("不能替代实时数据" in item for item in result.limitations)
    assert any("Macro Agent" in item for item in result.limitations)
    assert any("未生成具体增长率" in item for item in result.limitations)
    assert re.search(r"\d", result.summary) is None
    assert market_data.calls == 0


def test_market_and_dossier_validation_remain_strict() -> None:
    missing_dates = _research_plan({"symbols": ["000001.SZ"], "fields": []})
    invalid_symbol = _research_plan(
        {
            "symbols": ["NOT-A-SYMBOL"],
            "start_date": "20240101",
            "end_date": "20241231",
            "fields": [],
        }
    )
    dossier = _research_plan(
        {
            "symbol": "600519.SH",
            "scope": "financials",
            "period": "2024",
        }
    )

    with pytest.raises(PlanValidationError, match="requires start_date"):
        validate_execution_plan(missing_dates, AgentRegistry())
    with pytest.raises(PlanValidationError, match="invalid A-share symbol"):
        validate_execution_plan(invalid_symbol, AgentRegistry())
    assert validate_execution_plan(dossier, AgentRegistry()) is dossier
