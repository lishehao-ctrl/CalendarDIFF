from __future__ import annotations

import ast
from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_canonical_edit_service_wrapper_removed() -> None:
    assert not Path("app/modules/review_changes/canonical_edit_service.py").exists()

def test_edit_service_avoids_change_decision_dependency() -> None:
    content = _read("app/modules/review_changes/edit_service.py")
    assert "app.modules.review_changes.change_decision_service" not in content


def test_canonical_edit_modules_do_not_import_change_decision_service() -> None:
    module_paths = [
        "app/modules/review_changes/canonical_edit_target.py",
        "app/modules/review_changes/canonical_edit_snapshot.py",
        "app/modules/review_changes/canonical_edit_builder.py",
        "app/modules/review_changes/canonical_edit_audit.py",
        "app/modules/review_changes/canonical_edit_preview_flow.py",
        "app/modules/review_changes/canonical_edit_apply_txn.py",
    ]
    for module_path in module_paths:
        content = _read(module_path)
        assert "app.modules.review_changes.change_decision_service" not in content
