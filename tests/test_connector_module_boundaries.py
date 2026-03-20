from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_connector_runtime_does_not_embed_provider_fetchers() -> None:
    runtime_path = REPO_ROOT / "app" / "modules" / "runtime" / "connectors" / "connector_runtime.py"
    content = runtime_path.read_text(encoding="utf-8")
    assert "def _run_gmail_connector_fetch_only" not in content
    assert "def _run_calendar_connector_fetch_only" not in content
    assert "def _matches_gmail_source_filters" not in content
    assert "GmailClient" not in content
    assert "ICSClient" not in content


def test_fetchers_do_not_cross_import_each_other() -> None:
    gmail_path = REPO_ROOT / "app" / "modules" / "runtime" / "connectors" / "gmail_fetcher.py"
    calendar_path = REPO_ROOT / "app" / "modules" / "runtime" / "connectors" / "calendar_fetcher.py"
    gmail_content = gmail_path.read_text(encoding="utf-8")
    calendar_content = calendar_path.read_text(encoding="utf-8")
    assert "calendar_fetcher" not in gmail_content
    assert "gmail_fetcher" not in calendar_content


def test_connector_apply_has_no_provider_client_dependency() -> None:
    apply_path = REPO_ROOT / "app" / "modules" / "runtime" / "connectors" / "connector_apply.py"
    content = apply_path.read_text(encoding="utf-8")
    assert "GmailClient" not in content
    assert "ICSClient" not in content


def test_no_legacy_sync_module_imports_remain() -> None:
    roots = [
        REPO_ROOT / "app",
        REPO_ROOT / "tests",
        REPO_ROOT / "scripts",
    ]
    violations: list[str] = []
    legacy_marker = ".".join(["app", "modules", "sync"])
    for root in roots:
        for path in root.rglob("*.py"):
            content = path.read_text(encoding="utf-8")
            if legacy_marker in content and path.name != "test_connector_module_boundaries.py":
                violations.append(str(path.relative_to(REPO_ROOT)))
    assert not violations, "legacy sync module imports remain in:\n" + "\n".join(sorted(violations))
