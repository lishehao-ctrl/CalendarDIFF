from __future__ import annotations

from datetime import datetime

from app.db.models import Input, SyncRun
from app.modules.inputs.schemas import InputCreateResponse, InputResponse, InputRunResponse


def to_input_response(input: Input, *, next_check_at: datetime | None, last_result: str | None) -> InputResponse:
    return InputResponse(
        id=input.id,
        type=input.type.value,
        display_label=input.display_label,
        provider=input.provider,
        gmail_label=input.gmail_label,
        gmail_from_contains=input.gmail_from_contains,
        gmail_subject_keywords=input.gmail_subject_keywords,
        gmail_account_email=input.gmail_account_email,
        notify_email=input.notify_email,
        interval_minutes=input.interval_minutes,
        is_active=input.is_active,
        last_checked_at=input.last_checked_at,
        last_ok_at=input.last_ok_at,
        last_change_detected_at=input.last_change_detected_at,
        last_error_at=input.last_error_at,
        last_email_sent_at=input.last_email_sent_at,
        next_check_at=next_check_at,
        last_result=last_result,
        last_error=input.last_error,
        created_at=input.created_at,
    )


def to_input_create_response(input: Input, *, upserted_existing: bool) -> InputCreateResponse:
    base = to_input_response(input, next_check_at=input.last_checked_at, last_result=None)
    return InputCreateResponse(**base.model_dump(), upserted_existing=upserted_existing)


def to_input_run_response(run: SyncRun) -> InputRunResponse:
    return InputRunResponse(
        id=run.id,
        input_id=run.input_id,
        trigger_type=run.trigger_type.value,
        started_at=run.started_at,
        finished_at=run.finished_at,
        status=run.status.value,
        changes_count=run.changes_count,
        error_code=run.error_code,
        error_message=run.error_message,
        duration_ms=run.duration_ms,
        lock_owner=run.lock_owner,
    )
