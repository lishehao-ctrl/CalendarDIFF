from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import httpx
import pytest


def _count_jsonl_rows(path: Path) -> int:
    if not path.is_file():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def test_semester_demo_online(tmp_path: Path) -> None:
    required_llm_env = ["INGESTION_LLM_MODEL", "INGESTION_LLM_BASE_URL", "INGESTION_LLM_API_KEY"]
    missing_llm = [key for key in required_llm_env if not os.getenv(key)]
    if missing_llm:
        pytest.skip(f"missing ingestion llm env config: {missing_llm}")

    run_flag = os.getenv("RUN_SEMESTER_DEMO_SMOKE", "").strip().lower()
    if run_flag not in {"1", "true", "yes"}:
        pytest.skip("set RUN_SEMESTER_DEMO_SMOKE=true to run online semester demo smoke")

    app_api_key = (os.getenv("APP_API_KEY") or "").strip()
    ops_token = (os.getenv("INTERNAL_SERVICE_TOKEN_OPS") or "").strip()
    notification_jsonl = (os.getenv("SEMESTER_DEMO_NOTIFICATION_JSONL") or os.getenv("NOTIFY_JSONL_PATH") or "").strip()
    if not app_api_key or not ops_token or not notification_jsonl:
        pytest.skip("APP_API_KEY, INTERNAL_SERVICE_TOKEN_OPS, and SEMESTER_DEMO_NOTIFICATION_JSONL are required")

    public_api_base = os.getenv("SEMESTER_DEMO_PUBLIC_API_BASE", "http://127.0.0.1:8200").rstrip("/")
    ingest_internal_base = os.getenv("SEMESTER_DEMO_INGEST_INTERNAL_BASE", "http://127.0.0.1:8202").rstrip("/")
    notify_internal_base = os.getenv("SEMESTER_DEMO_NOTIFY_INTERNAL_BASE", "http://127.0.0.1:8204").rstrip("/")
    llm_internal_base = os.getenv("SEMESTER_DEMO_LLM_INTERNAL_BASE", "http://127.0.0.1:8205").rstrip("/")

    for base_url in (public_api_base, ingest_internal_base, notify_internal_base, llm_internal_base):
        try:
            response = httpx.get(f"{base_url}/health", timeout=3.0)
        except Exception as exc:
            pytest.skip(f"health check failed for {base_url}: {exc}")
        if response.status_code != 200:
            pytest.skip(f"health check returned status={response.status_code} for {base_url}")

    sink_path = Path(notification_jsonl)
    notify_email = f"semester-{uuid.uuid4().hex[:8]}@example.com"
    auth_password = "password123"
    rows_before = _count_jsonl_rows(sink_path)
    report_path = tmp_path / "semester_demo_online_report.json"
    cmd = [
        sys.executable,
        "scripts/smoke_semester_demo.py",
        "--public-api-base",
        public_api_base,
        "--ingest-internal-base",
        ingest_internal_base,
        "--notify-internal-base",
        notify_internal_base,
        "--llm-internal-base",
        llm_internal_base,
        "--api-key",
        app_api_key,
        "--ops-token",
        ops_token,
        "--notify-email",
        notify_email,
        "--auth-password",
        auth_password,
        "--notification-jsonl",
        str(sink_path),
        "--report",
        str(report_path),
    ]
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr or result.stdout
    assert report_path.is_file()

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["fatal_errors"] == []
    assert len(payload["semesters"]) == 3
    for semester_payload in payload["semesters"]:
        assert semester_payload["ics_target_count"] == 100
        assert semester_payload["gmail_target_count"] == 100
        assert len(semester_payload["courses"]) >= 2
    for suffix_payload in payload["suffix_assertions"].values():
        assert suffix_payload["passed"] is True
    flush = payload["notification_flush"]
    assert flush["sent_count"] > 0 or flush["processed_slots"] > 0
    assert payload["notification_sink"]["rows_after"] > rows_before
    assert payload["notification_sink"]["rows_delta"] > 0
