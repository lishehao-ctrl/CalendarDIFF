from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models.agents import ApprovalTicket, ApprovalTicketStatus, AgentProposal, AgentProposalStatus
from app.db.models.input import IngestTriggerType, InputSource, SourceKind, SyncRequest, SyncRequestStage, SyncRequestStatus
from app.db.models.review import Change, ChangeIntakePhase, ChangeOrigin, ChangeReviewBucket, ChangeSourceRef, ChangeType, ReviewStatus
from app.db.models.shared import CourseWorkItemLabelFamily, User
from app.modules.common.course_identity import normalize_label_token, normalized_course_identity_key, parse_course_display
from app.modules.sources.schemas import InputSourceCreateRequest
from app.modules.sources.sources_service import create_input_source


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


def _create_source(db_session, *, user: User, provider: str) -> InputSource:
    return create_input_source(
        db_session,
        user=user,
        payload=InputSourceCreateRequest(
            source_kind="email" if provider == "gmail" else "calendar",
            provider=provider,
            config={"label_id": "INBOX", "monitor_since": "2026-01-05"}
            if provider == "gmail"
            else {"monitor_since": "2026-01-05"},
            secrets={} if provider == "gmail" else {"url": "https://example.com/calendar.ics"},
        ),
    )


def _create_family(
    db_session,
    *,
    user_id: int,
    course_display: str,
    canonical_label: str,
) -> CourseWorkItemLabelFamily:
    parsed = parse_course_display(course_display)
    family = CourseWorkItemLabelFamily(
        user_id=user_id,
        course_dept=parsed["course_dept"],
        course_number=parsed["course_number"],
        course_suffix=parsed["course_suffix"],
        course_quarter=parsed["course_quarter"],
        course_year2=parsed["course_year2"],
        normalized_course_identity=normalized_course_identity_key(
            course_dept=parsed["course_dept"],
            course_number=parsed["course_number"],
            course_suffix=parsed["course_suffix"],
            course_quarter=parsed["course_quarter"],
            course_year2=parsed["course_year2"],
        ),
        canonical_label=canonical_label,
        normalized_canonical_label=normalize_label_token(canonical_label),
    )
    db_session.add(family)
    db_session.commit()
    db_session.refresh(family)
    return family


def _create_pending_change(db_session, *, user: User, source: InputSource, family: CourseWorkItemLabelFamily) -> Change:
    change = Change(
        user_id=user.id,
        entity_uid="approval-ticket-change-1",
        change_origin=ChangeOrigin.INGEST_PROPOSAL,
        change_type=ChangeType.DUE_CHANGED,
        intake_phase=ChangeIntakePhase.REPLAY,
        review_bucket=ChangeReviewBucket.CHANGES,
        detected_at=datetime.now(timezone.utc),
        before_semantic_json={
            "uid": "approval-ticket-change-1",
            "course_dept": "CSE",
            "course_number": 160,
            "course_quarter": "WI",
            "course_year2": 26,
            "family_id": family.id,
            "family_name": "Quiz",
            "event_name": "Quiz 1",
            "ordinal": 1,
            "due_date": "2026-03-20",
            "due_time": "09:00:00",
            "time_precision": "datetime",
        },
        after_semantic_json={
            "uid": "approval-ticket-change-1",
            "course_dept": "CSE",
            "course_number": 160,
            "course_quarter": "WI",
            "course_year2": 26,
            "family_id": family.id,
            "family_name": "Quiz",
            "event_name": "Quiz 1",
            "ordinal": 1,
            "due_date": "2026-03-21",
            "due_time": "09:00:00",
            "time_precision": "datetime",
        },
        before_evidence_json={"provider": "ics"},
        after_evidence_json={"provider": "ics"},
        review_status=ReviewStatus.PENDING,
    )
    db_session.add(change)
    db_session.flush()
    db_session.add(
        ChangeSourceRef(
            change_id=change.id,
            position=0,
            source_id=source.id,
            source_kind=source.source_kind,
            provider=source.provider,
            external_event_id="evt-approval-ticket-change",
            confidence=0.95,
        )
    )
    db_session.commit()
    db_session.refresh(change)
    return change


def test_change_decision_approval_ticket_executes_and_is_idempotent(client, db_session, auth_headers) -> None:
    user = _create_user(db_session, email="approval-ticket-change@example.com")
    source = _create_source(db_session, user=user, provider="ics")
    family = _create_family(db_session, user_id=user.id, course_display="CSE 160 WI26", canonical_label="Quiz")
    change = _create_pending_change(db_session, user=user, source=source, family=family)
    headers = auth_headers(client, user=user)

    proposal_response = client.post("/agent/proposals/change-decision", headers=headers, json={"change_id": change.id})
    assert proposal_response.status_code == 201
    proposal_id = proposal_response.json()["proposal_id"]

    ticket_response = client.post("/agent/approval-tickets", headers=headers, json={"proposal_id": proposal_id, "channel": "web"})
    assert ticket_response.status_code == 201
    ticket_payload = ticket_response.json()
    assert ticket_payload["action_type"] == "change_decision"
    assert ticket_payload["status"] == "open"
    assert ticket_payload["lifecycle_code"] == "agents.ticket.lifecycle.open"
    assert ticket_payload["next_step_code"] == "agents.ticket.next_step.confirm_or_cancel"
    assert ticket_payload["can_confirm"] is True
    assert ticket_payload["can_cancel"] is True

    confirm_response = client.post(
        f"/agent/approval-tickets/{ticket_payload['ticket_id']}/confirm",
        headers=headers,
        json={},
    )
    assert confirm_response.status_code == 200
    confirmed = confirm_response.json()
    assert confirmed["status"] == "executed"
    assert confirmed["lifecycle_code"] == "agents.ticket.lifecycle.executed"
    assert confirmed["next_step_code"] == "agents.ticket.next_step.completed"
    assert confirmed["can_confirm"] is False
    assert confirmed["can_cancel"] is False
    assert confirmed["executed_result"]["kind"] == "change_decision"
    assert confirmed["executed_result"]["review_status"] == "approved"

    db_session.expire_all()
    refreshed_change = db_session.scalar(select(Change).where(Change.id == change.id))
    proposal = db_session.scalar(select(AgentProposal).where(AgentProposal.id == proposal_id))
    ticket = db_session.scalar(select(ApprovalTicket).where(ApprovalTicket.ticket_id == ticket_payload["ticket_id"]))
    assert refreshed_change is not None
    assert refreshed_change.review_status == ReviewStatus.APPROVED
    assert proposal is not None and proposal.status == AgentProposalStatus.ACCEPTED
    assert ticket is not None and ticket.status == ApprovalTicketStatus.EXECUTED

    confirm_again = client.post(
        f"/agent/approval-tickets/{ticket_payload['ticket_id']}/confirm",
        headers=headers,
        json={},
    )
    assert confirm_again.status_code == 200
    assert confirm_again.json()["status"] == "executed"


def test_change_decision_approval_ticket_detects_state_drift(client, db_session, auth_headers) -> None:
    user = _create_user(db_session, email="approval-ticket-drift@example.com")
    source = _create_source(db_session, user=user, provider="ics")
    family = _create_family(db_session, user_id=user.id, course_display="CSE 161 WI26", canonical_label="Quiz")
    change = _create_pending_change(db_session, user=user, source=source, family=family)
    headers = auth_headers(client, user=user)

    proposal_response = client.post("/agent/proposals/change-decision", headers=headers, json={"change_id": change.id})
    proposal_id = proposal_response.json()["proposal_id"]
    ticket_response = client.post("/agent/approval-tickets", headers=headers, json={"proposal_id": proposal_id})
    ticket_id = ticket_response.json()["ticket_id"]

    db_change = db_session.scalar(select(Change).where(Change.id == change.id))
    assert db_change is not None
    db_change.review_status = ReviewStatus.REJECTED
    db_change.reviewed_at = datetime.now(timezone.utc)
    db_session.commit()

    confirm_response = client.post(f"/agent/approval-tickets/{ticket_id}/confirm", headers=headers, json={})
    assert confirm_response.status_code == 409
    assert confirm_response.json()["detail"]["code"] == "agents.approval.change_state_drifted"


def test_source_retry_sync_approval_ticket_executes_new_sync_request(client, db_session, auth_headers) -> None:
    user = _create_user(db_session, email="approval-ticket-source@example.com")
    source = _create_source(db_session, user=user, provider="ics")
    failed_sync = SyncRequest(
        request_id="approval-ticket-source-failed",
        source_id=source.id,
        trigger_type=IngestTriggerType.MANUAL,
        status=SyncRequestStatus.FAILED,
        stage=SyncRequestStage.FAILED,
        stage_updated_at=datetime.now(timezone.utc),
        idempotency_key="idemp:approval-ticket-source-failed",
        metadata_json={"kind": "test"},
        error_code="runtime_failed",
        error_message="runtime failed",
    )
    db_session.add(failed_sync)
    db_session.commit()

    headers = auth_headers(client, user=user)
    proposal_response = client.post("/agent/proposals/source-recovery", headers=headers, json={"source_id": source.id})
    assert proposal_response.status_code == 201
    proposal = proposal_response.json()
    assert proposal["suggested_action"] == "retry_sync"

    ticket_response = client.post("/agent/approval-tickets", headers=headers, json={"proposal_id": proposal["proposal_id"]})
    assert ticket_response.status_code == 201
    ticket_id = ticket_response.json()["ticket_id"]

    confirm_response = client.post(f"/agent/approval-tickets/{ticket_id}/confirm", headers=headers, json={})
    assert confirm_response.status_code == 200
    confirmed = confirm_response.json()
    assert confirmed["status"] == "executed"
    assert confirmed["lifecycle_code"] == "agents.ticket.lifecycle.executed"
    assert confirmed["executed_result"]["kind"] == "run_source_sync"
    assert confirmed["executed_result"]["source_id"] == source.id
    assert confirmed["executed_result"]["status"] == "PENDING"

    new_request_id = confirmed["executed_result"]["request_id"]
    db_session.expire_all()
    new_sync = db_session.scalar(select(SyncRequest).where(SyncRequest.request_id == new_request_id))
    proposal_row = db_session.scalar(select(AgentProposal).where(AgentProposal.id == proposal["proposal_id"]))
    assert new_sync is not None
    assert new_sync.source_id == source.id
    assert proposal_row is not None and proposal_row.status == AgentProposalStatus.ACCEPTED


def test_non_executable_source_recovery_proposal_cannot_create_ticket(client, db_session, auth_headers) -> None:
    user = _create_user(db_session, email="approval-ticket-nonexec@example.com")
    source = _create_source(db_session, user=user, provider="gmail")
    headers = auth_headers(client, user=user)

    proposal_response = client.post("/agent/proposals/source-recovery", headers=headers, json={"source_id": source.id})
    assert proposal_response.status_code == 201
    proposal = proposal_response.json()
    assert proposal["suggested_action"] == "reconnect_gmail"

    ticket_response = client.post("/agent/approval-tickets", headers=headers, json={"proposal_id": proposal["proposal_id"]})
    assert ticket_response.status_code == 409
    assert ticket_response.json()["detail"]["code"] == "agents.approval.proposal_not_executable"


def test_cancel_approval_ticket_marks_ticket_and_proposal_rejected(client, db_session, auth_headers) -> None:
    user = _create_user(db_session, email="approval-ticket-cancel@example.com")
    source = _create_source(db_session, user=user, provider="ics")
    family = _create_family(db_session, user_id=user.id, course_display="CSE 162 WI26", canonical_label="Quiz")
    change = _create_pending_change(db_session, user=user, source=source, family=family)
    headers = auth_headers(client, user=user)

    proposal_response = client.post("/agent/proposals/change-decision", headers=headers, json={"change_id": change.id})
    proposal_id = proposal_response.json()["proposal_id"]
    ticket_response = client.post("/agent/approval-tickets", headers=headers, json={"proposal_id": proposal_id})
    ticket_id = ticket_response.json()["ticket_id"]

    cancel_response = client.post(f"/agent/approval-tickets/{ticket_id}/cancel", headers=headers, json={})
    assert cancel_response.status_code == 200
    payload = cancel_response.json()
    assert payload["status"] == "canceled"

    db_session.expire_all()
    proposal = db_session.scalar(select(AgentProposal).where(AgentProposal.id == proposal_id))
    ticket = db_session.scalar(select(ApprovalTicket).where(ApprovalTicket.ticket_id == ticket_id))
    assert proposal is not None and proposal.status == AgentProposalStatus.REJECTED
    assert ticket is not None and ticket.status == ApprovalTicketStatus.CANCELED
