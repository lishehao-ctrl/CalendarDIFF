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
    LABEL_LEARNING_COMMIT = "label_learning_commit"
    PROPOSAL_EDIT_COMMIT = "proposal_edit_commit"


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


class McpToolInvocationStatus(str, Enum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
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
    summary_params_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    reason_params_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    suggested_action: Mapped[str] = mapped_column(String(64), nullable=False)
    origin_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown", server_default="unknown")
    origin_label: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown", server_default="unknown")
    origin_request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
    origin_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown", server_default="unknown")
    origin_label: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown", server_default="unknown")
    origin_request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[ApprovalTicketStatus] = mapped_column(
        SAEnum(ApprovalTicketStatus, name="approval_ticket_status", native_enum=False),
        nullable=False,
        default=ApprovalTicketStatus.OPEN,
        server_default=ApprovalTicketStatus.OPEN.value,
    )
    last_transition_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown", server_default="unknown")
    last_transition_label: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown", server_default="unknown")
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


class McpToolInvocation(Base):
    __tablename__ = "mcp_tool_invocations"
    __table_args__ = (
        Index("ix_mcp_tool_invocations_user_created", "user_id", "created_at"),
        Index("ix_mcp_tool_invocations_tool_created", "tool_name", "created_at"),
        Index("ix_mcp_tool_invocations_status_created", "status", "created_at"),
    )

    invocation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    transport_request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    transport: Mapped[str] = mapped_column(String(32), nullable=False)
    auth_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[McpToolInvocationStatus] = mapped_column(
        SAEnum(McpToolInvocationStatus, name="mcp_tool_invocation_status", native_enum=False),
        nullable=False,
        default=McpToolInvocationStatus.STARTED,
        server_default=McpToolInvocationStatus.STARTED.value,
    )
    input_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    output_summary_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposal_id: Mapped[int | None] = mapped_column(ForeignKey("agent_proposals.id", ondelete="SET NULL"), nullable=True)
    ticket_id: Mapped[str | None] = mapped_column(ForeignKey("approval_tickets.ticket_id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship("User")
    proposal: Mapped["AgentProposal | None"] = relationship("AgentProposal")
    ticket: Mapped["ApprovalTicket | None"] = relationship("ApprovalTicket")


class ChannelAccountType(str, Enum):
    TELEGRAM = "telegram"
    SLACK = "slack"
    WECHAT = "wechat"
    WECOM = "wecom"


class ChannelAccountStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    REVOKED = "revoked"


class ChannelAccountVerificationStatus(str, Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    REVOKED = "revoked"


class ChannelDeliveryStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    ACKNOWLEDGED = "acknowledged"
    FAILED = "failed"
    CANCELED = "canceled"


class ChannelAccount(Base):
    __tablename__ = "channel_accounts"
    __table_args__ = (
        Index("ix_channel_accounts_user_created", "user_id", "created_at"),
        Index("ix_channel_accounts_user_type_status", "user_id", "channel_type", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    channel_type: Mapped[ChannelAccountType] = mapped_column(
        SAEnum(ChannelAccountType, name="channel_account_type", native_enum=False),
        nullable=False,
    )
    account_label: Mapped[str] = mapped_column(String(128), nullable=False)
    external_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_workspace_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[ChannelAccountStatus] = mapped_column(
        SAEnum(ChannelAccountStatus, name="channel_account_status", native_enum=False),
        nullable=False,
        default=ChannelAccountStatus.ACTIVE,
        server_default=ChannelAccountStatus.ACTIVE.value,
    )
    verification_status: Mapped[ChannelAccountVerificationStatus] = mapped_column(
        SAEnum(ChannelAccountVerificationStatus, name="channel_account_verification_status", native_enum=False),
        nullable=False,
        default=ChannelAccountVerificationStatus.PENDING,
        server_default=ChannelAccountVerificationStatus.PENDING.value,
    )
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped["User"] = relationship("User")


class ChannelDelivery(Base):
    __tablename__ = "channel_deliveries"
    __table_args__ = (
        Index("ix_channel_deliveries_user_created", "user_id", "created_at"),
        Index("ix_channel_deliveries_account_status", "channel_account_id", "status"),
        Index("ix_channel_deliveries_ticket_status", "ticket_id", "status"),
    )

    delivery_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    channel_account_id: Mapped[int | None] = mapped_column(ForeignKey("channel_accounts.id", ondelete="SET NULL"), nullable=True)
    proposal_id: Mapped[int | None] = mapped_column(ForeignKey("agent_proposals.id", ondelete="SET NULL"), nullable=True)
    ticket_id: Mapped[str | None] = mapped_column(ForeignKey("approval_tickets.ticket_id", ondelete="SET NULL"), nullable=True)
    delivery_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[ChannelDeliveryStatus] = mapped_column(
        SAEnum(ChannelDeliveryStatus, name="channel_delivery_status", native_enum=False),
        nullable=False,
        default=ChannelDeliveryStatus.PENDING,
        server_default=ChannelDeliveryStatus.PENDING.value,
    )
    summary_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    detail_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cta_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    ack_payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    origin_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown", server_default="unknown")
    origin_label: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown", server_default="unknown")
    attempt_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    external_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    callback_token_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    callback_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped["User"] = relationship("User")
    channel_account: Mapped["ChannelAccount | None"] = relationship("ChannelAccount")
    proposal: Mapped["AgentProposal | None"] = relationship("AgentProposal")
    ticket: Mapped["ApprovalTicket | None"] = relationship("ApprovalTicket")


__all__ = [
    "ChannelAccount",
    "ChannelAccountStatus",
    "ChannelAccountType",
    "ChannelAccountVerificationStatus",
    "ChannelDelivery",
    "ChannelDeliveryStatus",
    "ApprovalTicket",
    "ApprovalTicketStatus",
    "AgentProposal",
    "AgentProposalStatus",
    "AgentProposalType",
    "McpToolInvocation",
    "McpToolInvocationStatus",
    "McpAccessToken",
]
