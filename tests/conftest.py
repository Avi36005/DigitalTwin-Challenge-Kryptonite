from __future__ import annotations

import json

import pytest
from glucotwin.config import paths
from glucotwin.data.pipeline import synthetic_store_dir


@pytest.fixture(scope="session")
def synthetic_ready():
    """Synthetic fixtures + synthetic demonstration model (built once; no download needed)."""
    from glucotwin.data.pipeline import build_synthetic
    from glucotwin.data.store import Store
    from glucotwin.synthetic_model import VERSION, train

    reg = paths().artifacts / "registry.json"
    have_model = reg.exists() and json.loads(reg.read_text()).get("serving", {}).get("synthetic_demo") == VERSION
    if not Store(synthetic_store_dir()).exists():
        build_synthetic()
    if not have_model:
        train()
    return True


@pytest.fixture()
def client(synthetic_ready, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from glucotwin_api.app import create_app

    monkeypatch.setenv("GLUCOTWIN_VAR_DIR", str(tmp_path / "var"))
    return TestClient(create_app())
