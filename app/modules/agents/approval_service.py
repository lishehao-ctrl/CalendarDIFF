from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.agents import ApprovalTicket, ApprovalTicketStatus, AgentProposal, AgentProposalStatus
from app.db.models.input import IngestTriggerType, SyncRequestStatus
from app.db.models.review import Change
from app.modules.changes.change_decision_service import ChangeNotFoundError, decide_change
from app.modules.channels.service import record_ticket_transition_delivery
from app.modules.common.api_errors import api_error_detail
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

    existing = db.scalar(
        select(ApprovalTicket)
        .where(
            ApprovalTicket.proposal_id == proposal.id,
            ApprovalTicket.user_id == user_id,
            ApprovalTicket.status.in_((ApprovalTicketStatus.OPEN, ApprovalTicketStatus.EXECUTED)),
        )
        .order_by(ApprovalTicket.created_at.desc())
        .limit(1)
    )
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
        payload_hash=_payload_hash(payload),
        target_snapshot_json=proposal.target_snapshot_json or {},
        risk_level=proposal.risk_level,
        origin_kind=origin_kind.strip()[:32] or "unknown",
        origin_label=origin_label.strip()[:64] or "unknown",
        status=ApprovalTicketStatus.OPEN,
        last_transition_kind=origin_kind.strip()[:32] or "unknown",
        last_transition_label=origin_label.strip()[:64] or "unknown",
        executed_result_json={},
        expires_at=proposal.expires_at,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    record_ticket_transition_delivery(
        db,
        ticket=ticket,
        summary_code=ticket_confirm_summary_code(ticket),
        detail_code=ticket_transition_message_code(ticket),
        cta_code=ticket_social_safe_cta_code(ticket),
    )
    return ticket


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
    if kind in {"change_decision", "run_source_sync"}:
        return
    raise ApprovalTicketError(
        status_code=409,
        code="agents.approval.proposal_not_executable",
        message="This proposal is not directly executable and must stay in the web workflow.",
        message_code="agents.approval.proposal_not_executable",
    )


def _assert_payload_hash(ticket: ApprovalTicket) -> None:
    expected = _payload_hash(ticket.payload_json or {})
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

    raise ApprovalTicketError(
        status_code=409,
        code="agents.approval.unsupported_action",
        message="Unsupported approval ticket action.",
        message_code="agents.approval.unsupported_action",
    )


def _payload_hash(payload: dict) -> str:
    encoded = json.dumps(jsonable_encoder(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _is_expired(ticket: ApprovalTicket) -> bool:
    return ticket.expires_at is not None and ticket.expires_at <= datetime.now(timezone.utc)


__all__ = [
    "ApprovalTicketError",
    "cancel_approval_ticket",
    "confirm_approval_ticket",
    "create_approval_ticket",
    "get_approval_ticket",
]
