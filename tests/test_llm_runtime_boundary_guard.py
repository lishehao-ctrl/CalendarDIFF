from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _iter_python_files(*roots: Path) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        files.extend(path for path in root.rglob("*.py") if path.is_file())
    return files


def _iter_scan_targets() -> list[Path]:
    targets = [
        REPO_ROOT / "app",
        REPO_ROOT / "services",
        REPO_ROOT / "scripts",
        REPO_ROOT / "tests",
        REPO_ROOT / "docs",
        REPO_ROOT / "README.md",
        REPO_ROOT / ".env.example",
    ]
    output: list[Path] = []
    for target in targets:
        if target.is_file():
            output.append(target)
            continue
        output.extend(path for path in target.rglob("*") if path.is_file())
    return output


def test_llm_parser_call_sites_are_restricted() -> None:
    allowed_call_sites = {
        (REPO_ROOT / "app" / "modules" / "llm_runtime" / "worker.py").resolve(),
        (REPO_ROOT / "app" / "modules" / "ingestion" / "llm_parsers" / "calendar_v2.py").resolve(),
        (REPO_ROOT / "app" / "modules" / "ingestion" / "llm_parsers" / "gmail_v2.py").resolve(),
    }
    pattern = re.compile(r"\b(parse_gmail_payload|parse_calendar_content)\s*\(")
    violations: list[str] = []

    for py_file in _iter_python_files(REPO_ROOT / "app", REPO_ROOT / "services"):
        content = py_file.read_text(encoding="utf-8")
        if not pattern.search(content):
            continue
        if py_file.resolve() not in allowed_call_sites:
            violations.append(str(py_file.relative_to(REPO_ROOT)))

    assert not violations, "unexpected llm parser call site(s):\n" + "\n".join(sorted(violations))


def test_connector_runtime_does_not_import_direct_llm_parser_or_gateway() -> None:
    connector_path = REPO_ROOT / "app" / "modules" / "ingestion" / "connector_runtime.py"
    content = connector_path.read_text(encoding="utf-8")
    assert "app.modules.ingestion.llm_parsers" not in content
    assert "invoke_llm_json" not in content


def test_ingest_llm_mode_token_removed_everywhere() -> None:
    token = "INGEST_" + "LLM_EXECUTION_MODE"
    this_file = Path(__file__).resolve()
    violations: list[str] = []
    for target in _iter_scan_targets():
        if target.resolve() == this_file:
            continue
        try:
            content = target.read_text(encoding="utf-8")
        except Exception:
            continue
        if token in content:
            violations.append(str(target.relative_to(REPO_ROOT)))

    assert not violations, "ingest llm mode token residue found in:\n" + "\n".join(sorted(violations))
