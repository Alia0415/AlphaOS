"""Macro Agent backed by allowlisted PandaData macro evidence and Ark analysis."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, Field, ValidationError

from backend.core.contracts import AgentId, ExpertResult, ExpertTask
from backend.services.ark_client import ArkClient, ArkClientError
from backend.services.pandadata_client import (
    MACRO_API_ALLOWLIST,
    MACRO_DATASETS,
    PandaDataClient,
    PandaDataConfigurationError,
)

HISTORICAL_MONTHS = 24
MAX_CATALOG_ROWS = 500
MAX_RECENT_OBSERVATIONS = 6
SERIES_FIELDS = ["symbol", "period_date", "data_value"]

CATALOG_FIELDS = [
    "symbol",
    "name",
    "en_name",
    "frequency",
    "unit",
    "importance",
    "info_source",
    "note_text",
    "end_date",
    "is_update",
    "api_name",
]

_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "macro.md"
_API_TO_CATEGORY = {api_name: code for code, (api_name, _) in MACRO_DATASETS.items()}

ModelT = TypeVar("ModelT", bound=BaseModel)


class MacroDataPlan(BaseModel):
    categories: list[str] = Field(min_length=1, max_length=4)
    indicator_search_terms: list[str] = Field(
        default_factory=list,
        max_length=8,
    )
    reasoning: list[str] = Field(default_factory=list, max_length=8)


class MacroIndicator(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    rationale: str = Field(min_length=1, max_length=500)


class MacroIndicatorSelection(BaseModel):
    indicators: list[MacroIndicator] = Field(min_length=1, max_length=8)


class MacroAnalysis(BaseModel):
    conclusion: str = Field(min_length=1, max_length=2_000)
    economic_cycle: str = Field(min_length=1, max_length=1_000)
    interest_rate: str = Field(min_length=1, max_length=1_000)
    policy_factors: list[str] = Field(default_factory=list, max_length=12)
    liquidity: str = Field(min_length=1, max_length=1_000)
    market_environment: str = Field(min_length=1, max_length=1_000)
    positive_factors: list[str] = Field(default_factory=list, max_length=12)
    risks: list[str] = Field(default_factory=list, max_length=12)


class MacroAgentError(RuntimeError):
    """Raised when Macro planning, validation, or analysis cannot proceed."""


@dataclass
class RepairBudget:
    remaining: int = 1


class MacroAgent:
    """Plan bounded PandaData macro queries, then analyze validated evidence."""

    def __init__(
        self,
        data_client: PandaDataClient | None = None,
        ark_client: ArkClient | None = None,
        today_provider: Callable[[], date] = date.today,
    ) -> None:
        self._data_client = data_client or PandaDataClient()
        self._ark_client = ark_client
        self._today_provider = today_provider

    def __call__(self, task: ExpertTask) -> ExpertResult:
        return self.execute(task)

    def execute(self, task: ExpertTask) -> ExpertResult:
        if task.agent != AgentId.MACRO:
            return _failed(task, "Macro Agent 收到了不匹配的任务类型。")

        inputs = task.inputs
        industry = str(inputs.get("industry", "")).strip()
        time_range = str(inputs.get("time_range", "")).strip()
        research_goal = str(inputs.get("research_goal", "")).strip()
        if not industry or not time_range or not research_goal:
            return _failed(
                task,
                "Macro Agent 需要 industry、time_range 和 research_goal。",
            )

        window = _resolve_window(inputs, self._today_provider)
        if window is None:
            return _failed(
                task,
                "start_date 和 end_date 必须是 YYYYMMDD 格式且不倒置。",
            )
        start_date, end_date = window
        budget = RepairBudget()

        try:
            client = self._get_client()
            plan = _structured_stage(
                client,
                _plan_prompt(task, start_date, end_date),
                MacroDataPlan,
                budget,
            )
            invalid = set(plan.categories) - set(MACRO_DATASETS)
            if invalid:
                raise MacroAgentError("Macro 选择了未授权的宏观分类。")

            catalog_rows = self._data_client.get_macro_catalog(
                categories=plan.categories,
                fields=CATALOG_FIELDS,
            )
            candidates = _bound_catalog(catalog_rows, plan)
            if not candidates:
                return _failed(task, "PandaData 未返回可用的宏观指标目录。")
            catalog_by_symbol = {row["symbol"]: row for row in candidates}

            selection = _structured_stage(
                client,
                _selection_prompt(task, candidates),
                MacroIndicatorSelection,
                budget,
            )
            selection = _validate_membership(
                client,
                selection,
                catalog_by_symbol,
                budget,
            )

            (
                evidence,
                tool_calls,
                data_sources,
                any_failed,
                any_success,
            ) = self._fetch_series(selection, catalog_by_symbol, start_date, end_date)
            if not any_success or not evidence:
                return _failed(
                    task,
                    "PandaData 未返回可用于分析的宏观指标数据。",
                    tool_calls=tool_calls,
                    data_sources=data_sources,
                )

            analysis = _structured_stage(
                client,
                _analysis_prompt(task, evidence, start_date, end_date),
                MacroAnalysis,
                budget,
            )
        except MacroAgentError as exc:
            return _failed(task, str(exc))
        except PandaDataConfigurationError:
            return _failed(task, "PandaData 宏观数据服务不可用。")
        except ArkClientError:
            return _failed(task, "Macro 分析所需的 Ark 服务不可用。")
        except (ValueError, ValidationError, json.JSONDecodeError):
            return _failed(task, "Macro 无法完成结构化宏观分析。")

        limitations = [
            "结论仅基于指定历史窗口内已发布的 PandaData 宏观数据。",
            "历史指标变化用于情景分析，不代表未来结果。",
        ]
        if any_failed and any_success:
            limitations.append(
                "部分 PandaData 指标不可用；结论仅基于成功返回的指标。"
            )

        return ExpertResult(
            task_id=task.task_id,
            agent=AgentId.MACRO,
            status="completed",
            summary=analysis.conclusion,
            evidence=evidence,
            assumptions=[
                f"前瞻判断以 {start_date} 至 {end_date} 的已发布历史数据为基础。",
                "历史指标变化用于情景分析，不代表未来结果。",
            ],
            risks=analysis.risks,
            limitations=limitations,
            recommendations=[
                "在形成投资决策前核对最新宏观发布值、政策文件和行业基本面。"
            ],
            tool_calls=tool_calls,
            data_sources=data_sources,
            metadata={
                "analysis_basis": "pandadata_macro_data",
                "historical_window": {
                    "start_date": start_date,
                    "end_date": end_date,
                },
                "forward_horizon": str(task.inputs["time_range"]),
                "data_plan": {
                    **plan.model_dump(mode="json"),
                    "indicators": selection.model_dump(mode="json")["indicators"],
                },
                "macro_analysis": analysis.model_dump(mode="json"),
            },
        )

    def _fetch_series(
        self,
        selection: MacroIndicatorSelection,
        catalog_by_symbol: dict[str, dict[str, Any]],
        start_date: str,
        end_date: str,
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
        bool,
        bool,
    ]:
        selected_symbols = [indicator.symbol for indicator in selection.indicators]
        groups: dict[str, list[str]] = {}
        for symbol in selected_symbols:
            api_name = catalog_by_symbol[symbol]["api_name"]
            groups.setdefault(api_name, []).append(symbol)

        tool_calls: list[dict[str, Any]] = []
        data_sources: list[dict[str, Any]] = []
        series_by_symbol: dict[str, dict[str, Any]] = {}
        any_failed = False
        any_success = False

        for api_name, symbols in groups.items():
            call = {
                "tool": "pandadata_macro_data",
                "status": "started",
                "arguments": {
                    "api_name": api_name,
                    "symbols": symbols,
                    "start_date": start_date,
                    "end_date": end_date,
                    "fields": SERIES_FIELDS,
                },
            }
            tool_calls.append(call)
            try:
                raw_rows = self._data_client.get_macro_data(
                    api_name=api_name,
                    symbols=symbols,
                    start_date=start_date,
                    end_date=end_date,
                    fields=SERIES_FIELDS,
                )
            except Exception:
                call["status"] = "failed"
                any_failed = True
                continue

            rows = _extract_rows(raw_rows)
            group_series = 0
            for symbol in symbols:
                symbol_rows = [
                    row
                    for row in rows
                    if str(row.get("symbol", "")).strip() == symbol
                ] or (rows if len(symbols) == 1 else [])
                summary = _series_summary(
                    symbol,
                    symbol_rows,
                    catalog_by_symbol[symbol],
                )
                if summary is not None:
                    series_by_symbol[symbol] = summary
                    group_series += 1

            if group_series == 0:
                call["status"] = "failed"
                any_failed = True
                continue

            call["status"] = "completed"
            any_success = True
            data_sources.append(
                {
                    "name": "PandaData",
                    "api_name": api_name,
                    "symbols": symbols,
                    "start_date": start_date,
                    "end_date": end_date,
                    "row_count": len(rows),
                }
            )

        evidence = [
            series_by_symbol[symbol]
            for symbol in selected_symbols
            if symbol in series_by_symbol
        ]
        return evidence, tool_calls, data_sources, any_failed, any_success

    def _get_client(self) -> ArkClient:
        if self._ark_client is None:
            self._ark_client = ArkClient()
        return self._ark_client


def _resolve_window(
    inputs: Mapping[str, Any],
    today_provider: Callable[[], date],
) -> tuple[str, str] | None:
    start = str(inputs.get("start_date", "")).strip()
    end = str(inputs.get("end_date", "")).strip()
    if start or end:
        start_obj = _parse_date(start)
        end_obj = _parse_date(end)
        if start_obj is None or end_obj is None or start_obj > end_obj:
            return None
        return start, end
    today = today_provider()
    start_obj = _subtract_months(today, HISTORICAL_MONTHS)
    return start_obj.strftime("%Y%m%d"), today.strftime("%Y%m%d")


def _parse_date(value: str) -> date | None:
    if len(value) != 8 or not value.isdigit():
        return None
    try:
        return date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    except ValueError:
        return None


def _subtract_months(value: date, months: int) -> date:
    month_index = value.month - 1 - months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, _days_in_month(year, month))
    return date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    first_next = date(year + (month // 12), month % 12 + 1, 1)
    return (first_next - date(year, month, 1)).days


def _structured_stage(
    client: ArkClient,
    prompt: str,
    model_type: type[ModelT],
    budget: RepairBudget,
) -> ModelT:
    raw = client.chat(prompt)
    try:
        return model_type.model_validate(_extract_json(raw))
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        if budget.remaining == 0:
            raise MacroAgentError("Macro 结构化输出无效。") from None
        budget.remaining -= 1
        repaired = client.chat(
            _repair_prompt(prompt, raw, str(exc), model_type.model_json_schema())
        )
        try:
            return model_type.model_validate(_extract_json(repaired))
        except (json.JSONDecodeError, ValidationError, ValueError):
            raise MacroAgentError(
                "Macro 结构化输出在一次修复后仍无效。"
            ) from None


def _validate_membership(
    client: ArkClient,
    selection: MacroIndicatorSelection,
    catalog_by_symbol: dict[str, dict[str, Any]],
    budget: RepairBudget,
) -> MacroIndicatorSelection:
    if _membership_ok(selection, catalog_by_symbol):
        return selection
    if budget.remaining == 0:
        raise MacroAgentError("Macro 指标选择超出目录允许范围。")
    budget.remaining -= 1
    repaired = client.chat(
        _membership_repair_prompt(catalog_by_symbol)
    )
    try:
        selection = MacroIndicatorSelection.model_validate(_extract_json(repaired))
    except (json.JSONDecodeError, ValidationError, ValueError):
        raise MacroAgentError(
            "Macro 指标选择在一次修复后仍无效。"
        ) from None
    if not _membership_ok(selection, catalog_by_symbol):
        raise MacroAgentError("Macro 指标选择在一次修复后仍超出目录范围。")
    return selection


def _membership_ok(
    selection: MacroIndicatorSelection,
    catalog_by_symbol: dict[str, dict[str, Any]],
) -> bool:
    symbols = [indicator.symbol for indicator in selection.indicators]
    if len(symbols) != len(set(symbols)):
        return False
    return all(symbol in catalog_by_symbol for symbol in symbols)


def _bound_catalog(
    rows: Any,
    plan: MacroDataPlan,
) -> list[dict[str, Any]]:
    terms = [term for term in plan.indicator_search_terms if term]
    candidates: list[dict[str, Any]] = []
    for row in _extract_rows(rows):
        api_name = str(row.get("api_name", "")).strip()
        symbol = str(row.get("symbol", "")).strip()
        if api_name not in MACRO_API_ALLOWLIST or not symbol:
            continue
        if row.get("is_update") not in (1, "1", True):
            continue
        projected = {key: row.get(key) for key in CATALOG_FIELDS}
        projected["symbol"] = symbol
        projected["api_name"] = api_name
        candidates.append(projected)

    def score(row: dict[str, Any]) -> tuple[int, int, str]:
        text = f"{row.get('name', '')}{row.get('en_name', '')}"
        term_hits = sum(1 for term in terms if term and term in text)
        importance = _importance_rank(row.get("importance"))
        end_date = str(row.get("end_date") or "")
        return (term_hits, importance, end_date)

    candidates.sort(key=score, reverse=True)
    return _category_balanced(candidates, MAX_CATALOG_ROWS)


def _category_balanced(
    candidates: list[dict[str, Any]],
    cap: int,
) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in candidates:
        code = _API_TO_CATEGORY.get(row["api_name"], row["api_name"])
        buckets.setdefault(code, []).append(row)
    balanced: list[dict[str, Any]] = []
    while len(balanced) < cap:
        added = False
        for code in list(buckets):
            if buckets[code]:
                balanced.append(buckets[code].pop(0))
                added = True
                if len(balanced) >= cap:
                    break
        if not added:
            break
    return balanced


def _importance_rank(value: Any) -> int:
    text = str(value or "")
    if "非常" in text or text == "重要":
        return 2
    if "重要" in text:
        return 1
    return 0


def _series_summary(
    symbol: str,
    rows: list[dict[str, Any]],
    metadata: dict[str, Any],
) -> dict[str, Any] | None:
    observations: list[dict[str, Any]] = []
    for row in rows:
        value = _number(row.get("data_value"))
        period = str(row.get("period_date", "")).strip()
        if value is None or not period:
            continue
        observations.append({"period_date": period, "data_value": value})
    observations.sort(key=lambda item: item["period_date"])
    observations = observations[-MAX_RECENT_OBSERVATIONS:]
    if not observations:
        return None

    latest = observations[-1]
    latest_value = latest["data_value"]
    previous_value = (
        observations[-2]["data_value"]
        if len(observations) >= 2
        else latest_value
    )
    return {
        "type": "macro_indicator",
        "symbol": symbol,
        "name": metadata["name"],
        "api_name": metadata["api_name"],
        "frequency": metadata.get("frequency"),
        "unit": metadata.get("unit"),
        "info_source": metadata.get("info_source"),
        "latest_period": latest["period_date"],
        "latest_value": latest_value,
        "previous_value": previous_value,
        "absolute_change": latest_value - previous_value,
        "percentage_change": (
            (latest_value - previous_value) / abs(previous_value)
            if previous_value != 0
            else None
        ),
        "observation_count": len(observations),
        "recent_observations": observations[-MAX_RECENT_OBSERVATIONS:],
    }


def _extract_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(row) for row in value if isinstance(row, Mapping)]
    if not isinstance(value, Mapping):
        return []
    for key in ("data", "records", "rows", "result"):
        nested = _extract_rows(value.get(key))
        if nested:
            return nested
    return []


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _role_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _plan_prompt(task: ExpertTask, start_date: str, end_date: str) -> str:
    context = {
        "industry": task.inputs.get("industry"),
        "time_range": task.inputs.get("time_range"),
        "research_goal": task.inputs.get("research_goal"),
        "historical_window": {"start_date": start_date, "end_date": end_date},
    }
    categories = {
        code: label for code, (_, label) in MACRO_DATASETS.items()
    }
    schema = MacroDataPlan.model_json_schema()
    return f"""{_role_prompt()}

阶段 1：宏观数据规划。
从下列 PandaData 宏观分类中选择 1-4 个与当前行业和研究目标最相关的分类代码，
并给出用于筛选具体指标的关键词（indicator_search_terms）。不要选择无关分类。

可用分类（代码到名称）：
{json.dumps(categories, ensure_ascii=False)}

任务上下文：
{json.dumps(context, ensure_ascii=False)}

只返回严格符合下列 JSON Schema 的 JSON：
{json.dumps(schema, ensure_ascii=False)}
""".strip()


def _selection_prompt(
    task: ExpertTask,
    candidates: list[dict[str, Any]],
) -> str:
    context = {
        "industry": task.inputs.get("industry"),
        "time_range": task.inputs.get("time_range"),
        "research_goal": task.inputs.get("research_goal"),
    }
    schema = MacroIndicatorSelection.model_json_schema()
    return f"""{_role_prompt()}

阶段 2：宏观指标选择。
只能从下列 PandaData 目录候选中选择 1-8 个最能支撑研究目标的指标。
symbol 必须与候选完全一致，不得虚构或改写。给出每个指标的选择理由。

候选指标目录：
{json.dumps(candidates, ensure_ascii=False)}

任务上下文：
{json.dumps(context, ensure_ascii=False)}

只返回严格符合下列 JSON Schema 的 JSON：
{json.dumps(schema, ensure_ascii=False)}
""".strip()


def _analysis_prompt(
    task: ExpertTask,
    evidence: list[dict[str, Any]],
    start_date: str,
    end_date: str,
) -> str:
    payload = {
        "industry": task.inputs.get("industry"),
        "time_range": task.inputs.get("time_range"),
        "research_goal": task.inputs.get("research_goal"),
        "historical_window": {"start_date": start_date, "end_date": end_date},
        "evidence_computed_by_python": evidence,
    }
    schema = MacroAnalysis.model_json_schema()
    return f"""{_role_prompt()}

阶段 3：宏观分析。以下所有数值均已由 Python 基于 PandaData 历史数据计算。
只解释证据，区分历史事实、前瞻解释与未知项；证据不足的维度请说明数据不足，
不要补造数据或引入未提供的实时信息。

结构化证据：
{json.dumps(payload, ensure_ascii=False)}

只返回严格符合下列 JSON Schema 的 JSON：
{json.dumps(schema, ensure_ascii=False)}
""".strip()


def _repair_prompt(
    original_prompt: str,
    raw: str,
    error: str,
    schema: dict[str, Any],
) -> str:
    return f"""
上一次 Macro 结构化输出无效。仅修复这一次。
只返回严格符合目标 JSON Schema 的 JSON，不要 Markdown、代码围栏或解释。

目标 JSON Schema：
{json.dumps(schema, ensure_ascii=False)}

验证错误：
{error}

无效输出：
{raw[:20_000]}

原始指令：
{original_prompt[:20_000]}
""".strip()


def _membership_repair_prompt(
    catalog_by_symbol: dict[str, dict[str, Any]],
) -> str:
    allowed = list(catalog_by_symbol)
    schema = MacroIndicatorSelection.model_json_schema()
    return f"""
上一次 Macro 指标选择包含目录之外或重复的 symbol。仅修复这一次。
只能从下列允许的 symbol 中选择 1-8 个，不得重复，不得虚构。

允许的 symbol：
{json.dumps(allowed, ensure_ascii=False)}

只返回严格符合下列 JSON Schema 的 JSON：
{json.dumps(schema, ensure_ascii=False)}
""".strip()


def _extract_json(value: str) -> Any:
    text = value.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
    return json.loads(text)


def _failed(
    task: ExpertTask,
    message: str,
    **kwargs: Any,
) -> ExpertResult:
    return ExpertResult(
        task_id=task.task_id,
        agent=task.agent,
        status="failed",
        summary="Macro Agent 未能完成宏观分析。",
        limitations=[message],
        error=message,
        **kwargs,
    )
