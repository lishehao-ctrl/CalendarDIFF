from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.security import require_public_api_key
from app.db.session import get_db
from app.modules.common.deps import get_onboarded_user_or_409
from app.modules.review_links.schemas import (
    LinkBlockDeleteResponse,
    LinkBlockItemResponse,
    LinkCandidateDecisionRequest,
    LinkCandidateDecisionResponse,
    LinkCandidateItemResponse,
)
from app.modules.review_links.service import (
    LinkBlockNotFoundError,
    LinkCandidateDecisionError,
    LinkCandidateNotFoundError,
    decide_link_candidate,
    delete_link_block,
    list_link_blocks,
    list_link_candidates,
)

router = APIRouter(
    prefix="/v2/review-items/link-candidates",
    tags=["review-items"],
    dependencies=[Depends(require_public_api_key)],
)


@router.get("", response_model=list[LinkCandidateItemResponse])
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


@router.post("/{candidate_id}/decisions", response_model=LinkCandidateDecisionResponse)
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


@router.get("/blocks", response_model=list[LinkBlockItemResponse])
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


@router.delete("/blocks/{block_id}", response_model=LinkBlockDeleteResponse)
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
