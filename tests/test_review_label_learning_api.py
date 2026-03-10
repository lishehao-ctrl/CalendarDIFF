from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.models.input import InputSource, InputSourceConfig, InputSourceCursor, InputSourceSecret, SourceKind
from app.db.models.review import Change, ChangeType, Input, InputType, ReviewStatus, SourceEventObservation
from app.db.models.shared import User
from app.modules.core_ingest.evidence_snapshots import materialize_change_snapshot
from app.modules.users.course_work_item_families_service import create_course_work_item_family
from tests.support.payload_builders import build_calendar_payload, build_course_parse, build_event_parts, build_link_signals, build_work_item_parse


def _create_user_with_calendar_source(db_session) -> tuple[User, InputSource, Input]:
    now = datetime.now(timezone.utc)
    user = User(email="learn@example.com", notify_email="learn@example.com", onboarding_completed_at=now)
    db_session.add(user)
    db_session.flush()
    source = InputSource(user_id=user.id, source_kind=SourceKind.CALENDAR, provider="ics", source_key="canvas_ics", display_name="Canvas ICS", is_active=True, poll_interval_seconds=900, next_poll_at=now)
    db_session.add(source)
    db_session.flush()
    db_session.add(InputSourceConfig(source_id=source.id, schema_version=1, config_json={}))
    db_session.add(InputSourceSecret(source_id=source.id, encrypted_payload="x"))
    db_session.add(InputSourceCursor(source_id=source.id, version=1, cursor_json={}))
    canonical = Input(user_id=user.id, type=InputType.ICS, identity_key=f"canonical:user:{user.id}", is_active=True)
    db_session.add(canonical)
    db_session.commit()
    db_session.refresh(user)
    db_session.refresh(source)
    db_session.refresh(canonical)
    return user, source, canonical



def _seed_pending_change(
    db_session,
    *,
    user: User,
    source: InputSource,
    canonical: Input,
    raw_label: str,
    title: str,
    ordinal: int,
    course_key: str = "CSE 100 WI26",
    course_parse: dict | None = None,
    external_event_id: str | None = None,
) -> Change:
    due = datetime(2026, 3, 12, 23, 59, tzinfo=timezone.utc) + timedelta(days=max(0, ordinal - 1))
    resolved_external_event_id = external_event_id or f"evt-{ordinal}"
    resolved_course_parse = course_parse or build_course_parse(
        dept="CSE",
        number=100,
        quarter="WI",
        year2=26,
        confidence=0.95,
        evidence=course_key,
    )
    payload = build_calendar_payload(
        external_event_id=resolved_external_event_id,
        title=title,
        start_at=due,
        end_at=due + timedelta(hours=1),
        course_parse=resolved_course_parse,
        work_item_parse=build_work_item_parse(raw_kind_label=raw_label, ordinal=ordinal, confidence=0.95, evidence=title),
        event_parts=build_event_parts(type="deadline", index=ordinal, confidence=0.95, evidence=title),
        link_signals=build_link_signals(),
    )
    db_session.add(
        SourceEventObservation(
            user_id=user.id,
            source_id=source.id,
            source_kind=source.source_kind,
            provider=source.provider,
            external_event_id=resolved_external_event_id,
            merge_key=f"tmp-{resolved_external_event_id}",
            event_payload=payload,
            event_hash=str(ordinal) * 64,
            observed_at=datetime.now(timezone.utc),
            is_active=True,
            last_request_id=f"req-{resolved_external_event_id}",
        )
    )
    snap = materialize_change_snapshot(
        db=db_session,
        input_id=canonical.id,
        event_payload=payload,
        fallback_json={
            "uid": f"tmp-{resolved_external_event_id}",
            "title": title,
            "course_label": course_key,
            "start_at_utc": due.isoformat(),
            "end_at_utc": (due + timedelta(hours=1)).isoformat(),
        },
        retrieved_at=datetime.now(timezone.utc),
    )
    change = Change(
        input_id=canonical.id,
        event_uid=f"tmp-{resolved_external_event_id}",
        change_type=ChangeType.CREATED,
        detected_at=datetime.now(timezone.utc),
        before_json=None,
        after_json={
            "uid": f"tmp-{resolved_external_event_id}",
            "title": title,
            "course_label": course_key,
            "start_at_utc": due.isoformat(),
            "end_at_utc": (due + timedelta(hours=1)).isoformat(),
        },
        delta_seconds=None,
        review_status=ReviewStatus.PENDING,
        proposal_merge_key=f"tmp-{resolved_external_event_id}",
        proposal_sources_json=[{"source_id": source.id, "source_kind": "calendar", "provider": "ics", "external_event_id": resolved_external_event_id, "confidence": 0.95}],
        after_snapshot_id=snap,
    )
    db_session.add(change)
    db_session.commit()
    db_session.refresh(change)
    return change



def test_label_learning_preview_and_create_family(client, db_session, auth_headers) -> None:
    user, source, canonical = _create_user_with_calendar_source(db_session)
    change = _seed_pending_change(db_session, user=user, source=source, canonical=canonical, raw_label="Lab Paper", title="Lab Paper 1", ordinal=1)
    headers = auth_headers(client, user=user)

    preview = client.post(f"/review/changes/{change.id}/label-learning/preview", headers=headers)
    assert preview.status_code == 200
    payload = preview.json()
    assert payload["course_key"] == "CSE 100 WI26"
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
    user, source, canonical = _create_user_with_calendar_source(db_session)
    family = create_course_work_item_family(db_session, user_id=user.id, course_key="CSE 100 WI26", canonical_label="Homework", aliases=["homework"])
    change = _seed_pending_change(db_session, user=user, source=source, canonical=canonical, raw_label="HW", title="HW1", ordinal=1)
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



def test_label_learning_rebuild_is_scoped_to_course(client, db_session, auth_headers) -> None:
    user, source, canonical = _create_user_with_calendar_source(db_session)
    target_family = create_course_work_item_family(db_session, user_id=user.id, course_key="CSE 100 WI26", canonical_label="Homework", aliases=["homework"])
    create_course_work_item_family(db_session, user_id=user.id, course_key="MATH 20B WI26", canonical_label="Quiz", aliases=["quiz"])

    target_change = _seed_pending_change(
        db_session,
        user=user,
        source=source,
        canonical=canonical,
        raw_label="PSET",
        title="PSET 1",
        ordinal=1,
        course_key="CSE 100 WI26",
        course_parse=build_course_parse(dept="CSE", number=100, quarter="WI", year2=26, confidence=0.95, evidence="CSE 100 WI26"),
        external_event_id="evt-target",
    )
    preserved_change = _seed_pending_change(
        db_session,
        user=user,
        source=source,
        canonical=canonical,
        raw_label="Quiz",
        title="Quiz 1",
        ordinal=2,
        course_key="MATH 20B WI26",
        course_parse=build_course_parse(dept="MATH", number=20, suffix="B", quarter="WI", year2=26, confidence=0.95, evidence="MATH 20B WI26"),
        external_event_id="evt-preserved",
    )
    preserved_change.viewed_at = datetime.now(timezone.utc)
    preserved_change.viewed_note = "keep"
    db_session.commit()
    db_session.refresh(preserved_change)

    headers = auth_headers(client, user=user)
    apply = client.post(
        f"/review/changes/{target_change.id}/label-learning",
        headers=headers,
        json={"mode": "add_alias", "family_id": target_family.id},
    )
    assert apply.status_code == 200

    preserved_after = db_session.scalar(select(Change).where(Change.id == preserved_change.id))
    assert preserved_after is not None
    assert preserved_after.viewed_at == preserved_change.viewed_at
    assert preserved_after.viewed_note == "keep"
    preserved_payload = preserved_after.after_json if isinstance(preserved_after.after_json, dict) else {}
    assert preserved_payload.get("course_label") == "MATH 20B WI26"


def test_label_learning_apply_rejects_missing_family_id(client, db_session, auth_headers) -> None:
    user, source, canonical = _create_user_with_calendar_source(db_session)
    change = _seed_pending_change(db_session, user=user, source=source, canonical=canonical, raw_label="HW", title="HW1", ordinal=1)
    headers = auth_headers(client, user=user)

    response = client.post(
        f"/review/changes/{change.id}/label-learning",
        headers=headers,
        json={"mode": "add_alias"},
    )
    assert response.status_code == 422
    assert "family_id is required" in response.json()["detail"]
