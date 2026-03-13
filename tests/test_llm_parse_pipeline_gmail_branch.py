from __future__ import annotations

from app.db.models.ingestion import ConnectorResultStatus
from app.modules.llm_runtime import parse_pipeline as pipeline


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
