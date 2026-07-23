"""Opt-in real PandaData smoke test for Research Agent financial analysis."""

from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from backend.agents.research_agent import ResearchAgent  # noqa: E402
from backend.core.contracts import AgentId, ExpertTask  # noqa: E402
from backend.services.pandadata_client import PandaDataClient  # noqa: E402


def main() -> None:
    client = PandaDataClient()
    if not client.configured:
        print(json.dumps({"status": "skipped"}, ensure_ascii=False))
        return

    result = ResearchAgent(data_client=client).execute(
        ExpertTask(
            task_id="manual_research_dossier",
            agent=AgentId.RESEARCH,
            objective="分析贵州茅台最近三个财务年度的财报。",
            original_user_request=(
                "分析贵州茅台最近三个财务年度的财报，重点关注盈利质量和现金流。"
            ),
            inputs={
                "symbol": "600519.SH",
                "period": "latest_3_fiscal_years",
                "scope": "financials",
                "focus": ["profitability", "cash_flow_quality"],
            },
        )
    )
    if not result.evidence:
        print(
            json.dumps(
                {
                    "status": result.metadata.get(
                        "validation_status",
                        result.status,
                    )
                },
                ensure_ascii=False,
            )
        )
        return

    data = result.evidence[0].get("data", {})
    metric_names = sorted(
        {
            str(item.get("metric"))
            for section_name in (
                "growth",
                "profitability",
                "cash_flow_quality",
                "solvency",
                "operating_efficiency",
            )
            for item in data.get(section_name, {}).get("derived_metrics", [])
            if item.get("metric")
        }
    )
    provenance = result.metadata.get("provenance", {})
    print(
        json.dumps(
            {
                "status": result.status,
                "symbol": data.get("symbol"),
                "periods": data.get("periods", []),
                "interfaces": [
                    {
                        "method": item.get("method"),
                        "row_count": item.get("row_count"),
                    }
                    for item in data.get("data_scope", [])
                ],
                "core_metrics": metric_names,
                "risk_signal_count": len(data.get("risk_signals", [])),
                "validation_status": result.metadata.get("validation_status"),
                "provenance": {
                    "repository": provenance.get("source_repository"),
                    "commit": provenance.get("source_commit"),
                    "license": provenance.get("license"),
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
