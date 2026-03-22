from __future__ import annotations

from datetime import datetime, timezone

from app.db.models.shared import CourseRawTypeSuggestion, User
from app.modules.common.course_identity import parse_course_display
from app.modules.families.resolution_service import resolve_kind_resolution
from app.modules.families.family_service import create_course_work_item_family
from tests.support.payload_builders import build_course_parse, build_semantic_parse


def test_resolve_kind_resolution_prefers_new_family_over_inline_suggestion_generation(db_session, monkeypatch) -> None:
    user = User(email=None, notify_email="suggest-user@example.com", password_hash="hash", onboarding_completed_at=datetime.now(timezone.utc))
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    course_identity = parse_course_display("CSE 8A")
    create_course_work_item_family(
        db_session,
        user_id=user.id,
        course_dept=course_identity["course_dept"],
        course_number=course_identity["course_number"],
        course_suffix=course_identity["course_suffix"],
        course_quarter=course_identity["course_quarter"],
        course_year2=course_identity["course_year2"],
        canonical_label="Homework",
        raw_types=[],
    )

    monkeypatch.setattr(
        "app.modules.families.resolution_service.find_course_raw_type",
        lambda *args, **kwargs: None,
    )

    result = resolve_kind_resolution(
        db_session,
        user_id=user.id,
        course_parse=build_course_parse(dept="CSE", number=8, suffix="A", confidence=0.95, evidence="CSE8A"),
        semantic_parse=build_semantic_parse(raw_type="HW", event_name="HW1 reminder", ordinal=1, confidence=0.9, evidence="HW1"),
        source_kind="email",
        external_event_id="evt-1",
    )
    assert result["status"] == "new_family"
    assert result["canonical_label"] == "HW"
    assert db_session.query(CourseRawTypeSuggestion).count() == 0
