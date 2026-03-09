from __future__ import annotations

from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_core_ingest_apply_modules_do_not_import_apply_service() -> None:
    paths = [
        "app/modules/core_ingest/calendar_apply.py",
        "app/modules/core_ingest/gmail_apply.py",
        "app/modules/core_ingest/apply_orchestrator.py",
    ]
    for path in paths:
        content = _read(path)
        assert "app.modules.core_ingest.apply_service" not in content
        assert "app.modules.core_ingest.pending_rebuild" not in content


def test_review_change_services_do_not_import_router_or_legacy_service() -> None:
    service_files = [
        "app/modules/review_changes/change_listing_service.py",
        "app/modules/review_changes/change_decision_service.py",
        "app/modules/review_changes/evidence_preview_service.py",
        "app/modules/review_changes/canonical_edit_service.py",
    ]
    forbidden_tokens = [
        "app.modules.review_changes.router",
        "app.modules.review_changes." + "service",
    ]
    for path in service_files:
        content = _read(path)
        for token in forbidden_tokens:
            assert token not in content, f"{path} must not import {token}"
