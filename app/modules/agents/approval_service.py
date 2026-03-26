from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.agents import ApprovalTicket, ApprovalTicketStatus, AgentProposal, AgentProposalStatus
from app.db.models.input import IngestTriggerType
from app.db.models.review import Change, ChangeType, ReviewStatus
from app.db.models.shared import CourseWorkItemLabelFamily, CourseWorkItemRawType
from app.modules.changes.edit_service import (
    ChangeEditInvalidStateError,
    ChangeEditNotFoundError,
    ChangeEditValidationError,
    apply_change_edit,
)
from app.modules.changes.label_learning_service import (
    LabelLearningNotFoundError,
    LabelLearningValidationError,
    apply_label_learning,
    preview_label_learning,
)
from app.modules.changes.change_decision_service import decide_change
from app.modules.channels.service import record_ticket_transition_delivery
from app.modules.common.api_errors import api_error_detail
from app.modules.common.stable_json_hash import stable_json_hash
from app.modules.families.application_service import FamilyApplicationValidationError, relink_raw_type_and_rebuild
from app.modules.common.source_monitoring_window import parse_source_monitoring_window, source_timezone_name
from app.modules.agents.lifecycle import (
    ticket_cancel_summary_code,
    ticket_confirm_summary_code,
    ticket_social_safe_cta_code,
    ticket_transition_message_code,
)
from app.modules.sources.read_service import build_source_read_payload
from app.modules.sources.source_monitoring_window_rebind import has_pending_monitoring_window_update
from app.modules.sources.sources_service import get_input_source
from app.modules.sources.sync_requests_service import enqueue_sync_request_idempotent


class ApprovalTicketError(RuntimeError):
    def __init__(self, *, status_code: int, code: str, message: str, message_code: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = api_error_detail(code=code, message=message, message_code=message_code)


def create_approval_ticket(
    db: Session,
    *,
    user_id: int,
    proposal_id: int,
    channel: str,
    origin_kind: str = "web",
    origin_label: str = "embedded_agent",
    origin_request_id: str | None = None,
) -> ApprovalTicket:
    proposal = db.scalar(
        select(AgentProposal)
        .where(AgentProposal.id == proposal_id, AgentProposal.user_id == user_id)
        .limit(1)
    )
    if proposal is None:
        raise ApprovalTicketError(
            status_code=404,
            code="agents.approval.proposal_not_found",
            message="Agent proposal not found",
            message_code="agents.approval.proposal_not_found",
        )
    _assert_proposal_executable(proposal)

    existing = _find_existing_live_ticket(db, proposal_id=proposal.id, user_id=user_id)
    if existing is not None and not _is_expired(existing):
        return existing

    payload = proposal.payload_json or {}
    ticket = ApprovalTicket(
        ticket_id=uuid4().hex,
        proposal_id=proposal.id,
        user_id=user_id,
        channel=channel.strip()[:32] or "web",
        action_type=str(payload.get("kind") or proposal.suggested_action),
        target_kind=proposal.target_kind,
        target_id=proposal.target_id,
        payload_json=payload,
        payload_hash=stable_json_hash(payload),
        target_snapshot_json=proposal.target_snapshot_json or {},
        risk_level=proposal.risk_level,
        origin_kind=origin_kind.strip()[:32] or "unknown",
        origin_label=origin_label.strip()[:64] or "unknown",
        origin_request_id=origin_request_id.strip()[:64] if isinstance(origin_request_id, str) and origin_request_id.strip() else None,
        status=ApprovalTicketStatus.OPEN,
        last_transition_kind=origin_kind.strip()[:32] or "unknown",
        last_transition_label=origin_label.strip()[:64] or "unknown",
        executed_result_json={},
        expires_at=proposal.expires_at,
    )
    db.add(ticket)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _find_existing_live_ticket(db, proposal_id=proposal.id, user_id=user_id)
        if existing is not None and not _is_expired(existing):
            return existing
        raise
    db.refresh(ticket)
    record_ticket_transition_delivery(
        db,
        ticket=ticket,
        summary_code=ticket_confirm_summary_code(ticket),
        detail_code=ticket_transition_message_code(ticket),
        cta_code=ticket_social_safe_cta_code(ticket),
    )
    return ticket


def _find_existing_live_ticket(db: Session, *, proposal_id: int, user_id: int) -> ApprovalTicket | None:
    return db.scalar(
        select(ApprovalTicket)
        .where(
            ApprovalTicket.proposal_id == proposal_id,
            ApprovalTicket.user_id == user_id,
            ApprovalTicket.status.in_((ApprovalTicketStatus.OPEN, ApprovalTicketStatus.EXECUTED)),
        )
        .order_by(ApprovalTicket.created_at.desc())
        .limit(1)
    )


def get_approval_ticket(db: Session, *, user_id: int, ticket_id: str) -> ApprovalTicket | None:
    return db.scalar(
        select(ApprovalTicket)
        .where(ApprovalTicket.ticket_id == ticket_id, ApprovalTicket.user_id == user_id)
        .limit(1)
    )


def confirm_approval_ticket(
    db: Session,
    *,
    user_id: int,
    ticket_id: str,
    transition_kind: str = "web",
    transition_label: str = "embedded_agent",
) -> tuple[ApprovalTicket, bool]:
    ticket = db.scalar(
        select(ApprovalTicket)
        .where(ApprovalTicket.ticket_id == ticket_id, ApprovalTicket.user_id == user_id)
        .with_for_update()
    )
    if ticket is None:
        raise ApprovalTicketError(
            status_code=404,
            code="agents.approval.ticket_not_found",
            message="Approval ticket not found",
            message_code="agents.approval.ticket_not_found",
        )
    if ticket.status == ApprovalTicketStatus.EXECUTED:
        return ticket, True
    if ticket.status == ApprovalTicketStatus.CANCELED:
        raise ApprovalTicketError(
            status_code=409,
            code="agents.approval.ticket_canceled",
            message="Approval ticket was canceled",
            message_code="agents.approval.ticket_canceled",
        )
    if _is_expired(ticket):
        ticket.status = ApprovalTicketStatus.EXPIRED
        ticket.last_transition_kind = transition_kind.strip()[:32] or "unknown"
        ticket.last_transition_label = transition_label.strip()[:64] or "unknown"
        db.commit()
        db.refresh(ticket)
        record_ticket_transition_delivery(
            db,
            ticket=ticket,
            summary_code=ticket_confirm_summary_code(ticket),
            detail_code=ticket_transition_message_code(ticket),
            cta_code=ticket_social_safe_cta_code(ticket),
        )
        raise ApprovalTicketError(
            status_code=409,
            code="agents.approval.ticket_expired",
            message="Approval ticket expired",
            message_code="agents.approval.ticket_expired",
        )

    proposal = db.scalar(select(AgentProposal).where(AgentProposal.id == ticket.proposal_id).limit(1))
    if proposal is None:
        raise ApprovalTicketError(
            status_code=404,
            code="agents.approval.proposal_not_found",
            message="Agent proposal not found",
            message_code="agents.approval.proposal_not_found",
        )
    _assert_payload_hash(ticket)

    try:
        executed_result = _execute_ticket_action(db=db, user_id=user_id, ticket=ticket)
    except ApprovalTicketError:
        raise
    except Exception as exc:
        ticket.status = ApprovalTicketStatus.FAILED
        ticket.last_transition_kind = transition_kind.strip()[:32] or "unknown"
        ticket.last_transition_label = transition_label.strip()[:64] or "unknown"
        ticket.executed_result_json = {"error": str(exc)}
        db.commit()
        db.refresh(ticket)
        record_ticket_transition_delivery(
            db,
            ticket=ticket,
            summary_code=ticket_confirm_summary_code(ticket),
            detail_code=ticket_transition_message_code(ticket),
            cta_code=ticket_social_safe_cta_code(ticket),
        )
        raise

    now = datetime.now(timezone.utc)
    ticket.status = ApprovalTicketStatus.EXECUTED
    ticket.confirmed_at = now
    ticket.executed_at = now
    ticket.last_transition_kind = transition_kind.strip()[:32] or "unknown"
    ticket.last_transition_label = transition_label.strip()[:64] or "unknown"
    ticket.executed_result_json = jsonable_encoder(executed_result)
    proposal.status = AgentProposalStatus.ACCEPTED
    db.commit()
    db.refresh(ticket)
    record_ticket_transition_delivery(
        db,
        ticket=ticket,
        summary_code=ticket_confirm_summary_code(ticket),
        detail_code=ticket_transition_message_code(ticket),
        cta_code=ticket_social_safe_cta_code(ticket),
    )
    return ticket, False


def cancel_approval_ticket(
    db: Session,
    *,
    user_id: int,
    ticket_id: str,
    transition_kind: str = "web",
    transition_label: str = "embedded_agent",
) -> tuple[ApprovalTicket, bool]:
    ticket = db.scalar(
        select(ApprovalTicket)
        .where(ApprovalTicket.ticket_id == ticket_id, ApprovalTicket.user_id == user_id)
        .with_for_update()
    )
    if ticket is None:
        raise ApprovalTicketError(
            status_code=404,
            code="agents.approval.ticket_not_found",
            message="Approval ticket not found",
            message_code="agents.approval.ticket_not_found",
        )
    if ticket.status == ApprovalTicketStatus.CANCELED:
        return ticket, True
    if ticket.status == ApprovalTicketStatus.EXECUTED:
        raise ApprovalTicketError(
            status_code=409,
            code="agents.approval.ticket_already_executed",
            message="Approval ticket already executed",
            message_code="agents.approval.ticket_already_executed",
        )
    now = datetime.now(timezone.utc)
    ticket.status = ApprovalTicketStatus.CANCELED
    ticket.canceled_at = now
    ticket.last_transition_kind = transition_kind.strip()[:32] or "unknown"
    ticket.last_transition_label = transition_label.strip()[:64] or "unknown"
    proposal = db.scalar(select(AgentProposal).where(AgentProposal.id == ticket.proposal_id).limit(1))
    if proposal is not None:
        proposal.status = AgentProposalStatus.REJECTED
    db.commit()
    db.refresh(ticket)
    record_ticket_transition_delivery(
        db,
        ticket=ticket,
        summary_code=ticket_cancel_summary_code(ticket),
        detail_code=ticket_transition_message_code(ticket),
        cta_code=ticket_social_safe_cta_code(ticket),
    )
    return ticket, False


def _assert_proposal_executable(proposal: AgentProposal) -> None:
    kind = str((proposal.payload_json or {}).get("kind") or "")
    if kind in {"change_decision", "run_source_sync", "family_relink_commit", "label_learning_add_alias_commit", "proposal_edit_commit"}:
        return
    raise ApprovalTicketError(
        status_code=409,
        code="agents.approval.proposal_not_executable",
        message="This proposal is not directly executable and must stay in the web workflow.",
        message_code="agents.approval.proposal_not_executable",
    )


def _assert_payload_hash(ticket: ApprovalTicket) -> None:
    expected = stable_json_hash(ticket.payload_json or {})
    if expected == ticket.payload_hash:
        return
    raise ApprovalTicketError(
        status_code=409,
        code="agents.approval.ticket_payload_mismatch",
        message="Approval ticket payload no longer matches its original hash.",
        message_code="agents.approval.ticket_payload_mismatch",
    )


def _execute_ticket_action(db: Session, *, user_id: int, ticket: ApprovalTicket) -> dict:
    payload = ticket.payload_json or {}
    kind = str(payload.get("kind") or "")
    if kind == "change_decision":
        change_id = int(payload["change_id"])
        decision = str(payload["decision"])
        row = db.scalar(select(Change).where(Change.id == change_id, Change.user_id == user_id).with_for_update())
        if row is None:
            raise ApprovalTicketError(
                status_code=404,
                code="agents.approval.change_not_found",
                message="Review change not found",
                message_code="agents.approval.change_not_found",
            )
        snapshot = ticket.target_snapshot_json or {}
        if str(row.review_status.value) != str(snapshot.get("review_status") or ""):
            raise ApprovalTicketError(
                status_code=409,
                code="agents.approval.change_state_drifted",
                message="Change state drifted since the ticket was created.",
                message_code="agents.approval.change_state_drifted",
            )
        row, idempotent = decide_change(
            db=db,
            user_id=user_id,
            change_id=change_id,
            decision=decision,
            note=None,
        )
        return {
            "kind": "change_decision",
            "change_id": change_id,
            "decision": decision,
            "review_status": row.review_status.value,
            "reviewed_at": row.reviewed_at,
            "idempotent": idempotent,
        }

    if kind == "run_source_sync":
        source_id = int(payload["source_id"])
        source = get_input_source(db, user_id=user_id, source_id=source_id)
        if source is None:
            raise ApprovalTicketError(
                status_code=404,
                code="agents.approval.source_not_found",
                message="Source not found",
                message_code="agents.approval.source_not_found",
            )
        current_snapshot = build_source_read_payload(db, source=source)
        target_snapshot = ticket.target_snapshot_json or {}
        if str(current_snapshot.get("active_request_id") or "") != str(target_snapshot.get("active_request_id") or ""):
            raise ApprovalTicketError(
                status_code=409,
                code="agents.approval.source_state_drifted",
                message="Source active runtime changed since the ticket was created.",
                message_code="agents.approval.source_state_drifted",
            )
        if has_pending_monitoring_window_update(source):
            raise ApprovalTicketError(
                status_code=409,
                code="agents.approval.source_monitoring_window_update_pending",
                message="Source monitoring window update is pending.",
                message_code="sources.sync.monitoring_window_update_pending",
            )
        term_window = parse_source_monitoring_window(source, required=False)
        now = datetime.now(timezone.utc)
        if term_window is not None and not term_window.has_started(now=now, timezone_name=source_timezone_name(source)):
            raise ApprovalTicketError(
                status_code=409,
                code="agents.approval.source_monitoring_not_started",
                message="Source monitoring has not started yet.",
                message_code="sources.sync.monitoring_not_started",
            )
        if not source.is_active:
            raise ApprovalTicketError(
                status_code=409,
                code="agents.approval.source_inactive",
                message="Source is inactive and cannot be synced.",
                message_code="sources.sync.source_inactive",
            )
        row = enqueue_sync_request_idempotent(
            db=db,
            source=source,
            trigger_type=IngestTriggerType.MANUAL,
            idempotency_key=f"approval-ticket:{ticket.ticket_id}",
            metadata={"kind": "agent_approval_ticket", "ticket_id": ticket.ticket_id},
            trace_id=ticket.ticket_id,
        )
        return {
            "kind": "run_source_sync",
            "source_id": source_id,
            "request_id": row.request_id,
            "status": row.status.value,
            "idempotency_key": row.idempotency_key,
        }

    if kind == "family_relink_commit":
        raw_type_id = int(payload["raw_type_id"])
        family_id = int(payload["family_id"])
        raw_type = db.scalar(
            select(CourseWorkItemRawType)
            .join(CourseWorkItemLabelFamily, CourseWorkItemRawType.family_id == CourseWorkItemLabelFamily.id)
            .where(
                CourseWorkItemRawType.id == raw_type_id,
                CourseWorkItemLabelFamily.user_id == user_id,
            )
            .with_for_update()
            .limit(1)
        )
        if raw_type is None:
            raise ApprovalTicketError(
                status_code=404,
                code="agents.approval.raw_type_not_found",
                message="Observed label not found",
                message_code="agents.approval.raw_type_not_found",
            )
        target_family = db.scalar(
            select(CourseWorkItemLabelFamily)
            .where(
                CourseWorkItemLabelFamily.id == family_id,
                CourseWorkItemLabelFamily.user_id == user_id,
            )
            .with_for_update()
            .limit(1)
        )
        if target_family is None:
            raise ApprovalTicketError(
                status_code=404,
                code="agents.approval.family_not_found",
                message="Family not found",
                message_code="agents.approval.family_not_found",
            )
        snapshot = ticket.target_snapshot_json or {}
        if int(raw_type.family_id or 0) != int(snapshot.get("current_family_id") or 0):
            raise ApprovalTicketError(
                status_code=409,
                code="agents.approval.family_relink_state_drifted",
                message="Observed label family changed since the ticket was created.",
                message_code="agents.approval.family_relink_state_drifted",
            )
        if int(target_family.id) != int(snapshot.get("target_family_id") or 0):
            raise ApprovalTicketError(
                status_code=409,
                code="agents.approval.family_relink_target_drifted",
                message="Target family changed since the ticket was created.",
                message_code="agents.approval.family_relink_target_drifted",
            )
        previous_family_id = raw_type.family_id
        try:
            moved_raw_type, _previous_family_id = relink_raw_type_and_rebuild(
                db,
                user=target_family.user,
                raw_type=raw_type,
                family=target_family,
            )
        except FamilyApplicationValidationError as exc:
            raise ApprovalTicketError(
                status_code=409,
                code="agents.approval.family_relink_invalid",
                message=str(exc),
                message_code="agents.approval.family_relink_invalid",
            ) from exc
        return {
            "kind": "family_relink_commit",
            "raw_type_id": moved_raw_type.id,
            "raw_type": moved_raw_type.raw_type,
            "previous_family_id": previous_family_id,
            "family_id": moved_raw_type.family_id,
            "target_family_name": target_family.canonical_label,
        }

    if kind == "label_learning_add_alias_commit":
        change_id = int(payload["change_id"])
        family_id = int(payload["family_id"])
        change = db.scalar(
            select(Change)
            .where(Change.id == change_id, Change.user_id == user_id)
            .with_for_update()
            .limit(1)
        )
        if change is None:
            raise ApprovalTicketError(
                status_code=404,
                code="agents.approval.change_not_found",
                message="Review change not found",
                message_code="agents.approval.change_not_found",
            )
        if change.review_status != ReviewStatus.PENDING:
            raise ApprovalTicketError(
                status_code=409,
                code="agents.approval.change_state_drifted",
                message="Change state drifted since the ticket was created.",
                message_code="agents.approval.change_state_drifted",
            )
        family = db.scalar(
            select(CourseWorkItemLabelFamily)
            .where(CourseWorkItemLabelFamily.id == family_id, CourseWorkItemLabelFamily.user_id == user_id)
            .with_for_update()
            .limit(1)
        )
        if family is None:
            raise ApprovalTicketError(
                status_code=404,
                code="agents.approval.family_not_found",
                message="Family not found",
                message_code="agents.approval.family_not_found",
            )
        snapshot = ticket.target_snapshot_json or {}
        try:
            preview = preview_label_learning(db, user_id=user_id, change_id=change_id)
        except LabelLearningNotFoundError as exc:
            raise ApprovalTicketError(
                status_code=404,
                code="agents.approval.label_learning_not_found",
                message=str(exc),
                message_code="agents.approval.label_learning_not_found",
            ) from exc
        except LabelLearningValidationError as exc:
            raise ApprovalTicketError(
                status_code=409,
                code="agents.approval.label_learning_invalid",
                message=str(exc),
                message_code="agents.approval.label_learning_invalid",
            ) from exc
        if str(preview.get("raw_label") or "") != str(snapshot.get("raw_label") or ""):
            raise ApprovalTicketError(
                status_code=409,
                code="agents.approval.label_learning_state_drifted",
                message="Observed label changed since the ticket was created.",
                message_code="agents.approval.label_learning_state_drifted",
            )
        if int(family.id) != int(snapshot.get("target_family_id") or 0):
            raise ApprovalTicketError(
                status_code=409,
                code="agents.approval.label_learning_target_drifted",
                message="Target family changed since the ticket was created.",
                message_code="agents.approval.label_learning_target_drifted",
            )
        try:
            result = apply_label_learning(
                db,
                user_id=user_id,
                change_id=change_id,
                mode="add_alias",
                family_id=family_id,
                canonical_label=None,
            )
        except (LabelLearningNotFoundError, LabelLearningValidationError) as exc:
            raise ApprovalTicketError(
                status_code=409,
                code="agents.approval.label_learning_invalid",
                message=str(exc),
                message_code="agents.approval.label_learning_invalid",
            ) from exc
        return {
            "kind": "label_learning_add_alias_commit",
            "change_id": change_id,
            "family_id": result.get("family_id"),
            "canonical_label": result.get("canonical_label"),
            "approved_change_id": result.get("approved_change_id"),
        }

    if kind == "proposal_edit_commit":
        change_id = int(payload["change_id"])
        patch = payload.get("patch")
        if not isinstance(patch, dict) or not patch:
            raise ApprovalTicketError(
                status_code=409,
                code="agents.approval.proposal_edit_invalid_state",
                message="Proposal edit ticket is missing its patch payload.",
                message_code="agents.approval.proposal_edit_invalid_state",
            )
        change = db.scalar(
            select(Change)
            .where(Change.id == change_id, Change.user_id == user_id)
            .with_for_update()
            .limit(1)
        )
        if change is None:
            raise ApprovalTicketError(
                status_code=404,
                code="agents.approval.change_not_found",
                message="Review change not found",
                message_code="agents.approval.change_not_found",
            )
        snapshot = ticket.target_snapshot_json or {}
        if change.review_status != ReviewStatus.PENDING or change.change_type not in {ChangeType.CREATED, ChangeType.DUE_CHANGED}:
            raise ApprovalTicketError(
                status_code=409,
                code="agents.approval.proposal_edit_invalid_state",
                message="Change is no longer in a valid pending proposal-edit state.",
                message_code="agents.approval.proposal_edit_invalid_state",
            )
        if str(change.review_status.value) != str(snapshot.get("review_status") or ""):
            raise ApprovalTicketError(
                status_code=409,
                code="agents.approval.proposal_edit_invalid_state",
                message="Change review state no longer matches the ticket snapshot.",
                message_code="agents.approval.proposal_edit_invalid_state",
            )
        if str(change.change_type.value) != str(snapshot.get("change_type") or ""):
            raise ApprovalTicketError(
                status_code=409,
                code="agents.approval.proposal_edit_invalid_state",
                message="Change type no longer matches the ticket snapshot.",
                message_code="agents.approval.proposal_edit_invalid_state",
            )
        current_after_payload = change.after_semantic_json if isinstance(change.after_semantic_json, dict) else None
        if current_after_payload is None:
            raise ApprovalTicketError(
                status_code=409,
                code="agents.approval.proposal_edit_invalid_state",
                message="Pending proposal no longer has an editable proposal payload.",
                message_code="agents.approval.proposal_edit_invalid_state",
            )
        if stable_json_hash(current_after_payload) != str(snapshot.get("current_after_payload_hash") or ""):
            raise ApprovalTicketError(
                status_code=409,
                code="agents.approval.proposal_edit_state_drifted",
                message="Proposal payload drifted since the ticket was created.",
                message_code="agents.approval.proposal_edit_state_drifted",
            )
        try:
            result = apply_change_edit(
                db=db,
                user_id=user_id,
                mode="proposal",
                change_id=change_id,
                entity_uid=None,
                patch=patch,
                reason=None,
            )
        except ChangeEditNotFoundError as exc:
            raise ApprovalTicketError(
                status_code=404,
                code="agents.approval.change_not_found",
                message=str(exc),
                message_code="agents.approval.change_not_found",
            ) from exc
        except ChangeEditInvalidStateError as exc:
            raise ApprovalTicketError(
                status_code=409,
                code="agents.approval.proposal_edit_invalid_state",
                message=str(exc),
                message_code="agents.approval.proposal_edit_invalid_state",
            ) from exc
        except ChangeEditValidationError as exc:
            raise ApprovalTicketError(
                status_code=409,
                code="agents.approval.proposal_edit_invalid_state",
                message=str(exc),
                message_code="agents.approval.proposal_edit_invalid_state",
            ) from exc
        return {
            "kind": "proposal_edit_commit",
            "change_id": change_id,
            "edited_change_id": result.get("edited_change_id"),
            "idempotent": result.get("idempotent"),
            "event": result.get("event"),
        }

    raise ApprovalTicketError(
        status_code=409,
        code="agents.approval.unsupported_action",
        message="Unsupported approval ticket action.",
        message_code="agents.approval.unsupported_action",
    )
def _is_expired(ticket: ApprovalTicket) -> bool:
    return ticket.expires_at is not None and ticket.expires_at <= datetime.now(timezone.utc)


__all__ = [
    "ApprovalTicketError",
    "cancel_approval_ticket",
    "confirm_approval_ticket",
    "create_approval_ticket",
    "get_approval_ticket",
]
