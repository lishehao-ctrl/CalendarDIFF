from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from services.ingest_api.main import app as ingest_app
from services.input_api.main import app as input_app
from services.notification_api.main import app as notification_app
from services.review_api.main import app as review_app

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = PROJECT_ROOT / "contracts" / "openapi"


def _canonical(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2) + "\n"


def _load_snapshot(name: str) -> str:
    path = SNAPSHOT_DIR / f"{name}.json"
    assert path.is_file(), f"missing OpenAPI snapshot: {path}"
    return path.read_text(encoding="utf-8")


def test_openapi_contract_snapshots(db_engine) -> None:
    del db_engine
    app_map = {
        "input-service": input_app,
        "ingest-service": ingest_app,
        "review-service": review_app,
        "notification-service": notification_app,
    }
    for name, app in app_map.items():
        with TestClient(app) as client:
            response = client.get("/openapi.json")
        assert response.status_code == 200
        payload = response.json()
        assert isinstance(payload, dict)
        assert _canonical(payload) == _load_snapshot(name)
