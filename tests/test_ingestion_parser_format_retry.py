from __future__ import annotations

from dataclasses import dataclass, field

import pytest

import app.modules.ingestion.llm_parsers.calendar_v2 as calendar_parser
import app.modules.ingestion.llm_parsers.gmail_v2 as gmail_parser
from app.modules.ingestion.llm_parsers.contracts import LlmParseError, ParserContext
from app.modules.llm_gateway.retry_policy import LLM_FORMAT_MAX_ATTEMPTS


@dataclass
class DummyInvokeResult:
    json_object: dict
    model: str = "test-model"
    provider_id: str = "env-default"
    api_mode: str = "chat_completions"
    latency_ms: int = 1
    upstream_request_id: str | None = None
    raw_usage: dict = field(default_factory=dict)


def test_gmail_parser_retries_validation_error_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "message_id": "msg-1",
        "subject": "HW due update",
        "body_text": "Homework due at 11:59pm",
        "snippet": "Homework due update",
        "from_header": "staff@example.edu",
        "internal_date": "2026-03-01T09:00:00-08:00",
        "label_ids": [],
    }
    context = ParserContext(source_id=1, provider="gmail", source_kind="email", request_id="req-gmail-1")
    calls = {"count": 0}

    def fake_invoke_llm_json(db, *, invoke_request):  # type: ignore[no-untyped-def]
        del db, invoke_request
        calls["count"] += 1
        if calls["count"] == 1:
            return DummyInvokeResult(
                json_object={
                    "messages": [
                        {
                            "message_id": "msg-1",
                            "subject": "HW due update",
                            "event_type": "assignment",
                            "due_at": "2026-03-05T23:59:00-08:00",
                            "confidence": 0.9,
                            "raw_extract": {"deadline_text": "Mar 5 11:59pm"},
                            "course_parse": "bad",
                        }
                    ]
                }
            )
        return DummyInvokeResult(
            json_object={
                "messages": [
                    {
                        "message_id": "msg-1",
                        "subject": "HW due update",
                        "event_type": "assignment",
                        "due_at": "2026-03-05T23:59:00-08:00",
                        "confidence": 0.9,
                        "raw_extract": {"deadline_text": "Mar 5 11:59pm"},
                        "course_parse": {
                            "dept": "CSE",
                            "number": 8,
                            "suffix": "A",
                            "quarter": "WI",
                            "year2": 26,
                            "confidence": 0.8,
                            "evidence": "CSE 8A WI26",
                        },
                    }
                ]
            }
        )

    monkeypatch.setattr(gmail_parser, "invoke_llm_json", fake_invoke_llm_json)
    parsed = gmail_parser.parse_gmail_payload(db=None, payload=payload, context=context)  # type: ignore[arg-type]

    assert calls["count"] == 2
    assert parsed.parser_name == "gmail_v2_llm"
    assert len(parsed.records) == 1
    assert parsed.records[0]["record_type"] == "gmail.message.extracted"


def test_calendar_parser_retries_validation_error_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    content = (
        b"BEGIN:VCALENDAR\n"
        b"VERSION:2.0\n"
        b"BEGIN:VEVENT\n"
        b"UID:uid-1\n"
        b"DTSTART:20260305T180000Z\n"
        b"DTEND:20260305T190000Z\n"
        b"SUMMARY:CSE 8A Lab\n"
        b"END:VEVENT\n"
        b"END:VCALENDAR\n"
    )
    context = ParserContext(source_id=2, provider="ics", source_kind="calendar", request_id="req-cal-1")
    calls = {"count": 0}

    def fake_invoke_llm_json(db, *, invoke_request):  # type: ignore[no-untyped-def]
        del db, invoke_request
        calls["count"] += 1
        if calls["count"] == 1:
            return DummyInvokeResult(
                json_object={
                    "course_parse": {
                        "dept": "CSE",
                        "number": "bad",
                        "suffix": "A",
                        "quarter": None,
                        "year2": None,
                        "confidence": 0.9,
                        "evidence": "CSE 8A",
                    }
                }
            )
        return DummyInvokeResult(
            json_object={
                "course_parse": {
                    "dept": "CSE",
                    "number": 8,
                    "suffix": "A",
                    "quarter": None,
                    "year2": None,
                    "confidence": 0.9,
                    "evidence": "CSE 8A",
                }
            }
        )

    monkeypatch.setattr(calendar_parser, "invoke_llm_json", fake_invoke_llm_json)
    parsed = calendar_parser.parse_calendar_content(db=None, content=content, context=context)  # type: ignore[arg-type]

    assert calls["count"] == 2
    assert parsed.parser_name == "calendar_v2_deterministic"
    assert len(parsed.records) == 1
    assert parsed.records[0]["record_type"] == "calendar.event.extracted"
    payload = parsed.records[0]["payload"]
    assert isinstance(payload.get("source_canonical"), dict)
    assert isinstance(payload.get("enrichment"), dict)
    assert payload["enrichment"]["course_parse"]["dept"] == "CSE"


def test_gmail_parser_exhausts_validation_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "message_id": "msg-2",
        "subject": "Exam reminder",
        "body_text": "Exam is on Friday",
        "snippet": "Exam is on Friday",
        "from_header": "staff@example.edu",
        "internal_date": "2026-03-01T09:00:00-08:00",
        "label_ids": [],
    }
    context = ParserContext(source_id=3, provider="gmail", source_kind="email", request_id="req-gmail-2")
    calls = {"count": 0}

    def always_bad_invoke(db, *, invoke_request):  # type: ignore[no-untyped-def]
        del db, invoke_request
        calls["count"] += 1
        return DummyInvokeResult(
            json_object={
                "messages": [
                    {
                        "message_id": "msg-2",
                        "subject": "Exam reminder",
                        "event_type": "exam",
                        "due_at": None,
                        "confidence": 0.8,
                        "raw_extract": {"snippet": "Exam reminder"},
                        "course_parse": "still-not-object",
                    }
                ]
            }
        )

    monkeypatch.setattr(gmail_parser, "invoke_llm_json", always_bad_invoke)
    with pytest.raises(LlmParseError) as exc_info:
        gmail_parser.parse_gmail_payload(db=None, payload=payload, context=context)  # type: ignore[arg-type]

    assert calls["count"] == LLM_FORMAT_MAX_ATTEMPTS
    assert exc_info.value.code == "parse_llm_gmail_schema_invalid"


def test_calendar_parser_exhausts_validation_retries_raises_schema_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = (
        b"BEGIN:VCALENDAR\n"
        b"VERSION:2.0\n"
        b"BEGIN:VEVENT\n"
        b"UID:uid-2\n"
        b"DTSTART:20260310T180000Z\n"
        b"DTEND:20260310T190000Z\n"
        b"SUMMARY:Project update\n"
        b"END:VEVENT\n"
        b"END:VCALENDAR\n"
    )
    context = ParserContext(source_id=4, provider="ics", source_kind="calendar", request_id="req-cal-2")
    calls = {"count": 0}

    def always_bad_invoke(db, *, invoke_request):  # type: ignore[no-untyped-def]
        del db, invoke_request
        calls["count"] += 1
        return DummyInvokeResult(
            json_object={
                "course_parse": {
                    "dept": "CSE",
                    "number": "bad",
                    "suffix": None,
                    "quarter": None,
                    "year2": None,
                    "confidence": 0.7,
                    "evidence": "Project",
                }
            }
        )

    monkeypatch.setattr(calendar_parser, "invoke_llm_json", always_bad_invoke)
    with pytest.raises(LlmParseError) as exc_info:
        calendar_parser.parse_calendar_content(db=None, content=content, context=context)  # type: ignore[arg-type]

    assert calls["count"] == LLM_FORMAT_MAX_ATTEMPTS
    assert exc_info.value.code == "parse_llm_calendar_schema_invalid"
