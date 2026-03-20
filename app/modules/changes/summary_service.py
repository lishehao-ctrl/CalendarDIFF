from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.input import InputSource
from app.db.models.review import Change, ChangeReviewBucket, ReviewStatus
from app.db.models.review import EventEntity, EventEntityLifecycle
from app.db.models.shared import (
    CourseRawTypeSuggestion,
    CourseRawTypeSuggestionStatus,
    CourseWorkItemLabelFamily,
    CourseWorkItemRawType,
    User,
)
from app.modules.sources.sources_service import list_input_sources
from app.modules.sources.source_runtime_state import derive_source_runtime_states
from app.modules.sources.status_projection import (
    build_source_observability_payload,
    build_source_operator_guidance_payload,
    build_sync_progress_payload,
    get_display_sync_request_for_source,
)

def get_changes_workbench_summary(
    db: Session,
    *,
    user_id: int,
) -> dict:
    user = db.scalar(select(User).where(User.id == user_id).limit(1))
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
    sources_summary = _build_sources_workbench_summary(db=db, user_id=user_id)
    recommended_lane, recommended_lane_reason_code, recommended_action_reason = _recommend_workbench_lane(
        baseline_review_pending=baseline_review_pending,
        changes_pending=changes_pending,
        families_attention_count=families_attention_count,
        sources_summary=sources_summary,
    )
    return {
        "changes_pending": changes_pending,
        "baseline_review_pending": baseline_review_pending,
        "recommended_lane": recommended_lane,
        "recommended_lane_reason_code": recommended_lane_reason_code,
        "recommended_action_reason": recommended_action_reason,
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


def _build_sources_workbench_summary(db: Session, *, user_id: int) -> dict:
    source_rows = list_input_sources(db, user_id=user_id, status="active")
    if not source_rows:
        return {
            "active_count": 0,
            "running_count": 0,
            "queued_count": 0,
            "attention_count": 0,
            "blocking_count": 0,
            "recommended_action": "continue_review",
            "severity": "info",
            "reason_code": "sources_missing",
            "message": "No active sources are connected yet.",
            "related_request_id": None,
            "progress_age_seconds": None,
        }

    projections = derive_source_runtime_states(db, sources=source_rows)
    running_count = 0
    queued_count = 0
    attention_count = 0
    blocking_count = 0
    strongest_guidance: dict | None = None

    for row in source_rows:
        runtime_state = projections.get(row.id)
        if runtime_state is not None:
            if runtime_state.sync_state == "running":
                running_count += 1
            elif runtime_state.sync_state == "queued":
                queued_count += 1
        guidance = _build_source_guidance_payload(db=db, source=row)
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
        "message": "No active sync is running. Continue reviewing changes.",
        "related_request_id": None,
        "progress_age_seconds": None,
    }
    return {
        "active_count": len(source_rows),
        "running_count": running_count,
        "queued_count": queued_count,
        "attention_count": attention_count,
        "blocking_count": blocking_count,
        "recommended_action": aggregate["recommended_action"],
        "severity": aggregate["severity"],
        "reason_code": aggregate["reason_code"],
        "message": aggregate["message"],
        "related_request_id": aggregate.get("related_request_id"),
        "progress_age_seconds": aggregate.get("progress_age_seconds"),
    }


def _build_source_guidance_payload(db: Session, *, source: InputSource) -> dict:
    observability = build_source_observability_payload(db, source_id=source.id)
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
    ) or {
        "recommended_action": "continue_review",
        "severity": "info",
        "reason_code": "source_idle",
        "message": "No active sync is running. Continue reviewing changes.",
        "related_request_id": None,
        "progress_age_seconds": None,
    }


def _recommend_workbench_lane(
    *,
    baseline_review_pending: int,
    changes_pending: int,
    families_attention_count: int,
    sources_summary: dict,
) -> tuple[str | None, str, str]:
    if int(sources_summary.get("blocking_count") or 0) > 0:
        return (
            "sources",
            "runtime_attention_required",
            "Source runtime needs attention before relying on lane state to be current.",
        )
    if baseline_review_pending > 0:
        return (
            "initial_review",
            "baseline_review_pending",
            f"{baseline_review_pending} baseline import items still need initial review before daily replay becomes the default workflow.",
        )
    if changes_pending > 0:
        return (
            "changes",
            "changes_pending",
            f"{changes_pending} pending change proposals are waiting for review decisions.",
        )
    if families_attention_count > 0:
        return (
            "families",
            "family_governance_pending",
            "Family or raw-type governance items need attention.",
        )
    return (None, "all_clear", "No immediate lane action is required.")


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
