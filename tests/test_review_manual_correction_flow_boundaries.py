from __future__ import annotations

from pathlib import Path


def test_manual_correction_service_is_orchestration_only() -> None:
    content = Path("app/modules/review_changes/manual_correction_service.py").read_text(encoding="utf-8")
    assert "db.commit(" not in content
    assert "with_for_update(" not in content
    assert "select(" not in content


def test_manual_correction_service_uses_flow_modules() -> None:
    content = Path("app/modules/review_changes/manual_correction_service.py").read_text(encoding="utf-8")
    assert "app.modules.review_changes.manual_correction_preview_flow" in content
    assert "app.modules.review_changes.manual_correction_apply_txn" in content
