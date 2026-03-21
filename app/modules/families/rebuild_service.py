from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.input import InputSource
from app.db.models.review import SourceEventObservation
from app.db.models.shared import User
from app.modules.common.course_identity import normalized_course_identity_key
from app.modules.families.family_service import (
    mark_course_work_item_family_rebuild_complete,
    mark_course_work_item_family_rebuild_failed,
    mark_course_work_item_family_rebuild_running,
)
from app.modules.families.resolution_service import resolve_kind_resolution
from app.modules.runtime.apply.observation_store import compute_payload_hash, normalize_observation_payload
from app.modules.runtime.apply.pending_proposal_rebuild import rebuild_pending_change_proposals


def rebuild_user_work_item_state(
    db: Session,
    *,
    user: User,
    course_dept: str | None = None,
    course_number: int | None = None,
    course_suffix: str | None = None,
    course_quarter: str | None = None,
    course_year2: int | None = None,
) -> None:
    mark_course_work_item_family_rebuild_running(db, user=user)
    normalized_course_key = normalized_course_identity_key(
        course_dept=course_dept,
        course_number=course_number,
        course_suffix=course_suffix,
        course_quarter=course_quarter,
        course_year2=course_year2,
    )
    try:
        observations = _load_active_observations(db, user_id=user.id, normalized_course_key=normalized_course_key)
        now = datetime.now(timezone.utc)
        affected_by_source = _recompute_observations(
            db,
            user_id=user.id,
            observations=observations,
            request_scope=f"user:{user.id}:{normalized_course_key or 'all'}",
            applied_at=now,
        )
        _rebuild_pending_proposals(
            db=db,
            user_id=user.id,
            affected_entity_uids_by_source=affected_by_source,
            applied_at=now,
        )
        db.commit()
        mark_course_work_item_family_rebuild_complete(db, user=user)
    except Exception as exc:
        db.rollback()
        mark_course_work_item_family_rebuild_failed(db, user=user, error=str(exc))
        raise


def _load_active_observations(
    db: Session,
    *,
    user_id: int,
    normalized_course_key: str | None,
) -> list[SourceEventObservation]:
    rows = list(
        db.scalars(
            select(SourceEventObservation)
            .where(SourceEventObservation.user_id == user_id, SourceEventObservation.is_active.is_(True))
            .order_by(SourceEventObservation.source_id.asc(), SourceEventObservation.observed_at.asc(), SourceEventObservation.id.asc())
        ).all()
    )
    if not normalized_course_key:
        return rows
    return [row for row in rows if _normalize_observation_course_key(row.event_payload) == normalized_course_key]


def _recompute_observations(
    db: Session,
    *,
    user_id: int,
    observations: list[SourceEventObservation],
    request_scope: str,
    applied_at: datetime,
) -> dict[int, set[str]]:
    if not observations:
        return {}
    affected_by_source: dict[int, set[str]] = defaultdict(set)

    rows_by_source_id: dict[int, list[SourceEventObservation]] = defaultdict(list)
    for row in observations:
        rows_by_source_id[int(row.source_id)].append(row)

    for source_id in sorted(rows_by_source_id.keys()):
        request_id = _build_rebuild_request_id(
            user_id=user_id,
            source_id=source_id,
            request_scope=request_scope,
            at=applied_at,
        )
        for row in rows_by_source_id[source_id]:
            payload = row.event_payload if isinstance(row.event_payload, dict) else {}
            normalized_payload = normalize_observation_payload(payload)

            source_facts = normalized_payload.get("source_facts")
            semantic_event = normalized_payload.get("semantic_event")
            link_signals = normalized_payload.get("link_signals")
            if not isinstance(source_facts, dict) or not isinstance(semantic_event, dict) or not isinstance(link_signals, dict):
                raise RuntimeError(
                    f"family_rebuild_integrity_error: invalid runtime payload for observation_id={row.id}"
                )

            entity_uid = row.entity_uid.strip() if isinstance(row.entity_uid, str) else ""
            if not entity_uid:
                raise RuntimeError(
                    f"family_rebuild_integrity_error: missing entity_uid for observation_id={row.id}"
                )

            kind_resolution = resolve_kind_resolution(
                db,
                user_id=user_id,
                course_parse=_course_parse_from_semantic_event(semantic_event),
                semantic_parse=_semantic_parse_from_semantic_event(semantic_event),
                source_facts=source_facts,
                source_kind=row.source_kind.value,
                external_event_id=row.external_event_id,
                source_id=row.source_id,
                request_id=request_id,
                provider=row.provider,
                source_observation_id=row.id,
            )
            if kind_resolution.get("status") == "unresolved":
                raise RuntimeError(
                    f"family_rebuild_integrity_error: active observation unresolved observation_id={row.id}"
                )

            next_semantic_event = dict(semantic_event)
            next_semantic_event["uid"] = entity_uid
            next_semantic_event["family_id"] = kind_resolution.get("family_id")
            if isinstance(kind_resolution.get("canonical_label"), str):
                next_semantic_event["family_name"] = kind_resolution["canonical_label"]
            if isinstance(kind_resolution.get("raw_type"), str):
                next_semantic_event["raw_type"] = kind_resolution["raw_type"]

            next_payload: dict[str, object] = {
                "source_facts": dict(source_facts),
                "semantic_event": next_semantic_event,
                "link_signals": dict(link_signals),
                "kind_resolution": kind_resolution,
            }
            raw_ics_component_b64 = normalized_payload.get("raw_ics_component_b64")
            if isinstance(raw_ics_component_b64, str) and raw_ics_component_b64:
                next_payload["raw_ics_component_b64"] = raw_ics_component_b64
            normalized_next_payload = normalize_observation_payload(next_payload)

            if normalized_next_payload == normalized_payload:
                continue
            row.event_payload = normalized_next_payload
            row.event_hash = compute_payload_hash(normalized_next_payload)
            row.observed_at = applied_at
            row.last_request_id = request_id
            affected_by_source[source_id].add(entity_uid)

    return {source_id: entity_uids for source_id, entity_uids in affected_by_source.items() if entity_uids}


def _build_rebuild_request_id(*, user_id: int, source_id: int, request_scope: str, at: datetime) -> str:
    digest = hashlib.sha1(request_scope.encode("utf-8")).hexdigest()[:10]
    return f"rebuild:{user_id}:{source_id}:{digest}:{int(at.timestamp())}"[:64]


def _rebuild_pending_proposals(
    *,
    db: Session,
    user_id: int,
    affected_entity_uids_by_source: dict[int, set[str]],
    applied_at: datetime,
) -> None:
    if not affected_entity_uids_by_source:
        return
    for source_id in sorted(affected_entity_uids_by_source.keys()):
        affected_entity_uids = affected_entity_uids_by_source.get(source_id) or set()
        if not affected_entity_uids:
            continue
        source = db.scalar(
            select(InputSource).where(
                InputSource.id == source_id,
                InputSource.user_id == user_id,
            ).limit(1)
        )
        if source is None:
            continue
        rebuild_pending_change_proposals(
            db=db,
            user_id=user_id,
            source=source,
            affected_entity_uids=affected_entity_uids,
            applied_at=applied_at,
        )


def _normalize_observation_course_key(payload: object) -> str:
    raw = payload if isinstance(payload, dict) else {}
    semantic_event = raw.get("semantic_event") if isinstance(raw.get("semantic_event"), dict) else {}
    return normalized_course_identity_key(
        course_dept=semantic_event.get("course_dept") if isinstance(semantic_event.get("course_dept"), str) else None,
        course_number=semantic_event.get("course_number") if isinstance(semantic_event.get("course_number"), int) else None,
        course_suffix=semantic_event.get("course_suffix") if isinstance(semantic_event.get("course_suffix"), str) else None,
        course_quarter=semantic_event.get("course_quarter") if isinstance(semantic_event.get("course_quarter"), str) else None,
        course_year2=semantic_event.get("course_year2") if isinstance(semantic_event.get("course_year2"), int) else None,
    )


def _course_parse_from_semantic_event(semantic_event: dict) -> dict:
    return {
        "dept": semantic_event.get("course_dept"),
        "number": semantic_event.get("course_number"),
        "suffix": semantic_event.get("course_suffix"),
        "quarter": semantic_event.get("course_quarter"),
        "year2": semantic_event.get("course_year2"),
        "confidence": semantic_event.get("confidence") if isinstance(semantic_event.get("confidence"), (int, float)) else 0.0,
        "evidence": semantic_event.get("evidence") if isinstance(semantic_event.get("evidence"), str) else "",
    }


def _semantic_parse_from_semantic_event(semantic_event: dict) -> dict:
    return {
        "course_dept": semantic_event.get("course_dept"),
        "course_number": semantic_event.get("course_number"),
        "course_suffix": semantic_event.get("course_suffix"),
        "course_quarter": semantic_event.get("course_quarter"),
        "course_year2": semantic_event.get("course_year2"),
        "raw_type": semantic_event.get("raw_type"),
        "event_name": semantic_event.get("event_name"),
        "ordinal": semantic_event.get("ordinal"),
        "due_date": semantic_event.get("due_date"),
        "due_time": semantic_event.get("due_time"),
        "time_precision": semantic_event.get("time_precision"),
        "confidence": semantic_event.get("confidence"),
        "evidence": semantic_event.get("evidence"),
    }


__all__ = ["rebuild_user_work_item_state"]
