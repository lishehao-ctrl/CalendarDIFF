from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.review import Change, EventLinkAlert, EventLinkAlertStatus, EventLinkCandidate, EventLinkCandidateStatus, ReviewStatus


def get_review_items_summary(
    db: Session,
    *,
    user_id: int,
) -> dict:
    changes_pending = int(
        db.scalar(
            select(func.count(Change.id)).where(
                Change.user_id == user_id,
                Change.review_status == ReviewStatus.PENDING,
            )
        )
        or 0
    )
    link_candidates_pending = int(
        db.scalar(
            select(func.count(EventLinkCandidate.id)).where(
                EventLinkCandidate.user_id == user_id,
                EventLinkCandidate.status == EventLinkCandidateStatus.PENDING,
            )
        )
        or 0
    )
    link_alerts_pending = int(
        db.scalar(
            select(func.count(EventLinkAlert.id)).where(
                EventLinkAlert.user_id == user_id,
                EventLinkAlert.status == EventLinkAlertStatus.PENDING,
            )
        )
        or 0
    )
    return {
        "changes_pending": changes_pending,
        "link_candidates_pending": link_candidates_pending,
        "link_alerts_pending": link_alerts_pending,
        "generated_at": datetime.now(timezone.utc),
    }
