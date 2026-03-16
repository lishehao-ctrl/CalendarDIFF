from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.db.models.input import InputSource
from app.db.session import get_session_factory
from app.modules.common.source_term_window import parse_source_term_window, source_timezone_name
from app.modules.ingestion.gmail_fetcher import _known_course_tokens_for_source, matches_gmail_source_filters
from app.modules.ingestion.llm_parsers.schemas import (
    GmailAtomicSegmentExtractionResponse,
    GmailDirectiveExtractionResponse,
    GmailPurposeModeResponse,
)
from app.modules.input_control_plane.source_secrets import decode_source_secrets
from app.modules.llm_gateway import LlmInvokeRequest, invoke_llm_json
from app.modules.sync.gmail_client import GmailClient

OUTPUT_ROOT = Path("/Users/lishehao/Desktop/Project/CalendarDIFF/output")

CLASSIFY_PROMPT = (
    "Classify one Gmail message for assignment/exam monitoring. "
    'Return mode="unknown" when it is not clearly about monitored course work or assessments. '
    'Return mode="atomic" when it describes one concrete work/test event update. '
    'Return mode="directive" when it gives a rule or instruction that should mutate multiple existing work/test items. '
    "Do not extract semantic fields yet."
)

ATOMIC_PROMPT = (
    "Extract semantic info for one atomic course-work or assessment update from the Gmail message. "
    "Return event when it clearly describes one monitored work/test item; otherwise return unknown. "
    'Return JSON: {"outcome":"event"|"unknown",'
    '"semantic_event_draft":{"course_dept":string|null,"course_number":number|null,'
    '"course_suffix":string|null,"course_quarter":"WI"|"SP"|"SU"|"FA"|null,"course_year2":number|null,'
    '"raw_type":string|null,"event_name":string|null,"ordinal":number|null,'
    '"due_date":string|null,"due_time":string|null,"time_precision":"date_only"|"datetime"|null,'
    '"confidence":number,"evidence":string},'
    '"link_signals":{"keywords":["exam"|"midterm"|"final"],"exam_sequence":number|null,'
    '"location_text":string|null,"instructor_hint":string|null}}.'
)

DIRECTIVE_PROMPT = (
    "Extract directive semantics from the Gmail message. "
    "Use directive only when the message clearly describes a rule or instruction that changes "
    "multiple monitored work/test items. Otherwise return unknown. "
    'Return JSON with schema: {"outcome":"directive"|"unknown",'
    '"selector":{"course_dept":string|null,"course_number":number|null,'
    '"course_suffix":string|null,"course_quarter":"WI"|"SP"|"SU"|"FA"|null,"course_year2":number|null,'
    '"family_hint":string|null,"raw_type_hint":string|null,'
    '"scope_mode":"all_matching"|"ordinal_list"|"ordinal_range","ordinal_list":[number],'
    '"ordinal_range_start":number|null,"ordinal_range_end":number|null,'
    '"current_due_weekday":"monday"|"tuesday"|"wednesday"|"thursday"|"friday"|"saturday"|"sunday"|null,'
    '"applies_to_future_only":boolean},'
    '"mutation":{"move_weekday":"monday"|"tuesday"|"wednesday"|"thursday"|"friday"|"saturday"|"sunday"|null,'
    '"set_due_date":string|null},'
    '"confidence":number,"evidence":string}.'
)


@dataclass
class UsageRow:
    sample_id: str
    subject: str
    mode_name: str
    stage: str
    chosen_mode: str | None
    input_tokens: int | None
    cached_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    latency_ms: int | None
    success: bool
    error: str | None


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare Gmail cache behavior across chat-completions and responses.")
    parser.add_argument("--source-id", type=int, default=2)
    parser.add_argument("--scan-limit", type=int, default=600)
    parser.add_argument("--max-hits", type=int, default=25)
    parser.add_argument("--modes", type=str, default="chat,responses")
    args = parser.parse_args()

    run_dir = OUTPUT_ROOT / f"gmail-cache-compare-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    samples = collect_samples(source_id=args.source_id, scan_limit=args.scan_limit, max_hits=args.max_hits)
    rows: list[UsageRow] = []
    selected_modes = [item.strip() for item in args.modes.split(",") if item.strip()]
    for sample in samples:
        for mode_name in selected_modes:
            rows.extend(run_mode(sample=sample, source_id=args.source_id, mode_name=mode_name))

    payload = {
        "source_id": args.source_id,
        "scan_limit": args.scan_limit,
        "sample_count": len(samples),
        "modes": selected_modes,
        "rows": [asdict(row) for row in rows],
    }
    (run_dir / "report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "summary.md").write_text(render_summary(rows=rows, sample_count=len(samples), modes=selected_modes), encoding="utf-8")
    print(run_dir)


def collect_samples(*, source_id: int, scan_limit: int, max_hits: int) -> list[dict[str, Any]]:
    session_factory = get_session_factory()
    with session_factory() as db:
        source = db.get(InputSource, source_id)
        if source is None:
            raise RuntimeError(f"gmail source id={source_id} not found")
        secrets = decode_source_secrets(source)
        refresh_token = secrets.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            raise RuntimeError("gmail source is missing refresh_token")
        client = GmailClient()
        access_token = client.refresh_access_token(refresh_token=refresh_token).access_token
        term_window = parse_source_term_window(source, required=False)
        if term_window is None:
            raise RuntimeError("gmail source is missing term window")
        start_date, end_exclusive = term_window.gmail_query_bounds()
        ids = client.list_message_ids(
            access_token=access_token,
            query=f"after:{start_date} before:{end_exclusive}",
            label_ids=["INBOX"],
        )
        known_tokens = _known_course_tokens_for_source(source)
        samples: list[dict[str, Any]] = []
        seen: set[str] = set()
        for message_id in ids[:scan_limit]:
            metadata = client.get_message_metadata(access_token=access_token, message_id=message_id)
            if metadata.message_id in seen:
                continue
            if not matches_gmail_source_filters(
                metadata=metadata,
                config=source.config.config_json if source.config else {},
                term_window=term_window,
                timezone_name=source_timezone_name(source),
                known_course_tokens=known_tokens,
            ):
                continue
            seen.add(metadata.message_id)
            samples.append(
                {
                    "message_id": metadata.message_id,
                    "thread_id": metadata.thread_id,
                    "subject": metadata.subject,
                    "snippet": metadata.snippet,
                    "body_text": metadata.body_text,
                    "from_header": metadata.from_header,
                    "internal_date": metadata.internal_date,
                }
            )
            if len(samples) >= max_hits:
                break
        return samples


def run_mode(*, sample: dict[str, Any], source_id: int, mode_name: str) -> list[UsageRow]:
    rows: list[UsageRow] = []
    session_factory = get_session_factory()
    with session_factory() as db:
        classify_request = build_request(
            mode_name=mode_name,
            task_name="gmail_purpose_mode_classify",
            system_prompt=CLASSIFY_PROMPT,
            user_payload={"purpose": "assignment_or_exam_monitoring"},
            prefix=sample,
            output_schema_name="GmailPurposeModeResponse",
            output_schema_json=GmailPurposeModeResponse.model_json_schema(),
            source_id=source_id,
            request_id=f"{mode_name}-classify-{sample['message_id']}",
        )
        try:
            classify_result = invoke_llm_json(db, invoke_request=classify_request)
            classify_usage = normalize_usage(classify_result.raw_usage)
            chosen_mode = None
            if isinstance(classify_result.json_object, dict):
                raw_mode = classify_result.json_object.get("mode")
                chosen_mode = raw_mode if isinstance(raw_mode, str) else None
            rows.append(
                UsageRow(
                    sample_id=str(sample["message_id"]),
                    subject=str(sample.get("subject") or "")[:200],
                    mode_name=mode_name,
                    stage="classify",
                    chosen_mode=chosen_mode,
                    input_tokens=classify_usage["input_tokens"],
                    cached_tokens=classify_usage["cached_tokens"],
                    output_tokens=classify_usage["output_tokens"],
                    total_tokens=classify_usage["total_tokens"],
                    latency_ms=classify_result.latency_ms,
                    success=True,
                    error=None,
                )
            )
        except Exception as exc:  # noqa: BLE001
            rows.append(
                UsageRow(
                    sample_id=str(sample["message_id"]),
                    subject=str(sample.get("subject") or "")[:200],
                    mode_name=mode_name,
                    stage="classify",
                    chosen_mode=None,
                    input_tokens=None,
                    cached_tokens=None,
                    output_tokens=None,
                    total_tokens=None,
                    latency_ms=None,
                    success=False,
                    error=str(exc)[:600],
                )
            )
            return rows

        if chosen_mode not in {"atomic", "directive"}:
            return rows

        if chosen_mode == "atomic":
            system_prompt = ATOMIC_PROMPT
            output_schema_name = "GmailAtomicSegmentExtractionResponse"
            output_schema_json = GmailAtomicSegmentExtractionResponse.model_json_schema()
        else:
            system_prompt = DIRECTIVE_PROMPT
            output_schema_name = "GmailDirectiveExtractionResponse"
            output_schema_json = GmailDirectiveExtractionResponse.model_json_schema()

        extract_request = build_request(
            mode_name=mode_name,
            task_name=f"gmail_{chosen_mode}_semantic_extract",
            system_prompt=system_prompt,
            user_payload={"mode": chosen_mode, "purpose": "assignment_or_exam_monitoring"},
            prefix=sample,
            output_schema_name=output_schema_name,
            output_schema_json=output_schema_json,
            source_id=source_id,
            request_id=f"{mode_name}-extract-{sample['message_id']}",
        )
        try:
            extract_result = invoke_llm_json(db, invoke_request=extract_request)
            extract_usage = normalize_usage(extract_result.raw_usage)
            rows.append(
                UsageRow(
                    sample_id=str(sample["message_id"]),
                    subject=str(sample.get("subject") or "")[:200],
                    mode_name=mode_name,
                    stage="extract",
                    chosen_mode=chosen_mode,
                    input_tokens=extract_usage["input_tokens"],
                    cached_tokens=extract_usage["cached_tokens"],
                    output_tokens=extract_usage["output_tokens"],
                    total_tokens=extract_usage["total_tokens"],
                    latency_ms=extract_result.latency_ms,
                    success=True,
                    error=None,
                )
            )
        except Exception as exc:  # noqa: BLE001
            rows.append(
                UsageRow(
                    sample_id=str(sample["message_id"]),
                    subject=str(sample.get("subject") or "")[:200],
                    mode_name=mode_name,
                    stage="extract",
                    chosen_mode=chosen_mode,
                    input_tokens=None,
                    cached_tokens=None,
                    output_tokens=None,
                    total_tokens=None,
                    latency_ms=None,
                    success=False,
                    error=str(exc)[:600],
                )
            )
    return rows


def build_request(
    *,
    mode_name: str,
    task_name: str,
    system_prompt: str,
    user_payload: dict[str, Any],
    prefix: dict[str, Any],
    output_schema_name: str,
    output_schema_json: dict[str, Any],
    source_id: int,
    request_id: str,
) -> LlmInvokeRequest:
    if mode_name == "chat":
        return LlmInvokeRequest(
            task_name=task_name,
            system_prompt=system_prompt,
            user_payload=user_payload,
            cache_prefix_payload=prefix,
            output_schema_name=output_schema_name,
            output_schema_json=output_schema_json,
            source_id=source_id,
            request_id=request_id,
            source_provider="gmail",
            api_mode_override="chat_completions",
            session_cache_mode="enable",
        )
    return LlmInvokeRequest(
        task_name=task_name,
        system_prompt=system_prompt,
        user_payload=user_payload,
        shared_user_payload=prefix,
        output_schema_name=output_schema_name,
        output_schema_json=output_schema_json,
        source_id=source_id,
        request_id=request_id,
        source_provider="gmail",
        api_mode_override="responses",
        session_cache_mode="enable",
    )


def normalize_usage(raw_usage: dict[str, Any]) -> dict[str, int | None]:
    if not isinstance(raw_usage, dict):
        return {
            "input_tokens": None,
            "cached_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
        }

    input_tokens = _int_or_none(raw_usage.get("input_tokens"))
    output_tokens = _int_or_none(raw_usage.get("output_tokens"))
    total_tokens = _int_or_none(raw_usage.get("total_tokens"))
    cached_tokens = None

    prompt_details = raw_usage.get("prompt_tokens_details")
    if isinstance(prompt_details, dict):
        cached_tokens = _int_or_none(prompt_details.get("cached_tokens"))
        if input_tokens is None:
            input_tokens = _int_or_none(raw_usage.get("prompt_tokens"))
        if output_tokens is None:
            output_tokens = _int_or_none(raw_usage.get("completion_tokens"))
        if total_tokens is None:
            total_tokens = _int_or_none(raw_usage.get("total_tokens"))

    input_details = raw_usage.get("input_tokens_details")
    if isinstance(input_details, dict) and cached_tokens is None:
        cached_tokens = _int_or_none(input_details.get("cached_tokens"))

    x_details = raw_usage.get("x_details")
    if isinstance(x_details, list) and x_details:
        first = x_details[0]
        if isinstance(first, dict):
            if input_tokens is None:
                input_tokens = _int_or_none(first.get("input_tokens"))
            if output_tokens is None:
                output_tokens = _int_or_none(first.get("output_tokens"))
            if total_tokens is None:
                total_tokens = _int_or_none(first.get("total_tokens"))
            prompt_details = first.get("prompt_tokens_details")
            if isinstance(prompt_details, dict) and cached_tokens is None:
                cached_tokens = _int_or_none(prompt_details.get("cached_tokens"))

    return {
        "input_tokens": input_tokens,
        "cached_tokens": cached_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def render_summary(*, rows: list[UsageRow], sample_count: int, modes: list[str]) -> str:
    lines = [
        "# Gmail Cache Mode Comparison",
        "",
        f"- Unique Gmail samples: `{sample_count}`",
        "",
    ]
    for mode_name in modes:
        lines.append(f"## {mode_name}")
        mode_rows = [row for row in rows if row.mode_name == mode_name and row.success]
        for stage in ("classify", "extract"):
            stage_rows = [row for row in mode_rows if row.stage == stage]
            lines.append(f"- {stage}: {summarize(stage_rows)}")
        lines.append("")
    return "\n".join(lines)


def summarize(rows: list[UsageRow]) -> str:
    if not rows:
        return "no successful rows"
    input_total = sum(row.input_tokens or 0 for row in rows)
    cached_total = sum(row.cached_tokens or 0 for row in rows)
    output_total = sum(row.output_tokens or 0 for row in rows)
    total_total = sum(row.total_tokens or 0 for row in rows)
    ratio = (cached_total / input_total) if input_total else 0.0
    return (
        f"n={len(rows)}, avg_input={round(input_total/len(rows),2)}, "
        f"avg_cached={round(cached_total/len(rows),2)}, cache_ratio={round(ratio,4)}, "
        f"avg_output={round(output_total/len(rows),2)}, avg_total={round(total_total/len(rows),2)}"
    )


def _int_or_none(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


if __name__ == "__main__":
    main()
