"""Manager Agent for dynamic expert selection and task-graph planning."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from backend.core.agent_registry import AgentRegistry
from backend.core.contracts import ExecutionPlan, ExpertResult
from backend.core.plan_validator import PlanValidationError, validate_execution_plan
from backend.services.ark_client import ArkClient, ArkClientError


class ManagerAgentError(RuntimeError):
    """Raised when the Manager cannot produce or synthesize a valid response."""


class ManagerAgent:
    """Select experts, construct a task graph, and synthesize their results."""

    def __init__(
        self,
        client: ArkClient | None = None,
        registry: AgentRegistry | None = None,
    ) -> None:
        self._client = client
        self.registry = registry or AgentRegistry()

    def create_plan(self, user_request: str) -> ExecutionPlan:
        request = user_request.strip()
        if not request:
            raise ManagerAgentError("规划请求不能为空。")

        prompt = self._planning_prompt(request)
        try:
            raw_response = self._get_client().chat(prompt)
        except ArkClientError as exc:
            raise ManagerAgentError(str(exc)) from None

        try:
            return self._parse_and_validate(raw_response)
        except (json.JSONDecodeError, ValidationError, PlanValidationError, ValueError) as exc:
            repair_prompt = self._repair_prompt(
                request=request,
                invalid_response=raw_response,
                error=str(exc),
            )
            try:
                repaired_response = self._get_client().chat(repair_prompt)
                return self._parse_and_validate(repaired_response)
            except ArkClientError as repair_exc:
                raise ManagerAgentError(str(repair_exc)) from None
            except (
                json.JSONDecodeError,
                ValidationError,
                PlanValidationError,
                ValueError,
            ):
                raise ManagerAgentError(
                    "Manager Agent 在一次修复后仍未返回有效的执行计划。"
                ) from None

    def synthesize(
        self,
        user_request: str,
        plan: ExecutionPlan,
        results: list[ExpertResult],
    ) -> str:
        if plan.needs_clarification:
            return plan.clarification_question or "请补充完成任务所需的关键信息。"

        payload = {
            "user_request": user_request,
            "plan": plan.model_dump(mode="json"),
            "expert_results": [
                result.model_dump(mode="json")
                for result in results
            ],
        }
        prompt = f"""
你是 AlphaOS Manager Agent。你不是专家池成员。
请综合下列已执行任务的结果，直接回答用户目标。
清楚区分事实、假设和占位结果；不得伪造专家尚未提供的业务结论。
用简洁、结构清晰的中文输出最终答案，不要返回 JSON。

执行上下文：
{json.dumps(payload, ensure_ascii=False)}
""".strip()
        try:
            return self._get_client().chat(prompt).strip()
        except ArkClientError as exc:
            raise ManagerAgentError(str(exc)) from None

    def _parse_and_validate(self, raw_response: str) -> ExecutionPlan:
        payload = _extract_json(raw_response)
        plan = ExecutionPlan.model_validate(payload)
        return validate_execution_plan(plan, self.registry)

    def _planning_prompt(self, request: str) -> str:
        registry_json = json.dumps(
            self.registry.prompt_payload(),
            ensure_ascii=False,
            indent=2,
        )
        schema_json = json.dumps(
            ExecutionPlan.model_json_schema(),
            ensure_ascii=False,
        )
        return f"""
你是 AlphaOS Manager Agent，是编排器，不属于专家池，也不能把 manager 写入计划。
你必须针对当前用户目标动态决定：
1. 需要哪些专家以及专家数量；
2. 哪些步骤可以并行；
3. 哪些步骤依赖前置结果；
4. 是否需要先向用户澄清。

不得套用固定工作流，不得只选择一个所谓主 Agent。简单目标可以只选一个专家；
复杂目标应按实际需要构建依赖图。depends_on 为空表示可立即并行执行。
最多生成 8 个步骤。selected_agents 必须与 steps 中实际使用的专家完全一致。
如果关键信息不足，将 needs_clarification 设为 true，并提供 clarification_question。

可用专家注册表：
{registry_json}

只返回一个严格符合下列 JSON Schema 的 JSON 对象，不要 Markdown、解释或代码围栏：
{schema_json}

用户请求：
{request}
""".strip()

    def _repair_prompt(
        self,
        request: str,
        invalid_response: str,
        error: str,
    ) -> str:
        schema_json = json.dumps(
            ExecutionPlan.model_json_schema(),
            ensure_ascii=False,
        )
        return f"""
你上一次为 AlphaOS 生成的计划无效。仅进行这一次修复。
保持用户目标不变，修正 JSON 语法、字段类型和任务图约束。
只返回严格 JSON，不要 Markdown 或解释。

用户请求：
{request}

验证错误：
{error}

无效响应：
{invalid_response[:20_000]}

目标 JSON Schema：
{schema_json}
""".strip()

    def _get_client(self) -> ArkClient:
        if self._client is None:
            self._client = ArkClient()
        return self._client


def _extract_json(value: str) -> Any:
    """Accept strict JSON and tolerate a single surrounding code fence."""

    text = value.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
    return json.loads(text)
