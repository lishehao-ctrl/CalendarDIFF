from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import and_, case, delete, func, literal, or_, select
from sqlalchemy.orm import Session

from app.db.models.ingestion import ConnectorResultStatus
from app.db.models.input import InputSource, SourceKind
from app.db.models.review import Change, Event, EventEntity, EventEntityLink, EventLinkAlert, EventLinkBlock, EventLinkCandidate, Input, InputType, SourceEventObservation
from app.db.models.shared import User
from app.modules.core_ingest.apply_orchestrator import apply_records, ensure_canonical_input_for_user
from app.modules.core_ingest.entity_profile import course_display_name, entity_best_display_name
from app.modules.users.course_work_item_families_service import mark_course_work_item_family_rebuild_complete, mark_course_work_item_family_rebuild_failed, mark_course_work_item_family_rebuild_running, normalize_course_key


def rebuild_user_work_item_state(db: Session, *, user: User, course_key: str | None = None) -> None:
    mark_course_work_item_family_rebuild_running(db, user=user)
    normalized_course_key = normalize_course_key(course_key)
    try:
        if normalized_course_key:
            _rebuild_user_course_state(db, user=user, normalized_course_key=normalized_course_key)
        else:
            _clear_user_derived_state(db, user_id=user.id)
            observations = _load_active_observations(db, user_id=user.id)
            _replay_observations(db, user_id=user.id, observations=observations, request_scope=f"user:{user.id}")
        db.commit()
        mark_course_work_item_family_rebuild_complete(db, user=user)
    except Exception as exc:
        db.rollback()
        mark_course_work_item_family_rebuild_failed(db, user=user, error=str(exc))
        raise


def _rebuild_user_course_state(db: Session, *, user: User, normalized_course_key: str) -> None:
    canonical_input = ensure_canonical_input_for_user(db=db, user_id=user.id)
    observations = _load_active_observations(db, user_id=user.id, normalized_course_key=normalized_course_key)
    _clear_course_derived_state(
        db,
        user_id=user.id,
        canonical_input=canonical_input,
        normalized_course_key=normalized_course_key,
        observations=observations,
    )
    _replay_observations(
        db,
        user_id=user.id,
        observations=observations,
        request_scope=f"user:{user.id}:course:{normalized_course_key}",
    )


def _load_active_observations(
    db: Session,
    *,
    user_id: int,
    normalized_course_key: str | None = None,
) -> list[SourceEventObservation]:
    stmt = (
        select(SourceEventObservation)
        .where(SourceEventObservation.user_id == user_id, SourceEventObservation.is_active.is_(True))
        .order_by(SourceEventObservation.source_id.asc(), SourceEventObservation.observed_at.asc(), SourceEventObservation.id.asc())
    )
    if normalized_course_key:
        stmt = stmt.where(_observation_course_key_clause(normalized_course_key))
    return list(db.scalars(stmt).all())


def _replay_observations(
    db: Session,
    *,
    user_id: int,
    observations: list[SourceEventObservation],
    request_scope: str,
) -> None:
    if not observations:
        return
    rows_by_source_id: dict[int, list[SourceEventObservation]] = defaultdict(list)
    for row in observations:
        rows_by_source_id[row.source_id].append(row)

    sources = list(
        db.scalars(
            select(InputSource)
            .where(
                InputSource.user_id == user_id,
                InputSource.is_active.is_(True),
                InputSource.id.in_(rows_by_source_id.keys()),
            )
            .order_by(InputSource.source_kind.asc(), InputSource.id.asc())
        ).all()
    )
    sources.sort(key=lambda row: (0 if row.source_kind == SourceKind.CALENDAR else 1, row.id))

    now = datetime.now(timezone.utc)
    for source in sources:
        source_rows = rows_by_source_id.get(source.id, [])
        if not source_rows:
            continue
        records: list[dict] = []
        record_type = "calendar.event.extracted" if source.source_kind == SourceKind.CALENDAR else "gmail.message.extracted"
        for row in source_rows:
            payload = _rebuild_payload_from_observation(
                source_kind=source.source_kind,
                external_event_id=row.external_event_id,
                payload=row.event_payload,
            )
            records.append({"record_type": record_type, "payload": payload})
        pseudo_result = SimpleNamespace(records=records, status=ConnectorResultStatus.CHANGED)
        request_id = _build_rebuild_request_id(
            user_id=user_id,
            source_id=source.id,
            request_scope=request_scope,
            at=now,
        )
        apply_records(db=db, result=pseudo_result, source=source, applied_at=now, request_id=request_id)



def _clear_user_derived_state(db: Session, *, user_id: int) -> None:
    canonical_input = db.scalar(
        select(Input).where(
            Input.user_id == user_id,
            Input.type == InputType.ICS,
            Input.identity_key == f"canonical:user:{user_id}",
        )
    )
    if canonical_input is not None:
        db.delete(canonical_input)
        db.flush()
    db.execute(delete(EventLinkAlert).where(EventLinkAlert.user_id == user_id))
    db.execute(delete(EventLinkCandidate).where(EventLinkCandidate.user_id == user_id))
    db.execute(delete(EventLinkBlock).where(EventLinkBlock.user_id == user_id))
    db.execute(delete(EventEntityLink).where(EventEntityLink.user_id == user_id))
    db.execute(delete(EventEntity).where(EventEntity.user_id == user_id))
    db.flush()



def _clear_course_derived_state(
    db: Session,
    *,
    user_id: int,
    canonical_input: Input,
    normalized_course_key: str,
    observations: list[SourceEventObservation],
) -> None:
    source_pairs = {(row.source_id, row.external_event_id) for row in observations}
    entity_uids_to_remove = {row.merge_key for row in observations if isinstance(row.merge_key, str) and row.merge_key.strip()}

    canonical_events = list(
        db.scalars(select(Event).where(Event.input_id == canonical_input.id)).all()
    )
    for row in canonical_events:
        event_course_key = normalize_course_key(row.course_label)
        if row.uid in entity_uids_to_remove or event_course_key == normalized_course_key:
            entity_uids_to_remove.add(row.uid)
            db.delete(row)

    pending_changes = list(
        db.scalars(select(Change).where(Change.input_id == canonical_input.id)).all()
    )
    for row in pending_changes:
        if row.event_uid in entity_uids_to_remove or _change_matches_course(row, normalized_course_key):
            entity_uids_to_remove.add(row.event_uid)
            db.delete(row)

    entity_links = list(
        db.scalars(select(EventEntityLink).where(EventEntityLink.user_id == user_id)).all()
    )
    for row in entity_links:
        if (row.source_id, row.external_event_id) in source_pairs or row.entity_uid in entity_uids_to_remove:
            entity_uids_to_remove.add(row.entity_uid)
            db.delete(row)

    link_candidates = list(
        db.scalars(select(EventLinkCandidate).where(EventLinkCandidate.user_id == user_id)).all()
    )
    for row in link_candidates:
        if (row.source_id, row.external_event_id) in source_pairs or (row.proposed_entity_uid in entity_uids_to_remove if row.proposed_entity_uid else False):
            if isinstance(row.proposed_entity_uid, str):
                entity_uids_to_remove.add(row.proposed_entity_uid)
            db.delete(row)

    link_blocks = list(
        db.scalars(select(EventLinkBlock).where(EventLinkBlock.user_id == user_id)).all()
    )
    for row in link_blocks:
        if (row.source_id, row.external_event_id) in source_pairs or row.blocked_entity_uid in entity_uids_to_remove:
            entity_uids_to_remove.add(row.blocked_entity_uid)
            db.delete(row)

    link_alerts = list(
        db.scalars(select(EventLinkAlert).where(EventLinkAlert.user_id == user_id)).all()
    )
    for row in link_alerts:
        if (row.source_id, row.external_event_id) in source_pairs or row.entity_uid in entity_uids_to_remove:
            entity_uids_to_remove.add(row.entity_uid)
            db.delete(row)

    entities = list(
        db.scalars(select(EventEntity).where(EventEntity.user_id == user_id)).all()
    )
    for row in entities:
        course_display = entity_best_display_name(row.course_best_json)
        if row.entity_uid in entity_uids_to_remove or normalize_course_key(course_display) == normalized_course_key:
            db.delete(row)

    db.flush()



def _change_matches_course(row: Change, normalized_course_key: str) -> bool:
    return _normalize_change_course_key(row.before_json) == normalized_course_key or _normalize_change_course_key(row.after_json) == normalized_course_key



def _normalize_change_course_key(payload: dict | None) -> str:
    if not isinstance(payload, dict):
        return ""
    course_label = payload.get("course_label")
    return normalize_course_key(course_label if isinstance(course_label, str) else None)



def _observation_course_key_clause(normalized_course_key: str):
    payload = SourceEventObservation.event_payload
    top_level_course_label = payload["course_label"].as_string()
    dept = payload["enrichment"]["course_parse"]["dept"].as_string()
    number = payload["enrichment"]["course_parse"]["number"].as_string()
    suffix = payload["enrichment"]["course_parse"]["suffix"].as_string()
    quarter = payload["enrichment"]["course_parse"]["quarter"].as_string()
    year2 = payload["enrichment"]["course_parse"]["year2"].as_string()

    course_parse_display = func.concat(
        func.coalesce(func.upper(dept), literal("")),
        case((number.is_not(None), literal(" ")), else_=literal("")),
        func.coalesce(number, literal("")),
        func.coalesce(func.upper(suffix), literal("")),
        case((and_(quarter.is_not(None), year2.is_not(None)), literal(" ")), else_=literal("")),
        case((and_(quarter.is_not(None), year2.is_not(None)), func.upper(quarter)), else_=literal("")),
        case((and_(quarter.is_not(None), year2.is_not(None)), func.lpad(year2, 2, "0")), else_=literal("")),
    )

    return or_(
        _sql_normalize_course_text(top_level_course_label) == normalized_course_key,
        and_(
            dept.is_not(None),
            number.is_not(None),
            _sql_normalize_course_text(course_parse_display) == normalized_course_key,
        ),
    )



def _sql_normalize_course_text(expr):
    lowered = func.lower(func.coalesce(expr, literal("")))
    punctuation_normalized = func.replace(func.replace(lowered, "-", " "), "_", " ")
    collapsed = func.regexp_replace(punctuation_normalized, r"\s+", " ", "g")
    return func.btrim(collapsed)



def _normalize_observation_course_key(payload: object) -> str:
    raw = payload if isinstance(payload, dict) else {}
    course_label = raw.get("course_label")
    if isinstance(course_label, str) and course_label.strip():
        normalized = normalize_course_key(course_label)
        if normalized:
            return normalized
    enrichment = raw.get("enrichment") if isinstance(raw.get("enrichment"), dict) else {}
    course_parse = enrichment.get("course_parse") if isinstance(enrichment.get("course_parse"), dict) else {}
    return normalize_course_key(course_display_name(course_parse=course_parse))



def _build_rebuild_request_id(*, user_id: int, source_id: int, request_scope: str, at: datetime) -> str:
    digest = hashlib.sha1(request_scope.encode("utf-8")).hexdigest()[:10]
    return f"rebuild:{user_id}:{source_id}:{digest}:{int(at.timestamp())}"[:64]


__all__ = ["rebuild_user_work_item_state"]



def _rebuild_payload_from_observation(*, source_kind: SourceKind, external_event_id: str, payload: object) -> dict:
    raw = payload if isinstance(payload, dict) else {}
    source_canonical_raw = raw.get("source_canonical")
    source_canonical = dict(source_canonical_raw) if isinstance(source_canonical_raw, dict) else {}
    enrichment_raw = raw.get("enrichment")
    enrichment = dict(enrichment_raw) if isinstance(enrichment_raw, dict) else {}
    rebuilt: dict = {
        "source_canonical": source_canonical,
        "enrichment": enrichment,
    }
    if source_kind == SourceKind.EMAIL:
        rebuilt["message_id"] = external_event_id
    if source_kind == SourceKind.CALENDAR and isinstance(raw.get("raw_ics_component_b64"), str):
        rebuilt["raw_ics_component_b64"] = raw["raw_ics_component_b64"]
    return rebuilt
