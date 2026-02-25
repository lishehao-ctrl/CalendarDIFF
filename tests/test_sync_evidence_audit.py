from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import encrypt_secret
from app.db.models import Change, ChangeType, Snapshot, SnapshotEvent, Input, InputType, User
from app.modules.sync.service import sync_input
from app.modules.sync.types import FetchResult


ICS_V1 = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Audit Test//EN
BEGIN:VEVENT
UID:event-1
DTSTART:20260220T100000Z
DTEND:20260220T110000Z
SUMMARY:CSE 151A Homework 1
DESCRIPTION:First version
END:VEVENT
END:VCALENDAR
"""

ICS_V2 = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Audit Test//EN
BEGIN:VEVENT
UID:event-1
DTSTART:20260220T120000Z
DTEND:20260220T130000Z
SUMMARY:CSE 151A Homework 1
DESCRIPTION:Updated due time
END:VEVENT
END:VCALENDAR
"""


class StubICSClient:
    def __init__(self, responses: list[FetchResult]) -> None:
        self._responses = responses
        self._index = 0

    def fetch(  # noqa: ARG002 - signature matches production client
        self,
        url: str,
        source_id: int,
        if_none_match: str | None = None,
        if_modified_since: str | None = None,
    ) -> FetchResult:
        if self._index >= len(self._responses):
            raise RuntimeError("No more stub fetch responses available")
        response = self._responses[self._index]
        self._index += 1
        return response


def test_sync_persists_snapshot_evidence_and_links_changes(tmp_path, monkeypatch, db_session: Session) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APP_SECRET_KEY", "7J2Btjj4GW8jIP5MErM81QOZeK4c7xYknVxKsgKMnmk=")
    monkeypatch.setenv("EVIDENCE_DIR", "./evidence")
    monkeypatch.setenv("ENABLE_NOTIFICATIONS", "false")
    get_settings.cache_clear()

    user = User(email="owner@example.com")
    db_session.add(user)
    db_session.flush()

    source = Input(
        user_id=user.id,
        type=InputType.ICS,
        identity_key="Audit Input",
        encrypted_url=encrypt_secret("https://example.com/private.ics"),
        interval_minutes=15,
        is_active=True,
    )
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)

    client = StubICSClient(
        [
            FetchResult(
                content=ICS_V1,
                etag="v1",
                fetched_at_utc=datetime(2026, 2, 19, 20, 31, 10, tzinfo=timezone.utc),
            ),
            FetchResult(
                content=ICS_V2,
                etag="v2",
                fetched_at_utc=datetime(2026, 2, 19, 21, 31, 10, tzinfo=timezone.utc),
            ),
        ]
    )

    first_run = sync_input(db=db_session, input=source, ics_client=client)
    second_run = sync_input(db=db_session, input=source, ics_client=client)

    assert first_run.last_error is None
    assert first_run.is_baseline_sync is True
    assert first_run.changes_created == 0
    assert second_run.last_error is None
    assert second_run.is_baseline_sync is False
    assert second_run.changes_created == 1

    snapshots = db_session.scalars(
        select(Snapshot).where(Snapshot.input_id == source.id).order_by(Snapshot.id.asc())
    ).all()
    assert len(snapshots) == 2

    expected_hashes = {_normalized_hash(ICS_V1), _normalized_hash(ICS_V2)}
    assert {snapshot.content_hash for snapshot in snapshots} == expected_hashes

    for snapshot in snapshots:
        assert snapshot.raw_evidence_key is not None
        path = Path(str(snapshot.raw_evidence_key["path"]))
        assert path.exists()
        assert path.parent.name == f"source_{source.id}"

    due_change = db_session.scalar(
        select(Change)
        .where(
            Change.input_id == source.id,
            Change.change_type == ChangeType.DUE_CHANGED,
        )
        .order_by(Change.id.desc())
    )
    assert due_change is not None
    assert due_change.before_snapshot_id == snapshots[0].id
    assert due_change.after_snapshot_id == snapshots[1].id
    assert due_change.evidence_keys is not None
    assert due_change.evidence_keys["before"] == snapshots[0].raw_evidence_key
    assert due_change.evidence_keys["after"] == snapshots[1].raw_evidence_key

    get_settings.cache_clear()


def test_sync_304_not_modified_skips_snapshot_and_diff(tmp_path, monkeypatch, db_session: Session) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APP_SECRET_KEY", "7J2Btjj4GW8jIP5MErM81QOZeK4c7xYknVxKsgKMnmk=")
    monkeypatch.setenv("EVIDENCE_DIR", "./evidence")
    monkeypatch.setenv("ENABLE_NOTIFICATIONS", "false")
    get_settings.cache_clear()

    user = User(email="owner@example.com")
    db_session.add(user)
    db_session.flush()

    source = Input(
        user_id=user.id,
        type=InputType.ICS,
        identity_key="Not Modified Input",
        encrypted_url=encrypt_secret("https://example.com/private.ics"),
        interval_minutes=15,
        is_active=True,
    )
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)

    client = StubICSClient(
        [
            FetchResult(
                content=ICS_V1,
                etag="etag-v1",
                fetched_at_utc=datetime(2026, 2, 19, 20, 31, 10, tzinfo=timezone.utc),
                last_modified="Wed, 19 Feb 2026 20:31:10 GMT",
                status_code=200,
            ),
            FetchResult(
                content=None,
                etag="etag-v1",
                fetched_at_utc=datetime(2026, 2, 19, 21, 31, 10, tzinfo=timezone.utc),
                last_modified="Wed, 19 Feb 2026 20:31:10 GMT",
                status_code=304,
                not_modified=True,
            ),
        ]
    )

    first_run = sync_input(db=db_session, input=source, ics_client=client)
    second_run = sync_input(db=db_session, input=source, ics_client=client)

    assert first_run.changes_created == 0
    assert first_run.is_baseline_sync is True
    assert second_run.changes_created == 0
    assert second_run.is_baseline_sync is False

    snapshots = db_session.scalars(
        select(Snapshot).where(Snapshot.input_id == source.id).order_by(Snapshot.id.asc())
    ).all()
    assert len(snapshots) == 1
    snapshot_event_count = db_session.scalar(
        select(func.count(SnapshotEvent.id)).join(Snapshot, SnapshotEvent.snapshot_id == Snapshot.id).where(
            Snapshot.input_id == source.id
        )
    )
    assert snapshot_event_count == 1

    changes = db_session.scalars(select(Change).where(Change.input_id == source.id)).all()
    assert changes == []

    db_session.refresh(source)
    assert source.etag == "etag-v1"
    assert source.last_modified == "Wed, 19 Feb 2026 20:31:10 GMT"
    assert source.last_content_hash == _normalized_hash(ICS_V1)
    assert source.last_checked_at is not None
    assert source.last_error is None

    get_settings.cache_clear()


def test_sync_same_normalized_hash_skips_snapshot_and_diff(tmp_path, monkeypatch, db_session: Session) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APP_SECRET_KEY", "7J2Btjj4GW8jIP5MErM81QOZeK4c7xYknVxKsgKMnmk=")
    monkeypatch.setenv("EVIDENCE_DIR", "./evidence")
    monkeypatch.setenv("ENABLE_NOTIFICATIONS", "false")
    get_settings.cache_clear()

    user = User(email="owner@example.com")
    db_session.add(user)
    db_session.flush()

    source = Input(
        user_id=user.id,
        type=InputType.ICS,
        identity_key="Normalized Hash Input",
        encrypted_url=encrypt_secret("https://example.com/private.ics"),
        interval_minutes=15,
        is_active=True,
    )
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)

    variant_with_crlf_and_spaces = ICS_V1.replace(b"\n", b"   \r\n")

    client = StubICSClient(
        [
            FetchResult(
                content=ICS_V1,
                etag="etag-v1",
                fetched_at_utc=datetime(2026, 2, 19, 20, 31, 10, tzinfo=timezone.utc),
                last_modified="Wed, 19 Feb 2026 20:31:10 GMT",
                status_code=200,
            ),
            FetchResult(
                content=variant_with_crlf_and_spaces,
                etag="etag-v2",
                fetched_at_utc=datetime(2026, 2, 19, 21, 31, 10, tzinfo=timezone.utc),
                last_modified="Wed, 19 Feb 2026 21:31:10 GMT",
                status_code=200,
            ),
        ]
    )

    first_run = sync_input(db=db_session, input=source, ics_client=client)
    second_run = sync_input(db=db_session, input=source, ics_client=client)

    assert first_run.is_baseline_sync is True
    assert second_run.is_baseline_sync is False
    assert second_run.changes_created == 0

    snapshots = db_session.scalars(
        select(Snapshot).where(Snapshot.input_id == source.id).order_by(Snapshot.id.asc())
    ).all()
    assert len(snapshots) == 1
    assert snapshots[0].content_hash == _normalized_hash(ICS_V1)
    snapshot_event_count = db_session.scalar(
        select(func.count(SnapshotEvent.id)).join(Snapshot, SnapshotEvent.snapshot_id == Snapshot.id).where(
            Snapshot.input_id == source.id
        )
    )
    assert snapshot_event_count == 1

    db_session.refresh(source)
    assert source.etag == "etag-v2"
    assert source.last_modified == "Wed, 19 Feb 2026 21:31:10 GMT"
    assert source.last_content_hash == _normalized_hash(ICS_V1)
    assert source.last_error is None

    get_settings.cache_clear()


def _normalized_hash(content: bytes) -> str:
    normalized_text = content.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized_text.split("\n")]
    joined = "\n".join(lines).rstrip("\n")
    if joined:
        joined += "\n"
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()
