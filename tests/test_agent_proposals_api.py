from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models.agents import AgentProposal, AgentProposalStatus, AgentProposalType
from app.db.models.input import IngestTriggerType, InputSource, SourceKind, SyncRequest, SyncRequestStage, SyncRequestStatus
from app.db.models.review import Change, ChangeIntakePhase, ChangeOrigin, ChangeReviewBucket, ChangeSourceRef, ChangeType, ReviewStatus, SourceEventObservation
from app.db.models.shared import CourseWorkItemLabelFamily, User
from app.modules.common.course_identity import normalize_label_token, normalized_course_identity_key, parse_course_display
from app.modules.sources.schemas import InputSourceCreateRequest
from app.modules.sources.sources_service import create_input_source


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


def _create_label_learning_change(db_session, *, user: User, source: InputSource, raw_label: str, title: str) -> Change:
    entity_uid = f"tmp-{title.lower().replace(' ', '-')}"
    external_event_id = f"evt-{title.lower().replace(' ', '-')}"
    semantic_event = {
        "uid": entity_uid,
        "course_dept": "CSE",
        "course_number": 100,
        "course_quarter": "WI",
        "course_year2": 26,
        "family_name": raw_label,
        "raw_type": raw_label,
        "event_name": title,
        "ordinal": 1,
        "due_date": "2026-03-12",
        "due_time": "23:59:00",
        "time_precision": "datetime",
    }
    db_session.add(
        SourceEventObservation(
            user_id=user.id,
            source_id=source.id,
            source_kind=source.source_kind,
            provider=source.provider,
            external_event_id=external_event_id,
            entity_uid=entity_uid,
            event_payload={
                "source_facts": {
                    "external_event_id": external_event_id,
                    "source_title": title,
                    "source_dtstart_utc": "2026-03-12T23:59:00+00:00",
                    "source_dtend_utc": "2026-03-13T00:59:00+00:00",
                },
                "semantic_event": semantic_event,
                "link_signals": {},
                "kind_resolution": {
                    "status": "unresolved",
                    "reason_code": "missing_course_identity",
                },
            },
            event_hash="2" * 64,
            observed_at=datetime.now(timezone.utc),
            is_active=True,
        )
    )
    change = Change(
        user_id=user.id,
        entity_uid=entity_uid,
        change_origin=ChangeOrigin.INGEST_PROPOSAL,
        change_type=ChangeType.CREATED,
        detected_at=datetime.now(timezone.utc),
        after_semantic_json=semantic_event,
        source_refs=[
            ChangeSourceRef(
                position=0,
                source_id=source.id,
                source_kind=SourceKind.CALENDAR,
                provider="ics",
                external_event_id=external_event_id,
                confidence=0.95,
            )
        ],
        review_status=ReviewStatus.PENDING,
    )
    db_session.add(change)
    db_session.commit()
    db_session.refresh(change)
    return change


def _create_editable_change(
    db_session,
    *,
    user: User,
    source: InputSource,
    family: CourseWorkItemLabelFamily,
    change_type: ChangeType = ChangeType.DUE_CHANGED,
) -> Change:
    change = Change(
        user_id=user.id,
        entity_uid=f"agent-editable-change-{change_type.value}",
        change_origin=ChangeOrigin.INGEST_PROPOSAL,
        change_type=change_type,
        intake_phase=ChangeIntakePhase.REPLAY,
        review_bucket=ChangeReviewBucket.CHANGES,
        detected_at=datetime.now(timezone.utc),
        before_semantic_json={
            "uid": f"agent-editable-change-{change_type.value}",
            "course_dept": "CSE",
            "course_number": 180,
            "course_quarter": "WI",
            "course_year2": 26,
            "family_id": family.id,
            "family_name": family.canonical_label,
            "event_name": "Project Proposal",
            "ordinal": 1,
            "due_date": "2026-03-20",
            "due_time": "09:00:00",
            "time_precision": "datetime",
        },
        after_semantic_json={
            "uid": f"agent-editable-change-{change_type.value}",
            "course_dept": "CSE",
            "course_number": 180,
            "course_quarter": "WI",
            "course_year2": 26,
            "family_id": family.id,
            "family_name": family.canonical_label,
            "event_name": "Project Proposal",
            "ordinal": 1,
            "due_date": "2026-03-21",
            "due_time": "09:00:00",
            "time_precision": "datetime",
        }
        if change_type != ChangeType.REMOVED
        else None,
        before_evidence_json={"provider": "ics"},
        after_evidence_json={"provider": "ics"} if change_type != ChangeType.REMOVED else None,
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
            external_event_id=f"evt-agent-editable-{change_type.value}",
            confidence=0.95,
        )
    )
    db_session.commit()
    db_session.refresh(change)
    return change


def test_agent_change_decision_proposal_is_persisted_and_fetchable(client, db_session, auth_headers) -> None:
    user = _create_user(db_session, email="agent-proposal-change@example.com")
    source = _create_source(db_session, user=user, provider="ics")
    family = _create_family(db_session, user_id=user.id, course_display="CSE 160 WI26", canonical_label="Quiz")
    change = Change(
        user_id=user.id,
        entity_uid="agent-proposal-change-1",
        change_origin=ChangeOrigin.INGEST_PROPOSAL,
        change_type=ChangeType.DUE_CHANGED,
        intake_phase=ChangeIntakePhase.REPLAY,
        review_bucket=ChangeReviewBucket.CHANGES,
        detected_at=datetime.now(timezone.utc),
        before_semantic_json={
            "uid": "agent-proposal-change-1",
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
            "uid": "agent-proposal-change-1",
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
            external_event_id="evt-agent-proposal-change",
            confidence=0.95,
        )
    )
    db_session.commit()

    headers = auth_headers(client, user=user)
    create_response = client.post(
        "/agent/proposals/change-decision",
        headers=headers,
        json={"change_id": change.id},
    )
    assert create_response.status_code == 201
    payload = create_response.json()
    assert payload["proposal_type"] == "change_decision"
    assert payload["status"] == "open"
    assert payload["target_kind"] == "change"
    assert payload["target_id"] == str(change.id)
    assert payload["suggested_action"] == "approve"
    assert payload["lifecycle_code"] == "agents.proposal.lifecycle.open"
    assert payload["execution_mode"] == "approval_ticket_required"
    assert payload["execution_mode_code"] == "agents.proposal.execution_mode.approval_ticket_required"
    assert payload["next_step_code"] == "agents.proposal.next_step.create_ticket"
    assert payload["can_create_ticket"] is True
    assert payload["owner_user_id"] == user.id
    assert payload["origin_kind"] == "web"
    assert payload["origin_label"] == "embedded_agent"
    assert payload["risk_level"] == "medium"
    assert payload["suggested_payload"] == {
        "kind": "change_decision",
        "change_id": change.id,
        "decision": "approve",
    }
    assert payload["context"]["change_id"] == change.id
    assert payload["target_snapshot"]["review_status"] == "pending"

    row = db_session.scalar(select(AgentProposal).where(AgentProposal.id == payload["proposal_id"]))
    assert row is not None
    assert row.proposal_type == AgentProposalType.CHANGE_DECISION
    assert row.status == AgentProposalStatus.OPEN

    get_response = client.get(f"/agent/proposals/{payload['proposal_id']}", headers=headers)
    assert get_response.status_code == 200
    fetched = get_response.json()
    assert fetched["proposal_id"] == payload["proposal_id"]
    assert fetched["summary"] == payload["summary"]


def test_agent_change_decision_proposal_rejects_already_reviewed_change(client, db_session, auth_headers) -> None:
    user = _create_user(db_session, email="agent-proposal-reviewed@example.com")
    source = _create_source(db_session, user=user, provider="ics")
    family = _create_family(db_session, user_id=user.id, course_display="CSE 101 WI26", canonical_label="Homework")
    change = Change(
        user_id=user.id,
        entity_uid="agent-reviewed-change",
        change_origin=ChangeOrigin.INGEST_PROPOSAL,
        change_type=ChangeType.CREATED,
        intake_phase=ChangeIntakePhase.REPLAY,
        review_bucket=ChangeReviewBucket.CHANGES,
        detected_at=datetime.now(timezone.utc),
        after_semantic_json={
            "uid": "agent-reviewed-change",
            "course_dept": "CSE",
            "course_number": 101,
            "course_quarter": "WI",
            "course_year2": 26,
            "family_id": family.id,
            "family_name": "Homework",
            "event_name": "Homework 1",
            "ordinal": 1,
            "due_date": "2026-03-20",
            "due_time": "23:59:00",
            "time_precision": "datetime",
        },
        review_status=ReviewStatus.APPROVED,
        reviewed_at=datetime.now(timezone.utc),
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
            external_event_id="evt-agent-reviewed-change",
            confidence=0.95,
        )
    )
    db_session.commit()

    response = client.post(
        "/agent/proposals/change-decision",
        headers=auth_headers(client, user=user),
        json={"change_id": change.id},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "agents.proposals.change.already_reviewed"


def test_agent_source_recovery_proposal_is_persisted_and_scoped(client, db_session, auth_headers) -> None:
    user = _create_user(db_session, email="agent-proposal-source@example.com")
    source = _create_source(db_session, user=user, provider="gmail")
    sync_request = SyncRequest(
        request_id="agent-proposal-source-sync",
        source_id=source.id,
        trigger_type=IngestTriggerType.MANUAL,
        status=SyncRequestStatus.RUNNING,
        stage=SyncRequestStage.CONNECTOR_FETCH,
        substage="gmail_message_hydrate",
        stage_updated_at=datetime.now(timezone.utc),
        progress_json={
            "phase": "connector_fetch",
            "label": "Fetching Gmail message metadata",
            "detail": "Hydrated 8 of 20 changed emails.",
            "current": 8,
            "total": 20,
            "percent": 40.0,
            "unit": "emails",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        idempotency_key="idemp:agent-proposal-source-sync",
        metadata_json={"kind": "test"},
    )
    db_session.add(sync_request)
    db_session.commit()

    headers = auth_headers(client, user=user)
    create_response = client.post(
        "/agent/proposals/source-recovery",
        headers=headers,
        json={"source_id": source.id},
    )
    assert create_response.status_code == 201
    payload = create_response.json()
    assert payload["proposal_type"] == "source_recovery"
    assert payload["target_kind"] == "source"
    assert payload["target_id"] == str(source.id)
    assert payload["suggested_action"] == "reconnect_gmail"
    assert payload["lifecycle_code"] == "agents.proposal.lifecycle.open"
    assert payload["execution_mode"] == "web_only"
    assert payload["execution_mode_code"] == "agents.proposal.execution_mode.web_only"
    assert payload["next_step_code"] == "agents.proposal.next_step.open_web_flow"
    assert payload["can_create_ticket"] is False
    assert payload["owner_user_id"] == user.id
    assert payload["origin_kind"] == "web"
    assert payload["origin_label"] == "embedded_agent"
    assert payload["risk_level"] == "high"
    assert payload["suggested_payload"]["kind"] == "reconnect_source"
    assert payload["context"]["source_id"] == source.id
    assert payload["target_snapshot"]["active_request_id"] == "agent-proposal-source-sync"

    row = db_session.scalar(select(AgentProposal).where(AgentProposal.id == payload["proposal_id"]))
    assert row is not None
    assert row.proposal_type == AgentProposalType.SOURCE_RECOVERY
    assert row.status == AgentProposalStatus.OPEN

    other_user = _create_user(db_session, email="other-agent-proposal-source@example.com")
    other_headers = auth_headers(client, user=other_user)
    forbidden = client.get(f"/agent/proposals/{payload['proposal_id']}", headers=other_headers)
    assert forbidden.status_code == 404


def test_agent_label_learning_commit_proposal_is_persisted_and_fetchable(client, db_session, auth_headers) -> None:
    user = _create_user(db_session, email="agent-proposal-label-learning@example.com")
    source = _create_source(db_session, user=user, provider="ics")
    family = _create_family(db_session, user_id=user.id, course_display="CSE 100 WI26", canonical_label="Homework")
    change = _create_label_learning_change(db_session, user=user, source=source, raw_label="HW", title="HW1")

    response = client.post(
        "/agent/proposals/label-learning-commit",
        headers=auth_headers(client, user=user),
        json={"change_id": change.id, "family_id": family.id},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["proposal_type"] == "label_learning_commit"
    assert payload["target_kind"] == "label_learning"
    assert payload["suggested_action"] == "commit_label_learning"
    assert payload["execution_mode"] == "approval_ticket_required"
    assert payload["can_create_ticket"] is True
    assert payload["suggested_payload"]["kind"] == "label_learning_add_alias_commit"
    assert payload["target_snapshot"]["change_id"] == change.id
    assert payload["target_snapshot"]["target_family_id"] == family.id

    row = db_session.scalar(select(AgentProposal).where(AgentProposal.id == payload["proposal_id"]))
    assert row is not None
    assert row.proposal_type == AgentProposalType.LABEL_LEARNING_COMMIT
    assert row.status == AgentProposalStatus.OPEN


def test_agent_change_edit_commit_proposal_is_persisted_and_fetchable(client, db_session, auth_headers) -> None:
    user = _create_user(db_session, email="agent-proposal-edit@example.com")
    source = _create_source(db_session, user=user, provider="ics")
    family = _create_family(db_session, user_id=user.id, course_display="CSE 180 WI26", canonical_label="Project")
    change = _create_editable_change(db_session, user=user, source=source, family=family)

    response = client.post(
        "/agent/proposals/change-edit-commit",
        headers=auth_headers(client, user=user),
        json={
            "change_id": change.id,
            "patch": {
                "event_name": "Project Proposal (updated)",
                "due_date": "2026-03-24",
                "due_time": "10:30:00",
                "time_precision": "datetime",
            },
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["proposal_type"] == "proposal_edit_commit"
    assert payload["target_kind"] == "change"
    assert payload["target_id"] == str(change.id)
    assert payload["suggested_action"] == "commit_proposal_edit"
    assert payload["execution_mode"] == "approval_ticket_required"
    assert payload["can_create_ticket"] is True
    assert payload["suggested_payload"] == {
        "kind": "proposal_edit_commit",
        "change_id": change.id,
        "patch": {
            "event_name": "Project Proposal (updated)",
            "due_date": "2026-03-24",
            "due_time": "10:30:00",
            "time_precision": "datetime",
        },
    }
    assert payload["context"]["proposal_change_type"] == "due_changed"
    assert payload["context"]["candidate_after"]["due_date"] == "2026-03-24"
    assert payload["context"]["candidate_after"]["due_time"] == "10:30:00"
    assert payload["target_snapshot"]["change_id"] == change.id
    assert payload["target_snapshot"]["review_status"] == "pending"
    assert payload["target_snapshot"]["change_type"] == "due_changed"
    assert payload["target_snapshot"]["patch_fields"] == ["due_date", "due_time", "event_name", "time_precision"]
    assert payload["target_snapshot"]["current_after_payload_hash"]

    row = db_session.scalar(select(AgentProposal).where(AgentProposal.id == payload["proposal_id"]))
    assert row is not None
    assert row.proposal_type == AgentProposalType.PROPOSAL_EDIT_COMMIT
    assert row.status == AgentProposalStatus.OPEN


def test_agent_change_edit_commit_proposal_rejects_removed_change(client, db_session, auth_headers) -> None:
    user = _create_user(db_session, email="agent-proposal-edit-removed@example.com")
    source = _create_source(db_session, user=user, provider="ics")
    family = _create_family(db_session, user_id=user.id, course_display="CSE 181 WI26", canonical_label="Project")
    change = _create_editable_change(db_session, user=user, source=source, family=family, change_type=ChangeType.REMOVED)

    response = client.post(
        "/agent/proposals/change-edit-commit",
        headers=auth_headers(client, user=user),
        json={"change_id": change.id, "patch": {"due_date": "2026-03-25"}},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "agents.proposals.change_edit.unsupported_change_type"


def test_agent_change_edit_commit_proposal_rejects_empty_patch(client, db_session, auth_headers) -> None:
    user = _create_user(db_session, email="agent-proposal-edit-empty@example.com")
    source = _create_source(db_session, user=user, provider="ics")
    family = _create_family(db_session, user_id=user.id, course_display="CSE 182 WI26", canonical_label="Project")
    change = _create_editable_change(db_session, user=user, source=source, family=family)

    response = client.post(
        "/agent/proposals/change-edit-commit",
        headers=auth_headers(client, user=user),
        json={"change_id": change.id, "patch": {}},
    )
    assert response.status_code == 422
