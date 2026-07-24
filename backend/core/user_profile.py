"""Validated user-profile facts and deterministic financial metrics.

The profile intentionally excludes identity and payment data. ``None`` means
"not answered"; explicit zero remains a valid financial fact.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

MAX_CNY_AMOUNT = 1_000_000_000_000
LOCAL_USER_ID = "local-default-user"

PROFILE_FACT_FIELDS = (
    "investment_goal",
    "monthly_after_tax_income_cny",
    "income_stability",
    "monthly_essential_expenses_cny",
    "monthly_debt_payment_cny",
    "dependents_count",
    "emergency_fund_cny",
    "planned_large_expenses_cny",
    "planned_large_expenses_within_months",
    "available_investment_funds_cny",
    "investment_horizon_months",
    "liquidity_need",
    "max_acceptable_loss_ratio",
    "existing_positions",
    "investment_experience",
)

class ExistingPosition(BaseModel):
    """One user-reported holding without inferred values."""

    model_config = ConfigDict(extra="forbid")

    asset_name: str = Field(min_length=1, max_length=100)
    asset_type: str = Field(min_length=1, max_length=50)
    amount_cny: int | None = Field(default=None, ge=0, le=MAX_CNY_AMOUNT)
    portfolio_ratio: float | None = Field(default=None, ge=0, le=1)

    @field_validator("asset_name", "asset_type", mode="before")
    @classmethod
    def normalize_required_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
        return value

    @model_validator(mode="after")
    def amount_or_ratio_is_required(self) -> "ExistingPosition":
        if self.amount_cny is None and self.portfolio_ratio is None:
            raise ValueError("每项持仓至少填写大致金额或占比")
        return self


class UserInvestmentProfile(BaseModel):
    """User-confirmed facts; missing values are never guessed or zero-filled."""

    model_config = ConfigDict(extra="forbid")

    monthly_after_tax_income_cny: int | None = Field(
        default=None, ge=0, le=MAX_CNY_AMOUNT
    )
    income_stability: Literal["stable", "variable", "uncertain"] | None = None
    monthly_essential_expenses_cny: int | None = Field(
        default=None, ge=0, le=MAX_CNY_AMOUNT
    )
    monthly_debt_payment_cny: int | None = Field(
        default=None, ge=0, le=MAX_CNY_AMOUNT
    )
    dependents_count: int | None = Field(default=None, ge=0, le=100)

    emergency_fund_cny: int | None = Field(default=None, ge=0, le=MAX_CNY_AMOUNT)
    planned_large_expenses_cny: int | None = Field(
        default=None, ge=0, le=MAX_CNY_AMOUNT
    )
    planned_large_expenses_within_months: int | None = Field(
        default=None, ge=0, le=1_200
    )

    investment_goal: str | None = Field(default=None, max_length=500)
    available_investment_funds_cny: int | None = Field(
        default=None, ge=0, le=MAX_CNY_AMOUNT
    )
    investment_horizon_months: int | None = Field(default=None, gt=0, le=1_200)
    liquidity_need: Literal["high", "medium", "low"] | None = None
    max_acceptable_loss_ratio: float | None = Field(default=None, ge=0, le=1)

    investment_experience: Literal["none", "basic", "experienced"] | None = None
    existing_positions: list[ExistingPosition] | None = Field(
        default=None, max_length=100
    )

    onboarding_completed: bool = False
    profile_version: int = Field(default=1, ge=1)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    confirmed_fields: set[str] = Field(default_factory=set)
    skipped_fields: set[str] = Field(default_factory=set)

    @field_validator("investment_goal", mode="before")
    @classmethod
    def empty_text_is_missing(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("confirmed_fields", "skipped_fields")
    @classmethod
    def field_markers_are_known(cls, values: set[str]) -> set[str]:
        unknown = values - set(PROFILE_FACT_FIELDS)
        if unknown:
            raise ValueError("画像字段标记包含未知字段")
        return values

    @field_validator("created_at", "updated_at")
    @classmethod
    def timestamps_have_timezone(
        cls, value: datetime | None
    ) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("画像时间必须包含时区")
        return value

    @model_validator(mode="after")
    def validate_metadata(self) -> "UserInvestmentProfile":
        overlap = self.confirmed_fields & self.skipped_fields
        if overlap:
            raise ValueError("同一画像字段不能同时确认和跳过")
        if (
            self.created_at is not None
            and self.updated_at is not None
            and self.updated_at < self.created_at
        ):
            raise ValueError("画像更新时间不能早于创建时间")
        return self

    @computed_field(return_type=int | None)
    @property
    def essential_cash_outflow_cny(self) -> int | None:
        if (
            self.monthly_essential_expenses_cny is None
            or self.monthly_debt_payment_cny is None
        ):
            return None
        return (
            self.monthly_essential_expenses_cny
            + self.monthly_debt_payment_cny
        )

    @computed_field(return_type=int | None)
    @property
    def monthly_surplus_cny(self) -> int | None:
        if (
            self.monthly_after_tax_income_cny is None
            or self.essential_cash_outflow_cny is None
        ):
            return None
        return self.monthly_after_tax_income_cny - self.essential_cash_outflow_cny

    @computed_field(return_type=float | None)
    @property
    def savings_rate(self) -> float | None:
        if (
            self.monthly_surplus_cny is None
            or self.monthly_after_tax_income_cny in (None, 0)
        ):
            return None
        return self.monthly_surplus_cny / self.monthly_after_tax_income_cny

    @computed_field(return_type=float | None)
    @property
    def emergency_fund_months(self) -> float | None:
        if (
            self.emergency_fund_cny is None
            or self.essential_cash_outflow_cny in (None, 0)
        ):
            return None
        return self.emergency_fund_cny / self.essential_cash_outflow_cny

    @computed_field(return_type=float | None)
    @property
    def debt_payment_ratio(self) -> float | None:
        if (
            self.monthly_debt_payment_cny is None
            or self.monthly_after_tax_income_cny in (None, 0)
        ):
            return None
        return self.monthly_debt_payment_cny / self.monthly_after_tax_income_cny

    @computed_field(return_type=int | None)
    @property
    def known_portfolio_value_cny(self) -> int | None:
        if self.existing_positions is None:
            return None
        if not self.existing_positions:
            return 0
        known = [
            position.amount_cny
            for position in self.existing_positions
            if position.amount_cny is not None
        ]
        return sum(known) if known else None

    @computed_field(return_type=float | None)
    @property
    def largest_position_ratio(self) -> float | None:
        positions = self.existing_positions
        if positions is None:
            return None
        if not positions:
            return 0.0
        explicit = [
            position.portfolio_ratio
            for position in positions
            if position.portfolio_ratio is not None
        ]
        if explicit:
            return max(explicit)
        if any(position.amount_cny is None for position in positions):
            return None
        total = sum(position.amount_cny or 0 for position in positions)
        if total == 0:
            return None
        return max((position.amount_cny or 0) / total for position in positions)

    @computed_field(return_type=float)
    @property
    def profile_completeness(self) -> float:
        answered = sum(
            getattr(self, field_name) is not None
            for field_name in PROFILE_FACT_FIELDS
        )
        return answered / len(PROFILE_FACT_FIELDS)

    def missing_fields(self, fields: tuple[str, ...] = PROFILE_FACT_FIELDS) -> list[str]:
        return [name for name in fields if getattr(self, name) is None]

    def risk_summary(self) -> dict[str, Any]:
        """Return only facts needed by Risk for a personal decision."""

        return {
            "investment_horizon_months": self.investment_horizon_months,
            "emergency_fund_months": self.emergency_fund_months,
            "monthly_surplus_cny": self.monthly_surplus_cny,
            "debt_payment_ratio": self.debt_payment_ratio,
            "liquidity_need": self.liquidity_need,
            "max_acceptable_loss_ratio": self.max_acceptable_loss_ratio,
            "largest_position_ratio": self.largest_position_ratio,
            "planned_large_expenses": {
                "amount_cny": self.planned_large_expenses_cny,
                "within_months": self.planned_large_expenses_within_months,
            },
        }


class UserProfilePut(UserInvestmentProfile):
    """Full validated profile replacement; server owns version and timestamps."""


class UserProfilePatch(BaseModel):
    """Validated partial profile update."""

    model_config = ConfigDict(extra="forbid")

    monthly_after_tax_income_cny: int | None = Field(
        default=None, ge=0, le=MAX_CNY_AMOUNT
    )
    income_stability: Literal["stable", "variable", "uncertain"] | None = None
    monthly_essential_expenses_cny: int | None = Field(
        default=None, ge=0, le=MAX_CNY_AMOUNT
    )
    monthly_debt_payment_cny: int | None = Field(
        default=None, ge=0, le=MAX_CNY_AMOUNT
    )
    dependents_count: int | None = Field(default=None, ge=0, le=100)
    emergency_fund_cny: int | None = Field(default=None, ge=0, le=MAX_CNY_AMOUNT)
    planned_large_expenses_cny: int | None = Field(
        default=None, ge=0, le=MAX_CNY_AMOUNT
    )
    planned_large_expenses_within_months: int | None = Field(
        default=None, ge=0, le=1_200
    )
    investment_goal: str | None = Field(default=None, max_length=500)
    available_investment_funds_cny: int | None = Field(
        default=None, ge=0, le=MAX_CNY_AMOUNT
    )
    investment_horizon_months: int | None = Field(default=None, gt=0, le=1_200)
    liquidity_need: Literal["high", "medium", "low"] | None = None
    max_acceptable_loss_ratio: float | None = Field(default=None, ge=0, le=1)
    investment_experience: Literal["none", "basic", "experienced"] | None = None
    existing_positions: list[ExistingPosition] | None = Field(
        default=None, max_length=100
    )
    onboarding_completed: bool | None = None
    confirmed_fields: set[str] | None = None
    skipped_fields: set[str] | None = None

    _empty_text_is_missing = field_validator(
        "investment_goal", mode="before"
    )(UserInvestmentProfile.empty_text_is_missing.__func__)
    _field_markers_are_known = field_validator(
        "confirmed_fields", "skipped_fields"
    )(UserInvestmentProfile.field_markers_are_known.__func__)
