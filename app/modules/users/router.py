from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import require_public_api_key
from app.db.models.shared import User
from app.db.session import get_db
from app.modules.auth.deps import get_authenticated_user_or_401
from app.modules.core_ingest.work_item_kind_rebuild import rebuild_user_work_item_state
from app.modules.users.schemas import (
    UserResponse,
    UserUpdateRequest,
    WorkItemKindMappingCreateRequest,
    WorkItemKindMappingResponse,
    WorkItemKindMappingStatusResponse,
    WorkItemKindMappingUpdateRequest,
)
from app.modules.users.service import update_current_user
from app.modules.users.work_item_kind_mappings_service import (
    WorkItemKindMappingNotFoundError,
    WorkItemKindMappingValidationError,
    create_user_work_item_kind_mapping,
    delete_user_work_item_kind_mapping,
    ensure_default_work_item_kind_mappings,
    get_user_work_item_kind_mapping,
    list_user_work_item_kind_mappings,
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
            calendar_delay_seconds=payload.calendar_delay_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _to_user_response(updated)


@router.get("/me/work-item-kind-mappings", response_model=list[WorkItemKindMappingResponse])
def get_work_item_kind_mappings(
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> list[WorkItemKindMappingResponse]:
    ensure_default_work_item_kind_mappings(db, user_id=user.id)
    rows = list_user_work_item_kind_mappings(db, user_id=user.id)
    return [_to_work_item_kind_mapping_response(row) for row in rows]


@router.post("/me/work-item-kind-mappings", response_model=WorkItemKindMappingResponse, status_code=status.HTTP_201_CREATED)
def post_work_item_kind_mapping(
    payload: WorkItemKindMappingCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> WorkItemKindMappingResponse:
    try:
        row = create_user_work_item_kind_mapping(db, user_id=user.id, name=payload.name, aliases=payload.aliases)
        db.refresh(user)
        rebuild_user_work_item_state(db, user=user)
    except WorkItemKindMappingValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _to_work_item_kind_mapping_response(row)


@router.patch("/me/work-item-kind-mappings/{mapping_id}", response_model=WorkItemKindMappingResponse)
def patch_work_item_kind_mapping(
    mapping_id: int,
    payload: WorkItemKindMappingUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> WorkItemKindMappingResponse:
    mapping = get_user_work_item_kind_mapping(db, user_id=user.id, mapping_id=mapping_id)
    if mapping is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="work item kind mapping not found")
    try:
        from app.modules.users.work_item_kind_mappings_service import update_user_work_item_kind_mapping
        row = update_user_work_item_kind_mapping(db, mapping=mapping, name=payload.name, aliases=payload.aliases)
        db.refresh(user)
        rebuild_user_work_item_state(db, user=user)
    except WorkItemKindMappingValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _to_work_item_kind_mapping_response(row)


@router.delete("/me/work-item-kind-mappings/{mapping_id}", status_code=status.HTTP_200_OK)
def remove_work_item_kind_mapping(
    mapping_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> dict[str, bool]:
    mapping = get_user_work_item_kind_mapping(db, user_id=user.id, mapping_id=mapping_id)
    if mapping is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="work item kind mapping not found")
    delete_user_work_item_kind_mapping(db, mapping=mapping)
    db.refresh(user)
    rebuild_user_work_item_state(db, user=user)
    return {"deleted": True}


@router.get("/me/work-item-kind-mappings/status", response_model=WorkItemKindMappingStatusResponse)
def get_work_item_kind_mapping_status(
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> WorkItemKindMappingStatusResponse:
    ensure_default_work_item_kind_mappings(db, user_id=user.id)
    db.refresh(user)
    return WorkItemKindMappingStatusResponse(
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


def _to_work_item_kind_mapping_response(row) -> WorkItemKindMappingResponse:
    aliases = row.aliases_json if isinstance(row.aliases_json, list) else []
    return WorkItemKindMappingResponse(
        id=row.id,
        name=row.name,
        aliases=[alias for alias in aliases if isinstance(alias, str)],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
