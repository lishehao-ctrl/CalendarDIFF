from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_real_source_smoke_report_schema(tmp_path: Path) -> None:
    report_path = tmp_path / "real_source_smoke_report.json"
    env = dict(os.environ)
    env.pop("INGESTION_LLM_MODEL", None)
    env.pop("INGESTION_LLM_BASE_URL", None)
    env.pop("INGESTION_LLM_API_KEY", None)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/smoke_real_sources_three_rounds.py",
            "--api-base",
            "http://127.0.0.1:1",
            "--api-key",
            "test-api-key",
            "--report",
            str(report_path),
            "--no-cleanup-sources",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 1
    assert report_path.is_file()

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    for key in (
        "run_id",
        "started_at",
        "finished_at",
        "api_base",
        "llm_model",
        "llm_base_url_hash",
        "passed",
        "fatal_errors",
        "source",
        "rounds",
        "provider_counters",
        "assertion_pass_rate",
        "failed_assertions",
    ):
        assert key in payload

    assert isinstance(payload["fatal_errors"], list)
    assert isinstance(payload["source"], dict)
    assert isinstance(payload["provider_counters"], dict)
    assert isinstance(payload["rounds"], list)
    assert len(payload["rounds"]) == 3

    round_required = {
        "round_id",
        "difficulty",
        "alias_profile",
        "ics_request_id",
        "gmail_request_id",
        "ics_status",
        "gmail_status",
        "pending_change_ids",
        "approved_change_ids",
        "timeline_count_after",
        "feed_count_after",
        "merge_verified",
        "errors",
    }
    for round_payload in payload["rounds"]:
        assert isinstance(round_payload, dict)
        assert round_required.issubset(set(round_payload.keys()))
