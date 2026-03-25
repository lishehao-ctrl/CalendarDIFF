from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.input import InputSource
from app.db.models.review import Change, ChangeReviewBucket, EventEntity, EventEntityLifecycle, ReviewStatus
from app.db.models.shared import (
    CourseRawTypeSuggestion,
    CourseRawTypeSuggestionStatus,
    CourseWorkItemLabelFamily,
    CourseWorkItemRawType,
    User,
)
from app.modules.common.structured_copy import render_structured_text
from app.modules.sources.source_runtime_state import derive_source_runtime_states
from app.modules.sources.source_serializers import serialize_source
from app.modules.sources.sources_service import list_input_sources
from app.modules.sources.status_projection import (
    build_source_observability_payload,
    build_source_operator_guidance_payload,
    build_sync_progress_payload,
    get_display_sync_request_for_source,
)
from app.modules.workbench.workspace_posture import build_workspace_posture, compute_monitoring_live_since


def get_changes_workbench_summary(
    db: Session,
    *,
    user_id: int,
    language_code: str | None = None,
) -> dict:
    user = db.scalar(select(User).where(User.id == user_id).limit(1))
    baseline_review_total = int(
        db.scalar(
            select(func.count(Change.id)).where(
                Change.user_id == user_id,
                Change.review_bucket == ChangeReviewBucket.INITIAL_REVIEW,
            )
        )
        or 0
    )
    changes_pending = int(
        db.scalar(
            select(func.count(Change.id)).where(
                Change.user_id == user_id,
                Change.review_status == ReviewStatus.PENDING,
                Change.review_bucket == ChangeReviewBucket.CHANGES,
            )
        )
        or 0
    )
    baseline_review_pending = int(
        db.scalar(
            select(func.count(Change.id)).where(
                Change.user_id == user_id,
                Change.review_status == ReviewStatus.PENDING,
                Change.review_bucket == ChangeReviewBucket.INITIAL_REVIEW,
            )
        )
        or 0
    )
    baseline_review_reviewed = max(baseline_review_total - baseline_review_pending, 0)
    baseline_review_completed_at = (
        db.scalar(
            select(func.max(Change.reviewed_at)).where(
                Change.user_id == user_id,
                Change.review_bucket == ChangeReviewBucket.INITIAL_REVIEW,
                Change.review_status.in_((ReviewStatus.APPROVED, ReviewStatus.REJECTED)),
            )
        )
        if baseline_review_pending == 0 and baseline_review_total > 0
        else None
    )
    pending_raw_type_suggestions = int(
        db.scalar(
            select(func.count(CourseRawTypeSuggestion.id))
            .join(CourseWorkItemRawType, CourseRawTypeSuggestion.source_raw_type_id == CourseWorkItemRawType.id)
            .join(CourseWorkItemLabelFamily, CourseWorkItemRawType.family_id == CourseWorkItemLabelFamily.id)
            .where(
                CourseWorkItemLabelFamily.user_id == user_id,
                CourseRawTypeSuggestion.status == CourseRawTypeSuggestionStatus.PENDING,
            )
        )
        or 0
    )
    mappings_failed = bool(
        user is not None
        and (
            str(user.work_item_mappings_state or "").lower() == "failed"
            or bool(user.work_item_mappings_last_error)
        )
    )
    families_attention_count = pending_raw_type_suggestions + (1 if mappings_failed else 0)
    manual_active_count = int(
        db.scalar(
            select(func.count(EventEntity.id)).where(
                EventEntity.user_id == user_id,
                EventEntity.manual_support.is_(True),
                EventEntity.lifecycle == EventEntityLifecycle.ACTIVE,
            )
        )
        or 0
    )
    sources_summary, source_observability_rows = _build_sources_workbench_summary(
        db=db,
        user_id=user_id,
        language_code=language_code,
    )
    (
        recommended_lane,
        recommended_lane_reason_code,
        recommended_action_reason,
        recommended_action_reason_code,
        recommended_action_reason_params,
    ) = _recommend_workbench_lane(
        baseline_review_pending=baseline_review_pending,
        changes_pending=changes_pending,
        families_attention_count=families_attention_count,
        sources_summary=sources_summary,
        language_code=language_code,
    )
    workspace_posture = build_workspace_posture(
        baseline_review_pending=baseline_review_pending,
        baseline_review_reviewed=baseline_review_reviewed,
        baseline_review_total=baseline_review_total,
        baseline_review_completed_at=baseline_review_completed_at,
        changes_pending=changes_pending,
        families_attention_count=families_attention_count,
        manual_active_count=manual_active_count,
        sources_summary=sources_summary,
        source_product_phases=[
            str(row.get("source_product_phase") or "")
            for row in source_observability_rows
            if isinstance(row, dict)
        ],
        monitoring_live_since=compute_monitoring_live_since(source_observability_rows=source_observability_rows),
        replay_active=any(
            isinstance(row, dict)
            and isinstance(row.get("active"), dict)
            and str((row.get("active") or {}).get("phase") or "") == "replay"
            and str((row.get("active") or {}).get("status") or "") in {"PENDING", "QUEUED", "RUNNING"}
            for row in source_observability_rows
        ),
        language_code=language_code,
    )
    return {
        "changes_pending": changes_pending,
        "baseline_review_pending": baseline_review_pending,
        "recommended_lane": recommended_lane,
        "recommended_lane_reason_code": recommended_lane_reason_code,
        "recommended_action_reason": recommended_action_reason,
        "recommended_action_reason_code": recommended_action_reason_code,
        "recommended_action_reason_params": recommended_action_reason_params,
        "workspace_posture": workspace_posture,
        "sources": sources_summary,
        "families": {
            "attention_count": families_attention_count,
            "pending_raw_type_suggestions": pending_raw_type_suggestions,
            "mappings_state": user.work_item_mappings_state if user is not None else "idle",
            "last_rebuilt_at": user.work_item_mappings_last_rebuilt_at if user is not None else None,
            "last_error": user.work_item_mappings_last_error if user is not None else None,
        },
        "manual": {
            "active_event_count": manual_active_count,
            "lane_role": "fallback",
        },
        "generated_at": datetime.now(timezone.utc),
    }


def _build_sources_workbench_summary(
    db: Session,
    *,
    user_id: int,
    language_code: str | None = None,
) -> tuple[dict, list[dict]]:
    source_rows = list_input_sources(db, user_id=user_id, status="active")
    if not source_rows:
        message_code = "workbench.sources_summary.sources_missing"
        return (
            {
                "active_count": 0,
                "running_count": 0,
                "queued_count": 0,
                "attention_count": 0,
                "blocking_count": 0,
                "recommended_action": "continue_review",
                "severity": "info",
                "reason_code": "sources_missing",
                "message": render_structured_text(
                    code=message_code,
                    language_code=language_code,
                    fallback="No active sources are connected yet.",
                ),
                "message_code": message_code,
                "message_params": {},
                "related_request_id": None,
                "progress_age_seconds": None,
            },
            [],
        )

    projections = derive_source_runtime_states(db, sources=source_rows)
    running_count = 0
    queued_count = 0
    attention_count = 0
    blocking_count = 0
    strongest_guidance: dict | None = None
    source_observability_rows: list[dict] = []

    for row in source_rows:
        runtime_state = projections.get(row.id)
        if runtime_state is not None:
            if runtime_state.sync_state == "running":
                running_count += 1
            elif runtime_state.sync_state == "queued":
                queued_count += 1
        observability = build_source_observability_payload(db, source_id=row.id, language_code=language_code)
        source_observability_rows.append(observability)
        guidance = observability.get("operator_guidance") if isinstance(observability, dict) else None
        if not isinstance(guidance, dict):
            guidance = _build_source_guidance_payload(db=db, source=row, language_code=language_code)
        if str(guidance.get("recommended_action") or "") != "continue_review":
            attention_count += 1
        if str(guidance.get("severity") or "") == "blocking":
            blocking_count += 1
        if _guidance_rank(guidance) > _guidance_rank(strongest_guidance):
            strongest_guidance = guidance

    aggregate = strongest_guidance or {
        "recommended_action": "continue_review",
        "severity": "info",
        "reason_code": "source_idle",
        "message": render_structured_text(
            code="sources.operator_guidance.source_idle",
            language_code=language_code,
            fallback="No active sync is running. Continue reviewing changes.",
        ),
        "message_code": "sources.operator_guidance.source_idle",
        "message_params": {},
        "related_request_id": None,
        "progress_age_seconds": None,
    }
    return (
        {
            "active_count": len(source_rows),
            "running_count": running_count,
            "queued_count": queued_count,
            "attention_count": attention_count,
            "blocking_count": blocking_count,
            "recommended_action": aggregate["recommended_action"],
            "severity": aggregate["severity"],
            "reason_code": aggregate["reason_code"],
            "message": aggregate["message"],
            "message_code": aggregate.get("message_code") or aggregate["reason_code"],
            "message_params": aggregate.get("message_params") or {},
            "related_request_id": aggregate.get("related_request_id"),
            "progress_age_seconds": aggregate.get("progress_age_seconds"),
        },
        source_observability_rows,
    )


def _build_source_guidance_payload(db: Session, *, source: InputSource, language_code: str | None = None) -> dict:
    observability = build_source_observability_payload(db, source_id=source.id, language_code=language_code)
    guidance = observability.get("operator_guidance") if isinstance(observability, dict) else None
    if isinstance(guidance, dict):
        return guidance
    active_sync = get_display_sync_request_for_source(db, source_id=source.id)
    sync_progress = build_sync_progress_payload(db, sync_request=active_sync) if active_sync is not None else None
    active_payload = (
        {
            "request_id": active_sync.request_id,
            "status": active_sync.status.value,
            "stage": active_sync.stage.value if active_sync.stage is not None else None,
            "substage": active_sync.substage,
            "stage_updated_at": active_sync.stage_updated_at,
            "updated_at": active_sync.updated_at,
            "progress": sync_progress,
        }
        if active_sync is not None
        else None
    )
    return build_source_operator_guidance_payload(
        active_payload=active_payload,
        latest_replay_payload=None,
        bootstrap_payload=None,
        language_code=language_code,
    ) or {
        "recommended_action": "continue_review",
        "severity": "info",
        "reason_code": "source_idle",
        "message": render_structured_text(
            code="sources.operator_guidance.source_idle",
            language_code=language_code,
            fallback="No active sync is running. Continue reviewing changes.",
        ),
        "message_code": "sources.operator_guidance.source_idle",
        "message_params": {},
        "related_request_id": None,
        "progress_age_seconds": None,
    }


def _recommend_workbench_lane(
    *,
    baseline_review_pending: int,
    changes_pending: int,
    families_attention_count: int,
    sources_summary: dict,
    language_code: str | None = None,
) -> tuple[str | None, str, str, str, dict]:
    if int(sources_summary.get("blocking_count") or 0) > 0:
        code = "workbench.summary.runtime_attention_required"
        return (
            "sources",
            "runtime_attention_required",
            render_structured_text(
                code=code,
                language_code=language_code,
                fallback="Source runtime needs attention before relying on lane state to be current.",
            ),
            code,
            {},
        )
    if baseline_review_pending > 0:
        code = "workbench.summary.baseline_review_pending"
        params = {"pending_count": baseline_review_pending}
        return (
            "initial_review",
            "baseline_review_pending",
            render_structured_text(
                code=code,
                language_code=language_code,
                params=params,
                fallback=f"{baseline_review_pending} baseline import items still need initial review before daily replay becomes the default workflow.",
            ),
            code,
            params,
        )
    if changes_pending > 0:
        code = "workbench.summary.changes_pending"
        params = {"pending_count": changes_pending}
        return (
            "changes",
            "changes_pending",
            render_structured_text(
                code=code,
                language_code=language_code,
                params=params,
                fallback=f"{changes_pending} pending change proposals are waiting for review decisions.",
            ),
            code,
            params,
        )
    if families_attention_count > 0:
        code = "workbench.summary.family_governance_pending"
        params = {"attention_count": families_attention_count}
        return (
            "families",
            "family_governance_pending",
            render_structured_text(
                code=code,
                language_code=language_code,
                params=params,
                fallback="Family or raw-type governance items need attention.",
            ),
            code,
            params,
        )
    code = "workbench.summary.all_clear"
    return (
        None,
        "all_clear",
        render_structured_text(code=code, language_code=language_code, fallback="No immediate lane action is required."),
        code,
        {},
    )


def _guidance_rank(guidance: dict | None) -> tuple[int, int]:
    if not isinstance(guidance, dict):
        return (0, 0)
    severity = str(guidance.get("severity") or "")
    recommended_action = str(guidance.get("recommended_action") or "")
    severity_rank = {"info": 1, "warning": 2, "blocking": 3}.get(severity, 0)
    action_rank = {
        "continue_review": 1,
        "continue_review_with_caution": 2,
        "wait_for_runtime": 3,
        "investigate_runtime": 4,
    }.get(recommended_action, 0)
    return (severity_rank, action_rank)


__all__ = ["get_changes_workbench_summary"]
