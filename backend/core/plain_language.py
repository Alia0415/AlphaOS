"""Central plain-language translations for user-facing aggregation output."""

from __future__ import annotations

from typing import Any


VALIDATION_LABELS = {
    "unverified": "尚未验证",
    "computed_not_validated": "已完成计算，但尚未证明能够稳定有效",
    "mixed_unvalidated": "多项计算已经完成，但整体有效性尚未验证",
    "insufficient_data": "当前证据不足，暂时无法可靠判断",
    "weak_positive_evidence": "已有初步支持，但证据仍然较弱",
    "moderate_positive_evidence": "已有多项证据支持，但仍需核对稳定性",
}

METRIC_LABELS = {
    "maximum_drawdown": "最大回撤",
    "annualized_volatility": "年化波动率",
    "daily_volatility": "日波动率",
    "period_return": "区间收益率",
    "coverage_ratio": "可正常计算的数据占比",
    "observation_count": "使用的数据条数",
    "non_null_count": "成功计算的数据条数",
    "highest_close": "区间最高收盘价",
    "lowest_close": "区间最低收盘价",
    "average_volume": "平均成交量",
}

PERCENT_METRICS = {
    "maximum_drawdown",
    "annualized_volatility",
    "daily_volatility",
    "period_return",
    "coverage_ratio",
}


def validation_label(status: str | None) -> str:
    """Translate a validation state while preserving unknown professional terms."""

    if not status:
        return "未声明验证状态"
    return VALIDATION_LABELS.get(status, status.replace("_", " "))


def metric_card(name: str, value: Any, *, subject: str | None = None) -> dict[str, Any]:
    """Build one readable metric without discarding its professional field name."""

    display_value = _format_metric(name, value)
    label = METRIC_LABELS.get(name, name.replace("_", " "))
    explanation = _metric_explanation(name, value)
    return {
        "metric": name,
        "label": label,
        "value": value,
        "display_value": display_value,
        "subject": subject,
        "explanation": explanation,
    }


def plain_text(value: Any) -> str:
    """Translate recurring technical status phrases in arbitrary evidence text."""

    text = str(value or "").strip()
    replacements = {
        "computed_not_validated": VALIDATION_LABELS["computed_not_validated"],
        "unverified": VALIDATION_LABELS["unverified"],
        "dependency blocked": "因前置分析未完成，本步骤无法继续",
        "Required dependency failed": "因前置分析未完成，本步骤无法继续",
        "low confidence": "当前证据较少，结论可信度较低",
        "maximum_drawdown": "最大回撤（区间内从阶段高点到低点的最大跌幅）",
        "annualized_volatility": "年化波动率（用于衡量价格波动有多大）",
    }
    for technical, readable in replacements.items():
        text = text.replace(technical, readable)
    return text


def _format_metric(name: str, value: Any) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        if name in PERCENT_METRICS:
            return f"{value:.2%}"
        if isinstance(value, int):
            return f"{value:,}"
        return f"{value:,.4g}"
    return str(value)


def _metric_explanation(name: str, value: Any) -> str:
    if name == "maximum_drawdown" and isinstance(value, (int, float)):
        return (
            "这意味着在该时间段内，如果恰好在阶段高点买入，"
            f"最大可能经历约 {abs(value):.2%} 的账面下跌。"
        )
    explanations = {
        "annualized_volatility": "用于衡量价格一年尺度上的波动有多大，数值越高，价格起伏通常越明显。",
        "daily_volatility": "用于衡量日常价格变化的幅度，数值越高，短期价格起伏通常越明显。",
        "period_return": "表示指定起止日期之间的价格变化，不代表未来还能获得相同结果。",
        "coverage_ratio": "表示原始数据中有多少比例能够正常参与本次计算。",
        "observation_count": "表示本次指标或分析实际覆盖的数据记录数量。",
        "non_null_count": "表示完成必要清洗后真正得到计算结果的数据记录数量。",
        "highest_close": "这是指定区间内出现过的最高收盘价。",
        "lowest_close": "这是指定区间内出现过的最低收盘价。",
        "average_volume": "这是指定区间内的平均成交量，仅描述历史交易活跃程度。",
    }
    return explanations.get(name, f"专业字段：{name}。")
