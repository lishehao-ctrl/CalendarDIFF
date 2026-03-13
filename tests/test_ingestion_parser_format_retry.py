from __future__ import annotations

from dataclasses import dataclass, field

import pytest

import app.modules.ingestion.llm_parsers.calendar_parser as calendar_parser
import app.modules.ingestion.llm_parsers.gmail_parser as gmail_parser
from app.modules.core_ingest.payload_contracts import validate_gmail_directive_payload, validate_gmail_payload
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
                    "message_id": "msg-1",
                    "mode": "segmented",
                    "segment_array": [
                        {
                            "segment_index": 0,
                            "anchor": "line-1",
                            "snippet": "Homework due at 11:59pm",
                            "segment_type_hint": "atomic",
                        }
                    ],
                }
            )
        if calls["count"] == 2:
            return DummyInvokeResult(
                json_object={
                    "semantic_event_draft": {
                        "course_dept": "CSE",
                        "course_number": "bad",
                        "course_suffix": "A",
                        "course_quarter": "WI",
                        "course_year2": 26,
                        "raw_type": "Homework",
                        "event_name": "HW1",
                        "ordinal": 1,
                        "due_date": "2026-03-05",
                        "due_time": "23:59:00",
                        "time_precision": "datetime",
                        "confidence": 0.9,
                        "evidence": "Homework due",
                    },
                    "link_signals": {
                        "keywords": [],
                        "exam_sequence": None,
                        "location_text": None,
                        "instructor_hint": "staff@example.edu",
                    },
                }
            )
        return DummyInvokeResult(
            json_object={
                "semantic_event_draft": {
                    "course_dept": "CSE",
                    "course_number": 8,
                    "course_suffix": "A",
                    "course_quarter": "WI",
                    "course_year2": 26,
                    "raw_type": "Homework",
                    "event_name": "HW1",
                    "ordinal": 1,
                    "due_date": "2026-03-05",
                    "due_time": "23:59:00",
                    "time_precision": "datetime",
                    "confidence": 0.9,
                    "evidence": "Homework due",
                },
                "link_signals": {
                    "keywords": [],
                    "exam_sequence": None,
                    "location_text": None,
                    "instructor_hint": "staff@example.edu",
                },
            }
        )

    monkeypatch.setattr(gmail_parser, "invoke_llm_json", fake_invoke_llm_json)
    parsed = gmail_parser.parse_gmail_payload(db=None, payload=payload, context=context)  # type: ignore[arg-type]

    assert calls["count"] == 3
    assert parsed.parser_name == "gmail_llm"
    assert len(parsed.records) == 1
    assert parsed.records[0]["record_type"] == "gmail.message.extracted"
    parsed_payload = parsed.records[0]["payload"]
    assert set(parsed_payload.keys()) == {"message_id", "source_facts", "semantic_event_draft", "link_signals"}
    assert parsed_payload["semantic_event_draft"]["course_dept"] == "CSE"


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
                    "semantic_event_draft": {
                        "course_dept": "CSE",
                        "course_number": "bad",
                        "course_suffix": "A",
                        "course_quarter": None,
                        "course_year2": None,
                        "raw_type": "Lab",
                        "event_name": "CSE 8A Lab",
                        "ordinal": 1,
                        "due_date": "2026-03-05",
                        "due_time": "18:00:00",
                        "time_precision": "datetime",
                        "confidence": 0.8,
                        "evidence": "Lab",
                    },
                    "link_signals": {
                        "keywords": [],
                        "exam_sequence": None,
                        "location_text": None,
                        "instructor_hint": None,
                    }
                }
            )
        return DummyInvokeResult(
            json_object={
                "semantic_event_draft": {
                    "course_dept": "CSE",
                    "course_number": 8,
                    "course_suffix": "A",
                    "course_quarter": None,
                    "course_year2": None,
                    "raw_type": "Lab",
                    "event_name": "CSE 8A Lab",
                    "ordinal": 1,
                    "due_date": "2026-03-05",
                    "due_time": "18:00:00",
                    "time_precision": "datetime",
                    "confidence": 0.8,
                    "evidence": "Lab",
                },
                "link_signals": {
                    "keywords": [],
                    "exam_sequence": None,
                    "location_text": None,
                    "instructor_hint": None,
                },
            }
        )

    monkeypatch.setattr(calendar_parser, "invoke_llm_json", fake_invoke_llm_json)
    parsed = calendar_parser.parse_calendar_content(db=None, content=content, context=context)  # type: ignore[arg-type]

    assert calls["count"] == 2
    assert parsed.parser_name == "calendar_deterministic"
    assert len(parsed.records) == 1
    assert parsed.records[0]["record_type"] == "calendar.event.extracted"
    payload = parsed.records[0]["payload"]
    assert isinstance(payload.get("source_facts"), dict)
    assert isinstance(payload.get("semantic_event_draft"), dict)
    assert payload["semantic_event_draft"]["course_dept"] == "CSE"


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
        if calls["count"] == 1:
            return DummyInvokeResult(
                json_object={
                    "message_id": "msg-2",
                    "mode": "segmented",
                    "segment_array": [
                        {
                            "segment_index": 0,
                            "anchor": "line-1",
                            "snippet": "Exam is on Friday",
                            "segment_type_hint": "atomic",
                        }
                    ],
                }
            )
        return DummyInvokeResult(
            json_object={
                "semantic_event_draft": {
                    "course_dept": "CSE",
                    "course_number": "bad",
                },
                "link_signals": {
                    "keywords": ["exam"],
                    "exam_sequence": 1,
                    "location_text": None,
                    "instructor_hint": None,
                },
            }
        )

    monkeypatch.setattr(gmail_parser, "invoke_llm_json", always_bad_invoke)
    with pytest.raises(LlmParseError) as exc_info:
        gmail_parser.parse_gmail_payload(db=None, payload=payload, context=context)  # type: ignore[arg-type]

    assert calls["count"] == LLM_FORMAT_MAX_ATTEMPTS + 1
    assert exc_info.value.code == "parse_llm_gmail_schema_invalid"


def test_gmail_parser_multi_atomic_segments_fan_out_and_keep_payload_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "message_id": "msg-multi",
        "subject": "HW updates",
        "body_text": "HW1 moved; Please update your planner; HW5 moved",
        "snippet": "HW updates",
        "from_header": "staff@example.edu",
        "internal_date": "2026-03-01T09:00:00-08:00",
        "thread_id": "thr-1",
        "label_ids": [],
    }
    context = ParserContext(source_id=9, provider="gmail", source_kind="email", request_id="req-gmail-multi")
    calls = {"count": 0}

    def fake_invoke_llm_json(db, *, invoke_request):  # type: ignore[no-untyped-def]
        del db
        calls["count"] += 1
        if invoke_request.task_name == "gmail_message_segment_plan":
            return DummyInvokeResult(
                json_object={
                    "message_id": "msg-multi",
                    "mode": "segmented",
                    "segment_array": [
                        {
                            "segment_index": 0,
                            "anchor": "s0",
                            "snippet": "HW1 moved to Friday",
                            "segment_type_hint": "atomic",
                        },
                        {
                            "segment_index": 1,
                            "anchor": "s1",
                            "snippet": "Please update your planner",
                            "segment_type_hint": "directive",
                        },
                        {
                            "segment_index": 2,
                            "anchor": "s2",
                            "snippet": "HW5 moved to next Monday",
                            "segment_type_hint": "atomic",
                        },
                    ],
                }
            )
        if invoke_request.task_name == "gmail_segment_atomic_extract" and invoke_request.user_payload.get("segment", {}).get("segment_index") == 0:
            return DummyInvokeResult(
                json_object={
                    "semantic_event_draft": {
                        "course_dept": "CSE",
                        "course_number": 8,
                        "course_suffix": "A",
                        "course_quarter": "WI",
                        "course_year2": 26,
                        "raw_type": "Homework",
                        "event_name": "HW1",
                        "ordinal": 1,
                        "due_date": "2026-03-05",
                        "due_time": "23:59:00",
                        "time_precision": "datetime",
                        "confidence": 0.9,
                        "evidence": "HW1 moved",
                    },
                    "link_signals": {
                        "keywords": [],
                        "exam_sequence": None,
                        "location_text": None,
                        "instructor_hint": "staff@example.edu",
                    },
                }
            )
        if invoke_request.task_name == "gmail_segment_directive_extract":
            return DummyInvokeResult(
                json_object={
                    "selector": {
                        "course_dept": "CSE",
                        "course_number": 8,
                        "course_suffix": "A",
                        "course_quarter": "WI",
                        "course_year2": 26,
                        "family_hint": "Homework",
                        "raw_type_hint": "Homework",
                        "scope_mode": "ordinal_list",
                        "ordinal_list": [3],
                        "ordinal_range_start": None,
                        "ordinal_range_end": None,
                        "current_due_weekday": None,
                        "applies_to_future_only": True,
                    },
                    "mutation": {
                        "move_weekday": "friday",
                        "set_due_date": None,
                    },
                    "confidence": 0.84,
                    "evidence": "please shift homework schedules",
                }
            )
        return DummyInvokeResult(
            json_object={
                "semantic_event_draft": {
                    "course_dept": "CSE",
                    "course_number": 8,
                    "course_suffix": "A",
                    "course_quarter": "WI",
                    "course_year2": 26,
                    "raw_type": "Homework",
                    "event_name": "HW5",
                    "ordinal": 5,
                    "due_date": "2026-03-10",
                    "due_time": "23:59:00",
                    "time_precision": "datetime",
                    "confidence": 0.9,
                    "evidence": "HW5 moved",
                },
                "link_signals": {
                    "keywords": [],
                    "exam_sequence": None,
                    "location_text": None,
                    "instructor_hint": "staff@example.edu",
                },
            }
        )

    monkeypatch.setattr(gmail_parser, "invoke_llm_json", fake_invoke_llm_json)
    parsed = gmail_parser.parse_gmail_payload(db=None, payload=payload, context=context)  # type: ignore[arg-type]

    assert calls["count"] == 4
    assert len(parsed.records) == 3
    assert parsed.records[0]["record_type"] == "gmail.message.extracted"
    assert parsed.records[1]["record_type"] == "gmail.message.extracted"
    assert parsed.records[2]["record_type"] == "gmail.directive.extracted"
    ids = [record["payload"]["message_id"] for record in parsed.records]
    assert ids == ["msg-multi#seg-0", "msg-multi#seg-2", "msg-multi"]
    for index, record in enumerate(parsed.records):
        record_payload = record.get("payload")
        assert isinstance(record_payload, dict)
        if record["record_type"] == "gmail.message.extracted":
            validate_gmail_payload(payload=record_payload, record_index=index)
        else:
            validate_gmail_directive_payload(payload=record_payload, record_index=index)


def test_gmail_parser_directive_segment_emits_directive_record(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "message_id": "msg-directive",
        "subject": "Policy update",
        "body_text": "Please check your inbox and review course policy changes.",
        "snippet": "Policy update",
        "from_header": "staff@example.edu",
        "internal_date": "2026-03-01T09:00:00-08:00",
        "thread_id": "thr-2",
        "label_ids": [],
    }
    context = ParserContext(source_id=10, provider="gmail", source_kind="email", request_id="req-gmail-directive")
    calls = {"count": 0}

    def fake_invoke_llm_json(db, *, invoke_request):  # type: ignore[no-untyped-def]
        del db
        calls["count"] += 1
        if invoke_request.task_name == "gmail_message_segment_plan":
            return DummyInvokeResult(
                json_object={
                    "message_id": "msg-directive",
                    "mode": "segmented",
                    "segment_array": [
                        {
                            "segment_index": 0,
                            "anchor": "s0",
                            "snippet": "Please move HWs to Friday",
                            "segment_type_hint": "directive",
                        },
                        {
                            "segment_index": 1,
                            "anchor": "s1",
                            "snippet": "General policy changes",
                            "segment_type_hint": "unknown",
                        },
                    ],
                }
            )
        assert invoke_request.task_name == "gmail_segment_directive_extract"
        return DummyInvokeResult(
            json_object={
                "selector": {
                    "course_dept": "CSE",
                    "course_number": 8,
                    "course_suffix": "A",
                    "course_quarter": "WI",
                    "course_year2": 26,
                    "family_hint": "Homework",
                    "raw_type_hint": "Homework",
                    "scope_mode": "all_matching",
                    "ordinal_list": [],
                    "ordinal_range_start": None,
                    "ordinal_range_end": None,
                    "current_due_weekday": None,
                    "applies_to_future_only": False,
                },
                "mutation": {
                    "move_weekday": "friday",
                    "set_due_date": None,
                },
                "confidence": 0.8,
                "evidence": "move all homeworks to Friday",
            }
        )

    monkeypatch.setattr(gmail_parser, "invoke_llm_json", fake_invoke_llm_json)
    parsed = gmail_parser.parse_gmail_payload(db=None, payload=payload, context=context)  # type: ignore[arg-type]

    assert calls["count"] == 2
    assert len(parsed.records) == 1
    assert parsed.records[0]["record_type"] == "gmail.directive.extracted"
    directive_payload = parsed.records[0]["payload"]
    assert isinstance(directive_payload, dict)
    validate_gmail_directive_payload(payload=directive_payload, record_index=0)


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
                "semantic_event_draft": {
                    "course_dept": "CSE",
                    "course_number": "bad",
                    "raw_type": "Project",
                    "event_name": "Project update",
                    "ordinal": 1,
                    "due_date": "2026-03-10",
                    "due_time": "18:00:00",
                    "time_precision": "datetime",
                    "confidence": 0.8,
                    "evidence": "Project update",
                },
                "link_signals": {
                    "keywords": [],
                    "exam_sequence": None,
                    "location_text": None,
                    "instructor_hint": None,
                },
            }
        )

    monkeypatch.setattr(calendar_parser, "invoke_llm_json", always_bad_invoke)
    with pytest.raises(LlmParseError) as exc_info:
        calendar_parser.parse_calendar_content(db=None, content=content, context=context)  # type: ignore[arg-type]

    assert calls["count"] == LLM_FORMAT_MAX_ATTEMPTS
    assert exc_info.value.code == "parse_llm_calendar_schema_invalid"
