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
    ReviewSourceRef,
    ReviewChangeViewRequest,
    ReviewDecisionRequest,
    ReviewDecisionResponse,
)
from app.modules.review_changes.change_decision_service import (
    ReviewChangeNotFoundError,
    decide_review_change,
    mark_review_change_viewed,
)
from app.modules.review_changes.change_listing_service import list_review_changes
from app.modules.review_changes.evidence_preview_service import (
    ReviewChangeEvidenceNotFoundError,
    ReviewChangeEvidenceReadError,
    preview_review_change_evidence,
)
from app.modules.review_changes.manual_correction_service import (
    ManualCorrectionNotFoundError,
    ManualCorrectionValidationError,
    apply_manual_correction,
    preview_manual_correction,
)

router = APIRouter(
    prefix="/review",
    tags=["review-items"],
    dependencies=[Depends(require_public_api_key)],
)


@router.get("/changes", response_model=list[ReviewChangeItemResponse])
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


@router.patch("/changes/{change_id}/views", response_model=ReviewChangeItemResponse)
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

    sources_raw = row.proposal_sources_json if isinstance(row.proposal_sources_json, list) else []
    sources: list[ReviewSourceRef] = []
    for item in sources_raw:
        if not isinstance(item, dict):
            continue
        source_id_value = item.get("source_id")
        if not isinstance(source_id_value, int):
            continue
        confidence_value = item.get("confidence")
        confidence = float(confidence_value) if isinstance(confidence_value, (int, float)) else None
        sources.append(
            ReviewSourceRef(
                source_id=source_id_value,
                source_kind=item.get("source_kind") if isinstance(item.get("source_kind"), str) else None,
                provider=item.get("provider") if isinstance(item.get("provider"), str) else None,
                external_event_id=item.get("external_event_id") if isinstance(item.get("external_event_id"), str) else None,
                confidence=confidence,
            )
        )
    source_id = None
    for source_ref in sources:
        source_id = source_ref.source_id
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


@router.post("/changes/{change_id}/decisions", response_model=ReviewDecisionResponse)
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


@router.get("/changes/{change_id}/evidence/{side}/preview", response_model=EvidencePreviewResponse)
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
