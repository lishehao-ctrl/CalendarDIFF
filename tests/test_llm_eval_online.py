from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_online_eval_cli_smoke(tmp_path: Path) -> None:
    required_env = ["INGESTION_LLM_MODEL", "INGESTION_LLM_BASE_URL", "INGESTION_LLM_API_KEY"]
    missing = [key for key in required_env if not os.getenv(key)]
    if missing:
        pytest.skip(f"missing ingestion llm env config: {missing}")

    if os.getenv("RUN_ONLINE_LLM_EVAL_TESTS", "").strip().lower() not in {"1", "true", "yes"}:
        pytest.skip("set RUN_ONLINE_LLM_EVAL_TESTS=true to run online 160-sample evaluation")

    report_path = tmp_path / "llm_pass_rate_report.json"
    cmd = [
        sys.executable,
        "scripts/eval_ingestion_llm_pass_rate.py",
        "--dataset-root",
        "data/synthetic/v2_ddlchange_160",
        "--report",
        str(report_path),
        "--max-workers",
        "4",
        "--no-fail-on-threshold",
    ]
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr or result.stdout
    assert report_path.is_file()

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["sample_counts"]["mail"] == 120
    assert payload["sample_counts"]["ics_pairs"] == 40
    assert payload["sample_counts"]["total"] == 160
    assert "mail" in payload and "ics" in payload
