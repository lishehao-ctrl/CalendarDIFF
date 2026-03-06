from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_semester_demo_report_schema(tmp_path: Path) -> None:
    report_path = tmp_path / "semester_demo_report.json"
    env = dict(os.environ)
    env.pop("INGESTION_LLM_MODEL", None)
    env.pop("INGESTION_LLM_BASE_URL", None)
    env.pop("INGESTION_LLM_API_KEY", None)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/smoke_semester_demo.py",
            "--input-api-base",
            "http://127.0.0.1:1",
            "--review-api-base",
            "http://127.0.0.1:1",
            "--notify-api-base",
            "http://127.0.0.1:1",
            "--ops-token",
            "test-internal-token-ops",
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
        "passed",
        "fatal_errors",
        "assertions",
        "failed_assertions",
        "llm_mode",
        "scenario_manifest_path",
        "source",
        "semesters",
        "suffix_assertions",
        "provider_state",
        "notification_sink",
        "notification_flush",
    ):
        assert key in payload

    assert payload["llm_mode"] == "online"
    assert isinstance(payload["fatal_errors"], list)
    assert isinstance(payload["assertions"], list)
    assert isinstance(payload["semesters"], list)
    assert isinstance(payload["notification_sink"], dict)
    assert isinstance(payload["notification_flush"], dict)
