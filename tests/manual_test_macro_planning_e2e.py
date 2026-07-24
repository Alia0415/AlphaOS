"""Opt-in real Ark + PandaData end-to-end check for Macro plan validation.

Run from the AlphaOS root after setting PandaData and Ark credentials. This
mirrors the production planning path (ManagerAgent.create_plan) so it exercises
the new Macro step-input validation and the single controlled repair attempt.

Scenario A: a genuine macro request should plan a complete macro step (with
non-empty industry/time_range/research_goal) and execute to completion.
Scenario B: a single-stock request that previously mis-triggered an incomplete
macro step should either drop macro or plan it with valid industry inputs, so no
step fails at execution time for missing macro inputs.

The script prints only bounded plan/result metadata and never prints
credentials, raw PandaData rows, prompts, or exception details.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from backend.agents.manager_agent import ManagerAgent, ManagerAgentError  # noqa: E402
from backend.core.contracts import AgentId, ExecutionPlan  # noqa: E402
from backend.services.pandadata_client import PandaDataClient  # noqa: E402
from backend.core.workflow_executor import WorkflowExecutor  # noqa: E402


def _plan_view(plan: ExecutionPlan) -> dict[str, object]:
    steps = []
    for step in plan.steps:
        entry: dict[str, object] = {
            "id": step.id,
            "agent": step.agent.value,
            "depends_on": list(step.depends_on),
        }
        if step.agent == AgentId.MACRO:
            entry["macro_inputs"] = {
                key: step.inputs.get(key)
                for key in (
                    "industry",
                    "time_range",
                    "research_goal",
                    "start_date",
                    "end_date",
                )
            }
        steps.append(entry)
    return {
        "needs_clarification": plan.needs_clarification,
        "selected_agents": [item.agent.value for item in plan.selected_agents],
        "steps": steps,
    }


def _run(label: str, prompt: str, *, execute: bool) -> None:
    manager = ManagerAgent()
    print(f"\n=== {label} ===")
    print(f"prompt: {prompt}")
    try:
        plan = manager.create_plan(prompt)
    except ManagerAgentError:
        print(json.dumps({"planning": "manager_error"}, ensure_ascii=False))
        return

    print(json.dumps(_plan_view(plan), ensure_ascii=False, indent=2))

    if not execute or plan.needs_clarification:
        return

    events, results = WorkflowExecutor().execute(plan, prompt)
    print(
        json.dumps(
            {
                "results": {
                    step_id: result.status for step_id, result in results.items()
                },
                "macro_missing_input_failure": any(
                    result.agent == AgentId.MACRO
                    and result.status == "failed"
                    and "industry" in (result.error or "")
                    for result in results.values()
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> None:
    if not PandaDataClient().configured:
        print(json.dumps({"status": "skipped", "reason": "no PandaData creds"}))
        return

    _run(
        "A: genuine macro request",
        "评估新能源汽车行业未来6到12个月的宏观、政策与流动性环境。",
        execute=True,
    )
    _run(
        "B: single-stock request (previously mis-triggered macro)",
        "分析比亚迪 002594.SZ 最近一年的股价表现和主要风险。",
        execute=False,
    )


if __name__ == "__main__":
    main()
