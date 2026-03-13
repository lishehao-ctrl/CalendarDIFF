from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from app.modules.common.payload_schemas import SourceFacts
from app.modules.core_ingest.semantic_event_service import normalize_semantic_event
from app.modules.ingestion.llm_parsers.schemas import (
    GmailAtomicSegmentExtractionResponse,
    GmailDirectiveExtractionResponse,
    GmailPlannerSegment,
)


def build_atomic_record(
    *,
    base_message_id: str,
    source_subject: str,
    source_snippet: str | None,
    source_from_header: str | None,
    source_thread_id: str | None,
    source_internal_date: str | None,
    segment: GmailPlannerSegment,
    atomic_segment_count: int,
    extraction: GmailAtomicSegmentExtractionResponse,
) -> dict:
    message_id = segment_message_id(
        base_message_id=base_message_id,
        segment_index=segment.segment_index,
        atomic_segment_count=atomic_segment_count,
    )
    semantic_event_draft = normalize_semantic_event(
        extraction.semantic_event_draft.model_dump(mode="json"),
        fallback_due_raw=source_internal_date,
    )
    due_start, due_end = due_window_from_semantic(semantic_event_draft)
    confidence = float(semantic_event_draft.get("confidence") or 0.0)
    return {
        "record_type": "gmail.message.extracted",
        "payload": {
            "message_id": message_id,
            "source_facts": SourceFacts.model_validate(
                {
                    "external_event_id": message_id,
                    "source_title": source_subject[:512] if isinstance(source_subject, str) else "Untitled",
                    "source_summary": source_snippet,
                    "source_dtstart_utc": due_start,
                    "source_dtend_utc": due_end,
                    "time_anchor_confidence": confidence,
                    "from_header": source_from_header,
                    "thread_id": source_thread_id,
                    "internal_date": source_internal_date,
                }
            ).model_dump(mode="json"),
            "semantic_event_draft": semantic_event_draft,
            "link_signals": extraction.link_signals.model_dump(),
        },
    }


def build_directive_record(
    *,
    base_message_id: str,
    source_subject: str,
    source_snippet: str | None,
    source_from_header: str | None,
    source_thread_id: str | None,
    source_internal_date: str | None,
    segment: GmailPlannerSegment,
    directive: GmailDirectiveExtractionResponse,
) -> dict:
    directive_external_event_id = directive_external_event_id_for_segment(
        base_message_id=base_message_id,
        segment_index=segment.segment_index,
    )
    return {
        "record_type": "gmail.directive.extracted",
        "payload": {
            "message_id": base_message_id,
            "source_facts": SourceFacts.model_validate(
                {
                    "external_event_id": directive_external_event_id,
                    "source_title": source_subject[:512] if isinstance(source_subject, str) else "Untitled",
                    "source_summary": segment.snippet or source_snippet,
                    "from_header": source_from_header,
                    "thread_id": source_thread_id,
                    "internal_date": source_internal_date,
                }
            ).model_dump(mode="json"),
            "segment_index": segment.segment_index,
            "segment_anchor": segment.anchor,
            "segment_snippet": segment.snippet,
            "directive": directive.model_dump(mode="json"),
        },
    }


def segment_message_id(*, base_message_id: str, segment_index: int, atomic_segment_count: int) -> str:
    if atomic_segment_count <= 1:
        return base_message_id
    return f"{base_message_id}#seg-{segment_index}"


def directive_external_event_id_for_segment(*, base_message_id: str, segment_index: int) -> str:
    return f"{base_message_id}#directive-seg-{segment_index}"


def due_window_from_semantic(semantic_parse: dict) -> tuple[str | None, str | None]:
    due_date_raw = semantic_parse.get("due_date")
    if not isinstance(due_date_raw, str) or not due_date_raw:
        return None, None
    try:
        due_date_value = date.fromisoformat(due_date_raw)
    except ValueError:
        return None, None

    due_time_raw = semantic_parse.get("due_time")
    time_precision = str(semantic_parse.get("time_precision") or "datetime")
    if time_precision == "date_only" or not isinstance(due_time_raw, str) or not due_time_raw:
        start_at = datetime(due_date_value.year, due_date_value.month, due_date_value.day, 23, 59, tzinfo=timezone.utc)
    else:
        try:
            due_time_value = time.fromisoformat(due_time_raw)
        except ValueError:
            return None, None
        start_at = datetime.combine(due_date_value, due_time_value, tzinfo=timezone.utc)

    return start_at.isoformat(), (start_at + timedelta(hours=1)).isoformat()


__all__ = [
    "build_atomic_record",
    "build_directive_record",
    "directive_external_event_id_for_segment",
    "due_window_from_semantic",
    "segment_message_id",
]
