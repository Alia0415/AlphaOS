"""Opt-in real Ark + PandaData macro smoke test.

Run from the AlphaOS root after setting PandaData and Ark credentials. The
script prints only bounded macro metadata and never prints credentials, raw
PandaData rows, prompts, or exception details.
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

from backend.agents.macro_agent import MacroAgent  # noqa: E402
from backend.core.contracts import AgentId, ExpertTask  # noqa: E402
from backend.services.pandadata_client import PandaDataClient  # noqa: E402


def main() -> None:
    data_client = PandaDataClient()
    if not data_client.configured:
        print(
            json.dumps(
                {
                    "status": "skipped",
                    "reason": (
                        "PandaData credentials are not configured; set "
                        "PANDADATA_USERNAME and PANDADATA_PASSWORD."
                    ),
                },
                ensure_ascii=False,
            )
        )
        return

    task = ExpertTask(
        task_id="manual_macro_1",
        agent=AgentId.MACRO,
        objective="判断新能源行业未来 12 个月的宏观支持程度",
        original_user_request="分析新能源行业未来 12 个月的投资机会",
        inputs={
            "industry": "新能源",
            "time_range": "未来12个月",
            "research_goal": "判断宏观环境支持程度",
        },
    )

    result = MacroAgent(data_client=data_client).execute(task)

    print(
        json.dumps(
            {
                "status": result.status,
                "categories": result.metadata.get("data_plan", {}).get(
                    "categories", []
                ),
                "symbols": [
                    item.get("symbol") for item in result.evidence
                ],
                "tool_calls": [
                    {
                        "tool": item.get("tool"),
                        "status": item.get("status"),
                    }
                    for item in result.tool_calls
                ],
                "sources": [
                    {
                        "api_name": item.get("api_name"),
                        "row_count": item.get("row_count"),
                    }
                    for item in result.data_sources
                ],
                "macro_analysis": result.metadata.get("macro_analysis", {}),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    if result.status != "completed":
        sys.exit(1)


if __name__ == "__main__":
    main()
