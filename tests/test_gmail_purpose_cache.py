from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.runtime import GmailMessagePurposeCache, GmailMessagePurposeCacheMode
from app.db.models.shared import User
from app.modules.runtime.connectors import gmail_fetcher
from app.modules.runtime.llm.gmail_purpose_cache import (
    GMAIL_PURPOSE_CLASSIFIER_VERSION,
    build_gmail_purpose_cache_key,
    classify_gmail_message_fast_path,
    load_cached_gmail_purpose_mode,
    store_cached_gmail_purpose_mode,
)
from app.modules.sources.schemas import InputSourceCreateRequest
from app.modules.sources.sources_service import create_input_source


def _create_source(db_session: Session) -> int:
    user = User(
        email="gmail-purpose-cache@example.com",
        password_hash="hash",
        timezone_name="America/Los_Angeles",
    )
    db_session.add(user)
    db_session.flush()
    source = create_input_source(
        db_session,
        user=user,
        payload=InputSourceCreateRequest(
            source_kind="email",
            provider="gmail",
            display_name="Test Gmail Source",
            config={},
            secrets={
                "access_token": "test-access-token",
                "account_email": "student@example.edu",
            },
        ),
    )
    return int(source.id)


def _payload(
    *,
    message_id: str,
    subject: str = "Digest update",
    snippet: str = "Digest content",
    body_text: str = "Digest body content",
    from_header: str = "digest@example.com",
    internal_date: str = "2026-02-01T15:00:00+00:00",
    label_ids: list[str] | None = None,
    reason_code: str = "newsletter_digest",
    risk_band: str = "safe",
    fast_path_unknown_eligible: bool = True,
    known_course_signal: bool = False,
    sender_family: str = "unknown_sender",
) -> dict[str, object]:
    return {
        "message_id": message_id,
        "subject": subject,
        "snippet": snippet,
        "body_text": body_text,
        "from_header": from_header,
        "internal_date": internal_date,
        "label_ids": list(label_ids or ["INBOX"]),
        "classification_hints": {
            "known_course_signal": known_course_signal,
            "second_filter_reason_code": reason_code,
            "second_filter_risk_band": risk_band,
            "fast_path_unknown_eligible": fast_path_unknown_eligible,
            "sender_family": sender_family,
        },
    }


def test_gmail_purpose_cache_exact_hit_increments_hit_count(db_session: Session) -> None:
    source_id = _create_source(db_session)
    payload = _payload(message_id="m-exact")
    store_cached_gmail_purpose_mode(
        db=db_session,
        source_id=source_id,
        payload_item=payload,
        mode="unknown",
        evidence="digest",
        reason_code="newsletter_digest",
        decision_source="llm",
        provider_id="qwen_us_main",
        model="qwen3.5-flash",
        protocol="responses",
    )

    loaded = load_cached_gmail_purpose_mode(db=db_session, source_id=source_id, payload_item=payload)

    assert loaded is not None
    assert loaded.hit_type == "exact"
    assert loaded.mode == "unknown"
    row = db_session.scalar(
        select(GmailMessagePurposeCache).where(
            GmailMessagePurposeCache.source_id == source_id,
            GmailMessagePurposeCache.message_id == "m-exact",
        )
    )
    assert row is not None
    assert row.hit_count == 1
    assert row.mode == GmailMessagePurposeCacheMode.UNKNOWN


def test_gmail_purpose_cache_reuses_shared_content_hash_across_message_ids(db_session: Session) -> None:
    source_id = _create_source(db_session)
    first = _payload(message_id="m-shared-a", subject="Project reminder", snippet="One concrete event", body_text="One concrete event body")
    second = _payload(message_id="m-shared-b", subject="Project reminder", snippet="One concrete event", body_text="One concrete event body")
    store_cached_gmail_purpose_mode(
        db=db_session,
        source_id=source_id,
        payload_item=first,
        mode="directive",
        evidence="change every section due date",
        reason_code=None,
        decision_source="llm",
        provider_id="qwen_us_main",
        model="qwen3.5-flash",
        protocol="responses",
    )

    loaded = load_cached_gmail_purpose_mode(db=db_session, source_id=source_id, payload_item=second)

    assert loaded is not None
    assert loaded.hit_type == "content_hash"
    assert loaded.mode == "directive"


def test_gmail_purpose_cache_reuses_unknown_fingerprint_only_for_safe_unknowns(db_session: Session) -> None:
    source_id = _create_source(db_session)
    first = _payload(
        message_id="m-fingerprint-a",
        body_text=("x" * 600) + "alpha",
        reason_code="newsletter_digest",
        fast_path_unknown_eligible=True,
    )
    second = _payload(
        message_id="m-fingerprint-b",
        body_text=("x" * 600) + "beta",
        reason_code="newsletter_digest",
        fast_path_unknown_eligible=True,
    )
    store_cached_gmail_purpose_mode(
        db=db_session,
        source_id=source_id,
        payload_item=first,
        mode="unknown",
        evidence="digest",
        reason_code="newsletter_digest",
        decision_source="llm",
        provider_id="qwen_us_main",
        model="qwen3.5-flash",
        protocol="responses",
    )

    loaded = load_cached_gmail_purpose_mode(db=db_session, source_id=source_id, payload_item=second)

    assert loaded is not None
    assert loaded.hit_type == "fingerprint"
    assert loaded.mode == "unknown"


def test_gmail_purpose_cache_does_not_reuse_atomic_fingerprint_hits(db_session: Session) -> None:
    source_id = _create_source(db_session)
    first = _payload(
        message_id="m-atomic-a",
        body_text=("y" * 600) + "alpha",
        reason_code="newsletter_digest",
        fast_path_unknown_eligible=True,
    )
    second = _payload(
        message_id="m-atomic-b",
        body_text=("y" * 600) + "beta",
        reason_code="newsletter_digest",
        fast_path_unknown_eligible=True,
    )
    store_cached_gmail_purpose_mode(
        db=db_session,
        source_id=source_id,
        payload_item=first,
        mode="atomic",
        evidence="single assignment",
        reason_code=None,
        decision_source="llm",
        provider_id="qwen_us_main",
        model="qwen3.5-flash",
        protocol="responses",
    )

    loaded = load_cached_gmail_purpose_mode(db=db_session, source_id=source_id, payload_item=second)

    assert loaded is None


def test_gmail_purpose_cache_misses_classifier_version_mismatch(db_session: Session) -> None:
    source_id = _create_source(db_session)
    payload = _payload(message_id="m-version")
    cache_key = build_gmail_purpose_cache_key(payload)
    assert cache_key is not None
    db_session.add(
        GmailMessagePurposeCache(
            source_id=source_id,
            message_id=str(cache_key["message_id"]),
            content_hash=str(cache_key["content_hash"]),
            classifier_version="gmail-purpose-mode:v0|prompt:v1|routing:v1|monitoring-window:v1",
            message_fingerprint=str(cache_key["message_fingerprint"]),
            mode=GmailMessagePurposeCacheMode.UNKNOWN,
            evidence="old digest",
            reason_code="newsletter_digest",
            decision_source="llm",
            provider_id="qwen_us_main",
            model="qwen3.5-flash",
            protocol="responses",
        )
    )
    db_session.commit()

    loaded = load_cached_gmail_purpose_mode(db=db_session, source_id=source_id, payload_item=payload)

    assert loaded is None


def test_gmail_purpose_cache_skips_store_without_message_id(db_session: Session) -> None:
    source_id = _create_source(db_session)
    payload = _payload(message_id="missing-id")
    payload.pop("message_id")

    assert build_gmail_purpose_cache_key(payload) is None
    store_cached_gmail_purpose_mode(
        db=db_session,
        source_id=source_id,
        payload_item=payload,
        mode="unknown",
        evidence="digest",
        reason_code="newsletter_digest",
        decision_source="llm",
        provider_id="qwen_us_main",
        model="qwen3.5-flash",
        protocol="responses",
    )

    count = db_session.scalar(select(func.count(GmailMessagePurposeCache.id)))
    assert int(count or 0) == 0


def test_gmail_fast_path_allows_shipping_subscription_aliases() -> None:
    metadata = SimpleNamespace(
        message_id="m-shipping",
        thread_id="t-shipping",
        subject="Project shipment exception notice",
        snippet="Shipping exception notification for your storage subscription",
        body_text="This is a subscription update and package tracking notice. No academic deadline changed.",
        from_header="CloudStorage Plus <shipping@cloudstorage-plus.example>",
        internal_date="2026-02-01T15:00:00+00:00",
        label_ids=["INBOX"],
    )
    payload = gmail_fetcher._build_gmail_parse_message_payload(
        metadata=metadata,
        request_id="req-shipping",
        history_id="history-1",
        account_email="student@example.edu",
        known_course_tokens=set(),
    )

    decision = classify_gmail_message_fast_path(payload_item=payload)

    assert payload["classification_hints"]["second_filter_reason_code"] == "shipping_subscription_bait"
    assert decision is not None
    assert decision.mode == "unknown"
    assert decision.reason_code == "shipping_subscription_bait"
    assert decision.classifier_version == GMAIL_PURPOSE_CLASSIFIER_VERSION


def test_gmail_fast_path_allows_recruiting_aliases() -> None:
    metadata = SimpleNamespace(
        message_id="m-jobs",
        thread_id="t-jobs",
        subject="Resume review and internship networking invitation",
        snippet="Career networking timing is non-target and unrelated to monitored course deadlines.",
        body_text="This mailbox is not monitored. Recruiting logistics are unrelated to monitored course deadlines.",
        from_header="Careers Team <jobs@careers.example.com>",
        internal_date="2026-02-01T15:00:00+00:00",
        label_ids=["INBOX"],
    )
    payload = gmail_fetcher._build_gmail_parse_message_payload(
        metadata=metadata,
        request_id="req-jobs",
        history_id="history-2",
        account_email="student@example.edu",
        known_course_tokens=set(),
    )

    decision = classify_gmail_message_fast_path(payload_item=payload)

    assert payload["classification_hints"]["second_filter_reason_code"] == "recruiting_career_internship_bait"
    assert decision is not None
    assert decision.reason_code == "recruiting_career_internship_bait"


def test_gmail_fast_path_rejects_clear_due_signal() -> None:
    metadata = SimpleNamespace(
        message_id="m-due",
        thread_id="t-due",
        subject="Project shipment exception notice",
        snippet="Homework 3 due tomorrow at 11:59 PM",
        body_text="Track shipment later. Homework 3 due tomorrow at 11:59 PM.",
        from_header="CloudStorage Plus <shipping@cloudstorage-plus.example>",
        internal_date="2026-02-01T15:00:00+00:00",
        label_ids=["INBOX"],
    )
    payload = gmail_fetcher._build_gmail_parse_message_payload(
        metadata=metadata,
        request_id="req-due",
        history_id="history-3",
        account_email="student@example.edu",
        known_course_tokens=set(),
    )

    assert payload["classification_hints"]["fast_path_unknown_eligible"] is False
    assert classify_gmail_message_fast_path(payload_item=payload) is None


def test_gmail_fast_path_rejects_known_course_signal() -> None:
    metadata = SimpleNamespace(
        message_id="m-course",
        thread_id="t-course",
        subject="CSE 120 campus weekly digest",
        snippet="Campus weekly digest for CSE 120 students",
        body_text="Newsletter action prompts are intentionally noisy and non-canonical. Manage preferences here.",
        from_header="Campus Weekly <digest@lists.example.edu>",
        internal_date="2026-02-01T15:00:00+00:00",
        label_ids=["INBOX"],
    )
    payload = gmail_fetcher._build_gmail_parse_message_payload(
        metadata=metadata,
        request_id="req-course",
        history_id="history-4",
        account_email="student@example.edu",
        known_course_tokens={"cse 120", "cse120"},
    )

    assert payload["classification_hints"]["known_course_signal"] is True
    assert payload["classification_hints"]["fast_path_unknown_eligible"] is False
    assert classify_gmail_message_fast_path(payload_item=payload) is None
