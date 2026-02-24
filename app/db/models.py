from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from uuid import uuid4

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
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class InputType(str, Enum):
    ICS = "ics"
    EMAIL = "email"


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


class SyncRunStatus(str, Enum):
    NO_CHANGE = "NO_CHANGE"
    CHANGED = "CHANGED"
    FETCH_FAILED = "FETCH_FAILED"
    PARSE_FAILED = "PARSE_FAILED"
    DIFF_FAILED = "DIFF_FAILED"
    EMAIL_FAILED = "EMAIL_FAILED"
    LOCK_SKIPPED = "LOCK_SKIPPED"


class SyncTriggerType(str, Enum):
    SCHEDULER = "scheduler"
    MANUAL = "manual"


class ReviewCandidateStatus(str, Enum):
    PENDING = "pending"
    APPLIED = "applied"
    DISMISSED = "dismissed"
    FAILED = "failed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notify_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    calendar_delay_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=120, server_default="120")
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    terms: Mapped[list[UserTerm]] = relationship(back_populates="user", cascade="all, delete-orphan")
    inputs: Mapped[list[Input]] = relationship(back_populates="user")
    notification_prefs: Mapped[UserNotificationPrefs | None] = relationship(back_populates="user", uselist=False)
    digest_send_logs: Mapped[list[DigestSendLog]] = relationship(back_populates="user", cascade="all, delete-orphan")
    email_rule_candidates: Mapped[list[EmailRuleCandidate]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class UserTerm(Base):
    __tablename__ = "user_terms"
    __table_args__ = (
        UniqueConstraint("user_id", "code", name="uq_user_terms_user_code"),
        Index("ix_user_terms_user_id", "user_id"),
        Index("ix_user_terms_active_window", "user_id", "is_active", "starts_on", "ends_on"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    starts_on: Mapped[date] = mapped_column(Date(), nullable=False)
    ends_on: Mapped[date] = mapped_column(Date(), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="terms")
    inputs: Mapped[list[Input]] = relationship(back_populates="user_term")
    changes: Mapped[list[Change]] = relationship(back_populates="user_term")
    input_baselines: Mapped[list[InputTermBaseline]] = relationship(
        back_populates="user_term",
        cascade="all, delete-orphan",
    )


class Input(Base):
    __tablename__ = "inputs"
    __table_args__ = (
        Index("ix_inputs_active_last_checked", "is_active", "last_checked_at"),
        Index("ix_inputs_due_lookup", "is_active", "last_checked_at", "interval_minutes"),
        UniqueConstraint("user_id", "type", "identity_key", name="uq_inputs_user_type_identity_key"),
        CheckConstraint("interval_minutes = 15", name="ck_inputs_interval_minutes_fixed_15"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    user_term_id: Mapped[int | None] = mapped_column(ForeignKey("user_terms.id", ondelete="SET NULL"), nullable=True)
    type: Mapped[InputType] = mapped_column(
        SAEnum(InputType, name="input_type", native_enum=False),
        nullable=False,
        default=InputType.ICS,
        server_default=InputType.ICS.value,
    )
    identity_key: Mapped[str] = mapped_column(String(128), nullable=False)
    encrypted_url: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    gmail_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gmail_from_contains: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gmail_subject_keywords: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    gmail_history_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    gmail_account_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    encrypted_access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    etag: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_modified: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notify_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15, server_default="15")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_change_detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="inputs")
    user_term: Mapped[UserTerm | None] = relationship(back_populates="inputs")
    events: Mapped[list[Event]] = relationship(back_populates="input", cascade="all, delete-orphan")
    snapshots: Mapped[list[Snapshot]] = relationship(back_populates="input", cascade="all, delete-orphan")
    changes: Mapped[list[Change]] = relationship(back_populates="input", cascade="all, delete-orphan")
    course_overrides: Mapped[list[CourseOverride]] = relationship(
        back_populates="input", cascade="all, delete-orphan"
    )
    task_overrides: Mapped[list[TaskOverride]] = relationship(back_populates="input", cascade="all, delete-orphan")
    sync_runs: Mapped[list[SyncRun]] = relationship(back_populates="input", cascade="all, delete-orphan")
    term_baselines: Mapped[list[InputTermBaseline]] = relationship(
        back_populates="input",
        cascade="all, delete-orphan",
    )
    email_rule_candidates: Mapped[list[EmailRuleCandidate]] = relationship(
        back_populates="input",
        cascade="all, delete-orphan",
    )

    # Keep constructor backward-compatible while removing persisted name fields.
    def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
        legacy_name = kwargs.pop("name", None)
        kwargs.pop("normalized_name", None)
        identity_key = kwargs.get("identity_key")
        if not isinstance(identity_key, str) or not identity_key.strip():
            kwargs["identity_key"] = f"legacy:{uuid4().hex}"
        super().__init__(**kwargs)
        if isinstance(legacy_name, str) and legacy_name.strip():
            self._legacy_name = legacy_name.strip()

    @property
    def term_scope(self) -> str:
        return "term" if self.user_term_id is not None else "global"

    @property
    def display_label(self) -> str:
        if self.type == InputType.EMAIL:
            account = (self.gmail_account_email or "").strip()
            return f"Gmail · {account}" if account else f"Gmail · input-{self.id}"
        term_label = self.user_term.label if self.user_term is not None else "Unassigned"
        return f"Calendar · {term_label}"

    # Compatibility alias for still-migrating call sites/tests.
    @property
    def name(self) -> str:
        legacy_name = getattr(self, "_legacy_name", None)
        if isinstance(legacy_name, str) and legacy_name.strip():
            return legacy_name
        return self.display_label

    @name.setter
    def name(self, value: str) -> None:
        self._legacy_name = value


class CourseOverride(Base):
    __tablename__ = "course_overrides"
    __table_args__ = (UniqueConstraint("input_id", "original_course_label", name="uq_course_overrides_input_label"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    input_id: Mapped[int] = mapped_column(ForeignKey("inputs.id", ondelete="CASCADE"), nullable=False)
    original_course_label: Mapped[str] = mapped_column(String(64), nullable=False)
    display_course_label: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    input: Mapped[Input] = relationship(back_populates="course_overrides")


class TaskOverride(Base):
    __tablename__ = "task_overrides"
    __table_args__ = (UniqueConstraint("input_id", "event_uid", name="uq_task_overrides_input_uid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    input_id: Mapped[int] = mapped_column(ForeignKey("inputs.id", ondelete="CASCADE"), nullable=False)
    event_uid: Mapped[str] = mapped_column(String(255), nullable=False)
    display_title: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    input: Mapped[Input] = relationship(back_populates="task_overrides")


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
        Index("ix_changes_user_term_id", "user_term_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    input_id: Mapped[int] = mapped_column(ForeignKey("inputs.id", ondelete="CASCADE"), nullable=False)
    user_term_id: Mapped[int | None] = mapped_column(ForeignKey("user_terms.id", ondelete="SET NULL"), nullable=True)
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
    before_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("snapshots.id", ondelete="SET NULL"),
        nullable=True,
    )
    after_snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )
    evidence_keys: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    input: Mapped[Input] = relationship(back_populates="changes")
    user_term: Mapped[UserTerm | None] = relationship(back_populates="changes")
    before_snapshot: Mapped[Snapshot | None] = relationship(
        "Snapshot",
        foreign_keys=[before_snapshot_id],
        back_populates="changes_as_before",
    )
    after_snapshot: Mapped[Snapshot] = relationship(
        "Snapshot",
        foreign_keys=[after_snapshot_id],
        back_populates="changes_as_after",
    )
    notifications: Mapped[list[Notification]] = relationship(back_populates="change", cascade="all, delete-orphan")
    source_email_rule_candidates: Mapped[list[EmailRuleCandidate]] = relationship(
        "EmailRuleCandidate",
        foreign_keys="EmailRuleCandidate.source_change_id",
        back_populates="source_change",
    )
    applied_email_rule_candidates: Mapped[list[EmailRuleCandidate]] = relationship(
        "EmailRuleCandidate",
        foreign_keys="EmailRuleCandidate.applied_change_id",
        back_populates="applied_change",
    )


class EmailRuleCandidate(Base):
    __tablename__ = "email_rule_candidates"
    __table_args__ = (
        UniqueConstraint(
            "input_id",
            "gmail_message_id",
            "rule_version",
            name="uq_email_rule_candidates_input_message_rule",
        ),
        Index("ix_email_rule_candidates_user_status_created", "user_id", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    input_id: Mapped[int] = mapped_column(ForeignKey("inputs.id", ondelete="CASCADE"), nullable=False)
    gmail_message_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_change_id: Mapped[int | None] = mapped_column(ForeignKey("changes.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[ReviewCandidateStatus] = mapped_column(
        SAEnum(
            ReviewCandidateStatus,
            name="review_candidate_status",
            native_enum=False,
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        nullable=False,
        default=ReviewCandidateStatus.PENDING,
        server_default=ReviewCandidateStatus.PENDING.value,
    )
    rule_version: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    proposed_event_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    proposed_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    proposed_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    proposed_course_hint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    raw_extract: Mapped[dict] = mapped_column(JSON, nullable=False)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    from_header: Mapped[str | None] = mapped_column(Text, nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    applied_change_id: Mapped[int | None] = mapped_column(ForeignKey("changes.id", ondelete="SET NULL"), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="email_rule_candidates")
    input: Mapped[Input] = relationship(back_populates="email_rule_candidates")
    source_change: Mapped[Change | None] = relationship(
        "Change",
        foreign_keys=[source_change_id],
        back_populates="source_email_rule_candidates",
    )
    applied_change: Mapped[Change | None] = relationship(
        "Change",
        foreign_keys=[applied_change_id],
        back_populates="applied_email_rule_candidates",
    )


class InputTermBaseline(Base):
    __tablename__ = "input_term_baselines"
    __table_args__ = (
        UniqueConstraint("input_id", "user_term_id", name="uq_input_term_baselines_input_term"),
        Index("ix_input_term_baselines_input_term", "input_id", "user_term_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    input_id: Mapped[int] = mapped_column(ForeignKey("inputs.id", ondelete="CASCADE"), nullable=False)
    user_term_id: Mapped[int] = mapped_column(ForeignKey("user_terms.id", ondelete="CASCADE"), nullable=False)
    first_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("snapshots.id", ondelete="SET NULL"),
        nullable=True,
    )
    established_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="auto_silent", server_default="auto_silent")

    input: Mapped[Input] = relationship(back_populates="term_baselines")
    user_term: Mapped[UserTerm] = relationship(back_populates="input_baselines")
    first_snapshot: Mapped[Snapshot | None] = relationship("Snapshot")


class SyncRun(Base):
    __tablename__ = "sync_runs"
    __table_args__ = (
        Index("ix_sync_runs_input_started_desc", "input_id", "started_at"),
        Index("ix_sync_runs_started_at", "started_at"),
        Index("ix_sync_runs_status_started_at", "status", "started_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    input_id: Mapped[int] = mapped_column(ForeignKey("inputs.id", ondelete="CASCADE"), nullable=False)
    trigger_type: Mapped[SyncTriggerType] = mapped_column(
        SAEnum(SyncTriggerType, name="sync_trigger_type", native_enum=False),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[SyncRunStatus] = mapped_column(
        SAEnum(SyncRunStatus, name="sync_run_status", native_enum=False),
        nullable=False,
    )
    changes_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    lock_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    input: Mapped[Input] = relationship(back_populates="sync_runs")


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


class UserNotificationPrefs(Base):
    __tablename__ = "user_notification_prefs"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    digest_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    timezone: Mapped[str] = mapped_column(String(128), nullable=False, default="America/Los_Angeles", server_default="America/Los_Angeles")
    digest_times: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list, server_default='["09:00"]')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="notification_prefs")


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


# Temporary code-level aliases during source->input migration.
# Public API contracts already use input/input_id naming.
Source = Input
SourceType = InputType
