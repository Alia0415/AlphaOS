"""Task-scoped user-profile requirements for personal investment research."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from backend.core.task_spec import TaskSpec
from backend.core.user_profile import PROFILE_FACT_FIELDS, UserInvestmentProfile


PersonalDecisionKind = Literal[
    "volatility_capacity",
    "lockup_capacity",
    "concentration_risk",
    "general_personal_decision",
    "not_applicable",
]


class ProfileFieldRequirements(BaseModel):
    """Profile fields relevant to one normalized task, never a global checklist."""

    decision_kind: PersonalDecisionKind
    required: list[str] = Field(default_factory=list)
    optional: list[str] = Field(default_factory=list)
    irrelevant: list[str] = Field(default_factory=list)
    declined: list[str] = Field(default_factory=list)
    available: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    reasons: dict[str, str] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)
    task_completeness: float = Field(default=1.0, ge=0, le=1)


_EMERGENCY_FUND_FIELDS = (
    "emergency_fund_cny",
    "monthly_essential_expenses_cny",
    "monthly_debt_payment_cny",
)
_LARGE_EXPENSE_FIELDS = (
    "planned_large_expenses_cny",
    "planned_large_expenses_within_months",
)
_DEBT_FIELDS = (
    "monthly_after_tax_income_cny",
    "monthly_debt_payment_cny",
)

_REASONS = {
    "investment_horizon_months": "用于判断资金承担波动或锁定的时间窗口。",
    "liquidity_need": "用于判断是否需要保留可随时使用的资金。",
    "emergency_fund_cny": "用于计算应急资金能够覆盖必要支出的月数。",
    "monthly_essential_expenses_cny": "用于计算必要现金流和应急资金覆盖月数。",
    "monthly_debt_payment_cny": "用于计算必要现金流、应急资金覆盖和负债压力。",
    "max_acceptable_loss_ratio": "用于确定用户明确接受的损失边界。",
    "planned_large_expenses_cny": "用于判断近期已知支出是否与资金锁定冲突。",
    "planned_large_expenses_within_months": "用于判断大额支出的时间紧迫性。",
    "monthly_after_tax_income_cny": "用于计算负债支出占收入的比例。",
    "income_stability": "用于判断未来现金流的不确定性。",
    "available_investment_funds_cny": "用于核对计划使用资金是否超出可投资范围。",
    "existing_positions": "用于识别已知持仓的集中暴露。",
    "dependents_count": "在需要时辅助理解家庭现金流责任。",
    "investment_goal": "用于理解个人研究目标，但不用于生成买卖建议。",
    "investment_experience": "仅用于调整解释方式，不用于提高风险承受能力。",
}
_LABELS = {
    "investment_horizon_months": "投资期限",
    "liquidity_need": "流动性需求",
    "emergency_fund_cny": "应急资金",
    "monthly_essential_expenses_cny": "每月必要支出",
    "monthly_debt_payment_cny": "每月债务偿付",
    "max_acceptable_loss_ratio": "最大可接受亏损",
    "planned_large_expenses_cny": "计划大额支出",
    "planned_large_expenses_within_months": "大额支出时间",
    "monthly_after_tax_income_cny": "每月税后收入",
    "income_stability": "收入稳定性",
    "available_investment_funds_cny": "可投资资金",
    "existing_positions": "现有持仓",
    "dependents_count": "家庭抚养责任",
    "investment_goal": "投资目标",
    "investment_experience": "投资经验",
}


class ProfileRequirementResolver:
    """Resolve the minimum profile facts needed for a specific TaskSpec."""

    def required_fields_for(
        self,
        task_spec: TaskSpec,
        profile: UserInvestmentProfile | None = None,
    ) -> ProfileFieldRequirements:
        if task_spec.task_type != "personal_investment_decision":
            return ProfileFieldRequirements(
                decision_kind="not_applicable",
                irrelevant=list(PROFILE_FACT_FIELDS),
            )

        kind = _decision_kind(task_spec)
        required, optional = _fields_for_kind(kind)
        required = list(dict.fromkeys(required))
        optional = [
            field for field in dict.fromkeys(optional) if field not in required
        ]
        relevant = set(required) | set(optional)
        declined = (
            sorted(profile.skipped_fields & relevant)
            if profile is not None
            else []
        )
        available = (
            [
                field
                for field in required
                if getattr(profile, field) is not None
            ]
            if profile is not None
            else []
        )
        missing = (
            [
                field
                for field in required
                if getattr(profile, field) is None
                and field not in declined
            ]
            if profile is not None
            else required
        )
        completeness = (
            len(available) / len(required) if required else 1.0
        )
        return ProfileFieldRequirements(
            decision_kind=kind,
            required=required,
            optional=optional,
            irrelevant=[
                field for field in PROFILE_FACT_FIELDS if field not in relevant
            ],
            declined=declined,
            available=available,
            missing=missing,
            reasons={
                field: _REASONS[field]
                for field in required
                if field in _REASONS
            },
            labels={
                field: _LABELS.get(field, field)
                for field in [*required, *optional]
            },
            task_completeness=completeness,
        )


def _fields_for_kind(
    kind: PersonalDecisionKind,
) -> tuple[list[str], list[str]]:
    if kind == "volatility_capacity":
        return (
            [
                "investment_horizon_months",
                "liquidity_need",
                *_EMERGENCY_FUND_FIELDS,
                "max_acceptable_loss_ratio",
            ],
            [
                *_LARGE_EXPENSE_FIELDS,
                *_DEBT_FIELDS,
                "income_stability",
                "existing_positions",
            ],
        )
    if kind == "lockup_capacity":
        return (
            [
                "investment_horizon_months",
                "liquidity_need",
                *_EMERGENCY_FUND_FIELDS,
                *_LARGE_EXPENSE_FIELDS,
            ],
            [
                *_DEBT_FIELDS,
                "income_stability",
                "available_investment_funds_cny",
            ],
        )
    if kind == "concentration_risk":
        return (
            [
                "existing_positions",
                "max_acceptable_loss_ratio",
                "investment_horizon_months",
            ],
            [
                "liquidity_need",
                *_EMERGENCY_FUND_FIELDS,
            ],
        )
    return (
        [
            "investment_horizon_months",
            "liquidity_need",
            *_EMERGENCY_FUND_FIELDS,
            "max_acceptable_loss_ratio",
        ],
        [
            *_DEBT_FIELDS,
            "income_stability",
            *_LARGE_EXPENSE_FIELDS,
            "available_investment_funds_cny",
            "existing_positions",
            "dependents_count",
            "investment_goal",
        ],
    )


def _decision_kind(task_spec: TaskSpec) -> PersonalDecisionKind:
    """Classify from the complete normalized task, using conservative scoring."""

    supporting_parts = [
        task_spec.expected_result_type,
        task_spec.time_range_description or "",
        *task_spec.subjects,
        *task_spec.evidence_requirements,
        *task_spec.assumptions,
    ]
    goal = task_spec.research_goal.lower()
    supporting_text = " ".join(supporting_parts).lower()
    marker_groups = {
        "volatility_capacity": (
            "波动",
            "回撤",
            "亏损",
            "承受",
            "高风险",
            "损失",
        ),
        "lockup_capacity": (
            "锁定",
            "锁住",
            "封闭",
            "大额支出",
            "学费",
            "首付",
            "未来半年",
            "未来一年",
            "流动性",
        ),
        "concentration_risk": (
            "集中",
            "大部分资金",
            "单一行业",
            "单一资产",
            "重仓",
            "持仓风险",
        ),
    }
    scores = {
        kind: (
            2 * sum(marker in goal for marker in markers)
            + sum(marker in supporting_text for marker in markers)
        )
        for kind, markers in marker_groups.items()
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general_personal_decision"
