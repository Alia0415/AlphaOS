"""Single source of truth for the AlphaOS expert pool."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from backend.core.contracts import AgentId


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    """Reviewable metadata and availability for one expert."""

    id: AgentId
    name: str
    description: str
    enabled: bool
    tools: tuple[str, ...]
    accepted_inputs: tuple[str, ...]
    capabilities: tuple[str, ...]

    def to_prompt_dict(self) -> dict[str, object]:
        return {
            "id": self.id.value,
            "name": self.name,
            "description": self.description,
            "enabled": self.enabled,
            "tools": list(self.tools),
            "accepted_inputs": list(self.accepted_inputs),
            "capabilities": list(self.capabilities),
        }


DEFAULT_EXPERTS = (
    AgentDefinition(
        id=AgentId.RESEARCH,
        name="Research Agent",
        description="负责公司、行业和市场研究，并基于真实市场数据整理证据",
        enabled=True,
        tools=("pandadata_market_data",),
        accepted_inputs=("symbols", "start_date", "end_date", "fields"),
        capabilities=(
            "market_analysis",
            "company_research",
            "industry_research",
        ),
    ),
    AgentDefinition(
        id=AgentId.QUANT,
        name="Quant Agent",
        description="负责因子假设生成、因子计算和量化验证准备",
        enabled=True,
        tools=(
            "factor_idea_generation",
            "r020_volume_expansion",
            "pandadata_market_data",
        ),
        accepted_inputs=(
            "symbols",
            "start_date",
            "end_date",
            "fields",
            "candidate_count",
            "factor_id",
            "horizon",
        ),
        capabilities=(
            "factor_ideation",
            "factor_computation",
            "quantitative_research",
        ),
    ),
    AgentDefinition(
        id=AgentId.RISK,
        name="Risk Agent",
        description="独立或结合上游证据进行风险、假设和失败模式审查",
        enabled=True,
        tools=(),
        accepted_inputs=("strategy", "thesis", "risk_context"),
        capabilities=("risk_review", "stress_testing", "assumption_review"),
    ),
    AgentDefinition(
        id=AgentId.PORTFOLIO,
        name="Portfolio Agent",
        description="组合构建、仓位配置、约束和再平衡设计",
        enabled=False,
        tools=(),
        accepted_inputs=(),
        capabilities=("portfolio_construction", "allocation", "rebalancing"),
    ),
    AgentDefinition(
        id=AgentId.MACRO,
        name="Macro Agent",
        description="基于 PandaData 分析宏观环境、政策、周期、利率与流动性",
        enabled=True,
        tools=("pandadata_macro_data",),
        accepted_inputs=(
            "industry",
            "time_range",
            "research_goal",
            "start_date",
            "end_date",
        ),
        capabilities=("macro_analysis", "policy_analysis", "cycle_analysis"),
    ),
    AgentDefinition(
        id=AgentId.REPORT,
        name="Report Agent",
        description="仅在需要正式输出或复杂整合时组织已有专家结果",
        enabled=True,
        tools=(),
        accepted_inputs=("format", "audience"),
        capabilities=("report_writing", "evidence_synthesis", "result_presentation"),
    ),
)


class AgentRegistry:
    """Immutable lookup surface for all and enabled experts."""

    def __init__(self, agents: Iterable[AgentDefinition] = DEFAULT_EXPERTS) -> None:
        definitions = tuple(agents)
        by_id = {definition.id: definition for definition in definitions}
        if len(by_id) != len(definitions):
            raise ValueError("Agent registry contains duplicate agent IDs")
        self._agents = by_id

    def contains(self, agent_id: AgentId, *, enabled_only: bool = False) -> bool:
        definition = self._agents.get(agent_id)
        return definition is not None and (
            definition.enabled or not enabled_only
        )

    def is_enabled(self, agent_id: AgentId) -> bool:
        definition = self._agents.get(agent_id)
        return bool(definition and definition.enabled)

    def get(self, agent_id: AgentId) -> AgentDefinition:
        try:
            return self._agents[agent_id]
        except KeyError:
            raise KeyError(f"Unknown expert: {agent_id}") from None

    def ids(self, *, enabled_only: bool = False) -> frozenset[AgentId]:
        return frozenset(
            agent_id
            for agent_id, definition in self._agents.items()
            if definition.enabled or not enabled_only
        )

    def prompt_payload(self) -> list[dict[str, object]]:
        """Only enabled experts are exposed to Manager planning."""

        return [
            self._agents[agent_id].to_prompt_dict()
            for agent_id in sorted(
                self.ids(enabled_only=True),
                key=lambda item: item.value,
            )
        ]
