from __future__ import annotations

from pathlib import Path


def test_canonical_edit_service_wrapper_removed() -> None:
    assert not Path("app/modules/changes/canonical_edit_service.py").exists()

def test_edit_service_uses_canonical_edit_flow_modules() -> None:
    content = Path("app/modules/changes/edit_service.py").read_text(encoding="utf-8")
    assert "app.modules.changes.canonical_edit_preview_flow" in content
    assert "app.modules.changes.canonical_edit_apply_txn" in content
