"""Manager Agent for dynamic expert selection and task-graph planning."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from backend.core.agent_registry import AgentRegistry
from backend.core.contracts import ExecutionPlan
from backend.core.plan_validator import PlanValidationError, validate_execution_plan
from backend.services.ark_client import ArkClient, ArkClientError


class ManagerAgentError(RuntimeError):
    """Raised when the Manager cannot produce a valid execution plan."""


class ManagerAgent:
    """Select experts and construct a task graph; never aggregate results."""

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
你只能选择专家和专家间依赖，绝不能选择、编排或写入专家内部的底层 Skill。
Research 和 Quant Agent 都会在各自授权 Skill 中另行动态规划；Manager 不得替它们
做这件事，plan 中不得出现 skill_id 或 a_share_stock_dossier。

始终选择完成任务所需的最小充分专家集合：
- 不得因为某个专家已实现就选择它；
- 价格/市场表现分析通常只需要 research，不得自动追加 risk 或 report；
- 独立策略风险审查可以只使用 risk，不得强制先调用 research；
- 只有用户明确要求报告、摘要、备忘录、正式输出，或复杂任务确需整合多个专家时，
  才选择 report；
- report 不是默认必经节点，risk 也不是默认必经节点；
- 不得生成 research→risk→report 或其他固定模板；依赖只能来自当前目标的业务需要；
- 每个 step.inputs 必须填写该专家需要的结构化输入。市场研究应提取 symbols、
  start_date、end_date、fields，日期格式为 YYYYMMDD。symbols 必须始终是列表，
  不能写成单数 symbol；fields 为空列表时 Research 使用默认字段，否则必须至少包含
  trade_date、symbol、close、volume，绝不能使用 price、financials、
  fundamental_metrics 等概念名代替真实字段；
- 单公司财报、基本面、尽调和财务风险问题只选择 research；应提取 symbol、
  period、scope、focus 和 research_goal。只问财报时 scope=financials，全面尽调时
  scope=full_dossier。Manager 仍然只能选择 research，绝不能写入底层 Skill；
- Quant 因子实际计算同样必须提取 symbols、start_date、end_date；缺少任一项时
  必须要求澄清，不能猜测。因子创意任务不要求先获取市场数据；
- 不得因为 Quant 可用就强制加入所有任务，也不得为 Quant 任务自动追加 risk 或
  report。只有用户明确要求风险审查或报告时才选相应专家并建立业务依赖。
- 当任务明确要求评估经济周期、利率、流动性、政策或行业宏观环境时，可以选择
  macro；Macro 使用 PandaData 自行规划内部宏观指标，Manager 不得选择指标或 API；
- 纯历史收益、因子计算、股票技术指标或公司财务任务不得自动追加 macro；
- Macro 输入应提取 industry、time_range、research_goal。用户给出明确历史区间时
  同时填写 start_date、end_date；只有前瞻期限时不猜测历史日期，由 Macro 使用
  截至执行日的最近 24 个月数据；
- 不得自动追加 macro。Macro 与其他专家的依赖只能来自当前任务的真实业务需要。

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
        registry_json = json.dumps(
            self.registry.prompt_payload(),
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

当前唯一可用的专家注册表（不得使用列表外或 enabled=false 的专家）：
{registry_json}

Agent 输入契约：
- 市场 Research 必须使用 symbols 列表、YYYYMMDD 的 start_date/end_date；fields
  为空列表或至少包含 trade_date、symbol、close、volume；
- 财报/尽调 Research 才能使用 symbol，并必须提供 financials、financial_risk
  或 full_dossier scope；
- Report 必须声明至少一个上游 depends_on；
- 不要为了修复契约而增加不需要的专家或改成固定流程。
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
