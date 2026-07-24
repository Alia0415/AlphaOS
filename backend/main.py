"""AlphaOS FastAPI application entry point."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from pathlib import Path
from time import perf_counter
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from backend.agents.router_agent import (
    RouteDecision,
    RouterAgent,
    RouterAgentError,
)
from backend.agents.manager_agent import ManagerAgent, ManagerAgentError
from backend.core.agent_registry import DEFAULT_EXPERTS, AgentRegistry
from backend.core.contracts import (
    AgentId,
    ExecutionEvent,
    ExecutionPlan,
    ExpertInfo,
    ExpertResult,
    FollowupAnswer,
    OverviewStats,
    RESEARCH_DISCLAIMER,
    ReportDetail,
    ReportSummary,
    SkillInfo,
    TaskDetail,
    TaskExecutionResponse,
    TaskSummary,
)
from backend.core.registry_factory import build_registry
from backend.core.reporting import build_report_record
from backend.core.result_aggregator import ResultAggregator
from backend.core.store import get_store
from backend.core.workflow_executor import WorkflowExecutor
from backend.services.pandadata_client import (
    PandaDataClient,
    PandaDataConfigurationError,
)
from backend.skills.skill_registry import SkillRegistry


app = FastAPI(title="AlphaOS API", version="0.4.0")
REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = REPO_ROOT / "frontend"
PUBLIC_DIR = REPO_ROOT / "public"
app.mount(
    "/static",
    StaticFiles(directory=FRONTEND_DIR),
    name="frontend-static",
)
app.mount(
    "/pixel",
    StaticFiles(directory=PUBLIC_DIR / "pixel"),
    name="pixel-sprites",
)
pandadata = PandaDataClient()
router = RouterAgent()
store = get_store()
skill_registry = SkillRegistry()
result_aggregator = ResultAggregator()
manager = ManagerAgent(registry=build_registry(store))
workflow_executor = WorkflowExecutor(registry=build_registry(store))


def _rebuild_experts() -> None:
    """Rebuild Manager and Executor with the current effective registry.

    The effective registry applies persisted enable/disable overrides, so a
    toggle takes effect for both planning and execution on the next request.
    """

    global manager, workflow_executor
    registry = build_registry(store)
    manager = ManagerAgent(registry=registry)
    workflow_executor = WorkflowExecutor(registry=registry)


class RouteRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, value: str) -> str:
        prompt = value.strip()
        if not prompt:
            raise ValueError("prompt 不能为空")
        return prompt


class ExpertToggleRequest(BaseModel):
    enabled: bool


class ClarifyRequest(BaseModel):
    answers: dict[str, Any] = Field(default_factory=dict)


class FollowupRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2_000)

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        question = value.strip()
        if not question:
            raise ValueError("question 不能为空")
        return question


class SessionResponse(BaseModel):
    task_id: str
    plan: ExecutionPlan


class MarketDataRequest(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=50)
    start_date: str = Field(pattern=r"^\d{8}$")
    end_date: str = Field(pattern=r"^\d{8}$")
    fields: list[str] = Field(default_factory=list, max_length=100)
    indicator: str = Field(default="000300", pattern=r"^[A-Za-z0-9.]+$")
    st: bool = True

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().upper() for value in values]
        if any(
            not value
            or "." not in value
            or not all(part.isalnum() for part in value.split(".", maxsplit=1))
            for value in normalized
        ):
            raise ValueError("股票代码格式应类似 000001.SZ")
        return normalized

    @field_validator("fields")
    @classmethod
    def validate_fields(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value or not value.replace("_", "").isalnum() for value in normalized):
            raise ValueError("字段名只能包含字母、数字和下划线")
        return normalized


class MarketDataResponse(BaseModel):
    source: str = "PandaData"
    symbols: list[str]
    start_date: str
    end_date: str
    data: Any


@app.get("/", include_in_schema=False)
async def frontend() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/office", include_in_schema=False)
async def office_frontend() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "office" / "index.html")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/pandadata/status")
async def pandadata_status() -> dict[str, object]:
    return pandadata.status()


# -- read-only surfaces ------------------------------------------------------


@app.get("/api/experts", response_model=list[ExpertInfo])
async def list_experts() -> list[ExpertInfo]:
    registry = build_registry(store)
    experts: list[ExpertInfo] = []
    for definition in DEFAULT_EXPERTS:
        effective = registry.get(definition.id)
        skills = [
            spec.id
            for spec in skill_registry.allowed_for_agent(definition.id.value)
        ]
        experts.append(
            ExpertInfo(
                id=effective.id.value,
                name=effective.name,
                description=effective.description,
                enabled=effective.enabled,
                capabilities=list(effective.capabilities),
                tools=list(effective.tools),
                skills=skills,
            )
        )
    return experts


@app.get("/api/skills", response_model=list[SkillInfo])
async def list_skills() -> list[SkillInfo]:
    return [
        SkillInfo(
            id=spec.id,
            name=spec.name,
            description=spec.description,
            mode=spec.mode.value,
            enabled=spec.enabled,
            owner_agents=list(spec.owner_agents),
            capabilities=list(spec.capabilities),
        )
        for spec in skill_registry.specs()
    ]


@app.get("/api/overview", response_model=OverviewStats)
async def overview() -> OverviewStats:
    registry = build_registry(store)
    counts = store.overview_counts()
    enabled_skills = sum(1 for spec in skill_registry.specs() if spec.enabled)
    return OverviewStats(
        enabled_experts=len(registry.ids(enabled_only=True)),
        enabled_skills=enabled_skills,
        total_tasks=counts["total_tasks"],
        completed_tasks=counts["completed_tasks"],
        report_count=counts["report_count"],
        average_completion=counts["average_completion"],
    )


@app.get("/api/tasks", response_model=list[TaskSummary])
async def list_tasks() -> list[TaskSummary]:
    return [TaskSummary(**row) for row in store.list_tasks()]


@app.get("/api/tasks/{task_id}", response_model=TaskDetail)
async def get_task(task_id: str) -> TaskDetail:
    task = store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return TaskDetail(**task)


@app.get("/api/reports", response_model=list[ReportSummary])
async def list_reports() -> list[ReportSummary]:
    return [ReportSummary(**row) for row in store.list_reports()]


@app.get("/api/reports/{report_id}", response_model=ReportDetail)
async def get_report(report_id: str) -> ReportDetail:
    report = store.get_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    return ReportDetail(**report)


# -- expert enable/disable ---------------------------------------------------


@app.post("/api/experts/{agent_id}/enabled", response_model=ExpertInfo)
async def set_expert_enabled(
    agent_id: str,
    request: ExpertToggleRequest,
) -> ExpertInfo:
    try:
        expert = AgentId(agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="未知专家") from exc
    if expert == AgentId.PORTFOLIO and request.enabled:
        raise HTTPException(
            status_code=409,
            detail="Portfolio 专家没有运行实现，暂不可启用。",
        )
    store.set_override(expert.value, request.enabled)
    _rebuild_experts()
    definition = build_registry(store).get(expert)
    return ExpertInfo(
        id=definition.id.value,
        name=definition.name,
        description=definition.description,
        enabled=definition.enabled,
        capabilities=list(definition.capabilities),
        tools=list(definition.tools),
        skills=[
            spec.id for spec in skill_registry.allowed_for_agent(expert.value)
        ],
    )


# -- planning session / clarify / stream -------------------------------------


@app.post("/api/tasks/sessions", response_model=SessionResponse)
async def create_session(request: RouteRequest) -> SessionResponse:
    try:
        plan = await run_in_threadpool(manager.create_plan, request.prompt)
    except ManagerAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    task_id = uuid.uuid4().hex
    status = "needs_clarification" if plan.needs_clarification else "planned"
    store.create_task(
        task_id=task_id,
        prompt=request.prompt,
        status=status,
        plan=plan.model_dump(mode="json"),
    )
    store.append_event(
        task_id,
        type="plan_created",
        message="Manager Agent 已创建并验证动态任务图。",
        metadata={
            "step_count": len(plan.steps),
            "selected_agents": [
                selection.agent.value for selection in plan.selected_agents
            ],
        },
    )
    if plan.needs_clarification:
        store.append_event(
            task_id,
            type="clarification_required",
            message=plan.clarification_question or "任务需要补充关键信息。",
            metadata={
                "options": [
                    group.model_dump(mode="json")
                    for group in plan.clarification_options
                ]
            },
        )
    return SessionResponse(task_id=task_id, plan=plan)


@app.post("/api/tasks/{task_id}/clarify", response_model=SessionResponse)
async def clarify_session(task_id: str, request: ClarifyRequest) -> SessionResponse:
    task = store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    try:
        plan = await run_in_threadpool(
            manager.resume,
            task["prompt"],
            request.answers,
        )
    except ManagerAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    status = "needs_clarification" if plan.needs_clarification else "planned"
    store.update_task_plan(task_id, status=status, plan=plan.model_dump(mode="json"))
    store.append_event(
        task_id,
        type="plan_created",
        message="Manager Agent 已根据澄清答案重新规划任务图。",
        metadata={
            "step_count": len(plan.steps),
            "selected_agents": [
                selection.agent.value for selection in plan.selected_agents
            ],
        },
    )
    if plan.needs_clarification:
        store.append_event(
            task_id,
            type="clarification_required",
            message=plan.clarification_question or "任务仍需补充关键信息。",
            metadata={
                "options": [
                    group.model_dump(mode="json")
                    for group in plan.clarification_options
                ]
            },
        )
    return SessionResponse(task_id=task_id, plan=plan)


@app.get("/api/tasks/{task_id}/stream")
async def stream_task(task_id: str) -> StreamingResponse:
    task = store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task["plan"] is None:
        raise HTTPException(status_code=409, detail="任务尚未生成计划")
    plan = ExecutionPlan.model_validate(task["plan"])
    prompt = task["prompt"]
    already_executed = task["status"] not in {"planned"}
    persisted_events = task["events"]

    async def event_stream() -> Any:
        for event in persisted_events:
            yield _sse(event)
        if plan.needs_clarification or already_executed:
            yield _sse_named("done", {"task_id": task_id, "status": task["status"]})
            return

        queue: asyncio.Queue[Any] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def sink(event: ExecutionEvent) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, event)

        def run() -> None:
            try:
                events, results = workflow_executor.execute(
                    plan, prompt, event_sink=sink
                )
                loop.call_soon_threadsafe(
                    queue.put_nowait, ("__done__", events, results)
                )
            except Exception as exc:  # surface failure to the stream, never hang
                loop.call_soon_threadsafe(queue.put_nowait, ("__error__", exc))

        loop.run_in_executor(None, run)

        results: dict[str, ExpertResult] = {}
        while True:
            item = await queue.get()
            if isinstance(item, tuple) and item and item[0] == "__done__":
                results = item[2]
                break
            if isinstance(item, tuple) and item and item[0] == "__error__":
                store.finish_task(task_id, status="failed")
                yield _sse_named("error", {"detail": "任务执行失败"})
                return
            event = item
            _persist_event(task_id, event)
            yield _sse(_event_to_dict(event))

        synthesis = ExecutionEvent(
            type="synthesis_started",
            message="Result Aggregator 开始整理实际执行结果。",
            metadata={"component": "result_aggregator"},
        )
        _persist_event(task_id, synthesis)
        yield _sse(_event_to_dict(synthesis))

        aggregation = await run_in_threadpool(
            result_aggregator.aggregate, prompt, plan, results
        )
        completed = ExecutionEvent(
            type="task_completed",
            message="AlphaOS 任务处理完成。",
            metadata={
                "completed_steps": sum(
                    r.status == "completed" for r in results.values()
                ),
                "failed_steps": sum(
                    r.status in {"failed", "blocked"} for r in results.values()
                ),
            },
        )
        _persist_event(task_id, completed)
        yield _sse(_event_to_dict(completed))

        record = build_report_record(task_id, plan, aggregation, results)
        report_id = uuid.uuid4().hex
        store.create_report(
            report_id=report_id,
            task_id=task_id,
            title=record["title"],
            completeness=record["completeness"],
            aggregation=record["aggregation"],
        )
        store.finish_task(
            task_id,
            status=aggregation.completion_status,
            aggregation=aggregation.model_dump(mode="json"),
            final_answer=(
                f"{aggregation.direct_answer.headline}\n\n"
                f"{aggregation.direct_answer.explanation}"
            ),
        )
        yield _sse_named(
            "aggregation",
            {
                "report_id": report_id,
                "completeness": record["completeness"],
                "aggregation": record["aggregation"],
            },
        )
        yield _sse_named(
            "done",
            {"task_id": task_id, "status": aggregation.completion_status},
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# -- report follow-up (deterministic evidence retrieval) ---------------------


@app.post("/api/reports/{report_id}/followup", response_model=FollowupAnswer)
async def report_followup(
    report_id: str,
    request: FollowupRequest,
) -> FollowupAnswer:
    report = store.get_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    store.add_followup(
        followup_id=uuid.uuid4().hex,
        report_id=report_id,
        role="user",
        text=request.question,
    )
    evidence = _retrieve_evidence(report.get("aggregation"), request.question)
    answer_text = (
        "以下为报告内证据检索结果，未调用模型，也不构成新的分析。"
        if evidence
        else "报告证据中未检索到与该问题直接相关的片段，请参考完整报告或补充提问。"
    )
    return FollowupAnswer.model_validate(
        store.add_followup(
            followup_id=uuid.uuid4().hex,
            report_id=report_id,
            role="assistant",
            text=answer_text,
            evidence=evidence,
        )
    )


# -- legacy endpoints (kept for compatibility) -------------------------------


@app.post("/api/route", response_model=RouteDecision, deprecated=True)
async def route_request(request: RouteRequest) -> RouteDecision:
    try:
        return await run_in_threadpool(router.route, request.prompt)
    except RouterAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/plan", response_model=ExecutionPlan)
async def plan_request(request: RouteRequest) -> ExecutionPlan:
    try:
        return await run_in_threadpool(manager.create_plan, request.prompt)
    except ManagerAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/tasks", response_model=TaskExecutionResponse)
async def execute_task(request: RouteRequest) -> TaskExecutionResponse:
    started_at = perf_counter()
    task_id = uuid.uuid4().hex
    try:
        plan = await run_in_threadpool(manager.create_plan, request.prompt)
        status = "needs_clarification" if plan.needs_clarification else "running"
        store.create_task(
            task_id=task_id,
            prompt=request.prompt,
            status=status,
            plan=plan.model_dump(mode="json"),
        )
        events = [
            ExecutionEvent(
                type="plan_created",
                message="Manager Agent 已创建并验证动态任务图。",
                metadata={
                    "step_count": len(plan.steps),
                    "selected_agents": [
                        selection.agent.value
                        for selection in plan.selected_agents
                    ],
                },
            )
        ]
        results: dict[str, ExpertResult]
        if plan.needs_clarification:
            events.append(
                ExecutionEvent(
                    type="clarification_required",
                    message=plan.clarification_question
                    or "任务需要补充关键信息。",
                )
            )
            results = {}
        else:
            execution_events, results = await run_in_threadpool(
                workflow_executor.execute,
                plan,
                request.prompt,
            )
            events.extend(execution_events)
            events.append(
                ExecutionEvent(
                    type="synthesis_started",
                    message="Result Aggregator 开始整理实际执行结果。",
                    metadata={"component": "result_aggregator"},
                )
            )
        aggregation = await run_in_threadpool(
            result_aggregator.aggregate,
            request.prompt,
            plan,
            results,
        )
        final_answer = (
            f"{aggregation.direct_answer.headline}\n\n"
            f"{aggregation.direct_answer.explanation}"
        )
        events.append(
            ExecutionEvent(
                type="task_completed",
                message="AlphaOS 任务处理完成。",
                metadata={
                    "completed_steps": sum(
                        result.status == "completed"
                        for result in results.values()
                    ),
                    "failed_steps": sum(
                        result.status in {"failed", "blocked"}
                        for result in results.values()
                    ),
                },
            )
        )
    except ManagerAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    for event in events:
        _persist_event(task_id, event)
    if not plan.needs_clarification:
        record = build_report_record(task_id, plan, aggregation, results)
        store.create_report(
            report_id=uuid.uuid4().hex,
            task_id=task_id,
            title=record["title"],
            completeness=record["completeness"],
            aggregation=record["aggregation"],
        )
    store.finish_task(
        task_id,
        status=aggregation.completion_status,
        aggregation=aggregation.model_dump(mode="json"),
        final_answer=final_answer,
        duration_ms=max(0, round((perf_counter() - started_at) * 1000)),
    )
    return TaskExecutionResponse(
        plan=plan,
        events=events,
        results=results,
        aggregation=aggregation,
        final_answer=final_answer,
        duration_ms=max(0, round((perf_counter() - started_at) * 1000)),
        disclaimer=RESEARCH_DISCLAIMER,
    )


@app.post("/api/market-data", response_model=MarketDataResponse)
async def market_data(request: MarketDataRequest) -> MarketDataResponse:
    if request.start_date > request.end_date:
        raise HTTPException(status_code=422, detail="start_date 不能晚于 end_date")
    try:
        data = await run_in_threadpool(
            pandadata.get_market_data,
            symbols=request.symbols,
            start_date=request.start_date,
            end_date=request.end_date,
            fields=request.fields,
            indicator=request.indicator,
            st=request.st,
        )
    except PandaDataConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"PandaData 调用失败: {exc}") from exc
    return MarketDataResponse(
        symbols=request.symbols,
        start_date=request.start_date,
        end_date=request.end_date,
        data=data,
    )


# -- helpers -----------------------------------------------------------------


def _event_to_dict(event: ExecutionEvent) -> dict[str, Any]:
    return event.model_dump(mode="json")


def _persist_event(task_id: str, event: ExecutionEvent) -> None:
    store.append_event(
        task_id,
        type=event.type,
        message=event.message,
        agent=event.agent.value if event.agent else None,
        step_id=event.step_id,
        metadata=event.metadata,
        ts=event.timestamp.isoformat(),
    )


def _sse(data: dict[str, Any]) -> str:
    return "data: " + json.dumps(data, ensure_ascii=False) + "\n\n"


def _sse_named(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\n" + "data: " + json.dumps(data, ensure_ascii=False) + "\n\n"


def _retrieve_evidence(
    aggregation: dict[str, Any] | None,
    question: str,
) -> list[dict[str, Any]]:
    """Deterministically rank stored evidence fragments against the question."""

    fragments = _aggregation_fragments(aggregation)
    if not fragments:
        return []
    terms = _query_terms(question)
    if not terms:
        return []

    scored: list[dict[str, Any]] = []
    for fragment in fragments:
        haystack = fragment["text"].lower()
        score = sum(haystack.count(term) for term in terms)
        if score > 0:
            scored.append({**fragment, "score": score})
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:5]


def _query_terms(question: str) -> list[str]:
    """Build match terms: latin/number word tokens plus CJK character bigrams.

    Chinese has no whitespace tokens, so a whole phrase would form one oversized
    token that never matches. Emitting CJK bigrams keeps retrieval deterministic
    while actually matching Chinese report text.
    """

    lowered = question.lower()
    terms: set[str] = set()
    for token in re.split(r"\W+", lowered):
        if len(token) >= 2 and token.isascii():
            terms.add(token)
    for run in re.findall(r"[\u4e00-\u9fff]+", lowered):
        if len(run) == 1:
            terms.add(run)
        else:
            terms.update(run[i : i + 2] for i in range(len(run) - 1))
    return list(terms)


def _aggregation_fragments(
    aggregation: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(aggregation, dict):
        return []
    fragments: list[dict[str, Any]] = []
    direct = aggregation.get("direct_answer")
    if isinstance(direct, dict):
        for key in ("headline", "explanation"):
            text = direct.get(key)
            if isinstance(text, str) and text.strip():
                fragments.append({"source": f"direct_answer.{key}", "text": text.strip()})
    for block in aggregation.get("content_blocks", []) or []:
        if not isinstance(block, dict):
            continue
        source = block.get("id") or block.get("type") or "block"
        for key in ("title", "description"):
            text = block.get(key)
            if isinstance(text, str) and text.strip():
                fragments.append({"source": str(source), "text": text.strip()})
        data = block.get("data")
        rendered = _stringify_block_data(data)
        if rendered:
            fragments.append({"source": str(source), "text": rendered})
    return fragments


def _stringify_block_data(data: Any) -> str:
    texts: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            if value.strip():
                texts.append(value.strip())
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(data)
    return " ".join(texts)[:2_000]
