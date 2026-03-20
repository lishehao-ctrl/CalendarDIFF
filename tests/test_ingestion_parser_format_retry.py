from __future__ import annotations

from dataclasses import dataclass, field

import pytest

import app.modules.runtime.connectors.llm_parsers.calendar_parser as calendar_parser
import app.modules.runtime.connectors.llm_parsers.gmail_parser as gmail_parser
import app.modules.runtime.connectors.llm_parsers.semantic_orchestrator as semantic_orchestrator
from app.modules.runtime.apply.payload_contracts import validate_gmail_directive_payload, validate_gmail_payload
from app.modules.runtime.connectors.llm_parsers.contracts import LlmParseError, ParserContext
from app.modules.llm_gateway.retry_policy import LLM_FORMAT_MAX_ATTEMPTS


@dataclass
class DummyInvokeResult:
    json_object: dict
    model: str = "test-model"
    provider_id: str = "env-default"
    api_mode: str = "responses"
    latency_ms: int = 1
    response_id: str | None = "resp-test"
    upstream_request_id: str | None = None
    raw_usage: dict = field(default_factory=dict)


def test_gmail_parser_retries_atomic_validation_error_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "message_id": "msg-1",
        "subject": "HW due update",
        "body_text": "Homework 1 due at 11:59pm.",
        "snippet": "Homework due update",
        "from_header": "staff@example.edu",
        "thread_id": "thr-1",
        "internal_date": "2026-03-01T09:00:00-08:00",
        "label_ids": [],
    }
    context = ParserContext(source_id=1, provider="gmail", source_kind="email", request_id="req-gmail-1")
    calls = {"count": 0}

    def fake_invoke_llm_json(db, *, invoke_request):  # type: ignore[no-untyped-def]
        del db
        calls["count"] += 1
        if invoke_request.task_name == "gmail_purpose_mode_classify":
            return DummyInvokeResult(json_object={"mode": "atomic", "evidence": "single homework update"})
        if invoke_request.task_name == "gmail_atomic_identity_extract" and calls["count"] == 2:
            return DummyInvokeResult(
                json_object={
                    "outcome": "event",
                    "semantic_identity_draft": {
                        "course_dept": "CSE",
                        "course_number": "bad",
                        "course_suffix": "A",
                        "course_quarter": "WI",
                        "course_year2": 26,
                        "raw_type": "Homework",
                        "event_name": "HW1",
                        "ordinal": 1,
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
        if invoke_request.task_name == "gmail_atomic_identity_extract":
            return DummyInvokeResult(
                json_object={
                    "outcome": "event",
                    "semantic_identity_draft": {
                        "course_dept": "CSE",
                        "course_number": 8,
                        "course_suffix": "A",
                        "course_quarter": "WI",
                        "course_year2": 26,
                        "raw_type": "Homework",
                        "event_name": "HW1",
                        "ordinal": 1,
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
        assert invoke_request.task_name == "gmail_atomic_time_resolve"
        return DummyInvokeResult(
            json_object={
                "outcome": "resolved",
                "source_time_phrase": "due at 11:59pm",
                "resolved_due_date": "2026-03-05",
                "resolved_due_time": "23:59:00",
                "time_precision": "datetime",
                "resolution_basis": "explicit_due_phrase",
                "confidence": 0.9,
                "evidence": "Homework due",
            }
        )

    monkeypatch.setattr(semantic_orchestrator, "invoke_llm_json", fake_invoke_llm_json)
    parsed = gmail_parser.parse_gmail_payload(db=None, payload=payload, context=context)  # type: ignore[arg-type]

    assert calls["count"] == 4
    assert parsed.parser_name == "gmail_llm"
    assert len(parsed.records) == 1
    assert parsed.records[0]["record_type"] == "gmail.message.extracted"
    parsed_payload = parsed.records[0]["payload"]
    assert set(parsed_payload.keys()) == {"message_id", "source_facts", "semantic_event_draft", "link_signals"}
    assert parsed_payload["semantic_event_draft"]["course_dept"] == "CSE"
    validate_gmail_payload(payload=parsed_payload, record_index=0)


def test_calendar_parser_retries_validation_error_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    content = (
        b"BEGIN:VCALENDAR\n"
        b"VERSION:2.0\n"
        b"BEGIN:VEVENT\n"
        b"UID:uid-1\n"
        b"DTSTART:20260305T180000Z\n"
        b"DTEND:20260305T190000Z\n"
        b"SUMMARY:CSE 8A Homework 1\n"
        b"END:VEVENT\n"
        b"END:VCALENDAR\n"
    )
    context = ParserContext(source_id=2, provider="ics", source_kind="calendar", request_id="req-cal-1")
    calls = {"count": 0}

    def fake_invoke_llm_json(db, *, invoke_request):  # type: ignore[no-untyped-def]
        del db
        calls["count"] += 1
        if invoke_request.task_name == "calendar_purpose_relevance":
            return DummyInvokeResult(json_object={"outcome": "relevant"})
        if calls["count"] == 2:
            return DummyInvokeResult(
                json_object={
                    "course_dept": "CSE",
                    "course_number": "bad",
                    "course_suffix": "A",
                    "course_quarter": None,
                    "course_year2": None,
                    "raw_type": "Homework",
                    "event_name": "Homework 1",
                    "ordinal": 1,
                    "confidence": 0.8,
                    "evidence": "Homework 1",
                }
            )
        return DummyInvokeResult(
            json_object={
                "course_dept": "CSE",
                "course_number": 8,
                "course_suffix": "A",
                "course_quarter": None,
                "course_year2": None,
                "raw_type": "Homework",
                "event_name": "Homework 1",
                "ordinal": 1,
                "confidence": 0.8,
                "evidence": "Homework 1",
            }
        )

    monkeypatch.setattr(semantic_orchestrator, "invoke_llm_json", fake_invoke_llm_json)
    parsed = calendar_parser.parse_calendar_content(db=None, content=content, context=context)  # type: ignore[arg-type]

    assert calls["count"] == 3
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
        "thread_id": "thr-2",
        "internal_date": "2026-03-01T09:00:00-08:00",
        "label_ids": [],
    }
    context = ParserContext(source_id=3, provider="gmail", source_kind="email", request_id="req-gmail-2")
    calls = {"count": 0}

    def always_bad_invoke(db, *, invoke_request):  # type: ignore[no-untyped-def]
        del db
        calls["count"] += 1
        if invoke_request.task_name == "gmail_purpose_mode_classify":
            return DummyInvokeResult(json_object={"mode": "atomic", "evidence": "single exam event"})
        assert invoke_request.task_name == "gmail_atomic_identity_extract"
        return DummyInvokeResult(
            json_object={
                "outcome": "event",
                "semantic_identity_draft": {
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

    monkeypatch.setattr(semantic_orchestrator, "invoke_llm_json", always_bad_invoke)
    with pytest.raises(LlmParseError) as exc_info:
        gmail_parser.parse_gmail_payload(db=None, payload=payload, context=context)  # type: ignore[arg-type]

    assert calls["count"] == LLM_FORMAT_MAX_ATTEMPTS + 1
    assert exc_info.value.code == "parse_llm_gmail_schema_invalid"


def test_gmail_parser_directive_emits_directive_record(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "message_id": "msg-directive",
        "subject": "Move all homeworks to Friday",
        "body_text": "Please move all homeworks to Friday.",
        "snippet": "Move all homeworks to Friday",
        "from_header": "staff@example.edu",
        "thread_id": "thr-3",
        "internal_date": "2026-03-01T09:00:00-08:00",
        "label_ids": [],
    }
    context = ParserContext(source_id=10, provider="gmail", source_kind="email", request_id="req-gmail-directive")
    calls = {"count": 0}

    def fake_invoke_llm_json(db, *, invoke_request):  # type: ignore[no-untyped-def]
        del db
        calls["count"] += 1
        if invoke_request.task_name == "gmail_purpose_mode_classify":
            return DummyInvokeResult(json_object={"mode": "directive", "evidence": "bulk mutation"})
        return DummyInvokeResult(
            json_object={
                "outcome": "directive",
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

    monkeypatch.setattr(semantic_orchestrator, "invoke_llm_json", fake_invoke_llm_json)
    parsed = gmail_parser.parse_gmail_payload(db=None, payload=payload, context=context)  # type: ignore[arg-type]

    assert calls["count"] == 2
    assert len(parsed.records) == 1
    assert parsed.records[0]["record_type"] == "gmail.directive.extracted"
    directive_payload = parsed.records[0]["payload"]
    assert isinstance(directive_payload, dict)
    validate_gmail_directive_payload(payload=directive_payload, record_index=0)


def test_gmail_parser_unknown_mode_emits_no_records(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "message_id": "msg-nonrelevant",
        "subject": "Campus newsletter",
        "body_text": "General admin updates.",
        "snippet": "newsletter",
        "from_header": "staff@example.edu",
        "thread_id": "thr-4",
        "internal_date": "2026-03-01T09:00:00-08:00",
        "label_ids": [],
    }
    context = ParserContext(source_id=11, provider="gmail", source_kind="email", request_id="req-gmail-nonrelevant")
    calls = {"count": 0}

    def fake_invoke_llm_json(db, *, invoke_request):  # type: ignore[no-untyped-def]
        del db
        calls["count"] += 1
        return DummyInvokeResult(json_object={"mode": "unknown", "evidence": "not coursework"})

    monkeypatch.setattr(semantic_orchestrator, "invoke_llm_json", fake_invoke_llm_json)
    parsed = gmail_parser.parse_gmail_payload(db=None, payload=payload, context=context)  # type: ignore[arg-type]

    assert calls["count"] == 1
    assert parsed.records == []


def test_gmail_parser_unknown_mode_accepts_minimal_unknown_json(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "message_id": "msg-min-unknown",
        "subject": "Daily digest",
        "body_text": "Multiple unrelated topics.",
        "snippet": "digest",
        "from_header": "staff@example.edu",
        "thread_id": "thr-unknown",
        "internal_date": "2026-03-01T09:00:00-08:00",
        "label_ids": [],
    }
    context = ParserContext(source_id=12, provider="gmail", source_kind="email", request_id="req-gmail-min-unknown")

    def fake_invoke_llm_json(db, *, invoke_request):  # type: ignore[no-untyped-def]
        del db
        assert invoke_request.task_name == "gmail_purpose_mode_classify"
        return DummyInvokeResult(json_object={"mode": "unknown", "evidence": ""})

    monkeypatch.setattr(semantic_orchestrator, "invoke_llm_json", fake_invoke_llm_json)
    parsed = gmail_parser.parse_gmail_payload(db=None, payload=payload, context=context)  # type: ignore[arg-type]

    assert parsed.records == []


def test_gmail_atomic_extract_can_represent_exam_notice_as_atomic_not_directive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "message_id": "msg-exam-info",
        "subject": "Final exam information",
        "body_text": "The final exam is Wednesday at 7 PM in York Hall 2722.",
        "snippet": "final exam info",
        "from_header": "staff@example.edu",
        "thread_id": "thr-exam",
        "internal_date": "2026-03-14T17:46:42+00:00",
        "label_ids": [],
    }
    context = ParserContext(source_id=13, provider="gmail", source_kind="email", request_id="req-gmail-exam-info")
    calls = {"count": 0}

    def fake_invoke_llm_json(db, *, invoke_request):  # type: ignore[no-untyped-def]
        del db
        calls["count"] += 1
        if invoke_request.task_name == "gmail_purpose_mode_classify":
            return DummyInvokeResult(json_object={"mode": "atomic", "evidence": "single final exam event"})
        if invoke_request.task_name == "gmail_atomic_identity_extract":
            return DummyInvokeResult(
                json_object={
                    "outcome": "event",
                    "semantic_identity_draft": {
                        "course_dept": "CHEM",
                        "course_number": 11,
                        "course_suffix": None,
                        "course_quarter": "WI",
                        "course_year2": 26,
                        "raw_type": "final_exam",
                        "event_name": "Final Exam",
                        "ordinal": None,
                        "confidence": 0.95,
                        "evidence": "The final exam is Wednesday at 7 PM in York Hall 2722.",
                    },
                    "link_signals": {
                        "keywords": ["final"],
                        "exam_sequence": None,
                        "location_text": "York Hall 2722",
                        "instructor_hint": None,
                    },
                }
            )
        assert invoke_request.task_name == "gmail_atomic_time_resolve"
        return DummyInvokeResult(
            json_object={
                "outcome": "resolved",
                "source_time_phrase": "Wednesday at 7 PM",
                "resolved_due_date": "2026-03-18",
                "resolved_due_time": "19:00:00",
                "time_precision": "datetime",
                "resolution_basis": "weekday_relative_to_internal_date",
                "confidence": 0.95,
                "evidence": "The final exam is Wednesday at 7 PM in York Hall 2722.",
            }
        )

    monkeypatch.setattr(semantic_orchestrator, "invoke_llm_json", fake_invoke_llm_json)
    parsed = gmail_parser.parse_gmail_payload(db=None, payload=payload, context=context)  # type: ignore[arg-type]

    assert calls["count"] == 3
    assert len(parsed.records) == 1
    assert parsed.records[0]["record_type"] == "gmail.message.extracted"


def test_gmail_extract_reuses_message_cache_prefix_instead_of_previous_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "message_id": "msg-cache-shape",
        "subject": "Homework 2 due tonight",
        "body_text": "Homework 2 is due tonight at 11:59 PM for all sections.",
        "snippet": "Homework 2 due tonight",
        "from_header": "staff@example.edu",
        "thread_id": "thr-cache-shape",
        "internal_date": "2026-03-14T17:46:42+00:00",
        "label_ids": [],
    }
    context = ParserContext(source_id=14, provider="gmail", source_kind="email", request_id="req-gmail-cache-shape")
    observed: list[object] = []
    expected_prefix = semantic_orchestrator._build_gmail_cache_prefix(payload=payload)

    def fake_invoke_llm_json(db, *, invoke_request):  # type: ignore[no-untyped-def]
        del db
        observed.append(invoke_request)
        if invoke_request.task_name == "gmail_purpose_mode_classify":
            return DummyInvokeResult(json_object={"mode": "atomic", "evidence": "single homework event"})
        if invoke_request.task_name == "gmail_atomic_identity_extract":
            return DummyInvokeResult(
                json_object={
                    "outcome": "event",
                    "semantic_identity_draft": {
                        "course_dept": "CSE",
                        "course_number": 8,
                        "course_suffix": None,
                        "course_quarter": "WI",
                        "course_year2": 26,
                        "raw_type": "homework",
                        "event_name": "Homework 2",
                        "ordinal": 2,
                        "confidence": 0.9,
                        "evidence": "Homework 2 is due tonight at 11:59 PM for all sections.",
                    },
                    "link_signals": {
                        "keywords": [],
                        "exam_sequence": None,
                        "location_text": None,
                        "instructor_hint": None,
                    },
                }
            )
        return DummyInvokeResult(
            json_object={
                "outcome": "resolved",
                "source_time_phrase": "tonight at 11:59 PM",
                "resolved_due_date": "2026-03-14",
                "resolved_due_time": "23:59:00",
                "time_precision": "datetime",
                "resolution_basis": "relative_to_internal_date",
                "confidence": 0.9,
                "evidence": "Homework 2 is due tonight at 11:59 PM for all sections.",
            }
        )

    monkeypatch.setattr(semantic_orchestrator, "invoke_llm_json", fake_invoke_llm_json)
    parsed = gmail_parser.parse_gmail_payload(db=None, payload=payload, context=context)  # type: ignore[arg-type]

    assert len(parsed.records) == 1
    assert len(observed) == 3
    classify_request = observed[0]
    identity_request = observed[1]
    time_request = observed[2]
    assert classify_request.task_name == "gmail_purpose_mode_classify"
    assert identity_request.task_name == "gmail_atomic_identity_extract"
    assert time_request.task_name == "gmail_atomic_time_resolve"
    assert classify_request.cache_prefix_payload == {"cache_scope": "gmail_purpose_mode_classify:v2"}
    assert classify_request.cache_task_prompt is True
    assert classify_request.user_payload == {
        "purpose": "assignment_or_exam_monitoring",
        "message_context": expected_prefix,
    }
    assert identity_request.cache_prefix_payload == expected_prefix
    assert time_request.cache_prefix_payload == expected_prefix
    assert classify_request.previous_response_id is None
    assert identity_request.previous_response_id is None
    assert time_request.previous_response_id is None


def test_gmail_atomic_prefers_authoritative_body_alias_over_subject_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "message_id": "msg-authoritative-alias",
        "subject": "[CSE120] HW 26 posted",
        "body_text": (
            "Course: CSE120\n"
            "The current graded item signal is: Problem Set 26 is posted, and the working due time is this Monday at 11:59 PM.\n"
            "This applies to every enrolled section, but it still refers to one graded item."
        ),
        "snippet": "HW 26 posted",
        "from_header": "staff@example.edu",
        "thread_id": "thr-authoritative-alias",
        "internal_date": "2026-12-01T04:18:00+00:00",
        "label_ids": [],
    }
    context = ParserContext(source_id=18, provider="gmail", source_kind="email", request_id="req-gmail-authoritative-alias")

    def fake_invoke_llm_json(db, *, invoke_request):  # type: ignore[no-untyped-def]
        del db
        if invoke_request.task_name == "gmail_purpose_mode_classify":
            return DummyInvokeResult(json_object={"mode": "atomic", "evidence": "single monitored item"})
        if invoke_request.task_name == "gmail_atomic_identity_extract":
            return DummyInvokeResult(
                json_object={
                    "outcome": "event",
                    "semantic_identity_draft": {
                        "course_dept": "CSE",
                        "course_number": 120,
                        "course_suffix": None,
                        "course_quarter": "FA",
                        "course_year2": 26,
                        "raw_type": "Problem Set",
                        "event_name": "Problem Set 26",
                        "ordinal": 26,
                        "confidence": 0.95,
                        "evidence": "Problem Set 26 is posted, and the working due time is this Monday at 11:59 PM.",
                    },
                    "link_signals": {
                        "keywords": [],
                        "exam_sequence": None,
                        "location_text": None,
                        "instructor_hint": None,
                    },
                }
            )
        assert invoke_request.task_name == "gmail_atomic_time_resolve"
        return DummyInvokeResult(
            json_object={
                "outcome": "resolved",
                "source_time_phrase": "this Monday at 11:59 PM",
                "resolved_due_date": "2026-12-07",
                "resolved_due_time": "23:59:00",
                "time_precision": "datetime",
                "resolution_basis": "relative_to_internal_date",
                "confidence": 0.95,
                "evidence": "this Monday at 11:59 PM",
            }
        )

    monkeypatch.setattr(semantic_orchestrator, "invoke_llm_json", fake_invoke_llm_json)
    parsed = gmail_parser.parse_gmail_payload(db=None, payload=payload, context=context)  # type: ignore[arg-type]

    assert len(parsed.records) == 1
    parsed_payload = parsed.records[0]["payload"]
    semantic = parsed_payload["semantic_event_draft"]
    assert semantic["raw_type"] == "Problem Set"
    assert semantic["event_name"] == "Problem Set 26"
    assert semantic["ordinal"] == 26


def test_gmail_directive_unknown_falls_back_to_atomic_record(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "message_id": "msg-directive-fallback-unknown",
        "subject": "Project 2 deadline extension",
        "body_text": "Project 2 is now due Sunday at 11:59 PM for all sections.",
        "snippet": "Project 2 deadline extension",
        "from_header": "staff@example.edu",
        "thread_id": "thr-directive-fallback-unknown",
        "internal_date": "2026-07-19T12:00:00Z",
        "label_ids": [],
    }
    context = ParserContext(source_id=16, provider="gmail", source_kind="email", request_id="req-gmail-directive-fallback-unknown")
    calls: list[str] = []

    def fake_invoke_llm_json(db, *, invoke_request):  # type: ignore[no-untyped-def]
        del db
        calls.append(invoke_request.task_name)
        if invoke_request.task_name == "gmail_purpose_mode_classify":
            return DummyInvokeResult(json_object={"mode": "directive", "evidence": "broad audience project update"})
        if invoke_request.task_name == "gmail_directive_semantic_extract":
            return DummyInvokeResult(json_object={"outcome": "unknown"})
        if invoke_request.task_name == "gmail_atomic_identity_extract":
            return DummyInvokeResult(
                json_object={
                    "outcome": "event",
                    "semantic_identity_draft": {
                        "course_dept": "CSE",
                        "course_number": 30,
                        "course_suffix": None,
                        "course_quarter": "SU",
                        "course_year2": 26,
                        "raw_type": "Project",
                        "event_name": "Project 2",
                        "ordinal": 2,
                        "confidence": 0.95,
                        "evidence": "Project 2 is now due Sunday at 11:59 PM for all sections.",
                    },
                    "link_signals": {
                        "keywords": [],
                        "exam_sequence": None,
                        "location_text": None,
                        "instructor_hint": None,
                    },
                }
            )
        assert invoke_request.task_name == "gmail_atomic_time_resolve"
        return DummyInvokeResult(
            json_object={
                "outcome": "resolved",
                "source_time_phrase": "Sunday at 11:59 PM",
                "resolved_due_date": "2026-07-19",
                "resolved_due_time": "23:59:00",
                "time_precision": "datetime",
                "resolution_basis": "explicit_absolute_with_year_inferred",
                "confidence": 0.95,
                "evidence": "Project 2 is now due Sunday at 11:59 PM for all sections.",
            }
        )

    monkeypatch.setattr(semantic_orchestrator, "invoke_llm_json", fake_invoke_llm_json)
    parsed = gmail_parser.parse_gmail_payload(db=None, payload=payload, context=context)  # type: ignore[arg-type]

    assert calls == [
        "gmail_purpose_mode_classify",
        "gmail_directive_semantic_extract",
        "gmail_atomic_identity_extract",
        "gmail_atomic_time_resolve",
    ]
    assert len(parsed.records) == 1
    assert parsed.records[0]["record_type"] == "gmail.message.extracted"


def test_gmail_directive_schema_invalid_falls_back_to_atomic_record(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "message_id": "msg-directive-fallback-invalid",
        "subject": "Project 2 deadline extension",
        "body_text": "Project 2 is now due Sunday at 11:59 PM for all sections.",
        "snippet": "Project 2 deadline extension",
        "from_header": "staff@example.edu",
        "thread_id": "thr-directive-fallback-invalid",
        "internal_date": "2026-07-19T12:00:00Z",
        "label_ids": [],
    }
    context = ParserContext(source_id=17, provider="gmail", source_kind="email", request_id="req-gmail-directive-fallback-invalid")
    calls = {"classify": 0, "directive": 0, "atomic": 0}

    def fake_invoke_llm_json(db, *, invoke_request):  # type: ignore[no-untyped-def]
        del db
        if invoke_request.task_name == "gmail_purpose_mode_classify":
            calls["classify"] += 1
            return DummyInvokeResult(json_object={"mode": "directive", "evidence": "broad audience project update"})
        if invoke_request.task_name == "gmail_directive_semantic_extract":
            calls["directive"] += 1
            return DummyInvokeResult(
                json_object={
                    "outcome": "directive",
                    "selector": None,
                    "mutation": None,
                }
            )
        if invoke_request.task_name == "gmail_atomic_identity_extract":
            calls["atomic"] += 1
            return DummyInvokeResult(
                json_object={
                    "outcome": "event",
                    "semantic_identity_draft": {
                        "course_dept": "CSE",
                        "course_number": 30,
                        "course_suffix": None,
                        "course_quarter": "SU",
                        "course_year2": 26,
                        "raw_type": "Project",
                        "event_name": "Project 2",
                        "ordinal": 2,
                        "confidence": 0.95,
                        "evidence": "Project 2 is now due Sunday at 11:59 PM for all sections.",
                    },
                    "link_signals": {
                        "keywords": [],
                        "exam_sequence": None,
                        "location_text": None,
                        "instructor_hint": None,
                    },
                }
            )
        assert invoke_request.task_name == "gmail_atomic_time_resolve"
        return DummyInvokeResult(
            json_object={
                "outcome": "resolved",
                "source_time_phrase": "Sunday at 11:59 PM",
                "resolved_due_date": "2026-07-19",
                "resolved_due_time": "23:59:00",
                "time_precision": "datetime",
                "resolution_basis": "explicit_absolute_with_year_inferred",
                "confidence": 0.95,
                "evidence": "Project 2 is now due Sunday at 11:59 PM for all sections.",
            }
        )

    monkeypatch.setattr(semantic_orchestrator, "invoke_llm_json", fake_invoke_llm_json)
    parsed = gmail_parser.parse_gmail_payload(db=None, payload=payload, context=context)  # type: ignore[arg-type]

    assert calls["classify"] == 1
    assert calls["directive"] == LLM_FORMAT_MAX_ATTEMPTS
    assert calls["atomic"] == 1
    assert len(parsed.records) == 1
    assert parsed.records[0]["record_type"] == "gmail.message.extracted"


def test_calendar_parser_unknown_relevance_skips_record(monkeypatch: pytest.MonkeyPatch) -> None:
    content = (
        b"BEGIN:VCALENDAR\n"
        b"VERSION:2.0\n"
        b"BEGIN:VEVENT\n"
        b"UID:uid-3\n"
        b"DTSTART:20260305T180000Z\n"
        b"DTEND:20260305T190000Z\n"
        b"SUMMARY:Discussion section moved\n"
        b"END:VEVENT\n"
        b"END:VCALENDAR\n"
    )
    context = ParserContext(source_id=5, provider="ics", source_kind="calendar", request_id="req-cal-no-event")

    def fake_invoke_llm_json(db, *, invoke_request):  # type: ignore[no-untyped-def]
        del db
        return DummyInvokeResult(json_object={"outcome": "unknown"})

    monkeypatch.setattr(semantic_orchestrator, "invoke_llm_json", fake_invoke_llm_json)
    parsed = calendar_parser.parse_calendar_content(db=None, content=content, context=context)  # type: ignore[arg-type]

    assert parsed.parser_name == "calendar_deterministic"
    assert parsed.records == []


def test_calendar_extract_reuses_event_cache_prefix_instead_of_previous_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = (
        b"BEGIN:VCALENDAR\n"
        b"VERSION:2.0\n"
        b"BEGIN:VEVENT\n"
        b"UID:uid-cache-shape\n"
        b"DTSTART:20260320T180000Z\n"
        b"DTEND:20260320T190000Z\n"
        b"SUMMARY:CSE 8A Homework 2\n"
        b"DESCRIPTION:Homework 2 due at the end of week 10.\n"
        b"END:VEVENT\n"
        b"END:VCALENDAR\n"
    )
    context = ParserContext(source_id=15, provider="ics", source_kind="calendar", request_id="req-cal-cache-shape")
    observed: list[object] = []
    expected_prefix: dict[str, object] = {}

    def fake_invoke_llm_json(db, *, invoke_request):  # type: ignore[no-untyped-def]
        del db
        observed.append(invoke_request)
        if invoke_request.task_name == "calendar_purpose_relevance":
            assert isinstance(invoke_request.cache_prefix_payload, dict)
            expected_prefix.update(invoke_request.cache_prefix_payload)
            return DummyInvokeResult(json_object={"outcome": "relevant"})
        return DummyInvokeResult(
            json_object={
                "course_dept": "CSE",
                "course_number": 8,
                "course_suffix": "A",
                "course_quarter": None,
                "course_year2": None,
                "raw_type": "Homework",
                "event_name": "Homework 2",
                "ordinal": 2,
                "confidence": 0.8,
                "evidence": "Homework 2",
            }
        )

    monkeypatch.setattr(semantic_orchestrator, "invoke_llm_json", fake_invoke_llm_json)
    parsed = calendar_parser.parse_calendar_content(db=None, content=content, context=context)  # type: ignore[arg-type]

    assert len(parsed.records) == 1
    assert len(observed) == 2
    classify_request = observed[0]
    extract_request = observed[1]
    assert classify_request.task_name == "calendar_purpose_relevance"
    assert extract_request.task_name == "calendar_semantic_extract"
    assert isinstance(classify_request.cache_prefix_payload, dict)
    assert classify_request.cache_prefix_payload == expected_prefix
    assert extract_request.cache_prefix_payload == expected_prefix
    assert classify_request.previous_response_id is None
    assert extract_request.previous_response_id is None


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
        del db
        calls["count"] += 1
        if invoke_request.task_name == "calendar_purpose_relevance":
            return DummyInvokeResult(json_object={"outcome": "relevant"})
        return DummyInvokeResult(
            json_object={
                "course_dept": "CSE",
                "course_number": "bad",
                "raw_type": "Project",
                "event_name": "Project update",
                "ordinal": 1,
                "confidence": 0.8,
                "evidence": "Project update",
            }
        )

    monkeypatch.setattr(semantic_orchestrator, "invoke_llm_json", always_bad_invoke)
    with pytest.raises(LlmParseError) as exc_info:
        calendar_parser.parse_calendar_content(db=None, content=content, context=context)  # type: ignore[arg-type]

    assert calls["count"] == LLM_FORMAT_MAX_ATTEMPTS + 1
    assert exc_info.value.code == "parse_llm_calendar_schema_invalid"
