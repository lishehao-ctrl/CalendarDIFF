from __future__ import annotations

import hashlib

from sqlalchemy.orm import Session

from app.modules.core_ingest.entity_profile import course_display_name
from app.modules.core_ingest.merge_engine import build_merge_key
from app.modules.users.work_item_kind_mappings_service import normalize_work_item_kind_token, resolve_work_item_kind_mapping


def normalize_work_item_parse(raw: object) -> dict:
    if not isinstance(raw, dict):
        return {"raw_kind_label": None, "ordinal": None, "confidence": 0.0, "evidence": ""}
    raw_kind_label = raw.get("raw_kind_label")
    ordinal = raw.get("ordinal") if isinstance(raw.get("ordinal"), int) and int(raw.get("ordinal")) > 0 else None
    confidence = float(raw.get("confidence")) if isinstance(raw.get("confidence"), (int, float)) else 0.0
    confidence = max(0.0, min(1.0, confidence))
    evidence = raw.get("evidence") if isinstance(raw.get("evidence"), str) else ""
    return {
        "raw_kind_label": raw_kind_label.strip()[:128] if isinstance(raw_kind_label, str) and raw_kind_label.strip() else None,
        "ordinal": ordinal,
        "confidence": confidence,
        "evidence": evidence.strip()[:120],
    }


def resolve_kind_resolution(
    db: Session,
    *,
    user_id: int,
    course_parse: dict,
    work_item_parse: dict,
    source_kind: str,
    external_event_id: str,
) -> dict[str, object]:
    del source_kind
    del external_event_id
    target_course = course_display_name(course_parse=course_parse) if isinstance(course_parse, dict) else None
    resolution = resolve_work_item_kind_mapping(db, user_id=user_id, raw_kind_label=work_item_parse.get("raw_kind_label"))
    ordinal = work_item_parse.get("ordinal") if isinstance(work_item_parse.get("ordinal"), int) else None
    if not target_course or resolution.get("status") != "resolved" or ordinal is None:
        return {
            "status": "unresolved",
            "mapping_id": resolution.get("mapping_id"),
            "name": resolution.get("name"),
            "matched_alias": resolution.get("matched_alias"),
            "target_course": target_course,
            "ordinal": ordinal,
            "entity_uid": None,
        }
    mapping_id = int(resolution["mapping_id"])
    entity_uid = build_semantic_entity_uid(target_course=target_course, mapping_id=mapping_id, ordinal=ordinal)
    return {
        "status": "resolved",
        "mapping_id": mapping_id,
        "name": resolution.get("name"),
        "matched_alias": resolution.get("matched_alias"),
        "target_course": target_course,
        "ordinal": ordinal,
        "entity_uid": entity_uid,
    }


def build_source_scoped_entity_uid(*, source_kind: str, external_event_id: str) -> str:
    return build_merge_key(
        course_label=None,
        title=None,
        start_at=None,
        end_at=None,
        event_type=None,
        source_kind=source_kind,
        external_event_id=external_event_id,
    )


def build_semantic_entity_uid(*, target_course: str, mapping_id: int, ordinal: int) -> str:
    canonical = "|".join([
        normalize_work_item_kind_token(target_course),
        str(int(mapping_id)),
        str(int(ordinal)),
        "work_item_v1",
    ])
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
    return f"wki_{digest}"


__all__ = [
    "build_semantic_entity_uid",
    "build_source_scoped_entity_uid",
    "normalize_work_item_parse",
    "resolve_kind_resolution",
]
