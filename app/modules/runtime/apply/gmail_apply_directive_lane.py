from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models.input import InputSource
from app.db.models.review import Change, ChangeType
from app.modules.common.family_labels import load_latest_family_labels, require_latest_family_label
from app.modules.common.source_term_window import parse_source_term_window, semantic_due_date_in_window, source_timezone_name
from app.modules.common.semantic_codec import (
    approved_entity_to_semantic_payload,
    parse_semantic_payload,
    semantic_delta_seconds,
    semantic_payloads_equivalent,
)
from app.modules.runtime.apply.gmail_directive_isolation import isolate_directive_record
from app.modules.runtime.apply.gmail_directive_mutation import apply_directive_mutation
from app.modules.runtime.apply.gmail_directive_selector import entity_matches_directive_selector, load_directive_candidates
from app.modules.runtime.apply.payload_contracts import PayloadContractError, validate_gmail_directive_payload
from app.modules.runtime.apply.pending_change_store import upsert_pending_change
from app.modules.runtime.apply.product_scope import is_monitored_assignment_or_exam_directive
from app.modules.runtime.apply.change_evidence import freeze_semantic_evidence
from app.modules.runtime.apply.unresolved_store import resolve_active_unresolved_records


def apply_gmail_directive_record(
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

    if not is_monitored_assignment_or_exam_directive(
        selector=selector,
        source_facts=source_facts,
    ):
        isolate_directive_record(
            db=db,
            source=source,
            external_event_id=external_event_id,
            request_id=request_id,
            reason_code="directive_product_scope_excluded",
            source_facts=source_facts,
            payload=payload,
        )
        return []

    selector_dept = selector.get("course_dept")
    selector_number = selector.get("course_number")
    if not isinstance(selector_dept, str) or not selector_dept.strip() or not isinstance(selector_number, int):
        isolate_directive_record(
            db=db,
            source=source,
            external_event_id=external_event_id,
            request_id=request_id,
            reason_code="directive_missing_selector_identity",
            source_facts=source_facts,
            payload=payload,
        )
        return []

    candidates = load_directive_candidates(
        db=db,
        user_id=source.user_id,
        selector=selector,
    )

    family_labels = load_latest_family_labels(
        db,
        user_id=source.user_id,
        family_ids=[entity.family_id for entity in candidates],
    )
    matched_entities = [
        entity
        for entity in candidates
        if entity_matches_directive_selector(
            entity=entity,
            selector=selector,
            latest_family_labels=family_labels,
            applied_at=applied_at,
        )
    ]
    if not matched_entities:
        isolate_directive_record(
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
    out_of_scope_count = 0
    unsupported_or_no_effect_count = 0
    partial_out_of_scope_external_event_id = f"{external_event_id}#directive:term_out_of_scope"
    source_refs = [
        {
            "source_id": source.id,
            "source_kind": source.source_kind.value,
            "provider": source.provider,
            "external_event_id": external_event_id,
            "confidence": confidence,
        }
    ]
    term_window = parse_source_term_window(source, required=False)
    timezone_name = source_timezone_name(source)
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
        after_payload = apply_directive_mutation(
            before_payload=before_payload,
            mutation=mutation,
        )
        if after_payload is None:
            unsupported_or_no_effect_count += 1
            continue
        if term_window is not None:
            before_in_window = semantic_due_date_in_window(
                semantic_payload=before_payload,
                fallback_datetime=None,
                term_window=term_window,
                timezone_name=timezone_name,
            )
            after_in_window = semantic_due_date_in_window(
                semantic_payload=after_payload,
                fallback_datetime=None,
                term_window=term_window,
                timezone_name=timezone_name,
            )
            if not before_in_window or not after_in_window:
                out_of_scope_count += 1
                continue
        if semantic_payloads_equivalent(before_payload, after_payload):
            unsupported_or_no_effect_count += 1
            continue
        candidate_count += 1
        if parse_semantic_payload(entity.entity_uid, after_payload) is None:
            raise RuntimeError(
                f"runtime_apply_integrity_error: directive generated invalid semantic payload entity_uid={entity.entity_uid}"
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
        isolate_directive_record(
            db=db,
            source=source,
            external_event_id=partial_out_of_scope_external_event_id if out_of_scope_count > 0 else external_event_id,
            request_id=request_id,
            reason_code="directive_term_out_of_scope" if out_of_scope_count > 0 else "directive_unsupported_or_no_effect",
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
    if out_of_scope_count > 0 or unsupported_or_no_effect_count > 0:
        isolate_directive_record(
            db=db,
            source=source,
            external_event_id=partial_out_of_scope_external_event_id if out_of_scope_count > 0 else external_event_id,
            request_id=request_id,
            reason_code="directive_term_out_of_scope_partial" if out_of_scope_count > 0 else "directive_unsupported_or_no_effect",
            source_facts=source_facts,
            payload=payload,
        )
    else:
        resolve_active_unresolved_records(
            db=db,
            user_id=source.user_id,
            source_id=source.id,
            external_event_id=partial_out_of_scope_external_event_id,
            resolved_at=applied_at,
        )
    return created_changes


__all__ = ["apply_gmail_directive_record"]
