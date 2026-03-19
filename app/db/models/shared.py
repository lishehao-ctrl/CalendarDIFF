from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, Enum as SAEnum, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.input import InputSource
    from app.db.models.notify import DigestSendLog
    from app.db.models.review import Change, EventEntity


class OutboxStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


class CourseRawTypeSuggestionStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DISMISSED = "dismissed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notify_email: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    timezone_name: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC", server_default="UTC")
    timezone_source: Mapped[str] = mapped_column(String(16), nullable=False, default="auto", server_default="auto")
    calendar_delay_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=120, server_default="120")
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    gmail_onboarding_skipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    work_item_mappings_state: Mapped[str] = mapped_column(String(32), nullable=False, default="idle", server_default="idle")
    work_item_mappings_last_rebuilt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    work_item_mappings_last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    course_work_item_families: Mapped[list["CourseWorkItemLabelFamily"]] = relationship(
        "CourseWorkItemLabelFamily", back_populates="user", cascade="all, delete-orphan"
    )
    input_sources: Mapped[list["InputSource"]] = relationship("InputSource", back_populates="user", cascade="all, delete-orphan")
    changes: Mapped[list["Change"]] = relationship(
        "Change",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="Change.user_id",
    )
    event_entities: Mapped[list["EventEntity"]] = relationship("EventEntity", back_populates="user", cascade="all, delete-orphan")
    digest_send_logs: Mapped[list["DigestSendLog"]] = relationship("DigestSendLog", back_populates="user", cascade="all, delete-orphan")
    sessions: Mapped[list["UserSession"]] = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")


class CourseWorkItemLabelFamily(Base):
    __tablename__ = "course_work_item_label_families"
    __table_args__ = (
        UniqueConstraint("user_id", "normalized_course_identity", "normalized_canonical_label", name="uq_course_work_item_families_user_course_label"),
        Index("ix_course_work_item_families_user_course_updated", "user_id", "normalized_course_identity", "updated_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    course_dept: Mapped[str] = mapped_column(String(16), nullable=False)
    course_number: Mapped[int] = mapped_column(Integer, nullable=False)
    course_suffix: Mapped[str | None] = mapped_column(String(8), nullable=True)
    course_quarter: Mapped[str | None] = mapped_column(String(4), nullable=True)
    course_year2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    normalized_course_identity: Mapped[str] = mapped_column(String(128), nullable=False)
    canonical_label: Mapped[str] = mapped_column(String(128), nullable=False)
    normalized_canonical_label: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship("User", back_populates="course_work_item_families")
    raw_types: Mapped[list["CourseWorkItemRawType"]] = relationship(
        "CourseWorkItemRawType",
        back_populates="family",
        cascade="all, delete-orphan",
        foreign_keys="CourseWorkItemRawType.family_id",
    )


class CourseWorkItemRawType(Base):
    __tablename__ = "course_work_item_raw_types"
    __table_args__ = (
        UniqueConstraint("family_id", "normalized_raw_type", name="uq_course_work_item_raw_types_family_raw_type"),
        Index("ix_course_work_item_raw_types_family", "family_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("course_work_item_label_families.id", ondelete="CASCADE"), nullable=False)
    raw_type: Mapped[str] = mapped_column(String(128), nullable=False)
    normalized_raw_type: Mapped[str] = mapped_column(String(128), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    family: Mapped[CourseWorkItemLabelFamily] = relationship("CourseWorkItemLabelFamily", back_populates="raw_types")
    source_suggestions: Mapped[list["CourseRawTypeSuggestion"]] = relationship(
        "CourseRawTypeSuggestion",
        back_populates="source_raw_type",
        foreign_keys="CourseRawTypeSuggestion.source_raw_type_id",
    )
    suggested_for: Mapped[list["CourseRawTypeSuggestion"]] = relationship(
        "CourseRawTypeSuggestion",
        back_populates="suggested_raw_type",
        foreign_keys="CourseRawTypeSuggestion.suggested_raw_type_id",
    )


class CourseRawTypeSuggestion(Base):
    __tablename__ = "course_raw_type_suggestions"
    __table_args__ = (
        Index("ix_course_raw_type_suggestions_status", "status", "created_at"),
        Index("ix_course_raw_type_suggestions_source_raw_type", "source_raw_type_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_raw_type_id: Mapped[int] = mapped_column(ForeignKey("course_work_item_raw_types.id", ondelete="CASCADE"), nullable=False)
    suggested_raw_type_id: Mapped[int | None] = mapped_column(ForeignKey("course_work_item_raw_types.id", ondelete="CASCADE"), nullable=True)
    source_observation_id: Mapped[int | None] = mapped_column(ForeignKey("source_event_observations.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[CourseRawTypeSuggestionStatus] = mapped_column(
        SAEnum(CourseRawTypeSuggestionStatus, name="course_raw_type_suggestion_status", native_enum=False),
        nullable=False,
        default=CourseRawTypeSuggestionStatus.PENDING,
        server_default=CourseRawTypeSuggestionStatus.PENDING.value,
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    evidence: Mapped[str | None] = mapped_column(String(255), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    source_raw_type: Mapped[CourseWorkItemRawType] = relationship(
        "CourseWorkItemRawType",
        back_populates="source_suggestions",
        foreign_keys=[source_raw_type_id],
    )
    suggested_raw_type: Mapped[CourseWorkItemRawType | None] = relationship(
        "CourseWorkItemRawType",
        back_populates="suggested_for",
        foreign_keys=[suggested_raw_type_id],
    )


class UserSession(Base):
    __tablename__ = "user_sessions"
    __table_args__ = (
        UniqueConstraint("session_id", name="uq_user_sessions_session_id"),
        Index("ix_user_sessions_user_expires", "user_id", "expires_at"),
        Index("ix_user_sessions_expires", "expires_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user: Mapped[User] = relationship("User", back_populates="sessions")


class IntegrationOutbox(Base):
    __tablename__ = "integration_outbox"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_integration_outbox_event_id"),
        Index("ix_integration_outbox_status_available", "status", "available_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    status: Mapped[OutboxStatus] = mapped_column(
        SAEnum(OutboxStatus, name="outbox_status", native_enum=False),
        nullable=False,
        default=OutboxStatus.PENDING,
        server_default=OutboxStatus.PENDING.value,
    )
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IntegrationInbox(Base):
    __tablename__ = "integration_inbox"
    __table_args__ = (
        UniqueConstraint("consumer_name", "event_id", name="uq_integration_inbox_consumer_event"),
        Index("ix_integration_inbox_processed", "processed_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    consumer_name: Mapped[str] = mapped_column(String(128), nullable=False)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


__all__ = [
    "CourseRawTypeSuggestion",
    "CourseRawTypeSuggestionStatus",
    "CourseWorkItemLabelFamily",
    "CourseWorkItemRawType",
    "IntegrationInbox",
    "IntegrationOutbox",
    "OutboxStatus",
    "User",
    "UserSession",
]
