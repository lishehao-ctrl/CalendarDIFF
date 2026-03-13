from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.core.security import require_internal_service_token
from app.db.models.input import SourceKind
from app.db.models.review import Change, EventEntityLink, EventLinkBlock, EventLinkCandidate, EventLinkCandidateStatus, EventLinkOrigin, ReviewStatus, SourceEventObservation
from app.db.models.shared import IntegrationOutbox, OutboxStatus
from app.db.session import get_db

router = APIRouter(
    prefix="/internal",
    tags=["internal-review-metrics"],
    dependencies=[Depends(require_internal_service_token({"ops", "review"}))],
)


@router.get("/metrics")
def get_review_metrics(db: Session = Depends(get_db)) -> dict[str, object]:
    now = datetime.now(timezone.utc)

    pending_changes = int(db.scalar(select(func.count(Change.id)).where(Change.review_status == ReviewStatus.PENDING)) or 0)
    max_age_seconds_raw = db.scalar(
        select(func.max(func.extract("epoch", func.now() - Change.detected_at))).where(
            Change.review_status == ReviewStatus.PENDING
        )
    )
    pending_backlog_age_seconds_max = float(max_age_seconds_raw or 0.0)
    apply_queue_pending = int(
        db.scalar(
            select(func.count(IntegrationOutbox.id)).where(
                IntegrationOutbox.event_type == "ingest.result.ready",
                IntegrationOutbox.status == OutboxStatus.PENDING,
            )
        )
        or 0
    )
    linker_auto_link_total = int(
        db.scalar(
            select(func.count(EventEntityLink.id)).where(
                EventEntityLink.link_origin == EventLinkOrigin.AUTO,
            )
        )
        or 0
    )
    linker_candidate_total = int(db.scalar(select(func.count(EventLinkCandidate.id))) or 0)
    linker_block_hit_total = int(db.scalar(select(func.count(EventLinkBlock.id))) or 0)
    linker_candidate_decision_approve_total = int(
        db.scalar(
            select(func.count(EventLinkCandidate.id)).where(
                EventLinkCandidate.status == EventLinkCandidateStatus.APPROVED,
            )
        )
        or 0
    )
    linker_candidate_decision_reject_total = int(
        db.scalar(
            select(func.count(EventLinkCandidate.id)).where(
                EventLinkCandidate.status == EventLinkCandidateStatus.REJECTED,
            )
        )
        or 0
    )
    linker_false_link_corrections_total = int(
        db.scalar(
            select(func.count(EventEntityLink.id)).where(
                EventEntityLink.link_origin == EventLinkOrigin.MANUAL_CANDIDATE,
            )
        )
        or 0
    )
    linker_unlinked_total = int(
        db.scalar(
            select(func.count(SourceEventObservation.id)).where(
                SourceEventObservation.source_kind == SourceKind.EMAIL,
                SourceEventObservation.is_active.is_(True),
                ~exists(
                    select(1).where(
                        EventEntityLink.source_id == SourceEventObservation.source_id,
                        EventEntityLink.external_event_id == SourceEventObservation.external_event_id,
                    )
                ),
            )
        )
        or 0
    )
    return {
        "service_name": "review-service",
        "timestamp": now.isoformat(),
        "metrics": {
            "pending_changes": pending_changes,
            "pending_backlog_age_seconds_max": pending_backlog_age_seconds_max,
            "apply_queue_pending": apply_queue_pending,
            "linker_auto_link_total": linker_auto_link_total,
            "linker_candidate_total": linker_candidate_total,
            "linker_unlinked_total": linker_unlinked_total,
            "linker_block_hit_total": linker_block_hit_total,
            "linker_candidate_decision_approve_total": linker_candidate_decision_approve_total,
            "linker_candidate_decision_reject_total": linker_candidate_decision_reject_total,
            "linker_false_link_corrections_total": linker_false_link_corrections_total,
        },
    }
