#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = PROJECT_ROOT / "contracts" / "openapi"
SNAPSHOT_PATH = SNAPSHOT_DIR / "public-service.json"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.public_api.main import app as public_app


def main() -> int:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    payload = public_app.openapi()
    SNAPSHOT_PATH.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(f"updated {SNAPSHOT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
