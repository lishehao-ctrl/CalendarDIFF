from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.security import require_public_api_key
from app.db.session import get_db
from app.modules.common.deps import get_onboarded_user_or_409
from app.modules.emails.schemas import (
    EmailQueueItemResponse,
    MarkEmailViewedResponse,
    UpdateEmailRouteRequest,
    UpdateEmailRouteResponse,
)
from app.modules.emails.service import (
    EmailQueueItemNotFoundError,
    list_email_queue,
    mark_email_viewed,
    update_email_route,
)

router = APIRouter(prefix="/v2/review-items/emails", tags=["review-items"], dependencies=[Depends(require_public_api_key)])


def _parse_offset_cursor(cursor: str | None) -> int:
    if cursor is None or not cursor.strip():
        return 0
    try:
        value = int(cursor)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="cursor must be an integer offset") from exc
    if value < 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="cursor must be >= 0")
    return value


def _parse_route_filter(route: str | None) -> str | None:
    if route is None:
        return "review"
    value = route.strip().lower()
    if value in {"drop", "archive", "review"}:
        return value
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="route must be one of: drop, archive, review")


@router.get("", response_model=list[EmailQueueItemResponse])
def get_email_queue(
    route: str | None = Query(default="review"),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> list[EmailQueueItemResponse]:
    rows = list_email_queue(
        db,
        user_id=user.id,
        route=_parse_route_filter(route),
        limit=limit,
        offset=_parse_offset_cursor(cursor),
    )
    return [EmailQueueItemResponse(**row) for row in rows]


@router.patch("/{email_id}", response_model=UpdateEmailRouteResponse)
def post_email_route(
    email_id: str,
    payload: UpdateEmailRouteRequest,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> UpdateEmailRouteResponse:
    try:
        route_row = update_email_route(
            db,
            user_id=user.id,
            email_id=email_id,
            route=payload.route,
        )
    except EmailQueueItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return UpdateEmailRouteResponse(
        email_id=route_row.email_id,
        route=route_row.route,  # type: ignore[arg-type]
        routed_at=route_row.routed_at,
        notified_at=route_row.notified_at,
    )


@router.post("/{email_id}/views", response_model=MarkEmailViewedResponse)
def post_mark_email_viewed(
    email_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> MarkEmailViewedResponse:
    try:
        route_row = mark_email_viewed(
            db,
            user_id=user.id,
            email_id=email_id,
        )
    except EmailQueueItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    assert route_row.viewed_at is not None
    return MarkEmailViewedResponse(email_id=route_row.email_id, viewed_at=route_row.viewed_at)
