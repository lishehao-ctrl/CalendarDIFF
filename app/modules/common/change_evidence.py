from __future__ import annotations

import base64
import json
from datetime import timedelta

from app.modules.common.event_display import event_display_dict
from app.modules.common.payload_schemas import (
    FrozenChangeEvidence,
    FrozenEvidenceEvent,
    FrozenEvidenceStructuredItem,
    SourceFacts,
)
from app.modules.runtime.apply.semantic_event_service import semantic_due_datetime_from_payload


def freeze_observation_evidence(
    *,
    provider: str | None,
    event_payload: dict | None,
    semantic_payload: dict | None,
) -> FrozenChangeEvidence | None:
    if not isinstance(event_payload, dict):
        return freeze_semantic_evidence(provider=provider, semantic_payload=semantic_payload)

    source_facts_raw = event_payload.get("source_facts") if isinstance(event_payload.get("source_facts"), dict) else {}
    try:
        source_facts = SourceFacts.model_validate(source_facts_raw) if source_facts_raw else None
    except Exception:
        source_facts = None
    raw_component_b64 = event_payload.get("raw_ics_component_b64") if isinstance(event_payload.get("raw_ics_component_b64"), str) else None
    normalized_provider = (provider or "").strip().lower() or None
    if normalized_provider in {"ics", "calendar"}:
        start_at = source_facts.source_dtstart_utc if source_facts is not None else None
        end_at = source_facts.source_dtend_utc if source_facts is not None else None
        summary = source_facts.source_title if source_facts is not None else None
        description = source_facts.source_summary if source_facts is not None else None
        item = FrozenEvidenceStructuredItem(
            uid=(source_facts.external_event_id if source_facts is not None else None) or _coerce_text((semantic_payload or {}).get("uid")),
            event_display=event_display_dict(semantic_payload, strict=False) if isinstance(semantic_payload, dict) else None,
            source_title=summary,
            start_at=start_at,
            end_at=end_at,
            location=source_facts.location if source_facts is not None else None,
            description=description,
            url=None,
            sender=None,
            snippet=None,
            internal_date=None,
            thread_id=None,
        )
        event = FrozenEvidenceEvent(
            uid=item.uid,
            summary=summary,
            dtstart=start_at,
            dtend=end_at,
            location=item.location,
            description=description,
            url=None,
        )
        preview_text = _decode_raw_component(raw_component_b64) or description or summary
        return FrozenChangeEvidence(
            provider="ics",
            content_type="text/calendar",
            structured_kind="ics_event",
            structured_items=[item],
            event_count=1,
            events=[event],
            preview_text=preview_text,
        )

    if normalized_provider == "gmail":
        semantic_due = semantic_due_datetime_from_payload(semantic_payload or {}) if isinstance(semantic_payload, dict) else None
        start_at = (source_facts.source_dtstart_utc if source_facts is not None else None) or (semantic_due.isoformat() if semantic_due is not None else None)
        end_at = (source_facts.source_dtend_utc if source_facts is not None else None) or (
            (semantic_due + timedelta(hours=1)).isoformat() if semantic_due is not None else None
        )
        item = FrozenEvidenceStructuredItem(
            uid=(source_facts.external_event_id if source_facts is not None else None) or _coerce_text((semantic_payload or {}).get("uid")),
            event_display=event_display_dict(semantic_payload, strict=False) if isinstance(semantic_payload, dict) else None,
            source_title=source_facts.source_title if source_facts is not None else None,
            start_at=start_at,
            end_at=end_at,
            location=source_facts.location if source_facts is not None else None,
            description=None,
            url=None,
            sender=source_facts.from_header if source_facts is not None else None,
            snippet=source_facts.source_summary if source_facts is not None else None,
            internal_date=source_facts.internal_date if source_facts is not None else None,
            thread_id=source_facts.thread_id if source_facts is not None else None,
        )
        preview_parts = [item.source_title, item.snippet, item.sender]
        return FrozenChangeEvidence(
            provider="gmail",
            content_type="text/plain",
            structured_kind="gmail_event",
            structured_items=[item],
            event_count=0,
            events=[],
            preview_text="\n".join(part for part in preview_parts if isinstance(part, str) and part),
        )

    return freeze_semantic_evidence(provider=normalized_provider, semantic_payload=semantic_payload)


def freeze_semantic_evidence(
    *,
    provider: str | None,
    semantic_payload: dict | None,
) -> FrozenChangeEvidence | None:
    if not isinstance(semantic_payload, dict):
        return None
    due_at = semantic_due_datetime_from_payload(semantic_payload)
    item = FrozenEvidenceStructuredItem(
        uid=_coerce_text(semantic_payload.get("uid")),
        event_display=event_display_dict(semantic_payload, strict=False),
        source_title=_coerce_text(semantic_payload.get("event_name")) or _display_label(semantic_payload),
        start_at=due_at.isoformat() if due_at is not None else None,
        end_at=(due_at + timedelta(hours=1)).isoformat() if due_at is not None else None,
        location=None,
        description=None,
        url=None,
        sender=None,
        snippet=None,
        internal_date=None,
        thread_id=None,
    )
    preview_text = json.dumps(semantic_payload, ensure_ascii=True, indent=2)
    return FrozenChangeEvidence(
        provider=provider,
        content_type="application/json",
        structured_kind="generic",
        structured_items=[item],
        event_count=0,
        events=[],
        preview_text=preview_text,
    )


def _decode_raw_component(raw_component_b64: str | None) -> str | None:
    if not isinstance(raw_component_b64, str) or not raw_component_b64:
        return None
    try:
        return base64.b64decode(raw_component_b64.encode("utf-8"), validate=True).decode("utf-8", errors="replace")
    except Exception:
        return None


def _display_label(payload: dict) -> str | None:
    display = event_display_dict(payload, strict=False)
    if isinstance(display, dict):
        value = display.get("display_label")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _coerce_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


__all__ = [
    "freeze_observation_evidence",
    "freeze_semantic_evidence",
]
