from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.agents import ChannelDelivery, ChannelDeliveryStatus


class ChannelDeliveryNotFoundError(RuntimeError):
    pass


class ChannelDeliveryClaimError(RuntimeError):
    pass


class ChannelDeliveryAckError(RuntimeError):
    pass


def claim_pending_deliveries(
    db: Session,
    *,
    worker_label: str,
    limit: int = 20,
    lease_seconds: int = 120,
) -> list[ChannelDelivery]:
    now = datetime.now(UTC)
    rows = list(
        db.scalars(
            select(ChannelDelivery)
            .where(
                ChannelDelivery.status == ChannelDeliveryStatus.PENDING,
                (ChannelDelivery.lease_expires_at.is_(None) | (ChannelDelivery.lease_expires_at <= now)),
            )
            .order_by(ChannelDelivery.created_at.asc(), ChannelDelivery.delivery_id.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
    )
    claimed: list[ChannelDelivery] = []
    for row in rows:
        row.attempt_count = int(row.attempt_count or 0) + 1
        row.lease_owner = worker_label.strip()[:128]
        row.lease_token = secrets.token_hex(16)
        row.lease_expires_at = now + timedelta(seconds=max(10, lease_seconds))
        claimed.append(row)
    db.commit()
    for row in claimed:
        db.refresh(row)
    return claimed


def mark_delivery_sent(
    db: Session,
    *,
    delivery_id: str,
    lease_token: str,
    external_message_id: str | None = None,
    callback_ttl_seconds: int = 24 * 60 * 60,
) -> tuple[ChannelDelivery, str]:
    row = _require_claimed_delivery(db=db, delivery_id=delivery_id, lease_token=lease_token)
    now = datetime.now(UTC)
    callback_token = _build_callback_token(delivery_id=delivery_id)
    row.status = ChannelDeliveryStatus.SENT
    row.sent_at = now
    row.external_message_id = external_message_id.strip()[:255] if isinstance(external_message_id, str) and external_message_id.strip() else None
    row.callback_token_hash = _hash_callback_token(callback_token)
    row.callback_expires_at = now + timedelta(seconds=max(60, callback_ttl_seconds))
    row.lease_owner = None
    row.lease_token = None
    row.lease_expires_at = None
    db.commit()
    db.refresh(row)
    return row, callback_token


def mark_delivery_failed(
    db: Session,
    *,
    delivery_id: str,
    lease_token: str,
    error_text: str,
) -> ChannelDelivery:
    row = _require_claimed_delivery(db=db, delivery_id=delivery_id, lease_token=lease_token)
    row.status = ChannelDeliveryStatus.FAILED
    row.failed_at = datetime.now(UTC)
    row.error_text = error_text[:2000]
    row.lease_owner = None
    row.lease_token = None
    row.lease_expires_at = None
    db.commit()
    db.refresh(row)
    return row


def acknowledge_delivery(
    db: Session,
    *,
    delivery_id: str,
    callback_token: str,
    ack_payload: dict | None = None,
) -> tuple[ChannelDelivery, bool]:
    row = db.scalar(select(ChannelDelivery).where(ChannelDelivery.delivery_id == delivery_id).with_for_update())
    if row is None:
        raise ChannelDeliveryNotFoundError("Channel delivery not found")
    if row.status == ChannelDeliveryStatus.ACKNOWLEDGED:
        return row, True
    now = datetime.now(UTC)
    if row.callback_expires_at is None or row.callback_expires_at <= now:
        raise ChannelDeliveryAckError("Channel delivery callback expired")
    if row.callback_token_hash != _hash_callback_token(callback_token):
        raise ChannelDeliveryAckError("Channel delivery callback token mismatch")
    row.status = ChannelDeliveryStatus.ACKNOWLEDGED
    row.acknowledged_at = now
    row.ack_payload_json = dict(ack_payload or {})
    db.commit()
    db.refresh(row)
    return row, False


def _require_claimed_delivery(db: Session, *, delivery_id: str, lease_token: str) -> ChannelDelivery:
    row = db.scalar(select(ChannelDelivery).where(ChannelDelivery.delivery_id == delivery_id).with_for_update())
    if row is None:
        raise ChannelDeliveryNotFoundError("Channel delivery not found")
    if row.status != ChannelDeliveryStatus.PENDING:
        raise ChannelDeliveryClaimError("Channel delivery is no longer pending")
    if not row.lease_token or row.lease_token != lease_token:
        raise ChannelDeliveryClaimError("Channel delivery lease token mismatch")
    now = datetime.now(UTC)
    if row.lease_expires_at is None or row.lease_expires_at <= now:
        raise ChannelDeliveryClaimError("Channel delivery lease expired")
    return row


def _build_callback_token(*, delivery_id: str) -> str:
    nonce = secrets.token_urlsafe(24)
    return f"cddel_{delivery_id}_{nonce}"


def _hash_callback_token(value: str) -> str:
    secret = get_settings().app_secret_key
    return hashlib.sha256(f"{secret}:{value}".encode("utf-8")).hexdigest()


__all__ = [
    "ChannelDeliveryAckError",
    "ChannelDeliveryClaimError",
    "ChannelDeliveryNotFoundError",
    "acknowledge_delivery",
    "claim_pending_deliveries",
    "mark_delivery_failed",
    "mark_delivery_sent",
]
