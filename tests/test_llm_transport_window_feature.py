from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from app.modules.llm_gateway.contracts import LlmInvokeRequest, LlmInvokeResult, ResolvedLlmProfile
from app.modules.llm_gateway.gateway import LlmGateway
from app.modules.llm_gateway.runtime_control import (
    reset_llm_invoke_observer,
    reset_session_cache_mode_override,
    set_llm_invoke_observer,
    set_session_cache_mode_override,
)
from app.modules.llm_gateway.transport_openai_compat import OpenAICompatTransport

REPO_ROOT = Path(__file__).resolve().parents[1]


def _profile(*, session_cache_enabled: bool) -> ResolvedLlmProfile:
    return ResolvedLlmProfile(
        provider_id="env-default",
        vendor="openai-compatible",
        base_url="https://example.com/v1",
        api_mode="responses",
        model="test-model",
        api_key="test-key",
        session_cache_enabled=session_cache_enabled,
        timeout_seconds=30.0,
        max_retries=0,
        max_input_chars=12000,
        extra_body={},
    )



def _request() -> LlmInvokeRequest:
    return LlmInvokeRequest(
        task_name="gmail_purpose_mode_classify",
        system_prompt="Return JSON.",
        user_payload={"purpose": "assignment_or_exam_monitoring"},
        output_schema_name="AnyObject",
        output_schema_json={"type": "object"},
        source_id=1,
        request_id="req-1",
        source_provider="gmail",
    )


class _FakeLimiter:
    def __init__(self) -> None:
        self.calls = 0

    def acquire(self):
        self.calls += 1
        return type("AcquireResult", (), {"waited_ms": 0, "in_window": 1, "max_requests": 480, "window_seconds": 60})()



def test_transport_uses_global_request_limiter(monkeypatch) -> None:
    captured: dict[str, object] = {}
    limiter = _FakeLimiter()

    class _FakeResponse:
        status_code = 200
        headers = {}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "{}"}]}], "usage": {}}

    class _FakeClient:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            captured["timeout"] = kwargs.get("timeout")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN201
            return False

        def post(self, endpoint, *, headers, json):  # noqa: ANN001
            captured["endpoint"] = endpoint
            captured["headers"] = headers
            captured["json"] = json
            return _FakeResponse()

    monkeypatch.setattr("app.modules.llm_gateway.transport_openai_compat.get_global_request_limiter", lambda: limiter)
    monkeypatch.setattr("app.modules.llm_gateway.transport_openai_compat.httpx.Client", _FakeClient)

    transport = OpenAICompatTransport()
    transport.post_json(
        profile=_profile(session_cache_enabled=True),
        payload={"model": "test-model", "input": "hello"},
        request_context={"request_id": "req-1", "task_name": "gmail_purpose_mode_classify"},
    )
    assert limiter.calls == 1
    assert captured["endpoint"] == "https://example.com/v1/responses"



def test_gateway_respects_session_cache_override_and_observer(monkeypatch) -> None:
    observed: list[tuple[str, str | None]] = []

    class _FakeTransport:
        def post_json(self, *, profile, payload, request_context):  # noqa: ANN001
            assert profile.session_cache_enabled is True
            return (
                {"output": [{"type": "message", "content": [{"type": "output_text", "text": "{}"}]}], "usage": {}, "id": "resp-1"},
                12,
                None,
            )

    monkeypatch.setattr(
        "app.modules.llm_gateway.gateway.resolve_llm_profile",
        lambda db, source_id: _profile(session_cache_enabled=False),
    )

    gateway = LlmGateway(transport=_FakeTransport())
    observer_token = set_llm_invoke_observer(lambda request, result: observed.append((request.task_name, result.response_id)))
    cache_token = set_session_cache_mode_override("enable")
    try:
        result = gateway.invoke_json(db=None, invoke_request=_request())  # type: ignore[arg-type]
    finally:
        reset_session_cache_mode_override(cache_token)
        reset_llm_invoke_observer(observer_token)

    assert result.response_id == "resp-1"
    assert observed == [("gmail_purpose_mode_classify", "resp-1")]



def test_process_local_email_pool_lists_derived_sets() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/process_local_email_pool.py", "--list-derived-sets"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "synthetic_smoke_4" in result.stdout
    assert "mixed_local_24" in result.stdout



def test_process_local_email_pool_lists_samples_for_derived_set() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/process_local_email_pool.py", "--list-samples", "--derived-set", "synthetic_smoke_4"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "syn-a01" in result.stdout
    assert "syn-d08" in result.stdout
