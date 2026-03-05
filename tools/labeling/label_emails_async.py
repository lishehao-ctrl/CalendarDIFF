#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import hashlib
import html
import importlib
import json
import logging
import mailbox
import os
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterator

import httpx
from jsonschema import Draft202012Validator

try:
    openai_module = importlib.import_module("openai")
except ImportError:  # pragma: no cover - runtime guard only
    OpenAIAsyncClient: Any = None
else:
    OpenAIAsyncClient = getattr(openai_module, "AsyncOpenAI", None)
AsyncOpenAI = OpenAIAsyncClient

try:
    from tools.labeling.json_enforcer import (
        build_repair_prompt,
        collect_validation_errors,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    json_enforcer_module = importlib.import_module("tools.labeling.json_enforcer")
    build_repair_prompt = json_enforcer_module.build_repair_prompt
    collect_validation_errors = json_enforcer_module.collect_validation_errors

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA_PATH = ROOT_DIR / "tools" / "labeling" / "schema" / "email_label.json"
DEFAULT_PROMPT_PATH = ROOT_DIR / "tools" / "labeling" / "prompts" / "system.txt"
DEFAULT_TOOL_ENV_PATH = ROOT_DIR / "tools" / "labeling" / ".env"
DEFAULT_TZ = "America/Los_Angeles"
TOOL_VERSION = "2.0.0"

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
URL_RE = re.compile(r"https?://[^\s)>\"']+")
TOKEN_RE = re.compile(r"\b(?:sk|rk|tok|token|apikey|api_key)[-_A-Za-z0-9]{8,}\b", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<[^>]+>")

logger = logging.getLogger("label_emails_async")


@dataclass(frozen=True)
class EmailRecord:
    email_id: str
    from_field: str | None
    subject: str | None
    date: str | None
    body_text: str


@dataclass(frozen=True)
class LabelingConfig:
    openai_api_key: str
    openai_model: str
    openai_base_url: str | None
    input_mbox: Path
    labeled_jsonl: Path
    error_jsonl: Path
    workers: int
    max_retries: int
    max_body_chars: int
    max_output_tokens: int
    temperature: float
    max_records: int | None
    dry_run: bool
    prompt_path: Path
    schema_path: Path


def parse_env_line(raw_line: str) -> tuple[str, str] | None:
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line[len("export ") :].strip()
    if "=" not in line:
        return None
    key, value = line.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not key:
        return None
    if value and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return key, value


def load_env_file(env_path: Path) -> int:
    if not env_path.is_file():
        return 0
    loaded = 0
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        parsed = parse_env_line(raw_line)
        if parsed is None:
            continue
        key, value = parsed
        if key in os.environ:
            continue
        os.environ[key] = value
        loaded += 1
    return loaded


def parse_positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be > 0, got {value}")
    return value


def parse_float_env(name: str, default: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a float, got {raw!r}") from exc
    if value < minimum or value > maximum:
        raise RuntimeError(f"{name} must be in [{minimum}, {maximum}], got {value}")
    return value


def parse_optional_positive_int_env(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be > 0, got {value}")
    return value


def sanitize_log_text(raw: str) -> str:
    text = TOKEN_RE.sub("<REDACTED_TOKEN>", raw)
    text = EMAIL_RE.sub("<REDACTED_EMAIL>", text)

    def _replace_url(match: re.Match[str]) -> str:
        value = match.group(0)
        try:
            parsed = httpx.URL(value)
            scheme = parsed.scheme or "https"
            host = parsed.host or "unknown-host"
            return f"{scheme}://{host}/<REDACTED_PATH>"
        except Exception:
            return "<REDACTED_URL>"

    return URL_RE.sub(_replace_url, text)


def truncate_body_text(body_text: str, max_chars: int, head_chars: int = 8000, tail_chars: int = 3500) -> str:
    if len(body_text) <= max_chars:
        return body_text
    if max_chars <= 64:
        return body_text[:max_chars]

    head = min(head_chars, max_chars // 2)
    tail = min(tail_chars, max_chars - head - 1)

    while head + tail >= max_chars:
        if tail > 0:
            tail -= 1
        else:
            head -= 1

    omitted = max(0, len(body_text) - head - tail)
    marker = f"\n...[TRUNCATED {omitted} CHARS]...\n"
    while head + tail + len(marker) > max_chars and (tail > 0 or head > 0):
        if tail > 0:
            tail -= 1
        elif head > 0:
            head -= 1
        omitted = max(0, len(body_text) - head - tail)
        marker = f"\n...[TRUNCATED {omitted} CHARS]...\n"

    if omitted <= 0:
        return body_text[:max_chars]
    if tail > 0:
        return body_text[:head] + marker + body_text[-tail:]
    return body_text[:head] + marker


def load_json_schema(schema_path: Path) -> dict[str, Any]:
    if not schema_path.is_file():
        raise RuntimeError(f"Schema file not found: {schema_path}")
    payload = json.loads(schema_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Schema file must contain a JSON object.")
    return payload


def load_system_prompt(prompt_path: Path) -> str:
    if not prompt_path.is_file():
        raise RuntimeError(f"System prompt file not found: {prompt_path}")
    content = prompt_path.read_text(encoding="utf-8").strip()
    if not content:
        raise RuntimeError("System prompt file is empty.")
    return content


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    ensure_parent_dir(path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def iter_jsonl(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"Line {line_number} must be a JSON object.")
            yield line_number, payload


def load_processed_email_ids(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    processed: set[str] = set()
    for _, payload in iter_jsonl(path):
        value = payload.get("email_id")
        if isinstance(value, str) and value.strip():
            processed.add(value.strip())
    return processed


def decode_mime_text(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        decoded = str(make_header(decode_header(value)))
        return decoded.strip() or None
    except Exception:
        fallback = value.strip()
        return fallback or None


def normalize_email_date(value: str | None) -> str | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.isoformat()
    except Exception:
        return raw


def strip_html_tags(value: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    text = HTML_TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def decode_message_part(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if isinstance(payload, (bytes, bytearray)):
        payload_bytes = bytes(payload)
    else:
        payload_text = part.get_payload()
        if isinstance(payload_text, str):
            return payload_text
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload_bytes.decode(charset, errors="replace")
    except Exception:
        return payload_bytes.decode("utf-8", errors="replace")


def extract_body_text_from_message(message: Message) -> str:
    plain_parts: list[str] = []
    html_parts: list[str] = []

    if message.is_multipart():
        for part in message.walk():
            if part.get_content_maintype() == "multipart":
                continue
            disposition = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disposition:
                continue
            content_type = (part.get_content_type() or "").lower()
            content = decode_message_part(part).strip()
            if not content:
                continue
            if content_type == "text/plain":
                plain_parts.append(content)
            elif content_type == "text/html":
                html_parts.append(content)
    else:
        content_type = (message.get_content_type() or "").lower()
        content = decode_message_part(message).strip()
        if content:
            if content_type == "text/html":
                html_parts.append(content)
            else:
                plain_parts.append(content)

    if plain_parts:
        return "\n\n".join(plain_parts).strip()
    if html_parts:
        return strip_html_tags("\n\n".join(html_parts))
    return ""


def derive_mbox_email_id(message: Message, index: int, body_text: str) -> str:
    message_id = decode_mime_text(message.get("Message-ID"))
    if message_id:
        cleaned = message_id.strip().strip("<>").strip()
        if cleaned:
            return cleaned

    from_field = decode_mime_text(message.get("From")) or ""
    subject = decode_mime_text(message.get("Subject")) or ""
    date_value = normalize_email_date(message.get("Date")) or ""
    fingerprint = f"{index}|{from_field}|{subject}|{date_value}|{body_text[:240]}"
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]
    return f"mbox-{index}-{digest}"


def build_error_record(
    *,
    email_id: str,
    error_type: str,
    message: str,
    model_name: str | None,
    retry_count: int = 0,
    status_code: int | None = None,
) -> dict[str, Any]:
    return {
        "email_id": email_id,
        "error_type": error_type,
        "status_code": status_code,
        "retry_count": retry_count,
        "message_sanitized": sanitize_log_text(message)[:1200],
        "_failed_at": datetime.now(timezone.utc).isoformat(),
        "_model": model_name,
    }


def read_mbox_input_emails(path: Path, skip_ids: set[str]) -> tuple[list[EmailRecord], list[dict[str, Any]]]:
    if path.suffix.lower() not in {".mbox", ".mbx"}:
        raise RuntimeError(f"Input must be an mbox file (.mbox/.mbx), got: {path}")
    if not path.is_file():
        raise RuntimeError(f"Input mbox not found: {path}")

    records: list[EmailRecord] = []
    preflight_errors: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    mbox = mailbox.mbox(str(path), factory=None, create=False)
    try:
        for index, message in enumerate(mbox, start=1):
            if not isinstance(message, Message):
                preflight_errors.append(
                    build_error_record(
                        email_id=f"mbox-{index}",
                        error_type="input_validation_error",
                        message="mbox entry is not a valid email message",
                        model_name=None,
                    )
                )
                continue

            body_text = extract_body_text_from_message(message)
            email_id = derive_mbox_email_id(message, index=index, body_text=body_text)
            if email_id in seen_ids:
                preflight_errors.append(
                    build_error_record(
                        email_id=email_id,
                        error_type="input_duplicate_email_id",
                        message="duplicate message id detected in mbox input",
                        model_name=None,
                    )
                )
                continue
            seen_ids.add(email_id)

            if email_id in skip_ids:
                continue

            records.append(
                EmailRecord(
                    email_id=email_id,
                    from_field=decode_mime_text(message.get("From")),
                    subject=decode_mime_text(message.get("Subject")),
                    date=normalize_email_date(message.get("Date")),
                    body_text=body_text,
                )
            )
    finally:
        mbox.close()

    return records, preflight_errors


def _as_mapping(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        if isinstance(dumped, dict):
            return dumped
    return None


def _extract_text_from_content_item(content_item: Any) -> str | None:
    if isinstance(content_item, str):
        stripped = content_item.strip()
        return stripped if stripped else None

    item = _as_mapping(content_item)
    if item is None:
        return None

    for key in ("text", "output_text", "value", "content"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value
        nested = _as_mapping(value)
        if nested:
            nested_value = nested.get("value")
            if isinstance(nested_value, str) and nested_value.strip():
                return nested_value
    return None


def _extract_from_output_items(output_items: Any) -> str | None:
    if not isinstance(output_items, list):
        return None
    for output_item in output_items:
        mapped = _as_mapping(output_item)
        if mapped:
            content = mapped.get("content")
            if isinstance(content, list):
                for content_item in content:
                    extracted = _extract_text_from_content_item(content_item)
                    if extracted:
                        return extracted
            for key in ("text", "output_text"):
                value = mapped.get(key)
                if isinstance(value, str) and value.strip():
                    return value
        else:
            content = getattr(output_item, "content", None)
            if isinstance(content, list):
                for content_item in content:
                    extracted = _extract_text_from_content_item(content_item)
                    if extracted:
                        return extracted
    return None


def extract_responses_text(response: Any) -> str:
    mapped = _as_mapping(response)
    if mapped:
        output_text = mapped.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text
        if isinstance(output_text, list):
            for item in output_text:
                if isinstance(item, str) and item.strip():
                    return item
        extracted = _extract_from_output_items(mapped.get("output"))
        if extracted:
            return extracted

    output_text_attr = getattr(response, "output_text", None)
    if isinstance(output_text_attr, str) and output_text_attr.strip():
        return output_text_attr
    if isinstance(output_text_attr, list):
        for item in output_text_attr:
            if isinstance(item, str) and item.strip():
                return item

    extracted = _extract_from_output_items(getattr(response, "output", None))
    if extracted:
        return extracted

    keys = sorted(mapped.keys()) if mapped else []
    raise RuntimeError(f"Responses payload did not contain parseable text. keys={keys[:12]}")


def _extract_exception_status_code(exc: Exception) -> int | None:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    if isinstance(response_status, int):
        return response_status
    return None


def classify_exception(exc: Exception) -> tuple[bool, int | None, str]:
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError, TimeoutError, ConnectionError)):
        return True, None, "network_error"

    status_code = _extract_exception_status_code(exc)
    if isinstance(status_code, int):
        if status_code == 429 or status_code >= 500:
            return True, status_code, "api_retryable_error"
        if 400 <= status_code < 500:
            return False, status_code, "api_client_error"
    return False, status_code, "unexpected_error"


def compute_backoff_seconds(attempt_index: int) -> float:
    base = 1.0
    max_delay = 20.0
    jitter = random.uniform(0.0, 0.35)
    return min(max_delay, base * (2**attempt_index)) + jitter


def build_prompt_payload(record: EmailRecord, max_body_chars: int) -> dict[str, Any]:
    return {
        "email_id": record.email_id,
        "from": record.from_field,
        "subject": record.subject,
        "date": record.date,
        "body_text": truncate_body_text(record.body_text, max_chars=max_body_chars),
        "default_timezone": DEFAULT_TZ,
    }


def build_labeling_prompt(system_prompt: str, payload: dict[str, Any]) -> str:
    return (
        f"{system_prompt}\n\n"
        "Now label this email payload. Output EXACTLY one JSON object, no markdown.\n\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )


async def call_responses_text(
    *,
    client: Any,
    model_name: str,
    prompt_text: str,
    temperature: float,
    max_output_tokens: int,
) -> tuple[str, str]:
    response = await client.responses.create(
        model=model_name,
        store=False,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        input=[
            {
                "role": "user",
                "content": [{"type": "input_text", "text": prompt_text}],
            }
        ],
    )
    raw_text = extract_responses_text(response)
    response_model = getattr(response, "model", None)
    used_model = response_model if isinstance(response_model, str) and response_model else model_name
    return raw_text, used_model


async def call_responses_with_retry(
    *,
    client: Any,
    model_name: str,
    prompt_text: str,
    temperature: float,
    max_output_tokens: int,
    max_retries: int,
) -> tuple[str, str]:
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return await call_responses_text(
                client=client,
                model_name=model_name,
                prompt_text=prompt_text,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )
        except Exception as exc:
            last_exc = exc
            retryable, _, _ = classify_exception(exc)
            if retryable and attempt < max_retries:
                await asyncio.sleep(compute_backoff_seconds(attempt))
                continue
            raise
    assert last_exc is not None  # pragma: no cover
    raise last_exc


async def label_single_email(
    *,
    record: EmailRecord,
    client: Any,
    config: LabelingConfig,
    validator: Draft202012Validator,
    schema: dict[str, Any],
    system_prompt: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    payload = build_prompt_payload(record, max_body_chars=config.max_body_chars)
    prompt_text = build_labeling_prompt(system_prompt, payload)

    used_model: str = config.openai_model
    try:
        raw_output, used_model = await call_responses_with_retry(
            client=client,
            model_name=config.openai_model,
            prompt_text=prompt_text,
            temperature=config.temperature,
            max_output_tokens=config.max_output_tokens,
            max_retries=config.max_retries,
        )
    except Exception as exc:
        return None, build_error_record(
            email_id=record.email_id,
            error_type="label_call_failed",
            message=str(exc),
            model_name=config.openai_model,
            status_code=_extract_exception_status_code(exc),
            retry_count=config.max_retries,
        )

    max_repair_rounds = 2
    current_output = raw_output
    all_validation_errors: list[str] = []

    for round_index in range(max_repair_rounds + 1):
        normalized, validation_errors = collect_validation_errors(
            raw_text=current_output,
            email_id=record.email_id,
            validator=validator,
        )
        if normalized is not None:
            return normalized, None

        if validation_errors:
            all_validation_errors.extend(validation_errors)

        if round_index == max_repair_rounds:
            break

        repair_prompt = build_repair_prompt(
            bad_output=current_output,
            schema=schema,
            validation_errors=validation_errors,
        )
        try:
            current_output, used_model = await call_responses_with_retry(
                client=client,
                model_name=config.openai_model,
                prompt_text=repair_prompt,
                temperature=config.temperature,
                max_output_tokens=config.max_output_tokens,
                max_retries=config.max_retries,
            )
        except Exception as repair_exc:
            return None, build_error_record(
                email_id=record.email_id,
                error_type="json_repair_call_failed",
                message=(
                    f"repair_round={round_index + 1}; "
                    f"validation_errors={all_validation_errors[:8]}; "
                    f"repair_error={repair_exc}"
                ),
                model_name=used_model,
                status_code=_extract_exception_status_code(repair_exc),
                retry_count=config.max_retries,
            )

    return None, build_error_record(
        email_id=record.email_id,
        error_type="json_invalid_after_repair",
        message=f"validation_errors={all_validation_errors[:12]}",
        model_name=used_model,
        retry_count=0,
        status_code=None,
    )


async def run_labeling_pipeline(config: LabelingConfig) -> dict[str, Any]:
    if OpenAIAsyncClient is None:
        raise RuntimeError("openai package is not installed. Install dependencies before running this script.")

    schema = load_json_schema(config.schema_path)
    validator = Draft202012Validator(schema)
    system_prompt = load_system_prompt(config.prompt_path)
    prompt_sha = hash_text(system_prompt)

    processed_ids = load_processed_email_ids(config.labeled_jsonl)
    records, preflight_errors = read_mbox_input_emails(config.input_mbox, skip_ids=processed_ids)

    if config.max_records is not None:
        records = records[: config.max_records]

    summary: dict[str, Any] = {
        "input_path": str(config.input_mbox),
        "output_path": str(config.labeled_jsonl),
        "error_path": str(config.error_jsonl),
        "dry_run": config.dry_run,
        "skipped_existing": len(processed_ids),
        "preflight_errors": len(preflight_errors),
        "planned_records": len(records),
        "tool_version": TOOL_VERSION,
        "prompt_sha256": prompt_sha,
    }

    if config.dry_run:
        summary["preview_email_ids"] = [item.email_id for item in records[:5]]
        return summary

    for item in preflight_errors:
        append_jsonl(config.error_jsonl, item)

    client = OpenAIAsyncClient(api_key=config.openai_api_key, base_url=config.openai_base_url)
    semaphore = asyncio.Semaphore(config.workers)
    write_lock = asyncio.Lock()
    start_time = time.monotonic()

    success_count = 0
    invalid_dropped_count = 0
    error_count = len(preflight_errors)

    async def _worker(record: EmailRecord) -> None:
        nonlocal success_count, invalid_dropped_count, error_count
        async with semaphore:
            label, error = await label_single_email(
                record=record,
                client=client,
                config=config,
                validator=validator,
                schema=schema,
                system_prompt=system_prompt,
            )

        async with write_lock:
            if label is not None:
                append_jsonl(config.labeled_jsonl, label)
                success_count += 1
                logger.info("labeled email_id=%s label=%s", record.email_id, label.get("label"))
            if error is not None:
                if error.get("error_type") in {"json_invalid_after_repair", "json_repair_call_failed"}:
                    invalid_dropped_count += 1
                error_count += 1
                append_jsonl(config.error_jsonl, error)
                logger.warning("excluded email_id=%s error_type=%s", record.email_id, error.get("error_type"))

    await asyncio.gather(*(_worker(record) for record in records))
    elapsed = round(time.monotonic() - start_time, 3)

    summary.update(
        {
            "processed": len(records),
            "success_count": success_count,
            "invalid_dropped_count": invalid_dropped_count,
            "error_count": error_count,
            "elapsed_seconds": elapsed,
        }
    )
    return summary


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def load_config_from_env() -> LabelingConfig:
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required.")

    input_mbox_raw = os.getenv("EMAILS_INPUT", "").strip()
    if not input_mbox_raw:
        raise RuntimeError("EMAILS_INPUT is required and must point to an mbox file.")

    return LabelingConfig(
        openai_api_key=openai_api_key,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5.3-codex").strip() or "gpt-5.3-codex",
        openai_base_url=os.getenv("OPENAI_BASE_URL", "").strip() or None,
        input_mbox=Path(input_mbox_raw),
        labeled_jsonl=Path(os.getenv("LABELED_JSONL", "data/labeled.jsonl")),
        error_jsonl=Path(os.getenv("ERROR_JSONL", "data/label_errors.jsonl")),
        workers=parse_positive_int_env("LABEL_CONCURRENCY", 10),
        max_retries=parse_positive_int_env("LABEL_MAX_RETRIES", 6),
        max_body_chars=parse_positive_int_env("LABEL_MAX_BODY_CHARS", 12000),
        max_output_tokens=parse_positive_int_env("LABEL_MAX_OUTPUT_TOKENS", 600),
        temperature=parse_float_env("LABEL_TEMPERATURE", 0.2, minimum=0.0, maximum=0.3),
        max_records=parse_optional_positive_int_env("LABEL_MAX_RECORDS"),
        dry_run=(os.getenv("LABEL_DRY_RUN", "").strip().lower() in {"1", "true", "yes"}),
        prompt_path=Path(os.getenv("EMAIL_LABEL_PROMPT", str(DEFAULT_PROMPT_PATH))),
        schema_path=Path(os.getenv("EMAIL_LABEL_SCHEMA", str(DEFAULT_SCHEMA_PATH))),
    )


def main() -> int:
    configure_logging()
    try:
        env_file = Path(os.getenv("LABELING_ENV_FILE", str(DEFAULT_TOOL_ENV_PATH)))
        loaded_count = load_env_file(env_file)
        if loaded_count > 0:
            logger.info("loaded_env_file path=%s keys=%s", env_file, loaded_count)

        config = load_config_from_env()
        summary = asyncio.run(run_labeling_pipeline(config))
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        logger.error("pipeline_failed error=%s", sanitize_log_text(str(exc)))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
