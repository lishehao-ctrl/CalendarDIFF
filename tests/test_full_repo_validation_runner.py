from __future__ import annotations

import argparse
from pathlib import Path

import pytest

import scripts.run_full_repo_validation as validation


@pytest.fixture(scope="session", autouse=True)
def configure_test_environment() -> None:
    return None


@pytest.fixture(scope="session")
def db_engine() -> None:
    return None


@pytest.fixture(autouse=True)
def clean_database() -> None:
    return None


def test_reset_frontend_dist_dir_removes_existing_tree(tmp_path: Path) -> None:
    frontend_dir = tmp_path / "frontend"
    dist_dir = frontend_dir / ".next-prod"
    dist_dir.mkdir(parents=True)
    (dist_dir / "artifact.txt").write_text("stale", encoding="utf-8")

    validation.reset_frontend_dist_dir(frontend_dir, dist_dir=".next-prod")

    assert not dist_dir.exists()


def test_run_preflight_passes_without_docker_daemon_when_services_are_already_reachable(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(validation, "_command_exists", lambda command: True)
    monkeypatch.setattr(validation, "_python_import_check", lambda: True)
    monkeypatch.setattr(validation, "_docker_daemon_available", lambda: False)
    monkeypatch.setattr(validation, "_port_open", lambda port: True if port in {5432, 6379} else False)
    monkeypatch.setattr(validation, "_try_start_infra", lambda run_dir: {"status": "unexpected"})

    preflight = validation.run_preflight(run_dir=tmp_path)

    assert preflight["ok"] is True
    assert preflight["infra_attempted"] is False


def test_run_preflight_attempts_compose_only_when_service_missing(monkeypatch, tmp_path: Path) -> None:
    calls = {"count": 0}

    def _port_open(port: int) -> bool:
        if port == 5432:
            return True
        if port == 6379:
            return calls["count"] > 0
        return False

    def _try_start_infra(*, run_dir):  # type: ignore[no-untyped-def]
        calls["count"] += 1
        return {"status": "ok", "log_path": str(run_dir / "compose.log")}

    monkeypatch.setattr(validation, "_command_exists", lambda command: True)
    monkeypatch.setattr(validation, "_python_import_check", lambda: True)
    monkeypatch.setattr(validation, "_docker_daemon_available", lambda: True)
    monkeypatch.setattr(validation, "_port_open", _port_open)
    monkeypatch.setattr(validation, "_try_start_infra", _try_start_infra)

    preflight = validation.run_preflight(run_dir=tmp_path)

    assert preflight["ok"] is True
    assert preflight["infra_attempted"] is True
    assert calls["count"] == 1


def test_build_final_report_marks_later_stages_not_run_after_preflight_failure(tmp_path: Path) -> None:
    report = validation.build_final_report(
        branch="main",
        head="abc123",
        failed_stage="Preflight",
        run_dir=tmp_path,
        preflight={"ok": False, "details": {}},
        engineering=None,
        agent_claw=None,
        replay=None,
    )

    assert report["overall_status"] == "failed"
    assert report["failed_stage"] == "Preflight"
    assert report["stages"]["engineering_full"]["status"] == "not_run"
    assert report["stages"]["agent_claw_closeout"]["status"] == "not_run"
    assert report["stages"]["year_timeline_replay"]["status"] == "not_run"


def test_replay_report_finished_requires_terminal_state() -> None:
    assert validation._replay_report_finished({"finished": True, "awaiting_manual": False}) is True
    assert validation._replay_report_finished({"finished": False, "awaiting_manual": False}) is False
    assert validation._replay_report_finished({"finished": True, "awaiting_manual": True}) is False
    assert validation._replay_report_finished(None) is False


def test_build_agent_claw_closeout_command_includes_frontend_base(tmp_path: Path) -> None:
    args = argparse.Namespace(
        strict_eval_db_url="postgresql+psycopg://postgres:postgres@localhost:5432/deadline_diff_agent_claw_eval",
        strict_eval_frontend_base="http://127.0.0.1:3001",
        public_api_host="127.0.0.1",
        strict_eval_port=8210,
    )

    command = validation.build_agent_claw_closeout_command(run_dir=tmp_path, args=args)

    assert command[-2:] == ["--frontend-base", "http://127.0.0.1:3001"]


def test_run_year_timeline_replay_allows_more_than_24_status_checks(monkeypatch, tmp_path: Path) -> None:
    replay_run_dir = tmp_path / "year-timeline-replay"
    replay_run_dir.mkdir()
    status_calls = {"count": 0}

    monkeypatch.setattr(validation, "build_stage_env", lambda **kwargs: {"APP_API_KEY": kwargs["app_api_key"]})
    monkeypatch.setattr(validation, "validate_replay_llm_env", lambda env: None)
    monkeypatch.setattr(validation, "recreate_postgres_database", lambda database_url: None)
    monkeypatch.setattr(validation.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(validation.time, "time", lambda: 0.0)

    from contextlib import contextmanager

    @contextmanager
    def _managed_backend(**kwargs):  # type: ignore[no-untyped-def]
        yield

    monkeypatch.setattr(validation, "managed_backend", _managed_backend)

    def _run_command(*, command, cwd, env, log_path):  # type: ignore[no-untyped-def]
        del cwd, env
        if command[1] == "scripts/run_year_timeline_replay_smoke.py" and command[2] == "start":
            validation._write_json(
                replay_run_dir / "state.json",
                {"finished": False, "awaiting_manual": False, "current_checkpoint_index": 0, "next_global_batch": 1},
            )
            Path(log_path).write_text(str(replay_run_dir) + "\n", encoding="utf-8")
            return {
                "command": command,
                "success": True,
                "returncode": 0,
                "stdout": str(replay_run_dir) + "\n",
                "stderr": "",
                "log_path": str(log_path),
                "run_dir": str(replay_run_dir),
            }
        if command[1] == "scripts/run_year_timeline_replay_smoke.py" and command[2] == "status":
            status_calls["count"] += 1
            finished = status_calls["count"] >= 25
            payload = {
                "run_id": "year-timeline-replay-test",
                "finished": finished,
                "awaiting_manual": False,
                "current_checkpoint_index": status_calls["count"],
                "next_global_batch": status_calls["count"] + 1,
            }
            validation._write_json(replay_run_dir / "state.json", payload)
            Path(log_path).write_text(validation.json.dumps(payload), encoding="utf-8")
            return {
                "command": command,
                "success": True,
                "returncode": 0,
                "stdout": validation.json.dumps(payload),
                "stderr": "",
                "log_path": str(log_path),
                "run_dir": None,
            }
        if command[1] == "scripts/run_year_timeline_replay_smoke.py" and command[2] == "report":
            report_payload = {"finished": True, "awaiting_manual": False}
            validation._write_json(replay_run_dir / "report.json", report_payload)
            Path(log_path).write_text(validation.json.dumps(report_payload), encoding="utf-8")
            return {
                "command": command,
                "success": True,
                "returncode": 0,
                "stdout": validation.json.dumps(report_payload),
                "stderr": "",
                "log_path": str(log_path),
                "run_dir": None,
            }
        raise AssertionError(command)

    monkeypatch.setattr(validation, "run_command", _run_command)

    result = validation.run_year_timeline_replay(
        run_dir=tmp_path,
        database_url="postgresql+psycopg://postgres:postgres@localhost:5432/deadline_diff_replay_eval",
        redis_url=validation.DEFAULT_REPLAY_REDIS_URL,
        app_api_key="test-api-key",
        host="127.0.0.1",
        port=8212,
        replay_time_budget_seconds=60,
    )

    assert result["ok"] is True
    assert status_calls["count"] == 25
