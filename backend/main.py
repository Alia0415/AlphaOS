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
from backend.core.contracts import (
    ExecutionEvent,
    ExecutionPlan,
    ExpertResult,
    RESEARCH_DISCLAIMER,
    TaskExecutionResponse,
)
from backend.core.evidence_validator import EvidenceValidator
from backend.core.policy_gate import PolicyGate
from backend.core.result_aggregator import ResultAggregator
from backend.core.result_policy_checker import ResultPolicyChecker
from backend.core.task_interpreter import TaskInterpreter
from backend.core.workflow_executor import WorkflowExecutor
from backend.services.pandadata_client import (
    PandaDataClient,
    PandaDataConfigurationError,
)


app = FastAPI(title="AlphaOS API", version="0.3.0")
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
policy_gate = PolicyGate()
task_interpreter = TaskInterpreter()
evidence_validator = EvidenceValidator()
result_policy_checker = ResultPolicyChecker()


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


@app.post("/api/plan", response_model=ExecutionPlan)
async def plan_request(request: RouteRequest) -> ExecutionPlan:
    try:
        return await run_in_threadpool(manager.create_plan, request.prompt)
    except ManagerAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/tasks", response_model=TaskExecutionResponse)
async def execute_task(request: RouteRequest) -> TaskExecutionResponse:
    started_at = perf_counter()
    try:
        policy = policy_gate.evaluate(request.prompt)
        if not policy.allowed:
            aggregation = result_policy_checker.check(
                result_aggregator.build_boundary_response(request.prompt, policy)
            )
            events = [
                ExecutionEvent(
                    type="policy_checked",
                    message="AlphaOS 已完成请求边界判断。",
                    metadata={
                        "decision": policy.decision,
                        "allowed": False,
                        "policy_tags": policy.policy_tags,
                    },
                ),
                ExecutionEvent(
                    type="result_policy_checked",
                    message="AlphaOS 已完成最终结果合规检查。",
                    metadata={"policy_rewrite": aggregation.metadata["policy_rewrite"]},
                ),
                ExecutionEvent(
                    type="task_completed",
                    message="AlphaOS 已返回能力边界说明。",
                    metadata={"completed_steps": 0, "failed_steps": 0},
                ),
            ]
            return TaskExecutionResponse(
                plan=None,
                events=events,
                results={},
                aggregation=aggregation,
                final_answer=(
                    f"{aggregation.direct_answer.headline}\n\n"
                    f"{aggregation.direct_answer.explanation}"
                ),
                duration_ms=max(
                    0,
                    round((perf_counter() - started_at) * 1000),
                ),
                disclaimer=RESEARCH_DISCLAIMER,
            )

        task_spec = task_interpreter.interpret(request.prompt, policy)
        if task_spec.execution_decision == "clarify":
            aggregation = result_policy_checker.check(
                result_aggregator.build_clarification_response(task_spec)
            )
            events = [
                ExecutionEvent(
                    type="clarification_required",
                    message=task_spec.clarification_question
                    or "任务需要补充关键信息。",
                    metadata={"missing_fields": task_spec.missing_fields},
                ),
                ExecutionEvent(
                    type="task_completed",
                    message="AlphaOS 已返回澄清请求。",
                    metadata={"completed_steps": 0, "failed_steps": 0},
                ),
            ]
            return TaskExecutionResponse(
                plan=None,
                events=events,
                results={},
                aggregation=aggregation,
                final_answer=(
                    f"{aggregation.direct_answer.headline}\n\n"
                    f"{aggregation.direct_answer.explanation}"
                ),
                duration_ms=max(
                    0,
                    round((perf_counter() - started_at) * 1000),
                ),
                disclaimer=RESEARCH_DISCLAIMER,
            )

        plan = await run_in_threadpool(
            manager.create_plan,
            task_spec,
            request.prompt,
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
            clarification_spec = task_spec.model_copy(
                update={
                    "execution_decision": "clarify",
                    "clarification_question": plan.clarification_question,
                }
            )
            aggregation = result_policy_checker.check(
                result_aggregator.build_clarification_response(
                    clarification_spec
                )
            )
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
            evidence_validation = await run_in_threadpool(
                evidence_validator.validate,
                task_spec,
                plan,
                results,
            )
            aggregation = await run_in_threadpool(
                result_aggregator.aggregate,
                task_spec,
                plan,
                evidence_validation,
            )
            aggregation = await run_in_threadpool(
                result_policy_checker.check,
                aggregation,
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
