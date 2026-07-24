from __future__ import annotations

from backend.core.profile_requirement_resolver import ProfileRequirementResolver
from backend.core.task_spec import TaskSpec
from backend.core.user_profile import UserInvestmentProfile


def _spec(goal: str, *, task_type: str = "personal_investment_decision") -> TaskSpec:
    return TaskSpec(
        task_type=task_type,
        subject_type="personal_finance" if task_type.startswith("personal") else "market",
        research_goal=goal,
        expected_result_type="direct_answer",
        evidence_requirements=["区分历史事实与现实承受约束"],
        execution_decision="clarify" if task_type.startswith("personal") else "execute",
        clarification_question="请补充本次决策直接需要的信息。"
        if task_type.startswith("personal")
        else None,
    )


def test_volatility_capacity_uses_task_scoped_fields() -> None:
    result = ProfileRequirementResolver().required_fields_for(
        _spec("我能否承受这个产品的历史波动？")
    )

    assert result.decision_kind == "volatility_capacity"
    assert {
        "investment_horizon_months",
        "liquidity_need",
        "emergency_fund_cny",
        "monthly_essential_expenses_cny",
        "monthly_debt_payment_cny",
        "max_acceptable_loss_ratio",
    } == set(result.required)
    assert "dependents_count" in result.irrelevant
    assert "existing_positions" not in result.required


def test_lockup_and_concentration_require_different_facts() -> None:
    resolver = ProfileRequirementResolver()
    lockup = resolver.required_fields_for(
        _spec("我未来半年有大额支出，还适合把钱锁定一年吗？")
    )
    concentration = resolver.required_fields_for(
        _spec("我大部分资金都在一个行业，风险大吗？")
    )

    assert lockup.decision_kind == "lockup_capacity"
    assert {
        "planned_large_expenses_cny",
        "planned_large_expenses_within_months",
    } <= set(lockup.required)
    assert concentration.decision_kind == "concentration_risk"
    assert "existing_positions" in concentration.required
    assert "planned_large_expenses_cny" in concentration.irrelevant


def test_declined_required_field_is_not_repeated_as_missing() -> None:
    profile = UserInvestmentProfile(
        onboarding_completed=True,
        skipped_fields={"max_acceptable_loss_ratio"},
    )
    requirements = ProfileRequirementResolver().required_fields_for(
        _spec("我能否承受这个产品的历史波动？"),
        profile,
    )

    assert "max_acceptable_loss_ratio" in requirements.declined
    assert "max_acceptable_loss_ratio" not in requirements.missing
    assert requirements.task_completeness == 0


def test_non_personal_research_has_no_profile_gate() -> None:
    result = ProfileRequirementResolver().required_fields_for(
        _spec("分析沪深300历史波动", task_type="market_research")
    )

    assert result.decision_kind == "not_applicable"
    assert result.required == []
    assert result.optional == []
    assert result.task_completeness == 1
