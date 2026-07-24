"""Deterministic personal financial constraints for research decisions."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.core.profile_requirement_resolver import ProfileFieldRequirements
from backend.core.user_profile import UserInvestmentProfile


# Conservative thresholds are centralized here so policy changes stay reviewable.
EMERGENCY_FUND_HIGH_CONSTRAINT_MONTHS = 3.0
EMERGENCY_FUND_MEDIUM_CONSTRAINT_MONTHS = 6.0
SHORT_HORIZON_MONTHS = 12
MEDIUM_HORIZON_MONTHS = 36
LOW_ACCEPTABLE_LOSS_RATIO = 0.10
MEDIUM_ACCEPTABLE_LOSS_RATIO = 0.20
HIGH_DEBT_PAYMENT_RATIO = 0.40
MEDIUM_DEBT_PAYMENT_RATIO = 0.20
HIGH_CONCENTRATION_RATIO = 0.50
MEDIUM_CONCENTRATION_RATIO = 0.30
UPCOMING_EXPENSE_MONTHS = 12

ConstraintCategory = Literal[
    "liquidity",
    "loss_capacity",
    "time_horizon",
    "cash_flow",
    "debt",
    "concentration",
]
ConstraintSeverity = Literal["low", "medium", "high"]


class PersonalConstraintItem(BaseModel):
    code: str = Field(min_length=1, pattern=r"^[a-z0-9_]+$")
    category: ConstraintCategory
    severity: ConstraintSeverity
    statement: str = Field(min_length=1)
    basis: str = Field(min_length=1)
    source_fields: list[str] = Field(min_length=1)


class PersonalConstraintResult(BaseModel):
    status: Literal[
        "evaluated",
        "insufficient_information",
        "not_applicable",
    ]
    capacity_level: Literal[
        "low",
        "medium",
        "high",
        "unable_to_grade",
    ]
    constraints: list[PersonalConstraintItem] = Field(default_factory=list)
    fields_used: list[str] = Field(default_factory=list)
    missing_critical_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def minimal_summary(self) -> dict[str, Any]:
        """Return a value-minimized summary safe for Manager and Risk."""

        return {
            "status": self.status,
            "capacity_level": self.capacity_level,
            "constraints": [
                item.model_dump(mode="json") for item in self.constraints
            ],
            "fields_used": self.fields_used,
            "missing_critical_fields": self.missing_critical_fields,
            "warnings": self.warnings,
        }


class PersonalConstraintEvaluator:
    """Evaluate explicit profile facts without models, tools, or hidden scores."""

    def evaluate(
        self,
        profile: UserInvestmentProfile | None,
        requirements: ProfileFieldRequirements,
    ) -> PersonalConstraintResult:
        if requirements.decision_kind == "not_applicable":
            return PersonalConstraintResult(
                status="not_applicable",
                capacity_level="unable_to_grade",
            )
        if profile is None:
            return PersonalConstraintResult(
                status="insufficient_information",
                capacity_level="unable_to_grade",
                missing_critical_fields=requirements.required,
                warnings=["本次任务缺少经过确认的用户画像。"],
            )

        missing = list(dict.fromkeys(
            [*requirements.missing, *requirements.declined]
        ))
        if missing:
            return PersonalConstraintResult(
                status="insufficient_information",
                capacity_level="unable_to_grade",
                fields_used=[
                    field
                    for field in requirements.required
                    if getattr(profile, field) is not None
                ],
                missing_critical_fields=missing,
                warnings=(
                    ["用户已拒绝提供部分关键字段；系统不会重复追问。"]
                    if requirements.declined
                    else []
                ),
            )

        constraints: list[PersonalConstraintItem] = []
        used: set[str] = set()

        self._evaluate_emergency_fund(profile, requirements, constraints, used)
        self._evaluate_liquidity(profile, requirements, constraints, used)
        self._evaluate_horizon(profile, requirements, constraints, used)
        self._evaluate_loss_capacity(profile, requirements, constraints, used)
        self._evaluate_large_expense(profile, requirements, constraints, used)
        self._evaluate_debt(profile, requirements, constraints, used)
        self._evaluate_income(profile, requirements, constraints, used)
        self._evaluate_concentration(profile, requirements, constraints, used)

        severities = {item.severity for item in constraints}
        capacity = (
            "low"
            if "high" in severities
            else "medium"
            if "medium" in severities
            else "high"
        )
        return PersonalConstraintResult(
            status="evaluated",
            capacity_level=capacity,
            constraints=constraints,
            fields_used=[
                field
                for field in (
                    *requirements.required,
                    *requirements.optional,
                )
                if field in used
            ],
        )

    @staticmethod
    def _is_relevant(
        requirements: ProfileFieldRequirements,
        *fields: str,
    ) -> bool:
        relevant = set(requirements.required) | set(requirements.optional)
        return any(field in relevant for field in fields)

    def _evaluate_emergency_fund(
        self, profile, requirements, constraints, used
    ) -> None:
        fields = (
            "emergency_fund_cny",
            "monthly_essential_expenses_cny",
            "monthly_debt_payment_cny",
        )
        if not self._is_relevant(requirements, *fields):
            return
        months = profile.emergency_fund_months
        if months is None:
            return
        used.update(fields)
        if months < EMERGENCY_FUND_HIGH_CONSTRAINT_MONTHS:
            constraints.append(_item(
                "emergency_fund_low",
                "liquidity",
                "high",
                "当前流动性缓冲约束较高。",
                "应急资金覆盖不足三个月必要现金支出。",
                fields,
            ))
        elif months < EMERGENCY_FUND_MEDIUM_CONSTRAINT_MONTHS:
            constraints.append(_item(
                "emergency_fund_limited",
                "liquidity",
                "medium",
                "当前流动性缓冲仍需保守处理。",
                "应急资金覆盖少于六个月必要现金支出。",
                fields,
            ))

    def _evaluate_liquidity(
        self, profile, requirements, constraints, used
    ) -> None:
        if not self._is_relevant(requirements, "liquidity_need"):
            return
        if profile.liquidity_need is None:
            return
        used.add("liquidity_need")
        if profile.liquidity_need == "high":
            constraints.append(_item(
                "high_liquidity_need",
                "liquidity",
                "high",
                "本次决策需要优先保留资金可用性。",
                "用户明确确认流动性需求较高。",
                ("liquidity_need",),
            ))
        elif profile.liquidity_need == "medium":
            constraints.append(_item(
                "medium_liquidity_need",
                "liquidity",
                "medium",
                "资金锁定期限需要保持审慎。",
                "用户确认存在中等流动性需求。",
                ("liquidity_need",),
            ))

    def _evaluate_horizon(
        self, profile, requirements, constraints, used
    ) -> None:
        if not self._is_relevant(requirements, "investment_horizon_months"):
            return
        months = profile.investment_horizon_months
        if months is None:
            return
        used.add("investment_horizon_months")
        if months <= SHORT_HORIZON_MONTHS:
            constraints.append(_item(
                "short_time_horizon",
                "time_horizon",
                "high",
                "投资期限较短，承受持续波动或长期锁定的空间有限。",
                "确认的投资期限不超过十二个月。",
                ("investment_horizon_months",),
            ))
        elif months <= MEDIUM_HORIZON_MONTHS:
            constraints.append(_item(
                "medium_time_horizon",
                "time_horizon",
                "medium",
                "投资期限对较长回撤修复形成一定约束。",
                "确认的投资期限不超过三十六个月。",
                ("investment_horizon_months",),
            ))

    def _evaluate_loss_capacity(
        self, profile, requirements, constraints, used
    ) -> None:
        field = "max_acceptable_loss_ratio"
        if not self._is_relevant(requirements, field):
            return
        ratio = profile.max_acceptable_loss_ratio
        if ratio is None:
            return
        used.add(field)
        if ratio <= LOW_ACCEPTABLE_LOSS_RATIO:
            constraints.append(_item(
                "low_loss_tolerance",
                "loss_capacity",
                "high",
                "可接受损失边界较低。",
                "用户确认的最大可接受损失不高于百分之十。",
                (field,),
            ))
        elif ratio <= MEDIUM_ACCEPTABLE_LOSS_RATIO:
            constraints.append(_item(
                "limited_loss_tolerance",
                "loss_capacity",
                "medium",
                "可接受损失边界需要纳入结论限制。",
                "用户确认的最大可接受损失不高于百分之二十。",
                (field,),
            ))

    def _evaluate_large_expense(
        self, profile, requirements, constraints, used
    ) -> None:
        fields = (
            "planned_large_expenses_cny",
            "planned_large_expenses_within_months",
        )
        if not self._is_relevant(requirements, *fields):
            return
        amount = profile.planned_large_expenses_cny
        within = profile.planned_large_expenses_within_months
        if amount is None or within is None:
            return
        used.update(fields)
        if amount > 0 and within <= UPCOMING_EXPENSE_MONTHS:
            constraints.append(_item(
                "upcoming_large_expense",
                "liquidity",
                "high",
                "近期大额支出提高了资金锁定约束。",
                "未来十二个月内存在已确认的大额支出。",
                fields,
            ))

    def _evaluate_debt(
        self, profile, requirements, constraints, used
    ) -> None:
        fields = (
            "monthly_after_tax_income_cny",
            "monthly_debt_payment_cny",
        )
        if not self._is_relevant(requirements, *fields):
            return
        ratio = profile.debt_payment_ratio
        if ratio is None:
            return
        used.update(fields)
        if ratio >= HIGH_DEBT_PAYMENT_RATIO:
            constraints.append(_item(
                "high_debt_pressure",
                "debt",
                "high",
                "债务偿付对可投资能力形成较高约束。",
                "每月债务偿付占税后收入比例不低于百分之四十。",
                fields,
            ))
        elif ratio >= MEDIUM_DEBT_PAYMENT_RATIO:
            constraints.append(_item(
                "medium_debt_pressure",
                "debt",
                "medium",
                "债务偿付对可投资现金流形成一定约束。",
                "每月债务偿付占税后收入比例不低于百分之二十。",
                fields,
            ))

    def _evaluate_income(
        self, profile, requirements, constraints, used
    ) -> None:
        if not self._is_relevant(requirements, "income_stability"):
            return
        stability = profile.income_stability
        if stability is None:
            return
        used.add("income_stability")
        if stability in {"variable", "uncertain"}:
            constraints.append(_item(
                "income_not_stable",
                "cash_flow",
                "high" if stability == "uncertain" else "medium",
                "收入稳定性限制了对长期波动和资金锁定的承受能力。",
                "用户确认收入存在波动或不确定性。",
                ("income_stability",),
            ))

    def _evaluate_concentration(
        self, profile, requirements, constraints, used
    ) -> None:
        if not self._is_relevant(requirements, "existing_positions"):
            return
        ratio = profile.largest_position_ratio
        if ratio is None:
            return
        used.add("existing_positions")
        if ratio >= HIGH_CONCENTRATION_RATIO:
            constraints.append(_item(
                "high_concentration",
                "concentration",
                "high",
                "已知持仓存在较高集中暴露。",
                "最大单项已知持仓占比不低于百分之五十。",
                ("existing_positions",),
            ))
        elif ratio >= MEDIUM_CONCENTRATION_RATIO:
            constraints.append(_item(
                "medium_concentration",
                "concentration",
                "medium",
                "已知持仓存在一定集中暴露。",
                "最大单项已知持仓占比不低于百分之三十。",
                ("existing_positions",),
            ))


def _item(
    code: str,
    category: ConstraintCategory,
    severity: ConstraintSeverity,
    statement: str,
    basis: str,
    source_fields: tuple[str, ...],
) -> PersonalConstraintItem:
    return PersonalConstraintItem(
        code=code,
        category=category,
        severity=severity,
        statement=statement,
        basis=basis,
        source_fields=list(source_fields),
    )
