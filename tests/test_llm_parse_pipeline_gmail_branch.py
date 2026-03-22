from __future__ import annotations

from types import SimpleNamespace

from app.modules.runtime.connectors.llm_parsers.contracts import LlmParseError
from app.db.models.runtime import ConnectorResultStatus
from app.modules.runtime.llm import parse_pipeline as pipeline


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
