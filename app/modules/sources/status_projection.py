from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.runtime import (
    CalendarComponentParseStatus,
    CalendarComponentParseTask,
    IngestJob,
    IngestResult,
    IngestUnresolvedRecord,
)
from app.db.models.input import IngestTriggerType, SyncRequest, SyncRequestStage, SyncRequestStatus
from app.db.models.review import (
    Change,
    ChangeIntakePhase,
    ChangeReviewBucket,
    ChangeSourceRef,
    IngestApplyLog,
    ReviewStatus,
)
from app.modules.llm_gateway.usage_tracking import LLM_USAGE_SUMMARY_KEY, present_llm_usage_summary

INFLIGHT_SYNC_STATUSES = (SyncRequestStatus.PENDING, SyncRequestStatus.QUEUED, SyncRequestStatus.RUNNING)
_DISPLAY_STATUS_PRIORITY = {
    SyncRequestStatus.RUNNING: 0,
    SyncRequestStatus.QUEUED: 1,
    SyncRequestStatus.PENDING: 2,
}


def build_sync_request_status_payload(db: Session, *, sync_request: SyncRequest) -> dict:
    result = db.scalar(select(IngestResult).where(IngestResult.request_id == sync_request.request_id))
    apply_log = db.scalar(select(IngestApplyLog).where(IngestApplyLog.request_id == sync_request.request_id))
    effective_stage, effective_substage, effective_stage_updated_at = _build_effective_stage_payload(
        db,
        sync_request=sync_request,
        result=result,
        apply_log=apply_log,
    )
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
        "stage": effective_stage,
        "substage": effective_substage,
        "stage_updated_at": effective_stage_updated_at,
        "idempotency_key": sync_request.idempotency_key,
        "trace_id": sync_request.trace_id,
        "error_code": sync_request.error_code,
        "error_message": sync_request.error_message,
        "metadata": sync_request.metadata_json or {},
        "created_at": sync_request.created_at,
        "updated_at": sync_request.updated_at,
        "connector_result": connector_result,
        "llm_usage": _extract_llm_usage_payload(sync_request),
        "elapsed_ms": _compute_elapsed_ms(sync_request=sync_request, apply_log=apply_log),
        "applied": apply_log is not None,
        "applied_at": apply_log.applied_at if apply_log is not None else None,
        "progress": progress,
    }


def build_source_observability_payload(db: Session, *, source_id: int) -> dict:
    sync_rows = list(
        db.scalars(
            select(SyncRequest)
            .where(SyncRequest.source_id == source_id)
            .order_by(SyncRequest.created_at.asc(), SyncRequest.id.asc())
        ).all()
    )
    if not sync_rows:
        return {
            "source_id": source_id,
            "active_request_id": None,
            "bootstrap": None,
            "bootstrap_summary": {
                "imported_count": 0,
                "review_required_count": 0,
                "ignored_count": 0,
                "conflict_count": 0,
                "state": "idle",
            },
            "latest_replay": None,
            "active": None,
            "operator_guidance": {
                "recommended_action": "continue_review",
                "severity": "info",
                "reason_code": "source_idle",
                "message": "No active sync is running. Continue reviewing changes.",
                "related_request_id": None,
                "progress_age_seconds": None,
            },
        }

    bootstrap_row = _resolve_bootstrap_sync_row(db, sync_rows=sync_rows)
    latest_replay_row = _latest_replay_sync_row(sync_rows=sync_rows, bootstrap_request_id=bootstrap_row.request_id if bootstrap_row is not None else None)
    active_row = get_display_sync_request_for_source(db, source_id=source_id)

    bootstrap_payload = _serialize_source_observability_sync(db, row=bootstrap_row, phase="bootstrap")
    latest_replay_payload = _serialize_source_observability_sync(db, row=latest_replay_row, phase="replay")
    active_payload = _serialize_source_observability_sync(
        db,
        row=active_row,
        phase=_derive_phase_for_row(row=active_row, bootstrap_request_id=bootstrap_row.request_id),
    )
    return {
        "source_id": source_id,
        "active_request_id": active_row.request_id if active_row is not None else None,
        "bootstrap": bootstrap_payload,
        "bootstrap_summary": _build_source_bootstrap_summary_payload(
            db,
            source_id=source_id,
            bootstrap_row=bootstrap_row,
            bootstrap_payload=bootstrap_payload,
            active_payload=active_payload,
        ),
        "latest_replay": latest_replay_payload,
        "active": active_payload,
        "operator_guidance": build_source_operator_guidance_payload(
            active_payload=active_payload,
            latest_replay_payload=latest_replay_payload,
            bootstrap_payload=bootstrap_payload,
        ),
    }


def build_source_sync_history_payload(
    db: Session,
    *,
    source_id: int,
    limit: int,
) -> dict:
    sync_rows = list(
        db.scalars(
            select(SyncRequest)
            .where(SyncRequest.source_id == source_id)
            .order_by(SyncRequest.created_at.asc(), SyncRequest.id.asc())
        ).all()
    )
    if not sync_rows:
        return {
            "source_id": source_id,
            "items": [],
        }

    bootstrap_row = _resolve_bootstrap_sync_row(db, sync_rows=sync_rows)
    bootstrap_request_id = bootstrap_row.request_id if bootstrap_row is not None else sync_rows[0].request_id
    selected_rows = list(reversed(sync_rows))[:limit]
    items = [
        _serialize_source_observability_sync(
            db,
            row=row,
            phase=_derive_phase_for_row(row=row, bootstrap_request_id=bootstrap_request_id),
        )
        for row in selected_rows
    ]
    return {
        "source_id": source_id,
        "items": [item for item in items if isinstance(item, dict)],
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


def _resolve_bootstrap_sync_row(db: Session, *, sync_rows: list[SyncRequest]) -> SyncRequest | None:
    if not sync_rows:
        return None
    request_ids = [row.request_id for row in sync_rows if isinstance(row.request_id, str) and row.request_id]
    applied_request_ids = set(
        db.scalars(select(IngestApplyLog.request_id).where(IngestApplyLog.request_id.in_(request_ids))).all()
    ) if request_ids else set()
    for row in sync_rows:
        if row.request_id in applied_request_ids:
            return row
    for row in sync_rows:
        if row.status in INFLIGHT_SYNC_STATUSES:
            return row
    for row in sync_rows:
        if row.status != SyncRequestStatus.FAILED:
            return row
    return sync_rows[0]


def _latest_replay_sync_row(*, sync_rows: list[SyncRequest], bootstrap_request_id: str | None) -> SyncRequest | None:
    for row in reversed(sync_rows):
        if bootstrap_request_id is not None and row.request_id == bootstrap_request_id:
            continue
        return row
    return None


def _build_source_bootstrap_summary_payload(
    db: Session,
    *,
    source_id: int,
    bootstrap_row: SyncRequest | None,
    bootstrap_payload: dict | None,
    active_payload: dict | None,
) -> dict:
    imported_count = int(
        db.scalar(
            select(func.count(func.distinct(Change.id)))
            .select_from(Change)
            .join(ChangeSourceRef, ChangeSourceRef.change_id == Change.id)
            .where(
                ChangeSourceRef.source_id == source_id,
                Change.intake_phase == ChangeIntakePhase.BASELINE,
            )
        )
        or 0
    )
    review_required_count = int(
        db.scalar(
            select(func.count(func.distinct(Change.id)))
            .select_from(Change)
            .join(ChangeSourceRef, ChangeSourceRef.change_id == Change.id)
            .where(
                ChangeSourceRef.source_id == source_id,
                Change.intake_phase == ChangeIntakePhase.BASELINE,
                Change.review_bucket == ChangeReviewBucket.INITIAL_REVIEW,
                Change.review_status == ReviewStatus.PENDING,
            )
        )
        or 0
    )
    ignored_count, conflict_count = _count_bootstrap_unresolved(
        db,
        source_id=source_id,
        bootstrap_request_id=bootstrap_row.request_id if bootstrap_row is not None else None,
    )

    state = "idle"
    active_phase = str(active_payload.get("phase") or "") if isinstance(active_payload, dict) else ""
    active_status = str(active_payload.get("status") or "") if isinstance(active_payload, dict) else ""
    bootstrap_status = str(bootstrap_payload.get("status") or "") if isinstance(bootstrap_payload, dict) else ""
    if active_phase == "bootstrap" and active_status in {"PENDING", "QUEUED", "RUNNING"}:
        state = "running"
    elif review_required_count > 0:
        state = "review_required"
    elif bootstrap_status == "SUCCEEDED":
        state = "completed"

    return {
        "imported_count": imported_count,
        "review_required_count": review_required_count,
        "ignored_count": ignored_count,
        "conflict_count": conflict_count,
        "state": state,
    }


def _count_bootstrap_unresolved(db: Session, *, source_id: int, bootstrap_request_id: str | None) -> tuple[int, int]:
    if not bootstrap_request_id:
        return 0, 0
    rows = db.execute(
        select(IngestUnresolvedRecord.reason_code, func.count(IngestUnresolvedRecord.id))
        .where(
            IngestUnresolvedRecord.source_id == source_id,
            IngestUnresolvedRecord.request_id == bootstrap_request_id,
        )
        .group_by(IngestUnresolvedRecord.reason_code)
    ).all()
    ignored_reason_codes = {
        "directive_monitoring_window_out_of_scope",
        "directive_monitoring_window_out_of_scope_partial",
        "directive_product_scope_excluded",
        "directive_unsupported_or_no_effect",
        "monitoring_window_out_of_scope",
        "product_scope_excluded",
    }
    ignored_count = 0
    conflict_count = 0
    for reason_code, count in rows:
        normalized_reason = str(reason_code or "")
        if normalized_reason in ignored_reason_codes:
            ignored_count += int(count or 0)
        else:
            conflict_count += int(count or 0)
    return ignored_count, conflict_count


def build_sync_progress_payload(
    db: Session,
    *,
    sync_request: SyncRequest,
    result: IngestResult | None = None,
    apply_log: IngestApplyLog | None = None,
) -> dict | None:
    explicit_progress = _build_explicit_progress_payload(sync_request=sync_request)
    if explicit_progress is not None:
        return explicit_progress

    # Minimal fallback for pre-migration historical rows.
    if sync_request.status == SyncRequestStatus.PENDING:
        return {
            "phase": "pending",
            "label": "Waiting for source turn",
            "detail": "This sync is queued behind an earlier source job.",
            "updated_at": sync_request.updated_at,
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
            "updated_at": sync_request.updated_at,
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
            "updated_at": result.fetched_at,
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
            "updated_at": sync_request.updated_at,
            "current": None,
            "total": None,
            "percent": None,
            "unit": None,
        }
    return None


def _build_effective_stage_payload(
    db: Session,
    *,
    sync_request: SyncRequest,
    result: IngestResult | None,
    apply_log: IngestApplyLog | None,
) -> tuple[str | None, str | None, datetime | None]:
    explicit_stage = sync_request.stage.value if getattr(sync_request, "stage", None) is not None else None
    explicit_substage = sync_request.substage
    explicit_updated_at = sync_request.stage_updated_at
    if isinstance(sync_request.progress_json, dict):
        return explicit_stage, explicit_substage, explicit_updated_at

    job = db.scalar(select(IngestJob).where(IngestJob.request_id == sync_request.request_id))
    payload = job.payload_json if job is not None and isinstance(job.payload_json, dict) else {}
    workflow_stage = payload.get("workflow_stage")
    if isinstance(workflow_stage, str):
        mapped = _legacy_stage_from_workflow_stage(workflow_stage=workflow_stage)
        if mapped is not None:
            progress_updated_at = payload.get("sync_progress_updated_at")
            if isinstance(progress_updated_at, str) and progress_updated_at:
                normalized_updated_at = datetime.fromisoformat(
                    progress_updated_at[:-1] + "+00:00" if progress_updated_at.endswith("Z") else progress_updated_at
                )
            else:
                normalized_updated_at = job.updated_at if job is not None else sync_request.updated_at
            return mapped[0], mapped[1], normalized_updated_at

    if result is not None and apply_log is None:
        return SyncRequestStage.RESULT_READY.value, "result_ready", result.fetched_at
    if apply_log is not None:
        return SyncRequestStage.COMPLETED.value, "apply_completed", apply_log.applied_at
    return explicit_stage, explicit_substage, explicit_updated_at


def _legacy_stage_from_workflow_stage(*, workflow_stage: str) -> tuple[str, str] | None:
    normalized = workflow_stage.strip().upper()
    mapping = {
        "LLM_ENQUEUE_PENDING": (SyncRequestStage.LLM_QUEUE.value, "parse_payload_ready"),
        "LLM_QUEUED": (SyncRequestStage.LLM_PARSE.value, "llm_task_queued"),
        "LLM_RUNNING": (SyncRequestStage.LLM_PARSE.value, "llm_parse"),
        "LLM_CALENDAR_FANOUT_QUEUED": (SyncRequestStage.LLM_PARSE.value, "calendar_child_queue"),
        "LLM_CALENDAR_REDUCE_WAITING": (SyncRequestStage.PROVIDER_REDUCE.value, "calendar_reduce_wait"),
        "LLM_RATE_LIMIT_BACKPRESSURE": (SyncRequestStage.LLM_PARSE.value, "llm_backpressure"),
        "CONNECTOR_RETRY_WAITING": (SyncRequestStage.CONNECTOR_FETCH.value, "connector_retry_waiting"),
        "CONNECTOR_DEAD_LETTER": (SyncRequestStage.FAILED.value, "connector_dead_letter"),
        "LLM_DEAD_LETTER": (SyncRequestStage.FAILED.value, "llm_dead_letter"),
    }
    return mapping.get(normalized)


def _build_explicit_progress_payload(*, sync_request: SyncRequest) -> dict | None:
    progress = sync_request.progress_json if isinstance(sync_request.progress_json, dict) else None
    if progress is not None:
        return _normalize_progress_payload(progress, updated_at=sync_request.stage_updated_at)

    stage = getattr(sync_request, "stage", None)
    if stage is None:
        return None
    if stage == SyncRequestStage.CONNECTOR_FETCH:
        if sync_request.status == SyncRequestStatus.PENDING:
            return {
                "phase": "pending",
                "label": "Waiting for source turn",
                "detail": "This sync is queued behind an earlier source job.",
                "updated_at": sync_request.stage_updated_at or sync_request.updated_at,
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
                "updated_at": sync_request.stage_updated_at or sync_request.updated_at,
                "current": None,
                "total": None,
                "percent": None,
                "unit": None,
            }
    if stage == SyncRequestStage.COMPLETED:
        return {
            "phase": "completed",
            "label": "Sync completed",
            "detail": "The sync finished successfully.",
            "updated_at": sync_request.stage_updated_at or sync_request.updated_at,
            "current": None,
            "total": None,
            "percent": None,
            "unit": None,
        }
    if stage == SyncRequestStage.FAILED:
        return {
            "phase": "failed",
            "label": "Sync failed",
            "detail": sync_request.error_message or "The sync failed.",
            "updated_at": sync_request.stage_updated_at or sync_request.updated_at,
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
            progress_payload = _normalize_progress_payload(progress)
            progress_updated_at = payload.get("sync_progress_updated_at")
            if isinstance(progress_updated_at, str) and progress_updated_at:
                progress_payload["updated_at"] = progress_updated_at
            return progress_payload
        parse_payload = payload.get("llm_parse_payload")
        if isinstance(parse_payload, dict) and parse_payload.get("kind") == "gmail":
            messages = parse_payload.get("messages")
            total = len(messages) if isinstance(messages, list) else 0
            if total > 0:
                return {
                    "phase": "gmail_llm_queue",
                    "label": "Queued for Gmail extraction",
                    "detail": f"{total} emails are ready for LLM extraction.",
                    "updated_at": payload.get("llm_enqueue_pending_at"),
                    "current": total,
                    "total": total,
                    "percent": 100,
                    "unit": "emails",
                }
    if provider_name in {"ics", "calendar"}:
        progress = payload.get("sync_progress")
        if isinstance(progress, dict) and payload.get("workflow_stage") != "LLM_CALENDAR_FANOUT_QUEUED":
            progress_payload = _normalize_progress_payload(progress)
            progress_updated_at = payload.get("sync_progress_updated_at")
            if isinstance(progress_updated_at, str) and progress_updated_at:
                progress_payload["updated_at"] = progress_updated_at
            return progress_payload
        component_counts, latest_component_updated_at = _calendar_component_progress_snapshot(db, request_id=request_id)
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
                "updated_at": latest_component_updated_at,
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
                    "updated_at": payload.get("llm_enqueue_pending_at"),
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
                    "updated_at": payload.get("llm_enqueue_pending_at"),
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


def _calendar_component_progress_snapshot(db: Session, *, request_id: str) -> tuple[dict[str, int], datetime | None]:
    rows = db.execute(
        select(
            CalendarComponentParseTask.status,
            func.count(CalendarComponentParseTask.id),
            func.max(CalendarComponentParseTask.updated_at),
        )
        .where(CalendarComponentParseTask.request_id == request_id)
        .group_by(CalendarComponentParseTask.status)
    ).all()
    counts: dict[str, int] = {}
    latest_updated_at: datetime | None = None
    for status, count, updated_at in rows:
        counts[status.value] = int(count)
        if isinstance(updated_at, datetime) and (latest_updated_at is None or updated_at > latest_updated_at):
            latest_updated_at = updated_at
    return counts, latest_updated_at


def _normalize_progress_payload(progress: dict, *, updated_at: datetime | None = None) -> dict:
    current = _coerce_optional_int(progress.get("current"))
    total = _coerce_optional_int(progress.get("total"))
    percent = _coerce_optional_float(progress.get("percent"))
    if percent is None and current is not None and total not in {None, 0}:
        percent = _percent(current, total)
    payload_updated_at = progress.get("updated_at")
    normalized_updated_at = payload_updated_at if payload_updated_at is not None else updated_at
    return {
        "phase": str(progress.get("phase") or "running"),
        "label": str(progress.get("label") or "Running"),
        "detail": str(progress.get("detail")) if progress.get("detail") is not None else None,
        "updated_at": normalized_updated_at,
        "current": current,
        "total": total,
        "percent": percent,
        "unit": str(progress.get("unit")) if progress.get("unit") is not None else None,
    }


def _serialize_source_observability_sync(
    db: Session,
    *,
    row: SyncRequest | None,
    phase: str | None,
) -> dict | None:
    if row is None or phase not in {"bootstrap", "replay"}:
        return None
    payload = build_sync_request_status_payload(db, sync_request=row)
    return {
        "request_id": payload["request_id"],
        "phase": phase,
        "trigger_type": payload["trigger_type"],
        "status": payload["status"],
        "stage": payload.get("stage"),
        "substage": payload.get("substage"),
        "stage_updated_at": payload.get("stage_updated_at"),
        "created_at": payload["created_at"],
        "updated_at": payload["updated_at"],
        "applied": payload["applied"],
        "applied_at": payload["applied_at"],
        "elapsed_ms": payload["elapsed_ms"],
        "error_code": payload["error_code"],
        "error_message": payload["error_message"],
        "connector_result": payload["connector_result"],
        "llm_usage": payload["llm_usage"],
        "progress": payload["progress"],
    }


def build_source_operator_guidance_payload(
    *,
    active_payload: dict | None,
    latest_replay_payload: dict | None,
    bootstrap_payload: dict | None,
) -> dict | None:
    if isinstance(active_payload, dict):
        status = str(active_payload.get("status") or "")
        stage = str(active_payload.get("stage") or "")
        request_id = str(active_payload.get("request_id") or "") or None
        progress = active_payload.get("progress") if isinstance(active_payload.get("progress"), dict) else {}
        updated_at = (
            progress.get("updated_at")
            if isinstance(progress.get("updated_at"), str) and progress.get("updated_at")
            else active_payload.get("stage_updated_at") or active_payload.get("updated_at")
        )
        age_seconds = _progress_age_seconds(updated_at)
        if status in {"PENDING", "QUEUED"}:
            return {
                "recommended_action": "continue_review",
                "severity": "info",
                "reason_code": "sync_queued",
                "message": "Source sync is queued. Continue reviewing current changes; more changes may appear later.",
                "related_request_id": request_id,
                "progress_age_seconds": age_seconds,
            }
        if status == "RUNNING":
            if stage in {"provider_reduce", "applying"} and age_seconds is not None and age_seconds >= 180:
                return {
                    "recommended_action": "wait_for_runtime",
                    "severity": "blocking",
                    "reason_code": "sync_progress_stale",
                    "message": "This source has not reported fresh progress recently. Wait for runtime recovery before making lane-changing decisions.",
                    "related_request_id": request_id,
                    "progress_age_seconds": age_seconds,
                }
            return {
                "recommended_action": "continue_review_with_caution",
                "severity": "warning",
                "reason_code": "sync_running",
                "message": "This source is still processing. You can review current changes, but new changes may still arrive.",
                "related_request_id": request_id,
                "progress_age_seconds": age_seconds,
            }
        if status == "FAILED" or stage == "failed":
            return {
                "recommended_action": "investigate_runtime",
                "severity": "blocking",
                "reason_code": "active_sync_failed",
                "message": "The active source sync failed. Investigate runtime health before trusting this lane to be current.",
                "related_request_id": request_id,
                "progress_age_seconds": age_seconds,
            }

    for payload in (latest_replay_payload, bootstrap_payload):
        if not isinstance(payload, dict):
            continue
        if str(payload.get("status") or "") != "FAILED":
            continue
        return {
            "recommended_action": "investigate_runtime",
            "severity": "blocking",
            "reason_code": "latest_sync_failed",
            "message": "The latest source sync failed. Investigate source/runtime health before trusting this lane to be current.",
            "related_request_id": str(payload.get("request_id") or "") or None,
            "progress_age_seconds": None,
        }

    return {
        "recommended_action": "continue_review",
        "severity": "info",
        "reason_code": "source_idle",
        "message": "No active sync is running. Continue reviewing changes.",
        "related_request_id": None,
        "progress_age_seconds": None,
    }


def _progress_age_seconds(updated_at_raw: object) -> int | None:
    if isinstance(updated_at_raw, datetime):
        updated_at = updated_at_raw
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        else:
            updated_at = updated_at.astimezone(UTC)
    else:
        if not isinstance(updated_at_raw, str) or not updated_at_raw:
            return None
        try:
            updated_at = datetime.fromisoformat(updated_at_raw[:-1] + "+00:00" if updated_at_raw.endswith("Z") else updated_at_raw)
        except Exception:
            return None
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        else:
            updated_at = updated_at.astimezone(UTC)
    return int(max((datetime.now(UTC) - updated_at).total_seconds(), 0))


def _derive_phase_for_row(*, row: SyncRequest | None, bootstrap_request_id: str) -> str | None:
    if row is None:
        return None
    return "bootstrap" if row.request_id == bootstrap_request_id else "replay"


def _extract_llm_usage_payload(sync_request: SyncRequest) -> dict | None:
    metadata = sync_request.metadata_json if isinstance(sync_request.metadata_json, dict) else {}
    usage = metadata.get(LLM_USAGE_SUMMARY_KEY)
    return present_llm_usage_summary(usage if isinstance(usage, dict) else None)


def _compute_elapsed_ms(*, sync_request: SyncRequest, apply_log: IngestApplyLog | None) -> int | None:
    ended_at = apply_log.applied_at if apply_log is not None else sync_request.updated_at
    if ended_at is None or sync_request.created_at is None:
        return None
    started_at = sync_request.created_at.astimezone(UTC)
    ended = ended_at.astimezone(UTC)
    return max(int((ended - started_at).total_seconds() * 1000), 0)


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
