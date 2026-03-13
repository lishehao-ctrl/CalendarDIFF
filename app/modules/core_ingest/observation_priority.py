from __future__ import annotations

from datetime import datetime, timezone

SOURCE_PRIORITY = {
    "calendar": 2,
    "email": 1,
}


def choose_primary_observation(observations: list[dict]) -> dict | None:
    if not observations:
        return None

    def _sort_key(obs: dict) -> tuple[float, float, float, int]:
        event_payload = obs.get("event_payload")
        payload = event_payload if isinstance(event_payload, dict) else {}
        semantic_event = payload.get("semantic_event") if isinstance(payload.get("semantic_event"), dict) else {}
        confidence = semantic_event.get("confidence") if isinstance(semantic_event, dict) else None
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
