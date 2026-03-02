from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

SOURCE_PRIORITY = {
    "calendar": 2,
    "email": 1,
}

NOISE_PREFIXES = (
    "re:",
    "fw:",
    "fwd:",
    "[reminder]",
    "[update]",
    "update:",
)


def normalize_course_label(raw: str | None) -> str:
    text = (raw or "").strip().upper()
    if not text:
        return "UNKNOWN"
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # Normalize forms like CSE8A / CSE_8A into CSE 8A.
    text = re.sub(r"([A-Z]+)\s*([0-9]+[A-Z]?)", r"\1 \2", text)
    return text[:64] or "UNKNOWN"


def normalize_title(raw: str | None) -> str:
    text = (raw or "").strip().lower()
    for prefix in NOISE_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
    text = re.sub(r"\[[^\]]*\]", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:160] or "untitled"


def normalize_time_bucket(start_at: datetime | None, end_at: datetime | None) -> str:
    baseline = start_at or end_at
    if baseline is None:
        return "no-time"
    utc_value = _as_utc(baseline)
    # Day-level bucket keeps \"due changed\" updates stable within a day while
    # still separating unrelated events on different dates.
    return utc_value.strftime("%Y-%m-%d")


def build_merge_key(
    *,
    course_label: str | None,
    title: str | None,
    start_at: datetime | None,
    end_at: datetime | None,
    event_type: str | None,
) -> str:
    normalized_course = normalize_course_label(course_label)
    normalized_title = normalize_title(title)
    normalized_time_bucket = normalize_time_bucket(start_at, end_at)
    normalized_event_type = (event_type or "event").strip().lower() or "event"
    canonical = "|".join(
        [
            normalized_course,
            normalized_title,
            normalized_time_bucket,
            normalized_event_type,
        ]
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
    return f"mk_{digest}"


def choose_primary_observation(observations: list[dict]) -> dict | None:
    if not observations:
        return None

    def _sort_key(obs: dict) -> tuple[float, int]:
        payload = obs.get("event_payload") if isinstance(obs.get("event_payload"), dict) else {}
        confidence = payload.get("confidence")
        if not isinstance(confidence, (int, float)):
            confidence = payload.get("raw_confidence")
        confidence_value = float(confidence) if isinstance(confidence, (int, float)) else 0.0
        source_kind = str(obs.get("source_kind") or "").lower()
        priority = SOURCE_PRIORITY.get(source_kind, 0)
        return (confidence_value, priority)

    return max(observations, key=_sort_key)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
