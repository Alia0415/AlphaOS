from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend import main as main_module
from backend.agents.manager_agent import ManagerAgent, ManagerAgentError
from backend.agents.report_agent import ReportAgent
from backend.agents.research_agent import ResearchAgent
from backend.agents.risk_agent import RiskAgent
from backend.core.agent_registry import AgentRegistry
from backend.core.contracts import (
    AgentId,
    ClarificationTurn,
    ExecutionPlan,
    ExpertResult,
    ExpertTask,
    RESEARCH_DISCLAIMER,
)
from backend.core.workflow_executor import WorkflowExecutor


class MockArkClient:
    """Deterministic Ark replacement that never performs network I/O."""

    def __init__(self, *responses: str, error: Exception | None = None) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []
        self.error = error

    def chat(self, prompt: str, model: str | None = None) -> str:
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        if not self.responses:
            raise AssertionError("Unexpected ArkClient call")
        return self.responses.pop(0)


class MockPandaData:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def get_market_data(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


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
    if agent == "risk":
        inputs = {"strategy": "高换手成交量动量策略"}
    return {
        "id": step_id,
        "agent": agent,
        "objective": f"{agent} objective",
        "inputs": inputs,
        "depends_on": depends_on or [],
        "expected_output": f"{agent} output",
    }


def _plan_payload(path: list[str]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    steps: list[dict[str, Any]] = []
    previous: str | None = None
    for agent in path:
        counts[agent] = counts.get(agent, 0) + 1
        step_id = f"{agent}_{counts[agent]}"
        steps.append(_step(step_id, agent, [previous] if previous else []))
        previous = step_id
    return {
        "goal": "动态任务",
        "intent": "按用户目标执行",
        "complexity": "low" if len(path) == 1 else "high",
        "selected_agents": [
            {"agent": agent, "reason": f"需要 {agent}"}
            for agent in dict.fromkeys(path)
        ],
        "steps": steps,
        "needs_clarification": False,
        "clarification_questions": [],
    }


def _plan(path: list[str]) -> ExecutionPlan:
    return ExecutionPlan.model_validate(_plan_payload(path))


def _task(
    agent: AgentId,
    *,
    inputs: dict[str, Any] | None = None,
    dependencies: dict[str, ExpertResult] | None = None,
) -> ExpertTask:
    return ExpertTask(
        task_id=f"{agent.value}_step",
        agent=agent,
        objective=f"{agent.value} objective",
        original_user_request="original request",
        inputs=inputs or {},
        dependency_results=dependencies or {},
    )


def _completed(task: ExpertTask, **kwargs: Any) -> ExpertResult:
    return ExpertResult(
        task_id=task.task_id,
        agent=task.agent,
        status="completed",
        summary=f"{task.agent.value} completed",
        **kwargs,
    )


def test_registry_exposes_only_enabled_experts_to_manager() -> None:
    registry = AgentRegistry()

    assert {item["id"] for item in registry.prompt_payload()} == {
        "quant",
        "research",
        "risk",
        "report",
    }
    assert registry.is_enabled(AgentId.QUANT)
    assert registry.get(AgentId.QUANT).enabled is True


def test_manager_stops_after_one_invalid_json_repair_attempt() -> None:
    client = MockArkClient("not-json", "still-not-json", "unused")

    with pytest.raises(ManagerAgentError):
        ManagerAgent(client=client).create_plan("分析一个投资机会")

    assert len(client.prompts) == 2
    assert client.responses == ["unused"]


def test_manager_prompt_uses_registry_and_minimal_sufficient_principle() -> None:
    client = MockArkClient(json.dumps(_plan_payload(["research"])))

    ManagerAgent(client=client).create_plan("分析 000001.SZ 的价格表现")

    prompt = client.prompts[0]
    assert "最小充分专家集合" in prompt
    assert '"id": "research"' in prompt
    assert '"id": "quant"' in prompt
    assert "绝不能选择、编排或写入专家内部的底层 Skill" in prompt
    assert "report 不是默认必经节点" in prompt


@pytest.mark.parametrize(
    ("user_request", "path"),
    [
        ("分析 000001.SZ 在 2024 年的价格表现。", ["research"]),
        ("评估一个高换手成交量动量策略的主要风险。", ["risk"]),
        ("分析 000001.SZ 在 2024 年的表现并识别风险。", ["research", "risk"]),
        ("分析 000001.SZ 在 2024 年的表现并生成研究报告。", ["research", "report"]),
        (
            "分析 000001.SZ 在 2024 年的表现，识别风险并生成研究报告。",
            ["research", "risk", "report"],
        ),
    ],
)
def test_manager_accepts_five_distinct_dynamic_graphs(
    user_request: str,
    path: list[str],
) -> None:
    manager = ManagerAgent(
        client=MockArkClient(json.dumps(_plan_payload(path), ensure_ascii=False))
    )

    plan = manager.create_plan(user_request)

    assert [step.agent.value for step in plan.steps] == path


def test_manager_accepts_quant_and_rejects_still_disabled_expert() -> None:
    quant_plan = json.dumps(_plan_payload(["quant"]))
    quant_manager = ManagerAgent(client=MockArkClient(quant_plan))

    assert quant_manager.create_plan("设计量化因子").steps[0].agent == AgentId.QUANT

    disabled_plan = json.dumps(_plan_payload(["portfolio"]))
    manager = ManagerAgent(client=MockArkClient(disabled_plan, disabled_plan))
    with pytest.raises(ManagerAgentError):
        manager.create_plan("构建组合")


def test_research_calculates_metrics_in_python_and_calls_pandadata() -> None:
    data = [
        {
            "trade_date": "20240101",
            "symbol": "000001.SZ",
            "close": 100,
            "volume": 1000,
        },
        {
            "trade_date": "20240102",
            "symbol": "000001.SZ",
            "close": 110,
            "volume": 1200,
        },
        {
            "trade_date": "20240103",
            "symbol": "000001.SZ",
            "close": 99,
            "volume": 1400,
        },
    ]
    panda = MockPandaData(data)
    ark = MockArkClient("基于已计算证据的解释。")
    agent = ResearchAgent(data_client=panda, ark_client=ark)

    result = agent.execute(
        _task(
            AgentId.RESEARCH,
            inputs={
                "symbols": ["000001.SZ"],
                "start_date": "20240101",
                "end_date": "20240103",
                "fields": [],
            },
        )
    )

    metrics = result.evidence[0]
    assert result.status == "completed"
    assert metrics["observation_count"] == 3
    assert metrics["period_return"] == pytest.approx(-0.01)
    assert metrics["maximum_drawdown"] == pytest.approx(-0.10)
    assert metrics["average_volume"] == pytest.approx(1200)
    assert metrics["highest_close"] == 110
    assert metrics["lowest_close"] == 99
    assert panda.calls[0]["symbols"] == ["000001.SZ"]
    assert result.metadata["calculation_engine"] == "python"
    assert "所有数值均已由 Python 计算" in ark.prompts[0]
    assert "不要重新计算数字" in ark.prompts[0]


def test_research_handles_empty_data_as_failure() -> None:
    result = ResearchAgent(
        data_client=MockPandaData([]),
        ark_client=MockArkClient(error=AssertionError("must not call Ark")),
    ).execute(
        _task(
            AgentId.RESEARCH,
            inputs={
                "symbols": ["000001.SZ"],
                "start_date": "20240101",
                "end_date": "20240103",
            },
        )
    )

    assert result.status == "failed"
    assert "未返回" in (result.error or "")
    assert result.data_sources[0]["observation_count"] == 0


def test_research_rejects_invalid_dates_before_external_calls() -> None:
    panda = MockPandaData([])

    result = ResearchAgent(data_client=panda).execute(
        _task(
            AgentId.RESEARCH,
            inputs={
                "symbols": ["000001.SZ"],
                "start_date": "20240231",
                "end_date": "20240101",
            },
        )
    )

    assert result.status == "failed"
    assert panda.calls == []


def test_research_keeps_metrics_when_ark_fails() -> None:
    panda = MockPandaData(
        [
            {"trade_date": "20240101", "close": 10, "volume": 100},
            {"trade_date": "20240102", "close": 11, "volume": 110},
        ]
    )
    result = ResearchAgent(
        data_client=panda,
        ark_client=MockArkClient(error=RuntimeError("offline")),
    ).execute(
        _task(
            AgentId.RESEARCH,
            inputs={
                "symbols": ["000001.SZ"],
                "start_date": "20240101",
                "end_date": "20240102",
            },
        )
    )

    assert result.status == "completed"
    assert result.evidence[0]["period_return"] == pytest.approx(0.1)
    assert any("降级" in item for item in result.limitations)


def test_research_does_not_expose_external_exception_or_credentials() -> None:
    result = ResearchAgent(
        data_client=MockPandaData(
            error=RuntimeError("password=super-secret token=private")
        )
    ).execute(
        _task(
            AgentId.RESEARCH,
            inputs={
                "symbols": ["000001.SZ"],
                "start_date": "20240101",
                "end_date": "20240102",
            },
        )
    )
    serialized = result.model_dump_json()

    assert result.status == "failed"
    assert "super-secret" not in serialized
    assert "private" not in serialized


def test_risk_supports_independent_execution() -> None:
    result = RiskAgent(
        ark_client=MockArkClient("独立风险审查摘要。")
    ).execute(
        _task(
            AgentId.RISK,
            inputs={"strategy": "高换手成交量动量策略"},
        )
    )

    assert result.status == "completed"
    assert result.metadata["mode"] == "independent"
    assert result.metadata["risk_level"] in {"low", "medium", "high"}
    assert result.risks
    assert any("未提供可引用" in item for item in result.limitations)


def test_risk_cites_specific_research_dependency_evidence() -> None:
    research = ExpertResult(
        task_id="research_1",
        agent=AgentId.RESEARCH,
        status="completed",
        summary="研究完成",
        evidence=[
            {
                "type": "market_metrics",
                "symbol": "000001.SZ",
                "observation_count": 20,
                "daily_volatility": 0.03,
                "maximum_drawdown": -0.25,
            }
        ],
        data_sources=[{"name": "PandaData"}],
    )
    result = RiskAgent(
        ark_client=MockArkClient("依赖证据风险摘要。")
    ).execute(
        _task(AgentId.RISK, dependencies={"research_1": research})
    )

    assert result.status == "completed"
    assert result.metadata["mode"] == "dependency"
    assert result.metadata["risk_level"] == "high"
    assert result.evidence[0]["source_step"] == "research_1"
    assert result.evidence[0]["fact"]["maximum_drawdown"] == -0.25
    assert any("最大回撤" in risk for risk in result.risks)
    assert result.metadata["fact_judgment_boundary"]["unknowns"]


def test_report_only_integrates_declared_dependencies_and_disclaimer() -> None:
    source = ExpertResult(
        task_id="research_1",
        agent=AgentId.RESEARCH,
        status="completed",
        summary="上游唯一事实",
        evidence=[{"symbol": "000001.SZ", "period_return": 0.1}],
    )
    result = ReportAgent(
        ark_client=MockArkClient("正式报告：上游唯一事实。")
    ).execute(
        _task(AgentId.REPORT, dependencies={"research_1": source})
    )

    assert result.status == "completed"
    assert result.metadata["integrated_steps"] == ["research_1"]
    assert result.evidence[0]["source_step"] == "research_1"
    assert RESEARCH_DISCLAIMER in result.summary
    assert "dependency_results" in result.metadata.get("report", result.summary) or (
        "上游唯一事实" in result.summary
    )


def test_report_without_dependencies_fails_explicitly() -> None:
    result = ReportAgent().execute(_task(AgentId.REPORT))

    assert result.status == "failed"
    assert "上游" in (result.error or "")


def test_report_recovers_cited_transitive_execution_path() -> None:
    risk = ExpertResult(
        task_id="risk_1",
        agent=AgentId.RISK,
        status="completed",
        summary="风险审查",
        evidence=[
            {
                "source_step": "research_1",
                "source_agent": "research",
                "fact": {"maximum_drawdown": -0.1},
            }
        ],
    )

    result = ReportAgent(
        ark_client=MockArkClient("正式报告。")
    ).execute(_task(AgentId.REPORT, dependencies={"risk_1": risk}))

    assert result.metadata["execution_path"] == [
        "research_1:research",
        "risk_1:risk",
    ]


def test_executor_strictly_follows_different_plans() -> None:
    executed: list[str] = []

    def handler(task: ExpertTask) -> ExpertResult:
        executed.append(task.agent.value)
        return _completed(task)

    executor = WorkflowExecutor(
        handlers={
            AgentId.RESEARCH: handler,
            AgentId.RISK: handler,
            AgentId.REPORT: handler,
        }
    )

    _, single_results = executor.execute(_plan(["risk"]), "risk only")
    single_path = executed.copy()
    executed.clear()
    _, chain_results = executor.execute(
        _plan(["research", "report"]),
        "research report",
    )

    assert single_path == ["risk"]
    assert executed == ["research", "report"]
    assert list(single_results) == ["risk_1"]
    assert list(chain_results) == ["research_1", "report_1"]


def test_executor_passes_complete_expert_result_to_downstream() -> None:
    received: list[ExpertTask] = []

    def handler(task: ExpertTask) -> ExpertResult:
        received.append(task)
        return _completed(
            task,
            evidence=[{"metric": 42}],
            assumptions=["assumption"],
            metadata={"complete": True},
        )

    executor = WorkflowExecutor(
        handlers={AgentId.RESEARCH: handler, AgentId.RISK: handler}
    )
    executor.execute(_plan(["research", "risk"]))

    dependency = received[1].dependency_results["research_1"]
    assert isinstance(dependency, ExpertResult)
    assert dependency.evidence == [{"metric": 42}]
    assert dependency.assumptions == ["assumption"]
    assert dependency.metadata == {"complete": True}


def test_still_disabled_expert_never_returns_placeholder_success() -> None:
    called = False

    def handler(task: ExpertTask) -> ExpertResult:
        nonlocal called
        called = True
        return _completed(task)

    events, results = WorkflowExecutor(
        handlers={AgentId.PORTFOLIO: handler}
    ).execute(_plan(["portfolio"]))

    assert not called
    assert results["portfolio_1"].status == "failed"
    assert "disabled" in (results["portfolio_1"].error or "")
    assert events[-1].type == "step_failed"


def test_dependency_failure_blocks_all_descendants() -> None:
    def failing(task: ExpertTask) -> ExpertResult:
        return ExpertResult(
            task_id=task.task_id,
            agent=task.agent,
            status="failed",
            summary="failed",
            error="expected failure",
        )

    report_called = False

    def report(task: ExpertTask) -> ExpertResult:
        nonlocal report_called
        report_called = True
        return _completed(task)

    _, results = WorkflowExecutor(
        handlers={
            AgentId.RESEARCH: failing,
            AgentId.RISK: _completed,
            AgentId.REPORT: report,
        }
    ).execute(_plan(["research", "risk", "report"]))

    assert results["research_1"].status == "failed"
    assert results["risk_1"].status == "blocked"
    assert results["report_1"].status == "blocked"
    assert not report_called


def test_dependency_ready_steps_start_in_same_parallel_batch() -> None:
    plan = ExecutionPlan.model_validate(
        {
            "goal": "parallel",
            "intent": "parallel",
            "complexity": "medium",
            "selected_agents": [
                {"agent": "research", "reason": "first"},
                {"agent": "risk", "reason": "second"},
            ],
            "steps": [
                _step("research_1", "research"),
                _step("risk_1", "risk"),
            ],
        }
    )

    events, _ = WorkflowExecutor(
        handlers={
            AgentId.RESEARCH: _completed,
            AgentId.RISK: _completed,
        }
    ).execute(plan)
    event_types = [(event.step_id, event.type) for event in events]

    assert event_types[:2] == [
        ("research_1", "step_started"),
        ("risk_1", "step_started"),
    ]


def test_executor_emits_tool_event_before_completion() -> None:
    def handler(task: ExpertTask) -> ExpertResult:
        return _completed(
            task,
            tool_calls=[{"tool": "pandadata_market_data", "status": "completed"}],
        )

    events, _ = WorkflowExecutor(
        handlers={AgentId.RESEARCH: handler}
    ).execute(_plan(["research"]))

    assert [event.type for event in events] == [
        "step_started",
        "tool_called",
        "step_completed",
    ]
    assert all(event.timestamp is not None for event in events)


def test_tasks_api_returns_v03_shape_and_full_event_lifecycle() -> None:
    plan_response = json.dumps(_plan_payload(["research"]), ensure_ascii=False)
    mock_manager = ManagerAgent(
        client=MockArkClient(plan_response, "Manager 最终结论。")
    )

    def handler(task: ExpertTask) -> ExpertResult:
        return _completed(task)

    mock_executor = WorkflowExecutor(
        handlers={AgentId.RESEARCH: handler}
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
    assert set(body) == {
        "plan",
        "events",
        "results",
        "final_answer",
        "duration_ms",
        "disclaimer",
    }
    assert list(body["results"]) == ["research_1"]
    assert [event["type"] for event in body["events"]] == [
        "plan_created",
        "step_started",
        "step_completed",
        "synthesis_started",
        "task_completed",
    ]
    assert body["disclaimer"] == RESEARCH_DISCLAIMER
    assert main_module.app.openapi()["paths"]["/api/route"]["post"]["deprecated"]


def test_clarification_returns_events_without_expert_execution() -> None:
    clarification = {
        "goal": "分析股票",
        "intent": "信息不足",
        "complexity": "low",
        "selected_agents": [],
        "steps": [],
        "needs_clarification": True,
        "clarification_questions": ["请提供股票代码和日期范围。"],
    }
    mock_manager = ManagerAgent(
        client=MockArkClient(json.dumps(clarification, ensure_ascii=False))
    )
    with patch.object(main_module, "manager", mock_manager):
        response = TestClient(main_module.app).post(
            "/api/tasks",
            json={"prompt": "帮我分析一下"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["results"] == {}
    assert [event["type"] for event in body["events"]] == [
        "plan_created",
        "clarification_required",
        "task_completed",
    ]
    assert body["events"][1]["metadata"] == {
        "round": 1,
        "max_rounds": 5,
        "questions": ["请提供股票代码和日期范围。"],
    }
    assert body["final_answer"] == "请提供股票代码和日期范围。"


def test_manager_prompt_includes_clarification_history_and_round_number() -> None:
    history_payload = [
        {"questions": ["请提供股票代码。"], "answer": "000001.SZ"},
    ]
    client = MockArkClient(json.dumps(_plan_payload(["research"])))

    ManagerAgent(client=client).create_plan(
        "帮我分析一下",
        [ClarificationTurn.model_validate(turn) for turn in history_payload],
    )

    prompt = client.prompts[0]
    assert "第 2 轮规划" in prompt
    assert "000001.SZ" in prompt
    assert "请提供股票代码。" in prompt


def test_manager_allows_clarification_through_round_five() -> None:
    history = [
        ClarificationTurn(questions=[f"问题 {i}"], answer=f"答案 {i}")
        for i in range(4)
    ]
    clarification = {
        "goal": "分析股票",
        "intent": "信息不足",
        "complexity": "low",
        "selected_agents": [],
        "steps": [],
        "needs_clarification": True,
        "clarification_questions": ["还需要哪个时间区间？"],
    }
    manager = ManagerAgent(
        client=MockArkClient(json.dumps(clarification, ensure_ascii=False))
    )

    plan = manager.create_plan("帮我分析一下", history)

    assert plan.needs_clarification is True


def test_manager_forbids_clarification_past_round_five() -> None:
    history = [
        ClarificationTurn(questions=[f"问题 {i}"], answer=f"答案 {i}")
        for i in range(5)
    ]
    clarification = {
        "goal": "分析股票",
        "intent": "信息不足",
        "complexity": "low",
        "selected_agents": [],
        "steps": [],
        "needs_clarification": True,
        "clarification_questions": ["还需要哪个时间区间？"],
    }
    manager = ManagerAgent(
        client=MockArkClient(
            json.dumps(clarification, ensure_ascii=False),
            json.dumps(clarification, ensure_ascii=False),
        )
    )

    with pytest.raises(ManagerAgentError):
        manager.create_plan("帮我分析一下", history)


def test_execution_plan_rejects_clarification_without_questions() -> None:
    with pytest.raises(Exception):
        ExecutionPlan.model_validate(
            {
                "goal": "g",
                "intent": "i",
                "complexity": "low",
                "selected_agents": [],
                "steps": [],
                "needs_clarification": True,
                "clarification_questions": [],
            }
        )


def test_execution_plan_rejects_clarification_with_steps() -> None:
    with pytest.raises(Exception):
        ExecutionPlan.model_validate(
            {
                "goal": "g",
                "intent": "i",
                "complexity": "low",
                "selected_agents": [{"agent": "research", "reason": "需要"}],
                "steps": [_step("research_1", "research")],
                "needs_clarification": True,
                "clarification_questions": ["问题？"],
            }
        )
