from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
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
    UniqueConstraint,
    func,
    text as sa_text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class InputType(str, Enum):
    ICS = "ics"
    EMAIL = "email"


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


class IngestJobStatus(str, Enum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    DEAD_LETTER = "DEAD_LETTER"


class ConnectorResultStatus(str, Enum):
    NO_CHANGE = "NO_CHANGE"
    CHANGED = "CHANGED"
    FETCH_FAILED = "FETCH_FAILED"
    PARSE_FAILED = "PARSE_FAILED"
    AUTH_FAILED = "AUTH_FAILED"
    RATE_LIMITED = "RATE_LIMITED"

class OutboxStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


class ChangeType(str, Enum):
    CREATED = "created"
    REMOVED = "removed"
    DUE_CHANGED = "due_changed"


class ReviewStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


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
    notify_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    calendar_delay_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=120, server_default="120")
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    inputs: Mapped[list[Input]] = relationship(back_populates="user")
    input_sources: Mapped[list[InputSource]] = relationship(back_populates="user", cascade="all, delete-orphan")
    digest_send_logs: Mapped[list[DigestSendLog]] = relationship(back_populates="user", cascade="all, delete-orphan")
    email_messages: Mapped[list[EmailMessage]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

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

    user: Mapped[User] = relationship(back_populates="inputs")
    events: Mapped[list[Event]] = relationship(back_populates="input", cascade="all, delete-orphan")
    snapshots: Mapped[list[Snapshot]] = relationship(back_populates="input", cascade="all, delete-orphan")
    changes: Mapped[list[Change]] = relationship(back_populates="input", cascade="all, delete-orphan")

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

    input: Mapped[Input] = relationship(back_populates="events")


class Snapshot(Base):
    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    input_id: Mapped[int] = mapped_column(ForeignKey("inputs.id", ondelete="CASCADE"), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_evidence_key: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    input: Mapped[Input] = relationship(back_populates="snapshots")
    snapshot_events: Mapped[list[SnapshotEvent]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan"
    )
    changes_as_before: Mapped[list[Change]] = relationship(
        "Change",
        foreign_keys="Change.before_snapshot_id",
        back_populates="before_snapshot",
    )
    changes_as_after: Mapped[list[Change]] = relationship(
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

    snapshot: Mapped[Snapshot] = relationship(back_populates="snapshot_events")


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

    input: Mapped[Input] = relationship(back_populates="changes")
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
    notifications: Mapped[list[Notification]] = relationship(back_populates="change", cascade="all, delete-orphan")


class EmailMessage(Base):
    __tablename__ = "email_messages"
    __table_args__ = (
        Index("ix_email_messages_user_received_at_desc", "user_id", "received_at"),
    )

    email_id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, default=1, server_default="1")
    from_addr: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    date_rfc822: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    evidence_key: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    user: Mapped[User] = relationship(back_populates="email_messages")
    rule_label: Mapped[EmailRuleLabel | None] = relationship(
        back_populates="email_message",
        uselist=False,
        cascade="all, delete-orphan",
    )
    action_items: Mapped[list[EmailActionItem]] = relationship(
        back_populates="email_message",
        cascade="all, delete-orphan",
    )
    rule_analysis: Mapped[EmailRuleAnalysis | None] = relationship(
        back_populates="email_message",
        uselist=False,
        cascade="all, delete-orphan",
    )
    route: Mapped[EmailRoute | None] = relationship(
        back_populates="email_message",
        uselist=False,
        cascade="all, delete-orphan",
    )


class EmailRuleLabel(Base):
    __tablename__ = "email_rule_labels"
    __table_args__ = (
        CheckConstraint("label IN ('KEEP', 'DROP')", name="ck_email_rule_labels_label"),
        CheckConstraint(
            "event_type IS NULL OR event_type IN ('deadline','exam','schedule_change','assignment','grade','action_required','announcement','other')",
            name="ck_email_rule_labels_event_type",
        ),
        Index("ix_email_rule_labels_event_type", "event_type"),
    )

    email_id: Mapped[str] = mapped_column(
        ForeignKey("email_messages.email_id", ondelete="CASCADE"),
        primary_key=True,
    )
    label: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    course_hints: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    event_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw_extract: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=lambda: {"deadline_text": None, "time_text": None, "location_text": None},
        server_default='{"deadline_text":null,"time_text":null,"location_text":null}',
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    email_message: Mapped[EmailMessage] = relationship(back_populates="rule_label")


class EmailActionItem(Base):
    __tablename__ = "email_action_items"
    __table_args__ = (
        Index("ix_email_action_items_email_id", "email_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email_id: Mapped[str] = mapped_column(ForeignKey("email_messages.email_id", ondelete="CASCADE"), nullable=False)
    action: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_iso: Mapped[str | None] = mapped_column(Text, nullable=True)
    where_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    email_message: Mapped[EmailMessage] = relationship(back_populates="action_items")


class EmailRuleAnalysis(Base):
    __tablename__ = "email_rule_analysis"

    email_id: Mapped[str] = mapped_column(
        ForeignKey("email_messages.email_id", ondelete="CASCADE"),
        primary_key=True,
    )
    event_flags: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    matched_snippets: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    drop_reason_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list, server_default="[]")

    email_message: Mapped[EmailMessage] = relationship(back_populates="rule_analysis")


class EmailRoute(Base):
    __tablename__ = "email_routes"
    __table_args__ = (
        CheckConstraint("route IN ('drop', 'archive', 'review')", name="ck_email_routes_route"),
        Index("ix_email_routes_route_routed_at_desc", "route", "routed_at"),
    )

    email_id: Mapped[str] = mapped_column(
        ForeignKey("email_messages.email_id", ondelete="CASCADE"),
        primary_key=True,
    )
    route: Mapped[str] = mapped_column(String(16), nullable=False)
    routed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    email_message: Mapped[EmailMessage] = relationship(back_populates="route")


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_notifications_idempotency_key"),
        UniqueConstraint("change_id", "channel", name="uq_notifications_change_channel"),
        Index("ix_notifications_status_deliver_after", "status", "deliver_after"),
    )

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
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    deliver_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    enqueue_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    change: Mapped[Change] = relationship(back_populates="notifications")


class DigestSendLog(Base):
    __tablename__ = "digest_send_log"
    __table_args__ = (
        UniqueConstraint("user_id", "scheduled_local_date", "scheduled_local_time", name="uq_digest_send_log_slot"),
        Index("ix_digest_send_log_user_slot", "user_id", "scheduled_local_date", "scheduled_local_time"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    scheduled_local_date: Mapped[date] = mapped_column(Date(), nullable=False)
    scheduled_local_time: Mapped[str] = mapped_column(String(5), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[User] = relationship(back_populates="digest_send_logs")


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

    user: Mapped[User] = relationship(back_populates="input_sources")
    config: Mapped[InputSourceConfig | None] = relationship(
        back_populates="source",
        uselist=False,
        cascade="all, delete-orphan",
    )
    secrets: Mapped[InputSourceSecret | None] = relationship(
        back_populates="source",
        uselist=False,
        cascade="all, delete-orphan",
    )
    cursor: Mapped[InputSourceCursor | None] = relationship(
        back_populates="source",
        uselist=False,
        cascade="all, delete-orphan",
    )
    sync_requests: Mapped[list[SyncRequest]] = relationship(back_populates="source", cascade="all, delete-orphan")
    observations: Mapped[list[SourceEventObservation]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
    )


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

    source: Mapped[InputSource] = relationship(back_populates="observations")


class InputSourceConfig(Base):
    __tablename__ = "input_source_configs"

    source_id: Mapped[int] = mapped_column(ForeignKey("input_sources.id", ondelete="CASCADE"), primary_key=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    config_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    source: Mapped[InputSource] = relationship(back_populates="config")


class InputSourceSecret(Base):
    __tablename__ = "input_source_secrets"

    source_id: Mapped[int] = mapped_column(ForeignKey("input_sources.id", ondelete="CASCADE"), primary_key=True)
    encrypted_payload: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    source: Mapped[InputSource] = relationship(back_populates="secrets")


class InputSourceCursor(Base):
    __tablename__ = "input_source_cursors"

    source_id: Mapped[int] = mapped_column(ForeignKey("input_sources.id", ondelete="CASCADE"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    cursor_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    source: Mapped[InputSource] = relationship(back_populates="cursor")


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

    source: Mapped[InputSource] = relationship(back_populates="sync_requests")
    jobs: Mapped[list[IngestJob]] = relationship(
        back_populates="sync_request",
        cascade="all, delete-orphan",
        primaryjoin="SyncRequest.request_id == foreign(IngestJob.request_id)",
    )
    ingest_result: Mapped[IngestResult | None] = relationship(
        back_populates="sync_request",
        uselist=False,
        primaryjoin="SyncRequest.request_id == foreign(IngestResult.request_id)",
    )
    apply_log: Mapped[IngestApplyLog | None] = relationship(
        back_populates="sync_request",
        uselist=False,
        primaryjoin="SyncRequest.request_id == foreign(IngestApplyLog.request_id)",
    )


class IngestJob(Base):
    __tablename__ = "ingest_jobs"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_ingest_jobs_request_id"),
        Index("ix_ingest_jobs_status_next_retry", "status", "next_retry_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey("input_sources.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[IngestJobStatus] = mapped_column(
        SAEnum(IngestJobStatus, name="ingest_job_status", native_enum=False),
        nullable=False,
        default=IngestJobStatus.PENDING,
        server_default=IngestJobStatus.PENDING.value,
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    claimed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    claim_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dead_lettered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    sync_request: Mapped[SyncRequest] = relationship(
        back_populates="jobs",
        primaryjoin="foreign(IngestJob.request_id) == SyncRequest.request_id",
    )
    source: Mapped[InputSource] = relationship()


class IngestResult(Base):
    __tablename__ = "ingest_results"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_ingest_results_request_id"),
        Index("ix_ingest_results_source_created", "source_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey("input_sources.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[ConnectorResultStatus] = mapped_column(
        SAEnum(ConnectorResultStatus, name="connector_result_status", native_enum=False),
        nullable=False,
    )
    cursor_patch: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    records: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    source: Mapped[InputSource] = relationship()
    sync_request: Mapped[SyncRequest | None] = relationship(
        back_populates="ingest_result",
        uselist=False,
        primaryjoin="foreign(IngestResult.request_id) == SyncRequest.request_id",
    )


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

    sync_request: Mapped[SyncRequest | None] = relationship(
        back_populates="apply_log",
        uselist=False,
        primaryjoin="foreign(IngestApplyLog.request_id) == SyncRequest.request_id",
    )
