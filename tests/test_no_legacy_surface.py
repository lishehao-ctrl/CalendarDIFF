from __future__ import annotations

from pathlib import Path

BLOCKED_TOKENS = (
    "review_candidates",
    "legacy_code",
    "source_busy",
    "source_lock_namespace",
    "source_kind",
    "before_raw_evidence_key",
    "after_raw_evidence_key",
    "/v1/inputs/{input_id}/changes/{change_id}/evidence/{side}/preview",
    "/v1/notification_prefs",
    "/v1/notifications/send_digest_now",
    "/v1/status",
    "/v1/inputs/{input_id}/deadlines",
    "/v1/inputs/{input_id}/runs",
    "/v1/inputs/{input_id}/overrides",
    'json={"route": "notify"}',
    'route="notify"',
    "/ui/runs",
    "/ui/dev",
    "/v1/dev/inject_notify",
    "/v1/user/terms",
    "POST /v1/user",
)

SCAN_ROOTS = (
    Path("app/modules"),
    Path("frontend/lib"),
    Path("frontend/app"),
    Path("frontend/components"),
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
