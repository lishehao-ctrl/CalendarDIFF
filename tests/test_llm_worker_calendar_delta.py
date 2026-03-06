from __future__ import annotations

import base64

from sqlalchemy.orm import sessionmaker

from app.db.models.ingestion import ConnectorResultStatus
from app.modules.ingestion.llm_parsers.contracts import ParserOutput
from app.modules.llm_runtime import parse_pipeline


def test_calendar_delta_removed_only_skips_llm(db_session_factory: sessionmaker) -> None:
    records, status = parse_pipeline.parse_calendar_delta_with_llm(
        redis_client=object(),  # type: ignore[arg-type]
        stream_key="llm:parse:stream:v1",
        parse_payload={
            "kind": "calendar_delta_v1",
            "changed_components": [],
            "removed_component_keys": ["evt-remove#"],
        },
        provider="ics",
        request_id="req-delta-removed-only",
        source_id=1,
        session_factory=db_session_factory,
    )

    assert status == ConnectorResultStatus.CHANGED
    assert records == [
        {
            "record_type": "calendar.event.removed",
            "payload": {
                "component_key": "evt-remove#",
                "external_event_id": "evt-remove",
            },
        }
    ]


def test_calendar_delta_changed_component_overrides_uid(monkeypatch, db_session_factory: sessionmaker) -> None:
    component_text = "\n".join(
        [
            "BEGIN:VEVENT",
            "UID:evt-rid",
            "RECURRENCE-ID:20260301T100000Z",
            "DTSTART:20260301T100000Z",
            "DTEND:20260301T110000Z",
            "SUMMARY:Quiz",
            "END:VEVENT",
        ]
    )
    component_ical_b64 = base64.b64encode(component_text.encode("utf-8")).decode("ascii")
    expected_external_event_id = "evt-rid#20260301T100000Z"

    monkeypatch.setattr(
        parse_pipeline,
        "invoke_parser_with_limit",
        lambda **kwargs: kwargs["parse_call"](),
    )

    def _fake_parse_calendar_content(*, db, content, context):  # noqa: ANN001
        del db, content, context
        return ParserOutput(
            records=[
                {
                    "record_type": "calendar.event.extracted",
                    "payload": {
                        "title": "Quiz",
                        "start_at": "2026-03-01T10:00:00+00:00",
                        "end_at": "2026-03-01T11:00:00+00:00",
                        "course_label": "CSE 8A",
                        "raw_confidence": 0.9,
                    },
                }
            ],
            parser_name="calendar_llm",
            parser_version="mainline",
            model_hint="test-model",
        )

    monkeypatch.setattr(parse_pipeline, "parse_calendar_content", _fake_parse_calendar_content)

    records, status = parse_pipeline.parse_calendar_delta_with_llm(
        redis_client=object(),  # type: ignore[arg-type]
        stream_key="llm:parse:stream:v1",
        parse_payload={
            "kind": "calendar_delta_v1",
            "changed_components": [
                {
                    "component_key": "evt-rid#20260301T100000Z",
                    "external_event_id": expected_external_event_id,
                    "component_ical_b64": component_ical_b64,
                }
            ],
            "removed_component_keys": [],
        },
        provider="ics",
        request_id="req-delta-changed",
        source_id=2,
        session_factory=db_session_factory,
    )

    assert status == ConnectorResultStatus.CHANGED
    assert len(records) == 1
    payload = records[0]["payload"]
    assert payload["source_canonical"]["external_event_id"] == expected_external_event_id
    assert payload["component_key"] == "evt-rid#20260301T100000Z"
