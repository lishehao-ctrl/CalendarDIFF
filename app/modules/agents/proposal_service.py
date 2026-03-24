from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.agents import AgentProposal, AgentProposalStatus, AgentProposalType
from app.modules.agents.service import (
    AgentContextNotFoundError,
    build_change_agent_context,
    build_family_agent_context,
    build_source_agent_context,
)
from app.modules.families.family_service import get_course_work_item_family
from app.modules.families.raw_type_service import get_course_raw_type


class AgentProposalInvalidStateError(RuntimeError):
    def __init__(self, *, code: str, message: str, message_code: str) -> None:
        super().__init__(message)
        self.detail = {
            "code": code,
            "message": message,
            "message_code": message_code,
            "message_params": {},
        }


def create_change_decision_proposal(db: Session, *, user_id: int, change_id: int) -> AgentProposal:
    context = build_change_agent_context(db=db, user_id=user_id, change_id=change_id)
    change = context["change"]
    if str(change.get("review_status") or "") != "pending":
        raise AgentProposalInvalidStateError(
            code="agents.proposals.change.already_reviewed",
            message="Change is no longer pending review",
            message_code="agents.proposals.change.already_reviewed",
        )
    support = change.get("decision_support") or {}
    suggested_action = str((context.get("recommended_next_action") or {}).get("recommended_tool") or "")
    action_kind = str(support.get("suggested_action") or "review_carefully")
    proposal = AgentProposal(
        user_id=user_id,
        proposal_type=AgentProposalType.CHANGE_DECISION,
        status=AgentProposalStatus.OPEN,
        target_kind="change",
        target_id=str(change_id),
        summary=_change_summary(action_kind=action_kind, review_bucket=str(change.get("review_bucket") or "changes")),
        summary_code=f"agents.proposals.change_decision.{action_kind}.summary",
        reason=str(support.get("suggested_action_reason") or ""),
        reason_code=str(support.get("suggested_action_reason_code") or "agents.proposals.change_decision.reason"),
        risk_level=str(support.get("risk_level") or "medium"),
        confidence=_confidence_for_risk_level(str(support.get("risk_level") or "medium")),
        suggested_action=action_kind,
        payload_json=_jsonable(_change_payload(change_id=change_id, action_kind=action_kind)),
        context_json=_jsonable(_minimal_change_context_snapshot(context=context)),
        target_snapshot_json=_jsonable(
            {
                "change_id": change_id,
                "review_status": change.get("review_status"),
                "review_bucket": change.get("review_bucket"),
                "intake_phase": change.get("intake_phase"),
                "detected_at": change.get("detected_at"),
            }
        ),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
    return proposal


def create_source_recovery_proposal(db: Session, *, user_id: int, source_id: int) -> AgentProposal:
    context = build_source_agent_context(db=db, user_id=user_id, source_id=source_id)
    source = context["source"]
    observability = context["observability"]
    recovery = observability.get("source_recovery") or {}
    guidance = observability.get("operator_guidance") or {}
    suggested_action = str(recovery.get("next_action") or "wait")
    proposal = AgentProposal(
        user_id=user_id,
        proposal_type=AgentProposalType.SOURCE_RECOVERY,
        status=AgentProposalStatus.OPEN,
        target_kind="source",
        target_id=str(source_id),
        summary=_source_summary(provider=str(source.get("provider") or "source"), action=suggested_action),
        summary_code=f"agents.proposals.source_recovery.{suggested_action}.summary",
        reason=str(guidance.get("message") or recovery.get("impact_summary") or ""),
        reason_code=str(guidance.get("reason_code") or recovery.get("impact_code") or "agents.proposals.source_recovery.reason"),
        risk_level=str((context.get("recommended_next_action") or {}).get("risk_level") or "medium"),
        confidence=_confidence_for_risk_level(str((context.get("recommended_next_action") or {}).get("risk_level") or "medium")),
        suggested_action=suggested_action,
        payload_json=_jsonable(_source_payload(source_id=source_id, action=suggested_action, provider=str(source.get("provider") or ""))),
        context_json=_jsonable(_minimal_source_context_snapshot(context=context)),
        target_snapshot_json=_jsonable(
            {
                "source_id": source_id,
                "active_request_id": source.get("active_request_id"),
                "runtime_state": source.get("runtime_state"),
                "source_product_phase": source.get("source_product_phase"),
                "trust_state": recovery.get("trust_state"),
            }
        ),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=12),
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
    return proposal


def create_family_relink_preview_proposal(
    db: Session,
    *,
    user_id: int,
    raw_type_id: int,
    family_id: int,
) -> AgentProposal:
    raw_type = get_course_raw_type(db, user_id=user_id, raw_type_id=raw_type_id)
    if raw_type is None:
        raise AgentContextNotFoundError(
            code="agents.context.raw_type_not_found",
            message="Observed label not found",
            message_code="agents.context.raw_type_not_found",
        )
    target_family = get_course_work_item_family(db, user_id=user_id, family_id=family_id)
    if target_family is None:
        raise AgentContextNotFoundError(
            code="agents.context.family_not_found",
            message="Family not found",
            message_code="agents.context.family_not_found",
        )
    current_family = raw_type.family
    if current_family is not None and int(current_family.id) == int(target_family.id):
        raise AgentProposalInvalidStateError(
            code="agents.proposals.family.already_in_family",
            message="Observed label is already mapped to this canonical family",
            message_code="agents.proposals.family.already_in_family",
        )
    family_context = build_family_agent_context(db=db, user_id=user_id, family_id=family_id)
    matching_suggestion = next(
        (
            row
            for row in family_context.get("pending_raw_type_suggestions") or []
            if int(row.get("source_raw_type_id") or 0) == int(raw_type_id)
            and int(row.get("suggested_family_id") or 0) == int(family_id)
        ),
        None,
    )
    risk_level = "low" if matching_suggestion is not None else "medium"
    proposal = AgentProposal(
        user_id=user_id,
        proposal_type=AgentProposalType.FAMILY_RELINK_PREVIEW,
        status=AgentProposalStatus.OPEN,
        target_kind="family_relink",
        target_id=f"{raw_type_id}:{family_id}",
        summary=_family_relink_summary(raw_type=raw_type.raw_type, target_family=target_family.canonical_label),
        summary_code="agents.proposals.family_relink_preview.summary",
        reason=_family_relink_reason(
            raw_type=raw_type.raw_type,
            current_family=current_family.canonical_label if current_family is not None else None,
            target_family=target_family.canonical_label,
            matching_suggestion=matching_suggestion,
        ),
        reason_code="agents.proposals.family_relink_preview.reason",
        risk_level=risk_level,
        confidence=_confidence_for_risk_level(risk_level),
        suggested_action="preview_relink",
        payload_json=_jsonable(
            {
                "kind": "web_only_family_relink_preview",
                "raw_type_id": raw_type_id,
                "family_id": family_id,
            }
        ),
        context_json=_jsonable(
            {
                "raw_type_id": raw_type.id,
                "raw_type": raw_type.raw_type,
                "current_family_id": current_family.id if current_family is not None else None,
                "current_family_name": current_family.canonical_label if current_family is not None else None,
                "target_family_context": family_context,
                "matching_suggestion": matching_suggestion,
            }
        ),
        target_snapshot_json=_jsonable(
            {
                "raw_type_id": raw_type.id,
                "raw_type": raw_type.raw_type,
                "current_family_id": current_family.id if current_family is not None else None,
                "target_family_id": target_family.id,
                "target_family_name": target_family.canonical_label,
                "course_display": (family_context.get("family") or {}).get("course_display"),
            }
        ),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=12),
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
    return proposal


def get_agent_proposal(db: Session, *, user_id: int, proposal_id: int) -> AgentProposal | None:
    return db.scalar(
        select(AgentProposal)
        .where(AgentProposal.id == proposal_id, AgentProposal.user_id == user_id)
        .limit(1)
    )


def _change_summary(*, action_kind: str, review_bucket: str) -> str:
    lane_label = "Initial Review" if review_bucket == "initial_review" else "Replay Review"
    return {
        "approve": f"Approve this change in {lane_label}.",
        "reject": f"Reject this change in {lane_label}.",
        "edit": f"Open web edit flow before approving this change in {lane_label}.",
        "review_carefully": f"Review this high-risk change carefully in {lane_label}.",
    }.get(action_kind, f"Review this change in {lane_label}.")


def _source_summary(*, provider: str, action: str) -> str:
    provider_label = "Gmail" if provider == "gmail" else "Canvas ICS" if provider == "ics" else provider.title() or "Source"
    return {
        "reconnect_gmail": f"Reconnect {provider_label} before trusting this source again.",
        "retry_sync": f"Run another sync for {provider_label}.",
        "update_ics": f"Update {provider_label} settings before the next sync.",
        "wait": f"Wait for {provider_label} runtime progress before taking further action.",
    }.get(action, f"Review {provider_label} source posture.")


def _change_payload(*, change_id: int, action_kind: str) -> dict:
    if action_kind in {"approve", "reject"}:
        return {
            "kind": "change_decision",
            "change_id": change_id,
            "decision": action_kind,
        }
    if action_kind == "edit":
        return {
            "kind": "web_only_change_edit_required",
            "change_id": change_id,
        }
    return {
        "kind": "web_only_high_risk_change_review",
        "change_id": change_id,
    }


def _source_payload(*, source_id: int, action: str, provider: str) -> dict:
    if action == "retry_sync":
        return {"kind": "run_source_sync", "source_id": source_id}
    if action == "reconnect_gmail":
        return {"kind": "reconnect_source", "source_id": source_id, "provider": provider}
    if action == "update_ics":
        return {"kind": "update_source_settings", "source_id": source_id, "provider": provider}
    return {"kind": "wait_for_runtime", "source_id": source_id}


def _family_relink_summary(*, raw_type: str, target_family: str) -> str:
    return f"Preview moving observed label '{raw_type}' into canonical family '{target_family}'."


def _family_relink_reason(
    *,
    raw_type: str,
    current_family: str | None,
    target_family: str,
    matching_suggestion: dict | None,
) -> str:
    if matching_suggestion is not None:
        return (
            f"A pending observed-label suggestion already points '{raw_type}' "
            f"from '{current_family or 'Unassigned'}' to '{target_family}'. "
            "Review the relink impact before applying it in the web flow."
        )
    return (
        f"Review whether observed label '{raw_type}' should move from "
        f"'{current_family or 'Unassigned'}' to '{target_family}' before changing future family mapping behavior."
    )


def _confidence_for_risk_level(risk_level: str) -> float:
    return {
        "low": 0.92,
        "medium": 0.78,
        "high": 0.56,
    }.get(risk_level, 0.7)


def _jsonable(value: object) -> dict:
    encoded = jsonable_encoder(value)
    return encoded if isinstance(encoded, dict) else {}


def _minimal_change_context_snapshot(*, context: dict) -> dict:
    change = context.get("change") or {}
    recommendation = context.get("recommended_next_action") or {}
    return {
        "change_id": change.get("id"),
        "review_bucket": change.get("review_bucket"),
        "intake_phase": change.get("intake_phase"),
        "review_status": change.get("review_status"),
        "decision_support": change.get("decision_support") or {},
        "recommended_next_action": recommendation,
        "blocking_conditions": context.get("blocking_conditions") or [],
    }


def _minimal_source_context_snapshot(*, context: dict) -> dict:
    source = context.get("source") or {}
    observability = context.get("observability") or {}
    recommendation = context.get("recommended_next_action") or {}
    return {
        "source_id": source.get("source_id"),
        "provider": source.get("provider"),
        "runtime_state": source.get("runtime_state"),
        "active_request_id": source.get("active_request_id"),
        "operator_guidance": observability.get("operator_guidance") or {},
        "source_recovery": observability.get("source_recovery") or {},
        "recommended_next_action": recommendation,
        "blocking_conditions": context.get("blocking_conditions") or [],
    }


__all__ = [
    "AgentProposalInvalidStateError",
    "create_change_decision_proposal",
    "create_family_relink_preview_proposal",
    "create_source_recovery_proposal",
    "get_agent_proposal",
]
