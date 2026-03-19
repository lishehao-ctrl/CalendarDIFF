from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.input import InputSource, SourceKind
from app.db.models.review import EventEntity, EventEntityLifecycle, SourceEventObservation
from app.db.models.shared import CourseWorkItemLabelFamily, User
from app.modules.common.course_identity import normalize_label_token, normalized_course_identity_key
from app.modules.core_ingest.entity_resolution import resolve_entity_uid


def _create_user_source_family(db_session: Session) -> tuple[User, InputSource, CourseWorkItemLabelFamily]:
    user = User(
        email="entity-resolution@example.com",
        notify_email="entity-resolution@example.com",
        onboarding_completed_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    db_session.flush()

    source = InputSource(
        user_id=user.id,
        source_kind=SourceKind.EMAIL,
        provider="gmail",
        source_key=f"entity-resolution-{user.id}",
        display_name="Entity Resolution",
        is_active=True,
        poll_interval_seconds=900,
        next_poll_at=datetime.now(timezone.utc),
    )
    db_session.add(source)
    db_session.flush()

    family = CourseWorkItemLabelFamily(
        user_id=user.id,
        course_dept="CSE",
        course_number=120,
        course_suffix=None,
        course_quarter="WI",
        course_year2=26,
        normalized_course_identity=normalized_course_identity_key(
            course_dept="CSE",
            course_number=120,
            course_suffix=None,
            course_quarter="WI",
            course_year2=26,
        ),
        canonical_label="Homework",
        normalized_canonical_label=normalize_label_token("Homework"),
    )
    db_session.add(family)
    db_session.commit()
    db_session.refresh(source)
    db_session.refresh(family)
    return user, source, family


def _kind_resolution(*, family_id: int, ordinal: int | None = 1) -> dict:
    return {
        "status": "exact",
        "family_id": family_id,
        "canonical_label": "Homework",
        "raw_type": "Homework",
        "ordinal": ordinal,
    }


def _course_parse(*, quarter: str = "WI", year2: int = 26) -> dict:
    return {
        "dept": "CSE",
        "number": 120,
        "suffix": None,
        "quarter": quarter,
        "year2": year2,
    }


def _observation_payload(*, entity_uid: str, external_event_id: str, family_id: int, ordinal: int = 1) -> dict:
    return {
        "source_facts": {
            "external_event_id": external_event_id,
            "source_title": "HW1",
            "internal_date": "2026-03-01T18:00:00+00:00",
        },
        "semantic_event": {
            "uid": entity_uid,
            "course_dept": "CSE",
            "course_number": 120,
            "course_suffix": None,
            "course_quarter": "WI",
            "course_year2": 26,
            "family_id": family_id,
            "family_name": "Homework",
            "raw_type": "Homework",
            "event_name": "HW1",
            "ordinal": ordinal,
            "due_date": "2026-03-09",
            "time_precision": "date_only",
            "confidence": 0.9,
        },
        "link_signals": {},
        "kind_resolution": _kind_resolution(family_id=family_id, ordinal=ordinal),
    }


def test_entity_resolution_reuses_active_observation_for_same_source_pair(db_session: Session) -> None:
    user, source, family = _create_user_source_family(db_session)
    db_session.add(
        SourceEventObservation(
            user_id=user.id,
            source_id=source.id,
            source_kind=source.source_kind,
            provider=source.provider,
            external_event_id="msg-1",
            entity_uid="entity-existing-1",
            event_payload=_observation_payload(entity_uid="entity-existing-1", external_event_id="msg-1", family_id=family.id),
            event_hash="hash-msg-1",
            observed_at=datetime.now(timezone.utc),
            is_active=True,
            last_request_id="seed",
        )
    )
    db_session.commit()

    resolved = resolve_entity_uid(
        db=db_session,
        source=source,
        external_event_id="msg-1",
        course_parse=_course_parse(),
        kind_resolution=_kind_resolution(family_id=family.id),
    )

    assert resolved.status == "resolved"
    assert resolved.entity_uid == "entity-existing-1"
    assert resolved.matched_via == "same_source_observation"


def test_entity_resolution_reuses_unique_active_entity(db_session: Session) -> None:
    user, source, family = _create_user_source_family(db_session)
    db_session.add(
        EventEntity(
            user_id=user.id,
            entity_uid="entity-approved-1",
            lifecycle=EventEntityLifecycle.ACTIVE,
            course_dept="CSE",
            course_number=120,
            course_suffix=None,
            course_quarter="WI",
            course_year2=26,
            family_id=family.id,
            raw_type="Homework",
            event_name="HW1",
            ordinal=1,
            due_date=None,
            due_time=None,
            time_precision="date_only",
        )
    )
    db_session.commit()

    resolved = resolve_entity_uid(
        db=db_session,
        source=source,
        external_event_id="msg-new",
        course_parse=_course_parse(),
        kind_resolution=_kind_resolution(family_id=family.id),
    )

    assert resolved.status == "resolved"
    assert resolved.entity_uid == "entity-approved-1"
    assert resolved.matched_via == "active_entity"


def test_entity_resolution_marks_multiple_matching_entities_as_ambiguous(db_session: Session) -> None:
    user, source, family = _create_user_source_family(db_session)
    for entity_uid in ("entity-approved-1", "entity-approved-2"):
        db_session.add(
            EventEntity(
                user_id=user.id,
                entity_uid=entity_uid,
                lifecycle=EventEntityLifecycle.ACTIVE,
                course_dept="CSE",
                course_number=120,
                course_suffix=None,
                course_quarter="WI",
                course_year2=26,
                family_id=family.id,
                raw_type="Homework",
                event_name="HW1",
                ordinal=1,
                due_date=None,
                due_time=None,
                time_precision="date_only",
            )
        )
    db_session.commit()

    resolved = resolve_entity_uid(
        db=db_session,
        source=source,
        external_event_id="msg-ambiguous",
        course_parse=_course_parse(),
        kind_resolution=_kind_resolution(family_id=family.id),
    )

    assert resolved.status == "unresolved"
    assert resolved.reason_code == "ambiguous_entity_resolution"


def test_entity_resolution_creates_new_entity_uid_when_tuple_is_unique_and_unseen(db_session: Session) -> None:
    _user, source, family = _create_user_source_family(db_session)

    resolved = resolve_entity_uid(
        db=db_session,
        source=source,
        external_event_id="msg-new-entity",
        course_parse=_course_parse(),
        kind_resolution=_kind_resolution(family_id=family.id),
    )

    assert resolved.status == "resolved"
    assert isinstance(resolved.entity_uid, str)
    assert resolved.entity_uid.startswith("entity-")
    assert resolved.matched_via == "new_entity"


def test_entity_resolution_marks_missing_ordinal_as_insufficient(db_session: Session) -> None:
    _user, source, family = _create_user_source_family(db_session)

    resolved = resolve_entity_uid(
        db=db_session,
        source=source,
        external_event_id="msg-insufficient",
        course_parse=_course_parse(),
        kind_resolution=_kind_resolution(family_id=family.id, ordinal=None),
    )

    assert resolved.status == "unresolved"
    assert resolved.reason_code == "insufficient_entity_resolution"
