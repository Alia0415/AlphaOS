"""Quant Agent with internal, allowlisted dynamic skill planning."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, ValidationError, field_validator

from backend.core.contracts import AgentId, ExpertResult, ExpertTask
from backend.services.ark_client import ArkClient, ArkClientError
from backend.services.pandadata_client import PandaDataClient
from backend.skills.contracts import (
    SkillInvocation,
    SkillResult,
    SkillStatus,
)
from backend.skills.skill_registry import SkillRegistry


MAX_SKILL_STEPS = 3
PANDADATA_FIELDS = ["open", "high", "low", "close", "volume"]


class SelectedSkill(BaseModel):
    skill_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class QuantSkillStep(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    skill_id: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list, max_length=MAX_SKILL_STEPS)

    @field_validator("depends_on")
    @classmethod
    def dependencies_are_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("Skill step dependencies must be unique")
        return values


class QuantSkillPlan(BaseModel):
    selected_skills: list[SelectedSkill] = Field(
        default_factory=list,
        max_length=MAX_SKILL_STEPS,
    )
    steps: list[QuantSkillStep] = Field(
        default_factory=list,
        max_length=MAX_SKILL_STEPS,
    )
    needs_clarification: bool = False
    clarification_question: str | None = None


class QuantAgent:
    """Plan and execute the minimal sufficient subset of Quant-owned skills."""

    def __init__(
        self,
        *,
        ark_client: ArkClient | None = None,
        data_client: PandaDataClient | None = None,
        skill_registry: SkillRegistry | None = None,
    ) -> None:
        self._ark_client = ark_client
        self._data_client = data_client or PandaDataClient()
        self.skills = skill_registry or SkillRegistry(ark_client=ark_client)

    def execute(self, task: ExpertTask) -> ExpertResult:
        if task.agent != AgentId.QUANT:
            return _failed(task, "Quant Agent 收到了不匹配的任务类型。")
        try:
            plan = self.create_skill_plan(task)
        except QuantAgentError as exc:
            return _failed(task, str(exc))

        agent_events: list[dict[str, Any]] = [
            {
                "type": "skill_plan_created",
                "metadata": {
                    "skill_id": None,
                    "selected_skill_count": len(plan.selected_skills),
                    "skill_step_count": len(plan.steps),
                },
            }
        ]
        if plan.needs_clarification:
            question = plan.clarification_question or "请补充量化计算所需的输入。"
            return _failed(
                task,
                question,
                metadata={
                    "needs_clarification": True,
                    "clarification_question": question,
                    "skill_plan": plan.model_dump(mode="json"),
                    "agent_events": agent_events,
                },
            )

        missing = self._missing_required_inputs(plan, task)
        if missing:
            question = "请补充以下 Quant 输入：" + "、".join(sorted(missing)) + "。"
            return _failed(
                task,
                question,
                metadata={
                    "needs_clarification": True,
                    "clarification_question": question,
                    "skill_plan": plan.model_dump(mode="json"),
                    "agent_events": agent_events,
                },
            )
        if (
            _requests_cross_section(task.original_user_request)
            and len(_symbols(task.inputs.get("symbols"))) < 2
            and any(
                self.skills.get(selection.skill_id).input_schema.get(
                    "x-data-source"
                )
                == "pandadata_market_data"
                for selection in plan.selected_skills
            )
        ):
            question = "横截面排序至少需要两个 symbol；请补充标的池。"
            return _failed(
                task,
                question,
                metadata={
                    "needs_clarification": True,
                    "clarification_question": question,
                    "skill_plan": plan.model_dump(mode="json"),
                    "agent_events": agent_events,
                },
            )

        skill_results: dict[str, SkillResult] = {}
        tool_calls: list[dict[str, Any]] = []
        pending = {step.id: step for step in plan.steps}
        while pending:
            ready = [
                step
                for step in pending.values()
                if all(dependency in skill_results for dependency in step.depends_on)
            ]
            if not ready:
                return _failed(
                    task,
                    "Quant Skill Plan 没有可执行步骤。",
                    metadata={
                        "skill_plan": plan.model_dump(mode="json"),
                        "agent_events": agent_events,
                    },
                )
            for step in sorted(ready, key=lambda item: item.id):
                failed_dependency = next(
                    (
                        dependency
                        for dependency in step.depends_on
                        if skill_results[dependency].status != SkillStatus.COMPLETED
                    ),
                    None,
                )
                if failed_dependency:
                    result = SkillResult(
                        invocation_id=str(uuid4()),
                        skill_id=step.skill_id,
                        status=SkillStatus.FAILED,
                        summary="Skill 步骤因依赖失败而被阻断。",
                        limitations=[f"Required skill step failed: {failed_dependency}"],
                        error=f"Required skill step failed: {failed_dependency}",
                    )
                    skill_results[step.id] = result
                    agent_events.append(
                        _skill_event("skill_failed", step.skill_id, result.status)
                    )
                    pending.pop(step.id)
                    continue

                invocation_inputs = {
                    **task.inputs,
                    "original_user_request": task.original_user_request,
                    "dependency_results": {
                        dependency: skill_results[dependency].model_dump(mode="json")
                        for dependency in step.depends_on
                    },
                }
                data_result = self._prepare_declared_inputs(
                    step.skill_id,
                    invocation_inputs,
                    tool_calls,
                )
                agent_events.append(
                    _skill_event("skill_started", step.skill_id, None)
                )
                if isinstance(data_result, SkillResult):
                    result = data_result
                else:
                    invocation = SkillInvocation(
                        invocation_id=str(uuid4()),
                        skill_id=step.skill_id,
                        agent=AgentId.QUANT.value,
                        objective=step.objective,
                        inputs=data_result,
                    )
                    result = self.skills.execute(invocation)
                skill_results[step.id] = result
                tool_calls.append(
                    {
                        "tool": step.skill_id,
                        "status": result.status.value,
                        "arguments": {
                            "objective": step.objective,
                            "depends_on": step.depends_on,
                        },
                    }
                )
                agent_events.append(
                    _skill_event(
                        (
                            "skill_completed"
                            if result.status == SkillStatus.COMPLETED
                            else "skill_failed"
                        ),
                        step.skill_id,
                        result.status,
                    )
                )
                pending.pop(step.id)

        return _expert_result(
            task,
            plan,
            skill_results,
            tool_calls,
            agent_events,
        )

    def __call__(self, task: ExpertTask) -> ExpertResult:
        return self.execute(task)

    def create_skill_plan(self, task: ExpertTask) -> QuantSkillPlan:
        """Ask Ark to plan over only the Quant Agent's authorized skills."""

        allowed = self.skills.prompt_payload(AgentId.QUANT.value)
        prompt = _planner_prompt(task, allowed)
        try:
            raw = self._get_client().chat(prompt)
            return _parse_and_validate_plan(raw, allowed)
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            try:
                repaired = self._get_client().chat(
                    _planner_repair_prompt(task, allowed, raw, str(exc))
                )
                return _parse_and_validate_plan(repaired, allowed)
            except (
                ArkClientError,
                json.JSONDecodeError,
                ValidationError,
                ValueError,
            ):
                raise QuantAgentError(
                    "Quant Skill Planner 在一次修复后仍未返回有效计划。"
                ) from None
        except ArkClientError:
            raise QuantAgentError("Quant Skill Planner 服务不可用。") from None

    def _missing_required_inputs(
        self,
        plan: QuantSkillPlan,
        task: ExpertTask,
    ) -> set[str]:
        required: set[str] = set()
        for selection in plan.selected_skills:
            required.update(self.skills.get(selection.skill_id).required_task_inputs)
        return {
            name
            for name in required
            if task.inputs.get(name) in (None, "", [], {})
        }

    def _prepare_declared_inputs(
        self,
        skill_id: str,
        inputs: dict[str, Any],
        tool_calls: list[dict[str, Any]],
    ) -> dict[str, Any] | SkillResult:
        spec = self.skills.get(skill_id)
        if spec.input_schema.get("x-data-source") != "pandadata_market_data":
            return inputs

        call = {
            "tool": "pandadata_market_data",
            "status": "started",
            "arguments": {
                "symbols": inputs["symbols"],
                "start_date": inputs["start_date"],
                "end_date": inputs["end_date"],
                "fields": PANDADATA_FIELDS,
            },
        }
        tool_calls.append(call)
        validation_error = _validate_market_request(
            _symbols(inputs["symbols"]),
            str(inputs["start_date"]),
            str(inputs["end_date"]),
        )
        if validation_error:
            call["status"] = "failed"
            return SkillResult(
                invocation_id=str(uuid4()),
                skill_id=skill_id,
                status=SkillStatus.FAILED,
                summary="Quant 市场数据输入无效。",
                limitations=[validation_error],
                error=validation_error,
            )
        try:
            inputs["market_data"] = self._data_client.get_market_data(
                symbols=_symbols(inputs["symbols"]),
                start_date=str(inputs["start_date"]),
                end_date=str(inputs["end_date"]),
                fields=PANDADATA_FIELDS,
                indicator=str(inputs.get("indicator", "000300")),
                st=bool(inputs.get("st", True)),
            )
        except Exception:
            call["status"] = "failed"
            return SkillResult(
                invocation_id=str(uuid4()),
                skill_id=skill_id,
                status=SkillStatus.FAILED,
                summary="PandaData OHLCV 获取失败。",
                limitations=["外部市场数据服务请求失败。"],
                error="外部市场数据服务请求失败。",
            )
        call["status"] = "completed"
        return inputs

    def _get_client(self) -> ArkClient:
        if self._ark_client is None:
            self._ark_client = ArkClient()
        return self._ark_client


class QuantAgentError(RuntimeError):
    """Raised when the internal skill planner cannot produce a valid DAG."""


def _parse_and_validate_plan(
    raw: str,
    allowed_payload: list[dict[str, Any]],
) -> QuantSkillPlan:
    plan = QuantSkillPlan.model_validate(_extract_json(raw))
    if plan.needs_clarification:
        if not plan.clarification_question or not plan.clarification_question.strip():
            raise ValueError("Clarification plans require a question")
        if plan.steps or plan.selected_skills:
            raise ValueError("Clarification plans cannot contain skill steps")
        return plan
    if not plan.steps or not plan.selected_skills:
        raise ValueError("Executable Quant plans require selected skills and steps")
    allowed = {item["id"] for item in allowed_payload}
    selected = [item.skill_id for item in plan.selected_skills]
    if len(selected) != len(set(selected)):
        raise ValueError("selected_skills contains duplicates")
    if not set(selected).issubset(allowed):
        raise ValueError("Quant planner selected an unauthorized skill")
    step_ids = [step.id for step in plan.steps]
    if len(step_ids) != len(set(step_ids)):
        raise ValueError("Skill step IDs must be unique")
    used = {step.skill_id for step in plan.steps}
    if used != set(selected):
        raise ValueError("selected_skills must exactly match skills used by steps")
    known_ids = set(step_ids)
    dependencies: dict[str, list[str]] = {}
    for step in plan.steps:
        if step.skill_id not in allowed:
            raise ValueError("Skill step is unauthorized")
        if step.id in step.depends_on:
            raise ValueError("Skill step cannot depend on itself")
        if not set(step.depends_on).issubset(known_ids):
            raise ValueError("Skill step references an unknown dependency")
        dependencies[step.id] = step.depends_on
    _assert_acyclic(dependencies)
    return plan


def _assert_acyclic(dependencies: dict[str, list[str]]) -> None:
    state: dict[str, int] = {}

    def visit(step_id: str) -> None:
        if state.get(step_id) == 1:
            raise ValueError("Skill plan contains a dependency cycle")
        if state.get(step_id) == 2:
            return
        state[step_id] = 1
        for dependency in dependencies[step_id]:
            visit(dependency)
        state[step_id] = 2

    for step_id in dependencies:
        visit(step_id)


def _planner_prompt(
    task: ExpertTask,
    allowed: list[dict[str, Any]],
) -> str:
    context = {
        "objective": task.objective,
        "original_user_request": task.original_user_request,
        "task_inputs": task.inputs,
        "dependency_results": {
            step_id: result.model_dump(mode="json")
            for step_id, result in task.dependency_results.items()
        },
    }
    schema = QuantSkillPlan.model_json_schema()
    return f"""
你是 AlphaOS Quant Agent 内部的 Quant Skill Planner。
你只能从下列 allowed Skills 中动态选择完成当前 Quant 任务所需的最小充分集合。
不得使用关键词 if/else 固定路由，不得建立固定 Skill 流水线，最多 3 个步骤。
步骤顺序和依赖必须由当前目标决定；简单任务只选一个 Skill。
不得调用未启用或未授权 Skill。Manager 不参与本层 Skill 选择。

若计算型 Skill 缺少 symbols、start_date 或 end_date，返回澄清计划，不得猜测。
若用户要求横截面排序但只有一个 symbol，应要求补充标的池或明确限制。
不得规划完整回测、自动交易、买卖建议，或声称未实际计算的 IC/绩效。

只返回严格 JSON，不要 Markdown。selected_skills 必须与 steps 使用的 Skill 完全一致。

allowed Skills：
{json.dumps(allowed, ensure_ascii=False)}

JSON Schema：
{json.dumps(schema, ensure_ascii=False)}

任务上下文：
{json.dumps(context, ensure_ascii=False)}
""".strip()


def _planner_repair_prompt(
    task: ExpertTask,
    allowed: list[dict[str, Any]],
    raw: str,
    error: str,
) -> str:
    return f"""
上一次 Quant Skill Plan 无效。仅修复一次。
只能使用这些 Skill ID：{json.dumps([item["id"] for item in allowed])}。
最多 3 步，检查 depends_on，selected_skills 必须与 steps 完全一致。
缺少计算所需的 symbols/start_date/end_date 时返回空步骤澄清计划。
只返回严格 JSON。

任务：{task.objective}
验证错误：{error}
无效输出：{raw[:20_000]}
""".strip()


def _extract_json(value: str) -> Any:
    text = value.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
    return json.loads(text)


def _symbols(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip().upper() for item in value if str(item).strip()]


def _validate_market_request(
    symbols: list[str],
    start_date: str,
    end_date: str,
) -> str | None:
    if not symbols:
        return "Quant 计算需要至少一个 symbol。"
    try:
        start = datetime.strptime(start_date, "%Y%m%d")
        end = datetime.strptime(end_date, "%Y%m%d")
    except ValueError:
        return "start_date 和 end_date 必须是 YYYYMMDD 格式的有效日期。"
    if start > end:
        return "start_date 不能晚于 end_date。"
    return None


def _requests_cross_section(user_request: str) -> bool:
    normalized = user_request.lower()
    return any(
        phrase in normalized
        for phrase in ("横截面", "cross-sectional", "cross section")
    )


def _skill_event(
    event_type: str,
    skill_id: str,
    status: SkillStatus | None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {"skill_id": skill_id}
    if status is not None:
        metadata["status"] = status.value
    return {"type": event_type, "skill_id": skill_id, "metadata": metadata}


def _expert_result(
    task: ExpertTask,
    plan: QuantSkillPlan,
    results: dict[str, SkillResult],
    tool_calls: list[dict[str, Any]],
    agent_events: list[dict[str, Any]],
) -> ExpertResult:
    completed = [
        result for result in results.values()
        if result.status == SkillStatus.COMPLETED
    ]
    failed = [
        result for result in results.values()
        if result.status != SkillStatus.COMPLETED
    ]
    evidence = [
        {
            "type": "skill_result",
            "skill_id": result.skill_id,
            "status": result.status.value,
            "summary": result.summary,
            "data": result.data,
            "validation_status": result.data.get(
                "validation_status",
                "unverified",
            ),
        }
        for result in results.values()
    ]
    assumptions = list(
        dict.fromkeys(
            assumption
            for result in results.values()
            for assumption in result.assumptions
        )
    )
    limitations = list(
        dict.fromkeys(
            limitation
            for result in results.values()
            for limitation in result.limitations
        )
    )
    provenance = [
        result.provenance
        for result in results.values()
        if result.provenance
    ]
    data_sources = [
        {
            "name": "PandaData",
            "symbols": _symbols(task.inputs.get("symbols")),
            "start_date": task.inputs.get("start_date"),
            "end_date": task.inputs.get("end_date"),
        }
    ] if any(call["tool"] == "pandadata_market_data" for call in tool_calls) else []
    data_sources.extend(
        {
            "name": item.get("source_repository"),
            "commit": item.get("source_commit"),
            "license": item.get("license"),
        }
        for item in provenance
    )
    statuses = {
        item["validation_status"]
        for item in evidence
        if item["status"] == SkillStatus.COMPLETED.value
    }
    validation_status = (
        next(iter(statuses))
        if len(statuses) == 1
        else "mixed_unvalidated"
    )
    status: Literal["completed", "failed"] = "failed" if failed else "completed"
    return ExpertResult(
        task_id=task.task_id,
        agent=AgentId.QUANT,
        status=status,
        summary=(
            f"Quant Agent 实际完成 {len(completed)}/{len(results)} 个 Skill 步骤。"
        ),
        evidence=evidence,
        assumptions=assumptions,
        risks=["量化因子假设和计算结果尚未完成实证有效性验证。"],
        limitations=limitations,
        recommendations=[
            "后续验证应独立设计，不能把当前结果视为交易信号。"
        ],
        tool_calls=tool_calls,
        data_sources=data_sources,
        metadata={
            "skill_plan": plan.model_dump(mode="json"),
            "actual_skills": [result.skill_id for result in results.values()],
            "skill_results": {
                step_id: result.model_dump(mode="json")
                for step_id, result in results.items()
            },
            "validation_status": validation_status,
            "provenance": provenance,
            "agent_events": agent_events,
        },
        error=(
            "; ".join(result.error or "Skill failed" for result in failed)
            if failed
            else None
        ),
    )


def _failed(
    task: ExpertTask,
    error: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> ExpertResult:
    return ExpertResult(
        task_id=task.task_id,
        agent=AgentId.QUANT,
        status="failed",
        summary="Quant Agent 未能完成量化任务。",
        limitations=[error],
        metadata=metadata or {},
        error=error,
    )
