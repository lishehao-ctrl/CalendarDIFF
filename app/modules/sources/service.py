from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import decrypt_secret, encrypt_secret
from app.db.models import Source, SourceType, User
from app.modules.scheduler.runner import release_source_lock, try_acquire_source_lock
from app.modules.sync.deadline_engine import CourseDeadlineGroup, ICSDeadlineEngine
from app.modules.sync.ics_client import ICSClient
from app.modules.sources.schemas import SourceCreateRequest
from app.modules.sync.service import SyncRunResult, sync_source


@dataclass(frozen=True)
class SourceDeadlinesPreview:
    source_id: int
    source_name: str | None
    fetched_at_utc: datetime
    total_deadlines: int
    courses: list[CourseDeadlineGroup]


def get_or_create_default_user(db: Session) -> User:
    user = db.scalar(select(User).order_by(User.id.asc()).limit(1))
    if user is not None:
        return user

    user = User(email=None)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_ics_source(db: Session, payload: SourceCreateRequest) -> Source:
    settings = get_settings()
    user = get_or_create_default_user(db)

    source = Source(
        user_id=user.id,
        type=SourceType.ICS,
        name=payload.name,
        encrypted_url=encrypt_secret(str(payload.url)),
        interval_minutes=payload.interval_minutes or settings.default_sync_interval_minutes,
        is_active=True,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def list_sources(db: Session) -> list[Source]:
    return db.scalars(select(Source).order_by(Source.id.asc())).all()


def get_source_by_id(db: Session, source_id: int) -> Source | None:
    return db.get(Source, source_id)


def run_manual_sync(db: Session, source: Source) -> SyncRunResult:
    settings = get_settings()
    lock_acquired = try_acquire_source_lock(db, settings.source_lock_namespace, source.id)
    if not lock_acquired:
        return SyncRunResult(
            source_id=source.id,
            changes_created=0,
            email_sent=False,
            last_error="source_lock_not_acquired",
        )

    try:
        return sync_source(db=db, source=source)
    finally:
        release_source_lock(db, settings.source_lock_namespace, source.id)


def preview_source_deadlines(
    source: Source,
    ics_client: ICSClient | None = None,
    deadline_engine: ICSDeadlineEngine | None = None,
) -> SourceDeadlinesPreview:
    source_url = decrypt_secret(source.encrypted_url)
    client = ics_client or ICSClient()
    engine = deadline_engine or ICSDeadlineEngine()

    fetched = client.fetch(source_url, source_id=source.id)
    courses = engine.parse_and_group(fetched.content)
    total_deadlines = sum(len(course.deadlines) for course in courses)

    return SourceDeadlinesPreview(
        source_id=source.id,
        source_name=source.name,
        fetched_at_utc=fetched.fetched_at_utc,
        total_deadlines=total_deadlines,
        courses=courses,
    )
