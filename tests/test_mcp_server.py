from __future__ import annotations

from datetime import datetime, timezone

import anyio

from app.db.models.input import IngestTriggerType, SyncRequest, SyncRequestStage, SyncRequestStatus
from app.db.models.review import Change, ChangeIntakePhase, ChangeOrigin, ChangeReviewBucket, ChangeSourceRef, ChangeType, ReviewStatus
from app.db.models.shared import CourseWorkItemLabelFamily, User
from app.modules.common.course_identity import normalize_label_token, normalized_course_identity_key, parse_course_display
from app.modules.sources.schemas import InputSourceCreateRequest
from app.modules.sources.sources_service import create_input_source
from services.mcp_server.main import (
    create_approval_ticket_impl,
    create_change_decision_proposal_impl,
    get_family_context_impl,
    get_workspace_context_impl,
    get_change_context_impl,
    get_source_context_impl,
    get_proposal_impl,
    mcp,
)


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


def _create_source(db_session, *, user: User, provider: str):
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


def test_mcp_server_registers_expected_tools_and_resources() -> None:
    tool_names = {tool.name for tool in anyio.run(mcp.list_tools)}
    resource_uris = {str(resource.uri) for resource in anyio.run(mcp.list_resources)}

    assert "get_workspace_context" in tool_names
    assert "create_change_decision_proposal" in tool_names
    assert "create_approval_ticket" in tool_names
    assert "confirm_approval_ticket" in tool_names
    assert "calendardiff://workspace" in resource_uris
    assert "calendardiff://pending-changes" in resource_uris
    assert "calendardiff://sources" in resource_uris


def test_mcp_impl_round_trip_uses_existing_agent_layers(db_session) -> None:
    user = _create_user(db_session, email="mcp-user@example.com")
    source = _create_source(db_session, user=user, provider="ics")
    family = _create_family(db_session, user_id=user.id, course_display="CSE 170 WI26", canonical_label="Quiz")
    change = Change(
        user_id=user.id,
        entity_uid="mcp-change-1",
        change_origin=ChangeOrigin.INGEST_PROPOSAL,
        change_type=ChangeType.DUE_CHANGED,
        intake_phase=ChangeIntakePhase.REPLAY,
        review_bucket=ChangeReviewBucket.CHANGES,
        detected_at=datetime.now(timezone.utc),
        before_semantic_json={
            "uid": "mcp-change-1",
            "course_dept": "CSE",
            "course_number": 170,
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
            "uid": "mcp-change-1",
            "course_dept": "CSE",
            "course_number": 170,
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
            external_event_id="evt-mcp-change",
            confidence=0.95,
        )
    )
    db_session.add(
        SyncRequest(
            request_id="mcp-sync-1",
            source_id=source.id,
            trigger_type=IngestTriggerType.MANUAL,
            status=SyncRequestStatus.RUNNING,
            stage=SyncRequestStage.CONNECTOR_FETCH,
            substage="calendar_fetch",
            stage_updated_at=datetime.now(timezone.utc),
            progress_json={
                "phase": "connector_fetch",
                "label": "Fetching calendar inventory",
                "detail": "Fetched 3 of 10 events.",
                "current": 3,
                "total": 10,
                "percent": 30.0,
                "unit": "events",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            idempotency_key="idemp:mcp-sync-1",
            metadata_json={"kind": "test"},
        )
    )
    db_session.commit()

    workspace = get_workspace_context_impl(notify_email=user.notify_email)
    change_context = get_change_context_impl(change_id=change.id, notify_email=user.notify_email)
    source_context = get_source_context_impl(source_id=source.id, notify_email=user.notify_email)
    family_context = get_family_context_impl(family_id=family.id, notify_email=user.notify_email)
    proposal = create_change_decision_proposal_impl(change_id=change.id, notify_email=user.notify_email)
    fetched_proposal = get_proposal_impl(proposal_id=proposal["proposal_id"], notify_email=user.notify_email)
    ticket = create_approval_ticket_impl(proposal_id=proposal["proposal_id"], notify_email=user.notify_email)

    assert workspace["summary"]["changes_pending"] == 1
    assert change_context["change"]["id"] == change.id
    assert source_context["source"]["source_id"] == source.id
    assert family_context["family"]["id"] == family.id
    assert proposal["target_id"] == str(change.id)
    assert fetched_proposal["proposal_id"] == proposal["proposal_id"]
    assert ticket["proposal_id"] == proposal["proposal_id"]
