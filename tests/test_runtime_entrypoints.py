from __future__ import annotations

import importlib
from pathlib import Path


def test_monolith_runtime_entrypoints_importable() -> None:
    importlib.import_module("services.app_api.main")



def test_split_service_runtime_entrypoints_absent() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    removed_paths = [
        repo_root / "services" / "input_api",
        repo_root / "services" / "ingest_api",
        repo_root / "services" / "review_api",
        repo_root / "services" / "notification_api",
        repo_root / "services" / "llm_api",
        repo_root / "scripts" / "check_microservice_closure.py",
        repo_root / "scripts" / "smoke_microservice_closure.py",
        repo_root / "scripts" / "ops_slo_check.py",
    ]
    for path in removed_paths:
        assert not path.exists(), f"split-runtime artifact should remain absent: {path}"
