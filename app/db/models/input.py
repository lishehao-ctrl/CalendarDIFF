from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SourceKind(str, Enum):
    CALENDAR = "calendar"
    EMAIL = "email"
    TASK = "task"
    EXAM = "exam"
    ANNOUNCEMENT = "announcement"


class IngestTriggerType(str, Enum):
    MANUAL = "manual"
    SCHEDULER = "scheduler"
    WEBHOOK = "webhook"


class SyncRequestStatus(str, Enum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class InputSource(Base):
    __tablename__ = "input_sources"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", "source_key", name="uq_input_sources_user_provider_source_key"),
        Index("ix_input_sources_active_kind", "is_active", "source_kind"),
        Index("ix_input_sources_active_due", "is_active", "next_poll_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source_kind: Mapped[SourceKind] = mapped_column(
        SAEnum(SourceKind, name="source_kind", native_enum=False),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    source_key: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    poll_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=900, server_default="900")
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="input_sources")
    config: Mapped["InputSourceConfig | None"] = relationship(
        "InputSourceConfig",
        back_populates="source",
        uselist=False,
        cascade="all, delete-orphan",
    )
    secrets: Mapped["InputSourceSecret | None"] = relationship(
        "InputSourceSecret",
        back_populates="source",
        uselist=False,
        cascade="all, delete-orphan",
    )
    cursor: Mapped["InputSourceCursor | None"] = relationship(
        "InputSourceCursor",
        back_populates="source",
        uselist=False,
        cascade="all, delete-orphan",
    )
    sync_requests: Mapped[list["SyncRequest"]] = relationship("SyncRequest", back_populates="source", cascade="all, delete-orphan")
    observations: Mapped[list["SourceEventObservation"]] = relationship(
        "SourceEventObservation",
        back_populates="source",
        cascade="all, delete-orphan",
    )
    event_entity_links: Mapped[list["EventEntityLink"]] = relationship(
        "EventEntityLink",
        back_populates="source",
        cascade="all, delete-orphan",
    )
    event_link_candidates: Mapped[list["EventLinkCandidate"]] = relationship(
        "EventLinkCandidate",
        back_populates="source",
        cascade="all, delete-orphan",
    )
    event_link_blocks: Mapped[list["EventLinkBlock"]] = relationship(
        "EventLinkBlock",
        back_populates="source",
        cascade="all, delete-orphan",
    )
    event_link_alerts: Mapped[list["EventLinkAlert"]] = relationship(
        "EventLinkAlert",
        back_populates="source",
        cascade="all, delete-orphan",
    )


class InputSourceConfig(Base):
    __tablename__ = "input_source_configs"

    source_id: Mapped[int] = mapped_column(ForeignKey("input_sources.id", ondelete="CASCADE"), primary_key=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    config_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    source: Mapped[InputSource] = relationship("InputSource", back_populates="config")


class InputSourceSecret(Base):
    __tablename__ = "input_source_secrets"

    source_id: Mapped[int] = mapped_column(ForeignKey("input_sources.id", ondelete="CASCADE"), primary_key=True)
    encrypted_payload: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    source: Mapped[InputSource] = relationship("InputSource", back_populates="secrets")


class InputSourceCursor(Base):
    __tablename__ = "input_source_cursors"

    source_id: Mapped[int] = mapped_column(ForeignKey("input_sources.id", ondelete="CASCADE"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    cursor_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    source: Mapped[InputSource] = relationship("InputSource", back_populates="cursor")


class SyncRequest(Base):
    __tablename__ = "sync_requests"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_sync_requests_request_id"),
        UniqueConstraint("source_id", "idempotency_key", name="uq_sync_requests_source_idempotency"),
        Index("ix_sync_requests_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey("input_sources.id", ondelete="CASCADE"), nullable=False)
    trigger_type: Mapped[IngestTriggerType] = mapped_column(
        SAEnum(IngestTriggerType, name="ingest_trigger_type", native_enum=False),
        nullable=False,
    )
    status: Mapped[SyncRequestStatus] = mapped_column(
        SAEnum(SyncRequestStatus, name="sync_request_status", native_enum=False),
        nullable=False,
        default=SyncRequestStatus.PENDING,
        server_default=SyncRequestStatus.PENDING.value,
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    source: Mapped[InputSource] = relationship("InputSource", back_populates="sync_requests")
    jobs: Mapped[list["IngestJob"]] = relationship(
        "IngestJob",
        back_populates="sync_request",
        cascade="all, delete-orphan",
        primaryjoin="SyncRequest.request_id == foreign(IngestJob.request_id)",
    )
    ingest_result: Mapped["IngestResult | None"] = relationship(
        "IngestResult",
        back_populates="sync_request",
        uselist=False,
        primaryjoin="SyncRequest.request_id == foreign(IngestResult.request_id)",
    )
    apply_log: Mapped["IngestApplyLog | None"] = relationship(
        "IngestApplyLog",
        back_populates="sync_request",
        uselist=False,
        primaryjoin="SyncRequest.request_id == foreign(IngestApplyLog.request_id)",
    )


__all__ = [
    "IngestTriggerType",
    "InputSource",
    "InputSourceConfig",
    "InputSourceCursor",
    "InputSourceSecret",
    "SourceKind",
    "SyncRequest",
    "SyncRequestStatus",
]
