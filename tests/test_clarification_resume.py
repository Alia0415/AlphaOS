"""needs_clarification returns structured options; clarify folds answers and re-plans."""

from __future__ import annotations

import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import main as main_module
from backend.agents.manager_agent import ManagerAgent


class MockArkClient:
    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def chat(self, prompt: str, model: str | None = None) -> str:
        self.prompts.append(prompt)
        return self.responses.pop(0)


def _clarification_payload() -> dict:
    return {
        "goal": "为用户构建投资组合",
        "intent": "按用户目标执行",
        "complexity": "medium",
        "selected_agents": [],
        "steps": [],
        "needs_clarification": True,
        "clarification_question": "请补充投资周期与风险偏好。",
        "clarification_options": [
            {
                "key": "horizon",
                "title": "投资周期",
                "hint": "预期持有时间",
                "multi": False,
                "items": ["短期", "中期", "长期"],
                "default": "中期",
            },
            {
                "key": "risk",
                "title": "风险偏好",
                "multi": False,
                "items": ["保守", "稳健", "激进"],
            },
        ],
    }


def _resolved_payload() -> dict:
    return {
        "goal": "分析 000001.SZ 在 2024 年的价格表现",
        "intent": "按用户目标执行",
        "complexity": "low",
        "selected_agents": [{"agent": "research", "reason": "需要 research"}],
        "steps": [
            {
                "id": "research_1",
                "agent": "research",
                "objective": "research objective",
                "inputs": {
                    "symbols": ["000001.SZ"],
                    "start_date": "20240101",
                    "end_date": "20241231",
                    "fields": [],
                },
                "depends_on": [],
                "expected_output": "research output",
            }
        ],
        "needs_clarification": False,
        "clarification_question": None,
    }


def test_session_returns_structured_clarification_options() -> None:
    manager = ManagerAgent(
        client=MockArkClient(json.dumps(_clarification_payload(), ensure_ascii=False))
    )
    client = TestClient(main_module.app)
    with patch.object(main_module, "manager", manager):
        response = client.post(
            "/api/tasks/sessions",
            json={"prompt": "帮我构建一个投资组合。"},
        )
        task_id = response.json()["task_id"]

        body = response.json()
        assert body["plan"]["needs_clarification"] is True
        options = body["plan"]["clarification_options"]
        assert [group["key"] for group in options] == ["horizon", "risk"]
        assert options[0]["items"] == ["短期", "中期", "长期"]

        detail = client.get(f"/api/tasks/{task_id}").json()

    assert detail["status"] == "needs_clarification"
    types = [event["type"] for event in detail["events"]]
    assert types == ["plan_created", "clarification_required"]


def test_clarify_folds_answers_and_replans_to_planned() -> None:
    manager = ManagerAgent(
        client=MockArkClient(
            json.dumps(_clarification_payload(), ensure_ascii=False),
            json.dumps(_resolved_payload(), ensure_ascii=False),
        )
    )
    client = TestClient(main_module.app)
    with patch.object(main_module, "manager", manager):
        created = client.post(
            "/api/tasks/sessions",
            json={"prompt": "帮我构建一个投资组合。"},
        )
        task_id = created.json()["task_id"]

        resumed = client.post(
            f"/api/tasks/{task_id}/clarify",
            json={"answers": {"horizon": "中期", "risk": "稳健"}},
        )
        body = resumed.json()

        detail = client.get(f"/api/tasks/{task_id}").json()

    assert resumed.status_code == 200
    assert body["plan"]["needs_clarification"] is False
    assert body["plan"]["steps"][0]["agent"] == "research"

    # The folded answers were passed to the Manager on the re-plan call.
    replan_prompt = manager._client.prompts[-1]
    assert "horizon=中期" in replan_prompt
    assert "risk=稳健" in replan_prompt

    assert detail["status"] == "planned"
    types = [event["type"] for event in detail["events"]]
    assert types == ["plan_created", "clarification_required", "plan_created"]


def test_clarify_on_missing_task_returns_404() -> None:
    response = TestClient(main_module.app).post(
        "/api/tasks/nope/clarify",
        json={"answers": {}},
    )
    assert response.status_code == 404
