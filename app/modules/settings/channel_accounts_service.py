from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.agents import (
    ChannelAccount,
    ChannelAccountStatus,
    ChannelAccountType,
    ChannelDeliveryStatus,
    ChannelAccountVerificationStatus,
    ChannelDelivery,
)
from app.db.models.shared import User


class ChannelAccountNotFoundError(RuntimeError):
    pass


def list_channel_accounts(db: Session, *, user_id: int) -> list[ChannelAccount]:
    return list(
        db.scalars(
            select(ChannelAccount)
            .where(ChannelAccount.user_id == user_id)
            .order_by(ChannelAccount.updated_at.desc(), ChannelAccount.created_at.desc(), ChannelAccount.id.desc())
        ).all()
    )


def create_channel_account(
    db: Session,
    *,
    user: User,
    channel_type: str,
    account_label: str,
    external_user_id: str | None,
    external_workspace_id: str | None,
) -> ChannelAccount:
    normalized_type = ChannelAccountType(channel_type.strip().lower())
    row = ChannelAccount(
        user_id=user.id,
        channel_type=normalized_type,
        account_label=account_label.strip()[:128],
        external_user_id=external_user_id.strip()[:255] if isinstance(external_user_id, str) and external_user_id.strip() else None,
        external_workspace_id=external_workspace_id.strip()[:255] if isinstance(external_workspace_id, str) and external_workspace_id.strip() else None,
        status=ChannelAccountStatus.ACTIVE,
        verification_status=ChannelAccountVerificationStatus.PENDING,
        metadata_json={},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def revoke_channel_account(db: Session, *, user_id: int, account_id: int) -> ChannelAccount:
    row = db.scalar(
        select(ChannelAccount)
        .where(ChannelAccount.id == account_id, ChannelAccount.user_id == user_id)
        .limit(1)
    )
    if row is None:
        raise ChannelAccountNotFoundError("Channel account not found")
    row.status = ChannelAccountStatus.REVOKED
    row.verification_status = ChannelAccountVerificationStatus.REVOKED
    db.commit()
    db.refresh(row)
    return row


def list_channel_deliveries(db: Session, *, user_id: int, limit: int = 20) -> list[ChannelDelivery]:
    return list(
        db.scalars(
            select(ChannelDelivery)
            .where(ChannelDelivery.user_id == user_id)
            .order_by(ChannelDelivery.updated_at.desc(), ChannelDelivery.created_at.desc(), ChannelDelivery.delivery_id.desc())
            .limit(limit)
        ).all()
    )


def record_channel_delivery(
    db: Session,
    *,
    user_id: int,
    channel_account_id: int | None,
    proposal_id: int | None,
    ticket_id: str | None,
    delivery_kind: str,
    summary_code: str | None,
    detail_code: str | None,
    cta_code: str | None,
    payload_json: dict | None,
    origin_kind: str,
    origin_label: str,
) -> ChannelDelivery:
    row = ChannelDelivery(
        delivery_id=uuid4().hex,
        user_id=user_id,
        channel_account_id=channel_account_id,
        proposal_id=proposal_id,
        ticket_id=ticket_id,
        delivery_kind=delivery_kind.strip()[:64],
        summary_code=summary_code.strip()[:128] if isinstance(summary_code, str) and summary_code.strip() else None,
        detail_code=detail_code.strip()[:128] if isinstance(detail_code, str) and detail_code.strip() else None,
        cta_code=cta_code.strip()[:128] if isinstance(cta_code, str) and cta_code.strip() else None,
        payload_json=dict(payload_json or {}),
        origin_kind=origin_kind.strip()[:32] or "unknown",
        origin_label=origin_label.strip()[:64] or "unknown",
        status=ChannelDeliveryStatus.PENDING,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def mark_channel_delivery_sent(db: Session, *, delivery: ChannelDelivery) -> ChannelDelivery:
    delivery.status = ChannelDeliveryStatus.SENT
    delivery.sent_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(delivery)
    return delivery


__all__ = [
    "ChannelAccountNotFoundError",
    "create_channel_account",
    "list_channel_accounts",
    "list_channel_deliveries",
    "mark_channel_delivery_sent",
    "record_channel_delivery",
    "revoke_channel_account",
]
