from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.input import InputSource
from app.db.models.review import EventEntityLink, EventLinkAlertResolution, EventLinkBlock, EventLinkCandidate, EventLinkCandidateReason, EventLinkCandidateStatus, EventLinkOrigin
from app.modules.core_ingest.linking_rules import LinkDecision, decide_inventory_link
from app.modules.review_links.alerts_service import resolve_pending_link_alerts_for_pair

__all__ = [
    "blocked_entity_uid_set",
    "coerce_candidate_reason",
    "find_existing_entity_link",
    "link_gmail_observation_to_entity",
    "resolve_pending_link_candidates_for_pair",
    "upsert_event_entity_link",
    "upsert_link_candidate",
    "with_candidate_evidence",
]


def link_gmail_observation_to_entity(
    *,
    db: Session,
    source: InputSource,
    external_event_id: str,
    course_parse: dict,
    event_parts: dict,
    time_anchor_confidence: float,
    signals: dict,
) -> LinkDecision:
    blocked_entity_uids = blocked_entity_uid_set(
        db=db,
        user_id=source.user_id,
        source_id=source.id,
        external_event_id=external_event_id,
    )
    decision = decide_inventory_link(
        db,
        source=source,
        external_event_id=external_event_id,
        course_parse=course_parse,
        event_parts=event_parts,
        time_anchor_confidence=time_anchor_confidence,
        blocked_entity_uids=blocked_entity_uids,
    )
    breakdown = dict(decision.score_breakdown)
    breakdown["incoming_signals"] = {
        "keywords": signals.get("keywords"),
        "exam_sequence": signals.get("exam_sequence"),
        "instructor_hint": signals.get("instructor_hint"),
        "location_text": signals.get("location_text"),
        "from_header": signals.get("from_header"),
        "thread_id": signals.get("thread_id"),
    }
    return LinkDecision(
        entity_uid=decision.entity_uid,
        status=decision.status,
        score=decision.score,
        candidate_entity_uid=decision.candidate_entity_uid,
        reason_code=decision.reason_code,
        score_breakdown=breakdown,
    )


def find_existing_entity_link(
    *,
    db: Session,
    user_id: int,
    source_id: int,
    external_event_id: str,
) -> EventEntityLink | None:
    return db.scalar(
        select(EventEntityLink).where(
            EventEntityLink.user_id == user_id,
            EventEntityLink.source_id == source_id,
            EventEntityLink.external_event_id == external_event_id,
        )
    )


def upsert_event_entity_link(
    *,
    db: Session,
    source: InputSource,
    external_event_id: str,
    entity_uid: str,
    link_origin: EventLinkOrigin,
    link_score: float,
    signals_json: dict,
) -> EventEntityLink:
    row = find_existing_entity_link(
        db=db,
        user_id=source.user_id,
        source_id=source.id,
        external_event_id=external_event_id,
    )
    if row is None:
        row = EventEntityLink(
            user_id=source.user_id,
            source_id=source.id,
            source_kind=source.source_kind,
            external_event_id=external_event_id,
            entity_uid=entity_uid,
            link_origin=link_origin,
            link_score=float(link_score),
            signals_json=signals_json or None,
        )
        db.add(row)
        return row

    row.source_kind = source.source_kind
    row.entity_uid = entity_uid
    row.link_origin = link_origin
    row.link_score = float(link_score)
    row.signals_json = signals_json or None
    return row


def resolve_pending_link_candidates_for_pair(
    *,
    db: Session,
    user_id: int,
    source_id: int,
    external_event_id: str,
    note: str,
) -> None:
    now = datetime.now(timezone.utc)
    rows = db.scalars(
        select(EventLinkCandidate).where(
            EventLinkCandidate.user_id == user_id,
            EventLinkCandidate.source_id == source_id,
            EventLinkCandidate.external_event_id == external_event_id,
            EventLinkCandidate.status == EventLinkCandidateStatus.PENDING,
        )
    ).all()
    for row in rows:
        row.status = EventLinkCandidateStatus.APPROVED
        row.reviewed_at = now
        row.review_note = note[:512]
        row.reviewed_by_user_id = None


def upsert_link_candidate(
    *,
    db: Session,
    user_id: int,
    source_id: int,
    external_event_id: str,
    proposed_entity_uid: str | None,
    score: float,
    score_breakdown: dict,
    reason_code: str,
) -> EventLinkCandidate:
    resolve_pending_link_alerts_for_pair(
        db=db,
        user_id=user_id,
        source_id=source_id,
        external_event_id=external_event_id,
        resolution_code=EventLinkAlertResolution.CANDIDATE_OPENED,
        note="candidate_opened",
    )
    pending_rows = db.scalars(
        select(EventLinkCandidate).where(
            EventLinkCandidate.user_id == user_id,
            EventLinkCandidate.source_id == source_id,
            EventLinkCandidate.external_event_id == external_event_id,
            EventLinkCandidate.status == EventLinkCandidateStatus.PENDING,
        )
    ).all()
    for row in pending_rows:
        if row.proposed_entity_uid == proposed_entity_uid:
            row.score = float(score)
            row.score_breakdown_json = score_breakdown
            row.reason_code = coerce_candidate_reason(reason_code)
            row.review_note = None
            row.reviewed_at = None
            row.reviewed_by_user_id = None
            return row

    row = EventLinkCandidate(
        user_id=user_id,
        source_id=source_id,
        external_event_id=external_event_id,
        proposed_entity_uid=proposed_entity_uid,
        score=float(score),
        score_breakdown_json=score_breakdown,
        reason_code=coerce_candidate_reason(reason_code),
        status=EventLinkCandidateStatus.PENDING,
        reviewed_by_user_id=None,
        reviewed_at=None,
        review_note=None,
    )
    db.add(row)
    return row


def coerce_candidate_reason(value: str) -> EventLinkCandidateReason:
    normalized = (value or "").strip().lower()
    if normalized == EventLinkCandidateReason.NO_TIME_ANCHOR.value:
        return EventLinkCandidateReason.NO_TIME_ANCHOR
    if normalized == EventLinkCandidateReason.LOW_CONFIDENCE.value:
        return EventLinkCandidateReason.LOW_CONFIDENCE
    return EventLinkCandidateReason.SCORE_BAND


def with_candidate_evidence(*, score_breakdown: dict, signals: dict) -> dict:
    payload = dict(score_breakdown)
    payload["incoming_signals"] = {
        "keywords": signals.get("keywords"),
        "exam_sequence": signals.get("exam_sequence"),
        "instructor_hint": signals.get("instructor_hint"),
        "location_text": signals.get("location_text"),
        "from_header": signals.get("from_header"),
        "thread_id": signals.get("thread_id"),
        "title_signature": signals.get("title_signature"),
    }
    return payload


def blocked_entity_uid_set(
    *,
    db: Session,
    user_id: int,
    source_id: int,
    external_event_id: str,
) -> set[str]:
    rows = db.scalars(
        select(EventLinkBlock).where(
            EventLinkBlock.user_id == user_id,
            EventLinkBlock.source_id == source_id,
            EventLinkBlock.external_event_id == external_event_id,
        )
    ).all()
    return {
        row.blocked_entity_uid
        for row in rows
        if isinstance(row.blocked_entity_uid, str) and row.blocked_entity_uid.strip()
    }
