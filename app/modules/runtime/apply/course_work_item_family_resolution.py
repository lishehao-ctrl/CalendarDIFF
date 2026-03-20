from __future__ import annotations

from sqlalchemy.orm import Session

from app.modules.common.course_identity import course_display_name, normalize_label_token
from app.modules.runtime.apply.semantic_event_service import normalize_semantic_parse
from app.modules.families.raw_type_service import (
    create_course_raw_type,
    find_course_raw_type,
    list_course_raw_types,
)
from app.modules.families.family_service import (
    create_course_work_item_family,
    list_course_work_item_families,
    resolve_course_work_item_family,
)


def resolve_kind_resolution(
    db: Session,
    *,
    user_id: int,
    course_parse: dict,
    semantic_parse: dict,
    source_facts: dict | None = None,
    source_kind: str,
    external_event_id: str,
    source_id: int | None = None,
    request_id: str | None = None,
    provider: str | None = None,
    source_observation_id: int | None = None,
) -> dict[str, object]:
    del source_kind
    del external_event_id
    normalized_semantic = normalize_semantic_parse(semantic_parse)
    course_dept = course_parse.get("dept") if isinstance(course_parse.get("dept"), str) else None
    course_number = course_parse.get("number") if isinstance(course_parse.get("number"), int) else None
    course_suffix = course_parse.get("suffix") if isinstance(course_parse.get("suffix"), str) else None
    course_quarter = course_parse.get("quarter") if isinstance(course_parse.get("quarter"), str) else None
    course_year2 = course_parse.get("year2") if isinstance(course_parse.get("year2"), int) else None
    target_course_display = course_display_name(course_parse=course_parse) if isinstance(course_parse, dict) else None
    raw_type = normalized_semantic.get("raw_type")
    ordinal = normalized_semantic.get("ordinal") if isinstance(normalized_semantic.get("ordinal"), int) else None
    event_name_value = normalized_semantic.get("event_name") if isinstance(normalized_semantic.get("event_name"), str) else None
    source_title_value = source_facts.get("source_title") if isinstance(source_facts, dict) and isinstance(source_facts.get("source_title"), str) else None
    incoming_raw_type = _first_non_empty_text(raw_type, event_name_value, source_title_value) or "Untitled"
    if course_dept is None or course_number is None:
        return {
            "status": "unresolved",
            "reason_code": "missing_course_identity",
            "family_id": None,
            "canonical_label": None,
            "matched_alias": None,
            "course_display": target_course_display,
            "course_dept": course_dept,
            "course_number": course_number,
            "course_suffix": course_suffix,
            "course_quarter": course_quarter,
            "course_year2": course_year2,
            "raw_type": incoming_raw_type,
            "ordinal": ordinal,
            "raw_type_id": None,
            "suggestion_id": None,
        }

    exact_resolution = resolve_course_work_item_family(
        db,
        user_id=user_id,
        course_dept=course_dept,
        course_number=course_number,
        course_suffix=course_suffix,
        course_quarter=course_quarter,
        course_year2=course_year2,
        raw_label=incoming_raw_type,
    )
    if exact_resolution.get("status") == "resolved" and isinstance(exact_resolution.get("family_id"), int):
        family_id = int(exact_resolution["family_id"])
        resolution = {
            "status": "exact",
            "family_id": family_id,
            "canonical_label": exact_resolution.get("canonical_label"),
            "matched_alias": exact_resolution.get("matched_alias"),
            "course_display": target_course_display,
            "course_dept": course_dept,
            "course_number": course_number,
            "course_suffix": course_suffix,
            "course_quarter": course_quarter,
            "course_year2": course_year2,
            "raw_type": incoming_raw_type,
            "ordinal": ordinal,
            "raw_type_id": exact_resolution.get("raw_type_id"),
            "suggestion_id": None,
        }
        _assert_family_resolution_invariant(resolution)
        return resolution

    family = create_course_work_item_family(
        db,
        user_id=user_id,
        course_dept=course_dept,
        course_number=course_number,
        course_suffix=course_suffix,
        course_quarter=course_quarter,
        course_year2=course_year2,
        canonical_label=incoming_raw_type,
        raw_types=[],
        commit=False,
    )
    current_raw_type = find_course_raw_type(
        db,
        user_id=user_id,
        course_dept=course_dept,
        course_number=course_number,
        course_suffix=course_suffix,
        course_quarter=course_quarter,
        course_year2=course_year2,
        raw_type=incoming_raw_type,
    )
    if current_raw_type is None:
        current_raw_type = create_course_raw_type(db, family=family, raw_type=incoming_raw_type, commit=False)
    resolution = {
        "status": "new_family",
        "family_id": family.id,
        "canonical_label": family.canonical_label,
        "matched_alias": incoming_raw_type,
        "course_display": target_course_display,
        "course_dept": course_dept,
        "course_number": course_number,
        "course_suffix": course_suffix,
        "course_quarter": course_quarter,
        "course_year2": course_year2,
        "raw_type": incoming_raw_type,
        "ordinal": ordinal,
        "raw_type_id": current_raw_type.id,
        "suggestion_id": None,
    }
    _assert_family_resolution_invariant(resolution)
    return resolution


def _assert_family_resolution_invariant(resolution: dict[str, object]) -> None:
    status = resolution.get("status")
    if status == "unresolved":
        return
    family_id = resolution.get("family_id")
    if not isinstance(family_id, int):
        raise RuntimeError(f"runtime_apply_integrity_error: resolved kind_resolution missing family_id (status={status})")


def _first_non_empty_text(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                return cleaned[:128]
    return None

__all__ = [
    "normalize_semantic_parse",
    "resolve_kind_resolution",
]
