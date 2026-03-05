from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.logging import sanitize_log_message
from app.db.session import get_db
from app.modules.input_control_plane.router_common import require_owned_source_or_404, require_registered_user_or_409
from app.modules.input_control_plane.schemas import InputSourceCreateRequest, InputSourcePatchRequest, InputSourceResponse
from app.modules.input_control_plane.source_serializers import serialize_source
from app.modules.input_control_plane.sources_service import (
    create_input_source,
    list_input_sources,
    soft_delete_input_source,
    update_input_source,
)

router = APIRouter()


@router.post("/sources", response_model=InputSourceResponse, status_code=status.HTTP_201_CREATED)
def create_source(
    payload: InputSourceCreateRequest,
    db: Session = Depends(get_db),
) -> InputSourceResponse:
    user = require_registered_user_or_409(db)
    try:
        source = create_input_source(db, user=user, payload=payload)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=sanitize_log_message(str(exc))) from exc
    return InputSourceResponse.model_validate(serialize_source(source))


@router.get("/sources", response_model=list[InputSourceResponse])
def list_sources(
    db: Session = Depends(get_db),
) -> list[InputSourceResponse]:
    user = require_registered_user_or_409(db)
    rows = list_input_sources(db, user_id=user.id)
    return [InputSourceResponse.model_validate(serialize_source(row)) for row in rows]


@router.patch("/sources/{source_id}", response_model=InputSourceResponse)
def patch_source(
    source_id: int,
    payload: InputSourcePatchRequest,
    db: Session = Depends(get_db),
) -> InputSourceResponse:
    user = require_registered_user_or_409(db)
    source = require_owned_source_or_404(db=db, user_id=user.id, source_id=source_id)
    try:
        updated = update_input_source(db, source=source, payload=payload)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=sanitize_log_message(str(exc))) from exc
    return InputSourceResponse.model_validate(serialize_source(updated))


@router.delete("/sources/{source_id}", status_code=status.HTTP_200_OK)
def delete_source(
    source_id: int,
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    user = require_registered_user_or_409(db)
    source = require_owned_source_or_404(db=db, user_id=user.id, source_id=source_id)
    soft_delete_input_source(db, source=source)
    return {"deleted": True}


__all__ = ["router"]
