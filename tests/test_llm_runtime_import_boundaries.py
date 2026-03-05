from __future__ import annotations

from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_ingestion_does_not_import_llm_worker_modules() -> None:
    ingestion_files = Path("app/modules/ingestion").glob("*.py")
    forbidden_tokens = [
        "app.modules.llm_runtime.worker",
        "app.modules.llm_runtime.worker_tick",
    ]
    for path in ingestion_files:
        content = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            assert token not in content, f"{path} must not import {token}"


def test_worker_tick_does_not_import_ingestion_runtime_modules() -> None:
    content = _read("app/modules/llm_runtime/worker_tick.py")
    assert "app.modules.ingestion.connector_runtime" not in content
    assert "app.modules.ingestion.connector_dispatch" not in content
    assert "app.modules.ingestion.orchestrator" not in content
