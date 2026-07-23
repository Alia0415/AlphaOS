"""Research Agent backed by PandaData and deterministic Python calculations."""

from __future__ import annotations

import json
import math
import statistics
from collections.abc import Mapping, Sequence
from datetime import datetime
import re
from typing import Any, Literal
from uuid import uuid4

from backend.agents.research_skill_planner import (
    ResearchSkillPlan,
    ResearchSkillPlanner,
)
from backend.core.contracts import AgentId, ExpertResult, ExpertTask
from backend.services.ark_client import ArkClient, ArkClientError
from backend.services.pandadata_client import (
    PandaDataClient,
    PandaDataConfigurationError,
)
from backend.skills.contracts import SkillInvocation, SkillResult, SkillStatus
from backend.skills.skill_registry import SkillRegistry


class ResearchAgent:
    """Fetch market observations, calculate evidence, then ask Ark to explain it."""

    def __init__(
        self,
        data_client: PandaDataClient | None = None,
        ark_client: ArkClient | None = None,
        skill_registry: SkillRegistry | None = None,
        skill_planner: ResearchSkillPlanner | None = None,
    ) -> None:
        self._data_client = data_client or PandaDataClient()
        self._ark_client = ark_client
        self.skills = skill_registry or SkillRegistry(ark_client=ark_client)
        self._skill_planner = skill_planner or ResearchSkillPlanner(
            registry=self.skills,
            ark_client=ark_client,
        )

    def execute(self, task: ExpertTask) -> ExpertResult:
        if task.agent != AgentId.RESEARCH:
            return _failed(task, "Research Agent 收到了不匹配的任务类型。")
        plan = self._skill_planner.create_plan(task)
        if plan.selected_skills:
            return self._execute_dossier(task, plan)
        return self._execute_market(task)

    def _execute_market(self, task: ExpertTask) -> ExpertResult:
        inputs = task.inputs
        symbols = _symbols(inputs.get("symbols"))
        start_date = str(inputs.get("start_date", "")).strip()
        end_date = str(inputs.get("end_date", "")).strip()
        fields = _fields(inputs.get("fields", []))
        validation_error = _validate_request(symbols, start_date, end_date)
        if validation_error:
            return _failed(task, validation_error)

        requested_fields = fields or ["trade_date", "symbol", "close", "volume"]
        tool_call = {
            "tool": "pandadata_market_data",
            "status": "started",
            "arguments": {
                "symbols": symbols,
                "start_date": start_date,
                "end_date": end_date,
                "fields": fields,
            },
        }
        try:
            raw_data = self._data_client.get_market_data(
                symbols=symbols,
                start_date=start_date,
                end_date=end_date,
                fields=fields,
                indicator=str(inputs.get("indicator", "000300")),
                st=bool(inputs.get("st", True)),
            )
        except Exception as exc:
            tool_call["status"] = "failed"
            return _failed(
                task,
                f"PandaData 调用失败：{_safe_error(exc)}",
                tool_calls=[tool_call],
            )

        tool_call["status"] = "completed"
        rows = _extract_rows(raw_data)
        if not rows:
            return _failed(
                task,
                "PandaData 在指定股票和日期范围内未返回可分析的数据。",
                tool_calls=[tool_call],
                data_sources=[_source(symbols, start_date, end_date, requested_fields, 0)],
            )

        evidence: list[dict[str, Any]] = []
        try:
            for symbol in symbols:
                symbol_rows = _rows_for_symbol(rows, symbol, len(symbols))
                if not symbol_rows:
                    raise ValueError(f"{symbol} 没有返回观测数据")
                evidence.append(
                    {
                        "type": "market_metrics",
                        "symbol": symbol,
                        **_calculate_metrics(symbol_rows),
                    }
                )
        except ValueError as exc:
            return _failed(
                task,
                f"市场数据字段不足：{exc}",
                tool_calls=[tool_call],
                data_sources=[
                    _source(
                        symbols,
                        start_date,
                        end_date,
                        requested_fields,
                        len(rows),
                    )
                ],
            )

        sources = [
            _source(symbols, start_date, end_date, requested_fields, len(rows))
        ]
        limitations = [
            "结论仅覆盖指定时间区间的历史日频市场数据。",
            "历史表现不能推导未来收益。",
        ]
        deterministic_summary = _deterministic_summary(evidence)
        summary = deterministic_summary
        try:
            explanation = self._get_ark_client().chat(
                _explanation_prompt(task, evidence, sources)
            ).strip()
            if explanation:
                summary = explanation
        except (ArkClientError, Exception):
            limitations.append(
                "Ark 解释服务不可用；当前摘要由已计算的确定性指标降级生成。"
            )

        return ExpertResult(
            task_id=task.task_id,
            agent=AgentId.RESEARCH,
            status="completed",
            summary=summary,
            evidence=evidence,
            assumptions=["PandaData 返回的收盘价和成交量口径在区间内一致。"],
            risks=["市场数据分析不包含公司基本面、估值和未来事件信息。"],
            limitations=limitations,
            recommendations=["如需决策，应补充基本面、估值与更长时间窗口的证据。"],
            tool_calls=[tool_call],
            data_sources=sources,
            metadata={
                "calculation_engine": "python",
                "requested_fields": requested_fields,
                "raw_observation_count": len(rows),
            },
        )

    def _execute_dossier(
        self,
        task: ExpertTask,
        plan: ResearchSkillPlan,
    ) -> ExpertResult:
        selection = plan.selected_skills[0]
        scope = selection.scope
        agent_events: list[dict[str, Any]] = [
            {
                "type": "skill_plan_created",
                "metadata": {
                    "skill_id": None,
                    "selected_skill_count": 1,
                    "skill_step_count": 1,
                    "scope": scope,
                },
            }
        ]
        symbol = _dossier_symbol(task.inputs)
        if symbol is None:
            question = (
                "个股财报分析需要明确的 A 股代码（XXXXXX.SH 或 XXXXXX.SZ）；"
                "当前输入无法可靠解析，请补充代码。"
            )
            return _failed(
                task,
                question,
                metadata={
                    "needs_clarification": True,
                    "clarification_question": question,
                    "skill_plan": plan.model_dump(mode="json"),
                    "actual_skills": [],
                    "agent_events": agent_events,
                },
            )
        try:
            start_period, end_period = _financial_period_range(task.inputs)
        except ValueError as exc:
            return _failed(
                task,
                str(exc),
                metadata={
                    "needs_clarification": True,
                    "skill_plan": plan.model_dump(mode="json"),
                    "actual_skills": [],
                    "agent_events": agent_events,
                },
            )

        financial_data, data_scope, tool_calls, unavailable = (
            self._collect_dossier_data(
                symbol=symbol,
                start_period=start_period,
                end_period=end_period,
                scope=scope,
            )
        )
        invocation_inputs = {
            **task.inputs,
            "symbol": symbol,
            "scope": scope,
            "start_period": start_period,
            "end_period": end_period,
            "financial_data": financial_data,
            "data_scope": data_scope,
        }
        if unavailable:
            invocation_inputs["data_unavailable_reason"] = unavailable
        agent_events.append(
            {
                "type": "skill_started",
                "skill_id": selection.skill_id,
                "metadata": {
                    "skill_id": selection.skill_id,
                    "scope": scope,
                },
            }
        )
        result = self.skills.execute(
            SkillInvocation(
                invocation_id=str(uuid4()),
                skill_id=selection.skill_id,
                agent=AgentId.RESEARCH.value,
                objective=task.objective,
                inputs=invocation_inputs,
            )
        )
        tool_calls.append(
            {
                "tool": selection.skill_id,
                "status": result.status.value,
                "arguments": {
                    "symbol": symbol,
                    "scope": scope,
                    "start_period": start_period,
                    "end_period": end_period,
                },
            }
        )
        event_type = (
            "skill_completed"
            if result.status == SkillStatus.COMPLETED
            else "skill_failed"
        )
        agent_events.append(
            {
                "type": event_type,
                "skill_id": selection.skill_id,
                "metadata": {
                    "skill_id": selection.skill_id,
                    "status": result.status.value,
                    "scope": scope,
                },
            }
        )
        return _dossier_expert_result(
            task=task,
            plan=plan,
            scope=scope,
            result=result,
            tool_calls=tool_calls,
            data_scope=data_scope,
            agent_events=agent_events,
        )

    def _collect_dossier_data(
        self,
        *,
        symbol: str,
        start_period: str,
        end_period: str,
        scope: str,
    ) -> tuple[
        dict[str, Any],
        list[dict[str, Any]],
        list[dict[str, Any]],
        str | None,
    ]:
        calls: list[tuple[str, dict[str, Any]]] = [
            (
                "get_fina_reports",
                {
                    "symbol": symbol,
                    "start_period": start_period,
                    "end_period": end_period,
                    "fields": None,
                },
            ),
            (
                "get_fina_performance",
                {"symbol": symbol, "end_period": end_period, "fields": None},
            ),
            (
                "get_fina_forecast",
                {"symbol": symbol, "end_period": end_period, "fields": None},
            ),
            (
                "get_audit_opinion",
                {
                    "symbol": symbol,
                    "start_period": start_period,
                    "end_period": end_period,
                    "fields": None,
                },
            ),
        ]
        if scope == "full_dossier":
            start_date = f"{start_period[:4]}0101"
            end_date = f"{end_period[:4]}1231"
            calls.extend(
                [
                    ("get_stock_detail", {"symbol": symbol}),
                    ("get_stock_industry", {"symbol": symbol}),
                    (
                        "get_share_float",
                        {
                            "symbol": symbol,
                            "start_date": start_date,
                            "end_date": end_date,
                        },
                    ),
                    (
                        "get_stock_status_change",
                        {
                            "symbol": symbol,
                            "start_date": start_date,
                            "end_date": end_date,
                        },
                    ),
                    (
                        "get_stock_dividend",
                        {
                            "symbol": symbol,
                            "start_date": start_date,
                            "end_date": end_date,
                        },
                    ),
                    (
                        "get_stock_cash_dividend",
                        {
                            "symbol": symbol,
                            "start_date": start_date,
                            "end_date": end_date,
                        },
                    ),
                    (
                        "get_stock_dividend_amount",
                        {
                            "symbol": symbol,
                            "start_date": start_date,
                            "end_date": end_date,
                        },
                    ),
                    (
                        "get_repurchase",
                        {
                            "symbol": symbol,
                            "start_date": start_date,
                            "end_date": end_date,
                        },
                    ),
                    (
                        "get_stock_private_placement",
                        {
                            "symbol": symbol,
                            "start_date": start_date,
                            "end_date": end_date,
                        },
                    ),
                    (
                        "get_stock_allotment",
                        {
                            "symbol": symbol,
                            "start_date": start_date,
                            "end_date": end_date,
                        },
                    ),
                    (
                        "get_stock_split",
                        {
                            "symbol": symbol,
                            "start_date": start_date,
                            "end_date": end_date,
                        },
                    ),
                    (
                        "get_investor_activity",
                        {
                            "symbol": symbol,
                            "start_date": start_date,
                            "end_date": end_date,
                        },
                    ),
                    (
                        "get_top_holders",
                        {
                            "symbol": symbol,
                            "start_date": start_date,
                            "end_date": end_date,
                        },
                    ),
                    (
                        "get_holder_count",
                        {
                            "symbol": symbol,
                            "start_date": start_date,
                            "end_date": end_date,
                        },
                    ),
                    (
                        "get_stock_pledge",
                        {
                            "symbol": symbol,
                            "start_date": start_date,
                            "end_date": end_date,
                        },
                    ),
                    (
                        "get_stock_shareholder_change",
                        {
                            "symbol": symbol,
                            "start_date": start_date,
                            "end_date": end_date,
                        },
                    ),
                    (
                        "get_restricted_list",
                        {
                            "symbol": symbol,
                            "start_date": start_date,
                            "end_date": end_date,
                        },
                    ),
                    (
                        "get_stock_daily",
                        {
                            "symbol": symbol,
                            "start_date": start_date,
                            "end_date": end_date,
                        },
                    ),
                    (
                        "get_lhb_list",
                        {
                            "symbol": symbol,
                            "start_date": start_date,
                            "end_date": end_date,
                        },
                    ),
                    (
                        "get_lhb_detail",
                        {
                            "symbol": symbol,
                            "start_date": start_date,
                            "end_date": end_date,
                        },
                    ),
                    (
                        "get_block_trade",
                        {
                            "symbol": symbol,
                            "start_date": start_date,
                            "end_date": end_date,
                        },
                    ),
                    (
                        "get_margin",
                        {
                            "symbol": symbol,
                            "start_date": start_date,
                            "end_date": end_date,
                        },
                    ),
                    (
                        "get_hsgt_hold",
                        {
                            "symbol": symbol,
                            "start_date": start_date,
                            "end_date": end_date,
                        },
                    ),
                ]
            )

        datasets: dict[str, Any] = {}
        data_scope: list[dict[str, Any]] = []
        tool_calls: list[dict[str, Any]] = []
        financial_failures = 0
        first_unavailable: str | None = None
        for method, arguments in calls:
            tool_call = {
                "tool": method,
                "status": "started",
                "arguments": _safe_query_arguments(arguments),
            }
            tool_calls.append(tool_call)
            try:
                function = getattr(self._data_client, method)
                response = function(**arguments)
            except Exception as exc:
                tool_call["status"] = "unavailable"
                if method in {
                    "get_fina_reports",
                    "get_fina_performance",
                    "get_fina_forecast",
                    "get_audit_opinion",
                }:
                    financial_failures += 1
                first_unavailable = first_unavailable or _safe_error(exc)
                data_scope.append(
                    {
                        "method": method,
                        "symbol": symbol,
                        "query_range": _query_range(arguments),
                        "row_count": 0,
                        "latest_report_period": None,
                        "missing_status": "unavailable",
                    }
                )
                continue
            tool_call["status"] = "completed"
            datasets[method] = response
            rows = _extract_rows(response)
            data_scope.append(
                {
                    "method": method,
                    "symbol": symbol,
                    "query_range": _query_range(arguments),
                    "row_count": len(rows),
                    "latest_report_period": _latest_report_period(rows),
                    "missing_status": "available" if rows else "no_data",
                }
            )
        unavailable = (
            first_unavailable
            if financial_failures == 4
            else None
        )
        return datasets, data_scope, tool_calls, unavailable

    def __call__(self, task: ExpertTask) -> ExpertResult:
        return self.execute(task)

    def _get_ark_client(self) -> ArkClient:
        if self._ark_client is None:
            self._ark_client = ArkClient()
        return self._ark_client


def _symbols(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip().upper() for item in value if str(item).strip()]


def _fields(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _validate_request(
    symbols: list[str],
    start_date: str,
    end_date: str,
) -> str | None:
    if not symbols:
        return "Research Agent 需要 inputs.symbols。"
    try:
        start = datetime.strptime(start_date, "%Y%m%d")
        end = datetime.strptime(end_date, "%Y%m%d")
    except ValueError:
        return "start_date 和 end_date 必须是 YYYYMMDD 格式的有效日期。"
    if start > end:
        return "start_date 不能晚于 end_date。"
    return None


def _extract_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(row) for row in value if isinstance(row, Mapping)]
    if not isinstance(value, Mapping):
        return []
    for key in ("data", "records", "rows", "result"):
        nested = value.get(key)
        rows = _extract_rows(nested)
        if rows:
            return rows
    if value and all(
        isinstance(item, Sequence) and not isinstance(item, (str, bytes))
        for item in value.values()
    ):
        lengths = {len(item) for item in value.values()}
        if len(lengths) == 1:
            return [
                {str(key): values[index] for key, values in value.items()}
                for index in range(next(iter(lengths)))
            ]
    return []


def _rows_for_symbol(
    rows: list[dict[str, Any]],
    symbol: str,
    symbol_count: int,
) -> list[dict[str, Any]]:
    symbol_keys = ("symbol", "ts_code", "code", "ticker")
    filtered = [
        row
        for row in rows
        if any(str(row.get(key, "")).upper() == symbol for key in symbol_keys)
    ]
    return filtered or (rows if symbol_count == 1 else [])


def _calculate_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    date_key = _first_key(rows, ("trade_date", "date", "datetime", "time"))
    close_key = _first_key(rows, ("close", "close_price", "收盘价"))
    volume_key = _first_key(rows, ("volume", "vol", "成交量"), required=False)
    if close_key is None:
        raise ValueError("缺少 close 收盘价字段")

    ordered = sorted(rows, key=lambda row: str(row.get(date_key or "", "")))
    closes = [_number(row.get(close_key)) for row in ordered]
    if any(value is None for value in closes):
        raise ValueError("close 收盘价包含空值或非数值")
    clean_closes = [float(value) for value in closes if value is not None]
    if not clean_closes:
        raise ValueError("没有有效收盘价")
    if any(value <= 0 for value in clean_closes):
        raise ValueError("close 收盘价必须为正数")

    daily_returns = [
        clean_closes[index] / clean_closes[index - 1] - 1
        for index in range(1, len(clean_closes))
    ]
    peak = clean_closes[0]
    maximum_drawdown = 0.0
    for close in clean_closes:
        peak = max(peak, close)
        maximum_drawdown = min(maximum_drawdown, close / peak - 1)

    volumes: list[float] = []
    if volume_key is not None:
        volumes = [
            number
            for row in ordered
            if (number := _number(row.get(volume_key))) is not None
        ]

    return {
        "date_start": str(ordered[0].get(date_key, "")) if date_key else None,
        "date_end": str(ordered[-1].get(date_key, "")) if date_key else None,
        "observation_count": len(clean_closes),
        "period_return": (
            clean_closes[-1] / clean_closes[0] - 1
            if len(clean_closes) > 1
            else 0.0
        ),
        "daily_volatility": (
            statistics.stdev(daily_returns) if len(daily_returns) > 1 else 0.0
        ),
        "maximum_drawdown": maximum_drawdown,
        "average_volume": statistics.fmean(volumes) if volumes else None,
        "volume_trend": _volume_trend(volumes),
        "highest_close": max(clean_closes),
        "lowest_close": min(clean_closes),
    }


def _first_key(
    rows: list[dict[str, Any]],
    candidates: tuple[str, ...],
    *,
    required: bool = True,
) -> str | None:
    keys = {str(key).lower(): str(key) for row in rows for key in row}
    for candidate in candidates:
        if candidate.lower() in keys:
            return keys[candidate.lower()]
    if required:
        return None
    return None


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _volume_trend(volumes: list[float]) -> str | None:
    if len(volumes) < 2:
        return None
    midpoint = len(volumes) // 2
    first = statistics.fmean(volumes[:midpoint])
    second = statistics.fmean(volumes[midpoint:])
    if first == 0:
        return "unknown"
    change = second / first - 1
    if change > 0.05:
        return "increasing"
    if change < -0.05:
        return "decreasing"
    return "stable"


def _source(
    symbols: list[str],
    start_date: str,
    end_date: str,
    fields: list[str],
    observations: int,
) -> dict[str, Any]:
    return {
        "name": "PandaData",
        "symbols": symbols,
        "start_date": start_date,
        "end_date": end_date,
        "fields": fields,
        "observation_count": observations,
    }


def _deterministic_summary(evidence: list[dict[str, Any]]) -> str:
    parts = []
    for item in evidence:
        parts.append(
            f"{item['symbol']} 共 {item['observation_count']} 个观测，"
            f"区间收益率 {item['period_return']:.2%}，"
            f"最大回撤 {item['maximum_drawdown']:.2%}。"
        )
    return "".join(parts)


def _explanation_prompt(
    task: ExpertTask,
    evidence: list[dict[str, Any]],
    sources: list[dict[str, Any]],
) -> str:
    payload = {
        "objective": task.objective,
        "evidence_calculated_by_python": evidence,
        "data_sources": sources,
    }
    return f"""
你是 AlphaOS Research Agent。以下所有数值均已由 Python 计算。
只解释证据、提炼发现并说明局限；不要重新计算数字、补造数据、给出买入卖出建议、
保证收益或引入上下文中不存在的事实。用简洁中文返回一段研究摘要。

结构化证据：
{json.dumps(payload, ensure_ascii=False)}
""".strip()


def _failed(
    task: ExpertTask,
    error: str,
    *,
    tool_calls: list[dict[str, Any]] | None = None,
    data_sources: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ExpertResult:
    return ExpertResult(
        task_id=task.task_id,
        agent=AgentId.RESEARCH,
        status="failed",
        summary="Research Agent 未能完成市场数据分析。",
        limitations=[error],
        tool_calls=tool_calls or [],
        data_sources=data_sources or [],
        metadata=metadata or {},
        error=error,
    )


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, PandaDataConfigurationError):
        return str(exc)
    return "外部市场数据服务请求失败"


def _dossier_symbol(inputs: Mapping[str, Any]) -> str | None:
    candidate = inputs.get("symbol")
    if not candidate:
        symbols = inputs.get("symbols")
        if isinstance(symbols, list) and len(symbols) == 1:
            candidate = symbols[0]
    value = str(candidate or "").strip().upper()
    if re.fullmatch(r"\d{6}\.(?:SH|SZ)", value):
        return value
    if re.fullmatch(r"\d{6}", value):
        if value.startswith(("600", "601", "603", "605", "688", "689")):
            return f"{value}.SH"
        if value.startswith(("000", "001", "002", "003", "300", "301")):
            return f"{value}.SZ"
    return None


def _financial_period_range(inputs: Mapping[str, Any]) -> tuple[str, str]:
    start = str(inputs.get("start_period", "")).strip().lower()
    end = str(inputs.get("end_period", "")).strip().lower()
    if not start and not end:
        period = str(
            inputs.get("period", "latest_3_fiscal_years")
        ).strip().lower()
        match = re.fullmatch(r"latest_(\d+)_fiscal_years", period)
        years = int(match.group(1)) if match else 3
        if years < 1 or years > 5:
            raise ValueError("财务年度窗口必须在一到五年之间。")
        end_year = datetime.now().year - 1
        return f"{end_year - years + 1}q4", f"{end_year}q4"
    if not start or not end:
        raise ValueError("start_period 和 end_period 必须同时提供。")
    pattern = re.compile(r"^(\d{4})q([1-4])$")
    start_match = pattern.fullmatch(start)
    end_match = pattern.fullmatch(end)
    if start_match is None or end_match is None:
        raise ValueError("start_period 和 end_period 必须是 YYYYqN 格式。")
    start_index = int(start_match.group(1)) * 4 + int(start_match.group(2))
    end_index = int(end_match.group(1)) * 4 + int(end_match.group(2))
    if start_index > end_index:
        raise ValueError("start_period 不能晚于 end_period。")
    if end_index - start_index > 20:
        raise ValueError("财务查询窗口不能超过五年。")
    return start, end


def _safe_query_arguments(arguments: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "symbol",
        "start_period",
        "end_period",
        "start_date",
        "end_date",
    }
    return {
        key: value
        for key, value in arguments.items()
        if key in allowed
    }


def _query_range(arguments: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: arguments[key]
        for key in ("start_period", "end_period", "start_date", "end_date")
        if key in arguments
    }


def _latest_report_period(rows: list[dict[str, Any]]) -> str | None:
    values: list[str] = []
    for row in rows:
        for key in (
            "quarter",
            "end_quarter",
            "report_period",
            "end_date",
            "report_date",
            "info_date",
            "trade_date",
        ):
            value = str(row.get(key, "")).strip()
            if value:
                values.append(value)
                break
    return max(values) if values else None


def _dossier_expert_result(
    *,
    task: ExpertTask,
    plan: ResearchSkillPlan,
    scope: str,
    result: SkillResult,
    tool_calls: list[dict[str, Any]],
    data_scope: list[dict[str, Any]],
    agent_events: list[dict[str, Any]],
) -> ExpertResult:
    validation_status = (
        result.data.get("overall_assessment", {}).get(
            "validation_status",
            "unavailable",
        )
        if isinstance(result.data.get("overall_assessment"), Mapping)
        else "unavailable"
    )
    risks = [
        str(item.get("statement"))
        for item in result.data.get("risk_signals", [])
        if isinstance(item, Mapping) and item.get("statement")
    ]
    evidence = [
        {
            "type": "skill_result",
            "skill_id": result.skill_id,
            "status": result.status.value,
            "validation_status": validation_status,
            "data": result.data,
        }
    ]
    status: Literal["completed", "failed"] = (
        "completed"
        if result.status == SkillStatus.COMPLETED
        else "failed"
    )
    data_sources = [
        {"name": "PandaData", **item}
        for item in data_scope
    ]
    if result.provenance:
        data_sources.append(
            {
                "name": result.provenance.get("source_repository"),
                "commit": result.provenance.get("source_commit"),
                "license": result.provenance.get("license"),
            }
        )
    return ExpertResult(
        task_id=task.task_id,
        agent=AgentId.RESEARCH,
        status=status,
        summary=result.summary,
        evidence=evidence,
        assumptions=result.assumptions,
        risks=risks,
        limitations=result.limitations,
        recommendations=[
            "将异常信号作为后续核查线索，不应直接解释为已确认原因。",
            "公开财务数据分析不构成买卖建议或未来收益保证。",
        ],
        tool_calls=tool_calls,
        data_sources=data_sources,
        metadata={
            "skill_plan": plan.model_dump(mode="json"),
            "actual_skills": [result.skill_id],
            "validation_status": validation_status,
            "scope": scope,
            "skill_results": {
                result.skill_id: result.model_dump(mode="json"),
            },
            "agent_events": agent_events,
            "provenance": result.provenance,
        },
        error=result.error if status == "failed" else None,
    )
