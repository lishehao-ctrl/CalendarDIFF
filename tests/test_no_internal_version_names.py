from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
THIS_FILE = Path(__file__).resolve()
DISALLOWED_TOKENS: tuple[str, ...] = (
    "llm:parse:stream:v1",
    "calendar_delta_v1",
    "ics_component_fingerprints_v1",
    "orchestrator.sync_requested.v1",
    "core.ingest.apply.v1",
    "notification.review_pending_created.v1",
    "review.link_alerts.consumer.v1",
    "course_raw_type_v1",
    "SOURCE_UID_VERSION",
    "ICS_COMPONENT_FINGERPRINT_HASH_VERSION",
    ":limiter:v1",
    "merge_key",
    "proposal_merge_key",
    "event_uid",
    "item_event_uids",
)

TARGETS: tuple[Path, ...] = (
    REPO_ROOT / ".gitignore",
    REPO_ROOT / "app",
    REPO_ROOT / "services",
    REPO_ROOT / "docs",
    REPO_ROOT / "scripts",
    REPO_ROOT / "contracts",
    REPO_ROOT / "tests",
    REPO_ROOT / "data" / "synthetic" / "ddlchange_160",
    REPO_ROOT / "README.md",
    REPO_ROOT / ".env.example",
)

ALLOWED_BY_FILE: dict[str, tuple[str, ...]] = {
    "app/db/migrations/versions/20260312_0004_entity_uid_cols.py": ("event_uid",),
}

def _iter_files() -> list[Path]:
    files: list[Path] = []
    for target in TARGETS:
        if target.is_file():
            files.append(target)
            continue
        files.extend(path for path in target.rglob("*") if path.is_file())
    return files


def test_no_internal_version_names_remain() -> None:
    violations: list[str] = []

    for path in _iter_files():
        if path.resolve() == THIS_FILE:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel = str(path.relative_to(REPO_ROOT))
        for allowed in ALLOWED_BY_FILE.get(rel, ()):
            text = text.replace(allowed, "")
        for token in DISALLOWED_TOKENS:
            if token == "event_uid" and rel.startswith("data/"):
                continue
            if token in text:
                violations.append(f"{rel} contains {token}")

    assert not violations, "versioned internal names found in:\n" + "\n".join(sorted(violations))
