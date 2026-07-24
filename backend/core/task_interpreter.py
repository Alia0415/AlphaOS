"""Deterministic natural-language normalization into a research TaskSpec."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Literal

from backend.core.policy_contracts import PolicyDecision
from backend.core.task_spec import SubjectType, TaskSpec, TaskType


_SYMBOL = re.compile(r"(?<!\d)(\d{6}\.(?:SH|SZ))(?![A-Z])", re.IGNORECASE)
_YEAR = re.compile(r"(?<!\d)(20\d{2})\s*年?")
_RELATIVE_TIME = re.compile(r"(最近|过去|未来)\s*([一二三四五六七八九十\d]+)\s*(年|个月|月|季度)")
_COMPANY_AFTER_ANALYZE = re.compile(
    r"(?:分析|研究|评估|对比|比较)\s*([^，。；,.]{2,20}?)(?=最近|过去|未来|在|的财|财务|财报|公司|与|和|、|，|。|$)"
)

_EVIDENCE_REQUIREMENTS = {
    "personal_investment_decision": [
        "资金期限与流动性约束",
        "应急资金与收入支出情况",
        "亏损承受边界",
        "当前持仓与债务约束",
    ],
    "market_research": ["历史市场指标", "数据范围", "风险与限制"],
    "company_research": ["财务事实", "盈利质量与异常信号", "数据缺失项"],
    "factor_research": ["因子定义与参数", "覆盖率与缺失值", "验证状态"],
    "historical_analysis": ["历史样本范围", "计算规则", "成本假设"],
    "risk_review": ["主要风险源", "被挑战的假设", "缺失证据"],
    "comparison": ["统一比较口径", "各对象证据", "差异与限制"],
    "formal_report": ["可追溯事实", "验证状态", "来源与限制"],
}


class TaskInterpreter:
    """Interpret intent without choosing experts, Skills, or conclusions."""

    def interpret(self, prompt: str, policy: PolicyDecision) -> TaskSpec:
        if not policy.allowed:
            raise ValueError("Blocked policy decisions cannot be interpreted as research")
        text = " ".join(prompt.strip().split())
        lowered = text.lower()
        task_type = _task_type(lowered)
        subject_type = _subject_type(lowered, task_type)
        subjects = _subjects(text, subject_type)
        symbols = [match.upper() for match in _SYMBOL.findall(text)]
        start_date, end_date, time_description = _time_range(text)
        missing_fields: list[str] = []
        clarification: str | None = None

        if task_type == "personal_investment_decision":
            missing_fields.extend(_missing_personal_decision_fields(lowered))
        else:
            is_factor_computation = task_type == "factor_research" and any(
                marker in lowered for marker in ("计算", "r020", "因子值", "排名")
            )
            if is_factor_computation and not symbols:
                missing_fields.append("subjects")
            if is_factor_computation and not (start_date and end_date):
                missing_fields.append("date_range")
            if subject_type == "company" and not subjects:
                missing_fields.append("company_or_stock_code")
            if task_type == "comparison" and len(subjects) < 2:
                missing_fields.append("comparison_subjects")

        if missing_fields:
            if task_type == "personal_investment_decision":
                clarification = (
                    "这是个人投资决策。关键信息不足时不会直接给出配置方案，"
                    "请补充投资期限、应急资金、稳定收入与日常支出，以及可承受的"
                    "最大亏损或回撤范围。"
                )
            elif "company_or_stock_code" in missing_fields:
                clarification = "请提供需要研究的公司名称或股票代码。"
            elif "comparison_subjects" in missing_fields:
                clarification = "请明确至少两个需要比较的研究对象。"
            elif {"subjects", "date_range"} <= set(missing_fields):
                clarification = "请提供因子计算的股票代码列表和明确日期范围。"
            elif "subjects" in missing_fields:
                clarification = "请提供因子计算的股票代码列表。"
            else:
                clarification = "请提供因子计算的明确日期范围。"

        defaulted_fields: list[str] = []
        assumptions: list[str] = []
        if (
            task_type != "personal_investment_decision"
            and not time_description
            and not (start_date and end_date)
        ):
            defaulted_fields.append("time_range=latest_available_research_window")
            assumptions.append("未指定时间范围时，使用专家能力允许的最近可用研究窗口。")
        defaulted_fields.append("requested_validation_level=research_draft")

        execution_decision: Literal[
            "execute",
            "execute_with_defaults",
            "clarify",
        ] = (
            "clarify"
            if missing_fields
            else "execute_with_defaults"
            if defaulted_fields
            else "execute"
        )
        return TaskSpec(
            task_type=task_type,
            subject_type=subject_type,
            subjects=subjects,
            market="A-share" if any(_SYMBOL.fullmatch(item) for item in subjects) else None,
            research_goal=text,
            expected_result_type=task_type,
            start_date=start_date,
            end_date=end_date,
            time_range_description=time_description,
            evidence_requirements=list(_EVIDENCE_REQUIREMENTS[task_type]),
            requested_validation_level="research_draft",
            assumptions=assumptions,
            defaulted_fields=defaulted_fields,
            missing_fields=missing_fields,
            execution_decision=execution_decision,
            clarification_question=clarification,
        )


def _task_type(text: str) -> TaskType:
    if _is_personal_investment_decision(text):
        return "personal_investment_decision"
    if any(marker in text for marker in ("正式报告", "研究报告", "备忘录")):
        return "formal_report"
    if any(marker in text for marker in ("对比", "比较", " vs ", " versus ")):
        return "comparison"
    if any(marker in text for marker in ("因子", "r020", "ic检验", "ic ", "factor")):
        return "factor_research"
    company_markers = ("财务", "财报", "现金流", "盈利质量", "审计意见", "公司", "个股")
    if any(marker in text for marker in company_markers):
        return "company_research"
    if _SYMBOL.search(text) and not any(
        marker in text
        for marker in (
            "价格",
            "股价",
            "行情",
            "波动",
            "回撤",
            "成交量",
            "收益",
            "表现",
        )
    ):
        return "company_research"
    risk_markers = ("风险审查", "评估风险", "失效风险", "主要风险", "风险分析")
    if any(marker in text for marker in risk_markers) and not _SYMBOL.search(text):
        return "risk_review"
    if any(marker in text for marker in ("历史计算", "历史表现", "历史收益", "回测")):
        return "historical_analysis"
    return "market_research"


def _subject_type(text: str, task_type: TaskType) -> SubjectType:
    if task_type == "personal_investment_decision":
        return "personal_finance"
    if task_type == "factor_research":
        return "factor"
    if task_type == "company_research" or any(
        marker in text for marker in ("这家公司", "该公司")
    ):
        return "company"
    if "行业" in text:
        return "industry"
    if any(marker in text for marker in ("宏观", "利率", "流动性", "经济周期", "政策")):
        return "macro_theme"
    if task_type == "risk_review":
        return "research_thesis"
    return "market"


def _subjects(text: str, subject_type: SubjectType) -> list[str]:
    symbols = [match.upper() for match in _SYMBOL.findall(text)]
    if subject_type == "factor":
        factors = re.findall(r"\bR\d{3}\b", text, flags=re.IGNORECASE)
        return list(
            dict.fromkeys([*(item.upper() for item in factors), *symbols])
        )
    if symbols:
        return list(dict.fromkeys(symbols))
    if subject_type == "industry":
        match = re.search(r"([^，。；,\s]{2,16}行业)", text)
        if not match:
            return []
        candidate = re.sub(r"^(?:请|帮我)?(?:分析|研究|评估)", "", match.group(1))
        return [candidate]
    if subject_type == "macro_theme":
        themes = [
            marker
            for marker in ("经济周期", "利率", "流动性", "政策", "宏观环境")
            if marker in text
        ]
        return themes
    if subject_type == "company":
        match = _COMPANY_AFTER_ANALYZE.search(text)
        if match:
            candidate = match.group(1).strip()
            if candidate not in {"这只股票", "该公司", "一家公司", "某公司"}:
                return [candidate]
    if subject_type == "research_thesis":
        return [text]
    return []


def _time_range(text: str) -> tuple[str | None, str | None, str | None]:
    years = [int(year) for year in _YEAR.findall(text)]
    if years:
        start_year, end_year = min(years), max(years)
        return (
            f"{start_year}0101",
            f"{end_year}1231",
            f"{start_year} 年" if start_year == end_year else f"{start_year} 至 {end_year} 年",
        )
    relative = _RELATIVE_TIME.search(text)
    if relative:
        return None, None, "".join(relative.groups())
    if "今年" in text:
        year = datetime.now().year
        return f"{year}0101", f"{year}1231", f"{year} 年"
    return None, None, None


def _is_personal_investment_decision(text: str) -> bool:
    personal_context = any(
        marker in text
        for marker in (
            "我有",
            "我的资金",
            "我的收入",
            "我的存款",
            "本人",
            "家庭资金",
            "家庭资产",
        )
    )
    allocation_request = any(
        marker in text
        for marker in (
            "想投资",
            "怎么安排",
            "如何安排",
            "怎么配置",
            "如何配置",
            "资产配置",
            "投资计划",
            "应该怎么投",
        )
    )
    return personal_context and allocation_request


def _missing_personal_decision_fields(text: str) -> list[str]:
    missing: list[str] = []
    if not any(
        marker in text
        for marker in ("投资期限", "资金期限", "持有期限", "长期", "短期", "个月", "年")
    ):
        missing.append("investment_horizon")
    if not any(marker in text for marker in ("应急资金", "应急金", "备用金")):
        missing.append("emergency_fund")
    has_income = any(marker in text for marker in ("收入", "工资", "现金流入"))
    has_expenses = any(marker in text for marker in ("支出", "开销", "月供", "现金流出"))
    if not (has_income and has_expenses):
        missing.append("income_and_expenses")
    if not any(
        marker in text
        for marker in ("亏损", "回撤", "风险承受", "最大损失", "损失承受")
    ):
        missing.append("loss_tolerance")
    return missing
