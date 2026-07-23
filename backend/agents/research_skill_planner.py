"""Bounded, ownership-aware Skill selection inside Research Agent."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from backend.core.contracts import AgentId, ExpertTask
from backend.services.ark_client import ArkClient, ArkClientError
from backend.skills.skill_registry import SkillRegistry


ResearchScope = Literal["financials", "financial_risk", "full_dossier"]


class ResearchSkillSelection(BaseModel):
    skill_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    scope: ResearchScope


class ResearchSkillPlan(BaseModel):
    selected_skills: list[ResearchSkillSelection] = Field(
        default_factory=list,
        max_length=1,
    )
    mode: Literal["market", "skills"]
    fallback_used: bool = False


class ResearchSkillPlanner:
    """Select the minimal Research-owned Skill set, or retain market analysis."""

    def __init__(
        self,
        *,
        registry: SkillRegistry,
        ark_client: ArkClient | None = None,
    ) -> None:
        self.registry = registry
        self.ark_client = ark_client

    def create_plan(self, task: ExpertTask) -> ResearchSkillPlan:
        allowed = self.registry.prompt_payload(AgentId.RESEARCH.value)
        candidate = _deterministic_scope(task)
        if candidate is None:
            return ResearchSkillPlan(mode="market")

        fallback = _skill_plan(candidate, fallback_used=True)
        if self.ark_client is None:
            return _validate_plan(fallback, allowed, skill_required=True)

        raw = ""
        try:
            raw = self.ark_client.chat(_planner_prompt(task, allowed, candidate))
            return _parse_plan(raw, allowed, skill_required=True)
        except (ArkClientError, json.JSONDecodeError, ValidationError, ValueError):
            try:
                repaired = self.ark_client.chat(
                    _repair_prompt(task, allowed, raw, candidate)
                )
                return _parse_plan(repaired, allowed, skill_required=True)
            except (
                ArkClientError,
                json.JSONDecodeError,
                ValidationError,
                ValueError,
            ):
                return _validate_plan(fallback, allowed, skill_required=True)


def _deterministic_scope(task: ExpertTask) -> ResearchScope | None:
    explicit = task.inputs.get("scope")
    if isinstance(explicit, list):
        explicit = explicit[0] if len(explicit) == 1 else None
    if explicit in {"financials", "financial_risk", "full_dossier"}:
        return explicit
    if isinstance(explicit, list) and "financials" in explicit:
        return "financials"

    text = " ".join(
        (
            task.objective,
            task.original_user_request,
            str(task.inputs.get("research_goal", "")),
            " ".join(
                str(item)
                for item in task.inputs.get("focus", [])
                if isinstance(item, str)
            ),
        )
    ).lower()
    full_markers = (
        "全面尽调",
        "个股尽调",
        "完整尽调",
        "full dossier",
        "full_dossier",
        "全面分析",
        "基本面和潜在风险",
    )
    financial_markers = (
        "财报",
        "财务报表",
        "财务表现",
        "基本面",
        "盈利质量",
        "现金流质量",
        "偿债能力",
        "审计意见",
        "业绩预告",
        "financial statement",
        "fundamental",
    )
    risk_markers = (
        "财务风险",
        "财务异常",
        "财务健康",
        "financial risk",
        "financial_risk",
    )
    if any(marker in text for marker in full_markers):
        return "full_dossier"
    if any(marker in text for marker in risk_markers):
        return "financial_risk"
    if any(marker in text for marker in financial_markers):
        return "financials"
    return None


def _skill_plan(
    scope: ResearchScope,
    *,
    fallback_used: bool,
) -> ResearchSkillPlan:
    return ResearchSkillPlan(
        selected_skills=[
            ResearchSkillSelection(
                skill_id="a_share_stock_dossier",
                reason="当前任务需要单公司财务或基本面证据。",
                scope=scope,
            )
        ],
        mode="skills",
        fallback_used=fallback_used,
    )


def _parse_plan(
    raw: str,
    allowed: list[dict[str, Any]],
    *,
    skill_required: bool,
) -> ResearchSkillPlan:
    text = raw.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
    plan = ResearchSkillPlan.model_validate(json.loads(text))
    return _validate_plan(plan, allowed, skill_required=skill_required)


def _validate_plan(
    plan: ResearchSkillPlan,
    allowed: list[dict[str, Any]],
    *,
    skill_required: bool,
) -> ResearchSkillPlan:
    allowed_ids = {item["id"] for item in allowed}
    selected = [item.skill_id for item in plan.selected_skills]
    if len(selected) != len(set(selected)):
        raise ValueError("Research Skill Plan contains duplicate Skills")
    if not set(selected).issubset(allowed_ids):
        raise ValueError("Research planner selected an unauthorized Skill")
    if skill_required and selected != ["a_share_stock_dossier"]:
        raise ValueError("Financial Research requires the approved dossier Skill")
    if plan.mode == "market" and selected:
        raise ValueError("Market mode cannot include a dossier Skill")
    if plan.mode == "skills" and not selected:
        raise ValueError("Skill mode requires a selected Skill")
    return plan


def _planner_prompt(
    task: ExpertTask,
    allowed: list[dict[str, Any]],
    fallback_scope: ResearchScope,
) -> str:
    context = {
        "objective": task.objective,
        "original_user_request": task.original_user_request,
        "inputs": task.inputs,
    }
    return f"""
你是 AlphaOS Research Agent 内部的 Skill Planner，不是 Manager。
只能看到并选择下列 Research-owned、enabled Skills，最多选择一个最小充分 Skill。
财报请求使用 financials；财务异常筛查使用 financial_risk；全面尽调使用 full_dossier。
不得选择 Quant-owned Skill，不得加入固定 Agent 流程。
只返回严格 JSON，并符合 ResearchSkillPlan Schema。

安全降级建议 scope：{fallback_scope}
allowed Skills：{json.dumps(allowed, ensure_ascii=False)}
Schema：{json.dumps(ResearchSkillPlan.model_json_schema(), ensure_ascii=False)}
任务：{json.dumps(context, ensure_ascii=False)}
""".strip()


def _repair_prompt(
    task: ExpertTask,
    allowed: list[dict[str, Any]],
    raw: str,
    fallback_scope: ResearchScope,
) -> str:
    return f"""
上一次 Research Skill Plan 无效。仅修复一次，只返回严格 JSON。
只能选择：{json.dumps([item["id"] for item in allowed])}。
当前任务至少需要 a_share_stock_dossier，scope 可为 financials、
financial_risk 或 full_dossier；安全 scope 为 {fallback_scope}。
任务：{task.objective}
无效输出：{raw[:20_000]}
""".strip()
