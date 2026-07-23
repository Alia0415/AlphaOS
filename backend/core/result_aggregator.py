"""Deterministic, evidence-bounded user-facing result aggregation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from backend.core.contracts import (
    AggregationResult,
    AnalysisStep,
    DirectAnswer,
    ExecutionPlan,
    ExecutionSummary,
    ExpertResult,
    RESEARCH_DISCLAIMER,
    ResultBlock,
    TechnicalEvidence,
)
from backend.core.plain_language import metric_card, plain_text, validation_label


_METRIC_FIELDS = {
    "maximum_drawdown",
    "annualized_volatility",
    "daily_volatility",
    "period_return",
    "coverage_ratio",
    "observation_count",
    "non_null_count",
    "highest_close",
    "lowest_close",
    "average_volume",
}
_UNVALIDATED_STATUSES = {
    "unverified",
    "computed_not_validated",
    "mixed_unvalidated",
}
CompletionStatus = Literal[
    "completed",
    "partially_completed",
    "needs_clarification",
    "failed",
]
OutputMode = Literal[
    "direct_answer",
    "data_analysis",
    "idea_generation",
    "risk_review",
    "comparison",
    "formal_report",
    "clarification",
    "failure",
]
Confidence = Literal["high", "medium", "low", "not_applicable"]
Stance = Literal[
    "positive",
    "cautiously_positive",
    "neutral",
    "mixed",
    "cautiously_negative",
    "negative",
    "insufficient_evidence",
    "not_applicable",
]
BlockType = Literal[
    "finding_cards",
    "metric_cards",
    "comparison",
    "risk_list",
    "factor_list",
    "action_list",
    "limitations",
    "clarification",
    "failure_notice",
    "narrative",
    "report",
    "data_scope",
]
Importance = Literal["primary", "secondary", "supporting"]


@dataclass
class EvidenceProfile:
    """Normalized feature inventory; agent identity never selects page sections."""

    completed: dict[str, ExpertResult] = field(default_factory=dict)
    failed: dict[str, ExpertResult] = field(default_factory=dict)
    blocked: dict[str, ExpertResult] = field(default_factory=dict)
    validation_statuses: dict[str, str] = field(default_factory=dict)
    metrics: list[dict[str, Any]] = field(default_factory=list)
    comparisons: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    factor_candidates: list[dict[str, Any]] = field(default_factory=list)
    factor_shortlist: list[str] = field(default_factory=list)
    reports: list[tuple[str, str]] = field(default_factory=list)
    summaries: list[dict[str, str]] = field(default_factory=list)
    risks: list[dict[str, str]] = field(default_factory=list)
    actions: list[dict[str, str]] = field(default_factory=list)
    limitations: list[dict[str, str]] = field(default_factory=list)
    data_scopes: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)


class ResultAggregator:
    """Answer the user from actual results without planning or invoking experts."""

    def aggregate(
        self,
        user_request: str,
        plan: ExecutionPlan,
        results: Mapping[str, ExpertResult],
    ) -> AggregationResult:
        """Create a validated, dynamic presentation contract."""

        normalized = {
            step_id: ExpertResult.model_validate(result)
            for step_id, result in results.items()
        }
        completion_status = self.determine_completion_status(plan, normalized)
        profile = self.inspect_available_evidence(normalized)
        output_mode = self.infer_output_mode(plan, profile, completion_status)
        direct_answer = self.build_direct_answer(
            plan,
            profile,
            completion_status,
            output_mode,
        )
        blocks = self.compose_content_blocks(plan, profile, completion_status)
        return AggregationResult(
            user_goal=plan.goal or user_request.strip(),
            completion_status=completion_status,
            output_mode=output_mode,
            direct_answer=direct_answer,
            content_blocks=blocks,
            execution_summary=self.build_execution_summary(plan, normalized),
            technical_evidence=self.build_technical_evidence(profile, normalized),
            disclaimer=RESEARCH_DISCLAIMER,
        )

    def determine_completion_status(
        self,
        plan: ExecutionPlan,
        results: Mapping[str, ExpertResult],
    ) -> CompletionStatus:
        if plan.needs_clarification:
            return "needs_clarification"
        expected_steps = [step.id for step in plan.steps]
        if not expected_steps:
            return "failed"
        statuses = [
            results[step_id].status if step_id in results else "missing"
            for step_id in expected_steps
        ]
        completed = statuses.count("completed")
        if completed == len(expected_steps):
            return "completed"
        if completed:
            return "partially_completed"
        return "failed"

    def inspect_available_evidence(
        self,
        results: Mapping[str, ExpertResult],
    ) -> EvidenceProfile:
        profile = EvidenceProfile()
        metric_keys: set[tuple[str, str, str]] = set()
        for step_id, result in results.items():
            getattr(profile, result.status)[step_id] = result
            status = _validation_status(result)
            if status:
                profile.validation_statuses[step_id] = status
            profile.limitations.extend(
                {"source_step": step_id, "text": plain_text(item)}
                for item in result.limitations
                if item
            )
            profile.risks.extend(
                {"source_step": step_id, "text": plain_text(item)}
                for item in result.risks
                if item
            )
            profile.actions.extend(
                {"source_step": step_id, "text": plain_text(item)}
                for item in result.recommendations
                if item
            )
            if result.status != "completed":
                continue
            if result.summary:
                profile.summaries.append(
                    {"source_step": step_id, "text": plain_text(result.summary)}
                )
            report = result.metadata.get("report")
            if isinstance(report, str) and report.strip():
                profile.reports.append((step_id, report.strip()))
            for source in result.data_sources:
                if isinstance(source, dict) and source:
                    profile.data_scopes.append(
                        {"source_step": step_id, **source}
                    )
            conflicts = result.metadata.get("conflicts", [])
            if isinstance(conflicts, list):
                profile.conflicts.extend(str(item) for item in conflicts if item)
            for evidence in result.evidence:
                if not isinstance(evidence, dict):
                    continue
                self._inspect_evidence_item(
                    evidence,
                    step_id,
                    profile,
                    metric_keys,
                )
        profile.metrics = _unique_dicts(profile.metrics)
        profile.factor_candidates = _unique_dicts(profile.factor_candidates)
        profile.factor_shortlist = list(dict.fromkeys(profile.factor_shortlist))
        profile.risks = _unique_text_items(profile.risks)
        profile.actions = _unique_text_items(profile.actions)
        profile.limitations = _unique_text_items(profile.limitations)
        profile.data_scopes = _unique_dicts(profile.data_scopes)
        profile.conflicts = list(dict.fromkeys(profile.conflicts))
        return profile

    def infer_output_mode(
        self,
        plan: ExecutionPlan,
        profile: EvidenceProfile,
        completion_status: CompletionStatus,
    ) -> OutputMode:
        if completion_status == "needs_clarification":
            return "clarification"
        if completion_status == "failed":
            return "failure"
        if profile.reports:
            return "formal_report"
        if profile.factor_candidates or profile.factor_shortlist:
            return "idea_generation"
        if len(profile.comparisons) > 1:
            return "comparison"
        if profile.risks and not profile.metrics and not profile.summaries:
            return "risk_review"
        if profile.risks and "risk" in plan.intent.lower():
            return "risk_review"
        if profile.metrics:
            return "data_analysis"
        return "direct_answer"

    def build_direct_answer(
        self,
        plan: ExecutionPlan,
        profile: EvidenceProfile,
        completion_status: CompletionStatus,
        output_mode: OutputMode,
    ) -> DirectAnswer:
        if completion_status == "needs_clarification":
            question = plan.clarification_question or "请补充完成任务所需的关键信息。"
            return DirectAnswer(
                headline="需要先补充信息",
                explanation=question,
                confidence="not_applicable",
                stance="not_applicable",
            )
        if completion_status == "failed":
            return DirectAnswer(
                headline="本次任务没有成功完成",
                explanation=(
                    "现有步骤均未产生可可靠回答问题的结果。系统没有使用模拟数据"
                    "或未验证假设来伪造结论；请查看失败说明后补充输入或稍后重试。"
                ),
                confidence="not_applicable",
                stance="insufficient_evidence",
            )

        prefix = (
            "部分分析已完成，但仍有步骤失败或受阻。"
            if completion_status == "partially_completed"
            else ""
        )
        headline, explanation = self._answer_from_profile(profile, output_mode)
        confidence = _confidence(profile, completion_status)
        stance: Stance = (
            "mixed"
            if completion_status == "partially_completed"
            else (
                "insufficient_evidence"
                if any(
                    status in _UNVALIDATED_STATUSES
                    for status in profile.validation_statuses.values()
                )
                else "neutral"
            )
        )
        return DirectAnswer(
            headline=headline,
            explanation=" ".join(part for part in (prefix, explanation) if part),
            confidence=confidence,
            stance=stance,
        )

    def compose_content_blocks(
        self,
        plan: ExecutionPlan,
        profile: EvidenceProfile,
        completion_status: CompletionStatus,
    ) -> list[ResultBlock]:
        if completion_status == "needs_clarification":
            return [
                ResultBlock(
                    id="clarification",
                    type="clarification",
                    title="需要补充的信息",
                    importance="primary",
                    source_steps=[],
                    data={
                        "question": plan.clarification_question
                        or "请补充完成任务所需的关键信息。"
                    },
                )
            ]

        blocks: list[ResultBlock] = []
        if profile.reports:
            step_id, report = profile.reports[-1]
            blocks.append(
                _block(
                    "report",
                    "report",
                    "正式研究报告",
                    [step_id],
                    {"content": report},
                    "primary",
                )
            )
        if profile.factor_candidates or profile.factor_shortlist:
            source_steps = _source_steps(
                profile.factor_candidates,
                fallback=profile.completed,
            )
            status = next(iter(profile.validation_statuses.values()), "unverified")
            blocks.append(
                _block(
                    "factor-ideas",
                    "factor_list",
                    "可验证的研究想法",
                    source_steps,
                    {
                        "items": profile.factor_candidates,
                        "shortlist": profile.factor_shortlist,
                        "validation_status": status,
                        "plain_status": validation_label(status),
                    },
                    "primary",
                )
            )
        if len(profile.comparisons) > 1:
            blocks.append(
                _block(
                    "comparison",
                    "comparison",
                    "结果对比",
                    _metric_source_steps(profile.metrics),
                    {
                        "entities": [
                            {"name": name, "metrics": metrics}
                            for name, metrics in profile.comparisons.items()
                        ]
                    },
                    "primary",
                )
            )
        if profile.metrics:
            blocks.append(
                _block(
                    "metrics",
                    "metric_cards",
                    "实际计算结果",
                    _metric_source_steps(profile.metrics),
                    {"metrics": profile.metrics},
                    "primary" if not blocks else "secondary",
                )
            )
        if profile.summaries and not profile.reports:
            block_type = "finding_cards" if len(profile.summaries) > 1 else "narrative"
            blocks.append(
                _block(
                    "findings",
                    block_type,
                    "已完成的分析",
                    _source_steps(profile.summaries),
                    {"items": profile.summaries},
                    "secondary" if blocks else "primary",
                )
            )
        if profile.risks:
            blocks.append(
                _block(
                    "risks",
                    "risk_list",
                    "实际识别的风险",
                    _source_steps(profile.risks),
                    {"items": profile.risks},
                    "secondary",
                )
            )
        if profile.actions:
            blocks.append(
                _block(
                    "actions",
                    "action_list",
                    "可继续验证的事项",
                    _source_steps(profile.actions),
                    {"items": profile.actions},
                    "supporting",
                )
            )
        if profile.data_scopes:
            blocks.append(
                _block(
                    "data-scope",
                    "data_scope",
                    "本次证据范围",
                    _source_steps(profile.data_scopes),
                    {"sources": profile.data_scopes},
                    "supporting",
                )
            )
        if profile.limitations:
            blocks.append(
                _block(
                    "limitations",
                    "limitations",
                    "目前不能确定的部分",
                    _source_steps(profile.limitations),
                    {"items": profile.limitations},
                    "supporting",
                )
            )
        if completion_status in {"partially_completed", "failed"}:
            blocks.append(self._failure_block(plan, profile))
        return [block for block in blocks if _has_content(block.data)]

    def build_execution_summary(
        self,
        plan: ExecutionPlan,
        results: Mapping[str, ExpertResult],
    ) -> ExecutionSummary:
        return ExecutionSummary(
            selected_agents=[
                selection.agent for selection in plan.selected_agents
            ],
            completed_steps=[
                step_id for step_id, result in results.items()
                if result.status == "completed"
            ],
            failed_steps=[
                step_id for step_id, result in results.items()
                if result.status == "failed"
            ],
            blocked_steps=[
                step_id for step_id, result in results.items()
                if result.status == "blocked"
            ],
            analysis_path=[
                AnalysisStep(
                    step_id=step.id,
                    agent=step.agent,
                    objective=step.objective,
                    status=(
                        results[step.id].status
                        if step.id in results
                        else "not_executed"
                    ),
                )
                for step in plan.steps
            ],
        )

    def build_technical_evidence(
        self,
        profile: EvidenceProfile,
        results: Mapping[str, ExpertResult],
    ) -> TechnicalEvidence:
        missing = [
            f"{item['source_step']}: {item['text']}"
            for item in profile.limitations
        ]
        for step_id, result in {**profile.failed, **profile.blocked}.items():
            missing.append(
                f"{step_id}: {plain_text(result.error or result.summary)}"
            )
        return TechnicalEvidence(
            validation_statuses=profile.validation_statuses,
            conflicts=profile.conflicts,
            missing_evidence=list(dict.fromkeys(missing)),
            source_results=dict(results),
        )

    def _inspect_evidence_item(
        self,
        evidence: dict[str, Any],
        step_id: str,
        profile: EvidenceProfile,
        metric_keys: set[tuple[str, str, str]],
    ) -> None:
        data = evidence.get("data")
        containers = [evidence]
        if isinstance(data, dict):
            containers.append(data)
            candidates = data.get("candidates")
            if isinstance(candidates, list):
                for candidate in candidates:
                    if isinstance(candidate, dict) and candidate:
                        profile.factor_candidates.append(
                            {"source_step": step_id, **candidate}
                        )
            shortlist = data.get("shortlist")
            if isinstance(shortlist, list):
                profile.factor_shortlist.extend(
                    str(item) for item in shortlist if item
                )
            latest = data.get("latest_values_by_symbol")
            if isinstance(latest, list):
                for item in latest:
                    if not isinstance(item, dict) or not item.get("symbol"):
                        continue
                    profile.comparisons.setdefault(
                        str(item["symbol"]), []
                    ).append(
                        metric_card(
                            str(data.get("factor_id") or "factor_value"),
                            item.get("value"),
                            subject=str(item["symbol"]),
                        )
                    )
        subject = _subject(evidence, data)
        for container in containers:
            for name, value in container.items():
                if (
                    name not in _METRIC_FIELDS
                    or isinstance(value, bool)
                    or not isinstance(value, (int, float))
                ):
                    continue
                key = (subject or "", name, repr(value))
                if key in metric_keys:
                    continue
                metric_keys.add(key)
                card = {
                    "source_step": step_id,
                    **metric_card(name, value, subject=subject),
                }
                profile.metrics.append(card)
                if subject:
                    profile.comparisons.setdefault(subject, []).append(card)

    def _answer_from_profile(
        self,
        profile: EvidenceProfile,
        output_mode: OutputMode,
    ) -> tuple[str, str]:
        if output_mode == "formal_report":
            return (
                "正式研究报告已生成",
                "报告只整合实际完成的上游结果；完整正文和证据范围见下方报告块。",
            )
        if output_mode == "idea_generation":
            candidate_count = len(profile.factor_candidates)
            shortlist_count = len(profile.factor_shortlist)
            return (
                "已形成可继续验证的研究想法",
                (
                    f"本次识别出 {candidate_count or '若干'} 个候选想法，"
                    f"其中 {shortlist_count} 个被列为优先验证对象。"
                    "它们目前只是研究假设，尚未经过回测或有效性验证。"
                ),
            )
        if output_mode == "risk_review":
            first = profile.risks[0]["text"] if profile.risks else "当前证据不足。"
            return (
                f"已识别 {len(profile.risks)} 项需要关注的风险",
                first,
            )
        if profile.metrics:
            examples = [
                "：".join(
                    part
                    for part in (
                        item.get("subject"),
                        f"{item['label']} {item['display_value']}",
                    )
                    if part
                )
                for item in profile.metrics[:3]
            ]
            boundary = ""
            if any(
                status in _UNVALIDATED_STATUSES
                for status in profile.validation_statuses.values()
            ):
                boundary = " 这些数值说明计算已经完成，但不能据此证明方法能够稳定获利。"
            return (
                "已完成所需的数据计算",
                "；".join(examples) + "。" + boundary,
            )
        if profile.summaries:
            return "已完成所需分析", profile.summaries[0]["text"]
        return "任务已执行完成", "本次执行未产生更多可安全提炼的结构化证据。"

    def _failure_block(
        self,
        plan: ExecutionPlan,
        profile: EvidenceProfile,
    ) -> ResultBlock:
        items = []
        step_by_id = {step.id: step for step in plan.steps}
        for step_id, result in {**profile.failed, **profile.blocked}.items():
            items.append(
                {
                    "step_id": step_id,
                    "stage": step_by_id[step_id].objective
                    if step_id in step_by_id
                    else step_id,
                    "status": result.status,
                    "message": plain_text(result.summary),
                    "reason": plain_text(result.error or "未提供失败原因"),
                }
            )
        planned_ids = {step.id for step in plan.steps}
        returned_ids = (
            set(profile.completed) | set(profile.failed) | set(profile.blocked)
        )
        items.extend(
            {
                "step_id": step_id,
                "stage": step_by_id[step_id].objective,
                "status": "failed",
                "message": "该步骤没有返回执行结果。",
                "reason": "系统未使用模拟数据填补缺失结果。",
            }
            for step_id in sorted(planned_ids - returned_ids)
        )
        return _block(
            "failures",
            "failure_notice",
            "未完成的部分",
            [item["step_id"] for item in items],
            {
                "items": items,
                "guidance": (
                    "系统没有使用模拟数据伪造结果。可根据失败原因补充输入，"
                    "或在相关服务恢复后重新执行。"
                ),
            },
            "secondary" if profile.completed else "primary",
        )


def _validation_status(result: ExpertResult) -> str | None:
    status = result.metadata.get("validation_status")
    if isinstance(status, str) and status:
        return status
    found: list[str] = []
    _visit(
        result.evidence,
        lambda key, value: (
            found.append(value)
            if key == "validation_status" and isinstance(value, str)
            else None
        ),
    )
    return found[0] if found else None


def _subject(evidence: dict[str, Any], data: Any) -> str | None:
    for container in (evidence, data):
        if not isinstance(container, dict):
            continue
        for key in ("symbol", "entity", "name", "factor_id"):
            value = container.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _confidence(
    profile: EvidenceProfile,
    completion_status: CompletionStatus,
) -> Confidence:
    if completion_status != "completed":
        return "low"
    statuses = set(profile.validation_statuses.values())
    if statuses & _UNVALIDATED_STATUSES:
        return "low"
    if statuses & {"moderate_positive_evidence"}:
        return "high"
    return "medium"


def _block(
    block_id: str,
    block_type: str,
    title: str,
    source_steps: list[str],
    data: dict[str, Any],
    importance: str,
) -> ResultBlock:
    return ResultBlock(
        id=block_id,
        type=cast(BlockType, block_type),
        title=title,
        importance=cast(Importance, importance),
        source_steps=list(dict.fromkeys(source_steps)),
        data=data,
    )


def _source_steps(
    items: list[dict[str, Any]],
    *,
    fallback: Mapping[str, ExpertResult] | None = None,
) -> list[str]:
    steps = [
        str(item["source_step"])
        for item in items
        if item.get("source_step")
    ]
    return list(dict.fromkeys(steps or list(fallback or {})))


def _metric_source_steps(metrics: list[dict[str, Any]]) -> list[str]:
    return _source_steps(metrics)


def _has_content(data: dict[str, Any]) -> bool:
    return any(value not in (None, "", [], {}) for value in data.values())


def _unique_dicts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        key = repr(sorted(item.items(), key=lambda pair: pair[0]))
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _unique_text_items(items: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for item in items:
        text = item.get("text", "")
        if text and text not in seen:
            seen.add(text)
            unique.append(item)
    return unique


def _visit(value: Any, callback: Any) -> None:
    if isinstance(value, list):
        for item in value:
            _visit(item, callback)
    elif isinstance(value, dict):
        for key, child in value.items():
            callback(key, child)
            _visit(child, callback)
