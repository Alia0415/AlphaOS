"""Central allowlist, authorization boundary, and dispatcher for runtime skills."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol

from backend.skills.contracts import (
    SkillInvocation,
    SkillMode,
    SkillResult,
    SkillSpec,
    SkillStatus,
)
from backend.skills.loaders.instruction_skill_loader import RuntimeSkillLocator


class SkillAdapter(Protocol):
    """Callable implemented by one approved skill adapter."""

    def __call__(
        self,
        invocation: SkillInvocation,
        spec: SkillSpec,
    ) -> SkillResult: ...


FACTOR_IDEA_REFERENCES = [
    "references/factor_shape_guidance.md",
    "references/idea_quality_bar.md",
    "references/output_schema.md",
]


DEFAULT_SKILLS = (
    SkillSpec(
        id="factor_idea_generation",
        name="Factor Idea Generation",
        description="基于已授权字段生成结构化、待验证的因子研究假设",
        mode=SkillMode.INSTRUCTION,
        enabled=True,
        owner_agents=["quant"],
        input_schema={
            "type": "object",
            "properties": {
                "fields": {"type": "array", "items": {"type": "string"}},
                "candidate_count": {"type": "integer", "minimum": 1, "maximum": 20},
                "shortlist_count": {"type": "integer", "minimum": 1, "maximum": 10},
                "horizon": {"type": "string"},
            },
        },
        output_schema={
            "type": "object",
            "required": ["candidates", "shortlist", "validation_status"],
        },
        source_repository="quantskills/skill-factor-idea-generation",
        source_ref="locked",
        license="GPL-3.0-only",
        runtime_path="skill-factor-idea-generation",
        expected_entrypoint="SKILL.md",
        allowed_references=FACTOR_IDEA_REFERENCES,
    ),
    SkillSpec(
        id="r020_volume_expansion",
        name="R020 5D Z-Scored Volume Expansion",
        description="用 PandaData OHLCV 和上游 compute_factor 实际计算 R020",
        mode=SkillMode.EXECUTABLE,
        enabled=True,
        owner_agents=["quant"],
        input_schema={
            "type": "object",
            "x-data-source": "pandadata_market_data",
            "properties": {
                "market_data": {"type": "array"},
                "symbols": {"type": "array", "items": {"type": "string"}},
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
            },
            "required": ["market_data"],
        },
        output_schema={
            "type": "object",
            "required": [
                "factor_id",
                "factor_name",
                "factor_column",
                "coverage_ratio",
                "latest_values_by_symbol",
            ],
        },
        source_repository="quantskills/skill-quant-factor-volume-stat-alpha",
        source_ref="locked",
        license="GPL-3.0-only",
        runtime_path=(
            "skill-quant-factor-volume-stat-alpha/"
            "factors/R020-5d-z-scored-volume-expansion"
        ),
        expected_entrypoint="scripts/factor.py",
        required_task_inputs=["symbols", "start_date", "end_date"],
    ),
)


class SkillRegistry:
    """The only runtime source of truth for approved AlphaOS skills."""

    def __init__(
        self,
        skills: Iterable[SkillSpec] = DEFAULT_SKILLS,
        *,
        adapters: dict[str, SkillAdapter] | None = None,
        project_root: Path | None = None,
        runtime_home: Path | None = None,
        lock_path: Path | None = None,
        ark_client: Any | None = None,
        register_default_adapters: bool = True,
    ) -> None:
        specs = tuple(skills)
        self._skills = {spec.id: spec for spec in specs}
        if len(self._skills) != len(specs):
            raise ValueError("Skill registry contains duplicate skill IDs")
        self.locator = RuntimeSkillLocator(
            project_root=project_root,
            runtime_home=runtime_home,
            lock_path=lock_path,
        )
        self._adapters: dict[str, SkillAdapter] = dict(adapters or {})
        if register_default_adapters:
            self._register_defaults(ark_client)

    def get(self, skill_id: str) -> SkillSpec:
        try:
            return self._skills[skill_id]
        except KeyError:
            raise KeyError(f"Unknown or unapproved skill: {skill_id}") from None

    def is_enabled(self, skill_id: str) -> bool:
        spec = self._skills.get(skill_id)
        return bool(spec and spec.enabled)

    def allowed_for_agent(self, agent_id: str) -> tuple[SkillSpec, ...]:
        return tuple(
            spec
            for spec in self._skills.values()
            if spec.enabled and agent_id in spec.owner_agents
        )

    def prompt_payload(self, agent_id: str) -> list[dict[str, Any]]:
        """Expose only enabled skills owned by the requesting expert."""

        return [
            {
                "id": spec.id,
                "name": spec.name,
                "description": spec.description,
                "mode": spec.mode.value,
                "input_schema": spec.input_schema,
                "output_schema": spec.output_schema,
            }
            for spec in self.allowed_for_agent(agent_id)
        ]

    def register_adapter(self, skill_id: str, adapter: SkillAdapter) -> None:
        self.get(skill_id)
        self._adapters[skill_id] = adapter

    def execute(self, invocation: SkillInvocation) -> SkillResult:
        spec = self._skills.get(invocation.skill_id)
        if spec is None:
            return _rejected(invocation, "Skill is not on the runtime allowlist.")
        if not spec.enabled:
            return _rejected(invocation, "Skill is disabled.")
        if invocation.agent not in spec.owner_agents:
            return _rejected(
                invocation,
                f"Agent '{invocation.agent}' is not authorized for this skill.",
            )
        adapter = self._adapters.get(spec.id)
        if adapter is None:
            return SkillResult(
                invocation_id=invocation.invocation_id,
                skill_id=invocation.skill_id,
                status=SkillStatus.UNAVAILABLE,
                summary="已批准的 Skill 没有可用 adapter。",
                limitations=["Runtime adapter is not registered."],
                error="Runtime adapter is not registered.",
            )
        try:
            return SkillResult.model_validate(adapter(invocation, spec))
        except Exception:
            return SkillResult(
                invocation_id=invocation.invocation_id,
                skill_id=invocation.skill_id,
                status=SkillStatus.FAILED,
                summary="Skill adapter 执行失败。",
                limitations=["Skill adapter raised an internal error."],
                error="Skill adapter raised an internal error.",
            )

    def _register_defaults(self, ark_client: Any | None) -> None:
        from backend.skills.adapters.factor_idea_generation import (
            FactorIdeaGenerationAdapter,
        )
        from backend.skills.adapters.r020_volume_expansion import (
            R020VolumeExpansionAdapter,
        )
        from backend.skills.loaders.instruction_skill_loader import (
            InstructionSkillLoader,
        )

        defaults: dict[str, SkillAdapter] = {
            "factor_idea_generation": FactorIdeaGenerationAdapter(
                loader=InstructionSkillLoader(locator=self.locator),
                ark_client=ark_client,
            ),
            "r020_volume_expansion": R020VolumeExpansionAdapter(
                locator=self.locator
            ),
        }
        for skill_id, adapter in defaults.items():
            self._adapters.setdefault(skill_id, adapter)


def _rejected(invocation: SkillInvocation, error: str) -> SkillResult:
    return SkillResult(
        invocation_id=invocation.invocation_id,
        skill_id=invocation.skill_id,
        status=SkillStatus.FAILED,
        summary="Skill 调用被运行时权限边界拒绝。",
        limitations=[error],
        error=error,
    )
