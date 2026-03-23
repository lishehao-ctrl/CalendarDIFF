from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.security import require_public_api_key
from app.db.models.shared import User
from app.db.session import get_db
from app.modules.auth.deps import get_authenticated_user_or_401
from app.modules.common.api_errors import api_error_detail
from app.modules.manual.schemas import ManualEventMutationResponse, ManualEventResponse, ManualEventWriteRequest
from app.modules.manual.service import (
    ManualEventNotFoundError,
    ManualEventValidationError,
    create_manual_event,
    delete_manual_event,
    list_manual_events,
    update_manual_event,
)

router = APIRouter(prefix="/manual", tags=["manual"], dependencies=[Depends(require_public_api_key)])


@router.get("/events", response_model=list[ManualEventResponse])
def get_manual_events(
    include_removed: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> list[ManualEventResponse]:
    rows = list_manual_events(db, user_id=user.id, include_removed=include_removed)
    return [ManualEventResponse(**row) for row in rows]


@router.post("/events", response_model=ManualEventMutationResponse, status_code=status.HTTP_201_CREATED)
def post_manual_event(
    payload: ManualEventWriteRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> ManualEventMutationResponse:
    try:
        result = create_manual_event(db, user_id=user.id, payload=payload)
    except ManualEventNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=api_error_detail(
                code="manual.family_not_found",
                message=str(exc),
                message_code="manual.family_not_found",
            ),
        ) from exc
    except ManualEventValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=api_error_detail(
                code="manual.create.validation_error",
                message=str(exc),
                message_code="manual.create.validation_error",
            ),
        ) from exc
    return ManualEventMutationResponse(**result)


@router.patch("/events/{entity_uid}", response_model=ManualEventMutationResponse)
def patch_manual_event(
    entity_uid: str,
    payload: ManualEventWriteRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> ManualEventMutationResponse:
    try:
        result = update_manual_event(db, user_id=user.id, entity_uid=entity_uid, payload=payload)
    except ManualEventNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=api_error_detail(
                code="manual.event_or_family_not_found",
                message=str(exc),
                message_code="manual.event_or_family_not_found",
            ),
        ) from exc
    except ManualEventValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=api_error_detail(
                code="manual.update.validation_error",
                message=str(exc),
                message_code="manual.update.validation_error",
            ),
        ) from exc
    return ManualEventMutationResponse(**result)


@router.delete("/events/{entity_uid}", response_model=ManualEventMutationResponse)
def remove_manual_event(
    entity_uid: str,
    reason: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> ManualEventMutationResponse:
    try:
        result = delete_manual_event(db, user_id=user.id, entity_uid=entity_uid, reason=reason)
    except ManualEventNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=api_error_detail(
                code="manual.event_not_found",
                message=str(exc),
                message_code="manual.event_not_found",
            ),
        ) from exc
    except ManualEventValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=api_error_detail(
                code="manual.delete.validation_error",
                message=str(exc),
                message_code="manual.delete.validation_error",
            ),
        ) from exc
    return ManualEventMutationResponse(**result)


__all__ = ["router"]
