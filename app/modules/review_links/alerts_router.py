from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.deps import get_onboarded_authenticated_user_or_409 as get_onboarded_user_or_409
from app.modules.review_links.alerts_decision_service import batch_decide_link_alerts, dismiss_link_alert, mark_safe_link_alert
from app.modules.review_links.alerts_errors import LinkAlertNotFoundError
from app.modules.review_links.alerts_query_service import list_link_alerts
from app.modules.review_links.schemas import (
    LinkAlertBatchDecisionRequest,
    LinkAlertBatchDecisionResponse,
    LinkAlertDecisionRequest,
    LinkAlertDecisionResponse,
    LinkAlertItemResponse,
)

router = APIRouter(prefix="/review/link-alerts")


@router.get("", response_model=list[LinkAlertItemResponse])
def get_link_alerts(
    status_filter: str = Query(default="pending", alias="status"),
    source_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> list[LinkAlertItemResponse]:
    normalized_status = status_filter.strip().lower() if isinstance(status_filter, str) else "pending"
    if normalized_status not in {"pending", "dismissed", "marked_safe", "resolved", "all"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="status must be one of: pending, dismissed, marked_safe, resolved, all",
        )
    rows = list_link_alerts(
        db=db,
        user_id=user.id,
        status=normalized_status,
        source_id=source_id,
        limit=limit,
        offset=offset,
    )
    return [LinkAlertItemResponse(**row) for row in rows]


@router.post("/batch/decisions", response_model=LinkAlertBatchDecisionResponse)
def post_link_alert_batch_decisions(
    payload: LinkAlertBatchDecisionRequest,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> LinkAlertBatchDecisionResponse:
    result = batch_decide_link_alerts(
        db=db,
        user_id=user.id,
        decision=payload.decision,
        ids=payload.ids,
        note=payload.note,
    )
    return LinkAlertBatchDecisionResponse(**result)


@router.post("/{alert_id}/dismiss", response_model=LinkAlertDecisionResponse)
def post_link_alert_dismiss(
    alert_id: int,
    payload: LinkAlertDecisionRequest,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> LinkAlertDecisionResponse:
    try:
        row, idempotent = dismiss_link_alert(
            db=db,
            user_id=user.id,
            alert_id=alert_id,
            note=payload.note,
        )
    except LinkAlertNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return LinkAlertDecisionResponse(
        id=row.id,
        status=row.status.value,
        idempotent=idempotent,
        reviewed_at=row.reviewed_at,
        review_note=row.review_note,
    )


@router.post("/{alert_id}/mark-safe", response_model=LinkAlertDecisionResponse)
def post_link_alert_mark_safe(
    alert_id: int,
    payload: LinkAlertDecisionRequest,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> LinkAlertDecisionResponse:
    try:
        row, idempotent = mark_safe_link_alert(
            db=db,
            user_id=user.id,
            alert_id=alert_id,
            note=payload.note,
        )
    except LinkAlertNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return LinkAlertDecisionResponse(
        id=row.id,
        status=row.status.value,
        idempotent=idempotent,
        reviewed_at=row.reviewed_at,
        review_note=row.review_note,
    )


__all__ = ["router"]
