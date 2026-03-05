from __future__ import annotations

from pathlib import Path


def test_core_ingest_modules_do_not_import_review_alerts_service() -> None:
    violations: list[str] = []
    forbidden = "app.modules.review_links.alerts_service"
    for path in Path("app/modules/core_ingest").glob("*.py"):
        content = path.read_text(encoding="utf-8")
        if forbidden in content:
            violations.append(str(path))
    assert not violations, "core_ingest must emit alert events instead of importing alerts_service:\n" + "\n".join(violations)
