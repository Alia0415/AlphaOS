"""Opt-in PandaData + pinned R020 integration smoke test.

Run from the AlphaOS root after setting PandaData credentials. The script prints
only bounded calculation metadata and never prints credentials or raw OHLCV.
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

from backend.services.pandadata_client import PandaDataClient  # noqa: E402
from backend.skills.contracts import SkillInvocation  # noqa: E402
from backend.skills.skill_registry import SkillRegistry  # noqa: E402


SYMBOLS = ["000001.SZ", "000002.SZ", "600519.SH"]
START_DATE = "20240101"
END_DATE = "20241231"
FIELDS = ["open", "high", "low", "close", "volume"]


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

    market_data = data_client.get_market_data(
        symbols=SYMBOLS,
        start_date=START_DATE,
        end_date=END_DATE,
        fields=FIELDS,
        indicator="000300",
        st=True,
    )
    result = SkillRegistry().execute(
        SkillInvocation(
            invocation_id="manual-pandadata-r020",
            skill_id="r020_volume_expansion",
            agent="quant",
            objective="计算指定标的 2024 年 R020 因子",
            inputs={"market_data": market_data},
        )
    )
    safe_output = {
        "status": result.status.value,
        "summary": result.summary,
        "factor_id": result.data.get("factor_id"),
        "factor_column": result.data.get("factor_column"),
        "observation_count": result.data.get("observation_count"),
        "non_null_count": result.data.get("non_null_count"),
        "coverage_ratio": result.data.get("coverage_ratio"),
        "date_range": result.data.get("date_range"),
        "symbols": [
            item.get("symbol")
            for item in result.data.get("latest_values_by_symbol", [])
        ],
        "source_repository": result.data.get("source_repository"),
        "source_commit": result.data.get("source_commit"),
        "license": result.data.get("license"),
        "validation_status": result.data.get("validation_status"),
        "error": result.error,
    }
    print(json.dumps(safe_output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
