from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.core.security import require_internal_service_token
from app.modules.llm_runtime.queue import (
    get_redis_client,
    latency_p95_5m,
    queue_depth_retry,
    queue_depth_stream,
    queue_stream_key,
    read_metric_counter_1m,
)

router = APIRouter(
    prefix="/internal",
    tags=["internal-llm-metrics"],
    dependencies=[Depends(require_internal_service_token({"ops", "llm"}))],
)


@router.get("/metrics")
def get_llm_metrics() -> dict[str, object]:
    now = datetime.now(timezone.utc)
    client = get_redis_client()
    stream_key = queue_stream_key()

    depth_stream = queue_depth_stream(client, stream_key=stream_key)
    depth_retry = queue_depth_retry(client, stream_key=stream_key)
    llm_calls_total_1m = read_metric_counter_1m(client, metric_name="llm_calls_total")
    llm_calls_rate_limited_1m = read_metric_counter_1m(client, metric_name="llm_calls_rate_limited")
    limiter_rejects_1m = read_metric_counter_1m(client, metric_name="limiter_rejects")
    llm_latency_p95_5m = latency_p95_5m(client, stream_key=stream_key)

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
