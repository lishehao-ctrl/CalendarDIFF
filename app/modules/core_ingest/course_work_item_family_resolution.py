from __future__ import annotations

from sqlalchemy.orm import Session

from app.modules.common.course_identity import course_display_name, normalize_label_token
from app.modules.core_ingest.semantic_event_service import normalize_semantic_parse
from app.modules.core_ingest.raw_type_matching import RawTypeMatchError, compare_raw_type_against_known_types
from app.modules.users.course_raw_types_service import (
    create_course_raw_type,
    create_raw_type_suggestion,
    find_course_raw_type,
    list_course_raw_types,
)
from app.modules.users.course_work_item_families_service import (
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
    known_rows = [
        row
        for row in list_course_raw_types(
            db,
            user_id=user_id,
            course_dept=course_dept,
            course_number=course_number,
            course_suffix=course_suffix,
            course_quarter=course_quarter,
            course_year2=course_year2,
        )
        if row.id != current_raw_type.id
    ]
    known_raw_types = [row.raw_type for row in known_rows]
    known_family_by_label = {
        normalize_label_token(row.canonical_label): row
        for row in list_course_work_item_families(
            db,
            user_id=user_id,
            course_dept=course_dept,
            course_number=course_number,
            course_suffix=course_suffix,
            course_quarter=course_quarter,
            course_year2=course_year2,
        )
        if row.id != family.id
    }
    for normalized_label, row in known_family_by_label.items():
        if normalized_label and normalized_label not in {normalize_label_token(value) for value in known_raw_types}:
            known_raw_types.append(row.canonical_label)
    suggestion_id = None
    matched_alias = incoming_raw_type
    status = "new_family"
    if known_raw_types:
        try:
            llm_match = compare_raw_type_against_known_types(
                db,
                source_id=source_id,
                request_id=request_id,
                provider=provider,
                course_key=target_course_display or "",
                incoming_raw_type=incoming_raw_type,
                event_name=event_name_value or incoming_raw_type,
                ordinal=ordinal,
                known_raw_types=known_raw_types,
            )
        except RawTypeMatchError:
            llm_match = {"matched_raw_type": None, "confidence": 0.0, "evidence": ""}
        matched_raw_type = llm_match.get("matched_raw_type") if isinstance(llm_match.get("matched_raw_type"), str) else None
        if matched_raw_type and normalize_label_token(matched_raw_type) != normalize_label_token(incoming_raw_type):
            suggested_row = find_course_raw_type(
                db,
                user_id=user_id,
                course_dept=course_dept,
                course_number=course_number,
                course_suffix=course_suffix,
                course_quarter=course_quarter,
                course_year2=course_year2,
                raw_type=matched_raw_type,
            )
            if suggested_row is None:
                suggested_family = known_family_by_label.get(normalize_label_token(matched_raw_type))
                if suggested_family is not None:
                    suggested_row = create_course_raw_type(db, family=suggested_family, raw_type=suggested_family.canonical_label, commit=False)
            if suggested_row is not None:
                suggestion = create_raw_type_suggestion(
                    db,
                    source_raw_type=current_raw_type,
                    suggested_raw_type=suggested_row,
                    source_observation_id=source_observation_id,
                    confidence=float(llm_match.get("confidence") or 0.0),
                    evidence=str(llm_match.get("evidence") or "") or None,
                )
                suggestion_id = suggestion.id
                status = "suggested"
                matched_alias = matched_raw_type

    resolution = {
        "status": status,
        "family_id": family.id,
        "canonical_label": family.canonical_label,
        "matched_alias": matched_alias,
        "course_display": target_course_display,
        "course_dept": course_dept,
        "course_number": course_number,
        "course_suffix": course_suffix,
        "course_quarter": course_quarter,
        "course_year2": course_year2,
        "raw_type": incoming_raw_type,
        "ordinal": ordinal,
        "raw_type_id": current_raw_type.id,
        "suggestion_id": suggestion_id,
    }
    _assert_family_resolution_invariant(resolution)
    return resolution


def _assert_family_resolution_invariant(resolution: dict[str, object]) -> None:
    status = resolution.get("status")
    if status == "unresolved":
        return
    family_id = resolution.get("family_id")
    if not isinstance(family_id, int):
        raise RuntimeError(f"core_ingest_integrity_error: resolved kind_resolution missing family_id (status={status})")


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
