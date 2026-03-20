from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_KERNEL_ROOT = REPO_ROOT / "app" / "modules" / "runtime" / "kernel"


def test_runtime_kernel_does_not_depend_on_ingestion_or_llm_modules() -> None:
    violations: list[str] = []
    for py_path in RUNTIME_KERNEL_ROOT.rglob("*.py"):
        tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                if module_name.startswith("app.modules.runtime.connectors") or module_name.startswith("app.modules.runtime.llm"):
                    violations.append(f"{py_path.relative_to(REPO_ROOT)}:{node.lineno} imports {module_name}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    if name.startswith("app.modules.runtime.connectors") or name.startswith("app.modules.runtime.llm"):
                        violations.append(f"{py_path.relative_to(REPO_ROOT)}:{node.lineno} imports {name}")
    assert not violations, "runtime kernel boundary violation(s):\n" + "\n".join(violations)

