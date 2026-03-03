from __future__ import annotations

import importlib
from pathlib import Path


def test_microservice_runtime_entrypoints_importable() -> None:
    importlib.import_module("services.input_api.main")
    importlib.import_module("services.ingest_api.main")
    importlib.import_module("services.review_api.main")
    importlib.import_module("services.notification_api.main")
    importlib.import_module("services.ingestion_runtime.worker")
    importlib.import_module("services.notification.worker")


def test_legacy_runtime_entrypoints_removed() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    removed_paths = [
        repo_root / "app" / "main.py",
        repo_root / "services" / "core_api" / "main.py",
        repo_root / "services" / "input_control_plane" / "main.py",
        repo_root / "services" / "ingestion_orchestrator" / "worker.py",
        repo_root / "services" / "connector_runtime" / "worker.py",
        repo_root / "services" / "core_apply_worker" / "worker.py",
        repo_root / "scripts" / "start.sh",
    ]
    for path in removed_paths:
        assert not path.exists(), f"legacy entrypoint should be removed: {path}"
