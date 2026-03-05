from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_connector_runtime_uses_shared_job_lifecycle_kernel() -> None:
    connector_path = REPO_ROOT / "app" / "modules" / "ingestion" / "connector_runtime.py"
    apply_path = REPO_ROOT / "app" / "modules" / "ingestion" / "connector_apply.py"
    content = connector_path.read_text(encoding="utf-8")
    apply_content = apply_path.read_text(encoding="utf-8")
    assert "from app.modules.ingestion.job_lifecycle import" in content or "from app.modules.ingestion.job_lifecycle import" in apply_content
    assert "apply_retry_transition" in apply_content
    assert "apply_dead_letter_transition" in content or "apply_dead_letter_transition" in apply_content
    assert "upsert_ingest_result_and_outbox_once" in apply_content
    assert "def _retry_or_fail_job" not in content
    assert "def _compute_retry_delay_seconds" not in content


def test_llm_worker_uses_shared_job_lifecycle_kernel() -> None:
    worker_path = REPO_ROOT / "app" / "modules" / "llm_runtime" / "worker.py"
    content = worker_path.read_text(encoding="utf-8")
    assert "from app.modules.ingestion.job_lifecycle import" in content
    assert "apply_retry_transition" in content
    assert "apply_dead_letter_transition" in content
    assert "upsert_ingest_result_and_outbox_once" in content
    assert "def _retry_or_dead_letter" not in content
    assert "def _compute_retry_delay_seconds" not in content
