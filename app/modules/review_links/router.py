from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.security import require_public_api_key
from app.db.session import get_db
from app.modules.common.deps import get_onboarded_user_or_409
from app.modules.review_links.schemas import (
    LinkAlertDecisionRequest,
    LinkAlertDecisionResponse,
    LinkAlertItemResponse,
    LinkBlockDeleteResponse,
    LinkBlockItemResponse,
    LinkCandidateDecisionRequest,
    LinkCandidateDecisionResponse,
    LinkCandidateItemResponse,
    LinkDeleteResponse,
    LinkItemResponse,
    LinkRelinkRequest,
    LinkRelinkResponse,
)
from app.modules.review_links.service import (
    LinkAlertNotFoundError,
    LinkBlockNotFoundError,
    LinkCandidateDecisionError,
    LinkCandidateNotFoundError,
    LinkNotFoundError,
    decide_link_candidate,
    delete_link,
    delete_link_block,
    dismiss_link_alert,
    list_link_blocks,
    list_link_alerts,
    list_link_candidates,
    list_links,
    mark_safe_link_alert,
    relink_observation,
)

router = APIRouter(
    tags=["review-items"],
    dependencies=[Depends(require_public_api_key)],
)
candidate_router = APIRouter(prefix="/v2/review-items/link-candidates")
links_router = APIRouter(prefix="/v2/review-items/links")
alerts_router = APIRouter(prefix="/v2/review-items/link-alerts")


@candidate_router.get("", response_model=list[LinkCandidateItemResponse])
def get_link_candidates(
    status_filter: str = Query(default="pending", alias="status"),
    source_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> list[LinkCandidateItemResponse]:
    normalized_status = status_filter.strip().lower() if isinstance(status_filter, str) else "pending"
    if normalized_status not in {"pending", "approved", "rejected", "all"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="status must be one of: pending, approved, rejected, all",
        )

    rows = list_link_candidates(
        db,
        user_id=user.id,
        status=normalized_status,
        source_id=source_id,
        limit=limit,
        offset=offset,
    )
    return [LinkCandidateItemResponse(**row) for row in rows]


@candidate_router.post("/{candidate_id}/decisions", response_model=LinkCandidateDecisionResponse)
def post_link_candidate_decision(
    candidate_id: int,
    payload: LinkCandidateDecisionRequest,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> LinkCandidateDecisionResponse:
    try:
        row, idempotent, link_row, block_row = decide_link_candidate(
            db,
            user_id=user.id,
            candidate_id=candidate_id,
            decision=payload.decision,
            note=payload.note,
        )
    except LinkCandidateNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LinkCandidateDecisionError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    return LinkCandidateDecisionResponse(
        id=row.id,
        status=row.status.value,
        idempotent=idempotent,
        block_id=block_row.id if block_row is not None else None,
        link_id=link_row.id if link_row is not None else None,
    )


@candidate_router.get("/blocks", response_model=list[LinkBlockItemResponse])
def get_link_blocks(
    source_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> list[LinkBlockItemResponse]:
    rows = list_link_blocks(
        db,
        user_id=user.id,
        source_id=source_id,
        limit=limit,
        offset=offset,
    )
    return [
        LinkBlockItemResponse(
            id=row.id,
            source_id=row.source_id,
            external_event_id=row.external_event_id,
            blocked_entity_uid=row.blocked_entity_uid,
            note=row.note,
            created_at=row.created_at,
        )
        for row in rows
    ]


@candidate_router.delete("/blocks/{block_id}", response_model=LinkBlockDeleteResponse)
def delete_link_block_route(
    block_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> LinkBlockDeleteResponse:
    try:
        row = delete_link_block(db, user_id=user.id, block_id=block_id)
    except LinkBlockNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return LinkBlockDeleteResponse(deleted=True, id=row.id)


@links_router.get("", response_model=list[LinkItemResponse])
def get_links(
    source_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> list[LinkItemResponse]:
    rows = list_links(
        db=db,
        user_id=user.id,
        source_id=source_id,
        limit=limit,
        offset=offset,
    )
    return [LinkItemResponse(**row) for row in rows]


@links_router.delete("/{link_id}", response_model=LinkDeleteResponse)
def delete_link_route(
    link_id: int,
    block: bool = Query(default=True),
    note: str | None = Query(default=None, max_length=512),
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> LinkDeleteResponse:
    try:
        deleted_id, block_row = delete_link(
            db=db,
            user_id=user.id,
            link_id=link_id,
            create_block=block,
            note=note,
        )
    except LinkNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return LinkDeleteResponse(deleted=True, id=deleted_id, block_id=block_row.id if block_row is not None else None)


@links_router.post("/relink", response_model=LinkRelinkResponse)
def post_relink_observation(
    payload: LinkRelinkRequest,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> LinkRelinkResponse:
    try:
        row, cleared = relink_observation(
            db=db,
            user_id=user.id,
            source_id=payload.source_id,
            external_event_id=payload.external_event_id.strip(),
            entity_uid=payload.entity_uid.strip(),
            clear_block=payload.clear_block,
            note=payload.note,
        )
    except LinkCandidateDecisionError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    return LinkRelinkResponse(
        link_id=row.id,
        entity_uid=row.entity_uid,
        source_id=row.source_id,
        external_event_id=row.external_event_id,
        cleared_blocks=cleared,
    )


@alerts_router.get("", response_model=list[LinkAlertItemResponse])
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


@alerts_router.post("/{alert_id}/dismiss", response_model=LinkAlertDecisionResponse)
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


@alerts_router.post("/{alert_id}/mark-safe", response_model=LinkAlertDecisionResponse)
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


router.include_router(candidate_router)
router.include_router(links_router)
router.include_router(alerts_router)
