from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.security import require_api_key
from app.db.models import EmailRuleCandidate, ReviewCandidateStatus
from app.db.session import get_db
from app.modules.review_candidates.schemas import (
    ApplyReviewCandidateRequest,
    ApplyReviewCandidateResponse,
    DismissReviewCandidateRequest,
    DismissReviewCandidateResponse,
    ReviewCandidateResponse,
)
from app.modules.review_candidates.service import (
    ReviewCandidateApplyError,
    ReviewCandidateNotFoundError,
    ReviewCandidateStateError,
    apply_review_candidate,
    dismiss_review_candidate,
    list_review_candidates,
)
from app.modules.users.service import (
    UserNotInitializedError,
    UserOnboardingIncompleteError,
    require_onboarded_user,
    user_onboarding_incomplete_detail,
    user_not_initialized_detail,
)


router = APIRouter(prefix="/v1/review_candidates", tags=["review_candidates"], dependencies=[Depends(require_api_key)])


def _to_response(row: EmailRuleCandidate) -> ReviewCandidateResponse:
    return ReviewCandidateResponse(
        id=row.id,
        user_id=row.user_id,
        input_id=row.input_id,
        gmail_message_id=row.gmail_message_id,
        source_change_id=row.source_change_id,
        status=row.status.value,
        rule_version=row.rule_version,
        confidence=row.confidence,
        proposed_event_type=row.proposed_event_type,
        proposed_due_at=row.proposed_due_at,
        proposed_title=row.proposed_title,
        proposed_course_hint=row.proposed_course_hint,
        reasons=row.reasons if isinstance(row.reasons, list) else [],
        raw_extract=row.raw_extract if isinstance(row.raw_extract, dict) else {},
        subject=row.subject,
        from_header=row.from_header,
        snippet=row.snippet,
        applied_change_id=row.applied_change_id,
        error=row.error,
        created_at=row.created_at,
        updated_at=row.updated_at,
        applied_at=row.applied_at,
        dismissed_at=row.dismissed_at,
    )


def _require_onboarded_user_id(db: Session) -> int:
    try:
        return require_onboarded_user(db).id
    except UserNotInitializedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=user_not_initialized_detail()) from exc
    except UserOnboardingIncompleteError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=user_onboarding_incomplete_detail()) from exc


def _parse_status(raw: str | None) -> ReviewCandidateStatus | None:
    if raw is None:
        return None
    value = raw.strip().lower()
    if not value:
        return None
    mapping = {
        "pending": ReviewCandidateStatus.PENDING,
        "applied": ReviewCandidateStatus.APPLIED,
        "dismissed": ReviewCandidateStatus.DISMISSED,
        "failed": ReviewCandidateStatus.FAILED,
    }
    status_value = mapping.get(value)
    if status_value is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid status filter")
    return status_value


@router.get("", response_model=list[ReviewCandidateResponse])
def get_review_candidates(
    status_filter: str | None = Query(default=None, alias="status"),
    input_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[ReviewCandidateResponse]:
    user_id = _require_onboarded_user_id(db)
    rows = list_review_candidates(
        db,
        user_id=user_id,
        status=_parse_status(status_filter),
        input_id=input_id,
        limit=limit,
        offset=offset,
    )
    return [_to_response(row) for row in rows]


@router.post("/{candidate_id}/apply", response_model=ApplyReviewCandidateResponse)
def post_apply_review_candidate(
    candidate_id: int,
    payload: ApplyReviewCandidateRequest,
    db: Session = Depends(get_db),
) -> ApplyReviewCandidateResponse:
    user_id = _require_onboarded_user_id(db)
    try:
        candidate, change_id, notification_state = apply_review_candidate(
            db,
            user_id=user_id,
            candidate_id=candidate_id,
            target_input_id=payload.target_input_id,
            target_event_uid=payload.target_event_uid,
            applied_due_at=payload.applied_due_at,
            note=payload.note,
        )
    except ReviewCandidateNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ReviewCandidateStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ReviewCandidateApplyError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    return ApplyReviewCandidateResponse(
        candidate=_to_response(candidate),
        applied_change_id=change_id,
        notification_state=notification_state,
    )


@router.post("/{candidate_id}/dismiss", response_model=DismissReviewCandidateResponse)
def post_dismiss_review_candidate(
    candidate_id: int,
    payload: DismissReviewCandidateRequest,
    db: Session = Depends(get_db),
) -> DismissReviewCandidateResponse:
    user_id = _require_onboarded_user_id(db)
    try:
        candidate = dismiss_review_candidate(
            db,
            user_id=user_id,
            candidate_id=candidate_id,
            note=payload.note,
        )
    except ReviewCandidateNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ReviewCandidateStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return DismissReviewCandidateResponse(candidate=_to_response(candidate))
