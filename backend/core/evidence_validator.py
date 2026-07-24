"""Evidence validation between DAG execution and result aggregation."""

from __future__ import annotations

from typing import Any, Mapping

from pydantic import BaseModel, Field

from backend.core.contracts import ExecutionPlan, ExpertResult, ValidationStatus
from backend.core.personal_constraint_evaluator import PersonalConstraintResult
from backend.core.task_spec import TaskSpec


VALIDATION_DETAILS: dict[ValidationStatus, tuple[str, str]] = {
    ValidationStatus.RESEARCH_DRAFT: (
        "研究草稿",
        "已形成研究判断或假设，但尚未完成可证明稳定性的验证。",
    ),
    ValidationStatus.COMPUTED_NOT_VALIDATED: (
        "已计算，尚未验证",
        "已完成公式计算，但尚不能证明具有稳定预测能力。",
    ),
    ValidationStatus.HISTORICALLY_ANALYZED: (
        "已完成历史分析",
        "已分析指定历史数据，但历史事实不能直接推断未来表现。",
    ),
    ValidationStatus.HISTORICALLY_TESTED: (
        "已完成历史测试",
        "已完成明确规则下的历史测试，仍不代表未来表现。",
    ),
    ValidationStatus.OUT_OF_SAMPLE_TESTED: (
        "已完成样本外测试",
        "已完成声明范围内的样本外检验，仍需关注稳定性和市场变化。",
    ),
    ValidationStatus.STRESS_TESTED: (
        "已完成压力测试",
        "已完成声明情景下的压力测试，不代表覆盖所有失效情景。",
    ),
    ValidationStatus.INSUFFICIENT_EVIDENCE: (
        "证据不足",
        "现有数据或成功结果不足，无法形成可靠判断。",
    ),
    ValidationStatus.UNAVAILABLE: (
        "当前不可用",
        "所需数据、方法或服务当前不可用。",
    ),
}


class EvidenceItem(BaseModel):
    source_step: str
    text: str
    evidence_type: str


class EvidenceValidationResult(BaseModel):
    overall_validation_status: ValidationStatus
    validated_results: dict[str, ExpertResult] = Field(default_factory=dict)
    assumptions: list[EvidenceItem] = Field(default_factory=list)
    risks: list[EvidenceItem] = Field(default_factory=list)
    limitations: list[EvidenceItem] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    data_scope: list[dict[str, Any]] = Field(default_factory=list)
    personal_constraints: PersonalConstraintResult | None = None


class EvidenceValidator:
    """Validate traceability and evidence boundaries without changing facts."""

    def validate(
        self,
        task_spec: TaskSpec,
        plan: ExecutionPlan,
        results: Mapping[str, ExpertResult],
    ) -> EvidenceValidationResult:
        step_by_id = {step.id: step for step in plan.steps}
        normalized = {
            step_id: ExpertResult.model_validate(result)
            for step_id, result in results.items()
        }
        missing: list[str] = []
        warnings: list[str] = []
        conflicts: list[str] = []
        validated: dict[str, ExpertResult] = {}
        assumptions: list[EvidenceItem] = []
        risks: list[EvidenceItem] = []
        limitations: list[EvidenceItem] = []
        data_scope: list[dict[str, Any]] = []
        statuses: list[ValidationStatus] = []
        personal_constraints = (
            plan.personal_context.constraints
            if plan.personal_context is not None
            else None
        )

        if task_spec.task_type == "personal_investment_decision":
            if personal_constraints is None:
                missing.append("个人投资决策缺少确定性的个人约束证据")
            else:
                warnings.extend(personal_constraints.warnings)
                if personal_constraints.status == "insufficient_information":
                    missing.append("个人约束评估缺少本次任务的关键画像字段")

        for step_id in normalized.keys() - step_by_id.keys():
            warnings.append(f"忽略计划外结果：{step_id}")
        for step in plan.steps:
            result = normalized.get(step.id)
            if result is None:
                missing.append(f"{step.id}: 计划步骤没有返回结果")
                continue
            if result.agent != step.agent:
                missing.append(f"{step.id}: 返回结果的 Agent 与计划不一致")
                continue
            validated[step.id] = result
            if result.status != "completed":
                missing.append(f"{step.id}: {result.error or result.summary or '步骤未完成'}")
                statuses.append(ValidationStatus.UNAVAILABLE)
            elif not result.evidence and not result.summary.strip():
                missing.append(f"{step.id}: completed 结果缺少最低必要证据")

            status = _result_status(result, task_spec)
            statuses.append(status)
            assumptions.extend(
                EvidenceItem(
                    source_step=step.id,
                    text=item,
                    evidence_type="assumption",
                )
                for item in result.assumptions
                if item
            )
            risks.extend(
                EvidenceItem(
                    source_step=step.id,
                    text=item,
                    evidence_type="risk",
                )
                for item in result.risks
                if item
            )
            limitations.extend(
                EvidenceItem(
                    source_step=step.id,
                    text=item,
                    evidence_type="limitation",
                )
                for item in result.limitations
                if item
            )
            data_scope.extend(
                {"source_step": step.id, **source}
                for source in result.data_sources
                if isinstance(source, dict) and source
            )
            conflicts.extend(_string_list(result.metadata.get("conflicts")))

            cited_steps = _find_values(result.evidence, "source_step")
            allowed_upstream = set(step.depends_on)
            for cited in cited_steps:
                if cited not in step_by_id:
                    conflicts.append(f"{step.id} 引用了不存在的上游步骤 {cited}")
                elif cited not in allowed_upstream and cited != step.id:
                    warnings.append(f"{step.id} 引用了未声明依赖的步骤 {cited}")

            risky_text = " ".join([result.summary, *result.recommendations])
            if status in {
                ValidationStatus.RESEARCH_DRAFT,
                ValidationStatus.COMPUTED_NOT_VALIDATED,
            } and any(
                phrase in risky_text
                for phrase in ("预测能力已验证", "验证有效", "稳定获利", "可实盘")
            ):
                warnings.append(f"{step.id}: 未验证结果被表述为具有预测或实盘能力")

        if not data_scope and any(
            result.status == "completed" for result in validated.values()
        ):
            warnings.append("已完成结果未声明数据范围")
        if task_spec.evidence_requirements and not validated:
            missing.extend(
                f"缺少任务要求的证据：{item}"
                for item in task_spec.evidence_requirements
            )

        overall = _overall_status(statuses, missing)
        return EvidenceValidationResult(
            overall_validation_status=overall,
            validated_results=validated,
            assumptions=_unique_items(assumptions),
            risks=_unique_items(risks),
            limitations=_unique_items(limitations),
            conflicts=list(dict.fromkeys(conflicts)),
            missing_evidence=list(dict.fromkeys(missing)),
            warnings=list(dict.fromkeys(warnings)),
            data_scope=_unique_dicts(data_scope),
            personal_constraints=personal_constraints,
        )


_STATUS_ALIASES = {
    "unverified": ValidationStatus.RESEARCH_DRAFT,
    "research_draft": ValidationStatus.RESEARCH_DRAFT,
    "computed_not_validated": ValidationStatus.COMPUTED_NOT_VALIDATED,
    "historically_analyzed": ValidationStatus.HISTORICALLY_ANALYZED,
    "historically_tested": ValidationStatus.HISTORICALLY_TESTED,
    "out_of_sample_tested": ValidationStatus.OUT_OF_SAMPLE_TESTED,
    "stress_tested": ValidationStatus.STRESS_TESTED,
    "insufficient_data": ValidationStatus.INSUFFICIENT_EVIDENCE,
    "insufficient_evidence": ValidationStatus.INSUFFICIENT_EVIDENCE,
    "unavailable": ValidationStatus.UNAVAILABLE,
}


def _result_status(result: ExpertResult, task_spec: TaskSpec) -> ValidationStatus:
    raw = result.metadata.get("validation_status")
    if not isinstance(raw, str):
        found = _find_values(result.evidence, "validation_status")
        raw = found[0] if found else None
    if isinstance(raw, str) and raw in _STATUS_ALIASES:
        return _STATUS_ALIASES[raw]
    if result.status != "completed":
        return ValidationStatus.UNAVAILABLE
    if task_spec.task_type in {"market_research", "historical_analysis", "company_research"}:
        return ValidationStatus.HISTORICALLY_ANALYZED
    return ValidationStatus.RESEARCH_DRAFT


def _overall_status(
    statuses: list[ValidationStatus],
    missing: list[str],
) -> ValidationStatus:
    if not statuses:
        return ValidationStatus.INSUFFICIENT_EVIDENCE
    if all(status == ValidationStatus.UNAVAILABLE for status in statuses):
        return ValidationStatus.UNAVAILABLE
    if missing and not any(
        status
        in {
            ValidationStatus.COMPUTED_NOT_VALIDATED,
            ValidationStatus.HISTORICALLY_ANALYZED,
            ValidationStatus.HISTORICALLY_TESTED,
            ValidationStatus.OUT_OF_SAMPLE_TESTED,
            ValidationStatus.STRESS_TESTED,
        }
        for status in statuses
    ):
        return ValidationStatus.INSUFFICIENT_EVIDENCE
    order = [
        ValidationStatus.INSUFFICIENT_EVIDENCE,
        ValidationStatus.UNAVAILABLE,
        ValidationStatus.RESEARCH_DRAFT,
        ValidationStatus.COMPUTED_NOT_VALIDATED,
        ValidationStatus.HISTORICALLY_ANALYZED,
        ValidationStatus.HISTORICALLY_TESTED,
        ValidationStatus.OUT_OF_SAMPLE_TESTED,
        ValidationStatus.STRESS_TESTED,
    ]
    return min(statuses, key=order.index)


def _find_values(value: Any, key: str) -> list[str]:
    found: list[str] = []
    if isinstance(value, list):
        for item in value:
            found.extend(_find_values(item, key))
    elif isinstance(value, dict):
        for child_key, child in value.items():
            if child_key == key and isinstance(child, str):
                found.append(child)
            found.extend(_find_values(child, key))
    return found


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _unique_items(items: list[EvidenceItem]) -> list[EvidenceItem]:
    seen: set[tuple[str, str]] = set()
    output: list[EvidenceItem] = []
    for item in items:
        key = (item.source_step, item.text)
        if key not in seen:
            seen.add(key)
            output.append(item)
    return output


def _unique_dicts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for item in items:
        key = repr(sorted(item.items()))
        if key not in seen:
            seen.add(key)
            output.append(item)
    return output
