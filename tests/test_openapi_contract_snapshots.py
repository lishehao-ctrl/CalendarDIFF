from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from services.public_api.main import app as public_app

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = PROJECT_ROOT / "contracts" / "openapi" / "public-service.json"


def _canonical(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2) + "\n"


def test_openapi_contract_snapshots(db_engine) -> None:
    del db_engine
    assert SNAPSHOT_PATH.is_file(), f"missing OpenAPI snapshot: {SNAPSHOT_PATH}"
    with TestClient(public_app) as client:
        response = client.get("/openapi.json")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, dict)
    assert _canonical(payload) == SNAPSHOT_PATH.read_text(encoding="utf-8")
