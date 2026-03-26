from __future__ import annotations

from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_core_ingest_apply_modules_import_unified_apply_module_only() -> None:
    paths = [
        "app/modules/runtime/apply/calendar_apply.py",
        "app/modules/runtime/apply/gmail_apply.py",
        "app/modules/runtime/apply/apply.py",
    ]
    for path in paths:
        content = _read(path)
        assert "app.modules.runtime.apply.apply_service" not in content
        assert "app.modules.runtime.apply.apply_orchestrator" not in content
        assert "app.modules.runtime.apply.pending_rebuild" not in content


def test_review_change_services_do_not_import_router_modules() -> None:
    service_files = [
        "app/modules/changes/change_listing_service.py",
        "app/modules/changes/change_decision_service.py",
        "app/modules/changes/change_evidence_service.py",
        "app/modules/changes/edit_service.py",
    ]
    forbidden_tokens = ["app.modules.changes.router"]
    for path in service_files:
        content = _read(path)
        for token in forbidden_tokens:
            assert token not in content, f"{path} must not import {token}"
