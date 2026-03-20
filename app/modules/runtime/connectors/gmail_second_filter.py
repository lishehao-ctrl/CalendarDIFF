from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.core.config import get_settings


SecondFilterAction = Literal["allow", "suppress", "abstain"]
GmailSecondFilterMode = Literal["off", "shadow", "enforce"]


@dataclass(frozen=True)
class GmailSecondFilterDecision:
    action: SecondFilterAction
    stage: str
    reason_code: str
    confidence: float | None = None
    label: str | None = None


def resolve_gmail_second_filter_mode() -> GmailSecondFilterMode:
    settings = get_settings()
    raw = str(settings.gmail_secondary_filter_mode or "").strip().lower()
    if raw in {"", "off", "disabled", "none"}:
        return "off"
    if raw in {"shadow", "shadow_only", "observe"}:
        return "shadow"
    if raw in {"enforce", "active"}:
        return "enforce"
    return "off"


def run_gmail_second_filter(
    *,
    from_header: str | None,
    subject: str | None,
    snippet: str | None,
    body_text: str | None,
    label_ids: list[str] | None,
    known_course_tokens: set[str] | None,
) -> GmailSecondFilterDecision:
    del from_header, subject, snippet, body_text, label_ids, known_course_tokens
    mode = resolve_gmail_second_filter_mode()
    if mode == "off":
        return GmailSecondFilterDecision(
            action="abstain",
            stage="disabled",
            reason_code="secondary_filter_off",
            confidence=None,
            label=None,
        )

    settings = get_settings()
    provider = str(settings.gmail_secondary_filter_provider or "").strip().lower()
    if provider in {"", "noop", "stub"}:
        return GmailSecondFilterDecision(
            action="abstain",
            stage=f"{mode}_stub",
            reason_code="secondary_filter_stub",
            confidence=None,
            label=None,
        )

    return GmailSecondFilterDecision(
        action="abstain",
        stage=f"{mode}_{provider}",
        reason_code="secondary_filter_provider_not_implemented",
        confidence=None,
        label=None,
    )


def should_enforce_gmail_second_filter(decision: GmailSecondFilterDecision) -> bool:
    return resolve_gmail_second_filter_mode() == "enforce" and decision.action == "suppress"


__all__ = [
    "GmailSecondFilterDecision",
    "GmailSecondFilterMode",
    "SecondFilterAction",
    "resolve_gmail_second_filter_mode",
    "run_gmail_second_filter",
    "should_enforce_gmail_second_filter",
]
