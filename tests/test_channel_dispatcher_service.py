from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models.agents import ApprovalTicket, ApprovalTicketStatus, AgentProposal, AgentProposalStatus, AgentProposalType, ChannelDelivery, ChannelDeliveryStatus
from app.db.models.shared import User
from app.modules.channels.dispatcher_service import (
    acknowledge_delivery,
    claim_pending_deliveries,
    mark_delivery_failed,
    mark_delivery_sent,
)
from app.modules.channels.service import record_channel_delivery


def _create_user(db_session, *, email: str) -> User:
    user = User(
        email=email,
        password_hash="hash",
        timezone_name="America/Los_Angeles",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _create_ticket_fixture(db_session, *, user_id: int, ticket_id: str) -> tuple[AgentProposal, ApprovalTicket]:
    proposal = AgentProposal(
        user_id=user_id,
        proposal_type=AgentProposalType.CHANGE_DECISION,
        status=AgentProposalStatus.OPEN,
        target_kind="change",
        target_id="101",
        summary="Proposal",
        summary_code="test.proposal.summary",
        reason="reason",
        reason_code="test.proposal.reason",
        risk_level="low",
        confidence=0.9,
        suggested_action="approve",
        origin_kind="web",
        origin_label="embedded_agent",
        payload_json={"kind": "change_decision", "change_id": 101, "decision": "approve"},
        context_json={},
        target_snapshot_json={"review_status": "pending"},
    )
    db_session.add(proposal)
    db_session.flush()
    ticket = ApprovalTicket(
        ticket_id=ticket_id,
        proposal_id=proposal.id,
        user_id=user_id,
        channel="web",
        action_type="change_decision",
        target_kind="change",
        target_id="101",
        payload_json={"kind": "change_decision", "change_id": 101, "decision": "approve"},
        payload_hash="hash",
        target_snapshot_json={"review_status": "pending"},
        risk_level="low",
        origin_kind="web",
        origin_label="embedded_agent",
        status=ApprovalTicketStatus.OPEN,
        last_transition_kind="web",
        last_transition_label="embedded_agent",
        executed_result_json={},
    )
    db_session.add(ticket)
    db_session.commit()
    db_session.refresh(proposal)
    db_session.refresh(ticket)
    return proposal, ticket


def test_claim_pending_deliveries_assigns_lease_and_attempt_count(db_session) -> None:
    user = _create_user(db_session, email="channel-dispatch-claim@example.com")
    _proposal, ticket = _create_ticket_fixture(db_session, user_id=user.id, ticket_id="ticket-1")
    delivery = record_channel_delivery(
        db_session,
        user_id=user.id,
        channel_account_id=None,
        proposal_id=ticket.proposal_id,
        ticket_id=ticket.ticket_id,
        delivery_kind="approval_ticket_open",
        summary_code="agents.ticket.confirm.change_decision.summary",
        detail_code="agents.ticket.transition.change_decision.waiting_confirm",
        cta_code="agents.ticket.cta.confirm",
        payload_json={"preview": True},
        origin_kind="system",
        origin_label="approval_ticket_transition",
    )

    claimed = claim_pending_deliveries(db_session, worker_label="dispatcher-a", limit=10)

    assert [row.delivery_id for row in claimed] == [delivery.delivery_id]
    assert claimed[0].attempt_count == 1
    assert claimed[0].lease_owner == "dispatcher-a"
    assert isinstance(claimed[0].lease_token, str) and claimed[0].lease_token


def test_mark_delivery_sent_issues_callback_token_and_acknowledges(db_session) -> None:
    user = _create_user(db_session, email="channel-dispatch-ack@example.com")
    _proposal, ticket = _create_ticket_fixture(db_session, user_id=user.id, ticket_id="ticket-2")
    delivery = record_channel_delivery(
        db_session,
        user_id=user.id,
        channel_account_id=None,
        proposal_id=ticket.proposal_id,
        ticket_id=ticket.ticket_id,
        delivery_kind="approval_ticket_open",
        summary_code="agents.ticket.confirm.change_decision.summary",
        detail_code="agents.ticket.transition.change_decision.waiting_confirm",
        cta_code="agents.ticket.cta.confirm",
        payload_json={"preview": True},
        origin_kind="system",
        origin_label="approval_ticket_transition",
    )
    lease = claim_pending_deliveries(db_session, worker_label="dispatcher-a", limit=10)[0]

    sent, callback_token = mark_delivery_sent(
        db_session,
        delivery_id=lease.delivery_id,
        lease_token=str(lease.lease_token),
        external_message_id="telegram-msg-123",
    )
    assert sent.status == ChannelDeliveryStatus.SENT
    assert sent.external_message_id == "telegram-msg-123"
    assert sent.callback_token_hash is not None
    assert callback_token.startswith(f"cddel_{delivery.delivery_id}_")

    acked, idempotent = acknowledge_delivery(
        db_session,
        delivery_id=delivery.delivery_id,
        callback_token=callback_token,
        ack_payload={"button": "confirm"},
    )
    assert idempotent is False
    assert acked.status == ChannelDeliveryStatus.ACKNOWLEDGED
    assert acked.ack_payload_json == {"button": "confirm"}

    acked_again, second_idempotent = acknowledge_delivery(
        db_session,
        delivery_id=delivery.delivery_id,
        callback_token=callback_token,
        ack_payload={"button": "confirm"},
    )
    assert second_idempotent is True
    assert acked_again.status == ChannelDeliveryStatus.ACKNOWLEDGED


def test_mark_delivery_failed_clears_lease_and_sets_failed_status(db_session) -> None:
    user = _create_user(db_session, email="channel-dispatch-failed@example.com")
    _proposal, ticket = _create_ticket_fixture(db_session, user_id=user.id, ticket_id="ticket-3")
    delivery = record_channel_delivery(
        db_session,
        user_id=user.id,
        channel_account_id=None,
        proposal_id=ticket.proposal_id,
        ticket_id=ticket.ticket_id,
        delivery_kind="approval_ticket_open",
        summary_code="agents.ticket.confirm.change_decision.summary",
        detail_code="agents.ticket.transition.change_decision.waiting_confirm",
        cta_code="agents.ticket.cta.confirm",
        payload_json={"preview": True},
        origin_kind="system",
        origin_label="approval_ticket_transition",
    )
    lease = claim_pending_deliveries(db_session, worker_label="dispatcher-b", limit=10)[0]

    failed = mark_delivery_failed(
        db_session,
        delivery_id=lease.delivery_id,
        lease_token=str(lease.lease_token),
        error_text="transport timeout",
    )

    assert failed.status == ChannelDeliveryStatus.FAILED
    assert failed.error_text == "transport timeout"
    assert failed.lease_token is None
    assert failed.lease_owner is None

    refreshed = db_session.scalar(select(ChannelDelivery).where(ChannelDelivery.delivery_id == delivery.delivery_id))
    assert refreshed is not None
    assert refreshed.status == ChannelDeliveryStatus.FAILED
