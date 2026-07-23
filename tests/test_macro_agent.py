from __future__ import annotations

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
