#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import random
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings
from app.db.models.input import InputSource
from app.db.session import get_session_factory
from app.modules.common.source_monitoring_window import (
    message_internal_date_in_window,
    parse_source_monitoring_window,
    source_timezone_name,
)
from app.modules.llm_gateway.runtime_control import (
    reset_llm_invoke_observer,
    reset_session_cache_mode_override,
    set_llm_invoke_observer,
    set_session_cache_mode_override,
)
from app.modules.llm_gateway.usage_normalizer import normalize_llm_usage
from app.modules.runtime.connectors.clients.gmail_client import GmailClient
from app.modules.runtime.connectors.gmail_fetcher import _effective_gmail_label_ids, _known_course_tokens_for_source
from app.modules.runtime.connectors.gmail_second_filter import run_gmail_second_filter, should_enforce_gmail_second_filter
from app.modules.runtime.connectors.llm_parsers.contracts import ParserContext
from app.modules.runtime.connectors.llm_parsers.gmail_parser import parse_gmail_payload
from app.modules.runtime.connectors.source_orchestrator import route_gmail_message
from app.modules.sources.source_secrets import decode_source_secrets
import app.modules.runtime.connectors.llm_parsers.semantic_orchestrator as semantic_orchestrator

OUTPUT_ROOT = REPO_ROOT / "output"
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "private" / "email_pool"
DEFAULT_REAL_SOURCE_ID = 2
DEFAULT_REAL_SAMPLE_COUNT = 100
DEFAULT_SYNTHETIC_TARGET_COUNT = 10
DEFAULT_REAL_SCAN_LIMIT = 500
DEFAULT_SEED = 20260321
RMB_PER_M_INPUT = 0.2
RMB_PER_M_OUTPUT = 2.0


@dataclass
class MixedSample:
    sample_id: str
    origin: str
    message_id: str
    thread_id: str | None
    subject: str
    from_header: str
    snippet: str
    body_text: str | None
    internal_date: str | None
    label_ids: list[str]


@dataclass
class BertDecisionLog:
    sample_id: str
    action: str
    stage: str
    reason_code: str
    risk_band: str
    label: str | None
    confidence: float | None
    would_suppress: bool
    elapsed_ms: int


@dataclass
class LlmStageUsage:
    sample_id: str
    task_name: str
    latency_ms: int | None
    input_tokens: int | None
    cached_input_tokens: int | None
    cache_creation_input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    model: str | None
    api_mode: str | None


@dataclass
class MessageRunResult:
    sample_id: str
    parse_success: bool
    parse_error: str | None
    record_count: int
    final_record_types: list[str]
    stage_usages: list[LlmStageUsage]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare prefilter->LLM versus prefilter->BERT(HF)->LLM on real Gmail + synthetic target mix."
    )
    parser.add_argument("--source-id", type=int, default=DEFAULT_REAL_SOURCE_ID)
    parser.add_argument("--real-sample-count", type=int, default=DEFAULT_REAL_SAMPLE_COUNT)
    parser.add_argument("--synthetic-target-count", type=int, default=DEFAULT_SYNTHETIC_TARGET_COUNT)
    parser.add_argument("--real-scan-limit", type=int, default=DEFAULT_REAL_SCAN_LIMIT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output-dir", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    started_at = datetime.now(timezone.utc)
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else OUTPUT_ROOT / f"real-gmail-filter-compare-{started_at.strftime('%Y%m%d-%H%M%S')}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.seed)
    source, source_config, known_course_tokens = load_real_source_context(source_id=args.source_id)
    real_samples = collect_real_gmail_samples(
        source=source,
        count=int(args.real_sample_count),
        scan_limit=int(args.real_scan_limit),
        rng=rng,
    )
    synthetic_samples = collect_synthetic_target_samples(
        count=int(args.synthetic_target_count),
        rng=rng,
    )
    mixed_samples = real_samples + synthetic_samples
    rng.shuffle(mixed_samples)

    baseline = run_strategy(
        strategy_name="prefilter_then_llm",
        samples=mixed_samples,
        source=source,
        source_config=source_config,
        known_course_tokens=known_course_tokens,
        use_bert=False,
        cache_scope_suffix="prefilter_only",
    )
    bert = run_strategy(
        strategy_name="prefilter_then_bert_then_llm",
        samples=mixed_samples,
        source=source,
        source_config=source_config,
        known_course_tokens=known_course_tokens,
        use_bert=True,
        cache_scope_suffix="prefilter_bert",
    )

    report = build_report(
        started_at=started_at,
        source_id=source.id,
        real_sample_count=len(real_samples),
        synthetic_target_count=len(synthetic_samples),
        seed=args.seed,
        baseline=baseline,
        bert=bert,
    )
    (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "summary.md").write_text(render_summary(report), encoding="utf-8")
    print(output_dir)


def load_real_source_context(*, source_id: int) -> tuple[InputSource, dict[str, Any], set[str]]:
    session_factory = get_session_factory()
    with session_factory() as db:
        source = db.get(InputSource, source_id)
        if source is None:
            raise RuntimeError(f"gmail source id={source_id} not found")
        if source.provider != "gmail":
            raise RuntimeError(f"source id={source_id} is not gmail")
        _ = source.secrets
        _ = source.config
        _ = source.user
        source_config = source.config.config_json if source.config and isinstance(source.config.config_json, dict) else {}
        known_course_tokens = _known_course_tokens_for_source(source)
        db.expunge(source)
        return source, source_config, known_course_tokens


def collect_real_gmail_samples(
    *,
    source: InputSource,
    count: int,
    scan_limit: int,
    rng: random.Random,
) -> list[MixedSample]:
    secrets = decode_source_secrets(source)
    client = GmailClient()
    access_token = _resolve_real_access_token(client=client, secrets=secrets)
    term_window = parse_source_monitoring_window(source, required=False)
    query = None
    if term_window is not None:
        start_date, end_exclusive = term_window.gmail_query_bounds(timezone_name=source_timezone_name(source))
        query = f"after:{start_date} before:{end_exclusive}"
    message_ids = _list_message_ids_limited(
        client=client,
        access_token=access_token,
        query=query,
        label_ids=["INBOX"],
        limit=max(scan_limit, count),
    )
    candidate_ids = message_ids[: max(scan_limit, count)]
    if len(candidate_ids) < count:
        raise RuntimeError(f"not enough inbox messages to sample {count}; found {len(candidate_ids)}")
    selected_ids = rng.sample(candidate_ids, count)
    samples: list[MixedSample] = []
    for message_id in selected_ids:
        metadata = client.get_message_metadata(access_token=access_token, message_id=message_id)
        samples.append(
            MixedSample(
                sample_id=f"real:{metadata.message_id}",
                origin="real_gmail",
                message_id=metadata.message_id,
                thread_id=metadata.thread_id,
                subject=metadata.subject,
                from_header=metadata.from_header,
                snippet=metadata.snippet,
                body_text=metadata.body_text,
                internal_date=metadata.internal_date,
                label_ids=list(metadata.label_ids),
            )
        )
    return samples


def _list_message_ids_limited(
    *,
    client: GmailClient,
    access_token: str,
    query: str | None,
    label_ids: list[str],
    limit: int,
) -> list[str]:
    message_ids: list[str] = []
    seen_ids: set[str] = set()
    page_token: str | None = None
    while len(message_ids) < limit:
        params: dict[str, Any] = {"maxResults": "500"}
        if query:
            params["q"] = query
        if label_ids:
            params["labelIds"] = [label for label in label_ids if isinstance(label, str) and label.strip()]
        if page_token is not None:
            params["pageToken"] = page_token
        payload = client._get_json("/messages", access_token=access_token, params=params)  # type: ignore[attr-defined]
        for item in payload.get("messages", []) or []:
            if not isinstance(item, dict):
                continue
            message_id = item.get("id")
            if isinstance(message_id, str) and message_id and message_id not in seen_ids:
                seen_ids.add(message_id)
                message_ids.append(message_id)
                if len(message_ids) >= limit:
                    break
        next_page_token = payload.get("nextPageToken")
        if not isinstance(next_page_token, str) or not next_page_token:
            break
        page_token = next_page_token
    return message_ids


def _resolve_real_access_token(*, client: GmailClient, secrets: dict[str, Any]) -> str:
    refresh_token = secrets.get("refresh_token")
    if isinstance(refresh_token, str) and refresh_token:
        return client.refresh_access_token(refresh_token=refresh_token).access_token
    access_token = secrets.get("access_token")
    if isinstance(access_token, str) and access_token:
        return access_token
    raise RuntimeError("gmail source is missing refresh_token/access_token")


def collect_synthetic_target_samples(*, count: int, rng: random.Random) -> list[MixedSample]:
    path = FIXTURE_ROOT / "year_timeline_gmail" / "samples.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    target_rows = [
        row
        for row in rows
        if row.get("prefilter_target_class") == "target_signal"
    ]
    if len(target_rows) < count:
        raise RuntimeError(f"not enough synthetic target rows to sample {count}")
    picked = rng.sample(target_rows, count)
    return [
        MixedSample(
            sample_id=str(row.get("sample_id") or row.get("message_id") or f"synthetic-{index}"),
            origin="synthetic_target",
            message_id=str(row.get("message_id") or row.get("sample_id") or f"synthetic-{index}"),
            thread_id=str(row.get("thread_id") or f"thread-synthetic-{index}"),
            subject=str(row.get("subject") or ""),
            from_header=str(row.get("from_header") or ""),
            snippet=str(row.get("snippet") or ""),
            body_text=str(row.get("body_text") or ""),
            internal_date=str(row.get("internal_date") or ""),
            label_ids=[value for value in (row.get("label_ids") or []) if isinstance(value, str)],
        )
        for index, row in enumerate(picked, start=1)
    ]


def run_strategy(
    *,
    strategy_name: str,
    samples: list[MixedSample],
    source: InputSource,
    source_config: dict[str, Any],
    known_course_tokens: set[str],
    use_bert: bool,
    cache_scope_suffix: str,
) -> dict[str, Any]:
    prefilter_pass: list[MixedSample] = []
    bert_logs: list[BertDecisionLog] = []
    llm_results: list[MessageRunResult] = []
    term_window = parse_source_monitoring_window(source, required=False)
    timezone_name = source_timezone_name(source)

    for sample in samples:
        if not passes_primary_prefilter(
            sample=sample,
            config=source_config,
            term_window=term_window,
            timezone_name=timezone_name,
            known_course_tokens=known_course_tokens,
        ):
            continue
        prefilter_pass.append(sample)

    diff_message_count = len(samples)
    llm_candidates: list[MixedSample] = []
    with _temporary_bert_runtime(use_bert=use_bert):
        for sample in prefilter_pass:
            if not use_bert:
                llm_candidates.append(sample)
                continue
            started = time.perf_counter()
            decision = run_gmail_second_filter(
                from_header=sample.from_header,
                subject=sample.subject,
                snippet=sample.snippet,
                body_text=sample.body_text,
                label_ids=sample.label_ids,
                known_course_tokens=known_course_tokens,
                diff_message_count=diff_message_count,
            )
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            bert_logs.append(
                BertDecisionLog(
                    sample_id=sample.sample_id,
                    action=decision.action,
                    stage=decision.stage,
                    reason_code=decision.reason_code,
                    risk_band=decision.risk_band,
                    label=decision.label,
                    confidence=decision.confidence,
                    would_suppress=decision.would_suppress,
                    elapsed_ms=elapsed_ms,
                )
            )
            if should_enforce_gmail_second_filter(decision):
                continue
            llm_candidates.append(sample)

    for sample in llm_candidates:
        llm_results.append(
            run_llm_parse_for_sample(
                sample=sample,
                source_id=source.id,
                cache_scope_suffix=cache_scope_suffix,
            )
        )

    return {
        "strategy_name": strategy_name,
        "input_message_count": len(samples),
        "prefilter_pass_count": len(prefilter_pass),
        "bert": summarize_bert_logs(bert_logs),
        "llm_candidate_count": len(llm_candidates),
        "llm": summarize_llm_results(llm_results),
    }


def passes_primary_prefilter(
    *,
    sample: MixedSample,
    config: dict[str, Any],
    term_window,
    timezone_name: str | None,
    known_course_tokens: set[str],
) -> bool:
    if term_window is not None and not message_internal_date_in_window(
        internal_date=sample.internal_date,
        monitoring_window=term_window,
        timezone_name=timezone_name,
    ):
        return False

    effective_label_ids = _effective_gmail_label_ids(config)
    if effective_label_ids and not any(label in sample.label_ids for label in effective_label_ids):
        return False

    from_contains = config.get("from_contains")
    explicit_sender_signal = False
    if isinstance(from_contains, str) and from_contains.strip():
        if from_contains.strip().lower() not in sample.from_header.lower():
            return False
        explicit_sender_signal = True

    subject_keywords = config.get("subject_keywords")
    explicit_subject_signal = False
    if isinstance(subject_keywords, list):
        normalized_keywords = [value.strip().lower() for value in subject_keywords if isinstance(value, str) and value.strip()]
        if normalized_keywords:
            subject_text = sample.subject.lower()
            if not any(keyword in subject_text for keyword in normalized_keywords):
                return False
            explicit_subject_signal = True

    decision = route_gmail_message(
        from_header=sample.from_header,
        subject=sample.subject,
        snippet=sample.snippet,
        body_text=sample.body_text,
        explicit_sender_signal=explicit_sender_signal,
        explicit_subject_signal=explicit_subject_signal,
        known_course_tokens=known_course_tokens,
    )
    return decision.route == "parse"


def run_llm_parse_for_sample(
    *,
    sample: MixedSample,
    source_id: int,
    cache_scope_suffix: str,
) -> MessageRunResult:
    stage_usages: list[LlmStageUsage] = []
    original_invoke = semantic_orchestrator.invoke_llm_json

    def wrapped_invoke(db, *, invoke_request):  # type: ignore[no-untyped-def]
        cache_prefix_payload = invoke_request.cache_prefix_payload if isinstance(invoke_request.cache_prefix_payload, dict) else {}
        scoped_request = replace(
            invoke_request,
            cache_prefix_payload={
                **cache_prefix_payload,
                "_experiment_cache_scope": cache_scope_suffix,
            },
            request_id=f"{invoke_request.request_id}:{cache_scope_suffix}" if invoke_request.request_id else cache_scope_suffix,
        )
        result = original_invoke(db, invoke_request=scoped_request)
        raw_usage = result.raw_usage if isinstance(result.raw_usage, dict) else {}
        usage = normalize_llm_usage(raw_usage)
        stage_usages.append(
            LlmStageUsage(
                sample_id=sample.sample_id,
                task_name=scoped_request.task_name,
                latency_ms=result.latency_ms,
                input_tokens=_int_or_none(usage.get("input_tokens")),
                cached_input_tokens=_int_or_none(usage.get("cached_input_tokens")),
                cache_creation_input_tokens=_int_or_none(usage.get("cache_creation_input_tokens")),
                output_tokens=_int_or_none(usage.get("output_tokens")),
                total_tokens=_int_or_none(usage.get("total_tokens")),
                model=result.model,
                api_mode=result.api_mode,
            )
        )
        return result

    semantic_orchestrator.invoke_llm_json = wrapped_invoke
    session_factory = get_session_factory()
    parse_error: str | None = None
    record_count = 0
    final_record_types: list[str] = []
    cache_token = set_session_cache_mode_override("enable")
    try:
        with session_factory() as db:
            parsed = parse_gmail_payload(
                db=db,
                payload={
                    "message_id": sample.message_id,
                    "thread_id": sample.thread_id,
                    "subject": sample.subject,
                    "snippet": sample.snippet,
                    "body_text": sample.body_text,
                    "from_header": sample.from_header,
                    "internal_date": sample.internal_date,
                    "label_ids": sample.label_ids,
                },
                context=ParserContext(
                    source_id=source_id,
                    provider="gmail",
                    source_kind="email",
                    request_id=f"exp-{cache_scope_suffix}-{sample.message_id}",
                ),
            )
            record_count = len(parsed.records)
            final_record_types = [
                str(record.get("record_type") or "")
                for record in parsed.records
                if isinstance(record, dict)
            ]
            db.rollback()
    except Exception as exc:  # noqa: BLE001
        parse_error = str(exc)[:1000]
    finally:
        reset_session_cache_mode_override(cache_token)
        semantic_orchestrator.invoke_llm_json = original_invoke

    return MessageRunResult(
        sample_id=sample.sample_id,
        parse_success=parse_error is None,
        parse_error=parse_error,
        record_count=record_count,
        final_record_types=final_record_types,
        stage_usages=stage_usages,
    )


def summarize_bert_logs(logs: list[BertDecisionLog]) -> dict[str, Any]:
    if not logs:
        return {
            "call_count": 0,
            "suppressed_count": 0,
            "allow_count": 0,
            "abstain_count": 0,
            "endpoint_error_count": 0,
            "avg_latency_ms": None,
            "max_latency_ms": None,
            "reason_counts": {},
            "risk_counts": {},
        }
    reason_counts: dict[str, int] = {}
    risk_counts: dict[str, int] = {}
    endpoint_error_count = 0
    suppressed_count = 0
    allow_count = 0
    abstain_count = 0
    for row in logs:
        reason_counts[row.reason_code] = reason_counts.get(row.reason_code, 0) + 1
        risk_counts[row.risk_band] = risk_counts.get(row.risk_band, 0) + 1
        if row.reason_code.startswith("secondary_filter_endpoint_error:"):
            endpoint_error_count += 1
        if row.would_suppress:
            suppressed_count += 1
        elif row.action == "allow":
            allow_count += 1
        else:
            abstain_count += 1
    latencies = [row.elapsed_ms for row in logs]
    return {
        "call_count": len(logs),
        "suppressed_count": suppressed_count,
        "allow_count": allow_count,
        "abstain_count": abstain_count,
        "endpoint_error_count": endpoint_error_count,
        "avg_latency_ms": round(mean(latencies), 2),
        "max_latency_ms": max(latencies),
        "reason_counts": reason_counts,
        "risk_counts": risk_counts,
    }


def summarize_llm_results(results: list[MessageRunResult]) -> dict[str, Any]:
    stage_rows = [stage for result in results for stage in result.stage_usages]
    input_tokens = sum(value for value in (_zero_if_none(stage.input_tokens) for stage in stage_rows))
    cached_input_tokens = sum(value for value in (_zero_if_none(stage.cached_input_tokens) for stage in stage_rows))
    cache_creation_input_tokens = sum(value for value in (_zero_if_none(stage.cache_creation_input_tokens) for stage in stage_rows))
    output_tokens = sum(value for value in (_zero_if_none(stage.output_tokens) for stage in stage_rows))
    total_tokens = sum(value for value in (_zero_if_none(stage.total_tokens) for stage in stage_rows))
    latencies = [stage.latency_ms for stage in stage_rows if stage.latency_ms is not None]
    parse_error_count = sum(1 for result in results if not result.parse_success)
    record_count = sum(result.record_count for result in results)
    llm_rmb_estimate = round(
        (input_tokens / 1_000_000.0) * RMB_PER_M_INPUT
        + (output_tokens / 1_000_000.0) * RMB_PER_M_OUTPUT,
        6,
    )
    return {
        "message_count": len(results),
        "parse_success_count": len(results) - parse_error_count,
        "parse_error_count": parse_error_count,
        "record_count": record_count,
        "successful_call_count": len(stage_rows),
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "cache_creation_input_tokens": cache_creation_input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cache_hit_ratio": round(cached_input_tokens / input_tokens, 4) if input_tokens > 0 else None,
        "avg_latency_ms": round(mean(latencies), 2) if latencies else None,
        "max_latency_ms": max(latencies) if latencies else None,
        "naive_llm_cost_rmb": llm_rmb_estimate,
    }


def build_report(
    *,
    started_at: datetime,
    source_id: int,
    real_sample_count: int,
    synthetic_target_count: int,
    seed: int,
    baseline: dict[str, Any],
    bert: dict[str, Any],
) -> dict[str, Any]:
    llm_cost_delta = round(
        baseline["llm"]["naive_llm_cost_rmb"] - bert["llm"]["naive_llm_cost_rmb"],
        6,
    )
    llm_input_delta = baseline["llm"]["input_tokens"] - bert["llm"]["input_tokens"]
    llm_output_delta = baseline["llm"]["output_tokens"] - bert["llm"]["output_tokens"]
    return {
        "started_at": started_at.isoformat(),
        "source_id": source_id,
        "seed": seed,
        "dataset": {
            "real_sample_count": real_sample_count,
            "synthetic_target_count": synthetic_target_count,
            "total_count": real_sample_count + synthetic_target_count,
        },
        "pricing_assumptions": {
            "llm_rmb_per_m_input_tokens": RMB_PER_M_INPUT,
            "llm_rmb_per_m_output_tokens": RMB_PER_M_OUTPUT,
            "hf_endpoint_note": "HF endpoint cost is not directly observable in-app; compare LLM savings against your endpoint warm-window cost separately.",
        },
        "strategies": {
            "prefilter_then_llm": baseline,
            "prefilter_then_bert_then_llm": bert,
        },
        "comparison": {
            "llm_input_token_delta_saved_by_bert": llm_input_delta,
            "llm_output_token_delta_saved_by_bert": llm_output_delta,
            "naive_llm_cost_delta_rmb_saved_by_bert": llm_cost_delta,
            "bert_suppressed_count": bert["bert"]["suppressed_count"],
            "llm_message_delta": baseline["llm_candidate_count"] - bert["llm_candidate_count"],
            "llm_parse_error_delta": baseline["llm"]["parse_error_count"] - bert["llm"]["parse_error_count"],
        },
    }


def render_summary(report: dict[str, Any]) -> str:
    baseline = report["strategies"]["prefilter_then_llm"]
    bert = report["strategies"]["prefilter_then_bert_then_llm"]
    comparison = report["comparison"]
    lines = [
        "# Real Gmail + Synthetic Target Comparison",
        "",
        f"- Source ID: `{report['source_id']}`",
        f"- Dataset: real `{report['dataset']['real_sample_count']}` + synthetic target `{report['dataset']['synthetic_target_count']}` = `{report['dataset']['total_count']}`",
        f"- Seed: `{report['seed']}`",
        "",
        "## Prefilter -> LLM",
        f"- prefilter_pass_count: `{baseline['prefilter_pass_count']}`",
        f"- llm_candidate_count: `{baseline['llm_candidate_count']}`",
        f"- llm_input_tokens: `{baseline['llm']['input_tokens']}`",
        f"- llm_cached_input_tokens: `{baseline['llm']['cached_input_tokens']}`",
        f"- llm_cache_creation_input_tokens: `{baseline['llm']['cache_creation_input_tokens']}`",
        f"- llm_output_tokens: `{baseline['llm']['output_tokens']}`",
        f"- llm_cache_hit_ratio: `{baseline['llm']['cache_hit_ratio']}`",
        f"- llm_avg_latency_ms: `{baseline['llm']['avg_latency_ms']}`",
        f"- naive_llm_cost_rmb: `{baseline['llm']['naive_llm_cost_rmb']}`",
        "",
        "## Prefilter -> BERT(HF) -> LLM",
        f"- prefilter_pass_count: `{bert['prefilter_pass_count']}`",
        f"- bert_call_count: `{bert['bert']['call_count']}`",
        f"- bert_suppressed_count: `{bert['bert']['suppressed_count']}`",
        f"- bert_endpoint_error_count: `{bert['bert']['endpoint_error_count']}`",
        f"- bert_avg_latency_ms: `{bert['bert']['avg_latency_ms']}`",
        f"- llm_candidate_count: `{bert['llm_candidate_count']}`",
        f"- llm_input_tokens: `{bert['llm']['input_tokens']}`",
        f"- llm_cached_input_tokens: `{bert['llm']['cached_input_tokens']}`",
        f"- llm_cache_creation_input_tokens: `{bert['llm']['cache_creation_input_tokens']}`",
        f"- llm_output_tokens: `{bert['llm']['output_tokens']}`",
        f"- llm_cache_hit_ratio: `{bert['llm']['cache_hit_ratio']}`",
        f"- llm_avg_latency_ms: `{bert['llm']['avg_latency_ms']}`",
        f"- naive_llm_cost_rmb: `{bert['llm']['naive_llm_cost_rmb']}`",
        "",
        "## Comparison",
        f"- llm_input_token_delta_saved_by_bert: `{comparison['llm_input_token_delta_saved_by_bert']}`",
        f"- llm_output_token_delta_saved_by_bert: `{comparison['llm_output_token_delta_saved_by_bert']}`",
        f"- naive_llm_cost_delta_rmb_saved_by_bert: `{comparison['naive_llm_cost_delta_rmb_saved_by_bert']}`",
        f"- llm_message_delta: `{comparison['llm_message_delta']}`",
        f"- llm_parse_error_delta: `{comparison['llm_parse_error_delta']}`",
        "",
        "HF endpoint cost must be compared against your own warm-window bill separately.",
    ]
    return "\n".join(lines)


@contextmanager
def _temporary_bert_runtime(*, use_bert: bool):
    saved_mode = os.environ.get("GMAIL_SECONDARY_FILTER_MODE")
    saved_provider = os.environ.get("GMAIL_SECONDARY_FILTER_PROVIDER")
    try:
        if use_bert:
            os.environ["GMAIL_SECONDARY_FILTER_MODE"] = "enforce"
            os.environ["GMAIL_SECONDARY_FILTER_PROVIDER"] = "huggingface_endpoint"
        get_settings.cache_clear()
        yield
    finally:
        if saved_mode is None:
            os.environ.pop("GMAIL_SECONDARY_FILTER_MODE", None)
        else:
            os.environ["GMAIL_SECONDARY_FILTER_MODE"] = saved_mode
        if saved_provider is None:
            os.environ.pop("GMAIL_SECONDARY_FILTER_PROVIDER", None)
        else:
            os.environ["GMAIL_SECONDARY_FILTER_PROVIDER"] = saved_provider
        get_settings.cache_clear()


def _int_or_none(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _zero_if_none(value: int | None) -> int:
    return value if isinstance(value, int) else 0


if __name__ == "__main__":
    main()
