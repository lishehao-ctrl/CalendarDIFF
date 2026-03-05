from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LEGACY_TOKEN = "v" + "2"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/" + LEGACY_TOKEN + "/auth"
GOOGLE_AUTH_SEGMENT = "oauth2/" + LEGACY_TOKEN

TARGETS: tuple[Path, ...] = (
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
    ".env.example": (GOOGLE_AUTH_URL,),
    "app/core/config.py": (GOOGLE_AUTH_URL,),
    "docs/architecture.md": (GOOGLE_AUTH_SEGMENT,),
    "tests/test_gmail_client_endpoint_overrides.py": (GOOGLE_AUTH_URL,),
}


def _iter_files() -> list[Path]:
    files: list[Path] = []
    for target in TARGETS:
        if target.is_file():
            files.append(target)
            continue
        files.extend(path for path in target.rglob("*") if path.is_file())
    return files


def test_no_legacy_version_token_residue() -> None:
    violations: list[str] = []

    for path in _iter_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel = str(path.relative_to(REPO_ROOT))
        for allowed in ALLOWED_BY_FILE.get(rel, ()):
            text = text.replace(allowed, "")
        if LEGACY_TOKEN in text:
            violations.append(rel)

    assert not violations, "legacy version token residue found in:\n" + "\n".join(sorted(violations))
