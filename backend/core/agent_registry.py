"""Registry describing the expert pool available to the Manager Agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from backend.core.contracts import AgentId


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    """Reviewable metadata for one expert."""

    id: AgentId
    description: str
    capabilities: tuple[str, ...]

    def to_prompt_dict(self) -> dict[str, object]:
        return {
            "id": self.id.value,
            "description": self.description,
            "capabilities": list(self.capabilities),
        }


DEFAULT_EXPERTS = (
    AgentDefinition(
        id=AgentId.RESEARCH,
        description="公司、行业与基本面研究，资料归纳和证据整理",
        capabilities=("company_research", "industry_research", "fundamental_analysis"),
    ),
    AgentDefinition(
        id=AgentId.QUANT,
        description="量化假设、指标计算、策略设计与可验证性分析",
        capabilities=("quantitative_analysis", "strategy_design", "backtesting"),
    ),
    AgentDefinition(
        id=AgentId.RISK,
        description="风险识别、假设审查、压力测试与失败模式分析",
        capabilities=("risk_review", "stress_testing", "assumption_review"),
    ),
    AgentDefinition(
        id=AgentId.PORTFOLIO,
        description="组合构建、仓位配置、约束和再平衡设计",
        capabilities=("portfolio_construction", "allocation", "rebalancing"),
    ),
    AgentDefinition(
        id=AgentId.MACRO,
        description="宏观环境、政策、周期与跨资产背景分析",
        capabilities=("macro_analysis", "policy_analysis", "cycle_analysis"),
    ),
    AgentDefinition(
        id=AgentId.REPORT,
        description="将多个专家结果组织为清晰、可审阅的研究报告",
        capabilities=("report_writing", "evidence_synthesis", "result_presentation"),
    ),
)


class AgentRegistry:
    """Immutable lookup surface for registered experts."""

    def __init__(self, agents: Iterable[AgentDefinition] = DEFAULT_EXPERTS) -> None:
        definitions = tuple(agents)
        by_id = {definition.id: definition for definition in definitions}
        if len(by_id) != len(definitions):
            raise ValueError("Agent registry contains duplicate agent IDs")
        self._agents = by_id

    def contains(self, agent_id: AgentId) -> bool:
        return agent_id in self._agents

    def get(self, agent_id: AgentId) -> AgentDefinition:
        try:
            return self._agents[agent_id]
        except KeyError:
            raise KeyError(f"Unknown expert: {agent_id}") from None

    def ids(self) -> frozenset[AgentId]:
        return frozenset(self._agents)

    def prompt_payload(self) -> list[dict[str, object]]:
        return [
            self._agents[agent_id].to_prompt_dict()
            for agent_id in sorted(self._agents, key=lambda item: item.value)
        ]
