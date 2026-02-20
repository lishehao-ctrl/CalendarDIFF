from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import encrypt_secret
from app.db.base import Base
from app.db.models import Change, ChangeType, Snapshot, Source, SourceType, User
from app.modules.sync.service import sync_source
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

    def fetch(self, url: str, source_id: int) -> FetchResult:  # noqa: ARG002 - signature matches production client
        if self._index >= len(self._responses):
            raise RuntimeError("No more stub fetch responses available")
        response = self._responses[self._index]
        self._index += 1
        return response


def test_sync_persists_snapshot_evidence_and_links_changes(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APP_SECRET_KEY", "7J2Btjj4GW8jIP5MErM81QOZeK4c7xYknVxKsgKMnmk=")
    monkeypatch.setenv("EVIDENCE_DIR", "./evidence")
    monkeypatch.setenv("ENABLE_NOTIFICATIONS", "false")
    get_settings.cache_clear()

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        user = User(email="owner@example.com")
        db.add(user)
        db.flush()

        source = Source(
            user_id=user.id,
            type=SourceType.ICS,
            name="Audit Source",
            encrypted_url=encrypt_secret("https://example.com/private.ics"),
            interval_minutes=15,
            is_active=True,
        )
        db.add(source)
        db.commit()
        db.refresh(source)

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

        first_run = sync_source(db=db, source=source, ics_client=client)
        second_run = sync_source(db=db, source=source, ics_client=client)

        assert first_run.last_error is None
        assert second_run.last_error is None
        assert second_run.changes_created == 1

        snapshots = db.scalars(select(Snapshot).where(Snapshot.source_id == source.id).order_by(Snapshot.id.asc())).all()
        assert len(snapshots) == 2

        expected_hashes = {hashlib.sha256(ICS_V1).hexdigest(), hashlib.sha256(ICS_V2).hexdigest()}
        assert {snapshot.content_hash for snapshot in snapshots} == expected_hashes

        for snapshot in snapshots:
            assert snapshot.raw_evidence_key is not None
            path = Path(str(snapshot.raw_evidence_key["path"]))
            assert path.exists()
            assert path.parent.name == f"source_{source.id}"

        due_change = db.scalar(
            select(Change)
            .where(
                Change.source_id == source.id,
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

    engine.dispose()
    get_settings.cache_clear()
