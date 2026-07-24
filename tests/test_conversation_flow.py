"""End-to-end test for multi-turn conversation with cross-turn context.

Tests the Phase 1 + Phase 2 conversation features:
1. First turn → auto-creates conversation
2. Second turn with same conversation_id → appends, sees prior context
3. Conversation listing and detail API
All Ark calls are mocked so the test needs no real API key.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import main as main_module
from backend.agents.manager_agent import ManagerAgent
from backend.agents.quant_agent import QuantAgent
from backend.agents.report_agent import ReportAgent
from backend.agents.research_agent import ResearchAgent
from backend.agents.risk_agent import RiskAgent
from backend.core.agent_registry import AgentRegistry
from backend.core.contracts import (
    AgentId,
    ExpertResult,
    ExpertTask,
)
from backend.core.workflow_executor import WorkflowExecutor


class MockArkClient:
    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.all_prompts: list[str] = []

    def chat(self, prompt: str, model: str | None = None) -> str:
        self.all_prompts.append(prompt)
        if not self.responses:
            raise AssertionError("Unexpected ArkClient call")
        return self.responses.pop(0)


def _step(
    step_id: str,
    agent: str,
    depends_on: list[str] | None = None,
) -> dict[str, Any]:
    inputs: dict[str, Any] = {}
    if agent == "research":
        inputs = {
            "symbols": ["000001.SZ"],
            "start_date": "20240101",
            "end_date": "20241231",
            "fields": [],
        }
    return {
        "id": step_id,
        "agent": agent,
        "objective": f"{agent} objective",
        "inputs": inputs,
        "depends_on": depends_on or [],
        "expected_output": f"{agent} output",
    }


def _plan_payload(
    path: list[str],
    text: str = "",
) -> dict[str, Any]:
    counts: dict[str, int] = {}
    steps: list[dict[str, Any]] = []
    previous: str | None = None
    for agent in path:
        counts[agent] = counts.get(agent, 0) + 1
        step_id = f"{agent}_{counts[agent]}"
        steps.append(_step(step_id, agent, [previous] if previous else []))
        previous = step_id
    return {
        "goal": text or "动态任务",
        "intent": text or "按用户目标执行",
        "complexity": "low" if len(path) == 1 else "high",
        "selected_agents": [
            {"agent": agent, "reason": f"需要 {agent}"}
            for agent in dict.fromkeys(path)
        ],
        "steps": steps,
        "needs_clarification": False,
        "clarification_questions": [],
    }


def completed(task: ExpertTask, **kwargs: Any) -> ExpertResult:
    return ExpertResult(
        task_id=task.task_id,
        agent=task.agent,
        status="completed",
        summary=f"{task.agent.value} completed",
        **kwargs,
    )


class TestConversationFlow:
    """Verify that multi-turn conversation + cross-turn context works."""

    def test_first_turn_creates_conversation(self) -> None:
        """First POST /api/tasks without conversation_id → gets one back."""
        plan_json = json.dumps(_plan_payload(["research"]), ensure_ascii=False)
        mock_manager = ManagerAgent(client=MockArkClient(plan_json))
        mock_executor = WorkflowExecutor(
            handlers={AgentId.RESEARCH: completed}
        )
        with (
            patch.object(main_module, "manager", mock_manager),
            patch.object(main_module, "workflow_executor", mock_executor),
        ):
            response = TestClient(main_module.app).post(
                "/api/tasks",
                json={"prompt": "分析 000001.SZ 在 2024 年的价格表现。"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["conversation_id"] is not None, "首次请求应返回 conversation_id"
        assert isinstance(body["conversation_id"], str)
        assert len(body["conversation_id"]) > 0

    def test_second_turn_appends_and_sees_context(self) -> None:
        """Second POST with conversation_id → appends turn, Manager sees past context."""
        conv_id: str | None = None

        # --- 第 1 轮 ---
        plan_json = json.dumps(_plan_payload(["research"]), ensure_ascii=False)
        mock_manager = ManagerAgent(client=MockArkClient(plan_json))
        mock_executor = WorkflowExecutor(
            handlers={AgentId.RESEARCH: completed}
        )
        with (
            patch.object(main_module, "manager", mock_manager),
            patch.object(main_module, "workflow_executor", mock_executor),
        ):
            r1 = TestClient(main_module.app).post(
                "/api/tasks",
                json={"prompt": "分析 000001.SZ 在 2024 年的价格表现。"},
            )
        assert r1.status_code == 200
        conv_id = r1.json()["conversation_id"]
        assert conv_id is not None

        # 验证对话列表
        list_resp = TestClient(main_module.app).get("/api/conversations")
        assert list_resp.status_code == 200
        conv_list = list_resp.json()
        ids = [c["id"] for c in conv_list]
        assert conv_id in ids, "对话应在列表中出现"

        # 验证对话详情有 1 条 turn
        detail_resp = TestClient(main_module.app).get(f"/api/conversations/{conv_id}")
        assert detail_resp.status_code == 200
        assert len(detail_resp.json()["turns"]) == 1

        # --- 第 2 轮（带 conversation_id） ---
        plan_json2 = json.dumps(
            _plan_payload(["quant"], text="继续分析波动率"),
            ensure_ascii=False,
        )
        mock_manager2 = ManagerAgent(
            client=MockArkClient(plan_json2)
        )
        mock_executor2 = WorkflowExecutor(
            handlers={AgentId.QUANT: completed}
        )
        with (
            patch.object(main_module, "manager", mock_manager2),
            patch.object(main_module, "workflow_executor", mock_executor2),
        ):
            r2 = TestClient(main_module.app).post(
                "/api/tasks",
                json={
                    "prompt": "解释一下波动率是怎么算的",
                    "conversation_id": conv_id,
                },
            )

        assert r2.status_code == 200, f"第 2 轮应成功，但返回 {r2.status_code}: {r2.text[:200]}"
        body2 = r2.json()
        assert body2["conversation_id"] == conv_id, "conversation_id 应不变"

        # 验证第 2 轮 Manager 收到了历史上下文
        manager_prompt = mock_manager2._client.all_prompts[0]
        assert "分析 000001.SZ" in manager_prompt, \
            f"Manager prompt 应包含第 1 轮用户请求：\n{manager_prompt[:500]}"
        assert "已完成的分析" in manager_prompt, \
            f"Manager prompt 应包含历史上下文标记：\n{manager_prompt[:500]}"

        # 验证对话详情现在有 2 条 turn
        detail_resp2 = TestClient(main_module.app).get(
            f"/api/conversations/{conv_id}"
        )
        assert detail_resp2.status_code == 200
        turns = detail_resp2.json()["turns"]
        assert len(turns) == 2, f"应有 2 条轮次，实际 {len(turns)}"

        # 验证第 1 轮和第 2 轮的内容都完整可渲染
        assert turns[0]["aggregation"]["direct_answer"]["headline"]
        assert turns[1]["aggregation"]["direct_answer"]["headline"]
        assert turns[0]["prompt"] == "分析 000001.SZ 在 2024 年的价格表现。"
        assert turns[1]["prompt"] == "解释一下波动率是怎么算的"

    def test_delete_conversation(self) -> None:
        """DELETE /api/conversations/{id} removes it."""
        # 创建一条对话
        plan_json = json.dumps(_plan_payload(["research"]), ensure_ascii=False)
        mock_manager = ManagerAgent(client=MockArkClient(plan_json))
        mock_executor = WorkflowExecutor(
            handlers={AgentId.RESEARCH: completed}
        )
        with (
            patch.object(main_module, "manager", mock_manager),
            patch.object(main_module, "workflow_executor", mock_executor),
        ):
            r = TestClient(main_module.app).post(
                "/api/tasks",
                json={"prompt": "test"},
            )
        conv_id = r.json()["conversation_id"]

        # 删除
        del_resp = TestClient(main_module.app).delete(
            f"/api/conversations/{conv_id}"
        )
        assert del_resp.status_code == 204
        # 验证已删除
        get_resp = TestClient(main_module.app).get(
            f"/api/conversations/{conv_id}"
        )
        assert get_resp.status_code == 404, "删除后应返回 404"

    def test_cross_turn_prompt_contains_prior_findings(self) -> None:
        """Phase 2: Manager's planning prompt includes extracted key findings."""
        conv_id: str | None = None

        # --- 第 1 轮：research 完成，产生指标数据 ---
        plan1 = json.dumps(_plan_payload(["research"]), ensure_ascii=False)
        mock_manager1 = ManagerAgent(client=MockArkClient(plan1))

        def research_with_metrics(task: ExpertTask) -> ExpertResult:
            return ExpertResult(
                task_id=task.task_id,
                agent=task.agent,
                status="completed",
                summary="研究完成",
                evidence=[{
                    "period_return": -0.01,
                    "maximum_drawdown": -0.10,
                    "daily_volatility": 0.02,
                    "observation_count": 243,
                }],
                data_sources=[{
                    "name": "PandaData",
                    "symbols": ["000001.SZ"],
                }],
            )

        mock_executor1 = WorkflowExecutor(
            handlers={AgentId.RESEARCH: research_with_metrics}
        )
        with (
            patch.object(main_module, "manager", mock_manager1),
            patch.object(main_module, "workflow_executor", mock_executor1),
        ):
            r1 = TestClient(main_module.app).post(
                "/api/tasks",
                json={"prompt": "分析 000001.SZ 在 2024 年的价格表现。"},
            )
        conv_id = r1.json()["conversation_id"]

        # --- 第 2 轮 ---
        plan2 = json.dumps(
            _plan_payload(["risk"], text="审查风险"),
            ensure_ascii=False,
        )
        mock_manager2 = ManagerAgent(
            client=MockArkClient(plan2)
        )
        mock_executor2 = WorkflowExecutor(
            handlers={AgentId.RISK: completed}
        )
        with (
            patch.object(main_module, "manager", mock_manager2),
            patch.object(main_module, "workflow_executor", mock_executor2),
        ):
            r2 = TestClient(main_module.app).post(
                "/api/tasks",
                json={
                    "prompt": "这个股票风险大吗",
                    "conversation_id": conv_id,
                },
            )

        assert r2.status_code == 200
        manager_prompt = mock_manager2._client.all_prompts[0]

        # 验证 Manager prompt 中包含第 1 轮的结论摘要
        assert "period_return" in manager_prompt or "最大回撤" in manager_prompt or \
               "指标" in manager_prompt, \
            f"Manager prompt 应包含前一轮的指标发现：\n{manager_prompt[:800]}"

        # 验证"延续已有对话的新一轮请求"指令存在
        assert "延续已有对话" in manager_prompt or "已完成的分析" in manager_prompt, \
            "Manager prompt 应有跨轮次指令"
