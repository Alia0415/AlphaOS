from __future__ import annotations

from backend.agents.risk_agent import RiskAgent
from backend.core.contracts import AgentId, ExpertResult, ExpertTask


class NoArk:
    def chat(self, prompt: str) -> str:
        raise AssertionError("personal_capacity must remain deterministic")


class EchoArk:
    def chat(self, prompt: str) -> str:
        return "受控风险摘要。"


def _task(inputs: dict, dependencies=None) -> ExpertTask:
    return ExpertTask(
        task_id="risk_1",
        agent=AgentId.RISK,
        objective="审查明确模式下的风险",
        original_user_request="测试风险模式",
        inputs=inputs,
        dependency_results=dependencies or {},
    )


def test_personal_capacity_never_emits_strategy_risk_language() -> None:
    result = RiskAgent(ark_client=NoArk()).execute(
        _task(
            {
                "risk_mode": "personal_capacity",
                "risk_context": {
                    "status": "evaluated",
                    "capacity_level": "low",
                    "constraints": [
                        {
                            "code": "upcoming_large_expense",
                            "category": "liquidity",
                            "severity": "high",
                            "statement": "近期大额支出提高了资金锁定约束。",
                            "basis": "未来十二个月内存在已确认的大额支出。",
                            "source_fields": [
                                "planned_large_expenses_cny",
                                "planned_large_expenses_within_months",
                            ],
                        }
                    ],
                    "fields_used": ["planned_large_expenses_cny"],
                    "missing_critical_fields": [],
                },
            }
        )
    )
    serialized = result.model_dump_json()

    assert result.status == "completed"
    assert result.metadata["risk_mode"] == "personal_capacity"
    assert result.metadata["capacity_level"] == "low"
    for forbidden in ("高换手", "成交量信号", "因子衰减", "交易成本", "样本外"):
        assert forbidden not in serialized


def test_strategy_and_market_modes_keep_separate_boundaries() -> None:
    strategy = RiskAgent(ark_client=EchoArk()).execute(
        _task({"risk_mode": "strategy_risk", "strategy": "高换手量价策略"})
    )
    market = RiskAgent(ark_client=EchoArk()).execute(
        _task({"risk_mode": "market_risk", "risk_context": "市场波动"})
    )

    assert any("高换手" in item for item in strategy.risks)
    assert not any("高换手" in item for item in market.risks)
    assert any("流动性" in item or "宏观" in item for item in market.risks)


def test_missing_mode_and_evidence_is_unable_to_grade() -> None:
    result = RiskAgent(ark_client=EchoArk()).execute(
        _task({"risk_context": "未分类上下文"})
    )

    assert result.status == "completed"
    assert result.metadata["risk_level"] == "unable_to_grade"
    assert result.risks == []


def test_quant_dependency_infers_strategy_mode_for_legacy_contract() -> None:
    quant = ExpertResult(
        task_id="quant_1",
        agent=AgentId.QUANT,
        status="completed",
        summary="计算完成",
        evidence=[{"maximum_drawdown": -0.2}],
    )
    result = RiskAgent(ark_client=EchoArk()).execute(
        _task({}, {"quant_1": quant})
    )

    assert result.metadata["risk_mode"] == "strategy_risk"
