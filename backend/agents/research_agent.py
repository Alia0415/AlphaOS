"""Research Agent backed by PandaData and deterministic Python calculations."""

from __future__ import annotations

import json
import math
import statistics
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from backend.core.contracts import AgentId, ExpertResult, ExpertTask
from backend.services.ark_client import ArkClient, ArkClientError
from backend.services.pandadata_client import (
    PandaDataClient,
    PandaDataConfigurationError,
)


class ResearchAgent:
    """Fetch market observations, calculate evidence, then ask Ark to explain it."""

    def __init__(
        self,
        data_client: PandaDataClient | None = None,
        ark_client: ArkClient | None = None,
    ) -> None:
        self._data_client = data_client or PandaDataClient()
        self._ark_client = ark_client

    def execute(self, task: ExpertTask) -> ExpertResult:
        if task.agent != AgentId.RESEARCH:
            return _failed(task, "Research Agent 收到了不匹配的任务类型。")

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

    ordered = sorted(rows, key=lambda row: str(row.get(date_key, "")))
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
) -> ExpertResult:
    return ExpertResult(
        task_id=task.task_id,
        agent=AgentId.RESEARCH,
        status="failed",
        summary="Research Agent 未能完成市场数据分析。",
        limitations=[error],
        tool_calls=tool_calls or [],
        data_sources=data_sources or [],
        error=error,
    )


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, PandaDataConfigurationError):
        return str(exc)
    return "外部市场数据服务请求失败"
