from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SourceType(str, Enum):
    ICS = "ics"


class ChangeType(str, Enum):
    CREATED = "created"
    REMOVED = "removed"
    DUE_CHANGED = "due_changed"
    TITLE_CHANGED = "title_changed"
    COURSE_CHANGED = "course_changed"


class NotificationChannel(str, Enum):
    EMAIL = "email"


class NotificationStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    sources: Mapped[list[Source]] = relationship(back_populates="user")


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (
        Index("ix_sources_active_last_checked", "is_active", "last_checked_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[SourceType] = mapped_column(
        SAEnum(SourceType, name="source_type", native_enum=False),
        nullable=False,
        default=SourceType.ICS,
        server_default=SourceType.ICS.value,
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    encrypted_url: Mapped[str] = mapped_column(Text, nullable=False)
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15, server_default="15")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="sources")
    events: Mapped[list[Event]] = relationship(back_populates="source", cascade="all, delete-orphan")
    snapshots: Mapped[list[Snapshot]] = relationship(back_populates="source", cascade="all, delete-orphan")
    changes: Mapped[list[Change]] = relationship(back_populates="source", cascade="all, delete-orphan")


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("source_id", "uid", name="uq_events_source_id_uid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), nullable=False)
    uid: Mapped[str] = mapped_column(String(255), nullable=False)
    course_label: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    start_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    source: Mapped[Source] = relationship(back_populates="events")


class Snapshot(Base):
    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False)

    source: Mapped[Source] = relationship(back_populates="snapshots")
    snapshot_events: Mapped[list[SnapshotEvent]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan"
    )


class SnapshotEvent(Base):
    __tablename__ = "snapshot_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id", ondelete="CASCADE"), nullable=False)
    uid: Mapped[str] = mapped_column(String(255), nullable=False)
    course_label: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    start_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    snapshot: Mapped[Snapshot] = relationship(back_populates="snapshot_events")


class Change(Base):
    __tablename__ = "changes"
    __table_args__ = (Index("ix_changes_source_detected_desc", "source_id", "detected_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), nullable=False)
    event_uid: Mapped[str] = mapped_column(String(255), nullable=False)
    change_type: Mapped[ChangeType] = mapped_column(
        SAEnum(ChangeType, name="change_type", native_enum=False),
        nullable=False,
    )
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    before_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    delta_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    source: Mapped[Source] = relationship(back_populates="changes")
    notifications: Mapped[list[Notification]] = relationship(back_populates="change", cascade="all, delete-orphan")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("changes.id", ondelete="CASCADE"), nullable=False)
    channel: Mapped[NotificationChannel] = mapped_column(
        SAEnum(NotificationChannel, name="notification_channel", native_enum=False),
        nullable=False,
        default=NotificationChannel.EMAIL,
        server_default=NotificationChannel.EMAIL.value,
    )
    status: Mapped[NotificationStatus] = mapped_column(
        SAEnum(NotificationStatus, name="notification_status", native_enum=False),
        nullable=False,
        default=NotificationStatus.PENDING,
        server_default=NotificationStatus.PENDING.value,
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    change: Mapped[Change] = relationship(back_populates="notifications")
