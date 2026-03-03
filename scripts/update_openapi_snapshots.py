#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.ingest_api.main import app as ingest_app
from services.input_api.main import app as input_app
from services.notification_api.main import app as notification_app
from services.review_api.main import app as review_app

SNAPSHOT_DIR = PROJECT_ROOT / "contracts" / "openapi"

APPS = {
    "input-service": input_app,
    "ingest-service": ingest_app,
    "review-service": review_app,
    "notification-service": notification_app,
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
