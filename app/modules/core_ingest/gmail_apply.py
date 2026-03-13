from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.input import InputSource, SourceKind
from app.db.models.review import Change, ChangeType, EventEntity, EventEntityLifecycle, EventLinkOrigin
from app.modules.common.family_labels import load_latest_family_labels, require_latest_family_label
from app.modules.common.semantic_codec import (
    approved_entity_to_semantic_payload,
    parse_semantic_payload,
    semantic_delta_seconds,
    semantic_payloads_equivalent,
)
from app.modules.core_ingest.semantic_event_service import build_semantic_event_payload
from app.modules.core_ingest.linking_engine import (
    find_existing_entity_link,
    link_gmail_observation_to_entity,
    resolve_pending_link_candidates_for_pair,
    upsert_event_entity_link,
    upsert_link_candidate,
    with_candidate_evidence,
)
from app.modules.core_ingest.observation_store import (
    retire_active_observation_for_unresolved_transition,
    upsert_observation,
)
from app.modules.core_ingest.unresolved_store import (
    resolve_active_unresolved_records,
    upsert_active_unresolved_record,
)
from app.modules.core_ingest.payload_contracts import (
    PayloadContractError,
    validate_gmail_directive_payload,
    validate_gmail_payload,
)
from app.modules.core_ingest.payload_extractors import (
    extract_course_parse,
    extract_link_signals,
    extract_semantic_event_draft,
    extract_source_facts_from_gmail_payload,
)
from app.modules.core_ingest.course_work_item_family_resolution import build_source_scoped_entity_uid, resolve_kind_resolution
from app.modules.core_ingest.pending_change_store import upsert_pending_change
from app.modules.core_ingest.pending_review_outbox import emit_review_pending_created_event
from app.modules.core_ingest.review_evidence import freeze_semantic_evidence

logger = logging.getLogger(__name__)

_WEEKDAY_TO_INDEX = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


@dataclass(frozen=True)
class GmailApplyOutcome:
    affected_entity_uids: set[str]
    directive_changes_created: int


def apply_gmail_observations(
    *,
    db: Session,
    source: InputSource,
    records: list[dict],
    applied_at: datetime,
    request_id: str,
) -> GmailApplyOutcome:
    affected_entity_uids: set[str] = set()
    directive_created_changes: list[Change] = []

    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        record_type = record.get("record_type")
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        if record_type == "gmail.message.extracted":
            changed_uids = _apply_gmail_atomic_record(
                db=db,
                source=source,
                payload=payload,
                record_index=index,
                applied_at=applied_at,
                request_id=request_id,
            )
            affected_entity_uids.update(changed_uids)
            continue
        if record_type == "gmail.directive.extracted":
            created_changes = _apply_gmail_directive_record(
                db=db,
                source=source,
                payload=payload,
                record_index=index,
                applied_at=applied_at,
                request_id=request_id,
            )
            directive_created_changes.extend(created_changes)

    if directive_created_changes:
        db.flush()
        emit_review_pending_created_event(
            db=db,
            user_id=source.user_id,
            changes=directive_created_changes,
            detected_at=applied_at,
        )

    return GmailApplyOutcome(
        affected_entity_uids=affected_entity_uids,
        directive_changes_created=len(directive_created_changes),
    )


def _apply_gmail_atomic_record(
    *,
    db: Session,
    source: InputSource,
    payload: dict,
    record_index: int,
    applied_at: datetime,
    request_id: str,
) -> set[str]:
    try:
        validate_gmail_payload(payload=payload, record_index=record_index)
    except PayloadContractError as exc:
        raise RuntimeError(str(exc)) from exc

    message_id = payload.get("message_id")
    if not isinstance(message_id, str) or not message_id.strip():
        return set()
    external_event_id = message_id.strip()
    source_facts = extract_source_facts_from_gmail_payload(payload=payload)

    course_parse = extract_course_parse(payload=payload, source_facts=source_facts)
    semantic_draft = extract_semantic_event_draft(payload=payload, source_facts=source_facts)
    link_signals = extract_link_signals(
        payload=payload,
        source_facts=source_facts,
    )
    kind_resolution = resolve_kind_resolution(
        db,
        user_id=source.user_id,
        course_parse=course_parse,
        semantic_parse=semantic_draft,
        source_facts=source_facts,
        source_kind=SourceKind.EMAIL.value,
        external_event_id=external_event_id,
        source_id=source.id,
        request_id=request_id,
        provider=source.provider,
    )
    if kind_resolution.get("status") == "unresolved":
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
            reason_code=str(kind_resolution.get("reason_code") or "missing_course_identity"),
            source_facts_json=source_facts,
            semantic_event_draft_json=semantic_draft,
            kind_resolution_json=kind_resolution,
            raw_payload_json=payload,
        )
        return set()

    existing_link = find_existing_entity_link(
        db=db,
        user_id=source.user_id,
        source_id=source.id,
        external_event_id=external_event_id,
    )
    should_emit_semantic_proposal = False
    if existing_link is not None and existing_link.link_origin != EventLinkOrigin.AUTO and isinstance(existing_link.entity_uid, str):
        entity_uid = existing_link.entity_uid
        should_emit_semantic_proposal = True
    else:
        link_decision = link_gmail_observation_to_entity(
            db=db,
            source=source,
            external_event_id=external_event_id,
            course_parse=course_parse,
            semantic_parse=semantic_draft,
            time_anchor_confidence=float(link_signals.get("time_anchor_confidence") or 0.0),
            signals=link_signals,
        )
        if link_decision.status == "linked" and isinstance(link_decision.entity_uid, str):
            entity_uid = link_decision.entity_uid
            upsert_event_entity_link(
                db=db,
                source=source,
                external_event_id=external_event_id,
                entity_uid=entity_uid,
                link_origin=EventLinkOrigin.AUTO,
                link_score=float(link_decision.score),
                signals_json=link_signals,
            )
            should_emit_semantic_proposal = True
            resolve_pending_link_candidates_for_pair(
                db=db,
                user_id=source.user_id,
                source_id=source.id,
                external_event_id=external_event_id,
                note="semantic_link_resolved",
            )
        else:
            rule_reason = str(link_decision.score_breakdown.get("rule_reason") or "")
            candidate_can_emit_semantic_proposal = (
                link_decision.status == "candidate"
                and rule_reason in {"no_rule_match", "missing_raw_type"}
                and isinstance(kind_resolution.get("family_id"), int)
            )
            entity_uid = (
                existing_link.entity_uid
                if existing_link is not None and isinstance(existing_link.entity_uid, str)
                else build_source_scoped_entity_uid(source_kind=SourceKind.EMAIL.value, external_event_id=external_event_id)
            )
            should_emit_semantic_proposal = candidate_can_emit_semantic_proposal
            if link_decision.status == "candidate" and not candidate_can_emit_semantic_proposal:
                upsert_link_candidate(
                    db=db,
                    user_id=source.user_id,
                    source_id=source.id,
                    external_event_id=external_event_id,
                    proposed_entity_uid=link_decision.candidate_entity_uid,
                    score=float(link_decision.score),
                    score_breakdown=with_candidate_evidence(score_breakdown=link_decision.score_breakdown, signals=link_signals),
                    reason_code=str(link_decision.reason_code or "score_band"),
                )

    semantic_event = build_semantic_event_payload(
        semantic_draft=semantic_draft,
        source_facts=source_facts,
        family_id=kind_resolution.get("family_id") if isinstance(kind_resolution.get("family_id"), int) else None,
        family_name=kind_resolution.get("canonical_label") if isinstance(kind_resolution.get("canonical_label"), str) else None,
        raw_type=kind_resolution.get("raw_type") if isinstance(kind_resolution.get("raw_type"), str) else None,
        entity_uid=entity_uid,
    )
    semantic_event["uid"] = entity_uid
    logger.debug(
        "core_ingest.observation.gmail request_id=%s source_id=%s entity_uid=%s external_event_id=%s resolution=%s",
        request_id,
        source.id,
        entity_uid,
        external_event_id,
        kind_resolution.get("status"),
    )
    observation_payload = {
        "kind_resolution": kind_resolution,
        "source_facts": source_facts,
        "semantic_event": semantic_event,
        "link_signals": link_signals,
    }

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
    return changed_entity_uids if should_emit_semantic_proposal else set()


def _apply_gmail_directive_record(
    *,
    db: Session,
    source: InputSource,
    payload: dict,
    record_index: int,
    applied_at: datetime,
    request_id: str,
) -> list[Change]:
    try:
        validate_gmail_directive_payload(payload=payload, record_index=record_index)
    except PayloadContractError as exc:
        raise RuntimeError(str(exc)) from exc

    source_facts = payload.get("source_facts") if isinstance(payload.get("source_facts"), dict) else {}
    external_event_id = source_facts.get("external_event_id") if isinstance(source_facts.get("external_event_id"), str) else None
    if not isinstance(external_event_id, str) or not external_event_id.strip():
        message_id = payload.get("message_id") if isinstance(payload.get("message_id"), str) else "directive"
        external_event_id = f"{message_id.strip()}#directive"
    external_event_id = external_event_id.strip()

    directive = payload.get("directive") if isinstance(payload.get("directive"), dict) else {}
    selector = directive.get("selector") if isinstance(directive.get("selector"), dict) else {}
    mutation = directive.get("mutation") if isinstance(directive.get("mutation"), dict) else {}
    confidence_raw = directive.get("confidence")
    confidence = float(confidence_raw) if isinstance(confidence_raw, (int, float)) else 0.0

    selector_dept = selector.get("course_dept")
    selector_number = selector.get("course_number")
    if not isinstance(selector_dept, str) or not selector_dept.strip() or not isinstance(selector_number, int):
        _isolate_directive_record(
            db=db,
            source=source,
            external_event_id=external_event_id,
            request_id=request_id,
            reason_code="directive_missing_selector_identity",
            source_facts=source_facts,
            payload=payload,
        )
        return []

    query = (
        select(EventEntity)
        .where(
            EventEntity.user_id == source.user_id,
            EventEntity.lifecycle == EventEntityLifecycle.ACTIVE,
            EventEntity.course_dept == selector_dept.strip().upper(),
            EventEntity.course_number == selector_number,
        )
        .order_by(EventEntity.entity_uid.asc())
    )
    if isinstance(selector.get("course_suffix"), str) and selector.get("course_suffix").strip():
        query = query.where(EventEntity.course_suffix == selector.get("course_suffix").strip().upper())
    if isinstance(selector.get("course_quarter"), str) and selector.get("course_quarter").strip():
        query = query.where(EventEntity.course_quarter == selector.get("course_quarter").strip().upper())
    if isinstance(selector.get("course_year2"), int):
        query = query.where(EventEntity.course_year2 == selector.get("course_year2"))
    candidates = list(db.scalars(query).all())

    family_labels = load_latest_family_labels(
        db,
        user_id=source.user_id,
        family_ids=[entity.family_id for entity in candidates],
    )
    matched_entities = [
        entity
        for entity in candidates
        if _entity_matches_directive_selector(
            entity=entity,
            selector=selector,
            latest_family_labels=family_labels,
            applied_at=applied_at,
        )
    ]
    if not matched_entities:
        _isolate_directive_record(
            db=db,
            source=source,
            external_event_id=external_event_id,
            request_id=request_id,
            reason_code="directive_no_match",
            source_facts=source_facts,
            payload=payload,
        )
        return []

    created_changes: list[Change] = []
    candidate_count = 0
    source_refs = [
        {
            "source_id": source.id,
            "source_kind": source.source_kind.value,
            "provider": source.provider,
            "external_event_id": external_event_id,
            "confidence": confidence,
        }
    ]
    for entity in matched_entities:
        family_name = require_latest_family_label(
            family_id=entity.family_id,
            latest_family_labels=family_labels,
            context=f"gmail.directive entity_uid={entity.entity_uid}",
        )
        before_payload = approved_entity_to_semantic_payload(
            entity,
            family_name_override=family_name,
        )
        after_payload = _apply_directive_mutation(
            before_payload=before_payload,
            mutation=mutation,
        )
        if after_payload is None:
            continue
        if semantic_payloads_equivalent(before_payload, after_payload):
            continue
        candidate_count += 1
        if parse_semantic_payload(entity.entity_uid, after_payload) is None:
            raise RuntimeError(
                f"core_ingest_integrity_error: directive generated invalid semantic payload entity_uid={entity.entity_uid}"
            )
        before_evidence = freeze_semantic_evidence(provider=source.provider, semantic_payload=before_payload)
        after_evidence = freeze_semantic_evidence(provider=source.provider, semantic_payload=after_payload)
        new_change = upsert_pending_change(
            db=db,
            user_id=source.user_id,
            entity_uid=entity.entity_uid,
            change_type=ChangeType.DUE_CHANGED,
            before_semantic_json=before_payload,
            after_semantic_json=after_payload,
            delta_seconds=semantic_delta_seconds(before_payload=before_payload, after_payload=after_payload),
            source_refs=source_refs,
            detected_at=applied_at,
            before_evidence_json=before_evidence.model_dump(mode="json") if before_evidence is not None else None,
            after_evidence_json=after_evidence.model_dump(mode="json") if after_evidence is not None else None,
        )
        if new_change is not None:
            created_changes.append(new_change)

    if candidate_count == 0:
        _isolate_directive_record(
            db=db,
            source=source,
            external_event_id=external_event_id,
            request_id=request_id,
            reason_code="directive_unsupported_or_no_effect",
            source_facts=source_facts,
            payload=payload,
        )
        return []

    resolve_active_unresolved_records(
        db=db,
        user_id=source.user_id,
        source_id=source.id,
        external_event_id=external_event_id,
        resolved_at=applied_at,
    )
    return created_changes


def _entity_matches_directive_selector(
    *,
    entity: EventEntity,
    selector: dict,
    latest_family_labels: dict[int, str],
    applied_at: datetime,
) -> bool:
    raw_type_hint = selector.get("raw_type_hint")
    if isinstance(raw_type_hint, str) and raw_type_hint.strip():
        if not isinstance(entity.raw_type, str) or entity.raw_type.strip().lower() != raw_type_hint.strip().lower():
            return False

    family_hint = selector.get("family_hint")
    if isinstance(family_hint, str) and family_hint.strip():
        family_name = require_latest_family_label(
            family_id=entity.family_id,
            latest_family_labels=latest_family_labels,
            context=f"gmail.directive.family_hint entity_uid={entity.entity_uid}",
        )
        if family_name.strip().lower() != family_hint.strip().lower():
            return False

    scope_mode = selector.get("scope_mode") if isinstance(selector.get("scope_mode"), str) else "all_matching"
    if scope_mode == "ordinal_list":
        if not isinstance(entity.ordinal, int):
            return False
        raw_ordinals = selector.get("ordinal_list")
        if not isinstance(raw_ordinals, list):
            return False
        ordinal_values = {value for value in raw_ordinals if isinstance(value, int)}
        if entity.ordinal not in ordinal_values:
            return False
    elif scope_mode == "ordinal_range":
        if not isinstance(entity.ordinal, int):
            return False
        start = selector.get("ordinal_range_start")
        end = selector.get("ordinal_range_end")
        if not isinstance(start, int) or not isinstance(end, int):
            return False
        if entity.ordinal < start or entity.ordinal > end:
            return False

    current_due_weekday = selector.get("current_due_weekday")
    if isinstance(current_due_weekday, str) and current_due_weekday.strip():
        weekday_index = _WEEKDAY_TO_INDEX.get(current_due_weekday.strip().lower())
        if weekday_index is None:
            return False
        if not isinstance(entity.due_date, date) or entity.due_date.weekday() != weekday_index:
            return False

    if bool(selector.get("applies_to_future_only")):
        due_at = _entity_due_datetime(entity)
        if due_at is None or due_at <= applied_at:
            return False

    return True


def _apply_directive_mutation(*, before_payload: dict, mutation: dict) -> dict | None:
    if not isinstance(before_payload.get("due_date"), str):
        return None

    move_weekday = mutation.get("move_weekday")
    set_due_date = mutation.get("set_due_date")

    if isinstance(move_weekday, str) and move_weekday.strip():
        weekday_index = _WEEKDAY_TO_INDEX.get(move_weekday.strip().lower())
        if weekday_index is None:
            return None
        current_due_date = _parse_iso_date(before_payload.get("due_date"))
        if current_due_date is None:
            return None
        delta_days = (weekday_index - current_due_date.weekday()) % 7
        if delta_days == 0:
            delta_days = 7
        next_due_date = current_due_date + timedelta(days=delta_days)
        after_payload = dict(before_payload)
        after_payload["due_date"] = next_due_date.isoformat()
        if str(after_payload.get("time_precision") or "datetime") == "date_only":
            after_payload["due_time"] = None
        return after_payload

    parsed_set_due_date = _parse_iso_date(set_due_date)
    if parsed_set_due_date is None:
        return None
    after_payload = dict(before_payload)
    after_payload["due_date"] = parsed_set_due_date.isoformat()
    if str(after_payload.get("time_precision") or "datetime") == "date_only":
        after_payload["due_time"] = None
    return after_payload


def _parse_iso_date(raw: object) -> date | None:
    if isinstance(raw, date):
        return raw
    if not isinstance(raw, str):
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    try:
        return date.fromisoformat(cleaned)
    except ValueError:
        return None


def _entity_due_datetime(entity: EventEntity) -> datetime | None:
    if not isinstance(entity.due_date, date):
        return None
    if str(entity.time_precision or "datetime") == "date_only" or not isinstance(entity.due_time, time):
        return datetime(entity.due_date.year, entity.due_date.month, entity.due_date.day, 23, 59, tzinfo=timezone.utc)
    return datetime.combine(entity.due_date, entity.due_time, tzinfo=timezone.utc)


def _isolate_directive_record(
    *,
    db: Session,
    source: InputSource,
    external_event_id: str,
    request_id: str,
    reason_code: str,
    source_facts: dict,
    payload: dict,
) -> None:
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
        semantic_event_draft_json=None,
        kind_resolution_json={
            "status": "directive_isolated",
            "reason_code": reason_code,
        },
        raw_payload_json=payload,
    )


__all__ = ["GmailApplyOutcome", "apply_gmail_observations"]
