from __future__ import annotations

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
