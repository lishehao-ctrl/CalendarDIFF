#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jsonschema import Draft202012Validator

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA_PATH = ROOT_DIR / "tools" / "labeling" / "schema" / "email_label.json"

HIGH_PRIORITY_TYPES = {"deadline", "exam", "schedule_change", "action_required"}
ARCHIVE_TYPES = {"grade", "announcement", "other", None}
UNCERTAINTY_RE = re.compile(r"(?:unsure|unclear|maybe|needs review)", re.IGNORECASE)

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
TOKEN_RE = re.compile(r"\b(?:sk|rk|tok|token|apikey|api_key)[-_A-Za-z0-9]{8,}\b", re.IGNORECASE)
URL_RE = re.compile(r"https?://[^\s)>\"']+")


@dataclass(frozen=True)
class RouteConfig:
    input_path: Path
    outdir: Path
    schema_path: Path
    review_threshold: float
    max_action_items: int
    timezone: str


@dataclass(frozen=True)
class ParsedRow:
    line_number: int
    payload: dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deterministic router/filter for labeled email JSONL.")
    parser.add_argument("--input", required=True, help="Input labeled JSONL path.")
    parser.add_argument("--outdir", required=True, help="Output route directory (drop/archive/notify/review/stats).")
    parser.add_argument(
        "--review-threshold",
        type=float,
        default=0.75,
        help="Review threshold for low confidence KEEP rows (default: 0.75).",
    )
    parser.add_argument(
        "--max-action-items",
        type=int,
        default=5,
        help="Warn when action_items count exceeds this value (stats-only; default: 5).",
    )
    parser.add_argument(
        "--timezone",
        default="America/Los_Angeles",
        help="IANA timezone identifier for report metadata (default: America/Los_Angeles).",
    )
    parser.add_argument(
        "--schema",
        default=str(DEFAULT_SCHEMA_PATH),
        help=f"Schema path for labeled rows (default: {DEFAULT_SCHEMA_PATH}).",
    )
    return parser.parse_args()


def build_config(args: argparse.Namespace) -> RouteConfig:
    input_path = Path(args.input)
    if not input_path.is_file():
        raise RuntimeError(f"Input JSONL not found: {input_path}")

    review_threshold = float(args.review_threshold)
    if review_threshold < 0.0 or review_threshold > 1.0:
        raise RuntimeError(f"--review-threshold must be in [0,1], got {review_threshold}")

    max_action_items = int(args.max_action_items)
    if max_action_items <= 0:
        raise RuntimeError(f"--max-action-items must be > 0, got {max_action_items}")

    timezone = str(args.timezone).strip()
    if not timezone:
        raise RuntimeError("--timezone cannot be empty")
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError(f"Invalid IANA timezone: {timezone}") from exc

    schema_path = Path(args.schema)
    if not schema_path.is_file():
        raise RuntimeError(f"Schema file not found: {schema_path}")

    return RouteConfig(
        input_path=input_path,
        outdir=Path(args.outdir),
        schema_path=schema_path,
        review_threshold=review_threshold,
        max_action_items=max_action_items,
        timezone=timezone,
    )


def sanitize_error_message(raw: str) -> str:
    text = TOKEN_RE.sub("<REDACTED_TOKEN>", raw)
    text = EMAIL_RE.sub("<REDACTED_EMAIL>", text)
    text = URL_RE.sub("<REDACTED_URL>", text)
    return text[:800]


def is_blank_text(value: Any) -> bool:
    return not isinstance(value, str) or value.strip() == ""


def parse_iso8601(value: str) -> bool:
    candidate = value.strip()
    if not candidate:
        return False
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        datetime.fromisoformat(candidate)
    except ValueError:
        return False
    return True


def iter_jsonl_lines(path: Path) -> Iterator[tuple[int, str]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            yield line_number, line


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_stats(path: Path, stats: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_error_record(
    *,
    line_number: int,
    email_id: str,
    error_type: str,
    message: str,
) -> dict[str, Any]:
    return {
        "line_number": line_number,
        "email_id": email_id,
        "error_type": error_type,
        "message_sanitized": sanitize_error_message(message),
    }


def validate_label_row(payload: dict[str, Any], validator: Draft202012Validator) -> list[str]:
    return sorted({err.message for err in validator.iter_errors(payload)})


def load_valid_rows(
    *,
    input_path: Path,
    validator: Draft202012Validator,
) -> tuple[list[ParsedRow], list[dict[str, Any]], int]:
    valid_rows: list[ParsedRow] = []
    errors: list[dict[str, Any]] = []
    total_rows = 0

    for line_number, line in iter_jsonl_lines(input_path):
        total_rows += 1
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(
                build_error_record(
                    line_number=line_number,
                    email_id="unknown",
                    error_type="json_parse_error",
                    message=str(exc),
                )
            )
            continue

        if not isinstance(payload, dict):
            errors.append(
                build_error_record(
                    line_number=line_number,
                    email_id="unknown",
                    error_type="json_parse_error",
                    message="line is not a JSON object",
                )
            )
            continue

        schema_issues = validate_label_row(payload, validator)
        if schema_issues:
            raw_email_id = payload.get("email_id")
            email_id = raw_email_id.strip() if isinstance(raw_email_id, str) and raw_email_id.strip() else "unknown"
            errors.append(
                build_error_record(
                    line_number=line_number,
                    email_id=email_id,
                    error_type="schema_validation_error",
                    message="; ".join(schema_issues[:8]),
                )
            )
            continue

        valid_rows.append(ParsedRow(line_number=line_number, payload=payload))

    return valid_rows, errors, total_rows


def dedupe_by_email_id(rows: list[ParsedRow]) -> tuple[list[ParsedRow], int]:
    deduped: dict[str, ParsedRow] = {}
    duplicate_count = 0

    for row in rows:
        email_id = str(row.payload.get("email_id"))
        existing = deduped.get(email_id)
        if existing is None:
            deduped[email_id] = row
            continue

        duplicate_count += 1
        existing_conf = float(existing.payload.get("confidence", 0.0))
        incoming_conf = float(row.payload.get("confidence", 0.0))
        if incoming_conf > existing_conf:
            deduped[email_id] = row
        elif incoming_conf == existing_conf and row.line_number > existing.line_number:
            deduped[email_id] = row

    ordered = sorted(deduped.values(), key=lambda item: item.line_number)
    return ordered, duplicate_count


def is_review_row(payload: dict[str, Any], review_threshold: float) -> bool:
    label = payload.get("label")
    if label != "KEEP":
        return False

    confidence = float(payload.get("confidence", 0.0))
    event_type = payload.get("event_type")
    action_items = payload.get("action_items") if isinstance(payload.get("action_items"), list) else []
    raw_extract = payload.get("raw_extract") if isinstance(payload.get("raw_extract"), dict) else {}
    notes = payload.get("notes")

    if confidence < review_threshold:
        return True

    deadline_text = raw_extract.get("deadline_text")
    time_text = raw_extract.get("time_text")
    location_text = raw_extract.get("location_text")

    if event_type in HIGH_PRIORITY_TYPES and len(action_items) == 0:
        if is_blank_text(deadline_text) and is_blank_text(time_text) and is_blank_text(location_text):
            return True

    for item in action_items:
        if not isinstance(item, dict):
            continue
        due_iso = item.get("due_iso")
        if isinstance(due_iso, str) and due_iso.strip() and not parse_iso8601(due_iso):
            return True

    if event_type == "schedule_change":
        where_all_blank = True
        for item in action_items:
            if not isinstance(item, dict):
                continue
            if not is_blank_text(item.get("where")):
                where_all_blank = False
                break
        if where_all_blank and is_blank_text(location_text):
            return True

    if event_type in {"deadline", "assignment", "exam"}:
        due_all_blank = True
        for item in action_items:
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("due_iso"), str) and item.get("due_iso", "").strip():
                due_all_blank = False
                break
        if due_all_blank and is_blank_text(deadline_text) and is_blank_text(time_text):
            return True

    if isinstance(notes, str) and notes.strip() and UNCERTAINTY_RE.search(notes):
        return True

    return False


def evaluate_notify_route(payload: dict[str, Any]) -> tuple[bool, bool]:
    event_type = payload.get("event_type")
    action_items = payload.get("action_items") if isinstance(payload.get("action_items"), list) else []
    raw_extract = payload.get("raw_extract") if isinstance(payload.get("raw_extract"), dict) else {}

    should_notify = False
    downgraded_from_notify_intent = False
    if event_type in HIGH_PRIORITY_TYPES:
        if has_notify_strong_signal(action_items, raw_extract):
            should_notify = True
        else:
            downgraded_from_notify_intent = True
    elif event_type == "assignment":
        if has_parseable_due_iso(action_items) and has_notify_strong_signal(action_items, raw_extract):
            should_notify = True
        else:
            downgraded_from_notify_intent = True
    return should_notify, downgraded_from_notify_intent


def derive_primary_route(payload: dict[str, Any], review_threshold: float) -> str:
    label = payload.get("label")
    if label == "DROP":
        return "drop"

    should_notify, downgraded_from_notify_intent = evaluate_notify_route(payload)
    review_hit = is_review_row(payload, review_threshold)
    if not review_hit and downgraded_from_notify_intent and float(payload.get("confidence", 0.0)) < review_threshold:
        review_hit = True
    if review_hit:
        return "review"
    if should_notify:
        return "notify"
    return "archive"


def has_parseable_due_iso(action_items: list[Any]) -> bool:
    for item in action_items:
        if not isinstance(item, dict):
            continue
        due_iso = item.get("due_iso")
        if isinstance(due_iso, str) and parse_iso8601(due_iso):
            return True
    return False


def has_non_empty_extract(raw_extract: dict[str, Any]) -> bool:
    for key in ("deadline_text", "time_text", "location_text"):
        if not is_blank_text(raw_extract.get(key)):
            return True
    return False


def has_notify_strong_signal(action_items: list[Any], raw_extract: dict[str, Any]) -> bool:
    return has_parseable_due_iso(action_items) or has_non_empty_extract(raw_extract)


def _percent(part: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round((part * 100.0) / total, 2)


def run_router(config: RouteConfig) -> dict[str, Any]:
    config.outdir.mkdir(parents=True, exist_ok=True)
    schema = json.loads(config.schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    valid_rows, route_errors, total_input_rows = load_valid_rows(input_path=config.input_path, validator=validator)
    deduped_rows, duplicate_count = dedupe_by_email_id(valid_rows)

    drop_rows: list[dict[str, Any]] = []
    archive_rows: list[dict[str, Any]] = []
    notify_rows: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []

    keep_count = 0
    drop_count = 0
    keep_with_null_event_type = 0
    notify_empty_action_items = 0
    review_keep_count = 0
    rows_exceeding_max_action_items = 0

    keep_event_distribution: Counter[str] = Counter()
    course_hint_counter: Counter[str] = Counter()

    for row in deduped_rows:
        payload = row.payload
        label = payload.get("label")
        event_type = payload.get("event_type")
        action_items = payload.get("action_items") if isinstance(payload.get("action_items"), list) else []
        raw_extract = payload.get("raw_extract") if isinstance(payload.get("raw_extract"), dict) else {}

        if len(action_items) > config.max_action_items:
            rows_exceeding_max_action_items += 1

        if label == "DROP":
            drop_count += 1
            drop_rows.append(payload)
            continue

        keep_count += 1
        event_bucket = event_type if isinstance(event_type, str) else "null"
        keep_event_distribution[event_bucket] += 1
        if event_type is None:
            keep_with_null_event_type += 1

        for hint in payload.get("course_hints", []):
            if isinstance(hint, str) and hint.strip():
                course_hint_counter[hint.strip()] += 1

        should_route_notify, downgraded_from_notify_intent = evaluate_notify_route(payload)

        if should_route_notify:
            notify_rows.append(payload)
            if len(action_items) == 0:
                notify_empty_action_items += 1
        else:
            archive_rows.append(payload)

        review_hit = is_review_row(payload, config.review_threshold)
        if not review_hit and downgraded_from_notify_intent and float(payload.get("confidence", 0.0)) < config.review_threshold:
            review_hit = True
        if review_hit:
            review_rows.append(payload)
            review_keep_count += 1

    warnings: list[str] = []
    total_rows = len(deduped_rows)
    keep_ratio = (keep_count / total_rows) if total_rows else 0.0
    review_keep_ratio = (review_keep_count / keep_count) if keep_count else 0.0
    keep_null_event_ratio = (keep_with_null_event_type / keep_count) if keep_count else 0.0

    if total_rows and (keep_ratio < 0.05 or keep_ratio > 0.95):
        warnings.append(f"keep_ratio={keep_ratio:.4f} is extreme.")
    if keep_count and review_keep_ratio > 0.30:
        warnings.append(f"review_ratio_keep={review_keep_ratio:.4f} exceeds 0.30.")
    if keep_count and keep_null_event_ratio > 0.30:
        warnings.append(f"keep_null_event_type_ratio={keep_null_event_ratio:.4f} exceeds 0.30.")
    if duplicate_count > 0:
        warnings.append(f"duplicate_email_id_count={duplicate_count}; kept highest confidence per email_id.")
    if rows_exceeding_max_action_items > 0:
        warnings.append(
            f"rows_exceeding_max_action_items={rows_exceeding_max_action_items} "
            f"(threshold={config.max_action_items}); outputs are not mutated."
        )

    parse_error_count = sum(1 for err in route_errors if err.get("error_type") == "json_parse_error")
    schema_error_count = sum(1 for err in route_errors if err.get("error_type") == "schema_validation_error")
    if parse_error_count or schema_error_count:
        warnings.append(
            f"ingest_errors=parse:{parse_error_count}, schema:{schema_error_count}; check route_errors.jsonl."
        )

    top_course_hints = [
        {"course_hint": key, "count": value}
        for key, value in sorted(course_hint_counter.items(), key=lambda item: (-item[1], item[0]))[:20]
    ]

    stats = {
        "input_path": str(config.input_path),
        "outdir": str(config.outdir),
        "timezone": config.timezone,
        "review_threshold": config.review_threshold,
        "max_action_items": config.max_action_items,
        "total_input_rows": total_input_rows,
        "total_rows": total_rows,
        "keep_count": keep_count,
        "drop_count": drop_count,
        "route_counts": {
            "drop": len(drop_rows),
            "archive": len(archive_rows),
            "notify": len(notify_rows),
            "review": len(review_rows),
        },
        "event_type_distribution_keep": dict(keep_event_distribution),
        "keep_in_review_percent": _percent(review_keep_count, keep_count),
        "notify_empty_action_items_percent": _percent(notify_empty_action_items, len(notify_rows)),
        "top_course_hints": top_course_hints,
        "duplicate_email_id_count": duplicate_count,
        "parse_error_count": parse_error_count,
        "schema_error_count": schema_error_count,
        "rows_exceeding_max_action_items": rows_exceeding_max_action_items,
        "warnings": warnings,
    }

    write_jsonl(config.outdir / "drop.jsonl", drop_rows)
    write_jsonl(config.outdir / "archive.jsonl", archive_rows)
    write_jsonl(config.outdir / "notify.jsonl", notify_rows)
    write_jsonl(config.outdir / "review.jsonl", review_rows)
    write_jsonl(config.outdir / "route_errors.jsonl", route_errors)
    write_stats(config.outdir / "stats.json", stats)
    return stats


def main() -> int:
    try:
        args = parse_args()
        config = build_config(args)
        stats = run_router(config)
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"error": sanitize_error_message(str(exc))}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
