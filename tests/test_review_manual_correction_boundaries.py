from __future__ import annotations

import ast
from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_manual_correction_service_avoids_change_decision_dependency() -> None:
    content = _read("app/modules/review_changes/manual_correction_service.py")
    assert "app.modules.review_changes.change_decision_service" not in content


def test_manual_correction_service_only_exposes_entrypoints() -> None:
    path = Path("app/modules/review_changes/manual_correction_service.py")
    module = ast.parse(path.read_text(encoding="utf-8"))
    function_names = [node.name for node in module.body if isinstance(node, ast.FunctionDef)]
    assert function_names == ["preview_manual_correction", "apply_manual_correction"]


def test_manual_modules_do_not_import_change_decision_service() -> None:
    module_paths = [
        "app/modules/review_changes/manual_correction_target.py",
        "app/modules/review_changes/manual_correction_snapshot.py",
        "app/modules/review_changes/manual_correction_builder.py",
        "app/modules/review_changes/manual_correction_audit.py",
        "app/modules/review_changes/manual_correction_preview_flow.py",
        "app/modules/review_changes/manual_correction_apply_txn.py",
    ]
    for module_path in module_paths:
        content = _read(module_path)
        assert "app.modules.review_changes.change_decision_service" not in content
