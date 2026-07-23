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

        assessment = _assess(task, dependency_evidence, independent_context)
        summary = (
            f"风险等级为 {assessment['risk_level']}；"
            f"识别出 {len(assessment['risk_factors'])} 个主要风险因素。"
        )
        limitations = list(assessment["missing_evidence"])
        try:
            explanation = self._get_ark_client().chat(
                _risk_prompt(task, dependency_evidence, assessment)
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
) -> dict[str, Any]:
    risk_factors: list[str] = []
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

    max_drawdowns: list[float] = []
    volatilities: list[float] = []
    observation_counts: list[int] = []
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
    if not evidence:
        risk_factors.extend(
            [
                "策略可能对参数、样本区间和市场状态高度敏感。",
                "高换手特征会放大交易成本与执行偏差。",
                "成交量信号可能受流动性骤降和拥挤交易影响。",
            ]
        )
        missing.insert(0, "当前为独立审查，未提供可引用的市场数据证据。")

    level = "medium"
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
        "recommended_follow_up": [
            "补充样本外、滚动窗口和市场状态分层检验。",
            "将手续费、滑点、冲击成本和容量约束纳入验证。",
        ],
        "reviewed_context": context,
    }


def _risk_prompt(
    task: ExpertTask,
    evidence: list[dict[str, Any]],
    assessment: dict[str, Any],
) -> str:
    payload = {
        "objective": task.objective,
        "cited_dependency_evidence": evidence,
        "deterministic_assessment": assessment,
    }
    return f"""
你是 AlphaOS Risk Agent。请基于给定结构化事实解释风险，不得重复冒充 Research
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
