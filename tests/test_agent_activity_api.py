from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.models.agents import ApprovalTicket, ApprovalTicketStatus, AgentProposal, AgentProposalStatus, AgentProposalType
from app.db.models.shared import User


def _create_user(db_session, *, email: str) -> User:
    user = User(
        email=email,
        notify_email=email,
        password_hash="hash",
        timezone_name="America/Los_Angeles",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _create_proposal(
    db_session,
    *,
    user_id: int,
    proposal_id: int,
    status: AgentProposalStatus,
    updated_at: datetime,
    summary: str,
) -> AgentProposal:
    row = AgentProposal(
        id=proposal_id,
        user_id=user_id,
        proposal_type=AgentProposalType.CHANGE_DECISION,
        status=status,
        target_kind="change",
        target_id=str(proposal_id),
        summary=summary,
        summary_code=f"test.summary.{proposal_id}",
        reason=f"reason-{proposal_id}",
        reason_code=f"test.reason.{proposal_id}",
        risk_level="medium",
        confidence=0.8,
        suggested_action="approve",
        payload_json={"kind": "change_decision", "change_id": proposal_id, "decision": "approve"},
        context_json={},
        target_snapshot_json={"review_status": "pending"},
        expires_at=updated_at + timedelta(hours=2),
        created_at=updated_at - timedelta(minutes=2),
        updated_at=updated_at,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def _create_ticket(
    db_session,
    *,
    ticket_id: str,
    proposal_id: int,
    user_id: int,
    status: ApprovalTicketStatus,
    updated_at: datetime,
) -> ApprovalTicket:
    row = ApprovalTicket(
        ticket_id=ticket_id,
        proposal_id=proposal_id,
        user_id=user_id,
        channel="web",
        action_type="change_decision",
        target_kind="change",
        target_id=str(proposal_id),
        payload_json={"kind": "change_decision", "change_id": proposal_id, "decision": "approve"},
        payload_hash=f"hash-{ticket_id}",
        target_snapshot_json={"review_status": "pending"},
        risk_level="medium",
        status=status,
        executed_result_json={"kind": "change_decision"} if status == ApprovalTicketStatus.EXECUTED else {},
        expires_at=updated_at + timedelta(hours=2),
        confirmed_at=updated_at if status == ApprovalTicketStatus.EXECUTED else None,
        canceled_at=updated_at if status == ApprovalTicketStatus.CANCELED else None,
        executed_at=updated_at if status == ApprovalTicketStatus.EXECUTED else None,
        created_at=updated_at - timedelta(minutes=3),
        updated_at=updated_at,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def test_list_agent_proposals_returns_recent_rows_and_status_filter(client, db_session, auth_headers) -> None:
    user = _create_user(db_session, email="agent-activity-proposals@example.com")
    base = datetime.now(timezone.utc)
    _create_proposal(
        db_session,
        user_id=user.id,
        proposal_id=101,
        status=AgentProposalStatus.OPEN,
        updated_at=base - timedelta(minutes=1),
        summary="Open proposal",
    )
    _create_proposal(
        db_session,
        user_id=user.id,
        proposal_id=102,
        status=AgentProposalStatus.ACCEPTED,
        updated_at=base,
        summary="Accepted proposal",
    )

    headers = auth_headers(client, user=user)
    response = client.get("/agent/proposals", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert [row["proposal_id"] for row in payload] == [102, 101]

    filtered = client.get("/agent/proposals?status_filter=open", headers=headers)
    assert filtered.status_code == 200
    filtered_payload = filtered.json()
    assert [row["proposal_id"] for row in filtered_payload] == [101]


def test_list_approval_tickets_returns_recent_rows_and_status_filter(client, db_session, auth_headers) -> None:
    user = _create_user(db_session, email="agent-activity-tickets@example.com")
    base = datetime.now(timezone.utc)
    proposal_open = _create_proposal(
        db_session,
        user_id=user.id,
        proposal_id=201,
        status=AgentProposalStatus.OPEN,
        updated_at=base - timedelta(minutes=2),
        summary="Proposal open",
    )
    proposal_executed = _create_proposal(
        db_session,
        user_id=user.id,
        proposal_id=202,
        status=AgentProposalStatus.ACCEPTED,
        updated_at=base - timedelta(minutes=1),
        summary="Proposal executed",
    )
    _create_ticket(
        db_session,
        ticket_id="ticket-open",
        proposal_id=proposal_open.id,
        user_id=user.id,
        status=ApprovalTicketStatus.OPEN,
        updated_at=base - timedelta(seconds=30),
    )
    _create_ticket(
        db_session,
        ticket_id="ticket-executed",
        proposal_id=proposal_executed.id,
        user_id=user.id,
        status=ApprovalTicketStatus.EXECUTED,
        updated_at=base,
    )

    headers = auth_headers(client, user=user)
    response = client.get("/agent/approval-tickets", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert [row["ticket_id"] for row in payload] == ["ticket-executed", "ticket-open"]

    filtered = client.get("/agent/approval-tickets?status_filter=open", headers=headers)
    assert filtered.status_code == 200
    filtered_payload = filtered.json()
    assert [row["ticket_id"] for row in filtered_payload] == ["ticket-open"]


def test_recent_agent_activity_merges_proposals_and_tickets_in_time_order(client, db_session, auth_headers) -> None:
    user = _create_user(db_session, email="agent-activity-recent@example.com")
    base = datetime.now(timezone.utc)
    proposal = _create_proposal(
        db_session,
        user_id=user.id,
        proposal_id=301,
        status=AgentProposalStatus.OPEN,
        updated_at=base - timedelta(minutes=3),
        summary="Proposal row",
    )
    _create_ticket(
        db_session,
        ticket_id="ticket-recent",
        proposal_id=proposal.id,
        user_id=user.id,
        status=ApprovalTicketStatus.EXECUTED,
        updated_at=base - timedelta(minutes=1),
    )
    _create_proposal(
        db_session,
        user_id=user.id,
        proposal_id=302,
        status=AgentProposalStatus.ACCEPTED,
        updated_at=base,
        summary="Most recent proposal",
    )

    response = client.get("/agent/activity/recent", headers=auth_headers(client, user=user))
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["item_kind"] == "proposal"
    assert payload["items"][0]["proposal_id"] == 302
    assert payload["items"][1]["item_kind"] == "ticket"
    assert payload["items"][1]["ticket_id"] == "ticket-recent"
    assert payload["items"][2]["item_kind"] == "proposal"
    assert payload["items"][2]["proposal_id"] == 301


def test_agent_activity_status_filters_validate(client, db_session, auth_headers) -> None:
    user = _create_user(db_session, email="agent-activity-invalid@example.com")
    headers = auth_headers(client, user=user)

    proposals = client.get("/agent/proposals?status_filter=weird", headers=headers)
    assert proposals.status_code == 422
    assert proposals.json()["detail"]["code"] == "agents.proposals.invalid_status_filter"

    tickets = client.get("/agent/approval-tickets?status_filter=weird", headers=headers)
    assert tickets.status_code == 422
    assert tickets.json()["detail"]["code"] == "agents.approval.invalid_status_filter"
