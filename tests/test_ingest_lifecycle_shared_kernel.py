from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_connector_runtime_uses_shared_job_lifecycle_kernel() -> None:
    connector_path = REPO_ROOT / "app" / "modules" / "ingestion" / "connector_runtime.py"
    apply_path = REPO_ROOT / "app" / "modules" / "ingestion" / "connector_apply.py"
    content = connector_path.read_text(encoding="utf-8")
    apply_content = apply_path.read_text(encoding="utf-8")
    assert "from app.modules.runtime_kernel import" in content or "from app.modules.runtime_kernel import" in apply_content
    assert "apply_retry_transition" in apply_content
    assert "apply_dead_letter_transition" in content or "apply_dead_letter_transition" in apply_content
    assert "upsert_ingest_result_and_outbox_once" in apply_content
    assert "def _retry_or_fail_job" not in content
    assert "def _compute_retry_delay_seconds" not in content


def test_llm_worker_uses_shared_job_lifecycle_kernel() -> None:
    worker_path = REPO_ROOT / "app" / "modules" / "llm_runtime" / "worker.py"
    legacy_tick_path = REPO_ROOT / "app" / "modules" / "llm_runtime" / "worker_tick.py"
    tick_path = REPO_ROOT / "app" / "modules" / "llm_runtime" / "tick_runner.py"
    transitions_path = REPO_ROOT / "app" / "modules" / "llm_runtime" / "transitions.py"
    assert not worker_path.exists()
    assert not legacy_tick_path.exists()
    tick_content = tick_path.read_text(encoding="utf-8")
    transitions_content = transitions_path.read_text(encoding="utf-8")
    assert "from app.modules.runtime_kernel import" in tick_content or "from app.modules.runtime_kernel import" in transitions_content
    assert "apply_retry_transition" in transitions_content
    assert "apply_dead_letter_transition" in tick_content or "apply_dead_letter_transition" in transitions_content
    assert "upsert_ingest_result_and_outbox_once" in transitions_content
    assert "def _retry_or_dead_letter" not in tick_content
    assert "def _compute_retry_delay_seconds" not in tick_content
