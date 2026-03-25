from __future__ import annotations

from datetime import datetime, timezone

from app.db.models.input import InputSource, SourceKind
from app.db.models.review import Change, ChangeOrigin, ChangeSourceRef, ChangeType, ReviewStatus
from app.db.models.shared import CourseWorkItemLabelFamily, User
from app.modules.common.course_identity import normalize_label_token, normalized_course_identity_key
from app.modules.common.change_evidence import freeze_observation_evidence


def _create_user_with_source(db_session, *, provider: str, source_kind: SourceKind) -> tuple[User, InputSource]:
    user = User(
        email=f"{provider}-preview@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()
    source = InputSource(
        user_id=user.id,
        source_kind=source_kind,
        provider=provider,
        source_key=f"{provider}-{user.id}",
        display_name=f"{provider} source",
        is_active=True,
        poll_interval_seconds=900,
    )
    db_session.add(source)
    db_session.commit()
    db_session.refresh(user)
    db_session.refresh(source)
    return user, source


def test_review_change_after_preview_returns_frozen_calendar_evidence(client, db_session, auth_headers) -> None:
    user, _source = _create_user_with_source(db_session, provider="ics", source_kind=SourceKind.CALENDAR)
    semantic_payload = {
        "uid": "ent-cal",
        "course_dept": "CSE",
        "course_number": 100,
        "family_name": "Homework",
        "event_name": "Homework 1",
        "ordinal": 1,
        "due_date": "2026-03-21",
        "due_time": "23:59:00",
        "time_precision": "datetime",
    }
    evidence = freeze_observation_evidence(
        provider="ics",
        event_payload={
            "source_facts": {
                "external_event_id": "evt-cal-1",
                "source_title": "Homework 1",
                "source_summary": "Calendar event",
                "source_dtstart_utc": "2026-03-21T23:59:00+00:00",
                "source_dtend_utc": "2026-03-22T00:59:00+00:00",
                "location": "Online",
            }
        },
        semantic_payload=semantic_payload,
    )
    db_session.add(
        Change(
            user_id=user.id,
            entity_uid="ent-cal",
            change_origin=ChangeOrigin.INGEST_PROPOSAL,
            change_type=ChangeType.CREATED,
            detected_at=datetime.now(timezone.utc),
            after_semantic_json=semantic_payload,
            after_evidence_json=evidence.model_dump(mode="json") if evidence is not None else None,
            review_status=ReviewStatus.PENDING,
        )
    )
    db_session.commit()

    response = client.get("/changes/1/evidence/after/preview", headers=auth_headers(client, user=user))
    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "ics"
    assert payload["structured_kind"] == "ics_event"
    assert payload["structured_items"][0]["source_title"] == "Homework 1"
    assert payload["events"][0]["summary"] == "Homework 1"


def test_review_change_after_preview_returns_frozen_gmail_evidence(client, db_session, auth_headers) -> None:
    user, _source = _create_user_with_source(db_session, provider="gmail", source_kind=SourceKind.EMAIL)
    semantic_payload = {
        "uid": "ent-mail",
        "course_dept": "CSE",
        "course_number": 120,
        "family_name": "Quiz",
        "event_name": "Quiz 1",
        "ordinal": 1,
        "due_date": "2026-03-25",
        "due_time": "10:00:00",
        "time_precision": "datetime",
    }
    evidence = freeze_observation_evidence(
        provider="gmail",
        event_payload={
            "source_facts": {
                "external_event_id": "gmail-1",
                "source_title": "Quiz 1 reminder",
                "source_summary": "Please submit Quiz 1 by 10am.",
                "source_dtstart_utc": "2026-03-25T10:00:00+00:00",
                "source_dtend_utc": "2026-03-25T11:00:00+00:00",
                "from_header": "Professor Example <prof@example.edu>",
                "thread_id": "thread-1",
                "internal_date": "2026-03-20T18:00:00+00:00",
            }
        },
        semantic_payload=semantic_payload,
    )
    db_session.add(
        Change(
            user_id=user.id,
            entity_uid="ent-mail",
            change_origin=ChangeOrigin.INGEST_PROPOSAL,
            change_type=ChangeType.CREATED,
            detected_at=datetime.now(timezone.utc),
            after_semantic_json=semantic_payload,
            after_evidence_json=evidence.model_dump(mode="json") if evidence is not None else None,
            review_status=ReviewStatus.PENDING,
        )
    )
    db_session.commit()

    response = client.get("/changes/1/evidence/after/preview", headers=auth_headers(client, user=user))
    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "gmail"
    assert payload["structured_kind"] == "gmail_event"
    assert payload["structured_items"][0]["sender"] == "Professor Example <prof@example.edu>"
    assert "Please submit Quiz 1" in (payload["preview_text"] or "")


def test_change_listing_exposes_frozen_evidence_availability(client, db_session, auth_headers) -> None:
    user, _source = _create_user_with_source(db_session, provider="ics", source_kind=SourceKind.CALENDAR)
    family = CourseWorkItemLabelFamily(
        user_id=user.id,
        course_dept="CSE",
        course_number=100,
        course_suffix=None,
        course_quarter=None,
        course_year2=None,
        normalized_course_identity=normalized_course_identity_key(
            course_dept="CSE",
            course_number=100,
            course_suffix=None,
            course_quarter=None,
            course_year2=None,
        ),
        canonical_label="Quiz",
        normalized_canonical_label=normalize_label_token("Quiz"),
    )
    db_session.add(family)
    db_session.flush()
    before_payload = {
        "uid": "ent-before-only",
        "course_dept": "CSE",
        "course_number": 100,
        "family_id": family.id,
        "family_name": "Quiz",
        "event_name": "Quiz 2",
        "ordinal": 2,
        "due_date": "2026-03-28",
        "due_time": "10:00:00",
        "time_precision": "datetime",
    }
    before_evidence = freeze_observation_evidence(
        provider="ics",
        event_payload={
            "source_facts": {
                "external_event_id": "evt-before-only",
                "source_title": "Quiz 2",
                "source_summary": "Calendar event",
                "source_dtstart_utc": "2026-03-28T10:00:00+00:00",
                "source_dtend_utc": "2026-03-28T11:00:00+00:00",
                "location": "Center Hall",
            }
        },
        semantic_payload=before_payload,
    )
    db_session.add(
        Change(
            user_id=user.id,
            entity_uid="ent-before-only",
            change_origin=ChangeOrigin.INGEST_PROPOSAL,
            change_type=ChangeType.REMOVED,
            detected_at=datetime.now(timezone.utc),
            before_semantic_json=before_payload,
            after_semantic_json=None,
            source_refs=[
                ChangeSourceRef(
                    position=0,
                    source_id=_source.id,
                    source_kind=_source.source_kind,
                    provider=_source.provider,
                    external_event_id="evt-before-only",
                    confidence=0.95,
                )
            ],
            before_evidence_json=before_evidence.model_dump(mode="json") if before_evidence is not None else None,
            after_evidence_json=None,
            review_status=ReviewStatus.PENDING,
        )
    )
    db_session.commit()

    response = client.get("/changes?review_status=pending", headers=auth_headers(client, user=user))
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["evidence_availability"] == {"before": True, "after": False}
