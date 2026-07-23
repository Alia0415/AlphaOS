"""Manual real-service smoke test for AlphaOS v0.3.

Run from the AlphaOS repository root after configuring ARK_API_KEY and
PandaData credentials. This script is intentionally excluded from automated
tests and never prints credential values or raw external responses.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from time import perf_counter

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from backend.agents.manager_agent import ManagerAgent, ManagerAgentError
from backend.core.contracts import ExpertResult
from backend.core.workflow_executor import WorkflowExecutor


REQUESTS = (
    "分析 000001.SZ 在 2024 年的价格表现。",
    "分析 000001.SZ 在 2024 年的表现并识别风险。",
    "分析 000001.SZ 在 2024 年的表现，识别风险并生成研究报告。",
)


def main() -> None:
    manager = ManagerAgent()
    executor = WorkflowExecutor()
    for index, request in enumerate(REQUESTS, start=1):
        print(f"\n=== Scenario {index} ===")
        print(f"Request: {request}")
        started = perf_counter()
        try:
            plan = manager.create_plan(request)
            print("Manager Task Graph:")
            print(
                json.dumps(
                    [
                        {
                            "step_id": step.id,
                            "agent": step.agent.value,
                            "depends_on": step.depends_on,
                        }
                        for step in plan.steps
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
            )
            events, results = executor.execute(plan, request)
            print("Actual Execution Events:")
            print(
                json.dumps(
                    [
                        {
                            "type": event.type,
                            "step_id": event.step_id,
                            "agent": (
                                event.agent.value if event.agent else None
                            ),
                            "message": event.message,
                        }
                        for event in events
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
            )
            print("PandaData Tool Calls:")
            print(
                json.dumps(
                    _tool_calls(results),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            print("Structured Expert Results:")
            print(
                json.dumps(
                    {
                        step_id: result.model_dump(mode="json")
                        for step_id, result in results.items()
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            print("Manager Final Answer:")
            print(manager.synthesize(request, plan, results))
        except ManagerAgentError as exc:
            print(f"Integration error: {exc}")
        except Exception:
            print("Integration error: dynamic execution failed.")
        finally:
            elapsed = round((perf_counter() - started) * 1000)
            print(f"Duration: {elapsed} ms")


def _tool_calls(results: dict[str, ExpertResult]) -> list[dict[str, object]]:
    return [
        {
            "step_id": step_id,
            "agent": result.agent.value,
            "tool": call.get("tool"),
            "status": call.get("status"),
            "arguments": call.get("arguments", {}),
        }
        for step_id, result in results.items()
        for call in result.tool_calls
    ]


if __name__ == "__main__":
    main()
