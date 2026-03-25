from __future__ import annotations

from app.modules.llm_gateway.contracts import LlmStreamRequest, ResolvedLlmProfile
from app.modules.llm_gateway.transport_gemini_native import GeminiNativeTransport
from app.modules.llm_gateway.transport_openai_compat import OpenAICompatTransport


def test_openai_chat_stream_normalizes_delta_and_completed(monkeypatch) -> None:
    class _FakeResponse:
        status_code = 200
        headers = {"x-request-id": "upstream-1"}

        def raise_for_status(self) -> None:
            return None

        def iter_lines(self):
            yield 'data: {"id":"chatcmpl-1","choices":[{"delta":{"content":"Hel"}}]}'
            yield 'data: {"id":"chatcmpl-1","choices":[{"delta":{"content":"lo"}}],"usage":{"total_tokens":12}}'
            yield "data: [DONE]"

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN201
            return False

    class _FakeClient:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN201
            return False

        def stream(self, method, endpoint, *, headers, json):  # noqa: ANN001
            assert method == "POST"
            assert endpoint == "https://api.openai.com/v1/chat/completions"
            assert headers["Authorization"] == "Bearer test-key"
            assert json["stream"] is True
            return _FakeResponse()

    monkeypatch.setattr("app.modules.llm_gateway.transport_openai_compat.httpx.Client", _FakeClient)
    monkeypatch.setattr(
        "app.modules.llm_gateway.transport_openai_compat.get_global_request_limiter",
        lambda: type("Limiter", (), {"acquire": lambda self: type("AcquireResult", (), {"waited_ms": 0, "in_window": 1, "max_requests": 480, "window_seconds": 60})()})(),
    )

    events = list(
        OpenAICompatTransport().stream_events(
            profile=ResolvedLlmProfile(
                provider_id="openai_main",
                vendor="openai",
                protocol="chat_completions",
                base_url="https://api.openai.com/v1",
                model="gpt-5-mini",
                api_key="test-key",
                session_cache_enabled=False,
                timeout_seconds=30.0,
                max_retries=0,
                max_input_chars=12000,
            ),
            payload={"model": "gpt-5-mini", "messages": [], "stream": True},
            request_context={"request_id": "req-1", "task_name": "stream_test"},
        )
    )

    assert [event.event_type for event in events] == ["delta", "delta", "completed"]
    assert "".join(event.text_delta or "" for event in events if event.event_type == "delta") == "Hello"
    assert events[-1].raw_usage == {"total_tokens": 12}


def test_gemini_native_stream_normalizes_delta_and_completed(monkeypatch) -> None:
    class _FakeResponse:
        status_code = 200
        headers = {"x-request-id": "upstream-2"}

        def raise_for_status(self) -> None:
            return None

        def iter_lines(self):
            yield 'data: {"responseId":"gem-1","candidates":[{"content":{"parts":[{"text":"Hi"}]}}]}'
            yield 'data: {"responseId":"gem-1","candidates":[{"content":{"parts":[{"text":" there"}]}}],"usageMetadata":{"totalTokenCount":9}}'

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN201
            return False

    class _FakeClient:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN201
            return False

        def stream(self, method, endpoint, *, headers, json):  # noqa: ANN001
            assert method == "POST"
            assert endpoint == "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:streamGenerateContent?alt=sse"
            assert headers["x-goog-api-key"] == "test-key"
            assert json["generationConfig"]["responseMimeType"] == "text/plain"
            return _FakeResponse()

    monkeypatch.setattr("app.modules.llm_gateway.transport_gemini_native.httpx.Client", _FakeClient)
    monkeypatch.setattr(
        "app.modules.llm_gateway.transport_gemini_native.get_global_request_limiter",
        lambda: type("Limiter", (), {"acquire": lambda self: type("AcquireResult", (), {"waited_ms": 0, "in_window": 1, "max_requests": 480, "window_seconds": 60})()})(),
    )

    events = list(
        GeminiNativeTransport().stream_events(
            profile=ResolvedLlmProfile(
                provider_id="gemini_main",
                vendor="gemini",
                protocol="gemini_generate_content",
                base_url="https://generativelanguage.googleapis.com/v1beta/models",
                model="gemini-2.5-flash",
                api_key="test-key",
                session_cache_enabled=False,
                timeout_seconds=30.0,
                max_retries=0,
                max_input_chars=12000,
            ),
            payload={"contents": [], "generationConfig": {"responseMimeType": "text/plain"}},
            request_context={"request_id": "req-2", "task_name": "stream_test"},
        )
    )

    assert [event.event_type for event in events] == ["delta", "delta", "completed"]
    assert "".join(event.text_delta or "" for event in events if event.event_type == "delta") == "Hi there"
    assert events[-1].response_id == "gem-1"
    assert events[-1].raw_usage == {"totalTokenCount": 9}


def test_stream_request_shape_stays_text_oriented() -> None:
    request = LlmStreamRequest(
        task_name="agent_chat",
        system_prompt="Help the user review changes.",
        user_payload={"prompt": "Summarize pending work."},
        profile_family="agent",
        request_id="req-stream-1",
    )
    assert request.task_name == "agent_chat"
    assert request.user_payload == {"prompt": "Summarize pending work."}
