#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.run_agent_live_eval as live_eval
import scripts.run_year_timeline_replay_smoke as replay
from app.core.config import get_settings
from app.db.models.agents import AgentCommandRun
from app.db.session import get_session_factory
from app.modules.agents.trace_service import persist_command_step_traces
from app.modules.llm_gateway import LlmInvokeRequest, invoke_llm_json
from app.modules.llm_gateway.costing import estimate_llm_usage_cost, merge_llm_cost_summary

OUTPUT_ROOT = REPO_ROOT / "output"
CORPUS_PATH = REPO_ROOT / "tests" / "fixtures" / "agent" / "chain_eval_corpus.json"
SAMPLE_PLAN_FILE = "sample-plan.json"
TRACE_ROWS_FILE = "agent-chain-trace-rows.jsonl"
STEP_ROWS_FILE = "agent-chain-step-rows.jsonl"
SUMMARY_JSON_FILE = "SUMMARY.json"
SUMMARY_MD_FILE = "SUMMARY.md"
JUDGE_MODES = {"llm", "deterministic", "off"}
LOW_STEP_SCORE_THRESHOLD = 0.8
PLACEHOLDER_PATTERN = re.compile(r"\$\{([^}]+)\}")

_STEP_JUDGE_SYSTEM_PROMPT = (
    "You are a strict evaluator for CalendarDIFF agent execution traces. "
    "Review only whether this single step advanced the intended operation, stayed within bounded execution rules, "
    "avoided obvious waste, and left the operator with a clear outcome. "
    "Do not override the deterministic success or failure outcome already provided. "
    "Do not invent missing facts. "
    "Return JSON only."
)


@dataclass(frozen=True)
class StepTraceRow:
    eval_run_id: str
    operation_id: str
    sample_id: str
    operation_name: str
    category: str
    sample_kind: str
    command_id: str | None
    user_id: int
    step_id: str
    tool_name: str
    scope_kind: str | None
    execution_boundary: str | None
    status: str
    success: bool
    http_status: int | None
    expected_statuses: list[int] | None
    started_at: str | None
    finished_at: str | None
    input_context_excerpt: str | None
    dependency_context_excerpt: str | None
    output_summary_excerpt: str | None
    raw_output_excerpt: str | None
    error_text: str | None
    http_trace_excerpts: list[dict[str, Any]] = field(default_factory=list)
    judge_available: bool = False
    task_completion_alignment_score: float | None = None
    boundedness_score: float | None = None
    efficiency_score: float | None = None
    operator_clarity_score: float | None = None
    step_trace_score: float | None = None
    judge_notes: list[str] = field(default_factory=list)
    judge_usage: dict[str, int] | None = None
    judge_cost: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_persisted_record(self) -> dict[str, Any]:
        return {
            "eval_run_id": self.eval_run_id,
            "operation_id": self.operation_id,
            "command_id": self.command_id,
            "user_id": self.user_id,
            "step_id": self.step_id,
            "tool_name": self.tool_name,
            "scope_kind": self.scope_kind,
            "execution_boundary": self.execution_boundary,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "payload": {
                "sample_id": self.sample_id,
                "operation_name": self.operation_name,
                "category": self.category,
                "sample_kind": self.sample_kind,
                "success": self.success,
                "http_status": self.http_status,
                "expected_statuses": self.expected_statuses,
                "input_context_excerpt": self.input_context_excerpt,
                "dependency_context_excerpt": self.dependency_context_excerpt,
                "output_summary_excerpt": self.output_summary_excerpt,
                "raw_output_excerpt": self.raw_output_excerpt,
                "error_text": self.error_text,
                "http_trace_excerpts": self.http_trace_excerpts,
                "judge_available": self.judge_available,
                "task_completion_alignment_score": self.task_completion_alignment_score,
                "boundedness_score": self.boundedness_score,
                "efficiency_score": self.efficiency_score,
                "operator_clarity_score": self.operator_clarity_score,
                "step_trace_score": self.step_trace_score,
                "judge_notes": self.judge_notes,
                "judge_usage": self.judge_usage,
                "judge_cost": self.judge_cost,
            },
        }


@dataclass(frozen=True)
class OperationTraceRow:
    eval_run_id: str
    operation_id: str
    sample_id: str
    name: str
    kind: str
    category: str
    success: bool
    status: str
    note: str | None
    command_id: str | None
    command_status: str | None
    http_statuses: list[int]
    request_count: int
    step_count: int
    judged_step_count: int
    operation_trace_score: float | None
    judge_available: bool
    judge_notes: list[str]
    resolved_entry: dict[str, Any]
    http_trace_excerpts: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run mixed HTTP agent trace eval with step-level LLM judge.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run")
    run.add_argument("--public-api-base", required=True)
    run.add_argument("--api-key", required=True)
    run.add_argument("--email", required=True)
    run.add_argument("--password", required=True)
    run.add_argument("--sample-count", type=int, default=20)
    run.add_argument("--seed", type=int, default=7)
    run.add_argument("--success-threshold", type=float, default=0.8)
    run.add_argument("--judge-mode", default="llm", choices=sorted(JUDGE_MODES))
    run.add_argument("--corpus-path", default=str(CORPUS_PATH))
    run.add_argument("--output-root", default=str(OUTPUT_ROOT))

    report = subparsers.add_parser("report")
    report.add_argument("--run-dir", required=True)
    return parser.parse_args()


def run_eval(args: argparse.Namespace) -> Path:
    started_at = datetime.now(UTC)
    run_dir = Path(args.output_root).expanduser().resolve() / f"agent-chain-trace-eval-{started_at.strftime('%Y%m%d-%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    client = replay.build_api_client(public_api_base=str(args.public_api_base), api_key=str(args.api_key))
    user = replay.ensure_authenticated_session(
        client,
        email=str(args.email),
        password=str(args.password),
    )
    workspace_snapshot = load_workspace_snapshot(client=client, user=user, run_dir=run_dir, started_at=started_at)
    selected_entries = select_sample_entries(
        entries=load_corpus_entries(Path(args.corpus_path).expanduser().resolve()),
        workspace_snapshot=workspace_snapshot,
        sample_count=max(int(args.sample_count), 1),
        seed=int(args.seed),
    )
    sample_plan = {
        "generated_at": datetime.now(UTC).isoformat(),
        "seed": int(args.seed),
        "sample_count": len(selected_entries),
        "success_threshold": float(args.success_threshold),
        "judge_mode": str(args.judge_mode),
        "user_id": int(user["id"]),
        "email": str(user.get("email") or args.email),
        "workspace_snapshot": summarize_workspace_snapshot(workspace_snapshot),
        "entries": selected_entries,
    }
    write_json(run_dir / SAMPLE_PLAN_FILE, sample_plan)

    operation_rows, step_rows = evaluate_entries(
        run_dir=run_dir,
        client=client,
        user=user,
        entries=selected_entries,
        judge_mode=str(args.judge_mode),
    )
    summary = compute_summary(
        operation_rows=operation_rows,
        step_rows=step_rows,
        sample_plan=sample_plan,
    )
    write_json(run_dir / SUMMARY_JSON_FILE, summary)
    (run_dir / SUMMARY_MD_FILE).write_text(render_summary_markdown(summary=summary), encoding="utf-8")
    return run_dir


def report_eval(run_dir: Path) -> dict[str, Any]:
    operation_rows = [
        OperationTraceRow(**json.loads(line))
        for line in live_eval.read_jsonl(run_dir / TRACE_ROWS_FILE)
        if line.strip()
    ]
    step_rows = [
        StepTraceRow(**json.loads(line))
        for line in live_eval.read_jsonl(run_dir / STEP_ROWS_FILE)
        if line.strip()
    ]
    sample_plan = json.loads((run_dir / SAMPLE_PLAN_FILE).read_text(encoding="utf-8"))
    summary = compute_summary(
        operation_rows=operation_rows,
        step_rows=step_rows,
        sample_plan=sample_plan,
    )
    write_json(run_dir / SUMMARY_JSON_FILE, summary)
    (run_dir / SUMMARY_MD_FILE).write_text(render_summary_markdown(summary=summary), encoding="utf-8")
    return summary


def load_workspace_snapshot(
    *,
    client,
    user: dict[str, Any],
    run_dir: Path,
    started_at: datetime,
) -> dict[str, Any]:
    scratch_dir = run_dir / "_bootstrap_live_eval"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    runner = live_eval.AgentLiveEvalRunner(
        client=client,
        run_dir=scratch_dir,
        user=user,
        started_at=started_at,
    )
    return runner.bootstrap_workspace_snapshot()


def summarize_workspace_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        key: snapshot.get(key)
        for key in (
            "primary_change_id",
            "repeat_change_id",
            "cancel_change_id",
            "drift_change_id",
            "reviewed_change_id",
            "selected_source_id",
            "executable_source_id",
            "disconnected_gmail_source_id",
            "family_relink_raw_type_id",
            "family_relink_target_family_id",
            "label_learning_change_id",
            "label_learning_family_id",
            "missing_change_id",
            "missing_source_id",
            "missing_proposal_id",
            "missing_ticket_id",
        )
        if key in snapshot
    }


def load_corpus_entries(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise RuntimeError(f"invalid chain eval corpus: {path}")
    return [dict(row) for row in entries if isinstance(row, dict)]


def select_sample_entries(
    *,
    entries: list[dict[str, Any]],
    workspace_snapshot: dict[str, Any],
    sample_count: int,
    seed: int,
) -> list[dict[str, Any]]:
    resolved_entries: list[dict[str, Any]] = []
    for entry in entries:
        try:
            resolved_entries.append(resolve_placeholders(entry, workspace_snapshot))
        except KeyError:
            continue
    if sample_count > len(resolved_entries):
        raise RuntimeError(f"requested sample_count={sample_count} but only {len(resolved_entries)} eligible entries exist")

    rng = random.Random(seed)
    commands = [row for row in resolved_entries if row.get("kind") == "command"]
    endpoints = [row for row in resolved_entries if row.get("kind") == "endpoint"]
    command_target = min(len(commands), sample_count // 2)
    endpoint_target = min(len(endpoints), sample_count - command_target)
    if command_target + endpoint_target < sample_count:
        command_target = min(len(commands), sample_count - endpoint_target)

    used_groups: set[str] = set()
    selected: list[dict[str, Any]] = []
    selected.extend(_select_from_pool(commands, command_target, rng=rng, used_groups=used_groups))
    selected.extend(_select_from_pool(endpoints, endpoint_target, rng=rng, used_groups=used_groups))

    if len(selected) < sample_count:
        remaining = [
            row
            for row in resolved_entries
            if row.get("sample_id") not in {item.get("sample_id") for item in selected}
        ]
        selected.extend(_select_from_pool(remaining, sample_count - len(selected), rng=rng, used_groups=used_groups))

    if len(selected) < sample_count:
        raise RuntimeError(f"unable to draw {sample_count} mixed samples without exclusive-group conflicts")
    rng.shuffle(selected)
    return selected[:sample_count]


def _select_from_pool(
    entries: list[dict[str, Any]],
    count: int,
    *,
    rng: random.Random,
    used_groups: set[str],
) -> list[dict[str, Any]]:
    ordered = list(entries)
    rng.shuffle(ordered)
    selected: list[dict[str, Any]] = []
    for entry in ordered:
        group = str(entry.get("exclusive_group") or "").strip()
        if group and group in used_groups:
            continue
        selected.append(entry)
        if group:
            used_groups.add(group)
        if len(selected) >= count:
            break
    return selected


def resolve_placeholders(value: Any, snapshot: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: resolve_placeholders(nested, snapshot) for key, nested in value.items()}
    if isinstance(value, list):
        return [resolve_placeholders(item, snapshot) for item in value]
    if not isinstance(value, str):
        return value
    matches = list(PLACEHOLDER_PATTERN.finditer(value))
    if not matches:
        return value
    if len(matches) == 1 and matches[0].span() == (0, len(value)):
        key = matches[0].group(1)
        resolved = snapshot.get(key)
        if resolved is None:
            raise KeyError(key)
        return resolved
    output = value
    for match in matches:
        key = match.group(1)
        resolved = snapshot.get(key)
        if resolved is None:
            raise KeyError(key)
        output = output.replace(match.group(0), str(resolved))
    return output


def evaluate_entries(
    *,
    run_dir: Path,
    client,
    user: dict[str, Any],
    entries: list[dict[str, Any]],
    judge_mode: str,
) -> tuple[list[OperationTraceRow], list[StepTraceRow]]:
    eval_run_id = run_dir.name
    base_operations: list[dict[str, Any]] = []
    base_steps: list[StepTraceRow] = []
    for index, entry in enumerate(entries, start=1):
        operation_id = f"op_{index:02d}_{str(entry.get('sample_id') or index)}"
        if entry.get("kind") == "command":
            operation, steps = execute_command_entry(
                client=client,
                user_id=int(user["id"]),
                eval_run_id=eval_run_id,
                operation_id=operation_id,
                entry=entry,
            )
        else:
            operation, steps = execute_endpoint_entry(
                client=client,
                user_id=int(user["id"]),
                eval_run_id=eval_run_id,
                operation_id=operation_id,
                entry=entry,
            )
        base_operations.append(operation)
        base_steps.extend(steps)

    judged_steps = [judge_step_row(step_row=row, judge_mode=judge_mode) for row in base_steps]
    operations = build_operation_rows(eval_run_id=eval_run_id, base_operations=base_operations, step_rows=judged_steps)
    for row in operations:
        live_eval.append_jsonl(run_dir / TRACE_ROWS_FILE, row.to_dict())
    for row in judged_steps:
        live_eval.append_jsonl(run_dir / STEP_ROWS_FILE, row.to_dict())
    persist_step_rows(eval_run_id=eval_run_id, step_rows=judged_steps)
    return operations, judged_steps


def execute_command_entry(
    *,
    client,
    user_id: int,
    eval_run_id: str,
    operation_id: str,
    entry: dict[str, Any],
) -> tuple[dict[str, Any], list[StepTraceRow]]:
    trace_rows: list[dict[str, Any]] = []
    plan_body = {
        "input_text": str(entry["input_text"]),
        "scope_kind": entry.get("scope_kind"),
        "scope_id": entry.get("scope_id"),
    }
    plan_status, plan_payload, plan_trace = request_json(
        client=client,
        method="POST",
        path="/agent/commands/plan",
        json_body=plan_body,
        expected_statuses=[201],
    )
    trace_rows.append(plan_trace)
    command_id = str(plan_payload.get("command_id") or "") if isinstance(plan_payload, dict) else ""
    execute_status = None
    execute_payload: Any = None
    planned = bool(plan_payload.get("status") == "planned") if isinstance(plan_payload, dict) else False
    if planned and plan_status == 201 and bool(entry.get("execute", True)) and command_id:
        execute_status, execute_payload, execute_trace = request_json(
            client=client,
            method="POST",
            path=f"/agent/commands/{command_id}/execute",
            json_body={},
            expected_statuses=[200],
        )
        trace_rows.append(execute_trace)

    command_snapshot = load_command_snapshot(command_id=command_id) if command_id else None
    command_status = str(
        ((command_snapshot or {}).get("status"))
        or (execute_payload or {}).get("status")
        or (plan_payload or {}).get("status")
        or ""
    )
    expected_command_statuses = [str(row) for row in entry.get("expected_command_statuses") or ["completed"]]
    success = planned and plan_status == 201 and execute_status == 200 and command_status in expected_command_statuses
    status = "succeeded" if success else ("skipped" if not planned else "failed")
    note = None
    if not planned:
        note = f"command_planner_status={command_status or 'missing'}"
    elif not success:
        note = f"command_status={command_status or 'missing'}"
    steps = build_command_step_rows(
        eval_run_id=eval_run_id,
        operation_id=operation_id,
        sample_id=str(entry["sample_id"]),
        operation_name=str(entry["name"]),
        category=str(entry["category"]),
        command_id=command_id or None,
        user_id=user_id,
        command_snapshot=command_snapshot,
        fallback_plan_payload=plan_payload if isinstance(plan_payload, dict) else {},
        fallback_execute_payload=execute_payload if isinstance(execute_payload, dict) else {},
    )
    operation = {
        "operation_id": operation_id,
        "sample_id": str(entry["sample_id"]),
        "name": str(entry["name"]),
        "kind": "command",
        "category": str(entry["category"]),
        "success": success,
        "status": status,
        "note": note,
        "command_id": command_id or None,
        "command_status": command_status or None,
        "http_statuses": [status for status in (plan_status, execute_status) if isinstance(status, int)],
        "resolved_entry": entry,
        "http_trace_excerpts": trace_rows,
    }
    return operation, steps


def execute_endpoint_entry(
    *,
    client,
    user_id: int,
    eval_run_id: str,
    operation_id: str,
    entry: dict[str, Any],
) -> tuple[dict[str, Any], list[StepTraceRow]]:
    http_status, response_payload, trace = request_json(
        client=client,
        method=str(entry["method"]),
        path=str(entry["path"]),
        json_body=dict(entry.get("body") or {}) if str(entry.get("method")).upper() != "GET" else None,
        expected_statuses=[int(row) for row in entry.get("expected_statuses") or []],
    )
    expected_statuses = [int(row) for row in entry.get("expected_statuses") or []]
    success = http_status in expected_statuses
    step_row = StepTraceRow(
        eval_run_id=eval_run_id,
        operation_id=operation_id,
        sample_id=str(entry["sample_id"]),
        operation_name=str(entry["name"]),
        category=str(entry["category"]),
        sample_kind="endpoint",
        command_id=None,
        user_id=user_id,
        step_id="http_request",
        tool_name=f"{str(entry['method']).upper()} {str(entry['path'])}",
        scope_kind=None,
        execution_boundary="read_only" if str(entry["method"]).upper() == "GET" else "proposal_or_ticket_chain",
        status="succeeded" if success else "failed",
        success=success,
        http_status=http_status,
        expected_statuses=expected_statuses,
        started_at=None,
        finished_at=None,
        input_context_excerpt=live_eval.excerpt_payload(
            {
                "method": str(entry["method"]).upper(),
                "path": str(entry["path"]),
                "body": entry.get("body"),
            },
            max_length=600,
        ),
        dependency_context_excerpt=None,
        output_summary_excerpt=live_eval.excerpt_payload(response_payload, max_length=500),
        raw_output_excerpt=live_eval.excerpt_payload(response_payload, max_length=800),
        error_text=None if success else f"unexpected_http_status={http_status}",
        http_trace_excerpts=[trace],
    )
    operation = {
        "operation_id": operation_id,
        "sample_id": str(entry["sample_id"]),
        "name": str(entry["name"]),
        "kind": "endpoint",
        "category": str(entry["category"]),
        "success": success,
        "status": "succeeded" if success else "failed",
        "note": None if success else f"unexpected_http_status={http_status}",
        "command_id": None,
        "command_status": None,
        "http_statuses": [http_status],
        "resolved_entry": entry,
        "http_trace_excerpts": [trace],
    }
    return operation, [step_row]


def request_json(
    *,
    client,
    method: str,
    path: str,
    json_body: dict[str, Any] | None,
    expected_statuses: list[int],
) -> tuple[int, Any, dict[str, Any]]:
    started = time.monotonic()
    response = client.request(
        method=method,
        url=path,
        json=json_body,
        timeout=20.0,
    )
    http_status = int(response.status_code)
    try:
        payload = response.json()
    except ValueError:
        payload = {"raw_text": response.text[:2000]}
    elapsed_ms = round((time.monotonic() - started) * 1000.0, 2)
    trace = {
        "method": str(method).upper(),
        "path": path,
        "status": http_status,
        "expected_statuses": expected_statuses,
        "elapsed_ms": elapsed_ms,
        "request_excerpt": live_eval.excerpt_payload(json_body or {}, max_length=400),
        "response_excerpt": live_eval.excerpt_payload(payload, max_length=600),
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    return http_status, payload, trace


def load_command_snapshot(*, command_id: str) -> dict[str, Any] | None:
    try:
        session_factory = get_session_factory()
        with session_factory() as db:
            row = db.scalar(select(AgentCommandRun).where(AgentCommandRun.command_id == command_id).limit(1))
            if row is None:
                return None
            return {
                "command_id": row.command_id,
                "user_id": row.user_id,
                "status": row.status.value,
                "plan_json": dict(row.plan_json or {}),
                "execution_results_json": dict(row.execution_results_json or {}),
                "executed_at": row.executed_at.isoformat() if row.executed_at is not None else None,
            }
    except Exception:
        return None


def build_command_step_rows(
    *,
    eval_run_id: str,
    operation_id: str,
    sample_id: str,
    operation_name: str,
    category: str,
    command_id: str | None,
    user_id: int,
    command_snapshot: dict[str, Any] | None,
    fallback_plan_payload: dict[str, Any],
    fallback_execute_payload: dict[str, Any],
) -> list[StepTraceRow]:
    plan_json = dict((command_snapshot or {}).get("plan_json") or {})
    plan_steps = list(plan_json.get("steps") or fallback_plan_payload.get("plan") or [])
    scope_snapshot = plan_json.get("scope_snapshot")
    raw_results_by_step = dict(((command_snapshot or {}).get("execution_results_json") or {}).get("results_by_step") or {})
    if not raw_results_by_step and isinstance(fallback_execute_payload.get("execution_results"), list):
        raw_results_by_step = {
            str(item.get("step_id") or ""): dict(item)
            for item in fallback_execute_payload.get("execution_results") or []
            if isinstance(item, dict)
        }
    rows: list[StepTraceRow] = []
    for step in plan_steps:
        step_id = str(step.get("step_id") or "")
        result = dict(raw_results_by_step.get(step_id) or {})
        depends_on = [str(item) for item in step.get("depends_on") or [] if str(item)]
        dependency_excerpt = live_eval.excerpt_payload(
            {
                dep: {
                    "status": (raw_results_by_step.get(dep) or {}).get("status"),
                    "raw_output": live_eval.excerpt_payload((raw_results_by_step.get(dep) or {}).get("raw_output"), max_length=250),
                }
                for dep in depends_on
            },
            max_length=500,
        )
        status = str(result.get("status") or "pending")
        rows.append(
            StepTraceRow(
                eval_run_id=eval_run_id,
                operation_id=operation_id,
                sample_id=sample_id,
                operation_name=operation_name,
                category=category,
                sample_kind="command",
                command_id=command_id,
                user_id=user_id,
                step_id=step_id,
                tool_name=str(step.get("tool_name") or "unknown_tool"),
                scope_kind=(scope_snapshot or {}).get("scope_kind") if isinstance(scope_snapshot, dict) else None,
                execution_boundary=str(step.get("execution_boundary") or "") or None,
                status=status,
                success=status == "succeeded",
                http_status=None,
                expected_statuses=None,
                started_at=result.get("started_at"),
                finished_at=result.get("finished_at"),
                input_context_excerpt=live_eval.excerpt_payload(
                    {
                        "title": step.get("title"),
                        "reason": step.get("reason"),
                        "target_kind": step.get("target_kind"),
                        "args": step.get("args") or {},
                        "scope_snapshot": scope_snapshot or {},
                    },
                    max_length=800,
                ),
                dependency_context_excerpt=dependency_excerpt,
                output_summary_excerpt=live_eval.excerpt_payload(result.get("output_summary") or {}, max_length=500),
                raw_output_excerpt=live_eval.excerpt_payload(result.get("raw_output"), max_length=800),
                error_text=str(result.get("error_text") or "") or None,
                http_trace_excerpts=[],
            )
        )
    return rows


def judge_step_row(*, step_row: StepTraceRow, judge_mode: str) -> StepTraceRow:
    if judge_mode in {"off", "deterministic"}:
        return step_row
    try:
        result = invoke_llm_json(
            None,
            invoke_request=LlmInvokeRequest(
                task_name="agent_chain_step_quality_judge",
                system_prompt=_STEP_JUDGE_SYSTEM_PROMPT,
                user_payload={
                    "operation": {
                        "operation_id": step_row.operation_id,
                        "sample_id": step_row.sample_id,
                        "operation_name": step_row.operation_name,
                        "category": step_row.category,
                        "sample_kind": step_row.sample_kind,
                    },
                    "step": {
                        "step_id": step_row.step_id,
                        "tool_name": step_row.tool_name,
                        "scope_kind": step_row.scope_kind,
                        "execution_boundary": step_row.execution_boundary,
                    },
                    "deterministic_outcome": {
                        "status": step_row.status,
                        "success": step_row.success,
                        "http_status": step_row.http_status,
                        "expected_statuses": step_row.expected_statuses,
                        "error_text": step_row.error_text,
                    },
                    "trace_context": {
                        "input_context_excerpt": step_row.input_context_excerpt,
                        "dependency_context_excerpt": step_row.dependency_context_excerpt,
                        "output_summary_excerpt": step_row.output_summary_excerpt,
                        "raw_output_excerpt": step_row.raw_output_excerpt,
                        "http_trace_excerpts": step_row.http_trace_excerpts,
                    },
                },
                output_schema_name="AgentChainStepJudgeResponse",
                output_schema_json={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "task_completion_alignment_score": {"type": "number"},
                        "boundedness_score": {"type": "number"},
                        "efficiency_score": {"type": "number"},
                        "operator_clarity_score": {"type": "number"},
                        "notes": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": [
                        "task_completion_alignment_score",
                        "boundedness_score",
                        "efficiency_score",
                        "operator_clarity_score",
                        "notes",
                    ],
                },
                profile_family="judge",
                request_id=step_row.operation_id,
                temperature=0.0,
                session_cache_mode="disable",
            ),
        )
    except Exception:
        return step_row

    judge = result.json_object if isinstance(result.json_object, dict) else {}
    usage = result.raw_usage if isinstance(result.raw_usage, dict) else {}
    cost = estimate_llm_usage_cost(
        provider_id=result.provider_id,
        vendor=result.vendor,
        model=result.model,
        protocol=result.protocol,
        usage=usage,
    )
    task_score = clamp_score(judge.get("task_completion_alignment_score"))
    boundedness_score = clamp_score(judge.get("boundedness_score"))
    efficiency_score = clamp_score(judge.get("efficiency_score"))
    operator_clarity_score = clamp_score(judge.get("operator_clarity_score"))
    step_trace_score = round(
        statistics.mean((task_score, boundedness_score, efficiency_score, operator_clarity_score)),
        4,
    )
    return StepTraceRow(
        **{
            **step_row.to_dict(),
            "judge_available": True,
            "task_completion_alignment_score": task_score,
            "boundedness_score": boundedness_score,
            "efficiency_score": efficiency_score,
            "operator_clarity_score": operator_clarity_score,
            "step_trace_score": step_trace_score,
            "judge_notes": list(judge.get("notes") or []),
            "judge_usage": {
                "input_tokens": int(usage.get("input_tokens") or 0),
                "cached_input_tokens": int(usage.get("cached_input_tokens") or 0),
                "output_tokens": int(usage.get("output_tokens") or 0),
                "total_tokens": int(usage.get("total_tokens") or 0),
            },
            "judge_cost": cost,
        }
    )


def build_operation_rows(
    *,
    eval_run_id: str,
    base_operations: list[dict[str, Any]],
    step_rows: list[StepTraceRow],
) -> list[OperationTraceRow]:
    steps_by_operation: dict[str, list[StepTraceRow]] = defaultdict(list)
    for row in step_rows:
        steps_by_operation[row.operation_id].append(row)
    operation_rows: list[OperationTraceRow] = []
    for base in base_operations:
        steps = steps_by_operation.get(str(base["operation_id"]), [])
        judged = [row for row in steps if row.judge_available and row.step_trace_score is not None]
        notes = collect_representative_notes(steps)
        operation_rows.append(
            OperationTraceRow(
                eval_run_id=eval_run_id,
                operation_id=str(base["operation_id"]),
                sample_id=str(base["sample_id"]),
                name=str(base["name"]),
                kind=str(base["kind"]),
                category=str(base["category"]),
                success=bool(base["success"]),
                status=str(base["status"]),
                note=base.get("note"),
                command_id=base.get("command_id"),
                command_status=base.get("command_status"),
                http_statuses=[int(row) for row in base.get("http_statuses") or []],
                request_count=len(base.get("http_trace_excerpts") or []),
                step_count=len(steps),
                judged_step_count=len(judged),
                operation_trace_score=avg(row.step_trace_score for row in judged if row.step_trace_score is not None),
                judge_available=bool(judged),
                judge_notes=notes,
                resolved_entry=dict(base.get("resolved_entry") or {}),
                http_trace_excerpts=list(base.get("http_trace_excerpts") or []),
            )
        )
    return operation_rows


def persist_step_rows(*, eval_run_id: str, step_rows: list[StepTraceRow]) -> None:
    del eval_run_id
    if not bool(get_settings().agent_trace_persistence_enabled):
        return
    session_factory = get_session_factory()
    with session_factory() as db:
        persist_command_step_traces(
            db,
            traces=[row.to_persisted_record() for row in step_rows if row.sample_kind == "command"],
        )
        db.commit()


def compute_summary(
    *,
    operation_rows: list[OperationTraceRow],
    step_rows: list[StepTraceRow],
    sample_plan: dict[str, Any],
) -> dict[str, Any]:
    judged_steps = [row for row in step_rows if row.judge_available]
    judged_operations = [row for row in operation_rows if row.judge_available]
    token_usage = {"overall": {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "total_tokens": 0}}
    judge_cost = {
        "overall": {
            "estimated_cost_usd": 0.0,
            "input_cost_usd": 0.0,
            "cached_input_cost_usd": 0.0,
            "output_cost_usd": 0.0,
            "pricing_available": True,
            "unpriced_call_count": 0,
        }
    }
    for row in judged_steps:
        if isinstance(row.judge_usage, dict):
            for key in token_usage["overall"]:
                token_usage["overall"][key] += max(int(row.judge_usage.get(key) or 0), 0)
        if isinstance(row.judge_cost, dict):
            judge_cost["overall"].update(merge_llm_cost_summary(judge_cost["overall"], estimate=row.judge_cost))

    executed = [row for row in operation_rows if row.status != "skipped"]
    success_rate = ratio(sum(1 for row in executed if row.success), len(executed))
    success_threshold = float(sample_plan.get("success_threshold") or 0.8)
    lowest_steps = sorted(
        [row for row in judged_steps if row.step_trace_score is not None],
        key=lambda row: (float(row.step_trace_score), row.operation_id, row.step_id),
    )[:10]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "overall_status": "passed" if success_rate is not None and success_rate >= success_threshold else "failed",
        "judge_mode": str(sample_plan.get("judge_mode") or "off"),
        "seed": int(sample_plan.get("seed") or 0),
        "sample_count": len(operation_rows),
        "success_threshold": success_threshold,
        "success_rate": success_rate,
        "passed_operation_count": sum(1 for row in operation_rows if row.success),
        "failed_operation_count": sum(1 for row in operation_rows if row.status == "failed"),
        "skipped_operation_count": sum(1 for row in operation_rows if row.status == "skipped"),
        "command_operation_count": sum(1 for row in operation_rows if row.kind == "command"),
        "endpoint_operation_count": sum(1 for row in operation_rows if row.kind == "endpoint"),
        "step_count": len(step_rows),
        "judged_step_count": len(judged_steps),
        "judge_available_rate": ratio(len(judged_steps), len(step_rows)),
        "operation_trace_score_avg": avg(
            row.operation_trace_score for row in judged_operations if row.operation_trace_score is not None
        ),
        "step_trace_score_avg": avg(row.step_trace_score for row in judged_steps if row.step_trace_score is not None),
        "task_completion_alignment_score_avg": avg(
            row.task_completion_alignment_score for row in judged_steps if row.task_completion_alignment_score is not None
        ),
        "boundedness_score_avg": avg(row.boundedness_score for row in judged_steps if row.boundedness_score is not None),
        "efficiency_score_avg": avg(row.efficiency_score for row in judged_steps if row.efficiency_score is not None),
        "operator_clarity_score_avg": avg(
            row.operator_clarity_score for row in judged_steps if row.operator_clarity_score is not None
        ),
        "low_step_score_count": sum(
            1 for row in judged_steps if row.step_trace_score is not None and row.step_trace_score < LOW_STEP_SCORE_THRESHOLD
        ),
        "judge_token_usage": token_usage,
        "judge_cost_usd": judge_cost,
        "trace_quality_summary": {
            "lowest_steps": [render_lowest_step(row) for row in lowest_steps],
            "representative_notes": collect_representative_notes(judged_steps),
        },
    }


def render_lowest_step(row: StepTraceRow) -> dict[str, Any]:
    return {
        "operation_id": row.operation_id,
        "sample_id": row.sample_id,
        "step_id": row.step_id,
        "tool_name": row.tool_name,
        "status": row.status,
        "success": row.success,
        "step_trace_score": row.step_trace_score,
        "judge_notes": row.judge_notes,
    }


def collect_representative_notes(rows: list[Any], *, limit: int = 12) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for row in rows:
        for note in list(getattr(row, "judge_notes", []) or []):
            cleaned = str(note or "").strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            ordered.append(cleaned)
            if len(ordered) >= limit:
                return ordered
    return ordered


def render_summary_markdown(*, summary: dict[str, Any]) -> str:
    lines = [
        "# Agent Chain Trace Eval Summary",
        "",
        "## Deterministic Execution",
        "",
        f"- overall_status: `{summary['overall_status']}`",
        f"- sample_count: `{summary['sample_count']}`",
        f"- success_rate: `{format_ratio(summary['success_rate'])}`",
        f"- success_threshold: `{format_ratio(summary['success_threshold'])}`",
        f"- passed_operation_count: `{summary['passed_operation_count']}`",
        f"- failed_operation_count: `{summary['failed_operation_count']}`",
        f"- skipped_operation_count: `{summary['skipped_operation_count']}`",
        f"- command_operation_count: `{summary['command_operation_count']}`",
        f"- endpoint_operation_count: `{summary['endpoint_operation_count']}`",
        "",
        "## Trace Judge Aggregate",
        "",
        f"- judge_mode: `{summary['judge_mode']}`",
        f"- judged_step_count: `{summary['judged_step_count']}`",
        f"- judge_available_rate: `{format_ratio(summary['judge_available_rate'])}`",
        f"- operation_trace_score_avg: `{summary['operation_trace_score_avg']}`",
        f"- step_trace_score_avg: `{summary['step_trace_score_avg']}`",
        f"- task_completion_alignment_score_avg: `{summary['task_completion_alignment_score_avg']}`",
        f"- boundedness_score_avg: `{summary['boundedness_score_avg']}`",
        f"- efficiency_score_avg: `{summary['efficiency_score_avg']}`",
        f"- operator_clarity_score_avg: `{summary['operator_clarity_score_avg']}`",
        f"- low_step_score_count: `{summary['low_step_score_count']}`",
        f"- judge_total_tokens: `{summary['judge_token_usage']['overall']['total_tokens']}`",
        f"- judge_estimated_cost_usd: `{format_usd(summary['judge_cost_usd']['overall']['estimated_cost_usd'])}`",
        "",
        "## Lowest-Scoring Steps",
        "",
    ]
    lowest = summary["trace_quality_summary"].get("lowest_steps") or []
    if lowest:
        for row in lowest:
            lines.append(
                f"- `{row['operation_id']}/{row['step_id']}` score={row['step_trace_score']} status={row['status']} notes={','.join(row['judge_notes']) or 'none'}"
            )
    else:
        lines.append("- No judged steps were available.")
    lines.extend(["", "## Representative Notes", ""])
    notes = summary["trace_quality_summary"].get("representative_notes") or []
    if notes:
        lines.extend([f"- {note}" for note in notes])
    else:
        lines.append("- No representative notes available.")
    lines.append("")
    return "\n".join(lines)


def clamp_score(value: Any) -> float:
    return round(max(0.0, min(float(value or 0.0), 1.0)), 4)


def ratio(numerator: int | float, denominator: int | float) -> float | None:
    if denominator <= 0:
        return None
    return round(float(numerator) / float(denominator), 4)


def avg(values) -> float | None:
    rows = list(values)
    if not rows:
        return None
    return round(float(sum(rows)) / float(len(rows)), 4)


def format_ratio(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def format_usd(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"${value:.6f}"


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    if args.command == "run":
        print(run_eval(args))
        return
    if args.command == "report":
        run_dir = Path(args.run_dir).expanduser().resolve()
        print(json.dumps(report_eval(run_dir), ensure_ascii=False, indent=2))
        return
    raise SystemExit(f"unsupported command: {args.command}")


if __name__ == "__main__":
    main()
