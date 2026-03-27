#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.run_agent_live_eval as live_eval
from app.modules.llm_gateway import LlmInvokeRequest, invoke_llm_json
from app.modules.llm_gateway.costing import estimate_llm_usage_cost, merge_llm_cost_summary

OUTPUT_ROOT = REPO_ROOT / "output"
ROWS_FILE = "trace-eval-rows.jsonl"
SUMMARY_JSON_FILE = "SUMMARY.json"
SUMMARY_MD_FILE = "SUMMARY.md"
LIVE_EVAL_RUN_DIR_FILE = "live-eval-run-dir.txt"
JUDGE_MODES = {"llm", "deterministic", "off"}
LOW_TRACE_SCORE_THRESHOLD = 0.8

_JUDGE_SYSTEM_PROMPT = (
    "You are a strict evaluator for CalendarDIFF bounded agent traces. "
    "Review only whether the trace advanced the scenario, stayed within bounded execution rules, "
    "avoided obvious waste, and stayed clear for an operator to review. "
    "Do not override the deterministic scenario outcome. "
    "Do not invent facts that are not present in the trace excerpts. "
    "Return JSON only."
)


@dataclass(frozen=True)
class ScenarioTraceBundle:
    scenario_id: str
    name: str
    category: str
    operation: str
    metadata: dict[str, Any]
    status: str
    success: bool
    expected_statuses: list[int] | None
    http_status: int | None
    note: str | None
    details: dict[str, Any] | None
    api_trace_excerpts: list[dict[str, Any]] = field(default_factory=list)
    mcp_trace_excerpts: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ScenarioTraceJudgeRow:
    scenario_id: str
    name: str
    category: str
    operation: str
    metadata: dict[str, Any]
    status: str
    success: bool
    expected_statuses: list[int] | None
    http_status: int | None
    note: str | None
    details: dict[str, Any] | None
    api_trace_excerpts: list[dict[str, Any]]
    mcp_trace_excerpts: list[dict[str, Any]]
    judge_available: bool
    task_completion_alignment_score: float | None
    boundedness_score: float | None
    efficiency_score: float | None
    operator_clarity_score: float | None
    scenario_trace_score: float | None
    judge_notes: list[str]
    judge_usage: dict[str, int] | None
    judge_cost: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run trace-based evaluation over CalendarDIFF agent live eval traces.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run")
    run.add_argument("--live-eval-run-dir", default=None)
    run.add_argument("--public-api-base", default=None)
    run.add_argument("--api-key", default=None)
    run.add_argument("--email", default=None)
    run.add_argument("--password", default=None)
    run.add_argument("--scenario-set", default="core", choices=["core", "expanded", "full"])
    run.add_argument("--cross-user-email", default=None)
    run.add_argument("--output-root", default=str(OUTPUT_ROOT))
    run.add_argument("--judge-mode", default="llm", choices=sorted(JUDGE_MODES))

    report = subparsers.add_parser("report")
    report.add_argument("--run-dir", required=True)
    return parser.parse_args()


def run_eval(args: argparse.Namespace) -> Path:
    started_at = datetime.now(UTC)
    run_dir = Path(args.output_root).expanduser().resolve() / f"agent-trace-eval-{started_at.strftime('%Y%m%d-%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    live_eval_run_dir = resolve_live_eval_run_dir(args=args, trace_run_dir=run_dir)
    (run_dir / LIVE_EVAL_RUN_DIR_FILE).write_text(str(live_eval_run_dir.resolve()) + "\n", encoding="utf-8")
    summary = evaluate_trace_run(
        run_dir=run_dir,
        live_eval_run_dir=live_eval_run_dir,
        judge_mode=str(args.judge_mode),
    )
    write_json(run_dir / SUMMARY_JSON_FILE, summary)
    (run_dir / SUMMARY_MD_FILE).write_text(render_summary_markdown(summary=summary), encoding="utf-8")
    return run_dir


def resolve_live_eval_run_dir(*, args: argparse.Namespace, trace_run_dir: Path) -> Path:
    if args.live_eval_run_dir:
        return Path(str(args.live_eval_run_dir)).expanduser().resolve()
    required_fields = {
        "public_api_base": args.public_api_base,
        "api_key": args.api_key,
        "email": args.email,
        "password": args.password,
    }
    missing = [key for key, value in required_fields.items() if not str(value or "").strip()]
    if missing:
        raise RuntimeError(
            "live eval connection args are required when --live-eval-run-dir is not provided: "
            + ", ".join(sorted(missing))
        )
    live_eval_args = argparse.Namespace(
        public_api_base=str(args.public_api_base),
        api_key=str(args.api_key),
        email=str(args.email),
        password=str(args.password),
        scenario_set=str(args.scenario_set),
        cross_user_email=str(args.cross_user_email).strip() if args.cross_user_email else None,
        output_root=str(trace_run_dir / "live-eval-output"),
    )
    return live_eval.run_eval(live_eval_args)


def report_eval(run_dir: Path) -> dict[str, Any]:
    live_eval_run_dir = Path((run_dir / LIVE_EVAL_RUN_DIR_FILE).read_text(encoding="utf-8").strip()).resolve()
    rows = [
        ScenarioTraceJudgeRow(**json.loads(line))
        for line in live_eval.read_jsonl(run_dir / ROWS_FILE)
        if line.strip()
    ]
    source_live_eval_summary = load_live_eval_summary(live_eval_run_dir=live_eval_run_dir)
    summary = compute_summary(
        rows=rows,
        source_live_eval_summary=source_live_eval_summary,
        judge_mode=load_summary_judge_mode(run_dir=run_dir, default="llm"),
    )
    write_json(run_dir / SUMMARY_JSON_FILE, summary)
    (run_dir / SUMMARY_MD_FILE).write_text(render_summary_markdown(summary=summary), encoding="utf-8")
    return summary


def evaluate_trace_run(*, run_dir: Path, live_eval_run_dir: Path, judge_mode: str) -> dict[str, Any]:
    bundles = load_trace_bundles(live_eval_run_dir=live_eval_run_dir)
    rows: list[ScenarioTraceJudgeRow] = []
    for bundle in bundles:
        row = judge_trace_bundle(bundle=bundle, judge_mode=judge_mode)
        rows.append(row)
        live_eval.append_jsonl(run_dir / ROWS_FILE, row.to_dict())
    source_live_eval_summary = load_live_eval_summary(live_eval_run_dir=live_eval_run_dir)
    return compute_summary(
        rows=rows,
        source_live_eval_summary=source_live_eval_summary,
        judge_mode=judge_mode,
    )


def load_live_eval_summary(*, live_eval_run_dir: Path) -> dict[str, Any]:
    summary_path = live_eval_run_dir / live_eval.SUMMARY_JSON_FILE
    if summary_path.exists():
        return json.loads(summary_path.read_text(encoding="utf-8"))
    return live_eval.report_eval(live_eval_run_dir)


def load_trace_bundles(*, live_eval_run_dir: Path) -> list[ScenarioTraceBundle]:
    plan_payload = json.loads((live_eval_run_dir / live_eval.SCENARIO_PLAN_FILE).read_text(encoding="utf-8"))
    results_by_id = {
        row.scenario_id: row
        for row in (
            live_eval.ScenarioResult(**json.loads(line))
            for line in live_eval.read_jsonl(live_eval_run_dir / live_eval.SCENARIO_RESULTS_FILE)
            if line.strip()
        )
    }
    api_traces = load_trace_rows(path=live_eval_run_dir / live_eval.API_TRACE_FILE)
    mcp_traces = load_trace_rows(path=live_eval_run_dir / live_eval.MCP_TRACE_FILE)
    bundles: list[ScenarioTraceBundle] = []
    for plan_row in [live_eval.ScenarioSpec(**row) for row in plan_payload.get("scenarios", [])]:
        result = results_by_id.get(plan_row.scenario_id)
        status = result.status if result is not None else "missing_result"
        success = bool(result.success) if result is not None else False
        bundles.append(
            ScenarioTraceBundle(
                scenario_id=plan_row.scenario_id,
                name=plan_row.name,
                category=plan_row.category,
                operation=plan_row.operation,
                metadata=dict(plan_row.metadata or {}),
                status=status,
                success=success,
                expected_statuses=list(result.expected_statuses) if result and result.expected_statuses is not None else None,
                http_status=result.http_status if result is not None else None,
                note=result.note if result is not None else "scenario result missing",
                details=dict(result.details or {}) if result and isinstance(result.details, dict) else None,
                api_trace_excerpts=[row for row in api_traces if row.get("scenario_id") == plan_row.scenario_id],
                mcp_trace_excerpts=[row for row in mcp_traces if row.get("scenario_id") == plan_row.scenario_id],
            )
        )
    return bundles


def load_trace_rows(*, path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in live_eval.read_jsonl(path):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            continue
        rows.append(compress_trace_row(payload))
    return rows


def compress_trace_row(payload: dict[str, Any]) -> dict[str, Any]:
    row = {
        "scenario_id": str(payload.get("scenario_id") or ""),
        "recorded_at": payload.get("recorded_at"),
    }
    if "method" in payload:
        row.update(
            {
                "kind": "api",
                "method": payload.get("method"),
                "path": payload.get("path"),
                "status": payload.get("status"),
                "expected_statuses": payload.get("expected_statuses") or [],
                "elapsed_ms": payload.get("elapsed_ms"),
                "request_excerpt": live_eval.excerpt_payload(payload.get("request_json"), max_length=300),
                "response_excerpt": str(payload.get("response_excerpt") or "")[:500] or None,
                "error": payload.get("error"),
            }
        )
        return row
    row.update(
        {
            "kind": "mcp",
            "action": payload.get("action"),
            "success": payload.get("success"),
            "elapsed_ms": payload.get("elapsed_ms"),
            "request_excerpt": live_eval.excerpt_payload(payload.get("request"), max_length=300),
            "response_excerpt": str(payload.get("response_excerpt") or "")[:500] or None,
            "error": payload.get("error"),
        }
    )
    return row


def judge_trace_bundle(*, bundle: ScenarioTraceBundle, judge_mode: str) -> ScenarioTraceJudgeRow:
    if bundle.status == "skipped":
        return build_non_judged_row(bundle=bundle)
    if judge_mode in {"off", "deterministic"}:
        return build_non_judged_row(bundle=bundle)
    try:
        result = invoke_llm_json(
            None,
            invoke_request=LlmInvokeRequest(
                task_name="agent_trace_quality_judge",
                system_prompt=_JUDGE_SYSTEM_PROMPT,
                user_payload={
                    "scenario": {
                        "scenario_id": bundle.scenario_id,
                        "name": bundle.name,
                        "category": bundle.category,
                        "operation": bundle.operation,
                        "metadata": bundle.metadata,
                    },
                    "deterministic_outcome": {
                        "status": bundle.status,
                        "success": bundle.success,
                        "expected_statuses": bundle.expected_statuses,
                        "http_status": bundle.http_status,
                        "note": bundle.note,
                        "details_excerpt": live_eval.excerpt_payload(bundle.details, max_length=500),
                    },
                    "api_trace_excerpts": bundle.api_trace_excerpts,
                    "mcp_trace_excerpts": bundle.mcp_trace_excerpts,
                },
                output_schema_name="AgentTraceQualityJudgeResponse",
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
                source_id=None,
                request_id=None,
                source_provider=None,
                temperature=0.0,
                session_cache_mode="disable",
            ),
        )
    except Exception:
        return build_non_judged_row(bundle=bundle)

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
    scenario_trace_score = round(
        statistics.mean((task_score, boundedness_score, efficiency_score, operator_clarity_score)),
        4,
    )
    return ScenarioTraceJudgeRow(
        scenario_id=bundle.scenario_id,
        name=bundle.name,
        category=bundle.category,
        operation=bundle.operation,
        metadata=bundle.metadata,
        status=bundle.status,
        success=bundle.success,
        expected_statuses=bundle.expected_statuses,
        http_status=bundle.http_status,
        note=bundle.note,
        details=bundle.details,
        api_trace_excerpts=bundle.api_trace_excerpts,
        mcp_trace_excerpts=bundle.mcp_trace_excerpts,
        judge_available=True,
        task_completion_alignment_score=task_score,
        boundedness_score=boundedness_score,
        efficiency_score=efficiency_score,
        operator_clarity_score=operator_clarity_score,
        scenario_trace_score=scenario_trace_score,
        judge_notes=list(judge.get("notes") or []),
        judge_usage={
            "input_tokens": int(usage.get("input_tokens") or 0),
            "cached_input_tokens": int(usage.get("cached_input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
        },
        judge_cost=cost,
    )


def build_non_judged_row(*, bundle: ScenarioTraceBundle) -> ScenarioTraceJudgeRow:
    return ScenarioTraceJudgeRow(
        scenario_id=bundle.scenario_id,
        name=bundle.name,
        category=bundle.category,
        operation=bundle.operation,
        metadata=bundle.metadata,
        status=bundle.status,
        success=bundle.success,
        expected_statuses=bundle.expected_statuses,
        http_status=bundle.http_status,
        note=bundle.note,
        details=bundle.details,
        api_trace_excerpts=bundle.api_trace_excerpts,
        mcp_trace_excerpts=bundle.mcp_trace_excerpts,
        judge_available=False,
        task_completion_alignment_score=None,
        boundedness_score=None,
        efficiency_score=None,
        operator_clarity_score=None,
        scenario_trace_score=None,
        judge_notes=[],
        judge_usage=None,
        judge_cost=None,
    )


def clamp_score(value: Any) -> float:
    return round(max(0.0, min(float(value or 0.0), 1.0)), 4)


def compute_summary(
    *,
    rows: list[ScenarioTraceJudgeRow],
    source_live_eval_summary: dict[str, Any],
    judge_mode: str,
) -> dict[str, Any]:
    judged_candidates = [row for row in rows if row.status != "skipped"]
    judged_rows = [row for row in judged_candidates if row.judge_available]
    token_usage = {"overall": {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "total_tokens": 0}}
    judge_cost_usd = {
        "overall": {
            "estimated_cost_usd": 0.0,
            "input_cost_usd": 0.0,
            "cached_input_cost_usd": 0.0,
            "output_cost_usd": 0.0,
            "pricing_available": True,
            "unpriced_call_count": 0,
        }
    }
    for row in judged_rows:
        if isinstance(row.judge_usage, dict):
            for key in token_usage["overall"]:
                token_usage["overall"][key] += max(int(row.judge_usage.get(key) or 0), 0)
        if isinstance(row.judge_cost, dict):
            judge_cost_usd["overall"].update(
                merge_llm_cost_summary(judge_cost_usd["overall"], estimate=row.judge_cost)
            )
    lowest_rows = sorted(
        [row for row in judged_rows if row.scenario_trace_score is not None],
        key=lambda row: (float(row.scenario_trace_score), row.scenario_id),
    )[:10]
    overall_status = derive_live_eval_status(source_live_eval_summary=source_live_eval_summary)
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "overall_status": overall_status,
        "source_live_eval_summary": source_live_eval_summary,
        "judge_mode": judge_mode,
        "judge_available_rate": ratio(len(judged_rows), len(judged_candidates)),
        "scenario_trace_score_avg": avg(row.scenario_trace_score for row in judged_rows if row.scenario_trace_score is not None),
        "task_completion_alignment_score_avg": avg(
            row.task_completion_alignment_score for row in judged_rows if row.task_completion_alignment_score is not None
        ),
        "boundedness_score_avg": avg(row.boundedness_score for row in judged_rows if row.boundedness_score is not None),
        "efficiency_score_avg": avg(row.efficiency_score for row in judged_rows if row.efficiency_score is not None),
        "operator_clarity_score_avg": avg(
            row.operator_clarity_score for row in judged_rows if row.operator_clarity_score is not None
        ),
        "low_trace_score_count": sum(
            1
            for row in judged_rows
            if row.scenario_trace_score is not None and row.scenario_trace_score < LOW_TRACE_SCORE_THRESHOLD
        ),
        "judge_token_usage": token_usage,
        "judge_cost_usd": judge_cost_usd,
        "trace_quality_summary": {
            "scenario_count": len(rows),
            "judged_candidate_count": len(judged_candidates),
            "judged_scenario_count": len(judged_rows),
            "lowest_scenarios": [render_lowest_row(row) for row in lowest_rows],
            "representative_notes": collect_representative_notes(judged_rows),
        },
    }
    return summary


def derive_live_eval_status(*, source_live_eval_summary: dict[str, Any]) -> str:
    if str(source_live_eval_summary.get("overall_status") or "").strip():
        return str(source_live_eval_summary["overall_status"])
    success_rate = source_live_eval_summary.get("success_rate")
    failed_count = int(source_live_eval_summary.get("failed_count") or 0)
    if success_rate == 1.0 and failed_count == 0:
        return "passed"
    return "failed"


def render_lowest_row(row: ScenarioTraceJudgeRow) -> dict[str, Any]:
    return {
        "scenario_id": row.scenario_id,
        "name": row.name,
        "category": row.category,
        "operation": row.operation,
        "status": row.status,
        "success": row.success,
        "scenario_trace_score": row.scenario_trace_score,
        "judge_notes": row.judge_notes,
    }


def collect_representative_notes(rows: list[ScenarioTraceJudgeRow], *, limit: int = 12) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for row in rows:
        for note in row.judge_notes:
            cleaned = str(note or "").strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            ordered.append(cleaned)
            if len(ordered) >= limit:
                return ordered
    return ordered


def render_summary_markdown(*, summary: dict[str, Any]) -> str:
    source = summary["source_live_eval_summary"]
    trace_quality = summary["trace_quality_summary"]
    lines = [
        "# Agent Trace Eval Summary",
        "",
        "## Live Eval Snapshot",
        "",
        f"- overall_status: `{summary['overall_status']}`",
        f"- executed_count: `{source.get('executed_count')}`",
        f"- passed_count: `{source.get('passed_count')}`",
        f"- failed_count: `{source.get('failed_count')}`",
        f"- success_rate: `{format_ratio(source.get('success_rate'))}`",
        f"- scenario_weighted_score: `{format_ratio(source.get('scenario_weighted_score'))}`",
        "",
        "## Trace Judge Aggregate",
        "",
        f"- judge_mode: `{summary['judge_mode']}`",
        f"- judge_available_rate: `{format_ratio(summary['judge_available_rate'])}`",
        f"- scenario_trace_score_avg: `{summary['scenario_trace_score_avg']}`",
        f"- task_completion_alignment_score_avg: `{summary['task_completion_alignment_score_avg']}`",
        f"- boundedness_score_avg: `{summary['boundedness_score_avg']}`",
        f"- efficiency_score_avg: `{summary['efficiency_score_avg']}`",
        f"- operator_clarity_score_avg: `{summary['operator_clarity_score_avg']}`",
        f"- low_trace_score_count: `{summary['low_trace_score_count']}`",
        f"- judge_total_tokens: `{summary['judge_token_usage']['overall']['total_tokens']}`",
        f"- judge_estimated_cost_usd: `{format_usd(summary['judge_cost_usd']['overall']['estimated_cost_usd'])}`",
        "",
        "## Lowest-Scoring Scenarios",
        "",
    ]
    lowest = trace_quality.get("lowest_scenarios") or []
    if lowest:
        for row in lowest:
            lines.append(
                f"- `{row['scenario_id']}` score={row['scenario_trace_score']} status={row['status']} notes={','.join(row['judge_notes']) or 'none'}"
            )
    else:
        lines.append("- No judged scenarios were available.")
    lines.extend(["", "## Representative Notes", ""])
    notes = trace_quality.get("representative_notes") or []
    if notes:
        lines.extend([f"- {note}" for note in notes])
    else:
        lines.append("- No representative notes available.")
    lines.append("")
    return "\n".join(lines)


def load_summary_judge_mode(*, run_dir: Path, default: str) -> str:
    path = run_dir / SUMMARY_JSON_FILE
    if not path.exists():
        return default
    payload = json.loads(path.read_text(encoding="utf-8"))
    judge_mode = payload.get("judge_mode")
    return str(judge_mode) if isinstance(judge_mode, str) and judge_mode else default


def ratio(numerator: int, denominator: int) -> float | None:
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
        run_dir = run_eval(args)
        print(run_dir)
        return
    if args.command == "report":
        run_dir = Path(args.run_dir).expanduser().resolve()
        print(json.dumps(report_eval(run_dir), ensure_ascii=False, indent=2))
        return
    raise SystemExit(f"unsupported command: {args.command}")


if __name__ == "__main__":
    main()
