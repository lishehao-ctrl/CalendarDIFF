from __future__ import annotations

import base64

from app.modules.runtime.connectors.llm_parsers.contracts import LlmParseError, ParserContext
from app.modules.runtime.llm import parse_pipeline as pipeline


class DummyParserOutput:
    def __init__(self, records):
        self.records = records
        self.parser_name = "calendar_deterministic"
        self.parser_version = "mainline"
        self.model_hint = "test-model"


def test_parse_calendar_changed_component_with_llm_uses_cache_hit(monkeypatch) -> None:
    component = pipeline.CalendarChangedComponentInput(
        component_key="evt-1#",
        external_event_id="evt-1",
        component_ical_b64=base64.b64encode(b"BEGIN:VEVENT\nUID:evt-1\nEND:VEVENT").decode("ascii"),
        fingerprint="fp-evt-1",
    )
    context = ParserContext(source_id=1, provider="ics", source_kind="calendar", request_id="req-cache-hit")

    monkeypatch.setattr(
        pipeline,
        "load_cached_calendar_component_records",
        lambda **kwargs: [{"record_type": "calendar.event.extracted", "payload": {"component_key": "evt-1#"}}],
    )
    monkeypatch.setattr(pipeline, "increment_parse_metric_counter", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        pipeline,
        "parse_calendar_content",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("calendar parser should not run on cache hit")),
    )

    records = pipeline.parse_calendar_changed_component_with_llm(
        db=object(),  # type: ignore[arg-type]
        redis_client=object(),  # type: ignore[arg-type]
        stream_key="llm:parse:stream",
        provider="ics",
        context=context,
        component=component,
    )

    assert records == [{"record_type": "calendar.event.extracted", "payload": {"component_key": "evt-1#"}}]


def test_parse_calendar_changed_component_with_llm_stores_non_retryable_skip(monkeypatch) -> None:
    component = pipeline.CalendarChangedComponentInput(
        component_key="evt-2#",
        external_event_id="evt-2",
        component_ical_b64=base64.b64encode(b"BEGIN:VEVENT\nUID:evt-2\nEND:VEVENT").decode("ascii"),
        fingerprint="fp-evt-2",
    )
    context = ParserContext(source_id=1, provider="ics", source_kind="calendar", request_id="req-cache-skip")
    stored: list[tuple[str | None, str]] = []

    monkeypatch.setattr(pipeline, "load_cached_calendar_component_records", lambda **kwargs: None)
    monkeypatch.setattr(
        pipeline,
        "store_non_retryable_calendar_component_skip",
        lambda **kwargs: stored.append((kwargs["fingerprint"], kwargs["error_code"])),
    )
    monkeypatch.setattr(
        pipeline,
        "invoke_parser_with_limit",
        lambda **kwargs: kwargs["parse_call"](),
    )

    def fake_parse_calendar_content(*, db, content, context):  # noqa: ANN001
        del db, content, context
        raise LlmParseError(
            code="parse_llm_calendar_schema_invalid",
            message="bad schema",
            retryable=False,
            provider="ics",
        )

    monkeypatch.setattr(pipeline, "parse_calendar_content", fake_parse_calendar_content)

    try:
        pipeline.parse_calendar_changed_component_with_llm(
            db=object(),  # type: ignore[arg-type]
            redis_client=object(),  # type: ignore[arg-type]
            stream_key="llm:parse:stream",
            provider="ics",
            context=context,
            component=component,
        )
    except LlmParseError as exc:
        assert exc.code == "parse_llm_calendar_schema_invalid"
    else:
        raise AssertionError("expected non-retryable calendar parse error")

    assert stored == [("fp-evt-2", "parse_llm_calendar_schema_invalid")]
