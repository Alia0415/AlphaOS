from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from backend.services.pandadata_client import PandaDataClient


class FakePandaSDK:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_macro_detail(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("get_macro_detail", kwargs))
        return [{"symbol": "CI0000001", "name": "制造业PMI"}]

    def get_macro_ci(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("get_macro_ci", kwargs))
        return [
            {
                "symbol": "CI0000001",
                "period_date": "20260630",
                "data_value": 50.4,
            }
        ]


def test_pandadata_macro_catalog_uses_reviewed_detail_endpoint() -> None:
    sdk = FakePandaSDK()
    client = PandaDataClient()

    with patch.object(client, "_authenticate", return_value=sdk):
        result = client.get_macro_catalog(
            categories=["CI", "MB"],
            fields=["symbol", "name", "api_name"],
        )

    assert result == [{"symbol": "CI0000001", "name": "制造业PMI"}]
    assert sdk.calls == [
        (
            "get_macro_detail",
            {
                "category": ["CI", "MB"],
                "fields": ["symbol", "name", "api_name"],
            },
        )
    ]


def test_pandadata_macro_data_dispatches_only_allowlisted_api() -> None:
    sdk = FakePandaSDK()
    client = PandaDataClient()

    with patch.object(client, "_authenticate", return_value=sdk):
        result = client.get_macro_data(
            api_name="get_macro_ci",
            symbols=["CI0000001"],
            start_date="20240723",
            end_date="20260723",
            fields=["symbol", "period_date", "data_value"],
        )

    assert result[0]["data_value"] == 50.4
    assert sdk.calls == [
        (
            "get_macro_ci",
            {
                "symbol": ["CI0000001"],
                "start_date": "20240723",
                "end_date": "20260723",
                "fields": ["symbol", "period_date", "data_value"],
            },
        )
    ]


def test_pandadata_macro_data_rejects_unknown_api_before_authentication() -> None:
    client = PandaDataClient()

    with (
        patch.object(
            client,
            "_authenticate",
            side_effect=AssertionError("must not authenticate"),
        ),
        pytest.raises(ValueError, match="not allowlisted"),
    ):
        client.get_macro_data(
            api_name="delete_everything",
            symbols=["CI0000001"],
            start_date="20240723",
            end_date="20260723",
            fields=[],
        )


import json
from datetime import date

from backend.agents.macro_agent import MacroAgent
from backend.core.contracts import AgentId, ExpertTask


class MockArk:
    def __init__(self, *responses: dict[str, Any] | str) -> None:
        self.responses = [
            response if isinstance(response, str) else json.dumps(response)
            for response in responses
        ]
        self.prompts: list[str] = []

    def chat(self, prompt: str, model: str | None = None) -> str:
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("Unexpected Ark call")
        return self.responses.pop(0)


class MockMacroData:
    def __init__(self) -> None:
        self.catalog_calls: list[dict[str, Any]] = []
        self.data_calls: list[dict[str, Any]] = []

    def get_macro_catalog(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.catalog_calls.append(kwargs)
        return [
            {
                "symbol": "CI0000001",
                "name": "制造业PMI",
                "en_name": "Manufacturing PMI",
                "frequency": "月",
                "unit": "%",
                "importance": "重要",
                "info_source": "国家统计局",
                "end_date": "20260630",
                "is_update": "1",
                "api_name": "get_macro_ci",
            },
            {
                "symbol": "EP0000001",
                "name": "新能源行业产量",
                "en_name": "New energy output",
                "frequency": "月",
                "unit": "同比%",
                "importance": "比较重要",
                "info_source": "国家统计局",
                "end_date": "20260630",
                "is_update": "1",
                "api_name": "get_macro_ep",
            },
        ]

    def get_macro_data(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.data_calls.append(kwargs)
        symbol = kwargs["symbols"][0]
        return [
            {"symbol": symbol, "period_date": "20260531", "data_value": 100.0},
            {"symbol": symbol, "period_date": "20260630", "data_value": 105.0},
        ]


def macro_task(industry: str = "新能源") -> ExpertTask:
    return ExpertTask(
        task_id="macro_1",
        agent=AgentId.MACRO,
        objective="判断宏观环境支持程度",
        original_user_request=f"分析{industry}未来12个月投资机会",
        inputs={
            "industry": industry,
            "time_range": "未来12个月",
            "research_goal": "判断宏观环境支持程度",
        },
    )


def test_macro_agent_uses_dynamic_pandadata_evidence_and_returns_contract() -> None:
    ark = MockArk(
        {
            "categories": ["CI", "EP"],
            "indicator_search_terms": ["景气", "新能源"],
            "reasoning": ["覆盖经济周期与行业供需"],
        },
        {
            "indicators": [
                {"symbol": "CI0000001", "rationale": "观察经济景气"},
                {"symbol": "EP0000001", "rationale": "观察行业供需"},
            ]
        },
        {
            "conclusion": "宏观环境中性偏积极",
            "economic_cycle": "温和扩张",
            "interest_rate": "数据证据不足",
            "policy_factors": [],
            "liquidity": "数据证据不足",
            "market_environment": "中性偏积极",
            "positive_factors": ["制造业景气及行业产量改善"],
            "risks": ["历史改善趋势可能反转"],
        },
    )
    data = MockMacroData()
    agent = MacroAgent(
        data_client=data,
        ark_client=ark,
        today_provider=lambda: date(2026, 7, 23),
    )

    result = agent.execute(macro_task())

    assert result.status == "completed"
    assert result.agent == AgentId.MACRO
    assert result.summary == "宏观环境中性偏积极"
    assert result.metadata["macro_analysis"]["economic_cycle"] == "温和扩张"
    assert result.metadata["data_plan"]["categories"] == ["CI", "EP"]
    assert {item["symbol"] for item in result.evidence} == {
        "CI0000001",
        "EP0000001",
    }
    assert all(item["latest_value"] == 105.0 for item in result.evidence)
    assert all(item["percentage_change"] == 0.05 for item in result.evidence)
    assert data.catalog_calls[0]["categories"] == ["CI", "EP"]
    assert all(
        call["start_date"] == "20240723"
        and call["end_date"] == "20260723"
        for call in data.data_calls
    )
    assert len(ark.prompts) == 3
    assert result.tool_calls[0]["tool"] == "pandadata_macro_catalog"
    assert result.tool_calls[0]["status"] == "completed"
    assert any(
        call["tool"] == "pandadata_macro_data" for call in result.tool_calls
    )


def valid_analysis() -> dict[str, Any]:
    return {
        "conclusion": "中性",
        "economic_cycle": "平稳",
        "interest_rate": "中性",
        "policy_factors": [],
        "liquidity": "平稳",
        "market_environment": "中性",
        "positive_factors": [],
        "risks": ["数据发布存在滞后"],
    }


def test_macro_rejects_catalog_external_symbol_without_data_call() -> None:
    ark = MockArk(
        {
            "categories": ["CI"],
            "indicator_search_terms": ["景气"],
            "reasoning": ["周期"],
        },
        {
            "indicators": [
                {"symbol": "EVIL0001", "rationale": "not in catalog"}
            ]
        },
        {
            "indicators": [
                {"symbol": "STILL_EVIL", "rationale": "not in catalog"}
            ]
        },
    )
    data = MockMacroData()

    result = MacroAgent(
        data_client=data,
        ark_client=ark,
        today_provider=lambda: date(2026, 7, 23),
    ).execute(macro_task())

    assert result.status == "failed"
    assert data.data_calls == []
    assert len(ark.prompts) == 3


def test_macro_structured_stages_share_one_repair_attempt() -> None:
    ark = MockArk(
        "not-json",
        {
            "categories": ["CI"],
            "indicator_search_terms": ["景气"],
            "reasoning": ["周期"],
        },
        "also-not-json",
    )
    data = MockMacroData()

    result = MacroAgent(
        data_client=data,
        ark_client=ark,
        today_provider=lambda: date(2026, 7, 23),
    ).execute(macro_task())

    assert result.status == "failed"
    assert len(ark.prompts) == 3


def test_macro_fails_instead_of_using_model_only_when_catalog_is_empty() -> None:
    data = MockMacroData()
    data.get_macro_catalog = lambda **kwargs: []
    ark = MockArk(
        {
            "categories": ["CI"],
            "indicator_search_terms": ["景气"],
            "reasoning": ["周期"],
        }
    )

    result = MacroAgent(
        data_client=data,
        ark_client=ark,
        today_provider=lambda: date(2026, 7, 23),
    ).execute(macro_task())

    assert result.status == "failed"
    assert result.data_sources == []
    assert len(ark.prompts) == 1
    assert result.agent == AgentId.MACRO
    assert result.tool_calls[0]["tool"] == "pandadata_macro_catalog"


def test_macro_continues_with_partial_api_failure() -> None:
    class PartialData(MockMacroData):
        def get_macro_data(self, **kwargs: Any) -> list[dict[str, Any]]:
            self.data_calls.append(kwargs)
            if kwargs["api_name"] == "get_macro_ep":
                raise RuntimeError("provider detail must be redacted")
            return [
                {
                    "symbol": "CI0000001",
                    "period_date": "20260531",
                    "data_value": 49.0,
                },
                {
                    "symbol": "CI0000001",
                    "period_date": "20260630",
                    "data_value": 50.0,
                },
            ]

    data = PartialData()
    ark = MockArk(
        {
            "categories": ["CI", "EP"],
            "indicator_search_terms": ["景气", "新能源"],
            "reasoning": ["周期和行业"],
        },
        {
            "indicators": [
                {"symbol": "CI0000001", "rationale": "周期"},
                {"symbol": "EP0000001", "rationale": "行业"},
            ]
        },
        valid_analysis(),
    )

    result = MacroAgent(
        data_client=data,
        ark_client=ark,
        today_provider=lambda: date(2026, 7, 23),
    ).execute(macro_task())

    assert result.status == "completed"
    assert [item["symbol"] for item in result.evidence] == ["CI0000001"]
    assert any("部分" in item for item in result.limitations)
    assert "provider detail" not in result.model_dump_json()


from backend.agents.manager_agent import ManagerAgent
from backend.core.agent_registry import AgentRegistry
from backend.core.contracts import ExecutionPlan
from backend.core.workflow_executor import WorkflowExecutor, _default_handlers


def plan_payload(agent: str, inputs: dict[str, Any]) -> dict[str, Any]:
    return {
        "goal": "动态任务",
        "intent": "按任务选择专家",
        "complexity": "low",
        "selected_agents": [{"agent": agent, "reason": "最小充分专家"}],
        "steps": [
            {
                "id": f"{agent}_1",
                "agent": agent,
                "objective": "完成专家分析",
                "inputs": inputs,
                "depends_on": [],
                "expected_output": "结构化专家结果",
            }
        ],
        "needs_clarification": False,
        "clarification_question": None,
    }


def test_registry_exposes_enabled_macro_but_keeps_portfolio_disabled() -> None:
    registry = AgentRegistry()
    ids = {item["id"] for item in registry.prompt_payload()}

    assert "macro" in ids
    assert "portfolio" not in ids
    assert registry.is_enabled(AgentId.MACRO)


def test_manager_accepts_macro_and_quant_only_dynamic_plans() -> None:
    macro_manager = ManagerAgent(
        client=MockArk(
            plan_payload(
                "macro",
                {
                    "industry": "新能源",
                    "time_range": "未来12个月",
                    "research_goal": "判断宏观支持程度",
                },
            )
        )
    )
    quant_manager = ManagerAgent(
        client=MockArk(
            plan_payload(
                "quant",
                {
                    "symbols": ["000001.SZ"],
                    "start_date": "20240101",
                    "end_date": "20241231",
                },
            )
        )
    )

    assert macro_manager.create_plan("分析新能源宏观环境").steps[0].agent == AgentId.MACRO
    quant_plan = quant_manager.create_plan("分析某股票历史收益")
    assert [step.agent for step in quant_plan.steps] == [AgentId.QUANT]
    prompt = quant_manager._planning_prompt("历史收益")
    assert '"id": "macro"' in prompt
    assert "不得自动追加 macro" in prompt


def test_default_executor_registers_real_macro_agent() -> None:
    handlers = _default_handlers()

    assert isinstance(handlers[AgentId.MACRO], MacroAgent)


def test_semiconductor_macro_result_has_complete_json_structure() -> None:
    data = MockMacroData()
    ark = MockArk(
        {
            "categories": ["CI", "ED"],
            "indicator_search_terms": ["景气", "电子"],
            "reasoning": ["周期与半导体行业"],
        },
        {
            "indicators": [
                {"symbol": "CI0000001", "rationale": "周期"}
            ]
        },
        valid_analysis(),
    )

    result = MacroAgent(
        data_client=data,
        ark_client=ark,
        today_provider=lambda: date(2026, 7, 23),
    ).execute(macro_task("半导体"))

    assert set(result.metadata["macro_analysis"]) == {
        "conclusion",
        "economic_cycle",
        "interest_rate",
        "policy_factors",
        "liquidity",
        "market_environment",
        "positive_factors",
        "risks",
    }


def test_macro_prompt_prohibits_price_forecasts_and_trade_advice() -> None:
    prompt = (
        Path("backend/prompts/macro.md")
        .read_text(encoding="utf-8")
    )

    assert "不要预测股票价格" in prompt
    assert "不要输出具体买卖建议" in prompt
    assert "PandaData" in prompt
