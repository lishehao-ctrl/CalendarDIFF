from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from app.modules.ingestion.eval.contracts import IcsEvalPair, IcsEvalResult
from app.modules.ingestion.llm_parsers import LlmParseError, ParserContext, parse_calendar_content


def run_ics_eval(*, pairs: list[IcsEvalPair], max_workers: int = 4) -> list[IcsEvalResult]:
    if not pairs:
        return []

    workers = max(int(max_workers), 1)
    indexed_results: dict[int, IcsEvalResult] = {}

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(_run_single_pair, index=index, pair=pair): index
            for index, pair in enumerate(pairs)
        }
        for future in as_completed(future_map):
            index = future_map[future]
            indexed_results[index] = future.result()

    return [indexed_results[index] for index in range(len(pairs))]


def infer_ics_diff(
    *,
    before_events: dict[str, dict[str, str]],
    after_events: dict[str, dict[str, str]],
) -> tuple[str, list[str]]:
    before_uids = set(before_events.keys())
    after_uids = set(after_events.keys())

    due_changed_uids: list[str] = []
    for uid in sorted(before_uids & after_uids):
        before = before_events[uid]
        after = after_events[uid]
        if before.get("start_at") != after.get("start_at") or before.get("end_at") != after.get("end_at"):
            due_changed_uids.append(uid)

    if due_changed_uids:
        return "DUE_CHANGED", due_changed_uids

    created_uids = sorted(after_uids - before_uids)
    if created_uids:
        return "CREATED", created_uids

    removed_uids = sorted(before_uids - after_uids)
    if removed_uids:
        return "REMOVED_CANDIDATE", removed_uids

    return "NO_CHANGE", []


def _run_single_pair(*, index: int, pair: IcsEvalPair) -> IcsEvalResult:
    context_before = ParserContext(
        source_id=20_000 + index,
        provider="ics",
        source_kind="calendar",
        request_id=f"ics-before-{pair.pair_id}",
    )
    context_after = ParserContext(
        source_id=30_000 + index,
        provider="ics",
        source_kind="calendar",
        request_id=f"ics-after-{pair.pair_id}",
    )

    try:
        before_output = parse_calendar_content(
            db=None,  # type: ignore[arg-type]
            content=pair.before_content,
            context=context_before,
        )
        after_output = parse_calendar_content(
            db=None,  # type: ignore[arg-type]
            content=pair.after_content,
            context=context_after,
        )
    except LlmParseError as exc:
        return IcsEvalResult(
            pair_id=pair.pair_id,
            expected_diff_class=pair.expected_diff_class,
            predicted_diff_class=None,
            expected_changed_uids=list(pair.expected_changed_uids),
            predicted_changed_uids=[],
            structured_success=False,
            ambiguous=pair.ambiguous,
            error_code=exc.code,
            error_message=str(exc),
        )

    before_events = _records_to_event_map(records=before_output.records)
    after_events = _records_to_event_map(records=after_output.records)
    predicted_class, predicted_changed_uids = infer_ics_diff(
        before_events=before_events,
        after_events=after_events,
    )

    return IcsEvalResult(
        pair_id=pair.pair_id,
        expected_diff_class=pair.expected_diff_class,
        predicted_diff_class=predicted_class,
        expected_changed_uids=list(pair.expected_changed_uids),
        predicted_changed_uids=predicted_changed_uids,
        structured_success=True,
        ambiguous=pair.ambiguous,
        error_code=None,
        error_message=None,
    )


def _records_to_event_map(*, records: list[dict]) -> dict[str, dict[str, str]]:
    mapped: dict[str, dict[str, str]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("record_type") != "calendar.event.extracted":
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        uid = payload.get("uid")
        if not isinstance(uid, str) or not uid.strip():
            continue
        clean_uid = uid.strip()
        mapped[clean_uid] = {
            "start_at": _normalize_datetime(payload.get("start_at")),
            "end_at": _normalize_datetime(payload.get("end_at")),
            "title": _normalize_text(payload.get("title")),
            "course_label": _normalize_text(payload.get("course_label")),
        }
    return mapped


def _normalize_datetime(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    raw = value.strip()
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return raw
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _normalize_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""
