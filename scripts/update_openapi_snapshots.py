#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from services.ingest_api.main import app as ingest_app
from services.input_api.main import app as input_app
from services.llm_api.main import app as llm_app
from services.notification_api.main import app as notification_app
from services.public_api.main import app as public_app
from services.review_api.main import app as review_app

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = PROJECT_ROOT / "contracts" / "openapi"

APPS = {
    "public-service": public_app,
    "input-service": input_app,
    "ingest-service": ingest_app,
    "review-service": review_app,
    "notification-service": notification_app,
    "llm-service": llm_app,
}


def main() -> int:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    for service_name, app in APPS.items():
        payload = app.openapi()
        target = SNAPSHOT_DIR / f"{service_name}.json"
        target.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(f"updated {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
