#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.run_full_repo_validation as validation

OUTPUT_ROOT = REPO_ROOT / "output"
STATE_FILE = "closeout_state.json"
FINAL_REPORT_FILE = "FINAL_REPORT.json"
FINAL_REPORT_MD_FILE = "FINAL_REPORT.md"
REPLAY_REPORT_COPY_FILE = "replay_report.json"
ACCEPTANCE_REPORT_COPY_FILE = "backend-acceptance-report.json"
COST_SUMMARY_FILE = "cost_summary.json"
REPLAY_RUN_DIR_FILE = "replay_run_dir.txt"
BACKEND_LOG_FILE = "backend.log"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run managed live replay closeout with final artifact packaging.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start")
    start.add_argument("--output-root", default=str(OUTPUT_ROOT))
    start.add_argument("--database-url", default=validation.DEFAULT_REPLAY_DB)
    start.add_argument("--redis-url", default=validation.DEFAULT_REPLAY_REDIS_URL)
    start.add_argument("--public-api-host", default="127.0.0.1")
    start.add_argument("--public-api-port", type=int, default=8212)
    start.add_argument("--time-budget-seconds", type=int, default=4 * 60 * 60)
    start.add_argument("--max-checkpoints", type=int, default=None)

    cont = subparsers.add_parser("continue")
    cont.add_argument("--run-dir", required=True)
    cont.add_argument("--time-budget-seconds", type=int, default=None)
    cont.add_argument("--max-checkpoints", type=int, default=None)

    report = subparsers.add_parser("report")
    report.add_argument("--run-dir", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "start":
        run_dir = start_closeout(args)
        print(run_dir)
        return
    run_dir = Path(args.run_dir).expanduser().resolve()
    if args.command == "continue":
        result_dir = continue_closeout(
            run_dir,
            time_budget_seconds=args.time_budget_seconds,
            max_checkpoints=args.max_checkpoints,
        )
        print(result_dir)
        return
    report = refresh_closeout_artifacts(run_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def start_closeout(args: argparse.Namespace) -> Path:
    started_at = datetime.now(UTC)
    run_dir = Path(args.output_root).expanduser().resolve() / f"live-replay-closeout-{started_at.strftime('%Y%m%d-%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    settings = validation.get_settings()
    state = {
        "run_id": run_dir.name,
        "created_at": started_at.isoformat(),
        "database_url": str(args.database_url),
        "redis_url": str(args.redis_url),
        "public_api_host": str(args.public_api_host),
        "public_api_port": int(args.public_api_port),
        "app_api_key": settings.app_api_key,
        "time_budget_seconds": int(args.time_budget_seconds),
        "max_checkpoints": int(args.max_checkpoints) if args.max_checkpoints is not None else None,
        "acceptance_run_dir": None,
    }
    validation._write_json(run_dir / STATE_FILE, state)
    _write_env_summary(run_dir / "env_summary.md")
    return continue_closeout(run_dir)


def continue_closeout(
    run_dir: Path,
    *,
    time_budget_seconds: int | None = None,
    max_checkpoints: int | None = None,
) -> Path:
    state = load_state(run_dir)
    if time_budget_seconds is not None:
        state["time_budget_seconds"] = int(time_budget_seconds)
    if max_checkpoints is not None:
        state["max_checkpoints"] = int(max_checkpoints)
    validation._write_json(run_dir / STATE_FILE, state)

    env = build_live_replay_env(state)
    live_llm_error = validation.validate_replay_llm_env(env)
    if live_llm_error is not None:
        report = build_final_report(run_dir=run_dir, state=state, status="failed", live_llm_error=live_llm_error)
        write_final_report(run_dir, report)
        return run_dir

    backend_log = run_dir / BACKEND_LOG_FILE
    with validation.managed_backend(
        env=env,
        host=str(state["public_api_host"]),
        port=int(state["public_api_port"]),
        log_path=backend_log,
    ):
        if isinstance(state.get("acceptance_run_dir"), str) and state["acceptance_run_dir"]:
            command = [
                sys.executable,
                "scripts/run_year_timeline_backend_acceptance.py",
                "continue",
                "--run-dir",
                str(state["acceptance_run_dir"]),
                "--time-budget-seconds",
                str(state["time_budget_seconds"]),
            ]
            if state.get("max_checkpoints") is not None:
                command.extend(["--max-checkpoints", str(state["max_checkpoints"])])
            result = validation.run_command(
                command=command,
                cwd=REPO_ROOT,
                env=env,
                log_path=run_dir / "continue.log",
            )
        else:
            command = [
                sys.executable,
                "scripts/run_year_timeline_backend_acceptance.py",
                "start",
                "--public-api-base",
                f"http://{state['public_api_host']}:{state['public_api_port']}",
                "--api-key",
                str(state["app_api_key"]),
                "--time-budget-seconds",
                str(state["time_budget_seconds"]),
            ]
            if state.get("max_checkpoints") is not None:
                command.extend(["--max-checkpoints", str(state["max_checkpoints"])])
            result = validation.run_command(
                command=command,
                cwd=REPO_ROOT,
                env=env,
                log_path=run_dir / "start.log",
            )
            if isinstance(result.get("run_dir"), str) and result["run_dir"]:
                state["acceptance_run_dir"] = str(Path(result["run_dir"]).resolve())
                validation._write_json(run_dir / STATE_FILE, state)

    report = refresh_closeout_artifacts(run_dir)
    if not result["success"] and report["overall_status"] == "passed":
        report["overall_status"] = "failed"
        report["runner_error"] = {
            "returncode": result["returncode"],
            "stdout": result.get("stdout"),
            "stderr": result.get("stderr"),
        }
        write_final_report(run_dir, report)
    return run_dir


def refresh_closeout_artifacts(run_dir: Path) -> dict[str, Any]:
    state = load_state(run_dir)
    acceptance_run_dir = Path(str(state.get("acceptance_run_dir") or "")).resolve() if state.get("acceptance_run_dir") else None
    acceptance_report = _load_json(acceptance_run_dir / "backend-acceptance-report.json") if acceptance_run_dir else None
    replay_report = _load_json(acceptance_run_dir / "report.json") if acceptance_run_dir else None
    if acceptance_report is not None:
        validation._write_json(run_dir / ACCEPTANCE_REPORT_COPY_FILE, acceptance_report)
    if replay_report is not None:
        validation._write_json(run_dir / REPLAY_REPORT_COPY_FILE, replay_report)
    if acceptance_run_dir is not None:
        validation._write_text(run_dir / REPLAY_RUN_DIR_FILE, str(acceptance_run_dir) + "\n")
    cost_summary = build_cost_summary(replay_report)
    validation._write_json(run_dir / COST_SUMMARY_FILE, cost_summary)
    report = build_final_report(
        run_dir=run_dir,
        state=state,
        status=_resolve_closeout_status(acceptance_report=acceptance_report, replay_report=replay_report),
        live_llm_error=None,
        acceptance_report=acceptance_report,
        replay_report=replay_report,
        cost_summary=cost_summary,
    )
    write_final_report(run_dir, report)
    return report


def build_live_replay_env(state: dict[str, Any]) -> dict[str, str]:
    env = validation.build_stage_env(
        database_url=str(state["database_url"]),
        redis_url=str(state["redis_url"]),
        app_api_key=str(state["app_api_key"]),
    )
    env["INGEST_SERVICE_ENABLE_WORKER"] = "true"
    env["REVIEW_SERVICE_ENABLE_APPLY_WORKER"] = "true"
    env["LLM_SERVICE_ENABLE_WORKER"] = "true"
    env["GMAIL_API_BASE_URL"] = "http://127.0.0.1:8765/gmail/v1/users/me"
    env["GMAIL_SECONDARY_FILTER_MODE"] = "off"
    env["GMAIL_SECONDARY_FILTER_PROVIDER"] = "noop"
    return env


def build_cost_summary(replay_report: dict[str, Any] | None) -> dict[str, Any]:
    llm_usage = replay_report.get("llm_usage") if isinstance(replay_report, dict) and isinstance(replay_report.get("llm_usage"), dict) else {}
    return {
        "overall": _extract_cost_node(llm_usage.get("overall")),
        "bootstrap": _extract_cost_node(llm_usage.get("bootstrap")),
        "replay": _extract_cost_node(llm_usage.get("replay")),
        "gmail": _extract_cost_node(llm_usage.get("gmail")),
        "ics": _extract_cost_node(llm_usage.get("ics")),
    }


def _extract_cost_node(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {
            "successful_call_count": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "input_cost_usd": 0.0,
            "cached_input_cost_usd": 0.0,
            "output_cost_usd": 0.0,
            "pricing_available": False,
            "unpriced_call_count": 0,
            "models": {},
            "task_counts": {},
        }
    return {
        "successful_call_count": max(int(value.get("successful_call_count") or 0), 0),
        "total_tokens": max(int(value.get("total_tokens") or 0), 0),
        "estimated_cost_usd": round(float(value.get("estimated_cost_usd") or 0), 6),
        "input_cost_usd": round(float(value.get("input_cost_usd") or 0), 6),
        "cached_input_cost_usd": round(float(value.get("cached_input_cost_usd") or 0), 6),
        "output_cost_usd": round(float(value.get("output_cost_usd") or 0), 6),
        "pricing_available": bool(value.get("pricing_available", False)),
        "unpriced_call_count": max(int(value.get("unpriced_call_count") or 0), 0),
        "models": dict(value.get("models") or {}) if isinstance(value.get("models"), dict) else {},
        "task_counts": dict(value.get("task_counts") or {}) if isinstance(value.get("task_counts"), dict) else {},
    }


def build_final_report(
    *,
    run_dir: Path,
    state: dict[str, Any],
    status: str,
    live_llm_error: str | None,
    acceptance_report: dict[str, Any] | None = None,
    replay_report: dict[str, Any] | None = None,
    cost_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    models = (
        ((replay_report or {}).get("llm_usage") or {}).get("overall", {}).get("models", {})
        if isinstance(replay_report, dict)
        else {}
    )
    normalized_models = dict(models) if isinstance(models, dict) else {}
    qwen_ok = int(normalized_models.get("qwen3.5-flash") or 0) > 0
    gemini_calls = sum(
        int(value or 0)
        for key, value in normalized_models.items()
        if isinstance(key, str) and "gemini" in key.lower()
    )
    replay_finished = validation._replay_report_finished(replay_report)
    cost_node = (cost_summary or {}).get("overall") if isinstance(cost_summary, dict) else {}
    token_and_cost_ready = bool(
        isinstance(cost_node, dict)
        and max(int(cost_node.get("total_tokens") or 0), 0) > 0
        and float(cost_node.get("estimated_cost_usd") or 0) >= 0
    )
    overall_status = "partial"
    if status == "failed":
        overall_status = "failed"
    elif status == "finished" and replay_finished and qwen_ok and gemini_calls == 0 and token_and_cost_ready:
        overall_status = "passed"
    elif status == "finished":
        overall_status = "failed"
    return {
        "run_dir": str(run_dir.resolve()),
        "run_id": state["run_id"],
        "created_at": state["created_at"],
        "overall_status": overall_status,
        "status": status,
        "live_llm_error": live_llm_error,
        "acceptance_run_dir": state.get("acceptance_run_dir"),
        "replay_finished": replay_finished,
        "qwen_model_ok": qwen_ok,
        "gemini_call_count": gemini_calls,
        "token_and_cost_ready": token_and_cost_ready,
        "artifacts": {
            "replay_run_dir": str((run_dir / REPLAY_RUN_DIR_FILE).resolve()),
            "backend_log": str((run_dir / BACKEND_LOG_FILE).resolve()),
            "replay_report": str((run_dir / REPLAY_REPORT_COPY_FILE).resolve()),
            "acceptance_report": str((run_dir / ACCEPTANCE_REPORT_COPY_FILE).resolve()),
            "cost_summary": str((run_dir / COST_SUMMARY_FILE).resolve()),
        },
        "replay_report": replay_report,
        "acceptance_report": acceptance_report,
        "cost_summary": cost_summary,
    }


def write_final_report(run_dir: Path, report: dict[str, Any]) -> None:
    validation._write_json(run_dir / FINAL_REPORT_FILE, report)
    lines = [
        "# Live Replay Closeout",
        "",
        f"- Overall: **{report['overall_status']}**",
        f"- Status: `{report['status']}`",
        f"- Replay finished: `{report['replay_finished']}`",
        f"- Qwen mainline present: `{report['qwen_model_ok']}`",
        f"- Gemini call count: `{report['gemini_call_count']}`",
    ]
    cost_overall = (report.get("cost_summary") or {}).get("overall", {}) if isinstance(report.get("cost_summary"), dict) else {}
    if isinstance(cost_overall, dict):
        lines.extend(
            [
                f"- Total tokens: `{int(cost_overall.get('total_tokens') or 0)}`",
                f"- Estimated cost usd: `${float(cost_overall.get('estimated_cost_usd') or 0):.6f}`",
                f"- Unpriced calls: `{int(cost_overall.get('unpriced_call_count') or 0)}`",
            ]
        )
    if report.get("live_llm_error"):
        lines.append(f"- Live LLM env error: `{report['live_llm_error']}`")
    validation._write_text(run_dir / FINAL_REPORT_MD_FILE, "\n".join(lines) + "\n")


def _resolve_closeout_status(*, acceptance_report: dict[str, Any] | None, replay_report: dict[str, Any] | None) -> str:
    if isinstance(acceptance_report, dict):
        status = str(acceptance_report.get("status") or "")
        if status == "finished" and validation._replay_report_finished(replay_report):
            return "finished"
        if status in {"partial", "running"}:
            return "partial"
    if replay_report is not None and validation._replay_report_finished(replay_report):
        return "finished"
    return "partial"


def load_state(run_dir: Path) -> dict[str, Any]:
    path = run_dir / STATE_FILE
    if not path.is_file():
        raise RuntimeError(f"closeout state not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_env_summary(path: Path) -> None:
    env_map = {k: v for k, v in dotenv_values(REPO_ROOT / ".env").items() if isinstance(k, str)} if (REPO_ROOT / ".env").exists() else {}
    keys = [
        "APP_API_KEY",
        "INGESTION_LLM_PROVIDER_ID",
        "AGENT_LLM_PROVIDER_ID",
        "LLM_PRICE_QWEN_US_MAIN_INPUT_PER_1M_USD",
        "LLM_PRICE_QWEN_US_MAIN_CACHED_INPUT_PER_1M_USD",
        "LLM_PRICE_QWEN_US_MAIN_OUTPUT_PER_1M_USD",
    ]
    lines = ["# Live Replay Env Summary", ""]
    for key in keys:
        lines.append(f"- `{key}`: {'set' if env_map.get(key) else 'unset'}")
    validation._write_text(path, "\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
