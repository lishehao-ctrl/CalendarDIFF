from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

import scripts.run_claw_mcp_smoke as claw_smoke
from app.db.models.shared import CourseWorkItemLabelFamily, User
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


def _create_family(db_session, *, user_id: int, course_display: str, canonical_label: str) -> CourseWorkItemLabelFamily:
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


def test_render_markdown_includes_steps() -> None:
    summary = {
        "generated_at": "2026-03-24T00:00:00+00:00",
        "success": True,
        "fixture": {"notify_email": "agent-live-eval@example.com"},
        "steps": [
            {"name": "workspace_context", "ok": True, "detail": "Loaded workspace context."},
            {"name": "change_proposal", "ok": True, "detail": "Created proposal."},
        ],
    }

    markdown = claw_smoke.render_markdown(summary)
    assert "Claw MCP Smoke" in markdown
    assert "`PASS` `workspace_context`" in markdown
    assert "agent-live-eval@example.com" in markdown


def test_ensure_family_preview_fixture_creates_raw_type_and_target_family(db_session, monkeypatch) -> None:
    user = _create_user(db_session, email="claw-smoke-fixture@example.com")
    source_family = _create_family(db_session, user_id=user.id, course_display="CSE 160 WI26", canonical_label="Homework")

    monkeypatch.setattr(claw_smoke, "get_session_factory", lambda: (lambda: db_session))

    raw_type_id, target_family_id = claw_smoke.ensure_family_preview_fixture(user_id=user.id, source_family_id=source_family.id)

    raw_type = db_session.execute(select(claw_smoke.CourseWorkItemRawType).where(claw_smoke.CourseWorkItemRawType.id == raw_type_id)).scalar_one()
    target_family = db_session.execute(select(CourseWorkItemLabelFamily).where(CourseWorkItemLabelFamily.id == target_family_id)).scalar_one()
    assert raw_type.family_id == source_family.id
    assert target_family.id != source_family.id
    assert target_family.normalized_course_identity == source_family.normalized_course_identity
