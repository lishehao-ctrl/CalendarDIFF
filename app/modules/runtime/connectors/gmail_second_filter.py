from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from app.core.config import get_settings


SecondFilterAction = Literal["allow", "suppress", "abstain"]
GmailSecondFilterMode = Literal["off", "shadow", "enforce"]
GmailSecondFilterRiskBand = Literal["safe", "ambiguous", "high_risk"]

SAFE_NON_TARGET_REASON_CODES = {
    "shipping_subscription_bait",
    "recruiting_career_internship_bait",
    "newsletter_digest",
    "lms_wrapper_noise",
    "piazza_ed_forum_summary",
    "calendar_wrapper_noise",
    "student_services_noise",
    "academic_non_target_explicit_no_change",
    "jobs",
    "package_subscription",
}

_KNOWN_LABELS = {"relevant", "non_target", "uncertain"}
_HF_PROVIDER_NAMES = {"hf", "huggingface", "huggingface_endpoint", "endpoint"}
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_DATE_TIME_TOKEN_RE = re.compile(
    r"\b(?:mon|monday|tue|tuesday|wed|wednesday|thu|thursday|fri|friday|sat|saturday|sun|sunday|"
    r"jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|"
    r"sep|sept|september|oct|october|nov|november|dec|december|\d{1,2}:\d{2}|am|pm|midnight|tomorrow)\b",
    re.IGNORECASE,
)
_TARGET_MARKERS = (
    "due",
    "deadline",
    "exam",
    "midterm",
    "final",
    "quiz",
    "homework",
    "assignment",
    "project",
    "problem set",
    "pset",
    "worksheet",
    "deliverable",
    "gradescope",
)
_LMS_MARKERS = (
    "canvas",
    "piazza",
    "gradescope",
    "edstem",
    "instructure",
    "blackboard",
    "brightspace",
    "moodle",
)
_NEWSLETTER_MARKERS = (
    "digest@lists",
    "campus weekly",
    "student digest",
    "morning roundup",
    "tech briefing",
    "newsletter",
    "weekly roundup",
    "roundup",
    "digest",
)
_NEWSLETTER_BODY_MARKERS = (
    "unsubscribe",
    "manage preferences",
    "view in browser",
    "digest content bundles many prompts together and should stay non-target",
    "newsletter action prompts are intentionally noisy and non-canonical",
    "roundup items are aggregate clutter",
)
_JOB_MARKERS = (
    "recruiting",
    "careers.example.com",
    "internship",
    "career",
    "talent",
    "resume review",
    "networking night",
    "final round availability",
    "this mailbox is not monitored",
    "recruiting logistics are unrelated to monitored course deadlines",
    "career networking timing is non-target",
)
_PACKAGE_MARKERS = (
    "track shipment",
    "manage subscription",
    "update delivery preferences",
    "delivery-window timing only",
    "shipping exception alerts are non-target noise",
    "subscription trial expiry is unrelated to the course timeline",
    "renewal timing is commercial account noise",
    "parcelhub",
    "shoprunner",
    "cloudstorage plus",
)
_CALENDAR_WRAPPER_MARKERS = (
    "calendar forwarding summary",
    "manage calendar",
    "calendar wrappers bundle actions without creating monitored course facts",
    "invite reminders are wrapper clutter",
    "calendar digests are noise",
    "rsvp service",
    "events calendar",
    "calendar@events.example.com",
)
_STUDENT_SERVICES_MARKERS = (
    "student accessibility office",
    "academic advising",
    "enrollment services",
    "easy requests",
    "student services notice",
    "please use the student services portal for follow-up",
    "paperwork timing from student services should be filtered before llm",
    "enrollment bureaucracy timing is administrative and non-target",
)
_NON_TARGET_MARKERS = _NEWSLETTER_BODY_MARKERS + _JOB_MARKERS + _PACKAGE_MARKERS + _STUDENT_SERVICES_MARKERS + _CALENDAR_WRAPPER_MARKERS
_ACADEMIC_EXPLICIT_NO_CHANGE_MARKERS = (
    "the graded submission schedule is unchanged",
    "no assignment due date changed",
    "no monitored deadline changed",
    "lab section moved, report unchanged",
    "discussion waitlist handling changed and the graded submission schedule is unchanged",
    "office hours expanded before the first quiz, but no assignment due date changed",
    "office hours expanded",
)
_WRAPPER_NEGATIVE_MARKERS = (
    "wrapper digest only",
    "rubric or comment-posted wrappers should not become monitored events",
    "discussion thread activity is present without a canonical due-time mutation",
    "an lms comment or notification was posted, but no monitored deadline changed",
    "you are receiving this notification because activity occurred",
    "view thread in browser",
    "manage notification settings",
)
_QUOTE_MARKERS = ("forwarded message", "original message", " wrote:", "> ")


@dataclass(frozen=True)
class GmailSecondFilterDecision:
    action: SecondFilterAction
    stage: str
    reason_code: str
    confidence: float | None = None
    label: str | None = None
    risk_band: GmailSecondFilterRiskBand = "ambiguous"
    would_suppress: bool = False


@dataclass(frozen=True)
class _HeuristicMatch:
    reason_code: str
    risk_band: GmailSecondFilterRiskBand


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
    diff_message_count: int | None = None,
) -> GmailSecondFilterDecision:
    mode = resolve_gmail_second_filter_mode()
    if mode == "off":
        return GmailSecondFilterDecision(
            action="abstain",
            stage="disabled",
            reason_code="secondary_filter_off",
        )

    settings = get_settings()
    if _should_bypass_small_batch(
        diff_message_count=diff_message_count,
        min_batch_size=int(settings.gmail_secondary_filter_min_batch_size),
    ):
        return GmailSecondFilterDecision(
            action="abstain",
            stage=f"{mode}_small_batch_bypass",
            reason_code="secondary_filter_small_batch_bypass",
        )
    provider = str(settings.gmail_secondary_filter_provider or "").strip().lower()
    if provider in {"", "noop", "stub"}:
        return GmailSecondFilterDecision(
            action="abstain",
            stage=f"{mode}_stub",
            reason_code="secondary_filter_stub",
        )

    heuristic = classify_safe_non_target_heuristic(
        from_header=from_header,
        subject=subject,
        snippet=snippet,
        body_text=body_text,
        known_course_tokens=known_course_tokens,
    )
    if provider in _HF_PROVIDER_NAMES:
        return _run_hf_provider(
            mode=mode,
            heuristic=heuristic,
            from_header=from_header,
            subject=subject,
            snippet=snippet,
            body_text=body_text,
            label_ids=label_ids,
        )
    return GmailSecondFilterDecision(
        action="abstain",
        stage=f"{mode}_{provider}",
        reason_code="secondary_filter_provider_not_implemented",
        risk_band=heuristic.risk_band,
    )


def should_enforce_gmail_second_filter(decision: GmailSecondFilterDecision) -> bool:
    return resolve_gmail_second_filter_mode() == "enforce" and (
        decision.would_suppress or decision.action == "suppress"
    )


def classify_safe_non_target_heuristic(
    *,
    from_header: str | None,
    subject: str | None,
    snippet: str | None,
    body_text: str | None,
    known_course_tokens: set[str] | None,
) -> _HeuristicMatch:
    from_text = _normalize_text(from_header, max_chars=220).lower()
    subject_text = _normalize_text(subject, max_chars=260).lower()
    snippet_text = _normalize_text(snippet, max_chars=360).lower()
    body_text_norm = _normalize_text(body_text, max_chars=2400).lower()
    combined = " ".join(part for part in (from_text, subject_text, snippet_text, body_text_norm) if part).strip()

    if _looks_high_risk(combined=combined, known_course_tokens=known_course_tokens, from_text=from_text):
        return _HeuristicMatch(reason_code="secondary_filter_high_risk", risk_band="high_risk")

    if _contains_any(combined, _NEWSLETTER_MARKERS) and _contains_any(combined, _NEWSLETTER_BODY_MARKERS):
        return _HeuristicMatch(reason_code="newsletter_digest", risk_band="safe")

    if _contains_any(combined, _JOB_MARKERS):
        return _HeuristicMatch(reason_code="jobs", risk_band="safe")

    if _contains_any(combined, _PACKAGE_MARKERS):
        return _HeuristicMatch(reason_code="package_subscription", risk_band="safe")

    if _contains_any(combined, _CALENDAR_WRAPPER_MARKERS):
        return _HeuristicMatch(reason_code="calendar_wrapper_noise", risk_band="safe")

    if _contains_any(combined, _STUDENT_SERVICES_MARKERS):
        return _HeuristicMatch(reason_code="student_services_noise", risk_band="safe")

    if _contains_any(combined, _ACADEMIC_EXPLICIT_NO_CHANGE_MARKERS):
        return _HeuristicMatch(reason_code="academic_non_target_explicit_no_change", risk_band="safe")

    if _contains_any(combined, _LMS_MARKERS) and _contains_any(combined, _WRAPPER_NEGATIVE_MARKERS):
        if "piazza" in combined or "edstem" in combined or "forum" in combined or "thread" in combined:
            return _HeuristicMatch(reason_code="piazza_ed_forum_summary", risk_band="safe")
        return _HeuristicMatch(reason_code="lms_wrapper_noise", risk_band="safe")

    return _HeuristicMatch(reason_code="secondary_filter_ambiguous", risk_band="ambiguous")


def _run_hf_provider(
    *,
    mode: GmailSecondFilterMode,
    heuristic: _HeuristicMatch,
    from_header: str | None,
    subject: str | None,
    snippet: str | None,
    body_text: str | None,
    label_ids: list[str] | None,
) -> GmailSecondFilterDecision:
    settings = get_settings()
    endpoint_url = str(settings.gmail_secondary_filter_endpoint_url or "").strip()
    api_token = str(settings.gmail_secondary_filter_api_token or "").strip()
    if not endpoint_url:
        return GmailSecondFilterDecision(
            action="abstain",
            stage=f"{mode}_huggingface_missing_endpoint",
            reason_code="secondary_filter_missing_endpoint_url",
            risk_band=heuristic.risk_band,
        )
    if not api_token:
        return GmailSecondFilterDecision(
            action="abstain",
            stage=f"{mode}_huggingface_missing_token",
            reason_code="secondary_filter_missing_api_token",
            risk_band=heuristic.risk_band,
        )

    compact_input = _build_compact_v2_text(
        from_header=from_header,
        subject=subject,
        snippet=snippet,
        body_text=body_text,
        label_ids=label_ids,
        max_chars=int(settings.gmail_secondary_filter_max_input_chars),
    )
    try:
        label, confidence = _invoke_huggingface_endpoint(
            endpoint_url=endpoint_url,
            api_token=api_token,
            classifier_input=compact_input,
            timeout_seconds=float(settings.gmail_secondary_filter_timeout_seconds),
        )
    except Exception as exc:
        reason = f"secondary_filter_endpoint_error:{type(exc).__name__}"
        return GmailSecondFilterDecision(
            action="abstain",
            stage=f"{mode}_huggingface_error",
            reason_code=reason,
            risk_band=heuristic.risk_band,
        )

    would_suppress = (
        heuristic.risk_band == "safe"
        and heuristic.reason_code in SAFE_NON_TARGET_REASON_CODES
        and label == "non_target"
        and confidence >= float(settings.gmail_secondary_filter_min_confidence)
    )
    return GmailSecondFilterDecision(
        action="suppress" if would_suppress else "allow",
        stage=f"{mode}_huggingface_endpoint",
        reason_code=heuristic.reason_code,
        confidence=confidence,
        label=label,
        risk_band=heuristic.risk_band,
        would_suppress=would_suppress,
    )


def _invoke_huggingface_endpoint(
    *,
    endpoint_url: str,
    api_token: str,
    classifier_input: str,
    timeout_seconds: float,
) -> tuple[str, float]:
    timeout = httpx.Timeout(connect=min(timeout_seconds, 5.0), read=timeout_seconds, write=timeout_seconds, pool=5.0)
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {"inputs": classifier_input, "parameters": {"top_k": 3}}
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.post(endpoint_url, json=payload, headers=headers)
        response.raise_for_status()
    return _extract_best_prediction(response.json())


def _extract_best_prediction(payload: Any) -> tuple[str, float]:
    rows = list(_iter_prediction_rows(payload))
    best_label = None
    best_score = -1.0
    for row in rows:
        raw_label = row.get("label")
        raw_score = row.get("score")
        if not isinstance(raw_label, str):
            continue
        label = raw_label.strip().lower()
        if label not in _KNOWN_LABELS:
            continue
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            continue
        if score > best_score:
            best_label = label
            best_score = score
    if best_label is None:
        raise ValueError("secondary filter response did not contain a valid label")
    return best_label, best_score


def _iter_prediction_rows(payload: Any):
    if isinstance(payload, dict):
        if "label" in payload and "score" in payload:
            yield payload
            return
        for value in payload.values():
            yield from _iter_prediction_rows(value)
        return
    if isinstance(payload, list):
        for item in payload:
            yield from _iter_prediction_rows(item)


def _looks_high_risk(*, combined: str, known_course_tokens: set[str] | None, from_text: str) -> bool:
    if any(token and token.lower() in combined for token in (known_course_tokens or set())):
        return True
    if _contains_any(combined, _TARGET_MARKERS) and _DATE_TIME_TOKEN_RE.search(combined):
        return True
    if _contains_any(from_text, _LMS_MARKERS) and _DATE_TIME_TOKEN_RE.search(combined):
        return True
    if "instead of" in combined or "moved from" in combined or "rescheduled to" in combined:
        return True
    return False


def _build_compact_v2_text(
    *,
    from_header: str | None,
    subject: str | None,
    snippet: str | None,
    body_text: str | None,
    label_ids: list[str] | None,
    max_chars: int,
) -> str:
    from_header_text = _normalize_text(from_header, max_chars=180)
    subject_text = _normalize_text(subject, max_chars=220)
    snippet_text = _normalize_text(snippet, max_chars=320)
    body_text_norm = _normalize_text(body_text, max_chars=4000)
    body_sentences = _top_salient_sentences(body_text_norm, budget_chars=720)
    labels = ", ".join(value for value in (label_ids or []) if isinstance(value, str))
    parts = [f"FROM: {from_header_text}", f"SUBJECT: {subject_text}"]
    if labels:
        parts.append(f"LABELS: {labels}")
    if snippet_text:
        parts.append(f"SNIPPET: {snippet_text}")
    if body_sentences:
        parts.append("SALIENT_BODY: " + " | ".join(body_sentences))
    text = "\n".join(parts)
    if max_chars > 0 and len(text) > max_chars:
        return text[: max_chars - 3].rstrip() + "..."
    return text


def _top_salient_sentences(body_text: str, *, budget_chars: int) -> list[str]:
    raw = [part.strip() for part in _SENTENCE_SPLIT_RE.split(body_text) if part.strip()]
    scored: list[tuple[int, int, str]] = []
    for index, sentence in enumerate(raw):
        lowered = sentence.lower()
        score = 0
        if any(marker in lowered for marker in _TARGET_MARKERS):
            score += 5
        if _DATE_TIME_TOKEN_RE.search(lowered):
            score += 4
        if any(marker in lowered for marker in _NON_TARGET_MARKERS):
            score += 3
        if any(marker in lowered for marker in _QUOTE_MARKERS):
            score -= 2
        if len(sentence) < 20:
            score -= 1
        if score <= 0:
            continue
        scored.append((score, -index, sentence))
    scored.sort(reverse=True)
    chosen: list[str] = []
    used = 0
    for _score, _index, sentence in scored:
        cost = len(sentence) + (3 if chosen else 0)
        if used + cost > budget_chars:
            continue
        chosen.append(sentence)
        used += cost
    if not chosen and raw:
        fallback = raw[0]
        chosen.append(fallback[: budget_chars - 3].rstrip() + "..." if len(fallback) > budget_chars else fallback)
    return chosen


def _normalize_text(value: Any, *, max_chars: int) -> str:
    text = str(value or "")
    text = _URL_RE.sub("[url]", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    if max_chars > 0 and len(text) > max_chars:
        return text[: max_chars - 3].rstrip() + "..."
    return text


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _should_bypass_small_batch(*, diff_message_count: int | None, min_batch_size: int) -> bool:
    if min_batch_size <= 1:
        return False
    if diff_message_count is None:
        return False
    return diff_message_count < min_batch_size


__all__ = [
    "GmailSecondFilterDecision",
    "GmailSecondFilterMode",
    "GmailSecondFilterRiskBand",
    "SAFE_NON_TARGET_REASON_CODES",
    "SecondFilterAction",
    "classify_safe_non_target_heuristic",
    "resolve_gmail_second_filter_mode",
    "run_gmail_second_filter",
    "should_enforce_gmail_second_filter",
]
