from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.llm_gateway import LlmInvokeRequest, LlmInvokeResult, invoke_llm_json
from app.modules.llm_gateway.contracts import LlmProtocolLiteral, SessionCacheModeLiteral


@dataclass(frozen=True)
class HelperAgentTask:
    task_name: str
    system_prompt: str
    user_payload: dict
    output_schema_name: str
    output_schema_json: dict
    source_id: int | None = None
    request_id: str | None = None
    source_provider: str | None = None
    temperature: float = 0.0
    shared_user_payload: dict | None = None
    cache_prefix_payload: dict | None = None
    cache_task_prompt: bool = False
    previous_response_id: str | None = None
    protocol_override: LlmProtocolLiteral | None = None
    session_cache_mode: SessionCacheModeLiteral = "disable"


def invoke_helper_json(
    db: Session | None,
    *,
    task: HelperAgentTask,
    invoke_json_fn: Callable[[Session | None, LlmInvokeRequest], LlmInvokeResult] | None = None,
) -> LlmInvokeResult:
    invoke_json = invoke_json_fn or _invoke_json_adapter
    return invoke_json(db, _build_helper_request(task))


def invoke_helper_batch_json(
    session_factory: Callable[[], Session],
    *,
    tasks: Sequence[HelperAgentTask],
    max_parallelism: int | None = None,
    invoke_json_fn: Callable[[Session | None, LlmInvokeRequest], LlmInvokeResult] | None = None,
) -> list[LlmInvokeResult]:
    task_list = list(tasks)
    if not task_list:
        return []

    invoke_json = invoke_json_fn or _invoke_json_adapter
    worker_count = min(len(task_list), _resolve_parallelism(max_parallelism))

    def _run(task: HelperAgentTask) -> LlmInvokeResult:
        db = session_factory()
        try:
            return invoke_json(db, _build_helper_request(task))
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        return list(executor.map(_run, task_list))


def _build_helper_request(task: HelperAgentTask) -> LlmInvokeRequest:
    return LlmInvokeRequest(
        task_name=task.task_name,
        system_prompt=task.system_prompt,
        user_payload=task.user_payload,
        output_schema_name=task.output_schema_name,
        output_schema_json=task.output_schema_json,
        profile_family="helper",
        source_id=task.source_id,
        request_id=task.request_id,
        source_provider=task.source_provider,
        temperature=task.temperature,
        shared_user_payload=task.shared_user_payload,
        cache_prefix_payload=task.cache_prefix_payload,
        cache_task_prompt=task.cache_task_prompt,
        previous_response_id=task.previous_response_id,
        protocol_override=task.protocol_override,
        session_cache_mode=task.session_cache_mode,
    )


def _resolve_parallelism(override: int | None) -> int:
    if override is not None:
        return max(int(override), 1)
    return max(int(get_settings().helper_agent_parallelism), 1)


def _invoke_json_adapter(db: Session | None, invoke_request: LlmInvokeRequest) -> LlmInvokeResult:
    return invoke_llm_json(db, invoke_request=invoke_request)  # type: ignore[arg-type]


__all__ = [
    "HelperAgentTask",
    "invoke_helper_batch_json",
    "invoke_helper_json",
]
