from __future__ import annotations

import hashlib

from sqlalchemy.orm import Session

from app.modules.core_ingest.entity_profile import course_display_name
from app.modules.core_ingest.merge_engine import build_merge_key
from app.modules.core_ingest.payload_extractors import normalize_work_item_parse
from app.modules.users.course_work_item_families_service import normalize_course_key, resolve_course_work_item_family


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
    raw_label = work_item_parse.get("raw_label") if isinstance(work_item_parse, dict) else None
    resolution = resolve_course_work_item_family(db, user_id=user_id, course_key=target_course, raw_label=raw_label)
    ordinal = work_item_parse.get("ordinal") if isinstance(work_item_parse.get("ordinal"), int) else None
    if not target_course or resolution.get("status") != "resolved" or ordinal is None:
        return {
            "status": "unresolved",
            "family_id": resolution.get("family_id"),
            "canonical_label": resolution.get("canonical_label"),
            "matched_alias": resolution.get("matched_alias"),
            "course_key": target_course,
            "raw_label": raw_label,
            "ordinal": ordinal,
            "entity_uid": None,
        }
    family_id = int(resolution["family_id"])
    entity_uid = build_semantic_entity_uid(course_key=target_course, family_id=family_id, ordinal=ordinal)
    return {
        "status": "resolved",
        "family_id": family_id,
        "canonical_label": resolution.get("canonical_label"),
        "matched_alias": resolution.get("matched_alias"),
        "course_key": target_course,
        "raw_label": raw_label,
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


def build_semantic_entity_uid(*, course_key: str, family_id: int, ordinal: int) -> str:
    canonical = "|".join([
        normalize_course_key(course_key),
        str(int(family_id)),
        str(int(ordinal)),
        "course_family_v1",
    ])
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
    return f"clf_{digest}"


__all__ = [
    "build_semantic_entity_uid",
    "build_source_scoped_entity_uid",
    "normalize_work_item_parse",
    "resolve_kind_resolution",
]
