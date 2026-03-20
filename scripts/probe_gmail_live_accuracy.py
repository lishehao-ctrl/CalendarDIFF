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
from app.modules.runtime.connectors.gmail_fetcher import _known_course_tokens_for_source, matches_gmail_source_filters
from app.modules.runtime.connectors.llm_parsers.contracts import ParserContext
from app.modules.runtime.connectors.llm_parsers.gmail_parser import parse_gmail_payload
import app.modules.runtime.connectors.llm_parsers.semantic_orchestrator as semantic_orchestrator
from app.modules.sources.source_secrets import decode_source_secrets
from app.modules.runtime.connectors.clients.gmail_client import GmailClient

OUTPUT_ROOT = Path("/Users/lishehao/Desktop/Project/CalendarDIFF/output")


@dataclass
class StageUsage:
    sample_id: str
    task_name: str
    latency_ms: int | None
    input_tokens: int | None
    cached_input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    json_object: dict[str, Any]


@dataclass
class SampleReport:
    sample_id: str
    subject: str
    from_header: str
    snippet: str
    body_preview: str
    stage_mode: str | None
    final_record_type: str | None
    semantic_summary: dict[str, Any] | None
    directive_summary: dict[str, Any] | None
    stage_usages: list[StageUsage]
    error: str | None


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe live Gmail parser accuracy and KV cache usage.")
    parser.add_argument("--source-id", type=int, default=2)
    parser.add_argument("--scan-limit", type=int, default=120)
    parser.add_argument("--max-hits", type=int, default=6)
    args = parser.parse_args()

    started_at = datetime.now(timezone.utc)
    run_dir = OUTPUT_ROOT / f"gmail-live-probe-{started_at.strftime('%Y%m%d-%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    samples = collect_samples(source_id=args.source_id, scan_limit=args.scan_limit, max_hits=args.max_hits)
    reports = [run_sample(sample=sample, source_id=args.source_id) for sample in samples]

    summary = {
        "started_at": started_at.isoformat(),
        "source_id": args.source_id,
        "scan_limit": args.scan_limit,
        "max_hits": args.max_hits,
        "sample_count": len(reports),
        "filter_rule": {
            "label_ids": ["INBOX"],
            "term_window": "active source term window",
            "routing": "matches_gmail_source_filters() with current source config and known course tokens",
        },
        "reports": [asdict(report) for report in reports],
    }
    (run_dir / "report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "summary.md").write_text(render_summary(summary), encoding="utf-8")
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
        for message_id in ids[:scan_limit]:
            metadata = client.get_message_metadata(access_token=access_token, message_id=message_id)
            if not matches_gmail_source_filters(
                metadata=metadata,
                config=source.config.config_json if source.config else {},
                term_window=term_window,
                timezone_name=source_timezone_name(source),
                known_course_tokens=known_tokens,
            ):
                continue
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


def run_sample(*, sample: dict[str, Any], source_id: int) -> SampleReport:
    stage_usages: list[StageUsage] = []
    original_invoke = semantic_orchestrator.invoke_llm_json

    def wrapped_invoke(db, *, invoke_request):  # type: ignore[no-untyped-def]
        result = original_invoke(db, invoke_request=invoke_request)
        usage = result.raw_usage if isinstance(result.raw_usage, dict) else {}
        input_details = usage.get("input_tokens_details") if isinstance(usage.get("input_tokens_details"), dict) else {}
        stage_usages.append(
            StageUsage(
                sample_id=str(sample["message_id"]),
                task_name=invoke_request.task_name,
                latency_ms=result.latency_ms,
                input_tokens=_int_or_none(usage.get("input_tokens")),
                cached_input_tokens=_int_or_none(input_details.get("cached_tokens")),
                output_tokens=_int_or_none(usage.get("output_tokens")),
                total_tokens=_int_or_none(usage.get("total_tokens")),
                json_object=result.json_object if isinstance(result.json_object, dict) else {},
            )
        )
        return result

    semantic_orchestrator.invoke_llm_json = wrapped_invoke
    parsed = None
    error: str | None = None
    try:
        session_factory = get_session_factory()
        with session_factory() as db:
            parsed = parse_gmail_payload(
                db=db,
                payload=sample,
                context=ParserContext(
                    source_id=source_id,
                    provider="gmail",
                    source_kind="email",
                    request_id=f"live-gmail-probe-{sample['message_id']}",
                ),
            )
    except Exception as exc:  # noqa: BLE001
        error = str(exc)[:1000]
    finally:
        semantic_orchestrator.invoke_llm_json = original_invoke

    final_record_type: str | None = None
    semantic_summary: dict[str, Any] | None = None
    directive_summary: dict[str, Any] | None = None
    if parsed is not None and parsed.records:
        record = parsed.records[0]
        final_record_type = record.get("record_type") if isinstance(record.get("record_type"), str) else None
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        if final_record_type == "gmail.message.extracted":
            draft = payload.get("semantic_event_draft") if isinstance(payload.get("semantic_event_draft"), dict) else {}
            semantic_summary = {
                "course": _course_label(draft),
                "raw_type": draft.get("raw_type"),
                "event_name": draft.get("event_name"),
                "ordinal": draft.get("ordinal"),
                "due_date": draft.get("due_date"),
                "due_time": draft.get("due_time"),
                "confidence": draft.get("confidence"),
            }
        elif final_record_type == "gmail.directive.extracted":
            directive = payload.get("directive") if isinstance(payload.get("directive"), dict) else {}
            directive_summary = {
                "selector": directive.get("selector"),
                "mutation": directive.get("mutation"),
                "confidence": directive.get("confidence"),
            }

    stage_mode = None
    for stage in stage_usages:
        if stage.task_name == "gmail_purpose_mode_classify":
            mode = stage.json_object.get("mode")
            stage_mode = mode if isinstance(mode, str) else None
            break

    return SampleReport(
        sample_id=str(sample["message_id"]),
        subject=str(sample.get("subject") or ""),
        from_header=str(sample.get("from_header") or ""),
        snippet=str(sample.get("snippet") or ""),
        body_preview=str((sample.get("body_text") or "")[:400]),
        stage_mode=stage_mode,
        final_record_type=final_record_type,
        semantic_summary=semantic_summary,
        directive_summary=directive_summary,
        stage_usages=stage_usages,
        error=error,
    )


def render_summary(summary: dict[str, Any]) -> str:
    lines = [
        "# Gmail Live Probe",
        "",
        f"- Source ID: `{summary['source_id']}`",
        f"- Scan limit: `{summary['scan_limit']}`",
        f"- Matched samples: `{summary['sample_count']}`",
        "- Filter rule: `matches_gmail_source_filters()` with current source config, active term window, and `INBOX` label",
        "",
    ]
    for report in summary["reports"]:
        lines.extend(
            [
                f"## {report['sample_id']}",
                f"- Subject: `{report['subject']}`",
                f"- From: `{report['from_header']}`",
                f"- Stage mode: `{report['stage_mode']}`",
                f"- Final record type: `{report['final_record_type']}`",
                f"- Semantic summary: `{json.dumps(report['semantic_summary'], ensure_ascii=False) if report['semantic_summary'] is not None else '-'}`",
                f"- Directive summary: `{json.dumps(report['directive_summary'], ensure_ascii=False) if report['directive_summary'] is not None else '-'}`",
                f"- Error: `{report['error'] if report['error'] is not None else '-'}`",
            ]
        )
        for stage in report["stage_usages"]:
            lines.append(
                f"- Stage `{stage['task_name']}`: input={stage['input_tokens']} cached={stage['cached_input_tokens']} output={stage['output_tokens']} total={stage['total_tokens']} latency_ms={stage['latency_ms']}"
            )
        lines.append("")
    return "\n".join(lines)


def _int_or_none(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _course_label(draft: dict[str, Any]) -> str | None:
    dept = draft.get("course_dept")
    number = draft.get("course_number")
    suffix = draft.get("course_suffix")
    if not isinstance(dept, str) or not isinstance(number, int):
        return None
    suffix_text = suffix if isinstance(suffix, str) else ""
    return f"{dept} {number}{suffix_text}"


if __name__ == "__main__":
    main()
