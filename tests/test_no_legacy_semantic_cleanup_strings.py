from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
THIS_FILE = Path(__file__).resolve()
TARGETS: tuple[Path, ...] = (
    REPO_ROOT / "app",
    REPO_ROOT / "frontend",
    REPO_ROOT / "docs",
    REPO_ROOT / "contracts" / "openapi",
    REPO_ROOT / "scripts",
    REPO_ROOT / "tests",
)
IGNORED_PATH_PARTS = {
    ".next",
    ".next-dev",
    ".next-prod",
    "node_modules",
    "__pycache__",
}

DISALLOWED_LITERALS: tuple[str, ...] = (
    "proposal_entity_uid",
    "before_json",
    "after_json",
    "canonical_input_id",
    "materialize_change_snapshot",
    "save_ics(",
    "input_label",
    "| inputs | review-service |",
    "| events | review-service |",
    "| snapshots | review-service |",
    "| snapshot_events | review-service |",
    "canonical input bootstrap",
    "user/canonical input loading",
    "source_canonical",
    "canonical_coercion",
    "should_affect_canonical",
    "primary_source_ref_json",
    "proposal_sources_json",
    "apply_change_to_canonical_event",
    "proposal_already_matches_canonical",
)

DISALLOWED_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"from app\.db\.models\.review import .*?\bInputType\b"),
    re.compile(r"from app\.db\.models\.review import .*?\bInput\b"),
    re.compile(r"from app\.db\.models\.review import .*?(?:^|,\s)Event(?:\s*,|$)"),
    re.compile(r"from app\.db\.models\.review import .*?\bSnapshot\b"),
    re.compile(r"\bChange\.input_id\b"),
)


def _iter_files() -> list[Path]:
    files: list[Path] = []
    for target in TARGETS:
        files.extend(
            path
            for path in target.rglob("*")
            if path.is_file() and not any(part in IGNORED_PATH_PARTS for part in path.parts)
        )
    return files


def test_no_legacy_semantic_cleanup_strings_remain() -> None:
    violations: list[str] = []

    for path in _iter_files():
        if path.resolve() == THIS_FILE:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel = str(path.relative_to(REPO_ROOT))
        for literal in DISALLOWED_LITERALS:
            if literal in text:
                violations.append(f"{rel} contains {literal}")
        for pattern in DISALLOWED_PATTERNS:
            if pattern.search(text):
                violations.append(f"{rel} matches {pattern.pattern}")

    assert not violations, "legacy semantic cleanup strings found in:\n" + "\n".join(sorted(violations))
