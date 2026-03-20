from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_sources_service_monolith_removed() -> None:
    service_path = REPO_ROOT / "app" / "modules" / "sources" / "service.py"
    assert not service_path.exists()


def test_no_call_site_imports_sources_service_shell() -> None:
    forbidden = "app.modules.sources" + ".service"
    scan_roots = [
        REPO_ROOT / "app",
        REPO_ROOT / "services",
        REPO_ROOT / "tests",
        REPO_ROOT / "scripts",
    ]
    violations: list[str] = []
    for root in scan_roots:
        for path in root.rglob("*.py"):
            content = path.read_text(encoding="utf-8")
            if forbidden in content:
                violations.append(str(path.relative_to(REPO_ROOT)))

    assert not violations, "legacy sources service shell import found:\n" + "\n".join(sorted(violations))
