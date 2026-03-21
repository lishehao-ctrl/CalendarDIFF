from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.security import require_public_api_key
from app.db.models.shared import User
from app.db.session import get_db
from app.modules.auth.deps import get_authenticated_user_or_401
from app.modules.families.application_service import (
    FamilyApplicationNotFoundError,
    FamilyApplicationValidationError,
    create_family_and_rebuild,
    decide_raw_type_suggestion_and_rebuild,
    relink_raw_type_and_rebuild,
    update_family_and_rebuild,
)
from app.modules.families.family_service import (
    get_course_work_item_family,
    list_course_work_item_families,
    list_known_course_identities,
)
from app.modules.families.raw_type_service import (
    get_course_raw_type,
    list_course_raw_types,
)
from app.modules.families.schemas import (
    CourseIdentityResponse,
    CourseRawTypeMoveRequest,
    CourseRawTypeMoveResponse,
    CourseRawTypeResponse,
    CourseWorkItemFamilyCoursesResponse,
    CourseWorkItemFamilyCreateRequest,
    CourseWorkItemFamilyResponse,
    CourseWorkItemFamilyStatusResponse,
    CourseWorkItemFamilyUpdateRequest,
    RawTypeSuggestionDecisionRequest,
    RawTypeSuggestionDecisionResponse,
    RawTypeSuggestionItemResponse,
)
from app.modules.families.raw_type_suggestion_service import list_raw_type_suggestion_items
from app.modules.families.serializers import (
    course_identity_response_payload,
    to_course_family_response,
    to_course_raw_type_response,
)

router = APIRouter(tags=["families"], dependencies=[Depends(require_public_api_key)])


@router.get("/families", response_model=list[CourseWorkItemFamilyResponse])
def get_course_families(
    course_dept: str | None = Query(default=None),
    course_number: int | None = Query(default=None),
    course_suffix: str | None = Query(default=None),
    course_quarter: str | None = Query(default=None),
    course_year2: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> list[CourseWorkItemFamilyResponse]:
    rows = list_course_work_item_families(
        db,
        user_id=user.id,
        course_dept=course_dept,
        course_number=course_number,
        course_suffix=course_suffix,
        course_quarter=course_quarter,
        course_year2=course_year2,
    )
    return [to_course_family_response(row) for row in rows]


@router.get("/families/raw-types", response_model=list[CourseRawTypeResponse])
def get_course_raw_types(
    course_dept: str | None = Query(default=None),
    course_number: int | None = Query(default=None),
    course_suffix: str | None = Query(default=None),
    course_quarter: str | None = Query(default=None),
    course_year2: int | None = Query(default=None),
    family_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> list[CourseRawTypeResponse]:
    rows = list_course_raw_types(
        db,
        user_id=user.id,
        course_dept=course_dept,
        course_number=course_number,
        course_suffix=course_suffix,
        course_quarter=course_quarter,
        course_year2=course_year2,
        family_id=family_id,
    )
    return [to_course_raw_type_response(row) for row in rows]


@router.post("/families/raw-types/relink", response_model=CourseRawTypeMoveResponse)
def post_course_raw_type_relink(
    payload: CourseRawTypeMoveRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> CourseRawTypeMoveResponse:
    raw_type = get_course_raw_type(db, user_id=user.id, raw_type_id=payload.raw_type_id)
    if raw_type is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="course raw type not found")
    family = get_course_work_item_family(db, user_id=user.id, family_id=payload.family_id)
    if family is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="course work item family not found")
    try:
        moved_raw_type, previous_family_id = relink_raw_type_and_rebuild(
            db,
            user=user,
            raw_type=raw_type,
            family=family,
        )
    except FamilyApplicationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return CourseRawTypeMoveResponse(
        raw_type_id=moved_raw_type.id,
        family_id=moved_raw_type.family_id,
        previous_family_id=previous_family_id,
        **course_identity_response_payload(
            course_dept=family.course_dept,
            course_number=family.course_number,
            course_suffix=family.course_suffix,
            course_quarter=family.course_quarter,
            course_year2=family.course_year2,
        ),
    )


@router.get("/families/courses", response_model=CourseWorkItemFamilyCoursesResponse)
def get_course_family_courses(
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> CourseWorkItemFamilyCoursesResponse:
    course_rows = list_known_course_identities(db, user_id=user.id)
    if not course_rows:
        course_rows = [
            course_identity_response_payload(
                course_dept=row.course_dept,
                course_number=row.course_number,
                course_suffix=row.course_suffix,
                course_quarter=row.course_quarter,
                course_year2=row.course_year2,
            )
            for row in list_course_work_item_families(db, user_id=user.id)
        ]
    courses = [CourseIdentityResponse(**row) for row in course_rows]
    return CourseWorkItemFamilyCoursesResponse(courses=courses)


@router.post("/families", response_model=CourseWorkItemFamilyResponse, status_code=status.HTTP_201_CREATED)
def post_course_family(
    payload: CourseWorkItemFamilyCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> CourseWorkItemFamilyResponse:
    try:
        row = create_family_and_rebuild(
            db,
            user=user,
            course_dept=payload.course_dept,
            course_number=payload.course_number,
            course_suffix=payload.course_suffix,
            course_quarter=payload.course_quarter,
            course_year2=payload.course_year2,
            canonical_label=payload.canonical_label,
            raw_types=payload.raw_types,
        )
    except FamilyApplicationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return to_course_family_response(row)


@router.patch("/families/{family_id}", response_model=CourseWorkItemFamilyResponse)
def patch_course_family(
    family_id: int,
    payload: CourseWorkItemFamilyUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> CourseWorkItemFamilyResponse:
    family = get_course_work_item_family(db, user_id=user.id, family_id=family_id)
    if family is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="course work item family not found")
    try:
        row = update_family_and_rebuild(
            db,
            user=user,
            family=family,
            canonical_label=payload.canonical_label,
            raw_types=payload.raw_types,
        )
    except FamilyApplicationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return to_course_family_response(row)


@router.get("/families/status", response_model=CourseWorkItemFamilyStatusResponse)
def get_course_family_status(
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> CourseWorkItemFamilyStatusResponse:
    db.refresh(user)
    return CourseWorkItemFamilyStatusResponse(
        state=user.work_item_mappings_state,
        last_rebuilt_at=user.work_item_mappings_last_rebuilt_at,
        last_error=user.work_item_mappings_last_error,
    )


@router.get("/families/raw-type-suggestions", response_model=list[RawTypeSuggestionItemResponse])
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
    user: User = Depends(get_authenticated_user_or_401),
) -> list[RawTypeSuggestionItemResponse]:
    rows = list_raw_type_suggestion_items(
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


@router.post("/families/raw-type-suggestions/{suggestion_id}/decisions", response_model=RawTypeSuggestionDecisionResponse)
def post_raw_type_suggestion_decision(
    suggestion_id: int,
    payload: RawTypeSuggestionDecisionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> RawTypeSuggestionDecisionResponse:
    try:
        result = decide_raw_type_suggestion_and_rebuild(
            db,
            user=user,
            suggestion_id=suggestion_id,
            decision=payload.decision,
            note=payload.note,
        )
    except FamilyApplicationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except FamilyApplicationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return RawTypeSuggestionDecisionResponse(**result)


__all__ = ["router"]
