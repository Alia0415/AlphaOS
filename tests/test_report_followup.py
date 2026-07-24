"""Report follow-up returns evidence fragments and persists the exchange."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from backend import main as main_module


def _seed_report() -> str:
    report_id = uuid.uuid4().hex
    task_id = uuid.uuid4().hex
    main_module.store.create_task(
        task_id=task_id,
        prompt="分析 000001.SZ 在 2024 年的价格表现。",
        status="completed",
        plan={"goal": "分析 000001.SZ", "steps": []},
    )
    aggregation = {
        "user_goal": "分析 000001.SZ",
        "completion_status": "completed",
        "output_mode": "data_analysis",
        "direct_answer": {
            "headline": "平安银行 2024 年全年上涨",
            "explanation": "区间累计收益为正，成交量整体放大。",
            "confidence": "medium",
            "stance": "neutral",
        },
        "content_blocks": [
            {
                "id": "b1",
                "type": "metric_cards",
                "title": "区间收益",
                "importance": "primary",
                "description": "period_return 指标显示全年收益率约 15%。",
                "data": {"period_return": "15%", "max_drawdown": "8%"},
            }
        ],
    }
    main_module.store.create_report(
        report_id=report_id,
        task_id=task_id,
        title="分析 000001.SZ",
        completeness={
            "planned_steps": 1,
            "completed_steps": 1,
            "failed_steps": 0,
            "blocked_steps": 0,
            "completion_ratio": 1.0,
            "evidence_coverage_ratio": 1.0,
            "validation_summary": {},
        },
        aggregation=aggregation,
    )
    return report_id


def test_followup_returns_matching_evidence_and_persists() -> None:
    report_id = _seed_report()
    client = TestClient(main_module.app)

    response = client.post(
        f"/api/reports/{report_id}/followup",
        json={"question": "区间收益是多少？"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "assistant"
    assert body["evidence"], "expected at least one matching evidence fragment"
    sources = {fragment["source"] for fragment in body["evidence"]}
    assert "b1" in sources

    # Both the user question and the assistant answer are persisted.
    detail = client.get(f"/api/reports/{report_id}").json()
    roles = [f["role"] for f in detail["followups"]]
    assert roles == ["user", "assistant"]
    assert detail["followups"][0]["text"] == "区间收益是多少？"
    assert detail["followups"][1]["evidence"]


def test_followup_without_match_returns_empty_evidence() -> None:
    report_id = _seed_report()
    client = TestClient(main_module.app)

    response = client.post(
        f"/api/reports/{report_id}/followup",
        json={"question": "完全无关的外星科技问题 zzz"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["evidence"] == []

    detail = client.get(f"/api/reports/{report_id}").json()
    assert [f["role"] for f in detail["followups"]] == ["user", "assistant"]


def test_followup_on_missing_report_returns_404() -> None:
    response = TestClient(main_module.app).post(
        "/api/reports/nope/followup",
        json={"question": "任意问题"},
    )
    assert response.status_code == 404
