import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)
REPO_ROOT = Path(__file__).resolve().parents[1]


def test_frontend_entrypoint_is_served() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "AlphaOS · Research Console" in response.text
    assert 'src="/static/app.js?v=' in response.text
    assert "看得懂版" in response.text
    assert "专业证据" in response.text
    assert "真实研究" in response.text
    assert "API Key" not in response.text
    assert 'id="disclaimer"' in response.text


def test_frontend_assets_are_served() -> None:
    script = client.get("/static/app.js")
    styles = client.get("/static/styles.css")

    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]
    assert "renderResponse" in script.text
    assert "用户无需填写任何 API Key" in script.text
    assert styles.status_code == 200
    assert "text/css" in styles.headers["content-type"]
    assert ".console-card" in styles.text
    assert "buildPlainLanguageResult" in script.text
    assert "BLOCK_RENDERERS" in script.text
    assert "renderContentBlocks" in script.text


def test_office_user_profile_module_is_served() -> None:
    client = TestClient(app)

    profile = client.get("/static/office/js/profile.js")
    office = client.get("/office")

    assert profile.status_code == 200
    assert "openProfileOnboarding" in profile.text
    assert "SQLite" in profile.text
    assert office.status_code == 200


def test_presentation_modules_are_served() -> None:
    status = client.get("/static/presentation/status-labels.js")
    events = client.get("/static/presentation/event-labels.js")
    adapter = client.get("/static/presentation/build-plain-language-result.js")

    assert status.status_code == 200
    assert "computed_not_validated" in status.text
    assert events.status_code == 200
    assert "pandadata_market_data" in events.text
    assert adapter.status_code == 200
    assert "buildPlainLanguageResult" in adapter.text
    assert "source.aggregation" in adapter.text


def test_frontend_presentation_adapter() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the zero-dependency frontend unit tests")

    completed = subprocess.run(
        [node, "tests/test_frontend_presentation.cjs"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "frontend presentation tests passed" in completed.stdout
