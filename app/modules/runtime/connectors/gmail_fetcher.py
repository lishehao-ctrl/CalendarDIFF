from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import re
from datetime import date, datetime, timezone
from collections.abc import Callable
from typing import Any, cast

from app.core.config import get_settings
from app.db.models.runtime import ConnectorResultStatus
from app.db.models.input import InputSource
from app.db.models.review import EventEntity, EventEntityLifecycle
from app.db.models.shared import CourseWorkItemLabelFamily
from app.modules.common.course_identity import normalized_course_identity_key
from app.modules.common.source_monitoring_window import (
    SourceMonitoringWindow,
    message_internal_date_in_window,
    parse_source_monitoring_window,
    source_timezone_name,
)
from app.modules.runtime.connectors.connector_types import ConnectorFetchOutcome
from app.modules.runtime.connectors.gmail_second_filter import (
    run_gmail_second_filter,
    should_enforce_gmail_second_filter,
)
from app.modules.runtime.connectors.source_orchestrator import route_gmail_message
from app.modules.sources.source_secrets import decode_source_secrets
from app.modules.runtime.connectors.clients.gmail_client import GmailAPIError, GmailClient, GmailHistoryExpiredError
from sqlalchemy import select
from sqlalchemy.orm import object_session
from sqlalchemy.orm.exc import UnmappedInstanceError


_DEFAULT_GMAIL_LABEL_IDS = ("INBOX",)
_GMAIL_FETCH_PROGRESS_BATCH = 10
_GMAIL_FETCH_TAIL_PROGRESS = 5
_GMAIL_CONNECTOR_CHUNK_SIZE = 25
_GMAIL_CONNECTOR_METADATA_MAX_WORKERS = 8
logger = logging.getLogger(__name__)


def fetch_gmail_changes(
    *,
    source: Any,
    request_id: str,
    job_payload: dict | None = None,
    emit_progress: Callable[[dict], None] | None = None,
) -> ConnectorFetchOutcome:
    input_source = cast(InputSource, source)
    secrets = decode_source_secrets(input_source)
    access_token = secrets.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        return ConnectorFetchOutcome(
            status=ConnectorResultStatus.AUTH_FAILED,
            cursor_patch={},
            parse_payload=None,
            error_code="gmail_missing_access_token",
            error_message="missing access token for gmail source",
        )

    client = GmailClient()
    try:
        profile = client.get_profile(access_token=access_token)
    except GmailAPIError as exc:
        if exc.status_code in {401, 403}:
            return _failed("gmail_auth_failed", str(exc), status=ConnectorResultStatus.AUTH_FAILED)
        if exc.status_code == 429:
            return _failed("gmail_rate_limited", str(exc), status=ConnectorResultStatus.RATE_LIMITED)
        return _failed("gmail_fetch_failed", str(exc), status=ConnectorResultStatus.FETCH_FAILED)

    source_config = getattr(input_source, "config", None)
    config_json = getattr(source_config, "config_json", None)
    config = config_json if isinstance(config_json, dict) else {}
    known_course_tokens = _known_course_tokens_for_source(input_source)
    term_window = parse_source_monitoring_window(input_source, required=False)
    timezone_name = source_timezone_name(input_source)
    now = datetime.now(timezone.utc)
    if term_window is not None and term_window.is_expired(now=now, timezone_name=timezone_name):
        latest_history_id = profile.history_id
        return _no_change(cursor_patch={"history_id": latest_history_id} if latest_history_id else {})

    source_cursor = getattr(input_source, "cursor", None)
    cursor_json = getattr(source_cursor, "cursor_json", None)
    cursor = cursor_json if isinstance(cursor_json, dict) else {}
    cursor_history_id = cursor.get("history_id") if isinstance(cursor.get("history_id"), str) else None
    continuation_state = _extract_gmail_continuation(job_payload)
    if continuation_state is not None:
        return _continue_gmail_connector_fetch(
            client=client,
            access_token=access_token,
            source=input_source,
            request_id=request_id,
            profile=profile,
            config=config,
            term_window=term_window,
            timezone_name=timezone_name,
            known_course_tokens=known_course_tokens,
            continuation_state=continuation_state,
            emit_progress=emit_progress,
        )

    if cursor_history_id is None:
        if job_payload is not None:
            return _bootstrap_gmail_discovery(
                client=client,
                access_token=access_token,
                source=input_source,
                request_id=request_id,
                profile=profile,
                config=config,
                term_window=term_window,
                timezone_name=timezone_name,
                known_course_tokens=known_course_tokens,
                emit_progress=emit_progress,
            )
        return _bootstrap_gmail_messages(
            client=client,
            access_token=access_token,
            source=input_source,
            request_id=request_id,
            profile=profile,
            config=config,
            term_window=term_window,
            timezone_name=timezone_name,
            known_course_tokens=known_course_tokens,
            emit_progress=emit_progress,
        )

    try:
        history_result = client.list_history(
            access_token=access_token,
            start_history_id=cursor_history_id,
        )
    except GmailHistoryExpiredError:
        if job_payload is not None:
            return _bootstrap_gmail_discovery(
                client=client,
                access_token=access_token,
                source=input_source,
                request_id=request_id,
                profile=profile,
                config=config,
                term_window=term_window,
                timezone_name=timezone_name,
                known_course_tokens=known_course_tokens,
                emit_progress=emit_progress,
            )
        return _bootstrap_gmail_messages(
            client=client,
            access_token=access_token,
            source=input_source,
            request_id=request_id,
            profile=profile,
            config=config,
            term_window=term_window,
            timezone_name=timezone_name,
            known_course_tokens=known_course_tokens,
            emit_progress=emit_progress,
        )
    except GmailAPIError as exc:
        if exc.status_code in {401, 403}:
            return _failed("gmail_auth_failed", str(exc), status=ConnectorResultStatus.AUTH_FAILED)
        if exc.status_code == 429:
            return _failed("gmail_rate_limited", str(exc), status=ConnectorResultStatus.RATE_LIMITED)
        return _failed("gmail_fetch_failed", str(exc), status=ConnectorResultStatus.FETCH_FAILED)

    latest_history_id = history_result.history_id or profile.history_id or cursor_history_id
    if not history_result.message_ids:
        return _no_change(cursor_patch={"history_id": latest_history_id})
    if job_payload is not None:
        return _build_gmail_continuation_outcome(
            mode="replay",
            request_id=request_id,
            account_email=profile.email_address,
            history_id_start=cursor_history_id,
            history_id_latest=latest_history_id,
            message_ids=history_result.message_ids,
            emit_progress=emit_progress,
            discovery_phase="gmail_history_list",
            discovery_label="Listing Gmail history delta",
            discovery_detail=f"Discovered {len(history_result.message_ids)} changed emails to hydrate in chunks.",
        )

    message_payloads: list[dict] = []
    total_messages = len(history_result.message_ids)
    _emit_progress(
        emit_progress,
        phase="gmail_history_fetch",
        label="Scanning Gmail delta",
        detail=f"Found {total_messages} changed emails to inspect in the active term window.",
        current=0,
        total=total_messages,
        unit="emails",
    )
    try:
        metadata_rows = _fetch_gmail_message_metadata_rows(
            client=client,
            access_token=access_token,
            message_ids=history_result.message_ids,
            emit_progress=emit_progress,
            phase="gmail_history_fetch",
            label="Scanning Gmail delta",
            detail_template="Inspected {current} of {total} changed emails.",
        )
    except GmailAPIError as exc:
        if exc.status_code in {401, 403}:
            return _failed("gmail_auth_failed", str(exc), status=ConnectorResultStatus.AUTH_FAILED)
        if exc.status_code == 429:
            return _failed("gmail_rate_limited", str(exc), status=ConnectorResultStatus.RATE_LIMITED)
        return _failed("gmail_fetch_failed", str(exc), status=ConnectorResultStatus.FETCH_FAILED)

    for metadata in metadata_rows:
        if not matches_gmail_source_filters(
            metadata=metadata,
            config=config,
            term_window=term_window,
            timezone_name=timezone_name,
            known_course_tokens=known_course_tokens,
            gmail_diff_message_count=total_messages,
        ):
            continue

        message_payloads.append(
            {
                "message_id": metadata.message_id,
                "thread_id": metadata.thread_id,
                "subject": metadata.subject,
                "snippet": metadata.snippet,
                "body_text": metadata.body_text,
                "from_header": metadata.from_header,
                "internal_date": metadata.internal_date,
                "label_ids": metadata.label_ids,
                "history_id": latest_history_id,
                "account_email": profile.email_address,
                "request_id": request_id,
            }
        )
    cursor_patch = {"history_id": latest_history_id}
    if not message_payloads:
        return _no_change(cursor_patch=cursor_patch)

    return ConnectorFetchOutcome(
        status=ConnectorResultStatus.CHANGED,
        cursor_patch=cursor_patch,
        parse_payload={"kind": "gmail", "messages": message_payloads},
        error_code=None,
        error_message=None,
    )


def matches_gmail_source_filters(
    *,
    metadata: Any,
    config: dict,
    term_window: SourceMonitoringWindow | None = None,
    timezone_name: str | None = None,
    known_course_tokens: set[str] | None = None,
    gmail_diff_message_count: int | None = None,
) -> bool:
    metadata_label_ids_raw = getattr(metadata, "label_ids", [])
    metadata_label_ids = [value for value in metadata_label_ids_raw if isinstance(value, str)]
    metadata_from_header = str(getattr(metadata, "from_header", "") or "")
    metadata_subject = str(getattr(metadata, "subject", "") or "")
    metadata_snippet = str(getattr(metadata, "snippet", "") or "")
    metadata_body_text = str(getattr(metadata, "body_text", "") or "")
    metadata_internal_date = getattr(metadata, "internal_date", None)

    if term_window is not None and not message_internal_date_in_window(
        internal_date=metadata_internal_date,
        monitoring_window=term_window,
        timezone_name=timezone_name,
    ):
        return False

    effective_label_ids = _effective_gmail_label_ids(config)
    if effective_label_ids and not any(label in metadata_label_ids for label in effective_label_ids):
        return False

    from_contains = config.get("from_contains")
    explicit_sender_signal = False
    if isinstance(from_contains, str) and from_contains.strip():
        if from_contains.strip().lower() not in metadata_from_header.lower():
            return False
        explicit_sender_signal = True

    subject_keywords = config.get("subject_keywords")
    explicit_subject_signal = False
    if isinstance(subject_keywords, list):
        normalized_keywords = [value.strip().lower() for value in subject_keywords if isinstance(value, str) and value.strip()]
        if normalized_keywords:
            subject_text = metadata_subject.lower()
            if not any(keyword in subject_text for keyword in normalized_keywords):
                return False
            explicit_subject_signal = True

    decision = route_gmail_message(
        from_header=metadata_from_header,
        subject=metadata_subject,
        snippet=metadata_snippet,
        body_text=metadata_body_text,
        explicit_sender_signal=explicit_sender_signal,
        explicit_subject_signal=explicit_subject_signal,
        known_course_tokens=known_course_tokens,
    )
    if decision.route != "parse":
        return False

    second_filter = run_gmail_second_filter(
        from_header=metadata_from_header,
        subject=metadata_subject,
        snippet=metadata_snippet,
        body_text=metadata_body_text,
        label_ids=metadata_label_ids,
        known_course_tokens=known_course_tokens,
        diff_message_count=gmail_diff_message_count,
    )
    enforced = should_enforce_gmail_second_filter(second_filter)
    _log_gmail_second_filter_decision(
        metadata=metadata,
        second_filter=second_filter,
        enforced=enforced,
    )
    return not enforced


def _log_gmail_second_filter_decision(
    *,
    metadata: Any,
    second_filter,
    enforced: bool,
) -> None:
    reason_code = str(getattr(second_filter, "reason_code", "") or "")
    if reason_code in {"secondary_filter_off", "secondary_filter_stub"}:
        return
    logger.info(
        "gmail second filter decision message_id=%s subject=%r from_header=%r stage=%s reason_code=%s risk_band=%s label=%s confidence=%s would_suppress=%s enforced=%s",
        str(getattr(metadata, "message_id", "") or ""),
        str(getattr(metadata, "subject", "") or "")[:180],
        str(getattr(metadata, "from_header", "") or "")[:180],
        str(getattr(second_filter, "stage", "") or ""),
        reason_code,
        str(getattr(second_filter, "risk_band", "") or ""),
        str(getattr(second_filter, "label", "") or ""),
        getattr(second_filter, "confidence", None),
        bool(getattr(second_filter, "would_suppress", False)),
        enforced,
    )


def _bootstrap_gmail_messages(
    *,
    client: GmailClient,
    access_token: str,
    source: InputSource,
    request_id: str,
    profile: Any,
    config: dict,
    term_window: SourceMonitoringWindow | None,
    timezone_name: str | None,
    known_course_tokens: set[str],
    emit_progress: Callable[[dict], None] | None,
) -> ConnectorFetchOutcome:
    latest_history_id = profile.history_id if isinstance(profile.history_id, str) and profile.history_id else None
    if term_window is None:
        return _no_change(cursor_patch={"history_id": latest_history_id} if latest_history_id else {})

    start_date, end_exclusive = term_window.gmail_query_bounds(timezone_name=timezone_name)
    query = f"after:{start_date} before:{end_exclusive}"
    try:
        message_ids = client.list_message_ids(
            access_token=access_token,
            query=query,
            label_ids=_bootstrap_label_ids(config),
        )
    except GmailAPIError as exc:
        if exc.status_code in {401, 403}:
            return _failed("gmail_auth_failed", str(exc), status=ConnectorResultStatus.AUTH_FAILED)
        if exc.status_code == 429:
            return _failed("gmail_rate_limited", str(exc), status=ConnectorResultStatus.RATE_LIMITED)
        return _failed("gmail_fetch_failed", str(exc), status=ConnectorResultStatus.FETCH_FAILED)

    if not message_ids:
        return _no_change(cursor_patch={"history_id": latest_history_id} if latest_history_id else {})

    message_payloads: list[dict] = []
    total_messages = len(message_ids)
    _emit_progress(
        emit_progress,
        phase="gmail_bootstrap_fetch",
        label="Scanning Gmail bootstrap window",
        detail=f"Found {total_messages} emails in the current bootstrap window.",
        current=0,
        total=total_messages,
        unit="emails",
    )
    try:
        metadata_rows = _fetch_gmail_message_metadata_rows(
            client=client,
            access_token=access_token,
            message_ids=message_ids,
            emit_progress=emit_progress,
            phase="gmail_bootstrap_fetch",
            label="Scanning Gmail bootstrap window",
            detail_template="Inspected {current} of {total} emails in the bootstrap window.",
        )
    except GmailAPIError as exc:
        if exc.status_code in {401, 403}:
            return _failed("gmail_auth_failed", str(exc), status=ConnectorResultStatus.AUTH_FAILED)
        if exc.status_code == 429:
            return _failed("gmail_rate_limited", str(exc), status=ConnectorResultStatus.RATE_LIMITED)
        return _failed("gmail_fetch_failed", str(exc), status=ConnectorResultStatus.FETCH_FAILED)

    for metadata in metadata_rows:
        if not matches_gmail_source_filters(
            metadata=metadata,
            config=config,
            term_window=term_window,
            timezone_name=timezone_name,
            known_course_tokens=known_course_tokens,
            gmail_diff_message_count=total_messages,
        ):
            continue
        message_payloads.append(
            {
                "message_id": metadata.message_id,
                "thread_id": metadata.thread_id,
                "subject": metadata.subject,
                "snippet": metadata.snippet,
                "body_text": metadata.body_text,
                "from_header": metadata.from_header,
                "internal_date": metadata.internal_date,
                "label_ids": metadata.label_ids,
                "history_id": latest_history_id,
                "account_email": profile.email_address,
                "request_id": request_id,
            }
        )
    if not message_payloads:
        return _no_change(cursor_patch={"history_id": latest_history_id} if latest_history_id else {})

    return ConnectorFetchOutcome(
        status=ConnectorResultStatus.CHANGED,
        cursor_patch={"history_id": latest_history_id} if latest_history_id else {},
        parse_payload={"kind": "gmail", "messages": message_payloads},
        error_code=None,
        error_message=None,
    )


def _emit_progress(
    emit_progress: Callable[[dict], None] | None,
    *,
    phase: str,
    label: str,
    detail: str,
    current: int,
    total: int,
    unit: str,
) -> None:
    if emit_progress is None:
        return
    percent = round((current / total) * 100, 1) if total > 0 else None
    emit_progress(
        {
            "phase": phase,
            "label": label,
            "detail": detail,
            "current": current,
            "total": total,
            "percent": percent,
            "unit": unit,
        }
    )


def _extract_gmail_continuation(job_payload: dict | None) -> dict | None:
    if not isinstance(job_payload, dict):
        return None
    state = job_payload.get("connector_continuation")
    if not isinstance(state, dict):
        return None
    if str(state.get("provider") or "").strip().lower() != "gmail":
        return None
    return state


def _bootstrap_gmail_discovery(
    *,
    client: GmailClient,
    access_token: str,
    source: InputSource,
    request_id: str,
    profile: Any,
    config: dict,
    term_window: SourceMonitoringWindow | None,
    timezone_name: str | None,
    known_course_tokens: set[str],
    emit_progress: Callable[[dict], None] | None,
) -> ConnectorFetchOutcome:
    latest_history_id = profile.history_id if isinstance(profile.history_id, str) and profile.history_id else None
    if term_window is None:
        return _no_change(cursor_patch={"history_id": latest_history_id} if latest_history_id else {})

    _emit_progress(
        emit_progress,
        phase="gmail_profile",
        label="Loading Gmail profile",
        detail="Connector fetch is loading Gmail profile and bootstrap window.",
        current=0,
        total=1,
        unit="steps",
    )
    start_date, end_exclusive = term_window.gmail_query_bounds(timezone_name=timezone_name)
    query = f"after:{start_date} before:{end_exclusive}"
    try:
        message_ids = client.list_message_ids(
            access_token=access_token,
            query=query,
            label_ids=_bootstrap_label_ids(config),
        )
    except GmailAPIError as exc:
        if exc.status_code in {401, 403}:
            return _failed("gmail_auth_failed", str(exc), status=ConnectorResultStatus.AUTH_FAILED)
        if exc.status_code == 429:
            return _failed("gmail_rate_limited", str(exc), status=ConnectorResultStatus.RATE_LIMITED)
        return _failed("gmail_fetch_failed", str(exc), status=ConnectorResultStatus.FETCH_FAILED)

    if not message_ids:
        return _no_change(cursor_patch={"history_id": latest_history_id} if latest_history_id else {})
    del source, known_course_tokens, timezone_name
    return _build_gmail_continuation_outcome(
        mode="bootstrap",
        request_id=request_id,
        account_email=profile.email_address,
        history_id_start=None,
        history_id_latest=latest_history_id,
        message_ids=message_ids,
        emit_progress=emit_progress,
        discovery_phase="gmail_history_list",
        discovery_label="Listing bootstrap Gmail window",
        discovery_detail=f"Discovered {len(message_ids)} bootstrap emails to hydrate in chunks.",
    )


def _build_gmail_continuation_outcome(
    *,
    mode: str,
    request_id: str,
    account_email: str,
    history_id_start: str | None,
    history_id_latest: str | None,
    message_ids: list[str],
    emit_progress: Callable[[dict], None] | None,
    discovery_phase: str,
    discovery_label: str,
    discovery_detail: str,
) -> ConnectorFetchOutcome:
    total_messages = len(message_ids)
    _emit_progress(
        emit_progress,
        phase=discovery_phase,
        label=discovery_label,
        detail=discovery_detail,
        current=total_messages,
        total=total_messages if total_messages > 0 else 1,
        unit="emails",
    )
    initial_progress = {
        "phase": "gmail_message_hydrate",
        "label": "Hydrating Gmail metadata",
        "detail": f"Hydrated 0 of {total_messages} emails. 0 candidate emails matched parse filters.",
        "current": 0,
        "total": total_messages,
        "percent": 0 if total_messages > 0 else None,
        "unit": "emails",
    }
    return ConnectorFetchOutcome(
        status=ConnectorResultStatus.NO_CHANGE,
        cursor_patch={},
        parse_payload=None,
        error_code=None,
        error_message=None,
        continuation_payload={
            "provider": "gmail",
            "gmail_mode": mode,
            "gmail_history_id_start": history_id_start,
            "gmail_history_id_latest": history_id_latest,
            "gmail_message_ids": list(message_ids),
            "gmail_total_messages": total_messages,
            "gmail_next_index": 0,
            "gmail_matched_messages_buffer": [],
            "gmail_matched_count": 0,
            "gmail_account_email": account_email,
            "substage": "gmail_message_hydrate",
            "progress": initial_progress,
            "request_id": request_id,
        },
        continuation_delay_seconds=0,
    )


def _continue_gmail_connector_fetch(
    *,
    client: GmailClient,
    access_token: str,
    source: InputSource,
    request_id: str,
    profile: Any,
    config: dict,
    term_window: SourceMonitoringWindow | None,
    timezone_name: str | None,
    known_course_tokens: set[str],
    continuation_state: dict,
    emit_progress: Callable[[dict], None] | None,
) -> ConnectorFetchOutcome:
    message_ids_raw = continuation_state.get("gmail_message_ids")
    message_ids = [value for value in message_ids_raw if isinstance(value, str)] if isinstance(message_ids_raw, list) else []
    total_messages = int(continuation_state.get("gmail_total_messages") or len(message_ids))
    next_index = max(int(continuation_state.get("gmail_next_index") or 0), 0)
    latest_history_id = continuation_state.get("gmail_history_id_latest")
    account_email = continuation_state.get("gmail_account_email") or profile.email_address
    matched_messages_raw = continuation_state.get("gmail_matched_messages_buffer")
    matched_messages = list(matched_messages_raw) if isinstance(matched_messages_raw, list) else []
    matched_count = max(int(continuation_state.get("gmail_matched_count") or len(matched_messages)), len(matched_messages))

    if next_index >= total_messages:
        cursor_patch = {"history_id": latest_history_id} if isinstance(latest_history_id, str) and latest_history_id else {}
        if not matched_messages:
            return _no_change(cursor_patch=cursor_patch)
        return ConnectorFetchOutcome(
            status=ConnectorResultStatus.CHANGED,
            cursor_patch=cursor_patch,
            parse_payload={"kind": "gmail", "messages": matched_messages},
            error_code=None,
            error_message=None,
        )

    end_index = min(next_index + _GMAIL_CONNECTOR_CHUNK_SIZE, total_messages)
    current_ids = message_ids[next_index:end_index]
    try:
        metadata_rows = _fetch_gmail_message_metadata_rows(
            client=client,
            access_token=access_token,
            message_ids=current_ids,
            emit_progress=emit_progress,
            phase="gmail_message_hydrate",
            label="Hydrating Gmail metadata",
            detail_template="Hydrated {current} of {total} emails.",
            current_offset=next_index,
            total_override=total_messages,
        )
    except GmailAPIError as exc:
        if exc.status_code in {401, 403}:
            return _failed("gmail_auth_failed", str(exc), status=ConnectorResultStatus.AUTH_FAILED)
        if exc.status_code == 429:
            return _failed("gmail_rate_limited", str(exc), status=ConnectorResultStatus.RATE_LIMITED)
        return _failed("gmail_fetch_failed", str(exc), status=ConnectorResultStatus.FETCH_FAILED)

    for metadata in metadata_rows:
        if not matches_gmail_source_filters(
            metadata=metadata,
            config=config,
            term_window=term_window,
            timezone_name=timezone_name,
            known_course_tokens=known_course_tokens,
            gmail_diff_message_count=total_messages,
        ):
            continue
        matched_messages.append(
            {
                "message_id": metadata.message_id,
                "thread_id": metadata.thread_id,
                "subject": metadata.subject,
                "snippet": metadata.snippet,
                "body_text": metadata.body_text,
                "from_header": metadata.from_header,
                "internal_date": metadata.internal_date,
                "label_ids": metadata.label_ids,
                "history_id": latest_history_id,
                "account_email": account_email,
                "request_id": request_id,
            }
        )
        matched_count += 1

    progress = {
        "phase": "gmail_filter" if end_index >= total_messages else "gmail_message_hydrate",
        "label": "Filtering Gmail candidates" if end_index >= total_messages else "Hydrating Gmail metadata",
        "detail": (
            f"Hydrated {end_index} of {total_messages} emails. "
            f"{matched_count} candidate emails matched parse filters."
        ),
        "current": end_index,
        "total": total_messages,
        "percent": round((end_index / total_messages) * 100, 1) if total_messages > 0 else None,
        "unit": "emails",
    }
    _emit_progress(
        emit_progress,
        phase=str(progress["phase"]),
        label=str(progress["label"]),
        detail=str(progress["detail"]),
        current=int(progress["current"]),
        total=int(progress["total"]) if total_messages > 0 else 1,
        unit="emails",
    )

    if end_index >= total_messages:
        cursor_patch = {"history_id": latest_history_id} if isinstance(latest_history_id, str) and latest_history_id else {}
        if not matched_messages:
            return _no_change(cursor_patch=cursor_patch)
        return ConnectorFetchOutcome(
            status=ConnectorResultStatus.CHANGED,
            cursor_patch=cursor_patch,
            parse_payload={"kind": "gmail", "messages": matched_messages},
            error_code=None,
            error_message=None,
        )

    return ConnectorFetchOutcome(
        status=ConnectorResultStatus.NO_CHANGE,
        cursor_patch={},
        parse_payload=None,
        error_code=None,
        error_message=None,
        continuation_payload={
            "provider": "gmail",
            "gmail_mode": continuation_state.get("gmail_mode"),
            "gmail_history_id_start": continuation_state.get("gmail_history_id_start"),
            "gmail_history_id_latest": latest_history_id,
            "gmail_message_ids": message_ids,
            "gmail_total_messages": total_messages,
            "gmail_next_index": end_index,
            "gmail_matched_messages_buffer": matched_messages,
            "gmail_matched_count": matched_count,
            "gmail_account_email": account_email,
            "substage": "gmail_message_hydrate",
            "progress": progress,
            "request_id": request_id,
        },
        continuation_delay_seconds=0,
    )


def _fetch_gmail_message_metadata_rows(
    *,
    client: GmailClient,
    access_token: str,
    message_ids: list[str],
    emit_progress: Callable[[dict], None] | None,
    phase: str,
    label: str,
    detail_template: str,
    current_offset: int = 0,
    total_override: int | None = None,
) -> list[Any]:
    if not message_ids:
        return []
    settings = get_settings()
    max_workers = max(
        1,
        min(
            len(message_ids),
            int(getattr(settings, "llm_worker_concurrency", 12)),
            _GMAIL_CONNECTOR_METADATA_MAX_WORKERS,
        ),
    )
    if max_workers <= 1 or len(message_ids) <= 1:
        out: list[Any] = []
        total = total_override if total_override is not None else len(message_ids)
        for index, message_id in enumerate(message_ids, start=1):
            metadata = _fetch_single_gmail_message_metadata_or_skip(
                client=client,
                access_token=access_token,
                message_id=message_id,
            )
            if metadata is not None:
                out.append(metadata)
            absolute_current = current_offset + index
            if _should_emit_gmail_progress(current=absolute_current, total=total):
                _emit_progress(
                    emit_progress,
                    phase=phase,
                    label=label,
                    detail=detail_template.format(current=absolute_current, total=total),
                    current=absolute_current,
                    total=total,
                    unit="emails",
                )
        return out

    total = total_override if total_override is not None else len(message_ids)
    results: list[Any | None] = [None] * len(message_ids)
    completed = 0
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="gmail-fetch") as pool:
        future_map = {
            pool.submit(
                _fetch_single_gmail_message_metadata_or_skip,
                client=client,
                access_token=access_token,
                message_id=message_id,
            ): index
            for index, message_id in enumerate(message_ids)
        }
        for future in as_completed(future_map):
            index = future_map[future]
            results[index] = future.result()
            completed += 1
            absolute_current = current_offset + completed
            if _should_emit_gmail_progress(current=absolute_current, total=total):
                _emit_progress(
                    emit_progress,
                    phase=phase,
                    label=label,
                    detail=detail_template.format(current=absolute_current, total=total),
                    current=absolute_current,
                    total=total,
                    unit="emails",
                )
    return [row for row in results if row is not None]


def _fetch_single_gmail_message_metadata_or_skip(
    *,
    client: GmailClient,
    access_token: str,
    message_id: str,
) -> Any | None:
    try:
        return client.get_message_metadata(access_token=access_token, message_id=message_id)
    except GmailAPIError as exc:
        if exc.status_code in {404, 410}:
            logger.info(
                "gmail metadata fetch skipped missing message_id=%s status_code=%s detail=%s",
                message_id,
                exc.status_code,
                str(exc),
            )
            return None
        raise


def _should_emit_gmail_progress(*, current: int, total: int) -> bool:
    if total <= _GMAIL_FETCH_TAIL_PROGRESS:
        return True
    if current >= total:
        return True
    if current % _GMAIL_FETCH_PROGRESS_BATCH == 0:
        return True
    return current > total - _GMAIL_FETCH_TAIL_PROGRESS


def _bootstrap_label_ids(config: dict) -> list[str] | None:
    effective_label_ids = _effective_gmail_label_ids(config)
    return effective_label_ids or None


def _effective_gmail_label_ids(config: dict) -> list[str]:
    out: list[str] = []
    label_id = config.get("label_id")
    if isinstance(label_id, str) and label_id.strip():
        out.append(label_id.strip())
    label_ids = config.get("label_ids")
    if isinstance(label_ids, list):
        for item in label_ids:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
    if out:
        return list(dict.fromkeys(out))
    return list(_DEFAULT_GMAIL_LABEL_IDS)


def _known_course_tokens_for_source(source: InputSource) -> set[str]:
    try:
        session = object_session(source)
    except UnmappedInstanceError:
        return set()
    if session is None or not isinstance(getattr(source, "user_id", None), int):
        return set()
    term_window = parse_source_monitoring_window(source, required=False)

    tokens: set[str] = set()
    current_term_stems: set[tuple[str, int, str | None]] = set()
    entity_rows = session.execute(
        select(
            EventEntity.course_dept,
            EventEntity.course_number,
            EventEntity.course_suffix,
            EventEntity.course_quarter,
            EventEntity.course_year2,
            EventEntity.due_date,
        ).where(
            EventEntity.user_id == source.user_id,
            EventEntity.lifecycle == EventEntityLifecycle.ACTIVE,
        )
    ).all()
    for course_dept, course_number, course_suffix, course_quarter, course_year2, due_date in entity_rows:
        if not _entity_matches_source_term(
            term_window=term_window,
            due_date=due_date,
        ):
            continue
        stem = _course_stem(course_dept=course_dept, course_number=course_number, course_suffix=course_suffix)
        if stem is None:
            continue
        current_term_stems.add(stem)
        tokens.update(_course_identity_tokens(course_dept=course_dept, course_number=course_number, course_suffix=course_suffix))

    family_rows = session.execute(
        select(
            CourseWorkItemLabelFamily.course_dept,
            CourseWorkItemLabelFamily.course_number,
            CourseWorkItemLabelFamily.course_suffix,
            CourseWorkItemLabelFamily.course_quarter,
            CourseWorkItemLabelFamily.course_year2,
        ).where(CourseWorkItemLabelFamily.user_id == source.user_id)
    ).all()
    for course_dept, course_number, course_suffix, course_quarter, course_year2 in family_rows:
        stem = _course_stem(course_dept=course_dept, course_number=course_number, course_suffix=course_suffix)
        if stem is None:
            continue
        del course_quarter, course_year2
        if not current_term_stems or stem in current_term_stems:
            tokens.update(_course_identity_tokens(course_dept=course_dept, course_number=course_number, course_suffix=course_suffix))
    return tokens


def _entity_matches_source_term(
    *,
    term_window: SourceMonitoringWindow | None,
    due_date: object,
) -> bool:
    if term_window is None:
        return True
    return isinstance(due_date, date) and due_date >= term_window.monitor_since


def _course_stem(*, course_dept: object, course_number: object, course_suffix: object) -> tuple[str, int, str | None] | None:
    if not isinstance(course_dept, str) or not course_dept.strip() or not isinstance(course_number, int):
        return None
    normalized = normalized_course_identity_key(
        course_dept=course_dept,
        course_number=course_number,
        course_suffix=course_suffix if isinstance(course_suffix, str) else None,
        course_quarter=None,
        course_year2=None,
    )
    if not normalized:
        return None
    parts = normalized.split("|")
    if len(parts) < 3 or not parts[0] or not parts[1]:
        return None
    suffix = parts[2].upper() if parts[2] else None
    return (parts[0].upper(), int(parts[1]), suffix)


def _course_identity_tokens(*, course_dept: object, course_number: object, course_suffix: object) -> set[str]:
    stem = _course_stem(course_dept=course_dept, course_number=course_number, course_suffix=course_suffix)
    if stem is None:
        return set()
    dept, number, suffix = stem
    suffix_text = suffix or ""
    return {
        f"{dept} {number}{suffix_text}".lower(),
        f"{dept}{number}{suffix_text}".lower(),
    }


def _failed(code: str, message: str, *, status: ConnectorResultStatus) -> ConnectorFetchOutcome:
    return ConnectorFetchOutcome(
        status=status,
        cursor_patch={},
        parse_payload=None,
        error_code=code,
        error_message=message,
    )


def _no_change(*, cursor_patch: dict | None = None) -> ConnectorFetchOutcome:
    return ConnectorFetchOutcome(
        status=ConnectorResultStatus.NO_CHANGE,
        cursor_patch=cursor_patch or {},
        parse_payload=None,
        error_code=None,
        error_message=None,
    )


__all__ = ["fetch_gmail_changes", "matches_gmail_source_filters"]
