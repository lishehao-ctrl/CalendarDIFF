from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum as SAEnum,
    Float,
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
from app.db.models.input import SourceKind

if TYPE_CHECKING:
    from app.db.models.input import InputSource, SyncRequest
    from app.db.models.notify import Notification
    from app.db.models.shared import User


class InputType(str, Enum):
    ICS = "ics"
    EMAIL = "email"


class ChangeType(str, Enum):
    CREATED = "created"
    REMOVED = "removed"
    DUE_CHANGED = "due_changed"


class ReviewStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


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


class EventLinkAlertRiskLevel(str, Enum):
    MEDIUM = "medium"


class EventLinkAlertReason(str, Enum):
    AUTO_LINK_WITHOUT_CANONICAL_CHANGE = "auto_link_without_canonical_change"


class EventLinkAlertStatus(str, Enum):
    PENDING = "pending"
    DISMISSED = "dismissed"
    MARKED_SAFE = "marked_safe"
    RESOLVED = "resolved"


class EventLinkAlertResolution(str, Enum):
    DISMISSED_BY_USER = "dismissed_by_user"
    MARKED_SAFE_BY_USER = "marked_safe_by_user"
    CANONICAL_PENDING_CREATED = "canonical_pending_created"
    CANDIDATE_OPENED = "candidate_opened"
    LINK_REMOVED = "link_removed"
    LINK_RELINKED = "link_relinked"


class Input(Base):
    __tablename__ = "inputs"
    __table_args__ = (
        UniqueConstraint("user_id", "type", "identity_key", name="uq_inputs_user_type_identity_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[InputType] = mapped_column(
        SAEnum(InputType, name="input_type", native_enum=False),
        nullable=False,
        default=InputType.ICS,
        server_default=InputType.ICS.value,
    )
    identity_key: Mapped[str] = mapped_column(String(128), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="inputs")
    events: Mapped[list["Event"]] = relationship("Event", back_populates="input", cascade="all, delete-orphan")
    snapshots: Mapped[list["Snapshot"]] = relationship("Snapshot", back_populates="input", cascade="all, delete-orphan")
    changes: Mapped[list["Change"]] = relationship("Change", back_populates="input", cascade="all, delete-orphan")

    @property
    def display_label(self) -> str:
        if self.type == InputType.EMAIL:
            return f"Gmail · input-{self.id}"
        return "Calendar · Primary"


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("input_id", "uid", name="uq_events_input_id_uid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    input_id: Mapped[int] = mapped_column(ForeignKey("inputs.id", ondelete="CASCADE"), nullable=False)
    uid: Mapped[str] = mapped_column(String(255), nullable=False)
    course_label: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    start_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    input: Mapped[Input] = relationship("Input", back_populates="events")


class EventEntity(Base):
    __tablename__ = "event_entities"
    __table_args__ = (
        UniqueConstraint("user_id", "entity_uid", name="uq_event_entities_user_entity_uid"),
        Index("ix_event_entities_user_updated", "user_id", "updated_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    entity_uid: Mapped[str] = mapped_column(String(128), nullable=False)
    course_best_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    course_best_strength: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    course_aliases_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    title_aliases_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
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


class EventLinkAlert(Base):
    __tablename__ = "event_link_alerts"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "source_id",
            "external_event_id",
            "entity_uid",
            name="uq_event_link_alerts_user_source_external_entity",
        ),
        Index("ix_event_link_alerts_user_status_created", "user_id", "status", "created_at"),
        Index("ix_event_link_alerts_source_external", "source_id", "external_event_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey("input_sources.id", ondelete="CASCADE"), nullable=False)
    external_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_uid: Mapped[str] = mapped_column(String(128), nullable=False)
    link_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    risk_level: Mapped[EventLinkAlertRiskLevel] = mapped_column(
        SAEnum(EventLinkAlertRiskLevel, name="event_link_alert_risk_level", native_enum=False),
        nullable=False,
        default=EventLinkAlertRiskLevel.MEDIUM,
        server_default=EventLinkAlertRiskLevel.MEDIUM.value,
    )
    reason_code: Mapped[EventLinkAlertReason] = mapped_column(
        SAEnum(EventLinkAlertReason, name="event_link_alert_reason", native_enum=False),
        nullable=False,
        default=EventLinkAlertReason.AUTO_LINK_WITHOUT_CANONICAL_CHANGE,
        server_default=EventLinkAlertReason.AUTO_LINK_WITHOUT_CANONICAL_CHANGE.value,
    )
    status: Mapped[EventLinkAlertStatus] = mapped_column(
        SAEnum(EventLinkAlertStatus, name="event_link_alert_status", native_enum=False),
        nullable=False,
        default=EventLinkAlertStatus.PENDING,
        server_default=EventLinkAlertStatus.PENDING.value,
    )
    resolution_code: Mapped[EventLinkAlertResolution | None] = mapped_column(
        SAEnum(EventLinkAlertResolution, name="event_link_alert_resolution", native_enum=False),
        nullable=True,
    )
    evidence_snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="event_link_alerts", foreign_keys=[user_id])
    source: Mapped["InputSource"] = relationship("InputSource", back_populates="event_link_alerts")


class Snapshot(Base):
    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    input_id: Mapped[int] = mapped_column(ForeignKey("inputs.id", ondelete="CASCADE"), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_evidence_key: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    input: Mapped[Input] = relationship("Input", back_populates="snapshots")
    snapshot_events: Mapped[list["SnapshotEvent"]] = relationship(
        "SnapshotEvent", back_populates="snapshot", cascade="all, delete-orphan"
    )
    changes_as_before: Mapped[list["Change"]] = relationship(
        "Change",
        foreign_keys="Change.before_snapshot_id",
        back_populates="before_snapshot",
    )
    changes_as_after: Mapped[list["Change"]] = relationship(
        "Change",
        foreign_keys="Change.after_snapshot_id",
        back_populates="after_snapshot",
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

    snapshot: Mapped[Snapshot] = relationship("Snapshot", back_populates="snapshot_events")


class Change(Base):
    __tablename__ = "changes"
    __table_args__ = (
        Index("ix_changes_input_detected_desc", "input_id", "detected_at"),
        Index("ix_changes_review_status_detected_at", "review_status", "detected_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    input_id: Mapped[int] = mapped_column(ForeignKey("inputs.id", ondelete="CASCADE"), nullable=False)
    event_uid: Mapped[str] = mapped_column(String(255), nullable=False)
    change_type: Mapped[ChangeType] = mapped_column(
        SAEnum(ChangeType, name="change_type", native_enum=False),
        nullable=False,
    )
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    before_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    delta_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    viewed_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_status: Mapped[ReviewStatus] = mapped_column(
        SAEnum(ReviewStatus, name="review_status", native_enum=False),
        nullable=False,
        default=ReviewStatus.APPROVED,
        server_default=ReviewStatus.APPROVED.value,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    proposal_merge_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    proposal_sources_json: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    before_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("snapshots.id", ondelete="SET NULL"),
        nullable=True,
    )
    after_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("snapshots.id", ondelete="CASCADE"),
        nullable=True,
    )
    evidence_keys: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    input: Mapped[Input] = relationship("Input", back_populates="changes")
    before_snapshot: Mapped[Snapshot | None] = relationship(
        "Snapshot",
        foreign_keys=[before_snapshot_id],
        back_populates="changes_as_before",
    )
    after_snapshot: Mapped[Snapshot | None] = relationship(
        "Snapshot",
        foreign_keys=[after_snapshot_id],
        back_populates="changes_as_after",
    )
    notifications: Mapped[list["Notification"]] = relationship("Notification", back_populates="change", cascade="all, delete-orphan")


class SourceEventObservation(Base):
    __tablename__ = "source_event_observations"
    __table_args__ = (
        UniqueConstraint("source_id", "external_event_id", name="uq_source_event_observations_source_external"),
        Index("ix_source_event_observations_user_merge_active", "user_id", "merge_key", "is_active"),
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
    merge_key: Mapped[str] = mapped_column(String(128), nullable=False)
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
    "ChangeType",
    "Event",
    "EventEntity",
    "EventEntityLink",
    "EventLinkAlert",
    "EventLinkAlertReason",
    "EventLinkAlertResolution",
    "EventLinkAlertRiskLevel",
    "EventLinkAlertStatus",
    "EventLinkBlock",
    "EventLinkCandidate",
    "EventLinkCandidateReason",
    "EventLinkCandidateStatus",
    "EventLinkOrigin",
    "IngestApplyLog",
    "Input",
    "InputType",
    "ReviewStatus",
    "Snapshot",
    "SnapshotEvent",
    "SourceEventObservation",
]
