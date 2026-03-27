#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import shutil
import sys
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from sqlalchemy import create_engine, text

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings
from app.db.session import reset_engine
from app.modules.llm_gateway.registry import validate_ingestion_llm_config

OUTPUT_ROOT = REPO_ROOT / "output"
DEFAULT_STRICT_EVAL_DB = "postgresql+psycopg://postgres:postgres@localhost:5432/deadline_diff_agent_claw_eval"
DEFAULT_REPLAY_DB = "postgresql+psycopg://postgres:postgres@localhost:5432/deadline_diff_replay_eval"
DEFAULT_TEST_REDIS_URL = "redis://127.0.0.1:6379/15"
DEFAULT_STRICT_REDIS_URL = "redis://127.0.0.1:6379/14"
DEFAULT_REPLAY_REDIS_URL = "redis://127.0.0.1:6379/13"
DEFAULT_STRICT_EVAL_FRONTEND_BASE = "http://127.0.0.1:3000"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run full local CalendarDIFF repo validation.")
    parser.add_argument("--output-root", default=str(OUTPUT_ROOT))
    parser.add_argument("--strict-eval-db-url", default=DEFAULT_STRICT_EVAL_DB)
    parser.add_argument("--strict-eval-frontend-base", default=DEFAULT_STRICT_EVAL_FRONTEND_BASE)
    parser.add_argument("--replay-db-url", default=DEFAULT_REPLAY_DB)
    parser.add_argument("--public-api-host", default="127.0.0.1")
    parser.add_argument("--replay-port", type=int, default=8212)
    parser.add_argument("--strict-eval-port", type=int, default=8210)
    return parser.parse_args()


def build_agent_claw_closeout_command(*, run_dir: Path, args: argparse.Namespace) -> list[str]:
    return [
        sys.executable,
        "scripts/run_agent_claw_strict_eval.py",
        "--output-root",
        str(run_dir / "agent-claw"),
        "--database-url",
        str(args.strict_eval_db_url),
        "--public-api-host",
        str(args.public_api_host),
        "--public-api-port",
        str(args.strict_eval_port),
        "--frontend-base",
        str(args.strict_eval_frontend_base),
    ]


def main() -> None:
    args = parse_args()
    started_at = datetime.now(UTC)
    run_dir = Path(args.output_root).expanduser().resolve() / f"full-repo-validation-{started_at.strftime('%Y%m%d-%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    _write_text(run_dir / "git_status.txt", _run_simple(["git", "status", "--short"]).stdout)
    branch = _run_simple(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    head = _run_simple(["git", "rev-parse", "HEAD"]).stdout.strip()
    _write_text(run_dir / "git_head.txt", f"{branch}\n{head}\n")
    _write_env_summary(run_dir / "env_summary.md")

    preflight = run_preflight(run_dir=run_dir)
    _write_text(run_dir / "preflight.md", render_preflight(preflight=preflight, branch=branch, head=head))
    if not preflight["ok"]:
        final = build_final_report(
            branch=branch,
            head=head,
            failed_stage="Preflight",
            run_dir=run_dir,
            preflight=preflight,
            engineering=None,
            agent_claw=None,
            replay=None,
        )
        write_final_report(run_dir=run_dir, report=final)
        print(run_dir)
        return

    engineering = run_engineering_full(run_dir=run_dir)
    _write_json(run_dir / "engineering_summary.json", engineering)
    if not engineering["ok"]:
        final = build_final_report(
            branch=branch,
            head=head,
            failed_stage="Engineering Full",
            run_dir=run_dir,
            preflight=preflight,
            engineering=engineering,
            agent_claw=None,
            replay=None,
        )
        write_final_report(run_dir=run_dir, report=final)
        print(run_dir)
        return

    settings = get_settings()
    strict_env = build_stage_env(
        database_url=str(args.strict_eval_db_url),
        redis_url=DEFAULT_STRICT_REDIS_URL,
        app_api_key=settings.app_api_key,
    )
    strict_eval = run_command(
        command=build_agent_claw_closeout_command(run_dir=run_dir, args=args),
        cwd=REPO_ROOT,
        env=strict_env,
        log_path=run_dir / "agent_claw.log",
    )
    strict_summary = _load_nested_report(strict_eval, "FINAL_REPORT.json")
    agent_claw = {
        "ok": strict_eval["success"] and isinstance(strict_summary, dict) and bool(strict_summary.get("passed", strict_summary.get("success"))),
        "command": strict_eval["command"],
        "log_path": strict_eval["log_path"],
        "run_dir": strict_eval.get("run_dir"),
        "summary": strict_summary,
    }
    _write_json(run_dir / "agent_claw_summary.json", agent_claw)
    if not agent_claw["ok"]:
        final = build_final_report(
            branch=branch,
            head=head,
            failed_stage="Agent/Claw Closeout",
            run_dir=run_dir,
            preflight=preflight,
            engineering=engineering,
            agent_claw=agent_claw,
            replay=None,
        )
        write_final_report(run_dir=run_dir, report=final)
        print(run_dir)
        return

    replay = run_year_timeline_replay(
        run_dir=run_dir,
        database_url=str(args.replay_db_url),
        redis_url=DEFAULT_REPLAY_REDIS_URL,
        app_api_key=settings.app_api_key,
        host=str(args.public_api_host),
        port=int(args.replay_port),
    )
    _write_json(run_dir / "replay_summary.json", replay)

    failed_stage = None if replay["ok"] else "Year Timeline Replay"
    final = build_final_report(
        branch=branch,
        head=head,
        failed_stage=failed_stage,
        run_dir=run_dir,
        preflight=preflight,
        engineering=engineering,
        agent_claw=agent_claw,
        replay=replay,
    )
    write_final_report(run_dir=run_dir, report=final)
    print(run_dir)


def run_preflight(*, run_dir: Path) -> dict[str, Any]:
    details: dict[str, Any] = {
        "frontend_node_modules": (REPO_ROOT / "frontend" / "node_modules").is_dir(),
        "docker_compose_installed": _command_exists(["docker", "compose", "version"]),
        "python_imports_ok": _python_import_check(),
        "manifest_present": (REPO_ROOT / "data" / "synthetic" / "year_timeline_demo" / "year_timeline_manifest.json").is_file(),
        "email_pool_present": (REPO_ROOT / "tests" / "fixtures" / "private" / "email_pool" / "year_timeline_full_sim").is_dir(),
        "postgres_5432": _port_open(5432),
        "redis_6379": _port_open(6379),
        "docker_daemon": _docker_daemon_available(),
    }
    infra_attempted = False
    infra_result: dict[str, Any] | None = None
    if not details["postgres_5432"] or not details["redis_6379"]:
        if details["docker_compose_installed"]:
            infra_attempted = True
            infra_result = _try_start_infra(run_dir=run_dir)
            details["postgres_5432"] = _port_open(5432)
            details["redis_6379"] = _port_open(6379)
            details["docker_daemon"] = _docker_daemon_available()
    ok = all(
        bool(details[key])
        for key in (
            "frontend_node_modules",
            "docker_compose_installed",
            "python_imports_ok",
            "manifest_present",
            "email_pool_present",
            "postgres_5432",
            "redis_6379",
        )
    )
    return {
        "ok": ok,
        "details": details,
        "infra_attempted": infra_attempted,
        "infra_result": infra_result,
    }


def run_engineering_full(*, run_dir: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env["REDIS_URL"] = os.getenv("REDIS_URL", DEFAULT_TEST_REDIS_URL) or DEFAULT_TEST_REDIS_URL
    backend = run_command(
        command=[sys.executable, "-m", "pytest", "-q"],
        cwd=REPO_ROOT,
        env=env,
        log_path=run_dir / "backend_pytest.log",
    )
    typecheck = run_command(
        command=["npm", "run", "typecheck"],
        cwd=REPO_ROOT / "frontend",
        env=os.environ.copy(),
        log_path=run_dir / "frontend_typecheck.log",
    )
    lint = run_command(
        command=["npm", "run", "lint"],
        cwd=REPO_ROOT / "frontend",
        env=os.environ.copy(),
        log_path=run_dir / "frontend_lint.log",
    )
    reset_frontend_dist_dir(REPO_ROOT / "frontend", dist_dir=".next-prod")
    build_env = os.environ.copy()
    build_env["NEXT_DIST_DIR"] = ".next-prod"
    build = run_command(
        command=["npm", "run", "build"],
        cwd=REPO_ROOT / "frontend",
        env=build_env,
        log_path=run_dir / "frontend_build.log",
    )
    ok = all(row["success"] for row in (backend, typecheck, lint, build))
    return {
        "ok": ok,
        "backend_pytest": backend,
        "frontend": {
            "typecheck": typecheck,
            "lint": lint,
            "build": build,
        },
    }


def reset_frontend_dist_dir(frontend_dir: Path, *, dist_dir: str) -> None:
    target = frontend_dir / dist_dir
    if target.exists():
        shutil.rmtree(target)


def run_year_timeline_replay(
    *,
    run_dir: Path,
    database_url: str,
    redis_url: str,
    app_api_key: str,
    host: str,
    port: int,
) -> dict[str, Any]:
    env = build_stage_env(database_url=database_url, redis_url=redis_url, app_api_key=app_api_key)
    env["INGEST_SERVICE_ENABLE_WORKER"] = "true"
    env["REVIEW_SERVICE_ENABLE_APPLY_WORKER"] = "true"
    env["LLM_SERVICE_ENABLE_WORKER"] = "true"
    env["GMAIL_API_BASE_URL"] = "http://127.0.0.1:8765/gmail/v1/users/me"
    env["GMAIL_SECONDARY_FILTER_MODE"] = "off"
    env["GMAIL_SECONDARY_FILTER_PROVIDER"] = "noop"
    live_llm_error = validate_replay_llm_env(env)
    if live_llm_error is not None:
        return {
            "ok": False,
            "start": None,
            "status_checks": [],
            "report": None,
            "report_json": None,
            "backend_log": None,
            "replay_run_dir": None,
            "live_llm_error": live_llm_error,
        }
    recreate_postgres_database(database_url)
    backend_log = run_dir / "replay_backend.log"
    with managed_backend(
        env=env,
        host=host,
        port=port,
        log_path=backend_log,
    ):
        start = run_command(
            command=[
                sys.executable,
                "scripts/run_year_timeline_replay_smoke.py",
                "start",
                "--public-api-base",
                f"http://{host}:{port}",
                "--api-key",
                app_api_key,
                "--manifest",
                "data/synthetic/year_timeline_demo/year_timeline_manifest.json",
                "--email-bucket",
                "year_timeline_full_sim",
                "--ics-derived-set",
                "year_timeline_smoke_16",
                "--fake-provider-host",
                "127.0.0.1",
                "--fake-provider-port",
                "8765",
                "--start-fake-provider",
            ],
            cwd=REPO_ROOT,
            env=env,
            log_path=run_dir / "replay_start.log",
        )
        replay_run_dir = start.get("run_dir")
        if not start["success"] or not replay_run_dir:
            return {
                "ok": False,
                "start": start,
                "status_checks": [],
                "report": None,
                "backend_log": str(backend_log),
            }

        replay_run_path = Path(replay_run_dir)
        _write_text(run_dir / "replay_run_dir.txt", str(replay_run_path) + "\n")
        status_checks: list[dict[str, Any]] = []
        for _ in range(24):
            status = run_command(
                command=[
                    sys.executable,
                    "scripts/run_year_timeline_replay_smoke.py",
                    "status",
                    "--run-dir",
                    str(replay_run_path),
                ],
                cwd=REPO_ROOT,
                env=env,
                log_path=run_dir / f"replay_status_{len(status_checks)+1:02d}.log",
            )
            status_checks.append(status)
            text = (status.get("stdout") or "") + "\n" + (status.get("stderr") or "")
            status_payload = _parse_json_blob(status.get("stdout"))
            state = _load_json_if_exists(replay_run_path / "state.json")
            awaiting_manual = bool(
                (isinstance(status_payload, dict) and status_payload.get("awaiting_manual"))
                or (isinstance(state, dict) and state.get("awaiting_manual"))
                or ("awaiting manual checkpoint" in text.lower())
            )
            if awaiting_manual:
                resume = run_command(
                    command=[
                        sys.executable,
                        "scripts/run_year_timeline_replay_smoke.py",
                        "resume",
                        "--run-dir",
                        str(replay_run_path),
                    ],
                    cwd=REPO_ROOT,
                    env=env,
                    log_path=run_dir / f"replay_resume_{len(status_checks):02d}.log",
                )
                status_checks.append(resume)
            if isinstance(state, dict) and bool(state.get("finished")):
                break
            time.sleep(5)

        report = run_command(
            command=[
                sys.executable,
                "scripts/run_year_timeline_replay_smoke.py",
                "report",
                "--run-dir",
                str(replay_run_path),
            ],
            cwd=REPO_ROOT,
            env=env,
            log_path=run_dir / "replay_report.log",
        )
        report_json = _load_json_if_exists(replay_run_path / "report.json")
        replay_finished = _replay_report_finished(report_json)
        report_summary = {
            "ok": report["success"] and replay_finished,
            "start": start,
            "status_checks": status_checks,
            "report": report,
            "report_json": report_json,
            "backend_log": str(backend_log),
            "replay_run_dir": str(replay_run_path),
        }
        return report_summary


def build_stage_env(*, database_url: str, redis_url: str, app_api_key: str) -> dict[str, str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env["TEST_DATABASE_URL"] = database_url
    env["REDIS_URL"] = redis_url
    env["APP_API_KEY"] = app_api_key
    env["SCHEMA_GUARD_ENABLED"] = "true"
    env["INGEST_SERVICE_ENABLE_WORKER"] = "false"
    env["REVIEW_SERVICE_ENABLE_APPLY_WORKER"] = "false"
    env["NOTIFICATION_SERVICE_ENABLE_WORKER"] = "false"
    env["LLM_SERVICE_ENABLE_WORKER"] = "false"
    env["BOOTSTRAP_ADMIN_EMAIL"] = ""
    env["BOOTSTRAP_ADMIN_PASSWORD"] = ""
    return env


@contextmanager
def applied_env(overrides: dict[str, str]):
    original = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(overrides)
        get_settings.cache_clear()
        reset_engine()
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)
        get_settings.cache_clear()
        reset_engine()


def validate_replay_llm_env(env: dict[str, str]) -> str | None:
    try:
        with applied_env(env):
            validate_ingestion_llm_config()
    except Exception as exc:
        return f"live LLM provider not configured: {exc}"
    return None


@contextmanager
def managed_backend(*, env: dict[str, str], host: str, port: int, log_path: Path):
    terminate_processes_on_port(port)
    with log_path.open("w", encoding="utf-8") as handle:
        process = subprocess.Popen(
            [
                "sh",
                "./scripts/start_service.sh",
            ],
            cwd=str(REPO_ROOT),
            env={
                **env,
                "SERVICE_NAME": "backend",
                "HOST": host,
                "PORT": str(port),
                "RUN_MIGRATIONS": "true",
            },
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
    try:
        wait_for_http(f"http://{host}:{port}/health", timeout_seconds=90.0)
        yield
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def wait_for_http(url: str, *, timeout_seconds: float) -> None:
    started = time.monotonic()
    while time.monotonic() - started < timeout_seconds:
        try:
            result = subprocess.run(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", url],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.stdout.strip() == "200":
                return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError(f"backend did not become healthy at {url}")


def recreate_postgres_database(database_url: str) -> None:
    if not database_url.startswith("postgresql"):
        return
    db_name = database_url.rsplit("/", 1)[-1]
    admin_url = database_url.rsplit("/", 1)[0] + "/postgres"
    engine = create_engine(admin_url, future=True, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        engine.dispose()


def terminate_processes_on_port(port: int) -> None:
    try:
        completed = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return
    pids = [int(line.strip()) for line in (completed.stdout or "").splitlines() if line.strip().isdigit()]
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
        except Exception:
            continue
    if pids:
        time.sleep(1)


def build_final_report(
    *,
    branch: str,
    head: str,
    failed_stage: str | None,
    run_dir: Path,
    preflight: dict[str, Any],
    engineering: dict[str, Any] | None,
    agent_claw: dict[str, Any] | None,
    replay: dict[str, Any] | None,
) -> dict[str, Any]:
    overall_ok = failed_stage is None
    return {
        "run_dir": str(run_dir.resolve()),
        "branch": branch,
        "commit": head,
        "overall_status": "passed" if overall_ok else "failed",
        "failed_stage": failed_stage,
        "stages": {
            "preflight": preflight,
            "engineering_full": engineering or {"status": "not_run"},
            "agent_claw_closeout": agent_claw or {"status": "not_run"},
            "year_timeline_replay": replay or {"status": "not_run"},
        },
        "artifacts": {
            "git_status": str((run_dir / "git_status.txt").resolve()),
            "git_head": str((run_dir / "git_head.txt").resolve()),
            "env_summary": str((run_dir / "env_summary.md").resolve()),
            "preflight": str((run_dir / "preflight.md").resolve()),
        },
    }


def write_final_report(*, run_dir: Path, report: dict[str, Any]) -> None:
    _write_json(run_dir / "FINAL_REPORT.json", report)
    lines = [
        "# CalendarDIFF Full Repo Validation",
        "",
        f"- Overall: **{report['overall_status']}**",
        f"- Failed stage: **{report['failed_stage'] or 'none'}**",
        f"- Branch: `{report['branch']}`",
        f"- HEAD: `{report['commit']}`",
        "",
        "## Stage Results",
        "",
        f"- Preflight: {'passed' if report['stages']['preflight']['ok'] else 'failed'}",
        f"- Engineering Full: {_stage_status(report['stages']['engineering_full'])}",
        f"- Agent/Claw Closeout: {_stage_status(report['stages']['agent_claw_closeout'])}",
        f"- Year Timeline Replay: {_stage_status(report['stages']['year_timeline_replay'])}",
        "",
    ]
    replay_stage = report["stages"]["year_timeline_replay"]
    if isinstance(replay_stage, dict) and replay_stage.get("live_llm_error"):
        lines.extend(
            [
                "## Live LLM",
                "",
                f"- Replay env error: `{replay_stage['live_llm_error']}`",
                "",
            ]
        )
    lines.extend(
        [
        "## Artifacts",
        "",
        "- `git_status.txt`",
        "- `git_head.txt`",
        "- `env_summary.md`",
        "- `preflight.md`",
        "- `FINAL_REPORT.json`",
    ]
    )
    _write_text(run_dir / "FINAL_REPORT.md", "\n".join(lines) + "\n")


def render_preflight(*, preflight: dict[str, Any], branch: str, head: str) -> str:
    details = preflight["details"]
    lines = [
        "# Preflight",
        "",
        f"- Branch: `{branch}`",
        f"- HEAD: `{head}`",
        f"- `frontend/node_modules`: {'present' if details['frontend_node_modules'] else 'missing'}",
        f"- `docker compose`: {'installed' if details['docker_compose_installed'] else 'missing'}",
        f"- Docker daemon: {'available' if details['docker_daemon'] else 'unavailable'}",
        f"- `data/synthetic/year_timeline_demo/year_timeline_manifest.json`: {'present' if details['manifest_present'] else 'missing'}",
        f"- `tests/fixtures/private/email_pool/year_timeline_full_sim/`: {'present' if details['email_pool_present'] else 'missing'}",
        f"- Port `5432` (PostgreSQL): {'open' if details['postgres_5432'] else 'closed'}",
        f"- Port `6379` (Redis): {'open' if details['redis_6379'] else 'closed'}",
        "",
        "## Result",
        "",
        "Preflight passed." if preflight["ok"] else "Preflight failed.",
    ]
    if preflight["infra_attempted"]:
        lines.extend(
            [
                "",
                "## Infra Attempt",
                "",
                f"- Attempted compose startup: {'yes' if preflight['infra_attempted'] else 'no'}",
                f"- Compose result: {preflight['infra_result']['status'] if preflight['infra_result'] else 'n/a'}",
            ]
        )
    return "\n".join(lines) + "\n"


def _try_start_infra(*, run_dir: Path) -> dict[str, Any]:
    log_path = run_dir / "preflight_compose.log"
    result = run_command(
        command=["docker", "compose", "up", "-d", "postgres", "redis"],
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        log_path=log_path,
    )
    return {"status": "ok" if result["success"] else "failed", "log_path": str(log_path)}


def run_command(*, command: list[str], cwd: Path, env: dict[str, str], log_path: Path) -> dict[str, Any]:
    completed = subprocess.run(command, cwd=str(cwd), env=env, capture_output=True, text=True)
    combined = (completed.stdout or "") + (("\n" + completed.stderr) if completed.stderr else "")
    _write_text(log_path, combined)
    return {
        "command": command,
        "success": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "log_path": str(log_path.resolve()),
        "run_dir": extract_run_dir(completed.stdout or ""),
    }


def extract_run_dir(stdout: str) -> str | None:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    for line in reversed(lines):
        if "/output/" in line:
            return line
    return None


def _load_nested_report(result: dict[str, Any], filename: str) -> dict[str, Any] | None:
    run_dir = result.get("run_dir")
    if not isinstance(run_dir, str) or not run_dir:
        return None
    return _load_json_if_exists(Path(run_dir) / filename)


def _load_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_json_blob(value: object) -> dict[str, Any] | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = json.loads(value)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _replay_report_finished(report_json: dict[str, Any] | None) -> bool:
    return bool(
        isinstance(report_json, dict)
        and report_json.get("finished") is True
        and report_json.get("awaiting_manual") is False
    )


def _stage_status(stage: dict[str, Any]) -> str:
    if "status" in stage:
        return str(stage["status"])
    return "passed" if stage.get("ok") else "failed"


def _port_open(port: int) -> bool:
    sock = socket.socket()
    sock.settimeout(1)
    try:
        sock.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _docker_daemon_available() -> bool:
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=3)
        return result.returncode == 0
    except Exception:
        return False


def _command_exists(command: list[str]) -> bool:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


def _run_simple(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=str(REPO_ROOT), capture_output=True, text=True, check=False)


def _python_import_check() -> bool:
    code = (
        "import importlib;"
        "mods=['fastapi','sqlalchemy','alembic','httpx','redis','pydantic_settings','mcp'];"
        "[importlib.import_module(m) for m in mods]"
    )
    try:
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except Exception:
        return False


def _write_env_summary(path: Path) -> None:
    env_map = {k: v for k, v in dotenv_values(REPO_ROOT / ".env").items() if isinstance(k, str)} if (REPO_ROOT / ".env").exists() else {}
    keys = [
        "APP_API_KEY",
        "DATABASE_URL",
        "TEST_DATABASE_URL",
        "REDIS_URL",
        "INGESTION_LLM_PROVIDER_ID",
        "AGENT_LLM_PROVIDER_ID",
    ]
    lines = ["# Env Summary", ""]
    for key in keys:
        lines.append(f"- `{key}`: {'set' if env_map.get(key) else 'unset'}")
    _write_text(path, "\n".join(lines) + "\n")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
