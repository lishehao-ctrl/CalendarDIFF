#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run microservice closure checks: health -> strict smoke -> cleanup -> retention dry-run -> slo check."
    )
    parser.add_argument("--input-api-base", default=os.getenv("INPUT_API_BASE_URL", "http://127.0.0.1:8001"))
    parser.add_argument("--review-api-base", default=os.getenv("REVIEW_API_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--ingest-api-base", default=os.getenv("INGEST_API_BASE_URL", "http://127.0.0.1:8002"))
    parser.add_argument("--notify-api-base", default=os.getenv("NOTIFY_API_BASE_URL", "http://127.0.0.1:8004"))
    parser.add_argument("--api-key", default=os.getenv("APP_API_KEY", ""))
    parser.add_argument("--ops-token", default=os.getenv("INTERNAL_SERVICE_TOKEN_OPS", ""))
    parser.add_argument(
        "--report",
        default="data/synthetic/v2_ddlchange_160/qa/real_source_smoke_report.json",
    )
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, text=True, capture_output=True)


def _check_health(base_url: str, timeout_seconds: float) -> None:
    response = httpx.get(f"{base_url.rstrip('/')}/health", timeout=timeout_seconds)
    if response.status_code != 200:
        raise RuntimeError(f"health check failed base={base_url} status={response.status_code} body={response.text[:300]}")


def _render_text(result: dict[str, Any]) -> None:
    print("smoke_microservice_closure summary")
    print(f"  passed: {result['passed']}")
    for step in result["steps"]:
        print(f"  - {step['name']}: passed={step['passed']}")
        if step.get("detail"):
            print(f"    detail: {step['detail']}")
    if result["errors"]:
        print(f"  errors: {result['errors']}")


def main() -> int:
    args = parse_args()
    result: dict[str, Any] = {"passed": False, "steps": [], "errors": []}

    try:
        _check_health(args.input_api_base, args.timeout_seconds)
        result["steps"].append({"name": "health_input", "passed": True})

        _check_health(args.review_api_base, args.timeout_seconds)
        result["steps"].append({"name": "health_review", "passed": True})

        if args.ingest_api_base:
            _check_health(args.ingest_api_base, args.timeout_seconds)
            result["steps"].append({"name": "health_ingest", "passed": True})
        if args.notify_api_base:
            _check_health(args.notify_api_base, args.timeout_seconds)
            result["steps"].append({"name": "health_notify", "passed": True})

        if not args.api_key:
            raise RuntimeError("APP_API_KEY (or --api-key) is required")
        if not args.ops_token:
            raise RuntimeError("INTERNAL_SERVICE_TOKEN_OPS (or --ops-token) is required")

        smoke_cmd = [
            sys.executable,
            "scripts/smoke_real_sources_three_rounds.py",
            "--input-api-base",
            args.input_api_base,
            "--review-api-base",
            args.review_api_base,
            "--api-key",
            args.api_key,
            "--report",
            args.report,
        ]
        if args.ingest_api_base:
            smoke_cmd += ["--ingest-api-base", args.ingest_api_base]
        if args.notify_api_base:
            smoke_cmd += ["--notify-api-base", args.notify_api_base]

        smoke = _run(smoke_cmd)
        if smoke.returncode != 0:
            raise RuntimeError(f"strict smoke failed: {smoke.stderr or smoke.stdout}")
        result["steps"].append({"name": "strict_smoke", "passed": True})

        report_path = Path(args.report)
        if not report_path.is_file():
            raise RuntimeError(f"smoke report not found: {report_path}")
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
        source_ids = []
        for key in ("calendar_source_id", "gmail_source_id"):
            value = source.get(key)
            if isinstance(value, int) and value > 0:
                source_ids.append(value)
        if source_ids:
            cleanup_cmd = [sys.executable, "scripts/ops_cleanup_smoke_state.py", "--apply", "--json"]
            for source_id in source_ids:
                cleanup_cmd += ["--source-id", str(source_id)]
            cleanup = _run(cleanup_cmd)
            if cleanup.returncode != 0:
                raise RuntimeError(f"smoke cleanup failed: {cleanup.stderr or cleanup.stdout}")
            result["steps"].append({"name": "smoke_cleanup", "passed": True, "detail": cleanup.stdout.strip()[:300]})

        retention = _run([sys.executable, "scripts/ops_retention_minimal.py", "--dry-run", "--json"])
        if retention.returncode != 0:
            raise RuntimeError(f"retention dry-run failed: {retention.stderr or retention.stdout}")
        result["steps"].append({"name": "retention_dry_run", "passed": True})

        slo = _run(
            [
                sys.executable,
                "scripts/ops_slo_check.py",
                "--input-base",
                args.input_api_base,
                "--ingest-base",
                args.ingest_api_base,
                "--review-base",
                args.review_api_base,
                "--notify-base",
                args.notify_api_base,
                "--ops-token",
                args.ops_token,
                "--json",
            ]
        )
        if slo.returncode != 0:
            raise RuntimeError(f"slo check failed: {slo.stderr or slo.stdout}")
        result["steps"].append({"name": "slo_check", "passed": True, "detail": slo.stdout.strip()[:300]})
        result["passed"] = True
    except Exception as exc:
        result["errors"].append(str(exc))
        result["passed"] = False

    if args.json:
        print(json.dumps(result, ensure_ascii=True))
    else:
        _render_text(result)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
