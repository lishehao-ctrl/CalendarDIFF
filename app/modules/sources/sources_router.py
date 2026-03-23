from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.logging import sanitize_log_message
from app.db.models.shared import User
from app.db.session import get_db
from app.modules.auth.deps import get_authenticated_user_or_401
from app.modules.common.api_errors import api_error_detail
from app.modules.sources.router_common import require_owned_source_or_404
from app.modules.sources.schemas import (
    InputSourceCreateRequest,
    InputSourcePatchRequest,
    InputSourceResponse,
    SourceObservabilityResponse,
    SourceSyncHistoryResponse,
)
from app.modules.sources.source_runtime_state import derive_source_runtime_state
from app.modules.sources.read_service import build_source_read_payload
from app.modules.sources.source_serializers import serialize_source
from app.modules.sources.status_projection import (
    build_source_observability_payload,
    build_source_sync_history_payload,
)
from app.modules.sources.sources_service import (
    GmailSourceAlreadyExistsError,
    IcsSourceAlreadyExistsError,
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
    user: User = Depends(get_authenticated_user_or_401),
) -> InputSourceResponse:
    try:
        source = create_input_source(db, user=user, payload=payload)
    except GmailSourceAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=api_error_detail(
                code="gmail_source_exists",
                message="gmail source already exists for this user",
                message_code="sources.create.gmail_source_exists",
                existing_source_id=exc.source_id,
            ),
        ) from exc
    except IcsSourceAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=api_error_detail(
                code="ics_source_exists",
                message="ics source already exists for this user",
                message_code="sources.create.ics_source_exists",
                existing_source_id=exc.source_id,
            ),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=api_error_detail(
                code="sources_invalid_input",
                message=sanitize_log_message(str(exc)),
                message_code="sources.validation_error",
            ),
        ) from exc
    return InputSourceResponse.model_validate(
        serialize_source(source, runtime_state=derive_source_runtime_state(db, source=source))
    )


@router.get("/sources", response_model=list[InputSourceResponse])
def list_sources(
    status_filter: str = Query(default="active", alias="status"),
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> list[InputSourceResponse]:
    normalized_status = status_filter.strip().lower() if isinstance(status_filter, str) else "active"
    if normalized_status not in {"active", "archived", "all"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=api_error_detail(
                code="sources_invalid_status_filter",
                message="status must be one of: active, archived, all",
                message_code="sources.invalid_status_filter",
            ),
        )
    rows = list_input_sources(db, user_id=user.id, status=normalized_status)
    return [InputSourceResponse.model_validate(build_source_read_payload(db, source=row)) for row in rows]


@router.patch("/sources/{source_id}", response_model=InputSourceResponse)
def patch_source(
    source_id: int,
    payload: InputSourcePatchRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> InputSourceResponse:
    source = require_owned_source_or_404(db=db, user_id=user.id, source_id=source_id)
    try:
        updated = update_input_source(db, source=source, payload=payload)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=api_error_detail(
                code="sources_invalid_patch",
                message=sanitize_log_message(str(exc)),
                message_code="sources.patch.validation_error",
            ),
        ) from exc
    return InputSourceResponse.model_validate(
        serialize_source(updated, runtime_state=derive_source_runtime_state(db, source=updated))
    )


@router.get("/sources/{source_id}/observability", response_model=SourceObservabilityResponse)
def get_source_observability(
    source_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> SourceObservabilityResponse:
    source = require_owned_source_or_404(db=db, user_id=user.id, source_id=source_id)
    return SourceObservabilityResponse.model_validate(
        build_source_observability_payload(db, source_id=source.id)
    )


@router.get("/sources/{source_id}/sync-history", response_model=SourceSyncHistoryResponse)
def get_source_sync_history(
    source_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> SourceSyncHistoryResponse:
    source = require_owned_source_or_404(db=db, user_id=user.id, source_id=source_id)
    return SourceSyncHistoryResponse.model_validate(
        build_source_sync_history_payload(db, source_id=source.id, limit=limit)
    )


@router.delete("/sources/{source_id}", status_code=status.HTTP_200_OK)
def delete_source(
    source_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user_or_401),
) -> dict[str, bool]:
    source = require_owned_source_or_404(db=db, user_id=user.id, source_id=source_id)
    soft_delete_input_source(db, source=source)
    return {"deleted": True}


__all__ = ["router"]
