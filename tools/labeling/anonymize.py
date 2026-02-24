#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse

EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
URL_PATTERN = re.compile(r"https?://[^\s)>\"']+")
GREETING_NAME_PATTERN = re.compile(r"\b(Hi|Hello|Dear)\s+([A-Z][a-z]{1,30})\b")
SIGNOFF_NAME_PATTERN = re.compile(r"\b(Thanks|Regards|Sincerely|Best),\s+([A-Z][a-z]{1,30})\b")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Anonymize emails.jsonl for offline labeling runs.")
    parser.add_argument(
        "--input",
        default=os.getenv("ANON_INPUT_JSONL", "data/emails.jsonl"),
        help="Input JSONL path (default: data/emails.jsonl or ANON_INPUT_JSONL).",
    )
    parser.add_argument(
        "--output",
        default=os.getenv("ANON_OUTPUT_JSONL", "data/anonymized_emails.jsonl"),
        help="Output JSONL path (default: data/anonymized_emails.jsonl or ANON_OUTPUT_JSONL).",
    )
    return parser.parse_args()


def short_hash(value: str, length: int = 10) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def anonymize_email(value: str) -> str:
    token = short_hash(value.lower(), length=8)
    return f"<EMAIL_HASH_{token}>"


def anonymize_url(value: str) -> str:
    parsed = urlparse(value)
    domain = parsed.netloc.lower() or "unknown-domain"
    path_key = f"{parsed.path}?{parsed.query}"
    path_hash = short_hash(path_key, length=8)
    return f"{parsed.scheme}://{domain}/<PATH_HASH_{path_hash}>"


def anonymize_text(text: str) -> str:
    updated = EMAIL_PATTERN.sub(lambda m: anonymize_email(m.group(0)), text)
    updated = URL_PATTERN.sub(lambda m: anonymize_url(m.group(0)), updated)
    updated = GREETING_NAME_PATTERN.sub(lambda m: f"{m.group(1)} <NAME>", updated)
    updated = SIGNOFF_NAME_PATTERN.sub(lambda m: f"{m.group(1)}, <NAME>", updated)
    return updated


def anonymize_record(record: dict[str, object]) -> dict[str, object]:
    output = dict(record)
    from_value = output.get("from")
    subject_value = output.get("subject")
    body_value = output.get("body_text")

    if isinstance(from_value, str):
        output["from"] = anonymize_text(from_value)
    if isinstance(subject_value, str):
        output["subject"] = anonymize_text(subject_value)
    if isinstance(body_value, str):
        output["body_text"] = anonymize_text(body_value)
    return output


def iter_jsonl(path: Path) -> Iterator[tuple[int, dict[str, object]]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {line_number}: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"Line {line_number} must be a JSON object.")
            yield line_number, payload


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.is_file():
        raise SystemExit(f"Input JSONL not found: {input_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    total_count = 0
    with output_path.open("w", encoding="utf-8") as output_handle:
        for _, payload in iter_jsonl(input_path):
            total_count += 1
            sanitized = anonymize_record(payload)
            output_handle.write(json.dumps(sanitized, ensure_ascii=False) + "\n")

    print(
        json.dumps(
            {
                "input": str(input_path),
                "output": str(output_path),
                "records_processed": total_count,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
