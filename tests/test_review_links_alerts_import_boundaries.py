from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET_MODULE = "app.modules.review_links.alerts_service"


def test_removed_alerts_service_module_is_not_imported() -> None:
    violations: list[str] = []
    for scope in ("app", "services", "tests", "scripts"):
        root = REPO_ROOT / scope
        if not root.exists():
            continue
        for py_path in root.rglob("*.py"):
            if "__pycache__" in py_path.parts:
                continue
            module = ast.parse(py_path.read_text(encoding="utf-8"))
            for node in ast.walk(module):
                if isinstance(node, ast.ImportFrom) and node.module == TARGET_MODULE:
                    violations.append(f"{py_path.relative_to(REPO_ROOT)} imports {TARGET_MODULE}")
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == TARGET_MODULE:
                            violations.append(f"{py_path.relative_to(REPO_ROOT)} imports {TARGET_MODULE}")
    assert not violations, "legacy alerts_service imports found:\n" + "\n".join(sorted(violations))


def test_removed_alerts_service_file_absent() -> None:
    assert not (REPO_ROOT / "app/modules/review_links/alerts_service.py").exists()
