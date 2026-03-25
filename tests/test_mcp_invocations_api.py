from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import anyio
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.fastmcp import Context
from mcp.server.fastmcp.server import RequestContext

from app.db.models.agents import McpToolInvocation
from app.db.models.input import InputSource
from app.db.models.review import Change, ChangeIntakePhase, ChangeOrigin, ChangeReviewBucket, ChangeSourceRef, ChangeType, ReviewStatus
from app.db.models.shared import CourseWorkItemLabelFamily, User
from app.modules.common.course_identity import normalize_label_token, normalized_course_identity_key, parse_course_display
from app.modules.settings.mcp_tokens_service import create_mcp_access_token
from app.modules.sources.schemas import InputSourceCreateRequest
from app.modules.sources.sources_service import create_input_source
from services.mcp_server.main import (
    CalendarDIFFTokenVerifier,
    create_change_decision_proposal_impl,
    get_workspace_context_impl,
    mcp,
)


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


def _create_source(db_session, *, user: User) -> InputSource:
    return create_input_source(
        db_session,
        user=user,
        payload=InputSourceCreateRequest(
            source_kind="calendar",
            provider="ics",
            config={"monitor_since": "2026-01-05"},
            secrets={"url": "https://example.com/calendar.ics"},
        ),
    )


def _create_family(db_session, *, user_id: int) -> CourseWorkItemLabelFamily:
    parsed = parse_course_display("CSE 170 WI26")
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
        canonical_label="Quiz",
        normalized_canonical_label=normalize_label_token("Quiz"),
    )
    db_session.add(family)
    db_session.commit()
    db_session.refresh(family)
    return family


def _create_pending_change(db_session, *, user: User, source: InputSource, family: CourseWorkItemLabelFamily) -> Change:
    change = Change(
        user_id=user.id,
        entity_uid="mcp-audit-change",
        change_origin=ChangeOrigin.INGEST_PROPOSAL,
        change_type=ChangeType.DUE_CHANGED,
        intake_phase=ChangeIntakePhase.REPLAY,
        review_bucket=ChangeReviewBucket.CHANGES,
        detected_at=datetime.now(timezone.utc),
        before_semantic_json={
            "uid": "mcp-audit-change",
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
            "uid": "mcp-audit-change",
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
            external_event_id="evt-mcp-audit-change",
            confidence=0.95,
        )
    )
    db_session.commit()
    db_session.refresh(change)
    return change


@dataclass
class _FakeRequest:
    user: object


def test_settings_mcp_invocations_lists_recent_rows(client, db_session, auth_headers) -> None:
    user = _create_user(db_session, email="mcp-invocations-user@example.com")
    get_workspace_context_impl(email=user.email)

    response = client.get("/settings/mcp-invocations", headers=auth_headers(client, user=user))
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["tool_name"] == "get_workspace_context"
    assert payload[0]["status"] == "succeeded"
    assert payload[0]["auth_mode"] == "email"


def test_mcp_invocation_links_request_id_and_created_proposal(db_session) -> None:
    user = _create_user(db_session, email="mcp-invocation-request@example.com")
    source = _create_source(db_session, user=user)
    family = _create_family(db_session, user_id=user.id)
    change = _create_pending_change(db_session, user=user, source=source, family=family)
    _row, plaintext = create_mcp_access_token(db_session, user=user, label="QClaw", expires_in_days=30)
    access = anyio.run(CalendarDIFFTokenVerifier().verify_token, plaintext)
    assert access is not None

    request = _FakeRequest(user=AuthenticatedUser(access))
    request_context = RequestContext(
        request_id="req-audit-123",
        meta=None,
        session=None,
        lifespan_context=None,
        request=request,
    )
    ctx = Context(request_context=request_context, fastmcp=mcp)

    proposal = create_change_decision_proposal_impl(change_id=change.id, email=None, ctx=ctx)
    row = db_session.query(McpToolInvocation).filter(McpToolInvocation.tool_name == "create_change_decision_proposal").one()

    assert proposal["origin_request_id"] == "req-audit-123"
    assert row.transport_request_id == "req-audit-123"
    assert row.proposal_id == proposal["proposal_id"]
    assert row.auth_mode == "bearer_token"
    assert row.status.value == "succeeded"
