from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

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
from app.db.models.input import SourceKind

if TYPE_CHECKING:
    from app.db.models.input import InputSource, SyncRequest
    from app.db.models.shared import User


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

    sync_request: Mapped["SyncRequest"] = relationship(
        "SyncRequest",
        back_populates="jobs",
        primaryjoin="foreign(IngestJob.request_id) == SyncRequest.request_id",
    )
    source: Mapped["InputSource"] = relationship("InputSource")


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

    source: Mapped["InputSource"] = relationship("InputSource")
    sync_request: Mapped["SyncRequest | None"] = relationship(
        "SyncRequest",
        back_populates="ingest_result",
        uselist=False,
        primaryjoin="foreign(IngestResult.request_id) == SyncRequest.request_id",
    )


class IngestUnresolvedRecord(Base):
    __tablename__ = "ingest_unresolved_records"
    __table_args__ = (
        Index(
            "ix_ingest_unresolved_records_user_source_external_active",
            "user_id",
            "source_id",
            "external_event_id",
            "is_active",
        ),
        Index(
            "ix_ingest_unresolved_records_active_created",
            "is_active",
            "created_at",
        ),
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
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    source_facts_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    semantic_event_draft_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    kind_resolution_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    source: Mapped["InputSource"] = relationship("InputSource")
    user: Mapped["User"] = relationship("User")


__all__ = [
    "ConnectorResultStatus",
    "IngestJob",
    "IngestJobStatus",
    "IngestResult",
    "IngestUnresolvedRecord",
]
