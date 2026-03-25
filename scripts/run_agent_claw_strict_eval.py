#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings
from app.db.models.agents import ApprovalTicket, AgentProposal, McpToolInvocation
from app.db.session import get_session_factory, reset_engine
from scripts.run_claw_mcp_smoke import configure_smoke_database

OUTPUT_ROOT = REPO_ROOT / "output"
DEFAULT_EMAIL = "agent-live-eval@example.com"
DEFAULT_OTHER_EMAIL = "agent-live-eval-other@example.com"
DEFAULT_PASSWORD = "password123"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8210

STRICT_PYTEST_COMMANDS: list[list[str]] = [
    [sys.executable, "-m", "pytest", "-q", "tests/test_mcp_server.py"],
    [sys.executable, "-m", "pytest", "-q", "tests/test_mcp_invocations_api.py"],
    [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "tests/test_agent_proposals_api.py",
        "tests/test_agent_approval_tickets_api.py",
        "tests/test_agent_activity_api.py",
        "tests/test_agent_family_proposals_api.py",
    ],
    [sys.executable, "-m", "pytest", "-q", "tests/test_mcp_access_tokens_api.py"],
    [sys.executable, "-m", "pytest", "-q", "tests/test_claw_mcp_smoke.py"],
]
PYCOMPILE_COMMAND = [
    sys.executable,
    "-m",
    "py_compile",
    "services/mcp_server/main.py",
    "scripts/run_claw_mcp_smoke.py",
    "app/modules/agents/mcp_audit_service.py",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the strict closeout eval for the CalendarDIFF Agent + Claw mainline.")
    parser.add_argument("--output-root", default=str(OUTPUT_ROOT))
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--public-api-host", default=DEFAULT_HOST)
    parser.add_argument("--public-api-port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--other-email", default=DEFAULT_OTHER_EMAIL)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    started_at = datetime.now(UTC)
    run_dir = Path(args.output_root).expanduser().resolve() / f"agent-claw-closeout-{started_at.strftime('%Y%m%d-%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    settings = get_settings()
    target_database_url = str(args.database_url).strip() if args.database_url else settings.test_database_url
    env = build_eval_env(database_url=target_database_url, app_api_key=settings.app_api_key)
    excluded_dirty = summarize_dirty_categories(run_git_status())

    strict_results = [run_command(command, cwd=REPO_ROOT, env=env, log_dir=run_dir) for command in STRICT_PYTEST_COMMANDS]
    pycompile_result = run_command(PYCOMPILE_COMMAND, cwd=REPO_ROOT, env=env, log_dir=run_dir)

    live_eval_result: dict[str, Any] | None = None
    claw_smoke_result: dict[str, Any] | None = None
    live_eval_summary: dict[str, Any] | None = None
    claw_smoke_summary: dict[str, Any] | None = None
    db_audit: dict[str, Any] | None = None

    if all(result["success"] for result in strict_results + [pycompile_result]):
        configure_smoke_database(database_url=target_database_url)
        seed_result = run_command(
            [
                sys.executable,
                "scripts/seed_agent_live_eval_fixture.py",
                "--email",
                str(args.email),
                "--other-email",
                str(args.other_email),
                "--password",
                str(args.password),
            ],
            cwd=REPO_ROOT,
            env=env,
            log_dir=run_dir,
        )
        if seed_result["success"]:
            with managed_backend(env=env, host=str(args.public_api_host), port=int(args.public_api_port), log_dir=run_dir):
                live_eval_result = run_command(
                    [
                        sys.executable,
                        "scripts/run_agent_live_eval.py",
                        "run",
                        "--public-api-base",
                        f"http://{args.public_api_host}:{args.public_api_port}",
                        "--api-key",
                        settings.app_api_key,
                        "--email",
                        str(args.email),
                        "--password",
                        str(args.password),
                        "--cross-user-email",
                        str(args.other_email),
                        "--scenario-set",
                        "full",
                        "--output-root",
                        str(run_dir),
                    ],
                    cwd=REPO_ROOT,
                    env=env,
                    log_dir=run_dir,
                )

            claw_smoke_result = run_command(
                [
                    sys.executable,
                    "scripts/run_claw_mcp_smoke.py",
                    "--email",
                    str(args.email),
                    "--other-email",
                    str(args.other_email),
                    "--password",
                    str(args.password),
                    "--database-url",
                    target_database_url,
                    "--output-root",
                    str(run_dir),
                ],
                cwd=REPO_ROOT,
                env=env,
                log_dir=run_dir,
            )

            live_eval_summary = load_result_summary(live_eval_result, summary_filename="SUMMARY.json") if live_eval_result else None
            claw_smoke_summary = load_result_summary(claw_smoke_result, summary_filename="summary.json") if claw_smoke_result else None
            db_audit = inspect_claw_db_audit(database_url=target_database_url)

    final = build_final_report(
        started_at=started_at,
        excluded_dirty=excluded_dirty,
        strict_results=strict_results,
        pycompile_result=pycompile_result,
        live_eval_summary=live_eval_summary,
        claw_smoke_summary=claw_smoke_summary,
        db_audit=db_audit,
    )
    final["live_eval"] = live_eval_result
    final["claw_smoke"] = claw_smoke_result
    write_final_report(run_dir, final)
    print(run_dir)


def build_eval_env(*, database_url: str, app_api_key: str) -> dict[str, str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env["TEST_DATABASE_URL"] = database_url
    env["APP_API_KEY"] = app_api_key
    env["SCHEMA_GUARD_ENABLED"] = "true"
    env["INGEST_SERVICE_ENABLE_WORKER"] = "false"
    env["REVIEW_SERVICE_ENABLE_APPLY_WORKER"] = "false"
    env["NOTIFICATION_SERVICE_ENABLE_WORKER"] = "false"
    env["LLM_SERVICE_ENABLE_WORKER"] = "false"
    env["BOOTSTRAP_ADMIN_EMAIL"] = ""
    env["BOOTSTRAP_ADMIN_PASSWORD"] = ""
    return env


def run_git_status() -> str:
    completed = subprocess.run(["git", "status", "--short"], cwd=str(REPO_ROOT), capture_output=True, text=True)
    return completed.stdout or ""


def summarize_dirty_categories(status_output: str) -> dict[str, Any]:
    lines = [line.strip() for line in status_output.splitlines() if line.strip()]
    excluded = {
        "frontend": False,
        "llm_gateway": False,
        "sources": False,
        "openapi_snapshot": False,
    }
    paths: list[str] = []
    for line in lines:
        path = line.split(maxsplit=1)[-1].strip() if " " in line else line
        paths.append(path)
        if path.startswith("frontend/"):
            excluded["frontend"] = True
        if path.startswith("app/modules/llm_gateway/") or path.startswith("tests/test_llm_") or "0016_llm_invocation_logs.py" in path:
            excluded["llm_gateway"] = True
        if path.startswith("app/modules/sources/") or path.startswith("tests/test_source_"):
            excluded["sources"] = True
        if path == "contracts/openapi/public-service.json":
            excluded["openapi_snapshot"] = True
    return {"raw_paths": paths, "excluded_categories": excluded}


def run_command(command: list[str], *, cwd: Path, env: dict[str, str], log_dir: Path) -> dict[str, Any]:
    raw_name = "_".join(command[2:4]) if len(command) >= 4 and command[1] == "-m" else Path(command[1] if len(command) > 1 else command[0]).stem
    log_name = raw_name.replace("/", "_").replace("\\", "_").replace(" ", "_")
    log_path = log_dir / f"{log_name}.log"
    completed = subprocess.run(command, cwd=str(cwd), env=env, capture_output=True, text=True)
    combined = (completed.stdout or "") + (("\n" + completed.stderr) if completed.stderr else "")
    log_path.write_text(combined, encoding="utf-8")
    return {
        "command": command,
        "success": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "log_path": str(log_path),
        "run_dir": extract_run_dir(completed.stdout or ""),
    }


def extract_run_dir(stdout: str) -> str | None:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    for line in reversed(lines):
        if "/output/" in line:
            return line
    return None


def load_result_summary(result: dict[str, Any], *, summary_filename: str) -> dict[str, Any] | None:
    run_dir = result.get("run_dir")
    if not isinstance(run_dir, str) or not run_dir:
        return None
    path = Path(run_dir) / summary_filename
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


@contextmanager
def managed_backend(*, env: dict[str, str], host: str, port: int, log_dir: Path):
    log_path = log_dir / "strict_eval_backend.log"
    with log_path.open("w", encoding="utf-8") as handle:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "services.app_api.main:app",
                "--host",
                host,
                "--port",
                str(port),
            ],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
    try:
        wait_for_health(f"http://{host}:{port}/health")
        yield
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def wait_for_health(url: str, *, timeout_seconds: float = 30.0) -> None:
    started = time.monotonic()
    with httpx.Client(timeout=2.0) as client:
        while time.monotonic() - started < timeout_seconds:
            try:
                response = client.get(url)
                if response.status_code == 200:
                    return
            except Exception:
                pass
            time.sleep(0.5)
    raise RuntimeError(f"backend health did not become ready at {url}")


def inspect_claw_db_audit(*, database_url: str) -> dict[str, Any]:
    os.environ["DATABASE_URL"] = database_url
    os.environ["TEST_DATABASE_URL"] = database_url
    get_settings.cache_clear()
    reset_engine()
    session_factory = get_session_factory()
    with session_factory() as db:
        invocations = list(
            db.scalars(
                select(McpToolInvocation)
                .order_by(McpToolInvocation.created_at.desc(), McpToolInvocation.invocation_id.desc())
                .limit(50)
            ).all()
        )
        proposals = list(
            db.scalars(
                select(AgentProposal)
                .where(AgentProposal.origin_kind == "mcp")
                .order_by(AgentProposal.created_at.desc(), AgentProposal.id.desc())
            ).all()
        )
        tickets = list(
            db.scalars(
                select(ApprovalTicket)
                .where(ApprovalTicket.origin_kind == "mcp")
                .order_by(ApprovalTicket.created_at.desc(), ApprovalTicket.ticket_id.desc())
            ).all()
        )
    proposal_request_ids = {row.origin_request_id for row in proposals if isinstance(row.origin_request_id, str) and row.origin_request_id}
    ticket_request_ids = {row.origin_request_id for row in tickets if isinstance(row.origin_request_id, str) and row.origin_request_id}
    invocation_request_ids = {row.transport_request_id for row in invocations if isinstance(row.transport_request_id, str) and row.transport_request_id}
    return {
        "mcp_invocation_count": len(invocations),
        "proposal_count": len(proposals),
        "ticket_count": len(tickets),
        "latest_tool_names": [row.tool_name for row in invocations[:10]],
        "proposal_ticket_correlation_success": proposal_request_ids.issubset(invocation_request_ids) and ticket_request_ids.issubset(invocation_request_ids),
    }


def build_final_report(
    *,
    started_at: datetime,
    excluded_dirty: dict[str, Any],
    strict_results: list[dict[str, Any]],
    pycompile_result: dict[str, Any],
    live_eval_summary: dict[str, Any] | None,
    claw_smoke_summary: dict[str, Any] | None,
    db_audit: dict[str, Any] | None,
) -> dict[str, Any]:
    strict_pass = all(item["success"] for item in strict_results) and bool(pycompile_result["success"])
    live_eval_pass = bool(live_eval_summary and live_eval_summary.get("success_rate") == 1.0)
    claw_smoke_pass = bool(claw_smoke_summary and claw_smoke_summary.get("success") is True)
    steps = {row["name"]: row for row in (claw_smoke_summary or {}).get("steps", []) if isinstance(row, dict)}
    live_eval_actions = dict((live_eval_summary or {}).get("executable_actions_exercised") or {})
    tool_families = {
        "read_context": all(name in steps and steps[name]["ok"] for name in ("recent_activity_before", "workspace_context", "change_context", "family_context")),
        "proposal": all(name in steps and steps[name]["ok"] for name in ("change_proposal", "family_relink_preview")),
        "approval": all(name in steps and steps[name]["ok"] for name in ("approval_ticket_create", "approval_ticket_confirm")),
    }
    smoke_actions = {
        "change_decision": all(name in steps and steps[name]["ok"] for name in ("change_proposal", "approval_ticket_create", "approval_ticket_confirm")),
        "proposal_edit_commit": all(name in steps and steps[name]["ok"] for name in ("change_edit_commit_proposal", "change_edit_commit_ticket_create", "change_edit_commit_ticket_confirm")),
        "family_low_risk_execute": all(name in steps and steps[name]["ok"] for name in ("family_relink_commit_proposal", "family_relink_commit_ticket_create", "family_relink_commit_ticket_confirm")),
    }
    latest_tool_names = []
    if "settings_mcp_invocations" in steps:
        latest_tool_names = list((steps["settings_mcp_invocations"].get("payload") or {}).get("latest_tool_names") or [])
    proposal_ticket_correlation_success = bool((db_audit or {}).get("proposal_ticket_correlation_success"))
    family_relink_preview_non_executable = bool(
        "family_relink_preview" in steps
        and isinstance((steps["family_relink_preview"].get("payload") or {}), dict)
        and (steps["family_relink_preview"]["payload"] or {}).get("can_create_ticket") is False
    )
    settings_mcp_invocations_visible = bool("settings_mcp_invocations" in steps and steps["settings_mcp_invocations"]["ok"])
    live_eval_action_gate = all(
        bool(live_eval_actions.get(name))
        for name in (
            "change_decision",
            "proposal_edit_commit",
            "run_source_sync",
            "family_relink_commit",
            "label_learning_add_alias_commit",
        )
    )
    smoke_action_gate = all(smoke_actions.values())
    final_success = (
        strict_pass
        and live_eval_pass
        and claw_smoke_pass
        and live_eval_action_gate
        and smoke_action_gate
        and proposal_ticket_correlation_success
        and family_relink_preview_non_executable
        and settings_mcp_invocations_visible
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "started_at": started_at.isoformat(),
        "success": final_success,
        "passed": final_success,
        "layers": {
            "strict_pytests": strict_pass,
            "full_live_eval": live_eval_pass,
            "claw_smoke": claw_smoke_pass,
        },
        "tool_families_exercised": tool_families,
        "smoke_actions_exercised": smoke_actions,
        "executable_actions_exercised": live_eval_actions,
        "mcp_invocations_written": bool((db_audit or {}).get("mcp_invocation_count", 0)),
        "latest_tool_names_observed": latest_tool_names or (db_audit or {}).get("latest_tool_names") or [],
        "proposal_ticket_correlation_success": proposal_ticket_correlation_success,
        "family_relink_preview_non_executable": family_relink_preview_non_executable,
        "settings_mcp_invocations_visible": settings_mcp_invocations_visible,
        "openapi_snapshot_refresh_deferred": True,
        "excluded_dirty_worktrees": excluded_dirty,
        "deferred_items": [
            "OpenAPI snapshot refresh intentionally deferred",
            "frontend/* dirty worktree intentionally excluded",
            "llm_gateway/* dirty worktree intentionally excluded",
            "sources/* dirty worktree intentionally excluded",
            "Telegram/Slack/WeChat expansion intentionally deferred",
        ],
        "strict_commands": strict_results + [pycompile_result],
        "live_eval_summary": live_eval_summary,
        "claw_smoke_summary": claw_smoke_summary,
        "db_audit": db_audit,
    }


def write_final_report(run_dir: Path, report: dict[str, Any]) -> None:
    (run_dir / "FINAL_REPORT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Agent + Claw Closeout",
        "",
        f"- Generated at: {report['generated_at']}",
        f"- Success: {'yes' if report['success'] else 'no'}",
        "",
        "## Layers",
        "",
        f"- Strict pytests: {'PASS' if report['layers']['strict_pytests'] else 'FAIL'}",
        f"- Full live eval: {'PASS' if report['layers']['full_live_eval'] else 'FAIL'}",
        f"- Claw smoke: {'PASS' if report['layers']['claw_smoke'] else 'FAIL'}",
        "",
        "## Tool Families",
        "",
        f"- Read/context exercised: {report['tool_families_exercised']['read_context']}",
        f"- Proposal exercised: {report['tool_families_exercised']['proposal']}",
        f"- Approval exercised: {report['tool_families_exercised']['approval']}",
        f"- Smoke change decision exercised: {report['smoke_actions_exercised']['change_decision']}",
        f"- Smoke proposal edit exercised: {report['smoke_actions_exercised']['proposal_edit_commit']}",
        f"- Smoke family executable exercised: {report['smoke_actions_exercised']['family_low_risk_execute']}",
        "",
        "## Audit",
        "",
        f"- MCP invocations written: {report['mcp_invocations_written']}",
        f"- Proposal/ticket correlation success: {report['proposal_ticket_correlation_success']}",
        f"- Family relink preview stayed non-executable: {report['family_relink_preview_non_executable']}",
        f"- Settings MCP invocation surface visible: {report['settings_mcp_invocations_visible']}",
        f"- Latest tool names observed: {', '.join(report['latest_tool_names_observed']) if report['latest_tool_names_observed'] else 'none'}",
        "",
        "## Executable Actions",
        "",
        f"- Change decision exercised: {report['executable_actions_exercised'].get('change_decision')}",
        f"- Proposal edit commit exercised: {report['executable_actions_exercised'].get('proposal_edit_commit')}",
        f"- Source sync exercised: {report['executable_actions_exercised'].get('run_source_sync')}",
        f"- Family relink commit exercised: {report['executable_actions_exercised'].get('family_relink_commit')}",
        f"- Label learning commit exercised: {report['executable_actions_exercised'].get('label_learning_add_alias_commit')}",
        "",
        "## Deferred",
        "",
    ]
    for item in report["deferred_items"]:
        lines.append(f"- {item}")
    lines.append("")
    (run_dir / "FINAL_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
