from __future__ import annotations

from datetime import datetime, timezone

from app.db.models.review import EventEntity
from app.modules.common.family_labels import semantic_family_equivalent
from app.modules.common.payload_schemas import ApprovedSemanticPayload
from app.modules.runtime.apply.semantic_event_service import semantic_due_datetime_from_payload

APPROVED_SEMANTIC_FIELDS = {
    "uid",
    "course_dept",
    "course_number",
    "course_suffix",
    "course_quarter",
    "course_year2",
    "family_id",
    "family_name",
    "raw_type",
    "event_name",
    "ordinal",
    "due_date",
    "due_time",
    "time_precision",
}

SEMANTIC_COMPARE_FIELDS = (
    "course_dept",
    "course_number",
    "course_suffix",
    "course_quarter",
    "course_year2",
    "raw_type",
    "event_name",
    "ordinal",
    "due_date",
    "due_time",
    "time_precision",
)


def parse_semantic_payload(entity_uid: str, payload: object) -> ApprovedSemanticPayload | None:
    model = _coerce_approved_semantic_payload(entity_uid=entity_uid, payload=payload)
    if model is None:
        return None
    if model.event_name is None or model.due_date is None:
        return None
    if semantic_due_datetime_from_payload(model) is None:
        return None
    return model


def semantic_payloads_equivalent(before_payload: object, after_payload: object) -> bool:
    before = _coerce_approved_semantic_payload(entity_uid=None, payload=before_payload)
    after = _coerce_approved_semantic_payload(entity_uid=None, payload=after_payload)
    if before is None or after is None:
        return False
    if not semantic_family_equivalent(
        before_family_id=before.family_id,
        after_family_id=after.family_id,
    ):
        return False
    for field in SEMANTIC_COMPARE_FIELDS:
        if str(getattr(before, field) or "") != str(getattr(after, field) or ""):
            return False
    return True


def semantic_delta_seconds(*, before_payload: object, after_payload: object) -> int | None:
    before = parse_semantic_payload("", before_payload)
    after = parse_semantic_payload("", after_payload)
    if before is None or after is None:
        return None
    before_due = semantic_due_datetime_from_payload(before)
    after_due = semantic_due_datetime_from_payload(after)
    if before_due is None or after_due is None:
        return None
    return int((after_due - before_due).total_seconds())


def approved_entity_to_semantic_payload(
    entity: EventEntity,
    *,
    family_name_override: str | None = None,
) -> dict:
    payload = ApprovedSemanticPayload.model_validate(
        {
            "uid": entity.entity_uid,
            "course_dept": entity.course_dept,
            "course_number": entity.course_number,
            "course_suffix": entity.course_suffix,
            "course_quarter": entity.course_quarter,
            "course_year2": entity.course_year2,
            "family_id": entity.family_id,
            "family_name": family_name_override.strip() if isinstance(family_name_override, str) and family_name_override.strip() else None,
            "raw_type": entity.raw_type,
            "event_name": entity.event_name,
            "ordinal": entity.ordinal,
            "due_date": entity.due_date,
            "due_time": entity.due_time,
            "time_precision": entity.time_precision or "datetime",
        }
    )
    return payload.to_json_dict()


def parse_iso_datetime(value: str) -> datetime | None:
    raw = value.strip()
    if not raw:
        return None
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed


def _coerce_approved_semantic_payload(
    *,
    entity_uid: str | None,
    payload: object,
) -> ApprovedSemanticPayload | None:
    if isinstance(payload, ApprovedSemanticPayload):
        if entity_uid and payload.uid != entity_uid:
            return payload.model_copy(update={"uid": entity_uid})
        return payload
    if not isinstance(payload, dict):
        return None
    normalized = {key: value for key, value in payload.items() if key in APPROVED_SEMANTIC_FIELDS}
    if entity_uid:
        normalized["uid"] = entity_uid
    elif not isinstance(normalized.get("uid"), str) or not str(normalized.get("uid")).strip():
        return None
    try:
        model = ApprovedSemanticPayload.model_validate(normalized)
    except Exception:
        return None
    return model


__all__ = [
    "approved_entity_to_semantic_payload",
    "parse_iso_datetime",
    "parse_semantic_payload",
    "semantic_delta_seconds",
    "semantic_payloads_equivalent",
]
