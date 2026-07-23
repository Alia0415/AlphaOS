from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import main as main_module
from backend.agents.manager_agent import ManagerAgent, ManagerAgentError
from backend.core.contracts import AgentId, ExpertResult, ExpertTask
from backend.core.workflow_executor import WorkflowExecutor


class MockArkClient:
    """Deterministic ArkClient replacement that never performs network I/O."""

    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def chat(self, prompt: str, model: str | None = None) -> str:
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("Unexpected ArkClient call")
        return self.responses.pop(0)


def _json_response(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False)


class DynamicPlanningTests(unittest.TestCase):
    def test_manager_stops_after_one_invalid_json_repair_attempt(self) -> None:
        client = MockArkClient("not-json", "still-not-json", "unused-response")

        with self.assertRaises(ManagerAgentError):
            ManagerAgent(client=client).create_plan("分析一个投资机会")

        self.assertEqual(len(client.prompts), 2)
        self.assertEqual(client.responses, ["unused-response"])

    def test_profitability_analysis_selects_research_only(self) -> None:
        response = _json_response(
            {
                "goal": "分析贵州茅台近五年的盈利能力",
                "intent": "公司盈利能力研究",
                "complexity": "low",
                "selected_agents": [
                    {"agent": "research", "reason": "完成公司基本面研究"}
                ],
                "steps": [
                    {
                        "id": "research_profitability",
                        "agent": "research",
                        "objective": "分析贵州茅台近五年的收入、利润率和回报指标",
                        "depends_on": [],
                        "expected_output": "五年盈利能力研究结论与依据",
                    }
                ],
                "needs_clarification": False,
                "clarification_question": None,
            }
        )
        client = MockArkClient(response)

        plan = ManagerAgent(client=client).create_plan(
            "分析贵州茅台近五年的盈利能力"
        )

        self.assertEqual(
            [selection.agent for selection in plan.selected_agents],
            [AgentId.RESEARCH],
        )
        self.assertEqual([step.agent for step in plan.steps], [AgentId.RESEARCH])
        self.assertIn("可用专家注册表", client.prompts[0])

    def test_volume_momentum_risk_executes_quant_before_risk(self) -> None:
        response = _json_response(
            {
                "goal": "检查成交量动量策略的主要风险",
                "intent": "量化策略风险审查",
                "complexity": "medium",
                "selected_agents": [
                    {"agent": "quant", "reason": "先明确策略逻辑和可检验假设"},
                    {"agent": "risk", "reason": "基于量化结果识别风险"},
                ],
                "steps": [
                    {
                        "id": "quant_check",
                        "agent": "quant",
                        "objective": "检查成交量动量策略定义和统计特征",
                        "depends_on": [],
                        "expected_output": "策略假设和量化检查结果",
                    },
                    {
                        "id": "risk_review",
                        "agent": "risk",
                        "objective": "识别策略的主要风险和失效场景",
                        "depends_on": ["quant_check"],
                        "expected_output": "按重要性排序的风险清单",
                    },
                ],
                "needs_clarification": False,
                "clarification_question": None,
            }
        )
        plan = ManagerAgent(client=MockArkClient(response)).create_plan(
            "检查一个成交量动量策略是否存在主要风险"
        )
        received_tasks: list[ExpertTask] = []

        def handler(task: ExpertTask) -> ExpertResult:
            received_tasks.append(task)
            return ExpertResult(
                step_id=task.step_id,
                agent=task.agent,
                status="completed",
                output={"checked_by": task.agent.value},
            )

        executor = WorkflowExecutor(
            {AgentId.QUANT: handler, AgentId.RISK: handler}
        )
        events, results = executor.execute(plan)

        self.assertEqual(
            [result.agent for result in results],
            [AgentId.QUANT, AgentId.RISK],
        )
        self.assertEqual(
            [task.agent for task in received_tasks],
            [AgentId.QUANT, AgentId.RISK],
        )
        self.assertEqual(
            received_tasks[1].dependency_results,
            {"quant_check": {"checked_by": "quant"}},
        )
        self.assertLess(
            next(
                event.sequence
                for event in events
                if event.step_id == "quant_check" and event.status == "completed"
            ),
            next(
                event.sequence
                for event in events
                if event.step_id == "risk_review" and event.status == "started"
            ),
        )

    def test_industry_opportunity_builds_dynamic_dependency_graph(self) -> None:
        response = _json_response(
            {
                "goal": "分析机器人行业机会并设计可验证的量化策略",
                "intent": "行业机会研究与量化策略设计",
                "complexity": "high",
                "selected_agents": [
                    {"agent": "macro", "reason": "评估政策与周期背景"},
                    {"agent": "research", "reason": "研究产业和公司机会"},
                    {"agent": "quant", "reason": "把研究结论转化为可检验策略"},
                    {"agent": "risk", "reason": "审查策略主要风险"},
                    {"agent": "report", "reason": "汇总完整研究结果"},
                ],
                "steps": [
                    {
                        "id": "macro_context",
                        "agent": "macro",
                        "objective": "分析机器人行业的宏观、政策和周期环境",
                        "depends_on": [],
                        "expected_output": "宏观驱动与约束",
                    },
                    {
                        "id": "research_opportunity",
                        "agent": "research",
                        "objective": "分析机器人产业链和投资机会",
                        "depends_on": [],
                        "expected_output": "机会假设与证据",
                    },
                    {
                        "id": "quant_strategy",
                        "agent": "quant",
                        "objective": "设计可验证的量化策略",
                        "depends_on": ["macro_context", "research_opportunity"],
                        "expected_output": "策略规则、数据需求和验证方案",
                    },
                    {
                        "id": "risk_review",
                        "agent": "risk",
                        "objective": "审查量化策略风险",
                        "depends_on": ["quant_strategy"],
                        "expected_output": "风险、压力场景和控制建议",
                    },
                    {
                        "id": "final_report",
                        "agent": "report",
                        "objective": "组织完整研究报告",
                        "depends_on": [
                            "macro_context",
                            "research_opportunity",
                            "quant_strategy",
                            "risk_review",
                        ],
                        "expected_output": "证据清晰的综合报告",
                    },
                ],
                "needs_clarification": False,
                "clarification_question": None,
            }
        )

        plan = ManagerAgent(client=MockArkClient(response)).create_plan(
            "分析机器人行业是否存在投资机会，并设计一个可验证的量化策略"
        )

        by_id = {step.id: step for step in plan.steps}
        self.assertEqual(by_id["macro_context"].depends_on, [])
        self.assertEqual(by_id["research_opportunity"].depends_on, [])
        self.assertEqual(
            set(by_id["quant_strategy"].depends_on),
            {"macro_context", "research_opportunity"},
        )
        self.assertEqual(by_id["risk_review"].depends_on, ["quant_strategy"])
        self.assertEqual(
            set(by_id["final_report"].depends_on),
            {
                "macro_context",
                "research_opportunity",
                "quant_strategy",
                "risk_review",
            },
        )

        events, results = WorkflowExecutor().execute(plan)
        started = {
            event.step_id: event.sequence
            for event in events
            if event.status == "started"
        }
        completed = {
            event.step_id: event.sequence
            for event in events
            if event.status == "completed"
        }
        self.assertLess(completed["macro_context"], started["quant_strategy"])
        self.assertLess(
            completed["research_opportunity"],
            started["quant_strategy"],
        )
        self.assertLess(completed["quant_strategy"], started["risk_review"])
        self.assertLess(completed["risk_review"], started["final_report"])
        self.assertEqual(len(results), 5)


class PlanningApiTests(unittest.TestCase):
    def test_plan_and_tasks_endpoints_use_mocked_ark(self) -> None:
        plan_response = _json_response(
            {
                "goal": "分析贵州茅台近五年的盈利能力",
                "intent": "公司盈利能力研究",
                "complexity": "low",
                "selected_agents": [
                    {"agent": "research", "reason": "完成基本面研究"}
                ],
                "steps": [
                    {
                        "id": "research_profitability",
                        "agent": "research",
                        "objective": "分析近五年盈利能力",
                        "depends_on": [],
                        "expected_output": "盈利能力研究结论",
                    }
                ],
                "needs_clarification": False,
                "clarification_question": None,
            }
        )
        mock_manager = ManagerAgent(
            client=MockArkClient(
                plan_response,
                plan_response,
                "基于当前占位执行结果，尚不能形成真实投资结论。",
            )
        )

        with patch.object(main_module, "manager", mock_manager):
            client = TestClient(main_module.app)
            plan_http_response = client.post(
                "/api/plan",
                json={"prompt": "分析贵州茅台近五年的盈利能力"},
            )
            task_http_response = client.post(
                "/api/tasks",
                json={"prompt": "分析贵州茅台近五年的盈利能力"},
            )

        self.assertEqual(plan_http_response.status_code, 200)
        self.assertEqual(
            plan_http_response.json()["selected_agents"][0]["agent"],
            "research",
        )
        self.assertEqual(task_http_response.status_code, 200)
        body = task_http_response.json()
        self.assertEqual(body["expert_results"][0]["status"], "completed")
        self.assertEqual(
            body["final_answer"],
            "基于当前占位执行结果，尚不能形成真实投资结论。",
        )
        self.assertTrue(
            main_module.app.openapi()["paths"]["/api/route"]["post"]["deprecated"]
        )


if __name__ == "__main__":
    unittest.main()
