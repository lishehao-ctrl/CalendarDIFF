from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.security import require_public_api_key
from app.db.session import get_db
from app.modules.common.deps import get_onboarded_user_or_409
from app.modules.review_changes.schemas import (
    EvidencePreviewResponse,
    ManualCorrectionApplyResponse,
    ManualCorrectionPreviewResponse,
    ManualCorrectionRequest,
    ReviewChangeItemResponse,
    ReviewChangeViewRequest,
    ReviewDecisionRequest,
    ReviewDecisionResponse,
)
from app.modules.review_changes.service import (
    ManualCorrectionNotFoundError,
    ReviewChangeEvidenceNotFoundError,
    ReviewChangeEvidenceReadError,
    ManualCorrectionValidationError,
    ReviewChangeNotFoundError,
    apply_manual_correction,
    decide_review_change,
    list_review_changes,
    mark_review_change_viewed,
    preview_review_change_evidence,
    preview_manual_correction,
)

router = APIRouter(
    prefix="/v2/review-items/changes",
    tags=["review-items"],
    dependencies=[Depends(require_public_api_key)],
)


@router.get("", response_model=list[ReviewChangeItemResponse])
def get_review_changes(
    review_status: str = Query(default="pending"),
    source_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> list[ReviewChangeItemResponse]:
    normalized_status = review_status.strip().lower() if isinstance(review_status, str) else "pending"
    if normalized_status not in {"pending", "approved", "rejected", "all"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="review_status must be one of: pending, approved, rejected, all",
        )

    rows = list_review_changes(
        db,
        user_id=user.id,
        review_status=normalized_status,
        source_id=source_id,
        limit=limit,
        offset=offset,
    )
    return [ReviewChangeItemResponse(**row) for row in rows]


@router.patch("/{change_id}/views", response_model=ReviewChangeItemResponse)
def patch_review_change_view(
    change_id: int,
    payload: ReviewChangeViewRequest,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> ReviewChangeItemResponse:
    try:
        row = mark_review_change_viewed(
            db,
            user_id=user.id,
            change_id=change_id,
            viewed=payload.viewed,
            note=payload.note,
        )
    except ReviewChangeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    sources = row.proposal_sources_json if isinstance(row.proposal_sources_json, list) else []
    source_id = None
    for item in sources:
        if isinstance(item, dict) and isinstance(item.get("source_id"), int):
            source_id = item["source_id"]
            break

    return ReviewChangeItemResponse(
        id=row.id,
        event_uid=row.event_uid,
        change_type=row.change_type.value,
        detected_at=row.detected_at,
        review_status=row.review_status.value,
        before_json=row.before_json,
        after_json=row.after_json,
        proposal_merge_key=row.proposal_merge_key,
        proposal_sources=sources,
        source_id=source_id,
        viewed_at=row.viewed_at,
        viewed_note=row.viewed_note,
        reviewed_at=row.reviewed_at,
        review_note=row.review_note,
    )


@router.post("/{change_id}/decisions", response_model=ReviewDecisionResponse)
def post_review_decision(
    change_id: int,
    payload: ReviewDecisionRequest,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> ReviewDecisionResponse:
    try:
        row, idempotent = decide_review_change(
            db,
            user_id=user.id,
            change_id=change_id,
            decision=payload.decision,
            note=payload.note,
        )
    except ReviewChangeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return ReviewDecisionResponse(
        id=row.id,
        review_status=row.review_status.value,
        reviewed_at=row.reviewed_at,
        review_note=row.review_note,
        idempotent=idempotent,
    )


@router.get("/{change_id}/evidence/{side}/preview", response_model=EvidencePreviewResponse)
def get_review_change_evidence_preview(
    change_id: int,
    side: Literal["before", "after"],
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> EvidencePreviewResponse:
    try:
        preview = preview_review_change_evidence(
            db,
            user_id=user.id,
            change_id=change_id,
            side=side,
        )
    except ReviewChangeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ReviewChangeEvidenceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ReviewChangeEvidenceReadError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return EvidencePreviewResponse(**preview)


@router.post("/corrections/preview", response_model=ManualCorrectionPreviewResponse)
def post_manual_correction_preview(
    payload: ManualCorrectionRequest,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> ManualCorrectionPreviewResponse:
    try:
        preview = preview_manual_correction(
            db=db,
            user_id=user.id,
            change_id=payload.target.change_id,
            event_uid=payload.target.event_uid,
            due_at=payload.patch.due_at,
            title=payload.patch.title,
            course_label=payload.patch.course_label,
            reason=payload.reason,
        )
    except ManualCorrectionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ManualCorrectionValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return ManualCorrectionPreviewResponse(**preview)


@router.post("/corrections", response_model=ManualCorrectionApplyResponse)
def post_manual_correction_apply(
    payload: ManualCorrectionRequest,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> ManualCorrectionApplyResponse:
    try:
        result = apply_manual_correction(
            db=db,
            user_id=user.id,
            change_id=payload.target.change_id,
            event_uid=payload.target.event_uid,
            due_at=payload.patch.due_at,
            title=payload.patch.title,
            course_label=payload.patch.course_label,
            reason=payload.reason,
        )
    except ManualCorrectionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ManualCorrectionValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return ManualCorrectionApplyResponse(**result)
