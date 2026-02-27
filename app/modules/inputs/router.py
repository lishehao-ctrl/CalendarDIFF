from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import require_api_key
from app.db.session import get_db
from app.modules.common.deps import require_onboarded_user_or_409
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


router = APIRouter(
    prefix="/v1/inputs",
    tags=["inputs"],
    dependencies=[Depends(require_api_key), Depends(require_onboarded_user_or_409)],
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
    _: Session = Depends(get_db),
) -> GmailOAuthStartResponse:
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

