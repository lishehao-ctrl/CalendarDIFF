from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.agents import AgentProposal, AgentProposalStatus, AgentProposalType
from app.db.models.review import Change, ChangeType, ReviewStatus
from app.modules.agents.family_relink_projection import (
    FamilyRelinkProjectionValidationError,
    build_family_relink_projection,
)
from app.modules.agents.label_learning_projection import (
    LabelLearningProjectionValidationError,
    build_label_learning_projection,
)
from app.modules.agents.generation_gateway import (
    AgentProposalDraft,
    AgentProposalDraftRequest,
    generate_agent_proposal_draft,
)
from app.modules.agents.service import (
    AgentContextNotFoundError,
    build_change_agent_context,
    build_source_agent_context,
)
from app.modules.changes.edit_service import (
    ChangeEditInvalidStateError,
    ChangeEditNotFoundError,
    ChangeEditValidationError,
    preview_change_edit,
)
from app.modules.common.stable_json_hash import stable_json_hash


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
    return create_change_decision_proposal_with_origin(
        db=db,
        user_id=user_id,
        change_id=change_id,
        origin_kind="web",
        origin_label="embedded_agent",
    )


def create_change_decision_proposal_with_origin(
    db: Session,
    *,
    user_id: int,
    change_id: int,
    origin_kind: str,
    origin_label: str,
    origin_request_id: str | None = None,
    language_code: str | None = None,
) -> AgentProposal:
    context = build_change_agent_context(db=db, user_id=user_id, change_id=change_id, language_code=language_code)
    change = context["change"]
    if str(change.get("review_status") or "") != "pending":
        raise AgentProposalInvalidStateError(
            code="agents.proposals.change.already_reviewed",
            message="Change is no longer pending review",
            message_code="agents.proposals.change.already_reviewed",
        )
    support = change.get("decision_support") or {}
    action_kind = str(support.get("suggested_action") or "review_carefully")
    draft = generate_agent_proposal_draft(
        db=db,
        draft_request=AgentProposalDraftRequest(
            proposal_kind="change_decision",
            target_kind="change",
            target_id=str(change_id),
            origin_request_id=origin_request_id,
            deterministic_draft=AgentProposalDraft(
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
            ),
        ),
    )
    proposal = AgentProposal(
        user_id=user_id,
        proposal_type=AgentProposalType.CHANGE_DECISION,
        status=AgentProposalStatus.OPEN,
        target_kind="change",
        target_id=str(change_id),
        summary=draft.summary,
        summary_code=draft.summary_code,
        reason=draft.reason,
        reason_code=draft.reason_code,
        risk_level=draft.risk_level,
        confidence=draft.confidence,
        suggested_action=draft.suggested_action,
        origin_kind=(origin_kind.strip()[:32] or "unknown"),
        origin_label=(origin_label.strip()[:64] or "unknown"),
        origin_request_id=origin_request_id.strip()[:64] if isinstance(origin_request_id, str) and origin_request_id.strip() else None,
        payload_json=draft.payload_json,
        context_json=draft.context_json,
        target_snapshot_json=draft.target_snapshot_json,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
    return proposal


def create_source_recovery_proposal(db: Session, *, user_id: int, source_id: int) -> AgentProposal:
    return create_source_recovery_proposal_with_origin(
        db=db,
        user_id=user_id,
        source_id=source_id,
        origin_kind="web",
        origin_label="embedded_agent",
    )


def create_source_recovery_proposal_with_origin(
    db: Session,
    *,
    user_id: int,
    source_id: int,
    origin_kind: str,
    origin_label: str,
    origin_request_id: str | None = None,
    language_code: str | None = None,
) -> AgentProposal:
    context = build_source_agent_context(db=db, user_id=user_id, source_id=source_id, language_code=language_code)
    source = context["source"]
    observability = context["observability"]
    recovery = observability.get("source_recovery") or {}
    guidance = observability.get("operator_guidance") or {}
    suggested_action = str(recovery.get("next_action") or "wait")
    draft = generate_agent_proposal_draft(
        db=db,
        draft_request=AgentProposalDraftRequest(
            proposal_kind="source_recovery",
            target_kind="source",
            target_id=str(source_id),
            origin_request_id=origin_request_id,
            deterministic_draft=AgentProposalDraft(
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
            ),
        ),
    )
    proposal = AgentProposal(
        user_id=user_id,
        proposal_type=AgentProposalType.SOURCE_RECOVERY,
        status=AgentProposalStatus.OPEN,
        target_kind="source",
        target_id=str(source_id),
        summary=draft.summary,
        summary_code=draft.summary_code,
        reason=draft.reason,
        reason_code=draft.reason_code,
        risk_level=draft.risk_level,
        confidence=draft.confidence,
        suggested_action=draft.suggested_action,
        origin_kind=(origin_kind.strip()[:32] or "unknown"),
        origin_label=(origin_label.strip()[:64] or "unknown"),
        origin_request_id=origin_request_id.strip()[:64] if isinstance(origin_request_id, str) and origin_request_id.strip() else None,
        payload_json=draft.payload_json,
        context_json=draft.context_json,
        target_snapshot_json=draft.target_snapshot_json,
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
    return create_family_relink_preview_proposal_with_origin(
        db=db,
        user_id=user_id,
        raw_type_id=raw_type_id,
        family_id=family_id,
        origin_kind="web",
        origin_label="embedded_agent",
    )


def create_family_relink_commit_proposal(
    db: Session,
    *,
    user_id: int,
    raw_type_id: int,
    family_id: int,
) -> AgentProposal:
    return create_family_relink_commit_proposal_with_origin(
        db=db,
        user_id=user_id,
        raw_type_id=raw_type_id,
        family_id=family_id,
        origin_kind="web",
        origin_label="embedded_agent",
    )


def create_label_learning_commit_proposal(
    db: Session,
    *,
    user_id: int,
    change_id: int,
    family_id: int,
) -> AgentProposal:
    return create_label_learning_commit_proposal_with_origin(
        db=db,
        user_id=user_id,
        change_id=change_id,
        family_id=family_id,
        origin_kind="web",
        origin_label="embedded_agent",
    )


def create_change_edit_commit_proposal(
    db: Session,
    *,
    user_id: int,
    change_id: int,
    patch: dict,
) -> AgentProposal:
    return create_change_edit_commit_proposal_with_origin(
        db=db,
        user_id=user_id,
        change_id=change_id,
        patch=patch,
        origin_kind="web",
        origin_label="embedded_agent",
    )


def create_family_relink_preview_proposal_with_origin(
    db: Session,
    *,
    user_id: int,
    raw_type_id: int,
    family_id: int,
    origin_kind: str,
    origin_label: str,
    origin_request_id: str | None = None,
) -> AgentProposal:
    projection = _build_family_relink_projection_or_raise(
        db=db,
        user_id=user_id,
        raw_type_id=raw_type_id,
        family_id=family_id,
    )
    raw_type_snapshot = projection["raw_type"]
    current_family_snapshot = projection["current_family"]
    target_family_snapshot = projection["target_family"]
    impact = projection["impact"]
    risk_level = str(impact.get("risk_level") or "medium")
    draft = generate_agent_proposal_draft(
        db=db,
        draft_request=AgentProposalDraftRequest(
            proposal_kind="family_relink_preview",
            target_kind="family_relink",
            target_id=f"{raw_type_id}:{family_id}",
            origin_request_id=origin_request_id,
            deterministic_draft=AgentProposalDraft(
                summary=_family_relink_preview_summary(
                    raw_type=str(raw_type_snapshot.get("raw_type") or ""),
                    target_family=str(target_family_snapshot.get("canonical_label") or ""),
                ),
                summary_code="agents.proposals.family_relink_preview.summary",
                reason=_family_relink_preview_reason(
                    raw_type=str(raw_type_snapshot.get("raw_type") or ""),
                    current_family=str(current_family_snapshot.get("canonical_label") or ""),
                    target_family=str(target_family_snapshot.get("canonical_label") or ""),
                    impacted_event_count=int(impact.get("impacted_event_count") or 0),
                    impacted_pending_change_count=int(impact.get("impacted_pending_change_count") or 0),
                    matching_suggestion_count=int(impact.get("matching_suggestion_count") or 0),
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
                context_json=_jsonable(projection),
                target_snapshot_json=_jsonable(_family_relink_target_snapshot(projection=projection)),
            ),
        ),
    )
    proposal = AgentProposal(
        user_id=user_id,
        proposal_type=AgentProposalType.FAMILY_RELINK_PREVIEW,
        status=AgentProposalStatus.OPEN,
        target_kind="family_relink",
        target_id=f"{raw_type_id}:{family_id}",
        summary=draft.summary,
        summary_code=draft.summary_code,
        reason=draft.reason,
        reason_code=draft.reason_code,
        risk_level=draft.risk_level,
        confidence=draft.confidence,
        suggested_action=draft.suggested_action,
        origin_kind=(origin_kind.strip()[:32] or "unknown"),
        origin_label=(origin_label.strip()[:64] or "unknown"),
        origin_request_id=origin_request_id.strip()[:64] if isinstance(origin_request_id, str) and origin_request_id.strip() else None,
        payload_json=draft.payload_json,
        context_json=draft.context_json,
        target_snapshot_json=draft.target_snapshot_json,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=12),
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
    return proposal


def create_family_relink_commit_proposal_with_origin(
    db: Session,
    *,
    user_id: int,
    raw_type_id: int,
    family_id: int,
    origin_kind: str,
    origin_label: str,
    origin_request_id: str | None = None,
) -> AgentProposal:
    projection = _build_family_relink_projection_or_raise(
        db=db,
        user_id=user_id,
        raw_type_id=raw_type_id,
        family_id=family_id,
    )
    impact = projection["impact"]
    risk_level = str(impact.get("risk_level") or "medium")
    if risk_level != "low":
        raise AgentProposalInvalidStateError(
            code="agents.proposals.family.commit_not_low_risk",
            message="Observed label relink needs the web workflow before it can be committed.",
            message_code="agents.proposals.family.commit_not_low_risk",
        )
    raw_type_snapshot = projection["raw_type"]
    current_family_snapshot = projection["current_family"]
    target_family_snapshot = projection["target_family"]
    draft = generate_agent_proposal_draft(
        db=db,
        draft_request=AgentProposalDraftRequest(
            proposal_kind="family_relink_preview",
            target_kind="family_relink",
            target_id=f"{raw_type_id}:{family_id}",
            origin_request_id=origin_request_id,
            deterministic_draft=AgentProposalDraft(
                summary=_family_relink_commit_summary(
                    raw_type=str(raw_type_snapshot.get("raw_type") or ""),
                    target_family=str(target_family_snapshot.get("canonical_label") or ""),
                ),
                summary_code="agents.proposals.family_relink_commit.summary",
                reason=_family_relink_commit_reason(
                    raw_type=str(raw_type_snapshot.get("raw_type") or ""),
                    current_family=str(current_family_snapshot.get("canonical_label") or ""),
                    target_family=str(target_family_snapshot.get("canonical_label") or ""),
                    impacted_event_count=int(impact.get("impacted_event_count") or 0),
                    impacted_pending_change_count=int(impact.get("impacted_pending_change_count") or 0),
                ),
                reason_code="agents.proposals.family_relink_commit.reason",
                risk_level="low",
                confidence=_confidence_for_risk_level("low"),
                suggested_action="commit_relink",
                payload_json=_jsonable(
                    {
                        "kind": "family_relink_commit",
                        "raw_type_id": raw_type_id,
                        "family_id": family_id,
                    }
                ),
                context_json=_jsonable(projection),
                target_snapshot_json=_jsonable(_family_relink_target_snapshot(projection=projection)),
            ),
        ),
    )
    proposal = AgentProposal(
        user_id=user_id,
        proposal_type=AgentProposalType.FAMILY_RELINK_PREVIEW,
        status=AgentProposalStatus.OPEN,
        target_kind="family_relink",
        target_id=f"{raw_type_id}:{family_id}",
        summary=draft.summary,
        summary_code=draft.summary_code,
        reason=draft.reason,
        reason_code=draft.reason_code,
        risk_level=draft.risk_level,
        confidence=draft.confidence,
        suggested_action=draft.suggested_action,
        origin_kind=(origin_kind.strip()[:32] or "unknown"),
        origin_label=(origin_label.strip()[:64] or "unknown"),
        origin_request_id=origin_request_id.strip()[:64] if isinstance(origin_request_id, str) and origin_request_id.strip() else None,
        payload_json=draft.payload_json,
        context_json=draft.context_json,
        target_snapshot_json=draft.target_snapshot_json,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=12),
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
    return proposal


def create_change_edit_commit_proposal_with_origin(
    db: Session,
    *,
    user_id: int,
    change_id: int,
    patch: dict,
    origin_kind: str,
    origin_label: str,
    origin_request_id: str | None = None,
) -> AgentProposal:
    change = _load_change_edit_commit_target_or_raise(db=db, user_id=user_id, change_id=change_id)
    try:
        preview = preview_change_edit(
            db=db,
            user_id=user_id,
            mode="proposal",
            change_id=change_id,
            entity_uid=None,
            patch=patch,
            reason=None,
        )
    except ChangeEditNotFoundError as exc:
        raise AgentContextNotFoundError(
            code="agents.context.change_not_found",
            message=str(exc),
            message_code="agents.context.change_not_found",
        ) from exc
    except ChangeEditInvalidStateError as exc:
        raise AgentProposalInvalidStateError(
            code="agents.proposals.change_edit.invalid_state",
            message=str(exc),
            message_code="agents.proposals.change_edit.invalid_state",
        ) from exc
    except ChangeEditValidationError as exc:
        raise AgentProposalInvalidStateError(
            code="agents.proposals.change_edit.invalid_patch",
            message=str(exc),
            message_code="agents.proposals.change_edit.invalid_patch",
        ) from exc

    serialized_patch = _jsonable(patch)
    patch_fields = sorted(serialized_patch.keys())
    draft = generate_agent_proposal_draft(
        db=db,
        draft_request=AgentProposalDraftRequest(
            proposal_kind="proposal_edit_commit",
            target_kind="change",
            target_id=str(change_id),
            origin_request_id=origin_request_id,
            deterministic_draft=AgentProposalDraft(
                summary=_proposal_edit_commit_summary(change_type=change.change_type.value, patch_fields=patch_fields),
                summary_code="agents.proposals.change_edit_commit.summary",
                reason=_proposal_edit_commit_reason(preview=preview, patch_fields=patch_fields),
                reason_code="agents.proposals.change_edit_commit.reason",
                risk_level="low",
                confidence=_confidence_for_risk_level("low"),
                suggested_action="commit_proposal_edit",
                payload_json=_jsonable(
                    {
                        "kind": "proposal_edit_commit",
                        "change_id": change_id,
                        "patch": serialized_patch,
                    }
                ),
                context_json=_jsonable(preview),
                target_snapshot_json=_jsonable(
                    {
                        "change_id": change.id,
                        "review_status": change.review_status.value,
                        "change_type": change.change_type.value,
                        "current_after_payload_hash": stable_json_hash(change.after_semantic_json or {}),
                        "current_before_payload_hash": (
                            stable_json_hash(change.before_semantic_json)
                            if isinstance(change.before_semantic_json, dict)
                            else None
                        ),
                        "patch_fields": patch_fields,
                    }
                ),
            ),
        ),
    )
    proposal = AgentProposal(
        user_id=user_id,
        proposal_type=AgentProposalType.PROPOSAL_EDIT_COMMIT,
        status=AgentProposalStatus.OPEN,
        target_kind="change",
        target_id=str(change_id),
        summary=draft.summary,
        summary_code=draft.summary_code,
        reason=draft.reason,
        reason_code=draft.reason_code,
        risk_level=draft.risk_level,
        confidence=draft.confidence,
        suggested_action=draft.suggested_action,
        origin_kind=(origin_kind.strip()[:32] or "unknown"),
        origin_label=(origin_label.strip()[:64] or "unknown"),
        origin_request_id=origin_request_id.strip()[:64] if isinstance(origin_request_id, str) and origin_request_id.strip() else None,
        payload_json=draft.payload_json,
        context_json=draft.context_json,
        target_snapshot_json=draft.target_snapshot_json,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=12),
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
    return proposal


def create_label_learning_commit_proposal_with_origin(
    db: Session,
    *,
    user_id: int,
    change_id: int,
    family_id: int,
    origin_kind: str,
    origin_label: str,
    origin_request_id: str | None = None,
) -> AgentProposal:
    projection = _build_label_learning_projection_or_raise(
        db=db,
        user_id=user_id,
        change_id=change_id,
        family_id=family_id,
    )
    change_snapshot = projection["change"]
    target_family_snapshot = projection["target_family"]
    impact = projection["impact"]
    draft = generate_agent_proposal_draft(
        db=db,
        draft_request=AgentProposalDraftRequest(
            proposal_kind="family_relink_preview",
            target_kind="label_learning",
            target_id=f"{change_id}:{family_id}",
            origin_request_id=origin_request_id,
            deterministic_draft=AgentProposalDraft(
                summary=_label_learning_commit_summary(
                    raw_label=str(change_snapshot.get("raw_label") or ""),
                    target_family=str(target_family_snapshot.get("canonical_label") or ""),
                ),
                summary_code="agents.proposals.label_learning_commit.summary",
                reason=_label_learning_commit_reason(
                    raw_label=str(change_snapshot.get("raw_label") or ""),
                    target_family=str(target_family_snapshot.get("canonical_label") or ""),
                    course_display=str(change_snapshot.get("course_display") or ""),
                ),
                reason_code="agents.proposals.label_learning_commit.reason",
                risk_level=str(impact.get("risk_level") or "low"),
                confidence=_confidence_for_risk_level("low"),
                suggested_action="commit_label_learning",
                payload_json=_jsonable(
                    {
                        "kind": "label_learning_add_alias_commit",
                        "change_id": change_id,
                        "family_id": family_id,
                    }
                ),
                context_json=_jsonable(projection),
                target_snapshot_json=_jsonable(
                    {
                        "change_id": change_snapshot["change_id"],
                        "raw_label": change_snapshot["raw_label"],
                        "status": change_snapshot["status"],
                        "resolved_family_id": change_snapshot.get("resolved_family_id"),
                        "target_family_id": target_family_snapshot["family_id"],
                        "target_family_name": target_family_snapshot["canonical_label"],
                        "course_display": target_family_snapshot["course_display"],
                    }
                ),
            ),
        ),
    )
    proposal = AgentProposal(
        user_id=user_id,
        proposal_type=AgentProposalType.LABEL_LEARNING_COMMIT,
        status=AgentProposalStatus.OPEN,
        target_kind="label_learning",
        target_id=f"{change_id}:{family_id}",
        summary=draft.summary,
        summary_code=draft.summary_code,
        reason=draft.reason,
        reason_code=draft.reason_code,
        risk_level=draft.risk_level,
        confidence=draft.confidence,
        suggested_action=draft.suggested_action,
        origin_kind=(origin_kind.strip()[:32] or "unknown"),
        origin_label=(origin_label.strip()[:64] or "unknown"),
        origin_request_id=origin_request_id.strip()[:64] if isinstance(origin_request_id, str) and origin_request_id.strip() else None,
        payload_json=draft.payload_json,
        context_json=draft.context_json,
        target_snapshot_json=draft.target_snapshot_json,
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


def _family_relink_preview_summary(*, raw_type: str, target_family: str) -> str:
    return f"Preview moving observed label '{raw_type}' into canonical family '{target_family}'."


def _family_relink_preview_reason(
    *,
    raw_type: str,
    current_family: str,
    target_family: str,
    impacted_event_count: int,
    impacted_pending_change_count: int,
    matching_suggestion_count: int,
) -> str:
    return (
        f"Observed label '{raw_type}' is currently mapped to '{current_family}'. "
        f"Previewing a move to '{target_family}' would affect {impacted_event_count} active events and "
        f"{impacted_pending_change_count} pending changes. Matching suggestions: {matching_suggestion_count}."
    )


def _family_relink_commit_summary(*, raw_type: str, target_family: str) -> str:
    return f"Move observed label '{raw_type}' into canonical family '{target_family}'."


def _family_relink_commit_reason(
    *,
    raw_type: str,
    current_family: str,
    target_family: str,
    impacted_event_count: int,
    impacted_pending_change_count: int,
) -> str:
    return (
        f"Observed label '{raw_type}' is currently mapped to '{current_family}'. "
        f"Committing the move to '{target_family}' would affect {impacted_event_count} active events and "
        f"{impacted_pending_change_count} pending changes."
    )


def _label_learning_commit_summary(*, raw_label: str, target_family: str) -> str:
    return f"Map observed label '{raw_label}' into canonical family '{target_family}'."


def _label_learning_commit_reason(*, raw_label: str, target_family: str, course_display: str) -> str:
    return (
        f"For {course_display}, map observed label '{raw_label}' into existing canonical family "
        f"'{target_family}' and approve the pending learned-label change."
    )


def _proposal_edit_commit_summary(*, change_type: str, patch_fields: list[str]) -> str:
    field_summary = ", ".join(patch_fields) if patch_fields else "proposal fields"
    if change_type == "created":
        return f"Commit a pending created-event proposal edit for {field_summary}."
    return f"Commit a pending due-change proposal edit for {field_summary}."


def _proposal_edit_commit_reason(*, preview: dict, patch_fields: list[str]) -> str:
    delta_seconds = preview.get("delta_seconds")
    delta_text = f"{delta_seconds} seconds" if isinstance(delta_seconds, int) else "no time delta"
    return (
        f"Updated proposal fields: {', '.join(patch_fields) or 'none'}. "
        f"The preview stays in proposal mode, keeps the change pending, and currently shows {delta_text}."
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


def _build_family_relink_projection_or_raise(
    *,
    db: Session,
    user_id: int,
    raw_type_id: int,
    family_id: int,
) -> dict:
    try:
        return build_family_relink_projection(
            db,
            user_id=user_id,
            raw_type_id=raw_type_id,
            family_id=family_id,
        )
    except FamilyRelinkProjectionValidationError as exc:
        if exc.code.startswith("agents.context."):
            raise AgentContextNotFoundError(
                code=exc.code,
                message=exc.message,
                message_code=exc.code,
            ) from exc
        raise AgentProposalInvalidStateError(
            code=exc.code,
            message=exc.message,
            message_code=exc.code,
        ) from exc


def _family_relink_target_snapshot(*, projection: dict) -> dict:
    raw_type_snapshot = projection["raw_type"]
    current_family_snapshot = projection["current_family"]
    target_family_snapshot = projection["target_family"]
    impact = projection["impact"]
    return {
        "raw_type_id": raw_type_snapshot["raw_type_id"],
        "raw_type": raw_type_snapshot["raw_type"],
        "current_family_id": current_family_snapshot["family_id"],
        "current_family_name": current_family_snapshot["canonical_label"],
        "target_family_id": target_family_snapshot["family_id"],
        "target_family_name": target_family_snapshot["canonical_label"],
        "course_display": target_family_snapshot["course_display"],
        "impacted_event_count": impact["impacted_event_count"],
        "impacted_pending_change_count": impact["impacted_pending_change_count"],
        "matching_suggestion_count": impact["matching_suggestion_count"],
    }


def _build_label_learning_projection_or_raise(
    *,
    db: Session,
    user_id: int,
    change_id: int,
    family_id: int,
) -> dict:
    try:
        return build_label_learning_projection(
            db,
            user_id=user_id,
            change_id=change_id,
            family_id=family_id,
        )
    except LabelLearningProjectionValidationError as exc:
        if exc.code.startswith("agents.context."):
            raise AgentContextNotFoundError(
                code=exc.code,
                message=exc.message,
                message_code=exc.code,
            ) from exc
        raise AgentProposalInvalidStateError(
            code=exc.code,
            message=exc.message,
            message_code=exc.code,
        ) from exc


def _load_change_edit_commit_target_or_raise(
    *,
    db: Session,
    user_id: int,
    change_id: int,
) -> Change:
    row = db.scalar(
        select(Change)
        .where(Change.id == change_id, Change.user_id == user_id)
        .limit(1)
    )
    if row is None:
        raise AgentContextNotFoundError(
            code="agents.context.change_not_found",
            message="Change not found",
            message_code="agents.context.change_not_found",
        )
    if row.review_status != ReviewStatus.PENDING:
        raise AgentProposalInvalidStateError(
            code="agents.proposals.change_edit.not_pending",
            message="Proposal edit commit requires a pending change.",
            message_code="agents.proposals.change_edit.not_pending",
        )
    if row.change_type not in {ChangeType.CREATED, ChangeType.DUE_CHANGED}:
        raise AgentProposalInvalidStateError(
            code="agents.proposals.change_edit.unsupported_change_type",
            message="Proposal edit commit only supports pending created or due_changed changes.",
            message_code="agents.proposals.change_edit.unsupported_change_type",
        )
    if not isinstance(row.after_semantic_json, dict):
        raise AgentProposalInvalidStateError(
            code="agents.proposals.change_edit.missing_payload",
            message="Pending proposal has no editable proposal payload.",
            message_code="agents.proposals.change_edit.missing_payload",
        )
    return row


__all__ = [
    "AgentProposalInvalidStateError",
    "create_change_decision_proposal",
    "create_change_decision_proposal_with_origin",
    "create_change_edit_commit_proposal",
    "create_change_edit_commit_proposal_with_origin",
    "create_family_relink_commit_proposal",
    "create_family_relink_commit_proposal_with_origin",
    "create_family_relink_preview_proposal",
    "create_family_relink_preview_proposal_with_origin",
    "create_label_learning_commit_proposal",
    "create_label_learning_commit_proposal_with_origin",
    "create_source_recovery_proposal",
    "create_source_recovery_proposal_with_origin",
    "get_agent_proposal",
]
