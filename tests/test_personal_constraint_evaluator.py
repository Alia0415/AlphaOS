from __future__ import annotations

from backend.core.personal_constraint_evaluator import PersonalConstraintEvaluator
from backend.core.profile_requirement_resolver import ProfileRequirementResolver
from backend.core.task_spec import TaskSpec
from backend.core.user_profile import UserInvestmentProfile


def _spec(goal: str = "我能否承受这个产品的历史波动？") -> TaskSpec:
    return TaskSpec(
        task_type="personal_investment_decision",
        subject_type="personal_finance",
        research_goal=goal,
        expected_result_type="direct_answer",
        evidence_requirements=["个人现实约束"],
        execution_decision="clarify",
        clarification_question="请补充本次任务需要的画像事实。",
    )


def _profile(*, emergency_fund_cny: int = 120_000) -> UserInvestmentProfile:
    return UserInvestmentProfile(
        investment_horizon_months=60,
        liquidity_need="low",
        emergency_fund_cny=emergency_fund_cny,
        monthly_essential_expenses_cny=8_000,
        monthly_debt_payment_cny=2_000,
        max_acceptable_loss_ratio=0.25,
        onboarding_completed=True,
    )


def _evaluate(profile: UserInvestmentProfile):
    requirements = ProfileRequirementResolver().required_fields_for(
        _spec(), profile
    )
    return PersonalConstraintEvaluator().evaluate(profile, requirements)


def test_emergency_fund_change_only_tightens_liquidity_constraint() -> None:
    sufficient = _evaluate(_profile(emergency_fund_cny=120_000))
    insufficient = _evaluate(_profile(emergency_fund_cny=20_000))

    assert sufficient.status == insufficient.status == "evaluated"
    assert not any(
        item.code == "emergency_fund_low" for item in sufficient.constraints
    )
    low = next(
        item
        for item in insufficient.constraints
        if item.code == "emergency_fund_low"
    )
    assert low.severity == "high"
    assert "emergency_fund_cny" in insufficient.fields_used
    assert {
        item.code for item in sufficient.constraints
    } - {"emergency_fund_low"} == {
        item.code for item in insufficient.constraints
    } - {"emergency_fund_low"}
    assert sufficient.capacity_level == "high"
    assert insufficient.capacity_level == "low"


def test_missing_critical_facts_never_default_to_medium() -> None:
    profile = UserInvestmentProfile(
        investment_horizon_months=24,
        liquidity_need="medium",
        onboarding_completed=True,
    )
    requirements = ProfileRequirementResolver().required_fields_for(
        _spec(), profile
    )
    result = PersonalConstraintEvaluator().evaluate(profile, requirements)

    assert result.status == "insufficient_information"
    assert result.capacity_level == "unable_to_grade"
    assert "emergency_fund_cny" in result.missing_critical_fields
    assert "max_acceptable_loss_ratio" in result.missing_critical_fields


def test_evaluator_outputs_constraints_not_investor_personality_labels() -> None:
    result = _evaluate(_profile(emergency_fund_cny=20_000))
    serialized = result.model_dump_json()

    assert "稳健型" not in serialized
    assert "平衡型" not in serialized
    assert "激进型" not in serialized


def test_irrelevant_profile_change_does_not_change_constraints() -> None:
    first = _profile(emergency_fund_cny=120_000)
    second = first.model_copy(
        update={
            "dependents_count": 5,
            "investment_experience": "experienced",
        }
    )

    first_result = _evaluate(first)
    second_result = _evaluate(second)

    assert first_result == second_result
