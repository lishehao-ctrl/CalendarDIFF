from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import sanitize_log_message
from app.core.security import decrypt_secret, encrypt_secret
from app.db.models import (
    Change,
    ChangeType,
    EmailMessage,
    Input,
    InputType,
    SyncRun,
    SyncRunStatus,
    SyncTriggerType,
)
from app.modules.evidence.store import save_ics
from app.modules.emails.service import create_review_queue_from_email_changes
from app.modules.notify.interface import Notifier
from app.modules.notify.service import enqueue_notifications_for_changes
from app.modules.sync.ics_client import ICSClient
from app.modules.sync.gmail_client import GmailAPIError, GmailClient, GmailHistoryExpiredError

logger = logging.getLogger(__name__)
MAX_SYNC_RUN_ERROR_MESSAGE_LEN = 512
LOCK_SKIPPED_COOLDOWN_SECONDS = 30


@dataclass(frozen=True)
class SyncRunResult:
    input_id: int
    changes_created: int
    email_sent: bool
    last_error: str | None
    is_baseline_sync: bool = False
    sync_failed: bool = False
    notification_failed: bool = False
    notification_skipped_duplicate: bool = False
    status: SyncRunStatus = SyncRunStatus.NO_CHANGE
    error_code: str | None = None
    run_id: int | None = None
    trigger_type: SyncTriggerType = SyncTriggerType.SCHEDULER
    notification_state: str | None = None


class GmailAuthTokenError(RuntimeError):
    def __init__(self, *, error_code: str, message: str) -> None:
        self.error_code = error_code
        super().__init__(message)


def list_due_inputs(db: Session, now: datetime | None = None) -> list[Input]:
    current = now or datetime.now(timezone.utc)
    interval_expr = Input.last_checked_at + func.make_interval(0, 0, 0, 0, 0, Input.interval_minutes, 0)
    due_at_expr = func.coalesce(interval_expr, current)
    priority_rank_expr = case((Input.type == InputType.EMAIL, 0), else_=1)
    stmt = (
        select(Input)
        .where(
            Input.is_active.is_(True),
            or_(
                Input.last_checked_at.is_(None),
                interval_expr <= current,
            ),
        )
        .order_by(priority_rank_expr.asc(), due_at_expr.asc(), Input.id.asc())
    )
    due_inputs = db.scalars(stmt).all()
    if not due_inputs:
        return []

    due_input_ids = [input.id for input in due_inputs]
    latest_run_subquery = (
        select(
            SyncRun.input_id.label("input_id"),
            func.max(SyncRun.id).label("latest_run_id"),
        )
        .where(SyncRun.input_id.in_(due_input_ids))
        .group_by(SyncRun.input_id)
        .subquery()
    )
    latest_runs = db.execute(
        select(
            SyncRun.input_id,
            SyncRun.status,
            SyncRun.trigger_type,
            SyncRun.started_at,
        ).join(latest_run_subquery, SyncRun.id == latest_run_subquery.c.latest_run_id)
    ).all()

    cooldown_start = current - timedelta(seconds=LOCK_SKIPPED_COOLDOWN_SECONDS)
    blocked_input_ids = {
        input_id
        for input_id, run_status, trigger_type, started_at in latest_runs
        if run_status == SyncRunStatus.LOCK_SKIPPED
        and trigger_type == SyncTriggerType.SCHEDULER
        and started_at is not None
        and started_at >= cooldown_start
    }
    if not blocked_input_ids:
        return due_inputs

    return [input for input in due_inputs if input.id not in blocked_input_ids]


def record_lock_skipped_run(
    db: Session,
    *,
    input_id: int,
    trigger_type: SyncTriggerType,
    lock_owner: str | None = None,
) -> SyncRunResult:
    started_at = datetime.now(timezone.utc)
    finished_at = datetime.now(timezone.utc)
    run = _build_sync_run(
        input_id=input_id,
        trigger_type=trigger_type,
        started_at=started_at,
        finished_at=finished_at,
        status=SyncRunStatus.LOCK_SKIPPED,
        changes_count=0,
        error_code="input_lock_not_acquired",
        error_message="input lock not acquired",
        lock_owner=lock_owner,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return SyncRunResult(
        input_id=input_id,
        changes_created=0,
        email_sent=False,
        last_error="input lock not acquired",
        is_baseline_sync=False,
        sync_failed=False,
        notification_failed=False,
        notification_skipped_duplicate=False,
        status=SyncRunStatus.LOCK_SKIPPED,
        error_code="input_lock_not_acquired",
        run_id=run.id,
        trigger_type=trigger_type,
    )


def sync_input(
    db: Session,
    input: Input,
    notifier: Notifier | None = None,
    ics_client: ICSClient | None = None,
    *,
    trigger_type: SyncTriggerType = SyncTriggerType.SCHEDULER,
    lock_owner: str | None = None,
) -> SyncRunResult:
    if input.type == InputType.EMAIL:
        return _sync_email_input(
            db=db,
            input=input,
            notifier=notifier,
            trigger_type=trigger_type,
            lock_owner=lock_owner,
        )

    run_started_at = datetime.now(timezone.utc)
    input.last_checked_at = run_started_at
    input.last_error = None

    client = ics_client or ICSClient()

    try:
        input_url = decrypt_secret(input.encrypted_url)
        fetched = client.fetch(
            input_url,
            input.id,
            if_none_match=input.etag,
            if_modified_since=input.last_modified,
        )

        if fetched.not_modified:
            return _handle_input_error(
                db,
                input,
                RuntimeError("calendar parser removed, pending llm implementation"),
                started_at=run_started_at,
                trigger_type=trigger_type,
                lock_owner=lock_owner,
                status=SyncRunStatus.PARSE_FAILED,
                error_code="parse_calendar_parser_removed",
            )

        if fetched.content is None:
            raise RuntimeError("ICS fetch returned no content for non-304 response")

        content_hash = _compute_normalized_content_hash(fetched.content)
        if input.last_content_hash is not None and input.last_content_hash == content_hash:
            return _handle_input_error(
                db,
                input,
                RuntimeError("calendar parser removed, pending llm implementation"),
                started_at=run_started_at,
                trigger_type=trigger_type,
                lock_owner=lock_owner,
                status=SyncRunStatus.PARSE_FAILED,
                error_code="parse_calendar_parser_removed",
            )
    except Exception as exc:
        return _handle_input_error(
            db,
            input,
            exc,
            started_at=run_started_at,
            trigger_type=trigger_type,
            lock_owner=lock_owner,
            status=SyncRunStatus.FETCH_FAILED,
            error_code=_classify_fetch_error(exc),
        )

    assert fetched.content is not None
    try:
        save_ics(input_id=input.id, content=fetched.content, retrieved_at=fetched.fetched_at_utc)
    except Exception as exc:
        return _handle_input_error(
            db,
            input,
            exc,
            started_at=run_started_at,
            trigger_type=trigger_type,
            lock_owner=lock_owner,
            status=SyncRunStatus.DIFF_FAILED,
            error_code="diff_exception",
        )

    return _handle_input_error(
        db,
        input,
        RuntimeError("calendar parser removed, pending llm implementation"),
        started_at=run_started_at,
        trigger_type=trigger_type,
        lock_owner=lock_owner,
        status=SyncRunStatus.PARSE_FAILED,
        error_code="parse_calendar_parser_removed",
    )


def _sync_email_input(
    *,
    db: Session,
    input: Input,
    notifier: Notifier | None,
    trigger_type: SyncTriggerType,
    lock_owner: str | None,
) -> SyncRunResult:
    run_started_at = datetime.now(timezone.utc)
    input.last_checked_at = run_started_at
    input.last_error = None

    if input.provider != "gmail":
        return _handle_input_error(
            db,
            input,
            RuntimeError(f"unsupported email provider: {input.provider}"),
            started_at=run_started_at,
            trigger_type=trigger_type,
            lock_owner=lock_owner,
            status=SyncRunStatus.FETCH_FAILED,
            error_code="fetch_provider_unsupported",
        )

    gmail_client = GmailClient()
    try:
        access_token = _resolve_gmail_access_token(input, gmail_client)
        profile = gmail_client.get_profile(access_token=access_token)

        if not input.gmail_history_id:
            finished_at = datetime.now(timezone.utc)
            input.gmail_history_id = profile.history_id
            input.gmail_account_email = profile.email_address
            input.last_checked_at = finished_at
            input.last_ok_at = finished_at
            input.last_error = None
            run = _build_sync_run(
                input_id=input.id,
                trigger_type=trigger_type,
                started_at=run_started_at,
                finished_at=finished_at,
                status=SyncRunStatus.NO_CHANGE,
                changes_count=0,
                lock_owner=lock_owner,
            )
            db.add(run)
            db.commit()
            db.refresh(run)
            return SyncRunResult(
                input_id=input.id,
                changes_created=0,
                email_sent=False,
                last_error=None,
                is_baseline_sync=True,
                sync_failed=False,
                notification_failed=False,
                notification_skipped_duplicate=False,
                status=SyncRunStatus.NO_CHANGE,
                error_code=None,
                run_id=run.id,
                trigger_type=trigger_type,
            )

        try:
            history_result = gmail_client.list_history(
                access_token=access_token,
                start_history_id=input.gmail_history_id,
            )
        except GmailHistoryExpiredError:
            finished_at = datetime.now(timezone.utc)
            input.gmail_history_id = profile.history_id
            input.gmail_account_email = profile.email_address
            input.last_checked_at = finished_at
            input.last_ok_at = finished_at
            input.last_error = None
            run = _build_sync_run(
                input_id=input.id,
                trigger_type=trigger_type,
                started_at=run_started_at,
                finished_at=finished_at,
                status=SyncRunStatus.NO_CHANGE,
                changes_count=0,
                lock_owner=lock_owner,
            )
            db.add(run)
            db.commit()
            db.refresh(run)
            return SyncRunResult(
                input_id=input.id,
                changes_created=0,
                email_sent=False,
                last_error=None,
                is_baseline_sync=False,
                sync_failed=False,
                notification_failed=False,
                notification_skipped_duplicate=False,
                status=SyncRunStatus.NO_CHANGE,
                error_code=None,
                run_id=run.id,
                trigger_type=trigger_type,
            )

        next_history_id = history_result.history_id or profile.history_id or input.gmail_history_id
        candidate_message_ids = history_result.message_ids
        if candidate_message_ids:
            existing_message_ids = set(
                db.scalars(
                    select(EmailMessage.email_id).where(
                        EmailMessage.email_id.in_(candidate_message_ids),
                        EmailMessage.user_id == input.user_id,
                    )
                ).all()
            )
            candidate_message_ids = [item for item in candidate_message_ids if item not in existing_message_ids]

        label_id: str | None = None
        if input.gmail_label:
            labels = gmail_client.list_labels(access_token=access_token)
            label_id = _resolve_gmail_label_id(input.gmail_label, labels)
            if label_id is None:
                raise RuntimeError(f"Gmail label not found: {input.gmail_label}")

        subject_keywords = _normalize_subject_keywords(input.gmail_subject_keywords)
        matched_messages = []
        for message_id in candidate_message_ids:
            metadata = gmail_client.get_message_metadata(access_token=access_token, message_id=message_id)
            if not _matches_gmail_filters(
                metadata=metadata,
                label_id=label_id,
                from_contains=input.gmail_from_contains,
                subject_keywords=subject_keywords,
            ):
                continue
            matched_messages.append(metadata)

        if not matched_messages:
            finished_at = datetime.now(timezone.utc)
            input.gmail_history_id = next_history_id
            input.gmail_account_email = profile.email_address
            input.last_checked_at = finished_at
            input.last_ok_at = finished_at
            input.last_error = None
            run = _build_sync_run(
                input_id=input.id,
                trigger_type=trigger_type,
                started_at=run_started_at,
                finished_at=finished_at,
                status=SyncRunStatus.NO_CHANGE,
                changes_count=0,
                lock_owner=lock_owner,
            )
            db.add(run)
            db.commit()
            db.refresh(run)
            return SyncRunResult(
                input_id=input.id,
                changes_created=0,
                email_sent=False,
                last_error=None,
                is_baseline_sync=False,
                sync_failed=False,
                notification_failed=False,
                notification_skipped_duplicate=False,
                status=SyncRunStatus.NO_CHANGE,
                error_code=None,
                run_id=run.id,
                trigger_type=trigger_type,
            )

        settings = get_settings()
        review_items_count = 0
        try:
            review_items_count = create_review_queue_from_email_changes(
                db,
                user_id=input.user_id,
                messages=matched_messages,
                timezone_name=settings.digest_fixed_timezone,
            )
        except Exception as exc:
            logger.error(
                "failed to create email review queue items input_id=%s error=%s",
                input.id,
                _sanitize_sync_error(str(exc)),
            )

        finished_at = datetime.now(timezone.utc)
        input.gmail_history_id = next_history_id
        input.gmail_account_email = profile.email_address
        input.last_checked_at = finished_at
        input.last_ok_at = finished_at
        input.last_error = None
        if review_items_count > 0:
            input.last_change_detected_at = finished_at

        run = _build_sync_run(
            input_id=input.id,
            trigger_type=trigger_type,
            started_at=run_started_at,
            finished_at=finished_at,
            status=SyncRunStatus.CHANGED if review_items_count > 0 else SyncRunStatus.NO_CHANGE,
            changes_count=review_items_count,
            error_code=None,
            error_message=None,
            lock_owner=lock_owner,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return SyncRunResult(
            input_id=input.id,
            changes_created=review_items_count,
            email_sent=False,
            last_error=None,
            is_baseline_sync=False,
            sync_failed=False,
            notification_failed=False,
            notification_skipped_duplicate=False,
            status=SyncRunStatus.CHANGED if review_items_count > 0 else SyncRunStatus.NO_CHANGE,
            error_code=None,
            run_id=run.id,
            trigger_type=trigger_type,
            notification_state=None,
        )
    except Exception as exc:
        return _handle_input_error(
            db,
            input,
            exc,
            started_at=run_started_at,
            trigger_type=trigger_type,
            lock_owner=lock_owner,
            status=SyncRunStatus.FETCH_FAILED,
            error_code=_classify_gmail_fetch_error(exc),
        )


def _handle_input_error(
    db: Session,
    input: Input,
    exc: Exception,
    *,
    started_at: datetime,
    trigger_type: SyncTriggerType,
    lock_owner: str | None,
    status: SyncRunStatus,
    error_code: str,
) -> SyncRunResult:
    db.rollback()

    safe_error = _sanitize_sync_error(str(exc))
    logger.error("sync failed for input_id=%s error=%s", input.id, safe_error)
    finished_at = datetime.now(timezone.utc)
    run = _build_sync_run(
        input_id=input.id,
        trigger_type=trigger_type,
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        changes_count=0,
        error_code=error_code,
        error_message=safe_error,
        lock_owner=lock_owner,
    )

    input_in_db = db.get(Input, input.id)
    if input_in_db is None:
        db.add(run)
        db.commit()
        db.refresh(run)
        return SyncRunResult(
            input_id=input.id,
            changes_created=0,
            email_sent=False,
            last_error=safe_error,
            is_baseline_sync=False,
            sync_failed=_is_sync_failed_status(status),
            notification_failed=status == SyncRunStatus.EMAIL_FAILED,
            notification_skipped_duplicate=False,
            status=status,
            error_code=error_code,
            run_id=run.id,
            trigger_type=trigger_type,
        )

    input_in_db.last_checked_at = finished_at
    input_in_db.last_error_at = finished_at
    input_in_db.last_error = safe_error
    db.add(run)
    db.commit()
    db.refresh(run)

    return SyncRunResult(
        input_id=input.id,
        changes_created=0,
        email_sent=False,
        last_error=safe_error,
        is_baseline_sync=False,
        sync_failed=_is_sync_failed_status(status),
        notification_failed=status == SyncRunStatus.EMAIL_FAILED,
        notification_skipped_duplicate=False,
        status=status,
        error_code=error_code,
        run_id=run.id,
        trigger_type=trigger_type,
    )


def _build_sync_run(
    *,
    input_id: int,
    trigger_type: SyncTriggerType,
    started_at: datetime,
    finished_at: datetime,
    status: SyncRunStatus,
    changes_count: int,
    error_code: str | None = None,
    error_message: str | None = None,
    lock_owner: str | None = None,
) -> SyncRun:
    duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
    return SyncRun(
        input_id=input_id,
        trigger_type=trigger_type,
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        changes_count=changes_count,
        error_code=error_code,
        error_message=error_message,
        lock_owner=lock_owner,
        duration_ms=duration_ms,
    )


def _is_sync_failed_status(status: SyncRunStatus) -> bool:
    return status in {
        SyncRunStatus.FETCH_FAILED,
        SyncRunStatus.PARSE_FAILED,
        SyncRunStatus.DIFF_FAILED,
    }


def _sanitize_sync_error(message: str | None) -> str:
    safe = sanitize_log_message(message or "").strip() or "unknown error"
    return safe[:MAX_SYNC_RUN_ERROR_MESSAGE_LEN]


def _resolve_gmail_access_token(input: Input, gmail_client: GmailClient) -> str:
    if not input.encrypted_access_token:
        raise GmailAuthTokenError(
            error_code="fetch_gmail_auth_missing_access_token",
            message="Missing Gmail access token. Reconnect Gmail input.",
        )

    access_token = decrypt_secret(input.encrypted_access_token)
    expires_at = input.access_token_expires_at
    now = datetime.now(timezone.utc)
    if expires_at is None or expires_at > now + timedelta(seconds=60):
        return access_token

    if not input.encrypted_refresh_token:
        raise GmailAuthTokenError(
            error_code="fetch_gmail_auth_refresh_token_missing",
            message="Gmail access token expired and refresh token is missing. Reconnect Gmail input.",
        )

    refresh_token = decrypt_secret(input.encrypted_refresh_token)
    try:
        refreshed = gmail_client.refresh_access_token(refresh_token=refresh_token)
    except Exception as exc:
        raise GmailAuthTokenError(
            error_code="fetch_gmail_auth_refresh_failed",
            message="Gmail token refresh failed. Reconnect Gmail input.",
        ) from exc
    input.encrypted_access_token = encrypt_secret(refreshed.access_token)
    if refreshed.refresh_token:
        input.encrypted_refresh_token = encrypt_secret(refreshed.refresh_token)
    input.access_token_expires_at = refreshed.expires_at
    return refreshed.access_token


def _resolve_gmail_label_id(label_name: str, labels) -> str | None:
    target = label_name.strip().lower()
    if not target:
        return None
    for label in labels:
        current_name = getattr(label, "name", None)
        current_id = getattr(label, "id", None)
        if (
            isinstance(current_name, str)
            and isinstance(current_id, str)
            and current_name.strip().lower() == target
        ):
            return current_id
    return None


def _normalize_subject_keywords(raw_keywords: object) -> list[str]:
    if not isinstance(raw_keywords, list):
        return []
    normalized: list[str] = []
    for item in raw_keywords:
        if not isinstance(item, str):
            continue
        cleaned = item.strip().lower()
        if cleaned:
            normalized.append(cleaned)
    return normalized


def _matches_gmail_filters(
    *,
    metadata,
    label_id: str | None,
    from_contains: str | None,
    subject_keywords: list[str],
) -> bool:
    if label_id is not None:
        label_ids = getattr(metadata, "label_ids", None)
        if not isinstance(label_ids, list) or label_id not in label_ids:
            return False

    if from_contains:
        from_header = str(getattr(metadata, "from_header", "") or "").lower()
        if from_contains.strip().lower() not in from_header:
            return False

    if subject_keywords:
        subject = str(getattr(metadata, "subject", "") or "").lower()
        if not any(keyword in subject for keyword in subject_keywords):
            return False

    return True


def _enqueue_and_maybe_dispatch_notifications(
    *,
    db: Session,
    input: Input,
    changes: list[Change],
    notifier: Notifier | None,
    now: datetime,
) -> tuple[bool, str | None, int, str | None]:
    del notifier
    enqueue_result = enqueue_notifications_for_changes(
        db,
        input,
        changes,
        deliver_after=now,
        enqueue_reason="digest_queue",
    )
    if enqueue_result.enqueued_count == 0:
        state = "skipped_duplicate" if enqueue_result.dedup_skipped_count > 0 else None
        return False, None, enqueue_result.dedup_skipped_count, state
    return False, None, enqueue_result.dedup_skipped_count, "queued_for_digest"


def _classify_fetch_error(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "fetch_timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        status_code = response.status_code if response is not None else None
        if status_code is not None and 400 <= status_code < 500:
            return "fetch_http_4xx"
        if status_code is not None and status_code >= 500:
            return "fetch_http_5xx"
        return "fetch_http_error"
    if isinstance(exc, httpx.NetworkError):
        return "fetch_network"
    return "fetch_exception"


def _classify_gmail_fetch_error(exc: Exception) -> str:
    if isinstance(exc, GmailAuthTokenError):
        return exc.error_code
    if isinstance(exc, GmailHistoryExpiredError):
        return "fetch_gmail_history_expired"
    if isinstance(exc, GmailAPIError):
        status_code = exc.status_code
        if status_code == 400:
            return "fetch_gmail_invalid_request"
        if status_code == 401:
            return "fetch_gmail_auth"
        if status_code == 403:
            return "fetch_gmail_forbidden"
        if status_code == 404:
            return "fetch_gmail_not_found"
        if status_code == 429:
            return "fetch_gmail_rate_limited"
        if status_code >= 500:
            return "fetch_gmail_5xx"
        return "fetch_gmail_http"
    return _classify_fetch_error(exc)


def _classify_email_error(message: str) -> str:
    lowered = message.lower()
    if "recipient" in lowered or "notify email" in lowered:
        return "email_no_recipient"
    return "email_send_failed"


def _compute_normalized_content_hash(content: bytes) -> str:
    normalized_content = _normalize_ics_bytes(content)
    return hashlib.sha256(normalized_content).hexdigest()


def _normalize_ics_bytes(content: bytes) -> bytes:
    normalized_text = content.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized_text.split("\n")]
    joined = "\n".join(lines).rstrip("\n")
    if joined:
        joined += "\n"
    return joined.encode("utf-8")
