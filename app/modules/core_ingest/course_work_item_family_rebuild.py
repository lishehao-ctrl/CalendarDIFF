from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.ingestion import ConnectorResultStatus
from app.db.models.input import InputSource, SourceKind
from app.db.models.review import SourceEventObservation
from app.db.models.shared import User
from app.modules.common.course_identity import normalized_course_identity_key
from app.modules.common.payload_schemas import SourceFacts
from app.modules.core_ingest.apply import apply_records
from app.modules.core_ingest.semantic_event_service import course_display_name
from app.modules.users.course_work_item_families_service import (
    mark_course_work_item_family_rebuild_complete,
    mark_course_work_item_family_rebuild_failed,
    mark_course_work_item_family_rebuild_running,
)


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
        _replay_observations(
            db,
            user_id=user.id,
            observations=observations,
            request_scope=f"user:{user.id}:{normalized_course_key or 'all'}",
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
        record_type = "calendar.event.extracted" if source.source_kind == SourceKind.CALENDAR else "gmail.message.extracted"
        records = [
            {
                "record_type": record_type,
                "payload": _rebuild_payload_from_observation(
                    source_kind=source.source_kind,
                    external_event_id=row.external_event_id,
                    payload=row.event_payload,
                ),
            }
            for row in source_rows
        ]
        pseudo_result = SimpleNamespace(records=records, status=ConnectorResultStatus.CHANGED)
        request_id = _build_rebuild_request_id(
            user_id=user_id,
            source_id=source.id,
            request_scope=request_scope,
            at=now,
        )
        apply_records(db=db, result=pseudo_result, source=source, applied_at=now, request_id=request_id)


def _build_rebuild_request_id(*, user_id: int, source_id: int, request_scope: str, at: datetime) -> str:
    digest = hashlib.sha1(request_scope.encode("utf-8")).hexdigest()[:10]
    return f"rebuild:{user_id}:{source_id}:{digest}:{int(at.timestamp())}"[:64]


def _rebuild_payload_from_observation(*, source_kind: SourceKind, external_event_id: str, payload: object) -> dict:
    raw = payload if isinstance(payload, dict) else {}
    source_facts_raw = raw.get("source_facts")
    try:
        source_facts = (
            SourceFacts.model_validate(source_facts_raw).model_dump(mode="json")
            if isinstance(source_facts_raw, dict)
            else {}
        )
    except Exception:
        source_facts = dict(source_facts_raw) if isinstance(source_facts_raw, dict) else {}
    semantic_event = raw.get("semantic_event") if isinstance(raw.get("semantic_event"), dict) else {}
    semantic_draft = {
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
    link_signals = raw.get("link_signals") if isinstance(raw.get("link_signals"), dict) else {}
    rebuilt: dict = {
        "source_facts": source_facts,
        "semantic_event_draft": semantic_draft,
        "link_signals": link_signals,
    }
    if source_kind == SourceKind.EMAIL:
        rebuilt["message_id"] = external_event_id
    if source_kind == SourceKind.CALENDAR and isinstance(raw.get("raw_ics_component_b64"), str):
        rebuilt["raw_ics_component_b64"] = raw["raw_ics_component_b64"]
    return rebuilt


def _normalize_observation_course_key(payload: object) -> str:
    raw = payload if isinstance(payload, dict) else {}
    semantic_event = raw.get("semantic_event") if isinstance(raw.get("semantic_event"), dict) else {}
    semantic_draft = raw.get("semantic_event_draft") if isinstance(raw.get("semantic_event_draft"), dict) else {}
    return normalized_course_identity_key(
        **_course_identity_from_display(course_display_name(semantic_event=semantic_event or semantic_draft))
    )


def _course_identity_from_display(course_display: str | None) -> dict[str, object]:
    from app.modules.common.course_identity import parse_course_display

    parsed = parse_course_display(course_display)
    return {
        "course_dept": parsed["course_dept"] if isinstance(parsed["course_dept"], str) else None,
        "course_number": parsed["course_number"] if isinstance(parsed["course_number"], int) else None,
        "course_suffix": parsed["course_suffix"] if isinstance(parsed["course_suffix"], str) else None,
        "course_quarter": parsed["course_quarter"] if isinstance(parsed["course_quarter"], str) else None,
        "course_year2": parsed["course_year2"] if isinstance(parsed["course_year2"], int) else None,
    }


__all__ = ["rebuild_user_work_item_state"]
