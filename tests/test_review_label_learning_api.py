from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models.input import InputSource, SourceKind
from app.db.models.review import Change, ChangeOrigin, ChangeSourceRef, ChangeType, ReviewStatus, SourceEventObservation
from app.db.models.shared import User
from app.modules.users.course_work_item_families_service import create_course_work_item_family


def _create_user_with_calendar_source(db_session) -> tuple[User, InputSource]:
    user = User(
        email="learn@example.com",
        notify_email="learn@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()
    source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.CALENDAR,
        provider="ics",
        source_key="canvas_ics",
        display_name="Canvas ICS",
        is_active=True,
        poll_interval_seconds=900,
    )
    db_session.add(source)
    db_session.commit()
    db_session.refresh(user)
    db_session.refresh(source)
    return user, source


def _seed_pending_change(db_session, *, user: User, source: InputSource, raw_label: str, title: str) -> Change:
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


def test_label_learning_preview_and_create_family(client, db_session, auth_headers) -> None:
    user, source = _create_user_with_calendar_source(db_session)
    change = _seed_pending_change(db_session, user=user, source=source, raw_label="Lab Paper", title="Lab Paper 1")
    headers = auth_headers(client, user=user)

    preview = client.post(f"/review/changes/{change.id}/label-learning/preview", headers=headers)
    assert preview.status_code == 200
    payload = preview.json()
    assert payload["course_display"] == "CSE 100 WI26"
    assert payload["raw_label"] == "Lab Paper"
    assert payload["status"] == "unresolved"

    apply = client.post(
        f"/review/changes/{change.id}/label-learning",
        headers=headers,
        json={"mode": "create_family", "canonical_label": "Lab Paper"},
    )
    assert apply.status_code == 200
    applied = apply.json()
    assert applied["applied"] is True
    assert applied["canonical_label"] == "Lab Paper"


def test_label_learning_add_alias_to_existing_family(client, db_session, auth_headers) -> None:
    user, source = _create_user_with_calendar_source(db_session)
    family = create_course_work_item_family(
        db_session,
        user_id=user.id,
        course_dept="CSE",
        course_number=100,
        course_quarter="WI",
        course_year2=26,
        canonical_label="Homework",
        raw_types=["homework"],
    )
    change = _seed_pending_change(db_session, user=user, source=source, raw_label="HW", title="HW1")
    headers = auth_headers(client, user=user)

    apply = client.post(
        f"/review/changes/{change.id}/label-learning",
        headers=headers,
        json={"mode": "add_alias", "family_id": family.id},
    )
    assert apply.status_code == 200
    applied = apply.json()
    assert applied["family_id"] == family.id
    assert applied["canonical_label"] == "Homework"

    refreshed = db_session.scalar(select(Change).where(Change.id == change.id))
    assert refreshed is not None
