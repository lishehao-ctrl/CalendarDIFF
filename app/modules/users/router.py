from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.security import require_public_api_key
from app.db.models.shared import User
from app.db.session import get_db
from app.modules.auth.deps import get_authenticated_user_or_401
from app.modules.common.course_identity import course_display_name
from app.modules.core_ingest.course_work_item_family_rebuild import rebuild_user_work_item_state
from app.modules.users.course_work_item_families_service import (
    CourseWorkItemFamilyValidationError,
    create_course_work_item_family,
    get_course_work_item_family,
    list_course_work_item_families,
    list_known_course_identities,
    update_course_work_item_family,
)
from app.modules.users.course_raw_types_service import (
    CourseRawTypeValidationError,
    get_course_raw_type,
    list_course_raw_types,
    move_course_raw_type_to_family,
)
from app.modules.users.schemas import (
    CourseIdentityResponse,
    ManualEventMutationResponse,
    ManualEventResponse,
    ManualEventWriteRequest,
    CourseWorkItemFamilyCoursesResponse,
    CourseRawTypeMoveRequest,
    CourseRawTypeMoveResponse,
    CourseRawTypeResponse,
    CourseWorkItemFamilyCreateRequest,
    CourseWorkItemFamilyResponse,
    CourseWorkItemFamilyStatusResponse,
    CourseWorkItemFamilyUpdateRequest,
    UserResponse,
    UserUpdateRequest,
)
from app.modules.users.service import update_current_user
from app.modules.users.manual_events_service import (
    ManualEventNotFoundError,
    ManualEventValidationError,
    create_manual_event,
    delete_manual_event,
    list_manual_events,
    update_manual_event,
)

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
            timezone_source=payload.timezone_source,
            calendar_delay_seconds=payload.calendar_delay_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _to_user_response(updated)


@router.get("/me/course-work-item-families", response_model=list[CourseWorkItemFamilyResponse])
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
    return [_to_course_family_response(row) for row in rows]


@router.get("/me/course-work-item-raw-types", response_model=list[CourseRawTypeResponse])
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
    return [_to_course_raw_type_response(row) for row in rows]


@router.post("/me/course-work-item-raw-types/relink", response_model=CourseRawTypeMoveResponse)
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
        **_course_identity_response_payload(
            course_dept=family.course_dept,
            course_number=family.course_number,
            course_suffix=family.course_suffix,
            course_quarter=family.course_quarter,
            course_year2=family.course_year2,
        ),
    )


@router.get("/me/course-work-item-families/courses", response_model=CourseWorkItemFamilyCoursesResponse)
def get_course_family_courses(
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> CourseWorkItemFamilyCoursesResponse:
    course_rows = list_known_course_identities(db, user_id=user.id)
    if not course_rows:
        course_rows = [
            _course_identity_response_payload(
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
    return _to_course_family_response(row)


@router.get("/me/course-work-item-families/status", response_model=CourseWorkItemFamilyStatusResponse)
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


@router.get("/me/manual-events", response_model=list[ManualEventResponse])
def get_manual_events(
    include_removed: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> list[ManualEventResponse]:
    rows = list_manual_events(db, user_id=user.id, include_removed=include_removed)
    return [ManualEventResponse(**row) for row in rows]


@router.post("/me/manual-events", response_model=ManualEventMutationResponse, status_code=status.HTTP_201_CREATED)
def post_manual_event(
    payload: ManualEventWriteRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> ManualEventMutationResponse:
    try:
        result = create_manual_event(db, user_id=user.id, payload=payload)
    except ManualEventNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ManualEventValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return ManualEventMutationResponse(**result)


@router.patch("/me/manual-events/{entity_uid}", response_model=ManualEventMutationResponse)
def patch_manual_event(
    entity_uid: str,
    payload: ManualEventWriteRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> ManualEventMutationResponse:
    try:
        result = update_manual_event(db, user_id=user.id, entity_uid=entity_uid, payload=payload)
    except ManualEventNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ManualEventValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return ManualEventMutationResponse(**result)


@router.delete("/me/manual-events/{entity_uid}", response_model=ManualEventMutationResponse)
def remove_manual_event(
    entity_uid: str,
    reason: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> ManualEventMutationResponse:
    try:
        result = delete_manual_event(db, user_id=user.id, entity_uid=entity_uid, reason=reason)
    except ManualEventNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ManualEventValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return ManualEventMutationResponse(**result)


def _to_user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        notify_email=user.notify_email,
        timezone_name=user.timezone_name,
        timezone_source=user.timezone_source,
        calendar_delay_seconds=user.calendar_delay_seconds,
        created_at=user.created_at,
    )


def _course_identity_response_payload(
    *,
    course_dept: str,
    course_number: int,
    course_suffix: str | None,
    course_quarter: str | None,
    course_year2: int | None,
) -> dict[str, object]:
    return {
        "course_display": course_display_name(
            course_dept=course_dept,
            course_number=course_number,
            course_suffix=course_suffix,
            course_quarter=course_quarter,
            course_year2=course_year2,
        )
        or "Unknown",
        "course_dept": course_dept,
        "course_number": course_number,
        "course_suffix": course_suffix,
        "course_quarter": course_quarter,
        "course_year2": course_year2,
    }


def _to_course_family_response(row) -> CourseWorkItemFamilyResponse:
    raw_types = []
    if hasattr(row, "raw_types") and isinstance(row.raw_types, list):
        for item in row.raw_types:
            raw = getattr(item, "raw_type", None)
            if isinstance(raw, str) and raw.strip():
                raw_types.append(raw)
    seen = set()
    deduped_raw_types = []
    for item in raw_types:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped_raw_types.append(item)
    return CourseWorkItemFamilyResponse(
        id=row.id,
        canonical_label=row.canonical_label,
        raw_types=deduped_raw_types,
        created_at=row.created_at,
        updated_at=row.updated_at,
        **_course_identity_response_payload(
            course_dept=row.course_dept,
            course_number=row.course_number,
            course_suffix=row.course_suffix,
            course_quarter=row.course_quarter,
            course_year2=row.course_year2,
        ),
    )


def _to_course_raw_type_response(row) -> CourseRawTypeResponse:
    family = row.family
    return CourseRawTypeResponse(
        id=row.id,
        family_id=row.family_id,
        raw_type=row.raw_type,
        created_at=row.created_at,
        updated_at=row.updated_at,
        **_course_identity_response_payload(
            course_dept=family.course_dept if family is not None else "",
            course_number=family.course_number if family is not None else 0,
            course_suffix=family.course_suffix if family is not None else None,
            course_quarter=family.course_quarter if family is not None else None,
            course_year2=family.course_year2 if family is not None else None,
        ),
    )
