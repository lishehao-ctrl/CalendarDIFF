from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import time
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings
from app.modules.runtime.connectors.llm_parsers.contracts import ParserContext
from app.modules.runtime.connectors.llm_parsers.gmail_parser import parse_gmail_payload
from app.modules.llm_gateway.runtime_control import (
    reset_llm_invoke_observer,
    reset_session_cache_mode_override,
    set_llm_invoke_observer,
    set_session_cache_mode_override,
)

FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "private" / "email_pool"
DERIVED_SET_ROOT = FIXTURE_ROOT / "derived_sets"
OUTPUT_ROOT = REPO_ROOT / "output"
VALID_BUCKETS = ("year_timeline_gmail", "year_timeline_full_sim")
ATOMIC_FIELDS = [
    "course_dept",
    "course_number",
    "course_suffix",
    "course_quarter",
    "course_year2",
    "raw_type",
    "event_name",
    "ordinal",
    "due_date",
    "due_time",
    "time_precision",
]
DIRECTIVE_SELECTOR_FIELDS = [
    "course_dept",
    "course_number",
    "course_suffix",
    "course_quarter",
    "course_year2",
    "family_hint",
    "raw_type_hint",
    "scope_mode",
    "ordinal_list",
    "ordinal_range_start",
    "ordinal_range_end",
    "current_due_weekday",
    "applies_to_future_only",
]
DIRECTIVE_MUTATION_FIELDS = ["move_weekday", "set_due_date"]


@dataclass
class StageUsage:
    task_name: str
    api_mode: str | None
    latency_ms: int | None
    input_tokens: int | None
    cached_input_tokens: int | None
    cache_creation_input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    response_id: str | None
    chosen_mode: str | None


@dataclass
class SampleRun:
    bucket: str
    sample_id: str
    cache_mode: str
    expected_mode: str | None
    stage_mode: str | None
    final_record_type: str | None
    sample_latency_ms: int
    success: bool
    error: str | None
    stage_usages: list[StageUsage]
    actual_semantic_event_draft: dict[str, Any] | None
    actual_directive: dict[str, Any] | None
    accuracy: dict[str, Any] | None


@dataclass
class AggregateMetrics:
    sample_count: int
    success_count: int
    error_count: int
    avg_sample_latency_ms: float | None
    median_sample_latency_ms: float | None
    avg_total_tokens: float | None
    avg_input_tokens: float | None
    avg_output_tokens: float | None
    avg_cached_input_tokens: float | None
    cache_hit_stage_count: int
    total_cached_input_tokens: int


@dataclass
class SyntheticAccuracy:
    sample_count: int
    mode_accuracy: float | None
    record_type_accuracy: float | None
    atomic_exact_accuracy: float | None
    directive_exact_accuracy: float | None
    field_accuracy: dict[str, float]



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Process local email-pool fixtures through the current Gmail parser path."
    )
    parser.add_argument(
        "--bucket",
        action="append",
        choices=["all", *VALID_BUCKETS],
        default=None,
        help="Bucket(s) to process. Repeatable. Defaults to all known Gmail local buckets.",
    )
    parser.add_argument(
        "--sample-id",
        action="append",
        default=None,
        help="Specific sample_id(s) to process from the local pool. Repeatable. Overrides bucket or derived-set sampling.",
    )
    parser.add_argument(
        "--derived-set",
        action="append",
        default=None,
        help="Derived-set name(s) under tests/fixtures/private/email_pool/derived_sets. Repeatable.",
    )
    parser.add_argument("--limit", type=int, default=4, help="Samples per selected bucket when not using sample_id or derived_set. Use -1 for all.")
    parser.add_argument("--seed", type=int, default=20260316, help="Deterministic sampling seed.")
    parser.add_argument("--source-id", type=int, default=2, help="Source id used in parser context only.")
    parser.add_argument("--parallel", type=int, default=12, help="How many samples to process concurrently.")
    parser.add_argument(
        "--api-mode",
        choices=["responses", "chat_completions"],
        default=((os.getenv("INGESTION_LLM_API_MODE") or "chat_completions").strip().lower() or "chat_completions"),
        help="LLM API mode to use for this run. Defaults to INGESTION_LLM_API_MODE or chat_completions.",
    )
    parser.add_argument(
        "--cache-mode",
        choices=["enable", "disable"],
        default="enable",
        help="Override semantic parser session cache mode. Default: enable.",
    )
    parser.add_argument(
        "--list-samples",
        action="store_true",
        help="List matching local sample_ids and exit without calling the model.",
    )
    parser.add_argument(
        "--list-derived-sets",
        action="store_true",
        help="List available derived-set names and exit.",
    )
    return parser.parse_args()



def main() -> None:
    args = parse_args()
    if args.list_derived_sets:
        print(json.dumps(sorted(list_derived_set_names()), ensure_ascii=False, indent=2))
        return

    selected_buckets = resolve_selected_buckets(args.bucket)
    selected_rows = select_rows(
        selected_buckets=selected_buckets,
        sample_ids=args.sample_id or [],
        derived_sets=args.derived_set or [],
        limit=args.limit,
        seed=args.seed,
    )

    if args.list_samples:
        print(json.dumps({bucket: [row["sample_id"] for row in rows] for bucket, rows in selected_rows.items()}, ensure_ascii=False, indent=2))
        return

    started_at = datetime.now(timezone.utc)
    run_dir = OUTPUT_ROOT / f"local-email-pool-{args.api_mode}-{args.cache_mode}-{started_at.strftime('%Y%m%d-%H%M%S-%f')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    runs: list[SampleRun] = []
    tasks = [(bucket, row) for bucket in selected_buckets for row in selected_rows[bucket]]
    with llm_api_mode_override(args.api_mode):
        if max(int(args.parallel), 1) <= 1:
            for bucket, row in tasks:
                runs.append(
                    run_sample(
                        row=row,
                        bucket=bucket,
                        cache_mode=args.cache_mode,
                        source_id=args.source_id,
                        api_mode=args.api_mode,
                    )
                )
        else:
            with ThreadPoolExecutor(max_workers=max(int(args.parallel), 1), thread_name_prefix="local-email-pool") as pool:
                future_map = {
                    pool.submit(
                        run_sample,
                        row=row,
                        bucket=bucket,
                        cache_mode=args.cache_mode,
                        source_id=args.source_id,
                        api_mode=args.api_mode,
                    ): (bucket, row)
                    for bucket, row in tasks
                }
                for future in as_completed(future_map):
                    runs.append(future.result())
            runs.sort(key=lambda item: (selected_buckets.index(item.bucket), item.sample_id))

    report = build_report(
        started_at=started_at,
        source_id=args.source_id,
        seed=args.seed,
        api_mode=args.api_mode,
        cache_mode=args.cache_mode,
        selected_rows=selected_rows,
        runs=runs,
    )
    (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "summary.md").write_text(render_summary(report), encoding="utf-8")
    print(run_dir)



def resolve_selected_buckets(raw_buckets: list[str] | None) -> list[str]:
    if not raw_buckets:
        return list(VALID_BUCKETS)
    if "all" in raw_buckets:
        return list(VALID_BUCKETS)
    seen: set[str] = set()
    ordered: list[str] = []
    for bucket in raw_buckets:
        if bucket not in seen:
            seen.add(bucket)
            ordered.append(bucket)
    return ordered



def load_bucket_rows(bucket: str) -> list[dict[str, Any]]:
    path = FIXTURE_ROOT / bucket / "samples.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]



def list_derived_set_names() -> list[str]:
    if not DERIVED_SET_ROOT.exists():
        return []
    return [path.stem for path in sorted(DERIVED_SET_ROOT.glob("*.json"))]



def load_derived_set(name: str) -> dict[str, list[str]]:
    path = DERIVED_SET_ROOT / f"{name}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"derived set must be a JSON object: {path}")
    sample_ids_by_bucket = payload.get("sample_ids_by_bucket")
    if not isinstance(sample_ids_by_bucket, dict):
        raise RuntimeError(f"derived set missing sample_ids_by_bucket: {path}")

    out: dict[str, list[str]] = {}
    for bucket, sample_ids in sample_ids_by_bucket.items():
        if bucket not in VALID_BUCKETS:
            raise RuntimeError(f"derived set {name} references unknown bucket: {bucket}")
        if not isinstance(sample_ids, list) or not all(isinstance(item, str) for item in sample_ids):
            raise RuntimeError(f"derived set {name} has invalid sample list for bucket: {bucket}")
        out[bucket] = sample_ids
    return out



def select_rows(
    *,
    selected_buckets: list[str],
    sample_ids: list[str],
    derived_sets: list[str],
    limit: int,
    seed: int,
) -> dict[str, list[dict[str, Any]]]:
    by_bucket = {bucket: load_bucket_rows(bucket) for bucket in selected_buckets}

    if sample_ids:
        wanted = set(sample_ids)
        return {
            bucket: [row for row in rows if str(row.get("sample_id")) in wanted]
            for bucket, rows in by_bucket.items()
        }

    if derived_sets:
        wanted_by_bucket: dict[str, set[str]] = {bucket: set() for bucket in selected_buckets}
        for derived_set in derived_sets:
            for bucket, sample_list in load_derived_set(derived_set).items():
                if bucket in wanted_by_bucket:
                    wanted_by_bucket[bucket].update(sample_list)
        return {
            bucket: [row for row in rows if str(row.get("sample_id")) in wanted_by_bucket[bucket]]
            for bucket, rows in by_bucket.items()
        }

    out: dict[str, list[dict[str, Any]]] = {}
    for bucket, rows in by_bucket.items():
        if limit < 0 or len(rows) <= limit:
            out[bucket] = rows
            continue
        rng = random.Random(f"{seed}:{bucket}")
        out[bucket] = rng.sample(rows, limit)
    return out



def run_sample(*, row: dict[str, Any], bucket: str, cache_mode: str, source_id: int, api_mode: str) -> SampleRun:
    stage_usages: list[StageUsage] = []

    def observe_invoke(invoke_request, result):  # type: ignore[no-untyped-def]
        usage = normalize_usage(result.raw_usage if isinstance(result.raw_usage, dict) else {})
        chosen_mode = None
        if invoke_request.task_name == "gmail_purpose_mode_classify" and isinstance(result.json_object, dict):
            raw_mode = result.json_object.get("mode")
            chosen_mode = raw_mode if isinstance(raw_mode, str) else None
        stage_usages.append(
            StageUsage(
                task_name=invoke_request.task_name,
                api_mode=result.api_mode,
                latency_ms=result.latency_ms,
                input_tokens=usage["input_tokens"],
                cached_input_tokens=usage["cached_input_tokens"],
                cache_creation_input_tokens=usage["cache_creation_input_tokens"],
                output_tokens=usage["output_tokens"],
                total_tokens=usage["total_tokens"],
                response_id=result.response_id,
                chosen_mode=chosen_mode,
            )
        )

    observer_token = set_llm_invoke_observer(observe_invoke)
    cache_mode_token = set_session_cache_mode_override(cache_mode)
    started = time.perf_counter()
    parsed = None
    error: str | None = None
    try:
        parsed = parse_gmail_payload(
            db=None,  # type: ignore[arg-type]
            payload={
                "message_id": row.get("message_id"),
                "thread_id": row.get("thread_id"),
                "subject": row.get("subject"),
                "snippet": row.get("snippet"),
                "body_text": row.get("body_text"),
                "from_header": row.get("from_header"),
                "internal_date": row.get("internal_date"),
                "label_ids": row.get("label_ids") or [],
            },
            context=ParserContext(
                source_id=source_id,
                provider="gmail",
                source_kind="email",
                request_id=f"local-email-pool-{api_mode}-{cache_mode}-{row.get('sample_id')}",
            ),
        )
    except Exception as exc:  # noqa: BLE001
        error = str(exc)[:1000]
    finally:
        reset_session_cache_mode_override(cache_mode_token)
        reset_llm_invoke_observer(observer_token)

    sample_latency_ms = max(int((time.perf_counter() - started) * 1000), 0)
    stage_mode = next((item.chosen_mode for item in stage_usages if item.task_name == "gmail_purpose_mode_classify"), None)
    final_record_type = None
    actual_semantic_event_draft = None
    actual_directive = None
    if parsed is not None and parsed.records:
        record = parsed.records[0]
        final_record_type = record.get("record_type") if isinstance(record.get("record_type"), str) else None
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        draft = payload.get("semantic_event_draft")
        directive = payload.get("directive")
        actual_semantic_event_draft = draft if isinstance(draft, dict) else None
        actual_directive = directive if isinstance(directive, dict) else None

    accuracy = None
    if any(
        row.get(key) is not None
        for key in ("expected_mode", "expected_record_type", "expected_semantic_event_draft", "expected_directive")
    ):
        accuracy = evaluate_synthetic_accuracy(
            expected_mode=row.get("expected_mode"),
            expected_record_type=row.get("expected_record_type"),
            expected_semantic=row.get("expected_semantic_event_draft"),
            expected_directive=row.get("expected_directive"),
            stage_mode=stage_mode,
            final_record_type=final_record_type,
            actual_semantic=actual_semantic_event_draft,
            actual_directive=actual_directive,
        )

    return SampleRun(
        bucket=bucket,
        sample_id=str(row.get("sample_id") or row.get("message_id") or "unknown"),
        cache_mode=cache_mode,
        expected_mode=row.get("expected_mode") if isinstance(row.get("expected_mode"), str) else None,
        stage_mode=stage_mode,
        final_record_type=final_record_type,
        sample_latency_ms=sample_latency_ms,
        success=error is None,
        error=error,
        stage_usages=stage_usages,
        actual_semantic_event_draft=actual_semantic_event_draft,
        actual_directive=actual_directive,
        accuracy=accuracy,
    )



def evaluate_synthetic_accuracy(
    *,
    expected_mode: Any,
    expected_record_type: Any,
    expected_semantic: Any,
    expected_directive: Any,
    stage_mode: str | None,
    final_record_type: str | None,
    actual_semantic: dict[str, Any] | None,
    actual_directive: dict[str, Any] | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "mode_match": stage_mode == expected_mode,
        "record_type_match": final_record_type == expected_record_type,
    }
    if isinstance(expected_semantic, dict):
        field_matches = {field: expected_semantic.get(field) == (actual_semantic or {}).get(field) for field in ATOMIC_FIELDS}
        payload["semantic_field_matches"] = field_matches
        payload["semantic_exact_match"] = all(field_matches.values())
    if isinstance(expected_directive, dict):
        expected_selector = expected_directive.get("selector") if isinstance(expected_directive.get("selector"), dict) else {}
        expected_mutation = expected_directive.get("mutation") if isinstance(expected_directive.get("mutation"), dict) else {}
        actual_selector = (actual_directive or {}).get("selector") if isinstance((actual_directive or {}).get("selector"), dict) else {}
        actual_mutation = (actual_directive or {}).get("mutation") if isinstance((actual_directive or {}).get("mutation"), dict) else {}
        selector_matches = {field: expected_selector.get(field) == actual_selector.get(field) for field in DIRECTIVE_SELECTOR_FIELDS}
        mutation_matches = {field: expected_mutation.get(field) == actual_mutation.get(field) for field in DIRECTIVE_MUTATION_FIELDS}
        payload["directive_selector_matches"] = selector_matches
        payload["directive_mutation_matches"] = mutation_matches
        payload["directive_exact_match"] = all(selector_matches.values()) and all(mutation_matches.values())
    return payload



def normalize_usage(raw_usage: dict[str, Any]) -> dict[str, int | None]:
    input_tokens = _int_or_none(raw_usage.get("input_tokens"))
    output_tokens = _int_or_none(raw_usage.get("output_tokens"))
    total_tokens = _int_or_none(raw_usage.get("total_tokens"))
    cached_input_tokens = None
    cache_creation_input_tokens = None
    input_details = raw_usage.get("input_tokens_details") if isinstance(raw_usage.get("input_tokens_details"), dict) else {}
    prompt_details = raw_usage.get("prompt_tokens_details") if isinstance(raw_usage.get("prompt_tokens_details"), dict) else {}
    cached_input_tokens = _int_or_none(input_details.get("cached_tokens"))
    if cached_input_tokens is None:
        cached_input_tokens = _int_or_none(prompt_details.get("cached_tokens"))
    cache_creation_input_tokens = _int_or_none(prompt_details.get("cache_creation_input_tokens"))
    if cache_creation_input_tokens is None:
        cache_creation = prompt_details.get("cache_creation")
        if isinstance(cache_creation, dict):
            cache_creation_input_tokens = _int_or_none(cache_creation.get("ephemeral_5m_input_tokens"))
    if cached_input_tokens is None or cache_creation_input_tokens is None:
        x_details = raw_usage.get("x_details")
        if isinstance(x_details, list):
            for item in x_details:
                if not isinstance(item, dict):
                    continue
                nested_prompt_details = item.get("prompt_tokens_details")
                if not isinstance(nested_prompt_details, dict):
                    continue
                if cached_input_tokens is None:
                    cached_input_tokens = _int_or_none(nested_prompt_details.get("cached_tokens"))
                if cache_creation_input_tokens is None:
                    cache_creation_input_tokens = _int_or_none(nested_prompt_details.get("cache_creation_input_tokens"))
                if cache_creation_input_tokens is None:
                    nested_creation = nested_prompt_details.get("cache_creation")
                    if isinstance(nested_creation, dict):
                        cache_creation_input_tokens = _int_or_none(nested_creation.get("ephemeral_5m_input_tokens"))
                if cached_input_tokens is not None and cache_creation_input_tokens is not None:
                    break
    if input_tokens is None:
        input_tokens = _int_or_none(raw_usage.get("prompt_tokens"))
    if output_tokens is None:
        output_tokens = _int_or_none(raw_usage.get("completion_tokens"))
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "cache_creation_input_tokens": cache_creation_input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }



def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None



def aggregate_metrics(runs: list[SampleRun]) -> AggregateMetrics:
    latencies = [run.sample_latency_ms for run in runs if run.success]
    stage_rows = [stage for run in runs for stage in run.stage_usages]
    total_tokens = [stage.total_tokens for stage in stage_rows if stage.total_tokens is not None]
    input_tokens = [stage.input_tokens for stage in stage_rows if stage.input_tokens is not None]
    output_tokens = [stage.output_tokens for stage in stage_rows if stage.output_tokens is not None]
    cached_tokens = [stage.cached_input_tokens for stage in stage_rows if stage.cached_input_tokens is not None]
    return AggregateMetrics(
        sample_count=len(runs),
        success_count=sum(1 for run in runs if run.success),
        error_count=sum(1 for run in runs if not run.success),
        avg_sample_latency_ms=mean_or_none(latencies),
        median_sample_latency_ms=median_or_none(latencies),
        avg_total_tokens=mean_or_none(total_tokens),
        avg_input_tokens=mean_or_none(input_tokens),
        avg_output_tokens=mean_or_none(output_tokens),
        avg_cached_input_tokens=mean_or_none(cached_tokens),
        cache_hit_stage_count=sum(1 for stage in stage_rows if (stage.cached_input_tokens or 0) > 0),
        total_cached_input_tokens=sum(value for value in cached_tokens if value is not None),
    )



def aggregate_synthetic_accuracy(runs: list[SampleRun]) -> SyntheticAccuracy:
    accuracy_rows = [run.accuracy for run in runs if isinstance(run.accuracy, dict)]
    field_totals: dict[str, list[bool]] = {}
    for row in accuracy_rows:
        for key in ("semantic_field_matches", "directive_selector_matches", "directive_mutation_matches"):
            values = row.get(key)
            if not isinstance(values, dict):
                continue
            for field, matched in values.items():
                if isinstance(matched, bool):
                    field_totals.setdefault(field, []).append(matched)
    atomic_exact = [row.get("semantic_exact_match") for row in accuracy_rows if isinstance(row.get("semantic_exact_match"), bool)]
    directive_exact = [row.get("directive_exact_match") for row in accuracy_rows if isinstance(row.get("directive_exact_match"), bool)]
    return SyntheticAccuracy(
        sample_count=len(accuracy_rows),
        mode_accuracy=bool_mean([row.get("mode_match") for row in accuracy_rows if isinstance(row.get("mode_match"), bool)]),
        record_type_accuracy=bool_mean([row.get("record_type_match") for row in accuracy_rows if isinstance(row.get("record_type_match"), bool)]),
        atomic_exact_accuracy=bool_mean([value for value in atomic_exact if isinstance(value, bool)]),
        directive_exact_accuracy=bool_mean([value for value in directive_exact if isinstance(value, bool)]),
        field_accuracy={field: bool_mean(values) or 0.0 for field, values in sorted(field_totals.items())},
    )



def build_report(
    *,
    started_at: datetime,
    source_id: int,
    seed: int,
    api_mode: str,
    cache_mode: str,
    selected_rows: dict[str, list[dict[str, Any]]],
    runs: list[SampleRun],
) -> dict[str, Any]:
    aggregates: dict[str, dict[str, Any]] = {}
    synthetic_accuracy: dict[str, Any] = {}
    for bucket in sorted(selected_rows):
        subset = [run for run in runs if run.bucket == bucket]
        aggregates[bucket] = asdict(aggregate_metrics(subset))
        if any(run.accuracy is not None for run in subset):
            synthetic_accuracy[bucket] = asdict(aggregate_synthetic_accuracy(subset))
    return {
        "started_at": started_at.isoformat(),
        "source_id": source_id,
        "seed": seed,
        "api_mode": api_mode,
        "cache_mode": cache_mode,
        "selection": {bucket: [row["sample_id"] for row in rows] for bucket, rows in selected_rows.items()},
        "runs": [asdict(run) for run in runs],
        "aggregates": aggregates,
        "synthetic_accuracy": synthetic_accuracy,
    }



def render_summary(report: dict[str, Any]) -> str:
    lines = [
        "# Local Email Pool Processing",
        "",
        f"- Started: `{report['started_at']}`",
        f"- Source ID: `{report['source_id']}`",
        f"- API mode: `{report['api_mode']}`",
        f"- Cache mode: `{report['cache_mode']}`",
        f"- Selection: `{json.dumps(report['selection'], ensure_ascii=False)}`",
        "",
    ]
    if report["synthetic_accuracy"]:
        lines.extend(["## Synthetic Accuracy", ""])
        for bucket, payload in report["synthetic_accuracy"].items():
            lines.extend(
                [
                    f"### {bucket}",
                    f"- sample_count: `{payload['sample_count']}`",
                    f"- mode_accuracy: `{format_pct(payload['mode_accuracy'])}`",
                    f"- record_type_accuracy: `{format_pct(payload['record_type_accuracy'])}`",
                    f"- atomic_exact_accuracy: `{format_pct(payload['atomic_exact_accuracy'])}`",
                    f"- directive_exact_accuracy: `{format_pct(payload['directive_exact_accuracy'])}`",
                    "",
                ]
            )
    lines.extend(["## Bucket Metrics", ""])
    for bucket, payload in report["aggregates"].items():
        lines.extend(
            [
                f"### {bucket}",
                f"- success: `{payload['success_count']}/{payload['sample_count']}`",
                f"- errors: `{payload['error_count']}`",
                f"- avg_sample_latency_ms: `{fmt_num(payload['avg_sample_latency_ms'])}`",
                f"- median_sample_latency_ms: `{fmt_num(payload['median_sample_latency_ms'])}`",
                f"- avg_total_tokens: `{fmt_num(payload['avg_total_tokens'])}`",
                f"- avg_input_tokens: `{fmt_num(payload['avg_input_tokens'])}`",
                f"- avg_output_tokens: `{fmt_num(payload['avg_output_tokens'])}`",
                f"- avg_cached_input_tokens: `{fmt_num(payload['avg_cached_input_tokens'])}`",
                f"- cache_hit_stage_count: `{payload['cache_hit_stage_count']}`",
                f"- total_cached_input_tokens: `{payload['total_cached_input_tokens']}`",
                "",
            ]
        )
    return "\n".join(lines)



def mean_or_none(values: list[int | float]) -> float | None:
    return statistics.mean(values) if values else None



def median_or_none(values: list[int | float]) -> float | None:
    return statistics.median(values) if values else None



def bool_mean(values: list[bool]) -> float | None:
    if not values:
        return None
    return sum(1 for value in values if value) / len(values)



def format_pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.1f}%"



def fmt_num(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1f}"


@contextmanager
def llm_api_mode_override(api_mode: str):
    previous_mode = os.environ.get("INGESTION_LLM_API_MODE")
    os.environ["INGESTION_LLM_API_MODE"] = api_mode
    get_settings.cache_clear()
    try:
        yield
    finally:
        if previous_mode is None:
            os.environ.pop("INGESTION_LLM_API_MODE", None)
        else:
            os.environ["INGESTION_LLM_API_MODE"] = previous_mode
        get_settings.cache_clear()


if __name__ == "__main__":
    main()
