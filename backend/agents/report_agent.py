"""Optional Report Agent that only integrates declared dependency results."""

from __future__ import annotations

import json

from backend.core.contracts import (
    AgentId,
    ExpertResult,
    ExpertTask,
    RESEARCH_DISCLAIMER,
)
from backend.services.ark_client import ArkClient, ArkClientError


class ReportAgent:
    """Turn existing expert results into a formal, traceable report."""

    def __init__(self, ark_client: ArkClient | None = None) -> None:
        self._ark_client = ark_client

    def execute(self, task: ExpertTask) -> ExpertResult:
        if task.agent != AgentId.REPORT:
            return _failed(task, "Report Agent 收到了不匹配的任务类型。")
        if not task.dependency_results:
            return _failed(task, "Report Agent 需要至少一个已声明的上游专家结果。")

        successful = {
            step_id: result
            for step_id, result in task.dependency_results.items()
            if result.status == "completed"
        }
        if not successful:
            return _failed(task, "Report Agent 没有可整合的成功上游结果。")

        payload = {
            step_id: result.model_dump(mode="json")
            for step_id, result in successful.items()
        }
        execution_path = _execution_path(successful)
        report = _fallback_report(task, successful, execution_path)
        limitations = [
            limitation
            for result in successful.values()
            for limitation in result.limitations
        ]
        try:
            generated = self._get_ark_client().chat(
                _report_prompt(task, payload, execution_path)
            ).strip()
            if generated:
                report = generated
        except (ArkClientError, Exception):
            limitations.append(
                "Ark 报告生成服务不可用；当前报告由已有结构化结果降级编排。"
            )
        if RESEARCH_DISCLAIMER not in report:
            report = f"{report}\n\n{RESEARCH_DISCLAIMER}"

        return ExpertResult(
            task_id=task.task_id,
            agent=AgentId.REPORT,
            status="completed",
            summary=report,
            evidence=[
                {
                    "source_step": step_id,
                    "source_agent": result.agent.value,
                    "summary": result.summary,
                    "evidence": result.evidence,
                }
                for step_id, result in successful.items()
            ],
            assumptions=[
                assumption
                for result in successful.values()
                for assumption in result.assumptions
            ],
            risks=[
                risk for result in successful.values() for risk in result.risks
            ],
            limitations=limitations,
            recommendations=[
                recommendation
                for result in successful.values()
                for recommendation in result.recommendations
            ],
            data_sources=[
                {"source_step": step_id, **source}
                for step_id, result in successful.items()
                for source in result.data_sources
            ],
            metadata={
                "execution_path": execution_path,
                "integrated_steps": list(successful),
                "report": report,
                "disclaimer": RESEARCH_DISCLAIMER,
            },
        )

    def __call__(self, task: ExpertTask) -> ExpertResult:
        return self.execute(task)

    def _get_ark_client(self) -> ArkClient:
        if self._ark_client is None:
            self._ark_client = ArkClient()
        return self._ark_client


def _report_prompt(
    task: ExpertTask,
    payload: dict[str, dict[str, object]],
    execution_path: list[str],
) -> str:
    context = {
        "research_objective": task.objective,
        "actual_execution_path": execution_path,
        "dependency_results": payload,
    }
    return f"""
你是 AlphaOS Report Agent，只能整合以下已执行专家结果，不得添加新的研究事实。
报告必须包含：研究目标、实际执行专家与路径、数据范围、核心发现、量化证据、
风险审查、假设与限制、结论及必要风险提示。若某部分无证据，请明确写“未提供”。
末尾必须原样包含：{RESEARCH_DISCLAIMER}

结构化上下文：
{json.dumps(context, ensure_ascii=False)}
""".strip()


def _fallback_report(
    task: ExpertTask,
    successful: dict[str, ExpertResult],
    execution_path: list[str],
) -> str:
    findings = "\n".join(
        f"- {step_id}（{result.agent.value}）：{result.summary}"
        for step_id, result in successful.items()
    )
    risks = [
        risk for result in successful.values() for risk in result.risks
    ]
    limitations = [
        item for result in successful.values() for item in result.limitations
    ]
    return (
        f"# 研究报告\n\n"
        f"## 研究目标\n{task.objective}\n\n"
        f"## 执行专家和实际路径\n{' → '.join(execution_path)}\n\n"
        f"## 数据范围与核心发现\n{findings}\n\n"
        f"## 量化证据\n已保留于结构化 evidence 字段。\n\n"
        f"## 风险审查\n{_bullets(risks)}\n\n"
        f"## 假设与限制\n{_bullets(limitations)}\n\n"
        f"## 结论\n以上结论仅整合实际完成的上游结果。\n\n"
        f"{RESEARCH_DISCLAIMER}"
    )


def _execution_path(successful: dict[str, ExpertResult]) -> list[str]:
    """Recover direct and cited upstream lineage without inventing plan nodes."""

    path: list[str] = []
    for step_id, result in successful.items():
        for item in result.evidence:
            source_step = item.get("source_step")
            source_agent = item.get("source_agent")
            if source_step and source_agent:
                entry = f"{source_step}:{source_agent}"
                if entry not in path:
                    path.append(entry)
        entry = f"{step_id}:{result.agent.value}"
        if entry not in path:
            path.append(entry)
    return path


def _bullets(values: list[str]) -> str:
    return "\n".join(f"- {value}" for value in values) if values else "- 未提供"


def _failed(task: ExpertTask, error: str) -> ExpertResult:
    return ExpertResult(
        task_id=task.task_id,
        agent=AgentId.REPORT,
        status="failed",
        summary="Report Agent 未能生成报告。",
        limitations=[error],
        error=error,
    )
