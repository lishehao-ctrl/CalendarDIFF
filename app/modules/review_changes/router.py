from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.security import require_public_api_key
from app.db.session import get_db
from app.modules.auth.deps import get_onboarded_authenticated_user_or_409 as get_onboarded_user_or_409
from app.modules.review_changes.schemas import (
    EvidencePreviewResponse,
    LabelLearningApplyRequest,
    LabelLearningApplyResponse,
    LabelLearningPreviewResponse,
    RawTypeSuggestionDecisionRequest,
    RawTypeSuggestionDecisionResponse,
    RawTypeSuggestionItemResponse,
    ReviewBatchDecisionRequest,
    ReviewBatchDecisionResponse,
    ReviewSummaryResponse,
    ReviewEditApplyResponse,
    ReviewEditContextResponse,
    ReviewEditPreviewResponse,
    ReviewEditRequest,
    ReviewChangeItemResponse,
    ReviewChangeViewRequest,
    ReviewDecisionRequest,
    ReviewDecisionResponse,
)
from app.modules.review_changes.summary_service import get_review_summary
from app.modules.review_changes.change_decision_service import (
    ReviewChangeNotFoundError,
    batch_decide_review_changes,
    decide_review_change,
    mark_review_change_viewed,
)
from app.modules.review_changes.change_listing_service import get_review_change, list_review_changes
from app.modules.review_changes.edit_service import (
    ReviewEditInvalidStateError,
    ReviewEditNotFoundError,
    ReviewEditValidationError,
    apply_review_edit,
    load_review_edit_context,
    preview_review_edit,
)
from app.modules.review_changes.evidence_preview_service import (
    ReviewChangeEvidenceNotFoundError,
    ReviewChangeEvidenceReadError,
    preview_review_change_evidence,
)
from app.modules.review_changes.label_learning_service import (
    LabelLearningNotFoundError,
    LabelLearningValidationError,
    apply_label_learning,
    preview_label_learning,
)
from app.modules.users.course_work_item_families_service import CourseWorkItemFamilyValidationError
from app.modules.review_changes.raw_type_suggestion_service import (
    RawTypeSuggestionNotFoundError,
    RawTypeSuggestionValidationError,
    decide_review_raw_type_suggestion,
    list_review_raw_type_suggestions,
)

router = APIRouter(
    prefix="/review",
    tags=["review-items"],
    dependencies=[Depends(require_public_api_key)],
)


@router.get("/summary", response_model=ReviewSummaryResponse)
def get_review_summary_route(
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> ReviewSummaryResponse:
    payload = get_review_summary(db=db, user_id=user.id)
    return ReviewSummaryResponse(**payload)


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


@router.get("/changes/{change_id}", response_model=ReviewChangeItemResponse)
def get_review_change_item(
    change_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> ReviewChangeItemResponse:
    row = get_review_change(db, user_id=user.id, change_id=change_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review change not found")
    return ReviewChangeItemResponse(**row)


@router.get("/changes/{change_id}/edit-context", response_model=ReviewEditContextResponse)
def get_review_change_edit_context(
    change_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> ReviewEditContextResponse:
    try:
        payload = load_review_edit_context(db=db, user_id=user.id, change_id=change_id)
    except ReviewEditNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ReviewEditValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return ReviewEditContextResponse(**payload)


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
    refreshed = get_review_change(db, user_id=user.id, change_id=row.id)
    if refreshed is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review change not found")
    return ReviewChangeItemResponse(**refreshed)


@router.post("/changes/batch/decisions", response_model=ReviewBatchDecisionResponse)
def post_review_batch_decisions(
    payload: ReviewBatchDecisionRequest,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> ReviewBatchDecisionResponse:
    result = batch_decide_review_changes(
        db=db,
        user_id=user.id,
        decision=payload.decision,
        ids=payload.ids,
        note=payload.note,
    )
    return ReviewBatchDecisionResponse(**result)


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


@router.post("/edits/preview", response_model=ReviewEditPreviewResponse)
def post_review_edit_preview(
    payload: ReviewEditRequest,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> ReviewEditPreviewResponse:
    try:
        preview = preview_review_edit(
            db=db,
            user_id=user.id,
            mode=payload.mode,
            change_id=payload.target.change_id,
            entity_uid=payload.target.entity_uid,
            patch=payload.patch.model_dump(exclude_unset=True),
            reason=payload.reason,
        )
    except ReviewEditNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ReviewEditInvalidStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ReviewEditValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return ReviewEditPreviewResponse(**preview)


@router.post("/changes/{change_id}/label-learning/preview", response_model=LabelLearningPreviewResponse)
def post_label_learning_preview(
    change_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> LabelLearningPreviewResponse:
    try:
        payload = preview_label_learning(db, user_id=user.id, change_id=change_id)
    except ReviewChangeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LabelLearningNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LabelLearningValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return LabelLearningPreviewResponse.model_validate(payload)


@router.post("/changes/{change_id}/label-learning", response_model=LabelLearningApplyResponse)
def post_label_learning_apply(
    change_id: int,
    payload: LabelLearningApplyRequest,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> LabelLearningApplyResponse:
    try:
        result = apply_label_learning(
            db,
            user_id=user.id,
            change_id=change_id,
            mode=payload.mode,
            family_id=payload.family_id,
            canonical_label=payload.canonical_label,
        )
    except ReviewChangeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LabelLearningNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LabelLearningValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except CourseWorkItemFamilyValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return LabelLearningApplyResponse.model_validate(result)


@router.get("/raw-type-suggestions", response_model=list[RawTypeSuggestionItemResponse])
def get_raw_type_suggestions(
    status: str = Query(default="pending"),
    course_dept: str | None = Query(default=None),
    course_number: int | None = Query(default=None),
    course_suffix: str | None = Query(default=None),
    course_quarter: str | None = Query(default=None),
    course_year2: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> list[RawTypeSuggestionItemResponse]:
    rows = list_review_raw_type_suggestions(
        db,
        user_id=user.id,
        status=status,
        course_dept=course_dept,
        course_number=course_number,
        course_suffix=course_suffix,
        course_quarter=course_quarter,
        course_year2=course_year2,
        limit=limit,
        offset=offset,
    )
    return [RawTypeSuggestionItemResponse(**row) for row in rows]


@router.post("/raw-type-suggestions/{suggestion_id}/decisions", response_model=RawTypeSuggestionDecisionResponse)
def post_raw_type_suggestion_decision(
    suggestion_id: int,
    payload: RawTypeSuggestionDecisionRequest,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> RawTypeSuggestionDecisionResponse:
    try:
        result = decide_review_raw_type_suggestion(
            db,
            user_id=user.id,
            suggestion_id=suggestion_id,
            decision=payload.decision,
            note=payload.note,
        )
    except RawTypeSuggestionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RawTypeSuggestionValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return RawTypeSuggestionDecisionResponse(**result)


@router.post("/edits", response_model=ReviewEditApplyResponse)
def post_review_edit_apply(
    payload: ReviewEditRequest,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> ReviewEditApplyResponse:
    try:
        result = apply_review_edit(
            db=db,
            user_id=user.id,
            mode=payload.mode,
            change_id=payload.target.change_id,
            entity_uid=payload.target.entity_uid,
            patch=payload.patch.model_dump(exclude_unset=True),
            reason=payload.reason,
        )
    except ReviewEditNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ReviewEditInvalidStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ReviewEditValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return ReviewEditApplyResponse(**result)
