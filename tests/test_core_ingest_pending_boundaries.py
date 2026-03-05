from __future__ import annotations

import ast
from pathlib import Path


def test_pending_rebuild_monolith_module_is_removed() -> None:
    assert not Path("app/modules/core_ingest/pending_rebuild.py").exists()


def test_no_imports_reference_removed_pending_rebuild_module() -> None:
    roots = [
        Path("app"),
        Path("services"),
        Path("tests"),
        Path("scripts"),
    ]
    violations: list[str] = []
    token = "app.modules.core_ingest.pending_rebuild"
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if (node.module or "") == token:
                        violations.append(str(path))
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == token:
                            violations.append(str(path))
    assert not violations, "removed pending_rebuild module is still imported:\n" + "\n".join(sorted(violations))


def test_apply_orchestrator_imports_new_pending_modules_only() -> None:
    content = Path("app/modules/core_ingest/apply_orchestrator.py").read_text(encoding="utf-8")
    assert "app.modules.core_ingest.pending_rebuild" not in content
    assert "app.modules.core_ingest.pending_proposal_rebuild" in content
    assert "app.modules.core_ingest.pending_auto_link_alerts" in content


def test_pending_modules_do_not_import_review_links_alerts_service() -> None:
    pending_files = [
        Path("app/modules/core_ingest/pending_proposal_rebuild.py"),
        Path("app/modules/core_ingest/pending_auto_link_alerts.py"),
        Path("app/modules/core_ingest/pending_change_store.py"),
        Path("app/modules/core_ingest/pending_review_outbox.py"),
    ]
    violations: list[str] = []
    token = "app.modules.review_links.alerts_service"
    for path in pending_files:
        content = path.read_text(encoding="utf-8")
        if token in content:
            violations.append(str(path))
    assert not violations, "pending modules must not import review_links alerts service:\n" + "\n".join(sorted(violations))
