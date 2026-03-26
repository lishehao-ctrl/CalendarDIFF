from __future__ import annotations

from types import SimpleNamespace

from app.modules.runtime.connectors.llm_parsers.contracts import LlmParseError
from app.db.models.runtime import ConnectorResultStatus
import app.modules.runtime.llm.gmail_parse_executor as gmail_parse_executor
from app.modules.runtime.llm import parse_pipeline as pipeline
from app.modules.runtime.llm.gmail_purpose_cache import GmailPurposeCacheEntry, GmailPurposeFastPathDecision, GMAIL_PURPOSE_CLASSIFIER_VERSION


class DummyParserOutput:
    def __init__(self, records):
        self.records = records
        self.parser_name = "gmail_llm"
        self.parser_version = "mainline"
        self.model_hint = "test-model"


def test_parse_with_llm_processes_gmail_messages(monkeypatch) -> None:
    captured = {"calls": 0}

    class DummySession:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("app.db.session.get_session_factory", lambda: lambda: DummySession())
    monkeypatch.setattr(pipeline, "load_cached_gmail_parse_records", lambda **kwargs: None)
    monkeypatch.setattr(pipeline, "store_cached_gmail_parse_records", lambda **kwargs: None)

    def _fake_invoke_parser_with_limit(**kwargs):
        captured["calls"] += 1
        return DummyParserOutput(
            [
                {
                    "record_type": "gmail.message.extracted",
                    "payload": {"message_id": "m1"},
                }
            ]
        )

    monkeypatch.setattr(pipeline, "invoke_parser_with_limit", _fake_invoke_parser_with_limit)
    monkeypatch.setattr(pipeline, "attach_parser_metadata", lambda *, records, parser_output: records)
    monkeypatch.setattr(pipeline, "parse_gmail_payload", lambda **kwargs: object())

    records, status = pipeline.parse_with_llm(
        redis_client=object(),  # type: ignore[arg-type]
        stream_key="llm:parse:stream",
        source_id=1,
        provider_hint="gmail",
        parse_payload={"kind": "gmail", "messages": [{"message_id": "m1"}]},
        request_id="req-gmail-branch",
    )

    assert captured["calls"] == 1
    assert status == ConnectorResultStatus.CHANGED
    assert len(records) == 1
    assert records[0]["record_type"] == "gmail.message.extracted"


def test_parse_with_llm_processes_gmail_messages_with_controlled_parallelism(monkeypatch) -> None:
    observed: list[str] = []
    monkeypatch.setattr(pipeline, "gmail_parse_worker_count", lambda _count: 4)
    monkeypatch.setattr("app.db.session.get_session_factory", lambda: object())
    monkeypatch.setattr(
        pipeline,
        "_parse_single_gmail_message",
        lambda **kwargs: observed.append(kwargs["payload_item"]["message_id"])
        or [{"record_type": "gmail.message.extracted", "payload": {"message_id": kwargs["payload_item"]["message_id"]}}],
    )

    messages = [{"message_id": f"m{i}"} for i in range(4)]
    records, status = pipeline.parse_with_llm(
        redis_client=object(),  # type: ignore[arg-type]
        stream_key="llm:parse:stream",
        source_id=1,
        provider_hint="gmail",
        parse_payload={"kind": "gmail", "messages": messages},
        request_id="req-gmail-parallel",
    )

    assert status == ConnectorResultStatus.CHANGED
    assert len(records) == 4
    assert sorted(record["payload"]["message_id"] for record in records) == ["m0", "m1", "m2", "m3"]


def test_gmail_parse_worker_count_obeys_settings(monkeypatch) -> None:
    monkeypatch.setattr(
        gmail_parse_executor,
        "get_settings",
        lambda: SimpleNamespace(llm_worker_concurrency=12, gmail_parse_max_workers=9),
    )

    assert gmail_parse_executor.gmail_parse_worker_count(1) == 1
    assert gmail_parse_executor.gmail_parse_worker_count(4) == 4
    assert gmail_parse_executor.gmail_parse_worker_count(20) == 9


def test_gmail_parse_worker_count_respects_global_concurrency(monkeypatch) -> None:
    monkeypatch.setattr(
        gmail_parse_executor,
        "get_settings",
        lambda: SimpleNamespace(llm_worker_concurrency=5, gmail_parse_max_workers=12),
    )

    assert gmail_parse_executor.gmail_parse_worker_count(20) == 5


def test_parse_with_llm_skips_non_retryable_gmail_message_error(monkeypatch) -> None:
    metric_calls: list[str] = []

    class DummySession:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("app.db.session.get_session_factory", lambda: lambda: DummySession())
    monkeypatch.setattr(pipeline, "load_cached_gmail_parse_records", lambda **kwargs: None)
    monkeypatch.setattr(pipeline, "store_cached_gmail_parse_records", lambda **kwargs: None)
    monkeypatch.setattr(pipeline, "store_non_retryable_gmail_parse_skip", lambda **kwargs: None)
    monkeypatch.setattr(pipeline, "attach_parser_metadata", lambda *, records, parser_output: records)

    def fake_parse_gmail_payload(*, db, payload, context):  # noqa: ANN001
        del db, context
        if payload["message_id"] == "bad":
            raise LlmParseError(
                code="parse_llm_gmail_schema_invalid",
                message="bad schema",
                retryable=False,
                provider="gmail",
            )
        return DummyParserOutput(
            [{"record_type": "gmail.message.extracted", "payload": {"message_id": payload["message_id"]}}]
        )

    monkeypatch.setattr(pipeline, "parse_gmail_payload", fake_parse_gmail_payload)
    monkeypatch.setattr(
        pipeline,
        "invoke_parser_with_limit",
        lambda **kwargs: kwargs["parse_call"](),
    )
    monkeypatch.setattr(
        pipeline,
        "increment_parse_metric_counter",
        lambda _redis, *, metric_name, amount=1: metric_calls.extend([metric_name] * amount),
    )

    good_records = pipeline._parse_single_gmail_message(
        redis_client=object(),  # type: ignore[arg-type]
        stream_key="llm:parse:stream",
        source_id=1,
        request_id="req-gmail-skip-bad",
        session_factory=(lambda: DummySession()),
        provider="gmail",
        payload_item={"message_id": "good"},
    )
    bad_records = pipeline._parse_single_gmail_message(
        redis_client=object(),  # type: ignore[arg-type]
        stream_key="llm:parse:stream",
        source_id=1,
        request_id="req-gmail-skip-bad",
        session_factory=(lambda: DummySession()),
        provider="gmail",
        payload_item={"message_id": "bad"},
    )

    assert len(good_records) == 1
    assert good_records[0]["payload"]["message_id"] == "good"
    assert bad_records == []
    assert "gmail_messages_skipped_non_retryable_parse_error" in metric_calls


def test_parse_single_gmail_message_uses_persistent_cache_hit(monkeypatch) -> None:
    class DummySession:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        pipeline,
        "load_cached_gmail_parse_records",
        lambda **kwargs: [{"record_type": "gmail.message.extracted", "payload": {"message_id": "cached"}}],
    )
    monkeypatch.setattr(
        pipeline,
        "increment_parse_metric_counter",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        pipeline,
        "parse_gmail_payload",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("parser should not run on cache hit")),
    )

    records = pipeline._parse_single_gmail_message(
        session_factory=(lambda: DummySession()),
        redis_client=object(),  # type: ignore[arg-type]
        stream_key="llm:parse:stream",
        source_id=1,
        provider="gmail",
        request_id="req-gmail-cache-hit",
        payload_item={"message_id": "cached"},
    )

    assert records == [{"record_type": "gmail.message.extracted", "payload": {"message_id": "cached"}}]


def test_parse_single_gmail_message_stores_non_retryable_skip(monkeypatch) -> None:
    stored: list[tuple[str, str]] = []

    class DummySession:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(pipeline, "load_cached_gmail_parse_records", lambda **kwargs: None)
    monkeypatch.setattr(pipeline, "attach_parser_metadata", lambda *, records, parser_output: records)
    monkeypatch.setattr(
        pipeline,
        "increment_parse_metric_counter",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        pipeline,
        "store_non_retryable_gmail_parse_skip",
        lambda **kwargs: stored.append((kwargs["payload_item"]["message_id"], kwargs["error_code"])),
    )
    monkeypatch.setattr(
        pipeline,
        "invoke_parser_with_limit",
        lambda **kwargs: kwargs["parse_call"](),
    )

    def fake_parse_gmail_payload(*, db, payload, context):  # noqa: ANN001
        del db, context
        raise LlmParseError(
            code="parse_llm_gmail_schema_invalid",
            message="bad schema",
            retryable=False,
            provider="gmail",
        )

    monkeypatch.setattr(pipeline, "parse_gmail_payload", fake_parse_gmail_payload)

    records = pipeline._parse_single_gmail_message(
        session_factory=(lambda: DummySession()),
        redis_client=object(),  # type: ignore[arg-type]
        stream_key="llm:parse:stream",
        source_id=1,
        provider="gmail",
        request_id="req-gmail-store-skip",
        payload_item={"message_id": "bad"},
    )

    assert records == []
    assert stored == [("bad", "parse_llm_gmail_schema_invalid")]


def test_parse_single_gmail_message_uses_cached_purpose_unknown_without_parser(monkeypatch) -> None:
    stored_empty: list[list[dict]] = []

    class DummySession:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(pipeline, "load_cached_gmail_parse_records", lambda **kwargs: None)
    monkeypatch.setattr(
        pipeline,
        "load_cached_gmail_purpose_mode",
        lambda **kwargs: GmailPurposeCacheEntry(
            mode="unknown",
            evidence="wrapper",
            reason_code="newsletter_digest",
            decision_source="llm",
            provider_id="qwen_us_main",
            model="qwen3.5-flash",
            protocol="responses",
            classifier_version=GMAIL_PURPOSE_CLASSIFIER_VERSION,
            message_fingerprint="fp-1",
            hit_type="exact",
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "store_cached_gmail_parse_records",
        lambda **kwargs: stored_empty.append(kwargs["records"]),
    )
    monkeypatch.setattr(pipeline, "increment_parse_metric_counter", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        pipeline,
        "parse_gmail_payload",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("parser should not run on cached purpose unknown")),
    )

    records = pipeline._parse_single_gmail_message(
        session_factory=(lambda: DummySession()),
        redis_client=object(),  # type: ignore[arg-type]
        stream_key="llm:parse:stream",
        source_id=1,
        provider="gmail",
        request_id="req-gmail-purpose-cache-unknown",
        payload_item={"message_id": "cached-unknown"},
    )

    assert records == []
    assert stored_empty == [[]]


def test_parse_single_gmail_message_uses_cached_purpose_atomic_hint(monkeypatch) -> None:
    seen_payloads: list[dict] = []

    class DummySession:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(pipeline, "load_cached_gmail_parse_records", lambda **kwargs: None)
    monkeypatch.setattr(
        pipeline,
        "load_cached_gmail_purpose_mode",
        lambda **kwargs: GmailPurposeCacheEntry(
            mode="atomic",
            evidence="single homework event",
            reason_code=None,
            decision_source="llm",
            provider_id="qwen_us_main",
            model="qwen3.5-flash",
            protocol="responses",
            classifier_version=GMAIL_PURPOSE_CLASSIFIER_VERSION,
            message_fingerprint="fp-2",
            hit_type="content_hash",
        ),
    )
    monkeypatch.setattr(pipeline, "increment_parse_metric_counter", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline, "store_cached_gmail_parse_records", lambda **kwargs: None)
    monkeypatch.setattr(pipeline, "attach_parser_metadata", lambda *, records, parser_output: records)
    monkeypatch.setattr(
        pipeline,
        "invoke_parser_with_limit",
        lambda **kwargs: kwargs["parse_call"](),
    )

    def fake_parse_gmail_payload(*, db, payload, context):  # noqa: ANN001
        del db, context
        seen_payloads.append(payload)
        return DummyParserOutput(
            [{"record_type": "gmail.message.extracted", "payload": {"message_id": payload["message_id"]}}]
        )

    monkeypatch.setattr(pipeline, "parse_gmail_payload", fake_parse_gmail_payload)

    records = pipeline._parse_single_gmail_message(
        session_factory=(lambda: DummySession()),
        redis_client=object(),  # type: ignore[arg-type]
        stream_key="llm:parse:stream",
        source_id=1,
        provider="gmail",
        request_id="req-gmail-purpose-cache-atomic",
        payload_item={"message_id": "cached-atomic"},
    )

    assert len(records) == 1
    assert seen_payloads
    assert seen_payloads[0]["_gmail_purpose_mode_hint"]["mode"] == "atomic"
    assert seen_payloads[0]["_gmail_purpose_mode_hint"]["decision_source"] == "purpose_cache"


def test_parse_single_gmail_message_uses_deterministic_fast_path_unknown(monkeypatch) -> None:
    stored_purpose: list[str] = []
    stored_empty: list[list[dict]] = []

    class DummySession:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(pipeline, "load_cached_gmail_parse_records", lambda **kwargs: None)
    monkeypatch.setattr(pipeline, "load_cached_gmail_purpose_mode", lambda **kwargs: None)
    monkeypatch.setattr(
        pipeline,
        "classify_gmail_message_fast_path",
        lambda **kwargs: GmailPurposeFastPathDecision(
            mode="unknown",
            reason_code="newsletter_digest",
            evidence="digest",
            classifier_version=GMAIL_PURPOSE_CLASSIFIER_VERSION,
            message_fingerprint="fp-3",
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "store_cached_gmail_purpose_mode",
        lambda **kwargs: stored_purpose.append(kwargs["mode"]),
    )
    monkeypatch.setattr(
        pipeline,
        "store_cached_gmail_parse_records",
        lambda **kwargs: stored_empty.append(kwargs["records"]),
    )
    monkeypatch.setattr(pipeline, "increment_parse_metric_counter", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        pipeline,
        "parse_gmail_payload",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("parser should not run on deterministic fast path")),
    )

    records = pipeline._parse_single_gmail_message(
        session_factory=(lambda: DummySession()),
        redis_client=object(),  # type: ignore[arg-type]
        stream_key="llm:parse:stream",
        source_id=1,
        provider="gmail",
        request_id="req-gmail-fast-path",
        payload_item={"message_id": "fast-path"},
    )

    assert records == []
    assert stored_purpose == ["unknown"]
    assert stored_empty == [[]]
