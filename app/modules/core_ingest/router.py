from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import require_api_key
from app.db.session import get_db
from app.modules.core_ingest.service import apply_ingest_result_idempotent, get_ingest_apply_status

router = APIRouter(prefix="/internal/v2", tags=["internal-ingest"], dependencies=[Depends(require_api_key)])


class IngestApplyRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=64)


class IngestApplyResponse(BaseModel):
    request_id: str
    applied: bool
    idempotent_replay: bool
    changes_created: int


class IngestApplyStatusResponse(BaseModel):
    request_id: str
    result_exists: bool
    result_status: str | None
    applied: bool
    applied_at: datetime | None


@router.post("/ingest-results/applications", response_model=IngestApplyResponse)
def apply_ingest_result(
    payload: IngestApplyRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
) -> IngestApplyResponse:
    if not idempotency_key or idempotency_key.strip() != payload.request_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key header must equal request_id",
        )
    try:
        applied = apply_ingest_result_idempotent(db, request_id=payload.request_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return IngestApplyResponse.model_validate(applied)


@router.get("/ingest-results/{request_id}", response_model=IngestApplyStatusResponse)
def get_ingest_result_status(
    request_id: str,
    db: Session = Depends(get_db),
) -> IngestApplyStatusResponse:
    payload = get_ingest_apply_status(db, request_id=request_id)
    return IngestApplyStatusResponse.model_validate(payload)
