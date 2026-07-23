from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from backend.agents.quant_agent import QuantAgent
from backend.agents.risk_agent import RiskAgent
from backend.core.contracts import AgentId, ExecutionPlan, ExpertResult, ExpertTask
from backend.core.workflow_executor import WorkflowExecutor
from backend.skills.adapters.factor_idea_generation import (
    FactorIdeaGenerationAdapter,
)
from backend.skills.adapters.r020_volume_expansion import (
    R020VolumeExpansionAdapter,
)
from backend.skills.contracts import (
    SkillInvocation,
    SkillResult,
    SkillStatus,
)
from backend.skills.loaders.instruction_skill_loader import (
    InstructionSkillLoader,
    RuntimeSkillLocator,
)
from backend.skills.skill_registry import DEFAULT_SKILLS, SkillRegistry


class MockArk:
    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def chat(self, prompt: str, model: str | None = None) -> str:
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("Unexpected Ark call")
        return self.responses.pop(0)


class MockPandaData:
    def __init__(
        self,
        response: Any = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def get_market_data(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


class StubAdapter:
    def __init__(self, result_data: dict[str, Any]) -> None:
        self.result_data = result_data
        self.calls: list[SkillInvocation] = []

    def __call__(self, invocation, spec) -> SkillResult:
        self.calls.append(invocation)
        return SkillResult(
            invocation_id=invocation.invocation_id,
            skill_id=invocation.skill_id,
            status=SkillStatus.COMPLETED,
            summary=f"{invocation.skill_id} completed",
            data=self.result_data,
            provenance={
                "source_repository": spec.source_repository,
                "source_commit": "a" * 40,
                "license": spec.license,
            },
        )


@pytest.fixture()
def runtime_install(tmp_path: Path) -> tuple[Path, Path, Path]:
    runtime_home = tmp_path / ".runtime_skills"
    idea_root = runtime_home / "skill-factor-idea-generation"
    references = idea_root / "references"
    references.mkdir(parents=True)
    idea_skill = idea_root / "SKILL.md"
    idea_skill.write_text(
        "# Factor Idea Generation\nGenerate hypotheses only.",
        encoding="utf-8",
    )
    for name in (
        "factor_shape_guidance.md",
        "idea_quality_bar.md",
        "output_schema.md",
    ):
        (references / name).write_text(f"# {name}\nAllowed reference.", encoding="utf-8")

    r020_root = (
        runtime_home
        / "skill-quant-factor-volume-stat-alpha"
        / "factors"
        / "R020-5d-z-scored-volume-expansion"
    )
    scripts = r020_root / "scripts"
    scripts.mkdir(parents=True)
    factor_script = scripts / "factor.py"
    factor_script.write_text(
        """
from __future__ import annotations
import numpy as np
import pandas as pd
FACTOR_COLUMN = "5d-z-scored-volume-expansion"
def compute_factor(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy().sort_values(["symbol", "date"]).reset_index(drop=True)
    def calculate(volume: pd.Series) -> pd.Series:
        ratio = volume / volume.rolling(5, min_periods=2).mean() - 1
        mean = ratio.rolling(20, min_periods=2).mean()
        std = ratio.rolling(20, min_periods=2).std(ddof=0)
        return (ratio - mean) / std.replace(0, np.nan)
    out[FACTOR_COLUMN] = out.groupby("symbol", group_keys=False)["volume"].apply(calculate)
    return out
""".strip()
        + "\n",
        encoding="utf-8",
    )

    lock_path = tmp_path / "skills.lock.json"
    lock_path.write_text(
        json.dumps(
            {
                "version": 1,
                "skills": {
                    "factor_idea_generation": _lock_entry(
                        repository="quantskills/skill-factor-idea-generation",
                        skill_path=".",
                        entrypoint="SKILL.md",
                        entrypoint_path=idea_skill,
                        owner="quant",
                        mode="instruction",
                    ),
                    "r020_volume_expansion": _lock_entry(
                        repository=(
                            "quantskills/skill-quant-factor-volume-stat-alpha"
                        ),
                        skill_path=(
                            "factors/R020-5d-z-scored-volume-expansion"
                        ),
                        entrypoint="scripts/factor.py",
                        entrypoint_path=factor_script,
                        owner="quant",
                        mode="executable",
                    ),
                },
            }
        ),
        encoding="utf-8",
    )
    return tmp_path, runtime_home, lock_path


def _lock_entry(
    *,
    repository: str,
    skill_path: str,
    entrypoint: str,
    entrypoint_path: Path,
    owner: str,
    mode: str,
) -> dict[str, Any]:
    return {
        "repository": repository,
        "commit_sha": "a" * 40,
        "skill_path": skill_path,
        "license": "GPL-3.0-only",
        "installed_at": "2026-07-23T00:00:00+00:00",
        "expected_entrypoint": entrypoint,
        "owner": owner,
        "mode": mode,
        "entrypoint_sha256": hashlib.sha256(entrypoint_path.read_bytes()).hexdigest(),
        "file_sha256": {
            entrypoint: hashlib.sha256(entrypoint_path.read_bytes()).hexdigest()
        },
    }


def _locator(runtime_install: tuple[Path, Path, Path]) -> RuntimeSkillLocator:
    project, runtime_home, lock_path = runtime_install
    return RuntimeSkillLocator(
        project_root=project,
        runtime_home=runtime_home,
        lock_path=lock_path,
    )


def _invocation(
    skill_id: str,
    *,
    agent: str = "quant",
    inputs: dict[str, Any] | None = None,
) -> SkillInvocation:
    return SkillInvocation(
        invocation_id="invocation-1",
        skill_id=skill_id,
        agent=agent,
        objective="test objective",
        inputs=inputs or {},
    )


def _idea_response(count: int = 5, shortlist: int = 2) -> str:
    candidates = [
        {
            "name": f"idea_{index}",
            "hypothesis": f"可反驳量价假设 {index}",
            "economic_rationale": "成交量变化可能反映注意力与流动性状态。",
            "required_fields": ["close", "volume"],
            "factor_shape": {
                "formula": "volume / rolling_mean(volume) - 1",
                "direction": "research_only",
            },
            "expected_regime": "流动性稳定的日频市场",
            "failure_modes": ["成交量口径变化", "拥挤交易"],
            "validation_status": "unverified",
        }
        for index in range(count)
    ]
    return json.dumps(
        {
            "candidates": candidates,
            "shortlist": [item["name"] for item in candidates[:shortlist]],
            "validation_status": "unverified",
        },
        ensure_ascii=False,
    )


def _market_rows(symbols: tuple[str, ...] = ("000001.SZ", "000002.SZ")):
    return [
        {
            "trade_date": f"202401{day:02d}",
            "symbol": symbol,
            "open": 10 + day / 100,
            "high": 10.5 + day / 100,
            "low": 9.5 + day / 100,
            "close": 10.2 + day / 100,
            "volume": 1000 + day * day * (index + 1),
        }
        for index, symbol in enumerate(symbols)
        for day in range(1, 26)
    ]


def _skill_plan(skill_id: str) -> str:
    return json.dumps(
        {
            "selected_skills": [
                {"skill_id": skill_id, "reason": "当前任务最小充分能力"}
            ],
            "steps": [
                {
                    "id": "skill_step_1",
                    "skill_id": skill_id,
                    "objective": "执行当前 Quant 任务",
                    "depends_on": [],
                }
            ],
            "needs_clarification": False,
            "clarification_question": None,
        },
        ensure_ascii=False,
    )


def _quant_task(inputs: dict[str, Any] | None = None) -> ExpertTask:
    return ExpertTask(
        task_id="quant_1",
        agent=AgentId.QUANT,
        objective="Quant objective",
        original_user_request="original quant request",
        inputs=inputs or {},
    )


def test_skill_registry_exposes_only_quant_owned_skills() -> None:
    registry = SkillRegistry(register_default_adapters=False)

    assert {spec.id for spec in registry.allowed_for_agent("quant")} == {
        "factor_idea_generation",
        "r020_volume_expansion",
    }
    assert registry.allowed_for_agent("risk") == ()
    assert {item["id"] for item in registry.prompt_payload("quant")} == {
        "factor_idea_generation",
        "r020_volume_expansion",
    }


def test_disabled_skill_cannot_execute() -> None:
    disabled = DEFAULT_SKILLS[0].model_copy(update={"enabled": False})
    adapter = StubAdapter({})
    registry = SkillRegistry(
        skills=[disabled],
        adapters={disabled.id: adapter},
        register_default_adapters=False,
    )

    result = registry.execute(_invocation(disabled.id))

    assert result.status == SkillStatus.FAILED
    assert result.error == "Skill is disabled."
    assert adapter.calls == []


def test_uninstalled_skill_returns_unavailable(tmp_path: Path) -> None:
    registry = SkillRegistry(
        project_root=tmp_path,
        runtime_home=tmp_path / ".runtime_skills",
        lock_path=tmp_path / "missing.lock.json",
        ark_client=MockArk(),
    )

    result = registry.execute(_invocation("factor_idea_generation"))

    assert result.status == SkillStatus.UNAVAILABLE
    assert "lock" in (result.error or "").lower()


def test_instruction_loader_reads_allowlisted_markdown(
    runtime_install: tuple[Path, Path, Path],
) -> None:
    loader = InstructionSkillLoader(locator=_locator(runtime_install))

    loaded = loader.load(
        DEFAULT_SKILLS[0],
        references=("references/output_schema.md",),
    )

    assert loaded.instructions.startswith("# Factor Idea Generation")
    assert "references/output_schema.md" in loaded.references
    assert loaded.provenance["source_commit"] == "a" * 40


def test_instruction_loader_rejects_path_traversal(
    runtime_install: tuple[Path, Path, Path],
) -> None:
    idea_root = runtime_install[1] / "skill-factor-idea-generation"
    (idea_root / "secret.md").write_text("must not load", encoding="utf-8")
    unsafe_spec = DEFAULT_SKILLS[0].model_copy(
        update={
            "allowed_references": [
                *DEFAULT_SKILLS[0].allowed_references,
                "references/../secret.md",
            ]
        }
    )
    loader = InstructionSkillLoader(locator=_locator(runtime_install))

    with pytest.raises(ValueError, match="Unsafe"):
        loader.load(
            unsafe_spec,
            references=("references/../secret.md",),
        )


def test_factor_idea_output_is_structured_and_unverified(
    runtime_install: tuple[Path, Path, Path],
) -> None:
    adapter = FactorIdeaGenerationAdapter(
        loader=InstructionSkillLoader(locator=_locator(runtime_install)),
        ark_client=MockArk(_idea_response()),
    )

    result = adapter(
        _invocation("factor_idea_generation"),
        DEFAULT_SKILLS[0],
    )

    assert result.status == SkillStatus.COMPLETED
    assert len(result.data["candidates"]) == 5
    assert len(result.data["shortlist"]) == 2
    assert {
        idea["validation_status"] for idea in result.data["candidates"]
    } == {"unverified"}
    assert result.data["research_disclosures"] == {
        "hypotheses_are_unverified": True,
        "ic_calculated": False,
        "backtest_run": False,
        "is_trading_signal": False,
    }
    assert any("尚未计算 IC" in item for item in result.limitations)
    assert any("尚未运行回测" in item for item in result.limitations)


def test_factor_idea_allows_only_one_json_repair(
    runtime_install: tuple[Path, Path, Path],
) -> None:
    ark = MockArk("not-json", _idea_response())
    adapter = FactorIdeaGenerationAdapter(
        loader=InstructionSkillLoader(locator=_locator(runtime_install)),
        ark_client=ark,
    )

    result = adapter(_invocation("factor_idea_generation"), DEFAULT_SKILLS[0])

    assert result.status == SkillStatus.COMPLETED
    assert len(ark.prompts) == 2


def test_r020_calls_runtime_compute_factor_and_returns_provenance(
    runtime_install: tuple[Path, Path, Path],
) -> None:
    adapter = R020VolumeExpansionAdapter(locator=_locator(runtime_install))

    result = adapter(
        _invocation(
            "r020_volume_expansion",
            inputs={"market_data": _market_rows()},
        ),
        DEFAULT_SKILLS[1],
    )

    assert result.status == SkillStatus.COMPLETED
    assert result.data["factor_id"] == "R020"
    assert result.data["factor_column"] == "5d-z-scored-volume-expansion"
    assert result.data["observation_count"] == 50
    assert result.data["non_null_count"] > 0
    assert len(result.data["latest_values_by_symbol"]) == 2
    assert result.data["source_commit"] == "a" * 40
    assert result.provenance["license"] == "GPL-3.0-only"
    assert result.data["validation_status"] == "computed_not_validated"
    assert "signal" not in result.data


def test_r020_missing_ohlcv_field_fails(
    runtime_install: tuple[Path, Path, Path],
) -> None:
    rows = _market_rows()
    for row in rows:
        row.pop("volume")
    adapter = R020VolumeExpansionAdapter(locator=_locator(runtime_install))

    result = adapter(
        _invocation("r020_volume_expansion", inputs={"market_data": rows}),
        DEFAULT_SKILLS[1],
    )

    assert result.status == SkillStatus.FAILED
    assert "volume" in (result.error or "")


def test_quant_agent_can_call_only_factor_idea_generation() -> None:
    idea_adapter = StubAdapter(
        {
            "candidates": [],
            "shortlist": [],
            "validation_status": "unverified",
        }
    )
    r020_adapter = StubAdapter({})
    registry = SkillRegistry(
        adapters={
            "factor_idea_generation": idea_adapter,
            "r020_volume_expansion": r020_adapter,
        },
        register_default_adapters=False,
    )
    agent = QuantAgent(
        ark_client=MockArk(_skill_plan("factor_idea_generation")),
        data_client=MockPandaData(error=AssertionError("must not fetch data")),
        skill_registry=registry,
    )

    result = agent.execute(_quant_task())

    assert result.status == "completed"
    assert result.metadata["actual_skills"] == ["factor_idea_generation"]
    assert len(idea_adapter.calls) == 1
    assert r020_adapter.calls == []
    assert not any(call["tool"] == "pandadata_market_data" for call in result.tool_calls)


def test_quant_agent_can_call_only_r020_with_mocked_pandadata() -> None:
    r020_adapter = StubAdapter(
        {
            "factor_id": "R020",
            "coverage_ratio": 0.8,
            "validation_status": "computed_not_validated",
        }
    )
    registry = SkillRegistry(
        adapters={
            "factor_idea_generation": StubAdapter({}),
            "r020_volume_expansion": r020_adapter,
        },
        register_default_adapters=False,
    )
    panda = MockPandaData(_market_rows(("000001.SZ",)))
    agent = QuantAgent(
        ark_client=MockArk(_skill_plan("r020_volume_expansion")),
        data_client=panda,
        skill_registry=registry,
    )

    result = agent.execute(
        _quant_task(
            {
                "symbols": ["000001.SZ"],
                "start_date": "20240101",
                "end_date": "20240125",
            }
        )
    )

    assert result.status == "completed"
    assert result.metadata["actual_skills"] == ["r020_volume_expansion"]
    assert len(panda.calls) == 1
    assert len(r020_adapter.calls[0].inputs["market_data"]) == 25
    assert any(call["tool"] == "pandadata_market_data" for call in result.tool_calls)


def test_quant_agent_rejects_unauthorized_planner_output() -> None:
    invalid = _skill_plan("factor_backtest")
    registry = SkillRegistry(register_default_adapters=False)
    agent = QuantAgent(
        ark_client=MockArk(invalid, invalid),
        skill_registry=registry,
    )

    result = agent.execute(_quant_task())

    assert result.status == "failed"
    assert "一次修复" in (result.error or "")
    assert result.tool_calls == []


def test_quant_agent_requires_r020_dates_and_symbols_without_guessing() -> None:
    registry = SkillRegistry(
        adapters={"r020_volume_expansion": StubAdapter({})},
        register_default_adapters=False,
    )
    agent = QuantAgent(
        ark_client=MockArk(_skill_plan("r020_volume_expansion")),
        skill_registry=registry,
    )

    result = agent.execute(_quant_task({"symbols": ["000001.SZ"]}))

    assert result.status == "failed"
    assert result.metadata["needs_clarification"] is True
    assert "start_date" in result.metadata["clarification_question"]
    assert "end_date" in result.metadata["clarification_question"]


def test_quant_agent_requires_pool_for_cross_sectional_ranking() -> None:
    registry = SkillRegistry(
        adapters={"r020_volume_expansion": StubAdapter({})},
        register_default_adapters=False,
    )
    agent = QuantAgent(
        ark_client=MockArk(_skill_plan("r020_volume_expansion")),
        skill_registry=registry,
    )
    task = _quant_task(
        {
            "symbols": ["000001.SZ"],
            "start_date": "20240101",
            "end_date": "20240125",
        }
    )
    task.original_user_request = "请计算 R020 并做横截面排序"

    result = agent.execute(task)

    assert result.status == "failed"
    assert result.metadata["needs_clarification"] is True
    assert "至少需要两个 symbol" in result.metadata["clarification_question"]


def test_quant_to_risk_passes_factor_coverage_and_validation_status() -> None:
    quant = ExpertResult(
        task_id="quant_1",
        agent=AgentId.QUANT,
        status="completed",
        summary="R020 computed",
        evidence=[
            {
                "type": "skill_result",
                "skill_id": "r020_volume_expansion",
                "data": {
                    "factor_id": "R020",
                    "factor_name": "5D Z-Scored Volume Expansion",
                    "coverage_ratio": 0.72,
                    "validation_status": "computed_not_validated",
                },
                "validation_status": "computed_not_validated",
            }
        ],
        assumptions=["OHLCV 口径一致"],
        limitations=["尚未计算 IC"],
        metadata={
            "validation_status": "computed_not_validated",
            "provenance": [{"source_commit": "a" * 40}],
        },
    )
    risk_task = ExpertTask(
        task_id="risk_1",
        agent=AgentId.RISK,
        objective="审查 R020 失效风险",
        original_user_request="计算并审查风险",
        dependency_results={"quant_1": quant},
    )

    result = RiskAgent(ark_client=MockArk("结构化风险摘要。")).execute(risk_task)

    assert result.status == "completed"
    assert result.evidence[0]["validation_status"] == "computed_not_validated"
    assert result.evidence[0]["upstream_assumptions"] == ["OHLCV 口径一致"]
    assert result.evidence[0]["upstream_limitations"] == ["尚未计算 IC"]
    assert any("72.00%" in risk for risk in result.risks)
    assert any("尚未验证" in risk for risk in result.risks)


def test_quant_only_and_quant_to_risk_are_distinct_outer_graphs() -> None:
    executed: list[str] = []

    def handler(task: ExpertTask) -> ExpertResult:
        executed.append(task.agent.value)
        return ExpertResult(
            task_id=task.task_id,
            agent=task.agent,
            status="completed",
            summary="completed",
        )

    quant_only = _outer_plan(["quant"])
    quant_risk = _outer_plan(["quant", "risk"])
    executor = WorkflowExecutor(
        handlers={AgentId.QUANT: handler, AgentId.RISK: handler}
    )

    _, first_results = executor.execute(quant_only)
    first_path = executed.copy()
    executed.clear()
    _, second_results = executor.execute(quant_risk)

    assert first_path == ["quant"]
    assert executed == ["quant", "risk"]
    assert list(first_results) == ["quant_1"]
    assert list(second_results) == ["quant_1", "risk_1"]


def test_workflow_surfaces_safe_skill_events() -> None:
    def handler(task: ExpertTask) -> ExpertResult:
        return ExpertResult(
            task_id=task.task_id,
            agent=task.agent,
            status="completed",
            summary="done",
            metadata={
                "agent_events": [
                    {
                        "type": "skill_plan_created",
                        "metadata": {
                            "skill_id": None,
                            "selected_skill_count": 1,
                            "raw_market_data": [{"secret": "must not surface"}],
                        },
                    },
                    {
                        "type": "skill_started",
                        "skill_id": "factor_idea_generation",
                        "metadata": {"skill_id": "factor_idea_generation"},
                    },
                    {
                        "type": "skill_completed",
                        "skill_id": "factor_idea_generation",
                        "metadata": {
                            "skill_id": "factor_idea_generation",
                            "status": "completed",
                        },
                    },
                ]
            },
        )

    events, _ = WorkflowExecutor(
        handlers={AgentId.QUANT: handler}
    ).execute(_outer_plan(["quant"]))

    assert [event.type for event in events] == [
        "step_started",
        "skill_plan_created",
        "skill_started",
        "skill_completed",
        "step_completed",
    ]
    serialized = json.dumps(
        [event.model_dump(mode="json") for event in events],
        ensure_ascii=False,
    )
    assert "raw_market_data" not in serialized
    assert "must not surface" not in serialized
    assert all(event.step_id == "quant_1" for event in events)
    assert all(event.agent == AgentId.QUANT for event in events)


def test_quant_failure_does_not_leak_external_credentials() -> None:
    registry = SkillRegistry(
        adapters={"r020_volume_expansion": StubAdapter({})},
        register_default_adapters=False,
    )
    agent = QuantAgent(
        ark_client=MockArk(_skill_plan("r020_volume_expansion")),
        data_client=MockPandaData(
            error=RuntimeError("password=super-secret token=private")
        ),
        skill_registry=registry,
    )

    result = agent.execute(
        _quant_task(
            {
                "symbols": ["000001.SZ"],
                "start_date": "20240101",
                "end_date": "20240125",
            }
        )
    )
    serialized = result.model_dump_json()

    assert result.status == "failed"
    assert "super-secret" not in serialized
    assert "private" not in serialized


def _outer_plan(path: list[str]) -> ExecutionPlan:
    steps = []
    previous = None
    for agent in path:
        step_id = f"{agent}_1"
        steps.append(
            {
                "id": step_id,
                "agent": agent,
                "objective": f"{agent} objective",
                "inputs": {},
                "depends_on": [previous] if previous else [],
                "expected_output": f"{agent} output",
            }
        )
        previous = step_id
    return ExecutionPlan.model_validate(
        {
            "goal": "dynamic quant task",
            "intent": "quant research",
            "complexity": "low" if len(path) == 1 else "medium",
            "selected_agents": [
                {"agent": agent, "reason": f"need {agent}"}
                for agent in path
            ],
            "steps": steps,
        }
    )
