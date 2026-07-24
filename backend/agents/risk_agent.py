"""Risk Agent supporting independent and dependency-based review."""

from __future__ import annotations

import json
from typing import Any

from backend.core.contracts import AgentId, ExpertResult, ExpertTask
from backend.services.ark_client import ArkClient, ArkClientError


class RiskAgent:
    """Challenge assumptions without inventing missing evidence."""

    def __init__(self, ark_client: ArkClient | None = None) -> None:
        self._ark_client = ark_client

    def execute(self, task: ExpertTask) -> ExpertResult:
        if task.agent != AgentId.RISK:
            return _failed(task, "Risk Agent 收到了不匹配的任务类型。")

        dependency_evidence = _dependency_evidence(task.dependency_results)
        independent_context = {
            key: value
            for key, value in task.inputs.items()
            if value not in (None, "", [], {})
        }
        if not dependency_evidence and not independent_context and not task.objective:
            return _failed(task, "Risk Agent 缺少可审查的策略、观点或上游证据。")

        risk_mode = _resolve_risk_mode(task)
        assessment = _assess(
            task,
            dependency_evidence,
            independent_context,
            risk_mode,
        )
        summary = _fallback_summary(assessment, risk_mode)
        limitations = list(assessment["missing_evidence"])
        if risk_mode != "personal_capacity":
            try:
                explanation = self._get_ark_client().chat(
                    _risk_prompt(task, dependency_evidence, assessment, risk_mode)
                ).strip()
                if explanation:
                    summary = explanation
            except (ArkClientError, Exception):
                limitations.append(
                    "Ark 风险解释服务不可用；风险清单由结构化证据规则降级生成。"
                )

        return ExpertResult(
            task_id=task.task_id,
            agent=AgentId.RISK,
            status="completed",
            summary=summary,
            evidence=dependency_evidence,
            assumptions=assessment["challenged_assumptions"],
            risks=assessment["risk_factors"],
            limitations=limitations,
            recommendations=assessment["recommended_follow_up"],
            data_sources=_dependency_sources(task.dependency_results),
            metadata={
                **assessment,
                "risk_mode": risk_mode,
                "mode": "dependency" if task.dependency_results else "independent",
                "fact_judgment_boundary": {
                    "facts": dependency_evidence,
                    "model_judgment": assessment["risk_factors"],
                    "unknowns": assessment["missing_evidence"],
                },
            },
        )

    def __call__(self, task: ExpertTask) -> ExpertResult:
        return self.execute(task)

    def _get_ark_client(self) -> ArkClient:
        if self._ark_client is None:
            self._ark_client = ArkClient()
        return self._ark_client


def _dependency_evidence(
    dependencies: dict[str, ExpertResult],
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for step_id, result in dependencies.items():
        for item in result.evidence:
            evidence.append(
                {
                    "source_step": step_id,
                    "source_agent": result.agent.value,
                    "fact": item,
                    "upstream_assumptions": result.assumptions,
                    "upstream_limitations": result.limitations,
                    "validation_status": result.metadata.get(
                        "validation_status",
                        item.get("validation_status")
                        if isinstance(item, dict)
                        else None,
                    ),
                    "provenance": result.metadata.get("provenance", []),
                }
            )
    return evidence


def _dependency_sources(
    dependencies: dict[str, ExpertResult],
) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for step_id, result in dependencies.items():
        for item in result.data_sources:
            sources.append({"source_step": step_id, **item})
    return sources


def _assess(
    task: ExpertTask,
    evidence: list[dict[str, Any]],
    context: dict[str, Any],
    risk_mode: str | None,
) -> dict[str, Any]:
    if risk_mode == "personal_capacity":
        return _assess_personal_capacity(context)
    if risk_mode not in {"strategy_risk", "market_risk"}:
        return {
            "risk_level": "unable_to_grade",
            "risk_factors": [],
            "challenged_assumptions": [],
            "missing_evidence": ["风险模式或可审查证据不足，无法可靠分级。"],
            "failure_scenarios": [],
            "recommended_follow_up": ["请明确需要审查个人承受能力、策略风险或市场风险。"],
            "reviewed_context": {},
        }

    risk_factors: list[str] = []
    if risk_mode == "strategy_risk":
        challenged = [
            "历史样本中的关系能够延续到未来市场环境。",
            "当前策略描述足以覆盖交易成本、容量和执行约束。",
        ]
        missing = [
            "缺少样本外验证和不同市场状态下的稳健性证据。",
            "缺少交易成本、滑点、容量与流动性约束数据。",
        ]
        failure_scenarios = [
            "市场状态切换导致历史信号失效。",
            "换手和冲击成本吞噬名义收益。",
        ]
    else:
        challenged = ["历史市场状态能够代表未来可能出现的风险环境。"]
        missing = ["缺少极端行情、流动性收缩和宏观冲击情景证据。"]
        failure_scenarios = [
            "市场状态切换使历史波动和相关性失去代表性。",
            "极端行情下流动性下降并放大价格波动。",
        ]

    max_drawdowns: list[float] = []
    volatilities: list[float] = []
    observation_counts: list[int] = []
    factor_coverages: list[float] = []
    unverified_factors: list[str] = []
    for cited in evidence:
        fact = cited.get("fact", {})
        if not isinstance(fact, dict):
            continue
        if isinstance(fact.get("maximum_drawdown"), (int, float)):
            max_drawdowns.append(float(fact["maximum_drawdown"]))
        if isinstance(fact.get("daily_volatility"), (int, float)):
            volatilities.append(float(fact["daily_volatility"]))
        if isinstance(fact.get("observation_count"), int):
            observation_counts.append(fact["observation_count"])
        factor_data = fact.get("data", {})
        if isinstance(factor_data, dict):
            if isinstance(factor_data.get("coverage_ratio"), (int, float)):
                factor_coverages.append(float(factor_data["coverage_ratio"]))
            factor_id = factor_data.get("factor_id") or fact.get("skill_id")
            validation_status = (
                fact.get("validation_status")
                or factor_data.get("validation_status")
                or cited.get("validation_status")
            )
            if validation_status in {
                "unverified",
                "computed_not_validated",
                "mixed_unvalidated",
            }:
                unverified_factors.append(str(factor_id or "quant factor"))

    if max_drawdowns:
        worst = min(max_drawdowns)
        risk_factors.append(f"上游证据显示样本内最大回撤为 {worst:.2%}。")
    if volatilities:
        peak_vol = max(volatilities)
        risk_factors.append(f"上游证据显示最高日波动率为 {peak_vol:.2%}。")
    if observation_counts and min(observation_counts) < 60:
        risk_factors.append(
            f"最小样本仅 {min(observation_counts)} 个观测，统计稳定性有限。"
        )
    if factor_coverages:
        risk_factors.append(
            f"上游因子计算的最低非空覆盖率为 {min(factor_coverages):.2%}。"
        )
    if unverified_factors and risk_mode == "strategy_risk":
        risk_factors.append(
            "上游结果明确标记为尚未验证有效性："
            + "、".join(dict.fromkeys(unverified_factors))
            + "。"
        )
        missing.append("缺少因子 IC、样本外和回测有效性证据。")
    if not evidence and risk_mode == "strategy_risk":
        risk_factors.extend(
            [
                "策略可能对参数、样本区间和市场状态高度敏感。",
                "高换手特征会放大交易成本与执行偏差。",
                "成交量信号可能受流动性骤降和拥挤交易影响。",
            ]
        )
        missing.insert(0, "当前为独立审查，未提供可引用的市场数据证据。")
    elif not evidence:
        risk_factors.extend(
            [
                "历史波动可能低估极端行情下的实际风险。",
                "市场流动性下降可能放大价格冲击和退出难度。",
                "宏观环境变化可能使历史市场状态失去代表性。",
            ]
        )
        missing.insert(0, "当前未提供可引用的市场数据或情景证据。")

    level = "unable_to_grade" if not risk_factors else "medium"
    if (max_drawdowns and min(max_drawdowns) <= -0.2) or (
        observation_counts and min(observation_counts) < 30
    ):
        level = "high"
    elif evidence and max_drawdowns and min(max_drawdowns) > -0.08:
        level = "low"

    return {
        "risk_level": level,
        "risk_factors": risk_factors,
        "challenged_assumptions": challenged,
        "missing_evidence": missing,
        "failure_scenarios": failure_scenarios,
        "recommended_follow_up": (
            [
                "补充样本外、滚动窗口和市场状态分层检验。",
                "将手续费、滑点、冲击成本和容量约束纳入验证。",
            ]
            if risk_mode == "strategy_risk"
            else [
                "补充极端行情、流动性收缩和宏观冲击情景。",
                "核对数据覆盖范围及其对波动判断的限制。",
            ]
        ),
        "reviewed_context": context,
    }


def _assess_personal_capacity(context: dict[str, Any]) -> dict[str, Any]:
    summary = context.get("risk_context")
    if not isinstance(summary, dict):
        summary = {}
    constraints = summary.get("constraints")
    if not isinstance(constraints, list):
        constraints = []
    risk_factors = [
        str(item.get("statement"))
        for item in constraints
        if isinstance(item, dict) and item.get("statement")
    ]
    status = summary.get("status")
    capacity = summary.get("capacity_level")
    missing = [
        "个人约束评估缺少本次任务的关键画像字段。"
    ] if status == "insufficient_information" else []
    return {
        "risk_level": (
            "unable_to_grade"
            if capacity == "unable_to_grade"
            else "high"
            if capacity == "low"
            else "medium"
            if capacity == "medium"
            else "low"
            if capacity == "high"
            else "unable_to_grade"
        ),
        "capacity_level": capacity or "unable_to_grade",
        "risk_factors": risk_factors,
        "challenged_assumptions": [
            "个人约束只能限制结论边界，不能证明任何产品适合用户。"
        ],
        "missing_evidence": missing,
        "failure_scenarios": [],
        "recommended_follow_up": (
            ["补充本次任务仍缺失的关键画像字段。"]
            if missing
            else ["将个人约束与实际产品风险证据分开核对。"]
        ),
        "reviewed_context": {
            "constraint_codes": [
                item.get("code")
                for item in constraints
                if isinstance(item, dict) and item.get("code")
            ],
            "fields_used": summary.get("fields_used", []),
            "missing_critical_fields": summary.get(
                "missing_critical_fields", []
            ),
        },
    }


def _resolve_risk_mode(task: ExpertTask) -> str | None:
    explicit = task.inputs.get("risk_mode")
    if explicit in {"personal_capacity", "strategy_risk", "market_risk"}:
        return str(explicit)
    context = task.inputs.get("risk_context")
    if isinstance(context, dict) and (
        "capacity_level" in context or "constraints" in context
    ):
        return "personal_capacity"
    if task.inputs.get("strategy") or task.inputs.get("thesis"):
        return "strategy_risk"
    upstream_agents = {result.agent for result in task.dependency_results.values()}
    if AgentId.QUANT in upstream_agents:
        return "strategy_risk"
    if upstream_agents & {AgentId.RESEARCH, AgentId.MACRO}:
        return "market_risk"
    return None


def _fallback_summary(
    assessment: dict[str, Any],
    risk_mode: str | None,
) -> str:
    level = assessment["risk_level"]
    count = len(assessment["risk_factors"])
    if level == "unable_to_grade":
        return "现有信息不足，无法对本次风险进行可靠分级。"
    if risk_mode == "personal_capacity":
        return f"个人约束评估识别出 {count} 项需要纳入结论边界的约束。"
    return f"风险等级为 {level}；识别出 {count} 个主要风险因素。"


def _risk_prompt(
    task: ExpertTask,
    evidence: list[dict[str, Any]],
    assessment: dict[str, Any],
    risk_mode: str | None,
) -> str:
    payload = {
        "objective": task.objective,
        "risk_mode": risk_mode,
        "cited_dependency_evidence": evidence,
        "deterministic_assessment": assessment,
    }
    return f"""
你是 AlphaOS Risk Agent。严格遵守 risk_mode 的分析边界，基于给定结构化事实解释风险，不得重复冒充 Research
结论，不得补造事实。明确区分数据事实、风险判断与未知信息，并引用 source_step。
不要给出买入卖出建议。用简洁中文返回风险摘要。

风险上下文：
{json.dumps(payload, ensure_ascii=False)}
""".strip()


def _failed(task: ExpertTask, error: str) -> ExpertResult:
    return ExpertResult(
        task_id=task.task_id,
        agent=AgentId.RISK,
        status="failed",
        summary="Risk Agent 未能完成风险审查。",
        limitations=[error],
        error=error,
    )
