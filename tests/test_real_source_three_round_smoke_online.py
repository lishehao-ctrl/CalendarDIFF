from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest


def test_real_source_three_round_smoke_online(tmp_path: Path) -> None:
    required_llm_env = ["INGESTION_LLM_MODEL", "INGESTION_LLM_BASE_URL", "INGESTION_LLM_API_KEY"]
    missing_llm = [key for key in required_llm_env if not os.getenv(key)]
    if missing_llm:
        pytest.skip(f"missing ingestion llm env config: {missing_llm}")

    run_flag = os.getenv("RUN_REAL_SOURCE_SMOKE", "").strip().lower()
    if run_flag not in {"1", "true", "yes"}:
        pytest.skip("set RUN_REAL_SOURCE_SMOKE=true to run online real-source smoke")

    api_base = os.getenv("REAL_SOURCE_SMOKE_API_BASE", "http://127.0.0.1:8000").rstrip("/")
    api_key = (os.getenv("APP_API_KEY") or "").strip()
    if not api_key:
        pytest.skip("APP_API_KEY is required for online real-source smoke")

    try:
        health = httpx.get(f"{api_base}/health", timeout=3.0)
    except Exception as exc:
        pytest.skip(f"api health check failed: {exc}")
    if health.status_code != 200:
        pytest.skip(f"api health check returned status={health.status_code}")

    report_path = tmp_path / "real_source_smoke_report.json"
    cmd = [
        sys.executable,
        "scripts/smoke_real_sources_three_rounds.py",
        "--api-base",
        api_base,
        "--api-key",
        api_key,
        "--report",
        str(report_path),
    ]
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr or result.stdout
    assert report_path.is_file()

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["fatal_errors"] == []
    assert len(payload["rounds"]) == 3
    assert payload["merge_gate_mode"] == "strict_same_topic"
    assert isinstance(payload["global_topic_uid"], str) and payload["global_topic_uid"]
    for round_payload in payload["rounds"]:
        assert round_payload["merge_verified"] is True
        assert len(round_payload["pending_change_ids"]) == 1
        assert round_payload["single_pending_enforced"] is True
        assert round_payload["merge_required_sources_present"] is True
        assert round_payload["same_topic_uid_enforced"] is True
        assert round_payload["topic_uid"] == payload["global_topic_uid"]
