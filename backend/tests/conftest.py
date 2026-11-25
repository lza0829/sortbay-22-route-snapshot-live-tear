from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app import config

    db_path = tmp_path / "sortbay-test.db"
    monkeypatch.setattr(config, "DB_PATH", db_path)
    # Tests construct exactly the scans they need; the human-facing demo scan
    # would otherwise bias counts and block the pristine shift-seal path.
    monkeypatch.setenv("SORTBAY_SEED_DEMO_SCANS", "0")

    from app.seed import seed_if_empty

    seed_if_empty(include_demo_scan=False)

    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def chute_ids(client):
    rows = client.get("/api/口门").json()
    return {row["code"]: row["id"] for row in rows}


@pytest.fixture()
def loaded_scan(client):
    def _load(barcode: str = "YB-TEST-001", dest: str = "110"):
        response = client.post("/api/扫描", json={"条码": barcode, "目的地码": dest})
        assert response.status_code == 200, response.text
        return response.json()

    return _load


def route_to_chute(client, dest: str, chute_id: int):
    response = client.post(
        "/api/路由表",
        json={"目的地码": dest, "口门编号": chute_id, "备注": "测试改档"},
    )
    assert response.status_code == 200, response.text
    return response.json()
