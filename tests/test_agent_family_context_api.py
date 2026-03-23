from __future__ import annotations

from datetime import datetime, timezone

from app.db.models.shared import CourseRawTypeSuggestion, CourseRawTypeSuggestionStatus, CourseWorkItemLabelFamily, CourseWorkItemRawType, User
from app.modules.common.course_identity import normalize_label_token, normalized_course_identity_key, parse_course_display


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


def test_agent_family_context_exposes_family_raw_types_and_pending_suggestions(client, db_session, auth_headers) -> None:
    user = _create_user(db_session, email="agent-family@example.com")
    family = _create_family(db_session, user_id=user.id, course_display="CSE 160 WI26", canonical_label="Homework")
    raw_type = CourseWorkItemRawType(
        family_id=family.id,
        raw_type="write-up",
        normalized_raw_type="write up",
        metadata_json={},
    )
    db_session.add(raw_type)
    db_session.flush()
    suggestion = CourseRawTypeSuggestion(
        source_raw_type_id=raw_type.id,
        suggested_raw_type_id=None,
        source_observation_id=None,
        status=CourseRawTypeSuggestionStatus.PENDING,
        confidence=0.82,
        evidence="matched from import",
    )
    db_session.add(suggestion)
    db_session.commit()

    response = client.get(f"/agent/context/families/{family.id}", headers=auth_headers(client, user=user))
    assert response.status_code == 200
    payload = response.json()
    assert payload["family"]["id"] == family.id
    assert payload["family"]["canonical_label"] == "Homework"
    assert payload["raw_types"][0]["raw_type"] == "write-up"
    assert payload["pending_raw_type_suggestions"][0]["id"] == suggestion.id
    assert payload["recommended_next_action"]["lane"] == "families"
    assert payload["recommended_next_action"]["recommended_tool"] == "review_family_raw_type_suggestions"
    assert payload["blocking_conditions"][0]["code"] == "family_pending_raw_type_suggestions"
    assert "review_family_detail" in payload["available_next_tools"]


def test_agent_family_context_missing_family_returns_404(client, db_session, auth_headers) -> None:
    user = _create_user(db_session, email="agent-family-missing@example.com")
    response = client.get("/agent/context/families/999999", headers=auth_headers(client, user=user))
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "agents.context.family_not_found"
