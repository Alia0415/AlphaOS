"""Final deterministic policy defense for aggregated user-facing results."""

from __future__ import annotations

import re
from typing import Any

from backend.core.contracts import (
    AggregationResult,
    RESEARCH_DISCLAIMER,
    ValidationStatus,
)


_REPLACEMENTS = {
    "建议买入": "该研究结果不构成买入建议",
    "建议卖出": "该研究结果不构成卖出建议",
    "推荐持有": "该研究结果不构成持有建议",
    "可以建仓": "该研究结果不能作为建仓依据",
    "目标仓位": "研究范围不包含仓位建议",
    "目标收益": "研究范围不包含目标收益",
    "预计收益": "研究范围不包含未来收益预测",
    "保证收益": "不能保证任何未来收益",
    "一定上涨": "不能据此推断未来上涨",
    "一定会涨": "不能据此推断未来上涨",
    "稳赚": "不存在由本结果支持的确定收益",
    "最值得买": "不能根据本结果形成证券推荐",
    "当前应配置": "研究范围不包含当前配置建议",
    "强烈推荐": "不能根据本结果形成证券推荐",
}
_EXPECTED_RETURN = re.compile(
    r"(?:预计|预期)(?:年化)?收益(?:率)?(?:为|约为|约)?\s*[-+]?\d+(?:\.\d+)?%?"
)
_RANKING_RECOMMENDATION = re.compile(
    r"(?:因子)?排名(?:前|最高).{0,12}(?:推荐|买入|建仓)"
)
_GENERIC_STOCK_RECOMMENDATION = re.compile(
    r"(?:推荐|建议).{0,12}(?:股票|证券|标的)"
)
_HISTORY_TO_FUTURE = re.compile(
    r"历史.{0,18}(?:证明|意味着|保证).{0,12}(?:未来|上涨|收益)"
)


class ResultPolicyChecker:
    """Rewrite prohibited conclusions while preserving safe research facts."""

    def check(self, aggregation: AggregationResult) -> AggregationResult:
        payload = aggregation.model_dump(mode="json")
        rewritten_paths: list[str] = []
        validation_status = aggregation.validation.status
        payload = _rewrite_value(
            payload,
            path="",
            validation_status=validation_status,
            rewritten_paths=rewritten_paths,
        )
        metadata = dict(payload.get("metadata") or {})
        metadata["policy_rewrite"] = bool(rewritten_paths)
        metadata["policy_rewrite_paths"] = list(dict.fromkeys(rewritten_paths))
        payload["metadata"] = metadata
        payload["disclaimer"] = RESEARCH_DISCLAIMER
        return AggregationResult.model_validate(payload)


def _rewrite_value(
    value: Any,
    *,
    path: str,
    validation_status: ValidationStatus,
    rewritten_paths: list[str],
) -> Any:
    if isinstance(value, list):
        return [
            _rewrite_value(
                item,
                path=f"{path}[{index}]",
                validation_status=validation_status,
                rewritten_paths=rewritten_paths,
            )
            for index, item in enumerate(value)
        ]
    if isinstance(value, dict):
        return {
            key: (
                child
                if _protected_input_path(f"{path}.{key}".strip("."))
                else _rewrite_value(
                    child,
                    path=f"{path}.{key}".strip("."),
                    validation_status=validation_status,
                    rewritten_paths=rewritten_paths,
                )
            )
            for key, child in value.items()
        }
    if not isinstance(value, str):
        return value

    rewritten = value
    if _EXPECTED_RETURN.search(rewritten):
        if validation_status in {
            ValidationStatus.HISTORICALLY_TESTED,
            ValidationStatus.OUT_OF_SAMPLE_TESTED,
            ValidationStatus.STRESS_TESTED,
        }:
            rewritten = _EXPECTED_RETURN.sub(
                lambda match: (
                    match.group(0)
                    .replace("预计", "指定历史样本中的")
                    .replace("预期", "指定历史样本中的")
                    + "，不代表未来表现"
                ),
                rewritten,
            )
        else:
            rewritten = _EXPECTED_RETURN.sub(
                "未完成可支持该收益数值的真实历史测试",
                rewritten,
            )
    for unsafe, safe in _REPLACEMENTS.items():
        rewritten = rewritten.replace(unsafe, safe)
    if _GENERIC_STOCK_RECOMMENDATION.search(rewritten):
        rewritten = _GENERIC_STOCK_RECOMMENDATION.sub(
            "不能根据本研究形成证券推荐",
            rewritten,
        )
    if _RANKING_RECOMMENDATION.search(rewritten):
        rewritten = _RANKING_RECOMMENDATION.sub(
            "因子排名仅代表指定历史截面的模型计算结果，不构成证券推荐",
            rewritten,
        )
    if _HISTORY_TO_FUTURE.search(rewritten):
        rewritten = _HISTORY_TO_FUTURE.sub(
            "历史结果不能证明或保证未来表现",
            rewritten,
        )
    if (
        validation_status == ValidationStatus.COMPUTED_NOT_VALIDATED
        and "验证有效" in rewritten
    ):
        rewritten = rewritten.replace(
            "验证有效",
            "仅完成计算，尚未验证有效性",
        )
    if rewritten != value:
        rewritten_paths.append(path or "$")
    return rewritten


def _protected_input_path(path: str) -> bool:
    return path in {"user_goal", "task_understanding.research_goal"}
