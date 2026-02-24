from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULES_ROOT = REPO_ROOT / "app" / "modules"


def test_router_modules_do_not_import_other_router_modules() -> None:
    violations: list[str] = []
    for router_path in MODULES_ROOT.glob("*/router.py"):
        current_module = router_path.parent.name
        tree = ast.parse(router_path.read_text(encoding="utf-8"), filename=str(router_path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            module_name = node.module or ""
            if not module_name.startswith("app.modules.") or not module_name.endswith(".router"):
                continue

            imported_module = module_name.split(".")[2]
            if imported_module != current_module:
                violations.append(
                    f"{router_path.relative_to(REPO_ROOT)}:{node.lineno} imports {module_name}"
                )

    assert not violations, "Router boundary violation(s):\n" + "\n".join(violations)


def test_cross_module_private_symbol_imports_are_forbidden() -> None:
    violations: list[str] = []
    for py_path in MODULES_ROOT.rglob("*.py"):
        tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
        relative_parts = py_path.relative_to(REPO_ROOT).parts
        current_module = relative_parts[2] if len(relative_parts) > 2 else ""

        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            module_name = node.module or ""
            if not module_name.startswith("app.modules."):
                continue

            imported_parts = module_name.split(".")
            imported_module = imported_parts[2] if len(imported_parts) > 2 else ""
            if imported_module == current_module:
                continue

            private_names = [
                alias.name for alias in node.names if alias.name.startswith("_") and alias.name != "__all__"
            ]
            if private_names:
                violations.append(
                    f"{py_path.relative_to(REPO_ROOT)}:{node.lineno} imports private symbol(s) {private_names} from {module_name}"
                )

    assert not violations, "Private cross-module import violation(s):\n" + "\n".join(violations)
