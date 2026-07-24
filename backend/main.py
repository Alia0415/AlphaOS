"""AlphaOS FastAPI application entry point."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from backend.agents.router_agent import (
    RouteDecision,
    RouterAgent,
    RouterAgentError,
)
from backend.agents.manager_agent import ManagerAgent, ManagerAgentError
from backend.conversation.store import (
    Conversation,
    TurnRecord,
    get_store,
)
from backend.core.contracts import (
    MAX_CLARIFICATION_ROUNDS,
    ClarificationTurn,
    ExecutionEvent,
    ExecutionPlan,
    ExpertResult,
    RESEARCH_DISCLAIMER,
    TaskExecutionResponse,
    format_clarification_questions,
)
from backend.core.result_aggregator import ResultAggregator
from backend.core.workflow_executor import WorkflowExecutor
from backend.services.pandadata_client import (
    PandaDataClient,
    PandaDataConfigurationError,
)


app = FastAPI(title="AlphaOS API", version="0.4.0")
FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"
app.mount(
    "/static",
    StaticFiles(directory=FRONTEND_DIR),
    name="frontend-static",
)
pandadata = PandaDataClient()
router = RouterAgent()
manager = ManagerAgent()
workflow_executor = WorkflowExecutor()
result_aggregator = ResultAggregator()
conversation_store = get_store()


class RouteRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, value: str) -> str:
        prompt = value.strip()
        if not prompt:
            raise ValueError("prompt 不能为空")
        return prompt


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


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/pandadata/status")
async def pandadata_status() -> dict[str, object]:
    return pandadata.status()


@app.post("/api/route", response_model=RouteDecision, deprecated=True)
async def route_request(request: RouteRequest) -> RouteDecision:
    try:
        return await run_in_threadpool(router.route, request.prompt)
    except RouterAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


class TaskRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    clarification_history: list[ClarificationTurn] = Field(
        default_factory=list, max_length=MAX_CLARIFICATION_ROUNDS
    )
    conversation_id: str | None = Field(
        default=None, max_length=64,
        description="Existing conversation ID to continue, or null for a new session.",
    )

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, value: str) -> str:
        prompt = value.strip()
        if not prompt:
            raise ValueError("prompt 不能为空")
        return prompt


@app.get("/api/conversations")
async def list_conversations() -> list[dict[str, Any]]:
    return [conv.to_meta() for conv in conversation_store.list_all()]


@app.get("/api/conversations/{conv_id}")
async def get_conversation(conv_id: str) -> dict[str, Any]:
    conv = conversation_store.get(conv_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    return {
        **conv.to_meta(),
        "turns": [turn.to_detail() for turn in conv.turns],
    }


@app.delete("/api/conversations/{conv_id}", status_code=204)
async def delete_conversation(conv_id: str) -> None:
    if not conversation_store.delete(conv_id):
        raise HTTPException(status_code=404, detail="对话不存在")


@app.post("/api/plan", response_model=ExecutionPlan)
async def plan_request(request: TaskRequest) -> ExecutionPlan:
    try:
        return await run_in_threadpool(
            manager.create_plan, request.prompt, request.clarification_history
        )
    except ManagerAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/tasks", response_model=TaskExecutionResponse)
async def execute_task(request: TaskRequest) -> TaskExecutionResponse:
    started_at = perf_counter()
    round_number = len(request.clarification_history) + 1

    conv: Conversation | None = None
    conversation_context: str | None = None
    if request.conversation_id:
        conv = conversation_store.get(request.conversation_id)
        if conv is None:
            raise HTTPException(
                status_code=404,
                detail=f"对话 {request.conversation_id} 不存在",
            )
        conversation_context = conv.build_history_context(exclude_turns=1)
    else:
        conv = conversation_store.create(title=request.prompt[:60])

    try:
        plan = await run_in_threadpool(
            manager.create_plan,
            request.prompt,
            request.clarification_history,
            conversation_context,
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
                    message=format_clarification_questions(
                        plan.clarification_questions
                    ),
                    metadata={
                        "round": round_number,
                        "max_rounds": MAX_CLARIFICATION_ROUNDS,
                        "questions": plan.clarification_questions,
                    },
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

    duration_ms = max(0, round((perf_counter() - started_at) * 1000))

    turn = TurnRecord(
        prompt=request.prompt,
        plan=plan,
        results=results,
        aggregation=aggregation,
        events=[e.model_dump(mode="json") for e in events],
        final_answer=final_answer,
        duration_ms=duration_ms,
    )
    conv.add_turn(turn)

    return TaskExecutionResponse(
        plan=plan,
        events=events,
        results=results,
        aggregation=aggregation,
        final_answer=final_answer,
        duration_ms=duration_ms,
        disclaimer=RESEARCH_DISCLAIMER,
        conversation_id=conv.id,
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
