"""Read-only surfaces: experts, skills, overview shapes and toggle effects."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend import main as main_module


def _client() -> TestClient:
    return TestClient(main_module.app)


def test_experts_expose_full_pool_with_enabled_flags() -> None:
    body = _client().get("/api/experts").json()

    by_id = {expert["id"]: expert for expert in body}
    assert set(by_id) == {"research", "quant", "risk", "portfolio", "macro", "report"}
    assert by_id["portfolio"]["enabled"] is False
    assert by_id["research"]["enabled"] is True
    assert "a_share_stock_dossier" in by_id["research"]["skills"]
    assert set(by_id["quant"]) == {
        "id",
        "name",
        "description",
        "enabled",
        "capabilities",
        "tools",
        "skills",
    }


def test_skills_are_read_only_and_owned() -> None:
    body = _client().get("/api/skills").json()

    by_id = {skill["id"]: skill for skill in body}
    assert {"factor_idea_generation", "r020_volume_expansion", "a_share_stock_dossier"} <= set(by_id)
    assert by_id["factor_idea_generation"]["owner_agents"] == ["quant"]
    assert by_id["a_share_stock_dossier"]["owner_agents"] == ["research"]
    assert set(by_id["r020_volume_expansion"]) == {
        "id",
        "name",
        "description",
        "mode",
        "enabled",
        "owner_agents",
        "capabilities",
    }


def test_overview_reports_real_counts() -> None:
    body = _client().get("/api/overview").json()

    assert body["enabled_experts"] == 5
    assert body["enabled_skills"] == 3
    assert body["total_tasks"] == 0
    assert body["completed_tasks"] == 0
    assert body["report_count"] == 0
    assert body["average_completion"] == 0.0


def test_toggle_expert_persists_and_reflects_in_reads() -> None:
    client = _client()

    disabled = client.post("/api/experts/quant/enabled", json={"enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False

    experts = {e["id"]: e for e in client.get("/api/experts").json()}
    assert experts["quant"]["enabled"] is False
    assert client.get("/api/overview").json()["enabled_experts"] == 4

    reenabled = client.post("/api/experts/quant/enabled", json={"enabled": True})
    assert reenabled.json()["enabled"] is True


def test_enabling_portfolio_is_rejected() -> None:
    response = _client().post("/api/experts/portfolio/enabled", json={"enabled": True})
    assert response.status_code == 409


def test_unknown_expert_toggle_returns_404() -> None:
    response = _client().post("/api/experts/nonsense/enabled", json={"enabled": False})
    assert response.status_code == 404
