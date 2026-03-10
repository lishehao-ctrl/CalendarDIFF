from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

SOURCE_PRIORITY = {
    "calendar": 2,
    "email": 1,
}

MERGE_KEY_SCHEMA_TAG = "mainline"
ENTITY_UID_VERSION = "v1"
THREAD_PREFIX_PATTERN = re.compile(r"^(?:\s*(?:re|fw|fwd)\s*:\s*|\s*\[(?:update|reminder)\]\s*|\s*update\s*:\s*)+", re.I)
COURSE_TOKEN_PATTERN = re.compile(r"\b([A-Za-z]{3,5})[\s_\-]*([0-9]{1,3}[A-Za-z]?)\b")
HOMEWORK_TOKEN_PATTERN = re.compile(r"\bhomework[\s_\-]*([0-9]+)\b")
HW_TOKEN_PATTERN = re.compile(r"\bhw[\s_\-]*([0-9]+)\b")
QUIZ_TOKEN_PATTERN = re.compile(r"\bquiz[\s_\-]*([0-9]+)\b")
PROJECT_TOKEN_PATTERN = re.compile(r"\bproject[\s_\-]*([0-9]+)\b")
TOPIC_NOISE_WORDS = {"update", "updated", "move", "moved", "reminder", "fwd", "forward"}


def normalize_course_label(raw: str | None) -> str:
    text = (raw or "").strip().upper()
    if not text:
        return "UNKNOWN"
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # Normalize forms like CSE8A / CSE_8A / CSE-8A into CSE 8A.
    text = re.sub(r"([A-Z]+)\s*([0-9]+[A-Z]?)", r"\1 \2", text)
    return text[:64] or "UNKNOWN"


def normalize_topic_signature(raw_title: str | None) -> str:
    text = (raw_title or "").strip().lower()
    if not text:
        return "untitled"

    # Strip email thread prefixes repeatedly until stable.
    while True:
        stripped = THREAD_PREFIX_PATTERN.sub("", text).strip()
        if stripped == text:
            break
        text = stripped

    # Normalize due-related synonyms before tokenization.
    text = re.sub(r"\bdue\s+date\b", "deadline", text)
    text = re.sub(r"\bdue\b", "deadline", text)

    # Normalize assignment token forms.
    text = HOMEWORK_TOKEN_PATTERN.sub(lambda m: f"hw{m.group(1)}", text)
    text = HW_TOKEN_PATTERN.sub(lambda m: f"hw{m.group(1)}", text)
    text = QUIZ_TOKEN_PATTERN.sub(lambda m: f"quiz{m.group(1)}", text)
    text = PROJECT_TOKEN_PATTERN.sub(lambda m: f"project{m.group(1)}", text)

    # Remove course code tokens from topic signature: course identity is already
    # captured independently by normalize_course_label.
    text = COURSE_TOKEN_PATTERN.sub(_replace_course_token, text)

    text = re.sub(r"\[[^\]]*\]", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = [token for token in text.split() if token and token not in TOPIC_NOISE_WORDS]
    normalized = " ".join(tokens).strip()
    return normalized[:160] or "untitled"


def _replace_course_token(match: re.Match[str]) -> str:
    prefix = match.group(1).lower()
    suffix = match.group(2).lower()
    if prefix in {"hw", "quiz", "project"}:
        return f"{prefix}{suffix}"
    return " "


def normalize_time_bucket(start_at: datetime | None, end_at: datetime | None) -> str:
    baseline = start_at or end_at
    if baseline is None:
        return "no-time"
    utc_value = _as_utc(baseline)
    # Kept for diagnostics only. Merge key schema does not include date bucket.
    return utc_value.strftime("%Y-%m-%d")


def build_merge_key(
    *,
    course_label: str | None,
    title: str | None,
    start_at: datetime | None,
    end_at: datetime | None,
    event_type: str | None,
    source_kind: str | None = None,
    external_event_id: str | None = None,
    linked_entity_uid: str | None = None,
) -> str:
    if isinstance(linked_entity_uid, str) and linked_entity_uid.strip():
        return linked_entity_uid.strip()[:128]

    if isinstance(external_event_id, str) and external_event_id.strip():
        normalized_kind = (source_kind or "").strip().lower() or "unknown"
        identity = f"{normalized_kind}|{external_event_id.strip()}|{ENTITY_UID_VERSION}"
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
        return f"ent_{digest}"

    return _build_content_merge_key(
        course_label=course_label,
        title=title,
        start_at=start_at,
        end_at=end_at,
        event_type=event_type,
    )


def _build_content_merge_key(
    *,
    course_label: str | None,
    title: str | None,
    start_at: datetime | None,
    end_at: datetime | None,
    event_type: str | None,
) -> str:
    del start_at
    del end_at
    normalized_course = normalize_course_label(course_label)
    normalized_topic_signature = normalize_topic_signature(title)
    normalized_event_type = (event_type or "event").strip().lower() or "event"
    canonical = "|".join(
        [
            normalized_course,
            normalized_topic_signature,
            normalized_event_type,
            MERGE_KEY_SCHEMA_TAG,
        ]
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
    return f"mk_{digest}"


def choose_primary_observation(observations: list[dict]) -> dict | None:
    if not observations:
        return None

    def _sort_key(obs: dict) -> tuple[float, float, float, int]:
        event_payload = obs.get("event_payload")
        payload = event_payload if isinstance(event_payload, dict) else {}
        confidence = payload.get("confidence")
        if not isinstance(confidence, (int, float)):
            confidence = payload.get("raw_confidence")
        confidence_value = float(confidence) if isinstance(confidence, (int, float)) else 0.0
        observed_at = obs.get("observed_at")
        observed_rank = _as_utc(observed_at).timestamp() if isinstance(observed_at, datetime) else 0.0
        source_kind = str(obs.get("source_kind") or "").lower()
        priority = SOURCE_PRIORITY.get(source_kind, 0)
        observation_id = int(obs.get("observation_id")) if isinstance(obs.get("observation_id"), int) else 0
        return (float(priority), confidence_value, observed_rank, observation_id)

    return max(observations, key=_sort_key)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
