from __future__ import annotations

from datetime import date, datetime, time
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.input import SourceKind

if TYPE_CHECKING:
    from app.db.models.input import InputSource, SyncRequest
    from app.db.models.notify import Notification
    from app.db.models.shared import User


class ChangeType(str, Enum):
    CREATED = "created"
    REMOVED = "removed"
    DUE_CHANGED = "due_changed"


class ChangeOrigin(str, Enum):
    INGEST_PROPOSAL = "ingest_proposal"
    MANUAL_CANONICAL_EDIT = "manual_canonical_edit"


class ReviewStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class EventEntityLifecycle(str, Enum):
    ACTIVE = "active"
    REMOVED = "removed"


class EventLinkOrigin(str, Enum):
    AUTO = "auto"
    MANUAL_CANDIDATE = "manual_candidate"


class EventLinkCandidateStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class EventLinkCandidateReason(str, Enum):
    SCORE_BAND = "score_band"
    NO_TIME_ANCHOR = "no_time_anchor"
    LOW_CONFIDENCE = "low_confidence"


class EventEntity(Base):
    __tablename__ = "event_entities"
    __table_args__ = (
        UniqueConstraint("user_id", "entity_uid", name="uq_event_entities_user_entity_uid"),
        Index("ix_event_entities_user_updated", "user_id", "updated_at"),
        Index("ix_event_entities_user_semantic_tuple", "user_id", "course_dept", "course_number", "family_id", "ordinal"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    entity_uid: Mapped[str] = mapped_column(String(128), nullable=False)
    lifecycle: Mapped[EventEntityLifecycle] = mapped_column(
        SAEnum(EventEntityLifecycle, name="event_entity_lifecycle", native_enum=False),
        nullable=False,
        default=EventEntityLifecycle.ACTIVE,
        server_default=EventEntityLifecycle.ACTIVE.value,
    )
    course_dept: Mapped[str | None] = mapped_column(String(16), nullable=True)
    course_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    course_suffix: Mapped[str | None] = mapped_column(String(8), nullable=True)
    course_quarter: Mapped[str | None] = mapped_column(String(4), nullable=True)
    course_year2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    family_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Deprecated audit snapshot only: do not use as default display authority.
    family_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    event_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ordinal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_time: Mapped[time | None] = mapped_column(Time(timezone=False), nullable=True)
    time_precision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="event_entities")


class EventEntityLink(Base):
    __tablename__ = "event_entity_links"
    __table_args__ = (
        UniqueConstraint("user_id", "source_id", "external_event_id", name="uq_event_entity_links_user_source_external"),
        Index("ix_event_entity_links_user_entity", "user_id", "entity_uid"),
        Index("ix_event_entity_links_source_external", "source_id", "external_event_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    entity_uid: Mapped[str] = mapped_column(String(128), nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey("input_sources.id", ondelete="CASCADE"), nullable=False)
    source_kind: Mapped[SourceKind] = mapped_column(
        SAEnum(SourceKind, name="source_kind", native_enum=False),
        nullable=False,
    )
    external_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    link_origin: Mapped[EventLinkOrigin] = mapped_column(
        SAEnum(EventLinkOrigin, name="event_link_origin", native_enum=False),
        nullable=False,
        default=EventLinkOrigin.AUTO,
        server_default=EventLinkOrigin.AUTO.value,
    )
    link_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    signals_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="event_entity_links")
    source: Mapped["InputSource"] = relationship("InputSource", back_populates="event_entity_links")


class EventLinkCandidate(Base):
    __tablename__ = "event_link_candidates"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "source_id",
            "external_event_id",
            "proposed_entity_uid",
            "status",
            name="uq_event_link_candidates_user_pair_entity_status",
        ),
        Index("ix_event_link_candidates_user_status_created", "user_id", "status", "created_at"),
        Index("ix_event_link_candidates_source_external", "source_id", "external_event_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey("input_sources.id", ondelete="CASCADE"), nullable=False)
    external_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    proposed_entity_uid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_breakdown_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    reason_code: Mapped[EventLinkCandidateReason] = mapped_column(
        SAEnum(EventLinkCandidateReason, name="event_link_candidate_reason", native_enum=False),
        nullable=False,
    )
    status: Mapped[EventLinkCandidateStatus] = mapped_column(
        SAEnum(EventLinkCandidateStatus, name="event_link_candidate_status", native_enum=False),
        nullable=False,
        default=EventLinkCandidateStatus.PENDING,
        server_default=EventLinkCandidateStatus.PENDING.value,
    )
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="event_link_candidates", foreign_keys=[user_id])
    source: Mapped["InputSource"] = relationship("InputSource", back_populates="event_link_candidates")


class EventLinkBlock(Base):
    __tablename__ = "event_link_blocks"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "source_id",
            "external_event_id",
            "blocked_entity_uid",
            name="uq_event_link_blocks_user_source_external_entity",
        ),
        Index("ix_event_link_blocks_source_external", "source_id", "external_event_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey("input_sources.id", ondelete="CASCADE"), nullable=False)
    external_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    blocked_entity_uid: Mapped[str] = mapped_column(String(128), nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="event_link_blocks", foreign_keys=[user_id])
    source: Mapped["InputSource"] = relationship("InputSource", back_populates="event_link_blocks")


class Change(Base):
    __tablename__ = "changes"
    __table_args__ = (
        Index("ix_changes_user_detected_desc", "user_id", "detected_at"),
        Index("ix_changes_user_review_status_detected", "user_id", "review_status", "detected_at"),
        Index("ix_changes_user_entity_status_detected", "user_id", "entity_uid", "review_status", "detected_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    entity_uid: Mapped[str] = mapped_column(String(255), nullable=False)
    change_origin: Mapped[ChangeOrigin] = mapped_column(
        SAEnum(ChangeOrigin, name="change_origin", native_enum=False),
        nullable=False,
        default=ChangeOrigin.INGEST_PROPOSAL,
        server_default=ChangeOrigin.INGEST_PROPOSAL.value,
    )
    change_type: Mapped[ChangeType] = mapped_column(
        SAEnum(ChangeType, name="change_type", native_enum=False),
        nullable=False,
    )
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    before_semantic_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_semantic_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    delta_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    before_evidence_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_evidence_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    viewed_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_status: Mapped[ReviewStatus] = mapped_column(
        SAEnum(ReviewStatus, name="review_status", native_enum=False),
        nullable=False,
        default=ReviewStatus.PENDING,
        server_default=ReviewStatus.PENDING.value,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    user: Mapped["User"] = relationship("User", back_populates="changes", foreign_keys=[user_id])
    notifications: Mapped[list["Notification"]] = relationship("Notification", back_populates="change", cascade="all, delete-orphan")
    source_refs: Mapped[list["ChangeSourceRef"]] = relationship(
        "ChangeSourceRef",
        back_populates="change",
        cascade="all, delete-orphan",
        order_by="ChangeSourceRef.position",
    )


class ChangeSourceRef(Base):
    __tablename__ = "change_source_refs"
    __table_args__ = (
        UniqueConstraint("change_id", "position", name="uq_change_source_refs_change_position"),
        Index("ix_change_source_refs_change_id", "change_id"),
        Index("ix_change_source_refs_source_id", "source_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    change_id: Mapped[int] = mapped_column(ForeignKey("changes.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey("input_sources.id", ondelete="CASCADE"), nullable=False)
    source_kind: Mapped[SourceKind | None] = mapped_column(
        SAEnum(SourceKind, name="source_kind", native_enum=False),
        nullable=True,
    )
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    external_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    change: Mapped["Change"] = relationship("Change", back_populates="source_refs")


class SourceEventObservation(Base):
    __tablename__ = "source_event_observations"
    __table_args__ = (
        UniqueConstraint("source_id", "external_event_id", name="uq_source_event_observations_source_external"),
        Index("ix_source_event_observations_user_entity_active", "user_id", "entity_uid", "is_active"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey("input_sources.id", ondelete="CASCADE"), nullable=False)
    source_kind: Mapped[SourceKind] = mapped_column(
        SAEnum(SourceKind, name="source_kind", native_enum=False),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    external_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_uid: Mapped[str] = mapped_column(String(128), nullable=False)
    event_payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    last_request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    source: Mapped["InputSource"] = relationship("InputSource", back_populates="observations")


class IngestApplyLog(Base):
    __tablename__ = "ingest_apply_log"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_ingest_apply_log_request_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="applied", server_default="applied")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    sync_request: Mapped["SyncRequest | None"] = relationship(
        "SyncRequest",
        back_populates="apply_log",
        uselist=False,
        primaryjoin="foreign(IngestApplyLog.request_id) == SyncRequest.request_id",
    )


__all__ = [
    "Change",
    "ChangeOrigin",
    "ChangeSourceRef",
    "ChangeType",
    "EventEntity",
    "EventEntityLifecycle",
    "EventEntityLink",
    "EventLinkBlock",
    "EventLinkCandidate",
    "EventLinkCandidateReason",
    "EventLinkCandidateStatus",
    "EventLinkOrigin",
    "IngestApplyLog",
    "ReviewStatus",
    "SourceEventObservation",
]
