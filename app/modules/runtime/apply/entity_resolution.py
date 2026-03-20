from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.input import InputSource
from app.db.models.review import EventEntity, EventEntityLifecycle, SourceEventObservation
from app.modules.common.course_identity import normalized_course_identity_key


@dataclass(frozen=True)
class EntityResolutionResult:
    status: str
    entity_uid: str | None
    reason_code: str | None
    matched_via: str | None


@dataclass(frozen=True)
class _EntityResolutionKey:
    course_identity: str
    course_dept: str | None
    course_number: int | None
    course_suffix: str | None
    course_quarter: str | None
    course_year2: int | None
    family_id: int
    ordinal: int


def resolve_entity_uid(
    *,
    db: Session,
    source: InputSource,
    external_event_id: str,
    course_parse: dict,
    kind_resolution: dict,
) -> EntityResolutionResult:
    existing_observation = db.scalar(
        select(SourceEventObservation).where(
            SourceEventObservation.source_id == source.id,
            SourceEventObservation.external_event_id == external_event_id,
            SourceEventObservation.is_active.is_(True),
        )
    )
    if existing_observation is not None and isinstance(existing_observation.entity_uid, str) and existing_observation.entity_uid.strip():
        return EntityResolutionResult(
            status="resolved",
            entity_uid=existing_observation.entity_uid,
            reason_code=None,
            matched_via="same_source_observation",
        )

    resolution_key = _build_resolution_key(course_parse=course_parse, kind_resolution=kind_resolution)
    if resolution_key is None:
        return EntityResolutionResult(
            status="unresolved",
            entity_uid=None,
            reason_code="insufficient_entity_resolution",
            matched_via=None,
        )

    active_entities = list(
        db.scalars(
            select(EventEntity).where(
                EventEntity.user_id == source.user_id,
                EventEntity.lifecycle == EventEntityLifecycle.ACTIVE,
                EventEntity.course_dept == resolution_key.course_dept,
                EventEntity.course_number == resolution_key.course_number,
                EventEntity.course_suffix == resolution_key.course_suffix,
                EventEntity.course_quarter == resolution_key.course_quarter,
                EventEntity.course_year2 == resolution_key.course_year2,
                EventEntity.family_id == resolution_key.family_id,
                EventEntity.ordinal == resolution_key.ordinal,
            )
        ).all()
    )
    entity_uids = sorted(
        {
            row.entity_uid.strip()
            for row in active_entities
            if isinstance(row.entity_uid, str) and row.entity_uid.strip()
        }
    )
    if len(entity_uids) == 1:
        return EntityResolutionResult(
            status="resolved",
            entity_uid=entity_uids[0],
            reason_code=None,
            matched_via="active_entity",
        )
    if len(entity_uids) > 1:
        return EntityResolutionResult(
            status="unresolved",
            entity_uid=None,
            reason_code="ambiguous_entity_resolution",
            matched_via=None,
        )

    active_observations = list(
        db.scalars(
            select(SourceEventObservation).where(
                SourceEventObservation.user_id == source.user_id,
                SourceEventObservation.is_active.is_(True),
            )
        ).all()
    )
    matched_observation_uids = sorted(
        {
            row.entity_uid.strip()
            for row in active_observations
            if _observation_matches_resolution_key(row=row, resolution_key=resolution_key)
            and isinstance(row.entity_uid, str)
            and row.entity_uid.strip()
        }
    )
    if len(matched_observation_uids) == 1:
        return EntityResolutionResult(
            status="resolved",
            entity_uid=matched_observation_uids[0],
            reason_code=None,
            matched_via="active_observation",
        )
    if len(matched_observation_uids) > 1:
        return EntityResolutionResult(
            status="unresolved",
            entity_uid=None,
            reason_code="ambiguous_entity_resolution",
            matched_via=None,
        )

    return EntityResolutionResult(
        status="resolved",
        entity_uid=_new_entity_uid(),
        reason_code=None,
        matched_via="new_entity",
    )


def _build_resolution_key(*, course_parse: dict, kind_resolution: dict) -> _EntityResolutionKey | None:
    course_dept = course_parse.get("dept") if isinstance(course_parse.get("dept"), str) else None
    course_number = course_parse.get("number") if isinstance(course_parse.get("number"), int) else None
    course_suffix = course_parse.get("suffix") if isinstance(course_parse.get("suffix"), str) else None
    course_quarter = course_parse.get("quarter") if isinstance(course_parse.get("quarter"), str) else None
    course_year2 = course_parse.get("year2") if isinstance(course_parse.get("year2"), int) else None
    family_id = kind_resolution.get("family_id") if isinstance(kind_resolution.get("family_id"), int) else None
    ordinal = kind_resolution.get("ordinal") if isinstance(kind_resolution.get("ordinal"), int) else None
    course_identity = normalized_course_identity_key(
        course_dept=course_dept,
        course_number=course_number,
        course_suffix=course_suffix,
        course_quarter=course_quarter,
        course_year2=course_year2,
    )
    if not course_identity or family_id is None or ordinal is None:
        return None
    return _EntityResolutionKey(
        course_identity=course_identity,
        course_dept=course_dept,
        course_number=course_number,
        course_suffix=course_suffix,
        course_quarter=course_quarter,
        course_year2=course_year2,
        family_id=family_id,
        ordinal=ordinal,
    )


def _observation_matches_resolution_key(*, row: SourceEventObservation, resolution_key: _EntityResolutionKey) -> bool:
    payload = row.event_payload if isinstance(row.event_payload, dict) else {}
    semantic_event = payload.get("semantic_event") if isinstance(payload.get("semantic_event"), dict) else {}
    family_id = semantic_event.get("family_id") if isinstance(semantic_event.get("family_id"), int) else None
    ordinal = semantic_event.get("ordinal") if isinstance(semantic_event.get("ordinal"), int) else None
    course_identity = normalized_course_identity_key(
        course_dept=semantic_event.get("course_dept") if isinstance(semantic_event.get("course_dept"), str) else None,
        course_number=semantic_event.get("course_number") if isinstance(semantic_event.get("course_number"), int) else None,
        course_suffix=semantic_event.get("course_suffix") if isinstance(semantic_event.get("course_suffix"), str) else None,
        course_quarter=semantic_event.get("course_quarter") if isinstance(semantic_event.get("course_quarter"), str) else None,
        course_year2=semantic_event.get("course_year2") if isinstance(semantic_event.get("course_year2"), int) else None,
    )
    return (
        course_identity == resolution_key.course_identity
        and family_id == resolution_key.family_id
        and ordinal == resolution_key.ordinal
    )


def _new_entity_uid() -> str:
    return f"entity-{uuid4().hex[:16]}"


__all__ = ["EntityResolutionResult", "resolve_entity_uid"]
