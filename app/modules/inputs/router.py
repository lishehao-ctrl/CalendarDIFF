from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.core.security import require_api_key
from app.db.models import Change, Snapshot
from app.db.session import get_db
from app.modules.changes.schemas import ChangeResponse, ChangeViewedUpdateRequest
from app.modules.inputs.presenters import to_input_response
from app.modules.inputs.schemas import (
    GmailOAuthStartRequest,
    GmailOAuthStartResponse,
    InputResponse,
    ManualInputSyncResponse,
)
from app.modules.inputs.service import (
    InputBusyError,
    InputDeactivateError,
    build_gmail_oauth_start,
    deactivate_input,
    get_input_by_id,
    list_inputs_with_runtime_state,
    run_manual_input_sync,
)
from app.modules.snapshots.schemas import SnapshotResponse
from app.modules.users.service import (
    UserNotInitializedError,
    UserOnboardingIncompleteError,
    require_onboarded_user,
    user_onboarding_incomplete_detail,
    user_not_initialized_detail,
)


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


@router.get("", response_model=list[InputResponse])
def list_inputs(db: Session = Depends(get_db)) -> list[InputResponse]:
    rows = list_inputs_with_runtime_state(db)
    return [
        to_input_response(input, next_check_at=next_check_at, last_result=last_result)
        for input, next_check_at, last_result in rows
    ]


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


@router.post("/ics", include_in_schema=False)
def create_ics_input_route_removed() -> None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


@router.post("/{input_id}/sync", response_model=ManualInputSyncResponse)
def sync_input_now(input_id: int, db: Session = Depends(get_db)) -> ManualInputSyncResponse:
    input = get_input_by_id(db, input_id)
    if input is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Input not found")
    if not input.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "input_inactive",
                "message": "Input is inactive",
            },
        )

    try:
        result = run_manual_input_sync(db, input)
    except InputBusyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "status": "LOCK_SKIPPED",
                "code": "input_busy",
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
        "error_code": result.error_code,
        "is_baseline_sync": result.is_baseline_sync,
    }
    if result.notification_state is not None:
        payload["notification_state"] = result.notification_state
    return ManualInputSyncResponse.model_validate(payload)


@router.delete("/{input_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_input_by_id(input_id: int, db: Session = Depends(get_db)) -> None:
    input_row = get_input_by_id(db, input_id)
    if input_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Input not found")
    try:
        deactivate_input(db, input_row)
    except InputDeactivateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": exc.code,
                "message": str(exc),
            },
        ) from exc


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
            has_evidence=isinstance(row.raw_evidence_key, dict),
            evidence_kind=_extract_evidence_kind(_extract_snapshot_evidence_key(row.raw_evidence_key)),
        )
        for row in rows
    ]


def _ensure_input_exists(db: Session, input_id: int) -> None:
    input_row = get_input_by_id(db, input_id)
    if input_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Input not found")


def _to_change_response(row: Change) -> ChangeResponse:
    before_evidence = _extract_snapshot_evidence_key(row.before_snapshot.raw_evidence_key if row.before_snapshot else None)
    after_evidence = _extract_snapshot_evidence_key(row.after_snapshot.raw_evidence_key if row.after_snapshot else None)
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
        has_before_evidence=before_evidence is not None,
        has_after_evidence=after_evidence is not None,
        before_evidence_kind=_extract_evidence_kind(before_evidence),
        after_evidence_kind=_extract_evidence_kind(after_evidence),
        viewed_at=row.viewed_at,
        viewed_note=row.viewed_note,
    )


def _extract_snapshot_evidence_key(raw_evidence_key: object) -> dict | None:
    if not isinstance(raw_evidence_key, dict):
        return None
    return raw_evidence_key


def _extract_evidence_kind(raw_evidence_key: dict | None) -> str | None:
    if raw_evidence_key is None:
        return None
    kind = raw_evidence_key.get("kind")
    if isinstance(kind, str) and kind.strip():
        return kind.strip()
    return None
