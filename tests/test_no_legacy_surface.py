from __future__ import annotations

from pathlib import Path

BLOCKED_TOKENS = (
    "review_candidates",
    "legacy_code",
    "source_busy",
    "/v1/user/terms",
    "POST /v1/user",
)

SCAN_ROOTS = (
    Path("app/modules"),
    Path("frontend/lib"),
)


def test_no_legacy_surface_tokens_in_runtime_code() -> None:
    violations: list[str] = []

    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in {".py", ".ts", ".tsx"}:
                continue

            text = path.read_text(encoding="utf-8")
            for line_no, line in enumerate(text.splitlines(), start=1):
                for token in BLOCKED_TOKENS:
                    if token in line:
                        violations.append(f"{path}:{line_no}: contains blocked token '{token}'")

    assert not violations, "\n" + "\n".join(violations)
