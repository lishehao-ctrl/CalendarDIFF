from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, Enum as SAEnum, Float, ForeignKey, Index, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.shared import User


class AgentProposalType(str, Enum):
    CHANGE_DECISION = "change_decision"
    SOURCE_RECOVERY = "source_recovery"
    FAMILY_RELINK_PREVIEW = "family_relink_preview"


class AgentProposalStatus(str, Enum):
    OPEN = "open"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


class ApprovalTicketStatus(str, Enum):
    OPEN = "open"
    EXECUTED = "executed"
    CANCELED = "canceled"
    EXPIRED = "expired"
    FAILED = "failed"


class AgentProposal(Base):
    __tablename__ = "agent_proposals"
    __table_args__ = (
        Index("ix_agent_proposals_user_created", "user_id", "created_at"),
        Index("ix_agent_proposals_type_target", "proposal_type", "target_kind", "target_id"),
        Index("ix_agent_proposals_status_expires", "status", "expires_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    proposal_type: Mapped[AgentProposalType] = mapped_column(
        SAEnum(AgentProposalType, name="agent_proposal_type", native_enum=False),
        nullable=False,
    )
    status: Mapped[AgentProposalStatus] = mapped_column(
        SAEnum(AgentProposalStatus, name="agent_proposal_status", native_enum=False),
        nullable=False,
        default=AgentProposalStatus.OPEN,
        server_default=AgentProposalStatus.OPEN.value,
    )
    target_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    summary_code: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    suggested_action: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    context_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    target_snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped["User"] = relationship("User")


class ApprovalTicket(Base):
    __tablename__ = "approval_tickets"
    __table_args__ = (
        Index("ix_approval_tickets_user_created", "user_id", "created_at"),
        Index("ix_approval_tickets_proposal_status", "proposal_id", "status"),
        Index("ix_approval_tickets_status_expires", "status", "expires_at"),
    )

    ticket_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("agent_proposals.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False, default="web", server_default="web")
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(255), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    payload_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    target_snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[ApprovalTicketStatus] = mapped_column(
        SAEnum(ApprovalTicketStatus, name="approval_ticket_status", native_enum=False),
        nullable=False,
        default=ApprovalTicketStatus.OPEN,
        server_default=ApprovalTicketStatus.OPEN.value,
    )
    executed_result_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped["User"] = relationship("User")
    proposal: Mapped[AgentProposal] = relationship("AgentProposal")


class McpAccessToken(Base):
    __tablename__ = "mcp_access_tokens"
    __table_args__ = (
        Index("ix_mcp_access_tokens_user_created", "user_id", "created_at"),
        Index("ix_mcp_access_tokens_token_id", "token_id"),
        Index("ix_mcp_access_tokens_revoked", "revoked_at"),
    )

    token_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    scopes_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped["User"] = relationship("User")


__all__ = [
    "ApprovalTicket",
    "ApprovalTicketStatus",
    "AgentProposal",
    "AgentProposalStatus",
    "AgentProposalType",
    "McpAccessToken",
]
