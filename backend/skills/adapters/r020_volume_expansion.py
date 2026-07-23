"""Executable adapter for the allowlisted QuantSkills R020 factor."""

from __future__ import annotations

import importlib.util
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pandas as pd

from backend.skills.contracts import (
    SkillInvocation,
    SkillResult,
    SkillSpec,
    SkillStatus,
)
from backend.skills.loaders.instruction_skill_loader import (
    RuntimeSkillLocator,
    SkillUnavailableError,
)


REQUIRED_COLUMNS = ("date", "symbol", "open", "high", "low", "close", "volume")
COLUMN_ALIASES = {
    "trade_date": "date",
    "datetime": "date",
    "time": "date",
    "ts_code": "symbol",
    "code": "symbol",
    "ticker": "symbol",
    "vol": "volume",
}


class R020VolumeExpansionAdapter:
    """Load one pinned Python entrypoint and calculate values on caller data."""

    def __init__(self, *, locator: RuntimeSkillLocator) -> None:
        self._locator = locator

    def __call__(
        self,
        invocation: SkillInvocation,
        spec: SkillSpec,
    ) -> SkillResult:
        try:
            entrypoint, provenance = self._locator.resolve_entrypoint(spec)
        except SkillUnavailableError as exc:
            return _unavailable(invocation, str(exc))
        except ValueError:
            return _failed(invocation, "R020 runtime path 未通过安全校验。")

        try:
            frame = _normalize_market_data(invocation.inputs.get("market_data"))
        except ValueError as exc:
            return _failed(invocation, str(exc), provenance=provenance)

        try:
            module = _load_factor_module(entrypoint)
            compute_factor = getattr(module, "compute_factor")
            result = compute_factor(frame)
        except Exception:
            return _failed(
                invocation,
                "R020 compute_factor 执行失败。",
                provenance=provenance,
            )
        if not isinstance(result, pd.DataFrame):
            return _failed(
                invocation,
                "R020 compute_factor 未返回 DataFrame。",
                provenance=provenance,
            )

        factor_column = str(
            getattr(module, "FACTOR_COLUMN", "5d-z-scored-volume-expansion")
        )
        if factor_column not in result.columns:
            return _failed(
                invocation,
                "R020 输出缺少预期 factor column。",
                provenance=provenance,
            )
        factor_values = pd.to_numeric(result[factor_column], errors="coerce")
        non_null_count = int(factor_values.notna().sum())
        observation_count = int(len(result))
        coverage_ratio = (
            non_null_count / observation_count if observation_count else 0.0
        )
        latest_values = _latest_values(result, factor_column)
        dates = result["date"].astype(str)
        data = {
            "factor_id": "R020",
            "factor_name": "5D Z-Scored Volume Expansion",
            "factor_column": factor_column,
            "observation_count": observation_count,
            "non_null_count": non_null_count,
            "coverage_ratio": coverage_ratio,
            "latest_values_by_symbol": latest_values,
            "date_range": {
                "start": dates.min() if observation_count else None,
                "end": dates.max() if observation_count else None,
            },
            "source_repository": provenance["source_repository"],
            "source_commit": provenance["source_commit"],
            "license": provenance["license"],
            "validation_status": "computed_not_validated",
        }
        limitations = [
            "结果仅表示对输入 OHLCV 实际执行了因子公式，未验证预测有效性。",
            "未计算 IC、回测收益或交易绩效，也未生成买卖信号。",
        ]
        if coverage_ratio < 1:
            limitations.append("滚动窗口预热会产生空值，coverage 低于 100%。")
        return SkillResult(
            invocation_id=invocation.invocation_id,
            skill_id=invocation.skill_id,
            status=SkillStatus.COMPLETED,
            summary=(
                f"R020 已对 {observation_count} 个调用方输入观测执行，"
                f"非空覆盖率 {coverage_ratio:.2%}。"
            ),
            data=data,
            evidence=[
                {
                    "type": "factor_computation",
                    "factor_id": "R020",
                    "coverage_ratio": coverage_ratio,
                    "observation_count": observation_count,
                    "non_null_count": non_null_count,
                }
            ],
            assumptions=[
                "PandaData OHLCV 字段口径在所选区间和标的间一致。",
                "外部 Skill 的锁定 compute_factor 是本轮唯一计算实现。",
            ],
            limitations=limitations,
            provenance=provenance,
        )


def _normalize_market_data(value: Any) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        frame = value.copy()
    else:
        rows = _extract_rows(value)
        if not rows:
            raise ValueError("R020 没有收到可用的 PandaData OHLCV 数据。")
        frame = pd.DataFrame(rows)
    normalized_columns = [str(column).strip().lower() for column in frame.columns]
    if len(normalized_columns) != len(set(normalized_columns)):
        raise ValueError("OHLCV 数据包含重复列名。")
    frame.columns = normalized_columns
    renames = {
        source: target
        for source, target in COLUMN_ALIASES.items()
        if source in frame.columns and target not in frame.columns
    }
    frame = frame.rename(columns=renames)
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"R020 缺少必需 OHLCV 字段：{', '.join(missing)}。")

    frame = frame.loc[:, list(REQUIRED_COLUMNS)].copy()
    frame["date"] = frame["date"].astype(str)
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    if (frame["symbol"] == "").any() or (frame["date"] == "").any():
        raise ValueError("R020 的 date 或 symbol 包含空值。")
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if frame[column].isna().any():
            raise ValueError(f"R020 字段 {column} 包含空值或非数值。")
        if not frame[column].map(math.isfinite).all():
            raise ValueError(f"R020 字段 {column} 包含非有限数值。")
    return frame.sort_values(["symbol", "date"]).reset_index(drop=True)


def _extract_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(row) for row in value if isinstance(row, Mapping)]
    if not isinstance(value, Mapping):
        return []
    for key in ("data", "records", "rows", "result"):
        rows = _extract_rows(value.get(key))
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


def _load_factor_module(entrypoint: Path) -> ModuleType:
    module_name = "alphaos_runtime_r020"
    module_spec = importlib.util.spec_from_file_location(module_name, entrypoint)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError("Unable to construct module loader")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    if not callable(getattr(module, "compute_factor", None)):
        raise RuntimeError("Approved module has no compute_factor")
    return module


def _latest_values(
    frame: pd.DataFrame,
    factor_column: str,
) -> list[dict[str, Any]]:
    ordered = frame.sort_values(["symbol", "date"])
    latest = ordered.groupby("symbol", sort=False).tail(1)
    values: list[dict[str, Any]] = []
    for _, row in latest.iterrows():
        raw_value = row[factor_column]
        values.append(
            {
                "symbol": str(row["symbol"]),
                "date": str(row["date"]),
                "value": (
                    float(raw_value)
                    if pd.notna(raw_value) and math.isfinite(float(raw_value))
                    else None
                ),
            }
        )
    return values


def _failed(
    invocation: SkillInvocation,
    error: str,
    *,
    provenance: dict[str, Any] | None = None,
) -> SkillResult:
    return SkillResult(
        invocation_id=invocation.invocation_id,
        skill_id=invocation.skill_id,
        status=SkillStatus.FAILED,
        summary="R020 因子计算未成功完成。",
        limitations=[error],
        provenance=provenance or {},
        error=error,
    )


def _unavailable(invocation: SkillInvocation, error: str) -> SkillResult:
    return SkillResult(
        invocation_id=invocation.invocation_id,
        skill_id=invocation.skill_id,
        status=SkillStatus.UNAVAILABLE,
        summary="R020 Runtime Skill 未安装或不可用。",
        limitations=[error],
        error=error,
    )
