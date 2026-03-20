from __future__ import annotations

from pathlib import Path


def test_runtime_connector_modules_do_not_import_runtime_llm_modules() -> None:
    violations: list[str] = []
    for path in Path("app/modules/runtime/connectors").glob("*.py"):
        content = path.read_text(encoding="utf-8")
        if "app.modules.runtime.llm" in content:
            violations.append(str(path))
    assert not violations, "runtime connector modules must not import runtime llm modules:\n" + "\n".join(violations)
