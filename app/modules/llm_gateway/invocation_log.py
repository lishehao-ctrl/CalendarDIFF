from __future__ import annotations

import logging

from app.core.config import get_settings
from app.db.models.runtime import LlmInvocationLog
from app.db.session import get_session_factory
from app.modules.llm_gateway.tracing import LlmGatewayTraceEvent

logger = logging.getLogger(__name__)


def record_llm_invocation_trace(*, event: LlmGatewayTraceEvent) -> None:
    if not bool(get_settings().llm_gateway_trace_persistence_enabled):
        return
    try:
        session_factory = get_session_factory()
        with session_factory() as db:
            db.add(
                LlmInvocationLog(
                    request_id=event.request_id,
                    source_id=event.source_id,
                    task_name=event.task_name,
                    profile_family=event.profile_family,
                    route_id=event.route_id,
                    route_index=event.route_index,
                    provider_id=event.provider_id,
                    vendor=event.vendor,
                    protocol=event.protocol,
                    model=event.model,
                    session_cache_enabled=event.session_cache_enabled,
                    success=event.success,
                    latency_ms=event.latency_ms,
                    upstream_request_id=event.upstream_request_id,
                    response_id=event.response_id,
                    error_code=event.error_code,
                    retryable=event.retryable,
                    http_status=event.http_status,
                    usage_json=event.usage,
                )
            )
            db.commit()
    except Exception as exc:
        logger.warning(
            "llm_invocation_log.persist_failed request_id=%s source_id=%s task_name=%s error=%s",
            event.request_id or "-",
            event.source_id if event.source_id is not None else "-",
            event.task_name,
            exc,
        )


__all__ = ["record_llm_invocation_trace"]
