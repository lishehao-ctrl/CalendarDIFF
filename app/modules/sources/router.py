from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.logging import sanitize_log_message
from app.core.security import require_api_key
from app.db.models import Source
from app.db.session import get_db
from app.modules.sources.schemas import (
    CourseDeadlinesResponse,
    DeadlineItemResponse,
    ManualSyncResponse,
    SourceCreateRequest,
    SourceDeadlinesPreviewResponse,
    SourceResponse,
)
from app.modules.sources.service import (
    create_ics_source,
    get_source_by_id,
    list_sources,
    preview_source_deadlines,
    run_manual_sync,
)

router = APIRouter(prefix="/v1/sources", tags=["sources"], dependencies=[Depends(require_api_key)])
logger = logging.getLogger(__name__)


@router.post("/ics", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
def create_source(payload: SourceCreateRequest, db: Session = Depends(get_db)) -> SourceResponse:
    source = create_ics_source(db, payload)
    return _to_response(source)


@router.get("", response_model=list[SourceResponse])
def get_sources(db: Session = Depends(get_db)) -> list[SourceResponse]:
    sources = list_sources(db)
    return [_to_response(source) for source in sources]


@router.post("/{source_id}/sync", response_model=ManualSyncResponse)
def sync_source_now(source_id: int, db: Session = Depends(get_db)) -> ManualSyncResponse:
    source = get_source_by_id(db, source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")

    result = run_manual_sync(db, source)
    return ManualSyncResponse(
        source_id=result.source_id,
        changes_created=result.changes_created,
        email_sent=result.email_sent,
        last_error=result.last_error,
    )


@router.get("/{source_id}/deadlines", response_model=SourceDeadlinesPreviewResponse)
def get_source_deadlines(source_id: int, db: Session = Depends(get_db)) -> SourceDeadlinesPreviewResponse:
    source = get_source_by_id(db, source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")

    try:
        preview = preview_source_deadlines(source=source)
    except Exception as exc:
        logger.error("failed to preview source_id=%s deadlines error=%s", source_id, sanitize_log_message(str(exc)))
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to fetch or parse ICS feed") from exc

    return SourceDeadlinesPreviewResponse(
        source_id=preview.source_id,
        source_name=preview.source_name,
        fetched_at_utc=preview.fetched_at_utc,
        total_deadlines=preview.total_deadlines,
        courses=[
            CourseDeadlinesResponse(
                course_label=course_group.course_label,
                deadlines=[
                    DeadlineItemResponse(
                        uid=item.uid,
                        title=item.title,
                        ddl_type=item.ddl_type.value,
                        start_at_utc=item.start_at_utc,
                        end_at_utc=item.end_at_utc,
                    )
                    for item in course_group.deadlines
                ],
            )
            for course_group in preview.courses
        ],
    )


def _to_response(source: Source) -> SourceResponse:
    return SourceResponse(
        id=source.id,
        user_id=source.user_id,
        type=source.type.value,
        name=source.name,
        interval_minutes=source.interval_minutes,
        is_active=source.is_active,
        last_checked_at=source.last_checked_at,
        last_error=source.last_error,
        created_at=source.created_at,
    )
