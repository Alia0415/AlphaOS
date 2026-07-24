from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend import main as main_module
from backend.core.agent_registry import AgentRegistry
from backend.core.contracts import AgentSelection, ExecutionPlan, PlanStep
from backend.core.profile_service import UserProfileService
from backend.core.store import Store
from backend.core.user_profile import (
    ExistingPosition,
    UserInvestmentProfile,
    UserProfilePatch,
    UserProfilePut,
)


def full_profile(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "investment_goal": "五年后的购房准备",
        "monthly_after_tax_income_cny": 20_000,
        "income_stability": "stable",
        "monthly_essential_expenses_cny": 8_000,
        "monthly_debt_payment_cny": 2_000,
        "dependents_count": 2,
        "emergency_fund_cny": 60_000,
        "planned_large_expenses_cny": 30_000,
        "planned_large_expenses_within_months": 10,
        "available_investment_funds_cny": 100_000,
        "investment_horizon_months": 60,
        "liquidity_need": "medium",
        "max_acceptable_loss_ratio": 0.1,
        "investment_experience": "basic",
        "existing_positions": [
            {
                "asset_name": "沪深300指数基金",
                "asset_type": "基金",
                "amount_cny": 60_000,
                "portfolio_ratio": 0.6,
            },
            {
                "asset_name": "银行存款",
                "asset_type": "存款",
                "amount_cny": 40_000,
                "portfolio_ratio": 0.4,
            },
        ],
        "onboarding_completed": True,
        "confirmed_fields": [
            "investment_goal",
            "monthly_after_tax_income_cny",
            "income_stability",
        ],
        "skipped_fields": [],
    }
    payload.update(overrides)
    return payload


def test_profile_contract_preserves_missing_values_and_empty_text() -> None:
    profile = UserInvestmentProfile(investment_goal="   ")

    assert profile.investment_goal is None
    assert profile.monthly_after_tax_income_cny is None
    assert profile.existing_positions is None
    assert profile.monthly_surplus_cny is None
    assert profile.profile_completeness == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("monthly_after_tax_income_cny", -1),
        ("monthly_essential_expenses_cny", -1),
        ("monthly_debt_payment_cny", -1),
        ("emergency_fund_cny", -1),
        ("investment_horizon_months", 0),
        ("max_acceptable_loss_ratio", -0.01),
        ("max_acceptable_loss_ratio", 1.01),
    ],
)
def test_profile_rejects_invalid_amount_horizon_and_ratio(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        UserInvestmentProfile.model_validate({field: value})


def test_no_positions_and_unanswered_positions_are_distinct() -> None:
    unanswered = UserInvestmentProfile(existing_positions=None)
    no_holdings = UserInvestmentProfile(existing_positions=[])

    assert unanswered.known_portfolio_value_cny is None
    assert unanswered.largest_position_ratio is None
    assert no_holdings.known_portfolio_value_cny == 0
    assert no_holdings.largest_position_ratio == 0


def test_position_requires_amount_or_ratio() -> None:
    with pytest.raises(ValidationError, match="金额或占比"):
        ExistingPosition(asset_name="基金", asset_type="基金")


def test_derived_metrics_are_deterministic_and_have_no_risk_label() -> None:
    profile = UserInvestmentProfile.model_validate(full_profile())

    assert profile.essential_cash_outflow_cny == 10_000
    assert profile.monthly_surplus_cny == 10_000
    assert profile.savings_rate == pytest.approx(0.5)
    assert profile.emergency_fund_months == pytest.approx(6)
    assert profile.debt_payment_ratio == pytest.approx(0.1)
    assert profile.known_portfolio_value_cny == 100_000
    assert profile.largest_position_ratio == pytest.approx(0.6)
    assert profile.profile_completeness == 1
    dumped = profile.model_dump(mode="json")
    assert not {"risk_label", "risk_type", "investor_type"} & dumped.keys()


@pytest.mark.parametrize(
    "field",
    ["name", "id_card_number", "bank_card_number", "phone", "address"],
)
def test_sensitive_identity_fields_are_rejected(field: str) -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        UserProfilePut.model_validate({**full_profile(), field: "secret"})


def test_profile_store_crud_version_and_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "profile.db"
    first_store = Store(db_path)
    service = UserProfileService(first_store)

    created = service.put(UserProfilePut.model_validate(full_profile()))
    assert created.profile_version == 1
    changed = service.patch(
        UserProfilePatch(monthly_after_tax_income_cny=21_000)
    )
    assert changed.profile_version == 2
    first_store.close()

    restarted_store = Store(db_path)
    restarted = UserProfileService(restarted_store)
    assert restarted.get().monthly_after_tax_income_cny == 21_000
    assert restarted.delete() is True
    assert restarted.get() is None
    restarted_store.close()


def test_profile_api_create_read_patch_status_and_delete() -> None:
    client = TestClient(main_module.app)
    assert client.get("/api/user-profile").json()["profile"] is None
    assert client.get("/api/user-profile/status").json()["action_required"] == (
        "profile_onboarding_required"
    )

    created = client.put("/api/user-profile", json=full_profile())
    assert created.status_code == 200
    assert created.json()["profile"]["profile_version"] == 1
    assert created.json()["derived_metrics"]["monthly_surplus_cny"] == 10_000

    changed = client.patch(
        "/api/user-profile",
        json={"monthly_after_tax_income_cny": 22_000},
    )
    assert changed.status_code == 200
    assert changed.json()["profile"]["profile_version"] == 2
    assert changed.json()["derived_metrics"]["monthly_surplus_cny"] == 12_000
    assert client.get("/api/user-profile/status").json()["action_required"] is None

    deleted = client.delete("/api/user-profile")
    assert deleted.json() == {"deleted": True}
    assert client.get("/api/user-profile/status").json()["action_required"] == (
        "profile_onboarding_required"
    )


def test_profile_api_revalidates_and_rejects_sensitive_browser_payload() -> None:
    client = TestClient(main_module.app)
    response = client.patch(
        "/api/user-profile",
        json={"bank_card_number": "6222"},
    )
    assert response.status_code == 422
    assert "traceback" not in response.text.lower()


def test_skipped_onboarding_does_not_restart_full_questionnaire() -> None:
    client = TestClient(main_module.app)
    created = client.put(
        "/api/user-profile",
        json=full_profile(
            investment_experience=None,
            onboarding_completed=True,
            skipped_fields=["investment_experience"],
        ),
    )
    assert created.status_code == 200
    status = client.get("/api/user-profile/status").json()
    assert status["onboarding_completed"] is True
    assert status["action_required"] is None


def test_personal_task_without_profile_requires_onboarding_before_dag() -> None:
    with patch.object(
        main_module.manager,
        "create_plan",
        side_effect=AssertionError("DAG must not be created"),
    ):
        response = TestClient(main_module.app).post(
            "/api/tasks",
            json={"prompt": "我有10万元，想投资新能源，应该怎么安排？"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["action_required"] == "profile_onboarding_required"
    assert body["plan"] is None
    assert body["required_profile_fields"]


def test_personal_planning_session_without_profile_creates_no_dag() -> None:
    with patch.object(
        main_module.manager,
        "create_plan",
        side_effect=AssertionError("DAG must not be created"),
    ):
        response = TestClient(main_module.app).post(
            "/api/tasks/sessions",
            json={"prompt": "我有10万元，想投资新能源，应该怎么安排？"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["plan"] is None
    assert body["action_required"] == "profile_onboarding_required"
    detail = TestClient(main_module.app).get(
        f"/api/tasks/{body['task_id']}"
    ).json()
    assert detail["status"] == "profile_onboarding_required"
    assert [event["type"] for event in detail["events"]] == [
        "clarification_required"
    ]


def test_personal_task_with_completed_but_missing_profile_requests_update() -> None:
    client = TestClient(main_module.app)
    assert client.put(
        "/api/user-profile",
        json=full_profile(emergency_fund_cny=None),
    ).status_code == 200

    with patch.object(
        main_module.manager,
        "create_plan",
        side_effect=AssertionError("DAG must not be created"),
    ):
        response = client.post(
            "/api/tasks",
            json={"prompt": "我有10万元，想投资新能源，应该怎么安排？"},
        )

    body = response.json()
    assert body["action_required"] == "profile_update_required"
    assert body["required_profile_fields"] == ["emergency_fund_cny"]
    assert "不会重新启动整套问卷" in body["final_answer"]


class CapturingManager:
    def __init__(self) -> None:
        self.summary: dict[str, object] | None = None

    def create_plan(
        self,
        task_spec,
        prompt: str,
        profile_summary: dict[str, object],
    ) -> ExecutionPlan:
        self.summary = profile_summary
        return ExecutionPlan(
            goal=prompt,
            intent="受控个人化研究",
            task_type=task_spec.task_type,
            expected_result_type=task_spec.expected_result_type,
            complexity="low",
            selected_agents=[],
            steps=[],
            needs_clarification=True,
            clarification_question="请明确要研究的新能源子行业。",
        )


def test_complete_profile_enters_controlled_flow_with_minimal_summary() -> None:
    client = TestClient(main_module.app)
    assert client.put("/api/user-profile", json=full_profile()).status_code == 200
    manager = CapturingManager()

    with patch.object(main_module, "manager", manager):
        response = client.post(
            "/api/tasks",
            json={"prompt": "我有10万元，想投资新能源，应该怎么安排？"},
        )

    assert response.status_code == 200
    assert "action_required" not in response.json()
    assert manager.summary is not None
    assert "monthly_surplus_cny" in manager.summary
    assert "monthly_after_tax_income_cny" not in manager.summary
    assert "investment_experience" not in manager.summary


def test_profile_summary_is_attached_only_to_risk_steps() -> None:
    plan = ExecutionPlan(
        goal="受控个人决策研究",
        intent="研究与风险约束",
        complexity="medium",
        selected_agents=[
            AgentSelection(agent="research", reason="行业事实"),
            AgentSelection(agent="risk", reason="个人约束"),
        ],
        steps=[
            PlanStep(
                id="research_1",
                agent="research",
                objective="研究行业",
                inputs={
                    "industry": "新能源",
                    "research_goal": "事实研究",
                },
                expected_output="事实",
            ),
            PlanStep(
                id="risk_1",
                agent="risk",
                objective="审查现实约束",
                inputs={"thesis": "个人投资研究"},
                depends_on=["research_1"],
                expected_output="风险约束",
            ),
        ],
    )
    summary = {"investment_horizon_months": 60}

    attached = main_module._attach_profile_to_risk(plan, summary)

    assert "risk_context" not in attached.steps[0].inputs
    assert attached.steps[1].inputs["risk_context"] == summary
    assert "profile" not in {agent.value for agent in AgentRegistry().ids()}
