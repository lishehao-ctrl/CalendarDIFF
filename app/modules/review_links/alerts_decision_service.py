from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.review import EventLinkAlert, EventLinkAlertResolution, EventLinkAlertStatus
from app.modules.review_links.alerts_errors import LinkAlertNotFoundError
from app.modules.review_links.common import (
    build_batch_result_error,
    build_batch_result_success,
    dedupe_ids_preserve_order,
    normalize_review_note,
)


def dismiss_link_alert(
    db: Session,
    *,
    user_id: int,
    alert_id: int,
    note: str | None,
) -> tuple[EventLinkAlert, bool]:
    row = db.scalar(
        select(EventLinkAlert)
        .where(
            EventLinkAlert.id == alert_id,
            EventLinkAlert.user_id == user_id,
        )
        .with_for_update()
    )
    if row is None:
        raise LinkAlertNotFoundError("Link alert not found")
    if row.status == EventLinkAlertStatus.DISMISSED:
        return row, True
    if row.status != EventLinkAlertStatus.PENDING:
        return row, True

    now = datetime.now(timezone.utc)
    row.status = EventLinkAlertStatus.DISMISSED
    row.resolution_code = EventLinkAlertResolution.DISMISSED_BY_USER
    row.reviewed_by_user_id = user_id
    row.reviewed_at = now
    row.review_note = normalize_review_note(note)
    db.commit()
    db.refresh(row)
    return row, False


def mark_safe_link_alert(
    db: Session,
    *,
    user_id: int,
    alert_id: int,
    note: str | None,
) -> tuple[EventLinkAlert, bool]:
    row = db.scalar(
        select(EventLinkAlert)
        .where(
            EventLinkAlert.id == alert_id,
            EventLinkAlert.user_id == user_id,
        )
        .with_for_update()
    )
    if row is None:
        raise LinkAlertNotFoundError("Link alert not found")
    if row.status == EventLinkAlertStatus.MARKED_SAFE:
        return row, True
    if row.status != EventLinkAlertStatus.PENDING:
        return row, True

    now = datetime.now(timezone.utc)
    row.status = EventLinkAlertStatus.MARKED_SAFE
    row.resolution_code = EventLinkAlertResolution.MARKED_SAFE_BY_USER
    row.reviewed_by_user_id = user_id
    row.reviewed_at = now
    row.review_note = normalize_review_note(note)
    db.commit()
    db.refresh(row)
    return row, False


def batch_decide_link_alerts(
    db: Session,
    *,
    user_id: int,
    decision: str,
    ids: list[int],
    note: str | None,
) -> dict:
    deduped_ids = dedupe_ids_preserve_order(ids)
    results: list[dict] = []
    succeeded = 0
    for alert_id in deduped_ids:
        try:
            if decision == "dismiss":
                row, idempotent = dismiss_link_alert(
                    db=db,
                    user_id=user_id,
                    alert_id=alert_id,
                    note=note,
                )
            else:
                row, idempotent = mark_safe_link_alert(
                    db=db,
                    user_id=user_id,
                    alert_id=alert_id,
                    note=note,
                )
            results.append(
                build_batch_result_success(
                    item_id=alert_id,
                    status=row.status.value,
                    idempotent=idempotent,
                    extras={
                        "reviewed_at": row.reviewed_at,
                        "review_note": row.review_note,
                        "error_code": None,
                        "error_detail": None,
                    },
                )
            )
            succeeded += 1
        except LinkAlertNotFoundError as exc:
            results.append(
                build_batch_result_error(
                    item_id=alert_id,
                    error_code="not_found",
                    error_detail=str(exc),
                    extras={"reviewed_at": None, "review_note": None},
                )
            )
    failed = len(results) - succeeded
    return {
        "decision": decision,
        "total_requested": len(deduped_ids),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
    }


__all__ = [
    "batch_decide_link_alerts",
    "dismiss_link_alert",
    "mark_safe_link_alert",
]
