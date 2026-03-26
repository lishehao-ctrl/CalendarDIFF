from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import scripts.run_live_replay_closeout as closeout


def test_build_cost_summary_extracts_usage_cost_nodes() -> None:
    summary = closeout.build_cost_summary(
        {
            "llm_usage": {
                "overall": {
                    "successful_call_count": 12,
                    "total_tokens": 1234,
                    "estimated_cost_usd": 0.0123,
                    "input_cost_usd": 0.004,
                    "cached_input_cost_usd": 0.001,
                    "output_cost_usd": 0.0073,
                    "pricing_available": True,
                    "unpriced_call_count": 0,
                    "models": {"qwen3.5-flash": 12},
                    "task_counts": {"gmail_purpose_mode_classify": 12},
                }
            }
        }
    )

    assert summary["overall"]["successful_call_count"] == 12
    assert summary["overall"]["estimated_cost_usd"] == 0.0123
    assert summary["overall"]["models"] == {"qwen3.5-flash": 12}
    assert summary["gmail"]["pricing_available"] is False


def test_continue_closeout_starts_acceptance_and_writes_final_artifacts(monkeypatch, tmp_path: Path) -> None:
    run_dir = tmp_path / "closeout"
    run_dir.mkdir()
    inner_run_dir = tmp_path / "year-timeline-replay-inner"
    inner_run_dir.mkdir()
    closeout.validation._write_json(
        run_dir / closeout.STATE_FILE,
        {
            "run_id": "live-replay-closeout-test",
            "created_at": "2026-03-26T00:00:00+00:00",
            "database_url": "postgresql+psycopg://postgres:postgres@localhost:5432/deadline_diff_replay_eval",
            "redis_url": "redis://127.0.0.1:6379/13",
            "public_api_host": "127.0.0.1",
            "public_api_port": 8212,
            "app_api_key": "test-api-key",
            "time_budget_seconds": 60,
            "max_checkpoints": None,
            "acceptance_run_dir": None,
        },
    )

    monkeypatch.setattr(closeout.validation, "validate_replay_llm_env", lambda env: None)

    @contextmanager
    def _managed_backend(**kwargs):  # type: ignore[no-untyped-def]
        Path(kwargs["log_path"]).write_text("backend ok\n", encoding="utf-8")
        yield

    monkeypatch.setattr(closeout.validation, "managed_backend", _managed_backend)

    def _run_command(*, command, cwd, env, log_path):  # type: ignore[no-untyped-def]
        del cwd, env
        Path(log_path).write_text("acceptance ok\n", encoding="utf-8")
        (inner_run_dir / "backend-acceptance-report.json").write_text(
            json.dumps({"status": "finished", "summary": {"checkpoint_count": 24}}),
            encoding="utf-8",
        )
        (inner_run_dir / "report.json").write_text(
            json.dumps(
                {
                    "finished": True,
                    "awaiting_manual": False,
                    "llm_usage": {
                        "overall": {
                            "successful_call_count": 40,
                            "total_tokens": 8000,
                            "estimated_cost_usd": 0.024,
                            "input_cost_usd": 0.008,
                            "cached_input_cost_usd": 0.004,
                            "output_cost_usd": 0.012,
                            "pricing_available": True,
                            "unpriced_call_count": 0,
                            "models": {"qwen3.5-flash": 40},
                            "task_counts": {"gmail_purpose_mode_classify": 36, "calendar_semantic_extract": 4},
                        },
                        "gmail": {
                            "successful_call_count": 36,
                            "total_tokens": 7200,
                            "estimated_cost_usd": 0.02,
                            "input_cost_usd": 0.006,
                            "cached_input_cost_usd": 0.004,
                            "output_cost_usd": 0.01,
                            "pricing_available": True,
                            "unpriced_call_count": 0,
                            "models": {"qwen3.5-flash": 36},
                            "task_counts": {"gmail_purpose_mode_classify": 36},
                        },
                        "ics": {
                            "successful_call_count": 4,
                            "total_tokens": 800,
                            "estimated_cost_usd": 0.004,
                            "input_cost_usd": 0.002,
                            "cached_input_cost_usd": 0.0,
                            "output_cost_usd": 0.002,
                            "pricing_available": True,
                            "unpriced_call_count": 0,
                            "models": {"qwen3.5-flash": 4},
                            "task_counts": {"calendar_semantic_extract": 4},
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        return {
            "success": True,
            "returncode": 0,
            "stdout": str(inner_run_dir) + "\n",
            "stderr": "",
            "log_path": str(Path(log_path)),
            "run_dir": str(inner_run_dir),
            "command": command,
        }

    monkeypatch.setattr(closeout.validation, "run_command", _run_command)

    result_dir = closeout.continue_closeout(run_dir)
    final_report = json.loads((run_dir / closeout.FINAL_REPORT_FILE).read_text(encoding="utf-8"))
    cost_summary = json.loads((run_dir / closeout.COST_SUMMARY_FILE).read_text(encoding="utf-8"))

    assert result_dir == run_dir
    assert final_report["overall_status"] == "passed"
    assert final_report["replay_finished"] is True
    assert final_report["qwen_model_ok"] is True
    assert final_report["gemini_call_count"] == 0
    assert cost_summary["overall"]["estimated_cost_usd"] == 0.024
    assert (run_dir / closeout.ACCEPTANCE_REPORT_COPY_FILE).is_file()
    assert (run_dir / closeout.REPLAY_REPORT_COPY_FILE).is_file()
