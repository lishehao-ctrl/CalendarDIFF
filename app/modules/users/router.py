from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.security import require_public_api_key
from app.db.models.shared import User
from app.db.session import get_db
from app.modules.auth.deps import get_authenticated_user_or_401
from app.modules.core_ingest.course_work_item_family_rebuild import rebuild_user_work_item_state
from app.modules.users.course_work_item_families_service import (
    CourseWorkItemFamilyValidationError,
    create_course_work_item_family,
    delete_course_work_item_family,
    get_course_work_item_family,
    list_course_work_item_families,
    list_known_course_keys,
    update_course_work_item_family,
)
from app.modules.users.schemas import (
    CourseWorkItemFamilyCoursesResponse,
    CourseWorkItemFamilyCreateRequest,
    CourseWorkItemFamilyResponse,
    CourseWorkItemFamilyStatusResponse,
    CourseWorkItemFamilyUpdateRequest,
    UserResponse,
    UserUpdateRequest,
)
from app.modules.users.service import update_current_user

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(require_public_api_key)])


@router.get("/me", response_model=UserResponse)
def get_user(user: User = Depends(get_authenticated_user_or_401)) -> UserResponse:
    return _to_user_response(user)


@router.patch("/me", response_model=UserResponse)
def patch_user(
    payload: UserUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> UserResponse:
    if "notify_email" in payload.model_fields_set and payload.notify_email is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="notify_email cannot be cleared")
    try:
        updated = update_current_user(
            db,
            user=user,
            email=payload.email,
            notify_email=payload.notify_email,
            timezone_name=payload.timezone_name,
            calendar_delay_seconds=payload.calendar_delay_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _to_user_response(updated)


@router.get("/me/course-work-item-families", response_model=list[CourseWorkItemFamilyResponse])
def get_course_families(
    course_key: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> list[CourseWorkItemFamilyResponse]:
    rows = list_course_work_item_families(db, user_id=user.id, course_key=course_key)
    return [_to_course_family_response(row) for row in rows]


@router.get("/me/course-work-item-families/courses", response_model=CourseWorkItemFamilyCoursesResponse)
def get_course_family_courses(
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> CourseWorkItemFamilyCoursesResponse:
    return CourseWorkItemFamilyCoursesResponse(courses=list_known_course_keys(db, user_id=user.id))


@router.post("/me/course-work-item-families", response_model=CourseWorkItemFamilyResponse, status_code=status.HTTP_201_CREATED)
def post_course_family(
    payload: CourseWorkItemFamilyCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> CourseWorkItemFamilyResponse:
    try:
        row = create_course_work_item_family(
            db,
            user_id=user.id,
            course_key=payload.course_key,
            canonical_label=payload.canonical_label,
            aliases=payload.aliases,
        )
        db.refresh(user)
        rebuild_user_work_item_state(db, user=user, course_key=payload.course_key)
    except CourseWorkItemFamilyValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _to_course_family_response(row)


@router.patch("/me/course-work-item-families/{family_id}", response_model=CourseWorkItemFamilyResponse)
def patch_course_family(
    family_id: int,
    payload: CourseWorkItemFamilyUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> CourseWorkItemFamilyResponse:
    family = get_course_work_item_family(db, user_id=user.id, family_id=family_id)
    if family is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="course work item family not found")
    previous_course_key = family.course_key
    try:
        row = update_course_work_item_family(
            db,
            family=family,
            course_key=payload.course_key,
            canonical_label=payload.canonical_label,
            aliases=payload.aliases,
        )
        db.refresh(user)
        if previous_course_key.strip() != payload.course_key.strip():
            rebuild_user_work_item_state(db, user=user, course_key=previous_course_key)
        rebuild_user_work_item_state(db, user=user, course_key=payload.course_key)
    except CourseWorkItemFamilyValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _to_course_family_response(row)


@router.delete("/me/course-work-item-families/{family_id}", status_code=status.HTTP_200_OK)
def delete_course_family(
    family_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> dict[str, bool]:
    family = get_course_work_item_family(db, user_id=user.id, family_id=family_id)
    if family is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="course work item family not found")
    delete_course_work_item_family(db, family=family)
    db.refresh(user)
    rebuild_user_work_item_state(db, user=user, course_key=family.course_key)
    return {"deleted": True}


@router.get("/me/course-work-item-families/status", response_model=CourseWorkItemFamilyStatusResponse)
def get_course_family_status(
    course_key: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> CourseWorkItemFamilyStatusResponse:
    del course_key
    db.refresh(user)
    return CourseWorkItemFamilyStatusResponse(
        state=user.work_item_mappings_state,
        last_rebuilt_at=user.work_item_mappings_last_rebuilt_at,
        last_error=user.work_item_mappings_last_error,
    )


def _to_user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        notify_email=user.notify_email,
        timezone_name=user.timezone_name,
        calendar_delay_seconds=user.calendar_delay_seconds,
        created_at=user.created_at,
    )


def _to_course_family_response(row) -> CourseWorkItemFamilyResponse:
    aliases = row.aliases_json if isinstance(row.aliases_json, list) else []
    return CourseWorkItemFamilyResponse(
        id=row.id,
        course_key=row.course_key,
        canonical_label=row.canonical_label,
        aliases=[alias for alias in aliases if isinstance(alias, str)],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
