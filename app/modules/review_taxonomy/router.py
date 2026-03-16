from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.security import require_public_api_key
from app.db.models.shared import User
from app.db.session import get_db
from app.modules.auth.deps import get_authenticated_user_or_401
from app.modules.core_ingest.course_work_item_family_rebuild import rebuild_user_work_item_state
from app.modules.users.course_raw_types_service import (
    CourseRawTypeValidationError,
    get_course_raw_type,
    list_course_raw_types,
    move_course_raw_type_to_family,
)
from app.modules.users.course_work_item_families_service import (
    CourseWorkItemFamilyValidationError,
    create_course_work_item_family,
    get_course_work_item_family,
    list_course_work_item_families,
    list_known_course_identities,
    update_course_work_item_family,
)
from app.modules.users.schemas import (
    CourseIdentityResponse,
    CourseRawTypeMoveRequest,
    CourseRawTypeMoveResponse,
    CourseRawTypeResponse,
    CourseWorkItemFamilyCoursesResponse,
    CourseWorkItemFamilyCreateRequest,
    CourseWorkItemFamilyResponse,
    CourseWorkItemFamilyStatusResponse,
    CourseWorkItemFamilyUpdateRequest,
)
from app.modules.users.serializers import (
    course_identity_response_payload,
    to_course_family_response,
    to_course_raw_type_response,
)

router = APIRouter(prefix="/review", tags=["review-items"], dependencies=[Depends(require_public_api_key)])


@router.get("/course-work-item-families", response_model=list[CourseWorkItemFamilyResponse])
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


@router.get("/course-work-item-raw-types", response_model=list[CourseRawTypeResponse])
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


@router.post("/course-work-item-raw-types/relink", response_model=CourseRawTypeMoveResponse)
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
    previous_family_id = raw_type.family_id
    try:
        move_course_raw_type_to_family(db, raw_type=raw_type, family=family, commit=True)
        db.refresh(user)
        rebuild_user_work_item_state(
            db,
            user=user,
            course_dept=family.course_dept,
            course_number=family.course_number,
            course_suffix=family.course_suffix,
            course_quarter=family.course_quarter,
            course_year2=family.course_year2,
        )
    except CourseRawTypeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return CourseRawTypeMoveResponse(
        raw_type_id=raw_type.id,
        family_id=raw_type.family_id,
        previous_family_id=previous_family_id,
        **course_identity_response_payload(
            course_dept=family.course_dept,
            course_number=family.course_number,
            course_suffix=family.course_suffix,
            course_quarter=family.course_quarter,
            course_year2=family.course_year2,
        ),
    )


@router.get("/course-work-item-families/courses", response_model=CourseWorkItemFamilyCoursesResponse)
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


@router.post("/course-work-item-families", response_model=CourseWorkItemFamilyResponse, status_code=status.HTTP_201_CREATED)
def post_course_family(
    payload: CourseWorkItemFamilyCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> CourseWorkItemFamilyResponse:
    try:
        row = create_course_work_item_family(
            db,
            user_id=user.id,
            course_dept=payload.course_dept,
            course_number=payload.course_number,
            course_suffix=payload.course_suffix,
            course_quarter=payload.course_quarter,
            course_year2=payload.course_year2,
            canonical_label=payload.canonical_label,
            raw_types=payload.raw_types,
        )
        db.refresh(user)
        rebuild_user_work_item_state(
            db,
            user=user,
            course_dept=payload.course_dept,
            course_number=payload.course_number,
            course_suffix=payload.course_suffix,
            course_quarter=payload.course_quarter,
            course_year2=payload.course_year2,
        )
    except CourseWorkItemFamilyValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return to_course_family_response(row)


@router.patch("/course-work-item-families/{family_id}", response_model=CourseWorkItemFamilyResponse)
def patch_course_family(
    family_id: int,
    payload: CourseWorkItemFamilyUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> CourseWorkItemFamilyResponse:
    family = get_course_work_item_family(db, user_id=user.id, family_id=family_id)
    if family is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="course work item family not found")
    previous_identity = {
        "course_dept": family.course_dept,
        "course_number": family.course_number,
        "course_suffix": family.course_suffix,
        "course_quarter": family.course_quarter,
        "course_year2": family.course_year2,
    }
    try:
        row = update_course_work_item_family(
            db,
            family=family,
            course_dept=payload.course_dept,
            course_number=payload.course_number,
            course_suffix=payload.course_suffix,
            course_quarter=payload.course_quarter,
            course_year2=payload.course_year2,
            canonical_label=payload.canonical_label,
            raw_types=payload.raw_types,
        )
        db.refresh(user)
        if previous_identity != {
            "course_dept": payload.course_dept,
            "course_number": payload.course_number,
            "course_suffix": payload.course_suffix,
            "course_quarter": payload.course_quarter,
            "course_year2": payload.course_year2,
        }:
            rebuild_user_work_item_state(db, user=user, **previous_identity)
        rebuild_user_work_item_state(
            db,
            user=user,
            course_dept=payload.course_dept,
            course_number=payload.course_number,
            course_suffix=payload.course_suffix,
            course_quarter=payload.course_quarter,
            course_year2=payload.course_year2,
        )
    except CourseWorkItemFamilyValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return to_course_family_response(row)


@router.get("/course-work-item-families/status", response_model=CourseWorkItemFamilyStatusResponse)
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


__all__ = ["router"]
