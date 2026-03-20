from __future__ import annotations

from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_ingestion_does_not_import_llm_worker_modules() -> None:
    ingestion_files = Path("app/modules/runtime/connectors").glob("*.py")
    forbidden_tokens = [
        "app.modules.runtime.llm.",
    ]
    for path in ingestion_files:
        content = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            assert token not in content, f"{path} must not import {token}"


def test_tick_runner_does_not_import_ingestion_runtime_modules() -> None:
    content = _read("app/modules/runtime/llm/tick_runner.py")
    assert "app.modules.runtime.connectors.connector_runtime" not in content
    assert "app.modules.runtime.connectors.connector_dispatch" not in content
    assert "app.modules.runtime.connectors.orchestrator" not in content
