"""Intent classification for routing future AlphaOS agent tasks."""

from __future__ import annotations

import json
from enum import Enum

from pydantic import BaseModel, Field, ValidationError

from backend.services.ark_client import ArkClient, ArkClientError


class AgentName(str, Enum):
    RESEARCH = "research"
    QUANT = "quant"
    RISK = "risk"
    MANAGER = "manager"


class RouteDecision(BaseModel):
    """Validated output produced by the Router Agent."""

    agent: AgentName
    intent: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    needs_clarification: bool = False


class RouterAgentError(RuntimeError):
    """Raised when a routing decision cannot be produced."""


class RouterAgent:
    """Classify a user request without invoking downstream agents."""

    def __init__(self, client: ArkClient | None = None) -> None:
        self._client = client

    def route(self, user_request: str) -> RouteDecision:
        request = user_request.strip()
        if not request:
            raise RouterAgentError("路由请求不能为空。")

        prompt = f"""
你是 AlphaOS 的 Intent Router Agent，只负责识别意图和选择一个主处理 Agent。
不要回答用户问题，也不要执行研究、计算、风险评估或投资决策。

可选 Agent：
- research：资料检索、公司或行业研究、信息归纳
- quant：数据分析、因子研究、回测、量化计算
- risk：风险识别、压力测试、合规与假设审查
- manager：综合性任务、投资决策整合，或无法归入以上单一类别的任务

只返回一个合法 JSON 对象，不要使用 Markdown：
{{
  "agent": "research|quant|risk|manager",
  "intent": "简洁描述用户意图",
  "reason": "简洁说明路由原因",
  "needs_clarification": false
}}

如果完成任务所需的关键信息不足，将 needs_clarification 设为 true。

用户请求：
{request}
""".strip()

        try:
            raw_response = self._get_client().chat(prompt)
            payload = _extract_json(raw_response)
            return RouteDecision.model_validate(payload)
        except ArkClientError as exc:
            raise RouterAgentError(str(exc)) from None
        except (json.JSONDecodeError, ValidationError, ValueError, TypeError):
            raise RouterAgentError("Router Agent 返回了无效的结构化结果。") from None

    def _get_client(self) -> ArkClient:
        if self._client is None:
            self._client = ArkClient()
        return self._client


def _extract_json(value: str) -> object:
    """Accept plain JSON and tolerate a surrounding Markdown code fence."""
    text = value.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
    return json.loads(text)
