from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.ingestion import CalendarComponentParseStatus, CalendarComponentParseTask, IngestJob, IngestResult
from app.db.models.input import SyncRequest, SyncRequestStatus
from app.db.models.review import IngestApplyLog

INFLIGHT_SYNC_STATUSES = (SyncRequestStatus.PENDING, SyncRequestStatus.QUEUED, SyncRequestStatus.RUNNING)
_DISPLAY_STATUS_PRIORITY = {
    SyncRequestStatus.RUNNING: 0,
    SyncRequestStatus.QUEUED: 1,
    SyncRequestStatus.PENDING: 2,
}


def build_sync_request_status_payload(db: Session, *, sync_request: SyncRequest) -> dict:
    result = db.scalar(select(IngestResult).where(IngestResult.request_id == sync_request.request_id))
    apply_log = db.scalar(select(IngestApplyLog).where(IngestApplyLog.request_id == sync_request.request_id))
    progress = build_sync_progress_payload(db, sync_request=sync_request, result=result, apply_log=apply_log)
    connector_result: dict | None = None
    if result is not None:
        connector_result = {
            "provider": result.provider,
            "status": result.status.value,
            "fetched_at": result.fetched_at,
            "error_code": result.error_code,
            "error_message": result.error_message,
            "records_count": len(result.records or []),
        }
    return {
        "request_id": sync_request.request_id,
        "source_id": sync_request.source_id,
        "trigger_type": sync_request.trigger_type.value,
        "status": sync_request.status.value,
        "idempotency_key": sync_request.idempotency_key,
        "trace_id": sync_request.trace_id,
        "error_code": sync_request.error_code,
        "error_message": sync_request.error_message,
        "metadata": sync_request.metadata_json or {},
        "created_at": sync_request.created_at,
        "updated_at": sync_request.updated_at,
        "connector_result": connector_result,
        "applied": apply_log is not None,
        "applied_at": apply_log.applied_at if apply_log is not None else None,
        "progress": progress,
    }


def get_display_sync_request_for_source(db: Session, *, source_id: int) -> SyncRequest | None:
    rows = list(
        db.scalars(
            select(SyncRequest)
            .where(
                SyncRequest.source_id == source_id,
                SyncRequest.status.in_(INFLIGHT_SYNC_STATUSES),
            )
            .order_by(SyncRequest.created_at.asc(), SyncRequest.id.asc())
        ).all()
    )
    if not rows:
        return None
    rows.sort(key=lambda row: (_DISPLAY_STATUS_PRIORITY[row.status], row.created_at, row.id))
    return rows[0]


def build_sync_progress_payload(
    db: Session,
    *,
    sync_request: SyncRequest,
    result: IngestResult | None = None,
    apply_log: IngestApplyLog | None = None,
) -> dict | None:
    if sync_request.status == SyncRequestStatus.PENDING:
        return {
            "phase": "pending",
            "label": "Waiting for source turn",
            "detail": "This sync is queued behind an earlier source job.",
            "current": None,
            "total": None,
            "percent": None,
            "unit": None,
        }
    if sync_request.status == SyncRequestStatus.QUEUED:
        return {
            "phase": "queued",
            "label": "Queued to run",
            "detail": "The worker has accepted this sync and will start it soon.",
            "current": None,
            "total": None,
            "percent": None,
            "unit": None,
        }

    job = db.scalar(select(IngestJob).where(IngestJob.request_id == sync_request.request_id))
    if job is not None:
        payload = job.payload_json if isinstance(job.payload_json, dict) else {}
        progress = _build_job_progress_payload(
            db,
            request_id=sync_request.request_id,
            payload=payload,
            result=result,
            apply_log=apply_log,
        )
        if progress is not None:
            return progress

    if result is not None and apply_log is None:
        record_count = len(result.records or [])
        return {
            "phase": "applying",
            "label": "Applying extracted results",
            "detail": f"{record_count} parsed records are being applied to observations and review.",
            "current": record_count if record_count > 0 else None,
            "total": record_count if record_count > 0 else None,
            "percent": 100 if record_count > 0 else None,
            "unit": "records" if record_count > 0 else None,
        }

    if sync_request.status == SyncRequestStatus.RUNNING:
        return {
            "phase": "running",
            "label": "Running",
            "detail": "The backend is still processing this sync.",
            "current": None,
            "total": None,
            "percent": None,
            "unit": None,
        }
    return None


def _build_job_progress_payload(
    db: Session,
    *,
    request_id: str,
    payload: dict,
    result: IngestResult | None,
    apply_log: IngestApplyLog | None,
) -> dict | None:
    provider = payload.get("provider")
    provider_name = provider.strip().lower() if isinstance(provider, str) else None
    workflow_stage = payload.get("workflow_stage")
    if provider_name == "gmail":
        progress = payload.get("sync_progress") or payload.get("gmail_progress")
        if isinstance(progress, dict):
            return _normalize_progress_payload(progress)
        parse_payload = payload.get("llm_parse_payload")
        if isinstance(parse_payload, dict) and parse_payload.get("kind") == "gmail":
            messages = parse_payload.get("messages")
            total = len(messages) if isinstance(messages, list) else 0
            if total > 0:
                return {
                    "phase": "gmail_llm_queue",
                    "label": "Queued for Gmail extraction",
                    "detail": f"{total} emails are ready for LLM extraction.",
                    "current": total,
                    "total": total,
                    "percent": 100,
                    "unit": "emails",
                }
    if provider_name in {"ics", "calendar"}:
        progress = payload.get("sync_progress")
        if isinstance(progress, dict) and payload.get("workflow_stage") != "LLM_CALENDAR_FANOUT_QUEUED":
            return _normalize_progress_payload(progress)
        component_counts = _calendar_component_status_counts(db, request_id=request_id)
        total_components = sum(component_counts.values())
        if total_components > 0:
            completed_components = (
                component_counts.get(CalendarComponentParseStatus.SUCCEEDED.value, 0)
                + component_counts.get(CalendarComponentParseStatus.UNRESOLVED.value, 0)
                + component_counts.get(CalendarComponentParseStatus.FAILED.value, 0)
            )
            return {
                "phase": "calendar_parsing" if completed_components < total_components else "calendar_reducing",
                "label": "Parsing calendar events" if completed_components < total_components else "Reducing parsed events",
                "detail": f"{completed_components} of {total_components} calendar events have finished parsing.",
                "current": completed_components,
                "total": total_components,
                "percent": _percent(completed_components, total_components),
                "unit": "events",
            }
        parse_payload = payload.get("llm_parse_payload")
        if isinstance(parse_payload, dict) and parse_payload.get("kind") == "calendar_delta":
            changed_components = parse_payload.get("changed_components")
            removed_components = parse_payload.get("removed_component_keys")
            changed_total = len(changed_components) if isinstance(changed_components, list) else 0
            removed_total = len(removed_components) if isinstance(removed_components, list) else 0
            if changed_total > 0:
                return {
                    "phase": "calendar_queueing",
                    "label": "Preparing calendar event parses",
                    "detail": f"{changed_total} calendar events are queued for parsing."
                    + (f" {removed_total} removals are waiting for reducer apply." if removed_total > 0 else ""),
                    "current": 0,
                    "total": changed_total,
                    "percent": 0,
                    "unit": "events",
                }
            if removed_total > 0:
                return {
                    "phase": "calendar_removed_only",
                    "label": "Applying calendar removals",
                    "detail": f"{removed_total} removed calendar items are waiting for apply.",
                    "current": removed_total,
                    "total": removed_total,
                    "percent": 100,
                    "unit": "events",
                }
    if result is not None and apply_log is None:
        record_count = len(result.records or [])
        return {
            "phase": "applying",
            "label": "Applying extracted results",
            "detail": f"{record_count} parsed records are being applied to observations and review.",
            "current": record_count if record_count > 0 else None,
            "total": record_count if record_count > 0 else None,
            "percent": 100 if record_count > 0 else None,
            "unit": "records" if record_count > 0 else None,
        }
    if workflow_stage == "LLM_ENQUEUE_PENDING":
        return {
            "phase": "llm_enqueue_pending",
            "label": "Waiting to queue parser",
            "detail": "Connector fetch finished and the parser queue is the next step.",
            "current": None,
            "total": None,
            "percent": None,
            "unit": None,
        }
    return None


def _calendar_component_status_counts(db: Session, *, request_id: str) -> dict[str, int]:
    rows = db.execute(
        select(CalendarComponentParseTask.status, func.count(CalendarComponentParseTask.id))
        .where(CalendarComponentParseTask.request_id == request_id)
        .group_by(CalendarComponentParseTask.status)
    ).all()
    return {status.value: int(count) for status, count in rows}


def _normalize_progress_payload(progress: dict) -> dict:
    current = _coerce_optional_int(progress.get("current"))
    total = _coerce_optional_int(progress.get("total"))
    percent = _coerce_optional_float(progress.get("percent"))
    if percent is None and current is not None and total not in {None, 0}:
        percent = _percent(current, total)
    return {
        "phase": str(progress.get("phase") or "running"),
        "label": str(progress.get("label") or "Running"),
        "detail": str(progress.get("detail")) if progress.get("detail") is not None else None,
        "current": current,
        "total": total,
        "percent": percent,
        "unit": str(progress.get("unit")) if progress.get("unit") is not None else None,
    }


def _coerce_optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _coerce_optional_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _percent(current: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round((current / total) * 100, 1)


__all__ = [
    "build_sync_progress_payload",
    "build_sync_request_status_payload",
    "get_display_sync_request_for_source",
]
