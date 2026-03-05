from __future__ import annotations

from pathlib import Path


def test_ingestion_modules_do_not_import_llm_runtime_modules() -> None:
    violations: list[str] = []
    for path in Path("app/modules/ingestion").glob("*.py"):
        content = path.read_text(encoding="utf-8")
        if "app.modules.llm_runtime" in content:
            violations.append(str(path))
    assert not violations, "ingestion modules must not import llm_runtime modules:\n" + "\n".join(violations)
