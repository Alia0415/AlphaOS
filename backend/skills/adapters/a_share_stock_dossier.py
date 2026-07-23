"""Deterministic adapter for the pinned A-share stock dossier instructions."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from backend.skills.contracts import (
    SkillInvocation,
    SkillResult,
    SkillSpec,
    SkillStatus,
)
from backend.skills.loaders.instruction_skill_loader import (
    InstructionSkillLoader,
    SkillUnavailableError,
)


FINANCIAL_METHODS = (
    "get_fina_reports",
    "get_fina_performance",
    "get_fina_forecast",
    "get_audit_opinion",
)
FULL_DOSSIER_METHODS = (
    "get_stock_detail",
    "get_stock_industry",
    "get_share_float",
    "get_stock_status_change",
    "get_stock_dividend",
    "get_stock_cash_dividend",
    "get_stock_dividend_amount",
    "get_repurchase",
    "get_stock_private_placement",
    "get_stock_allotment",
    "get_stock_split",
    "get_investor_activity",
    "get_top_holders",
    "get_holder_count",
    "get_stock_shareholder_change",
    "get_stock_pledge",
    "get_restricted_list",
    "get_stock_daily",
    "get_lhb_list",
    "get_lhb_detail",
    "get_block_trade",
    "get_margin",
    "get_hsgt_hold",
)
VALIDATION_STATUS = "calculated_from_disclosed_financial_data"

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": (
        "is_revenue",
        "is_operating_revenue",
        "operating_revenue",
        "total_operating_revenue",
        "revenue",
        "营业收入",
    ),
    "operating_cost": (
        "is_operating_cost",
        "operating_cost",
        "cost_of_revenue",
        "营业成本",
    ),
    "gross_profit": ("is_gross_profit", "gross_profit", "毛利润"),
    "operating_profit": (
        "is_operate_profit",
        "is_operating_profit",
        "operating_profit",
        "op_profit",
        "营业利润",
    ),
    "net_profit": (
        "is_n_income_attr_p",
        "is_net_profit_parent",
        "net_profit_parent",
        "n_income_attr_p",
        "归母净利润",
    ),
    "net_profit_excluding_nonrecurring": (
        "is_net_after_nr",
        "net_profit_excluding_nonrecurring",
        "deducted_net_profit",
        "net_profit_deducted",
        "扣非净利润",
    ),
    "operating_cash_flow": (
        "cfs_net_cash_operating",
        "cfs_net_cashflow_operating",
        "cfs_cash_flow_operating",
        "net_cash_flow_operating",
        "n_cashflow_act",
        "经营活动现金流量净额",
    ),
    "total_assets": ("bs_total_assets", "total_assets", "total_asset", "资产总计"),
    "total_liabilities": (
        "bs_total_liab",
        "bs_total_liabilities",
        "total_liabilities",
        "total_liab",
        "负债合计",
    ),
    "total_equity": (
        "bs_total_hldr_eqy_exc_min_int",
        "bs_total_equity_parent",
        "total_equity_parent",
        "total_equity",
        "股东权益合计",
    ),
    "current_assets": (
        "bs_total_cur_assets",
        "bs_total_current_assets",
        "total_current_assets",
        "current_assets",
        "流动资产合计",
    ),
    "current_liabilities": (
        "bs_total_cur_liab",
        "bs_total_current_liabilities",
        "total_current_liabilities",
        "current_liabilities",
        "流动负债合计",
    ),
    "accounts_receivable": (
        "bs_net_accts_receive",
        "bs_accounts_receivable",
        "accounts_receivable",
        "acct_receivable",
        "应收账款",
    ),
    "inventory": ("bs_inventory", "inventory", "inventories", "存货"),
    "roe": ("roe", "roe_weighted", "weighted_roe", "净资产收益率"),
    "roa": ("roa", "return_on_assets", "总资产收益率"),
}


class AShareStockDossierAdapter:
    """Apply the reviewed methodology without executing upstream commands."""

    def __init__(self, *, loader: InstructionSkillLoader) -> None:
        self.loader = loader

    def __call__(
        self,
        invocation: SkillInvocation,
        spec: SkillSpec,
    ) -> SkillResult:
        try:
            loaded = self.loader.load(spec)
        except (OSError, ValueError, SkillUnavailableError) as exc:
            return SkillResult(
                invocation_id=invocation.invocation_id,
                skill_id=invocation.skill_id,
                status=SkillStatus.UNAVAILABLE,
                summary="A 股尽调 Skill 未安装或未通过锁定校验。",
                limitations=[str(exc)],
                error=str(exc),
            )

        unavailable = str(
            invocation.inputs.get("data_unavailable_reason", "")
        ).strip()
        if unavailable:
            return SkillResult(
                invocation_id=invocation.invocation_id,
                skill_id=invocation.skill_id,
                status=SkillStatus.UNAVAILABLE,
                summary="财务数据服务当前不可用，未生成财务数字。",
                limitations=[unavailable],
                provenance=_provenance(loaded.provenance),
                error=unavailable,
            )

        symbol = str(invocation.inputs.get("symbol", "")).strip().upper()
        scope = str(invocation.inputs.get("scope", "financials")).strip()
        financial_data = invocation.inputs.get("financial_data", {})
        if not isinstance(financial_data, Mapping):
            financial_data = {}
        rows_by_method = {
            method: _rows(financial_data.get(method))
            for method in FINANCIAL_METHODS
        }
        records = _financial_records(
            rows_by_method["get_fina_reports"],
            rows_by_method["get_fina_performance"],
        )
        analysis = _analyze(
            symbol=symbol,
            scope=scope,
            records=records,
            forecast_rows=rows_by_method["get_fina_forecast"],
            audit_rows=rows_by_method["get_audit_opinion"],
            data_scope=_data_scope(invocation.inputs.get("data_scope")),
        )
        status = analysis["overall_assessment"]["validation_status"]
        return SkillResult(
            invocation_id=invocation.invocation_id,
            skill_id=invocation.skill_id,
            status=SkillStatus.COMPLETED,
            summary=(
                f"{symbol} 财务分析完成，覆盖 {len(analysis['periods'])} 个报告期。"
                if status == VALIDATION_STATUS
                else f"{symbol} 查询完成，但指定范围内没有可计算的财务数据。"
            ),
            data=analysis,
            evidence=[
                {
                    "type": "methodology",
                    "facts_are_direct": True,
                    "derived_metrics_include_formulas": True,
                    "judgments_reference_evidence": True,
                }
            ],
            assumptions=[
                "跨期比较仅使用可识别为同口径年度报告的数据。",
                "PandaData 返回字段单位保持同一口径。",
            ],
            limitations=[
                "公开财务数据和确定性计算不能验证公司未来表现。",
                "缺少字段的指标会明确披露，不进行数值填补。",
            ],
            provenance=_provenance(loaded.provenance),
        )


def _analyze(
    *,
    symbol: str,
    scope: str,
    records: list[dict[str, Any]],
    forecast_rows: list[dict[str, Any]],
    audit_rows: list[dict[str, Any]],
    data_scope: list[dict[str, Any]],
) -> dict[str, Any]:
    sections: dict[str, dict[str, list[dict[str, Any]]]] = {
        name: {"facts": [], "derived_metrics": [], "judgments": []}
        for name in (
            "growth",
            "profitability",
            "cash_flow_quality",
            "solvency",
            "operating_efficiency",
            "audit_and_forecast",
        )
    }
    missing: list[str] = []
    risk_signals: list[dict[str, Any]] = []
    positive_signals: list[dict[str, Any]] = []

    for record in records:
        period = record["period"]
        for metric in (
            "revenue",
            "operating_profit",
            "net_profit",
            "net_profit_excluding_nonrecurring",
        ):
            _append_fact(sections["growth"], record, metric, period)
        for metric in ("roe", "roa"):
            _append_fact(sections["profitability"], record, metric, period)
        for metric in ("operating_cash_flow",):
            _append_fact(sections["cash_flow_quality"], record, metric, period)
        for metric in (
            "total_assets",
            "total_liabilities",
            "current_assets",
            "current_liabilities",
        ):
            _append_fact(sections["solvency"], record, metric, period)
        for metric in ("accounts_receivable", "inventory"):
            _append_fact(sections["operating_efficiency"], record, metric, period)

        _append_gross_margin(sections["profitability"], record, period)
        _derived_ratio(
            sections["profitability"],
            record,
            period,
            "operating_margin",
            ("operating_profit", "revenue"),
            "营业利润 / 营业收入",
            lambda profit, revenue: profit / revenue,
        )
        _derived_ratio(
            sections["profitability"],
            record,
            period,
            "net_margin",
            ("net_profit", "revenue"),
            "归母净利润 / 营业收入",
            lambda profit, revenue: profit / revenue,
        )
        _derived_ratio(
            sections["cash_flow_quality"],
            record,
            period,
            "operating_cash_flow_to_net_profit",
            ("operating_cash_flow", "net_profit"),
            "经营活动现金流量净额 / 归母净利润",
            lambda cash_flow, profit: cash_flow / profit,
        )
        _derived_ratio(
            sections["solvency"],
            record,
            period,
            "asset_liability_ratio",
            ("total_liabilities", "total_assets"),
            "负债合计 / 资产总计",
            lambda liabilities, assets: liabilities / assets,
        )
        _derived_ratio(
            sections["solvency"],
            record,
            period,
            "current_ratio",
            ("current_assets", "current_liabilities"),
            "流动资产合计 / 流动负债合计",
            lambda assets, liabilities: assets / liabilities,
        )
        for metric, numerator in (
            ("accounts_receivable_to_revenue", "accounts_receivable"),
            ("inventory_to_revenue", "inventory"),
        ):
            _derived_ratio(
                sections["operating_efficiency"],
                record,
                period,
                metric,
                (numerator, "revenue"),
                f"{numerator} / 营业收入",
                lambda value, revenue: value / revenue,
            )

    _append_growth_metrics(records, sections["growth"])
    _append_average_return_metrics(records, sections["profitability"])
    _append_efficiency_metrics(records, sections["operating_efficiency"])
    _append_trend_judgments(
        records,
        sections,
        positive_signals,
        risk_signals,
    )
    _append_audit_and_forecast(
        audit_rows,
        forecast_rows,
        sections["audit_and_forecast"],
        risk_signals,
    )

    required_metrics = {
        "营业收入": _has_value(records, "revenue"),
        "归母净利润": _has_value(records, "net_profit"),
        "经营活动现金流": _has_value(records, "operating_cash_flow"),
        "资产负债率所需字段": (
            _has_value(records, "total_assets")
            and _has_value(records, "total_liabilities")
        ),
    }
    missing.extend(
        f"缺少{label}，未计算相关指标。"
        for label, available in required_metrics.items()
        if not available
    )
    if not audit_rows:
        missing.append("get_audit_opinion 未返回审计意见数据。")
    if not forecast_rows:
        missing.append("get_fina_forecast 未返回业绩预告数据。")
    if scope == "full_dossier":
        expected = set(FULL_DOSSIER_METHODS)
        present = {
            str(item.get("method"))
            for item in data_scope
            if item.get("missing_status") == "available"
        }
        missing.extend(
            f"{method} 未返回可用数据或未能完成查询。"
            for method in sorted(expected - present)
        )

    periods = [record["period"] for record in records]
    has_calculation = any(
        section["facts"] or section["derived_metrics"]
        for section in sections.values()
    )
    validation_status = VALIDATION_STATUS if has_calculation else "no_data"
    return {
        "symbol": symbol,
        "scope": scope,
        "periods": periods,
        "overall_assessment": {
            "validation_status": validation_status,
            "fact_count": sum(len(item["facts"]) for item in sections.values()),
            "derived_metric_count": sum(
                len(item["derived_metrics"]) for item in sections.values()
            ),
            "judgment_count": sum(
                len(item["judgments"]) for item in sections.values()
            ),
            "future_performance_validated": False,
        },
        **sections,
        "positive_signals": positive_signals,
        "risk_signals": risk_signals,
        "missing_information": list(dict.fromkeys(missing)),
        "data_scope": data_scope,
        "dossier_modules": [
            item
            for item in data_scope
            if item.get("method") in FULL_DOSSIER_METHODS
        ],
    }


def _financial_records(
    reports: list[dict[str, Any]],
    performance: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates = reports or performance
    annual = [row for row in candidates if _is_annual_period(_period(row))]
    selected = sorted(
        annual or candidates,
        key=lambda row: (_period(row), _row_date(row)),
    )
    by_period: dict[str, dict[str, Any]] = {}
    for row in selected:
        period = _period(row)
        if not period:
            continue
        record = by_period.setdefault(
            period,
            {"period": period, "values": {}, "fields": {}},
        )
        for metric, aliases in FIELD_ALIASES.items():
            value, field = _pick_number(row, aliases)
            if value is not None:
                record["values"][metric] = value
                record["fields"][metric] = field
    return [by_period[key] for key in sorted(by_period)]


def _append_fact(
    section: dict[str, list[dict[str, Any]]],
    record: dict[str, Any],
    metric: str,
    period: str,
) -> None:
    value = record["values"].get(metric)
    if value is None:
        return
    section["facts"].append(
        {
            "id": f"fact:{period}:{metric}",
            "metric": metric,
            "value": value,
            "field": record["fields"][metric],
            "period": period,
            "method": "get_fina_reports",
            "source_type": "direct",
        }
    )


def _derived_ratio(
    section: dict[str, list[dict[str, Any]]],
    record: dict[str, Any],
    period: str,
    metric: str,
    inputs: tuple[str, str],
    formula: str,
    calculate: Any,
) -> None:
    values = [record["values"].get(name) for name in inputs]
    if any(value is None for value in values) or values[1] == 0:
        return
    value = calculate(float(values[0]), float(values[1]))
    if not math.isfinite(value):
        return
    section["derived_metrics"].append(
        {
            "id": f"derived:{period}:{metric}",
            "metric": metric,
            "value": value,
            "formula": formula,
            "fields": [record["fields"][name] for name in inputs],
            "period": period,
            "method": "get_fina_reports",
            "source_type": "derived",
        }
    )


def _append_gross_margin(
    section: dict[str, list[dict[str, Any]]],
    record: dict[str, Any],
    period: str,
) -> None:
    gross_profit = record["values"].get("gross_profit")
    revenue = record["values"].get("revenue")
    if gross_profit is not None and revenue not in (None, 0):
        _derived_ratio(
            section,
            record,
            period,
            "gross_margin",
            ("gross_profit", "revenue"),
            "毛利润 / 营业收入",
            lambda gross, sales: gross / sales,
        )
        return
    _derived_ratio(
        section,
        record,
        period,
        "gross_margin",
        ("revenue", "operating_cost"),
        "(营业收入 - 营业成本) / 营业收入",
        lambda sales, cost: (sales - cost) / sales,
    )


def _append_growth_metrics(
    records: list[dict[str, Any]],
    section: dict[str, list[dict[str, Any]]],
) -> None:
    for previous, current in zip(records, records[1:]):
        for metric in (
            "revenue",
            "operating_profit",
            "net_profit",
            "net_profit_excluding_nonrecurring",
        ):
            before = previous["values"].get(metric)
            after = current["values"].get(metric)
            if before in (None, 0) or after is None:
                continue
            value = after / before - 1
            if not math.isfinite(value):
                continue
            section["derived_metrics"].append(
                {
                    "id": f"derived:{current['period']}:{metric}_yoy",
                    "metric": f"{metric}_yoy",
                    "value": value,
                    "formula": f"本期{metric} / 上期{metric} - 1",
                    "fields": [
                        previous["fields"][metric],
                        current["fields"][metric],
                    ],
                    "period": current["period"],
                    "comparison_period": previous["period"],
                    "method": "get_fina_reports",
                    "source_type": "derived",
                }
            )


def _append_average_return_metrics(
    records: list[dict[str, Any]],
    section: dict[str, list[dict[str, Any]]],
) -> None:
    for previous, current in zip(records, records[1:]):
        profit = current["values"].get("net_profit")
        if profit is None:
            continue
        for metric, base, label in (
            ("derived_roe", "total_equity", "归母净利润 / 平均股东权益"),
            ("derived_roa", "total_assets", "归母净利润 / 平均总资产"),
        ):
            before = previous["values"].get(base)
            after = current["values"].get(base)
            if before is None or after is None or before + after == 0:
                continue
            value = profit / ((before + after) / 2)
            section["derived_metrics"].append(
                {
                    "id": f"derived:{current['period']}:{metric}",
                    "metric": metric,
                    "value": value,
                    "formula": label,
                    "fields": [
                        current["fields"]["net_profit"],
                        previous["fields"][base],
                        current["fields"][base],
                    ],
                    "period": current["period"],
                    "method": "get_fina_reports",
                    "source_type": "derived",
                }
            )


def _append_efficiency_metrics(
    records: list[dict[str, Any]],
    section: dict[str, list[dict[str, Any]]],
) -> None:
    for previous, current in zip(records, records[1:]):
        revenue = current["values"].get("revenue")
        before = previous["values"].get("total_assets")
        after = current["values"].get("total_assets")
        if revenue is None or before is None or after is None or before + after == 0:
            continue
        section["derived_metrics"].append(
            {
                "id": f"derived:{current['period']}:total_asset_turnover",
                "metric": "total_asset_turnover",
                "value": revenue / ((before + after) / 2),
                "formula": "营业收入 / 平均总资产",
                "fields": [
                    current["fields"]["revenue"],
                    previous["fields"]["total_assets"],
                    current["fields"]["total_assets"],
                ],
                "period": current["period"],
                "method": "get_fina_reports",
                "source_type": "derived",
            }
        )


def _append_trend_judgments(
    records: list[dict[str, Any]],
    sections: dict[str, dict[str, list[dict[str, Any]]]],
    positive: list[dict[str, Any]],
    risks: list[dict[str, Any]],
) -> None:
    if len(records) < 2:
        return
    previous, current = records[-2:]
    revenue_change = _change(previous, current, "revenue")
    profit_change = _change(previous, current, "net_profit")
    cash_change = _change(previous, current, "operating_cash_flow")
    if revenue_change is not None and profit_change is not None:
        if revenue_change > 0 and profit_change > 0:
            _judgment(
                sections["growth"],
                positive,
                "收入和归母净利润同步增长。",
                current["period"],
                ("revenue_yoy", "net_profit_yoy"),
            )
        elif revenue_change > 0 >= profit_change:
            _judgment(
                sections["growth"],
                risks,
                "收入增长但归母净利润未同步增长，可能提示盈利承压。",
                current["period"],
                ("revenue_yoy", "net_profit_yoy"),
            )
        elif profit_change < revenue_change:
            _judgment(
                sections["growth"],
                risks,
                "归母净利润增速落后于收入增速，需要进一步核查成本和费用变化。",
                current["period"],
                ("revenue_yoy", "net_profit_yoy"),
            )
    if profit_change is not None and cash_change is not None:
        if profit_change > 0 and cash_change < 0:
            _judgment(
                sections["cash_flow_quality"],
                risks,
                "账面利润增长但经营现金流恶化，可能提示盈利质量下降。",
                current["period"],
                ("net_profit_yoy", "operating_cash_flow_yoy"),
            )
    net_profit = current["values"].get("net_profit")
    deducted = current["values"].get("net_profit_excluding_nonrecurring")
    if (
        net_profit not in (None, 0)
        and deducted is not None
        and deducted / net_profit < 0.8
    ):
        _judgment(
            sections["growth"],
            risks,
            "扣非净利润明显弱于归母净利润，需要核查非经常性损益来源。",
            current["period"],
            ("net_profit", "net_profit_excluding_nonrecurring"),
        )


def _append_audit_and_forecast(
    audit_rows: list[dict[str, Any]],
    forecast_rows: list[dict[str, Any]],
    section: dict[str, list[dict[str, Any]]],
    risks: list[dict[str, Any]],
) -> None:
    standard_phrases = ("标准无保留", "无保留意见")
    nonstandard_phrases = (
        "保留意见",
        "否定意见",
        "无法表示意见",
        "非标准",
        "带强调事项",
    )
    for index, row in enumerate(audit_rows):
        text = " ".join(str(value) for value in row.values() if value is not None)
        period = _period(row) or f"audit_{index + 1}"
        section["facts"].append(
            {
                "id": f"fact:{period}:audit_opinion",
                "metric": "audit_opinion",
                "value": text[:500],
                "field": "audit_opinion_record",
                "period": period,
                "method": "get_audit_opinion",
                "source_type": "direct",
            }
        )
        is_nonstandard = any(phrase in text for phrase in nonstandard_phrases)
        if "无保留意见" in text and not any(
            phrase in text for phrase in ("带强调事项", "非标准")
        ):
            is_nonstandard = False
        if is_nonstandard and not (
            any(phrase in text for phrase in standard_phrases)
            and "带强调事项" not in text
        ):
            _judgment(
                section,
                risks,
                "出现非标准或需关注的审计意见，需要进一步核查审计说明。",
                period,
                ("audit_opinion",),
            )

    negative_forecasts = ("首亏", "续亏", "预减", "下修", "亏损")
    for index, row in enumerate(forecast_rows):
        text = " ".join(str(value) for value in row.values() if value is not None)
        period = _period(row) or f"forecast_{index + 1}"
        section["facts"].append(
            {
                "id": f"fact:{period}:forecast",
                "metric": "performance_forecast",
                "value": text[:500],
                "field": "forecast_record",
                "period": period,
                "method": "get_fina_forecast",
                "source_type": "direct",
            }
        )
        if any(phrase in text for phrase in negative_forecasts):
            _judgment(
                section,
                risks,
                "业绩预告包含下修或亏损信号，当前证据不足以确认原因。",
                period,
                ("performance_forecast",),
            )


def _judgment(
    section: dict[str, list[dict[str, Any]]],
    signal_list: list[dict[str, Any]],
    statement: str,
    period: str,
    metrics: tuple[str, ...],
) -> None:
    item = {
        "statement": statement,
        "period": period,
        "basis": list(metrics),
        "source_type": "judgment",
    }
    section["judgments"].append(item)
    signal_list.append(item)


def _change(
    previous: dict[str, Any],
    current: dict[str, Any],
    metric: str,
) -> float | None:
    before = previous["values"].get(metric)
    after = current["values"].get(metric)
    if before in (None, 0) or after is None:
        return None
    value = after / before - 1
    return value if math.isfinite(value) else None


def _pick_number(
    row: Mapping[str, Any],
    aliases: tuple[str, ...],
) -> tuple[float | None, str]:
    keys = {str(key).lower(): str(key) for key in row}
    for alias in aliases:
        actual = keys.get(alias.lower())
        if actual is None:
            continue
        number = _number(row.get(actual))
        if number is not None:
            return number, actual
    return None, ""


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _period(row: Mapping[str, Any]) -> str:
    for key in (
        "quarter",
        "end_quarter",
        "report_period",
        "end_date",
        "report_date",
    ):
        value = str(row.get(key, "")).strip()
        if not value:
            continue
        normalized = value.lower().replace("-", "").replace("/", "")
        if len(normalized) == 6 and normalized[4] == "q":
            return normalized
        if len(normalized) >= 8 and normalized[:8].isdigit():
            month = int(normalized[4:6])
            quarter = min(4, max(1, (month - 1) // 3 + 1))
            return f"{normalized[:4]}q{quarter}"
        return value
    return ""


def _is_annual_period(period: str) -> bool:
    return period.lower().endswith("q4") or period.replace("-", "").endswith("1231")


def _row_date(row: Mapping[str, Any]) -> str:
    for key in ("date", "info_date", "announcement_date", "ann_date"):
        value = str(row.get(key, "")).strip()
        if value:
            return value
    return ""


def _rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(row) for row in value if isinstance(row, Mapping)]
    if not isinstance(value, Mapping):
        return []
    for key in ("data", "records", "rows", "result"):
        nested = value.get(key)
        extracted = _rows(nested)
        if extracted:
            return extracted
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


def _has_value(records: list[dict[str, Any]], metric: str) -> bool:
    return any(record["values"].get(metric) is not None for record in records)


def _data_scope(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    safe_keys = {
        "method",
        "symbol",
        "query_range",
        "row_count",
        "latest_report_period",
        "missing_status",
    }
    return [
        {key: item.get(key) for key in safe_keys if key in item}
        for item in value
        if isinstance(item, Mapping)
    ]


def _provenance(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **dict(value),
        "pandadata_dependency": (
            "Mapped to AlphaOS controlled PandaDataClient; no second client "
            "or upstream command execution."
        ),
        "calculation_engine": "AlphaOS deterministic Python adapter",
    }
