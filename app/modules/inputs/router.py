from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.core.logging import sanitize_log_message
from app.core.security import require_api_key
from app.db.models import Change, Snapshot
from app.db.session import get_db
from app.modules.changes.schemas import ChangeResponse, ChangeViewedUpdateRequest
from app.modules.evidence import EvidencePathError, resolve_evidence_file_path
from app.modules.inputs.presenters import to_input_create_response, to_input_response, to_input_run_response
from app.modules.inputs.schemas import (
    CourseDeadlinesResponse,
    DeadlineItemResponse,
    GmailOAuthStartRequest,
    GmailOAuthStartResponse,
    InputCourseOverrideResponse,
    InputCreateRequest,
    InputCreateResponse,
    InputDeadlinesPreviewResponse,
    InputOverridesResponse,
    InputResponse,
    InputRunResponse,
    InputTaskOverrideResponse,
    ManualInputSyncResponse,
)
from app.modules.inputs.service import (
    InputBusyError,
    InputReplaceConflictError,
    build_gmail_oauth_start,
    create_ics_input,
    get_input_by_id,
    list_input_runs,
    list_inputs_with_runtime_state,
    preview_input_deadlines,
    run_manual_input_sync,
)
from app.modules.overrides.schemas import CourseRenameRequest, TaskRenameRequest
from app.modules.overrides.service import (
    delete_course_override,
    delete_task_override,
    list_source_overrides,
    upsert_course_override,
    upsert_task_override,
)
from app.modules.users.service import (
    UserNotInitializedError,
    UserOnboardingIncompleteError,
    require_onboarded_user,
    user_onboarding_incomplete_detail,
    user_not_initialized_detail,
)
from app.modules.snapshots.schemas import SnapshotResponse


def _require_onboarded_user_or_409(db: Session = Depends(get_db)) -> None:
    try:
        require_onboarded_user(db)
    except UserNotInitializedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=user_not_initialized_detail()) from exc
    except UserOnboardingIncompleteError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=user_onboarding_incomplete_detail()) from exc


router = APIRouter(
    prefix="/v1/inputs",
    tags=["inputs"],
    dependencies=[Depends(require_api_key), Depends(_require_onboarded_user_or_409)],
)
logger = logging.getLogger(__name__)


@router.get("", response_model=list[InputResponse])
def list_inputs(db: Session = Depends(get_db)) -> list[InputResponse]:
    rows = list_inputs_with_runtime_state(db)
    return [
        to_input_response(input, next_check_at=next_check_at, last_result=last_result)
        for input, next_check_at, last_result in rows
    ]


@router.post("/ics", response_model=InputCreateResponse, status_code=status.HTTP_201_CREATED)
def create_input_from_ics(
    payload: InputCreateRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> InputCreateResponse:
    user = require_onboarded_user(db)
    try:
        result = create_ics_input(db, user_id=user.id, payload=payload)
    except InputReplaceConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    if result.upserted_existing:
        response.status_code = status.HTTP_200_OK
    return to_input_create_response(result.input, upserted_existing=result.upserted_existing)


@router.post("/email/gmail/oauth/start", response_model=GmailOAuthStartResponse)
def start_input_gmail_oauth(
    payload: GmailOAuthStartRequest,
    db: Session = Depends(get_db),
) -> GmailOAuthStartResponse:
    require_onboarded_user(db)
    try:
        result = build_gmail_oauth_start(
            label=payload.label,
            from_contains=payload.from_contains,
            subject_keywords=payload.subject_keywords,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    return GmailOAuthStartResponse(
        authorization_url=result.authorization_url,
        expires_at=result.expires_at,
    )


@router.post("/{input_id}/sync", response_model=ManualInputSyncResponse)
def sync_input_now(input_id: int, db: Session = Depends(get_db)) -> ManualInputSyncResponse:
    input = get_input_by_id(db, input_id)
    if input is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Input not found")

    try:
        result = run_manual_input_sync(db, input)
    except InputBusyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "status": "LOCK_SKIPPED",
                "code": "source_busy",
                "message": "sync in progress",
                "retry_after_seconds": exc.retry_after_seconds,
                "recoverable": True,
            },
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc

    payload: dict[str, object] = {
        "input_id": result.input_id,
        "changes_created": result.changes_created,
        "email_sent": result.email_sent,
        "last_error": result.last_error,
        "is_baseline_sync": result.is_baseline_sync,
    }
    if result.notification_state is not None:
        payload["notification_state"] = result.notification_state
    return ManualInputSyncResponse.model_validate(payload)


@router.get("/{input_id}/deadlines", response_model=InputDeadlinesPreviewResponse)
def get_input_deadlines(input_id: int, db: Session = Depends(get_db)) -> InputDeadlinesPreviewResponse:
    input = get_input_by_id(db, input_id)
    if input is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Input not found")

    try:
        preview = preview_input_deadlines(input=input)
    except Exception as exc:
        logger.error("failed to preview input_id=%s deadlines error=%s", input_id, sanitize_log_message(str(exc)))
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to fetch or parse ICS feed") from exc

    return InputDeadlinesPreviewResponse(
        input_id=preview.input_id,
        input_label=preview.input_label,
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


@router.get("/{input_id}/runs", response_model=list[InputRunResponse])
def get_input_runs(
    input_id: int,
    limit: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[InputRunResponse]:
    _ensure_input_exists(db, input_id)
    runs = list_input_runs(db, input_id, limit=limit)
    return [to_input_run_response(run) for run in runs]


@router.get("/{input_id}/changes", response_model=list[ChangeResponse])
def list_input_changes(
    input_id: int,
    limit: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[ChangeResponse]:
    _ensure_input_exists(db, input_id)
    settings = get_settings()
    applied_limit = limit or settings.default_changes_limit
    applied_limit = min(applied_limit, settings.max_changes_limit)

    stmt = (
        select(Change)
        .options(joinedload(Change.before_snapshot), joinedload(Change.after_snapshot))
        .where(Change.input_id == input_id)
        .order_by(Change.detected_at.desc(), Change.id.desc())
        .offset(offset)
        .limit(applied_limit)
    )
    rows = db.scalars(stmt).all()
    return [_to_change_response(row) for row in rows]


@router.patch("/{input_id}/changes/{change_id}/viewed", response_model=ChangeResponse)
def mark_input_change_viewed(
    input_id: int,
    change_id: int,
    payload: ChangeViewedUpdateRequest,
    db: Session = Depends(get_db),
) -> ChangeResponse:
    row = db.scalar(
        select(Change)
        .options(joinedload(Change.before_snapshot), joinedload(Change.after_snapshot))
        .where(Change.id == change_id, Change.input_id == input_id)
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Change not found")

    if payload.viewed:
        row.viewed_at = datetime.now(timezone.utc)
        row.viewed_note = payload.note
    else:
        row.viewed_at = None
        row.viewed_note = None

    db.commit()
    db.refresh(row)
    return _to_change_response(row)


@router.get("/{input_id}/changes/{change_id}/evidence/{side}/download")
def download_input_change_evidence(
    input_id: int,
    change_id: int,
    side: Literal["before", "after"],
    db: Session = Depends(get_db),
) -> FileResponse:
    row = db.scalar(
        select(Change)
        .options(joinedload(Change.before_snapshot), joinedload(Change.after_snapshot))
        .where(Change.id == change_id, Change.input_id == input_id)
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Change not found")

    snapshot = row.before_snapshot if side == "before" else row.after_snapshot
    evidence_path = _extract_snapshot_evidence_path(snapshot.raw_evidence_key if snapshot is not None else None)
    if evidence_path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence file not found")

    try:
        resolved = resolve_evidence_file_path(evidence_path)
    except EvidencePathError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence file not found") from None
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.error("failed to resolve evidence path error=%s", sanitize_log_message(str(exc)))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to prepare evidence file")

    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence file not found")

    return FileResponse(
        resolved,
        media_type="text/calendar",
        filename=f"change-{row.id}-{side}.ics",
    )


@router.get("/{input_id}/snapshots", response_model=list[SnapshotResponse])
def list_input_snapshots(
    input_id: int,
    limit: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[SnapshotResponse]:
    _ensure_input_exists(db, input_id)
    settings = get_settings()
    applied_limit = limit or settings.default_changes_limit
    applied_limit = min(applied_limit, settings.max_changes_limit)

    stmt = (
        select(Snapshot)
        .where(Snapshot.input_id == input_id)
        .order_by(Snapshot.retrieved_at.desc(), Snapshot.id.desc())
        .offset(offset)
        .limit(applied_limit)
    )
    rows = db.scalars(stmt).all()
    return [
        SnapshotResponse(
            id=row.id,
            input_id=row.input_id,
            retrieved_at=row.retrieved_at,
            content_hash=row.content_hash,
            event_count=row.event_count,
            raw_evidence_key=row.raw_evidence_key,
        )
        for row in rows
    ]


@router.get("/{input_id}/overrides", response_model=InputOverridesResponse)
def get_input_overrides(input_id: int, db: Session = Depends(get_db)) -> InputOverridesResponse:
    _ensure_input_exists(db, input_id)
    courses, tasks = list_source_overrides(db, input_id)
    return InputOverridesResponse(
        input_id=input_id,
        courses=[_to_course_response(row) for row in courses],
        tasks=[_to_task_response(row) for row in tasks],
    )


@router.put("/{input_id}/courses/rename", response_model=InputCourseOverrideResponse)
def rename_input_course(
    input_id: int,
    payload: CourseRenameRequest,
    db: Session = Depends(get_db),
) -> InputCourseOverrideResponse:
    _ensure_input_exists(db, input_id)
    row = upsert_course_override(
        db=db,
        input_id=input_id,
        original_course_label=payload.original_course_label.strip(),
        display_course_label=payload.display_course_label.strip(),
    )
    return _to_course_response(row)


@router.put("/{input_id}/tasks/{event_uid}/rename", response_model=InputTaskOverrideResponse)
def rename_input_task(
    input_id: int,
    event_uid: str,
    payload: TaskRenameRequest,
    db: Session = Depends(get_db),
) -> InputTaskOverrideResponse:
    _ensure_input_exists(db, input_id)
    row = upsert_task_override(
        db=db,
        input_id=input_id,
        event_uid=event_uid.strip(),
        display_title=payload.display_title.strip(),
    )
    return _to_task_response(row)


@router.delete("/{input_id}/courses/rename", status_code=status.HTTP_204_NO_CONTENT)
def remove_input_course_rename(
    input_id: int,
    original_course_label: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
) -> Response:
    _ensure_input_exists(db, input_id)
    deleted = delete_course_override(db, input_id, original_course_label.strip())
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course override not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{input_id}/tasks/{event_uid}/rename", status_code=status.HTTP_204_NO_CONTENT)
def remove_input_task_rename(
    input_id: int,
    event_uid: str,
    db: Session = Depends(get_db),
) -> Response:
    _ensure_input_exists(db, input_id)
    deleted = delete_task_override(db, input_id, event_uid.strip())
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task override not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _ensure_input_exists(db: Session, input_id: int) -> None:
    if get_input_by_id(db, input_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Input not found")


def _to_course_response(row) -> InputCourseOverrideResponse:
    return InputCourseOverrideResponse(
        id=row.id,
        input_id=row.input_id,
        original_course_label=row.original_course_label,
        display_course_label=row.display_course_label,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_task_response(row) -> InputTaskOverrideResponse:
    return InputTaskOverrideResponse(
        id=row.id,
        input_id=row.input_id,
        event_uid=row.event_uid,
        display_title=row.display_title,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_change_response(row: Change) -> ChangeResponse:
    return ChangeResponse(
        id=row.id,
        input_id=row.input_id,
        event_uid=row.event_uid,
        change_type=row.change_type.value,
        detected_at=row.detected_at,
        before_json=row.before_json,
        after_json=row.after_json,
        delta_seconds=row.delta_seconds,
        before_snapshot_id=row.before_snapshot_id,
        after_snapshot_id=row.after_snapshot_id,
        evidence_keys=row.evidence_keys,
        before_raw_evidence_key=row.before_snapshot.raw_evidence_key if row.before_snapshot else None,
        after_raw_evidence_key=row.after_snapshot.raw_evidence_key if row.after_snapshot else None,
        viewed_at=row.viewed_at,
        viewed_note=row.viewed_note,
    )


def _extract_snapshot_evidence_path(raw_evidence_key: object) -> str | None:
    if not isinstance(raw_evidence_key, dict):
        return None
    path_value = raw_evidence_key.get("path")
    if isinstance(path_value, str) and path_value:
        return path_value
    return None
