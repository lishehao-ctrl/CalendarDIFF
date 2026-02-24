#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from jsonschema import Draft202012Validator

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA_PATH = ROOT_DIR / "tools" / "labeling" / "schema" / "email_label.json"

REQUIRED_KEYS = {
    "email_id",
    "label",
    "confidence",
    "reasons",
    "course_hints",
    "event_type",
    "action_items",
    "raw_extract",
    "notes",
}
EVENT_TYPES = {
    "deadline",
    "exam",
    "schedule_change",
    "assignment",
    "grade",
    "action_required",
    "announcement",
    "other",
}
RESCUE_SCHEDULE_HINT_RE = re.compile(
    r"(?:schedule|reschedul|moved|postpon|cancel|class|section|lecture|location|room|zoom|time change)",
    re.IGNORECASE,
)

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
TOKEN_RE = re.compile(r"\b(?:sk|rk|tok|token|apikey|api_key)[-_A-Za-z0-9]{8,}\b", re.IGNORECASE)
URL_RE = re.compile(r"https?://[^\s)>\"']+")

LABEL_MAP = {
    "keep": "KEEP",
    "drop": "DROP",
    "true": "KEEP",
    "false": "DROP",
    "1": "KEEP",
    "0": "DROP",
    "yes": "KEEP",
    "no": "DROP",
}
EVENT_MAP = {
    "schedule": "schedule_change",
    "schedulechange": "schedule_change",
    "schedule_change": "schedule_change",
    "reschedule": "schedule_change",
    "deadline": "deadline",
    "due": "deadline",
    "due_date": "deadline",
    "ddl": "deadline",
    "quiz": "exam",
    "midterm": "exam",
    "final": "exam",
    "grade_update": "grade",
    "grades": "grade",
    "action": "action_required",
    "required": "action_required",
    "action_required": "action_required",
    "announcement": "announcement",
    "logistics": "announcement",
}
LEGACY_CATEGORY_TO_EVENT = {
    "deadline": "deadline",
    "exam": "exam",
    "schedule_change": "schedule_change",
    "required_action": "action_required",
    "grade_update": "grade",
    "course_logistics": "announcement",
    "irrelevant": None,
}


@dataclass(frozen=True)
class NormalizeConfig:
    input_path: Path
    output_path: Path
    errors_path: Path
    dedupe: bool
    max_action_items: int
    rescue_llm: bool
    rescue_out_path: Path
    timezone: str
    schema_path: Path


@dataclass(frozen=True)
class RescueConfig:
    enabled: bool
    base_url: str | None
    api_key: str | None
    model: str
    timeout_seconds: float
    batch_size: int
    concurrency: int
    path: str


@dataclass
class NormalizedRow:
    line_number: int
    payload: dict[str, Any]
    source_row: dict[str, Any]
    rescue_candidate: bool
    rescue_reason: str | None
    unmapped_event_type: bool


@dataclass(frozen=True)
class RescueDecision:
    email_id: str
    label: str
    confidence: float
    event_type: str | None
    course_hints: list[str]
    notes: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize and optionally rescue labeled JSONL outputs.")
    parser.add_argument("--input", required=True, help="Input labeled JSONL path.")
    parser.add_argument("--output", required=True, help="Output normalized JSONL path.")
    parser.add_argument("--errors", required=True, help="Output normalize errors JSONL path.")
    parser.add_argument("--dedupe", default="true", help="Whether to dedupe by email_id: true|false (default: true).")
    parser.add_argument("--max-action-items", type=int, default=5, help="Max action_items kept in normalized output.")
    parser.add_argument("--rescue-llm", default="false", help="Enable optional LLM rescue: true|false.")
    parser.add_argument("--rescue-out", required=True, help="Output JSONL path for applied rescue decisions.")
    parser.add_argument("--timezone", default="America/Los_Angeles", help="IANA timezone for metadata validation.")
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA_PATH), help="Schema path for final strict validation.")
    return parser.parse_args()


def parse_bool_text(raw: str, *, arg_name: str) -> bool:
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    raise RuntimeError(f"{arg_name} must be true|false, got {raw!r}")


def sanitize_log_text(raw: str) -> str:
    text = TOKEN_RE.sub("<REDACTED_TOKEN>", raw)
    text = EMAIL_RE.sub("<REDACTED_EMAIL>", text)
    text = URL_RE.sub("<REDACTED_URL>", text)
    return text[:1200]


def build_config(args: argparse.Namespace) -> NormalizeConfig:
    input_path = Path(args.input)
    if not input_path.is_file():
        raise RuntimeError(f"Input JSONL not found: {input_path}")

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

    return NormalizeConfig(
        input_path=input_path,
        output_path=Path(args.output),
        errors_path=Path(args.errors),
        dedupe=parse_bool_text(args.dedupe, arg_name="--dedupe"),
        max_action_items=max_action_items,
        rescue_llm=parse_bool_text(args.rescue_llm, arg_name="--rescue-llm"),
        rescue_out_path=Path(args.rescue_out),
        timezone=timezone,
        schema_path=schema_path,
    )


def load_rescue_config(*, enabled_from_cli: bool) -> RescueConfig:
    env_enabled = parse_bool_text(os.getenv("RESCUE_LLM_ENABLED", "false"), arg_name="RESCUE_LLM_ENABLED")
    enabled = enabled_from_cli or env_enabled
    base_url = (os.getenv("RESCUE_LLM_BASE_URL") or "").strip() or None
    api_key = (os.getenv("RESCUE_LLM_API_KEY") or "").strip() or None
    model = (os.getenv("RESCUE_LLM_MODEL") or "gpt-5.3-codex").strip() or "gpt-5.3-codex"
    timeout_seconds = float(os.getenv("RESCUE_LLM_TIMEOUT_SECONDS", "30"))
    batch_size = int(os.getenv("RESCUE_LLM_BATCH_SIZE", "25"))
    concurrency = int(os.getenv("RESCUE_LLM_CONCURRENCY", "5"))
    path = (os.getenv("RESCUE_LLM_PATH") or "/label").strip() or "/label"
    if not path.startswith("/"):
        path = "/" + path

    if enabled and not base_url:
        raise RuntimeError("RESCUE_LLM_BASE_URL is required when rescue is enabled.")
    if enabled and batch_size <= 0:
        raise RuntimeError("RESCUE_LLM_BATCH_SIZE must be > 0.")
    if enabled and concurrency <= 0:
        raise RuntimeError("RESCUE_LLM_CONCURRENCY must be > 0.")
    if enabled and timeout_seconds <= 0:
        raise RuntimeError("RESCUE_LLM_TIMEOUT_SECONDS must be > 0.")

    return RescueConfig(
        enabled=enabled,
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout_seconds=timeout_seconds,
        batch_size=batch_size,
        concurrency=concurrency,
        path=path,
    )


def iter_jsonl_lines(path: Path) -> Iterator[tuple[int, str]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            yield line_number, line


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def append_error(
    bucket: list[dict[str, Any]],
    *,
    line_number: int,
    email_id: str,
    error_type: str,
    message: str,
    original_keys: list[str] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "email_id": email_id if email_id else "unknown",
        "error_type": error_type,
        "message_sanitized": sanitize_log_text(message),
        "line_number": line_number,
    }
    if original_keys:
        payload["original_keys"] = original_keys[:30]
    bucket.append(payload)


def clamp_confidence(value: Any) -> float:
    if isinstance(value, bool):
        numeric = 1.0 if value else 0.0
    elif isinstance(value, (int, float)):
        numeric = float(value)
    elif isinstance(value, str):
        try:
            numeric = float(value.strip())
        except ValueError:
            numeric = 0.0
    else:
        numeric = 0.0
    return min(1.0, max(0.0, numeric))


def coerce_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed or None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return str(value)
    return None


def normalize_string_list(value: Any, *, max_items: int | None = None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        return []

    out: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = coerce_text(item)
        if text is None:
            continue
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
        if max_items is not None and len(out) >= max_items:
            break
    return out


def normalize_label(value: Any, *, fallback_keep: Any = None) -> str:
    if isinstance(value, str):
        mapped = LABEL_MAP.get(value.strip().lower())
        if mapped:
            return mapped
    elif isinstance(value, bool):
        return "KEEP" if value else "DROP"
    elif isinstance(value, (int, float)):
        if float(value) == 1.0:
            return "KEEP"
        if float(value) == 0.0:
            return "DROP"

    if fallback_keep is not None:
        return normalize_label(fallback_keep)
    return "DROP"


def normalize_event_type(value: Any) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None, False
        lower = raw.lower()
        if lower in EVENT_TYPES:
            return lower, False
        mapped = EVENT_MAP.get(lower)
        if mapped:
            return mapped, False
        if lower == "null":
            return None, False
        return None, True
    return None, True


def parse_iso8601(value: str | None) -> bool:
    if value is None:
        return False
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


def normalize_action_items(
    value: Any,
    *,
    max_action_items: int,
    line_number: int,
    email_id: str,
    error_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(value, list):
        return [], 0

    items: list[dict[str, Any]] = []
    for raw_item in value:
        if not isinstance(raw_item, dict):
            continue
        action = coerce_text(raw_item.get("action"))
        due_iso = coerce_text(raw_item.get("due_iso"))
        where = coerce_text(raw_item.get("where"))

        if action is None and (due_iso is not None or where is not None):
            action = "unknown action"
        if action is None:
            continue

        items.append(
            {
                "action": action,
                "due_iso": due_iso,
                "where": where,
            }
        )

    truncated = 0
    if len(items) > max_action_items:
        truncated = len(items) - max_action_items
        items = items[:max_action_items]
        append_error(
            error_rows,
            line_number=line_number,
            email_id=email_id,
            error_type="coercion_warning",
            message=f"action_items truncated to {max_action_items}",
        )
    return items, truncated


def normalize_raw_extract(value: Any) -> dict[str, str | None]:
    source = value if isinstance(value, dict) else {}
    return {
        "deadline_text": coerce_text(source.get("deadline_text")),
        "time_text": coerce_text(source.get("time_text")),
        "location_text": coerce_text(source.get("location_text")),
    }


def normalize_legacy_candidates(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            out.append(item)
    return out


def maybe_legacy_row(row: dict[str, Any]) -> bool:
    return "keep" in row or "category" in row or "candidates" in row


def build_legacy_action_items(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    action_items: list[dict[str, Any]] = []
    for candidate in candidates:
        action = coerce_text(candidate.get("item_title_hint")) or coerce_text(candidate.get("change_type")) or "legacy change"
        due_iso_candidate = coerce_text(candidate.get("new_time"))
        if due_iso_candidate is None:
            due_iso_candidate = coerce_text(candidate.get("old_time"))
        due_iso = due_iso_candidate if parse_iso8601(due_iso_candidate) else None
        action_items.append({"action": action, "due_iso": due_iso, "where": None})
    return action_items


def build_legacy_raw_extract(candidates: list[dict[str, Any]]) -> dict[str, str | None]:
    deadline_text: str | None = None
    time_text: str | None = None

    for candidate in candidates:
        evidence = candidate.get("evidence_spans")
        if deadline_text is None and isinstance(evidence, list):
            for item in evidence:
                text = coerce_text(item)
                if text:
                    deadline_text = text
                    break
        for key in ("new_time", "old_time"):
            if time_text is None:
                candidate_time = coerce_text(candidate.get(key))
                if candidate_time:
                    time_text = candidate_time
    return {
        "deadline_text": deadline_text,
        "time_text": time_text,
        "location_text": None,
    }


def merge_course_hints(current: list[str], extra: list[str]) -> list[str]:
    merged = list(current)
    seen = set(current)
    for hint in extra:
        if hint not in seen:
            merged.append(hint)
            seen.add(hint)
    return merged


def normalize_row(
    *,
    row: dict[str, Any],
    line_number: int,
    max_action_items: int,
    error_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], bool, str | None, bool]:
    email_id = coerce_text(row.get("email_id")) or f"unknown-{line_number}"
    legacy = maybe_legacy_row(row) and "label" not in row
    unmapped_event_type = False

    if legacy:
        append_error(
            error_rows,
            line_number=line_number,
            email_id=email_id,
            error_type="coercion_warning",
            message="legacy keep/category/candidates mapped to strict output contract",
            original_keys=sorted([str(k) for k in row.keys()]),
        )

    label = normalize_label(row.get("label"), fallback_keep=row.get("keep"))
    confidence = clamp_confidence(row.get("confidence"))
    reasons = normalize_string_list(row.get("reasons"), max_items=3)
    course_hints = normalize_string_list(row.get("course_hints"))
    notes = coerce_text(row.get("notes"))

    if legacy:
        category = row.get("category")
        if isinstance(category, str):
            category_normalized = category.strip().lower()
            event_type = LEGACY_CATEGORY_TO_EVENT.get(category_normalized)
            if category_normalized not in LEGACY_CATEGORY_TO_EVENT:
                event_type = None
                unmapped_event_type = True
        else:
            event_type = None
        candidates = normalize_legacy_candidates(row.get("candidates"))
        legacy_hints = normalize_string_list([candidate.get("course_hint") for candidate in candidates])
        course_hints = merge_course_hints(course_hints, legacy_hints)
        action_items = build_legacy_action_items(candidates)
        raw_extract = build_legacy_raw_extract(candidates)
    else:
        event_type, unmapped_event_type = normalize_event_type(row.get("event_type"))
        action_items, _ = normalize_action_items(
            row.get("action_items"),
            max_action_items=max_action_items,
            line_number=line_number,
            email_id=email_id,
            error_rows=error_rows,
        )
        raw_extract = normalize_raw_extract(row.get("raw_extract"))

    action_items, truncated_count = normalize_action_items(
        action_items,
        max_action_items=max_action_items,
        line_number=line_number,
        email_id=email_id,
        error_rows=error_rows,
    )

    if label == "DROP":
        event_type = None
        action_items = []

    if label == "KEEP" and event_type is None:
        append_error(
            error_rows,
            line_number=line_number,
            email_id=email_id,
            error_type="invalid_enum",
            message="KEEP row has event_type=null after normalization",
        )

    rescue_reason: str | None = None
    if label == "KEEP":
        if event_type is None:
            rescue_reason = "event_type_null"
        elif len(action_items) == 0:
            text_blob = " ".join(
                item
                for item in [
                    " ".join(reasons),
                    raw_extract.get("deadline_text") or "",
                    raw_extract.get("time_text") or "",
                    raw_extract.get("location_text") or "",
                    notes or "",
                ]
                if item
            )
            if RESCUE_SCHEDULE_HINT_RE.search(text_blob):
                rescue_reason = "schedule_signal_without_action_items"

    normalized = {
        "email_id": email_id,
        "label": label,
        "confidence": confidence,
        "reasons": reasons[:3],
        "course_hints": course_hints,
        "event_type": event_type,
        "action_items": action_items,
        "raw_extract": raw_extract,
        "notes": notes,
    }
    if truncated_count > 0:
        append_error(
            error_rows,
            line_number=line_number,
            email_id=email_id,
            error_type="coercion_warning",
            message=f"action_items exceeded max and was truncated by {truncated_count}",
        )
    return normalized, rescue_reason is not None, rescue_reason, unmapped_event_type


def dedupe_rows(rows: list[NormalizedRow]) -> tuple[list[NormalizedRow], int]:
    deduped: dict[str, NormalizedRow] = {}
    duplicates = 0

    for row in rows:
        email_id = row.payload["email_id"]
        existing = deduped.get(email_id)
        if existing is None:
            deduped[email_id] = row
            continue

        duplicates += 1
        existing_conf = float(existing.payload["confidence"])
        incoming_conf = float(row.payload["confidence"])
        if incoming_conf > existing_conf:
            deduped[email_id] = row
            continue
        if incoming_conf < existing_conf:
            continue

        existing_label = str(existing.payload["label"])
        incoming_label = str(row.payload["label"])
        if existing_label != incoming_label:
            if incoming_label == "KEEP":
                deduped[email_id] = row
            continue

        if row.line_number > existing.line_number:
            deduped[email_id] = row

    ordered = sorted(deduped.values(), key=lambda item: item.line_number)
    return ordered, duplicates


def _truncate_head_tail(value: str, limit: int = 1500) -> str:
    if len(value) <= limit:
        return value
    head = limit // 2
    tail = limit - head - 20
    return value[:head] + " ...[TRUNCATED]... " + value[-tail:]


def build_rescue_prompt(entry: NormalizedRow) -> str:
    payload = entry.payload
    source = entry.source_row
    email_id = payload["email_id"]

    from_field = coerce_text(source.get("from"))
    subject = coerce_text(source.get("subject")) or coerce_text(source.get("item_title_hint"))
    body_text = coerce_text(source.get("body_text"))
    reasons = ", ".join(payload.get("reasons", []))
    raw_extract = payload.get("raw_extract", {})
    raw_bits = [
        coerce_text(raw_extract.get("deadline_text")),
        coerce_text(raw_extract.get("time_text")),
        coerce_text(raw_extract.get("location_text")),
    ]

    fallback_source = []
    candidates = source.get("candidates")
    if isinstance(candidates, list):
        for candidate in candidates[:3]:
            if isinstance(candidate, dict):
                spans = candidate.get("evidence_spans")
                if isinstance(spans, list):
                    for item in spans[:2]:
                        text = coerce_text(item)
                        if text:
                            fallback_source.append(text)
    fallback = " | ".join(item for item in fallback_source if item)
    context = body_text or " ".join(item for item in [reasons, *raw_bits, fallback] if item)
    context = _truncate_head_tail(context, limit=1500) if context else "n/a"

    return (
        "Return exactly one TAB-separated line in this format:\n"
        "email_id<TAB>label<TAB>confidence<TAB>event_type<TAB>course_hints_csv<TAB>notes\n"
        "Rules: label must be KEEP or DROP; confidence in [0,1]; event_type in "
        "deadline|exam|schedule_change|assignment|grade|action_required|announcement|other|null.\n"
        f"email_id={email_id}\n"
        f"from={from_field or 'n/a'}\n"
        f"subject={subject or 'n/a'}\n"
        f"context={context}"
    )


def parse_rescue_line(line: str) -> RescueDecision:
    parts = line.split("\t")
    if len(parts) < 6:
        raise ValueError("rescue line must contain 6 TAB-separated fields")

    email_id = parts[0].strip()
    raw_label = parts[1].strip().upper()
    if raw_label not in {"KEEP", "DROP"}:
        raise ValueError(f"invalid rescue label: {parts[1]!r}")
    label = raw_label
    confidence = clamp_confidence(parts[2])
    event_raw = parts[3].strip()
    if not event_raw or event_raw.lower() == "null":
        event_type = None
    else:
        mapped, unmapped = normalize_event_type(event_raw)
        if unmapped or mapped is None:
            raise ValueError(f"invalid rescue event_type: {event_raw!r}")
        event_type = mapped

    course_hints = normalize_string_list([item.strip() for item in parts[4].split(",") if item.strip()])
    notes = coerce_text(parts[5])
    return RescueDecision(
        email_id=email_id,
        label=label,
        confidence=confidence,
        event_type=event_type,
        course_hints=course_hints,
        notes=notes,
    )


async def call_rescue_batch(
    *,
    client: httpx.AsyncClient,
    config: RescueConfig,
    inputs: list[str],
) -> str:
    assert config.base_url is not None
    url = config.base_url.rstrip("/") + config.path
    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    response = await client.post(url, json={"model": config.model, "inputs": inputs}, headers=headers)
    response.raise_for_status()
    return response.text


async def apply_rescue(
    *,
    rows: list[NormalizedRow],
    rescue_config: RescueConfig,
    error_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not rescue_config.enabled:
        return []

    candidates = [row for row in rows if row.rescue_candidate]
    if not candidates:
        return []

    applied_rows: list[dict[str, Any]] = []
    semaphore = asyncio.Semaphore(rescue_config.concurrency)
    timeout = httpx.Timeout(rescue_config.timeout_seconds)

    async with httpx.AsyncClient(timeout=timeout) as client:
        async def _handle_batch(batch: list[NormalizedRow]) -> None:
            async with semaphore:
                prompts = [build_rescue_prompt(entry) for entry in batch]
                try:
                    raw = await call_rescue_batch(client=client, config=rescue_config, inputs=prompts)
                except Exception as exc:
                    for item in batch:
                        append_error(
                            error_rows,
                            line_number=item.line_number,
                            email_id=str(item.payload.get("email_id", "unknown")),
                            error_type="rescue_failed",
                            message=f"request_failed: {exc}",
                        )
                    return

                lines = [line for line in raw.splitlines() if line.strip()]
                if len(lines) != len(batch):
                    for item in batch:
                        append_error(
                            error_rows,
                            line_number=item.line_number,
                            email_id=str(item.payload.get("email_id", "unknown")),
                            error_type="rescue_failed",
                            message=f"line_count_mismatch expected={len(batch)} got={len(lines)}",
                        )
                    return

                for entry, line in zip(batch, lines):
                    try:
                        decision = parse_rescue_line(line)
                    except Exception as exc:
                        append_error(
                            error_rows,
                            line_number=entry.line_number,
                            email_id=str(entry.payload.get("email_id", "unknown")),
                            error_type="rescue_failed",
                            message=f"parse_failed: {exc}",
                        )
                        continue

                    expected_email_id = str(entry.payload.get("email_id"))
                    if decision.email_id and decision.email_id != expected_email_id:
                        append_error(
                            error_rows,
                            line_number=entry.line_number,
                            email_id=expected_email_id,
                            error_type="rescue_failed",
                            message=f"email_id_mismatch expected={expected_email_id} got={decision.email_id}",
                        )
                        continue

                    before_event = entry.payload.get("event_type")
                    before_label = entry.payload.get("label")
                    entry.payload["label"] = decision.label
                    entry.payload["confidence"] = decision.confidence
                    entry.payload["event_type"] = decision.event_type
                    entry.payload["course_hints"] = merge_course_hints(
                        normalize_string_list(entry.payload.get("course_hints")),
                        decision.course_hints,
                    )
                    if decision.label == "DROP":
                        entry.payload["action_items"] = []
                        entry.payload["event_type"] = None
                    if coerce_text(entry.payload.get("notes")) is None:
                        entry.payload["notes"] = decision.notes or "rescued by LLM"

                    applied_rows.append(
                        {
                            "email_id": expected_email_id,
                            "before_event_type": before_event,
                            "after_event_type": entry.payload.get("event_type"),
                            "before_label": before_label,
                            "after_label": entry.payload.get("label"),
                            "rescue_confidence": decision.confidence,
                        }
                    )

        batches: list[list[NormalizedRow]] = []
        batch_size = rescue_config.batch_size
        for start in range(0, len(candidates), batch_size):
            batches.append(candidates[start : start + batch_size])
        await asyncio.gather(*(_handle_batch(batch) for batch in batches))

    return applied_rows


def finalize_and_validate(
    *,
    rows: list[NormalizedRow],
    validator: Draft202012Validator,
    error_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        payload = row.payload
        missing = sorted(REQUIRED_KEYS - set(payload.keys()))
        if missing:
            append_error(
                error_rows,
                line_number=row.line_number,
                email_id=str(payload.get("email_id", "unknown")),
                error_type="missing_required",
                message=f"missing keys: {missing}",
            )
            continue

        extra = sorted(set(payload.keys()) - REQUIRED_KEYS)
        if extra:
            append_error(
                error_rows,
                line_number=row.line_number,
                email_id=str(payload.get("email_id", "unknown")),
                error_type="invalid_enum",
                message=f"extra keys present: {extra}",
            )
            continue

        if payload.get("label") == "DROP":
            payload["action_items"] = []
            payload["event_type"] = None

        try:
            validator.validate(payload)
        except Exception as exc:
            append_error(
                error_rows,
                line_number=row.line_number,
                email_id=str(payload.get("email_id", "unknown")),
                error_type="schema_validation",
                message=str(exc),
            )
            continue

        out.append(payload)
    return out


def run_normalization_pipeline(config: NormalizeConfig) -> dict[str, Any]:
    schema = json.loads(config.schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    rescue_config = load_rescue_config(enabled_from_cli=config.rescue_llm)

    error_rows: list[dict[str, Any]] = []
    normalized_rows: list[NormalizedRow] = []

    total_in = 0
    action_items_truncated_count = 0

    for line_number, line in iter_jsonl_lines(config.input_path):
        total_in += 1
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            append_error(
                error_rows,
                line_number=line_number,
                email_id="unknown",
                error_type="json_parse",
                message=str(exc),
            )
            continue

        if not isinstance(raw, dict):
            append_error(
                error_rows,
                line_number=line_number,
                email_id="unknown",
                error_type="json_parse",
                message="line is not a JSON object",
            )
            continue

        original_keys = sorted([str(key) for key in raw.keys()])
        normalized, rescue_candidate, rescue_reason, unmapped_event = normalize_row(
            row=raw,
            line_number=line_number,
            max_action_items=config.max_action_items,
            error_rows=error_rows,
        )
        if len(normalized.get("action_items", [])) >= config.max_action_items and isinstance(raw.get("action_items"), list):
            if len(raw.get("action_items", [])) > config.max_action_items:
                action_items_truncated_count += 1

        if unmapped_event:
            append_error(
                error_rows,
                line_number=line_number,
                email_id=normalized.get("email_id", "unknown"),
                error_type="invalid_enum",
                message="event_type could not be mapped and was set to null",
                original_keys=original_keys,
            )

        normalized_rows.append(
            NormalizedRow(
                line_number=line_number,
                payload=normalized,
                source_row=raw,
                rescue_candidate=rescue_candidate,
                rescue_reason=rescue_reason,
                unmapped_event_type=unmapped_event,
            )
        )

    dedupe_count = 0
    if config.dedupe:
        normalized_rows, dedupe_count = dedupe_rows(normalized_rows)

    rescue_applied_rows: list[dict[str, Any]] = []
    if rescue_config.enabled:
        rescue_applied_rows = asyncio.run(
            apply_rescue(
                rows=normalized_rows,
                rescue_config=rescue_config,
                error_rows=error_rows,
            )
        )

    final_rows = finalize_and_validate(rows=normalized_rows, validator=validator, error_rows=error_rows)

    write_jsonl(config.output_path, final_rows)
    write_jsonl(config.errors_path, error_rows)
    write_jsonl(config.rescue_out_path, rescue_applied_rows)

    rescue_candidate_count = sum(1 for row in normalized_rows if row.rescue_candidate)

    summary = {
        "input_path": str(config.input_path),
        "output_path": str(config.output_path),
        "errors_path": str(config.errors_path),
        "rescue_out_path": str(config.rescue_out_path),
        "timezone": config.timezone,
        "total_in": total_in,
        "parsed_rows": len(normalized_rows),
        "normalized_out": len(final_rows),
        "error_count": len(error_rows),
        "rescue_enabled": rescue_config.enabled,
        "rescue_candidate_count": rescue_candidate_count,
        "rescue_applied_count": len(rescue_applied_rows),
        "dedupe_count": dedupe_count,
        "action_items_truncated_count": action_items_truncated_count,
    }
    return summary


def main() -> int:
    try:
        args = parse_args()
        config = build_config(args)
        summary = run_normalization_pipeline(config)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"error": sanitize_log_text(str(exc))}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
