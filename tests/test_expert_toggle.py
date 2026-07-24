"""Disabling an expert must be enforced at planning AND execution time."""

from __future__ import annotations

import json

import pytest

from backend.agents.manager_agent import ManagerAgent, ManagerAgentError
from backend.core.contracts import ExecutionPlan
from backend.core.plan_validator import PlanValidationError, validate_execution_plan
from backend.core.registry_factory import build_registry
from backend.core.store import Store
from backend.core.workflow_executor import WorkflowExecutor


class MockArkClient:
    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def chat(self, prompt: str, model: str | None = None) -> str:
        self.prompts.append(prompt)
        return self.responses.pop(0)


def _quant_plan_payload() -> dict:
    return {
        "goal": "设计量化因子",
        "intent": "按用户目标执行",
        "complexity": "low",
        "selected_agents": [{"agent": "quant", "reason": "需要 quant"}],
        "steps": [
            {
                "id": "quant_1",
                "agent": "quant",
                "objective": "quant objective",
                "inputs": {},
                "depends_on": [],
                "expected_output": "quant output",
            }
        ],
        "needs_clarification": False,
        "clarification_question": None,
    }


def _disabled_quant_registry(tmp_path):
    store = Store(tmp_path / "alphaos.db")
    store.set_override("quant", False)
    return build_registry(store)


def test_disabled_registry_drops_expert_from_enabled_set(tmp_path) -> None:
    registry = _disabled_quant_registry(tmp_path)

    assert not registry.is_enabled(_agent("quant"))
    assert "quant" not in {a.value for a in registry.ids(enabled_only=True)}
    assert {a.value for a in registry.ids(enabled_only=True)} == {
        "research",
        "risk",
        "macro",
        "report",
    }


def test_planning_rejects_disabled_expert(tmp_path) -> None:
    registry = _disabled_quant_registry(tmp_path)
    payload = json.dumps(_quant_plan_payload(), ensure_ascii=False)
    manager = ManagerAgent(client=MockArkClient(payload, payload), registry=registry)

    with pytest.raises(ManagerAgentError):
        manager.create_plan("设计一个量化因子")


def test_plan_validator_rejects_disabled_expert(tmp_path) -> None:
    registry = _disabled_quant_registry(tmp_path)
    plan = ExecutionPlan.model_validate(_quant_plan_payload())

    with pytest.raises(PlanValidationError):
        validate_execution_plan(plan, registry)


def test_execution_rejects_disabled_expert(tmp_path) -> None:
    registry = _disabled_quant_registry(tmp_path)
    executor = WorkflowExecutor(registry=registry)
    plan = ExecutionPlan.model_validate(_quant_plan_payload())

    _events, results = executor.execute(plan, "设计一个量化因子")

    assert results["quant_1"].status == "failed"
    assert "disabled" in (results["quant_1"].error or "")


def _agent(value: str):
    from backend.core.contracts import AgentId

    return AgentId(value)
