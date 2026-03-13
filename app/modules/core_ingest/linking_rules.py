from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.input import InputSource, SourceKind
from app.db.models.review import SourceEventObservation
from app.modules.core_ingest.semantic_event_service import normalize_semantic_parse


@dataclass(frozen=True)
class LinkDecision:
    entity_uid: str | None
    status: str
    score: float
    candidate_entity_uid: str | None
    reason_code: str | None
    score_breakdown: dict


def decide_inventory_link(
    db: Session,
    *,
    source: InputSource,
    external_event_id: str,
    course_parse: dict,
    semantic_parse: dict,
    time_anchor_confidence: float,
    blocked_entity_uids: set[str],
) -> LinkDecision:
    normalized_conf = max(0.0, min(1.0, float(time_anchor_confidence)))
    if normalized_conf < 0.5:
        return _candidate(
            rule_reason="low_time_anchor_confidence",
            candidate_entity_uid=None,
            evidence={"time_anchor_confidence": round(normalized_conf, 4)},
            reason_code="low_confidence",
        )

    incoming_dept = _coerce_text(course_parse.get("dept"))
    incoming_number = course_parse.get("number") if isinstance(course_parse.get("number"), int) else None
    incoming_suffix = _coerce_text(course_parse.get("suffix"))
    normalized_semantic = normalize_semantic_parse(semantic_parse)
    incoming_raw_type = _coerce_text(normalized_semantic.get("raw_type"))
    incoming_ordinal = normalized_semantic.get("ordinal") if isinstance(normalized_semantic.get("ordinal"), int) else None

    if incoming_dept is None or incoming_number is None:
        return _candidate(
            rule_reason="missing_course_anchor",
            candidate_entity_uid=None,
            evidence={"incoming_course_parse": {"dept": incoming_dept, "number": incoming_number}},
        )
    if incoming_raw_type is None:
        return _candidate(
            rule_reason="missing_raw_type",
            candidate_entity_uid=None,
            evidence={"incoming_semantic_parse": {"raw_type": incoming_raw_type, "ordinal": incoming_ordinal}},
        )

    calendar_observations = db.scalars(
        select(SourceEventObservation).where(
            SourceEventObservation.user_id == source.user_id,
            SourceEventObservation.source_kind == SourceKind.CALENDAR,
            SourceEventObservation.is_active.is_(True),
        )
    ).all()
    if not calendar_observations:
        return _candidate(rule_reason="no_rule_match", candidate_entity_uid=None, evidence={"candidate_count": 0})

    by_course = [
        row
        for row in calendar_observations
        if _course_key(_course_parse_from_payload(row.event_payload)) == (incoming_dept, incoming_number)
    ]
    if not by_course:
        return _candidate(
            rule_reason="no_rule_match",
            candidate_entity_uid=None,
            evidence={"course_key": f"{incoming_dept}{incoming_number}", "candidate_count": 0},
        )

    course_suffixes = sorted(
        {
            suffix
            for row in by_course
            for suffix in [_coerce_text(_course_parse_from_payload(row.event_payload).get("suffix"))]
            if suffix is not None
        }
    )
    requires_suffix = bool(course_suffixes)
    suffix_filtered = list(by_course)
    if requires_suffix:
        if incoming_suffix is None:
            return _candidate(
                rule_reason="suffix_required_missing",
                candidate_entity_uid=_pick_candidate_uid(by_course),
                evidence={
                    "course_key": f"{incoming_dept}{incoming_number}",
                    "course_requires_suffix": True,
                    "candidate_suffixes": course_suffixes,
                },
            )
        suffix_filtered = [
            row
            for row in by_course
            if _coerce_text(_course_parse_from_payload(row.event_payload).get("suffix")) == incoming_suffix
        ]
        if not suffix_filtered:
            return _candidate(
                rule_reason="suffix_mismatch",
                candidate_entity_uid=_pick_candidate_uid(by_course),
                evidence={
                    "course_key": f"{incoming_dept}{incoming_number}",
                    "course_requires_suffix": True,
                    "incoming_suffix": incoming_suffix,
                    "candidate_suffixes": course_suffixes,
                },
            )

    by_raw_type = [
        row for row in suffix_filtered if _coerce_text(_semantic_parse_from_payload(row.event_payload).get("raw_type")) == incoming_raw_type
    ]
    if not by_raw_type:
        return _candidate(
            rule_reason="no_rule_match",
            candidate_entity_uid=_pick_candidate_uid(suffix_filtered),
            evidence={"incoming_raw_type": incoming_raw_type, "candidate_count": 0},
        )

    ordinal_set = sorted(
        {
            int(value)
            for value in (_semantic_parse_from_payload(row.event_payload).get("ordinal") for row in by_raw_type)
            if isinstance(value, int) and int(value) > 0
        }
    )
    ordinal_filtered = list(by_raw_type)
    if len(ordinal_set) > 1:
        if incoming_ordinal is None:
            return _candidate(
                rule_reason="multi_ordinal_requires_input_ordinal",
                candidate_entity_uid=_pick_candidate_uid(by_raw_type),
                evidence={"incoming_ordinal": None, "candidate_ordinals": ordinal_set},
            )
        ordinal_filtered = [
            row for row in by_raw_type if _semantic_parse_from_payload(row.event_payload).get("ordinal") == incoming_ordinal
        ]
        if not ordinal_filtered:
            return _candidate(
                rule_reason="ordinal_mismatch",
                candidate_entity_uid=_pick_candidate_uid(by_raw_type),
                evidence={"incoming_ordinal": incoming_ordinal, "candidate_ordinals": ordinal_set},
            )
    elif len(ordinal_set) == 1:
        existing_ordinal = ordinal_set[0]
        if incoming_ordinal is not None and incoming_ordinal != existing_ordinal:
            return _candidate(
                rule_reason="ordinal_mismatch",
                candidate_entity_uid=_pick_candidate_uid(by_raw_type),
                evidence={"incoming_ordinal": incoming_ordinal, "candidate_ordinals": ordinal_set},
            )

    unblocked = [row for row in ordinal_filtered if row.entity_uid not in blocked_entity_uids]
    blocked_count = len(ordinal_filtered) - len(unblocked)
    if not unblocked:
        return LinkDecision(
            entity_uid=None,
            status="unlinked",
            score=0.0,
            candidate_entity_uid=None,
            reason_code="blocked",
            score_breakdown={
                "rule_engine": "inventory",
                "rule_reason": "blocked",
                "blocked_candidates": blocked_count,
                "source_id": source.id,
                "external_event_id": external_event_id,
            },
        )
    if len(unblocked) > 1:
        return _candidate(
            rule_reason="multiple_rule_matches",
            candidate_entity_uid=_pick_candidate_uid(unblocked),
            evidence={
                "candidate_count": len(unblocked),
                "blocked_candidates": blocked_count,
                "candidate_entity_uids": sorted({row.entity_uid for row in unblocked}),
            },
        )

    linked_row = unblocked[0]
    return LinkDecision(
        entity_uid=linked_row.entity_uid,
        status="linked",
        score=1.0,
        candidate_entity_uid=linked_row.entity_uid,
        reason_code="auto_link_inventory_rule",
        score_breakdown={
            "rule_engine": "inventory",
            "rule_reason": "linked",
            "course_key": f"{incoming_dept}{incoming_number}",
            "course_requires_suffix": requires_suffix,
            "incoming_suffix": incoming_suffix,
            "incoming_raw_type": incoming_raw_type,
            "incoming_ordinal": incoming_ordinal,
            "blocked_candidates": blocked_count,
        },
    )


def _candidate(*, rule_reason: str, candidate_entity_uid: str | None, evidence: dict, reason_code: str = "score_band") -> LinkDecision:
    payload = {"rule_engine": "inventory", "rule_reason": rule_reason}
    payload.update(evidence)
    return LinkDecision(
        entity_uid=None,
        status="candidate",
        score=0.0,
        candidate_entity_uid=candidate_entity_uid,
        reason_code=reason_code,
        score_breakdown=payload,
    )


def _pick_candidate_uid(observations: list[SourceEventObservation]) -> str | None:
    if not observations:
        return None
    sorted_rows = sorted(
        observations,
        key=lambda row: (
            row.observed_at if isinstance(row.observed_at, datetime) else datetime.min,
            row.id,
        ),
        reverse=True,
    )
    return sorted_rows[0].entity_uid


def _course_key(course_parse: dict) -> tuple[str, int] | None:
    dept = _coerce_text(course_parse.get("dept"))
    number = course_parse.get("number") if isinstance(course_parse.get("number"), int) else None
    if dept is None or number is None:
        return None
    return dept, int(number)


def _course_parse_from_payload(payload: object) -> dict:
    if not isinstance(payload, dict):
        return {}
    semantic_event = payload.get("semantic_event")
    if isinstance(semantic_event, dict):
        return {
            "dept": semantic_event.get("course_dept"),
            "number": semantic_event.get("course_number"),
            "suffix": semantic_event.get("course_suffix"),
            "quarter": semantic_event.get("course_quarter"),
            "year2": semantic_event.get("course_year2"),
        }
    return {}


def _semantic_parse_from_payload(payload: object) -> dict:
    if not isinstance(payload, dict):
        return {}
    semantic_event = payload.get("semantic_event")
    if isinstance(semantic_event, dict):
        return semantic_event
    return {}


def _coerce_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned.lower() if cleaned else None
