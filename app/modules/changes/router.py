from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.security import require_public_api_key
from app.db.session import get_db
from app.modules.auth.deps import get_onboarded_authenticated_user_or_409 as get_onboarded_user_or_409
from app.modules.changes.schemas import (
    ChangeBatchDecisionRequest,
    ChangeBatchDecisionResponse,
    ChangeDecisionRequest,
    ChangeDecisionResponse,
    ChangeEditApplyResponse,
    ChangeEditContextResponse,
    ChangeEditPreviewResponse,
    ChangeEditRequest,
    ChangeItemResponse,
    ChangeViewRequest,
    ChangesWorkbenchSummaryResponse,
    EvidencePreviewResponse,
    LabelLearningApplyRequest,
    LabelLearningApplyResponse,
    LabelLearningPreviewResponse,
)
from app.modules.changes.summary_service import get_changes_workbench_summary
from app.modules.changes.change_decision_service import (
    ChangeNotFoundError,
    batch_decide_changes,
    decide_change,
    mark_change_viewed,
)
from app.modules.changes.change_listing_service import get_change, list_changes
from app.modules.changes.edit_service import (
    ChangeEditInvalidStateError,
    ChangeEditNotFoundError,
    ChangeEditValidationError,
    apply_change_edit,
    load_change_edit_context,
    preview_change_edit,
)
from app.modules.changes.change_evidence_service import (
    ChangeEvidenceNotFoundError,
    ChangeEvidenceReadError,
    preview_change_evidence,
)
from app.modules.changes.label_learning_service import (
    LabelLearningNotFoundError,
    LabelLearningValidationError,
    apply_label_learning,
    preview_label_learning,
)
from app.modules.families.family_service import CourseWorkItemFamilyValidationError

router = APIRouter(
    tags=["changes"],
    dependencies=[Depends(require_public_api_key)],
)


@router.get("/changes/summary", response_model=ChangesWorkbenchSummaryResponse, tags=["changes"])
def get_changes_summary_route(
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> ChangesWorkbenchSummaryResponse:
    payload = get_changes_workbench_summary(db=db, user_id=user.id)
    return ChangesWorkbenchSummaryResponse(**payload)


@router.get("/changes", response_model=list[ChangeItemResponse], tags=["changes"])
def get_changes(
    review_status: str = Query(default="pending"),
    source_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> list[ChangeItemResponse]:
    normalized_status = review_status.strip().lower() if isinstance(review_status, str) else "pending"
    if normalized_status not in {"pending", "approved", "rejected", "all"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="review_status must be one of: pending, approved, rejected, all",
        )

    rows = list_changes(
        db,
        user_id=user.id,
        review_status=normalized_status,
        source_id=source_id,
        limit=limit,
        offset=offset,
    )
    return [ChangeItemResponse(**row) for row in rows]


@router.get("/changes/{change_id}", response_model=ChangeItemResponse, tags=["changes"])
def get_change_item(
    change_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> ChangeItemResponse:
    row = get_change(db, user_id=user.id, change_id=change_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review change not found")
    return ChangeItemResponse(**row)


@router.get("/changes/{change_id}/edit-context", response_model=ChangeEditContextResponse, tags=["changes"])
def get_change_edit_context(
    change_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> ChangeEditContextResponse:
    try:
        payload = load_change_edit_context(db=db, user_id=user.id, change_id=change_id)
    except ChangeEditNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ChangeEditValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return ChangeEditContextResponse(**payload)


@router.patch("/changes/{change_id}/views", response_model=ChangeItemResponse, tags=["changes"])
def patch_change_view(
    change_id: int,
    payload: ChangeViewRequest,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> ChangeItemResponse:
    try:
        row = mark_change_viewed(
            db,
            user_id=user.id,
            change_id=change_id,
            viewed=payload.viewed,
            note=payload.note,
        )
    except ChangeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    refreshed = get_change(db, user_id=user.id, change_id=row.id)
    if refreshed is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review change not found")
    return ChangeItemResponse(**refreshed)


@router.post("/changes/batch/decisions", response_model=ChangeBatchDecisionResponse, tags=["changes"])
def post_change_batch_decisions(
    payload: ChangeBatchDecisionRequest,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> ChangeBatchDecisionResponse:
    result = batch_decide_changes(
        db=db,
        user_id=user.id,
        decision=payload.decision,
        ids=payload.ids,
        note=payload.note,
    )
    return ChangeBatchDecisionResponse(**result)


@router.post("/changes/{change_id}/decisions", response_model=ChangeDecisionResponse, tags=["changes"])
def post_change_decision(
    change_id: int,
    payload: ChangeDecisionRequest,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> ChangeDecisionResponse:
    try:
        row, idempotent = decide_change(
            db,
            user_id=user.id,
            change_id=change_id,
            decision=payload.decision,
            note=payload.note,
        )
    except ChangeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return ChangeDecisionResponse(
        id=row.id,
        review_status=row.review_status.value,
        reviewed_at=row.reviewed_at,
        review_note=row.review_note,
        idempotent=idempotent,
    )


@router.get("/changes/{change_id}/evidence/{side}/preview", response_model=EvidencePreviewResponse, tags=["changes"])
def get_change_evidence_preview(
    change_id: int,
    side: Literal["before", "after"],
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> EvidencePreviewResponse:
    try:
        preview = preview_change_evidence(
            db,
            user_id=user.id,
            change_id=change_id,
            side=side,
        )
    except ChangeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ChangeEvidenceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ChangeEvidenceReadError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return EvidencePreviewResponse(**preview)


@router.post("/changes/edits/preview", response_model=ChangeEditPreviewResponse, tags=["changes"])
def post_change_edit_preview(
    payload: ChangeEditRequest,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> ChangeEditPreviewResponse:
    try:
        preview = preview_change_edit(
            db=db,
            user_id=user.id,
            mode=payload.mode,
            change_id=payload.target.change_id,
            entity_uid=payload.target.entity_uid,
            patch=payload.patch.model_dump(exclude_unset=True),
            reason=payload.reason,
        )
    except ChangeEditNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ChangeEditInvalidStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ChangeEditValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return ChangeEditPreviewResponse(**preview)


@router.post("/changes/{change_id}/label-learning/preview", response_model=LabelLearningPreviewResponse, tags=["changes"])
def post_label_learning_preview(
    change_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> LabelLearningPreviewResponse:
    try:
        payload = preview_label_learning(db, user_id=user.id, change_id=change_id)
    except ChangeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LabelLearningNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LabelLearningValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return LabelLearningPreviewResponse.model_validate(payload)


@router.post("/changes/{change_id}/label-learning", response_model=LabelLearningApplyResponse, tags=["changes"])
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
    except ChangeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LabelLearningNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LabelLearningValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except CourseWorkItemFamilyValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return LabelLearningApplyResponse.model_validate(result)


@router.post("/changes/edits", response_model=ChangeEditApplyResponse, tags=["changes"])
def post_change_edit_apply(
    payload: ChangeEditRequest,
    db: Session = Depends(get_db),
    user=Depends(get_onboarded_user_or_409),
) -> ChangeEditApplyResponse:
    try:
        result = apply_change_edit(
            db=db,
            user_id=user.id,
            mode=payload.mode,
            change_id=payload.target.change_id,
            entity_uid=payload.target.entity_uid,
            patch=payload.patch.model_dump(exclude_unset=True),
            reason=payload.reason,
        )
    except ChangeEditNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ChangeEditInvalidStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ChangeEditValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return ChangeEditApplyResponse(**result)
