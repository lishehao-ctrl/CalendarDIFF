from __future__ import annotations

from pathlib import Path


def test_canonical_edit_service_is_orchestration_only() -> None:
    content = Path("app/modules/review_changes/canonical_edit_service.py").read_text(encoding="utf-8")
    assert "db.commit(" not in content
    assert "with_for_update(" not in content
    assert "select(" not in content


def test_canonical_edit_service_uses_flow_modules() -> None:
    content = Path("app/modules/review_changes/canonical_edit_service.py").read_text(encoding="utf-8")
    assert "app.modules.review_changes.canonical_edit_preview_flow" in content
    assert "app.modules.review_changes.canonical_edit_apply_txn" in content
