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
    ResultItem,
    TaskUnderstanding,
    TechnicalEvidence,
    ValidationStatus,
    ValidationSummary,
)
from backend.core.evidence_validator import (
    EvidenceValidationResult,
    VALIDATION_DETAILS,
)
from backend.core.plain_language import metric_card, plain_text, validation_label
from backend.core.policy_contracts import PolicyDecision
from backend.core.task_spec import TaskSpec


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
    "task_understanding",
    "validation_summary",
    "finding_cards",
    "metric_cards",
    "comparison",
    "risk_list",
    "assumption_list",
    "factor_list",
    "action_list",
    "limitations",
    "clarification",
    "failure_notice",
    "narrative",
    "report",
    "data_scope",
    "boundary_response",
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
        task_spec: TaskSpec | str,
        plan: ExecutionPlan,
        evidence: EvidenceValidationResult | Mapping[str, ExpertResult],
    ) -> AggregationResult:
        """Create a validated presentation contract.

        The string/raw-results form remains for compatibility with v0.3 callers.
        New orchestration must provide TaskSpec plus EvidenceValidationResult.
        """

        if isinstance(task_spec, TaskSpec):
            if not isinstance(evidence, EvidenceValidationResult):
                raise TypeError(
                    "TaskSpec aggregation requires EvidenceValidationResult"
                )
            return self._aggregate_task(task_spec, plan, evidence)
        if isinstance(evidence, EvidenceValidationResult):
            raw_results: Mapping[str, ExpertResult] = evidence.validated_results
        else:
            raw_results = evidence
        return self._aggregate_legacy(task_spec, plan, raw_results)

    def _aggregate_legacy(
        self,
        user_request: str,
        plan: ExecutionPlan,
        results: Mapping[str, ExpertResult],
    ) -> AggregationResult:
        """Preserve the v0.3 block behavior for existing in-process callers."""

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
        status = _overall_profile_status(profile, completion_status)
        label, explanation = VALIDATION_DETAILS[status]
        understanding = TaskUnderstanding(
            task_type=plan.task_type or _result_type_from_mode(output_mode),
            subject_type="research_thesis",
            subjects=[],
            research_goal=plan.goal or user_request.strip(),
            time_range=None,
            defaults_used=[],
            excluded_outputs=_excluded_outputs(),
        )
        return AggregationResult(
            user_goal=plan.goal or user_request.strip(),
            completion_status=completion_status,
            output_mode=output_mode,
            result_type=cast(Any, _result_type_from_mode(output_mode)),
            task_understanding=understanding,
            validation=ValidationSummary(
                status=status,
                label=label,
                explanation=explanation,
            ),
            direct_answer=direct_answer,
            content_blocks=blocks,
            execution_summary=self.build_execution_summary(plan, normalized),
            technical_evidence=self.build_technical_evidence(profile, normalized),
            disclaimer=RESEARCH_DISCLAIMER,
        )

    def _aggregate_task(
        self,
        task_spec: TaskSpec,
        plan: ExecutionPlan,
        evidence: EvidenceValidationResult,
    ) -> AggregationResult:
        results = evidence.validated_results
        completion_status = self.determine_completion_status(plan, results)
        profile = self.inspect_available_evidence(results)
        result_type = (
            "failure" if completion_status == "failed" else task_spec.task_type
        )
        output_mode = _output_mode_for_result(result_type)
        understanding = _task_understanding(task_spec)
        validation = _validation_summary(task_spec, evidence, profile)
        findings = _finding_items(profile)
        evidence_items = _evidence_items(profile)
        assumptions = [
            ResultItem(
                text=item.text,
                source_steps=[item.source_step],
                evidence_type="assumption",
            )
            for item in evidence.assumptions
        ]
        risks = [
            ResultItem(
                text=item.text,
                source_steps=[item.source_step],
                evidence_type="risk",
            )
            for item in evidence.risks
        ]
        limitations = [
            ResultItem(
                text=item.text,
                source_steps=[item.source_step],
                evidence_type="limitation",
            )
            for item in evidence.limitations
        ]
        limitations.extend(
            ResultItem(
                text=item,
                source_steps=[],
                evidence_type="limitation",
            )
            for item in evidence.missing_evidence
            if item
        )
        actions = _research_actions(task_spec, profile, evidence)
        direct_answer = _task_direct_answer(
            task_spec,
            profile,
            evidence,
            completion_status,
        )
        blocks = self._compose_task_blocks(
            task_spec,
            understanding,
            validation,
            profile,
            evidence,
            assumptions,
            risks,
            limitations,
            actions,
            completion_status,
            plan,
        )
        technical = TechnicalEvidence(
            validation_statuses={
                **profile.validation_statuses,
                "overall": evidence.overall_validation_status.value,
            },
            conflicts=evidence.conflicts,
            missing_evidence=evidence.missing_evidence,
            warnings=evidence.warnings,
            source_results=dict(results),
        )
        return AggregationResult(
            user_goal=task_spec.research_goal,
            completion_status=completion_status,
            output_mode=output_mode,
            result_type=cast(Any, result_type),
            task_understanding=understanding,
            validation=validation,
            direct_answer=direct_answer,
            key_findings=findings[:5],
            evidence_summary=evidence_items,
            assumptions=assumptions,
            risks=risks,
            limitations=_unique_result_items(limitations),
            data_scope=evidence.data_scope,
            next_research_steps=actions,
            content_blocks=blocks,
            execution_summary=self.build_execution_summary(plan, results),
            technical_evidence=technical,
            metadata={"policy_rewrite": False},
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

    def _compose_task_blocks(
        self,
        task_spec: TaskSpec,
        understanding: TaskUnderstanding,
        validation: ValidationSummary,
        profile: EvidenceProfile,
        evidence: EvidenceValidationResult,
        assumptions: list[ResultItem],
        risks: list[ResultItem],
        limitations: list[ResultItem],
        actions: list[ResultItem],
        completion_status: CompletionStatus,
        plan: ExecutionPlan,
    ) -> list[ResultBlock]:
        """Compose the task-type skeleton and omit unsupported empty modules."""

        blocks = [
            _block(
                "task-understanding",
                "task_understanding",
                "AlphaOS 如何理解本次任务",
                [],
                understanding.model_dump(mode="json"),
                "primary",
            ),
            _block(
                "validation",
                "validation_summary",
                "当前验证状态",
                list(profile.completed),
                validation.model_dump(mode="json"),
                "primary",
            ),
        ]
        evidence_blocks: list[ResultBlock] = []
        if task_spec.task_type == "formal_report" and profile.reports:
            step_id, report = profile.reports[-1]
            evidence_blocks.append(
                _block(
                    "report",
                    "report",
                    "正式研究报告",
                    [step_id],
                    {"content": report},
                    "primary",
                )
            )
        if task_spec.task_type == "factor_research" and (
            profile.factor_candidates or profile.factor_shortlist
        ):
            evidence_blocks.append(
                _block(
                    "factor-evidence",
                    "factor_list",
                    "因子定义与研究逻辑",
                    _source_steps(
                        profile.factor_candidates,
                        fallback=profile.completed,
                    ),
                    {
                        "items": profile.factor_candidates,
                        "shortlist": profile.factor_shortlist,
                        "validation_status": validation.status.value,
                        "plain_status": validation.label,
                    },
                    "secondary",
                )
            )
        if len(profile.comparisons) > 1:
            evidence_blocks.append(
                _block(
                    "comparison",
                    "comparison",
                    "研究对象对比",
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
            titles = {
                "company_research": "公司与财务事实",
                "factor_research": "计算结果、覆盖率与缺失情况",
                "personal_investment_decision": "个人约束与风险边界",
                "historical_analysis": "历史计算指标",
                "market_research": "市场历史事实",
                "comparison": "统一口径的比较证据",
            }
            evidence_blocks.append(
                _block(
                    "evidence-metrics",
                    "metric_cards",
                    titles.get(task_spec.task_type, "关键证据"),
                    _metric_source_steps(profile.metrics),
                    {"metrics": profile.metrics},
                    "primary",
                )
            )
        if profile.summaries and not profile.reports:
            evidence_blocks.append(
                _block(
                    "findings",
                    "finding_cards",
                    _findings_title(task_spec.task_type),
                    _source_steps(profile.summaries),
                    {"items": profile.summaries[:5]},
                    "secondary",
                )
            )
        if risks:
            evidence_blocks.append(
                _block(
                    "risks",
                    "risk_list",
                    "结论可能在什么情况下失效",
                    _result_item_steps(risks),
                    {"items": [item.model_dump(mode="json") for item in risks]},
                    "secondary",
                )
            )
        if assumptions:
            evidence_blocks.append(
                _block(
                    "assumptions",
                    "assumption_list",
                    "本次分析基于哪些前提",
                    _result_item_steps(assumptions),
                    {
                        "items": [
                            item.model_dump(mode="json") for item in assumptions
                        ]
                    },
                    "secondary",
                )
            )
        if limitations:
            evidence_blocks.append(
                _block(
                    "limitations",
                    "limitations",
                    "目前仍不能确定什么",
                    _result_item_steps(limitations),
                    {
                        "items": [
                            item.model_dump(mode="json")
                            for item in _unique_result_items(limitations)
                        ]
                    },
                    "secondary",
                )
            )
        if evidence.data_scope:
            evidence_blocks.append(
                _block(
                    "data-scope",
                    "data_scope",
                    "本次证据和数据范围",
                    _source_steps(evidence.data_scope),
                    {"sources": evidence.data_scope},
                    "supporting",
                )
            )
        if actions:
            evidence_blocks.append(
                _block(
                    "actions",
                    "action_list",
                    "下一步研究",
                    _result_item_steps(actions),
                    {"items": [item.model_dump(mode="json") for item in actions]},
                    "supporting",
                )
            )
        if completion_status in {"partially_completed", "failed"}:
            evidence_blocks.append(self._failure_block(plan, profile))
        return [block for block in [*blocks, *evidence_blocks] if _has_content(block.data)]

    def build_boundary_response(
        self,
        prompt: str,
        policy: PolicyDecision,
    ) -> AggregationResult:
        """Build a no-plan, no-expert response for blocked requests."""

        understanding = TaskUnderstanding(
            task_type="boundary_response",
            subject_type="research_thesis",
            subjects=[],
            research_goal=prompt.strip(),
            time_range=None,
            defaults_used=[],
            excluded_outputs=_excluded_outputs(),
        )
        validation = ValidationSummary(
            status=ValidationStatus.INSUFFICIENT_EVIDENCE,
            label="未进入研究执行",
            explanation="该请求在调用 Manager 或任何 Expert Agent 之前已完成边界判断。",
            supported_claims=[],
            unsupported_claims=["未执行任何研究计算或专家分析"],
        )
        direct = DirectAnswer(
            headline="本次请求不能直接执行",
            explanation=policy.safe_response or policy.reason,
            confidence="not_applicable",
            stance="not_applicable",
        )
        suggestions = [
            ResultItem(
                text=item,
                source_steps=[],
                evidence_type="research_action",
            )
            for item in policy.suggested_research_tasks
        ]
        return AggregationResult(
            user_goal=prompt.strip(),
            completion_status="rejected",
            output_mode="direct_answer",
            result_type="boundary_response",
            task_understanding=understanding,
            validation=validation,
            direct_answer=direct,
            next_research_steps=suggestions,
            content_blocks=[
                _block(
                    "boundary",
                    "boundary_response",
                    "AlphaOS 的能力范围",
                    [],
                    {
                        "reason": policy.reason,
                        "safe_response": policy.safe_response,
                        "suggested_research_tasks": policy.suggested_research_tasks,
                    },
                    "primary",
                )
            ],
            execution_summary=None,
            technical_evidence=None,
            metadata={
                "policy_decision": policy.decision,
                "policy_tags": policy.policy_tags,
                "policy_rewrite": False,
            },
            disclaimer=RESEARCH_DISCLAIMER,
        )

    def build_clarification_response(
        self,
        task_spec: TaskSpec,
    ) -> AggregationResult:
        """Build a no-expert response when required research inputs are missing."""

        understanding = _task_understanding(task_spec)
        question = (
            task_spec.clarification_question
            or "请补充完成研究所需的关键信息。"
        )
        validation = ValidationSummary(
            status=ValidationStatus.INSUFFICIENT_EVIDENCE,
            label="等待补充信息",
            explanation="关键研究输入尚未明确，因此未创建专家任务图。",
            unsupported_claims=["尚未执行研究，不能形成事实或结论"],
        )
        return AggregationResult(
            user_goal=task_spec.research_goal,
            completion_status="needs_clarification",
            output_mode="clarification",
            result_type="clarification",
            task_understanding=understanding,
            validation=validation,
            direct_answer=DirectAnswer(
                headline="需要先补充信息",
                explanation=question,
                confidence="not_applicable",
                stance="not_applicable",
            ),
            content_blocks=[
                _block(
                    "clarification",
                    "clarification",
                    "需要补充的信息",
                    [],
                    {
                        "question": question,
                        "missing_fields": task_spec.missing_fields,
                        "reason": "缺少这些信息时不能安全地猜测股票代码、日期或比较对象。",
                    },
                    "primary",
                ),
                _block(
                    "task-understanding",
                    "task_understanding",
                    "AlphaOS 如何理解本次任务",
                    [],
                    understanding.model_dump(mode="json"),
                    "primary",
                ),
            ],
            execution_summary=None,
            technical_evidence=None,
            metadata={"policy_rewrite": False},
            disclaimer=RESEARCH_DISCLAIMER,
        )

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


def _task_understanding(task_spec: TaskSpec) -> TaskUnderstanding:
    time_range = task_spec.time_range_description
    if not time_range and (task_spec.start_date or task_spec.end_date):
        time_range = (
            f"{task_spec.start_date or '起始日期未明确'} 至 "
            f"{task_spec.end_date or '结束日期未明确'}"
        )
    return TaskUnderstanding(
        task_type=task_spec.task_type,
        subject_type=task_spec.subject_type,
        subjects=task_spec.subjects,
        research_goal=task_spec.research_goal,
        time_range=time_range,
        defaults_used=task_spec.defaulted_fields,
        excluded_outputs=_excluded_outputs(),
    )


def _validation_summary(
    task_spec: TaskSpec,
    evidence: EvidenceValidationResult,
    profile: EvidenceProfile,
) -> ValidationSummary:
    status = evidence.overall_validation_status
    label, explanation = VALIDATION_DETAILS[status]
    supported = [
        item["text"]
        for item in profile.summaries[:3]
        if item.get("text")
    ]
    if profile.metrics:
        supported.append("已展示指标仅代表声明数据范围内的实际计算值。")
    unsupported = list(evidence.missing_evidence)
    if status in {
        ValidationStatus.RESEARCH_DRAFT,
        ValidationStatus.COMPUTED_NOT_VALIDATED,
        ValidationStatus.HISTORICALLY_ANALYZED,
        ValidationStatus.INSUFFICIENT_EVIDENCE,
    }:
        unsupported.extend(
            [
                "不能据此证明稳定预测能力",
                "不能据此推断未来收益或形成证券推荐",
            ]
        )
    if task_spec.task_type == "factor_research":
        unsupported.append("因子数值和排序不代表推荐，也不能证明未来上涨")
    return ValidationSummary(
        status=status,
        label=label,
        explanation=explanation,
        supported_claims=list(dict.fromkeys(supported)),
        unsupported_claims=list(dict.fromkeys(unsupported)),
    )


def _task_direct_answer(
    task_spec: TaskSpec,
    profile: EvidenceProfile,
    evidence: EvidenceValidationResult,
    completion_status: CompletionStatus,
) -> DirectAnswer:
    if completion_status == "failed":
        return DirectAnswer(
            headline="本次研究没有成功完成",
            explanation=(
                "现有步骤没有产生足以回答问题的可靠证据，系统未使用模拟数据"
                "或未执行结果补造结论。"
            ),
            confidence="not_applicable",
            stance="insufficient_evidence",
        )
    prefix = (
        "部分研究步骤未完成；以下结论只基于已返回的证据。"
        if completion_status == "partially_completed"
        else ""
    )
    status = evidence.overall_validation_status
    subject = "、".join(task_spec.subjects) or "指定研究对象"
    if task_spec.task_type == "factor_research":
        if status == ValidationStatus.COMPUTED_NOT_VALIDATED:
            explanation = (
                f"{subject} 已在指定样本中完成计算，但当前证据只能证明公式运行成功，"
                "尚不能证明该因子具有稳定的选股或收益预测能力。"
            )
            headline = "因子已计算，但有效性尚未验证"
        else:
            explanation = (
                f"已形成关于 {subject} 的研究结果；当前验证状态为"
                f"“{VALIDATION_DETAILS[status][0]}”，不能据此形成股票推荐。"
            )
            headline = "已完成因子研究范围内的证据整理"
    elif task_spec.task_type == "company_research":
        headline = "已完成公司事实与主要风险整理"
        explanation = (
            (profile.summaries[0]["text"] + " ") if profile.summaries else ""
        ) + "结论仅覆盖已声明的数据范围，不构成买卖、持有或估值交易建议。"
    elif task_spec.task_type == "risk_review":
        headline = (
            f"已识别 {len(profile.risks)} 项主要风险"
            if profile.risks
            else "风险结论所需证据仍不充分"
        )
        explanation = (
            profile.risks[0]["text"]
            if profile.risks
            else "当前缺少足以支持完整风险判断的证据。"
        )
    elif task_spec.task_type == "formal_report":
        headline = "正式研究报告已生成"
        explanation = "报告仅整合实际完成的上游研究证据，并保留验证状态与限制。"
    elif task_spec.task_type == "comparison":
        headline = "已按统一口径完成比较"
        explanation = (
            "比较结果只说明声明样本中的差异，不能直接外推为未来表现或证券推荐。"
        )
    elif task_spec.task_type == "historical_analysis":
        headline = "已完成指定范围的历史分析"
        explanation = (
            "所展示数值是历史样本计算结果，不代表未来收益；未真实完成的回测指标不会展示。"
        )
    else:
        headline = "已完成市场研究范围内的证据整理"
        explanation = (
            (profile.summaries[0]["text"] + " ") if profile.summaries else ""
        ) + "历史事实与研究判断已区分展示，未知项保留为限制。"
    return DirectAnswer(
        headline=headline,
        explanation=" ".join(part for part in (prefix, explanation) if part),
        confidence=_confidence(profile, completion_status),
        stance=(
            "insufficient_evidence"
            if status
            in {
                ValidationStatus.RESEARCH_DRAFT,
                ValidationStatus.COMPUTED_NOT_VALIDATED,
                ValidationStatus.INSUFFICIENT_EVIDENCE,
                ValidationStatus.UNAVAILABLE,
            }
            else "neutral"
        ),
    )


def _finding_items(profile: EvidenceProfile) -> list[ResultItem]:
    return [
        ResultItem(
            text=item["text"],
            source_steps=[item["source_step"]],
            evidence_type="judgment",
        )
        for item in profile.summaries
        if item.get("text")
    ]


def _evidence_items(profile: EvidenceProfile) -> list[ResultItem]:
    items: list[ResultItem] = []
    for metric in profile.metrics:
        subject = f"{metric.get('subject')}：" if metric.get("subject") else ""
        items.append(
            ResultItem(
                text=f"{subject}{metric.get('label')} {metric.get('display_value')}",
                source_steps=[metric["source_step"]],
                evidence_type="fact",
            )
        )
    return items


def _research_actions(
    task_spec: TaskSpec,
    profile: EvidenceProfile,
    evidence: EvidenceValidationResult,
) -> list[ResultItem]:
    action_texts: list[str] = []
    safe_markers = (
        "验证",
        "检验",
        "补充",
        "延长",
        "检查",
        "对比",
        "核对",
        "测试",
        "分析",
    )
    prohibited = (
        "买入",
        "卖出",
        "持有",
        "建仓",
        "减仓",
        "仓位",
        "配置",
        "目标收益",
    )
    for item in profile.actions:
        text = item.get("text", "")
        if (
            text
            and any(marker in text for marker in safe_markers)
            and not any(marker in text for marker in prohibited)
        ):
            action_texts.append(text)
    defaults = {
        "factor_research": [
            "补充 IC、样本外和市场状态分层检验。",
            "检查参数敏感性并纳入交易成本。",
        ],
        "company_research": [
            "补充最新公司基本面、现金流和审计意见。",
            "核对数据缺失项及其对结论的影响。",
        ],
        "personal_investment_decision": [
            "补充个人资金期限、应急资金和收入支出约束。",
            "明确可承受的最大亏损或回撤边界。",
        ],
        "market_research": [
            "延长历史样本并分市场状态复核。",
            "核对最新宏观发布值和数据范围。",
        ],
        "historical_analysis": [
            "补充样本外检验和交易成本假设。",
            "检查计算规则与参数敏感性。",
        ],
        "risk_review": [
            "针对主要失效情景补充压力测试。",
            "补齐当前缺失的上游证据。",
        ],
        "comparison": ["补充统一数据窗口和口径下的稳健性比较。"],
        "formal_report": ["补齐报告列出的缺失证据后重新验证结论。"],
    }
    if not action_texts or evidence.missing_evidence:
        action_texts.extend(defaults[task_spec.task_type])
    return [
        ResultItem(
            text=text,
            source_steps=[],
            evidence_type="research_action",
        )
        for text in dict.fromkeys(action_texts)
    ]


def _overall_profile_status(
    profile: EvidenceProfile,
    completion_status: CompletionStatus,
) -> ValidationStatus:
    if completion_status == "failed":
        return ValidationStatus.INSUFFICIENT_EVIDENCE
    statuses = set(profile.validation_statuses.values())
    if "computed_not_validated" in statuses:
        return ValidationStatus.COMPUTED_NOT_VALIDATED
    if "unverified" in statuses:
        return ValidationStatus.RESEARCH_DRAFT
    if profile.metrics:
        return ValidationStatus.HISTORICALLY_ANALYZED
    return ValidationStatus.RESEARCH_DRAFT


def _result_type_from_mode(output_mode: OutputMode) -> str:
    return {
        "data_analysis": "historical_analysis",
        "idea_generation": "factor_research",
        "risk_review": "risk_review",
        "comparison": "comparison",
        "formal_report": "formal_report",
        "clarification": "clarification",
        "failure": "failure",
    }.get(output_mode, "market_research")


def _output_mode_for_result(result_type: str) -> OutputMode:
    return cast(
        OutputMode,
        {
            "factor_research": "data_analysis",
            "personal_investment_decision": "direct_answer",
            "historical_analysis": "data_analysis",
            "risk_review": "risk_review",
            "comparison": "comparison",
            "formal_report": "formal_report",
            "failure": "failure",
        }.get(result_type, "direct_answer"),
    )


def _excluded_outputs() -> list[str]:
    return [
        "收益预测",
        "证券推荐",
        "买卖或持有建议",
        "交易指令",
        "仓位配置",
        "收益承诺",
    ]


def _findings_title(task_type: str) -> str:
    return {
        "company_research": "盈利质量与异常信号",
        "factor_research": "因子计算与研究发现",
        "personal_investment_decision": "个人约束与风险边界",
        "risk_review": "总体风险判断",
        "market_research": "核心发现",
        "historical_analysis": "历史样本发现",
        "comparison": "主要差异",
    }.get(task_type, "关键发现")


def _result_item_steps(items: list[ResultItem]) -> list[str]:
    return list(
        dict.fromkeys(
            step
            for item in items
            for step in item.source_steps
            if step
        )
    )


def _unique_result_items(items: list[ResultItem]) -> list[ResultItem]:
    seen: set[str] = set()
    output: list[ResultItem] = []
    for item in items:
        if item.text not in seen:
            seen.add(item.text)
            output.append(item)
    return output


def _visit(value: Any, callback: Any) -> None:
    if isinstance(value, list):
        for item in value:
            _visit(item, callback)
    elif isinstance(value, dict):
        for key, child in value.items():
            callback(key, child)
            _visit(child, callback)
