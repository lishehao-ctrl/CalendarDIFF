from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.runtime import GmailMessagePurposeCache, GmailMessagePurposeCacheMode
from app.modules.runtime.kernel import utcnow

GMAIL_PURPOSE_CLASSIFIER_VERSION = "gmail-purpose-mode:v1|prompt:v3|routing:v1|monitoring-window:v1"
GmailPurposeCacheHitType = Literal["exact", "content_hash", "fingerprint"]
_FINGERPRINT_REUSE_ALLOWED_REASON_CODES = {
    "academic_non_target_explicit_no_change",
    "newsletter_digest",
    "calendar_wrapper_noise",
    "student_services_noise",
    "shipping_subscription_bait",
    "recruiting_career_internship_bait",
    "package_subscription",
    "jobs",
}


@dataclass(frozen=True)
class GmailPurposeCacheEntry:
    mode: str
    evidence: str | None
    reason_code: str | None
    decision_source: str
    provider_id: str | None
    model: str | None
    protocol: str | None
    classifier_version: str
    message_fingerprint: str
    hit_type: GmailPurposeCacheHitType

    def to_hint_payload(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "evidence": self.evidence,
            "reason_code": self.reason_code,
            "decision_source": "purpose_cache",
            "provider_id": self.provider_id,
            "model": self.model,
            "protocol": self.protocol,
            "classifier_version": self.classifier_version,
            "message_fingerprint": self.message_fingerprint,
            "cache_hit_type": self.hit_type,
        }


@dataclass(frozen=True)
class GmailPurposeFastPathDecision:
    mode: Literal["unknown"]
    reason_code: str
    evidence: str | None
    classifier_version: str
    message_fingerprint: str

    def to_hint_payload(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "evidence": self.evidence,
            "reason_code": self.reason_code,
            "decision_source": "fast_path",
            "provider_id": None,
            "model": None,
            "protocol": None,
            "classifier_version": self.classifier_version,
            "message_fingerprint": self.message_fingerprint,
        }


def load_cached_gmail_purpose_mode(
    *,
    db: Session,
    source_id: int,
    payload_item: dict[str, Any],
) -> GmailPurposeCacheEntry | None:
    if not bool(get_settings().gmail_purpose_mode_cache_enabled):
        return None
    if not hasattr(db, "scalar"):
        return None
    cache_key = build_gmail_purpose_cache_key(payload_item)
    if cache_key is None:
        return None

    exact = db.scalar(
        select(GmailMessagePurposeCache).where(
            GmailMessagePurposeCache.source_id == source_id,
            GmailMessagePurposeCache.message_id == cache_key["message_id"],
            GmailMessagePurposeCache.content_hash == cache_key["content_hash"],
            GmailMessagePurposeCache.classifier_version == cache_key["classifier_version"],
        )
    )
    if exact is not None:
        _mark_cache_hit(db, row=exact)
        return _to_cache_entry(exact, hit_type="exact")

    shared_content = db.scalar(
        select(GmailMessagePurposeCache)
        .where(
            GmailMessagePurposeCache.source_id == source_id,
            GmailMessagePurposeCache.content_hash == cache_key["content_hash"],
            GmailMessagePurposeCache.classifier_version == cache_key["classifier_version"],
        )
        .order_by(GmailMessagePurposeCache.updated_at.desc(), GmailMessagePurposeCache.id.desc())
        .limit(1)
    )
    if shared_content is not None:
        _mark_cache_hit(db, row=shared_content)
        return _to_cache_entry(shared_content, hit_type="content_hash")

    if _allow_unknown_fingerprint_reuse(payload_item):
        shared_unknown = db.scalar(
            select(GmailMessagePurposeCache)
            .where(
                GmailMessagePurposeCache.source_id == source_id,
                GmailMessagePurposeCache.message_fingerprint == cache_key["message_fingerprint"],
                GmailMessagePurposeCache.classifier_version == cache_key["classifier_version"],
                GmailMessagePurposeCache.mode == GmailMessagePurposeCacheMode.UNKNOWN,
            )
            .order_by(GmailMessagePurposeCache.updated_at.desc(), GmailMessagePurposeCache.id.desc())
            .limit(1)
        )
        if shared_unknown is not None:
            _mark_cache_hit(db, row=shared_unknown)
            return _to_cache_entry(shared_unknown, hit_type="fingerprint")
    return None


def store_cached_gmail_purpose_mode(
    *,
    db: Session,
    source_id: int,
    payload_item: dict[str, Any],
    mode: str,
    evidence: str | None,
    reason_code: str | None,
    decision_source: str,
    provider_id: str | None,
    model: str | None,
    protocol: str | None,
) -> None:
    if not bool(get_settings().gmail_purpose_mode_cache_enabled):
        return
    if not hasattr(db, "scalar"):
        return
    cache_key = build_gmail_purpose_cache_key(payload_item)
    if cache_key is None:
        return
    normalized_mode = _normalize_mode(mode)
    if normalized_mode is None:
        return
    row = db.scalar(
        select(GmailMessagePurposeCache).where(
            GmailMessagePurposeCache.source_id == source_id,
            GmailMessagePurposeCache.message_id == cache_key["message_id"],
            GmailMessagePurposeCache.content_hash == cache_key["content_hash"],
            GmailMessagePurposeCache.classifier_version == cache_key["classifier_version"],
        )
    )
    now = utcnow()
    if row is None:
        row = GmailMessagePurposeCache(
            source_id=source_id,
            message_id=cache_key["message_id"],
            content_hash=cache_key["content_hash"],
            classifier_version=cache_key["classifier_version"],
            message_fingerprint=cache_key["message_fingerprint"],
            mode=normalized_mode,
            evidence=_normalize_optional_text(evidence, max_chars=255),
            reason_code=_normalize_optional_text(reason_code, max_chars=64),
            decision_source=_normalize_optional_text(decision_source, max_chars=32) or "llm",
            provider_id=_normalize_optional_text(provider_id, max_chars=64),
            model=_normalize_optional_text(model, max_chars=128),
            protocol=_normalize_optional_text(protocol, max_chars=64),
            hit_count=0,
            last_used_at=now,
        )
        db.add(row)
    else:
        row.message_fingerprint = cache_key["message_fingerprint"]
        row.mode = normalized_mode
        row.evidence = _normalize_optional_text(evidence, max_chars=255)
        row.reason_code = _normalize_optional_text(reason_code, max_chars=64)
        row.decision_source = _normalize_optional_text(decision_source, max_chars=32) or "llm"
        row.provider_id = _normalize_optional_text(provider_id, max_chars=64)
        row.model = _normalize_optional_text(model, max_chars=128)
        row.protocol = _normalize_optional_text(protocol, max_chars=64)
        row.last_used_at = now
    db.commit()


def classify_gmail_message_fast_path(
    *,
    payload_item: dict[str, Any],
) -> GmailPurposeFastPathDecision | None:
    hints = payload_item.get("classification_hints")
    if not isinstance(hints, dict):
        return None
    if not bool(hints.get("fast_path_unknown_eligible")):
        return None
    reason_code = _normalize_optional_text(hints.get("second_filter_reason_code"), max_chars=64)
    if reason_code not in _FINGERPRINT_REUSE_ALLOWED_REASON_CODES:
        return None
    return GmailPurposeFastPathDecision(
        mode="unknown",
        reason_code=reason_code,
        evidence=_normalize_optional_text(payload_item.get("snippet") or payload_item.get("subject"), max_chars=255),
        classifier_version=GMAIL_PURPOSE_CLASSIFIER_VERSION,
        message_fingerprint=build_gmail_purpose_message_fingerprint(payload_item),
    )


def build_gmail_purpose_cache_key(payload_item: dict[str, Any]) -> dict[str, str] | None:
    message_id = _normalize_optional_text(payload_item.get("message_id"), max_chars=255)
    if not message_id:
        return None
    normalized = {
        "from_header": _normalize_optional_text(payload_item.get("from_header"), max_chars=512),
        "subject": _normalize_optional_text(payload_item.get("subject"), max_chars=512),
        "snippet": _normalize_optional_text(payload_item.get("snippet"), max_chars=2048),
        "body_text": _normalize_optional_text(payload_item.get("body_text"), max_chars=12000),
        "label_ids": [value for value in payload_item.get("label_ids", []) if isinstance(value, str)],
    }
    serialized = json.dumps(normalized, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return {
        "message_id": message_id,
        "content_hash": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        "classifier_version": GMAIL_PURPOSE_CLASSIFIER_VERSION,
        "message_fingerprint": build_gmail_purpose_message_fingerprint(payload_item),
    }


def build_gmail_purpose_message_fingerprint(payload_item: dict[str, Any]) -> str:
    hints = payload_item.get("classification_hints") if isinstance(payload_item.get("classification_hints"), dict) else {}
    normalized = {
        "sender_bucket": _normalize_optional_text(hints.get("sender_family"), max_chars=32),
        "subject": _normalize_optional_text(payload_item.get("subject"), max_chars=160),
        "snippet": _normalize_optional_text(payload_item.get("snippet"), max_chars=160),
        "body_digest": hashlib.sha256(
            (_normalize_optional_text(payload_item.get("body_text"), max_chars=600) or "").encode("utf-8")
        ).hexdigest(),
        "label_ids": sorted(value for value in payload_item.get("label_ids", []) if isinstance(value, str)),
        "internal_date_bucket": _normalize_internal_date_bucket(payload_item.get("internal_date")),
        "reason_code": _normalize_optional_text(hints.get("second_filter_reason_code"), max_chars=64),
    }
    serialized = json.dumps(normalized, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _normalize_internal_date_bucket(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    return candidate[:7] if len(candidate) >= 7 else candidate


def _allow_unknown_fingerprint_reuse(payload_item: dict[str, Any]) -> bool:
    if not bool(get_settings().gmail_purpose_mode_fingerprint_reuse_enabled):
        return False
    hints = payload_item.get("classification_hints")
    if not isinstance(hints, dict):
        return False
    return bool(hints.get("fast_path_unknown_eligible"))


def _to_cache_entry(row: GmailMessagePurposeCache, *, hit_type: GmailPurposeCacheHitType) -> GmailPurposeCacheEntry:
    return GmailPurposeCacheEntry(
        mode=row.mode.value if isinstance(row.mode, GmailMessagePurposeCacheMode) else str(row.mode),
        evidence=row.evidence,
        reason_code=row.reason_code,
        decision_source=row.decision_source,
        provider_id=row.provider_id,
        model=row.model,
        protocol=row.protocol,
        classifier_version=row.classifier_version,
        message_fingerprint=row.message_fingerprint,
        hit_type=hit_type,
    )


def _mark_cache_hit(db: Session, *, row: GmailMessagePurposeCache) -> None:
    row.hit_count = max(int(row.hit_count or 0), 0) + 1
    row.last_used_at = utcnow()
    db.commit()


def _normalize_mode(value: str | None) -> GmailMessagePurposeCacheMode | None:
    normalized = str(value or "").strip().lower()
    if normalized == "unknown":
        return GmailMessagePurposeCacheMode.UNKNOWN
    if normalized == "atomic":
        return GmailMessagePurposeCacheMode.ATOMIC
    if normalized == "directive":
        return GmailMessagePurposeCacheMode.DIRECTIVE
    return None


def _normalize_optional_text(value: Any, *, max_chars: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split()).strip()
    if not cleaned:
        return None
    return cleaned[:max_chars]


__all__ = [
    "GMAIL_PURPOSE_CLASSIFIER_VERSION",
    "GmailPurposeCacheEntry",
    "GmailPurposeFastPathDecision",
    "build_gmail_purpose_cache_key",
    "build_gmail_purpose_message_fingerprint",
    "classify_gmail_message_fast_path",
    "load_cached_gmail_purpose_mode",
    "store_cached_gmail_purpose_mode",
]
