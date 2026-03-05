#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _service_block(compose_text: str, service_name: str) -> str:
    pattern = re.compile(
        rf"^  {re.escape(service_name)}:\n(?P<body>(?:^(?!  [a-z0-9-]+:).*\n)*)",
        flags=re.MULTILINE,
    )
    match = pattern.search(compose_text)
    if not match:
        return ""
    return match.group("body")


def main() -> int:
    errors: list[str] = []

    # 1) Monolith references must be removed.
    scan_paths = [
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / "docs",
        PROJECT_ROOT / "Dockerfile",
        PROJECT_ROOT / "docker-compose.yml",
        PROJECT_ROOT / "docker-compose.dev.yml",
    ]
    forbidden_patterns = ("app." + "main:app", "scripts/" + "start.sh")
    for path in scan_paths:
        files = [path] if path.is_file() else [p for p in path.rglob("*") if p.is_file()]
        for file in files:
            if file.resolve() == Path(__file__).resolve():
                continue
            try:
                content = file.read_text(encoding="utf-8")
            except Exception:
                continue
            for token in forbidden_patterns:
                if token in content:
                    errors.append(f"forbidden token '{token}' found in {file}")

    # 1b) Removed worker entrypoints must remain absent.
    removed_paths = [
        PROJECT_ROOT / "services" / "ingestion_runtime" / "worker.py",
        PROJECT_ROOT / "services" / "notification" / "worker.py",
    ]
    for path in removed_paths:
        if path.exists():
            errors.append(f"removed entrypoint should remain absent: {path}")

    # 2) Internal routers must not depend on require_api_key.
    for file in (PROJECT_ROOT / "app" / "modules").rglob("*.py"):
        content = file.read_text(encoding="utf-8")
        if 'prefix="/internal' in content and "require_api_key" in content:
            errors.append(f"internal router still references require_api_key: {file}")

    # 3) Default compose must not expose ingest/notification/llm host ports.
    compose_path = PROJECT_ROOT / "docker-compose.yml"
    compose_text = compose_path.read_text(encoding="utf-8")
    for service_name in ("ingest-service", "notification-service", "llm-service"):
        body = _service_block(compose_text, service_name)
        if not body:
            errors.append(f"service block not found in docker-compose.yml: {service_name}")
            continue
        if re.search(r"^\s{4}ports:\s*$", body, flags=re.MULTILINE):
            errors.append(f"default compose should not expose host ports for {service_name}")

    # 4) OpenAPI snapshots must exist.
    snapshot_dir = PROJECT_ROOT / "contracts" / "openapi"
    expected_snapshots = [
        snapshot_dir / "input-service.json",
        snapshot_dir / "ingest-service.json",
        snapshot_dir / "review-service.json",
        snapshot_dir / "notification-service.json",
        snapshot_dir / "llm-service.json",
    ]
    for snapshot in expected_snapshots:
        if not snapshot.is_file():
            errors.append(f"missing OpenAPI snapshot: {snapshot}")

    summary = {
        "valid": not errors,
        "errors": errors,
    }
    print(json.dumps(summary, ensure_ascii=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
