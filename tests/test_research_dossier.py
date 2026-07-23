from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from backend.agents.research_agent import ResearchAgent
from backend.agents.research_skill_planner import ResearchSkillPlanner
from backend.core.contracts import AgentId, ExecutionPlan, ExpertTask, PlanStep
from backend.core.workflow_executor import WorkflowExecutor
from backend.services.ark_client import ArkClientError
from backend.services.pandadata_client import PandaDataClient
from backend.skills.contracts import SkillInvocation, SkillStatus
from backend.skills.loaders.instruction_skill_loader import (
    InstructionSkillLoader,
    RuntimeSkillLocator,
    SkillUnavailableError,
)
from backend.skills.skill_registry import DEFAULT_SKILLS, SkillRegistry


DOSSIER_COMMIT = "213a9cb6b36ccc3ae4c72606ff72211de7b67199"


class OfflineArk:
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, prompt: str, model: str | None = None) -> str:
        self.calls += 1
        raise ArkClientError("offline")


class MockFinancialPandaData:
    def __init__(
        self,
        *,
        reports: Any = None,
        performance: Any = None,
        forecast: Any = None,
        audit: Any = None,
    ) -> None:
        self.responses = {
            "get_fina_reports": reports if reports is not None else _reports(),
            "get_fina_performance": performance if performance is not None else [],
            "get_fina_forecast": forecast if forecast is not None else [],
            "get_audit_opinion": audit if audit is not None else [],
        }
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _result(self, method: str, kwargs: dict[str, Any]) -> Any:
        self.calls.append((method, kwargs))
        return self.responses.get(method, [{"symbol": kwargs["symbol"]}])

    def get_fina_reports(self, **kwargs: Any) -> Any:
        return self._result("get_fina_reports", kwargs)

    def get_fina_performance(self, **kwargs: Any) -> Any:
        return self._result("get_fina_performance", kwargs)

    def get_fina_forecast(self, **kwargs: Any) -> Any:
        return self._result("get_fina_forecast", kwargs)

    def get_audit_opinion(self, **kwargs: Any) -> Any:
        return self._result("get_audit_opinion", kwargs)

    def __getattr__(self, method: str) -> Any:
        if method.startswith("get_"):
            return lambda **kwargs: self._result(method, kwargs)
        raise AttributeError(method)


@pytest.fixture()
def dossier_runtime(tmp_path: Path) -> tuple[Path, Path, Path]:
    runtime_home = tmp_path / ".runtime_skills"
    root = runtime_home / "skill-a-share-stock-dossier"
    references = root / "references"
    references.mkdir(parents=True)
    skill = root / "SKILL.md"
    guide = references / "dossier-guide.md"
    skill.write_text("# A-Share Stock Dossier\n", encoding="utf-8")
    guide.write_text("# Dossier Guide\n", encoding="utf-8")
    lock_path = tmp_path / "skills.lock.json"
    lock_path.write_text(
        json.dumps(
            {
                "version": 1,
                "skills": {
                    "a_share_stock_dossier": {
                        "repository": (
                            "quantskills/skill-a-share-stock-dossier"
                        ),
                        "commit_sha": DOSSIER_COMMIT,
                        "skill_path": ".",
                        "license": "GPL-3.0-only",
                        "installed_at": "2026-07-23T00:00:00+00:00",
                        "owner": "research",
                        "mode": "instruction",
                        "expected_entrypoint": "SKILL.md",
                        "entrypoint_sha256": _hash(skill),
                        "file_sha256": {
                            "SKILL.md": _hash(skill),
                            "references/dossier-guide.md": _hash(guide),
                        },
                        "dependency_mapping": {
                            "skill-pandadata-api": (
                                "backend.services.pandadata_client.PandaDataClient"
                            )
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return tmp_path, runtime_home, lock_path


def _registry(runtime: tuple[Path, Path, Path]) -> SkillRegistry:
    project, home, lock = runtime
    return SkillRegistry(
        project_root=project,
        runtime_home=home,
        lock_path=lock,
    )


def _task(
    *,
    request: str = "分析贵州茅台最近三年的财报。",
    inputs: dict[str, Any] | None = None,
) -> ExpertTask:
    return ExpertTask(
        task_id="research_1",
        agent=AgentId.RESEARCH,
        objective=request,
        original_user_request=request,
        inputs=inputs or {},
    )


def _reports() -> list[dict[str, Any]]:
    return [
        {
            "symbol": "600519.SH",
            "quarter": "2023q4",
            "is_operating_revenue": 100,
            "is_operating_cost": 60,
            "is_operating_profit": 20,
            "net_profit_parent": 15,
            "net_profit_excluding_nonrecurring": 14,
            "cfs_net_cashflow_operating": 17,
            "bs_total_assets": 200,
            "bs_total_liabilities": 80,
            "bs_total_equity_parent": 120,
            "bs_total_current_assets": 100,
            "bs_total_current_liabilities": 40,
            "bs_accounts_receivable": 10,
            "bs_inventory": 20,
        },
        {
            "symbol": "600519.SH",
            "quarter": "2024q4",
            "is_operating_revenue": 120,
            "is_operating_cost": 70,
            "is_operating_profit": 25,
            "net_profit_parent": 18,
            "net_profit_excluding_nonrecurring": 17,
            "cfs_net_cashflow_operating": 20,
            "bs_total_assets": 220,
            "bs_total_liabilities": 85,
            "bs_total_equity_parent": 135,
            "bs_total_current_assets": 110,
            "bs_total_current_liabilities": 42,
            "bs_accounts_receivable": 11,
            "bs_inventory": 22,
        },
        {
            "symbol": "600519.SH",
            "quarter": "2025q4",
            "is_operating_revenue": 140,
            "is_operating_cost": 80,
            "is_operating_profit": 30,
            "net_profit_parent": 22,
            "net_profit_excluding_nonrecurring": 14,
            "cfs_net_cashflow_operating": 12,
            "bs_total_assets": 240,
            "bs_total_liabilities": 90,
            "bs_total_equity_parent": 150,
            "bs_total_current_assets": 120,
            "bs_total_current_liabilities": 45,
            "bs_accounts_receivable": 12,
            "bs_inventory": 25,
        },
    ]


def test_registry_registers_research_owned_dossier_and_enforces_ownership() -> None:
    registry = SkillRegistry(register_default_adapters=False)
    spec = registry.get("a_share_stock_dossier")

    assert spec.enabled is True
    assert spec.owner_agents == ["research"]
    assert "financial_statement_analysis" in spec.capabilities
    assert {item.id for item in registry.allowed_for_agent("research")} == {
        "a_share_stock_dossier"
    }
    assert registry.execute(
        SkillInvocation(
            invocation_id="1",
            skill_id="a_share_stock_dossier",
            agent="quant",
            objective="unauthorized",
        )
    ).status == SkillStatus.FAILED
    assert registry.execute(
        SkillInvocation(
            invocation_id="2",
            skill_id="factor_idea_generation",
            agent="research",
            objective="unauthorized",
        )
    ).status == SkillStatus.FAILED


def test_manager_plan_contract_rejects_internal_skill_selection() -> None:
    with pytest.raises(ValidationError, match="cannot select internal Skills"):
        PlanStep.model_validate(
            {
                "id": "research_1",
                "agent": "research",
                "objective": "财报",
                "inputs": {"skill_id": "a_share_stock_dossier"},
                "expected_output": "分析",
            }
        )


def test_required_reference_hash_mismatch_fails_closed(
    dossier_runtime: tuple[Path, Path, Path],
) -> None:
    guide = (
        dossier_runtime[1]
        / "skill-a-share-stock-dossier"
        / "references"
        / "dossier-guide.md"
    )
    guide.write_text("tampered", encoding="utf-8")
    spec = next(item for item in DEFAULT_SKILLS if item.id == "a_share_stock_dossier")

    with pytest.raises(SkillUnavailableError, match="hash mismatch"):
        InstructionSkillLoader(
            locator=RuntimeSkillLocator(
                project_root=dossier_runtime[0],
                runtime_home=dossier_runtime[1],
                lock_path=dossier_runtime[2],
            )
        ).load(spec)


def test_dossier_loader_rejects_unknown_and_traversal_references(
    dossier_runtime: tuple[Path, Path, Path],
) -> None:
    registry = _registry(dossier_runtime)
    loader = InstructionSkillLoader(locator=registry.locator)
    spec = registry.get("a_share_stock_dossier")

    with pytest.raises(ValueError, match="not allowlisted"):
        loader.load(spec, references=("references/unknown.md",))
    unsafe = spec.model_copy(
        update={
            "allowed_references": [
                *spec.allowed_references,
                "references/../SKILL.md",
            ]
        }
    )
    with pytest.raises(ValueError, match="Unsafe"):
        loader.load(unsafe, references=("references/../SKILL.md",))


@pytest.mark.parametrize(
    ("user_request", "inputs", "expected_scope"),
    [
        (
            "分析贵州茅台最近三年的财报。",
            {"symbol": "600519.SH", "scope": "financials"},
            "financials",
        ),
        (
            "全面分析贵州茅台的基本面和潜在风险。",
            {"symbol": "600519.SH"},
            "full_dossier",
        ),
        (
            "筛查贵州茅台财务风险。",
            {"symbol": "600519.SH"},
            "financial_risk",
        ),
    ],
)
def test_research_planner_selects_dossier_scope(
    user_request: str,
    inputs: dict[str, Any],
    expected_scope: str,
) -> None:
    registry = SkillRegistry(register_default_adapters=False)
    plan = ResearchSkillPlanner(registry=registry).create_plan(
        _task(request=user_request, inputs=inputs)
    )

    assert [item.skill_id for item in plan.selected_skills] == [
        "a_share_stock_dossier"
    ]
    assert plan.selected_skills[0].scope == expected_scope


def test_research_planner_keeps_price_analysis_on_existing_market_path() -> None:
    registry = SkillRegistry(register_default_adapters=False)
    plan = ResearchSkillPlanner(registry=registry).create_plan(
        _task(
            request="分析贵州茅台过去一年的价格表现和波动率。",
            inputs={
                "symbols": ["600519.SH"],
                "start_date": "20250101",
                "end_date": "20251231",
            },
        )
    )

    assert plan.mode == "market"
    assert plan.selected_skills == []


def test_research_planner_falls_back_safely_when_ark_is_unavailable() -> None:
    registry = SkillRegistry(register_default_adapters=False)
    ark = OfflineArk()
    plan = ResearchSkillPlanner(
        registry=registry,
        ark_client=ark,
    ).create_plan(
        _task(
            request="分析贵州茅台最近三年的财报。",
            inputs={"symbol": "600519.SH"},
        )
    )

    assert plan.fallback_used is True
    assert plan.selected_skills[0].scope == "financials"
    assert ark.calls == 2


def test_financial_scope_calls_only_financial_methods_and_returns_expert_result(
    dossier_runtime: tuple[Path, Path, Path],
) -> None:
    panda = MockFinancialPandaData(
        audit=[{"quarter": "2025q4", "opinion": "标准无保留意见"}],
    )
    result = ResearchAgent(
        data_client=panda,
        skill_registry=_registry(dossier_runtime),
    ).execute(
        _task(
            inputs={
                "symbol": "600519",
                "period": "latest_3_fiscal_years",
                "scope": "financials",
                "focus": [
                    "growth",
                    "profitability",
                    "cash_flow_quality",
                    "solvency",
                ],
            }
        )
    )

    assert result.status == "completed"
    assert result.agent == AgentId.RESEARCH
    assert result.metadata["actual_skills"] == ["a_share_stock_dossier"]
    assert result.metadata["scope"] == "financials"
    assert result.metadata["validation_status"] == (
        "calculated_from_disclosed_financial_data"
    )
    assert {method for method, _ in panda.calls} == {
        "get_fina_reports",
        "get_fina_performance",
        "get_fina_forecast",
        "get_audit_opinion",
    }
    data = result.evidence[0]["data"]
    assert data["periods"] == ["2023q4", "2024q4", "2025q4"]
    assert data["overall_assessment"]["future_performance_validated"] is False
    assert data["profitability"]["derived_metrics"]
    calculated_metrics = {
        item["metric"]
        for section in (
            "growth",
            "profitability",
            "cash_flow_quality",
            "solvency",
        )
        for item in data[section]["derived_metrics"]
    }
    assert {
        "revenue_yoy",
        "net_profit_yoy",
        "gross_margin",
        "net_margin",
        "operating_cash_flow_to_net_profit",
        "asset_liability_ratio",
    }.issubset(calculated_metrics)
    assert all(
        item["source_type"] == "direct"
        for item in data["growth"]["facts"]
    )
    assert all(
        item["source_type"] == "derived"
        for item in data["profitability"]["derived_metrics"]
    )
    assert any(
        "经营现金流恶化" in item["statement"]
        for item in data["risk_signals"]
    )
    assert "财务造假" not in result.model_dump_json()
    assert result.metadata["provenance"]["source_commit"] == DOSSIER_COMMIT
    assert result.metadata["provenance"]["license"] == "GPL-3.0-only"


def test_full_dossier_scope_calls_reviewed_supplementary_methods(
    dossier_runtime: tuple[Path, Path, Path],
) -> None:
    panda = MockFinancialPandaData()
    result = ResearchAgent(
        data_client=panda,
        skill_registry=_registry(dossier_runtime),
    ).execute(
        _task(
            request="全面分析贵州茅台的基本面和潜在风险。",
            inputs={"symbol": "600519.SH", "scope": "full_dossier"},
        )
    )

    called = {method for method, _ in panda.calls}
    assert result.status == "completed"
    assert result.metadata["scope"] == "full_dossier"
    assert {
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
    }.issubset(called)


def test_empty_financial_data_is_explicit_no_data_not_fabricated(
    dossier_runtime: tuple[Path, Path, Path],
) -> None:
    panda = MockFinancialPandaData(reports=[])
    result = ResearchAgent(
        data_client=panda,
        skill_registry=_registry(dossier_runtime),
    ).execute(
        _task(inputs={"symbol": "600519.SH", "scope": "financials"})
    )

    data = result.evidence[0]["data"]
    assert result.status == "completed"
    assert result.metadata["validation_status"] == "no_data"
    assert data["periods"] == []
    assert data["overall_assessment"]["fact_count"] == 0
    assert data["missing_information"]
    assert all(source["row_count"] == 0 for source in result.data_sources[:-1])


def test_missing_fields_degrade_without_inventing_metrics(
    dossier_runtime: tuple[Path, Path, Path],
) -> None:
    panda = MockFinancialPandaData(
        reports=[{"quarter": "2025q4", "is_operating_revenue": 100}]
    )
    result = ResearchAgent(
        data_client=panda,
        skill_registry=_registry(dossier_runtime),
    ).execute(
        _task(inputs={"symbol": "600519.SH", "scope": "financials"})
    )

    data = result.evidence[0]["data"]
    assert data["growth"]["facts"][0]["value"] == 100
    assert data["cash_flow_quality"]["derived_metrics"] == []
    assert any("经营活动现金流" in item for item in data["missing_information"])


def test_missing_symbol_returns_clarification_without_data_calls(
    dossier_runtime: tuple[Path, Path, Path],
) -> None:
    panda = MockFinancialPandaData()
    result = ResearchAgent(
        data_client=panda,
        skill_registry=_registry(dossier_runtime),
    ).execute(_task(inputs={"scope": "financials"}))

    assert result.status == "failed"
    assert result.metadata["needs_clarification"] is True
    assert result.metadata["actual_skills"] == []
    assert panda.calls == []


def test_nonstandard_audit_opinion_creates_traceable_risk_signal(
    dossier_runtime: tuple[Path, Path, Path],
) -> None:
    panda = MockFinancialPandaData(
        audit=[{"quarter": "2025q4", "opinion": "保留意见"}],
    )
    result = ResearchAgent(
        data_client=panda,
        skill_registry=_registry(dossier_runtime),
    ).execute(
        _task(inputs={"symbol": "600519.SH", "scope": "financial_risk"})
    )

    data = result.evidence[0]["data"]
    assert any(
        "审计意见" in item["statement"]
        for item in data["risk_signals"]
    )
    assert any(
        fact["method"] == "get_audit_opinion"
        for fact in data["audit_and_forecast"]["facts"]
    )


def test_workflow_surfaces_bounded_research_skill_events(
    dossier_runtime: tuple[Path, Path, Path],
) -> None:
    agent = ResearchAgent(
        data_client=MockFinancialPandaData(),
        skill_registry=_registry(dossier_runtime),
    )
    plan = ExecutionPlan.model_validate(
        {
            "goal": "财报",
            "intent": "财报",
            "complexity": "low",
            "selected_agents": [{"agent": "research", "reason": "财务分析"}],
            "steps": [
                {
                    "id": "research_1",
                    "agent": "research",
                    "objective": "分析财报",
                    "inputs": {
                        "symbol": "600519.SH",
                        "scope": "financials",
                    },
                    "expected_output": "财务证据",
                }
            ],
        }
    )

    events, _ = WorkflowExecutor(
        handlers={AgentId.RESEARCH: agent}
    ).execute(plan, "分析财报")

    skill_events = [
        event
        for event in events
        if event.type.startswith("skill_")
    ]
    assert [event.type for event in skill_events] == [
        "skill_plan_created",
        "skill_started",
        "skill_completed",
    ]
    assert skill_events[-1].metadata == {
        "skill_id": "a_share_stock_dossier",
        "status": "completed",
        "scope": "financials",
    }
    serialized = json.dumps(
        [event.model_dump(mode="json") for event in skill_events],
        ensure_ascii=False,
    )
    assert "financial_data" not in serialized
    assert "SKILL.md" not in serialized


def test_pandadata_financial_wrapper_validates_and_maps_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class FakeSdk:
        def get_fina_reports(self, **kwargs: Any) -> list[dict[str, Any]]:
            calls.append(kwargs)
            return [{"quarter": "2025q4"}]

    client = PandaDataClient()
    monkeypatch.setattr(client, "_authenticate", lambda: FakeSdk())

    result = client.get_fina_reports(
        symbol="600519.SH",
        start_period="2023q4",
        end_period="2025q4",
    )

    assert result == [{"quarter": "2025q4"}]
    assert calls == [
        {
            "symbol": "600519.SH",
            "start_quarter": "2023q4",
            "end_quarter": "2025q4",
            "fields": None,
            "is_latest": False,
        }
    ]


def test_pandadata_financial_wrapper_rejects_invalid_input_before_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = PandaDataClient()
    monkeypatch.setattr(
        client,
        "_authenticate",
        lambda: pytest.fail("must not authenticate"),
    )

    with pytest.raises(ValueError, match="XXXXXX"):
        client.get_fina_reports(
            symbol="贵州茅台",
            start_period="2023q4",
            end_period="2025q4",
        )


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
