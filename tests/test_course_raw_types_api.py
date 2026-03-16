from __future__ import annotations

from datetime import datetime, timezone

from app.db.models.shared import User
from app.modules.common.course_identity import parse_course_display


def _create_user(db_session) -> User:
    user = User(
        email=None,
        notify_email="rawtype-user@example.com",
        password_hash="hash",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _course_identity_payload(course_display: str) -> dict:
    parsed = parse_course_display(course_display)
    return {
        "course_dept": parsed["course_dept"],
        "course_number": parsed["course_number"],
        "course_suffix": parsed["course_suffix"],
        "course_quarter": parsed["course_quarter"],
        "course_year2": parsed["course_year2"],
    }


def test_course_raw_type_list_and_relink(input_client, db_session, authenticate_client) -> None:
    user = _create_user(db_session)
    authenticate_client(input_client, user=user)

    first = input_client.post(
        "/review/course-work-item-families",
        headers={"X-API-Key": "test-api-key"},
        json={**_course_identity_payload("CSE 100 WI26"), "canonical_label": "Homework", "raw_types": ["hw"]},
    )
    assert first.status_code == 201
    second = input_client.post(
        "/review/course-work-item-families",
        headers={"X-API-Key": "test-api-key"},
        json={**_course_identity_payload("CSE 100 WI26"), "canonical_label": "Programming Assignment", "raw_types": ["pa"]},
    )
    assert second.status_code == 201

    raw_types = input_client.get(
        "/review/course-work-item-raw-types?course_dept=CSE&course_number=100&course_quarter=WI&course_year2=26",
        headers={"X-API-Key": "test-api-key"},
    )
    assert raw_types.status_code == 200
    payload = raw_types.json()
    assert {row["raw_type"] for row in payload} == {"hw", "pa"}
    hw_row = next(row for row in payload if row["raw_type"] == "hw")

    relink = input_client.post(
        "/review/course-work-item-raw-types/relink",
        headers={"X-API-Key": "test-api-key"},
        json={"raw_type_id": hw_row["id"], "family_id": second.json()["id"]},
    )
    assert relink.status_code == 200
    moved = relink.json()
    assert moved["raw_type_id"] == hw_row["id"]
    assert moved["family_id"] == second.json()["id"]
    assert moved["previous_family_id"] == first.json()["id"]
