from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = ["app", "services", "tests", "scripts"]


def test_legacy_monolith_models_module_is_removed() -> None:
    assert not (REPO_ROOT / "app" / "db" / "models.py").exists()


def test_no_imports_from_removed_app_db_models_module() -> None:
    violations: list[str] = []
    this_file = Path(__file__).resolve()
    for root_name in SCAN_ROOTS:
        root = REPO_ROOT / root_name
        for py_path in root.rglob("*.py"):
            if py_path.resolve() == this_file:
                continue
            content = py_path.read_text(encoding="utf-8")
            if "from app.db.models import" in content:
                violations.append(f"{py_path.relative_to(REPO_ROOT)} uses from app.db.models import ...")
            if "import app.db.models" in content:
                violations.append(f"{py_path.relative_to(REPO_ROOT)} uses import app.db.models")
            if "from app.db import models" in content:
                violations.append(f"{py_path.relative_to(REPO_ROOT)} uses from app.db import models")
    assert not violations, "legacy model import violation(s):\n" + "\n".join(violations)


