from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, Enum as SAEnum, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.input import InputSource
    from app.db.models.notify import DigestSendLog
    from app.db.models.review import Input
    from app.db.models.review import EventEntity, EventEntityLink, EventLinkAlert, EventLinkBlock, EventLinkCandidate


class OutboxStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notify_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timezone_name: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC", server_default="UTC")
    calendar_delay_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=120, server_default="120")
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    inputs: Mapped[list["Input"]] = relationship("Input", back_populates="user")
    input_sources: Mapped[list["InputSource"]] = relationship("InputSource", back_populates="user", cascade="all, delete-orphan")
    event_entities: Mapped[list["EventEntity"]] = relationship("EventEntity", back_populates="user", cascade="all, delete-orphan")
    event_entity_links: Mapped[list["EventEntityLink"]] = relationship("EventEntityLink", back_populates="user", cascade="all, delete-orphan")
    event_link_candidates: Mapped[list["EventLinkCandidate"]] = relationship(
        "EventLinkCandidate",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="EventLinkCandidate.user_id",
    )
    event_link_blocks: Mapped[list["EventLinkBlock"]] = relationship(
        "EventLinkBlock",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="EventLinkBlock.user_id",
    )
    event_link_alerts: Mapped[list["EventLinkAlert"]] = relationship(
        "EventLinkAlert",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="EventLinkAlert.user_id",
    )
    digest_send_logs: Mapped[list["DigestSendLog"]] = relationship("DigestSendLog", back_populates="user", cascade="all, delete-orphan")


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
    "IntegrationInbox",
    "IntegrationOutbox",
    "OutboxStatus",
    "User",
]
