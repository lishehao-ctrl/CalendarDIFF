from __future__ import annotations

import argparse
import json
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from icalendar import Calendar
from sqlalchemy.orm import Session

from app.db.models.input import InputSource
from app.db.session import get_session_factory
from app.modules.common.source_term_window import parse_iso_datetime, parse_source_term_window, source_timezone_name
from app.modules.runtime.connectors.gmail_fetcher import _known_course_tokens_for_source, matches_gmail_source_filters
from app.modules.runtime.connectors.llm_parsers.calendar_parser import _extract_source_facts
from app.modules.runtime.connectors.llm_parsers.schemas import (
    CalendarRelevanceResponse,
    CalendarSemanticEventClassification,
    GmailAtomicSegmentExtractionResponse,
    GmailDirectiveExtractionResponse,
    GmailPlannerResponse,
)
from app.modules.sources.source_secrets import decode_source_secrets
from app.modules.llm_gateway import LlmInvokeRequest, invoke_llm_json
from app.modules.runtime.connectors.clients.gmail_client import GmailClient

OUTPUT_ROOT = Path("/Users/lishehao/Desktop/Project/CalendarDIFF/output")
DEFAULT_SEED = 20260315

CALENDAR_SYSTEM_PROMPT = (
    "Decide whether the VEVENT is relevant to work/test monitoring. "
    "Relevant means course work/test events. "
    "Use event only for homework-like deliverables or test-like assessments. "
    "Homework-like includes required submissions or deliverables. "
    "Test-like includes quizzes, exams, midterms, finals, or similar assessments. "
    "Use unknown for lectures, discussions, sections, lab sessions, office hours, or anything outside work/test scope. "
    "Examples that should be relevant: Homework 1, Programming Assignment 6, Quiz 3, Midterm 2, Final Reflection, RQ21. "
    "Examples that should be unknown: Lecture, Discussion section moved, Office Hours, Lab session, campus event. "
    'Return JSON: {"outcome":"relevant"|"unknown"}. '
    'For unknown, return exactly {"outcome":"unknown"}.'
)

CALENDAR_SEMANTIC_SYSTEM_PROMPT = (
    "Extract the minimal semantic classification for one relevant work/test VEVENT. "
    "Only infer course identity, raw_type, event_name, ordinal, confidence, and evidence. "
    "Do not infer due date/time or link metadata; the backend derives those deterministically. "
    "Return only the classification object matching the schema."
)

GMAIL_PLANNER_SYSTEM_PROMPT = (
    "You are pass-1 planner for Gmail work/test change parsing. "
    "Classify message text into extraction segments. "
    "Only keep segments about homework-like course work or test-like assessment changes. "
    "Homework-like means any required deliverable or submission. "
    "Test-like means quizzes, exams, midterms, finals, or similar assessments. "
    "Only use atomic or directive when there is clear course context, such as a course identifier, "
    "class context, LMS sender, or unmistakable course-specific wording. "
    "Ignore lab, discussion, section, grade-only, newsletter, campus admin, or marketing content "
    "unless the text clearly changes homework-like work or test-like assessment requirements. "
    "Use unknown for competition announcements, recruiting or career tests, generic memos, newsletters, digests, "
    "study notes, solutions postings, opportunity announcements, grade notifications, graded or regrade notices, "
    "score-release messages, meeting notices, voting notices, annual meeting notices, corporate notices, "
    "and non-course content even if they mention "
    "words like quiz, test, final, deadline, or due. "
    'Return JSON: {"message_id":string|null,"mode":string,"segment_array":[{"segment_index":number,'
    '"anchor":string|null,"snippet":string|null,"segment_type_hint":"atomic"|"directive"|"unknown"}]}. '
    "Use segment_type_hint=atomic for independent homework-like or test-like change statements. "
    "Use directive when the text is a batch rule or instruction targeting homework-like work or test-like assessments. "
    "Use unknown for anything outside the monitored work/test scope or when relevance is genuinely unclear."
)

GMAIL_ATOMIC_SYSTEM_PROMPT = (
    "You are pass-2 extractor for one Gmail segment. "
    "Use only the provided segment snippet plus minimal message metadata. "
    "Classify only homework-like course work or test-like assessments. "
    "Homework-like means any required deliverable or submission. "
    "Test-like means quizzes, exams, midterms, finals, or similar assessments. "
    "If there is no clear course context, or the segment is a competition, recruiting or career test, "
    "memo, digest, study note, solutions post, grade notification, graded or regrade notice, "
    "score-release message, meeting notice, voting notice, annual meeting notice, corporate notice, "
    "or other non-course content, return unknown. "
    'Return JSON: {"outcome":"event"|"unknown",'
    '"semantic_event_draft":{"course_dept":string|null,"course_number":number|null,'
    '"course_suffix":string|null,"course_quarter":"WI"|"SP"|"SU"|"FA"|null,"course_year2":number|null,'
    '"raw_type":string|null,"event_name":string|null,"ordinal":number|null,'
    '"due_date":string|null,"due_time":string|null,"time_precision":"date_only"|"datetime"|null,'
    '"confidence":number,"evidence":string},'
    '"link_signals":{"keywords":["exam"|"midterm"|"final"],"exam_sequence":number|null,'
    '"location_text":string|null,"instructor_hint":string|null}}. '
    'Use outcome="event" only when the segment clearly describes a homework-like work item or test-like assessment. '
    'Use outcome="unknown" when the segment is nonrelevant, too vague, or not actionable.'
)

GMAIL_DIRECTIVE_SYSTEM_PROMPT = (
    "You are pass-2 extractor for one Gmail directive segment. "
    "Use only provided segment text and minimal message metadata. "
    "Classify only homework-like course work or test-like assessment directives. "
    "If there is no clear course context, or the segment is a competition, recruiting or career test, "
    "memo, digest, study note, solutions post, grade notification, graded or regrade notice, "
    "score-release message, meeting notice, voting notice, annual meeting notice, corporate notice, "
    "or other non-course content, return unknown. "
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
    '"confidence":number,"evidence":string}. '
    'Use outcome="directive" only when the text clearly applies to homework-like work or test-like assessments. '
    'Use outcome="unknown" when it is nonrelevant or too vague. '
    "Mutation must set exactly one of move_weekday or set_due_date."
)


@dataclass
class ProbeRecord:
    kind: str
    sample_id: str
    label: str
    stage: str
    latency_ms: int | None
    input_tokens: int | None
    cached_input_tokens: int | None
    output_tokens: int | None
    reasoning_tokens: int | None
    total_tokens: int | None
    success: bool
    error: str | None


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe real-source LLM latency and token usage.")
    parser.add_argument("--vevents", type=int, default=20)
    parser.add_argument("--gmail", type=int, default=20)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--parallel", type=int, default=4)
    parser.add_argument("--gmail-scan-limit", type=int, default=1500)
    parser.add_argument("--gmail-pool-limit", type=int, default=250)
    args = parser.parse_args()

    started_at = datetime.now(timezone.utc)
    run_dir = OUTPUT_ROOT / f"llm-usage-probe-{started_at.strftime('%Y%m%d-%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.seed)
    vevent_samples = collect_calendar_samples(count=args.vevents, rng=rng) if args.vevents > 0 else []
    gmail_samples = (
        collect_gmail_samples(
            count=args.gmail,
            rng=rng,
            scan_limit=args.gmail_scan_limit,
            pool_limit=args.gmail_pool_limit,
        )
        if args.gmail > 0
        else []
    )

    print(f"Selected {len(vevent_samples)} VEVENT samples and {len(gmail_samples)} Gmail samples.", flush=True)

    all_records: list[ProbeRecord] = []
    vevent_records = run_parallel_probes(
        items=vevent_samples,
        worker_count=args.parallel,
        worker_fn=run_calendar_probe,
        progress_label="VEVENT",
        sink=all_records,
        run_dir=run_dir,
        seed=args.seed,
        vevent_sample_count=len(vevent_samples),
        gmail_sample_count=len(gmail_samples),
    )
    gmail_records = run_parallel_probes(
        items=gmail_samples,
        worker_count=args.parallel,
        worker_fn=run_gmail_probe,
        progress_label="Gmail",
        sink=all_records,
        run_dir=run_dir,
        seed=args.seed,
        vevent_sample_count=len(vevent_samples),
        gmail_sample_count=len(gmail_samples),
    )

    all_records = vevent_records + gmail_records
    write_outputs(
        run_dir=run_dir,
        records=all_records,
        seed=args.seed,
        vevent_sample_count=len(vevent_samples),
        gmail_sample_count=len(gmail_samples),
    )
    print(f"Wrote results to {run_dir}", flush=True)


def collect_calendar_samples(*, count: int, rng: random.Random) -> list[dict[str, Any]]:
    with _session() as db:
        source = db.get(InputSource, 1)
        if source is None:
            raise RuntimeError("calendar source id=1 not found")
        secrets = decode_source_secrets(source)
        url = secrets.get("url")
        if not isinstance(url, str) or not url:
            raise RuntimeError("calendar source is missing url")
        content = httpx.get(url, timeout=30).content
        calendar = Calendar.from_ical(content)
        term_window = parse_source_term_window(source, required=False)
        timezone_name = source_timezone_name(source)
        candidates: list[dict[str, Any]] = []
        index = 0
        for component in calendar.walk():
            if getattr(component, "name", "") != "VEVENT":
                continue
            source_facts = _extract_source_facts(component=component, source_id=source.id, index=index)
            index += 1
            dtstart = parse_iso_datetime(source_facts.get("source_dtstart_utc"))
            if term_window is not None and not term_window.contains_datetime(dtstart, timezone_name=timezone_name):
                continue
            candidates.append(source_facts)
        if len(candidates) < count:
            return candidates
        return rng.sample(candidates, count)


def collect_gmail_samples(
    *,
    count: int,
    rng: random.Random,
    scan_limit: int,
    pool_limit: int,
) -> list[dict[str, Any]]:
    with _session() as db:
        source = db.get(InputSource, 2)
        if source is None:
            raise RuntimeError("gmail source id=2 not found")
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
        candidates: list[dict[str, Any]] = []
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
            candidates.append(
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
            if len(candidates) >= pool_limit:
                break
        if len(candidates) < count:
            return candidates
        return rng.sample(candidates, count)


def run_parallel_probes(
    *,
    items: list[dict[str, Any]],
    worker_count: int,
    worker_fn,
    progress_label: str,
    sink: list[ProbeRecord],
    run_dir: Path,
    seed: int,
    vevent_sample_count: int,
    gmail_sample_count: int,
):
    results: list[ProbeRecord] = []
    if not items:
        return results
    max_workers = max(1, min(worker_count, len(items)))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(worker_fn, item, idx) for idx, item in enumerate(items, start=1)]
        completed = 0
        total = len(futures)
        for future in as_completed(futures):
            rows = future.result()
            results.extend(rows)
            sink.extend(rows)
            completed += 1
            write_outputs(
                run_dir=run_dir,
                records=sink,
                seed=seed,
                vevent_sample_count=vevent_sample_count,
                gmail_sample_count=gmail_sample_count,
            )
            print(f"[{progress_label}] completed {completed}/{total}", flush=True)
    return results


def run_calendar_probe(item: dict[str, Any], idx: int) -> list[ProbeRecord]:
    with _session() as db:
        relevance_request = LlmInvokeRequest(
            task_name="calendar_event_relevance_plan",
            system_prompt=CALENDAR_SYSTEM_PROMPT,
            user_payload={
                "source_id": 1,
                "provider": "ics",
                "source_kind": "calendar",
                "source_facts": {
                    "source_title": item.get("source_title"),
                    "source_summary": item.get("source_summary"),
                    "location": item.get("location"),
                    "organizer": item.get("organizer"),
                    "source_dtstart_utc": item.get("source_dtstart_utc"),
                    "source_dtend_utc": item.get("source_dtend_utc"),
                },
            },
            output_schema_name="CalendarRelevanceResponse",
            output_schema_json=CalendarRelevanceResponse.model_json_schema(),
            source_id=1,
            source_provider="ics",
            request_id=f"usage-cal-rel-{idx}",
        )
        try:
            relevance_result = invoke_llm_json(db, invoke_request=relevance_request)
            records = [
                _record_from_result(
                    kind="vevent",
                    stage="calendar_event_relevance_plan",
                    sample_id=item["external_event_id"],
                    label=str(item.get("source_title") or ""),
                    result=relevance_result,
                )
            ]
            parsed_relevance = CalendarRelevanceResponse.model_validate(relevance_result.json_object)
            if parsed_relevance.outcome == "unknown":
                return records
            semantic_request = LlmInvokeRequest(
                task_name="calendar_event_semantic_extract",
                system_prompt=CALENDAR_SEMANTIC_SYSTEM_PROMPT,
                user_payload={
                    "source_id": 1,
                    "provider": "ics",
                    "source_kind": "calendar",
                    "source_facts": {
                        "source_title": item.get("source_title"),
                        "source_summary": item.get("source_summary"),
                        "location": item.get("location"),
                        "organizer": item.get("organizer"),
                        "source_dtstart_utc": item.get("source_dtstart_utc"),
                        "source_dtend_utc": item.get("source_dtend_utc"),
                    },
                },
                output_schema_name="CalendarSemanticEventClassification",
                output_schema_json=CalendarSemanticEventClassification.model_json_schema(),
                source_id=1,
                source_provider="ics",
                request_id=f"usage-cal-sem-{idx}",
            )
            semantic_result = invoke_llm_json(db, invoke_request=semantic_request)
            records.append(
                _record_from_result(
                    kind="vevent",
                    stage="calendar_event_semantic_extract",
                    sample_id=item["external_event_id"],
                    label=str(item.get("source_title") or ""),
                    result=semantic_result,
                )
            )
            return records
        except Exception as exc:  # noqa: BLE001
            return [
                _record_from_error(
                    kind="vevent",
                    stage="calendar_event_relevance_plan",
                    sample_id=item["external_event_id"],
                    label=str(item.get("source_title") or ""),
                    error=exc,
                )
            ]


def run_gmail_probe(item: dict[str, Any], idx: int) -> list[ProbeRecord]:
    records: list[ProbeRecord] = []
    with _session() as db:
        planner_request = LlmInvokeRequest(
            task_name="gmail_message_segment_plan",
            system_prompt=GMAIL_PLANNER_SYSTEM_PROMPT,
            user_payload={
                "source_id": 2,
                "provider": "gmail",
                "source_kind": "email",
                "message": item,
            },
            output_schema_name="GmailPlannerResponse",
            output_schema_json=GmailPlannerResponse.model_json_schema(),
            source_id=2,
            source_provider="gmail",
            request_id=f"usage-gmail-plan-{idx}",
        )
        try:
            planner_result = invoke_llm_json(db, invoke_request=planner_request)
            records.append(
                _record_from_result(
                    kind="gmail",
                    stage="gmail_message_segment_plan",
                    sample_id=item["message_id"],
                    label=str(item.get("subject") or ""),
                    result=planner_result,
                )
            )
            planner_json = planner_result.json_object
        except Exception as exc:  # noqa: BLE001
            records.append(
                _record_from_error(
                    kind="gmail",
                    stage="gmail_message_segment_plan",
                    sample_id=item["message_id"],
                    label=str(item.get("subject") or ""),
                    error=exc,
                )
            )
            return records

        segment, stage_name, stage_prompt, stage_schema_name, stage_schema_json = _pick_gmail_stage(planner_json, item)
        if segment is None:
            return records

        extract_request = LlmInvokeRequest(
            task_name=stage_name,
            system_prompt=stage_prompt,
            user_payload={
                "source_id": 2,
                "provider": "gmail",
                "source_kind": "email",
                "message_meta": {
                    "message_id": item.get("message_id"),
                    "subject": item.get("subject"),
                    "from_header": item.get("from_header"),
                    "thread_id": item.get("thread_id"),
                    "internal_date": item.get("internal_date"),
                },
                "segment": segment,
            },
            output_schema_name=stage_schema_name,
            output_schema_json=stage_schema_json,
            source_id=2,
            source_provider="gmail",
            request_id=f"usage-gmail-stage2-{idx}",
        )
        try:
            stage2_result = invoke_llm_json(db, invoke_request=extract_request)
            records.append(
                _record_from_result(
                    kind="gmail",
                    stage=stage_name,
                    sample_id=item["message_id"],
                    label=str(item.get("subject") or ""),
                    result=stage2_result,
                )
            )
        except Exception as exc:  # noqa: BLE001
            records.append(
                _record_from_error(
                    kind="gmail",
                    stage=stage_name,
                    sample_id=item["message_id"],
                    label=str(item.get("subject") or ""),
                    error=exc,
                )
            )
    return records


def _pick_gmail_stage(
    planner_json: dict[str, Any],
    item: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None, str | None, str | None, dict[str, Any] | None]:
    for segment in planner_json.get("segment_array") or []:
        if not isinstance(segment, dict):
            continue
        hint = segment.get("segment_type_hint")
        if hint == "atomic":
            return (
                segment,
                "gmail_segment_atomic_extract",
                GMAIL_ATOMIC_SYSTEM_PROMPT,
                "GmailAtomicSegmentExtractionResponse",
                GmailAtomicSegmentExtractionResponse.model_json_schema(),
            )
        if hint == "directive":
            return (
                segment,
                "gmail_segment_directive_extract",
                GMAIL_DIRECTIVE_SYSTEM_PROMPT,
                "GmailDirectiveExtractionResponse",
                GmailDirectiveExtractionResponse.model_json_schema(),
            )
    fallback_segment = {
        "segment_index": 0,
        "anchor": item.get("subject"),
        "snippet": item.get("snippet"),
        "segment_type_hint": "atomic",
    }
    return (
        fallback_segment,
        "gmail_segment_atomic_extract",
        GMAIL_ATOMIC_SYSTEM_PROMPT,
        "GmailAtomicSegmentExtractionResponse",
        GmailAtomicSegmentExtractionResponse.model_json_schema(),
    )


def _record_from_result(*, kind: str, stage: str, sample_id: str, label: str, result) -> ProbeRecord:
    usage = result.raw_usage if isinstance(result.raw_usage, dict) else {}
    input_details = usage.get("input_tokens_details") if isinstance(usage.get("input_tokens_details"), dict) else {}
    output_details = usage.get("output_tokens_details") if isinstance(usage.get("output_tokens_details"), dict) else {}
    return ProbeRecord(
        kind=kind,
        sample_id=sample_id,
        label=label[:200],
        stage=stage,
        latency_ms=result.latency_ms,
        input_tokens=_int_or_none(usage.get("input_tokens")),
        cached_input_tokens=_int_or_none(input_details.get("cached_tokens")),
        output_tokens=_int_or_none(usage.get("output_tokens")),
        reasoning_tokens=_int_or_none(output_details.get("reasoning_tokens")),
        total_tokens=_int_or_none(usage.get("total_tokens")),
        success=True,
        error=None,
    )


def _record_from_error(*, kind: str, stage: str, sample_id: str, label: str, error: Exception) -> ProbeRecord:
    return ProbeRecord(
        kind=kind,
        sample_id=sample_id,
        label=label[:200],
        stage=stage,
        latency_ms=None,
        input_tokens=None,
        cached_input_tokens=None,
        output_tokens=None,
        reasoning_tokens=None,
        total_tokens=None,
        success=False,
        error=str(error)[:500],
    )


def write_outputs(
    *,
    run_dir: Path,
    records: list[ProbeRecord],
    seed: int,
    vevent_sample_count: int,
    gmail_sample_count: int,
) -> None:
    json_path = run_dir / "probe_records.json"
    md_path = run_dir / "summary.md"
    json_path.write_text(json.dumps([asdict(row) for row in records], ensure_ascii=False, indent=2), encoding="utf-8")

    vevent_rows = [row for row in records if row.kind == "vevent"]
    gmail_rows = [row for row in records if row.kind == "gmail"]
    lines = [
        f"# Real LLM Usage Probe",
        "",
        f"- Seed: `{seed}`",
        f"- VEVENT samples: `{vevent_sample_count}`",
        f"- Gmail samples: `{gmail_sample_count}`",
        "",
        "## VEVENT",
        _summary_block(vevent_rows),
        "",
        "## Gmail",
        _summary_block(gmail_rows),
        "",
        f"Raw records: `{json_path}`",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")


def _summary_block(rows: list[ProbeRecord]) -> str:
    if not rows:
        return "- No rows"
    success_rows = [row for row in rows if row.success]
    fail_rows = [row for row in rows if not row.success]
    latencies = [row.latency_ms for row in success_rows if row.latency_ms is not None]
    inputs = [row.input_tokens for row in success_rows if row.input_tokens is not None]
    cached_inputs = [row.cached_input_tokens for row in success_rows if row.cached_input_tokens is not None]
    outputs = [row.output_tokens for row in success_rows if row.output_tokens is not None]
    totals = [row.total_tokens for row in success_rows if row.total_tokens is not None]
    reasoning = [row.reasoning_tokens for row in success_rows if row.reasoning_tokens is not None]
    return "\n".join(
        [
            f"- Success rows: `{len(success_rows)}`",
            f"- Failed rows: `{len(fail_rows)}`",
            f"- Avg latency ms: `{_avg(latencies)}`",
            f"- Avg input tokens: `{_avg(inputs)}`",
            f"- Avg cached input tokens: `{_avg(cached_inputs)}`",
            f"- Avg output tokens: `{_avg(outputs)}`",
            f"- Avg reasoning tokens: `{_avg(reasoning)}`",
            f"- Avg total tokens: `{_avg(totals)}`",
        ]
    )


def _avg(values: list[int]) -> str:
    if not values:
        return "-"
    return str(round(sum(values) / len(values), 2))


def _int_or_none(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _session():
    return get_session_factory()()


if __name__ == "__main__":
    main()
