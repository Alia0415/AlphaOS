"""Shared pytest fixtures: isolate every test from the real AlphaOS database."""

from __future__ import annotations

import os
import tempfile

# Redirect the default store path before any backend import creates the file.
os.environ.setdefault(
    "ALPHAOS_DB",
    os.path.join(tempfile.gettempdir(), "alphaos_pytest_default.db"),
)

import pytest

from backend.core import store as store_module


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Give each test a private SQLite file and wire it into the app + module."""

    test_store = store_module.Store(tmp_path / "alphaos.db")
    monkeypatch.setattr(store_module, "_default_store", test_store)
    try:
        from backend import main as main_module

        monkeypatch.setattr(main_module, "store", test_store, raising=False)
    except Exception:
        # Tests that never touch the FastAPI app still get an isolated store.
        pass
    yield test_store
    test_store.close()
