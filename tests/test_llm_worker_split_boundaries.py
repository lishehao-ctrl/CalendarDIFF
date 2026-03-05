from __future__ import annotations

from pathlib import Path


def test_tick_runner_only_contains_orchestration_logic() -> None:
    content = Path("app/modules/llm_runtime/tick_runner.py").read_text(encoding="utf-8")

    assert "app.modules.llm_runtime.message_processor" in content
    assert "parse_with_llm(" not in content
    assert "apply_llm_failure_transition(" not in content
    assert "mark_llm_success(" not in content
    assert "app.db.models." not in content
    assert "select(" not in content
