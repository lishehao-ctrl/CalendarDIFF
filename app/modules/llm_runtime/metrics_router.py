from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.core.security import require_internal_service_token
from app.modules.runtime_kernel.parse_task_queue import (
    get_parse_queue_redis_client,
    parse_latency_p95_5m,
    parse_queue_depth,
    parse_retry_depth,
    read_parse_metric_counter_1m,
)

router = APIRouter(
    prefix="/internal",
    tags=["internal-llm-metrics"],
    dependencies=[Depends(require_internal_service_token({"ops", "llm"}))],
)


@router.get("/metrics")
def get_llm_metrics() -> dict[str, object]:
    now = datetime.now(timezone.utc)
    client = get_parse_queue_redis_client()

    depth_stream = parse_queue_depth(client)
    depth_retry = parse_retry_depth(client)
    llm_calls_total_1m = read_parse_metric_counter_1m(client, metric_name="llm_calls_total")
    llm_calls_rate_limited_1m = read_parse_metric_counter_1m(client, metric_name="llm_calls_rate_limited")
    limiter_rejects_1m = read_parse_metric_counter_1m(client, metric_name="limiter_rejects")
    llm_latency_p95_5m = parse_latency_p95_5m(client)

    denominator = llm_calls_total_1m + limiter_rejects_1m
    limiter_reject_rate_1m = round(limiter_rejects_1m / denominator, 6) if denominator > 0 else 0.0

    return {
        "service_name": "llm-service",
        "timestamp": now.isoformat(),
        "metrics": {
            "queue_depth_stream": depth_stream,
            "queue_depth_retry": depth_retry,
            "llm_calls_total_1m": llm_calls_total_1m,
            "llm_calls_rate_limited_1m": llm_calls_rate_limited_1m,
            "llm_call_latency_ms_p95_5m": float(llm_latency_p95_5m),
            "limiter_reject_rate_1m": limiter_reject_rate_1m,
        },
    }
