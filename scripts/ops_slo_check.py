#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from typing import Any

import httpx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run minimal microservice SLO checks using internal metrics endpoints.")
    parser.add_argument(
        "--input-base",
        default=os.getenv("INPUT_API_BASE_URL", "http://127.0.0.1:8001"),
        help="Input service base URL.",
    )
    parser.add_argument(
        "--ingest-base",
        default=os.getenv("INGEST_API_BASE_URL", "http://127.0.0.1:8002"),
        help="Ingest service base URL.",
    )
    parser.add_argument(
        "--review-base",
        default=os.getenv("REVIEW_API_BASE_URL", "http://127.0.0.1:8000"),
        help="Review service base URL.",
    )
    parser.add_argument(
        "--notify-base",
        default=os.getenv("NOTIFY_API_BASE_URL", "http://127.0.0.1:8004"),
        help="Notification service base URL.",
    )
    parser.add_argument(
        "--llm-base",
        default=os.getenv("LLM_API_BASE_URL", "http://127.0.0.1:8005"),
        help="LLM service base URL.",
    )
    parser.add_argument(
        "--ops-token",
        default=os.getenv("INTERNAL_SERVICE_TOKEN_OPS", ""),
        help="Ops internal service token (X-Service-Token). Defaults to INTERNAL_SERVICE_TOKEN_OPS.",
    )
    parser.add_argument("--max-dead-letter-rate-1h", type=float, default=0.2)
    parser.add_argument("--max-pending-backlog-age-seconds", type=float, default=900.0)
    parser.add_argument("--max-notify-fail-rate-24h", type=float, default=0.2)
    parser.add_argument("--max-event-lag-seconds-p95", type=float, default=120.0)
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    return parser.parse_args()


def _fetch_metrics(base_url: str, *, token: str, timeout_seconds: float) -> dict[str, Any]:
    normalized_base = base_url.rstrip("/")
    headers = {
        "X-Service-Name": "ops",
        "X-Service-Token": token,
    }
    with httpx.Client(timeout=timeout_seconds) as client:
        response = client.get(f"{normalized_base}/internal/v2/metrics", headers=headers)
    if response.status_code >= 400:
        raise RuntimeError(f"metrics request failed base={normalized_base} status={response.status_code} body={response.text[:400]}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"metrics response is not object for base={normalized_base}")
    return payload


def _to_float(value: Any, *, key: str) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    raise RuntimeError(f"missing/invalid metric '{key}'")


def _render_text(summary: dict[str, Any]) -> None:
    print("ops_slo_check summary")
    print(f"  passed: {summary['passed']}")
    print(f"  checked_at: {summary['checked_at']}")
    for check in summary["checks"]:
        print(
            f"  - {check['name']}: passed={check['passed']} value={check['value']} threshold={check['threshold']}"
        )
    if summary["errors"]:
        print(f"  errors: {summary['errors']}")


def main() -> int:
    args = parse_args()
    if not args.ops_token:
        payload = {"passed": False, "errors": ["missing ops token: --ops-token or INTERNAL_SERVICE_TOKEN_OPS"]}
        if args.json:
            print(json.dumps(payload, ensure_ascii=True))
        else:
            print("ops_slo_check failed: missing ops token: --ops-token or INTERNAL_SERVICE_TOKEN_OPS", file=sys.stderr)
        return 1

    output: dict[str, Any] = {
        "checked_at": datetime.now(UTC).isoformat(),
        "passed": False,
        "errors": [],
        "services": {},
        "checks": [],
    }

    try:
        input_metrics = _fetch_metrics(args.input_base, token=args.ops_token, timeout_seconds=args.timeout_seconds)
        ingest_metrics = _fetch_metrics(args.ingest_base, token=args.ops_token, timeout_seconds=args.timeout_seconds)
        review_metrics = _fetch_metrics(args.review_base, token=args.ops_token, timeout_seconds=args.timeout_seconds)
        notify_metrics = _fetch_metrics(args.notify_base, token=args.ops_token, timeout_seconds=args.timeout_seconds)
        llm_metrics = _fetch_metrics(args.llm_base, token=args.ops_token, timeout_seconds=args.timeout_seconds)
        output["services"] = {
            "input": input_metrics,
            "ingest": ingest_metrics,
            "review": review_metrics,
            "notification": notify_metrics,
            "llm": llm_metrics,
        }

        ingest_values = ingest_metrics.get("metrics") if isinstance(ingest_metrics.get("metrics"), dict) else {}
        review_values = review_metrics.get("metrics") if isinstance(review_metrics.get("metrics"), dict) else {}
        notify_values = notify_metrics.get("metrics") if isinstance(notify_metrics.get("metrics"), dict) else {}
        llm_values = llm_metrics.get("metrics") if isinstance(llm_metrics.get("metrics"), dict) else {}

        # Validate llm-service metric contract is present.
        _to_float(llm_values.get("queue_depth_stream"), key="queue_depth_stream")
        _to_float(llm_values.get("queue_depth_retry"), key="queue_depth_retry")
        _to_float(llm_values.get("llm_calls_total_1m"), key="llm_calls_total_1m")
        _to_float(llm_values.get("llm_calls_rate_limited_1m"), key="llm_calls_rate_limited_1m")
        _to_float(llm_values.get("llm_call_latency_ms_p95_5m"), key="llm_call_latency_ms_p95_5m")
        _to_float(llm_values.get("limiter_reject_rate_1m"), key="limiter_reject_rate_1m")

        checks = [
            {
                "name": "dead_letter_rate_1h",
                "value": _to_float(ingest_values.get("dead_letter_rate_1h"), key="dead_letter_rate_1h"),
                "threshold": args.max_dead_letter_rate_1h,
            },
            {
                "name": "pending_backlog_age_seconds_max",
                "value": _to_float(
                    review_values.get("pending_backlog_age_seconds_max"),
                    key="pending_backlog_age_seconds_max",
                ),
                "threshold": args.max_pending_backlog_age_seconds,
            },
            {
                "name": "notify_fail_rate_24h",
                "value": _to_float(notify_values.get("notify_fail_rate_24h"), key="notify_fail_rate_24h"),
                "threshold": args.max_notify_fail_rate_24h,
            },
            {
                "name": "event_lag_seconds_p95",
                "value": _to_float(ingest_values.get("event_lag_seconds_p95"), key="event_lag_seconds_p95"),
                "threshold": args.max_event_lag_seconds_p95,
            },
            {
                "name": "llm_metrics_contract",
                "value": 1.0,
                "threshold": 1.0,
            },
        ]

        for check in checks:
            check["passed"] = bool(check["value"] <= check["threshold"])
        output["checks"] = checks
        output["passed"] = all(check["passed"] for check in checks)
    except Exception as exc:
        output["errors"].append(str(exc))
        output["passed"] = False

    if args.json:
        print(json.dumps(output, ensure_ascii=True))
    else:
        _render_text(output)
    return 0 if output["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
