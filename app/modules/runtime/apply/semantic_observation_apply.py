from __future__ import annotations

from datetime import datetime

from app.db.models.input import InputSource, SourceKind
from app.modules.common.source_monitoring_window import (
    parse_iso_datetime,
    parse_source_monitoring_window,
    semantic_due_date_in_window,
    source_timezone_name,
)
from app.modules.families.resolution_service import resolve_kind_resolution
from app.modules.runtime.apply.entity_resolution import resolve_entity_uid
from app.modules.runtime.apply.observation_store import retire_active_observation_for_unresolved_transition, upsert_observation
from app.modules.runtime.apply.product_scope import is_monitored_assignment_or_exam_event
from app.modules.runtime.apply.semantic_event_service import build_semantic_event_payload
from app.modules.runtime.apply.unresolved_store import resolve_active_unresolved_records, upsert_active_unresolved_record


def apply_semantic_observation_candidate(
    *,
    db,
    source: InputSource,
    external_event_id: str,
    source_facts: dict,
    semantic_draft: dict,
    course_parse: dict,
    link_signals: dict,
    raw_payload: dict,
    applied_at: datetime,
    request_id: str,
    source_kind_value: str,
    raw_ics_component_b64: str | None = None,
) -> set[str]:
    term_window = parse_source_monitoring_window(source, required=False)
    if term_window is not None and not semantic_due_date_in_window(
        semantic_payload=semantic_draft,
        fallback_datetime=_fallback_datetime_for_source_kind(
            source_kind_value=source_kind_value,
            source_facts=source_facts,
        ),
        monitoring_window=term_window,
        timezone_name=source_timezone_name(source),
    ):
        _move_to_unresolved(
            db=db,
            source=source,
            external_event_id=external_event_id,
            applied_at=applied_at,
            request_id=request_id,
            reason_code="monitoring_window_out_of_scope",
            source_facts=source_facts,
            semantic_draft=semantic_draft,
            kind_resolution=None,
            raw_payload=raw_payload,
        )
        return set()

    if not is_monitored_assignment_or_exam_event(
        semantic_draft=semantic_draft,
        source_facts=source_facts,
    ):
        _move_to_unresolved(
            db=db,
            source=source,
            external_event_id=external_event_id,
            applied_at=applied_at,
            request_id=request_id,
            reason_code="product_scope_excluded",
            source_facts=source_facts,
            semantic_draft=semantic_draft,
            kind_resolution=None,
            raw_payload=raw_payload,
        )
        return set()

    kind_resolution = resolve_kind_resolution(
        db,
        user_id=source.user_id,
        course_parse=course_parse,
        semantic_parse=semantic_draft,
        source_facts=source_facts,
        source_kind=source_kind_value,
        external_event_id=external_event_id,
        source_id=source.id,
        request_id=request_id,
        provider=source.provider,
    )
    if kind_resolution.get("status") == "unresolved":
        _move_to_unresolved(
            db=db,
            source=source,
            external_event_id=external_event_id,
            applied_at=applied_at,
            request_id=request_id,
            reason_code=str(kind_resolution.get("reason_code") or "missing_course_identity"),
            source_facts=source_facts,
            semantic_draft=semantic_draft,
            kind_resolution=kind_resolution,
            raw_payload=raw_payload,
        )
        return set()

    entity_resolution = resolve_entity_uid(
        db=db,
        source=source,
        external_event_id=external_event_id,
        course_parse=course_parse,
        kind_resolution=kind_resolution,
    )
    if entity_resolution.status != "resolved" or not isinstance(entity_resolution.entity_uid, str):
        _move_to_unresolved(
            db=db,
            source=source,
            external_event_id=external_event_id,
            applied_at=applied_at,
            request_id=request_id,
            reason_code=str(entity_resolution.reason_code or "insufficient_entity_resolution"),
            source_facts=source_facts,
            semantic_draft=semantic_draft,
            kind_resolution=kind_resolution,
            raw_payload=raw_payload,
        )
        return set()

    entity_uid = entity_resolution.entity_uid
    semantic_event = build_semantic_event_payload(
        semantic_draft=semantic_draft,
        source_facts=source_facts,
        family_id=kind_resolution.get("family_id") if isinstance(kind_resolution.get("family_id"), int) else None,
        family_name=kind_resolution.get("canonical_label") if isinstance(kind_resolution.get("canonical_label"), str) else None,
        raw_type=kind_resolution.get("raw_type") if isinstance(kind_resolution.get("raw_type"), str) else None,
        entity_uid=entity_uid,
    )
    semantic_event["uid"] = entity_uid
    observation_payload = {
        "kind_resolution": kind_resolution,
        "source_facts": source_facts,
        "semantic_event": semantic_event,
        "link_signals": link_signals,
    }
    if isinstance(raw_ics_component_b64, str) and raw_ics_component_b64:
        observation_payload["raw_ics_component_b64"] = raw_ics_component_b64

    changed_entity_uids = upsert_observation(
        db=db,
        source=source,
        external_event_id=external_event_id,
        entity_uid=entity_uid,
        event_payload=observation_payload,
        applied_at=applied_at,
        request_id=request_id,
    )
    resolve_active_unresolved_records(
        db=db,
        user_id=source.user_id,
        source_id=source.id,
        external_event_id=external_event_id,
        resolved_at=applied_at,
    )
    return changed_entity_uids


def _move_to_unresolved(
    *,
    db,
    source: InputSource,
    external_event_id: str,
    applied_at: datetime,
    request_id: str,
    reason_code: str,
    source_facts: dict,
    semantic_draft: dict,
    kind_resolution: dict | None,
    raw_payload: dict,
) -> None:
    retire_active_observation_for_unresolved_transition(
        db=db,
        source_id=source.id,
        external_event_id=external_event_id,
        applied_at=applied_at,
        request_id=request_id,
    )
    upsert_active_unresolved_record(
        db=db,
        user_id=source.user_id,
        source_id=source.id,
        source_kind=source.source_kind,
        provider=source.provider,
        external_event_id=external_event_id,
        request_id=request_id,
        reason_code=reason_code,
        source_facts_json=source_facts,
        semantic_event_draft_json=semantic_draft,
        kind_resolution_json=kind_resolution,
        raw_payload_json=raw_payload,
    )


def _fallback_datetime_for_source_kind(*, source_kind_value: str, source_facts: dict):
    if source_kind_value == SourceKind.CALENDAR.value:
        return parse_iso_datetime(source_facts.get("source_dtstart_utc"))
    return parse_iso_datetime(source_facts.get("internal_date"))


__all__ = ["apply_semantic_observation_candidate"]
